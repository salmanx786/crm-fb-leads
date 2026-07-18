"""Tests for the admin media-management CMS and its effect on the public page.

Covers the addendum requirements:
- fallback rules: required slots, branded placeholder, hide-when-empty;
- text/URL and media slot editing flowing through to the public page;
- the gallery hide/show QA (§4): hidden when empty, appears after upload,
  hidden again after removal;
- default FAQ seeding, and FAQ add/edit/delete.
"""
import io
import os
import re
import shutil

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import FaqItem, GalleryItem, SiteContent
from app.services import content_service, user_service

_CSRF_RE = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"'
)


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match, "CSRF token not found"
    return match.group(1) or match.group(2)


@pytest.fixture()
def admin(app):
    return user_service.create_admin("Admin User", "admin@mc.edu", "s3cret-pass")


@pytest.fixture()
def auth(client, admin):
    """A logged-in client."""
    token = _csrf(client.get("/login").get_data(as_text=True))
    client.post(
        "/login",
        data={"csrf_token": token, "email": "admin@mc.edu", "password": "s3cret-pass"},
        follow_redirects=False,
    )
    return client


@pytest.fixture(autouse=True)
def _cleanup_uploads(app):
    """Remove any files written to static/uploads during a test."""
    yield
    uploads = os.path.join(app.static_folder, "uploads")
    if os.path.isdir(uploads):
        shutil.rmtree(uploads)


def _dash_csrf(auth):
    return _csrf(auth.get("/dashboard/content/").get_data(as_text=True))


def _png():
    return (io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "pic.png")


# --- fallback rules -------------------------------------------------------

