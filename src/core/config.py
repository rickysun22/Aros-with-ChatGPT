"""Configuration loading for AROS.

Settings are read from config/settings.yaml and may be overridden by
environment variables (e.g. AROS_DATABASE_URL). Centralizing every runtime
parameter here keeps the code config-driven, per the project principle
all-parameters-configurable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class DataConfig(BaseModel):
    """Data source and date-range configuration.

    source selects the DataProvider implementation: akshare (default,
    forward-adjusted) or astockdata (akshare-free, direct HTTP).
    """

    source: str = "akshare"
    frequency: str = "daily"
    adjust: str = "qfq"
    start_date: str = "2015-01-01"
    end_date: str = "2026-06-30"
    symbols: list[str] | None = None


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    url: str = "sqlite:///data/aros.db"


class PathsConfig(BaseModel):
    """Filesystem paths for generated artifacts."""

    data_dir: str = "data"
    cache_dir: str = "data/cache"
    report_dir: str = "reports"


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    dir: str = "logs"


class IndicatorSpec(BaseModel):
    """A single configured indicator instance.

    name must match a registered indicator (see indicators.base); params are
    passed straight to that indicator's constructor so every indicator
    parameter stays config-driven.
    """

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class IndicatorConfig(BaseModel):
    """The set of indicators AROS computes for each stock."""

    enabled: list[IndicatorSpec] = Field(default_factory=list)


class FactorSpec(BaseModel):
    """A single configured factor instance.

    name must match a registered factor (see factors.base). Factors are built
    on top of computed indicators, so params typically reference the same
    windows/columns produced by the indicator layer.
    """

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class FactorConfig(BaseModel):
    """The set of factors AROS computes for each stock."""

    enabled: list[FactorSpec] = Field(default_factory=list)


class WeightSpec(BaseModel):
    """A single factor contribution inside a weighted strategy.

    factor references the **factor output column** (e.g. ma_dist_20) produced
    by the factor layer. clip (lo, hi) maps that column into [-1, 1] before
    weighting; when omitted the column is assumed already bounded in [-1, 1].
    """

    factor: str
    weight: float
    clip: tuple[float, float] | None = None


class WeightedParams(BaseModel):
    """Parameters for the weighted strategy type."""

    weights: list[WeightSpec] = Field(default_factory=list)
    buy_threshold: float = 0.30
    sell_threshold: float = -0.30


class ConditionSpec(BaseModel):
    """A single boolean condition inside a rule strategy."""

    factor: str
    op: Literal[">", ">=", "<", "<=", "==", "!="] = ">"
    value: float = 0.0


class RuleParams(BaseModel):
    """Parameters for the rule strategy type."""

    combine: Literal["all", "any"] = "all"
    conditions: list[ConditionSpec] = Field(default_factory=list)


class StrategySpec(BaseModel):
    """A single configured strategy instance.

    type selects the strategy class (see strategies.base); name is the instance
    label used to namespace the output signal_<name> / score_<name> columns.
    A strategy sits on top of computed factors, so params reference the factor
    output columns produced by the factor layer. Every parameter is
    config-driven.
    """

    name: str
    type: Literal["weighted", "rule"]
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyConfig(BaseModel):
    """The set of strategies AROS computes for each stock."""

    enabled: list[StrategySpec] = Field(default_factory=list)


class CostConfig(BaseModel):
    """A-share transaction cost rates (2024 defaults)."""

    commission_rate: float = 0.00025  # 万 2.5
    commission_min: float = 5.0  # 单笔最低佣金（按侧计）
    stamp_tax_rate: float = 0.0005  # 万 5，仅卖出
    transfer_fee_rate: float = 0.00001  # 万 0.1，双边
    slippage: float = 0.0  # 滑点，双边，简化为成本拖累


class BacktestConfig(BaseModel):
    """Backtest Engine (Sprint 1.6) configuration."""

    strategy: str | None = None  # 回测哪个策略；None -> 第一个启用策略
    initial_cash: float = 1_000_000.0
    max_position: float = 1.0  # 单标的仓位上限（1.0 = 满仓）
    risk_free: float = 0.0  # 无风险年化，用于 Sharpe/Sortino
    metrics: list[str] = Field(
        default_factory=lambda: [
            "total_return",
            "cagr",
            "max_drawdown",
            "sharpe",
            "sortino",
            "win_rate",
            "num_trades",
            "turnover",
        ]
    )
    benchmark: bool = True  # 与同名标的买入持有对比
    cost: CostConfig = Field(default_factory=CostConfig)
    cache_enabled: bool = True  # 回测结果落库缓存，相同窗口/参数命中即跳过仿真


class DimensionSpec(BaseModel):
    """One ranking dimension: a strategy's score_<name> column + its weight."""

    strategy: str  # matches a StrategySpec.name
    weight: float = 1.0  # may be negative to penalise


