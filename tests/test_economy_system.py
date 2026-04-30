"""
tests/test_economy_system.py
Tests: Wallet, transfers, dynamic pricing, shop buy/sell, auctions, tax policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import (
    AUCTION_TAX, RARITY_PRICE_MULT, SHOP_TYPE_MARKUP,
    Auction, InventoryItem, Location, Shop, ShopInventory,
    TarotEntity, TaxPolicy, Wallet,
)
from app.db.economy_service import (
    buy_from_shop, compute_price, create_auction, create_shop,
    get_or_create_wallet, get_tax_rates, place_bid,
    resolve_all_expired_auctions, resolve_auction,
    sell_to_shop, set_tax_policy, stock_shop, transfer_money, restock_shop,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _entity(session, name="Player", balance=1000) -> TarotEntity:
    e = TarotEntity(entity_name=name)
    session.add(e)
    session.flush()
    w = Wallet(owner_entity_id=e.id, balance=balance)
    session.add(w)
    session.commit()
    session.refresh(e)
    return e


def _item(session, owner_id, name="Sword", rarity="common",
          base_price=100, tradable=True, qty=5, value=50) -> InventoryItem:
    item = InventoryItem(
        name=name, description="A test item.", quantity=qty,
        item_type="equipment", rarity=rarity, value=value,
        base_price=base_price, tradable=tradable, stackable=True,
        owner_id=owner_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _location(session, name="TestCity", loc_type="city") -> Location:
    loc = Location(name=name, description=".", x=0.0, y=0.0,
                   location_type=loc_type)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _shop(session, location_id, shop_type="general", owner_id=None) -> Shop:
    r = create_shop(session, f"Shop@{location_id}", location_id,
                    shop_type=shop_type, owner_entity_id=owner_id)
    return session.get(Shop, r["shop_id"])


def _future(seconds=3600):
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds=1):
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# ─────────────────────────────────────────────────────────────
# 1. Wallet
# ─────────────────────────────────────────────────────────────
class TestWallet:
    def test_create_wallet(self, session):
        e = _entity(session, balance=0)
        w = get_or_create_wallet(session, e.id)
        assert w.owner_entity_id == e.id
        assert w.balance == 0

    def test_idempotent_get_or_create(self, session):
        e = _entity(session)
        w1 = get_or_create_wallet(session, e.id)
        w2 = get_or_create_wallet(session, e.id)
        assert w1.id == w2.id

    def test_entity_not_found_raises(self, session):
        with pytest.raises(ValueError):
            get_or_create_wallet(session, 99999)


# ─────────────────────────────────────────────────────────────
# 2. Money transfers
# ─────────────────────────────────────────────────────────────
class TestTransferMoney:
    def test_successful_transfer(self, session):
        a = _entity(session, "Alice", 500)
        b = _entity(session, "Bob", 0)
        r = transfer_money(session, a.id, b.id, 200)
        assert r["success"] is True
        assert r["sender_balance"] == 300
        assert r["receiver_balance"] == 200

    def test_insufficient_funds(self, session):
        a = _entity(session, "Poor", 50)
        b = _entity(session, "Rich", 0)
        r = transfer_money(session, a.id, b.id, 100)
        assert r["success"] is False
        assert r["reason"] == "insufficient_funds"

    def test_zero_amount_rejected(self, session):
        a = _entity(session, "A", 100)
        b = _entity(session, "B", 0)
        r = transfer_money(session, a.id, b.id, 0)
        assert r["success"] is False

    def test_negative_amount_rejected(self, session):
        a = _entity(session, "A2", 100)
        b = _entity(session, "B2", 0)
        r = transfer_money(session, a.id, b.id, -50)
        assert r["success"] is False

    def test_self_transfer_rejected(self, session):
        a = _entity(session, "Self", 100)
        r = transfer_money(session, a.id, a.id, 50)
        assert r["success"] is False
        assert r["reason"] == "cannot_transfer_to_self"

    def test_balance_never_goes_negative(self, session):
        a = _entity(session, "Broke", 10)
        b = _entity(session, "Recv", 0)
        transfer_money(session, a.id, b.id, 10)
        w = get_or_create_wallet(session, a.id)
        assert w.balance == 0


# ─────────────────────────────────────────────────────────────
# 3. Dynamic pricing
# ─────────────────────────────────────────────────────────────
class TestComputePrice:
    def test_base_price_used(self, session):
        loc = _location(session)
        e = _entity(session)
        item = _item(session, e.id, base_price=200)
        price = compute_price(session, item, loc.id)
        assert price == pytest.approx(200, rel=0.1)

    def test_rarity_fallback_when_base_price_zero(self, session):
        loc = _location(session)
        e = _entity(session)
        item = _item(session, e.id, base_price=0, value=100, rarity="rare")
        price = compute_price(session, item, loc.id)
        # fallback = value * rarity_mult = 100 * 3.0 = 300
        assert price >= 300

    def test_non_tradable_returns_zero(self, session):
        loc = _location(session)
        e = _entity(session)
        item = _item(session, e.id, tradable=False, base_price=100)
        assert compute_price(session, item, loc.id) == 0

    def test_price_always_positive_for_tradable(self, session):
        loc = _location(session)
        e = _entity(session)
        item = _item(session, e.id, base_price=1)
        assert compute_price(session, item, loc.id) >= 1


# ─────────────────────────────────────────────────────────────
# 4. Shop creation
# ─────────────────────────────────────────────────────────────
class TestCreateShop:
    def test_create_general_shop(self, session):
        loc = _location(session)
        r = create_shop(session, "General Store", loc.id)
        assert r["success"] is True
        assert r["shop_id"] is not None

    def test_duplicate_shop_rejected(self, session):
        loc = _location(session)
        create_shop(session, "Dup Shop", loc.id)
        r = create_shop(session, "Dup Shop", loc.id)
        assert r["success"] is False
        assert r["reason"] == "shop_already_exists"

    def test_invalid_shop_type(self, session):
        loc = _location(session)
        r = create_shop(session, "Bad", loc.id, shop_type="tavern")
        assert r["success"] is False

    def test_all_valid_shop_types(self, session):
        loc = _location(session)
        for i, st in enumerate(SHOP_TYPE_MARKUP):
            r = create_shop(session, f"Shop_{i}", loc.id, shop_type=st)
            assert r["success"] is True


# ─────────────────────────────────────────────────────────────
# 5. Buy from shop
# ─────────────────────────────────────────────────────────────
class TestBuyFromShop:
    def _setup(self, session, buyer_balance=1000):
        loc = _location(session)
        merchant = _entity(session, "Merchant", 0)
        buyer = _entity(session, "Buyer", buyer_balance)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, merchant.id, base_price=100, qty=10)
        stock_shop(session, shop.id, item.id, quantity=10)
        return buyer, shop, item, loc

    def test_successful_buy(self, session):
        buyer, shop, item, loc = self._setup(session)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 2)
        assert r["success"] is True
        assert r["qty"] == 2
        assert r["total_cost"] > 0

    def test_buyer_balance_decreases(self, session):
        buyer, shop, item, _ = self._setup(session, buyer_balance=5000)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 1)
        assert r["buyer_balance"] < 5000

    def test_insufficient_funds(self, session):
        buyer, shop, item, _ = self._setup(session, buyer_balance=1)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 5)
        assert r["success"] is False
        assert r["reason"] == "insufficient_funds"

    def test_insufficient_stock(self, session):
        buyer, shop, item, _ = self._setup(session)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 999)
        assert r["success"] is False
        assert r["reason"] == "insufficient_stock"

    def test_non_tradable_item_blocked(self, session):
        loc = _location(session)
        merchant = _entity(session, "M2", 0)
        buyer = _entity(session, "B2", 5000)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, merchant.id, tradable=False, base_price=100)
        stock_shop(session, shop.id, item.id, quantity=5)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 1)
        assert r["success"] is False
        assert r["reason"] == "item_not_tradable"

    def test_zero_qty_rejected(self, session):
        buyer, shop, item, _ = self._setup(session)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 0)
        assert r["success"] is False

    def test_item_stacks_in_buyer_inventory(self, session):
        buyer, shop, item, _ = self._setup(session, buyer_balance=9999)
        buy_from_shop(session, buyer.id, shop.id, item.id, 2)
        buy_from_shop(session, buyer.id, shop.id, item.id, 3)
        from sqlmodel import select
        stacks = session.exec(
            select(InventoryItem).where(
                InventoryItem.owner_id == buyer.id,
                InventoryItem.name == item.name,
            )
        ).all()
        total_qty = sum(s.quantity for s in stacks)
        assert total_qty == 5


# ─────────────────────────────────────────────────────────────
# 6. Sell to shop
# ─────────────────────────────────────────────────────────────
class TestSellToShop:
    def _setup(self, session):
        loc = _location(session)
        merchant = _entity(session, "M_sell", 5000)
        seller = _entity(session, "Seller", 0)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, seller.id, base_price=100, qty=5)
        return seller, shop, item, merchant

    def test_successful_sell(self, session):
        seller, shop, item, _ = self._setup(session)
        r = sell_to_shop(session, seller.id, shop.id, item.id, 2)
        assert r["success"] is True
        assert r["net_received"] > 0

    def test_seller_balance_increases(self, session):
        seller, shop, item, _ = self._setup(session)
        r = sell_to_shop(session, seller.id, shop.id, item.id, 1)
        assert r["seller_balance"] > 0

    def test_sell_more_than_owned_fails(self, session):
        seller, shop, item, _ = self._setup(session)
        r = sell_to_shop(session, seller.id, shop.id, item.id, 999)
        assert r["success"] is False
        assert r["reason"] == "insufficient_quantity"

    def test_item_removed_from_seller(self, session):
        seller, shop, item, _ = self._setup(session)
        sell_to_shop(session, seller.id, shop.id, item.id, 5)
        from sqlmodel import select
        remaining = session.exec(
            select(InventoryItem).where(
                InventoryItem.id == item.id,
                InventoryItem.owner_id == seller.id,
            )
        ).first()
        assert remaining is None  # qty hit 0 → deleted

    def test_black_market_accepts_non_tradable(self, session):
        loc = _location(session)
        seller = _entity(session, "Smuggler", 0)
        bm_shop = _shop(session, loc.id, shop_type="black_market")
        item = _item(session, seller.id, tradable=False, base_price=200, qty=2)
        r = sell_to_shop(session, seller.id, bm_shop.id, item.id, 1)
        assert r["success"] is True


# ─────────────────────────────────────────────────────────────
# 7. Shop restock
# ─────────────────────────────────────────────────────────────
class TestRestock:
    def test_restock_adds_units(self, session):
        loc = _location(session)
        merchant = _entity(session, "Restockler", 0)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, merchant.id, qty=1)
        stock_shop(session, shop.id, item.id, quantity=1, restock_rate=2.0)
        r = restock_shop(session, shop.id, delta_minutes=5.0)
        assert r["success"] is True
        assert r["units_restocked"] == 10   # 2.0 * 5 = 10

    def test_no_restock_rate_adds_nothing(self, session):
        loc = _location(session)
        merchant = _entity(session, "NoRestock", 0)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, merchant.id, qty=1)
        stock_shop(session, shop.id, item.id, quantity=5, restock_rate=0.0)
        r = restock_shop(session, shop.id, delta_minutes=60.0)
        assert r["units_restocked"] == 0


# ─────────────────────────────────────────────────────────────
# 8. Auctions
# ─────────────────────────────────────────────────────────────
class TestAuctions:
    def _setup(self, session, hall="small_hall"):
        loc = _location(session)
        seller = _entity(session, "Seller_A", 0)
        bidder = _entity(session, "Bidder_A", 5000)
        item = _item(session, seller.id, base_price=100, qty=3)
        r = create_auction(
            session, seller.id, item.id, 1, 100,
            loc.id, _future(3600), hall_type=hall,
        )
        return seller, bidder, item, session.get(Auction, r["auction_id"])

    def test_create_auction(self, session):
        loc = _location(session)
        seller = _entity(session, "SA", 0)
        item = _item(session, seller.id, qty=2)
        r = create_auction(session, seller.id, item.id, 1, 50, loc.id, _future())
        assert r["success"] is True
        assert r["auction_id"] is not None

    def test_item_locked_on_listing(self, session):
        loc = _location(session)
        seller = _entity(session, "SLock", 0)
        item = _item(session, seller.id, qty=3, base_price=50)
        create_auction(session, seller.id, item.id, 2, 50, loc.id, _future())
        session.refresh(item)
        assert item.quantity == 1   # 3 - 2 locked

    def test_invalid_hall_type(self, session):
        loc = _location(session)
        seller = _entity(session, "SBad", 0)
        item = _item(session, seller.id)
        r = create_auction(session, seller.id, item.id, 1, 50, loc.id, _future(),
                           hall_type="fake_hall")
        assert r["success"] is False

    def test_past_end_time_rejected(self, session):
        loc = _location(session)
        seller = _entity(session, "SPast", 0)
        item = _item(session, seller.id)
        r = create_auction(session, seller.id, item.id, 1, 50, loc.id, _past())
        assert r["success"] is False

    def test_place_bid(self, session):
        seller, bidder, item, auction = self._setup(session)
        r = place_bid(session, bidder.id, auction.id, 200)
        assert r["success"] is True
        session.refresh(auction)
        assert auction.current_bid == 200
        assert auction.highest_bidder_id == bidder.id

    def test_bid_too_low(self, session):
        seller, bidder, item, auction = self._setup(session)
        place_bid(session, bidder.id, auction.id, 200)
        r = place_bid(session, bidder.id, auction.id, 150)
        assert r["success"] is False
        assert r["reason"] == "bid_too_low"

    def test_seller_cannot_bid(self, session):
        seller, bidder, item, auction = self._setup(session)
        r = place_bid(session, seller.id, auction.id, 200)
        assert r["success"] is False
        assert r["reason"] == "seller_cannot_bid"

    def test_insufficient_funds_bid(self, session):
        loc = _location(session)
        seller = _entity(session, "SRich", 0)
        poor_bidder = _entity(session, "BPoor", 50)
        item = _item(session, seller.id, qty=2, base_price=50)
        r_a = create_auction(session, seller.id, item.id, 1, 100, loc.id, _future())
        r = place_bid(session, poor_bidder.id, r_a["auction_id"], 200)
        assert r["success"] is False
        assert r["reason"] == "insufficient_funds"

    def test_previous_bidder_refunded(self, session):
        seller, bidder1, item, auction = self._setup(session)
        bidder2 = _entity(session, "Bidder2", 5000)
        place_bid(session, bidder1.id, auction.id, 300)
        w1_before = get_or_create_wallet(session, bidder1.id).balance
        place_bid(session, bidder2.id, auction.id, 500)
        w1_after = get_or_create_wallet(session, bidder1.id).balance
        assert w1_after == w1_before + 300   # refunded

    def test_resolve_auction_sold(self, session):
        seller, bidder, item, auction = self._setup(session)
        place_bid(session, bidder.id, auction.id, 400)
        # Force expire
        auction.end_time = _past()
        session.add(auction)
        session.commit()
        r = resolve_auction(session, auction.id)
        assert r["success"] is True
        assert r["outcome"] == "sold"
        assert r["winner_id"] == bidder.id
        assert r["seller_payout"] < 400   # tax deducted

    def test_resolve_no_bids_returns_item(self, session):
        seller, _, item, auction = self._setup(session)
        auction.end_time = _past()
        session.add(auction)
        session.commit()
        r = resolve_auction(session, auction.id)
        assert r["success"] is True
        assert r["outcome"] == "no_bids_item_returned"

    def test_resolve_not_ended_yet(self, session):
        seller, bidder, item, auction = self._setup(session)
        r = resolve_auction(session, auction.id)
        assert r["success"] is False
        assert r["reason"] == "auction_not_yet_ended"

    def test_resolve_all_expired(self, session):
        loc = _location(session)
        for i in range(3):
            s = _entity(session, f"S{i}", 0)
            it = _item(session, s.id, name=f"Item{i}", qty=2)
            a = create_auction(session, s.id, it.id, 1, 10, loc.id, _future())
            auc = session.get(Auction, a["auction_id"])
            auc.end_time = _past()
            session.add(auc)
        session.commit()
        count = resolve_all_expired_auctions(session)
        assert count == 3

    def test_all_hall_types_work(self, session):
        loc = _location(session)
        for hall in AUCTION_TAX:
            s = _entity(session, f"SH_{hall}", 0)
            it = _item(session, s.id, name=f"item_{hall}", qty=1)
            r = create_auction(session, s.id, it.id, 1, 10, loc.id, _future(),
                               hall_type=hall)
            assert r["success"] is True


# ─────────────────────────────────────────────────────────────
# 9. Tax policy
# ─────────────────────────────────────────────────────────────
class TestTaxPolicy:
    def test_set_and_get_tax(self, session):
        loc = _location(session)
        r = set_tax_policy(session, loc.id, trade_tax=0.02, auction_tax=0.05)
        assert r["success"] is True
        rates = get_tax_rates(session, loc.id)
        assert rates["trade_tax"] == pytest.approx(0.02)
        assert rates["auction_tax"] == pytest.approx(0.05)

    def test_default_tax_when_no_policy(self, session):
        loc = _location(session)
        rates = get_tax_rates(session, loc.id)
        assert rates["trade_tax"] == pytest.approx(0.05)
        assert rates["auction_tax"] == pytest.approx(0.10)

    def test_tax_clamped_at_100_percent(self, session):
        loc = _location(session)
        r = set_tax_policy(session, loc.id, trade_tax=5.0, auction_tax=10.0)
        assert r["trade_tax"] == pytest.approx(1.0)
        assert r["auction_tax"] == pytest.approx(1.0)

    def test_trading_hub_low_tax(self, session):
        """Virell Prime hub should use trading_hub shop type (0.9 markup, 2% tax)."""
        loc = _location(session, name="Virell Prime", loc_type="trading_hub")
        set_tax_policy(session, loc.id, trade_tax=0.02, auction_tax=0.03)
        rates = get_tax_rates(session, loc.id)
        assert rates["trade_tax"] == pytest.approx(0.02)

    def test_buy_uses_location_tax(self, session):
        """Tax from TaxPolicy overrides shop.tax_rate in buy_from_shop."""
        loc = _location(session)
        set_tax_policy(session, loc.id, trade_tax=0.0, auction_tax=0.0)
        merchant = _entity(session, "M_tax", 0)
        buyer = _entity(session, "B_tax", 9999)
        shop = _shop(session, loc.id, owner_id=merchant.id)
        item = _item(session, merchant.id, base_price=100, qty=5)
        stock_shop(session, shop.id, item.id, quantity=5)
        r = buy_from_shop(session, buyer.id, shop.id, item.id, 1)
        # With 0% tax, total_cost == unit_price
        assert r["success"] is True
        assert r["tax_rate"] == pytest.approx(0.0)
        assert r["total_cost"] == r["unit_price"]


# ─────────────────────────────────────────────────────────────
# 10. Model constants sanity
# ─────────────────────────────────────────────────────────────
class TestModelConstants:
    def test_rarity_price_mult_all_positive(self):
        for k, v in RARITY_PRICE_MULT.items():
            assert v > 0, f"Negative multiplier for rarity {k}"

    def test_shop_markup_all_positive(self):
        for k, v in SHOP_TYPE_MARKUP.items():
            assert v > 0, f"Negative markup for shop type {k}"

    def test_auction_tax_all_between_0_and_1(self):
        for k, v in AUCTION_TAX.items():
            assert 0 < v < 1, f"Auction tax out of range for {k}"

    def test_trading_hub_cheapest(self):
        assert SHOP_TYPE_MARKUP["trading_hub"] < SHOP_TYPE_MARKUP["general"]

    def test_black_market_most_expensive(self):
        assert SHOP_TYPE_MARKUP["black_market"] > SHOP_TYPE_MARKUP["general"]
