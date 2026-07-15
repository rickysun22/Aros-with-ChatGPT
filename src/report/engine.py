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
