from datetime import timedelta
import random
from sqlmodel import Session, select
from typing import Optional

from app.db.models import (
    NPCIntent, NPCWorldEvent, TarotEntity, SideCharacter, Location, TravelState, utcnow
)
from app.db.world_service import travel_entity

def spawn_generic_npc(session: Session, role: str, location_id: int):
    """Generates a generic NPC into the database."""
    names = {
        "merchant": ["Oren the Trader", "Silk Weaver Mila", "Traveling Merchant"],
        "guard": ["City Guard", "Guild Patrol", "Watchman"],
        "bandit": ["Highwayman", "Forest Bandit", "Rogue"],
        "wanderer": ["Lost Traveler", "Pilgrim", "Nomad"]
    }
    
    name = random.choice(names.get(role, ["Stranger"]))
    
    # Create TarotEntity wallet
    entity = TarotEntity(
        entity_name=name,
        level=1,
        max_health=50,
        current_health=50,
        upright_capacity=100,
        reversed_capacity=100,
        current_location_id=location_id
    )
    session.add(entity)
    session.commit()
    session.refresh(entity)
    
    # Create SideCharacter
    side_char = SideCharacter(
        name=name,
        position=role.title(),
        current_status="Idle",
        tarot_entity_id=entity.id,
        location_id=location_id
    )
    session.add(side_char)
    session.commit()
    session.refresh(side_char)
    
    return entity, side_char

def evaluate_intent(session: Session, entity_id: int, role: str, current_location_id: int):
    """Assigns goals to NPCs based on archetype."""
    # Check if they already have an intent
    existing_intent = session.exec(
        select(NPCIntent).where(NPCIntent.entity_id == entity_id)
    ).first()
    
    if existing_intent:
        return
        
    locations = session.exec(select(Location)).all()
    if not locations:
        return
        
    intent_type = "idle"
    target_loc = None
    
    if role == "merchant":
        intent_type = "trade"
        target_loc = random.choice([l for l in locations if l.id != current_location_id])
    elif role == "guard":
        intent_type = "patrol"
        target_loc = random.choice(locations)
    elif role == "bandit":
        intent_type = "hunt"
        # Bandits pick dangerous routes
        dangerous = [l for l in locations if l.danger_level > 1.0]
        if dangerous:
            target_loc = random.choice(dangerous)
        else:
            target_loc = random.choice(locations)
    elif role == "wanderer":
        intent_type = "travel"
        target_loc = random.choice(locations)

    if target_loc:
        intent = NPCIntent(
            entity_id=entity_id,
            intent_type=intent_type,
            target_location_id=target_loc.id,
            expires_at=utcnow() + timedelta(hours=random.randint(1, 4))
        )
        session.add(intent)
        session.commit()

def simulate_npc_behavior(session: Session, delta_seconds: float, player_location_id: Optional[int] = None):
    """Executes intents and moves NPCs."""
    # We only care about NPCs that are SideCharacters
    npcs = session.exec(select(SideCharacter).where(SideCharacter.tarot_entity_id != None)).all()
    
    for npc in npcs:
        if not npc.tarot_entity_id: continue
        
        role = npc.position.lower()
        evaluate_intent(session, npc.tarot_entity_id, role, npc.location_id or player_location_id or 1)
        
        intent = session.exec(select(NPCIntent).where(NPCIntent.entity_id == npc.tarot_entity_id)).first()
        if not intent: continue
        
        # Expire old intents
        if intent.expires_at and utcnow() > intent.expires_at:
            session.delete(intent)
            session.commit()
            continue
            
        # Is the NPC already traveling?
        is_traveling = session.exec(
            select(TravelState).where(TravelState.entity_id == npc.tarot_entity_id, TravelState.is_completed == False)
        ).first()
        
        if not is_traveling and intent.target_location_id and intent.target_location_id != npc.location_id:
            # Get target coordinates
            target_loc = session.get(Location, intent.target_location_id)
            if target_loc:
                # Start travel
                speed = 1.0 if role == "merchant" else 1.2
                route_type = "dangerous" if role == "bandit" else "safe"
                travel_entity(
                    session=session,
                    entity_id=npc.tarot_entity_id,
                    target_x=target_loc.pos_x,
                    target_y=target_loc.pos_y,
                    terrain_type=target_loc.terrain_type,
                    speed=speed,
                    route_type=route_type,
                    target_location_id=target_loc.id
                )
                npc.location_id = None # They are on the road
                session.add(npc)
                session.commit()

def generate_world_events(session: Session, player_location_id: Optional[int]):
    """Checks overlaps in the same location and creates NPCWorldEvent."""
    locations = session.exec(select(Location)).all()
    
    for loc in locations:
        npcs_here = session.exec(
            select(SideCharacter).where(SideCharacter.location_id == loc.id)
        ).all()
        
        if len(npcs_here) < 2: continue
        
        roles = [npc.position.lower() for npc in npcs_here]
        
        if "bandit" in roles and "merchant" in roles:
            # Ambush!
            bandit = next(n for n in npcs_here if n.position.lower() == "bandit")
            merchant = next(n for n in npcs_here if n.position.lower() == "merchant")
            
            # Check if event already exists to avoid spam
            existing = session.exec(
                select(NPCWorldEvent).where(
                    NPCWorldEvent.location_id == loc.id,
                    NPCWorldEvent.resolved == False,
                    NPCWorldEvent.event_type == "ambush"
                )
            ).first()
            
            if not existing:
                event = NPCWorldEvent(
                    event_type="ambush",
                    location_id=loc.id,
                    involved_entities=f"{bandit.name}, {merchant.name}",
                    impact_level=2
                )
                session.add(event)
                
                # Consume intent
                intent = session.exec(select(NPCIntent).where(NPCIntent.entity_id == bandit.tarot_entity_id)).first()
                if intent: session.delete(intent)
                
        elif "guard" in roles and "bandit" in roles:
            # Combat
            guard = next(n for n in npcs_here if n.position.lower() == "guard")
            bandit = next(n for n in npcs_here if n.position.lower() == "bandit")
            
            existing = session.exec(
                select(NPCWorldEvent).where(
                    NPCWorldEvent.location_id == loc.id,
                    NPCWorldEvent.resolved == False,
                    NPCWorldEvent.event_type == "combat"
                )
            ).first()
            
            if not existing:
                event = NPCWorldEvent(
                    event_type="combat",
                    location_id=loc.id,
                    involved_entities=f"{guard.name}, {bandit.name}",
                    impact_level=1
                )
                session.add(event)
                
                intent = session.exec(select(NPCIntent).where(NPCIntent.entity_id == guard.tarot_entity_id)).first()
                if intent: session.delete(intent)
                
    session.commit()

def resolve_world_events(session: Session):
    """Applies systemic consequences of events."""
    events = session.exec(
        select(NPCWorldEvent).where(NPCWorldEvent.resolved == False)
    ).all()
    
    for event in events:
        loc = session.get(Location, event.location_id)
        if not loc: continue
        
        if event.event_type == "ambush":
            # Ambush succeeds naturally over time
            loc.danger_level += 0.2
            event.resolved = True
        elif event.event_type == "combat":
            # Guard defeats bandit naturally
            loc.danger_level = max(0.5, loc.danger_level - 0.3)
            event.resolved = True
            
        session.add(loc)
        session.add(event)
        
    session.commit()
