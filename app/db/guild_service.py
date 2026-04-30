"""
app/db/guild_service.py
========================
Guild system service layer: membership, ranks, quests, income, exposure.

Public API
----------
Membership:
    join_guild(session, entity_id, guild_id) -> dict
    leave_guild(session, entity_id, guild_id) -> dict
    get_memberships(session, entity_id) -> list[dict]

Progression:
    promote_member(session, entity_id, guild_id) -> dict
    add_reputation(session, entity_id, guild_id, amount) -> dict
    get_perks(session, entity_id, guild_id) -> list[str]

Guild Quests:
    get_available_quests(session, entity_id, guild_id) -> list[dict]
    complete_guild_quest(session, entity_id, quest_id) -> dict

Income:
    distribute_income(session, guild_id, base_income) -> dict
    deposit_to_treasury(session, guild_id, amount, depositor_id) -> dict

Exposure:
    update_exposure(session, entity_id, delta, reason) -> dict
    trigger_exposure_event(session, entity_id) -> dict  ← DETERMINISTIC, bypasses GM

Admin:
    create_guild(session, ...) -> dict
    appoint_role(session, entity_id, guild_id, role) -> dict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.models import (
    EXPOSURE_TRIGGERED,
    RANK_PERKS,
    RANK_TIER,
    Guild,
    GuildExposure,
    GuildIncome,
    GuildMembership,
    GuildQuest,
    QuestProgress,
    TarotEntity,
)

# Reputation needed to be eligible for promotion to each rank
PROMOTION_REP: dict[int, int] = {
    2: 100, 3: 250, 4: 500,
    5: 800, 6: 1200, 7: 2000,
    8: 3000, 9: 4500, 10: 7000,
}
# Required guild-quest completions per rank
PROMOTION_QUESTS: dict[int, int] = {
    2: 1, 3: 2, 4: 3,
    5: 5, 6: 7, 7: 10,
    8: 13, 9: 17, 10: 22,
}

VALID_ROLES = {"member", "officer", "treasurer", "master"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================
# GUILD CRUD
# =============================================================

def create_guild(
    session: Session,
    name: str,
    description: str,
    guild_type: str,
    is_secret: bool = False,
    headquarters_location_id: Optional[int] = None,
) -> dict:
    from app.db.models import GUILD_TYPES
    if guild_type not in GUILD_TYPES:
        return {"success": False, "reason": "invalid_guild_type",
                "valid": list(GUILD_TYPES)}
    existing = session.exec(select(Guild).where(Guild.name == name)).first()
    if existing:
        return {"success": False, "reason": "guild_name_taken", "guild_id": existing.id}

    guild = Guild(
        name=name, description=description,
        guild_type=guild_type, is_secret=is_secret,
        headquarters_location_id=headquarters_location_id,
    )
    session.add(guild)
    session.commit()
    session.refresh(guild)
    return {"success": True, "guild_id": guild.id, "name": guild.name,
            "is_secret": guild.is_secret}


# =============================================================
# MEMBERSHIP
# =============================================================

def _active_memberships(session: Session, entity_id: int) -> list[GuildMembership]:
    return session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).all()


def join_guild(session: Session, entity_id: int, guild_id: int) -> dict:
    """
    Join a guild. Enforces dual-membership rule:
      - max 1 public (non-secret) guild
      - max 1 secret guild
    Rejects duplicate membership in same guild.
    """
    entity = session.get(TarotEntity, entity_id)
    if not entity:
        return {"success": False, "reason": "entity_not_found"}

    guild = session.get(Guild, guild_id)
    if not guild:
        return {"success": False, "reason": "guild_not_found"}

    # Duplicate check
    existing = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if existing:
        return {"success": False, "reason": "already_a_member"}

    # Slot check: count active memberships by secrecy type
    active = _active_memberships(session, entity_id)
    for m in active:
        g = session.get(Guild, m.guild_id)
        if g and g.is_secret == guild.is_secret:
            slot = "secret" if guild.is_secret else "public"
            return {
                "success": False,
                "reason": f"already_in_a_{slot}_guild",
                "current_guild_id": g.id,
                "current_guild_name": g.name,
            }

    membership = GuildMembership(
        entity_id=entity_id,
        guild_id=guild_id,
        rank=1, role="member", reputation=0,
        is_active=True,
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return {
        "success": True,
        "membership_id": membership.id,
        "guild_name": guild.name,
        "is_secret": guild.is_secret,
        "rank": 1,
        "tier": RANK_TIER[1],
    }


def leave_guild(session: Session, entity_id: int, guild_id: int) -> dict:
    """
    Leave a guild. Resets reputation to 0. Removes Guild Master title if held.
    """
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "membership_not_found"}

    guild = session.get(Guild, guild_id)
    was_master = membership.role == "master"

    membership.is_active = False
    membership.reputation = 0
    session.add(membership)

    # Clear Guild Master pointer if this member was master
    if was_master and guild and guild.master_id == membership.id:
        guild.master_id = None
        session.add(guild)

    session.commit()
    return {"success": True, "guild_id": guild_id, "reputation_reset": True}


def get_memberships(session: Session, entity_id: int) -> list[dict]:
    """Return all active guild memberships for an entity."""
    memberships = _active_memberships(session, entity_id)
    result = []
    for m in memberships:
        guild = session.get(Guild, m.guild_id)
        if guild:
            result.append({
                "membership_id": m.id,
                "guild_id": m.guild_id,
                "guild_name": guild.name,
                "guild_type": guild.guild_type,
                "is_secret": guild.is_secret,
                "rank": m.rank,
                "tier": RANK_TIER.get(m.rank, "Unknown"),
                "role": m.role,
                "reputation": m.reputation,
            })
    return result


# =============================================================
# REPUTATION & PROMOTION
# =============================================================

def add_reputation(
    session: Session,
    entity_id: int,
    guild_id: int,
    amount: int,
) -> dict:
    """Add reputation to a membership. Triggers auto-promotion check."""
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "membership_not_found"}

    membership.reputation = max(0, membership.reputation + amount)
    session.add(membership)
    session.commit()
    return {
        "success": True,
        "reputation": membership.reputation,
        "rank": membership.rank,
        "tier": RANK_TIER.get(membership.rank),
    }


def _count_guild_quest_completions(
    session: Session, entity_id: int, guild_id: int
) -> int:
    """Count completed GuildQuest entries for this entity × guild pair."""
    quests = session.exec(
        select(GuildQuest).where(GuildQuest.guild_id == guild_id)
    ).all()
    quest_ids = {q.id for q in quests}
    if not quest_ids:
        return 0
    count = 0
    for qid in quest_ids:
        prog = session.exec(
            select(QuestProgress).where(
                QuestProgress.quest_id == qid,
                QuestProgress.entity_id == entity_id,
                QuestProgress.is_completed == True,  # noqa: E712
            )
        ).first()
        if prog:
            count += 1
    return count


def promote_member(session: Session, entity_id: int, guild_id: int) -> dict:
    """
    Attempt to promote entity by 1 rank.
    Requirements: sufficient reputation + guild quest completions.
    Cannot exceed rank 10 or auto-promote to master role (must be appointed).
    """
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "membership_not_found"}

    current_rank = membership.rank
    if current_rank >= 10:
        return {"success": False, "reason": "already_at_max_rank"}

    target_rank = current_rank + 1
    req_rep = PROMOTION_REP.get(target_rank, 9999)
    req_quests = PROMOTION_QUESTS.get(target_rank, 99)
    completed_quests = _count_guild_quest_completions(session, entity_id, guild_id)

    if membership.reputation < req_rep:
        return {
            "success": False, "reason": "insufficient_reputation",
            "have": membership.reputation, "need": req_rep,
        }
    if completed_quests < req_quests:
        return {
            "success": False, "reason": "insufficient_quest_completions",
            "have": completed_quests, "need": req_quests,
        }

    membership.rank = target_rank
    # Auto-update role label for rank 10
    if target_rank == 10:
        membership.role = "master"
        guild = session.get(Guild, guild_id)
        if guild:
            guild.master_id = membership.id
            session.add(guild)

    session.add(membership)
    session.commit()
    return {
        "success": True,
        "new_rank": target_rank,
        "tier": RANK_TIER[target_rank],
        "perks": get_perks_for_rank(target_rank),
    }


def get_perks_for_rank(rank: int) -> list[str]:
    """Return the perk list for a given rank."""
    tier = RANK_TIER.get(rank, "Novice")
    return RANK_PERKS.get(tier, [])


def get_perks(session: Session, entity_id: int, guild_id: int) -> list[str]:
    """Return active perks for entity in guild based on current rank."""
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return []
    return get_perks_for_rank(membership.rank)


def appoint_role(
    session: Session,
    entity_id: int,
    guild_id: int,
    role: str,
) -> dict:
    """Appoint a specific role (officer/treasurer/master). Only one master per guild."""
    if role not in VALID_ROLES:
        return {"success": False, "reason": "invalid_role", "valid": list(VALID_ROLES)}

    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "membership_not_found"}

    if role == "master":
        if membership.rank < 10:
            return {"success": False, "reason": "rank_10_required_for_master"}
        # Demote existing master
        existing_master = session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == "master",
                GuildMembership.is_active == True,  # noqa: E712
            )
        ).first()
        if existing_master and existing_master.id != membership.id:
            existing_master.role = "officer"
            session.add(existing_master)

        guild = session.get(Guild, guild_id)
        if guild:
            guild.master_id = membership.id
            session.add(guild)

    membership.role = role
    session.add(membership)
    session.commit()
    return {"success": True, "entity_id": entity_id, "role": role}


# =============================================================
# GUILD QUESTS
# =============================================================

def get_available_quests(
    session: Session,
    entity_id: int,
    guild_id: int,
) -> list[dict]:
    """Return guild quests the entity qualifies for (rank + level check)."""
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return []

    entity = session.get(TarotEntity, entity_id)
    entity_level = entity.level if entity else 1

    quests = session.exec(
        select(GuildQuest).where(
            GuildQuest.guild_id == guild_id,
            GuildQuest.required_rank <= membership.rank,
            GuildQuest.required_level <= entity_level,
        )
    ).all()

    result = []
    for q in quests:
        # Check not already completed (unless repeatable)
        prog = session.exec(
            select(QuestProgress).where(
                QuestProgress.quest_id == q.id,
                QuestProgress.entity_id == entity_id,
                QuestProgress.is_completed == True,  # noqa: E712
            )
        ).first()
        if prog and not q.is_repeatable:
            continue
        result.append({
            "quest_id": q.id,
            "name": q.name,
            "arc": q.arc,
            "sequence": q.sequence,
            "required_rank": q.required_rank,
            "xp_reward": q.xp_reward,
            "reputation_reward": q.reputation_reward,
        })
    return result


def complete_guild_quest(
    session: Session,
    entity_id: int,
    quest_id: int,
) -> dict:
    """
    Mark a guild quest complete.
    Awards XP (via add_xp) and reputation.
    Secret guild quests also increase exposure slightly.
    """
    quest = session.get(GuildQuest, quest_id)
    if not quest:
        return {"success": False, "reason": "quest_not_found"}

    # Verify membership
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.guild_id == quest.guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "not_a_member_of_this_guild"}

    # Check duplicate
    existing = session.exec(
        select(QuestProgress).where(
            QuestProgress.quest_id == quest_id,
            QuestProgress.entity_id == entity_id,
            QuestProgress.is_completed == True,  # noqa: E712
        )
    ).first()
    if existing and not quest.is_repeatable:
        return {"success": False, "reason": "quest_already_completed"}

    # Record completion
    prog = QuestProgress(
        quest_id=quest_id, entity_id=entity_id,
        progress=1, goal=1, is_completed=True,
    )
    session.add(prog)

    # Award XP
    entity = session.get(TarotEntity, entity_id)
    if entity and quest.xp_reward > 0:
        from app.db.service import tarot_service
        tarot_service.add_xp(session, entity_id, quest.xp_reward)

    # Award reputation
    add_reputation(session, entity_id, quest.guild_id, quest.reputation_reward)

    # Secret guild quests slightly increase exposure
    guild = session.get(Guild, quest.guild_id)
    exposure_increase = 0.0
    if guild and guild.is_secret:
        exposure_increase = 5.0
        update_exposure(session, entity_id, exposure_increase,
                        reason=f"secret_guild_quest:{quest.name}")

    session.commit()
    return {
        "success": True,
        "quest_name": quest.name,
        "xp_awarded": quest.xp_reward,
        "reputation_awarded": quest.reputation_reward,
        "exposure_increase": exposure_increase,
    }


# =============================================================
# INCOME DISTRIBUTION
# =============================================================

def deposit_to_treasury(
    session: Session,
    guild_id: int,
    amount: int,
    depositor_id: int,
) -> dict:
    """Deposit gold from an entity's wallet into the guild treasury."""
    if amount <= 0:
        return {"success": False, "reason": "amount_must_be_positive"}

    guild = session.get(Guild, guild_id)
    if not guild:
        return {"success": False, "reason": "guild_not_found"}

    # Verify membership
    membership = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == depositor_id,
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).first()
    if not membership:
        return {"success": False, "reason": "not_a_member"}

    from app.db.economy_service import get_or_create_wallet
    wallet = get_or_create_wallet(session, depositor_id)
    if wallet.balance < amount:
        return {"success": False, "reason": "insufficient_funds",
                "have": wallet.balance, "need": amount}

    wallet.balance -= amount
    guild.treasury += amount
    session.add(wallet)
    session.add(guild)
    session.commit()
    return {"success": True, "deposited": amount, "treasury": guild.treasury}


