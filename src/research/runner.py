"""Experiment runner (Sprint 2.4).

Thin *orchestration + persistence* layer that chains the existing engines into
one runnable, persistable experiment:

    resolve candidates -> run portfolio -> compute metrics ->
    benchmark compare -> persist -> return ExperimentResult

It builds no new metric math (that lives in ``src/backtest/metrics.py`` and
``src/research/benchmark.py``); it only wires the already-shipped engines
(``PortfolioBacktest`` 1.16, ``compute_metrics`` 1.6/2.2, ``BenchmarkEngine``
2.3) and the persistence layer (``ExperimentRegistry`` 2.1) together.

No-look-ahead: the benchmark fetch and ``BenchmarkEngine.compare`` are both
capped at ``as_of=end`` (the experiment's last date), so the benchmark can never
read data the portfolio could not have seen.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd

from backtest.metrics import compute_metrics
from backtest.portfolio import PortfolioBacktest, PortfolioResult
from core.config import AppConfig, get_config
from core.exceptions import ConfigError, DataError
from data.manager import DataManager
from research.benchmark import BenchmarkEngine
from research.experiment import ExperimentConfig, ExperimentResult
from research.registry import ExperimentRegistry
from universe.engine import UniverseEngine

PortfolioFn = Callable[[list[str], Any, date, date], PortfolioResult]


def _to_date(value: str | date) -> date:
    """Coerce an ISO ``YYYY-MM-DD`` string (or a ``date``) into a ``date``."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DataError(f"Invalid date string {value!r}, expected YYYY-MM-DD") from exc


def _equity_to_dict(equity: pd.Series) -> dict[str, float]:
    """Serialize an equity/price series into ``{iso_date: float}``."""
    return {pd.Timestamp(ts).strftime("%Y-%m-%d"): float(v) for ts, v in equity.items()}


