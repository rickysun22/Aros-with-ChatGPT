"""Phase 4.8 — Exit Intelligence (Alpha Exit Engine, real Daily Exit Intelligence).

This module is the *real* Daily Exit Intelligence that upgrades the 4.7 paper
trading validation environment's proxy score-decay (design Part III §III.5).
Where the validation environment used a momentum *proxy* score (marked
``score_type="proxy"``), this engine consumes the **real AROS Score** — supplied
by an injectable :class:`ScoreProvider` that re-runs / reads the live consensus
output — and produces a **graded Exit Signal** with an explainable reason:

* **logic decay** — the real AROS Score has fallen below threshold, or dropped
  materially from its entry value (e.g. 92 → 65: the thesis logic is gone).
* **money weakening** — public / hidden money-flow read turned negative.
* **trend break** — price broke below its key moving average / key support.
* **stop hit** — the hard stop-loss level was breached.

The signal level is ``High`` / ``Medium`` / ``Low`` / ``None`` (never a binary
"SELL"); ``should_exit`` is ``True`` for High + Medium. Every dependency is
injected (``PriceProvider`` for peak / trend, ``ScoreProvider`` for the real
score) so the module is fully offline-testable. No look-ahead: only data
``<= as_of`` is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
from sqlalchemy.orm import Session

from research.feedback import PriceProvider


# --------------------------------------------------------------------------- #
# Result + config contracts
# --------------------------------------------------------------------------- #
@dataclass
class ExitScoreInput:
    """The real AROS scoring read for one (code, date), from a ScoreProvider."""

    aros_score: float
    entry_aros_score: float  # the score captured at entry (for decay)
    public_money_score: float | None = None
    hidden_flow_score: float | None = None
    sector_score: float | None = None


@dataclass
class ExitEvalConfig:
    """Tunable thresholds for the Exit Engine (design §III.4 / §III.5)."""

    stop_loss_mode: str = "fixed"  # fixed | atr (atr evaluated by caller)
    stop_loss_pct: float = 8.0
    trailing_enabled: bool = False
    trailing_trigger: float = 0.15  # peak profit to arm the trailing stop
    trailing_drawdown: float = 0.08  # exit when off the peak by this much
    score_decay_threshold: float = 70.0
    score_drop_threshold: float = 15.0  # AROS points lost vs entry -> decay
    deep_decay_multiplier: float = 2.0  # drop >= mult*threshold -> High
    money_weakening_threshold: float = 45.0
    trend_ma_period: int = 20


@dataclass
class ExitSignal:
    """The Exit Engine's graded verdict for one (code, date)."""

    code: str
    date: date
    level: str  # High | Medium | Low | None
    should_exit: bool
    reasons: list[str]
    aros_score: float | None
    score_drop: float | None  # entry_aros - current (positive = decayed)
    stop_hit: bool = False
    trend_broken: bool = False
    money_weakening: bool = False
    logic_decay: bool = False
    trailing_hit: bool = False


class ScoreProvider(Protocol):
    """Supplies the real AROS scoring read for (code, date).

    Production wires this to the consensus engine / latest daily screening; tests
    inject a deterministic fake. Must not use data after ``as_of``.
    """

    def __call__(self, code: str, as_of: date) -> ExitScoreInput | None: ...


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


