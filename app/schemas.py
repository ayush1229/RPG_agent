from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Chat participant roles."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentStatus(str, Enum):
    """Lifecycle states of the agent during a turn."""
    IDLE = "idle"
    THINKING = "thinking"
    RESPONDING = "responding"
    ERROR = "error"


class ChatMessage(BaseModel):
    """A single message in the conversation history."""
    role: Role
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentResponse(BaseModel):
    """
    What the agent returns after processing a user message.
    'metadata' is a free-form dict for future use (tool calls, token counts, etc.)
    """
    text: str
    status: AgentStatus = AgentStatus.RESPONDING
    is_streaming: bool = False
    metadata: dict = Field(default_factory=dict)
