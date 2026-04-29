from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


# ---------------------------------------------------------
# 1. STATIC LORE (REFERENCE DATA — no FK dependencies)
# ---------------------------------------------------------
class TarotCardLore(SQLModel, table=True):
    """
    Static reference table for Tarot card meanings and magical themes.
    Seeded once and used as JIT context by the GM and Persona agents.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)     # e.g. "The Fool", "Three of Swords"
    arcana_type: str                                # "Major" | "Minor"
    suit: Optional[str] = Field(default=None)      # None for Major Arcana

    # Core meanings
    upright_meaning: str
    reversed_meaning: str

    # RPG-specific hooks injected into agent prompts
    magical_manifestation: str     # e.g. "Lightning strikes that arc unpredictably"
    personality_archetype: str     # e.g. "The reckless visionary who leaps before looking"

    # Relationships
    affiliated_personas: List["CharacterPersona"] = Relationship(
        back_populates="tarot_affinity"
    )
    affiliated_shards: List["TarotShard"] = Relationship(
        back_populates="lore"
    )


# ---------------------------------------------------------
# 2. GLOBAL CONFIGURATION (HARD INVARIANTS)
# ---------------------------------------------------------
class GlobalConfig(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    key: str = Field(primary_key=True)
    value: int


# ---------------------------------------------------------
# 3. CORE ENERGY HOLDERS
# ---------------------------------------------------------
class TarotEntity(SQLModel, table=True):
    """
    Any entity that can hold Tarot energy (player, NPC, ROOT, etc.).
    Never mutate balances directly — use TarotService only.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_name: str = Field(index=True)
    upright_energy: int = Field(default=0, ge=0)
    reversed_energy: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    side_character: Optional["SideCharacter"] = Relationship(back_populates="tarot_wallet")
    outgoing_transactions: List["TarotTransaction"] = Relationship(
        back_populates="from_entity",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.from_entity_id]"},
    )
    incoming_transactions: List["TarotTransaction"] = Relationship(
        back_populates="to_entity",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.to_entity_id]"},
    )


# ---------------------------------------------------------
# 4. TRANSACTION LEDGER
# ---------------------------------------------------------
class TarotTransaction(SQLModel, table=True):
    """Immutable append-only ledger. from_entity_id=None means genesis mint."""
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    from_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    to_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    upright_amount: int = Field(default=0, ge=0)
    reversed_amount: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str

    from_entity: Optional[TarotEntity] = Relationship(
        back_populates="outgoing_transactions",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.from_entity_id]"},
    )
    to_entity: Optional[TarotEntity] = Relationship(
        back_populates="incoming_transactions",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.to_entity_id]"},
    )


# ---------------------------------------------------------
# 5. WORLD GEOGRAPHY (Game Master Agent)
# ---------------------------------------------------------
class Location(SQLModel, table=True):
    """
    A physical place in the world.
    is_safe_zone: Arbiter rejects energy transfers here.
    is_magic_restricted: GM shapes encounter possibilities.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str
    is_safe_zone: bool = Field(default=False)
    is_magic_restricted: bool = Field(default=False)

    occupants: List["SideCharacter"] = Relationship(back_populates="current_location")


# ---------------------------------------------------------
# 6. NARRATIVE LAYER (CHARACTERS)
# ---------------------------------------------------------
class SideCharacter(SQLModel, table=True):
    """A narrative character with a TarotEntity wallet, location, and persona."""
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    position: str
    current_status: str

    tarot_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    location_id: Optional[int] = Field(default=None, foreign_key="location.id")

    tarot_wallet: Optional[TarotEntity] = Relationship(back_populates="side_character")
    current_location: Optional[Location] = Relationship(back_populates="occupants")
    history_logs: List["CharacterHistory"] = Relationship(back_populates="character")
    persona: Optional["CharacterPersona"] = Relationship(back_populates="character")


# ---------------------------------------------------------
# 7. CHARACTER HISTORY (Roleplay Memory)
# ---------------------------------------------------------
class CharacterHistory(SQLModel, table=True):
    """
    Append-only event log. event_type allows filtered recall:
    'dialogue' | 'combat' | 'transfer' | 'movement'
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str
    event_description: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    character_id: int = Field(foreign_key="sidecharacter.id")
    character: SideCharacter = Relationship(back_populates="history_logs")


# ---------------------------------------------------------
# 8. NPC BRAIN (Persona Agent)
# ---------------------------------------------------------
class CharacterPersona(SQLModel, table=True):
    """
    Static personality data injected into the Persona Agent's system prompt.
    Behavioral attributes (0–100) make NPC responses numerically consistent.
    tarot_affinity links to the card archetype that defines their magic style.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    motivation: str
    hidden_secret: str
    speaking_style: str
    risk_tolerance: int = Field(default=50, ge=0, le=100)  # 0=coward, 100=reckless
    loyalty: int = Field(default=50, ge=0, le=100)         # 0=betrayer, 100=devoted
    aggression: int = Field(default=50, ge=0, le=100)      # 0=pacifist, 100=violent

    character_id: int = Field(foreign_key="sidecharacter.id")
    character: Optional[SideCharacter] = Relationship(back_populates="persona")

    # Tarot affinity — links to the card whose archetype defines this NPC's magic
    tarot_affinity_id: Optional[int] = Field(default=None, foreign_key="tarotcardlore.id")
    tarot_affinity: Optional[TarotCardLore] = Relationship(
        back_populates="affiliated_personas"
    )


# ---------------------------------------------------------
# 9. ARCANA SHARD SYSTEM
# ---------------------------------------------------------
class TarotShard(SQLModel, table=True):
    """
    A discrete arcana shard. energy_type validated at service layer.
    lore links to the TarotCardLore that names and defines this shard.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    energy_type: str   # "upright" | "reversed"
    value: int         # must be > 0

    # Normalized: card name comes from lore.name, not a denormalized string field
    lore_id: Optional[int] = Field(default=None, foreign_key="tarotcardlore.id")
    lore: Optional[TarotCardLore] = Relationship(back_populates="affiliated_shards")

    owner_id: int = Field(foreign_key="tarotentity.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
