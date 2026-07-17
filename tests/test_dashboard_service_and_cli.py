"""Tests for the dashboard service (metrics + search) and the seed CLI.

These exercise the read-side query layer directly (no HTTP), plus the
`seed-demo-data` Click command through Flask's CliRunner.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Lead, LeadNote, TimelineEvent
from app.services import dashboard_service, lead_service, lead_service


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


# --- follow-up service (schedule / reschedule / clear) --------------------

def _fmt(dt):
    """Minute-precision string, matching lead_service's timeline wording."""
    return dt.strftime("%Y-%m-%d %H:%M")


def test_schedule_follow_up_sets_date_and_records_event(app):
    lead_id = _make_lead(app, phone="+91 90000 A0001")
    when = datetime(2026, 7, 25, 10, 30)
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.set_follow_up(lead, when)

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.next_follow_up_at == when

        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="follow_up_set")
        ).all()
        assert len(events) == 1
        assert events[0].description == f"Follow-up scheduled for {_fmt(when)}"


def test_reschedule_follow_up_records_from_to_event(app):
    lead_id = _make_lead(app, phone="+91 90000 A0002")
    first = datetime(2026, 7, 25, 9, 0)
    second = datetime(2026, 7, 28, 15, 0)
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.set_follow_up(lead, first)
        lead_service.set_follow_up(lead, second)

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.next_follow_up_at == second

        events = db.session.scalars(
            select(TimelineEvent)
            .filter_by(lead_id=lead_id, event_type="follow_up_set")
            .order_by(TimelineEvent.id)
        ).all()
        assert len(events) == 2
        assert events[1].description == (
            f"Follow-up rescheduled from {_fmt(first)} to {_fmt(second)}"
        )


def test_clear_follow_up_removes_date_and_records_event(app):
    lead_id = _make_lead(app, phone="+91 90000 A0003")
    when = datetime(2026, 7, 25, 10, 30)
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.set_follow_up(lead, when)
        lead_service.clear_follow_up(lead)

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.next_follow_up_at is None

        cleared = db.session.scalars(
            select(TimelineEvent).filter_by(
                lead_id=lead_id, event_type="follow_up_cleared"
            )
        ).all()
        assert len(cleared) == 1
        assert cleared[0].description == "Follow-up cleared"


def test_set_same_follow_up_value_is_noop(app):
    lead_id = _make_lead(app, phone="+91 90000 A0004")
    when = datetime(2026, 7, 25, 10, 30)
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.set_follow_up(lead, when)
        # Submitting the identical value again writes nothing new.
        lead_service.set_follow_up(lead, when)

        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="follow_up_set")
        ).all()
        assert len(events) == 1


def test_clear_follow_up_when_none_is_noop(app):
    lead_id = _make_lead(app, phone="+91 90000 A0005")
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.clear_follow_up(lead)  # nothing scheduled
        cleared = db.session.scalars(
            select(TimelineEvent).filter_by(
                lead_id=lead_id, event_type="follow_up_cleared"
            )
        ).all()
        assert cleared == []


# --- follow-up dashboard filters (database-level) -------------------------

