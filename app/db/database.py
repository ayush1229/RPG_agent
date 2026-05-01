from __future__ import annotations

from sqlalchemy.orm import configure_mappers
from sqlmodel import Session, create_engine, select

from app.db.models import (
    GlobalConfig,
    SQLModel,
    TarotEntity,
)

# ─── Engine ───────────────────────────────────────────────────────────────────
DATABASE_URL = "sqlite:///./tarot.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# Force SQLAlchemy to resolve all deferred string Relationship() references
# (e.g. "CharacterPersona" in TarotCardLore) immediately at import time.
# Without this, the mapper configuration can fail on the first query if the
# data layer is imported before all model classes have been scanned.
configure_mappers()


def create_db_and_tables() -> None:
    """Create all tables from the SQLModel metadata."""
    SQLModel.metadata.create_all(engine)


def run_migrations() -> None:
    """
    Idempotent column migrations for SQLite.
    Adds new columns to existing tables without dropping data.
    Safe to call on every startup.
    """
    from sqlalchemy import text

    # (table, column_name, sqlite_column_def)
    new_columns = [
        ("inventoryitem", "is_equipped",    "BOOLEAN NOT NULL DEFAULT 0"),
        ("inventoryitem", "equipped_slot",  "TEXT"),
        ("inventoryitem", "max_durability", "INTEGER"),
        ("inventoryitem", "max_stack",      "INTEGER NOT NULL DEFAULT 99"),
        ("inventoryitem", "weight",         "REAL NOT NULL DEFAULT 0.0"),
        ("inventoryitem", "attack_bonus",   "INTEGER NOT NULL DEFAULT 0"),
        ("inventoryitem", "defense_bonus",  "INTEGER NOT NULL DEFAULT 0"),
        ("location", "danger_level",        "REAL NOT NULL DEFAULT 1.0"),
        ("location", "terrain_type",        "TEXT NOT NULL DEFAULT 'plains'"),
        ("travelstate", "route_type",       "TEXT NOT NULL DEFAULT 'safe'"),
        ("travelstate", "status",           "TEXT NOT NULL DEFAULT 'active'"),
        ("travelstate", "last_event_progress_pct", "REAL NOT NULL DEFAULT 0.0"),
        ("sidecharacter", "has_met_player", "BOOLEAN NOT NULL DEFAULT 0"),
        ("sidecharacter", "sub_location_id", "INTEGER"),
        ("tarotentity", "sub_location_id",  "INTEGER"),
    ]

    with engine.begin() as conn:
        for table, col, col_def in new_columns:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in rows}
            if col not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))



def get_session() -> Session:
    """Return a Session usable as a context manager: `with get_session() as s:`"""
    return Session(engine)


# ---------------------------------------------------------
# Genesis Constants
# ---------------------------------------------------------
TOTAL_UPRIGHT_CAPACITY = 1_000_000_000
TOTAL_REVERSED_CAPACITY = 1_000_000_000


def init_root(session: Session) -> TarotEntity:
    """
    Idempotent root initialization:
      1. Write GlobalConfig capacity constants if not already present.
      2. Create the ROOT entity with full capacity + mana if it doesn't exist.
    Returns the ROOT entity.
    """
    # 1 — Global capacity totals
    for key, value in [
        ("TOTAL_UPRIGHT_CAPACITY", TOTAL_UPRIGHT_CAPACITY),
        ("TOTAL_REVERSED_CAPACITY", TOTAL_REVERSED_CAPACITY),
    ]:
        if not session.get(GlobalConfig, key):
            session.add(GlobalConfig(key=key, value=value))

    # 2 — ROOT entity (holds all capacity at genesis)
    existing = session.exec(
        select(TarotEntity).where(TarotEntity.entity_name == "ROOT")
    ).first()

    if existing:
        session.commit()
        return existing

    root = TarotEntity(
        entity_name="ROOT",
        upright_capacity=TOTAL_UPRIGHT_CAPACITY,
        reversed_capacity=TOTAL_REVERSED_CAPACITY,
        current_upright_mana=TOTAL_UPRIGHT_CAPACITY,
        current_reversed_mana=TOTAL_REVERSED_CAPACITY,
    )
    session.add(root)
    session.commit()
    session.refresh(root)
    return root
