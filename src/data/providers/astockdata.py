"""``a-stock-data`` backed provider (akshare-free, direct HTTP).

This provider is adapted from the ``a-stock-data`` toolkit
(https://github.com/simonlin1212/a-stock-data), which deliberately dropped the
``akshare`` dependency in favour of direct HTTP/TCP calls to multiple A-share
data sources with built-in fallback and rate limiting.

Implemented here (the parts AROS needs):

* **Daily bars** -- Sina Finance (``akshare stock_zh_a_daily``) is the
  **preferred** source because ``push2his.eastmoney.com`` is unreachable from
  many networks (proxy / ISP / firewall). Eastmoney push2his and Baidu are
  fallbacks used only when Sina fails.
* **Stock list** -- Eastmoney clist (``push2.eastmoney.com``) with akshare
  fallback; both sources return ``code``/``name`` pairs.

``requests`` is imported lazily so the module (and the test suite) never
requires network access unless a real fetch is performed.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

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
    """Return the full A-share list from Eastmoney clist API.

    Falls back to ``akshare stock_info_a_code_name()`` when Eastmoney is
    unreachable (same network issues that block push2his).
    """
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
    session = requests.Session()
    session.trust_env = False
    try:
        resp = session.get(_EASTMONEY_LIST_URL, params=params, headers=headers, timeout=10)
        payload = resp.json()
        items = (payload.get("data") or {}).get("diff") or []
        rows = [
            {
                "code": str(it.get("f12", "")).strip(),
                "name": str(it.get("f14", "")).strip(),
            }
            for it in items
        ]
        return pd.DataFrame(rows, columns=["code", "name"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("eastmoney_stock_list failed (%s), falling back to akshare", exc)
        return _akshare_stock_list()


def _akshare_stock_list() -> pd.DataFrame:
    """Return the full A-share list via akshare (fallback for stock list)."""
    import akshare as ak

    try:
        df = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001
        logger.error("akshare stock_info_a_code_name failed: %s", exc)
        return pd.DataFrame(columns=["code", "name"])

    if df.empty:
        return pd.DataFrame(columns=["code", "name"])
    # akshare returns columns like ["code", "name"] already
    out = df[["code", "name"]].copy()
    out["code"] = out["code"].astype(str).str.strip()
    out["name"] = out["name"].astype(str).str.strip()
    return out.reset_index(drop=True)


_EASTMONEY_KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"


def _secid(code: str) -> str:
    """Map a 6-digit A-share code to Eastmoney's ``market.code`` secid."""
    if code.startswith("6"):
        return f"1.{code}"  # Shanghai
    if code.startswith(("0", "3")):
        return f"0.{code}"  # Shenzhen (incl. ChiNext 3xxxxx)
    if code.startswith(("8", "4")):
        return f"2.{code}"  # Beijing Exchange
    return f"0.{code}"


def _eastmoney_daily(code: str) -> pd.DataFrame:
    """Return daily bars from Eastmoney push2his K-line API (raw, unadjusted).

    This is a **fallback** source; Sina Finance is preferred because Eastmoney
    push2his is unreachable from many networks. Returns the canonical AROS
    schema ``[code, date, open, high, low, close, volume, amount]``.
    """
    import requests

    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",  # 101 = daily
        "fqt": "0",  # 0 = raw (unadjusted)
        "secid": _secid(code),
        "beg": "0",
        "end": "20500101",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    session = requests.Session()
    session.trust_env = False  # bypass any system proxy; Eastmoney was blocked by it
    resp = session.get(_EASTMONEY_KLINE_URL, params=params, headers=headers, timeout=10)
    payload = resp.json()
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return pd.DataFrame(
            columns=["code", "date", "open", "high", "low", "close", "volume", "amount"]
        )
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5],
                "amount": parts[6],
            }
        )
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "close"])
    out = df[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
    out.insert(0, "code", code)
    return out.sort_values("date").reset_index(drop=True)


def _sina_daily(code: str) -> pd.DataFrame:
    """Return daily bars from Sina Finance (``stock_zh_a_daily``).

    This is the **preferred** source because ``push2his.eastmoney.com`` is
    unreachable from many networks (proxy / ISP / firewall). Sina's endpoint
    works reliably through most environments.

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
        # 1) Preferred: Sina Finance (works reliably through most networks)
        df = _sina_daily(code)
        if not df.empty:
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            return df[mask].reset_index(drop=True)

        # 2) Fallback: Eastmoney push2his K-line (raw, unadjusted)
        df = _eastmoney_daily(code)
        if not df.empty:
            logger.warning("daily source=eastmoney (sina failed) code=%s", code)
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            return df[mask].reset_index(drop=True)

        # 3) Fallback: Baidu K-line API
        raw = _baidu_kline(code)
        df = normalize_baidu_daily(raw, code)
        if df.empty:
            logger.warning("daily source=NONE (all sources failed) code=%s", code)
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
