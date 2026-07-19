"""Cross-strategy ranking report (Sprint 3.3).

Bridges a :class:`~research.batch.BatchResult` into the :class:`~research.scorecard.Scorecard`
and renders the AROS Strategy Score ranking table in markdown / json / html
(frozen format in Phase 3 design §4). The ranking is computed on the
*out-of-sample* (walk-forward) metrics so it reflects the honest, anti-overfit
read; the in-sample metrics are carried alongside only to power the E3 OOS-decay
penalty on the Sharpe dimension.

The :class:`RankingReport` is part of the research reporting family (sits beside
:class:`~research.report.ResearchReport`) and is re-exported from that module.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from research.batch import BatchResult, StrategyBatchOutcome
from research.scorecard import Scorecard, ScoreInput, ScoreRow


def _numeric_metrics(d: Mapping[str, float | None] | None) -> dict[str, float]:
    """Drop ``None``/non-numeric/non-finite entries -> clean ``{key: float}``.

    Non-finite values (e.g. ``profit_factor`` when a backtest has zero losing
    days, or a divide-by-zero Sharpe) are excluded like missing data so they
    can never poison the scorer's min-max normalisation with ``inf``/``nan``.
    """
    if not d:
        return {}
    return {
        k: float(v)
        for k, v in d.items()
        if v is not None and isinstance(v, (int, float)) and math.isfinite(v)
    }


def build_score_inputs(batch: BatchResult) -> list[ScoreInput]:
    """Bridge a :class:`BatchResult` into the :class:`Scorecard` input list.

    Ranking uses the *out-of-sample* (OOS / walk-forward) metrics as the scored
    values (the honest, anti-overfit read); ``is_metrics`` / ``oos_metrics`` are
    passed through so the scorer can apply the E3 OOS-decay penalty on Sharpe.
    ``None`` values are dropped (a strategy with no realised value on a dimension
    simply does not contribute to that dimension's cross-section).
    """
    out: list[ScoreInput] = []
    for o in batch.outcomes:
        oos = _numeric_metrics(o.oos_metrics)
        is_m = _numeric_metrics(o.is_metrics)
        # When no walk-forward OOS window exists, fall back to IS (== full).
        scored = oos or is_m
        out.append(
            ScoreInput(
                name=o.name,
                metrics=dict(scored),
                is_metrics=dict(is_m),
                oos_metrics=dict(oos or is_m),
            )
        )
    return out


def _oos_decay(is_m: Mapping[str, float | None], oos_m: Mapping[str, float | None]) -> float:
    """Walk-forward Sharpe decay (IS -> OOS); 0 when IS Sharpe <= 0 or unknown."""
    is_s = is_m.get("sharpe")
    oos_s = oos_m.get("sharpe")
    if is_s is None or oos_s is None:
        return 0.0
    is_s = float(is_s)
    if is_s <= 0:
        return 0.0
    return max(0.0, (is_s - float(oos_s)) / is_s)


def _decay_tag(decay: float) -> str:
    """Map a Sharpe decay ratio to a 低/中/高 stability label (§4 sample)."""
    if decay < 0.30:
        return "低"
    if decay < 0.60:
        return "中"
    return "高"


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    if v == 0:
        return "0.0000"
    return f"{v:.4f}"


def _pct(v: float | None) -> str:
    if v is None:
        return "-"
    if v == 0:
        return "0.0%"
    return f"{v * 100:.1f}%"


@dataclass
class RankingReport:
    """A rendered cross-strategy AROS Strategy Score ranking.

    Built from a :class:`BatchResult` via :meth:`from_batch`. ``details`` carries
    one row per strategy (aligned to ``rows`` by name) with the headline metrics
    shown in the §4 table plus the OOS-decay stability read.
    """

    config_name: str
    rows: list[ScoreRow]
    details: list[dict[str, Any]]
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ #
    # Builder
    # ------------------------------------------------------------------ #
    @classmethod
    def from_batch(cls, batch: BatchResult, scorecard: Scorecard | None = None) -> RankingReport:
        """Score ``batch`` and build the ranking report.

        ``scorecard`` lets the caller inject a config-driven
        :class:`Scorecard` (e.g. ``Scorecard.from_config(app.research.scorecard)``);
        otherwise the default 7-dimension weights are used.
        """
        sc = scorecard or Scorecard()
        inputs = build_score_inputs(batch)
        rows = sc.rank(inputs)
        details = cls._build_details(batch, rows)
        return cls(config_name=batch.config_name, rows=rows, details=details)

    @staticmethod
    def _build_details(batch: BatchResult, rows: list[ScoreRow]) -> list[dict[str, Any]]:
        by_name = {o.name: o for o in batch.outcomes}
        out: list[dict[str, Any]] = []
        for r in rows:  # rows are score-descending after rank()
            o: StrategyBatchOutcome | None = by_name.get(r.name)
            if o is None:
                continue
            is_m = o.is_metrics or {}
            oos_m = o.oos_metrics or {}
            decay = _oos_decay(is_m, oos_m)
            out.append(
                {
                    "rank": r.rank,
                    "name": o.name,
                    "display_name": o.display_name,
                    "category": o.category,
                    "engine": o.engine,
                    "data_fidelity": o.data_fidelity,
                    "score": round(r.score, 4),
                    "total_return_oos": oos_m.get("total_return"),
                    "win_rate_oos": oos_m.get("win_rate"),
                    "max_drawdown_oos": oos_m.get("max_drawdown"),
                    "avg_holding_days_oos": oos_m.get("avg_holding_days"),
                    "oos_decay": round(decay, 4),
                    "oos_decay_tag": _decay_tag(decay),
                    "components": {k: round(v, 4) for k, v in r.components.items()},
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {
                "config_name": self.config_name,
                "generated_at": self.generated_at,
                "n_strategies": len(self.rows),
                "ranking": self.details,
            },
            ensure_ascii=False,
            indent=indent,
        )

    # ------------------------------------------------------------------ #
    # Markdown
    # ------------------------------------------------------------------ #
    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# AROS 策略排名报告")
        lines.append("")
        lines.append(f"- 实验配置: {self.config_name}")
        lines.append(f"- 策略数: {len(self.rows)}")
        lines.append(f"- 生成时间: {self.generated_at}")
        lines.append("")
        lines.append("## 策略排名（AROS Strategy Score · 0–100）")
        lines.append("")
        header = [
            "排名",
            "策略",
            "类别",
            "引擎",
            "评分",
            "收益(OOS)",
            "胜率(OOS)",
            "回撤(OOS)",
            "持仓(天)",
            "OOS衰减",
            "数据可信度",
        ]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for d in self.details:
            lines.append(
                "| {rank} | {name} | {cat} | {eng} | {score:.2f} | {tr} | {wr} | "
                "{mdd} | {hold} | {tag} | {fid} |".format(
                    rank=d["rank"],
                    name=d["display_name"] or d["name"],
                    cat=d["category"],
                    eng=d["engine"],
                    score=d["score"],
                    tr=_pct(d["total_return_oos"]),
                    wr=_pct(d["win_rate_oos"]),
                    mdd=_pct(d["max_drawdown_oos"]),
                    hold=_fmt(d["avg_holding_days_oos"]),
                    tag=d["oos_decay_tag"],
                    fid=d["data_fidelity"],
                )
            )
        lines.append("")
        lines.append(
            "> 评分基于样本外(OOS) walk-forward 指标做截面归一化加权；"
            "「OOS衰减」高代表过拟合风险（夏普 IS→OOS 衰减大），"
            "E3 会据此对稳定性维度打折。"
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
            "table{border-collapse:collapse;width:auto;margin:8px 0;font-size:13px;}"
            "th,td{border:1px solid #d1d5db;padding:5px 10px;text-align:right;}"
            "th{background:#eff6ff;}"
            "td:nth-child(1),th:nth-child(1),td:nth-child(2),th:nth-child(2)"
            "{text-align:left;}"
            ".meta{font-size:13px;color:#374151;}"
            ".meta b{color:#111827;}"
            ".tag-low{color:#15803d;font-weight:600;}"
            ".tag-mid{color:#b45309;font-weight:600;}"
            ".tag-high{color:#b91c1c;font-weight:600;}"
        )
        cls = {"低": "tag-low", "中": "tag-mid", "高": "tag-high"}

        parts: list[str] = []
        parts.append("<!doctype html><html lang='zh'><head><meta charset='utf-8'>")
        parts.append("<title>AROS 策略排名报告</title><style>" + css + "</style></head><body>")
        parts.append("<h1>AROS 策略排名报告</h1>")
        parts.append("<div class='meta'>")
        parts.append(f"<p><b>实验配置:</b> {esc(self.config_name)} &nbsp; ")
        parts.append(f"<b>策略数:</b> {esc(len(self.rows))}</p>")
        parts.append(f"<p><b>生成时间:</b> {esc(self.generated_at)}</p>")
        parts.append("</div>")
        parts.append("<h2>策略排名（AROS Strategy Score · 0–100）</h2>")
        parts.append(
            "<table><tr>"
            "<th>排名</th><th>策略</th><th>类别</th><th>引擎</th><th>评分</th>"
            "<th>收益(OOS)</th><th>胜率(OOS)</th><th>回撤(OOS)</th>"
            "<th>持仓(天)</th><th>OOS衰减</th><th>数据可信度</th></tr>"
        )
        for d in self.details:
            tag_cls = cls.get(d["oos_decay_tag"], "")
            parts.append(
                "<tr>"
                f"<td>{esc(d['rank'])}</td>"
                f"<td>{esc(d['display_name'] or d['name'])}</td>"
                f"<td>{esc(d['category'])}</td>"
                f"<td>{esc(d['engine'])}</td>"
                f"<td>{esc(f'{d['score']:.2f}')}</td>"
                f"<td>{esc(_pct(d['total_return_oos']))}</td>"
                f"<td>{esc(_pct(d['win_rate_oos']))}</td>"
                f"<td>{esc(_pct(d['max_drawdown_oos']))}</td>"
                f"<td>{esc(_fmt(d['avg_holding_days_oos']))}</td>"
                f"<td class='{tag_cls}'>{esc(d['oos_decay_tag'])}</td>"
                f"<td>{esc(d['data_fidelity'])}</td>"
                "</tr>"
            )
        parts.append("</table>")
        parts.append(
            "<p style='font-size:12px;color:#6b7280;'>评分基于样本外(OOS) walk-forward "
            "指标做截面归一化加权；「OOS衰减」高代表过拟合风险（夏普 IS→OOS 衰减大），"
            "E3 会据此对稳定性维度打折。</p>"
        )
        parts.append("</body></html>")
        return "\n".join(parts)


def render_ranking_report(batch: BatchResult, scorecard: Scorecard | None = None) -> str:
    """Render a batch's cross-strategy ranking to a markdown report (entry point).

    Mirrors :func:`research.report.render_experiment_report`: a convenience for
    the reporting layer / CLI that scores and renders in one call.
    """
    return RankingReport.from_batch(batch, scorecard=scorecard).to_markdown()
