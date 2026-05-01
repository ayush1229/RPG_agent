from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.db.models import Location, SideCharacter, TarotShard
from app.db.service import tarot_service


def build_gm_context(session: Session, location_id: Optional[int] = None, sub_location_id: Optional[int] = None) -> str:
    """
    Just-In-Time (JIT) context builder for the Game Master agent.

    Injects ONLY active scene data to avoid token limit exhaustion:
      - Location name, description, and mechanic flags
      - Characters present and their current status
      - Each character's held Tarot cards (name + magic style)
      - Each character's upright/reversed mana (NOT all global lore)

    Args:
        session: Read-only SQLModel session.
        location_id: If None, returns a brief world overview.
        sub_location_id: If set, injects specific sub-location details.
    """
    if location_id is not None:
        return _build_location_context(session, location_id, sub_location_id)
    return _build_world_overview(session)


def _build_location_context(session: Session, location_id: int, sub_location_id: Optional[int] = None) -> str:
    loc = session.get(Location, location_id)
    if not loc:
        return "(location not found)"

    from app.db.models import CitySubLocation
    
    sub_loc = None
    if sub_location_id:
        sub_loc = session.get(CitySubLocation, sub_location_id)
        
    if sub_loc:
        lines: list[str] = [
            f"LOCATION: {sub_loc.name} (Inside {loc.name})",
            f"Description: {sub_loc.description}",
            f"Type: {sub_loc.sub_type.title()} | Safe Zone: {sub_loc.is_safe_zone}",
        ]
    else:
        lines: list[str] = [
            f"LOCATION: {loc.name}",
            f"Description: {loc.description}",
            f"Safe Zone: {loc.is_safe_zone} | Magic Restricted: {loc.is_magic_restricted}",
        ]
        
    lines.extend([
        _build_time_context(session),
        "",
        "CHARACTERS PRESENT:"
    ])

    for char in loc.occupants:
        entity = char.tarot_wallet
        mana_line = ""
        card_line = ""

        if entity:
            # Lazy mana regen before injecting context
            tarot_service._regen_mana(entity)
            mana_line = (
                f"    Mana: ↑{entity.current_upright_mana}/{entity.upright_capacity} "
                f"↓{entity.current_reversed_mana}/{entity.reversed_capacity}"
            )

            cards = tarot_service.get_held_cards(session, entity.id)
            if cards:
                card_parts = []
                for c in cards:
                    card_parts.append(f"{c['card_name']} ({c['arcana_type']}): {c['magic_style']}")
                card_line = "    Cards: " + " | ".join(card_parts)

        lines.append(f"  • {char.name} [{char.position}] — {char.current_status}")
        if mana_line:
            lines.append(mana_line)
        if card_line:
            lines.append(card_line)
            
        # Travel status
        from app.db.models import TravelState
        travel = session.exec(select(TravelState).where(TravelState.entity_id == entity.id, TravelState.is_completed == False)).first()
        if travel:
            lines.append(f"    Travel Status: {travel.status.upper()} (Route: {travel.route_type})")
            if travel.status == "interrupted":
                lines.append(f"    [TUTORIAL CONTROL] MANDATORY SYSTEM INSTRUCTION: {char.name}'s journey is currently INTERRUPTED by an event on the road. The GM MUST force the player to resolve this event (combat, dialogue, flight) before continuing. Once resolved, the GM MUST instruct the Arbiter to 'resume travel' or 'cancel travel'.")

        # Tarot affinity (archetype, not full lore dump)
        if char.persona and char.persona.tarot_affinity:
            lore = char.persona.tarot_affinity
            lines.append(
                f"    Affinity: {lore.name} — {lore.magical_manifestation}"
            )

    if not sub_loc:
        discovered_subs = session.exec(
            select(CitySubLocation)
            .where(CitySubLocation.city_id == location_id, CitySubLocation.is_discovered == True)
        ).all()
        if discovered_subs:
            lines.append("\nDISCOVERED SUB-LOCATIONS IN THIS CITY:")
            for s in discovered_subs:
                lines.append(f"  • {s.name} ({s.sub_type.title()}): {s.description}")

    # World Events
    from app.db.models import NPCWorldEvent
    recent_events = session.exec(
        select(NPCWorldEvent)
        .where(NPCWorldEvent.location_id == location_id, NPCWorldEvent.resolved == False)
        .order_by(NPCWorldEvent.created_at.desc())
        .limit(3)
    ).all()
    
    if recent_events:
        lines.append("\nRECENT WORLD EVENTS (MANDATORY NARRATIVE CONTEXT):")
        for ev in recent_events:
            lines.append(f"  • A {ev.event_type} involving {ev.involved_entities} happened here recently.")

    return "\n".join(lines)


def _build_world_overview(session: Session) -> str:
    """Fallback: brief summary of all locations and their occupants."""
    locations = session.exec(select(Location)).all()
    if not locations:
        return "(no locations seeded yet)"

    parts: list[str] = ["WORLD OVERVIEW:", _build_time_context(session)]
    for loc in locations:
        occupant_names = [c.name for c in loc.occupants] or ["empty"]
        parts.append(
            f"  {loc.name}: {', '.join(occupant_names)}"
            f" [safe={loc.is_safe_zone}, magic_restricted={loc.is_magic_restricted}]"
        )
    return "\n".join(parts)


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
