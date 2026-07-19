"""Phase 4.1 Validation Engine + Strategy Validation Gate (design §5 4.1 / §1.5).

Wraps :class:`~research.batch.BatchRunner` to turn a strategy into *evidence*:

    walk-forward OOS  ->  OOS Composite quality_star (+ vetoes)
                      ->  parameter-sensitivity test (±1 / ±0.1 perturbation)
                      ->  period-stability (per-OOS-fold positive ratio)
                      ->  Reliability Score (0-100)
                      ->  Strategy Validation Gate (constitutional PASS/FAIL)

The outcome is persisted to ``strategy_validations`` (the evidence chain) and
the strategy's ``strategy_registry`` row is updated with star / reliability /
gate / status. The gate decides admission to the formal library; the engine only
*suggests* a status (v2 §3.2: verification decides, never auto-enables).

All thresholds come from ``config.validation`` so the gate can be calibrated
against the built-in 10 strategies without code changes (design §5 4.1 校准).
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from core.config import AppConfig, ValidationGateConfig, get_config
from research.batch import BatchRunner
from research.experiment import ExperimentConfig, WalkForwardSpec
from research.models import StrategyRegistry as StrategyRegistryModel
from research.models import StrategyValidation
from research.strategy_library import get_strategy
from research.walk_forward import WalkForwardSplitter


# --------------------------------------------------------------------------- #
# Pure scoring helpers (unit-testable, no data access)
# --------------------------------------------------------------------------- #
def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a metric value to a finite float (None / NaN -> default)."""
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _numeric_params(spec: Any) -> dict[str, float]:
    """Return the strategy's tunable parameters that are numeric (int/float)."""
    out: dict[str, float] = {}
    for k, v in (spec.parameters or {}).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def _perturbations(params: dict[str, float]) -> list[tuple[str, float, float]]:
    """Yield ``(key, delta, new_value)`` for each numeric parameter.

    Integers step by ±1 (a 1-bar window change); floats step by ±0.1 (a small
    relative nudge) so the perturbation stays meaningful (design §5 4.1: '±1
    （或小幅网格）扰动').
    """
    out: list[tuple[str, float, float]] = []
    for key, val in params.items():
        if float(val).is_integer() and not isinstance(val, float):
            step = 1.0
        else:
            step = 0.1
        # never drop a window to <= 0
        for delta in (step, -step):
            new_val = val + delta
            if new_val <= 0:
                continue
            out.append((key, delta, new_val))
    return out


def _sharpe_decay(base: float, perturbed: float) -> float:
    """Fractional OOS Sharpe loss under perturbation (0 if base <= 0)."""
    if base <= 0:
        return 0.0
    return max(0.0, (base - perturbed) / base)


def compute_oos_composite(
    oos_metrics: dict[str, float | None],
    fold_returns: list[float | None],
    qcfg: Any,
) -> tuple[float, dict[str, float]]:
    """OOS Composite Score (0-100) from four blended OOS components (design §4.0).

    Components (each 0-100 via a tunable scale, then weighted):
      return 30% / sharpe 25% / drawdown 25% (less drawdown = better) /
      stability 20% (lower std of per-fold OOS returns = better).
    """
    ret = _as_float(oos_metrics.get("total_return"))
    sh = _as_float(oos_metrics.get("sharpe"))
    mdd = abs(_as_float(oos_metrics.get("max_drawdown")))

    ret_s = _clip(ret / qcfg.return_scale, 0.0, 1.0) * 100.0
    sh_s = _clip(sh / qcfg.sharpe_scale, 0.0, 1.0) * 100.0
    dd_s = 100.0 * (1.0 - _clip(mdd / qcfg.drawdown_scale, 0.0, 1.0))
    stab = _fold_std(fold_returns)
    stab_s = 100.0 * (1.0 - _clip(stab / qcfg.stability_scale, 0.0, 1.0))

    composite = 0.30 * ret_s + 0.25 * sh_s + 0.25 * dd_s + 0.20 * stab_s
    breakdown = {
        "return": round(ret_s, 2),
        "sharpe": round(sh_s, 2),
        "drawdown": round(dd_s, 2),
        "stability": round(stab_s, 2),
    }
    return round(composite, 2), breakdown


