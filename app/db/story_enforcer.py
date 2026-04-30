"""
app/db/story_enforcer.py
=========================
Narrative control layer — runs BEFORE the GM on every message.

Enforcement contract
---------------------
1. Load (or create) MainStoryState for the player entity.
2. Check mandatory prologue gates sequentially:
      interview_done → cards_drawn → awakening_triggered
3. If any gate is incomplete → return a forced narrative override response.
   The GM is NOT called.
4. After prologue, enforce arc-level sequential quest gating:
   - Player cannot receive a quest response for Arc N+1 content
     until Arc N's required quests are complete.
5. GM may suggest flag changes only when gm_override_allowed == True.

Return value
-------------
  None  → gates passed, GM may proceed normally.
  str   → forced override text to send directly to the player (GM bypassed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.models import (
    DEFAULT_STORY_FLAGS,
    ARC_LEVEL_RANGES,
    MainStoryState,
    Quest,
    QuestProgress,
    TarotEntity,
)

# ── Arc → list of quest names that MUST be completed to unlock next arc ───────
ARC_GATE_QUESTS: dict[int, list[str]] = {
    0: ["The Council Beyond Reality"],
    1: ["The First Spark", "Fragments of Fate", "Unstable Currents", "Echoes in the Crowd"],
    2: ["The Hidden Economy", "Trial of Balance", "The Broken Card", "Watcher in Silence"],
    3: ["Whispers of Sovereignty", "Lines of Control", "First Rival", "Fractured Allegiance"],
    4: ["Gather the Fragments", "The Controlled Collapse", "Echo of the Sovereign", "Claim of Presence"],
    5: ["War of Arcana", "Shattered Authority", "Core Resonance", "Breaking the Threshold"],
    6: ["The Hidden Sovereigns", "Unstable Balance", "The Final Rival"],
    7: ["Threshold of Power", "Sovereign Trial", "Ascension"],
}

# ── Prologue interview: ONE question per step ─────────────────────────────────

_Q1 = """[SYSTEM — NARRATIVE OVERRIDE]

The void is absolute. There is no up, no down, no time.

Five luminous figures materialise before you, each radiating a different energy frequency:
  • The Fool  — chaotic, joyful, flickering in and out of existence
  • The Magician — precise, calculating, surrounded by orbiting tools
  • The High Priestess — silent, her eyes holding centuries
  • The Emperor — armoured, immovable, radiating authority
  • The Star — warm, distant, inexhaustibly hopeful

The Magician speaks first: "Anomaly. You exist outside the distribution model."
The High Priestess adds, barely audible: "The energy knows you. It called you here."
The Emperor steps forward, his gaze unwavering:

"Answer our questions. Every choice you make shapes what you become."

Question 1 of 3 — The Emperor asks:

*"Do you seek power, or understanding?"*""".strip()

_Q2 = """[The High Priestess tilts her head. She has heard your first answer.]

Question 2 of 3 — The High Priestess asks:

*"Would you sacrifice others to secure control?"*""".strip()

_Q3 = """[The Fool stops flickering. Even chaos listens now.]

Question 3 of 3 — The Star asks, gently:

*"Do you trust fate — or do you defy it?"*""".strip()

_INTERVIEW_COMPLETE = """[The five Arcana exchange a glance. The Fool laughs softly.
"We have heard enough."

The void hums. Three cards rise from nothingness.]""".strip()

_CARD_DRAW_SCRIPT = """
[SYSTEM — CARD DRAW SEQUENCE]

The five Arcana have listened to your answers. The Fool laughs softly.
"The deck remembers what you said."

Three cards rise from the void:

  ★ One Major Arcana — your CORE AFFINITY. This card defines your primary energy alignment.
  ★ Two Minor Arcana — your SUPPORT aspects. These modulate how your power expresses.

The High Priestess whispers: "Do not choose. Let the cards find you."

