"""Web Push (VAPID) notifications to logged-in admins.

This service owns everything about sending browser push notifications: reading
the VAPID configuration, persisting/removing browser subscriptions, building the
payload, calling the Web Push protocol, and pruning subscriptions the push
service says are gone. Business code (lead_service, the CLI) only ever calls
``notify_all_admins`` / ``notify_user`` — it never touches the wire format.

Design (mirrors meta_service):
- Failures NEVER propagate to the caller. ``notify_*`` swallow and log every
  error, so a push outage can't break lead creation or a CLI run.
- A subscription the push service reports as gone (HTTP 404/410) is deleted, so
  dead browsers self-clean and we don't retry them forever.
- Push is a no-op unless it is enabled AND fully configured (both VAPID keys +
  a subject), so an empty/half-configured deployment behaves exactly as before.

SECRET HANDLING: VAPID_PRIVATE_KEY is a credential (see settings_service
SECRET_KEYS). It is read here to sign requests but never logged and never
rendered into a page.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from flask import current_app
from pywebpush import WebPushException, webpush

from app.extensions import db
from app.models import PushSubscription, User
from app.utils.logger import get_logger

logger = get_logger("app.push_service")

_DEFAULT_TIMEOUT = 10  # seconds; keep short so a slow push service never stalls


# --- config ---------------------------------------------------------------

def _config() -> dict[str, Any]:
    """Resolve the active Web Push settings from settings_service (DB, else env)."""
    from app.services import settings_service as s

    return {
        "enabled": s.get_bool(s.PUSH_ENABLED),
        "public_key": s.get_str(s.VAPID_PUBLIC_KEY).strip(),
        "private_key": s.get_str(s.VAPID_PRIVATE_KEY).strip(),
        "subject": s.get_str(s.VAPID_SUBJECT).strip(),
        "timeout": current_app.config.get("PUSH_TIMEOUT", _DEFAULT_TIMEOUT)
        if current_app
        else _DEFAULT_TIMEOUT,
    }


def is_configured() -> bool:
    """True when push is enabled and every VAPID value needed to send is present."""
    cfg = _config()
    return bool(
        cfg["enabled"] and cfg["public_key"] and cfg["private_key"] and cfg["subject"]
    )


def public_key() -> str:
    """The VAPID public key the browser needs to create a subscription."""
    return _config()["public_key"]


# --- subscription storage --------------------------------------------------

def save_subscription(
    user_id: int, subscription: dict, user_agent: Optional[str] = None
) -> PushSubscription:
    """Upsert a browser subscription for a user, keyed by its endpoint.

    ``subscription`` is the object the browser's PushManager returns:
    ``{"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}``. Re-subscribing
    the same browser updates the stored keys instead of creating a duplicate.
    Raises ValueError on a malformed payload (the route maps it to a 400).
    """
    endpoint = (subscription or {}).get("endpoint")
    keys = (subscription or {}).get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not endpoint or not p256dh or not auth:
        raise ValueError("Malformed push subscription payload.")

    row = db.session.scalar(
        db.select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if row is None:
        row = PushSubscription(endpoint=endpoint)
        db.session.add(row)
    # (Re)claim the subscription for this user and refresh its keys.
    row.user_id = user_id
    row.p256dh = p256dh
    row.auth = auth
    row.user_agent = (user_agent or "")[:512] or None
    db.session.commit()
    logger.info("Push subscription saved: user=%s id=%s", user_id, row.id)
    return row


def delete_subscription(user_id: int, endpoint: str) -> bool:
    """Remove a user's subscription by endpoint (on client unsubscribe).

    Scoped to the owning user so one admin can't delete another's row. Returns
    True if something was deleted.
    """
    row = db.session.scalar(
        db.select(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == user_id,
        )
    )
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    logger.info("Push subscription removed: user=%s", user_id)
    return True


def _delete_row(row: PushSubscription) -> None:
    """Best-effort delete of a single stale subscription row."""
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception:  # pragma: no cover - defensive; never break the caller
        db.session.rollback()
        logger.exception("Failed to prune stale push subscription id=%s", row.id)


# --- sending ---------------------------------------------------------------

def _send_one(row: PushSubscription, payload: dict, cfg: dict) -> bool:
    """Send one push. Returns True on success. Never raises.

    On 404/410 the endpoint is gone, so the row is pruned. Any other failure is
    logged and swallowed.
    """
    try:
        webpush(
            subscription_info={
                "endpoint": row.endpoint,
                "keys": {"p256dh": row.p256dh, "auth": row.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=cfg["private_key"],
            vapid_claims={"sub": cfg["subject"]},
            timeout=cfg["timeout"],
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            # Subscription expired/unsubscribed at the push service — prune it.
            logger.info("Pruning gone push subscription id=%s (%s)", row.id, status)
            _delete_row(row)
        else:
            logger.warning("Push send failed id=%s status=%s", row.id, status)
        return False
    except Exception:  # pragma: no cover - defensive catch-all
        logger.exception("Unexpected error sending push id=%s", row.id)
        return False


def _dispatch(rows: Iterable[PushSubscription], title: str, body: str, url: Optional[str]) -> dict:
    """Send a notification to every row. Never raises; returns a small summary."""
    result = {"sent": 0, "failed": 0}
    if not is_configured():
        # Enabled+configured gate: silently no-op otherwise (matches meta_service).
        return result

    cfg = _config()
    payload = {"title": title, "body": body}
    if url:
        payload["url"] = url

    for row in list(rows):
        if _send_one(row, payload, cfg):
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result


def notify_user(user_id: int, title: str, body: str, url: Optional[str] = None) -> dict:
    """Push to all of one user's subscribed browsers. Never raises."""
    try:
        rows = db.session.scalars(
            db.select(PushSubscription).where(PushSubscription.user_id == user_id)
        ).all()
        return _dispatch(rows, title, body, url)
    except Exception:  # pragma: no cover - defensive
        logger.exception("notify_user failed for user=%s", user_id)
        return {"sent": 0, "failed": 0}


def notify_all_admins(title: str, body: str, url: Optional[str] = None) -> dict:
    """Push to every subscription belonging to an active admin. Never raises.

    This is the entry point for the new-lead and follow-up-reminder triggers.
    """
    try:
        rows = db.session.scalars(
            db.select(PushSubscription)
            .join(User, User.id == PushSubscription.user_id)
            .where(User.is_active_flag.is_(True))
        ).all()
        return _dispatch(rows, title, body, url)
    except Exception:  # pragma: no cover - defensive
        logger.exception("notify_all_admins failed")
        return {"sent": 0, "failed": 0}
