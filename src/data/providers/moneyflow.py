"""Phase 4.3 Market Context & Money Flow providers (design §5 4.3 / §6).

Real, akshare-backed implementations of the money-flow / hidden-flow provider
contracts defined in ``research.consensus``:

* :class:`AkShareMoneyFlowProvider` -> ``get_stock_flow(code)`` returns a
  :class:`MoneyFlowSignal` (``sector_score`` + ``public_money_score``), derived
  from akshare individual-stock + industry fund flow.
* :class:`AkShareHiddenFlowProvider` -> ``infer(code)`` returns a
  :class:`HiddenFlowSignal` (``score`` + ``explanation``) from a *behavioural*
  inference over recent price + fund-flow — **never a fabricated amount**
  (v2 red line: 不伪造暗盘资金金额).

Both providers are defensive: every external fetch is wrapped so that any
network error, rate-limit, or column drift degrades to a **neutral** signal
(50) rather than breaking the daily screening run. This keeps Sprint 4.2's
offline-testable property and the AROS constitution ("暗盘永不淘汰候选").

The scoring math is factored into pure module-level functions so it can be unit
tested with synthetic DataFrames, no network, no database.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pandas as pd

from research.consensus import HiddenFlowSignal, MoneyFlowSignal

# --------------------------------------------------------------------------- #
# Pure scoring math (unit-testable, no network / DB)
# --------------------------------------------------------------------------- #


def _sigmoid_score(x: float, scale: float = 3.0) -> float:
    """Map a signed percentage (e.g. main-net-inflow %) to 0-100 around 50."""
    try:
        return float(50.0 + 50.0 * math.tanh(x / scale))
    except (ValueError, OverflowError):
        return 50.0


def public_money_score(main_net_pct: float | None) -> float:
    """0-100 public money-flow score from the recent main-net-inflow %.

    Positive net inflow -> above 50; negative -> below 50. Returns 50 (neutral)
    when the input is missing or non-finite.
    """
    if main_net_pct is None or not math.isfinite(main_net_pct):
        return 50.0
    return _sigmoid_score(main_net_pct)


def sector_score(stock_net_pct: float | None, sector_net_pct: float | None) -> float:
    """0-100 relative-strength score of a stock vs its sector.

    The stock's main-net-inflow % minus the sector's; positive -> above 50.
    Missing sector data degrades gracefully to the stock's own absolute score
    (no relative view available).
    """
    if stock_net_pct is None or not math.isfinite(stock_net_pct):
        return 50.0
    if sector_net_pct is None or not math.isfinite(sector_net_pct):
        return _sigmoid_score(stock_net_pct)
    return _sigmoid_score(stock_net_pct - sector_net_pct)


def hidden_flow_infer(prices: pd.DataFrame | None, flow_pct: float | None) -> tuple[float, str]:
    """Behavioural-inference (score, explanation) of hidden / smart money.

    Pure function over recent OHLCV + the stock's recent main-net-inflow %.
    No amount is ever produced — only a 0-100 behavioural score and a rationale
    string. This is the "暗盘仅作行为推断" contract from the design.
    """
    if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
        return 50.0, "无价格数据，取中性分(行为推断不可得)"
    if "close" not in prices.columns:
        return 50.0, "价格序列缺少 close，取中性分(行为推断不可得)"

    close = pd.to_numeric(prices["close"], errors="coerce").dropna()
    vol = (
        pd.to_numeric(prices["volume"], errors="coerce").dropna()
        if "volume" in prices.columns
        else pd.Series(dtype=float)
    )
    if close.empty or len(close) < 12:
        return 50.0, "价格序列过短，取中性分(行为推断不可得)"

    rets = close.pct_change()
    n = 10 if len(close) >= 20 else len(close) // 2
    n = max(1, n)

    recent_close = close.tail(n)
    prior_close = close.iloc[:-n].tail(n) if len(close) > n else recent_close
    base = float(prior_close.iloc[0]) if len(prior_close) else float(recent_close.iloc[0])
    recent_ret = (float(recent_close.iloc[-1]) / base - 1.0) if base else 0.0

    recent_vol = vol.tail(n)
    prior_vol = vol.iloc[:-n].tail(n) if len(vol) > n else recent_vol
    prior_mean = float(prior_vol.mean()) if not prior_vol.empty else 0.0
    vol_ratio = float(recent_vol.mean()) / prior_mean if prior_mean > 0 else 1.0

    price_vol = rets.tail(n).std()
    price_vol = 0.0 if price_vol is None or math.isnan(price_vol) else float(price_vol)

    score = 50.0
    reasons: list[str] = []

    # 1) Low price volatility => a base is being built (constructive).
    if price_vol < 0.015:
        score += 8.0
        reasons.append("低波动横盘(构筑基底)")

    # 2) Volume pickup on a flat/down tape with net inflow => quiet accumulation.
    if vol_ratio > 1.2 and abs(recent_ret) < 0.03:
        if flow_pct is not None and flow_pct > 0:
            score += min(25.0, 8.0 + flow_pct * 3.0)
            reasons.append(f"放量横盘且主力净流入{flow_pct:.1f}%→潜在承接吸筹")
        else:
            score += 6.0
            reasons.append("放量横盘(资金异动但流向不明)")

    # 3) Up on rising volume but main outflow => distribution risk.
    if recent_ret > 0.06 and vol_ratio > 1.25 and (flow_pct is None or flow_pct < 0):
        score -= 28.0
        reasons.append("高位放量上涨却主力净流出→疑似派发")

    # 4) Down on rising volume => selling pressure.
    if recent_ret < -0.05 and vol_ratio > 1.25:
        score -= 18.0
        reasons.append("下跌放量→抛压/出货迹象")

    # 5) Mild net inflow without red flags => modestly constructive.
    if flow_pct is not None and 0 < flow_pct <= 3 and abs(recent_ret) < 0.06:
        score += 6.0
        reasons.append(f"温和主力流入{flow_pct:.1f}%→中性偏积极")

    score = max(0.0, min(100.0, score))
    if not reasons:
        explanation = "暂无明确暗盘行为信号(基于量价行为推断，非金额)"
    else:
        explanation = "；".join(reasons) + "（行为推断，非金额）"
    return score, explanation


# --------------------------------------------------------------------------- #
# Column-resolution helpers (akshare column drift, see data/provider.py)
# --------------------------------------------------------------------------- #


def _col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first present column name from ``candidates``."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _recent_net_pct(raw: pd.DataFrame | None, window: int = 5) -> float | None:
    """Mean of the last ``window`` rows' main-net-inflow % (or None)."""
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return None
    col = _col(raw, "主力净流入-净占比", "main_net_pct_inflow", "主力净流入净占比")
    if col is None:
        return None
    s = pd.to_numeric(raw[col], errors="coerce").dropna().tail(window)
    if s.empty:
        return None
    return float(s.mean())


