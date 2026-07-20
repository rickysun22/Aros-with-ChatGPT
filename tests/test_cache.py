"""Tests for the disk cache layer used by the daily loop (data.cache).

Offline: a temp dir stands in for ``.cache``; money-flow providers are fakes whose
call counts prove caching actually throttles repeated network hits.
"""

from __future__ import annotations

from data.cache import (
    CachedHiddenFlowProvider,
    CachedMoneyFlowProvider,
    DayCache,
)
from research.consensus import HiddenFlowSignal, MoneyFlowSignal


def test_daycache_roundtrip(tmp_path) -> None:
    c = DayCache(tmp_path, ttl_days=1)
    c.set("k", {"a": 1, "b": [2, 3]})
    assert c.get("k") == {"a": 1, "b": [2, 3]}


def test_daycache_ttl_expiry(tmp_path) -> None:
    # ttl_days=0 -> any entry is immediately stale, so get() returns None.
    c = DayCache(tmp_path, ttl_days=0)
    c.set("k", 42)
    assert c.get("k") is None


def test_daycache_miss_returns_none(tmp_path) -> None:
    c = DayCache(tmp_path, ttl_days=1)
    assert c.get("missing") is None


def test_cached_money_flow_throttles_calls(tmp_path) -> None:
    calls: list[int] = [0]

    class _Fake:
        def get_stock_flow(self, code: str) -> MoneyFlowSignal:
            calls[0] += 1
            return MoneyFlowSignal(sector_score=50.0, public_money_score=50.0)

    wrapped = CachedMoneyFlowProvider(_Fake(), DayCache(tmp_path, ttl_days=1))
    # Two calls for the same code on the same day -> only one underlying hit.
    wrapped.get_stock_flow("000001")
    wrapped.get_stock_flow("000001")
    assert calls[0] == 1
    # A different code forces a second fetch.
    wrapped.get_stock_flow("000002")
    assert calls[0] == 2


def test_cached_hidden_flow_throttles_calls(tmp_path) -> None:
    calls: list[int] = [0]

    class _Fake:
        def infer(self, code: str) -> HiddenFlowSignal:
            calls[0] += 1
            return HiddenFlowSignal(score=50.0, explanation="x")

    wrapped = CachedHiddenFlowProvider(_Fake(), DayCache(tmp_path, ttl_days=1))
    wrapped.infer("000001")
    wrapped.infer("000001")
    assert calls[0] == 1


def test_cached_price_provider_roundtrip(tmp_path) -> None:
    # cached_daily_price_provider wraps a DataManager-like object; a fake proves
    # the cache short-circuits repeated window pulls.
    calls: list[int] = [0]

    class _FakeDM:
        def get_daily(self, code, start, end):  # noqa: ANN001
            calls[0] += 1
            return f"frame:{code}:{start}:{end}"

    from data.cache import cached_daily_price_provider

    pp = cached_daily_price_provider(_FakeDM(), DayCache(tmp_path, ttl_days=7))
    assert pp("000001", "2026-01-05", "2026-02-01") == "frame:000001:2026-01-05:2026-02-01"
    # Second pull of the same window hits the cache, not the fake.
    pp("000001", "2026-01-05", "2026-02-01")
    assert calls[0] == 1
