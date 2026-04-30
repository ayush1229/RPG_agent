

from datetime import datetime, timezone
from math import sqrt
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
    affiliated_personas: List["app.db.models.CharacterPersona"] = Relationship(
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
    - Position is ONLY modified via TarotService.move_entity()
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

    # ── HEALTH ────────────────────────────────────────────
    # current_health is stored; max_health is computed from energy capacity
    current_health: int = Field(default=100, ge=0)

    # ── POSITION ──────────────────────────────────────────────────
    pos_x: float = Field(default=0.0)
    pos_y: float = Field(default=0.0)
    current_location_id: Optional[int] = Field(default=None, foreign_key="location.id")

    # ── DAMAGE MODIFIERS ──────────────────────────────────
    damage_bonus: int = Field(default=0)     # flat bonus to outgoing damage
    damage_reduction: int = Field(default=0) # flat reduction to incoming damage

    # ── SOVEREIGN FLAGS ───────────────────────────────────
    # True when this entity controls >50% of a card's upright/reversed pool.
    # Set by generate_sovereigns.py; enforced by world generation logic only.
    is_upright_sovereign: bool = Field(default=False)
    is_reversed_sovereign: bool = Field(default=False)

    # ── PROGRESSION ───────────────────────────────────────
    level: int = Field(default=1, ge=1, le=100)
    current_xp: int = Field(default=0, ge=0)
    # Flat HP bonus accumulated from level-up rewards (+5 per level)
    health_bonus_from_levels: int = Field(default=0, ge=0)

    # ─────────────────────────────────────────────────────
    # Computed properties (no DB column)
    # ─────────────────────────────────────────────────────

    @property
    def max_upright_mana(self) -> int:
        """Dynamic mana limit: 100 + (capacity ^ 0.9)"""
        return int(100 + (self.upright_capacity ** 0.9))

    @property
    def max_reversed_mana(self) -> int:
        """Dynamic mana limit: 100 + (capacity ^ 0.9)"""
        return int(100 + (self.reversed_capacity ** 0.9))

    @property
    def energy_shard_count(self) -> int:
        """
        Total energy capacity = upright + reversed.
        This is the canonical 'shard count' for power scaling.
        """
        return self.upright_capacity + self.reversed_capacity

    @property
    def max_health(self) -> int:
        """
        Health scales with energy capacity AND level rewards.
          base = 100 + (energy_shard_count * 10)
          + 5 HP per level earned (health_bonus_from_levels)
        """
        return 100 + self.energy_shard_count * 10 + self.health_bonus_from_levels

    @property
    def shard_power_multiplier(self) -> float:
        """
        Power multiplier from energy capacity:
          +5% per energy shard, hard-capped at 1.5x.
        Cap is reached at 10 total energy shards.
        """
        return min(1.5, 1.0 + self.energy_shard_count * 0.05)

    @property
    def dominant_energy(self) -> str:
        """
        Dominant energy alignment based on capacity.
        Upright wins on tie (both equal).
        """
        return "upright" if self.upright_capacity >= self.reversed_capacity else "reversed"

    @property
    def is_dead(self) -> bool:
        """True when health has reached zero."""
        return self.current_health == 0

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
    inventory: List["InventoryItem"] = Relationship(back_populates="owner")
    status_effects: List["StatusEffect"] = Relationship(back_populates="target")
    combat_slots: List["CombatParticipant"] = Relationship(back_populates="entity")


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
# 5. WORLD GEOGRAPHY (spatial)
# ---------------------------------------------------------
class Location(SQLModel, table=True):
    """
    Spatial location with coordinates and radius.
    is_safe_zone: Arbiter rejects capacity transfers here.
    is_magic_restricted: GM limits magical outcomes here.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str

    # Spatial system
    x: float = Field(default=0.0)
    y: float = Field(default=0.0)
    radius: float = Field(default=50.0)   # defines the area's size

    is_safe_zone: bool = Field(default=False)
    is_magic_restricted: bool = Field(default=False)
    # "major_kingdom" | "minor_kingdom" | "dungeon" | "town" | "void" | "neutral"
    location_type: str = Field(default="neutral")
    # If set, completing this main quest invalidates all active events in the region
    region_main_quest_id: Optional[int] = Field(default=None, foreign_key="quest.id")

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
    persona: Optional["app.db.models.CharacterPersona"] = Relationship(back_populates="character")


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
    ability_category: str = Field(default="combat", regex="^(combat|utility|passive|healing)$")
    description: str = Field(default="")

    # ── Combat / healing stats ─────────────────────────────
    base_damage: Optional[int] = Field(default=None, ge=0)
    base_heal: Optional[int] = Field(default=None, ge=0)
    scaling_factor: float = Field(default=1.0)

    # ── AOE ───────────────────────────────────────────────
    is_aoe: bool = Field(default=False)
    aoe_radius: float = Field(default=0.0)  # world-units; 0 = single target

    # ── Status effect trigger ────────────────────────────
    # If set, casting this ability applies the named status to the target
    applies_status: Optional[str] = Field(default=None)  # e.g. "burn", "stun"
    status_duration: int = Field(default=0, ge=0)
    status_value: int = Field(default=0, ge=0)
    status_stackable: bool = Field(default=False)

    card_id: int = Field(foreign_key="tarotcardlore.id")
    card: Optional[TarotCardLore] = Relationship(back_populates="abilities")


# ---------------------------------------------------------
# 12. INVENTORY SYSTEM
# ---------------------------------------------------------
class InventoryItem(SQLModel, table=True):
    """
    An item owned by an entity.

    item_type   : "consumable" | "equipment" | "artifact" | "quest"
    rarity      : "common" | "rare" | "epic" | "legendary"
    item_effect : "heal" | "mana" | "buff" | "damage" | None  (legacy name kept)
    effect_type : mirrors item_effect (preferred going forward)
    effect_value: numeric magnitude
    quantity    : stacks (consumables use one per use; equipment/quest = 1)
    value       : gold/trade value (quest items have value=0, cannot be sold)
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    quantity: int = Field(default=1, ge=0)

    item_type: str = Field(default="consumable")   # consumable|equipment|artifact|quest
    rarity: str = Field(default="common")           # common|rare|epic|legendary
    value: int = Field(default=0, ge=0)             # trade value (quest items = 0)

    # Effect fields
    item_effect: Optional[str] = Field(default=None)
    effect_type: Optional[str] = Field(default=None)
    effect_value: int = Field(default=0, ge=0)

    # ── Economy fields ───────────────────────────────────────────────
    # base_price: canonical gold cost in a neutral market
    # tradable  : quest items and sovereign artifacts are non-tradable
    # durability: None = unbreakable; 0 = broken
    # stackable : if False, each unit must be its own row
    base_price: int = Field(default=0, ge=0)
    tradable: bool = Field(default=True)
    durability: Optional[int] = Field(default=None)
    stackable: bool = Field(default=True)

    owner_id: int = Field(foreign_key="tarotentity.id")
    owner: Optional[TarotEntity] = Relationship(back_populates="inventory")


# ---------------------------------------------------------
# 12b. ARCANA-SPECIFIC COMBAT MODIFIERS
#
# Each Major Arcana card that an entity holds grants a passive
# combat modifier. Keys match TarotCardLore.name exactly.
# All values are small (5–15%) to ensure build diversity without
# breaking combat integrity. Effects do NOT stack (single card each).
# ---------------------------------------------------------
ARCANA_EFFECTS: dict[str, dict[str, float]] = {
    "The Fool":        {"aoe_bonus": 0.05},               # unpredictable chaos burst
    "The Magician":    {"damage_bonus": 0.10},             # precise arcane strike
    "The High Priestess": {"healing_bonus": 0.15},         # deep restorative knowledge
    "The Empress":     {"healing_bonus": 0.10},            # nurturing life force
    "The Emperor":     {"damage_reduction_bonus": 0.10},   # iron-willed defense
    "The Hierophant":  {"healing_bonus": 0.05},            # structured doctrine
    "The Lovers":      {"alignment_penalty_reduction": 0.10},  # harmony across energies
    "The Chariot":     {"speed_bonus": 0.10},              # initiative advantage
    "Strength":        {"damage_bonus": 0.10},             # raw physical power
    "The Hermit":      {"stealth_bonus": 0.10},            # elusive, hard to target
    "Wheel of Fortune": {"aoe_bonus": 0.10},               # fate's wide reach
    "Justice":         {"damage_bonus": 0.05},             # balanced retribution
    "The Hanged Man":  {"healing_bonus": 0.10},            # sacrifice for gain
    "Death":           {"damage_bonus": 0.15},             # lethal transformation
    "Temperance":      {"alignment_penalty_reduction": 0.15}, # perfect balance
    "The Devil":       {"damage_bonus": 0.10},             # raw destructive force
    "The Tower":       {"aoe_bonus": 0.10},                # wide-area devastation
    "The Star":        {"healing_bonus": 0.15},            # celestial restoration
    "The Moon":        {"stealth_bonus": 0.10},            # illusion and misdirection
    "The Sun":         {"damage_bonus": 0.05},             # radiant clarity
    "Judgement":       {"damage_bonus": 0.10},             # decisive reckoning
    "The World":       {"aoe_bonus": 0.10},                # universal reach
}


# ---------------------------------------------------------
# 13. STATUS EFFECT SYSTEM
# ---------------------------------------------------------

# Supported baseline effect types (enforced at service layer)
STATUS_EFFECT_TYPES = frozenset({
    "damage_over_time",   # burn, bleed
    "control",            # stun, slow
    "buff",               # shield
    "debuff",             # weaken
})

# Supported named effects and their canonical type
STATUS_EFFECT_CATALOGUE: dict[str, str] = {
    "burn":    "damage_over_time",
    "bleed":   "damage_over_time",
    "stun":    "control",
    "slow":    "control",
    "shield":  "buff",
    "weaken":  "debuff",
}


class StatusEffect(SQLModel, table=True):
    """
    A timed effect applied to an entity.

    effect_type: "damage_over_time" | "control" | "buff" | "debuff"
    name: "burn" | "bleed" | "stun" | "slow" | "shield" | "weaken"
    value: magnitude (damage per tick for DoT; % reduction for shield; etc.)
    duration: turns remaining — deleted when it reaches 0
    stackable: if False, a second application of the same name REFRESHES duration
               instead of adding a new row
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)

    name: str                        # e.g. "burn"
    effect_type: str                 # "damage_over_time" | "control" | "buff" | "debuff"
    value: int = Field(default=0)   # magnitude
    duration: int = Field(default=1, ge=0)  # turns remaining
    stackable: bool = Field(default=False)

    source_ability_id: Optional[int] = Field(default=None, foreign_key="tarotability.id")
    target_entity_id: int = Field(foreign_key="tarotentity.id")

    target: Optional[TarotEntity] = Relationship(back_populates="status_effects")


# ---------------------------------------------------------
# 14. COMBAT ENGINE
# ---------------------------------------------------------
class CombatState(SQLModel, table=True):
    """
    Tracks the active state of a single combat encounter.
    Separate from GameState — purely mechanical, not narrative.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    is_active: bool = Field(default=True)
    turn_number: int = Field(default=1, ge=1)

    # The entity_id whose turn it currently is
    current_actor_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")

    created_at: datetime = Field(default_factory=utcnow)

    participants: List["CombatParticipant"] = Relationship(back_populates="combat")


class CombatParticipant(SQLModel, table=True):
    """
    Join table linking entities to a CombatState.
    initiative determines action order (higher = acts earlier).
    is_player_side: True for allies, False for enemies.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    combat_id: int = Field(foreign_key="combatstate.id")
    entity_id: int = Field(foreign_key="tarotentity.id")
    initiative: int = Field(default=0)
    is_player_side: bool = Field(default=True)
    is_stunned: bool = Field(default=False)   # set by stun status effect tick

    combat: Optional[CombatState] = Relationship(back_populates="participants")
    entity: Optional[TarotEntity] = Relationship(back_populates="combat_slots")


# ---------------------------------------------------------
# 15. PROGRESSION HELPERS (pure functions — no DB)
# ---------------------------------------------------------

def xp_required(level: int) -> int:
    """
    XP needed to advance FROM 'level' TO 'level+1'.
    Non-linear scaling: level 1 = 100 XP, level 99 = ~99,000 XP.
    """
    return int(100 * (level ** 1.5))


# ---------------------------------------------------------
# 16. QUEST SYSTEM
# ---------------------------------------------------------

DIFFICULTY_XP_MULTIPLIER: dict[str, float] = {
    "easy":   1.0,
    "medium": 1.5,
    "hard":   2.5,
    "elite":  4.0,
}


def calculate_xp_reward(base: int, difficulty: str, player_level: int) -> int:
    """
    Scale quest XP by difficulty and current player level.
    Higher-level players earn more XP from the same quest.

    formula: base * difficulty_multiplier * (1 + player_level * 0.05)
    """
    mult = DIFFICULTY_XP_MULTIPLIER.get(difficulty, 1.0)
    return max(1, int(base * mult * (1 + player_level * 0.05)))


class Quest(SQLModel, table=True):
    """
    A quest definition.  Main-line quests are seeded statically.
    Side quests are generated dynamically by the GM.

    quest_type  : "main" | "side"
    difficulty  : "easy" | "medium" | "hard" | "elite"
    required_level: minimum entity level to accept
    xp_reward   : base XP before difficulty/level scaling
    item_reward_id: optional FK to InventoryItem template (NOT an owned item)
    is_completed: True once any entity has completed it (side quests are per-entity
                  via QuestProgress; main quests share this flag)
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = Field(default="")

    quest_type: str = Field(default="side")    # "main" | "side"
    difficulty: str = Field(default="easy")    # "easy" | "medium" | "hard" | "elite"
    required_level: int = Field(default=1, ge=1)

    xp_reward: int = Field(default=100, ge=0)
    item_reward_id: Optional[int] = Field(default=None, foreign_key="inventoryitem.id")

    is_completed: bool = Field(default=False)

    # Back-populated list of per-entity progress rows
    progress_entries: List["QuestProgress"] = Relationship(back_populates="quest")


class QuestProgress(SQLModel, table=True):
    """
    Per-entity progress on a quest.
    progress / goal tracks how many objectives are completed.
    is_completed is set True when progress >= goal.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)

    quest_id: int = Field(foreign_key="quest.id")
    entity_id: int = Field(foreign_key="tarotentity.id")

    progress: int = Field(default=0, ge=0)
    goal: int = Field(default=1, ge=1)
    is_completed: bool = Field(default=False)

    quest: Optional[Quest] = Relationship(back_populates="progress_entries")


# ---------------------------------------------------------
# 17. USER SESSION PERSISTENCE
# ---------------------------------------------------------

class UserSession(SQLModel, table=True):
    """
    One row per user. Persists player identity and last-known game state
    across Chainlit restarts. Always updated on every interaction.

    user_id      : Chainlit identifier (username or session-id for guests)
    entity_id    : FK to the player's TarotEntity (energy wallet)
    last_location_id  : where the player last was
    last_game_state   : arbitrary JSON string (GM can store scene flags here)
    last_active_quest_id: the quest the player is currently focused on
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    entity_id: int = Field(foreign_key="tarotentity.id")

    last_location_id: Optional[int] = Field(default=None, foreign_key="location.id")
    last_game_state: Optional[str] = Field(default=None)       # JSON blob
    last_active_quest_id: Optional[int] = Field(default=None, foreign_key="quest.id")

    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 18. DIALOGUE LOG (UI replay — NOT sent to LLM raw)
# ---------------------------------------------------------

class DialogueLog(SQLModel, table=True):
    """
    Append-only log of every message for UI replay.
    Never deleted automatically.
    NEVER injected into the LLM directly — only the last N lines and
    the ConversationSummary are used for model context.

    role            : "user" | "assistant"
    chat_session_id : Chainlit session id — groups messages per browser tab/session.
                      Allows a user to start a fresh chat without losing prior history.
                      When None the row belongs to a legacy session (pre-migration).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    chat_session_id: Optional[str] = Field(default=None, index=True)  # Chainlit session id
    role: str                          # "user" | "assistant"
    message: str
    timestamp: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 19. CONVERSATION SUMMARY (compressed long-term memory)
# ---------------------------------------------------------

class ConversationSummary(SQLModel, table=True):
    """
    One row per user. Compressed key facts about past conversation.
    Updated every N messages or after major events.
    Injected into the LLM instead of the full chat log.

    Must include: important decisions, NPC relationships,
    quest progress, major events.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    summary: str = Field(default="No history yet.")
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 20. MAIN STORY STATE  (narrative enforcement)
# ---------------------------------------------------------

# Canonical arc boundaries (inclusive level range)
ARC_LEVEL_RANGES: dict[int, tuple[int, int]] = {
    0: (1,  1),    # Prologue / void council
    1: (1,  10),
    2: (10, 25),
    3: (25, 40),
    4: (40, 60),
    5: (60, 80),
    6: (80, 95),
    7: (95, 100),
}

# Default flags for a brand-new player
DEFAULT_STORY_FLAGS: dict = {
    # Prologue flags
    "interview_done": False,
    "cards_drawn": False,
    "awakening_triggered": False,
    # Arc tracking
    "current_arc": 0,
    # Alignment chosen during interview
    "alignment_tendency": None,   # "order" | "chaos" | "balance"
    # Branching flags (Arc 3 Q12)
    "faction_chosen": None,       # "ally" | "oppose" | None
    # Ascension flags (Arc 7)
    "sovereign_challenged": False,
    "sovereign_defeated": False,
    "ascension_complete": False,
    # GM override permission flag
    "gm_override_allowed": False,
}


class MainStoryState(SQLModel, table=True):
    """
    One row per entity (player). Tracks canonical main-quest progression.

    current_arc       : 0 = prologue, 1-7 = story arcs
    current_quest_id  : FK to the Quest the player is actively on
    flags             : JSON blob — see DEFAULT_STORY_FLAGS for schema

    Enforcement contract:
      The StoryEnforcer reads this BEFORE the GM executes any response.
      If a mandatory prologue step is incomplete, GM is bypassed entirely.
      GM may ONLY alter flags when gm_override_allowed == True.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)
    current_arc: int = Field(default=0, ge=0, le=7)
    current_quest_id: Optional[int] = Field(default=None, foreign_key="quest.id")
    flags: str = Field(default="{}")   # JSON blob — always parse with json.loads
    updated_at: datetime = Field(default_factory=utcnow)


# =============================================================
# WORLD SYSTEMS (Map, Travel, Factions, War, Events)
# =============================================================

# ── Terrain modifiers (used by travel_time formula) ──────────────────────
TERRAIN_MODIFIERS: dict[str, float] = {
    "city":      1.0,
    "town":      1.0,
    "plains":    1.2,
    "forest":    1.5,
    "wild":      1.5,
    "mountain":  2.0,
    "dungeon":   1.8,
    "corrupted": 2.5,
    "void":      3.0,
    "neutral":   1.2,
    "major_kingdom": 1.0,
    "minor_kingdom": 1.1,
}


# ---------------------------------------------------------
# 21. WORLD MAP
# ---------------------------------------------------------
class WorldMap(SQLModel, table=True):
    """
    Top-level named map. All Locations belong to one WorldMap.
    Typically one map per campaign ('The Known World').
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = Field(default="")
    width: float = Field(default=2000.0)    # logical units
    height: float = Field(default=2000.0)


# ---------------------------------------------------------
# 22. TRAVEL STATE
# ---------------------------------------------------------
class TravelState(SQLModel, table=True):
    """
    Active travel journey for one entity.
    One row per entity; replaced when a new journey starts.

    is_completed: True once resolve_travel() has fired.
    terrain_type: used to look up the modifier at journey start.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)

    start_x: float
    start_y: float
    target_x: float
    target_y: float
    target_location_id: Optional[int] = Field(default=None, foreign_key="location.id")

    terrain_type: str = Field(default="plains")   # key into TERRAIN_MODIFIERS
    speed: float = Field(default=1.0, gt=0)        # units per second
    travel_time_seconds: float                     # total journey duration

    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime                              # = start_time + travel_time_seconds
    is_completed: bool = Field(default=False)


# ---------------------------------------------------------
# 23. FACTION
# ---------------------------------------------------------
class Faction(SQLModel, table=True):
    """
    A political entity (usually a kingdom).
    alignment: 'order' | 'chaos' | 'neutral'
    ruler_id: FK to SideCharacter (optional — minor factions may lack a ruler)
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = Field(default="")
    alignment: str = Field(default="neutral")    # order | chaos | neutral
    ruler_id: Optional[int] = Field(default=None, foreign_key="sidecharacter.id")
    home_location_id: Optional[int] = Field(default=None, foreign_key="location.id")


# ---------------------------------------------------------
# 24. FACTION RELATION
# ---------------------------------------------------------
class FactionRelation(SQLModel, table=True):
    """
    Bilateral diplomatic relation between two factions.
    relation: -100 (full war) to +100 (fully allied)
    ≤ -50 → hostile   ≥ +50 → allied   else → neutral
    Canonical form: faction_a_id < faction_b_id (enforced at service layer).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    faction_a_id: int = Field(foreign_key="faction.id", index=True)
    faction_b_id: int = Field(foreign_key="faction.id", index=True)
    relation: int = Field(default=0)   # -100 to +100


# ---------------------------------------------------------
# 25. TERRITORY CONTROL
# ---------------------------------------------------------
class TerritoryControl(SQLModel, table=True):
    """
    Faction control level over a specific location.
    control_value: 0–100 (>50 = controlled)
    Multiple factions can have entries for the same location;
    highest control_value wins.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    faction_id: int = Field(foreign_key="faction.id", index=True)
    control_value: float = Field(default=0.0, ge=0.0, le=100.0)


# ---------------------------------------------------------
# 26. WAR
# ---------------------------------------------------------
class War(SQLModel, table=True):
    """
    Active or historical conflict between two factions.
    A war can only be declared when FactionRelation.relation <= -50.
    War ends when one faction loses majority territorial control
    or a scripted peace event fires.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    faction_a_id: int = Field(foreign_key="faction.id", index=True)
    faction_b_id: int = Field(foreign_key="faction.id", index=True)
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True)
    # Tick accumulator: total delta_seconds processed so far
    total_ticks_seconds: float = Field(default=0.0)


# ---------------------------------------------------------
# 27. SOVEREIGN INFLUENCE
# ---------------------------------------------------------
class SovereignInfluence(SQLModel, table=True):
    """
    A Sovereign's influence over a specific location.
    influence_value: 0–100
    > 70 → location becomes unstable (energy distortion, special enemies)
    Decays at base rate unless Sovereign actively maintains it.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    sovereign_entity_id: int = Field(foreign_key="tarotentity.id", index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    influence_value: float = Field(default=0.0, ge=0.0, le=100.0)
    growth_rate: float = Field(default=1.0)    # units gained per 60 seconds
    decay_rate: float = Field(default=0.5)     # units lost per 60 seconds when not maintained
    last_updated: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 28. WORLD EVENT
# ---------------------------------------------------------
# Supported event types
WORLD_EVENT_TYPES = frozenset({
    "war",        # active military conflict
    "sovereign",  # Sovereign-driven distortion
    "anomaly",    # energy anomaly
    "festival",   # peaceful bonus event
    "siege",      # faction siege on a location
})

EVENT_EFFECTS: dict[str, dict] = {
    "war":       {"spawn_rate": 2.0, "travel_danger": 1.5, "reward_mult": 1.3},
    "sovereign": {"spawn_rate": 2.5, "travel_danger": 2.0, "reward_mult": 1.8},
    "anomaly":   {"spawn_rate": 1.8, "travel_danger": 1.8, "reward_mult": 1.5},
    "festival":  {"spawn_rate": 0.5, "travel_danger": 0.8, "reward_mult": 1.2},
    "siege":     {"spawn_rate": 2.2, "travel_danger": 2.5, "reward_mult": 1.4},
}


class WorldEvent(SQLModel, table=True):
    """
    A time-limited event active at a location.
    duration_seconds: when it reaches 0 the event expires.
    Effects modify spawn rates, travel danger, and reward multipliers.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    event_type: str                                # key into WORLD_EVENT_TYPES
    duration_seconds: float = Field(default=3600.0, gt=0)  # seconds remaining
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_ticked: datetime = Field(default_factory=utcnow)


# =============================================================
# ECONOMY SYSTEMS (Wallet, Shop, Auction, Tax)
# =============================================================

# Rarity → base price multiplier (applied when no explicit base_price set)
RARITY_PRICE_MULT: dict[str, float] = {
    "common":    1.0,
    "rare":      3.0,
    "epic":      8.0,
    "legendary": 25.0,
}

# Shop type → markup factor applied on top of compute_price
SHOP_TYPE_MARKUP: dict[str, float] = {
    "general":      1.0,
    "magic":        1.2,
    "black_market": 1.6,
    "guild":        1.1,
    "trading_hub":  0.9,   # cheapest — Virell Prime hub
}

# Auction hall type → tax rate applied to seller proceeds
AUCTION_TAX: dict[str, float] = {
    "small_hall":        0.08,
    "grand_hall":        0.12,
    "sovereign_exchange": 0.20,
}


# ---------------------------------------------------------
# 29. WALLET
# ---------------------------------------------------------
class Wallet(SQLModel, table=True):
    """
    Gold wallet for any entity (player, NPC merchant, shop owner).
    balance is always non-negative — enforced at service layer.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)
    balance: int = Field(default=0, ge=0)


# ---------------------------------------------------------
# 30. SHOP
# ---------------------------------------------------------
class Shop(SQLModel, table=True):
    """
    A merchant shop anchored to a location.
    shop_type: 'general' | 'magic' | 'black_market' | 'guild' | 'trading_hub'
    tax_rate  : fraction of sale deducted as kingdom tax (default 5%).
    owner_entity_id: the NPC/player entity that receives sold-item proceeds.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    owner_entity_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")
    shop_type: str = Field(default="general")
    tax_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    is_open: bool = Field(default=True)


# ---------------------------------------------------------
# 31. SHOP INVENTORY
# ---------------------------------------------------------
class ShopInventory(SQLModel, table=True):
    """
    Stock of one item inside one shop.
    price_override: if set, supersedes compute_price() for this specific item/shop.
    restock_rate  : units restored per world-tick minute (0 = no restock).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    shop_id: int = Field(foreign_key="shop.id", index=True)
    item_id: int = Field(foreign_key="inventoryitem.id", index=True)
    quantity: int = Field(default=1, ge=0)
    price_override: Optional[int] = Field(default=None)   # None → use compute_price
    restock_rate: float = Field(default=0.0, ge=0.0)      # units per minute


# ---------------------------------------------------------
# 32. AUCTION
# ---------------------------------------------------------
class Auction(SQLModel, table=True):
    """
    A live auction listing.
    hall_type: 'small_hall' | 'grand_hall' | 'sovereign_exchange'
    is_active: False once resolved or cancelled.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    seller_id: int = Field(foreign_key="tarotentity.id", index=True)
    item_id: int = Field(foreign_key="inventoryitem.id")
    quantity: int = Field(default=1, ge=1)

    starting_price: int = Field(ge=1)
    current_bid: int = Field(ge=0)
    highest_bidder_id: Optional[int] = Field(default=None, foreign_key="tarotentity.id")

    location_id: int = Field(foreign_key="location.id")
    hall_type: str = Field(default="small_hall")   # key into AUCTION_TAX
    end_time: datetime
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 33. TAX POLICY
# ---------------------------------------------------------
class TaxPolicy(SQLModel, table=True):
    """
    Per-kingdom (location) tax overrides.
    If no row exists for a location, Shop.tax_rate is used directly.
    trade_tax   : applied to buy/sell transactions in shops.
    auction_tax : applied to auction sale proceeds (overrides AUCTION_TAX default).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", unique=True, index=True)
    trade_tax: float = Field(default=0.05, ge=0.0, le=1.0)
    auction_tax: float = Field(default=0.10, ge=0.0, le=1.0)


# =============================================================
# GUILD SYSTEMS
# =============================================================

# Valid guild types
GUILD_TYPES = frozenset({"combat", "magic", "trade", "shadow", "chaos", "hybrid"})

# Rank tier labels
RANK_TIER: dict[int, str] = {
    1: "Novice", 2: "Novice", 3: "Novice",
    4: "Core Member", 5: "Core Member", 6: "Core Member",
    7: "Elite", 8: "Elite", 9: "Elite",
    10: "Guild Master",
}

# Rank-based perk definitions (read by service layer)
RANK_PERKS: dict[str, list[str]] = {
    "Novice":      ["xp_bonus_5pct", "guild_shop_access"],
    "Core Member": ["xp_bonus_10pct", "item_discount_10pct", "minor_stat_bonus"],
    "Elite":       ["xp_bonus_20pct", "exclusive_ability_slot", "priority_quests"],
    "Guild Master": ["xp_bonus_25pct", "faction_influence", "treasury_control",
                     "guild_decision_vote"],
}

# Exposure thresholds
EXPOSURE_WARNING   = 50.0    # warn player
EXPOSURE_CRITICAL  = 75.0    # GM hinted danger
EXPOSURE_TRIGGERED = 100.0   # forced event fires


# ---------------------------------------------------------
# 34. GUILD
# ---------------------------------------------------------
class Guild(SQLModel, table=True):
    """
    A player/NPC organisation.
    is_secret: hidden guilds — not visible in normal UI, joined via special triggers.
    headquarters_location_id: city/kingdom where the guild HQ is anchored.
    master_id: FK to GuildMembership of the current Guild Master (rank 10).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = Field(default="")
    guild_type: str                                   # key in GUILD_TYPES
    is_secret: bool = Field(default=False)
    headquarters_location_id: Optional[int] = Field(default=None, foreign_key="location.id")
    master_id: Optional[int] = Field(default=None)   # FK to GuildMembership.id (set after)
    # Treasury balance (managed by treasurer)
    treasury: int = Field(default=0, ge=0)


# ---------------------------------------------------------
# 35. GUILD MEMBERSHIP
# ---------------------------------------------------------
class GuildMembership(SQLModel, table=True):
    """
    One row per (entity × guild) pair.
    Dual-membership rules:
      - entity may hold EXACTLY ONE non-secret membership
      - entity may hold EXACTLY ONE secret membership
    Leaving resets reputation to 0 (enforced by leave_guild()).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", index=True)
    guild_id: int = Field(foreign_key="guild.id", index=True)

    rank: int = Field(default=1, ge=1, le=10)
    role: str = Field(default="member")      # member | officer | treasurer | master
    reputation: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)
    joined_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 36. GUILD QUEST
