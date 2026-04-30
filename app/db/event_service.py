"""
app/db/event_service.py
========================
Random Event System — probabilistic spawning, lifecycle, player acceptance, rewards.

Public API
----------
Templates (admin):
    create_template(session, ...) -> dict
    seed_default_templates(session) -> int   ← 5 mandatory special events

Spawn:
    try_spawn_event(session, entity_id, location_id) -> dict
    create_event_instance(session, template_id, location_id, entity_id, player_level) -> dict

Active events:
    get_active_events_at(session, location_id, entity_id) -> list[dict]
    expire_events(session) -> int

Player interaction:
    accept_event(session, entity_id, event_instance_id) -> dict
    advance_event_quest(session, entity_id, event_quest_id, amount) -> dict
    complete_event(session, entity_id, event_quest_id) -> dict
    abandon_event(session, entity_id, event_quest_id) -> dict

Area-lock (main quest integration):
    invalidate_region_events(session, location_id) -> int

Design rules
------------
- Spawn uses weighted-random selection, never pure random
- Max MAX_EVENTS_PER_LOCATION active instances per location
- Expired events are lazily marked inactive on next interaction
- GM reads get_active_events_at() to narrate — it does NOT invent events
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.models import (
    BASE_SPAWN_WEIGHTS,
    DIFFICULTY_SCALE_FACTOR,
    EVENT_RARITY_TIERS,
    EVENT_TEMPLATE_TYPES,
    MAX_EVENTS_PER_LOCATION,
    SPAWN_MODIFIERS,
    EventQuest,
    EventTemplate,
    Location,
    QuestProgress,
    TarotEntity,
    WorldEventInstance,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# TEMPLATE MANAGEMENT
# =============================================================

def create_template(
    session: Session,
    name: str,
    description: str,
    event_type: str,
    rarity: str = "common",
    base_duration_minutes: int = 60,
    min_level: int = 1,
    max_level: Optional[int] = None,
    risk_level: int = 3,
    reward_base_xp: int = 200,
    reward_item_pool: Optional[list[str]] = None,
    requires_war: bool = False,
    requires_sovereign_influence: bool = False,
) -> dict:
    if event_type not in EVENT_TEMPLATE_TYPES:
        return {"success": False, "reason": "invalid_event_type",
                "valid": list(EVENT_TEMPLATE_TYPES)}
    if rarity not in BASE_SPAWN_WEIGHTS:
        return {"success": False, "reason": "invalid_rarity",
                "valid": list(BASE_SPAWN_WEIGHTS.keys())}
    existing = session.exec(select(EventTemplate).where(EventTemplate.name == name)).first()
    if existing:
        return {"success": False, "reason": "template_already_exists", "id": existing.id}

    tpl = EventTemplate(
        name=name, description=description,
        event_type=event_type, rarity=rarity,
        base_duration_minutes=base_duration_minutes,
        min_level=min_level, max_level=max_level,
        risk_level=max(1, min(10, risk_level)),
        reward_base_xp=reward_base_xp,
        reward_item_pool=json.dumps(reward_item_pool) if reward_item_pool else None,
        requires_war=requires_war,
        requires_sovereign_influence=requires_sovereign_influence,
    )
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return {"success": True, "template_id": tpl.id, "name": tpl.name, "rarity": tpl.rarity}


def seed_default_templates(session: Session) -> int:
    """
    Seed the 5 mandatory special event templates.
    Idempotent — skips existing names. Returns count created.
    """
    defaults = [
        {
            "name": "Ambush",
            "description": (
                "A group of hostile entities springs from cover, seeking to rob or kill. "
                "Survive and drive them off to claim their goods."
            ),
            "event_type": "combat",
            "rarity": "common",
            "base_duration_minutes": 30,
            "min_level": 1,
            "risk_level": 5,
            "reward_base_xp": 150,
            "reward_item_pool": ["Bandit Loot Bag", "Crude Weapon"],
        },
        {
            "name": "Lost Merchant",
            "description": (
                "A merchant has lost their escort and cargo in unfamiliar territory. "
                "Guide them to the nearest settlement before nightfall."
            ),
            "event_type": "escort",
            "rarity": "uncommon",
            "base_duration_minutes": 90,
            "min_level": 3,
            "risk_level": 3,
            "reward_base_xp": 250,
            "reward_item_pool": ["Merchant's Gratitude Coin", "Trade Good Bundle"],
        },
        {
            "name": "Arcane Surge",
            "description": (
                "Wild Tarot energy erupts in the area, temporarily amplifying all magic. "
                "Exploit the surge — but overextension is dangerous."
            ),
            "event_type": "anomaly",
            "rarity": "rare",
            "base_duration_minutes": 20,
            "min_level": 10,
            "risk_level": 6,
            "reward_base_xp": 400,
            "reward_item_pool": ["Arcane Residue", "Unstable Shard Fragment"],
        },
        {
            "name": "War Skirmish",
            "description": (
                "A small-scale battle between faction forces erupts nearby. "
                "Join one side, play both, or survive the crossfire."
            ),
            "event_type": "combat",
            "rarity": "rare",
            "base_duration_minutes": 60,
            "min_level": 15,
            "risk_level": 8,
            "reward_base_xp": 600,
            "reward_item_pool": ["War Trophy", "Faction Commendation"],
            "requires_war": True,
        },
        {
            "name": "Sovereign Distortion",
            "description": (
                "A Sovereign's influence tears at reality itself. Physics and Tarot energy "
                "behave unpredictably. Only the strongest survive the rift."
            ),
            "event_type": "anomaly",
            "rarity": "epic",
            "base_duration_minutes": 45,
            "min_level": 30,
            "risk_level": 10,
            "reward_base_xp": 1200,
            "reward_item_pool": ["Sovereign Fragment", "Distortion Core", "Rift Crystal"],
            "requires_sovereign_influence": True,
        },
    ]
    created = 0
    for d in defaults:
        r = create_template(session, **d)
        if r.get("success"):
            created += 1
    return created


# =============================================================
# SPAWN SYSTEM
# =============================================================

def _build_weights(
    player_level: int,
    is_war_zone: bool,
    sovereign_influence: float,
    is_safe_zone: bool,
) -> dict[str, float]:
    """Return adjusted rarity weights for weighted-random selection."""
    weights = dict(BASE_SPAWN_WEIGHTS)

    if is_safe_zone:
        for rarity, delta in SPAWN_MODIFIERS["safe_zone"].items():
            weights[rarity] = max(0.0, weights.get(rarity, 0) + delta)
    if is_war_zone:
        for rarity, delta in SPAWN_MODIFIERS["war_zone"].items():
            weights[rarity] = weights.get(rarity, 0) + delta
    if sovereign_influence >= 50:
        for rarity, delta in SPAWN_MODIFIERS["sovereign_high"].items():
            weights[rarity] = weights.get(rarity, 0) + delta
    if player_level >= 40:
        for rarity, delta in SPAWN_MODIFIERS["level_tier_3"].items():
            weights[rarity] = weights.get(rarity, 0) + delta
    elif player_level >= 20:
        for rarity, delta in SPAWN_MODIFIERS["level_tier_2"].items():
            weights[rarity] = weights.get(rarity, 0) + delta

    # Clamp all to >= 0
    return {k: max(0.0, v) for k, v in weights.items()}


def _pick_rarity(weights: dict[str, float]) -> Optional[str]:
    """Weighted-random rarity selection. Returns None if all weights are 0."""
    rarities = [r for r in EVENT_RARITY_TIERS if weights.get(r, 0) > 0]
    w_values = [weights[r] for r in rarities]
    total = sum(w_values)
    if total <= 0:
        return None
    roll = random.uniform(0, total)
    cumulative = 0.0
    for rarity, w in zip(rarities, w_values):
        cumulative += w
        if roll <= cumulative:
            return rarity
    return rarities[-1]


def _count_active_at(session: Session, location_id: int) -> int:
    now = _utcnow()
    rows = session.exec(
        select(WorldEventInstance).where(
            WorldEventInstance.location_id == location_id,
            WorldEventInstance.is_active == True,  # noqa: E712
        )
    ).all()
    return sum(
        1 for r in rows
        if (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None
            else r.expires_at) > now
    )


def _world_status(session: Session, location_id: int) -> tuple[bool, float]:
    """Return (is_war_zone, max_sovereign_influence) for a location."""
    from app.db.world_service import get_active_events, get_location_status
    try:
        events = get_active_events(session, location_id)
        is_war = any(e["event_type"] == "war" for e in events)
        status = get_location_status(session, location_id)
        influence = status.get("max_sovereign_influence", 0.0)
        return is_war, influence
    except Exception:
        return False, 0.0


def try_spawn_event(
    session: Session,
    entity_id: int,
    location_id: int,
) -> dict:
    """
    Probabilistic spawn attempt. Called on:
      - player entering a location
      - player completing any action
      - world tick

    Returns spawned event data or {"spawned": False, "reason": ...}.
    Never spawns if MAX_EVENTS_PER_LOCATION is reached.
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"spawned": False, "reason": "entity_not_found"}

    location = session.get(Location, location_id)
    if not location:
        return {"spawned": False, "reason": "location_not_found"}

    # Cap check
    active_count = _count_active_at(session, location_id)
    if active_count >= MAX_EVENTS_PER_LOCATION:
        return {"spawned": False, "reason": "location_event_cap_reached",
                "active": active_count}

    is_war, influence = _world_status(session, location_id)
    weights = _build_weights(
        player_level=entity.level,
        is_war_zone=is_war,
        sovereign_influence=influence,
        is_safe_zone=location.is_safe_zone,
    )

    chosen_rarity = _pick_rarity(weights)
    if chosen_rarity is None:
        return {"spawned": False, "reason": "no_eligible_rarity"}

    # Filter templates eligible for this context
    all_templates = session.exec(
        select(EventTemplate).where(
            EventTemplate.rarity == chosen_rarity,
            EventTemplate.is_active == True,  # noqa: E712
            EventTemplate.min_level <= entity.level,
        )
    ).all()

    # Level cap filter
    eligible = [
        t for t in all_templates
        if (t.max_level is None or entity.level <= t.max_level)
        and (not t.requires_war or is_war)
        and (not t.requires_sovereign_influence or influence >= 50)
    ]

    if not eligible:
        return {"spawned": False, "reason": "no_eligible_templates",
                "rarity_attempted": chosen_rarity}

    template = random.choice(eligible)
    result = create_event_instance(session, template.id, location_id, entity_id, entity.level)
    result["spawned"] = result.pop("success", False)
    result["rarity"] = chosen_rarity
    return result


