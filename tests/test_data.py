"""Tests for the Sprint 1.2 data layer: normalization, models, DataManager."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core.exceptions import DataError
from data.manager import DataManager
from data.provider import normalize_daily, normalize_stock_list


# --------------------------------------------------------------------------- #
# Fake provider (no network)
# --------------------------------------------------------------------------- #
class FakeProvider:
    """In-memory :class:`DataProvider` returning canned, already-normalized data."""

    def __init__(self) -> None:
        self.stocks = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])
        self.bars = pd.DataFrame(
            [
                {
                    "code": "600000",
                    "date": date(2024, 1, 2),
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10.1,
                    "volume": 1000.0,
                    "amount": 10100.0,
                },
                {
                    "code": "600000",
                    "date": date(2024, 1, 3),
                    "open": 10.5,
                    "high": 10.6,
                    "low": 10.4,
                    "close": 10.55,
                    "volume": 1100.0,
                    "amount": 11500.0,
                },
            ]
        )
        self.calls: list[object] = []

    def get_stock_list(self) -> pd.DataFrame:
        self.calls.append("list")
        return self.stocks

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        self.calls.append(("bars", code, start_date, end_date))
        return self.bars


# --------------------------------------------------------------------------- #
# Normalization (pure functions)
# --------------------------------------------------------------------------- #
def test_normalize_stock_list() -> None:
    raw = pd.DataFrame([{"代码": "600000 ", "名称": "浦发银行"}])
    out = normalize_stock_list(raw)
    assert list(out.columns) == ["code", "name"]
    assert out.iloc[0]["code"] == "600000"
    assert out.iloc[0]["name"] == "浦发银行"


def test_normalize_daily() -> None:
    raw = pd.DataFrame(
        [
            {
                "日期": "2024-01-03",
                "开盘": 10.5,
                "最高": 10.6,
                "最低": 10.4,
                "收盘": 10.55,
                "成交量": 1100,
                "成交额": 11500,
            },
            {
                "日期": "2024-01-02",
                "开盘": 10.0,
                "最高": 10.2,
                "最低": 9.8,
                "收盘": 10.1,
                "成交量": 1000,
                "成交额": 10100,
            },
        ]
    )
    out = normalize_daily(raw, "600000")
    assert list(out.columns) == [
        "code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert out.iloc[0]["date"] == date(2024, 1, 2)  # sorted ascending
    assert out.iloc[0]["code"] == "600000"


def test_normalize_daily_missing_columns_raises() -> None:
    raw = pd.DataFrame([{"日期": "2024-01-02"}])
    with pytest.raises(DataError):
        normalize_daily(raw, "600000")


# --------------------------------------------------------------------------- #
# DataManager end-to-end (fake provider, temp database)
# --------------------------------------------------------------------------- #
@pytest.fixture
def dm(tmp_path, monkeypatch: pytest.MonkeyPatch) -> DataManager:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return DataManager(provider=FakeProvider())


def test_manager_sync_and_read(dm: DataManager) -> None:
    assert dm.sync_stock_list() == 1
    assert dm.sync_daily("600000") == 2

    stocks = dm.get_stock_list()
    assert set(stocks["code"]) == {"600000"}

    bars = dm.get_daily("600000")
    assert len(bars) == 2
    assert bars.iloc[0]["date"] == date(2024, 1, 2)
    assert dm.last_sync_date("600000") == date(2024, 1, 3)


def test_manager_resync_is_idempotent(dm: DataManager) -> None:
    dm.sync_daily("600000")
    assert dm.sync_daily("600000") == 2  # no duplicates
    assert len(dm.get_daily("600000")) == 2


def test_manager_get_daily_range(dm: DataManager) -> None:
    dm.sync_daily("600000")
    out = dm.get_daily("600000", start_date=date(2024, 1, 3))
    assert len(out) == 1
    assert out.iloc[0]["date"] == date(2024, 1, 3)


def test_manager_passes_date_range_to_provider() -> None:
    prov = FakeProvider()
    dm = DataManager(provider=prov)
    dm.sync_daily("600000", start_date=date(2023, 1, 1), end_date=date(2023, 12, 31))
    # The fake provider records the exact (start, end) it received.
    assert ("bars", "600000", date(2023, 1, 1), date(2023, 12, 31)) in prov.calls