# ---------------------------------------------------------
class GuildQuest(SQLModel, table=True):
    """
    A quest that belongs to a specific guild.
    required_rank: minimum rank needed to accept.
    arc: story arc number (1–5).
    sequence: order within the arc.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guild.id", index=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    required_rank: int = Field(default=1, ge=1, le=10)
    required_level: int = Field(default=1, ge=1)
    xp_reward: int = Field(default=0, ge=0)
    reputation_reward: int = Field(default=50, ge=0)
    arc: int = Field(default=1, ge=1, le=5)
    sequence: int = Field(default=1, ge=1)
    is_repeatable: bool = Field(default=False)


# ---------------------------------------------------------
# 37. GUILD INCOME
# ---------------------------------------------------------
class GuildIncome(SQLModel, table=True):
    """
    Periodic gold distribution from guild treasury to active members.
    amount = base_income * (member_rank / 10)
    distribution_time: when the distribution was processed.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guild.id", index=True)
    recipient_entity_id: int = Field(foreign_key="tarotentity.id", index=True)
    amount: int = Field(default=0, ge=0)
    rank_at_time: int = Field(default=1)
    distribution_time: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 38. GUILD EXPOSURE (secret guild detection)
# ---------------------------------------------------------
class GuildExposure(SQLModel, table=True):
    """
    Tracks how close an entity is to being exposed as a secret guild member.
    exposure_level: 0.0 (unknown) – 100.0 (fully exposed).
    When exposure_level >= EXPOSURE_TRIGGERED (100), trigger_exposure_event() fires.
    Exposure event outcome is MANDATORY (forced loss, all memberships revoked).
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)
    exposure_level: float = Field(default=0.0, ge=0.0, le=100.0)
    last_increased_at: datetime = Field(default_factory=utcnow)
    exposure_triggered: bool = Field(default=False)   # True after event fired


# =============================================================
# RANDOM EVENT SYSTEM
# =============================================================

# Event types
EVENT_TEMPLATE_TYPES = frozenset({
    "combat", "exploration", "escort", "trade", "anomaly",
})

# Rarity tiers
EVENT_RARITY_TIERS = ("common", "uncommon", "rare", "epic")

# Base spawn weights (probabilities out of 100)
BASE_SPAWN_WEIGHTS: dict[str, float] = {
    "common":   60.0,
    "uncommon": 25.0,
    "rare":     10.0,
    "epic":      5.0,
}

# Per-rarity modifier bonuses applied to weights
SPAWN_MODIFIERS: dict[str, dict[str, float]] = {
    "war_zone":       {"rare": +8.0,  "epic": +4.0},
    "sovereign_high": {"epic": +10.0, "rare": +5.0},
    "safe_zone":      {"common": -20.0, "uncommon": -10.0, "rare": -5.0, "epic": -3.0},
    "level_tier_2":   {"rare": +3.0,  "epic": +1.0},   # level 20–39
    "level_tier_3":   {"rare": +6.0,  "epic": +3.0},   # level 40+
}

# Max concurrent active events per location (prevents spam)
MAX_EVENTS_PER_LOCATION = 5

# Difficulty scaling: final = 1 + player_level * factor
DIFFICULTY_SCALE_FACTOR = 0.03


# ---------------------------------------------------------
# 39. EVENT TEMPLATE
# ---------------------------------------------------------
class EventTemplate(SQLModel, table=True):
    """
    Reusable blueprint for a random event category.
    reward_item_pool : JSON array of item name strings for loot rolls.
    requires_war     : only eligible when an active war WorldEvent exists nearby.
    requires_sovereign_influence: only eligible when influence > 50 at location.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = Field(default="")

    event_type: str                         # key in EVENT_TEMPLATE_TYPES
    rarity: str = Field(default="common")   # key in BASE_SPAWN_WEIGHTS

    base_duration_minutes: int = Field(default=60, gt=0)
    min_level: int = Field(default=1, ge=1)
    max_level: Optional[int] = Field(default=None)   # None = no cap

    risk_level: int = Field(default=1, ge=1, le=10)
    reward_base_xp: int = Field(default=100, ge=0)
    reward_item_pool: Optional[str] = Field(default=None)  # JSON array

    requires_war: bool = Field(default=False)
    requires_sovereign_influence: bool = Field(default=False)
    is_active: bool = Field(default=True)  # soft-disable without deleting