def create_event_instance(
    session: Session,
    template_id: int,
    location_id: int,
    entity_id: Optional[int],
    player_level: int = 1,
) -> dict:
    """
    Directly create a WorldEventInstance from a template.
    Used by try_spawn_event and can be called by admin/test code.
    """
    template = session.get(EventTemplate, template_id)
    if not template:
        return {"success": False, "reason": "template_not_found"}

    now = _utcnow()
    expires_at = now + timedelta(minutes=template.base_duration_minutes)
    scaling = round(1.0 + player_level * DIFFICULTY_SCALE_FACTOR, 4)

    instance = WorldEventInstance(
        template_id=template_id,
        location_id=location_id,
        spawned_at=now,
        expires_at=expires_at,
        is_active=True,
        is_completed=False,
        spawned_for_entity_id=entity_id,
        difficulty_scaling=scaling,
    )
    session.add(instance)
    session.commit()
    session.refresh(instance)

    return {
        "success": True,
        "instance_id": instance.id,
        "template_name": template.name,
        "event_type": template.event_type,
        "rarity": template.rarity,
        "expires_at": expires_at.isoformat(),
        "difficulty_scaling": scaling,
        "risk_level": template.risk_level,
        "reward_base_xp": template.reward_base_xp,
    }


# =============================================================
# ACTIVE EVENT QUERIES
# =============================================================

