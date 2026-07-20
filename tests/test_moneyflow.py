"""Tests for the Phase 4.3 Market Context & Money Flow providers.

Fully offline: the real akshare-backed providers are exercised through *injected*
fake functions (mirroring how the rest of the suite injects a fake DataProvider),
so no network call is ever made. The pure scoring math is tested directly with
synthetic DataFrames.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from data.providers.moneyflow import (
    AkShareHiddenFlowProvider,
    AkShareMoneyFlowProvider,
    _market_of,
    _recent_net_pct,
    hidden_flow_infer,
    public_money_score,
    sector_score,
)
from research.consensus import HiddenFlowSignal, MoneyFlowSignal


# --------------------------------------------------------------------------- #
# Pure scoring math
# --------------------------------------------------------------------------- #
def test_public_money_score_bounds_and_midpoint() -> None:
    assert public_money_score(None) == 50.0
    assert public_money_score(float("nan")) == 50.0
    assert public_money_score(0.0) == 50.0
    assert public_money_score(3.0) > 50.0  # net inflow -> above neutral
    assert public_money_score(-3.0) < 50.0  # net outflow -> below neutral


def test_sector_score_relative_and_fallback() -> None:
    # Stock stronger than sector -> above 50.
    assert sector_score(3.0, 1.0) > 50.0
    # Stock weaker than sector -> below 50.
    assert sector_score(1.0, 3.0) < 50.0
    # Missing sector -> falls back to the stock's own absolute score.
    assert sector_score(3.0, None) > 50.0
    # Missing both -> neutral.
    assert sector_score(None, None) == 50.0


def _accum_prices() -> pd.DataFrame:
    """Flat, low-vol, with a late volume pickup (behavioural accumulation)."""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    close = 15.0 + 0.05 * np.sin(np.linspace(0, 2 * math.pi, 30))
    vol = np.full(30, 1000.0)
    vol[-5:] = 1500.0
    return pd.DataFrame({"close": close, "volume": vol}, index=idx)


def _dist_prices() -> pd.DataFrame:
    """Strong late rally on rising volume with net outflow (distribution)."""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    close = np.full(30, 15.0)
    close[20:] = np.linspace(15.0, 16.5, 10)
    vol = np.full(30, 1000.0)
    vol[20:] = 1400.0
    return pd.DataFrame({"close": close, "volume": vol}, index=idx)


def test_hidden_flow_infer_accumulation() -> None:
    score, expl = hidden_flow_infer(_accum_prices(), 2.5)
    assert score > 50.0
    assert ("吸筹" in expl) or ("承接" in expl)
    assert "非金额" in expl  # red line: no fabricated amount


def test_hidden_flow_infer_distribution() -> None:
    score, expl = hidden_flow_infer(_dist_prices(), -2.0)
    assert score < 50.0
    assert "派发" in expl
    assert "非金额" in expl


def test_hidden_flow_infer_no_data_is_neutral() -> None:
    for bad in (None, pd.DataFrame(), pd.DataFrame({"close": [1, 2]})):
        score, expl = hidden_flow_infer(bad, 1.0)
        assert score == 50.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_recent_net_pct_parses_column() -> None:
    raw = pd.DataFrame({"主力净流入-净占比": [2.0, 3.0, 4.0, 1.0, 5.0]})
    v = _recent_net_pct(raw)
    assert v is not None
    assert math.isclose(v, 3.0)
    # Drifted (English) header is still resolved.
    raw_en = pd.DataFrame({"main_net_pct_inflow": [1.0, -1.0]})
    v_en = _recent_net_pct(raw_en)
    assert v_en is not None
    assert math.isclose(v_en, 0.0)
    assert _recent_net_pct(pd.DataFrame()) is None
    assert _recent_net_pct(None) is None


def test_market_of_mapping() -> None:
    assert _market_of("600000") == "sh"
    assert _market_of("000001") == "sz"
    assert _market_of("300750") == "sz"
    assert _market_of("830799") == "bj"
    assert _market_of("420063") == "bj"


# --------------------------------------------------------------------------- #
# Providers with injected fakes (no network)
# --------------------------------------------------------------------------- #
def _fake_flow(code: str) -> pd.DataFrame:
    return pd.DataFrame({"主力净流入-净占比": [2.0, 3.0, 4.0, 1.0, 5.0]})


def _fake_industry(code: str) -> str | None:
    return "半导体"


def _fake_sector(industry: str) -> float | None:
    return 1.0


def test_moneyflow_provider_uses_injected_fns() -> None:
    prov = AkShareMoneyFlowProvider(
        flow_fn=_fake_flow, industry_fn=_fake_industry, sector_flow_fn=_fake_sector
    )
    sig = prov.get_stock_flow("600000")
    assert isinstance(sig, MoneyFlowSignal)
    # net_pct mean = 3.0 -> public = 50 + 50*tanh(1.0)
    assert math.isclose(sig.public_money_score, 50.0 + 50.0 * math.tanh(1.0), abs_tol=0.5)
    # sector = 50 + 50*tanh((3.0 - 1.0)/3.0)
    assert math.isclose(sig.sector_score, 50.0 + 50.0 * math.tanh(2.0 / 3.0), abs_tol=0.5)


def test_moneyflow_provider_degrades_on_exception() -> None:
    def boom(code: str) -> pd.DataFrame:
        raise RuntimeError("network down")

    prov = AkShareMoneyFlowProvider(flow_fn=boom)
    sig = prov.get_stock_flow("600000")
    assert sig.sector_score == 50.0
    assert sig.public_money_score == 50.0


def test_hidden_provider_uses_injected_fns() -> None:
    prov = AkShareHiddenFlowProvider(
        price_fn=lambda c: _accum_prices(),
        flow_fn=lambda c: pd.DataFrame({"主力净流入-净占比": [2.5]}),
    )
    sig = prov.infer("600000")
    assert isinstance(sig, HiddenFlowSignal)
    assert sig.score > 50.0
    assert "非金额" in sig.explanation


def test_hidden_provider_degrades_on_exception() -> None:
    def boom(code: str) -> pd.DataFrame:
        raise RuntimeError("network down")

    prov = AkShareHiddenFlowProvider(price_fn=boom)
    sig = prov.infer("600000")
    assert sig.score == 50.0
    assert "不淘汰候选" in sig.explanation  # constitution preserved


def test_provider_contract_satisfied() -> None:
    m = AkShareMoneyFlowProvider(
        flow_fn=_fake_flow, industry_fn=_fake_industry, sector_flow_fn=_fake_sector
    )
    h = AkShareHiddenFlowProvider(price_fn=lambda c: _accum_prices(), flow_fn=_fake_flow)
    assert isinstance(m.get_stock_flow("600000"), MoneyFlowSignal)
    assert isinstance(h.infer("600000"), HiddenFlowSignal)