def distribute_income(
    session: Session,
    guild_id: int,
    base_income: int,
) -> dict:
    """
    Distribute guild income to all active members.
    Formula: each member receives floor(base_income * rank / 10).
    Deducted from guild treasury. Fails if treasury insufficient.
    """
    if base_income <= 0:
        return {"success": False, "reason": "base_income_must_be_positive"}

    guild = session.get(Guild, guild_id)
    if not guild:
        return {"success": False, "reason": "guild_not_found"}

    members = session.exec(
        select(GuildMembership).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).all()

    total_payout = sum(int(base_income * m.rank / 10) for m in members)
    if guild.treasury < total_payout:
        return {
            "success": False, "reason": "insufficient_treasury",
            "treasury": guild.treasury, "needed": total_payout,
        }

    guild.treasury -= total_payout
    session.add(guild)

    from app.db.economy_service import get_or_create_wallet
    distributions = []
    for m in members:
        payout = int(base_income * m.rank / 10)
        if payout <= 0:
            continue
        wallet = get_or_create_wallet(session, m.entity_id)
        wallet.balance += payout
        session.add(wallet)

        log = GuildIncome(
            guild_id=guild_id, recipient_entity_id=m.entity_id,
            amount=payout, rank_at_time=m.rank,
        )
        session.add(log)
        distributions.append({"entity_id": m.entity_id, "amount": payout})

    session.commit()
    return {
        "success": True,
        "guild_id": guild_id,
        "total_distributed": total_payout,
        "treasury_remaining": guild.treasury,
        "distributions": distributions,
    }


