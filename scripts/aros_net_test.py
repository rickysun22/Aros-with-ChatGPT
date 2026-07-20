"""Quick connectivity test — run this FIRST to diagnose network issues.

This script does NOT use any AROS code.  It directly tests whether your
machine can reach Sina (akshare) and Eastmoney, with and without proxy
environment variables.

Usage:  python scripts/aros_net_test.py
"""

from __future__ import annotations

import os
import sys


def _header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _show_env() -> None:
    keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "NO_PROXY",
        "no_proxy",
    ]
    found = {k: os.environ.get(k, "(unset)") for k in keys if k in os.environ}
    if found:
        print(f"  Proxy env vars present: {found}")
    else:
        print("  Proxy env vars: (all clear)")


def test_raw_urllib(url: str, label: str) -> bool:
    """Test with stdlib urllib (no dependencies)."""
    try:
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urlopen(req, timeout=10)
        data = resp.read(200)
        print(f"  [OK]   {label}: HTTP {resp.status} ({len(data)} bytes)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {label}: {type(exc).__name__}: {exc}")
        return False


def test_requests_lib(url: str, label: str) -> bool:
    """Test with requests library (same as akshare uses internally)."""
    try:
        import requests

        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        print(
            f"  [OK]   {label} (requests trust_env=False): "
            f"HTTP {resp.status_code} ({len(resp.content)} bytes)"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {label} (requests): {type(exc).__name__}: {exc}")
        return False


def test_akshare_direct() -> bool:
    """Test if akshare.stock_zh_a_daily works."""
    try:
        import akshare as ak

        df = ak.stock_zh_a_daily(symbol="sh600000")
        if df.empty:
            print("  [WARN] akshare returned empty DataFrame")
            return False
        print(
            f"  [OK]   akshare stock_zh_a_daily('sh600000'): "
            f"{len(df)} rows, latest={df.iloc[-1].get('date', 'N/A')}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] akshare: {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    print("AROS Network Connectivity Diagnostic")
    print(f"Python: {sys.executable}")
    print(f"Version: {sys.version}")

    _header("STEP 1: Current proxy environment")
    _show_env()

    _header("STEP 2: Raw urllib tests (no proxy control)")
    test_raw_urllib("https://finance.sina.com.cn", "Sina Finance portal")
    test_raw_urllib("http://push2his.eastmoney.com", "EastMoney push2his")

    _header("STEP 3: Clearing proxy env vars + re-test with requests")
    for k in list(os.environ.keys()):
        kl = k.lower()
        if "proxy" in kl:
            del os.environ[k]
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    _show_env()

    test_requests_lib("https://hq.sinajs.cn/list=sh600000", "Sina HQ (real-time quote)")
    test_requests_lib(
        "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=3&fields=f12,f14&fs=m:0+t:6",
        "EastMoney clist (stock list)",
    )

    _header("STEP 4: akshare direct call (stock_zh_a_daily)")
    ok_ak = test_akshare_direct()

    _header("SUMMARY")
    if ok_ak:
        print("  >>> akshare WORKS — you should be able to run aros_backfill.bat <<<")
        print("      If it still fails, the issue is in AROS code, not network.")
    else:
        print("  >>> akshare FAILED — network or proxy issue on this machine <<<")
        print("      Check:")
        print("      1. Windows Settings → Network → Proxy → turn OFF")
        print("      2. IE/Edge: Internet Options → Connections → LAN Settings → uncheck proxy")
        print("      3. VPN/Clash/TUN mode must be completely disabled")


if __name__ == "__main__":
    main()
