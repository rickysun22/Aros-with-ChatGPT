"""Tests for the Sprint 2.0 foundation (Phase 2).

Covers the 2.0 test contract:
* IndexBar ORM round-trip + unique (code, date)
* DataManager.get_index_daily via a fake provider (columns normalized)
* get_index_daily ``as_of`` no-look-ahead ceiling
* missing benchmark -> DataError
* ExperimentRegistry CRUD + config_json round-trip
* ExperimentMetric unique (run_id, metric_name, is_oos, window)
* real settings.yaml wires the benchmark + research sections
* network-gated real-index smoke (skipped offline / unless opted in)

All non-network tests use isolated in-memory or temp SQLite -- no real data.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backtest.portfolio import PortfolioResult
from core.config import get_config
from core.database import Base
from core.exceptions import ConfigError, DataError
from data.manager import DataManager
from data.models import IndexBar
from data.provider import normalize_index_daily
from research.benchmark import BenchmarkEngine
from research.experiment import ExperimentConfig
from research.models import ExperimentEquity, ExperimentMetric
from research.registry import ExperimentRegistry
from research.runner import ResearchRunner


# --------------------------------------------------------------------------- #
# Fake index provider (no network) -- multi-day so as_of is meaningful
# --------------------------------------------------------------------------- #
class FakeIndexProvider:
    """In-memory :class:`DataProvider` serving canned index bars."""

    def __init__(self) -> None:
        self._bars = pd.DataFrame(
            [
                {
                    "code": "000300",
                    "date": date(2024, 1, 2),
                    "open": 3000.0,
                    "high": 3020.0,
                    "low": 2990.0,
                    "close": 3010.0,
                    "volume": None,
                    "amount": None,
                },
                {
                    "code": "000300",
                    "date": date(2024, 1, 3),
                    "open": 3010.0,
                    "high": 3050.0,
                    "low": 3005.0,
                    "close": 3040.0,
                    "volume": None,
                    "amount": None,
                },
                {
                    "code": "000300",
                    "date": date(2024, 1, 4),
                    "open": 3040.0,
                    "high": 3060.0,
                    "low": 3020.0,
                    "close": 3025.0,
                    "volume": None,
                    "amount": None,
                },
            ]
        )

    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "name"])

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            columns=["code", "date", "open", "high", "low", "close", "volume", "amount"]
        )

    def get_index_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        mask = (self._bars["date"] >= start_date) & (self._bars["date"] <= end_date)
        return self._bars[self._bars["code"].eq(code) & mask].reset_index(drop=True)


@pytest.fixture
def dm(tmp_path, monkeypatch: pytest.MonkeyPatch) -> DataManager:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return DataManager(provider=FakeIndexProvider())


def _mem_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# --------------------------------------------------------------------------- #
# Normalization (pure)
# --------------------------------------------------------------------------- #
def test_normalize_index_daily() -> None:
    raw = pd.DataFrame(
        [
            {
                "日期": "2024-01-03",
                "开盘": 3010,
                "最高": 3050,
                "最低": 3005,
                "收盘": 3040,
                "成交量": None,
                "成交额": None,
            },
            {
                "日期": "2024-01-02",
                "开盘": 3000,
                "最高": 3020,
                "最低": 2990,
                "收盘": 3010,
                "成交量": None,
                "成交额": None,
            },
        ]
    )
    out = normalize_index_daily(raw, "000300")
    assert list(out.columns) == ["code", "date", "open", "high", "low", "close", "volume", "amount"]
    assert out.iloc[0]["date"] == date(2024, 1, 2)  # sorted ascending
    assert out.iloc[0]["code"] == "000300"


def test_normalize_index_daily_missing_columns_raises() -> None:
    with pytest.raises(DataError):
        normalize_index_daily(pd.DataFrame([{"日期": "2024-01-02"}]), "000300")


# --------------------------------------------------------------------------- #
# IndexBar ORM
# --------------------------------------------------------------------------- #
def test_index_bar_roundtrip() -> None:
    session = _mem_session()
    session.add(
        IndexBar(
            code="000300", date=date(2024, 1, 2), open=3000.0, high=3020.0, low=2990.0, close=3010.0
        )
    )
    session.commit()
    stored = session.query(IndexBar).one()
    assert stored.code == "000300"
    assert stored.close == 3010.0
    # unique (code, date) enforced
    session.add(
        IndexBar(code="000300", date=date(2024, 1, 2), open=1.0, high=1.0, low=1.0, close=1.0)
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --------------------------------------------------------------------------- #
# DataManager index accessors
# --------------------------------------------------------------------------- #
def test_get_index_daily_fake(dm: DataManager) -> None:
    assert dm.sync_index("000300", date(2024, 1, 1), date(2024, 1, 31)) == 3
    out = dm.get_index_daily("000300", date(2024, 1, 1), date(2024, 1, 31))
    assert list(out.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert len(out) == 3
    assert out.iloc[0]["date"] == date(2024, 1, 2)


def test_get_index_daily_as_of_no_lookahead(dm: DataManager) -> None:
    dm.sync_index("000300", date(2024, 1, 1), date(2024, 1, 31))
    out = dm.get_index_daily("000300", as_of=date(2024, 1, 3))
    # Only bars on or before as_of are visible; the 2024-01-04 bar is hidden.
    assert out["date"].max() == date(2024, 1, 3)
    assert date(2024, 1, 4) not in set(out["date"])


def test_get_index_daily_missing_raises(dm: DataManager) -> None:
    with pytest.raises(DataError):
        dm.get_index_daily("999999", date(2024, 1, 1), date(2024, 1, 31))


# --------------------------------------------------------------------------- #
# Experiment persistence
# --------------------------------------------------------------------------- #
def test_experiment_registry_crud() -> None:
    reg = ExperimentRegistry(session=_mem_session())
    cfg = ExperimentConfig(
        name="demo",
        strategy="weighted_momentum",
        start="2020-01-01",
        end="2021-01-01",
        codes=["600000"],
    )
    run_id = reg.create("demo", cfg.model_dump_json())
    assert run_id.startswith("exp_")

    fetched = reg.get(run_id)
    assert fetched is not None
    assert fetched.name == "demo"
    # config_json round-trips back into an equivalent ExperimentConfig
    assert ExperimentConfig.model_validate_json(fetched.config_json).strategy == "weighted_momentum"

    assert [r.id for r in reg.list()] == [run_id]
    assert reg.delete(run_id) is True
    assert reg.delete(run_id) is False
    assert reg.get(run_id) is None


def test_experiment_metric_unique() -> None:
    session = _mem_session()
    session.add(
        ExperimentMetric(
            run_id="exp_x", metric_name="sharpe", value=1.2, is_oos=False, window="full"
        )
    )
    session.commit()
    session.add(
        ExperimentMetric(
            run_id="exp_x", metric_name="sharpe", value=9.9, is_oos=False, window="full"
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_experiment_config_rejects_both_sources() -> None:
    with pytest.raises(ValueError):
        ExperimentConfig(
            name="bad",
            strategy="s",
            start="2020-01-01",
            end="2021-01-01",
            universe="pool",
            codes=["600000"],
        )


def test_experiment_run_uuid_pk_is_unique() -> None:
    reg = ExperimentRegistry(session=_mem_session())
    cfg = ExperimentConfig(
        name="a", strategy="s", start="2020-01-01", end="2021-01-01", codes=["600000"]
    )
    id1 = reg.create("a", cfg.model_dump_json())
    id2 = reg.create("b", cfg.model_dump_json())
    assert id1 != id2  # short-uuid primary keys


# --------------------------------------------------------------------------- #
# Config wiring
# --------------------------------------------------------------------------- #
def test_research_config_wiring() -> None:
    from core.config import AppConfig

    cfg = AppConfig.from_file()
    assert cfg.benchmark.default == "csi300"
    assert cfg.benchmark.indices["csi300"] == "000300"
    assert cfg.research.experiment_id_prefix == "exp_"


# --------------------------------------------------------------------------- #
# Real-data smoke (network-gated)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    os.getenv("AROS_RUN_NETWORK_TESTS") != "1",
    reason="network-gated: set AROS_RUN_NETWORK_TESTS=1 to fetch a real index",
)
def test_smoke_real_index(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # pragma: no cover
    from research.experiment import ExperimentConfig as _Cfg

    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'smoke.db'}")
    manager = DataManager()  # real AkShareProvider
    n = manager.sync_index("000300", date(2024, 1, 1), date(2024, 3, 1))
    assert n > 0
    bars = manager.get_index_daily("000300", date(2024, 1, 1), date(2024, 3, 1))
    assert not bars.empty

    reg = ExperimentRegistry()
    run_id = reg.create(
        "smoke",
        _Cfg(
            name="smoke",
            strategy="weighted_momentum",
            start="2024-01-01",
            end="2024-03-01",
            codes=["600000"],
        ).model_dump_json(),
    )
    assert reg.get(run_id) is not None


# --------------------------------------------------------------------------- #
# Sprint 2.3 -- BenchmarkEngine.compare
# --------------------------------------------------------------------------- #
_DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]


class FakeDataManager:
    """Injectable stand-in for :class:`DataManager` serving one benchmark frame.

    Honours the ``as_of`` / ``[start, end]`` window exactly like the real
    :meth:`DataManager.get_index_daily`, and raises :class:`DataError` when the
    resulting window is empty so a missing benchmark is never silently ignored.
    """

    def __init__(self, bench: pd.DataFrame | None) -> None:
        self.config = get_config()
        self._bench = bench

    def get_index_daily(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        if self._bench is None or self._bench.empty:
            raise DataError(f"No index data for benchmark {code!r}")
        df = self._bench.copy()
        if start_date is not None:
            df = df[df["date"] >= start_date]
        if end_date is not None:
            df = df[df["date"] <= end_date]
        if as_of is not None:
            df = df[df["date"] <= as_of]
        if df.empty:
            raise DataError(f"No index data for benchmark {code!r} in window")
        return df.reset_index(drop=True)


def _bench_frame(closes: list[float], dates: list[date] | None = None) -> pd.DataFrame:
    dts = dates or _DATES[: len(closes)]
    return pd.DataFrame({"date": dts, "close": [float(c) for c in closes]})


def _pe(closes: list[float], dates: list[date] | None = None) -> pd.Series:
    dts = dates or _DATES[: len(closes)]
    return pd.Series([float(c) for c in closes], index=pd.DatetimeIndex(dts))


def _ref_metrics(
    pe_close: list[float], be_close: list[float], rf: float = 0.0
) -> tuple[float, float, float, float, float]:
    """Independent parallel computation of the five benchmark metrics."""
    import numpy as np

    pe = np.asarray(pe_close, dtype=float)
    be = np.asarray(be_close, dtype=float)

    def dr(x: np.ndarray) -> np.ndarray:
        r = np.zeros_like(x)
        r[1:] = x[1:] / x[:-1] - 1.0
        return r

    r_p, r_b = dr(pe), dr(be)
    rf_d = (1.0 + rf) ** (1.0 / 252) - 1.0
    excess_return = (pe[-1] / pe[0] - 1.0) - (be[-1] / be[0] - 1.0)
    var_b = float(np.var(r_b, ddof=1))
    beta = 0.0 if var_b == 0.0 else float(np.cov(r_p, r_b, ddof=1)[0, 1] / var_b)
    alpha = float(((r_p - rf_d).mean() - beta * (r_b - rf_d).mean()) * 252)
    active = r_p - r_b
    te = float(active.std(ddof=1) * np.sqrt(252))
    ir = 0.0 if te == 0.0 else float(active.mean() * 252 / te)
    return excess_return, alpha, beta, te, ir


def test_benchmark_equal() -> None:
    closes = [100.0, 101.0, 103.0, 102.0]
    eng = BenchmarkEngine(FakeDataManager(_bench_frame(closes)))
    res = eng.compare(_pe(closes), "csi300", ("2024-01-01", "2024-01-31"), risk_free=0.0)
    assert res.n_points == 4
    assert res.beta == pytest.approx(1.0, abs=1e-9)
    assert res.excess_return == pytest.approx(0.0, abs=1e-9)
    assert res.alpha == pytest.approx(0.0, abs=1e-9)
    assert res.tracking_error == pytest.approx(0.0, abs=1e-9)
    assert res.information_ratio == pytest.approx(0.0, abs=1e-9)


def test_benchmark_beta_zero() -> None:
    # Flat portfolio (constant equity) vs a moving benchmark => beta == 0.
    flat = [100.0, 100.0, 100.0, 100.0]
    bench = [100.0, 101.0, 103.0, 102.0]
    eng = BenchmarkEngine(FakeDataManager(_bench_frame(bench)))
    res = eng.compare(_pe(flat), "csi300", ("2024-01-01", "2024-01-31"), risk_free=0.0)
    assert res.beta == pytest.approx(0.0, abs=1e-9)
    assert res.tracking_error > 0.0
    assert res.information_ratio == res.information_ratio  # finite (not NaN)


def test_benchmark_hand_values() -> None:
    pe_close = [100.0, 102.0, 101.0, 104.0]
    be_close = [100.0, 101.0, 102.0, 101.0]
    eng = BenchmarkEngine(FakeDataManager(_bench_frame(be_close)))
    res = eng.compare(_pe(pe_close), "csi300", ("2024-01-01", "2024-01-31"), risk_free=0.0)
    exp_er, exp_alpha, exp_beta, exp_te, exp_ir = _ref_metrics(pe_close, be_close, 0.0)
    assert res.excess_return == pytest.approx(exp_er, abs=1e-9)
    assert res.alpha == pytest.approx(exp_alpha, abs=1e-9)
    assert res.beta == pytest.approx(exp_beta, abs=1e-9)
    assert res.tracking_error == pytest.approx(exp_te, abs=1e-9)
    assert res.information_ratio == pytest.approx(exp_ir, abs=1e-9)
    # to_dict drops the label and keeps numeric metrics only.
    d = res.to_dict()
    assert "benchmark_code" not in d
    assert d["beta"] == pytest.approx(exp_beta, abs=1e-9)


def test_benchmark_no_lookahead() -> None:
    pe_close = [100.0, 102.0, 101.0, 104.0]  # portfolio ends 2024-01-05
    # Benchmark has an extra later bar (2024-01-08) the portfolio never saw.
    bench_dates = [*_DATES, date(2024, 1, 8)]
    bench = _bench_frame([100.0, 101.0, 102.0, 101.0, 150.0], bench_dates)
    eng = BenchmarkEngine(FakeDataManager(bench))

    # Default as_of caps at the portfolio's last date => the 01-08 bar is hidden.
    res_default = eng.compare(_pe(pe_close), "csi300", ("2024-01-01", "2024-01-31"), risk_free=0.0)
    assert res_default.n_points == 4

    # Explicit as_of before the portfolio end => only the non-leaking window.
    res_trunc = eng.compare(
        _pe(pe_close), "csi300", ("2024-01-01", "2024-01-31"), risk_free=0.0, as_of="2024-01-04"
    )
    assert res_trunc.n_points == 3
    exp_er, *_ = _ref_metrics(pe_close[:3], [100.0, 101.0, 102.0], 0.0)
    assert res_trunc.excess_return == pytest.approx(exp_er, abs=1e-9)


def test_benchmark_missing_data() -> None:
    eng = BenchmarkEngine(FakeDataManager(None))
    with pytest.raises(DataError):
        eng.compare(_pe([100.0, 101.0]), "csi300", ("2024-01-01", "2024-01-31"))


def test_benchmark_unknown_key() -> None:
    eng = BenchmarkEngine(FakeDataManager(_bench_frame([100.0, 101.0])))
    with pytest.raises(ConfigError):
        eng.compare(_pe([100.0, 101.0]), "does_not_exist", ("2024-01-01", "2024-01-31"))


# --------------------------------------------------------------------------- #
# Sprint 2.1 -- research CLI surface + registry.delete cascade
# --------------------------------------------------------------------------- #
def _invoke(args: list[str]):
    from typer.testing import CliRunner

    import main

    return CliRunner().invoke(main.app, args)


def _run_id_from(output: str) -> str:
    m = re.search(r"Created experiment (exp_\w+)", output)
    assert m is not None, output
    return m.group(1)


def test_cli_research_init_flags(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    result = _invoke(
        [
            "research",
            "init",
            "--name",
            "exp1",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--codes",
            "600000,600519",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "Created experiment exp_" in result.output


def test_cli_research_init_config_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(
        json.dumps(
            {
                "name": "fromfile",
                "strategy": "weighted_momentum",
                "start": "2024-01-01",
                "end": "2024-03-01",
                "codes": ["600000"],
            }
        ),
        encoding="utf-8",
    )
    init = _invoke(["research", "init", "--config", str(cfg_path)])
    assert init.exit_code == 0, init.output
    rid = _run_id_from(init.output)
    show = _invoke(["research", "show", rid])
    assert show.exit_code == 0, show.output
    assert '"name": "fromfile"' in show.output
    assert '"strategy": "weighted_momentum"' in show.output


def test_cli_research_init_both_sources_fails(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    result = _invoke(
        [
            "research",
            "init",
            "--name",
            "x",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--universe",
            "U",
            "--codes",
            "600000",
        ]
    )
    assert result.exit_code != 0


def test_cli_research_init_unknown_universe_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    result = _invoke(
        [
            "research",
            "init",
            "--name",
            "x",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--universe",
            "does_not_exist",
        ]
    )
    assert result.exit_code == 1
    assert "empty or unknown" in result.output


def test_cli_research_init_dry_run(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    result = _invoke(
        [
            "research",
            "init",
            "--name",
            "dry",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--codes",
            "600000",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "(not persisted)" in result.output
    lst = _invoke(["research", "list"])
    assert "No experiments yet." in lst.output


def test_cli_research_list_show_delete(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'research.db'}")
    init = _invoke(
        [
            "research",
            "init",
            "--name",
            "lifecycle",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--codes",
            "600000",
        ]
    )
    assert init.exit_code == 0, init.output
    rid = _run_id_from(init.output)
    lst = _invoke(["research", "list"])
    assert rid in lst.output
    show = _invoke(["research", "show", rid])
    assert show.exit_code == 0
    assert '"name": "lifecycle"' in show.output
    deleted = _invoke(["research", "delete", rid])
    assert "deleted" in deleted.output
    again = _invoke(["research", "delete", rid])
    assert again.exit_code == 1


def test_registry_delete_cascades(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'cascade.db'}")
    from research.experiment import ExperimentConfig
    from research.models import ExperimentMetric

    reg = ExperimentRegistry()
    rid = reg.create(
        "cascade",
        ExperimentConfig(
            name="cascade",
            strategy="weighted_momentum",
            start="2024-01-01",
            end="2024-03-01",
            codes=["600000"],
        ).model_dump_json(),
    )
    reg.session.add(ExperimentMetric(run_id=rid, metric_name="sharpe", value=0.42))
    reg.session.commit()
    assert reg.session.query(ExperimentMetric).filter_by(run_id=rid).count() == 1
    assert reg.delete(rid) is True
    assert reg.session.query(ExperimentMetric).filter_by(run_id=rid).count() == 0
    assert reg.get(rid) is None


# --------------------------------------------------------------------------- #
# Sprint 2.4 -- ResearchRunner end-to-end orchestration + persistence
# --------------------------------------------------------------------------- #
def _fake_portfolio_fn(equity_close: list[float], dates: list[date] | None = None):
    """Return a ``portfolio_fn`` seam yielding a canned :class:`PortfolioResult`."""

    def _fn(codes: list[str], dm: Any, start: date, end: date) -> PortfolioResult:
        return PortfolioResult(
            equity=_pe(equity_close, dates),
            metrics={},
            selections=[],
            trades=pd.DataFrame(),  # empty blotter is safe for compute_metrics
        )

    return _fn


def _runner_for(
    bench_closes: list[float],
    bench_dates: list[date] | None = None,
    pf_closes: list[float] | None = None,
    config: ExperimentConfig | None = None,
) -> tuple[ResearchRunner, ExperimentConfig]:
    """Wire a :class:`ResearchRunner` with injected fakes (no network / no real IO)."""
    bench = _bench_frame(bench_closes, bench_dates)
    dm = FakeDataManager(bench)
    runner = ResearchRunner(
        data_manager=dm,
        portfolio_fn=_fake_portfolio_fn(pf_closes if pf_closes is not None else bench_closes),
        benchmark_engine=BenchmarkEngine(dm),
        config=get_config(),
    )
    cfg = config or ExperimentConfig(
        name="r1",
        strategy="weighted_momentum",
        start="2024-01-01",
        end="2024-01-31",
        codes=["600000"],
        benchmark="csi300",
        metrics=["total_return", "sharpe", "max_drawdown", "sortino", "benchmark_return"],
    )
    return runner, cfg


def test_runner_end_to_end_persists() -> None:
    session = _mem_session()
    runner, cfg = _runner_for([100.0, 101.0, 102.0, 101.0], pf_closes=[100.0, 102.0, 101.0, 104.0])
    result = runner.run(cfg, session=session, notes="t")
    assert result.run_id.startswith("exp_")
    assert result.windows == ["full"]

    combined = result.metrics["full"]
    assert "total_return" in combined
    assert "bench_beta" in combined
    assert "bench_excess_return" in combined

    # Benchmark metrics match the independent reference, capped at the portfolio end.
    exp_er, exp_alpha, exp_beta, exp_te, exp_ir = _ref_metrics(
        [100.0, 102.0, 101.0, 104.0], [100.0, 101.0, 102.0, 101.0], 0.0
    )
    assert combined["bench_excess_return"] == pytest.approx(exp_er, abs=1e-9)
    assert combined["bench_beta"] == pytest.approx(exp_beta, abs=1e-9)
    assert combined["bench_alpha"] == pytest.approx(exp_alpha, abs=1e-9)
    assert combined["bench_tracking_error"] == pytest.approx(exp_te, abs=1e-9)
    assert combined["bench_information_ratio"] == pytest.approx(exp_ir, abs=1e-9)

    # Persistence: run marked done, metric + equity rows recorded.
    reg = ExperimentRegistry(session=session)
    run = reg.get(result.run_id)
    assert run is not None
    assert run.status == "done"
    assert run.notes == "t"
    names = {
        r.metric_name for r in session.query(ExperimentMetric).filter_by(run_id=result.run_id).all()
    }
    assert "bench_beta" in names and "total_return" in names
    eq_rows = session.query(ExperimentEquity).filter_by(run_id=result.run_id).all()
    assert len(eq_rows) == 1
    assert len(json.loads(eq_rows[0].equity_json)) == 4


def test_runner_no_lookahead() -> None:
    # Benchmark carries an extra later bar (2024-01-08) the portfolio never saw.
    bench_dates = [*_DATES, date(2024, 1, 8)]
    bench_closes = [100.0, 101.0, 102.0, 101.0, 150.0]
    session = _mem_session()
    runner, cfg = _runner_for(
        bench_closes, bench_dates=bench_dates, pf_closes=[100.0, 102.0, 101.0, 104.0]
    )
    result = runner.run(cfg, session=session)
    # The 01-08 bar must NOT leak: metrics match the 4-point (in-window) reference.
    exp_er, exp_alpha, exp_beta, exp_te, exp_ir = _ref_metrics(
        [100.0, 102.0, 101.0, 104.0], [100.0, 101.0, 102.0, 101.0], 0.0
    )
    assert result.metrics["full"]["bench_beta"] == pytest.approx(exp_beta, abs=1e-9)
    assert result.metrics["full"]["bench_excess_return"] == pytest.approx(exp_er, abs=1e-9)
    assert result.metrics["full"]["bench_tracking_error"] == pytest.approx(exp_te, abs=1e-9)
    assert result.metrics["full"]["bench_information_ratio"] == pytest.approx(exp_ir, abs=1e-9)


def test_runner_missing_benchmark_raises() -> None:
    runner, cfg = _runner_for(
        [],
        pf_closes=[100.0, 102.0, 101.0, 104.0],
        config=ExperimentConfig(
            name="r",
            strategy="weighted_momentum",
            start="2024-01-01",
            end="2024-01-31",
            codes=["600000"],
            benchmark="csi300",
            metrics=["total_return", "benchmark_return"],
        ),
    )
    # Force the data manager to have no benchmark data.
    runner._dm = FakeDataManager(None)
    runner._benchmark_engine = BenchmarkEngine(runner._dm)
    with pytest.raises(DataError):
        runner.run(cfg, session=_mem_session())


def test_runner_unknown_benchmark_key_raises() -> None:
    runner, cfg = _runner_for(
        [100.0, 101.0, 102.0, 101.0],
        pf_closes=[100.0, 102.0, 101.0, 104.0],
        config=ExperimentConfig(
            name="r",
            strategy="weighted_momentum",
            start="2024-01-01",
            end="2024-01-31",
            codes=["600000"],
            benchmark="nope",
            metrics=["total_return", "benchmark_return"],
        ),
    )
    with pytest.raises(ConfigError):
        runner.run(cfg, session=_mem_session())


def test_runner_empty_candidates_raises() -> None:
    runner, cfg = _runner_for(
        [100.0, 101.0, 102.0, 101.0],
        config=ExperimentConfig(
            name="r",
            strategy="weighted_momentum",
            start="2024-01-01",
            end="2024-01-31",
            codes=[],
            benchmark="csi300",
            metrics=["total_return", "benchmark_return"],
        ),
    )
    with pytest.raises(DataError):
        runner.run(cfg, session=_mem_session())


def test_cli_research_run_dry_run(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AROS_DATABASE_URL", f"sqlite:///{tmp_path / 'run.db'}")
    result = _invoke(
        [
            "research",
            "run",
            "--name",
            "dryrun",
            "--strategy",
            "weighted_momentum",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-01",
            "--codes",
            "600000",
            "--dry-run",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "(not executed)" in result.output
    assert '"name": "dryrun"' in result.output
    # Nothing persisted: dry-run never calls the runner.
    lst = _invoke(["research", "list"])
    assert "No experiments yet." in lst.output
