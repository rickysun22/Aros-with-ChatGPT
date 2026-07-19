"""Phase 3 Strategy Library (Sprint 3.1).

Implements the 10 research strategies from the Phase 3 design §7, each as a
:class:`ResearchStrategy` that pairs a frozen :class:`ResearchStrategySpec`
contract (D1-D5, D7) with a *pure, explainable* entry-signal generator.

Design invariants (no negotiation, see design §8):
  * Every signal at day T uses **only data <= T** -- no look-ahead, no leakage.
  * Signal logic is a small, explicit rule set -- no ML, no black box.
  * A strategy emits a per-code, per-date boolean ``entry`` signal that feeds
    :class:`~backtest.event.EventBacktest` (T-day signal -> T+1 open fill).
  * ``engine == "portfolio"`` strategies additionally expose ``score()`` for
    cross-sectional Top-N selection (consumed by the 3.2 BatchRunner); the
    3.1 ``run_strategy`` helper runs every strategy through ``EventBacktest``
    for one comparable metric set (uniform V1.0 research).

Limit-up detection uses a 9.5% close-to-prev-close threshold as a main-board
proxy (board-specific 10%/20%/5% rates are refined in 3.2). All thresholds are
read from ``spec.parameters`` with documented defaults so they stay configurable
(D5 / engineering discipline).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd

from backtest.event import EventBacktest, EventResult
from core.config import BacktestConfig

from .strategy_spec import ResearchStrategySpec, register_strategy

# Uniform close-to-prev-close threshold that captures a main-board 10% limit
# (with rounding tolerance). Board-specific rates land in 3.2.
LIMIT_UP_RATE = 0.095
LIMIT_DOWN_RATE = -0.095


# --------------------------------------------------------------------------- #
# Indicator helpers (pure, no look-ahead)
# --------------------------------------------------------------------------- #
def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average over ``n`` bars (NaN until ``n`` bars available)."""
    if n <= 0:
        raise ValueError("sma window must be positive")
    return series.rolling(n, min_periods=n).mean()


def is_limit_up(close: pd.Series, prev_close: pd.Series, rate: float = LIMIT_UP_RATE) -> pd.Series:
    """Boolean: close >= prev_close * (1 + rate) (main-board limit-up proxy)."""
    prev = prev_close.replace(0, np.nan)
    return (close / prev - 1.0) >= rate


def is_limit_down(
    close: pd.Series, prev_close: pd.Series, rate: float = LIMIT_DOWN_RATE
) -> pd.Series:
    """Boolean: close <= prev_close * (1 + rate) (main-board limit-down proxy)."""
    prev = prev_close.replace(0, np.nan)
    return (close / prev - 1.0) <= rate


def vol_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    """Volume relative to its ``n``-bar average (1.0 == average)."""
    avg = volume.rolling(n, min_periods=n).mean()
    avg_safe = avg.replace(0, np.nan)
    return (volume / avg_safe).fillna(0.0)


def _require_cols(df: pd.DataFrame) -> None:
    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in df.columns]
    if missing:
        raise ValueError(f"price frame missing columns: {missing}")


def _param(spec: ResearchStrategySpec, key: str, default: Any) -> Any:
    """Read an optional tunable from ``spec.parameters`` (D5: configurable)."""
    return spec.parameters.get(key, default)


def _ensure_date_index(prices: dict[str, Any]) -> dict[str, Any]:
    """Normalise each OHLCV frame to a DatetimeIndex on ``date``.

    :class:`~backtest.event.EventBacktest` (and the cross-sectional score path)
    require prices indexed by date. :meth:`data.manager.DataManager.get_daily`
    returns a plain ``date`` *column* with a default RangeIndex (its documented
    storage contract), so frames coming straight from the DataManager must be
    re-indexed here -- otherwise the event engine builds a 1970-epoch common
    index and every signal silently drops to zero (no trades). Frames that are
    already DatetimeIndex'd (e.g. synthetic test data) pass through untouched.
    """
    out: dict[str, Any] = {}
    for code, df in prices.items():
        if isinstance(df, pd.Series):
            out[code] = df  # e.g. the optional __index__ breadth series
            continue
        if isinstance(df.index, pd.DatetimeIndex):
            out[code] = df
            continue
        norm = df.copy()
        if "date" in norm.columns:
            norm["date"] = pd.to_datetime(norm["date"])
            norm = norm.set_index("date")
        out[code] = norm
    return out


