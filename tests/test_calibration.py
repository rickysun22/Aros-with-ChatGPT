"""Tests for the Sprint 4.6 Rating Validation & Calibration (research.calibration).

All network access is injected as a fake price provider (mirrors research.feedback
and test_feedback.py), so the entire 4.6 statistics / calibration path runs offline.
"""

from __future__ import annotations

import math
import os
from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.calibration import (
    baseline_excess,
    build_validation_payload,
    fill_all_performances,
    generate_validation_reports,
    human_vs_ai,
    migrate_rating_labels,
    propose_calibration,
    rating_distribution,
    significance_test,
    strategy_contribution,
)
from research.feedback import post_hoc
from research.models import (
    CandidatePerformance,
    DailyAlphaCandidate,
    DailyScreening,
    DecisionTracking,
    StrategyRegistry,
)


def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _fake_prices(code, start, end):
    """Deterministic rising closes on business days between start and end."""
    idx = pd.bdate_range(start, end)
    closes = [100.0 + i for i in range(len(idx))]
    return pd.DataFrame({"date": list(idx.date), "close": closes})


def _ensure_screening(session, sid="scr_test", run_date=date(2026, 7, 1)):
    scr = session.get(DailyScreening, sid)
    if scr is None:
        scr = DailyScreening(id=sid, run_date=run_date, universe="csi800", regime_label="Neutral")
        session.add(scr)
        session.commit()
    return scr


def _make_cand_with_perf(
    session,
    cand_id,
    code,
    rating,
    aros,
    result_10d,
    run_date=date(2026, 7, 1),
    human=None,
    hit='["s1"]',
):
    """Create a candidate + its CandidatePerformance row + optional human decision."""
    _ensure_screening(session, "scr_test", run_date)
    cand = DailyAlphaCandidate(
        id=cand_id,
        screening_id="scr_test",
        code=code,
        regime_label="Neutral",
        hit_count=1,
        hit_strategies_json=hit,
        consensus_score=aros,
        aros_score=aros,
        rating=rating,
    )
    session.add(cand)
    perf = CandidatePerformance(
        id=f"cp_{cand_id}",
        candidate_id=cand_id,
        code=code,
        signal_date=run_date,
        aros_score=aros,
        rating=rating,
        result_10d=result_10d,
        status="success" if result_10d > 0 else "fail",
    )
    session.add(perf)
    if human is not None:
        dt = DecisionTracking(
            id=f"dt_{cand_id}",
            candidate_id=cand_id,
            code=code,
            signal_date=run_date,
            human_decision=human,
        )
        session.add(dt)
    session.commit()
    return cand, perf


# --------------------------------------------------------------------------- #
# feedback.post_hoc extension (T+20 + target_hit_date) -- regression guard
# --------------------------------------------------------------------------- #
def test_post_hoc_t20_and_target_hit() -> None:
    res = post_hoc(
        "600000",
        date(2026, 7, 1),
        _fake_prices,
        horizon_days=(1, 3, 5, 10, 20),
        window=45,
        target_pct=0.05,
    )
    assert res is not None
    assert res["result_20d"] is not None
    assert res["result_20d"] > res["result_10d"]  # type: ignore[operator]
    # +5% target reached on a steadily rising series, after the entry day.
    assert res["target_hit_date"] is not None
    assert res["target_hit_date"] > date(2026, 7, 1)  # type: ignore[operator]


# --------------------------------------------------------------------------- #
# Rating-label migration (historical "A+" -> "S")
# --------------------------------------------------------------------------- #
def test_migrate_rating_labels_idempotent() -> None:
    session = _mem_session()
    _ensure_screening(session, "scr_m", date(2026, 7, 1))
    cand = DailyAlphaCandidate(
        id="cA",
        screening_id="scr_m",
        code="600000",
        regime_label="Neutral",
        hit_count=1,
        hit_strategies_json='["s1"]',
        consensus_score=90.0,
        aros_score=90.0,
        rating="A+",
    )
    session.add(cand)
    perf = CandidatePerformance(
        id="cp_cA",
        candidate_id="cA",
        code="600000",
        signal_date=date(2026, 7, 1),
        aros_score=90.0,
        rating="A+",
    )
    session.add(perf)
    session.commit()

    n1, n2 = migrate_rating_labels(session)
    assert n1 == 1 and n2 == 1
    assert session.get(DailyAlphaCandidate, "cA").rating == "S"
    assert session.get(CandidatePerformance, "cp_cA").rating == "S"
    # Idempotent re-run touches nothing.
    n3, n4 = migrate_rating_labels(session)
    assert n3 == 0 and n4 == 0


