"""
Inventory service — full item management for the RPG engine.

Supports:
  - Stackable and non-stackable items
  - Equipment slots with stat bonuses (rarity-scaled)
  - Consumable use with effect application
  - Weight and slot limits (MAX_SLOTS=50, MAX_WEIGHT=100)
  - Gold wallet helpers (uses existing Wallet model)
  - Rarity effectiveness multipliers

All functions take an open SQLModel Session and are transactional.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from sqlmodel import Session, select

from app.db.models import InventoryItem, TarotEntity, Wallet

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_SLOTS: int = 50
MAX_WEIGHT: float = 100.0

# Effectiveness multipliers applied to consumable effects and equipment bonuses
RARITY_MULTIPLIER: dict[str, float] = {
    "common":    1.00,
    "uncommon":  1.10,
    "rare":      1.25,
    "epic":      1.50,
    "legendary": 2.00,
}

# item_types that can be placed in equipment slots
EQUIPPABLE_TYPES: frozenset[str] = frozenset({"equipment", "artifact"})


class EquipmentSlot(str, Enum):
    HEAD      = "head"
    CHEST     = "chest"
    LEGS      = "legs"
    WEAPON    = "weapon"
    OFFHAND   = "offhand"
    ACCESSORY = "accessory"


VALID_SLOTS: frozenset[str] = frozenset(s.value for s in EquipmentSlot)


# ─── Wallet helpers ───────────────────────────────────────────────────────────

def _get_or_create_wallet(session: Session, entity_id: int) -> Wallet:
    wallet = session.exec(
        select(Wallet).where(Wallet.owner_entity_id == entity_id)
    ).first()
    if not wallet:
        wallet = Wallet(owner_entity_id=entity_id, balance=0)
        session.add(wallet)
        session.commit()
        session.refresh(wallet)
    return wallet


def get_gold(session: Session, entity_id: int) -> int:
    """Return the entity's current gold balance (0 if no wallet yet)."""
    wallet = session.exec(
        select(Wallet).where(Wallet.owner_entity_id == entity_id)
    ).first()
    return wallet.balance if wallet else 0


def add_gold(session: Session, entity_id: int, amount: int) -> dict:
    """
    Add (positive) or deduct (negative) gold.
    Returns {"success": bool, "balance": int, "change": int}.
    """
    if amount == 0:
        return {"success": False, "reason": "amount_must_be_nonzero"}
    wallet = _get_or_create_wallet(session, entity_id)
    new_balance = wallet.balance + amount
    if new_balance < 0:
        return {
            "success": False,
            "reason": "insufficient_gold",
            "have": wallet.balance,
            "need": abs(amount),
        }
    wallet.balance = new_balance
    session.add(wallet)
    try:
        session.commit()
        return {"success": True, "balance": new_balance, "change": amount}
    except Exception as exc:
        session.rollback()
        return {"success": False, "reason": f"db_error: {exc}"}


# ─── Inventory helpers ────────────────────────────────────────────────────────

def get_inventory(session: Session, entity_id: int) -> list[InventoryItem]:
    """Return all inventory rows owned by entity_id."""
    return list(
        session.exec(
            select(InventoryItem).where(InventoryItem.owner_id == entity_id)
        ).all()
    )


def check_limits(session: Session, entity_id: int) -> dict:
    """Return slot and weight usage for an entity."""
    items = get_inventory(session, entity_id)
    slots_used = len(items)
    weight_used = round(sum((i.weight or 0.0) for i in items), 2)
    return {
        "slots_used":  slots_used,
        "slots_max":   MAX_SLOTS,
        "slots_free":  MAX_SLOTS - slots_used,
        "weight_used": weight_used,
        "weight_max":  MAX_WEIGHT,
        "weight_free": round(MAX_WEIGHT - weight_used, 2),
        "within_limits": slots_used <= MAX_SLOTS and weight_used <= MAX_WEIGHT,
    }


# ─── Core CRUD ────────────────────────────────────────────────────────────────

