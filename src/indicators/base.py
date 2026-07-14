"""Indicator base class and registry.

Every technical indicator is a :class:`BaseIndicator` subclass decorated with
:func:`register`. Indicators are **pure, causal functions** of historical bars:
an indicator value computed at bar *t* may only depend on data at bars
``<= t``. This is what guarantees the project principle *禁止未来函数* (no
future-function leakage). The test-suite enforces it with a truncation test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from core.exceptions import ConfigError


class BaseIndicator:
    """Base class for all indicators.

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
        """Return new indicator columns as a name -> Series mapping."""
        raise NotImplementedError

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Append this indicator's columns to ``df`` and return the result."""
        out = df.copy()
        for col, series in self._series(df).items():
            out[col] = series
        return out


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, type[BaseIndicator]] = {}


def register(name: str) -> Callable[[type[BaseIndicator]], type[BaseIndicator]]:
    """Class decorator registering an indicator under *name*."""

    def _decorate(cls: type[BaseIndicator]) -> type[BaseIndicator]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorate


def available() -> list[str]:
    """Return the names of all registered indicators (sorted)."""
    return sorted(_REGISTRY)


def build(name: str, params: dict[str, Any] | None = None) -> BaseIndicator:
    """Instantiate a registered indicator by *name*.

    Raises:
        ConfigError: if *name* is not a registered indicator.
    """
    if name not in _REGISTRY:
        raise ConfigError(f"Unknown indicator {name!r}; available: {', '.join(available())}")
    return _REGISTRY[name](params or {})
