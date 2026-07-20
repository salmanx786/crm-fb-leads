"""Admin-editable application settings, backed by the AppSetting table.

Currently this owns the Meta (Facebook) Conversions API configuration so an
admin can manage it from the dashboard instead of editing ``.env`` on the
server. Each setting has a stable key and reads with a fallback chain:

    DB value (admin-saved)  ->  app.config (env / .env)  ->  hard default

so an empty table behaves exactly like the pre-dashboard code path — existing
deployments and tests keep working until an admin saves something.

SECRET HANDLING: META_ACCESS_TOKEN is a credential. It is stored here (the
admin opted into DB storage), but it is never rendered back into a page, never
logged, and a blank submit on the settings form leaves the stored value
untouched rather than clearing it (see the dashboard route).
"""
from __future__ import annotations

from typing import Optional

from flask import current_app

from app.extensions import db
from app.models import AppSetting

# Keys the dashboard manages. Each maps to the matching app.config name used as
# the env fallback. Booleans are stored as "true"/"false" strings.
META_ENABLED = "META_ENABLED"
META_PIXEL_ID = "META_PIXEL_ID"
META_ACCESS_TOKEN = "META_ACCESS_TOKEN"
META_TEST_EVENT_CODE = "META_TEST_EVENT_CODE"
META_DEFAULT_COUNTRY = "META_DEFAULT_COUNTRY"
META_EVENT_SOURCE_URL = "META_EVENT_SOURCE_URL"

# Keys whose stored value is a secret — masked in the UI, never logged.
SECRET_KEYS = frozenset({META_ACCESS_TOKEN})

# String settings the settings form reads/writes, in display order.
META_STRING_KEYS = (
    META_PIXEL_ID,
    META_ACCESS_TOKEN,
    META_TEST_EVENT_CODE,
    META_DEFAULT_COUNTRY,
    META_EVENT_SOURCE_URL,
)

_TRUE = {"1", "true", "yes", "on"}


def _row(key: str) -> Optional[AppSetting]:
    return db.session.scalar(db.select(AppSetting).where(AppSetting.key == key))


def get_raw(key: str) -> Optional[str]:
    """The admin-saved value for a key, or None if never set."""
    row = _row(key)
    return row.value if row is not None else None


def get_str(key: str) -> str:
    """Resolved string value: DB, else app.config (env), else empty string."""
    stored = get_raw(key)
    if stored is not None:
        return stored
    return (current_app.config.get(key) or "") if current_app else ""


def get_bool(key: str) -> bool:
    """Resolved boolean: DB value if set, else the app.config value."""
    stored = get_raw(key)
    if stored is not None:
        return stored.strip().lower() in _TRUE
    return bool(current_app.config.get(key)) if current_app else False


def set_value(key: str, value: Optional[str]) -> None:
    """Upsert a single setting. Passing None clears it (reverts to the env
    fallback). Caller owns the commit boundary via ``save_meta_settings``."""
    row = _row(key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value


def save_meta_settings(data: dict) -> None:
    """Persist the Meta settings submitted from the dashboard.

    `data` carries the raw form values. The access token is special: a blank
    submission means "leave the stored token unchanged" so the admin never has
    to re-enter it to tweak another field, and so it need not be pre-filled
    into the page. All writes commit in one transaction.
    """
    set_value(META_ENABLED, "true" if data.get("enabled") else "false")
    set_value(META_PIXEL_ID, (data.get("pixel_id") or "").strip() or None)
    set_value(META_TEST_EVENT_CODE, (data.get("test_event_code") or "").strip() or None)
    set_value(META_DEFAULT_COUNTRY, (data.get("default_country") or "").strip().lower() or None)
    set_value(META_EVENT_SOURCE_URL, (data.get("event_source_url") or "").strip() or None)

    # Token: only overwrite when a non-empty value was submitted.
    token = (data.get("access_token") or "").strip()
    if token:
        set_value(META_ACCESS_TOKEN, token)

    db.session.commit()


def meta_settings_view() -> dict:
    """Resolved Meta settings for rendering the settings page.

    Never includes the raw access token — only whether one is configured — so
    the secret is not written into the HTML response.
    """
    return {
        "enabled": get_bool(META_ENABLED),
        "pixel_id": get_str(META_PIXEL_ID),
        "test_event_code": get_str(META_TEST_EVENT_CODE),
        "default_country": get_str(META_DEFAULT_COUNTRY),
        "event_source_url": get_str(META_EVENT_SOURCE_URL),
        "has_access_token": bool(get_str(META_ACCESS_TOKEN)),
    }
