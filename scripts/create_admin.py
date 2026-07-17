"""Create the first administrator account (non-interactive).

For cPanel's "Execute python script" field, which cannot answer the interactive
prompts that `flask create-admin` uses. Reads the admin details from environment
variables so no password is passed on a command line (which would be logged):

    ADMIN_NAME, ADMIN_EMAIL, ADMIN_PASSWORD

Set these as Environment variables in the Python App panel, run this script once,
then remove ADMIN_PASSWORD. Re-running is safe: a duplicate email is reported and
no second admin is created.
"""
import os
import sys

# Running a script puts scripts/ on sys.path, not the project root, so the
# `app` package would not import. Add the project root explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services import user_service
from app.services.user_service import UserAlreadyExistsError

app = create_app()

name = os.environ.get("ADMIN_NAME", "").strip()
email = os.environ.get("ADMIN_EMAIL", "").strip()
password = os.environ.get("ADMIN_PASSWORD", "")

if not (name and email and password):
    raise SystemExit(
        "Set ADMIN_NAME, ADMIN_EMAIL and ADMIN_PASSWORD environment variables "
        "before running this script."
    )

with app.app_context():
    try:
        user = user_service.create_admin(name=name, email=email, password=password)
    except UserAlreadyExistsError as exc:
        print(str(exc))
    else:
        print(f"Admin created: {user.name} <{user.email}>")
