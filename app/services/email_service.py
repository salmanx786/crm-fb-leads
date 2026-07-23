"""Transactional email over SMTP (applicant confirmation on new lead).

This service owns everything about sending a confirmation email to a
just-captured applicant: reading the SMTP configuration, composing the
plain-text message, and talking to the SMTP server. Business code
(lead_service) only ever calls ``notify_new_lead`` — it never builds a message
or opens a connection.

Design (mirrors push_service / meta_service):
- Failures NEVER propagate to the caller. ``notify_new_lead`` swallows and logs
  every error, so an SMTP outage can't break lead creation.
- Email is a no-op unless it is enabled AND fully configured, so an empty or
  half-configured deployment behaves exactly as before.
- A lead with no email address is silently skipped (Lead.email is nullable).

SECRET HANDLING: MAIL_PASSWORD is a credential (see settings_service
SECRET_KEYS). It is read here to authenticate but never logged and never
rendered into a page. Applicant email addresses are PII and are never logged —
log lines carry the lead id only, matching the rest of the project.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Optional

from flask import current_app

from app.models import Lead
from app.utils.logger import get_logger

logger = get_logger("app.email_service")

_DEFAULT_TIMEOUT = 10  # seconds; keep short so a slow SMTP never stalls a request

# Contact details reused in the confirmation sign-off (kept in step with the
# thank-you page). Plain, human-readable — no branding markup (plain text).
_PHONE_DISPLAY = "021-36684658"
_WHATSAPP_DISPLAY = "+92 331 2004658"


# --- config ---------------------------------------------------------------

def _config() -> dict[str, Any]:
    """Resolve the active email settings from settings_service (DB, else env)."""
    from app.services import settings_service as s

    port_raw = s.get_str(s.MAIL_SMTP_PORT)
    try:
        port = int(str(port_raw).strip())
    except (TypeError, ValueError):
        port = 0

    username = s.get_str(s.MAIL_USERNAME).strip()
    return {
        "enabled": s.get_bool(s.MAIL_ENABLED),
        "host": s.get_str(s.MAIL_SMTP_HOST).strip(),
        "port": port,
        "username": username,
        "password": s.get_str(s.MAIL_PASSWORD).strip(),
        # From falls back to the login address when not explicitly set.
        "from": s.get_str(s.MAIL_FROM).strip() or username,
        "timeout": current_app.config.get("MAIL_TIMEOUT", _DEFAULT_TIMEOUT)
        if current_app
        else _DEFAULT_TIMEOUT,
    }


def is_configured() -> bool:
    """True when email is enabled and every value needed to send is present."""
    cfg = _config()
    return bool(
        cfg["enabled"]
        and cfg["host"]
        and cfg["port"]
        and cfg["username"]
        and cfg["password"]
        and cfg["from"]
    )


# --- sending ---------------------------------------------------------------

def _compose(lead: Lead) -> tuple[str, str]:
    """Build the (subject, body) plain-text confirmation for an applicant."""
    first = (lead.first_name or "").strip() or "there"
    program = (lead.course or "").strip()
    track = (lead.specialization or "").strip()
    program_line = program + (f" ({track})" if track else "") if program else ""

    subject = "We've received your admission enquiry — MC College"
    lines = [
        f"Dear {first},",
        "",
        "Thank you for your admission enquiry to MC College of Medical & "
        "Allied Health Sciences.",
    ]
    if program_line:
        lines.append("")
        lines.append(f"Programme of interest: {program_line}")
    lines += [
        "",
        "We have received your details and one of our admission counselors "
        "will contact you shortly to guide you through the next steps.",
        "",
        "If you have any questions in the meantime, you can reach us at:",
        f"  Phone: {_PHONE_DISPLAY}",
        f"  WhatsApp: {_WHATSAPP_DISPLAY}",
        "",
        "Warm regards,",
        "Admissions Office",
        "MC College of Medical & Allied Health Sciences",
    ]
    return subject, "\n".join(lines)


def _send(to: str, subject: str, body: str, cfg: dict) -> bool:
    """Send one plain-text email. Returns True on success. Never raises."""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["from"]
        msg["To"] = to
        msg.set_content(body)

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg["timeout"]) as smtp:
            smtp.starttls()
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)
        return True
    except Exception:  # pragma: no cover - defensive; never break the caller
        # No recipient address in the log line (PII).
        logger.exception("Confirmation email send failed")
        return False


def notify_new_lead(lead: Lead) -> bool:
    """Send an applicant confirmation email for a newly created lead.

    No-op (returns False) when email is disabled/unconfigured or the lead has no
    email address. Never raises — a mail failure must not break lead creation.
    Returns True only when the message was handed to the SMTP server.
    """
    try:
        if not is_configured():
            return False
        to = (lead.email or "").strip()
        if not to:
            return False  # email is optional on the form; nothing to send to

        cfg = _config()
        subject, body = _compose(lead)
        sent = _send(to, subject, body, cfg)
        if sent:
            logger.info("Confirmation email sent: lead=%s", lead.id)
        return sent
    except Exception:  # pragma: no cover - defensive catch-all
        logger.exception("notify_new_lead failed for lead=%s", getattr(lead, "id", "?"))
        return False
