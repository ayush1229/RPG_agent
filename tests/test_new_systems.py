"""
tests/test_new_systems.py

Status Effects, Combat Engine, and Movement/Spatial system tests.
All isolated with in-memory SQLite.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    from app.db.models import (  # noqa: F401
        CombatParticipant, CombatState, GlobalConfig, InventoryItem,
        Location, StatusEffect, TarotAbility, TarotCardLore,
        TarotCardTransaction, TarotEntity, TarotShard, TarotTransaction,
    )
    SQLModel.metadata.create_all(TEST_ENGINE)
    yield


@pytest.fixture()
def session():
    with Session(TEST_ENGINE) as s:
        yield s
        s.rollback()


@pytest.fixture()
def service():
    from app.db.service import TarotService
    return TarotService()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_entity(session, name, hp=100, x=0.0, y=0.0, upright=0, reversed=0):
    from app.db.models import TarotEntity
    e = TarotEntity(
        entity_name=name,
        current_health=hp,
        pos_x=x,
        pos_y=y,
        upright_capacity=upright,
        reversed_capacity=reversed,
    )
    e.current_upright_mana = e.max_upright_mana
    e.current_reversed_mana = e.max_reversed_mana
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def make_location(session, name, x=0.0, y=0.0, radius=100.0):
    from app.db.models import Location
    loc = Location(name=name, description="test location", x=x, y=y, radius=radius)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


# =============================================================================
# STATUS EFFECT SYSTEM
# =============================================================================

class TestStatusEffects:

    def test_apply_burn_creates_dot(self, session, service):
        e = make_entity(session, "BurnVictim")
        result = service.apply_status(session, e.id, "burn", value=10, duration=3)
        assert result["success"] is True
        assert result["action"] == "applied"
        assert result["status"] == "burn"

        from app.db.models import StatusEffect
        effect = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).first()
        assert effect is not None
        assert effect.name == "burn"
        assert effect.duration == 3
        assert effect.value == 10
        assert effect.effect_type == "damage_over_time"

    def test_apply_stun_creates_control(self, session, service):
        e = make_entity(session, "StunVictim")
        result = service.apply_status(session, e.id, "stun", value=0, duration=2)
        assert result["success"] is True

        from app.db.models import StatusEffect
        effect = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).first()
        assert effect.effect_type == "control"

    def test_non_stackable_refreshes_duration(self, session, service):
        e = make_entity(session, "RefreshVictim")
        service.apply_status(session, e.id, "bleed", value=5, duration=2, stackable=False)
        # Apply again — should refresh, not add a second row
        result = service.apply_status(session, e.id, "bleed", value=5, duration=4, stackable=False)
        assert result["action"] == "refreshed"

        from app.db.models import StatusEffect
        effects = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).all()
        assert len(effects) == 1
        assert effects[0].duration == 4  # max(2, 4)

    def test_stackable_adds_new_row(self, session, service):
        e = make_entity(session, "StackVictim")
        service.apply_status(session, e.id, "bleed", value=5, duration=2, stackable=True)
        service.apply_status(session, e.id, "bleed", value=3, duration=3, stackable=True)

        from app.db.models import StatusEffect
        effects = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).all()
        assert len(effects) == 2

    def test_unknown_status_rejected(self, session, service):
        e = make_entity(session, "UnknownStatusTarget")
        result = service.apply_status(session, e.id, "poison")
        assert result["success"] is False
        assert "unknown_status" in result["reason"]

    def test_process_status_ticks_dot_damage(self, session, service):
        e = make_entity(session, "BurnTickVictim", hp=100)
        service.apply_status(session, e.id, "burn", value=15, duration=2)

        result = service.process_status_effects(session, e.id)
        assert result["success"] is True
        assert any(fx.get("damage") == 15 for fx in result["effects"])
        session.refresh(e)
        assert e.current_health == 85

    def test_process_status_decrements_duration(self, session, service):
        e = make_entity(session, "DurationVictim", hp=200)
        service.apply_status(session, e.id, "burn", value=5, duration=3)
        service.process_status_effects(session, e.id)

        from app.db.models import StatusEffect
        effect = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).first()
        assert effect.duration == 2

    def test_process_status_removes_expired(self, session, service):
        e = make_entity(session, "ExpireVictim", hp=200)
        service.apply_status(session, e.id, "burn", value=5, duration=1)
        result = service.process_status_effects(session, e.id)

        assert any(fx.get("expired") for fx in result["effects"])
        from app.db.models import StatusEffect
        remaining = session.exec(
            select(StatusEffect).where(StatusEffect.target_entity_id == e.id)
        ).all()
        assert len(remaining) == 0

    def test_process_status_stun_sets_flag(self, session, service):
        e = make_entity(session, "StunTicker")
        service.apply_status(session, e.id, "stun", value=0, duration=2)
        result = service.process_status_effects(session, e.id)
        assert result["stunned"] is True

    def test_remove_expired_effects(self, session, service):
        from app.db.models import StatusEffect
        e = make_entity(session, "CleanupVictim", hp=200)
        # Manually insert a zero-duration effect
        fx = StatusEffect(name="burn", effect_type="damage_over_time", value=5,
                          duration=0, target_entity_id=e.id)
        session.add(fx)
        session.commit()

        result = service.remove_expired_effects(session, e.id)
        assert result["success"] is True
        assert result["removed"] == 1

    def test_shield_reduces_incoming_damage(self, session, service):
        """Shield effect should reduce incoming damage by value%."""
        attacker = make_entity(session, "ShieldAttacker", hp=100)
        defender = make_entity(session, "ShieldDefender", hp=100)
        # Apply 50% shield
        service.apply_status(session, defender.id, "shield", value=50, duration=2)
        # Basic attack for 20 → should land as 10
        result = service.basic_attack(session, attacker.id, defender.id, damage=20)
        assert result["success"] is True
        assert result["damage"] == 10
        session.refresh(defender)
        assert defender.current_health == 90

    def test_weaken_reduces_outgoing_damage(self, session, service):
        """Weaken on attacker should reduce their outgoing damage by value%."""
        attacker = make_entity(session, "WeakenAttacker", hp=100)
        defender = make_entity(session, "WeakenDefender", hp=100)
        # Apply 50% weaken to attacker
        service.apply_status(session, attacker.id, "weaken", value=50, duration=2)
        # Basic attack for 20 → should land as 10
        result = service.basic_attack(session, attacker.id, defender.id, damage=20)
        assert result["success"] is True
        assert result["damage"] == 10


# =============================================================================
# COMBAT ENGINE
# =============================================================================

class TestCombatEngine:

    def _make_two_sides(self, session):
        player = make_entity(session, f"Player_{id(session)}", hp=100)
        enemy = make_entity(session, f"Enemy_{id(session)}", hp=50)
        return player, enemy

    def test_init_combat_creates_state(self, session, service):
        player, enemy = self._make_two_sides(session)
        result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        assert result["success"] is True
        assert result["combat_id"] is not None
        assert result["current_actor_id"] == player.id  # higher initiative acts first
        assert result["turn_order"] == [player.id, enemy.id]

    def test_init_combat_rejects_dead_entity(self, session, service):
        player = make_entity(session, f"DeadPlayer_{id(session)}", hp=100)
        enemy = make_entity(session, f"LiveEnemy_{id(session)}", hp=50)
        player.current_health = 0
        session.add(player)
        session.commit()

        result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        assert result["success"] is False
        assert "entity_dead" in result["reason"]

    def test_advance_turn_cycles_actor(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]

        adv = service.advance_turn(session, combat_id)
        assert adv["success"] is True
        assert adv["combat_ended"] is False
        assert adv["current_actor_id"] == enemy.id
        assert adv["turn_number"] == 2

    def test_advance_turn_ends_on_all_enemies_dead(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]

        # Kill the enemy
        enemy.current_health = 0
        session.add(enemy)
        session.commit()

        adv = service.advance_turn(session, combat_id)
        assert adv["success"] is True
        assert adv["combat_ended"] is True
        assert adv["victor"] == "players"

    def test_advance_turn_ends_on_player_dead(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]

        # Kill the player
        player.current_health = 0
        session.add(player)
        session.commit()

        adv = service.advance_turn(session, combat_id)
        assert adv["success"] is True
        assert adv["combat_ended"] is True
        assert adv["victor"] == "enemies"

    def test_end_combat_force(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 5, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]

        result = service.end_combat(session, combat_id)
        assert result["success"] is True

        from app.db.models import CombatState
        state = session.get(CombatState, combat_id)
        assert state.is_active is False

    def test_advance_on_ended_combat_rejected(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 5, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]
        service.end_combat(session, combat_id)

        adv = service.advance_turn(session, combat_id)
        assert adv["success"] is False
        assert adv["reason"] == "combat_already_ended"

    def test_get_combat_state_returns_summary(self, session, service):
        player, enemy = self._make_two_sides(session)
        init_result = service.init_combat(session, [
            {"entity_id": player.id, "initiative": 10, "is_player_side": True},
            {"entity_id": enemy.id, "initiative": 5, "is_player_side": False},
        ])
        combat_id = init_result["combat_id"]

        state = service.get_combat_state(session, combat_id)
        assert state["success"] is True
        assert state["is_active"] is True
        assert len(state["participants"]) == 2

    def test_basic_attack_deals_damage(self, session, service):
        attacker = make_entity(session, f"BAttacker_{id(session)}", hp=100)
        target = make_entity(session, f"BTarget_{id(session)}", hp=100)
        result = service.basic_attack(session, attacker.id, target.id, damage=20)
        assert result["success"] is True
        assert result["damage"] == 20
        session.refresh(target)
        assert target.current_health == 80

    def test_basic_attack_dead_target_rejected(self, session, service):
        attacker = make_entity(session, f"BA2_{id(session)}", hp=100)
        target = make_entity(session, f"BT2_{id(session)}", hp=100)
        target.current_health = 0
        session.add(target)
        session.commit()
        result = service.basic_attack(session, attacker.id, target.id)
        assert result["success"] is False
        assert result["reason"] == "target_already_dead"


# =============================================================================
# MOVEMENT / SPATIAL SYSTEM
# =============================================================================

class TestMovement:

    def test_distance_calculation(self, service):
        assert service.distance(0, 0, 3, 4) == pytest.approx(5.0)
        assert service.distance(1, 1, 1, 1) == pytest.approx(0.0)

    def test_move_entity_updates_position(self, session, service):
        e = make_entity(session, "Mover1", x=0.0, y=0.0)
        result = service.move_entity(session, e.id, 10.0, 20.0)
        assert result["success"] is True
        session.refresh(e)
        assert e.pos_x == pytest.approx(10.0)
        assert e.pos_y == pytest.approx(20.0)

    def test_move_within_location_allowed(self, session, service):
        e = make_entity(session, "Mover2", x=0.0, y=0.0)
        loc = make_location(session, "SmallRoom", x=0.0, y=0.0, radius=50.0)
        result = service.move_entity(session, e.id, 30.0, 30.0, location_id=loc.id)
        assert result["success"] is True

    def test_move_outside_location_rejected(self, session, service):
        e = make_entity(session, "Mover3", x=0.0, y=0.0)
        loc = make_location(session, "TinyRoom", x=0.0, y=0.0, radius=5.0)
        result = service.move_entity(session, e.id, 100.0, 100.0, location_id=loc.id)
        assert result["success"] is False
        assert result["reason"] == "out_of_bounds"
        assert "distance_from_center" in result

    def test_move_nonexistent_entity_rejected(self, session, service):
        result = service.move_entity(session, 99999, 5.0, 5.0)
        assert result["success"] is False
        assert result["reason"] == "entity_not_found"

    def test_get_entities_in_radius(self, session, service):
        center = make_entity(session, f"RadCenter_{id(session)}", x=0.0, y=0.0)
        near = make_entity(session, f"RadNear_{id(session)}", x=5.0, y=0.0)
        far = make_entity(session, f"RadFar_{id(session)}", x=500.0, y=500.0)

        entities = service.get_entities_in_radius(session, cx=0.0, cy=0.0, radius=10.0)
        ids = [e.id for e in entities]
        assert near.id in ids
        assert far.id not in ids

    def test_location_has_spatial_fields(self, session):
        from app.db.models import Location
        loc = Location(name="Spatial Test Zone", description="Has coords",
                       x=10.0, y=20.0, radius=75.0)
        session.add(loc)
        session.commit()
        session.refresh(loc)
        assert loc.x == pytest.approx(10.0)
        assert loc.y == pytest.approx(20.0)
        assert loc.radius == pytest.approx(75.0)

    def test_entity_has_position_fields(self, session):
        e = make_entity(session, "PosEntity", x=3.5, y=7.2)
        session.refresh(e)
        assert e.pos_x == pytest.approx(3.5)
        assert e.pos_y == pytest.approx(7.2)