def add_item(
    session: Session,
    entity_id: int,
    name: str,
    description: str = "",
    quantity: int = 1,
    item_type: str = "misc",
    rarity: str = "common",
    value: int = 0,
    effect_type: Optional[str] = None,
    effect_value: int = 0,
    stackable: bool = True,
    weight: float = 0.0,
    attack_bonus: int = 0,
    defense_bonus: int = 0,
    tradable: bool = True,
    durability: Optional[int] = None,
    max_durability: Optional[int] = None,
    max_stack: int = 99,
    equipped_slot: Optional[str] = None,
) -> dict:
    """
    Add items to an entity's inventory.
    - Stackable items fill existing stacks up to max_stack, then create new rows.
    - Non-stackable items always create a new row per unit.
    - Enforces slot count and weight limits.
    """
    if quantity <= 0:
        return {"success": False, "reason": "quantity_must_be_positive"}

    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    limits = check_limits(session, entity_id)
    added_weight = weight * quantity
    if limits["weight_used"] + added_weight > MAX_WEIGHT:
        return {"success": False, "reason": "weight_limit_exceeded", **limits}

    remaining = quantity
    new_rows = 0

    if stackable:
        # Fill existing stacks first
        existing = session.exec(
            select(InventoryItem).where(
                InventoryItem.owner_id == entity_id,
                InventoryItem.name == name,
            )
        ).all()
        for row in existing:
            if remaining <= 0:
                break
            current_max = row.max_stack or 99
            space = current_max - row.quantity
            if space > 0:
                add = min(space, remaining)
                row.quantity += add
                remaining -= add
                session.add(row)

    # Create new rows for overflow (or all of it if non-stackable)
    while remaining > 0:
        if limits["slots_free"] - new_rows <= 0:
            return {"success": False, "reason": "inventory_full", **limits}
        stack_qty = min(remaining, max_stack) if stackable else 1
        new_item = InventoryItem(
            name=name,
            description=description,
            quantity=stack_qty,
            item_type=item_type,
            rarity=rarity,
            value=value,
            item_effect=effect_type,
            effect_type=effect_type,
            effect_value=effect_value,
            stackable=stackable,
            weight=weight,
            attack_bonus=attack_bonus,
            defense_bonus=defense_bonus,
            tradable=tradable,
            durability=durability,
            max_durability=max_durability,
            max_stack=max_stack,
            equipped_slot=equipped_slot,
            is_equipped=False,
            owner_id=entity_id,
        )
        session.add(new_item)
        remaining -= stack_qty
        new_rows += 1

    try:
        session.commit()
        return {"success": True, "item": name, "quantity_added": quantity}
    except Exception as exc:
        session.rollback()
        return {"success": False, "reason": f"db_error: {exc}"}


def remove_item(
    session: Session,
    entity_id: int,
    item_id: int,
    quantity: int = 1,
) -> dict:
    """Remove quantity from an owned item. Deletes the row when quantity hits 0."""
    if quantity <= 0:
        return {"success": False, "reason": "quantity_must_be_positive"}

    item = session.get(InventoryItem, item_id)
    if not item:
        return {"success": False, "reason": "item_not_found"}
    if item.owner_id != entity_id:
        return {"success": False, "reason": "not_owner"}
    if item.quantity < quantity:
        return {"success": False, "reason": "insufficient_quantity",
                "have": item.quantity, "need": quantity}

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


# ─── Consumable use ───────────────────────────────────────────────────────────

