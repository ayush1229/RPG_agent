"""
app/db/world_service.py
========================
World simulation service — travel, factions, wars, sovereign influence, events.

Lazy-tick design: simulation advances ONLY when a player interacts.
Every call begins with process_world_delta(delta_seconds) to catch up.

Public API
----------
Travel:
    travel_entity(session, entity_id, target_x, target_y, *, terrain, speed, location_id)
    resolve_travel(session, entity_id)          # completes journey if end_time reached
    get_travel_state(session, entity_id)

Factions:
    create_faction(session, ...)
    set_relation(session, faction_a_id, faction_b_id, relation)
    get_relation(session, faction_a_id, faction_b_id) -> int
    update_control(session, location_id, faction_id, delta)

Wars:
    start_war(session, faction_a_id, faction_b_id)
    end_war(session, war_id, *, reason)

Sovereign influence:
    apply_sovereign_influence(session, sovereign_id, location_id, delta)
    get_location_status(session, location_id) -> dict

Events:
    trigger_event(session, name, location_id, event_type, duration_seconds)
    get_active_events(session, location_id) -> list[dict]

Simulation:
    process_world_delta(session, delta_seconds)   # main lazy-tick entry point
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Optional

from sqlmodel import Session, col, select

from app.db.models import (
    EVENT_EFFECTS,
    TERRAIN_MODIFIERS,
    WORLD_EVENT_TYPES,
    Faction,
    FactionRelation,
    Location,
    SovereignInfluence,
    TarotEntity,
    TerritoryControl,
    TravelState,
    War,
    WorldEvent,
    WorldMap,
)

# ── Constants ─────────────────────────────────────────────────────────────────
HOSTILE_THRESHOLD = -50
ALLIED_THRESHOLD = 50
INSTABILITY_THRESHOLD = 70.0       # sovereign influence > this → unstable
WAR_CONTROL_SHIFT_PER_MINUTE = 0.5  # control transferred per minute of war
SOVEREIGN_DECAY_INTERVAL = 60.0    # seconds between decay ticks
DEFAULT_PLAYER_SPEED = 10.0        # world-units per second


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# DISTANCE & TRAVEL TIME
# =============================================================

def calculate_distance(ax: float, ay: float, bx: float, by: float) -> float:
    return sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def calculate_travel_time(
    distance: float,
    speed: float = DEFAULT_PLAYER_SPEED,
    terrain_type: str = "plains",
) -> float:
    """
    travel_time_seconds = distance / speed * terrain_modifier
    Returns 0.0 if already at destination.
    """
    if distance <= 0:
        return 0.0
    modifier = TERRAIN_MODIFIERS.get(terrain_type, 1.2)
    return (distance / max(speed, 0.01)) * modifier


# =============================================================
# TRAVEL
# =============================================================

def travel_entity(
    session: Session,
    entity_id: int,
    target_x: float,
    target_y: float,
    *,
    terrain_type: str = "plains",
    speed: float = DEFAULT_PLAYER_SPEED,
    target_location_id: Optional[int] = None,
) -> dict:
    """
    Start a travel journey. Blocks the entity (is_traveling flag via TravelState).
    Replaces any existing incomplete journey.
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    # Cancel existing journey if present
    existing = session.exec(
        select(TravelState).where(TravelState.entity_id == entity_id)
    ).first()
    if existing and not existing.is_completed:
        session.delete(existing)
        session.flush()

    dist = calculate_distance(entity.pos_x, entity.pos_y, target_x, target_y)
    if dist == 0.0:
        # Already there — snap location
        if target_location_id:
            entity.current_location_id = target_location_id
            session.add(entity)
            session.commit()
        return {"success": True, "travel_time_seconds": 0, "already_there": True}

    travel_time = calculate_travel_time(dist, speed, terrain_type)
    now = _utcnow()
    end_time = now + timedelta(seconds=travel_time)

    travel = TravelState(
        entity_id=entity_id,
        start_x=entity.pos_x,
        start_y=entity.pos_y,
        target_x=target_x,
        target_y=target_y,
        target_location_id=target_location_id,
        terrain_type=terrain_type,
        speed=speed,
        travel_time_seconds=travel_time,
        start_time=now,
        end_time=end_time,
        is_completed=False,
    )
    session.add(travel)
    session.commit()
    session.refresh(travel)

    return {
        "success": True,
        "travel_id": travel.id,
        "distance": round(dist, 2),
        "terrain_type": terrain_type,
        "travel_time_seconds": round(travel_time, 2),
        "eta": end_time.isoformat(),
        "is_traveling": True,
    }


