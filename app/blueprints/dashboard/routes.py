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

from .forms import FollowUpForm, NoteForm, StatusForm

# Follow-up filter options surfaced as toggle links on the leads list.
# (value, label) — value matches dashboard_service.list_leads(follow_up=...).
FOLLOW_UP_FILTERS = [
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("upcoming", "Upcoming"),
    ("no_follow_up", "No Follow-up"),
]

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
    period = request.args.get("period", type=str)
    follow_up = request.args.get("follow_up", type=str)

    pagination = dashboard_service.list_leads(
        page=page, search=search, status=status, period=period, follow_up=follow_up
    )
    return render_template(
        "dashboard/leads.html",
        pagination=pagination,
        leads=pagination.items,
        duplicate_counts=dashboard_service.duplicate_counts(pagination.items),
        follow_up_state=dashboard_service.follow_up_state,
        statuses=LEAD_STATUSES,
        follow_up_filters=FOLLOW_UP_FILTERS,
        search=search or "",
        active_status=status or "",
        active_period=period or "",
        active_follow_up=follow_up or "",
    )


@dashboard_bp.route("/leads/<int:lead_id>/duplicates")
@login_required
def lead_duplicates(lead_id: int):
    """List every submission sharing this lead's phone or email."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    return render_template(
        "dashboard/lead_duplicates.html",
        lead=lead,
        submissions=dashboard_service.matching_submissions(lead),
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
        follow_up_form=FollowUpForm(next_follow_up_at=lead.next_follow_up_at),
        follow_up_state=dashboard_service.follow_up_state,
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


@dashboard_bp.route("/leads/<int:lead_id>/follow-up", methods=["POST"])
@login_required
def set_follow_up(lead_id: int):
    """Schedule or reschedule a lead's follow-up date via LeadService."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    form = FollowUpForm()
    if form.validate_on_submit():
        try:
            lead_service.set_follow_up(
                lead, form.next_follow_up_at.data, actor_id=_current_user_id()
            )
            flash("Follow-up saved.", "success")
        except LeadValidationError as exc:
            flash("; ".join(exc.errors.values()), "error")
    else:
        flash("Please choose a valid follow-up date and time.", "error")

    return redirect(url_for("dashboard.lead_detail", lead_id=lead_id))


@dashboard_bp.route("/leads/<int:lead_id>/follow-up/clear", methods=["POST"])
@login_required
def clear_follow_up(lead_id: int):
    """Remove a lead's follow-up date via LeadService."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    lead_service.clear_follow_up(lead, actor_id=_current_user_id())
    flash("Follow-up cleared.", "success")
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
