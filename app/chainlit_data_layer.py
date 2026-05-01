"""
app/chainlit_data_layer.py
==========================
Custom Chainlit data layer backed by the existing SQLite DialogueLog table.

Chainlit's sidebar uses this to:
  - List previous chat sessions per user (list_threads)
  - Load a specific session's messages when clicked (get_thread)
  - Associate threads with an authenticated user (get_user / create_user)

All persistence is still handled by our own handlers.py pipeline.
This layer is READ-ONLY — we just expose existing data to Chainlit's UI.

Mapping:
  Chainlit thread_id  ↔  chat_session_id  (Chainlit's own session UUID)
  Chainlit user_id    ↔  user_id          (player's username / identifier)
  StepDict            ←  DialogueLog rows
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

import chainlit.data as cl_data
from chainlit.data.base import BaseDataLayer
from chainlit.types import (
    Feedback,
    FeedbackDict,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import User
from sqlmodel import Session, select, func

from app.db.database import engine
from app.db.models import DialogueLog

log = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_to_step(log_row: DialogueLog) -> dict:
    """Convert a DialogueLog row to a Chainlit StepDict-compatible dict."""
    step_type = "user_message" if log_row.role == "user" else "assistant_message"
    return {
        "id": str(log_row.id),
        "threadId": log_row.chat_session_id or "legacy",
        "parentId": None,
        "command": None,
        "modes": None,
        "streaming": False,
        "waitForAnswer": None,
        "isError": None,
        "metadata": {},
        "tags": None,
        "input": "",
        "output": log_row.message,
        "name": "Player" if log_row.role == "user" else "AI RPG Agent",
        "type": step_type,
        "createdAt": log_row.timestamp.isoformat() if log_row.timestamp else _utcnow_iso(),
        "start": None,
        "end": None,
        "generation": None,
        "showInput": None,
        "defaultOpen": None,
        "autoCollapse": None,
        "language": None,
        "icon": None,
        "feedback": None,
    }


class RPGDataLayer(BaseDataLayer):
    """
    Minimal read-only data layer that exposes our DialogueLog as Chainlit threads.
    All write operations (create_step etc.) are no-ops because handlers.py already
    persists messages directly to the DB.
    """

    # ── User ──────────────────────────────────────────────────────────────────

    async def get_user(self, identifier: str) -> Optional[User]:
        """Return a User object if we have any dialogue for this identifier."""
        with Session(engine) as session:
            row = session.exec(
                select(DialogueLog).where(DialogueLog.user_id == identifier).limit(1)
            ).first()
            if row:
                return User(identifier=identifier, metadata={})
        return None

    async def create_user(self, user: User) -> Optional[User]:
        """User creation is handled by our on_chat_start pipeline."""
        return user

    # ── Threads ───────────────────────────────────────────────────────────────

    async def get_thread_author(self, thread_id: str) -> str:
        with Session(engine) as session:
            row = session.exec(
                select(DialogueLog)
                .where(DialogueLog.chat_session_id == thread_id)
                .limit(1)
            ).first()
            return row.user_id if row else "unknown"

    async def list_threads(
        self,
        pagination: Pagination,
        filters: ThreadFilter,
    ) -> PaginatedResponse[ThreadDict]:
        user_id = filters.userId
        if not user_id:
            return PaginatedResponse(
                data=[],
                pageInfo={"hasNextPage": False, "startCursor": None, "endCursor": None},
            )

        with Session(engine) as session:
            # Find all unique chat_session_ids for this user with their latest timestamp
            all_logs = session.exec(
                select(DialogueLog)
                .where(DialogueLog.user_id == user_id)
                .where(DialogueLog.chat_session_id.isnot(None))  # type: ignore[union-attr]
                .order_by(DialogueLog.timestamp.desc())          # type: ignore[union-attr]
            ).all()

            # Deduplicate by chat_session_id, keeping the latest timestamp for ordering
            seen: dict[str, DialogueLog] = {}
            ordered_ids: list[str] = []
            for row in all_logs:
                sid = row.chat_session_id
                if sid and sid not in seen:
                    seen[sid] = row
                    ordered_ids.append(sid)

            threads: list[ThreadDict] = []
            for sid in ordered_ids:
                last_row = seen[sid]
                # Use the first user message as the thread display name
                first_user = session.exec(
                    select(DialogueLog)
                    .where(DialogueLog.chat_session_id == sid)
                    .where(DialogueLog.role == "user")
                    .order_by(DialogueLog.timestamp.asc())  # type: ignore[union-attr]
                    .limit(1)
                ).first()
                raw_name = (
                    first_user.message[:60] if first_user and first_user.message else sid[:16]
                )
                name = raw_name.strip() or sid[:16]

                threads.append(
                    ThreadDict(
                        id=sid,
                        createdAt=last_row.timestamp.isoformat()
                        if last_row.timestamp
                        else _utcnow_iso(),
                        name=name,
                        userId=user_id,
                        userIdentifier=user_id,
                        tags=[],
                        metadata={},
                        steps=[],
                        elements=[],
                    )
                )

        return PaginatedResponse(
            data=threads,
            pageInfo={"hasNextPage": False, "startCursor": None, "endCursor": None},
        )

    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        with Session(engine) as session:
            logs = session.exec(
                select(DialogueLog)
                .where(DialogueLog.chat_session_id == thread_id)
                .order_by(DialogueLog.timestamp.asc())  # type: ignore[union-attr]
            ).all()
            if not logs:
                return None

            user_id = logs[0].user_id
            steps = [_log_to_step(row) for row in logs]

            first_user = next((r for r in logs if r.role == "user"), logs[0])
            name = (first_user.message[:60] if first_user.message else thread_id[:16]).strip()

            return ThreadDict(
                id=thread_id,
                createdAt=logs[0].timestamp.isoformat() if logs[0].timestamp else _utcnow_iso(),
                name=name,
                userId=user_id,
                userIdentifier=user_id,
                tags=[],
                metadata={},
                steps=steps,
                elements=[],
            )

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        pass  # We don't need to persist thread metadata separately

    async def delete_thread(self, thread_id: str) -> None:
        pass  # Preserve all history

    # ── Steps (messages) ─────────────────────────────────────────────────────
    # We persist messages ourselves in handlers.py; these are all no-ops.

    async def create_step(self, step_dict: dict) -> None:
        pass

    async def update_step(self, step_dict: dict) -> None:
        pass

    async def delete_step(self, step_id: str) -> None:
        pass

    # ── Elements ─────────────────────────────────────────────────────────────

    async def get_element(self, thread_id: str, element_id: str) -> Optional[dict]:
        return None

    async def create_element(self, element) -> None:
        pass

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None) -> None:
        pass

    # ── Feedback ─────────────────────────────────────────────────────────────

    async def upsert_feedback(self, feedback: Feedback) -> str:
        return str(uuid4())

    async def delete_feedback(self, feedback_id: str) -> None:
        pass

    # ── Misc ─────────────────────────────────────────────────────────────────

    async def get_favorite_steps(self) -> List[dict]:
        return []

    async def build_debug_url(self) -> Optional[str]:
        return None

    async def close(self) -> None:
        pass
