from __future__ import annotations

import chainlit as cl

from app.agent.arbiter import arbiter_agent
from app.agent.game_master import game_master
from app.agent.persona import persona_agent
from app.config import settings
from app.contracts import PersonaSpeakRequest
from app.db.database import create_db_and_tables, init_root
from app.db.database import get_session
from app.schemas import ChatMessage, Role

_HISTORY_KEY = "chat_history"


# ─── App startup ──────────────────────────────────────────────────────────────

@cl.on_app_startup
async def on_app_startup() -> None:
    """Create DB tables and seed ROOT entity on first run."""
    create_db_and_tables()
    with get_session() as session:
        init_root(session)


# ─── Lifecycle hooks ──────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set(_HISTORY_KEY, [])
    await cl.Message(
        content=(
            "# ⚔️ Welcome to the AI RPG Agent\n\n"
            f"Your journey begins, powered by **{settings.app_name}**.\n\n"
            "Type anything to begin your adventure!"
        ),
        author="System",
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    history: list[ChatMessage] = cl.user_session.get(_HISTORY_KEY, [])

    # ── Phase 1: GM Analysis ──────────────────────────────────────────────────
    decision = None
    async with cl.Step(name="🧠 Reading the scene...", show_input=False) as step:
        decision = await game_master.analyze(message.content, history)
        step.output = (
            f"Needs Persona: {decision.needs_persona} "
            f"| Needs Arbiter: {decision.needs_arbiter}"
        )

    # ── Phase 2a: Persona Agent (NPC dialogue) ────────────────────────────────
    persona_dialogue = None
    if decision and decision.needs_persona and decision.npc_name:
        async with cl.Step(
            name=f"🎭 {decision.npc_name} speaks...", show_input=False
        ) as step:
            # Pull recent dialogue from history for context
            recent = [
                m.content for m in history[-6:]
                if m.role == Role.ASSISTANT
            ]
            persona_dialogue = await persona_agent.speak(
                PersonaSpeakRequest(
                    character_name=decision.npc_name,
                    context=decision.persona_context or message.content,
                    recent_dialogue=recent,
                )
            )
            step.output = persona_dialogue[:200] + ("…" if len(persona_dialogue) > 200 else "")

    # ── Phase 2b: Arbiter Agent (energy mechanics) ────────────────────────────
    arbiter_result = None
    if decision and decision.needs_arbiter and decision.arbiter_instruction:
        async with cl.Step(name="⚖️ Arbiter resolving...", show_input=False) as step:
            arbiter_result = await arbiter_agent.resolve(decision.arbiter_instruction)
            status = "✅ Success" if arbiter_result.success else "❌ Rejected"
            step.output = f"{status}: {arbiter_result.message[:300]}"

    # ── Phase 3: GM Narrative (streaming) ────────────────────────────────────
    reply_msg = cl.Message(content="", author=settings.app_name)
    await reply_msg.send()

    try:
        async for token in game_master.narrate(
            message=message.content,
            history=history,
            decision=decision,
            persona_dialogue=persona_dialogue,
            arbiter_result=arbiter_result,
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
        print(f"[DEBUG] Session ended. Turns: {len(history)}")
