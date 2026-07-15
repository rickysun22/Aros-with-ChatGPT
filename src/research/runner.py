"""Experiment runner -- STUB (fills in Sprint 2.4).

The runner orchestrates an experiment end to end: resolve candidates (universe
or codes), run the strategy through the existing ``BacktestEngine`` /
``PortfolioBacktest``, compute metrics via ``src/backtest/metrics.py``, compare
to the benchmark, and persist results through the registry. 2.0 only reserves
the module and its signature.
"""

from __future__ import annotations

from research.experiment import ExperimentConfig, ExperimentResult


class ResearchRunner:
    """Runs an :class:`ExperimentConfig` and returns an :class:`ExperimentResult`."""

    def run(self, config: ExperimentConfig) -> ExperimentResult:
        raise NotImplementedError("experiment orchestration lands in Sprint 2.4")
