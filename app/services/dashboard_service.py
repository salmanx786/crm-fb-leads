"""Read-side queries for the dashboard: metrics and paginated lead listings.

Keeps aggregation SQL out of the view functions and gives the templates a
stable, named data shape to render. All queries use the SQLAlchemy 2.x
session API (select/execute/scalar) rather than the legacy Model.query.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select

from app.constants import is_valid_status
from app.extensions import db
from app.models import Lead


# --- date boundaries ------------------------------------------------------
# Centralised so the metric cards and the "period" list filter agree on what
# "today" and "this week" mean (server-local/UTC midnight, week starts Monday).

def _start_of_today() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _start_of_week() -> datetime:
    start = _start_of_today()
    return start - timedelta(days=start.weekday())


def _period_start(period: Optional[str]) -> Optional[datetime]:
    """Map a period keyword to its lower-bound datetime, or None for all-time."""
    if period == "today":
        return _start_of_today()
    if period == "week":
        return _start_of_week()
    return None


# --- metrics --------------------------------------------------------------

def get_metrics() -> dict[str, int]:
    """Headline counts for the dashboard cards.

    One aggregate query per time window plus a single grouped query for the
    per-status counts, so adding/removing a status card costs no extra SQL.
    """
    today = db.session.scalar(
        select(func.count(Lead.id)).where(Lead.created_at >= _start_of_today())
    )
    this_week = db.session.scalar(
        select(func.count(Lead.id)).where(Lead.created_at >= _start_of_week())
    )
    total = db.session.scalar(select(func.count(Lead.id)))

    # Every status/count pair in one round trip; read the ones we surface.
    status_rows = db.session.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    ).all()
    by_status = {status: count for status, count in status_rows}

    return {
        "today": today or 0,
        "this_week": this_week or 0,
        "total": total or 0,
        "new": by_status.get("New", 0),
        "follow_up": by_status.get("Follow-up", 0),
        "documents_pending": by_status.get("Documents Pending", 0),
        "interested": by_status.get("Interested", 0),
        "admitted": by_status.get("Admitted", 0),
    }


# --- listings -------------------------------------------------------------

def follow_up_state(value: Optional[datetime]) -> Optional[str]:
    """Classify a follow-up datetime for badge display.

    Returns "overdue" / "today" / "upcoming", or None when unscheduled. Shares
    the same midnight boundaries as the list filters so the badge a lead shows
    always agrees with the filter that would select it.
    """
    if value is None:
        return None
    today = _start_of_today()
    tomorrow = today + timedelta(days=1)
    if value < today:
        return "overdue"
    if value < tomorrow:
        return "today"
    return "upcoming"


def _apply_follow_up_filter(stmt, follow_up: Optional[str]):
    """Add a follow-up date predicate to `stmt`, entirely in SQL.

    All four filters are index-friendly range/NULL scans on next_follow_up_at
    (no rows loaded into Python):
      overdue      — scheduled before today's midnight
      today        — scheduled within [today 00:00, tomorrow 00:00)
      upcoming     — scheduled at/after tomorrow's midnight
      no_follow_up — never scheduled (NULL)
    Unknown/blank values leave the statement unchanged (all leads).
    """
    if follow_up == "no_follow_up":
        return stmt.where(Lead.next_follow_up_at.is_(None))

    today = _start_of_today()
    tomorrow = today + timedelta(days=1)

    if follow_up == "overdue":
        return stmt.where(
            Lead.next_follow_up_at.isnot(None),
            Lead.next_follow_up_at < today,
        )
    if follow_up == "today":
        return stmt.where(
            Lead.next_follow_up_at >= today,
            Lead.next_follow_up_at < tomorrow,
        )
    if follow_up == "upcoming":
        return stmt.where(Lead.next_follow_up_at >= tomorrow)
    return stmt


def _filtered_leads_stmt(
    search: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
    follow_up: Optional[str] = None,
):
    """Build the filtered, newest-first `select(Lead)` shared by the listing.

    Single source of truth for the dashboard's lead filters so the paginated
    list (`list_leads`) and the full-set export (`filtered_leads`) apply
    identical SQL — no duplicated WHERE logic.

    `search` matches name/phone/email/city/course (case-insensitive);
    `status` filters by exact stage; `period` ("today"/"week") bounds by
    creation time; `follow_up` ("overdue"/"today"/"upcoming"/"no_follow_up")
    bounds by the next follow-up date. All filters compose and run in SQL.
    """
    stmt = select(Lead)

    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.name.ilike(term),
                Lead.phone.ilike(term),
                Lead.email.ilike(term),
                Lead.city.ilike(term),
                Lead.course.ilike(term),
            )
        )

    if status and is_valid_status(status):
        stmt = stmt.where(Lead.status == status)

    since = _period_start(period)
    if since is not None:
        stmt = stmt.where(Lead.created_at >= since)

    stmt = _apply_follow_up_filter(stmt, follow_up)

    return stmt.order_by(Lead.created_at.desc())


def list_leads(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
    follow_up: Optional[str] = None,
):
    """Return a Flask-SQLAlchemy Pagination of leads, newest first.

    Applies the shared dashboard filters (see `_filtered_leads_stmt`) and wraps
    the result in the familiar Pagination object (items, pages, has_next,
    iter_pages, ...).
    """
    stmt = _filtered_leads_stmt(search, status, period, follow_up)
    return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def filtered_leads(
    search: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
    follow_up: Optional[str] = None,
) -> list[Lead]:
    """Every lead matching the dashboard filters, newest first (unpaginated).

    Reuses the exact same filter SQL as `list_leads` via `_filtered_leads_stmt`.
    Backs the CSV export, which needs the full filtered set rather than a page.
    """
    return list(db.session.scalars(_filtered_leads_stmt(search, status, period, follow_up)))


def recent_leads(limit: int = 5) -> list[Lead]:
    """Most recently captured leads for the dashboard home panel."""
    return list(
        db.session.scalars(
            select(Lead).order_by(Lead.created_at.desc()).limit(limit)
        )
    )


# --- duplicate detection --------------------------------------------------
# Duplicates are never prevented at capture time: every form submission is its
# own Lead row. Instead we surface, per lead, how many submissions share the
# same phone OR email. Counts are computed on read via SQL aggregation and are
# never stored on the model.

def duplicate_counts(leads: list[Lead]) -> dict[int, int]:
    """Map each lead's id to the size of its duplicate group.

    A lead's "group" is every submission sharing its phone OR its email
    (email is only considered when present). The returned count includes the
    lead itself, so a value of 1 means "no duplicates" and the listing shows a
    badge only when the count exceeds 1. This equals the number of rows the
    drill-down (`matching_submissions`) lists, keeping badge and list in sync.

    Cost is independent of page size: three grouped aggregate queries over the
    page's distinct phone/email values, not one round trip per lead.
    """
    if not leads:
        return {}

    phones = {lead.phone for lead in leads if lead.phone}
    emails = {lead.email for lead in leads if lead.email}

    # How many submissions share each phone / each email on this page.
    phone_counts: dict[str, int] = {}
    if phones:
        phone_counts = dict(
            db.session.execute(
                select(Lead.phone, func.count(Lead.id))
                .where(Lead.phone.in_(phones))
                .group_by(Lead.phone)
            ).all()
        )

    email_counts: dict[str, int] = {}
    if emails:
        email_counts = dict(
            db.session.execute(
                select(Lead.email, func.count(Lead.id))
                .where(Lead.email.in_(emails))
                .group_by(Lead.email)
            ).all()
        )

    # Overlap: submissions sharing BOTH the same phone and email, so leads
    # matched by phone *and* email aren't counted twice (inclusion-exclusion).
    both_counts: dict[tuple[str, str], int] = {}
    if phones and emails:
        both_counts = {
            (phone, email): count
            for phone, email, count in db.session.execute(
                select(Lead.phone, Lead.email, func.count(Lead.id))
                .where(Lead.phone.in_(phones), Lead.email.in_(emails))
                .group_by(Lead.phone, Lead.email)
            ).all()
        }

    counts: dict[int, int] = {}
    for lead in leads:
        group = phone_counts.get(lead.phone, 0)
        if lead.email:
            group += email_counts.get(lead.email, 0)
            group -= both_counts.get((lead.phone, lead.email), 0)
        counts[lead.id] = group
    return counts


def matching_submissions(lead: Lead) -> list[Lead]:
    """Every submission sharing this lead's phone or email, newest first.

    Includes the lead itself. Backs the duplicate-badge drill-down; the row
    count matches the badge produced by `duplicate_counts`.
    """
    conditions = [Lead.phone == lead.phone]
    if lead.email:
        conditions.append(Lead.email == lead.email)

    return list(
        db.session.scalars(
            select(Lead)
            .where(or_(*conditions))
            .order_by(Lead.created_at.desc())
        )
    )
