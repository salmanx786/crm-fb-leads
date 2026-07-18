"""Dashboard media-management (CMS) routes.

One page lists every editable slot, section-by-section, mirroring the public
page top-to-bottom. Writes are small, focused POST endpoints that delegate to
content_service and redirect back with a flash. All routes are login-gated.

CSRF: forms post a hidden `csrf_token` (WTForms/Flask-WTF global protection is
on), so these plain POST handlers are still protected.
"""
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.services import content_service
from app.services.content_service import ContentError

content_bp = Blueprint("content", __name__, url_prefix="/dashboard/content")


@content_bp.route("/")
@login_required
def index():
    """The media-management dashboard: all sections and slots."""
    return render_template(
        "dashboard/content.html",
        sections=content_service.SECTIONS,
        resolve=content_service.resolve_slot,
        raw=content_service.get_raw,
        gallery=content_service.gallery_items(),
        faqs=content_service.faq_items(),
        missing_required=content_service.missing_required_slots(),
    )


# --- Single-value slots (text / url / media) --------------------------------
@content_bp.route("/slot/<key>/text", methods=["POST"])
@login_required
def save_text_slot(key: str):
    """Save a text or URL slot (hero headline, JSMU verify URLs)."""
    if key not in content_service.SLOTS:
        flash("Unknown content slot.", "error")
        return redirect(url_for("content.index"))
    value = (request.form.get("value") or "").strip()
    slot = content_service.SLOTS[key]
    # Text/placeholder slots must never be blank on the page — keep the
    # default rather than storing an empty string.
    if not value:
        flash(f"{slot.label} can't be blank; the default will be used.", "warning")
        content_service.set_value(key, None)
    else:
        content_service.set_value(key, value)
        flash(f"{slot.label} updated.", "success")
    return redirect(url_for("content.index", _anchor=slot_section_anchor(key)))


@content_bp.route("/slot/<key>/media", methods=["POST"])
@login_required
def upload_media_slot(key: str):
    """Upload/replace a media slot (logos, program images, why-us icons,
    principal video + poster)."""
    if key not in content_service.SLOTS:
        flash("Unknown content slot.", "error")
        return redirect(url_for("content.index"))
    slot = content_service.SLOTS[key]
    try:
        content_service.set_media_slot(key, request.files.get("file"))
        # Principal video: if the client captured a first-frame poster and no
        # poster is set yet, auto-save it (addendum §3 "auto-generate thumbnail").
        if key == "principal_video":
            poster = request.files.get("poster")
            if poster and poster.filename and not content_service.get_raw(
                "principal_video_poster"
            ):
                content_service.set_media_slot("principal_video_poster", poster)
        flash(f"{slot.label} uploaded.", "success")
    except ContentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("content.index", _anchor=slot_section_anchor(key)))


@content_bp.route("/slot/<key>/clear", methods=["POST"])
@login_required
def clear_media_slot(key: str):
    """Remove a slot's value (reverts to placeholder/hidden per its rule)."""
    if key not in content_service.SLOTS:
        flash("Unknown content slot.", "error")
        return redirect(url_for("content.index"))
    slot = content_service.SLOTS[key]
    content_service.clear_slot(key)
    flash(f"{slot.label} removed.", "success")
    return redirect(url_for("content.index", _anchor=slot_section_anchor(key)))


# --- Gallery ----------------------------------------------------------------
@content_bp.route("/gallery/add", methods=["POST"])
@login_required
def add_gallery():
    """Add one gallery photo or short video."""
    try:
        content_service.add_gallery_item(
            request.files.get("file"),
            poster_storage=request.files.get("poster"),
            caption=request.form.get("caption", ""),
        )
        flash("Gallery item added.", "success")
    except ContentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("content.index", _anchor="gallery"))


@content_bp.route("/gallery/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_gallery(item_id: int):
    content_service.delete_gallery_item(item_id)
    flash("Gallery item removed.", "success")
    return redirect(url_for("content.index", _anchor="gallery"))


# --- FAQ --------------------------------------------------------------------
@content_bp.route("/faq/add", methods=["POST"])
@login_required
def add_faq():
    try:
        content_service.add_faq(
            request.form.get("question", ""), request.form.get("answer", "")
        )
        flash("FAQ added.", "success")
    except ContentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("content.index", _anchor="faq"))


@content_bp.route("/faq/<int:item_id>/update", methods=["POST"])
@login_required
def update_faq(item_id: int):
    try:
        content_service.update_faq(
            item_id,
            request.form.get("question", ""),
            request.form.get("answer", ""),
        )
        flash("FAQ updated.", "success")
    except ContentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("content.index", _anchor="faq"))


@content_bp.route("/faq/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_faq(item_id: int):
    content_service.delete_faq(item_id)
    flash("FAQ removed.", "success")
    return redirect(url_for("content.index", _anchor="faq"))


def slot_section_anchor(key: str) -> str:
    """The dashboard section id a slot belongs to (for scroll-back on save)."""
    for section in content_service.SECTIONS:
        if any(s.key == key for s in section.slots):
            return section.key
    return ""
