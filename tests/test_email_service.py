"""Tests for the transactional email service.

All SMTP is mocked — these tests never contact a mail server. We monkeypatch
``smtplib.SMTP`` so config resolution, message composition, and the never-raise
contract are exercised end-to-end.

Covers: no-op when disabled, no-op when unconfigured, no-op when lead has no
email, successful send, SMTP exception swallowed (create_lead still returns),
and message content basics.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.models import Lead
from app.services import email_service


# --- fixtures -------------------------------------------------------------

@pytest.fixture()
def mail_on(app):
    """Enable email on the app config for the duration of a test."""
    app.config["MAIL_ENABLED"] = True
    app.config["MAIL_SMTP_HOST"] = "smtp.gmail.com"
    app.config["MAIL_SMTP_PORT"] = 587
    app.config["MAIL_USERNAME"] = "admissions@example.com"
    app.config["MAIL_PASSWORD"] = "test-app-password"
    app.config["MAIL_FROM"] = "admissions@example.com"
    yield app


@pytest.fixture()
def a_lead():
    """A minimal lead with an email address (not persisted)."""
    return Lead(
        name="Sara Ahmed",
        first_name="Sara",
        last_name="Ahmed",
        phone="03001234567",
        email="sara@example.com",
        course="DPT",
        status="New",
    )


@pytest.fixture()
def a_lead_no_email():
    """A lead that submitted without an email address."""
    return Lead(
        name="Ali Khan",
        first_name="Ali",
        last_name="Khan",
        phone="03009876543",
        email=None,
        course="BSMT",
        status="New",
    )


# --- is_configured --------------------------------------------------------

def test_is_configured_false_when_disabled(app, mail_on):
    app.config["MAIL_ENABLED"] = False
    assert email_service.is_configured() is False


def test_is_configured_false_when_missing_host(app, mail_on):
    app.config["MAIL_SMTP_HOST"] = ""
    assert email_service.is_configured() is False


def test_is_configured_false_when_missing_password(app, mail_on):
    app.config["MAIL_PASSWORD"] = ""
    assert email_service.is_configured() is False


def test_is_configured_true_when_fully_set(app, mail_on):
    assert email_service.is_configured() is True


# --- notify_new_lead: no-op paths -----------------------------------------

def test_no_send_when_disabled(app, mail_on, a_lead):
    app.config["MAIL_ENABLED"] = False
    with patch("smtplib.SMTP") as mock_smtp:
        result = email_service.notify_new_lead(a_lead)
    assert result is False
    mock_smtp.assert_not_called()


def test_no_send_when_unconfigured(app, a_lead):
    # mail_on fixture not applied — MAIL_ENABLED defaults to False
    with patch("smtplib.SMTP") as mock_smtp:
        result = email_service.notify_new_lead(a_lead)
    assert result is False
    mock_smtp.assert_not_called()


def test_no_send_when_lead_has_no_email(app, mail_on, a_lead_no_email):
    with patch("smtplib.SMTP") as mock_smtp:
        result = email_service.notify_new_lead(a_lead_no_email)
    assert result is False
    mock_smtp.assert_not_called()


# --- notify_new_lead: successful send -------------------------------------

def test_send_called_with_applicant_email(app, mail_on, a_lead):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        mock_smtp_instance.__enter__ = lambda s: s
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        result = email_service.notify_new_lead(a_lead)

    assert result is True
    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with(
        "admissions@example.com", "test-app-password"
    )
    # send_message receives an EmailMessage; verify the To header.
    sent_msg = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_msg["To"] == "sara@example.com"
    assert sent_msg["From"] == "admissions@example.com"


def test_subject_contains_college_name(app, mail_on, a_lead):
    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__ = lambda s: s
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        email_service.notify_new_lead(a_lead)

    sent_msg = mock_smtp_instance.send_message.call_args[0][0]
    assert "MC College" in sent_msg["Subject"]


# --- never-raise contract -------------------------------------------------

def test_smtp_exception_is_swallowed(app, mail_on, a_lead):
    """An SMTP error must not propagate — lead creation must not break."""
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        result = email_service.notify_new_lead(a_lead)
    # Returns False (not True), but crucially does not raise.
    assert result is False


def test_create_lead_succeeds_when_smtp_fails(app, mail_on):
    """End-to-end: create_lead returns a Lead even when SMTP blows up."""
    from app.extensions import db
    from app.services import lead_service

    with patch("smtplib.SMTP", side_effect=OSError("smtp down")):
        lead = lead_service.create_lead(
            data={
                "first_name": "Test",
                "last_name": "User",
                "phone": "03001112233",
                "email": "test@example.com",
            }
        )

    assert lead.id is not None
    assert lead.name == "Test User"
