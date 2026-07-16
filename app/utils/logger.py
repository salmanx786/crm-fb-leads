"""Structured application logging.

Reusable across the whole app: call ``configure_logging(app)`` once from the
factory, then ``get_logger(__name__)`` anywhere to obtain a namespaced logger.

Design notes:
- A rotating file handler writes to ``logs/app.log`` (INFO and above) so the
  file never grows unbounded on shared hosting.
- A separate stream handler surfaces WARNING+ on the console during
  development.
- Under the testing config we skip the file handler entirely, so the test
  suite never touches the filesystem.

NEVER pass secrets to these loggers. Log identifiers (lead id, user id/email,
status names) — never passwords, session cookies, or CSRF tokens.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing Flask at module load for lightweight reuse
    from flask import Flask

# Root logger name every app module hangs off, so one config governs them all.
LOGGER_ROOT = "mc"

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Rotation policy: 1 MB per file, keep 5 backups (~6 MB ceiling).
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 5


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced logger under the app's root logger.

    Passing ``__name__`` (e.g. ``app.services.lead_service``) yields a child
    logger, so log lines show exactly where they came from.
    """
    if not name or name == LOGGER_ROOT:
        return logging.getLogger(LOGGER_ROOT)
    # Normalise the caller's module path onto our root namespace.
    suffix = name.split(".", 1)[-1] if name.startswith("app") else name
    return logging.getLogger(f"{LOGGER_ROOT}.{suffix}")


def configure_logging(app: "Flask") -> None:
    """Attach handlers to the app's root logger. Idempotent.

    Called once from the application factory. Safe to call again (e.g. per
    test app) — existing handlers are cleared first so we don't double-log.
    """
    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # don't bubble to the root logger / double print

    # Clear any handlers from a previous configuration (test app rebuilds).
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console: WARNING+ so dev output stays readable.
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # File handler is skipped during tests to keep the suite filesystem-free.
    if not app.config.get("TESTING"):
        log_dir = os.path.join(app.root_path, os.pardir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Route Flask's own logger through our handlers too, so app.logger.error
    # (e.g. from the exception handler) lands in the same file.
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logging.INFO)
