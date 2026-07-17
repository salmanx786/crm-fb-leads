"""Create all database tables (non-interactive).

For cPanel's "Execute python script" field, which runs scripts without a TTY.
Point that field at scripts/init_db.py. Equivalent to `flask --app manage init-db`
but usable where interactive commands and the manage.py web server are not.
"""
from app import create_app
from app.extensions import db

app = create_app()
with app.app_context():
    db.create_all()
    print("Database tables created.")
