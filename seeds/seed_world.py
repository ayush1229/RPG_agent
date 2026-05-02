"""
seed_world.py — World structure + main questline seeder.
Run AFTER seed.py:
    uv run python seed_world.py
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from __future__ import annotations
import json
from app.db.database import create_db_and_tables, get_session
from app.db.models import (
    CharacterPersona, InventoryItem, Location, Quest,
    SideCharacter, TarotCardLore, TarotEntity,
)
from sqlmodel import select, Session

# ── MAJOR KINGDOMS ────────────────────────────────────────────────────────────
MAJOR_KINGDOMS = [
    {"name": "Aurelion",    "description": "Kingdom of light and order, ruled from the Radiant Throne.",
     "x": 100.0, "y": 100.0, "location_type": "major_kingdom",
     "ruler_name": "King Valen Solis",   "ruler_position": "Sovereign King of Aurelion",
     "ruler_status": "Ruling from the Radiant Throne, maintaining solar order across the realm",
     "ruler_card": "The Sun",
     "motivation": "Illuminate every corner of the world; darkness is merely absence of will",
     "hidden_secret": "His radiance is artificial — he siphons energy from a hidden Arcana wellspring",
     "speaking_style": "Regal, inspiring, every sentence a proclamation",
     "risk": 35, "loyalty": 85, "aggression": 40,
     "legendary_name": "Crown of the Sun",
     "legendary_desc": "A crown that amplifies solar upright energy — grants the wearer immunity to darkness effects.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "The Radiant Throne"},

    {"name": "Noctyra",    "description": "Shadow kingdom of illusions. Truth is always a veil here.",
     "x": -100.0, "y": 100.0, "location_type": "major_kingdom",
     "ruler_name": "Queen Velka Nyx",    "ruler_position": "Sovereign Queen of Noctyra",
     "ruler_status": "Weaving illusions from her obsidian palace, watching all who enter",
     "ruler_card": "The Moon",
     "motivation": "Control through perception — if she shapes what people see, she shapes reality",
     "hidden_secret": "She herself cannot distinguish illusion from reality anymore",
     "speaking_style": "Whispering, indirect, every statement deniable",
     "risk": 55, "loyalty": 40, "aggression": 50,
     "legendary_name": "Veil of the Moon",
     "legendary_desc": "Cloak woven from reversed Moon energy — renders the wearer invisible to magical detection.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Shadows That Breathe"},

    {"name": "Tharros",    "description": "An empire built on war and authority. Strength is the only law.",
     "x": 0.0, "y": 200.0, "location_type": "major_kingdom",
     "ruler_name": "Emperor Dain Varkos", "ruler_position": "Emperor of Tharros",
     "ruler_status": "Commanding seven legions; currently subjugating borderland tribes",
     "ruler_card": "The Emperor",
     "motivation": "Order through conquest — chaos is the enemy and every battle is a surgery",
     "hidden_secret": "He fears he has already lost the mandate of heaven; his iron grip is panic",
     "speaking_style": "Blunt military commands, no qualifiers, speaks in edicts",
     "risk": 20, "loyalty": 70, "aggression": 90,
     "legendary_name": "Scepter of Dominion",
     "legendary_desc": "Amplifies command-type abilities — nearby entities feel compelled to obey the wielder.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Iron Rule"},

    {"name": "Sylvaris",   "description": "Living forest kingdom where trees are older than memory.",
     "x": -200.0, "y": 0.0, "location_type": "major_kingdom",
     "ruler_name": "Archdruid Kaelis Thorn", "ruler_position": "Archdruid of Sylvaris",
     "ruler_status": "Communing with the root network, sensing every footstep in the forest",
     "ruler_card": "The Empress",
     "motivation": "Let the world grow uninterrupted; civilisation is a wound on the land",
     "hidden_secret": "She is merging with the World Tree — within a century she will no longer be human",
     "speaking_style": "Seasonal metaphors, unhurried, speaks as though the forest is listening",
     "risk": 40, "loyalty": 80, "aggression": 20,
     "legendary_name": "Heartseed Core",
     "legendary_desc": "A living seed from the World Tree — heals 500 HP instantly when consumed; regrows over decades.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Roots of Eternity"},

    {"name": "Pyrosia",    "description": "A nation of ash and forge. Everything is fuel.",
     "x": 200.0, "y": 0.0, "location_type": "major_kingdom",
     "ruler_name": "Warlord Ignar Rex",  "ruler_position": "Warlord of Pyrosia",
     "ruler_status": "Overseeing the great forges, planning the next campaign of destruction",
     "ruler_card": "The Tower",
     "motivation": "Burn the old world to make room for something stronger — creation requires destruction",
     "hidden_secret": "He secretly preserves ancient libraries before burning each city he conquers",
     "speaking_style": "Loud, passionate, speaks of destruction as a lover speaks of a muse",
     "risk": 95, "loyalty": 30, "aggression": 95,
     "legendary_name": "Ember Core Blade",
     "legendary_desc": "A sword forged from a collapsed Tower-energy node — deals +200 base damage; shatters on legendary kills.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Ashes of the Old World"},

    {"name": "Cryon Vale", "description": "Frozen tundra kingdom of stillness and perfect preservation.",
     "x": 0.0, "y": -200.0, "location_type": "major_kingdom",
     "ruler_name": "Lady Seraphine Frost", "ruler_position": "Lady Sovereign of Cryon Vale",
     "ruler_status": "Maintaining the Great Stasis that keeps the kingdom frozen in perfect form",
     "ruler_card": "The Hanged Man",
     "motivation": "Perfection through preservation — nothing should change until it is ready",
     "hidden_secret": "She has not aged in 400 years and cannot die; she is exhausted of existence",
     "speaking_style": "Measured, glacial calm, finishes every sentence regardless of interruption",
     "risk": 10, "loyalty": 90, "aggression": 15,
     "legendary_name": "Frostbound Sigil",
     "legendary_desc": "A rune that freezes time for one target for 3 turns — single use, cannot be replicated.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Stillness Eternal"},

    {"name": "Zephyros",   "description": "Sky-nation of wind-riders — borders are irrelevant, movement is sacred.",
     "x": -100.0, "y": -200.0, "location_type": "major_kingdom",
     "ruler_name": "Highwind Arkan",     "ruler_position": "Highwind of Zephyros",
     "ruler_status": "Patrolling the upper wind-lanes, enforcing freedom of movement",
     "ruler_card": "The Chariot",
     "motivation": "Speed is truth — anything that cannot move freely is already dead",
     "hidden_secret": "He is dying; his body cannot keep pace with the speeds his mind demands",
     "speaking_style": "Rapid-fire, impatient, cuts sentences short, always in motion",
     "risk": 80, "loyalty": 60, "aggression": 70,
     "legendary_name": "Wings of the Chariot",
     "legendary_desc": "Winged armour that doubles movement speed and grants flight for 10 turns per battle.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Unbound Skies"},

    {"name": "Umbrath",    "description": "A kingdom consumed by reversed energy — reality frays at the edges here.",
     "x": 100.0, "y": -200.0, "location_type": "major_kingdom",
     "ruler_name": "The Bound Sovereign", "ruler_position": "Sovereign of Umbrath",
     "ruler_status": "Chained in the Deep Sanctum, radiating corruption that warps the kingdom",
     "ruler_card": "The Devil",
     "motivation": "Break every chain — including the ones holding reality together",
     "hidden_secret": "The chains are self-imposed; the Sovereign is too afraid to act freely",
     "speaking_style": "Paradoxical, inverts meaning, speaks in chains-and-freedom metaphors",
     "risk": 100, "loyalty": 10, "aggression": 80,
     "legendary_name": "Abyssal Chain",
     "legendary_desc": "A chain that binds a target's energy — prevents mana regeneration for 5 turns.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "Chains Below Reality"},

    {"name": "Solmara",    "description": "Desert kingdom of fate-readers — probability is the only currency.",
     "x": 200.0, "y": -100.0, "location_type": "major_kingdom",
     "ruler_name": "Oracle Zareth",      "ruler_position": "Oracle-Sovereign of Solmara",
     "ruler_status": "Reading the Probability Cascades, adjusting events to prevent catastrophic futures",
     "ruler_card": "The Wheel of Fortune",
     "motivation": "Maintain the optimal probability tree — the best future requires constant gardening",
     "hidden_secret": "She does not read fate; she alters it by making people believe she can read it",
     "speaking_style": "Cheerful fatalism, references events before they happen, speaks in probabilities",
     "risk": 75, "loyalty": 30, "aggression": 40,
     "legendary_name": "Wheel Fragment",
     "legendary_desc": "A shard of the Cosmic Wheel — once per session, reroll any combat outcome.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "The Turning Sands"},

    {"name": "Astryx",     "description": "Floating citadel of arcane scholars — knowledge is weaponised here.",
     "x": -200.0, "y": -100.0, "location_type": "major_kingdom",
     "ruler_name": "Grand Arcanist Lume", "ruler_position": "Grand Arcanist of Astryx",
     "ruler_status": "Completing the Codex Prime — a document containing every known magical law",
     "ruler_card": "The Magician",
     "motivation": "Complete understanding of all arcane systems — ignorance is the only true enemy",
     "hidden_secret": "The Codex Prime, when completed, will give him the power to rewrite the rules of magic",
     "speaking_style": "Precise, technical, corrects everyone, treats conversation as data exchange",
     "risk": 35, "loyalty": 25, "aggression": 55,
     "legendary_name": "Codex Prime",
     "legendary_desc": "A tome of all magical laws — reading it for 1 hour unlocks any ability the reader has seen used.",
     "legendary_rarity": "legendary", "legendary_value": 50000,
     "quest_anchor": "The Final Equation"},
]

# ── MINOR KINGDOMS ────────────────────────────────────────────────────────────
MINOR_KINGDOM_NAMES = [
    "Virell", "Karthos", "Eldmere", "Brakkar", "Lythra",
    "Morvain", "Drenfall", "Iskrel", "Halvorn", "Nythera",
    "Valmere", "Ostrix", "Qyros", "Fenloch", "Ardent Hollow",
]

MINOR_KINGDOM_DESCS = [
    "A river-trade hub with contested borders.",
    "Rocky highlands ruled by mercenary clans.",
    "Ancient ruins settlement, scholars flock here.",
    "Mining colony rich in arcane ore.",
    "Coastal fishing villages with deep sea mysteries.",
    "Swamp region, home to reclusive alchemists.",
    "Crossroads town, neutral in all conflicts.",
    "Island chain, pirate-governed.",
    "Northern fortress-town, last bastion before the tundra.",
    "Underground cave-city lit by bioluminescent fungi.",
    "Farming plains, breadbasket of the region.",
    "Desert outpost, smugglers' paradise.",
    "Forest border-town, tense relationship with Sylvaris.",
    "Fog-shrouded bog village, superstitious locals.",
    "Volcanic foothills, refugees from Pyrosia.",
]

# ── MAIN QUESTLINE (26 quests across 7 arcs) ─────────────────────────────────
MAIN_QUESTS = [
    # ── Prologue (Quest 0) ──────────────────────────────────────────────────
    {"name": "The Council Beyond Reality",
     "description": (
         "You awaken in a void. Five Major Arcana manifest: The Fool, The Magician, "
         "The High Priestess, The Emperor, The Star. They speak of energy imbalance, "
         "rising Sovereigns, and your existence as an anomaly. Answer their questions "
         "honestly — your answers will shape your starting alignment and first card draw."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 1,
     "xp_reward": 0,  # prologue; XP via arc 1
     "arc": 0, "sequence": 0},

    # ── Arc 1: Awakening ────────────────────────────────────────────────────
    {"name": "The First Spark",
     "description": (
         "Survive the initial energy anomaly. Learn to cast your first spell using "
         "cast_spell. Reach the nearest settlement alive."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 1,
     "xp_reward": 200, "arc": 1, "sequence": 1},

    {"name": "Fragments of Fate",
     "description": (
         "Acquire your first Tarot shard. Understand the difference between upright "
         "and reversed energy. Use an ability at least once in the field."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 1,
     "xp_reward": 300, "arc": 1, "sequence": 2},

    {"name": "Unstable Currents",
     "description": (
         "Defeat your first hostile NPC in combat. Experience the damage and healing "
         "mechanics first-hand. Survive the encounter."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 2,
     "xp_reward": 400, "arc": 1, "sequence": 3},

    {"name": "Echoes in the Crowd",
     "description": (
         "Interact meaningfully with at least 3 NPCs. Your conversations will trigger "
         "the first dynamically generated side quest."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 3,
     "xp_reward": 300, "arc": 1, "sequence": 4},

    # ── Arc 2: Foundation ───────────────────────────────────────────────────
    {"name": "The Hidden Economy",
     "description": (
         "Learn how the global energy distribution works. Identify a high-energy NPC "
         "in your region and observe their capabilities."
     ),
     "quest_type": "main", "difficulty": "easy", "required_level": 10,
     "xp_reward": 500, "arc": 2, "sequence": 5},

    {"name": "Trial of Balance",
     "description": (
         "Use both upright and reversed abilities in a single encounter. Experience "
         "the alignment penalty for off-element casting first-hand."
     ),
     "quest_type": "main", "difficulty": "medium", "required_level": 12,
     "xp_reward": 700, "arc": 2, "sequence": 6},

    {"name": "The Broken Card",
     "description": (
         "A damaged Tarot shard has been located. Retrieve it through a multi-step "
         "quest chain. Restore it to working condition via an NPC artificer."
     ),
     "quest_type": "main", "difficulty": "medium", "required_level": 15,
     "xp_reward": 900, "arc": 2, "sequence": 7},

    {"name": "Watcher in Silence",
     "description": (
         "Encounter your first elite-tier NPC — not a Sovereign, but close. "
         "Survival is the objective. Victory is optional but rewarded."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 20,
     "xp_reward": 1200, "arc": 2, "sequence": 8},

    # ── Arc 3: Conflict ─────────────────────────────────────────────────────
    {"name": "Whispers of Sovereignty",
     "description": (
         "The word 'Sovereign' surfaces in rumour. Research what a Sovereign is, "
         "trace energy flows back to their source, and identify one active Sovereign."
     ),
     "quest_type": "main", "difficulty": "medium", "required_level": 25,
     "xp_reward": 1500, "arc": 3, "sequence": 9},

    {"name": "Lines of Control",
     "description": (
         "Enter a contested territory where energy distortion warps reality. "
         "Navigate the zone and survive its hazards."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 28,
     "xp_reward": 1800, "arc": 3, "sequence": 10},

    {"name": "First Rival",
     "description": (
         "A rival entity carrying a similar Tarot shard has targeted you. "
         "Defeat them in direct combat."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 32,
     "xp_reward": 2200, "arc": 3, "sequence": 11},

    {"name": "Fractured Allegiance",
     "description": (
         "A faction war is brewing. Choose your side: ally with an existing power "
         "structure or actively oppose it. This decision persists and shapes Arc 4."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 37,
     "xp_reward": 2500, "arc": 3, "sequence": 12},

    # ── Arc 4: Ascent Begins ────────────────────────────────────────────────
    {"name": "Gather the Fragments",
     "description": (
         "Collect 3 to 5 Tarot shards. Reach a mid-tier power threshold that makes "
         "you visible to Sovereigns for the first time."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 40,
     "xp_reward": 3000, "arc": 4, "sequence": 13},

    {"name": "The Controlled Collapse",
     "description": (
         "A Tower-type energy event is destabilising a region. Survive the collapse "
         "without losing your shard collection."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 45,
     "xp_reward": 3500, "arc": 4, "sequence": 14},

    {"name": "Echo of the Sovereign",
     "description": (
         "Face a Sovereign directly — combat or negotiation, your choice. "
         "Survival is the minimum requirement. Victory earns additional rewards."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 50,
     "xp_reward": 5000, "arc": 4, "sequence": 15},

    {"name": "Claim of Presence",
     "description": (
         "Assert control over a minor region. Establish yourself as a power actor. "
         "This grants a passive energy bonus going forward."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 55,
     "xp_reward": 4000, "arc": 4, "sequence": 16},

    # ── Arc 5: Dominion ─────────────────────────────────────────────────────
    {"name": "War of Arcana",
     "description": (
         "Two Sovereigns are in open conflict. Choose which side to support "
         "— or exploit both. Participate in the war's decisive engagement."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 60,
     "xp_reward": 6000, "arc": 5, "sequence": 17},

    {"name": "Shattered Authority",
     "description": (
         "A high-tier elite NPC (mini-boss) has consolidated power in a region "
         "you need. Defeat them to claim their territory."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 65,
     "xp_reward": 7000, "arc": 5, "sequence": 18},

    {"name": "Core Resonance",
     "description": (
         "Synchronise fully with your dominant energy type. "
         "This unlocks advanced scaling bonuses and reveals your Arcana affinity."
     ),
     "quest_type": "main", "difficulty": "hard", "required_level": 70,
     "xp_reward": 6000, "arc": 5, "sequence": 19},

    {"name": "Breaking the Threshold",
     "description": (
         "Accumulate 25% of a single card's total energy pool. "
         "This marks you as a legitimate challenger to Sovereign status."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 75,
     "xp_reward": 8000, "arc": 5, "sequence": 20},

    # ── Arc 6: Pre-Ascension ────────────────────────────────────────────────
    {"name": "The Hidden Sovereigns",
     "description": (
         "Intelligence suggests some Sovereigns are dormant, hidden, or in disguise. "
         "Discover at least two hidden Sovereigns and their locations."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 80,
     "xp_reward": 9000, "arc": 6, "sequence": 21},

    {"name": "Unstable Balance",
     "description": (
         "A catastrophic energy imbalance event is underway. "
         "Stabilise or deliberately disrupt it — both paths lead forward."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 85,
     "xp_reward": 9500, "arc": 6, "sequence": 22},

    {"name": "The Final Rival",
     "description": (
         "A near-sovereign entity has emerged as your direct rival. "
         "Defeat or demonstrably surpass them in power and influence."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 90,
     "xp_reward": 10000, "arc": 6, "sequence": 23},

    # ── Arc 7: Ascension ────────────────────────────────────────────────────
    {"name": "Threshold of Power",
     "description": (
         "Reach level 100. Achieve the required energy control (>25% of a card pool). "
         "The world recognises you as a pre-Sovereign force."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 95,
     "xp_reward": 12000, "arc": 7, "sequence": 24},

    {"name": "Sovereign Trial",
     "description": (
         "Challenge a full Sovereign in their domain. Defeat them in direct combat "
         "or outmaneuver them politically. Prove absolute dominance over one Arcana."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 98,
     "xp_reward": 15000, "arc": 7, "sequence": 25},

    {"name": "Ascension",
     "description": (
         "Claim more than 50% of a Major Arcana card's energy pool. "
         "Become an Arcana Sovereign. The world state changes permanently. "
         "Endgame systems unlock. You are now one of the most powerful forces in existence."
     ),
     "quest_type": "main", "difficulty": "elite", "required_level": 100,
     "xp_reward": 20000, "arc": 7, "sequence": 26},
]

# ── SEEDER ────────────────────────────────────────────────────────────────────

def _upsert_location(session: Session, name: str, **kwargs) -> Location:
    loc = session.exec(select(Location).where(Location.name == name)).first()
    if loc:
        return loc
    loc = Location(name=name, **kwargs)
    session.add(loc)
    session.flush()
    return loc


def _upsert_quest(session: Session, name: str, **kwargs) -> Quest:
    q = session.exec(select(Quest).where(Quest.name == name)).first()
    if q:
        return q
    q = Quest(name=name, **kwargs)
    session.add(q)
    session.flush()
    return q


def seed_kingdoms(session: Session) -> None:
    print("  Seeding 10 major kingdoms...")
    for k in MAJOR_KINGDOMS:
        loc = _upsert_location(
            session, k["name"],
            description=k["description"],
            x=k["x"], y=k["y"],
            location_type=k["location_type"],
            is_safe_zone=False,
            is_magic_restricted=False,
        )

        # Ruler entity
        ruler_entity_name = f"[RULER] {k['ruler_name']}"
        entity = session.exec(
            select(TarotEntity).where(TarotEntity.entity_name == ruler_entity_name)
        ).first()
        if not entity:
            entity = TarotEntity(
                entity_name=ruler_entity_name,
                upright_capacity=1_000_000,
                reversed_capacity=500_000,
                current_upright_mana=1000,
                current_reversed_mana=500,
                current_health=5000,
                level=60,
                damage_bonus=30,
                damage_reduction=20,
            )
            session.add(entity)
            session.flush()

        # SideCharacter ruler
        ruler = session.exec(
            select(SideCharacter).where(SideCharacter.name == k["ruler_name"])
        ).first()
        if not ruler:
            ruler = SideCharacter(
                name=k["ruler_name"],
                position=k["ruler_position"],
                current_status=k["ruler_status"],
                tarot_entity_id=entity.id,
                location_id=loc.id,
            )
            session.add(ruler)
            session.flush()

        # CharacterPersona
        if ruler.persona is None:
            lore = session.exec(
                select(TarotCardLore).where(TarotCardLore.name == k["ruler_card"])
            ).first()
            persona = CharacterPersona(
                motivation=k["motivation"],
                hidden_secret=k["hidden_secret"],
                speaking_style=k["speaking_style"],
                risk_tolerance=k["risk"],
                loyalty=k["loyalty"],
                aggression=k["aggression"],
                character_id=ruler.id,
                tarot_affinity_id=lore.id if lore else None,
            )
            session.add(persona)

        # Legendary item (world template — owner_id = ruler entity, quantity=1)
        existing_leg = session.exec(
            select(InventoryItem).where(InventoryItem.name == k["legendary_name"])
        ).first()
        if not existing_leg:
            leg = InventoryItem(
                owner_id=entity.id,
                name=k["legendary_name"],
                description=k["legendary_desc"],
                item_type="artifact",
                rarity=k["legendary_rarity"],
                value=k["legendary_value"],
                quantity=1,
            )
            session.add(leg)

    print("  Seeding 15 minor kingdoms...")
    for i, name in enumerate(MINOR_KINGDOM_NAMES):
        _upsert_location(
            session, name,
            description=MINOR_KINGDOM_DESCS[i],
            x=float((i % 5 - 2) * 150),
            y=float(-(i // 5 + 1) * 150),
            location_type="minor_kingdom",
            is_safe_zone=True,
            is_magic_restricted=False,
        )

    session.commit()
    print(f"  Kingdoms committed.")


def seed_main_quests(session: Session) -> None:
    print(f"  Seeding {len(MAIN_QUESTS)} main questline entries...")
    # Strip internal-only keys before inserting
    internal_keys = {"arc", "sequence"}
    for q_data in MAIN_QUESTS:
        clean = {k: v for k, v in q_data.items() if k not in internal_keys}
        _upsert_quest(session, **clean)
    session.commit()
    print("  Main questline committed.")


def main() -> None:
    print("=" * 60)
    print("  World Structure Seeder — AI RPG Tarot System")
    print("=" * 60)
    create_db_and_tables()
    with get_session() as session:
        seed_kingdoms(session)
        seed_main_quests(session)
    print("\n  World structure ready.\n")


if __name__ == "__main__":
    main()
