"""Concrete A-share short-term indicators.

All indicators only look at data up to the current bar (rolling windows, EMA
recursions, min/max over trailing windows). None of them peek into the future,
so they are safe to use for signal generation.

Every parameter is read from ``self.params`` so the same indicator can be
instantiated with different windows/smoothing from configuration alone.
"""

from __future__ import annotations

import pandas as pd

from .base import BaseIndicator, register


@register("ma")
class MAIndicator(BaseIndicator):
    """Simple moving average of close over ``window`` bars."""

    name = "ma"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 5))
        col = f"ma_{window}"
        return {col: df["close"].rolling(window, min_periods=window).mean()}


@register("ema")
class EMAIndicator(BaseIndicator):
    """Exponential moving average of close (trading-style, ``adjust=False``)."""

    name = "ema"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 12))
        col = f"ema_{window}"
        # adjust=False => purely recursive over past data (causal).
        return {col: df["close"].ewm(span=window, adjust=False).mean()}


@register("rsi")
class RSIIndicator(BaseIndicator):
    """Relative Strength Index over ``window`` bars (Wilder smoothing)."""

    name = "rsi"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 14))
        delta = df["close"].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
        avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # Edge cases only where the averages are defined (warm-up stays NaN).
        valid = avg_gain.notna() & avg_loss.notna()
        no_loss = valid & (avg_loss == 0) & (avg_gain > 0)
        flat = valid & (avg_gain == 0) & (avg_loss == 0)
        rsi = rsi.where(~no_loss, 100.0)
        rsi = rsi.where(~flat, 0.0)
        return {f"rsi_{window}": rsi}


@register("macd")
class MACDIndicator(BaseIndicator):
    """MACD line, signal line and histogram.

    Params: ``fast`` (default 12), ``slow`` (default 26), ``signal`` (default 9).
    """

    name = "macd"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        fast = int(self.params.get("fast", 12))
        slow = int(self.params.get("slow", 26))
        signal = int(self.params.get("signal", 9))
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        macd_hist = macd - macd_signal
        return {"macd": macd, "macd_signal": macd_signal, "macd_hist": macd_hist}


@register("kdj")
class KDJIndicator(BaseIndicator):
    """KDJ stochastic indicator.

    Params: ``n`` (default 9, RSV window), ``m1`` (default 3, K smoothing),
    ``m2`` (default 3, D smoothing). Produces ``kdj_k``, ``kdj_d``, ``kdj_j``.
    """

    name = "kdj"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        n = int(self.params.get("n", 9))
        m1 = int(self.params.get("m1", 3))
        m2 = int(self.params.get("m2", 3))
        low_n = df["low"].rolling(n, min_periods=n).min()
        high_n = df["high"].rolling(n, min_periods=n).max()
        rsv = (df["close"] - low_n) / (high_n - low_n) * 100.0
        # Flat range (high == low) -> neutral RSV of 50.
        rsv = rsv.where(high_n != low_n, 50.0)
        # K/D use SMA-style smoothing = EMA with alpha = 1/m (causal).
        k = rsv.ewm(alpha=1.0 / m1, adjust=False, min_periods=m1).mean()
        d = k.ewm(alpha=1.0 / m2, adjust=False, min_periods=m2).mean()
        j = 3.0 * k - 2.0 * d
        return {"kdj_k": k, "kdj_d": d, "kdj_j": j}


@register("boll")
class BOLLIndicator(BaseIndicator):
    """Bollinger Bands around the close.

    Params: ``window`` (default 20), ``num_std`` (default 2.0). Produces
    ``boll_mid_{window}``, ``boll_upper_{window}``, ``boll_lower_{window}``.
    """

    name = "boll"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 20))
        num_std = float(self.params.get("num_std", 2.0))
        mid = df["close"].rolling(window, min_periods=window).mean()
        std = df["close"].rolling(window, min_periods=window).std(ddof=0)
        upper = mid + num_std * std
        lower = mid - num_std * std
        return {
            f"boll_mid_{window}": mid,
            f"boll_upper_{window}": upper,
            f"boll_lower_{window}": lower,
        }


@register("vol_ma")
class VOLMAIndicator(BaseIndicator):
    """Simple moving average of volume over ``window`` bars."""

    name = "vol_ma"

    def _series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        window = int(self.params.get("window", 5))
        col = f"vol_ma_{window}"
        return {col: df["volume"].rolling(window, min_periods=window).mean()}
