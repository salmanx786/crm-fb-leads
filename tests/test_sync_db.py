"""Tests for scripts/sync_db.py — the additive schema-sync command.

Simulates the production scenario the script exists for: a live table that
predates a column now present on the model. Asserts the sync adds the missing
column and is idempotent on a second run.
"""
import importlib

from sqlalchemy import inspect, text

from app.extensions import db


def _load_sync_db():
    """Import scripts/sync_db.py by path (scripts/ isn't a package)."""
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("sync_db")


def test_adds_missing_column_and_is_idempotent(app):
    """Drop a known column from the live `leads` table, then sync it back."""
    engine = db.engine
    sync_db = _load_sync_db()

    # Sanity: the model declares first_name; the fresh test DB has it.
    cols = {c["name"] for c in inspect(engine).get_columns("leads")}
    assert "first_name" in cols

    # Simulate an older schema by dropping the column at the DB level. SQLite
    # supports DROP COLUMN (3.35+), which the test runner ships.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE leads DROP COLUMN first_name"))

    cols = {c["name"] for c in inspect(engine).get_columns("leads")}
    assert "first_name" not in cols

    # Run the additive sync against the already-built app/DB context.
    added = sync_db._add_missing_columns(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("leads")}
    assert "first_name" in cols, "sync should re-add the dropped column"
    assert "first_name" in added.get("leads", [])

    # Idempotent: a second run finds nothing to add.
    added_again = sync_db._add_missing_columns(engine)
    assert "leads" not in added_again


def test_skips_not_null_column_without_default(app, capsys):
    """A NOT NULL column with no default can't be back-filled — sync skips it
    and says so, rather than issuing DDL that would fail on a table with rows.
    """
    engine = db.engine
    sync_db = _load_sync_db()

    # `name` is NOT NULL with no default. Drop it and confirm sync refuses.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE leads DROP COLUMN name"))

    added = sync_db._add_missing_columns(engine)

    assert "name" not in added.get("leads", [])
    out = capsys.readouterr().out
    assert "SKIP name" in out
    cols = {c["name"] for c in inspect(engine).get_columns("leads")}
    assert "name" not in cols
