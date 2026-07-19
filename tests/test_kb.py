"""Tests for the Phase 4.0 Strategy Knowledge Base (kb.py) + UniverseProvider."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.kb import RawPool, StrategyRegistry
from research.universe_provider import (
    CSI800Provider,
    CustomProvider,
    WatchlistProvider,
    get_universe_provider,
)
from universe.engine import UniverseEngine


def _mem_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(eng)()


class _FakeUE(UniverseEngine):
    """Stub UniverseEngine: csi800 -> a small fixed code list."""

    def get_codes(self, name: str) -> list[str]:
        return ["600000", "600036", "000001", "000002"]


# --------------------------------------------------------------------------- #
# Raw pool
# --------------------------------------------------------------------------- #
def test_add_raw_and_list() -> None:
    session = _mem_session()
    sid = RawPool(session).add("my idea", source="book", description="breakout on volume")
    assert sid.startswith("RAW-")
    rows = RawPool(session).list()
    assert len(rows) == 1
    assert rows[0].name == "my idea" and rows[0].status == "raw"
    assert RawPool(session).get(sid) is not None


def test_raw_set_status() -> None:
    session = _mem_session()
    sid = RawPool(session).add("x")
    assert RawPool(session).set_status(sid, "pending_validation")
    raw = RawPool(session).get(sid)
    assert raw is not None
    assert raw.status == "pending_validation"
    assert RawPool(session).set_status("nope", "raw") is False


# --------------------------------------------------------------------------- #
# Strategy registry seed
# --------------------------------------------------------------------------- #
def test_seed_builtins_seeds_ten_active() -> None:
    session = _mem_session()
    n = StrategyRegistry(session).seed_builtins()
    assert n == 10
    rows = StrategyRegistry(session).list_active()
    assert len(rows) == 10
    for r in rows:
        assert r.status == "active"
        assert r.executable_ref  # strategy_library registration name
        assert r.best_fit_regimes  # JSON list, non-empty


def test_seed_is_idempotent() -> None:
    session = _mem_session()
    first = StrategyRegistry(session).seed_builtins()
    # second run adds nothing new (idempotent) but the library still has 10
    second = StrategyRegistry(session).seed_builtins()
    assert first == 10
    assert second == 0
    assert len(StrategyRegistry(session).list_active()) == 10


def test_registry_update_validation_and_retire() -> None:
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    ok = StrategyRegistry(session).update_validation(
        "ma_bull",
        validation_run_id="exp_x",
        quality_star=4,
        reliability_score=82.0,
        gate_passed=True,
    )
    assert ok is True
    row = StrategyRegistry(session).get("ma_bull")
    assert row is not None
    assert row.quality_star == 4
    assert row.reliability_score == 82.0
    assert row.gate_passed is True
    assert row.status == "active"
    assert StrategyRegistry(session).retire("ma_bull") is True
    retired = StrategyRegistry(session).get("ma_bull")
    assert retired is not None
    assert retired.status == "retired"


def test_registry_add_then_update() -> None:
    session = _mem_session()
    StrategyRegistry(session).add(
        "RAW-1", "custom strat", "trend", "my_module.fn", best_fit_regimes=["Bull"]
    )
    assert StrategyRegistry(session).get("RAW-1") is not None
    assert StrategyRegistry(session).update_validation("RAW-1", gate_passed=False) is True
    updated = StrategyRegistry(session).get("RAW-1")
    assert updated is not None
    assert updated.gate_passed is False


# --------------------------------------------------------------------------- #
# Universe Provider
# --------------------------------------------------------------------------- #
def test_csi800_provider() -> None:
    prov = CSI800Provider(universe_engine=_FakeUE())
    codes = prov.codes()
    assert codes == ["000001", "000002", "600000", "600036"]  # sorted, dedup


def test_watchlist_provider_inline_codes() -> None:
    prov = WatchlistProvider(codes=["600000", "600000", "000001"])
    assert prov.codes() == ["000001", "600000"]


def test_watchlist_provider_file(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("# comment\n600000\n 000001 \n\n600036\n", encoding="utf-8")
    prov = WatchlistProvider(watchlist_path=p)
    assert prov.codes() == ["000001", "600000", "600036"]


def test_custom_provider() -> None:
    prov = CustomProvider(codes=["600519", "300750"])
    assert prov.codes() == ["300750", "600519"]
    # empty code list -> rejected on construction
    raised = False
    try:
        CustomProvider(codes=[])
    except ValueError:
        raised = True
    assert raised


def test_get_universe_provider_factory() -> None:
    # csi800 via injected config
    from core.config import AppConfig, UniverseConfig

    cfg = AppConfig().model_copy(deep=True)
    cfg.universe = UniverseConfig(type="csi800")
    prov = get_universe_provider(config=cfg)
    assert isinstance(prov, CSI800Provider)

    # watchlist inline override
    prov2 = get_universe_provider("watchlist", codes=["1", "2"])
    assert prov2.codes() == ["1", "2"]

    # custom via config
    cfg.universe = UniverseConfig(type="custom", custom_codes=["9", "8"])
    prov3 = get_universe_provider(config=cfg)
    assert prov3.codes() == ["8", "9"]