# ---------------------------------------------------------
# 40. WORLD EVENT INSTANCE
# ---------------------------------------------------------
class WorldEventInstance(SQLModel, table=True):
    """
    A live spawned event at a location.
    spawned_for_entity_id: None = world-visible; set = personalized to one player.
    difficulty_scaling    = 1 + (player_level * DIFFICULTY_SCALE_FACTOR)
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    template_id: int = Field(foreign_key="eventtemplate.id", index=True)
    location_id: int = Field(foreign_key="location.id", index=True)

    spawned_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime

    is_active: bool = Field(default=True)
    is_completed: bool = Field(default=False)

    spawned_for_entity_id: Optional[int] = Field(
        default=None, foreign_key="tarotentity.id"
    )
    difficulty_scaling: float = Field(default=1.0, gt=0)


# ---------------------------------------------------------
# 41. EVENT QUEST
# ---------------------------------------------------------
class EventQuest(SQLModel, table=True):
    """
    Created when a player accepts a WorldEventInstance (converts to side quest).
    One row per (event_instance × entity) pair.
    is_abandoned: player explicitly gave up — no rewards, event unmarked so others can take it.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    event_instance_id: int = Field(foreign_key="worldeventinstance.id", index=True)
    entity_id: int = Field(foreign_key="tarotentity.id", index=True)

    progress: int = Field(default=0, ge=0)
    goal: int = Field(default=1, ge=1)

    is_completed: bool = Field(default=False)
    is_abandoned: bool = Field(default=False)
    accepted_at: datetime = Field(default_factory=utcnow)


