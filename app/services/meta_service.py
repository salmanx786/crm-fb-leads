"""Meta (Facebook) Conversions API integration.

This service owns everything about talking to Meta: building the payload,
hashing PII, sending the HTTP request, persisting the attempt as a MetaEvent,
and retrying failures. Business code (lead_service) only ever calls
``track_event`` — it never builds a payload or knows Meta's wire format.

Design:
- Every attempt is a MetaEvent row, so nothing is ever lost. A send is
  created ``pending``, then flipped to ``sent`` or ``failed`` by save_result.
- Failures never propagate to the caller: track_event swallows and records
  them, so a Meta outage can't break lead creation.
- Retries reuse the stored event_id, which Meta uses for deduplication, so
  resending a partially-succeeded event is safe.

PII SAFETY: email and phone are SHA-256 hashed (hash_user_data) before they
ever enter a payload or the database. Raw email/phone are never logged and
never stored on the MetaEvent.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import requests
from flask import current_app

from app.constants import meta_event_for as _const_meta_event_for
from app.extensions import db
from app.models import Lead, MetaEvent
from app.utils.logger import get_logger

logger = get_logger("app.meta_service")

# Fallbacks used only if the config keys are somehow absent.
_DEFAULT_GRAPH_VERSION = "v19.0"
_DEFAULT_TIMEOUT = 10  # seconds; keep short so a slow Meta never stalls a request


# --- config helpers -------------------------------------------------------

def _config() -> dict[str, Any]:
    """Resolve the active Meta settings.

    Admin-editable values (enable toggle, pixel id, access token, test event
    code, country, source url) come from settings_service, which falls back to
    app.config / env when the dashboard has saved nothing. API version and
    timeout stay env-only — they are deployment details, not day-to-day knobs.
    """
    from app.services import settings_service as s

    return {
        "enabled": s.get_bool(s.META_ENABLED),
        "pixel_id": s.get_str(s.META_PIXEL_ID),
        "access_token": s.get_str(s.META_ACCESS_TOKEN),
        "test_event_code": s.get_str(s.META_TEST_EVENT_CODE),
        "api_version": current_app.config.get("META_API_VERSION", _DEFAULT_GRAPH_VERSION),
        "timeout": current_app.config.get("META_TIMEOUT", _DEFAULT_TIMEOUT),
        # 2-letter country used to hash a `country` identifier. Improves match
        # quality for a single-country audience.
        "default_country": s.get_str(s.META_DEFAULT_COUNTRY).strip(),
        # Absolute URL of the page the conversion happened on. Sent as
        # event_source_url when configured; omitted otherwise.
        "event_source_url": s.get_str(s.META_EVENT_SOURCE_URL).strip(),
    }


def _endpoint(pixel_id: str, api_version: str) -> str:
    return f"https://graph.facebook.com/{api_version}/{pixel_id}/events"


# --- hashing --------------------------------------------------------------

def _sha256(value: str) -> str:
    """Lowercase-trim-normalise then SHA-256 hash, per Meta's spec."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _normalise_phone(phone: str) -> str:
    """Digits only (Meta expects a normalised number before hashing)."""
    return "".join(ch for ch in phone if ch.isdigit())


def hash_user_data(lead: Lead) -> dict[str, list[str]]:
    """Build Meta's hashed ``user_data`` block from a lead.

    Only hashed identifiers leave this function. Raw PII is never included.
    Keys follow Meta's field names: em (email), ph (phone), fn (first name),
    ln (last name), ct (city), country. Every value that carries PII is
    SHA-256 hashed after Meta's normalisation (lowercase + trim). Each extra
    matched field raises the event's match quality.
    """
    user_data: dict[str, list[str]] = {}
    if lead.email:
        user_data["em"] = [_sha256(lead.email)]
    if lead.phone:
        normalised = _normalise_phone(lead.phone)
        if normalised:
            user_data["ph"] = [_sha256(normalised)]
    if lead.first_name:
        user_data["fn"] = [_sha256(lead.first_name)]
    if lead.last_name:
        user_data["ln"] = [_sha256(lead.last_name)]
    if lead.city:
        # Meta expects the city with spaces/punctuation removed before hashing.
        city = "".join(ch for ch in lead.city.lower() if ch.isalpha())
        if city:
            user_data["ct"] = [_sha256(city)]

    country = _config()["default_country"]
    if country:
        user_data["country"] = [_sha256(country)]

    return user_data


# --- payload --------------------------------------------------------------

