"""Sprint 3.0 — EventBacktest tests.

Anchors the Phase 3 execution rule: T-day close signal -> T+1 open entry, and
stop/take-profit/max-holding-days exits at close. The no-look-ahead property is
asserted explicitly (no position on day 0, buy never on the signal day).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.event import EventBacktest
from core.config import BacktestConfig


def _df(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float]
) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(opens), freq="D")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx)


def _sig(flags: list[int]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(flags), freq="D")
    return pd.Series(flags, index=idx, dtype="float64")


def test_take_profit_path_and_no_lookahead() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    prices = {
        "X": _df(
            opens=[10, 10.5, 11.5, 12.5, 13.5],
            highs=[10, 11.5, 12.5, 13.5, 14.5],
            lows=[9.5, 10.5, 11.5, 12.5, 13.5],
            closes=[10, 11, 12, 13, 14],
        )
    }
    signals = {"X": _sig([1, 0, 0, 0, 0])}  # signal on day 0 -> enter day 1 open

    eb = EventBacktest(BacktestConfig(), stop_loss=-0.05, take_profit=0.10, max_holding_days=5)
    res = eb.run(signals, prices)

    # No position on day 0 (no look-ahead): equity starts at initial cash.
    assert res.equity.iloc[0] == pytest.approx(1_000_000.0)
    # Exactly one round trip.
    assert len(res.trades) == 2
    buy, sell = res.trades.iloc[0], res.trades.iloc[1]
    assert buy["action"] == "buy" and buy["date"] == dates[1]  # T+1 open entry
    assert sell["action"] == "sell" and sell["date"] == dates[2]  # target hit day 2
    # Buy never happens on the signal day (day 0).
    assert buy["date"] != dates[0]
    assert res.metrics["num_trades"] == 2
    # Profitable round trip (entry 10.5 -> exit 12, before costs).
    assert res.equity.iloc[-1] > 1_000_000.0
    assert len(res.positions) == 1  # logged round trip
    assert res.positions[0]["return"] == pytest.approx(12 / 10.5 - 1.0, rel=1e-6)


def test_stop_loss_path() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    prices = {
        "Y": _df(
            opens=[10, 10, 9, 8, 8],
            highs=[10, 10, 9.5, 9, 9],
            lows=[10, 9, 8.5, 7.5, 7.5],
            closes=[10, 9.5, 9, 8, 8],
        )
    }
    signals = {"Y": _sig([1, 0, 0, 0, 0])}

    eb = EventBacktest(BacktestConfig(), stop_loss=-0.05, take_profit=0.50, max_holding_days=5)
    res = eb.run(signals, prices)

    assert len(res.trades) == 2
    buy, sell = res.trades.iloc[0], res.trades.iloc[1]
    assert buy["action"] == "buy" and buy["date"] == dates[1]
    # Stop price = 10 * 0.95 = 9.5; day-1 low 9.0 breaches it -> exit at close 9.5.
    assert sell["action"] == "sell" and sell["date"] == dates[1]
    assert sell["price"] == pytest.approx(9.5)
    assert res.positions[0]["return"] == pytest.approx(9.5 / 10.0 - 1.0, rel=1e-6)


def test_max_holding_days_expiry() -> None:
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    # Drifts up but stays below the 10% target, so only the expiry rule fires.
    prices = {
        "Z": _df(
            opens=[10, 10.2, 10.4, 10.6, 10.8, 11.0],
            highs=[10, 10.3, 10.5, 10.7, 10.9, 11.1],
            lows=[10, 10.1, 10.3, 10.5, 10.7, 10.9],
            closes=[10, 10.2, 10.4, 10.6, 10.8, 11.0],
        )
    }
    signals = {"Z": _sig([1, 0, 0, 0, 0, 0])}

    eb = EventBacktest(BacktestConfig(), stop_loss=-0.05, take_profit=0.50, max_holding_days=2)
    res = eb.run(signals, prices)

    assert len(res.trades) == 2
    buy, sell = res.trades.iloc[0], res.trades.iloc[1]
    assert buy["date"] == dates[1]
    # Entered day 1, held 2 days -> expires at day 2 close (entry date + 1).
    assert sell["date"] == dates[2]
    assert res.positions[0]["days_held"] == 2


def test_no_signals_no_trades() -> None:
    prices = {
        "X": _df(
            opens=[10, 10.5, 11.5, 12.5, 13.5],
            highs=[10, 11.5, 12.5, 13.5, 14.5],
            lows=[9.5, 10.5, 11.5, 12.5, 13.5],
            closes=[10, 11, 12, 13, 14],
        )
    }
    signals = {"X": _sig([0, 0, 0, 0, 0])}
    eb = EventBacktest(BacktestConfig())
    res = eb.run(signals, prices)
    assert len(res.trades) == 0
    assert res.equity.iloc[0] == pytest.approx(1_000_000.0)