def _fold_std(fold_returns: list[float | None]) -> float:
    """Std of per-fold OOS returns (0 when fewer than 2 folds available)."""
    vals = [float(r) for r in fold_returns if r is not None]
    if len(vals) < 2:
        return 0.0
    return float(np.std(vals, ddof=0))


def quality_star_from_composite(
    composite: float,
    max_drawdown_abs: float,
    num_trades: float | None,
    qcfg: Any,
) -> int:
    """Map an OOS composite (0-100) to a 1-5 star, applying hard vetoes (§4.0)."""
    if composite >= 90:
        star = 5
    elif composite >= 75:
        star = 4
    elif composite >= 60:
        star = 3
    elif composite >= 40:
        star = 2
    else:
        star = 1
    # Veto 1: deep drawdown cannot be averaged away -> cap at 2 stars.
    if max_drawdown_abs > qcfg.drawdown_veto:
        star = min(star, 2)
    # Veto 2: too few trades -> cap at 3 stars (statistical noise).
    if num_trades is not None and num_trades < qcfg.min_trades_veto:
        star = min(star, 3)
    return star


def compute_reliability(
    oos_metrics: dict[str, float | None],
    fold_returns: list[float | None],
    num_params: int,
    avg_decay: float,
    vcfg: Any,
) -> tuple[float, dict[str, float]]:
    """Reliability Score (0-100): how *trustworthy* the evidence is (design §4.3).

    OOS 40% / parameter-sensitivity 20% / period-stability 20% / trade-count 20%.
    ``vcfg`` is the :class:`~core.config.ValidationConfig` (gate + reliability weights).
    """
    gate: ValidationGateConfig = vcfg.gate
    rc = vcfg.reliability
    ret = _as_float(oos_metrics.get("total_return"))
    sh = _as_float(oos_metrics.get("sharpe"))
    num_trades = _as_float(oos_metrics.get("num_trades"))

    # OOS performance component
    if ret > 0 and sh >= gate.oos_sharpe_gt:
        oos_perf = 100.0
    elif ret > 0:
        oos_perf = 50.0
    else:
        oos_perf = 0.0

    # Parameter-sensitivity component (fixed rules with no tunable -> full marks)
    if num_params == 0:
        param_sens = 100.0
    else:
        denom = max(gate.param_decay_threshold, 1e-9)
        param_sens = 100.0 * max(0.0, 1.0 - avg_decay / denom)

    # Period-stability component (positive OOS sub-windows ratio)
    vals = [r for r in fold_returns if r is not None]
    if vals:
        positive = sum(1 for r in vals if r > 0)
        period_stab = 100.0 * (positive / len(vals))
    else:
        period_stab = 0.0

    # Trade-count adequacy component
    trade_score = 100.0 * _clip(num_trades / max(gate.min_trades, 1), 0.0, 1.0)

    score = (
        rc.oos_weight * oos_perf
        + rc.param_weight * param_sens
        + rc.period_weight * period_stab
        + rc.trades_weight * trade_score
    )
    breakdown = {
        "oos_perf": round(oos_perf, 2),
        "param_sensitivity": round(param_sens, 2),
        "period_stability": round(period_stab, 2),
        "trade_adequacy": round(trade_score, 2),
    }
    return round(score, 2), breakdown


def evaluate_gate(
    oos_metrics: dict[str, float | None],
    max_drawdown_abs: float,
    num_trades: float | None,
    avg_decay: float,
    gate: ValidationGateConfig,
) -> tuple[bool, dict[str, bool]]:
    """Strategy Validation Gate (design §5 4.1): every check must PASS."""
    ret = _as_float(oos_metrics.get("total_return"))
    sh = _as_float(oos_metrics.get("sharpe"))
    n = _as_float(num_trades)
    detail = {
        "no_lookahead": bool(gate.no_lookahead),  # architecture guarantee (T+1)
        "oos_return_gt": ret > gate.oos_return_gt,
        "oos_sharpe_gt": sh > gate.oos_sharpe_gt,
        "max_drawdown_lt": max_drawdown_abs < gate.max_drawdown_lt,
        "min_trades": n >= gate.min_trades,
        "param_stable": (not gate.param_stable) or (avg_decay <= gate.param_decay_threshold),
    }
    return all(detail.values()), detail


