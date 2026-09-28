"""Dashboard action forms (CSRF-protected)."""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, Regexp

from app.services.reference_service import (
    get_bsmt_specializations,
    get_courses,
    get_education_boards,
    get_intermediate_types,
    get_marks_ranges,
    get_statuses,
)

# Accepts digits, spaces, +, -, and parentheses; 7–20 chars. Matches the
# public AdmissionForm so a lead's phone validates identically on edit.
_PHONE_PATTERN = r"^\+?[0-9\s\-()]{7,20}$"

# Matches the value an <input type="datetime-local"> submits (minute precision),
# which is also the precision the follow-up timeline records.
FOLLOW_UP_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


class StatusForm(FlaskForm):
    """Change a lead's status. Choices come from the admin-editable status
    list (status_service via reference_service), resolved per request."""

    status = SelectField("Status", validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status.choices = [(s, s) for s in get_statuses()]


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
    """Edit a lead's applicant fields, status, source, guardian, and academic history.

    Field names match Lead attributes so the route can prefill with
    `LeadEditForm(obj=lead)` and hand `form.data` straight to
    lead_service.update_lead. First-pass shape checks only — normalisation
    and the change/timeline logic stay in the service (single source of
    truth), so this never duplicates business rules. Uniqueness is not
    enforced: the project deliberately allows duplicate phone/email.
    """

    first_name = StringField(
        "First Name",
        validators=[
            DataRequired("Please enter the lead's first name."),
            Length(min=2, max=60),
        ],
    )
    last_name = StringField(
        "Last Name",
        validators=[
            DataRequired("Please enter the lead's last name."),
            Length(min=1, max=60),
        ],
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
    specialization = SelectField("Specialization (BSMT)", validators=[Optional()])

    # Guardian & locality
    guardian_name = StringField("Guardian / Parent Name", validators=[Optional(), Length(max=120)])
    guardian_phone = StringField(
        "Guardian Contact",
        validators=[
            Optional(),
            Regexp(_PHONE_PATTERN, message="Please enter a valid guardian phone number."),
        ],
    )
    address = StringField("Area / Locality", validators=[Optional(), Length(max=512)])

    # Academic qualifications
    matric_board = SelectField("Matric Board", validators=[Optional()])
    matric_marks = SelectField("Matric Marks", validators=[Optional()])
    inter_board = SelectField("Intermediate Board", validators=[Optional()])
    inter_marks = SelectField("Intermediate Marks", validators=[Optional()])
    inter_group = SelectField("Intermediate Study Group", validators=[Optional()])

    # "Source" is stored as utm_source on the model.
    utm_source = StringField("Source", validators=[Optional(), Length(max=120)])
    status = SelectField("Status", validators=[DataRequired()])
    # "Notes" maps to the lead's free-text message field.
    message = TextAreaField("Notes / Comments", validators=[Optional(), Length(max=2000)])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.course.choices = [("", "Select a course")] + [(c, c) for c in get_courses()]
        self.specialization.choices = [("", "Select specialization (if BSMT)")] + [
            (s, s) for s in get_bsmt_specializations()
        ]
        board_choices = [("", "Select examination board")] + [(b, b) for b in get_education_boards()]
        self.matric_board.choices = board_choices
        self.inter_board.choices = board_choices

        marks_choices = [("", "Select marks band")] + [(m, m) for m in get_marks_ranges()]
        self.matric_marks.choices = marks_choices
        self.inter_marks.choices = marks_choices

        self.inter_group.choices = [("", "Select study group")] + [
            (g, g) for g in get_intermediate_types()
        ]
        self.status.choices = [(s, s) for s in get_statuses()]


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
        validators=[Optional()],
    )
    next_follow_up_at = DateTimeLocalField(
        "Follow-up date",
        format=FOLLOW_UP_INPUT_FORMAT,
        validators=[Optional()],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Status choices from the admin-editable status_service (request-time).
        self.status.choices = [("", "Select a status")] + [
            (s, s) for s in get_statuses()
        ]


class MetaSettingsForm(FlaskForm):
    """Manage the Meta (Facebook) Conversions API settings from the dashboard.

    Field names map to settings_service.save_meta_settings keys. The access
    token is a PasswordField that is never pre-filled: leaving it blank keeps
    the stored token, so the secret never has to round-trip through the page.
    """

    enabled = BooleanField("Enable Meta tracking", validators=[Optional()])
    pixel_id = StringField(
        "Pixel ID",
        validators=[Optional(), Regexp(r"^\d*$", message="Pixel ID is numeric."),
                    Length(max=32)],
    )
    access_token = PasswordField(
        "Access token",
        validators=[Optional(), Length(max=1024)],
    )
    test_event_code = StringField(
        "Test event code", validators=[Optional(), Length(max=64)]
    )
    default_country = StringField(
        "Default country (2-letter)",
        validators=[Optional(), Regexp(r"^[A-Za-z]{0,2}$",
                    message="Use a 2-letter country code, e.g. pk.")],
    )
    event_source_url = StringField(
        "Event source URL", validators=[Optional(), Length(max=512)]
    )


class PushSettingsForm(FlaskForm):
    """Manage the Web Push (VAPID) settings from the dashboard.

    Field names map to settings_service.save_push_settings keys. Like the Meta
    access token, the private key is a PasswordField that is never pre-filled:
    leaving it blank keeps the stored key, so the secret never round-trips
    through the page.
    """

    enabled = BooleanField("Enable push notifications", validators=[Optional()])
    public_key = StringField(
        "VAPID public key", validators=[Optional(), Length(max=255)]
    )
    private_key = PasswordField(
        "VAPID private key", validators=[Optional(), Length(max=255)]
    )
    subject = StringField(
        "Contact subject (mailto: or https:)",
        validators=[Optional(), Length(max=255)],
    )


class MailSettingsForm(FlaskForm):
    """Manage the transactional email (SMTP) settings from the dashboard.

    Field names map to settings_service.save_mail_settings keys. Like the Meta
    access token and VAPID private key, the SMTP password is a PasswordField
    that is never pre-filled: leaving it blank keeps the stored password, so the
    secret never round-trips through the page. Defaults target Google Workspace
    SMTP, which requires an App Password (not the account password).
    """

    enabled = BooleanField("Enable confirmation emails", validators=[Optional()])
    smtp_host = StringField(
        "SMTP host", validators=[Optional(), Length(max=255)]
    )
    smtp_port = IntegerField(
        "SMTP port", validators=[Optional(), NumberRange(min=1, max=65535)]
    )
    username = StringField(
        "SMTP username", validators=[Optional(), Length(max=255)]
    )
    password = PasswordField(
        "SMTP password (App Password)", validators=[Optional(), Length(max=255)]
    )
    from_address = StringField(
        "From address",
        validators=[Optional(), Email("Please enter a valid email."), Length(max=255)],
    )
    admissions_notify_email = StringField(
        "Admissions team alert email",
        validators=[Optional(), Email("Please enter a valid email address."), Length(max=255)],
    )


class UserCreateForm(FlaskForm):
    """Create a new user / staff member."""

    name = StringField(
        "Full Name",
        validators=[DataRequired("Please enter the user's name."), Length(min=2, max=120)],
    )
    email = StringField(
        "Email Address",
        validators=[DataRequired("Please enter an email address."), Email("Please enter a valid email address."), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired("Please enter a temporary password."), Length(min=6, max=100, message="Password must be at least 6 characters.")],
    )
    role = SelectField(
        "Role",
        choices=[("admin", "Administrator"), ("counselor", "Admissions Counselor")],
        default="admin",
        validators=[DataRequired()],
    )


class ProfileForm(FlaskForm):
    """Update current user's profile details."""

    name = StringField(
        "Full Name",
        validators=[DataRequired("Please enter your name."), Length(min=2, max=120)],
    )
    email = StringField(
        "Email Address",
        validators=[DataRequired("Please enter your email."), Email("Please enter a valid email address."), Length(max=255)],
    )


class ChangePasswordForm(FlaskForm):
    """Change current user's password."""

    old_password = PasswordField(
        "Current Password",
        validators=[DataRequired("Please enter your current password.")],
    )
    new_password = PasswordField(
        "New Password",
        validators=[DataRequired("Please enter your new password."), Length(min=6, max=100, message="Password must be at least 6 characters.")],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired("Please confirm your new password."),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )


class AdminResetPasswordForm(FlaskForm):
    """Reset a user's password by administrator."""

    new_password = PasswordField(
        "New Password",
        validators=[DataRequired("Please enter the new password."), Length(min=6, max=100, message="Password must be at least 6 characters.")],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired("Please confirm the new password."),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )

