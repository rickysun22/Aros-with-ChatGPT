"""Tests for the Sprint 1.9 watchlist tracker.

We inject a fake strategy engine (raw_* -> score_<name>) and a fake data
manager serving per-code OHLC frames, plus an isolated temp SQLite database, so
the tests exercise the real membership / snapshot / delta code without
indicators, factors, network, or the project's main database.
"""

from __future__ import annotations

import json
import os
import tempfile

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import RankingConfig, WatchlistConfig, get_config
from core.database import Base
from ranking.engine import RankingEngine
from watchlist.engine import WatchlistEngine, _classify
from watchlist.models import BacktestPoint, RankingPoint, WatchlistItem


class FakeSE:
    """Minimal stand-in for StrategyEngine: emits score_a / score_b."""

    names = ["a", "b"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["score_a"] = df["raw_a"]
        df["score_b"] = df["raw_b"]
        return df


class FakeDM:
    """Minimal stand-in for DataManager: serves per-code OHLC frames."""

    config = None

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def get_daily(self, code, start=None, end=None):  # noqa: ANN001
        df = self.frames.get(code)
        if df is None:
            return pd.DataFrame()
        out = df
        if end is not None:
            out = out[pd.to_datetime(out["date"]) <= pd.Timestamp(end)]
        return out.reset_index(drop=True)


def make_frames(spec: dict[str, tuple[str, float]]) -> dict[str, pd.DataFrame]:
    """spec: code -> (date, raw) with raw_a == raw_b == raw."""
    out = {}
    for code, (dt, raw) in spec.items():
        out[code] = pd.DataFrame(
            {
                "date": [dt],
                "close": [raw * 10.0],
                "raw_a": [raw],
                "raw_b": [raw],
            }
        )
    return out


def make_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    eng = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(eng)
    sm = sessionmaker(bind=eng, future=True)
    return sm(), eng, path


def cleanup(s, eng, path):
    s.close()
    try:
        eng.dispose()
    except Exception:
        pass
    try:
        os.remove(path)
    except Exception:
        pass


def make_engine(
    session,
    wl=None,
    bt_fn=None,
    bt_config=None,
    ind=None,
    fac=None,
    st=None,
):
    re = RankingEngine(FakeSE(), RankingConfig())
    return WatchlistEngine(
        re,
        wl or WatchlistConfig(),
        session=session,
        backtest_fn=bt_fn,
        backtest_config=bt_config,
        indicators=ind,
        factors=fac,
        strategies=st,
    )


# --------------------------------------------------------------------------- #
# Membership
# --------------------------------------------------------------------------- #
def test_add_list_remove_is_member():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        e.add("A")
        e.add("B")
        e.add("C")
        assert e.list_active() == ["A", "B", "C"]
        assert e.is_member("A") is True
        e.remove("B")
        assert e.list_active() == ["A", "C"]
        assert e.is_member("B") is False
        e.add("B", note="back")
        assert e.list_active() == ["A", "B", "C"]
        item = s.get(WatchlistItem, "B")
        assert item.note == "back"
        assert item.removed_at is None
    finally:
        cleanup(s, eng, path)


def test_remove_unknown_returns_none():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        assert e.remove("Z") is None
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# Snapshot (full cross-sectional rank, including no-data codes)
# --------------------------------------------------------------------------- #
def test_snapshot_records_full_rank_and_no_data():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        for c in ["A", "B", "C"]:
            e.add(c)
        e.add("D")
        frames = make_frames(
            {
                "A": ("2024-01-02", 0.9),
                "B": ("2024-01-02", 0.5),
                "C": ("2024-01-02", 0.1),
            }
        )
        dm = FakeDM(frames)
        e.snapshot(data_manager=dm, as_of="2024-01-02")
        pts = {p.code: p for p in s.query(RankingPoint).all()}
        assert pts["A"].rank == 1
        assert pts["B"].rank == 2
        assert pts["C"].rank == 3
        assert "D" not in pts
        assert pts["A"].composite_score == 0.9
        assert pts["A"].scores_json == {"a": 0.9, "b": 0.9}
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# Deltas: state machine
# --------------------------------------------------------------------------- #
def test_deltas_all_new_on_first_snapshot():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        for c in ["A", "B", "C"]:
            e.add(c)
        dm = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-01", 0.9),
                    "B": ("2024-01-01", 0.5),
                    "C": ("2024-01-01", 0.1),
                }
            )
        )
        digest = e.snapshot(data_manager=dm, as_of="2024-01-01")
        assert digest.summary["new"] == 3
        assert all(m.status == "new" for m in digest.members)
    finally:
        cleanup(s, eng, path)


def test_deltas_up_down_steady():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        for c in ["A", "B", "C"]:
            e.add(c)
        dm1 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-01", 0.9),
                    "B": ("2024-01-01", 0.5),
                    "C": ("2024-01-01", 0.1),
                }
            )
        )
        e.snapshot(data_manager=dm1, as_of="2024-01-01")
        dm2 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-02", 0.2),
                    "B": ("2024-01-02", 0.8),
                    "C": ("2024-01-02", 0.2),
                }
            )
        )
        digest = e.snapshot(data_manager=dm2, as_of="2024-01-02")
        by = {m.code: m for m in digest.members}
        assert by["A"].status == "down" and by["A"].rank_change == -1
        assert by["B"].status == "up" and by["B"].rank_change == 1
        assert by["C"].status == "steady" and by["C"].rank_change == 0
        assert digest.summary["up"] == 1
        assert digest.summary["down"] == 1
        assert digest.summary["steady"] == 1
    finally:
        cleanup(s, eng, path)


def test_deltas_dropped_when_data_gone():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        for c in ["A", "B", "C"]:
            e.add(c)
        dm1 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-01", 0.9),
                    "B": ("2024-01-01", 0.5),
                    "C": ("2024-01-01", 0.1),
                }
            )
        )
        e.snapshot(data_manager=dm1, as_of="2024-01-01")
        dm2 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-02", 0.9),
                    "B": ("2024-01-02", 0.5),
                }
            )
        )
        digest = e.snapshot(data_manager=dm2, as_of="2024-01-02")
        by = {m.code: m for m in digest.members}
        assert by["C"].status == "dropped"
        assert by["C"].rank is None
    finally:
        cleanup(s, eng, path)


def test_classify_state_machine_direct():
    def p(rank, score):
        return RankingPoint(as_of="2024-01-02", code="X", rank=rank, composite_score=score)

    assert _classify(p(1, 0.5), None)[0] == "new"
    assert _classify(None, p(1, 0.5))[0] == "dropped"
    assert _classify(p(None, None), p(1, 0.5))[0] == "no_data"
    assert _classify(p(1, 0.9), p(3, 0.1))[0] == "up"
    assert _classify(p(3, 0.1), p(1, 0.9))[0] == "down"
    assert _classify(p(2, 0.5), p(2, 0.5))[0] == "steady"
    _, rc, _ = _classify(p(2, 0.5), p(5, 0.1))
    assert rc == 3


# --------------------------------------------------------------------------- #
# Backtest persistence (Sprint 1.11)
# --------------------------------------------------------------------------- #
def test_snapshot_backtest_disabled_by_default():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        e.add("A")
        dm = FakeDM(make_frames({"A": ("2024-01-02", 0.9)}))
        called = []
        e._backtest_fn = lambda c, d, st, en: (called.append(en) or {"total_return": 0.1})
        e.snapshot(data_manager=dm, as_of="2024-01-02")
        # Backtest must NOT run when disabled, and nothing gets persisted.
        assert called == []
        assert s.query(BacktestPoint).count() == 0
    finally:
        cleanup(s, eng, path)


def test_snapshot_backtest_stores_points():
    s, eng, path = make_session()
    try:
        captured = {}

        def fn(code, dm, start, end):
            captured[code] = end
            return {
                "total_return": 0.12,
                "max_drawdown": -0.07,
                "sharpe": 1.5,
                "benchmark_return": 0.04,
            }

        e = make_engine(s, WatchlistConfig(include_backtest=True), bt_fn=fn)
        e.add("A")
        e.add("B")
        dm = FakeDM(make_frames({"A": ("2024-01-02", 0.9), "B": ("2024-01-02", 0.5)}))
        e.snapshot(data_manager=dm, as_of="2024-01-02")
        pts = {p.code: p for p in s.query(BacktestPoint).all()}
        assert set(pts) == {"A", "B"}
        assert abs(float(pts["A"].total_return) - 0.12) < 1e-9
        assert abs(float(pts["A"].sharpe) - 1.5) < 1e-9
        assert abs(float(pts["A"].benchmark_return) - 0.04) < 1e-9
        # The backtest window end equals the ranking cross-section (no look-ahead).
        assert str(captured["A"]) == "2024-01-02"
    finally:
        cleanup(s, eng, path)


def test_snapshot_backtest_no_lookahead():
    s, eng, path = make_session()
    try:
        captured = {}

        def fn(code, dm, start, end):
            captured[code] = end
            return {
                "total_return": 0.1,
                "max_drawdown": -0.1,
                "sharpe": 1.0,
                "benchmark_return": 0.02,
            }

        e = make_engine(s, WatchlistConfig(include_backtest=True), bt_fn=fn)
        e.add("A")
        frames = {
            "A": pd.DataFrame(
                {
                    "date": ["2024-01-01", "2024-01-02"],
                    "close": [9.0, 1.0],
                    "raw_a": [0.9, 0.1],
                    "raw_b": [0.9, 0.1],
                }
            )
        }
        e.snapshot(data_manager=FakeDM(frames), as_of="2024-01-01")
        # Even though the underlying data extends to 2024-01-02, the backtest
        # window must stop at the as_of cross-section.
        assert str(captured["A"]) == "2024-01-01"
    finally:
        cleanup(s, eng, path)


