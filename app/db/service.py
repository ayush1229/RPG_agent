from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import GlobalConfig, TarotEntity, TarotShard, TarotTransaction


class TarotService:
    """
    The ONLY authorised way to mutate energy balances.

    Conservation Law (Non-negotiable):
        SUM(TarotEntity.upright_energy)  == TOTAL_UPRIGHT_ENERGY  (always)
        SUM(TarotEntity.reversed_energy) == TOTAL_REVERSED_ENERGY (always)

    All writes are wrapped in try/except with session.rollback() to prevent
    partially-applied mutations corrupting the database if the commit fails.
    """

    # ── Sovereignty helper ────────────────────────────────────────────────────

    @staticmethod
    def get_sovereign_upright(entity: TarotEntity, session: Session) -> bool:
        """True if this entity holds more than 50% of total upright energy."""
        total_cfg = session.get(GlobalConfig, "TOTAL_UPRIGHT_ENERGY")
        if not total_cfg:
            return False
        return entity.upright_energy > 0.5 * total_cfg.value

    @staticmethod
    def get_sovereign_reversed(entity: TarotEntity, session: Session) -> bool:
        """True if this entity holds more than 50% of total reversed energy."""
        total_cfg = session.get(GlobalConfig, "TOTAL_REVERSED_ENERGY")
        if not total_cfg:
            return False
        return entity.reversed_energy > 0.5 * total_cfg.value

    # ── Core transfer ─────────────────────────────────────────────────────────

    def transfer_energy(
        self,
        session: Session,
        from_id: int,
        to_id: int,
        upright: int = 0,
        reversed: int = 0,
        reason: str = "",
    ) -> TarotTransaction:
        """
        Atomically transfer energy between two entities.

        Rules enforced:
          - At least one of upright or reversed must be > 0.
          - from_entity must have sufficient balance.
          - A TarotTransaction ledger row is always inserted.
          - Both entity balances are updated in the same commit.
          - On any commit failure, all in-memory changes are rolled back.

        Returns the committed TarotTransaction.
        Raises ValueError on rule violations.
        Raises RuntimeError if the database commit fails.
        """
        # ── Input validation ──────────────────────────────────────────────────
        if upright < 0 or reversed < 0:
            raise ValueError("Energy amounts must be non-negative.")
        if upright == 0 and reversed == 0:
            raise ValueError(
                "At least one of upright_amount or reversed_amount must be > 0."
            )

        from_entity = session.get(TarotEntity, from_id)
        to_entity = session.get(TarotEntity, to_id)

        if from_entity is None:
            raise ValueError(f"TarotEntity with id={from_id} not found.")
        if to_entity is None:
            raise ValueError(f"TarotEntity with id={to_id} not found.")

        if upright > from_entity.upright_energy:
            raise ValueError(
                f"Insufficient upright energy: need {upright}, "
                f"have {from_entity.upright_energy}."
            )
        if reversed > from_entity.reversed_energy:
            raise ValueError(
                f"Insufficient reversed energy: need {reversed}, "
                f"have {from_entity.reversed_energy}."
            )

        # ── Stage all mutations in memory BEFORE committing ───────────────────
        tx = TarotTransaction(
            from_entity_id=from_id,
            to_entity_id=to_id,
            upright_amount=upright,
            reversed_amount=reversed,
            reason=reason,
        )

        from_entity.upright_energy -= upright
        from_entity.reversed_energy -= reversed

        to_entity.upright_energy += upright
        to_entity.reversed_energy += reversed

        session.add(tx)
        session.add(from_entity)
        session.add(to_entity)

        # ── Atomic commit with rollback guard ─────────────────────────────────
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise RuntimeError(
                f"Database commit failed — all changes rolled back. "
                f"Reason: {exc}"
            ) from exc

        session.refresh(tx)
        return tx

    # ── Genesis mint (from_entity = None = ROOT creation) ───────────────────────

    def mint_energy(
        self,
        session: Session,
        to_id: int,
        upright: int = 0,
        reversed: int = 0,
        reason: str = "genesis",
    ) -> TarotTransaction:
        """
        Create energy from nothing (genesis only).  from_entity_id is None.
        Use only during root initialization — minting breaks conservation law
        if called after the root is running.
        """
        if upright < 0 or reversed < 0:
            raise ValueError("Energy amounts must be non-negative.")
        if upright == 0 and reversed == 0:
            raise ValueError("Must mint at least some energy.")

        to_entity = session.get(TarotEntity, to_id)
        if to_entity is None:
            raise ValueError(f"TarotEntity with id={to_id} not found.")

        tx = TarotTransaction(
            from_entity_id=None,
            to_entity_id=to_id,
            upright_amount=upright,
            reversed_amount=reversed,
            reason=reason,
        )
        to_entity.upright_energy += upright
        to_entity.reversed_energy += reversed

        session.add(tx)
        session.add(to_entity)

        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise RuntimeError(
                f"Database commit failed during mint — all changes rolled back. "
                f"Reason: {exc}"
            ) from exc

        session.refresh(tx)
        return tx

    # ── Shard creation ────────────────────────────────────────────────────────

    def create_shard(
        self,
        session: Session,
        owner_id: int,
        arcana_name: str,
        energy_type: str,
        value: int,
    ) -> TarotShard:
        """
        Attach an arcana shard to an entity.
        energy_type must be 'upright' or 'reversed'.
        value must be > 0.
        """
        if energy_type not in ("upright", "reversed"):
            raise ValueError("energy_type must be 'upright' or 'reversed'.")
        if value <= 0:
            raise ValueError("Shard value must be > 0.")

        owner = session.get(TarotEntity, owner_id)
        if owner is None:
            raise ValueError(f"TarotEntity with id={owner_id} not found.")

        shard = TarotShard(
            arcana_name=arcana_name,
            energy_type=energy_type,
            value=value,
            owner_id=owner_id,
        )
        session.add(shard)

        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise RuntimeError(
                f"Database commit failed while creating shard — rolled back. "
                f"Reason: {exc}"
            ) from exc

        session.refresh(shard)
        return shard

    # ── Read helpers ──────────────────────────────────────────────────────────

    def get_entity_by_name(
        self, session: Session, name: str
    ) -> TarotEntity | None:
        return session.exec(
            select(TarotEntity).where(TarotEntity.entity_name == name)
        ).first()

    def get_transaction_history(
        self, session: Session, entity_id: int
    ) -> list[TarotTransaction]:
        """Return all transactions involving this entity (sent or received)."""
        sent = session.exec(
            select(TarotTransaction).where(
                TarotTransaction.from_entity_id == entity_id
            )
        ).all()
        received = session.exec(
            select(TarotTransaction).where(
                TarotTransaction.to_entity_id == entity_id
            )
        ).all()
        # Merge and sort by timestamp
        return sorted(set(sent) | set(received), key=lambda t: t.timestamp)


# Module-level singleton
tarot_service = TarotService()
