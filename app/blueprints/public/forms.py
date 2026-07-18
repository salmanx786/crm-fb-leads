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

from app.services.reference_service import (
    get_bsmt_specializations,
    get_courses,
    get_education_boards,
    get_intermediate_types,
    get_marks_ranges,
)

# Accepts digits, spaces, +, -, and parentheses; 7–20 chars.
_PHONE_PATTERN = r"^\+?[0-9\s\-()]{7,20}$"


class AdmissionForm(FlaskForm):
    """Landing-page admission enquiry form (multi-step DPT / BSMT).

    The template drives the 3-step UX; server-side this is one form. Fields
    map 1:1 to Lead columns so the route hands `form`-derived data straight to
    lead_service.create_lead. Only program, name, and phone are strictly
    required — academic and guardian fields are Optional so a partially
    completed but still useful lead is never lost.
    """

    # --- Step 1: program selection ---
    course = SelectField(
        "Which program are you applying for?",
        validators=[InputRequired("Please choose a program.")],
    )
    specialization = SelectField(
        "Which BSMT specialization?",
        validators=[Optional()],
    )

    # --- Step 2: academic qualifications ---
    # Boards and marks are dropdowns (choices populated in __init__) so lead
    # data stays clean. Year fields were removed — not needed at lead capture.
    matric_board = SelectField("Matric Board", validators=[Optional()])
    matric_marks = SelectField("Matric Marks", validators=[Optional()])
    inter_board = SelectField("Intermediate Board", validators=[Optional()])
    inter_marks = SelectField("Intermediate Marks", validators=[Optional()])
    inter_group = SelectField("Intermediate Type", validators=[Optional()])

    # --- Step 3: personal / contact ---
    name = StringField(
        "Full Name",
        validators=[InputRequired("Please enter your name."), Length(min=2, max=120)],
    )
    guardian_name = StringField(
        "Guardian / Parent Name", validators=[Optional(), Length(max=120)]
    )
    phone = StringField(
        "Contact Number",
        validators=[
            InputRequired("Please enter your phone number."),
            Regexp(_PHONE_PATTERN, message="Please enter a valid phone number."),
        ],
    )
    guardian_phone = StringField(
        "Guardian / Parent Contact Number",
        validators=[
            Optional(),
            Regexp(_PHONE_PATTERN, message="Please enter a valid phone number."),
        ],
    )
    email = StringField(
        "Email Address",
        validators=[Optional(), Email("Please enter a valid email."), Length(max=255)],
    )
    city = StringField("City", validators=[Optional(), Length(max=120)])
    # Kept optional and relabelled "Area / Locality" (addendum 2 §3) — a full
    # mailing address is unnecessary friction at lead capture. Still stored in
    # Lead.address.
    address = StringField("Area / Locality", validators=[Optional(), Length(max=512)])
    message = TextAreaField(
        "Anything else you'd like to tell us?",
        validators=[Optional(), Length(max=2000)],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Choices come from the reference service so the form, dashboard
        # filters, and constants never drift apart. Program has no blank
        # option — it's required and chosen via tap-cards in the template.
        self.course.choices = [(c, c) for c in get_courses()]
        # Blank first option keeps specialization optional (only BSMT needs it).
        self.specialization.choices = [("", "Select specialization")] + [
            (s, s) for s in get_bsmt_specializations()
        ]
        # Step 2 dropdowns — each leads with a blank placeholder so the field
        # stays optional and reads as "not answered" rather than a real value.
        board_choices = [(b, b) for b in get_education_boards()]
        marks_choices = [(m, m) for m in get_marks_ranges()]
        self.matric_board.choices = [("", "Select board")] + board_choices
        self.inter_board.choices = [("", "Select board")] + board_choices
        self.matric_marks.choices = [("", "Select marks range")] + marks_choices
        self.inter_marks.choices = [("", "Select marks range")] + marks_choices
        self.inter_group.choices = [("", "Select type")] + [
            (t, t) for t in get_intermediate_types()
        ]

    def validate(self, extra_validators=None):
        """Require a BSMT specialization only when BSMT is the chosen program."""
        if not super().validate(extra_validators=extra_validators):
            return False
        if self.course.data == "BSMT" and not self.specialization.data:
            self.specialization.errors.append(
                "Please choose a BSMT specialization."
            )
            return False
        return True