class ResearchRunner:
    """Runs an :class:`ExperimentConfig` end to end and returns an
    :class:`ExperimentResult` (Sprint 2.4).
    """

    def __init__(
        self,
        data_manager: Any | None = None,
        portfolio_fn: PortfolioFn | None = None,
        benchmark_engine: BenchmarkEngine | None = None,
        config: AppConfig | None = None,
    ) -> None:
        # ``None`` dependencies are resolved lazily from get_config() so tests can
        # inject fakes. ``data_manager`` flows to *both* the portfolio step and the
        # benchmark step (single data entry point).
        self._dm = data_manager if data_manager is not None else DataManager()
        self._portfolio_fn = portfolio_fn
        self._benchmark_engine = benchmark_engine
        self._config = config if config is not None else get_config()

    # ------------------------------------------------------------------ #
    # Default heavy backtest (real pipeline)
    # ------------------------------------------------------------------ #
    def _make_default_portfolio_fn(self, strategy: str | None) -> PortfolioFn:
        """Build the real ``PortfolioBacktest.from_config`` path as a 4-arg seam."""
        cfg = self._config

        def _fn(codes: list[str], dm: Any, start: date, end: date) -> PortfolioResult:
            bt = cfg.backtest.model_copy(deep=True)
            if strategy is not None:
                bt.strategy = strategy
            pb = PortfolioBacktest.from_config(
                cfg.indicators,
                cfg.factors,
                cfg.strategies,
                cfg.ranking,
                bt,
                top_n=cfg.ranking.top_n,
            )
            return pb.run(codes, dm, start, end)

        return _fn

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        config: ExperimentConfig,
        session: Any = None,
        notes: str | None = None,
    ) -> ExperimentResult:
        """Execute ``config`` end to end, persist, and return the result.

        Public behaviour is unchanged from 2.4 (a single ``"full"`` window).
        The per-window work now lives in :meth:`_execute_window` so the
        walk-forward runner can reuse it without duplicating the
        backtest/metric/benchmark/persist logic.
        """
        reg = ExperimentRegistry(session)
        run_id = reg.create(name=config.name, config_json=config.model_dump_json(), notes=notes)
        result = self._execute_window(config, session, window="full", run_id=run_id, is_oos=False)
        reg.mark_done(run_id)
        return result

    def _execute_window(
        self,
        config: ExperimentConfig,
        session: Any,
        *,
        window: str,
        run_id: str,
        is_oos: bool,
    ) -> ExperimentResult:
        """Run one window of ``config`` and persist it under ``window``/``is_oos``.

        Identical to the former ``run()`` body (steps 1-6) except it does NOT
        create the run (``run_id`` is passed in) and does NOT call
        ``mark_done`` -- the caller owns lifecycle. Used directly by
        :class:`~research.walk_forward.WalkForwardRunner` for each IS/OOS fold.
        Returns the result keyed by ``window``.
        """
        cfg = self._config

        # 1. Resolve candidates (universe pool XOR explicit codes).
        if config.universe is not None:
            codes = UniverseEngine(session).get_codes(config.universe)
        else:
            codes = list(config.codes or [])
        if not codes:
            raise DataError(
                "Experiment has no candidate codes: empty universe and no explicit codes"
            )

        start_d = _to_date(config.start)
        end_d = _to_date(config.end)

        # 2. Portfolio backtest (injected seam; default = real pipeline).
        pf = (
            self._portfolio_fn
            if self._portfolio_fn is not None
            else self._make_default_portfolio_fn(config.strategy)
        )
        presult = pf(list(codes), self._dm, start_d, end_d)
        equity = presult.equity
        trades = presult.trades
        if equity is None or len(equity) < 2:
            raise DataError("Portfolio backtest produced fewer than 2 equity points")

        # No-look-ahead ceiling: the benchmark is capped at the portfolio's *own*
        # last date, never the calendar experiment end. The equity can end before
        # ``end`` (sparse data / non-trading tail), and a later benchmark bar would
        # otherwise leak into ``benchmark_return`` (step 3 has no inner join).
        as_of_date = pd.Timestamp(equity.index[-1]).date()

        # 3. Benchmark close for the portfolio ``benchmark_return`` metric.
        indices = cfg.benchmark.indices
        bench_key = config.benchmark
        if bench_key not in indices:
            raise ConfigError(f"Unknown benchmark key {bench_key!r}; known keys: {sorted(indices)}")
        raw_code = indices[bench_key]
        bench_df = self._dm.get_index_daily(raw_code, start_d, end_d, as_of=as_of_date)
        bench_close = pd.Series(
            bench_df["close"].to_numpy(dtype=float),
            index=pd.to_datetime(bench_df["date"]),
        )

        # 4. Portfolio metrics (reuse the single metric dispatcher; no new math).
        metrics_list = list(config.metrics) if config.metrics else list(cfg.backtest.metrics)
        bt_cfg = cfg.backtest.model_copy(deep=True)
        bt_cfg.metrics = metrics_list
        bt_cfg.benchmark = True
        portfolio_metrics = compute_metrics(equity, trades, bench_close, bt_cfg)

        # 5. Benchmark-relative metrics (capped at the same portfolio last date).
        engine = self._benchmark_engine or BenchmarkEngine(self._dm)
        bench = engine.compare(
            equity,
            bench_key,
            (config.start, config.end),
            risk_free=cfg.backtest.risk_free,
            as_of=str(as_of_date),
        )

        # 6. Persist this window (all ORM writes go through the registry).
        bench_metrics = {f"bench_{k}": v for k, v in bench.to_dict().items()}
        equity_dict = _equity_to_dict(equity)
        reg = ExperimentRegistry(session)
        reg.record_metrics(run_id, portfolio_metrics, window, is_oos)
        reg.record_metrics(run_id, bench_metrics, window, is_oos)
        reg.record_equity(run_id, equity_dict, window, is_oos)

        # 7. Return the typed result keyed by ``window`` (2.5 slots OOS in).
        combined = {**portfolio_metrics, **bench_metrics}
        return ExperimentResult(
            run_id=run_id,
            metrics={window: combined},
            equity={window: equity_dict},
            windows=[window],
        )
