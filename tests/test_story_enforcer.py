"""
tests/test_story_enforcer.py
Tests for MainStoryState, story gates, arc advancement, and flag management.
"""
from __future__ import annotations
import json
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    DEFAULT_STORY_FLAGS, ARC_LEVEL_RANGES, MainStoryState,
    Quest, QuestProgress, TarotEntity,
)
from app.db.story_enforcer import (
    _load_or_create, _flags, check_prologue_gates,
    complete_interview, complete_card_draw,
    advance_arc_if_ready, get_story_state,
    gm_update_flags, set_gm_override, set_faction,
    mark_ascension_complete,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def entity(session):
    e = TarotEntity(entity_name="TestPlayer", level=1)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


class TestMainStoryStateCreation:
    def test_creates_default_state_for_new_entity(self, session, entity):
        state = _load_or_create(session, entity.id)
        assert state.entity_id == entity.id
        assert state.current_arc == 0
        flags = _flags(state)
        assert flags["interview_done"] is False
        assert flags["cards_drawn"] is False
        assert flags["awakening_triggered"] is False

    def test_idempotent_creation(self, session, entity):
        s1 = _load_or_create(session, entity.id)
        s2 = _load_or_create(session, entity.id)
        assert s1.id == s2.id
        rows = session.exec(
            select(MainStoryState).where(MainStoryState.entity_id == entity.id)
        ).all()
        assert len(rows) == 1

    def test_default_flags_match_schema(self, session, entity):
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        for key in DEFAULT_STORY_FLAGS:
            assert key in flags


class TestPrologueGates:
    def test_interview_gate_fires_first(self, session, entity):
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is not None
        assert "COUNCIL" in result or "void" in result.lower() or "QUESTION" in result

    def test_interview_done_shows_card_draw(self, session, entity):
        complete_interview(session, entity.id, alignment="order")
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is not None
        assert "CARD" in result.upper() or "card" in result.lower()

    def test_cards_done_shows_awakening(self, session, entity):
        complete_interview(session, entity.id, alignment="chaos")
        complete_card_draw(session, entity.id)
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is not None
        assert "awaken" in result.lower() or "AWAKENING" in result or "spark" in result.lower()

    def test_awakening_consumed_next_call_returns_none(self, session, entity):
        complete_interview(session, entity.id, alignment="balance")
        complete_card_draw(session, entity.id)
        # First call triggers awakening
        check_prologue_gates(session, entity.id, "hello")
        # Second call should return None (all gates passed)
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is None

    def test_alignment_stored_after_interview(self, session, entity):
        complete_interview(session, entity.id, alignment="order")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["alignment_tendency"] == "order"

    def test_cards_drawn_flag_set(self, session, entity):
        complete_interview(session, entity.id, alignment="chaos")
        complete_card_draw(session, entity.id)
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["cards_drawn"] is True


class TestArcAdvancement:
    def _complete_quest(self, session, entity_id: int, name: str) -> None:
        """Helper: create quest + mark progress complete."""
        q = session.exec(select(Quest).where(Quest.name == name)).first()
        if not q:
            q = Quest(name=name, description=".", quest_type="main",
                      difficulty="easy", required_level=1, xp_reward=0)
            session.add(q)
            session.flush()
        prog = QuestProgress(quest_id=q.id, entity_id=entity_id,
                             progress=1, goal=1, is_completed=True)
        session.add(prog)
        session.commit()

    def test_arc_does_not_advance_without_quests(self, session, entity):
        arc = advance_arc_if_ready(session, entity.id)
        assert arc == 0

    def test_arc_advances_after_prologue_quest_complete(self, session, entity):
        self._complete_quest(session, entity.id, "The Council Beyond Reality")
        arc = advance_arc_if_ready(session, entity.id)
        assert arc == 1

    def test_arc_caps_at_7(self, session, entity):
        state = _load_or_create(session, entity.id)
        state.current_arc = 7
        session.add(state)
        session.commit()
        arc = advance_arc_if_ready(session, entity.id)
        assert arc == 7


class TestStoryStateSnapshot:
    def test_get_story_state_shape(self, session, entity):
        snapshot = get_story_state(session, entity.id)
        assert "current_arc" in snapshot
        assert "current_quest_id" in snapshot
        assert "flags" in snapshot
        assert isinstance(snapshot["flags"], dict)


class TestGMOverride:
    def test_gm_cannot_update_flags_without_permission(self, session, entity):
        _load_or_create(session, entity.id)
        result = gm_update_flags(session, entity.id, {"interview_done": True})
        assert result["interview_done"] is False  # rejected

    def test_gm_can_update_flags_with_permission(self, session, entity):
        _load_or_create(session, entity.id)
        set_gm_override(session, entity.id, allowed=True)
        result = gm_update_flags(session, entity.id, {"interview_done": True})
        assert result["interview_done"] is True

    def test_set_faction(self, session, entity):
        _load_or_create(session, entity.id)
        set_faction(session, entity.id, "ally")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["faction_chosen"] == "ally"

    def test_mark_ascension(self, session, entity):
        _load_or_create(session, entity.id)
        mark_ascension_complete(session, entity.id)
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["ascension_complete"] is True
        assert state.current_arc == 7


class TestArcLevelRanges:
    def test_all_seven_arcs_defined(self):
        for arc in range(8):
            assert arc in ARC_LEVEL_RANGES

    def test_arc_ranges_are_ascending(self):
        # Each arc's minimum level >= previous arc's minimum
        prev_min = 0
        for arc in range(8):
            lo, hi = ARC_LEVEL_RANGES[arc]
            assert lo >= prev_min
            assert hi >= lo
            prev_min = lo
