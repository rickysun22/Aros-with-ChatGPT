"""Tests for the Phase 4.7 Entry Intelligence engine (research.entry).

Offline: a fake ``PriceProvider`` returns deterministic business-day OHLCV; the
Entry Score / action is checked against hand-reasoned scenarios (breakout,
near-limit-up guard, bear-regime guard, downtrend guard, no-data).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from research.entry import EntryEngine, EntrySignal, MarketState, resolve_categories
from research.models import StrategyRegistry


def _mk(start: date, closes: list[float], volumes=None, highs=None, lows=None):
    """Build a fake PriceProvider over consecutive business days from ``start``."""
    days = list(pd.bdate_range(start, start + timedelta(days=len(closes) * 2)))[: len(closes)]

    def _p(code: str, s: date, e: date):
        df = pd.DataFrame({"date": days, "close": closes})
        if volumes is not None:
            df["volume"] = volumes
        if highs is not None:
            df["high"] = highs
        if lows is not None:
            df["low"] = lows
        df = df[(df["date"] >= s) & (df["date"] <= e)]
        return df if not df.empty else None

    return _p, days


# A 130-day consolidation that breaks out +5% on the final day (good timing).
GOOD_BREAKOUT = [100.0] * 129 + [105.0]
# Flat then a +10% limit-up-style jump on the last day (chase guard).
LIMIT_UP = [100.0] * 129 + [110.0]
# A long decline ending below both moving averages (downtrend).
DOWNTREND = [float(229 - i) for i in range(130)]


def _eval(code: str, closes: list[float], *, market: MarketState | None = None) -> EntrySignal:
    provider, days = _mk(date(2026, 1, 5), closes)
    return EntryEngine().evaluate(
        code,
        days[-1],
        provider,
        aros_score=90.0,
        rating="S",
        categories=["strong"],
        market=market or MarketState(regime="Neutral"),
    )


def test_breakout_gives_buyable_score() -> None:
    sig = _eval("000001", GOOD_BREAKOUT)
    assert sig.entry_score >= 65.0
    assert sig.action in ("buy", "strong_buy")
    assert sig.dominant_family == "strong"


def test_near_limit_up_is_capped() -> None:
    sig = _eval("000001", LIMIT_UP)
    assert sig.entry_score <= 40.0
    assert sig.action == "avoid"
    assert "涨停" in sig.reason


def test_bear_regime_is_defensive() -> None:
    sig = _eval("000001", GOOD_BREAKOUT, market=MarketState(regime="Bear"))
    assert sig.entry_score <= 55.0
    assert sig.action in ("wait", "avoid")


def test_downtrend_is_avoided() -> None:
    sig = _eval("000001", DOWNTREND)
    assert sig.entry_score <= 40.0
    assert sig.action == "avoid"


def test_no_data_returns_avoid() -> None:
    def _p(code: str, s: date, e: date):
        return None

    sig = EntryEngine().evaluate(
        "000001",
        date(2026, 2, 1),
        _p,
        aros_score=90.0,
        rating="S",
        categories=["trend"],
    )
    assert sig.action == "avoid"
    assert sig.entry_score == 0.0


def test_resolve_categories_maps_strategy_ids() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.database import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    session.add(
        StrategyRegistry(
            strategy_id="s_trend",
            name="Trend A",
            category="trend",
            executable_ref="trend_a",
            status="active",
        )
    )
    session.add(
        StrategyRegistry(
            strategy_id="s_emotion",
            name="Emotion B",
            category="emotion",
            executable_ref="emotion_b",
            status="active",
        )
    )
    session.commit()
    cats = resolve_categories(session, ["s_trend", "s_emotion", "unknown"])
    assert set(cats) == {"trend", "emotion"}


def test_dominant_family_selection() -> None:
    provider, days = _mk(date(2026, 1, 5), GOOD_BREAKOUT)
    sig = EntryEngine().evaluate(
        "000001",
        days[-1],
        provider,
        aros_score=90.0,
        rating="S",
        categories=["trend"],
    )
    assert sig.dominant_family == "trend"
