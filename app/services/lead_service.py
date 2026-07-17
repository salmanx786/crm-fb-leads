"""Lead business logic: creation, updates, status changes, notes, deletion.

Every write goes through here so that side effects (timeline events, field
normalisation, validation) happen consistently regardless of the caller.
"""
from typing import Optional

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
        message=clean_str(data.get("message")),
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


def update_lead(lead: Lead, data: dict, actor_id: Optional[int] = None) -> Lead:
    """Update editable applicant fields and log the change."""
    errors = validate_lead_payload({**_as_dict(lead), **data})
    if errors:
        raise LeadValidationError(errors)

    lead.name = clean_str(data.get("name"), 120) or lead.name
    lead.phone = normalize_phone(data.get("phone")) or lead.phone
    lead.email = normalize_email(data.get("email"))
    lead.city = clean_str(data.get("city"), 120)
    lead.course = clean_str(data.get("course"), 120)
    lead.message = clean_str(data.get("message"))

    _record_event(lead, "updated", "Lead details updated.", actor_id)
    db.session.commit()
    return lead


def change_status(lead: Lead, new_status: str, actor_id: Optional[int] = None) -> Lead:
    """Move a lead to a new lifecycle stage, recording the transition."""
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


def delete_lead(lead: Lead) -> None:
    """Delete a lead; cascade removes its notes and timeline events."""
    db.session.delete(lead)
    db.session.commit()


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
