from __future__ import annotations

from sqlmodel import Session, create_engine

from app.db.models import (
    CharacterHistory,
    GlobalConfig,
    SideCharacter,
    SQLModel,
    TarotEntity,
    TarotShard,
    TarotTransaction,
)

# ─── Engine ───────────────────────────────────────────────────────────────────
# SQLite for local dev. Swap the URL via DATABASE_URL env var for production.
DATABASE_URL = "sqlite:///./tarot.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True to log all SQL statements (debug mode)
    connect_args={"check_same_thread": False},  # Required for SQLite + async
)


def create_db_and_tables() -> None:
    """Create all tables from the SQLModel metadata."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """Return a Session that can be used as a context manager: `with get_session() as s:`"""
    return Session(engine)


# ---------------------------------------------------------
# Initialization Blueprint
# Seeds the database on first run with root totals + ROOT entity.
# Safe to call multiple times (checks for existing records first).
# ---------------------------------------------------------
TOTAL_UPRIGHT_ENERGY = 1_000_000_000
TOTAL_REVERSED_ENERGY = 1_000_000_000


def init_root(session: Session) -> TarotEntity:
    """
    Idempotent root initialization:
      1. Write GlobalConfig constants if not already present.
      2. Create the ROOT entity if it doesn't exist.
    Returns the ROOT entity.
    """
    # 1 — Global totals
    for key, value in [
        ("TOTAL_UPRIGHT_ENERGY", TOTAL_UPRIGHT_ENERGY),
        ("TOTAL_REVERSED_ENERGY", TOTAL_REVERSED_ENERGY),
    ]:
        if not session.get(GlobalConfig, key):
            session.add(GlobalConfig(key=key, value=value))

    # 2 — ROOT entity (holds all energy at genesis)
    from sqlmodel import select

    existing = session.exec(
        select(TarotEntity).where(TarotEntity.entity_name == "ROOT")
    ).first()

    if existing:
        session.commit()
        return existing

    root = TarotEntity(
        entity_name="ROOT",
        upright_energy=TOTAL_UPRIGHT_ENERGY,
        reversed_energy=TOTAL_REVERSED_ENERGY,
    )
    session.add(root)
    session.commit()
    session.refresh(root)
    return root
