from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.db.models import Location, SideCharacter, TarotShard
from app.db.service import tarot_service


def build_gm_context(session: Session, player_id: int, location_id: Optional[int] = None, sub_location_id: Optional[int] = None) -> dict:
    """
    Constructs a structured context dictionary from the database.
    This replaces reliance on conversational memory.
    """
    from app.db.models import TarotEntity, Location, CitySubLocation, SideCharacter, InventoryItem, StatusEffect, Quest, QuestProgress, NPCIntent, TravelState
    from app.db.service import tarot_service

    # Fetch Player
    player = session.get(TarotEntity, player_id)
    if not player:
        return {}

    # Fetch Location
    loc_dict = {}
    loc = session.get(Location, location_id) if location_id else None
    if loc:
        sub_loc = session.get(CitySubLocation, sub_location_id) if sub_location_id else None
        if sub_loc:
            loc_dict = {
                "id": sub_loc.id,
                "name": f"{sub_loc.name} (Inside {loc.name})",
                "type": sub_loc.sub_type,
                "description": sub_loc.description,
                "danger_level": loc.danger_level if not sub_loc.is_safe_zone else 0.0
            }
        else:
            loc_dict = {
                "id": loc.id,
                "name": loc.name,
                "type": loc.location_type,
                "description": loc.description,
                "danger_level": loc.danger_level if not loc.is_safe_zone else 0.0
            }

    # Fetch Nearby NPCs
    nearby_npcs = []
    if loc:
        for char in loc.occupants:
            # Check intent
            intent = session.exec(select(NPCIntent).where(NPCIntent.entity_id == char.tarot_entity_id)).first()
            intent_str = intent.intent_type if intent else "idle"
            
            # Check travel status
            travel = session.exec(select(TravelState).where(TravelState.entity_id == char.tarot_entity_id, TravelState.is_completed == False)).first()
            if travel and travel.status == "interrupted":
                intent_str = f"travel interrupted - [TUTORIAL CONTROL] MANDATORY SYSTEM INSTRUCTION: {char.name}'s journey is currently INTERRUPTED by an event on the road. The GM MUST force the player to resolve this event before continuing."

            # Fetch cards and affinity
            cards_summary = []
            if char.tarot_entity_id:
                cards = tarot_service.get_held_cards(session, char.tarot_entity_id)
                cards_summary = [f"{c['card_name']} ({c['arcana_type']}): {c['magic_style']}" for c in cards] if cards else []
                
            affinity_str = None
            if char.persona and char.persona.tarot_affinity:
                lore = char.persona.tarot_affinity
                affinity_str = f"{lore.name} — {lore.magical_manifestation}"

            nearby_npcs.append({
                "name": char.name,
                "type": char.position,
                "intent": intent_str,
                "status": char.current_status,
                "cards": cards_summary,
                "affinity": affinity_str
            })

    # Fetch Active Quests
    active_quests = []
    quests = session.exec(select(QuestProgress).where(QuestProgress.entity_id == player_id, QuestProgress.is_completed == False)).all()
    for qp in quests:
        q = session.get(Quest, qp.quest_id)
        if q:
            active_quests.append({
                "id": q.id,
                "title": q.name,
                "objective": qp.goal,
                "progress": qp.progress
            })

    # Fetch Inventory
    inventory = []
    items = session.exec(select(InventoryItem).where(InventoryItem.owner_id == player_id)).all()
    for item in items:
        inventory.append({
            "item_name": item.name,
            "quantity": item.quantity
        })
        
    statuses = [s.name for s in session.exec(select(StatusEffect).where(StatusEffect.target_entity_id == player_id)).all()]
    
    tarot_service._regen_mana(player)

    # Compile Context
    
    player_cards = tarot_service.get_held_cards(session, player_id)
    player_cards_summary = [f"{c['card_name']} ({c['arcana_type']}): {c['magic_style']}" for c in player_cards] if player_cards else []
    
    discovered_subs = []
    if location_id and not sub_location_id:
        discovered_subs = [s.name for s in session.exec(
            select(CitySubLocation)
            .where(CitySubLocation.city_id == location_id, CitySubLocation.is_discovered == True)
        ).all()]
        
    time_str = _build_time_context(session)

    context = {
        "time": time_str.strip(),
        "player": {
            "id": player.id,
            "name": player.entity_name,
            "level": player.level,
            "health": player.current_health,
            "mana": player.current_upright_mana + player.current_reversed_mana,
            "statuses": statuses,
            "cards": player_cards_summary
        },
        "location": loc_dict,
        "discovered_sub_locations": discovered_subs,
        "nearby_npcs": nearby_npcs,
        "active_quests": active_quests,
        "recent_events": get_recent_events(session, player_id=player.id, global_only=False),
        "inventory": inventory
    }
    
    return context


