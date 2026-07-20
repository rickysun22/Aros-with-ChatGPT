"""Human Feedback Loop (Sprint 4.5).

Closes the loop opened by the 4.2 consensus engine + 4.4 daily report:

* ``DecisionTracking`` — a human records a judgement (关注/买入/放弃/忽略) on a
  daily Alpha candidate; the system then auto-fills the post-hoc results
  (1/3/5/10-day forward returns, float profit/loss, final return) from price
  data, so manual review only needs the human's interpretation.
* ``PersonalTrade`` — a self-kept trade blotter the user fills in manually after
  launch (design §3.6: the system never auto-derives here).

Everything that touches the network is injected as a ``price_provider`` so the
module is fully offline-testable (tests inject a fake); the CLI wires the real
``DataManager.get_daily``. All post-hoc math is pure and unit-tested.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from research.models import DailyAlphaCandidate, DailyScreening, DecisionTracking, PersonalTrade

# Human decision vocabulary (design §3.6 / v2 Sheet2).
DECISION_WATCH = "关注"
DECISION_BUY = "买入"
DECISION_DROP = "放弃"
DECISION_IGNORE = "忽略"
HUMAN_DECISIONS = (DECISION_WATCH, DECISION_BUY, DECISION_DROP, DECISION_IGNORE)

# Forward post-hoc horizons (trading days after the T+1 entry).
POSTHOC_DAYS = (1, 3, 5, 10)

# A price provider mirrors ``DataManager.get_daily``: given (code, start, end)
# it returns a DataFrame with at least 'date' + 'close' (ascending), or None.
PriceProvider = Callable[[str, date, date], "pd.DataFrame | None"]


def _next_trading_day_after(signal_date: date, dates: list[date]) -> date | None:
    """First date strictly greater than ``signal_date`` (the T+1 entry)."""
    for d in dates:
        if d > signal_date:
            return d
    return None


def post_hoc(
    code: str,
    signal_date: date,
    price_provider: PriceProvider,
    *,
    horizon_days: tuple[int, ...] = POSTHOC_DAYS,
    window: int = 30,
) -> dict[str, float | None] | None:
    """Compute post-hoc outcomes for ``code`` from its ``signal_date``.

    Entry is the first trading day strictly after ``signal_date`` (T+1 fill, no
    look-ahead). Returns a dict with ``result_{n}d`` for each horizon, plus
    ``max_float_profit`` / ``max_float_loss`` (favorable / adverse excursion over
    the longest horizon window) and ``final_return`` (= the longest available
    result). All values are total returns (price_N / entry - 1).

    Returns ``None`` when the provider yields no usable data, so callers degrade
    gracefully (no abort, no fabricated numbers).
    """
    end = date.fromordinal(signal_date.toordinal() + window)
    df = price_provider(code, signal_date, end)
    if df is None or df.empty or "close" not in df.columns or df["close"].isna().any():
        return None
    # Normalise to a clean (date, close) ascending series.
    rows = df[["date", "close"]].copy()
    rows["date"] = pd.to_datetime(rows["date"]).dt.date
    rows = rows.sort_values("date").drop_duplicates("date")
    dates = list(rows["date"])
    closes = [float(x) for x in rows["close"].to_numpy()]

    entry_date = _next_trading_day_after(signal_date, dates)
    if entry_date is None:
        return None
    # Index of the entry day within the sorted series.
    entry_idx = dates.index(entry_date)
    entry_close = closes[entry_idx]
    if entry_close <= 0:
        return None

    # Trading-day offsets after entry.
    fwd = closes[entry_idx:]
    longest = min(max(horizon_days), len(fwd) - 1)

    out: dict[str, float | None] = {}
    for n in horizon_days:
        if n <= len(fwd) - 1:
            out[f"result_{n}d"] = fwd[n] / entry_close - 1.0
        else:
            out[f"result_{n}d"] = None
    # Float excursion over the longest covered window (entry .. entry+longest).
    window_closes = fwd[: longest + 1]
    rets = [c / entry_close - 1.0 for c in window_closes]
    out["max_float_profit"] = max(rets) if rets else None
    out["max_float_loss"] = min(rets) if rets else None
    out["final_return"] = out[f"result_{max(horizon_days)}d"]
    return out


def record_decision(
    session: Session,
    candidate_id: str,
    human_decision: str,
    human_reason: str | None = None,
) -> DecisionTracking:
    """Record a human judgement on a candidate; create the tracking row.

    Looks up the candidate to capture ``code`` + ``signal_date`` (from its
    screening ``run_date``) so post-hoc has a stable anchor even if the screening
    row is later deleted. Raises ``ValueError`` on an unknown candidate id or an
    invalid decision label.
    """
    if human_decision not in HUMAN_DECISIONS:
        raise ValueError(
            f"invalid human_decision {human_decision!r}; choose from {HUMAN_DECISIONS}"
        )
    cand = session.get(DailyAlphaCandidate, candidate_id)
    if cand is None:
        raise ValueError(f"candidate_id {candidate_id!r} not found")
    screening = session.get(DailyScreening, cand.screening_id)
    if screening is None:
        raise ValueError(f"screening for candidate {candidate_id!r} not found")
    tracking = DecisionTracking(
        id=f"dt_{uuid.uuid4().hex[:8]}",
        candidate_id=candidate_id,
        code=cand.code,
        signal_date=screening.run_date,
        human_decision=human_decision,
        human_reason=human_reason,
    )
    session.add(tracking)
    session.commit()
    session.refresh(tracking)
    return tracking


def fill_posthoc(
    tracking: DecisionTracking,
    price_provider: PriceProvider,
    *,
    review_date: date | None = None,
) -> DecisionTracking:
    """Fill the post-hoc numeric columns on ``tracking`` in place (no commit).

    Returns the same row so callers can commit. Leaves the human columns
    (``verified_system`` / ``review_summary``) untouched — those are the human's.
    """
    res = post_hoc(tracking.code, tracking.signal_date, price_provider)
    if res is None:
        return tracking
    tracking.result_1d = res["result_1d"]
    tracking.result_3d = res["result_3d"]
    tracking.result_5d = res["result_5d"]
    tracking.result_10d = res["result_10d"]
    tracking.max_float_profit = res["max_float_profit"]
    tracking.max_float_loss = res["max_float_loss"]
    tracking.final_return = res["final_return"]
    tracking.review_date = review_date or date.today()
    return tracking


def review(
    session: Session,
    tracking_id: str,
    price_provider: PriceProvider,
    *,
    verified_system: bool | None = None,
    review_summary: str | None = None,
    review_date: date | None = None,
) -> DecisionTracking:
    """Fill post-hoc + optional human review fields, then persist.

    ``verified_system`` records whether the candidate validated the system's
    thesis; ``review_summary`` is the human's free-text retrospective.
    """
    tracking = session.get(DecisionTracking, tracking_id)
    if tracking is None:
        raise ValueError(f"tracking_id {tracking_id!r} not found")
    fill_posthoc(tracking, price_provider, review_date=review_date)
    if verified_system is not None:
        tracking.verified_system = verified_system
    if review_summary is not None:
        tracking.review_summary = review_summary
    session.commit()
    session.refresh(tracking)
    return tracking


def record_trade(
    session: Session,
    code: str,
    *,
    name: str | None = None,
    entry_date: date | None = None,
    entry_price: float | None = None,
    exit_date: date | None = None,
    exit_price: float | None = None,
    quantity: float | None = None,
    direction: str | None = None,
    pnl: float | None = None,
    pnl_pct: float | None = None,
    note: str | None = None,
    source: str = "人工录入",
) -> PersonalTrade:
    """Manually record a personal trade (design §3.6). System never derives these."""
    trade = PersonalTrade(
        id=f"pt_{uuid.uuid4().hex[:8]}",
        code=code,
        name=name,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=exit_date,
        exit_price=exit_price,
        quantity=quantity,
        direction=direction,
        pnl=pnl,
        pnl_pct=pnl_pct,
        note=note,
        source=source,
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return trade


def list_decisions(
    session: Session,
    *,
    code: str | None = None,
    human_decision: str | None = None,
) -> list[DecisionTracking]:
    """Query decision-tracking rows, optionally filtered by code / decision."""
    stmt = select(DecisionTracking)
    if code is not None:
        stmt = stmt.where(DecisionTracking.code == code)
    if human_decision is not None:
        stmt = stmt.where(DecisionTracking.human_decision == human_decision)
    return list(session.execute(stmt.order_by(DecisionTracking.created_at.desc())).scalars().all())


def list_trades(session: Session, *, code: str | None = None) -> list[PersonalTrade]:
    """Query personal trades, optionally filtered by code."""
    stmt = select(PersonalTrade)
    if code is not None:
        stmt = stmt.where(PersonalTrade.code == code)
    return list(session.execute(stmt.order_by(PersonalTrade.created_at.desc())).scalars().all())


def query_decisions(session: Session, run_date: date) -> dict[str, DecisionTracking]:
    """Map ``candidate_id -> DecisionTracking`` for a day's screening.

    Used by the 4.4 report to fill Sheet2's human columns when a decision exists.
    """
    rows = (
        session.query(DecisionTracking)
        .join(
            DailyAlphaCandidate,
            DecisionTracking.candidate_id == DailyAlphaCandidate.id,
        )
        .join(DailyScreening, DailyAlphaCandidate.screening_id == DailyScreening.id)
        .filter(DailyScreening.run_date == run_date)
        .all()
    )
    return {r.candidate_id: r for r in rows}
