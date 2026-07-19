"""Tests for the Sprint 3.5 V1.0 Final Research Report.

Verifies the report composes every Phase 3 layer (library / ranking /
combination / regime engine) and yields a deterministic, self-contained
markdown / json / html deliverable with an explicit verdict.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.batch import BatchResult, StrategyBatchOutcome
from research.final_report import FinalReport, render_final_report
from research.market_regime import BULL, REGIMES_5


def _price(daily_ret: float, n: int = 60, start: float = 100.0) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    vals = start * np.power(1.0 + daily_ret, np.arange(n, dtype=float))
    return pd.Series(vals, index=idx, dtype="float64")


def _outcome(
    name: str,
    display: str,
    category: str,
    oos: dict[str, float] | None = None,
    breakdown: dict[str, dict[str, float]] | None = None,
) -> StrategyBatchOutcome:
    return StrategyBatchOutcome(
        name=name,
        display_name=display,
        run_id=f"exp::{name}",
        category=category,
        engine="event",
        data_fidelity="daily_approx",
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


def test_markdown_has_all_sections() -> None:
    report = FinalReport.from_batch(_batch())
    md = report.to_markdown()
    assert "AROS A 股短线策略研究报告 V1.0" in md
    assert "一、策略库概览" in md
    assert "二、AROS 策略排名" in md
    assert "三、组合方案" in md
    assert "四、市场状态引擎与动态选策略" in md
    assert "五、最终推荐结论" in md
    # Without market data the verdict falls back to the top AROS strategy.
    assert "最值得使用的是" in md


def test_json_round_trips() -> None:
    report = FinalReport.from_batch(_batch())
    payload = json.loads(report.to_json())
    assert payload["n_strategies"] == 3
    assert set(payload["recommendations"].keys()) == set(REGIMES_5)
    assert "weights" in payload["combination"]
    assert payload["top_single"] is not None


def test_with_market_data_infers_current_regime() -> None:
    close = _price(0.004)  # uptrend -> Bull
    report = FinalReport.from_batch(_batch(), benchmark_close=close)
    assert report.current_regime == BULL
    assert report.regime_counts.get(BULL, 0) > 0
    # The verdict explains the current-regime fit.
    assert "当前市场状态" in report.verdict_note
    assert report.verdict_strategy in {"ma_bull", "sentiment_rebound", "strong_pullback"}


def test_deterministic() -> None:
    a = FinalReport.from_batch(_batch()).to_dict()
    b = FinalReport.from_batch(_batch()).to_dict()
    assert a == b


def test_html_self_contained() -> None:
    report = FinalReport.from_batch(_batch())
    html = report.to_html()
    assert "<!doctype html>" in html
    assert "verdict" in html
    assert "若明天开始做 A 股短线" in html


def test_render_entry_point() -> None:
    md = render_final_report(_batch())
    assert "AROS A 股短线策略研究报告 V1.0" in md
