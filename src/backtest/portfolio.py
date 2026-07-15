"""Portfolio backtest (Sprint 1.16).

Combine single-stock backtests into a rebalancing portfolio. At each rebalance
date the Top-N codes (by the cross-sectional ranking at that date) are selected
and held with equal weight until the next rebalance; the portfolio equity is the
sum of the per-stock equity curves weighted by the current holdings.

No look-ahead: selection at rebalance date *t* uses only data known by *t*
(the ranking layer's as_of is *t*), and each stock's equity is the 1.6 engine's
cost-aware curve. The benchmark is an equal-weight buy-and-hold of the whole
candidate set.

The heavy ranking/backtest work is injectable (``rank_fn`` / ``equity_fn``) so the
combination logic is unit-testable without the full upstream pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from core.config import (
    BacktestConfig,
    FactorConfig,
    IndicatorConfig,
    RankingConfig,
    StrategyConfig,
)
from ranking.engine import RankingEngine

from .engine import BacktestEngine
from .metrics import compute_metrics

logger = logging.getLogger(__name__)

RankFn = Callable[[list[str], Any, Any, Any], list[str]]
EquityFn = Callable[[str, Any, Any, Any], pd.Series]


@dataclass
class PortfolioResult:
    """Outcome of a portfolio backtest."""

    equity: pd.Series
    metrics: dict[str, float]
    selections: list[tuple[Any, list[str]]] = field(default_factory=list)
    trades: Any = None  # pandas.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "selections": [(str(d), list(codes)) for d, codes in self.selections],
            "num_rebalances": len(self.selections),
            "final_equity": (float(self.equity.iloc[-1]) if len(self.equity) else None),
        }


class PortfolioBacktest:
    """Rebalance a Top-N portfolio and track its combined equity."""

    def __init__(
        self,
        ranking_engine: RankingEngine,
        backtest_engine: BacktestEngine,
        config: BacktestConfig,
        top_n: int = 10,
        rebalance_freq: str = "ME",
    ) -> None:
        self.ranking_engine = ranking_engine
        self.backtest_engine = backtest_engine
        self.config = config
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq

    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
        ranking: RankingConfig,
        backtest: BacktestConfig,
        top_n: int = 10,
        rebalance_freq: str = "ME",
    ) -> PortfolioBacktest:
        re = RankingEngine.from_config(indicators, factors, strategies, ranking)
        bt = BacktestEngine.from_config(indicators, factors, strategies, backtest)
        return cls(re, bt, backtest, top_n=top_n, rebalance_freq=rebalance_freq)

    # ------------------------------------------------------------------ #
    # Default heavy functions (real pipeline)
    # ------------------------------------------------------------------ #
    def _default_equity_fn(self, code: str, dm: Any, start: Any, end: Any) -> pd.Series:
        df, _metrics = self.backtest_engine.run_code(code, dm, start, end)
        if df is None or df.empty or "equity" not in df.columns:
            return pd.Series(dtype=float)
        eq = df["equity"].copy()
        if "date" in df.columns:
            eq.index = pd.to_datetime(df["date"])
        else:
            eq.index = pd.to_datetime(eq.index)
        return eq.sort_index()

    def _default_rank_fn(self, codes: list[str], dm: Any, start: Any, end: Any) -> list[str]:
        table, _ = self.ranking_engine.rank_universe(list(codes), dm, start, end)
        if table.empty:
            return []
        return [str(c) for c in table.sort_values("rank")["code"].head(self.top_n)]

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        codes: list[str],
        data_manager: Any,
        start_date: date | None = None,
        end_date: date | None = None,
        rank_fn: RankFn | None = None,
        equity_fn: EquityFn | None = None,
    ) -> PortfolioResult:
        rank_fn = rank_fn or self._default_rank_fn
        equity_fn = equity_fn or self._default_equity_fn
        codes = list(codes)

        eq_map: dict[str, pd.Series] = {}
        all_dates: set[Any] = set()
        for c in codes:
            s = equity_fn(c, data_manager, start_date, end_date)
            if len(s) == 0:
                continue
            eq_map[c] = s
            all_dates.update(s.index)

        empty_trades = pd.DataFrame(
            columns=["date", "action", "price", "weight_change", "notional", "cost"]
        )
        if not eq_map:
            return PortfolioResult(pd.Series(dtype=float), self._zero_metrics(), [], empty_trades)

        common = sorted(
            d
            for d in all_dates
            if (end_date is None or pd.Timestamp(d) <= pd.Timestamp(end_date))
            and (start_date is None or pd.Timestamp(d) >= pd.Timestamp(start_date))
        )
        aligned = {c: eq_map[c].reindex(common).ffill().bfill() for c in eq_map}

        start_ts = pd.Timestamp(start_date) if start_date else pd.Timestamp(common[0])
        end_ts = pd.Timestamp(end_date) if end_date else pd.Timestamp(common[-1])
        reb = pd.date_range(start_ts, end_ts, freq=self.rebalance_freq)
        # Snap each rebalance date to the latest common date at/before it.
        reb_common: set[Any] = {common[0]}
        for r in reb:
            candidates = [d for d in common if pd.Timestamp(d) <= pd.Timestamp(r)]
            if candidates:
                reb_common.add(max(candidates))

        selections: list[tuple[Any, list[str]]] = []
        trades_rows: list[dict[str, Any]] = []
        holdings: dict[str, float] = {}
        portfolio_vals: list[float] = []
        for t in common:
            if t in reb_common:
                sel = [c for c in rank_fn(list(eq_map.keys()), data_manager, start_date, t)]
                sel = [c for c in sel if c in aligned][: self.top_n]
                value = (
                    sum(
                        holdings[c] * float(aligned[c][t])
                        for c in holdings
                        if not pd.isna(aligned[c][t])
                    )
                    if holdings
                    else self.config.initial_cash
                )
                n = max(len(sel), 1)
                holdings = {}
                for c in sel:
                    price = float(aligned[c][t])
                    if pd.isna(price) or price == 0:
                        continue
                    holdings[c] = (value / n) / price
                selections.append((t, sel))
                trades_rows.append(
                    {
                        "date": t,
                        "action": "rebalance",
                        "price": 0.0,
                        "weight_change": 1.0,
                        "notional": value,
                        "cost": 0.0,
                    }
                )
            val = sum(
                holdings[c] * float(aligned[c][t]) for c in holdings if not pd.isna(aligned[c][t])
            )
            portfolio_vals.append(val)

        equity = pd.Series(portfolio_vals, index=common)

        # Equal-weight buy-and-hold of the whole set = benchmark.
        n_all = len(aligned)
        base0 = {c: float(aligned[c][common[0]]) for c in aligned}
        bench_hold = {c: (self.config.initial_cash / n_all) / base0[c] for c in aligned}
        bench = pd.Series(
            [sum(bench_hold[c] * float(aligned[c][t]) for c in aligned) for t in common],
            index=common,
        )
        trades = pd.DataFrame(
            trades_rows,
            columns=["date", "action", "price", "weight_change", "notional", "cost"],
        )

        if equity.empty or len(equity) < 2:
            metrics = self._zero_metrics()
        else:
            metrics = compute_metrics(equity, trades, bench, self.config)

        return PortfolioResult(equity, metrics, selections, trades)

    def _zero_metrics(self) -> dict[str, float]:
        m = {k: 0.0 for k in self.config.metrics}
        if self.config.benchmark:
            m["benchmark_return"] = 0.0
        return m
