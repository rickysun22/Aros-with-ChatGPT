"""One-off universe sync helper for AROS.

Usage::

    PYTHONPATH=src python scripts/sync_universe.py [pool] [start] [end] [limit]

Syncs every code in ``pool`` (default ``csi800``) from ``start`` (default
``2024-01-01``) through ``end`` (default today) via the AkShare-backed
``DataManager.sync_daily``. Idempotent (upsert on ``(code, date)``) and
resilient (one bad code never aborts the batch). Used to backfill the local
DB before a ``research alpha run --no-sync`` so the screen sees fresh data.

This is a manual tool — the scheduled daily loop does its own incremental sync
inside ``run_daily``; call this when you need a bounded, one-shot backfill
(e.g. a fresh clone, or after changing the lookback window).
"""
from __future__ import annotations

import sys
import time
from datetime import date

from data.manager import DataManager
from universe.engine import UniverseEngine


def main() -> None:
    pool = sys.argv[1] if len(sys.argv) > 1 else "csi800"
    start = sys.argv[2] if len(sys.argv) > 2 else "2024-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else date.today().isoformat()
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    dm = DataManager()
    ue = UniverseEngine()
    # ``all_a`` is not a named pool row; it resolves from the persisted ``Stock``
    # table. Refresh that table first, then read it so the one-shot backfill
    # covers the whole market (~5300 codes).
    if pool == "all_a":
        print("[sync_universe] refreshing full A-share stock list ...")
        dm.sync_stock_list()
    codes = list(ue.get_codes(pool))
    if not codes:
        print(f"[sync_universe] pool {pool!r} is empty; nothing to sync")
        return
    if limit:
        codes = codes[:limit]
    print(f"[sync_universe] pool={pool} codes={len(codes)} window={start}..{end}")

    ok = fail = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        try:
            dm.sync_daily(
                code,
                start_date=date.fromisoformat(start),
                end_date=date.fromisoformat(end),
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  FAIL {code}: {type(exc).__name__} {str(exc)[:80]}")
        if i % 50 == 0:
            print(f"  ...{i}/{len(codes)} ok={ok} fail={fail} {time.time() - t0:.0f}s")
    print(f"[sync_universe] DONE ok={ok} fail={fail} total={time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
