"""Tests for the dashboard service (metrics + search) and the seed CLI.

These exercise the read-side query layer directly (no HTTP), plus the
`seed-demo-data` Click command through Flask's CliRunner.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Lead, LeadNote, TimelineEvent
from app.services import dashboard_service


def _make_lead(app, **overrides):
    """Insert a Lead directly with sensible defaults; return its id."""
    data = {
        "name": "Test Lead",
        "phone": "+91 90000 00000",
        "email": "test@example.com",
        "city": "Pune",
        "course": "MBA",
        "status": "New",
    }
    data.update(overrides)
    with app.app_context():
        lead = Lead(**data)
        db.session.add(lead)
        db.session.commit()
        return lead.id


# --- metrics --------------------------------------------------------------

def test_metrics_counts_by_time_and_status(app):
    now = datetime.utcnow()
    with app.app_context():
        # Two leads today (one New, one Interested), one last week (Admitted).
        db.session.add_all([
            Lead(name="A", phone="+91 90000 00001", status="New", created_at=now),
            Lead(name="B", phone="+91 90000 00002", status="Interested", created_at=now),
            Lead(
                name="C", phone="+91 90000 00003", status="Admitted",
                created_at=now - timedelta(days=10),
            ),
        ])
        db.session.commit()

        metrics = dashboard_service.get_metrics()

    assert metrics["total"] == 3
    assert metrics["today"] == 2
    assert metrics["new"] == 1
    assert metrics["interested"] == 1
    assert metrics["admitted"] == 1
    # New keys the milestone requires are present.
    assert "follow_up" in metrics
    assert "documents_pending" in metrics


def test_metrics_empty_database_is_all_zero(app):
    with app.app_context():
        metrics = dashboard_service.get_metrics()
    assert metrics["total"] == 0
    assert all(isinstance(v, int) for v in metrics.values())


# --- search ---------------------------------------------------------------

def test_search_matches_city_case_insensitively(app):
    _make_lead(app, name="Nagpur Person", city="Nagpur", phone="+91 90000 11111")
    _make_lead(app, name="Other Person", city="Mumbai", phone="+91 90000 22222")
    with app.app_context():
        result = dashboard_service.list_leads(search="nagpur")
    assert result.total == 1
    assert result.items[0].city == "Nagpur"


def test_search_matches_course_case_insensitively(app):
    _make_lead(app, name="BCA Person", course="BCA", phone="+91 90000 33333")
    _make_lead(app, name="MBA Person", course="MBA", phone="+91 90000 44444")
    with app.app_context():
        result = dashboard_service.list_leads(search="bca")
    assert result.total == 1
    assert result.items[0].course == "BCA"


def test_search_still_matches_name_phone_email(app):
    _make_lead(app, name="Findable Name", email="unique@example.com", phone="+91 98888 00000")
    with app.app_context():
        assert dashboard_service.list_leads(search="Findable").total == 1
        assert dashboard_service.list_leads(search="unique@example").total == 1
        assert dashboard_service.list_leads(search="98888").total == 1


def test_period_filter_bounds_by_creation_time(app):
    now = datetime.utcnow()
    _make_lead(app, name="Recent", created_at=now, phone="+91 90000 55555")
    _make_lead(app, name="Old", created_at=now - timedelta(days=10), phone="+91 90000 66666")
    with app.app_context():
        assert dashboard_service.list_leads(period="today").total == 1
        assert dashboard_service.list_leads(period="week").total == 1
        assert dashboard_service.list_leads().total == 2


# --- seed-demo-data CLI ---------------------------------------------------

def test_seed_demo_data_creates_leads_events_and_notes(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-demo-data", "--count", "20"])

    assert result.exit_code == 0, result.output
    assert "Seeded 20 demo leads" in result.output

    with app.app_context():
        assert db.session.scalar(select(func.count(Lead.id))) == 20
        # Every lead gets at least a "created" event.
        assert db.session.scalar(select(func.count(TimelineEvent.id))) >= 20
        # Some notes were generated (probabilistic but effectively certain at n=20).
        assert db.session.scalar(select(func.count(LeadNote.id))) >= 1
        # Seeded statuses are all valid lifecycle stages.
        from app.constants import LEAD_STATUSES
        statuses = set(db.session.scalars(select(Lead.status)))
        assert statuses.issubset(set(LEAD_STATUSES))
