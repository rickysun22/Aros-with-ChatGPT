"""Phase 4.0 Universe Provider (design §5 4.0 / §10 Q1).

The daily screening universe is **not** hard-coded to csi800. A small Provider
abstraction lets the screening engine resolve a code pool from whichever source
is configured, without the caller knowing the mechanics:

* ``CSI800Provider``   -- constituent codes of the CSI 800 index (000906),
  via :class:`~universe.engine.UniverseEngine` (seeded from AKShare).
* ``WatchlistProvider`` -- an explicit code list passed inline, or read from a
  one-code-per-line text file (``--watchlist`` / ``universe.watchlist_path``).
* ``CustomProvider``    -- a fixed custom code list (reserved for custom strong
  pools; today fed from ``universe.custom_codes``).

``get_universe_provider`` resolves the right provider from config (or an
explicit ``type`` override), so the CLI can switch universe at run time:

    python main.py research alpha daily --universe watchlist --watchlist mine.txt
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.config import AppConfig, UniverseConfig, get_config
from universe.engine import UniverseEngine


class UniverseProvider(ABC):
    """Resolve a candidate code pool for screening / daily-alpha.

    Implementations must return a de-duplicated, sorted code list. ``as_of``
    is accepted for forward-compatible point-in-time resolution but the Phase
    4.0 providers ignore it (current membership).
    """

    @abstractmethod
    def codes(self, as_of: Any | None = None) -> list[str]:
        """Return the candidate codes for this universe."""


class CSI800Provider(UniverseProvider):
    """CSI 800 constituents via :class:`UniverseEngine` (design §5 4.0)."""

    def __init__(self, universe_engine: UniverseEngine | None = None) -> None:
        self._ue = universe_engine or UniverseEngine()

    def codes(self, as_of: Any | None = None) -> list[str]:
        codes = self._ue.get_codes("csi800")
        if not codes:
            raise ValueError(
                "csi800 pool is empty; seed it first (python main.py research batch --seed-csi800)"
            )
        return sorted(set(codes))


class WatchlistProvider(UniverseProvider):
    """An explicit watchlist: either inline ``codes`` or a text file.

    The file format is one code per line; ``#``-prefixed lines are ignored.
    """

    def __init__(
        self,
        codes: list[str] | None = None,
        watchlist_path: str | Path | None = None,
    ) -> None:
        self._codes = [str(c).strip() for c in (codes or []) if str(c).strip()]
        self._path = Path(watchlist_path) if watchlist_path else None

    def codes(self, as_of: Any | None = None) -> list[str]:
        if self._codes:
            return sorted(set(self._codes))
        if self._path and self._path.exists():
            text = self._path.read_text(encoding="utf-8")
            parsed = [
                ln.strip()
                for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            if not parsed:
                raise ValueError(f"watchlist file {self._path} is empty")
            return sorted(set(parsed))
        raise ValueError("WatchlistProvider requires codes or a non-empty watchlist_path")


class CustomProvider(UniverseProvider):
    """A fixed custom code list (reserved for custom strong pools, design §5 4.0)."""

    def __init__(self, codes: list[str] | None) -> None:
        if not codes:
            raise ValueError("CustomProvider requires a non-empty code list")
        self._codes = sorted(set(str(c).strip() for c in codes if str(c).strip()))

    def codes(self, as_of: Any | None = None) -> list[str]:
        return list(self._codes)


def get_universe_provider(
    type: str | None = None,
    *,
    config: AppConfig | None = None,
    watchlist_path: str | Path | None = None,
    codes: list[str] | None = None,
) -> UniverseProvider:
    """Resolve a :class:`UniverseProvider` from config or an explicit override.

    The explicit ``type`` / ``watchlist_path`` / ``codes`` take precedence over
    the config, so the CLI can switch universe without editing ``settings.yaml``.
    """
    cfg: UniverseConfig = (config or get_config()).universe
    utype: str = type or cfg.type
    if utype == "csi800":
        return CSI800Provider()
    if utype == "watchlist":
        return WatchlistProvider(codes=codes, watchlist_path=watchlist_path or cfg.watchlist_path)
    if utype == "custom":
        return CustomProvider(codes or cfg.custom_codes)
    raise ValueError(f"unknown universe type {utype!r} (expected csi800/watchlist/custom)")
