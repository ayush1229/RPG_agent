"""
app/db/time_service.py
========================
Day/Night cycle, Housing, and Dreamscape systems.
All advancement is LAZY-TICK — time only moves forward when a player interacts.

Public API
----------
World Time:
    get_world_time(session) -> WorldTime          # singleton, creates if missing
    update_time(session) -> dict                  # advance clock by real delta, return state
    check_day_night(session) -> dict              # {is_night, game_hour, ...}
    apply_night_modifiers(base_value, session, *, is_spawn_weight=False) -> float

Housing:
    rent_housing(session, entity_id, location_id, housing_type, duration_hours) -> dict
    buy_housing(session, entity_id, location_id) -> dict
    enter_housing(session, entity_id) -> dict
    exit_housing(session, entity_id) -> dict
    is_player_sheltered(session, entity_id) -> bool

Dreamscape:
    unlock_dreamscape(session, entity_id) -> dict
    try_enter_dream(session, entity_id) -> dict        # probabilistic gate
    enter_dreamscape(session, entity_id) -> dict       # deterministic entry
    exit_dreamscape(session, entity_id) -> dict
    set_dream_flag(session, entity_id, key, value) -> dict
    get_dream_flags(session, entity_id) -> dict
    is_in_dreamscape(session, entity_id) -> bool

Integration hooks:
    get_night_event_weight_boost(session) -> dict[str, float]
    get_travel_night_modifier(session) -> float
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.models import (
    DREAM_BASE_CHANCE,
    DREAMSCAPE_LOCATION_NAME,
    HOUSING_TYPES,
    NIGHT_END_HOUR,
    NIGHT_RISK_MULTIPLIER,
    NIGHT_START_HOUR,
    DreamState,
    Location,
    PlayerHousing,
    TarotEntity,
    WorldTime,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# WORLD TIME (LAZY-TICK SINGLETON)
# =============================================================

def get_world_time(session: Session) -> WorldTime:
    """Return singleton WorldTime row, creating it if needed."""
    wt = session.get(WorldTime, 1)
    if not wt:
        wt = WorldTime(id=1, current_time=_utcnow(), last_real_tick=_utcnow())
        session.add(wt)
        session.commit()
        session.refresh(wt)
    return wt


def update_time(session: Session, advance_minutes: int = 15) -> dict:
    """
    TURN-BASED TICK: advance game time by a fixed amount of game minutes.
    By default, each interaction advances the clock by 15 minutes.
    """
    wt = get_world_time(session)
    
    wt.current_time = wt.current_time + timedelta(minutes=advance_minutes)
    wt.last_real_tick = _utcnow()
    session.add(wt)
    session.commit()

    return _time_snapshot(wt, 0, advance_minutes * 60)


def _time_snapshot(wt: WorldTime, real_elapsed: float = 0, game_seconds: float = 0) -> dict:
    ct = wt.current_time
    hour = ct.hour
    is_night = hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR
    return {
        "game_time": ct.isoformat(),
        "game_hour": hour,
        "game_minute": ct.minute,
        "is_night": is_night,
        "time_phase": "night" if is_night else "day",
        "time_scale": wt.time_scale,
        "real_seconds_elapsed": round(real_elapsed, 2),
        "game_seconds_advanced": round(game_seconds, 2),
        "night_risk_multiplier": NIGHT_RISK_MULTIPLIER if is_night else 1.0,
    }


def check_day_night(session: Session) -> dict:
    """Return current day/night state without advancing time."""
    wt = get_world_time(session)
    return _time_snapshot(wt)


def apply_night_modifiers(
    base_value: float,
    session: Session,
    *,
    is_spawn_weight: bool = False,
) -> float:
    """
    Multiply base_value by NIGHT_RISK_MULTIPLIER if currently night.
    For spawn weights, the multiplier is additive on top of 1.0.
    """
    dn = check_day_night(session)
    if not dn["is_night"]:
        return base_value
    if is_spawn_weight:
        # Spawn weights: add a night bonus on top of base (not × multiplier)
        return base_value * NIGHT_RISK_MULTIPLIER
    return base_value * NIGHT_RISK_MULTIPLIER


def get_night_event_weight_boost(session: Session) -> dict[str, float]:
    """
    Returns per-rarity additive bonuses for the event spawn system at night.
    Integrated into try_spawn_event in event_service.py.
    """
    dn = check_day_night(session)
    if not dn["is_night"]:
        return {}
    # At night: significantly boost rare+epic, add nightmare-flavoured events
    return {
        "common":   +10.0,   # ambushes more frequent
        "uncommon": +5.0,
        "rare":     +12.0,   # shadow encounters, nightmare events
        "epic":     +6.0,    # sovereign distortions peak at night
    }


def get_travel_night_modifier(session: Session) -> float:
    """
    Returns the extra danger multiplier for entities travelling at night.
    Applied to TravelState risk and enemy level scaling.
    """
    dn = check_day_night(session)
    return NIGHT_RISK_MULTIPLIER if dn["is_night"] else 1.0


# =============================================================
# HOUSING
# =============================================================

def _get_housing(session: Session, entity_id: int) -> Optional[PlayerHousing]:
    return session.exec(
        select(PlayerHousing).where(PlayerHousing.entity_id == entity_id)
    ).first()


def _housing_valid(housing: PlayerHousing) -> bool:
    """Return True if rental hasn't expired (owned = always valid)."""
    if housing.expires_at is None:
        return True   # owned house — permanent
    exp = housing.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return _utcnow() < exp


