"""
app/db/story_enforcer.py
=========================
Narrative control layer — runs BEFORE the GM on every message.

Enforcement contract
---------------------
1. Load (or create) MainStoryState for the player entity.
2. Check mandatory prologue gates sequentially:
      interview_done → cards_drawn → awakening_triggered
3. If any gate is incomplete → return a PrologueOverride.
   - is_gm_directive=False → shown verbatim to the player (GM bypassed)
   - is_gm_directive=True  → injected into GM.narrate() as a system directive;
                              the GM writes the actual player-facing text.
4. After prologue, enforce arc-level sequential quest gating.
5. GM may suggest flag changes only when gm_override_allowed == True.

Return value
-------------
  None             → gates passed, GM may proceed normally.
  PrologueOverride → a gate is active (see is_gm_directive flag).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
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

@dataclass
class PrologueOverride:
    """
    Returned by check_prologue_gates when a prologue gate is active.

    is_gm_directive=False (default):
        Show `text` verbatim to the player. GM is bypassed entirely.
        Used for: Q1/Q2/Q3 prompts, INTERVIEW_COMPLETE, CARD_DRAW_SCRIPT, AWAKENING.

    is_gm_directive=True:
        Inject `text` into GM.narrate() as a system directive block.
        The GM writes the actual player-facing narrative — the raw directive
        is NEVER shown to the player.
        Used for: _GM_CARD_REVEAL_DIRECTIVE.
    """
    text: str
    is_gm_directive: bool = False


# -- Prologue interview: ONE question per step --------------------------------

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

The cards begin to turn face-up, one by one.

*Say anything to let the Game Master reveal your cards.*""".strip()

_GM_CARD_REVEAL_DIRECTIVE = """[SYSTEM — GM INSTRUCTION: CARD REVEAL]

The player has completed the void interview. You must now reveal their three drawn cards.

Player alignment tendency: {alignment}

Rules for card selection:
  • You MUST select EXACTLY ONE Major Arcana (core card) that resonates with their alignment:
    - balance → prefer The High Priestess, The Star, Temperance, The World
    - order   → prefer The Emperor, Justice, The Hierophant, Strength
    - chaos   → prefer The Fool, The Tower, The Magician, The Moon
  • You MUST select EXACTLY TWO Minor Arcana (support cards). These must be from the Wands, Cups, Swords, or Pentacles suits.
  • CRITICAL: Do NOT select more than one Major Arcana. The second and third cards MUST be Minor Arcana.

Narrate the reveal poetically. Name each of the three cards. Describe what the player feels as each turns face-up.
After the reveal, tell the player: "These cards are now yours. They hum in your memory."
Then transition naturally into the physical world: the void dissolves, the Awakening begins.

[The next system override will place the player in the physical world.]""".strip()


_AWAKENING_DIRECTIVE = """\
[SYSTEM — GM INSTRUCTION: AWAKENING SCENE]

The void interview and card draw are complete. You must now transition the player
into the physical world. Write this as an immersive, grounded scene — NOT mystical.

Setting: A small, worn room at the Broken Lantern Inn, Elaris Hollow.
  - Morning light cuts through a cracked wooden shutter.
  - Rough hewn walls. Smell of woodsmoke and damp straw.
  - A clay cup on the bedside table. A threadbare wool blanket.
  - Distant sounds of a waking market outside — calls, cart wheels, a dog barking.

What happens:
  1. The player wakes. The void dream lingers, fading fast.
  2. They reach for the cup. It slides a few inches on its own — just for a moment.
     They blink. It is still. Did that happen?
  3. DO NOT explain it. Let them wonder.
  4. Outside the window, the market is starting. Something falls. Laughter. A bell.
  5. End with an open prompt: the player must choose what to do first.

Rules:
  - Name the inn and the village. Make it feel like a REAL place with texture and smell.
  - Do NOT mention cards, Arcana, the void, or any system names.
  - 3-4 paragraphs max. Grounded. Curious. Real.
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
    order   -> Emperor-aligned (power / sacrifice / defy fate)
    chaos   -> Fool-aligned (both / no sacrifice / defy fate strongly)
    balance -> middle path (understanding / no sacrifice / trust fate)
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
) -> Optional[PrologueOverride]:
    """
    Check prologue completeness. ONE question at a time.
    Returns a PrologueOverride if a gate is active, else None.

    interview_phase: 0=show Q1, 1=record+show Q2, 2=record+show Q3, 3=record+mark done
    card_draw_phase: 0=show CARD_DRAW_SCRIPT, 1=inject GM_CARD_REVEAL_DIRECTIVE
    """
    state = _load_or_create(session, entity_id)
    flags = _flags(state)

    # -- Gate 1: Sequential interview -----------------------------------------
    if not flags.get("interview_done", False):
        phase = flags.get("interview_phase", 0)

        if phase == 0:
            flags["interview_phase"] = 1
            flags.setdefault("interview_answers", [])
            _save_flags(session, state, flags)
            return PrologueOverride(_Q1)

        elif phase == 1:
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])
            flags["interview_answers"] = answers
            flags["interview_phase"] = 2
            _save_flags(session, state, flags)
            return PrologueOverride(_Q2)

        elif phase == 2:
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])
            flags["interview_answers"] = answers
            flags["interview_phase"] = 3
            _save_flags(session, state, flags)
            return PrologueOverride(_Q3)

        else:  # phase == 3
            answers = flags.get("interview_answers", [])
            answers.append(user_message[:200])
            alignment = _derive_alignment(answers)
            flags["interview_answers"] = answers
            flags["interview_phase"] = 4
            flags["interview_done"] = True
            flags["alignment_tendency"] = alignment
            _save_flags(session, state, flags)
            return PrologueOverride(_INTERVIEW_COMPLETE)

    # -- Gate 2: Card draw ----------------------------------------------------
    if not flags.get("cards_drawn", False):
        card_phase = flags.get("card_draw_phase", 0)

        if card_phase == 0:
            # Show atmospheric card draw prompt TO the player
            flags["card_draw_phase"] = 1
            _save_flags(session, state, flags)
            return PrologueOverride(_CARD_DRAW_SCRIPT)          # player-visible

        else:
            # Player acknowledged — let GM narrate the actual card reveal
            alignment = flags.get("alignment_tendency", "balance")
            flags["cards_drawn"] = True
            flags["card_draw_phase"] = 2
            _save_flags(session, state, flags)
            return PrologueOverride(                             # GM directive
                _GM_CARD_REVEAL_DIRECTIVE.format(alignment=alignment),
                is_gm_directive=True,
            )

    # -- Gate 3: Awakening ----------------------------------------------------
    if not flags.get("awakening_triggered", False):
        flags["awakening_triggered"] = True
        _save_flags(session, state, flags)
        # Kick off tutorial phase 1 (places entity in Elaris Hollow, phase 0→1)
        try:
            from app.db.tutorial_service import start_tutorial
            start_tutorial(session, entity_id)
        except Exception:
            pass
        return PrologueOverride(_AWAKENING_DIRECTIVE, is_gm_directive=True)

    return None  # All prologue gates passed -- GM may proceed


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