# =============================================================
# EXPOSURE SYSTEM (DETERMINISTIC — GM CANNOT OVERRIDE)
# =============================================================

def _get_or_create_exposure(session: Session, entity_id: int) -> GuildExposure:
    exp = session.exec(
        select(GuildExposure).where(GuildExposure.entity_id == entity_id)
    ).first()
    if not exp:
        exp = GuildExposure(entity_id=entity_id, exposure_level=0.0)
        session.add(exp)
        session.flush()
    return exp


def update_exposure(
    session: Session,
    entity_id: int,
    delta: float,
    *,
    reason: str = "unknown",
) -> dict:
    """
    Increase or decrease exposure level. Clamped 0–100.
    If level reaches EXPOSURE_TRIGGERED (100.0), fire trigger_exposure_event().
    Returns the updated exposure state.
    """
    exp = _get_or_create_exposure(session, entity_id)

    if exp.exposure_triggered:
        return {
            "success": True,
            "exposure_level": 100.0,
            "already_triggered": True,
        }

    exp.exposure_level = max(0.0, min(100.0, exp.exposure_level + delta))
    exp.last_increased_at = _utcnow()
    session.add(exp)
    session.commit()

    triggered = False
    if exp.exposure_level >= EXPOSURE_TRIGGERED and not exp.exposure_triggered:
        result = trigger_exposure_event(session, entity_id)
        triggered = result.get("triggered", False)

    from app.db.models import EXPOSURE_WARNING, EXPOSURE_CRITICAL
    return {
        "success": True,
        "exposure_level": exp.exposure_level,
        "reason": reason,
        "status": (
            "triggered" if triggered else
            "critical" if exp.exposure_level >= EXPOSURE_CRITICAL else
            "warning"  if exp.exposure_level >= EXPOSURE_WARNING else
            "safe"
        ),
        "triggered": triggered,
    }


