from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlmodel import Session

from app.config import settings
from app.contracts import PersonaSpeakRequest
from app.db.context import get_character_lore_block
from app.db.database import engine
from app.db.models import CharacterPersona, SideCharacter
from sqlmodel import select

_BASE_SYSTEM = """\
You are the Persona Agent. You speak exclusively as the character described below.
You DO NOT modify any game state. You only generate authentic in-character dialogue.

CHARACTER: {name}
MOTIVATION: {motivation}
HIDDEN SECRET: {hidden_secret}
SPEAKING STYLE: {speaking_style}
BEHAVIORAL PROFILE:
  - Risk Tolerance: {risk_tolerance}/100 (0=coward, 100=reckless)
  - Loyalty: {loyalty}/100 (0=betrayer, 100=devoted)
  - Aggression: {aggression}/100 (0=pacifist, 100=violent)
{lore_block}
Stay completely in character. React authentically to the situation given.\
"""


class PersonaAgent:
    """
    Read-only NPC voice agent.
    Receives a read-only context dict — never a DB session.
    Cannot mutate any state.
    """

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.persona_model,   # Steelskull/L3.3-Nevoria-R1-70b
            streaming=False,
        )

    def _load_persona(self, character_name: str) -> dict | None:
        """Read character persona + tarot affinity. Returns a plain dict (no session leak)."""
        with Session(engine) as session:
            char = session.exec(
                select(SideCharacter).where(SideCharacter.name == character_name)
            ).first()
            if not char or not char.persona:
                return None
            p: CharacterPersona = char.persona

            # ── JIT Tarot Lore injection ──────────────────────────────────────
            lore_block = get_character_lore_block(character_name, session)

            return {
                "name": char.name,
                "motivation": p.motivation,
                "hidden_secret": p.hidden_secret,
                "speaking_style": p.speaking_style,
                "risk_tolerance": p.risk_tolerance,
                "loyalty": p.loyalty,
                "aggression": p.aggression,
                "lore_block": lore_block,
            }

    async def speak(self, request: PersonaSpeakRequest) -> str:
        """Generate in-character dialogue for an NPC. Read-only — no DB writes."""
        persona = self._load_persona(request.character_name)

        if persona:
            system_prompt = _BASE_SYSTEM.format(**persona)
        else:
            system_prompt = (
                f"You are {request.character_name}, an NPC in an RPG world. "
                "Respond in character based on the context given."
            )

        history_block = ""
        if request.recent_dialogue:
            history_block = "\n\nRecent dialogue history:\n" + "\n".join(
                f"  - {line}" for line in request.recent_dialogue
            )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Situation: {context}{history}\n\nRespond as {name} now."),
        ])

        chain = prompt | self.llm
        response = await chain.ainvoke({
            "context": request.context,
            "history": history_block,
            "name": request.character_name,
        })

        content = response.content
        if isinstance(content, list):
            content = content[0].get("text", "") if content else ""
        return content


# Module-level singleton
persona_agent = PersonaAgent()