def resolve_travel(session: Session, entity_id: int) -> dict:
    """
    Complete the journey if end_time has been reached.
    Updates entity position + current_location_id.
    """
    travel = session.exec(
        select(TravelState).where(
            TravelState.entity_id == entity_id,
            TravelState.is_completed == False,  # noqa: E712
        )
    ).first()

    if not travel:
        return {"success": False, "reason": "no_active_journey"}

    now = _utcnow()
    end_time = travel.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    if now < end_time:
        remaining = (end_time - now).total_seconds()
        return {
            "success": False,
            "reason": "journey_not_complete",
            "seconds_remaining": round(remaining, 1),
        }

    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    entity.pos_x = travel.target_x
    entity.pos_y = travel.target_y
    if travel.target_location_id:
        entity.current_location_id = travel.target_location_id
    travel.is_completed = True

    session.add(entity)
    session.add(travel)
    session.commit()

    return {
        "success": True,
        "arrived_at": {"x": entity.pos_x, "y": entity.pos_y},
        "location_id": entity.current_location_id,
    }


def get_travel_state(session: Session, entity_id: int) -> dict:
    travel = session.exec(
        select(TravelState).where(
            TravelState.entity_id == entity_id,
            TravelState.is_completed == False,  # noqa: E712
        )
    ).first()
    if not travel:
        return {"is_traveling": False}
    now = _utcnow()
    end_time = travel.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    remaining = max(0.0, (end_time - now).total_seconds())
    elapsed = travel.travel_time_seconds - remaining
    progress = min(1.0, elapsed / travel.travel_time_seconds) if travel.travel_time_seconds > 0 else 1.0
    return {
        "is_traveling": True,
        "target_x": travel.target_x,
        "target_y": travel.target_y,
        "target_location_id": travel.target_location_id,
        "seconds_remaining": round(remaining, 1),
        "progress_pct": round(progress * 100, 1),
        "eta": end_time.isoformat(),
    }


# =============================================================
# FACTIONS
# =============================================================

def create_faction(
    session: Session,
    name: str,
    description: str = "",
    alignment: str = "neutral",
    ruler_id: Optional[int] = None,
    home_location_id: Optional[int] = None,
) -> dict:
    existing = session.exec(select(Faction).where(Faction.name == name)).first()
    if existing:
        return {"success": False, "reason": "faction_already_exists", "faction_id": existing.id}
    if alignment not in {"order", "chaos", "neutral"}:
        return {"success": False, "reason": "invalid_alignment"}
    faction = Faction(
        name=name, description=description, alignment=alignment,
        ruler_id=ruler_id, home_location_id=home_location_id,
    )
    session.add(faction)
    session.commit()
    session.refresh(faction)
    return {"success": True, "faction_id": faction.id, "name": faction.name}


def _canonical_ids(a: int, b: int) -> tuple[int, int]:
    """Ensure faction_a < faction_b for unique pair indexing."""
    return (a, b) if a < b else (b, a)


