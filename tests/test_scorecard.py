"""Tests for the AROS Strategy Score scorecard (Sprint 3.3).

Hand-anchored: the expected scores are worked out by hand from the §4
min-max-normalise + weighted-sum algorithm so the test catches any regression
in the scoring math, the reverse-indicator direction, or the E3 OOS-decay
penalty.
"""

from __future__ import annotations

import pytest

from research.scorecard import Scorecard, ScoreInput


def _metrics(
    *,
    total_return: float = 0.1,
    cagr: float = 0.1,
    win_rate: float = 0.5,
    max_drawdown: float = -0.1,
    profit_factor: float = 1.5,
    sharpe: float = 1.0,
    avg_holding_days: float = 5.0,
    max_consecutive_losses: float = 2.0,
) -> dict[str, float]:
    return {
        "total_return": total_return,
        "cagr": cagr,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "avg_holding_days": avg_holding_days,
        "max_consecutive_losses": max_consecutive_losses,
    }


def test_score_perfect_separation_anchored() -> None:
    """A strictly dominates B on every dimension -> A=100, B=0 (hand-checked)."""
    a = _metrics(
        total_return=0.50,
        cagr=0.20,
        win_rate=0.60,
        max_drawdown=-0.10,
        profit_factor=2.0,
        sharpe=1.5,
        avg_holding_days=5.0,
        max_consecutive_losses=2.0,
    )
    b = _metrics(
        total_return=0.30,
        cagr=0.10,
        win_rate=0.50,
        max_drawdown=-0.20,
        profit_factor=1.5,
        sharpe=1.0,
        avg_holding_days=10.0,
        max_consecutive_losses=4.0,
    )
    rows = Scorecard().score([ScoreInput(name="A", metrics=a), ScoreInput(name="B", metrics=b)])
    by = {r.name: r for r in rows}
    assert by["A"].score == pytest.approx(100.0)
    assert by["B"].score == pytest.approx(0.0)
    assert by["A"].rank == 1
    assert by["B"].rank == 2


def test_score_mixed_directions_anchored() -> None:
    """P beats Q on return, Q beats P on risk -> hand-anchored 40 vs 60."""
    p = _metrics(
        total_return=0.60,
        cagr=0.25,
        win_rate=0.45,
        max_drawdown=-0.30,
        profit_factor=1.2,
        sharpe=0.8,
        avg_holding_days=4.0,
        max_consecutive_losses=1.0,
    )
    q = _metrics(
        total_return=0.30,
        cagr=0.10,
        win_rate=0.65,
        max_drawdown=-0.10,
        profit_factor=2.5,
        sharpe=1.8,
        avg_holding_days=12.0,
        max_consecutive_losses=5.0,
    )
    rows = Scorecard().score([ScoreInput(name="P", metrics=p), ScoreInput(name="Q", metrics=q)])
    by = {r.name: r for r in rows}
    # P wins return/holding, Q wins risk -> weighted by §4 weights.
    assert by["P"].score == pytest.approx(40.0)
    assert by["Q"].score == pytest.approx(60.0)
    assert by["Q"].rank == 1
    assert by["P"].rank == 2


def test_reverse_indicator_direction() -> None:
    """Smaller (better) drawdown must score higher on the drawdown dimension."""
    good = _metrics(max_drawdown=-0.05)  # abs 0.05
    bad = _metrics(max_drawdown=-0.25)  # abs 0.25
    rows = Scorecard().score(
        [ScoreInput(name="good", metrics=good), ScoreInput(name="bad", metrics=bad)]
    )
    by = {r.name: r for r in rows}
    # Only max_drawdown differs -> it alone decides the ordering.
    assert by["good"].components["max_drawdown"] == pytest.approx(1.0)
    assert by["bad"].components["max_drawdown"] == pytest.approx(0.0)
    assert by["good"].score > by["bad"].score


def test_oos_decay_penalty_discounts_sharpe() -> None:
    """When OOS Sharpe decays > threshold vs IS, the Sharpe dim is discounted."""
    base = dict(_metrics())
    x = ScoreInput(
        name="X",
        metrics=dict(base, sharpe=1.0),
        is_metrics=dict(base, sharpe=2.0),
        oos_metrics=dict(base, sharpe=1.0),  # decay = (2-1)/2 = 0.5 -> no penalty
    )
    y = ScoreInput(
        name="Y",
        metrics=dict(base, sharpe=1.0),
        is_metrics=dict(base, sharpe=2.0),
        oos_metrics=dict(base, sharpe=0.8),  # decay = (2-0.8)/2 = 0.6 -> penalty 0.8
    )
    rows = Scorecard().score([x, y])
    by = {r.name: r for r in rows}
    # Sharpe norm is 0.5 for both (equal scored value); only Y is penalised.
    assert by["X"].components["sharpe"] == pytest.approx(0.5)
    assert by["Y"].components["sharpe"] == pytest.approx(0.4)
    assert by["X"].score > by["Y"].score


def test_equal_inputs_neutral_score() -> None:
    """All strategies identical -> every dimension is neutral (0.5) -> score 50."""
    m = _metrics()
    rows = Scorecard().score([ScoreInput(name="A", metrics=m), ScoreInput(name="B", metrics=m)])
    for r in rows:
        assert r.score == pytest.approx(50.0)


def test_custom_weights_and_threshold() -> None:
    """Weights/threshold are configurable (E5) and change the penalty behaviour."""
    base = dict(_metrics())
    y = ScoreInput(
        name="Y",
        metrics=dict(base, sharpe=1.0),
        is_metrics=dict(base, sharpe=2.0),
        oos_metrics=dict(base, sharpe=0.8),  # decay 0.6
    )
    # Stricter threshold 0.4, decay 0.6 -> factor = 1-(0.6-0.4)*2 = 0.6.
    sc = Scorecard(weights={"sharpe": 1.0}, oos_decay_threshold=0.4)
    rows = sc.score([y])
    assert rows[0].components["sharpe"] == pytest.approx(0.3)
    # No penalty requested -> full component retained.
    sc2 = Scorecard(weights={"sharpe": 1.0}, oos_decay_penalty=False)
    rows2 = sc2.score([y])
    assert rows2[0].components["sharpe"] == pytest.approx(0.5)