def _build_time_context(session: Session) -> str:
    """One-line in-game time block for GM context injection."""
    try:
        from app.db.time_service import check_day_night
        dn = check_day_night(session)
        hour = dn.get("hour", 12)
        period = dn.get("period", "day")
        phase_name = dn.get("phase_name", "midday")
        is_night = dn.get("is_night", False)
        night_flag = " ⚠️ NIGHT — NPCs less safe, outdoor encounters risk" if is_night else ""
        return (
            f"\nTIME: {hour:02d}:00 — {phase_name.replace('_', ' ').title()} "
            f"({'Night' if is_night else 'Day'}){night_flag}"
        )
    except Exception:
        return ""



def get_character_lore_block(character_name: str, session: Session) -> str:
    """
    Fetch a single character's Tarot affinity block for injection into
    the Persona Agent's system prompt.
    Returns empty string if no affinity is set.
    """
    char = session.exec(
        select(SideCharacter).where(SideCharacter.name == character_name)
    ).first()

    if not char or not char.persona or not char.persona.tarot_affinity:
        return ""

    lore = char.persona.tarot_affinity
    return (
        f"\nTAROT AFFINITY — {lore.name}:\n"
        f"Your soul is bound to the archetype of {lore.name}. "
        f"Subtly weave themes of {lore.upright_meaning} (upright) or "
        f"{lore.reversed_meaning} (reversed) into your dialogue and decisions.\n"
        f"Your magical nature manifests as: {lore.magical_manifestation}\n"
        f"Core themes you embody: {lore.core_themes}\n"
        f"Power domains: {lore.power_domains}\n"
        f"Behavioral bias: {lore.behavioral_bias}"
    )


def get_recent_events(session: Session, player_id: Optional[int] = None, global_only: bool = False) -> list[str]:
    """
    Returns the last N important world events.
    If global_only is True, skips player-specific history and only shows NPCWorldEvents/Wars.
    """
    from app.db.models import NPCWorldEvent, CharacterHistory, War, Faction
    events = []

    # 1. Global World Events
    npc_events = session.exec(
        select(NPCWorldEvent).order_by(NPCWorldEvent.created_at.desc()).limit(10)
    ).all()
    
    for e in npc_events:
        status = "Resolved" if e.resolved else "Active"
        events.append(f"[Global] {e.event_type.title()}: {e.involved_entities} ({status})")

    # 2. Wars
    wars = session.exec(
        select(War).order_by(War.start_time.desc()).limit(3)
    ).all()
    for w in wars:
        fa = session.get(Faction, w.faction_a_id)
        fb = session.get(Faction, w.faction_b_id)
        status = "Active" if w.is_active else "Ended"
        events.append(f"[War] {fa.name if fa else 'Unknown'} vs {fb.name if fb else 'Unknown'} ({status})")

    # 3. Player History (if applicable)
    if player_id and not global_only:
        histories = session.exec(
            select(CharacterHistory)
            .where(CharacterHistory.character_id == player_id)
            .order_by(CharacterHistory.timestamp.desc())
            .limit(5)
        ).all()
        for h in histories:
            events.append(f"[Player] {h.event_type}: {h.event_description}")

    # Return top 10 combined (we just sort them roughly by recency if we had a unified timestamp, but string list is fine)
    # The prompt handles them as an unordered list of facts anyway.
    return events[:10]
