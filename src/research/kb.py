"""Phase 4.0 Strategy Knowledge Base (design §5 4.0 / §3.1-3.2).

Two management classes over the Phase 4 ORM tables:

* :class:`RawPool` -- the raw strategy pool: unimplemented ideas / rules /
  sources captured for later validation (``raw_strategies``).
* :class:`StrategyRegistry` -- the *executable* formal library: validated
  strategies mapped to a runnable implementation, with their verification
  evidence (``strategy_registry``). On first use the 10 ``strategy_library``
  strategies are seeded as ``active`` so the daily-alpha engine has a working
  library immediately.

All writes go through the session (mirrors :mod:`research.registry`), and the
seed is idempotent (``merge``) so re-running never duplicates rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from research.market_regime import REGIME_CATEGORY_FIT
from research.models import RawStrategy
from research.models import StrategyRegistry as StrategyRegistryModel
from research.strategy_library import list_strategies


def _new_raw_id() -> str:
    """A human-readable raw strategy id, e.g. ``RAW-2026-0720-1A2B``."""
    return f"RAW-{date.today().strftime('%Y-%m%d')}-{uuid.uuid4().hex[:4].upper()}"


def _new_validation_id() -> str:
    return f"val_{uuid.uuid4().hex[:8]}"


class RawPool:
    """CRUD over the raw strategy pool (``raw_strategies``)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        name: str,
        *,
        source_type: str = "manual",
        source: str | None = None,
        description: str | None = None,
        rules: str | None = None,
        strategy_id: str | None = None,
        status: str = "raw",
    ) -> str:
        """Insert a raw strategy and return its id (auto-generated if omitted)."""
        sid = strategy_id or _new_raw_id()
        row = RawStrategy(
            strategy_id=sid,
            name=name,
            source_type=source_type,
            source=source,
            original_description=description,
            original_rules=rules,
            status=status,
        )
        self.session.add(row)
        self.session.commit()
        return sid

    def get(self, strategy_id: str) -> RawStrategy | None:
        return self.session.get(RawStrategy, strategy_id)

    def list(self, status: str | None = None) -> list[RawStrategy]:
        """List raw strategies (newest first); optionally filtered by status."""
        q = self.session.query(RawStrategy)
        if status is not None:
            q = q.filter_by(status=status)
        return list(q.order_by(RawStrategy.created_at.desc()).all())

    def set_status(self, strategy_id: str, status: str) -> bool:
        """Move a raw strategy to a new status. Returns False if unknown."""
        row = self.session.get(RawStrategy, strategy_id)
        if row is None:
            return False
        row.status = status
        self.session.commit()
        return True


class StrategyRegistry:
    """Management of the executable formal library (``strategy_registry``)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Seed (idempotent)
    # ------------------------------------------------------------------ #
    def seed_builtins(self, *, overwrite: bool = False) -> int:
        """Seed the 10 ``strategy_library`` strategies as ``active``.

        ``best_fit_regimes`` is derived from the strategy category via
        :data:`REGIME_CATEGORY_FIT` (design §4.2 / §5 4.0). Re-running is safe:
        existing rows are kept unless ``overwrite`` rebuilds them.
        """
        seeded = 0
        for strat in list_strategies():
            spec = strat.spec
            sid = spec.name
            existing = self.session.get(StrategyRegistryModel, sid)
            if existing is not None and not overwrite:
                continue
            regimes = [r for r, cats in REGIME_CATEGORY_FIT.items() if spec.category in cats]
            row = StrategyRegistryModel(
                strategy_id=sid,
                name=spec.display_name,
                category=spec.category,
                executable_ref=spec.name,  # strategy_library registration name
                status="active",
                best_fit_regimes=json.dumps(regimes, ensure_ascii=False),
            )
            self.session.merge(row)
            seeded += 1
        self.session.commit()
        return seeded

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #
    def get(self, strategy_id: str) -> StrategyRegistryModel | None:
        return self.session.get(StrategyRegistryModel, strategy_id)

    def list_active(self) -> list[StrategyRegistryModel]:
        """All library entries (newest first); not restricted to ``active`` so
        degraded/retired strategies stay visible for audit."""
        return list(
            self.session.query(StrategyRegistryModel)
            .order_by(StrategyRegistryModel.added_at.desc())
            .all()
        )

    def list_by_status(self, status: str) -> list[StrategyRegistryModel]:
        return list(self.session.query(StrategyRegistryModel).filter_by(status=status).all())

    # ------------------------------------------------------------------ #
    # Write / update
    # ------------------------------------------------------------------ #
    def add(
        self,
        strategy_id: str,
        name: str,
        category: str,
        executable_ref: str,
        *,
        status: str = "validated",
        best_fit_regimes: list[str] | None = None,
    ) -> None:
        """Insert a new library entry (e.g. promote a raw strategy)."""
        row = StrategyRegistryModel(
            strategy_id=strategy_id,
            name=name,
            category=category,
            executable_ref=executable_ref,
            status=status,
            best_fit_regimes=(
                json.dumps(best_fit_regimes, ensure_ascii=False) if best_fit_regimes else None
            ),
        )
        self.session.merge(row)
        self.session.commit()

    def update_validation(
        self,
        strategy_id: str,
        *,
        validation_run_id: str | None = None,
        quality_star: float | None = None,
        reliability_score: float | None = None,
        gate_passed: bool | None = None,
        best_fit_regimes: list[str] | None = None,
        status: str | None = None,
    ) -> bool:
        """Record a validation outcome onto a library entry. Returns False if
        the strategy is unknown."""
        row = self.session.get(StrategyRegistryModel, strategy_id)
        if row is None:
            return False
        if validation_run_id is not None:
            row.validation_run_id = validation_run_id
        if quality_star is not None:
            row.quality_star = quality_star
        if reliability_score is not None:
            row.reliability_score = reliability_score
        if gate_passed is not None:
            row.gate_passed = gate_passed
        if best_fit_regimes is not None:
            row.best_fit_regimes = json.dumps(best_fit_regimes, ensure_ascii=False)
        # Status follows the gate unless explicitly overridden (4.1: evidence only
        # suggests; the gate result is the authoritative pass/fail signal).
        if status is not None:
            row.status = status
        elif gate_passed is not None:
            row.status = "active" if gate_passed else "degraded"
        self.session.commit()
        return True

    def retire(self, strategy_id: str) -> bool:
        """Retire a library entry. Returns False if unknown."""
        row = self.session.get(StrategyRegistryModel, strategy_id)
        if row is None:
            return False
        row.status = "retired"
        self.session.commit()
        return True


def ensure_kb_tables(engine: Any = None) -> None:
    """Create all ORM tables (idempotent) so CLI / tests can rely on schema."""
    from core.database import Base as _Base
    from core.database import get_engine

    eng = engine or get_engine()
    _Base.metadata.create_all(eng)
