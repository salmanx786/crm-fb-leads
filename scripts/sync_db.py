"""Bring any database in line with the current models — tables AND columns.

This repo has no active migration path (Alembic is installed but never
initialised). `scripts/init_db.py` runs `db.create_all()`, which adds missing
*tables* but never ALTERs existing tables to add new *columns*. After a
`git pull` that adds columns to an existing table (e.g. the split-name and
academic fields on `leads`), the old table is missing those columns and every
query that selects them 500s.

This script closes that gap with an additive, idempotent, dialect-aware sync:

1. `db.create_all()` — create any missing tables.
2. For each mapped table, diff the model's columns against the live table
   (via SQLAlchemy's inspector) and `ALTER TABLE ... ADD COLUMN` the ones the
   DB is missing. Additive only — never DROP, RENAME, or change a type.
3. Seed defaults (content, lead statuses), mirroring init_db.py.

Safe to run repeatedly: a second run finds nothing missing. Works on prod
MySQL and the SQLite test DB because column types are compiled with the
active dialect.

For cPanel's "Execute python script" field (no TTY), point it at this file.
"""
import os
import sys

# Running a script puts scripts/ on sys.path, not the project root, so the
# `app` package would not import. Add the project root explicitly (mirrors
# init_db.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect

from app import create_app
from app.extensions import db
from app.services import content_service, status_service


def _default_clause(column, dialect):
    """Return a `DEFAULT <literal>` fragment for a column, or "" if none.

    Only scalar Python defaults (str/int/bool) and server_defaults are
    translated. A DEFAULT is required to safely add a NOT NULL column to a
    table that already has rows, so existing rows get a value.
    """
    server_default = getattr(column, "server_default", None)
    if server_default is not None and getattr(server_default, "arg", None) is not None:
        arg = server_default.arg.text if hasattr(server_default.arg, "text") else server_default.arg
        if isinstance(arg, str):
            clean = arg.strip()
            if not (clean.startswith("'") and clean.endswith("'")) and "(" not in clean:
                escaped = clean.replace("'", "''")
                return f" DEFAULT '{escaped}'"
            return f" DEFAULT {clean}"
        return f" DEFAULT {arg}"

    default = getattr(column, "default", None)
    if default is None or getattr(default, "is_callable", False) or default.is_clause_element:
        return ""  # callable/py-side dynamic defaults can't be expressed in DDL
    value = default.arg
    if isinstance(value, bool):
        return f" DEFAULT {'1' if value else '0'}"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def _add_missing_columns(engine):
    """ALTER existing tables to add columns present in the models but not the DB.

    Returns a dict {table_name: [added_column_names]} and prints per-column
    actions and any DB-only columns (informational).
    """
    inspector = inspect(engine)
    dialect = engine.dialect
    live_tables = set(inspector.get_table_names())
    added = {}

    for table in db.metadata.sorted_tables:
        if table.name not in live_tables:
            # create_all already made brand-new tables; nothing to ALTER.
            continue

        live_columns = {c["name"] for c in inspector.get_columns(table.name)}
        model_columns = {c.name for c in table.columns}

        # Informational: columns in the DB the model no longer declares. We
        # never touch these (additive only), just report them.
        extra = live_columns - model_columns
        if extra:
            print(f"  [{table.name}] DB has columns not in model (left alone): "
                  f"{', '.join(sorted(extra))}")

        for column in table.columns:
            if column.name in live_columns:
                continue

            type_sql = column.type.compile(dialect)
            default_sql = _default_clause(column, dialect)

            if not column.nullable and not default_sql:
                # Can't back-fill existing rows safely — needs a human.
                print(f"  [{table.name}] SKIP {column.name}: NOT NULL with no "
                      f"default. Add it by hand (choose a back-fill value).")
                continue

            null_sql = "" if column.nullable else " NOT NULL"
            ddl = (f"ALTER TABLE {table.name} ADD COLUMN "
                   f"{column.name} {type_sql}{default_sql}{null_sql}")
            with engine.begin() as conn:
                from sqlalchemy import text
                conn.execute(text(ddl))
            added.setdefault(table.name, []).append(column.name)
            print(f"  [{table.name}] ADDED {column.name} ({type_sql})")

    return added


def main():
    app = create_app()
    with app.app_context():
        engine = db.engine

        print("1. Creating any missing tables (create_all)...")
        before = set(inspect(engine).get_table_names())
        db.create_all()
        after = set(inspect(engine).get_table_names())
        created = sorted(after - before)
        if created:
            print(f"   Created tables: {', '.join(created)}")
        else:
            print("   No new tables.")

        print("2. Adding any missing columns...")
        added = _add_missing_columns(engine)
        if not added:
            print("   No missing columns.")

        print("3. Seeding defaults (idempotent)...")
        content_service.seed_defaults()
        seeded = status_service.seed_defaults()
        print(f"   Lead statuses seeded: {seeded}")

        # Summary
        print("\nSummary")
        print(f"  Tables created : {len(created)} ({', '.join(created) or 'none'})")
        total_cols = sum(len(v) for v in added.values())
        print(f"  Columns added  : {total_cols}")
        for table, cols in added.items():
            print(f"    {table}: {', '.join(cols)}")
        print(f"  Statuses seeded: {seeded}")
        print("Done.")


if __name__ == "__main__":
    main()
