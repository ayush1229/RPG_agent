"""
app/agent/summarizer.py
========================
Conversation Summarizer Agent.

Condenses older dialogue logs into a structured key-facts summary that gets
injected into GM context instead of the full chat history.

Responsibilities:
  - Fetch the last N dialogue turns from the DB
  - Call the LLM to compress them into structured key facts
  - Update ConversationSummary (upsert by user_id)

Rules:
  - NEVER sends compressed log back as raw dialogue
  - Summary must capture: decisions, NPC relationships, quests, major events
  - Concise: target 150-300 words max
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from sqlmodel import Session, select

from app.config import settings
from app.db.models import ConversationSummary, DialogueLog

# How many dialogue rows to feed the summarizer
SUMMARIZE_WINDOW = 20

_SUMMARIZE_PROMPT = """\
You are an RPG session recorder. Given the following dialogue between a player \
and the Game Master, extract a concise factual summary (150-300 words max).

Focus ONLY on:
- Important decisions the player made
- NPCs the player interacted with and the relationship formed (ally/enemy/neutral)
- Quests started, advanced, or completed
- Combat outcomes
- Major world events or lore reveals
- Player's current goals and intentions

Do NOT include:
- Flavour narration
- Repeated information
- Meta-commentary
- Descriptive prose or adjectives

BAD EXAMPLE:
"The player walked through the dark and foreboding forest, their boots crunching on the leaves, and bravely fought a group of vicious bandits."

GOOD EXAMPLE:
"Player reached Whispering Forest, defeated a bandit group, gained item 'Rust Blade'."

DIALOGUE:
{dialogue}

EXISTING SUMMARY (update/extend this, do not repeat facts already captured):
{existing_summary}

UPDATED SUMMARY:"""


class SummarizerAgent:
    """
    Wraps the LLM call to produce a structured session summary.
    Non-streaming, deterministic (temperature=0.3).
    """

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            streaming=False,
            temperature=0.3,
            max_tokens=512,
        )
        self._chain = (
            PromptTemplate(
                template=_SUMMARIZE_PROMPT,
                input_variables=["dialogue", "existing_summary"],
            )
            | self._llm
        )

    async def summarize(
        self,
        session: Session,
        user_id: str,
        *,
        window: int = SUMMARIZE_WINDOW,
    ) -> str:
        """
        Fetch recent dialogue logs, call LLM, update ConversationSummary.
        Returns the new summary string.
        """
        # 1. Fetch recent dialogue rows (ordered oldest→newest)
        logs = session.exec(
            select(DialogueLog)
            .where(DialogueLog.user_id == user_id)
            .order_by(DialogueLog.timestamp)  # type: ignore[arg-type]
        ).all()

        if not logs:
            return "No history yet."

        # Use the last `window` entries
        recent_logs = logs[-window:]
        dialogue_text = "\n".join(
            f"{log.role.upper()}: {log.message}" for log in recent_logs
        )

        # 2. Fetch existing summary
        existing = session.exec(
            select(ConversationSummary).where(ConversationSummary.user_id == user_id)
        ).first()
        existing_text = existing.summary if existing else "No history yet."

        # 3. Call LLM
        try:
            result = await self._chain.ainvoke({
                "dialogue": dialogue_text,
                "existing_summary": existing_text,
            })
            new_summary = result.content.strip() if hasattr(result, "content") else str(result).strip()
        except Exception:
            # Fallback: keep existing summary on LLM failure
            return existing_text

        # 4. Upsert ConversationSummary
        if existing:
            existing.summary = new_summary
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
        else:
            session.add(ConversationSummary(
                user_id=user_id,
                summary=new_summary,
                updated_at=datetime.now(timezone.utc),
            ))

        session.commit()
        return new_summary


# Module-level singleton
summarizer_agent = SummarizerAgent()
