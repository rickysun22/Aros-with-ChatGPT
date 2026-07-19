"""Live smoke: confirm AKShare returns real A-share data for the 3 calls the
real-data path depends on (stock daily, index daily, csi800 constituents)."""

from __future__ import annotations

import akshare as ak
import pandas as pd

pd.set_option("display.width", 120)

print("== stock_zh_a_hist 600000 (2023) ==")
df = ak.stock_zh_a_hist(
    symbol="600000", period="daily", start_date="20230101", end_date="20231231", adjust="qfq"
)
print("rows:", len(df), "| cols:", list(df.columns)[:6])
print(df.head(3).to_string(index=False))

print("\n== index_zh_a_hist 000300 (2023) ==")
idx = ak.index_zh_a_hist(
    symbol="000300", period="daily", start_date="20230101", end_date="20231231"
)
print("rows:", len(idx))
print(idx.head(3).to_string(index=False))

print("\n== index_stock_cons 000906 (csi800 constituents) ==")
cons = ak.index_stock_cons(symbol="000906")
print("rows:", len(cons), "| cols:", list(cons.columns))
print(cons.head(3).to_string(index=False))
print("\nLIVE SMOKE OK")
