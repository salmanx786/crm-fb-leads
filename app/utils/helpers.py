from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from flask import current_app

DEFAULT_TIMEZONE = "Asia/Karachi"


def get_app_timezone() -> ZoneInfo:
    """Return the configured business timezone (default: Asia/Karachi, PKT)."""
    try:
        tz_name = current_app.config.get("TIMEZONE", DEFAULT_TIMEZONE)
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def to_local_datetime(
    dt: Optional[datetime], tz: Optional[ZoneInfo] = None
) -> Optional[datetime]:
    """Convert a naive UTC datetime (stored in DB) to an aware local datetime."""
    if dt is None:
        return None
    target_tz = tz or get_app_timezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(target_tz)


def format_local_time(
    dt: Optional[datetime],
    fmt: str = "%d %b %Y, %H:%M",
    tz: Optional[ZoneInfo] = None,
) -> str:
    """Format a naive UTC datetime into the local timezone (Asia/Karachi / PKT)."""
    local_dt = to_local_datetime(dt, tz=tz)
    if local_dt is None:
        return ""
    return local_dt.strftime(fmt)


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
