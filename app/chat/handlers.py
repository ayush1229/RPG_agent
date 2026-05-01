"""
app/chat/handlers.py
====================
Chainlit event handlers — the main request pipeline.

Pipeline per message
---------------------
1.  save_dialogue (user turn)
2.  load_user_state         → PlayerState (full DB rehydration)
3.  build_agent_context     → minimal context dict (NO full history)
4.  GM analyze              → GMDecision (structured intent)
5a. Persona Agent           → NPC dialogue (if needed)
5b. Arbiter                 → energy transfer (if needed)
6.  GM narrate (streaming)  → reply tokens
7.  save_dialogue (assistant turn)
8.  update_user_session     → persist location / quest / state
9.  maybe_update_summary    → LLM summary every N messages

State contract
--------------
- cl.user_session stores ONLY: user_id, location_id
  (entity_id is resolved every turn from DB — never cached in memory)
- History is NOT stored in Chainlit session; load_user_state fetches it
- Full chat log is DB-only; LLM only ever sees last N + summary
"""
from __future__ import annotations

from typing import Optional

import chainlit as cl
from sqlmodel import select

from app.agent.arbiter import arbiter_agent
from app.agent.game_master import game_master
from app.agent.persona import persona_agent
from app.config import settings
from app.contracts import PersonaSpeakRequest
from app.llm_logger import SessionLLMLogger
from app.db.database import create_db_and_tables, get_session, init_root
from app.db.session_service import (
    build_agent_context,
    get_chat_history,
    load_user_state,
    maybe_update_summary,
    save_dialogue,
    update_user_session,
)
from app.db.story_enforcer import (
    advance_arc_if_ready,
    check_prologue_gates,
    get_story_state,
    PrologueOverride,
)
from app.db.tutorial_service import build_tutorial_context
from app.schemas import ChatMessage, Role

_LOCATION_ID_KEY = "location_id"
_USER_ID_KEY = "user_id"       # game identity — unique per chat session (= thread id)
_UI_USER_ID_KEY = "ui_user_id" # Chainlit auth identity — groups sessions in the sidebar


# ─── App startup ──────────────────────────────────────────────────────────────

@cl.on_app_startup
async def on_app_startup() -> None:
    """Create all DB tables (incl. new persistence tables) and seed ROOT entity."""
    create_db_and_tables()
    with get_session() as session:
        init_root(session)


