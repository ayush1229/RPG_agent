from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from typing import List, Optional, Tuple

from sqlmodel import Session, col, func, select

from app.db.models import (
    ARCANA_EFFECTS,
    CombatParticipant,
    CombatState,
    GlobalConfig,
    InventoryItem,
    Quest,
    QuestProgress,
    StatusEffect,
    STATUS_EFFECT_CATALOGUE,
    TarotAbility,
    TarotCardLore,
    TarotCardTransaction,
    TarotEntity,
    TarotShard,
    TarotTransaction,
    calculate_xp_reward,
    xp_required,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Conservation Law constants ────────────────────────────────────────────────
_TOTAL_UPRIGHT_KEY = "TOTAL_UPRIGHT_CAPACITY"
_TOTAL_REVERSED_KEY = "TOTAL_REVERSED_CAPACITY"

# Mana regeneration: 1 unit per minute (out-of-combat), capped at capacity.
# Lazy — calculated only on access, never in a background loop.
_MANA_REGEN_RATE: float = 1.0 / 10  # units per second


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

    # ── Health helpers (in-memory, caller must commit) ────────────────────────

    @staticmethod
    def _apply_damage(entity: TarotEntity, amount: int) -> int:
        """
        Reduce entity health by amount, clamped at 0.
        Returns the actual damage dealt.
        """
        amount = max(0, amount)
        actual = min(entity.current_health, amount)
        entity.current_health = max(0, entity.current_health - amount)
        return actual

    @staticmethod
    def _apply_heal(entity: TarotEntity, amount: int) -> int:
        """
        Increase entity health by amount, clamped at dynamic max_health.
        Returns the actual HP restored.
        """
        amount = max(0, amount)
        before = entity.current_health
        entity.current_health = min(entity.max_health, entity.current_health + amount)
        return entity.current_health - before

    # ── Scaling helpers (pure functions, no DB) ─────────────────────────────

    @staticmethod
    def compute_power_multiplier(entity: TarotEntity) -> float:
        """
        Shard-count power multiplier: +5% per energy shard, capped at 1.5x.
        Uses total energy capacity (upright + reversed) as shard count.
        Cap is hit at 10 total energy shards.
        """
        return entity.shard_power_multiplier

    @staticmethod
    def get_dominant_energy(entity: TarotEntity) -> str:
        """
        Returns 'upright' or 'reversed' based on which capacity is larger.
        Upright wins on equal capacity.
        """
        return entity.dominant_energy

    @staticmethod
    def get_arcana_modifiers(session: Session, entity_id: int) -> dict[str, float]:
        """
        Aggregate all arcana-specific modifier bonuses from Major Arcana
        cards held by the entity. Returns a merged dict of bonus keys.
        Multiple cards with the same key ADD together (e.g. two damage_bonus
        cards combine), but each card's own effect applies only once.
        """
        shards = session.exec(
            select(TarotShard)
            .join(TarotCardLore, TarotShard.lore_id == TarotCardLore.id)
            .where(
                TarotShard.owner_id == entity_id,
                TarotCardLore.arcana_type == "Major",
            )
        ).all()

        merged: dict[str, float] = {}
        for shard in shards:
            if shard.lore and shard.lore.name in ARCANA_EFFECTS:
                for key, val in ARCANA_EFFECTS[shard.lore.name].items():
                    merged[key] = merged.get(key, 0.0) + val
        return merged

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
                entity.max_upright_mana,
                entity.current_upright_mana + regen,
            )
            entity.current_reversed_mana = min(
                entity.max_reversed_mana,
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

        # Cap mana if capacity drop lowers the limit below current mana
        from_e.current_upright_mana = min(from_e.current_upright_mana, from_e.max_upright_mana)
        from_e.current_reversed_mana = min(from_e.current_reversed_mana, from_e.max_reversed_mana)

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
        # Also fill mana to maximum limit on genesis
        to_e.current_upright_mana = to_e.max_upright_mana
        to_e.current_reversed_mana = to_e.max_reversed_mana

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
        target_id: int | None = None,
    ) -> dict:
        """
        Attempt to cast a TarotAbility.
        Pipeline:
          1. Validate caster exists and is alive
          2. Validate ability exists
          3. Verify card ownership
          4. Apply lazy mana regen
          5. Check and deduct mana
          6. Compute and apply damage / healing to target
          7. Commit atomically
        Returns structured result dict.
        """
        entity = session.get(TarotEntity, entity_id)
        ability = session.get(TarotAbility, ability_id)

        if not entity:
            return {"success": False, "reason": "entity_not_found"}
        if entity.is_dead:
            return {"success": False, "reason": "entity_dead"}
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

        # ── Resolve target ────────────────────────────────────────────────────
        if target_id is not None and target_id != entity_id:
            target = session.get(TarotEntity, target_id)
            if not target:
                return {"success": False, "reason": "target_not_found"}
        else:
            target = entity  # self-targeting (heals, buffs)

        # ──────────────────────────────────────────────────────────────────────
        # DAMAGE PIPELINE (mandatory order)
        # 1. Base = base_damage + mana_cost * scaling_factor
        # 2. Power multiplier (energy shard count)
        # 3. Arcana modifiers (damage_bonus)
        # 4. Alignment penalty (off-element → ×0.75)
        # 5. Flat attacker bonus / defender reduction
        # 6. Status modifiers (shield, weaken)
        # 7. Final clamp ≥ 0
        # ──────────────────────────────────────────────────────────────────────

        power_mult = self.compute_power_multiplier(entity)
        arcana_mods = self.get_arcana_modifiers(session, entity_id)
        dominant = self.get_dominant_energy(entity)
        if ability.energy_type != dominant:
            alignment_mult = 0.75 + arcana_mods.get("alignment_penalty_reduction", 0.0)
            alignment_mult = min(1.0, alignment_mult)  # cannot exceed full power
        else:
            alignment_mult = 1.0

        actual_damage = 0
        actual_heal = 0

        # Status modifier queries (done once, shared by damage and heal)
        shield = session.exec(
            select(StatusEffect).where(
                StatusEffect.target_entity_id == target.id,
                StatusEffect.name == "shield",
            )
        ).first()
        weaken = session.exec(
            select(StatusEffect).where(
                StatusEffect.target_entity_id == entity.id,
                StatusEffect.name == "weaken",
            )
        ).first()

        if ability.base_damage is not None:
            if target.is_dead:
                return {"success": False, "reason": "target_already_dead"}

            raw = float(ability.base_damage + ability.mana_cost * ability.scaling_factor)
            # Step 2: Power multiplier
            raw *= power_mult
            # Step 3: Arcana damage_bonus
            raw *= (1.0 + arcana_mods.get("damage_bonus", 0.0))
            # Step 4: Alignment penalty
            raw *= alignment_mult
            # Step 5: Flat modifiers
            raw = raw + entity.damage_bonus - target.damage_reduction
            # Step 6: Status effects
            if shield:
                raw *= (1.0 - shield.value / 100)
            if weaken:
                raw *= (1.0 - weaken.value / 100)
            # Step 7: Clamp
            actual_damage = self._apply_damage(target, max(0, int(raw)))

        if ability.base_heal is not None:
            raw_h = float(ability.base_heal + ability.mana_cost * ability.scaling_factor)
            # Step 2: Power multiplier
            raw_h *= power_mult
            # Step 3: Arcana healing_bonus
            raw_h *= (1.0 + arcana_mods.get("healing_bonus", 0.0))
            # Step 4: Alignment penalty (same rule applies to healing)
            raw_h *= alignment_mult
            # Step 7: Clamp
            actual_heal = self._apply_heal(target, max(0, int(raw_h)))

        # ── Status effect from ability ─────────────────────────────────────────
        status_applied: dict | None = None
        if ability.applies_status and ability.status_duration > 0:
            s_result = self.apply_status(
                session,
                target.id,
                name=ability.applies_status,
                value=ability.status_value,
                duration=ability.status_duration,
                stackable=ability.status_stackable,
                source_ability_id=ability.id,
                _commit=False,
            )
            status_applied = s_result

        session.add(entity)
        if target is not entity:
            session.add(target)

        try:
            session.commit()
            return {
                "success": True,
                "ability": ability.name,
                "cost": ability.mana_cost,
                "damage": actual_damage,
                "healing": actual_heal,
                "target_dead": target.is_dead,
                "status_applied": status_applied,
            }
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

    # ── Inventory ──────────────────────────────────────────────────────────────

    def add_item(
        self,
        session: Session,
        entity_id: int,
        name: str,
        description: str = "",
        quantity: int = 1,
        item_effect: str | None = None,
        effect_value: int = 0,
    ) -> dict:
        """
        Add qty of a named item to entity's inventory.
        If the item already exists (by name), increments quantity.
        """
        if quantity <= 0:
            return {"success": False, "reason": "quantity_must_be_positive"}
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}
        if item_effect and item_effect not in ("heal", "mana"):
            return {"success": False, "reason": "invalid_item_effect"}

        existing = session.exec(
            select(InventoryItem).where(
                InventoryItem.owner_id == entity_id,
                InventoryItem.name == name,
            )
        ).first()

        if existing:
            existing.quantity += quantity
            session.add(existing)
        else:
            item = InventoryItem(
                name=name,
                description=description,
                quantity=quantity,
                item_effect=item_effect,
                effect_value=effect_value,
                owner_id=entity_id,
            )
            session.add(item)

        try:
            session.commit()
            return {"success": True, "item": name, "quantity_added": quantity}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def remove_item(
        self,
        session: Session,
        entity_id: int,
        item_id: int,
        quantity: int = 1,
    ) -> dict:
        """
        Remove qty from an item. Deletes the row when quantity reaches 0.
        """
        if quantity <= 0:
            return {"success": False, "reason": "quantity_must_be_positive"}

        item = session.get(InventoryItem, item_id)
        if not item:
            return {"success": False, "reason": "item_not_found"}
        if item.owner_id != entity_id:
            return {"success": False, "reason": "not_owner"}
        if item.quantity < quantity:
            return {
                "success": False,
                "reason": "insufficient_quantity",
                "have": item.quantity,
                "need": quantity,
            }

        item.quantity -= quantity
        if item.quantity == 0:
            session.delete(item)
        else:
            session.add(item)

        try:
            session.commit()
            return {"success": True, "item_id": item_id, "remaining": max(0, item.quantity)}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def use_item(
        self,
        session: Session,
        entity_id: int,
        item_id: int,
    ) -> dict:
        """
        Consume one use of an item, applying its effect.
        Supported effects: 'heal' (restores HP), 'mana' (restores upright mana).
        Deletes the item row when quantity reaches 0.
        """
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        item = session.get(InventoryItem, item_id)
        if not item:
            return {"success": False, "reason": "item_not_found"}
        if item.owner_id != entity_id:
            return {"success": False, "reason": "not_owner"}
        if item.quantity <= 0:
            return {"success": False, "reason": "item_depleted"}

        effect_summary: dict = {}

        if item.item_effect == "heal":
            restored = self._apply_heal(entity, item.effect_value)
            effect_summary = {"heal": restored}
        elif item.item_effect == "mana":
            before = entity.current_upright_mana
            entity.current_upright_mana = min(
                entity.max_upright_mana,
                entity.current_upright_mana + item.effect_value,
            )
            effect_summary = {"mana": entity.current_upright_mana - before}

        item.quantity -= 1
        if item.quantity == 0:
            session.delete(item)
        else:
            session.add(item)

        session.add(entity)

        try:
            session.commit()
            return {
                "success": True,
                "item": item.name,
                "effect": item.item_effect,
                **effect_summary,
            }
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    # ── Status Effects ─────────────────────────────────────────────────────────

    def apply_status(
        self,
        session: Session,
        entity_id: int,
        name: str,
        value: int = 0,
        duration: int = 1,
        stackable: bool = False,
        source_ability_id: int | None = None,
        _commit: bool = True,
    ) -> dict:
        """
        Apply a named status effect to an entity.
        If stackable=False and the same name already exists, refreshes duration.
        Supported names: burn, bleed, stun, slow, shield, weaken.
        Returns structured dict.
        """
        if name not in STATUS_EFFECT_CATALOGUE:
            return {"success": False, "reason": f"unknown_status: {name}"}
        if duration <= 0:
            return {"success": False, "reason": "duration_must_be_positive"}

        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        effect_type = STATUS_EFFECT_CATALOGUE[name]

        if not stackable:
            existing = session.exec(
                select(StatusEffect).where(
                    StatusEffect.target_entity_id == entity_id,
                    StatusEffect.name == name,
                )
            ).first()
            if existing:
                existing.duration = max(existing.duration, duration)
                existing.value = value
                session.add(existing)
                if _commit:
                    try:
                        session.commit()
                    except Exception as exc:
                        session.rollback()
                        return {"success": False, "reason": f"db_error: {exc}"}
                return {"success": True, "action": "refreshed", "status": name, "duration": existing.duration}

        effect = StatusEffect(
            name=name,
            effect_type=effect_type,
            value=max(0, value),
            duration=max(1, duration),
            stackable=stackable,
            source_ability_id=source_ability_id,
            target_entity_id=entity_id,
        )
        session.add(effect)
        if _commit:
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                return {"success": False, "reason": f"db_error: {exc}"}
        return {"success": True, "action": "applied", "status": name, "duration": duration}

    def process_status_effects(self, session: Session, entity_id: int) -> dict:
        """
        Tick all active status effects for an entity (called at start of each turn).
        Applies effect, decrements duration, deletes expired effects.
        Returns a summary of what happened.
        """
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        effects = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == entity_id)
        ).all()

        log: list[dict] = []
        stunned = False

        for effect in effects:
            entry: dict = {"status": effect.name, "type": effect.effect_type}

            if effect.effect_type == "damage_over_time":
                dmg = self._apply_damage(entity, effect.value)
                entry["damage"] = dmg

            elif effect.effect_type == "control":
                if effect.name == "stun":
                    stunned = True
                    entry["stunned"] = True
                elif effect.name == "slow":
                    entry["slow"] = effect.value   # caller uses this

            elif effect.effect_type == "buff":
                # shield is already applied inside damage pipeline; just log
                entry["active_value"] = effect.value

            elif effect.effect_type == "debuff":
                # weaken is applied inside damage pipeline; just log
                entry["active_value"] = effect.value

            # Decrement and remove if expired
            effect.duration -= 1
            if effect.duration <= 0:
                session.delete(effect)
                entry["expired"] = True
            else:
                session.add(effect)
                entry["turns_left"] = effect.duration

            log.append(entry)

        session.add(entity)

        try:
            session.commit()
            return {"success": True, "entity_id": entity_id, "effects": log, "stunned": stunned}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def remove_expired_effects(self, session: Session, entity_id: int) -> dict:
        """Explicitly remove all duration=0 effects (cleanup utility)."""
        effects = session.exec(
            select(StatusEffect).where(
                StatusEffect.target_entity_id == entity_id,
                StatusEffect.duration <= 0,
            )
        ).all()
        count = len(effects)
        for e in effects:
            session.delete(e)
        try:
            session.commit()
            return {"success": True, "removed": count}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    # ── Spatial / Movement ─────────────────────────────────────────────────────

    @staticmethod
    def distance(ax: float, ay: float, bx: float, by: float) -> float:
        """Euclidean distance between two points."""
        return sqrt((ax - bx) ** 2 + (ay - by) ** 2)

    def move_entity(
        self,
        session: Session,
        entity_id: int,
        new_x: float,
        new_y: float,
        location_id: int | None = None,
    ) -> dict:
        """
        Move entity to (new_x, new_y).
        If location_id is provided, enforces that the new position is within
        the location's radius.
        Costs 1 action (tracked externally by combat engine).
        """
        from app.db.models import Location  # local import to avoid circulars

        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        if location_id is not None:
            loc = session.get(Location, location_id)
            if not loc:
                return {"success": False, "reason": "location_not_found"}
            dist = self.distance(new_x, new_y, loc.x, loc.y)
            if dist > loc.radius:
                return {
                    "success": False,
                    "reason": "out_of_bounds",
                    "distance_from_center": dist,
                    "location_radius": loc.radius,
                }

        entity.pos_x = new_x
        entity.pos_y = new_y
        session.add(entity)

        try:
            session.commit()
            return {"success": True, "entity_id": entity_id, "x": new_x, "y": new_y}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def get_entities_in_radius(
        self,
        session: Session,
        cx: float,
        cy: float,
        radius: float,
        exclude_id: int | None = None,
    ) -> list[TarotEntity]:
        """Return all entities whose position falls within the given radius."""
        all_entities = session.exec(select(TarotEntity)).all()
        return [
            e for e in all_entities
            if e.id != exclude_id
            and self.distance(e.pos_x, e.pos_y, cx, cy) <= radius
        ]

    # ── Basic Attack (no ability card required) ────────────────────────────────

    def basic_attack(
        self,
        session: Session,
        attacker_id: int,
        target_id: int,
        damage: int = 5,
    ) -> dict:
        """
        Simple unarmed strike — no card, no mana cost.
        Respects the full damage pipeline (attacker bonuses, defender reductions).
        """
        attacker = session.get(TarotEntity, attacker_id)
        target = session.get(TarotEntity, target_id)

        if not attacker:
            return {"success": False, "reason": "attacker_not_found"}
        if not target:
            return {"success": False, "reason": "target_not_found"}
        if attacker.is_dead:
            return {"success": False, "reason": "attacker_dead"}
        if target.is_dead:
            return {"success": False, "reason": "target_already_dead"}

        # Full damage pipeline for basic attack
        # 1. Base damage
        raw = float(damage)
        # 2. Power multiplier
        raw *= self.compute_power_multiplier(attacker)
        # 3. Arcana damage_bonus
        arcana_mods = self.get_arcana_modifiers(session, attacker_id)
        raw *= (1.0 + arcana_mods.get("damage_bonus", 0.0))
        # (No alignment penalty for basic attacks — no energy type)
        # 4. Flat attacker bonus / defender reduction
        raw = raw + attacker.damage_bonus - target.damage_reduction
        # 5. Status effects
        shield = session.exec(
            select(StatusEffect).where(
                StatusEffect.target_entity_id == target_id,
                StatusEffect.name == "shield",
            )
        ).first()
        if shield:
            raw *= (1.0 - shield.value / 100)
        weaken = session.exec(
            select(StatusEffect).where(
                StatusEffect.target_entity_id == attacker_id,
                StatusEffect.name == "weaken",
            )
        ).first()
        if weaken:
            raw *= (1.0 - weaken.value / 100)
        # 6. Clamp
        raw = max(0, int(raw))

        actual = self._apply_damage(target, raw)
        session.add(target)

        try:
            session.commit()
            return {
                "success": True,
                "damage": actual,
                "power_multiplier": self.compute_power_multiplier(attacker),
                "target_dead": target.is_dead,
            }
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    # ── Combat Engine ──────────────────────────────────────────────────────────

    def init_combat(
        self,
        session: Session,
        participants: list[dict],
    ) -> dict:
        """
        Initialise a new combat encounter.

        participants: list of dicts with keys:
          - entity_id: int
          - initiative: int          (higher acts first)
          - is_player_side: bool

        Returns {"success": True, "combat_id": int, "turn_order": [...]}
        """
        if not participants:
            return {"success": False, "reason": "no_participants"}

        # Validate all entities exist and are alive
        for p in participants:
            e = session.get(TarotEntity, p["entity_id"])
            if not e:
                return {"success": False, "reason": f"entity_not_found: {p['entity_id']}"}
            if e.is_dead:
                return {"success": False, "reason": f"entity_dead: {p['entity_id']}"}

        # Sort by initiative descending to determine first actor
        ordered = sorted(participants, key=lambda p: p.get("initiative", 0), reverse=True)
        first_actor_id = ordered[0]["entity_id"]

        combat = CombatState(
            is_active=True,
            turn_number=1,
            current_actor_id=first_actor_id,
        )
        session.add(combat)
        session.flush()  # get combat.id

        slots = []
        for p in participants:
            slot = CombatParticipant(
                combat_id=combat.id,
                entity_id=p["entity_id"],
                initiative=p.get("initiative", 0),
                is_player_side=p.get("is_player_side", True),
            )
            session.add(slot)
            slots.append(slot)

        try:
            session.commit()
            session.refresh(combat)
            return {
                "success": True,
                "combat_id": combat.id,
                "turn_number": combat.turn_number,
                "current_actor_id": combat.current_actor_id,
                "turn_order": [p["entity_id"] for p in ordered],
            }
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def advance_turn(self, session: Session, combat_id: int) -> dict:
        """
        Advance to the next turn:
        1. Process status effects for the current actor
        2. Determine next actor (round-robin by initiative)
        3. Check victory / defeat conditions
        4. Increment turn number
        Returns structured dict with combat state.
        """
        combat = session.get(CombatState, combat_id)
        if not combat:
            return {"success": False, "reason": "combat_not_found"}
        if not combat.is_active:
            return {"success": False, "reason": "combat_already_ended"}

        # Process status effects for current actor
        status_log: dict = {}
        if combat.current_actor_id:
            status_log = self.process_status_effects(session, combat.current_actor_id)

        # Reload participants (sorted by initiative desc for round-robin)
        slots = session.exec(
            select(CombatParticipant)
            .where(CombatParticipant.combat_id == combat_id)
            .order_by(CombatParticipant.initiative.desc())  # type: ignore[attr-defined]
        ).all()

        # Check end conditions
        alive_player = any(
            s for s in slots
            if s.is_player_side and not (session.get(TarotEntity, s.entity_id) or TarotEntity()).is_dead
        )
        alive_enemy = any(
            s for s in slots
            if not s.is_player_side and not (session.get(TarotEntity, s.entity_id) or TarotEntity()).is_dead
        )

        if not alive_player or not alive_enemy:
            combat.is_active = False
            session.add(combat)
            session.commit()
            return {
                "success": True,
                "combat_ended": True,
                "victor": "players" if alive_player else "enemies",
                "turn_number": combat.turn_number,
            }

        # Advance to next alive actor (skip dead)
        entity_order = [s.entity_id for s in slots]
        current_idx = entity_order.index(combat.current_actor_id) if combat.current_actor_id in entity_order else -1
        next_actor_id = None
        for i in range(1, len(entity_order) + 1):
            candidate_id = entity_order[(current_idx + i) % len(entity_order)]
            candidate = session.get(TarotEntity, candidate_id)
            if candidate and not candidate.is_dead:
                next_actor_id = candidate_id
                break

        combat.current_actor_id = next_actor_id
        combat.turn_number += 1
        session.add(combat)

        try:
            session.commit()
            return {
                "success": True,
                "combat_ended": False,
                "turn_number": combat.turn_number,
                "current_actor_id": combat.current_actor_id,
                "status_log": status_log,
            }
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def end_combat(self, session: Session, combat_id: int) -> dict:
        """Forcefully end a combat (e.g. escape, story event)."""
        combat = session.get(CombatState, combat_id)
        if not combat:
            return {"success": False, "reason": "combat_not_found"}
        combat.is_active = False
        session.add(combat)
        try:
            session.commit()
            return {"success": True, "combat_id": combat_id, "turns_elapsed": combat.turn_number}
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": f"db_error: {exc}"}

    def get_combat_state(self, session: Session, combat_id: int) -> dict:
        """Return a structured snapshot of the current combat."""
        combat = session.get(CombatState, combat_id)
        if not combat:
            return {"success": False, "reason": "combat_not_found"}

        slots = session.exec(
            select(CombatParticipant)
            .where(CombatParticipant.combat_id == combat_id)
            .order_by(CombatParticipant.initiative.desc())  # type: ignore[attr-defined]
        ).all()

        participants_summary = []
        for s in slots:
            e = session.get(TarotEntity, s.entity_id)
            if e:
                participants_summary.append({
                    "entity_id": e.id,
                    "name": e.entity_name,
                    "hp": e.current_health,
                    "max_hp": e.max_health,
                    "is_dead": e.is_dead,
                    "initiative": s.initiative,
                    "is_player_side": s.is_player_side,
                })

        return {
            "success": True,
            "combat_id": combat_id,
            "is_active": combat.is_active,
            "turn_number": combat.turn_number,
            "current_actor_id": combat.current_actor_id,
            "participants": participants_summary,
        }

    # ── NPC Generator ─────────────────────────────────────────────────────────

    async def generate_npc(
        self,
        session: Session,
        role: str,
        location_id: Optional[int],
        power_level: Optional[str] = None,
        optional_card: Optional[str] = None,
    ) -> dict:
        """
        LLM-assisted NPC generation with strict energy conservation.

        Steps:
          1. Resolve location name (for spawn bias).
          2. Pick power tier (Pareto-weighted, location-biased).
          3. Fetch all Major Arcana card names available in DB.
          4. Call NPCGeneratorAgent -> NPCBlueprint.
          5. Validate world energy reserve (ROOT entity).
          6. Deduct energy from ROOT (zero-sum law).
          7. Create TarotEntity + SideCharacter + CharacterPersona + TarotShard.
          8. Commit in a single transaction.

        Returns a dict summarising the created NPC.
        """
        from app.agent.npc_generator import NPCGeneratorAgent, POWER_TIER_RANGES
        from app.db.models import CharacterPersona, Location, SideCharacter

        # ── 1. Resolve location ───────────────────────────────────────────────
        location_name = "Unknown"
        if location_id is not None:
            loc = session.get(Location, location_id)
            if loc:
                location_name = loc.name

        # ── 2. Pick power tier ────────────────────────────────────────────────
        agent = NPCGeneratorAgent()
        tier = agent.pick_power_level(
            requested_tier=power_level,
            location_name=location_name,
        )

        # ── 3. Fetch Major Arcana card names ──────────────────────────────────
        card_names: list[str] = [
            lore.name
            for lore in session.exec(
                select(TarotCardLore).where(TarotCardLore.arcana_type == "Major")
            ).all()
        ]
        if not card_names:
            return {"success": False, "reason": "no_major_arcana_in_db"}

        # ── 4. LLM generation ─────────────────────────────────────────────────
        try:
            blueprint = await agent.generate(
                role=role,
                power_level=tier,
                location_name=location_name,
                card_names=card_names,
                optional_card=optional_card,
            )
        except ValueError as exc:
            return {"success": False, "reason": "llm_validation_error", "detail": str(exc)}
        except Exception as exc:
            return {"success": False, "reason": "llm_error", "detail": str(exc)}

        # ── 5. Validate world reserve (ROOT entity) ───────────────────────────
        world = session.exec(
            select(TarotEntity).where(TarotEntity.entity_name == "ROOT")
        ).first()
        if not world:
            return {"success": False, "reason": "world_entity_not_found"}

        if blueprint.energy_type == "upright":
            if world.upright_capacity < blueprint.energy_amount:
                return {
                    "success": False,
                    "reason": "insufficient_world_upright_energy",
                    "available": world.upright_capacity,
                    "requested": blueprint.energy_amount,
                }
        else:
            if world.reversed_capacity < blueprint.energy_amount:
                return {
                    "success": False,
                    "reason": "insufficient_world_reversed_energy",
                    "available": world.reversed_capacity,
                    "requested": blueprint.energy_amount,
                }

        # ── 6. Deduct energy from ROOT (zero-sum) ─────────────────────────────
        if blueprint.energy_type == "upright":
            world.upright_capacity -= blueprint.energy_amount
            world.current_upright_mana = min(
                world.current_upright_mana, world.upright_capacity
            )
        else:
            world.reversed_capacity -= blueprint.energy_amount
            world.current_reversed_mana = min(
                world.current_reversed_mana, world.reversed_capacity
            )
        session.add(world)

        # ── 7. Create TarotEntity ─────────────────────────────────────────────
        up_cap = blueprint.energy_amount if blueprint.energy_type == "upright" else 0
        rev_cap = blueprint.energy_amount if blueprint.energy_type == "reversed" else 0
        entity = TarotEntity(
            entity_name=blueprint.name,
            upright_capacity=up_cap,
            reversed_capacity=rev_cap,
            current_upright_mana=up_cap,
            current_reversed_mana=rev_cap,
            current_health=100 + (up_cap + rev_cap) * 10,
            is_upright_sovereign=False,
            is_reversed_sovereign=False,
        )
        entity.current_upright_mana = min(entity.current_upright_mana, entity.max_upright_mana)
        entity.current_reversed_mana = min(entity.current_reversed_mana, entity.max_reversed_mana)
        session.add(entity)
        session.flush()  # get entity.id

        # ── 7b. SideCharacter ─────────────────────────────────────────────────
        character = SideCharacter(
            name=blueprint.name,
            position=blueprint.position,
            current_status=blueprint.current_status,
            tarot_entity_id=entity.id,
            location_id=location_id,
        )
        session.add(character)
        session.flush()  # get character.id

        # ── 7c. CharacterPersona ──────────────────────────────────────────────
        lore = session.exec(
            select(TarotCardLore).where(TarotCardLore.name == blueprint.card_affinity)
        ).first()
        persona = CharacterPersona(
            motivation=blueprint.motivation,
            hidden_secret=blueprint.hidden_secret,
            speaking_style=blueprint.personality,
            character_id=character.id,
            tarot_affinity_id=lore.id if lore else None,
        )
        session.add(persona)

        # ── 7d. TarotShard (card ownership) ───────────────────────────────────
        if lore:
            shard = TarotShard(owner_id=entity.id, lore_id=lore.id)
            session.add(shard)

        # ── 8. Commit ─────────────────────────────────────────────────────────
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            return {"success": False, "reason": "db_commit_error", "detail": str(exc)}

        session.refresh(character)
        session.refresh(entity)

        return {
            "success": True,
            "npc": {
                "character_id": character.id,
                "entity_id": entity.id,
                "name": blueprint.name,
                "position": blueprint.position,
                "current_status": blueprint.current_status,
                "role": blueprint.role,
                "card_affinity": blueprint.card_affinity,
                "energy_type": blueprint.energy_type,
                "energy_amount": blueprint.energy_amount,
                "level_estimate": blueprint.level_estimate,
                "power_tier": tier,
                "location_id": location_id,
                "location_name": location_name,
                "max_health": entity.max_health,
                "shard_power_multiplier": entity.shard_power_multiplier,
            },
        }

    # ── LEVEL & XP SYSTEM ─────────────────────────────────────────────

    # Level-up milestone items by tier (every 5 levels)
    _LEVEL_MILESTONE_ITEMS: list[dict] = [
        # levels  1–10 (milestones 5, 10)
        {"name": "Minor Mana Vial",   "description": "Restores 50 mana.",
         "item_type": "consumable", "rarity": "common",
         "effect_type": "mana", "item_effect": "mana", "effect_value": 50, "value": 10},
        {"name": "Healing Salve",     "description": "Restores 75 HP.",
         "item_type": "consumable", "rarity": "common",
         "effect_type": "heal", "item_effect": "heal", "effect_value": 75, "value": 20},
        # levels 11–20 (milestones 15, 20)
        {"name": "Arcane Tonic",      "description": "Restores 150 mana.",
         "item_type": "consumable", "rarity": "rare",
         "effect_type": "mana", "item_effect": "mana", "effect_value": 150, "value": 75},
        {"name": "Silver Flask",      "description": "Restores 200 HP.",
         "item_type": "consumable", "rarity": "rare",
         "effect_type": "heal", "item_effect": "heal", "effect_value": 200, "value": 100},
        # levels 21–40 (milestones 25, 30, 35, 40)
        {"name": "Tarot Shard Chip",  "description": "A fragment resonating with arcane power.",
         "item_type": "artifact", "rarity": "rare",
         "effect_type": None,     "item_effect": None,  "effect_value": 0, "value": 300},
        {"name": "Elixir of Clarity", "description": "Fully restores mana.",
         "item_type": "consumable", "rarity": "epic",
         "effect_type": "mana", "item_effect": "mana", "effect_value": 500, "value": 400},
        {"name": "Crystal Heart",     "description": "Fully restores HP.",
         "item_type": "consumable", "rarity": "epic",
         "effect_type": "heal", "item_effect": "heal", "effect_value": 600, "value": 500},
        {"name": "Arcana Relic",      "description": "A relic resonating with Major Arcana energy.",
         "item_type": "artifact", "rarity": "epic",
         "effect_type": None,     "item_effect": None,  "effect_value": 0, "value": 800},
        # levels 41–100 (milestones 45+)
        {"name": "Sovereign Essence", "description": "Distilled energy from a Sovereign's aura.",
         "item_type": "artifact", "rarity": "legendary",
         "effect_type": None,     "item_effect": None,  "effect_value": 0, "value": 5000},
    ]

    @staticmethod
    def _milestone_item_template(level: int) -> dict:
        """Return the item template for a 5-level milestone reward."""
        tiers = TarotService._LEVEL_MILESTONE_ITEMS
        if level <= 10:   return tiers[0] if level == 5  else tiers[1]
        if level <= 20:   return tiers[2] if level == 15 else tiers[3]
        if level <= 40:   idx = min(4 + (level - 25) // 5, 7); return tiers[idx]
        return tiers[8]   # level 45+ always gets Sovereign Essence

    def add_xp(self, session: Session, entity_id: int, amount: int) -> dict:
        """
        Grant XP to an entity, applying level-ups with rewards as needed.

        Level-up rewards per level:
          - +5 max_health (stored in health_bonus_from_levels)
        Every 5 levels:
          - Grant one milestone InventoryItem

        Returns:
          {
            success, entity_id, xp_added, levels_gained,
            new_level, new_xp, items_granted: [str]
          }
        """
        if amount <= 0:
            return {"success": False, "reason": "xp_must_be_positive"}

        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        entity.current_xp += amount
        levels_gained = 0
        items_granted: list[str] = []

        # Level-up loop
        while entity.level < 100:
            needed = xp_required(entity.level)
            if entity.current_xp < needed:
                break
            entity.current_xp -= needed
            entity.level += 1
            levels_gained += 1

            # Reward: +5 max_health via stored bonus
            entity.health_bonus_from_levels += 5

            # Reward: milestone item every 5 levels
            if entity.level % 5 == 0:
                template = self._milestone_item_template(entity.level)
                item = InventoryItem(
                    owner_id=entity_id,
                    quantity=1,
                    **template,
                )
                session.add(item)
                items_granted.append(template["name"])

        # Clamp XP at max level (no overflow)
        if entity.level >= 100:
            entity.current_xp = 0

        session.add(entity)
        session.commit()
        session.refresh(entity)

        return {
            "success": True,
            "entity_id": entity_id,
            "xp_added": amount,
            "levels_gained": levels_gained,
            "new_level": entity.level,
            "new_xp": entity.current_xp,
            "xp_to_next_level": xp_required(entity.level) if entity.level < 100 else 0,
            "items_granted": items_granted,
        }

    def get_xp_info(self, session: Session, entity_id: int) -> dict:
        """Return current XP / level / progress info for an entity."""
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}
        needed = xp_required(entity.level) if entity.level < 100 else 0
        return {
            "success": True,
            "entity_id": entity_id,
            "level": entity.level,
            "current_xp": entity.current_xp,
            "xp_to_next_level": needed,
            "progress_pct": round(entity.current_xp / needed * 100, 1) if needed else 100.0,
            "max_health": entity.max_health,
        }

    # ── QUEST SYSTEM ───────────────────────────────────────────────────

    def create_quest(
        self,
        session: Session,
        name: str,
        description: str,
        quest_type: str = "side",
        difficulty: str = "easy",
        required_level: int = 1,
        xp_reward: int = 100,
        item_reward_id: Optional[int] = None,
    ) -> dict:
        """
        Create a new Quest definition. Idempotent by name.
        Validates difficulty and quest_type before insertion.
        """
        valid_difficulties = {"easy", "medium", "hard", "elite"}
        valid_types = {"main", "side"}
        if difficulty not in valid_difficulties:
            return {"success": False, "reason": "invalid_difficulty"}
        if quest_type not in valid_types:
            return {"success": False, "reason": "invalid_quest_type"}
        if required_level < 1:
            return {"success": False, "reason": "required_level_must_be_positive"}

        existing = session.exec(select(Quest).where(Quest.name == name)).first()
        if existing:
            return {"success": False, "reason": "quest_already_exists", "quest_id": existing.id}

        quest = Quest(
            name=name, description=description,
            quest_type=quest_type, difficulty=difficulty,
            required_level=required_level,
            xp_reward=xp_reward, item_reward_id=item_reward_id,
        )
        session.add(quest)
        session.commit()
        session.refresh(quest)
        return {"success": True, "quest_id": quest.id, "name": quest.name}

    def assign_quest(
        self,
        session: Session,
        entity_id: int,
        quest_id: int,
        goal: int = 1,
    ) -> dict:
        """
        Assign a quest to an entity, creating a QuestProgress row.
        Enforces level requirement. Prevents duplicate active assignments.
        """
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        quest = session.get(Quest, quest_id)
        if not quest:
            return {"success": False, "reason": "quest_not_found"}

        if entity.level < quest.required_level:
            return {
                "success": False,
                "reason": "level_too_low",
                "entity_level": entity.level,
                "required_level": quest.required_level,
            }

        existing_progress = session.exec(
            select(QuestProgress).where(
                QuestProgress.entity_id == entity_id,
                QuestProgress.quest_id == quest_id,
            )
        ).first()
        if existing_progress:
            return {
                "success": False,
                "reason": "already_assigned",
                "progress_id": existing_progress.id,
                "is_completed": existing_progress.is_completed,
            }

        progress = QuestProgress(
            quest_id=quest_id,
            entity_id=entity_id,
            progress=0,
            goal=max(1, goal),
        )
        session.add(progress)
        session.commit()
        session.refresh(progress)
        return {
            "success": True,
            "progress_id": progress.id,
            "quest_id": quest_id,
            "quest_name": quest.name,
            "goal": progress.goal,
        }

    def advance_quest(
        self,
        session: Session,
        entity_id: int,
        quest_id: int,
        increment: int = 1,
    ) -> dict:
        """
        Advance a quest's progress by `increment` steps.
        Automatically triggers completion when progress >= goal.
        """
        if increment <= 0:
            return {"success": False, "reason": "increment_must_be_positive"}

        progress = session.exec(
            select(QuestProgress).where(
                QuestProgress.entity_id == entity_id,
                QuestProgress.quest_id == quest_id,
            )
        ).first()
        if not progress:
            return {"success": False, "reason": "quest_not_assigned"}
        if progress.is_completed:
            return {"success": False, "reason": "quest_already_completed"}

        progress.progress = min(progress.progress + increment, progress.goal)
        session.add(progress)
        session.commit()

        if progress.progress >= progress.goal:
            return self.complete_quest(session, entity_id, quest_id)

        session.refresh(progress)
        return {
            "success": True,
            "quest_id": quest_id,
            "progress": progress.progress,
            "goal": progress.goal,
            "completed": False,
        }

    def complete_quest(
        self,
        session: Session,
        entity_id: int,
        quest_id: int,
    ) -> dict:
        """
        Complete a quest for an entity:
          1. Mark QuestProgress.is_completed = True
          2. Mark Quest.is_completed = True (for main quests; side quests keep it False)
          3. Grant scaled XP via add_xp()
          4. Grant item reward (copied to entity inventory) if configured

        All DB writes are committed atomically.
        """
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            return {"success": False, "reason": "entity_not_found"}

        quest = session.get(Quest, quest_id)
        if not quest:
            return {"success": False, "reason": "quest_not_found"}

        progress = session.exec(
            select(QuestProgress).where(
                QuestProgress.entity_id == entity_id,
                QuestProgress.quest_id == quest_id,
            )
        ).first()
        if not progress:
            return {"success": False, "reason": "quest_not_assigned"}
        if progress.is_completed:
            return {"success": False, "reason": "quest_already_completed"}

        # 1 & 2. Mark progress + quest flags
        progress.is_completed = True
        progress.progress = progress.goal
        session.add(progress)
        if quest.quest_type == "main":
            quest.is_completed = True
            session.add(quest)
        session.flush()

        # 3. Grant scaled XP
        scaled_xp = calculate_xp_reward(quest.xp_reward, quest.difficulty, entity.level)
        xp_result = self.add_xp(session, entity_id, scaled_xp)

        # 4. Grant item reward (copy template into entity inventory)
        item_granted: Optional[str] = None
        if quest.item_reward_id:
            template = session.get(InventoryItem, quest.item_reward_id)
            if template:
                reward_item = InventoryItem(
                    owner_id=entity_id,
                    name=template.name,
                    description=template.description,
                    item_type=template.item_type,
                    rarity=template.rarity,
                    value=template.value,
                    item_effect=template.item_effect,
                    effect_type=template.effect_type,
                    effect_value=template.effect_value,
                    quantity=1,
                )
                session.add(reward_item)
                session.commit()
                item_granted = template.name

        return {
            "success": True,
            "quest_id": quest_id,
            "quest_name": quest.name,
            "completed": True,
            "xp_granted": scaled_xp,
            "levels_gained": xp_result.get("levels_gained", 0),
            "new_level": xp_result.get("new_level", entity.level),
            "milestone_items": xp_result.get("items_granted", []),
            "item_reward": item_granted,
        }

    def get_quest_progress(
        self,
        session: Session,
        entity_id: int,
        quest_id: Optional[int] = None,
    ) -> dict:
        """Return quest progress for an entity. Optionally filter by quest_id."""
        query = select(QuestProgress).where(QuestProgress.entity_id == entity_id)
        if quest_id is not None:
            query = query.where(QuestProgress.quest_id == quest_id)
        rows = session.exec(query).all()
        result = []
        for row in rows:
            q = session.get(Quest, row.quest_id)
            result.append({
                "quest_id": row.quest_id,
                "quest_name": q.name if q else None,
                "difficulty": q.difficulty if q else None,
                "progress": row.progress,
                "goal": row.goal,
                "is_completed": row.is_completed,
            })
        return {"success": True, "entity_id": entity_id, "quests": result}


# Module-level singleton
tarot_service = TarotService()
