"""Tests for the Sprint 1.6 backtest engine.

Mirrors tests/test_strategies.py: pure unit checks for the cost model and
metrics, an end-to-end engine run on synthetic data, a no-look-ahead
truncation test, and a CLI smoke test.
"""

from __future__ import annotations

import math

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
# Sprint 2.2 — extended metrics (hand-checked)
# --------------------------------------------------------------------------- #
def test_metric_profit_factor():
    # 100->110 (+.10), 110->100 (-1/11), 100->110 (+.10): pf = .20 / (1/11) = 2.2
    eq = pd.Series([100.0, 110.0, 100.0, 110.0])
    close = pd.Series([100.0, 110.0, 100.0, 110.0])
    cfg = BacktestConfig(metrics=["profit_factor"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert abs(m["profit_factor"] - 2.2) < 1e-9


def test_metric_profit_factor_no_loss_is_inf():
    eq = pd.Series([100.0, 110.0, 110.0, 121.0])
    close = pd.Series([100.0, 110.0, 110.0, 121.0])
    cfg = BacktestConfig(metrics=["profit_factor"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert math.isinf(m["profit_factor"])


def test_metric_profit_factor_flat_is_zero():
    eq = pd.Series([100.0, 100.0, 100.0])
    close = pd.Series([100.0, 100.0, 100.0])
    cfg = BacktestConfig(metrics=["profit_factor"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert m["profit_factor"] == 0.0


def test_metric_calmar():
    # 252 bars: 100 -> dip 90 -> steady 120. cagr=0.20, mdd=-0.10 => calmar=2.0
    eq = pd.Series([100.0, 90.0] + [120.0] * 250)
    close = eq
    cfg = BacktestConfig(metrics=["calmar"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert abs(m["calmar"] - 2.0) < 1e-9


def test_metric_calmar_no_drawdown_is_zero():
    eq = pd.Series([100.0, 110.0, 121.0])  # monotonic up -> mdd = 0
    close = eq
    cfg = BacktestConfig(metrics=["calmar"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert m["calmar"] == 0.0


def test_metric_avg_holding_days():
    trades = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-06")],
            "weight_change": [1.0, -1.0],
        }
    )
    eq = pd.Series([100.0, 100.0])
    cfg = BacktestConfig(metrics=["avg_holding_days"])
    m = compute_metrics(eq, trades, eq, cfg)
    assert abs(m["avg_holding_days"] - 5.0) < 1e-9


def test_metric_avg_holding_days_few_trades_is_zero():
    trades = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "weight_change": [1.0]})
    eq = pd.Series([100.0])
    cfg = BacktestConfig(metrics=["avg_holding_days"])
    m = compute_metrics(eq, trades, eq, cfg)
    assert m["avg_holding_days"] == 0.0


def test_metric_max_consecutive_losses():
    # down run of 3 (bars 1,2,3)
    eq = pd.Series([100.0, 99.0, 98.0, 97.0, 100.0])
    close = eq
    cfg = BacktestConfig(metrics=["max_consecutive_losses"])
    m = compute_metrics(eq, pd.DataFrame(columns=["weight_change"]), close, cfg)
    assert m["max_consecutive_losses"] == 3.0


def test_metric_exposure():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    equity = pd.Series([100.0] * 10, index=idx)
    trades = pd.DataFrame({"date": [idx[0], idx[5]], "weight_change": [1.0, -1.0]})
    cfg = BacktestConfig(metrics=["exposure"])
    m = compute_metrics(equity, trades, equity, cfg)
    # bars 0-4 invested (5), bars 5-9 flat (5) => exposure 0.5
    assert abs(m["exposure"] - 0.5) < 1e-9


def test_metric_exposure_no_trades_is_zero():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    equity = pd.Series([100.0] * 5, index=idx)
    cfg = BacktestConfig(metrics=["exposure"])
    m = compute_metrics(equity, pd.DataFrame(columns=["weight_change"]), equity, cfg)
    assert m["exposure"] == 0.0


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


# --------------------------------------------------------------------------- #
# Sprint 1.12: backtest result cache
# --------------------------------------------------------------------------- #
from datetime import date  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backtest.cache import (  # noqa: E402
    BacktestCache,
    compute_params_hash,
    run_code_cached,
)
from core.database import Base  # noqa: E402


def _isolated_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    return Session()


class _FakeBT:
    def __init__(self) -> None:
        self.config = BacktestConfig()
        self.names = ["weighted_momentum"]
        self._calls = 0

    def run_code(self, code, dm, start=None, end=None, signal_col=None, use_cache=True):
        self._calls += 1
        df = dm.get_daily(code, start, end).copy()
        df["equity"] = list(range(len(df)))
        metrics = {
            "total_return": 0.12,
            "max_drawdown": -0.07,
            "sharpe": 1.3,
            "benchmark_return": 0.05,
        }
        return df, metrics


class _FakeDM:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_daily(self, code, start=None, end=None):
        return self._df


def _frame() -> pd.DataFrame:
    n = 10
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": [100] * n,
            "high": [100] * n,
            "low": [100] * n,
            "close": list(range(100, 100 + n)),
            "volume": [1000] * n,
            "amount": [1000] * n,
        }
    )


def test_backtest_cache_hit_avoids_recompute():
    s = _isolated_session()
    fake = _FakeBT()
    dm = _FakeDM(_frame())
    a, b = date(2024, 1, 1), date(2024, 1, 10)
    run_code_cached(fake, "A", dm, a, b, None, session=s)
    run_code_cached(fake, "A", dm, a, b, None, session=s)  # same window -> hit
    assert fake._calls == 1
    # different window -> recompute (miss)
    run_code_cached(fake, "A", dm, a, date(2024, 1, 20), None, session=s)
    assert fake._calls == 2
    s.close()


def test_backtest_cache_persists_rows():
    s = _isolated_session()
    fake = _FakeBT()
    dm = _FakeDM(_frame())
    run_code_cached(fake, "A", dm, date(2024, 1, 1), date(2024, 1, 10), None, session=s)
    run_code_cached(fake, "B", dm, date(2024, 1, 1), date(2024, 1, 10), None, session=s)
    rows = s.query(BacktestCache).all()
    assert len(rows) == 2
    s.close()


def test_backtest_params_hash_deterministic():
    cfg = BacktestConfig()
    h1 = compute_params_hash(cfg, "signal_x", date(2024, 1, 1), date(2024, 1, 10))
    h2 = compute_params_hash(cfg, "signal_x", date(2024, 1, 1), date(2024, 1, 10))
    assert h1 == h2
    h3 = compute_params_hash(cfg, "signal_x", date(2024, 1, 1), date(2024, 1, 11))
    assert h3 != h1
