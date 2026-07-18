"""Editable landing-page content, managed from the admin dashboard.

Three tables back the media-management CMS so an admin can change every
piece of media/text on the public page without a developer editing code:

- `SiteContent` — a key/value store for the fixed, single-value slots
  (logos, hero headline, principal video + poster, JSMU verify URLs, the
  program-card images, the why-us icons). One row per slot key; `value`
  holds either an uploaded file's relative path or a text value depending
  on the slot's kind (see app.services.content_service.SLOTS).
- `GalleryItem` — the open-ended gallery (0..N images/short videos).
- `FaqItem`     — the editable question/answer list.

Nothing here stores absolute paths or secrets: uploaded assets live under
`static/uploads/…` and only their static-relative path is persisted.
"""
from app.extensions import db
from app.models.base import BaseModel


class SiteContent(BaseModel):
    """One editable single-value slot on the landing page.

    `key` matches a slot id in content_service.SLOTS. `value` is the stored
    text (for text slots) or the static-relative file path (for media slots),
    or NULL when the slot has never been set — in which case the public page
    applies that slot's fallback rule (required / placeholder / hide).
    """

    __tablename__ = "site_content"

    key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    value = db.Column(db.String(512), nullable=True)


class GalleryItem(BaseModel):
    """A single gallery photo or short video, uploaded via the dashboard.

    The gallery section on the public page is hidden entirely when no items
    exist and reappears automatically once at least one is added.
    """

    __tablename__ = "gallery_items"

    # Static-relative path to the uploaded file.
    file_path = db.Column(db.String(512), nullable=False)
    # "image" or "video" — drives whether the page renders <img> or <video>.
    media_type = db.Column(db.String(16), nullable=False, default="image")
    # Poster for video items (auto-captured client-side at upload). Null for images.
    poster_path = db.Column(db.String(512), nullable=True)
    # Optional caption / alt text.
    caption = db.Column(db.String(255), nullable=True)
    # Manual ordering on the page (ascending). Ties break on id.
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)


class FaqItem(BaseModel):
    """One editable FAQ question/answer pair."""

    __tablename__ = "faq_items"

    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)
