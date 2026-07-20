"""Tests for admin-editable settings (app.services.settings_service).

Covers the DB-over-env fallback chain, the "blank token keeps the stored one"
rule, the secret never being exposed to the view, and meta_service reading the
saved values.
"""
import re

import pytest

from app.extensions import db
from app.models import AppSetting
from app.services import meta_service, settings_service as s


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


# --- fallback chain -------------------------------------------------------

def test_get_str_falls_back_to_config_when_unset(app):
    app.config["META_PIXEL_ID"] = "env-pixel"
    assert s.get_str(s.META_PIXEL_ID) == "env-pixel"


def test_db_value_overrides_config(app):
    app.config["META_PIXEL_ID"] = "env-pixel"
    s.set_value(s.META_PIXEL_ID, "db-pixel")
    db.session.commit()
    assert s.get_str(s.META_PIXEL_ID) == "db-pixel"


def test_get_bool_reads_stored_true_false(app):
    app.config["META_ENABLED"] = False
    s.set_value(s.META_ENABLED, "true")
    db.session.commit()
    assert s.get_bool(s.META_ENABLED) is True


# --- save rules -----------------------------------------------------------

def test_save_meta_settings_persists_fields(app):
    s.save_meta_settings(
        {
            "enabled": True,
            "pixel_id": "123",
            "access_token": "tok-abc",
            "test_event_code": "TEST9",
            "default_country": "US",
            "event_source_url": "https://x.test/",
        }
    )
    assert s.get_bool(s.META_ENABLED) is True
    assert s.get_str(s.META_PIXEL_ID) == "123"
    assert s.get_str(s.META_ACCESS_TOKEN) == "tok-abc"
    # Country is normalised to lowercase.
    assert s.get_str(s.META_DEFAULT_COUNTRY) == "us"


def test_blank_token_keeps_existing(app):
    s.save_meta_settings({"access_token": "original", "enabled": True})
    # A later save with a blank token must not wipe it.
    s.save_meta_settings({"access_token": "", "enabled": True, "pixel_id": "9"})
    assert s.get_str(s.META_ACCESS_TOKEN) == "original"


def test_view_never_exposes_token(app):
    s.save_meta_settings({"access_token": "supersecret", "enabled": True})
    view = s.meta_settings_view()
    assert view["has_access_token"] is True
    assert "supersecret" not in str(view)


# --- meta_service reads the saved values ----------------------------------

def test_meta_service_config_reads_saved_settings(app):
    s.save_meta_settings(
        {"enabled": True, "pixel_id": "77", "access_token": "tok", "default_country": "pk"}
    )
    cfg = meta_service._config()
    assert cfg["enabled"] is True
    assert cfg["pixel_id"] == "77"
    assert cfg["access_token"] == "tok"
    assert cfg["default_country"] == "pk"


# --- the dashboard route --------------------------------------------------

def test_settings_page_requires_login(client):
    resp = client.get("/dashboard/settings/meta")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_settings_page_does_not_render_token(client, app):
    _login(client)
    s.save_meta_settings({"access_token": "leaky-token", "enabled": True})
    html = client.get("/dashboard/settings/meta").get_data(as_text=True)
    assert "leaky-token" not in html


def test_post_saves_settings(client, app):
    _login(client)
    html = client.get("/dashboard/settings/meta").get_data(as_text=True)
    token = _csrf(html)
    resp = client.post(
        "/dashboard/settings/meta",
        data={
            "csrf_token": token,
            "enabled": "y",
            "pixel_id": "555",
            "access_token": "new-token",
            "default_country": "pk",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert s.get_str(s.META_PIXEL_ID) == "555"
    assert s.get_str(s.META_ACCESS_TOKEN) == "new-token"
    assert s.get_bool(s.META_ENABLED) is True
