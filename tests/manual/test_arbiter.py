import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.arbiter import ArbiterAgent

async def main():
    agent = ArbiterAgent()
    
    # Try an explicit command!
    instruction = "Please call the move_player tool to move 'SystemTester' to 'Old Well Square', and then call the advance_tutorial_phase tool for 'SystemTester'."
    entity_name = "SystemTester"
    
    print(f"Instruction: {instruction}")
    result = await agent.resolve(instruction, entity_name)
    
    print("Arbiter Result Object:")
    print(f"Success: {result.success}")
    print(f"Message: {result.message}")

if __name__ == "__main__":
    asyncio.run(main())
