"""
app/db/tutorial_service.py
===========================
Tutorial pipeline: Elaris Hollow onboarding, phase gating, system locks,
and the TutorialEnforcer that intercepts GM context.

Public API
----------
State:
    get_tutorial_state(session, entity_id) -> TutorialState
    start_tutorial(session, entity_id) -> dict
    advance_phase(session, entity_id) -> dict
    set_phase_flag(session, entity_id, key, value) -> dict
    get_phase_flags(session, entity_id) -> dict
    is_tutorial_complete(session, entity_id) -> bool

Gate checks (called by every service before acting):
    check_system_access(session, entity_id, system_name) -> dict
    get_max_event_rarity(session, entity_id) -> str

TutorialEnforcer (GM hook):
    build_tutorial_context(session, entity_id) -> str
        ↳ Injected into GM scene_context before LLM call.
        ↳ Returns the mandatory phase narrative directive.

Global Clock note:
    ALL time-dependent logic calls time_service.update_time(session) first.
    This single lazy-tick call advances the global WorldTime clock and all
    time-dependent services (night cycle, travel, expiry) synchronise off it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.models import (
    TUTORIAL_MAX_RARITY,
    TUTORIAL_PHASES,
    TUTORIAL_SYSTEM_LOCKS,
    TarotEntity,
    TutorialState,
)

MAX_PHASE = 11


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# STATE MANAGEMENT
# =============================================================

def get_tutorial_state(session: Session, entity_id: int) -> TutorialState:
    """Return (or create) the TutorialState row for an entity."""
    ts = session.exec(
        select(TutorialState).where(TutorialState.entity_id == entity_id)
    ).first()
    if not ts:
        ts = TutorialState(entity_id=entity_id, phase=0, phase_data="{}")
        session.add(ts)
        session.commit()
        session.refresh(ts)
    return ts


def start_tutorial(session: Session, entity_id: int) -> dict:
    """
    Begin the tutorial for a new entity.
    Places entity in Elaris Hollow, sets phase=1.
    Idempotent — skips if already started.
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    ts = get_tutorial_state(session, entity_id)
    if ts.phase >= 1:
        return {"success": True, "already_started": True, "phase": ts.phase}

    # Place entity in Elaris Hollow
    from app.db.models import Location
    elaris = session.exec(
        select(Location).where(Location.name == "Elaris Hollow")
    ).first()
    if elaris:
        entity.current_location_id = elaris.id
        session.add(entity)

    ts.phase = 1
    ts.started_at = _utcnow()
    session.add(ts)
    session.commit()

    return {
        "success": True,
        "phase": 1,
        "phase_name": TUTORIAL_PHASES[1],
        "location": "Elaris Hollow",
        "directive": _phase_directive(1),
    }


def advance_phase(session: Session, entity_id: int) -> dict:
    """
    Advance tutorial one phase. Cannot skip. Cannot exceed MAX_PHASE.
    Returns new phase + directive injected into next GM response.
    """
    ts = get_tutorial_state(session, entity_id)
    if ts.phase >= MAX_PHASE:
        return {"success": True, "already_complete": True, "phase": ts.phase}

    ts.phase += 1
    if ts.phase == MAX_PHASE:
        ts.completed_at = _utcnow()
    session.add(ts)
    session.commit()

    return {
        "success": True,
        "phase": ts.phase,
        "phase_name": TUTORIAL_PHASES[ts.phase],
        "directive": _phase_directive(ts.phase),
    }


def set_phase_flag(
    session: Session, entity_id: int, key: str, value: Any
) -> dict:
    """Store arbitrary per-phase state inside phase_data JSON."""
    ts = get_tutorial_state(session, entity_id)
    data: dict = json.loads(ts.phase_data or "{}")
    data[key] = value
    ts.phase_data = json.dumps(data)
    session.add(ts)
    session.commit()
    return {"success": True, "key": key, "value": value}


def get_phase_flags(session: Session, entity_id: int) -> dict:
    ts = get_tutorial_state(session, entity_id)
    return json.loads(ts.phase_data or "{}")


def is_tutorial_complete(session: Session, entity_id: int) -> bool:
    ts = get_tutorial_state(session, entity_id)
    return ts.phase >= MAX_PHASE


# =============================================================
# GATE CHECKS
# =============================================================

def check_system_access(
    session: Session, entity_id: int, system_name: str
) -> dict:
    """
    Returns {"allowed": bool, "reason": str}.
    Called by guild_service, economy_service, event_service before acting.
    """
    ts = get_tutorial_state(session, entity_id)
    required_phase = TUTORIAL_SYSTEM_LOCKS.get(system_name)
    if required_phase is None:
        return {"allowed": True, "reason": "system_not_gated"}

    if ts.phase >= required_phase:
        return {"allowed": True, "reason": "phase_cleared"}

    return {
        "allowed": False,
        "reason": "tutorial_gate",
        "current_phase": ts.phase,
        "current_phase_name": TUTORIAL_PHASES.get(ts.phase, "unknown"),
        "required_phase": required_phase,
        "required_phase_name": TUTORIAL_PHASES.get(required_phase, "unknown"),
        "hint": "Continue your journey in Elaris Hollow to unlock this.",
    }


