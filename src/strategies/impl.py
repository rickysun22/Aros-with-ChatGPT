"""Concrete A-share short-term strategies.

Two strategy *types* ship with Sprint 1.5:

* weighted -- normalise each factor column to [-1, 1], form a weighted
  composite score, then map the score to a signal via buy/sell thresholds.
* rule -- combine boolean factor conditions (all = AND, any = OR) into a
  single long/flat signal.

Both read their inputs by name from the frame: a strategy references the
factor output column (e.g. ma_dist_20) produced by the factor layer. If a
referenced column is missing (misconfigured strategies vs factors),
DataError is raised so the mismatch is caught immediately.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from core.exceptions import ConfigError, DataError

from .base import BaseStrategy, register


def _normalize(series: pd.Series, clip: tuple[float, float] | None) -> pd.Series:
    """Map series into [-1, 1]. Without clip the series is assumed already
    bounded in [-1, 1] (e.g. crossover signals); with clip=(lo, hi) the series
    is clamped then linearly mapped onto [-1, 1]."""
    if clip is None:
        return series.astype(float)
    lo, hi = float(clip[0]), float(clip[1])
    if hi == lo:
        return pd.Series(0.0, index=series.index)
    clamped = series.clip(lower=lo, upper=hi)
    return (clamped - lo) / (hi - lo) * 2.0 - 1.0


_OPS: dict[str, Callable[[pd.Series, float], pd.Series]] = {
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
}


def _require(df: pd.DataFrame, col: str, strategy_name: str) -> None:
    """Raise DataError if col is absent from df."""
    if col not in df.columns:
        raise DataError(f"Strategy {strategy_name!r} requires factor column {col!r}")


@register("weighted")
class WeightedStrategy(BaseStrategy):
    """Weighted composite of normalised factor columns -> scored signal."""

    name = "weighted"

    def _columns(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        weights = self.params.get("weights") or []
        if not weights:
            raise ConfigError("weighted strategy requires a non-empty 'weights' list")
        score = pd.Series(0.0, index=df.index)
        total = 0.0
        for w in weights:
            factor = w["factor"]
            weight = float(w["weight"])
            clip = w.get("clip")
            _require(df, factor, self.instance_name)
            norm = _normalize(df[factor], tuple(clip) if clip is not None else None)
            score = score + weight * norm
            total += abs(weight)
        if total > 0:
            score = score / total
        buy = float(self.params.get("buy_threshold", 0.30))
        sell = float(self.params.get("sell_threshold", -0.30))
        signal = (score > buy).astype(int) - (score < sell).astype(int)
        return {
            f"score_{self.instance_name}": score,
            f"signal_{self.instance_name}": signal,
        }


@register("rule")
class RuleStrategy(BaseStrategy):
    """Boolean combination of factor conditions -> long/flat signal."""

    name = "rule"

    def _columns(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        conditions = self.params.get("conditions") or []
        if not conditions:
            raise ConfigError("rule strategy requires a non-empty 'conditions' list")
        combine = self.params.get("combine", "all")
        masks: list[pd.Series] = []
        for c in conditions:
            factor = c["factor"]
            op = c["op"]
            value = float(c["value"])
            _require(df, factor, self.instance_name)
            if op not in _OPS:
                raise ConfigError(f"rule strategy: unknown operator {op!r}")
            masks.append(_OPS[op](df[factor], value))
        if combine == "all":
            satisfied = masks[0]
            for m in masks[1:]:
                satisfied = satisfied & m
        elif combine == "any":
            satisfied = masks[0]
            for m in masks[1:]:
                satisfied = satisfied | m
        else:
            raise ConfigError(f"rule strategy: combine must be 'all' or 'any', got {combine!r}")
        signal = satisfied.astype(int)
        return {
            f"score_{self.instance_name}": signal.astype(float),
            f"signal_{self.instance_name}": signal,
        }
