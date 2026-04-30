"""
seed_elaris.py — Seeds Elaris Hollow starting area, NPCs, and tutorial quests.
Run once after all migrations:
    uv run python seed_elaris.py

Idempotent — skips existing rows by name.
"""
from __future__ import annotations

from app.db.database import create_db_and_tables, get_session
from app.db.models import (
    Location, Quest, SideCharacter,
)
from sqlmodel import Session, select


# ── ELARIS HOLLOW SUB-LOCATIONS ───────────────────────────────────────────────
LOCATIONS = [
    {
        "name": "Elaris Hollow",
        "description": (
            "A quiet village nestled between rolling hills and the edge of an old forest. "
            "Smoke curls from chimneys. Locals go about their routines with a wariness "
            "that suggests the world beyond the hollow is rarely kind."
        ),
        "x": 10.0, "y": 10.0, "radius": 200.0,
        "is_safe_zone": True, "is_magic_restricted": False,
        "location_type": "town",
    },
    {
        "name": "Broken Lantern Inn",
        "description": (
            "A low-beamed inn that smells of pine resin and old ale. "
            "The innkeeper keeps everything in careful order. "
            "Travelers say it is the safest night's sleep within a day's walk."
        ),
        "x": 10.5, "y": 10.2, "radius": 20.0,
        "is_safe_zone": True, "is_magic_restricted": False,
        "location_type": "town",
    },
    {
        "name": "Old Well Square",
        "description": (
            "The centre of Elaris Hollow. An ancient stone well sits at the middle, "
            "its rope worn smooth by generations. Merchants set up modest stalls here "
            "and locals gather to trade gossip as freely as coin."
        ),
        "x": 10.0, "y": 10.5, "radius": 30.0,
        "is_safe_zone": True, "is_magic_restricted": False,
        "location_type": "town",
    },
    {
        "name": "Whispering Forest Edge",
        "description": (
            "Where the village ends and the forest begins. The trees here are old — "
            "their canopies press close and swallow sound. "
            "The locals avoid it after dusk without good reason."
        ),
        "x": 8.0, "y": 10.0, "radius": 80.0,
        "is_safe_zone": False, "is_magic_restricted": False,
        "location_type": "neutral",
    },
    {
        "name": "Ruins of Velkar",
        "description": (
            "Crumbled stone walls half-consumed by roots and time. "
            "Whatever stood here before has been mostly forgotten. "
            "Scholars say it was once a watchtower. "
            "Something about it makes the air feel different — older."
        ),
        "x": 12.0, "y": 8.0, "radius": 60.0,
        "is_safe_zone": False, "is_magic_restricted": False,
        "location_type": "dungeon",
    },
    {
        "name": "Abandoned Shrine",
        "description": (
            "A small shrine at the edge of the hollow, no longer maintained. "
            "The carvings on its stone face are Tarot symbols — worn but legible. "
            "An old woman often sits here in silence. No one knows her name."
        ),
        "x": 9.0, "y": 11.5, "radius": 15.0,
        "is_safe_zone": True, "is_magic_restricted": True,
        "location_type": "neutral",
    },
]

# ── STARTER NPCs ──────────────────────────────────────────────────────────────
NPCS = [
    {
        "name": "Maren",
        "position": "innkeeper",         # personality encoded in position field
        "current_status": "calm, practical, observant — introduces housing system",
        "location_name": "Broken Lantern Inn",
    },
    {
        "name": "Callum",
        "position": "merchant",
        "current_status": "opportunistic, gregarious, anxious — introduces economy system",
        "location_name": "Old Well Square",
    },
    {
        "name": "Captain Oren",
        "position": "guard captain",
        "current_status": "strict, direct, brief — introduces combat system",
        "location_name": "Whispering Forest Edge",
    },
    {
        "name": "The Old Seer",
        "position": "seer",
        "current_status": "cryptic, unhurried, unsettling — foreshadows dreamscape",
        "location_name": "Abandoned Shrine",
    },
]

