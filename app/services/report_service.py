"""Lead-response analytics for the reports dashboard.

Answers, for a Day / Week / Month (or custom) window: how many leads arrived,
how many we contacted vs didn't, how fast we contacted them, and — the headline
— whether contacting quickly drives a higher response rate than contacting late.

Design notes
------------
* **Contacted** = the lead's *first status change* off "New". Its moment is the
  earliest ``TimelineEvent`` carrying a ``to_status`` (see that column). We read
  the structured ``to_status``, never the human-readable description.
* **Lead-to-contact time** = ``first_contact_at - lead.created_at``, reported as
  both **median** and **average** (median resists the one lead called days late).
* **Responded** = a contacted lead that *progressed beyond its first contact* to
  a non-lost stage (see ``LOST_STATUSES``). Reaching only the first contact
  stage, or only a lost stage after it, is "contacted, no response".
* **Early vs late** = contacted within ``EARLY_CONTACT_HOURS`` vs later, compared
  by response rate. This is the number the page exists to surface.

Windowing is timezone-aware (``REPORT_TZ``): ``created_at`` is stored naive-UTC,
but a "day" must mean a local day, so boundaries are computed in local time and
converted back to UTC for the query. Aggregation (median especially) is done in
Python from a small per-lead record set — dialect-safe across SQLite and
PostgreSQL, and the volume here is an admissions pipeline, not a firehose.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import mean, median
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.extensions import db
from app.models import Lead, TimelineEvent, User

# --- tunable knobs --------------------------------------------------------
# Kept as module constants (documented) rather than settings: they encode the
# report's definitions, and a code edit is the right ceremony for changing them.

# Business timezone for day/week/month boundaries. Pakistan (fixed UTC+5, no DST).
REPORT_TZ = ZoneInfo("Asia/Karachi")

# The early/late split for the speed-to-contact comparison.
EARLY_CONTACT_HOURS = 4.0

# Terminal-negative stages. A lead whose only post-contact move is into one of
# these did not "respond". Matched by name; mirrors the seeded lifecycle. Rename
# a status and you'd update this set (the one place the report knows about it).
LOST_STATUSES = frozenset({"Rejected", "Spam"})

# A lead created less than this long ago hasn't had a fair chance to respond;
# the "mature only" view drops them so the late/recent cohort isn't understated.
RESPONSE_MATURITY_HOURS = 24.0

VALID_PERIODS = ("day", "week", "month")


# --- windowing ------------------------------------------------------------

def _local_now() -> datetime:
    """Current time in the business timezone (aware)."""
    return datetime.now(REPORT_TZ)


def _to_utc_naive(local_dt: datetime) -> datetime:
    """Convert an aware local datetime to the naive-UTC form stored on rows."""
    return local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _local_midnight(d: date) -> datetime:
    """Aware local midnight at the start of local date ``d``."""
    return datetime.combine(d, time.min, tzinfo=REPORT_TZ)


def resolve_window(
    period: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> tuple[datetime, datetime, str]:
    """Return the ``[start_utc, end_utc)`` window and a human label.

    ``period`` is one of VALID_PERIODS. A custom ``start``/``end`` (inclusive
    local dates) overrides ``period`` when both are given. Bounds are local-time
    midnights converted to naive UTC, so a lead is counted on the local calendar
    day it arrived.
    """
    today = _local_now().date()

    if start and end:
        start_local = _local_midnight(start)
        end_local = _local_midnight(end + timedelta(days=1))  # inclusive end day
        label = f"{start.isoformat()} to {end.isoformat()}"
        return _to_utc_naive(start_local), _to_utc_naive(end_local), label

    if period == "week":
        monday = today - timedelta(days=today.weekday())
        start_local = _local_midnight(monday)
        label = "This week"
    elif period == "month":
        start_local = _local_midnight(today.replace(day=1))
        label = "This month"
    else:  # "day" and any unknown value fall back to today
        start_local = _local_midnight(today)
        label = "Today"

    end_local = _local_midnight(today + timedelta(days=1))
    return _to_utc_naive(start_local), _to_utc_naive(end_local), label


# --- per-lead record ------------------------------------------------------

@dataclass
class LeadRecord:
    """One lead's response facts, derived from its status-change timeline."""

    lead_id: int
    created_at: datetime
    first_contact_at: Optional[datetime]
    first_contact_actor_id: Optional[int]
    # Statuses the lead moved to *after* first contact, in order.
    post_contact_statuses: list[str]

    @property
    def contacted(self) -> bool:
        return self.first_contact_at is not None

    @property
    def hours_to_contact(self) -> Optional[float]:
        if self.first_contact_at is None:
            return None
        delta = self.first_contact_at - self.created_at
        return max(delta.total_seconds() / 3600.0, 0.0)

    @property
    def responded(self) -> bool:
        """Progressed beyond first contact to at least one non-lost stage."""
        return any(s not in LOST_STATUSES for s in self.post_contact_statuses)

    @property
    def cohort(self) -> Optional[str]:
        """'early' / 'late' for contacted leads, else None."""
        hours = self.hours_to_contact
        if hours is None:
            return None
        return "early" if hours <= EARLY_CONTACT_HOURS else "late"


