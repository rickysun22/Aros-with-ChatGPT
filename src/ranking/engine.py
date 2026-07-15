"""RankingEngine - cross-sectional composite-score ranking (Sprint 1.7).

Composes StrategyEngine (which produces score_<name> columns) and turns the
per-stock scores at a chosen cross-section into a ranked Top-N watch-list.
Ranking is a thin layer over the strategy engine: it adds no new metric math
and inherits the no-look-ahead guarantee from Sprint 1.5.

Sorting semantics (user-confirmed): each candidate stock keeps its strategy
score_<name> at the cross-section date; those scores are combined with
configured weights into a composite; candidates are sorted descending and the
top_n are returned.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from core.config import (
    DimensionSpec,
    FactorConfig,
    IndicatorConfig,
    RankingConfig,
    StrategyConfig,
)
from core.exceptions import DataError
from strategies.engine import StrategyEngine

logger = logging.getLogger(__name__)

SCORE_PREFIX = "score_"


class RankingEngine:
    """Rank candidate stocks by a composite of strategy scores."""

    def __init__(self, strategy_engine: StrategyEngine, config: RankingConfig) -> None:
        self.strategy_engine = strategy_engine
        self.config = config

    @classmethod
    def from_config(
        cls,
        indicators: IndicatorConfig,
        factors: FactorConfig,
        strategies: StrategyConfig,
        ranking: RankingConfig,
    ) -> RankingEngine:
        se = StrategyEngine.from_config(indicators, factors, strategies)
        return cls(se, ranking)

    @property
    def names(self) -> list[str]:
        return self.strategy_engine.names

    # ------------------------------------------------------------------ #
    # Dimension resolution
    # ------------------------------------------------------------------ #
    def _resolve_dimensions(self) -> list[DimensionSpec]:
        if self.config.dimensions:
            return list(self.config.dimensions)
        # default: every configured strategy, equal weight
        return [DimensionSpec(strategy=n, weight=1.0) for n in self.strategy_engine.names]

    # ------------------------------------------------------------------ #
    # Cross-section extraction
    # ------------------------------------------------------------------ #
    def _cross_section(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return one row per code: the as_of (or latest) bar.

        get_daily returns a frame with a ``date`` column and a default integer
        index (no DatetimeIndex), so the as_of filter uses the ``date`` column.
        """
        if self.config.as_of:
            target = pd.Timestamp(self.config.as_of)
            parts: list[pd.DataFrame] = []
            for _, g in df.groupby("code"):
                mask = pd.to_datetime(g["date"]) <= target
                gd = g[mask]
                if not gd.empty:
                    parts.append(gd.iloc[[-1]])
            return pd.concat(parts) if parts else pd.DataFrame()
        # latest bar per code (data is date-ascending from get_daily)
        return df.groupby("code").tail(1)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def rank(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Score and rank a multi-stock frame at the cross-section.

        Returns ``(ranking, scored)`` where ``ranking`` is the Top-N table
        (columns: rank, code, composite_score, score_<name> ...) sorted
        descending by composite score, and ``scored`` is the full cross-section
        (every candidate, every dimension) before the Top-N slice.
        """
        if "code" not in df.columns:
            raise DataError("ranking requires a 'code' column (multi-stock frame)")
        df = self.strategy_engine.compute(df)
        dims = self._resolve_dimensions()
        scored = self._cross_section(df).copy()
        if scored.empty:
            empty_rank = pd.DataFrame(columns=["code", "composite_score", "rank"])
            return empty_rank, scored

        score_cols: dict[str, str] = {}
        for d in dims:
            col = SCORE_PREFIX + d.strategy
            if col not in scored.columns:
                avail = [c for c in scored.columns if c.startswith(SCORE_PREFIX)]
                raise DataError(
                    f"ranking dimension {d.strategy!r} has no score column {col!r}; "
                    f"available score columns: {avail}"
                )
            score_cols[d.strategy] = col

        wsum = sum(abs(d.weight) for d in dims) or 1.0
        composite = pd.Series(0.0, index=scored.index)
        for d in dims:
            col = score_cols[d.strategy]
            composite = composite + (d.weight / wsum) * scored[col].astype(float)
        scored["composite_score"] = composite

        scored = scored.sort_values("composite_score", ascending=False)
        keep = ["code", "composite_score", *score_cols.values()]
        ranking = scored[keep].reset_index(drop=True)
        ranking.insert(0, "rank", range(1, len(ranking) + 1))
        ranking = ranking.head(self.config.top_n)
        return ranking, scored

    def rank_universe(
        self,
        codes: list[str],
        data_manager: Any,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch each code's bars, concat with a code column, then rank."""
        parts: list[pd.DataFrame] = []
        for code in codes:
            g = data_manager.get_daily(code, start_date, end_date)
            if g is None or g.empty:
                logger.warning("ranking: no data for %s, skipped", code)
                continue
            g = g.copy()
            g["code"] = code
            parts.append(g)
        if not parts:
            empty = pd.DataFrame(columns=["code", "composite_score", "rank"])
            return empty, pd.DataFrame()
        df = pd.concat(parts, ignore_index=False)
        return self.rank(df)