# =============================================================
# TIME / HOUSING / DREAMSCAPE SYSTEMS
# =============================================================

# Day/Night boundary hours (game-time)
NIGHT_START_HOUR: int = 18   # 6 PM
NIGHT_END_HOUR:   int = 6    # 6 AM

# Night risk multiplier — applied to event spawn weights, combat scaling, ambush chance
NIGHT_RISK_MULTIPLIER: float = 1.7

# Default game-day length in real-world seconds
DEFAULT_DAY_LENGTH_SECONDS: float = 24 * 60.0   # 24 real-minutes = 24 game-hours

# Housing types
HOUSING_TYPES = frozenset({"inn", "rented_room", "owned_house"})

# Dreamscape entry base probability (per check)
DREAM_BASE_CHANCE: float = 0.10   # 10%

# Dreamscape location name (must be seeded / created)
DREAMSCAPE_LOCATION_NAME: str = "The Dreamscape"


# ---------------------------------------------------------
# 42. WORLD TIME  (singleton — always id=1)
# ---------------------------------------------------------
class WorldTime(SQLModel, table=True):
    """
    Singleton row (id=1) that tracks the global game clock.

    current_time : authoritative game-world datetime.
    time_scale   : how many game-seconds pass per real-second.
                   Default = 60 → 1 real-minute = 1 game-hour.
    last_real_tick: wall-clock time of the last update (lazy-tick basis).

    is_night() computed in service layer from current_time.hour.
    """
    __table_args__ = {'extend_existing': True}

    id: int = Field(default=1, primary_key=True)
    current_time: datetime = Field(default_factory=utcnow)
    time_scale: float = Field(default=60.0, gt=0)   # game-seconds per real-second
    last_real_tick: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 43. PLAYER HOUSING
