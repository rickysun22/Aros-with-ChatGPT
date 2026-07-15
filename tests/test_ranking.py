"""Tests for the Sprint 1.7 ranking engine.

The ranking layer sits on top of StrategyEngine, which turns raw data into
score_<name> columns. To test the ranking math in isolation (no indicators /
factors / network), we inject a tiny fake strategy engine that maps raw_* input
columns onto score_<name> outputs. The CLI --list smoke test and a real-config
wiring test exercise the genuine config path without computing factors.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.config import (
    DimensionSpec,
    RankingConfig,
    get_config,
)
from core.exceptions import DataError
from ranking.engine import RankingEngine


class FakeSE:
    """Minimal stand-in for StrategyEngine: emits score_a / score_b."""

    names = ["a", "b"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["score_a"] = df["raw_a"]
        df["score_b"] = df["raw_b"]
        return df


def make_engine(se=None, ranking=None):
    return RankingEngine(se or FakeSE(), ranking or RankingConfig())


def multi_stock_df():
    return pd.DataFrame(
        {
            "code": ["A", "A", "B", "B", "C", "C"],
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-01",
                "2024-01-02",
                "2024-01-01",
                "2024-01-02",
            ],
            "raw_a": [0.1, 0.3, 0.5, 0.7, 0.2, 0.9],
            "raw_b": [0.4, 0.2, 0.6, 0.1, 0.8, 0.3],
        }
    )


# --------------------------------------------------------------------------- #
# Core ranking
# --------------------------------------------------------------------------- #
def test_rank_sorted_descending_default_equal_weight():
    eng = make_engine()
    table, scored = eng.rank(multi_stock_df())
    assert table["code"].tolist() == ["C", "B", "A"]
    # default equal weight => 0.5*(score_a + score_b)
    c = table.set_index("code")
    assert abs(c.loc["C", "composite_score"] - 0.60) < 1e-9
    assert abs(c.loc["B", "composite_score"] - 0.40) < 1e-9
    assert abs(c.loc["A", "composite_score"] - 0.25) < 1e-9
    assert list(table["rank"]) == [1, 2, 3]


def test_rank_explicit_weights():
    rc = RankingConfig(
        dimensions=[
            DimensionSpec(strategy="a", weight=1.0),
            DimensionSpec(strategy="b", weight=2.0),
        ]
    )
    eng = make_engine(ranking=rc)
    table, _ = eng.rank(multi_stock_df())
    # wsum=3: composite = (1*sa + 2*sb)/3
    c = table.set_index("code")
    assert abs(c.loc["C", "composite_score"] - 0.50) < 1e-9
    assert abs(c.loc["B", "composite_score"] - 0.30) < 1e-9


def test_rank_negative_weight():
    rc = RankingConfig(
        dimensions=[
            DimensionSpec(strategy="a", weight=1.0),
            DimensionSpec(strategy="b", weight=-0.5),
        ]
    )
    eng = make_engine(ranking=rc)
    table, _ = eng.rank(multi_stock_df())
    # wsum=1.5: composite = (sa - 0.5*sb)/1.5
    c = table.set_index("code")
    assert abs(c.loc["C", "composite_score"] - 0.50) < 1e-9
    assert abs(c.loc["B", "composite_score"] - 0.4333333) < 1e-6


def test_rank_top_n_cutoff():
    rc = RankingConfig(top_n=2)
    eng = make_engine(ranking=rc)
    table, _ = eng.rank(multi_stock_df())
    assert len(table) == 2
    assert table["code"].tolist() == ["C", "B"]
    assert list(table["rank"]) == [1, 2]


# --------------------------------------------------------------------------- #
# Cross-section (as_of)
# --------------------------------------------------------------------------- #
def test_rank_as_of_uses_only_past_bars():
    rc = RankingConfig(as_of="2024-01-01")
    eng = make_engine(ranking=rc)
    table, _ = eng.rank(multi_stock_df())
    # cross-section picks each code's last bar <= 2024-01-01
    # A: sa=0.1,sb=0.4 => 0.25; B: sa=0.5,sb=0.6 => 0.55; C: sa=0.2,sb=0.8 => 0.50
    # => B(0.55) > C(0.50) > A(0.25)
    assert table["code"].tolist() == ["B", "C", "A"]
    c = table.set_index("code")
    assert abs(c.loc["B", "composite_score"] - 0.55) < 1e-9
    assert abs(c.loc["C", "composite_score"] - 0.50) < 1e-9


def test_rank_as_of_is_no_lookahead():
    # as_of must never see a bar dated after it
    rc = RankingConfig(as_of="2024-01-01")
    eng = make_engine(ranking=rc)
    table, _ = eng.rank(multi_stock_df())
    # B wins under as_of, but under the latest cross-section C wins (B's later
    # bar has a much weaker sb). If look-ahead leaked, B would use its 2024-01-02
    # bar (sa=0.7) and beat C here too.
    assert table.iloc[0]["code"] == "B"


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
def test_rank_requires_code_column():
    eng = make_engine()
    df = multi_stock_df().drop(columns=["code"])
    with pytest.raises(DataError):
        eng.rank(df)


def test_rank_missing_score_column_raises():
    rc = RankingConfig(dimensions=[DimensionSpec(strategy="zzz", weight=1.0)])
    eng = make_engine(ranking=rc)
    with pytest.raises(DataError):
        eng.rank(multi_stock_df())


# --------------------------------------------------------------------------- #
# Real config wiring (no factor computation)
# --------------------------------------------------------------------------- #
def test_real_config_wiring():
    cfg = get_config()
    eng = RankingEngine.from_config(cfg.indicators, cfg.factors, cfg.strategies, cfg.ranking)
    expected = [s.name for s in cfg.strategies.enabled]
    assert eng.names == expected
    # default dimensions resolve to all enabled strategies, equal weight
    dims = eng._resolve_dimensions()
    assert [d.strategy for d in dims] == expected
    assert all(d.weight == 1.0 for d in dims)


# --------------------------------------------------------------------------- #
# CLI smoke
# --------------------------------------------------------------------------- #
def test_cli_ranking_list():
    from typer.testing import CliRunner

    import main

    runner = CliRunner()
    result = runner.invoke(main.app, ["ranking", "--list"])
    assert result.exit_code == 0, result.output
    assert "Available strategies" in result.output
    assert "weighted_momentum" in result.output