The cards turn face-up. Remember them — you will carry them always.

[The Game Master will now reveal your drawn cards based on your interview answers.]
""".strip()

_AWAKENING_SCRIPT = """
[SYSTEM — AWAKENING TRIGGER]

You wake up. The void is gone. There is sunlight, cobblestones, noise.
You are alive. In a city. The void feels like a dream.

You reach for a cup. It moves before you touch it.

A market stall collapses nearby. People scatter. No one else seems to have noticed
the faint shimmer of energy that passed through your hand a moment ago.

Your first power has activated — accidentally.
The cards you drew in the void hum quietly in your memory.

The world is the same. But you are not.

[Continue: describe what you do next.]
""".strip()


# ── Core enforcer ─────────────────────────────────────────────────────────────

def _load_or_create(session: Session, entity_id: int) -> MainStoryState:
    """Fetch or create MainStoryState for the entity. Always returns valid flags."""
    state = session.exec(
        select(MainStoryState).where(MainStoryState.entity_id == entity_id)
    ).first()
    if not state:
        state = MainStoryState(
            entity_id=entity_id,
            current_arc=0,
            flags=json.dumps(DEFAULT_STORY_FLAGS),
        )
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def _flags(state: MainStoryState) -> dict:
    try:
        return json.loads(state.flags) if state.flags else dict(DEFAULT_STORY_FLAGS)
    except (json.JSONDecodeError, TypeError):
        return dict(DEFAULT_STORY_FLAGS)


def _save_flags(session: Session, state: MainStoryState, flags: dict) -> None:
    state.flags = json.dumps(flags)
    state.updated_at = datetime.now(timezone.utc)
    session.add(state)
    session.commit()


def _derive_alignment(answers: list[str]) -> str:
    """
    Derive a rough alignment from the 3 raw answer strings.
    order → Emperor-aligned (power / sacrifice / defy fate)
    chaos → Fool-aligned (both / no sacrifice / defy fate strongly)
    balance → middle path (understanding / no sacrifice / trust fate)
    """
    text = " ".join(answers).lower()
    order_signals = sum([
        "power" in text and "understanding" not in text,
        "sacrifice" in text and "would" in text and "not" not in text,
        "defy" in text,
    ])
    if order_signals >= 2:
        return "order"
    balance_signals = sum([
        "understanding" in text,
        "not" in text or "no" in text,
        "trust" in text,
    ])
    if balance_signals >= 2:
        return "balance"
    return "chaos"


def check_prologue_gates(
    session: Session,
    entity_id: int,
    user_message: str,
) -> Optional[str]:
    """
    Check prologue completeness. ONE question at a time.
    Reads the player's answer and advances the sub-phase before returning the next prompt.

    interview sub-phases stored in flags["interview_phase"]:
      0 → Q1 not yet shown
      1 → Q1 shown, waiting for answer → record answer, show Q2
      2 → Q2 shown, waiting for answer → record answer, show Q3
      3 → Q3 shown, waiting for answer → record answer, mark complete

    Returns forced narrative text if a prologue gate is active, else None.
    """
    state = _load_or_create(session, entity_id)
    flags = _flags(state)

    # ── Gate 1: Sequential interview ──────────────────────────────────────────
    if not flags.get("interview_done", False):
        phase = flags.get("interview_phase", 0)

        if phase == 0:
            # First visit — show Q1, advance to phase 1
            flags["interview_phase"] = 1
            flags.setdefault("interview_answers", [])
            _save_flags(session, state, flags)
            return _Q1

        elif phase == 1:
            # Player answered Q1 — record it, show Q2
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])   # cap to 200 chars
            flags["interview_answers"] = answers
            flags["interview_phase"] = 2
            _save_flags(session, state, flags)
            return _Q2

        elif phase == 2:
            # Player answered Q2 — record it, show Q3
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])
            flags["interview_answers"] = answers
            flags["interview_phase"] = 3
            _save_flags(session, state, flags)
            return _Q3

        else:  # phase == 3
            # Player answered Q3 — record it, mark interview done
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])
            alignment = _derive_alignment(answers)
            flags["interview_answers"] = answers
            flags["interview_phase"] = 4
            flags["interview_done"] = True
            flags["alignment_tendency"] = alignment
            _save_flags(session, state, flags)
            return _INTERVIEW_COMPLETE

    # ── Gate 2: Card draw ──────────────────────────────────────────────────────
    if not flags.get("cards_drawn", False):
        return _CARD_DRAW_SCRIPT

    # ── Gate 3: Awakening ──────────────────────────────────────────────────────
    if not flags.get("awakening_triggered", False):
        flags["awakening_triggered"] = True
        _save_flags(session, state, flags)
        return _AWAKENING_SCRIPT

    return None  # All prologue gates passed — GM may proceed


def complete_interview(
    session: Session,
    entity_id: int,
    alignment: str,           # "order" | "chaos" | "balance"
) -> None:
    """Call after the player answers the three interview questions."""
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    flags["interview_done"] = True
    flags["alignment_tendency"] = alignment
    _save_flags(session, state, flags)


def complete_card_draw(session: Session, entity_id: int) -> None:
    """Call after the player's cards have been revealed."""
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    flags["cards_drawn"] = True
    _save_flags(session, state, flags)


