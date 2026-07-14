"""Tests for the Sprint 1.5 Strategy Engine.

Mirrors the factor suite and adds strategy-specific checks: registry / build,
pure-function correctness of weighted and rule types, missing-column DataError,
malformed-param ConfigError, the no-future-function leakage invariant, Portfolio
signal->position / mark-to-market, engine orchestration, and CLI smoke tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from core.config import (
    FactorConfig,
    FactorSpec,
    IndicatorConfig,
    IndicatorSpec,
    StrategyConfig,
    StrategySpec,
)
from core.exceptions import ConfigError, DataError
from main import app
from strategies import SignalType, StrategyEngine, available, build, to_position
from strategies.portfolio import Portfolio


def _make_df(n: int = 40) -> pd.DataFrame:
    """Deterministic synthetic OHLCV frame (high >= close >= low)."""
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(np.arange(1, n + 1, dtype=float)) + rng.standard_normal(n).cumsum() * 0.5
    high = close + np.abs(rng.standard_normal(n)) * 0.5 + 0.1
    low = close - np.abs(rng.standard_normal(n)) * 0.5 - 0.1
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = 1000.0 + np.abs(rng.standard_normal(n)) * 100.0
    amount = volume * close
    return pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    )


INDICATOR_CONFIG = IndicatorConfig(
    enabled=[
        IndicatorSpec(name="ma", params={"window": 5}),
        IndicatorSpec(name="ma", params={"window": 20}),
        IndicatorSpec(name="rsi", params={"window": 14}),
        IndicatorSpec(name="macd", params={}),
        IndicatorSpec(name="kdj", params={}),
        IndicatorSpec(name="boll", params={"window": 20, "num_std": 2.0}),
        IndicatorSpec(name="vol_ma", params={"window": 5}),
    ]
)

FACTOR_CONFIG = FactorConfig(
    enabled=[
        FactorSpec(name="ma_distance", params={"window": 20}),
        FactorSpec(name="ma_cross", params={"fast": 5, "slow": 20}),
        FactorSpec(name="rsi_signal", params={"window": 14, "lower": 30, "upper": 70}),
        FactorSpec(name="macd_cross", params={}),
        FactorSpec(name="kdj_cross", params={}),
        FactorSpec(name="vol_ratio", params={"window": 5}),
        FactorSpec(name="boll_position", params={"window": 20}),
        FactorSpec(name="momentum", params={"window": 5}),
    ]
)

STRATEGY_CONFIG = StrategyConfig(
    enabled=[
        StrategySpec(
            name="weighted_momentum",
            type="weighted",
            params={
                "weights": [
                    {"factor": "ma_dist_20", "weight": 0.15, "clip": [-0.15, 0.15]},
                    {"factor": "ma_cross_5_20", "weight": 0.20},
                    {"factor": "rsi_signal_14", "weight": 0.15},
                    {"factor": "macd_cross", "weight": 0.20},
                    {"factor": "kdj_cross", "weight": 0.15},
                    {"factor": "vol_ratio_5", "weight": 0.05, "clip": [0.5, 2.5]},
                    {"factor": "boll_pos_20", "weight": 0.05},
                    {"factor": "mom_5", "weight": 0.05, "clip": [-0.1, 0.1]},
                ],
                "buy_threshold": 0.30,
                "sell_threshold": -0.30,
            },
        ),
        StrategySpec(
            name="golden_cross_rule",
            type="rule",
            params={
                "combine": "all",
                "conditions": [
                    {"factor": "ma_cross_5_20", "op": ">", "value": 0},
                    {"factor": "macd_cross", "op": ">", "value": 0},
                    {"factor": "rsi_signal_14", "op": "<", "value": 70},
                ],
            },
        ),
    ]
)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_available_contains_core_strategies() -> None:
    names = available()
    assert "weighted" in names
    assert "rule" in names


def test_build_unknown_raises() -> None:
    with pytest.raises(ConfigError):
        build("does_not_exist")


def test_signaltype_coerce_and_position() -> None:
    assert SignalType.coerce(1) is SignalType.LONG
    assert SignalType.coerce("short") is SignalType.SHORT
    assert SignalType.coerce("FLAT") is SignalType.FLAT
    assert SignalType.coerce(SignalType.LONG) is SignalType.LONG
    assert to_position(SignalType.LONG) == 1.0
    assert to_position(SignalType.FLAT) == 0.0
    assert to_position(SignalType.SHORT) == -1.0
    assert SignalType.LONG.value == 1
    assert SignalType.SHORT.value == -1


# --------------------------------------------------------------------------- #
# Weighted strategy: correctness + clipping
# --------------------------------------------------------------------------- #
def test_weighted_score_and_signal() -> None:
    df = pd.DataFrame({"ma_cross_5_20": [1.0, -1.0, 0.0], "macd_cross": [1.0, 1.0, 0.0]})
    strat = build(
        "weighted",
        {
            "weights": [
                {"factor": "ma_cross_5_20", "weight": 1.0},
                {"factor": "macd_cross", "weight": 1.0},
            ],
            "buy_threshold": 0.30,
            "sell_threshold": -0.30,
        },
        "wm",
    )
    out = strat.compute(df)
    assert out["score_wm"].tolist() == pytest.approx([1.0, 0.0, 0.0])
    assert out["signal_wm"].tolist() == [1, 0, 0]


def test_weighted_clip_normalises() -> None:
    df = pd.DataFrame({"mom_5": [0.2, -0.2]})
    strat = build(
        "weighted",
        {"weights": [{"factor": "mom_5", "weight": 1.0, "clip": [-0.1, 0.1]}]},
        "wm",
    )
    out = strat.compute(df)
    assert out["score_wm"].tolist() == pytest.approx([1.0, -1.0])


def test_weighted_empty_weights_raises() -> None:
    with pytest.raises(ConfigError):
        build("weighted", {"weights": []}, "wm").compute(pd.DataFrame({"close": [1.0]}))


def test_rule_all_and_any() -> None:
    # distinct columns so AND vs OR are distinguishable
    df = pd.DataFrame({"ma_cross_5_20": [1.0, -1.0, 1.0], "macd_cross": [-1.0, 1.0, 1.0]})
    alls = build(
        "rule",
        {
            "combine": "all",
            "conditions": [
                {"factor": "ma_cross_5_20", "op": ">", "value": 0},
                {"factor": "macd_cross", "op": ">", "value": 0},
            ],
        },
        "r",
    ).compute(df)
    assert alls["signal_r"].tolist() == [0, 0, 1]  # only row 2 has both > 0

    anys = build(
        "rule",
        {
            "combine": "any",
            "conditions": [
                {"factor": "ma_cross_5_20", "op": ">", "value": 0},
                {"factor": "macd_cross", "op": ">", "value": 0},
            ],
        },
        "r2",
    ).compute(df)
    assert anys["signal_r2"].tolist() == [1, 1, 1]  # every row has one > 0


def test_rule_operators() -> None:
    df = pd.DataFrame({"x": [5.0, 10.0, 15.0]})
    cases = [
        (">=", 10.0, [0, 1, 1]),
        ("<", 10.0, [1, 0, 0]),
        ("==", 10.0, [0, 1, 0]),
        ("!=", 10.0, [1, 0, 1]),
    ]
    for op, val, expected in cases:
        out = build(
            "rule",
            {"combine": "all", "conditions": [{"factor": "x", "op": op, "value": val}]},
            "r",
        ).compute(df)
        assert out["signal_r"].tolist() == expected, op


def test_rule_empty_conditions_raises() -> None:
    with pytest.raises(ConfigError):
        build("rule", {"conditions": []}, "r").compute(pd.DataFrame({"close": [1.0]}))


def test_rule_bad_combine_raises() -> None:
    with pytest.raises(ConfigError):
        build(
            "rule",
            {"combine": "maybe", "conditions": [{"factor": "x", "op": ">", "value": 0}]},
            "r",
        ).compute(pd.DataFrame({"x": [1.0]}))


def test_rule_bad_operator_raises() -> None:
    with pytest.raises(ConfigError):
        build(
            "rule",
            {"combine": "all", "conditions": [{"factor": "x", "op": "~", "value": 0}]},
            "r",
        ).compute(pd.DataFrame({"x": [1.0]}))


def test_weighted_missing_factor_raises() -> None:
    df = pd.DataFrame({"close": [10.0]})
    with pytest.raises(DataError):
        build("weighted", {"weights": [{"factor": "ma_dist_20", "weight": 1.0}]}, "wm").compute(df)


def test_rule_missing_factor_raises() -> None:
    df = pd.DataFrame({"close": [10.0]})
    with pytest.raises(DataError):
        build(
            "rule",
            {"combine": "all", "conditions": [{"factor": "nope", "op": ">", "value": 0}]},
            "r",
        ).compute(df)


def test_portfolio_positions() -> None:
    pf = Portfolio()
    df = pd.DataFrame({"signal": [1, 0, -1, "long", None]})
    assert pf.positions(df).tolist() == [1.0, 0.0, -1.0, 1.0, 0.0]


def test_portfolio_missing_signal_col_raises() -> None:
    with pytest.raises(ValueError):
        Portfolio().positions(pd.DataFrame({"close": [1.0]}))


def test_portfolio_mark_to_market() -> None:
    pf = Portfolio(initial_cash=1_000_000.0)
    df = pd.DataFrame({"close": [100.0, 110.0, 121.0]})
    out = pf.mark_to_market(df.assign(signal=[1, 1, 1]))
    assert out["equity"].iloc[0] == pytest.approx(1_000_000.0)
    assert out["equity"].iloc[2] == pytest.approx(1_200_000.0)


def test_portfolio_no_lookahead() -> None:
    pf = Portfolio()
    df = pd.DataFrame({"close": [100.0, 110.0, 121.0]})
    base = pf.mark_to_market(df.assign(signal=[0, 0, 0]))
    changed = pf.mark_to_market(df.assign(signal=[0, 0, 1]))
    pd.testing.assert_series_equal(base["equity"], changed["equity"])


# --------------------------------------------------------------------------- #
# Engine orchestration
# --------------------------------------------------------------------------- #
def test_engine_from_config_names() -> None:
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, STRATEGY_CONFIG)
    assert engine.names == ["weighted_momentum", "golden_cross_rule"]


def test_engine_compute_adds_signal_columns() -> None:
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, STRATEGY_CONFIG)
    out = engine.compute(_make_df(30))
    for col in (
        "score_weighted_momentum",
        "signal_weighted_momentum",
        "score_golden_cross_rule",
        "signal_golden_cross_rule",
    ):
        assert col in out.columns


def test_engine_groups_by_code() -> None:
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, STRATEGY_CONFIG)
    a = _make_df(20).assign(code="A")
    b = _make_df(20).assign(code="B")
    out = engine.compute(pd.concat([a, b], ignore_index=True))
    assert set(out["code"]) == {"A", "B"}
    assert "signal_weighted_momentum" in out.columns


def test_engine_idempotent() -> None:
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, STRATEGY_CONFIG)
    out1 = engine.compute(_make_df(25))
    out2 = engine.compute(_make_df(25))
    pd.testing.assert_frame_equal(out1, out2)


def test_engine_missing_factor_raises() -> None:
    # At the engine level, a strategy that references a factor column the factor
    # layer never produced must surface as DataError during compute (not silently
    # yield NaNs).
    bad = StrategyConfig(
        enabled=[
            StrategySpec(
                name="bad",
                type="weighted",
                params={"weights": [{"factor": "does_not_exist", "weight": 1.0}]},
            )
        ]
    )
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, bad)
    with pytest.raises(DataError):
        engine.compute(_make_df(20))


# --------------------------------------------------------------------------- #
# No future-function leakage (engine-level invariant)
# --------------------------------------------------------------------------- #
def test_engine_no_future_leak() -> None:
    engine = StrategyEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG, STRATEGY_CONFIG)
    raw = _make_df(40)
    full = engine.compute(raw.copy())
    signal_cols = [c for c in full.columns if c.startswith("signal_")]
    for t in range(10, len(raw)):
        trunc = engine.compute(raw.iloc[: t + 1].copy())
        for col in signal_cols:
            a = int(full[col].iloc[t]) if pd.notna(full[col].iloc[t]) else None
            b = int(trunc[col].iloc[-1]) if pd.notna(trunc[col].iloc[-1]) else None
            assert a == b, f"{col} leaked at t={t}"


# --------------------------------------------------------------------------- #
# Config parsing from settings.yaml
# --------------------------------------------------------------------------- #
def test_settings_yaml_strategies_load() -> None:
    from core.config import get_config

    cfg = get_config()
    names = {s.name for s in cfg.strategies.enabled}
    assert "weighted_momentum" in names
    assert "golden_cross_rule" in names


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def test_cli_strategies_list() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["strategies", "--list"])
    assert res.exit_code == 0, res.stdout
    assert "weighted" in res.stdout
    assert "rule" in res.stdout
    assert "weighted_momentum" in res.stdout


def test_cli_strategies_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DM:
        def get_daily(self, code, start_date=None, end_date=None):
            return _make_df(25)

    monkeypatch.setattr("main.DataManager", _DM)
    runner = CliRunner()
    res = runner.invoke(app, ["strategies", "600000"])
    assert res.exit_code == 0, res.stdout
    assert "signal_weighted_momentum" in res.stdout
    assert "signal_golden_cross_rule" in res.stdout