def rent_housing(
    session: Session,
    entity_id: int,
    location_id: int,
    housing_type: str = "inn",
    duration_hours: int = 8,
) -> dict:
    """
    Assign temporary housing. Replaces existing if present.
    inn          → default 8 game-hours, cheap
    rented_room  → up to 30 days, moderate
    """
    if housing_type not in HOUSING_TYPES or housing_type == "owned_house":
        return {"success": False, "reason": "invalid_housing_type_for_rent",
                "rentable": ["inn", "rented_room"]}

    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    location = session.get(Location, location_id)
    if not location:
        return {"success": False, "reason": "location_not_found"}

    now = _utcnow()
    expires_at = now + timedelta(hours=duration_hours)

    existing = _get_housing(session, entity_id)
    if existing:
        existing.location_id = location_id
        existing.housing_type = housing_type
        existing.expires_at = expires_at
        existing.rented_at = now
        existing.is_inside = False
        session.add(existing)
    else:
        existing = PlayerHousing(
            entity_id=entity_id, location_id=location_id,
            housing_type=housing_type, is_safe_zone=True,
            is_inside=False, expires_at=expires_at, rented_at=now,
        )
        session.add(existing)

    session.commit()
    session.refresh(existing)
    return {
        "success": True,
        "housing_id": existing.id,
        "housing_type": housing_type,
        "location_id": location_id,
        "expires_at": expires_at.isoformat(),
        "is_safe_zone": True,
    }


