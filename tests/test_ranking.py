"""Tests for the Sprint 3.3 cross-strategy ranking report + BatchResult bridge."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from research.batch import BatchResult, StrategyBatchOutcome
from research.ranking import RankingReport, build_score_inputs
from research.scorecard import Scorecard


def _outcome(
    name: str,
    display: str,
    oos: Mapping[str, float | None],
    is_m: Mapping[str, float | None],
    category: str = "trend",
    engine: str = "event",
    fidelity: str = "daily_full",
) -> StrategyBatchOutcome:
    return StrategyBatchOutcome(
        name=name,
        display_name=display,
        run_id=f"exp_{name}",
        category=category,
        engine=engine,
        data_fidelity=fidelity,
        is_metrics=dict(is_m),
        oos_metrics=dict(oos),
    )


def _batch() -> BatchResult:
    alpha_oos = {
        "total_return": 0.40,
        "cagr": 0.20,
        "win_rate": 0.60,
        "max_drawdown": -0.10,
        "profit_factor": 2.0,
        "sharpe": 1.2,
        "avg_holding_days": 5.0,
        "max_consecutive_losses": 2.0,
    }
    beta_oos = {
        "total_return": 0.20,
        "cagr": 0.10,
        "win_rate": 0.50,
        "max_drawdown": -0.20,
        "profit_factor": 1.5,
        "sharpe": 0.8,
        "avg_holding_days": 10.0,
        "max_consecutive_losses": 4.0,
    }
    return BatchResult(
        config_name="batch_test",
        outcomes=[
            # alpha dominates beta -> rank 1; low OOS decay (IS==OOS sharpe).
            _outcome("alpha", "龙头首阴", alpha_oos, {"sharpe": 1.2}),
            # beta: IS sharpe 2.0 vs OOS 0.8 -> decay 0.6 -> 高.
            _outcome("beta", "首板", beta_oos, {"sharpe": 2.0}),
        ],
    )


def test_build_score_inputs_bridges_oos() -> None:
    inputs = build_score_inputs(_batch())
    assert len(inputs) == 2
    by = {i.name: i for i in inputs}
    alpha = by["alpha"]
    # Scored metrics are the OOS set; IS/OOS carried for the E3 penalty.
    assert alpha.metrics["total_return"] == pytest.approx(0.40)
    assert alpha.is_metrics is not None
    assert alpha.oos_metrics is not None
    assert alpha.is_metrics["sharpe"] == pytest.approx(1.2)
    assert alpha.oos_metrics["sharpe"] == pytest.approx(1.2)


def test_build_score_inputs_drops_none() -> None:
    batch = BatchResult(
        config_name="x",
        outcomes=[_outcome("z", "Z", {"total_return": 0.1, "sharpe": None}, {"sharpe": 1.0})],
    )
    inputs = build_score_inputs(batch)
    assert "sharpe" not in inputs[0].metrics  # None dropped
    assert inputs[0].metrics["total_return"] == pytest.approx(0.1)


def test_ranking_orders_and_tags() -> None:
    report = RankingReport.from_batch(_batch())
    assert [r.name for r in report.rows] == ["alpha", "beta"]
    assert report.rows[0].rank == 1
    details = {d["name"]: d for d in report.details}
    assert details["alpha"]["rank"] == 1
    assert details["alpha"]["oos_decay_tag"] == "低"
    assert details["beta"]["oos_decay_tag"] == "高"
    assert details["alpha"]["category"] == "trend"
    assert details["alpha"]["display_name"] == "龙头首阴"


def test_ranking_markdown_contains_frozen_columns() -> None:
    md = RankingReport.from_batch(_batch()).to_markdown()
    assert "AROS 策略排名报告" in md
    assert "龙头首阴" in md and "首板" in md
    assert "低" in md and "高" in md
    # Frozen §4 columns present.
    for col in (
        "排名",
        "策略",
        "评分",
        "收益(OOS)",
        "胜率(OOS)",
        "回撤(OOS)",
        "持仓(天)",
        "OOS衰减",
    ):
        assert col in md


def test_ranking_json_roundtrip() -> None:
    payload = json.loads(RankingReport.from_batch(_batch()).to_json())
    assert payload["config_name"] == "batch_test"
    assert payload["n_strategies"] == 2
    assert len(payload["ranking"]) == 2
    assert payload["ranking"][0]["name"] == "alpha"
    assert payload["ranking"][0]["rank"] == 1


def test_ranking_html_self_contained() -> None:
    html = RankingReport.from_batch(_batch()).to_html()
    assert "<!doctype html>" in html
    assert "<table" in html
    assert "龙头首阴" in html and "首板" in html
    assert "tag-low" in html and "tag-high" in html


def test_single_window_no_decay_tag_low() -> None:
    """No walk-forward -> IS==OOS -> decay 0 -> 低 stability tag."""
    oos = {
        "total_return": 0.2,
        "cagr": 0.1,
        "win_rate": 0.5,
        "max_drawdown": -0.1,
        "profit_factor": 1.5,
        "sharpe": 1.0,
        "avg_holding_days": 5.0,
        "max_consecutive_losses": 2.0,
    }
    batch = BatchResult(
        config_name="full",
        outcomes=[_outcome("solo", "单策略", oos, dict(oos))],
    )
    report = RankingReport.from_batch(batch)
    assert report.details[0]["oos_decay"] == pytest.approx(0.0)
    assert report.details[0]["oos_decay_tag"] == "低"


def test_ranking_accepts_configured_scorecard() -> None:
    """A config-driven Scorecard (E5) flows through the ranking unchanged."""
    sc = Scorecard(weights={"sharpe": 1.0})
    report = RankingReport.from_batch(_batch(), scorecard=sc)
    # With only sharpe weighted, the higher-OOS-sharpe strategy ranks first.
    assert report.rows[0].name == "alpha"
