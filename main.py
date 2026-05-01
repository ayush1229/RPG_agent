from __future__ import annotations

"""
main.py — Chainlit app entry point.

Registers:
  1. RPGDataLayer — custom data layer so Chainlit's sidebar shows previous sessions
  2. @cl.header_auth_callback — silently auto-auths all visitors (no login form)
  3. @cl.on_chat_resume — restores player state when clicking a past session

Identity split
--------------
  ui_user_id  = "player" (Chainlit auth) — groups ALL sessions in the sidebar
  game_user_id = chat_session_id (thread UUID) — binds to a unique TarotEntity,
                 making every chat thread a completely independent game save.

The game event handlers (on_chat_start, on_message, on_chat_end) live in
app/chat/handlers.py and are registered by the import below.
"""

from typing import Optional

import chainlit as cl
import chainlit.data as cl_data

from app.chat import handlers  # noqa: F401 — registers Chainlit lifecycle hooks
from app.chainlit_data_layer import RPGDataLayer
from app.db.database import create_db_and_tables, run_migrations

# ── Ensure DB tables exist and migrations are applied ─────────────────────────
create_db_and_tables()
run_migrations()

# ── Register custom data layer ─────────────────────────────────────────────────

# This enables the thread-history sidebar. All reads come from DialogueLog.
# Writes are still handled exclusively by handlers.py (no duplication).
cl_data._data_layer = RPGDataLayer()


# ── Silent auth — no login form ────────────────────────────────────────────────
@cl.header_auth_callback
def header_auth_callback(headers: dict) -> Optional[cl.User]:
    """
    Auto-authenticate all visitors without showing a login page.
    Every visitor is identified as 'player' so all their sessions aggregate
    under one account in the thread sidebar.

    For multi-character support in future: read a custom header or cookie and
    return a different identifier per character. Replace with
    @cl.password_auth_callback when you want per-user passwords.
    """
    return cl.User(identifier="player", metadata={})


# ── Resume previous session ───────────────────────────────────────────────────
@cl.on_chat_resume
async def on_chat_resume(thread: dict) -> None:
    """
    Fired when the user clicks a previous session in the sidebar.

    Restores both identities:
      game_user_id = thread_id   (unique per save slot — binds to its TarotEntity)
      ui_user_id   = "player"    (Chainlit auth identity — keeps sidebar grouping)
    """
    from app.chat.handlers import _USER_ID_KEY, _UI_USER_ID_KEY, _LOCATION_ID_KEY
    from app.db.database import get_session
    from app.db.session_service import load_user_state

    thread_id: str = thread["id"]
    ui_user_id: str = (
        thread.get("userId")
        or thread.get("userIdentifier")
        or "player"
    )
    # game_user_id == thread_id (each thread is its own game save)
    game_user_id: str = thread_id

    cl.user_session.set(_UI_USER_ID_KEY, ui_user_id)
    cl.user_session.set(_USER_ID_KEY, game_user_id)
    cl.user_session.set("_chat_session_id", thread_id)

    with get_session() as session:
        state = load_user_state(session, game_user_id, chat_session_id=thread_id)
        location_id = state.session_row.last_location_id

    cl.user_session.set(_LOCATION_ID_KEY, location_id)
    cl.user_session.set("_entity_id_cache", state.entity.id)
