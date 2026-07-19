"""Batch strategy experiment runner (Sprint 3.2).

Runs every Phase 3 research strategy against one *frozen*
:class:`~research.experiment.ExperimentConfig` (pool / range / capital / fees /
benchmark, frozen in 2.0), using the same walk-forward machinery as
:class:`~research.walk_forward.WalkForwardRunner` (Sprint 2.5). Each strategy is
executed through :func:`research.strategy_library.run_strategy` -- the uniform
event-engine path introduced in 3.1 -- so all strategies land in one comparable
metric set (portfolio metrics + ``bench_*`` relative metrics).

Key design points:

* **One run per strategy.** Each strategy gets its own
  :class:`~research.registry.ExperimentRegistry` run (``{config.name}:{strategy}``)
  so :meth:`~research.registry.ExperimentRegistry.load_result` reproduces it
  exactly (the design's "结果可 load_result 复现" requirement).
* **D7 universe binding.** The codes for each fold come from
  :class:`~research.strategy_spec.UniverseResolver` reading the strategy's own
  ``universe`` field (``csi800`` / ``all_a`` / ``custom``) -- never a global pool.
* **No look-ahead.** The benchmark is capped at the strategy's own last equity
  date (mirrors :class:`~research.runner.ResearchRunner`); the event engine also
  reindexes the benchmark to the traded dates.
* **Regime robustness (optional).** When ``regime_analysis=True`` each trade is
  tagged with the market regime on its entry date (via
  :func:`research.regime.classify_regime`) and aggregated per regime, giving a
  sub-period stability read without re-running the backtest.
* **Testability.** ``price_provider`` / ``benchmark_provider`` are injectable so
  the runner is exercised end-to-end on synthetic data (no DB / no network).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from core.config import AppConfig, get_config
from core.exceptions import ConfigError, DataError
from data.manager import DataManager
from research.benchmark import BenchmarkEngine
from research.experiment import ExperimentConfig
from research.registry import ExperimentRegistry
from research.strategy_library import get_strategy, run_strategy
from research.strategy_spec import UniverseResolver
from research.walk_forward import WalkForwardSplitter, _aggregate_walk_forward

from .regime import NEUTRAL, classify_regime
from .scorecard import SCORECARD_METRIC_KEYS

PriceProvider = Callable[[list[str], str, str], dict[str, pd.DataFrame]]
BenchmarkProvider = Callable[[str, str, str], pd.Series]


def _to_date(value: str | date) -> date:
    """Coerce an ISO ``YYYY-MM-DD`` string (or ``date``) into a ``date``."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _equity_to_dict(equity: pd.Series) -> dict[str, float]:
    """Serialize an equity series into ``{iso_date: float}`` (runner contract)."""
    return {pd.Timestamp(ts).strftime("%Y-%m-%d"): float(v) for ts, v in equity.items()}


class _DmPriceProvider:
    """Default price provider: pull daily bars from :class:`DataManager`."""

    def __init__(self, data_manager: DataManager) -> None:
        self._dm = data_manager

    def __call__(self, codes: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for code in codes:
            df = self._dm.get_daily(code, _to_date(start), _to_date(end))
            if df is not None and not df.empty:
                out[code] = df
        return out


class _DmBenchmarkProvider:
    """Default benchmark provider: pull index close from :class:`DataManager`."""

    def __init__(self, data_manager: DataManager, config: AppConfig) -> None:
        self._dm = data_manager
        self._config = config

    def __call__(self, bench_key: str, start: str, end: str) -> pd.Series:
        raw_code = self._config.benchmark.indices[bench_key]
        df = self._dm.get_index_daily(raw_code, _to_date(start), _to_date(end))
        return pd.Series(df["close"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]))


