"""Management CLI.

Run with `flask --app manage <command>` or `python manage.py <command>`.
Provides helpers for local development and first-time setup on the host.
"""
import click

from app import create_app
from app.extensions import db

app = create_app()


@app.cli.command("init-db")
def init_db() -> None:
    """Create all tables directly (quick local bootstrap without migrations)."""
    with app.app_context():
        db.create_all()
    click.echo("Database tables created.")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
