"""Quick connectivity probe for Eastmoney push2his K-line API.

Run on the USER's machine (with the system proxy OFF) to confirm that
``push2his.eastmoney.com`` is reachable. Exit code 0 = reachable.

Usage:  python scripts/aros_probe_eastmoney.py
"""

from __future__ import annotations

import sys

import requests

CODE = "000001"  # Ping An Bank (Shenzhen)
URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"


def _secid(code: str) -> str:
    if code.startswith("6"):
        return f"1.{code}"
    if code.startswith(("0", "3")):
        return f"0.{code}"
    if code.startswith(("8", "4")):
        return f"2.{code}"
    return f"0.{code}"


def probe() -> int:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "0",
        "secid": _secid(CODE),
        "beg": "0",
        "end": "20500101",
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    session = requests.Session()
    session.trust_env = False  # force direct connection, ignore system proxy
    try:
        resp = session.get(URL, params=params, headers=headers, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] EastMoney request raised: {exc!r}")
        return 1
    if resp.status_code != 200:
        print(f"[FAIL] EastMoney HTTP {resp.status_code}")
        return 1
    try:
        klines = (resp.json().get("data") or {}).get("klines") or []
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] EastMoney JSON parse error: {exc!r}")
        return 1
    if not klines:
        print("[FAIL] EastMoney returned empty klines (possible block / rate-limit)")
        return 1
    last = klines[-1].split(",")
    print(f"[OK] EastMoney reachable. {CODE} returned {len(klines)} daily rows.")
    print(f"     latest bar: date={last[0]} close={last[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(probe())
