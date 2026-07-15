"""Backtest Engine for AROS (Sprint 1.6).

Public surface:
* BacktestEngine - simulate a strategy signal as a cost-aware A-share portfolio.
* CostModel - A-share transaction cost model (commission / stamp / transfer / slippage).
* compute_metrics - pure-function performance metrics.
* BacktestCache - cached single-code backtest result (Sprint 1.12).
"""

from .cache import BacktestCache
from .cost import CostModel
from .engine import BacktestEngine
from .metrics import compute_metrics

__all__ = [
    "BacktestEngine",
    "CostModel",
    "compute_metrics",
    "BacktestCache",
]
