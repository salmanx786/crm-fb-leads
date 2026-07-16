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

def list_leads(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
):
    """Return a Flask-SQLAlchemy Pagination of leads, newest first.

    `search` matches name/phone/email/city/course (case-insensitive);
    `status` filters by exact stage; `period` ("today"/"week") bounds by
    creation time so the metric cards can deep-link into a filtered list.
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

    stmt = stmt.order_by(Lead.created_at.desc())

    # db.paginate runs the select and wraps it in the familiar Pagination
    # object (items, pages, has_next, iter_pages, ...).
    return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def recent_leads(limit: int = 5) -> list[Lead]:
    """Most recently captured leads for the dashboard home panel."""
    return list(
        db.session.scalars(
            select(Lead).order_by(Lead.created_at.desc()).limit(limit)
        )
    )
