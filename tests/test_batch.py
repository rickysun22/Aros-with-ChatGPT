"""Tests for the Sprint 3.2 BatchRunner + persistence + regime breakdown."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.database import Base
from data.manager import DataManager
from research.batch import BatchRunner
from research.benchmark import BenchmarkComparison, BenchmarkEngine
from research.experiment import ExperimentConfig, WalkForwardSpec
from research.registry import ExperimentRegistry


def _mem_session() -> Session:
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(eng)()


def _frames(codes: list[str], start: str, end: str, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Deterministic trending OHLCV: rising close (new highs) + periodic volume
    surges, so trend/event strategies actually take positions."""
    idx = pd.date_range(start, end, freq="B")
    rng = np.random.RandomState(seed)
    out: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(codes):
        n = len(idx)
        drift = np.cumsum(rng.randn(n) * 0.05) + i * 0.5
        close = 10.0 + np.maximum.accumulate(drift)  # monotonic-ish up -> new highs
        vol = np.full(n, 1_000_000.0)
        # volume surges every ~20 bars -> vol_ratio spikes above the breakout gate
        vol[::20] = 5_000_000.0
        out[code] = pd.DataFrame(
            {
                "open": (close * 0.99).round(3),
                "high": (close * 1.02).round(3),
                "low": (close * 0.98).round(3),
                "close": close.round(3),
                "volume": vol,
            },
            index=idx,
        )
    return out


def _price_provider(codes: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    return _frames(codes, start, end, seed=hash(tuple(codes)) % 1000)


def _bench_provider(key: str, start: str, end: str) -> pd.Series:
    idx = pd.date_range(start, end, freq="B")
    rng = np.random.RandomState(7)
    close = 3000.0 + np.cumsum(rng.randn(len(idx)) * 5)
    return pd.Series(close, index=idx)


class _FakeUE:
    """Point-in-time stub: csi800 -> a small fixed, seeded code list (D6 guard)."""

    def get_codes(self, name: str) -> list[str]:
        return ["600000", "600036", "000001", "000002"]


class _FakeDM(DataManager):
    """Subclass so mypy accepts it as a ``DataManager``; only ``get_stock_list``
    (used for the ``all_a`` universe) is exercised in tests."""

    def get_stock_list(self) -> pd.DataFrame:  # type: ignore[override]
        return pd.DataFrame({"code": ["600000", "600036"]})


class _FakeBenchEngine(BenchmarkEngine):
    """Injectable benchmark engine so the ``bench_*`` merge path is exercised
    without a real index database."""

    def __init__(self) -> None:
        super().__init__(None)

    def compare(self, portfolio_equity, benchmark_code, range, risk_free=None, as_of=None):
        return BenchmarkComparison(
            benchmark_code=benchmark_code,
            excess_return=0.05,
            alpha=0.01,
            beta=1.0,
            tracking_error=0.02,
            information_ratio=0.5,
            n_points=int(len(portfolio_equity)),
        )


def _config(walk_forward: bool) -> ExperimentConfig:
    wf = WalkForwardSpec(train_years=1, test_years=1, step_years=1) if walk_forward else None
    return ExperimentConfig(
        name="batch_test",
        strategy="n/a",
        start="2021-01-01",
        end="2023-12-31",
        benchmark="csi300",
        walk_forward=wf,
    )


def test_batch_runs_two_strategies_and_persists() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    res = runner.run(["ma_bull", "high_breakout"], _config(True), session=session)

    assert len(res.outcomes) == 2
    for o in res.outcomes:
        assert o.run_id.startswith("exp_")
        assert "sharpe" in o.is_metrics
        assert "sharpe" in o.oos_metrics
        # benchmark_return is computed by the event engine via the injected
        # benchmark provider (always present, even without a benchmark engine).
        assert "benchmark_return" in o.is_metrics
        # fold metrics carry the IS/OOS windows
        assert "is_0" in o.fold_metrics and "oos_0" in o.fold_metrics


def test_load_result_reproduces_batch_run() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    res = runner.run(["ma_bull"], _config(True), session=session)
    run_id = res.outcomes[0].run_id

    loaded = ExperimentRegistry(session).load_result(run_id)
    assert loaded is not None
    # 2021-2023 with 1y/1y walk-forward yields a single fold (is_0/oos_0) plus
    # the aggregated is_agg/oos_agg windows.
    assert loaded.windows == ["is_0", "oos_0", "is_agg", "oos_agg"]
    # The persisted IS window metrics equal what the runner reported.
    assert loaded.metrics["is_0"]["sharpe"] == res.outcomes[0].fold_metrics["is_0"]["sharpe"]


def test_regime_breakdown_populated_when_trades_exist() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    res = runner.run(["high_breakout"], _config(True), session=session)
    # high_breakout fires on volume surges -> at least one regime bucket exists.
    assert res.outcomes[0].regime_breakdown
    for bucket in res.outcomes[0].regime_breakdown.values():
        assert bucket["n_trades"] >= 1
        assert "mean_return" in bucket


def test_single_window_no_walk_forward() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    res = runner.run(["ma_bull"], _config(False), session=session)
    o = res.outcomes[0]
    assert "full" in o.fold_metrics
    assert "is_agg" in o.fold_metrics and "oos_agg" in o.fold_metrics
    # Without walk-forward, IS == OOS == full.
    assert o.is_metrics == o.oos_metrics
    loaded = ExperimentRegistry(session).load_result(o.run_id)
    assert loaded is not None
    assert "full" in loaded.windows


def test_all_a_universe_resolves_via_data_manager() -> None:
    session = _mem_session()
    runner = BatchRunner(
        data_manager=_FakeDM(),  # provides get_stock_list for the all_a universe
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    # first_board is an all_a (emotion) strategy -> must resolve via data_manager.
    res = runner.run(["first_board"], _config(False), session=session)
    assert len(res.outcomes) == 1
    assert res.outcomes[0].name == "first_board"


def test_run_all_ten_strategies() -> None:
    session = _mem_session()
    runner = BatchRunner(
        data_manager=_FakeDM(),
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    cfg = ExperimentConfig(
        name="all",
        strategy="n/a",
        start="2021-01-01",
        end="2023-12-31",
        benchmark="csi300",
        walk_forward=WalkForwardSpec(train_years=1, test_years=1, step_years=1),
    )
    res = runner.run_all(cfg, session=session)
    # All 10 registered strategies ran and produced an outcome each.
    assert len(res.outcomes) == 10
    names = {o.name for o in res.outcomes}
    assert "ma_bull" in names and "high_breakout" in names and "first_board" in names


def test_benchmark_relative_metrics_merged_via_engine() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
        benchmark_engine=_FakeBenchEngine(),
    )
    res = runner.run(["ma_bull"], _config(True), session=session)
    o = res.outcomes[0]
    # The injected engine's bench_* metrics must be merged into every window.
    assert o.is_metrics.get("bench_excess_return") == 0.05
    assert o.oos_metrics.get("bench_beta") == 1.0
    assert "bench_information_ratio" in o.fold_metrics["is_0"]


def test_unknown_strategy_raises() -> None:
    session = _mem_session()
    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    with pytest.raises(KeyError):
        runner.run(["does_not_exist"], _config(False), session=session)