def get_max_event_rarity(session: Session, entity_id: int) -> str:
    """
    Returns the maximum event rarity the entity may encounter.
    "common" during early tutorial, "epic" after completion.
    """
    ts = get_tutorial_state(session, entity_id)
    return TUTORIAL_MAX_RARITY.get(ts.phase, "common")


# =============================================================
# PHASE DIRECTIVES (injected into GM context)
# =============================================================

# Each directive is a GM system prompt override for that phase.
# Written as narrative instructions, NOT mechanic explanations.
_PHASE_DIRECTIVES: dict[int, str] = {
    0: "",
    1: (
        "TUTORIAL PHASE 1 — AWAKENING\n"
        "The player has just woken up in a small room at the Broken Lantern Inn in Elaris Hollow. "
        "They feel disoriented. A strange dream lingers — fragments of cards, light, and voices. "
        "DO NOT explain any mechanics. "
        "Describe only the immediate environment: the rough wooden walls, morning light through a cracked shutter, "
        "the smell of woodsmoke, and a distant sound from outside. "
        "End with a prompt that makes the player want to step outside."
    ),
    2: (
        "TUTORIAL PHASE 2 — FIRST INTERACTION\n"
        "The player has entered Old Well Square. "
        "A merchant named Callum — stocky, around fifty, salt-and-pepper beard, patched trader's vest — "
        "is anxiously pacing near the old stone well. "
        "He notices the player and addresses them: his cart was raided during the night, "
        "and a small lockbox of trade samples was left behind in the Whispering Forest Edge. "
        "He asks the player to retrieve it — nothing dangerous, he says, though he looks uncertain. "
        "ALWAYS refer to the merchant as Callum. Never invent a different name or appearance for him. "
        "DO NOT mention quest systems, objectives, or UI elements. "
        "Let Callum speak naturally. The player must feel like they are helping a person, not accepting a task."
    ),
    3: (
        "TUTORIAL PHASE 3 — FIRST TASK\n"
        "The player is heading toward the Whispering Forest Edge. "
        "Describe the transition: the village sounds fade, the path narrows, trees close in. "
        "The lockbox is visible near an old log — partially hidden by undergrowth. "
        "Before they reach it, something moves in the shadows. "
        "DO NOT name it yet. Build tension. Let the player decide whether to grab the box or investigate."
    ),
    4: (
        "TUTORIAL PHASE 4 — FIRST COMBAT\n"
        "A weakened forest predator — a Hollow Stalker — lunges from the brush. "
        "Captain Oren (the village guard, nearby on patrol) calls out: "
        "\"Focus. Don't panic. Strike when it moves — not before.\"\n"
        "Run a single combat encounter. The Hollow Stalker is WEAK — level 1, minimal health. "
        "The player MUST win this encounter. Do NOT allow the player to lose. "
        "Describe the fight with weight and consequence even if brief. "
        "After victory, let the scene breathe — the player has just survived their first real danger."
    ),
    5: (
        "TUTORIAL PHASE 5 — FIRST REWARD\n"
        "The player returns to Old Well Square with Callum's lockbox. "
        "Callum is relieved, grateful. He presses a small coin pouch and a worn leather satchel into "
        "the player's hands, saying he has no better way to thank them. "
        "DO NOT name XP, inventory slots, or item stats. "
        "The player simply has new things. Let them feel the weight of earning something."
    ),
    6: (
        "TUTORIAL PHASE 6 — ECONOMY INTRODUCTION\n"
        "Callum opens his modest market stall — a few crates of goods arranged on a cloth. "
        "He explains he buys and sells what travelers need, and gestures at his wares. "
        "Let the player browse and trade naturally. "
        "DO NOT show price lists or menu prompts. "
        "Callum names prices conversationally: 'That one? Four marks. Fair for the quality.'"
    ),
    7: (
        "TUTORIAL PHASE 7 — HOUSING INTRODUCTION\n"
        "MANDATORY GM INSTRUCTION: The sky is visibly darkening. You MUST include the line: "
        "\"The light is fading. You should find shelter.\"\n"
        "Direct the player toward the Broken Lantern Inn. "
        "The innkeeper, a broad woman named Maren, is already lighting lamps at the entrance. "
        "She offers a room for the night — simple, safe, warm. "
        "She names a small price. Nothing threatening. "
        "DO NOT describe the rental UI. The player pays Maren directly in the story."
    ),
    8: (
        "TUTORIAL PHASE 8 — NIGHT SYSTEM\n"
        "Night has fully fallen over Elaris Hollow. "
        "If the player is inside (sheltered), describe the muffled sounds of the dark outside — "
        "safe and distant. "
        "If the player is still outside: describe shadows deepening, distant sounds of movement, "
        "the feeling of being watched. A minor ambush event IS possible. "
        "Enemies are slightly stronger at night — narrate this through atmosphere, not numbers. "
        "Never break narrative to explain the night multiplier."
    ),
    9: (
        "TUTORIAL PHASE 9 — FIRST DUNGEON (OPTIONAL)\n"
        "The Ruins of Velkar lie at the eastern edge of Elaris Hollow — "
        "crumbled stone walls half-consumed by roots. "
        "It is quiet. Something was here long ago. "
        "The exploration is low-risk but not empty: a hidden cache, a carved symbol, "
        "a passage that goes deeper than expected. "
        "Let the player explore at their pace. Reward curiosity with small finds. "
        "This is optional — if the player does not seek it, do not force it."
    ),
    10: (
        "TUTORIAL PHASE 10 — DREAM HOOK\n"
        "The Old Seer, a hunched figure who sits near the Abandoned Shrine at the hollow's edge, "
        "speaks without being addressed first. "
        "She says only: 'You have seen it before, haven't you? The space behind closed eyes.' "
        "She does not explain. She does not elaborate. She turns away. "
        "The Dreamscape does NOT activate. "
        "DO NOT mention dream mechanics. This is foreshadowing only — atmosphere, not instruction."
    ),
    11: (
        "TUTORIAL PHASE 11 — COMPLETE\n"
        "The player has experienced everything Elaris Hollow has to offer. "
        "The world beyond the hollow is now open. "
        "Describe the horizon: distant towers, roads leading north and east, "
        "the smell of unfamiliar places on the wind. "
        "The player is ready. Do not say so explicitly — let the world's openness communicate it."
    ),
}


