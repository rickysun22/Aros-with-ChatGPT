"""``a-stock-data`` backed provider (akshare-free, direct HTTP).

This provider is adapted from the ``a-stock-data`` toolkit
(https://github.com/simonlin1212/a-stock-data), which deliberately dropped the
``akshare`` dependency in favour of direct HTTP/TCP calls to multiple A-share
data sources with built-in fallback and rate limiting.

Implemented here (the parts AROS needs):

* **Daily bars** -- Baidu 股市通 K-line (``finance.pae.baidu.com``), zero-auth
  HTTP, returns OHLCV (+ MA). It yields *raw* (unadjusted) prices; for
  forward-adjusted research data keep ``data.source: akshare`` as the default.
* **Stock list** -- Eastmoney clist (``push2.eastmoney.com``), zero-auth HTTP.

``requests`` is imported lazily so the module (and the test suite) never
requires network access unless a real fetch is performed.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# Baidu K-line field order -> canonical AROS field.
_BAIDU_FIELD_MAP = {
    "time": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}

_BAIDU_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"
_EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# Sina field order -> canonical AROS field.
_SINA_FIELD_MAP = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}


# --------------------------------------------------------------------------- #
# Raw fetchers (lazy network)
# --------------------------------------------------------------------------- #
def _baidu_kline(code: str, start_time: str = "") -> dict:
    """Return raw Baidu K-line payload: ``{"keys": [...], "rows": [...]}``."""
    import requests

    params = {
        "all": "1",
        "isIndex": "false",
        "isBk": "false",
        "isBlock": "false",
        "isFutures": "false",
        "isStock": "true",
        "newFormat": "1",
        "group": "quotation_kline_ab",
        "finClientType": "pc",
        "code": code,
        "start_time": start_time,
        "ktype": "1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    resp = requests.get(_BAIDU_URL, params=params, headers=headers, timeout=10)
    data = resp.json()
    market = (data.get("Result") or {}).get("newMarketData") or {}
    return {
        "keys": market.get("keys", []),
        "rows": (market.get("marketData") or "").split(";"),
    }


def _eastmoney_stock_list() -> pd.DataFrame:
    """Return the full A-share list as a DataFrame with ``code``/``name``."""
    import requests

    params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23",
        "fields": "f12,f14",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    resp = requests.get(_EASTMONEY_LIST_URL, params=params, headers=headers, timeout=15)
    payload = resp.json()
    items = (payload.get("data") or {}).get("diff") or []
    rows = [
        {"code": str(it.get("f12", "")).strip(), "name": str(it.get("f14", "")).strip()}
        for it in items
    ]
    return pd.DataFrame(rows, columns=["code", "name"])


def _sina_daily(code: str) -> pd.DataFrame:
    """Return daily bars from Sina Finance (``stock_zh_a_daily``).

    This is the **preferred** source because:
    * ``push2his.eastmoney.com`` is blocked on many corporate / proxy networks.
    * Baidu's K-line API is fragile (empty keys in some environments).
    * Sina's endpoint works reliably through most proxies and firewalls.

    Returns a DataFrame with columns matching the canonical AROS schema:
    ``[code, date, open, high, low, close, volume, amount]``.
    """
    import akshare as ak

    # stock_zh_a_daily expects prefix: sh for Shanghai, sz for Shenzhen
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    df = ak.stock_zh_a_daily(symbol=symbol)

    if df.empty or "date" not in df.columns:
        return pd.DataFrame(
            columns=["code", "date", "open", "high", "low", "close", "volume", "amount"]
        )

    # Select + rename to canonical schema
    out = df.rename(columns=_SINA_FIELD_MAP)[list(_SINA_FIELD_MAP.values())].copy()
    out.insert(0, "code", code)
    # Ensure date is date type
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    # Ensure numeric types
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "close"]).reset_index(drop=True)[
        ["code", "date", "open", "high", "low", "close", "volume", "amount"]
    ]


# --------------------------------------------------------------------------- #
# Normalization (pure)
# --------------------------------------------------------------------------- #
def normalize_baidu_daily(raw: dict, code: str) -> pd.DataFrame:
    """Normalize a raw Baidu K-line payload to the canonical AROS schema."""
    keys = raw.get("keys", [])
    rows = raw.get("rows", [])
    if not keys or not rows:
        return pd.DataFrame(
            columns=["code", "date", "open", "high", "low", "close", "volume", "amount"]
        )

    records = []
    for row in rows:
        if not row:
            continue
        parts = row.split(",")
        if len(parts) != len(keys):
            continue
        record = {"code": code}
        record.update(dict(zip(keys, parts, strict=True)))
        mapped = {"code": code}
        for src, dst in _BAIDU_FIELD_MAP.items():
            mapped[dst] = record.get(src) or ""
        records.append(mapped)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "close"])
    return df.sort_values("date").reset_index(drop=True)[
        ["code", "date", "open", "high", "low", "close", "volume", "amount"]
    ]


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class AStockDataProvider:
    """``a-stock-data`` backed :class:`DataProvider` (direct HTTP, akshare-free)."""

    def get_stock_list(self) -> pd.DataFrame:
        return _eastmoney_stock_list()

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        # Primary source: Sina Finance (reliable through most proxies)
        df = _sina_daily(code)
        if not df.empty:
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            return df[mask].reset_index(drop=True)

        # Fallback: Baidu K-line API
        raw = _baidu_kline(code)
        df = normalize_baidu_daily(raw, code)
        if df.empty:
            return df
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        return df[mask].reset_index(drop=True)

    def get_index_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        # Frozen decision (Sprint 2.0 §7 Q6): index history via astockdata is
        # deferred; AKShare is the default index source. Fail loudly (not
        # silently) so ``data.source=astockdata`` surfaces the gap immediately.
        raise NotImplementedError(
            "astockdata does not provide index history yet; "
            "set data.source=akshare for benchmark index data"
        )