def _collect(start_utc: datetime, end_utc: datetime) -> list[LeadRecord]:
    """Build a LeadRecord per lead created in the window.

    Two queries: the leads in-window, and every status-change event for those
    leads (``to_status`` not null), read in chronological order so the first row
    per lead is its first contact and the rest are its progression.
    """
    leads = list(
        db.session.execute(
            select(Lead.id, Lead.created_at).where(
                Lead.created_at >= start_utc, Lead.created_at < end_utc
            )
        ).all()
    )
    if not leads:
        return []

    lead_ids = [row.id for row in leads]

    events = db.session.execute(
        select(
            TimelineEvent.lead_id,
            TimelineEvent.created_at,
            TimelineEvent.to_status,
            TimelineEvent.actor_id,
        )
        .where(
            TimelineEvent.lead_id.in_(lead_ids),
            TimelineEvent.to_status.is_not(None),
        )
        .order_by(TimelineEvent.lead_id, TimelineEvent.created_at, TimelineEvent.id)
    ).all()

    # Group status changes per lead (already chronological within each lead).
    changes: dict[int, list] = {}
    for ev in events:
        changes.setdefault(ev.lead_id, []).append(ev)

    records: list[LeadRecord] = []
    for row in leads:
        lead_changes = changes.get(row.id, [])
        if lead_changes:
            first = lead_changes[0]
            records.append(
                LeadRecord(
                    lead_id=row.id,
                    created_at=row.created_at,
                    first_contact_at=first.created_at,
                    first_contact_actor_id=first.actor_id,
                    post_contact_statuses=[c.to_status for c in lead_changes[1:]],
                )
            )
        else:
            records.append(
                LeadRecord(
                    lead_id=row.id,
                    created_at=row.created_at,
                    first_contact_at=None,
                    first_contact_actor_id=None,
                    post_contact_statuses=[],
                )
            )
    return records


def _mature(records: list[LeadRecord]) -> list[LeadRecord]:
    """Drop leads too young to have had a fair chance to respond."""
    cutoff = _to_utc_naive(_local_now()) - timedelta(hours=RESPONSE_MATURITY_HOURS)
    return [r for r in records if r.created_at <= cutoff]


# --- summarising (pure) ---------------------------------------------------

def _rate(part: int, whole: int) -> Optional[float]:
    """Percentage part/whole, or None when there's nothing to divide."""
    return round(100.0 * part / whole, 1) if whole else None


def _cohort_stats(records: list[LeadRecord], cohort: str) -> dict:
    members = [r for r in records if r.cohort == cohort]
    responded = sum(1 for r in members if r.responded)
    return {
        "count": len(members),
        "responded": responded,
        "response_rate": _rate(responded, len(members)),
    }


