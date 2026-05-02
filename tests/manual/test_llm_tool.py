import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from app.config import settings

@tool
def dummy_tool(word: str) -> str:
    """Returns the word capitalized."""
    return word.upper()

async def main():
    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.arbiter_model,
        temperature=0.0
    ).bind_tools([dummy_tool])
    
    print("Testing basic prompt WITH one dummy tool via bind_tools...")
    resp = await llm.ainvoke("Capitalize the word 'hello' for me.")
    print("Response content:", resp.content)
    print("Response tool calls:", resp.tool_calls)

if __name__ == "__main__":
    asyncio.run(main())
