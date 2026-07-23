"""Dashboard routes: overview, lead listing, lead detail, and lead actions.

Every route here is login-protected. Routes stay thin: they read query
params / form data, delegate to the service layer, and render or redirect.
All writes go through lead_service so timeline events stay consistent.
"""
import csv
import io

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import login_required

from app.services import dashboard_service, lead_service, reference_service
from app.services.lead_service import LeadValidationError

from .forms import (
    BulkActionForm,
    FollowUpForm,
    LeadEditForm,
    MailSettingsForm,
    MetaSettingsForm,
    NoteForm,
    PushSettingsForm,
    StatusForm,
)

# Follow-up filter options surfaced as toggle links on the leads list.
# (value, label) — value matches dashboard_service.list_leads(follow_up=...).
FOLLOW_UP_FILTERS = [
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("upcoming", "Upcoming"),
    ("no_follow_up", "No Follow-up"),
]

# CSV export column headers, in order. Maps 1:1 to _lead_csv_row below.
# Deliberately excludes timeline, notes, meta events, and audit fields.
EXPORT_COLUMNS = [
    "ID",
    "Created At",
    "Name",
    "First Name",
    "Last Name",
    "Phone",
    "Email",
    "City",
    "Program",
    "Specialization",
    "Guardian Name",
    "Guardian Phone",
    "Address",
    "Matric Board",
    "Matric Marks",
    "Inter Board",
    "Inter Marks",
    "Inter Type",
    "Status",
    "Source",
    "Next Follow-up",
    "Duplicate Count",
]


def _iso(value):
    """ISO-8601 datetime string, or empty for a missing value."""
    return value.isoformat() if value else ""


def _lead_csv_row(lead, duplicate_count):
    """Shape one Lead into an export row matching EXPORT_COLUMNS.

    Missing values render as empty cells; datetimes use ISO-8601. "Source"
    is the lead's utm_source (consistent with the edit form's labelling).
    """
    return [
        lead.id,
        _iso(lead.created_at),
        lead.name or "",
        lead.first_name or "",
        lead.last_name or "",
        lead.phone or "",
        lead.email or "",
        lead.city or "",
        lead.course or "",
        lead.specialization or "",
        lead.guardian_name or "",
        lead.guardian_phone or "",
        lead.address or "",
        lead.matric_board or "",
        lead.matric_marks or "",
        lead.inter_board or "",
        lead.inter_marks or "",
        lead.inter_group or "",
        lead.status or "",
        lead.utm_source or "",
        _iso(lead.next_follow_up_at),
        duplicate_count,
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
        bulk_form=BulkActionForm(),
        statuses=reference_service.get_statuses(),
        follow_up_filters=FOLLOW_UP_FILTERS,
        search=search or "",
        active_status=status or "",
        active_period=period or "",
        active_follow_up=follow_up or "",
    )


@dashboard_bp.route("/leads/export.csv")
@login_required
def export_leads_csv():
    """Download the currently-filtered lead list as a UTF-8 CSV.

    Thin: reads the same query params as the list view, reuses
    dashboard_service.filtered_leads (identical filter SQL) plus the existing
    duplicate_counts, shapes rows, and returns the CSV. Loading the full
    filtered set into memory is acceptable for V1 (see spec).
    """
    search = request.args.get("q", type=str)
    status = request.args.get("status", type=str)
    period = request.args.get("period", type=str)
    follow_up = request.args.get("follow_up", type=str)

    leads = dashboard_service.filtered_leads(
        search=search, status=status, period=period, follow_up=follow_up
    )
    dup_counts = dashboard_service.duplicate_counts(leads)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for lead in leads:
        writer.writerow(_lead_csv_row(lead, dup_counts.get(lead.id, 1)))

    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
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


@dashboard_bp.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id: int):
    """Edit a lead. GET renders the prefilled form; POST delegates to LeadService."""
    lead = lead_service.get_lead(lead_id)
    if lead is None:
        abort(404)

    # obj=lead prefills every field (names match Lead attributes) on GET and on
    # a re-render after a validation error.
    form = LeadEditForm(obj=lead)
    if form.validate_on_submit():
        try:
            lead_service.update_lead(lead, form.data, actor_id=_current_user_id())
            flash("Lead updated.", "success")
            return redirect(url_for("dashboard.lead_detail", lead_id=lead_id))
        except LeadValidationError as exc:
            for message in exc.errors.values():
                flash(message, "error")

    return render_template("dashboard/lead_edit.html", lead=lead, form=form)


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


