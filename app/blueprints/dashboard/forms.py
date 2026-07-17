"""Dashboard action forms (CSRF-protected)."""
from flask_wtf import FlaskForm
from wtforms import (
    DateTimeLocalField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp

from app.constants import LEAD_STATUSES
from app.services.reference_service import get_courses

# Accepts digits, spaces, +, -, and parentheses; 7–20 chars. Matches the
# public AdmissionForm so a lead's phone validates identically on edit.
_PHONE_PATTERN = r"^\+?[0-9\s\-()]{7,20}$"

# Matches the value an <input type="datetime-local"> submits (minute precision),
# which is also the precision the follow-up timeline records.
FOLLOW_UP_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


class StatusForm(FlaskForm):
    """Change a lead's status. Choices are the canonical status list."""

    status = SelectField(
        "Status",
        choices=[(s, s) for s in LEAD_STATUSES],
        validators=[DataRequired()],
    )


class NoteForm(FlaskForm):
    """Attach a free-text note to a lead."""

    body = TextAreaField(
        "Note",
        validators=[DataRequired("Note cannot be empty."), Length(max=5000)],
    )


class FollowUpForm(FlaskForm):
    """Schedule or reschedule a lead's follow-up date.

    Clearing is a separate POST (no date to validate), so this form only
    covers the set/reschedule path and requires a parseable datetime.
    """

    next_follow_up_at = DateTimeLocalField(
        "Follow-up date",
        format=FOLLOW_UP_INPUT_FORMAT,
        validators=[DataRequired("Please choose a follow-up date and time.")],
    )


class LeadEditForm(FlaskForm):
    """Edit a lead's applicant fields, status, and source.

    Field names match Lead attributes so the route can prefill with
    `LeadEditForm(obj=lead)` and hand `form.data` straight to
    lead_service.update_lead. First-pass shape checks only — normalisation
    and the change/timeline logic stay in the service (single source of
    truth), so this never duplicates business rules. Uniqueness is not
    enforced: the project deliberately allows duplicate phone/email.
    """

    name = StringField(
        "Name",
        validators=[DataRequired("Please enter the lead's name."), Length(min=2, max=120)],
    )
    phone = StringField(
        "Phone",
        validators=[
            DataRequired("Please enter a phone number."),
            Regexp(_PHONE_PATTERN, message="Please enter a valid phone number."),
        ],
    )
    email = StringField(
        "Email",
        validators=[Optional(), Email("Please enter a valid email."), Length(max=255)],
    )
    city = StringField("City", validators=[Optional(), Length(max=120)])
    course = SelectField("Course", validators=[Optional()])
    # "Source" is stored as utm_source on the model.
    utm_source = StringField("Source", validators=[Optional(), Length(max=120)])
    status = SelectField(
        "Status",
        choices=[(s, s) for s in LEAD_STATUSES],
        validators=[DataRequired()],
    )
    # "Notes" maps to the lead's free-text message field.
    message = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blank option keeps course optional; choices come from the same
        # source as the public form so they never drift.
        self.course.choices = [("", "Select a course")] + [
            (c, c) for c in get_courses()
        ]


# Bulk action choices surfaced in the leads-list dropdown. Values match
# lead_service.BULK_ACTIONS so the form and service never drift.
BULK_ACTION_CHOICES = [
    ("", "Bulk actions…"),
    ("change_status", "Change Status"),
    ("schedule_follow_up", "Schedule Follow-up"),
    ("clear_follow_up", "Clear Follow-up"),
    ("delete", "Delete"),
]


class BulkActionForm(FlaskForm):
    """Apply one action to the checked leads on the list page.

    Only covers CSRF + the action selector and its two optional parameters
    (status, follow-up datetime). The checked lead ids are a dynamic list read
    from request.form in the route, and the real per-action validation lives in
    lead_service.bulk_action — so this form stays a thin input container and
    never duplicates business rules. The status/datetime fields are Optional
    here because they only apply to their respective actions; the service
    rejects a missing value for the action that needs it.
    """

    action = SelectField(
        "Action",
        choices=BULK_ACTION_CHOICES,
        validators=[DataRequired("Choose a bulk action.")],
    )
    status = SelectField(
        "Status",
        choices=[("", "Select a status")] + [(s, s) for s in LEAD_STATUSES],
        validators=[Optional()],
    )
    next_follow_up_at = DateTimeLocalField(
        "Follow-up date",
        format=FOLLOW_UP_INPUT_FORMAT,
        validators=[Optional()],
    )