def build_payload(
    lead: Lead, event_name: str, event_id: str, event_time: Optional[int] = None
) -> dict[str, Any]:
    """Assemble the Conversions API request body for a single event.

    event_id is included so Meta can deduplicate retries against the original.
    """
    if event_time is None:
        event_time = int(datetime.utcnow().timestamp())

    user_data = hash_user_data(lead)
    # Non-hashed identifiers. Meta requires these in the clear (they are not
    # PII in Meta's model) and they are among the strongest matching signals.
    if lead.ip_address:
        user_data["client_ip_address"] = lead.ip_address
    if lead.user_agent:
        user_data["client_user_agent"] = lead.user_agent
    if lead.fbc:
        user_data["fbc"] = lead.fbc
    if lead.fbp:
        user_data["fbp"] = lead.fbp

    data_entry: dict[str, Any] = {
        "event_name": event_name,
        "event_time": event_time,
        "event_id": event_id,
        "action_source": "website",
        "user_data": user_data,
    }

    cfg = _config()
    if cfg["event_source_url"]:
        data_entry["event_source_url"] = cfg["event_source_url"]

    payload: dict[str, Any] = {"data": [data_entry]}

    # Test events surface in Meta's Test Events tool without affecting metrics.
    if cfg["test_event_code"]:
        payload["test_event_code"] = cfg["test_event_code"]

    return payload


# --- HTTP send ------------------------------------------------------------

def send_event(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """POST a payload to Meta. Returns (ok, response_dict).

    Never raises: network/timeout errors are caught and returned as a failed
    result so the caller can persist them.
    """
    cfg = _config()
    url = _endpoint(cfg["pixel_id"], cfg["api_version"])
    try:
        resp = requests.post(
            url,
            params={"access_token": cfg["access_token"]},
            json=payload,
            timeout=cfg["timeout"],
        )
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}

        if resp.status_code == 200:
            return True, body
        return False, {"status_code": resp.status_code, "body": body}
    except requests.RequestException as exc:
        # Connection error, timeout, DNS, etc.
        return False, {"error": str(exc)}


# --- persistence ----------------------------------------------------------

def save_result(
    event: MetaEvent, ok: bool, response: dict[str, Any]
) -> MetaEvent:
    """Persist the outcome of a send onto an existing MetaEvent row."""
    event.response_payload = json.dumps(response)[:8000]
    if ok:
        event.status = "sent"
        event.sent_at = datetime.utcnow()
    else:
        event.status = "failed"
    db.session.commit()
    return event


def deliver_now(meta_event_id: int) -> Optional[MetaEvent]:
    """Deliver a persisted pending/failed event by its id, recording the result.

    This is the single unit of work behind every delivery path: it takes only
    a row id, reloads the event and lead from the DB, rebuilds the payload
    (reusing the stored event_id so Meta deduplicates), sends, and persists the
    outcome. It depends on no request-scoped state, so a background queue worker
    can call exactly this function later without any change here.
    """
    event = db.session.get(MetaEvent, meta_event_id)
    if event is None:
        return None
    if event.status == "sent":
        return event  # already delivered; nothing to do

    lead = db.session.get(Lead, event.lead_id)
    if lead is None:
        # Lead was deleted; nothing to resend. Mark it so we stop retrying.
        event.status = "orphaned"
        db.session.commit()
        return event

    payload = build_payload(lead, event.event_name, event.event_id)
    event.request_payload = json.dumps(payload)[:8000]
    ok, response = send_event(payload)
    save_result(event, ok, response)
    if ok:
        logger.info(
            "Meta event sent: id=%s event=%s lead_id=%s",
            event.id, event.event_name, event.lead_id,
        )
    else:
        logger.warning(
            "Meta event failed: id=%s event=%s lead_id=%s",
            event.id, event.event_name, event.lead_id,
        )
    return event


# --- dispatch strategy (the swap point for a future background queue) ------
#
# track_event always persists a `pending` row, then hands its id to a
# dispatcher. The dispatcher decides *how* delivery happens; the pending row is
# the handoff contract. Swapping synchronous delivery for a queue means
# registering a different dispatcher here — track_event and, above it,
# lead_service stay untouched and never learn whether Meta is sent inline or
# enqueued.

class MetaDispatcher:
    """Strategy for delivering a persisted MetaEvent by its id."""

    def dispatch(self, meta_event_id: int) -> None:
        raise NotImplementedError


class SyncDispatcher(MetaDispatcher):
    """Deliver inline, within the current request. The default today."""

    def dispatch(self, meta_event_id: int) -> None:
        deliver_now(meta_event_id)


# Available strategies, keyed by the META_DISPATCH_MODE config value. A future
# queue backend registers itself here (e.g. "queue": QueueDispatcher) — its
# dispatch() would enqueue the id for a worker that calls deliver_now().
_DISPATCHERS: dict[str, "type[MetaDispatcher]"] = {
    "sync": SyncDispatcher,
}

