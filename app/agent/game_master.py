from __future__ import annotations

from typing import AsyncIterator, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_openai import ChatOpenAI
from sqlmodel import Session

from app.config import settings
from app.contracts import ArbiterResult, GMDecision
from app.db.context import build_gm_context
from app.db.database import engine
from app.db.models import CharacterHistory
from app.schemas import ChatMessage, Role

# ─── Phase 1: Analysis prompt ─────────────────────────────────────────────────
_ANALYSIS_SYSTEM = (
    "You are the decision engine of an RPG Game Master.\n"
    "You have access to the active scene context (location, characters, Tarot affinities) below.\n"
    "When describing characters' magic or actions, align them with their listed Magic Style.\n\n"
    "Analyze the player action and return ONLY a valid JSON object with these exact keys:\n"
    "  needs_persona   (bool)      : true if an NPC should speak\n"
    "  npc_name        (str|null)  : NPC name if needs_persona is true\n"
    "  persona_context (str|null)  : situation context for Persona Agent\n"
    "  needs_arbiter   (bool)      : true if an energy/resource transfer must happen\n"
    "  arbiter_instruction (str|null): e.g. 'Transfer 50 upright from Merchant to Player, reason: intimidation'\n"
    "  narrative_intent (str)      : one sentence of what the GM should narrate\n\n"
    "Respond with ONLY the JSON object. No markdown. No explanation."
)

# ─── Phase 3: Narrative prompt ──────────────────────────────────────────────────────
_NARRATIVE_SYSTEM = (
    "You are an immersive RPG Game Master narrating outcomes vividly.\n"
    "Keep responses engaging and concise (2-4 paragraphs max).\n"
    "Ground your narration in the physical world — real locations, real textures, real NPCs.\n"
    "Do NOT invent locations, characters, or lore not present in the scene context.\n"
    "Do NOT invent energy values — use only what is provided in the context.\n"
    "When a character uses magic, strictly align their abilities with their Tarot Magic Style.\n\n"
    "CRITICAL RULE: If a [TUTORIAL CONTROL] block appears in your context, it is a MANDATORY "
    "SYSTEM INSTRUCTION that overrides all other instructions. Follow it exactly. "
    "Do not invent side-plots, mystical revelations, or new characters until the tutorial is complete."
)


