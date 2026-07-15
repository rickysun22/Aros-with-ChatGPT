"""ReportEngine - generate the daily A-share research report (Sprint 1.8).

Aggregates the upstream pipeline (indicators -> factors -> strategies ->
backtest -> ranking) into a single, human-readable daily report. The report
reuses RankingEngine for the cross-sectional Top-N and enriches each candidate
with its latest price snapshot (close, daily change, trade date) fetched from
the DataManager. It adds no new metric math and preserves the no-look-ahead
guarantee: the price snapshot for a code is taken at/before the same as_of
cross-section the ranking layer uses.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from core.config import (
    BacktestConfig,
    FactorConfig,
    IndicatorConfig,
    RankingConfig,
    ReportConfig,
    StrategyConfig,
)
from ranking.engine import RankingEngine

# Metrics surfaced per candidate in the report (the compact, decision-useful set).
BT_METRIC_KEYS = ("total_return", "max_drawdown", "sharpe", "benchmark_return")

logger = logging.getLogger(__name__)

SCORE_PREFIX = "score_"


@dataclass
class ReportRow:
    """One ranked candidate enriched with its latest price snapshot."""

    rank: int
    code: str
    composite_score: float
    scores: dict[str, float]
    close: float | None = None
    as_of_date: str | None = None
    daily_change_pct: float | None = None
    stale: bool | None = None
    # Backtest enrichment (Sprint 1.10): historical performance of the candidate
    # under the configured strategy, computed only over [start, as_of] so no
    # future data leaks into the report. None when backtest is disabled/empty.
    bt_total_return: float | None = None
    bt_max_drawdown: float | None = None
    bt_sharpe: float | None = None
    bt_benchmark_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyReport:
    """The full daily research report (metadata + ranked rows)."""

    generated_at: str
    as_of: str
    universe_size: int
    source: str
    rows: list[ReportRow] = field(default_factory=list)
    backtest_included: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "as_of": self.as_of,
            "universe_size": self.universe_size,
            "source": self.source,
            "backtest_included": self.backtest_included,
            "rows": [r.to_dict() for r in self.rows],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self, include_detail: bool = True) -> str:
        lines: list[str] = []
        lines.append("# AROS 每日研究日报")
        lines.append("")
        lines.append(f"- 生成时间: {self.generated_at}")
        lines.append(f"- 截面日期: {self.as_of}")
        lines.append(f"- 候选池: {self.universe_size} 只")
        lines.append(f"- 数据来源: {self.source}")
        if self.backtest_included:
            lines.append("- 回测: 已附每个候选的历史表现（策略 signal，区间 [start, as_of]）")
        lines.append("")
        if not self.rows:
            lines.append("> 无候选标的（无数据或无打分）。")
            return "\n".join(lines)

        score_names = list(self.rows[0].scores.keys())
        lines.append("## 一、Top 候选排序")
        lines.append("")
        header = ["排名", "代码", "综合分"]
        header += [f"score_{n}" for n in score_names]
        header += ["最新价", "日涨跌%", "数据日期", "新鲜"]
        if self.backtest_included:
            header += ["回测收益%", "最大回撤%", "Sharpe", "基准%"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")

        def _bt(v: float | None, pct: bool) -> str:
            if v is None:
                return "-"
            return f"{v * 100:+.2f}" if pct else f"{v:.2f}"

        for r in self.rows:
            sc = " | ".join(f"{r.scores[n]:.4f}" for n in score_names)
            chg = f"{r.daily_change_pct:+.2f}" if r.daily_change_pct is not None else "-"
            fresh = "-" if r.stale is None else ("新鲜" if not r.stale else "滞后")
            row = [
                str(r.rank),
                r.code,
                f"{r.composite_score:.4f}",
                sc,
                f"{r.close:.2f}" if r.close is not None else "-",
                chg,
                r.as_of_date or "-",
                fresh,
            ]
            if self.backtest_included:
                row += [
                    _bt(r.bt_total_return, True),
                    _bt(r.bt_max_drawdown, True),
                    _bt(r.bt_sharpe, False),
                    _bt(r.bt_benchmark_return, True),
                ]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        if include_detail:
            lines.append("## 二、候选明细")
            lines.append("")
            for r in self.rows:
                lines.append(f"### #{r.rank} {r.code}")
                lines.append("")
                lines.append(f"- 综合分: {r.composite_score:.4f}")
                for n in score_names:
                    lines.append(f"- {n}: {r.scores[n]:.4f}")
                if r.close is not None:
                    chg = f"{r.daily_change_pct:+.2f}%" if r.daily_change_pct is not None else "n/a"
                    lines.append(f"- 最新价: {r.close:.2f}（{r.as_of_date}），日涨跌 {chg}")
                    if r.stale is not None:
                        lines.append(f"- 数据新鲜度: {'新鲜' if not r.stale else '滞后'}")
                if self.backtest_included:
                    lines.append("- 历史回测（策略 signal，区间 [start, as_of]）:")
                    lines.append(
                        f"  - 收益 {_bt(r.bt_total_return, True)}% / "
                        f"最大回撤 {_bt(r.bt_max_drawdown, True)}% / "
                        f"Sharpe {_bt(r.bt_sharpe, False)} / "
                        f"基准(买入持有) {_bt(r.bt_benchmark_return, True)}%"
                    )
                lines.append("")
        return "\n".join(lines)

    def to_html(self, include_detail: bool = True) -> str:
        """Render a self-contained HTML report (inline CSS + SVG bar chart).

        No external JS/CSS dependencies, so it renders offline. Includes the same
        columns as the markdown table plus a horizontal bar chart of the composite
        scores; backtest columns are shown when ``backtest_included`` is True.
        """

        def esc(s: Any) -> str:
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # ---- SVG bar chart of composite scores ----
        chart_rows: list[str] = []
        if self.rows:
            scores = [r.composite_score for r in self.rows]
            lo, hi = min(scores), max(scores)
            span = (hi - lo) or 1.0
            chart_w = 560.0
            row_h = 26
            chart_h = row_h * len(self.rows)
            for i, r in enumerate(self.rows):
                y = i * row_h + 4
                shifted = (r.composite_score - lo) / span  # 0..1
                bw = max(2.0, shifted * chart_w)
                label = esc(r.code)
                val = f"{r.composite_score:.4f}"
                chart_rows.append(
                    f'<text x="0" y="{y + 16}" class="bl">{label}</text>'
                    f'<rect x="70" y="{y + 4}" width="{bw:.1f}" height="16" rx="3" '
                    f'class="bar"/>'
                    f'<text x="{70 + bw + 6:.1f}" y="{y + 16}" class="bv">{val}</text>'
                )
            chart_svg = (
                f'<svg width="{70 + chart_w + 80:.0f}" height="{chart_h + 8}" '
                f'class="chart" role="img" aria-label="composite score ranking">'
                + "".join(chart_rows)
                + "</svg>"
            )
        else:
            chart_svg = '<p class="muted">无候选标的（无数据或无打分）。</p>'

        # ---- table ----
        score_names = list(self.rows[0].scores.keys()) if self.rows else []
        head = ["排名", "代码", "综合分"] + [f"score_{n}" for n in score_names]
        head += ["最新价", "日涨跌%", "数据日期", "新鲜"]
        if self.backtest_included:
            head += ["回测收益%", "最大回撤%", "Sharpe", "基准%"]

        def _bt(v: float | None, pct: bool) -> str:
            if v is None:
                return "-"
            return f"{v * 100:+.2f}" if pct else f"{v:.2f}"

        body_rows: list[str] = []
        for r in self.rows:
            chg = f"{r.daily_change_pct:+.2f}" if r.daily_change_pct is not None else "-"
            fresh = "-" if r.stale is None else ("新鲜" if not r.stale else "滞后")
            cells = [
                str(r.rank),
                esc(r.code),
                f"{r.composite_score:.4f}",
                *[f"{r.scores[n]:.4f}" for n in score_names],
                f"{r.close:.2f}" if r.close is not None else "-",
                chg,
                r.as_of_date or "-",
                fresh,
            ]
            if self.backtest_included:
                cells += [
                    _bt(r.bt_total_return, True),
                    _bt(r.bt_max_drawdown, True),
                    _bt(r.bt_sharpe, False),
                    _bt(r.bt_benchmark_return, True),
                ]
            body_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")

        bt_banner = (
            '<p class="muted">回测：已附每个候选的历史表现（策略 signal，区间 [start, as_of]）</p>'
            if self.backtest_included
            else ""
        )

        details: list[str] = []
        if include_detail and self.rows:
            for r in self.rows:
                parts = [f"<li>综合分: {r.composite_score:.4f}</li>"]
                parts += [f"<li>{n}: {r.scores[n]:.4f}</li>" for n in score_names]
                if r.close is not None:
                    chg = f"{r.daily_change_pct:+.2f}%" if r.daily_change_pct is not None else "n/a"
                    parts.append(
                        f"<li>最新价: {r.close:.2f}（{esc(r.as_of_date or '-')}），"
                        f"日涨跌 {chg}</li>"
                    )
                    if r.stale is not None:
                        parts.append(f"<li>数据新鲜度: {'新鲜' if not r.stale else '滞后'}</li>")
                if self.backtest_included:
                    parts.append(
                        "<li>历史回测: 收益 "
                        f"{_bt(r.bt_total_return, True)}% / "
                        f"最大回撤 {_bt(r.bt_max_drawdown, True)}% / "
                        f"Sharpe {_bt(r.bt_sharpe, False)} / "
                        f"基准 {_bt(r.bt_benchmark_return, True)}%</li>"
                    )
                details.append(
                    f'<div class="card"><h3>#{r.rank} {esc(r.code)}</h3><ul>'
                    + "".join(parts)
                    + "</ul></div>"
                )

        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AROS 每日研究日报</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
   color:#1f2937;margin:0;padding:24px;background:#f7f8fa}}
 h1{{font-size:20px;margin:0 0 4px}}
 .meta{{color:#6b7280;font-size:13px;margin-bottom:16px}}
 .muted{{color:#9ca3af;font-size:13px}}
 .banner{{background:#eef2ff;border-left:3px solid #6366f1;padding:8px 12px;
   border-radius:4px;font-size:13px;color:#4338ca;margin-bottom:16px}}
 .chart{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;
   padding:12px;margin-bottom:20px}}
 .bl{{font-size:13px;fill:#374151}}
 .bv{{font-size:12px;fill:#6b7280}}
 .bar{{fill:#6366f1}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px;
   border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}}
 th,td{{padding:8px 10px;text-align:right;border-bottom:1px solid #f0f1f3}}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
 thead th{{background:#f3f4f6;color:#374151;font-weight:600}}
 tbody tr:hover{{background:#fafafa}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:20px}}
 .card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px}}
 .card h3{{margin:0 0 6px;font-size:14px}}
 .card ul{{margin:0;padding-left:18px;font-size:12px;color:#4b5563}}
</style></head><body>
<h1>AROS 每日研究日报</h1>
<div class="meta">生成时间: {esc(self.generated_at)} ｜ 截面日期: {esc(self.as_of)} ｜
候选池: {self.universe_size} 只 ｜ 数据来源: {esc(self.source)}</div>
{bt_banner}
<h2>一、Top 候选排序</h2>
{chart_svg}
<table><thead><tr>{"".join(f"<th>{esc(h)}</th>" for h in head)}</tr></thead>
<tbody>{"".join(body_rows)}</tbody></table>
{f'<h2>二、候选明细</h2><div class="cards">{"".join(details)}</div>' if details else ""}
</body></html>"""


