"""Benchmark comparison engine (Sprint 2.3).

Compares an experiment's equity curve against a benchmark index pulled through
:meth:`DataManager.get_index_daily` -- the single data entry point, with a
no-look-ahead ``as_of`` ceiling. Produces five benchmark-relative metrics:
``excess_return``, ``alpha`` (annualised CAPM), ``beta``, ``tracking_error``
(annualised) and ``information_ratio`` (annualised).

Return math (daily returns) is reused from ``src/backtest/metrics.py`` via the
public :func:`daily_returns` helper -- return computation lives in exactly one
place. Only the *benchmark-specific* maths (alpha/beta/TE/IR) lives here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from backtest.metrics import TRADING_DAYS, daily_returns
from core.config import AppConfig, get_config
from core.exceptions import ConfigError, DataError
from data.manager import DataManager


@runtime_checkable
class IndexDataSource(Protocol):
    """Structural type for the benchmark data dependency (mirrors DataProvider).

    :class:`~data.manager.DataManager` satisfies this protocol; tests inject a
    lightweight fake exposing the same ``config`` + ``get_index_daily`` surface.
    """

    config: AppConfig

    def get_index_daily(
        self,
        code: str,
        start_date: date | None = ...,
        end_date: date | None = ...,
        as_of: date | None = ...,
    ) -> pd.DataFrame: ...


@dataclass
class BenchmarkComparison:
    """Result of comparing a portfolio equity curve against a benchmark index."""

    benchmark_code: str  # the resolved key actually used, e.g. "csi300"
    excess_return: float
    alpha: float  # annualised CAPM alpha
    beta: float
    tracking_error: float  # annualised
    information_ratio: float  # annualised
    n_points: int  # aligned overlapping bars used

    def to_dict(self) -> dict[str, float]:
        """Return the numeric metrics as a plain dict (for 2.4 persistence).

        The ``benchmark_code`` label is a dimension, not a metric, so it is not
        included; every remaining field is cast to ``float``.
        """
        d = asdict(self)
        d.pop("benchmark_code", None)
        return {k: float(v) for k, v in d.items()}


def _to_date(value: str | date) -> date:
    """Coerce an ISO ``YYYY-MM-DD`` string (or a ``date``) into a ``date``."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DataError(f"Invalid date string {value!r}, expected YYYY-MM-DD") from exc


def _as_ts_series(series: pd.Series) -> pd.Series:
    """Return a copy indexed by ``Timestamp`` and sorted ascending by date."""
    out = pd.Series(series.to_numpy(dtype=float), index=pd.to_datetime(series.index))
    return out.sort_index()


class BenchmarkEngine:
    """Compares experiment performance against a benchmark index (Sprint 2.3)."""

    def __init__(self, data_manager: IndexDataSource | None = None) -> None:
        # None => a DataManager built from get_config(); injectable for tests.
        self._dm: IndexDataSource = data_manager if data_manager is not None else DataManager()

    @property
    def _config(self) -> AppConfig:
        cfg = getattr(self._dm, "config", None)
        return cfg if isinstance(cfg, AppConfig) else get_config()

    def compare(
        self,
        portfolio_equity: pd.Series,
        benchmark_code: str,
        range: tuple[str, str],  # noqa: A002 - matches Phase2 plan signature
        risk_free: float | None = None,
        as_of: str | None = None,
    ) -> BenchmarkComparison:
        """Compare ``portfolio_equity`` to a benchmark over an aligned window.

        Metrics are computed on the inner-joined dates of the portfolio equity
        and the benchmark equity (only dates present in *both* series). The
        benchmark fetch is capped at ``as_of`` (defaulting to the portfolio's
        own last date) so it can never leak data the portfolio could not see.
        """
        if portfolio_equity is None or len(portfolio_equity) < 2:
            raise DataError("portfolio_equity must have at least 2 points to compare")

        cfg = self._config
        indices = cfg.benchmark.indices
        if benchmark_code not in indices:
            raise ConfigError(
                f"Unknown benchmark key {benchmark_code!r}; known keys: {sorted(indices)}"
            )
        raw_code = indices[benchmark_code]

        if risk_free is None:
            risk_free = cfg.backtest.risk_free

        start = _to_date(range[0])
        end = _to_date(range[1])
        pe = _as_ts_series(portfolio_equity)
        ceiling = _to_date(as_of) if as_of is not None else pe.index.max().date()

        bench_df = self._dm.get_index_daily(raw_code, start, end, ceiling)
        be = _as_ts_series(
            pd.Series(
                bench_df["close"].to_numpy(dtype=float),
                index=pd.to_datetime(bench_df["date"]),
            )
        )

        aligned = pd.concat({"p": pe, "b": be}, axis=1, join="inner").dropna()
        if len(aligned) < 2:
            raise DataError(
                "Insufficient overlapping dates between portfolio and benchmark "
                f"(got {len(aligned)}); need at least 2."
            )
        pe_a = aligned["p"]
        be_a = aligned["b"]

        r_p = daily_returns(pe_a)
        r_b = daily_returns(be_a)
        rf_daily = (1.0 + risk_free) ** (1.0 / TRADING_DAYS) - 1.0
        excess_p = r_p - rf_daily
        excess_b = r_b - rf_daily

        # excess_return: scale-invariant period-return difference.
        excess_return = float(
            (pe_a.iloc[-1] / pe_a.iloc[0] - 1.0) - (be_a.iloc[-1] / be_a.iloc[0] - 1.0)
        )

        # beta = Cov(r_p, r_b) / Var(r_b); flat benchmark => 0.0.
        var_b = float(r_b.var(ddof=1))
        if var_b == 0.0 or np.isnan(var_b):
            beta = 0.0
        else:
            cov = float(np.cov(r_p.to_numpy(), r_b.to_numpy(), ddof=1)[0, 1])
            beta = cov / var_b

        # annualised CAPM alpha.
        alpha = float((excess_p.mean() - beta * excess_b.mean()) * TRADING_DAYS)

        # annualised tracking error of active returns; IR = active mean / TE.
        active = r_p - r_b
        te = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS))
        if np.isnan(te):
            te = 0.0
        information_ratio = 0.0 if te == 0.0 else float(active.mean() * TRADING_DAYS / te)

        return BenchmarkComparison(
            benchmark_code=benchmark_code,
            excess_return=excess_return,
            alpha=alpha,
            beta=beta,
            tracking_error=te,
            information_ratio=information_ratio,
            n_points=int(len(aligned)),
        )
