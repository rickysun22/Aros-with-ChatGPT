"""Tests for the Sprint 1.8 daily report engine.

The report layer sits on top of RankingEngine (which itself wraps
StrategyEngine). We inject a fake strategy engine (raw_* -> score_<name>) and a
fake data manager serving per-code OHLC frames, keeping the tests free of
indicators / factors / network while exercising the real ranking + snapshot
code paths.
"""

from __future__ import annotations

import json

import pandas as pd

from core.config import RankingConfig, ReportConfig, get_config
from ranking.engine import RankingEngine
from report.engine import DailyReport, ReportEngine, ReportRow


class FakeSE:
    """Minimal stand-in for StrategyEngine: emits score_a / score_b."""

    names = ["a", "b"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["score_a"] = df["raw_a"]
        df["score_b"] = df["raw_b"]
        return df


class _Data:
    source = "test"
    adjust = "qfq"


class _Cfg:
    data = _Data()


class FakeDM:
    """Minimal stand-in for DataManager: serves per-code OHLC frames."""

    config = _Cfg()

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


def make_frames() -> dict[str, pd.DataFrame]:
    def one(closes, ra, rb):
        return pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "close": closes,
                "raw_a": ra,
                "raw_b": rb,
            }
        )

    return {
        "A": one([10.0, 11.0], [0.1, 0.3], [0.4, 0.2]),
        "B": one([20.0, 19.0], [0.5, 0.7], [0.6, 0.1]),
        "C": one([30.0, 33.0], [0.2, 0.9], [0.8, 0.3]),
    }


def make_engine(report=None, ranking=None):
    re = RankingEngine(FakeSE(), ranking or RankingConfig())
    return ReportEngine(re, report or ReportConfig())


def test_generate_sorted_and_scored():
    eng = make_engine()
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    assert [r.code for r in rep.rows] == ["C", "B", "A"]
    assert [r.rank for r in rep.rows] == [1, 2, 3]
    by = {r.code: r for r in rep.rows}
    assert abs(by["C"].composite_score - 0.60) < 1e-9
    assert abs(by["B"].composite_score - 0.40) < 1e-9
    assert abs(by["A"].composite_score - 0.25) < 1e-9
    assert rep.universe_size == 3
    assert rep.source == "test (qfq)"


def test_generate_price_snapshot_and_daily_change():
    eng = make_engine()
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    by = {r.code: r for r in rep.rows}
    assert by["C"].close == 33.0
    assert abs(by["C"].daily_change_pct - 10.0) < 1e-9
    assert by["B"].close == 19.0
    assert abs(by["B"].daily_change_pct - (-5.0)) < 1e-9
    assert by["C"].as_of_date == "2024-01-02"


def test_generate_top_n_cutoff():
    eng = make_engine(report=ReportConfig(top_n=2))
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    assert [r.code for r in rep.rows] == ["C", "B"]


def test_as_of_cross_section_and_snapshot_no_lookahead():
    eng = make_engine(report=ReportConfig(as_of="2024-01-01"))
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    assert [r.code for r in rep.rows] == ["B", "C", "A"]
    by = {r.code: r for r in rep.rows}
    assert by["B"].close == 20.0
    assert by["B"].as_of_date == "2024-01-01"
    assert by["B"].daily_change_pct is None
    assert by["B"].stale is False


def test_stale_flag_when_data_lags_as_of():
    eng = make_engine(report=ReportConfig(as_of="2024-01-20", freshness_days=5))
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    assert all(r.stale is True for r in rep.rows)


def test_generate_empty_when_no_data():
    eng = make_engine()
    rep = eng.generate(["X", "Y"], FakeDM({}))
    assert rep.rows == []
    assert "无候选标的" in rep.to_markdown()


def test_to_markdown_has_table_and_detail():
    eng = make_engine()
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    md = rep.to_markdown(include_detail=True)
    assert "# AROS 每日研究日报" in md
    assert "## 一、Top 候选排序" in md
    assert "## 二、候选明细" in md
    assert "| 排名 |" in md


def test_to_markdown_without_detail():
    eng = make_engine()
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    md = rep.to_markdown(include_detail=False)
    assert "## 一、Top 候选排序" in md
    assert "## 二、候选明细" not in md


def test_to_json_roundtrip():
    eng = make_engine()
    rep = eng.generate(["A", "B", "C"], FakeDM(make_frames()))
    payload = json.loads(rep.to_json())
    assert payload["universe_size"] == 3
    assert len(payload["rows"]) == 3
    assert payload["rows"][0]["code"] == "C"
    assert "composite_score" in payload["rows"][0]


def test_report_row_to_dict():
    row = ReportRow(rank=1, code="A", composite_score=0.5, scores={"a": 0.5})
    d = row.to_dict()
    assert d["code"] == "A"
    assert d["scores"] == {"a": 0.5}


def test_daily_report_dataclass_defaults():
    rep = DailyReport(generated_at="now", as_of="latest", universe_size=0, source="test")
    assert rep.rows == []


def test_real_config_wiring():
    cfg = get_config()
    eng = ReportEngine.from_config(
        cfg.indicators, cfg.factors, cfg.strategies, cfg.ranking, cfg.report
    )
    expected = [s.name for s in cfg.strategies.enabled]
    assert eng.ranking_engine.names == expected


def test_cli_report_list():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    result = runner.invoke(main.app, ["report", "--list"])
    assert result.exit_code == 0, result.output
    assert "Available strategies" in result.output
    assert "Report:" in result.output
