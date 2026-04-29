from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.db.models import Location, SideCharacter


def build_gm_context(session: Session, location_id: Optional[int] = None) -> str:
    """
    Just-In-Time (JIT) context builder for the Game Master agent.

    Dynamically assembles a context string containing:
      - Location name, description, and mechanic flags
      - Characters currently in the location
      - Each character's Tarot affinity (card name, magic style, upright/reversed meaning)

    This is injected into the GM's analysis and narrative prompts without
    hitting the token limit by only pulling lore for *active scene* characters.

    Args:
        session: Read-only SQLModel session.
        location_id: If None, returns a brief world overview (all locations).

    Returns:
        A formatted string ready to embed in an LLM system prompt.
    """
    if location_id is not None:
        return _build_location_context(session, location_id)
    return _build_world_overview(session)


def _build_location_context(session: Session, location_id: int) -> str:
    loc = session.get(Location, location_id)
    if not loc:
        return "(location not found)"

    lines: list[str] = [
        f"LOCATION: {loc.name}",
        f"Description: {loc.description}",
        f"Safe Zone: {loc.is_safe_zone} | Magic Restricted: {loc.is_magic_restricted}",
    ]

    lore_lines: list[str] = []
    for char in loc.occupants:
        char_line = f"\n  Character: {char.name} ({char.position}) — {char.current_status}"
        lines.append(char_line)

        if char.persona and char.persona.tarot_affinity:
            lore = char.persona.tarot_affinity
            lore_lines.append(
                f"[{char.name}'s Affinity: {lore.name}]\n"
                f"  Magic Style: {lore.magical_manifestation}\n"
                f"  Upright: {lore.upright_meaning}\n"
                f"  Reversed: {lore.reversed_meaning}\n"
                f"  Archetype: {lore.personality_archetype}"
            )

    if lore_lines:
        lines.append("\nACTIVE LORE THEMES:")
        lines.extend(lore_lines)

    return "\n".join(lines)


def _build_world_overview(session: Session) -> str:
    """Fallback: brief summary of all locations and their occupants."""
    locations = session.exec(select(Location)).all()
    if not locations:
        return "(no locations seeded yet)"

    parts: list[str] = ["WORLD OVERVIEW:"]
    for loc in locations:
        occupant_names = [c.name for c in loc.occupants] or ["empty"]
        parts.append(
            f"  {loc.name}: {', '.join(occupant_names)}"
            f" [safe={loc.is_safe_zone}, magic_restricted={loc.is_magic_restricted}]"
        )
    return "\n".join(parts)


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
        f"Your magical nature manifests as: {lore.magical_manifestation}"
    )
