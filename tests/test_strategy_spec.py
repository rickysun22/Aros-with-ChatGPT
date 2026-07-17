"""Sprint 3.0 — StrategySpec contract + UniverseResolver tests.

Anchors D1/D2/D3/D5/D7 of the Phase 3 design: category/engine/universe enums,
the custom-code guard, the ExperimentConfig mapping, and the D6 survivor-ship
guard inside UniverseResolver.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from core.config import BacktestConfig
from research.strategy_spec import (
    ResearchStrategySpec,
    StrategySpec,
    UniverseResolver,
    clear_registry,
    get_strategy,
    list_strategies,
    register_strategy,
)

_BASE_SPEC = ResearchStrategySpec(
    name="trend_ma",
    display_name="均线多头",
    category="trend",
    engine="portfolio",
    universe="csi800",
)


def _spec(**kw: object) -> ResearchStrategySpec:
    return _BASE_SPEC.model_copy(update=kw)  # type: ignore[arg-type]


def test_alias_resolves() -> None:
    assert StrategySpec is ResearchStrategySpec


def test_registry_roundtrip() -> None:
    clear_registry()
    spec = _spec()
    register_strategy(spec)
    assert get_strategy("trend_ma") is spec
    assert [s.name for s in list_strategies()] == ["trend_ma"]
    clear_registry()


def test_category_engine_universe_enum_enforced() -> None:
    with pytest.raises(ValidationError):
        _spec(category="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _spec(engine="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _spec(universe="bogus")  # type: ignore[arg-type]


def test_custom_universe_requires_codes() -> None:
    with pytest.raises(ValueError):
        _spec(universe="custom")
    spec = _spec(universe="custom", custom_codes=["000001", "600000"])
    assert spec.universe == "custom"
    assert set(spec.custom_codes or []) == {"000001", "600000"}


def test_experiment_universe_mapping() -> None:
    assert _spec(universe="csi800").experiment_universe() == "csi800"
    assert _spec(universe="all_a").experiment_universe() == "all_a"
    assert _spec(universe="custom", custom_codes=["000001"]).experiment_universe() is None


def test_resolver_custom_returns_sorted_codes() -> None:
    spec = _spec(universe="custom", custom_codes=["600000", "000001"])
    codes = UniverseResolver().resolve(spec)
    assert codes == ["000001", "600000"]


class _FakeDM:
    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame({"code": ["000001", "600000", "000002"]})


def test_resolver_all_a_requires_data_manager() -> None:
    spec = _spec(universe="all_a")
    with pytest.raises(ValueError):
        UniverseResolver().resolve(spec)
    codes = UniverseResolver().resolve(spec, data_manager=_FakeDM())
    assert codes == ["000001", "000002", "600000"]


class _EmptyEngine:
    def get_codes(self, pool: str) -> list[str]:
        return []


class _PopulatedEngine:
    def get_codes(self, pool: str) -> list[str]:
        return ["000001", "600000"]


def test_resolver_csi800_d6_guard_on_empty_pool() -> None:
    spec = _spec(universe="csi800")
    with pytest.raises(ValueError):
        # D6: never silently fall back to a wrong (survivor) set.
        UniverseResolver(universe_engine=_EmptyEngine()).resolve(spec)
    codes = UniverseResolver(universe_engine=_PopulatedEngine()).resolve(spec)
    assert codes == ["000001", "600000"]


def test_backtest_config_accepts_event_fields() -> None:
    # EventBacktest reads exit/risk params from the spec, not BacktestConfig,
    # so the config stays compatible with the existing portfolio engine.
    cfg = BacktestConfig()
    assert cfg.initial_cash == 1_000_000.0
