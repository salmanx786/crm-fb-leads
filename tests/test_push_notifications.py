"""Focused tests for the Web Push notification feature.

Covers:
- create_lead calls push_service.notify_all_admins (mocked so no real push).
- save_push_settings blank private key leaves the stored key untouched.
- push_settings_view never returns the raw private key.
- /push/subscribe persists a row; malformed payload → 400.
- /push/unsubscribe removes the row.
- /settings/notifications requires login.
"""
import json
import re
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models import PushSubscription
from app.services import settings_service as s

_CSRF_RE = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"'
)


def _csrf(html: str) -> str:
    m = _CSRF_RE.search(html)
    assert m, "CSRF token not found"
    return m.group(1) or m.group(2)


def _login(client):
    from app.services import user_service

    user_service.create_admin("Admin", "admin@mc.edu", "s3cret-pass")
    token = _csrf(client.get("/login").get_data(as_text=True))
    client.post(
        "/login",
        data={"csrf_token": token, "email": "admin@mc.edu", "password": "s3cret-pass"},
    )


def _admin_id(app):
    from app.models import User

    return db.session.scalar(db.select(User).where(User.email == "admin@mc.edu")).id


# --- lead creation trigger ------------------------------------------------

def test_create_lead_calls_notify_all_admins(app):
    """notify_all_admins is called once when a lead is created."""
    from app.services import lead_service

    with patch("app.services.lead_service.push_service.notify_all_admins") as mock_notify:
        lead = lead_service.create_lead(
            {"first_name": "Asha", "last_name": "Verma", "phone": "+92 300 1234567"}
        )
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args
        assert "New lead" in (call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("title", ""))
        assert str(lead.id) in (call_kwargs.kwargs.get("url") or "")


# --- settings service -----------------------------------------------------

def test_save_push_settings_persists_fields(app):
    s.save_push_settings(
        {
            "enabled": True,
            "public_key": "pub-key-abc",
            "private_key": "priv-key-xyz",
            "subject": "mailto:admin@mc.edu",
        }
    )
    assert s.get_bool(s.PUSH_ENABLED) is True
    assert s.get_str(s.VAPID_PUBLIC_KEY) == "pub-key-abc"
    assert s.get_str(s.VAPID_PRIVATE_KEY) == "priv-key-xyz"
    assert s.get_str(s.VAPID_SUBJECT) == "mailto:admin@mc.edu"


def test_blank_private_key_keeps_existing(app):
    s.save_push_settings({"enabled": True, "private_key": "original-priv"})
    # A later save with a blank private key must not wipe it.
    s.save_push_settings({"enabled": True, "private_key": "", "public_key": "new-pub"})
    assert s.get_str(s.VAPID_PRIVATE_KEY) == "original-priv"


def test_push_settings_view_never_exposes_private_key(app):
    s.save_push_settings({"enabled": True, "private_key": "supersecret-priv"})
    view = s.push_settings_view()
    assert view["has_private_key"] is True
    assert "supersecret-priv" not in str(view)


# --- subscribe / unsubscribe routes ---------------------------------------

_GOOD_SUB = {
    "endpoint": "https://push.example.com/sub/abc123",
    "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
}


def test_subscribe_persists_row(client, app):
    _login(client)
    csrf = _csrf(client.get("/dashboard/").get_data(as_text=True))
    resp = client.post(
        "/dashboard/push/subscribe",
        data=json.dumps({"subscription": _GOOD_SUB}),
        content_type="application/json",
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    row = db.session.scalar(
        db.select(PushSubscription).where(
            PushSubscription.endpoint == _GOOD_SUB["endpoint"]
        )
    )
    assert row is not None
    assert row.user_id == _admin_id(app)


def test_subscribe_malformed_payload_returns_400(client, app):
    _login(client)
    csrf = _csrf(client.get("/dashboard/").get_data(as_text=True))
    resp = client.post(
        "/dashboard/push/subscribe",
        data=json.dumps({"subscription": {"endpoint": "https://x.test"}}),  # missing keys
        content_type="application/json",
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 400


def test_unsubscribe_removes_row(client, app):
    _login(client)
    csrf = _csrf(client.get("/dashboard/").get_data(as_text=True))
    # Subscribe first.
    client.post(
        "/dashboard/push/subscribe",
        data=json.dumps({"subscription": _GOOD_SUB}),
        content_type="application/json",
        headers={"X-CSRFToken": csrf},
    )
    # Then unsubscribe.
    resp = client.post(
        "/dashboard/push/unsubscribe",
        data=json.dumps({"endpoint": _GOOD_SUB["endpoint"]}),
        content_type="application/json",
        headers={"X-CSRFToken": csrf},
    )
    assert resp.status_code == 200
    assert resp.get_json()["removed"] is True
    row = db.session.scalar(
        db.select(PushSubscription).where(
            PushSubscription.endpoint == _GOOD_SUB["endpoint"]
        )
    )
    assert row is None


# --- settings page --------------------------------------------------------

def test_notification_settings_requires_login(client):
    resp = client.get("/dashboard/settings/notifications")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_notification_settings_page_renders(client, app):
    _login(client)
    resp = client.get("/dashboard/settings/notifications")
    assert resp.status_code == 200
    assert b"Push notifications" in resp.data


def test_notification_settings_page_does_not_render_private_key(client, app):
    _login(client)
    s.save_push_settings({"enabled": True, "private_key": "leaky-priv-key"})
    html = client.get("/dashboard/settings/notifications").get_data(as_text=True)
    assert "leaky-priv-key" not in html