def buy_housing(
    session: Session,
    entity_id: int,
    location_id: int,
) -> dict:
    """
    Purchase a permanent house. expires_at=None (never expires).
    Deducts gold via economy_service (house cost = 5000 gold).
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    location = session.get(Location, location_id)
    if not location:
        return {"success": False, "reason": "location_not_found"}

    HOUSE_COST = 5000
    from app.db.economy_service import get_or_create_wallet
    wallet = get_or_create_wallet(session, entity_id)
    if wallet.balance < HOUSE_COST:
        return {"success": False, "reason": "insufficient_funds",
                "have": wallet.balance, "need": HOUSE_COST}

    wallet.balance -= HOUSE_COST
    session.add(wallet)

    existing = _get_housing(session, entity_id)
    if existing:
        existing.location_id = location_id
        existing.housing_type = "owned_house"
        existing.expires_at = None
        existing.is_inside = False
        existing.rented_at = _utcnow()
        session.add(existing)
    else:
        existing = PlayerHousing(
            entity_id=entity_id, location_id=location_id,
            housing_type="owned_house", is_safe_zone=True,
            is_inside=False, expires_at=None,
        )
        session.add(existing)

    session.commit()
    session.refresh(existing)
    return {
        "success": True,
        "housing_id": existing.id,
        "housing_type": "owned_house",
        "location_id": location_id,
        "permanent": True,
        "gold_spent": HOUSE_COST,
        "wallet_balance": wallet.balance,
    }


def enter_housing(session: Session, entity_id: int) -> dict:
    """
    Move player inside their housing → activates safe zone.
    Blocks if housing is expired. Updates entity location to housing location.
    """
    housing = _get_housing(session, entity_id)
    if not housing:
        return {"success": False, "reason": "no_housing_assigned"}
    if not _housing_valid(housing):
        housing.is_inside = False
        session.add(housing)
        session.commit()
        return {"success": False, "reason": "housing_expired"}

    entity = session.get(TarotEntity, entity_id)
    if entity:
        entity.current_location_id = housing.location_id
        session.add(entity)

    housing.is_inside = True
    session.add(housing)
    session.commit()
    return {
        "success": True,
        "is_inside": True,
        "is_safe_zone": housing.is_safe_zone,
        "location_id": housing.location_id,
        "housing_type": housing.housing_type,
        "night_risk_nullified": True,
    }


def exit_housing(session: Session, entity_id: int) -> dict:
    """Mark player as outside housing. Night modifiers resume."""
    housing = _get_housing(session, entity_id)
    if not housing or not housing.is_inside:
        return {"success": False, "reason": "not_currently_inside"}

    housing.is_inside = False
    session.add(housing)
    session.commit()
    dn = check_day_night(session)
    return {
        "success": True,
        "is_inside": False,
        "night_risk_active": dn["is_night"],
        "gm_hint": "Night is approaching. Seek shelter." if dn["is_night"] else None,
    }


def is_player_sheltered(session: Session, entity_id: int) -> bool:
    """
    True if player is inside valid housing (safe zone active).
    Used by event spawn and combat systems to suppress night modifiers.
    """
    housing = _get_housing(session, entity_id)
    if not housing or not housing.is_inside:
        return False
    return _housing_valid(housing)


# =============================================================
# DREAMSCAPE
# =============================================================

def _get_dream_state(session: Session, entity_id: int) -> DreamState:
    ds = session.exec(
        select(DreamState).where(DreamState.entity_id == entity_id)
    ).first()
    if not ds:
        ds = DreamState(entity_id=entity_id, dream_progress_flag="{}")
        session.add(ds)
        session.flush()
    return ds


def _get_dreamscape_location(session: Session) -> Optional[Location]:
    return session.exec(
        select(Location).where(Location.name == DREAMSCAPE_LOCATION_NAME)
    ).first()


def unlock_dreamscape(session: Session, entity_id: int) -> dict:
    """
    Mark the Dreamscape as unlocked for an entity.
    Called by the story enforcer when the required main quest milestone fires.
    """
    ds = _get_dream_state(session, entity_id)
    if ds.has_unlocked:
        return {"success": True, "already_unlocked": True}
    ds.has_unlocked = True
    session.add(ds)
    session.commit()
    return {"success": True, "unlocked": True, "entity_id": entity_id}


def try_enter_dream(session: Session, entity_id: int) -> dict:
    """
    Probabilistic Dreamscape entry gate. Called each player interaction.

    Gate checks (all must pass):
      1. has_unlocked == True
      2. is_night == True
      3. not currently in combat (CombatState check)
      4. not currently in dreamscape already
      5. random roll < DREAM_BASE_CHANCE

    Returns entry result or {"entered": False, "reason": ...}.
    """
    ds = _get_dream_state(session, entity_id)

    if not ds.has_unlocked:
        return {"entered": False, "reason": "dreamscape_not_unlocked"}

    if ds.is_in_dreamscape:
        return {"entered": False, "reason": "already_in_dreamscape"}

    dn = check_day_night(session)
    if not dn["is_night"]:
        return {"entered": False, "reason": "only_possible_at_night"}

    # Combat check — don't interrupt active combat
    from app.db.models import CombatState
    active_combat = session.exec(
        select(CombatState).where(
            CombatState.is_active == True  # noqa: E712
        )
    ).first()
    # If entity is a participant in active combat, block
    if active_combat:
        from app.db.models import CombatParticipant
        participant = session.exec(
            select(CombatParticipant).where(
                CombatParticipant.combat_id == active_combat.id,
                CombatParticipant.entity_id == entity_id,
            )
        ).first()
        if participant:
            return {"entered": False, "reason": "cannot_enter_during_combat"}

    # Cooldown: at least 30 game-minutes since last entry
    if ds.last_entered:
        wt = get_world_time(session)
        last = ds.last_entered
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        game_now = wt.current_time
        if game_now.tzinfo is None:
            game_now = game_now.replace(tzinfo=timezone.utc)
        elapsed_game_mins = (game_now - last).total_seconds() / 60
        if elapsed_game_mins < 30:
            return {"entered": False, "reason": "dream_cooldown",
                    "minutes_remaining": round(30 - elapsed_game_mins, 1)}

    # Probabilistic roll
    if random.random() >= DREAM_BASE_CHANCE:
        return {"entered": False, "reason": "chance_not_triggered"}

    return enter_dreamscape(session, entity_id)


def enter_dreamscape(session: Session, entity_id: int) -> dict:
    """
    Deterministic Dreamscape entry.
    - Saves current location as pre_dream_location_id
    - Moves entity to Dreamscape location
    - Sets is_in_dreamscape = True
    - Dreamscape is magic-restricted + no combat + no inventory
    """
    ds = _get_dream_state(session, entity_id)

    if ds.is_in_dreamscape:
        return {"success": False, "reason": "already_in_dreamscape"}

    dream_loc = _get_dreamscape_location(session)
    if not dream_loc:
        # Auto-create the Dreamscape location if it doesn't exist
        dream_loc = Location(
            name=DREAMSCAPE_LOCATION_NAME,
            description=(
                "A realm between consciousness and reality. "
                "Magic does not function here. Only the mind travels freely."
            ),
            x=9999.0, y=9999.0, radius=500.0,
            is_safe_zone=True, is_magic_restricted=True,
            location_type="void",
        )
        session.add(dream_loc)
        session.flush()

    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    # Save current location
    ds.pre_dream_location_id = entity.current_location_id
    ds.is_in_dreamscape = True
    ds.last_entered = get_world_time(session).current_time
    session.add(ds)

    # Move entity
    entity.current_location_id = dream_loc.id
    session.add(entity)

    session.commit()
    return {
        "entered": True,
        "success": True,
        "entity_id": entity_id,
        "dreamscape_location_id": dream_loc.id,
        "restrictions": {
            "combat": False,
            "inventory": False,
            "abilities": False,
            "mana_usage": False,
        },
        "narrative_prompt": (
            "You close your eyes and the world dissolves. "
            "A realm of shifting light and impossible geometry opens before you. "
            "Here, only thought and will carry meaning."
        ),
    }


def exit_dreamscape(session: Session, entity_id: int) -> dict:
    """
    Return entity to pre_dream_location_id, clear dreamscape state.
    """
    ds = _get_dream_state(session, entity_id)
    if not ds.is_in_dreamscape:
        return {"success": False, "reason": "not_in_dreamscape"}

    entity = session.get(TarotEntity, entity_id)
    if entity and ds.pre_dream_location_id:
        entity.current_location_id = ds.pre_dream_location_id
        session.add(entity)

    ds.is_in_dreamscape = False
    ds.pre_dream_location_id = None
    session.add(ds)
    session.commit()

    dn = check_day_night(session)
    return {
        "success": True,
        "returned_to_location_id": entity.current_location_id if entity else None,
        "is_night": dn["is_night"],
        "gm_hint": (
            "You wake gasping. The world feels vivid — too vivid. Night still holds."
            if dn["is_night"] else
            "Dawn breaks as you return. The dream fades, but its knowledge lingers."
        ),
    }


def set_dream_flag(
    session: Session,
    entity_id: int,
    key: str,
    value: Any,
) -> dict:
    """Persist a narrative flag inside DreamState.dream_progress_flag (JSON dict)."""
    ds = _get_dream_state(session, entity_id)
    flags: dict = json.loads(ds.dream_progress_flag or "{}")
    flags[key] = value
    ds.dream_progress_flag = json.dumps(flags)
    session.add(ds)
    session.commit()
    return {"success": True, "key": key, "value": value}


def get_dream_flags(session: Session, entity_id: int) -> dict:
    """Return all dream progress flags for an entity."""
    ds = _get_dream_state(session, entity_id)
    return json.loads(ds.dream_progress_flag or "{}")


def is_in_dreamscape(session: Session, entity_id: int) -> bool:
    """Quick check — used by GM, Arbiter, and combat system."""
    ds = session.exec(
        select(DreamState).where(DreamState.entity_id == entity_id)
    ).first()
    return bool(ds and ds.is_in_dreamscape)
