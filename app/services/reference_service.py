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

# Minimum Intermediate percentage each program requires. Used by the post-
# submission thank-you page to give the applicant an instant eligibility read.
ELIGIBILITY_THRESHOLDS: dict[str, int] = {
    "BSMT": 50,
    "DPT": 60,
}

# The percentage floor each marks band guarantees. "Below 60%" has no reliable
# floor (it spans everything under 60), so it maps to None and can never be
# auto-confirmed — the counselor verifies exact marks on the call.
_MARKS_FLOOR: dict[str, int] = {
    "60–70%": 60,
    "70–80%": 70,
    "Above 80%": 80,
}

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


def evaluate_eligibility(course: str, inter_marks: str) -> dict:
    """Give an instant, provisional eligibility read for the thank-you page.

    BSMT needs Intermediate marks above 50%, DPT above 60%. Marks come in as a
    coarse band (see MARKS_RANGES), so we compare the band's guaranteed floor
    against the threshold:

    - band floor >= threshold  -> "eligible" (e.g. "60–70%" clears BSMT's 50%)
    - "Below 60%" or no marks   -> "unknown" (can't confirm; counselor verifies)
    - otherwise                 -> "below"   (band sits under the threshold)

    Returns a dict the template renders directly:
        {status, threshold, course, marks}
    where status is one of "eligible" | "below" | "unknown". Always safe —
    an unknown course or empty marks yields "unknown", never an error.
    """
    threshold = ELIGIBILITY_THRESHOLDS.get(course)
    if threshold is None:
        return {"status": "unknown", "threshold": None, "course": course, "marks": inter_marks}

    floor = _MARKS_FLOOR.get(inter_marks)
    if floor is None:
        # "Below 60%" or blank — no reliable floor to compare, stay provisional.
        status = "unknown"
    elif floor >= threshold:
        status = "eligible"
    else:
        status = "below"

    return {
        "status": status,
        "threshold": threshold,
        "course": course,
        "marks": inter_marks,
    }
