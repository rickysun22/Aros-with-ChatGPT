"""Ranking Engine for AROS (Sprint 1.7).

Public surface:
* RankingEngine - cross-sectional composite-score ranking over candidate stocks.
* ScoreModel - (re-exported for symmetry) the scoring config types live in core.config.
"""

from .engine import RankingEngine

__all__ = [
    "RankingEngine",
]
