"""Phase 3 Strategy Contract (Sprint 3.0).

A single, reusable contract every AROS research strategy must satisfy so it can
be batch-backtested and fairly compared. This contract is deliberately separate
from :class:`core.config.StrategySpec` (which drives the 1.5 weighted/rule
engine): that one is an *engine instance* config, while this is the
*research-level* description -- category, engine, universe, holding period, exit
rules, data fidelity -- that the Phase 3 discovery pipeline consumes. It never
touches the 2.0 frozen :class:`research.experiment.ExperimentConfig`.

Frozen decisions implemented here (Phase 3 Design v1.0):
  D1 -- category is one of trend / strong / emotion
  D2 -- engine is one of portfolio / event (both emit the same metrics)
  D3 -- data_fidelity must be declared; needs_intraday => "advisory only"
  D5 -- the contract is a Pydantic model living in this module
  D7 -- every strategy binds a universe (csi800 / all_a / custom)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal["trend", "strong", "emotion"]
Engine = Literal["portfolio", "event"]
UniverseName = Literal["csi800", "all_a", "custom"]
DataFidelity = Literal["daily_full", "daily_approx", "needs_intraday"]


class HoldingPeriod(BaseModel):
    """Holding horizon in trading days (reporting / risk-control metadata)."""

    min: int = 1
    max: int = 20


class ExitRules(BaseModel):
    """Event-engine exit rules (used when engine == ``"event"``)."""

    stop_loss: float = -0.05
    take_profit: float = 0.10
    max_holding_days: int = 5


class RiskControl(BaseModel):
    """Hard position limits applied by the runner / event engine."""

    max_position_per_name: float = 0.1
    max_positions: int = 10


class ResearchStrategySpec(BaseModel):
    """The Phase 3 strategy contract (implements D1-D5, D7)."""

    name: str
    display_name: str
    category: Category
    engine: Engine
    universe: UniverseName
    description: str = ""
    holding_period: HoldingPeriod = Field(default_factory=HoldingPeriod)
    entry_rules: list[str] = Field(default_factory=list)
    exit_rules: ExitRules = Field(default_factory=ExitRules)
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_control: RiskControl = Field(default_factory=RiskControl)
    data_fidelity: DataFidelity = "daily_full"
    custom_codes: list[str] | None = None

    @model_validator(mode="after")
    def _check_custom(self) -> ResearchStrategySpec:
        if self.universe == "custom" and not self.custom_codes:
            raise ValueError("universe='custom' requires non-empty custom_codes")
        return self

    def experiment_universe(self) -> str | None:
        """Map this spec's universe to an :class:`ExperimentConfig` value.

        ``custom`` maps to ``None`` (the runner must pass ``codes`` instead);
        ``csi800`` / ``all_a`` are pool keys resolved by the runner at run time
        via :class:`UniverseResolver`.
        """
        return self.universe if self.universe != "custom" else None


# Convenience alias so the design doc's "StrategySpec" name resolves here.
StrategySpec = ResearchStrategySpec


# --------------------------------------------------------------------------- #
# In-process strategy library registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, ResearchStrategySpec] = {}


def register_strategy(spec: ResearchStrategySpec) -> ResearchStrategySpec:
    """Register a strategy spec by its ``name`` (idempotent overwrite)."""
    _REGISTRY[spec.name] = spec
    return spec


def get_strategy(name: str) -> ResearchStrategySpec:
    """Return the registered spec for ``name`` or raise KeyError."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_strategies() -> list[ResearchStrategySpec]:
    """All registered strategy specs, sorted by name."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def clear_registry() -> None:
    """Drop all registered specs (test helper)."""
    _REGISTRY.clear()


# --------------------------------------------------------------------------- #
# Universe resolution (D6 survivor-ship bias guard / D7 frozen pools)
# --------------------------------------------------------------------------- #
class UniverseResolver:
    """Resolve a strategy's :class:`UniverseName` to concrete codes.

    The survivor-ship-bias guard (D6) is a *requirement*, not a nicety:

    * ``custom`` -- the explicit ``custom_codes`` (always point-in-time).
    * ``all_a``  -- ``DataManager.get_stock_list()``. The data layer currently
      returns the *current* list, so this is an approximation until a
      point-in-time snapshot is wired in 3.2; callers must be aware.
    * ``csi800`` -- a named :class:`~universe.engine.UniverseEngine` pool whose
      membership must be seeded with *historical* constituents in 3.2. If the
      pool is empty/unknown the resolver refuses to silently use the wrong set
      (that would be exactly the survivor-ship bias D6 forbids).
    """

    def __init__(self, universe_engine: Any | None = None) -> None:
        self.universe_engine = universe_engine

    def resolve(
        self,
        spec: ResearchStrategySpec,
        as_of: Any | None = None,
        data_manager: Any | None = None,
    ) -> list[str]:
        """Return the sorted, de-duplicated code list for ``spec``.

        Args:
            spec: the strategy whose universe is resolved.
            as_of: optional point-in-time date (used by point-in-time resolvers
                in 3.2); unused by the 3.0 default resolver.
            data_manager: required for the ``all_a`` pool.
        """
        if spec.universe == "custom":
            return sorted(set(spec.custom_codes or []))
        if spec.universe == "all_a":
            if data_manager is None:
                raise ValueError("all_a universe requires a data_manager")
            df = data_manager.get_stock_list()
            if "code" not in df.columns:
                return []
            return sorted(df["code"].astype(str).tolist())
        if spec.universe == "csi800":
            if self.universe_engine is None:
                raise ValueError("csi800 universe requires a universe_engine")
            codes = self.universe_engine.get_codes("csi800")
            if not codes:
                raise ValueError(
                    "csi800 pool empty/undefined; seed historical constituents (D6) before use"
                )
            return sorted(set(codes))
        raise ValueError(f"Unknown universe {spec.universe!r}")