@dataclass
class StrategyBatchOutcome:
    """Per-strategy result of a :meth:`BatchRunner.run`."""

    name: str
    display_name: str
    run_id: str
    category: str
    engine: str
    data_fidelity: str
    is_metrics: dict[str, float | None]
    oos_metrics: dict[str, float | None]
    fold_metrics: dict[str, dict[str, float | None]] = field(default_factory=dict)
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Aggregated outcome of a batch experiment across many strategies."""

    config_name: str
    outcomes: list[StrategyBatchOutcome] = field(default_factory=list)


class BatchRunner:
    """Traverse strategies x frozen ExperimentConfig x walk-forward (3.2)."""

    def __init__(
        self,
        data_manager: DataManager | None = None,
        universe_engine: Any | None = None,
        config: AppConfig | None = None,
        price_provider: PriceProvider | None = None,
        benchmark_provider: BenchmarkProvider | None = None,
        benchmark_engine: BenchmarkEngine | None = None,
    ) -> None:
        self._dm = data_manager if data_manager is not None else DataManager()
        self._universe_engine = universe_engine
        self._config = config if config is not None else get_config()
        self._price = price_provider or _DmPriceProvider(self._dm)
        self._bench = benchmark_provider or _DmBenchmarkProvider(self._dm, self._config)
        self._bench_engine = benchmark_engine or BenchmarkEngine(self._dm)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run_all(
        self,
        config: ExperimentConfig,
        session: Any = None,
        notes: str | None = None,
        *,
        regime_analysis: bool = True,
    ) -> BatchResult:
        """Run every registered research strategy against ``config``."""
        from research.strategy_library import list_strategies

        return self.run(
            [s.spec.name for s in list_strategies()],
            config,
            session,
            notes,
            regime_analysis=regime_analysis,
        )

    def run(
        self,
        strategies: list[str],
        config: ExperimentConfig,
        session: Any = None,
        notes: str | None = None,
        *,
        regime_analysis: bool = True,
    ) -> BatchResult:
        """Batch-backtest ``strategies`` under the frozen ``config``.

        Each strategy is run through walk-forward (or a single full window when
        ``config.walk_forward is None``), persisted as its own
        :class:`ExperimentRun`, and returned as a :class:`StrategyBatchOutcome`.
        """
        reg = ExperimentRegistry(session)
        cfg = self._config
        bench_key = config.benchmark
        if bench_key not in cfg.benchmark.indices:
            raise ConfigError(
                f"Unknown benchmark key {bench_key!r}; known: {sorted(cfg.benchmark.indices)}"
            )

        backtest_cfg = cfg.backtest.model_copy(deep=True)
        metrics_list = list(config.metrics) if config.metrics else list(cfg.backtest.metrics)
        # Sprint 3.3: ensure the scorecard (7-dimension AROS Strategy Score) can
        # be computed from this run. ``profit_factor`` / ``avg_holding_days`` /
        # ``max_consecutive_losses`` are not in the default backtest metric set
        # but ``compute_metrics`` produces them; add any that are missing so the
        # realised metrics are always present for scoring (additive, no removal).
        for key in SCORECARD_METRIC_KEYS:
            if key not in metrics_list:
                metrics_list.append(key)
        backtest_cfg.metrics = metrics_list
        backtest_cfg.benchmark = True

        resolver = UniverseResolver(self._universe_engine)
        outcomes: list[StrategyBatchOutcome] = []

        for name in strategies:
            strategy = get_strategy(name)
            spec = strategy.spec
            run_id = reg.create(
                name=f"{config.name}:{spec.name}",
                config_json=config.model_dump_json(),
                notes=notes,
            )

            results: dict[str, Mapping[str, float | None]] = {}
            windows: list[str] = []
            fold_metrics: dict[str, dict[str, float | None]] = {}
            regime_acc: dict[str, list[float]] = {}
            regime_count: dict[str, int] = {}

            fold_pairs = self._fold_windows(config)
            for window, is_oos, ws, we in fold_pairs:
                codes = resolver.resolve(spec, as_of=we, data_manager=self._dm)
                if not codes:
                    combined: dict[str, float | None] = {k: None for k in metrics_list}
                    positions: list[dict] = []
                    bench_close: pd.Series | None = None
                else:
                    combined, positions, bench_close = self._run_fold(
                        strategy, codes, ws, we, bench_key, backtest_cfg
                    )
                results[window] = combined
                fold_metrics[window] = combined
                windows.append(window)
                if regime_analysis and positions and bench_close is not None:
                    self._accumulate_regime(regime_acc, regime_count, positions, bench_close)

                reg.record_metrics(run_id, combined, window, is_oos)

            # Aggregate IS / OOS summaries.
            if config.walk_forward is None:
                full = dict(results.get("full", {}))
                is_agg: dict[str, float | None] = dict(full)
                oos_agg: dict[str, float | None] = dict(full)
                agg_windows = ["full", "is_agg", "oos_agg"]
            else:
                is_agg, oos_agg = _aggregate_walk_forward(results, windows)
                agg_windows = ["is_agg", "oos_agg"]

            reg.record_metrics(run_id, is_agg, "is_agg", False)
            reg.record_metrics(run_id, oos_agg, "oos_agg", True)
            fold_metrics["is_agg"] = is_agg
            fold_metrics["oos_agg"] = oos_agg
            windows += agg_windows
            reg.mark_done(run_id)

            breakdown = self._regime_breakdown(regime_acc, regime_count)
            outcomes.append(
                StrategyBatchOutcome(
                    name=spec.name,
                    display_name=spec.display_name,
                    run_id=run_id,
                    category=spec.category,
                    engine=spec.engine,
                    data_fidelity=spec.data_fidelity,
                    is_metrics=is_agg,
                    oos_metrics=oos_agg,
                    fold_metrics=fold_metrics,
                    regime_breakdown=breakdown,
                )
            )

        return BatchResult(config_name=config.name, outcomes=outcomes)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fold_windows(
        config: ExperimentConfig,
    ) -> list[tuple[str, bool, str, str]]:
        """Return ``(window, is_oos, start, end)`` pairs for one strategy run."""
        if config.walk_forward is None:
            return [("full", False, config.start, config.end)]
        folds = WalkForwardSplitter().split(config.walk_forward, config.start, config.end)
        if not folds:
            raise DataError("Range too short for walk_forward spec (need >= train+test years)")
        pairs: list[tuple[str, bool, str, str]] = []
        for f in folds:
            pairs.append((f"is_{f.index}", False, f.train_start, f.train_end))
            pairs.append((f"oos_{f.index}", True, f.test_start, f.test_end))
        return pairs

    def _run_fold(
        self,
        strategy: Any,
        codes: list[str],
        start: str,
        end: str,
        bench_key: str,
        backtest_cfg: Any,
    ) -> tuple[dict[str, float | None], list[dict], pd.Series | None]:
        """Run one strategy fold; return (combined_metrics, positions, bench_close)."""
        prices = self._price(codes, start, end)
        bench_close = self._bench(bench_key, start, end)
        result = run_strategy(strategy, prices, backtest_cfg, benchmark=bench_close)

        if result.equity is None or len(result.equity) < 2:
            combined: dict[str, float | None] = {k: None for k in backtest_cfg.metrics}
            return combined, [], bench_close

        as_of_date = pd.Timestamp(result.equity.index[-1]).date()
        if len(result.equity) >= 2:
            try:
                bench = self._bench_engine.compare(
                    result.equity,
                    bench_key,
                    (start, end),
                    risk_free=backtest_cfg.risk_free,
                    as_of=str(as_of_date),
                )
                bench_metrics = {f"bench_{k}": v for k, v in bench.to_dict().items()}
            except (DataError, ConfigError):
                bench_metrics = {}
        else:
            bench_metrics = {}

        combined = {**result.metrics, **bench_metrics}
        return combined, result.positions, bench_close

    @staticmethod
    def _accumulate_regime(
        acc: dict[str, list[float]],
        counts: dict[str, int],
        positions: list[dict],
        bench_close: pd.Series,
    ) -> None:
        """Tag each trade by the regime on its entry date and accumulate returns."""
        regime = classify_regime(bench_close)
        for pos in positions:
            r = regime.get(pd.Timestamp(str(pos["entry_date"])), NEUTRAL)
            counts[r] = counts.get(r, 0) + 1
            acc.setdefault(r, []).append(float(pos["return"]))

    @staticmethod
    def _regime_breakdown(
        acc: dict[str, list[float]], counts: dict[str, int]
    ) -> dict[str, dict[str, float]]:
        """Turn accumulated per-regime returns into a readable summary."""
        breakdown: dict[str, dict[str, float]] = {}
        for r, rets in acc.items():
            if not rets:
                continue
            breakdown[r] = {
                "n_trades": float(counts.get(r, 0)),
                "mean_return": float(sum(rets) / len(rets)),
                "total_return": float(sum(rets)),
            }
        return breakdown
