"""Authentication forms.

CSRF is handled automatically by FlaskForm. Validation here is intentionally
light — the real credential check happens against the database in the route.
"""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length


class LoginForm(FlaskForm):
    """Admin login form."""

    email = StringField(
        "Email",
        validators=[DataRequired("Please enter your email."), Email(), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired("Please enter your password.")],
    )
    remember = BooleanField("Remember me")
