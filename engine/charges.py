"""
engine/charges.py
─────────────────
Effective-dated Indian Market Transaction Cost Engine.

Calculates statutory taxes, exchange fees, SEBI turnover fees, stamp duty,
and brokerage charges across NSE/BSE Cash and NFO F&O segments.

Used identically across:
  - Pre-order tickets & margin calculations
  - Paper trading simulation
  - Backtesting engines (vectorized & event-driven)
  - Post-trade reconciliation & P&L accounting

Statutory Rates (Effective 2024-2026 Union Budget / SEBI schedules):
  - STT:
      • Equity Delivery : 0.1% on Buy and Sell turnover
      • Equity Intraday : 0.025% on Sell turnover
      • Futures         : 0.02% on Sell turnover
      • Options         : 0.1% (or 0.125% for exercised contracts) on Sell premium turnover
  - Exchange Turnover Charges:
      • NSE Cash        : 0.00297% (₹297 / crore)
      • NSE Futures     : 0.00173% (₹173 / crore)
      • NSE Options     : 0.03503% (on premium turnover)
  - GST: 18% on (Brokerage + Exchange Turnover Charges)
  - SEBI Turnover Fee : ₹10 / crore (0.0001%) on turnover
  - Stamp Duty (Buy side only):
      • Equity Delivery : 0.015% (₹1,500 / crore)
      • Equity Intraday : 0.003% (₹300 / crore)
      • Futures         : 0.002% (₹200 / crore)
      • Options         : 0.003% (₹300 / crore on premium)
  - Brokerage: Default discount model (₹20 flat or 0.03%, ₹0 for delivery).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Dict, Any

SegmentType = Literal["EQUITY_DELIVERY", "EQUITY_INTRADAY", "FUTURES", "OPTIONS"]
OrderSide = Literal["BUY", "SELL"]


@dataclass
class TransactionCostBreakdown:
    """Detailed statutory and broker cost breakdown for an Indian market order."""

    segment: SegmentType
    side: OrderSide
    notional_turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_charges: Decimal
    gst: Decimal
    stamp_duty: Decimal
    sebi_charges: Decimal
    total_charges: Decimal
    effective_pct: Decimal  # total charges as % of turnover

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment": self.segment,
            "side": self.side,
            "notional_turnover": float(self.notional_turnover),
            "brokerage": float(self.brokerage),
            "stt": float(self.stt),
            "exchange_charges": float(self.exchange_charges),
            "gst": float(self.gst),
            "stamp_duty": float(self.stamp_duty),
            "sebi_charges": float(self.sebi_charges),
            "total_charges": float(self.total_charges),
            "effective_pct": float(self.effective_pct),
        }


def _round_currency(val: Decimal | float) -> Decimal:
    """Round to 2 decimal places (paisa)."""
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_transaction_charges(
    price: float | Decimal,
    quantity: int,
    segment: SegmentType = "EQUITY_DELIVERY",
    side: OrderSide = "BUY",
    brokerage_rate: float | None = None,  # None = use standard discount defaults
    broker_flat_fee: float = 20.0,
) -> TransactionCostBreakdown:
    """
    Calculate full statutory Indian transaction costs for an order leg.

    Args:
        price: Price per share/contract (or option premium).
        quantity: Total quantity (shares or contracts).
        segment: EQUITY_DELIVERY, EQUITY_INTRADAY, FUTURES, or OPTIONS.
        side: BUY or SELL.
        brokerage_rate: Custom brokerage % (if variable).
        broker_flat_fee: Flat max brokerage fee (default ₹20).

    Returns:
        TransactionCostBreakdown dataclass with all individual line items.
    """
    p = Decimal(str(price))
    q = Decimal(str(abs(quantity)))
    turnover = p * q

    if turnover <= Decimal("0"):
        return TransactionCostBreakdown(
            segment=segment,
            side=side,
            notional_turnover=Decimal("0.00"),
            brokerage=Decimal("0.00"),
            stt=Decimal("0.00"),
            exchange_charges=Decimal("0.00"),
            gst=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            sebi_charges=Decimal("0.00"),
            total_charges=Decimal("0.00"),
            effective_pct=Decimal("0.00"),
        )

    # 1. Brokerage calculation
    if segment == "EQUITY_DELIVERY":
        # Zero brokerage for delivery or max ₹20 depending on broker plan
        if brokerage_rate is not None:
            brokerage = min(turnover * Decimal(str(brokerage_rate)), Decimal(str(broker_flat_fee)))
        else:
            brokerage = Decimal("0.00")
    else:
        # Intraday & F&O: 0.03% or flat ₹20 whichever is lower
        rate = Decimal("0.0003") if brokerage_rate is None else Decimal(str(brokerage_rate))
        brokerage = min(turnover * rate, Decimal(str(broker_flat_fee)))

    # 2. Securities Transaction Tax (STT)
    stt = Decimal("0.00")
    if segment == "EQUITY_DELIVERY":
        # 0.1% on both Buy and Sell
        stt = turnover * Decimal("0.001")
    elif segment == "EQUITY_INTRADAY":
        # 0.025% on Sell only
        if side == "SELL":
            stt = turnover * Decimal("0.00025")
    elif segment == "FUTURES":
        # 0.02% on Sell only
        if side == "SELL":
            stt = turnover * Decimal("0.0002")
    elif segment == "OPTIONS":
        # 0.1% on Sell premium turnover
        if side == "SELL":
            stt = turnover * Decimal("0.001")

    # 3. Exchange Turnover Charges (NSE rates)
    if segment in ("EQUITY_DELIVERY", "EQUITY_INTRADAY"):
        exchange_charges = turnover * Decimal("0.0000297")  # 0.00297%
    elif segment == "FUTURES":
        exchange_charges = turnover * Decimal("0.0000173")  # 0.00173%
    elif segment == "OPTIONS":
        exchange_charges = turnover * Decimal("0.0003503")  # 0.03503% on premium

    # 4. GST (18% on Brokerage + Exchange Charges)
    gst = (brokerage + exchange_charges) * Decimal("0.18")

    # 5. Stamp Duty (Buy side only)
    stamp_duty = Decimal("0.00")
    if side == "BUY":
        if segment == "EQUITY_DELIVERY":
            stamp_duty = turnover * Decimal("0.00015")  # 0.015%
        elif segment == "EQUITY_INTRADAY":
            stamp_duty = turnover * Decimal("0.00003")  # 0.003%
        elif segment == "FUTURES":
            stamp_duty = turnover * Decimal("0.00002")  # 0.002%
        elif segment == "OPTIONS":
            stamp_duty = turnover * Decimal("0.00003")  # 0.003% on premium

    # 6. SEBI Turnover Charges (₹10 / crore = 0.0001%)
    sebi_charges = turnover * Decimal("0.000001")

    # Quantize line items to ₹0.01
    b_rounded = _round_currency(brokerage)
    stt_rounded = _round_currency(stt)
    ex_rounded = _round_currency(exchange_charges)
    gst_rounded = _round_currency(gst)
    sd_rounded = _round_currency(stamp_duty)
    sebi_rounded = _round_currency(sebi_charges)

    total = b_rounded + stt_rounded + ex_rounded + gst_rounded + sd_rounded + sebi_rounded
    effective_pct = _round_currency((total / turnover) * Decimal("100")) if turnover > Decimal("0") else Decimal("0.00")

    return TransactionCostBreakdown(
        segment=segment,
        side=side,
        notional_turnover=_round_currency(turnover),
        brokerage=b_rounded,
        stt=stt_rounded,
        exchange_charges=ex_rounded,
        gst=gst_rounded,
        stamp_duty=sd_rounded,
        sebi_charges=sebi_rounded,
        total_charges=_round_currency(total),
        effective_pct=effective_pct,
    )
