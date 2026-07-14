"""BacktestEngine - turn strategy signals into a tradeable A-share portfolio.

Composes a StrategyEngine (which produces the signal columns) with a
CostModel (A-share transaction costs) and the metric functions. The engine
reuses Portfolio to derive target positions, then layers costs on top of the
no-cost mark-to-market primitive.

No look-ahead: the position held at bar t is decided at t-1 close and earns
the t-1 to t return; rebalance costs are charged at t-1 close using only data
known by then. A truncation test in tests/test_backtest.py guards this.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from core.config import (
    BacktestConfig,
    FactorConfig,
    IndicatorConfig,
    StrategyConfig,
)
from core.exceptions import ConfigError, DataError
from strategies.engine import StrategyEngine
from strategies.portfolio import Portfolio

from .cost import CostModel
from .metrics import compute_metrics

logger = logging.getLogger(__name__)

SIGNAL_PREFIX = "signal_"
Metrics = dict[str, float]
MultiMetrics = dict[str, Metrics]
BacktestResult = Metrics | MultiMetrics


class BacktestEngine:
    """Simulate a strategy signal as a cost-aware A-share portfolio."""

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        cost: CostModel,
        config: BacktestConfig,
    ) -> None:
        self.strategy_engine = strategy_engine
        self.cost = cost
        self.config = config
        self.portfolio = Portfolio(config.initial_cash)

    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
        backtest: BacktestConfig,
    ) -> BacktestEngine:
        se = StrategyEngine.from_config(indicators, factors, strategies)
        cost = CostModel(**backtest.cost.model_dump())
        return cls(se, cost, backtest)

    @property
    def names(self) -> list[str]:
        return self.strategy_engine.names

    def _resolve_signal_col(self, df: pd.DataFrame, signal_col: str | None) -> str:
        if signal_col is not None:
            return signal_col
        if self.config.strategy:
            name = self.config.strategy
            if name not in self.strategy_engine.names:
                raise ConfigError(
                    f"backtest.strategy {name!r} is not a configured strategy; "
                    f"available: {self.strategy_engine.names}"
                )
            return SIGNAL_PREFIX + name
        names = self.strategy_engine.names
        if not names:
            raise ConfigError("No strategies configured; cannot resolve signal column")
        return SIGNAL_PREFIX + names[0]

    def run(
        self, df: pd.DataFrame, signal_col: str | None = None
    ) -> tuple[pd.DataFrame, BacktestResult]:
        if "code" in df.columns and df["code"].nunique() > 1:
            parts: list[pd.DataFrame] = []
            metrics_by_code: dict[str, Metrics] = {}
            for code, group in df.groupby("code"):
                out, m = self._run_single(group, signal_col)
                out = out.copy()
                out["code"] = code
                parts.append(out)
                metrics_by_code[code] = m
            combined = pd.concat(parts, ignore_index=False)
            return combined, metrics_by_code
        return self._run_single(df, signal_col)

    def run_code(
        self,
        code: str,
        data_manager: Any,
        start_date: date | None = None,
        end_date: date | None = None,
        signal_col: str | None = None,
    ) -> tuple[pd.DataFrame, BacktestResult]:
        df = data_manager.get_daily(code, start_date, end_date)
        if df is None or df.empty:
            return (df if df is not None else pd.DataFrame()), {}
        return self.run(df, signal_col)

    def _run_single(self, df: pd.DataFrame, signal_col: str | None) -> tuple[pd.DataFrame, Metrics]:
        resolved = self._resolve_signal_col(df, signal_col)
        df = self.strategy_engine.compute(df)
        if resolved not in df.columns:
            raise DataError(
                f"backtest: signal column {resolved!r} not found after compute; "
                f"available signals: {[SIGNAL_PREFIX + n for n in self.strategy_engine.names]}"
            )
        pos = self._to_position(df, resolved)
        out, equity, trades = self._simulate(df, pos)
        close_reset = out["close"].astype(float).reset_index(drop=True)
        metrics = compute_metrics(equity, trades, close_reset, self.config)
        out = out.copy()
        out["position"] = pos.values
        out["equity"] = equity.values
        return out, metrics

    def _to_position(self, df: pd.DataFrame, signal_col: str) -> pd.Series:
        pos = self.portfolio.positions(df, signal_col)
        if (pos < 0).any():
            logger.warning(
                "backtest: short signal (-1) detected; A-share 1.6 does not short, "
                "treating as FLAT"
            )
            pos = pos.clip(lower=0.0)
        mp = self.config.max_position
        if mp < 1.0:
            pos = pos.clip(upper=mp)
        return pos

    def _simulate(
        self, df: pd.DataFrame, pos: pd.Series
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        close = df["close"].astype(float).reset_index(drop=True)
        n = len(close)
        equity = np.empty(n, dtype=float)
        equity[0] = self.config.initial_cash
        ret = close.pct_change().fillna(0.0).to_numpy()
        pos_arr = pos.to_numpy()
        trade_rows: list[dict[str, Any]] = []
        for i in range(1, n):
            prev2 = pos_arr[i - 2] if i >= 2 else 0.0
            chg = pos_arr[i - 1] - prev2
            cost = 0.0
            if chg != 0.0:
                notional = abs(chg) * equity[i - 1]
                is_sell = chg < 0
                cost = self.cost.charge(notional, is_sell)
                trade_rows.append(
                    {
                        "date": df.index[i - 1],
                        "action": "sell" if is_sell else "buy",
                        "price": float(close.iloc[i - 1]),
                        "weight_change": float(chg),
                        "notional": float(notional),
                        "cost": float(cost),
                    }
                )
            equity[i] = (equity[i - 1] - cost) * (1.0 + pos_arr[i - 1] * ret[i])
        equity_series = pd.Series(equity, index=df.index, name="equity")
        trades = pd.DataFrame(trade_rows)
        if trades.empty:
            trades = pd.DataFrame(
                columns=["date", "action", "price", "weight_change", "notional", "cost"]
            )
        return df, equity_series, trades