@dashboard_bp.route("/leads/bulk", methods=["POST"])
@login_required
def bulk_action():
    """Apply one action to the checked leads via LeadService.

    Thin: validate the form, read the checked ids, delegate to
    lead_service.bulk_action (which owns the single-transaction / rollback
    boundary), flash the outcome, and redirect back to the list.
    """
    form = BulkActionForm()
    # Checkbox ids are a dynamic list, so read them from the raw form.
    lead_ids = request.form.getlist("lead_ids", type=int)

    if form.validate_on_submit():
        try:
            count = lead_service.bulk_action(
                action=form.action.data,
                lead_ids=lead_ids,
                actor_id=_current_user_id(),
                status=form.status.data or None,
                when=form.next_follow_up_at.data,
            )
            flash(f"Bulk action applied to {count} lead(s).", "success")
        except LeadValidationError as exc:
            flash("; ".join(exc.errors.values()), "error")
    else:
        flash("Could not apply bulk action. Please try again.", "error")

    return redirect(url_for("dashboard.leads"))


@dashboard_bp.route("/settings/meta", methods=["GET", "POST"])
@login_required
def meta_settings():
    """View and save the Meta (Facebook) Conversions API settings.

    Thin: on GET, prefill the form from resolved settings (the access token is
    never prefilled — only whether one exists is shown). On POST, hand the raw
    form values to settings_service, which owns the "blank token keeps the
    stored one" rule and the transaction boundary.
    """
    from app.services import settings_service

    view = settings_service.meta_settings_view()
    form = MetaSettingsForm()

    if form.validate_on_submit():
        settings_service.save_meta_settings(
            {
                "enabled": form.enabled.data,
                "pixel_id": form.pixel_id.data,
                "access_token": form.access_token.data,
                "test_event_code": form.test_event_code.data,
                "default_country": form.default_country.data,
                "event_source_url": form.event_source_url.data,
            }
        )
        flash("Meta settings saved.", "success")
        return redirect(url_for("dashboard.meta_settings"))

    if request.method == "GET":
        # Prefill non-secret fields; the token field stays intentionally empty.
        form.enabled.data = view["enabled"]
        form.pixel_id.data = view["pixel_id"]
        form.test_event_code.data = view["test_event_code"]
        form.default_country.data = view["default_country"]
        form.event_source_url.data = view["event_source_url"]

    return render_template(
        "dashboard/settings_meta.html",
        form=form,
        has_access_token=view["has_access_token"],
    )


@dashboard_bp.route("/settings/statuses", methods=["GET"])
@login_required
def lead_statuses():
    """Manage the editable lead-status list and each status's Meta mapping.

    Read-only render here; every mutation is a small focused POST below that
    delegates to status_service and redirects back (Post/Redirect/Get), so a
    refresh never re-submits. All are login-gated and CSRF-protected.
    """
    from app.services import status_service

    return render_template(
        "dashboard/settings_statuses.html",
        statuses=status_service.get_status_rows(),
        meta_choices=status_service.META_EVENT_CHOICES,
        leads_using=status_service.leads_using,
    )


@dashboard_bp.route("/settings/statuses/add", methods=["POST"])
@login_required
def add_lead_status():
    """Create a new lead status with an optional Meta-event mapping."""
    from app.services import status_service
    from app.services.status_service import StatusError

    try:
        status_service.add_status(
            request.form.get("name", ""),
            request.form.get("meta_event") or None,
        )
        flash("Status added.", "success")
    except StatusError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard.lead_statuses"))


@dashboard_bp.route("/settings/statuses/<int:status_id>/rename", methods=["POST"])
@login_required
def rename_lead_status(status_id: int):
    """Rename a status; the change cascades to every lead using the old name."""
    from app.services import status_service
    from app.services.status_service import StatusError

    try:
        status_service.rename_status(status_id, request.form.get("name", ""))
        flash("Status renamed.", "success")
    except StatusError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard.lead_statuses"))


@dashboard_bp.route("/settings/statuses/<int:status_id>/meta", methods=["POST"])
@login_required
def set_lead_status_meta(status_id: int):
    """Change which Meta event a status reports (or clear it)."""
    from app.services import status_service
    from app.services.status_service import StatusError

    try:
        status_service.set_meta_event(status_id, request.form.get("meta_event") or None)
        flash("Meta mapping updated.", "success")
    except StatusError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard.lead_statuses"))


