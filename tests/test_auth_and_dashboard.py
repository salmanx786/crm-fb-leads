"""Tests for admin authentication and dashboard lead management.

Covers: create-admin logic, login (success + failure), protected-route
redirects, status updates, and note creation. All write paths go through
the service layer, so asserting on the DB confirms the whole chain.
"""
import csv
import io
import re

import pytest
from sqlalchemy import select

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
        {"first_name": "Rohan", "last_name": "Das",
         "phone": "+91 90000 00000", "email": "rohan@example.com"}
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
    stored = db.session.scalar(select(User).filter_by(email="admin@mc.edu"))
    assert stored is not None
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
        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id)
        ).all()
        types = {e.event_type for e in events}
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
        notes = db.session.scalars(
            select(LeadNote).filter_by(lead_id=lead_id)
        ).all()
        assert len(notes) == 1
        assert notes[0].body == "Called; interested in MBA."
        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id)
        ).all()
        types = {e.event_type for e in events}
        assert "note_added" in types


# --- lead editing ---------------------------------------------------------

def test_edit_lead_form_renders_prefilled(client, admin, lead):
    _login(client)
    resp = client.get(f"/dashboard/leads/{lead.id}/edit")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Prefilled from the lead (obj=lead) and posts back to the edit route.
    assert "Rohan Das" in html
    assert f"/dashboard/leads/{lead.id}/edit" in html


def test_edit_lead_updates_fields_and_records_event(client, admin, lead, app):
    _login(client)
    lead_id = lead.id

    form = client.get(f"/dashboard/leads/{lead_id}/edit")
    token = _csrf(form.get_data(as_text=True))

    resp = client.post(
        f"/dashboard/leads/{lead_id}/edit",
        data={
            "csrf_token": token,
            "first_name": "Rohan",
            "last_name": "D.",
            "phone": lead.phone,
            "email": lead.email,
            "city": "Pune",
            "course": "",
            "utm_source": "referral",
            "status": "Interested",
            "message": "",
        },
    )
    assert resp.status_code == 302
    assert f"/dashboard/leads/{lead_id}" in resp.headers["Location"]

    with app.app_context():
        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.name == "Rohan D."
        assert refreshed.last_name == "D."
        assert refreshed.city == "Pune"
        assert refreshed.utm_source == "referral"
        assert refreshed.status == "Interested"
        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="updated")
        ).all()
        assert len(events) == 1


def test_edit_lead_updates_all_academic_and_guardian_fields(client, admin, lead, app):
    _login(client)
    lead_id = lead.id

    form = client.get(f"/dashboard/leads/{lead_id}/edit")
    token = _csrf(form.get_data(as_text=True))

    resp = client.post(
        f"/dashboard/leads/{lead_id}/edit",
        data={
            "csrf_token": token,
            "first_name": "Rohan",
            "last_name": "Das",
            "phone": lead.phone,
            "email": lead.email,
            "city": "Karachi",
            "course": "BSMT",
            "specialization": "Clinical Laboratory Sciences",
            "guardian_name": "Dr. Das Senior",
            "guardian_phone": "+92 300 9998888",
            "address": "Gulshan-e-Iqbal Block 5",
            "matric_board": "BSEK (Karachi)",
            "matric_marks": "Above 80%",
            "inter_board": "Federal Board (FBISE)",
            "inter_marks": "70–80%",
            "inter_group": "Pre-Medical",
            "utm_source": "google_ads",
            "status": "Documents Pending",
            "message": "Interested in morning shift",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.course == "BSMT"
        assert refreshed.specialization == "Clinical Laboratory Sciences"
        assert refreshed.guardian_name == "Dr. Das Senior"
        assert refreshed.guardian_phone == "+923009998888"
        assert refreshed.address == "Gulshan-e-Iqbal Block 5"
        assert refreshed.matric_board == "BSEK (Karachi)"
        assert refreshed.matric_marks == "Above 80%"
        assert refreshed.inter_board == "Federal Board (FBISE)"
        assert refreshed.inter_marks == "70–80%"
        assert refreshed.inter_group == "Pre-Medical"
        assert refreshed.status == "Documents Pending"
        assert refreshed.message == "Interested in morning shift"


def test_edit_lead_invalid_phone_reraises_form(client, admin, lead, app):
    _login(client)
    lead_id = lead.id

    form = client.get(f"/dashboard/leads/{lead_id}/edit")
    token = _csrf(form.get_data(as_text=True))

    resp = client.post(
        f"/dashboard/leads/{lead_id}/edit",
        data={"csrf_token": token, "first_name": "Rohan", "last_name": "Das",
              "phone": "abc", "status": "New"},
    )
    # Re-renders the form (200), does not redirect, and persists nothing.
    assert resp.status_code == 200
    with app.app_context():
        # Phone is unchanged (normalised form the lead was created with).
        assert db.session.get(Lead, lead_id).phone == "+919000000000"
        assert db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="updated")
        ).all() == []


# --- duplicate badge + drill-down -----------------------------------------