def _market_of(code: str) -> str:
    """Map an A-share code to its akshare market prefix (sh/sz/bj)."""
    c = code.strip()
    if c.startswith(("8", "4")):
        return "bj"
    if c.startswith(("6", "9", "5")):
        return "sh"
    return "sz"


# --------------------------------------------------------------------------- #
# akshare wrappers (lazy import so the module never needs network at import)
# --------------------------------------------------------------------------- #


def _ak_individual_flow(code: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_individual_fund_flow(stock=code, market=_market_of(code))


def _ak_industry_of(code: str) -> str | None:
    import akshare as ak

    raw = ak.stock_individual_info_em(symbol=code)
    if raw is None or raw.empty or raw.shape[1] < 2:
        return None
    items = raw.iloc[:, 0].astype(str).str.strip()
    mask = items == "行业"
    if not mask.any():
        return None
    val = raw.iloc[:, 1][mask].iloc[0]
    return str(val).strip() or None


def _ak_industry_flow(industry: str) -> float | None:
    import akshare as ak

    raw = ak.stock_board_industry_rank_em()
    if raw is None or raw.empty:
        return None
    name_col = _col(raw, "行业", "name", "industry")
    pct_col = _col(raw, "主力净流入-净占比", "main_net_pct_inflow", "主力净流入净占比")
    if name_col is None or pct_col is None:
        return None
    match = raw[raw[name_col].astype(str).str.strip() == industry]
    if match.empty:
        return None
    return float(pd.to_numeric(match.iloc[0][pct_col], errors="coerce"))


def _ak_daily_bars(code: str) -> pd.DataFrame:
    """Recent qfq daily OHLCV for behavioural inference (no future leakage)."""
    import akshare as ak

    raw = ak.stock_zh_a_hist(stock=code, period="daily", adjust="qfq")
    if raw is None or raw.empty:
        return pd.DataFrame()
    from data.provider import _DAILY_CANON

    rename: dict[str, str] = {}
    for canon, cands in _DAILY_CANON.items():
        found = next((c for c in cands if c in raw.columns), None)
        if found:
            rename[found] = canon
    return raw.rename(columns=rename)


# --------------------------------------------------------------------------- #
# Concrete providers (Sprint 4.3)
# --------------------------------------------------------------------------- #


class AkShareMoneyFlowProvider:
    """Public money-flow + sector-strength provider backed by akshare.

    Implements the ``MoneyFlowProvider`` contract (``get_stock_flow``). Every
    external fetch is guarded: on any failure the provider returns a *neutral*
    signal (50, 50) so the daily screening run never aborts.
    """

    def __init__(
        self,
        flow_fn: Callable[[str], pd.DataFrame] | None = None,
        industry_fn: Callable[[str], str | None] | None = None,
        sector_flow_fn: Callable[[str], float | None] | None = None,
    ) -> None:
        self._flow_fn = flow_fn or _ak_individual_flow
        self._industry_fn = industry_fn or _ak_industry_of
        self._sector_flow_fn = sector_flow_fn or _ak_industry_flow

    def get_stock_flow(self, code: str) -> MoneyFlowSignal:
        try:
            raw = self._flow_fn(code)
            net_pct = _recent_net_pct(raw)
            public = public_money_score(net_pct)
            industry = self._industry_fn(code)
            sector = 50.0
            if industry:
                sector = sector_score(net_pct, self._sector_flow_fn(industry))
            return MoneyFlowSignal(sector_score=sector, public_money_score=public)
        except Exception:
            return MoneyFlowSignal(sector_score=50.0, public_money_score=50.0)

    # Design §6 extras (not required by the engine contract, but reusable).
    def get_industry_concept(self, code: str) -> tuple[str, str, list[str]]:
        """Return ``(industry, concept, concept_list)`` — concept is best-effort."""
        try:
            industry = self._industry_fn(code)
            return (industry or "", "", [])
        except Exception:
            return ("", "", [])

    def get_sector_flow(self, industry: str) -> float | None:
        """Return the sector's recent main-net-inflow % (or None)."""
        try:
            return self._sector_flow_fn(industry)
        except Exception:
            return None


class AkShareHiddenFlowProvider:
    """Behavioural-inference provider for hidden / smart money (no amount).

    Implements the ``HiddenFlowProvider`` contract (``infer``). Returns a
    :class:`HiddenFlowSignal` with a 0-100 score + a Chinese explanation; never
    a fabricated monetary amount. Degrades to neutral (50) on any failure.
    """

    def __init__(
        self,
        price_fn: Callable[[str], pd.DataFrame] | None = None,
        flow_fn: Callable[[str], pd.DataFrame] | None = None,
    ) -> None:
        self._price_fn = price_fn or _ak_daily_bars
        self._flow_fn = flow_fn or _ak_individual_flow

    def infer(self, code: str) -> HiddenFlowSignal:
        try:
            prices = self._price_fn(code)
            net_pct = _recent_net_pct(self._flow_fn(code))
            score, explanation = hidden_flow_infer(prices, net_pct)
            return HiddenFlowSignal(score=score, explanation=explanation)
        except Exception:
            return HiddenFlowSignal(
                score=50.0,
                explanation="暗盘数据不可得(网络/接口异常)，取中性分；不淘汰候选(行为推断)",
            )
