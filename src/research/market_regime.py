"""Market Regime Engine (Sprint 3.5).

A transparent, rule-based market-regime tagger that powers *dynamic strategy
selection* -- the last piece of Phase 3. The classifier emits five explainable
labels:

* ``Bull``        -- index rising, calm realised vol, no sentiment frenzy.
* ``Neutral``     -- no clear trend / elevated vol / ambiguous.
* ``Bear``        -- index falling.
* ``EmotionHot``  -- market-wide sentiment frenzy (net limit-up breadth hot).
* ``EmotionCold`` -- sentiment capitulation (net limit-up breadth frozen).

The rules use only **explainable** statistics of a benchmark close series (trend
/ momentum, realised volatility) plus an *optional* market-breadth sentiment
series (net limit-up ratio) -- never a black-box model -- so the Phase 3
"no AI prediction" red line stays intact. ``EmotionHot`` / ``EmotionCold`` only
fire when a breadth series is supplied; without it the output collapses to the
trend/vol labels (Bull / Neutral / Bear), keeping the function deterministic and
testable on price-only data.

No look-ahead: every signal at date ``t`` uses only data ``<= t`` (rolling
windows with ``min_periods`` and causal rolling means), so a tag can never
depend on the future. The :class:`MarketRegimeEngine` then maps the live regime
to the best-fit strategy from a :class:`~research.batch.BatchResult`, combining
an *explainable* category-fit rule with the *empirical* per-regime walk-forward
(OOS) performance the 3.2 batch already produced.

The engine is the bridge the V1.0 :class:`~research.final_report.FinalReport`
consumes: given a live regime label it returns the strategy to trade.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from core.config import MarketRegimeConfig, get_config
from research.batch import BatchResult
from research.ranking import RankingReport
from research.scorecard import Scorecard

# Five market-regime labels (ordered by design §3.5).
Regime = str
BULL: Regime = "Bull"
NEUTRAL: Regime = "Neutral"
BEAR: Regime = "Bear"
EMOTION_HOT: Regime = "EmotionHot"
EMOTION_COLD: Regime = "EmotionCold"

REGIMES_5: Sequence[Regime] = (BULL, NEUTRAL, BEAR, EMOTION_HOT, EMOTION_COLD)

# Human labels for the report layer.
REGIME_LABELS: Mapping[Regime, str] = {
    BULL: "牛市(趋势上行)",
    NEUTRAL: "震荡市(无趋势)",
    BEAR: "熊市(趋势下行)",
    EMOTION_HOT: "情绪高涨(题材炒作)",
    EMOTION_COLD: "情绪冰点(恐慌冰点)",
}

# Explainable category fit: which strategy categories suit each regime. This is
# the *primary* (non-empirical) driver of selection; it encodes the domain rule
# "trend strategies in up-markets, reversal/emotion strategies at extremes".
REGIME_CATEGORY_FIT: Mapping[Regime, tuple[str, ...]] = {
    BULL: ("trend", "strong"),
    NEUTRAL: ("strong", "trend"),
    BEAR: ("strong", "emotion"),
    EMOTION_HOT: ("emotion", "strong"),
    EMOTION_COLD: ("emotion",),
}

# Map a 5-label regime to the 3.2 backtest regime bucket used by
# ``StrategyBatchOutcome.regime_breakdown``. Emotion labels have no
# breadth-segmented backtest in V1.0, so they fall back to the trend-aligned
# bucket for the *empirical* read while selection still leans on category fit.
_REGIME_BACKTEST: Mapping[Regime, str | None] = {
    BULL: "Bull",
    NEUTRAL: "Neutral",
    BEAR: "Bear",
    EMOTION_HOT: "Bull",  # frenzy aligns with an up-market empirically
    EMOTION_COLD: "Bear",
}


def classify_market_regime(
    benchmark_close: pd.Series,
    breadth: pd.Series | None = None,
    config: MarketRegimeConfig | None = None,
) -> pd.Series:
    """Tag each date of ``benchmark_close`` with a 5-label market regime.

    Args:
        benchmark_close: index level series (MA structure + volatility).
        breadth: optional net sentiment series (e.g. (limit_up - limit_down) /
            total); required to detect ``EmotionHot`` / ``EmotionCold``. When
            ``None`` those two labels never fire and the output collapses to
            Bull / Neutral / Bear.
        config: optional :class:`~core.config.MarketRegimeConfig` override.

    Returns:
        A :class:`pandas.Series` of :data:`REGIMES_5` strings, indexed
        identically to ``benchmark_close``. Any ``NaN`` prices are dropped first
        so they do not poison the rolling windows, then reindexed back.
    """
    cfg = config or get_config().research.market_regime
    s = benchmark_close.dropna()
    if s.empty:
        return pd.Series(dtype="object", index=benchmark_close.index)

    mom = s.pct_change(cfg.momentum_window)
    daily_ret = s.pct_change().fillna(0.0)
    ann_vol = daily_ret.rolling(cfg.vol_window, min_periods=cfg.vol_window).std() * (252**0.5)

    # Causal smoothed sentiment; None when no breadth was supplied.
    sent: pd.Series | None = None
    if breadth is not None:
        b = breadth.reindex(s.index)
        if b.notna().any():
            sent = b.rolling(cfg.sentiment_window, min_periods=cfg.sentiment_window).mean()

    labels: list[Regime] = []
    n = len(s)
    for i in range(n):
        if i + 1 < cfg.vol_window:
            # Not enough history yet -- default to neutral until vol is known.
            labels.append(NEUTRAL)
            continue
        # 1-2. Sentiment extremes take priority (market-wide frenzy / capitulation).
        if sent is not None and pd.notna(sent.iloc[i]):
            sv = float(sent.iloc[i])
            if sv >= cfg.emotion_hot_threshold:
                labels.append(EMOTION_HOT)
                continue
            if sv <= cfg.emotion_cold_threshold:
                labels.append(EMOTION_COLD)
                continue
        # 3-5. Trend + volatility (no breadth extreme).
        m = float(mom.iloc[i])
        v = float(ann_vol.iloc[i])
        if m > cfg.bull_mom and v <= cfg.high_vol_cap:
            labels.append(BULL)
        elif m < cfg.bear_mom:
            labels.append(BEAR)
        else:
            labels.append(NEUTRAL)

    out = pd.Series(labels, index=s.index, dtype="object")
    return out.reindex(benchmark_close.index, fill_value=NEUTRAL)


def _regime_counts(labels: pd.Series) -> dict[str, int]:
    """Count occurrences of each of the 5 labels (missing -> 0)."""
    counts: dict[str, int] = {r: 0 for r in REGIMES_5}
    for v in labels.tolist():
        if v in counts:
            counts[v] += 1
    return counts


@dataclass
class SelectionResult:
    """The strategy the engine recommends for one regime, with its rationale."""

    regime: Regime
    strategy: str
    display_name: str
    category: str
    engine: str
    data_fidelity: str
    score: float | None = None  # AROS Strategy Score (0-100)
    regime_return: float | None = None  # empirical regime-bucket OOS return, if any
    basis: str = ""  # explainable reason string
    alternatives: list[dict[str, Any]] = field(default_factory=list)  # top-3 candidates

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketRegimeEngine:
    """Map a live market regime to the best-fit Phase 3 strategy."""

    def __init__(self, config: MarketRegimeConfig | None = None) -> None:
        self._cfg = config or get_config().research.market_regime

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #
    def classify(
        self,
        benchmark_close: pd.Series,
        breadth: pd.Series | None = None,
        config: MarketRegimeConfig | None = None,
    ) -> pd.Series:
        """Classify a benchmark series into the 5-label regime time series."""
        return classify_market_regime(benchmark_close, breadth=breadth, config=config or self._cfg)

    def current_regime(
        self, benchmark_close: pd.Series, breadth: pd.Series | None = None
    ) -> Regime:
        """Return the latest regime label of a benchmark series."""
        labels = self.classify(benchmark_close, breadth=breadth)
        if labels.empty:
            return NEUTRAL
        return Regime(labels.iloc[-1])

    # ------------------------------------------------------------------ #
    # Dynamic strategy selection
    # ------------------------------------------------------------------ #
    def select_strategy(
        self,
        regime: Regime,
        batch: BatchResult,
        ranking: RankingReport | None = None,
        scorecard: Scorecard | None = None,
    ) -> SelectionResult:
        """Recommend the best-fit strategy for ``regime`` from a batch result.

        Selection signal per candidate:
        * When the regime maps to a 3.2 backtest bucket that has a
          ``regime_breakdown`` cell, use that bucket's mean OOS total return
          (empirical, honest).
        * Otherwise (the Emotion* labels have no breadth-segmented backtest in
          V1.0) fall back to the AROS Strategy Score -- and say so in ``basis``.

        Candidates are first restricted to the regime's explainable
        :data:`REGIME_CATEGORY_FIT`, then ranked by the signal above.
        """
        rank = ranking or RankingReport.from_batch(batch, scorecard=scorecard)
        score_by_name = {d["name"]: float(d["score"]) for d in rank.details}
        cat_by_name = {o.name: o.category for o in batch.outcomes}
        disp_by_name = {o.name: o.display_name for o in batch.outcomes}
        eng_by_name = {o.name: o.engine for o in batch.outcomes}
        fid_by_name = {o.name: o.data_fidelity for o in batch.outcomes}

        bt_regime = _REGIME_BACKTEST.get(regime)
        emp_by_name: dict[str, float] = {}
        if bt_regime:
            for o in batch.outcomes:
                cell = (o.regime_breakdown or {}).get(bt_regime)
                if cell and cell.get("total_return") is not None:
                    v = cell["total_return"]
                    if isinstance(v, (int, float)) and math.isfinite(float(v)):
                        emp_by_name[o.name] = float(v)

        fit = REGIME_CATEGORY_FIT.get(regime, ())
        candidates = [o.name for o in batch.outcomes if o.category in fit]
        if not candidates:
            # Defensive: if no category fits, consider every strategy.
            candidates = [o.name for o in batch.outcomes]

        def signal(name: str) -> float:
            if name in emp_by_name:
                return emp_by_name[name]
            return score_by_name.get(name, 0.0)

        ordered = sorted(candidates, key=lambda nm: signal(nm), reverse=True)
        top = ordered[0]

        basis_parts = [f"类别适配[{','.join(fit) or '-'}]"]
        if top in emp_by_name:
            basis_parts.append(f"该状态样本外收益 {emp_by_name[top]:.2%}")
        else:
            basis_parts.append("情绪状态无独立回测，按 AROS 总评分择优")

        alternatives = [
            {
                "name": nm,
                "display_name": disp_by_name.get(nm, nm),
                "category": cat_by_name.get(nm, ""),
                "score": round(score_by_name.get(nm, 0.0), 4),
                "regime_return": round(emp_by_name[nm], 4) if nm in emp_by_name else None,
            }
            for nm in ordered[:3]
        ]

        return SelectionResult(
            regime=regime,
            strategy=top,
            display_name=disp_by_name.get(top, top),
            category=cat_by_name.get(top, ""),
            engine=eng_by_name.get(top, ""),
            data_fidelity=fid_by_name.get(top, ""),
            score=round(score_by_name.get(top, 0.0), 4),
            regime_return=round(emp_by_name[top], 4) if top in emp_by_name else None,
            basis="；".join(basis_parts),
            alternatives=alternatives,
        )

    def recommendations(
        self,
        batch: BatchResult,
        ranking: RankingReport | None = None,
        scorecard: Scorecard | None = None,
    ) -> dict[Regime, SelectionResult]:
        """Recommend a strategy for *every* one of the 5 regimes."""
        return {
            r: self.select_strategy(r, batch, ranking=ranking, scorecard=scorecard)
            for r in REGIMES_5
        }
