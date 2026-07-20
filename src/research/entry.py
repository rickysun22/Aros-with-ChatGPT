"""Phase 4.7 — Entry Intelligence (Alpha Entry Engine, the synthesis layer).

This module answers *"现在是否适合买？"* (Entry Score), which is deliberately
kept **independent** of the AROS Score (which answers *"值不值得研究？"*).

Design contract (design Part III §III.3): the Entry Engine is a *synthesis
layer*, not a follower of any single strategy's ``entry_rules`` (those are
collected reference inputs). It blends three families of evidence:

1. **Strategy-combo signal** — the categories of the strategies that hit the
   candidate (trend / strong / emotion) choose which timing model applies.
2. **Current stock reality** — price action, volume, relative position, and a
   near-limit-up guard so we never "chase the涨停".
3. **Market judgement** — regime friendliness + money-flow read.

The output is a single ``Entry Score`` (0-100) plus a discrete ``action`` and an
explainable ``reason`` string. Every network / DB dependency is injected so the
module is fully offline-testable (tests inject a fake ``PriceProvider``).

All timing math uses only data ``<= as_of`` — no look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from research.feedback import PriceProvider


# --------------------------------------------------------------------------- #
# Config + result contracts
# --------------------------------------------------------------------------- #
@dataclass
class EntryConfig:
    """Tunable weights / thresholds for the Entry Engine (design §III.3)."""

    # Component weights (must sum to 1.0).
    w_setup: float = 0.45  # timing setup quality (family model)
    w_not_extended: float = 0.20  # not overbought / not chasing limit-up
    w_trend_health: float = 0.20  # broader uptrend intact
    w_market_env: float = 0.15  # regime friendliness + money flow

    ma_short: int = 20
    ma_long: int = 60

    # Guard rails (hard caps).
    near_limit_up_cap: float = 40.0  # chasing 涨停 -> score capped here
    bear_regime_cap: float = 55.0  # defensive in Bear
    downtrend_cap: float = 40.0  # price below both MAs -> capped

    # Action thresholds on the final Entry Score.
    strong_buy_min: float = 80.0
    buy_min: float = 65.0
    wait_min: float = 45.0

    # Regime friendliness (0-100) used by the market-env component.
    regime_friendliness: dict[str, float] = field(
        default_factory=lambda: {
            "Bull": 100.0,
            "Neutral": 70.0,
            "Bear": 30.0,
            "EmotionHot": 80.0,
            "EmotionCold": 40.0,
        }
    )


@dataclass
class MarketState:
    """Market / money-flow context for one evaluation (design §III.3.3).

    ``regime`` is required; money-flow scores default to neutral (50) when the
    4.3 provider is not wired in, exactly like the consensus engine.
    """

    regime: str
    sector_score: float = 50.0
    public_money_score: float = 50.0
    hidden_flow_score: float = 50.0


@dataclass
class EntrySignal:
    """The Entry Engine's verdict for one (code, date)."""

    code: str
    date: date
    entry_score: float
    action: str  # strong_buy | buy | wait | avoid
    confidence: float  # 0-1, how decisive the timing read is
    components: dict[str, float]  # sub-scores (setup / not_extended / ...)
    reason: str
    # Context carried for the report layer (kept separate from the timing score).
    aros_score: float
    rating: str
    dominant_family: str


# --------------------------------------------------------------------------- #
# Pure price-action helpers (no look-ahead; data <= as_of only)
# --------------------------------------------------------------------------- #
def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, v)))


def _safe_div(a: float, b: float) -> float:
    return a / b if b not in (0.0, None) and b != 0 else 0.0


def _window(code: str, as_of: date, pp: PriceProvider, lookback: int = 60) -> pd.DataFrame | None:
    """Return an ascending (date, close[, high, low, volume]) frame up to as_of."""
    end = as_of
    # Pull a window ending at as_of; lookback*2 calendar days is enough for the
    # MA(60) on business days.
    import datetime as _dt

    start = as_of - _dt.timedelta(days=lookback * 2)
    df = pp(code, start, end)
    if df is None or df.empty or "close" not in df.columns:
        return None
    cols = ["date", "close"]
    for c in ("high", "low", "volume"):
        if c in df.columns:
            cols.append(c)
    out = df[cols].copy()
    # Keep dates as Timestamps (avoids object/date comparison pitfalls); the
    # caller only reads price columns, never the date index.
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").drop_duplicates("date")
    out = out[out["date"] <= pd.Timestamp(as_of)]
    return out if not out.empty else None


def _dominant_family(categories: list[str]) -> str:
    """Pick the dominant strategy category among the hits.

    trend / strong / emotion; "strong" is the balanced default when nothing hits.
    """
    if not categories:
        return "strong"
    counts: dict[str, int] = {}
    for c in categories:
        counts[c] = counts.get(c, 0) + 1
    # Prefer the explicit market-structure families when present; else strong.
    for pref in ("trend", "emotion", "strong"):
        if pref in counts:
            return pref
    return categories[0]


