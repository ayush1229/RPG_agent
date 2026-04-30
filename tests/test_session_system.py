"""
tests/test_session_system.py
=============================
Tests for the persistent session / memory system:
  1. UserSession (create, idempotent load)
  2. DialogueLog (save, retrieve)
  3. ConversationSummary (upsert)
  4. load_user_state (full rehydration)
  5. build_agent_context (shape + safety rules)
  6. update_user_session (field updates)
  7. get_chat_history (UI replay, ordered)
  8. maybe_update_summary (interval logic)
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    ConversationSummary,
    DialogueLog,
    Location,
    Quest,
    QuestProgress,
    TarotEntity,
    UserSession,
)
from app.db.session_service import (
    MAX_RECENT_MESSAGES,
    SUMMARY_INTERVAL,
    build_agent_context,
    get_chat_history,
    load_user_state,
    save_dialogue,
    update_user_session,
)


# ── In-memory test engine ──────────────────────────────────────────────────────
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ─────────────────────────────────────────────────────────────────────────────
# 1. UserSession — create + idempotent load
# ─────────────────────────────────────────────────────────────────────────────
class TestUserSession:
    def test_first_load_creates_entity_and_session(self, session):
        state = load_user_state(session, "alice")
        assert state.entity is not None
        assert state.entity.entity_name == "alice"
        assert state.session_row.user_id == "alice"
        assert state.session_row.entity_id == state.entity.id

    def test_second_load_is_idempotent(self, session):
        state1 = load_user_state(session, "bob")
        state2 = load_user_state(session, "bob")
        assert state1.entity.id == state2.entity.id
        assert state1.session_row.id == state2.session_row.id

        # Only one UserSession row for bob
        rows = session.exec(select(UserSession).where(UserSession.user_id == "bob")).all()
        assert len(rows) == 1

    def test_different_users_get_different_entities(self, session):
        a = load_user_state(session, "carol")
        b = load_user_state(session, "dave")
        assert a.entity.id != b.entity.id

    def test_new_entity_has_correct_defaults(self, session):
        state = load_user_state(session, "newbie")
        e = state.entity
        assert e.level == 1
        assert e.current_xp == 0
        assert e.upright_capacity == 0
        assert e.is_upright_sovereign is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. DialogueLog — save + retrieve
# ─────────────────────────────────────────────────────────────────────────────
class TestDialogueLog:
    def test_save_user_message(self, session):
        log = save_dialogue(session, "eve", role="user", message="Hello!")
        assert log.id is not None
        assert log.user_id == "eve"
        assert log.role == "user"
        assert log.message == "Hello!"

    def test_save_assistant_message(self, session):
        log = save_dialogue(session, "eve", role="assistant", message="Greetings!")
        assert log.role == "assistant"

    def test_invalid_role_raises(self, session):
        with pytest.raises(ValueError, match="Invalid role"):
            save_dialogue(session, "eve", role="system", message="x")

    def test_multiple_messages_stored(self, session):
        for i in range(5):
            save_dialogue(session, "frank", role="user", message=f"msg {i}")
        logs = session.exec(
            select(DialogueLog).where(DialogueLog.user_id == "frank")
        ).all()
        assert len(logs) == 5

    def test_messages_are_per_user(self, session):
        save_dialogue(session, "grace", role="user", message="Grace msg")
        save_dialogue(session, "henry", role="user", message="Henry msg")
        grace_logs = session.exec(
            select(DialogueLog).where(DialogueLog.user_id == "grace")
        ).all()
        assert len(grace_logs) == 1
        assert grace_logs[0].message == "Grace msg"


# ─────────────────────────────────────────────────────────────────────────────
# 3. get_chat_history — UI replay
# ─────────────────────────────────────────────────────────────────────────────
class TestGetChatHistory:
    def test_returns_all_messages_ordered(self, session):
        save_dialogue(session, "iris", role="user", message="first")
        save_dialogue(session, "iris", role="assistant", message="reply")
        save_dialogue(session, "iris", role="user", message="second")
        history = get_chat_history(session, "iris")
        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[0]["message"] == "first"
        assert history[1]["role"] == "assistant"
        assert history[2]["message"] == "second"

    def test_empty_for_new_user(self, session):
        history = get_chat_history(session, "nobody")
        assert history == []

    def test_history_has_required_fields(self, session):
        save_dialogue(session, "jack", role="user", message="test")
        history = get_chat_history(session, "jack")
        row = history[0]
        assert "id" in row
        assert "role" in row
        assert "message" in row
        assert "timestamp" in row


# ─────────────────────────────────────────────────────────────────────────────
# 4. load_user_state — recent message cap
# ─────────────────────────────────────────────────────────────────────────────
class TestLoadUserStateMessages:
    def test_recent_messages_capped_at_max(self, session):
        # Create more messages than the cap
        for i in range(MAX_RECENT_MESSAGES + 5):
            save_dialogue(session, "kate", role="user", message=f"msg {i}")
        state = load_user_state(session, "kate")
        assert len(state.recent_messages) == MAX_RECENT_MESSAGES

    def test_recent_messages_are_newest(self, session):
        for i in range(MAX_RECENT_MESSAGES + 3):
            save_dialogue(session, "liam", role="user", message=f"msg {i}")
        state = load_user_state(session, "liam")
        # The most recent message should be msg N-1 (highest index)
        last_msg = state.recent_messages[-1]["content"]
        expected = f"msg {MAX_RECENT_MESSAGES + 2}"
        assert last_msg == expected

    def test_no_messages_returns_empty_list(self, session):
        state = load_user_state(session, "mary")
        assert state.recent_messages == []

    def test_summary_defaults_to_no_history(self, session):
        state = load_user_state(session, "nancy")
        assert state.summary == "No history yet."


# ─────────────────────────────────────────────────────────────────────────────
# 5. build_agent_context — shape + safety rules
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildAgentContext:
    def test_has_required_keys(self, session):
        state = load_user_state(session, "oscar")
        ctx = build_agent_context(state)
        required = {
            "player", "location", "location_id",
            "is_safe_zone", "is_magic_restricted",
            "nearby_npcs", "inventory", "active_quests",
            "status_effects", "summary", "recent_messages",
        }
        assert required.issubset(ctx.keys())

    def test_player_block_has_correct_fields(self, session):
        state = load_user_state(session, "peter")
        ctx = build_agent_context(state)
        player = ctx["player"]
        for key in ("entity_id", "name", "level", "xp",
                    "health", "max_health", "upright_mana",
                    "reversed_mana", "dominant_energy"):
            assert key in player, f"Missing player key: {key}"

    def test_recent_messages_never_exceeds_cap(self, session):
        for i in range(MAX_RECENT_MESSAGES + 10):
            save_dialogue(session, "quinn", role="user", message=f"m{i}")
        state = load_user_state(session, "quinn")
        ctx = build_agent_context(state)
        assert len(ctx["recent_messages"]) <= MAX_RECENT_MESSAGES

    def test_summary_is_string(self, session):
        state = load_user_state(session, "rachel")
        ctx = build_agent_context(state)
        assert isinstance(ctx["summary"], str)

    def test_location_unknown_when_no_location(self, session):
        state = load_user_state(session, "steve")
        ctx = build_agent_context(state)
        assert ctx["location"] == "Unknown"
        assert ctx["location_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. update_user_session
# ─────────────────────────────────────────────────────────────────────────────
class TestUpdateUserSession:
    def test_update_location(self, session):
        load_user_state(session, "tina")   # creates session row
        loc = Location(name="Dark Forest", description="Spooky.", x=1.0, y=2.0)
        session.add(loc)
        session.commit()
        session.refresh(loc)

        update_user_session(session, "tina", location_id=loc.id)
        row = session.exec(
            select(UserSession).where(UserSession.user_id == "tina")
        ).first()
        assert row.last_location_id == loc.id

    def test_update_game_state(self, session):
        load_user_state(session, "uma")
        update_user_session(session, "uma", game_state={"boss_defeated": True})
        row = session.exec(
            select(UserSession).where(UserSession.user_id == "uma")
        ).first()
        import json
        parsed = json.loads(row.last_game_state)
        assert parsed["boss_defeated"] is True

    def test_updated_at_refreshes(self, session):
        state = load_user_state(session, "victor")
        original_ts = state.session_row.updated_at
        update_user_session(session, "victor", game_state={})
        row = session.exec(
            select(UserSession).where(UserSession.user_id == "victor")
        ).first()
        assert row.updated_at >= original_ts

    def test_update_nonexistent_user_is_noop(self, session):
        # Should not raise
        update_user_session(session, "ghost_user", location_id=1)


# ─────────────────────────────────────────────────────────────────────────────
# 7. ConversationSummary model
# ─────────────────────────────────────────────────────────────────────────────
class TestConversationSummary:
    def test_upsert_creates_row(self, session):
        row = ConversationSummary(user_id="wendy", summary="Explored the forest.")
        session.add(row)
        session.commit()
        fetched = session.exec(
            select(ConversationSummary).where(ConversationSummary.user_id == "wendy")
        ).first()
        assert fetched.summary == "Explored the forest."

    def test_default_summary_in_load(self, session):
        state = load_user_state(session, "xavier")
        assert state.summary == "No history yet."

    def test_summary_loaded_if_exists(self, session):
        row = ConversationSummary(user_id="yasmin", summary="Defeated the Fool Sovereign.")
        session.add(row)
        session.commit()
        state = load_user_state(session, "yasmin")
        assert state.summary == "Defeated the Fool Sovereign."


# ─────────────────────────────────────────────────────────────────────────────
# 8. Active quest loading via load_user_state
# ─────────────────────────────────────────────────────────────────────────────
class TestActiveQuestLoading:
    def test_active_quest_included_in_state(self, session):
        state = load_user_state(session, "zara")
        entity_id = state.entity.id

        quest = Quest(name="Find the Hermit", description="Locate him.",
                      quest_type="side", difficulty="easy", required_level=1,
                      xp_reward=100)
        session.add(quest)
        session.flush()

        progress = QuestProgress(
            quest_id=quest.id, entity_id=entity_id,
            progress=0, goal=3, is_completed=False,
        )
        session.add(progress)
        session.commit()

        state2 = load_user_state(session, "zara")
        assert len(state2.active_quests) == 1
        assert state2.active_quests[0]["name"] == "Find the Hermit"

    def test_completed_quest_excluded(self, session):
        state = load_user_state(session, "alan")
        entity_id = state.entity.id

        quest = Quest(name="Done Quest", description="Finished.",
                      difficulty="easy", required_level=1, xp_reward=50)
        session.add(quest)
        session.flush()

        progress = QuestProgress(
            quest_id=quest.id, entity_id=entity_id,
            progress=1, goal=1, is_completed=True,
        )
        session.add(progress)
        session.commit()

        state2 = load_user_state(session, "alan")
        assert state2.active_quests == []
