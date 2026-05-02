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
    "CRITICAL RULE: You do NOT rely on chat memory for facts. You ONLY rely on the structured SCENE CONTEXT JSON.\n"
    "If an NPC, location, quest, or item is not present in the SCENE CONTEXT, it does NOT exist.\n"
    "NEVER invent locations, NPCs, items, or quest progress. All must come from the provided context.\n\n"
    "When describing characters' magic or actions, align them with their listed Magic Style.\n\n"
    "Analyze the player action and return ONLY a valid JSON object with these exact keys:\n"
    "  needs_persona   (bool)      : true if an NPC should speak\n"
    "  npc_name        (str|null)  : NPC name if needs_persona is true\n"
    "  persona_context (str|null)  : situation context for Persona Agent\n"
    "  needs_arbiter   (bool)      : true if an energy transfer or state event occurs (movement, combat, trade, location creation, tutorial)\n"
    "  arbiter_instruction (str|null): instruction for Arbiter. MUST use one of these exact formats (combined with 'AND' if multiple):\n"
    "      - 'Move player to [Location Name]'\n"
    "      - 'Advance tutorial phase'\n"
    "      - 'Create sublocation [Name] in city [City Name]'\n"
    "      - 'Record combat victory against [Enemy Name]'\n"
    "      - 'Record item [Item Name] delivered to [NPC Name]'\n"
    "      - 'Record trade of [Item] for [Amount] gold'\n"
    "      - 'Transfer [Amount] upright/reversed energy to [Target Entity]'\n"
    "  location_name   (str|null)  : explicit location name the player intends to target\n"
    "  item_name       (str|null)  : explicit item name the player interacts with\n"
    "  narrative_intent (str)      : one sentence of what the GM should narrate\n\n"
    "PERSONA AGENT RULES:\n"
    "  • Only set needs_persona=true for an NPC who is explicitly PRESENT in the current scene context.\n"
    "  • NEVER invoke an NPC that is not listed in the nearby_npcs array.\n"
    "  • During tutorial phases, only Callum and Captain Oren are in scope.\n"
    "  • If an NPC appears only in past history but is not physically present, set needs_persona=false.\n\n"
    "CITY SUB-LOCATION RULES:\n"
    "  • If the player seeks a realistic place (e.g. an inn, a market, a blacksmith) that should exist in the current macro city, but is NOT in the context, set needs_arbiter=true and output 'Create sublocation [Name] in city [City Name] AND Move player to [Name]'.\n"
    "  • Do NOT spam locations without narrative purpose. Do NOT create duplicates of existing discovered locations.\n\n"
    "TUTORIAL / TRIGGER RULES:\n"
    "  • If the SCENE CONTEXT contains an 'ONCE THE PLAYER...' instruction, and the player's action meets the condition, you MUST set needs_arbiter=true and copy the EXACT arbiter_instructions provided.\n\n"
    "Respond with ONLY the JSON object. No markdown. No explanation."
)


