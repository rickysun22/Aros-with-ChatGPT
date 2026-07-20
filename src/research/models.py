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
    Integer,
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
    # Optional per-strategy max holding horizon (trading days). Used by the 4.7
    # paper-trading time-exit priority chain (Strategy > Rating > Portfolio). Null
    # = no strategy-level constraint (rating cap / portfolio limit still apply).
    max_holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


# --------------------------------------------------------------------------- #
# Phase 4.2 -- Daily multi-strategy screening & Alpha candidates
# --------------------------------------------------------------------------- #
class DailyScreening(Base):
    """One daily screening run (§3.4): the universe + market regime snapshot."""

    __tablename__ = "daily_screenings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # csi800 / watchlist / custom (Provider mode, §5 4.0)
    universe: Mapped[str] = mapped_column(String(16), nullable=False)
    # Bull / Neutral / Bear / EmotionHot / EmotionCold (§3.5 market_regime)
    regime_label: Mapped[str] = mapped_column(String(16), nullable=False)
    regime_detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class ScreeningHit(Base):
    """One strategy hit on one candidate (§3.4): the traceable core link."""

    __tablename__ = "screening_hits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    screening_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("daily_screenings.id"), index=True, nullable=False
    )
    strategy_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    # quality_star at hit time (0-5), used for scoring + dedup (§4.1 Q / I)
    quality_star_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)


class DailyAlphaCandidate(Base):
    """One daily Alpha candidate (§3.5 / v2 Sheet1): scoring + explainability."""

    __tablename__ = "daily_alpha_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    screening_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("daily_screenings.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True)
    concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    regime_label: Mapped[str] = mapped_column(String(16), nullable=False)
    hit_count: Mapped[int] = mapped_column(default=0, nullable=False)
    hit_strategies_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    avg_quality_star: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_quality_star: Mapped[float | None] = mapped_column(Float, nullable=True)
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    public_money_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hidden_flow_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aros_score: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    # consensus + aros component breakdown (explainability, §4)
    consensus_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    aros_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    advantages: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# --------------------------------------------------------------------------- #
# Phase 4.5 -- Human feedback loop (Sprint 4.5)
# --------------------------------------------------------------------------- #
class DecisionTracking(Base):
    """One human decision + system post-hoc on a daily Alpha candidate (§3.6).

    System auto-fills post-hoc prices (result_1d/3d/5d/10d, float pnl, final
    return) from ``DataManager``; the human only fills the judgement columns
    (``human_decision`` / ``human_reason`` / plan-vs-actual / ``review_summary``
    / ``verified_system``). ``signal_date`` anchors the post-hoc window (T+1
    entry) and is stored redundantly so the record survives screening deletion.
    """

    __tablename__ = "decision_tracking"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("daily_alpha_candidates.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    # T-day signal date of the candidate; anchors the post-hoc window (entry = T+1).
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    human_decision: Mapped[str] = mapped_column(
        String(16), default="关注", nullable=False
    )  # 关注/买入/放弃/忽略
    human_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_position: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-1 fraction
    actual_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_3d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_10d: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_float_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_float_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_system: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    review_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PersonalTrade(Base):
    """A manually-recorded personal trade (§3.6, the deferred deep-review sink).

    Live-from-launch the user records their own selected names here; the system
    does NOT auto-ingest or derive — this is purely a self-kept trade blotter that
    enriches the database over time. ``source`` marks 人工录入 / 导入.
    """

    __tablename__ = "personal_trades"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # long/short
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="人工录入", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# --------------------------------------------------------------------------- #
# Phase 4.6 -- Candidate performance review (auto post-hoc for ALL candidates)
# --------------------------------------------------------------------------- #
class CandidatePerformance(Base):
    """One auto-filled performance record per daily Alpha candidate (§3 / §4.6).

    Unlike ``DecisionTracking`` (which only covers candidates a human judged),
    this table covers *every* candidate so the rating system can be validated
    statistically (S > A > B > C monotonicity + significance). One row per
    candidate (1:1 via ``candidate_id``). Filled incrementally by
    ``research.calibration.fill_all_performances`` as forward windows mature
    (T+20 needs ~1 month of trading days before it has a value).
    """

    __tablename__ = "candidate_performance"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_candidate_perf"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # f"cp_{candidate_id}"
    candidate_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("daily_alpha_candidates.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    aros_score: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    # Forward returns (T+1 entry, total return). None until the window matures.
    result_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_3d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_10d: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_float_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_float_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    # First trading day the running max return reached ``target_pct`` (e.g. +5%).
    target_hit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # success / fail / pending (pending = T+10 not yet available).
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    filled_at: Mapped[date | None] = mapped_column(Date, nullable=True)


# --------------------------------------------------------------------------- #
# Phase 4.7 -- Paper trading (exit experiment, anti-confounding dual axis)
# --------------------------------------------------------------------------- #
class Portfolio(Base):
    """One paper-trading portfolio = one cell of the 4.7 dual-axis experiment.

    The ``axis`` column marks whether the portfolio belongs to the *selection*
    experiment (S1 ai / S2 human / S3 random) or the *exit* experiment
    (E1 fixed / E2 trailing / E3 dynamic). Each portfolio holds its own trades
    (FK ``simulated_trades.portfolio_id``), so the 6 combinations never share
    data (design Part II §II.3). Account state is *not* stored — it is rebuilt
    from the trade blotter + a ``PriceProvider`` on demand (no dual-write drift).
    """

    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. "S1_E1"
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # selection | exit
    axis: Mapped[str] = mapped_column(String(8), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    position_fraction: Mapped[float] = mapped_column(Float, default=0.2)
    # immediate | signal_confirmation | manual — Phase 4.8 Entry engine reserved.
    entry_mode: Mapped[str] = mapped_column(String(16), default="immediate")
    # ExitConfig (design §II.5) serialized as JSON; drives E1/E2/E3 behaviour.
    exit_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    # ai | human | random — which candidate pool feeds entries (design §II.3).
    picker: Mapped[str] = mapped_column(String(8), default="ai")
    # Portfolio-level risk limit on holding days (time-stop lowest priority).
    max_holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class SimulatedTrade(Base):
    """One hypothetical (non-executed) trade inside a paper-trading portfolio.

    Purely a simulation record — AROS never places real orders (constitutional
    red line: no broker connection, no auto-trading). ``entry_date`` is the first
    trading day after the candidate's ``signal_date`` (T+1 fill, no look-ahead).
    ``score_type`` / ``entry_score`` are reserved for Phase 5 (real Daily Exit
    Intelligence); in 4.7 ``score_type`` is ``"proxy"`` only when a trade is
    closed by Score Decay, otherwise ``None``.
    """

    __tablename__ = "simulated_trades"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("portfolios.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_mode: Mapped[str] = mapped_column(String(16), default="immediate")
    score_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    entry_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aros_score: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    hit_strategies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Strategy-level max holding horizon captured at entry (time-stop priority).
    strategy_max_holding: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # stop_loss | take_profit | trailing | score_decay | time_stop | manual
    exit_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
