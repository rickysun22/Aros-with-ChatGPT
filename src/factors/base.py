"""Factor base class and registry.

Factors sit one level above indicators: a factor consumes indicator columns
(and/or raw bars) and produces a research signal. Like indicators, every
factor is a **pure, causal function** -- a factor value at bar *t* may only
depend on data at bars ``<= t``. This keeps the project principle
*禁止未来函数* (no future-function leakage) intact, and the test-suite enforces
it with the same truncation test used for indicators.

Factors read their inputs from the frame (indicator columns like ``ma_20`` or
raw ``close``/``volume``); they never reach back to the data source.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from core.exceptions import ConfigError


class BaseFactor:
    """Base class for all factors.

    Subclasses set the class attribute ``name`` (the registry key used in
    configuration) and implement :meth:`_series`, which returns a mapping of
    new column name -> :class:`pandas.Series`. :meth:`compute` appends those
    columns to a copy of the input frame so the original is never mutated.
    """

    name = "base"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = dict(params or {})

    # ------------------------------------------------------------------ #
    # Interface
    # ------------------------------------------------------------------ #
    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Return new factor columns as a name -> Series mapping."""
        raise NotImplementedError

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Append this factor's columns to ``df`` and return the result."""
        out = df.copy()
        for col, series in self._series(df).items():
            out[col] = series
        return out


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, type[BaseFactor]] = {}


def register(name: str) -> Callable[[type[BaseFactor]], type[BaseFactor]]:
    """Class decorator registering a factor under *name*."""

    def _decorate(cls: type[BaseFactor]) -> type[BaseFactor]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorate


def available() -> list[str]:
    """Return the names of all registered factors (sorted)."""
    return sorted(_REGISTRY)


def build(name: str, params: dict[str, Any] | None = None) -> BaseFactor:
    """Instantiate a registered factor by *name*.

    Raises:
        ConfigError: if *name* is not a registered factor.
    """
    if name not in _REGISTRY:
        raise ConfigError(f"Unknown factor {name!r}; available: {', '.join(available())}")
    return _REGISTRY[name](params or {})
