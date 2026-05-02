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

_SYSTEM_PROMPT = """You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:
<tool_call>
{"name": <function-name>,"arguments": <args-dict>}
</tool_call>

Here are the available tools:
<tools> {
    "name": "get_current_weather",
    "description": "Get the current weather in a given location",
    "parameters": {
        "properties": {
            "location": {
                "description": "The city and state, e.g. San Francisco, CA",
                "type": "string"
            },
            "unit": {
                "enum": [
                    "celsius",
                    "fahrenheit"
                ],
                "type": "string"
            }
        },
        "required": [
            "location"
        ],
        "type": "object"
    }
} </tools>"""

async def main():
    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.arbiter_model,
        streaming=False,
        temperature=0.0,
    )
    
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content="What is the weather like in San Francisco?"),
    ]
    response = await llm.ainvoke(messages)
    print("Response:\n", response.content)

if __name__ == "__main__":
    asyncio.run(main())
