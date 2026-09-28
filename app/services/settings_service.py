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

# Web Push (VAPID) settings. Same DB->config->default fallback as Meta, so push
# stays off until an admin (or env) configures it. The private key is a secret.
PUSH_ENABLED = "PUSH_ENABLED"
VAPID_PUBLIC_KEY = "VAPID_PUBLIC_KEY"
VAPID_PRIVATE_KEY = "VAPID_PRIVATE_KEY"
VAPID_SUBJECT = "VAPID_SUBJECT"

# Transactional email (SMTP) settings. Same DB->config->default fallback, so
# email stays off until an admin (or env) configures it. The SMTP password is a
# secret. Defaults target Google Workspace SMTP (see config.py).
MAIL_ENABLED = "MAIL_ENABLED"
MAIL_SMTP_HOST = "MAIL_SMTP_HOST"
MAIL_SMTP_PORT = "MAIL_SMTP_PORT"
MAIL_USERNAME = "MAIL_USERNAME"
MAIL_PASSWORD = "MAIL_PASSWORD"
MAIL_FROM = "MAIL_FROM"
ADMISSIONS_NOTIFY_EMAIL = "ADMISSIONS_NOTIFY_EMAIL"

# Keys whose stored value is a secret — masked in the UI, never logged.
SECRET_KEYS = frozenset({META_ACCESS_TOKEN, VAPID_PRIVATE_KEY, MAIL_PASSWORD})

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


def save_push_settings(data: dict) -> None:
    """Persist the Web Push (VAPID) settings submitted from the dashboard.

    Mirrors ``save_meta_settings``: the private key is a secret, so a blank
    submission means "leave the stored key unchanged" — the admin never has to
    re-enter it to tweak the subject or toggle push, and it need not be
    pre-filled into the page. All writes commit in one transaction.
    """
    set_value(PUSH_ENABLED, "true" if data.get("enabled") else "false")
    set_value(VAPID_PUBLIC_KEY, (data.get("public_key") or "").strip() or None)
    set_value(VAPID_SUBJECT, (data.get("subject") or "").strip() or None)

    # Private key: only overwrite when a non-empty value was submitted.
    private_key = (data.get("private_key") or "").strip()
    if private_key:
        set_value(VAPID_PRIVATE_KEY, private_key)

    db.session.commit()


def push_settings_view() -> dict:
    """Resolved Web Push settings for rendering the settings page.

    Never includes the raw private key — only whether one is configured — so
    the secret is not written into the HTML response.
    """
    return {
        "enabled": get_bool(PUSH_ENABLED),
        "public_key": get_str(VAPID_PUBLIC_KEY),
        "subject": get_str(VAPID_SUBJECT),
        "has_private_key": bool(get_str(VAPID_PRIVATE_KEY)),
    }


def save_mail_settings(data: dict) -> None:
    """Persist the transactional email (SMTP) settings from the dashboard.

    Mirrors ``save_push_settings``: the SMTP password is a secret, so a blank
    submission means "leave the stored password unchanged" — the admin never
    has to re-enter it to tweak the host or toggle email, and it need not be
    pre-filled into the page. All writes commit in one transaction.
    """
    set_value(MAIL_ENABLED, "true" if data.get("enabled") else "false")
    set_value(MAIL_SMTP_HOST, (data.get("smtp_host") or "").strip() or None)
    set_value(MAIL_SMTP_PORT, (str(data.get("smtp_port")).strip() or None)
              if data.get("smtp_port") not in (None, "") else None)
    set_value(MAIL_USERNAME, (data.get("username") or "").strip() or None)
    set_value(MAIL_FROM, (data.get("from_address") or "").strip() or None)
    set_value(ADMISSIONS_NOTIFY_EMAIL, (data.get("admissions_notify_email") or "").strip() or None)

    # Password: only overwrite when a non-empty value was submitted.
    password = (data.get("password") or "").strip()
    if password:
        set_value(MAIL_PASSWORD, password)

    db.session.commit()


def mail_settings_view() -> dict:
    """Resolved email settings for rendering the settings page.

    Never includes the raw SMTP password — only whether one is configured — so
    the secret is not written into the HTML response.
    """
    return {
        "enabled": get_bool(MAIL_ENABLED),
        "smtp_host": get_str(MAIL_SMTP_HOST),
        "smtp_port": get_str(MAIL_SMTP_PORT),
        "username": get_str(MAIL_USERNAME),
        "from_address": get_str(MAIL_FROM),
        "admissions_notify_email": get_str(ADMISSIONS_NOTIFY_EMAIL),
        "has_password": bool(get_str(MAIL_PASSWORD)),
    }