# ---------------------------------------------------------
class PlayerHousing(SQLModel, table=True):
    """
    Active housing assignment for a player entity.
    One row per entity; replaced on re-rent / purchase.

    housing_type : "inn" | "rented_room" | "owned_house"
    expires_at   : None for owned houses; set for inn/rental
    is_inside    : True while player is physically inside (safe zone active)
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)
    location_id: int = Field(foreign_key="location.id")

    housing_type: str = Field(default="inn")      # key in HOUSING_TYPES
    is_safe_zone: bool = Field(default=True)
    is_inside: bool = Field(default=False)

    # None = permanent (owned); datetime = rental expiry
    expires_at: Optional[datetime] = Field(default=None)
    rented_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------
# 44. DREAM STATE
# ---------------------------------------------------------
class DreamState(SQLModel, table=True):
    """
    Per-entity Dreamscape progression.

    has_unlocked      : True once the required main quest milestone is reached.
    is_in_dreamscape  : True while player is inside the realm.
    last_entered      : last entry datetime (rate-limit / cooldown check).
    pre_dream_location_id: where to return the entity after dream exit.
    dream_progress_flag: JSON dict for arbitrary narrative flags.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)

    has_unlocked: bool = Field(default=False)
    is_in_dreamscape: bool = Field(default=False)
    last_entered: Optional[datetime] = Field(default=None)

    pre_dream_location_id: Optional[int] = Field(default=None, foreign_key="location.id")
    dream_progress_flag: str = Field(default="{}")   # JSON dict


