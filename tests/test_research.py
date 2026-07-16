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

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.exceptions import DataError
from data.manager import DataManager
from data.models import IndexBar
from data.provider import normalize_index_daily
from research.experiment import ExperimentConfig
from research.models import ExperimentMetric
from research.registry import ExperimentRegistry


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