# --------------------------------------------------------------------------- #
# Validation engine
# --------------------------------------------------------------------------- #
@dataclass
class ValidationResult:
    """Structured outcome of one :meth:`ValidationEngine.run_strategy` call."""

    strategy_id: str
    validation_id: str
    run_id: str
    composite: float
    quality_star: int
    reliability_score: float
    gate_passed: bool
    status_suggestion: str
    oos_metrics: dict[str, float] = field(default_factory=dict)
    composite_breakdown: dict[str, float] = field(default_factory=dict)
    reliability_breakdown: dict[str, float] = field(default_factory=dict)
    gate_detail: dict[str, bool] = field(default_factory=dict)
    avg_decay: float = 0.0
    is_range: str | None = None
    oos_range: str | None = None
    perturbed_run_ids: list[str] = field(default_factory=list)


class ValidationEngine:
    """Validate one or more strategies and persist the evidence chain (§5 4.1)."""

    def __init__(
        self,
        batch_runner: BatchRunner | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._config = config or get_config()
        self._batch = batch_runner  # injectable for offline tests
        # Convert the config's WalkForwardConfig into the runner's WalkForwardSpec
        # (kept separate so core.config never imports research.*).
        wf = self._config.validation.walk_forward
        self._wf = WalkForwardSpec(
            train_years=wf.train_years, test_years=wf.test_years, step_years=wf.step_years
        )

    def _make_runner(self) -> BatchRunner:
        return self._batch or BatchRunner(config=self._config)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run_strategy(
        self,
        strategy_name: str,
        session: Session,
        *,
        start: str | None = None,
        end: str | None = None,
        benchmark: str | None = None,
        notes: str | None = None,
    ) -> ValidationResult:
        """Validate ``strategy_name`` end to end and persist the evidence.

        Runs a frozen walk-forward OOS (config.data range + config.validation
        walk_forward), computes the quality star / reliability / gate, and writes
        a ``strategy_validations`` row plus updates the ``strategy_registry`` row
        (creating it if the strategy is not yet in the library).
        """
        cfg = self._config
        start = start or cfg.data.start_date
        end = end or cfg.data.end_date
        bench = benchmark or cfg.benchmark.default
        strategy = get_strategy(strategy_name)
        spec = strategy.spec

        runner = self._make_runner()

        # 1. Baseline OOS run (walk-forward, regime analysis off for speed).
        base_cfg = ExperimentConfig(
            name=f"validate_{strategy_name}_base",
            strategy=strategy_name,
            start=start,
            end=end,
            benchmark=bench,
            walk_forward=self._wf,
        )
        batch = runner.run([strategy_name], base_cfg, session=session, regime_analysis=False)
        outcome = batch.outcomes[0]
        oos = outcome.oos_metrics
        fold_metrics = outcome.fold_metrics
        fold_returns = [
            fold_metrics[k].get("total_return")
            for k in sorted(fold_metrics)
            if k.startswith("oos_") and k != "oos_agg"
        ]

        # 2. Parameter-sensitivity test: perturb each numeric parameter, re-run OOS.
        base_sharpe = _as_float(oos.get("sharpe"))
        num_params = _numeric_params(spec)
        decays: list[float] = []
        pert_run_ids: list[str] = []
        if num_params:
            for key, _delta, value in _perturbations(num_params):
                pcfg = base_cfg.model_copy(
                    update={"name": f"validate_{strategy_name}_pert_{key}_{value}"}
                )
                pbatch = runner.run(
                    [strategy_name],
                    pcfg,
                    session=session,
                    regime_analysis=False,
                    spec_overrides={strategy_name: {key: value}},
                )
                psharpe = _as_float(pbatch.outcomes[0].oos_metrics.get("sharpe"))
                decays.append(_sharpe_decay(base_sharpe, psharpe))
                pert_run_ids.append(pbatch.outcomes[0].run_id)
        avg_decay = float(sum(decays) / len(decays)) if decays else 0.0

        # 3. Quality star (OOS composite + vetoes).
        mdd = abs(_as_float(oos.get("max_drawdown")))
        num_trades = _as_float(oos.get("num_trades"))
        composite, comp_break = compute_oos_composite(
            oos, fold_returns, cfg.validation.quality_star
        )
        star = quality_star_from_composite(composite, mdd, num_trades, cfg.validation.quality_star)

        # 4. Reliability score.
        rel_score, rel_break = compute_reliability(
            oos, fold_returns, len(num_params), avg_decay, cfg.validation
        )

        # 5. Strategy Validation Gate.
        passed, gate_detail = evaluate_gate(oos, mdd, num_trades, avg_decay, cfg.validation.gate)
        status_suggestion = "active" if passed else "degraded"

        # 6. Evidence-chain ranges from the walk-forward split.
        is_range, oos_range = self._evidence_ranges(start, end)

        # 7. Persist validation + update registry.
        val_id = f"val_{uuid.uuid4().hex[:8]}"
        val = StrategyValidation(
            id=val_id,
            strategy_id=strategy_name,
            run_id=outcome.run_id,
            metrics_json=_json({k: _as_float(v) for k, v in oos.items()}),
            oos_json=_json(
                {
                    "composite": composite,
                    "components": comp_break,
                    "fold_returns": [None if r is None else float(r) for r in fold_returns],
                }
            ),
            status_suggestion=status_suggestion,
            is_range=is_range,
            oos_range=oos_range,
            optimization="fixed",
            walk_forward_passed=True,
            reliability_json=_json(rel_break),
            gate_result_json=_json(gate_detail),
        )
        session.add(val)

        reg = session.get(StrategyRegistryModel, strategy_name)
        if reg is None:
            from research.kb import StrategyRegistry
            from research.market_regime import REGIME_CATEGORY_FIT

            regimes = [r for r, cats in REGIME_CATEGORY_FIT.items() if spec.category in cats]
            StrategyRegistry(session).add(
                strategy_id=strategy_name,
                name=spec.display_name,
                category=spec.category,
                executable_ref=spec.name,
                status=status_suggestion,
                best_fit_regimes=regimes,
            )
            reg = session.get(StrategyRegistryModel, strategy_name)
        if reg is not None:
            reg.validation_run_id = outcome.run_id
            reg.quality_star = float(star)
            reg.reliability_score = rel_score
            reg.gate_passed = passed
            reg.status = status_suggestion
        session.commit()

        return ValidationResult(
            strategy_id=strategy_name,
            validation_id=val_id,
            run_id=outcome.run_id,
            composite=composite,
            quality_star=star,
            reliability_score=rel_score,
            gate_passed=passed,
            status_suggestion=status_suggestion,
            oos_metrics={k: _as_float(v) for k, v in oos.items()},
            composite_breakdown=comp_break,
            reliability_breakdown=rel_break,
            gate_detail=gate_detail,
            avg_decay=round(avg_decay, 4),
            is_range=is_range,
            oos_range=oos_range,
            perturbed_run_ids=pert_run_ids,
        )

    def run_all(
        self,
        strategy_names: list[str],
        session: Session,
        **kwargs: Any,
    ) -> list[ValidationResult]:
        """Validate several strategies (e.g. all active built-ins)."""
        return [self.run_strategy(name, session, **kwargs) for name in strategy_names]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _evidence_ranges(self, start: str, end: str) -> tuple[str | None, str | None]:
        """Derive in-sample / out-of-sample window ranges for the evidence chain."""
        try:
            folds = WalkForwardSplitter().split(self._wf, start, end)
        except Exception:  # noqa: BLE001 - non-fatal; ranges are evidence only
            return None, None
        if not folds:
            return None, None
        is_range = f"{folds[0].train_start}~{folds[-1].train_end}"
        oos_range = f"{folds[0].test_start}~{folds[-1].test_end}"
        return is_range, oos_range


def _json(obj: Any) -> str:
    """JSON-serialise, coercing numpy / non-finite values to plain JSON-safe."""

    def _clean(o: Any) -> Any:
        if isinstance(o, (np.floating, np.integer)):
            o = float(o) if isinstance(o, np.floating) else int(o)
        if isinstance(o, float):
            return o if math.isfinite(o) else None
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, bool):
            return o
        if o is None:
            return None
        return o

    return json.dumps(_clean(obj), ensure_ascii=False)
