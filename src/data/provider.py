"""External data providers and column normalization.

The :class:`DataProvider` protocol decouples the rest of the system from any
specific data source. :class:`AkShareProvider` is the concrete implementation
backed by `akshare`; tests inject a fake implementation so no network call is
ever made during the suite.

Normalization is kept as pure, side-effect-free functions so it can be unit
tested with plain DataFrames.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

from core.exceptions import DataError

# AKShare raw column names -> canonical AROS field names.
_DAILY_COLUMNS = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}
_STOCK_COLUMNS = {
    "代码": "code",
    "名称": "name",
}


@runtime_checkable
class DataProvider(Protocol):
    """Interface any market-data source must satisfy."""

    def get_stock_list(self) -> pd.DataFrame:
        """Return all A-share instruments as a DataFrame with ``code``/``name``."""
        ...

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        """Return daily OHLCV for ``code`` in ``[start_date, end_date]``.

        The result must contain columns: ``code``, ``date``, ``open``, ``high``,
        ``low``, ``close``, ``volume``, ``amount``. Only historical data up to
        ``end_date`` is returned -- no future leakage.
        """
        ...

    def get_index_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        """Return daily OHLCV for a benchmark index ``code`` (Sprint 2.0).

        Same normalized columns as :meth:`get_daily_bars` (``volume``/``amount``
        may be ``NaN`` for indices). Only historical data up to ``end_date`` is
        returned -- no future leakage.
        """
        ...


def normalize_stock_list(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize an AKShare stock-list DataFrame to canonical columns."""
    missing = [c for c in _STOCK_COLUMNS if c not in raw.columns]
    if missing:
        raise DataError(f"AKShare stock list missing columns: {missing}")
    out = raw.rename(columns=_STOCK_COLUMNS)[list(_STOCK_COLUMNS.values())].copy()
    out["code"] = out["code"].astype(str).str.strip()
    out["name"] = out["name"].astype(str).str.strip()
    return out


def normalize_daily(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    """Normalize an AKShare daily-bar DataFrame to the canonical AROS schema."""
    missing = [c for c in _DAILY_COLUMNS if c not in raw.columns]
    if missing:
        raise DataError(f"AKShare daily bars missing columns: {missing}")
    out = raw.rename(columns=_DAILY_COLUMNS)[list(_DAILY_COLUMNS.values())].copy()
    out["code"] = code
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # Drop rows we cannot use (e.g. suspended days with no close print).
    out = out.dropna(subset=["open", "close"])
    out = out.sort_values("date").reset_index(drop=True)
    return out[["code", "date", "open", "high", "low", "close", "volume", "amount"]]


def normalize_index_daily(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    """Normalize an AKShare index-history DataFrame to the canonical AROS schema.

    ``ak.index_zh_a_hist`` returns the same Chinese OHLCV headers as stock
    history, so the same column map applies. Unlike stocks, an index bar may
    legitimately lack volume/amount, so those are coerced but kept (as ``NaN``)
    rather than used to drop rows -- only a missing open/close drops a row.
    """
    missing = [c for c in _DAILY_COLUMNS if c not in raw.columns]
    if missing:
        raise DataError(f"AKShare index bars missing columns: {missing}")
    out = raw.rename(columns=_DAILY_COLUMNS)[list(_DAILY_COLUMNS.values())].copy()
    out["code"] = code
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["open", "close"])
    out = out.sort_values("date").reset_index(drop=True)
    return out[["code", "date", "open", "high", "low", "close", "volume", "amount"]]


class AkShareProvider:
    """AKShare-backed :class:`DataProvider`.

    `akshare` is imported lazily inside each method so the package is only
    required when live data is actually fetched (tests use a fake provider and
    never trigger the import).
    """

    def __init__(self, adjust: str = "qfq") -> None:
        self.adjust = adjust

    def get_stock_list(self) -> pd.DataFrame:
        import akshare as ak

        return normalize_stock_list(ak.stock_info_a_code_name())

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        import akshare as ak

        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust=self.adjust,
        )
        return normalize_daily(raw, code)

    def get_index_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        # Frozen decision (Sprint 2.0 §7 Q1): use index_zh_a_hist for native
        # date-range support and integer-date alignment with get_daily_bars.
        import akshare as ak

        raw = ak.index_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        return normalize_index_daily(raw, code)
