from __future__ import annotations

from typing import Optional

import chainlit as cl
from sqlmodel import select

from app.agent.arbiter import arbiter_agent
from app.agent.game_master import game_master
from app.agent.persona import persona_agent
from app.config import settings
from app.contracts import PersonaSpeakRequest
from app.db.database import create_db_and_tables, get_session, init_root
from app.db.models import TarotEntity
from app.db.service import tarot_service
from app.schemas import ChatMessage, Role

_HISTORY_KEY = "chat_history"
_ENTITY_ID_KEY = "entity_id"
_LOCATION_ID_KEY = "location_id"


# ─── App startup ──────────────────────────────────────────────────────────────

@cl.on_app_startup
async def on_app_startup() -> None:
    """Create DB tables and seed ROOT entity on first run."""
    create_db_and_tables()
    with get_session() as session:
        init_root(session)


# ─── Session lifecycle ────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    """
    Initialize session state.
    Player identity is resolved HERE and stored in session.
    The LLM NEVER infers who the player is.
    """
    cl.user_session.set(_HISTORY_KEY, [])
    cl.user_session.set(_LOCATION_ID_KEY, None)

    # ── Resolve or create the player entity ──────────────────────────────────
    # Use Chainlit's built-in user identifier if auth is enabled,
    # otherwise fall back to the session id for guest play.
    user = cl.user_session.get("user")
    player_name = getattr(user, "identifier", None) or f"Player_{cl.user_session.get('id', 'guest')}"

    entity_id: Optional[int] = None
    with get_session() as session:
        existing = session.exec(
            select(TarotEntity).where(TarotEntity.entity_name == player_name)
        ).first()

        if existing:
            entity_id = existing.id
        else:
            # New player — create entity with no capacity (Arbiter grants it)
            player_entity = TarotEntity(entity_name=player_name)
            session.add(player_entity)
            session.commit()
            session.refresh(player_entity)
            entity_id = player_entity.id

    cl.user_session.set(_ENTITY_ID_KEY, entity_id)

    await cl.Message(
        content=(
            f"# ⚔️ {settings.app_name}\n\n"
            f"Welcome, **{player_name}**. Your soul awakens in a world of Tarot energy.\n\n"
            "Type anything to begin your adventure!"
        ),
        author="System",
    ).send()


# ─── Message handler ──────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message) -> None:
    history: list[ChatMessage] = cl.user_session.get(_HISTORY_KEY, [])
    location_id: Optional[int] = cl.user_session.get(_LOCATION_ID_KEY)

    # ── Phase 1: GM Analysis ──────────────────────────────────────────────────
    async with cl.Step(name="🧠 Reading the scene...", show_input=False) as step:
        decision = await game_master.analyze(
            message=message.content,
            history=history,
            location_id=location_id,
        )
        step.output = (
            f"Needs Persona: {decision.needs_persona} "
            f"| Needs Arbiter: {decision.needs_arbiter}"
        )

    # ── Phase 2a: Persona Agent (NPC dialogue, if needed) ────────────────────
    persona_dialogue = None
    if decision.needs_persona and decision.npc_name:
        async with cl.Step(
            name=f"🎭 {decision.npc_name} speaks...", show_input=False
        ) as step:
            recent = [m.content for m in history[-6:] if m.role == Role.ASSISTANT]
            persona_dialogue = await persona_agent.speak(
                PersonaSpeakRequest(
                    character_name=decision.npc_name,
                    context=decision.persona_context or message.content,
                    recent_dialogue=recent,
                )
            )
            step.output = persona_dialogue[:200] + ("…" if len(persona_dialogue) > 200 else "")

    # ── Phase 2b: Arbiter (BLOCKING — GM waits for result) ───────────────────
    arbiter_result = None
    if decision.needs_arbiter and decision.arbiter_instruction:
        async with cl.Step(name="⚖️ Arbiter resolving...", show_input=False) as step:
            arbiter_result = await arbiter_agent.resolve(decision.arbiter_instruction)
            status = "✅ Success" if arbiter_result.success else "❌ Rejected"
            step.output = f"{status}: {arbiter_result.message[:300]}"

    # ── Phase 3: GM Narrative (streaming — only after sub-agents finish) ──────
    reply_msg = cl.Message(content="", author=settings.app_name)
    await reply_msg.send()

    try:
        async for token in game_master.narrate(
            message=message.content,
            history=history,
            decision=decision,
            persona_dialogue=persona_dialogue,
            arbiter_result=arbiter_result,
            location_id=location_id,
        ):
            await reply_msg.stream_token(token)
    except Exception as e:
        reply_msg.content = f"⚠️ Narrative error: {e}"

    await reply_msg.update()

    # ── Update session history ────────────────────────────────────────────────
    history.append(ChatMessage(role=Role.USER, content=message.content))
    history.append(ChatMessage(role=Role.ASSISTANT, content=reply_msg.content))
    cl.user_session.set(_HISTORY_KEY, history)


@cl.on_chat_end
async def on_chat_end() -> None:
    history: list[ChatMessage] = cl.user_session.get(_HISTORY_KEY, [])
    if settings.app_debug:
        entity_id = cl.user_session.get(_ENTITY_ID_KEY)
        print(f"[DEBUG] Session ended. entity_id={entity_id}, turns={len(history)}")
