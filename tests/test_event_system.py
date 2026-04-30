"""
tests/test_event_system.py
Tests: templates, spawn mechanics, lifecycle, rewards, area-lock, cap enforcement.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    BASE_SPAWN_WEIGHTS, DIFFICULTY_SCALE_FACTOR, EVENT_TEMPLATE_TYPES,
    MAX_EVENTS_PER_LOCATION, SPAWN_MODIFIERS,
    EventQuest, EventTemplate, Location, TarotEntity, WorldEventInstance,
)
from app.db.event_service import (
    abandon_event, accept_event, advance_event_quest, check_and_invalidate_on_quest_complete,
    complete_event, create_event_instance, create_template, expire_events,
    get_active_events_at, invalidate_region_events, seed_default_templates,
    try_spawn_event, _build_weights,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _entity(session, name="Player", level=5) -> TarotEntity:
    e = TarotEntity(entity_name=name, level=level)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _location(session, name="Loc", safe=False) -> Location:
    loc = Location(name=name, description=".", x=0.0, y=0.0, is_safe_zone=safe)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _template(session, name="Ambush", rarity="common", event_type="combat",
              min_level=1, max_level=None, requires_war=False,
              requires_sovereign=False, duration=60, xp=200) -> EventTemplate:
    r = create_template(
        session, name=name, description="Test event.", event_type=event_type,
        rarity=rarity, base_duration_minutes=duration, min_level=min_level,
        max_level=max_level, requires_war=requires_war,
        requires_sovereign_influence=requires_sovereign,
        reward_base_xp=xp, reward_item_pool=["Test Item"],
    )
    return session.get(EventTemplate, r["template_id"])


def _instance(session, template, location, entity=None, offset_minutes=-1) -> WorldEventInstance:
    """Create an instance already expired if offset_minutes < 0."""
    from app.db.event_service import _utcnow
    now = _utcnow()
    inst = WorldEventInstance(
        template_id=template.id,
        location_id=location.id,
        spawned_at=now,
        expires_at=now + timedelta(minutes=offset_minutes),
        is_active=True,
        is_completed=False,
        spawned_for_entity_id=entity.id if entity else None,
        difficulty_scaling=1.0,
    )
    session.add(inst)
    session.commit()
    session.refresh(inst)
    return inst


# ─────────────────────────────────────────────────────────────
# 1. Template management
# ─────────────────────────────────────────────────────────────
class TestTemplateCreation:
    def test_create_template(self, session):
        r = create_template(session, "Test", "desc", "combat")
        assert r["success"] is True
        assert r["template_id"] is not None

    def test_duplicate_template_rejected(self, session):
        create_template(session, "Dup", ".", "combat")
        r = create_template(session, "Dup", ".", "exploration")
        assert r["success"] is False
        assert r["reason"] == "template_already_exists"

    def test_invalid_event_type(self, session):
        r = create_template(session, "Bad", ".", "siege")
        assert r["success"] is False

    def test_invalid_rarity(self, session):
        r = create_template(session, "BadR", ".", "combat", rarity="mythic")
        assert r["success"] is False

    def test_all_event_types_accepted(self, session):
        for i, et in enumerate(EVENT_TEMPLATE_TYPES):
            r = create_template(session, f"T_{i}", ".", et)
            assert r["success"] is True

    def test_all_rarities_accepted(self, session):
        for i, r_val in enumerate(BASE_SPAWN_WEIGHTS.keys()):
            r = create_template(session, f"R_{i}", ".", "combat", rarity=r_val)
            assert r["success"] is True

    def test_item_pool_stored_as_json(self, session):
        create_template(session, "Pool", ".", "trade", reward_item_pool=["Sword", "Shield"])
        tpl = session.exec(select(EventTemplate).where(EventTemplate.name == "Pool")).first()
        assert tpl.reward_item_pool is not None
        pool = json.loads(tpl.reward_item_pool)
        assert "Sword" in pool


# ─────────────────────────────────────────────────────────────
# 2. Default templates seeding
# ─────────────────────────────────────────────────────────────
class TestDefaultTemplates:
    def test_seed_creates_5(self, session):
        count = seed_default_templates(session)
        assert count == 5

    def test_seed_idempotent(self, session):
        seed_default_templates(session)
        count = seed_default_templates(session)
        assert count == 0   # already exist

    def test_war_skirmish_requires_war(self, session):
        seed_default_templates(session)
        tpl = session.exec(
            select(EventTemplate).where(EventTemplate.name == "War Skirmish")
        ).first()
        assert tpl.requires_war is True

    def test_sovereign_distortion_requires_influence(self, session):
        seed_default_templates(session)
        tpl = session.exec(
            select(EventTemplate).where(EventTemplate.name == "Sovereign Distortion")
        ).first()
        assert tpl.requires_sovereign_influence is True
        assert tpl.rarity == "epic"

    def test_ambush_is_common_combat(self, session):
        seed_default_templates(session)
        tpl = session.exec(
            select(EventTemplate).where(EventTemplate.name == "Ambush")
        ).first()
        assert tpl.event_type == "combat"
        assert tpl.rarity == "common"


# ─────────────────────────────────────────────────────────────
# 3. Weight calculation
# ─────────────────────────────────────────────────────────────
class TestWeightSystem:
    def test_base_weights_sum_100(self):
        w = _build_weights(1, False, 0, False)
        assert abs(sum(w.values()) - 100.0) < 0.01

    def test_safe_zone_reduces_weights(self):
        normal = _build_weights(1, False, 0, False)
        safe   = _build_weights(1, False, 0, True)
        assert safe["common"] < normal["common"]
        assert safe["rare"] <= normal["rare"]

    def test_war_zone_increases_rare(self):
        normal = _build_weights(1, False, 0, False)
        war    = _build_weights(1, True,  0, False)
        assert war["rare"] > normal["rare"]
        assert war["epic"] > normal["epic"]

    def test_sovereign_influence_increases_epic(self):
        normal = _build_weights(1, False, 0,    False)
        sov    = _build_weights(1, False, 80.0, False)
        assert sov["epic"] > normal["epic"]

    def test_high_level_increases_rare(self):
        low  = _build_weights(1,  False, 0, False)
        high = _build_weights(45, False, 0, False)
        assert high["rare"] > low["rare"]

    def test_weights_never_negative(self):
        w = _build_weights(1, False, 0, True)  # safe zone
        for v in w.values():
            assert v >= 0.0


# ─────────────────────────────────────────────────────────────
# 4. create_event_instance
# ─────────────────────────────────────────────────────────────
class TestCreateInstance:
    def test_creates_instance(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session)
        r = create_event_instance(session, tpl.id, loc.id, e.id, player_level=5)
        assert r["success"] is True
        assert r["instance_id"] is not None

    def test_difficulty_scaling_formula(self, session):
        loc = _location(session)
        e = _entity(session, level=10)
        tpl = _template(session, name="ScaleTest")
        r = create_event_instance(session, tpl.id, loc.id, e.id, player_level=10)
        expected = round(1.0 + 10 * DIFFICULTY_SCALE_FACTOR, 4)
        assert r["difficulty_scaling"] == pytest.approx(expected)

    def test_expires_at_set_correctly(self, session):
        from app.db.event_service import _utcnow
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="ExpTest", duration=30)
        before = _utcnow()
        r = create_event_instance(session, tpl.id, loc.id, e.id, player_level=1)
        inst = session.get(WorldEventInstance, r["instance_id"])
        exp = inst.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = (exp - before).total_seconds()
        assert 29 * 60 <= delta <= 31 * 60

    def test_invalid_template(self, session):
        loc = _location(session)
        r = create_event_instance(session, 9999, loc.id, None, 1)
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 5. try_spawn_event
# ─────────────────────────────────────────────────────────────
class TestTrySpawn:
    def test_spawn_with_templates(self, session):
        seed_default_templates(session)
        loc = _location(session)
        e = _entity(session, level=5)
        # Run many times — should eventually spawn something common
        results = [try_spawn_event(session, e.id, loc.id) for _ in range(30)]
        assert any(r.get("spawned") for r in results)

    def test_no_templates_returns_no_eligible(self, session):
        loc = _location(session)
        e = _entity(session, level=5)
        r = try_spawn_event(session, e.id, loc.id)
        assert r["spawned"] is False

    def test_entity_not_found(self, session):
        loc = _location(session)
        r = try_spawn_event(session, 99999, loc.id)
        assert r["spawned"] is False
        assert r["reason"] == "entity_not_found"

    def test_level_filter_respected(self, session):
        loc = _location(session)
        e = _entity(session, level=2)
        # Only a template requiring level 30
        _template(session, name="HighLevel", min_level=30)
        r = try_spawn_event(session, e.id, loc.id)
        assert r["spawned"] is False

    def test_cap_enforcement(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="CapTest", duration=120)
        # Fill to cap
        for _ in range(MAX_EVENTS_PER_LOCATION):
            create_event_instance(session, tpl.id, loc.id, None, 1)
        r = try_spawn_event(session, e.id, loc.id)
        assert r["spawned"] is False
        assert r["reason"] == "location_event_cap_reached"

    def test_war_only_template_blocked_without_war(self, session):
        loc = _location(session)
        e = _entity(session, level=20)
        _template(session, name="WarOnly", rarity="rare", requires_war=True, min_level=1)
        # Run many attempts — should never spawn the war template when no war active
        results = [try_spawn_event(session, e.id, loc.id) for _ in range(20)]
        for r in results:
            if r.get("spawned"):
                assert "WarOnly" not in r.get("template_name", "")


# ─────────────────────────────────────────────────────────────
# 6. Expiry
# ─────────────────────────────────────────────────────────────
class TestExpiry:
    def test_expire_events_marks_stale(self, session):
        loc = _location(session)
        tpl = _template(session, name="ShortEvent")
        inst = _instance(session, tpl, loc, offset_minutes=-5)
        count = expire_events(session)
        assert count >= 1
        session.refresh(inst)
        assert inst.is_active is False

    def test_active_events_not_expired(self, session):
        loc = _location(session)
        tpl = _template(session, name="LongEvent", duration=120)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        count = expire_events(session)
        assert count == 0

    def test_get_active_excludes_expired(self, session):
        loc = _location(session)
        tpl = _template(session, name="ExpiredEvent")
        _instance(session, tpl, loc, offset_minutes=-10)
        events = get_active_events_at(session, loc.id)
        assert len(events) == 0


# ─────────────────────────────────────────────────────────────
# 7. Accept event
# ─────────────────────────────────────────────────────────────
class TestAcceptEvent:
    def _live_instance(self, session, loc, e=None):
        tpl = _template(session, name=f"LiveEvent_{id(loc)}", duration=120)
        r = create_event_instance(session, tpl.id, loc.id, e.id if e else None, 5)
        return session.get(WorldEventInstance, r["instance_id"])

    def test_accept_event(self, session):
        loc = _location(session)
        e = _entity(session)
        inst = self._live_instance(session, loc)
        r = accept_event(session, e.id, inst.id)
        assert r["success"] is True
        assert r["event_quest_id"] is not None

    def test_duplicate_accept_rejected(self, session):
        loc = _location(session)
        e = _entity(session)
        inst = self._live_instance(session, loc)
        accept_event(session, e.id, inst.id)
        r = accept_event(session, e.id, inst.id)
        assert r["success"] is False
        assert r["reason"] == "already_accepted"

    def test_expired_event_cannot_be_accepted(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="ExpiredAccept")
        inst = _instance(session, tpl, loc, offset_minutes=-5)
        r = accept_event(session, e.id, inst.id)
        assert r["success"] is False
        assert r["reason"] == "event_expired"

    def test_inactive_event_rejected(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="InactiveAccept")
        inst = _instance(session, tpl, loc, offset_minutes=120)
        inst.is_active = False
        session.add(inst)
        session.commit()
        r = accept_event(session, e.id, inst.id)
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 8. Complete event
# ─────────────────────────────────────────────────────────────
class TestCompleteEvent:
    def _accept(self, session, loc, e):
        tpl = _template(session, name=f"Completable_{id(e)}", duration=120, xp=500)
        r = create_event_instance(session, tpl.id, loc.id, None, e.level)
        inst = session.get(WorldEventInstance, r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        return session.get(EventQuest, eq_r["event_quest_id"])

    def test_complete_at_goal(self, session):
        loc = _location(session)
        e = _entity(session)
        eq = self._accept(session, loc, e)
        advance_event_quest(session, e.id, eq.id, 1)
        r = complete_event(session, e.id, eq.id)
        assert r["success"] is True
        assert r["xp_awarded"] > 0

    def test_complete_without_progress_fails(self, session):
        loc = _location(session)
        e = _entity(session)
        eq = self._accept(session, loc, e)
        r = complete_event(session, e.id, eq.id)
        assert r["success"] is False
        assert r["reason"] == "not_enough_progress"

    def test_xp_scaled_by_difficulty(self, session):
        loc = _location(session)
        e = _entity(session, level=10)
        eq = self._accept(session, loc, e)
        advance_event_quest(session, e.id, eq.id, 1)
        r = complete_event(session, e.id, eq.id)
        # scaling = 1 + level*factor, applied to base_xp=500
        expected_min = int(500 * (1 + 10 * DIFFICULTY_SCALE_FACTOR)) - 5
        assert r["xp_awarded"] >= expected_min

    def test_item_rewarded_from_pool(self, session):
        loc = _location(session)
        e = _entity(session)
        eq = self._accept(session, loc, e)
        advance_event_quest(session, e.id, eq.id, 1)
        r = complete_event(session, e.id, eq.id)
        # reward_item_pool was ["Test Item"]
        assert r["item_rewarded"] == "Test Item"

    def test_double_complete_rejected(self, session):
        loc = _location(session)
        e = _entity(session)
        eq = self._accept(session, loc, e)
        advance_event_quest(session, e.id, eq.id, 1)
        complete_event(session, e.id, eq.id)
        r = complete_event(session, e.id, eq.id)
        assert r["success"] is False

    def test_instance_marked_completed_after_complete(self, session):
        loc = _location(session)
        e = _entity(session)
        eq = self._accept(session, loc, e)
        advance_event_quest(session, e.id, eq.id, 1)
        complete_event(session, e.id, eq.id)
        inst = session.get(WorldEventInstance, eq.event_instance_id)
        assert inst.is_completed is True
        assert inst.is_active is False


# ─────────────────────────────────────────────────────────────
# 9. Abandon event
# ─────────────────────────────────────────────────────────────
class TestAbandon:
    def test_abandon_event(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="AbandonTest", duration=120)
        r = create_event_instance(session, tpl.id, loc.id, None, 1)
        inst = session.get(WorldEventInstance, r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        eq = session.get(EventQuest, eq_r["event_quest_id"])
        r = abandon_event(session, e.id, eq.id)
        assert r["success"] is True
        assert r["abandoned"] is True

    def test_complete_after_abandon_fails(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="AbandonThenComplete", duration=120)
        r = create_event_instance(session, tpl.id, loc.id, None, 1)
        inst = session.get(WorldEventInstance, r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        eq = session.get(EventQuest, eq_r["event_quest_id"])
        abandon_event(session, e.id, eq.id)
        r = complete_event(session, e.id, eq.id)
        assert r["success"] is False
        assert r["reason"] == "quest_abandoned"

    def test_event_instance_stays_active_after_abandon(self, session):
        """Other players can still take the event."""
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="SharedEvent", duration=120)
        r = create_event_instance(session, tpl.id, loc.id, None, 1)
        inst = session.get(WorldEventInstance, r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        eq = session.get(EventQuest, eq_r["event_quest_id"])
        abandon_event(session, e.id, eq.id)
        session.refresh(inst)
        # Instance should still be active for other players
        assert inst.is_active is True


# ─────────────────────────────────────────────────────────────
# 10. Advance quest progress
# ─────────────────────────────────────────────────────────────
class TestAdvanceProgress:
    def test_advance_progress(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="Advance", duration=120)
        inst_r = create_event_instance(session, tpl.id, loc.id, None, 1)
        inst = session.get(WorldEventInstance, inst_r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        r = advance_event_quest(session, e.id, eq_r["event_quest_id"], 1)
        assert r["success"] is True
        assert r["progress"] == 1
        assert r["ready_to_complete"] is True

    def test_progress_capped_at_goal(self, session):
        loc = _location(session)
        e = _entity(session)
        tpl = _template(session, name="CapProgress", duration=120)
        inst_r = create_event_instance(session, tpl.id, loc.id, None, 1)
        inst = session.get(WorldEventInstance, inst_r["instance_id"])
        eq_r = accept_event(session, e.id, inst.id)
        advance_event_quest(session, e.id, eq_r["event_quest_id"], 99)
        eq = session.get(EventQuest, eq_r["event_quest_id"])
        assert eq.progress <= eq.goal


# ─────────────────────────────────────────────────────────────
# 11. Area lock — region invalidation
# ─────────────────────────────────────────────────────────────
class TestAreaLock:
    def test_invalidate_region_events(self, session):
        loc = _location(session)
        tpl = _template(session, name="RegionTest", duration=120)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        count = invalidate_region_events(session, loc.id)
        assert count == 2
        events = get_active_events_at(session, loc.id)
        assert len(events) == 0

    def test_invalidate_by_quest_id(self, session):
        from app.db.models import Quest
        q = Quest(name="MainQ", description=".", quest_type="main",
                  difficulty="easy", required_level=1, xp_reward=0)
        session.add(q)
        session.flush()
        loc = _location(session, name="QuestLoc")
        loc.region_main_quest_id = q.id
        session.add(loc)
        session.commit()

        tpl = _template(session, name="QuestRegionEvent", duration=120)
        create_event_instance(session, tpl.id, loc.id, None, 1)

        count = check_and_invalidate_on_quest_complete(session, q.id)
        assert count == 1


# ─────────────────────────────────────────────────────────────
# 12. get_active_events_at
# ─────────────────────────────────────────────────────────────
class TestGetActiveEvents:
    def test_returns_live_events(self, session):
        loc = _location(session)
        tpl = _template(session, name="LiveQ", duration=120)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        events = get_active_events_at(session, loc.id)
        assert len(events) == 2

    def test_excludes_expired(self, session):
        loc = _location(session)
        tpl = _template(session, name="Expired")
        _instance(session, tpl, loc, offset_minutes=-1)
        events = get_active_events_at(session, loc.id)
        assert len(events) == 0

    def test_personalized_event_only_visible_to_owner(self, session):
        loc = _location(session)
        e1 = _entity(session, "E1")
        e2 = _entity(session, "E2")
        tpl = _template(session, name="PersonalEvent", duration=120)
        # Personalized to e1
        create_event_instance(session, tpl.id, loc.id, e1.id, 1)
        events_for_e2 = get_active_events_at(session, loc.id, entity_id=e2.id)
        assert len(events_for_e2) == 0
        events_for_e1 = get_active_events_at(session, loc.id, entity_id=e1.id)
        assert len(events_for_e1) == 1

    def test_event_snapshot_has_required_keys(self, session):
        loc = _location(session)
        tpl = _template(session, name="Snapshot", duration=120)
        create_event_instance(session, tpl.id, loc.id, None, 1)
        events = get_active_events_at(session, loc.id)
        assert len(events) == 1
        ev = events[0]
        for key in ("instance_id", "template_name", "event_type", "rarity",
                    "risk_level", "difficulty_scaling", "seconds_remaining", "reward_base_xp"):
            assert key in ev


# ─────────────────────────────────────────────────────────────
# 13. Constants sanity
# ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_base_weights_sum_100(self):
        assert abs(sum(BASE_SPAWN_WEIGHTS.values()) - 100.0) < 0.01

    def test_all_spawn_modifiers_reference_valid_rarities(self):
        valid = set(BASE_SPAWN_WEIGHTS.keys())
        for mod_name, deltas in SPAWN_MODIFIERS.items():
            for rarity in deltas:
                assert rarity in valid, f"{rarity} in {mod_name} not a valid rarity"

    def test_max_events_per_location_positive(self):
        assert MAX_EVENTS_PER_LOCATION > 0

    def test_difficulty_scale_factor_positive(self):
        assert DIFFICULTY_SCALE_FACTOR > 0

    def test_event_types_non_empty(self):
        assert len(EVENT_TEMPLATE_TYPES) >= 5
