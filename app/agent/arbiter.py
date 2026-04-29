from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.contracts import ArbiterResult
from app.tools.arbiter_tools import ARBITER_TOOLS

# ─── Race condition guard ──────────────────────────────────────────────────────
_ARBITER_LOCK = asyncio.Lock()

# ─── Build XML tool manifest from registered tools ────────────────────────────

def _build_tools_xml() -> str:
    """Serialise all ARBITER_TOOLS into the XML format the model expects."""
    tool_defs = []
    for tool in ARBITER_TOOLS:
        schema: dict[str, Any] = {}
        if hasattr(tool, "args_schema") and tool.args_schema:
            try:
                schema = tool.args_schema.model_json_schema()
            except AttributeError:
                schema = tool.args_schema.schema()  # pydantic v1 fallback

        tool_defs.append(json.dumps({
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }, indent=2))

    return "<tools>\n" + "\n".join(tool_defs) + "\n</tools>"


_TOOLS_XML = _build_tools_xml()

_SYSTEM_PROMPT = f"""\
You are a function calling AI model. You are provided with function signatures \
within <tools></tools> XML tags. You may call one or more functions to assist \
with the user query. Don't make assumptions about what values to plug into \
functions. For each function call return a json object with function name and \
arguments within <tool_call></tool_call> XML tags as follows:
<tool_call>
{{"name": <function-name>,"arguments": <args-dict>}}
</tool_call>

You are the Arbiter — a strict logic and rules engine for an RPG.

RULES (non-negotiable):
1. You may ONLY call tools. Never narrate. Never improvise.
2. Always call get_entity_info FIRST to verify entities exist and check balances.
3. Call check_location_rules if a location is mentioned in the instruction.
4. If is_safe_zone=True → REJECT the transfer and state why.
5. If is_magic_restricted=True → REJECT energy transfers.
6. Call transfer_energy only after all checks pass.
7. End with a concise factual summary: SUCCESS or REJECTED + amounts.

Here are the available tools:
{_TOOLS_XML}"""

# ─── Tool name → callable map ─────────────────────────────────────────────────
_TOOL_MAP = {tool.name: tool for tool in ARBITER_TOOLS}

# ─── XML tag parser ───────────────────────────────────────────────────────────
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


class ArbiterAgent:
    """
    Strictly constrained tool-calling agent using the native XML prompt format
    expected by Llama-3-Groq-8B-Tool-Use.

    All energy mutations are serialized via _ARBITER_LOCK.
    temperature=0.5, top_p=0.65 per model recommendation.
    """

    MAX_ITERATIONS = 6

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.arbiter_model,
            streaming=False,
            temperature=0.5,
            top_p=0.65,
        )

    async def resolve(self, instruction: str) -> ArbiterResult:
        """
        Run the XML tool-calling loop until the model stops emitting <tool_call>
        tags or MAX_ITERATIONS is reached.
        Acquires _ARBITER_LOCK before any DB mutation.
        """
        async with _ARBITER_LOCK:
            messages: list = [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=instruction),
            ]

            for _ in range(self.MAX_ITERATIONS):
                try:
                    response = await self._llm.ainvoke(messages)
                except Exception as e:
                    return ArbiterResult(
                        success=False, message=f"LLM error: {e}"
                    )

                content: str = (
                    response.content
                    if isinstance(response.content, str)
                    else str(response.content)
                )
                messages.append(AIMessage(content=content))

                # ── Parse tool calls ──────────────────────────────────────────
                tool_calls = _TOOL_CALL_RE.findall(content)
                if not tool_calls:
                    # No more tool calls → final answer
                    success = (
                        "error" not in content.lower()
                        and "reject" not in content.lower()
                    )
                    return ArbiterResult(success=success, message=content)

                # ── Execute each tool call and feed result back ───────────────
                for tc_raw in tool_calls:
                    try:
                        tc = json.loads(tc_raw)
                        tool_name: str = tc.get("name", "")
                        tool_args: dict = tc.get("arguments", {})
                    except json.JSONDecodeError as e:
                        tool_result = f'{{"error": "JSON parse failed: {e}"}}'
                    else:
                        tool = _TOOL_MAP.get(tool_name)
                        if tool:
                            try:
                                raw = await tool.ainvoke(tool_args)
                                tool_result = json.dumps({"result": raw})
                            except Exception as e:
                                tool_result = json.dumps({"error": str(e)})
                        else:
                            tool_result = json.dumps(
                                {"error": f"Unknown tool: {tool_name}"}
                            )

                    messages.append(
                        HumanMessage(
                            content=f"<tool_response>\n{tool_result}\n</tool_response>"
                        )
                    )

            return ArbiterResult(
                success=False,
                message=f"Arbiter reached max iterations ({self.MAX_ITERATIONS}) without resolution.",
            )


# Module-level singleton
arbiter_agent = ArbiterAgent()
