"""Strategy base class and registry.

A strategy is the top of the AROS research pipeline: it reads the factor
columns produced by the factor layer and emits a tradeable **signal** (LONG /
FLAT / SHORT) per bar. Like indicators and factors, every strategy is a pure,
causal function of past data -- a signal at bar *t* depends only on factor
values at bars ``<= t`` -- so the *禁止未来函数* (no future-function leakage)
guarantee is preserved end-to-end.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from core.exceptions import ConfigError


class BaseStrategy:
    """Base class for all strategies.

    Subclasses set the class attribute ``name`` (the registry key / strategy
    *type*) and implement :meth:`_columns`, which returns new column name ->
    :class:`pandas.Series` mappings (typically a ``signal_<name>`` column and
    an optional ``score_<name>`` column). :meth:`compute` appends them to a
    copy of the input frame so the original is never mutated.
    """

    name = "base"

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        instance_name: str | None = None,
    ) -> None:
        self.params: dict[str, Any] = dict(params or {})
        # The output column uses the *instance* name from configuration so
        # several strategies of the same type can coexist without collisions.
        self.instance_name: str = instance_name or self.name

    # ------------------------------------------------------------------ #
    # Interface
    # ------------------------------------------------------------------ #
    def _columns(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Return new strategy columns as a name -> Series mapping."""
        raise NotImplementedError

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Append this strategy's columns to ``df`` and return the result."""
        out = df.copy()
        for col, series in self._columns(df).items():
            out[col] = series
        return out


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register(name: str) -> Callable[[type[BaseStrategy]], type[BaseStrategy]]:
    """Class decorator registering a strategy under *name* (its ``type``)."""

    def _decorate(cls: type[BaseStrategy]) -> type[BaseStrategy]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorate


def available() -> list[str]:
    """Return the names of all registered strategy types (sorted)."""
    return sorted(_REGISTRY)


def build(
    name: str,
    params: dict[str, Any] | None = None,
    instance_name: str | None = None,
) -> BaseStrategy:
    """Instantiate a registered strategy by its *type* name.

    Args:
        name: registry key (the strategy ``type``, e.g. ``"weighted"``).
        params: parameter dictionary passed to the strategy constructor.
        instance_name: configuration instance name used to namespace the
            output columns (e.g. ``"weighted_momentum"``).

    Raises:
        ConfigError: if *name* is not a registered strategy type.
    """
    if name not in _REGISTRY:
        raise ConfigError(f"Unknown strategy type {name!r}; available: {', '.join(available())}")
    return _REGISTRY[name](params or {}, instance_name)
