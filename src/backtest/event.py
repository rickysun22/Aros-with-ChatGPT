"""Event-driven backtest (Sprint 3.0).

A complementary engine to :class:`PortfolioBacktest` for short-horizon,
single-name strategies (the Phase 3 ``event`` engine). It simulates the
research-friendly execution rule frozen in the Phase 3 design:

* an entry signal confirmed at the **close of day T** is executed at the
  **open of day T+1** (no look-ahead -- the decision uses only data <= T, and
  the fill uses the real T+1 open);
* the position is held until one of three exit rules fires -- a stop-loss,
  a take-profit, or the maximum holding-days expiry -- at which point it is
  closed at that day's **close** (daily-data approximation; the stop/target
  are standing orders, so using the day's own high/low/close is legitimate).

The engine reuses the existing :class:`CostModel` and :func:`compute_metrics`
exactly -- no new metric math -- so ``event``-engine strategies are directly
comparable to ``portfolio``-engine strategies through one shared metric set.

Portfolio accounting: each opened position takes a fixed fraction
(``max_position_per_name``) of current equity; at most ``max_positions`` names
are held at once. Cash + mark-to-market positions make the equity curve.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import BacktestConfig

from .cost import CostModel
from .metrics import compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class EventResult:
    """Outcome of an event-driven backtest."""

    equity: pd.Series
    metrics: dict[str, float]
    trades: pd.DataFrame
    positions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": self.metrics,
            "final_equity": (float(self.equity.iloc[-1]) if len(self.equity) else None),
            "num_trades": int(len(self.trades)),
            "num_positions": len(self.positions),
        }


class EventBacktest:
    """Event-driven, cost-aware backtest for single-name short-horizon strategies."""

    def __init__(
        self,
        config: BacktestConfig,
        *,
        stop_loss: float = -0.05,
        take_profit: float = 0.10,
        max_holding_days: int = 5,
        max_position_per_name: float = 0.1,
        max_positions: int = 10,
    ) -> None:
        self.config = config
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        self.max_holding_days = int(max_holding_days)
        self.max_position_per_name = float(max_position_per_name)
        self.max_positions = int(max_positions)
        self.cost_model = CostModel(**config.cost.model_dump())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        signals: dict[str, pd.Series],
        prices: dict[str, pd.DataFrame],
        benchmark: pd.Series | None = None,
    ) -> EventResult:
        """Run the event backtest over a set of codes.

        Args:
            signals: code -> boolean/int entry-signal series indexed by date.
                A truthy value on day T schedules an entry at T+1's open.
            prices: code -> OHLCV DataFrame indexed by date (needs at least
                ``open``/``high``/``low``/``close`` columns).
            benchmark: optional benchmark close series; if omitted, a flat
                buy-and-hold at ``initial_cash`` is used so ``benchmark_return``
                reports 0.
        """
        if not prices:
            return EventResult(pd.Series(dtype=float), {}, self._empty_trades(), [])

        common = self._common_index(prices)
        n = len(common)

        open_a, high_a, low_a, close_a, last_close = self._align_prices(prices, common, n)
        sig_arr = {
            code: np.asarray(s.reindex(common).fillna(0).to_numpy(), dtype="float64")
            for code, s in signals.items()
        }

        cash = float(self.config.initial_cash)
        positions: dict[str, dict] = {}
        pending: list[str] = []  # codes whose T-day signal fires at next open
        trades_rows: list[dict] = []
        position_log: list[dict] = []
        equity_vals: list[float] = []

        for i in range(n):
            t = common[i]

            # 1. Execute pending entries at T+1 open (no look-ahead: signal was
            #    known at the prior close; we only consume this day's open).
            for code in pending:
                if code in positions or len(positions) >= self.max_positions:
                    continue
                op = open_a[code][i]
                if np.isnan(op) or op <= 0:
                    continue
                eq_now = cash + sum(
                    positions[c]["shares"] * last_close[c]
                    for c in positions
                    if not np.isnan(last_close[c])
                )
                if eq_now <= 0:
                    continue
                notional = eq_now * min(self.max_position_per_name, 1.0)
                shares = notional / op
                cost = self.cost_model.charge(notional, is_sell=False)
                cash -= notional + cost
                positions[code] = {
                    "entry_date": t,
                    "entry_price": op,
                    "shares": shares,
                    "days_held": 0,
                }
                trades_rows.append(
                    {
                        "date": t,
                        "action": "buy",
                        "price": float(op),
                        "weight_change": 1.0,
                        "notional": float(notional),
                        "cost": float(cost),
                    }
                )
            pending = []

            # 2. Exit checks using this day's OHLC (standing stop/target orders).
            for code in list(positions.keys()):
                lo = low_a[code][i]
                hi = high_a[code][i]
                cl = close_a[code][i]
                if np.isnan(lo) or np.isnan(hi) or np.isnan(cl):
                    continue  # code not trading today; cannot evaluate/exit
                pos = positions[code]
                pos["days_held"] += 1
                stop_px = pos["entry_price"] * (1.0 + self.stop_loss)
                tgt_px = pos["entry_price"] * (1.0 + self.take_profit)
                exit_price: float | None = None
                if lo <= stop_px:
                    exit_price = cl
                elif hi >= tgt_px:
                    exit_price = cl
                elif pos["days_held"] >= self.max_holding_days:
                    exit_price = cl
                if exit_price is not None:
                    proceeds = pos["shares"] * exit_price
                    cost = self.cost_model.charge(proceeds, is_sell=True)
                    cash += proceeds - cost
                    trades_rows.append(
                        {
                            "date": t,
                            "action": "sell",
                            "price": float(exit_price),
                            "weight_change": -1.0,
                            "notional": float(proceeds),
                            "cost": float(cost),
                        }
                    )
                    position_log.append(
                        {
                            "code": code,
                            "entry_date": str(pos["entry_date"]),
                            "entry_price": float(pos["entry_price"]),
                            "exit_date": str(t),
                            "exit_price": float(exit_price),
                            "days_held": int(pos["days_held"]),
                            "return": float(exit_price / pos["entry_price"] - 1.0),
                        }
                    )
                    del positions[code]

            # 3. Carry last close for mark-to-market.
            for code in prices:
                cl = close_a[code][i]
                if not np.isnan(cl):
                    last_close[code] = cl

            # 4. Mark to market.
            eq = cash + sum(
                positions[c]["shares"] * last_close[c]
                for c in positions
                if not np.isnan(last_close[c])
            )
            equity_vals.append(eq)

            # 5. Collect today's signals -> execute at next open (T -> T+1).
            for code, arr in sig_arr.items():
                if i < len(arr) and arr[i] > 0:
                    if code not in positions:
                        pending.append(code)

        equity = pd.Series(equity_vals, index=common)
        trades = pd.DataFrame(
            trades_rows, columns=["date", "action", "price", "weight_change", "notional", "cost"]
        )
        bench = (
            benchmark.reindex(common).ffill().bfill()
            if benchmark is not None
            else pd.Series(float(self.config.initial_cash), index=common)
        )

        if equity.empty or len(equity) < 2:
            metrics = {k: 0.0 for k in self.config.metrics}
            if self.config.benchmark:
                metrics["benchmark_return"] = 0.0
        else:
            metrics = compute_metrics(equity, trades, bench, self.config)

        return EventResult(equity, metrics, trades, position_log)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _common_index(prices: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
        union: set[pd.Timestamp] = set()
        for df in prices.values():
            union.update(pd.DatetimeIndex(df.index))
        return pd.DatetimeIndex(sorted(union))

    @staticmethod
    def _align_prices(
        prices: dict[str, pd.DataFrame], common: pd.DatetimeIndex, n: int
    ) -> tuple[dict, dict, dict, dict, dict]:
        open_a, high_a, low_a, close_a, last_close = {}, {}, {}, {}, {}
        for code, df in prices.items():
            a = df.reindex(common)
            open_a[code] = (
                a["open"].to_numpy(dtype="float64") if "open" in a else np.full(n, np.nan)
            )
            high_a[code] = (
                a["high"].to_numpy(dtype="float64") if "high" in a else np.full(n, np.nan)
            )
            low_a[code] = a["low"].to_numpy(dtype="float64") if "low" in a else np.full(n, np.nan)
            close_a[code] = (
                a["close"].to_numpy(dtype="float64") if "close" in a else np.full(n, np.nan)
            )
            last_close[code] = np.nan
        return open_a, high_a, low_a, close_a, last_close

    @staticmethod
    def _empty_trades() -> pd.DataFrame:
        return pd.DataFrame(
            columns=["date", "action", "price", "weight_change", "notional", "cost"]
        )
