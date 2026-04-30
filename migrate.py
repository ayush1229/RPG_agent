"""
migrate.py — Idempotent SQLite schema migration for tarot.db.

Run once to add columns that exist in the SQLModel definitions
but are missing from the on-disk SQLite database (because SQLite
only creates tables, it never ALTERs existing ones automatically).

Safe to run multiple times — each ALTER TABLE is skipped if the
column already exists.

Usage:
    uv run python migrate.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("tarot.db")


def existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def add_column(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    """Add a column if it does not already exist."""
    if col not in existing_columns(conn, table):
        sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
        conn.execute(sql)
        print(f"  + {table}.{col}")
    else:
        print(f"  . {table}.{col}  (already present)")


def existing_tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def migrate() -> None:
    if not DB_PATH.exists():
        print("tarot.db not found — nothing to migrate (will be created fresh on startup).")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")   # allow schema edits without FK violations
    tables = existing_tables(conn)

    print(f"\nMigrating {DB_PATH} ...\n")

    # ─── tarotentity ───────────────────────────────────────────────────────────
    if "tarotentity" in tables:
        print("[tarotentity]")
        add_column(conn, "tarotentity", "current_location_id", "INTEGER REFERENCES location(id)")
        add_column(conn, "tarotentity", "level",                    "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "tarotentity", "current_xp",               "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tarotentity", "health_bonus_from_levels",  "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tarotentity", "damage_bonus",              "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tarotentity", "damage_reduction",          "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tarotentity", "pos_x",                     "REAL NOT NULL DEFAULT 0.0")
        add_column(conn, "tarotentity", "pos_y",                     "REAL NOT NULL DEFAULT 0.0")
        add_column(conn, "tarotentity", "max_health",                "INTEGER NOT NULL DEFAULT 100")
        add_column(conn, "tarotentity", "dominant_energy",           "VARCHAR DEFAULT 'upright'")
        add_column(conn, "tarotentity", "is_upright_sovereign",      "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tarotentity", "is_reversed_sovereign",     "INTEGER NOT NULL DEFAULT 0")

    # ─── dialoguelog ───────────────────────────────────────────────────────────
    if "dialoguelog" in tables:
        print("\n[dialoguelog]")
        add_column(conn, "dialoguelog", "chat_session_id", "VARCHAR")

    # ─── location ──────────────────────────────────────────────────────────────
    if "location" in tables:
        print("\n[location]")
        add_column(conn, "location", "radius",               "REAL NOT NULL DEFAULT 50.0")
        add_column(conn, "location", "is_safe_zone",         "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "location", "is_magic_restricted",  "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "location", "location_type",        "VARCHAR DEFAULT 'town'")
        add_column(conn, "location", "description",          "VARCHAR DEFAULT ''")
        add_column(conn, "location", "x",                    "REAL NOT NULL DEFAULT 0.0")
        add_column(conn, "location", "y",                    "REAL NOT NULL DEFAULT 0.0")
        add_column(conn, "location", "kingdom_id",           "INTEGER REFERENCES worldmap(id)")
        add_column(conn, "location", "region_type",          "VARCHAR DEFAULT 'plains'")
        add_column(conn, "location", "region_main_quest_id", "INTEGER REFERENCES quest(id)")
        add_column(conn, "location", "terrain_type",         "VARCHAR DEFAULT 'plains'")
        add_column(conn, "location", "danger_level",         "INTEGER NOT NULL DEFAULT 1")

    # ─── usersession ───────────────────────────────────────────────────────────
    if "usersession" in tables:
        print("\n[usersession]")
        add_column(conn, "usersession", "last_location_id",    "INTEGER REFERENCES location(id)")
        add_column(conn, "usersession", "last_game_state",     "VARCHAR")
        add_column(conn, "usersession", "last_active_quest_id","INTEGER REFERENCES quest(id)")
        add_column(conn, "usersession", "updated_at",          "TIMESTAMP")

    # ─── inventoryitem ─────────────────────────────────────────────────────────
    if "inventoryitem" in tables:
        print("\n[inventoryitem]")
        add_column(conn, "inventoryitem", "base_price",  "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "inventoryitem", "tradable",    "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "inventoryitem", "durability",  "INTEGER")
        add_column(conn, "inventoryitem", "stackable",   "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "inventoryitem", "quantity",    "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "inventoryitem", "rarity",      "VARCHAR DEFAULT 'common'")

    # ─── quest ─────────────────────────────────────────────────────────────────
    if "quest" in tables:
        print("\n[quest]")
        add_column(conn, "quest", "quest_type",     "VARCHAR DEFAULT 'side'")
        add_column(conn, "quest", "difficulty",     "VARCHAR DEFAULT 'normal'")
        add_column(conn, "quest", "required_level", "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "quest", "xp_reward",      "INTEGER NOT NULL DEFAULT 100")
        add_column(conn, "quest", "description",    "VARCHAR DEFAULT ''")
        add_column(conn, "quest", "region_main_quest_id", "INTEGER REFERENCES quest(id)")

    # ─── sidecharacter ─────────────────────────────────────────────────────────
    if "sidecharacter" in tables:
        print("\n[sidecharacter]")
        add_column(conn, "sidecharacter", "location_id",    "INTEGER REFERENCES location(id)")
        add_column(conn, "sidecharacter", "position",       "VARCHAR DEFAULT 'citizen'")
        add_column(conn, "sidecharacter", "current_status", "VARCHAR DEFAULT 'idle'")

    # ─── travelstate ───────────────────────────────────────────────────────────
    if "travelstate" in tables:
        print("\n[travelstate]")
        add_column(conn, "travelstate", "terrain_type",         "VARCHAR DEFAULT 'plains'")
        add_column(conn, "travelstate", "speed",                "REAL NOT NULL DEFAULT 1.0")
        add_column(conn, "travelstate", "travel_time_seconds",  "REAL NOT NULL DEFAULT 0.0")
        add_column(conn, "travelstate", "is_completed",         "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "travelstate", "target_location_id",   "INTEGER REFERENCES location(id)")

    # ─── worldeventinstance ────────────────────────────────────────────────────
    if "worldeventinstance" in tables:
        print("\n[worldeventinstance]")
        add_column(conn, "worldeventinstance", "difficulty_scale", "REAL NOT NULL DEFAULT 1.0")
        add_column(conn, "worldeventinstance", "is_active",        "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "worldeventinstance", "location_id",      "INTEGER REFERENCES location(id)")
        add_column(conn, "worldeventinstance", "template_id",      "INTEGER REFERENCES eventtemplate(id)")
        add_column(conn, "worldeventinstance", "spawned_at",       "TIMESTAMP")
        add_column(conn, "worldeventinstance", "expires_at",       "TIMESTAMP")

    # ─── guild ─────────────────────────────────────────────────────────────────
    if "guild" in tables:
        print("\n[guild]")
        add_column(conn, "guild", "description",              "VARCHAR DEFAULT ''")
        add_column(conn, "guild", "guild_type",               "VARCHAR DEFAULT 'combat'")
        add_column(conn, "guild", "is_secret",                "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "guild", "headquarters_location_id", "INTEGER REFERENCES location(id)")
        add_column(conn, "guild", "master_id",                "INTEGER REFERENCES tarotentity(id)")

    # ─── wallet ────────────────────────────────────────────────────────────────
    if "wallet" in tables:
        print("\n[wallet]")
        add_column(conn, "wallet", "balance", "INTEGER NOT NULL DEFAULT 0")

    # ─── playerhousing ─────────────────────────────────────────────────────────
    if "playerhousing" in tables:
        print("\n[playerhousing]")
        add_column(conn, "playerhousing", "housing_type",  "VARCHAR DEFAULT 'inn'")
        add_column(conn, "playerhousing", "is_safe_zone",  "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "playerhousing", "is_inside",     "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "playerhousing", "expires_at",    "TIMESTAMP")
        add_column(conn, "playerhousing", "rented_at",     "TIMESTAMP")
        add_column(conn, "playerhousing", "location_id",   "INTEGER REFERENCES location(id)")

    # ─── dreamstate ────────────────────────────────────────────────────────────
    if "dreamstate" in tables:
        print("\n[dreamstate]")
        add_column(conn, "dreamstate", "has_unlocked",         "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "dreamstate", "is_in_dreamscape",     "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "dreamstate", "last_entered",         "TIMESTAMP")
        add_column(conn, "dreamstate", "pre_dream_location_id","INTEGER REFERENCES location(id)")
        add_column(conn, "dreamstate", "dream_progress_flag",  "VARCHAR DEFAULT '{}'")

    # ─── tutorialstate ─────────────────────────────────────────────────────────
    if "tutorialstate" in tables:
        print("\n[tutorialstate]")
        add_column(conn, "tutorialstate", "phase",        "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "tutorialstate", "phase_data",   "VARCHAR DEFAULT '{}'")
        add_column(conn, "tutorialstate", "started_at",   "TIMESTAMP")
        add_column(conn, "tutorialstate", "completed_at", "TIMESTAMP")

    # ─── worldtime ─────────────────────────────────────────────────────────────
    if "worldtime" in tables:
        print("\n[worldtime]")
        add_column(conn, "worldtime", "current_time",  "TIMESTAMP")
        add_column(conn, "worldtime", "time_scale",    "REAL NOT NULL DEFAULT 60.0")
        add_column(conn, "worldtime", "last_real_tick","TIMESTAMP")

    # ─── questprogress ─────────────────────────────────────────────────────────
    if "questprogress" in tables:
        print("\n[questprogress]")
        add_column(conn, "questprogress", "progress",     "VARCHAR DEFAULT ''")
        add_column(conn, "questprogress", "goal",         "VARCHAR DEFAULT ''")
        add_column(conn, "questprogress", "is_completed", "INTEGER NOT NULL DEFAULT 0")

    # ─── mainstorystate ────────────────────────────────────────────────────────
    if "mainstorystate" in tables:
        print("\n[mainstorystate]")
        add_column(conn, "mainstorystate", "current_arc",    "INTEGER NOT NULL DEFAULT 0")
        add_column(conn, "mainstorystate", "flags",          "VARCHAR DEFAULT '{}'")
        add_column(conn, "mainstorystate", "updated_at",     "TIMESTAMP")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    print("\n✅  Migration complete.\n")
    print("Run: uv run chainlit run main.py -w")


if __name__ == "__main__":
    migrate()
