"""Phase 4.7 — Paper Trading (Exit Experiment, Sprint 4.7).

Closes the loop opened by 4.6 (selection is valid) by answering the next causal
question: *once we hold AROS picks, what is the best way to exit?* The experiment
is deliberately split into two orthogonal axes so the result is attributable
(design Part II §II.3):

* **Selection axis** -- S1 (ai S/A/B) / S2 (human enhanced) / S3 (random bench).
* **Exit axis** -- E1 (fixed) / E2 (trailing) / E3 (dynamic + score decay).

Phase 1 runs only **S1 + E1/E2/E3**. Every portfolio keeps its own trades, so the
6 combinations never share data (anti-confounding).

Hard red lines (constitution):
* No broker, no order, no auto-trading. ``SimulatedTrade`` is hypothetical only.
* No look-ahead. Entry = first trading day after the signal date (T+1 fill);
  every exit check uses only prices up to ``run_date``.

Three exit engines verified by unit tests:
* **Stop loss** -- ``fixed`` (default) or ``atr`` (adaptive; falls back to fixed
  when ``high``/``low`` columns are unavailable).
* **Profit protection** -- fixed take-profit (E1) or trailing stop (E2/E3).
* **Score decay** -- lightweight *proxy* score (price momentum mapped to 0-100);
  marked ``score_type="proxy"``. When ``score_decay.score_source == "real"`` a
  real AROS Score (from :mod:`research.exit`'s ``ScoreProvider``) drives the
  decay instead — this is the Phase 4.8 Daily Exit Intelligence, implemented in
  ``research/exit.py`` and wired in here.
* **Time stop** -- ``min(strategy, rating, portfolio)`` holding cap (design §II.4).

Everything network-bound is injected as a ``PriceProvider`` (mirrors
``feedback.post_hoc``) so the module is fully offline-testable.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict, cast

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from research.exit import ScoreProvider
from research.feedback import PriceProvider
from research.models import (
    DailyAlphaCandidate,
    DailyScreening,
    DecisionTracking,
    Portfolio,
    SimulatedTrade,
    StrategyRegistry,
)

# Rating-linked holding caps + hard-stop floors (design §II.4 rating table).
RATING_CAP_DAYS: dict[str, int] = {"S": 60, "A": 30, "B": 15}
RATING_STOP_PCT: dict[str, float] = {"S": 0.10, "A": 0.08, "B": 0.05}

PICKER_AI = "ai"
PICKER_HUMAN = "human"
PICKER_RANDOM = "random"

# Minimum closed trades before a metric is considered statistically meaningful.
MIN_SAMPLE_FOR_REPORT = 5


# --------------------------------------------------------------------------- #
# ExitConfig (drives E1 / E2 / E3 behaviour)
# --------------------------------------------------------------------------- #
@dataclass
class StopLossConfig:
    mode: str = "fixed"  # fixed | atr
    fixed_percent: float = 8.0
    atr_period: int = 14
    atr_multiplier: float = 2.0


@dataclass
class FixedTakeProfitConfig:
    enabled: bool = False
    percent: float = 20.0


@dataclass
class TrailingConfig:
    enabled: bool = False
    trigger_profit: float = 0.15
    drawdown: float = 0.08


@dataclass
class ScoreDecayConfig:
    enabled: bool = False
    window: int = 5
    threshold: float = 70.0
    # "proxy" (lightweight momentum stand-in, default) or "real" (4.8 Daily Exit
    # Intelligence: the real AROS Score supplied by a ScoreProvider). When "real"
    # but no score_provider is wired in, the environment falls back to proxy.
    score_source: str = "proxy"


@dataclass
class TimeStopConfig:
    from_rating: bool = True


@dataclass
class ExitConfig:
    """Serializable exit policy (design §II.5)."""

    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    fixed_tp: FixedTakeProfitConfig = field(default_factory=FixedTakeProfitConfig)
    trailing: TrailingConfig = field(default_factory=TrailingConfig)
    score_decay: ScoreDecayConfig = field(default_factory=ScoreDecayConfig)
    time_stop: TimeStopConfig = field(default_factory=TimeStopConfig)

    def to_json(self) -> str:
        return json.dumps(
            {
                "stop_loss": {
                    "mode": self.stop_loss.mode,
                    "fixed_percent": self.stop_loss.fixed_percent,
                    "atr": {
                        "period": self.stop_loss.atr_period,
                        "multiplier": self.stop_loss.atr_multiplier,
                    },
                },
                "fixed_tp": {
                    "enabled": self.fixed_tp.enabled,
                    "percent": self.fixed_tp.percent,
                },
                "trailing": {
                    "enabled": self.trailing.enabled,
                    "trigger_profit": self.trailing.trigger_profit,
                    "drawdown": self.trailing.drawdown,
                },
                "score_decay": {
                    "enabled": self.score_decay.enabled,
                    "window": self.score_decay.window,
                    "threshold": self.score_decay.threshold,
                    "score_source": self.score_decay.score_source,
                },
                "time_stop": {"from_rating": self.time_stop.from_rating},
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, s: str) -> ExitConfig:
        d = json.loads(s)
        sl = d.get("stop_loss", {})
        atr = sl.get("atr", {})
        ftp = d.get("fixed_tp", {})
        tr = d.get("trailing", {})
        sd = d.get("score_decay", {})
        ts = d.get("time_stop", {})
        return cls(
            stop_loss=StopLossConfig(
                mode=sl.get("mode", "fixed"),
                fixed_percent=float(sl.get("fixed_percent", 8.0)),
                atr_period=int(atr.get("period", 14)),
                atr_multiplier=float(atr.get("multiplier", 2.0)),
            ),
            fixed_tp=FixedTakeProfitConfig(
                enabled=bool(ftp.get("enabled", False)),
                percent=float(ftp.get("percent", 20.0)),
            ),
            trailing=TrailingConfig(
                enabled=bool(tr.get("enabled", False)),
                trigger_profit=float(tr.get("trigger_profit", 0.15)),
                drawdown=float(tr.get("drawdown", 0.08)),
            ),
            score_decay=ScoreDecayConfig(
                enabled=bool(sd.get("enabled", False)),
                window=int(sd.get("window", 5)),
                threshold=float(sd.get("threshold", 70.0)),
                score_source=sd.get("score_source", "proxy"),
            ),
            time_stop=TimeStopConfig(from_rating=bool(ts.get("from_rating", True))),
        )


def exit_preset(name: str) -> ExitConfig:
    """Return a ready-made ExitConfig for the exit-axis presets (design §II.3)."""
    if name == "E1":  # Fixed exit: fixed stop + fixed take-profit + time stop.
        cfg = ExitConfig()
        cfg.fixed_tp.enabled = True
        cfg.fixed_tp.percent = 20.0
        return cfg
    if name == "E2":  # Trailing exit: fixed stop floor + trailing profit.
        cfg = ExitConfig()
        cfg.trailing.enabled = True
        cfg.trailing.trigger_profit = 0.15
        cfg.trailing.drawdown = 0.08
        return cfg
    if name == "E3":  # Dynamic exit: trailing + score-decay proxy + time stop.
        cfg = ExitConfig()
        cfg.trailing.enabled = True
        cfg.trailing.trigger_profit = 0.15
        cfg.trailing.drawdown = 0.08
        cfg.score_decay.enabled = True
        cfg.score_decay.window = 5
        cfg.score_decay.threshold = 70.0
        return cfg
    raise ValueError(f"unknown exit preset {name!r} (expected E1/E2/E3)")


# --------------------------------------------------------------------------- #
# Calendar / price helpers (no look-ahead)
# --------------------------------------------------------------------------- #
def _next_business_day(d: date) -> date:
    return cast(date, (pd.Timestamp(d) + pd.tseries.offsets.BusinessDay(1)).date())


def _prev_business_day(d: date) -> date:
    return cast(date, (pd.Timestamp(d) - pd.tseries.offsets.BusinessDay(1)).date())


def _business_days_held(start: date, end: date) -> int:
    """Count of business days from ``start`` to ``end`` inclusive, minus 1."""
    rng = pd.bdate_range(start, end)
    return max(0, len(rng) - 1)


def _price_window(code: str, start: date, end: date, pp: PriceProvider) -> pd.DataFrame | None:
    """Return a clean ascending (date, close[, high, low]) frame, or None."""
    df = pp(code, start, end)
    if df is None or df.empty or "close" not in df.columns:
        return None
    cols = ["date", "close"]
    if "high" in df.columns:
        cols.append("high")
    if "low" in df.columns:
        cols.append("low")
    out = df[cols].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out = out.sort_values("date").drop_duplicates("date")
    return out if not out.empty else None


def _close_on(code: str, day: date, pp: PriceProvider) -> float | None:
    win = _price_window(code, day, day, pp)
    if win is None:
        return None
    row = win[win["date"] == day]
    if row.empty:
        return None
    return float(row["close"].iloc[-1])


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    """Simple rolling True-Range average (Wilder-ish) for the last ``period`` days."""
    n = len(closes)
    if n < 2:
        return None
    trs: list[float] = []
    for i in range(1, n):
        h, lo, c_prev = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - lo, abs(h - c_prev), abs(lo - c_prev)))
    if len(trs) < period:
        return float(np.mean(trs))
    return float(np.mean(trs[-period:]))


def _proxy_score(close_now: float, close_prev: float) -> float:
    """Lightweight Score-Decay proxy: momentum mapped to 0-100 (design §II.4 L3).

    A pure price-momentum stand-in for the real AROS score (Phase 5). Not a real
    alpha signal — only used to decide whether decay has eroded enough to exit.
    """
    if close_prev <= 0:
        return 50.0
    ret = close_now / close_prev - 1.0
    return float(min(100.0, max(0.0, 50.0 + 50.0 * math.tanh(5.0 * ret))))


# --------------------------------------------------------------------------- #
# Picker (selection axis) + strategy holding horizon
# --------------------------------------------------------------------------- #
def _picker_accepts(p: Portfolio, cand: DailyAlphaCandidate, session: Session) -> bool:
    if p.picker == PICKER_AI:
        return cand.rating in ("S", "A", "B")  # C excluded from sim.
    if p.picker == PICKER_HUMAN:
        dt = (
            session.query(DecisionTracking)
            .filter_by(candidate_id=cand.id)
            .filter(DecisionTracking.human_decision.in_(("买入", "关注")))
            .first()
        )
        return dt is not None
    if p.picker == PICKER_RANDOM:
        # Deterministic benchmark subset (placeholder for S3 random/index pool).
        return cand.code[-1:].isdigit() and int(cand.code[-1]) % 2 == 0
    return False


def _min_strategy_max_holding(session: Session, cand: DailyAlphaCandidate) -> int | None:
    """Tightest (min) strategy-level max-holding horizon among hit strategies."""
    try:
        sids = json.loads(cand.hit_strategies_json) if cand.hit_strategies_json else []
    except (json.JSONDecodeError, TypeError):
        return None
    vals: list[int] = []
    for sid in sids:
        reg = session.get(StrategyRegistry, sid)
        if reg is not None and reg.max_holding_days is not None:
            vals.append(reg.max_holding_days)
    return min(vals) if vals else None


# --------------------------------------------------------------------------- #
# Account state (rebuilt from the blotter — no stored cash/equity)
# --------------------------------------------------------------------------- #
def _all_trades(session: Session, portfolio_id: str) -> list[SimulatedTrade]:
    return session.query(SimulatedTrade).filter_by(portfolio_id=portfolio_id).all()


class AccountState(TypedDict):
    cash: float
    market_value: float
    equity: float
    open_trades: list[SimulatedTrade]


def account_state(session: Session, p: Portfolio, as_of: date, pp: PriceProvider) -> AccountState:
    """Reconstruct cash / market-value / equity from the trade blotter at ``as_of``."""
    trades = _all_trades(session, p.id)
    cash = p.initial_capital
    market_value = 0.0
    open_trades: list[SimulatedTrade] = []
    for t in trades:
        cash -= t.quantity * t.entry_price
        if t.exit_date is not None and t.exit_date <= as_of:
            # Realised (closed on/before as_of): book the exit proceeds.
            if t.exit_price is not None:
                cash += t.quantity * t.exit_price
        else:
            # Still open as of as_of (exit in the future or not yet) -> mark to market.
            open_trades.append(t)
    for t in open_trades:
        px = _close_on(t.code, as_of, pp)
        if px is None:
            px = t.entry_price  # guard: mark at cost if no price (shouldn't happen)
        market_value += t.quantity * px
    return {
        "cash": cash,
        "market_value": market_value,
        "equity": cash + market_value,
        "open_trades": open_trades,
    }


# --------------------------------------------------------------------------- #
# Exit evaluation (single open trade, no look-ahead)
# --------------------------------------------------------------------------- #
def _stop_level(trade: SimulatedTrade, win: pd.DataFrame, cfg: ExitConfig) -> float:
    if cfg.stop_loss.mode == "atr":
        highs = win["high"].to_numpy() if "high" in win.columns else None
        lows = win["low"].to_numpy() if "low" in win.columns else None
        if highs is not None and lows is not None:
            closes = [float(x) for x in win["close"].to_numpy()]
            atr = _atr(
                list(map(float, highs)), list(map(float, lows)), closes, cfg.stop_loss.atr_period
            )
            if atr is not None:
                return trade.entry_price - atr * cfg.stop_loss.atr_multiplier
        # fall through to fixed if ATR unavailable (graceful degradation)
    return trade.entry_price * (1.0 - cfg.stop_loss.fixed_percent / 100.0)


def _holding_limit_days(
    rating: str,
    strategy_mh: int | None,
    portfolio_mh: int | None,
    from_rating: bool,
) -> int | None:
    """min(strategy, rating, portfolio) — smallest cap wins (design §II.4 L4)."""
    caps: list[int] = []
    if from_rating and rating in RATING_CAP_DAYS:
        caps.append(RATING_CAP_DAYS[rating])
    if strategy_mh is not None:
        caps.append(strategy_mh)
    if portfolio_mh is not None:
        caps.append(portfolio_mh)
    return min(caps) if caps else None


def _evaluate_exit(
    trade: SimulatedTrade,
    run_date: date,
    pp: PriceProvider,
    cfg: ExitConfig,
    portfolio_mh: int | None,
    score_provider: ScoreProvider | None = None,
) -> tuple[float, str, str | None] | None:
    """Return (exit_price, exit_reason, score_type) or None. Uses only data <= run_date.

    ``score_provider`` supplies the *real* AROS Score (4.8 Daily Exit
    Intelligence) when ``score_decay.score_source == "real"``; otherwise the
    lightweight proxy stands in (default, no network needed).
    """
    win = _price_window(trade.code, trade.entry_date, run_date, pp)
    if win is None or win.empty:
        return None
    dates = list(win["date"])
    if run_date not in dates:
        return None
    i = dates.index(run_date)
    entry = trade.entry_price
    close_i = float(win["close"].iloc[i])

    # Layer 1 — hard stop loss (most urgent).
    stop = _stop_level(trade, win, cfg)
    if close_i <= stop:
        return (stop, "stop_loss", None)

    # Layer 2a — fixed take-profit (E1).
    if cfg.fixed_tp.enabled:
        tp = entry * (1.0 + cfg.fixed_tp.percent / 100.0)
        if close_i >= tp:
            return (tp, "take_profit", None)

    # Layer 2b — trailing profit protection (E2/E3).
    if cfg.trailing.enabled:
        peak = float(np.max([float(x) for x in win["close"].to_numpy()[: i + 1]]))
        if peak >= entry * (1.0 + cfg.trailing.trigger_profit):
            trail_exit = peak * (1.0 - cfg.trailing.drawdown)
            if close_i <= trail_exit:
                return (trail_exit, "trailing", None)

    # Layer 3 — score decay.
    if cfg.score_decay.enabled:
        w = cfg.score_decay.window
        if cfg.score_decay.score_source == "real" and score_provider is not None:
            # Real AROS Score series: last `w` days, each score <= run_date.
            recent = dates[max(0, i - w + 1) : i + 1]
            real_scores: list[float] = []
            for d in recent:
                sin = score_provider(trade.code, d)
                if sin is not None:
                    real_scores.append(sin.aros_score)
            if len(real_scores) >= w:
                consec = 0
                for s in reversed(real_scores):
                    if s < cfg.score_decay.threshold:
                        consec += 1
                    else:
                        break
                if consec >= w:
                    return (close_i, "score_decay", "real")
        else:
            # Proxy (default): `window`-day momentum mapped to 0-100.
            scores: list[float] = []
            closes = [float(x) for x in win["close"].to_numpy()]
            for j in range(w, i + 1):
                scores.append(_proxy_score(closes[j], closes[max(0, j - w)]))
            consec = 0
            for s in reversed(scores):
                if s < cfg.score_decay.threshold:
                    consec += 1
                else:
                    break
            if consec >= w:
                return (close_i, "score_decay", "proxy")

    # Layer 4 — time stop (min priority).
    limit = _holding_limit_days(
        trade.rating, trade.strategy_max_holding, portfolio_mh, cfg.time_stop.from_rating
    )
    if limit is not None:
        held = _business_days_held(trade.entry_date, run_date)
        if held >= limit:
            return (close_i, "time_stop", None)
    return None


# --------------------------------------------------------------------------- #
# Daily simulation step
# --------------------------------------------------------------------------- #
# Gate for entry_mode == "signal_confirmation": require the Entry Score to reach
# at least EntryConfig.buy_min before auto-entering (design §III.3).
_ENTRY_CONFIRM_MIN = 65.0


def _entry_confirm_score(
    session: Session, cand: DailyAlphaCandidate, run_date: date, pp: PriceProvider
) -> float | None:
    """Entry Score for a candidate via the 4.7 Entry Engine (or None on failure)."""
    from research.entry import EntryEngine, MarketState, resolve_categories

    try:
        hit = json.loads(cand.hit_strategies_json) if cand.hit_strategies_json else []
    except (json.JSONDecodeError, TypeError):
        hit = []
    cats = resolve_categories(session, hit)
    mkt = MarketState(regime=cand.regime_label)
    try:
        sig = EntryEngine().evaluate(
            cand.code,
            run_date,
            pp,
            aros_score=cand.aros_score,
            rating=cand.rating,
            categories=cats,
            market=mkt,
        )
    except Exception:
        return None
    return sig.entry_score


def simulate_day(
    session: Session,
    run_date: date,
    pp: PriceProvider,
    score_provider: ScoreProvider | None = None,
) -> dict[str, object]:
    """Run one trading day for every portfolio: entries (T+1) then exits.

    Returns ``{"date", "entries", "exits"}``. Account state is never stored — it
    is rebuilt on demand by :func:`account_state`.

    ``score_provider`` supplies the *real* AROS Score for the 4.8 Daily Exit
    Intelligence; when wired in, ``score_decay.score_source == "real"`` portfolios
    use it instead of the proxy.
    """
    portfolios = session.query(Portfolio).all()
    prev_bday = _prev_business_day(run_date)
    entries = 0
    exits = 0
    for p in portfolios:
        cfg = ExitConfig.from_json(p.exit_config_json)
        # ---- entries: candidates signalled on prev_bday enter today (T+1) ----
        screenings = session.query(DailyScreening).filter_by(run_date=prev_bday).all()
        open_trades = (
            session.query(SimulatedTrade).filter_by(portfolio_id=p.id, exit_date=None).all()
        )
        open_count = len(open_trades)
        for sc in screenings:
            cands = session.query(DailyAlphaCandidate).filter_by(screening_id=sc.id).all()
            for cand in cands:
                if not _picker_accepts(p, cand, session):
                    continue
                exists = (
                    session.query(SimulatedTrade)
                    .filter_by(portfolio_id=p.id, code=cand.code, signal_date=sc.run_date)
                    .first()
                )
                if exists is not None:
                    continue  # already entered this candidate once
                # Entry-mode gating (4.7 Entry Intelligence).
                entry_score: float | None = None
                if p.entry_mode == "manual":
                    continue  # manual portfolios are filled by a human, never auto
                if p.entry_mode == "signal_confirmation":
                    entry_score = _entry_confirm_score(session, cand, run_date, pp)
                    if entry_score is None or entry_score < _ENTRY_CONFIRM_MIN:
                        continue  # timing not yet confirmed -> wait
                if open_count >= p.max_positions:
                    break
                state = account_state(session, p, run_date, pp)
                entry_px = _close_on(cand.code, run_date, pp)
                if entry_px is None or entry_px <= 0:
                    continue
                cash = state["cash"]
                size_value = p.position_fraction * state["equity"]
                qty = int(size_value / entry_px // 100) * 100
                if qty * entry_px > cash or qty <= 0:
                    qty = int(cash / entry_px // 100) * 100
                if qty <= 0:
                    continue
                trade = SimulatedTrade(
                    id=f"st_{uuid.uuid4().hex[:10]}",
                    portfolio_id=p.id,
                    code=cand.code,
                    name=cand.name,
                    signal_date=sc.run_date,
                    entry_date=run_date,
                    entry_price=entry_px,
                    quantity=float(qty),
                    entry_mode=p.entry_mode,
                    entry_score=entry_score,
                    aros_score=cand.aros_score,
                    rating=cand.rating,
                    hit_strategies_json=cand.hit_strategies_json,
                    strategy_max_holding=_min_strategy_max_holding(session, cand),
                )
                session.add(trade)
                entries += 1
                open_count += 1
        # ---- exits: evaluate every still-open trade ----
        open_trades = (
            session.query(SimulatedTrade).filter_by(portfolio_id=p.id, exit_date=None).all()
        )
        for t in open_trades:
            res = _evaluate_exit(t, run_date, pp, cfg, p.max_holding_days, score_provider)
            if res is None:
                continue
            exit_px, reason, score_type = res
            t.exit_date = run_date
            t.exit_price = exit_px
            t.exit_reason = reason
            t.score_type = score_type
            t.pnl = (exit_px - t.entry_price) * t.quantity
            t.pnl_pct = exit_px / t.entry_price - 1.0
            exits += 1
    session.commit()
    return {"date": run_date.isoformat(), "entries": entries, "exits": exits}


def init_portfolio(
    session: Session,
    *,
    portfolio_id: str,
    axis: str,
    name: str | None = None,
    picker: str = PICKER_AI,
    exit_config: ExitConfig | None = None,
    initial_capital: float = 100000.0,
    max_positions: int = 5,
    position_fraction: float = 0.2,
    entry_mode: str = "immediate",
    max_holding_days: int | None = None,
) -> Portfolio:
    """Create a paper-trading portfolio (one cell of the experiment)."""
    if session.get(Portfolio, portfolio_id) is not None:
        raise ValueError(f"portfolio {portfolio_id!r} already exists")
    p = Portfolio(
        id=portfolio_id,
        name=name or portfolio_id,
        axis=axis,
        initial_capital=initial_capital,
        max_positions=max_positions,
        position_fraction=position_fraction,
        entry_mode=entry_mode,
        exit_config_json=(exit_config or ExitConfig()).to_json(),
        picker=picker,
        max_holding_days=max_holding_days,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# --------------------------------------------------------------------------- #
# Metrics (incl. Alpha indicators)
# --------------------------------------------------------------------------- #
class PortfolioMetrics(TypedDict):
    portfolio_id: str
    n_trades: int
    n_closed: int
    n_open: int
    equity: float
    cumulative_return: float
    max_drawdown: float
    win_rate: float
    profit_loss_ratio: float
    avg_holding_days: float
    annualized_return: float
    sharpe: float
    calmar: float
    max_consecutive_losses: int


def _equity_curve(
    session: Session, p: Portfolio, as_of: date, pp: PriceProvider
) -> list[tuple[date, float]]:
    trades = _all_trades(session, p.id)
    if not trades:
        return []
    first_entry = min(t.entry_date for t in trades)
    if as_of < first_entry:
        return []
    days = [d.date() for d in pd.bdate_range(first_entry, as_of)]
    return [(d, float(account_state(session, p, d, pp)["equity"])) for d in days]


def _max_drawdown(equity: list[float]) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    return float(dd.max()) if dd.size else 0.0


def _sharpe(equity: list[float]) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size < 3:
        return float("nan")
    rets = np.diff(eq) / eq[:-1]
    std = float(np.std(rets, ddof=1))
    if std == 0:
        return float("nan")
    return float(np.mean(rets) / std * math.sqrt(252.0))


def _max_consecutive_losses(closed: list[SimulatedTrade]) -> int:
    ordered = sorted(closed, key=lambda t: t.exit_date or date.min)
    best = cur = 0
    for t in ordered:
        if t.pnl is not None and t.pnl < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def portfolio_metrics(
    session: Session, p: Portfolio, as_of: date, pp: PriceProvider
) -> PortfolioMetrics:
    """Full metric set for one portfolio, including the Alpha indicators."""
    trades = _all_trades(session, p.id)
    closed = [t for t in trades if t.exit_date is not None]
    open_trades = [t for t in trades if t.exit_date is None]
    n_closed = len(closed)
    wins = [t for t in closed if t.pnl is not None and t.pnl > 0]
    losses = [t for t in closed if t.pnl is not None and t.pnl < 0]
    win_rate = (len(wins) / n_closed) if n_closed else float("nan")
    avg_win = float(np.mean([t.pnl for t in wins])) if wins else float("nan")
    avg_loss = float(np.mean([t.pnl for t in losses])) if losses else float("nan")
    pl_ratio = (
        (avg_win / abs(avg_loss))
        if (losses and not math.isnan(avg_loss) and avg_loss != 0)
        else float("nan")
    )
    if closed:
        helds = [
            _business_days_held(t.entry_date, t.exit_date)
            for t in closed
            if t.exit_date is not None
        ]
        avg_holding = float(np.mean(helds)) if helds else float("nan")
    else:
        avg_holding = float("nan")

    curve = _equity_curve(session, p, as_of, pp)
    equity = float(curve[-1][1]) if curve else p.initial_capital
    cum_ret = equity / p.initial_capital - 1.0
    max_dd = _max_drawdown([e for _, e in curve]) if curve else 0.0
    if curve and len(curve) > 1:
        n_days = len(curve) - 1
        ann = (equity / p.initial_capital) ** (252.0 / n_days) - 1.0
    else:
        ann = float("nan")
    sharpe = _sharpe([e for _, e in curve]) if len(curve) > 2 else float("nan")
    calmar = (ann / abs(max_dd)) if (max_dd > 0 and not math.isnan(ann)) else float("nan")
    return PortfolioMetrics(
        portfolio_id=p.id,
        n_trades=len(trades),
        n_closed=n_closed,
        n_open=len(open_trades),
        equity=equity,
        cumulative_return=cum_ret,
        max_drawdown=max_dd,
        win_rate=win_rate,
        profit_loss_ratio=pl_ratio,
        avg_holding_days=avg_holding,
        annualized_return=ann,
        sharpe=sharpe,
        calmar=calmar,
        max_consecutive_losses=_max_consecutive_losses(closed),
    )


# --------------------------------------------------------------------------- #
# Report (md + html + xlsx, with baseline comparison)
# --------------------------------------------------------------------------- #
def _benchmark_return(
    session: Session,
    portfolios: list[Portfolio],
    as_of: date,
    bench_pp: PriceProvider,
    bench_code: str,
) -> float | None:
    first: date | None = None
    for p in portfolios:
        for t in _all_trades(session, p.id):
            if first is None or t.entry_date < first:
                first = t.entry_date
    if first is None:
        return None
    win = _price_window(bench_code, first, as_of, bench_pp)
    if win is None or win.empty:
        return None
    closes = [float(x) for x in win["close"].to_numpy()]
    if len(closes) < 2:
        return None
    return closes[-1] / closes[0] - 1.0


def _fmt(v: float) -> str:
    if isinstance(v, float) and math.isnan(v):
        return "n/a"
    return f"{v:+.2%}"


def _render_markdown(
    portfolios: list[Portfolio],
    metrics: list[PortfolioMetrics],
    as_of: date,
    bench_ret: float | None,
) -> str:
    lines: list[str] = []
    lines.append(f"# AROS Paper Trading Report — {as_of.isoformat()}")
    lines.append("")
    if bench_ret is not None:
        lines.append(f"- 基准（买入持有）收益: {_fmt(bench_ret)}")
    lines.append("")
    for p, m in zip(portfolios, metrics, strict=False):
        lines.append(f"## 组合 {p.id}（{p.axis} / picker={p.picker}）")
        lines.append("")
        note = "（样本不足，n_closed<5）" if m["n_closed"] < MIN_SAMPLE_FOR_REPORT else ""
        lines.append(f"- 交易数: {m['n_trades']}（已平 {m['n_closed']}，持仓 {m['n_open']}）{note}")
        lines.append(f"- 当前净值: {m['equity']:,.2f} · 累计收益: {_fmt(m['cumulative_return'])}")
        pl = f"{m['profit_loss_ratio']:.2f}" if not math.isnan(m["profit_loss_ratio"]) else "n/a"
        lines.append(
            f"- 最大回撤: {_fmt(m['max_drawdown'])} · 胜率: {_fmt(m['win_rate'])} · 盈亏比: {pl}"
        )
        lines.append(f"- 平均持仓: {m['avg_holding_days']:.1f} 交易日")
        lines.append(
            f"- 年化收益: {_fmt(m['annualized_return'])} · Sharpe: {m['sharpe']:.2f} · "
            f"Calmar: {m['calmar']:.2f} · 最大连亏: {m['max_consecutive_losses']}"
            if not math.isnan(m["sharpe"])
            else f"- 年化收益: {_fmt(m['annualized_return'])} · Sharpe: n/a · "
            f"Calmar: n/a · 最大连亏: {m['max_consecutive_losses']}"
        )
        lines.append("")
    return "\n".join(lines)


def _render_html(md: str) -> str:
    body: list[str] = []
    for raw in md.splitlines():
        line = raw
        if line.startswith("# "):
            body.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("- "):
            body.append(f"<li>{line[2:]}</li>")
        else:
            body.append(f"<p>{line}</p>")
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;"
        "padding:0 1rem;color:#1a1a1a}h1{color:#b91c1c}h2{color:#7f1d1d;margin-top:1.6rem}"
        "li{margin:.2rem 0}</style></head><body>" + "".join(body) + "</body></html>"
    )


def _render_xlsx(
    portfolios: list[Portfolio],
    metrics: list[PortfolioMetrics],
    path: str,
    bench_ret: float | None,
) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Paper Trading"
    ws.append(["AROS Paper Trading Report"])
    if bench_ret is not None:
        ws.append(["Benchmark (buy&hold)", bench_ret])
    ws.append([])
    ws.append(
        [
            "组合",
            "轴",
            "交易数",
            "已平",
            "持仓",
            "净值",
            "累计收益",
            "最大回撤",
            "胜率",
            "盈亏比",
            "平均持仓",
            "年化",
            "Sharpe",
            "Calmar",
            "最大连亏",
        ]
    )
    for p, m in zip(portfolios, metrics, strict=False):
        ws.append(
            [
                p.id,
                p.axis,
                m["n_trades"],
                m["n_closed"],
                m["n_open"],
                m["equity"],
                m["cumulative_return"],
                m["max_drawdown"],
                m["win_rate"],
                m["profit_loss_ratio"],
                m["avg_holding_days"],
                m["annualized_return"],
                m["sharpe"],
                m["calmar"],
                m["max_consecutive_losses"],
            ]
        )
    wb.save(path)


def generate_papertrade_report(
    session: Session,
    out_dir: str = "reports",
    as_of: date | None = None,
    *,
    price_provider: PriceProvider | None = None,
    bench_price_provider: PriceProvider | None = None,
    bench_code: str | None = None,
    portfolio_ids: list[str] | None = None,
) -> dict[str, str]:
    """Render the Portfolio Performance Report (md + html + xlsx).

    Output lands in ``<out_dir>/papertrade/<as_of>/``. Equity / Alpha metrics need
    ``price_provider``; if it is ``None`` only basic trade counts are reported.
    """
    as_of = as_of or date.today()
    q = session.query(Portfolio)
    if portfolio_ids:
        q = q.filter(Portfolio.id.in_(portfolio_ids))
    portfolios = q.all()
    metrics: list[PortfolioMetrics] = []
    for p in portfolios:
        if price_provider is not None:
            metrics.append(portfolio_metrics(session, p, as_of, price_provider))
        else:
            trades = _all_trades(session, p.id)
            closed = [t for t in trades if t.exit_date is not None]
            metrics.append(
                PortfolioMetrics(
                    portfolio_id=p.id,
                    n_trades=len(trades),
                    n_closed=len(closed),
                    n_open=len(trades) - len(closed),
                    equity=p.initial_capital,
                    cumulative_return=float("nan"),
                    max_drawdown=float("nan"),
                    win_rate=float("nan"),
                    profit_loss_ratio=float("nan"),
                    avg_holding_days=float("nan"),
                    annualized_return=float("nan"),
                    sharpe=float("nan"),
                    calmar=float("nan"),
                    max_consecutive_losses=0,
                )
            )
    bench_ret: float | None = None
    if bench_price_provider is not None and bench_code is not None:
        bench_ret = _benchmark_return(session, portfolios, as_of, bench_price_provider, bench_code)
    folder = os.path.join(out_dir, "papertrade", as_of.isoformat())
    os.makedirs(folder, exist_ok=True)
    md_path = os.path.join(folder, "papertrade_report.md")
    html_path = os.path.join(folder, "papertrade_report.html")
    xlsx_path = os.path.join(folder, "papertrade_report.xlsx")
    md = _render_markdown(portfolios, metrics, as_of, bench_ret)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(md))
    _render_xlsx(portfolios, metrics, xlsx_path, bench_ret)
    return {"md": md_path, "html": html_path, "xlsx": xlsx_path}
