"""
app/db/session_service.py
==========================
Persistent user state management for the AI RPG system.

Responsibilities
----------------
- load_user_state   : Rehydrate full player state from DB on every request
- update_user_session: Persist updated location / quest / game-state flags
- save_dialogue     : Append a DialogueLog row (user or assistant turn)
- get_chat_history  : Return full ordered DialogueLog for UI replay
- build_agent_context: Build the minimal, structured context dict for the LLM
- update_conversation_summary: Trigger LLM summarization every N messages

Design rules
------------
- NEVER send full chat history to any LLM (enforced here, not in agents)
- Limit recent_messages to MAX_RECENT_MESSAGES (default 10)
- All writes are committed in a single transaction per call
- UserSession is idempotent (upsert pattern)
- Summary is updated every SUMMARY_INTERVAL messages or on major events
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.db.models import (
    ConversationSummary,
    DialogueLog,
    InventoryItem,
    Location,
    Quest,
    QuestProgress,
    SideCharacter,
    StatusEffect,
    TarotEntity,
    UserSession,
)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_RECENT_MESSAGES = 10   # max turns injected into LLM context
SUMMARY_INTERVAL = 10      # trigger re-summarization every N total messages


# ── Typed state container ─────────────────────────────────────────────────────

@dataclass
class PlayerState:
    """
    Full rehydrated state for one user. Passed to build_agent_context().
    All fields come directly from the DB — no in-memory inference.
    """
    user_id: str
    entity: TarotEntity
    session_row: UserSession

    location: Optional[Location] = None
    inventory: list[InventoryItem] = field(default_factory=list)
    active_quests: list[dict] = field(default_factory=list)
    status_effects: list[StatusEffect] = field(default_factory=list)
    nearby_npcs: list[dict] = field(default_factory=list)

    recent_messages: list[dict] = field(default_factory=list)   # last N only
    summary: str = "No history yet."


# ── Core functions ─────────────────────────────────────────────────────────────

def load_user_state(
    session: Session,
    user_id: str,
    chat_session_id: Optional[str] = None,
) -> PlayerState:
    """
    Rehydrate the complete player state from DB.

    chat_session_id: Chainlit session id. When provided, recent_messages is
    scoped to ONLY the current chat session, so a new chat tab starts with a
    clean dialogue window while preserving all entity state (inventory, quests,
    health, location, TutorialState etc.) from the DB.

    Steps:
      1. Fetch or create UserSession (idempotent)
      2. Load TarotEntity
      3. Load Location, Inventory, QuestProgress, StatusEffects, nearby NPCs
      4. Load last MAX_RECENT_MESSAGES dialogue turns (scoped to chat_session_id)
      5. Load ConversationSummary (cross-session compressed memory)
    """
    # ── 1. Resolve UserSession (create player entity if first login) ───────────
    user_session = session.exec(
        select(UserSession).where(UserSession.user_id == user_id)
    ).first()

    if not user_session:
        # New player — create a blank TarotEntity
        entity = TarotEntity(entity_name=user_id)
        session.add(entity)
        session.flush()

        user_session = UserSession(
            user_id=user_id,
            entity_id=entity.id,
        )
        session.add(user_session)
        session.commit()
        session.refresh(entity)
        session.refresh(user_session)
    else:
        entity = session.get(TarotEntity, user_session.entity_id)
        if not entity:
            raise RuntimeError(f"TarotEntity {user_session.entity_id} missing for user '{user_id}'")

    # ── 2. Location ────────────────────────────────────────────────────────────
    location: Optional[Location] = None
    if user_session.last_location_id:
        location = session.get(Location, user_session.last_location_id)

    # ── 3a. Inventory ──────────────────────────────────────────────────────────
    inventory = session.exec(
        select(InventoryItem).where(InventoryItem.owner_id == entity.id)
    ).all()

    # ── 3b. Active (incomplete) quests ────────────────────────────────────────
    active_quest_rows = session.exec(
        select(QuestProgress).where(
            QuestProgress.entity_id == entity.id,
            QuestProgress.is_completed == False,  # noqa: E712
        )
    ).all()
    active_quests: list[dict] = []
    for qp in active_quest_rows:
        q = session.get(Quest, qp.quest_id)
        if q:
            active_quests.append({
                "quest_id": q.id,
                "name": q.name,
                "difficulty": q.difficulty,
                "progress": qp.progress,
                "goal": qp.goal,
            })

    # ── 3c. Status effects ────────────────────────────────────────────────────
    status_effects = session.exec(
        select(StatusEffect).where(StatusEffect.target_entity_id == entity.id)
    ).all()

    # ── 3d. Nearby NPCs (at current location) ─────────────────────────────────
    nearby_npcs: list[dict] = []
    if location:
        for char in location.occupants:
            nearby_npcs.append({
                "name": char.name,
                "position": char.position,
                "status": char.current_status,
                "affinity": (
                    char.persona.tarot_affinity.name
                    if char.persona and char.persona.tarot_affinity
                    else None
                ),
            })

    # ── 4. Recent dialogue (last MAX_RECENT_MESSAGES, scoped to this chat session) ─
    dialogue_query = (
        select(DialogueLog)
        .where(DialogueLog.user_id == user_id)
        .order_by(col(DialogueLog.id).desc())
        .limit(MAX_RECENT_MESSAGES)
    )
    if chat_session_id is not None:
        dialogue_query = (
            select(DialogueLog)
            .where(
                DialogueLog.user_id == user_id,
                DialogueLog.chat_session_id == chat_session_id,
            )
            .order_by(col(DialogueLog.id).desc())
            .limit(MAX_RECENT_MESSAGES)
        )
    all_logs = session.exec(dialogue_query).all()
    # Reverse so oldest-first for context window
    recent_messages = [
        {"role": log.role, "content": log.message}
        for log in reversed(all_logs)
    ]

    # ── 5. Conversation summary ────────────────────────────────────────────────
    summary_row = session.exec(
        select(ConversationSummary).where(ConversationSummary.user_id == user_id)
    ).first()
    summary_text = summary_row.summary if summary_row else "No history yet."

    return PlayerState(
        user_id=user_id,
        entity=entity,
        session_row=user_session,
        location=location,
        inventory=list(inventory),
        active_quests=active_quests,
        status_effects=list(status_effects),
        nearby_npcs=nearby_npcs,
        recent_messages=recent_messages,
        summary=summary_text,
    )


def update_user_session(
    session: Session,
    user_id: str,
    *,
    location_id: Optional[int] = None,
    game_state: Optional[dict] = None,
    active_quest_id: Optional[int] = None,
) -> None:
    """
    Persist updated session fields. Idempotent — only provided kwargs are written.
    Always refreshes updated_at.
    """
    user_session = session.exec(
        select(UserSession).where(UserSession.user_id == user_id)
    ).first()
    if not user_session:
        return   # should not happen after load_user_state, but guard anyway

    if location_id is not None:
        user_session.last_location_id = location_id
    if game_state is not None:
        user_session.last_game_state = json.dumps(game_state)
    if active_quest_id is not None:
        user_session.last_active_quest_id = active_quest_id

    user_session.updated_at = datetime.now(timezone.utc)
    session.add(user_session)
    session.commit()


def save_dialogue(
    session: Session,
    user_id: str,
    role: str,
    message: str,
    chat_session_id: Optional[str] = None,
) -> DialogueLog:
    """
    Append one DialogueLog row. role must be 'user' or 'assistant'.
    chat_session_id: Chainlit session id, scopes the message to a specific chat window.
    Returns the created row.
    """
    if role not in {"user", "assistant"}:
        raise ValueError(f"Invalid role '{role}'. Must be 'user' or 'assistant'.")
    log = DialogueLog(
        user_id=user_id,
        chat_session_id=chat_session_id,
        role=role,
        message=message,
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def get_chat_history(
    session: Session,
    user_id: str,
    chat_session_id: Optional[str] = None,
) -> list[dict]:
    """
    Return ordered dialogue history for UI replay.
    When chat_session_id is given, returns ONLY that session's messages.
    When None, returns ALL messages for the user across all sessions (admin/debug use).
    NOT for model input — caller must never pass this to an LLM directly.
    """
    query = select(DialogueLog).where(DialogueLog.user_id == user_id)
    if chat_session_id is not None:
        query = query.where(DialogueLog.chat_session_id == chat_session_id)
    logs = session.exec(query.order_by(col(DialogueLog.id))).all()
    return [
        {
            "id": log.id,
            "role": log.role,
            "message": log.message,
            "timestamp": log.timestamp.isoformat(),
            "chat_session_id": log.chat_session_id,
        }
        for log in logs
    ]


def build_agent_context(state: PlayerState) -> dict[str, Any]:
    """
    Build the minimal, structured context dict injected into every LLM call.

    Rules:
      - recent_messages is capped at MAX_RECENT_MESSAGES (enforced in load_user_state)
      - summary replaces the full history
      - status effects, inventory, active quests are summarised, not dumped raw

    Returns a dict that GM/Persona/Arbiter agents can serialise into their prompts.
    """
    entity = state.entity

    # Mana values
    upright_mana = entity.current_upright_mana
    reversed_mana = entity.current_reversed_mana
    upright_max = entity.max_upright_mana
    reversed_max = entity.max_reversed_mana

    # Health
    health = entity.current_health
    max_health = entity.max_health

    # Level
    level = entity.level
    xp = entity.current_xp

    # Inventory summary (name + type, not full detail)
    inventory_summary = [
        {"name": item.name, "type": item.item_type, "qty": item.quantity}
        for item in state.inventory
    ]

    # Status effect summary
    effects_summary = [
        {"name": eff.name, "type": eff.effect_type, "duration": eff.duration}
        for eff in state.status_effects
    ]

    return {
        "player": {
            "entity_id": entity.id,
            "name": entity.entity_name,
            "level": level,
            "xp": xp,
            "health": health,
            "max_health": max_health,
            "upright_mana": upright_mana,
            "upright_mana_max": upright_max,
            "reversed_mana": reversed_mana,
            "reversed_mana_max": reversed_max,
            "dominant_energy": entity.dominant_energy,
            "is_sovereign": entity.is_upright_sovereign or entity.is_reversed_sovereign,
        },
        "location": state.location.name if state.location else "Unknown",
        "location_id": state.location.id if state.location else None,
        "is_safe_zone": state.location.is_safe_zone if state.location else True,
        "is_magic_restricted": state.location.is_magic_restricted if state.location else False,
        "nearby_npcs": state.nearby_npcs,
        "inventory": inventory_summary,
        "active_quests": state.active_quests,
        "status_effects": effects_summary,
        # ── Memory injection (replaces full history) ───────────────────────────
        "summary": state.summary,
        "recent_messages": state.recent_messages,   # last MAX_RECENT_MESSAGES only
    }


async def maybe_update_summary(
    session: Session,
    user_id: str,
    force: bool = False,
    chat_session_id: Optional[str] = None,
) -> bool:
    """
    Trigger summarisation if total message count (for this chat session) is a
    multiple of SUMMARY_INTERVAL or if force=True.

    The ConversationSummary is cross-session — it accumulates the narrative
    across ALL sessions. The summary always replaces rather than appends, so
    it remains compact regardless of how many sessions a player has had.

    Returns True if summarisation was triggered.
    """
    query = select(DialogueLog).where(DialogueLog.user_id == user_id)
    if chat_session_id is not None:
        query = query.where(DialogueLog.chat_session_id == chat_session_id)
    count = len(session.exec(query).all())

    if force or (count > 0 and count % SUMMARY_INTERVAL == 0):
        from app.agent.summarizer import summarizer_agent
        await summarizer_agent.summarize(session, user_id)
        return True
    return False
