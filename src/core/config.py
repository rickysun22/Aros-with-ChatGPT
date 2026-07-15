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
    format: Literal["markdown", "json"] = "markdown"
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
