"""
migrate.py -- Fully automatic, idempotent SQLite schema migration.

Compares every column defined in SQLModel metadata against the on-disk
tarot.db schema, and issues ALTER TABLE ADD COLUMN for any that are missing.

Safe to run any number of times. Covers ALL models, past and future.

Usage:
    uv run python migrate.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Force all models to register with SQLModel.metadata
from sqlmodel import SQLModel
from app.db.models import *  # noqa: F401,F403

DB_PATH = Path("tarot.db")

# Map SQLAlchemy type objects to SQLite type affinity strings
_TYPE_MAP = {
    "INTEGER": "INTEGER",
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "FLOAT": "REAL",
    "REAL": "REAL",
    "BOOLEAN": "INTEGER",
    "DATETIME": "TIMESTAMP",
    "DATE": "DATE",
    "BLOB": "BLOB",
    "NUMERIC": "NUMERIC",
}


def _sqlite_type(sa_type) -> str:
    """Convert an SA type to a SQLite affinity string."""
    type_name = type(sa_type).__name__.upper()
    for key, val in _TYPE_MAP.items():
        if key in type_name:
            return val
    return "TEXT"


def _col_default(col) -> str:
    """Build a DEFAULT clause from the SA column, if any."""
    if col.server_default is not None:
        raw = col.server_default.arg
        if callable(raw):
            return ""
        return f" DEFAULT {raw}"
    if col.nullable:
        return ""
    # Non-nullable with no server_default — provide a safe zero-value
    affinity = _sqlite_type(col.type)
    if affinity in ("INTEGER", "REAL", "NUMERIC"):
        return " NOT NULL DEFAULT 0"
    return " NOT NULL DEFAULT ''"


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def migrate() -> None:
    if not DB_PATH.exists():
        print("tarot.db not found -- nothing to migrate (will be created fresh on startup).")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    disk_tables = _existing_tables(conn)

    added = 0
    skipped = 0
    tables_missing = 0

    print(f"\nMigrating {DB_PATH} ...\n")

    for table_name, table_obj in sorted(SQLModel.metadata.tables.items()):
        if table_name not in disk_tables:
            print(f"  [{table_name}] TABLE MISSING -- will be created by create_db_and_tables()")
            tables_missing += 1
            continue

        disk_cols = _existing_columns(conn, table_name)
        model_cols = {col.name: col for col in table_obj.columns}
        missing = set(model_cols.keys()) - disk_cols

        if not missing:
            continue

        print(f"  [{table_name}]")
        for col_name in sorted(missing):
            col = model_cols[col_name]
            affinity = _sqlite_type(col.type)
            default_clause = _col_default(col)
            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {affinity}{default_clause}"
            try:
                conn.execute(sql)
                print(f"    + {col_name}  ({affinity})")
                added += 1
            except Exception as e:
                print(f"    ! {col_name}  FAILED: {e}")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    print(f"\nDone: {added} columns added, {skipped} skipped, {tables_missing} tables pending creation.\n")


if __name__ == "__main__":
    migrate()
