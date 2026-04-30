"""
generate_sovereigns.py
======================
Sovereign Generation System for the AI RPG Tarot world.

World constants
---------------
- 22 Major Arcana cards
- Each card: 1,000,000,000 upright energy + 1,000,000,000 reversed energy
- Population: 7,000,000,000 entities (represented statistically)
- 80% of each pool is distributed (skewed Pareto)
- 20% stays in ROOT / world reserve

Sovereign rules
---------------
- Exactly 1 Sovereign per card (upright OR reversed, defined per-card)
- Sovereign holds > 50% of their energy type's total pool (600M default)
- Sovereign holds their card as a TarotShard
- Marked with is_upright_sovereign or is_reversed_sovereign on TarotEntity

Run:
    uv run python generate_sovereigns.py
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.db.database import create_db_and_tables, get_session
from app.db.models import (
    CharacterPersona,
    SideCharacter,
    TarotCardLore,
    TarotEntity,
    TarotShard,
)

# ─────────────────────────────────────────────────────────────────────────────
# WORLD CONSTANTS (per card)
# ─────────────────────────────────────────────────────────────────────────────
TOTAL_POOL = 1_000_000_000          # per energy type, per card
DISTRIBUTED_POOL = int(TOTAL_POOL * 0.80)  # 800_000_000 available for distribution

# Energy tiers (per-card, per-type)
SOVEREIGN_ENERGY   = 600_000_000    # >50% of total pool  ✓
ELITE_ENERGY       = 10_000_000     # top ~0.1%
COMMON_MAX_ENERGY  = 10_000         # vast majority of 7B population

# ─────────────────────────────────────────────────────────────────────────────
# SOVEREIGN DEFINITIONS
# One per Major Arcana. energy_type = which pool they dominate.
# Remaining ~200M in each pool is split among world reserve and minor NPCs.
# ─────────────────────────────────────────────────────────────────────────────
SOVEREIGN_DATA: list[dict] = [
    {
        "card_name": "The Fool",
        "energy_type": "upright",
        "name": "Zephyros the Boundless",
        "position": "Sovereign of The Fool",
        "current_status": "Wandering between realms, disrupting order wherever found",
        "motivation": "To dissolve every boundary and wall that mortals call 'law' — freedom is the only truth worth dying for",
        "hidden_secret": "Secretly terrified of commitment; every step forward masks a desperate fear of arriving",
        "speaking_style": "Speaks in riddles, laughs at serious moments, treats life-or-death as a game",
        "risk_tolerance": 98, "loyalty": 10, "aggression": 40,
    },
    {
        "card_name": "The Magician",
        "energy_type": "upright",
        "name": "Arcanis the Architect",
        "position": "Sovereign of The Magician",
        "current_status": "Weaving the foundational spellwork that underpins half the world's infrastructure",
        "motivation": "To be the hand that shapes all things — every king, every law, every invention traces back to his design",
        "hidden_secret": "Cannot actually create; he only recombines what others invented. His empire is built on stolen ingenuity",
        "speaking_style": "Measured, precise, uses technical vocabulary as a weapon of intimidation",
        "risk_tolerance": 35, "loyalty": 20, "aggression": 55,
    },
    {
        "card_name": "The High Priestess",
        "energy_type": "reversed",
        "name": "Veila the Unspoken",
        "position": "Sovereign of The High Priestess",
        "current_status": "Residing in a sealed temple, receiving messengers but never leaving",
        "motivation": "To hoard all forbidden knowledge until she alone decides who may know what — information is the only power that compounds",
        "hidden_secret": "She is slowly losing her mind to the weight of secrets; she has forgotten her own name",
        "speaking_style": "Whispers even when alone; never finishes sentences; lets silence carry meaning",
        "risk_tolerance": 15, "loyalty": 30, "aggression": 20,
    },
    {
        "card_name": "The Empress",
        "energy_type": "upright",
        "name": "Floraia the Everbloom",
        "position": "Sovereign of The Empress",
        "current_status": "Governing the great living forests and the agricultural heartlands",
        "motivation": "To seed life in every barren place and erase the concept of scarcity from the world",
        "hidden_secret": "She is slowly merging with the root-network of the world forest; in decades she will no longer be human",
        "speaking_style": "Warm, unhurried, speaks in seasonal metaphors and botanical references",
        "risk_tolerance": 40, "loyalty": 80, "aggression": 20,
    },
    {
        "card_name": "The Emperor",
        "energy_type": "upright",
        "name": "Ketharon the Ironwill",
        "position": "Sovereign of The Emperor",
        "current_status": "Enforcing absolute order across seven territories through an unbreakable legal architecture",
        "motivation": "Chaos is death. Every war, every famine, every epidemic traces back to disorder. Order is mercy",
        "hidden_secret": "His rigid law code secretly exempts himself from its harshest provisions",
        "speaking_style": "Declarative, no qualifiers, speaks in edicts rather than conversation",
        "risk_tolerance": 20, "loyalty": 70, "aggression": 75,
    },
    {
        "card_name": "The Hierophant",
        "energy_type": "reversed",
        "name": "Schism the Unchained",
        "position": "Sovereign of The Hierophant (Reversed)",
        "current_status": "Leading an underground movement that systematically dismantles religious institutions",
        "motivation": "Every creed is a cage. He tears down doctrine to expose the naked truth beneath",
        "hidden_secret": "He once was a high priest himself and still prays privately every night",
        "speaking_style": "Fiery, rhetorical, weaponizes scripture against itself",
        "risk_tolerance": 70, "loyalty": 50, "aggression": 65,
    },
    {
        "card_name": "The Lovers",
        "energy_type": "upright",
        "name": "Elara the Bonded",
        "position": "Sovereign of The Lovers",
        "current_status": "Maintaining the vast network of soul-bonds that stabilize inter-faction diplomacy",
        "motivation": "Every conflict is a severed connection. She stitches fractured relationships to prevent war",
        "hidden_secret": "She is bonded to two people who are sworn enemies of each other and must keep both bonds intact",
        "speaking_style": "Empathic, mirroring; adapts tone to whoever she speaks with to establish rapport immediately",
        "risk_tolerance": 50, "loyalty": 90, "aggression": 10,
    },
    {
        "card_name": "The Chariot",
        "energy_type": "upright",
        "name": "Voren the Unstoppable",
        "position": "Sovereign of The Chariot",
        "current_status": "Leading the largest standing army in recorded history on a campaign of conquest",
        "motivation": "Victory is the only language the world understands. He intends to be the last word",
        "hidden_secret": "He is dying of a degenerative condition; the campaign must end before his body fails",
        "speaking_style": "Blunt, military cadence, no patience for ambiguity or delay",
        "risk_tolerance": 80, "loyalty": 60, "aggression": 90,
    },
    {
        "card_name": "Strength",
        "energy_type": "upright",
        "name": "Seraya the Unbroken",
        "position": "Sovereign of Strength",
        "current_status": "Acting as the world's peacekeeper, intervening in conflicts without taking sides",
        "motivation": "True power is restraint. She wants to demonstrate that the strongest force need never strike first",
        "hidden_secret": "She has never lost a fight. She is secretly afraid of what happens if she ever does",
        "speaking_style": "Calm to the point of seeming cold; speaks slowly, weighs every word",
        "risk_tolerance": 30, "loyalty": 75, "aggression": 25,
    },
    {
        "card_name": "The Hermit",
        "energy_type": "reversed",
        "name": "The Hollow Voice",
        "position": "Sovereign of The Hermit (Reversed)",
        "current_status": "Unknown — last confirmed location was a mountain pass three years ago",
        "motivation": "To unmake the loneliness he chose by destroying the systems that forced isolation upon others",
        "hidden_secret": "He is everywhere. He has fragmented his consciousness into a thousand wandering observers",
        "speaking_style": "Never appears in person; communicates only through intermediaries and cryptic written missives",
        "risk_tolerance": 60, "loyalty": 15, "aggression": 45,
    },
    {
        "card_name": "The Wheel of Fortune",
        "energy_type": "upright",
        "name": "Tyche the Turning",
        "position": "Sovereign of The Wheel of Fortune",
        "current_status": "Orchestrating cascading events across the continent like a celestial clockwork",
        "motivation": "The wheel must keep turning. Stagnation is the only true death; she accelerates cycles deliberately",
        "hidden_secret": "She does not control fate — she merely reads it faster than others and acts on the reading",
        "speaking_style": "Cheerful and fatalistic simultaneously; laughs at tragedy because she already saw it coming",
        "risk_tolerance": 75, "loyalty": 25, "aggression": 35,
    },
    {
        "card_name": "Justice",
        "energy_type": "upright",
        "name": "Lex the Immovable",
        "position": "Sovereign of Justice",
        "current_status": "Presiding over the Conclave of Final Arbitration, the world's highest court",
        "motivation": "Every wrong will be accounted for. Every crime carries a price. She is the price",
        "hidden_secret": "She once committed an act she cannot judge by her own code, and has suppressed the evidence",
        "speaking_style": "Formal and dispassionate; references precedent constantly; never uses first person",
        "risk_tolerance": 20, "loyalty": 85, "aggression": 50,
    },
    {
        "card_name": "The Hanged Man",
        "energy_type": "upright",
        "name": "Mori the Suspended",
        "position": "Sovereign of The Hanged Man",
        "current_status": "Voluntarily imprisoned in a temporal stasis — he claims he is 'waiting for the right moment'",
        "motivation": "The world is not ready. He sacrifices relevance now to emerge at the exact moment he can change everything",
        "hidden_secret": "He has been waiting for four hundred years. He no longer remembers what he was waiting for",
        "speaking_style": "Paradoxical, inverts expectations, responds to questions with opposite questions",
        "risk_tolerance": 5, "loyalty": 95, "aggression": 5,
    },
    {
        "card_name": "Death",
        "energy_type": "upright",
        "name": "Morthos the Final",
        "position": "Sovereign of Death",
        "current_status": "Quietly accelerating the collapse of three civilizations that have refused to change",
        "motivation": "Everything that refuses to transform becomes a cancer. He culls to enable renewal",
        "hidden_secret": "He is incapable of dying himself and is slowly driven mad by the one experience he cannot understand",
        "speaking_style": "Clinical, impersonal; refers to victims by cause of death rather than name",
        "risk_tolerance": 90, "loyalty": 40, "aggression": 70,
    },
    {
        "card_name": "Temperance",
        "energy_type": "upright",
        "name": "Alchema the Calibrated",
        "position": "Sovereign of Temperance",
        "current_status": "Running the world's largest neutral diplomatic hub where no violence is permitted",
        "motivation": "Every conflict is a chemical reaction gone wrong. She provides the catalyst for peaceful resolution",
        "hidden_secret": "She privately considers most people too extreme to be worth saving and selects who receives her mediation",
        "speaking_style": "Even-toned, never raises voice, uses precise measurement language — 'approximately', 'within tolerance'",
        "risk_tolerance": 30, "loyalty": 65, "aggression": 10,
    },
    {
        "card_name": "The Devil",
        "energy_type": "reversed",
        "name": "Lexa the Unchained",
        "position": "Sovereign of The Devil (Reversed)",
        "current_status": "Breaking compulsive energy bondage contracts that The Devil's upright network established",
        "motivation": "Every chain can be broken. She dismantles the control structures that masquerade as tradition",
        "hidden_secret": "She was once the most bound person in the world — a slave to the very contracts she now destroys",
        "speaking_style": "Raw, unfiltered, laughs loudly at propriety, uses blunt profanity as philosophical statement",
        "risk_tolerance": 85, "loyalty": 30, "aggression": 60,
    },
    {
        "card_name": "The Tower",
        "energy_type": "upright",
        "name": "Ruin the Inevitable",
        "position": "Sovereign of The Tower",
        "current_status": "At the center of three simultaneous catastrophes that observers claim were 'natural disasters'",
        "motivation": "Corrupt structures must fall. He finds the load-bearing lie in every institution and removes it",
        "hidden_secret": "He is haunted by the innocent casualties of his work and volunteers anonymously at disaster relief sites",
        "speaking_style": "Speaks rarely; when he does, buildings crack — not metaphorically",
        "risk_tolerance": 95, "loyalty": 20, "aggression": 85,
    },
    {
        "card_name": "The Star",
        "energy_type": "upright",
        "name": "Stella the Undying Hope",
        "position": "Sovereign of The Star",
        "current_status": "Maintaining seventeen active healing sanctuaries across the continent",
        "motivation": "As long as one person still hopes, the world is worth saving. She intends to be that one person if necessary",
        "hidden_secret": "She has lost hope herself but performs optimism perfectly, believing her role requires it",
        "speaking_style": "Warm, luminous, finds something genuinely beautiful in every person she meets",
        "risk_tolerance": 55, "loyalty": 95, "aggression": 5,
    },
    {
        "card_name": "The Moon",
        "energy_type": "reversed",
        "name": "Clarity the Revealer",
        "position": "Sovereign of The Moon (Reversed)",
        "current_status": "Systematically exposing illusions and hidden deceptions across the ruling class",
        "motivation": "Every comfortable lie is a postponed catastrophe. Truth now, however painful, prevents worse later",
        "hidden_secret": "She cannot perceive her own self-deceptions, making her blind to her greatest flaws",
        "speaking_style": "Blunt to the point of cruelty; mistakes tact for dishonesty; no softening of hard truths",
        "risk_tolerance": 65, "loyalty": 50, "aggression": 55,
    },
    {
        "card_name": "The Sun",
        "energy_type": "upright",
        "name": "Solarius the Radiant",
        "position": "Sovereign of The Sun",
        "current_status": "Leading the most prosperous civilization in history through an age of unprecedented growth",
        "motivation": "Success is contagious. If he can make one society undeniably thrive, others will follow the model",
        "hidden_secret": "His civilization's prosperity is built on a resource extraction deal that will collapse in thirty years",
        "speaking_style": "Infectious enthusiasm, makes everyone feel chosen and capable, rarely shows doubt",
        "risk_tolerance": 60, "loyalty": 70, "aggression": 30,
    },
    {
        "card_name": "Judgment",
        "energy_type": "upright",
        "name": "Rekonis the Awakener",
        "position": "Sovereign of Judgment",
        "current_status": "Traveling the world issuing irreversible Awakenings — forcing individuals to face their defining choices",
        "motivation": "Every person carries an unlived life. He forces them to choose: become what they were meant to be, or perish trying",
        "hidden_secret": "He has not yet faced his own Awakening and fears what it would reveal about him",
        "speaking_style": "Resonant, prophetic, speaks as though each word has been considered for centuries",
        "risk_tolerance": 50, "loyalty": 55, "aggression": 45,
    },
    {
        "card_name": "The World",
        "energy_type": "upright",
        "name": "Omnis the Complete",
        "position": "Sovereign of The World",
        "current_status": "Exists simultaneously in all places, maintaining the equilibrium of the known world",
        "motivation": "Completion. Every cycle must close. She works to bring all open threads to resolution before the age ends",
        "hidden_secret": "She is the world's last iteration. When she achieves completion, this reality ends and a new one begins",
        "speaking_style": "Speaks in completed thoughts; finishes others' sentences; references events that haven't happened yet",
        "risk_tolerance": 45, "loyalty": 100, "aggression": 20,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _validate_sovereign_data() -> None:
    """Pre-flight: catch duplicates and invalid energy amounts before any DB work."""
    seen: set[tuple[str, str]] = set()
    for s in SOVEREIGN_DATA:
        key = (s["card_name"], s["energy_type"])
        if key in seen:
            raise ValueError(f"Duplicate sovereign definition: {key}")
        seen.add(key)
        if SOVEREIGN_ENERGY <= TOTAL_POOL * 0.5:
            raise ValueError(
                f"Sovereign energy {SOVEREIGN_ENERGY} is NOT > 50% of {TOTAL_POOL}"
            )
        if SOVEREIGN_ENERGY + ELITE_ENERGY > DISTRIBUTED_POOL:
            raise ValueError(
                f"Sovereign + elite allocation exceeds distributed pool for {s['card_name']}"
            )
    if not (10 <= len(SOVEREIGN_DATA) <= 22):
        raise ValueError(f"Sovereign count {len(SOVEREIGN_DATA)} must be 10–22")
    print(f"  ✓ Pre-flight validation passed ({len(SOVEREIGN_DATA)} sovereigns defined)")


# ─────────────────────────────────────────────────────────────────────────────
# CORE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_sovereigns(session: Session) -> list[SideCharacter]:
    """
    Create all sovereign SideCharacters, their TarotEntity energy wallets,
    their CharacterPersona, and their TarotShard card ownership.

    Idempotent: skips any sovereign whose SideCharacter name already exists.
    Returns the list of created (or pre-existing) SideCharacter records.
    """
    _validate_sovereign_data()
    results: list[SideCharacter] = []

    for idx, sov in enumerate(SOVEREIGN_DATA, start=1):
        print(f"  [{idx:02d}/{len(SOVEREIGN_DATA)}] Generating: {sov['name']} ({sov['card_name']})")

        # ── Idempotency check ──────────────────────────────────────────────
        existing_sc = session.exec(
            select(SideCharacter).where(SideCharacter.name == sov["name"])
        ).first()
        if existing_sc:
            print(f"         → Already exists, skipping.")
            results.append(existing_sc)
            continue

        # ── Resolve card lore ──────────────────────────────────────────────
        lore = session.exec(
            select(TarotCardLore).where(TarotCardLore.name == sov["card_name"])
        ).first()
        if not lore:
            raise RuntimeError(
                f"Card '{sov['card_name']}' not found in TarotCardLore. "
                "Run seed.py first."
            )

        # ── Per-card energy accounting ─────────────────────────────────────
        # Calculate how much energy this card's sovereign holds.
        # The remainder (DISTRIBUTED_POOL - SOVEREIGN_ENERGY) represents
        # elites + commons across the 7B population (statistical, not stored).
        energy_type   = sov["energy_type"]   # "upright" | "reversed"
        sovereign_amt = SOVEREIGN_ENERGY      # 600_000_000

        # Build capacity kwargs based on energy type
        if energy_type == "upright":
            entity_kwargs = dict(
                upright_capacity=sovereign_amt,
                reversed_capacity=0,
                current_upright_mana=int(100 + sovereign_amt ** 0.9),
                current_reversed_mana=100,
                is_upright_sovereign=True,
                is_reversed_sovereign=False,
            )
        else:
            entity_kwargs = dict(
                upright_capacity=0,
                reversed_capacity=sovereign_amt,
                current_upright_mana=100,
                current_reversed_mana=int(100 + sovereign_amt ** 0.9),
                is_upright_sovereign=False,
                is_reversed_sovereign=True,
            )

        # ── 1. TarotEntity (energy wallet) ────────────────────────────────
        entity = TarotEntity(
            entity_name=f"[SOVEREIGN] {sov['name']}",
            current_health=100 + (sovereign_amt * 10),   # extremely high HP
            damage_bonus=50,
            damage_reduction=30,
            **entity_kwargs,
        )
        session.add(entity)
        session.flush()   # get entity.id

        # ── 2. SideCharacter (narrative identity) ─────────────────────────
        character = SideCharacter(
            name=sov["name"],
            position=sov["position"],
            current_status=sov["current_status"],
            tarot_entity_id=entity.id,
        )
        session.add(character)
        session.flush()   # get character.id

        # ── 3. CharacterPersona (AI brain config) ─────────────────────────
        persona = CharacterPersona(
            motivation=sov["motivation"],
            hidden_secret=sov["hidden_secret"],
            speaking_style=sov["speaking_style"],
            risk_tolerance=sov["risk_tolerance"],
            loyalty=sov["loyalty"],
            aggression=sov["aggression"],
            character_id=character.id,
            tarot_affinity_id=lore.id,
        )
        session.add(persona)

        # ── 4. TarotShard (card ownership — grants abilities) ─────────────
        shard = TarotShard(
            owner_id=entity.id,
            lore_id=lore.id,
        )
        session.add(shard)

        results.append(character)
        print(f"         → Created | energy={sovereign_amt:,} {energy_type} | "
              f"entity_id=<pending> | card='{sov['card_name']}'")

    # ── Commit all in one transaction ──────────────────────────────────────
    try:
        session.commit()
        print(f"\n  ✓ All {len(SOVEREIGN_DATA)} sovereigns committed successfully.")
    except Exception as exc:
        session.rollback()
        raise RuntimeError(f"Sovereign generation failed during commit: {exc}") from exc

    # Refresh to get final IDs
    for sc in results:
        try:
            session.refresh(sc)
        except Exception:
            pass

    return results


# ─────────────────────────────────────────────────────────────────────────────
# POST-GENERATION VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_sovereigns(session: Session) -> None:
    """
    Post-generation validation:
    1. Every sovereign entity holds > 50% of TOTAL_POOL for their energy type.
    2. No card+energy_type combination has more than one sovereign.
    3. Every sovereign has a linked CharacterPersona.
    4. Every sovereign entity has the correct sovereign flag set.
    """
    print("\n  Running post-generation validation...")

    sovereigns = session.exec(
        select(SideCharacter)
    ).all()

    seen_combinations: dict[tuple[str, str], str] = {}
    errors: list[str] = []

    for sc in sovereigns:
        entity = sc.tarot_wallet
        if not entity:
            continue
        if not (entity.is_upright_sovereign or entity.is_reversed_sovereign):
            continue   # skip non-sovereign characters

        # Check persona link
        persona = sc.persona
        if not persona:
            errors.append(f"MISSING PERSONA: {sc.name}")
            continue

        # Determine card + energy_type from persona affinity
        lore = persona.tarot_affinity
        if not lore:
            errors.append(f"MISSING LORE AFFINITY: {sc.name}")
            continue

        energy_type = "upright" if entity.is_upright_sovereign else "reversed"
        key = (lore.name, energy_type)

        # Check for duplicates
        if key in seen_combinations:
            errors.append(
                f"DUPLICATE SOVEREIGN: {sc.name} and {seen_combinations[key]} "
                f"both claim {lore.name} / {energy_type}"
            )
        else:
            seen_combinations[key] = sc.name

        # Check energy amount
        capacity = (
            entity.upright_capacity if energy_type == "upright"
            else entity.reversed_capacity
        )
        threshold = TOTAL_POOL * 0.50
        if capacity <= threshold:
            errors.append(
                f"ENERGY TOO LOW: {sc.name} holds {capacity:,} "
                f"({energy_type}), must be > {threshold:,.0f}"
            )

    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        raise RuntimeError(f"Validation failed with {len(errors)} error(s).")

    print(f"  ✓ Validation passed. {len(seen_combinations)} sovereign "
          f"card+energy combinations verified.")


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY REPORT
# ─────────────────────────────────────────────────────────────────────────────

def print_sovereign_report(session: Session) -> None:
    """Print a formatted summary of all generated sovereigns."""
    print("\n" + "=" * 72)
    print("  SOVEREIGN GENERATION REPORT")
    print("=" * 72)

    # Collect sovereigns via entity flag
    entities = session.exec(
        select(TarotEntity).where(
            (TarotEntity.is_upright_sovereign == True) |
            (TarotEntity.is_reversed_sovereign == True)
        )
    ).all()

    print(f"  Total Sovereigns : {len(entities)}")
    print(f"  Sovereign Energy : {SOVEREIGN_ENERGY:,} per card")
    print(f"  Total Pool/Card  : {TOTAL_POOL:,} per energy type")
    print(f"  Dominance        : {SOVEREIGN_ENERGY/TOTAL_POOL*100:.1f}% of pool\n")

    header = f"  {'Name':<30} {'Card':<22} {'Type':<10} {'Energy':>15}"
    print(header)
    print("  " + "-" * 70)

    for entity in sorted(entities, key=lambda e: e.entity_name):
        sc = entity.side_character
        if not sc or not sc.persona or not sc.persona.tarot_affinity:
            continue
        lore = sc.persona.tarot_affinity
        e_type = "upright" if entity.is_upright_sovereign else "reversed"
        cap = entity.upright_capacity if e_type == "upright" else entity.reversed_capacity
        print(f"  {sc.name:<30} {lore.name:<22} {e_type:<10} {cap:>15,}")

    print("=" * 72)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("  Sovereign Generation System — AI RPG Tarot World")
    print("=" * 72 + "\n")

    # Ensure tables exist (safe if already created)
    create_db_and_tables()

    with get_session() as session:
        print("  Phase 1: Generating sovereign entities...\n")
        generate_sovereigns(session)

        print("\n  Phase 2: Validating world economy constraints...")
        validate_sovereigns(session)

        print_sovereign_report(session)

    print("\n  Sovereign generation complete. The world's power hierarchy is set.\n")


if __name__ == "__main__":
    main()