def _price_window(code: str, start: date, end: date, pp: PriceProvider) -> pd.DataFrame | None:
    df = pp(code, start, end)
    if df is None or df.empty or "close" not in df.columns:
        return None
    cols = ["date", "close"]
    for c in ("high", "low"):
        if c in df.columns:
            cols.append(c)
    out = df[cols].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out = out.sort_values("date").drop_duplicates("date")
    return out if not out.empty else None


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class ExitEngine:
    """Graded Daily Exit Intelligence driven by the real AROS Score."""

    def __init__(self, config: ExitEvalConfig | None = None) -> None:
        self.cfg = config or ExitEvalConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        code: str,
        as_of: date,
        entry_price: float,
        price_provider: PriceProvider,
        score_provider: ScoreProvider,
        *,
        entry_date: date,
        entry_aros_score: float,
        rating: str = "",
        config: ExitEvalConfig | None = None,
    ) -> ExitSignal:
        """Produce the graded Exit Signal for a held position at ``as_of``.

        Args:
            code / as_of / entry_price / entry_date: the open position.
            price_provider: daily prices (used for peak / trailing / trend).
            score_provider: real AROS scoring read (§III.5).
            entry_aros_score: the score captured at entry, for decay comparison.
            rating: carried for context / explainability.
        """
        cfg = config or self.cfg
        win = _price_window(code, entry_date, as_of, price_provider)
        if win is None or win.empty:
            return ExitSignal(
                code=code,
                date=as_of,
                level="None",
                should_exit=False,
                reasons=["无可用行情数据，无法评估退出"],
                aros_score=None,
                score_drop=None,
            )

        dates = list(win["date"])
        if as_of not in dates:
            return ExitSignal(
                code=code,
                date=as_of,
                level="None",
                should_exit=False,
                reasons=["当前日期无行情，无法评估退出"],
                aros_score=None,
                score_drop=None,
            )
        i = dates.index(as_of)
        close_i = float(win["close"].iloc[i])

        # ---- Layer 1: hard stop loss (urgent) ----
        stop = entry_price * (1.0 - cfg.stop_loss_pct / 100.0)
        stop_hit = close_i <= stop

        # ---- Layer 2: trailing profit protection ----
        peak = float(pd.Series([float(x) for x in win["close"].to_numpy()[: i + 1]]).max())
        trailing_hit = False
        if cfg.trailing_enabled and peak >= entry_price * (1.0 + cfg.trailing_trigger):
            trail_exit = peak * (1.0 - cfg.trailing_drawdown)
            trailing_hit = close_i <= trail_exit

        # ---- Layer 3: trend break (price below key MA) ----
        closes = [float(x) for x in win["close"].to_numpy()]
        n = len(closes)
        ma = float(
            pd.Series(closes).rolling(min(cfg.trend_ma_period, n), min_periods=1).mean().iloc[-1]
        )
        trend_broken = close_i < ma

        # ---- Layer 4: real AROS score (logic decay + money) ----
        sinput = score_provider(code, as_of)
        aros = sinput.aros_score if sinput is not None else None
        score_drop = (entry_aros_score - aros) if aros is not None else None
        logic_decay = False
        if aros is not None:
            if aros < cfg.score_decay_threshold:
                logic_decay = True
            if score_drop is not None and score_drop >= cfg.score_drop_threshold:
                logic_decay = True

        money_weakening = False
        if sinput is not None:
            pub = sinput.public_money_score
            hid = sinput.hidden_flow_score
            if pub is not None and pub < cfg.money_weakening_threshold:
                money_weakening = True
            if hid is not None and hid < cfg.money_weakening_threshold:
                money_weakening = True

        # ---- Grade the signal ----
        reasons: list[str] = []
        if stop_hit:
            reasons.append(f"跌破硬止损（{stop:.2f}）")
        if trailing_hit:
            reasons.append(f"移动止盈触发（峰值 {peak:.2f} 回撤 {cfg.trailing_drawdown:.0%}）")
        if trend_broken:
            reasons.append(f"趋势破坏（收盘价 {close_i:.2f} < MA{cfg.trend_ma_period} {ma:.2f}）")
        if logic_decay and aros is not None:
            drop_txt = f"（{entry_aros_score:.0f}→{aros:.0f}）" if score_drop is not None else ""
            reasons.append(f"逻辑衰减：AROS Score 低于阈值{drop_txt}")
        if money_weakening:
            reasons.append("资金转弱（主力净流出 / 暗盘转负）")

        level, should_exit = _grade(
            stop_hit=stop_hit,
            trailing_hit=trailing_hit,
            trend_broken=trend_broken,
            logic_decay=logic_decay,
            money_weakening=money_weakening,
            score_drop=score_drop,
            cfg=cfg,
            in_profit=close_i >= entry_price,
        )

        return ExitSignal(
            code=code,
            date=as_of,
            level=level,
            should_exit=should_exit,
            reasons=reasons,
            aros_score=aros,
            score_drop=score_drop,
            stop_hit=stop_hit,
            trend_broken=trend_broken,
            money_weakening=money_weakening,
            logic_decay=logic_decay,
            trailing_hit=trailing_hit,
        )


def _grade(
    *,
    stop_hit: bool,
    trailing_hit: bool,
    trend_broken: bool,
    logic_decay: bool,
    money_weakening: bool,
    score_drop: float | None,
    cfg: ExitEvalConfig,
    in_profit: bool,
) -> tuple[str, bool]:
    """Map the fired flags to a (level, should_exit) pair.

    High  — forced exits (stop, or a broken trend while already under water).
    Medium — trailing hit, logic decay (incl. deep decay), money weakening, or a
             broken trend while still in profit (give the benefit of the doubt).
    Low   — only a minor warning fired.
    None  — nothing fired.
    """
    if stop_hit:
        return "High", True
    if trend_broken and not in_profit:
        return "High", True
    deep = score_drop is not None and (
        score_drop >= cfg.score_drop_threshold * cfg.deep_decay_multiplier
    )
    if deep:
        return "High", True
    if trailing_hit or logic_decay or money_weakening or trend_broken:
        return "Medium", True
    if stop_hit or trailing_hit:  # defensive: any forced flag is at least Medium
        return "Medium", True
    return "None", False


def consensus_score_provider(session: Session) -> ScoreProvider:
    """Build the real-AROS :class:`ScoreProvider` from the daily screening output.

    Returns a callable ``(code, as_of) -> ExitScoreInput | None`` that reads the
    latest :class:`~research.models.DailyAlphaCandidate` AROS Score (+ money-flow)
    for the code on/before ``as_of`` — the honest "real AROS Score" source for the
    4.8 Daily Exit Intelligence. Returns ``None`` when no candidate exists, so the
    engine never fabricates a decay signal.

    Shared by ``research.run_daily`` (the daily loop) and the ``alpha exit eval``
    CLI so both use one definition.
    """
    from research.models import DailyAlphaCandidate, DailyScreening

    def _p(code: str, as_of: date) -> ExitScoreInput | None:
        c = (
            session.query(DailyAlphaCandidate)
            .filter_by(code=code)
            .join(DailyScreening, DailyAlphaCandidate.screening_id == DailyScreening.id)
            .filter(DailyScreening.run_date <= as_of)
            .order_by(DailyScreening.run_date.desc())
            .first()
        )
        if c is None:
            return None
        return ExitScoreInput(
            aros_score=c.aros_score,
            entry_aros_score=c.aros_score,
            public_money_score=c.public_money_score,
            hidden_flow_score=c.hidden_flow_score,
            sector_score=c.sector_score,
        )

    return _p
