"""
seed_guilds.py — Seeds 5 predefined guilds + full questlines (5 arcs each).
Run after seed_world.py:
    uv run python seed_guilds.py
"""
from __future__ import annotations

from app.db.database import create_db_and_tables, get_session
from app.db.guild_service import create_guild
from app.db.models import Guild, GuildQuest
from sqlmodel import Session, select


# ── GUILD DEFINITIONS ─────────────────────────────────────────────────────────
GUILDS = [
    {
        "name": "Order of the Radiant Crown",
        "description": (
            "A militant order devoted to law, order, and the purification of corrupted energy. "
            "Members are trained warriors who serve as the world's judges and enforcers."
        ),
        "guild_type": "combat",
        "is_secret": False,
    },
    {
        "name": "Arcane Conclave",
        "description": (
            "A scholarly collective obsessed with uncovering the fundamental laws of Tarot magic. "
            "Access to forbidden archives is their greatest currency."
        ),
        "guild_type": "magic",
        "is_secret": False,
    },
    {
        "name": "Consortium of Virell",
        "description": (
            "The wealthiest trade network in the known world. "
            "They control supply chains, auction houses, and pricing — invisibly."
        ),
        "guild_type": "trade",
        "is_secret": False,
    },
    {
        "name": "Veil Syndicate",
        "description": (
            "A shadow network of spies, black market operators, and assassins. "
            "They do not exist on any record. Membership is invitation-only."
        ),
        "guild_type": "shadow",
        "is_secret": True,
    },
    {
        "name": "Ashen Circle",
        "description": (
            "A secret brotherhood that worships destruction as a path to transcendence. "
            "They believe the world must burn before it can be reborn."
        ),
        "guild_type": "chaos",
        "is_secret": True,
    },
]


