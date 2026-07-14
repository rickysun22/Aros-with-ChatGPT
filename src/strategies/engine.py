"""StrategyEngine - combines factors into tradeable signals.

The engine sits at the top of the research pipeline. It is constructed with an
already-built FactorEngine; compute first runs indicators -> factors (via the
factor engine) and then applies every configured strategy. Because strategies
only read factor columns already present in the frame, the whole pipeline stays
behind the no-future-function guarantee.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from core.config import FactorConfig, IndicatorConfig, StrategyConfig
from core.exceptions import ConfigError

from . import impl  # noqa: F401  (importing registers all strategy classes)
from .base import BaseStrategy, build


class StrategyEngine:
    """Applies indicators -> factors -> strategies to a price DataFrame."""

    def __init__(self, factor_engine: Any, strategies: list[BaseStrategy]) -> None:
        # factor_engine is typed loosely to avoid a circular import with the
        # factors package; it must expose compute / compute_code.
        self.factor_engine = factor_engine
        self.strategies = strategies

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
    ) -> StrategyEngine:
        """Build an engine from indicator, factor and strategy configs."""
        from factors.engine import FactorEngine

        factor_engine = FactorEngine.from_config(indicators, factors)
        strategy_list: list[BaseStrategy] = []
        for spec in strategies.enabled:
            try:
                strategy_list.append(build(spec.type, spec.params, spec.name))
            except ConfigError:
                raise ConfigError(
                    f"Strategy {spec.name!r} (type {spec.type!r}) is not registered"
                ) from None
        return cls(factor_engine, strategy_list)

    @classmethod
    def available(cls) -> list[str]:
        """Names of all registered strategy types (delegates to the registry)."""
        from .base import available

        return available()

    @property
    def names(self) -> list[str]:
        """Configured strategy instance names, in computation order."""
        return [s.instance_name for s in self.strategies]

    # ------------------------------------------------------------------ #
    # Computation
    # ------------------------------------------------------------------ #
    def _apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.factor_engine.compute(df)
        for strategy in self.strategies:
            df = strategy.compute(df)
        return df

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute indicators -> factors -> strategies for df.

        If df contains more than one stock (a code column with several distinct
        values), the pipeline runs independently per code.
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
        """Fetch code's bars via data_manager, then compute the pipeline.

        data_manager must expose get_daily(code, start_date, end_date), i.e. the
        DataManager interface.
        """
        df = data_manager.get_daily(code, start_date, end_date)
        if df.empty:
            return df
        return self.compute(df)
