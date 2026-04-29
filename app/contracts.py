from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ── Inter-agent communication schemas ─────────────────────────────────────────
# The Game Master NEVER touches TarotEntity directly.
# It sends EnergyTransferRequest to the Arbiter and PersonaSpeakRequest to Persona.


class EnergyTransferRequest(BaseModel):
    """Structured request the GM sends to the Arbiter for energy mechanics."""
    from_entity_name: str
    to_entity_name: str
    upright_amount: int = Field(default=0, ge=0)
    reversed_amount: int = Field(default=0, ge=0)
    reason: str


class PersonaSpeakRequest(BaseModel):
    """Context the GM sends to the Persona Agent to generate NPC dialogue."""
    character_name: str
    context: str                       # narrative situation
    recent_dialogue: list[str] = []    # last N dialogue entries from CharacterHistory


class ArbiterResult(BaseModel):
    """What the Arbiter returns to the GM after resolving an energy action."""
    success: bool
    upright_transferred: int = 0
    reversed_transferred: int = 0
    message: str                       # human-readable outcome for the GM to narrate


class GMDecision(BaseModel):
    """
    Structured output from the GM's analysis phase.
    Drives which sub-agents get called and what they receive.
    """
    needs_persona: bool = False
    npc_name: Optional[str] = None
    persona_context: Optional[str] = None

    needs_arbiter: bool = False
    # Natural-language instruction for the Arbiter's tool-calling LLM
    arbiter_instruction: Optional[str] = None

    # What the GM wants to ultimately narrate (used in Phase 3 prompt)
    narrative_intent: str