# ── QUESTLINES (5 arcs × 2 quests each = 10 per guild) ───────────────────────
# Format: (name, description, arc, sequence, required_rank, required_level, xp, rep)
GUILD_QUESTS: dict[str, list[tuple]] = {
    "Order of the Radiant Crown": [
        # Arc 1: Initiation — rank 1, level 1–5
        ("Discipline Trials",
         "Prove your combat discipline in a series of controlled bouts against Order initiates.",
         1, 1, 1, 1, 300, 80),
        ("Civilian Escort",
         "Lead a group of civilians through an unstable energy zone to safety.",
         1, 2, 1, 3, 400, 100),
        # Arc 2: Law Enforcement — rank 3, level 10–15
        ("Rogue Shard Hunt",
         "Track and neutralize three rogue shard users operating outside the law.",
         2, 1, 3, 10, 700, 150),
        ("Black Market Suppression",
         "Raid a known black market operation and confiscate restricted items.",
         2, 2, 3, 12, 800, 180),
        # Arc 3: Internal Conflict — rank 5, level 20–25
        ("The Corruption Audit",
         "Investigate senior Order members for suspected energy embezzlement.",
         3, 1, 5, 20, 1200, 220),
        ("Judgment Call",
         "Choose: expose the corrupt officers publicly or handle it internally. Both paths continue.",
         3, 2, 5, 22, 1400, 250),
        # Arc 4: Warfront — rank 7, level 35–40
        ("Field Command",
         "Lead an Order battalion in a major faction war engagement. Capture contested territory.",
         4, 1, 7, 35, 2000, 350),
        ("Territorial Hold",
         "Defend captured territory against three waves of counterattacks.",
         4, 2, 7, 38, 2200, 380),
        # Arc 5: Judgment — rank 9, level 50+
        ("The Warlord Confrontation",
         "Track down a Sovereign-aligned warlord threatening Order dominance.",
         5, 1, 9, 50, 3500, 500),
        ("Execute or Recruit",
         "Make the final judgment: execute the warlord or offer them a place in the Order. "
         "Your decision reshapes faction relations permanently.",
         5, 2, 9, 55, 4000, 600),
    ],

    "Arcane Conclave": [
        # Arc 1: Apprentice Trials
        ("Advanced Spell Interactions",
         "Demonstrate mastery of upright-reversed energy combinations in the Conclave's test chamber.",
         1, 1, 1, 1, 350, 90),
        ("Anomaly Stabilization",
         "Stabilize a wild magical anomaly threatening a nearby settlement. Time-sensitive.",
         1, 2, 1, 4, 450, 110),
        # Arc 2: Forbidden Knowledge
        ("Restricted Archive Access",
         "Earn clearance to enter the Conclave's forbidden archives and extract specific lore.",
         2, 1, 3, 10, 750, 160),
        ("Hidden Arcana Truths",
         "Decode a set of encrypted arcana texts revealing suppressed magical history.",
         2, 2, 3, 13, 850, 190),
        # Arc 3: Reality Distortion
        ("Unstable Zone Entry",
         "Navigate a region where reality is actively distorting due to unchecked Tarot energy.",
         3, 1, 5, 22, 1300, 230),
        ("Spatial Collapse Survival",
         "Survive a full spatial collapse event inside a Tarot energy rift.",
         3, 2, 5, 25, 1500, 260),
        # Arc 4: Arcane Rivalry
        ("The Elite Mage Challenge",
         "Compete against Arcane Conclave's top-ranked mage NPC in a structured duel of abilities.",
         4, 1, 7, 36, 2100, 360),
        ("Proof of Superiority",
         "Demonstrate quantitatively superior magical output against the rival using three ability types.",
         4, 2, 7, 40, 2300, 390),
        # Arc 5: Grand Formula
        ("Universal Pattern Decoding",
         "Piece together the Grand Formula from fragments scattered across five locations.",
         5, 1, 9, 52, 3800, 520),
        ("Formula Activation",
         "Activate the decoded Grand Formula to unlock a unique ability modifier. "
         "The Conclave's ultimate discovery.",
         5, 2, 9, 58, 4500, 650),
    ],

    "Consortium of Virell": [
        # Arc 1: Entry Contract
        ("First Trade Route",
         "Complete a profitable trade run from Virell Prime to a distant kingdom. "
         "Earn at least 500 gold profit.",
         1, 1, 1, 1, 250, 70),
        ("Capital Establishment",
         "Build initial capital of 2000 gold through Consortium-approved trade activities.",
         1, 2, 1, 3, 350, 90),
        # Arc 2: Market Manipulation
        ("Supply Squeeze",
         "Deliberately corner supply of a common item to drive up prices in one region.",
         2, 1, 3, 10, 650, 140),
        ("Shortage Exploitation",
         "Exploit a naturally occurring supply shortage to generate 5000 gold in premium sales.",
         2, 2, 3, 12, 750, 170),
        # Arc 3: Auction Dominance
        ("High-Value Auction Win",
         "Win a Grand Hall auction for a rare-tier item by outbidding all competition.",
         3, 1, 5, 20, 1100, 200),
        ("Rare Item Flow Control",
         "Acquire three rare items via auction and resell them at a 50% markup through the Consortium network.",
         3, 2, 5, 23, 1300, 240),
        # Arc 4: Economic War
        ("Rival Guild Undermining",
         "Deliberately undercut a rival trade guild's prices below profitability.",
         4, 1, 7, 34, 1900, 330),
        ("Controlled Market Crash",
         "Engineer a controlled crash in one item category, then buy at the bottom.",
         4, 2, 7, 37, 2100, 360),
        # Arc 5: Monopoly
        ("Trade Hub Sector Control",
         "Achieve dominant control of one trade sector in Virell Prime — majority of supply.",
         5, 1, 9, 48, 3500, 490),
        ("Passive Income Unlock",
         "Establish the infrastructure for a permanent income stream. "
         "The Consortium grants a passive gold multiplier on all future trades.",
         5, 2, 9, 53, 4000, 580),
    ],

    "Veil Syndicate": [
        # Arc 1: Recruitment (secret)
        ("Unseen Delivery",
         "Deliver a contraband item from one city to another without being detected. "
         "Exposure increases if caught.",
         1, 1, 1, 1, 400, 100),
        ("Ghost Protocol",
         "Complete a stealth-only infiltration of a city guard post. No combat allowed.",
         1, 2, 1, 4, 500, 130),
        # Arc 2: Network Expansion
        ("Underground Contact Chain",
         "Build a network of three NPC contacts across different factions. Each must not know the others.",
         2, 1, 3, 12, 800, 170),
        ("Authority Infiltration",
         "Place a Syndicate asset inside a major kingdom's administration. "
         "Long-term intelligence access unlocked.",
         2, 2, 3, 15, 950, 200),
        # Arc 3: Dual Identity
        ("Cover Maintenance",
         "Complete a conflicting public guild quest while concealing Syndicate affiliation. "
         "Exposure +10 if detected.",
         3, 1, 5, 22, 1200, 220),
        ("Double Mission",
         "Simultaneously advance a public guild quest and a Syndicate operation. "
         "Both must succeed without overlap being discovered.",
         3, 2, 5, 26, 1500, 260),
        # Arc 4: Silent Elimination
        ("High-Value Target",
         "Remove a designated high-value target. Method must leave no traceable evidence.",
         4, 1, 7, 36, 2200, 370),
        ("Clean Exit",
         "Escape the elimination zone completely undetected. "
         "Failure triggers immediate exposure increase (+25).",
         4, 2, 7, 40, 2500, 410),
        # Arc 5: Shadow Control
        ("Black Market Dominance",
         "Establish Syndicate control over the black market in one major kingdom.",
         5, 1, 9, 52, 3800, 520),
        ("Invisible Economy",
         "Route 50% of a region's restricted item trade through Syndicate channels, "
         "remaining undetected by faction authorities.",
         5, 2, 9, 58, 4500, 650),
    ],

    "Ashen Circle": [
        # Arc 1: Initiation by Fire (secret)
        ("Destructive Trial",
         "Survive a trial in which unstable reversed energy is pushed through your body. "
         "Health loss is mandatory. Weakness is failure.",
         1, 1, 1, 1, 450, 110),
        ("Embrace the Unstable",
         "Channel reversed energy beyond your safe mana limit. Demonstrate control of chaos.",
         1, 2, 1, 5, 550, 140),
        # Arc 2: Controlled Collapse
        ("Trigger the Collapse",
         "Initiate a deliberate energy collapse event in a designated region.",
         2, 1, 3, 13, 900, 180),
        ("Consequence Management",
         "Stabilize just enough of the aftermath to prevent total destruction — "
         "controlled chaos, not blind annihilation.",
         2, 2, 3, 16, 1000, 210),
        # Arc 3: Breaking Order
        ("Kingdom Disruption",
         "Undermine the authority of a major kingdom's faction control. "
         "Reduce their TerritoryControl value by 30.",
         3, 1, 5, 24, 1400, 240),
        ("Destabilization Campaign",
         "Trigger a WorldEvent of type 'anomaly' in a controlled kingdom zone.",
         3, 2, 5, 28, 1600, 280),
        # Arc 4: Sovereign Interest
        ("Attract the Chaos Sovereign",
         "Perform sufficient destruction to draw attention of a Chaos-aligned Sovereign.",
         4, 1, 7, 38, 2300, 390),
        ("Survive the Encounter",
         "Meet the Chaos Sovereign directly. Survival (not victory) is the only requirement.",
         4, 2, 7, 42, 2600, 430),
        # Arc 5: Rebirth
        ("Energy Absorption",
         "Absorb residual energy from a region the Ashen Circle has destroyed.",
         5, 1, 9, 55, 4000, 540),
        ("The Rebirth Modifier",
         "Complete the Circle's final rite. Gain a permanent power modifier from absorbed chaos energy.",
         5, 2, 9, 60, 5000, 700),
    ],
}


