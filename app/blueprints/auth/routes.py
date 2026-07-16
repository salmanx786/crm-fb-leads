"""Authentication routes: login and logout.

Routes stay thin — they validate the form, look the user up, and delegate
password checking to the User model. Session handling is Flask-Login's job.
"""
from urllib.parse import urlparse

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth.forms import LoginForm
from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__)


def _is_safe_next(target: str) -> bool:
    """Only allow same-host relative redirects, to prevent open redirects."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Already signed in? Skip straight to the dashboard.
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.query(User).filter_by(email=form.email.data.lower().strip()).first()

        # Same generic error for unknown email or wrong password — don't leak
        # which accounts exist.
        if user is None or not user.check_password(form.password.data):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", form=form), 401

        if not user.is_active:
            flash("This account is disabled.", "error")
            return render_template("auth/login.html", form=form), 403

        login_user(user, remember=form.remember.data)

        next_page = request.args.get("next")
        if not _is_safe_next(next_page):
            next_page = url_for("dashboard.index")
        return redirect(next_page)

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
