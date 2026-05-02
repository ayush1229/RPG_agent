import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.arbiter import ArbiterAgent

async def main():
    agent = ArbiterAgent()
    entity_name = "SystemTester"
    
    test_cases = [
        "Move player to 'Old Well Square'.",
        "Move player to 'Old Well Square' AND advance tutorial phase.",
        "The player bought an Iron Sword for 15 gold from the Blacksmith.",
        "Transfer 10 upright mana to Ayush."
    ]
    
    print("="*60)
    print("TESTING 8B MODEL (FAST ARBITER)")
    print("="*60)
    for i, instruction in enumerate(test_cases):
        print(f"\n--- Test {i+1} ---")
        print(f"Instruction: {instruction}")
        res = await agent._run_tool_loop(agent._llm_fast, instruction, entity_name)
        print(f"Success: {res.success}")
        print(f"Message:\n{res.message}")
        
    print("\n" + "="*60)
    print("TESTING 70B MODEL (COMPLEX ARBITER)")
    print("="*60)
    for i, instruction in enumerate(test_cases):
        print(f"\n--- Test {i+1} ---")
        print(f"Instruction: {instruction}")
        res = await agent._run_tool_loop(agent._llm_complex, instruction, entity_name)
        print(f"Success: {res.success}")
        print(f"Message:\n{res.message}")

if __name__ == "__main__":
    asyncio.run(main())
