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


class GameState(Enum):
    """Execution flow state of the game engine."""
    # Phase 1: Onboarding
    INTERVIEW = 1
    CARD_DRAW = 2
    WORLD_INTRO = 3

    # Phase 2: Core Loop
    ACTIVE_ROLEPLAY = 4          # Default exploration / narration
    NPC_INTERACTION = 5          # Persona-driven dialogue
    SYSTEM_INTERCEPT = 6         # Conflict detected (GM pauses)

    # Phase 3: Resolution Layer
    ARBITER_RESOLUTION = 7       # Arbiter executing rules
    POST_RESOLUTION = 8          # GM narrates outcome

    # Phase 4: End States
    DEATH = 9
    ASCENSION = 10


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
