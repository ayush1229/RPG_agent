"""
tests/test_guild_system.py
Tests: Guild CRUD, dual-membership, ranks, promotion, exposure event.
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import (
    EXPOSURE_TRIGGERED, GUILD_TYPES, RANK_PERKS, RANK_TIER,
    Guild, GuildExposure, GuildIncome, GuildMembership, GuildQuest,
    Location, QuestProgress, TarotEntity, Wallet,
)
from app.db.guild_service import (
    add_reputation, appoint_role, complete_guild_quest, create_guild,
    deposit_to_treasury, distribute_income, get_available_quests,
    get_memberships, get_perks, get_perks_for_rank,
    join_guild, leave_guild, promote_member,
    trigger_exposure_event, update_exposure,
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


def _location(session, name="HQ") -> Location:
    loc = Location(name=name, description=".", x=0.0, y=0.0)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _guild(session, name="TestGuild", guild_type="combat", is_secret=False) -> Guild:
    r = create_guild(session, name, "A test guild.", guild_type, is_secret)
    return session.get(Guild, r["guild_id"])


# ─────────────────────────────────────────────────────────────
# 1. Guild creation
# ─────────────────────────────────────────────────────────────
class TestCreateGuild:
    def test_create_public_guild(self, session):
        r = create_guild(session, "Fighters", "desc", "combat")
        assert r["success"] is True
        assert r["guild_id"] is not None
        assert r["is_secret"] is False

    def test_create_secret_guild(self, session):
        r = create_guild(session, "Shadow", "desc", "shadow", is_secret=True)
        assert r["success"] is True
        assert r["is_secret"] is True

    def test_duplicate_name_rejected(self, session):
        create_guild(session, "Dup", ".", "combat")
        r = create_guild(session, "Dup", ".", "magic")
        assert r["success"] is False
        assert r["reason"] == "guild_name_taken"

    def test_invalid_guild_type(self, session):
        r = create_guild(session, "Bad", ".", "barbarian")
        assert r["success"] is False

    def test_all_valid_types_accepted(self, session):
        for i, gt in enumerate(GUILD_TYPES):
            r = create_guild(session, f"G_{i}", ".", gt)
            assert r["success"] is True


# ─────────────────────────────────────────────────────────────
# 2. Join / Leave guild (dual-membership enforcement)
# ─────────────────────────────────────────────────────────────
class TestMembership:
    def test_join_public_guild(self, session):
        e = _entity(session)
        g = _guild(session)
        r = join_guild(session, e.id, g.id)
        assert r["success"] is True
        assert r["rank"] == 1
        assert r["tier"] == "Novice"

    def test_join_secret_guild(self, session):
        e = _entity(session)
        g = _guild(session, "Shadow", "shadow", is_secret=True)
        r = join_guild(session, e.id, g.id)
        assert r["success"] is True
        assert r["is_secret"] is True

    def test_dual_membership_allowed(self, session):
        e = _entity(session)
        pub = _guild(session, "Public", "combat", is_secret=False)
        sec = _guild(session, "Secret", "shadow", is_secret=True)
        r1 = join_guild(session, e.id, pub.id)
        r2 = join_guild(session, e.id, sec.id)
        assert r1["success"] is True
        assert r2["success"] is True

    def test_second_public_guild_rejected(self, session):
        e = _entity(session)
        g1 = _guild(session, "PubA", "combat")
        g2 = _guild(session, "PubB", "magic")
        join_guild(session, e.id, g1.id)
        r = join_guild(session, e.id, g2.id)
        assert r["success"] is False
        assert "public" in r["reason"]

    def test_second_secret_guild_rejected(self, session):
        e = _entity(session)
        s1 = _guild(session, "SecA", "shadow", is_secret=True)
        s2 = _guild(session, "SecB", "chaos", is_secret=True)
        join_guild(session, e.id, s1.id)
        r = join_guild(session, e.id, s2.id)
        assert r["success"] is False
        assert "secret" in r["reason"]

    def test_duplicate_join_rejected(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = join_guild(session, e.id, g.id)
        assert r["success"] is False
        assert r["reason"] == "already_a_member"

    def test_entity_not_found(self, session):
        g = _guild(session)
        r = join_guild(session, 99999, g.id)
        assert r["success"] is False

    def test_leave_guild(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = leave_guild(session, e.id, g.id)
        assert r["success"] is True
        assert r["reputation_reset"] is True

    def test_leave_resets_reputation(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        add_reputation(session, e.id, g.id, 500)
        leave_guild(session, e.id, g.id)
        # After leaving, membership is_active=False
        from sqlmodel import select
        m = session.exec(
            select(GuildMembership).where(
                GuildMembership.entity_id == e.id,
                GuildMembership.guild_id == g.id,
            )
        ).first()
        assert m.reputation == 0

    def test_leave_nonexistent_membership(self, session):
        e = _entity(session)
        g = _guild(session)
        r = leave_guild(session, e.id, g.id)
        assert r["success"] is False

    def test_get_memberships_returns_correct_guilds(self, session):
        e = _entity(session)
        pub = _guild(session, "PubX", "combat")
        sec = _guild(session, "SecX", "shadow", is_secret=True)
        join_guild(session, e.id, pub.id)
        join_guild(session, e.id, sec.id)
        mems = get_memberships(session, e.id)
        assert len(mems) == 2
        names = {m["guild_name"] for m in mems}
        assert "PubX" in names
        assert "SecX" in names

    def test_can_rejoin_after_leave(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        leave_guild(session, e.id, g.id)
        r = join_guild(session, e.id, g.id)
        assert r["success"] is True


# ─────────────────────────────────────────────────────────────
# 3. Reputation & Rank
# ─────────────────────────────────────────────────────────────
class TestReputationAndRank:
    def test_add_reputation(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = add_reputation(session, e.id, g.id, 200)
        assert r["success"] is True
        assert r["reputation"] == 200

    def test_reputation_not_negative(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = add_reputation(session, e.id, g.id, -500)
        assert r["reputation"] == 0

    def test_promote_without_enough_rep_fails(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = promote_member(session, e.id, g.id)
        assert r["success"] is False
        assert r["reason"] == "insufficient_reputation"

    def test_promote_with_enough_rep_and_quests(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        add_reputation(session, e.id, g.id, 100)

        # Create + complete required quest (1 for rank 2)
        gq = GuildQuest(guild_id=g.id, name="TestQ1", required_rank=1,
                        required_level=1, xp_reward=100, reputation_reward=50,
                        arc=1, sequence=1)
        session.add(gq)
        session.flush()
        prog = QuestProgress(quest_id=gq.id, entity_id=e.id,
                             progress=1, goal=1, is_completed=True)
        session.add(prog)
        session.commit()

        r = promote_member(session, e.id, g.id)
        assert r["success"] is True
        assert r["new_rank"] == 2
        assert r["tier"] == "Novice"

    def test_max_rank_cannot_promote(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        # Force rank to 10
        from sqlmodel import select
        m = session.exec(
            select(GuildMembership).where(
                GuildMembership.entity_id == e.id,
                GuildMembership.guild_id == g.id,
            )
        ).first()
        m.rank = 10
        session.add(m)
        session.commit()
        r = promote_member(session, e.id, g.id)
        assert r["success"] is False
        assert r["reason"] == "already_at_max_rank"


# ─────────────────────────────────────────────────────────────
# 4. Perks
# ─────────────────────────────────────────────────────────────
class TestPerks:
    def test_rank_1_perks(self, session):
        perks = get_perks_for_rank(1)
        assert "xp_bonus_5pct" in perks
        assert "guild_shop_access" in perks

    def test_rank_4_perks(self, session):
        perks = get_perks_for_rank(4)
        assert "item_discount_10pct" in perks

    def test_rank_7_perks(self, session):
        perks = get_perks_for_rank(7)
        assert "exclusive_ability_slot" in perks

    def test_rank_10_perks(self, session):
        perks = get_perks_for_rank(10)
        assert "faction_influence" in perks
        assert "treasury_control" in perks

    def test_get_perks_from_membership(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        perks = get_perks(session, e.id, g.id)
        assert "guild_shop_access" in perks

    def test_perks_empty_for_non_member(self, session):
        e = _entity(session)
        g = _guild(session)
        perks = get_perks(session, e.id, g.id)
        assert perks == []


# ─────────────────────────────────────────────────────────────
# 5. Guild quests
# ─────────────────────────────────────────────────────────────
class TestGuildQuests:
    def _setup(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        gq = GuildQuest(guild_id=g.id, name="TestMission", required_rank=1,
                        required_level=1, xp_reward=200, reputation_reward=80,
                        arc=1, sequence=1)
        session.add(gq)
        session.commit()
        session.refresh(gq)
        return e, g, gq

    def test_get_available_quests(self, session):
        e, g, gq = self._setup(session)
        quests = get_available_quests(session, e.id, g.id)
        assert len(quests) == 1
        assert quests[0]["name"] == "TestMission"

    def test_high_rank_quest_hidden_from_low_rank(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)   # rank 1
        gq = GuildQuest(guild_id=g.id, name="EliteOnly", required_rank=7,
                        required_level=1, xp_reward=500, reputation_reward=200,
                        arc=4, sequence=1)
        session.add(gq)
        session.commit()
        quests = get_available_quests(session, e.id, g.id)
        assert not any(q["name"] == "EliteOnly" for q in quests)

    def test_complete_guild_quest(self, session):
        e, g, gq = self._setup(session)
        r = complete_guild_quest(session, e.id, gq.id)
        assert r["success"] is True
        assert r["reputation_awarded"] == 80

    def test_cannot_complete_twice(self, session):
        e, g, gq = self._setup(session)
        complete_guild_quest(session, e.id, gq.id)
        r = complete_guild_quest(session, e.id, gq.id)
        assert r["success"] is False
        assert r["reason"] == "quest_already_completed"

    def test_repeatable_quest_allows_repeat(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        gq = GuildQuest(guild_id=g.id, name="Daily", required_rank=1,
                        required_level=1, xp_reward=50, reputation_reward=20,
                        arc=1, sequence=1, is_repeatable=True)
        session.add(gq)
        session.commit()
        session.refresh(gq)
        r1 = complete_guild_quest(session, e.id, gq.id)
        r2 = complete_guild_quest(session, e.id, gq.id)
        assert r1["success"] is True
        assert r2["success"] is True

    def test_non_member_cannot_complete_quest(self, session):
        e = _entity(session, "Outsider")
        g = _guild(session)
        gq = GuildQuest(guild_id=g.id, name="Q_nonmember", required_rank=1,
                        required_level=1, xp_reward=100, reputation_reward=50,
                        arc=1, sequence=1)
        session.add(gq)
        session.commit()
        session.refresh(gq)
        r = complete_guild_quest(session, e.id, gq.id)
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 6. Income & Treasury
# ─────────────────────────────────────────────────────────────
class TestIncomeSystem:
    def test_deposit_to_treasury(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        w = Wallet(owner_entity_id=e.id, balance=1000)
        session.add(w)
        session.commit()
        r = deposit_to_treasury(session, g.id, 500, e.id)
        assert r["success"] is True
        assert r["deposited"] == 500
        session.refresh(g)
        assert g.treasury == 500

    def test_deposit_insufficient_funds(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        w = Wallet(owner_entity_id=e.id, balance=10)
        session.add(w)
        session.commit()
        r = deposit_to_treasury(session, g.id, 500, e.id)
        assert r["success"] is False

    def test_distribute_income(self, session):
        e1 = _entity(session, "E1")
        e2 = _entity(session, "E2")
        g = _guild(session)
        join_guild(session, e1.id, g.id)
        join_guild(session, e2.id, g.id)

        # Fund treasury
        g.treasury = 10000
        session.add(g)
        session.commit()

        # Add wallets
        session.add(Wallet(owner_entity_id=e1.id, balance=0))
        session.add(Wallet(owner_entity_id=e2.id, balance=0))
        session.commit()

        r = distribute_income(session, g.id, base_income=1000)
        assert r["success"] is True
        # Rank 1 → 1000 * 1/10 = 100 each
        assert r["total_distributed"] == 200
        assert len(r["distributions"]) == 2

    def test_distribute_insufficient_treasury(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        g.treasury = 5
        session.add(g)
        session.commit()
        session.add(Wallet(owner_entity_id=e.id, balance=0))
        session.commit()
        r = distribute_income(session, g.id, base_income=1000)
        assert r["success"] is False
        assert r["reason"] == "insufficient_treasury"


# ─────────────────────────────────────────────────────────────
# 7. Role appointment
# ─────────────────────────────────────────────────────────────
class TestRoles:
    def test_appoint_officer(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = appoint_role(session, e.id, g.id, "officer")
        assert r["success"] is True
        assert r["role"] == "officer"

    def test_appoint_master_requires_rank_10(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = appoint_role(session, e.id, g.id, "master")
        assert r["success"] is False
        assert r["reason"] == "rank_10_required_for_master"

    def test_appoint_master_at_rank_10(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        from sqlmodel import select
        m = session.exec(
            select(GuildMembership).where(
                GuildMembership.entity_id == e.id,
                GuildMembership.guild_id == g.id,
            )
        ).first()
        m.rank = 10
        session.add(m)
        session.commit()
        r = appoint_role(session, e.id, g.id, "master")
        assert r["success"] is True

    def test_invalid_role_rejected(self, session):
        e = _entity(session)
        g = _guild(session)
        join_guild(session, e.id, g.id)
        r = appoint_role(session, e.id, g.id, "janitor")
        assert r["success"] is False


# ─────────────────────────────────────────────────────────────
# 8. Exposure system
# ─────────────────────────────────────────────────────────────
class TestExposureSystem:
    def test_update_exposure_increases(self, session):
        e = _entity(session)
        r = update_exposure(session, e.id, 30.0, reason="test")
        assert r["success"] is True
        assert r["exposure_level"] == pytest.approx(30.0)
        assert r["status"] == "safe"

    def test_exposure_warning_status(self, session):
        e = _entity(session)
        r = update_exposure(session, e.id, 55.0, reason="test")
        assert r["status"] == "warning"

    def test_exposure_critical_status(self, session):
        e = _entity(session)
        r = update_exposure(session, e.id, 80.0, reason="test")
        assert r["status"] == "critical"

    def test_exposure_clamped_at_100(self, session):
        e = _entity(session)
        update_exposure(session, e.id, 60.0, reason="step1")
        r = update_exposure(session, e.id, 200.0, reason="step2")
        assert r["exposure_level"] == pytest.approx(100.0)

    def test_exposure_decrease(self, session):
        e = _entity(session)
        update_exposure(session, e.id, 60.0, reason="up")
        r = update_exposure(session, e.id, -20.0, reason="down")
        assert r["exposure_level"] == pytest.approx(40.0)

    def test_exposure_cannot_go_negative(self, session):
        e = _entity(session)
        r = update_exposure(session, e.id, -50.0, reason="neg")
        assert r["exposure_level"] == pytest.approx(0.0)

    def test_trigger_exposure_event(self, session):
        e = _entity(session)
        pub = _guild(session, "PubExp", "combat")
        sec = _guild(session, "SecExp", "shadow", is_secret=True)
        join_guild(session, e.id, pub.id)
        join_guild(session, e.id, sec.id)

        r = trigger_exposure_event(session, e.id)
        assert r["triggered"] is True
        assert r["memberships_revoked"] == 2
        assert "narrative_override" in r

    def test_exposure_event_revokes_all_memberships(self, session):
        e = _entity(session)
        pub = _guild(session, "P_ev", "combat")
        sec = _guild(session, "S_ev", "shadow", is_secret=True)
        join_guild(session, e.id, pub.id)
        join_guild(session, e.id, sec.id)
        trigger_exposure_event(session, e.id)
        mems = get_memberships(session, e.id)
        assert mems == []

    def test_exposure_event_resets_health(self, session):
        e = _entity(session)
        e.current_health = 1000
        session.add(e)
        session.commit()
        trigger_exposure_event(session, e.id)
        session.refresh(e)
        assert e.current_health <= 100   # 90% penalty applied

    def test_exposure_event_fires_at_100(self, session):
        e = _entity(session)
        sec = _guild(session, "AutoExpose", "shadow", is_secret=True)
        join_guild(session, e.id, sec.id)
        # Push just below limit
        update_exposure(session, e.id, 95.0, reason="buildup")
        # This push should cross 100 and auto-trigger
        r = update_exposure(session, e.id, 10.0, reason="final_push")
        assert r["triggered"] is True

    def test_double_trigger_prevented(self, session):
        e = _entity(session)
        trigger_exposure_event(session, e.id)
        r = trigger_exposure_event(session, e.id)
        assert r["success"] is False
        assert r["reason"] == "already_triggered"

    def test_already_triggered_exposure_update_blocked(self, session):
        e = _entity(session)
        trigger_exposure_event(session, e.id)
        r = update_exposure(session, e.id, 10.0, reason="post")
        assert r.get("already_triggered") is True


# ─────────────────────────────────────────────────────────────
# 9. Rank / Tier constant sanity
# ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_all_ranks_have_tiers(self):
        for rank in range(1, 11):
            assert rank in RANK_TIER

    def test_all_tiers_have_perks(self):
        for tier in set(RANK_TIER.values()):
            assert tier in RANK_PERKS
            assert len(RANK_PERKS[tier]) > 0

    def test_rank_10_is_guild_master(self):
        assert RANK_TIER[10] == "Guild Master"

    def test_ranks_1_3_are_novice(self):
        for r in [1, 2, 3]:
            assert RANK_TIER[r] == "Novice"

    def test_ranks_7_9_are_elite(self):
        for r in [7, 8, 9]:
            assert RANK_TIER[r] == "Elite"
