"""ORM models for the Phase 2 research engine (Sprint 2.0 foundation).

These models reuse the shared :class:`~core.database.Base` so the database
engine in ``core.database`` manages their schema alongside the existing tables,
following the exact pattern of ``BacktestPoint`` / ``RankingPoint`` (Sprint
1.9/1.11). 2.0 only lays the persistence rails; the runner that fills them lands
in later sprints.

* ``ExperimentRun``    - one research experiment (config + lifecycle status).
* ``ExperimentMetric`` - one metric value in *long* form, tagged in-sample /
  out-of-sample and by walk-forward window, so 2.5 can record IS/OOS per window
  and 2.6 can query/aggregate without parsing a wide JSON blob.
* ``ExperimentEquity`` - the equity curve for a run/window kept as a JSON blob
  (mirrors 1.12 ``equity_json``) since it is read whole.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ExperimentRun(Base):
    """A single research experiment run.

    Frozen decision (Sprint 2.0 §7 Q3): the primary key is a short UUID and the
    human ``name`` carries a UNIQUE constraint. This keeps runs rename-safe and
    human-searchable while giving child rows a stable FK target.
    """

    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. "exp_a1b2c3d4"
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # ExperimentConfig round-trip
    # status: created / running / done / failed
    status: Mapped[str] = mapped_column(String(16), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExperimentMetric(Base):
    """One metric value for a run, in long form (Sprint 2.0 §7 Q4).

    ``value`` is nullable so a metric that cannot be computed (e.g. Sharpe with
    no trades) is recorded as absent rather than a misleading zero. The unique
    key spans ``(run_id, metric_name, is_oos, window)`` so the same metric can
    coexist for in-sample vs out-of-sample and across walk-forward windows.
    """

    __tablename__ = "experiment_metrics"
    __table_args__ = (
        UniqueConstraint("run_id", "metric_name", "is_oos", "window", name="uq_exp_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("experiment_runs.id"), index=True, nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "sharpe"
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_oos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    window: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g. "2019-2020"


class ExperimentEquity(Base):
    """The equity curve for a run/window, serialized as a JSON blob."""

    __tablename__ = "experiment_equity"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("experiment_runs.id"), index=True, nullable=False
    )
    window: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_oos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    equity_json: Mapped[str] = mapped_column(Text, nullable=False)  # {date: equity} serialized


# --------------------------------------------------------------------------- #
# Phase 4.0 -- Strategy knowledge base
# --------------------------------------------------------------------------- #
class RawStrategy(Base):
    """The raw strategy pool (§3.1): ideas / rules / sources collected for later
    implementation + validation. Missing fields are allowed (v2 principle 2) so a
    strategy can be captured before it is fully specified."""

    __tablename__ = "raw_strategies"

    strategy_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # manual/web/book/paper/other
    source_type: Mapped[str] = mapped_column(String(16), default="manual")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[date] = mapped_column(Date, default=date.today)
    # raw/pending_validation/validated/active/degraded/retired
    status: Mapped[str] = mapped_column(String(16), default="raw")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class StrategyRegistry(Base):
    """The executable formal library (§3.2): a validated strategy mapped to a
    runnable implementation, with its verification evidence and quality signals.
    Seeded from ``strategy_library`` (10 built-ins) at ``active`` status."""

    __tablename__ = "strategy_registry"

    strategy_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # trend/strong/emotion
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    # strategy_library name / module path
    executable_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    # validated/active/degraded/retired
    status: Mapped[str] = mapped_column(String(16), default="validated")
    # -> experiment_runs.id
    validation_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 0-5 OOS composite star
    quality_star: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0-100 reliability
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Strategy Validation Gate
    gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # JSON list of Regime labels
    best_fit_regimes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class StrategyValidation(Base):
    """One validation run for a strategy (§3.3): the evidence chain behind its
    quality_star / reliability_score / gate result. One row per validation."""

    __tablename__ = "strategy_validations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # base experiment run -> experiment_runs.id
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)  # OOS metric summary
    # OOS composite + components + fold returns
    oos_json: Mapped[str] = mapped_column(Text, nullable=False)
    # active/degraded (advisory only)
    status_suggestion: Mapped[str] = mapped_column(String(16), default="degraded")
    # in-sample window range (evidence)
    is_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # out-of-sample window range (evidence)
    oos_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    optimization: Mapped[str] = mapped_column(String(32), default="fixed")  # none/fixed/grid(...)
    walk_forward_passed: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability_json: Mapped[str] = mapped_column(Text, nullable=False)  # reliability breakdown
    gate_result_json: Mapped[str] = mapped_column(Text, nullable=False)  # gate PASS/FAIL detail
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
