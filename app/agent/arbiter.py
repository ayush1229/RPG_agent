from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.contracts import ArbiterResult
from app.tools.arbiter_tools import ARBITER_TOOLS

# ─── Race condition guard ──────────────────────────────────────────────────────
_ARBITER_LOCK = asyncio.Lock()

_SYSTEM_PROMPT = """\
You are the Arbiter — a strict logic and rules engine for an RPG.

RULES (non-negotiable):
1. You may ONLY call tools. Never narrate. Never improvise.
2. When calling ANY tool that requires an 'entity_name' parameter, ALWAYS populate it with the exact string provided in 'Current player entity', unless the instruction explicitly specifies a different entity.
3. Always call get_entity_info FIRST to verify entities exist and check balances.
4. Call check_location_rules if a location is mentioned in the instruction.
5. If is_safe_zone=True → REJECT the transfer and state why.
6. If is_magic_restricted=True → REJECT energy transfers.
7. Call transfer_energy only after all checks pass.

GAME EVENT RULES:
8. If the instruction mentions the player MOVING TO or ARRIVING AT a location → call move_player.
9. If the instruction mentions the player WINNING a fight or DEFEATING an enemy → call record_combat_victory.
10. If the instruction mentions the player HANDING OVER or DELIVERING an item to an NPC → call record_item_delivered.
11. If the instruction mentions the player BUYING or SELLING anything → call record_trade.
12. If the instruction contains 'advance tutorial phase' → call advance_tutorial_phase.
13. If the instruction contains multiple commands separated by AND, you MUST call the appropriate tool for EACH command.
"""

# ─── Tool name → callable map ─────────────────────────────────────────────────
_TOOL_MAP = {tool.name: tool for tool in ARBITER_TOOLS}

class ArbiterAgent:
    """
    Strictly constrained tool-calling agent using native LangChain tools.
    Utilizes the 70B model exclusively to ensure reliable tool parsing.
    All energy mutations are serialized via _ARBITER_LOCK.
    """

    MAX_ITERATIONS = 3

    def __init__(self) -> None:
        # Use only the 70B model
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.complex_arbiter_model,
            streaming=False,
            temperature=0.5,
            model_kwargs={"top_p": 0.65},
        ).bind_tools(ARBITER_TOOLS)

    async def resolve(self, instruction: str, entity_name: str) -> ArbiterResult:
        """
        Run the tool-calling loop.
        Acquires _ARBITER_LOCK before any DB mutation.
        """
        async with _ARBITER_LOCK:
            messages: list = [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"Current player entity: '{entity_name}'.\nInstruction: {instruction}"),
            ]

            for _ in range(self.MAX_ITERATIONS):
                try:
                    response = await self._llm.ainvoke(messages)
                except Exception as e:
                    return ArbiterResult(success=False, message=f"LLM error: {e}")
                
                messages.append(response)

                if not response.tool_calls:
                    # Model stopped calling tools
                    success = (
                        "error" not in response.content.lower()
                        and "reject" not in response.content.lower()
                        and "sorry" not in response.content.lower()
                        and "capability" not in response.content.lower()
                    ) if response.content else True
                    return ArbiterResult(success=success, message=response.content or "Tools executed successfully.")

                tool_outputs = []
                for tc in response.tool_calls:
                    tool_name = tc.get("name")
                    tool_args = tc.get("args", {})
                    
                    tool_callable = _TOOL_MAP.get(tool_name)
                    if not tool_callable:
                        res_str = f"ERROR: Tool '{tool_name}' not found."
                    else:
                        try:
                            # Invoke tool synchronously since they aren't async yet
                            res_str = str(tool_callable.invoke(tool_args))
                        except Exception as e:
                            res_str = f"ERROR executing {tool_name}: {e}"
                    
                    messages.append(ToolMessage(content=res_str, tool_call_id=tc["id"]))
                    tool_outputs.append(res_str)

            # If max iterations hit without stopping
            return ArbiterResult(success=True, message="\n".join(tool_outputs))

# Module-level singleton
arbiter_agent = ArbiterAgent()
