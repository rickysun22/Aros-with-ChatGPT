"""Sprint 3.1 — Strategy Library tests.

Anchors the §7 directory: every strategy's entry-signal rule fires on crafted
data, no strategy leaks future data, and the registry + runner are wired.

All synthetic frames use a single shared DatetimeIndex so column alignment is
correct (the earlier 18-row anomaly came from a mismatched-index fixture, not
from the strategy code -- real ``get_daily`` output always shares one index).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import BacktestConfig
from research.strategy_library import (
    STRATEGIES,
    get_strategy,
    list_strategies,
    run_strategy,
)


def _frame(
    close: list[float],
    *,
    open_: list[float] | None = None,
    high_: list[float] | None = None,
    low_: list[float] | None = None,
    vol: list[float] | None = None,
    start: str = "2024-01-01",
    n: int = 60,
) -> pd.DataFrame:
    """Build an OHLCV frame with a single shared DatetimeIndex.

    ``open_``/``high_``/``low_`` default to a small bullish spread around close;
    pass them explicitly to model down days / inside days.
    """
    idx = pd.date_range(start, periods=len(close), freq="D")
    c = pd.Series(close, index=idx)
    o = pd.Series(open_ if open_ is not None else (c * 0.99), index=idx)
    h = pd.Series(high_ if high_ is not None else (c * 1.02), index=idx)
    lo = pd.Series(low_ if low_ is not None else (c * 0.98), index=idx)
    if vol is None:
        vol = [1_000_000.0] * len(close)
    v = pd.Series(vol, index=idx)
    return pd.DataFrame(
        {
            "open": o.round(3),
            "high": h.round(3),
            "low": lo.round(3),
            "close": c.round(3),
            "volume": v,
        }
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_registry_has_10_strategies() -> None:
    names = {s.spec.name for s in list_strategies()}
    assert names == {
        "ma_bull",
        "high_breakout",
        "volume_breakout",
        "strong_pullback",
        "leader_first_down",
        "shrink_reversal",
        "first_board",
        "second_board_relay",
        "high_board",
        "sentiment_rebound",
    }
    assert len(STRATEGIES) == 10


def test_spec_contract_fields_frozen() -> None:
    # D1/D2/D3/D7 invariants on the published specs.
    cats = {s.spec.category for s in list_strategies()}
    assert cats == {"trend", "strong", "emotion"}
    engines = {s.spec.engine for s in list_strategies()}
    assert engines == {"portfolio", "event"}
    # D3: the advisory-only strategy is explicitly flagged.
    assert get_strategy("high_board").spec.data_fidelity == "needs_intraday"
    # D7: every strategy binds a universe.
    assert all(s.spec.universe in {"csi800", "all_a", "custom"} for s in list_strategies())


# --------------------------------------------------------------------------- #
# No look-ahead (design §8 -- hard requirement)
# --------------------------------------------------------------------------- #
def test_no_future_function_leak() -> None:
    """Truncating the input must not change earlier signals (no look-ahead)."""
    rng = np.random.RandomState(7)
    close = (np.linspace(10, 15, 80) + rng.randn(80) * 0.2).tolist()
    prices = {"000001": _frame(close, start="2024-01-01", n=80)}
    for name in ("high_breakout", "volume_breakout", "leader_first_down", "first_board"):
        full = get_strategy(name).entry_signals(prices)["000001"]
        cut = 50
        trunc = get_strategy(name).entry_signals({"000001": prices["000001"].iloc[:cut]})["000001"]
        assert full.iloc[:cut].reindex(trunc.index).equals(trunc), f"{name} leaked"


# --------------------------------------------------------------------------- #
# Per-strategy rule tests
# --------------------------------------------------------------------------- #
def test_ma_bull_scores_aligned_only() -> None:
    # Steady uptrend with MA5>MA10>MA20 -> positive score, else ~0.
    close = list(np.linspace(10, 20, 60))
    sig = get_strategy("ma_bull").entry_signals({"A": _frame(close)})["A"]
    # After warm-up the aligned regime holds; entry signal True on most days.
    assert bool(sig.iloc[-1])
    assert sig.iloc[25:].sum() > 20


def test_high_breakout_fires_on_new_high() -> None:
    close = list(np.linspace(10, 14, 30)) + [20.0] + list(np.linspace(14, 15, 10))
    vol = [1_000_000] * 41
    vol[30] = 5_000_000  # volume surge on the breakout bar
    sig = get_strategy("high_breakout").entry_signals({"A": _frame(close, vol=vol)})["A"]
    assert bool(sig.iloc[30])  # the N-day-high day fires
    assert int(sig.iloc[:30].sum()) == 0  # nothing before the spike


def test_volume_breakout_fires_on_surge() -> None:
    base = list(np.linspace(10, 12, 40))
    close = base + [12.4]  # small clearance above MA, not an N-day high
    vol = [1_000_000] * 40 + [4_000_000]  # big surge
    sig = get_strategy("volume_breakout").entry_signals({"A": _frame(close, vol=vol)})["A"]
    assert bool(sig.iloc[-1])


def test_strong_pullback_fires_on_relaunch() -> None:
    # uptrend, then a 2-day soft pullback (down days, low vol), then relaunch.
    up = list(np.linspace(10, 14, 20))
    pull_close = [13.8, 13.6]  # down days (close below prior close)
    pull_open = [14.0, 13.9]  # open above close => red bars
    relaunch_close = [14.2]  # up day, closes back above support
    relaunch_open = [13.6]
    close = up + pull_close + relaunch_close
    open_ = list(np.linspace(9.9, 13.9, 20)) + pull_open + relaunch_open
    vol = [2_000_000] * 23
    vol[20] = 500_000  # shrink on pullback
    vol[21] = 500_000
    sig = get_strategy("strong_pullback").entry_signals({"A": _frame(close, open_=open_, vol=vol)})[
        "A"
    ]
    assert bool(sig.iloc[-1])


def test_leader_first_down_fires() -> None:
    up = list(np.linspace(10, 15, 20))  # strong uptrend
    first_down = [14.6]  # first down day (close < prior close)
    close = up + first_down
    sig = get_strategy("leader_first_down").entry_signals({"A": _frame(close)})["A"]
    assert bool(sig.iloc[-1])
    assert int(sig.iloc[:-1].sum()) == 0


def test_shrink_reversal_fires() -> None:
    # Pre-window long enough for the 20-bar volume average to be meaningful.
    # wash-out red bar on shrinking volume, then a bullish engulfing bar.
    pre = list(np.linspace(10, 12, 25))
    wash_close = [11.5]  # down day
    wash_open = [11.9]  # open above close => red bar
    engulf_close = [12.0]  # up day covering the prior body
    engulf_open = [11.3]  # open below prior close
    close = pre + wash_close + engulf_close
    open_ = list(np.linspace(9.9, 11.9, 25)) + wash_open + engulf_open
    vol = [2_000_000] * 27
    vol[25] = 400_000  # shrink on the wash-out day
    sig = get_strategy("shrink_reversal").entry_signals({"A": _frame(close, open_=open_, vol=vol)})[
        "A"
    ]
    assert bool(sig.iloc[-1])


def test_first_board_second_board_high_board() -> None:
    idx = pd.date_range("2024-02-01", periods=8)
    c = pd.Series([10, 10, 10, 10, 11.0, 12.1, 13.33, 13.33], index=idx)
    df = pd.DataFrame(
        {
            "open": (c * 0.99).round(3),
            "high": (c * 1.02).round(3),
            "low": (c * 0.98).round(3),
            "close": c.round(3),
            "volume": pd.Series([1e3] * 8, index=idx),
        }
    )
    prices = {"X": df}
    fb = get_strategy("first_board").entry_signals(prices)["X"]
    sb = get_strategy("second_board_relay").entry_signals(prices)["X"]
    hb = get_strategy("high_board").entry_signals(prices)["X"]
    assert fb.tolist() == [False, False, False, False, True, False, False, False]
    assert sb.tolist() == [False, False, False, False, False, True, True, False]
    assert hb.tolist() == [False, False, False, False, False, False, True, False]


def test_sentiment_rebound_fires() -> None:
    # Sustained drawdown below MA, then a reversal up day.
    down = list(np.linspace(20, 14, 30))
    rebound = [14.8]  # up day after fear
    close = down + rebound
    sig = get_strategy("sentiment_rebound").entry_signals({"A": _frame(close)})["A"]
    assert bool(sig.iloc[-1])


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def test_run_strategy_event_engine() -> None:
    close = list(np.linspace(10, 14, 30)) + [20.0] + list(np.linspace(14, 15, 10))
    vol = [1_000_000] * 41
    vol[30] = 5_000_000
    prices = {"000001": _frame(close, vol=vol)}
    res = run_strategy(get_strategy("high_breakout"), prices, BacktestConfig())
    assert isinstance(res.metrics, dict) and "total_return" in res.metrics
    assert len(res.trades) >= 1  # at least the breakout entry


def test_run_strategy_portfolio_cross_section() -> None:
    # Two names; ma_bull runs through the cross-sectional Top-N path without error.
    strong = list(np.linspace(10, 18, 60))
    weak = list(np.linspace(10, 11, 60))
    prices = {"STRONG": _frame(strong), "WEAK": _frame(weak)}
    strat = get_strategy("ma_bull")
    res = run_strategy(strat, prices, BacktestConfig())
    assert res.metrics["num_trades"] >= 1
    # Strong name scores higher, so it must be selected at least once.
    scores = strat.score(prices)
    assert float(scores["STRONG"].iloc[-1]) > float(scores["WEAK"].iloc[-1])
