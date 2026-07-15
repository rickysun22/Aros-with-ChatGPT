"""Walk-forward / out-of-sample splitting -- STUB (fills in Sprint 2.5).

Turns a :class:`~research.experiment.WalkForwardSpec` into rolling
train/test windows for out-of-sample validation. The no-look-ahead guarantee
(test windows never precede their training window) is enforced here in 2.5.
2.0 only reserves the module.
"""

from __future__ import annotations

from research.experiment import WalkForwardSpec


class WalkForwardSplitter:
    """Generates rolling IS/OOS windows from a :class:`WalkForwardSpec` (Sprint 2.5)."""

    def split(self, spec: WalkForwardSpec, start: str, end: str) -> list[tuple[str, str, str, str]]:
        raise NotImplementedError("walk-forward splitting lands in Sprint 2.5")
