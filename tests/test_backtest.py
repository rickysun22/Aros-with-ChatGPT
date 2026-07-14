"""Tests for the Sprint 1.6 backtest engine.

Mirrors tests/test_strategies.py: pure unit checks for the cost model and
metrics, an end-to-end engine run on synthetic data, a no-look-ahead
truncation test, and a CLI smoke test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.cost import CostModel
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics
from core.config import (
    BacktestConfig,
    CostConfig,
    FactorConfig,
    IndicatorConfig,
    StrategyConfig,
    get_config,
)
from core.exceptions import ConfigError, DataError


def make_engine(backtest=None, indicators=None, factors=None, strategies=None):
    """Build a BacktestEngine; empty configs make compute a pass-through."""
    bt = backtest or BacktestConfig()
    return BacktestEngine.from_config(
        indicators or IndicatorConfig(),
        factors or FactorConfig(),
        strategies or StrategyConfig(),
        bt,
    )


def price_df(closes, signals, start="2024-01-01"):
    """Synthetic single-stock frame with an exogenous signal_test column."""
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": list(closes),
            "high": list(closes),
            "low": list(closes),
            "close": list(closes),
            "volume": [1000] * n,
            "amount": [1000] * n,
            "signal_test": list(signals),
        }
    )


# --------------------------------------------------------------------------- #
# Cost model
# --------------------------------------------------------------------------- #
def test_cost_commission_min_buy():
    c = CostModel()
    # notional 1e6: commission 250 (> min 5), no stamp, transfer 10 -> 260
    assert abs(c.charge(1_000_000, is_sell=False) - 260.0) < 1e-9
    # small notional: commission = max(0.25, 5) = 5, transfer 0.01 -> 5.01
    assert abs(c.charge(1_000, is_sell=False) - 5.01) < 1e-9


def test_cost_stamp_only_on_sell():
    c = CostModel()
    buy = c.charge(1_000_000, is_sell=False)
    sell = c.charge(1_000_000, is_sell=True)
    # sell adds exactly the stamp tax (0.0005 * 1e6 = 500)
    assert abs(sell - buy - 500.0) < 1e-9


def test_cost_slippage():
    c = CostModel(slippage=0.001)
    # notional 1e6 buy: 250 commission + 10 transfer + 1000 slippage = 1260
    assert abs(c.charge(1_000_000, is_sell=False) - 1260.0) < 1e-9


# --------------------------------------------------------------------------- #
# Metrics (pure functions)
# --------------------------------------------------------------------------- #
def test_metrics_constant_equity():
    eq = pd.Series([100.0, 100.0, 100.0, 100.0])
    close = pd.Series([10.0, 10.0, 10.0, 10.0])
    cfg = BacktestConfig()
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert abs(m["total_return"]) < 1e-9
    assert abs(m["max_drawdown"]) < 1e-9
    assert abs(m["sharpe"]) < 1e-9
    assert abs(m["sortino"]) < 1e-9
    assert abs(m["win_rate"]) < 1e-9
    assert m["num_trades"] == 0.0


def test_metrics_hand_computed():
    eq = pd.Series([100.0, 110.0, 121.0, 108.9])
    close = pd.Series([100.0, 110.0, 121.0, 108.9])
    cfg = BacktestConfig()
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert abs(m["total_return"] - 0.089) < 1e-9
    assert abs(m["max_drawdown"] - (-0.1)) < 1e-9
    assert abs(m["benchmark_return"] - 0.089) < 1e-9


def test_unknown_metric_raises():
    eq = pd.Series([100.0, 110.0])
    close = pd.Series([100.0, 110.0])
    with pytest.raises(ConfigError):
        compute_metrics(
            eq, pd.DataFrame(columns=["weight_change"]), close, BacktestConfig(metrics=["bogus"])
        )


# --------------------------------------------------------------------------- #
# Cost-aware simulation vs no-cost
# --------------------------------------------------------------------------- #
def test_cost_aware_le_no_cost():
    df = price_df([100, 110, 121, 108.9], [0, 1, 1, 0])
    eng = make_engine()
    out, _ = eng.run(df, signal_col="signal_test")
    free = make_engine(
        backtest=BacktestConfig(
            cost=CostConfig(
                commission_rate=0.0,
                commission_min=0.0,
                stamp_tax_rate=0.0,
                transfer_fee_rate=0.0,
                slippage=0.0,
            )
        )
    )
    out_free, _ = free.run(df, signal_col="signal_test")
    assert (out["equity"] <= out_free["equity"] + 1e-6).all()


# --------------------------------------------------------------------------- #
# Trade blotter
# --------------------------------------------------------------------------- #
def test_trade_blotter_buy_and_sell():
    df = price_df([100, 110, 121, 130], [0, 1, 0, 0])
    eng = make_engine()
    pos = eng._to_position(df, "signal_test")
    _out, _eq, trades = eng._simulate(df, pos)
    assert len(trades) == 2
    assert list(trades["action"]) == ["buy", "sell"]
    assert abs(trades.iloc[0]["cost"] - 260.0) < 1e-6
    # sell cost: commission 274.93 + stamp 549.86 + transfer 10.997 = ~835.78
    assert abs(trades.iloc[1]["cost"] - 835.78) < 0.5
    assert abs(trades.iloc[0]["notional"] - 1_000_000.0) < 1.0


def test_trade_metrics_num_trades_turnover():
    df = price_df([100, 110, 121, 130], [0, 1, 0, 0])
    eng = make_engine()
    out, metrics = eng.run(df, signal_col="signal_test")
    assert metrics["num_trades"] == 2.0
    assert abs(metrics["turnover"] - 2.0) < 1e-9
    assert "benchmark_return" in metrics


# --------------------------------------------------------------------------- #
# max_position clamp
# --------------------------------------------------------------------------- #
def test_max_position_clamp():
    df = price_df([100, 110, 121, 130], [0, 1, 1, 1])
    eng = make_engine(backtest=BacktestConfig(max_position=0.5))
    out, _ = eng.run(df, signal_col="signal_test")
    assert out["position"].max() <= 0.5 + 1e-9
    assert abs(out["position"].max() - 0.5) < 1e-9


# --------------------------------------------------------------------------- #
# No look-ahead: truncating the input reproduces the prefix of the equity curve
# --------------------------------------------------------------------------- #
def test_no_lookahead_truncation():
    closes = [100, 110, 121, 108.9, 120, 132, 145, 130]
    signals = [0, 1, 1, 0, 1, 1, 1, 0]
    df = price_df(closes, signals)
    eng = make_engine()
    full, _ = eng.run(df, signal_col="signal_test")
    eq_full = full["equity"].to_numpy()
    n = len(df)
    for k in range(2, n):
        trunc, _ = eng.run(df.iloc[:k], signal_col="signal_test")
        eq_k = trunc["equity"].to_numpy()
        assert np.allclose(eq_k, eq_full[:k], atol=1e-6), f"mismatch at k={k}"


# --------------------------------------------------------------------------- #
# Missing signal column -> DataError
# --------------------------------------------------------------------------- #
def test_missing_signal_raises():
    df = price_df([100, 110, 121], [0, 1, 0])
    eng = make_engine()
    with pytest.raises(DataError):
        eng.run(df, signal_col="signal_nonexistent")


# --------------------------------------------------------------------------- #
# Integration: full pipeline on synthetic OHLCV using the real config
# --------------------------------------------------------------------------- #
def test_integration_real_config():
    n = 80
    rng = np.random.default_rng(7)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.02, n))
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": [1_000_000] * n,
            "amount": (1_000_000 * close).tolist(),
        }
    )
    cfg = get_config()
    eng = BacktestEngine.from_config(cfg.indicators, cfg.factors, cfg.strategies, cfg.backtest)
    out, metrics = eng.run(df)  # signal_col=None -> default weighted_momentum
    assert "equity" in out.columns
    assert "position" in out.columns
    for key in ("total_return", "sharpe", "max_drawdown", "num_trades", "turnover"):
        assert key in metrics
    assert out["equity"].iloc[0] == cfg.backtest.initial_cash


# --------------------------------------------------------------------------- #
# CLI smoke
# --------------------------------------------------------------------------- #
def test_cli_backtest_list():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    result = runner.invoke(main.app, ["backtest", "--list"])
    assert result.exit_code == 0, result.output
    assert "Available strategies" in result.output
    assert "weighted_momentum" in result.output