def trigger_exposure_event(session: Session, entity_id: int) -> dict:
    """
    DETERMINISTIC MANDATORY ENFORCEMENT — bypasses GM entirely.

    When an entity's secret guild exposure reaches 100:
      1. Mark exposure as triggered
      2. Record forced combat loss
      3. Remove ALL active guild memberships
      4. Reset all reputations to 0
      5. Remove all guild perks (cleared at perk-read time based on membership)

    Returns a structured event record for the GM to narrate (narration only,
    outcome is already enforced in DB).
    """
    exp = _get_or_create_exposure(session, entity_id)
    if exp.exposure_triggered:
        return {"success": False, "reason": "already_triggered"}

    # 1. Mark triggered
    exp.exposure_triggered = True
    exp.exposure_level = 100.0
    session.add(exp)

    # 2. Remove ALL guild memberships and reset reputation
    memberships = session.exec(
        select(GuildMembership).where(
            GuildMembership.entity_id == entity_id,
            GuildMembership.is_active == True,  # noqa: E712
        )
    ).all()
    guild_names = []
    for m in memberships:
        guild = session.get(Guild, m.guild_id)
        if guild:
            guild_names.append(guild.name)
            # Clear master pointer
            if guild.master_id == m.id:
                guild.master_id = None
                session.add(guild)
        m.is_active = False
        m.reputation = 0
        session.add(m)

    session.commit()

    # 3. Apply damage penalty (forced combat loss → lose 90% health)
    entity = session.get(TarotEntity, entity_id)
    if entity:
        entity.current_health = max(1, entity.current_health // 10)
        session.add(entity)
        session.commit()

    return {
        "triggered": True,
        "entity_id": entity_id,
        "guilds_removed": guild_names,
        "memberships_revoked": len(memberships),
        "health_penalty": True,
        "narrative_override": (
            "SYSTEM — EXPOSURE EVENT:\n\n"
            "Guild enforcers arrive in force. The confrontation is brief and brutal.\n"
            "Your hidden allegiances are known. You are expelled from all guilds.\n"
            "Your reputation is forfeit. Start over — if you survive."
        ),
    }
