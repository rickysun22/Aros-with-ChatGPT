"""向 AROS 库写入合成日线,用于在本机无 akshare/无网络时端到端验证桥接服务。

这不是真实行情,仅用于演示:写入后 /api/factors/{code} 返回的指标与 8 因子,
全部由 AROS 的 IndicatorEngine / FactorEngine 在落库数据上实时算出。

真实数据请改用: python main.py sync --list && python main.py sync --code 600000

运行: python seed_demo.py
可选: python seed_demo.py --reset   (先清空这些标的的旧数据)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402

from core.config import get_config  # noqa: E402
from core.database import Base, get_engine, get_sessionmaker  # noqa: E402
from data.models import DailyBar, Stock  # noqa: E402

# 演示标的(代码, 名称, 起始价)
DEMO = [
    ("600000", "浦发银行", 9.5),
    ("600519", "贵州茅台", 1680.0),
    ("000001", "平安银行", 11.2),
    ("300750", "宁德时代", 185.0),
    ("000858", "五粮液", 145.0),
    ("601318", "中国平安", 48.0),
    ("000333", "美的集团", 62.0),
    ("600036", "招商银行", 35.0),
]

N_DAYS = 260
SEED = 42


def _trading_days(n: int, end: date) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:  # 跳过周末
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def main(reset: bool = False) -> None:
    cfg = get_config()
    engine = get_engine(cfg.database.url)
    Base.metadata.create_all(engine)
    Session = get_sessionmaker(engine)

    rng = np.random.default_rng(SEED)
    end = date(2026, 6, 30)
    days = _trading_days(N_DAYS, end)

    with Session() as s:
        for code, name, price0 in DEMO:
            # 股票主记录
            s.merge(Stock(code=code, name=name))
            if reset:
                s.query(DailyBar).filter(DailyBar.code == code).delete()

            # 随机游走生成 OHLCV(确定性的,便于复现)
            drift = rng.normal(0.0003, 0.012, N_DAYS)
            closes = price0 * np.exp(np.cumsum(drift))
            bars = []
            prev = price0
            for i, d in enumerate(days):
                close = round(float(closes[i]), 2)
                open_ = round(float(prev * (1 + rng.normal(0, 0.004))), 2)
                high = round(float(max(open_, close) * (1 + abs(rng.normal(0, 0.008)))), 2)
                low = round(float(min(open_, close) * (1 - abs(rng.normal(0, 0.008)))), 2)
                vol = int(rng.integers(5_000_000, 60_000_000))
                amount = round(float(vol * close / 100), 2)  # 百元手估算,仅演示
                bars.append(
                    DailyBar(
                        code=code, date=d, open=open_, high=high,
                        low=low, close=close, volume=float(vol), amount=amount,
                    )
                )
                prev = close
            s.bulk_save_objects(bars, update_changed_only=False)
            print(f"  + {code} {name}: {N_DAYS} 根日线 ({days[0]} ~ {days[-1]})")
        s.commit()
    print("合成数据写入完成。启动服务后访问 /api/factors/600000 即可看到真实计算的指标与因子。")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    main(reset=args.reset)
