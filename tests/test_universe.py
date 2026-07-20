"""Tests for the Sprint 1.13 Universe (stock-pool) engine.

Uses an isolated in-memory SQLite session; no real data or config required.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from data.models import Stock
from universe.engine import UniverseEngine


def make_engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    return UniverseEngine(session=Session())


def test_universe_add_and_get():
    ue = make_engine()
    ue.add_codes("blue_chips", ["600519", "601318"])
    ue.add_codes("blue_chips", ["600519", "000001"])  # 600519 dup, 000001 new
    codes = ue.get_codes("blue_chips")
    assert codes == ["000001", "600519", "601318"]  # de-dup + sorted


def test_universe_remove():
    ue = make_engine()
    ue.add_codes("pool", ["A", "B", "C"])
    remaining = ue.remove_codes("pool", ["B"])
    assert remaining == ["A", "C"]


def test_universe_unknown_pool_empty():
    ue = make_engine()
    assert ue.get_codes("nope") == []
    assert ue.remove_codes("nope", ["X"]) == []


def test_universe_list_and_delete():
    ue = make_engine()
    ue.add_codes("aaa", ["1"])
    ue.add_codes("bbb", ["2"])
    assert ue.list_pools() == ["aaa", "bbb"]
    assert ue.delete("aaa") is True
    assert ue.delete("aaa") is False
    assert ue.list_pools() == ["bbb"]


def test_universe_exists():
    ue = make_engine()
    assert ue.exists("x") is False
    ue.add_codes("x", ["1"])
    assert ue.exists("x") is True


def test_cli_universe_add_list():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    add = runner.invoke(main.app, ["universe", "add", "demo", "A", "B"])
    assert add.exit_code == 0, add.output
    assert "A" in add.output and "B" in add.output
    lst = runner.invoke(main.app, ["universe", "list"])
    assert lst.exit_code == 0, lst.output
    assert "demo" in lst.output


def test_universe_all_a_reads_stock_table():
    ue = make_engine()
    ue.session.add(Stock(code="000001", name="平安银行"))
    ue.session.add(Stock(code="600519", name="贵州茅台"))
    ue.session.commit()
    assert ue.get_codes("all_a") == ["000001", "600519"]


def test_universe_all_a_empty_when_no_stock_rows():
    ue = make_engine()
    assert ue.get_codes("all_a") == []


def test_all_a_provider_resolves_from_stock_list():
    import pandas as pd

    class _FakeDM:
        def get_stock_list(self):
            return pd.DataFrame([{"code": "000001"}, {"code": "600519"}])

    from research.universe_provider import AllAProvider

    prov = AllAProvider(data_manager=_FakeDM())
    assert prov.codes() == ["000001", "600519"]


def test_all_a_provider_excludes_st_by_name():
    import pandas as pd

    class _FakeDM:
        def get_stock_list(self):
            return pd.DataFrame(
                [
                    {"code": "000001", "name": "平安银行"},
                    {"code": "600519", "name": "贵州茅台"},
                    {"code": "600608", "name": "ST 某某"},
                    {"code": "000982", "name": "*ST 某某"},
                ]
            )

    from research.universe_provider import AllAProvider

    prov = AllAProvider(data_manager=_FakeDM())
    assert prov.codes() == ["000001", "600519"]  # both ST / *ST dropped


def test_universe_all_a_excludes_st():
    ue = make_engine()
    ue.session.add(Stock(code="000001", name="平安银行"))
    ue.session.add(Stock(code="600519", name="贵州茅台"))
    ue.session.add(Stock(code="600608", name="ST 某某"))
    ue.session.add(Stock(code="000982", name="*ST 某某"))
    ue.session.commit()
    assert ue.get_codes("all_a") == ["000001", "600519"]


def test_get_universe_provider_all_a():
    from research.universe_provider import AllAProvider, get_universe_provider

    prov = get_universe_provider("all_a")
    assert isinstance(prov, AllAProvider)


def test_st_filter_is_st_name():
    from data.st_filter import is_st_name

    assert is_st_name("ST 某某") is True
    assert is_st_name("*ST 某某") is True
    assert is_st_name("st 小写") is True  # case-insensitive
    assert is_st_name("贵州茅台") is False
    assert is_st_name("") is False
    assert is_st_name(None) is False


def test_filter_st_codes_drops_st_rows():
    import pandas as pd

    from data.st_filter import filter_st_codes

    df = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "600608", "name": "ST 某某"},
            {"code": "000982", "name": "*ST 某某"},
        ]
    )
    out = filter_st_codes(df)
    assert list(out["code"]) == ["000001"]
    # Defensive: no name column -> unchanged (never silently emptied)
    assert list(filter_st_codes(df[["code"]])["code"]) == ["000001", "600608", "000982"]
