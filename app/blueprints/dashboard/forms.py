"""Dashboard action forms (CSRF-protected)."""
from flask_wtf import FlaskForm
from wtforms import DateTimeLocalField, SelectField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.constants import LEAD_STATUSES

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