def use_item(session: Session, entity_id: int, item_id: int) -> dict:
    """
    Use one consumable item:
      - Applies effect (heal / mana / buff / damage) scaled by rarity
      - Decrements quantity; deletes row at 0
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
    if item.item_type not in ("consumable", "misc"):
        return {"success": False, "reason": "not_consumable — use equip_item for equipment"}

    mult = RARITY_MULTIPLIER.get(item.rarity or "common", 1.0)
    scaled = int((item.effect_value or 0) * mult)
    effect = item.effect_type or item.item_effect
    result: dict = {}

    if effect == "heal":
        before = entity.current_health
        entity.current_health = min(entity.max_health, entity.current_health + scaled)
        result = {"healed": entity.current_health - before, "hp_now": entity.current_health}
    elif effect == "mana":
        before = entity.current_upright_mana
        entity.current_upright_mana = min(
            entity.max_upright_mana, entity.current_upright_mana + scaled
        )
        result = {"mana_restored": entity.current_upright_mana - before,
                  "mana_now": entity.current_upright_mana}
    elif effect == "buff":
        entity.damage_bonus += scaled
        result = {"damage_bonus_added": scaled}
    elif effect == "damage":
        entity.current_health = max(0, entity.current_health - scaled)
        result = {"damage_taken": scaled}

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
            "effect": effect,
            "rarity": item.rarity,
            "rarity_multiplier": mult,
            **result,
        }
    except Exception as exc:
        session.rollback()
        return {"success": False, "reason": f"db_error: {exc}"}


# ─── Equipment ────────────────────────────────────────────────────────────────

def equip_item(session: Session, entity_id: int, item_id: int) -> dict:
    """
    Equip an item to its designated slot.
    - Unequips the current item in that slot first (keeps it in inventory).
    - Applies attack_bonus and defense_bonus scaled by rarity.
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    item = session.get(InventoryItem, item_id)
    if not item:
        return {"success": False, "reason": "item_not_found"}
    if item.owner_id != entity_id:
        return {"success": False, "reason": "not_owner"}
    if item.item_type not in EQUIPPABLE_TYPES:
        return {"success": False, "reason": f"not_equippable (type={item.item_type})"}
    if item.is_equipped:
        return {"success": False, "reason": "already_equipped"}

    slot = item.equipped_slot
    if not slot:
        return {"success": False, "reason": "item_has_no_slot_defined"}
    if slot not in VALID_SLOTS:
        return {"success": False, "reason": f"invalid_slot: {slot}"}

    # Unequip whatever is already in this slot
    already = session.exec(
        select(InventoryItem).where(
            InventoryItem.owner_id == entity_id,
            InventoryItem.equipped_slot == slot,
            InventoryItem.is_equipped == True,  # noqa: E712
        )
    ).first()
    if already:
        already_mult = RARITY_MULTIPLIER.get(already.rarity or "common", 1.0)
        entity.damage_bonus    = max(0, entity.damage_bonus    - int(already.attack_bonus  * already_mult))
        entity.damage_reduction = max(0, entity.damage_reduction - int(already.defense_bonus * already_mult))
        already.is_equipped = False
        session.add(already)

    mult = RARITY_MULTIPLIER.get(item.rarity or "common", 1.0)
    atk  = int(item.attack_bonus  * mult)
    def_ = int(item.defense_bonus * mult)

    item.is_equipped = True
    entity.damage_bonus     += atk
    entity.damage_reduction += def_
    session.add(item)
    session.add(entity)

    try:
        session.commit()
        return {
            "success": True,
            "item": item.name,
            "slot": slot,
            "attack_bonus_applied": atk,
            "defense_bonus_applied": def_,
        }
    except Exception as exc:
        session.rollback()
        return {"success": False, "reason": f"db_error: {exc}"}


def unequip_item(session: Session, entity_id: int, slot: str) -> dict:
    """Remove the item in `slot`, reverting its stat bonuses."""
    if slot not in VALID_SLOTS:
        return {"success": False, "reason": f"invalid_slot: {slot}. Valid: {sorted(VALID_SLOTS)}"}

    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    equipped = session.exec(
        select(InventoryItem).where(
            InventoryItem.owner_id == entity_id,
            InventoryItem.equipped_slot == slot,
            InventoryItem.is_equipped == True,  # noqa: E712
        )
    ).first()
    if not equipped:
        return {"success": False, "reason": f"nothing_equipped_in_{slot}"}

    mult = RARITY_MULTIPLIER.get(equipped.rarity or "common", 1.0)
    atk  = int(equipped.attack_bonus  * mult)
    def_ = int(equipped.defense_bonus * mult)

    equipped.is_equipped = False
    entity.damage_bonus     = max(0, entity.damage_bonus     - atk)
    entity.damage_reduction = max(0, entity.damage_reduction - def_)
    session.add(equipped)
    session.add(entity)

    try:
        session.commit()
        return {"success": True, "unequipped": equipped.name, "slot": slot,
                "attack_bonus_removed": atk, "defense_bonus_removed": def_}
    except Exception as exc:
        session.rollback()
        return {"success": False, "reason": f"db_error: {exc}"}
