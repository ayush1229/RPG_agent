import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from __future__ import annotations
import asyncio
import json
import re
from typing import Any
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.contracts import ArbiterResult
from app.tools.arbiter_tools import move_player, advance_tutorial_phase

# ONLY load 2 tools
ARBITER_TOOLS = [move_player, advance_tutorial_phase]
_ARBITER_LOCK = asyncio.Lock()

def _build_tools_xml() -> str:
    tool_defs = []
    for tool in ARBITER_TOOLS:
        schema = tool.args_schema.model_json_schema()
        tool_defs.append(json.dumps({
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }, indent=2))
    # NO square brackets! Just comma separated or newline separated?
    # The example had no brackets.
    return "<tools>\n" + "\n</tools>\n<tools>\n".join(tool_defs) + "\n</tools>"

_TOOLS_XML = _build_tools_xml()

_SYSTEM_PROMPT = f"""You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:
<tool_call>
{{"name": <function-name>,"arguments": <args-dict>}}
</tool_call>

Here are the available tools:
{_TOOLS_XML}"""

class ArbiterAgent:
    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.arbiter_model,
            streaming=False,
            temperature=0.0,
        )

    async def resolve(self, instruction: str, entity_name: str) -> ArbiterResult:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=instruction),
        ]
        response = await self._llm.ainvoke(messages)
        return ArbiterResult(success=True, message=str(response.content))

async def main():
    agent = ArbiterAgent()
    instruction = "Move player 'SystemTester' to 'Old Well Square'."
    print(f"Instruction: {instruction}")
    result = await agent.resolve(instruction, "SystemTester")
    print("Response:\n", result.message)

if __name__ == "__main__":
    asyncio.run(main())
