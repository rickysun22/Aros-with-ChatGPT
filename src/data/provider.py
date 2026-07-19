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
# Canonical AROS field -> accepted raw header candidates (in priority order).
# AKShare has drifted column naming across releases (e.g. stock_info_a_code_name
# now returns English `code`/`name`, while stock_zh_a_hist still returns the
# Chinese 日期/开盘/... headers). The resolver below picks whichever header is
# actually present so the provider keeps working across akshare versions.
_DAILY_CANON: dict[str, tuple[str, ...]] = {
    "date": ("日期", "date"),
    "open": ("开盘", "open"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "close": ("收盘", "close"),
    "volume": ("成交量", "volume"),
    "amount": ("成交额", "amount"),
}
_STOCK_CANON: dict[str, tuple[str, ...]] = {
    "code": ("代码", "code"),
    "name": ("名称", "name"),
}


def _canon_columns(raw: pd.DataFrame, canon: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Map ``{present_raw_col: canonical_field}`` using the first matching
    candidate for each field; raise :class:`DataError` if any field is absent.
    """
    rename: dict[str, str] = {}
    for field, candidates in canon.items():
        found = next((c for c in candidates if c in raw.columns), None)
        if found is None:
            raise DataError(
                f"AKShare data missing expected columns {list(candidates)}; got {list(raw.columns)}"
            )
        rename[found] = field
    return rename


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
    rename = _canon_columns(raw, _STOCK_CANON)
    out = raw.rename(columns=rename)[list(_STOCK_CANON)].copy()
    out["code"] = out["code"].astype(str).str.strip()
    out["name"] = out["name"].astype(str).str.strip()
    return out


def normalize_daily(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    """Normalize an AKShare daily-bar DataFrame to the canonical AROS schema."""
    rename = _canon_columns(raw, _DAILY_CANON)
    out = raw.rename(columns=rename)[list(_DAILY_CANON)].copy()
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

    ``ak.index_zh_a_hist`` returns the same OHLCV headers as stock history, so
    the same column map applies. Unlike stocks, an index bar may legitimately
    lack volume/amount, so those are coerced but kept (as ``NaN``) rather than
    used to drop rows -- only a missing open/close drops a row.
    """
    rename = _canon_columns(raw, _DAILY_CANON)
    out = raw.rename(columns=rename)[list(_DAILY_CANON)].copy()
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
