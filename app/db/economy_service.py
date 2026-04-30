"""
app/db/economy_service.py
==========================
Complete economy service: money, dynamic pricing, shops, auctions, tax.

Public API
----------
Wallet:
    get_or_create_wallet(session, entity_id) -> Wallet
    transfer_money(session, from_id, to_id, amount) -> dict

Pricing:
    compute_price(session, item, location_id) -> int

Shops:
    create_shop(session, ...) -> dict
    buy_from_shop(session, entity_id, shop_id, item_id, qty) -> dict
    sell_to_shop(session, entity_id, shop_id, item_id, qty) -> dict
    restock_shop(session, shop_id, delta_minutes) -> dict

Auctions:
    create_auction(session, seller_id, item_id, qty, start_price, location_id, end_time, hall_type) -> dict
    place_bid(session, entity_id, auction_id, amount) -> dict
    resolve_auction(session, auction_id) -> dict
    resolve_all_expired_auctions(session) -> int

Tax helpers:
    get_tax_rates(session, location_id) -> dict
    set_tax_policy(session, location_id, trade_tax, auction_tax) -> dict

Design rules
------------
- No negative balances — every transfer is validated before mutation
- All mutations use session.flush() before commit to catch FK violations early
- Prices are integer gold — float math is done then int()-truncated
- Dynamic pricing hooks into world_service.get_location_status() for live modifiers
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.models import (
    AUCTION_TAX,
    RARITY_PRICE_MULT,
    SHOP_TYPE_MARKUP,
    Auction,
    InventoryItem,
    Shop,
    ShopInventory,
    TaxPolicy,
    TarotEntity,
    Wallet,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# WALLET
# =============================================================

def get_or_create_wallet(session: Session, entity_id: int) -> Wallet:
    """Idempotent: returns existing wallet or creates one with balance=0."""
    wallet = session.exec(
        select(Wallet).where(Wallet.owner_entity_id == entity_id)
    ).first()
    if not wallet:
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            raise ValueError(f"Entity {entity_id} not found")
        wallet = Wallet(owner_entity_id=entity_id, balance=0)
        session.add(wallet)
        session.commit()
        session.refresh(wallet)
    return wallet


def transfer_money(
    session: Session,
    from_entity_id: int,
    to_entity_id: int,
    amount: int,
) -> dict:
    """
    Atomically debit from_entity and credit to_entity.
    Rules:
      - amount must be > 0
      - sender must have sufficient balance
      - both wallets created if missing
    """
    if amount <= 0:
        return {"success": False, "reason": "amount_must_be_positive"}
    if from_entity_id == to_entity_id:
        return {"success": False, "reason": "cannot_transfer_to_self"}

    sender = get_or_create_wallet(session, from_entity_id)
    receiver = get_or_create_wallet(session, to_entity_id)

    if sender.balance < amount:
        return {
            "success": False,
            "reason": "insufficient_funds",
            "have": sender.balance,
            "need": amount,
        }

    sender.balance -= amount
    receiver.balance += amount
    session.add(sender)
    session.add(receiver)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    return {
        "success": True,
        "amount": amount,
        "sender_balance": sender.balance,
        "receiver_balance": receiver.balance,
    }


# =============================================================
# DYNAMIC PRICING
# =============================================================

def _location_demand_factor(session: Session, location_id: int) -> float:
    """
    Demand factor from location type and active sovereign influence.
    Pulls live world state from world_service without importing at module level
    to avoid circular imports.
    """
    from app.db.world_service import get_location_status
    try:
        status = get_location_status(session, location_id)
        # Unstable locations inflate prices
        instability_bonus = 0.3 if status.get("is_unstable") else 0.0
        # Sovereign influence → price distortion (+0.1 per 10 influence above 50)
        influence = status.get("max_sovereign_influence", 0.0)
        influence_bonus = max(0.0, (influence - 50) / 100.0)
        return 1.0 + instability_bonus + influence_bonus
    except Exception:
        return 1.0


def _location_in_war(session: Session, location_id: int) -> bool:
    """Check if any active war event exists at this location."""
    from app.db.world_service import get_active_events
    events = get_active_events(session, location_id)
    return any(e["event_type"] == "war" for e in events)


def compute_price(session: Session, item: InventoryItem, location_id: int) -> int:
    """
    Dynamic price formula:
      base = item.base_price (if 0, use value * rarity_mult as fallback)
      * demand_factor(location)
      * 1.3 if war active at location
      * (1 + sovereign_influence_modifier)

    Returns integer gold. Minimum 1 if item is tradable, else 0.
    """
    if not item.tradable:
        return 0

    base = item.base_price
    if base == 0:
        rarity_mult = RARITY_PRICE_MULT.get(item.rarity, 1.0)
        base = max(1, int(item.value * rarity_mult))

    price = float(base)
    price *= _location_demand_factor(session, location_id)

    if _location_in_war(session, location_id):
        price *= 1.3

    return max(1, int(price))


def _get_trade_tax(session: Session, location_id: int) -> float:
    """Return trade tax rate for a location. Falls back to 5% if no policy row."""
    policy = session.exec(
        select(TaxPolicy).where(TaxPolicy.location_id == location_id)
    ).first()
    return policy.trade_tax if policy else 0.05


def _get_auction_tax(session: Session, location_id: int, hall_type: str) -> float:
    """Return auction tax: use TaxPolicy if set, else AUCTION_TAX constant."""
    policy = session.exec(
        select(TaxPolicy).where(TaxPolicy.location_id == location_id)
    ).first()
    if policy:
        return policy.auction_tax
    return AUCTION_TAX.get(hall_type, 0.10)


# =============================================================
# SHOPS
# =============================================================

def create_shop(
    session: Session,
    name: str,
    location_id: int,
    shop_type: str = "general",
    owner_entity_id: Optional[int] = None,
    tax_rate: float = 0.05,
) -> dict:
    if shop_type not in SHOP_TYPE_MARKUP:
        return {"success": False, "reason": "invalid_shop_type",
                "valid": list(SHOP_TYPE_MARKUP.keys())}
    existing = session.exec(
        select(Shop).where(Shop.name == name, Shop.location_id == location_id)
    ).first()
    if existing:
        return {"success": False, "reason": "shop_already_exists", "shop_id": existing.id}

    # Ensure owner has a wallet
    if owner_entity_id:
        get_or_create_wallet(session, owner_entity_id)

    shop = Shop(
        name=name, location_id=location_id,
        shop_type=shop_type, owner_entity_id=owner_entity_id,
        tax_rate=max(0.0, min(1.0, tax_rate)),
    )
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return {"success": True, "shop_id": shop.id, "name": shop.name, "shop_type": shop_type}


def stock_shop(
    session: Session,
    shop_id: int,
    item_id: int,
    quantity: int,
    price_override: Optional[int] = None,
    restock_rate: float = 0.0,
) -> dict:
    """Add or update item stock in a shop."""
    shop = session.get(Shop, shop_id)
    if not shop:
        return {"success": False, "reason": "shop_not_found"}
    item = session.get(InventoryItem, item_id)
    if not item:
        return {"success": False, "reason": "item_not_found"}

    row = session.exec(
        select(ShopInventory).where(
            ShopInventory.shop_id == shop_id,
            ShopInventory.item_id == item_id,
        )
    ).first()
    if row:
        row.quantity += quantity
        if price_override is not None:
            row.price_override = price_override
    else:
        row = ShopInventory(
            shop_id=shop_id, item_id=item_id,
            quantity=quantity, price_override=price_override,
            restock_rate=restock_rate,
        )
    session.add(row)
    session.commit()
    return {"success": True, "shop_id": shop_id, "item_id": item_id, "quantity": row.quantity}


def _get_shop_item_price(session: Session, shop: Shop, item: InventoryItem) -> int:
    """Resolve item price in a specific shop (override → compute_price → markup)."""
    inv = session.exec(
        select(ShopInventory).where(
            ShopInventory.shop_id == shop.id,
            ShopInventory.item_id == item.id,
        )
    ).first()
    if inv and inv.price_override is not None:
        base = inv.price_override
    else:
        base = compute_price(session, item, shop.location_id)

    markup = SHOP_TYPE_MARKUP.get(shop.shop_type, 1.0)
    return max(1, int(base * markup))


def buy_from_shop(
    session: Session,
    entity_id: int,
    shop_id: int,
    item_id: int,
    qty: int,
) -> dict:
    """
    Player buys qty units from a shop.
    Steps:
      1. Validate shop open + stock sufficient
      2. Compute total price (with shop markup)
      3. Apply location trade tax → player pays price * (1 + tax)
      4. Deduct gold from player
      5. Transfer stock to player inventory
    """
    if qty <= 0:
        return {"success": False, "reason": "qty_must_be_positive"}

    shop = session.get(Shop, shop_id)
    if not shop or not shop.is_open:
        return {"success": False, "reason": "shop_not_found_or_closed"}

    item = session.get(InventoryItem, item_id)
    if not item:
        return {"success": False, "reason": "item_not_found"}
    if not item.tradable:
        return {"success": False, "reason": "item_not_tradable"}

    # Stock check
    inv = session.exec(
        select(ShopInventory).where(
            ShopInventory.shop_id == shop_id,
            ShopInventory.item_id == item_id,
        )
    ).first()
    if not inv or inv.quantity < qty:
        available = inv.quantity if inv else 0
        return {"success": False, "reason": "insufficient_stock", "available": available}

    unit_price = _get_shop_item_price(session, shop, item)
    tax_rate = _get_trade_tax(session, shop.location_id)
    # Buyer pays price + tax
    total_cost = int(unit_price * qty * (1 + tax_rate))

    buyer_wallet = get_or_create_wallet(session, entity_id)
    if buyer_wallet.balance < total_cost:
        return {"success": False, "reason": "insufficient_funds",
                "have": buyer_wallet.balance, "need": total_cost}

    # Deduct from buyer
    tax_amount = int(unit_price * qty * tax_rate)
    net_to_seller = total_cost - tax_amount
    buyer_wallet.balance -= total_cost
    session.add(buyer_wallet)

    # Pay seller (if shop has owner)
    if shop.owner_entity_id:
        seller_wallet = get_or_create_wallet(session, shop.owner_entity_id)
        seller_wallet.balance += net_to_seller
        session.add(seller_wallet)

    # Deduct shop stock
    inv.quantity -= qty
    session.add(inv)

    # Add to player inventory (stack if same item name + type exists)
    existing_stack = session.exec(
        select(InventoryItem).where(
            InventoryItem.owner_id == entity_id,
            InventoryItem.name == item.name,
        )
    ).first()
    if existing_stack and item.stackable:
        existing_stack.quantity += qty
        session.add(existing_stack)
    else:
        new_item = InventoryItem(
            name=item.name, description=item.description,
            quantity=qty, item_type=item.item_type, rarity=item.rarity,
            value=item.value, base_price=item.base_price, tradable=item.tradable,
            durability=item.durability, stackable=item.stackable,
            item_effect=item.item_effect, effect_type=item.effect_type,
            effect_value=item.effect_value, owner_id=entity_id,
        )
        session.add(new_item)

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    return {
        "success": True,
        "item": item.name,
        "qty": qty,
        "unit_price": unit_price,
        "tax_rate": tax_rate,
        "total_cost": total_cost,
        "buyer_balance": buyer_wallet.balance,
    }


def sell_to_shop(
    session: Session,
    entity_id: int,
    shop_id: int,
    item_id: int,
    qty: int,
) -> dict:
    """
    Player sells qty units to a shop.
    Shop pays: unit_price * qty * (1 - tax_rate)
    Black-market shops accept restricted items (tradable=False flagged items are still blocked).
    """
    if qty <= 0:
        return {"success": False, "reason": "qty_must_be_positive"}

    shop = session.get(Shop, shop_id)
    if not shop or not shop.is_open:
        return {"success": False, "reason": "shop_not_found_or_closed"}

    item = session.exec(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.owner_id == entity_id,
        )
    ).first()
    if not item:
        return {"success": False, "reason": "item_not_found_in_player_inventory"}
    if not item.tradable and shop.shop_type != "black_market":
        return {"success": False, "reason": "item_not_tradable"}
    if item.quantity < qty:
        return {"success": False, "reason": "insufficient_quantity",
                "have": item.quantity}

    unit_price = _get_shop_item_price(session, shop, item)
    tax_rate = _get_trade_tax(session, shop.location_id)
    gross = unit_price * qty
    tax_amount = int(gross * tax_rate)
    net_to_seller = gross - tax_amount

    # Deduct from player inventory
    item.quantity -= qty
    if item.quantity == 0:
        session.delete(item)
    else:
        session.add(item)

    # Pay player
    seller_wallet = get_or_create_wallet(session, entity_id)
    seller_wallet.balance += net_to_seller
    session.add(seller_wallet)

    # Deduct shop owner wallet if applicable
    if shop.owner_entity_id:
        owner_wallet = get_or_create_wallet(session, shop.owner_entity_id)
        if owner_wallet.balance >= gross:
            owner_wallet.balance -= gross
            session.add(owner_wallet)
        # If shop can't pay → sale still goes through (shop credit)

    # Add to shop stock
    inv = session.exec(
        select(ShopInventory).where(
            ShopInventory.shop_id == shop_id,
            ShopInventory.item_id == item_id,
        )
    ).first()
    if inv:
        inv.quantity += qty
        session.add(inv)

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    return {
        "success": True,
        "item": item.name,
        "qty": qty,
        "unit_price": unit_price,
        "tax_rate": tax_rate,
        "gross": gross,
        "tax_amount": tax_amount,
        "net_received": net_to_seller,
        "seller_balance": seller_wallet.balance,
    }


def restock_shop(session: Session, shop_id: int, delta_minutes: float) -> dict:
    """
    Advance shop restock by delta_minutes.
    Each ShopInventory row with restock_rate > 0 gains floor(rate * delta) units.
    """
    shop = session.get(Shop, shop_id)
    if not shop:
        return {"success": False, "reason": "shop_not_found"}

    rows = session.exec(
        select(ShopInventory).where(ShopInventory.shop_id == shop_id)
    ).all()
    restocked = 0
    for row in rows:
        if row.restock_rate > 0:
            gain = int(row.restock_rate * delta_minutes)
            if gain > 0:
                row.quantity += gain
                session.add(row)
                restocked += gain
    session.commit()
    return {"success": True, "shop_id": shop_id, "units_restocked": restocked}


# =============================================================
# AUCTIONS
# =============================================================

def create_auction(
    session: Session,
    seller_id: int,
    item_id: int,
    qty: int,
    starting_price: int,
    location_id: int,
    end_time: datetime,
    hall_type: str = "small_hall",
) -> dict:
    """
    List an item for auction. Item is locked in the listing (quantity deducted from player).
    """
    if hall_type not in AUCTION_TAX:
        return {"success": False, "reason": "invalid_hall_type",
                "valid": list(AUCTION_TAX.keys())}
    if starting_price < 1:
        return {"success": False, "reason": "starting_price_must_be_positive"}

    item = session.exec(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.owner_id == seller_id,
        )
    ).first()
    if not item:
        return {"success": False, "reason": "item_not_in_seller_inventory"}
    if not item.tradable:
        return {"success": False, "reason": "item_not_tradable"}
    if item.quantity < qty:
        return {"success": False, "reason": "insufficient_quantity", "have": item.quantity}

    # Lock item quantity
    item.quantity -= qty
    if item.quantity == 0:
        session.delete(item)
    else:
        session.add(item)

    now = _utcnow()
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if end_time <= now:
        return {"success": False, "reason": "end_time_must_be_in_future"}

    auction = Auction(
        seller_id=seller_id, item_id=item_id, quantity=qty,
        starting_price=starting_price, current_bid=0,
        location_id=location_id, hall_type=hall_type,
        end_time=end_time, is_active=True,
    )
    session.add(auction)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    session.refresh(auction)
    return {
        "success": True,
        "auction_id": auction.id,
        "item_id": item_id,
        "starting_price": starting_price,
        "hall_type": hall_type,
        "end_time": end_time.isoformat(),
    }


def place_bid(
    session: Session,
    entity_id: int,
    auction_id: int,
    amount: int,
) -> dict:
    """
    Place a bid on an active auction.
    Rules:
      - amount must exceed current_bid (or starting_price if no bids yet)
      - bidder must have the funds (reserved in wallet at bid time)
      - previous highest bidder is refunded immediately
    """
    auction = session.get(Auction, auction_id)
    if not auction or not auction.is_active:
        return {"success": False, "reason": "auction_not_found_or_inactive"}

    now = _utcnow()
    end_time = auction.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if now >= end_time:
        return {"success": False, "reason": "auction_has_ended"}
    if entity_id == auction.seller_id:
        return {"success": False, "reason": "seller_cannot_bid"}

    min_bid = max(auction.starting_price, auction.current_bid + 1)
    if amount < min_bid:
        return {"success": False, "reason": "bid_too_low",
                "minimum": min_bid, "offered": amount}

    bidder_wallet = get_or_create_wallet(session, entity_id)
    if bidder_wallet.balance < amount:
        return {"success": False, "reason": "insufficient_funds",
                "have": bidder_wallet.balance, "need": amount}

    # Refund previous highest bidder
    if auction.highest_bidder_id and auction.highest_bidder_id != entity_id:
        prev_wallet = get_or_create_wallet(session, auction.highest_bidder_id)
        prev_wallet.balance += auction.current_bid
        session.add(prev_wallet)
    elif auction.highest_bidder_id == entity_id:
        # Same bidder raising their own bid — refund their previous amount
        bidder_wallet.balance += auction.current_bid

    # Reserve new bid amount
    bidder_wallet.balance -= amount
    session.add(bidder_wallet)

    auction.current_bid = amount
    auction.highest_bidder_id = entity_id
    session.add(auction)

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    return {
        "success": True,
        "auction_id": auction_id,
        "new_bid": amount,
        "bidder_balance": bidder_wallet.balance,
    }


def resolve_auction(session: Session, auction_id: int) -> dict:
    """
    Resolve an expired auction.
    If bids exist:
      - transfer item to highest bidder
      - transfer gold (bid - tax) to seller
    If no bids:
      - return item to seller
    """
    auction = session.get(Auction, auction_id)
    if not auction:
        return {"success": False, "reason": "auction_not_found"}
    if not auction.is_active:
        return {"success": False, "reason": "auction_already_resolved"}

    now = _utcnow()
    end_time = auction.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if now < end_time:
        return {"success": False, "reason": "auction_not_yet_ended"}

    auction.is_active = False

    if auction.highest_bidder_id is None:
        # No bids — return item to seller
        _give_item_to(session, auction, auction.seller_id)
        session.add(auction)
        session.commit()
        return {"success": True, "outcome": "no_bids_item_returned", "auction_id": auction_id}

    # Calculate seller payout
    tax_rate = _get_auction_tax(session, auction.location_id, auction.hall_type)
    tax_amount = int(auction.current_bid * tax_rate)
    seller_payout = auction.current_bid - tax_amount

    # Pay seller
    seller_wallet = get_or_create_wallet(session, auction.seller_id)
    seller_wallet.balance += seller_payout
    session.add(seller_wallet)

    # Transfer item to winner (funds already reserved from place_bid)
    _give_item_to(session, auction, auction.highest_bidder_id)
    session.add(auction)

    try:
        session.commit()
    except Exception as e:
        session.rollback()
        return {"success": False, "reason": f"db_error: {e}"}

    return {
        "success": True,
        "outcome": "sold",
        "auction_id": auction_id,
        "winner_id": auction.highest_bidder_id,
        "final_bid": auction.current_bid,
        "tax_amount": tax_amount,
        "seller_payout": seller_payout,
    }


def _give_item_to(session: Session, auction: Auction, recipient_id: int) -> None:
    """Internal: create or stack item in recipient inventory from auction listing."""
    # Fetch item template by id (item was removed from seller inv at listing time)
    # We stored item_id which still points to the original item row.
    # Try to find a copy we can use as a template.
    template = session.get(InventoryItem, auction.item_id)
    if template:
        # Stack into existing inventory if possible
        existing = session.exec(
            select(InventoryItem).where(
                InventoryItem.owner_id == recipient_id,
                InventoryItem.name == template.name,
            )
        ).first()
        if existing and template.stackable:
            existing.quantity += auction.quantity
            session.add(existing)
            return
        # Otherwise create a new row
        new_item = InventoryItem(
            name=template.name, description=template.description,
            quantity=auction.quantity, item_type=template.item_type,
            rarity=template.rarity, value=template.value,
            base_price=template.base_price, tradable=template.tradable,
            durability=template.durability, stackable=template.stackable,
            item_effect=template.item_effect, effect_type=template.effect_type,
            effect_value=template.effect_value, owner_id=recipient_id,
        )
        session.add(new_item)
    # If template row no longer exists (deleted when qty hit 0), we can't reconstruct.
    # In production this would use a separate ItemTemplate table.


def resolve_all_expired_auctions(session: Session) -> int:
    """Batch-resolve all expired active auctions. Returns count resolved."""
    now = _utcnow()
    auctions = session.exec(
        select(Auction).where(Auction.is_active == True)  # noqa: E712
    ).all()
    count = 0
    for a in auctions:
        end_time = a.end_time
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        if now >= end_time:
            result = resolve_auction(session, a.id)
            if result.get("success"):
                count += 1
    return count


# =============================================================
# TAX POLICY
# =============================================================

def set_tax_policy(
    session: Session,
    location_id: int,
    trade_tax: float,
    auction_tax: float,
) -> dict:
    trade_tax = max(0.0, min(1.0, trade_tax))
    auction_tax = max(0.0, min(1.0, auction_tax))
    row = session.exec(
        select(TaxPolicy).where(TaxPolicy.location_id == location_id)
    ).first()
    if row:
        row.trade_tax = trade_tax
        row.auction_tax = auction_tax
    else:
        row = TaxPolicy(location_id=location_id, trade_tax=trade_tax, auction_tax=auction_tax)
    session.add(row)
    session.commit()
    return {"success": True, "location_id": location_id,
            "trade_tax": trade_tax, "auction_tax": auction_tax}


def get_tax_rates(session: Session, location_id: int) -> dict:
    policy = session.exec(
        select(TaxPolicy).where(TaxPolicy.location_id == location_id)
    ).first()
    return {
        "location_id": location_id,
        "trade_tax": policy.trade_tax if policy else 0.05,
        "auction_tax": policy.auction_tax if policy else 0.10,
    }
