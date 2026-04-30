"""
tests/test_progression_systems.py
===================================
Tests for:
  1. XP & Level system (xp_required, add_xp, max_health, milestone items)
  2. Inventory system (item_type, rarity, value, effect_type)
  3. Quest system (create, assign, advance, complete, XP scaling)
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    InventoryItem,
    Quest,
    QuestProgress,
    TarotEntity,
    calculate_xp_reward,
    xp_required,
)
from app.db.service import TarotService

# ── In-memory test engine ──────────────────────────────────────────────────────
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def svc():
    return TarotService()


@pytest.fixture
def entity(session):
    e = TarotEntity(entity_name="TestHero", level=1, current_xp=0)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


# ─────────────────────────────────────────────────────────────────────────────
# 1. XP FORMULA
# ─────────────────────────────────────────────────────────────────────────────
class TestXPFormula:
    def test_level_1_is_100(self):
        assert xp_required(1) == 100

    def test_level_2_gt_level_1(self):
        assert xp_required(2) > xp_required(1)

    def test_strictly_increasing(self):
        for lvl in range(1, 99):
            assert xp_required(lvl + 1) > xp_required(lvl)

    def test_level_10(self):
        assert xp_required(10) == int(100 * (10 ** 1.5))

    def test_level_100(self):
        assert xp_required(100) == int(100 * (100 ** 1.5))

    def test_no_negative(self):
        for lvl in range(1, 101):
            assert xp_required(lvl) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. XP SERVICE
# ─────────────────────────────────────────────────────────────────────────────
class TestAddXP:
    def test_add_small_xp_no_levelup(self, session, svc, entity):
        result = svc.add_xp(session, entity.id, 50)
        assert result["success"] is True
        assert result["levels_gained"] == 0
        assert result["new_level"] == 1
        assert result["new_xp"] == 50
        assert result["items_granted"] == []

    def test_add_enough_xp_to_level_up(self, session, svc, entity):
        needed = xp_required(1)   # 100
        result = svc.add_xp(session, entity.id, needed)
        assert result["success"] is True
        assert result["levels_gained"] == 1
        assert result["new_level"] == 2
        assert result["new_xp"] == 0

    def test_level_up_increases_max_health(self, session, svc, entity):
        initial_hp = entity.max_health
        svc.add_xp(session, entity.id, xp_required(1))
        session.refresh(entity)
        assert entity.max_health == initial_hp + 5
        assert entity.health_bonus_from_levels == 5

    def test_multiple_level_ups_in_one_call(self, session, svc, entity):
        # Give enough XP to reach level 3
        total = xp_required(1) + xp_required(2)
        result = svc.add_xp(session, entity.id, total)
        assert result["levels_gained"] == 2
        assert result["new_level"] == 3

    def test_milestone_item_at_level_5(self, session, svc, entity):
        """Level 1→5 should grant a milestone item."""
        total_xp = sum(xp_required(lvl) for lvl in range(1, 5))
        result = svc.add_xp(session, entity.id, total_xp)
        assert result["new_level"] == 5
        assert len(result["items_granted"]) == 1
        assert result["items_granted"][0] == "Minor Mana Vial"

    def test_milestone_item_is_in_inventory(self, session, svc, entity):
        total_xp = sum(xp_required(lvl) for lvl in range(1, 5))
        svc.add_xp(session, entity.id, total_xp)
        items = session.exec(
            select(InventoryItem).where(InventoryItem.owner_id == entity.id)
        ).all()
        assert len(items) == 1
        assert items[0].name == "Minor Mana Vial"

    def test_no_xp_overflow_at_max_level(self, session, svc, entity):
        """At level 100 XP should clamp to 0."""
        entity.level = 99
        entity.current_xp = 0
        session.add(entity)
        session.commit()
        result = svc.add_xp(session, entity.id, 10_000_000)
        assert result["new_level"] == 100
        assert result["new_xp"] == 0

    def test_invalid_xp_amount(self, session, svc, entity):
        result = svc.add_xp(session, entity.id, 0)
        assert result["success"] is False
        assert result["reason"] == "xp_must_be_positive"

    def test_invalid_xp_negative(self, session, svc, entity):
        result = svc.add_xp(session, entity.id, -50)
        assert result["success"] is False

    def test_entity_not_found(self, session, svc):
        result = svc.add_xp(session, 99999, 100)
        assert result["success"] is False
        assert result["reason"] == "entity_not_found"

    def test_xp_info(self, session, svc, entity):
        svc.add_xp(session, entity.id, 50)
        info = svc.get_xp_info(session, entity.id)
        assert info["success"] is True
        assert info["level"] == 1
        assert info["current_xp"] == 50
        assert info["xp_to_next_level"] == xp_required(1)
        assert 0 < info["progress_pct"] < 100

    def test_xp_info_max_level(self, session, svc, entity):
        entity.level = 100
        session.add(entity)
        session.commit()
        info = svc.get_xp_info(session, entity.id)
        assert info["xp_to_next_level"] == 0
        assert info["progress_pct"] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. INVENTORY ITEM MODEL
# ─────────────────────────────────────────────────────────────────────────────
class TestInventoryItem:
    def test_create_consumable(self, session, entity):
        item = InventoryItem(
            owner_id=entity.id,
            name="Health Potion",
            description="Heals 50 HP",
            item_type="consumable",
            rarity="common",
            value=10,
            item_effect="heal",
            effect_type="heal",
            effect_value=50,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.id is not None
        assert item.item_type == "consumable"
        assert item.rarity == "common"
        assert item.value == 10
        assert item.effect_type == "heal"
        assert item.item_effect == "heal"  # legacy field preserved

    def test_create_artifact(self, session, entity):
        item = InventoryItem(
            owner_id=entity.id,
            name="Fool's Stone",
            item_type="artifact",
            rarity="legendary",
            value=5000,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.item_type == "artifact"
        assert item.rarity == "legendary"
        assert item.item_effect is None
        assert item.effect_type is None

    def test_quest_item_value_zero(self, session, entity):
        item = InventoryItem(
            owner_id=entity.id,
            name="Ancient Key",
            item_type="quest",
            rarity="epic",
            value=0,
        )
        session.add(item)
        session.commit()
        assert item.value == 0

    def test_defaults(self, session, entity):
        item = InventoryItem(owner_id=entity.id, name="Basic Item")
        session.add(item)
        session.commit()
        assert item.item_type == "consumable"
        assert item.rarity == "common"
        assert item.quantity == 1
        assert item.value == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. XP REWARD SCALING
# ─────────────────────────────────────────────────────────────────────────────
class TestXPRewardScaling:
    def test_easy_multiplier(self):
        assert calculate_xp_reward(100, "easy", 1) == int(100 * 1.0 * 1.05)

    def test_elite_multiplier(self):
        val = calculate_xp_reward(100, "elite", 1)
        assert val == int(100 * 4.0 * 1.05)

    def test_scales_with_player_level(self):
        low = calculate_xp_reward(100, "hard", 1)
        high = calculate_xp_reward(100, "hard", 50)
        assert high > low

    def test_always_at_least_1(self):
        assert calculate_xp_reward(0, "easy", 1) >= 1

    def test_unknown_difficulty_defaults_to_1x(self):
        base = calculate_xp_reward(100, "unknown", 1)
        assert base == max(1, int(100 * 1.0 * 1.05))


# ─────────────────────────────────────────────────────────────────────────────
# 5. QUEST SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
class TestQuestSystem:
    def test_create_quest(self, session, svc):
        result = svc.create_quest(
            session, name="Test Quest", description="A test.",
            quest_type="side", difficulty="easy",
            required_level=1, xp_reward=100,
        )
        assert result["success"] is True
        assert result["quest_id"] is not None

    def test_create_quest_idempotent(self, session, svc):
        svc.create_quest(session, name="Unique", description="X")
        result = svc.create_quest(session, name="Unique", description="X")
        assert result["success"] is False
        assert result["reason"] == "quest_already_exists"

    def test_invalid_difficulty(self, session, svc):
        result = svc.create_quest(session, name="Bad", description=".", difficulty="insane")
        assert result["success"] is False
        assert result["reason"] == "invalid_difficulty"

    def test_invalid_quest_type(self, session, svc):
        result = svc.create_quest(session, name="Bad2", description=".", quest_type="mini")
        assert result["success"] is False
        assert result["reason"] == "invalid_quest_type"

    def test_assign_quest(self, session, svc, entity):
        q = svc.create_quest(session, name="Find Herbs", description="Gather herbs.")
        result = svc.assign_quest(session, entity.id, q["quest_id"])
        assert result["success"] is True
        assert result["quest_name"] == "Find Herbs"

    def test_assign_quest_level_too_low(self, session, svc, entity):
        q = svc.create_quest(
            session, name="Elite Mission", description="Hard quest.",
            difficulty="elite", required_level=50,
        )
        result = svc.assign_quest(session, entity.id, q["quest_id"])
        assert result["success"] is False
        assert result["reason"] == "level_too_low"

    def test_assign_quest_duplicate_rejected(self, session, svc, entity):
        q = svc.create_quest(session, name="Dup Quest", description=".")
        svc.assign_quest(session, entity.id, q["quest_id"])
        result = svc.assign_quest(session, entity.id, q["quest_id"])
        assert result["success"] is False
        assert result["reason"] == "already_assigned"

    def test_advance_quest(self, session, svc, entity):
        q = svc.create_quest(session, name="Kill 3 Wolves", description=".", xp_reward=100)
        svc.assign_quest(session, entity.id, q["quest_id"], goal=3)
        result = svc.advance_quest(session, entity.id, q["quest_id"], increment=1)
        assert result["success"] is True
        assert result["progress"] == 1
        assert result["completed"] is False

    def test_advance_quest_completes_at_goal(self, session, svc, entity):
        q = svc.create_quest(session, name="Kill 1 Wolf", description=".", xp_reward=50)
        svc.assign_quest(session, entity.id, q["quest_id"], goal=1)
        result = svc.advance_quest(session, entity.id, q["quest_id"], increment=1)
        assert result["success"] is True
        assert result["completed"] is True
        assert result["xp_granted"] > 0

    def test_complete_quest_grants_xp(self, session, svc, entity):
        initial_level = entity.level
        q = svc.create_quest(
            session, name="Hard Task", description=".",
            difficulty="hard", xp_reward=500,
        )
        svc.assign_quest(session, entity.id, q["quest_id"])
        result = svc.complete_quest(session, entity.id, q["quest_id"])
        assert result["success"] is True
        assert result["xp_granted"] > 0
        # XP > base because of difficulty multiplier
        assert result["xp_granted"] >= int(500 * 2.5)

    def test_complete_quest_marks_progress(self, session, svc, entity):
        q = svc.create_quest(session, name="Simple", description=".")
        svc.assign_quest(session, entity.id, q["quest_id"])
        svc.complete_quest(session, entity.id, q["quest_id"])
        progress = session.exec(
            select(QuestProgress).where(
                QuestProgress.entity_id == entity.id,
                QuestProgress.quest_id == q["quest_id"],
            )
        ).first()
        assert progress.is_completed is True

    def test_complete_main_quest_marks_quest(self, session, svc, entity):
        q = svc.create_quest(
            session, name="Main Chapter 1", description=".",
            quest_type="main",
        )
        svc.assign_quest(session, entity.id, q["quest_id"])
        svc.complete_quest(session, entity.id, q["quest_id"])
        quest_row = session.get(Quest, q["quest_id"])
        assert quest_row.is_completed is True

    def test_side_quest_does_not_mark_quest_completed(self, session, svc, entity):
        q = svc.create_quest(session, name="Side A", description=".", quest_type="side")
        svc.assign_quest(session, entity.id, q["quest_id"])
        svc.complete_quest(session, entity.id, q["quest_id"])
        quest_row = session.get(Quest, q["quest_id"])
        assert quest_row.is_completed is False

    def test_cannot_complete_twice(self, session, svc, entity):
        q = svc.create_quest(session, name="Once Only", description=".")
        svc.assign_quest(session, entity.id, q["quest_id"])
        svc.complete_quest(session, entity.id, q["quest_id"])
        result = svc.complete_quest(session, entity.id, q["quest_id"])
        assert result["success"] is False
        assert result["reason"] == "quest_already_completed"

    def test_advance_with_bad_increment(self, session, svc, entity):
        q = svc.create_quest(session, name="Zero Test", description=".")
        svc.assign_quest(session, entity.id, q["quest_id"])
        result = svc.advance_quest(session, entity.id, q["quest_id"], increment=0)
        assert result["success"] is False

    def test_get_quest_progress(self, session, svc, entity):
        q = svc.create_quest(session, name="Progress Check", description=".")
        svc.assign_quest(session, entity.id, q["quest_id"])
        result = svc.get_quest_progress(session, entity.id)
        assert result["success"] is True
        assert len(result["quests"]) == 1
        assert result["quests"][0]["quest_name"] == "Progress Check"

    def test_get_quest_progress_filtered(self, session, svc, entity):
        q1 = svc.create_quest(session, name="Q1", description=".")
        q2 = svc.create_quest(session, name="Q2", description=".")
        svc.assign_quest(session, entity.id, q1["quest_id"])
        svc.assign_quest(session, entity.id, q2["quest_id"])
        result = svc.get_quest_progress(session, entity.id, quest_id=q1["quest_id"])
        assert len(result["quests"]) == 1
        assert result["quests"][0]["quest_name"] == "Q1"

    def test_quest_with_item_reward(self, session, svc, entity):
        """Quest with an item_reward_id should copy item to entity's inventory."""
        # Create a template item owned by the entity (acts as item template)
        template = InventoryItem(
            owner_id=entity.id, name="Reward Potion",
            item_type="consumable", rarity="rare",
            item_effect="heal", effect_type="heal",
            effect_value=200, value=100,
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        q = svc.create_quest(
            session, name="Potion Quest", description=".",
            xp_reward=100, item_reward_id=template.id,
        )
        svc.assign_quest(session, entity.id, q["quest_id"])
        result = svc.complete_quest(session, entity.id, q["quest_id"])
        assert result["item_reward"] == "Reward Potion"
        # Entity should now have 2 copies (original + reward)
        items = session.exec(
            select(InventoryItem).where(
                InventoryItem.owner_id == entity.id,
                InventoryItem.name == "Reward Potion",
            )
        ).all()
        assert len(items) == 2
