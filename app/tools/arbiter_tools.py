from __future__ import annotations

from langchain_core.tools import tool
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import CharacterHistory, Location, SideCharacter, TarotEntity
from app.db.service import tarot_service

# ─────────────────────────────────────────────────────────────────────────────
# Arbiter Tools — ONLY callable by the ArbiterAgent.
# All functions use their own DB session and commit atomically.
# The GM never imports or calls these directly.
# ─────────────────────────────────────────────────────────────────────────────


@tool
def get_entity_info(entity_name: str) -> str:
    """
    Look up a TarotEntity by name.
    Returns its id, upright_energy, and reversed_energy.
    Call this before any transfer to confirm the entity exists and check balance.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found in the database."
        return (
            f"Entity '{entity.entity_name}': "
            f"id={entity.id}, "
            f"upright={entity.upright_energy}, "
            f"reversed={entity.reversed_energy}"
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
    Transfer energy between two entities.
    Validates balances, inserts a TarotTransaction, and updates both entities atomically.
    Returns a confirmation string or an error message.
    """
    with Session(engine) as session:
        from_e = tarot_service.get_entity_by_name(session, from_entity_name)
        to_e = tarot_service.get_entity_by_name(session, to_entity_name)

        if not from_e:
            return f"ERROR: Source entity '{from_entity_name}' not found."
        if not to_e:
            return f"ERROR: Target entity '{to_entity_name}' not found."

        try:
            tx = tarot_service.transfer_energy(
                session=session,
                from_id=from_e.id,
                to_id=to_e.id,
                upright=upright_amount,
                reversed=reversed_amount,
                reason=reason,
            )
            return (
                f"SUCCESS: Transferred upright={tx.upright_amount}, "
                f"reversed={tx.reversed_amount} "
                f"from '{from_entity_name}' to '{to_entity_name}'. "
                f"Transaction id={tx.id}."
            )
        except (ValueError, RuntimeError) as e:
            return f"ERROR: {e}"


@tool
def check_location_rules(location_name: str) -> str:
    """
    Check whether energy transfers are permitted in a location.
    Returns is_safe_zone and is_magic_restricted flags.
    Use this before approving any transfer in a named location.
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
    Return the last N transactions for an entity (sent + received).
    Useful for detecting recent activity or verifying a prior transfer.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
        txs = tarot_service.get_transaction_history(session, entity.id)
        recent = txs[-limit:]
        if not recent:
            return f"No transactions found for '{entity_name}'."
        lines = []
        for tx in recent:
            lines.append(
                f"  tx#{tx.id} | upright={tx.upright_amount} reversed={tx.reversed_amount} "
                f"| from={tx.from_entity_id} → to={tx.to_entity_id} | reason='{tx.reason}'"
            )
        return "\n".join(lines)


# ─── Convenience list for AgentExecutor ──────────────────────────────────────
ARBITER_TOOLS = [
    get_entity_info,
    transfer_energy,
    check_location_rules,
    get_transaction_log,
]
