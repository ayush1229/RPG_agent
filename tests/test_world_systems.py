"""
tests/test_world_systems.py
============================
Tests for: travel, factions, wars, sovereign influence, world events,
terrain formulas, and process_world_delta lazy-tick simulation.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
from math import sqrt

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import (
    EVENT_EFFECTS, TERRAIN_MODIFIERS, WORLD_EVENT_TYPES,
    Faction, FactionRelation, Location, SovereignInfluence,
    TarotEntity, TerritoryControl, TravelState, War, WorldEvent, WorldMap,
)
from app.db.world_service import (
    apply_sovereign_influence, calculate_distance, calculate_travel_time,
    create_faction, end_war, get_active_events, get_dominant_faction,
    get_location_status, get_relation, get_travel_state,
    process_world_delta, resolve_travel, set_relation,
    start_war, travel_entity, trigger_event, update_control,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def entity(session):
    e = TarotEntity(entity_name="Traveller", pos_x=0.0, pos_y=0.0,
                    is_upright_sovereign=False)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


@pytest.fixture
def sovereign(session):
    e = TarotEntity(entity_name="TheSovereign", pos_x=0.0, pos_y=0.0,
                    is_upright_sovereign=True)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


@pytest.fixture
def location(session):
    loc = Location(name="TestCity", description="A test location.",
                   x=100.0, y=100.0, location_type="city")
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


@pytest.fixture
def faction_a(session, location):
    r = create_faction(session, "Alpha", alignment="order",
                       home_location_id=location.id)
    return session.get(Faction, r["faction_id"])


@pytest.fixture
def faction_b(session):
    loc = Location(name="BetaCity", description=".", x=200.0, y=200.0)
    session.add(loc)
    session.flush()
    r = create_faction(session, "Beta", alignment="chaos",
                       home_location_id=loc.id)
    return session.get(Faction, r["faction_id"])


# ─────────────────────────────────────────────────────────────
# 1. Distance + travel time formulas
# ─────────────────────────────────────────────────────────────
class TestFormulas:
    def test_distance_zero(self):
        assert calculate_distance(0, 0, 0, 0) == 0.0

    def test_distance_pythagorean(self):
        assert calculate_distance(0, 0, 3, 4) == pytest.approx(5.0)

    def test_travel_time_city(self):
        t = calculate_travel_time(100.0, speed=10.0, terrain_type="city")
        assert t == pytest.approx(10.0)  # 100/10 * 1.0

    def test_travel_time_corrupted(self):
        t_city = calculate_travel_time(100.0, speed=10.0, terrain_type="city")
        t_cor  = calculate_travel_time(100.0, speed=10.0, terrain_type="corrupted")
        assert t_cor == pytest.approx(t_city * 2.5)

    def test_travel_time_zero_distance(self):
        assert calculate_travel_time(0.0) == 0.0

    def test_all_terrain_modifiers_positive(self):
        for terrain, mod in TERRAIN_MODIFIERS.items():
            assert mod > 0, f"Negative modifier for {terrain}"


# ─────────────────────────────────────────────────────────────
# 2. Travel system
# ─────────────────────────────────────────────────────────────
class TestTravelSystem:
    def test_start_travel(self, session, entity, location):
        r = travel_entity(session, entity.id, 100.0, 100.0,
                          terrain_type="plains", speed=10.0,
                          target_location_id=location.id)
        assert r["success"] is True
        assert r["is_traveling"] is True
        assert r["travel_time_seconds"] > 0

    def test_travel_distance_correct(self, session, entity, location):
        r = travel_entity(session, entity.id, 3.0, 4.0, speed=1.0)
        assert r["distance"] == pytest.approx(5.0)

    def test_already_at_destination(self, session, entity):
        r = travel_entity(session, entity.id, 0.0, 0.0)
        assert r["already_there"] is True

    def test_entity_not_found(self, session):
        r = travel_entity(session, 99999, 10.0, 10.0)
        assert r["success"] is False
        assert r["reason"] == "entity_not_found"

    def test_resolve_travel_not_complete_yet(self, session, entity):
        travel_entity(session, entity.id, 100.0, 0.0,
                      terrain_type="mountain", speed=1.0)
        r = resolve_travel(session, entity.id)
        assert r["success"] is False
        assert r["reason"] == "journey_not_complete"
        assert r["seconds_remaining"] > 0

    def test_resolve_travel_completes(self, session, entity, location):
        travel_entity(session, entity.id, location.x, location.y,
                      speed=10.0, target_location_id=location.id)
        # Force end_time into the past
        ts = session.exec(
            __import__("sqlmodel", fromlist=["select"]).select(TravelState)
            .where(TravelState.entity_id == entity.id)
        ).first()
        ts.end_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.add(ts)
        session.commit()

        r = resolve_travel(session, entity.id)
        assert r["success"] is True
        assert r["location_id"] == location.id
        session.refresh(entity)
        assert entity.pos_x == pytest.approx(location.x)
        assert entity.current_location_id == location.id

    def test_get_travel_state_traveling(self, session, entity):
        travel_entity(session, entity.id, 200.0, 0.0, speed=1.0)
        state = get_travel_state(session, entity.id)
        assert state["is_traveling"] is True
        assert "seconds_remaining" in state
        assert 0 <= state["progress_pct"] <= 100

    def test_get_travel_state_not_traveling(self, session, entity):
        state = get_travel_state(session, entity.id)
        assert state["is_traveling"] is False

    def test_new_journey_cancels_old(self, session, entity):
        travel_entity(session, entity.id, 100.0, 0.0, speed=1.0)
        travel_entity(session, entity.id, 200.0, 0.0, speed=1.0)
        from sqlmodel import select
        rows = session.exec(
            select(TravelState).where(
                TravelState.entity_id == entity.id,
                TravelState.is_completed == False,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].target_x == pytest.approx(200.0)


# ─────────────────────────────────────────────────────────────
# 3. Faction system
# ─────────────────────────────────────────────────────────────
class TestFactionSystem:
    def test_create_faction(self, session):
        r = create_faction(session, "TestFaction", alignment="order")
        assert r["success"] is True
        assert r["faction_id"] is not None

    def test_create_duplicate_rejected(self, session):
        create_faction(session, "Dup")
        r = create_faction(session, "Dup")
        assert r["success"] is False
        assert r["reason"] == "faction_already_exists"

    def test_invalid_alignment(self, session):
        r = create_faction(session, "Bad", alignment="evil")
        assert r["success"] is False

    def test_set_and_get_relation(self, session, faction_a, faction_b):
        r = set_relation(session, faction_a.id, faction_b.id, -60)
        assert r["status"] == "hostile"
        assert get_relation(session, faction_a.id, faction_b.id) == -60

    def test_relation_clamped(self, session, faction_a, faction_b):
        set_relation(session, faction_a.id, faction_b.id, 150)
        assert get_relation(session, faction_a.id, faction_b.id) == 100

    def test_relation_canonical_order(self, session, faction_a, faction_b):
        set_relation(session, faction_b.id, faction_a.id, 75)  # reversed order
        assert get_relation(session, faction_a.id, faction_b.id) == 75

    def test_allied_status(self, session, faction_a, faction_b):
        r = set_relation(session, faction_a.id, faction_b.id, 60)
        assert r["status"] == "allied"

    def test_no_relation_defaults_to_0(self, session, faction_a, faction_b):
        assert get_relation(session, faction_a.id, faction_b.id) == 0


# ─────────────────────────────────────────────────────────────
# 4. Territory control
# ─────────────────────────────────────────────────────────────
class TestTerritoryControl:
    def test_update_control_gain(self, session, location, faction_a):
        r = update_control(session, location.id, faction_a.id, 60.0)
        assert r["control_value"] == pytest.approx(60.0)
        assert r["is_controlled"] is True

    def test_update_control_clamped_max(self, session, location, faction_a):
        r = update_control(session, location.id, faction_a.id, 200.0)
        assert r["control_value"] == pytest.approx(100.0)

    def test_update_control_clamped_min(self, session, location, faction_a):
        r = update_control(session, location.id, faction_a.id, -200.0)
        assert r["control_value"] == pytest.approx(0.0)

    def test_dominant_faction(self, session, location, faction_a, faction_b):
        update_control(session, location.id, faction_a.id, 70.0)
        update_control(session, location.id, faction_b.id, 30.0)
        assert get_dominant_faction(session, location.id) == faction_a.id

    def test_no_dominant_below_50(self, session, location, faction_a):
        update_control(session, location.id, faction_a.id, 40.0)
        assert get_dominant_faction(session, location.id) is None


# ─────────────────────────────────────────────────────────────
# 5. War system
# ─────────────────────────────────────────────────────────────
class TestWarSystem:
    def test_war_requires_hostile_relation(self, session, faction_a, faction_b):
        r = start_war(session, faction_a.id, faction_b.id)
        assert r["success"] is False
        assert r["reason"] == "relation_not_hostile"

    def test_start_war(self, session, faction_a, faction_b):
        set_relation(session, faction_a.id, faction_b.id, -60)
        r = start_war(session, faction_a.id, faction_b.id)
        assert r["success"] is True
        assert r["war_id"] is not None

    def test_duplicate_war_rejected(self, session, faction_a, faction_b):
        set_relation(session, faction_a.id, faction_b.id, -80)
        start_war(session, faction_a.id, faction_b.id)
        r = start_war(session, faction_a.id, faction_b.id)
        assert r["success"] is False
        assert r["reason"] == "war_already_active"

    def test_end_war(self, session, faction_a, faction_b):
        set_relation(session, faction_a.id, faction_b.id, -70)
        w = start_war(session, faction_a.id, faction_b.id)
        r = end_war(session, w["war_id"], reason="peace_treaty")
        assert r["success"] is True
        war = session.get(War, w["war_id"])
        assert war.is_active is False
        assert war.end_time is not None

    def test_same_faction_war_rejected(self, session, faction_a):
        r = start_war(session, faction_a.id, faction_a.id)
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 6. Sovereign influence
# ─────────────────────────────────────────────────────────────
class TestSovereignInfluence:
    def test_non_sovereign_rejected(self, session, entity, location):
        r = apply_sovereign_influence(session, entity.id, location.id, 50.0)
        assert r["success"] is False
        assert r["reason"] == "entity_is_not_sovereign"

    def test_apply_influence(self, session, sovereign, location):
        r = apply_sovereign_influence(session, sovereign.id, location.id, 50.0)
        assert r["success"] is True
        assert r["influence_value"] == pytest.approx(50.0)

    def test_influence_clamped_at_100(self, session, sovereign, location):
        r = apply_sovereign_influence(session, sovereign.id, location.id, 200.0)
        assert r["influence_value"] == pytest.approx(100.0)

    def test_influence_clamped_at_0(self, session, sovereign, location):
        apply_sovereign_influence(session, sovereign.id, location.id, 50.0)
        r = apply_sovereign_influence(session, sovereign.id, location.id, -200.0)
        assert r["influence_value"] == pytest.approx(0.0)

    def test_instability_threshold(self, session, sovereign, location):
        r = apply_sovereign_influence(session, sovereign.id, location.id, 75.0)
        assert r["is_unstable"] is True

    def test_below_instability_stable(self, session, sovereign, location):
        r = apply_sovereign_influence(session, sovereign.id, location.id, 60.0)
        assert r["is_unstable"] is False


# ─────────────────────────────────────────────────────────────
# 7. World events
# ─────────────────────────────────────────────────────────────
class TestWorldEvents:
    def test_trigger_event(self, session, location):
        r = trigger_event(session, "Test War", location.id, "war", 3600.0)
        assert r["success"] is True
        assert r["event_id"] is not None
        assert "effects" in r

    def test_invalid_event_type(self, session, location):
        r = trigger_event(session, "Bad", location.id, "earthquake", 100.0)
        assert r["success"] is False
        assert r["reason"] == "invalid_event_type"

    def test_get_active_events(self, session, location):
        trigger_event(session, "E1", location.id, "war", 100.0)
        trigger_event(session, "E2", location.id, "anomaly", 200.0)
        events = get_active_events(session, location.id)
        assert len(events) == 2

    def test_all_event_types_valid(self, session, location):
        for et in WORLD_EVENT_TYPES:
            r = trigger_event(session, f"ev_{et}", location.id, et, 60.0)
            assert r["success"] is True

    def test_event_effects_structure(self):
        for et in WORLD_EVENT_TYPES:
            assert et in EVENT_EFFECTS
            eff = EVENT_EFFECTS[et]
            assert "spawn_rate" in eff
            assert "travel_danger" in eff
            assert "reward_mult" in eff


# ─────────────────────────────────────────────────────────────
# 8. Location status aggregation
# ─────────────────────────────────────────────────────────────
class TestLocationStatus:
    def test_status_no_data(self, session, location):
        status = get_location_status(session, location.id)
        assert status["dominant_faction_id"] is None
        assert status["is_unstable"] is False
        assert status["spawn_rate_mult"] == pytest.approx(1.0)

    def test_status_with_events(self, session, location):
        trigger_event(session, "War", location.id, "war", 100.0)
        status = get_location_status(session, location.id)
        assert status["spawn_rate_mult"] == pytest.approx(
            EVENT_EFFECTS["war"]["spawn_rate"]
        )


# ─────────────────────────────────────────────────────────────
# 9. Lazy-tick simulation
# ─────────────────────────────────────────────────────────────
class TestLazyTick:
    def test_process_delta_skips_zero(self, session):
        r = process_world_delta(session, 0)
        assert r.get("skipped") is True

    def test_process_delta_resolves_travel(self, session, entity, location):
        travel_entity(session, entity.id, location.x, location.y,
                      speed=10.0, target_location_id=location.id)
        # Manually expire the journey
        from sqlmodel import select as sq_select
        ts = session.exec(sq_select(TravelState).where(
            TravelState.entity_id == entity.id
        )).first()
        ts.end_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        session.add(ts)
        session.commit()

        r = process_world_delta(session, 10.0)
        assert r["travels_completed"] == 1

    def test_process_delta_decays_events(self, session, location):
        trigger_event(session, "Short", location.id, "anomaly", 5.0)
        r = process_world_delta(session, 10.0)
        assert r["events_expired"] == 1
        events = get_active_events(session, location.id)
        assert len(events) == 0

    def test_process_delta_war_shifts_control(self, session, faction_a, faction_b, location):
        set_relation(session, faction_a.id, faction_b.id, -80)
        start_war(session, faction_a.id, faction_b.id)
        # faction_a attacks faction_b's home (BetaCity)
        beta_loc_id = faction_b.home_location_id
        if beta_loc_id:
            process_world_delta(session, 60.0)   # 1 minute of war
            from sqlmodel import select as sq_select
            rows = session.exec(
                sq_select(TerritoryControl).where(
                    TerritoryControl.location_id == beta_loc_id
                )
            ).all()
            # At least one control row should exist after the tick
            assert len(rows) > 0
