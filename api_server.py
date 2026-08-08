"""AROS FastAPI 桥接服务 — 把 AROS 真实数据/指标/因子引擎暴露给前端。

设计要点
--------
* 直接 import AROS 的 ``DataManager`` / ``IndicatorEngine`` / ``FactorEngine``,
  不做任何数据造假:前端拿到的 MA/RSI/MACD/KDJ/BOLL 与 8 因子,都是 AROS
  引擎在已落库日线上**实时计算**的结果。
* akshare 在 AROS 内是懒加载,只有真正 ``sync`` 抓数时才 import;本服务只做
  读取与计算,因此**不安装 akshare 也能启动**(数据需先 sync 或 seed)。
* 无数据时返回 ``empty: true`` + 友好提示,前端据此切 mock 兜底,不白屏。
* 放开 CORS,方便前端 dev server (localhost:5173) 直接 fetch。

运行
----
    cd aros-backend
    pip install -r requirements-api.txt
    python api_server.py            # 或: uvicorn api_server:app --port 8000
前端访问 http://localhost:8000/api/...
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

# 让 `src` 包可被绝对导入 (core / data / indicators / factors)
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
import pandas as pd  # noqa: E402

from core.config import get_config  # noqa: E402
from data.manager import DataManager  # noqa: E402
from indicators.engine import IndicatorEngine  # noqa: E402
from factors.engine import FactorEngine  # noqa: E402

app = FastAPI(title="AROS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 进程级单例:配置 + DataManager + 引擎 -------------------------------
_cfg = get_config()
_dm = DataManager(config=_cfg)
_ind_engine = IndicatorEngine.from_config(_cfg.indicators)
_fac_engine = FactorEngine.from_config(_cfg.indicators, _cfg.factors)

# 友好名称映射(指数代码 -> 中文名)
_INDEX_NAMES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
}


# ---- 序列化辅助 --------------------------------------------------------
def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON 可序列化 records。日期转 ISO,NaN/NaT -> None。"""
    if df is None or df.empty:
        return []
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].apply(
                lambda v: v.isoformat() if hasattr(v, "isoformat") else v
            )
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")


def _as_date(value: str | None, default) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"日期格式应为 YYYY-MM-DD,收到: {value!r}")


# ---- 路由 --------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    try:
        stocks = _dm.get_stock_list()
        stock_count = 0 if stocks is None else len(stocks)
    except Exception:
        stock_count = 0
    return {
        "status": "ok",
        "aros_version": "0.1.0",
        "data_source": _cfg.data.source,
        "database": _cfg.database.url,
        "indicators": _ind_engine.names,
        "factors": _fac_engine.names,
        "stock_count": stock_count,
    }


@app.get("/api/stocks")
def stocks() -> dict:
    df = _dm.get_stock_list()
    recs = _df_to_records(df)
    return {"empty": len(recs) == 0, "stocks": recs}


@app.get("/api/bars/{code}")
def bars(
    code: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(240),
) -> dict:
    start_d = _as_date(start, date.fromisoformat(_cfg.data.start_date))
    end_d = _as_date(end, date.fromisoformat(_cfg.data.end_date))
    df = _dm.get_daily(code, start_d, end_d)
    if df is None or df.empty:
        return {
            "empty": True,
            "code": code,
            "message": "该标的无落库数据,请先运行: python main.py sync --code " + code,
            "bars": [],
        }
    df = df.sort_values("date").tail(limit).copy()
    # 计算逐根涨跌
    df["prev_close"] = df["close"].shift(1)
    df["change"] = df["close"] - df["prev_close"]
    df["pct"] = (df["change"] / df["prev_close"] * 100).round(2)
    recs = _df_to_records(df)
    last = recs[-1] if recs else None
    return {
        "empty": False,
        "code": code,
        "bars": recs,
        "last": last,
    }


@app.get("/api/indicators/{code}")
def indicators(
    code: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> dict:
    start_d = _as_date(start, date.fromisoformat(_cfg.data.start_date))
    end_d = _as_date(end, date.fromisoformat(_cfg.data.end_date))
    df = _ind_engine.compute_code(code, _dm, start_d, end_d)
    if df is None or df.empty:
        return {"empty": True, "code": code, "message": "无数据,请先 sync。", "rows": []}
    recs = _df_to_records(df)
    return {"empty": False, "code": code, "columns": list(df.columns), "rows": recs}


@app.get("/api/factors/{code}")
def factors(
    code: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> dict:
    start_d = _as_date(start, date.fromisoformat(_cfg.data.start_date))
    end_d = _as_date(end, date.fromisoformat(_cfg.data.end_date))
    df = _fac_engine.compute_code(code, _dm, start_d, end_d)
    if df is None or df.empty:
        return {"empty": True, "code": code, "message": "无数据,请先 sync。", "rows": []}
    recs = _df_to_records(df)
    return {"empty": False, "code": code, "columns": list(df.columns), "rows": recs}


@app.get("/api/indices/{code}")
def indices(
    code: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> dict:
    start_d = _as_date(start, date.fromisoformat(_cfg.data.start_date))
    end_d = _as_date(end, date.fromisoformat(_cfg.data.end_date))
    try:
        df = _dm.get_index_daily(code, start_d, end_d)
    except Exception as exc:  # DataError: 未 sync
        return {"empty": True, "code": code, "message": str(exc), "bars": []}
    if df is None or df.empty:
        return {"empty": True, "code": code, "message": "指数无数据,请先 sync_index。", "bars": []}
    df = df.sort_values("date").copy()
    df["pct"] = (df["close"].pct_change() * 100).round(2)
    recs = _df_to_records(df)
    last = recs[-1] if recs else None
    return {"empty": False, "code": code, "name": _INDEX_NAMES.get(code, code), "bars": recs, "last": last}


@app.get("/api/market")
def market() -> dict:
    """指数快照(上证/深证/沪深300)。无数据则 empty。"""
    codes = ["000001", "399001", "000300"]
    out = []
    for c in codes:
        try:
            df = _dm.get_index_daily(c)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df = df.sort_values("date")
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        pct = round((last["close"] - prev["close"]) / prev["close"] * 100, 2) if prev["close"] else 0.0
        out.append(
            {
                "code": c,
                "name": _INDEX_NAMES.get(c, c),
                "close": float(last["close"]),
                "pct": pct,
                "date": last["date"].isoformat() if hasattr(last["date"], "isoformat") else str(last["date"]),
            }
        )
    return {"empty": len(out) == 0, "indices": out}


@app.get("/")
def root() -> dict:
    return {"service": "AROS API", "docs": "/docs", "health": "/api/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
