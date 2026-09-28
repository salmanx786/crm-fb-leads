"""Public routes: the landing page and the admission form submission.

Routes stay thin — they parse the request, hand off to LeadService, and
render or redirect. All lead business logic lives in the service layer.
"""
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from flask import session

import uuid

from app.blueprints.public.forms import AdmissionForm
from app.services import content_service, lead_service
from app.services.lead_service import LeadValidationError
from app.services.reference_service import evaluate_eligibility, get_courses
from app.utils.tracking import extract_tracking

# Session key holding the just-submitted applicant's confirmation payload,
# consumed once by the thank-you page (Post/Redirect/Get — no PII in the URL).
_CONFIRMATION_KEY = "admission_confirmation"
_ATTRIBUTION_KEY = "lead_attribution"

public_bp = Blueprint("public", __name__)


def _render_landing(form, status_code=200):
    """Render the landing page with the admission form and CMS content.

    Content (logos, hero, video, images, gallery, FAQ) is resolved through
    content_service with all fallback rules applied, so the template never
    renders a broken or empty slot.
    """
    content = content_service.get_public_content()
    return render_template(
        "public/index.html",
        form=form,
        courses=get_courses(),
        **content,
    ), status_code


@public_bp.route("/health", methods=["GET"])
def health():
    """Lightweight liveness probe for uptime monitors and load balancers.

    Deliberately unauthenticated and does no database or business work, so it
    stays fast and green even if the DB is unavailable — it reports that the
    app process is up, nothing more.
    """
    return jsonify(status="ok"), 200


@public_bp.route("/", methods=["GET"])
def index():
    """Render the landing page with an empty admission form.

    Captures and retains campaign attribution (UTMs and fbclid) in the user's
    session so that subsequent navigation or multi-step form actions preserve
    attribution on submission.
    """
    attr = session.get(_ATTRIBUTION_KEY) or {}
    for param in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"):
        val = request.args.get(param)
        if val:
            attr[param] = val.strip()
    if request.referrer and "referrer" not in attr:
        attr["referrer"] = request.referrer.strip()
    session[_ATTRIBUTION_KEY] = attr

    form = AdmissionForm()
    return _render_landing(form)


@public_bp.route("/privacy", methods=["GET"])
def privacy():
    """Render the Privacy Policy.

    Pulls the shared CMS content (logos, brand slots) so the page carries the
    same trust bar and footer branding as the landing page.
    """
    content = content_service.get_public_content()
    return render_template("public/privacy.html", **content)


@public_bp.route("/admission", methods=["POST"])
def submit_admission():
    """Handle an admission enquiry submission.

    On success: persist via LeadService (which records the "created" timeline
    event), flash a confirmation, and redirect back to the thank-you page.
    On failure: re-render the page with field errors.
    """
    form = AdmissionForm()

    if form.validate_on_submit():
        # Shared event_id used by both server CAPI and browser Meta Pixel
        # so Meta deduplicates them into a single verified conversion.
        lead_event_id = uuid.uuid4().hex
        session_attr = session.get(_ATTRIBUTION_KEY) or {}

        try:
            lead_service.create_lead(
                data={
                    "first_name": form.first_name.data,
                    "last_name": form.last_name.data,
                    "phone": form.phone.data,
                    "email": form.email.data,
                    "city": form.city.data,
                    "course": form.course.data,
                    "specialization": form.specialization.data,
                    "message": form.message.data,
                    "guardian_name": form.guardian_name.data,
                    "guardian_phone": form.guardian_phone.data,
                    "address": form.address.data,
                    "matric_board": form.matric_board.data,
                    "matric_marks": form.matric_marks.data,
                    "inter_board": form.inter_board.data,
                    "inter_marks": form.inter_marks.data,
                    "inter_group": form.inter_group.data,
                },
                tracking=extract_tracking(request, fallback=session_attr),
                event_id=lead_event_id,
            )
        except LeadValidationError as exc:
            # Surface service-level validation on the matching form fields.
            for field_name, message in exc.errors.items():
                field = getattr(form, field_name, None)
                if field is not None:
                    field.errors.append(message)
        else:
            # Stash confirmation payload for the thank-you page (Post/Redirect/Get)
            session[_CONFIRMATION_KEY] = {
                "first_name": (form.first_name.data or "").strip(),
                "course": form.course.data,
                "specialization": form.specialization.data,
                "inter_marks": form.inter_marks.data,
                "lead_event_id": lead_event_id,
            }
            return redirect(url_for("public.thank_you"))

    # Either WTForms validation failed or the service rejected the data.
    return _render_landing(form, status_code=400)


@public_bp.route("/thank-you", methods=["GET"])
def thank_you():
    """Post-submission confirmation page.

    Reads (and clears) the one-shot confirmation payload set by
    submit_admission. Reached directly with no prior submission, there's
    nothing to confirm, so redirect home rather than show an empty page.
    """
    confirmation = session.pop(_CONFIRMATION_KEY, None)
    if not confirmation:
        return redirect(url_for("public.index"))

    first_name = (confirmation.get("first_name") or "").strip()
    eligibility = evaluate_eligibility(
        confirmation.get("course"), confirmation.get("inter_marks")
    )

    content = content_service.get_public_content()
    response = make_response(
        render_template(
            "public/thank_you.html",
            first_name=first_name,
            course=confirmation.get("course"),
            specialization=confirmation.get("specialization"),
            eligibility=eligibility,
            lead_event_id=confirmation.get("lead_event_id"),
            **content,
        )
    )
    # Prevent browser caching of the thank-you page to avoid re-firing client-side tracking pixels on back/refresh
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

