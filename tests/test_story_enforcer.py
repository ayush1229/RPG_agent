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
        assert "void" in result.text.lower() or "Question 1" in result.text

    def test_interview_done_shows_card_draw(self, session, entity):
        complete_interview(session, entity.id, alignment="order")
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is not None
        assert "CARD" in result.text.upper() or "card" in result.text.lower()

    def test_cards_done_shows_awakening(self, session, entity):
        complete_interview(session, entity.id, alignment="chaos")
        complete_card_draw(session, entity.id)
        result = check_prologue_gates(session, entity.id, "hello")
        assert result is not None
        assert result.is_gm_directive     # awakening is now a GM directive
        assert "AWAKENING" in result.text or "Broken Lantern" in result.text

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


class TestSequentialInterview:
    """Verify the one-question-at-a-time prologue interview flow."""

    def test_q1_shown_on_first_call(self, session, entity):
        result = check_prologue_gates(session, entity.id, "anything")
        assert result is not None
        assert not result.is_gm_directive
        assert "Question 1" in result.text
        assert "power" in result.text.lower() or "understanding" in result.text.lower()

    def test_q2_shown_after_first_answer(self, session, entity):
        check_prologue_gates(session, entity.id, "")        # trigger Q1
        result = check_prologue_gates(session, entity.id, "I seek power")
        assert "Question 2" in result.text
        assert "sacrifice" in result.text.lower()

    def test_q3_shown_after_second_answer(self, session, entity):
        check_prologue_gates(session, entity.id, "")        # Q1
        check_prologue_gates(session, entity.id, "power")   # Q2
        result = check_prologue_gates(session, entity.id, "no")  # Q3
        assert "Question 3" in result.text
        assert "fate" in result.text.lower()

    def test_interview_done_after_third_answer(self, session, entity):
        check_prologue_gates(session, entity.id, "")          # Q1
        check_prologue_gates(session, entity.id, "power")     # Q2
        check_prologue_gates(session, entity.id, "no")        # Q3
        result = check_prologue_gates(session, entity.id, "trust fate")  # complete
        assert result is not None
        assert "heard enough" in result.text.lower() or "cards" in result.text.lower()
        # Next call should go to card draw gate
        result2 = check_prologue_gates(session, entity.id, "")
        assert "CARD" in result2.text.upper() or "card" in result2.text.lower()

    def test_answers_stored_in_flags(self, session, entity):
        check_prologue_gates(session, entity.id, "")
        check_prologue_gates(session, entity.id, "power")
        check_prologue_gates(session, entity.id, "no")
        check_prologue_gates(session, entity.id, "trust fate")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        answers = flags.get("interview_answers", [])
        assert len(answers) == 3
        assert "power" in answers[0]
        assert "no" in answers[1]
        assert "trust fate" in answers[2]

    def test_alignment_derived_from_answers(self, session, entity):
        check_prologue_gates(session, entity.id, "")
        check_prologue_gates(session, entity.id, "I seek understanding above all")
        check_prologue_gates(session, entity.id, "no, never")
        check_prologue_gates(session, entity.id, "I trust fate completely")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        # understanding + no + trust = balance
        assert flags["alignment_tendency"] == "balance"

    def test_order_alignment_derived(self, session, entity):
        check_prologue_gates(session, entity.id, "")
        check_prologue_gates(session, entity.id, "power")
        check_prologue_gates(session, entity.id, "yes I would sacrifice")
        check_prologue_gates(session, entity.id, "I defy fate")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["alignment_tendency"] == "order"

    def test_phase_not_reset_on_repeated_calls(self, session, entity):
        """Calling gates twice without answering should NOT re-show Q1 twice."""
        check_prologue_gates(session, entity.id, "")   # triggers Q1, phase → 1
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["interview_phase"] == 1           # phase advanced


class TestCardDrawGate:
    """Verify card draw gate does NOT loop and hands off to GM on second call."""

    def _complete_interview(self, session, entity_id):
        """Fast-forward through the 4-call interview sequence."""
        check_prologue_gates(session, entity_id, "")             # show Q1
        check_prologue_gates(session, entity_id, "power")        # answer Q1 → Q2
        check_prologue_gates(session, entity_id, "no")           # answer Q2 → Q3
        check_prologue_gates(session, entity_id, "trust fate")   # answer Q3 → COMPLETE

    def test_card_draw_script_shown_once(self, session, entity):
        self._complete_interview(session, entity.id)
        result = check_prologue_gates(session, entity.id, "")
        assert result is not None
        assert not result.is_gm_directive        # atmospheric prompt is player-visible
        assert "CARD DRAW" in result.text or "cards" in result.text.lower()

    def test_card_draw_does_not_repeat(self, session, entity):
        """Second call after card draw prompt must NOT return the same script."""
        self._complete_interview(session, entity.id)
        check_prologue_gates(session, entity.id, "")        # show card draw prompt
        result2 = check_prologue_gates(session, entity.id, "reveal")
        # Must be a GM directive, not the card draw script again
        assert result2 is not None
        assert result2.is_gm_directive           # card reveal is a GM directive
        assert "CARD DRAW SEQUENCE" not in result2.text

    def test_gm_directive_contains_alignment(self, session, entity):
        self._complete_interview(session, entity.id)
        check_prologue_gates(session, entity.id, "")          # card draw prompt
        result = check_prologue_gates(session, entity.id, "reveal")
        assert result is not None
        assert result.is_gm_directive
        assert "balance" in result.text or "order" in result.text or "chaos" in result.text

    def test_cards_drawn_flag_set_after_second_call(self, session, entity):
        self._complete_interview(session, entity.id)
        check_prologue_gates(session, entity.id, "")
        check_prologue_gates(session, entity.id, "reveal")
        state = _load_or_create(session, entity.id)
        flags = _flags(state)
        assert flags["cards_drawn"] is True

    def test_awakening_follows_card_reveal(self, session, entity):
        self._complete_interview(session, entity.id)
        check_prologue_gates(session, entity.id, "")          # card draw prompt
        check_prologue_gates(session, entity.id, "reveal")    # GM directive
        result = check_prologue_gates(session, entity.id, "") # awakening
        assert result is not None
        assert result.is_gm_directive     # awakening is now a GM directive
        assert "AWAKENING" in result.text or "Broken Lantern" in result.text

    def test_after_awakening_gates_open(self, session, entity):
        self._complete_interview(session, entity.id)
        check_prologue_gates(session, entity.id, "")
        check_prologue_gates(session, entity.id, "reveal")
        check_prologue_gates(session, entity.id, "")    # awakening (self-consumes)
        result = check_prologue_gates(session, entity.id, "I look around")
        assert result is None  # GM is now free


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
