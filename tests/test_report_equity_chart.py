"""Tests for the equity / drawdown curve rendering added in Sprint 3.2.

The curves are built from the equity blob the runner already persists
(runner.record_equity), so the renderer must plot them for any experiment
that has equity stored -- no network or real data required here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research.report import ResearchReport  # noqa: E402


def _report_with_equity() -> ResearchReport:
    # A small rising-then-dipping equity series to exercise drawdown math.
    eq = {
        "2022-01-03": 1.00,
        "2022-01-04": 1.05,
        "2022-01-05": 1.12,
        "2022-01-06": 1.08,  # dip -> drawdown
        "2022-01-07": 1.15,
    }
    return ResearchReport(
        run_id="R-test",
        name="eq-test",
        strategy="dummy",
        start="2022-01-03",
        end="2022-01-07",
        benchmark="csi300",
        walk_forward=None,
        status="done",
        is_oos=False,
        windows=["full"],
        metrics={"full": {"total_return": 0.15, "sharpe": 1.2}},
        equity={"full": eq},
    )


def test_html_contains_equity_and_drawdown_svg() -> None:
    html = _report_with_equity().to_html()
    assert "净值曲线与回撤曲线" in html
    # one equity svg + one drawdown svg
    assert html.count("<svg") >= 2
    assert "equity full" in html
    assert "drawdown full" in html


def test_markdown_contains_max_drawdown_summary() -> None:
    md = _report_with_equity().to_markdown()
    assert "## 三、净值与回撤" in md
    assert "最大回撤" in md
    # 1.12 peak, dip to 1.08 -> drawdown ~ -3.6%
    assert "-3.6%" in md


def test_empty_equity_renders_without_charts() -> None:
    rep = _report_with_equity()
    rep.equity = {}
    html = rep.to_html()
    assert "<svg" not in html
    assert "净值曲线与回撤曲线" not in html
