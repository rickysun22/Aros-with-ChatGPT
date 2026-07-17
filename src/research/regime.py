"""Market-regime classification (Sprint 3.2).

A transparent, rule-based market-regime tagger used by
:class:`~research.batch.BatchRunner` for sub-period robustness analysis. The
labels are derived from **explainable** statistics of a benchmark close series
(momentum, realised volatility, drawdown) -- never a black-box model -- so the
Phase 3 "no AI prediction" red line stays intact.

Categories (ordered by severity of stress):

* ``Bull``     -- benchmark rising, calm vol, no deep drawdown.
* ``Neutral``  -- no clear trend / moderate vol.
* ``Bear``     -- benchmark falling, no extreme stress.
* ``Extreme``  -- spike in volatility or deep drawdown (panic / melt-up tails).

No look-ahead: the regime at date ``t`` uses only data ``<= t`` (rolling windows
with ``min_periods``), so a tag can never depend on the future.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

# Thresholds (tunable). Windows are in trading days; vol is annualised.
_MOM_WINDOW = 20
_VOL_WINDOW = 20
_DD_WINDOW = 20
_BULL_MOM = 0.05
_BEAR_MOM = -0.05
_EXTREME_ANN_VOL = 0.45
_EXTREME_DD = 0.15

Regime = str  # one of the four labels below
BULL: Regime = "Bull"
NEUTRAL: Regime = "Neutral"
BEAR: Regime = "Bear"
EXTREME: Regime = "Extreme"

REGIMES: Sequence[Regime] = (BULL, NEUTRAL, BEAR, EXTREME)


def classify_regime(benchmark_close: pd.Series) -> pd.Series:
    """Tag each date of ``benchmark_close`` with a market regime.

    The result is a :class:`pandas.Series` of :data:`REGIMES` strings, indexed
    identically to ``benchmark_close`` (any ``NaN`` prices are dropped first so
    they do not poison the rolling windows). Rules, evaluated per date using
    only data up to that date:

    1. ``Extreme`` if annualised realised vol > :data:`_EXTREME_ANN_VOL` *or* the
       drawdown from the trailing ``_DD_WINDOW``-day high exceeds
       :data:`_EXTREME_DD`.
    2. ``Bull`` if momentum (``_MOM_WINDOW``-day return) > :data:`_BULL_MOM`
       (and not Extreme).
    3. ``Bear`` if momentum < :data:`_BEAR_MOM` (and not Extreme).
    4. ``Neutral`` otherwise.
    """
    s = benchmark_close.dropna()
    if s.empty:
        return pd.Series(dtype="object", index=benchmark_close.index)

    mom = s.pct_change(_MOM_WINDOW)
    daily_ret = s.pct_change().fillna(0.0)
    ann_vol = daily_ret.rolling(_VOL_WINDOW, min_periods=_VOL_WINDOW).std() * (252**0.5)
    run_max = s.rolling(_DD_WINDOW, min_periods=1).max()
    dd = s / run_max - 1.0

    labels: list[Regime] = []
    for i in range(len(s)):
        if i + 1 < _VOL_WINDOW:
            # Not enough history yet -- default to neutral until vol is known.
            labels.append(NEUTRAL)
            continue
        is_extreme = (ann_vol.iloc[i] > _EXTREME_ANN_VOL) or (dd.iloc[i] < -_EXTREME_DD)
        if is_extreme:
            labels.append(EXTREME)
        elif mom.iloc[i] > _BULL_MOM:
            labels.append(BULL)
        elif mom.iloc[i] < _BEAR_MOM:
            labels.append(BEAR)
        else:
            labels.append(NEUTRAL)

    out = pd.Series(labels, index=s.index, dtype="object")
    return out.reindex(benchmark_close.index, fill_value=NEUTRAL)
