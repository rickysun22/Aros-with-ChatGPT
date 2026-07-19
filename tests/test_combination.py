"""Tests for Sprint 3.4 — Strategy Combination (regime-conditioned weighting)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from core.config import CombinationConfig
from research.batch import BatchResult, StrategyBatchOutcome
from research.combination import (
    OSCILLATING,
    TRENDING,
    CombinationEngine,
    CombinedResult,
    env_for_regime,
)


def _outcome(
    name: str,
    display: str,
    category: str,
    oos: Mapping[str, float | None],
    *,
    engine: str = "event",
    fidelity: str = "daily_full",
    regime: Mapping[str, dict[str, float]] | None = None,
) -> StrategyBatchOutcome:
    return StrategyBatchOutcome(
        name=name,
        display_name=display,
        run_id=f"exp:{name}",
        category=category,
        engine=engine,
        data_fidelity=fidelity,
        is_metrics=dict(oos),
        oos_metrics=dict(oos),
        fold_metrics={"oos_agg": dict(oos)},
        regime_breakdown=dict(regime or {}),
    )


def _batch(*outcomes: StrategyBatchOutcome) -> BatchResult:
    return BatchResult(config_name="cfgX", outcomes=list(outcomes))


TREND_OOS = {
    "total_return": 0.40,
    "cagr": 0.35,
    "win_rate": 0.60,
    "max_drawdown": -0.15,
    "profit_factor": 1.8,
    "sharpe": 1.2,
    "sortino": 1.6,
    "avg_holding_days": 8.0,
    "max_consecutive_losses": 3.0,
}
EMO_OS = {
    "total_return": 0.20,
    "cagr": 0.18,
    "win_rate": 0.40,
    "max_drawdown": -0.25,
    "profit_factor": 1.2,
    "sharpe": 0.6,
    "sortino": 0.8,
    "avg_holding_days": 5.0,
    "max_consecutive_losses": 5.0,
}


def test_weights_normalize_per_env() -> None:
    """Every environment bucket's weights sum to 1.0 and respect the floor."""
    cfg = CombinationConfig(top_n=3, equal_weight_floor=0.1)
    batch = _batch(
        _outcome("a", "A", "trend", TREND_OOS),
        _outcome("b", "B", "emotion", EMO_OS),
        _outcome("c", "C", "strong", TREND_OOS),
    )
    res = CombinationEngine(config=cfg).combine(batch)
    for env in (TRENDING, OSCILLATING):
        w = res.weights[env]
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(v >= cfg.equal_weight_floor - 1e-9 for v in w.values())


def test_combined_metrics_reproducible() -> None:
    """Same inputs -> identical combined metrics (pure function)."""
    batch = _batch(
        _outcome("a", "A", "trend", TREND_OOS),
        _outcome("b", "B", "emotion", EMO_OS),
    )
    eng = CombinationEngine(config=CombinationConfig(top_n=3))
    r1 = eng.combine(batch)
    r2 = eng.combine(batch)
    assert r1.combined_metrics == r2.combined_metrics
    assert r1.weights == r2.weights


def test_top_n_respected() -> None:
    """Only the top-N strategies are combined."""
    cfg = CombinationConfig(top_n=2)
    batch = _batch(
        _outcome("a", "A", "trend", TREND_OOS),
        _outcome("b", "B", "emotion", EMO_OS),
        _outcome("c", "C", "strong", TREND_OOS),
    )
    res = CombinationEngine(config=cfg).combine(batch)
    assert len(res.selected) == 2


def test_category_bias_direction() -> None:
    """Trend category wins in trending env; emotion wins in oscillating env."""
    # No regime breakdown -> weights driven purely by category fit.
    batch = _batch(
        _outcome("trend_s", "Trend", "trend", TREND_OOS),
        _outcome("emo_s", "Emo", "emotion", EMO_OS),
    )
    res = CombinationEngine(config=CombinationConfig(top_n=3)).combine(batch)
    trend_w = res.weights[TRENDING]
    osc_w = res.weights[OSCILLATING]
    assert trend_w["trend_s"] > trend_w["emo_s"]
    assert osc_w["emo_s"] > osc_w["trend_s"]


def test_regime_performance_tilt() -> None:
    """A strategy that performed in Bull gets more weight in the trending bucket."""
    strong_bias = CombinationConfig(top_n=3, category_bias=0.5, perf_weight=2.0, perf_cap=0.30)
    a = _outcome(
        "a",
        "A",
        "trend",
        TREND_OOS,
        regime={"Bull": {"n_trades": 10.0, "mean_return": 0.05, "total_return": 0.50}},
    )
    b = _outcome("b", "B", "trend", TREND_OOS)  # same category, no regime data
    res = CombinationEngine(config=strong_bias).combine(_batch(a, b))
    assert res.weights[TRENDING]["a"] > res.weights[TRENDING]["b"]


def test_blended_metrics_hand_calc() -> None:
    """With equal weights, combined total_return / win_rate are the means."""
    cfg = CombinationConfig(top_n=2, category_bias=0.0, perf_weight=0.0)
    o1 = {"total_return": 0.40, "win_rate": 0.60, "max_drawdown": -0.15, "sharpe": 1.2}
    o2 = {"total_return": 0.20, "win_rate": 0.40, "max_drawdown": -0.25, "sharpe": 0.6}
    batch = _batch(
        _outcome("a", "A", "trend", o1),
        _outcome("b", "B", "emotion", o2),
    )
    res = CombinationEngine(config=cfg).combine(batch)
    m = res.combined_metrics[TRENDING]
    assert m["total_return"] == pytest.approx(0.30)
    assert m["win_rate"] == pytest.approx(0.50)
    # drawdown blends additively (portfolio drawdown proxy)
    assert m["max_drawdown"] == pytest.approx(-0.20)


def test_env_for_regime_mapping() -> None:
    """Bull/Bear -> trending; Neutral/Extreme -> oscillating."""
    assert env_for_regime("Bull") == TRENDING
    assert env_for_regime("Bear") == TRENDING
    assert env_for_regime("Neutral") == OSCILLATING
    assert env_for_regime("Extreme") == OSCILLATING


def test_combination_report_renders() -> None:
    """The markdown report carries both environment buckets."""
    batch = _batch(
        _outcome("a", "A", "trend", TREND_OOS),
        _outcome("b", "B", "emotion", EMO_OS),
    )
    res = CombinationEngine(config=CombinationConfig(top_n=3)).combine(batch)
    md = res.to_markdown()
    assert "趋势市" in md
    assert "震荡市" in md
    assert isinstance(res, CombinedResult)
    # JSON serialises (no pd.Series inside)
    assert "weights" in res.to_dict()
