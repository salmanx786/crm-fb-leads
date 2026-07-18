"""Public routes: the landing page and the admission form submission.

Routes stay thin — they parse the request, hand off to LeadService, and
render or redirect. All lead business logic lives in the service layer.
"""
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.blueprints.public.forms import AdmissionForm
from app.services import content_service, lead_service
from app.services.lead_service import LeadValidationError
from app.services.reference_service import get_courses
from app.utils.tracking import extract_tracking

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
    """Render the landing page with an empty admission form."""
    form = AdmissionForm()
    return _render_landing(form)


@public_bp.route("/admission", methods=["POST"])
def submit_admission():
    """Handle an admission enquiry submission.

    On success: persist via LeadService (which records the "created" timeline
    event), flash a confirmation, and redirect back to the landing page.
    On failure: re-render the page with field errors.
    """
    form = AdmissionForm()

    if form.validate_on_submit():
        try:
            lead_service.create_lead(
                data={
                    "name": form.name.data,
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
                tracking=extract_tracking(request),
            )
        except LeadValidationError as exc:
            # Surface service-level validation on the matching form fields.
            for field_name, message in exc.errors.items():
                field = getattr(form, field_name, None)
                if field is not None:
                    field.errors.append(message)
        else:
            flash(
                "Thank you! Your enquiry has been received. "
                "Our admissions team will contact you shortly.",
                "success",
            )
            return redirect(url_for("public.index", _anchor="admission"))

    # Either WTForms validation failed or the service rejected the data.
    return _render_landing(form, status_code=400)
