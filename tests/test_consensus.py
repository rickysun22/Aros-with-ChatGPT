"""Tests for the Phase 4.2 Consensus Engine (consensus.py) + daily screening.

Fully offline: a synthetic price provider makes chosen built-in strategies fire
on chosen codes, so the daily screening, scoring, dedup and persistence paths
are exercised without a database server or network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import AppConfig
from core.database import Base
from research.consensus import (
    ConsensusEngine,
    HiddenFlowSignal,
    MoneyFlowSignal,
    aros_score,
    consensus_score,
    independence_score,
    rating_from_score,
    regime_match_fraction,
)
from research.kb import StrategyRegistry
from research.models import DailyAlphaCandidate, ScreeningHit


def _mem_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(eng)()


def _rising_prices(codes, start, end):
    """Deterministic rising OHLCV so ma_bull + high_breakout fire on every code."""
    out: dict[str, pd.DataFrame] = {}
    idx = pd.date_range(start, end, freq="B")
    n = len(idx)
    close = pd.Series(np.linspace(10.0, 20.0, n), index=idx, dtype=float)
    # Constant volume with a modest last-day spike so high_breakout fires
    # (vol_ratio in [1.2, 2.0)) but volume_breakout (vol_mult=2.0) does not.
    vol = pd.Series(1000.0, index=idx, dtype=float)
    vol.iloc[-1] = 1500.0
    for code in codes:
        df = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": vol,
            }
        )
        out[code] = df
    return out


def _flat_prices(codes, start, end):
    """Flat OHLCV so no strategy fires (no candidate expected)."""
    out: dict[str, pd.DataFrame] = {}
    idx = pd.date_range(start, end, freq="B")
    close = pd.Series(15.0, index=idx, dtype=float)
    vol = pd.Series(1000.0, index=idx, dtype=float)
    for code in codes:
        df = pd.DataFrame(
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": vol,
            }
        )
        out[code] = df
    return out


def _engine_with(custom_codes, price_provider, money_flow_provider=None, hidden_flow_provider=None):
    cfg = AppConfig()
    cfg.universe.type = "custom"
    cfg.universe.custom_codes = list(custom_codes)
    return ConsensusEngine(
        config=cfg,
        price_provider=price_provider,
        money_flow_provider=money_flow_provider,
        hidden_flow_provider=hidden_flow_provider,
    )


# --------------------------------------------------------------------------- #
# Engine integration (offline)
# --------------------------------------------------------------------------- #
def test_daily_produces_candidates_and_persists() -> None:
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    codes = ["600000", "600036", "000001"]
    engine = _engine_with(codes, lambda c, s, e: _rising_prices(c, s, e))

    results = engine.daily(None, "2026-06-30", session=session, regime="Bull")

    # ma_bull + high_breakout both fire on the rising series -> 2 hits / code.
    assert len(results) == 3
    for r in results:
        assert r.hit_count == 2
        assert set(r.hit_strategies) == {"ma_bull", "high_breakout"}
        assert r.regime_label == "Bull"
        assert r.consensus_score > 0
        assert r.aros_score > 0
        assert r.rating in {"A+", "A", "B", "C"}

    # Traceability: 3 codes x 2 hits = 6 screening hits.
    assert session.query(ScreeningHit).count() == 6
    # Top-N candidates persisted (3 < top_n=10).
    assert session.query(DailyAlphaCandidate).count() == 3


def test_daily_no_hits_means_no_candidates() -> None:
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    codes = ["600000", "600036"]
    engine = _engine_with(codes, lambda c, s, e: _flat_prices(c, s, e))

    results = engine.daily(None, "2026-06-30", session=session, regime="Neutral")
    assert results == []
    assert session.query(ScreeningHit).count() == 0
    assert session.query(DailyAlphaCandidate).count() == 0


def test_daily_respects_top_n() -> None:
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    # Many candidate codes but a low top_n.
    codes = [f"600{str(i).zfill(3)}" for i in range(100, 105)]
    cfg_engine = _engine_with(codes, lambda c, s, e: _rising_prices(c, s, e))
    cfg_engine._cc.top_n = 2  # type: ignore[attr-defined]

    results = cfg_engine.daily(None, "2026-06-30", session=session, regime="Bull")
    assert len(results) == 5  # all candidates returned
    # but only Top-2 persisted as DailyAlphaCandidate.
    assert session.query(DailyAlphaCandidate).count() == 2


def test_daily_persists_ranking_by_aros() -> None:
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    codes = ["600000", "600036", "000001"]
    engine = _engine_with(codes, lambda c, s, e: _rising_prices(c, s, e))
    engine.daily(None, "2026-06-30", session=session, regime="Bull")
    rows = session.query(DailyAlphaCandidate).order_by(DailyAlphaCandidate.aros_score.desc()).all()
    scores = [r.aros_score for r in rows]
    assert scores == sorted(scores, reverse=True)


class _FakeMoneyFlow:
    def get_stock_flow(self, code: str) -> MoneyFlowSignal:
        return MoneyFlowSignal(sector_score=80.0, public_money_score=70.0)


class _FakeHiddenFlow:
    def infer(self, code: str) -> HiddenFlowSignal:
        return HiddenFlowSignal(score=30.0, explanation="测试:行为推断(非金额)")


def test_daily_wires_43_providers() -> None:
    """The 4.3 provider outputs must flow through to ConsensusResult."""
    session = _mem_session()
    StrategyRegistry(session).seed_builtins()
    codes = ["600000", "600036", "000001"]
    engine = _engine_with(
        codes,
        lambda c, s, e: _rising_prices(c, s, e),
        money_flow_provider=_FakeMoneyFlow(),
        hidden_flow_provider=_FakeHiddenFlow(),
    )
    results = engine.daily(None, "2026-06-30", session=session, regime="Bull")
    assert results
    for r in results:
        assert r.sector_score == 80.0
        assert r.public_money_score == 70.0
        assert r.hidden_flow_score == 30.0
        assert r.system_suggestion == "测试:行为推断(非金额)"


# --------------------------------------------------------------------------- #
# Pure scoring math
# --------------------------------------------------------------------------- #
def _cfg() -> AppConfig:
    return AppConfig()


def test_consensus_components_sum_to_score() -> None:
    cfg = _cfg().consensus
    hits = [
        {
            "strategy_id": "a",
            "category": "trend",
            "quality_star": 4.0,
            "best_fit_regimes": ["Bull", "Neutral"],
        },
        {
            "strategy_id": "b",
            "category": "emotion",
            "quality_star": 2.0,
            "best_fit_regimes": ["EmotionHot"],
        },
    ]
    score, brk, _ = consensus_score(hits, {}, "Bull", 60.0, 70.0, cfg)
    comp = brk["hit"] + brk["quality"] + brk["independence"] + brk["regime"] + brk["sector_money"]
    assert abs(comp - score) < 0.01
    # No fold returns -> full independence credit (avg_corr 0).
    assert brk["independence"] == cfg.w_independence
    assert brk["avg_corr"] == 0.0


def test_dedup_drops_correlated_strategy() -> None:
    cfg = _cfg().consensus
    # Two trend strategies with near-identical OOS fold returns -> one cluster.
    hits = [
        {
            "strategy_id": "a",
            "category": "trend",
            "quality_star": 4.0,
            "best_fit_regimes": ["Bull"],
        },
        {
            "strategy_id": "b",
            "category": "trend",
            "quality_star": 3.0,
            "best_fit_regimes": ["Bull"],
        },
    ]
    folds = {"a": [0.10, 0.12, 0.08], "b": [0.11, 0.13, 0.09]}
    _, brk, survivors = consensus_score(hits, folds, "Bull", 50.0, 50.0, cfg)
    # Higher-star 'a' survives; 'b' deduped (correlated, same category).
    assert survivors == {"a"}
    assert brk["survivors"] == 1


def test_independence_penalises_correlation() -> None:
    cfg = _cfg().consensus
    # Perfectly (positively) correlated pair -> I -> 0 (no independence).
    i_hi, _ = independence_score(["a", "b"], {"a": [0.1, 0.2, 0.3], "b": [0.1, 0.2, 0.3]}, cfg)
    # Near-uncorrelated pair -> significantly more independence credit.
    i_lo, _ = independence_score(
        ["a", "b"], {"a": [0.1, 0.2, 0.3, 0.4], "b": [0.1, 0.4, 0.2, 0.3]}, cfg
    )
    assert i_hi < 1e-6
    assert i_lo > i_hi + 5.0


def test_regime_match_fraction() -> None:
    regs = [["Bull", "Neutral"], ["Bull"], ["EmotionHot"]]
    assert abs(regime_match_fraction("Bull", regs) - (2 / 3)) < 1e-9
    assert regime_match_fraction("Bear", regs) == 0.0  # no Bear -> caller uses base


def test_aros_weights_and_rating() -> None:
    cfg = _cfg().consensus
    score, brk = aros_score(80.0, "Bull", 60.0, 70.0, 50.0, 100.0, cfg)
    # Weighted blend of 0-100 components -> in [0,100].
    assert 0.0 <= score <= 100.0
    for key in ("consensus", "market_sector_env", "money_flow", "risk_filter"):
        assert key in brk
    # rating buckets
    assert rating_from_score(90.0, cfg) == "A+"
    assert rating_from_score(72.0, cfg) == "A"
    assert rating_from_score(60.0, cfg) == "B"
    assert rating_from_score(40.0, cfg) == "C"
