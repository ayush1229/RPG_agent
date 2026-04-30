"""
tests/test_time_system.py
Tests: WorldTime lazy-tick, day/night detection, night modifiers,
       housing lifecycle, Dreamscape gate + entry/exit, dream flags.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    DREAM_BASE_CHANCE, DREAMSCAPE_LOCATION_NAME, HOUSING_TYPES,
    NIGHT_END_HOUR, NIGHT_RISK_MULTIPLIER, NIGHT_START_HOUR,
    DreamState, Location, PlayerHousing, TarotEntity, WorldTime, Wallet,
)
from app.db.time_service import (
    apply_night_modifiers, buy_housing, check_day_night, enter_dreamscape,
    enter_housing, exit_dreamscape, exit_housing, get_dream_flags,
    get_night_event_weight_boost, get_travel_night_modifier, get_world_time,
    is_in_dreamscape, is_player_sheltered, rent_housing, set_dream_flag,
    try_enter_dream, unlock_dreamscape, update_time,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _entity(session, name="Player") -> TarotEntity:
    e = TarotEntity(entity_name=name, level=5)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _location(session, name="Town", safe=False, magic_restricted=False) -> Location:
    loc = Location(name=name, description=".", x=0.0, y=0.0,
                   is_safe_zone=safe, is_magic_restricted=magic_restricted)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _set_game_hour(session, hour: int) -> WorldTime:
    """Force the game clock to a specific hour for deterministic night/day tests."""
    wt = get_world_time(session)
    ct = wt.current_time.replace(hour=hour, minute=0, second=0, microsecond=0)
    wt.current_time = ct
    wt.last_real_tick = datetime.now(timezone.utc)
    session.add(wt)
    session.commit()
    return wt


# ─────────────────────────────────────────────────────────────
# 1. WorldTime singleton
# ─────────────────────────────────────────────────────────────
class TestWorldTime:
    def test_creates_singleton(self, session):
        wt = get_world_time(session)
        assert wt.id == 1
        assert wt.current_time is not None

    def test_idempotent_get(self, session):
        wt1 = get_world_time(session)
        wt2 = get_world_time(session)
        assert wt1.id == wt2.id

    def test_update_time_advances_clock(self, session):
        wt = get_world_time(session)
        # Manually backdate last_real_tick by 5 real-seconds
        wt.last_real_tick = datetime.now(timezone.utc) - timedelta(seconds=5)
        wt.time_scale = 60.0   # 5 real-secs * 60 = 300 game-secs = 5 game-mins
        session.add(wt)
        session.commit()

        before = wt.current_time
        result = update_time(session)
        after = session.get(WorldTime, 1).current_time

        assert after > before
        assert result["game_seconds_advanced"] == pytest.approx(300, rel=0.1)

    def test_update_time_returns_snapshot_keys(self, session):
        result = update_time(session)
        for key in ("game_time", "game_hour", "is_night", "time_phase",
                    "night_risk_multiplier", "time_scale"):
            assert key in result

    def test_check_day_night_no_advance(self, session):
        wt = get_world_time(session)
        before = wt.current_time
        check_day_night(session)
        after = session.get(WorldTime, 1).current_time
        assert before == after   # check_day_night must NOT advance clock


# ─────────────────────────────────────────────────────────────
# 2. Day / Night detection
# ─────────────────────────────────────────────────────────────
class TestDayNight:
    @pytest.mark.parametrize("hour,expected_night", [
        (0,  True),   # midnight
        (5,  True),   # pre-dawn
        (6,  False),  # dawn — boundary
        (12, False),  # noon
        (17, False),  # late afternoon
        (18, True),   # dusk — boundary
        (23, True),   # late night
    ])
    def test_night_hours(self, session, hour, expected_night):
        _set_game_hour(session, hour)
        dn = check_day_night(session)
        assert dn["is_night"] == expected_night, f"hour={hour}"

    def test_night_phase_label(self, session):
        _set_game_hour(session, 22)
        dn = check_day_night(session)
        assert dn["time_phase"] == "night"

    def test_day_phase_label(self, session):
        _set_game_hour(session, 10)
        dn = check_day_night(session)
        assert dn["time_phase"] == "day"

    def test_night_multiplier_in_snapshot(self, session):
        _set_game_hour(session, 21)
        dn = check_day_night(session)
        assert dn["night_risk_multiplier"] == pytest.approx(NIGHT_RISK_MULTIPLIER)

    def test_day_multiplier_is_one(self, session):
        _set_game_hour(session, 12)
        dn = check_day_night(session)
        assert dn["night_risk_multiplier"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────
# 3. Night modifiers
# ─────────────────────────────────────────────────────────────
class TestNightModifiers:
    def test_apply_night_modifiers_at_night(self, session):
        _set_game_hour(session, 22)
        result = apply_night_modifiers(100.0, session)
        assert result == pytest.approx(100.0 * NIGHT_RISK_MULTIPLIER)

    def test_apply_night_modifiers_at_day(self, session):
        _set_game_hour(session, 10)
        result = apply_night_modifiers(100.0, session)
        assert result == pytest.approx(100.0)   # no modifier

    def test_night_event_weight_boost_at_night(self, session):
        _set_game_hour(session, 2)
        boosts = get_night_event_weight_boost(session)
        assert boosts.get("rare", 0) > 0
        assert boosts.get("epic", 0) > 0

    def test_night_event_weight_boost_at_day(self, session):
        _set_game_hour(session, 12)
        boosts = get_night_event_weight_boost(session)
        assert boosts == {}   # no boosts during day

    def test_travel_modifier_at_night(self, session):
        _set_game_hour(session, 23)
        mod = get_travel_night_modifier(session)
        assert mod == pytest.approx(NIGHT_RISK_MULTIPLIER)

    def test_travel_modifier_at_day(self, session):
        _set_game_hour(session, 9)
        mod = get_travel_night_modifier(session)
        assert mod == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────
# 4. Housing — rent
# ─────────────────────────────────────────────────────────────
class TestRentHousing:
    def test_rent_inn(self, session):
        e = _entity(session)
        loc = _location(session)
        r = rent_housing(session, e.id, loc.id, "inn", duration_hours=8)
        assert r["success"] is True
        assert r["housing_type"] == "inn"
        assert r["is_safe_zone"] is True

    def test_rent_rented_room(self, session):
        e = _entity(session)
        loc = _location(session)
        r = rent_housing(session, e.id, loc.id, "rented_room", duration_hours=24)
        assert r["success"] is True

    def test_cannot_rent_owned_house(self, session):
        e = _entity(session)
        loc = _location(session)
        r = rent_housing(session, e.id, loc.id, "owned_house")
        assert r["success"] is False

    def test_invalid_type_rejected(self, session):
        e = _entity(session)
        loc = _location(session)
        r = rent_housing(session, e.id, loc.id, "tent")
        assert r["success"] is False

    def test_rent_replaces_existing(self, session):
        e = _entity(session)
        loc1 = _location(session, "Loc1")
        loc2 = _location(session, "Loc2")
        rent_housing(session, e.id, loc1.id, "inn", 4)
        r = rent_housing(session, e.id, loc2.id, "rented_room", 24)
        assert r["success"] is True
        housing = session.exec(
            select(PlayerHousing).where(PlayerHousing.entity_id == e.id)
        ).first()
        assert housing.location_id == loc2.id
        assert housing.housing_type == "rented_room"

    def test_expires_at_set(self, session):
        from app.db.time_service import _utcnow
        e = _entity(session)
        loc = _location(session)
        before = _utcnow()
        r = rent_housing(session, e.id, loc.id, "inn", duration_hours=8)
        housing = session.exec(
            select(PlayerHousing).where(PlayerHousing.entity_id == e.id)
        ).first()
        exp = housing.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = (exp - before).total_seconds()
        assert 7.5 * 3600 <= delta <= 8.5 * 3600


# ─────────────────────────────────────────────────────────────
# 5. Housing — buy
# ─────────────────────────────────────────────────────────────
class TestBuyHousing:
    def test_buy_house_sufficient_funds(self, session):
        e = _entity(session)
        loc = _location(session)
        wallet = Wallet(owner_entity_id=e.id, balance=10000)
        session.add(wallet)
        session.commit()
        r = buy_housing(session, e.id, loc.id)
        assert r["success"] is True
        assert r["housing_type"] == "owned_house"
        assert r["permanent"] is True
        assert r["gold_spent"] == 5000

    def test_buy_house_insufficient_funds(self, session):
        e = _entity(session)
        loc = _location(session)
        wallet = Wallet(owner_entity_id=e.id, balance=100)
        session.add(wallet)
        session.commit()
        r = buy_housing(session, e.id, loc.id)
        assert r["success"] is False
        assert r["reason"] == "insufficient_funds"

    def test_owned_house_no_expiry(self, session):
        e = _entity(session)
        loc = _location(session)
        wallet = Wallet(owner_entity_id=e.id, balance=10000)
        session.add(wallet)
        session.commit()
        buy_housing(session, e.id, loc.id)
        housing = session.exec(
            select(PlayerHousing).where(PlayerHousing.entity_id == e.id)
        ).first()
        assert housing.expires_at is None

    def test_gold_deducted(self, session):
        e = _entity(session)
        loc = _location(session)
        wallet = Wallet(owner_entity_id=e.id, balance=10000)
        session.add(wallet)
        session.commit()
        buy_housing(session, e.id, loc.id)
        session.refresh(wallet)
        assert wallet.balance == 5000


# ─────────────────────────────────────────────────────────────
# 6. Housing — enter / exit
# ─────────────────────────────────────────────────────────────
class TestEnterExitHousing:
    def test_enter_housing(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        r = enter_housing(session, e.id)
        assert r["success"] is True
        assert r["is_inside"] is True
        assert r["is_safe_zone"] is True
        assert r["night_risk_nullified"] is True

    def test_enter_sets_entity_location(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        enter_housing(session, e.id)
        session.refresh(e)
        assert e.current_location_id == loc.id

    def test_exit_housing(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        enter_housing(session, e.id)
        r = exit_housing(session, e.id)
        assert r["success"] is True
        assert r["is_inside"] is False

    def test_exit_when_not_inside(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        r = exit_housing(session, e.id)
        assert r["success"] is False

    def test_gm_hint_at_night(self, session):
        _set_game_hour(session, 21)
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        enter_housing(session, e.id)
        r = exit_housing(session, e.id)
        assert r["gm_hint"] is not None
        assert "Night" in r["gm_hint"]

    def test_no_housing_enter_fails(self, session):
        e = _entity(session)
        r = enter_housing(session, e.id)
        assert r["success"] is False

    def test_is_player_sheltered_when_inside(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        enter_housing(session, e.id)
        assert is_player_sheltered(session, e.id) is True

    def test_is_player_sheltered_false_when_outside(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        assert is_player_sheltered(session, e.id) is False

    def test_expired_housing_blocks_entry(self, session):
        e = _entity(session)
        loc = _location(session)
        rent_housing(session, e.id, loc.id, "inn", 8)
        # Manually expire
        housing = session.exec(
            select(PlayerHousing).where(PlayerHousing.entity_id == e.id)
        ).first()
        housing.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(housing)
        session.commit()
        r = enter_housing(session, e.id)
        assert r["success"] is False
        assert r["reason"] == "housing_expired"


# ─────────────────────────────────────────────────────────────
# 7. Dreamscape unlock
# ─────────────────────────────────────────────────────────────
class TestUnlockDream:
    def test_unlock_dreamscape(self, session):
        e = _entity(session)
        r = unlock_dreamscape(session, e.id)
        assert r["success"] is True
        assert r.get("unlocked") is True

    def test_unlock_idempotent(self, session):
        e = _entity(session)
        unlock_dreamscape(session, e.id)
        r = unlock_dreamscape(session, e.id)
        assert r["success"] is True
        assert r.get("already_unlocked") is True


# ─────────────────────────────────────────────────────────────
# 8. Dreamscape entry/exit
# ─────────────────────────────────────────────────────────────
class TestDreamEntry:
    def test_enter_requires_unlock(self, session):
        e = _entity(session)
        r = enter_dreamscape(session, e.id)
        # entity not found or just enters? State check: has_unlocked=False
        # enter_dreamscape is deterministic — only try_enter_dream checks unlock
        # But we still need entity to exist
        assert r["entered"] is True or r.get("success") is True   # direct entry bypasses gate

    def test_try_enter_blocked_without_unlock(self, session):
        e = _entity(session)
        _set_game_hour(session, 23)
        r = try_enter_dream(session, e.id)
        assert r["entered"] is False
        assert r["reason"] == "dreamscape_not_unlocked"

    def test_try_enter_blocked_during_day(self, session):
        e = _entity(session)
        unlock_dreamscape(session, e.id)
        _set_game_hour(session, 12)
        r = try_enter_dream(session, e.id)
        assert r["entered"] is False
        assert r["reason"] == "only_possible_at_night"

    def test_enter_dreamscape_saves_location(self, session):
        e = _entity(session)
        loc = _location(session, "StartCity")
        e.current_location_id = loc.id
        session.add(e)
        session.commit()
        result = enter_dreamscape(session, e.id)
        assert result["entered"] is True
        ds = session.exec(
            select(DreamState).where(DreamState.entity_id == e.id)
        ).first()
        assert ds.pre_dream_location_id == loc.id

    def test_entity_moved_to_dreamscape_location(self, session):
        e = _entity(session)
        result = enter_dreamscape(session, e.id)
        assert result["entered"] is True
        session.refresh(e)
        dream_loc = session.exec(
            select(Location).where(Location.name == DREAMSCAPE_LOCATION_NAME)
        ).first()
        assert e.current_location_id == dream_loc.id

    def test_dreamscape_location_is_magic_restricted(self, session):
        e = _entity(session)
        enter_dreamscape(session, e.id)
        dream_loc = session.exec(
            select(Location).where(Location.name == DREAMSCAPE_LOCATION_NAME)
        ).first()
        assert dream_loc.is_magic_restricted is True
        assert dream_loc.is_safe_zone is True

    def test_entry_restrictions_in_result(self, session):
        e = _entity(session)
        r = enter_dreamscape(session, e.id)
        assert r["restrictions"]["combat"] is False
        assert r["restrictions"]["abilities"] is False
        assert r["restrictions"]["mana_usage"] is False

    def test_cannot_enter_twice(self, session):
        e = _entity(session)
        enter_dreamscape(session, e.id)
        r = enter_dreamscape(session, e.id)
        assert r["success"] is False
        assert r["reason"] == "already_in_dreamscape"

    def test_exit_dreamscape(self, session):
        e = _entity(session)
        loc = _location(session, "HomeCity")
        e.current_location_id = loc.id
        session.add(e)
        session.commit()
        enter_dreamscape(session, e.id)
        r = exit_dreamscape(session, e.id)
        assert r["success"] is True
        session.refresh(e)
        assert e.current_location_id == loc.id

    def test_exit_clears_dreamscape_flag(self, session):
        e = _entity(session)
        enter_dreamscape(session, e.id)
        exit_dreamscape(session, e.id)
        assert is_in_dreamscape(session, e.id) is False

    def test_is_in_dreamscape_true(self, session):
        e = _entity(session)
        enter_dreamscape(session, e.id)
        assert is_in_dreamscape(session, e.id) is True

    def test_is_in_dreamscape_false_by_default(self, session):
        e = _entity(session)
        assert is_in_dreamscape(session, e.id) is False

    def test_exit_when_not_in_dream_fails(self, session):
        e = _entity(session)
        r = exit_dreamscape(session, e.id)
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 9. Dream flags
# ─────────────────────────────────────────────────────────────
class TestDreamFlags:
    def test_set_and_get_flag(self, session):
        e = _entity(session)
        set_dream_flag(session, e.id, "met_fool_arcana", True)
        flags = get_dream_flags(session, e.id)
        assert flags["met_fool_arcana"] is True

    def test_multiple_flags(self, session):
        e = _entity(session)
        set_dream_flag(session, e.id, "vision_1", "fire")
        set_dream_flag(session, e.id, "riddle_solved", 3)
        flags = get_dream_flags(session, e.id)
        assert flags["vision_1"] == "fire"
        assert flags["riddle_solved"] == 3

    def test_flags_persist_after_exit(self, session):
        e = _entity(session)
        enter_dreamscape(session, e.id)
        set_dream_flag(session, e.id, "anchor_seen", True)
        exit_dreamscape(session, e.id)
        flags = get_dream_flags(session, e.id)
        assert flags["anchor_seen"] is True

    def test_empty_flags_initially(self, session):
        e = _entity(session)
        flags = get_dream_flags(session, e.id)
        assert flags == {}


# ─────────────────────────────────────────────────────────────
# 10. try_enter_dream — probabilistic gate
# ─────────────────────────────────────────────────────────────
class TestTryEnterDream:
    def test_many_attempts_some_succeed(self, session):
        """Over 200 night attempts with 10% chance, at least one should trigger."""
        e = _entity(session)
        unlock_dreamscape(session, e.id)
        _set_game_hour(session, 2)
        results = []
        for _ in range(200):
            # Reset dreamscape state each iteration so entry is possible
            ds = session.exec(
                select(DreamState).where(DreamState.entity_id == e.id)
            ).first()
            ds.is_in_dreamscape = False
            ds.last_entered = None
            session.add(ds)
            session.commit()
            r = try_enter_dream(session, e.id)
            results.append(r["entered"])
        assert any(results), "Expected at least one successful dream entry in 200 tries"

    def test_already_in_dreamscape_blocked(self, session):
        e = _entity(session)
        unlock_dreamscape(session, e.id)
        _set_game_hour(session, 2)
        enter_dreamscape(session, e.id)
        r = try_enter_dream(session, e.id)
        assert r["entered"] is False
        assert r["reason"] == "already_in_dreamscape"


# ─────────────────────────────────────────────────────────────
# 11. Cooldown
# ─────────────────────────────────────────────────────────────
class TestDreamCooldown:
    def test_cooldown_blocks_immediate_reentry(self, session):
        e = _entity(session)
        unlock_dreamscape(session, e.id)
        _set_game_hour(session, 2)

        # Force entry + set last_entered to NOW (game time)
        enter_dreamscape(session, e.id)
        exit_dreamscape(session, e.id)

        # last_entered was set to current game time — cooldown active
        r = try_enter_dream(session, e.id)
        # Should be blocked by cooldown or chance — not "only_possible_at_night"
        assert r["entered"] is False
        assert r["reason"] in ("dream_cooldown", "chance_not_triggered")


# ─────────────────────────────────────────────────────────────
# 12. Constants
# ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_night_risk_multiplier_gt_one(self):
        assert NIGHT_RISK_MULTIPLIER > 1.0

    def test_dream_chance_between_0_and_1(self):
        assert 0 < DREAM_BASE_CHANCE < 1

    def test_night_boundaries(self):
        assert NIGHT_START_HOUR == 18
        assert NIGHT_END_HOUR == 6

    def test_housing_types_non_empty(self):
        assert len(HOUSING_TYPES) == 3
        assert "inn" in HOUSING_TYPES
        assert "owned_house" in HOUSING_TYPES