def _phase_directive(phase: int) -> str:
    return _PHASE_DIRECTIVES.get(phase, "")


# =============================================================
# TUTORIAL ENFORCER — GM CONTEXT HOOK
# =============================================================

def build_tutorial_context(session: Session, entity_id: int) -> str:
    """
    Called by build_gm_context() before every GM LLM call.
    Returns a tutorial directive block to prepend to scene_context.

    If tutorial is complete → returns empty string (no interference).
    If active → returns the current phase's mandatory GM directive.

    Also advances the global clock via lazy-tick.
    """
    # Global clock lazy-tick — synchronises all time-dependent services
    from app.db.time_service import update_time, check_day_night
    try:
        update_time(session)
    except Exception:
        pass

    ts = get_tutorial_state(session, entity_id)
    if ts.phase == 0:
        return ""   # not started yet
    if ts.phase >= MAX_PHASE:
        return ""   # tutorial over — GM runs free

    phase_data: dict = json.loads(ts.phase_data or "{}")
    directive = _phase_directive_stateful(ts.phase, phase_data)
    dn = check_day_night(session)
    night_warning = (
        "\n[SYSTEM: It is currently NIGHT. "
        "If player is outside, you MUST hint that shelter is advisable. "
        "Night risk multiplier is active.]\n"
        if dn["is_night"] and ts.phase >= 7 else ""
    )

    return (
        f"[TUTORIAL CONTROL — PHASE {ts.phase}: "
        f"{TUTORIAL_PHASES.get(ts.phase, 'unknown').upper()}]\n"
        f"{directive}"
        f"{night_warning}"
        f"\n[SYSTEM LOCKS ACTIVE: {_active_locks_summary(ts.phase)}]"
    )


def _active_locks_summary(phase: int) -> str:
    locked = [
        sys for sys, req in TUTORIAL_SYSTEM_LOCKS.items() if phase < req
    ]
    return ", ".join(locked) if locked else "none"


# Prepended to any phase directive after the first turn in that phase.
# Instructs the GM not to re-introduce NPCs or re-describe the scene,
# while still providing the full phase context as background reference.
# Works for ALL phases without any per-phase special-casing.
_CONTINUING_PREFIX = (
    "[SCENE ALREADY ESTABLISHED — DO NOT RESET]\n"
    "The opening of this phase has already been narrated to the player. "
    "Do NOT re-introduce any NPCs, re-describe the environment, or repeat any backstory. "
    "Any named character keeps their exact name and appearance from their first introduction — "
    "do not invent a new description. "
    "Respond directly to the player's current action and continue the scene naturally.\n"
    "The following is reference context for this phase (not a re-narration instruction):\n"
)


