"""The Phase 2 experiment protocol (Sprint 2.0 -- frozen schema).

The whole point of Sprint 2.0 is to *freeze* :class:`ExperimentConfig` now so
that Sprints 2.1-2.6 read a stable set of fields. Changing these later ripples
across the entire phase, so the schema is defined here even though the engines
that consume it are still stubbed.

``ExperimentResult`` is a light, typed container the runner (2.4) will populate;
it is intentionally minimal in 2.0 (rails, not logic).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, model_validator


class WalkForwardSpec(BaseModel):
    """Walk-forward split specification (consumed in Sprint 2.5).

    All units are in years. ``None`` on :attr:`ExperimentConfig.walk_forward`
    means a single full-range run instead of a rolling walk-forward.
    """

    train_years: int
    test_years: int
    step_years: int


class ExperimentConfig(BaseModel):
    """A reproducible research experiment definition (frozen in Sprint 2.0).

    Candidate source is either a named :class:`UniversePool` (1.13) via
    ``universe`` *or* an explicit ``codes`` list -- the two are mutually
    exclusive. Everything needed to reproduce a run lives here so the config can
    be round-tripped to/from ``ExperimentRun.config_json``.
    """

    name: str
    strategy: str  # StrategyEngine strategy name (1.5)
    start: str  # "YYYY-MM-DD" inclusive
    end: str  # "YYYY-MM-DD" inclusive
    universe: str | None = None  # UniversePool name (1.13); mutually exclusive with codes
    codes: list[str] | None = None  # explicit candidate codes
    benchmark: str = "csi300"  # key into BenchmarkConfig.indices
    metrics: list[str] | None = None  # None => BacktestConfig.metrics default
    walk_forward: WalkForwardSpec | None = None  # None => single full-range run
    seed: int | None = None

    @model_validator(mode="after")
    def _validate_candidate_source(self) -> ExperimentConfig:
        if self.universe is not None and self.codes is not None:
            raise ValueError("ExperimentConfig: set either 'universe' or 'codes', not both")
        return self


@dataclass
class ExperimentResult:
    """Typed container for a completed experiment (populated by the 2.4 runner).

    Kept intentionally minimal in 2.0. ``metrics`` / ``equity`` are keyed by a
    window tag (``"full"`` for a single-range run) so walk-forward results slot
    in without a schema change.
    """

    run_id: str
    metrics: dict[str, dict[str, float | None]] = field(default_factory=dict)
    equity: dict[str, dict[str, float]] = field(default_factory=dict)
    windows: list[str] = field(default_factory=list)
