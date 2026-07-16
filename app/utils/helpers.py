"""Small, general-purpose helpers with no business logic."""
from typing import Optional


def clean_str(value: Optional[str], max_len: Optional[int] = None) -> Optional[str]:
    """Trim whitespace and optionally cap length. Empty -> None.

    Keeps the database free of blank strings and over-long values that would
    otherwise be silently truncated by the column definition.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if max_len is not None:
        value = value[:max_len]
    return value


def normalize_phone(value: Optional[str]) -> Optional[str]:
    """Strip formatting characters, keeping digits and a leading +."""
    if not value:
        return None
    value = value.strip()
    plus = value.startswith("+")
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return ("+" + digits) if plus else digits


def normalize_email(value: Optional[str]) -> Optional[str]:
    """Lowercase and trim an email address; empty -> None."""
    cleaned = clean_str(value)
    return cleaned.lower() if cleaned else None
