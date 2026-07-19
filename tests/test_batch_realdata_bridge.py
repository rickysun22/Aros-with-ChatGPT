"""Sprint 3.2 real-data bridge test (offline, no network).

The real-data path is: ``BatchRunner`` -> its *default* ``_DmPriceProvider`` /
``_DmBenchmarkProvider`` -> ``DataManager.get_daily`` / ``get_index_daily``.
That bridge code already exists; what was missing was (a) ``akshare`` installed,
(b) data actually synced, and (c) a CLI entry point. This test proves the bridge
composition works end-to-end by feeding ``BatchRunner`` a *fake* ``DataManager``
that satisfies the exact ``get_daily`` / ``get_index_daily`` / ``get_stock_list``
surface the real bridge calls -- so the same code path a live ``akshare``-backed
``DataManager`` would exercise is exercised here, deterministically.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import get_config
from core.database import Base
from data.manager import DataManager
from research.batch import BatchRunner, _DmBenchmarkProvider, _DmPriceProvider
from research.benchmark import BenchmarkComparison, BenchmarkEngine
from research.experiment import ExperimentConfig
from research.scorecard import Scorecard, ScoreInput
from research.strategy_library import list_strategies

START = "2020-01-01"
END = "2021-12-31"


class _FakeBenchEngine(BenchmarkEngine):
    """Stand-in for BenchmarkEngine: returns zeroed comparison metrics."""

    def compare(self, *args: object, **kwargs: object) -> BenchmarkComparison:
        return BenchmarkComparison(
            benchmark_code="csi300",
            excess_return=0.0,
            alpha=0.0,
            beta=0.0,
            tracking_error=0.0,
            information_ratio=0.0,
            n_points=2,
        )


class _FakeDM(DataManager):
    """Subclass so mypy accepts it as a ``DataManager``; returns deterministic
    OHLCV for a fixed set of codes instead of hitting the provider/DB."""

    def __init__(self, codes: list[str], seed: int = 0) -> None:
        super().__init__(None)
        self._codes = list(codes)
        self.calls = 0
        rng = pd.bdate_range(START, END)
        gen = np.random.default_rng(seed)
        self._prices: dict[str, pd.DataFrame] = {}
        for code in self._codes:
            n = len(rng)
            rets = gen.normal(gen.uniform(-0.001, 0.002), 0.02, n)
            close = 10.0 * (1.0 + rets).cumprod()
            open_ = close * (1.0 + gen.normal(0, 0.003, n))
            high = np.maximum(open_, close) * (1.0 + np.abs(gen.normal(0, 0.004, n)))
            low = np.minimum(open_, close) * (1.0 - np.abs(gen.normal(0, 0.004, n)))
            vol = gen.integers(int(1e5), int(1e6), n).astype(float)
            self._prices[code] = pd.DataFrame(
                {
                    "code": code,
                    "date": rng,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": vol,
                    "amount": vol * close,
                }
            )
        idx = gen.normal(0.0005, 0.015, n)
        idx_close = 3000.0 * (1.0 + idx).cumprod()
        self._index = pd.DataFrame(
            {
                "code": "000300",
                "date": rng,
                "open": idx_close,
                "high": idx_close,
                "low": idx_close,
                "close": idx_close,
                "volume": pd.NA,
                "amount": pd.NA,
            }
        )

    def get_stock_list(self) -> pd.DataFrame:  # type: ignore[override]
        return pd.DataFrame([{"code": c, "name": c} for c in self._codes])

    def get_daily(
        self, code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        self.calls += 1
        df = self._prices.get(code)
        if df is None:
            return pd.DataFrame()
        mask = (df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))
        return df.loc[mask].reset_index(drop=True)

    def get_index_daily(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        self.calls += 1
        df = self._index
        mask = (df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))
        if as_of is not None:
            mask &= df["date"] <= pd.Timestamp(as_of)
        return df.loc[mask].reset_index(drop=True)


class _FakeUE:
    """A UniverseEngine-shaped object; only csi800 is populated."""

    def __init__(self, codes: list[str]) -> None:
        self._codes = list(codes)

    def get_codes(self, name: str) -> list[str]:
        return list(self._codes) if name == "csi800" else []


def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _pick_strategies() -> list[str]:
    specs = list_strategies()
    names = [
        next(s.spec.name for s in specs if s.spec.universe == "all_a"),
        next(s.spec.name for s in specs if s.spec.universe == "csi800"),
    ]
    return names


def _clean(d: dict[str, float | None]) -> dict[str, float]:
    return {k: float(v) for k, v in d.items() if v is not None}


def test_bridge_providers_call_datamanager() -> None:
    """The default providers must read through DataManager, never network."""
    codes = ["600000", "600519", "000001"]
    dm = _FakeDM(codes)
    cfg = get_config()

    prices = _DmPriceProvider(dm)(codes, START, END)
    assert set(prices.keys()) == set(codes)
    for df in prices.values():
        assert list(df["close"])  # non-empty, real bars returned

    bench = _DmBenchmarkProvider(dm, cfg)("csi300", START, END)
    assert isinstance(bench, pd.Series)
    assert len(bench) > 0


def test_batchrunner_uses_default_datamanager_bridge() -> None:
    """BatchRunner with a (fake) DataManager exercises the real data bridge."""
    codes = ["600000", "600519", "000001", "300750", "601318"]
    dm = _FakeDM(codes)
    ue = _FakeUE(codes)
    names = _pick_strategies()

    exp_cfg = ExperimentConfig(
        name="bridge-test",
        strategy=names[0],
        start=START,
        end=END,
        benchmark="csi300",
    )

    runner = BatchRunner(data_manager=dm, universe_engine=ue, benchmark_engine=_FakeBenchEngine())
    result = runner.run(names, exp_cfg, session=_mem_session(), regime_analysis=True)

    # The bridge was actually invoked (DataManager.get_daily / get_index_daily).
    assert dm.calls > 0
    # One outcome per requested strategy, with the AROS scorecard computable.
    assert len(result.outcomes) == len(names)
    ranked = Scorecard().score(
        [
            ScoreInput(
                name=o.name,
                metrics=_clean(o.oos_metrics),
                is_metrics=_clean(o.is_metrics),
                oos_metrics=_clean(o.oos_metrics),
            )
            for o in result.outcomes
        ]
    )
    assert len(ranked) == len(names)
    # At least one strategy produced a real (non-None) OOS total return.
    assert any(o.oos_metrics.get("total_return") is not None for o in result.outcomes)
