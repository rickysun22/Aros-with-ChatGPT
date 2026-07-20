"""Phase 4.6 — Rating Validation & Calibration (Sprint 4.6).

Closes the loop opened by 4.2 (selection) + 4.5 (human feedback): it proves the
AROS rating ladder actually ranks opportunity quality. Concretely:

* ``fill_all_performances`` auto-fills a :class:`CandidatePerformance` row for
  *every* daily Alpha candidate (not just the ones a human judged), pulling
  forward returns T+1/3/5/10/20 + float excursion + target-hit from price data.
* ``rating_distribution`` / ``significance_test`` answer the key question:
  do higher ratings earn significantly higher forward returns (S > A > B > C)?
* ``baseline_excess`` / ``strategy_contribution`` / ``human_vs_ai`` attribute
  the edge to the market, to individual strategies, and to human judgement.
* ``generate_validation_reports`` renders the four deliverables (Calibration /
  Strategy Contribution / Human Decision / Paper Trading stub) as md+html+xlsx.

Everything network-bound is injected as a ``price_provider`` (mirrors
``feedback.post_hoc``) so the module is fully offline-testable. The calibration
is deliberately *two-stage*: it only *proposes* threshold changes after >= 60
trading days of data — early runs stay in observe-only mode (design §5.2).
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from typing import TypedDict

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from research.feedback import PriceProvider, post_hoc
from research.models import (
    CandidatePerformance,
    DailyAlphaCandidate,
    DailyScreening,
    DecisionTracking,
    StrategyRegistry,
)

# Forward horizons used by the 4.6 candidate review (extends the 4.5 set with T+20).
CALIBRATION_HORIZONS = (1, 3, 5, 10, 20)
# Trading-day threshold before the first real calibration is allowed (design §5.2).
MIN_CALIBRATION_TRADING_DAYS = 60

RATINGS = ("S", "A", "B", "C")
HUMAN_ENGAGED = ("买入", "关注")


# --------------------------------------------------------------------------- #
# Typed payloads
# --------------------------------------------------------------------------- #
class RatingStat(TypedDict):
    count: int
    avg_return: float
    win_rate: float
    avg_max_drawdown: float
    avg_max_profit: float


class SignificanceRow(TypedDict):
    mean_diff: float | None
    ci_low: float | None
    ci_high: float | None
    mwu_p: float | None
    significant: bool
    sample: list[int]


class BaselineRow(TypedDict):
    per_rating: dict[str, float]
    overall: float


class StrategyContribRow(TypedDict):
    strategy_id: str
    name: str
    hits: int
    successes: int
    success_rate: float


class HumanVsAIRow(TypedDict):
    ai_avg: float
    ai_n: int
    human_avg: float
    human_n: int
    delta: float


class CalibrationRow(TypedDict):
    trading_days: int
    can_calibrate: bool
    proposed: dict[str, float] | None
    note: str


class ValidationPayload(TypedDict):
    as_of: str
    n_candidates: int
    n_performances: int
    coverage: float
    distribution: dict[str, RatingStat]
    monotone: bool
    significance: dict[str, SignificanceRow]
    baseline: BaselineRow | None
    strategy_contribution: list[StrategyContribRow]
    human_vs_ai: HumanVsAIRow
    calibration: CalibrationRow


# --------------------------------------------------------------------------- #
# Rating-label migration (historical "A+" -> "S")
# --------------------------------------------------------------------------- #
def migrate_rating_labels(session: Session) -> tuple[int, int]:
    """One-off migration of the historical top bucket label ``"A+"`` to ``"S"``.

    Returns ``(n_candidates, n_performances)`` rows updated. Idempotent: running
    it again on an already-migrated DB updates 0 rows. The change is also picked
    up automatically by ``fill_all_performances`` (it copies the candidate's
    current rating), so this mainly repairs rows written before 4.6.
    """
    n_cand = (
        session.query(DailyAlphaCandidate)
        .filter(DailyAlphaCandidate.rating == "A+")
        .update({DailyAlphaCandidate.rating: "S"})
    )
    n_perf = (
        session.query(CandidatePerformance)
        .filter(CandidatePerformance.rating == "A+")
        .update({CandidatePerformance.rating: "S"})
    )
    session.commit()
    return n_cand, n_perf


# --------------------------------------------------------------------------- #
# Daily fill
# --------------------------------------------------------------------------- #
def fill_all_performances(
    session: Session,
    price_provider: PriceProvider,
    as_of: date | None = None,
    *,
    target_pct: float = 0.05,
    horizons: tuple[int, ...] = CALIBRATION_HORIZONS,
) -> int:
    """Auto-fill :class:`CandidatePerformance` for every candidate (incremental).

    Skips rows that already have a T+20 value (their window has fully matured);
    recomputes rows still missing T+20 as time passes. Returns the number of rows
    (re)written. Never fabricates numbers — candidates with no price data are
    simply skipped.
    """
    cands = session.query(DailyAlphaCandidate).all()
    filled = 0
    for cand in cands:
        cp = session.get(CandidatePerformance, f"cp_{cand.id}")
        if cp is not None and cp.result_20d is not None:
            continue
        screening = session.get(DailyScreening, cand.screening_id)
        sig = screening.run_date if screening is not None else None
        if sig is None:
            continue
        res = post_hoc(
            cand.code,
            sig,
            price_provider,
            horizon_days=horizons,
            window=45,
            target_pct=target_pct,
        )
        if res is None:
            continue
        if cp is None:
            cp = CandidatePerformance(
                id=f"cp_{cand.id}",
                candidate_id=cand.id,
                code=cand.code,
                signal_date=sig,
                aros_score=cand.aros_score,
                rating=cand.rating,
            )
            session.add(cp)
        cp.result_1d = res["result_1d"]
        cp.result_3d = res["result_3d"]
        cp.result_5d = res["result_5d"]
        cp.result_10d = res["result_10d"]
        cp.result_20d = res["result_20d"]
        cp.max_float_profit = res["max_float_profit"]
        cp.max_float_loss = res["max_float_loss"]
        cp.target_hit_date = res.get("target_hit_date")
        cp.status = (
            "success"
            if res["result_10d"] is not None and res["result_10d"] > 0
            else ("fail" if res["result_10d"] is not None else "pending")
        )
        cp.filled_at = as_of or date.today()
        filled += 1
    session.commit()
    return filled


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def _returns_by_rating(session: Session) -> dict[str, list[float]]:
    """Map each rating to its list of realised T+10 returns (non-null only)."""
    rows = (
        session.query(CandidatePerformance)
        .filter(CandidatePerformance.result_10d.isnot(None))
        .all()
    )
    out: dict[str, list[float]] = {r: [] for r in RATINGS}
    for r in rows:
        if r.rating in out and r.result_10d is not None:
            out[r.rating].append(r.result_10d)
    return out


def _bootstrap_ci(
    a: list[float], b: list[float], n: int = 2000, seed: int = 7
) -> tuple[float, float]:
    """95% bootstrap CI of the difference in means (a - b)."""
    rng = np.random.default_rng(seed)
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    diffs = np.empty(n, dtype=float)
    for i in range(n):
        sa = rng.choice(av, size=av.size, replace=True)
        sb = rng.choice(bv, size=bv.size, replace=True)
        diffs[i] = float(sa.mean() - sb.mean())
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def _mann_whitney_p(a: list[float], b: list[float]) -> float | None:
    """Two-sided p-value via the normal approximation with tie correction."""
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    n, m = av.size, bv.size
    if n == 0 or m == 0:
        return None
    allv = np.concatenate([av, bv])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(allv.size, dtype=float)
    ranks[order] = np.arange(1, allv.size + 1, dtype=float)
    _, counts = np.unique(allv, return_counts=True)
    tie = float(((counts.astype(float) ** 3) - counts.astype(float)).sum() / 12.0)
    u = float(ranks[:n].sum() - n * (n + 1) / 2.0)
    mu = n * m / 2.0
    denom = n * m * (n + m + 1) / 12.0
    if n + m > 1:
        denom = denom - n * m * tie / ((n + m) * (n + m - 1))
    sigma = math.sqrt(denom) if denom > 0 else 0.0
    if sigma == 0:
        return 1.0
    z = (u - mu) / sigma
    return float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0)))))


def rating_distribution(session: Session) -> dict[str, RatingStat]:
    """Per-rating summary stats over realised T+10 returns."""
    by_rating = _returns_by_rating(session)
    out: dict[str, RatingStat] = {}
    for r in RATINGS:
        rets = by_rating[r]
        if not rets:
            out[r] = RatingStat(
                count=0,
                avg_return=float("nan"),
                win_rate=float("nan"),
                avg_max_drawdown=float("nan"),
                avg_max_profit=float("nan"),
            )
            continue
        arr = np.asarray(rets, dtype=float)
        wins = float((arr > 0).mean())
        draws = (
            session.query(CandidatePerformance)
            .filter(CandidatePerformance.rating == r)
            .filter(CandidatePerformance.max_float_loss.isnot(None))
            .all()
        )
        avg_dd = float("nan")
        if draws:
            avg_dd = float(np.mean([-(d.max_float_loss or 0.0) for d in draws]))
        profs = (
            session.query(CandidatePerformance)
            .filter(CandidatePerformance.rating == r)
            .filter(CandidatePerformance.max_float_profit.isnot(None))
            .all()
        )
        avg_up = float("nan")
        if profs:
            avg_up = float(np.mean([d.max_float_profit or 0.0 for d in profs]))
        out[r] = RatingStat(
            count=len(rets),
            avg_return=float(arr.mean()),
            win_rate=wins,
            avg_max_drawdown=avg_dd,
            avg_max_profit=avg_up,
        )
    return out


def significance_test(session: Session) -> dict[str, SignificanceRow]:
    """Adjacent-rating separation: bootstrap CI + Mann-Whitney p for S>A>B>C."""
    by_rating = _returns_by_rating(session)
    out: dict[str, SignificanceRow] = {}
    for hi, lo in (("S", "A"), ("A", "B"), ("B", "C")):
        a = by_rating.get(hi, [])
        b = by_rating.get(lo, [])
        if len(a) < 3 or len(b) < 3:
            out[f"{hi}-{lo}"] = SignificanceRow(
                mean_diff=None,
                ci_low=None,
                ci_high=None,
                mwu_p=None,
                significant=False,
                sample=[len(a), len(b)],
            )
            continue
        mean_diff = float(np.mean(a) - np.mean(b))
        ci_low, ci_high = _bootstrap_ci(a, b)
        p = _mann_whitney_p(a, b)
        significant = bool((ci_low > 0) and (p is not None and p < 0.05))
        out[f"{hi}-{lo}"] = SignificanceRow(
            mean_diff=mean_diff,
            ci_low=ci_low,
            ci_high=ci_high,
            mwu_p=p,
            significant=significant,
            sample=[len(a), len(b)],
        )
    return out


def baseline_excess(
    session: Session,
    bench_price_provider: PriceProvider,
    bench_code: str,
    as_of: date | None = None,
) -> BaselineRow | None:
    """Excess T+10 return vs a benchmark index, per rating and overall.

    For each candidate we pull the benchmark's T+10 return over the *same* entry
    window (T+1 after the signal date) and subtract it. Returns ``None`` when no
    benchmark data is available, so callers can skip gracefully.
    """
    rows = (
        session.query(CandidatePerformance)
        .filter(CandidatePerformance.result_10d.isnot(None))
        .all()
    )
    if not rows:
        return None
    per_rating: dict[str, list[float]] = {r: [] for r in RATINGS}
    overall: list[float] = []
    for r in rows:
        bench = post_hoc(
            bench_code, r.signal_date, bench_price_provider, horizon_days=(10,), window=20
        )
        if bench is None or bench["result_10d"] is None or r.result_10d is None:
            continue
        excess = r.result_10d - bench["result_10d"]
        if r.rating in per_rating:
            per_rating[r.rating].append(excess)
        overall.append(excess)
    if not overall:
        return None
    return BaselineRow(
        per_rating={r: float(np.mean(v)) if v else float("nan") for r, v in per_rating.items()},
        overall=float(np.mean(overall)),
    )


def strategy_contribution(session: Session) -> list[StrategyContribRow]:
    """Tally how often each strategy fired on candidates and on successes."""
    rows = session.query(CandidatePerformance).all()
    by_id: dict[str, dict[str, int]] = {}
    for r in rows:
        cand = session.get(DailyAlphaCandidate, r.candidate_id)
        if cand is None:
            continue
        try:
            strs = json.loads(cand.hit_strategies_json) if cand.hit_strategies_json else []
        except (json.JSONDecodeError, TypeError):
            strs = []
        success = r.status == "success"
        for sid in strs:
            if sid not in by_id:
                by_id[sid] = {"hits": 0, "successes": 0}
            by_id[sid]["hits"] += 1
            if success:
                by_id[sid]["successes"] += 1
    out: list[StrategyContribRow] = []
    for sid, c in by_id.items():
        reg = session.get(StrategyRegistry, sid)
        name = reg.name if reg is not None else sid
        rate = c["successes"] / c["hits"] if c["hits"] else float("nan")
        out.append(
            StrategyContribRow(
                strategy_id=sid,
                name=name,
                hits=c["hits"],
                successes=c["successes"],
                success_rate=rate,
            )
        )

    def _sort_key(d: StrategyContribRow):
        sr = d["success_rate"]
        return (d["hits"], 0.0 if (isinstance(sr, float) and math.isnan(sr)) else sr)

    out.sort(key=_sort_key, reverse=True)
    return out


def human_vs_ai(session: Session) -> HumanVsAIRow:
    """Compare AI Top-20 (by AROS score) vs Human Top-5 (engaged decisions)."""
    ai_rows = (
        session.query(CandidatePerformance)
        .join(DailyAlphaCandidate, CandidatePerformance.candidate_id == DailyAlphaCandidate.id)
        .filter(CandidatePerformance.result_10d.isnot(None))
        .order_by(DailyAlphaCandidate.aros_score.desc())
        .limit(20)
        .all()
    )
    ai_rets = [r.result_10d for r in ai_rows if r.result_10d is not None]
    human_rows = (
        session.query(CandidatePerformance)
        .join(DailyAlphaCandidate, CandidatePerformance.candidate_id == DailyAlphaCandidate.id)
        .join(DecisionTracking, CandidatePerformance.candidate_id == DecisionTracking.candidate_id)
        .filter(DecisionTracking.human_decision.in_(HUMAN_ENGAGED))
        .filter(CandidatePerformance.result_10d.isnot(None))
        .order_by(DailyAlphaCandidate.aros_score.desc())
        .limit(5)
        .all()
    )
    human_rets = [r.result_10d for r in human_rows if r.result_10d is not None]
    ai_avg = float(np.mean(ai_rets)) if ai_rets else float("nan")
    human_avg = float(np.mean(human_rets)) if human_rets else float("nan")
    if human_rets and ai_rets:
        delta = float(np.mean(human_rets) - np.mean(ai_rets))
    else:
        delta = float("nan")
    return HumanVsAIRow(
        ai_avg=ai_avg, ai_n=len(ai_rets), human_avg=human_avg, human_n=len(human_rets), delta=delta
    )


def propose_calibration(session: Session, as_of: date | None = None) -> CalibrationRow:
    """Two-stage calibration proposal (observe-first, no auto-apply).

    Returns the approximated trading-day count since the first candidate and a
    *proposed* set of rating thresholds (95/80/50 percentiles of AROS scores).
    Thresholds are only a recommendation — applying them is a manual config edit
    (design §5.2: first real calibration requires >= 60 trading days).
    """
    as_of = as_of or date.today()
    cands = session.query(DailyAlphaCandidate).all()
    if not cands:
        return CalibrationRow(
            trading_days=0, can_calibrate=False, proposed=None, note="no candidates yet"
        )
    scores = np.asarray([c.aros_score for c in cands], dtype=float)
    # The candidate's signal date lives on its parent screening (run_date).
    first = (
        session.query(func.min(DailyScreening.run_date))
        .join(DailyAlphaCandidate, DailyAlphaCandidate.screening_id == DailyScreening.id)
        .scalar()
    )
    if first is None:
        return CalibrationRow(
            trading_days=0, can_calibrate=False, proposed=None, note="no screening dates yet"
        )
    cal_days = max(0, round((as_of - first).days * 5 / 7))
    proposed = {
        "rating_s": float(np.percentile(scores, 95)),
        "rating_a": float(np.percentile(scores, 80)),
        "rating_b": float(np.percentile(scores, 50)),
    }
    return CalibrationRow(
        trading_days=cal_days,
        can_calibrate=cal_days >= MIN_CALIBRATION_TRADING_DAYS,
        proposed=proposed,
        note=(
            "样本充足，可校准"
            if cal_days >= MIN_CALIBRATION_TRADING_DAYS
            else f"样本不足（{cal_days} 交易日 < {MIN_CALIBRATION_TRADING_DAYS}），仅观察"
        ),
    )


# --------------------------------------------------------------------------- #
# Report rendering (md + html + xlsx)
# --------------------------------------------------------------------------- #
def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v * 100:+.2f}%"


def build_validation_payload(
    session: Session,
    as_of: date | None = None,
    bench_price_provider: PriceProvider | None = None,
    bench_code: str | None = None,
) -> ValidationPayload:
    """Collect every 4.6 metric into one payload for the renderers."""
    as_of = as_of or date.today()
    dist = rating_distribution(session)
    sig = significance_test(session)
    monotone = True
    for hi, lo in (("S", "A"), ("A", "B"), ("B", "C")):
        dh = dist.get(hi)
        dl = dist.get(lo)
        if dh is None or dl is None:
            monotone = False
        elif math.isnan(dh["avg_return"]) or math.isnan(dl["avg_return"]):
            monotone = False
        elif not (dh["avg_return"] > dl["avg_return"]):
            monotone = False
    n_perf = session.query(CandidatePerformance).count()
    n_cand = session.query(DailyAlphaCandidate).count()
    coverage = (n_perf / n_cand) if n_cand else float("nan")
    baseline: BaselineRow | None = None
    if bench_price_provider is not None and bench_code is not None:
        baseline = baseline_excess(session, bench_price_provider, bench_code, as_of=as_of)
    return ValidationPayload(
        as_of=as_of.isoformat(),
        n_candidates=n_cand,
        n_performances=n_perf,
        coverage=coverage,
        distribution=dist,
        monotone=monotone,
        significance=sig,
        baseline=baseline,
        strategy_contribution=strategy_contribution(session),
        human_vs_ai=human_vs_ai(session),
        calibration=propose_calibration(session, as_of=as_of),
    )


def _render_markdown(p: ValidationPayload) -> str:
    lines: list[str] = []
    lines.append(f"# AROS Rating Calibration Report — {p['as_of']}")
    lines.append("")
    cov = p["coverage"]
    cov_str = f"{cov:.1%}" if not math.isnan(cov) else "n/a"
    lines.append(
        f"- 候选总数: {p['n_candidates']} · 已复盘: {p['n_performances']} · 覆盖率: {cov_str}"
    )
    lines.append(f"- 评级单调 (S>A>B>C): **{'是' if p['monotone'] else '否'}**")
    lines.append("")
    lines.append("## 1. 评分有效性（分层统计）")
    lines.append("")
    lines.append("| 评级 | 数量 | 平均T+10收益 | 胜率 | 平均最大回撤 | 平均最大涨幅 |")
    lines.append("|---|---|---|---|---|---|")
    for r in RATINGS:
        d = p["distribution"].get(
            r,
            RatingStat(
                count=0,
                avg_return=float("nan"),
                win_rate=float("nan"),
                avg_max_drawdown=float("nan"),
                avg_max_profit=float("nan"),
            ),
        )
        lines.append(
            f"| {r} | {d['count']} | {_pct(d['avg_return'])} | "
            f"{_pct(d['win_rate'])} | {_pct(d['avg_max_drawdown'])} | {_pct(d['avg_max_profit'])} |"
        )
    lines.append("")
    lines.append("## 2. 档间显著性（bootstrap CI + Mann-Whitney）")
    lines.append("")
    lines.append("| 对比 | 样本 | 均值差 | 95% CI | MWU p | 显著 |")
    lines.append("|---|---|---|---|---|---|")
    for pair, s in p["significance"].items():
        if s["mean_diff"] is None:
            lines.append(f"| {pair} | {s['sample']} | n/a | n/a | n/a | 样本不足 |")
        else:
            pval = s["mwu_p"]
            pstr = f"{pval:.4f}" if pval is not None else "n/a"
            lines.append(
                f"| {pair} | {s['sample']} | {_pct(s['mean_diff'])} | "
                f"[{_pct(s['ci_low'])}, {_pct(s['ci_high'])}] | {pstr} | "
                f"{'✅' if s['significant'] else '❌'} |"
            )
    lines.append("")
    base = p["baseline"]
    if base is not None:
        lines.append("## 3. 基线超额（vs 基准）")
        lines.append("")
        lines.append(f"- 整体超额: {_pct(base['overall'])}")
        for r in RATINGS:
            v = base["per_rating"].get(r)
            lines.append(f"- {r}: {_pct(v) if v is not None else 'n/a'}")
        lines.append("")
    lines.append("## 4. 策略贡献")
    lines.append("")
    lines.append("| 策略 | 命中数 | 成功数 | 成功率 |")
    lines.append("|---|---|---|---|")
    for sc in p["strategy_contribution"]:
        lines.append(
            f"| {sc['name']} | {sc['hits']} | {sc['successes']} | {_pct(sc['success_rate'])} |"
        )
    lines.append("")
    hv = p["human_vs_ai"]
    lines.append("## 5. 人工 Top5 vs AI Top20")
    lines.append("")
    lines.append(
        f"- AI Top20 平均T+10: {_pct(hv['ai_avg'])}（n={hv['ai_n']}）\n"
        f"- 人工 Top5 平均T+10: {_pct(hv['human_avg'])}（n={hv['human_n']}）\n"
        f"- 差值（人工-AI）: {_pct(hv['delta'])}"
    )
    lines.append("")
    cal = p["calibration"]
    lines.append("## 6. 校准建议（两阶段）")
    lines.append("")
    lines.append(
        f"- 交易日数: {cal['trading_days']} · 能否校准: "
        f"**{'是' if cal['can_calibrate'] else '否'}**"
    )
    lines.append(f"- 说明: {cal['note']}")
    if cal["proposed"] is not None:
        pr = cal["proposed"]
        lines.append(
            f"- 建议阈值: S≥{pr['rating_s']:.1f} · A≥{pr['rating_a']:.1f} "
            f"· B≥{pr['rating_b']:.1f}"
        )
    lines.append("")
    lines.append("## 7. 模拟交易（Paper Trading）")
    lines.append("")
    lines.append("_Phase 4.7 产物，本报表仅占位。模拟盘上线后补充净值/收益/回撤等指标。_")
    lines.append("")
    return "\n".join(lines)


def _render_html(p: ValidationPayload) -> str:
    md = _render_markdown(p)
    # Minimal, dependency-free markdown -> html (headings, tables, bold, hr, lists).
    body: list[str] = []
    for raw in md.splitlines():
        line = raw
        if line.startswith("# "):
            body.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("| ") and line.endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        elif set(line.strip()) <= {"-"}:
            body.append("<hr/>")
        elif line.startswith("- "):
            body.append(f"<li>{line[2:]}</li>")
        else:
            body.append(f"<p>{line}</p>")
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;"
        "padding:0 1rem;color:#1a1a1a}h1{color:#b91c1c}h2{color:#7f1d1d;margin-top:1.6rem}"
        "table{border-collapse:collapse;width:100%;margin:.6rem 0}td,th{border:1px solid #ddd;"
        "padding:.4rem .6rem;font-size:.9rem}tr:nth-child(even){background:#fafafa}"
        "li{margin:.2rem 0}</style></head><body>" + "".join(body) + "</body></html>"
    )


def _render_xlsx(p: ValidationPayload, path: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Rating Calibration"
    ws.append(["AROS Rating Calibration", p["as_of"]])
    ws.append(["评级单调 (S>A>B>C)", "是" if p["monotone"] else "否"])
    ws.append([])
    ws.append(["评级", "数量", "平均T+10收益", "胜率", "平均最大回撤", "平均最大涨幅"])
    for r in RATINGS:
        d = p["distribution"].get(
            r,
            RatingStat(
                count=0,
                avg_return=float("nan"),
                win_rate=float("nan"),
                avg_max_drawdown=float("nan"),
                avg_max_profit=float("nan"),
            ),
        )
        ws.append(
            [
                r,
                d["count"],
                d["avg_return"],
                d["win_rate"],
                d["avg_max_drawdown"],
                d["avg_max_profit"],
            ]
        )
    ws.append([])
    ws.append(["对比", "样本", "均值差", "CI_low", "CI_high", "MWU p", "显著"])
    for pair, s in p["significance"].items():
        ws.append(
            [
                pair,
                str(s["sample"]),
                s["mean_diff"],
                s["ci_low"],
                s["ci_high"],
                s["mwu_p"],
                "是" if s["significant"] else "否",
            ]
        )
    ws.append([])
    ws.append(["策略", "命中数", "成功数", "成功率"])
    for sc in p["strategy_contribution"]:
        ws.append([sc["name"], sc["hits"], sc["successes"], sc["success_rate"]])
    ws.append([])
    hv = p["human_vs_ai"]
    ws.append(["AI Top20 平均T+10", hv["ai_avg"], f"n={hv['ai_n']}"])
    ws.append(["人工 Top5 平均T+10", hv["human_avg"], f"n={hv['human_n']}"])
    ws.append(["差值（人工-AI）", hv["delta"], ""])
    cal = p["calibration"]
    ws.append([])
    ws.append(["交易日数", cal["trading_days"], "能否校准", "是" if cal["can_calibrate"] else "否"])
    if cal["proposed"] is not None:
        pr = cal["proposed"]
        ws.append(["建议阈值 S/A/B", pr["rating_s"], pr["rating_a"], pr["rating_b"]])
    wb.save(path)


def generate_validation_reports(
    session: Session,
    out_dir: str = "reports",
    as_of: date | None = None,
    bench_price_provider: PriceProvider | None = None,
    bench_code: str | None = None,
) -> dict[str, str]:
    """Render the four 4.6 deliverables (combined) as md + html + xlsx.

    Output lands in ``<out_dir>/validation/<as_of>/``. Returns the three paths.
    """
    as_of = as_of or date.today()
    payload = build_validation_payload(
        session, as_of=as_of, bench_price_provider=bench_price_provider, bench_code=bench_code
    )
    folder = os.path.join(out_dir, "validation", as_of.isoformat())
    os.makedirs(folder, exist_ok=True)
    md_path = os.path.join(folder, "validation_report.md")
    html_path = os.path.join(folder, "validation_report.html")
    xlsx_path = os.path.join(folder, "validation_report.xlsx")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_markdown(payload))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(payload))
    _render_xlsx(payload, xlsx_path)
    return {"md": md_path, "html": html_path, "xlsx": xlsx_path}
