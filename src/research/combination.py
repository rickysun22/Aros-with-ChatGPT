"""Cross-strategy combination by market environment (Sprint 3.4).

Combines the top-ranked Phase 3 research strategies into a regime-conditioned
allocation. Rather than a single static blend, the weight on each strategy is
recomputed *per market environment* (trending vs oscillating), tilting toward
the categories / regimes that actually performed there -- so the combined book
is better adapted to the regime it is trading.

Key design points (all per Phase 3 design §3.4):

* **Selection.** The combined book is built from the Top-N strategies by the
  3.3 AROS Strategy Score (passed in as a :class:`~research.ranking.RankingReport`
  or recomputed from the :class:`~research.batch.BatchResult`).
* **Per-environment weights.** For each environment bucket we compute a raw
  weight = base + category-fit bonus + regime-performance tilt, floor it at
  ``equal_weight_floor`` (so no selected strategy is ever dropped), then
  normalise so the bucket sums to 1.0. The "weights normalise" test pins this.
* **Combined metrics reuse existing metrics.** The combined per-environment
  metrics are a *weighted blend* of the selected strategies' already-computed
  OOS metrics (produced by :func:`backtest.metrics.compute_metrics` during the
  3.2 batch run) -- never recomputed, never re-invented. Non-finite values
  (e.g. ``profit_factor`` on a zero-loss backtest) are dropped like missing
  data so they cannot poison the blend with ``inf``/``nan``.
* **Illustrative combined equity.** A synthetic equity curve is reconstructed
  from the blended total return *for visualisation only*; it is clearly labelled
  and is NOT used to derive any combined metric (a smooth curve would otherwise
  fake away real volatility / drawdown).
* **No black box.** Weights come from explainable category / regime tilts; the
  engine is a pure function of its inputs so the "combined metrics reproducible"
  test holds.

The :class:`CombinationEngine` is the bridge 3.5's Market Regime Engine consumes:
given a live regime label, :func:`env_for_regime` maps it to an environment and
``CombinedResult.weights_for`` returns the allocation to trade.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from core.config import CombinationConfig, get_config
from research.batch import BatchResult, StrategyBatchOutcome
from research.ranking import RankingReport
from research.scorecard import Scorecard

# Market-environment buckets.
MarketEnv = str
TRENDING: MarketEnv = "trending"
OSCILLATING: MarketEnv = "oscillating"
ENVS: Sequence[MarketEnv] = (TRENDING, OSCILLATING)

_ENV_LABELS: Mapping[MarketEnv, str] = {
    TRENDING: "趋势市",
    OSCILLATING: "震荡市",
}

_SYNTHETIC_PERIODS = 252  # ~1 trading year, illustrative only
_SYNTHETIC_END = "2026-06-30"


def env_for_regime(regime: str, config: CombinationConfig | None = None) -> MarketEnv:
    """Map a 3.2 regime label (Bull/Bear/Neutral/Extreme) to a 3.4 environment bucket.

    Trending regimes (``Bull``/``Bear``) -> :data:`TRENDING`; everything else ->
    :data:`OSCILLATING`. Mapping is config-driven via
    :class:`~core.config.CombinationConfig`.
    """
    cfg = config or get_config().research.combination
    if regime in cfg.trending_regimes:
        return TRENDING
    return OSCILLATING


def _regime_tilt(o: StrategyBatchOutcome, env: MarketEnv, cfg: CombinationConfig) -> float:
    """Extra raw weight from how the strategy performed in ``env``'s regimes.

    Reads the per-regime breakdown 3.2 already produced (``regime_breakdown``):
    the mean total return across the bucket's regimes, clamped, scaled by
    ``perf_weight``. Returns 0.0 when no regime data is available (falls back to
    the category-fit base weight).
    """
    regs = cfg.trending_regimes if env == TRENDING else cfg.oscillating_regimes
    bd = o.regime_breakdown or {}
    rets: list[float] = []
    for r in regs:
        cell = bd.get(r)
        if cell and cell.get("total_return") is not None:
            v = float(cell["total_return"])
            if math.isfinite(v):
                rets.append(v)
    if not rets:
        return 0.0
    avg = sum(rets) / len(rets)
    avg = max(-cfg.perf_cap, min(cfg.perf_cap, avg))
    return cfg.perf_weight * avg


def _env_weights(
    selected: Sequence[StrategyBatchOutcome], env: MarketEnv, cfg: CombinationConfig
) -> dict[str, float]:
    """Raw -> floored -> normalised weights for one environment bucket."""
    raw: dict[str, float] = {}
    for o in selected:
        r = 1.0
        if env == TRENDING and o.category in cfg.trending_bias_category:
            r += cfg.category_bias
        elif env == OSCILLATING and o.category in cfg.oscillating_bias_category:
            r += cfg.category_bias
        r += _regime_tilt(o, env, cfg)
        raw[o.name] = max(cfg.equal_weight_floor, r)
    total = sum(raw.values())
    if total <= 0:
        # Defensive: should never happen (floor > 0), but keep weights finite.
        n = len(raw)
        return {k: 1.0 / n for k in raw}
    return {k: w / total for k, w in raw.items()}


def _blend_metrics(
    selected: Sequence[StrategyBatchOutcome], weights: Mapping[str, float]
) -> dict[str, float]:
    """Weighted-blend the selected strategies' OOS metrics (reuses existing metrics).

    For each metric key present across the selected outcomes, combine the finite
    values with the (already normalised) bucket weights. Missing / non-finite
    values for a strategy simply drop out of that key's blend, with the remaining
    weights renormalised for the key.
    """
    # Union of all metric keys seen on the selected OOS maps.
    keys: set[str] = set()
    for o in selected:
        if o.oos_metrics:
            keys.update(o.oos_metrics.keys())

    out: dict[str, float] = {}
    for key in sorted(keys):
        vals: list[float] = []
        ws: list[float] = []
        for o in selected:
            v = o.oos_metrics.get(key) if o.oos_metrics else None
            w = weights.get(o.name, 0.0)
            if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)) and w > 0:
                vals.append(float(v))
                ws.append(w)
        if not vals:
            continue
        wsum = sum(ws)
        if wsum <= 0:
            continue
        out[key] = sum(v * w for v, w in zip(vals, ws, strict=True)) / wsum
    return out


def _synthetic_equity(total_return: float | None) -> dict[str, float] | None:
    """Reconstruct an illustrative combined equity curve from a blended total return.

    Purely for visualisation: a smooth daily-compounded curve over
    ``_SYNTHETIC_PERIODS`` business days. NOT used to derive any combined metric.
    """
    if total_return is None or not math.isfinite(total_return):
        return None
    daily = (1.0 + total_return) ** (1.0 / _SYNTHETIC_PERIODS) - 1.0
    idx = pd.bdate_range(end=_SYNTHETIC_END, periods=_SYNTHETIC_PERIODS)
    eq = np.power(1.0 + daily, np.arange(_SYNTHETIC_PERIODS, dtype=float))
    return {pd.Timestamp(ts).strftime("%Y-%m-%d"): float(v) for ts, v in zip(idx, eq, strict=True)}


@dataclass
class CombinedResult:
    """Regime-conditioned combination of the Top-N strategies.

    ``weights`` and ``combined_metrics`` are keyed by environment bucket
    (:data:`TRENDING` / :data:`OSCILLATING`). ``combined_equity`` is the
    illustrative reconstructed curve per environment (see :func:`_synthetic_equity`).
    """

    config_name: str
    selected: list[str]
    scores: dict[str, float]
    weights: dict[str, dict[str, float]] = field(default_factory=dict)
    combined_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    combined_equity: dict[str, dict[str, float] | None] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def weights_for(self, env: MarketEnv) -> dict[str, float]:
        """Return the (normalised) weight map for one environment bucket."""
        return dict(self.weights.get(env, {}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json

        return json.dumps(
            {
                "config_name": self.config_name,
                "generated_at": self.generated_at,
                "selected": self.selected,
                "scores": self.scores,
                "weights": self.weights,
                "combined_metrics": self.combined_metrics,
            },
            ensure_ascii=False,
            indent=indent,
        )

    def to_markdown(self) -> str:
        def pct(v: float | None) -> str:
            return "-" if v is None else f"{v * 100:.1f}%"

        def f4(v: float | None) -> str:
            return "-" if v is None else f"{v:.4f}"

        lines: list[str] = []
        lines.append("# AROS 策略组合配权报告")
        lines.append("")
        lines.append(f"- 实验配置: {self.config_name}")
        lines.append(f"- 组合策略数: {len(self.selected)}")
        lines.append(f"- 生成时间: {self.generated_at}")
        lines.append("")
        for env in ENVS:
            wmap = self.weights.get(env)
            if not wmap:
                continue
            m = self.combined_metrics.get(env, {})
            lines.append(f"## {_ENV_LABELS.get(env, env)}（组合权重与指标）")
            lines.append("")
            lines.append("| 策略 | 权重 |")
            lines.append("| --- | --- |")
            for name, w in wmap.items():
                lines.append(f"| {name} | {w * 100:.1f}% |")
            lines.append("")
            lines.append(
                f"- 组合收益(OOS): {pct(m.get('total_return'))} ｜ "
                f"胜率: {pct(m.get('win_rate'))} ｜ "
                f"回撤: {pct(m.get('max_drawdown'))} ｜ "
                f"夏普: {f4(m.get('sharpe'))} ｜ "
                f"盈亏比: {f4(m.get('profit_factor'))}"
            )
            lines.append("")
        lines.append(
            "> 组合权重按市场环境（趋势市=Bull+Bear，震荡市=Neutral+Extreme）分别归一化；"
            "组合指标为各策略样本外(OOS)指标的加权混合，复用既有回测指标，非重新计算。"
            "合成净值为示意曲线，不用于派生指标。"
        )
        return "\n".join(lines)


class CombinationEngine:
    """Combine the Top-N AROS strategies into a regime-conditioned allocation."""

    def __init__(self, config: CombinationConfig | None = None) -> None:
        self._cfg = config or get_config().research.combination

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def combine(
        self,
        batch: BatchResult,
        ranking: RankingReport | None = None,
        scorecard: Scorecard | None = None,
        config: CombinationConfig | None = None,
    ) -> CombinedResult:
        """Build the regime-conditioned combination from a batch experiment.

        ``ranking`` lets the caller pass a pre-built 3.3 ranking (so the ordering
        is shared with the report); otherwise it is recomputed from ``batch``.
        ``config`` overrides the engine's :class:`CombinationConfig`.
        """
        cfg = config or self._cfg
        rank = ranking or RankingReport.from_batch(batch, scorecard=scorecard)

        selected_details = rank.details[: max(0, cfg.top_n)]
        by_name = {o.name: o for o in batch.outcomes}
        selected = [by_name[d["name"]] for d in selected_details if d["name"] in by_name]
        scores = {d["name"]: float(d["score"]) for d in selected_details}

        weights: dict[str, dict[str, float]] = {}
        combined_metrics: dict[str, dict[str, float]] = {}
        combined_equity: dict[str, dict[str, float] | None] = {}
        for env in ENVS:
            wmap = _env_weights(selected, env, cfg)
            weights[env] = wmap
            blended = _blend_metrics(selected, wmap)
            combined_metrics[env] = blended
            combined_equity[env] = _synthetic_equity(blended.get("total_return"))

        return CombinedResult(
            config_name=batch.config_name,
            selected=[o.name for o in selected],
            scores=scores,
            weights=weights,
            combined_metrics=combined_metrics,
            combined_equity=combined_equity,
        )


def render_combination_report(
    batch: BatchResult,
    ranking: RankingReport | None = None,
    scorecard: Scorecard | None = None,
    config: CombinationConfig | None = None,
) -> str:
    """Render a batch's regime-conditioned combination to markdown (entry point)."""
    return (
        CombinationEngine(config=config)
        .combine(batch, ranking=ranking, scorecard=scorecard)
        .to_markdown()
    )
