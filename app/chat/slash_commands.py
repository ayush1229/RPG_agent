"""
Slash command handler — in-chat game panel commands.

These bypass the GM/Arbiter pipeline entirely and send formatted
Chainlit system messages directly to the player.

Supported commands:
  /inventory  — item list grouped by type + gold balance
  /profile    — character stats, Tarot cards, equipped gear
  /quests     — tutorial phase as a quest log
  /help       — list all commands
"""

from __future__ import annotations

import chainlit as cl
from sqlmodel import select

from app.db.database import get_session
from app.db.models import InventoryItem, TarotEntity, TarotShard

# ─── Display helpers ──────────────────────────────────────────────────────────

_RARITY_ICON: dict[str, str] = {
    "common":    "⬜",
    "uncommon":  "🟩",
    "rare":      "🟦",
    "epic":      "🟪",
    "legendary": "🟨",
}
_TYPE_ICON: dict[str, str] = {
    "consumable": "🧪",
    "equipment":  "⚔️",
    "artifact":   "✨",
    "quest":      "📜",
    "material":   "🪨",
    "misc":       "📦",
}


def _ri(rarity: str | None) -> str:
    return _RARITY_ICON.get(rarity or "common", "⬜")


def _ti(item_type: str | None) -> str:
    return _TYPE_ICON.get(item_type or "misc", "📦")


# ─── Command handlers ─────────────────────────────────────────────────────────

async def handle_inventory(entity_id: int) -> None:
    with get_session() as session:
        from app.db.inventory_service import check_limits, get_gold

        items = list(
            session.exec(
                select(InventoryItem).where(InventoryItem.owner_id == entity_id)
            ).all()
        )
        gold   = get_gold(session, entity_id)
        limits = check_limits(session, entity_id)

    if not items:
        body = "*Your inventory is empty.*"
    else:
        groups: dict[str, list[InventoryItem]] = {}
        for item in items:
            groups.setdefault(item.item_type or "misc", []).append(item)

        lines: list[str] = []
        for itype in sorted(groups):
            group = groups[itype]
            lines.append(f"\n**{_ti(itype)} {itype.title()}**")
            lines.append("| Item | Qty | Rarity | Equipped |")
            lines.append("|------|-----|--------|:--------:|")
            for it in group:
                equipped = "✅" if it.is_equipped else "—"
                lines.append(
                    f"| {it.name} | {it.quantity} | {_ri(it.rarity)} {it.rarity or 'common'} | {equipped} |"
                )
        body = "\n".join(lines)

    await cl.Message(
        content=(
            f"## 🎒 Inventory\n"
            f"*{limits['slots_used']}/{limits['slots_max']} slots · "
            f"{limits['weight_used']}/{limits['weight_max']} kg*\n"
            f"{body}\n\n"
            f"💰 **Gold:** {gold}"
        ),
        author="🎮 System",
    ).send()


async def handle_profile(entity_id: int) -> None:
    with get_session() as session:
        entity = session.get(TarotEntity, entity_id)
        if not entity:
            await cl.Message(content="❌ No character found.", author="🎮 System").send()
            return

        equipped_items = list(
            session.exec(
                select(InventoryItem).where(
                    InventoryItem.owner_id == entity_id,
                    InventoryItem.is_equipped == True,  # noqa: E712
                )
            ).all()
        )
        shards = list(
            session.exec(select(TarotShard).where(TarotShard.owner_id == entity_id)).all()
        )
        card_names = [
            f"{s.lore.name} ({s.lore.arcana_type})" for s in shards if s.lore
        ]

    xp_to_next  = max(0, entity.level * 100 - entity.current_xp)
    hp_fill     = int((entity.current_health / max(1, entity.max_health)) * 10)
    hp_bar      = "█" * hp_fill + "░" * (10 - hp_fill)
    alignment   = "Upright ☀️" if entity.upright_capacity >= entity.reversed_capacity else "Reversed 🌑"

    equip_lines = (
        "\n".join(
            f"  - **{(it.equipped_slot or '?').title()}:** {it.name} {_ri(it.rarity)}"
            for it in equipped_items
        )
        or "  *Nothing equipped*"
    )

    await cl.Message(
        content=(
            f"## 🧙 Character Profile\n\n"
            f"**Level {entity.level}** · XP: {entity.current_xp} *(+{xp_to_next} to next)*\n\n"
            f"❤️ **HP:** `[{hp_bar}]` {entity.current_health}/{entity.max_health}\n"
            f"🔮 **MP:** {entity.current_upright_mana}/{entity.max_upright_mana}\n"
            f"⚖️ **Alignment:** {alignment}\n\n"
            f"**🃏 Tarot Cards:** {', '.join(card_names) or '*None*'}\n\n"
            f"**⚔️ Equipped:**\n{equip_lines}\n\n"
            f"**📊 Combat Stats:**\n"
            f"  - Attack Bonus: +{entity.damage_bonus}\n"
            f"  - Defense Bonus: +{entity.damage_reduction}"
        ),
        author="🎮 System",
    ).send()


