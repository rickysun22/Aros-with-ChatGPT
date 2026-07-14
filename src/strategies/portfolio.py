"""Portfolio: turn strategy signals into positions and track equity.

The Portfolio is the bridge between research (signals) and the future backtest
engine (Sprint 1.6). Given a frame that already carries a signal column (or any
signal_<name> column), it derives a target position per bar and marks the book
to market using close-to-close returns. Everything uses only data known at bar
t (the signal at t and the return realised from t to t+1), so it introduces no
look-ahead.
"""

from __future__ import annotations

import pandas as pd

from .signal import SignalType, to_position


class Portfolio:
    """Converts signals into positions and tracks equity (mark-to-market)."""

    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self.initial_cash = float(initial_cash)

    # ------------------------------------------------------------------ #
    # Position derivation
    # ------------------------------------------------------------------ #
    def positions(self, df: pd.DataFrame, signal_col: str = "signal") -> pd.Series:
        """Return the target position weight (float) per bar from signal_col.

        Unknown / NaN signals are treated as FLAT (0.0).
        """
        if signal_col not in df.columns:
            raise ValueError(f"Portfolio: missing signal column {signal_col!r}")
        sig = df[signal_col].map(lambda v: SignalType.coerce(v).value if pd.notna(v) else 0)
        return sig.map(to_position)

    # ------------------------------------------------------------------ #
    # Mark to market
    # ------------------------------------------------------------------ #
    def mark_to_market(self, df: pd.DataFrame, signal_col: str = "signal") -> pd.DataFrame:
        """Append position and equity columns to df.

        The position held at bar t earns the return from t to t+1 (realised on
        the next bar's close), which is exactly the no-look-ahead convention a
        backtester uses. equity starts at initial_cash.
        """
        out = df.copy()
        pos = self.positions(out, signal_col)
        out["position"] = pos
        # The position decided at bar t-1 is marked against the t->t+1 return.
        fwd_pos = pos.shift(1).fillna(0.0)
        ret = out["close"].pct_change().fillna(0.0)
        out["equity"] = self.initial_cash * (1.0 + (fwd_pos * ret).cumsum())
        return out
