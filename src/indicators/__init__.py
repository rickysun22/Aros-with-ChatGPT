"""Indicator Engine for AROS.

Public surface:
* :class:`IndicatorEngine` - orchestrates the configured indicators.
* :class:`BaseIndicator` - base class for implementing new indicators.
* :func:`register` / :func:`build` / :func:`available` - registry helpers.
"""

from .base import BaseIndicator, available, build, register
from .engine import IndicatorEngine

__all__ = [
    "BaseIndicator",
    "IndicatorEngine",
    "available",
    "build",
    "register",
]