def set_relation(session: Session, faction_a_id: int, faction_b_id: int, relation: int) -> dict:
    """Set diplomatic relation (-100 to +100). Clamped automatically."""
    if faction_a_id == faction_b_id:
        return {"success": False, "reason": "same_faction"}
    relation = max(-100, min(100, relation))
    a, b = _canonical_ids(faction_a_id, faction_b_id)
    row = session.exec(
        select(FactionRelation).where(
            FactionRelation.faction_a_id == a,
            FactionRelation.faction_b_id == b,
        )
    ).first()
    if row:
        row.relation = relation
    else:
        row = FactionRelation(faction_a_id=a, faction_b_id=b, relation=relation)
    session.add(row)
    session.commit()
    status = "hostile" if relation <= HOSTILE_THRESHOLD else ("allied" if relation >= ALLIED_THRESHOLD else "neutral")
    return {"success": True, "relation": relation, "status": status}


def get_relation(session: Session, faction_a_id: int, faction_b_id: int) -> int:
    """Return current relation value (0 if no row exists)."""
    a, b = _canonical_ids(faction_a_id, faction_b_id)
    row = session.exec(
        select(FactionRelation).where(
            FactionRelation.faction_a_id == a,
            FactionRelation.faction_b_id == b,
        )
    ).first()
    return row.relation if row else 0


def update_control(
    session: Session,
    location_id: int,
    faction_id: int,
    delta: float,  # positive = gain, negative = lose
) -> dict:
    """Shift a faction's territory control value by delta. Clamped to 0–100."""
    row = session.exec(
        select(TerritoryControl).where(
            TerritoryControl.location_id == location_id,
            TerritoryControl.faction_id == faction_id,
        )
    ).first()
    if not row:
        row = TerritoryControl(location_id=location_id, faction_id=faction_id, control_value=0.0)
    row.control_value = max(0.0, min(100.0, row.control_value + delta))
    session.add(row)
    session.commit()
    return {
        "success": True,
        "location_id": location_id,
        "faction_id": faction_id,
        "control_value": row.control_value,
        "is_controlled": row.control_value > 50,
    }


def get_dominant_faction(session: Session, location_id: int) -> Optional[int]:
    """Return the faction_id with highest control_value > 50, or None."""
    rows = session.exec(
        select(TerritoryControl).where(TerritoryControl.location_id == location_id)
    ).all()
    if not rows:
        return None
    best = max(rows, key=lambda r: r.control_value)
    return best.faction_id if best.control_value > 50 else None


# =============================================================
# WARS
# =============================================================

def start_war(session: Session, faction_a_id: int, faction_b_id: int) -> dict:
    """
    Declare war. Requires FactionRelation.relation <= -50.
    Only one active war per pair is allowed.
    """
    if faction_a_id == faction_b_id:
        return {"success": False, "reason": "same_faction"}

    rel = get_relation(session, faction_a_id, faction_b_id)
    if rel > HOSTILE_THRESHOLD:
        return {
            "success": False, "reason": "relation_not_hostile",
            "current_relation": rel, "required": f"<= {HOSTILE_THRESHOLD}",
        }

    a, b = _canonical_ids(faction_a_id, faction_b_id)
    existing = session.exec(
        select(War).where(
            War.faction_a_id == a, War.faction_b_id == b, War.is_active == True  # noqa: E712
        )
    ).first()
    if existing:
        return {"success": False, "reason": "war_already_active", "war_id": existing.id}

    war = War(faction_a_id=a, faction_b_id=b, is_active=True)
    session.add(war)
    session.commit()
    session.refresh(war)

    # Spawn war event at each faction's home location
    for fid in (a, b):
        f = session.get(Faction, fid)
        if f and f.home_location_id:
            trigger_event(session, f"War: {war.id}", f.home_location_id, "war", 7200.0)

    return {"success": True, "war_id": war.id, "faction_a": a, "faction_b": b}