def get_active_events_at(
    session: Session,
    location_id: int,
    entity_id: Optional[int] = None,
) -> list[dict]:
    """
    Return all live, non-expired events visible to an entity at a location.
    Includes world-visible events + events personalized to this entity.
    Lazily expires stale rows.
    """
    expire_events(session)   # lazy cleanup first

    rows = session.exec(
        select(WorldEventInstance).where(
            WorldEventInstance.location_id == location_id,
            WorldEventInstance.is_active == True,  # noqa: E712
            WorldEventInstance.is_completed == False,  # noqa: E712
        )
    ).all()

    now = _utcnow()
    result = []
    for inst in rows:
        # Visibility filter: world events OR personalized to this entity
        if inst.spawned_for_entity_id and entity_id:
            if inst.spawned_for_entity_id != entity_id:
                continue
        exp = inst.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            continue

        tpl = session.get(EventTemplate, inst.template_id)
        seconds_remaining = (exp - now).total_seconds()
        result.append({
            "instance_id": inst.id,
            "template_name": tpl.name if tpl else "Unknown",
            "event_type": tpl.event_type if tpl else "unknown",
            "rarity": tpl.rarity if tpl else "common",
            "description": tpl.description if tpl else "",
            "risk_level": tpl.risk_level if tpl else 1,
            "difficulty_scaling": inst.difficulty_scaling,
            "seconds_remaining": round(seconds_remaining),
            "reward_base_xp": tpl.reward_base_xp if tpl else 0,
        })
    return result


