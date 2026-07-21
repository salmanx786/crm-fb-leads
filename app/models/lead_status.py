"""Admin-editable lead lifecycle stages, backed by a DB table.

Historically the lifecycle was a hardcoded Python list (``constants.LEAD_STATUSES``)
plus a hardcoded status->Meta-event dict (``constants.META_EVENT_MAP``). This
table makes both editable from the dashboard: an admin can add/rename/remove
statuses and choose which standard Meta (Facebook) event each one reports for
conversion-quality optimization.

The lead's own ``status`` column stays a plain string (see ``Lead.status``);
this table is the source of truth for *which* statuses are valid, their display
order, and their Meta mapping. The constants remain as the one-time seed source
so a fresh/empty table reproduces today's exact behaviour.
"""
from app.extensions import db
from app.models.base import BaseModel


class LeadStatus(BaseModel):
    """One lead lifecycle stage.

    - ``name`` is the label shown in dropdowns and stored on leads.
    - ``meta_event`` is the standard Meta event fired when a lead reaches this
      status, or NULL for "don't send to Meta" (internal-only stages like Spam).
    - ``sort_order`` drives dropdown/filter order (ascending; ties break on id).
    - ``is_protected`` marks the default status ("New") so it can't be deleted.
    """

    __tablename__ = "lead_statuses"

    name = db.Column(db.String(64), nullable=False, unique=True, index=True)
    meta_event = db.Column(db.String(64), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_protected = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<LeadStatus {self.name} meta={self.meta_event or '-'}>"