# =============================================================
# TUTORIAL SYSTEM
# =============================================================

# Tutorial phase constants — gating order enforced by TutorialEnforcer
TUTORIAL_PHASES: dict[int, str] = {
    0:  "not_started",
    1:  "awakening",          # phase 1 — player wakes in Elaris Hollow
    2:  "first_interaction",  # phase 2 — Old Well Square, merchant dialogue
    3:  "first_task",         # phase 3 — retrieve item from forest edge
    4:  "first_combat",       # phase 4 — weak enemy encounter
    5:  "first_reward",       # phase 5 — return item, XP + item reward
    6:  "economy_intro",      # phase 6 — shop buy/sell with merchant
    7:  "housing_intro",      # phase 7 — night approaches, rent inn room
    8:  "night_system",       # phase 8 — night risk live if outside
    9:  "first_dungeon",      # phase 9 — optional Ruins of Velkar run
    10: "dream_hook",         # phase 10 — Old Seer foreshadowing
    11: "complete",           # tutorial finished — all systems unlocked
}

# Systems locked per phase (entity cannot access until phase passed)
TUTORIAL_SYSTEM_LOCKS: dict[str, int] = {
    "guilds":       11,   # only after tutorial completes
    "auctions":     11,
    "war_zones":    11,
    "sovereign":    11,
    "rare_events":  8,    # only from phase 8 onward
    "epic_events":  11,
    "economy":      6,    # unlocks at phase 6
    "housing":      7,    # unlocks at phase 7
    "night_system": 8,
    "dreamscape":   11,
}

# Max event rarity during tutorial phases (enforced by spawn gate)
TUTORIAL_MAX_RARITY: dict[int, str] = {
    phase: "common" for phase in range(1, 9)   # phases 1-8: common only
}
TUTORIAL_MAX_RARITY[9]  = "uncommon"   # dungeon phase: allow uncommon
TUTORIAL_MAX_RARITY[10] = "uncommon"
TUTORIAL_MAX_RARITY[11] = "epic"       # tutorial done: all rarities


# ---------------------------------------------------------
# 45. TUTORIAL STATE
# ---------------------------------------------------------
class TutorialState(SQLModel, table=True):
    """
    Per-entity tutorial progression tracker.
    phase     : current phase index (0 = not started, 11 = complete).
    phase_data: JSON dict for phase-specific flags (e.g. quest_accepted, item_retrieved).
    The TutorialEnforcer reads this before every GM response and injects
    phase-appropriate context overrides.
    """
    __table_args__ = {'extend_existing': True}

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="tarotentity.id", unique=True, index=True)
    phase: int = Field(default=0, ge=0, le=11)
    phase_data: str = Field(default="{}")   # JSON — arbitrary per-phase state
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = Field(default=None)
