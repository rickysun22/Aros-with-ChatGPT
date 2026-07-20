"""Tests for the Sprint 4.7 Paper Trading engine (research.papertrade).

All scenarios are offline: a fake ``PriceProvider`` returns deterministic
business-day prices, and the session is an in-memory sqlite DB. Each exit layer
(fixed stop / fixed take-profit / trailing / score-decay proxy / time stop) and
the Alpha metrics are checked against hand-computed small examples.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from research.feedback import PriceProvider
from research.models import DailyAlphaCandidate, DailyScreening, Portfolio, SimulatedTrade
from research.papertrade import (
    AccountState,
    ExitConfig,
    _holding_limit_days,
    _max_consecutive_losses,
    _max_drawdown,
    _proxy_score,
    _sharpe,
    _stop_level,
    account_state,
    exit_preset,
    generate_papertrade_report,
    init_portfolio,
    portfolio_metrics,
    simulate_day,
)

# A fixed window of consecutive business days for all scenarios.
DAYS = [d.date() for d in pd.bdate_range(date(2026, 1, 5), date(2026, 1, 30))]


def _mem_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _make_provider(
    schedule: dict[str, list[tuple[date, float]]], with_ohl: bool = False
) -> PriceProvider:
    def _p(code: str, start: date, end: date) -> pd.DataFrame | None:
        rows = schedule.get(code)
        if rows is None:
            return None
        df = pd.DataFrame(rows, columns=["date", "close"])
        if with_ohl:
            df["high"] = df["close"] * 1.02
            df["low"] = df["close"] * 0.98
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df if not df.empty else None

    return _p


def _seed(
    session,
    code: str,
    rating: str,
    sig: date,
    closes: list[float],
    with_ohl: bool = False,
    hit: list[str] | None = None,
) -> PriceProvider:
    scr = DailyScreening(id=f"scr_{code}", run_date=sig, universe="csi800", regime_label="Bull")
    session.add(scr)
    cand = DailyAlphaCandidate(
        id=f"cand_{code}",
        screening_id=scr.id,
        code=code,
        name=f"N{code}",
        regime_label="Bull",
        hit_count=len(hit or []),
        hit_strategies_json=json.dumps(hit or []),
        consensus_score=90.0,
        aros_score=90.0,
        rating=rating,
    )
    session.add(cand)
    session.commit()
    return _make_provider({code: list(zip(DAYS, closes, strict=False))}, with_ohl=with_ohl)


def _seed_multi(session, sig: date, closes: list[float]) -> PriceProvider:
    scr = DailyScreening(id="scr_multi", run_date=sig, universe="csi800", regime_label="Bull")
    session.add(scr)
    schedule: dict[str, list[tuple[date, float]]] = {}
    for code, rating in (
        ("000001", "S"),
        ("000002", "A"),
        ("000003", "B"),
        ("000004", "C"),
    ):
        cand = DailyAlphaCandidate(
            id=f"cand_{code}",
            screening_id=scr.id,
            code=code,
            name=f"N{code}",
            regime_label="Bull",
            hit_count=0,
            hit_strategies_json="[]",
            consensus_score=90.0,
            aros_score=90.0,
            rating=rating,
        )
        session.add(cand)
        schedule[code] = list(zip(DAYS, closes, strict=False))
    session.commit()
    return _make_provider(schedule)


def _run(session, provider: PriceProvider) -> None:
    for d in DAYS:
        simulate_day(session, d, provider)


# --------------------------------------------------------------------------- #
# Config + init
# --------------------------------------------------------------------------- #
def test_exit_config_json_roundtrip() -> None:
    cfg = exit_preset("E3")
    assert cfg.trailing.enabled and cfg.score_decay.enabled
    cfg2 = ExitConfig.from_json(cfg.to_json())
    assert cfg2.trailing.trigger_profit == cfg.trailing.trigger_profit
    assert cfg2.score_decay.threshold == cfg.score_decay.threshold
    assert cfg2.stop_loss.mode == "fixed"


def test_init_portfolio_creates_row() -> None:
    session = _mem_session()
    p = init_portfolio(
        session,
        portfolio_id="S1_E1",
        axis="exit",
        picker="ai",
        exit_config=exit_preset("E1"),
    )
    assert p.id == "S1_E1"
    got = session.get(Portfolio, "S1_E1")
    assert got is not None
    assert ExitConfig.from_json(got.exit_config_json).fixed_tp.enabled
    with pytest.raises(ValueError):
        init_portfolio(session, portfolio_id="S1_E1", axis="exit")


# --------------------------------------------------------------------------- #
# Entry: rating filter (C excluded) + data isolation
# --------------------------------------------------------------------------- #
def test_entry_excludes_rating_c() -> None:
    session = _mem_session()
    provider = _seed_multi(session, DAYS[0], [100.0] * len(DAYS))
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    trades = session.query(SimulatedTrade).all()
    assert all(t.rating != "C" for t in trades)
    assert {t.rating for t in trades} == {"S", "A", "B"}


def test_data_isolation_between_portfolios() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 120.0, 110.0] + [110.0] * (len(DAYS) - 4)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    init_portfolio(session, portfolio_id="S1_E2", axis="exit", exit_config=exit_preset("E2"))
    _run(session, provider)
    e1 = session.query(SimulatedTrade).filter_by(portfolio_id="S1_E1").first()
    e2 = session.query(SimulatedTrade).filter_by(portfolio_id="S1_E2").first()
    assert e1.exit_reason == "take_profit"
    assert e2.exit_reason == "trailing"
    assert e1.id != e2.id
    assert {t.portfolio_id for t in session.query(SimulatedTrade).all()} == {
        "S1_E1",
        "S1_E2",
    }


# --------------------------------------------------------------------------- #
# Exit layer 1 — hard stop loss (fixed)
# --------------------------------------------------------------------------- #
def test_fixed_stop_loss_exit() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 90.0] + [90.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(92.0)  # 100 * (1 - 0.08)
    assert t.pnl == pytest.approx((92.0 - 100.0) * t.quantity)


# --------------------------------------------------------------------------- #
# Exit layer 2a — fixed take-profit (E1)
# --------------------------------------------------------------------------- #
def test_fixed_take_profit_exit() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 121.0] + [121.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "take_profit"
    assert t.exit_price == pytest.approx(120.0)


# --------------------------------------------------------------------------- #
# Exit layer 2b — trailing profit (E2)
# --------------------------------------------------------------------------- #
def test_trailing_exit() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 120.0, 110.0] + [110.0] * (len(DAYS) - 4)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E2", axis="exit", exit_config=exit_preset("E2"))
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "trailing"
    assert t.exit_price == pytest.approx(110.4)  # 120 * (1 - 0.08)


# --------------------------------------------------------------------------- #
# Exit layer 3 — score decay (proxy). Disable stop/tp/trailing to isolate.
# --------------------------------------------------------------------------- #
def test_score_decay_proxy_exit() -> None:
    session = _mem_session()
    cfg = ExitConfig()
    cfg.stop_loss.fixed_percent = 50.0  # never triggers in this window
    cfg.trailing.enabled = False
    cfg.fixed_tp.enabled = False
    cfg.score_decay.enabled = True
    cfg.score_decay.window = 5
    cfg.score_decay.threshold = 70.0
    closes = [100.0 * (0.98**i) for i in range(len(DAYS))]
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E3", axis="exit", exit_config=cfg)
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "score_decay"
    assert t.score_type == "proxy"
    assert t.exit_date is not None


# --------------------------------------------------------------------------- #
# Exit layer 4 — time stop (min priority), portfolio cap
# --------------------------------------------------------------------------- #
def test_time_stop_exit() -> None:
    session = _mem_session()
    cfg = exit_preset("E1")
    cfg.fixed_tp.enabled = False  # keep flat price from triggering tp
    closes = [100.0] * len(DAYS)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(
        session,
        portfolio_id="S1_T",
        axis="exit",
        exit_config=cfg,
        max_holding_days=3,
    )
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "time_stop"
    assert t.exit_price == pytest.approx(100.0)
    assert t.exit_date == DAYS[4]  # held 3 trading days from entry (DAYS[1])


# --------------------------------------------------------------------------- #
# ATR stop: falls back to fixed when high/low absent; uses ATR when present
# --------------------------------------------------------------------------- #
def test_atr_fallback_to_fixed_without_ohl() -> None:
    session = _mem_session()
    cfg = ExitConfig()
    cfg.stop_loss.mode = "atr"
    cfg.stop_loss.fixed_percent = 8.0
    closes = [100.0, 100.0, 90.0] + [90.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes, with_ohl=False)
    init_portfolio(session, portfolio_id="S1_ATR", axis="exit", exit_config=cfg)
    _run(session, provider)
    t = session.query(SimulatedTrade).first()
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(92.0)  # fixed fallback, NOT atr


def test_stop_level_fixed_and_atr() -> None:
    trade = SimulatedTrade(
        id="t",
        portfolio_id="x",
        code="000001",
        signal_date=DAYS[0],
        entry_date=DAYS[1],
        entry_price=100.0,
        quantity=100.0,
        aros_score=90.0,
        rating="S",
    )
    win = pd.DataFrame(
        {
            "date": [DAYS[1], DAYS[2]],
            "close": [100.0, 95.0],
            "high": [102.0, 96.0],
            "low": [98.0, 94.0],
        }
    )
    cfg_f = ExitConfig()  # default fixed 8%
    assert _stop_level(trade, win, cfg_f) == pytest.approx(92.0)
    cfg_a = ExitConfig()
    cfg_a.stop_loss.mode = "atr"
    cfg_a.stop_loss.atr_period = 2
    cfg_a.stop_loss.atr_multiplier = 2
    # TR on day2 = max(96-94, |96-100|, |94-100|) = 6; ATR = 6; stop = 100 - 2*6 = 88
    assert _stop_level(trade, win, cfg_a) == pytest.approx(88.0)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_proxy_score_bounds() -> None:
    assert _proxy_score(100.0, 100.0) == pytest.approx(50.0)
    assert _proxy_score(200.0, 100.0) == pytest.approx(100.0, abs=1.0)
    assert _proxy_score(50.0, 100.0) == pytest.approx(0.0, abs=1.0)


def test_holding_limit_min_priority() -> None:
    # Strategy (5) is the tightest -> highest priority wins.
    assert _holding_limit_days("S", 5, 30, True) == 5
    # Rating excluded -> portfolio cap only.
    assert _holding_limit_days("S", None, 30, False) == 30
    # Only rating cap available.
    assert _holding_limit_days("B", None, None, True) == 15


def test_max_drawdown() -> None:
    assert _max_drawdown([100.0, 120.0, 90.0, 110.0]) == pytest.approx(0.25)
    assert _max_drawdown([]) == 0.0


def test_sharpe_flat_is_nan_and_rising_positive() -> None:
    assert math.isnan(_sharpe([100.0, 100.0, 100.0]))
    assert _sharpe([100.0, 101.0, 102.0, 103.0]) > 0


def test_max_consecutive_losses() -> None:
    trades = [
        SimulatedTrade(
            id=f"t{i}",
            portfolio_id="x",
            code="000001",
            signal_date=DAYS[0],
            entry_date=DAYS[1],
            entry_price=100.0,
            quantity=100.0,
            aros_score=90.0,
            rating="S",
            pnl=pnl,
            exit_date=DAYS[2],
        )
        for i, pnl in enumerate([-1.0, -2.0, 3.0, -4.0, -5.0])
    ]
    assert _max_consecutive_losses(trades) == 2


# --------------------------------------------------------------------------- #
# Account state rebuild + Alpha metrics (hand-checked small example)
# --------------------------------------------------------------------------- #
def test_account_state_rebuilds_equity() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 120.0] + [120.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    p = session.get(Portfolio, "S1_E1")
    st: AccountState = account_state(session, p, DAYS[-1], provider)
    # Entry 200 sh @100, exit @120 -> cash +4000 vs 100000 start.
    assert st["equity"] == pytest.approx(104000.0)


def test_portfolio_metrics_alpha() -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 120.0] + [120.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    p = session.get(Portfolio, "S1_E1")
    m = portfolio_metrics(session, p, DAYS[-1], provider)
    assert m["n_closed"] == 1
    assert m["n_open"] == 0
    assert m["win_rate"] == pytest.approx(1.0)
    assert m["cumulative_return"] == pytest.approx(0.04)
    assert m["equity"] == pytest.approx(104000.0)
    assert m["max_consecutive_losses"] == 0
    assert m["max_drawdown"] >= 0.0
    # Annualized/sharpe are finite numbers (trend up then flat).
    assert not math.isnan(m["annualized_return"])
    assert not math.isnan(m["sharpe"])


# --------------------------------------------------------------------------- #
# Report generation
# --------------------------------------------------------------------------- #
def test_generate_report_files(tmp_path) -> None:
    session = _mem_session()
    closes = [100.0, 100.0, 120.0] + [120.0] * (len(DAYS) - 3)
    provider = _seed(session, "000001", "S", DAYS[0], closes)
    init_portfolio(session, portfolio_id="S1_E1", axis="exit", exit_config=exit_preset("E1"))
    _run(session, provider)
    paths = generate_papertrade_report(
        session, out_dir=str(tmp_path), as_of=DAYS[-1], price_provider=provider
    )
    for k in ("md", "html", "xlsx"):
        assert os.path.exists(paths[k])
    md = open(paths["md"], encoding="utf-8").read()
    assert "S1_E1" in md