def _phase_directive_stateful(phase: int, phase_data: dict) -> str:
    """
    Generic stateful directive selector.

    Turn 0 of a phase  → return the full intro directive verbatim.
    Turn 1+ of a phase → prepend _CONTINUING_PREFIX to the intro directive.

    This single function handles every phase (2–11) without any per-phase
    branching, so new phases or NPC introductions are automatically covered.
    """
    base = _PHASE_DIRECTIVES.get(phase, "")
    if not base:
        return base

    turns_done = phase_data.get(f"turns_in_phase_{phase}", 0)
    if turns_done == 0:
        return base   # First turn: present the full scene-setting directive

    # Subsequent turns: tell the GM the scene is established, keep context as ref
    return _CONTINUING_PREFIX + base


# =============================================================
# AUTO-ADVANCE HOOKS (called by other services)
# =============================================================

def on_location_entered(session: Session, entity_id: int, location_name: str) -> dict:
    """
    Called by travel service when entity enters a location.
    Checks if location matches a phase advancement trigger.
    """
    ts = get_tutorial_state(session, entity_id)
    triggers = {
        "Old Well Square":           2,
        "Whispering Forest Edge":    3,
        "Ruins of Velkar":           9,
        "Abandoned Shrine":          10,
    }
    required_phase = triggers.get(location_name)
    if required_phase and ts.phase == required_phase - 1:
        return advance_phase(session, entity_id)
    return {"success": False, "reason": "no_phase_trigger", "location": location_name}


def on_combat_won(session: Session, entity_id: int) -> dict:
    """Called by combat engine after a combat victory. Advances phase 3→4→5."""
    ts = get_tutorial_state(session, entity_id)
    if ts.phase == 4:   # first combat complete → reward phase
        return advance_phase(session, entity_id)
    return {"success": False, "reason": "not_combat_phase"}


def on_item_returned(session: Session, entity_id: int) -> dict:
    """Called when player delivers item to Callum (phase 3 task complete)."""
    ts = get_tutorial_state(session, entity_id)
    if ts.phase == 3:
        set_phase_flag(session, entity_id, "item_retrieved", True)
        return advance_phase(session, entity_id)   # → phase 4: first combat
    return {"success": False, "reason": "wrong_phase"}


def on_housing_rented(session: Session, entity_id: int) -> dict:
    """Called by time_service.rent_housing() after successful rental."""
    ts = get_tutorial_state(session, entity_id)
    if ts.phase == 7:
        return advance_phase(session, entity_id)   # → phase 8: night system
    return {"success": False, "reason": "wrong_phase"}


def on_trade_completed(session: Session, entity_id: int) -> dict:
    """Called by economy_service after any buy/sell during phase 6."""
    ts = get_tutorial_state(session, entity_id)
    if ts.phase == 6:
        return advance_phase(session, entity_id)   # → phase 7: housing intro
    return {"success": False, "reason": "wrong_phase"}


# =============================================================
# TURN-BASED AUTO-ADVANCE (called once per player message)
# =============================================================

# Minimum player turns before a phase can auto-advance.
# Phase 1 is handled separately in handlers.py (instant after Awakening).
_PHASE_MIN_TURNS: dict[int, int] = {
    2: 3,   # After 3 turns in Phase 2 (Callum encounter), head to Forest
    3: 3,   # After 3 turns in Phase 3 (approaching Forest), combat starts
    4: 2,   # After 2 turns in Phase 4 (combat), reward follows
    5: 2,   # After 2 turns in Phase 5 (reward), economy opens
    6: 3,   # After 3 turns in Phase 6 (economy), housing intro
    7: 2,   # After 2 turns in Phase 7 (housing), night system
    8: 3,   # After 3 turns in Phase 8 (night), optional dungeon
    9: 2,   # After 2 turns in Phase 9 (dungeon), dream hook
    10: 2,  # After 2 turns in Phase 10 (dream), tutorial complete
}


def tick_phase_turn(session: Session, entity_id: int) -> dict:
    """
    Called once per player message (after the GM has responded).
    Increments the per-phase turn counter stored in phase_data.
    When the counter reaches the phase minimum, auto-advances to the next phase.

    Returns {"advanced": bool, "new_phase": int | None}.
    """
    ts = get_tutorial_state(session, entity_id)
    phase = ts.phase

    # Only auto-advance phases that have a turn minimum defined
    min_turns = _PHASE_MIN_TURNS.get(phase)
    if min_turns is None:
        return {"advanced": False, "new_phase": None}

    data: dict = json.loads(ts.phase_data or "{}")
    turns_key = f"turns_in_phase_{phase}"
    turns = data.get(turns_key, 0) + 1
    data[turns_key] = turns
    ts.phase_data = json.dumps(data)
    session.add(ts)
    session.commit()

    if turns >= min_turns:
        result = advance_phase(session, entity_id)
        return {"advanced": True, "new_phase": result.get("phase")}

    return {"advanced": False, "new_phase": None, "turns": turns, "min": min_turns}