def test_leads_list_shows_duplicate_badge(client, admin, app):
    """Two submissions with the same phone surface a 'Duplicates: 2' badge."""
    with app.app_context():
        db.session.add_all([
            Lead(name="Dup A", phone="+91 90000 90909", email="a@x.com"),
            Lead(name="Dup B", phone="+91 90000 90909", email="b@x.com"),
        ])
        db.session.commit()

    _login(client)
    html = client.get("/dashboard/leads").get_data(as_text=True)
    assert "Duplicates: 2" in html


def test_duplicates_drill_down_lists_matching_submissions(client, admin, app):
    """The drill-down page renders every matching submission and its columns."""
    with app.app_context():
        first = Lead(
            name="Dup A", phone="+91 90000 80808", email="a@x.com",
            course="MBA", utm_source="google",
        )
        db.session.add_all([
            first,
            Lead(name="Dup B", phone="+91 90000 80808", email="b@x.com", course="BCA"),
        ])
        db.session.commit()
        first_id = first.id

    _login(client)
    resp = client.get(f"/dashboard/leads/{first_id}/duplicates")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # The required columns and both submissions' data are present. The table
    # keys on Date/Status/Course/UTM/Assigned (not Name), so assert on those.
    assert "Submission Date" in html
    assert "UTM Source" in html
    assert "Assigned User" in html
    assert "google" in html          # first submission's utm_source
    assert "MBA" in html and "BCA" in html  # both submissions' courses
    assert "2 submissions" in html


def test_duplicates_drill_down_404_for_unknown_lead(client, admin):
    _login(client)
    assert client.get("/dashboard/leads/999999/duplicates").status_code == 404


# --- CSV export -----------------------------------------------------------

def _export_rows(client, query=""):
    """GET the export endpoint and parse it into a list of CSV rows."""
    resp = client.get(f"/dashboard/leads/export.csv{query}")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "attachment" in resp.headers["Content-Disposition"]
    text = resp.get_data(as_text=True)
    return list(csv.reader(io.StringIO(text)))


def test_export_has_header_row_and_all_leads(client, admin, app):
    with app.app_context():
        db.session.add_all([
            Lead(name="Apart", phone="+919000000001", status="New"),
            Lead(name="Bpart", phone="+919000000002", status="Interested"),
        ])
        db.session.commit()

    _login(client)
    rows = _export_rows(client)
    # Header matches the documented column order exactly.
    assert rows[0] == [
        "ID", "Created At", "Name", "First Name", "Last Name", "Phone",
        "Email", "City", "Program", "Specialization", "Guardian Name",
        "Guardian Phone", "Address", "Matric Board", "Matric Marks",
        "Inter Board", "Inter Marks", "Inter Type",
        "Status", "Source", "Next Follow-up", "Duplicate Count",
    ]
    # Two data rows (order is newest-first, but we only care about membership).
    names = {r[2] for r in rows[1:]}
    assert names == {"Apart", "Bpart"}


def test_export_respects_status_filter(client, admin, app):
    with app.app_context():
        db.session.add_all([
            Lead(name="NewOne", phone="+919000000011", status="New"),
            Lead(name="IntOne", phone="+919000000012", status="Interested"),
        ])
        db.session.commit()

    _login(client)
    rows = _export_rows(client, "?status=Interested")
    names = {r[2] for r in rows[1:]}
    assert names == {"IntOne"}


def test_export_respects_search_filter(client, admin, app):
    with app.app_context():
        db.session.add_all([
            Lead(name="Findme", phone="+919000000021", city="Pune"),
            Lead(name="Otherlead", phone="+919000000022", city="Mumbai"),
        ])
        db.session.commit()

    _login(client)
    rows = _export_rows(client, "?q=findme")
    names = {r[2] for r in rows[1:]}
    assert names == {"Findme"}


def test_export_respects_follow_up_filter(client, admin, app):
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    with app.app_context():
        db.session.add_all([
            Lead(name="Overdue", phone="+919000000031",
                 next_follow_up_at=now - timedelta(days=2)),
            Lead(name="Unscheduled", phone="+919000000032", next_follow_up_at=None),
        ])
        db.session.commit()

    _login(client)
    rows = _export_rows(client, "?follow_up=overdue")
    names = {r[2] for r in rows[1:]}
    assert names == {"Overdue"}


def test_export_duplicate_count_column_populated(client, admin, app):
    with app.app_context():
        # Two submissions sharing a phone => each has Duplicate Count 2.
        db.session.add_all([
            Lead(name="DupA", phone="+919000009999", email="a@x.com"),
            Lead(name="DupB", phone="+919000009999", email="b@x.com"),
            Lead(name="Solo", phone="+919000008888", email="solo@x.com"),
        ])
        db.session.commit()

    _login(client)
    rows = _export_rows(client)
    dup_col = {r[2]: r[-1] for r in rows[1:]}  # name -> Duplicate Count (last col)
    assert dup_col["DupA"] == "2"
    assert dup_col["DupB"] == "2"
    assert dup_col["Solo"] == "1"


def test_export_requires_login(client):
    resp = client.get("/dashboard/leads/export.csv", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
