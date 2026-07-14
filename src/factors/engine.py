"""FactorEngine - runs indicators then factors over price data.

The engine is the single orchestrator for the research layer. It first builds
the indicator layer (via :class:`~indicators.engine.IndicatorEngine`) and then
applies every configured factor on top of the enriched frame. Because factors
only ever read columns already present in the frame, the whole pipeline stays
behind the *禁止未来函数* guarantee.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from core.config import FactorConfig, IndicatorConfig
from core.exceptions import ConfigError

from . import impl  # noqa: F401  (importing registers all factor classes)
from .base import BaseFactor, build


class FactorEngine:
    """Applies indicators then factors to a price DataFrame."""

    def __init__(self, indicator_engine: Any, factors: list[BaseFactor]) -> None:
        # ``indicator_engine`` is typed loosely to avoid a circular import with
        # the indicators package; it must expose ``compute``/``compute_code``.
        self.indicator_engine = indicator_engine
        self.factors = factors

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(cls, indicators: IndicatorConfig, factors: FactorConfig) -> FactorEngine:
        """Build an engine from indicator and factor configs."""
        from indicators.engine import IndicatorEngine

        indicator_engine = IndicatorEngine.from_config(indicators)
        factor_list: list[BaseFactor] = []
        for spec in factors.enabled:
            try:
                factor_list.append(build(spec.name, spec.params))
            except ConfigError:
                raise ConfigError(f"Factor {spec.name!r} in config is not registered") from None
        return cls(indicator_engine, factor_list)

    @classmethod
    def available(cls) -> list[str]:
        """Names of all registered factors (delegates to the registry)."""
        from .base import available

        return available()

    @property
    def names(self) -> list[str]:
        """Configured factor names, in computation order."""
        return [f.name for f in self.factors]

    # ------------------------------------------------------------------ #
    # Computation
    # ------------------------------------------------------------------ #
    def _apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.indicator_engine.compute(df)
        for factor in self.factors:
            df = factor.compute(df)
        return df

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute indicators then factors for ``df``.

        If ``df`` contains more than one stock (a ``code`` column with several
        distinct values), the pipeline runs independently per code.
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
        """Fetch ``code``'s bars via *data_manager*, then compute indicators+factors.

        *data_manager* must expose ``get_daily(code, start_date, end_date)``,
        i.e. the :class:`~data.manager.DataManager` interface.
        """
        df = data_manager.get_daily(code, start_date, end_date)
        if df.empty:
            return df
        return self.compute(df)
