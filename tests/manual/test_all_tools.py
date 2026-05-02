import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.arbiter import ArbiterAgent

async def main():
    agent = ArbiterAgent()
    entity_name = "SystemTester"
    
    test_cases = [
        "Move player to Old Well Square",
        "Advance tutorial phase",
        "Create sublocation Marketplace in city Ardent Hollow",
        "Record combat victory against Goblin",
        "Record item Iron Sword delivered to Blacksmith",
        "Record trade of Iron Sword for 15 gold",
        "Transfer 10 upright energy to Ayush",
        "Resume travel",
        "Cancel travel",
        "Mark npc Oren as met",
        "Give 50 gold to the player",
        "Give item Healing Potion to the player",
        "Transfer card The Fool to the player with reason 'quest reward'",
        "Cast spell Fireball on Goblin",
    ]
    
    print("="*60)
    print("TESTING ALL ARBITER TOOLS (70B MODEL)")
    print("="*60)
    
    success_count = 0
    for i, instruction in enumerate(test_cases):
        print(f"\n--- Test {i+1} ---")
        print(f"Instruction: {instruction}")
        try:
            res = await agent.resolve(instruction, entity_name)
            print(f"Success: {res.success}")
            print(f"Message:\n{res.message.strip()}")
            if res.success:
                success_count += 1
        except Exception as e:
            print(f"Test failed with exception: {e}")
            
    print("\n" + "="*60)
    print(f"RESULT: {success_count} / {len(test_cases)} tools successfully parsed and executed.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