def _family_scores(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    vols: list[float],
    cfg: EntryConfig,
) -> dict[str, float]:
    """Three timing-model sub-scores (each 0-100) from price action."""
    n = len(closes)
    if n < 2:
        return {"trend": 0.0, "pullback": 0.0, "emotion": 0.0}

    last = closes[-1]
    prev = closes[-2]
    ma_s = float(pd.Series(closes).rolling(min(cfg.ma_short, n), min_periods=1).mean().iloc[-1])
    ma_l = float(pd.Series(closes).rolling(min(cfg.ma_long, n), min_periods=1).mean().iloc[-1])
    win20 = closes[-cfg.ma_short :] if n >= cfg.ma_short else closes
    high20 = max(win20)
    pct_from_high = _safe_div(last - high20, high20)

    # Volume expansion vs recent average (neutral 1.0 when volume absent).
    if vols and any(v > 0 for v in vols):
        series = pd.Series(vols).rolling(min(cfg.ma_short, n), min_periods=1).mean()
        avg_vol = float(series.iloc[-1])
        vol_ratio = _safe_div(vols[-1], avg_vol)
    else:
        vol_ratio = 1.0

    above_ma_s = last > ma_s
    above_ma_l = last > ma_l
    retreat = _safe_div(high20 - last, high20)  # 0 at high, grows as it falls back

    # --- trend breakout model ---
    breakout = above_ma_s and above_ma_l and (-0.03 <= pct_from_high <= 0.02)
    trend_score = 0.0
    if above_ma_l:
        trend_score += 35.0
    if breakout:
        trend_score += 45.0
    if above_ma_l and vol_ratio >= 1.2:
        trend_score += 20.0 * _clamp(vol_ratio - 1.0, 0.0, 1.0)
    trend_score = _clamp(trend_score)

    # --- pullback dip-buy model ---
    pullback_score = 0.0
    if above_ma_l:
        pullback_score += 40.0
    if retreat > 0.05:
        pullback_score += 35.0 * _clamp(retreat / 0.15, 0.0, 1.0)
    if vol_ratio < 0.85:
        pullback_score += 25.0 * _clamp((0.85 - vol_ratio) / 0.85, 0.0, 1.0)
    pullback_score = _clamp(pullback_score)

    # --- emotion leader model (divergence -> consensus) ---
    gap_up = highs[-1] > prev  # today traded above yesterday
    gap_held = lows[-1] >= prev * 0.995  # held the gap (didn't fill)
    emotion_score = 0.0
    if gap_up and gap_held:
        emotion_score += 45.0
    if vol_ratio >= 1.2:
        emotion_score += 35.0 * _clamp(vol_ratio - 1.0, 0.0, 1.5) / 1.5
    if above_ma_s:
        emotion_score += 20.0
    emotion_score = _clamp(emotion_score)

    return {"trend": trend_score, "pullback": pullback_score, "emotion": emotion_score}


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class EntryEngine:
    """Synthesis layer that produces the Entry Score (design §III.3)."""

    def __init__(self, config: EntryConfig | None = None) -> None:
        self.cfg = config or EntryConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        code: str,
        as_of: date,
        price_provider: PriceProvider,
        *,
        aros_score: float,
        rating: str,
        categories: list[str] | None = None,
        hit_strategies: list[str] | None = None,
        market: MarketState | None = None,
        config: EntryConfig | None = None,
    ) -> EntrySignal:
        """Synthesize the Entry Signal + Entry Score for ``code`` at ``as_of``.

        Args:
            code / as_of / price_provider: the candidate + business-day prices
                (only data ``<= as_of`` is used; no look-ahead).
            aros_score / rating: the candidate's quality read (context only;
                the Entry Score is computed independently).
            categories: dominant strategy categories (trend/strong/emotion) among
                the hits — selects the timing model. If ``None`` it is inferred
                from ``hit_strategies`` when a ``category_resolver`` is set, else
                defaults to "strong".
            hit_strategies: strategy ids (used only to resolve categories).
            market: regime + money-flow context; defaults to neutral.
        """
        cfg = config or self.cfg
        win = _window(code, as_of, price_provider, lookback=max(cfg.ma_long, cfg.ma_short))
        if win is None or win.empty:
            return EntrySignal(
                code=code,
                date=as_of,
                entry_score=0.0,
                action="avoid",
                confidence=0.0,
                components={},
                reason="无可用行情数据，无法评估买点",
                aros_score=aros_score,
                rating=rating,
                dominant_family=_dominant_family(categories or []),
            )

        closes = [float(x) for x in win["close"].to_numpy()]
        highs = [float(x) for x in win["high"].to_numpy()] if "high" in win.columns else closes
        lows = [float(x) for x in win["low"].to_numpy()] if "low" in win.columns else closes
        vols = [float(x) for x in win["volume"].to_numpy()] if "volume" in win.columns else []

        n = len(closes)
        last = closes[-1]
        prev = closes[-2]
        ma_s = float(pd.Series(closes).rolling(min(cfg.ma_short, n), min_periods=1).mean().iloc[-1])
        ma_l = float(pd.Series(closes).rolling(min(cfg.ma_long, n), min_periods=1).mean().iloc[-1])
        fam = _family_scores(closes, highs, lows, vols, cfg)
        dominant = _dominant_family(categories or [])

        # Select the timing setup by the dominant family.
        if dominant == "trend":
            setup = fam["trend"]
        elif dominant == "emotion":
            setup = fam["emotion"]
        else:  # strong -> best of momentum / mean-reversion
            setup = max(fam["trend"], fam["pullback"])

        # not_extended: penalize overbought + chasing limit-up.
        ext = _clamp((last / ma_s - 1.0) / 0.15, 0.0, 1.0) if ma_s > 0 else 0.0
        not_extended = _clamp(100.0 - 100.0 * ext)
        near_limit_up = last >= prev * 1.095
        if near_limit_up:
            not_extended = 0.0

        # trend_health: above long MA = healthy uptrend.
        trend_health = 100.0 if (last > ma_l and last > ma_s) else (60.0 if last > ma_l else 20.0)

        # market_env: regime friendliness + money flow (neutral 50 default).
        mkt = market or MarketState(regime="Neutral")
        friendly = float(cfg.regime_friendliness.get(mkt.regime, 70.0))
        money = 0.5 * mkt.public_money_score + 0.3 * mkt.hidden_flow_score + 0.2 * mkt.sector_score
        market_env = _clamp(0.5 * friendly + 0.5 * money)

        entry_score = _clamp(
            cfg.w_setup * setup
            + cfg.w_not_extended * not_extended
            + cfg.w_trend_health * trend_health
            + cfg.w_market_env * market_env
        )

        # Hard guard rails.
        guards: list[str] = []
        if near_limit_up:
            entry_score = min(entry_score, cfg.near_limit_up_cap)
            guards.append("逼近涨停，避免追高")
        if mkt.regime == "Bear":
            entry_score = min(entry_score, cfg.bear_regime_cap)
            guards.append("熊市环境，防守优先")
        if last < ma_s and last < ma_l:
            entry_score = min(entry_score, cfg.downtrend_cap)
            guards.append("价格跌破长短均线，趋势走弱")

        action, confidence = _action_and_confidence(entry_score, cfg, aros_score)

        # Build an explainable reason.
        fam_name = {"trend": "趋势突破", "strong": "强势综合", "emotion": "情绪龙头"}[dominant]
        reason = (
            f"主导模型={fam_name}；买点分={setup:.0f}/100，"
            f"未超买={not_extended:.0f}，趋势健康={trend_health:.0f}，"
            f"市场环境={market_env:.0f}；综合 Entry={entry_score:.0f}"
        )
        if guards:
            reason += "；⚠" + "，".join(guards)

        return EntrySignal(
            code=code,
            date=as_of,
            entry_score=entry_score,
            action=action,
            confidence=confidence,
            components={
                "setup": round(setup, 2),
                "not_extended": round(not_extended, 2),
                "trend_health": round(trend_health, 2),
                "market_env": round(market_env, 2),
            },
            reason=reason,
            aros_score=aros_score,
            rating=rating,
            dominant_family=dominant,
        )


