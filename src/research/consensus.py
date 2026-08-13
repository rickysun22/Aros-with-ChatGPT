"""Phase 4.2 Multi-Strategy Consensus Engine (design §4 / §5 4.2).

Aggregates *daily* entry signals from every ``active`` library strategy into a
ranked set of Alpha candidates:

    active strategies -> per-code daily signals -> screening_hits
                      -> Consensus Score (H+Q+I+R+S)
                      -> AROS Final Score (consensus/env/money/risk)
                      -> persist DailyScreening + ScreeningHit + DailyAlphaCandidate

The scoring math is fully specified in the design (§4) and is implemented as
pure functions so it can be unit-tested offline without a database or network.

Money-flow / sector components (S in Consensus, ``money_flow`` in AROS) are
owned by Sprint 4.3. They are exposed here as pluggable providers; when none is
wired in they return a *neutral* score (50) so this sprint is self-contained and
the AROS constitution (hidden flow never eliminates a candidate) is preserved.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from core.config import AppConfig, ConsensusConfig, get_config
from research.market_regime import NEUTRAL
from research.models import (
    DailyAlphaCandidate,
    DailyScreening,
    ScreeningHit,
    StrategyValidation,
)
from research.strategy_library import get_strategy
from research.universe_provider import get_universe_provider


# --------------------------------------------------------------------------- #
# Pluggable providers (Sprint 4.3 owns the real implementations)
# --------------------------------------------------------------------------- #
@dataclass
class MoneyFlowSignal:
    """Public money-flow read for one stock (0-100 scores, never an amount)."""

    sector_score: float  # 个股相对所属板块强弱百分位
    public_money_score: float  # 板块资金流百分位


@dataclass
class HiddenFlowSignal:
    """Behavioural-inference read of hidden / smart money (no fabricated amount)."""

    score: float  # 0-100 behavioural-inference score
    explanation: str  # human-readable rationale (守住 v2 红线：无金额)


class MoneyFlowProvider(Protocol):
    """Sprint 4.3 interface: public money flow + sector strength for a code."""

    def get_stock_flow(self, code: str) -> MoneyFlowSignal: ...


class HiddenFlowProvider(Protocol):
    """Sprint 4.3 interface: behavioural inference of hidden flow (no amount)."""

    def infer(self, code: str) -> HiddenFlowSignal: ...


class _NeutralMoneyFlow:
    """Default money-flow provider: neutral (50) when 4.3 is not wired in."""

    def get_stock_flow(self, code: str) -> MoneyFlowSignal:
        return MoneyFlowSignal(sector_score=50.0, public_money_score=50.0)


class _NeutralHiddenFlow:
    """Default hidden-flow provider: neutral (50) + a clear 'no source' note."""

    def infer(self, code: str) -> HiddenFlowSignal:
        return HiddenFlowSignal(
            score=50.0, explanation="无暗盘数据源(4.3 接入)，取中性分；不淘汰候选"
        )


# --------------------------------------------------------------------------- #
# Result contract
# --------------------------------------------------------------------------- #
@dataclass
class ConsensusResult:
    """One ranked Alpha candidate produced by :meth:`ConsensusEngine.daily`."""

    code: str
    hit_count: int
    hit_strategies: list[str]
    avg_quality_star: float | None
    max_quality_star: float | None
    consensus_score: float
    aros_score: float
    rating: str
    regime_label: str
    consensus_breakdown: dict[str, float] = field(default_factory=dict)
    aros_breakdown: dict[str, float] = field(default_factory=dict)
    sector_score: float | None = None
    public_money_score: float | None = None
    hidden_flow_score: float | None = None
    risk_filter: float | None = None
    advantages: str | None = None
    risks: str | None = None
    thesis: str | None = None
    system_suggestion: str | None = None


# --------------------------------------------------------------------------- #
# Pure scoring math (unit-testable, no DB / network)
# --------------------------------------------------------------------------- #
def _star_of(hit: Mapping[str, Any], cfg: ConsensusConfig) -> float:
    """quality_star for a hit, falling back to the configured default."""
    q = hit.get("quality_star")
    return float(q) if q is not None else float(cfg.default_star_when_unvalidated)


def _paired(a: Sequence[float | None], b: Sequence[float | None]) -> list[tuple[float, float]]:
    """Align two OOS fold-return lists on positions where *both* are finite."""
    out: list[tuple[float, float]] = []
    for x, y in zip(a, b, strict=False):
        if x is not None and y is not None:
            out.append((float(x), float(y)))
    return out


def _pearson(a: Sequence[float | None], b: Sequence[float | None]) -> float | None:
    """Pearson correlation over positions where both series are finite.

    Returns ``None`` when there are fewer than 2 paired observations or either
    series has zero variance (treated as 'cannot judge' upstream, not 0)."""
    paired = _paired(a, b)
    if len(paired) < 2:
        return None
    xa = np.array([p[0] for p in paired], dtype=float)
    xb = np.array([p[1] for p in paired], dtype=float)
    if np.std(xa) == 0.0 or np.std(xb) == 0.0:
        return None
    return float(np.corrcoef(xa, xb)[0, 1])


def regime_match_fraction(current: str, best_fit_regimes: Sequence[Sequence[str]]) -> float:
    """Fraction of hitting strategies whose best-fit regimes contain ``current``.

    Full match -> 1.0; partial -> proportional; none -> ``regime_base`` (the
    design's "still give a base score, never hard-reject").
    """
    flat: list[str] = []
    for regs in best_fit_regimes:
        flat.extend(regs or [])
    total = len(best_fit_regimes)
    if total == 0:
        return 0.0
    matches = sum(1 for regs in best_fit_regimes if current in (regs or []))
    frac = matches / total
    return frac if frac > 0.0 else 0.0  # caller applies regime_base when 0


def _dedup_survivors(
    hits: list[dict[str, Any]],
    fold_by_strategy: Mapping[str, Sequence[float | None]],
    cfg: ConsensusConfig,
) -> set[str]:
    """Keep the highest-quality strategy per (category, correlation-cluster).

    Within one category, strategies whose OOS fold-return series are correlated
    above ``corr_dedup_threshold`` form a cluster; only the highest-star member
    survives into the quality / independence computation (design §4.1 ``I``).
    Non-survivors still count toward the hit count ``H``.
    """
    survivors = {h["strategy_id"] for h in hits}
    by_cat: dict[str, list[str]] = defaultdict(list)
    for h in hits:
        by_cat[h["category"]].append(h["strategy_id"])

    for ids in by_cat.values():
        avail = [s for s in ids if s in fold_by_strategy and fold_by_strategy[s]]
        if len(avail) < 2:
            continue
        # Union-find clusters by correlation > threshold.
        parent = {s: s for s in avail}

        def find(x: str, parent: dict[str, str] = parent) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str, parent: dict[str, str] = parent, _find=find) -> None:
            rx, ry = _find(x), _find(y)
            if rx != ry:
                parent[rx] = ry

        for i in range(len(avail)):
            for j in range(i + 1, len(avail)):
                c = _pearson(fold_by_strategy[avail[i]], fold_by_strategy[avail[j]])
                if c is not None and c > cfg.corr_dedup_threshold:
                    union(avail[i], avail[j])

        clusters: dict[str, list[str]] = defaultdict(list)
        for s in avail:
            clusters[find(s)].append(s)
        for members in clusters.values():
            if len(members) > 1:
                best = max(members, key=lambda s: _star_of(_hit_by_id(hits, s), cfg))
                for m in members:
                    if m != best:
                        survivors.discard(m)
    return survivors


def _hit_by_id(hits: list[dict[str, Any]], sid: str) -> dict[str, Any]:
    for h in hits:
        if h["strategy_id"] == sid:
            return h
    return {"strategy_id": sid, "category": "", "quality_star": None}


def independence_score(
    survivors: Sequence[str],
    fold_by_strategy: Mapping[str, Sequence[float | None]],
    cfg: ConsensusConfig,
) -> tuple[float, float]:
    """Independence component ``I`` from avg pairwise OOS-fold correlation.

    Returns ``(score, avg_corr)``. With fewer than two series available the
    strategy is treated as independent (avg_corr = 0 -> full credit).
    """
    series = [
        fold_by_strategy[s] for s in survivors if s in fold_by_strategy and fold_by_strategy[s]
    ]
    if len(series) < 2:
        return float(cfg.w_independence), 0.0
    pairs: list[float] = []
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            c = _pearson(series[i], series[j])
            pairs.append(c if c is not None else 0.0)
    # Correlation magnitude (|r|): a negatively-correlated pair still shares one
    # factor and is NOT independent, so both signs count equally against I.
    avg = abs(sum(pairs) / len(pairs))
    avg = max(0.0, min(1.0, avg))
    return float(cfg.w_independence) * (1.0 - avg), avg


def consensus_score(
    hits: list[dict[str, Any]],
    fold_by_strategy: Mapping[str, Sequence[float | None]],
    current_regime: str,
    sector_score: float,
    public_money_score: float,
    cfg: ConsensusConfig,
) -> tuple[float, dict[str, float], set[str]]:
    """Consensus Score (0-100): H + Q + I + R + S (design §4.1).

    Returns ``(score, breakdown, survivors)``. ``survivors`` is the deduped set
    used for Q / I so correlated strategies do not inflate the quality read.
    """
    survivors = _dedup_survivors(hits, fold_by_strategy, cfg)
    n_hits = len(hits)

    # H -- hit count (saturating).
    h = float(cfg.w_hit) * min(n_hits, cfg.hit_cap) / cfg.hit_cap

    # Q -- mean quality star of survivors.
    if survivors:
        mean_star = sum(_star_of(_hit_by_id(hits, s), cfg) for s in survivors) / len(survivors)
    else:
        mean_star = _star_of(hits[0], cfg) if hits else 0.0
    q = float(cfg.w_quality) * mean_star / 5.0

    # I -- independence.
    i_score, avg_corr = independence_score(list(survivors), fold_by_strategy, cfg)

    # R -- regime match.
    reg_frac = regime_match_fraction(
        current_regime, [_hit_by_id(hits, s).get("best_fit_regimes", []) for s in survivors]
    )
    r = float(cfg.w_regime) * (reg_frac if reg_frac > 0.0 else cfg.regime_base)

    # S -- sector / money (0.6*sector + 0.4*public).
    s_input = 0.6 * sector_score + 0.4 * public_money_score
    s = float(cfg.w_sector_money) * s_input / 100.0

    score = h + q + i_score + r + s
    score = max(0.0, min(100.0, score))
    breakdown = {
        "hit": round(h, 3),
        "quality": round(q, 3),
        "independence": round(i_score, 3),
        "regime": round(r, 3),
        "sector_money": round(s, 3),
        "avg_corr": round(avg_corr, 4),
        "survivors": len(survivors),
        "hits": n_hits,
    }
    return score, breakdown, survivors


def aros_score(
    consensus: float,
    current_regime: str,
    sector_score: float | None,
    public_money_score: float | None,
    hidden_flow_score: float | None,
    risk_filter: float,
    cfg: ConsensusConfig,
) -> tuple[float, dict[str, float]]:
    """AROS Final Score (0-100): weighted blend (design §4.2)."""
    friend = float(cfg.regime_friendliness.get(current_regime, 70.0))
    sec = sector_score if sector_score is not None else 50.0
    pub = public_money_score if public_money_score is not None else 50.0
    hid = hidden_flow_score if hidden_flow_score is not None else 50.0

    env = 0.5 * friend + 0.5 * sec
    money = pub * float(cfg.money_visible_weight) + hid * float(cfg.money_hidden_weight)

    score = (
        float(cfg.w_aros_consensus) * consensus
        + float(cfg.w_aros_env) * env
        + float(cfg.w_aros_money) * money
        + float(cfg.w_aros_risk) * risk_filter
    )
    score = max(0.0, min(100.0, score))
    breakdown = {
        "consensus": round(consensus, 3),
        "market_sector_env": round(env, 3),
        "money_flow": round(money, 3),
        "risk_filter": round(risk_filter, 3),
        "regime_friendliness": round(friend, 2),
    }
    return score, breakdown


def rating_from_score(aros: float, cfg: ConsensusConfig) -> str:
    """Map an AROS score to a rating bucket (design §4.4 / Phase 4.6).

    The top bucket is ``"S"`` (renamed from the historical ``"A+"`` so the
    rating ladder reads S > A > B > C, matching the calibration vocabulary).
    """
    if aros >= cfg.rating_s:
        return "S"
    if aros >= cfg.rating_a:
        return "A"
    if aros >= cfg.rating_b:
        return "B"
    return "C"


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
PriceProvider = Callable[[list[str], str, str], dict[str, pd.DataFrame]]
BenchmarkProvider = Callable[[str, str, str], pd.Series]


class ConsensusEngine:
    """Daily multi-strategy consensus screening (design §5 4.2)."""

    def __init__(
        self,
        data_manager: Any | None = None,
        universe_engine: Any | None = None,
        config: AppConfig | None = None,
        price_provider: PriceProvider | None = None,
        benchmark_provider: BenchmarkProvider | None = None,
        money_flow_provider: MoneyFlowProvider | None = None,
        hidden_flow_provider: HiddenFlowProvider | None = None,
    ) -> None:
        self._dm = data_manager
        self._universe_engine = universe_engine
        self._cfg = config or get_config()
        self._cc = self._cfg.consensus
        self._price = price_provider
        self._bench = benchmark_provider
        self._money = money_flow_provider or _NeutralMoneyFlow()
        self._hidden = hidden_flow_provider or _NeutralHiddenFlow()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def daily(
        self,
        universe: str | None = None,
        signal_date: str | None = None,
        *,
        session: Session,
        limit: int | None = None,
        regime: str | None = None,
        notes: str | None = None,
    ) -> list[ConsensusResult]:
        """Run one daily screening and persist the candidate set.

        Args:
            universe: provider type override (csi800/watchlist/custom); None ->
                config default.
            signal_date: ``YYYY-MM-DD``; None -> today.
            session: DB session (writes DailyScreening / ScreeningHit / candidates).
            limit: cap on number of universe codes scanned (cost control).
            regime: explicit market regime label (tests); None -> inferred from a
                benchmark series when a benchmark provider is available.
            notes: free-text note persisted on the screening row.

        Returns:
            Ranked :class:`ConsensusResult` list (highest AROS first); the Top-N
            by AROS are also persisted as :class:`DailyAlphaCandidate` rows.
        """
        cfg = self._cfg
        sdate = pd.Timestamp(signal_date).date() if signal_date else date.today()
        provider = get_universe_provider(universe, config=cfg)
        codes = provider.codes(as_of=sdate)
        if limit is not None:
            codes = codes[:limit]

        regime_label = regime or self._infer_regime(sdate)

        # One price fetch for the whole universe, reused across strategies.
        prices = self._fetch_prices(codes, str(sdate))

        # Active library strategies.
        from research.kb import StrategyRegistry

        active = [r for r in StrategyRegistry(session).list_by_status("active")]

        # Aggregate hits: code -> list of hit dicts.
        hits_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in active:
            strat = get_strategy(row.executable_ref)
            try:
                signals = strat.entry_signals(prices)
            except Exception:  # defensive: one bad strategy must not abort the run
                continue
            for code in codes:
                sig = signals.get(code)
                if sig is None or not _signal_at(sig, sdate):
                    continue
                hits_by_code[code].append(
                    {
                        "strategy_id": row.strategy_id,
                        "category": row.category,
                        "quality_star": row.quality_star,
                        "validated": row.quality_star is not None,
                        "best_fit_regimes": _json_regimes(row.best_fit_regimes),
                    }
                )

        # Validation evidence (fold returns + max drawdown) per strategy.
        fold_by_strategy, max_dd_by_strategy = self._load_validations(
            session, {h["strategy_id"] for hs in hits_by_code.values() for h in hs}
        )

        # Idempotent re-run: drop any prior screening + its candidates/hits for
        # this date before persisting. No ON DELETE CASCADE is configured on the
        # FKs, so children must be removed explicitly, in dependency order.
        from research.models import (
            DailyScreening as _DS,
            DailyAlphaCandidate as _DAC,
            ScreeningHit as _SH,
            DecisionTracking as _DT,
            CandidatePerformance as _CP,
        )

        _prev_ids = [r.id for r in session.query(_DS.id).filter(_DS.run_date == sdate).all()]
        if _prev_ids:
            _cand_ids = [
                r.id
                for r in session.query(_DAC.id)
                .filter(_DAC.screening_id.in_(_prev_ids))
                .all()
            ]
            if _cand_ids:
                session.query(_DT).filter(_DT.candidate_id.in_(_cand_ids)).delete(
                    synchronize_session=False
                )
                session.query(_CP).filter(_CP.candidate_id.in_(_cand_ids)).delete(
                    synchronize_session=False
                )
                session.query(_DAC).filter(_DAC.screening_id.in_(_prev_ids)).delete(
                    synchronize_session=False
                )
            session.query(_SH).filter(_SH.screening_id.in_(_prev_ids)).delete(
                synchronize_session=False
            )
            session.query(_DS).filter(_DS.id.in_(_prev_ids)).delete(
                synchronize_session=False
            )
            session.flush()

        # Persist the screening header.
        screening_id = f"scr_{uuid.uuid4().hex[:8]}"
        session.add(
            DailyScreening(
                id=screening_id,
                run_date=sdate,
                universe=provider.__class__.__name__.replace("Provider", "").lower() or "custom",
                regime_label=regime_label,
                regime_detail_json=json.dumps(
                    {"notes": notes} if notes else {}, ensure_ascii=False
                ),
            )
        )

        # Build + score candidates.
        results: list[ConsensusResult] = []
        from data.models import Stock as _Stock

        name_map = {
            code: name
            for code, name in session.query(_Stock.code, _Stock.name).all()
        }
        for code, hits in hits_by_code.items():
            res = self._score_candidate(
                code, hits, fold_by_strategy, max_dd_by_strategy, regime_label, screening_id
            )
            results.append(res)
            # Persist screening hits (one row per hitting strategy).
            for h in hits:
                session.add(
                    ScreeningHit(
                        id=f"hit_{uuid.uuid4().hex[:8]}",
                        screening_id=screening_id,
                        strategy_id=h["strategy_id"],
                        code=code,
                        signal_date=sdate,
                        quality_star_snapshot=h["quality_star"],
                    )
                )

        # Rank by AROS and persist Top-N candidates.
        results.sort(key=lambda r: r.aros_score, reverse=True)
        top = results[: self._cc.top_n]
        # Read industry / sector from the persistent cache (StockIndustry) so the
        # scan stays fast and resilient to source flakiness / rate-limiting. Codes
        # not yet cached simply stay blank until the backfill job fetches them.
        from data.models import StockIndustry as _SI

        _ind_cache = {
            code: (ind, sec)
            for code, ind, sec in session.query(_SI.code, _SI.industry, _SI.sector).all()
        }
        for rank, res in enumerate(top, start=1):
            _ind, _sec = _ind_cache.get(res.code, (None, None))
            session.add(
                self._candidate_row(
                    res,
                    screening_id,
                    rank,
                    name=name_map.get(res.code),
                    industry=_ind,
                    sector=_sec,
                )
            )

        session.commit()
        return results

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _infer_regime(self, sdate: date) -> str:
        if self._bench is None:
            return NEUTRAL
        try:
            bench = self._bench(self._cfg.benchmark.default, "2010-01-01", str(sdate))
            from research.market_regime import MarketRegimeEngine

            eng = MarketRegimeEngine(self._cfg.research.market_regime)
            if isinstance(bench, pd.DataFrame):
                if "close" in bench.columns:
                    bench = bench.set_index("date")["close"].astype(float)
                elif bench.shape[1] == 1:
                    bench = bench.iloc[:, 0]
            return eng.current_regime(bench)
        except Exception:
            return NEUTRAL

    def _fetch_prices(self, codes: list[str], sdate: str) -> dict[str, pd.DataFrame]:
        if self._price is not None:
            return self._price(codes, self._cfg.data.start_date, sdate)
        if self._dm is None:
            return {}
        from data.manager import DataManager

        dm = self._dm if isinstance(self._dm, DataManager) else DataManager()
        out: dict[str, pd.DataFrame] = {}
        start = date.fromisoformat(self._cfg.data.start_date) if self._cfg.data.start_date else None
        end = date.fromisoformat(sdate) if sdate else None
        for code in codes:
            df = dm.get_daily(code, start, end)
            if df is not None and not df.empty:
                # Strategy contract: entry_signals() indexes its boolean Series by
                # date, so _signal_at() can locate the trigger on `sdate`. DataManager
                # returns a `date` *column* with a RangeIndex, which breaks that
                # lookup (Timestamp not found in an integer index -> every signal
                # filtered out -> zero candidates). Normalize to a DatetimeIndex here,
                # the single chokepoint feeding all strategies.
                if not isinstance(df.index, pd.DatetimeIndex):
                    if "date" in df.columns:
                        df = df.copy()
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.set_index("date")
                out[code] = df
        return out

    def _load_validations(
        self, session: Session, strategy_ids: set[str]
    ) -> tuple[dict[str, list[float | None]], dict[str, float]]:
        fold: dict[str, list[float | None]] = {}
        mdd: dict[str, float] = {}
        if not strategy_ids:
            return fold, mdd
        rows = (
            session.query(StrategyValidation)
            .filter(StrategyValidation.strategy_id.in_(strategy_ids))
            .order_by(StrategyValidation.created_at.desc())
            .all()
        )
        seen: set[str] = set()
        for v in rows:
            if v.strategy_id in seen:
                continue
            seen.add(v.strategy_id)
            try:
                oos = json.loads(v.oos_json)
                fr = oos.get("fold_returns")
                if isinstance(fr, list):
                    fold[v.strategy_id] = [float(x) if x is not None else None for x in fr]
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                metrics = json.loads(v.metrics_json)
                dd = metrics.get("max_drawdown")
                if isinstance(dd, (int, float)):
                    mdd[v.strategy_id] = abs(float(dd))
            except (json.JSONDecodeError, TypeError):
                pass
        return fold, mdd

    def _score_candidate(
        self,
        code: str,
        hits: list[dict[str, Any]],
        fold_by_strategy: Mapping[str, Sequence[float | None]],
        max_dd_by_strategy: Mapping[str, float],
        regime_label: str,
        screening_id: str,
    ) -> ConsensusResult:
        cc = self._cc
        # Money flow (4.3 provider; neutral by default).
        mflow = self._money.get_stock_flow(code)
        hflow = self._hidden.infer(code)
        sector_score = float(mflow.sector_score)
        public_money_score = float(mflow.public_money_score)
        hidden_flow_score = float(hflow.score)

        consensus, c_break, survivors = consensus_score(
            hits, fold_by_strategy, regime_label, sector_score, public_money_score, cc
        )

        # Risk filter: penalty when the worst hitting strategy's OOS max DD
        # exceeds the threshold (design §4.2 risk_filter).
        worst_dd = max(
            (max_dd_by_strategy.get(s, 0.0) for s in (h["strategy_id"] for h in hits)),
            default=0.0,
        )
        risk_filter = 100.0 - (cc.risk_dd_penalty if worst_dd > cc.risk_dd_threshold else 0.0)

        aros, a_break = aros_score(
            consensus,
            regime_label,
            sector_score,
            public_money_score,
            hidden_flow_score,
            risk_filter,
            cc,
        )
        rating = rating_from_score(aros, cc)

        stars = [_star_of(h, cc) for h in hits]
        avg_star = sum(stars) / len(stars) if stars else None
        max_star = max(stars) if stars else None

        # Infer explainable advantages / risks / thesis / system suggestion now
        # that rating + avg_star are known (Chinese, money-flow-aware text).
        advantages, risks, thesis, system_suggestion = _build_explanation(
            hits, regime_label, rating, avg_star
        )

        return ConsensusResult(
            code=code,
            hit_count=len(hits),
            hit_strategies=[h["strategy_id"] for h in hits],
            avg_quality_star=avg_star,
            max_quality_star=max_star,
            consensus_score=round(consensus, 3),
            aros_score=round(aros, 3),
            rating=rating,
            regime_label=regime_label,
            consensus_breakdown=c_break,
            aros_breakdown=a_break,
            sector_score=sector_score,
            public_money_score=public_money_score,
            hidden_flow_score=hidden_flow_score,
            risk_filter=risk_filter,
            advantages=advantages,
            risks=risks,
            thesis=thesis,
            system_suggestion=system_suggestion,
        )

    @staticmethod
    def _candidate_row(
        res: ConsensusResult,
        screening_id: str,
        rank: int,
        name: str | None = None,
        industry: str | None = None,
        sector: str | None = None,
    ) -> DailyAlphaCandidate:
        return DailyAlphaCandidate(
            id=f"dac_{uuid.uuid4().hex[:8]}",
            screening_id=screening_id,
            code=res.code,
            name=name,
            industry=industry,
            sector=sector or industry,  # 板块优先用缓存的行业划分,回退到行业名
            concepts_json=None,
            regime_label=res.regime_label,
            hit_count=res.hit_count,
            hit_strategies_json=json.dumps(res.hit_strategies, ensure_ascii=False),
            avg_quality_star=res.avg_quality_star,
            max_quality_star=res.max_quality_star,
            consensus_score=res.consensus_score,
            public_money_score=res.public_money_score,
            hidden_flow_score=res.hidden_flow_score,
            sector_score=res.sector_score,
            aros_score=res.aros_score,
            rating=res.rating,
            consensus_breakdown_json=json.dumps(res.consensus_breakdown, ensure_ascii=False),
            aros_breakdown_json=json.dumps(res.aros_breakdown, ensure_ascii=False),
            advantages=res.advantages,
            risks=res.risks,
            thesis=res.thesis,
            system_suggestion=res.system_suggestion,
        )


# --- Display helpers (Chinese names + explainability) ----------------- #
REGIME_CN: dict[str, str] = {
    "Bull": "牛市",
    "Neutral": "中性",
    "Bear": "熊市",
    "EmotionHot": "情绪过热",
    "EmotionCold": "情绪过冷",
}

try:
    from research.strategy_library import list_strategies as _list_strategies

    STRATEGY_CN: dict[str, str] = {s.spec.name: s.spec.display_name for s in _list_strategies()}
except Exception:  # pragma: no cover - defensive
    STRATEGY_CN = {}


def _strategy_cn(sid: str) -> str:
    """Chinese display name for a strategy id, falling back to the raw id."""
    return STRATEGY_CN.get(sid, sid)


def _stars(value: float | None) -> str:
    """Render a 0-5 quality-star float as a ★/☆ string (e.g. 3.0 -> '★★★')."""
    if value is None:
        return "-"
    n = int(round(value))
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def _build_explanation(
    hits: list[dict[str, Any]],
    regime_label: str,
    rating: str,
    avg_star: float | None,
) -> tuple[str, str, str, str]:
    """Infer human-readable advantages / risks / thesis / system suggestion from
    the hitting strategies (Chinese). Replaces the old hidden-flow-only note so
    the report carries a usable, explainable verdict even with no money-flow data.
    """
    names = [_strategy_cn(h["strategy_id"]) for h in hits]
    cats = {h.get("category") for h in hits}
    n = len(hits)
    regime_cn = REGIME_CN.get(regime_label, regime_label)

    adv_parts = [f"{n} 套策略共振（{'、'.join(names)}）"]
    if "trend" in cats:
        adv_parts.append("趋势多头结构确认")
    if "strong" in cats:
        adv_parts.append("强势股博弈形态")
    if "emotion" in cats:
        adv_parts.append("情绪/连板活跃度提升")
    advantages = "；".join(adv_parts)

    all_validated = all(h.get("validated") for h in hits)
    any_validated = any(h.get("validated") for h in hits)
    if all_validated:
        star_txt = _stars(avg_star) if avg_star is not None else ""
        risk_parts = [
            f"策略均已通过样本外验证（实测星级 {star_txt}），回测证据支撑",
            "资金流数据未接入（中性 50），暗盘风险不可见",
            "日线粒度，分时与盘口不可见，警惕追高与回撤",
        ]
    elif any_validated:
        risk_parts = [
            "部分策略已验证、部分未验证，证据强度不一",
            "资金流数据未接入（中性 50），暗盘风险不可见",
            "日线粒度，分时与盘口不可见，警惕追高与回撤",
        ]
    else:
        risk_parts = [
            "策略均未经验证（质量星级默认 3★），缺回测证据支撑",
            "资金流数据未接入（中性 50），暗盘风险不可见",
            "日线粒度，分时与盘口不可见，警惕追高与回撤",
        ]
    if avg_star is not None and avg_star <= 3.0:
        if all_validated or any_validated:
            risk_parts.append("样本外实测星级中性偏低，胜率/夏普需结合回测综合判断")
        else:
            risk_parts.insert(1, "信号质量中性，胜率尚未证实")
    risks = "；".join(risk_parts)

    thesis = (
        f"以{'、'.join(names)}为代表的多策略在截面日发出共振看多信号，"
        f"当前市况「{regime_cn}」。系统据此列为 Alpha 候选，"
        f"建议结合量价与板块强度二次确认后关注。"
    )

    if rating in ("S", "A"):
        sug = f"共振强度 {rating} 级，优先纳入观察池，放量确认后逢低布局。"
    elif rating == "B":
        sug = f"共振强度 B 级（中等），建议加入自选观察，等待更明确量价确认再介入。"
    else:
        sug = f"共振强度 {rating} 级偏弱，仅作关注，不建议直接介入。"
    return advantages, risks, thesis, sug


def _signal_at(sig: pd.Series, sdate: date) -> bool:
    """Boolean entry signal for ``sdate`` in a strategy signal Series."""
    ts = pd.Timestamp(sdate)
    if ts not in sig.index:
        return False
    val = sig.loc[ts]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return bool(val) if pd.notna(val) else False


def _json_regimes(raw: str | None) -> list[str]:
    """Parse the best_fit_regimes JSON column; tolerate None / bad JSON."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