class ReportEngine:
    """Build the daily report from the ranking layer + price snapshots (+ backtest)."""

    def __init__(
        self,
        ranking_engine: RankingEngine,
        config: ReportConfig,
        backtest_config: BacktestConfig | None = None,
        backtest_fn: Callable[[str, Any, Any, Any], dict | None] | None = None,
    ) -> None:
        self.ranking_engine = ranking_engine
        self.config = config
        self.backtest_config = backtest_config
        self._backtest_fn = backtest_fn
        self._bt_engine: Any = None
        self._bt_ind: IndicatorConfig | None = None
        self._bt_fac: FactorConfig | None = None
        self._bt_str: StrategyConfig | None = None

    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
        ranking: RankingConfig,
        report: ReportConfig,
        backtest: BacktestConfig | None = None,
    ) -> ReportEngine:
        re = RankingEngine.from_config(indicators, factors, strategies, ranking)
        eng = cls(re, report, backtest_config=backtest)
        eng._bt_ind = indicators
        eng._bt_fac = factors
        eng._bt_str = strategies
        return eng

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _source_of(data_manager: Any) -> str:
        cfg = getattr(data_manager, "config", None)
        data = getattr(cfg, "data", None) if cfg is not None else None
        if data is None:
            return "unknown"
        return f"{getattr(data, 'source', '?')} ({getattr(data, 'adjust', '?')})"

    def _price_snapshot(
        self,
        code: str,
        data_manager: Any,
        start_date: date | None,
        end_date: date | None,
    ) -> dict[str, Any]:
        """Return close / as_of_date / daily_change / stale for a code.

        Fetches bars at/before end_date so the daily change uses only past data
        (no look-ahead). end_date is already the as_of ceiling set by caller.
        """
        bars = data_manager.get_daily(code, start_date, end_date)
        if bars is None or bars.empty:
            return {
                "close": None,
                "as_of_date": None,
                "daily_change_pct": None,
                "stale": None,
            }
        last = bars.iloc[-1]
        as_of_date = str(last["date"])
        close = float(last["close"])
        daily_change_pct: float | None = None
        if len(bars) >= 2:
            prev = float(bars.iloc[-2]["close"])
            if prev:
                daily_change_pct = (close / prev - 1.0) * 100.0
        stale: bool | None = None
        if self.config.as_of:
            cut = pd.Timestamp(self.config.as_of) - pd.Timedelta(days=self.config.freshness_days)
            stale = pd.Timestamp(as_of_date) < cut
        return {
            "close": close,
            "as_of_date": as_of_date,
            "daily_change_pct": daily_change_pct,
            "stale": stale,
        }

    # ------------------------------------------------------------------ #
    # Backtest enrichment (Sprint 1.10)
    # ------------------------------------------------------------------ #
    def _backtest_enabled(self) -> bool:
        return self._backtest_fn is not None or self.backtest_config is not None

    def _get_bt_engine(self) -> Any:
        """Lazily build a BacktestEngine from the stored configs."""
        if self._bt_engine is None and self.backtest_config is not None:
            ind, fac, st = self._bt_ind, self._bt_fac, self._bt_str
            if ind is None or fac is None or st is None:
                return None
            from backtest.engine import BacktestEngine

            self._bt_engine = BacktestEngine.from_config(ind, fac, st, self.backtest_config)
        return self._bt_engine

    def _backtest_snapshot(
        self, code: str, data_manager: Any, start: Any, end: Any
    ) -> dict[str, float] | None:
        """Return the compact backtest metrics for a code, or None.

        The backtest window is [start, end] where ``end`` is the as_of ceiling,
        so the report never consumes data after the cross-section (no look-ahead).
        """
        if self._backtest_fn is not None:
            return self._backtest_fn(code, data_manager, start, end)
        engine = self._get_bt_engine()
        if engine is None:
            return None
        _df, metrics = engine.run_code(code, data_manager, start, end)
        if not metrics:
            return None
        return {
            "bt_total_return": metrics.get("total_return"),
            "bt_max_drawdown": metrics.get("max_drawdown"),
            "bt_sharpe": metrics.get("sharpe"),
            "bt_benchmark_return": metrics.get("benchmark_return"),
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def generate(
        self,
        codes: list[str],
        data_manager: Any,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DailyReport:
        rc = self.config
        # The report drives the ranking layer through its own top_n / as_of.
        self.ranking_engine.config = RankingConfig(
            top_n=rc.top_n,
            as_of=rc.as_of,
            dimensions=self.ranking_engine.config.dimensions,
        )
        # The price snapshot ceiling follows as_of when set (no look-ahead).
        snap_end = pd.Timestamp(rc.as_of).date() if rc.as_of else end_date
        bt_enabled = self._backtest_enabled()

        ranking, _scored = self.ranking_engine.rank_universe(
            list(codes), data_manager, start_date, end_date
        )
        source = self._source_of(data_manager)
        report = DailyReport(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            as_of=rc.as_of or "latest",
            universe_size=len(codes),
            source=source,
            backtest_included=bt_enabled,
        )
        if ranking.empty:
            logger.warning("report: no ranking produced for %d candidates", len(codes))
            return report

        score_names = [
            c[len(SCORE_PREFIX) :] for c in ranking.columns if c.startswith(SCORE_PREFIX)
        ]
        for _, row in ranking.iterrows():
            code = str(row["code"])
            snap = self._price_snapshot(code, data_manager, start_date, snap_end)
            bt = (
                self._backtest_snapshot(code, data_manager, start_date, snap_end)
                if bt_enabled
                else None
            )
            report.rows.append(
                ReportRow(
                    rank=int(row["rank"]),
                    code=code,
                    composite_score=float(row["composite_score"]),
                    scores={n: float(row[SCORE_PREFIX + n]) for n in score_names},
                    close=snap["close"],
                    as_of_date=snap["as_of_date"],
                    daily_change_pct=snap["daily_change_pct"],
                    stale=snap["stale"],
                    bt_total_return=bt["bt_total_return"] if bt else None,
                    bt_max_drawdown=bt["bt_max_drawdown"] if bt else None,
                    bt_sharpe=bt["bt_sharpe"] if bt else None,
                    bt_benchmark_return=bt["bt_benchmark_return"] if bt else None,
                )
            )
        return report
