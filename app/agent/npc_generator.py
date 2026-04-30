"""
app/agent/npc_generator.py
==========================
NPC Generator Agent.

Calls the GM model with a structured prompt to produce a valid NPC JSON.
Returns a typed NPCBlueprint that the service layer uses to commit the entity.

Responsibilities:
  - Build the generation prompt with power-level energy bounds and card lore context
  - Call the LLM (same GM model / key / URL from settings)
  - Parse and validate the JSON output
  - Raise ValueError on malformed or out-of-bounds responses

Does NOT touch the database — that is the exclusive domain of TarotService.generate_npc().
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings

# ── Energy bounds per power tier ─────────────────────────────────────────────
POWER_TIER_RANGES: dict[str, tuple[int, int]] = {
    "low":   (1,          1_000),
    "mid":   (1_001,      100_000),
    "high":  (100_001,    5_000_000),
    "elite": (5_000_001,  50_000_000),
}

# Pareto-skewed spawn weights (used by service, exposed here for reference)
TIER_WEIGHTS: dict[str, float] = {
    "low":   0.70,
    "mid":   0.20,
    "high":  0.09,
    "elite": 0.01,
}

# Location-based spawn bias: dangerous zones skew toward higher tiers
LOCATION_BIAS: dict[str, str] = {
    "dungeon":    "high",
    "ruins":      "high",
    "wilderness": "mid",
    "forest":     "mid",
    "city":       "low",
    "town":       "low",
    "village":    "low",
    "capital":    "mid",
    "castle":     "mid",
    "temple":     "mid",
    "arena":      "high",
    "mine":       "mid",
    "cave":       "high",
    "void":       "elite",
    "abyss":      "elite",
}

# ── NPC prompt ────────────────────────────────────────────────────────────────
_NPC_GENERATION_PROMPT = """You are generating a structured NPC for a tarot-based RPG system with a strict global energy economy.

CONTEXT:
* Total energy is limited and must be conserved — every unit assigned to an NPC is deducted from the world reserve.
* Each NPC must be aligned to ONE Major Arcana card.
* NPCs have roles: ally, enemy, neutral, ruler.
* Sovereigns are forbidden — do NOT generate sovereign-level entities.

AVAILABLE CARDS (Major Arcana only):
{card_list}

INPUT:
* role: {role}
* power_level: {power_level}
* location: {location_name}
* optional_card: {optional_card}
* energy_range: {energy_min} to {energy_max}

RULES:
1. Assign a Tarot card affinity from the list above. If optional_card is provided and valid, use it.
2. Assign energy_amount — must be an integer strictly within [{energy_min}, {energy_max}].
3. Energy must be EITHER upright OR reversed — not both.
4. Personality must reflect the chosen Tarot card's meaning and the role behavior:
   * ally   -> cooperative, helpful, approaches player with good intent
   * enemy  -> aggressive, conflicting, acts against player interests
   * neutral-> conditional, transactional, neither ally nor enemy by default
   * ruler  -> authoritative, commanding, controls local territory
5. Generate realistic motivations and hidden secrets that create narrative hooks.
6. level_estimate: integer 1-100 scaling with energy (low=1-10, mid=11-35, high=36-70, elite=71-100).
7. Do NOT create sovereigns (is_upright_sovereign / is_reversed_sovereign must remain false).

