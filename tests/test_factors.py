"""Tests for the Sprint 1.4 Factor Engine.

Coverage mirrors the indicator suite:
* Pure-function correctness of each factor.
* *No future-function leakage*: a factor value at bar t computed on the full
  raw series (indicators + factor) must equal the value computed on only bars
  0..t. This is the automated guard for the project principle 禁止未来函数.
* Engine orchestration (indicators + factors, per-code grouping, idempotency).
* Configuration parsing, rejection of unknown factors, and missing-column errors.
* CLI smoke test (--list and compute).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from core.config import FactorConfig, FactorSpec, IndicatorConfig, IndicatorSpec
from core.exceptions import ConfigError, DataError
from factors import available, build
from factors.engine import FactorEngine
from indicators.engine import IndicatorEngine
from main import app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
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


# Indicator set required by the factors under test.
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

CORE_FACTORS = [s.name for s in FACTOR_CONFIG.enabled]

_ind_engine = IndicatorEngine.from_config(INDICATOR_CONFIG)


def _indicate(raw: pd.DataFrame) -> pd.DataFrame:
    """Run the indicator layer so factors have their input columns."""
    return _ind_engine.compute(raw.copy())


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_available_contains_core_factors() -> None:
    names = available()
    for name in CORE_FACTORS:
        assert name in names


# --------------------------------------------------------------------------- #
# Pure-function correctness
# --------------------------------------------------------------------------- #
def test_ma_distance_basic() -> None:
    df = pd.DataFrame({"close": [11.0, 10.0], "ma_20": [10.0, 10.0]})
    out = build("ma_distance", {"window": 20}).compute(df)
    # (11 - 10) / 10 * 100 == 10.0
    assert out["ma_dist_20"].iloc[0] == pytest.approx(10.0)


def test_ma_cross_signs() -> None:
    df = pd.DataFrame({"ma_5": [12.0, 8.0, 10.0], "ma_20": [10.0, 10.0, 10.0]})
    out = build("ma_cross", {"fast": 5, "slow": 20}).compute(df)
    assert out["ma_cross_5_20"].tolist() == [1, -1, 0]


def test_rsi_signal_zones() -> None:
    df = pd.DataFrame({"rsi_14": [80.0, 20.0, 50.0]})
    out = build("rsi_signal", {"window": 14, "lower": 30, "upper": 70}).compute(df)
    assert out["rsi_signal_14"].tolist() == [1, -1, 0]


def test_macd_cross_signs() -> None:
    df = pd.DataFrame({"macd": [0.5, -0.5, 0.0], "macd_signal": [0.0, 0.0, 0.0]})
    out = build("macd_cross").compute(df)
    assert out["macd_cross"].tolist() == [1, -1, 0]


def test_kdj_cross_signs() -> None:
    df = pd.DataFrame({"kdj_k": [60.0, 40.0, 50.0], "kdj_d": [50.0, 50.0, 50.0]})
    out = build("kdj_cross").compute(df)
    assert out["kdj_cross"].tolist() == [1, -1, 0]


def test_vol_ratio_basic() -> None:
    df = pd.DataFrame({"volume": [2000.0, 1000.0], "vol_ma_5": [1000.0, 1000.0]})
    out = build("vol_ratio", {"window": 5}).compute(df)
    assert out["vol_ratio_5"].iloc[0] == pytest.approx(2.0)


def test_boll_position_clamped() -> None:
    # close exactly at the upper band -> position 1.0
    df = pd.DataFrame({"close": [15.0], "boll_lower_20": [10.0], "boll_upper_20": [15.0]})
    out = build("boll_position", {"window": 20}).compute(df)
    assert out["boll_pos_20"].iloc[0] == pytest.approx(1.0)


def test_momentum_basic() -> None:
    df = pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 14.0, 21.0]})
    out = build("momentum", {"window": 5}).compute(df)
    # 21 / 10 - 1 == 1.1
    assert out["mom_5"].iloc[-1] == pytest.approx(1.1)


def test_factor_missing_indicator_column_raises() -> None:
    df = pd.DataFrame({"close": [10.0]})  # no ma_20 column
    with pytest.raises(DataError):
        build("ma_distance", {"window": 20}).compute(df)


# --------------------------------------------------------------------------- #
# No future-function leakage (the key invariant)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spec", FACTOR_CONFIG.enabled, ids=lambda s: s.name)
def test_no_future_leak(spec: FactorSpec) -> None:
    factor = build(spec.name, spec.params)
    raw = _make_df(40)
    full = factor.compute(_indicate(raw.copy()))
    new_cols = [c for c in full.columns if c not in raw.columns]
    for t in range(10, len(raw)):
        trunc = factor.compute(_indicate(raw.iloc[: t + 1].copy()))
        for col in new_cols:
            a = full[col].iloc[t]
            b = trunc[col].iloc[-1]
            if pd.isna(a):
                assert pd.isna(b), f"{spec.name}.{col} leaked at t={t}"
            else:
                assert abs(float(a) - float(b)) < 1e-9, f"{spec.name}.{col} leaked at t={t}"


# --------------------------------------------------------------------------- #
# Engine orchestration
# --------------------------------------------------------------------------- #
def test_engine_from_config_names() -> None:
    engine = FactorEngine.from_config(
        INDICATOR_CONFIG,
        FactorConfig(enabled=[FactorSpec(name="ma_distance", params={"window": 20})]),
    )
    assert engine.names == ["ma_distance"]


def test_engine_compute_adds_factor_columns_and_is_idempotent() -> None:
    engine = FactorEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG)
    out = engine.compute(_make_df(30))
    for expected in (
        "ma_dist_20",
        "ma_cross_5_20",
        "rsi_signal_14",
        "macd_cross",
        "kdj_cross",
        "vol_ratio_5",
        "boll_pos_20",
        "mom_5",
    ):
        assert expected in out.columns
    out2 = engine.compute(_make_df(30))
    pd.testing.assert_frame_equal(out, out2)


class _StubDM:
    """Minimal DataManager stand-in for compute_code (no DB, no network)."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_daily(self, code: str, start_date=None, end_date=None) -> pd.DataFrame:
        return self._df


def test_engine_compute_code_uses_datamanager() -> None:
    engine = FactorEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG)
    out = engine.compute_code("600000", _StubDM(_make_df(20)))
    assert "ma_dist_20" in out.columns
    assert len(out) == 20


def test_engine_groups_by_code() -> None:
    engine = FactorEngine.from_config(INDICATOR_CONFIG, FACTOR_CONFIG)
    a = _make_df(20).assign(code="A")
    b = _make_df(20).assign(code="B")
    both = pd.concat([a, b], ignore_index=True)
    out = engine.compute(both)
    assert set(out["code"]) == {"A", "B"}
    assert "ma_dist_20" in out.columns


def test_engine_rejects_unknown_factor() -> None:
    with pytest.raises(ConfigError):
        build("does_not_exist")
    with pytest.raises(ConfigError):
        FactorEngine.from_config(INDICATOR_CONFIG, FactorConfig(enabled=[FactorSpec(name="nope")]))


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def test_cli_factors_list() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["factors", "--list"])
    assert res.exit_code == 0
    assert "ma_distance" in res.stdout
    assert "rsi_signal" in res.stdout


def test_cli_factors_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DM:
        def get_daily(self, code: str, start_date=None, end_date=None) -> pd.DataFrame:
            return _make_df(25)

    monkeypatch.setattr("main.DataManager", _DM)
    runner = CliRunner()
    res = runner.invoke(app, ["factors", "600000"])
    assert res.exit_code == 0
    assert "ma_dist_20" in res.stdout