def test_public_page_renders_with_no_content(client):
    """No CMS content yet: page still renders, no broken/empty slots."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Branded placeholder is used for program/why-us images.
    assert "branded-placeholder.svg" in body
    # Video + gallery sections are hidden when empty.
    assert "Hear From Our Principal" not in body
    assert "Campus Gallery" not in body


def test_required_logos_reported_missing_then_satisfied(app):
    missing = {s.key for s in content_service.missing_required_slots()}
    assert missing == {"logo_mc", "logo_jsmu"}
    content_service.set_value("logo_mc", "uploads/logos/x.svg")
    content_service.set_value("logo_jsmu", "uploads/logos/y.svg")
    assert content_service.missing_required_slots() == []


def test_hero_headline_defaults_and_is_editable(app):
    # Default applies when unset — never blank.
    assert content_service.resolve_slot("hero_headline") == (
        "Apply for DPT or BSMT — Affordable, HEC Recognized."
    )
    content_service.set_value("hero_headline", "Custom Headline")
    assert content_service.resolve_slot("hero_headline") == "Custom Headline"


# --- media + text slot editing via the dashboard --------------------------

def test_upload_media_slot_shows_on_public_page(auth):
    csrf = _dash_csrf(auth)
    resp = auth.post(
        "/dashboard/content/slot/logo_mc/media",
        data={"csrf_token": csrf, "file": _png()},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    stored = content_service.get_raw("logo_mc")
    assert stored and stored.startswith("uploads/logo_mc/")
    # Resolves to the uploaded file, and it's referenced on the public page.
    with auth.application.test_request_context():
        assert content_service.resolve_slot("logo_mc").endswith(stored)
    assert stored in auth.get("/").get_data(as_text=True)


def test_clear_media_slot_reverts_to_placeholder(auth):
    csrf = _dash_csrf(auth)
    auth.post(
        "/dashboard/content/slot/program_dpt_img/media",
        data={"csrf_token": csrf, "file": _png()},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert content_service.get_raw("program_dpt_img") is not None
    auth.post(
        "/dashboard/content/slot/program_dpt_img/clear",
        data={"csrf_token": _dash_csrf(auth)},
        follow_redirects=True,
    )
    assert content_service.get_raw("program_dpt_img") is None
    # Placeholder rule: resolves to the branded placeholder, not None.
    with auth.application.test_request_context():
        assert content_service.resolve_slot("program_dpt_img").endswith(
            "branded-placeholder.svg"
        )


def test_text_slot_edit_reflected_on_page(auth):
    auth.post(
        "/dashboard/content/slot/hero_headline/text",
        data={"csrf_token": _dash_csrf(auth), "value": "Enroll Today at MC"},
        follow_redirects=True,
    )
    assert "Enroll Today at MC" in auth.get("/").get_data(as_text=True)


def test_blank_text_slot_falls_back_to_default(auth):
    content_service.set_value("hero_headline", "Something")
    auth.post(
        "/dashboard/content/slot/hero_headline/text",
        data={"csrf_token": _dash_csrf(auth), "value": "   "},
        follow_redirects=True,
    )
    # Stored value cleared; default used on the page (never blank).
    assert content_service.get_raw("hero_headline") is None
    assert "Apply for DPT or BSMT" in auth.get("/").get_data(as_text=True)


def test_unsupported_file_type_rejected(auth):
    resp = auth.post(
        "/dashboard/content/slot/logo_mc/media",
        data={"csrf_token": _dash_csrf(auth),
              "file": (io.BytesIO(b"bad"), "malware.exe")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert content_service.get_raw("logo_mc") is None  # nothing stored


# --- video hide-when-empty ------------------------------------------------

def test_video_section_hidden_until_uploaded(auth):
    assert "Hear From Our Principal" not in auth.get("/").get_data(as_text=True)
    auth.post(
        "/dashboard/content/slot/principal_video/media",
        data={"csrf_token": _dash_csrf(auth),
              "file": (io.BytesIO(b"fakemp4"), "clip.mp4")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    body = auth.get("/").get_data(as_text=True)
    assert "Hear From Our Principal" in body
    # Self-hosted + lazy: no YouTube, uses data-src not an eager src.
    assert "youtube" not in body.lower()
    assert "data-lazy-video" in body


# --- gallery hide/show QA (§4) --------------------------------------------

def test_gallery_hide_show_cycle(auth):
    # 1. Empty -> section absent.
    assert "Campus Gallery" not in auth.get("/").get_data(as_text=True)

    # 2. Upload one photo -> section appears.
    auth.post(
        "/dashboard/content/gallery/add",
        data={"csrf_token": _dash_csrf(auth), "caption": "Lab",
              "file": (io.BytesIO(b"img"), "lab.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert db.session.scalar(select(db.func.count(GalleryItem.id))) == 1
    body = auth.get("/").get_data(as_text=True)
    assert "Campus Gallery" in body
    assert "Lab" in body

    # 3. Remove it -> section disappears again.
    item_id = db.session.scalar(select(GalleryItem.id))
    auth.post(
        f"/dashboard/content/gallery/{item_id}/delete",
        data={"csrf_token": _dash_csrf(auth)},
        follow_redirects=True,
    )
    assert db.session.scalar(select(db.func.count(GalleryItem.id))) == 0
    assert "Campus Gallery" not in auth.get("/").get_data(as_text=True)


# --- FAQ ------------------------------------------------------------------

def test_seed_defaults_populates_faqs(app):
    content_service.seed_defaults()
    count = db.session.scalar(select(db.func.count(FaqItem.id)))
    assert count >= 4
    # Idempotent: a second call does not duplicate.
    content_service.seed_defaults()
    assert db.session.scalar(select(db.func.count(FaqItem.id))) == count


def test_faq_add_update_delete_flow(auth):
    auth.post(
        "/dashboard/content/faq/add",
        data={"csrf_token": _dash_csrf(auth), "question": "Q1?", "answer": "A1."},
        follow_redirects=True,
    )
    item = db.session.scalar(select(FaqItem).filter_by(question="Q1?"))
    assert item is not None
    assert "Q1?" in auth.get("/").get_data(as_text=True)

    auth.post(
        f"/dashboard/content/faq/{item.id}/update",
        data={"csrf_token": _dash_csrf(auth), "question": "Q1 edited?", "answer": "A1."},
        follow_redirects=True,
    )
    db.session.refresh(item)
    assert item.question == "Q1 edited?"

    auth.post(
        f"/dashboard/content/faq/{item.id}/delete",
        data={"csrf_token": _dash_csrf(auth)},
        follow_redirects=True,
    )
    assert db.session.get(FaqItem, item.id) is None


def test_content_dashboard_requires_login(client):
    resp = client.get("/dashboard/content/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
