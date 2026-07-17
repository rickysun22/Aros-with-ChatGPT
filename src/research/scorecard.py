"""AROS Strategy Score (Sprint 3.0 skeleton, completed in 3.3).

The score ranks Phase 3 strategies on a single 0-100 scale by cross-sectionally
normalising the *realised* metric keys (no new metric math -- see Phase 3
design §4). It is a pure function of a list of :class:`ScoreInput`, so it is
fully reproducible and unit-test-anchored.

Frozen algorithm (E1-E5):
  E1 -- cross-sectional min-max normalisation to [0, 1]; reverse (``down``)
        indicators are negated first (``max_drawdown`` is taken in absolute
        value before reversal).
  E2 -- weighted sum: ``score = sum(weight_i * norm_i) * 100`` -> 0..100.
  E3 -- stability penalty: when the OOS Sharpe decays more than
        ``oos_decay_threshold`` vs the IS Sharpe, the stability (``sharpe``)
        dimension is discounted -- the anti-overfit guard.
  E4 -- pure function of inputs, hand-anchor tested.
  E5 -- weights/configurable via ``config/settings.yaml`` ``research.scorecard``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Default 7-dimension weights (sum = 1.0). Overridable via settings.yaml (E5).
DEFAULT_WEIGHTS: dict[str, float] = {
    "total_return": 0.20,
    "cagr": 0.15,
    "win_rate": 0.20,
    "max_drawdown": 0.20,
    "profit_factor": 0.10,
    "sharpe": 0.10,
    "holding_experience": 0.05,
}

# Per-metric normalisation metadata: (direction, transform).
#   direction "up"   -> larger value is better
#   direction "down" -> smaller value is better (max_drawdown uses abs transform)
_METRIC_META: dict[str, tuple[str, str | None]] = {
    "total_return": ("up", None),
    "cagr": ("up", None),
    "win_rate": ("up", None),
    "max_drawdown": ("down", "abs"),
    "profit_factor": ("up", None),
    "sharpe": ("up", None),
}
# Holding-experience dimension combines two "down" metrics (averaged after norm).
_HOLDING_METRICS: list[str] = ["avg_holding_days", "max_consecutive_losses"]


@dataclass
class ScoreInput:
    """One strategy's metrics for scoring.

    ``metrics`` are the values scored (typically OOS/walk-forward metrics).
    ``is_metrics`` / ``oos_metrics`` enable the E3 OOS-decay penalty on the
    Sharpe dimension.
    """

    name: str
    metrics: dict[str, float]
    is_metrics: dict[str, float] | None = None
    oos_metrics: dict[str, float] | None = None


@dataclass
class ScoreRow:
    """A scored + ranked strategy."""

    name: str
    score: float
    components: dict[str, float] = field(default_factory=dict)
    rank: int = 0


class Scorecard:
    """Pure-function AROS Strategy Score calculator."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        *,
        oos_decay_penalty: bool = True,
        oos_decay_threshold: float = 0.5,
    ) -> None:
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)
        self.oos_decay_penalty = oos_decay_penalty
        self.oos_decay_threshold = float(oos_decay_threshold)

    @classmethod
    def from_config(cls, cfg: Any) -> Scorecard:
        """Build from a :class:`core.config.ScorecardConfig`."""
        return cls(
            weights=dict(cfg.weights),
            oos_decay_penalty=cfg.oos_decay_penalty,
            oos_decay_threshold=cfg.oos_decay_threshold,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def score(self, items: list[ScoreInput]) -> list[ScoreRow]:
        """Return a :class:`ScoreRow` per item with ``rank`` assigned."""
        if not items:
            return []
        total = len(items)

        norm: dict[str, list[float]] = {}
        for key, (direction, transform) in _METRIC_META.items():
            vals = [it.metrics.get(key, 0.0) for it in items]
            norm[key] = self._normalize(vals, direction, transform)

        hold_norms = [
            self._normalize([it.metrics.get(k, 0.0) for it in items], "down", None)
            for k in _HOLDING_METRICS
        ]
        norm["holding_experience"] = [
            (hold_norms[0][i] + hold_norms[1][i]) / 2.0 for i in range(total)
        ]

        rows: list[ScoreRow] = []
        for i, it in enumerate(items):
            comp: dict[str, float] = {}
            weighted = 0.0
            for dim, w in self.weights.items():
                nv = norm[dim][i]
                if dim == "sharpe" and self.oos_decay_penalty and it.is_metrics and it.oos_metrics:
                    decay = self._sharpe_decay(it.is_metrics, it.oos_metrics)
                    if decay > self.oos_decay_threshold:
                        factor = max(0.0, 1.0 - (decay - self.oos_decay_threshold) * 2.0)
                        nv = nv * factor
                comp[dim] = nv
                weighted += w * nv
            rows.append(ScoreRow(name=it.name, score=weighted * 100.0, components=comp))

        for rank, idx in enumerate(
            sorted(range(total), key=lambda j: rows[j].score, reverse=True), start=1
        ):
            rows[idx].rank = rank
        return rows

    def rank(self, items: list[ScoreInput]) -> list[ScoreRow]:
        """Like :meth:`score` but returns rows sorted by score descending."""
        return sorted(self.score(items), key=lambda r: r.score, reverse=True)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize(values: list[float], direction: str, transform: str | None) -> list[float]:
        vv = [abs(x) for x in values] if transform == "abs" else list(values)
        lo, hi = min(vv), max(vv)
        if hi == lo:
            return [0.5 for _ in vv]  # no cross-sectional spread -> neutral
        if direction == "up":
            return [(x - lo) / (hi - lo) for x in vv]
        return [(hi - x) / (hi - lo) for x in vv]  # down: smaller value better

    @staticmethod
    def _sharpe_decay(is_m: dict[str, float], oos_m: dict[str, float]) -> float:
        is_s = is_m.get("sharpe", 0.0)
        oos_s = oos_m.get("sharpe", 0.0)
        if is_s is None or oos_s is None or is_s <= 0:
            return 0.0
        return max(0.0, (is_s - oos_s) / is_s)
