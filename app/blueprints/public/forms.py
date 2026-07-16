"""Public-facing WTForms.

The AdmissionForm handles CSRF and first-pass field validation. Deeper
normalisation and business rules live in LeadService, so validation here is
deliberately light — enough to give the visitor immediate feedback.
"""
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField
from wtforms.validators import (
    Email,
    InputRequired,
    Length,
    Optional,
    Regexp,
)

from app.services.meta_service import get_courses

# Accepts digits, spaces, +, -, and parentheses; 7–20 chars.
_PHONE_PATTERN = r"^\+?[0-9\s\-()]{7,20}$"


class AdmissionForm(FlaskForm):
    """Landing-page admission enquiry form."""

    name = StringField(
        "Full Name",
        validators=[InputRequired("Please enter your name."), Length(min=2, max=120)],
    )
    phone = StringField(
        "Phone Number",
        validators=[
            InputRequired("Please enter your phone number."),
            Regexp(_PHONE_PATTERN, message="Please enter a valid phone number."),
        ],
    )
    email = StringField(
        "Email Address",
        validators=[Optional(), Email("Please enter a valid email."), Length(max=255)],
    )
    city = StringField("City", validators=[Optional(), Length(max=120)])
    course = SelectField("Course of Interest", validators=[Optional()])
    message = TextAreaField("Message", validators=[Optional(), Length(max=2000)])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate course choices from the meta service so the form, dashboard
        # filters, and constants never drift apart. A blank first option keeps
        # the field optional.
        self.course.choices = [("", "Select a course")] + [
            (c, c) for c in get_courses()
        ]
