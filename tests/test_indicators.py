"""Tests for the Sprint 1.3 Indicator Engine.

Coverage:
* Pure-function correctness of each indicator.
* *No future-function leakage*: an indicator value at bar t computed on the
  full series must equal the value computed on only bars 0..t. This is the
  automated guard for the project principle 禁止未来函数.
* Engine orchestration (config-driven, per-code grouping, idempotency).
* Configuration parsing and rejection of unknown indicators.
* CLI smoke test (--list and compute).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from core.config import IndicatorConfig, IndicatorSpec
from core.exceptions import ConfigError
from indicators import available, build
from indicators.engine import IndicatorEngine
from main import app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_df(n: int = 30) -> pd.DataFrame:
    """Deterministic synthetic OHLCV frame (high >= close >= low)."""
    rng = np.random.default_rng(42)
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


CORE_INDICATORS = ["ma", "ema", "rsi", "macd", "kdj", "boll", "vol_ma"]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_available_contains_core_indicators() -> None:
    names = available()
    for name in CORE_INDICATORS:
        assert name in names


# --------------------------------------------------------------------------- #
# Pure-function correctness
# --------------------------------------------------------------------------- #
def test_ma_rolling_mean() -> None:
    out = build("ma", {"window": 3}).compute(pd.DataFrame({"close": [1, 2, 3, 4, 5]}))
    ma = out["ma_3"].tolist()
    assert pd.isna(ma[0]) and pd.isna(ma[1])
    assert ma[2] == pytest.approx(2.0)
    assert ma[3] == pytest.approx(3.0)
    assert ma[4] == pytest.approx(4.0)


def test_rsi_monotone_prices() -> None:
    up = build("rsi", {"window": 3}).compute(pd.DataFrame({"close": [1, 2, 3, 4, 5]}))
    up_vals = up["rsi_3"].dropna().tolist()
    assert up_vals == pytest.approx([100.0] * len(up_vals))
    down = build("rsi", {"window": 3}).compute(pd.DataFrame({"close": [5, 4, 3, 2, 1]}))
    down_vals = down["rsi_3"].dropna().tolist()
    assert down_vals == pytest.approx([0.0] * len(down_vals))


def test_macd_flat_prices_zero() -> None:
    out = build("macd").compute(pd.DataFrame({"close": [10.0] * 12}))
    assert out["macd"].dropna().tolist() == pytest.approx([0.0] * 12)
    assert out["macd_signal"].dropna().tolist() == pytest.approx([0.0] * 12)
    assert out["macd_hist"].dropna().tolist() == pytest.approx([0.0] * 12)


def test_boll_band_ordering() -> None:
    out = build("boll", {"window": 3, "num_std": 2.0}).compute(
        pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    )
    valid = ~out["boll_mid_3"].isna()
    assert (out["boll_lower_3"][valid] <= out["boll_mid_3"][valid] + 1e-9).all()
    assert (out["boll_mid_3"][valid] <= out["boll_upper_3"][valid] + 1e-9).all()


def test_kdj_flat_prices_neutral() -> None:
    df = pd.DataFrame({"close": [10.0] * 20, "high": [10.0] * 20, "low": [10.0] * 20})
    out = build("kdj").compute(df)
    for col in ("kdj_k", "kdj_d", "kdj_j"):
        vals = out[col].dropna()
        assert vals.tolist() == pytest.approx([50.0] * len(vals), abs=1e-9)


def test_vol_ma_rolling_mean() -> None:
    out = build("vol_ma", {"window": 3}).compute(
        pd.DataFrame({"volume": [3.0, 3.0, 3.0, 3.0, 3.0]})
    )
    assert out["vol_ma_3"].dropna().tolist() == pytest.approx([3.0, 3.0, 3.0])


# --------------------------------------------------------------------------- #
# No future-function leakage (the key invariant)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", available())
def test_no_future_leak(name: str) -> None:
    ind = build(name)
    df = _make_df(40)
    full = ind.compute(df.copy())
    new_cols = [c for c in full.columns if c not in df.columns]
    for t in range(10, len(df)):
        trunc = ind.compute(df.iloc[: t + 1].copy())
        for col in new_cols:
            a = full[col].iloc[t]
            b = trunc[col].iloc[-1]
            if pd.isna(a):
                assert pd.isna(b), f"{name}.{col} leaked at t={t}"
            else:
                assert abs(float(a) - float(b)) < 1e-9, f"{name}.{col} leaked at t={t}"


# --------------------------------------------------------------------------- #
# Engine orchestration
# --------------------------------------------------------------------------- #
def test_engine_from_config_names() -> None:
    cfg = IndicatorConfig(
        enabled=[
            IndicatorSpec(name="ma", params={"window": 10}),
            IndicatorSpec(name="rsi"),
        ]
    )
    engine = IndicatorEngine.from_config(cfg)
    assert engine.names == ["ma", "rsi"]


def test_engine_compute_adds_columns_and_is_idempotent() -> None:
    cfg = IndicatorConfig(
        enabled=[
            IndicatorSpec(name="ma", params={"window": 5}),
            IndicatorSpec(name="rsi", params={"window": 14}),
        ]
    )
    engine = IndicatorEngine.from_config(cfg)
    out = engine.compute(_make_df(30))
    assert "ma_5" in out.columns
    assert "rsi_14" in out.columns
    out2 = engine.compute(_make_df(30))
    pd.testing.assert_frame_equal(out, out2)


class _StubDM:
    """Minimal DataManager stand-in for compute_code (no DB, no network)."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_daily(self, code: str, start_date=None, end_date=None) -> pd.DataFrame:
        return self._df


def test_engine_compute_code_uses_datamanager() -> None:
    cfg = IndicatorConfig(enabled=[IndicatorSpec(name="ma", params={"window": 5})])
    engine = IndicatorEngine.from_config(cfg)
    out = engine.compute_code("600000", _StubDM(_make_df(20)))
    assert "ma_5" in out.columns
    assert len(out) == 20


def test_engine_groups_by_code() -> None:
    cfg = IndicatorConfig(enabled=[IndicatorSpec(name="ma", params={"window": 5})])
    engine = IndicatorEngine.from_config(cfg)
    a = _make_df(20).assign(code="A")
    b = _make_df(20).assign(code="B")
    both = pd.concat([a, b], ignore_index=True)
    out = engine.compute(both)
    assert set(out["code"]) == {"A", "B"}
    assert "ma_5" in out.columns


def test_engine_rejects_unknown_indicator() -> None:
    with pytest.raises(ConfigError):
        build("does_not_exist")
    with pytest.raises(ConfigError):
        IndicatorEngine.from_config(IndicatorConfig(enabled=[IndicatorSpec(name="nope")]))


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def test_cli_indicators_list() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["indicators", "--list"])
    assert res.exit_code == 0
    assert "ma" in res.stdout
    assert "rsi" in res.stdout


def test_cli_indicators_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DM:
        def get_daily(self, code: str, start_date=None, end_date=None) -> pd.DataFrame:
            return _make_df(25)

    monkeypatch.setattr("main.DataManager", _DM)
    runner = CliRunner()
    res = runner.invoke(app, ["indicators", "600000"])
    assert res.exit_code == 0
    assert "ma_5" in res.stdout
