"""Dashboard action forms (CSRF-protected)."""
from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.constants import LEAD_STATUSES


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
