from app.extensions import db
from app.models.base import BaseModel


class Lead(BaseModel):
    """A prospective student captured from the landing page form."""

    __tablename__ = "leads"

    # Applicant-provided fields.
    # `first_name`/`last_name` are the source of truth captured by the form;
    # `name` holds the composed "First Last" display value and remains the
    # single field the dashboard listing, search, CSV, duplicate detection, and
    # Meta events read — so those paths don't need to know the name is split.
    first_name = db.Column(db.String(60), nullable=True)
    last_name = db.Column(db.String(60), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    course = db.Column(db.String(120), nullable=True)
    message = db.Column(db.Text, nullable=True)

    # Program selection (Step 1). `course` holds the program label (DPT / BSMT);
    # `specialization` holds the BSMT track (Clinical Laboratory Sciences /
    # Radiological Imaging) and is null for DPT.
    specialization = db.Column(db.String(120), nullable=True)

    # Guardian / contact (Step 3)
    guardian_name = db.Column(db.String(120), nullable=True)
    guardian_phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(512), nullable=True)

    # Academic qualifications (Step 2)
    matric_board = db.Column(db.String(120), nullable=True)
    matric_year = db.Column(db.String(10), nullable=True)
    matric_marks = db.Column(db.String(30), nullable=True)
    inter_board = db.Column(db.String(120), nullable=True)
    inter_year = db.Column(db.String(10), nullable=True)
    inter_marks = db.Column(db.String(30), nullable=True)
    inter_group = db.Column(db.String(60), nullable=True)  # Pre-Medical / Other

    # Attribution / tracking
    utm_source = db.Column(db.String(120), nullable=True)
    utm_medium = db.Column(db.String(120), nullable=True)
    utm_campaign = db.Column(db.String(120), nullable=True)
    referrer = db.Column(db.String(512), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)  # supports IPv6
    user_agent = db.Column(db.String(512), nullable=True)
    # Meta (Facebook) click and browser identifiers, captured from the `_fbc`
    # and `_fbp` cookies the Pixel sets. Stored on the lead (not just the
    # request) because meta_service rebuilds the Conversions API payload from
    # the lead on retry, long after the request cookies are gone. Sending them
    # markedly raises event match quality.
    fbc = db.Column(db.String(255), nullable=True)
    fbp = db.Column(db.String(255), nullable=True)

    # Management. Stored as a plain string; valid values live in
    # app.constants.LEAD_STATUSES so we can add stages without a migration.
    status = db.Column(db.String(32), default="New", nullable=False)

    # When the next follow-up call/action is due. Nullable: a lead with no
    # scheduled follow-up is a first-class state ("No Follow-up" filter). Set
    # and cleared only through lead_service so every change is timelined.
    next_follow_up_at = db.Column(db.DateTime, nullable=True)

    # When a "follow-up due" push reminder was last sent for the current
    # follow-up. Nullable (never reminded). The reminder sweep only notifies
    # leads whose reminder is unsent or predates the current follow-up time, so
    # rescheduling re-arms a reminder and a due lead is never notified twice.
    follow_up_reminded_at = db.Column(db.DateTime, nullable=True)

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
        # Backs the follow-up dashboard filters (overdue/today/upcoming), which
        # all range-scan this column; NULLs serve the "No Follow-up" filter.
        db.Index("ix_leads_next_follow_up_at", "next_follow_up_at"),
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

    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body = db.Column(db.Text, nullable=False)

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

    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Machine-readable kind, e.g. "created", "status_changed", "note_added".
    event_type = db.Column(db.String(50), nullable=False)
    # Human-readable summary rendered in the lead detail timeline.
    description = db.Column(db.String(512), nullable=False)
    # The status the lead moved TO on events that change its status (set by
    # lead_service on both the dedicated status change and the edit form).
    # NULL for non-status events (created, note_added, follow-up changes). This
    # is the structured, rename-proof source the reports read to reconstruct
    # when a lead was first contacted and how far it progressed — as opposed to
    # parsing it out of the free-text `description`. Indexed with created_at so
    # the "first contact per lead" scan the report runs stays cheap.
    to_status = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.Index("ix_timeline_events_to_status_created_at", "to_status", "created_at"),
    )

    lead = db.relationship("Lead", back_populates="timeline")
    actor = db.relationship("User")

    def __repr__(self) -> str:
        return f"<TimelineEvent {self.event_type} lead={self.lead_id}>"