# --------------------------------------------------------------------------- #
# Strategy contract
# --------------------------------------------------------------------------- #
class ResearchStrategy(ABC):
    """A Phase 3 research strategy: frozen contract + explainable signal logic."""

    spec: ResearchStrategySpec

    @abstractmethod
    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """code -> boolean entry-signal Series (T-day trigger, T+1 open fill).

        Each inner Series is indexed by date and uses only data <= that date.
        """

    def score(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """code -> continuous cross-sectional score (portfolio engine only).

        Default: re-use the boolean entry signal as a 0/1 score. Portfolio
        strategies override this with a real ranking input.
        """
        return self.entry_signals(prices)


def _single_code(
    spec: ResearchStrategySpec, fn: Any, prices: dict[str, pd.DataFrame]
) -> dict[str, pd.Series]:
    """Apply a per-code boolean rule ``fn(df) -> pd.Series`` across all codes."""
    out: dict[str, pd.Series] = {}
    for code, df in prices.items():
        _require_cols(df)
        out[code] = fn(df).fillna(False)
    return out


# --------------------------------------------------------------------------- #
# Batch 1 -- daily_full modelling
# --------------------------------------------------------------------------- #
class MaBullStrategy(ResearchStrategy):
    """均线多头: MA short > mid > long, price above long MA, optional volume filter.

    Portfolio engine (D2): emits a continuous strength score; ``run_strategy``
    picks the cross-sectional Top-N each day.
    """

    spec = ResearchStrategySpec(
        name="ma_bull",
        display_name="均线多头",
        category="trend",
        engine="portfolio",
        universe="csi800",
        description="MA5>MA10>MA20 多头排列且收盘价在长均线上方，量能不过度萎缩。",
        data_fidelity="daily_full",
        parameters={"fast": 5, "mid": 10, "slow": 20, "vol_floor": 0.6},
    )

    def _strength(self, df: pd.DataFrame) -> pd.Series:
        fast = int(_param(self.spec, "fast", 5))
        mid = int(_param(self.spec, "mid", 10))
        slow = int(_param(self.spec, "slow", 20))
        vol_floor = float(_param(self.spec, "vol_floor", 0.6))
        ma_f = sma(df["close"], fast)
        ma_m = sma(df["close"], mid)
        ma_s = sma(df["close"], slow)
        aligned = (ma_f > ma_m) & (ma_m > ma_s) & (df["close"] > ma_s)
        vol_ok = vol_ratio(df["volume"], 20) >= vol_floor
        # Strength: only meaningful when aligned (cross-sectionally comparable).
        strength = (df["close"] / ma_s - 1.0).where(aligned & vol_ok, 0.0)
        return strength

    def score(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        return {code: self._strength(df) for code, df in prices.items()}

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        return {code: (self._strength(df) > 0) for code, df in prices.items()}


class HighBreakoutStrategy(ResearchStrategy):
    """新高突破: N-day new high with volume confirmation; T+1 open entry."""

    spec = ResearchStrategySpec(
        name="high_breakout",
        display_name="新高突破",
        category="trend",
        engine="event",
        universe="csi800",
        description="收盘价创 N 日新高且成交量放大，确认趋势突破。",
        data_fidelity="daily_full",
        parameters={"n": 20, "vol_mult": 1.2},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        n = int(_param(self.spec, "n", 20))
        vol_mult = float(_param(self.spec, "vol_mult", 1.2))

        def fn(df: pd.DataFrame) -> pd.Series:
            prev_high = df["close"].shift(1).rolling(n, min_periods=n).max()
            new_high = df["close"] >= prev_high
            vol_ok = vol_ratio(df["volume"], 20) >= vol_mult
            return (new_high & vol_ok).fillna(False)

        return _single_code(self.spec, fn, prices)


class VolumeBreakoutStrategy(ResearchStrategy):
    """放量突破: volume spike with price clearing prior resistance.

    Distinct from 新高突破: here the *volume surge* is the primary trigger and
    the price simply clears the prior day's high (or short MA), so it fires on
    accumulation days that may not yet be N-day highs.
    """

    spec = ResearchStrategySpec(
        name="volume_breakout",
        display_name="放量突破",
        category="trend",
        engine="event",
        universe="csi800",
        description="成交量骤放（量比阈值）且价格突破前高/短均线的资金持续日。",
        data_fidelity="daily_full",
        parameters={"vol_mult": 2.0, "ma": 5},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        vol_mult = float(_param(self.spec, "vol_mult", 2.0))
        ma = int(_param(self.spec, "ma", 5))

        def fn(df: pd.DataFrame) -> pd.Series:
            surge = vol_ratio(df["volume"], 20) >= vol_mult
            resistance = sma(df["close"], ma)
            cleared = df["close"] > resistance.shift(1)
            return (surge & cleared).fillna(False)

        return _single_code(self.spec, fn, prices)


class StrongPullbackStrategy(ResearchStrategy):
    """强势回踩: strong uptrend -> shrinking-volume pullback to support -> relaunch."""

    spec = ResearchStrategySpec(
        name="strong_pullback",
        display_name="强势回踩",
        category="strong",
        engine="event",
        universe="csi800",
        description="强趋势中缩量回踩均线支撑，再次出现启动阳线时低吸。日线近似。",
        data_fidelity="daily_approx",
        parameters={"ma": 20, "pullback_days": 3, "vol_floor": 0.7},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        ma = int(_param(self.spec, "ma", 20))
        pullback_days = int(_param(self.spec, "pullback_days", 3))
        vol_floor = float(_param(self.spec, "vol_floor", 0.7))

        def fn(df: pd.DataFrame) -> pd.Series:
            sup = sma(df["close"], ma)
            uptrend = df["close"] > sup
            # Pullback = down days; "shrinking" = low volume during the pullback.
            # We require a *recent* shrinking-volume pullback, NOT that the relaunch
            # day itself be low-volume (a relaunch normally comes on rising volume).
            down = df["close"].diff() < 0
            shrink = vol_ratio(df["volume"], 20) <= vol_floor
            recent_pullback = (
                (down & shrink).rolling(pullback_days, min_periods=1).max().fillna(0).astype(bool)
            )
            # Relaunch: today closes up (vs yesterday) and back above the support MA.
            relaunch = (df["close"] > df["close"].shift(1)) & (df["close"] > sup)
            return (uptrend & recent_pullback & relaunch).fillna(False)

        return _single_code(self.spec, fn, prices)


class LeaderFirstDownStrategy(ResearchStrategy):
    """龙头首阴: first down day after a strong uptrend (low-absorption dip-buy)."""

    spec = ResearchStrategySpec(
        name="leader_first_down",
        display_name="龙头首阴",
        category="strong",
        engine="event",
        universe="csi800",
        description="强趋势后首个阴线日低吸。日线近似（无分时），仅作研究。",
        data_fidelity="daily_approx",
        parameters={"ma": 20, "lookback": 10},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        ma = int(_param(self.spec, "ma", 20))
        lookback = int(_param(self.spec, "lookback", 10))

        def fn(df: pd.DataFrame) -> pd.Series:
            sup = sma(df["close"], ma)
            uptrend = df["close"] > sup
            up_count = (df["close"].diff() > 0).rolling(lookback).sum()
            was_up = up_count >= (lookback * 0.6)
            first_down = (df["close"] < df["close"].shift(1)) & (
                df["close"].shift(1) >= df["close"].shift(2)
            )
            return (uptrend & was_up & first_down).fillna(False)

        return _single_code(self.spec, fn, prices)


# --------------------------------------------------------------------------- #
# Batch 2 -- daily_approx modelling
# --------------------------------------------------------------------------- #
class ShrinkReversalStrategy(ResearchStrategy):
    """缩量反包: wash-out down day on shrinking volume, then bullish engulfing."""

    spec = ResearchStrategySpec(
        name="shrink_reversal",
        display_name="缩量反包",
        category="strong",
        engine="event",
        universe="csi800",
        description="洗盘缩量阴线后，次日反包阳线介入。日线近似。",
        data_fidelity="daily_approx",
        parameters={"vol_floor": 0.7},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        vol_floor = float(_param(self.spec, "vol_floor", 0.7))

        def fn(df: pd.DataFrame) -> pd.Series:
            # Wash-out day: a red bar on shrinking volume (the shake-out).
            wash = (df["close"] < df["open"]) & (vol_ratio(df["volume"], 20) <= vol_floor)
            # Bullish engulfing on the next bar: today's body fully covers
            # yesterday's body (close >= yesterday's open, open <= yesterday's
            # close). This is the standard engulfing definition -- no gap required,
            # which suits daily-approx research where intraday gaps are invisible.
            engulf = (
                (df["close"] > df["open"])  # today is a bullish bar
                & (df["close"] >= df["open"].shift(1))  # closes above prior open
                & (df["open"] <= df["close"].shift(1))  # opens below prior close
            )
            return (wash.shift(1).fillna(False) & engulf).fillna(False)

        return _single_code(self.spec, fn, prices)


class FirstBoardStrategy(ResearchStrategy):
    """首板: first limit-up after a non-limit day; study next-day open premium."""

    spec = ResearchStrategySpec(
        name="first_board",
        display_name="首板",
        category="emotion",
        engine="event",
        universe="all_a",
        description="涨停日判定（日线可判），研究次日开盘溢价。日线近似。",
        data_fidelity="daily_approx",
        parameters={"rate": LIMIT_UP_RATE},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        rate = float(_param(self.spec, "rate", LIMIT_UP_RATE))

        def fn(df: pd.DataFrame) -> pd.Series:
            prev_close = df["close"].shift(1)
            up = is_limit_up(df["close"], prev_close, rate)
            up_prev = up.shift(1).fillna(False)
            # NB: use .eq(False), not ~, because ~ on a pandas bool Series is a
            # bitwise op in pandas >=3.16 and would NOT negate logically.
            first = up & up_prev.eq(False)
            return first.fillna(False)

        return _single_code(self.spec, fn, prices)


class SecondBoardRelayStrategy(ResearchStrategy):
    """二板接力: buy on the 2nd consecutive limit-up day (relay)."""

    spec = ResearchStrategySpec(
        name="second_board_relay",
        display_name="二板接力",
        category="emotion",
        engine="event",
        universe="all_a",
        description="连板判定，次日接力收益（日线粒度）。",
        data_fidelity="daily_approx",
        parameters={"rate": LIMIT_UP_RATE},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        rate = float(_param(self.spec, "rate", LIMIT_UP_RATE))

        def fn(df: pd.DataFrame) -> pd.Series:
            prev_close = df["close"].shift(1)
            up = is_limit_up(df["close"], prev_close, rate)
            up_prev = up.shift(1).fillna(False)
            return (up & up_prev).fillna(False)

        return _single_code(self.spec, fn, prices)


# --------------------------------------------------------------------------- #
# Batch 3 -- lowest confidence (one advisory-only)
# --------------------------------------------------------------------------- #
class HighBoardStrategy(ResearchStrategy):
    """连板博弈: enter on the 3rd+ consecutive limit-up (height-board lifecycle).

    data_fidelity = needs_intraday: intraday timing of limit openings/closings is
    NOT modelled by daily bars, so this strategy's V1.0 conclusions are
    **advisory only** (frozen decision D3).
    """

    spec = ResearchStrategySpec(
        name="high_board",
        display_name="连板博弈",
        category="emotion",
        engine="event",
        universe="all_a",
        description="高度板生命周期——分时缺失，V1.0 标注仅供参考。",
        data_fidelity="needs_intraday",
        parameters={"rate": LIMIT_UP_RATE, "min_boards": 3},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        rate = float(_param(self.spec, "rate", LIMIT_UP_RATE))
        min_boards = int(_param(self.spec, "min_boards", 3))

        def fn(df: pd.DataFrame) -> pd.Series:
            prev_close = df["close"].shift(1)
            up = is_limit_up(df["close"], prev_close, rate)
            # Count consecutive limit-up days ending today.
            grp = (up != up.shift(1)).cumsum()
            streak = up.groupby(grp).cumsum()
            return (up & (streak >= min_boards)).fillna(False)

        return _single_code(self.spec, fn, prices)


class SentimentReboundStrategy(ResearchStrategy):
    """情绪冰点修复: extreme-fear wash-out followed by a reversal day.

    Per-code proxy when no breadth index is supplied; pass an ``index`` Series
    (e.g. 全A等权指数或跌停家数) to ``entry_signals`` via the prices dict under
    the reserved key ``"__index__"`` for true market-breadth detection (3.2).
    """

    spec = ResearchStrategySpec(
        name="sentiment_rebound",
        display_name="情绪冰点修复",
        category="emotion",
        engine="event",
        universe="all_a",
        description="极端情绪（超跌/冰点）后反弹。日线近似。",
        data_fidelity="daily_approx",
        parameters={"ma": 20, "drawdown": -0.15},
    )

    def entry_signals(self, prices: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        ma = int(_param(self.spec, "ma", 20))
        drawdown = float(_param(self.spec, "drawdown", -0.15))

        idx = prices.get("__index__")
        out: dict[str, pd.Series] = {}
        for code, df in prices.items():
            if code == "__index__":
                continue
            _require_cols(df)
            sup = sma(df["close"], ma)
            fear = (df["close"] < sup) & (
                df["close"] / df["close"].rolling(ma, min_periods=ma).max() - 1.0 <= drawdown
            )
            reversal = (df["close"] > df["open"]) & (df["close"] > df["close"].shift(1))
            out[code] = (fear & reversal).fillna(False)
        # When a breadth index is present, gate all names on a market-wide fear.
        if idx is not None and isinstance(idx, pd.Series) and not idx.empty:
            idx_fear = idx < sma(idx, ma)
            gated = {
                code: sig & idx_fear.reindex(sig.index).ffill().fillna(False)
                for code, sig in out.items()
            }
            return gated
        return out


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
STRATEGIES: dict[str, ResearchStrategy] = {}


def _register(strategy: ResearchStrategy) -> None:
    register_strategy(strategy.spec)
    STRATEGIES[strategy.spec.name] = strategy


_register(MaBullStrategy())
_register(HighBreakoutStrategy())
_register(VolumeBreakoutStrategy())
_register(StrongPullbackStrategy())
_register(LeaderFirstDownStrategy())
_register(ShrinkReversalStrategy())
_register(FirstBoardStrategy())
_register(SecondBoardRelayStrategy())
_register(HighBoardStrategy())
_register(SentimentReboundStrategy())


def get_strategy(name: str) -> ResearchStrategy:
    """Return a registered research strategy by name or raise KeyError."""
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy {name!r}; available: {sorted(STRATEGIES)}")
    return STRATEGIES[name]


def list_strategies() -> list[ResearchStrategy]:
    """All registered research strategies, sorted by name."""
    return [STRATEGIES[k] for k in sorted(STRATEGIES)]


# --------------------------------------------------------------------------- #
# Single-strategy runner (uniform V1.0 research via EventBacktest)
# --------------------------------------------------------------------------- #
def run_strategy(
    strategy: ResearchStrategy,
    prices: dict[str, pd.DataFrame],
    config: BacktestConfig,
    benchmark: pd.Series | None = None,
) -> EventResult:
    """Run one strategy through :class:`EventBacktest` for a comparable metric set.

    * ``engine == "event"`` -- uses the boolean ``entry_signals`` directly.
    * ``engine == "portfolio"`` -- selects the cross-sectional Top-N names each
      day from ``score()`` (the 3.2 BatchRunner performs the real monthly
      rebalance; this is the faithful single-strategy V1.0 approximation).
    """
    prices = _ensure_date_index(prices)

    if strategy.spec.engine == "portfolio":
        scores = strategy.score(prices)
        signals = _cross_section_top_n(scores, strategy.spec.risk_control.max_positions)
    else:
        signals = strategy.entry_signals(prices)

    eb = EventBacktest(
        config,
        stop_loss=strategy.spec.exit_rules.stop_loss,
        take_profit=strategy.spec.exit_rules.take_profit,
        max_holding_days=strategy.spec.exit_rules.max_holding_days,
        max_position_per_name=strategy.spec.risk_control.max_position_per_name,
        max_positions=strategy.spec.risk_control.max_positions,
    )
    return eb.run(signals, prices, benchmark)


def _cross_section_top_n(scores: dict[str, pd.Series], top_n: int) -> dict[str, pd.Series]:
    """Each day, mark the ``top_n`` names with the highest score as held."""
    if not scores:
        return {}
    common = pd.DatetimeIndex(sorted({ts for s in scores.values() for ts in s.index}))
    aligned = {c: s.reindex(common) for c, s in scores.items()}
    frame = pd.DataFrame(aligned)
    held = pd.DataFrame(index=common, columns=list(aligned), dtype=bool)
    for i in range(len(common)):
        row = frame.iloc[i]
        valid = row.dropna()
        if valid.empty:
            held.iloc[i] = False
            continue
        thr = valid.sort_values(ascending=False).index[:top_n]
        held.iloc[i] = frame.columns.isin(thr)
    return {c: held[c].fillna(False) for c in aligned}
