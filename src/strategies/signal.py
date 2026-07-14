"""Trading signal primitives for AROS.

A :class:`SignalType` is the discrete action a strategy emits at a bar:
``LONG`` (+1), ``FLAT`` (0) or ``SHORT`` (-1). Strategies write a ``signal``
column holding these integer codes; the
:class:`~strategies.portfolio.Portfolio` turns them into positions. Keeping the
signal as a small, explicit vocabulary makes every strategy explainable and
keeps the A-share reality (long/flat first, short reserved for future
extension) obvious.
"""

from __future__ import annotations

from enum import IntEnum


class SignalType(IntEnum):
    """Discrete trading action emitted by a strategy at a bar."""

    SHORT = -1
    FLAT = 0
    LONG = 1

    @classmethod
    def coerce(cls, value: object) -> SignalType:
        """Coerce an int / IntEnum / str / float into a :class:`SignalType`."""
        if isinstance(value, SignalType):
            return value
        if isinstance(value, str):
            try:
                return cls[value.upper()]
            except KeyError:
                return cls(int(value))
        if isinstance(value, (int, float)):
            return cls(int(value))
        raise TypeError(f"Cannot coerce {type(value).__name__} into a SignalType")


def to_position(signal: SignalType | int | float) -> float:
    """Map a signal to a target position weight.

    Accepts a :class:`SignalType` or a raw code (``1`` / ``0`` / ``-1``), so it
    works directly on the integer signal columns that strategies emit.

    A-share first: ``LONG`` -> 1.0 (fully invested), ``FLAT`` -> 0.0 (cash),
    ``SHORT`` -> -1.0 (reserved for future short-selling support).
    """
    return float(SignalType.coerce(signal).value)
