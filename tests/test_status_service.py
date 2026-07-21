"""Tests for the admin-editable lead-status service.

Covers seeding from the legacy constants, add/rename/delete/reorder, the
delete guards (protected + in-use), case-insensitive uniqueness, and the
status->Meta-event resolution that drives conversion tracking.
"""
import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Lead, LeadStatus
from app.services import status_service
from app.services.status_service import StatusError


# --- seeding --------------------------------------------------------------

def test_seed_defaults_reproduces_constants(app):
    """The conftest fixture already seeds; seeding again is a no-op, and the
    seeded rows match the legacy constants (names, order, Meta mapping)."""
    from app.constants import LEAD_STATUSES, META_EVENT_MAP, DEFAULT_LEAD_STATUS

    # Already seeded by the fixture -> idempotent second call creates nothing.
    assert status_service.seed_defaults() == 0

    rows = status_service.get_status_rows()
    assert [r.name for r in rows] == LEAD_STATUSES
    for r in rows:
        assert r.meta_event == META_EVENT_MAP.get(r.name)
    protected = [r for r in rows if r.is_protected]
    assert [r.name for r in protected] == [DEFAULT_LEAD_STATUS]


# --- add ------------------------------------------------------------------

def test_add_status_appends_with_meta_event(app):
    row = status_service.add_status("Visited", "Schedule")
    assert row.meta_event == "Schedule"
    # Appended at the end of the order.
    assert status_service.get_statuses()[-1] == "Visited"


def test_add_status_rejects_blank(app):
    with pytest.raises(StatusError):
        status_service.add_status("   ", None)


def test_add_status_rejects_duplicate_case_insensitive(app):
    with pytest.raises(StatusError):
        status_service.add_status("interested", "Lead")  # "Interested" seeded


def test_add_status_unknown_meta_event_is_dropped(app):
    """An event outside the whitelist coerces to None rather than erroring."""
    row = status_service.add_status("Not serious", "Bogus")
    assert row.meta_event is None


# --- rename cascades ------------------------------------------------------

def test_rename_cascades_to_existing_leads(app):
    row = next(r for r in status_service.get_status_rows() if r.name == "Interested")

    # Two leads sit on "Interested".
    db.session.add_all([
        Lead(name="A", phone="111", status="Interested"),
        Lead(name="B", phone="222", status="Interested"),
    ])
    db.session.commit()

    status_service.rename_status(row.id, "Hot Lead")

    # Row renamed AND both leads moved in the same transaction.
    assert status_service.is_valid_status("Hot Lead")
    moved = db.session.scalar(
        select(func.count(Lead.id)).where(Lead.status == "Hot Lead")
    )
    assert moved == 2
    assert db.session.scalar(
        select(func.count(Lead.id)).where(Lead.status == "Interested")
    ) == 0


def test_rename_preserves_meta_mapping(app):
    row = next(r for r in status_service.get_status_rows() if r.name == "Interested")
    status_service.rename_status(row.id, "Hot Lead")
    # "Interested" mapped to "Lead" in the seed; the mapping follows the rename.
    assert status_service.meta_event_for("Hot Lead") == "Lead"


def test_rename_rejects_duplicate(app):
    row = next(r for r in status_service.get_status_rows() if r.name == "Called")
    with pytest.raises(StatusError):
        status_service.rename_status(row.id, "Interested")


# --- delete guards --------------------------------------------------------

def test_delete_blocked_while_leads_use_it(app):
    row = next(r for r in status_service.get_status_rows() if r.name == "Called")
    db.session.add(Lead(name="C", phone="333", status="Called"))
    db.session.commit()

    with pytest.raises(StatusError):
        status_service.delete_status(row.id)
    # Still present.
    assert status_service.is_valid_status("Called")


def test_delete_protected_default_blocked(app):
    row = next(r for r in status_service.get_status_rows() if r.is_protected)
    with pytest.raises(StatusError):
        status_service.delete_status(row.id)


def test_delete_unused_status_succeeds(app):
    row = status_service.add_status("Temp", None)
    status_service.delete_status(row.id)
    assert not status_service.is_valid_status("Temp")


# --- meta event mapping ---------------------------------------------------

def test_set_meta_event_updates_and_clears(app):
    row = next(r for r in status_service.get_status_rows() if r.name == "Called")
    status_service.set_meta_event(row.id, "Contact")
    assert status_service.meta_event_for("Called") == "Contact"
    status_service.set_meta_event(row.id, None)
    assert status_service.meta_event_for("Called") is None


def test_meta_event_for_unknown_status_is_none(app):
    assert status_service.meta_event_for("Nonexistent") is None


# --- reorder --------------------------------------------------------------

def test_reorder_sets_display_order(app):
    rows = status_service.get_status_rows()
    reversed_ids = [r.id for r in reversed(rows)]
    status_service.reorder(reversed_ids)
    assert [r.id for r in status_service.get_status_rows()] == reversed_ids