def summarize(records: list[LeadRecord]) -> dict:
    """Aggregate a set of LeadRecords into the report's numbers. Pure."""
    total = len(records)
    contacted = [r for r in records if r.contacted]
    responded = sum(1 for r in contacted if r.responded)
    times = [r.hours_to_contact for r in contacted]

    return {
        "new_leads": total,
        "contacted": len(contacted),
        "not_contacted": total - len(contacted),
        "contact_rate": _rate(len(contacted), total),
        "avg_hours_to_contact": round(mean(times), 1) if times else None,
        "median_hours_to_contact": round(median(times), 1) if times else None,
        "responded": responded,
        "not_responded": len(contacted) - responded,
        "response_rate": _rate(responded, len(contacted)),
        "early": _cohort_stats(contacted, "early"),
        "late": _cohort_stats(contacted, "late"),
        "early_cutoff_hours": EARLY_CONTACT_HOURS,
    }


# --- public API -----------------------------------------------------------

def report(
    period: str = "day",
    start: Optional[date] = None,
    end: Optional[date] = None,
    mature_only: bool = False,
) -> dict:
    """Full report payload for the page/CSV: summary, cohorts, trend, staff."""
    start_utc, end_utc, label = resolve_window(period, start, end)
    records = _collect(start_utc, end_utc)
    if mature_only:
        records = _mature(records)

    summary = summarize(records)
    summary.update(
        period=period,
        label=label,
        mature_only=mature_only,
        start=start_utc,
        end=end_utc,
    )
    return {
        "summary": summary,
        "trend": _trend(records, start_utc, end_utc, period),
        "per_staff": _per_staff(records),
        "records": records,  # per-lead rows for the CSV export
    }


def _trend(
    records: list[LeadRecord], start_utc: datetime, end_utc: datetime, period: str
) -> list[dict]:
    """New vs contacted counts bucketed by local calendar day across the window.

    (A single-day window yields one bucket; week/month yield one per day.) Buckets
    are keyed on the local date the lead was *created*.
    """
    def local_day(dt: datetime) -> date:
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(REPORT_TZ).date()

    # Pre-seed every day in the window so gaps render as zero, not missing bars.
    buckets: dict[date, dict] = {}
    cursor = local_day(start_utc)
    last = local_day(end_utc - timedelta(seconds=1))
    while cursor <= last:
        buckets[cursor] = {"date": cursor.isoformat(), "new_leads": 0, "contacted": 0}
        cursor += timedelta(days=1)

    for r in records:
        day = local_day(r.created_at)
        bucket = buckets.get(day)
        if bucket is None:  # defensive; shouldn't happen given the window
            continue
        bucket["new_leads"] += 1
        if r.contacted:
            bucket["contacted"] += 1

    return [buckets[d] for d in sorted(buckets)]


def _per_staff(records: list[LeadRecord]) -> list[dict]:
    """Per-admin first-contact volume and median response time.

    Attributed to whoever logged the lead's *first* status change. Leads with no
    identified actor (e.g. system/bulk without an actor) are grouped as "—".
    """
    by_actor: dict[Optional[int], list[LeadRecord]] = {}
    for r in records:
        if r.contacted:
            by_actor.setdefault(r.first_contact_actor_id, []).append(r)

    if not by_actor:
        return []

    # Resolve names in one query.
    actor_ids = [aid for aid in by_actor if aid is not None]
    names: dict[int, str] = {}
    if actor_ids:
        names = {
            u.id: (u.name or u.email or f"User {u.id}")
            for u in db.session.scalars(select(User).where(User.id.in_(actor_ids)))
        }

    rows = []
    for actor_id, member in by_actor.items():
        times = [r.hours_to_contact for r in member]
        responded = sum(1 for r in member if r.responded)
        rows.append(
            {
                "actor": names.get(actor_id, "—") if actor_id is not None else "—",
                "contacted": len(member),
                "median_hours_to_contact": round(median(times), 1),
                "response_rate": _rate(responded, len(member)),
            }
        )
    # Busiest first.
    rows.sort(key=lambda r: r["contacted"], reverse=True)
    return rows
