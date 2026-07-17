"""AROS Phase 2 research engine (Sprint 2.0 foundation).

Sprint 2.0 lays the rails: experiment-persistence ORM models, the frozen
:class:`ExperimentConfig` protocol, and a CRUD :class:`ExperimentRegistry`.
Sprint 2.3 adds :class:`BenchmarkEngine` (benchmark comparison). Sprint 2.4
adds :class:`ResearchRunner`, the orchestration + persistence layer that chains
the engines and records results. Walk-forward/OOS (2.5) and report rendering
(2.6) still land later.

NOTE: there is intentionally **no** ``research/metrics.py``. All metric math
lives in ``src/backtest/metrics.py`` and is *extended there* in Sprint 2.2 --
never duplicated into this package. This mirror-free rule is the reuse map from
``Phase2-Research-Engine-Revision.md``; do not re-add a metrics module here.
"""

from .benchmark import BenchmarkComparison, BenchmarkEngine
from .experiment import ExperimentConfig, ExperimentResult, WalkForwardSpec
from .models import ExperimentEquity, ExperimentMetric, ExperimentRun
from .registry import ExperimentRegistry
from .report import ResearchReport, render_experiment_report
from .runner import ResearchRunner
from .scorecard import Scorecard, ScoreInput, ScoreRow
from .strategy_library import (
    STRATEGIES,
    ResearchStrategy,
    get_strategy,
    list_strategies,
    run_strategy,
)
from .strategy_spec import (
    ResearchStrategySpec,
    StrategySpec,
    UniverseResolver,
    clear_registry,
    register_strategy,
)
from .walk_forward import WalkForwardFold, WalkForwardRunner, WalkForwardSplitter

__all__ = [
    "ExperimentConfig",
    "ExperimentResult",
    "WalkForwardSpec",
    "ExperimentRun",
    "ExperimentMetric",
    "ExperimentEquity",
    "ExperimentRegistry",
    "BenchmarkEngine",
    "BenchmarkComparison",
    "ResearchRunner",
    "WalkForwardSplitter",
    "WalkForwardRunner",
    "WalkForwardFold",
    "ResearchReport",
    "render_experiment_report",
    "Scorecard",
    "ScoreInput",
    "ScoreRow",
    "ResearchStrategySpec",
    "StrategySpec",
    "UniverseResolver",
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "clear_registry",
    "ResearchStrategy",
    "STRATEGIES",
    "run_strategy",
]
