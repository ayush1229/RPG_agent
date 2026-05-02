import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.arbiter import ArbiterAgent

async def main():
    agent = ArbiterAgent()
    instruction = "Move player to 'Ardent Hollow'."
    
    # Test with a UUID
    uuid_name = "f0455684-7622-44e9-95da-5f73d660b69f"
    print(f"Testing with UUID entity: {uuid_name}")
    res1 = await agent.resolve(instruction, uuid_name)
    print("UUID Result:", res1.message)
    
    # Test with a normal name
    normal_name = "Ayush"
    print(f"\nTesting with normal entity: {normal_name}")
    res2 = await agent.resolve(instruction, normal_name)
    print("Normal Result:", res2.message)

if __name__ == "__main__":
    asyncio.run(main())