# Test/runtime override; takes precedence over config when set.
_dispatcher_override: Optional[MetaDispatcher] = None


def set_dispatcher(dispatcher: Optional[MetaDispatcher]) -> None:
    """Install a specific dispatcher (for wiring a queue, or in tests).

    Pass None to clear the override and fall back to config selection.
    """
    global _dispatcher_override
    _dispatcher_override = dispatcher


def get_dispatcher() -> MetaDispatcher:
    """Resolve the active dispatcher: explicit override, else config, else sync."""
    if _dispatcher_override is not None:
        return _dispatcher_override
    mode = current_app.config.get("META_DISPATCH_MODE", "sync")
    cls = _DISPATCHERS.get(mode)
    if cls is None:
        logger.warning("Unknown META_DISPATCH_MODE=%s; falling back to sync.", mode)
        cls = SyncDispatcher
    return cls()


# --- public entry point ---------------------------------------------------

def _resolve_event(trigger: str) -> Optional[str]:
    """Map a CRM trigger to the Meta event name to send, or None if untracked.

    Two kinds of trigger reach here:
    - "lead_created": the synthetic on-creation trigger. It isn't a lead status,
      so it's resolved from the static constants map.
    - a lead status name (e.g. "Interested"): resolved from the admin-editable
      status_service (DB), so renaming a status or changing its Meta mapping in
      the dashboard takes effect immediately, with no code change.
    """
    if trigger == "lead_created":
        return _const_meta_event_for(trigger)
    # Any other trigger is a lead status — its mapping is admin-managed.
    from app.services import status_service
    return status_service.meta_event_for(trigger)


def track_event(
    lead: Lead, trigger: str, event_id: Optional[str] = None
) -> Optional[MetaEvent]:
    """Fire a conversion event for a lead trigger, if one is mapped.

    `trigger` is either "lead_created" or a lead status. Persists a pending
    MetaEvent, then hands it to the active dispatcher (synchronous today).
    Returns the MetaEvent row, or None when Meta is disabled or the trigger is
    untracked. Never raises — failures are persisted, not propagated.

    If `event_id` is passed, it is reused for the event (crucial for
    deduplicating against a browser-side Pixel hit with the identical eventID).
    """
    cfg = _config()
    if not cfg["enabled"]:
        return None

    event_name = _resolve_event(trigger)
    if not event_name:
        return None  # trigger isn't in the mapping — nothing to send

    if not cfg["pixel_id"] or not cfg["access_token"]:
        logger.warning("Meta enabled but pixel_id/access_token missing; skipping.")
        return None

    event_id = event_id or uuid.uuid4().hex
    payload = build_payload(lead, event_name, event_id)

    # Persist as pending BEFORE dispatching, so a crash mid-delivery still
    # leaves a record we can retry. This row is the handoff contract to the
    # dispatcher (and to any future queue worker).
    event = MetaEvent(
        lead_id=lead.id,
        event_name=event_name,
        event_id=event_id,
        status="pending",
        request_payload=json.dumps(payload)[:8000],
    )
    db.session.add(event)
    db.session.commit()

    get_dispatcher().dispatch(event.id)
    # With the sync dispatcher `event` now reflects sent/failed (same session
    # identity). With an async dispatcher it stays `pending` until a worker
    # delivers it — either way the row is authoritative.
    return event


# --- retry ----------------------------------------------------------------

def retry_failed_events(limit: int = 100) -> dict[str, int]:
    """Resend events currently marked ``failed``. Returns a counts summary.

    Reuses each event's stored event_id (rebuilding the payload) so Meta
    deduplicates against the original attempt.
    """
    cfg = _config()
    if not cfg["enabled"]:
        logger.info("Meta disabled; retry-failed-events is a no-op.")
        return {"retried": 0, "sent": 0, "failed": 0}

    from sqlalchemy import select

    failed = db.session.scalars(
        select(MetaEvent)
        .where(MetaEvent.status == "failed")
        .order_by(MetaEvent.created_at)
        .limit(limit)
    ).all()

    sent = 0
    still_failed = 0
    for event in failed:
        # Reuse the same unit of work as live delivery. deliver_now handles the
        # lead-deleted (orphaned) case and reuses the stored event_id so Meta
        # deduplicates against the original attempt.
        result = deliver_now(event.id)
        if result is not None and result.status == "sent":
            sent += 1
        else:
            still_failed += 1

    logger.info(
        "Meta retry complete: retried=%s sent=%s failed=%s",
        len(failed), sent, still_failed,
    )
    return {"retried": len(failed), "sent": sent, "failed": still_failed}
