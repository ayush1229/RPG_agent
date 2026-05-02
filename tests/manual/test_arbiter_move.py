import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.arbiter import ArbiterAgent

async def main():
    agent = ArbiterAgent()
    instruction = "Move player to Old Well Square"
    entity_name = "Player_f0455684"
    
    res = await agent.resolve(instruction, entity_name)
    print("Result:")
    print(res.message)

if __name__ == "__main__":
    asyncio.run(main())
