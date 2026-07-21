"""Create all database tables (non-interactive).

For cPanel's "Execute python script" field, which runs scripts without a TTY.
Point that field at scripts/init_db.py. Equivalent to `flask --app manage init-db`
but usable where interactive commands and the manage.py web server are not.
"""
import os
import sys

# Running a script puts scripts/ on sys.path, not the project root, so the
# `app` package would not import. Add the project root (this file's parent's
# parent) explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.services import content_service, status_service

app = create_app()
with app.app_context():
    db.create_all()
    print("Database tables created.")
    # Seed default editable content (FAQ) so the CMS isn't empty on first run.
    # Idempotent: a no-op once content exists, so re-running is safe.
    content_service.seed_defaults()
    # Seed the editable lead statuses from the legacy constants on first run.
    # Idempotent: a no-op once any status exists, so re-running is safe.
    seeded = status_service.seed_defaults()
    if seeded:
        print(f"Seeded {seeded} default lead statuses.")