def expire_events(session: Session) -> int:
    """
    Mark all WorldEventInstances past their expires_at as is_active=False.
    Called lazily at the start of every query. Returns count expired.
    """
    now = _utcnow()
    rows = session.exec(
        select(WorldEventInstance).where(
            WorldEventInstance.is_active == True,  # noqa: E712
            WorldEventInstance.is_completed == False,  # noqa: E712
        )
    ).all()
    expired = 0
    for inst in rows:
        exp = inst.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            inst.is_active = False
            session.add(inst)
            expired += 1
    if expired:
        session.commit()
    return expired


# =============================================================
# PLAYER INTERACTION
# =============================================================

def accept_event(
    session: Session,
    entity_id: int,
    event_instance_id: int,
) -> dict:
    """
    Player accepts a WorldEventInstance → creates an EventQuest.
    Rejects if: expired, already accepted, already completed by this player.
    """
    instance = session.get(WorldEventInstance, event_instance_id)
    if not instance or not instance.is_active:
        return {"success": False, "reason": "event_not_found_or_inactive"}

    now = _utcnow()
    exp = instance.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now >= exp:
        instance.is_active = False
        session.add(instance)
        session.commit()
        return {"success": False, "reason": "event_expired"}

    # Duplicate acceptance check
    existing = session.exec(
        select(EventQuest).where(
            EventQuest.event_instance_id == event_instance_id,
            EventQuest.entity_id == entity_id,
            EventQuest.is_abandoned == False,  # noqa: E712
        )
    ).first()
    if existing:
        return {"success": False, "reason": "already_accepted",
                "event_quest_id": existing.id}

    template = session.get(EventTemplate, instance.template_id)
    eq = EventQuest(
        event_instance_id=event_instance_id,
        entity_id=entity_id,
        progress=0,
        goal=1,   # simple binary for base: reach goal=1 to complete
    )
    session.add(eq)
    session.commit()
    session.refresh(eq)

    return {
        "success": True,
        "event_quest_id": eq.id,
        "event_name": template.name if template else "Unknown",
        "goal": eq.goal,
        "expires_at": exp.isoformat(),
    }


def advance_event_quest(
    session: Session,
    entity_id: int,
    event_quest_id: int,
    amount: int = 1,
) -> dict:
    """Increment progress on an active EventQuest."""
    eq = session.get(EventQuest, event_quest_id)
    if not eq or eq.entity_id != entity_id:
        return {"success": False, "reason": "event_quest_not_found"}
    if eq.is_completed or eq.is_abandoned:
        return {"success": False, "reason": "event_quest_already_finished"}

    eq.progress = min(eq.goal, eq.progress + max(0, amount))
    session.add(eq)
    session.commit()
    return {
        "success": True,
        "progress": eq.progress,
        "goal": eq.goal,
        "ready_to_complete": eq.progress >= eq.goal,
    }


