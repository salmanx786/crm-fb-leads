"""Read-side queries for the dashboard: metrics and paginated lead listings.

Keeps aggregation SQL out of the view functions and gives the templates a
stable, named data shape to render.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func

from app.constants import ADMITTED_STATUS, is_valid_status
from app.extensions import db
from app.models import Lead


def get_metrics() -> dict[str, int]:
    """Headline counts for the dashboard cards."""
    now = datetime.utcnow()
    start_of_today = datetime(now.year, now.month, now.day)
    start_of_week = start_of_today - timedelta(days=start_of_today.weekday())

    today = db.session.query(func.count(Lead.id)).filter(
        Lead.created_at >= start_of_today
    ).scalar()
    this_week = db.session.query(func.count(Lead.id)).filter(
        Lead.created_at >= start_of_week
    ).scalar()
    total = db.session.query(func.count(Lead.id)).scalar()

    # Per-status counts the dashboard cards surface. One query returns every
    # status/count pair; we read the ones we care about from the mapping.
    status_rows = (
        db.session.query(Lead.status, func.count(Lead.id))
        .group_by(Lead.status)
        .all()
    )
    by_status = {status: count for status, count in status_rows}

    return {
        "today": today or 0,
        "this_week": this_week or 0,
        "total": total or 0,
        "interested": by_status.get("Interested", 0),
        "admitted": by_status.get(ADMITTED_STATUS, 0),
        "rejected": by_status.get("Rejected", 0),
    }


def list_leads(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
):
    """Return a Flask-SQLAlchemy Pagination of leads, newest first.

    `search` matches name/phone/email; `status` filters by exact stage.
    """
    query = Lead.query

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            db.or_(
                Lead.name.ilike(term),
                Lead.phone.ilike(term),
                Lead.email.ilike(term),
            )
        )

    if status and is_valid_status(status):
        query = query.filter(Lead.status == status)

    query = query.order_by(Lead.created_at.desc())
    return query.paginate(page=page, per_page=per_page, error_out=False)


def recent_leads(limit: int = 5) -> list[Lead]:
    """Most recently captured leads for the dashboard home panel."""
    return Lead.query.order_by(Lead.created_at.desc()).limit(limit).all()