def test_digest_backtest_ring_comparison():
    s, eng, path = make_session()
    try:
        bt_state = {"A": 0.10}

        def fn(code, dm, start, end):
            return {
                "total_return": bt_state.get(code, 0.0),
                "max_drawdown": -0.05,
                "sharpe": 1.2,
                "benchmark_return": 0.03,
            }

        e = make_engine(s, WatchlistConfig(include_backtest=True), bt_fn=fn)
        e.add("A")
        e.snapshot(data_manager=FakeDM(make_frames({"A": ("2024-01-01", 0.9)})), as_of="2024-01-01")
        bt_state["A"] = 0.25  # performance improved in the second snapshot
        digest = e.snapshot(
            data_manager=FakeDM(make_frames({"A": ("2024-01-02", 0.4)})), as_of="2024-01-02"
        )
        md = digest.to_markdown()
        assert "回测表现" in md
        assert digest.backtest_included is True
        by = {m.code: m for m in digest.members}
        assert by["A"].backtest.total_return == 0.25
        assert by["A"].prev_backtest.total_return == 0.10
        # Ring delta (0.25 - 0.10) rendered as +15.00%.
        assert "+15.00" in md
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def test_history_ordered_desc():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        e.add("A")
        dm1 = FakeDM(make_frames({"A": ("2024-01-01", 0.9)}))
        e.snapshot(data_manager=dm1, as_of="2024-01-01")
        dm2 = FakeDM(make_frames({"A": ("2024-01-02", 0.4)}))
        e.snapshot(data_manager=dm2, as_of="2024-01-02")
        hist = e.history("A")
        assert len(hist) == 2
        assert str(hist[0].as_of) == "2024-01-02"
        assert str(hist[1].as_of) == "2024-01-01"
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# No look-ahead: snapshot at as_of uses only bars <= as_of
# --------------------------------------------------------------------------- #
def test_snapshot_as_of_no_lookahead():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        e.add("A")
        frames = {
            "A": pd.DataFrame(
                {
                    "date": ["2024-01-01", "2024-01-02"],
                    "close": [9.0, 1.0],
                    "raw_a": [0.9, 0.1],
                    "raw_b": [0.9, 0.1],
                }
            )
        }
        dm = FakeDM(frames)
        e.snapshot(data_manager=dm, as_of="2024-01-01")
        pt = s.query(RankingPoint).filter(RankingPoint.code == "A").one()
        assert abs(pt.composite_score - 0.9) < 1e-9
        assert str(pt.as_of) == "2024-01-01"
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_digest_markdown_and_json():
    s, eng, path = make_session()
    try:
        e = make_engine(s)
        for c in ["A", "B", "C"]:
            e.add(c)
        dm1 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-01", 0.9),
                    "B": ("2024-01-01", 0.5),
                    "C": ("2024-01-01", 0.1),
                }
            )
        )
        e.snapshot(data_manager=dm1, as_of="2024-01-01")
        dm2 = FakeDM(
            make_frames(
                {
                    "A": ("2024-01-02", 0.2),
                    "B": ("2024-01-02", 0.8),
                    "C": ("2024-01-02", 0.2),
                }
            )
        )
        digest = e.snapshot(data_manager=dm2, as_of="2024-01-02")
        md = digest.to_markdown(alert_rank_jump=5)
        assert "AROS 自选股追踪日报" in md
        assert "上升" in md and "下降" in md
        payload = json.loads(digest.to_json())
        assert payload["summary"]["up"] == 1
        assert payload["members"][0]["code"] == "B"
    finally:
        cleanup(s, eng, path)


# --------------------------------------------------------------------------- #
# Real config wiring
# --------------------------------------------------------------------------- #
def test_real_config_wiring():
    cfg = get_config()
    re = RankingEngine.from_config(cfg.indicators, cfg.factors, cfg.strategies, cfg.ranking)
    e = WatchlistEngine(re, cfg.watchlist)
    assert e.config is cfg.watchlist
    assert e.list_active() == []


# --------------------------------------------------------------------------- #
# CLI smoke
# --------------------------------------------------------------------------- #
def test_cli_watchlist_list():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    result = runner.invoke(main.app, ["watchlist", "list"])
    assert result.exit_code == 0, result.output
    assert "Watchlist" in result.output
