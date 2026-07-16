"""Public routes: the landing page and the admission form submission.

Routes stay thin — they parse the request, hand off to LeadService, and
render or redirect. All lead business logic lives in the service layer.
"""
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.blueprints.public.forms import AdmissionForm
from app.services import lead_service
from app.services.lead_service import LeadValidationError
from app.services.meta_service import get_courses
from app.utils.tracking import extract_tracking

public_bp = Blueprint("public", __name__)


@public_bp.route("/", methods=["GET"])
def index():
    """Render the landing page with an empty admission form."""
    form = AdmissionForm()
    return render_template("public/index.html", form=form, courses=get_courses())


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
                    "message": form.message.data,
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
    return render_template(
        "public/index.html", form=form, courses=get_courses()
    ), 400
