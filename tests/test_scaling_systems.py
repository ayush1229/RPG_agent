"""
tests/test_scaling_systems.py

Tests for:
- Shard Power Multiplier
- Health Scaling
- Energy Alignment System
- Arcana-Specific Modifiers
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    from app.db.models import (  # noqa: F401
        CombatParticipant, CombatState, GlobalConfig, InventoryItem,
        Location, StatusEffect, TarotAbility, TarotCardLore,
        TarotCardTransaction, TarotEntity, TarotShard, TarotTransaction,
    )
    SQLModel.metadata.create_all(TEST_ENGINE)
    yield


@pytest.fixture()
def session():
    with Session(TEST_ENGINE) as s:
        yield s
        s.rollback()


@pytest.fixture()
def service():
    from app.db.service import TarotService
    return TarotService()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_entity(session, name, upright=0, reversed=0, hp=100):
    from app.db.models import TarotEntity
    e = TarotEntity(
        entity_name=name,
        upright_capacity=upright,
        reversed_capacity=reversed,
        current_health=hp,
    )
    e.current_upright_mana = e.max_upright_mana
    e.current_reversed_mana = e.max_reversed_mana
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def make_lore(session, name, arcana_type="Minor", suit="Cups"):
    from app.db.models import TarotCardLore
    existing = session.exec(select(TarotCardLore).where(TarotCardLore.name == name)).first()
    if existing:
        return existing
    lore = TarotCardLore(
        name=name, arcana_type=arcana_type,
        suit=suit if arcana_type == "Minor" else None,
        upright_meaning="u", reversed_meaning="r",
        magical_manifestation="test", personality_archetype="test",
        core_themes="test", power_domains="test", behavioral_bias="test",
    )
    session.add(lore)
    session.commit()
    session.refresh(lore)
    return lore


def make_shard(session, owner_id, lore_id):
    from app.db.models import TarotShard
    s = TarotShard(owner_id=owner_id, lore_id=lore_id)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def make_ability(session, card_lore, base_damage=None, base_heal=None,
                 mana_cost=5, scaling=1.0, energy_type="upright", category="combat"):
    from app.db.models import TarotAbility
    a = TarotAbility(
        name=f"Ability_{id(card_lore)}_{base_damage}",
        mana_cost=mana_cost,
        energy_type=energy_type,
        ability_category=category,
        description="test",
        base_damage=base_damage,
        base_heal=base_heal,
        scaling_factor=scaling,
        card_id=card_lore.id,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# =============================================================================
# SHARD POWER MULTIPLIER
# =============================================================================

class TestPowerMultiplier:

    def test_zero_energy_gives_no_bonus(self, session, service):
        e = make_entity(session, "ZeroShard", upright=0, reversed=0)
        assert e.energy_shard_count == 0
        assert e.shard_power_multiplier == pytest.approx(1.0)
        assert service.compute_power_multiplier(e) == pytest.approx(1.0)

    def test_two_energy_gives_ten_percent_bonus(self, session, service):
        e = make_entity(session, "TwoShard", upright=1, reversed=1)
        assert e.energy_shard_count == 2
        # 1 + 2*0.05 = 1.10
        assert e.shard_power_multiplier == pytest.approx(1.10)

    def test_ten_energy_hits_cap(self, session, service):
        e = make_entity(session, "TenShard", upright=5, reversed=5)
        assert e.energy_shard_count == 10
        # 1 + 10*0.05 = 1.5 (exactly at cap)
        assert e.shard_power_multiplier == pytest.approx(1.50)

    def test_large_energy_capped_at_1_5(self, session, service):
        e = make_entity(session, "LargeShard", upright=500, reversed=500)
        # 1 + 1000*0.05 would be 51 — capped at 1.5
        assert e.shard_power_multiplier == pytest.approx(1.50)

    def test_power_mult_scales_damage(self, session, service):
        """
        Caster with 4 energy (upright=2, reversed=2) → mult = 1 + 4*0.05 = 1.20
        base_damage=10, mana_cost=0, scaling=1.0 → raw=10 → after mult: int(10*1.20)=12
        """
        lore = make_lore(session, "MultDmgLore", arcana_type="Minor")
        caster = make_entity(session, "MultDmgCaster", upright=2, reversed=2)
        target = make_entity(session, "MultDmgTarget", upright=0, reversed=0)

        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore, base_damage=10, mana_cost=0, scaling=1.0)

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        assert result["damage"] == 12   # 10 * 1.20 = 12.0

    def test_power_mult_scales_healing(self, session, service):
        """
        Caster with 4 energy → mult=1.20
        base_heal=10, mana_cost=0, scaling=1.0 → int(10*1.20)=12
        """
        lore = make_lore(session, "MultHealLore", arcana_type="Minor")
        caster = make_entity(session, "MultHealCaster", upright=2, reversed=2)
        target = make_entity(session, "MultHealTarget", upright=0, reversed=0)
        target.current_health = 50
        session.add(target)
        session.commit()
        session.refresh(target)

        make_shard(session, caster.id, lore.id)
        ability = make_ability(session, lore, base_heal=10, mana_cost=0, scaling=1.0,
                               energy_type="upright", category="healing")

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        assert result["healing"] == 12   # 10 * 1.20


# =============================================================================
# HEALTH SCALING
# =============================================================================

class TestHealthScaling:

    def test_base_max_health_is_100(self, session):
        e = make_entity(session, "BaseHP", upright=0, reversed=0)
        assert e.max_health == 100      # 100 + 0*10

    def test_max_health_increases_with_energy(self, session):
        e = make_entity(session, "ScaledHP", upright=5, reversed=5)
        assert e.energy_shard_count == 10
        assert e.max_health == 200      # 100 + 10*10

    def test_max_health_uses_both_capacities(self, session):
        e = make_entity(session, "BothCapHP", upright=3, reversed=7)
        assert e.energy_shard_count == 10
        assert e.max_health == 200

    def test_max_health_updates_when_capacity_changes(self, session, service):
        """
        Minting energy increases max_health for the entity.
        """
        e = make_entity(session, "GrowingHP", upright=0, reversed=0)
        assert e.max_health == 100
        service.mint_capacity(session, e.id, upright=5)
        session.refresh(e)
        # Now upright=5 → energy_shard_count=5 → max_health = 150
        assert e.max_health == 150

    def test_heal_clamps_at_dynamic_max(self, session, service):
        """
        Entity with 10 energy has max_health=200.
        Healing past 200 should clamp.
        """
        e = make_entity(session, "DynClamp", upright=5, reversed=5, hp=150)
        e.current_health = 150
        session.add(e)
        session.commit()
        session.refresh(e)
        assert e.max_health == 200

        restored = service._apply_heal(e, 9999)
        assert e.current_health == 200
        assert restored == 50


# =============================================================================
# ENERGY ALIGNMENT SYSTEM
# =============================================================================

class TestEnergyAlignment:

    def test_dominant_energy_upright_when_equal(self, session):
        e = make_entity(session, "EqualAlign", upright=5, reversed=5)
        assert e.dominant_energy == "upright"

    def test_dominant_energy_reversed_when_more_reversed(self, session):
        e = make_entity(session, "ReversedDom", upright=3, reversed=7)
        assert e.dominant_energy == "reversed"

    def test_dominant_energy_upright_when_more_upright(self, session):
        e = make_entity(session, "UprightDom", upright=8, reversed=2)
        assert e.dominant_energy == "upright"

    def test_aligned_cast_no_penalty(self, session, service):
        """
        Upright caster using upright ability → alignment_mult = 1.0, no penalty.
        """
        lore = make_lore(session, "AlignLore", arcana_type="Minor")
        # upright dominant (upright > reversed)
        caster = make_entity(session, "AlignCaster", upright=5, reversed=0)
        target = make_entity(session, "AlignTarget", upright=0, reversed=0)
        make_shard(session, caster.id, lore.id)
        # upright ability, caster dominant = upright → aligned
        ability = make_ability(session, lore, base_damage=10, mana_cost=0, scaling=1.0,
                               energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        # power_mult = min(1.5, 1 + 5*0.05) = 1.25; alignment = 1.0
        assert result["damage"] == 12   # int(10 * 1.25)

    def test_misaligned_cast_applies_penalty(self, session, service):
        """
        Reversed caster using upright ability → alignment_mult = 0.75.
        """
        lore = make_lore(session, "MisalignLore", arcana_type="Minor")
        # reversed dominant
        caster = make_entity(session, "MisalignCaster", upright=0, reversed=5)
        target = make_entity(session, "MisalignTarget", upright=0, reversed=0)
        make_shard(session, caster.id, lore.id)
        # upright ability, caster dominant = reversed → misaligned
        ability = make_ability(session, lore, base_damage=10, mana_cost=0, scaling=1.0,
                               energy_type="upright")

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        # power_mult = 1.25; alignment_mult = 0.75
        # raw = 10 * 1.25 * 0.75 = 9.375 → int = 9
        assert result["damage"] == 9

    def test_get_dominant_energy_helper(self, session, service):
        e = make_entity(session, "DomHelper", upright=3, reversed=7)
        assert service.get_dominant_energy(e) == "reversed"


# =============================================================================
# ARCANA-SPECIFIC MODIFIERS
# =============================================================================

class TestArcanaModifiers:

    def test_no_major_arcana_gives_empty_mods(self, session, service):
        e = make_entity(session, "NoMajor", upright=5)
        mods = service.get_arcana_modifiers(session, e.id)
        assert mods == {}

    def test_magician_gives_damage_bonus(self, session, service):
        """Holding 'The Magician' grants damage_bonus=0.10."""
        lore = make_lore(session, "The Magician", arcana_type="Major", suit="Major")
        e = make_entity(session, "MagicianHolder", upright=5)
        make_shard(session, e.id, lore.id)

        mods = service.get_arcana_modifiers(session, e.id)
        assert mods.get("damage_bonus") == pytest.approx(0.10)

    def test_star_gives_healing_bonus(self, session, service):
        """Holding 'The Star' grants healing_bonus=0.15."""
        lore = make_lore(session, "The Star", arcana_type="Major", suit="Major")
        e = make_entity(session, "StarHolder", upright=5)
        make_shard(session, e.id, lore.id)

        mods = service.get_arcana_modifiers(session, e.id)
        assert mods.get("healing_bonus") == pytest.approx(0.15)

    def test_arcana_damage_bonus_applies_in_combat(self, session, service):
        """
        'The Magician' grants +10% damage.
        Caster: 0 energy (mult=1.0), Magician card → damage_bonus=0.10.
        base_damage=10, mana_cost=0, scaling=1.0.
        Expected: int(10 * 1.0 * 1.10) = 11.
        """
        # Ability must be on a Minor card (caster needs that card)
        minor_lore = make_lore(session, "TestMinorForMagician", arcana_type="Minor")
        major_lore = make_lore(session, "The Magician", arcana_type="Major", suit="Major")

        caster = make_entity(session, "MagicianCombatCaster", upright=0, reversed=0)
        target = make_entity(session, "MagicianCombatTarget", upright=0, reversed=0)

        # Grant minor card (for ability) AND major card (for arcana bonus)
        make_shard(session, caster.id, minor_lore.id)
        make_shard(session, caster.id, major_lore.id)

        ability = make_ability(session, minor_lore, base_damage=10, mana_cost=0, scaling=1.0)

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        # 10 * 1.0 (power) * 1.10 (magician) * 1.0 (aligned) = 11
        assert result["damage"] == 11

    def test_arcana_healing_bonus_applies(self, session, service):
        """
        'The Star' grants +15% healing.
        Caster: 0 energy (mult=1.0), base_heal=10, mana_cost=0 → int(10*1.15)=11.
        """
        minor_lore = make_lore(session, "TestMinorForStar", arcana_type="Minor")
        major_lore = make_lore(session, "The Star", arcana_type="Major", suit="Major")

        caster = make_entity(session, "StarCombatCaster", upright=0, reversed=0)
        target = make_entity(session, "StarCombatTarget", upright=0, reversed=0)
        target.current_health = 50
        session.add(target)
        session.commit()
        session.refresh(target)

        make_shard(session, caster.id, minor_lore.id)
        make_shard(session, caster.id, major_lore.id)

        ability = make_ability(session, minor_lore, base_heal=10, mana_cost=0, scaling=1.0,
                               category="healing")

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        # 10 * 1.0 (power) * 1.15 (star) * 1.0 (aligned) = 11 (int)
        assert result["healing"] == 11

    def test_minor_arcana_gives_no_mods(self, session, service):
        """Minor Arcana cards do NOT appear in ARCANA_EFFECTS — no mods."""
        lore = make_lore(session, "Three of Cups", arcana_type="Minor")
        e = make_entity(session, "MinorOnlyHolder", upright=5)
        make_shard(session, e.id, lore.id)

        mods = service.get_arcana_modifiers(session, e.id)
        assert mods == {}

    def test_combined_power_mult_and_arcana(self, session, service):
        """
        Caster: 4 energy → mult=1.20. Holds 'Strength' → +10% damage.
        base_damage=10, mana_cost=0 → int(10 * 1.20 * 1.10) = int(13.2) = 13.
        """
        minor_lore = make_lore(session, "TestMinorForStrength", arcana_type="Minor")
        major_lore = make_lore(session, "Strength", arcana_type="Major", suit="Major")

        caster = make_entity(session, "StrengthComboCaster", upright=2, reversed=2)
        target = make_entity(session, "StrengthComboTarget", upright=0, reversed=0)

        make_shard(session, caster.id, minor_lore.id)
        make_shard(session, caster.id, major_lore.id)

        ability = make_ability(session, minor_lore, base_damage=10, mana_cost=0, scaling=1.0)

        result = service.cast_spell(session, caster.id, ability.id, target_id=target.id)
        assert result["success"] is True
        # 10 * 1.20 (power) * 1.10 (strength) * 1.0 (aligned) = 13.2 → int = 13
        assert result["damage"] == 13