class RankingConfig(BaseModel):
    """Ranking Engine (Sprint 1.7) configuration.

    Cross-sectional composite-score ranking over candidate stocks. The
    composite is the weight-normalised sum of each strategy's score_<name> at
    the chosen cross-section, sorted descending, Top-N kept.
    """

    top_n: int = 20
    as_of: str | None = None  # "YYYY-MM-DD"; None => latest bar per code
    dimensions: list[DimensionSpec] | None = None  # None => all enabled, equal weight


class ReportConfig(BaseModel):
    """Daily Report Engine (Sprint 1.8) configuration.

    A presentation/aggregation layer over the ranking output. It selects the
    Top-N candidates, enriches each with a latest price snapshot, and renders a
    markdown/json daily research report. No new metric math is introduced.
    """

    top_n: int = 20  # 日报展示的候选数量（可独立于 ranking.top_n）
    as_of: str | None = None  # "YYYY-MM-DD"; None => 每标的取最新一根
    format: Literal["markdown", "json", "html"] = "markdown"
    freshness_days: int = 5  # 数据比 as_of 滞后超过该天数则标"滞后"
    include_detail: bool = True  # markdown 是否展开候选明细
    include_backtest: bool = False  # 是否给每个候选附上历史回测指标（用 backtest 配置）


class WatchlistConfig(BaseModel):
    """Watchlist Tracker (Sprint 1.9) configuration.

    Persists the daily ranking of watched instruments into the shared database
    and derives day-over-day deltas (new entries, drops, rank/score moves). It
    is a tracking/aggregation layer built on top of RankingEngine + the shared
    database (core.database.Base).
    """

    alert_rank_jump: int = 5  # |rank_change| >= this flags a notable move in the digest
    include_backtest: bool = False  # snapshot 时是否附上每只标的回测表现并落库 (用 backtest 配置)


class SchedulerConfig(BaseModel):
    """Scheduled generation + push (Sprint 1.15).

    The scheduler runs a task (report / watchlist digest) on an interval and
    delivers it through a notifier. No external credentials are required: the
    webhook notifier is a no-op when ``webhook_url`` is absent.
    """

    notifier_type: Literal["console", "file", "webhook"] = "console"
    webhook_url: str | None = None  # IM webhook (DingTalk/WeCom); None => skip webhook
    file_path: str | None = None  # target for the file notifier


class BenchmarkConfig(BaseModel):
    """Benchmark index configuration (Phase 2 / Sprint 2.0).

    Maps human-friendly benchmark keys (used by ``ExperimentConfig.benchmark``)
    to the raw index codes that :meth:`DataManager.get_index_daily` understands.
    """

    default: str = "csi300"
    indices: dict[str, str] = Field(
        default_factory=lambda: {
            "csi300": "000300",
            "csi500": "000905",
            "csi1000": "000852",
            "sh_composite": "000001",
        }
    )


class ScorecardConfig(BaseModel):
    """AROS Strategy Score weights (Phase 3 / Sprint 3.0, E5).

    Drives :class:`research.scorecard.Scorecard`. The seven dimensions map to
    realised metric keys (see docs/Phase3-Technical-Design.md §4); the weights
    sum to 1.0. ``oos_decay_*`` control the anti-overfit penalty on the Sharpe
    dimension when walk-forward OOS decays vs IS.
    """

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "total_return": 0.20,
            "cagr": 0.15,
            "win_rate": 0.20,
            "max_drawdown": 0.20,
            "profit_factor": 0.10,
            "sharpe": 0.10,
            "holding_experience": 0.05,
        }
    )
    oos_decay_penalty: bool = True
    oos_decay_threshold: float = 0.5


class CombinationConfig(BaseModel):
    """Cross-strategy combination weights (Phase 3 / Sprint 3.4, E5).

    Drives :class:`research.combination.CombinationEngine`. Strategies are
    combined per market environment (trending vs oscillating) so the allocation
    tilts toward the categories / regimes that actually performed there. All
    parameters are config-driven per the project's all-parameters-configurable
    principle.
    """

    top_n: int = 3  # how many top-ranked strategies to combine
    trending_regimes: list[str] = Field(default_factory=lambda: ["Bull", "Bear"])
    oscillating_regimes: list[str] = Field(default_factory=lambda: ["Neutral", "Extreme"])
    trending_bias_category: list[str] = Field(default_factory=lambda: ["trend", "strong"])
    oscillating_bias_category: list[str] = Field(default_factory=lambda: ["emotion", "strong"])
    category_bias: float = 0.5  # bonus added to a strategy's raw weight on category fit
    perf_weight: float = 2.0  # scales the regime-performance tilt
    perf_cap: float = 0.30  # clamp on the per-regime avg return used for the tilt
    equal_weight_floor: float = 0.1  # minimum weight so no selected strategy is dropped


