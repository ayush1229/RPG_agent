from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from sqlmodel import Session, col, func, select

from app.db.models import (
    GlobalConfig,
    TarotAbility,
    TarotCardTransaction,
    TarotEntity,
    TarotShard,
    TarotTransaction,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Conservation Law constants ────────────────────────────────────────────────
_TOTAL_UPRIGHT_KEY = "TOTAL_UPRIGHT_CAPACITY"
_TOTAL_REVERSED_KEY = "TOTAL_REVERSED_CAPACITY"

# Mana regeneration: 1 unit per minute (out-of-combat), capped at capacity.
# Lazy — calculated only on access, never in a background loop.
_MANA_REGEN_RATE: float = 1.0  # units per second


class TarotService:
    """
    The ONLY authorised way to mutate energy balances or card ownership.

    Economy rules (non-negotiable):
      - Capacity is ONLY modified via transfer_energy()
      - Mana is ONLY modified via _regen_mana() and cast_spell()
      - Card ownership is ONLY modified via transfer_card()
      - All writes are atomic: commit succeeds or rolls back completely.
      - Structured dicts are returned instead of raising exceptions to agents.
    """

    # ── Mana Regeneration (LAZY — calculated on access) ───────────────────────

    @staticmethod
    def _regen_mana(entity: TarotEntity) -> None:
        """
        Mutate entity mana in-memory based on time elapsed since last update.
        Caller must commit the session after calling this.
        """
        now = utcnow()
        # Ensure both datetimes are offset-aware for comparison
        last = entity.last_mana_update
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        delta_seconds = (now - last).total_seconds()
        regen = int(delta_seconds * _MANA_REGEN_RATE)  # 1 per minute = 0.01667/s

        if regen > 0:
            entity.current_upright_mana = min(
                entity.upright_capacity,
                entity.current_upright_mana + regen,
            )
            entity.current_reversed_mana = min(
                entity.reversed_capacity,
                entity.current_reversed_mana + regen,
            )
            entity.last_mana_update = now

    # ── Sovereignty helpers ────────────────────────────────────────────────────

    @staticmethod
    def is_sovereign_upright(entity: TarotEntity, session: Session) -> bool:
        """True if this entity holds > 50% of total upright capacity."""
        cfg = session.get(GlobalConfig, _TOTAL_UPRIGHT_KEY)
        return bool(cfg and entity.upright_capacity > 0.5 * cfg.value)

    @staticmethod
    def is_sovereign_reversed(entity: TarotEntity, session: Session) -> bool:
        """True if this entity holds > 50% of total reversed capacity."""
        cfg = session.get(GlobalConfig, _TOTAL_REVERSED_KEY)
        return bool(cfg and entity.reversed_capacity > 0.5 * cfg.value)

    # ── Loadout query (DB-level, no Python iteration) ────────────────────────

    @staticmethod
    def count_arcana(session: Session, entity_id: int) -> Tuple[int, int]:
        """
        Returns (major_count, minor_count) for the entity's held_cards.
        Uses SQL-level aggregation instead of Python loops.
        """
        from app.db.models import TarotCardLore  # avoid circular at top

        majors = session.exec(
            select(func.count(TarotShard.id))
            .join(TarotCardLore, TarotShard.lore_id == TarotCardLore.id)
            .where(TarotShard.owner_id == entity_id)
            .where(TarotCardLore.arcana_type == "Major")
        ).one()

        minors = session.exec(
            select(func.count(TarotShard.id))
            .join(TarotCardLore, TarotShard.lore_id == TarotCardLore.id)
            .where(TarotShard.owner_id == entity_id)
            .where(TarotCardLore.arcana_type == "Minor")
        ).one()

        return (majors or 0, minors or 0)

    # ── Capacity transfer ──────────────────────────────────────────────────────

    def transfer_energy(
        self,
        session: Session,
        from_id: int,
        to_id: int,
        upright: int = 0,
        reversed: int = 0,
        reason: str = "",
    ) -> dict:
        """
        Atomically transfer capacity (permanent/sovereignty energy) between entities.
        Returns structured dict: {"success": bool, "message": str, "tx_id": int|None}
        """
        if upright < 0 or reversed < 0:
            return {"success": False, "message": "Amounts must be non-negative.", "tx_id": None}
        if upright == 0 and reversed == 0:
            return {"success": False, "message": "At least one amount must be > 0.", "tx_id": None}

        from_e = session.get(TarotEntity, from_id)
        to_e = session.get(TarotEntity, to_id)

        if not from_e:
            return {"success": False, "message": f"Entity id={from_id} not found.", "tx_id": None}
        if not to_e:
            return {"success": False, "message": f"Entity id={to_id} not found.", "tx_id": None}

        if upright > from_e.upright_capacity:
            return {
                "success": False,
                "message": (
                    f"Insufficient upright capacity: need {upright}, "
                    f"have {from_e.upright_capacity}."
                ),
                "tx_id": None,
            }
        if reversed > from_e.reversed_capacity:
            return {
                "success": False,
                "message": (
                    f"Insufficient reversed capacity: need {reversed}, "
                    f"have {from_e.reversed_capacity}."
                ),
                "tx_id": None,
            }

        tx = TarotTransaction(
            from_entity_id=from_id,
            to_entity_id=to_id,
            upright_amount=upright,
            reversed_amount=reversed,
            reason=reason,
        )
        from_e.upright_capacity -= upright
        from_e.reversed_capacity -= reversed
        to_e.upright_capacity += upright
        to_e.reversed_capacity += reversed

        session.add(tx)
        session.add(from_e)
        session.add(to_e)

        try:
            session.commit()
            session.refresh(tx)
            return {
                "success": True,
                "message": (
                    f"Transferred upright={upright}, reversed={reversed} "
                    f"from entity {from_id} to {to_id}."
                ),
                "tx_id": tx.id,
            }
        except Exception as exc:
            session.rollback()
            return {"success": False, "message": f"DB commit failed: {exc}", "tx_id": None}

    # ── Genesis mint ───────────────────────────────────────────────────────────

    def mint_capacity(
        self,
        session: Session,
        to_id: int,
        upright: int = 0,
        reversed: int = 0,
        reason: str = "genesis",
    ) -> dict:
        """Create capacity from nothing (genesis only). Breaks conservation if called post-genesis."""
        if upright == 0 and reversed == 0:
            return {"success": False, "message": "Must mint at least some capacity."}

        to_e = session.get(TarotEntity, to_id)
        if not to_e:
            return {"success": False, "message": f"Entity id={to_id} not found."}

        tx = TarotTransaction(
            from_entity_id=None,
            to_entity_id=to_id,
            upright_amount=upright,
            reversed_amount=reversed,
            reason=reason,
        )
        to_e.upright_capacity += upright
        to_e.reversed_capacity += reversed
        # Also fill mana to capacity on genesis
        to_e.current_upright_mana = to_e.upright_capacity
        to_e.current_reversed_mana = to_e.reversed_capacity

        session.add(tx)
        session.add(to_e)

        try:
            session.commit()
            return {"success": True, "message": f"Minted upright={upright}, reversed={reversed}."}
        except Exception as exc:
            session.rollback()
            return {"success": False, "message": f"DB commit failed: {exc}"}

    # ── Card transfer (with loadout limits + ledger) ───────────────────────────

    def transfer_card(
        self,
        session: Session,
        from_id: int,
        to_id: int,
        shard_id: int,
        reason: str = "transfer",
    ) -> dict:
        """
        Transfer ownership of a TarotShard.
        Enforces loadout: max 1 Major Arcana, max 2 Minor Arcana per entity.
        Writes a TarotCardTransaction ledger entry.
        """
        shard = session.get(TarotShard, shard_id)
        if not shard:
            return {"success": False, "reason": "shard_not_found"}
        if shard.owner_id != from_id:
            return {"success": False, "reason": "invalid_ownership"}

        # Load lore to check arcana type
        from app.db.models import TarotCardLore
        lore = session.get(TarotCardLore, shard.lore_id)
        if not lore:
            return {"success": False, "reason": "lore_not_found"}

        majors, minors = self.count_arcana(session, to_id)

        if lore.arcana_type == "Major" and majors >= 1:
            return {"success": False, "reason": "major_limit"}
        if lore.arcana_type == "Minor" and minors >= 2:
            return {"success": False, "reason": "minor_limit"}

        shard.owner_id = to_id
        card_tx = TarotCardTransaction(
            shard_id=shard_id,
            from_entity_id=from_id,
            to_entity_id=to_id,
            reason=reason,
        )

        session.add(shard)
        session.add(card_tx)

        try:
            session.commit()
            return {"success": True, "card": lore.name, "reason": reason}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    # ── Cast spell (mana deduction) ────────────────────────────────────────────

    def cast_spell(
        self,
        session: Session,
        entity_id: int,
        ability_id: int,
    ) -> dict:
        """
        Attempt to cast a TarotAbility. Applies lazy mana regen first,
        then deducts cost. Returns structured result.
        """
        entity = session.get(TarotEntity, entity_id)
        ability = session.get(TarotAbility, ability_id)

        if not entity:
            return {"success": False, "reason": "entity_not_found"}
        if not ability:
            return {"success": False, "reason": "ability_not_found"}

        # Verify the entity holds the card granting this ability
        card_held = session.exec(
            select(TarotShard).where(
                TarotShard.owner_id == entity_id,
                TarotShard.lore_id == ability.card_id,
            )
        ).first()
        if not card_held:
            return {"success": False, "reason": "card_not_held"}

        # Lazy regen before checking cost
        self._regen_mana(entity)

        if ability.energy_type == "upright":
            if entity.current_upright_mana < ability.mana_cost:
                return {
                    "success": False,
                    "reason": "insufficient_mana",
                    "have": entity.current_upright_mana,
                    "need": ability.mana_cost,
                }
            entity.current_upright_mana -= ability.mana_cost
        elif ability.energy_type == "reversed":
            if entity.current_reversed_mana < ability.mana_cost:
                return {
                    "success": False,
                    "reason": "insufficient_mana",
                    "have": entity.current_reversed_mana,
                    "need": ability.mana_cost,
                }
            entity.current_reversed_mana -= ability.mana_cost
        else:
            return {"success": False, "reason": f"unknown_energy_type: {ability.energy_type}"}

        session.add(entity)

        try:
            session.commit()
            return {"success": True, "ability": ability.name, "cost": ability.mana_cost}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    # ── Read helpers ───────────────────────────────────────────────────────────

    def get_entity_by_name(self, session: Session, name: str) -> TarotEntity | None:
        return session.exec(
            select(TarotEntity).where(TarotEntity.entity_name == name)
        ).first()

    def get_transaction_history(
        self, session: Session, entity_id: int
    ) -> list[TarotTransaction]:
        sent = session.exec(
            select(TarotTransaction).where(
                TarotTransaction.from_entity_id == entity_id
            )
        ).all()
        received = session.exec(
            select(TarotTransaction).where(
                TarotTransaction.to_entity_id == entity_id
            )
        ).all()
        # Deduplicate by id (SQLModel objects are not hashable)
        seen: set[int] = set()
        combined = []
        for tx in sent + received:
            if tx.id not in seen:
                seen.add(tx.id)
                combined.append(tx)
        return sorted(combined, key=lambda t: t.timestamp)

    def get_held_cards(self, session: Session, entity_id: int) -> list[dict]:
        """Return a list of held card summaries for context injection."""
        shards = session.exec(
            select(TarotShard).where(TarotShard.owner_id == entity_id)
        ).all()
        results = []
        for s in shards:
            if s.lore:
                results.append({
                    "shard_id": s.id,
                    "card_name": s.lore.name,
                    "arcana_type": s.lore.arcana_type,
                    "magic_style": s.lore.magical_manifestation,
                })
        return results


# Module-level singleton
tarot_service = TarotService()