def end_war(session: Session, war_id: int, *, reason: str = "peace") -> dict:
    """Deactivate a war. Sets end_time and is_active=False."""
    war = session.get(War, war_id)
    if not war:
        return {"success": False, "reason": "war_not_found"}
    if not war.is_active:
        return {"success": False, "reason": "war_already_ended"}
    war.is_active = False
    war.end_time = _utcnow()
    session.add(war)
    session.commit()
    return {"success": True, "war_id": war_id, "reason": reason}


# =============================================================
# SOVEREIGN INFLUENCE
# =============================================================

def apply_sovereign_influence(
    session: Session,
    sovereign_entity_id: int,
    location_id: int,
    delta: float,  # direct addition (can be negative to weaken)
) -> dict:
    """Add delta to a Sovereign's influence over a location. Capped 0–100."""
    entity = session.get(TarotEntity, sovereign_entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}
    if not (entity.is_upright_sovereign or entity.is_reversed_sovereign):
        return {"success": False, "reason": "entity_is_not_sovereign"}

    row = session.exec(
        select(SovereignInfluence).where(
            SovereignInfluence.sovereign_entity_id == sovereign_entity_id,
            SovereignInfluence.location_id == location_id,
        )
    ).first()
    if not row:
        row = SovereignInfluence(
            sovereign_entity_id=sovereign_entity_id,
            location_id=location_id,
            influence_value=0.0,
        )
    row.influence_value = max(0.0, min(100.0, row.influence_value + delta))
    row.last_updated = _utcnow()
    session.add(row)
    session.commit()

    unstable = row.influence_value > INSTABILITY_THRESHOLD
    if unstable:
        trigger_event(
            session, f"Sovereign Distortion @ {location_id}",
            location_id, "sovereign", 1800.0,
        )

    return {
        "success": True,
        "location_id": location_id,
        "influence_value": row.influence_value,
        "is_unstable": unstable,
    }


def get_location_status(session: Session, location_id: int) -> dict:
    """
    Aggregate all dynamic modifiers for a location:
      - dominant faction + control value
      - sovereign influence (max across all sovereigns)
      - active events + their effects
    """
    dominant_faction = get_dominant_faction(session, location_id)

    inf_rows = session.exec(
        select(SovereignInfluence).where(SovereignInfluence.location_id == location_id)
    ).all()
    max_influence = max((r.influence_value for r in inf_rows), default=0.0)
    is_unstable = max_influence > INSTABILITY_THRESHOLD

    events = get_active_events(session, location_id)
    spawn_rate = 1.0
    travel_danger = 1.0
    reward_mult = 1.0
    for ev in events:
        eff = EVENT_EFFECTS.get(ev["event_type"], {})
        spawn_rate *= eff.get("spawn_rate", 1.0)
        travel_danger *= eff.get("travel_danger", 1.0)
        reward_mult *= eff.get("reward_mult", 1.0)

    return {
        "location_id": location_id,
        "dominant_faction_id": dominant_faction,
        "max_sovereign_influence": max_influence,
        "is_unstable": is_unstable,
        "active_events": len(events),
        "spawn_rate_mult": round(spawn_rate, 2),
        "travel_danger_mult": round(travel_danger, 2),
        "reward_mult": round(reward_mult, 2),
    }


# =============================================================
# WORLD EVENTS
# =============================================================

