"""Benchmark comparison -- STUB (fills in Sprint 2.3).

2.0 only reserves the module so downstream imports are stable. The actual
comparison (experiment equity vs a benchmark index pulled through
``DataManager.get_index_daily``) lands in Sprint 2.3. No metric math is defined
here -- metrics live in ``src/backtest/metrics.py``.
"""

from __future__ import annotations

from typing import Any


class BenchmarkComparator:
    """Compares experiment performance against a benchmark index (Sprint 2.3)."""

    def compare(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("benchmark comparison lands in Sprint 2.3")
