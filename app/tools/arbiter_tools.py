from __future__ import annotations

from langchain_core.tools import tool
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import (
    Location,
    TarotCardLore,
    TarotEntity,
    UserSession,
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


# ─────────────────────────────────────────────────────────────────────────────
# Game Event Tools — bridge GM narrative → DB world state
#
# The GM narrates events but cannot update the DB directly.
# These tools let the Arbiter record what actually happened in the world
# These tools let the Arbiter record what actually happened in the world
# and the DB stays in sync with the story — during AND after the tutorial.
# ─────────────────────────────────────────────────────────────────────────────

@tool
def create_location_in_city(city_name: str, name: str, description: str, sub_type: str) -> str:
    """
    Creates a new sub-location (inn, shop, square, hidden, etc.) inside a city.
    Only use this when the player actively searches for a place or uncovers a hidden area.
    """
    from app.db.location_service import create_city_sublocation
    with Session(engine) as session:
        city = session.exec(select(Location).where(Location.name == city_name)).first()
        if not city:
            return f"ERROR: City '{city_name}' not found."
            
        result = create_city_sublocation(session, city.id, name, description, sub_type)
        if result["success"]:
            import chainlit as cl
            try:
                cl.run_sync(cl.Message(content=f"📍 **Discovered Location:** {name} ({sub_type.title()})", author="🎮 System").send())
            except:
                pass
            return f"SUCCESS: Created and discovered sub-location '{name}' in '{city_name}'."
        return f"FAILED: {result['reason']}"



@tool
def move_player(entity_name: str, location_name: str) -> str:
    """
    Move the player entity to a named location and update the DB.
    Updates UserSession.last_location_id so the player's position persists.
    Also fires tutorial phase triggers (e.g. entering Old Well Square → phase 2).
    Call this whenever the GM narrates that the player travels to or arrives at a place.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        # Try to find a main location
        loc = session.exec(
            select(Location).where(Location.name == location_name)
        ).first()
        
        sub_loc = None
        if not loc:
            # Try to find a sub-location
            from app.db.models import CitySubLocation
            sub_loc = session.exec(
                select(CitySubLocation).where(CitySubLocation.name == location_name)
            ).first()
            if sub_loc:
                loc = session.get(Location, sub_loc.city_id)
                
        if not loc:
            return f"ERROR: Location '{location_name}' not found in DB."

        user_session = session.exec(
            select(UserSession).where(UserSession.entity_id == entity.id)
        ).first()
        if not user_session:
            return f"ERROR: No UserSession found for entity '{entity_name}'."

        user_session.last_location_id = loc.id
        entity.current_location_id = loc.id
        entity.sub_location_id = sub_loc.id if sub_loc else None
        
        session.add(user_session)
        session.add(entity)
        session.commit()

        return f"SUCCESS: '{entity_name}' moved to '{location_name}'."


@tool
def record_combat_victory(entity_name: str, enemy_name: str) -> str:
    """
    Record that the player won a combat encounter and award XP.
    Call this immediately after the GM narrates a combat victory.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        XP_REWARD = 25
        entity.current_xp = (entity.current_xp or 0) + XP_REWARD
        session.add(entity)
        session.commit()

        return (
            f"SUCCESS: Combat victory recorded. '{entity_name}' defeated '{enemy_name}' "
            f"and earned {XP_REWARD} XP."
        )


@tool
def record_item_delivered(entity_name: str, item_description: str) -> str:
    """
    Record that the player delivered or handed over an item or quest object.
    Call this when the GM narrates the player returning an item to an NPC.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        return f"SUCCESS: Item delivery recorded ('{item_description}')."


@tool
def record_trade(entity_name: str, trade_summary: str) -> str:
    """
    Record that the player completed a buy or sell transaction.
    Call this after the GM narrates any successful purchase or sale.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        return f"SUCCESS: Trade recorded ('{trade_summary}')."


# ─── Game-world Item Tools ─────────────────────────────────────────────────────

@tool
def give_item(
    entity_name: str,
    item_name: str,
    item_type: str,
    quantity: int,
    description: str,
    rarity: str = "common",
    value: int = 0,
    effect_type: str = "",
    effect_value: int = 0,
    weight: float = 0.0,
    attack_bonus: int = 0,
    defense_bonus: int = 0,
    equipped_slot: str = "",
) -> str:
    """
    Award an item to the player's inventory.

    item_type   : "consumable" | "equipment" | "material" | "quest" | "artifact" | "misc"
    rarity      : "common" | "uncommon" | "rare" | "epic" | "legendary"
    effect_type : "heal" | "mana" | "buff" | "damage"  (leave blank for equipment/quest items)
    equipped_slot: "head" | "chest" | "legs" | "weapon" | "offhand" | "accessory"
                  (required for equipment, blank for consumables/misc)

    Call this whenever the GM narrates the player receiving an item as loot, a reward, or a gift.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        from app.db.inventory_service import add_item
        result = add_item(
            session,
            entity.id,
            name=item_name,
            description=description,
            quantity=quantity,
            item_type=item_type,
            rarity=rarity,
            value=value,
            effect_type=effect_type or None,
            effect_value=effect_value,
            weight=weight,
            attack_bonus=attack_bonus,
            defense_bonus=defense_bonus,
            equipped_slot=equipped_slot or None,
        )

        if result["success"]:
            # Send UI System Message
            try:
                import chainlit as cl
                msg = f"📦 **Gained Item:** {quantity}x {item_name} ({rarity} {item_type})"
                cl.run_sync(cl.Message(content=msg, author="🎮 System").send())
            except Exception:
                pass

            return (
                f"SUCCESS: {quantity}x '{item_name}' ({rarity} {item_type}) "
                f"added to {entity_name}'s inventory."
            )
        return f"FAILED: {result.get('reason', 'unknown error')}"


@tool
def give_gold(entity_name: str, amount: int) -> str:
    """
    Award gold coins to the player's wallet.
    Use a positive amount for rewards; negative to deduct (e.g. purchase cost).
    Call this whenever the GM narrates the player receiving or spending gold.
    """
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."

        from app.db.inventory_service import add_gold
        result = add_gold(session, entity.id, amount)

        if result["success"]:
            verb = "received" if amount > 0 else "spent"
            # Send UI System Message
            try:
                import chainlit as cl
                icon = "💰" if amount > 0 else "💸"
                action = "Gained" if amount > 0 else "Lost"
                msg = f"{icon} **{action} Gold:** {abs(amount)} (Balance: {result['balance']})"
                cl.run_sync(cl.Message(content=msg, author="🎮 System").send())
            except Exception:
                pass

            return f"SUCCESS: {entity_name} {verb} {abs(amount)} gold. Balance: {result['balance']}."
        return f"FAILED: {result.get('reason', 'unknown error')}"


@tool
def mark_npc_met(npc_name: str) -> str:
    """
    Mark an NPC as 'met' by the player.
    Call this whenever the player has a meaningful interaction with an NPC.
    """
    from app.db.models import SideCharacter
    with Session(engine) as session:
        npc = session.exec(select(SideCharacter).where(SideCharacter.name == npc_name)).first()
        if not npc:
            return f"ERROR: NPC '{npc_name}' not found."
            
        npc.has_met_player = True
        session.add(npc)
        session.commit()
        return f"SUCCESS: {npc_name} marked as met."

@tool
def resume_travel(entity_name: str) -> str:
    """
    Resume an interrupted travel journey for an entity.
    Call this when a travel event (like combat) is resolved successfully.
    """
    from app.db.models import TravelState
    import chainlit as cl
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
            
        travel = session.exec(select(TravelState).where(TravelState.entity_id == entity.id, TravelState.is_completed == False)).first()
        if not travel:
            return f"ERROR: No active or interrupted journey for {entity_name}."
            
        if travel.status != "interrupted":
            return f"ERROR: Journey is already {travel.status}."
            
        travel.status = "active"
        session.add(travel)
        session.commit()
        
        try:
            cl.run_sync(cl.Message(content=f"🛣️ **Travel Resumed:** {entity_name} continues their journey.").send())
        except Exception:
            pass
            
        return f"SUCCESS: Journey for {entity_name} resumed."

@tool
def cancel_travel(entity_name: str) -> str:
    """
    Cancel an active or interrupted journey.
    The entity will be stranded at their current location or last known checkpoint.
    """
    from app.db.models import TravelState
    import chainlit as cl
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
            
        travel = session.exec(select(TravelState).where(TravelState.entity_id == entity.id, TravelState.is_completed == False)).first()
        if not travel:
            return f"ERROR: No active journey to cancel for {entity_name}."
            
        session.delete(travel)
        session.commit()
        
        try:
            cl.run_sync(cl.Message(content=f"🛑 **Travel Canceled:** {entity_name} abandons their journey.").send())
        except Exception:
            pass
            
        return f"SUCCESS: Journey for {entity_name} canceled."


@tool
def advance_tutorial_phase(entity_name: str) -> str:
    """
    Advance the tutorial to the next phase.
    Call this when the GM's phase directive says "ONCE THE PLAYER... issue the arbiter_instruction: 'advance tutorial phase'".
    This fires the UI notifications and progresses the internal quest state.
    """
    from app.db.tutorial_service import advance_phase, PHASE_EVENTS
    with Session(engine) as session:
        entity = tarot_service.get_entity_by_name(session, entity_name)
        if not entity:
            return f"ERROR: Entity '{entity_name}' not found."
            
        result = advance_phase(session, entity.id)
        if result.get("success"):
            new_phase = result.get("phase")
            event_msg = PHASE_EVENTS.get(new_phase, "")
            if event_msg:
                try:
                    import chainlit as cl
                    cl.run_sync(cl.Message(content=event_msg, author="🎮 System").send())
                except Exception:
                    pass
            return f"SUCCESS: Tutorial advanced to phase {new_phase}."
        return f"FAILED: {result.get('reason', 'already complete')}"



# ─── Tool registry ────────────────────────────────────────────────────────────
ARBITER_TOOLS = [
    # Tarot economy tools
    get_entity_info,
    transfer_energy,
    transfer_card,
    cast_spell,
    check_location_rules,
    get_transaction_log,
    get_card_abilities,
    # Game event tools — bridge narrative to DB state
    move_player,
    record_combat_victory,
    record_item_delivered,
    record_trade,
    # Inventory tools — award items/gold when GM narrates rewards
    give_item,
    give_gold,
    # Travel tools
    resume_travel,
    cancel_travel,
    # NPC tools
    mark_npc_met,
    create_location_in_city,
    # Tutorial
    advance_tutorial_phase,
]
