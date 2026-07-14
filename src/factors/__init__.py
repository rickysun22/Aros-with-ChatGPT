"""Factor Engine for AROS.

Public surface:
* :class:`FactorEngine` - orchestrates indicators then factors.
* :class:`BaseFactor` - base class for implementing new factors.
* :func:`register` / :func:`build` / :func:`available` - registry helpers.
"""

from .base import BaseFactor, available, build, register
from .engine import FactorEngine

__all__ = [
    "BaseFactor",
    "FactorEngine",
    "available",
    "build",
    "register",
]
