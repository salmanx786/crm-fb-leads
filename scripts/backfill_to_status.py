"""Backfill TimelineEvent.to_status for rows created before the column existed.

The `to_status` column (added to `timeline_events` for the lead reports) is
populated going forward by lead_service. This one-off script recovers the value
for *historical* `status_changed` rows by parsing it out of their human-readable
description, which has the stable form "Status changed from X to Y.".

Only `status_changed` rows are recoverable: edit-form status changes were logged
as "updated" events whose description ("Lead updated: Status, ...") does not name
the target stage, so those stay NULL — the reports simply treat a lead's first
recoverable status change as its first contact.

Additive and idempotent: only rows where to_status IS NULL are touched, and a
second run finds nothing to do. Run it once after deploying the column
(alongside / after scripts/sync_db.py). For cPanel's "Execute python script"
field (no TTY), point it at this file.
"""
import os
import re
import sys

# Running a script puts scripts/ on sys.path, not the project root; add the
# project root explicitly (mirrors init_db.py / sync_db.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import TimelineEvent

# "Status changed from <old> to <new>." — capture <new>, tolerating a missing
# trailing period. Anchored to end so an old/new name containing " to " is safe.
_PATTERN = re.compile(r"^Status changed from .+ to (?P<to>.+?)\.?$")


def backfill() -> int:
    """Populate to_status on legacy status_changed rows. Returns rows updated."""
    rows = db.session.scalars(
        select(TimelineEvent).where(
            TimelineEvent.event_type == "status_changed",
            TimelineEvent.to_status.is_(None),
        )
    )
    updated = 0
    for event in rows:
        match = _PATTERN.match(event.description or "")
        if match:
            event.to_status = match.group("to").strip()
            updated += 1
    db.session.commit()
    return updated


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        count = backfill()
        print(f"Backfilled to_status on {count} timeline event(s).")
