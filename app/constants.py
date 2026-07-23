"""Application-wide constants.

Centralising the lead lifecycle here means the string `status` column, the
form dropdown, the dashboard filters, and validation all read from one list.
Add a stage by editing this file — no database migration required.
"""
from __future__ import annotations  # 3.9-safe PEP 604 unions in annotations

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


# --- Meta Conversions API event mapping ---------------------------------
# Maps a CRM trigger to the Meta (Facebook) event name we send. Kept here as
# configuration so the meta_service never hardcodes event names and new
# mappings are a one-line edit. Triggers not present here are simply not sent.
#
# "lead_created" is a synthetic trigger fired once on lead creation and is the
# only trigger mapped to the "Lead" conversion, so a single submission counts
# as exactly one Lead. The rest are lead statuses that, when reached, raise a
# later-funnel conversion. Deliberately NOT mapped: "Interested" (and other
# early stages) — they are CRM stages set on an already-counted lead, so
# mapping them to "Lead" would double-count the same person in Ads Manager.
META_EVENT_MAP: dict[str, str] = {
    "lead_created": "Lead",
    "Documents Pending": "SubmitApplication",
    "Admitted": "CompleteRegistration",
}


def meta_event_for(trigger: str) -> str | None:
    """Return the Meta event name for a CRM trigger, or None if untracked."""
    return META_EVENT_MAP.get(trigger)
