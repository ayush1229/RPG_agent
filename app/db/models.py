

from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------
# 1. STATIC LORE (no FK dependencies — defined first)
# ---------------------------------------------------------
class TarotCardLore(SQLModel, table=True):
    """
    Static reference table for Tarot card meanings and magical themes.
    Seeded once. Used as JIT context by GM and Persona agents.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)   # "The Fool", "Three of Swords"
    arcana_type: str                              # "Major" | "Minor"
    suit: Optional[str] = Field(default=None)    # None for Major Arcana

    # Core meanings
    upright_meaning: str
    reversed_meaning: str

    # RPG-specific prompt hooks
    magical_manifestation: str      # "Lightning arcs that strike unpredictably"
    personality_archetype: str      # "The reckless visionary"

    # Structured thematic fields (for richer JIT context)
    core_themes: str                # "beginnings, freedom, spontaneity"
    power_domains: str              # "air, wind, chaos, chance"
    behavioral_bias: str            # "acts before thinking, trusts fate"

    # Relationships (back-populated from dependents)
    affiliated_personas: List["CharacterPersona"] = Relationship(
        back_populates="tarot_affinity"
    )
    affiliated_shards: List["TarotShard"] = Relationship(
        back_populates="lore"
    )
    abilities: List["TarotAbility"] = Relationship(
        back_populates="card"
    )


# ---------------------------------------------------------
# 2. GLOBAL CONFIGURATION (hard invariants)
# ---------------------------------------------------------
class GlobalConfig(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    key: str = Field(primary_key=True)
    value: int


# ---------------------------------------------------------
# 3. CORE ENERGY HOLDERS
#    Capacity = permanent, zero-sum, used for sovereignty
#    Mana     = temporary, regenerates, used for casting
# ---------------------------------------------------------
class TarotEntity(SQLModel, table=True):
    """
    Any entity that can hold Tarot energy (player, NPC, ROOT).
    - Capacity is ONLY modified via TarotService.transfer_energy()
    - Mana is ONLY modified via regeneration and spell casting
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_name: str = Field(index=True)

    # ── PERMANENT (zero-sum, conserved) ──────────────────
    upright_capacity: int = Field(default=0, ge=0)
    reversed_capacity: int = Field(default=0, ge=0)

    # ── TEMPORARY (spendable mana) ────────────────────────
    current_upright_mana: int = Field(default=0, ge=0)
    current_reversed_mana: int = Field(default=0, ge=0)
    last_mana_update: datetime = Field(default_factory=utcnow)

    created_at: datetime = Field(default_factory=utcnow)

    # Relationships
    side_character: Optional["SideCharacter"] = Relationship(
        back_populates="tarot_wallet"
    )
    outgoing_transactions: List["TarotTransaction"] = Relationship(
        back_populates="from_entity",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.from_entity_id]"},
    )
    incoming_transactions: List["TarotTransaction"] = Relationship(
        back_populates="to_entity",
        sa_relationship_kwargs={"foreign_keys": "[TarotTransaction.to_entity_id]"},
    )
    held_cards: List["TarotShard"] = Relationship(back_populates="owner")


# ---------------------------------------------------------
# 4. CAPACITY TRANSACTION LEDGER (immutable)
# ---------------------------------------------------------
class TarotTransaction(SQLModel, table=True):
    """Immutable append-only ledger for capacity (sovereignty) transfers."""
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    from_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    to_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    upright_amount: int = Field(default=0, ge=0)
    reversed_amount: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=utcnow)
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
# 5. WORLD GEOGRAPHY
# ---------------------------------------------------------
class Location(SQLModel, table=True):
    """
    is_safe_zone: Arbiter rejects capacity transfers here.
    is_magic_restricted: GM limits magical outcomes here.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str
    is_safe_zone: bool = Field(default=False)
    is_magic_restricted: bool = Field(default=False)

    occupants: List["SideCharacter"] = Relationship(back_populates="current_location")


# ---------------------------------------------------------
# 6. NARRATIVE CHARACTERS
# ---------------------------------------------------------
class SideCharacter(SQLModel, table=True):
    """Narrative character with energy wallet, location, and persona."""
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
# 7. CHARACTER HISTORY (roleplay memory)
# ---------------------------------------------------------
class CharacterHistory(SQLModel, table=True):
    """
    Append-only event log. event_type allows filtered recall:
    'dialogue' | 'combat' | 'transfer' | 'movement' | 'spell'
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str
    event_description: str
    timestamp: datetime = Field(default_factory=utcnow)

    character_id: int = Field(foreign_key="sidecharacter.id")
    character: SideCharacter = Relationship(back_populates="history_logs")


# ---------------------------------------------------------
# 8. NPC BRAIN (Persona Agent)
# ---------------------------------------------------------
class CharacterPersona(SQLModel, table=True):
    """
    Static personality data injected into the Persona Agent's system prompt.
    tarot_affinity links to the card archetype defining their magic style.
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

    tarot_affinity_id: Optional[int] = Field(default=None, foreign_key="tarotcardlore.id")
    tarot_affinity: Optional[TarotCardLore] = Relationship(
        back_populates="affiliated_personas"
    )


# ---------------------------------------------------------
# 9. TAROT SHARD INVENTORY (physical card ownership)
#    Loadout enforced at service layer:
#    - Max 1 Major Arcana
#    - Max 2 Minor Arcana
# ---------------------------------------------------------
class TarotShard(SQLModel, table=True):
    """
    A physical Tarot card held by an entity.
    energy_type and value are gone — abilities on the card define those.
    lore_id is mandatory (normalized, no arcana_name string).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)

    owner_id: int = Field(foreign_key="tarotentity.id")
    owner: Optional[TarotEntity] = Relationship(back_populates="held_cards")

    lore_id: int = Field(foreign_key="tarotcardlore.id")
    lore: Optional[TarotCardLore] = Relationship(back_populates="affiliated_shards")


# ---------------------------------------------------------
# 10. CARD OWNERSHIP LEDGER (mandatory)
# ---------------------------------------------------------
class TarotCardTransaction(SQLModel, table=True):
    """Immutable ledger tracking every card ownership change."""
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    shard_id: int = Field(foreign_key="tarotshard.id")
    from_entity_id: int = Field(foreign_key="tarotentity.id")
    to_entity_id: int = Field(foreign_key="tarotentity.id")
    timestamp: datetime = Field(default_factory=utcnow)
    reason: str


# ---------------------------------------------------------
# 11. ABILITY SYSTEM
# ---------------------------------------------------------
class TarotAbility(SQLModel, table=True):
    """
    A spell or action unlocked by holding a specific Tarot card.
    Costs mana of the given energy_type when cast.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    mana_cost: int = Field(ge=0)
    energy_type: str = Field(regex="^(upright|reversed)$")
    tags: Optional[str] = Field(default=None, regex=r"^[a-z0-9\-]+(,[a-z0-9\-]+)*$")
    ability_category: str = Field(default="combat", regex="^(combat|utility|passive)$")

    card_id: int = Field(foreign_key="tarotcardlore.id")
    card: Optional[TarotCardLore] = Relationship(back_populates="abilities")
