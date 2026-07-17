"""Walk-forward / out-of-sample splitting + orchestration (Sprint 2.5).

Turns a :class:`~research.experiment.WalkForwardSpec` into rolling train/test
windows for out-of-sample validation. Two pieces:

* :class:`WalkForwardSplitter` -- pure date arithmetic, no data access.
* :class:`WalkForwardRunner` -- orchestrates rolling windows by reusing
  ``ResearchRunner._execute_window`` (the single-window seam added in 2.5), so
  the backtest / metric / benchmark / persist logic is written exactly once.

No-look-ahead is guaranteed at two levels (per the frozen design):

1. **Window isolation** -- each fold runs on a ``config.model_copy`` bounded to
   that fold's ``[start, end]``; the OOS fold's ``start == train_end`` (the test
   window begins exactly where training ends), so it can never consume
   train-window data.
2. **Within-window ceiling** -- ``_execute_window`` keeps the 2.4 ``as_of``
   ceiling: the benchmark is capped at the portfolio's *own* last date inside the
   fold, so a later benchmark bar never leaks into the fold's metrics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.config import AppConfig, get_config
from core.exceptions import DataError
from data.manager import DataManager
from research.benchmark import BenchmarkEngine
from research.experiment import ExperimentConfig, ExperimentResult, WalkForwardSpec
from research.registry import ExperimentRegistry
from research.runner import ResearchRunner


@dataclass(frozen=True)
class WalkForwardFold:
    """One rolling train/test window (all dates are ``"YYYY-MM-DD"`` strings)."""

    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str


class WalkForwardSplitter:
    """Generates rolling IS/OOS windows from a :class:`WalkForwardSpec`."""

    def split(self, spec: WalkForwardSpec, start: str, end: str) -> list[WalkForwardFold]:
        """Return folds in chronological order.

        Year offsets use ``pd.DateOffset(years=N)`` (leap-day safe -- never
        ``date.replace(year=...)``). A fold is included only when its *whole*
        test window fits inside ``[start, end]``; partial trailing windows are
        dropped. Returns ``[]`` when the range is shorter than ``train+test``.

        The OOS window starts exactly where training ends (``test_start ==
        train_end``) -- the core no-look-ahead boundary.
        """
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        folds: list[WalkForwardFold] = []
        cursor = start_ts
        i = 0
        while True:
            train_start = cursor
            train_end = train_start + pd.DateOffset(years=spec.train_years)
            test_start = train_end  # test begins exactly where train ends
            test_end = test_start + pd.DateOffset(years=spec.test_years)
            if test_end > end_ts:  # never extend past the experiment range
                break
            folds.append(
                WalkForwardFold(
                    index=i,
                    train_start=train_start.strftime("%Y-%m-%d"),
                    train_end=train_end.strftime("%Y-%m-%d"),
                    test_start=test_start.strftime("%Y-%m-%d"),
                    test_end=test_end.strftime("%Y-%m-%d"),
                )
            )
            cursor = cursor + pd.DateOffset(years=spec.step_years)
            i += 1
        return folds


def _aggregate_walk_forward(
    results: dict[str, Mapping[str, float | None]],
    windows: list[str],
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Simple per-metric mean over IS folds and over OOS folds.

    ``None`` / non-finite entries are skipped (mirrors the registry's
    ``record_metrics`` coercion contract). Returns ``(is_agg, oos_agg)``.
    """
    is_windows = [w for w in windows if w.startswith("is_") and w != "is_agg"]
    oos_windows = [w for w in windows if w.startswith("oos_") and w != "oos_agg"]

    all_keys: set[str] = set()
    for w in (*is_windows, *oos_windows):
        all_keys.update(results.get(w, {}).keys())

    def _mean(window_keys: list[str]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for k in sorted(all_keys):
            vals: list[float] = []
            for w in window_keys:
                v = results.get(w, {}).get(k)
                if v is not None and math.isfinite(v):
                    vals.append(float(v))
            out[k] = (sum(vals) / len(vals)) if vals else None
        return out

    return _mean(is_windows), _mean(oos_windows)


class WalkForwardRunner:
    """Runs a rolling walk-forward experiment and tags OOS folds (Sprint 2.5)."""

    def __init__(
        self,
        data_manager: Any | None = None,
        portfolio_fn: Any | None = None,
        benchmark_engine: BenchmarkEngine | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._dm = data_manager if data_manager is not None else DataManager()
        self._portfolio_fn = portfolio_fn
        self._benchmark_engine = benchmark_engine
        self._config = config if config is not None else get_config()

    def run(
        self,
        config: ExperimentConfig,
        session: Any = None,
        notes: str | None = None,
    ) -> ExperimentResult:
        """Execute a walk-forward experiment and return the aggregated result."""
        spec = config.walk_forward

        # D8: no walk_forward => delegate to the normal single-range runner.
        if spec is None:
            return ResearchRunner(
                self._dm, self._portfolio_fn, self._benchmark_engine, self._config
            ).run(config, session, notes)

        folds = WalkForwardSplitter().split(spec, config.start, config.end)
        if not folds:
            raise DataError("Range too short for walk_forward spec (need >= train+test years)")

        reg = ExperimentRegistry(session)
        run_id = reg.create(name=config.name, config_json=config.model_dump_json(), notes=notes)

        results: dict[str, Mapping[str, float | None]] = {}
        equity: dict[str, dict[str, float]] = {}
        windows: list[str] = []

        runner = ResearchRunner(self._dm, self._portfolio_fn, self._benchmark_engine, self._config)

        for f in folds:
            # Each fold is bounded to its own slice -> window isolation (D5).
            is_cfg = config.model_copy(update={"start": f.train_start, "end": f.train_end})
            oos_cfg = config.model_copy(update={"start": f.test_start, "end": f.test_end})
            is_res = runner._execute_window(
                is_cfg, session, window=f"is_{f.index}", run_id=run_id, is_oos=False
            )
            oos_res = runner._execute_window(
                oos_cfg, session, window=f"oos_{f.index}", run_id=run_id, is_oos=True
            )
            results[f"is_{f.index}"] = is_res.metrics[f"is_{f.index}"]
            results[f"oos_{f.index}"] = oos_res.metrics[f"oos_{f.index}"]
            equity[f"is_{f.index}"] = is_res.equity[f"is_{f.index}"]
            equity[f"oos_{f.index}"] = oos_res.equity[f"oos_{f.index}"]
            windows += [f"is_{f.index}", f"oos_{f.index}"]

        # 5.3 aggregation into two summary windows (metrics only; no equity curve).
        is_agg, oos_agg = _aggregate_walk_forward(results, windows)
        results["is_agg"] = is_agg
        results["oos_agg"] = oos_agg
        equity["is_agg"] = {}
        equity["oos_agg"] = {}
        windows += ["is_agg", "oos_agg"]

        reg.record_metrics(run_id, is_agg, "is_agg", False)
        reg.record_metrics(run_id, oos_agg, "oos_agg", True)
        reg.mark_done(run_id)

        return ExperimentResult(run_id=run_id, metrics=results, equity=equity, windows=windows)
