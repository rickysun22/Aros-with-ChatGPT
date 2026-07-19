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

from .batch import BatchResult, BatchRunner
from .benchmark import BenchmarkComparison, BenchmarkEngine
from .combination import (
    OSCILLATING,
    TRENDING,
    CombinationEngine,
    CombinedResult,
    MarketEnv,
    env_for_regime,
    render_combination_report,
)
from .experiment import ExperimentConfig, ExperimentResult, WalkForwardSpec
from .final_report import FinalReport, render_final_report
from .market_regime import (
    BEAR,
    BULL,
    EMOTION_COLD,
    EMOTION_HOT,
    REGIMES_5,
    MarketRegimeEngine,
    SelectionResult,
    classify_market_regime,
)
from .models import ExperimentEquity, ExperimentMetric, ExperimentRun
from .ranking import RankingReport, build_score_inputs
from .regime import NEUTRAL, REGIMES, classify_regime
from .registry import ExperimentRegistry
from .report import ResearchReport, render_experiment_report
from .runner import ResearchRunner
from .scorecard import SCORECARD_METRIC_KEYS, Scorecard, ScoreInput, ScoreRow
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
    "RankingReport",
    "build_score_inputs",
    "CombinationEngine",
    "CombinedResult",
    "render_combination_report",
    "env_for_regime",
    "MarketEnv",
    "TRENDING",
    "OSCILLATING",
    "FinalReport",
    "render_final_report",
    "MarketRegimeEngine",
    "SelectionResult",
    "classify_market_regime",
    "REGIMES_5",
    "BULL",
    "NEUTRAL",
    "BEAR",
    "EMOTION_HOT",
    "EMOTION_COLD",
    "Scorecard",
    "ScoreInput",
    "ScoreRow",
    "SCORECARD_METRIC_KEYS",
    "BatchRunner",
    "BatchResult",
    "classify_regime",
    "REGIMES",
    "NEUTRAL",
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