def complete_event(
    session: Session,
    entity_id: int,
    event_quest_id: int,
) -> dict:
    """
    Complete an EventQuest. Awards XP (scaled by difficulty_scaling).
    Rolls one random item from reward_item_pool if available.
    Marks WorldEventInstance as completed.
    """
    eq = session.get(EventQuest, event_quest_id)
    if not eq or eq.entity_id != entity_id:
        return {"success": False, "reason": "event_quest_not_found"}
    if eq.is_completed:
        return {"success": False, "reason": "already_completed"}
    if eq.is_abandoned:
        return {"success": False, "reason": "quest_abandoned"}
    if eq.progress < eq.goal:
        return {"success": False, "reason": "not_enough_progress",
                "progress": eq.progress, "goal": eq.goal}

    instance = session.get(WorldEventInstance, eq.event_instance_id)
    template = session.get(EventTemplate, instance.template_id) if instance else None

    # Check not expired
    if instance:
        exp = instance.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if _utcnow() >= exp:
            eq.is_abandoned = True
            session.add(eq)
            session.commit()
            return {"success": False, "reason": "event_expired_before_completion"}

    # Compute rewards
    scaling = instance.difficulty_scaling if instance else 1.0
    base_xp = template.reward_base_xp if template else 100
    xp_awarded = int(base_xp * scaling)

    # Award XP
    from app.db.service import tarot_service
    tarot_service.add_xp(session, entity_id, xp_awarded)

    # Roll loot
    item_rewarded = None
    if template and template.reward_item_pool:
        try:
            pool = json.loads(template.reward_item_pool)
            if pool:
                item_rewarded = random.choice(pool)
        except (json.JSONDecodeError, IndexError):
            pass

    eq.is_completed = True
    session.add(eq)

    if instance:
        instance.is_completed = True
        instance.is_active = False
        session.add(instance)

    session.commit()

    return {
        "success": True,
        "xp_awarded": xp_awarded,
        "item_rewarded": item_rewarded,
        "difficulty_scaling": scaling,
    }


def abandon_event(
    session: Session,
    entity_id: int,
    event_quest_id: int,
) -> dict:
    """
    Player abandons an EventQuest. No rewards. Event instance remains for others.
    """
    eq = session.get(EventQuest, event_quest_id)
    if not eq or eq.entity_id != entity_id:
        return {"success": False, "reason": "event_quest_not_found"}
    if eq.is_completed or eq.is_abandoned:
        return {"success": False, "reason": "already_finished"}

    eq.is_abandoned = True
    session.add(eq)
    session.commit()
    return {"success": True, "abandoned": True}


# =============================================================
# AREA-LOCK: MAIN QUEST INTEGRATION
# =============================================================

def invalidate_region_events(session: Session, location_id: int) -> int:
    """
    Called when the main quest linked to a location is completed.
    Deactivates all active WorldEventInstances tied to that location.
    Returns count invalidated.
    """
    rows = session.exec(
        select(WorldEventInstance).where(
            WorldEventInstance.location_id == location_id,
            WorldEventInstance.is_active == True,  # noqa: E712
            WorldEventInstance.is_completed == False,  # noqa: E712
        )
    ).all()
    count = 0
    for inst in rows:
        inst.is_active = False
        session.add(inst)
        count += 1
    if count:
        session.commit()
    return count


def check_and_invalidate_on_quest_complete(
    session: Session,
    quest_id: int,
) -> int:
    """
    Called by quest completion logic. Finds all locations whose
    region_main_quest_id matches this quest and invalidates their events.
    """
    from app.db.models import Location
    locations = session.exec(
        select(Location).where(Location.region_main_quest_id == quest_id)
    ).all()
    total = 0
    for loc in locations:
        total += invalidate_region_events(session, loc.id)
    return total
