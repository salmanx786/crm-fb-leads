"""Application-wide constants.

Centralising the lead lifecycle here means the string `status` column, the
form dropdown, the dashboard filters, and validation all read from one list.
Add a stage by editing this file — no database migration required.
"""

# Ordered lifecycle stages. Order is used for display in filters/dropdowns.
LEAD_STATUSES: list[str] = [
    "New",
    "Called",
    "Interested",
    "Follow-up",
    "Documents Pending",
    "Fee Pending",
    "Admitted",
    "Rejected",
    "Spam",
]

DEFAULT_LEAD_STATUS: str = "New"

# Status that counts as a completed admission (used by dashboard metrics).
ADMITTED_STATUS: str = "Admitted"


def is_valid_status(value: str) -> bool:
    """True if `value` is a recognised lead status."""
    return value in LEAD_STATUSES
