"""Application factory.

Creates and configures the Flask app, wires up extensions, and registers
blueprints. Keeping this in a factory lets tests and the WSGI entry point
build isolated app instances with different configs.
"""
from __future__ import annotations  # 3.9-safe PEP 604 unions in annotations

import os

from flask import Flask

from app.extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)

    # Resolve which config class to load (env var wins, else default).
    from config import config

    config_name = config_name or os.environ.get("FLASK_CONFIG", "default")
    config_class = config[config_name]
    app.config.from_object(config_class)
    # Let the config validate/adjust the app (e.g. ProductionConfig refuses to
    # start with an unsafe SECRET_KEY). No-op for dev/testing.
    config_class.init_app(app)

    _configure_logging(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_context_processors(app)
    _register_error_handlers(app)
    _register_cli(app)

    # Ensure models are imported so SQLAlchemy/Migrate see them.
    from app import models  # noqa: F401

    return app


def _configure_logging(app: Flask) -> None:
    from app.utils.logger import configure_logging

    configure_logging(app)


def _register_error_handlers(app: Flask) -> None:
    """Log unhandled (500-class) exceptions before Flask handles them."""
    from werkzeug.exceptions import HTTPException

    from app.utils.logger import get_logger

    logger = get_logger("app.errors")

    @app.errorhandler(Exception)
    def _on_exception(exc: Exception):
        # Let normal HTTP responses (404, 400 CSRF, 401, etc.) pass through
        # untouched — they're expected control flow, not failures to log.
        if isinstance(exc, HTTPException):
            return exc
        # Real unhandled error: record the traceback. No request body is
        # logged, so passwords / tokens in the POST payload never reach the log.
        logger.exception("Unhandled exception: %s", exc)
        # Re-raise so Flask's normal 500 handling / debugger still runs.
        raise exc


def _register_context_processors(app: Flask) -> None:
    import uuid
    from datetime import datetime

    @app.context_processor
    def inject_globals() -> dict:
        # `current_year` is used in the footer; injected here so templates
        # don't need each route to pass it.
        #
        # `meta_pixel_id` / `meta_event_id` drive the browser Meta Pixel in
        # base.html. The pixel id is read from config (never hardcoded), so it
        # only fires where META_PIXEL_ID is set — dev and tests stay silent.
        # A fresh event_id per request lets a browser event be deduplicated
        # against the matching server-side Conversions API event that shares
        # the same id (see app/services/meta_service.py).
        # Pixel id resolves through settings_service (dashboard value, else
        # env), so enabling the pixel from the admin UI lights up the browser
        # tag too. Only fire the browser pixel when Meta is enabled.
        from app.services import settings_service

        pixel_id = ""
        if settings_service.get_bool(settings_service.META_ENABLED):
            pixel_id = settings_service.get_str(settings_service.META_PIXEL_ID)
        return {
            "current_year": datetime.utcnow().year,
            "meta_pixel_id": pixel_id,
            "meta_event_id": uuid.uuid4().hex,
        }


def _register_cli(app: Flask) -> None:
    """Attach custom CLI commands (e.g. `flask create-admin`)."""
    from app.cli import register_commands

    register_commands(app)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import content_bp, dashboard_bp
    from app.blueprints.public import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(content_bp)