class MarketRegimeConfig(BaseModel):
    """Market-regime classification (Phase 3 / Sprint 3.5, E5).

    Drives :class:`research.market_regime.MarketRegimeEngine`. A transparent,
    rule-based 5-label classifier (Bull / Neutral / Bear / EmotionHot /
    EmotionCold) built from explainable signals only -- index MA/momentum
    structure, realised volatility, and an optional market-breadth (net
    limit-up) sentiment series. No black-box model, no look-ahead.
    """

    momentum_window: int = 20  # bars for the trend-momentum read
    vol_window: int = 20  # bars for annualised realised-vol
    drawdown_window: int = 20  # bars for the trailing-high drawdown
    bull_mom: float = 0.05  # 20d return above this (and calm vol) -> Bull
    bear_mom: float = -0.05  # 20d return below this -> Bear
    high_vol_cap: float = 0.60  # annualised vol above this disqualifies a calm Bull
    sentiment_window: int = 5  # bars for the smoothed net-sentiment read
    emotion_hot_threshold: float = 0.15  # smoothed net limit-up ratio >= -> EmotionHot
    emotion_cold_threshold: float = -0.15  # smoothed net limit-up ratio <= -> EmotionCold


class UniverseConfig(BaseModel):
    """Phase 4.0 Universe Provider mode (design §5 4.0 / §10 Q1).

    The daily screening universe is not hard-coded to csi800. ``type`` selects a
    provider implementation; ``watchlist_path`` / ``custom_codes`` feed the
    Watchlist / Custom providers. The CLI can override ``type`` at run time.
    """

    type: Literal["csi800", "watchlist", "custom"] = "csi800"
    watchlist_path: str | None = None  # used when type == "watchlist"
    custom_codes: list[str] | None = None  # used when type == "custom"


class WalkForwardConfig(BaseModel):
    """Walk-forward split (years). Mirrors ``research.experiment.WalkForwardSpec``
    but declared here so ``core.config`` stays free of any ``research`` import
    (avoids a circular import: ``research.batch`` imports ``core.config`` while
    ``research/__init__`` executes). ``validate.py`` converts this to the
    ``research.experiment.WalkForwardSpec`` the runner consumes."""

    train_years: int = 3
    test_years: int = 1
    step_years: int = 1


class ValidationGateConfig(BaseModel):
    """Strategy Validation Gate (Phase 4.1, AROS 宪法级闸门, design §5 4.1).

    Every check must PASS for a strategy to enter the formal library. Thresholds
    are config-driven so the gate can be calibrated against the built-in 10
    strategies (design §5 4.1 校准) without code changes.
    """

    no_lookahead: bool = True  # architecture guarantee (T+1); code future-func needs human/lint
    oos_return_gt: float = 0.0  # OOS total return must exceed this
    oos_sharpe_gt: float = 0.5  # OOS Sharpe must exceed this
    max_drawdown_lt: float = 0.40  # OOS max drawdown must be below this (abs)
    min_trades: int = 100  # at least this many OOS trades
    param_stable: bool = True  # parameter-sensitivity test must pass
    param_decay_threshold: float = 0.5  # avg OOS Sharpe decay above this fails param_stable


class QualityStarConfig(BaseModel):
    """OOS Composite Score -> quality_star (design §4.0).

    The composite blends four OOS components, each normalised to 0-100 by a
    tunable scale before weighted summation. Hard vetoes cap the star so a single
    flaw (deep drawdown / too few trades) cannot be averaged away.
    """

    return_scale: float = 0.30  # OOS return of +return_scale -> 100 on the return component
    sharpe_scale: float = 2.0  # OOS Sharpe of +sharpe_scale -> 100 on the Sharpe component
    drawdown_scale: float = 0.60  # OOS max drawdown of this (abs) -> 0 on the drawdown component
    stability_scale: float = 0.15  # std of per-fold OOS returns of this -> 0 on stability
    # star veto rules (override the composite->star mapping)
    drawdown_veto: float = 0.40  # max drawdown above this -> star capped at 2
    min_trades_veto: int = 100  # OOS trades below this -> star capped at 3


class ReliabilityConfig(BaseModel):
    """Reliability Score weights (design §4.3): how *trustworthy* the evidence is.

    Complements quality_star (how *good* it is). Weights sum to 1.0.
    """

    oos_weight: float = 0.40  # OOS performance (return>0 & Sharpe>=gate)
    param_weight: float = 0.20  # parameter-sensitivity (perturbation Sharpe decay)
    period_weight: float = 0.20  # period stability (positive OOS sub-windows ratio)
    trades_weight: float = 0.20  # trade count adequacy


