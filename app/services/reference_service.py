"""Read-only metadata the UI needs: status lists, courses, cities.

Keeps presentational reference data in one place so routes/templates ask a
service for their dropdown options instead of hard-coding them.
"""
from app.constants import LEAD_STATUSES

# Programs offered — used by the landing page form and dashboard filters.
COURSES: list[str] = [
    "DPT",
    "BSMT",
]

# BSMT specialization tracks the applicant chooses between in Step 1.
BSMT_SPECIALIZATIONS: list[str] = [
    "Clinical Laboratory Sciences",
    "Radiological Imaging",
]

# Examination boards, offered as a dropdown in Step 2 so lead data stays clean
# and consistent (no free-text typos/abbreviations). "Other" is a catch-all for
# boards not listed. Kept as one list — Matric and Intermediate share it.
EDUCATION_BOARDS: list[str] = [
    "BSEK (Karachi)",
    "BISE Hyderabad",
    "BISE Larkana",
    "BISE Sukkur",
    "BISE Mirpurkhas",
    "Aga Khan (AKU-EB)",
    "Federal Board (FBISE)",
    "Other",
]

# Coarse marks bands, used instead of an exact typed percentage. Enough to
# screen a lead; the admissions team confirms exact marks on the follow-up call.
MARKS_RANGES: list[str] = [
    "Below 60%",
    "60–70%",
    "70–80%",
    "Above 80%",
]

# Intermediate study groups. Not every applicant (especially BSMT) is
# Pre-Medical, so the list covers the common Intermediate streams.
INTERMEDIATE_TYPES: list[str] = [
    "Pre-Medical",
    "Pre-Engineering",
    "General Science",
    "ICS",
    "Other",
]


def get_statuses() -> list[str]:
    """All valid lead statuses, in lifecycle order."""
    return list(LEAD_STATUSES)


def get_courses() -> list[str]:
    """All programs offered, for form + filter dropdowns."""
    return list(COURSES)


def get_bsmt_specializations() -> list[str]:
    """BSMT specialization tracks, for the Step 1 sub-question."""
    return list(BSMT_SPECIALIZATIONS)


def get_education_boards() -> list[str]:
    """Examination boards for the Matric/Intermediate board dropdowns."""
    return list(EDUCATION_BOARDS)


def get_marks_ranges() -> list[str]:
    """Coarse marks bands for the Matric/Intermediate marks dropdowns."""
    return list(MARKS_RANGES)


def get_intermediate_types() -> list[str]:
    """Intermediate study groups (Pre-Medical, Pre-Engineering, ...)."""
    return list(INTERMEDIATE_TYPES)