async def handle_quests(entity_id: int) -> None:
    from app.db.models import Quest, QuestProgress
    from app.db.tutorial_service import TUTORIAL_PHASES, MAX_PHASE, get_tutorial_state

    with get_session() as session:
        ts = get_tutorial_state(session, entity_id)

        # Load all QuestProgress rows for this player
        progress_rows = list(
            session.exec(
                select(QuestProgress).where(QuestProgress.entity_id == entity_id)
            ).all()
        )
        # Load matching Quest definitions
        quest_map: dict[int, Quest] = {}
        for pr in progress_rows:
            q = session.get(Quest, pr.quest_id)
            if q:
                quest_map[pr.quest_id] = q

    # ── Real quests (from DB) ─────────────────────────────────────────────────
    real_active: list[str] = []
    real_done: list[str] = []
    _diff_icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "elite": "⚫"}

    for pr in progress_rows:
        q = quest_map.get(pr.quest_id)
        if not q:
            continue
        pct      = int((pr.progress / max(1, pr.goal)) * 100)
        d_icon   = _diff_icon.get(q.difficulty, "⚪")
        tag      = f"{d_icon} [{q.quest_type.title()}]"
        snippet  = q.description[:80] + ("…" if len(q.description) > 80 else "")
        if pr.is_completed:
            real_done.append(f"✅ **{q.name}** {tag}")
        else:
            real_active.append(
                f"🔵 **{q.name}** {tag}\n"
                f"   *{snippet}*\n"
                f"   Progress: {pr.progress}/{pr.goal} ({pct}%) · Reward: {q.xp_reward} XP"
            )

    # ── Tutorial phases as quests ─────────────────────────────────────────────
    tut_active: list[str] = []
    tut_done:   list[str] = []

    for phase_num, phase_name in sorted(TUTORIAL_PHASES.items()):
        if phase_num == 0:
            continue
        label = phase_name.replace("_", " ").title()
        if phase_num < ts.phase:
            tut_done.append(f"✅ *{label}* (Tutorial)")
        elif phase_num == ts.phase and ts.phase < MAX_PHASE:
            tut_active.append(f"🔵 *{label}* (Tutorial) ← current")

    all_active = real_active + tut_active
    all_done   = real_done   + tut_done

    active_str = "\n\n".join(all_active) if all_active else "*No active quests*"
    done_str   = "\n".join(all_done)     if all_done   else "*None yet*"

    await cl.Message(
        content=(
            f"## 📜 Quest Log\n\n"
            f"**Active**\n{active_str}\n\n"
            f"**Completed**\n{done_str}"
        ),
        author="🎮 System",
    ).send()


async def handle_help() -> None:
    await cl.Message(
        content=(
            "## 🎮 Commands\n\n"
            "| Command | Description |\n"
            "|---------|-------------|\n"
            "| `/inventory` | View your items, equipment, and gold |\n"
            "| `/profile` | View character stats, Tarot cards, and equipped gear |\n"
            "| `/quests` | View active and completed quests |\n"
            "| `/help` | Show this help message |\n\n"
            "*Commands are instant and do not advance the story.*"
        ),
        author="🎮 System",
    ).send()


# ─── Dispatcher ───────────────────────────────────────────────────────────────

_COMMANDS: dict[str, object] = {
    "/inventory": handle_inventory,
    "/profile":   handle_profile,
    "/quests":    handle_quests,
    "/help":      handle_help,
}


async def dispatch_slash_command(
    message_content: str, entity_id: int | None
) -> bool:
    """
    If the message starts with a known slash command, handle it and return True.
    Returns False for normal messages so the GM pipeline continues.
    """
    token = message_content.strip().split()[0].lower() if message_content.strip() else ""
    if not token.startswith("/"):
        return False

    handler = _COMMANDS.get(token)
    if handler is None:
        await cl.Message(
            content=f"❓ Unknown command `{token}`. Type `/help` for a list.",
            author="🎮 System",
        ).send()
        return True

    if token == "/help":
        await handler()  # type: ignore[call-arg]
    elif entity_id is None:
        await cl.Message(
            content="❌ No character found. Start a new session to create your character.",
            author="🎮 System",
        ).send()
    else:
        await handler(entity_id)  # type: ignore[call-arg]

    return True