class ValidationConfig(BaseModel):
    """Phase 4.1 validation engine configuration (design §5 4.1)."""

    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    gate: ValidationGateConfig = Field(default_factory=ValidationGateConfig)
    quality_star: QualityStarConfig = Field(default_factory=QualityStarConfig)
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)


class ConsensusConfig(BaseModel):
    """Phase 4.2 multi-strategy consensus (design §4 / §5 4.2).

    All weights are config-driven so the resonance scoring can be calibrated
    without code changes. Money-flow / sector components default to *neutral*
    when no provider is wired in (the real providers land in Sprint 4.3), so
    this sprint is self-contained and offline-testable.
    """

    # Consensus Score (0-100) component weights: H20 / Q30 / I20 / R15 / S15.
    w_hit: float = 20.0
    w_quality: float = 30.0
    w_independence: float = 20.0
    w_regime: float = 15.0
    w_sector_money: float = 15.0

    # Hit count saturates at ``hit_cap`` (H = w_hit * min(hit_count, cap)/cap).
    hit_cap: int = 5

    # Regime match (R): full when current regime is in the union of the hitting
    # strategies' best_fit_regimes; no match -> base fraction of w_regime.
    regime_full: float = 15.0
    regime_base: float = 0.3

    # Independence (I): avg pairwise Pearson correlation of OOS fold returns
    # among the surviving (deduped) strategies; I = w_independence * (1 - avg_corr).
    corr_dedup_threshold: float = 0.7  # same-(category, corr-cluster) dedup cutoff
    # quality_star used when a strategy has no validation yet (registry star None).
    default_star_when_unvalidated: float = 3.0

    # AROS Final Score (0-100) weights: consensus35 / env20 / money30 / risk15.
    w_aros_consensus: float = 0.35
    w_aros_env: float = 0.20
    w_aros_money: float = 0.30
    w_aros_risk: float = 0.15

    # market_sector_env = regime_friend*0.5 + sector_score*0.5.
    regime_friendliness: dict[str, float] = Field(
        default_factory=lambda: {
            "Bull": 100.0,
            "Neutral": 70.0,
            "Bear": 40.0,
            "EmotionHot": 55.0,
            "EmotionCold": 30.0,
        }
    )
    # money_flow = public*visible_weight + hidden*hidden_weight (design §4.2).
    money_visible_weight: float = 0.9
    money_hidden_weight: float = 0.1
    # risk_filter penalty when a candidate's max drawdown exceeds threshold.
    risk_dd_penalty: float = 30.0
    risk_dd_threshold: float = 0.40

    # Rating thresholds (design §4.4 / Phase 4.6). Top bucket is "S" (was "A+").
    rating_s: float = 85.0
    rating_a: float = 70.0
    rating_b: float = 55.0
    # Top-N candidates persisted per daily screening.
    top_n: int = 10


class ResearchConfig(BaseModel):
    """Research engine configuration (Phase 2 / Sprint 2.0 foundation).

    Only the surface needed to freeze the 2.0 foundation is defined here; the
    runner / walk-forward / report parameters land in their own sprints
    (2.4-2.6). ``metrics=None`` means the research layer reuses
    ``BacktestConfig.metrics`` rather than defining a parallel metric list.
    ``scorecard`` (Phase 3 / 3.0) carries the AROS Strategy Score weights.
    """

    experiment_id_prefix: str = "exp_"  # short-uuid prefix for ExperimentRun.id
    metrics: list[str] | None = None  # None => reuse backtest.metrics (no parallel list)
    scorecard: ScorecardConfig = Field(default_factory=ScorecardConfig)
    combination: CombinationConfig = Field(default_factory=CombinationConfig)
    market_regime: MarketRegimeConfig = Field(default_factory=MarketRegimeConfig)


class AppConfig(BaseModel):
    """Top-level application configuration."""

    app_name: str = "AROS"
    data: DataConfig = Field(default_factory=DataConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    factors: FactorConfig = Field(default_factory=FactorConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    consensus: ConsensusConfig = Field(default_factory=ConsensusConfig)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
        """Load configuration from a YAML file with .env overrides."""
        load_dotenv(PROJECT_ROOT / ".env")
        raw: dict[str, Any] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        cfg = cls.model_validate(raw)

        db_url = os.getenv("AROS_DATABASE_URL")
        if db_url:
            cfg.database.url = db_url
        log_level = os.getenv("AROS_LOG_LEVEL")
        if log_level:
            cfg.logging.level = log_level.upper()
        return cfg


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return the process-wide AppConfig (cached)."""
    return AppConfig.from_file()
