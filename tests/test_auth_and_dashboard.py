"""Tests for admin authentication and dashboard lead management.

Covers: create-admin logic, login (success + failure), protected-route
redirects, status updates, and note creation. All write paths go through
the service layer, so asserting on the DB confirms the whole chain.
"""
import re

import pytest

from app.extensions import db
from app.models import Lead, LeadNote, TimelineEvent, User
from app.services import lead_service, user_service

_CSRF_RE = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"'
)


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match, "CSRF token not found"
    return match.group(1) or match.group(2)


@pytest.fixture()
def admin(app):
    """A persisted admin user (created via the service, like the CLI does)."""
    return user_service.create_admin("Admin User", "admin@mc.edu", "s3cret-pass")


@pytest.fixture()
def lead(app):
    """A persisted lead created through the service (records a timeline event)."""
    return lead_service.create_lead(
        {"name": "Rohan Das", "phone": "+91 90000 00000", "email": "rohan@example.com"}
    )


def _login(client, email="admin@mc.edu", password="s3cret-pass"):
    """Log in through the real form so the CSRF + session flow is exercised."""
    token = _csrf(client.get("/login").get_data(as_text=True))
    return client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
        follow_redirects=False,
    )


# --- create-admin ---------------------------------------------------------

def test_create_admin_hashes_password_and_persists(app, admin):
    stored = User.query.filter_by(email="admin@mc.edu").one()
    assert stored.name == "Admin User"
    assert stored.password_hash != "s3cret-pass"      # not stored in plaintext
    assert stored.check_password("s3cret-pass")       # but verifies correctly


def test_create_admin_rejects_duplicate_email(app, admin):
    with pytest.raises(user_service.UserAlreadyExistsError):
        user_service.create_admin("Someone Else", "ADMIN@mc.edu", "another-pass")


# --- login ----------------------------------------------------------------

def test_login_success_redirects_to_dashboard(client, admin):
    resp = _login(client)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_login_wrong_password_is_rejected(client, admin):
    resp = _login(client, password="wrong")
    assert resp.status_code == 401
    # No session established.
    with client.session_transaction() as session:
        assert "_user_id" not in session


# --- protected routes -----------------------------------------------------

def test_dashboard_requires_login(client):
    resp = client.get("/dashboard/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_leads_page_accessible_after_login(client, admin):
    _login(client)
    resp = client.get("/dashboard/leads")
    assert resp.status_code == 200


# --- status update --------------------------------------------------------

def test_update_status_changes_lead_and_logs_event(client, admin, lead, app):
    _login(client)
    lead_id = lead.id

    detail = client.get(f"/dashboard/leads/{lead_id}")
    token = _csrf(detail.get_data(as_text=True))

    resp = client.post(
        f"/dashboard/leads/{lead_id}/status",
        data={"csrf_token": token, "status": "Interested"},
    )
    assert resp.status_code == 302

    with app.app_context():
        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.status == "Interested"
        # created + status_changed
        types = {e.event_type for e in TimelineEvent.query.filter_by(lead_id=lead_id)}
        assert "status_changed" in types


# --- note creation --------------------------------------------------------

def test_add_note_persists_and_logs_event(client, admin, lead, app):
    _login(client)
    lead_id = lead.id

    detail = client.get(f"/dashboard/leads/{lead_id}")
    token = _csrf(detail.get_data(as_text=True))

    resp = client.post(
        f"/dashboard/leads/{lead_id}/notes",
        data={"csrf_token": token, "body": "Called; interested in MBA."},
    )
    assert resp.status_code == 302

    with app.app_context():
        notes = LeadNote.query.filter_by(lead_id=lead_id).all()
        assert len(notes) == 1
        assert notes[0].body == "Called; interested in MBA."
        types = {e.event_type for e in TimelineEvent.query.filter_by(lead_id=lead_id)}
        assert "note_added" in types
