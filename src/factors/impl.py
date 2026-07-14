"""Concrete A-share short-term factors.

Each factor consumes indicator columns (produced by the indicator layer) and/or
raw bars, and emits a research signal. Every factor is **causal**: a factor
value at bar *t* depends only on data at bars ``<= t`` (it uses rolling means,
shifts and element-wise arithmetic -- never a look-ahead). The truncation test
in the test-suite proves it.

A factor reads its inputs by name from the frame. If a required indicator
column is missing (e.g. the factor was configured but the indicator that
produces it was not), :class:`~core.exceptions.DataError` is raised so the
misconfiguration is caught immediately.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import DataError

from .base import BaseFactor, register


def _require(df: pd.DataFrame, col: str, factor_name: str) -> None:
    """Raise :class:`DataError` if *col* is absent from *df*."""
    if col not in df.columns:
        raise DataError(f"Factor {factor_name!r} requires indicator column {col!r}")


@register("ma_distance")
class MADistanceFactor(BaseFactor):
    """(close - MA) / MA * 100 -- distance of price from its moving average."""

    name = "ma_distance"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 20))
        col = f"ma_{window}"
        _require(df, col, self.name)
        ma = df[col].replace(0.0, float("nan"))
        return {f"ma_dist_{window}": (df["close"] - ma) / ma * 100.0}


@register("ma_cross")
class MACrossFactor(BaseFactor):
    """Sign of (fast MA - slow MA): +1 bullish, -1 bearish, 0 flat."""

    name = "ma_cross"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        fast = int(self.params.get("fast", 5))
        slow = int(self.params.get("slow", 20))
        fcol, scol = f"ma_{fast}", f"ma_{slow}"
        _require(df, fcol, self.name)
        _require(df, scol, self.name)
        diff = df[fcol] - df[scol]
        return {f"ma_cross_{fast}_{slow}": (diff > 0).astype(int) - (diff < 0).astype(int)}


@register("rsi_signal")
class RSISignalFactor(BaseFactor):
    """Categorical RSI zone: +1 overbought (>=upper), -1 oversold (<=lower), 0."""

    name = "rsi_signal"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 14))
        lower = float(self.params.get("lower", 30))
        upper = float(self.params.get("upper", 70))
        col = f"rsi_{window}"
        _require(df, col, self.name)
        rsi = df[col]
        return {f"rsi_signal_{window}": (rsi > upper).astype(int) - (rsi < lower).astype(int)}


@register("macd_cross")
class MACDCrossFactor(BaseFactor):
    """Sign of (MACD - signal): +1 bullish cross, -1 bearish cross, 0 flat."""

    name = "macd_cross"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        _require(df, "macd", self.name)
        _require(df, "macd_signal", self.name)
        diff = df["macd"] - df["macd_signal"]
        return {"macd_cross": (diff > 0).astype(int) - (diff < 0).astype(int)}


@register("kdj_cross")
class KDJCrossFactor(BaseFactor):
    """Sign of (K - D): +1 golden cross, -1 death cross, 0 flat."""

    name = "kdj_cross"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        _require(df, "kdj_k", self.name)
        _require(df, "kdj_d", self.name)
        diff = df["kdj_k"] - df["kdj_d"]
        return {"kdj_cross": (diff > 0).astype(int) - (diff < 0).astype(int)}


@register("vol_ratio")
class VolRatioFactor(BaseFactor):
    """Current volume / volume MA -- volume amplification vs its baseline."""

    name = "vol_ratio"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 5))
        col = f"vol_ma_{window}"
        _require(df, col, self.name)
        vma = df[col].replace(0.0, float("nan"))
        return {f"vol_ratio_{window}": df["volume"] / vma}


@register("boll_position")
class BollPositionFactor(BaseFactor):
    """Position of close within the Bollinger band, clipped to [0, 1]."""

    name = "boll_position"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 20))
        lcol, ucol = f"boll_lower_{window}", f"boll_upper_{window}"
        _require(df, lcol, self.name)
        _require(df, ucol, self.name)
        lower, upper = df[lcol], df[ucol]
        width = (upper - lower).replace(0.0, float("nan"))
        pos = (df["close"] - lower) / width
        return {f"boll_pos_{window}": pos.clip(lower=0.0, upper=1.0)}


@register("momentum")
class MomentumFactor(BaseFactor):
    """Close-to-close return over ``window`` bars: close / close[shift] - 1."""

    name = "momentum"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 5))
        prev = df["close"].shift(window).replace(0.0, float("nan"))
        return {f"mom_{window}": df["close"] / prev - 1.0}
