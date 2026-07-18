"""Landing-page content management (the admin media CMS).

This is the single source of truth for every editable slot on the public
page. The `SECTIONS`/`SLOTS` registry drives three things at once so they can
never drift apart:

  1. the dashboard UI (which slots render, in which section, with what label);
  2. the public page (what value/asset each slot resolves to); and
  3. the fallback behaviour when a slot is empty (required / placeholder /
     hide-section), per the addendum.

Media files are written under `static/uploads/<slot>/` and only their
static-relative path is stored in the DB. Text/URL slots store their value
directly. Reads are collected into one `get_public_content()` dict the public
route hands to the template, so the template never queries the DB itself.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Optional

from flask import current_app, url_for
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import FaqItem, GalleryItem, SiteContent

# ---------------------------------------------------------------------------
# Fallback rules (addendum §3)
# ---------------------------------------------------------------------------
REQUIRED = "required"        # page cannot go live without it; no fallback
PLACEHOLDER = "placeholder"  # show branded placeholder until real upload
HIDE = "hide"                # hide the whole section when empty

# Slot "kinds" — determines the upload/validation + how the value is stored.
KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_TEXT = "text"
KIND_URL = "url"

# Allowed upload extensions per kind. Kept deliberately tight.
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "svg", "gif"}
ALLOWED_VIDEO_EXTS = {"mp4", "webm", "mov", "m4v"}

# Branded placeholder assets (committed to the repo under static/img/placeholders/).
# Used for PLACEHOLDER-rule slots that have no upload yet.
PLACEHOLDER_IMAGE = "img/placeholders/branded-placeholder.svg"


@dataclass(frozen=True)
class Slot:
    """One editable slot in the CMS registry."""

    key: str
    label: str
    kind: str
    fallback: str
    default: Optional[str] = None   # default value for text/url slots
    help_text: str = ""


@dataclass
class Section:
    """A dashboard section grouping related slots (mirrors the page order)."""

    key: str
    title: str
    slots: list = field(default_factory=list)
    # Section-level behaviour flags used by the public page.
    hide_when_empty: bool = False


# ---------------------------------------------------------------------------
# The registry — dashboard sections, in page (top-to-bottom) order.
# ---------------------------------------------------------------------------
SECTIONS: list[Section] = [
    Section("logos", "Logos", [
        Slot("logo_mc", "MC College Logo", KIND_IMAGE, REQUIRED,
             help_text="Required before the page can go live."),
        Slot("logo_jsmu", "JSMU Logo", KIND_IMAGE, REQUIRED,
             help_text="Required before the page can go live."),
    ]),
    Section("hero", "Hero", [
        Slot("hero_headline", "Hero Headline", KIND_TEXT, PLACEHOLDER,
             default="Apply for DPT or BSMT — Affordable, HEC Recognized.",
             help_text="Shown at the top of the page. Never blank."),
    ]),
    Section("video", "Principal's Video", [
        Slot("principal_video", "Principal's Video", KIND_VIDEO, HIDE,
             help_text="If empty, the whole video section is hidden."),
        Slot("principal_video_poster", "Principal's Video — Poster Image",
             KIND_IMAGE, PLACEHOLDER,
             help_text="Auto-generated from the first frame if left empty."),
    ], hide_when_empty=True),
    Section("recognition", "Recognition / Proof", [
        Slot("jsmu_dpt_url", "JSMU — Verify DPT URL", KIND_URL, PLACEHOLDER,
             default="https://www.jsmu.edu.pk/affilated-dpt-program.html"),
        Slot("jsmu_bsmt_url", "JSMU — Verify BSMT URL", KIND_URL, PLACEHOLDER,
             default="https://www.jsmu.edu.pk/affilated-bsmt-program.html"),
    ]),
    Section("programs", "Programs", [
        Slot("program_dpt_img", "DPT — Card Image", KIND_IMAGE, PLACEHOLDER),
        Slot("program_bsmt_cls_img",
             "BSMT — Clinical Laboratory Sciences — Card Image",
             KIND_IMAGE, PLACEHOLDER),
        Slot("program_bsmt_ri_img",
             "BSMT — Radiological Imaging — Card Image",
             KIND_IMAGE, PLACEHOLDER),
    ]),
    Section("why_us", "Why Choose Us / Affordability", [
        Slot("why_1_img", "Affordable Fees — Icon/Photo", KIND_IMAGE, PLACEHOLDER),
        Slot("why_2_img", "Foundation Support — Icon/Photo", KIND_IMAGE, PLACEHOLDER),
        Slot("why_3_img", "HEC-Recognized Degree — Icon/Photo", KIND_IMAGE, PLACEHOLDER),
        Slot("why_4_img", "Faculty & Facilities — Icon/Photo", KIND_IMAGE, PLACEHOLDER),
    ]),
    Section("gallery", "Gallery", [], hide_when_empty=True),  # repeatable; see GalleryItem
    Section("faq", "FAQ", []),  # repeatable; see FaqItem
]

# Flat lookup: slot key -> Slot.
SLOTS: dict[str, Slot] = {
    slot.key: slot for section in SECTIONS for slot in section.slots
}

# Default FAQ content (addendum §3) — seeded on first setup, editable after.
DEFAULT_FAQS: list[tuple[str, str]] = [
    ("Who is eligible to apply?",
     "For DPT and BSMT you generally need Intermediate (Pre-Medical preferred). "
     "Submit your marks in the form and our team will confirm your eligibility."),
    ("How affordable is it really?",
     "Fees are kept low, and eligible students can receive support through the "
     "Mother & Child Foundation. Our team will walk you through the exact fee structure."),
    ("Is the degree HEC recognized?",
     "Yes. Programs are offered under affiliation with Jinnah Sindh Medical "
     "University (JSMU); you can verify this on JSMU's official site linked above."),
    ("How long are the programs?",
     "DPT is 5 years. BSMT (both specializations) is 4 years."),
    ("Is financial support available?",
     "Yes — support through the Mother & Child Foundation is available for "
     "deserving students. Ask our team about how to qualify."),
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ContentError(Exception):
    """Raised on invalid upload / unknown slot. Message is user-safe."""


# ---------------------------------------------------------------------------
# Low-level slot value access
# ---------------------------------------------------------------------------
def _row(key: str) -> Optional[SiteContent]:
    return db.session.scalar(db.select(SiteContent).filter_by(key=key))


def get_raw(key: str) -> Optional[str]:
    """The stored value for a slot, or None if never set."""
    row = _row(key)
    return row.value if row else None


def set_value(key: str, value: Optional[str]) -> None:
    """Upsert a slot's stored value (text/url or a file path)."""
    row = _row(key)
    if row is None:
        row = SiteContent(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------
def _upload_root() -> str:
    """Absolute path to static/uploads, created on demand."""
    root = os.path.join(current_app.static_folder, "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def _ext_ok(filename: str, kind: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = ALLOWED_IMAGE_EXTS if kind == KIND_IMAGE else ALLOWED_VIDEO_EXTS
    return ext in allowed


def save_upload(subdir: str, file_storage, kind: str) -> str:
    """Persist an uploaded file under static/uploads/<subdir>/ and return its
    static-relative path (e.g. "uploads/logos/ab12cd.png").

    Raises ContentError for a missing file or a disallowed extension.
    """
    if file_storage is None or not file_storage.filename:
        raise ContentError("Please choose a file to upload.")
    filename = secure_filename(file_storage.filename)
    if not _ext_ok(filename, kind):
        allowed = ALLOWED_IMAGE_EXTS if kind == KIND_IMAGE else ALLOWED_VIDEO_EXTS
        raise ContentError(
            f"Unsupported file type. Allowed: {', '.join(sorted(allowed))}."
        )
    ext = filename.rsplit(".", 1)[-1].lower()
    # Random name avoids collisions and stops one upload overwriting another.
    stored_name = f"{secrets.token_hex(8)}.{ext}"
    dest_dir = os.path.join(_upload_root(), subdir)
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, stored_name))
    return f"uploads/{subdir}/{stored_name}"