def _seed_follow_up_leads(app):
    """One lead in each follow-up state; returns their ids by state."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ids = {
        "overdue": _make_lead(
            app, name="Overdue", phone="+91 90000 B0001",
            next_follow_up_at=today - timedelta(days=1),
        ),
        "today": _make_lead(
            app, name="Today", phone="+91 90000 B0002",
            next_follow_up_at=today + timedelta(hours=9),
        ),
        "upcoming": _make_lead(
            app, name="Upcoming", phone="+91 90000 B0003",
            next_follow_up_at=today + timedelta(days=3),
        ),
        "none": _make_lead(
            app, name="NoFollowUp", phone="+91 90000 B0004",
            next_follow_up_at=None,
        ),
    }
    return ids


def test_overdue_filter_selects_only_past_follow_ups(app):
    _seed_follow_up_leads(app)
    with app.app_context():
        result = dashboard_service.list_leads(follow_up="overdue")
    assert result.total == 1
    assert result.items[0].name == "Overdue"


def test_today_filter_selects_only_todays_follow_ups(app):
    _seed_follow_up_leads(app)
    with app.app_context():
        result = dashboard_service.list_leads(follow_up="today")
    assert result.total == 1
    assert result.items[0].name == "Today"


def test_upcoming_filter_selects_only_future_follow_ups(app):
    _seed_follow_up_leads(app)
    with app.app_context():
        result = dashboard_service.list_leads(follow_up="upcoming")
    assert result.total == 1
    assert result.items[0].name == "Upcoming"


def test_no_follow_up_filter_selects_only_unscheduled(app):
    _seed_follow_up_leads(app)
    with app.app_context():
        result = dashboard_service.list_leads(follow_up="no_follow_up")
    assert result.total == 1
    assert result.items[0].name == "NoFollowUp"


def test_follow_up_state_classifier_matches_filters(app):
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    assert dashboard_service.follow_up_state(None) is None
    assert dashboard_service.follow_up_state(today - timedelta(days=1)) == "overdue"
    assert dashboard_service.follow_up_state(today + timedelta(hours=9)) == "today"
    assert dashboard_service.follow_up_state(today + timedelta(days=3)) == "upcoming"


# --- duplicate detection --------------------------------------------------

def test_duplicate_by_phone(app):
    """Two submissions sharing a phone are each counted as a group of 2."""
    with app.app_context():
        db.session.add_all([
            Lead(name="First", phone="+91 90000 77777", email="a@example.com"),
            Lead(name="Second", phone="+91 90000 77777", email="b@example.com"),
        ])
        db.session.commit()
        leads = list(db.session.scalars(select(Lead)))

        counts = dashboard_service.duplicate_counts(leads)
        assert all(c == 2 for c in counts.values())

        # Drill-down lists both submissions, newest first.
        matches = dashboard_service.matching_submissions(leads[0])
        assert len(matches) == 2
        assert {m.name for m in matches} == {"First", "Second"}


def test_duplicate_by_email(app):
    """Same email but different phones still forms one duplicate group."""
    with app.app_context():
        db.session.add_all([
            Lead(name="First", phone="+91 90000 11111", email="dup@example.com"),
            Lead(name="Second", phone="+91 90000 22222", email="dup@example.com"),
        ])
        db.session.commit()
        leads = list(db.session.scalars(select(Lead)))

        counts = dashboard_service.duplicate_counts(leads)
        assert all(c == 2 for c in counts.values())

        matches = dashboard_service.matching_submissions(leads[0])
        assert len(matches) == 2


def test_no_duplicate(app):
    """Distinct phone and email means a group of just the lead itself."""
    with app.app_context():
        db.session.add_all([
            Lead(name="Alone One", phone="+91 90000 33333", email="one@example.com"),
            Lead(name="Alone Two", phone="+91 90000 44444", email="two@example.com"),
        ])
        db.session.commit()
        leads = list(db.session.scalars(select(Lead)))

        counts = dashboard_service.duplicate_counts(leads)
        assert all(c == 1 for c in counts.values())

        matches = dashboard_service.matching_submissions(leads[0])
        assert len(matches) == 1


def test_duplicate_counts_no_double_count_when_phone_and_email_match(app):
    """A lead matching another on BOTH phone and email counts it once."""
    with app.app_context():
        db.session.add_all([
            Lead(name="First", phone="+91 90000 55555", email="same@example.com"),
            Lead(name="Second", phone="+91 90000 55555", email="same@example.com"),
        ])
        db.session.commit()
        leads = list(db.session.scalars(select(Lead)))

        counts = dashboard_service.duplicate_counts(leads)
        assert all(c == 2 for c in counts.values())


def test_duplicate_counts_empty_list_is_empty(app):
    with app.app_context():
        assert dashboard_service.duplicate_counts([]) == {}


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
