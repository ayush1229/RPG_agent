import asyncio
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.game_master import game_master
from app.schemas import ChatMessage, Role

async def simulate_gm_analyze():
    print("Simulating GM analyze step...")
    history = [
        ChatMessage(role=Role.ASSISTANT, content="You wake on a narrow straw mattress... What will you do first?"),
    ]
    message = "step outside"
    
    decision = await game_master.analyze(
        message=message,
        history=history,
        player_id=1,
        location_id=1,
        sub_location_id=1,
    )
    
    print("\n--- GM Decision ---")
    print(f"Needs Arbiter: {decision.needs_arbiter}")
    print(f"Arbiter Instruction: {decision.arbiter_instruction}")
    print(f"Needs Persona: {decision.needs_persona}")
    print(f"NPC Name: {decision.npc_name}")
    print(f"Narrative Intent: {decision.narrative_intent}")

if __name__ == "__main__":
    asyncio.run(simulate_gm_analyze())
