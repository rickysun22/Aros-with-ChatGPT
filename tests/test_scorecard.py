"""Sprint 3.0 — Scorecard tests.

Anchors E1-E4 with a hand-computed 3-strategy example so the normalisation,
weighting, reverse-direction (max_drawdown), holding-experience composite, and
OOS-decay penalty are locked to known numbers.
"""

from __future__ import annotations

import pytest

from research.scorecard import Scorecard, ScoreInput

# Hand-computed anchor (see Phase 3 design §4):
#   dims: total_return, cagr, win_rate, max_drawdown(abs,down), profit_factor,
#         sharpe(up), holding_experience = avg(avg_holding_days, max_consecutive_losses)
#   weights: .20/.15/.20/.20/.10/.10/.05
_A = dict(
    total_return=0.50,
    cagr=0.20,
    win_rate=0.60,
    max_drawdown=-0.10,
    profit_factor=2.0,
    sharpe=1.5,
    avg_holding_days=5,
    max_consecutive_losses=3,
)
_B = dict(
    total_return=0.35,
    cagr=0.15,
    win_rate=0.55,
    max_drawdown=-0.15,
    profit_factor=1.8,
    sharpe=1.3,
    avg_holding_days=7,
    max_consecutive_losses=4,
)
_C = dict(
    total_return=0.20,
    cagr=0.10,
    win_rate=0.50,
    max_drawdown=-0.20,
    profit_factor=1.5,
    sharpe=1.0,
    avg_holding_days=10,
    max_consecutive_losses=6,
)

ITEMS = [
    ScoreInput(name="A", metrics=_A),
    ScoreInput(name="B", metrics=_B),
    ScoreInput(name="C", metrics=_C),
]


def test_score_anchors() -> None:
    rows = Scorecard().rank(ITEMS)
    by = {r.name: r for r in rows}
    # A is best on every dimension -> 100.0 ; C worst -> 0.0
    assert by["A"].score == 100.0
    assert by["C"].score == 0.0
    # B hand-computed: 0.526667 * 100 = 52.6667
    assert by["B"].score == pytest.approx(52.6667, abs=1e-3)
    # Ranking order A > B > C
    assert [r.name for r in rows] == ["A", "B", "C"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_reverse_direction_max_drawdown() -> None:
    rows = {r.name: r for r in Scorecard().score(ITEMS)}
    # Shallower drawdown (A, -0.10) must normalise higher than deeper (C, -0.20).
    assert rows["A"].components["max_drawdown"] > rows["C"].components["max_drawdown"]
    assert rows["A"].components["max_drawdown"] == 1.0
    assert rows["C"].components["max_drawdown"] == 0.0


def test_holding_experience_is_composite() -> None:
    rows = {r.name: r for r in Scorecard().score(ITEMS)}
    # A fewer holding days & fewer consecutive losses -> best holding experience.
    assert rows["A"].components["holding_experience"] == 1.0
    assert rows["C"].components["holding_experience"] == 0.0


def test_oos_decay_penalty_lowers_sharpe_dim() -> None:
    penalised = Scorecard().score(
        [
            ScoreInput(
                name="B",
                metrics=_B,
                is_metrics={"sharpe": 1.3},
                oos_metrics={"sharpe": 0.5},  # decay = (1.3-0.5)/1.3 ~= 0.615 > 0.5
            ),
            ScoreInput(name="A", metrics=_A),
            ScoreInput(name="C", metrics=_C),
        ]
    )
    clean = Scorecard().score(ITEMS)
    b_pen = next(r for r in penalised if r.name == "B")
    b_clean = next(r for r in clean if r.name == "B")
    assert b_pen.score < b_clean.score  # penalty applied
    # Sharpe component of B is discounted relative to its clean value.
    assert b_pen.components["sharpe"] < b_clean.components["sharpe"]


def test_empty_input() -> None:
    assert Scorecard().score([]) == []