OUTPUT: respond with ONLY a valid JSON object, no markdown, no commentary:
{{
  "name": "...",
  "position": "...",
  "current_status": "...",
  "card_affinity": "...",
  "energy_type": "upright | reversed",
  "energy_amount": <integer in [{energy_min}, {energy_max}]>,
  "role": "...",
  "personality": "...",
  "motivation": "...",
  "hidden_secret": "...",
  "level_estimate": <integer 1-100>
}}"""


# ── Blueprint dataclass ───────────────────────────────────────────────────────
@dataclass
class NPCBlueprint:
    name: str
    position: str
    current_status: str
    card_affinity: str          # name of a Major Arcana card
    energy_type: str            # "upright" | "reversed"
    energy_amount: int
    role: str
    personality: str
    motivation: str
    hidden_secret: str
    level_estimate: int


# ── Agent class ───────────────────────────────────────────────────────────────
class NPCGeneratorAgent:
    """
    Calls the GM LLM to generate a structured NPC blueprint.

    Usage:
        agent = NPCGeneratorAgent()
        blueprint = await agent.generate(
            role="enemy",
            power_level="mid",
            location_name="Dark Forest",
            card_names=["The Fool", "The Tower", ...],
            optional_card="The Tower",
        )
    """

    VALID_ROLES = {"ally", "enemy", "neutral", "ruler"}
    VALID_TIERS = set(POWER_TIER_RANGES.keys())
    VALID_ENERGY_TYPES = {"upright", "reversed"}

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            streaming=False,
            temperature=0.8,
            top_p=0.9,
            max_tokens=1024,
        )
        self._parser = JsonOutputParser()
        self._chain = (
            PromptTemplate(
                template=_NPC_GENERATION_PROMPT,
                input_variables=[
                    "card_list", "role", "power_level", "location_name",
                    "optional_card", "energy_min", "energy_max",
                ],
            )
            | self._llm
            | self._parser
        )

    @staticmethod
    def pick_power_level(
        requested_tier: Optional[str] = None,
        location_name: str = "",
    ) -> str:
        """
        Choose a power level with Pareto-skewed bias.
        If requested_tier is given, use it. Otherwise, apply location bias
        then random weighted selection.
        """
        if requested_tier:
            if requested_tier not in POWER_TIER_RANGES:
                raise ValueError(
                    f"Invalid power_level '{requested_tier}'. "
                    f"Must be one of: {list(POWER_TIER_RANGES)}"
                )
            return requested_tier

        # Location bias: check if any keyword appears in the location name
        loc_lower = location_name.lower()
        for keyword, biased_tier in LOCATION_BIAS.items():
            if keyword in loc_lower:
                # Bias: 60% chance to use the biased tier, 40% random
                if random.random() < 0.60:
                    return biased_tier
                break

        # Weighted random selection
        tiers = list(TIER_WEIGHTS.keys())
        weights = list(TIER_WEIGHTS.values())
        return random.choices(tiers, weights=weights, k=1)[0]

    async def generate(
        self,
        role: str,
        power_level: str,
        location_name: str,
        card_names: list[str],
        optional_card: Optional[str] = None,
    ) -> NPCBlueprint:
        """
        Call LLM and return a validated NPCBlueprint.
        Raises ValueError on invalid role, tier, or LLM output.
        """
        if role not in self.VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {self.VALID_ROLES}")
        if power_level not in self.VALID_TIERS:
            raise ValueError(f"Invalid power_level '{power_level}'. Must be one of: {self.VALID_TIERS}")

        energy_min, energy_max = POWER_TIER_RANGES[power_level]
        card_list = "\n".join(f"  - {c}" for c in sorted(card_names))

        raw = await self._chain.ainvoke({
            "card_list": card_list,
            "role": role,
            "power_level": power_level,
            "location_name": location_name,
            "optional_card": optional_card or "null (choose freely)",
            "energy_min": energy_min,
            "energy_max": energy_max,
        })

        return self._validate(raw, power_level, energy_min, energy_max, card_names)

    def _validate(
        self,
        raw: dict,
        power_level: str,
        energy_min: int,
        energy_max: int,
        card_names: list[str],
    ) -> NPCBlueprint:
        """Validate the LLM JSON output and return a typed NPCBlueprint."""
        required = {
            "name", "position", "current_status", "card_affinity",
            "energy_type", "energy_amount", "role", "personality",
            "motivation", "hidden_secret", "level_estimate",
        }
        missing = required - set(raw.keys())
        if missing:
            raise ValueError(f"LLM output missing required fields: {missing}")

        # Energy type
        energy_type = str(raw["energy_type"]).strip().lower()
        if energy_type not in self.VALID_ENERGY_TYPES:
            raise ValueError(f"Invalid energy_type '{energy_type}' from LLM.")

        # Energy amount
        try:
            energy_amount = int(raw["energy_amount"])
        except (TypeError, ValueError):
            raise ValueError(f"energy_amount must be an integer, got: {raw['energy_amount']}")

        if not (energy_min <= energy_amount <= energy_max):
            # Clamp rather than reject — LLMs sometimes go slightly off-range
            energy_amount = max(energy_min, min(energy_max, energy_amount))

        # Card affinity — must be a real Major Arcana name
        card_affinity = str(raw["card_affinity"]).strip()
        if card_affinity not in card_names:
            # Fuzzy match: pick the closest card name by case-insensitive prefix
            match = next(
                (c for c in card_names if c.lower().startswith(card_affinity.lower()[:6])),
                card_names[0],   # fallback to first card
            )
            card_affinity = match

        # level_estimate clamp
        try:
            level = max(1, min(100, int(raw["level_estimate"])))
        except (TypeError, ValueError):
            level = {"low": 5, "mid": 20, "high": 55, "elite": 85}[power_level]

        return NPCBlueprint(
            name=str(raw["name"]).strip(),
            position=str(raw["position"]).strip(),
            current_status=str(raw["current_status"]).strip(),
            card_affinity=card_affinity,
            energy_type=energy_type,
            energy_amount=energy_amount,
            role=str(raw["role"]).strip(),
            personality=str(raw["personality"]).strip(),
            motivation=str(raw["motivation"]).strip(),
            hidden_secret=str(raw["hidden_secret"]).strip(),
            level_estimate=level,
        )


# Module-level singleton
npc_generator = NPCGeneratorAgent()
