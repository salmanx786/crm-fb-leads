"""Lead business logic: creation, updates, status changes, notes, deletion.

Every write goes through here so that side effects (timeline events, field
normalisation, validation) happen consistently regardless of the caller.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.constants import DEFAULT_LEAD_STATUS, is_valid_status
from app.extensions import db
from app.models import Lead, LeadNote, TimelineEvent
from app.services import meta_service
from app.utils.helpers import clean_str, normalize_email, normalize_phone
from app.utils.logger import get_logger
from app.utils.validators import is_valid_email, is_valid_phone, is_nonempty

logger = get_logger(__name__)


class LeadValidationError(ValueError):
    """Raised when submitted lead data fails server-side validation.

    Carries a field->message mapping so callers can surface per-field errors.
    """

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("Lead validation failed")


def validate_lead_payload(data: dict) -> dict[str, str]:
    """Return a dict of validation errors (empty if the payload is valid)."""
    errors: dict[str, str] = {}

    if not is_nonempty(data.get("name", ""), min_len=2):
        errors["name"] = "Please enter your full name."

    if not is_valid_phone(data.get("phone", "")):
        errors["phone"] = "Please enter a valid phone number."

    email = data.get("email")
    if email and not is_valid_email(email):
        errors["email"] = "Please enter a valid email address."

    return errors


def _record_event(
    lead: Lead, event_type: str, description: str, actor_id: Optional[int] = None
) -> None:
    """Append a timeline event. Not committed here; caller owns the transaction."""
    db.session.add(
        TimelineEvent(
            lead=lead,
            event_type=event_type,
            description=description,
            actor_id=actor_id,
        )
    )


def create_lead(data: dict, tracking: Optional[dict] = None) -> Lead:
    """Validate, normalise and persist a new lead from the public form.

    `data` holds applicant fields; `tracking` holds attribution/request
    metadata (see utils.tracking.extract_tracking). Raises
    LeadValidationError if the applicant fields are invalid.
    """
    errors = validate_lead_payload(data)
    if errors:
        raise LeadValidationError(errors)

    tracking = tracking or {}
    lead = Lead(
        name=clean_str(data.get("name"), 120),
        phone=normalize_phone(data.get("phone")),
        email=normalize_email(data.get("email")),
        city=clean_str(data.get("city"), 120),
        course=clean_str(data.get("course"), 120),
        specialization=clean_str(data.get("specialization"), 120),
        message=clean_str(data.get("message")),
        # Guardian / contact (Step 3)
        guardian_name=clean_str(data.get("guardian_name"), 120),
        guardian_phone=normalize_phone(data.get("guardian_phone")),
        address=clean_str(data.get("address"), 512),
        # Academic qualifications (Step 2). Year fields were dropped from the
        # form (addendum 2 §2); the nullable columns remain but stay empty.
        matric_board=clean_str(data.get("matric_board"), 120),
        matric_marks=clean_str(data.get("matric_marks"), 30),
        inter_board=clean_str(data.get("inter_board"), 120),
        inter_marks=clean_str(data.get("inter_marks"), 30),
        inter_group=clean_str(data.get("inter_group"), 60),
        status=DEFAULT_LEAD_STATUS,
        utm_source=clean_str(tracking.get("utm_source"), 120),
        utm_medium=clean_str(tracking.get("utm_medium"), 120),
        utm_campaign=clean_str(tracking.get("utm_campaign"), 120),
        referrer=clean_str(tracking.get("referrer"), 512),
        ip_address=clean_str(tracking.get("ip_address"), 45),
        user_agent=clean_str(tracking.get("user_agent"), 512),
    )
    db.session.add(lead)
    db.session.flush()  # assign lead.id before writing the timeline event

    _record_event(lead, "created", "Lead captured from landing page.")
    db.session.commit()
    # Log identifiers only — no phone/email PII in the log line.
    logger.info(
        "Lead created: id=%s course=%s utm_source=%s",
        lead.id, lead.course or "-", lead.utm_source or "-",
    )
    # Fire the Meta conversion event (no-op if disabled/untracked; never raises).
    meta_service.track_event(lead, "lead_created")
    return lead


def get_lead(lead_id: int) -> Optional[Lead]:
    return db.session.get(Lead, lead_id)


# Editable fields exposed by the dashboard edit form, mapped to the human
# labels used in the "Lead updated" timeline summary. Order defines the summary
# order. Internal/tracking fields (ip_address, user_agent, utm_medium/campaign,
# referrer, timestamps) are deliberately not editable here.
_EDIT_LABELS = {
    "name": "Name",
    "phone": "Phone",
    "email": "Email",
    "city": "City",
    "course": "Course",
    "status": "Status",
    "utm_source": "Source",
    "message": "Message",
}


def update_lead(lead: Lead, data: dict, actor_id: Optional[int] = None) -> Lead:
    """Update editable lead fields, recording a single timeline event.

    Reuses validate_lead_payload (name/phone/email) and is_valid_status for the
    stage. Records one "Lead updated" event summarising which fields changed,
    and is a no-op (no write, no event) when nothing changed — mirroring
    change_status' idempotence. Phone/email are intentionally not required to be
    unique, consistent with the rest of the project (see duplicate detection).
    """
    errors = validate_lead_payload({**_as_dict(lead), **data})
    status = data.get("status")
    if status is not None and not is_valid_status(status):
        errors["status"] = f"Unknown status: {status}"
    if errors:
        raise LeadValidationError(errors)

    # Normalise candidates the same way create_lead does. Required fields
    # (name/phone) fall back to the current value when submitted blank.
    candidates = {
        "name": clean_str(data.get("name"), 120) or lead.name,
        "phone": normalize_phone(data.get("phone")) or lead.phone,
        "email": normalize_email(data.get("email")),
        "city": clean_str(data.get("city"), 120),
        "course": clean_str(data.get("course"), 120),
        "status": status or lead.status,
        "utm_source": clean_str(data.get("utm_source"), 120),
        "message": clean_str(data.get("message")),
    }

    # Only the fields that actually differ from what's stored.
    changed = [f for f, v in candidates.items() if getattr(lead, f) != v]
    if not changed:
        return lead  # nothing changed; don't clutter the timeline

    status_changed = "status" in changed
    for field in changed:
        setattr(lead, field, candidates[field])

    summary = ", ".join(_EDIT_LABELS[f] for f in changed)
    _record_event(lead, "updated", f"Lead updated: {summary}", actor_id)
    db.session.commit()
    logger.info(
        "Lead updated: id=%s fields=%s by user=%s",
        lead.id, summary, actor_id if actor_id is not None else "-",
    )
    # Preserve the status-change side effect (Meta conversion) without emitting
    # a second timeline event. No-op if disabled/untracked; never raises.
    if status_changed:
        meta_service.track_event(lead, lead.status)
    return lead


def change_status(
    lead: Lead, new_status: str, actor_id: Optional[int] = None, commit: bool = True
) -> Lead:
    """Move a lead to a new lifecycle stage, recording the transition.

    `commit=False` lets a caller (e.g. bulk_action) fold this into a larger
    transaction: the field change + timeline event are staged but not
    committed, and the Meta conversion is deferred to the caller so it only
    fires once the change is durably committed.
    """
    if not is_valid_status(new_status):
        raise LeadValidationError({"status": f"Unknown status: {new_status}"})

    if new_status == lead.status:
        return lead  # no-op, don't clutter the timeline

    old_status = lead.status
    lead.status = new_status
    _record_event(
        lead,
        "status_changed",
        f"Status changed from {old_status} to {new_status}.",
        actor_id,
    )
    if not commit:
        return lead

    db.session.commit()
    logger.info(
        "Lead status changed: id=%s %s -> %s by user=%s",
        lead.id, old_status, new_status, actor_id if actor_id is not None else "-",
    )
    # Fire a Meta conversion for this status, if the status is mapped
    # (no-op if disabled/untracked; never raises).
    meta_service.track_event(lead, new_status)
    return lead


def add_note(lead: Lead, body: str, author_id: Optional[int] = None) -> LeadNote:
    """Attach a free-text note to a lead and mirror it on the timeline."""
    body = clean_str(body)
    if not body:
        raise LeadValidationError({"body": "Note cannot be empty."})

    note = LeadNote(lead=lead, body=body, author_id=author_id)
    db.session.add(note)
    _record_event(lead, "note_added", "Note added.", author_id)
    db.session.commit()
    return note


# --- follow-ups -----------------------------------------------------------
# A follow-up is just a datetime on the lead. Scheduling and rescheduling are
# the same write (set the column); only the timeline wording differs, so both
# go through set_follow_up rather than a separate schedule/reschedule pair.

_FOLLOW_UP_FMT = "%Y-%m-%d %H:%M"


def _fmt_follow_up(value: Optional[datetime]) -> str:
    """Render a follow-up datetime for timeline messages (minute precision)."""
    return value.strftime(_FOLLOW_UP_FMT) if value else ""


def set_follow_up(
    lead: Lead, when: datetime, actor_id: Optional[int] = None, commit: bool = True
) -> Lead:
    """Schedule or reschedule a lead's follow-up date.

    Records "scheduled" when there was none, "rescheduled from…to…" when the
    date moves, and is a no-op (no write, no timeline entry) when the submitted
    value matches the current one — mirroring change_status' idempotence.
    `commit=False` stages the change for a caller-owned transaction.
    """
    if when is None:
        raise LeadValidationError({"next_follow_up_at": "A follow-up date is required."})

    old = lead.next_follow_up_at
    # Compare at minute precision, the resolution staff actually pick and the
    # resolution the timeline records, so a same-value submit stays a no-op.
    if old is not None and _fmt_follow_up(old) == _fmt_follow_up(when):
        return lead  # unchanged; don't clutter the timeline

    lead.next_follow_up_at = when
    if old is None:
        description = f"Follow-up scheduled for {_fmt_follow_up(when)}"
    else:
        description = (
            f"Follow-up rescheduled from {_fmt_follow_up(old)} "
            f"to {_fmt_follow_up(when)}"
        )
    _record_event(lead, "follow_up_set", description, actor_id)
    if not commit:
        return lead

    db.session.commit()
    logger.info(
        "Lead follow-up set: id=%s at=%s by user=%s",
        lead.id, _fmt_follow_up(when), actor_id if actor_id is not None else "-",
    )
    return lead


def clear_follow_up(
    lead: Lead, actor_id: Optional[int] = None, commit: bool = True
) -> Lead:
    """Remove a lead's follow-up date, recording the change.

    No-op (no write, no timeline entry) when there is nothing scheduled.
    `commit=False` stages the change for a caller-owned transaction.
    """
    if lead.next_follow_up_at is None:
        return lead  # nothing to clear

    lead.next_follow_up_at = None
    _record_event(lead, "follow_up_cleared", "Follow-up cleared", actor_id)
    if not commit:
        return lead

    db.session.commit()
    logger.info(
        "Lead follow-up cleared: id=%s by user=%s",
        lead.id, actor_id if actor_id is not None else "-",
    )
    return lead


def delete_lead(lead: Lead, commit: bool = True) -> None:
    """Delete a lead; cascade removes its notes and timeline events.

    `commit=False` stages the delete for a caller-owned transaction.
    """
    db.session.delete(lead)
    if commit:
        db.session.commit()


# --- bulk actions ---------------------------------------------------------
# One entry point that applies a single action to many leads atomically. It
# orchestrates the existing per-lead operations with commit=False so every
# lead gets exactly the timeline events it would get individually, then owns a
# single commit/rollback boundary — no partial updates, no "bulk" event type.

BULK_ACTIONS = ("change_status", "delete", "schedule_follow_up", "clear_follow_up")


def bulk_action(
    action: str,
    lead_ids: list[int],
    actor_id: Optional[int] = None,
    status: Optional[str] = None,
    when: Optional[datetime] = None,
) -> int:
    """Apply one action to many leads inside a single transaction.

    `action` is one of BULK_ACTIONS. `status` is required for change_status;
    `when` (a datetime) for schedule_follow_up. Returns the number of leads
    processed. Raises LeadValidationError on an empty/unknown selection, an
    invalid action, or invalid action params — and rolls back so nothing is
    left partially applied. Per-lead validation and timeline events are reused
    from the single-lead operations; the Meta conversion for status changes is
    deferred until after the commit succeeds.
    """
    if action not in BULK_ACTIONS:
        raise LeadValidationError({"action": f"Unknown bulk action: {action}"})

    # De-duplicate while preserving order; reject an empty selection.
    ids = list(dict.fromkeys(lead_ids or []))
    if not ids:
        raise LeadValidationError({"leads": "Select at least one lead."})

    leads = list(db.session.scalars(select(Lead).where(Lead.id.in_(ids))))
    found = {lead.id for lead in leads}
    missing = [i for i in ids if i not in found]
    if missing:
        # A stale/tampered selection fails the whole operation (no partial run).
        raise LeadValidationError(
            {"leads": f"Some selected leads no longer exist: {missing}"}
        )

    try:
        # Track leads whose status actually changed, to fire Meta post-commit.
        status_changed: list[Lead] = []
        for lead in leads:
            if action == "change_status":
                before = lead.status
                change_status(lead, status, actor_id=actor_id, commit=False)
                if lead.status != before:
                    status_changed.append(lead)
            elif action == "schedule_follow_up":
                set_follow_up(lead, when, actor_id=actor_id, commit=False)
            elif action == "clear_follow_up":
                clear_follow_up(lead, actor_id=actor_id, commit=False)
            elif action == "delete":
                delete_lead(lead, commit=False)

        db.session.commit()
    except Exception:
        # Any failure (validation or DB) rolls back the entire batch.
        db.session.rollback()
        raise

    logger.info(
        "Bulk %s applied to %d lead(s) by user=%s",
        action, len(leads), actor_id if actor_id is not None else "-",
    )
    # Side effect only after a durable commit; never raises.
    for lead in status_changed:
        meta_service.track_event(lead, lead.status)
    return len(leads)


def _as_dict(lead: Lead) -> dict:
    """Current editable values, used to backfill partial update payloads."""
    return {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "city": lead.city,
        "course": lead.course,
        "message": lead.message,
    }
