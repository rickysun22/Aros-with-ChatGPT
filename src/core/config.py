"""Configuration loading for AROS.

Settings are read from ``config/settings.yaml`` and may be overridden by
environment variables (e.g. ``AROS_DATABASE_URL``). Centralizing every runtime
parameter here keeps the code config-driven, per the project principle
*所有参数配置化*.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class DataConfig(BaseModel):
    """Data source and date-range configuration.

    ``source`` selects the :class:`~data.provider.DataProvider`
    implementation: ``"akshare"`` (default, forward-adjusted) or
    ``"astockdata"`` (akshare-free, direct HTTP via Baidu/Eastmoney).
    """

    source: str = "akshare"
    frequency: str = "daily"
    # Price adjustment for historical bars: "qfq" (forward), "hfq" (backward),
    # or "" (raw). Forward-adjusted is the sensible default for research.
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

    ``name`` must match a registered indicator (see ``indicators.base``),
    ``params`` are passed straight to that indicator's constructor so every
    indicator parameter stays config-driven (project principle
    *所有参数配置化*).
    """

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class IndicatorConfig(BaseModel):
    """The set of indicators AROS computes for each stock."""

    enabled: list[IndicatorSpec] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Top-level application configuration."""

    app_name: str = "AROS"
    data: DataConfig = Field(default_factory=DataConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
        """Load configuration from a YAML file with ``.env`` overrides.

        Args:
            path: Path to the YAML settings file. Defaults to
                ``config/settings.yaml`` relative to the project root.

        Returns:
            A validated :class:`AppConfig` instance.
        """
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
    """Return the process-wide :class:`AppConfig` (cached)."""
    return AppConfig.from_file()
