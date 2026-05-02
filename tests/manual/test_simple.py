import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from app.config import settings

async def main():
    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.arbiter_model,
        temperature=0.0
    )
    
    resp = await llm.ainvoke([
        {"role": "system", "content": 'You have python functions: def get_weather(location). Output json {"tool": "get_weather", "kwargs": {}}.'},
        {"role": "user", "content": "Weather in SF?"}
    ])
    print("Response:", resp.content)

if __name__ == "__main__":
    asyncio.run(main())
