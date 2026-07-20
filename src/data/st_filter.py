"""Data-quality gate: hard-exclude ST / *ST (special-treatment) A-share stocks.

ST and *ST names carry a 5% daily limit (vs 10% / 20% on normal boards),
elevated delisting risk, and frequent suspension / illiquidity, so they are
excluded from every tradable universe as a hard gate — independent of the
AROS scoring layers. Detection keys off the stock ``name`` prefix, which the
EastMoney / AKShare list feeds store verbatim (e.g. ``"ST 某某"``,
``"*ST 某某"``).
"""

from __future__ import annotations

import pandas as pd

# Both the "ST" (special treatment) and "*ST" (delisting-risk warning) prefixes.
ST_PREFIXES: tuple[str, ...] = ("ST", "*ST")


def is_st_name(name: str | None) -> bool:
    """Return ``True`` if *name* denotes an ST / *ST stock."""
    if not name:
        return False
    return str(name).strip().upper().startswith(ST_PREFIXES)


def filter_st_codes(
    df: pd.DataFrame,
    code_col: str = "code",
    name_col: str = "name",
) -> pd.DataFrame:
    """Return ``df`` with ST / *ST rows removed (data-quality hard gate).

    Defensive: if ``name_col`` is absent the frame is returned unchanged so a
    caller that only carries codes is never silently emptied.
    """
    if df.empty or code_col not in df.columns:
        return df
    if name_col not in df.columns:
        return df
    mask = df[name_col].astype(str).str.upper().str.startswith(ST_PREFIXES)
    return df.loc[~mask].copy()
