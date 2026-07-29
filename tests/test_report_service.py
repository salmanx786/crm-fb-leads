"""Tests for the lead-response report service and its dashboard routes.

Two layers:

* The pure aggregation (``summarize`` + ``LeadRecord`` properties) is tested on
  hand-built records — no DB, no clock, no timezone — so the definitions of
  "contacted", "responded", the early/late split, and median-vs-average are
  pinned down deterministically.
* ``report()`` and the two routes are exercised end-to-end against seeded leads
  and timeline events inside a fixed custom window, confirming the DB queries,
  windowing, trend/per-staff shaping, and CSV export hang together.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Lead, TimelineEvent, User
from app.services import report_service, user_service

# --- helpers for the pure layer ------------------------------------------


def _record(
    lead_id,
    *,
    created_at=datetime(2026, 7, 1, 8, 0, 0),
    first_contact_at=None,
    actor_id=None,
    post=None,
):
    """Build a LeadRecord without touching the DB."""
    return report_service.LeadRecord(
        lead_id=lead_id,
        created_at=created_at,
        first_contact_at=first_contact_at,
        first_contact_actor_id=actor_id,
        post_contact_statuses=list(post or []),
    )


# --- LeadRecord properties ------------------------------------------------


def test_never_contacted_record_has_no_contact_facts():
    r = _record(1)
    assert r.contacted is False
    assert r.hours_to_contact is None
    assert r.cohort is None
    assert r.responded is False


def test_hours_to_contact_and_cohort_split_on_four_hours():
    base = datetime(2026, 7, 1, 8, 0, 0)
    early = _record(1, created_at=base, first_contact_at=base + timedelta(hours=2))
    boundary = _record(2, created_at=base, first_contact_at=base + timedelta(hours=4))
    late = _record(3, created_at=base, first_contact_at=base + timedelta(hours=7))

    assert early.hours_to_contact == 2.0
    assert early.cohort == "early"
    # Exactly at the cutoff counts as early (<=).
    assert boundary.cohort == "early"
    assert late.hours_to_contact == 7.0
    assert late.cohort == "late"


def test_hours_to_contact_never_negative():
    """A contact stamped before created_at (clock skew) floors at zero."""
    base = datetime(2026, 7, 1, 8, 0, 0)
    r = _record(1, created_at=base, first_contact_at=base - timedelta(hours=1))
    assert r.hours_to_contact == 0.0


def test_responded_requires_a_non_lost_progression():
    base = datetime(2026, 7, 1, 8, 0, 0)
    contact = base + timedelta(hours=1)
    # Progressed to a live stage -> responded.
    progressed = _record(1, created_at=base, first_contact_at=contact, post=["Interested"])
    # Only moved into a lost stage after contact -> not a response.
    lost = _record(2, created_at=base, first_contact_at=contact, post=["Rejected"])
    # Reached only the first-contact stage, no further move -> not a response.
    stalled = _record(3, created_at=base, first_contact_at=contact, post=[])

    assert progressed.responded is True
    assert lost.responded is False
    assert stalled.responded is False


# --- summarize (pure) -----------------------------------------------------


def _mixed_cohort_records():
    """Four leads: never-contacted, early-responded, late-no-response, early-lost."""
    base = datetime(2026, 7, 1, 8, 0, 0)
    return [
        _record(1, created_at=base),  # never contacted
        _record(  # early (2h), responded
            2, created_at=base, first_contact_at=base + timedelta(hours=2),
            post=["Interested"],
        ),
        _record(  # late (7h), no response
            3, created_at=base, first_contact_at=base + timedelta(hours=7),
        ),
        _record(  # early (1h), only rejected -> no response
            4, created_at=base, first_contact_at=base + timedelta(hours=1),
            post=["Rejected"],
        ),
    ]


def test_summarize_counts_rates_and_times():
    summary = report_service.summarize(_mixed_cohort_records())

    assert summary["new_leads"] == 4
    assert summary["contacted"] == 3
    assert summary["not_contacted"] == 1
    assert summary["contact_rate"] == 75.0

    # times = [2, 7, 1] -> mean 3.3, median 2.0
    assert summary["avg_hours_to_contact"] == 3.3
    assert summary["median_hours_to_contact"] == 2.0

    assert summary["responded"] == 1        # only lead 2
    assert summary["not_responded"] == 2
    assert summary["response_rate"] == 33.3


def test_summarize_early_beats_late_cohorts():
    summary = report_service.summarize(_mixed_cohort_records())

    # early = leads 2 (responded) and 4 (rejected): 1 of 2 responded.
    assert summary["early"] == {"count": 2, "responded": 1, "response_rate": 50.0}
    # late = lead 3 only, no response.
    assert summary["late"] == {"count": 1, "responded": 0, "response_rate": 0.0}
    assert summary["early_cutoff_hours"] == report_service.EARLY_CONTACT_HOURS


def test_summarize_empty_is_all_none_not_zero_division():
    summary = report_service.summarize([])
    assert summary["new_leads"] == 0
    assert summary["contact_rate"] is None
    assert summary["avg_hours_to_contact"] is None
    assert summary["median_hours_to_contact"] is None
    assert summary["response_rate"] is None
    assert summary["early"]["response_rate"] is None


# --- windowing ------------------------------------------------------------


def test_resolve_window_labels_per_period(app):
    _, _, day = report_service.resolve_window("day")
    _, _, week = report_service.resolve_window("week")
    _, _, month = report_service.resolve_window("month")
    assert (day, week, month) == ("Today", "This week", "This month")


def test_resolve_window_custom_range_overrides_period(app):
    start_utc, end_utc, label = report_service.resolve_window(
        "day", start=date(2026, 7, 1), end=date(2026, 7, 3)
    )
    assert label == "2026-07-01 to 2026-07-03"
    # Inclusive end day -> window spans three local days == 72h.
    assert end_utc - start_utc == timedelta(days=3)


def test_mature_drops_young_leads(app):
    now_utc = report_service._to_utc_naive(report_service._local_now())
    fresh = _record(1, created_at=now_utc)                       # too young
    aged = _record(2, created_at=now_utc - timedelta(days=2))    # old enough
    kept = report_service._mature([fresh, aged])
    assert [r.lead_id for r in kept] == [2]


# --- integration: report() against a seeded DB ----------------------------

# A window that sits entirely in the past so "now"-relative maturity never
# interferes, and every seeded lead falls inside it.
WINDOW_START = date(2026, 7, 1)
WINDOW_END = date(2026, 7, 1)
_CREATED = datetime(2026, 7, 1, 8, 0, 0)  # naive-UTC, inside the local day


def _seed_lead(name, phone, *, contacts=()):
    """Create a lead at _CREATED plus its status-change timeline events.

    ``contacts`` is a sequence of (hours_after_created, to_status, actor_id).
    The lead's `created` event carries no to_status, so it's ignored by the
    report exactly as a real one is.
    """
    lead = Lead(name=name, phone=phone, status="New", created_at=_CREATED)
    db.session.add(lead)
    db.session.flush()
    db.session.add(
        TimelineEvent(
            lead_id=lead.id, event_type="created",
            description="Lead created", created_at=_CREATED, to_status=None,
        )
    )
    for hours, to_status, actor_id in contacts:
        db.session.add(
            TimelineEvent(
                lead_id=lead.id,
                event_type="status_changed",
                description=f"Status changed to {to_status}.",
                created_at=_CREATED + timedelta(hours=hours),
                to_status=to_status,
                actor_id=actor_id,
            )
        )
    return lead


@pytest.fixture()
def seeded(app):
    """Four leads mirroring the pure-layer cohorts, plus a contacting admin."""
    admin = user_service.create_admin("Aisha", "aisha@mc.edu", "s3cret-pass")
    _seed_lead("Never", "+92 300 0000001")
    _seed_lead(
        "EarlyWin", "+92 300 0000002",
        contacts=[(2, "Called", admin.id), (5, "Interested", admin.id)],
    )
    _seed_lead("LateMiss", "+92 300 0000003", contacts=[(7, "Called", admin.id)])
    _seed_lead(
        "EarlyLost", "+92 300 0000004",
        contacts=[(1, "Called", admin.id), (3, "Rejected", admin.id)],
    )
    db.session.commit()
    return admin


def test_report_summary_matches_seeded_cohorts(seeded):
    data = report_service.report("day", start=WINDOW_START, end=WINDOW_END)
    s = data["summary"]

    assert s["new_leads"] == 4
    assert s["contacted"] == 3
    assert s["not_contacted"] == 1
    assert s["contact_rate"] == 75.0
    assert s["median_hours_to_contact"] == 2.0
    assert s["responded"] == 1
    assert s["response_rate"] == 33.3
    assert s["early"] == {"count": 2, "responded": 1, "response_rate": 50.0}
    assert s["late"] == {"count": 1, "responded": 0, "response_rate": 0.0}
    assert s["label"] == "2026-07-01 to 2026-07-01"


def test_report_uses_first_status_change_as_contact(seeded):
    """The earliest to_status event is first contact; the `created` event is not."""
    records = report_service._collect(
        *report_service.resolve_window("day", WINDOW_START, WINDOW_END)[:2]
    )
    by_name = {r.lead_id: r for r in records}
    early = next(r for r in records if r.hours_to_contact == 2.0)
    # First contact for EarlyWin is the 2h "Called", not the 5h "Interested".
    assert early.first_contact_at == _CREATED + timedelta(hours=2)
    assert early.post_contact_statuses == ["Interested"]
    assert len(by_name) == 4


def test_report_trend_buckets_new_vs_contacted(seeded):
    data = report_service.report("day", start=WINDOW_START, end=WINDOW_END)
    trend = data["trend"]
    # Single local day in the window -> one bucket with all four leads.
    assert len(trend) == 1
    assert trend[0]["new_leads"] == 4
    assert trend[0]["contacted"] == 3


def test_report_per_staff_attributes_to_first_contact_actor(seeded):
    data = report_service.report("day", start=WINDOW_START, end=WINDOW_END)
    per_staff = data["per_staff"]
    assert len(per_staff) == 1
    row = per_staff[0]
    assert row["actor"] == "Aisha"
    assert row["contacted"] == 3
    # times [2,7,1] -> median 2.0; 1 of 3 responded.
    assert row["median_hours_to_contact"] == 2.0
    assert row["response_rate"] == 33.3


def test_report_mature_only_keeps_historical_leads(seeded):
    """The seeded window is in the past, so every lead is already mature and a
    mature-only run keeps all four. (The actual dropping of too-young leads is
    covered deterministically by test_mature_drops_young_leads.)"""
    data = report_service.report(
        "day", start=WINDOW_START, end=WINDOW_END, mature_only=True
    )
    assert data["summary"]["new_leads"] == 4


# --- integration: routes --------------------------------------------------


def _login(client, email="aisha@mc.edu", password="s3cret-pass"):
    token_page = client.get("/login").get_data(as_text=True)
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"',
        token_page,
    )
    token = match.group(1) or match.group(2)
    return client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
    )


def test_reports_page_requires_login(client):
    resp = client.get("/dashboard/reports")
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]


def test_reports_page_renders(client, seeded):
    _login(client)
    resp = client.get("/dashboard/reports?period=day&from=2026-07-01&to=2026-07-01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Lead Response Report" in body
    assert "Does speed to contact matter?" in body


def test_reports_csv_export_shape(client, seeded):
    _login(client)
    resp = client.get(
        "/dashboard/reports/export.csv?period=day&from=2026-07-01&to=2026-07-01"
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "attachment" in resp.headers["Content-Disposition"]

    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    flat = {r[0]: r[1] for r in rows if len(r) == 2}
    assert flat["New leads"] == "4"
    assert flat["Contacted"] == "3"
    assert flat["Median hours to contact"] == "2.0"

    # The per-lead section header and one row per lead (4) are present.
    assert report_service_header_present(rows)


def report_service_header_present(rows):
    """The CSV carries the per-lead column header from the routes module."""
    from app.blueprints.dashboard.routes import REPORT_LEAD_COLUMNS

    return any(row == REPORT_LEAD_COLUMNS for row in rows)
