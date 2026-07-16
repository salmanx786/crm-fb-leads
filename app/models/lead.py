from app.extensions import db
from app.models.base import BaseModel


class Lead(BaseModel):
    """A prospective student captured from the landing page form."""

    __tablename__ = "leads"

    # Applicant-provided fields
    name: str = db.Column(db.String(120), nullable=False)
    phone: str = db.Column(db.String(20), nullable=False)
    email: str = db.Column(db.String(255), nullable=True)
    city: str = db.Column(db.String(120), nullable=True)
    course: str = db.Column(db.String(120), nullable=True)
    message: str = db.Column(db.Text, nullable=True)

    # Attribution / tracking
    utm_source: str = db.Column(db.String(120), nullable=True)
    utm_medium: str = db.Column(db.String(120), nullable=True)
    utm_campaign: str = db.Column(db.String(120), nullable=True)
    referrer: str = db.Column(db.String(512), nullable=True)
    ip_address: str = db.Column(db.String(45), nullable=True)  # supports IPv6
    user_agent: str = db.Column(db.String(512), nullable=True)

    # Management. Stored as a plain string; valid values live in
    # app.constants.LEAD_STATUSES so we can add stages without a migration.
    status: str = db.Column(db.String(32), default="New", nullable=False)

    # Indexes for the columns the dashboard filters and sorts on. The
    # composite (status, created_at) index backs the common "leads in a given
    # stage, newest first" query the listing view runs.
    __table_args__ = (
        db.Index("ix_leads_status", "status"),
        db.Index("ix_leads_phone", "phone"),
        db.Index("ix_leads_email", "email"),
        db.Index("ix_leads_city", "city"),
        db.Index("ix_leads_course", "course"),
        db.Index("ix_leads_status_created_at", "status", "created_at"),
    )

    # Related records. Deleting a lead cleans up its notes and timeline.
    notes = db.relationship(
        "LeadNote",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadNote.created_at.desc()",
    )
    timeline = db.relationship(
        "TimelineEvent",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="TimelineEvent.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Lead {self.name} ({self.phone})>"


class LeadNote(BaseModel):
    """A free-text note an admin attaches to a lead (call summary, remark)."""

    __tablename__ = "lead_notes"

    lead_id: int = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: int = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: str = db.Column(db.Text, nullable=False)

    lead = db.relationship("Lead", back_populates="notes")
    author = db.relationship("User")

    def __repr__(self) -> str:
        return f"<LeadNote lead={self.lead_id}>"


class TimelineEvent(BaseModel):
    """An immutable audit entry describing something that happened to a lead.

    Examples: lead created, status changed, note added. Kept separate from
    LeadNote so the activity history is system-generated and append-only.
    """

    __tablename__ = "timeline_events"

    lead_id: int = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: int = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Machine-readable kind, e.g. "created", "status_changed", "note_added".
    event_type: str = db.Column(db.String(50), nullable=False)
    # Human-readable summary rendered in the lead detail timeline.
    description: str = db.Column(db.String(512), nullable=False)

    lead = db.relationship("Lead", back_populates="timeline")
    actor = db.relationship("User")

    def __repr__(self) -> str:
        return f"<TimelineEvent {self.event_type} lead={self.lead_id}>"
