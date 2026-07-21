"""Admin-editable lead statuses + their Meta (Facebook) event mapping.

Backed by the ``LeadStatus`` table. This service is the single source of truth
for which lead statuses exist, their display order, and which standard Meta
event each one reports when a lead reaches it. It replaces the hardcoded
``constants.LEAD_STATUSES`` / ``constants.META_EVENT_MAP`` for status triggers;
those constants remain only as the one-time seed source (``seed_defaults``) so a
fresh table reproduces today's exact behaviour.

Design mirrors ``settings_service``/``content_service``: routes and forms ask
this service for their dropdown options instead of importing a constant, so the
status list can change at runtime without a code edit or migration.

Rename/remove policy (product decision):
- Rename cascades: the row is renamed AND every lead on the old status is moved
  to the new name in the same transaction, so no lead is left on a dead status.
- Delete is blocked while any lead still uses the status (and the protected
  default "New" can never be deleted) — this avoids silently orphaning leads.
  Rename covers the "I picked a bad name" case.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, update

from app.constants import (
    DEFAULT_LEAD_STATUS,
    LEAD_STATUSES,
    META_EVENT_MAP,
)
from app.extensions import db
from app.models import Lead, LeadStatus
from app.utils.logger import get_logger

logger = get_logger("app.status_service")


class StatusError(Exception):
    """Raised on an invalid status operation. Message is user-safe."""


# The standard, optimizable Meta events an admin may map a status to. Kept as a
# fixed whitelist so an admin can only choose an event Meta actually accepts —
# never free-type a name Meta would silently reject. NULL/"" means don't send.
META_EVENT_CHOICES: tuple[str, ...] = (
    "Lead",
    "Contact",
    "Schedule",
    "SubmitApplication",
    "CompleteRegistration",
    "Purchase",
)


def _clean_name(name: Optional[str]) -> str:
    return (name or "").strip()


def _normalise_event(event: Optional[str]) -> Optional[str]:
    """Coerce a submitted Meta-event value to a whitelisted event or None."""
    event = (event or "").strip()
    return event if event in META_EVENT_CHOICES else None


# --- reads ----------------------------------------------------------------

def _all_rows() -> list[LeadStatus]:
    return list(
        db.session.scalars(
            db.select(LeadStatus).order_by(LeadStatus.sort_order, LeadStatus.id)
        )
    )


def get_status_rows() -> list[LeadStatus]:
    """Full status rows, in display order — for the settings screen."""
    return _all_rows()


def get_statuses() -> list[str]:
    """All valid status names, in lifecycle order — for dropdowns/filters."""
    return [row.name for row in _all_rows()]


def is_valid_status(name: str) -> bool:
    """True if ``name`` is a currently-defined status."""
    return db.session.scalar(
        db.select(func.count(LeadStatus.id)).where(LeadStatus.name == name)
    ) > 0


def meta_event_for(status: str) -> Optional[str]:
    """The Meta event a status reports, or None if unmapped / unknown."""
    row = db.session.scalar(db.select(LeadStatus).where(LeadStatus.name == status))
    return row.meta_event if row is not None else None


def leads_using(name: str) -> int:
    """How many leads currently sit on this status (for delete guards/UI)."""
    return db.session.scalar(
        db.select(func.count(Lead.id)).where(Lead.status == name)
    )


# --- writes ---------------------------------------------------------------

def _next_sort_order() -> int:
    current = db.session.scalar(db.select(func.max(LeadStatus.sort_order)))
    return (current or 0) + 1


def add_status(name: str, meta_event: Optional[str] = None) -> LeadStatus:
    """Create a new status. Name must be non-empty and unique (case-insensitive)."""
    name = _clean_name(name)
    if not name:
        raise StatusError("Status name can't be blank.")
    if len(name) > 64:
        raise StatusError("Status name is too long (max 64 characters).")
    existing = db.session.scalar(
        db.select(LeadStatus).where(func.lower(LeadStatus.name) == name.lower())
    )
    if existing is not None:
        raise StatusError(f"A status named “{existing.name}” already exists.")

    row = LeadStatus(
        name=name,
        meta_event=_normalise_event(meta_event),
        sort_order=_next_sort_order(),
        is_protected=False,
    )
    db.session.add(row)
    db.session.commit()
    logger.info("Lead status added: %s (meta=%s)", row.name, row.meta_event or "-")
    return row


def rename_status(status_id: int, new_name: str) -> LeadStatus:
    """Rename a status and cascade the new name to every lead using the old one.

    The row rename and the bulk lead update run in one transaction, so leads are
    never left pointing at a name that no longer exists.
    """
    row = db.session.get(LeadStatus, status_id)
    if row is None:
        raise StatusError("That status no longer exists.")

    new_name = _clean_name(new_name)
    if not new_name:
        raise StatusError("Status name can't be blank.")
    if len(new_name) > 64:
        raise StatusError("Status name is too long (max 64 characters).")
    if new_name == row.name:
        return row  # no-op

    clash = db.session.scalar(
        db.select(LeadStatus).where(
            func.lower(LeadStatus.name) == new_name.lower(),
            LeadStatus.id != row.id,
        )
    )
    if clash is not None:
        raise StatusError(f"A status named “{clash.name}” already exists.")

    old_name = row.name
    row.name = new_name
    # Cascade to existing leads in the same transaction.
    affected = db.session.execute(
        update(Lead).where(Lead.status == old_name).values(status=new_name)
    ).rowcount
    db.session.commit()
    logger.info(
        "Lead status renamed: %s -> %s (%s leads moved)",
        old_name, new_name, affected,
    )
    return row


def set_meta_event(status_id: int, meta_event: Optional[str]) -> LeadStatus:
    """Set (or clear) the Meta event a status reports."""
    row = db.session.get(LeadStatus, status_id)
    if row is None:
        raise StatusError("That status no longer exists.")
    row.meta_event = _normalise_event(meta_event)
    db.session.commit()
    logger.info(
        "Lead status meta mapping set: %s -> %s", row.name, row.meta_event or "(none)"
    )
    return row


def delete_status(status_id: int) -> None:
    """Delete a status. Blocked for the protected default or while leads use it."""
    row = db.session.get(LeadStatus, status_id)
    if row is None:
        return  # already gone; idempotent
    if row.is_protected:
        raise StatusError(f"“{row.name}” is the default status and can't be deleted.")
    in_use = leads_using(row.name)
    if in_use:
        raise StatusError(
            f"{in_use} lead(s) still use “{row.name}”. "
            "Rename it or move those leads to another status first."
        )
    db.session.delete(row)
    db.session.commit()
    logger.info("Lead status deleted: %s", row.name)


def reorder(ordered_ids: list[int]) -> None:
    """Persist a new display order from a list of status ids (first = top)."""
    for position, status_id in enumerate(ordered_ids):
        row = db.session.get(LeadStatus, status_id)
        if row is not None:
            row.sort_order = position
    db.session.commit()


# --- seeding --------------------------------------------------------------

def seed_defaults() -> int:
    """Seed the table from the legacy constants on first run.

    Idempotent: does nothing if any status already exists. Reproduces today's
    exact statuses (order preserved) and status->Meta-event mapping, so a fresh
    deployment behaves identically until an admin edits something. Returns the
    number of rows created.
    """
    if db.session.scalar(db.select(func.count(LeadStatus.id))):
        return 0  # already seeded

    for order, name in enumerate(LEAD_STATUSES):
        db.session.add(
            LeadStatus(
                name=name,
                meta_event=META_EVENT_MAP.get(name),  # None if unmapped
                sort_order=order,
                is_protected=(name == DEFAULT_LEAD_STATUS),
            )
        )
    db.session.commit()
    count = len(LEAD_STATUSES)
    logger.info("Seeded %s default lead statuses.", count)
    return count