class GameMasterAgent:
    """
    Orchestrator agent. Two-phase execution:
      Phase 1 (analyze): Structured JSON output → GMDecision (with JIT lore context)
      Phase 3 (narrate): Streaming narrative incorporating sub-agent results + lore

    DB access: READ Location/SideCharacter/TarotCardLore + WRITE CharacterHistory only.
    Cannot touch TarotEntity (Arbiter's domain).
    """

    def __init__(self) -> None:
        # Standard OpenAI-compatible sampling parameters
        # Note: Qwen-specific extras (top_k, min_p) are NOT passed — they are
        # not part of the OpenAI API spec and cause 'unexpected keyword argument'
        # errors on most OpenAI-compatible endpoints.
        _llm_kwargs = {
            "temperature": 0.7,
            "top_p": 0.8,
            "max_tokens": 16384,
        }

        self._llm_analyze = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            streaming=False,
            **_llm_kwargs,
        )
        self._llm_narrate = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            streaming=True,
            **_llm_kwargs,
        )

        self._parser = JsonOutputParser(pydantic_object=GMDecision)

        # PromptTemplate avoids curly-brace conflicts with JSON examples in _ANALYSIS_SYSTEM
        self._analysis_chain = (
            PromptTemplate(
                template=(
                    _ANALYSIS_SYSTEM
                    + "\n\nSCENE CONTEXT:\n{scene_context}"
                    + "\n\nConversation so far:\n{history}"
                    + "\n\nPlayer action: {input}"
                ),
                input_variables=["scene_context", "history", "input"],
            )
            | self._llm_analyze
            | self._parser
        )

        self._narrative_prompt = ChatPromptTemplate.from_messages([
            ("system", _NARRATIVE_SYSTEM),
            MessagesPlaceholder("history"),
            ("human", (
                "SCENE CONTEXT:\n{scene_context}\n\n"
                "Player action: {input}\n\n"
                "Narrative intent: {narrative_intent}\n\n"
                "{npc_block}"
                "{arbiter_block}"
                "Narrate the outcome now."
            )),
            # Directive injected LAST as a system message = highest authority.
            # Overrides conversation history patterns (e.g. void interview tone).
            # Empty string when no directive is active.
            ("system", "{directive_block}"),
        ])
        self._narrative_chain = self._narrative_prompt | self._llm_narrate

    # ── JIT context fetcher (GM's read-only DB access) ────────────────────────

    def _fetch_scene_context(self, location_id: Optional[int] = None) -> str:
        """Build JIT context string with location + character + lore data."""
        with Session(engine) as session:
            return build_gm_context(session, location_id)

    # ── Phase 1: Analyze ──────────────────────────────────────────────────────

    async def analyze(
        self,
        message: str,
        history: list[ChatMessage],
        location_id: Optional[int] = None,
        callbacks: Optional[list] = None,
    ) -> GMDecision:
        """
        Parse player message into a structured GMDecision.
        Injects JIT scene context (location + lore) before calling the LLM.
        """
        scene_context = self._fetch_scene_context(location_id)
        history_text = "\n".join(
            f"{'Player' if m.role == Role.USER else 'GM'}: {m.content}"
            for m in history[-10:]
        )
        try:
            result = await self._analysis_chain.ainvoke(
                {
                    "input": message,
                    "history": history_text or "(start of session)",
                    "scene_context": scene_context or "(no active scene data)",
                },
                config={"callbacks": callbacks} if callbacks else None,
            )
            return GMDecision(**result) if isinstance(result, dict) else result
        except Exception:
            return GMDecision(narrative_intent=message)

    # ── Phase 3: Narrate ──────────────────────────────────────────────────────

    async def narrate(
        self,
        message: str,
        history: list[ChatMessage],
        decision: GMDecision,
        persona_dialogue: Optional[str],
        arbiter_result: Optional[ArbiterResult],
        location_id: Optional[int] = None,
        system_directive: Optional[str] = None,
        callbacks: Optional[list] = None,
    ) -> AsyncIterator[str]:
        """Stream the final narrative, incorporating lore context + sub-agent results.

        system_directive: injected from the StoryEnforcer for GM-directed prologue
        gates (e.g. card reveal). Never shown verbatim to the player.
        """
        scene_context = self._fetch_scene_context(location_id)
        lc_history = [
            HumanMessage(content=m.content) if m.role == Role.USER
            else AIMessage(content=m.content)
            for m in history
        ]

        npc_block = ""
        if persona_dialogue:
            npc_block = f'NPC ({decision.npc_name}) said: "{persona_dialogue}"\n\n'

        arbiter_block = ""
        if arbiter_result:
            status = "succeeded" if arbiter_result.success else "was rejected"
            arbiter_block = f"Energy transfer {status}: {arbiter_result.message}\n\n"

        # GM directive from the StoryEnforcer (highest priority context)
        directive_block = ""
        if system_directive:
            directive_block = f"{system_directive}\n\n"

        async for chunk in self._narrative_chain.astream(
            {
                "input": message,
                "history": lc_history,
                "narrative_intent": decision.narrative_intent,
                "scene_context": scene_context or "(no active scene data)",
                "npc_block": npc_block,
                "arbiter_block": arbiter_block,
                "directive_block": directive_block,
            },
            config={"callbacks": callbacks} if callbacks else None,
        ):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list) and content:
                text = content[0].get("text", "")
                if text:
                    yield text

    # ── CharacterHistory writer (only DB write the GM has) ────────────────────

    def log_event(self, character_id: int, event_type: str, description: str) -> None:
        """Append a CharacterHistory row. Only DB write the GM is permitted."""
        with Session(engine) as session:
            session.add(CharacterHistory(
                character_id=character_id,
                event_type=event_type,
                event_description=description,
            ))
            session.commit()


# Module-level singleton
game_master = GameMasterAgent()
