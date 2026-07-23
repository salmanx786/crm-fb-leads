"""Web Push subscription for a logged-in admin's browser/device.

Each row is one browser Push subscription (the object the browser's
``PushManager.subscribe`` returns) belonging to a ``User``. An admin can have
several — one per browser/device they enable notifications on. Rows are created
when an admin opts in from the dashboard and removed when they unsubscribe or
when the push service reports the endpoint is gone (404/410).

No secrets live here: ``p256dh``/``auth`` are the browser-generated client keys
used to encrypt a push payload *to* that browser, not credentials of ours.
"""
from app.extensions import db
from app.models.base import BaseModel


class PushSubscription(BaseModel):
    """One browser Web Push subscription owned by an admin user."""

    __tablename__ = "push_subscriptions"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The push service URL the browser gave us. Unique so re-subscribing the
    # same browser updates the existing row instead of duplicating it. Endpoints
    # can be long; 500 chars covers FCM/Mozilla/WNS in practice.
    endpoint = db.Column(db.String(500), nullable=False, unique=True)
    # Browser-generated keys used to encrypt the push payload to this client.
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    # Best-effort device label for a future "your devices" list. Optional.
    user_agent = db.Column(db.String(512), nullable=True)

    user = db.relationship("User")

    def __repr__(self) -> str:
        return f"<PushSubscription user={self.user_id} id={self.id}>"
