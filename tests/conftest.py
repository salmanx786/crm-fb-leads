"""Shared pytest fixtures.

Builds an app on the testing config (in-memory SQLite, CSRF enabled so the
tests exercise the real token flow) and creates the schema fresh per test.
"""
import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        # Seed the editable lead statuses, mirroring production (init_db seeds
        # them). Status validation and dropdowns are now DB-backed, so tests run
        # against the same seeded lifecycle a real deployment has.
        from app.services import status_service

        status_service.seed_defaults()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    """Expose the SQLAlchemy handle inside the app context."""
    return _db
