from __future__ import annotations

from langchain_core.tools import tool
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import (
    Location,
    TarotAbility,
    TarotCardLore,
    TarotEntity,
    TarotShard,
)
from app.db.service import tarot_service

# ─────────────────────────────────────────────────────────────────────────────
# Arbiter Tools — ONLY callable by the ArbiterAgent.
# All functions open their own session and return structured strings.
# The GM NEVER imports or calls these directly.
# ─────────────────────────────────────────────────────────────────────────────


@tool
def get_entity_info(entity_name: str) -> str:
    """
    Look up a TarotEntity by name.
    Returns its id, upright_capacity, reversed_capacity, and current mana values.
    Call this first to confirm the entity exists and check its balances.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
        cards = tarot_service.get_held_cards(session, entity.id)
        card_names = ", ".join(c["card_name"] for c in cards) or "none"
        return (
            f"Entity '{entity.entity_name}': id={entity.id} | "
            f"upright_capacity={entity.upright_capacity}, "
            f"reversed_capacity={entity.reversed_capacity} | "
            f"upright_mana={entity.current_upright_mana}, "
            f"reversed_mana={entity.current_reversed_mana} | "
            f"held_cards=[{card_names}]"
        )


@tool
def transfer_energy(
    from_entity_name: str,
    to_entity_name: str,
    upright_amount: int,
    reversed_amount: int,
    reason: str,
) -> str:
    """
    Transfer permanent capacity between two entities.
    Capacity is zero-sum (sovereignty resource). Validates balances atomically.
    Returns a confirmation string or an error message.
    """
    with Session(engine) as session:
        from_e = tarot_service.get_entity_by_name(session, from_entity_name)
        to_e = tarot_service.get_entity_by_name(session, to_entity_name)

        if not from_e:
            return f"ERROR: Source entity '{from_entity_name}' not found."
        if not to_e:
            return f"ERROR: Target entity '{to_entity_name}' not found."

        result = tarot_service.transfer_energy(
            session=session,
            from_id=from_e.id,
            to_id=to_e.id,
            upright=upright_amount,
            reversed=reversed_amount,
            reason=reason,
        )

        if result["success"]:
            return (
                f"SUCCESS: {result['message']} Transaction id={result['tx_id']}."
            )
        return f"REJECTED: {result['message']}"


@tool
def transfer_card(
    from_entity_name: str,
    to_entity_name: str,
    shard_id: int,
    reason: str,
) -> str:
    """
    Transfer ownership of a Tarot card shard between entities.
    Enforces loadout limits: max 1 Major Arcana, max 2 Minor Arcana.
    Writes a TarotCardTransaction ledger entry.
    """
    with Session(engine) as session:
        from_e = tarot_service.get_entity_by_name(session, from_entity_name)
        to_e = tarot_service.get_entity_by_name(session, to_entity_name)

        if not from_e:
            return f"ERROR: Source entity '{from_entity_name}' not found."
        if not to_e:
            return f"ERROR: Target entity '{to_entity_name}' not found."

        result = tarot_service.transfer_card(
            session=session,
            from_id=from_e.id,
            to_id=to_e.id,
            shard_id=shard_id,
            reason=reason,
        )

        if result["success"]:
            return f"SUCCESS: Card '{result['card']}' transferred. Reason: {reason}."
        return f"REJECTED: {result['reason']}"


@tool
def cast_spell(entity_name: str, ability_id: int) -> str:
    """
    Cast a TarotAbility for an entity. Applies lazy mana regen first,
    then deducts mana cost. Entity must hold the card granting this ability.
    Returns success or detailed failure reason.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        result = tarot_service.cast_spell(
            session=session,
            entity_id=entity.id,
            ability_id=ability_id,
        )

        if result["success"]:
            return (
                f"SUCCESS: '{entity_name}' cast '{result['ability']}' "
                f"(cost: {result['cost']} mana)."
            )
        return f"REJECTED: {result['reason']}"


@tool
def check_location_rules(location_name: str) -> str:
    """
    Check whether energy transfers or magic are permitted at a location.
    Returns is_safe_zone and is_magic_restricted flags.
    Always call this before approving a transfer in a named location.
    """
    with Session(engine) as session:
        loc = session.exec(
            select(Location).where(Location.name == location_name)
        ).first()
        if not loc:
            return f"Location '{location_name}' not found. Assuming no restrictions."
        return (
            f"Location '{loc.name}': "
            f"is_safe_zone={loc.is_safe_zone}, "
            f"is_magic_restricted={loc.is_magic_restricted}"
        )


@tool
def get_transaction_log(entity_name: str, limit: int = 5) -> str:
    """
    Return the last N capacity transactions for an entity (sent + received).
    Useful for verifying prior transfers or detecting recent activity.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
        txs = tarot_service.get_transaction_history(session, entity.id)
        recent = txs[-limit:]
        if not recent:
            return f"No capacity transactions found for '{entity_name}'."
        lines = [
            f"  tx#{tx.id} | up={tx.upright_amount} rev={tx.reversed_amount} "
            f"| from={tx.from_entity_id} → to={tx.to_entity_id} | '{tx.reason}'"
            for tx in recent
        ]
        return "\n".join(lines)


@tool
def get_card_abilities(card_name: str) -> str:
    """
    List all abilities unlocked by a specific Tarot card.
    Returns ability ids, names, mana costs, and energy types.
    """
    with Session(engine) as session:
        lore = session.exec(
            select(TarotCardLore).where(TarotCardLore.name == card_name)
        ).first()
        if not lore:
            return f"ERROR: Card '{card_name}' not found in TarotCardLore."
        if not lore.abilities:
            return f"Card '{card_name}' has no abilities defined yet."
        lines = [
            f"  ability#{a.id}: '{a.name}' | cost={a.mana_cost} {a.energy_type} mana"
            for a in lore.abilities
        ]
        return f"Abilities for '{card_name}':\n" + "\n".join(lines)


# ─── Tool registry ────────────────────────────────────────────────────────────
ARBITER_TOOLS = [
    get_entity_info,
    transfer_energy,
    transfer_card,
    cast_spell,
    check_location_rules,
    get_transaction_log,
    get_card_abilities,
]