# ─── Phase 3: Narrative prompt ──────────────────────────────────────────────────────
_NARRATIVE_SYSTEM = (
    "You are an immersive RPG Game Master narrating outcomes vividly.\n"
    "CRITICAL RULE: You do NOT rely on chat memory for facts. You ONLY rely on the structured SCENE CONTEXT JSON.\n"
    "If an NPC, location, quest, or item is not present in the SCENE CONTEXT, it does NOT exist.\n"
    "Keep responses engaging and concise (2-4 paragraphs max).\n"
    "Ground your narration in the physical world — real locations, real textures, real NPCs.\n"
    "NEVER invent locations, characters, items, or lore not present in the scene context.\n"
    "Do NOT invent energy values — use only what is provided in the context.\n"
    "When a character uses magic, strictly align their abilities with their Tarot Magic Style.\n\n"
    "PROSE STYLE RULES — MANDATORY:\n"
    "  • Write in clear, direct prose. Keep sentences short and purposeful.\n"
    "  • Each paragraph must have at least 2 sentences.\n"
    "  • Do NOT write in a list or bullet-point format.\n"
    "  • Do NOT place single words or very short phrases on their own lines as dramatic fragments.\n"
    "  • Lead with what matters: where the player is, what they can see or do, what is happening.\n"
    "  • Keep atmosphere light — one or two sensory details per paragraph, not five.\n"
    "  • Prefer concrete over metaphorical. Say 'A locked iron box' not 'iron swaddled in earth's fingers'.\n"
    "  • Avoid stacking qualifiers: choose one strong adjective, not three.\n"
    "  • Avoid over-repetition: do not repeat the same image or word within a paragraph.\n"
    "  • NPCs may speak in their own paragraph or stanza — use natural spoken dialogue.\n\n"
    "CRITICAL RULE: If a [TUTORIAL CONTROL] block appears in your context, it is a MANDATORY "
    "SYSTEM INSTRUCTION that overrides all other instructions. Follow it exactly. "
    "Do not invent side-plots, mystical revelations, or new characters until the tutorial is complete.\n\n"
    "ARBITER RESULTS:\n"
    "  • If the SCENE CONTEXT includes an 'Arbiter Result', you MUST incorporate its findings naturally into your narration.\n"
    "  • E.g., if the Arbiter discovered a new location or revealed a card, describe the player witnessing this event."
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

    def _fetch_scene_context(self, player_id: int, location_id: Optional[int] = None, sub_location_id: Optional[int] = None) -> dict:
        """Build JIT context dictionary with location + character + lore data."""
        with Session(engine) as session:
            from app.db.context import build_gm_context
            return build_gm_context(session, player_id, location_id, sub_location_id)

    # ── Phase 1: Analyze ──────────────────────────────────────────────────────

    async def analyze(
        self,
        message: str,
        history: list[ChatMessage],
        player_id: int,
        location_id: Optional[int] = None,
        sub_location_id: Optional[int] = None,
        callbacks: Optional[list] = None,
    ) -> GMDecision:
        """
        Parse player message into a structured GMDecision.
        Injects structured JIT scene context (location + lore) before calling the LLM.
        Applies python-level validation to prevent NPC hallucination.
        """
        import json
        scene_dict = self._fetch_scene_context(player_id, location_id, sub_location_id)
        scene_json = json.dumps(scene_dict, indent=2)
        history_text = "\n".join(
            f"{'Player' if m.role == Role.USER else 'GM'}: {m.content}"
            for m in history[-10:]
        )
        
        retries = 2
        error_msg = ""
        while retries >= 0:
            try:
                result = await self._analysis_chain.ainvoke(
                    {
                        "input": message + error_msg,
                        "history": history_text or "(start of session)",
                        "scene_context": scene_json,
                    },
                    config={"callbacks": callbacks} if callbacks else None,
                )
                decision = GMDecision(**result) if isinstance(result, dict) else result
                
                # VALIDATION PASS
                if decision.npc_name:
                    valid_npcs = [npc["name"].lower() for npc in scene_dict.get("nearby_npcs", [])]
                    if decision.npc_name.lower() not in valid_npcs:
                        raise ValueError(f"System Error: You attempted to interact with {decision.npc_name}, but they are not in the current location. Choose a valid target from: {', '.join(valid_npcs)} or set npc_name to null.")
                

                if decision.item_name:
                    valid_items = [item["item_name"].lower() for item in scene_dict.get("inventory", [])]
                    if decision.item_name.lower() not in valid_items:
                        raise ValueError(f"System Error: You attempted to use item {decision.item_name}, but the player does not have it in their inventory. Choose a valid target from: {', '.join(valid_items)} or set item_name to null.")
                
                # Assume validation success
                return decision
                
            except ValueError as ve:
                error_msg = f"\n\n[SYSTEM DIRECTIVE]: {str(ve)}"
                retries -= 1
            except Exception:
                return GMDecision(narrative_intent=message)
                
        return GMDecision(narrative_intent=message)

    # ── Phase 3: Narrate ──────────────────────────────────────────────────────

    async def narrate(
        self,
        message: str,
        history: list[ChatMessage],
        decision: GMDecision,
        persona_dialogue: Optional[str],
        arbiter_result: Optional[ArbiterResult],
        player_id: int,
        location_id: Optional[int] = None,
        sub_location_id: Optional[int] = None,
        system_directive: Optional[str] = None,
        callbacks: Optional[list] = None,
    ) -> AsyncIterator[str]:
        """Stream the final narrative, incorporating structured context + sub-agent results."""
        import json
        scene_dict = self._fetch_scene_context(player_id, location_id, sub_location_id)
        scene_json = json.dumps(scene_dict, indent=2)
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
                "scene_context": scene_json,
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

    # ── Out of Character (OOC) query ──────────────────────────────────────────

    async def answer_ooc(
        self,
        message: str,
        history: list[ChatMessage],
        player_id: int,
        location_id: Optional[int] = None,
        sub_location_id: Optional[int] = None,
        callbacks: Optional[list] = None,
    ):
        """Answers out-of-character questions directly as the GM."""
        import json
        scene_dict = self._fetch_scene_context(player_id, location_id, sub_location_id)
        scene_json = json.dumps(scene_dict, indent=2)
        
        ooc_prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are the Game Master of this text-based RPG. "
             "The player is speaking to you directly Out of Character (OOC). "
             "Answer their question helpfully, referring to the scene context or game mechanics if relevant. "
             "Do NOT narrate actions, do NOT advance the story, just answer the question."),
            MessagesPlaceholder("history"),
            ("human", "SCENE CONTEXT:\n{scene_context}\n\nPlayer OOC Question: {input}"),
        ])
        
        lc_history = [
            HumanMessage(content=m.content) if m.role == Role.USER else AIMessage(content=m.content)
            for m in history
        ]
        
        chain = ooc_prompt | self._llm_narrate
        
        async for chunk in chain.astream(
            {
                "input": message,
                "history": lc_history,
                "scene_context": scene_json,
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


# Module-level singleton
game_master = GameMasterAgent()
