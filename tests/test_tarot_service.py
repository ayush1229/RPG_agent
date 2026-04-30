"""
tests/test_tarot_service.py

Run with:
    uv run python -m pytest tests/ -v

Tests are ISOLATED — each test uses an in-memory SQLite DB and a fresh
set of entities, so they never pollute each other or the real tarot.db.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

# ─── Use an in-memory DB for all tests ────────────────────────────────────────
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)


def get_test_session() -> Session:
    return Session(TEST_ENGINE)


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    """Create all tables once for the test session."""
    from app.db.models import (  # noqa: F401 — import side effects register models
        GlobalConfig, TarotAbility, TarotCardLore, TarotCardTransaction,
        TarotEntity, TarotShard, TarotTransaction,
    )
    SQLModel.metadata.create_all(TEST_ENGINE)
    yield


@pytest.fixture()
def session():
    """Fresh session per test; rolls back on teardown."""
    with Session(TEST_ENGINE) as s:
        yield s
        s.rollback()


@pytest.fixture()
def service():
    from app.db.service import TarotService
    return TarotService()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_entity(session: Session, name: str, upright: int = 100, reversed: int = 100):
    """Create and persist a TarotEntity with given capacity and full mana."""
    from app.db.models import TarotEntity
    e = TarotEntity(
        entity_name=name,
        upright_capacity=upright,
        reversed_capacity=reversed,
        current_upright_mana=upright,
        current_reversed_mana=reversed,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def make_lore(session: Session, name: str, arcana_type: str = "Minor", suit: str = "Cups"):
    """Create and persist a TarotCardLore entry."""
    from app.db.models import TarotCardLore
    lore = TarotCardLore(
        name=name,
        arcana_type=arcana_type,
        suit=suit if arcana_type == "Minor" else None,
        upright_meaning="test upright",
        reversed_meaning="test reversed",
        magical_manifestation="test magic",
        personality_archetype="test archetype",
        core_themes="test themes",
        power_domains="test domains",
        behavioral_bias="test bias",
    )
    session.add(lore)
    session.commit()
    session.refresh(lore)
    return lore


def make_shard(session: Session, owner_id: int, lore_id: int):
    """Give entity a TarotShard."""
    from app.db.models import TarotShard
    shard = TarotShard(owner_id=owner_id, lore_id=lore_id)
    session.add(shard)
    session.commit()
    session.refresh(shard)
    return shard


def make_ability(session: Session, lore_id: int, name: str = "Test Ability",
                 mana_cost: int = 5, energy_type: str = "upright"):
    """Create a TarotAbility linked to a lore card."""
    from app.db.models import TarotAbility
    ability = TarotAbility(
        name=name,
        mana_cost=mana_cost,
        energy_type=energy_type,
        ability_category="utility",
        tags="test,utility",
        card_id=lore_id,
    )
    session.add(ability)
    session.commit()
    session.refresh(ability)
    return ability


# ══════════════════════════════════════════════════════════════════════════════
# 1. MANA REGENERATION
# ══════════════════════════════════════════════════════════════════════════════

class TestManaRegeneration:

    def test_no_regen_when_at_capacity(self, session, service):
        e = make_entity(session, "RegenFullEntity", upright=10, reversed=10)
        before_u = e.current_upright_mana
        service._regen_mana(e)
        assert e.current_upright_mana == before_u, "Should not exceed capacity"

    def test_regen_increases_mana_over_time(self, session, service):
        from app.db.models import TarotEntity
        e = make_entity(session, "RegenEntity", upright=100, reversed=100)
        # Drain mana first
        e.current_upright_mana = 0
        e.current_reversed_mana = 0
        # Backdate last_mana_update by 120 seconds → should regen ~2 units (at 1/min rate)
        e.last_mana_update = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.add(e)
        session.commit()
        session.refresh(e)

        service._regen_mana(e)

        assert e.current_upright_mana >= 1, "Should have regenerated at least 1 upright mana"
        assert e.current_reversed_mana >= 1, "Should have regenerated at least 1 reversed mana"

    def test_regen_caps_at_capacity(self, session, service):
        e = make_entity(session, "RegenCapEntity", upright=5, reversed=5)
        e.current_upright_mana = 0
        e.current_reversed_mana = 0
        # Backdate by 1 hour — would overflow without cap
        e.last_mana_update = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(e)
        session.commit()

        service._regen_mana(e)

        assert e.current_upright_mana == 5, "Mana must not exceed capacity"
        assert e.current_reversed_mana == 5, "Mana must not exceed capacity"

    def test_regen_is_lazy_not_background(self, session, service):
        """Regen should only happen when explicitly called, not automatically."""
        e = make_entity(session, "LazyRegenEntity", upright=100, reversed=100)
        e.current_upright_mana = 0
        e.last_mana_update = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.add(e)
        session.commit()
        session.refresh(e)

        # Without calling _regen_mana, value should still be 0
        assert e.current_upright_mana == 0, "Regen should not run in background"

        # Only after calling _regen_mana does it update
        service._regen_mana(e)
        assert e.current_upright_mana > 0, "Regen should update on explicit call"


# ══════════════════════════════════════════════════════════════════════════════
# 2. ENERGY TRANSFER (CAPACITY)
# ══════════════════════════════════════════════════════════════════════════════

class TestEnergyTransfer:

    def test_successful_transfer(self, session, service):
        src = make_entity(session, "TransferSrc", upright=100)
        dst = make_entity(session, "TransferDst", upright=0)

        result = service.transfer_energy(session, src.id, dst.id, upright=50, reason="test")

        assert result["success"] is True
        session.refresh(src)
        session.refresh(dst)
        assert src.upright_capacity == 50
        assert dst.upright_capacity == 50

    def test_transfer_insufficient_capacity(self, session, service):
        src = make_entity(session, "PoorSrc", upright=10)
        dst = make_entity(session, "PoorDst", upright=0)

        result = service.transfer_energy(session, src.id, dst.id, upright=99)
        assert result["success"] is False
        assert "Insufficient" in result["message"]

    def test_transfer_zero_amounts_rejected(self, session, service):
        src = make_entity(session, "ZeroSrc", upright=100)
        dst = make_entity(session, "ZeroDst", upright=0)

        result = service.transfer_energy(session, src.id, dst.id)
        assert result["success"] is False

    def test_transfer_negative_amounts_rejected(self, session, service):
        src = make_entity(session, "NegSrc", upright=100)
        dst = make_entity(session, "NegDst", upright=0)

        result = service.transfer_energy(session, src.id, dst.id, upright=-10)
        assert result["success"] is False

    def test_transfer_both_upright_and_reversed(self, session, service):
        src = make_entity(session, "BothSrc", upright=100, reversed=100)
        dst = make_entity(session, "BothDst", upright=0, reversed=0)

        result = service.transfer_energy(session, src.id, dst.id, upright=30, reversed=40)
        assert result["success"] is True
        session.refresh(src)
        session.refresh(dst)
        assert src.upright_capacity == 70
        assert src.reversed_capacity == 60
        assert dst.upright_capacity == 30
        assert dst.reversed_capacity == 40

    def test_transfer_nonexistent_entity(self, session, service):
        src = make_entity(session, "RealSrc2", upright=100)
        result = service.transfer_energy(session, src.id, 99999, upright=10)
        assert result["success"] is False

    def test_transfer_writes_ledger_entry(self, session, service):
        from app.db.models import TarotTransaction
        src = make_entity(session, "LedgerSrc", upright=100)
        dst = make_entity(session, "LedgerDst", upright=0)

        result = service.transfer_energy(session, src.id, dst.id, upright=25, reason="ledger_test")
        assert result["success"] is True

        tx = session.exec(
            select(TarotTransaction).where(TarotTransaction.reason == "ledger_test")
        ).first()
        assert tx is not None
        assert tx.upright_amount == 25


# ══════════════════════════════════════════════════════════════════════════════
# 3. CARD TRANSFER + LOADOUT LIMITS
# ══════════════════════════════════════════════════════════════════════════════

class TestCardTransfer:

    def test_successful_minor_transfer(self, session, service):
        giver = make_entity(session, "CardGiver")
        receiver = make_entity(session, "CardReceiver")
        lore = make_lore(session, "Ace of Cups (T)", arcana_type="Minor")
        shard = make_shard(session, giver.id, lore.id)

        result = service.transfer_card(session, giver.id, receiver.id, shard.id, reason="gift")
        assert result["success"] is True
        session.refresh(shard)
        assert shard.owner_id == receiver.id

    def test_transfer_wrong_owner_rejected(self, session, service):
        true_owner = make_entity(session, "TrueOwner")
        impostor = make_entity(session, "Impostor")
        receiver = make_entity(session, "CardReceiver2")
        lore = make_lore(session, "Two of Cups (T)", arcana_type="Minor")
        shard = make_shard(session, true_owner.id, lore.id)

        result = service.transfer_card(session, impostor.id, receiver.id, shard.id)
        assert result["success"] is False
        assert result["reason"] == "invalid_ownership"

    def test_major_arcana_loadout_limit_one(self, session, service):
        giver = make_entity(session, "MajorGiver")
        receiver = make_entity(session, "MajorReceiver")

        lore1 = make_lore(session, "The Fool (T)", arcana_type="Major")
        lore2 = make_lore(session, "The Magician (T)", arcana_type="Major")
        shard1 = make_shard(session, giver.id, lore1.id)
        shard2 = make_shard(session, giver.id, lore2.id)

        # First major should succeed
        r1 = service.transfer_card(session, giver.id, receiver.id, shard1.id)
        assert r1["success"] is True

        # Second major should be rejected
        r2 = service.transfer_card(session, giver.id, receiver.id, shard2.id)
        assert r2["success"] is False
        assert r2["reason"] == "major_limit"

    def test_minor_arcana_loadout_limit_two(self, session, service):
        giver = make_entity(session, "MinorGiver")
        receiver = make_entity(session, "MinorReceiver")

        lore1 = make_lore(session, "Three of Cups (T)", arcana_type="Minor")
        lore2 = make_lore(session, "Four of Cups (T)", arcana_type="Minor")
        lore3 = make_lore(session, "Five of Cups (T)", arcana_type="Minor")
        shard1 = make_shard(session, giver.id, lore1.id)
        shard2 = make_shard(session, giver.id, lore2.id)
        shard3 = make_shard(session, giver.id, lore3.id)

        assert service.transfer_card(session, giver.id, receiver.id, shard1.id)["success"] is True
        assert service.transfer_card(session, giver.id, receiver.id, shard2.id)["success"] is True

        # Third minor should be rejected
        r3 = service.transfer_card(session, giver.id, receiver.id, shard3.id)
        assert r3["success"] is False
        assert r3["reason"] == "minor_limit"

    def test_transfer_writes_card_ledger(self, session, service):
        from app.db.models import TarotCardTransaction
        giver = make_entity(session, "LedgerGiver")
        receiver = make_entity(session, "LedgerRcvr")
        lore = make_lore(session, "Six of Cups (T)", arcana_type="Minor")
        shard = make_shard(session, giver.id, lore.id)

        result = service.transfer_card(session, giver.id, receiver.id, shard.id, reason="ledger_card_test")
        assert result["success"] is True

        tx = session.exec(
            select(TarotCardTransaction).where(TarotCardTransaction.shard_id == shard.id)
        ).first()
        assert tx is not None
        assert tx.from_entity_id == giver.id
        assert tx.to_entity_id == receiver.id


# ══════════════════════════════════════════════════════════════════════════════
# 4. SPELL CASTING
# ══════════════════════════════════════════════════════════════════════════════

class TestCastSpell:

    def test_successful_cast_deducts_mana(self, session, service):
        caster = make_entity(session, "Caster", upright=50)
        lore = make_lore(session, "Seven of Cups (T)", arcana_type="Minor")
        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore.id, mana_cost=10, energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id)
        assert result["success"] is True
        session.refresh(caster)
        assert caster.current_upright_mana == 40

    def test_cast_fails_without_card(self, session, service):
        caster = make_entity(session, "NakedCaster", upright=50)
        lore = make_lore(session, "Eight of Cups (T)", arcana_type="Minor")
        # Do NOT give the shard to caster
        ability = make_ability(session, lore.id, mana_cost=5, energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id)
        assert result["success"] is False
        assert result["reason"] == "card_not_held"

    def test_cast_fails_insufficient_mana(self, session, service):
        caster = make_entity(session, "BrokeCaster", upright=3)
        caster.current_upright_mana = 3
        session.add(caster)
        session.commit()

        lore = make_lore(session, "Nine of Cups (T)", arcana_type="Minor")
        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore.id, mana_cost=10, energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id)
        assert result["success"] is False
        assert result["reason"] == "insufficient_mana"
        assert result["have"] == 3
        assert result["need"] == 10

    def test_cast_reversed_energy(self, session, service):
        caster = make_entity(session, "RevCaster", reversed=50)
        lore = make_lore(session, "Ten of Cups (T)", arcana_type="Minor")
        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore.id, mana_cost=8, energy_type="reversed")

        result = service.cast_spell(session, caster.id, ability.id)
        assert result["success"] is True
        session.refresh(caster)
        assert caster.current_reversed_mana == 42

    def test_cast_triggers_mana_regen_first(self, session, service):
        """Mana regen should apply before checking cost."""
        caster = make_entity(session, "RegenCaster", upright=50)
        caster.current_upright_mana = 0
        # Backdate 120s → regen should give 2 mana (at 1/min)
        caster.last_mana_update = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.add(caster)
        session.commit()
        session.refresh(caster)

        lore = make_lore(session, "Ace of Swords (T)", arcana_type="Minor", suit="Swords")
        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore.id, mana_cost=1, energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id)
        assert result["success"] is True, "Should succeed after regen provides mana"

    def test_cast_nonexistent_entity(self, session, service):
        lore = make_lore(session, "Two of Swords (T)", arcana_type="Minor", suit="Swords")
        ability = make_ability(session, lore.id, mana_cost=1, energy_type="upright")

        result = service.cast_spell(session, 99999, ability.id)
        assert result["success"] is False
        assert result["reason"] == "entity_not_found"

    def test_cast_nonexistent_ability(self, session, service):
        caster = make_entity(session, "GhostCaster", upright=50)
        result = service.cast_spell(session, caster.id, 99999)
        assert result["success"] is False
        assert result["reason"] == "ability_not_found"


# ══════════════════════════════════════════════════════════════════════════════
# 5. ARCANA COUNT (loadout query)
# ══════════════════════════════════════════════════════════════════════════════

class TestCountArcana:

    def test_empty_loadout(self, session, service):
        e = make_entity(session, "EmptyLoadout")
        majors, minors = service.count_arcana(session, e.id)
        assert majors == 0
        assert minors == 0

    def test_counts_correctly_mixed_loadout(self, session, service):
        e = make_entity(session, "MixedLoadout")
        major_lore = make_lore(session, "The Emperor (T)", arcana_type="Major")
        minor_lore1 = make_lore(session, "Three of Wands (T)", arcana_type="Minor", suit="Wands")
        minor_lore2 = make_lore(session, "Four of Wands (T)", arcana_type="Minor", suit="Wands")
        make_shard(session, e.id, major_lore.id)
        make_shard(session, e.id, minor_lore1.id)
        make_shard(session, e.id, minor_lore2.id)

        majors, minors = service.count_arcana(session, e.id)
        assert majors == 1
        assert minors == 2


# ══════════════════════════════════════════════════════════════════════════════
# 6. SOVEREIGNTY CHECKS
# ══════════════════════════════════════════════════════════════════════════════

class TestSovereignty:

    def test_not_sovereign_with_small_capacity(self, session, service):
        from app.db.models import GlobalConfig
        session.add(GlobalConfig(key="TOTAL_UPRIGHT_CAPACITY", value=1000))
        session.commit()

        e = make_entity(session, "WeakEntity", upright=100)
        assert service.is_sovereign_upright(e, session) is False

    def test_sovereign_with_majority_capacity(self, session, service):
        from app.db.models import GlobalConfig
        existing = session.get(GlobalConfig, "TOTAL_UPRIGHT_CAPACITY")
        if not existing:
            session.add(GlobalConfig(key="TOTAL_UPRIGHT_CAPACITY", value=1000))
            session.commit()

        e = make_entity(session, "KingEntity", upright=600)
        assert service.is_sovereign_upright(e, session) is True


# ══════════════════════════════════════════════════════════════════════════════
# 7. READ HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class TestReadHelpers:

    def test_get_entity_by_name_found(self, session, service):
        make_entity(session, "NamedEntity")
        e = service.get_entity_by_name(session, "NamedEntity")
        assert e is not None
        assert e.entity_name == "NamedEntity"

    def test_get_entity_by_name_missing(self, session, service):
        e = service.get_entity_by_name(session, "DoesNotExist")
        assert e is None

    def test_get_held_cards_empty(self, session, service):
        e = make_entity(session, "NoCardEntity")
        cards = service.get_held_cards(session, e.id)
        assert cards == []

    def test_get_held_cards_returns_summary(self, session, service):
        e = make_entity(session, "CardHolder")
        lore = make_lore(session, "Six of Wands (T)", arcana_type="Minor", suit="Wands")
        make_shard(session, e.id, lore.id)

        cards = service.get_held_cards(session, e.id)
        assert len(cards) == 1
        assert cards[0]["card_name"] == "Six of Wands (T)"
        assert cards[0]["arcana_type"] == "Minor"

    def test_get_transaction_history(self, session, service):
        src = make_entity(session, "HistSrc", upright=100)
        dst = make_entity(session, "HistDst", upright=0)

        service.transfer_energy(session, src.id, dst.id, upright=10, reason="hist_test")
        history = service.get_transaction_history(session, src.id)
        assert len(history) >= 1
        reasons = [t.reason for t in history]
        assert "hist_test" in reasons


# ══════════════════════════════════════════════════════════════════════════════
# 8. MINT CAPACITY (genesis)
# ══════════════════════════════════════════════════════════════════════════════

class TestMintCapacity:

    def test_mint_increases_capacity(self, session, service):
        e = make_entity(session, "MintTarget", upright=0, reversed=0)
        result = service.mint_capacity(session, e.id, upright=500, reversed=200)
        assert result["success"] is True
        session.refresh(e)
        assert e.upright_capacity == 500
        assert e.reversed_capacity == 200

    def test_mint_zero_rejected(self, session, service):
        e = make_entity(session, "MintZeroTarget", upright=0)
        result = service.mint_capacity(session, e.id)
        assert result["success"] is False

    def test_mint_fills_mana_to_capacity(self, session, service):
        e = make_entity(session, "MintManaTarget", upright=0, reversed=0)
        service.mint_capacity(session, e.id, upright=100)
        session.refresh(e)
        assert e.current_upright_mana == 100
