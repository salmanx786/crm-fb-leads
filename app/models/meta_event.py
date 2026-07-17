from app.extensions import db
from app.models.base import BaseModel


class MetaEvent(BaseModel):
    """One Meta Conversions API send attempt for a lead.

    Every attempt is persisted so a failed send is never lost: rows start as
    ``pending``, become ``sent`` on a 2xx response, or ``failed`` otherwise.
    ``retry_failed_events`` re-sends only the ``failed`` rows, reusing
    ``event_id`` so Meta deduplicates against any partial success.
    """

    __tablename__ = "meta_events"

    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    # CRM-side event name, e.g. "Lead", "Interested" (the Meta event_name).
    event_name = db.Column(db.String(64), nullable=False)
    # Idempotency key sent to Meta; reused on retry so events dedupe.
    event_id = db.Column(db.String(64), nullable=False)
    # pending | sent | failed
    status = db.Column(db.String(16), default="pending", nullable=False)
    # JSON strings of what we sent and what came back (never contains raw PII;
    # user data is SHA-256 hashed before the payload is built).
    request_payload = db.Column(db.Text, nullable=True)
    response_payload = db.Column(db.Text, nullable=True)
    # When Meta accepted the event (set on success only).
    sent_at = db.Column(db.DateTime, nullable=True)

    # Note: created_at is already indexed by BaseModel (ix_meta_events_created_at),
    # so the milestone's created_at index requirement is covered there.
    __table_args__ = (
        db.Index("ix_meta_events_status", "status"),
        db.Index("ix_meta_events_lead_id", "lead_id"),
    )

    lead = db.relationship("Lead")

    def __repr__(self) -> str:
        return f"<MetaEvent {self.event_name} lead={self.lead_id} {self.status}>"
