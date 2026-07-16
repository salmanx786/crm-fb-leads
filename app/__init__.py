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
    app.config.from_object(config[config_name])

    _init_extensions(app)
    _register_blueprints(app)
    _register_context_processors(app)

    # Ensure models are imported so SQLAlchemy/Migrate see them.
    from app import models  # noqa: F401

    return app


def _register_context_processors(app: Flask) -> None:
    from datetime import datetime

    @app.context_processor
    def inject_globals() -> dict:
        # `current_year` is used in the footer; injected here so templates
        # don't need each route to pass it.
        return {"current_year": datetime.utcnow().year}


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.public import public_bp

    app.register_blueprint(public_bp)
