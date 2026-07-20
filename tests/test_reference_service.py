"""Unit tests for reference_service.evaluate_eligibility.

Pure logic (no app context needed): maps a program + coarse marks band to a
provisional eligibility read for the thank-you page. BSMT needs >50%, DPT >60%.
"""
import pytest

from app.services.reference_service import evaluate_eligibility


@pytest.mark.parametrize(
    "course,marks,expected",
    [
        # BSMT threshold is 50%: any band with a floor >= 50 clears it.
        ("BSMT", "60–70%", "eligible"),
        ("BSMT", "70–80%", "eligible"),
        ("BSMT", "Above 80%", "eligible"),
        # DPT threshold is 60%: the 60–70% band's floor (60) clears it.
        ("DPT", "60–70%", "eligible"),
        ("DPT", "Above 80%", "eligible"),
        # "Below 60%" has no reliable floor -> provisional for either program.
        ("BSMT", "Below 60%", "unknown"),
        ("DPT", "Below 60%", "unknown"),
        # No marks given -> provisional.
        ("DPT", "", "unknown"),
        ("BSMT", None, "unknown"),
    ],
)
def test_evaluate_eligibility_status(course, marks, expected):
    result = evaluate_eligibility(course, marks)
    assert result["status"] == expected
    assert result["course"] == course


def test_evaluate_eligibility_carries_threshold():
    assert evaluate_eligibility("BSMT", "70–80%")["threshold"] == 50
    assert evaluate_eligibility("DPT", "70–80%")["threshold"] == 60


def test_evaluate_eligibility_unknown_course_is_safe():
    """An unrecognised course never raises — it returns a provisional read."""
    result = evaluate_eligibility("MBBS", "Above 80%")
    assert result["status"] == "unknown"
    assert result["threshold"] is None
