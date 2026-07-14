"""Strategy Engine for AROS.

Public surface:
* StrategyEngine - orchestrates indicators -> factors -> strategies.
* BaseStrategy - base class for implementing new strategies.
* Portfolio - turns signals into positions and tracks equity.
* SignalType - the LONG / FLAT / SHORT vocabulary.
* register / build / available - registry helpers.
"""

from .base import BaseStrategy, available, build, register
from .engine import StrategyEngine
from .portfolio import Portfolio
from .signal import SignalType, to_position

__all__ = [
    "BaseStrategy",
    "StrategyEngine",
    "Portfolio",
    "SignalType",
    "to_position",
    "available",
    "build",
    "register",
]