# ─── Session start ────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    """
    Resolve user identity → load_user_state (creates entity if new player)
    → restore last location → send welcome with persisted state summary.

    Identity split:
      ui_user_id  = Chainlit auth identifier ('player') — groups sessions in the sidebar
      game_user_id = chat_session_id (unique per tab) — binds to a distinct TarotEntity
                     so every new chat is a completely independent game save.
    """
    # Chainlit gives each browser tab a unique session id
    chat_session_id: str = cl.user_session.get("id", "default")

    # ui_user_id: used only for DialogueLog and the sidebar — stays constant per auth user
    user = cl.user_session.get("user")
    ui_user_id: str = getattr(user, "identifier", None) or "player"

    # game_user_id: used for UserSession / TarotEntity — unique per chat thread
    game_user_id: str = chat_session_id

    cl.user_session.set(_UI_USER_ID_KEY, ui_user_id)
    cl.user_session.set(_USER_ID_KEY, game_user_id)
    cl.user_session.set("_chat_session_id", chat_session_id)

    with get_session() as session:
        state = load_user_state(session, game_user_id, chat_session_id=chat_session_id)
        location_id = state.session_row.last_location_id

    cl.user_session.set(_LOCATION_ID_KEY, location_id)
    cl.user_session.set("_entity_id_cache", state.entity.id)

    # ── Build a personalised welcome ──────────────────────────────────────────
    is_returning = state.summary != "No history yet."
    if is_returning:
        welcome_body = (
            f"Welcome back. Your adventure continues.\n\n"
            f"**Level {state.entity.level}** | "
            f"HP {state.entity.current_health}/{state.entity.max_health} | "
            f"Location: {state.location.name if state.location else 'Unknown'}\n\n"
            f"*{state.summary[:300]}{'…' if len(state.summary) > 300 else ''}*"
        )
    else:
        welcome_body = (
            f"# ⚔️ {settings.app_name}\n\n"
            "Welcome. Your soul awakens in a world of Tarot energy.\n\n"
            "Type anything to begin your adventure!"
        )

    await cl.Message(content=welcome_body, author="System").send()


# ─── Message handler ──────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message) -> None:
    # game_user_id is unique per chat thread — binds to a specific TarotEntity/UserSession
    game_user_id: str = cl.user_session.get(_USER_ID_KEY, "unknown")
    # ui_user_id groups all threads under one Chainlit account for the sidebar
    ui_user_id: str = cl.user_session.get(_UI_USER_ID_KEY, "player")
    location_id: Optional[int] = cl.user_session.get(_LOCATION_ID_KEY)
    chat_session_id: str = cl.user_session.get("_chat_session_id", "default")

    with get_session() as session:
        # ── Step 1: Persist user message (using ui_user_id for sidebar grouping) ─
        save_dialogue(session, ui_user_id, role="user",
                      message=message.content, chat_session_id=chat_session_id)

        # ── Step 2: Load full state from DB (using game_user_id for game state) ──
        state = load_user_state(session, game_user_id, chat_session_id=chat_session_id)

        # ── Step 3: Build minimal LLM context ─────────────────────────────────
        agent_ctx = build_agent_context(state)

        # -- STORY ENFORCER: prologue gate check --------------------------------
        entity_id = state.entity.id
        prologue: Optional[PrologueOverride] = check_prologue_gates(
            session, entity_id, message.content
        )
        story_ctx = get_story_state(session, entity_id)

        if prologue and not prologue.is_gm_directive:
            # Player-visible override: persist it (GM bypassed)
            save_dialogue(session, ui_user_id, role="assistant",
                          message=prologue.text, chat_session_id=chat_session_id)
            update_user_session(session, game_user_id, location_id=location_id)
            await maybe_update_summary(session, ui_user_id,
                                       chat_session_id=chat_session_id)

        # Convert recent_messages -> ChatMessage list for GM
        history: list[ChatMessage] = [
            ChatMessage(
                role=Role.USER if m["role"] == "user" else Role.ASSISTANT,
                content=m["content"],
            )
            for m in state.recent_messages
        ]

    # -- Player-visible override: send directly, skip GM --------------------
    if prologue and not prologue.is_gm_directive:
        await cl.Message(content=prologue.text, author="System").send()
        return

    # -- GM-directive OR normal play: run full GM pipeline ------------------
    # Priority: prologue directive (card reveal / awakening) > tutorial context > None
    with get_session() as session:
        entity_id = cl.user_session.get("_entity_id_cache")
        if entity_id:
            from app.db.tutorial_service import get_tutorial_state, advance_phase
            from app.db.models import TarotEntity
            ts = get_tutorial_state(session, entity_id)
            # Phase 1 (Awakening) is already handled by the awakening GM directive.
            # Auto-advance to Phase 2 (First Interaction / Callum) immediately.
            if ts.phase == 1:
                advance_phase(session, entity_id)

        tutorial_ctx = build_tutorial_context(session, entity_id) if entity_id else ""

        # Capture entity stats for the HUD footer (before session closes)
        _ent = session.get(TarotEntity, entity_id) if entity_id else None
        stats_footer = ""
        if _ent:
            stats_footer = (
                f"\n\n---\n"
                f"`⚔️ Lv.{_ent.level}` "
                f"`❤️ {_ent.current_health} HP` "
                f"`🔮 {_ent.current_upright_mana}/{_ent.upright_capacity} MP` "
                f"`✨ {_ent.current_xp} XP`"
            )

    if prologue and prologue.is_gm_directive:
        # Prologue directive takes priority; append tutorial phase if already started
        system_directive = prologue.text + (f"\n\n{tutorial_ctx}" if tutorial_ctx else "")
    elif tutorial_ctx:
        # Normal play: tutorial enforcer directs the GM
        system_directive = tutorial_ctx
    else:
        system_directive = None

    # -- Step 4: Analyze OR bypass for directive turns ----------------------
    # Prologue GM directives (card reveal, awakening) are self-contained.
    # Running analyze on top of them causes the GM to hallucinate NPCs
    # (e.g. 'The High Priestess speaks') and spurious arbiter transfers.
    if prologue and prologue.is_gm_directive:
        # Bypass: the directive IS the full instruction to the GM.
        from app.contracts import GMDecision
        decision = GMDecision(
            needs_persona=False,
            needs_arbiter=False,
            narrative_intent="Follow the system directive exactly as instructed.",
        )
    else:
        async with cl.Step(name="Reading the scene...", show_input=False) as step:
            llm_logger = SessionLLMLogger(chat_session_id)
            decision = await game_master.analyze(
                message=message.content,
                history=history,
                location_id=location_id,
                callbacks=[llm_logger],
            )
            step.output = (
                f"Needs Persona: {decision.needs_persona} "
                f"| Needs Arbiter: {decision.needs_arbiter}"
                + (f" | tutorial phase active" if tutorial_ctx else "")
            )

    # -- Step 5a: Persona Agent (graceful degradation on capacity failure) ---
    persona_dialogue: Optional[str] = None
    if decision.needs_persona and decision.npc_name:
        async with cl.Step(
            name=f"🎭 {decision.npc_name} speaks...", show_input=False
        ) as step:
            try:
                recent_assistant = [
                    m["content"] for m in state.recent_messages
                    if m["role"] == "assistant"
                ][-3:]   # cap at 3 to respect 32k context limit
                persona_dialogue = await persona_agent.speak(
                    PersonaSpeakRequest(
                        character_name=decision.npc_name,
                        context=decision.persona_context or message.content,
                        recent_dialogue=recent_assistant,
                    )
                )
                step.output = (
                    persona_dialogue[:200]
                    + ("…" if len(persona_dialogue) > 200 else "")
                )
            except Exception as exc:
                err = str(exc)
                step.output = f"⚠️ Persona unavailable ({err[:120]}). GM will narrate."
                persona_dialogue = None   # GM narrates without NPC dialogue

    # ── Step 5b: Arbiter ──────────────────────────────────────────────────────
    arbiter_result = None
    if decision.needs_arbiter and decision.arbiter_instruction:
        async with cl.Step(name="⚖️ Arbiter resolving...", show_input=False) as step:
            arbiter_result = await arbiter_agent.resolve(decision.arbiter_instruction)
            status = "✅ Success" if arbiter_result.success else "❌ Rejected"
            step.output = f"{status}: {arbiter_result.message[:300]}"

    # ── Step 6: GM Narrative (streaming) ─────────────────────────────────────
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
            system_directive=system_directive,
            callbacks=[SessionLLMLogger(chat_session_id)],
        ):
            await reply_msg.stream_token(token)
    except Exception as e:
        reply_msg.content = f"Narrative error: {e}"

    # -- Append stats HUD footer -------------------------------------------
    if stats_footer and reply_msg.content and not reply_msg.content.startswith("Narrative error"):
        reply_msg.content += stats_footer

    await reply_msg.update()

    # ── Steps 7–9: Persist reply + update session + maybe summarise ───────────
    with get_session() as session:
        # 7. Save assistant reply (ui_user_id for sidebar grouping)
        save_dialogue(session, ui_user_id, role="assistant",
                      message=reply_msg.content, chat_session_id=chat_session_id)

        # 8. Update session (game_user_id for game state)
        update_user_session(session, game_user_id, location_id=location_id)

        # Advance arc if all gate quests completed
        entity_id = cl.user_session.get("_entity_id_cache")
        if entity_id:
            advance_arc_if_ready(session, entity_id)

        # 9a. Advance tutorial phase by turn count (phases 2–10)
        if entity_id:
            from app.db.tutorial_service import tick_phase_turn
            tick_result = tick_phase_turn(session, entity_id)
            if tick_result.get("advanced") and settings.app_debug:
                print(f"[DEBUG] Tutorial auto-advanced to phase {tick_result['new_phase']}")

        # 9b. Trigger summary if interval reached or major event fired
        major_event = (
            arbiter_result is not None and getattr(arbiter_result, "success", False)
        )
        await maybe_update_summary(session, ui_user_id, force=major_event,
                                   chat_session_id=chat_session_id)


# ─── Chat end ─────────────────────────────────────────────────────────────────

@cl.on_chat_end
async def on_chat_end() -> None:
    """
    On disconnect: force a summary update so the next session starts with
    fresh compressed context, regardless of message count.
    """
    game_user_id: str = cl.user_session.get(_USER_ID_KEY, "unknown")
    ui_user_id: str = cl.user_session.get(_UI_USER_ID_KEY, "player")
    if game_user_id == "unknown":
        return
    chat_session_id: str = cl.user_session.get("_chat_session_id", "default")
    with get_session() as session:
        await maybe_update_summary(session, ui_user_id, force=True,
                                   chat_session_id=chat_session_id)

    if settings.app_debug:
        print(f"[DEBUG] Session ended for game_user_id={game_user_id}")
