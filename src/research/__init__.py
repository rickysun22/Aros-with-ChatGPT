"""AROS Phase 2 research engine (Sprint 2.0 foundation).

Sprint 2.0 lays only the rails: experiment-persistence ORM models, the frozen
:class:`ExperimentConfig` protocol, and a CRUD :class:`ExperimentRegistry`. The
actual research logic -- benchmark comparison, runner orchestration,
walk-forward/OOS, and report rendering -- lands in Sprints 2.1-2.6 and is only
*stubbed* here (see ``benchmark.py`` / ``runner.py`` / ``walk_forward.py`` /
``report.py``).

NOTE: there is intentionally **no** ``research/metrics.py``. All metric math
lives in ``src/backtest/metrics.py`` and is *extended there* in Sprint 2.2 --
never duplicated into this package. This mirror-free rule is the reuse map from
``Phase2-Research-Engine-Revision.md``; do not re-add a metrics module here.
"""

from .experiment import ExperimentConfig, ExperimentResult, WalkForwardSpec
from .models import ExperimentEquity, ExperimentMetric, ExperimentRun
from .registry import ExperimentRegistry

__all__ = [
    "ExperimentConfig",
    "ExperimentResult",
    "WalkForwardSpec",
    "ExperimentRun",
    "ExperimentMetric",
    "ExperimentEquity",
    "ExperimentRegistry",
]
