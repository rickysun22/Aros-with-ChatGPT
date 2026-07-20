"""Disk-backed cache for the daily operational loop (Sprint 4.9).

The daily research pipeline makes two classes of expensive, repeated calls:

* **Money-flow providers** (``AkShareMoneyFlowProvider`` / ``AkShareHiddenFlowProvider``)
  hit AKShare live, once per candidate, every run. Their value only changes once
  per trading day (after the close), so a 1-day TTL cache cuts the daily call
  count dramatically without staleness risk.
* **Price windows** for post-hoc / calibration backfills (each candidate pulls a
  T+1..T+20 window). Caching these avoids re-fetching the same range across the
  many backfill passes and across ``--catch-up`` re-runs.

The cache is intentionally dumb and safe:

* Every entry is a pickle file plus a ``.ts`` sidecar holding its write epoch.
* ``get`` returns ``None`` on a miss *or* when the TTL has elapsed (and deletes
  the stale file), so a expired entry is treated exactly like a miss — callers
  always recompute and re-store. No silent stale reads.
* Keys are arbitrary strings; callers are responsible for namespacing
  (``mf:<code>``, ``px:<code>:<start>:<end>``).
"""

from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, cast

from research.consensus import HiddenFlowSignal, MoneyFlowSignal

_DEFAULT_TTL_DAYS = 1
_SECONDS_PER_DAY = 86_400


class DayCache:
    """A tiny disk cache with a per-entry time-to-live in days."""

    def __init__(self, cache_dir: str | Path = ".cache", ttl_days: int = _DEFAULT_TTL_DAYS) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl_days = max(0, int(ttl_days))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.pkl", self.cache_dir / f"{h}.ts"

    def get(self, key: str) -> Any | None:
        """Return the cached value, or ``None`` on miss / expiry / corruption."""
        pkl, ts = self._paths(key)
        if not pkl.exists() or not ts.exists():
            return None
        try:
            written = float(ts.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pkl.unlink(missing_ok=True)
            ts.unlink(missing_ok=True)
            return None
        if time.time() - written > self.ttl_days * _SECONDS_PER_DAY:
            pkl.unlink(missing_ok=True)
            ts.unlink(missing_ok=True)
            return None
        try:
            with pkl.open("rb") as fh:
                return pickle.load(fh)
        except (OSError, pickle.PickleError):
            return None

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` (overwrites any existing entry)."""
        pkl, ts = self._paths(key)
        try:
            with pkl.open("wb") as fh:
                pickle.dump(value, fh)
            ts.write_text(f"{time.time():.6f}", encoding="utf-8")
        except OSError:
            # Cache is best-effort: a write failure must never break the run.
            pass


class CachedMoneyFlowProvider:
    """Wrap a money-flow provider, caching ``get_stock_flow`` per code (1-day TTL)."""

    def __init__(self, provider: Any, cache: DayCache | None = None) -> None:
        self._provider = provider
        self._cache = cache or DayCache(".cache/moneyflow", ttl_days=1)

    def get_stock_flow(self, code: str) -> MoneyFlowSignal:
        key = f"mf:{code}"
        hit = self._cache.get(key)
        if hit is not None:
            return cast(MoneyFlowSignal, hit)
        val = self._provider.get_stock_flow(code)
        self._cache.set(key, val)
        return cast(MoneyFlowSignal, val)


class CachedHiddenFlowProvider:
    """Wrap a hidden-flow provider, caching ``infer`` per code (1-day TTL)."""

    def __init__(self, provider: Any, cache: DayCache | None = None) -> None:
        self._provider = provider
        self._cache = cache or DayCache(".cache/hiddenflow", ttl_days=1)

    def infer(self, code: str) -> HiddenFlowSignal:
        key = f"hf:{code}"
        hit = self._cache.get(key)
        if hit is not None:
            return cast(HiddenFlowSignal, hit)
        val = self._provider.infer(code)
        self._cache.set(key, val)
        return cast(HiddenFlowSignal, val)


def cached_daily_price_provider(data_manager: Any, cache: DayCache | None = None) -> Any:
    """Return a ``PriceProvider`` that caches ``get_daily`` results by (code,start,end).

    The underlying ``DataManager.get_daily`` reads the local DB, so the cache
    mostly helps repeated window pulls (post-hoc / calibration backfills and
    ``--catch-up`` re-runs) avoid re-scanning the same rows. Harmless if unused.
    """
    cm = cache or DayCache(".cache/prices", ttl_days=7)

    def _p(code: str, start: Any, end: Any) -> Any:
        key = f"px:{code}:{start}:{end}"
        hit = cm.get(key)
        if hit is not None:
            return hit
        val = data_manager.get_daily(code, start, end)
        cm.set(key, val)
        return val

    return _p