# --------------------------------------------------------------------------- #
# fill_all_performances (auto post-hoc for every candidate)
# --------------------------------------------------------------------------- #
def test_fill_all_performances_creates_rows() -> None:
    session = _mem_session()
    _ensure_screening(session, "scr1", date(2026, 7, 1))
    cand = DailyAlphaCandidate(
        id="c1",
        screening_id="scr1",
        code="600000",
        regime_label="Neutral",
        hit_count=1,
        hit_strategies_json='["s1"]',
        consensus_score=85.0,
        aros_score=85.0,
        rating="S",
    )
    session.add(cand)
    session.commit()

    n = fill_all_performances(session, _fake_prices, date(2026, 7, 1))
    assert n == 1
    perf = session.get(CandidatePerformance, "cp_c1")
    assert perf is not None
    assert perf.result_20d is not None
    assert perf.result_10d is not None and perf.result_10d > 0
    assert perf.target_hit_date is not None
    assert perf.target_hit_date > date(2026, 7, 1)
    assert perf.status == "success"


def test_fill_all_performances_incremental() -> None:
    session = _mem_session()
    _ensure_screening(session, "scr1", date(2026, 7, 1))
    # Already-matured row (result_20d present) must be skipped.
    cand_old = DailyAlphaCandidate(
        id="cold",
        screening_id="scr1",
        code="600001",
        regime_label="Neutral",
        hit_count=1,
        hit_strategies_json='["s1"]',
        consensus_score=80.0,
        aros_score=80.0,
        rating="A",
    )
    session.add(cand_old)
    session.add(
        CandidatePerformance(
            id="cp_cold",
            candidate_id="cold",
            code="600001",
            signal_date=date(2026, 7, 1),
            aros_score=80.0,
            rating="A",
            result_20d=0.05,
            status="success",
        )
    )
    # Fresh candidate without a performance row.
    cand_new = DailyAlphaCandidate(
        id="cnew",
        screening_id="scr1",
        code="600002",
        regime_label="Neutral",
        hit_count=1,
        hit_strategies_json='["s1"]',
        consensus_score=70.0,
        aros_score=70.0,
        rating="B",
    )
    session.add(cand_new)
    session.commit()

    n1 = fill_all_performances(session, _fake_prices, date(2026, 7, 1))
    assert n1 == 1
    n2 = fill_all_performances(session, _fake_prices, date(2026, 7, 1))
    assert n2 == 0  # nothing left to (re)write


# --------------------------------------------------------------------------- #
# rating_distribution + significance_test (the core S>A>B>C question)
# --------------------------------------------------------------------------- #
def test_distribution_monotone_and_significant() -> None:
    session = _mem_session()
    data = {
        "S": [0.30, 0.32, 0.31],
        "A": [0.10, 0.11, 0.12],
        "B": [0.02, 0.03, 0.04],
        "C": [-0.20, -0.18, -0.19],
    }
    i = 0
    for rating, rets in data.items():
        for r in rets:
            _make_cand_with_perf(session, f"d{i}", f"60{i:03d}", rating, 80.0, r)
            i += 1

    dist = rating_distribution(session)
    assert dist["S"]["avg_return"] > dist["A"]["avg_return"]
    assert dist["A"]["avg_return"] > dist["B"]["avg_return"]
    assert dist["B"]["avg_return"] > dist["C"]["avg_return"]

    sig = significance_test(session)
    assert sig["S-A"]["significant"] is True
    assert sig["B-C"]["significant"] is True
    # Strongly separated: CI lower bound clearly above 0 and p well below 0.05.
    assert sig["S-A"]["ci_low"] is not None and sig["S-A"]["ci_low"] > 0
    assert sig["S-A"]["mwu_p"] is not None and sig["S-A"]["mwu_p"] < 0.05


def test_significance_insufficient_sample_is_none() -> None:
    session = _mem_session()
    # Only S and A have >=3 samples; B and C are empty -> those pairs are n/a.
    for rating, rets in {"S": [0.30, 0.32, 0.31], "A": [0.10, 0.11, 0.12]}.items():
        for r in rets:
            _make_cand_with_perf(session, f"d_{rating}_{r}", "600000", rating, 80.0, r)
    sig = significance_test(session)
    assert sig["S-A"]["mean_diff"] is not None
    assert sig["A-B"]["mean_diff"] is None
    assert sig["B-C"]["mean_diff"] is None


def test_distribution_empty_session() -> None:
    session = _mem_session()
    dist = rating_distribution(session)
    assert set(dist.keys()) == {"S", "A", "B", "C"}
    assert all(dist[r]["count"] == 0 for r in dist)


# --------------------------------------------------------------------------- #
# baseline_excess (edge vs a benchmark index)
# --------------------------------------------------------------------------- #
def test_baseline_excess_computes() -> None:
    session = _mem_session()
    _make_cand_with_perf(session, "c1", "600001", "S", 90.0, 0.10, date(2026, 7, 1))
    row = baseline_excess(session, _fake_prices, "000300", as_of=date(2026, 8, 1))
    assert row is not None
    assert isinstance(row["overall"], float)
    assert math.isfinite(row["overall"])


def test_baseline_excess_no_data_returns_none() -> None:
    session = _mem_session()
    assert baseline_excess(session, _fake_prices, "000300") is None


