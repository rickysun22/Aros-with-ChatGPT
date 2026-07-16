"""Backtest performance metrics (Sprint 1.6).

Pure, side-effect-free functions: given an equity curve and a trade blotter,
return scalar metrics. The :func:`compute_metrics` dispatcher picks the metrics
named in the backtest config and raises :class:`ConfigError` on unknown names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import BacktestConfig
from core.exceptions import ConfigError

TRADING_DAYS = 252


def total_return(equity: pd.Series) -> float:
    """Total return over the whole equity curve."""
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, years: float | None = None) -> float:
    """Annualised (geometric) return, assuming ~252 trading days per year."""
    if len(equity) < 2:
        return 0.0
    if years is None:
        years = len(equity) / TRADING_DAYS
    if years <= 0:
        return float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough decline (a non-positive number)."""
    runmax = equity.cummax()
    dd = equity / runmax - 1.0
    return float(dd.min())


def _daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().fillna(0.0)


def sharpe(equity: pd.Series, risk_free: float = 0.0) -> float:
    """Annualised Sharpe ratio of daily returns."""
    r = _daily_returns(equity)
    rf_daily = (1.0 + risk_free) ** (1.0 / TRADING_DAYS) - 1.0
    excess = r - rf_daily
    std = r.std(ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS))


def sortino(equity: pd.Series, risk_free: float = 0.0) -> float:
    """Annualised Sortino ratio (downside-deviation denominator)."""
    r = _daily_returns(equity)
    rf_daily = (1.0 + risk_free) ** (1.0 / TRADING_DAYS) - 1.0
    excess = r - rf_daily
    downside = r[r < rf_daily]
    if len(downside) == 0:
        return 0.0
    dd_dev = np.sqrt(((downside - rf_daily) ** 2).mean())
    if dd_dev == 0 or np.isnan(dd_dev):
        return 0.0
    return float(excess.mean() / dd_dev * np.sqrt(TRADING_DAYS))


def win_rate(equity: pd.Series) -> float:
    """Fraction of bars with a positive period return."""
    r = _daily_returns(equity)
    if len(r) == 0:
        return 0.0
    return float((r > 0).mean())


def num_trades(trades: pd.DataFrame) -> int:
    """Number of rebalance events in the blotter."""
    return int(len(trades))


def turnover(trades: pd.DataFrame) -> float:
    """Cumulative one-way turnover (sum of absolute weight changes)."""
    if trades is None or len(trades) == 0:
        return 0.0
    return float(trades["weight_change"].abs().sum())


def benchmark_return(close: pd.Series) -> float:
    """Buy-and-hold return of the underlying instrument."""
    if close.iloc[0] == 0:
        return 0.0
    return float(close.iloc[-1] / close.iloc[0] - 1.0)


def profit_factor(equity: pd.Series) -> float:
    """Gross profit / gross loss over daily equity returns.

    The trade blotter carries no per-trade realised PnL, so this is computed
    from daily returns (the standard return-based profit factor).
    """
    r = _daily_returns(equity)
    gross_profit = float(r[r > 0].sum())
    gross_loss = float(-r[r < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calmar(equity: pd.Series) -> float:
    """CAGR divided by the absolute maximum drawdown."""
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return cagr(equity) / abs(mdd)


def avg_holding_days(trades: pd.DataFrame) -> float:
    """Mean calendar-day gap between consecutive rebalance events."""
    if trades is None or len(trades) < 2 or "date" not in trades.columns:
        return 0.0
    dates = pd.to_datetime(trades["date"]).sort_values()
    gaps = dates.diff().dropna().dt.days
    if len(gaps) == 0:
        return 0.0
    return float(gaps.mean())


def max_consecutive_losses(equity: pd.Series) -> float:
    """Length of the longest run of consecutive down days."""
    r = _daily_returns(equity)
    best = 0
    run = 0
    for v in r.to_numpy():
        if v < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return float(best)


def exposure(equity: pd.Series, trades: pd.DataFrame) -> float:
    """Fraction of bars holding a non-zero weight.

    ``compute_metrics`` does not receive a position series, only trade events,
    so the held weight is reconstructed from cumulative ``weight_change`` over
    the equity index; the result is the share of bars with non-zero weight.
    """
    if trades is None or len(trades) == 0:
        return 0.0
    pos = pd.Series(0.0, index=equity.index)
    for _, t in trades.iterrows():
        try:
            i = equity.index.get_loc(t["date"])
        except KeyError:
            continue
        pos.iloc[i:] = pos.iloc[i:] + float(t["weight_change"])
    return float((pos != 0).mean())


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame,
    close: pd.Series,
    config: BacktestConfig,
) -> dict[str, float]:
    """Compute the metrics selected in ``config.metrics`` plus optional benchmark."""
    available = {
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "max_drawdown": max_drawdown(equity),
        "sharpe": sharpe(equity, config.risk_free),
        "sortino": sortino(equity, config.risk_free),
        "win_rate": win_rate(equity),
        "num_trades": float(num_trades(trades)),
        "turnover": turnover(trades),
        "benchmark_return": benchmark_return(close),
        "profit_factor": profit_factor(equity),
        "calmar": calmar(equity),
        "avg_holding_days": avg_holding_days(trades),
        "max_consecutive_losses": max_consecutive_losses(equity),
        "exposure": exposure(equity, trades),
    }
    result: dict[str, float] = {}
    for name in config.metrics:
        if name not in available:
            raise ConfigError(f"Unknown metric name in backtest.metrics: {name!r}")
        result[name] = available[name]
    if config.benchmark and "benchmark_return" not in result:
        result["benchmark_return"] = available["benchmark_return"]
    return result
