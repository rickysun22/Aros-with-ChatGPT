"""IndicatorEngine - runs the configured set of indicators over price data.

The engine is the only place that orchestrates indicators. It reads raw daily
bars (typically via the :class:`~data.manager.DataManager` single entry point),
applies every configured indicator in order, and returns an enriched frame.

Indicators are applied per stock when several codes are present, so each
series is computed on its own history only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from core.config import IndicatorConfig
from core.exceptions import ConfigError

from . import impl  # noqa: F401  (importing registers all indicator classes)
from .base import BaseIndicator, build


class IndicatorEngine:
    """Applies a list of indicators to a price DataFrame."""

    def __init__(self, indicators: list[BaseIndicator]) -> None:
        self.indicators = indicators

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(cls, cfg: IndicatorConfig) -> IndicatorEngine:
        """Build an engine from an :class:`IndicatorConfig`."""
        indicators: list[BaseIndicator] = []
        for spec in cfg.enabled:
            try:
                indicators.append(build(spec.name, spec.params))
            except ConfigError:
                raise ConfigError(f"Indicator {spec.name!r} in config is not registered") from None
        return cls(indicators)

    @classmethod
    def available(cls) -> list[str]:
        """Names of all registered indicators (delegates to the registry)."""
        from .base import available

        return available()

    @property
    def names(self) -> list[str]:
        """Configured indicator names, in computation order."""
        return [ind.name for ind in self.indicators]

    # ------------------------------------------------------------------ #
    # Computation
    # ------------------------------------------------------------------ #
    def _apply(self, df: pd.DataFrame) -> pd.DataFrame:
        for ind in self.indicators:
            df = ind.compute(df)
        return df

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all indicators for ``df``.

        If ``df`` contains more than one stock (a ``code`` column with several
        distinct values), indicators are computed independently per code.
        """
        if "code" in df.columns and df["code"].nunique() > 1:
            parts = [self._apply(group.copy()) for _, group in df.groupby("code")]
            return pd.concat(parts, ignore_index=False)
        return self._apply(df.copy())

    def compute_code(
        self,
        code: str,
        data_manager: Any,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Fetch ``code``'s bars via *data_manager* and compute indicators.

        *data_manager* must expose ``get_daily(code, start_date, end_date)``,
        i.e. the :class:`~data.manager.DataManager` interface. This keeps the
        engine behind the single data-entry principle.
        """
        df = data_manager.get_daily(code, start_date, end_date)
        if df.empty:
            return df
        return self.compute(df)
