"""Research report rendering (Sprint 2.6).

Aggregates an experiment's metrics + benchmark comparison + walk-forward IS/OOS
into a shareable report (markdown / json / html). Rendering reuses the 1.8 /
1.14 :class:`~report.engine.DailyReport` style: inline CSS and inline SVG bars
so the HTML is fully self-contained and renders offline (no external JS/CSS).

No new metric math -- the report only *presents* data the runner (2.4) and the
walk-forward runner (2.5) already produced and persisted. The renderer is a pure
function of an :class:`ExperimentResult` (plus optional run metadata), so it can
render either a fresh in-memory result or one reconstructed from the database.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# Sprint 3.3: cross-strategy ranking report -- part of the research report
# family (sits beside :class:`ResearchReport` and is reachable from this module).
# Sprint 3.5: Market Regime Engine + V1.0 final report join the same family.
from research.experiment import ExperimentConfig, ExperimentResult
from research.models import ExperimentRun

# Metric keys surfaced prominently in the report (portfolio + benchmark).
_PORTFOLIO_KEYS = (
    "total_return",
    "annual_return",
    "max_drawdown",
    "sharpe",
    "sortino",
    "benchmark_return",
)
_BENCH_KEYS = (
    "bench_excess_return",
    "bench_alpha",
    "bench_beta",
    "bench_tracking_error",
    "bench_information_ratio",
)
_METRIC_LABELS = {
    "total_return": "总收益",
    "annual_return": "年化收益",
    "max_drawdown": "最大回撤",
    "sharpe": "夏普比率",
    "sortino": "索提诺比率",
    "benchmark_return": "基准收益(买入持有)",
    "bench_excess_return": "超额收益",
    "bench_alpha": "Alpha",
    "bench_beta": "Beta",
    "bench_tracking_error": "跟踪误差",
    "bench_information_ratio": "信息比率",
}


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.4f}"


def _label_with_key(k: str) -> str:
    """Human label plus the raw metric key (markdown is the machine reference)."""
    label = _METRIC_LABELS.get(k, k)
    if k == label:
        return label
    return f"{label} `{k}`"


def _drawdown_series(eq: Mapping[str, float]) -> list[float]:
    """Running drawdown at each equity point: value / running-peak - 1 (<= 0).

    Derived purely for *visualisation* (the renderer presents, it does not
    invent backtest metrics); the underlying equity is already persisted.
    """
    out: list[float] = []
    peak = float("-inf")
    for v in eq.values():
        v = float(v)
        peak = max(peak, v)
        out.append(v / peak - 1.0 if peak > 0 else 0.0)
    return out


def _max_drawdown(eq: Mapping[str, float]) -> float:
    """Largest drawdown over the equity series (<= 0)."""
    dd = _drawdown_series(eq)
    return min(dd) if dd else 0.0


def _svg_equity(window_label: str, eq: Mapping[str, float]) -> str:
    """Inline SVG equity curve -- self-contained, offline (no external JS/CSS)."""
    items = sorted((str(d), float(v)) for d, v in eq.items())
    if len(items) < 2:
        return ""
    labels = [d for d, _ in items]
    vals = [v for _, v in items]
    n = len(vals)
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1e-9
    W, H = 720.0, 240.0
    px0, px1, py0, py1 = 52.0, 704.0, 16.0, 212.0

    def X(i: int) -> float:
        return px0 + (i / (n - 1)) * (px1 - px0)

    def Y(v: float) -> float:
        return py1 - ((v - vmin) / (vmax - vmin)) * (py1 - py0)

    grid = ""
    for g in range(5):
        gv = vmin + (vmax - vmin) * g / 4
        gy = Y(gv)
        grid += (
            f'<line x1="{px0:.1f}" y1="{gy:.1f}" x2="{px1:.1f}" y2="{gy:.1f}" class="gl"/>'
            f'<text x="{px0 - 6:.1f}" y="{gy + 3:.1f}" class="gx" text-anchor="end">'
            f"{gv:.2f}</text>"
        )
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    base = ""
    if vmin <= 1.0 <= vmax:
        by = Y(1.0)
        base = f'<line x1="{px0:.1f}" y1="{by:.1f}" x2="{px1:.1f}" y2="{by:.1f}" class="base"/>'
    xl = (
        f'<text x="{X(0):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">{labels[0]}</text>'
        f'<text x="{X(n // 2):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">'
        f"{labels[n // 2]}</text>"
        f'<text x="{X(n - 1):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">'
        f"{labels[-1]}</text>"
    )
    return (
        f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
        f'role="img" aria-label="equity {window_label}">'
        + grid
        + base
        + f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="2"/>'
        + xl
        + "</svg>"
    )


def _svg_drawdown(window_label: str, eq: Mapping[str, float]) -> str:
    """Inline SVG drawdown area -- self-contained, offline (no external JS/CSS)."""
    items = sorted((str(d), float(v)) for d, v in eq.items())
    if len(items) < 2:
        return ""
    dd = _drawdown_series(dict(items))
    n = len(dd)
    dmin = min(dd)
    dmax = max(dd)
    if dmin == dmax:
        dmin -= 1e-9
    W, H = 720.0, 180.0
    px0, px1, py0, py1 = 52.0, 704.0, 12.0, 152.0

    def X(i: int) -> float:
        return px0 + (i / (n - 1)) * (px1 - px0)

    def Y(d: float) -> float:
        return py0 + ((d - dmin) / (dmax - dmin)) * (py1 - py0)

    zero_y = Y(0.0)
    area = (
        f"M {X(0):.1f} {zero_y:.1f} "
        + " ".join(f"L {X(i):.1f} {Y(d):.1f}" for i, d in enumerate(dd))
        + f" L {X(n - 1):.1f} {zero_y:.1f} Z"
    )
    line = " ".join(f"{X(i):.1f},{Y(d):.1f}" for i, d in enumerate(dd))
    labels = [d for d, _ in items]
    grid = (
        f'<text x="{px0 - 6:.1f}" y="{zero_y + 3:.1f}" class="gx" text-anchor="end">0.0%</text>'
        f'<text x="{px0 - 6:.1f}" y="{Y(dmin) + 3:.1f}" class="gx" text-anchor="end">'
        f"{dmin:.1%}</text>"
    )
    xl = (
        f'<text x="{X(0):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">{labels[0]}</text>'
        f'<text x="{X(n // 2):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">'
        f"{labels[n // 2]}</text>"
        f'<text x="{X(n - 1):.1f}" y="{H - 8:.1f}" class="gx" text-anchor="middle">'
        f"{labels[-1]}</text>"
    )
    return (
        f'<svg width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
        f'role="img" aria-label="drawdown {window_label}">'
        + grid
        + f'<path d="{area}" fill="#fca5a5" fill-opacity="0.45"/>'
        + f'<polyline points="{line}" fill="none" stroke="#dc2626" stroke-width="1.5"/>'
        + xl
        + "</svg>"
    )


def _is_oos_window(w: str) -> bool:
    return str(w).startswith("oos")


@dataclass
class ResearchReport:
    """A rendered research experiment report.

    Built from a persisted :class:`ExperimentRun` plus its reconstructed
    :class:`ExperimentResult` via :meth:`from_run`. The stub-era
    :func:`render_experiment_report` falls back to :meth:`from_result` when only
    an in-memory result is available.
    """

    run_id: str
    name: str
    strategy: str
    start: str
    end: str
    benchmark: str
    walk_forward: str | None
    status: str
    is_oos: bool
    windows: list[str]
    metrics: dict[str, Mapping[str, float | None]]
    equity: dict[str, dict[str, float]]
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------------------ #
    # Builders
    # ------------------------------------------------------------------ #
    @staticmethod
    def _config(run: ExperimentRun) -> ExperimentConfig:
        return ExperimentConfig.model_validate_json(run.config_json)

    @classmethod
    def from_run(cls, run: ExperimentRun, result: ExperimentResult) -> ResearchReport:
        """Build the report from a DB row + its reconstructed result."""
        cfg = cls._config(run)
        windows = list(result.windows)
        is_oos = any(_is_oos_window(w) for w in windows)
        wf = None
        if cfg.walk_forward is not None:
            wf = (
                f"{cfg.walk_forward.train_years}/{cfg.walk_forward.test_years}/"
                f"{cfg.walk_forward.step_years} 年"
            )
        return cls(
            run_id=run.id,
            name=run.name,
            strategy=cfg.strategy,
            start=cfg.start,
            end=cfg.end,
            benchmark=cfg.benchmark,
            walk_forward=wf,
            status=run.status,
            is_oos=is_oos,
            windows=windows,
            metrics={k: dict(v) for k, v in result.metrics.items()},
            equity={k: dict(v) for k, v in result.equity.items()},
        )

    @classmethod
    def from_result(cls, result: ExperimentResult) -> ResearchReport:
        """Build a report from an in-memory result only (stub fallback path)."""
        windows = list(result.windows)
        is_oos = any(_is_oos_window(w) for w in windows)
        return cls(
            run_id=result.run_id,
            name="(from result)",
            strategy="-",
            start="-",
            end="-",
            benchmark="-",
            walk_forward=None,
            status="unknown",
            is_oos=is_oos,
            windows=windows,
            metrics={k: dict(v) for k, v in result.metrics.items()},
            equity={k: dict(v) for k, v in result.equity.items()},
        )

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    # ------------------------------------------------------------------ #
    # Metric selection helpers
    # ------------------------------------------------------------------ #
    def _summary_window(self) -> str | None:
        """Pick the window to summarize: prefer is_agg (walk-forward) / full."""
        if "is_agg" in self.metrics:
            return "is_agg"
        if "full" in self.metrics:
            return "full"
        return self.windows[0] if self.windows else None

    def _ordered_keys(self, *groups: tuple[str, ...]) -> list[str]:
        """Return the union of known metric keys actually present, in order."""
        present: list[str] = []
        for group in groups:
            for k in group:
                if k not in present and (
                    k in self.metrics.get("is_agg", {})
                    or k in self.metrics.get("oos_agg", {})
                    or k in self.metrics.get(self._summary_window() or "", {})
                ):
                    present.append(k)
        return present

    # ------------------------------------------------------------------ #
    # Markdown
    # ------------------------------------------------------------------ #
    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# AROS 研究实验报告")
        lines.append("")
        lines.append(f"- 实验 ID: {self.run_id}")
        lines.append(f"- 名称: {self.name}")
        lines.append(f"- 状态: {self.status}")
        lines.append(f"- 策略: {self.strategy}")
        lines.append(f"- 区间: {self.start} ~ {self.end}")
        lines.append(f"- 基准: {self.benchmark}")
        lines.append(f"- 样本外(OOS): {'是' if self.is_oos else '否'}")
        if self.walk_forward is not None:
            lines.append(f"- Walk-forward: 训练/测试/步长 = {self.walk_forward}")
        lines.append(f"- 生成时间: {self.generated_at}")
        lines.append("")

        if self.is_oos:
            lines.append("## 一、IS vs OOS 指标对比")
            lines.append("")
            header = ["指标", "样本内(IS)", "样本外(OOS)", "衰减(IS-OOS)"]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            is_m = self.metrics.get("is_agg", {})
            oos_m = self.metrics.get("oos_agg", {})
            for k in self._ordered_keys(_PORTFOLIO_KEYS, _BENCH_KEYS):
                iv = is_m.get(k)
                ov = oos_m.get(k)
                decay = "-" if (iv is None or ov is None) else f"{iv - ov:.4f}"
                lines.append(f"| {_label_with_key(k)} | {_fmt(iv)} | {_fmt(ov)} | {decay} |")
            lines.append("")
        else:
            lines.append("## 一、指标汇总")
            lines.append("")
            lines.append("| 指标 | 值 |")
            lines.append("| --- | --- |")
            summ = self.metrics.get(self._summary_window() or "", {})
            for k, v in summ.items():
                lines.append(f"| {_label_with_key(k)} | {_fmt(v)} |")
            lines.append("")

        lines.append("## 二、全部窗口明细")
        lines.append("")
        for w in self.windows:
            m = self.metrics.get(w, {})
            if not m:
                continue
            title = f"窗口 {w}" + (" (OOS)" if _is_oos_window(w) else "")
            lines.append(f"### {title}")
            lines.append("")
            for k, v in m.items():
                lines.append(f"- {_label_with_key(k)}: {_fmt(v)}")
            lines.append("")

        if self.equity:
            lines.append("## 三、净值与回撤")
            lines.append("")
            for w, eq in self.equity.items():
                if not eq:
                    continue
                vals = list(eq.values())
                peak = max(vals)
                mdd = _max_drawdown(eq)
                last = vals[-1] if vals else 0.0
                tag = " (OOS)" if _is_oos_window(w) else ""
                lines.append(
                    f"- 窗口 {w}{tag}: 期末净值 {last:.3f}, 峰值 {peak:.3f}, " f"最大回撤 {mdd:.1%}"
                )
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # HTML (self-contained, offline: inline CSS + inline SVG)
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
            "td:nth-child(1),th:nth-child(1){text-align:left;}"
            ".meta{font-size:13px;color:#374151;}"
            ".meta b{color:#111827;}"
            ".bar-is{fill:#2563eb;}"
            ".bar-oos{fill:#f59e0b;}"
            ".bl{font-size:12px;fill:#374151;}"
            ".bv{font-size:11px;fill:#6b7280;}"
            ".zero{stroke:#9ca3af;stroke-width:1;}"
            ".gl{stroke:#e5e7eb;stroke-width:1;}"
            ".gx{font-size:10px;fill:#6b7280;}"
            ".base{stroke:#9ca3af;stroke-width:1;stroke-dasharray:4 3;}"
            ".ct{font-size:13px;font-weight:600;color:#111827;margin:6px 0 2px;}"
            ".chart{margin:10px 0;}"
        )

        parts: list[str] = []
        parts.append("<!doctype html><html lang='zh'><head><meta charset='utf-8'>")
        parts.append("<title>AROS 研究实验报告</title><style>" + css + "</style></head><body>")
        parts.append("<h1>AROS 研究实验报告</h1>")
        parts.append("<div class='meta'>")
        parts.append(f"<p><b>实验 ID:</b> {esc(self.run_id)}</p>")
        parts.append(
            f"<p><b>名称:</b> {esc(self.name)} &nbsp; " f"<b>状态:</b> {esc(self.status)}</p>"
        )
        parts.append(
            f"<p><b>策略:</b> {esc(self.strategy)} &nbsp; "
            f"<b>区间:</b> {esc(self.start)} ~ {esc(self.end)}</p>"
        )
        parts.append(
            f"<p><b>基准:</b> {esc(self.benchmark)} &nbsp; "
            f"<b>样本外(OOS):</b> {'是' if self.is_oos else '否'}"
        )
        if self.walk_forward is not None:
            parts.append(f" &nbsp; <b>Walk-forward:</b> {esc(self.walk_forward)}")
        parts.append("</p>")
        parts.append(f"<p><b>生成时间:</b> {esc(self.generated_at)}</p>")
        parts.append("</div>")

        if self.is_oos:
            parts.append("<h2>一、IS vs OOS 指标对比</h2>")
            is_m = self.metrics.get("is_agg", {})
            oos_m = self.metrics.get("oos_agg", {})
            keys = self._ordered_keys(_PORTFOLIO_KEYS, _BENCH_KEYS)
            parts.append(
                "<table><tr><th>指标</th><th>样本内(IS)</th>"
                "<th>样本外(OOS)</th><th>衰减(IS-OOS)</th></tr>"
            )
            for k in keys:
                iv = is_m.get(k)
                ov = oos_m.get(k)
                decay = "-" if (iv is None or ov is None) else f"{iv - ov:.4f}"
                parts.append(
                    f"<tr><td>{esc(_METRIC_LABELS.get(k, k))}</td>"
                    f"<td>{esc(_fmt(iv))}</td><td>{esc(_fmt(ov))}</td>"
                    f"<td>{esc(decay)}</td></tr>"
                )
            parts.append("</table>")
            parts.append(self._svg_is_oos(is_m, oos_m, keys))
        else:
            parts.append("<h2>一、指标汇总</h2>")
            summ = self.metrics.get(self._summary_window() or "", {})
            if summ:
                parts.append("<table><tr><th>指标</th><th>值</th></tr>")
                for k, v in summ.items():
                    parts.append(
                        f"<tr><td>{esc(_METRIC_LABELS.get(k, k))}</td>"
                        f"<td>{esc(_fmt(v))}</td></tr>"
                    )
                parts.append("</table>")
            else:
                parts.append("<p>无指标数据。</p>")

        parts.append("<h2>二、全部窗口明细</h2>")
        for w in self.windows:
            m = self.metrics.get(w, {})
            if not m:
                continue
            tag = " (OOS)" if _is_oos_window(w) else ""
            parts.append(f"<h3>窗口 {esc(w)}{esc(tag)}</h3>")
            parts.append("<table><tr><th>指标</th><th>值</th></tr>")
            for k, v in m.items():
                parts.append(
                    f"<tr><td>{esc(_METRIC_LABELS.get(k, k))}</td>" f"<td>{esc(_fmt(v))}</td></tr>"
                )
            parts.append("</table>")

        if self.equity:
            parts.append("<h2>三、净值曲线与回撤曲线</h2>")
            for w, eq in self.equity.items():
                if not eq or len(eq) < 2:
                    continue
                tag = " (OOS)" if _is_oos_window(w) else ""
                wlabel = f"窗口 {esc(w)}{esc(tag)}"
                parts.append(f"<div class='chart'><div class='ct'>{wlabel} · 净值</div>")
                parts.append(_svg_equity(w, eq))
                parts.append(f"<div class='ct'>{wlabel} · 回撤</div>")
                parts.append(_svg_drawdown(w, eq))
                parts.append("</div>")

        parts.append("</body></html>")
        return "\n".join(parts)

    @staticmethod
    def _svg_is_oos(
        is_m: Mapping[str, float | None],
        oos_m: Mapping[str, float | None],
        keys: list[str],
    ) -> str:
        """Inline SVG diverging bar chart: IS (blue) vs OOS (orange) per metric.

        Self-contained and offline (no external resources). Bars share a signed
        axis so IS/OOS magnitudes are visually comparable even for negatives.
        """
        plotted = [k for k in keys if is_m.get(k) is not None or oos_m.get(k) is not None]
        if not plotted:
            return ""
        vals = [v for k in plotted for v in (is_m.get(k), oos_m.get(k)) if v is not None]
        lo, hi = min(vals), max(vals)
        maxabs = max(abs(lo), abs(hi)) or 1.0

        gutter = 130.0
        chart_w = 360.0
        zero_x = gutter + chart_w / 2.0
        half = chart_w / 2.0 - 12.0
        row_h = 40.0
        chart_h = row_h * len(plotted) + 8.0

        def bx(v: float) -> float:
            return zero_x + (v / maxabs) * half

        rows: list[str] = []
        for i, k in enumerate(plotted):
            y = i * row_h + 6.0
            label = _METRIC_LABELS.get(k, k)
            rows.append(f'<text x="0" y="{y + 14:.1f}" class="bl">{label}</text>')
            iv = is_m.get(k)
            if iv is not None:
                x1 = bx(iv)
                x = min(zero_x, x1)
                w = abs(x1 - zero_x)
                rows.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="13" '
                    f'rx="2" class="bar-is"/>'
                )
                rows.append(
                    f'<text x="{x1 + 4:.1f}" y="{y + 11:.1f}" class="bv">' f"{iv:.4f}</text>"
                )
            ov = oos_m.get(k)
            if ov is not None:
                y2 = y + 17.0
                x1 = bx(ov)
                x = min(zero_x, x1)
                w = abs(x1 - zero_x)
                rows.append(
                    f'<rect x="{x:.1f}" y="{y2:.1f}" width="{w:.1f}" height="13" '
                    f'rx="2" class="bar-oos"/>'
                )
                rows.append(
                    f'<text x="{x1 + 4:.1f}" y="{y2 + 11:.1f}" class="bv">' f"{ov:.4f}</text>"
                )
        svg = (
            f'<svg width="{zero_x + half + 70:.0f}" height="{chart_h:.0f}" '
            f'viewBox="0 0 {zero_x + half + 70:.0f} {chart_h:.0f}" '
            f'role="img" aria-label="IS vs OOS">'
            f'<line x1="{zero_x:.1f}" y1="0" x2="{zero_x:.1f}" y2="{chart_h:.1f}" '
            f'class="zero"/>' + "".join(rows) + "</svg>"
        )
        return "<div>" + svg + "</div>"


def render_experiment_report(result: ExperimentResult) -> str:
    """Render an experiment result to a markdown report (stub-era entry point).

    Kept for backward compatibility with the 2.0 stub contract; the full CLI path
    uses :meth:`ResearchReport.from_run` so it can include run metadata (name,
    status, config). When only an in-memory result is available, this falls back
    to :meth:`ResearchReport.from_result`.
    """
    return ResearchReport.from_result(result).to_markdown()
