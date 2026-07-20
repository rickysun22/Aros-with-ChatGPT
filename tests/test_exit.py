"""Tests for the Phase 4.8 Exit Intelligence engine (research.exit).

Offline: a fake ``PriceProvider`` (prices) + fake ``ScoreProvider`` (real AROS
score) drive :class:`ExitEngine` through every graded branch (stop / trend
break / logic decay / money weakening), and the 4.7 validation environment is
checked to honour ``score_source == "real"`` (records ``score_type="real"``).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.exit import ExitEngine, ExitScoreInput, ScoreProvider
from research.feedback import PriceProvider
from research.models import DailyAlphaCandidate, DailyScreening, SimulatedTrade
from research.papertrade import exit_preset, init_portfolio, simulate_day


def _days(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    """``n`` consecutive business days as python ``date`` objects."""
    return [d.date() for d in pd.bdate_range(start, start + timedelta(days=n * 2))[:n]]


def _price_provider(closes: list[float], days: list[date]) -> PriceProvider:
    def _p(code: str, s: date, e: date):
        df = pd.DataFrame({"date": days, "close": closes})
        df = df[(df["date"] >= s) & (df["date"] <= e)]
        return df if not df.empty else None

    return _p


def _score_provider(value: float, entry: float = 90.0) -> ScoreProvider:
    def _sp(code: str, as_of: date) -> ExitScoreInput:
        return ExitScoreInput(aros_score=value, entry_aros_score=entry)

    return _sp


# --------------------------------------------------------------------------- #
# ExitEngine branches
# --------------------------------------------------------------------------- #
def test_stop_loss_is_high() -> None:
    days = _days(3)
    closes = [100.0, 100.0, 90.0]
    pp = _price_provider(closes, days)
    sig = ExitEngine().evaluate(
        "000001",
        days[-1],
        100.0,
        pp,
        _score_provider(90.0),
        entry_date=days[0],
        entry_aros_score=90.0,
    )
    assert sig.stop_hit
    assert sig.level == "High"
    assert sig.should_exit
    assert any("止损" in r for r in sig.reasons)


def test_logic_decay_is_medium() -> None:
    days = _days(40)
    closes = [100.0] * len(days)
    pp = _price_provider(closes, days)
    sig = ExitEngine().evaluate(
        "000001",
        days[-1],
        100.0,
        pp,
        _score_provider(65.0, entry=90.0),
        entry_date=days[0],
        entry_aros_score=90.0,
    )
    assert sig.logic_decay
    assert sig.level == "Medium"
    assert sig.should_exit
    assert any("逻辑衰减" in r for r in sig.reasons)


def test_money_weakening_is_medium() -> None:
    days = _days(40)
    closes = [100.0] * len(days)
    pp = _price_provider(closes, days)

    def _sp(code: str, as_of: date) -> ExitScoreInput:
        return ExitScoreInput(aros_score=90.0, entry_aros_score=90.0, public_money_score=40.0)

    sig = ExitEngine().evaluate(
        "000001",
        days[-1],
        100.0,
        pp,
        _sp,
        entry_date=days[0],
        entry_aros_score=90.0,
    )
    assert sig.money_weakening
    assert sig.level == "Medium"


def test_trend_break_in_profit_is_medium() -> None:
    days = _days(8)
    closes = [100.0, 110.0, 120.0, 118.0, 112.0] + [108.0] * (len(days) - 5)
    pp = _price_provider(closes, days)
    sig = ExitEngine().evaluate(
        "000001",
        days[-1],
        100.0,
        pp,
        _score_provider(90.0),
        entry_date=days[0],
        entry_aros_score=90.0,
    )
    assert sig.trend_broken
    assert sig.should_exit  # in profit -> Medium, not High


def test_no_signal_when_healthy() -> None:
    days = _days(40)
    closes = [100.0 + i for i in range(len(days))]  # gentle uptrend
    pp = _price_provider(closes, days)
    sig = ExitEngine().evaluate(
        "000001",
        days[-1],
        100.0,
        pp,
        _score_provider(92.0, entry=90.0),
        entry_date=days[0],
        entry_aros_score=90.0,
    )
    assert sig.level == "None"
    assert not sig.should_exit


# --------------------------------------------------------------------------- #
# Validation-environment wiring: score_source == "real"
# --------------------------------------------------------------------------- #
def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_score_decay_real_records_real_type() -> None:
    session = _mem_session()
    days = _days(40)
    closes = [100.0] * len(days)

    def _pp(code: str, s: date, e: date):
        df = pd.DataFrame({"date": days, "close": closes})
        df = df[(df["date"] >= s) & (df["date"] <= e)]
        return df if not df.empty else None

    scr = DailyScreening(id="scr1", run_date=days[0], universe="csi800", regime_label="Bull")
    session.add(scr)
    cand = DailyAlphaCandidate(
        id="cand1",
        screening_id=scr.id,
        code="000001",
        name="N1",
        regime_label="Bull",
        hit_count=0,
        hit_strategies_json="[]",
        consensus_score=90.0,
        aros_score=90.0,
        rating="S",
    )
    session.add(cand)
    session.commit()

    cfg = exit_preset("E3")
    cfg.score_decay.score_source = "real"
    init_portfolio(
        session,
        portfolio_id="S1_E3R",
        axis="exit",
        picker="ai",
        exit_config=cfg,
    )
    # Score provider: real AROS score below threshold for the whole window.
    score_provider = _score_provider(60.0, entry=90.0)
    for d in days:
        simulate_day(session, d, _pp, score_provider=score_provider)
    t = session.query(SimulatedTrade).first()
    assert t is not None
    assert t.exit_reason == "score_decay"
    assert t.score_type == "real"