# --------------------------------------------------------------------------- #
# strategy_contribution (parse hit_strategies_json -> names)
# --------------------------------------------------------------------------- #
def test_strategy_contribution_tallies() -> None:
    session = _mem_session()
    reg = StrategyRegistry(strategy_id="s1", name="均线多头", category="trend", executable_ref="x")
    session.add(reg)
    session.commit()
    _make_cand_with_perf(
        session, "c1", "600001", "S", 90.0, 0.10, date(2026, 7, 1), hit='["s1","s2"]'
    )
    _make_cand_with_perf(session, "c2", "600002", "A", 80.0, 0.05, date(2026, 7, 1), hit='["s1"]')
    rows = strategy_contribution(session)
    ids = {r["strategy_id"] for r in rows}
    assert ids == {"s1", "s2"}
    s1 = next(r for r in rows if r["strategy_id"] == "s1")
    assert s1["name"] == "均线多头"
    assert s1["hits"] == 2 and s1["successes"] == 2
    s2 = next(r for r in rows if r["strategy_id"] == "s2")
    assert s2["name"] == "s2"  # unresolved id falls back to the id
    assert s2["hits"] == 1


# --------------------------------------------------------------------------- #
# human_vs_ai (AI Top20 vs Human Top5 engaged)
# --------------------------------------------------------------------------- #
def test_human_vs_ai() -> None:
    session = _mem_session()
    # 5 engaged (买入) with the highest AROS scores.
    for i in range(5):
        _make_cand_with_perf(
            session,
            f"e{i}",
            f"61000{i}",
            "S",
            95.0 - i,
            0.10,
            date(2026, 7, 1),
            human="买入",
        )
    # 20 non-engaged candidates with lower AROS scores.
    for i in range(20):
        _make_cand_with_perf(
            session, f"a{i}", f"62000{i}", "A", 70.0 - i * 0.5, 0.04, date(2026, 7, 1)
        )
    row = human_vs_ai(session)
    assert row["ai_n"] == 20
    assert row["human_n"] == 5
    assert math.isfinite(row["delta"])
    # Engaged names beat the broader AI set in this synthetic setup.
    assert row["human_avg"] > row["ai_avg"]


# --------------------------------------------------------------------------- #
# propose_calibration (two-stage, observe-first)
# --------------------------------------------------------------------------- #
def test_propose_calibration_two_stage() -> None:
    session = _mem_session()
    _make_cand_with_perf(session, "c1", "600001", "S", 90.0, 0.10, date(2026, 1, 1))
    # Far enough in trading days -> can calibrate.
    cal = propose_calibration(session, as_of=date(2026, 7, 1))
    assert cal["trading_days"] >= 60
    assert cal["can_calibrate"] is True
    assert cal["proposed"] is not None
    # Too few trading days -> observe-only (proposal still emitted, flag False).
    cal2 = propose_calibration(session, as_of=date(2026, 1, 5))
    assert cal2["can_calibrate"] is False
    assert "样本不足" in cal2["note"]


# --------------------------------------------------------------------------- #
# Report rendering (md + html + xlsx, with / without benchmark)
# --------------------------------------------------------------------------- #
def test_build_payload_and_reports(tmp_path) -> None:
    session = _mem_session()
    for cid, code, rating, aros, r10 in (
        ("c1", "600001", "S", 90.0, 0.10),
        ("c2", "600002", "A", 80.0, 0.05),
        ("c3", "600003", "B", 70.0, 0.02),
        ("c4", "600004", "C", 60.0, -0.03),
    ):
        _make_cand_with_perf(session, cid, code, rating, aros, r10, date(2026, 7, 1))

    payload = build_validation_payload(session, as_of=date(2026, 7, 1))
    assert payload["as_of"] == "2026-07-01"
    assert payload["n_candidates"] == 4
    assert payload["n_performances"] == 4
    assert payload["monotone"] is True
    assert payload["baseline"] is None  # no benchmark injected

    paths = generate_validation_reports(session, out_dir=str(tmp_path), as_of=date(2026, 7, 1))
    for p in paths.values():
        assert os.path.exists(p)
    md = open(paths["md"], encoding="utf-8").read()
    assert "S>A>B>C" in md


def test_reports_with_benchmark(tmp_path) -> None:
    session = _mem_session()
    _make_cand_with_perf(session, "c1", "600001", "S", 90.0, 0.10, date(2026, 7, 1))
    payload = build_validation_payload(
        session,
        as_of=date(2026, 7, 1),
        bench_price_provider=_fake_prices,
        bench_code="000300",
    )
    assert payload["baseline"] is not None
    paths = generate_validation_reports(
        session,
        out_dir=str(tmp_path),
        as_of=date(2026, 7, 1),
        bench_price_provider=_fake_prices,
        bench_code="000300",
    )
    assert os.path.exists(paths["xlsx"])
