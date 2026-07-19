"""V1.0 Final Research Report (Sprint 3.5).

Aggregates the whole Phase 3 pipeline into the single project deliverable
(design §9): the *AROS A 股短线策略研究报告 V1.0*. It composes:

  * the strategy library (10 research strategies, with category / universe /
    data-fidelity),
  * the AROS Strategy Score ranking (3.3),
  * the regime-conditioned combination (3.4), and
  * the 3.5 Market Regime Engine's per-regime strategy recommendations,

and concludes with an explicit, actionable answer to the project's success
question: *"若明天开始做 A 股短线，哪套（或哪组）策略最值得使用"*.

No new metric math -- the report only *presents* results the pipeline already
computed and persisted, so it is a pure function of its inputs and fully
reproducible. Rendering reuses the self-contained markdown / json / html style
of the other research reports (inline CSS, no external JS/CSS).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from research.batch import BatchResult
from research.combination import ENVS, TRENDING, CombinationEngine
from research.market_regime import (
    NEUTRAL,
    REGIME_LABELS,
    REGIMES_5,
    MarketRegimeEngine,
    Regime,
    _regime_counts,
)
from research.ranking import RankingReport
from research.scorecard import Scorecard
from research.strategy_library import get_strategy

_DATE_RANGE_DEFAULT = ("-", "-")


def _pct(v: float | None) -> str:
    if v is None:
        return "-"
    if v == 0:
        return "0.0%"
    return f"{v * 100:.1f}%"


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    if v == 0:
        return "0.0000"
    return f"{v:.4f}"


def _library_meta(batch: BatchResult) -> list[dict[str, Any]]:
    """Strategy-library rows: prefer the frozen spec, fall back to outcome fields."""
    out: list[dict[str, Any]] = []
    for o in batch.outcomes:
        meta: dict[str, Any] = {
            "name": o.name,
            "display_name": o.display_name,
            "category": o.category,
            "engine": o.engine,
            "data_fidelity": o.data_fidelity,
            "universe": "-",
            "description": "",
        }
        try:
            spec = get_strategy(o.name).spec
            meta["universe"] = spec.universe
            meta["description"] = spec.description
        except (KeyError, Exception):  # noqa: BLE001 - spec optional for the report
            pass
        out.append(meta)
    return out


@dataclass
class FinalReport:
    """The composed V1.0 research report."""

    config_name: str
    generated_at: str
    start: str
    end: str
    benchmark: str
    n_strategies: int
    library: list[dict[str, Any]]
    ranking: list[dict[str, Any]]
    combination: dict[str, Any]
    current_regime: Regime
    regime_counts: dict[str, int]
    recommendations: dict[str, dict[str, Any]]
    top_single: dict[str, Any] | None
    verdict_strategy: str
    verdict_display: str
    verdict_note: str

    # ------------------------------------------------------------------ #
    # Builder
    # ------------------------------------------------------------------ #
    @classmethod
    def from_batch(
        cls,
        batch: BatchResult,
        *,
        benchmark_close: pd.Series | None = None,
        breadth: pd.Series | None = None,
        current_regime: Regime | None = None,
        ranking: RankingReport | None = None,
        scorecard: Scorecard | None = None,
        combination_cfg: Any | None = None,
        start: str = _DATE_RANGE_DEFAULT[0],
        end: str = _DATE_RANGE_DEFAULT[1],
        benchmark: str = "csi300",
    ) -> FinalReport:
        """Compose the V1.0 report from a batch experiment (plus optional market data)."""
        rank = ranking or RankingReport.from_batch(batch, scorecard=scorecard)
        combo = CombinationEngine(config=combination_cfg).combine(
            batch, ranking=rank, scorecard=scorecard
        )
        engine = MarketRegimeEngine()

        # Current / live regime: explicit > inferred from benchmark > neutral.
        live = current_regime
        regime_counts: dict[str, int] = {r: 0 for r in REGIMES_5}
        if live is None and benchmark_close is not None:
            labels = engine.classify(benchmark_close, breadth=breadth)
            live = Regime(labels.iloc[-1]) if not labels.empty else NEUTRAL
            regime_counts = _regime_counts(labels)
        elif live is None:
            live = NEUTRAL

        recs = engine.recommendations(batch, ranking=rank, scorecard=scorecard)
        top_single = rank.details[0] if rank.details else None

        # The verdict: strategy for the current environment (if known), else the
        # highest-ranked single strategy overall.
        rec = recs.get(live)
        if rec is not None:
            verdict_strategy = rec.strategy
            verdict_display = rec.display_name
        elif top_single is not None:
            verdict_strategy = top_single["name"]
            verdict_display = top_single.get("display_name") or top_single["name"]
        else:
            verdict_strategy = "-"
            verdict_display = "-"

        note = cls._build_verdict_note(live, rec, top_single, combo, benchmark_close is not None)

        return cls(
            config_name=batch.config_name,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            start=start,
            end=end,
            benchmark=benchmark,
            n_strategies=len(batch.outcomes),
            library=_library_meta(batch),
            ranking=rank.details,
            combination=combo.to_dict(),
            current_regime=live,
            regime_counts=regime_counts,
            recommendations={r: recs[r].to_dict() for r in REGIMES_5},
            top_single=top_single,
            verdict_strategy=verdict_strategy,
            verdict_display=verdict_display,
            verdict_note=note,
        )

    @staticmethod
    def _build_verdict_note(
        live: Regime,
        rec: Any | None,
        top_single: dict[str, Any] | None,
        combo: Any,
        has_market: bool,
    ) -> str:
        """Compose the explicit answer to the project's success question."""
        parts: list[str] = []
        if has_market and rec is not None:
            parts.append(
                f"当前市场状态为「{REGIME_LABELS.get(live, live)}」，该状态下历史样本外"
                f"最优策略为「{rec.display_name}」（{rec.category} 类 / {rec.engine} 引擎 / "
                f"数据可信度 {rec.data_fidelity}）。建议以此策略为主、配合组合配权分散风险。"
            )
        elif top_single is not None:
            parts.append(
                f"未提供实时市场状态；综合 AROS 评分最高的单策略为「"
                f"{top_single.get('display_name') or top_single['name']}」"
                f"（评分 {top_single['score']:.2f}）。"
            )
        # Always surface the combined book as the diversification anchor.
        sel = combo.selected
        if sel:
            parts.append(
                f"推荐组合为对 Top-{len(sel)} 策略（{', '.join(sel)}）做分市场环境配权，"
                f"趋势市与震荡市分别归一化，权重见「组合方案」。"
            )
        parts.append(
            "情绪类策略（首板/二板接力/连板博弈/情绪冰点修复）涉及分时与连板生命周期，"
            "日线仅可近似，连板博弈标注为仅供参考；所有结论以 walk-forward 样本外(OOS)为准，"
            "严禁未来函数。"
        )
        return "".join(parts)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    # ------------------------------------------------------------------ #
    # Markdown
    # ------------------------------------------------------------------ #
    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# AROS A 股短线策略研究报告 V1.0")
        lines.append("")
        lines.append(f"- 实验配置: {self.config_name}")
        lines.append(f"- 策略数: {self.n_strategies}")
        lines.append(f"- 区间: {self.start} ~ {self.end}")
        lines.append(f"- 基准: {self.benchmark}")
        lines.append(
            f"- 当前市场状态: {REGIME_LABELS.get(self.current_regime, self.current_regime)}"
        )
        lines.append(f"- 生成时间: {self.generated_at}")
        lines.append("")

        # Section 1: strategy library
        lines.append("## 一、策略库概览（10 套 · 按数据可信度）")
        lines.append("")
        lib_header = ["策略", "类别", "引擎", "股票池", "数据可信度", "说明"]
        lines.append("| " + " | ".join(lib_header) + " |")
        lines.append("|" + "|".join(["---"] * len(lib_header)) + "|")
        for m in self.library:
            lines.append(
                f"| {m['display_name'] or m['name']} | {m['category']} | {m['engine']} | "
                f"{m['universe']} | {m['data_fidelity']} | {m['description']} |"
            )
        lines.append("")

        # Section 2: ranking
        lines.append("## 二、AROS 策略排名（样本外 OOS · 0–100）")
        lines.append("")
        lines.append("| 排名 | 策略 | 类别 | 评分 | 收益(OOS) | 胜率(OOS) | 回撤(OOS) | OOS衰减 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for d in self.ranking:
            lines.append(
                f"| {d['rank']} | {d['display_name'] or d['name']} | {d['category']} | "
                f"{d['score']:.2f} | {_pct(d['total_return_oos'])} | {_pct(d['win_rate_oos'])} | "
                f"{_pct(d['max_drawdown_oos'])} | {d['oos_decay_tag']} |"
            )
        lines.append("")

        # Section 3: combination
        lines.append("## 三、组合方案（分市场环境配权）")
        lines.append("")
        for env in ENVS:
            wmap = self.combination.get("weights", {}).get(env)
            if not wmap:
                continue
            label = "趋势市" if env == TRENDING else "震荡市"
            lines.append(f"### {label}")
            lines.append("")
            lines.append("| 策略 | 权重 |")
            lines.append("| --- | --- |")
            for name, w in wmap.items():
                lines.append(f"| {name} | {w * 100:.1f}% |")
            lines.append("")

        # Section 4: regime engine
        lines.append("## 四、市场状态引擎与动态选策略")
        lines.append("")
        if any(v for v in self.regime_counts.values()):
            counts = " / ".join(
                f"{REGIME_LABELS.get(r, r)}:{self.regime_counts.get(r, 0)}" for r in REGIMES_5
            )
            lines.append(f"- 历史区间状态分布: {counts}")
            lines.append("")
        lines.append("| 市场状态 | 推荐策略 | 类别 | 数据可信度 | 依据 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in REGIMES_5:
            rec = self.recommendations.get(r, {})
            dn = rec.get("display_name") or rec.get("strategy", "-")
            lines.append(
                f"| {REGIME_LABELS.get(r, r)} | {dn} | "
                f"{rec.get('category', '-')} | {rec.get('data_fidelity', '-')} | "
                f"{rec.get('basis', '-')} |"
            )
        lines.append("")

        # Section 5: verdict
        lines.append("## 五、最终推荐结论")
        lines.append("")
        lines.append(
            f"**若明天开始做 A 股短线，最值得使用的是：** "
            f"「{self.verdict_display}」"
            + (
                f"（当前状态「{REGIME_LABELS.get(self.current_regime, self.current_regime)}」适配）"
                if any(v for v in self.regime_counts.values())
                else ""
            )
            + "。"
        )
        lines.append("")
        lines.append(self.verdict_note)
        lines.append("")
        lines.append(
            "> 本报告所有评分与推荐均基于 walk-forward 样本外(OOS)回测，可复现、可解释、"
            "无未来函数；情绪类策略分时缺失，连板博弈标注为仅供参考。"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # HTML (self-contained, offline: inline CSS)
    # ------------------------------------------------------------------ #
    def to_html(self) -> str:
        def esc(s: Any) -> str:
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        css = (
            "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,"
            "sans-serif;color:#1f2937;margin:24px;line-height:1.5;}"
            "h1{font-size:22px;border-bottom:2px solid #2563eb;padding-bottom:6px;}"
            "h2{font-size:17px;margin-top:24px;color:#111827;}"
            "h3{font-size:15px;margin-top:16px;color:#1f2937;}"
            "table{border-collapse:collapse;width:auto;margin:8px 0;font-size:13px;}"
            "th,td{border:1px solid #d1d5db;padding:5px 10px;text-align:right;}"
            "th{background:#eff6ff;}"
            "td:nth-child(1),th:nth-child(1),td:nth-child(2),th:nth-child(2)"
            "{text-align:left;}"
            ".meta{font-size:13px;color:#374151;}"
            ".meta b{color:#111827;}"
            ".verdict{background:#ecfdf5;border:1px solid #10b981;border-radius:6px;"
            "padding:10px 14px;margin:10px 0;font-size:14px;}"
            ".note{font-size:12px;color:#6b7280;}"
        )
        parts: list[str] = []
        parts.append("<!doctype html><html lang='zh'><head><meta charset='utf-8'>")
        parts.append("<title>AROS A 股短线策略研究报告 V1.0</title>")
        parts.append("<style>" + css + "</style></head><body>")
        parts.append("<h1>AROS A 股短线策略研究报告 V1.0</h1>")
        parts.append("<div class='meta'>")
        parts.append(f"<p><b>实验配置:</b> {esc(self.config_name)} &nbsp; ")
        parts.append(f"<b>策略数:</b> {esc(self.n_strategies)} &nbsp; ")
        parts.append(f"<b>区间:</b> {esc(self.start)} ~ {esc(self.end)}</p>")
        cur = REGIME_LABELS.get(self.current_regime, self.current_regime)
        parts.append(
            f"<p><b>基准:</b> {esc(self.benchmark)} &nbsp; "
            f"<b>当前市场状态:</b> {esc(cur)}"
            f" &nbsp; <b>生成时间:</b> {esc(self.generated_at)}</p>"
        )
        parts.append("</div>")

        # Section 1
        parts.append("<h2>一、策略库概览</h2>")
        parts.append(
            "<table><tr><th>策略</th><th>类别</th><th>引擎</th><th>股票池</th>"
            "<th>数据可信度</th><th>说明</th></tr>"
        )
        for m in self.library:
            parts.append(
                f"<tr><td>{esc(m['display_name'] or m['name'])}</td>"
                f"<td>{esc(m['category'])}</td><td>{esc(m['engine'])}</td>"
                f"<td>{esc(m['universe'])}</td><td>{esc(m['data_fidelity'])}</td>"
                f"<td>{esc(m['description'])}</td></tr>"
            )
        parts.append("</table>")

        # Section 2
        parts.append("<h2>二、AROS 策略排名（样本外 OOS · 0–100）</h2>")
        parts.append(
            "<table><tr><th>排名</th><th>策略</th><th>类别</th><th>评分</th>"
            "<th>收益(OOS)</th><th>胜率(OOS)</th><th>回撤(OOS)</th><th>OOS衰减</th></tr>"
        )
        for d in self.ranking:
            score_s = f"{d['score']:.2f}"
            parts.append(
                "<tr>"
                f"<td>{esc(d['rank'])}</td>"
                f"<td>{esc(d['display_name'] or d['name'])}</td>"
                f"<td>{esc(d['category'])}</td>"
                f"<td>{esc(score_s)}</td>"
                f"<td>{esc(_pct(d['total_return_oos']))}</td>"
                f"<td>{esc(_pct(d['win_rate_oos']))}</td>"
                f"<td>{esc(_pct(d['max_drawdown_oos']))}</td>"
                f"<td>{esc(d['oos_decay_tag'])}</td>"
                "</tr>"
            )
        parts.append("</table>")

        # Section 3
        parts.append("<h2>三、组合方案（分市场环境配权）</h2>")
        for env in ENVS:
            wmap = self.combination.get("weights", {}).get(env)
            if not wmap:
                continue
            label = "趋势市" if env == TRENDING else "震荡市"
            parts.append(f"<h3>{label}</h3>")
            parts.append("<table><tr><th>策略</th><th>权重</th></tr>")
            for name, w in wmap.items():
                weight_s = f"{w * 100:.1f}%"
                parts.append(f"<tr><td>{esc(name)}</td><td>{esc(weight_s)}</td></tr>")
            parts.append("</table>")

        # Section 4
        parts.append("<h2>四、市场状态引擎与动态选策略</h2>")
        parts.append(
            "<table><tr><th>市场状态</th><th>推荐策略</th><th>类别</th>"
            "<th>数据可信度</th><th>依据</th></tr>"
        )
        for r in REGIMES_5:
            rec = self.recommendations.get(r, {})
            parts.append(
                "<tr>"
                f"<td>{esc(REGIME_LABELS.get(r, r))}</td>"
                f"<td>{esc(rec.get('display_name') or rec.get('strategy', '-'))}</td>"
                f"<td>{esc(rec.get('category', '-'))}</td>"
                f"<td>{esc(rec.get('data_fidelity', '-'))}</td>"
                f"<td>{esc(rec.get('basis', '-'))}</td>"
                "</tr>"
            )
        parts.append("</table>")

        # Section 5
        parts.append("<h2>五、最终推荐结论</h2>")
        cur = REGIME_LABELS.get(self.current_regime, self.current_regime)
        suffix = (
            f"（当前状态「{esc(cur)}」适配）" if any(v for v in self.regime_counts.values()) else ""
        )
        parts.append(
            f"<div class='verdict'>若明天开始做 A 股短线，最值得使用的是："
            f"<b>{esc(self.verdict_display)}</b>{suffix}</div>"
        )
        parts.append(f"<p class='note'>{esc(self.verdict_note)}</p>")
        parts.append("</body></html>")
        return "\n".join(parts)


def render_final_report(
    batch: BatchResult,
    *,
    benchmark_close: pd.Series | None = None,
    breadth: pd.Series | None = None,
    current_regime: Regime | None = None,
    ranking: RankingReport | None = None,
    scorecard: Scorecard | None = None,
    start: str = _DATE_RANGE_DEFAULT[0],
    end: str = _DATE_RANGE_DEFAULT[1],
    benchmark: str = "csi300",
) -> str:
    """Render the V1.0 final report to markdown (entry point)."""
    return FinalReport.from_batch(
        batch,
        benchmark_close=benchmark_close,
        breadth=breadth,
        current_regime=current_regime,
        ranking=ranking,
        scorecard=scorecard,
        start=start,
        end=end,
        benchmark=benchmark,
    ).to_markdown()
