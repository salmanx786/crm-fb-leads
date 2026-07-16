"""Read-only metadata the UI needs: status lists, courses, cities.

Keeps presentational reference data in one place so routes/templates ask a
service for their dropdown options instead of hard-coding them.
"""
from app.constants import LEAD_STATUSES

# Programs offered — used by the landing page form and dashboard filters.
COURSES: list[str] = [
    "B.Com",
    "BBA",
    "BCA",
    "B.Sc",
    "B.A",
    "M.Com",
    "MBA",
    "MCA",
]


def get_statuses() -> list[str]:
    """All valid lead statuses, in lifecycle order."""
    return list(LEAD_STATUSES)


def get_courses() -> list[str]:
    """All programs offered, for form + filter dropdowns."""
    return list(COURSES)