def trigger_event(
    session: Session,
    name: str,
    location_id: int,
    event_type: str,
    duration_seconds: float = 3600.0,
) -> dict:
    """Create a new WorldEvent at a location. Validates event_type."""
    if event_type not in WORLD_EVENT_TYPES:
        return {"success": False, "reason": "invalid_event_type",
                "valid_types": list(WORLD_EVENT_TYPES)}
    if duration_seconds <= 0:
        return {"success": False, "reason": "duration_must_be_positive"}
    event = WorldEvent(
        name=name,
        location_id=location_id,
        event_type=event_type,
        duration_seconds=duration_seconds,
        is_active=True,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return {
        "success": True,
        "event_id": event.id,
        "name": event.name,
        "event_type": event_type,
        "duration_seconds": duration_seconds,
        "effects": EVENT_EFFECTS.get(event_type, {}),
    }


def get_active_events(session: Session, location_id: int) -> list[dict]:
    events = session.exec(
        select(WorldEvent).where(
            WorldEvent.location_id == location_id,
            WorldEvent.is_active == True,  # noqa: E712
        )
    ).all()
    return [
        {"event_id": e.id, "name": e.name, "event_type": e.event_type,
         "duration_seconds": e.duration_seconds}
        for e in events
    ]


# =============================================================
# LAZY-TICK WORLD SIMULATION
# =============================================================

def _update_travel(session: Session, _delta: float) -> int:
    """Resolve all journeys whose end_time has passed. Returns completed count."""
    now = _utcnow()
    pending = session.exec(
        select(TravelState).where(TravelState.is_completed == False)  # noqa: E712
    ).all()
    completed = 0
    for travel in pending:
        end_time = travel.end_time
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        if now >= end_time:
            resolve_travel(session, travel.entity_id)
            completed += 1
    return completed


def _update_wars(session: Session, delta_seconds: float) -> None:
    """
    Shift territory control during active wars.
    Each minute of war = WAR_CONTROL_SHIFT_PER_MINUTE control points
    transferred from the losing side to the winning side.
    For simplicity: faction_a gains control at faction_b's home and vice versa.
    """
    wars = session.exec(select(War).where(War.is_active == True)).all()  # noqa: E712
    shift = WAR_CONTROL_SHIFT_PER_MINUTE * (delta_seconds / 60.0)
    for war in wars:
        war.total_ticks_seconds += delta_seconds
        session.add(war)
        # Shift control in both factions' home locations
        for attacker_id, defender_id in [
            (war.faction_a_id, war.faction_b_id),
            (war.faction_b_id, war.faction_a_id),
        ]:
            defender = session.get(Faction, defender_id)
            if defender and defender.home_location_id:
                update_control(session, defender.home_location_id, attacker_id, shift)
                update_control(session, defender.home_location_id, defender_id, -shift)


def _update_sovereign_influence(session: Session, delta_seconds: float) -> None:
    """Grow influence by growth_rate per 60s, decay by decay_rate per 60s."""
    rows = session.exec(select(SovereignInfluence)).all()
    minute_fraction = delta_seconds / 60.0
    for row in rows:
        # Net: grow if sovereign is active, else decay
        net = (row.growth_rate - row.decay_rate) * minute_fraction
        row.influence_value = max(0.0, min(100.0, row.influence_value + net))
        row.last_updated = _utcnow()
        session.add(row)


def _update_events(session: Session, delta_seconds: float) -> int:
    """Decay event durations. Deactivate expired events. Returns expired count."""
    events = session.exec(
        select(WorldEvent).where(WorldEvent.is_active == True)  # noqa: E712
    ).all()
    expired = 0
    for ev in events:
        ev.duration_seconds = max(0.0, ev.duration_seconds - delta_seconds)
        ev.last_ticked = _utcnow()
        if ev.duration_seconds <= 0:
            ev.is_active = False
            expired += 1
        session.add(ev)
    return expired


def process_world_delta(session: Session, delta_seconds: float) -> dict:
    """
    Main lazy-tick entry point.
    Called at the start of every player interaction with
    delta = (now - last_interaction_time).total_seconds()

    Processes in order:
      1. Travel resolution
      2. War progression
      3. Sovereign influence spread
      4. Event decay
    """
    if delta_seconds <= 0:
        return {"skipped": True}

    travels_completed = _update_travel(session, delta_seconds)
    _update_wars(session, delta_seconds)
    _update_sovereign_influence(session, delta_seconds)
    events_expired = _update_events(session, delta_seconds)
    session.commit()

    return {
        "delta_seconds": round(delta_seconds, 1),
        "travels_completed": travels_completed,
        "events_expired": events_expired,
    }
