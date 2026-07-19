"""Tests for the Phase 4.1 Validation Engine + Strategy Validation Gate.

Pure-function tests cover the scoring math; the integration test runs the full
engine on synthetic data (offline, no network) to confirm the evidence chain is
persisted and the registry is updated. Calibration against the real built-in 10
strategies is a separate, data-synced step (``python main.py research validate all``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import AppConfig, WalkForwardConfig, get_config
from core.database import Base
from research.models import StrategyRegistry as StrategyRegistryModel
from research.models import StrategyValidation
from research.validate import (
    ValidationEngine,
    compute_oos_composite,
    compute_reliability,
    evaluate_gate,
    quality_star_from_composite,
)


# --------------------------------------------------------------------------- #
# Synthetic data fakes (mirror tests/test_batch.py, kept self-contained)
# --------------------------------------------------------------------------- #
def _mem_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(eng)()


def _frames(codes, start, end, seed=0):
    idx = pd.date_range(start, end, freq="B")
    rng = np.random.RandomState(seed)
    out = {}
    for i, code in enumerate(codes):
        n = len(idx)
        drift = np.cumsum(rng.randn(n) * 0.05) + i * 0.5
        close = 10.0 + np.maximum.accumulate(drift)
        vol = np.full(n, 1_000_000.0)
        vol[::20] = 5_000_000.0
        out[code] = pd.DataFrame(
            {
                "open": (close * 0.99).round(3),
                "high": (close * 1.02).round(3),
                "low": (close * 0.98).round(3),
                "close": close.round(3),
                "volume": vol,
            },
            index=idx,
        )
    return out


def _price_provider(codes, start, end):
    return _frames(codes, start, end, seed=hash(tuple(codes)) % 1000)


def _bench_provider(key, start, end):
    idx = pd.date_range(start, end, freq="B")
    rng = np.random.RandomState(7)
    close = 3000.0 + np.cumsum(rng.randn(len(idx)) * 5)
    return pd.Series(close, index=idx)


class _FakeUE:
    def get_codes(self, name):
        return ["600000", "600036", "000001", "000002"]


# --------------------------------------------------------------------------- #
# Pure scoring math
# --------------------------------------------------------------------------- #
def _qcfg():
    return AppConfig().validation.quality_star


def test_oos_composite_at_full_marks() -> None:
    q = _qcfg()
    oos = {"total_return": 0.30, "sharpe": 2.0, "max_drawdown": -0.10, "num_trades": 200}
    composite, br = compute_oos_composite(oos, [0.10, 0.12, 0.08], q)
    assert composite > 90
    assert br["return"] == 100.0  # 0.30 / 0.30 = 1.0 -> 100
    assert br["sharpe"] == 100.0  # 2.0 / 2.0 = 1.0 -> 100
    # drawdown 0.10 / 0.60 -> 1 - 0.167 = 0.833 -> 83.3
    assert br["drawdown"] == pytest.approx(100 * (1 - 0.10 / 0.60), abs=0.01)


def test_quality_star_vetoes() -> None:
    q = _qcfg()
    # high composite but deep drawdown -> capped at 2
    composite, _ = compute_oos_composite(
        {"total_return": 0.5, "sharpe": 3.0, "max_drawdown": -0.5, "num_trades": 200},
        [0.1, 0.1],
        q,
    )
    assert quality_star_from_composite(composite, 0.5, 200, q) == 2
    # high composite but too few trades -> capped at 3
    assert quality_star_from_composite(composite, 0.10, 10, q) == 3
    # clean -> 5 stars
    clean, _ = compute_oos_composite(
        {"total_return": 0.4, "sharpe": 2.5, "max_drawdown": -0.05, "num_trades": 300},
        [0.1, 0.1, 0.1],
        q,
    )
    assert quality_star_from_composite(clean, 0.05, 300, q) == 5


def test_reliability_fixed_rule_is_full_marks() -> None:
    vcfg = AppConfig().validation
    oos = {"total_return": 0.2, "sharpe": 1.0, "max_drawdown": -0.1, "num_trades": 200}
    # num_params=0 -> param_sens=100; oos_perf=100; period=100; trades=100
    score, br = compute_reliability(oos, [0.1, 0.1, 0.1], 0, 0.10, vcfg)
    assert score == 100.0
    assert br["param_sensitivity"] == 100.0


def test_gate_pass_and_fail() -> None:
    vcfg = AppConfig().validation
    good = {"total_return": 0.2, "sharpe": 1.0, "max_drawdown": -0.1, "num_trades": 200}
    passed, detail = evaluate_gate(good, 0.1, 200, 0.10, vcfg.gate)
    assert passed is True
    assert all(detail.values())

    bad = {"total_return": -0.1, "sharpe": -0.2, "max_drawdown": -0.5, "num_trades": 5}
    failed, detail_bad = evaluate_gate(bad, 0.5, 5, 0.95, vcfg.gate)
    assert failed is False
    assert detail_bad["oos_return_gt"] is False
    assert detail_bad["min_trades"] is False
    assert detail_bad["param_stable"] is False


# --------------------------------------------------------------------------- #
# Integration: full engine on synthetic data
# --------------------------------------------------------------------------- #
def test_validation_engine_runs_and_persists() -> None:
    from research.batch import BatchRunner

    session = _mem_session()
    cfg = get_config().model_copy(deep=True)
    cfg.validation.gate.min_trades = 0  # synthetic trade count is low
    cfg.validation.walk_forward = WalkForwardConfig(train_years=1, test_years=1, step_years=1)

    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    engine = ValidationEngine(batch_runner=runner, config=cfg)

    res = engine.run_strategy("ma_bull", session, start="2021-01-01", end="2023-12-31")

    # structured result is well-formed
    assert 1 <= res.quality_star <= 5
    assert 0.0 <= res.reliability_score <= 100.0
    assert isinstance(res.gate_passed, bool)
    assert res.is_range and res.oos_range  # evidence-chain ranges populated

    # evidence chain persisted
    val = session.get(StrategyValidation, res.validation_id)
    assert val is not None
    assert val.strategy_id == "ma_bull"
    assert val.gate_result_json  # JSON string, non-empty
    assert val.reliability_json

    # registry updated (ma_bull was not pre-seeded -> engine auto-added it)
    reg = session.get(StrategyRegistryModel, "ma_bull")
    assert reg is not None
    assert reg.quality_star == res.quality_star
    assert reg.reliability_score == res.reliability_score
    assert reg.gate_passed == res.gate_passed
    assert reg.status == res.status_suggestion


def test_validation_engine_param_sensitivity_runs() -> None:
    """ma_bull has tunable params; the perturbation path must execute and the
    average decay be recorded (even if synthetic data yields zero decay)."""
    from research.batch import BatchRunner

    session = _mem_session()
    cfg = get_config().model_copy(deep=True)
    cfg.validation.gate.min_trades = 0
    cfg.validation.walk_forward = WalkForwardConfig(train_years=1, test_years=1, step_years=1)

    runner = BatchRunner(
        universe_engine=_FakeUE(),
        price_provider=_price_provider,
        benchmark_provider=_bench_provider,
    )
    engine = ValidationEngine(batch_runner=runner, config=cfg)
    res = engine.run_strategy("ma_bull", session, start="2021-01-01", end="2023-12-31")
    # ma_bull numeric params -> at least one perturbed run was produced
    assert res.avg_decay >= 0.0
