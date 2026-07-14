"""A-share transaction cost model (Sprint 1.6).

Costs are charged per side (each rebalance is one side: a buy or a sell).
All rates are configurable via :class:`~core.config.CostConfig` so a change in
broker fees never requires code changes.

The cost of a trade depends on its ``notional`` -- the traded dollar amount
(``|delta weight| * equity`` at trade time). This is the dimensionally correct
form; the design note's literal ``price * equity`` product was a typo and is
not used here.
"""

from __future__ import annotations


class CostModel:
    """Computes the transaction cost (yuan) for a single trade."""

    def __init__(
        self,
        commission_rate: float = 0.00025,
        commission_min: float = 5.0,
        stamp_tax_rate: float = 0.0005,
        transfer_fee_rate: float = 0.00001,
        slippage: float = 0.0,
    ) -> None:
        self.commission_rate = float(commission_rate)
        self.commission_min = float(commission_min)
        self.stamp_tax_rate = float(stamp_tax_rate)
        self.transfer_fee_rate = float(transfer_fee_rate)
        self.slippage = float(slippage)

    def charge(self, notional: float, is_sell: bool = False) -> float:
        """Return the total cost (yuan) for a trade of ``notional`` yuan.

        Commission applies to both sides with a per-trade minimum; the stamp
        tax is charged only on sells; the transfer fee and slippage apply on
        both sides.
        """
        notional = abs(float(notional))
        commission = max(self.commission_rate * notional, self.commission_min)
        stamp = self.stamp_tax_rate * notional if is_sell else 0.0
        transfer = self.transfer_fee_rate * notional
        slip = self.slippage * notional
        return commission + stamp + transfer + slip
