"""Tests for the Sprint 3.5 Market Regime Engine.

Covers the design's two required behaviours -- deterministic classification
rules and no look-ahead -- plus the dynamic strategy selection that consumes a
:class:`~research.batch.BatchResult`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.batch import BatchResult, StrategyBatchOutcome
from research.market_regime import (
    BEAR,
    BULL,
    EMOTION_COLD,
    EMOTION_HOT,
    NEUTRAL,
    REGIME_CATEGORY_FIT,
    REGIMES_5,
    MarketRegimeEngine,
    classify_market_regime,
)


def _price(daily_ret: float, n: int = 60, start: float = 100.0) -> pd.Series:
    """A benchmark close path with a constant daily return (no look-ahead)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    vals = start * np.power(1.0 + daily_ret, np.arange(n, dtype=float))
    return pd.Series(vals, index=idx, dtype="float64")


def _outcome(
    name: str,
    display: str,
    category: str,
    engine: str = "event",
    fidelity: str = "daily_approx",
    oos: dict[str, float] | None = None,
    breakdown: dict[str, dict[str, float]] | None = None,
) -> StrategyBatchOutcome:
    return StrategyBatchOutcome(
        name=name,
        display_name=display,
        run_id=f"exp::{name}",
        category=category,
        engine=engine,
        data_fidelity=fidelity,
        is_metrics=dict(oos or {}),
        oos_metrics=dict(oos or {}),
        regime_breakdown=dict(breakdown or {}),
    )


def _batch() -> BatchResult:
    outcomes = [
        _outcome(
            "ma_bull",
            "均线多头",
            "trend",
            oos={"total_return": 0.25, "win_rate": 0.55, "max_drawdown": -0.12},
            breakdown={
                "Bull": {"total_return": 0.30},
                "Bear": {"total_return": -0.10},
                "Neutral": {"total_return": 0.05},
            },
        ),
        _outcome(
            "sentiment_rebound",
            "情绪冰点修复",
            "emotion",
            oos={"total_return": 0.18, "win_rate": 0.50, "max_drawdown": -0.18},
            breakdown={
                "Bull": {"total_return": 0.10},
                "Bear": {"total_return": 0.20},
                "Neutral": {"total_return": 0.02},
            },
        ),
        _outcome(
            "strong_pullback",
            "强势回踩",
            "strong",
            oos={"total_return": 0.20, "win_rate": 0.52, "max_drawdown": -0.15},
            breakdown={
                "Bull": {"total_return": 0.15},
                "Bear": {"total_return": 0.05},
                "Neutral": {"total_return": 0.08},
            },
        ),
    ]
    return BatchResult(config_name="exp_main", outcomes=outcomes)


# --------------------------------------------------------------------------- #
# Classification rules (deterministic, explainable)
# --------------------------------------------------------------------------- #
def test_classification_deterministic() -> None:
    close = _price(0.004)
    a = classify_market_regime(close)
    b = classify_market_regime(close)
    assert a.equals(b)


def test_trend_uptrend_is_bull() -> None:
    close = _price(0.004)  # ~8% 20d return, calm vol -> Bull
    labels = classify_market_regime(close)
    assert labels.iloc[-1] == BULL


def test_trend_downtrend_is_bear() -> None:
    close = _price(-0.004)  # ~-8% 20d return -> Bear
    labels = classify_market_regime(close)
    assert labels.iloc[-1] == BEAR


def test_flat_is_neutral() -> None:
    close = _price(0.0)
    labels = classify_market_regime(close)
    assert labels.iloc[-1] == NEUTRAL


def test_no_emotion_without_breadth() -> None:
    """EmotionHot/Cold never fire when no breadth series is supplied."""
    close = _price(0.0)
    labels = classify_market_regime(close)
    assert set(labels.tolist()).issubset({BULL, NEUTRAL, BEAR})


def test_breadth_hot_is_emotion_hot() -> None:
    close = _price(0.0)  # flat -> would be Neutral on price alone
    # Strongly bullish net limit-up breadth everywhere -> frenzy.
    breadth = pd.Series(0.5, index=close.index, dtype="float64")
    labels = classify_market_regime(close, breadth=breadth)
    # After the vol warmup window the series must be EmotionHot.
    hot = labels[labels == EMOTION_HOT]
    assert not hot.empty
    assert labels.iloc[-1] == EMOTION_HOT


def test_breadth_cold_is_emotion_cold() -> None:
    close = _price(0.0)
    breadth = pd.Series(-0.5, index=close.index, dtype="float64")
    labels = classify_market_regime(close, breadth=breadth)
    assert labels.iloc[-1] == EMOTION_COLD


def test_no_look_ahead() -> None:
    """Changing a future value must not alter earlier regime labels."""
    close = _price(0.004)
    base = classify_market_regime(close)
    mutated = close.copy()
    # Spike only the very last point (the "future" relative to everything else).
    mutated.iloc[-1] = mutated.iloc[-1] * 5.0
    after = classify_market_regime(mutated)
    assert base.iloc[:-1].equals(after.iloc[:-1])


# --------------------------------------------------------------------------- #
# Dynamic strategy selection
# --------------------------------------------------------------------------- #
def test_category_fit_mapping() -> None:
    assert REGIME_CATEGORY_FIT[BULL] == ("trend", "strong")
    assert REGIME_CATEGORY_FIT[EMOTION_COLD] == ("emotion",)
    assert set(REGIMES_5) == {BULL, NEUTRAL, BEAR, EMOTION_HOT, EMOTION_COLD}


def test_select_bull_prefers_trend() -> None:
    engine = MarketRegimeEngine()
    sel = engine.select_strategy(BULL, _batch())
    # Bull candidates are trend/strong; ma_bull has the best Bull-bucket return.
    assert sel.strategy == "ma_bull"
    assert sel.regime_return == pytest.approx(0.30)


def test_select_bear_prefers_emotion_strong() -> None:
    engine = MarketRegimeEngine()
    sel = engine.select_strategy(BEAR, _batch())
    # Bear candidates are strong/emotion; sentiment_rebound has the best Bear return.
    assert sel.strategy == "sentiment_rebound"
    assert sel.regime_return == pytest.approx(0.20)


def test_select_deterministic() -> None:
    engine = MarketRegimeEngine()
    a = engine.select_strategy(NEUTRAL, _batch())
    b = engine.select_strategy(NEUTRAL, _batch())
    assert a.strategy == b.strategy


def test_recommendations_cover_all_regimes() -> None:
    engine = MarketRegimeEngine()
    recs = engine.recommendations(_batch())
    assert set(recs.keys()) == set(REGIMES_5)
    for r, sel in recs.items():
        assert sel.regime == r
        # Selected strategy must belong to the regime's explainable fit set.
        assert sel.category in REGIME_CATEGORY_FIT[r]


def test_emotion_selection_is_deterministic_and_valid() -> None:
    engine = MarketRegimeEngine()
    sel = engine.select_strategy(EMOTION_HOT, _batch())
    assert sel.strategy in {"sentiment_rebound", "strong_pullback"}
    again = engine.select_strategy(EMOTION_HOT, _batch())
    assert sel.strategy == again.strategy
