"""Daily operational orchestrator (Sprint 4.9 — the "run loop").

Wires the already-built engines into one idempotent, per-trading-day pass so the
system can run unattended and *accumulate out-of-sample evidence* — the
constitution's anti-overfit / no-look-ahead guarantees only become meaningful
once real data has accrued:

    seed KB          -> ensure the 10 built-in strategies are active (4.0)
    sync data        -> incremental: stock list + universe codes + benchmark
    consensus screen -> ConsensusEngine.daily  (persists DailyScreening + candidates)
    daily report     -> DailyAlphaReport (xlsx + html + md)
    calibration fill -> fill_all_performances  (4.6 CandidatePerformance)
    feedback fill    -> fill_all_posthoc       (4.5 decision post-hoc)
    papertrade sim   -> simulate_day           (optional; needs portfolios)
    checkpoint       -> at auto_validate_at trading days, generate_validation_reports

Every network-bound dependency is injected, so the loop is fully offline-testable
(tests pass fakes; production builds cached, real AKShare-backed providers). Each
step is keyed on ``run_date`` and skips work already done, so re-running the same
date is a safe idempotent refresh.

``catch_up`` backfills every missing trading day in a date range so an unattended
schedule that missed a day (machine off, network down) can self-heal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from research.exit import consensus_score_provider
from research.models import DailyScreening


# --------------------------------------------------------------------------- #
# Injectable dependencies (providers + flags) for one run
# --------------------------------------------------------------------------- #
@dataclass
class RunDeps:
    """All swappable inputs to :func:`run_daily` / :func:`catch_up`.

    A ``None`` provider means "use the production default" (built lazily inside
    :func:`run_daily`); tests override exactly what they need and pass
    ``no_sync`` / ``no_papertrade`` to skip the network-dependent steps.
    """

    universe: str | None = None
    limit: int | None = None
    regime: str | None = None
    money_flow_provider: Any = None
    hidden_flow_provider: Any = None
    price_provider: Any = None
    bench_provider: Any = None
    bench_code: str | None = None
    score_provider: Any = None
    screen_fn: Any = None  # (universe, run_date, *, session, limit, regime) -> list
    sync_fn: Any = None  # (session, run_date) -> None
    no_sync: bool = False
    no_papertrade: bool = False
    no_money_flow: bool = False
    auto_validate_at: int | None = 60
    report_out_dir: str = "reports"
    cache_dir: str | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _business_days(since: date, until: date) -> list[date]:
    """Return Mon–Fri weekdays in ``[since, until]`` (exchange-calendar proxy)."""
    days: list[date] = []
    d = since
    while d <= until:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _has_screening(session: Session, run_date: date) -> bool:
    """True if a DailyScreening already exists for ``run_date`` (idempotency)."""
    return (
        session.query(DailyScreening).filter(DailyScreening.run_date == run_date).first()
        is not None
    )


def _trading_days_count(session: Session, run_date: date) -> int:
    """Distinct screening dates on/before ``run_date`` = accumulated trading days."""
    return (
        session.query(func.count(func.distinct(DailyScreening.run_date)))
        .filter(DailyScreening.run_date <= run_date)
        .scalar()
        or 0
    )


def _can_calibrate(session: Session, run_date: date) -> bool:
    """Whether >= 60 trading days of evidence exist (design §5.2 two-stage)."""
    try:
        from research.calibration import build_validation_payload

        payload = build_validation_payload(session, as_of=run_date)
        return bool(payload["calibration"]["can_calibrate"])
    except Exception:  # noqa: BLE001 - payload is best-effort; never block a run
        return False


def _screen(session: Session, deps: RunDeps, run_date: date) -> list[Any]:
    """Run the daily consensus screen (real engine, or an injected fake)."""
    if deps.screen_fn is not None:
        return list(
            deps.screen_fn(
                deps.universe,
                run_date,
                session=session,
                limit=deps.limit,
                regime=deps.regime,
            )
        )
    from core.config import get_config
    from data.manager import DataManager
    from research.consensus import ConsensusEngine
    from universe.engine import UniverseEngine

    dm = DataManager()
    ue = UniverseEngine()
    cfg = get_config()

    mf = deps.money_flow_provider
    hf = deps.hidden_flow_provider
    if not deps.no_money_flow and (mf is None or hf is None):
        from data.cache import CachedHiddenFlowProvider, CachedMoneyFlowProvider, DayCache
        from data.providers.moneyflow import AkShareHiddenFlowProvider, AkShareMoneyFlowProvider

        cmf = DayCache(f"{deps.cache_dir}/moneyflow") if deps.cache_dir else None
        chf = DayCache(f"{deps.cache_dir}/hiddenflow") if deps.cache_dir else None
        if mf is None:
            mf = CachedMoneyFlowProvider(AkShareMoneyFlowProvider(), cmf)
        if hf is None:
            hf = CachedHiddenFlowProvider(AkShareHiddenFlowProvider(), chf)

    engine = ConsensusEngine(
        data_manager=dm,
        universe_engine=ue,
        config=cfg,
        benchmark_provider=deps.bench_provider,
        money_flow_provider=mf,
        hidden_flow_provider=hf,
    )
    return list(
        engine.daily(
            deps.universe,
            run_date.isoformat(),
            session=session,
            limit=deps.limit,
            regime=deps.regime,
        )
    )


def _price_provider(session: Session, deps: RunDeps) -> Callable[..., Any]:
    """Return the price provider to use (injected, or cached real reads)."""
    if deps.price_provider is not None:
        return cast("Callable[..., Any]", deps.price_provider)
    from data.cache import DayCache, cached_daily_price_provider
    from data.manager import DataManager

    dm = DataManager()
    cm = DayCache(f"{deps.cache_dir}/prices", ttl_days=7) if deps.cache_dir else None
    return cast("Callable[..., Any]", cached_daily_price_provider(dm, cm))


def _sync_data(session: Session, deps: RunDeps, run_date: date) -> None:
    """Incremental data sync for one day (production default). Best-effort."""
    if deps.sync_fn is not None:
        deps.sync_fn(session, run_date)
        return
    from core.config import get_config
    from data.manager import DataManager
    from universe.engine import UniverseEngine

    dm = DataManager()
    ue = UniverseEngine()
    try:
        dm.sync_stock_list()
    except Exception as exc:  # noqa: BLE001 - one source failure must not abort
        print(f"[run_daily] stock-list sync failed: {exc}")
    pool = deps.universe or "csi800"
    if pool == "all_a":
        # The full A-share universe lives in the persisted ``Stock`` table (filled
        # by sync_stock_list above), not in a named UniversePool row. Resolve it
        # there so the daily incremental sync covers the whole market.
        stock_df = dm.get_stock_list()
        codes = [str(c) for c in stock_df["code"].tolist()] if "code" in stock_df.columns else []
    else:
        try:
            codes = ue.get_codes(pool)
        except Exception:  # noqa: BLE001 - pool may not exist yet
            codes = []
    if deps.limit:
        codes = list(codes)[: deps.limit]
    for code in codes:
        try:
            # Incremental: pick up where the last sync left off, capped at the
            # run date. A first-ever sync (no SyncState) falls back to the
            # config start_date for the full backfill; every later daily run only
            # fetches the new trading days, so the scheduler stays cheap.
            last = dm.last_sync_date(code)
            start = (last + timedelta(days=1)) if last else None
            dm.sync_daily(code, start_date=start, end_date=run_date)
        except Exception as exc:  # noqa: BLE001 - one bad code must not abort
            print(f"[run_daily] sync {code} failed: {exc}")
    try:
        cfg = get_config()
        if cfg.benchmark.indices:
            bench_code = next(iter(cfg.benchmark.indices.values()))
            dm.sync_index(bench_code)
    except Exception as exc:  # noqa: BLE001
        print(f"[run_daily] benchmark sync failed: {exc}")


# --------------------------------------------------------------------------- #
# Core entry points
# --------------------------------------------------------------------------- #
def run_daily(
    session: Session,
    run_date: date,
    deps: RunDeps | None = None,
) -> dict[str, Any]:
    """Run one idempotent daily pass for ``run_date``.

    Returns a summary dict with candidate / backfill / report counts. Safe to
    re-run for the same date.
    """
    deps = deps or RunDeps()
    summary: dict[str, Any] = {
        "run_date": run_date.isoformat(),
        "candidates": 0,
        "performance_rows": 0,
        "posthoc_rows": 0,
        "entries": 0,
        "exits": 0,
        "report_paths": {},
        "validation_can_calibrate": False,
        "validation_report_paths": None,
    }

    # 1) Seed the strategy knowledge base (4.0) if empty.
    from research.kb import StrategyRegistry

    if not StrategyRegistry(session).list_by_status("active"):
        StrategyRegistry(session).seed_builtins()

    # 2) Incremental data sync (optional).
    if not deps.no_sync:
        _sync_data(session, deps, run_date)

    # 3) Daily multi-strategy consensus screen (skip if already done today so a
    #    re-run never duplicates candidates — the loop stays idempotent per date).
    if not _has_screening(session, run_date):
        _screen(session, deps, run_date)

    # 4) Daily Alpha report (xlsx + html + md).
    from report.daily_alpha import DailyAlphaReport, query_candidates
    from research.feedback import query_decisions

    candidates = query_candidates(session, run_date)
    summary["candidates"] = len(candidates)
    decisions = query_decisions(session, run_date)
    paths = DailyAlphaReport().generate(
        candidates,
        run_date,
        out_dir=deps.report_out_dir,
        decision_by_candidate=decisions,
    )
    summary["report_paths"] = {k: str(v) for k, v in paths.items()}

    # 5) Calibration performance fill (4.6) — pulls T+1/3/5/10/20 forward returns.
    from research.calibration import fill_all_performances

    pp = _price_provider(session, deps)
    summary["performance_rows"] = fill_all_performances(session, pp, as_of=run_date)

    # 6) Human-decision post-hoc fill (4.5).
    from research.feedback import fill_all_posthoc

    summary["posthoc_rows"] = fill_all_posthoc(session, pp, as_of=run_date)

    # 7) Paper-trading simulation (optional; needs portfolios to do anything).
    if not deps.no_papertrade:
        from research.papertrade import simulate_day

        if deps.score_provider is None:
            deps.score_provider = consensus_score_provider(session)
        sim = simulate_day(session, run_date, pp, score_provider=deps.score_provider)
        summary["entries"] = sim["entries"]
        summary["exits"] = sim["exits"]

    # 8) Checkpoint validation report at the configured trading-day threshold.
    summary["validation_can_calibrate"] = _can_calibrate(session, run_date)
    if deps.auto_validate_at is not None:
        if _trading_days_count(session, run_date) >= deps.auto_validate_at:
            from research.calibration import generate_validation_reports

            vpaths = generate_validation_reports(
                session,
                out_dir=deps.report_out_dir,
                as_of=run_date,
                bench_price_provider=deps.bench_provider,
                bench_code=deps.bench_code,
            )
            summary["validation_report_paths"] = {k: str(v) for k, v in vpaths.items()}

    return summary


def catch_up(
    session: Session,
    since: date,
    until: date | None = None,
    deps: RunDeps | None = None,
) -> dict[str, Any]:
    """Backfill every missing trading day in ``[since, until]`` (self-heal).

    Enumerates weekdays and runs :func:`run_daily` only for days that have no
    ``DailyScreening`` yet, so already-processed days are skipped. Returns the
    list of backfilled dates.
    """
    deps = deps or RunDeps()
    until = until or date.today()
    days = _business_days(since, until)
    backfilled: list[str] = []
    for d in days:
        if _has_screening(session, d):
            continue
        run_daily(session, d, deps)
        backfilled.append(d.isoformat())
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "examined": len(days),
        "backfilled": backfilled,
    }
