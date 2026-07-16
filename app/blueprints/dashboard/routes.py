"""Dashboard routes: overview, lead listing, lead detail, and lead actions.

Every route here is login-protected. Routes stay thin: they read query
params / form data, delegate to the service layer, and render or redirect.
All writes go through lead_service so timeline events stay consistent.
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.constants import LEAD_STATUSES
from app.services import dashboard_service, lead_service
from app.services.lead_service import LeadValidationError

from .forms import NoteForm, StatusForm

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def index():
    """Dashboard home: summary cards + a handful of recent leads."""
    return render_template(
        "dashboard/index.html",
        metrics=dashboard_service.get_metrics(),
        recent=dashboard_service.recent_leads(limit=8),
    )


@dashboard_bp.route("/leads")
@login_required
def leads():
    """Paginated, searchable, status-filterable lead list (newest first)."""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", type=str)
    status = request.args.get("status", type=str)

    pagination = dashboard_service.list_leads(
        page=page, search=search, status=status
    )
    return render_template(
        "dashboard/leads.html",
        pagination=pagination,
        leads=pagination.items,
        statuses=LEAD_STATUSES,
        search=search or "",
        active_status=status or "",
    )


@dashboard_bp.route("/leads/<int:lead_id>")
@login_required
def lead_detail(lead_id: int):
    """Full lead record: personal info, tracking, timeline, notes, status."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    return render_template(
        "dashboard/lead_detail.html",
        lead=lead,
        status_form=StatusForm(status=lead.status),
        note_form=NoteForm(),
    )


@dashboard_bp.route("/leads/<int:lead_id>/status", methods=["POST"])
@login_required
def update_status(lead_id: int):
    """Change a lead's status via LeadService."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    form = StatusForm()
    if form.validate_on_submit():
        try:
            lead_service.change_status(
                lead, form.status.data, actor_id=_current_user_id()
            )
            flash(f"Status updated to “{form.status.data}”.", "success")
        except LeadValidationError as exc:
            flash("; ".join(exc.errors.values()), "error")
    else:
        flash("Could not update status. Please try again.", "error")

    return redirect(url_for("dashboard.lead_detail", lead_id=lead_id))


@dashboard_bp.route("/leads/<int:lead_id>/notes", methods=["POST"])
@login_required
def add_note(lead_id: int):
    """Attach a note to a lead via LeadService."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    form = NoteForm()
    if form.validate_on_submit():
        try:
            lead_service.add_note(
                lead, form.body.data, author_id=_current_user_id()
            )
            flash("Note added.", "success")
        except LeadValidationError as exc:
            flash("; ".join(exc.errors.values()), "error")
    else:
        flash("Note cannot be empty.", "error")

    return redirect(url_for("dashboard.lead_detail", lead_id=lead_id))


@dashboard_bp.route("/leads/<int:lead_id>/delete", methods=["POST"])
@login_required
def delete_lead(lead_id: int):
    """Delete a lead (and its notes/timeline via cascade)."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    lead_service.delete_lead(lead)
    flash("Lead deleted.", "success")
    return redirect(url_for("dashboard.leads"))


def _current_user_id():
    """Best-effort id of the logged-in admin for timeline attribution."""
    from flask_login import current_user

    return getattr(current_user, "id", None)
