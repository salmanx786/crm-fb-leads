"""Reusable, framework-agnostic validation helpers.

These are plain functions so they can be called from WTForms validators,
the JSON API, or tests without pulling in request state.
"""
import re

# Accepts 7–15 digits, optional leading +, and common separators.
_PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,20}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_phone(value: str) -> bool:
    """True if `value` looks like a usable phone number."""
    if not value:
        return False
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15 and bool(_PHONE_RE.match(value.strip()))


def is_valid_email(value: str) -> bool:
    """Lightweight email shape check. Deep validation is left to email-validator."""
    if not value:
        return False
    return bool(_EMAIL_RE.match(value.strip()))


def is_nonempty(value: str, min_len: int = 1) -> bool:
    """True if `value` has at least `min_len` non-whitespace characters."""
    return bool(value) and len(value.strip()) >= min_len