# ── TUTORIAL QUEST CHAIN ─────────────────────────────────────────────────────
TUTORIAL_QUESTS = [
    {
        "name": "The Merchant's Lost Box",
        "description": (
            "Callum, the merchant at Old Well Square, left a small lockbox of trade samples "
            "at the Whispering Forest Edge during last night's confusion. "
            "He needs it back. It is a short errand — probably."
        ),
        "quest_type": "tutorial",
        "difficulty": "easy",
        "required_level": 1,
        "xp_reward": 80,
        "phase": 3,
    },
    {
        "name": "Something in the Brush",
        "description": (
            "A Hollow Stalker has been lurking near the forest edge, emboldened by the dark. "
            "Captain Oren has marked it as a threat. "
            "This is not optional — but it is manageable."
        ),
        "quest_type": "tutorial",
        "difficulty": "easy",
        "required_level": 1,
        "xp_reward": 120,
        "phase": 4,
    },
    {
        "name": "A Night Under Roof",
        "description": (
            "Night is coming. Maren at the Broken Lantern has a room available. "
            "It is not expensive. It is safe."
        ),
        "quest_type": "tutorial",
        "difficulty": "easy",
        "required_level": 1,
        "xp_reward": 50,
        "phase": 7,
    },
    {
        "name": "The Ruins at the Edge",
        "description": (
            "The Ruins of Velkar sit at the eastern edge of the hollow. "
            "No one goes there much anymore. "
            "That does not mean there is nothing to find."
        ),
        "quest_type": "tutorial",
        "difficulty": "easy",
        "required_level": 1,
        "xp_reward": 150,
        "phase": 9,
    },
]


# ── SEEDER ────────────────────────────────────────────────────────────────────
def _get_or_create_location(session: Session, data: dict) -> Location:
    loc = session.exec(
        select(Location).where(Location.name == data["name"])
    ).first()
    if not loc:
        loc = Location(
            name=data["name"],
            description=data["description"],
            x=data["x"], y=data["y"], radius=data["radius"],
            is_safe_zone=data["is_safe_zone"],
            is_magic_restricted=data["is_magic_restricted"],
            location_type=data["location_type"],
        )
        session.add(loc)
        session.flush()
        print(f"    Created location: {data['name']}")
    return loc


def seed_elaris(session: Session) -> None:
    print("\n  Seeding Elaris Hollow locations...")
    location_map: dict[str, Location] = {}
    for loc_data in LOCATIONS:
        loc = _get_or_create_location(session, loc_data)
        location_map[loc.name] = loc
    session.commit()

    print("  Seeding starter NPCs...")
    for npc_data in NPCS:
        existing = session.exec(
            select(SideCharacter).where(SideCharacter.name == npc_data["name"])
        ).first()
        if not existing:
            loc = location_map.get(npc_data["location_name"])
            npc = SideCharacter(
                name=npc_data["name"],
                position=npc_data["position"],
                current_status=npc_data["current_status"],
                location_id=loc.id if loc else None,
            )
            session.add(npc)
            print(f"    Created NPC: {npc_data['name']} @ {npc_data['location_name']}")
    session.commit()

    print("  Seeding tutorial quest chain...")
    for q_data in TUTORIAL_QUESTS:
        existing = session.exec(
            select(Quest).where(Quest.name == q_data["name"])
        ).first()
        if not existing:
            q = Quest(
                name=q_data["name"],
                description=q_data["description"],
                quest_type=q_data["quest_type"],
                difficulty=q_data["difficulty"],
                required_level=q_data["required_level"],
                xp_reward=q_data["xp_reward"],
            )
            session.add(q)
            print(f"    Created quest: {q_data['name']}")
    session.commit()
    print("  Elaris Hollow seeded successfully.\n")


def main() -> None:
    print("=" * 60)
    print("  Elaris Hollow Seeder — AI RPG Starting Experience")
    print("=" * 60)
    create_db_and_tables()
    with get_session() as session:
        seed_elaris(session)


if __name__ == "__main__":
    main()