@dashboard_bp.route("/settings/statuses/<int:status_id>/delete", methods=["POST"])
@login_required
def delete_lead_status(status_id: int):
    """Delete a status (blocked while leads use it, or if it's the default)."""
    from app.services import status_service
    from app.services.status_service import StatusError

    try:
        status_service.delete_status(status_id)
        flash("Status deleted.", "success")
    except StatusError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard.lead_statuses"))


@dashboard_bp.route("/settings/notifications", methods=["GET", "POST"])
@login_required
def notification_settings():
    """View and save the Web Push (VAPID) settings.

    Thin: on GET, prefill non-secret fields (the private key is never
    prefilled — only whether one exists is shown). On POST, hand the raw form
    values to settings_service, which owns the "blank key keeps the stored one"
    rule and the transaction boundary. The template also needs the resolved
    public key + configured flag so the "enable on this browser" button works.
    """
    from app.services import push_service, settings_service

    view = settings_service.push_settings_view()
    form = PushSettingsForm()

    if form.validate_on_submit():
        settings_service.save_push_settings(
            {
                "enabled": form.enabled.data,
                "public_key": form.public_key.data,
                "private_key": form.private_key.data,
                "subject": form.subject.data,
            }
        )
        flash("Notification settings saved.", "success")
        return redirect(url_for("dashboard.notification_settings"))

    if request.method == "GET":
        # Prefill non-secret fields; the private-key field stays empty.
        form.enabled.data = view["enabled"]
        form.public_key.data = view["public_key"]
        form.subject.data = view["subject"]

    return render_template(
        "dashboard/settings_notifications.html",
        form=form,
        has_private_key=view["has_private_key"],
        push_public_key=push_service.public_key(),
        push_configured=push_service.is_configured(),
    )


@dashboard_bp.route("/settings/email", methods=["GET", "POST"])
@login_required
def mail_settings():
    """View and save the transactional email (SMTP) settings.

    Thin: on GET, prefill non-secret fields (the SMTP password is never
    prefilled — only whether one exists is shown). On POST, hand the raw form
    values to settings_service, which owns the "blank password keeps the stored
    one" rule and the transaction boundary.
    """
    from app.services import email_service, settings_service

    view = settings_service.mail_settings_view()
    form = MailSettingsForm()

    if form.validate_on_submit():
        settings_service.save_mail_settings(
            {
                "enabled": form.enabled.data,
                "smtp_host": form.smtp_host.data,
                "smtp_port": form.smtp_port.data,
                "username": form.username.data,
                "password": form.password.data,
                "from_address": form.from_address.data,
            }
        )
        flash("Email settings saved.", "success")
        return redirect(url_for("dashboard.mail_settings"))

    if request.method == "GET":
        # Prefill non-secret fields; the password field stays empty.
        form.enabled.data = view["enabled"]
        form.smtp_host.data = view["smtp_host"]
        form.smtp_port.data = int(view["smtp_port"]) if view["smtp_port"] else None
        form.username.data = view["username"]
        form.from_address.data = view["from_address"]

    return render_template(
        "dashboard/settings_email.html",
        form=form,
        has_password=view["has_password"],
        mail_configured=email_service.is_configured(),
    )


@dashboard_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    """Persist the browser Push subscription for the current admin.

    Called by push.js after the browser grants permission and creates a
    PushManager subscription. The CSRF token travels in the X-CSRFToken header
    (Flask-WTF reads it there), so the global CSRFProtect covers this endpoint
    without an exemption.
    """
    from app.services import push_service

    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription")
    try:
        push_service.save_subscription(
            _current_user_id(), subscription, request.user_agent.string
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})


@dashboard_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    """Remove the current admin's subscription (browser opt-out)."""
    from app.services import push_service

    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    removed = bool(endpoint) and push_service.delete_subscription(
        _current_user_id(), endpoint
    )
    return jsonify({"ok": True, "removed": removed})


@dashboard_bp.route("/sw.js")
def service_worker():
    """Serve the push service worker at /dashboard/sw.js.

    A service worker only controls pages at or below its own path, so serving
    it under the dashboard prefix scopes it to the admin area (where the only
    notification-consuming pages live). Not login-gated: the browser fetches it
    without the session cookie in some flows, and it contains no secrets.
    """
    import os

    return send_from_directory(
        os.path.join(current_app.static_folder, "js"),
        "sw.js",
        mimetype="application/javascript",
    )


def _current_user_id():
    """Best-effort id of the logged-in admin for timeline attribution."""
    from flask_login import current_user

    return getattr(current_user, "id", None)
