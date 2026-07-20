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


# --- lead editing (update_lead) -------------------------------------------

def test_update_lead_changes_fields_and_records_single_event(app):
    """A successful edit updates fields and logs one 'updated' event."""
    # Phone stored already-normalised so resubmitting it isn't seen as a change.
    lead_id = _make_lead(
        app, first_name="Old", last_name="Name", name="Old Name",
        phone="+919000080001", course="MBA",
    )
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.update_lead(
            lead,
            {"first_name": "New", "last_name": "Name", "phone": lead.phone,
             "email": lead.email, "city": lead.city, "course": "BCA",
             "status": "Interested"},
        )

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.first_name == "New"
        assert refreshed.name == "New Name"  # composed display value stays in sync
        assert refreshed.course == "BCA"
        assert refreshed.status == "Interested"

        updated = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="updated")
        ).all()
        assert len(updated) == 1
        # Summary lists only the fields that changed, in label order.
        assert updated[0].description == "Lead updated: First Name, Course, Status"


def test_update_lead_source_maps_to_utm_source(app):
    """The 'Source' field edits utm_source on the model."""
    lead_id = _make_lead(app, phone="+91 90000 80002")
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.update_lead(lead, {"utm_source": "walk-in"})
        assert db.session.get(Lead, lead_id).utm_source == "walk-in"


def test_update_lead_no_change_does_not_record_event(app):
    """Resubmitting identical values is a no-op: no 'updated' event."""
    # All values stored in already-normalised form so resubmitting is a no-op.
    lead_id = _make_lead(
        app, first_name="Same", last_name="Name", name="Same Name",
        phone="+919000080003", course="MBA",
    )
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        lead_service.update_lead(
            lead,
            {"first_name": "Same", "last_name": "Name", "phone": lead.phone,
             "email": lead.email, "city": lead.city, "course": "MBA",
             "status": lead.status},
        )
        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="updated")
        ).all()
        assert events == []


def test_update_lead_invalid_phone_raises_and_does_not_persist(app):
    """Validation reuses validate_lead_payload; bad phone rolls back cleanly."""
    lead_id = _make_lead(app, name="Keep", phone="+91 90000 80004")
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.update_lead(lead, {"phone": "abc"})

        refreshed = db.session.get(Lead, lead_id)
        assert refreshed.phone == "+91 90000 80004"
        assert db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead_id, event_type="updated")
        ).all() == []


def test_update_lead_invalid_status_raises(app):
    lead_id = _make_lead(app, phone="+91 90000 80005")
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.update_lead(lead, {"status": "Bogus"})


# --- bulk actions (bulk_action) -------------------------------------------

def _make_bulk_leads(app, n=3, **overrides):
    """Insert n leads with distinct phones; return their ids in order."""
    ids = []
    for i in range(n):
        ids.append(_make_lead(app, name=f"Bulk {i}", phone=f"+9190000900{i:02d}", **overrides))
    return ids


def test_bulk_change_status_updates_all_and_records_events(app):
    ids = _make_bulk_leads(app, 3, status="New")
    with app.app_context():
        processed = lead_service.bulk_action("change_status", ids, status="Interested")
        assert processed == 3
        for lead_id in ids:
            lead = db.session.get(Lead, lead_id)
            assert lead.status == "Interested"
            # Same event a single change_status would produce — no "bulk" type.
            events = db.session.scalars(
                select(TimelineEvent).filter_by(lead_id=lead_id, event_type="status_changed")
            ).all()
            assert len(events) == 1


def test_bulk_delete_removes_all_selected(app):
    ids = _make_bulk_leads(app, 3)
    with app.app_context():
        processed = lead_service.bulk_action("delete", ids)
        assert processed == 3
        remaining = db.session.scalar(select(func.count(Lead.id)))
        assert remaining == 0


def test_bulk_schedule_follow_up_sets_all(app):
    ids = _make_bulk_leads(app, 3)
    when = datetime(2026, 8, 1, 10, 30)
    with app.app_context():
        processed = lead_service.bulk_action("schedule_follow_up", ids, when=when)
        assert processed == 3
        for lead_id in ids:
            lead = db.session.get(Lead, lead_id)
            assert lead.next_follow_up_at == when
            events = db.session.scalars(
                select(TimelineEvent).filter_by(lead_id=lead_id, event_type="follow_up_set")
            ).all()
            assert len(events) == 1


def test_bulk_clear_follow_up_clears_all(app):
    ids = _make_bulk_leads(app, 2)
    when = datetime(2026, 8, 1, 10, 30)
    with app.app_context():
        lead_service.bulk_action("schedule_follow_up", ids, when=when)
        processed = lead_service.bulk_action("clear_follow_up", ids)
        assert processed == 2
        for lead_id in ids:
            lead = db.session.get(Lead, lead_id)
            assert lead.next_follow_up_at is None
            cleared = db.session.scalars(
                select(TimelineEvent).filter_by(lead_id=lead_id, event_type="follow_up_cleared")
            ).all()
            assert len(cleared) == 1


def test_bulk_invalid_status_rolls_back_everything(app):
    """An invalid status fails the batch: no lead changes, no events written."""
    ids = _make_bulk_leads(app, 3, status="New")
    with app.app_context():
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.bulk_action("change_status", ids, status="Bogus")

        # Nothing was applied — every lead keeps its original status, and no
        # status_changed events leaked from leads processed before the failure.
        for lead_id in ids:
            assert db.session.get(Lead, lead_id).status == "New"
        assert db.session.scalar(
            select(func.count(TimelineEvent.id)).where(
                TimelineEvent.event_type == "status_changed"
            )
        ) == 0


def test_bulk_missing_lead_rolls_back_everything(app):
    """A stale id in the selection fails the whole batch (no partial delete)."""
    ids = _make_bulk_leads(app, 2)
    with app.app_context():
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.bulk_action("delete", ids + [999999])
        # Both real leads survive.
        assert db.session.scalar(select(func.count(Lead.id))) == 2


def test_bulk_rolls_back_staged_writes_when_a_later_lead_fails(app, monkeypatch):
    """Prove atomicity: if lead #3 fails mid-batch, #1 and #2's staged status
    changes are discarded — not just that validation happens up front."""
    ids = _make_bulk_leads(app, 3, status="New")
    real_change_status = lead_service.change_status
    calls = {"n": 0}

    def flaky_change_status(lead, new_status, actor_id=None, commit=True):
        calls["n"] += 1
        if calls["n"] == 3:  # third lead blows up after the first two are staged
            raise RuntimeError("boom")
        return real_change_status(lead, new_status, actor_id=actor_id, commit=commit)

    # bulk_action calls change_status as a module global, so patching it here
    # is what the orchestrator will actually invoke.
    monkeypatch.setattr(lead_service, "change_status", flaky_change_status)

    with app.app_context():
        with pytest.raises(RuntimeError):
            lead_service.bulk_action("change_status", ids, status="Interested")

        # The two leads mutated before the failure must be rolled back to "New".
        for lead_id in ids:
            assert db.session.get(Lead, lead_id).status == "New"
        assert db.session.scalar(
            select(func.count(TimelineEvent.id)).where(
                TimelineEvent.event_type == "status_changed"
            )
        ) == 0


def test_bulk_empty_selection_raises(app):
    with app.app_context():
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.bulk_action("delete", [])


def test_bulk_invalid_action_raises(app):
    ids = _make_bulk_leads(app, 1)
    with app.app_context():
        with pytest.raises(lead_service.LeadValidationError):
            lead_service.bulk_action("frobnicate", ids)


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