def _delete_static_file(rel_path: Optional[str]) -> None:
    """Remove a previously-uploaded file. Only touches paths under uploads/."""
    if not rel_path or not rel_path.startswith("uploads/"):
        return
    abs_path = os.path.join(current_app.static_folder, rel_path)
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except OSError:
        # A missing/again-removed file is not an error worth surfacing.
        pass


def set_media_slot(key: str, file_storage) -> None:
    """Upload a new file for a media slot, replacing any previous file."""
    slot = SLOTS.get(key)
    if slot is None or slot.kind not in (KIND_IMAGE, KIND_VIDEO):
        raise ContentError("Unknown media slot.")
    new_path = save_upload(slot.key, file_storage, slot.kind)
    old_path = get_raw(key)
    set_value(key, new_path)
    if old_path and old_path != new_path:
        _delete_static_file(old_path)


def clear_slot(key: str) -> None:
    """Remove a slot's value (and its file, for media slots)."""
    slot = SLOTS.get(key)
    old_path = get_raw(key)
    set_value(key, None)
    if slot and slot.kind in (KIND_IMAGE, KIND_VIDEO):
        _delete_static_file(old_path)


# ---------------------------------------------------------------------------
# Public-page resolution (applies fallback rules)
# ---------------------------------------------------------------------------
def _resolved_url(rel_path: Optional[str]) -> Optional[str]:
    """Static URL for a stored asset path, or None."""
    return url_for("static", filename=rel_path) if rel_path else None


