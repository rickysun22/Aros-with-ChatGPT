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
