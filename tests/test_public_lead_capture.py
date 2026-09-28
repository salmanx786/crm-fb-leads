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
            "first_name": "Asha",
            "last_name": "Verma",
            "phone": "+91 98765 43210",
            "email": "asha@example.com",
            "city": "Karachi",
            "course": "BSMT",
            "specialization": "Radiological Imaging",
            "guardian_name": "Ramesh Verma",
            "guardian_phone": "+92 300 1234567",
            "address": "Block A",
            # Step 2 fields are dropdowns — values must match the reference
            # choices (see reference_service). Year fields were removed.
            "matric_board": "BSEK (Karachi)",
            "matric_marks": "Above 80%",
            "inter_board": "Aga Khan (AKU-EB)",
            "inter_marks": "70–80%",
            "inter_group": "Pre-Medical",
            "message": "Please share the fee structure.",
        },
    )

    # 3. Success redirects (302) to the dedicated thank-you page.
    assert post_resp.status_code == 302
    assert "/thank-you" in post_resp.headers["Location"]

    # 4a. The thank-you page renders the confirmation, personalised with the
    #     applicant's first name, and reports BSMT eligibility (Above 80% > 50%).
    ty_resp = client.get("/thank-you")
    assert ty_resp.status_code == 200
    ty_body = ty_resp.get_data(as_text=True)
    assert "Thank you, Asha" in ty_body
    assert "received successfully" in ty_body
    assert "15–30 minutes" in ty_body
    assert "you look eligible" in ty_body.lower()

    # 4b. The lead was created with normalised, attributed data.
    with app.app_context():
        leads = db.session.scalars(select(Lead)).all()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.first_name == "Asha"
        assert lead.last_name == "Verma"
        assert lead.name == "Asha Verma"  # composed display value
        assert lead.email == "asha@example.com"  # normalised to lowercase
        assert lead.course == "BSMT"
        assert lead.specialization == "Radiological Imaging"
        assert lead.guardian_name == "Ramesh Verma"
        assert lead.guardian_phone == "+923001234567"  # normalised
        assert lead.matric_board == "BSEK (Karachi)"
        assert lead.matric_marks == "Above 80%"
        assert lead.inter_marks == "70–80%"
        assert lead.inter_group == "Pre-Medical"
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
            "first_name": "",     # required
            "last_name": "",      # required
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
        data={"first_name": "No", "last_name": "Token", "phone": "+91 98765 43210"},
    )
    assert resp.status_code in (400, 403)
    with app.app_context():
        assert db.session.scalar(select(func.count(Lead.id))) == 0


def test_thank_you_without_submission_redirects_home(client):
    """Visiting /thank-you directly (no prior submission) redirects home."""
    resp = client.get("/thank-you", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_thank_you_is_one_shot(client):
    """The confirmation is consumed once — a second visit redirects home."""
    token = _extract_csrf_token(client.get("/").get_data(as_text=True))
    client.post(
        "/admission",
        data={
            "csrf_token": token,
            "first_name": "Bilal",
            "last_name": "Ahmed",
            "phone": "+92 300 1112222",
            "course": "DPT",
            "inter_marks": "70–80%",
        },
    )
    # First visit shows the page...
    assert client.get("/thank-you").status_code == 200
    # ...second visit has nothing left to confirm.
    assert client.get("/thank-you", follow_redirects=False).status_code == 302


def test_thank_you_dpt_below_threshold_message(client):
    """DPT needs >60%; a "Below 60%" band can't be auto-confirmed."""
    token = _extract_csrf_token(client.get("/").get_data(as_text=True))
    client.post(
        "/admission",
        data={
            "csrf_token": token,
            "first_name": "Sana",
            "last_name": "Khan",
            "phone": "+92 301 2223333",
            "course": "DPT",
            "inter_marks": "Below 60%",
        },
    )
    body = client.get("/thank-you").get_data(as_text=True)
    assert "Thank you, Sana" in body
    # "Below 60%" has no reliable floor -> provisional "Eligibility check" card.
    assert "Eligibility check" in body


def test_duplicate_submission_within_debounce_window_is_throttled(client, app):
    """Submitting the same phone number within 5 minutes throttles duplicate creation."""
    token = _extract_csrf_token(client.get("/").get_data(as_text=True))
    payload = {
        "csrf_token": token,
        "first_name": "Tariq",
        "last_name": "Mahmood",
        "phone": "+92 333 4445555",
        "course": "DPT",
    }
    # 1. First submission succeeds and creates a lead
    resp1 = client.post("/admission", data=payload)
    assert resp1.status_code == 302

    with app.app_context():
        leads = db.session.scalars(select(Lead).where(Lead.phone == "+923334445555")).all()
        assert len(leads) == 1
        initial_id = leads[0].id

    # 2. Second rapid submission with same phone
    token2 = _extract_csrf_token(client.get("/").get_data(as_text=True))
    payload["csrf_token"] = token2
    payload["message"] = "Additional message"
    resp2 = client.post("/admission", data=payload)
    assert resp2.status_code == 302

    with app.app_context():
        leads_after = db.session.scalars(select(Lead).where(Lead.phone == "+923334445555")).all()
        # Still exactly 1 lead in the database!
        assert len(leads_after) == 1
        lead = leads_after[0]
        assert lead.id == initial_id
        # Timeline recorded the throttled duplicate
        events = db.session.scalars(select(TimelineEvent).where(TimelineEvent.lead_id == lead.id)).all()
        types = [e.event_type for e in events]
        assert "created" in types
        assert "duplicate_throttled" in types


def test_attribution_preserved_from_landing_to_post(client, app):
    """Visiting / with UTMs preserves attribution even when /admission POST has no query params."""
    # 1. User visits landing page from Facebook Ad
    get_resp = client.get("/?utm_source=facebook&utm_medium=paid_social&utm_campaign=admissions_2026&fbclid=fb_click_123")
    assert get_resp.status_code == 200
    token = _extract_csrf_token(get_resp.get_data(as_text=True))

    # 2. User submits without query params on the POST URL
    post_resp = client.post(
        "/admission",
        data={
            "csrf_token": token,
            "first_name": "Zain",
            "last_name": "Ali",
            "phone": "+92 345 6789012",
            "course": "DPT",
        },
    )
    assert post_resp.status_code == 302

    with app.app_context():
        lead = db.session.scalar(select(Lead).where(Lead.phone == "+923456789012"))
        assert lead is not None
        assert lead.utm_source == "facebook"
        assert lead.utm_medium == "paid_social"
        assert lead.utm_campaign == "admissions_2026"
        assert lead.fbc is not None
        assert "fb_click_123" in lead.fbc


def test_thank_you_renders_deduplicated_meta_pixel_lead_event(app, client):
    """When Meta Pixel is enabled, /thank-you renders fbq('track', 'Lead') with matching eventID."""
    app.config["META_ENABLED"] = True
    app.config["META_PIXEL_ID"] = "1234567890"

    token = _extract_csrf_token(client.get("/").get_data(as_text=True))
    client.post(
        "/admission",
        data={
            "csrf_token": token,
            "first_name": "Hina",
            "last_name": "Altaf",
            "phone": "+92 321 9876543",
            "course": "DPT",
        },
    )

    ty_body = client.get("/thank-you").get_data(as_text=True)
    assert "fbq('track', 'Lead'" in ty_body
    assert "eventID:" in ty_body

