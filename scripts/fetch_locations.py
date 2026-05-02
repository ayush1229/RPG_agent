import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from sqlmodel import Session, select
from app.db.database import engine
from app.db.models import Location

def main():
    print("Fetching all locations from the database...\n" + "="*50)
    with Session(engine) as session:
        locations = session.exec(select(Location)).all()
        if not locations:
            print("No locations found in the database.")
            return

        for loc in locations:
            print(f"ID: {loc.id} | Name: {loc.name}")
            print(f"Type: {loc.location_type} | Safe Zone: {loc.is_safe_zone} | Magic Restricted: {loc.is_magic_restricted}")
            print(f"Position: ({loc.x}, {loc.y}) | Radius: {loc.radius}")
            print(f"Description: {loc.description}")
            print("-" * 50)

if __name__ == "__main__":
    main()
