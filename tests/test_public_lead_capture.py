"""End-to-end test for the public lead capture workflow.

Exercises the real request cycle through Flask's test client: render the
form (which mints a CSRF token), submit it with that token, and assert the
lead plus its "created" timeline event were persisted.
"""
import re

from sqlalchemy import func, select

from app.extensions import db
from app.models import Lead, TimelineEvent

# Pulls the value out of <input ... name="csrf_token" ... value="...">
# regardless of attribute order.
_CSRF_RE = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"'
)


def _extract_csrf_token(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match, "CSRF token not found in the rendered form"
    return match.group(1) or match.group(2)


def test_admission_submission_creates_lead_and_timeline(client, app):
    # 1. GET the landing page and pull the CSRF token from the form.
    get_resp = client.get("/")
    assert get_resp.status_code == 200
    token = _extract_csrf_token(get_resp.get_data(as_text=True))

    # 2. POST a valid admission enquiry with UTM params on the query string,
    #    so we also cover attribution capture.
    post_resp = client.post(
        "/admission?utm_source=google&utm_medium=cpc&utm_campaign=summer",
        data={
            "csrf_token": token,
            "name": "Asha Verma",
            "phone": "+91 98765 43210",
            "email": "asha@example.com",
            "city": "Pune",
            "course": "MBA",
            "message": "Please share the fee structure.",
        },
    )

    # 3. Success redirects (302) back to the landing page's #admission anchor.
    assert post_resp.status_code == 302
    assert "/#admission" in post_resp.headers["Location"]

    # 4a. The flash message is queued in the session.
    with client.session_transaction() as session:
        flashes = dict(session.get("_flashes", []))
    assert "success" in flashes
    assert "received" in flashes["success"].lower()

    # 4b. The lead was created with normalised, attributed data.
    with app.app_context():
        leads = db.session.scalars(select(Lead)).all()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.name == "Asha Verma"
        assert lead.email == "asha@example.com"  # normalised to lowercase
        assert lead.course == "MBA"
        assert lead.status == "New"
        assert lead.utm_source == "google"
        assert lead.utm_medium == "cpc"
        assert lead.utm_campaign == "summer"
        assert lead.user_agent is not None  # captured from the request

        # 4c. Exactly one "created" timeline event is linked to the lead.
        events = db.session.scalars(
            select(TimelineEvent).filter_by(lead_id=lead.id)
        ).all()
        assert len(events) == 1
        assert events[0].event_type == "created"


def test_admission_submission_rejects_invalid_data(client, app):
    """Missing name + bad phone should re-render (400) and persist nothing."""
    token = _extract_csrf_token(client.get("/").get_data(as_text=True))

    resp = client.post(
        "/admission",
        data={
            "csrf_token": token,
            "name": "",           # required
            "phone": "abc",       # fails the phone pattern
            "email": "not-an-email",
        },
    )

    assert resp.status_code == 400
    with app.app_context():
        assert db.session.scalar(select(func.count(Lead.id))) == 0
        assert db.session.scalar(select(func.count(TimelineEvent.id))) == 0


def test_admission_submission_without_csrf_is_rejected(client, app):
    """A POST with no CSRF token must be refused and persist nothing."""
    resp = client.post(
        "/admission",
        data={"name": "No Token", "phone": "+91 98765 43210"},
    )
    assert resp.status_code in (400, 403)
    with app.app_context():
        assert db.session.scalar(select(func.count(Lead.id))) == 0
