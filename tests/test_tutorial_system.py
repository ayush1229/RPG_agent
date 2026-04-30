"""
tests/test_tutorial_system.py
Tests: TutorialState CRUD, phase gating, system locks, event rarity caps,
       auto-advance hooks, GM context injection, and global clock integration.
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    TUTORIAL_MAX_RARITY, TUTORIAL_PHASES, TUTORIAL_SYSTEM_LOCKS,
    Location, TarotEntity, TutorialState, WorldTime,
)
from app.db.tutorial_service import (
    advance_phase, build_tutorial_context, check_system_access,
    get_max_event_rarity, get_phase_flags, get_tutorial_state,
    is_tutorial_complete, on_combat_won, on_housing_rented,
    on_item_returned, on_location_entered, on_trade_completed,
    set_phase_flag, start_tutorial,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _entity(session, name="Player") -> TarotEntity:
    e = TarotEntity(entity_name=name, level=1)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _location(session, name="Elaris Hollow") -> Location:
    loc = Location(name=name, description=".", x=0.0, y=0.0)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _force_phase(session, entity_id: int, phase: int) -> TutorialState:
    ts = get_tutorial_state(session, entity_id)
    ts.phase = phase
    session.add(ts)
    session.commit()
    return ts


# ─────────────────────────────────────────────────────────────
# 1. TutorialState CRUD
# ─────────────────────────────────────────────────────────────
class TestTutorialState:
    def test_creates_state(self, session):
        e = _entity(session)
        ts = get_tutorial_state(session, e.id)
        assert ts.entity_id == e.id
        assert ts.phase == 0

    def test_idempotent_get(self, session):
        e = _entity(session)
        ts1 = get_tutorial_state(session, e.id)
        ts2 = get_tutorial_state(session, e.id)
        assert ts1.id == ts2.id

    def test_set_and_get_phase_flag(self, session):
        e = _entity(session)
        set_phase_flag(session, e.id, "item_retrieved", True)
        flags = get_phase_flags(session, e.id)
        assert flags["item_retrieved"] is True

    def test_multiple_flags(self, session):
        e = _entity(session)
        set_phase_flag(session, e.id, "a", 1)
        set_phase_flag(session, e.id, "b", "hello")
        flags = get_phase_flags(session, e.id)
        assert flags["a"] == 1
        assert flags["b"] == "hello"


# ─────────────────────────────────────────────────────────────
# 2. start_tutorial
# ─────────────────────────────────────────────────────────────
class TestStartTutorial:
    def test_start_tutorial(self, session):
        _location(session)   # seed Elaris Hollow
        e = _entity(session)
        r = start_tutorial(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 1

    def test_start_sets_location(self, session):
        loc = _location(session)
        e = _entity(session)
        start_tutorial(session, e.id)
        session.refresh(e)
        assert e.current_location_id == loc.id

    def test_start_idempotent(self, session):
        _location(session)
        e = _entity(session)
        start_tutorial(session, e.id)
        r = start_tutorial(session, e.id)
        assert r["success"] is True
        assert r.get("already_started") is True

    def test_entity_not_found(self, session):
        r = start_tutorial(session, 99999)
        assert r["success"] is False
        assert r["reason"] == "entity_not_found"


# ─────────────────────────────────────────────────────────────
# 3. advance_phase
# ─────────────────────────────────────────────────────────────
class TestAdvancePhase:
    def test_advance_increments_phase(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        r = advance_phase(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 2

    def test_cannot_exceed_max_phase(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 11)
        r = advance_phase(session, e.id)
        assert r.get("already_complete") is True

    def test_phase_name_matches_constant(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 3)
        r = advance_phase(session, e.id)
        assert r["phase_name"] == TUTORIAL_PHASES[4]

    def test_directive_returned(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        r = advance_phase(session, e.id)
        assert "directive" in r
        assert len(r["directive"]) > 0

    def test_completed_at_set_on_finish(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 10)
        advance_phase(session, e.id)
        ts = get_tutorial_state(session, e.id)
        assert ts.completed_at is not None

    def test_is_complete_after_phase_11(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 11)
        assert is_tutorial_complete(session, e.id) is True

    def test_is_not_complete_before_phase_11(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 5)
        assert is_tutorial_complete(session, e.id) is False


# ─────────────────────────────────────────────────────────────
# 4. System gate checks
# ─────────────────────────────────────────────────────────────
class TestSystemGates:
    @pytest.mark.parametrize("system,required_phase", list(TUTORIAL_SYSTEM_LOCKS.items()))
    def test_system_blocked_before_phase(self, session, system, required_phase):
        e = _entity(session)
        _force_phase(session, e.id, required_phase - 1)
        r = check_system_access(session, e.id, system)
        assert r["allowed"] is False
        assert r["reason"] == "tutorial_gate"

    @pytest.mark.parametrize("system,required_phase", list(TUTORIAL_SYSTEM_LOCKS.items()))
    def test_system_allowed_at_required_phase(self, session, system, required_phase):
        e = _entity(session)
        _force_phase(session, e.id, required_phase)
        r = check_system_access(session, e.id, system)
        assert r["allowed"] is True

    def test_unknown_system_always_allowed(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 0)
        r = check_system_access(session, e.id, "some_future_system")
        assert r["allowed"] is True

    def test_guilds_locked_until_phase_11(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 5)
        r = check_system_access(session, e.id, "guilds")
        assert r["allowed"] is False

    def test_all_unlocked_at_phase_11(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 11)
        for system in TUTORIAL_SYSTEM_LOCKS:
            r = check_system_access(session, e.id, system)
            assert r["allowed"] is True, f"{system} should be unlocked at phase 11"

    def test_gate_hint_present(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        r = check_system_access(session, e.id, "guilds")
        assert "hint" in r
        assert "Elaris Hollow" in r["hint"]


# ─────────────────────────────────────────────────────────────
# 5. Event rarity caps
# ─────────────────────────────────────────────────────────────
class TestEventRarityCap:
    def test_common_only_in_early_phases(self, session):
        e = _entity(session)
        for phase in range(1, 8):
            _force_phase(session, e.id, phase)
            assert get_max_event_rarity(session, e.id) == "common"

    def test_uncommon_at_phase_9(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 9)
        assert get_max_event_rarity(session, e.id) == "uncommon"

    def test_epic_after_tutorial_complete(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 11)
        assert get_max_event_rarity(session, e.id) == "epic"

    def test_max_rarity_all_phases_defined(self, session):
        e = _entity(session)
        for phase in range(1, 12):
            _force_phase(session, e.id, phase)
            rarity = get_max_event_rarity(session, e.id)
            assert rarity in ("common", "uncommon", "rare", "epic")


# ─────────────────────────────────────────────────────────────
# 6. Auto-advance hooks
# ─────────────────────────────────────────────────────────────
class TestAutoAdvanceHooks:
    def test_on_location_entered_triggers_phase2(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        r = on_location_entered(session, e.id, "Old Well Square")
        assert r["success"] is True
        assert r["phase"] == 2

    def test_on_location_entered_wrong_phase_no_advance(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 3)
        r = on_location_entered(session, e.id, "Old Well Square")
        assert r["success"] is False

    def test_on_location_entered_forest_triggers_phase3(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 2)
        r = on_location_entered(session, e.id, "Whispering Forest Edge")
        assert r["success"] is True
        assert r["phase"] == 3

    def test_on_item_returned_advances_to_phase4(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 3)
        r = on_item_returned(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 4

    def test_on_item_returned_wrong_phase(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 5)
        r = on_item_returned(session, e.id)
        assert r["success"] is False

    def test_on_combat_won_phase4_to_5(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 4)
        r = on_combat_won(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 5

    def test_on_combat_won_wrong_phase(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 2)
        r = on_combat_won(session, e.id)
        assert r["success"] is False

    def test_on_trade_completed_phase6_to_7(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 6)
        r = on_trade_completed(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 7

    def test_on_housing_rented_phase7_to_8(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 7)
        r = on_housing_rented(session, e.id)
        assert r["success"] is True
        assert r["phase"] == 8

    def test_ruins_triggers_phase9(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 8)
        r = on_location_entered(session, e.id, "Ruins of Velkar")
        assert r["success"] is True
        assert r["phase"] == 9

    def test_abandoned_shrine_triggers_phase10(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 9)
        r = on_location_entered(session, e.id, "Abandoned Shrine")
        assert r["success"] is True
        assert r["phase"] == 10


# ─────────────────────────────────────────────────────────────
# 7. GM context injection (TutorialEnforcer)
# ─────────────────────────────────────────────────────────────
class TestTutorialEnforcer:
    def test_context_empty_when_complete(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 11)
        ctx = build_tutorial_context(session, e.id)
        assert ctx == ""

    def test_context_empty_before_start(self, session):
        e = _entity(session)
        ctx = build_tutorial_context(session, e.id)
        assert ctx == ""

    def test_context_includes_phase_number(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 2)
        ctx = build_tutorial_context(session, e.id)
        assert "PHASE 2" in ctx

    def test_context_includes_phase_name(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 3)
        ctx = build_tutorial_context(session, e.id)
        assert "FIRST_TASK" in ctx.upper() or "FIRST TASK" in ctx.upper()

    def test_context_includes_directive(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        ctx = build_tutorial_context(session, e.id)
        assert "AWAKENING" in ctx.upper()
        assert len(ctx) > 100   # substantial directive

    def test_context_includes_system_locks(self, session):
        e = _entity(session)
        _force_phase(session, e.id, 1)
        ctx = build_tutorial_context(session, e.id)
        assert "guilds" in ctx

    def test_all_phases_have_non_empty_directive(self, session):
        e = _entity(session)
        for phase in range(1, 11):
            _force_phase(session, e.id, phase)
            ctx = build_tutorial_context(session, e.id)
            assert len(ctx) > 50, f"Phase {phase} directive is too short"

    def test_night_warning_injected_at_phase7(self, session):
        from app.db.time_service import get_world_time
        e = _entity(session)
        _force_phase(session, e.id, 7)
        # Force night
        wt = get_world_time(session)
        wt.current_time = wt.current_time.replace(hour=21)
        session.add(wt)
        session.commit()
        ctx = build_tutorial_context(session, e.id)
        assert "NIGHT" in ctx

    def test_no_night_warning_during_day(self, session):
        from app.db.time_service import get_world_time
        e = _entity(session)
        _force_phase(session, e.id, 7)
        wt = get_world_time(session)
        wt.current_time = wt.current_time.replace(hour=12)
        session.add(wt)
        session.commit()
        ctx = build_tutorial_context(session, e.id)
        assert "night_risk_active" not in ctx.lower() or "NIGHT" not in ctx


# ─────────────────────────────────────────────────────────────
# 8. Global clock integration
# ─────────────────────────────────────────────────────────────
class TestGlobalClockIntegration:
    def test_build_tutorial_context_advances_clock(self, session):
        """build_tutorial_context calls update_time — clock should advance."""
        from datetime import timedelta, timezone
        from app.db.time_service import get_world_time
        e = _entity(session)
        _force_phase(session, e.id, 2)

        wt = get_world_time(session)
        # Backdate last_real_tick by 10 real seconds
        from datetime import datetime
        wt.last_real_tick = datetime.now(timezone.utc) - timedelta(seconds=10)
        wt.time_scale = 60.0
        session.add(wt)
        session.commit()
        before = wt.current_time

        build_tutorial_context(session, e.id)

        wt2 = session.get(WorldTime, 1)
        assert wt2.current_time > before

    def test_tutorial_service_is_deterministic(self, session):
        """Same entity + same phase → same phase_name every time."""
        e = _entity(session)
        _force_phase(session, e.id, 5)
        names = {get_tutorial_state(session, e.id).phase for _ in range(5)}
        assert names == {5}


# ─────────────────────────────────────────────────────────────
# 9. Constants sanity
# ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_all_phases_defined_0_to_11(self):
        for p in range(0, 12):
            assert p in TUTORIAL_PHASES

    def test_phase_11_is_complete(self):
        assert TUTORIAL_PHASES[11] == "complete"

    def test_all_system_locks_reference_valid_phases(self):
        for sys, phase in TUTORIAL_SYSTEM_LOCKS.items():
            assert 0 <= phase <= 11, f"{sys} lock phase {phase} out of range"

    def test_rarity_caps_defined_for_all_tutorial_phases(self):
        for p in range(1, 12):
            assert p in TUTORIAL_MAX_RARITY

    def test_rarity_progression_never_downgrades(self):
        """Rarity caps should be monotonically non-decreasing as phase increases."""
        order = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3}
        prev = 0
        for p in range(1, 12):
            cur = order[TUTORIAL_MAX_RARITY[p]]
            assert cur >= prev, f"Phase {p} rarity cap decreased"
            prev = cur