def _action_and_confidence(score: float, cfg: EntryConfig, aros_score: float) -> tuple[str, float]:
    """Map an Entry Score to an action + confidence (0-1)."""
    if score >= cfg.strong_buy_min:
        action = "strong_buy"
    elif score >= cfg.buy_min:
        action = "buy"
    elif score >= cfg.wait_min:
        action = "wait"
    else:
        action = "avoid"
    # A low-quality name (C-ish) downgrades the action one notch for honesty.
    if aros_score < 55.0 and action in ("strong_buy", "buy"):
        action = "wait" if action == "strong_buy" else "avoid"
    conf = _clamp((score - cfg.wait_min) / (cfg.strong_buy_min - cfg.wait_min), 0.0, 1.0)
    return action, conf


# --------------------------------------------------------------------------- #
# DB helper (lazy import so entry.py stays lightweight / offline-testable)
# --------------------------------------------------------------------------- #
def resolve_categories(session: object, hit_strategies: list[str] | None) -> list[str]:
    """Resolve strategy ids -> categories via the research StrategyRegistry.

    Returns the category list (trend/strong/emotion) of the hit strategies, used
    by :meth:`EntryEngine.evaluate` to choose the timing model. An unknown id is
    skipped rather than raising, so a stale hit never breaks the evaluation.
    """
    if not hit_strategies:
        return []
    from research.kb import StrategyRegistry

    reg = StrategyRegistry(session)  # type: ignore[arg-type]
    cats: list[str] = []
    for sid in hit_strategies:
        row = reg.get(sid)
        if row is not None and getattr(row, "category", None):
            cats.append(row.category)
    return cats
