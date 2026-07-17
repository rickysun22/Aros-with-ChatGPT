"""Tests for the market-regime classifier (Sprint 3.2)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from research.regime import (
    BEAR,
    BULL,
    EXTREME,
    NEUTRAL,
    REGIMES,
    classify_regime,
)


def _series(values: Sequence[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(list(values), index=idx, dtype="float64")


def test_returns_regime_labels_aligned_to_index() -> None:
    s = _series([100, 101, 102, 103, 104])
    out = classify_regime(s)
    assert list(out.index) == list(s.index)
    assert set(out.tolist()).issubset(set(REGIMES))


def test_bull_when_strong_uptrend() -> None:
    # A steady 1%/day climb over >20 days -> Bull.
    vals = [100.0]
    for _ in range(40):
        vals.append(vals[-1] * 1.01)
    out = classify_regime(_series(vals))
    # After the 20-day warmup the series should be Bull.
    assert (out.iloc[25:] == BULL).all()


def test_bear_when_strong_downtrend() -> None:
    # A shallow ~0.3%/day slide: 20-day momentum < -5% (Bear) but drawdown stays
    # under the -15% Extreme threshold.
    vals = [100.0]
    for _ in range(40):
        vals.append(vals[-1] * 0.997)
    out = classify_regime(_series(vals))
    assert (out.iloc[25:] == BEAR).all()


def test_extreme_on_volatility_spike() -> None:
    rng = np.random.RandomState(0)
    base = 100 + np.cumsum(rng.randn(40) * 0.1)  # calm
    # Inject a violent tail so annualised vol breaches the extreme threshold.
    tail = base[30] * np.cumprod([1 + rng.randn() * 0.08 for _ in range(10)])
    vals = list(base[:30]) + list(tail)
    out = classify_regime(_series(vals))
    assert EXTREME in out.tolist()


def test_no_look_ahead_labels_use_only_past_data() -> None:
    # A crash only at the very end must not flip earlier labels to Extreme.
    vals = [100.0] * 30
    for _ in range(10):
        vals.append(vals[-1] * 1.01)  # calm bull
    crash = vals[-1]
    vals = vals + [crash * 0.7]  # single drop at the end
    out = classify_regime(_series(vals))
    # The last point may be Extreme, but the prior 30 calm points stay non-extreme.
    assert EXTREME not in out.iloc[:30].tolist()


def test_empty_series_returns_empty() -> None:
    out = classify_regime(pd.Series(dtype="float64"))
    assert out.empty


def test_neutral_default_before_warmup() -> None:
    # Fewer than the vol window of history -> Neutral (no premature label).
    out = classify_regime(_series([100, 101, 99, 102, 103]))
    assert (out == NEUTRAL).all()


@pytest.mark.parametrize("label", [BULL, NEUTRAL, BEAR, EXTREME])
def test_all_four_regimes_are_valid_constants(label: str) -> None:
    assert label in REGIMES
