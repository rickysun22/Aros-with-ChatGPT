"""Tests for the Sprint 4.5 Human Feedback Loop (research.feedback)."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.feedback import (
    HUMAN_DECISIONS,
    fill_posthoc,
    list_decisions,
    list_trades,
    post_hoc,
    query_decisions,
    record_decision,
    record_trade,
    review,
)
from research.models import DailyAlphaCandidate, DailyScreening, DecisionTracking


def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _make_candidate(session, cand_id="dac_test", code="600000", sdate=date(2026, 7, 1)):
    scr = DailyScreening(id="scr_test", run_date=sdate, universe="csi800", regime_label="Neutral")
    session.add(scr)
    cand = DailyAlphaCandidate(
        id=cand_id,
        screening_id="scr_test",
        code=code,
        regime_label="Neutral",
        hit_count=2,
        hit_strategies_json='["ma_bull", "high_breakout"]',
        consensus_score=70.0,
        aros_score=80.0,
        rating="A",
    )
    session.add(cand)
    session.commit()
    return cand


def _fake_prices(code, start, end):
    """Deterministic rising closes on business days between start and end."""
    idx = pd.bdate_range(start, end)
    closes = [100.0 + i for i in range(len(idx))]
    return pd.DataFrame({"date": list(idx.date), "close": closes})


def _none_prices(code, start, end):
    return None


# --------------------------------------------------------------------------- #
# Pure post-hoc math
# --------------------------------------------------------------------------- #
def test_post_hoc_returns_on_rising_prices() -> None:
    res = post_hoc("600000", date(2026, 7, 1), _fake_prices)
    assert res is not None
    assert res["result_1d"] is not None
    assert res["result_3d"] is not None
    assert res["result_5d"] is not None
    assert res["result_10d"] is not None
    # Monotonic up: 10d cumulative > 1d; float loss floored at 0 (entry day).
    assert res["result_10d"] > res["result_1d"]  # type: ignore[operator]
    assert res["max_float_profit"] == res["result_10d"]  # type: ignore[comparison-overlap]
    assert res["max_float_loss"] == 0.0
    assert res["final_return"] == res["result_10d"]


def test_post_hoc_degrades_to_none_without_data() -> None:
    assert post_hoc("600000", date(2026, 7, 1), _none_prices) is None


def test_post_hoc_no_entry_day_returns_none() -> None:
    # Prices only before the signal date -> no T+1 entry -> no result.
    def _before_only(code, start, end):
        idx = pd.bdate_range(date(2026, 6, 1), date(2026, 6, 30))
        return pd.DataFrame({"date": list(idx.date), "close": [100.0] * len(idx)})

    assert post_hoc("600000", date(2026, 7, 1), _before_only) is None


# --------------------------------------------------------------------------- #
# Decision recording + review
# --------------------------------------------------------------------------- #
def test_record_decision_persists_and_links() -> None:
    session = _mem_session()
    _make_candidate(session)
    dt = record_decision(session, "dac_test", "买入", "looks good")
    assert dt.code == "600000"
    assert dt.signal_date == date(2026, 7, 1)
    assert dt.human_decision == "买入"
    assert dt.human_reason == "looks good"
    # Reloadable + listed.
    assert len(list_decisions(session)) == 1
    reloaded = session.get(DecisionTracking, dt.id)
    assert reloaded is not None and reloaded.candidate_id == "dac_test"


def test_record_decision_rejects_unknown_candidate() -> None:
    session = _mem_session()
    try:
        record_decision(session, "nope", "买入")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown candidate_id")


def test_record_decision_rejects_invalid_label() -> None:
    session = _mem_session()
    _make_candidate(session)
    try:
        record_decision(session, "dac_test", "HODL")
    except ValueError:
        return
    raise AssertionError("expected ValueError for invalid decision")


def test_review_fills_posthoc_and_human_fields() -> None:
    session = _mem_session()
    _make_candidate(session)
    dt = record_decision(session, "dac_test", "关注")
    updated = review(session, dt.id, _fake_prices, verified_system=True, review_summary="validated")
    assert updated.result_1d is not None
    assert updated.result_10d is not None
    assert updated.verified_system is True
    assert updated.review_summary == "validated"
    assert updated.review_date is not None
    # Persisted.
    reloaded = session.get(DecisionTracking, dt.id)
    assert reloaded is not None and reloaded.verified_system is True


def test_fill_posthoc_no_commit_does_not_persist() -> None:
    session = _mem_session()
    _make_candidate(session)
    dt = record_decision(session, "dac_test", "放弃")
    fill_posthoc(dt, _fake_prices)
    assert dt.result_1d is not None
    session.rollback()
    reloaded = session.get(DecisionTracking, dt.id)
    # Without commit, the post-hoc fields are not persisted.
    assert reloaded is not None and reloaded.result_1d is None


# --------------------------------------------------------------------------- #
# Personal trade blotter
# --------------------------------------------------------------------------- #
def test_record_and_list_trades() -> None:
    session = _mem_session()
    t = record_trade(
        session,
        "600000",
        name="浦发银行",
        entry_date=date(2026, 7, 2),
        entry_price=10.5,
        exit_date=date(2026, 7, 12),
        exit_price=11.2,
        direction="long",
        pnl=700.0,
        pnl_pct=0.0667,
    )
    assert t.code == "600000"
    assert len(list_trades(session)) == 1
    assert len(list_trades(session, code="600000")) == 1
    assert len(list_trades(session, code="000001")) == 0


# --------------------------------------------------------------------------- #
# Report enrichment map
# --------------------------------------------------------------------------- #
def test_query_decisions_maps_by_candidate() -> None:
    session = _mem_session()
    _make_candidate(session)
    record_decision(session, "dac_test", "买入", "conviction")
    mapping = query_decisions(session, date(2026, 7, 1))
    assert "dac_test" in mapping
    assert mapping["dac_test"].human_decision == "买入"
    # A different day yields no rows.
    assert query_decisions(session, date(2026, 6, 1)) == {}


def test_human_decisions_constant() -> None:
    assert HUMAN_DECISIONS == ("关注", "买入", "放弃", "忽略")