# ── SEEDER ────────────────────────────────────────────────────────────────────
def seed_guilds(session: Session) -> None:
    print("  Seeding 5 predefined guilds...")
    for g_data in GUILDS:
        existing = session.exec(
            select(Guild).where(Guild.name == g_data["name"])
        ).first()
        if not existing:
            r = create_guild(session, **g_data)
            print(f"    Created: {g_data['name']} (id={r.get('guild_id')})")
        else:
            print(f"    Skipped (exists): {g_data['name']}")

    print("  Seeding guild questlines...")
    for guild_name, quests in GUILD_QUESTS.items():
        guild = session.exec(select(Guild).where(Guild.name == guild_name)).first()
        if not guild:
            print(f"  WARNING: Guild '{guild_name}' not found, skipping quests.")
            continue

        for q in quests:
            name, desc, arc, seq, req_rank, req_level, xp, rep = q
            existing_q = session.exec(
                select(GuildQuest).where(
                    GuildQuest.guild_id == guild.id,
                    GuildQuest.name == name,
                )
            ).first()
            if not existing_q:
                gq = GuildQuest(
                    guild_id=guild.id, name=name, description=desc,
                    arc=arc, sequence=seq, required_rank=req_rank,
                    required_level=req_level, xp_reward=xp,
                    reputation_reward=rep,
                )
                session.add(gq)

    session.commit()
    print(f"  Guild questlines committed.")


def main() -> None:
    print("=" * 60)
    print("  Guild System Seeder — AI RPG")
    print("=" * 60)
    create_db_and_tables()
    with get_session() as session:
        seed_guilds(session)
    print("\n  Guilds and questlines ready.\n")


if __name__ == "__main__":
    main()