def resolve_slot(key: str) -> Optional[str]:
    """The value the public page should use for a slot, after fallbacks.

    - text/url: stored value, else the slot default.
    - image: static URL of the upload, else the branded placeholder for
      PLACEHOLDER slots, else None (REQUIRED/HIDE with no upload).
    - video: static URL of the upload, else None (section is hidden).
    """
    slot = SLOTS[key]
    raw = get_raw(key)
    if slot.kind in (KIND_TEXT, KIND_URL):
        return raw if raw else slot.default
    if slot.kind == KIND_IMAGE:
        if raw:
            return _resolved_url(raw)
        if slot.fallback == PLACEHOLDER:
            return _resolved_url(PLACEHOLDER_IMAGE)
        return None
    if slot.kind == KIND_VIDEO:
        return _resolved_url(raw) if raw else None
    return None


def gallery_items() -> list[GalleryItem]:
    """All gallery items, in display order."""
    return list(
        db.session.scalars(
            db.select(GalleryItem).order_by(
                GalleryItem.sort_order, GalleryItem.id
            )
        )
    )


def faq_items() -> list[FaqItem]:
    """All FAQ items, in display order."""
    return list(
        db.session.scalars(
            db.select(FaqItem).order_by(FaqItem.sort_order, FaqItem.id)
        )
    )


def get_public_content() -> dict:
    """Everything the public template needs, with fallbacks already applied.

    Returns a dict with resolved slot values plus gallery/FAQ lists and the
    section-visibility flags the template uses to hide empty sections.
    """
    resolved = {key: resolve_slot(key) for key in SLOTS}
    gallery = gallery_items()
    return {
        "c": resolved,
        "gallery": gallery,
        "faqs": faq_items(),
        # Section visibility (addendum §3 hide-when-empty rules).
        "show_video": bool(resolved.get("principal_video")),
        "show_gallery": len(gallery) > 0,
        # For the video: a poster is guaranteed (placeholder) but may be the
        # branded one; the template still autoplays muted with captions.
    }


# ---------------------------------------------------------------------------
# Gallery operations
# ---------------------------------------------------------------------------
def add_gallery_item(file_storage, poster_storage=None, caption: str = "") -> GalleryItem:
    """Add a gallery photo or short video.

    Media type is inferred from the file extension. For videos an optional
    poster image (captured client-side) may be supplied.
    """
    if file_storage is None or not file_storage.filename:
        raise ContentError("Please choose a file to upload.")
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED_IMAGE_EXTS:
        media_type = "image"
    elif ext in ALLOWED_VIDEO_EXTS:
        media_type = "video"
    else:
        raise ContentError("Unsupported file type for the gallery.")

    path = save_upload("gallery", file_storage, media_type)
    poster_path = None
    if media_type == "video" and poster_storage and poster_storage.filename:
        poster_path = save_upload("gallery", poster_storage, KIND_IMAGE)

    # New items append to the end.
    next_order = (
        db.session.scalar(db.select(db.func.max(GalleryItem.sort_order))) or 0
    ) + 1
    item = GalleryItem(
        file_path=path,
        media_type=media_type,
        poster_path=poster_path,
        caption=caption.strip() or None,
        sort_order=next_order,
    )
    db.session.add(item)
    db.session.commit()
    return item


def delete_gallery_item(item_id: int) -> None:
    """Remove a gallery item and its files."""
    item = db.session.get(GalleryItem, item_id)
    if item is None:
        return
    _delete_static_file(item.file_path)
    _delete_static_file(item.poster_path)
    db.session.delete(item)
    db.session.commit()


# ---------------------------------------------------------------------------
# FAQ operations
# ---------------------------------------------------------------------------
def add_faq(question: str, answer: str) -> FaqItem:
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise ContentError("Both a question and an answer are required.")
    next_order = (
        db.session.scalar(db.select(db.func.max(FaqItem.sort_order))) or 0
    ) + 1
    item = FaqItem(question=question, answer=answer, sort_order=next_order)
    db.session.add(item)
    db.session.commit()
    return item


def update_faq(item_id: int, question: str, answer: str) -> None:
    item = db.session.get(FaqItem, item_id)
    if item is None:
        raise ContentError("FAQ item not found.")
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise ContentError("Both a question and an answer are required.")
    item.question, item.answer = question, answer
    db.session.commit()


def delete_faq(item_id: int) -> None:
    item = db.session.get(FaqItem, item_id)
    if item is None:
        return
    db.session.delete(item)
    db.session.commit()


# ---------------------------------------------------------------------------
# Launch-readiness (addendum §3 "required at setup")
# ---------------------------------------------------------------------------
def missing_required_slots() -> list[Slot]:
    """REQUIRED slots that have no value yet — the page can't go live until
    these are filled. Used to warn the admin and (optionally) gate the page.
    """
    return [
        slot for slot in SLOTS.values()
        if slot.fallback == REQUIRED and not get_raw(slot.key)
    ]


def seed_defaults() -> None:
    """Seed default FAQ content on first run if none exists. Idempotent."""
    if db.session.scalar(db.select(db.func.count(FaqItem.id))) == 0:
        for order, (q, a) in enumerate(DEFAULT_FAQS, start=1):
            db.session.add(FaqItem(question=q, answer=a, sort_order=order))
        db.session.commit()