def advance_arc_if_ready(session: Session, entity_id: int) -> int:
    """
    Check whether all gate quests for the current arc are complete.
    If yes, advance current_arc by 1.
    Returns the new (or unchanged) arc number.
    """
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    current_arc = state.current_arc

    if current_arc >= 7:
        return current_arc

    gate_quests = ARC_GATE_QUESTS.get(current_arc, [])
    all_done = True
    for qname in gate_quests:
        quest = session.exec(select(Quest).where(Quest.name == qname)).first()
        if not quest:
            all_done = False
            break
        progress = session.exec(
            select(QuestProgress).where(
                QuestProgress.quest_id == quest.id,
                QuestProgress.entity_id == entity_id,
                QuestProgress.is_completed == True,  # noqa: E712
            )
        ).first()
        if not progress:
            all_done = False
            break

    if all_done and current_arc < 7:
        state.current_arc = current_arc + 1
        flags["current_arc"] = state.current_arc
        _save_flags(session, state, flags)

    return state.current_arc


def get_story_state(session: Session, entity_id: int) -> dict:
    """Return the full story state as a plain dict for context injection."""
    state = _load_or_create(session, entity_id)
    return {
        "current_arc": state.current_arc,
        "current_quest_id": state.current_quest_id,
        "flags": _flags(state),
    }


def gm_update_flags(
    session: Session,
    entity_id: int,
    updates: dict,
) -> dict:
    """
    Allow GM to update story flags — ONLY when gm_override_allowed is True.
    Returns updated flags dict (or original if override not permitted).
    """
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    if not flags.get("gm_override_allowed", False):
        return flags  # silently reject
    flags.update(updates)
    _save_flags(session, state, flags)
    return flags


def set_gm_override(session: Session, entity_id: int, allowed: bool) -> None:
    """Enable or disable GM flag-editing permission."""
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    flags["gm_override_allowed"] = allowed
    _save_flags(session, state, flags)


def set_faction(session: Session, entity_id: int, faction: str) -> None:
    """Record Arc 3 faction choice: 'ally' | 'oppose'."""
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    flags["faction_chosen"] = faction
    _save_flags(session, state, flags)


def mark_ascension_complete(session: Session, entity_id: int) -> None:
    """Mark end-game: player has become a Sovereign."""
    state = _load_or_create(session, entity_id)
    flags = _flags(state)
    flags["ascension_complete"] = True
    flags["sovereign_defeated"] = True
    state.current_arc = 7
    _save_flags(session, state, flags)
