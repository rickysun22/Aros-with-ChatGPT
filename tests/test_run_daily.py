"""Tests for the daily operational orchestrator (research.run_daily).

Offline: an in-memory sqlite session, a fake ``screen_fn`` that persists a
DailyScreening + candidates, and a fake PriceProvider. Verifies the loop wires
4.2/4.4/4.6/4.5 together, stays idempotent per date, and that ``catch_up``
self-heals missing trading days.
"""

from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.feedback import record_decision
from research.models import (
    CandidatePerformance,
    DailyAlphaCandidate,
    DailyScreening,
    DecisionTracking,
)
from research.run_daily import RunDeps, _has_screening, catch_up, run_daily

# A long run of business days so forward returns (T+1..T+20) are always available.
DAYS = [d.date() for d in pd.bdate_range(date(2026, 1, 5), date(2026, 3, 15))]

CLOSES = {
    code: [100.0 + 0.5 * i for i in range(len(DAYS))] for code in ("000001", "000002", "000003")
}
SCHEDULE = {code: list(zip(DAYS, closes, strict=False)) for code, closes in CLOSES.items()}


def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _make_price(schedule: dict[str, list[tuple[date, float]]]):
    def _p(code, start, end):  # noqa: ANN001
        rows = schedule.get(code)
        if rows is None:
            return None
        df = pd.DataFrame(rows, columns=["date", "close"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df if not df.empty else None

    return _p


def _fake_screen(universe, run_date, *, session, limit=None, regime=None):  # noqa: ANN001
    """Persist one screening + 3 candidates for ``run_date`` (deterministic ids)."""
    scr = DailyScreening(
        id=f"scr_{run_date.isoformat()}",
        run_date=run_date,
        universe="csi800",
        regime_label=regime or "Neutral",
    )
    session.add(scr)
    for i, code in enumerate(("000001", "000002", "000003")):
        session.add(
            DailyAlphaCandidate(
                id=f"cand_{run_date.isoformat()}_{code}",
                screening_id=scr.id,
                code=code,
                name=f"N{code}",
                regime_label=regime or "Neutral",
                hit_count=1,
                hit_strategies_json=json.dumps(["trend_follow"]),
                consensus_score=80.0 + i,
                aros_score=80.0 + i,
                rating="A",
                public_money_score=60.0,
                hidden_flow_score=60.0,
                sector_score=60.0,
            )
        )
    session.commit()
    return [i for i in range(3)]  # length == candidate count


def _deps(tmp_path, **overrides) -> RunDeps:
    base = dict(
        no_sync=True,
        no_papertrade=True,
        no_money_flow=True,
        auto_validate_at=None,
        price_provider=_make_price(SCHEDULE),
        screen_fn=_fake_screen,
        report_out_dir=str(tmp_path),
    )
    base.update(overrides)
    return RunDeps(**base)


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
def test_run_daily_wires_pipeline(tmp_path) -> None:
    session = _mem_session()
    s = run_daily(session, DAYS[0], _deps(tmp_path))

    # 4.2 screening + Top-N candidates persisted.
    assert session.query(DailyScreening).filter_by(run_date=DAYS[0]).count() == 1
    assert session.query(DailyAlphaCandidate).count() == 3
    # 4.6 calibration filled one CandidatePerformance per candidate.
    assert session.query(CandidatePerformance).count() == 3
    # 4.4 report written in all three formats.
    assert os.path.exists(s["report_paths"]["md"])
    assert os.path.exists(s["report_paths"]["html"])
    assert os.path.exists(s["report_paths"]["xlsx"])
    # Summary coherent.
    assert s["candidates"] == 3
    assert s["performance_rows"] == 3
    assert s["posthoc_rows"] == 0  # no decisions recorded yet


def test_run_daily_idempotent(tmp_path) -> None:
    session = _mem_session()
    run_daily(session, DAYS[0], _deps(tmp_path))
    run_daily(session, DAYS[0], _deps(tmp_path))  # re-run same date
    # No duplicate screening / candidates despite two passes.
    assert session.query(DailyScreening).filter_by(run_date=DAYS[0]).count() == 1
    assert session.query(DailyAlphaCandidate).count() == 3
    assert session.query(CandidatePerformance).count() == 3


def test_run_daily_backfills_decision_posthoc(tmp_path) -> None:
    session = _mem_session()
    run_daily(session, DAYS[0], _deps(tmp_path))
    cand = session.query(DailyAlphaCandidate).filter_by(code="000001").first()
    dt = record_decision(session, cand.id, "买入", "test")
    assert dt.result_10d is None

    run_daily(session, DAYS[0], _deps(tmp_path))  # re-run -> post-hoc fill
    dt2 = session.get(DecisionTracking, dt.id)
    assert dt2 is not None
    assert dt2.result_10d is not None  # 4.5 evidence auto-filled


def test_checkpoint_validation_report_at_one(tmp_path) -> None:
    session = _mem_session()
    s = run_daily(session, DAYS[0], _deps(tmp_path, auto_validate_at=1))
    # At the first trading day the checkpoint validation report is generated.
    assert s["validation_report_paths"] is not None
    vp = s["validation_report_paths"]
    assert os.path.exists(vp["md"])
    assert os.path.exists(vp["html"])
    assert os.path.exists(vp["xlsx"])


def test_checkpoint_suppressed_before_threshold(tmp_path) -> None:
    session = _mem_session()
    s = run_daily(session, DAYS[0], _deps(tmp_path, auto_validate_at=60))
    # With the default 60-day threshold, day 1 does NOT emit a checkpoint report.
    assert s["validation_report_paths"] is None
    assert isinstance(s["validation_can_calibrate"], bool)


# --------------------------------------------------------------------------- #
# catch_up self-heal
# --------------------------------------------------------------------------- #
def test_catch_up_backfills_missing_days(tmp_path) -> None:
    session = _mem_session()
    deps = _deps(tmp_path)
    run_daily(session, DAYS[0], deps)
    run_daily(session, DAYS[2], deps)  # deliberately skip DAYS[1]

    assert _has_screening(session, DAYS[0])
    assert not _has_screening(session, DAYS[1])
    assert _has_screening(session, DAYS[2])

    res = catch_up(session, DAYS[0], DAYS[2], deps)
    assert res["backfilled"] == [DAYS[1].isoformat()]
    assert _has_screening(session, DAYS[1])
    # No duplicates for the days already processed.
    assert session.query(DailyScreening).filter_by(run_date=DAYS[0]).count() == 1
    assert session.query(DailyScreening).filter_by(run_date=DAYS[2]).count() == 1
