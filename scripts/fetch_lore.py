import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from sqlmodel import Session, select
from app.db.database import engine
from app.db.models import TarotCardLore

def main():
    print("Fetching all Tarot Lore from the database...\n" + "="*80)
    with Session(engine) as session:
        lore_entries = session.exec(select(TarotCardLore)).all()
        if not lore_entries:
            print("No lore found in the database.")
            return

        for lore in lore_entries:
            suit_info = f" | Suit: {lore.suit}" if lore.suit else ""
            print(f"[{lore.arcana_type} Arcana] {lore.name}{suit_info}")
            print(f"  Upright Meaning: {lore.upright_meaning}")
            print(f"  Reversed Meaning: {lore.reversed_meaning}")
            print(f"  Magical Manifestation: {lore.magical_manifestation}")
            print(f"  Personality Archetype: {lore.personality_archetype}")
            print(f"  Core Themes: {lore.core_themes}")
            print(f"  Power Domains: {lore.power_domains}")
            print(f"  Behavioral Bias: {lore.behavioral_bias}")
            print("-" * 80)

if __name__ == "__main__":
    main()
