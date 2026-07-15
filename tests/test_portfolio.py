"""Tests for the Sprint 1.16 portfolio (Top-N rebalancing) backtest.

The expensive ranking/backtest steps are injected (rank_fn / equity_fn) so the
combination logic is tested without the full upstream pipeline or real data.
"""

from __future__ import annotations

import pandas as pd

from backtest.portfolio import PortfolioBacktest
from core.config import BacktestConfig


def _make_engine(top_n=2, rebalance_freq="ME"):
    eng = PortfolioBacktest.__new__(PortfolioBacktest)
    eng.config = BacktestConfig()  # initial_cash=1e6, metrics default, benchmark=True
    eng.top_n = top_n
    eng.rebalance_freq = rebalance_freq
    eng.ranking_engine = None
    eng.backtest_engine = None
    return eng


def _frames():
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    slopes = {"A": 1.0, "B": 2.0, "C": 0.5}

    def equity_fn(code, dm, start, end):
        slope = slopes.get(code, 1.0)
        return pd.Series([100.0 + slope * i for i in range(20)], index=dates)

    def rank_fn(codes, dm, start, end):
        # Always prefer the two steepest (A, B).
        return [c for c in ["A", "B", "C"] if c in codes][:2]

    return equity_fn, rank_fn


def test_portfolio_combines_and_grows():
    eng = _make_engine()
    equity_fn, rank_fn = _frames()
    res = eng.run(["A", "B", "C"], None, None, None, rank_fn=rank_fn, equity_fn=equity_fn)
    assert not res.equity.empty
    assert len(res.selections) >= 1
    # A and B both grow, equal-weighted -> portfolio grows.
    assert res.equity.iloc[-1] > res.equity.iloc[0]
    assert "total_return" in res.metrics
    assert "benchmark_return" in res.metrics  # benchmark enabled


def test_portfolio_top_n_respected():
    eng = _make_engine(top_n=1)
    equity_fn, rank_fn = _frames()

    def rank_top1(codes, dm, start, end):
        return ["B"]  # only the steepest

    res = eng.run(["A", "B", "C"], None, None, None, rank_fn=rank_top1, equity_fn=equity_fn)
    for _d, sel in res.selections:
        assert sel == ["B"]


def test_portfolio_empty_data_graceful():
    eng = _make_engine()

    def empty_fn(code, dm, start, end):
        return pd.Series(dtype=float)

    def rank_fn(codes, dm, start, end):
        return []

    res = eng.run(["A", "B"], None, None, None, rank_fn=rank_fn, equity_fn=empty_fn)
    assert res.equity.empty
    assert res.metrics  # zeros filled, not crashing


def test_portfolio_to_dict():
    eng = _make_engine()
    equity_fn, rank_fn = _frames()
    res = eng.run(["A", "B", "C"], None, None, None, rank_fn=rank_fn, equity_fn=equity_fn)
    d = res.to_dict()
    assert d["num_rebalances"] == len(res.selections)
    assert d["final_equity"] is not None
