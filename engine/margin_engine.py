"""
engine/margin_engine.py
───────────────────────
Real-Time SEBI 2026 Margin Engine & Expiry Day Extreme Loss Margin (ELM) Sentinel.

Implements the official SEBI F&O Framework & Clearing Corporation (NSE Clearing / ICCL)
margin constraints:
  1. Upfront Premium Mandate:
     - 100% upfront premium cash required for option buyers (intraday broker leverage is prohibited).
  2. Expiry Day Extreme Loss Margin (ELM):
     - Additional 2.0% Extreme Loss Margin on short option positions on expiry date:
       Additional ELM = 0.02 * (Spot Price * Quantity)
  3. Expiry Calendar Spread Margin Trap Detector:
     - Calendar spread margin relief is eliminated on expiry day for the expiring contract leg,
       spiking margin requirements to standalone unhedged levels.
  4. Pre-Trade Capital & Margin Solvency Gate:
     - Verifies broker available cash against Total Required Margin + Buffer before execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Any

from engine.charges import SegmentType, OrderSide

logger = logging.getLogger("engine.margin_engine")

# Canonical default baseline SPAN and Exposure percentages (NSE F&O averages)
DEFAULT_INDEX_SPAN_PCT: float = 0.10  # ~10% SPAN for Nifty/Sensex
DEFAULT_INDEX_EXPOSURE_PCT: float = 0.02  # 2% Exposure margin
DEFAULT_STOCK_SPAN_PCT: float = 0.15  # ~15% SPAN for F&O equities
DEFAULT_STOCK_EXPOSURE_PCT: float = 0.035  # 3.5% Exposure margin
SEBI_EXPIRY_ADDITIONAL_ELM_PCT: float = 0.02  # 2.0% additional ELM on expiry day


@dataclass
class MarginRequirement:
    """Detailed margin requirements for an order intent."""

    symbol: str
    segment: SegmentType
    side: OrderSide
    quantity: int
    price: float  # execution price or option premium
    underlying_spot: float
    notional_value: float  # underlying_spot * quantity
    upfront_premium: float  # cash needed for option buyers
    span_margin: float
    exposure_margin: float
    expiry_additional_elm: float  # SEBI 2% ELM on short options on expiry day
    total_margin_required: float
    is_expiry_day: bool
    is_short_option: bool
    is_calendar_spread_trap: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "segment": self.segment,
            "side": self.side,
            "quantity": self.quantity,
            "price": round(self.price, 2),
            "underlying_spot": round(self.underlying_spot, 2),
            "notional_value": round(self.notional_value, 2),
            "upfront_premium": round(self.upfront_premium, 2),
            "span_margin": round(self.span_margin, 2),
            "exposure_margin": round(self.exposure_margin, 2),
            "expiry_additional_elm": round(self.expiry_additional_elm, 2),
            "total_margin_required": round(self.total_margin_required, 2),
            "is_expiry_day": self.is_expiry_day,
            "is_short_option": self.is_short_option,
            "is_calendar_spread_trap": self.is_calendar_spread_trap,
            "warnings": self.warnings,
        }


def _is_index(clean_symbol: str) -> bool:
    """Check if the instrument is an index derivative."""
    idx_set = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}
    return any(clean_symbol.startswith(idx) for idx in idx_set)


def calculate_order_margin(
    symbol: str,
    price: float,
    quantity: int,
    segment: SegmentType,
    side: OrderSide,
    underlying_spot: Optional[float] = None,
    is_expiry_day: bool = False,
    is_calendar_spread: bool = False,
    custom_span_pct: Optional[float] = None,
) -> MarginRequirement:
    """
    Calculate statutory SEBI 2026 pre-trade margin requirement for an order.

    Args:
        symbol: Instrument symbol (e.g. 'NIFTY24OCT24500CE' or 'RELIANCE').
        price: Price per share or option contract premium.
        quantity: Total shares/contracts.
        segment: 'EQUITY_DELIVERY', 'EQUITY_INTRADAY', 'FUTURES', or 'OPTIONS'.
        side: 'BUY' or 'SELL'.
        underlying_spot: Spot price of the underlying asset (defaults to price if cash).
        is_expiry_day: True if today is the contract's expiration day.
        is_calendar_spread: True if the order forms part of a calendar spread.
        custom_span_pct: Optional override for broker-specific SPAN %.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    spot = float(underlying_spot if underlying_spot is not None and underlying_spot > 0 else price)
    notional = float(spot * quantity)
    warnings: list[str] = []

    upfront_premium = 0.0
    span_margin = 0.0
    exposure_margin = 0.0
    expiry_additional_elm = 0.0
    is_short_opt = False
    is_cal_trap = False

    # 1. Cash Equity Segments
    if segment == "EQUITY_DELIVERY":
        # 100% upfront delivery value
        upfront_premium = float(price * quantity)
        total_required = upfront_premium

    elif segment == "EQUITY_INTRADAY":
        # Standard MIS margin: ~20% (5x leverage)
        margin_pct = 0.20
        total_required = float(price * quantity * margin_pct)

    # 2. Futures Segment
    elif segment == "FUTURES":
        is_idx = _is_index(clean_sym)
        span_rate = custom_span_pct or (
            DEFAULT_INDEX_SPAN_PCT if is_idx else DEFAULT_STOCK_SPAN_PCT
        )
        expo_rate = DEFAULT_INDEX_EXPOSURE_PCT if is_idx else DEFAULT_STOCK_EXPOSURE_PCT

        span_margin = float(notional * span_rate)
        exposure_margin = float(notional * expo_rate)
        total_required = span_margin + exposure_margin

    # 3. Options Segment
    elif segment == "OPTIONS":
        if side == "BUY":
            # SEBI Rule: 100% upfront cash for option buyers, zero broker leverage
            upfront_premium = float(price * quantity)
            total_required = upfront_premium
        else:
            # Short Option Position: Requires SPAN + Exposure + Expiry ELM
            is_short_opt = True
            is_idx = _is_index(clean_sym)
            span_rate = custom_span_pct or (
                DEFAULT_INDEX_SPAN_PCT if is_idx else DEFAULT_STOCK_SPAN_PCT
            )
            expo_rate = DEFAULT_INDEX_EXPOSURE_PCT if is_idx else DEFAULT_STOCK_EXPOSURE_PCT

            span_margin = float(notional * span_rate)
            exposure_margin = float(notional * expo_rate)

            # SEBI 2026 Expiry Day Rule: +2.0% Extreme Loss Margin
            if is_expiry_day:
                expiry_additional_elm = float(notional * SEBI_EXPIRY_ADDITIONAL_ELM_PCT)
                warnings.append(
                    f"[SEBI 2026 Mandate] Expiry day 2.0% Extreme Loss Margin (ELM) applied: "
                    f"+₹{expiry_additional_elm:,.2f} on short notional ₹{notional:,.2f}."
                )

            # Calendar Spread Trap: Margin relief revoked on expiry day
            if is_calendar_spread and is_expiry_day:
                is_cal_trap = True
                warnings.append(
                    "[SEBI 2026 Calendar Spread Mandate] Calendar spread margin relief is REVOKED on expiry day "
                    "for expiring legs. Standalone unhedged margin is enforced."
                )

            total_required = span_margin + exposure_margin + expiry_additional_elm

    else:
        total_required = float(price * quantity)

    return MarginRequirement(
        symbol=symbol,
        segment=segment,
        side=side,
        quantity=quantity,
        price=price,
        underlying_spot=spot,
        notional_value=notional,
        upfront_premium=upfront_premium,
        span_margin=span_margin,
        exposure_margin=exposure_margin,
        expiry_additional_elm=expiry_additional_elm,
        total_margin_required=total_required,
        is_expiry_day=is_expiry_day,
        is_short_option=is_short_opt,
        is_calendar_spread_trap=is_cal_trap,
        warnings=warnings,
    )


def validate_margin_solvency(
    margin_req: MarginRequirement,
    available_cash: float,
    buffer_pct: float = 0.05,
) -> tuple[bool, str]:
    """
    Validate whether the trader's available broker cash satisfies the required margin
    plus a safety liquidity buffer (default 5%).

    Returns:
        (is_solvent, message)
    """
    min_required = margin_req.total_margin_required * (1.0 + buffer_pct)
    if available_cash >= min_required:
        return (
            True,
            f"Solvent: Available cash ₹{available_cash:,.2f} exceeds required margin ₹{margin_req.total_margin_required:,.2f} (with 5% buffer).",
        )

    shortfall = min_required - available_cash
    reason = (
        f"MARGIN SHORTFALL: Required capital ₹{min_required:,.2f} (including 5% safety buffer) "
        f"exceeds available cash ₹{available_cash:,.2f}. Deficit: ₹{shortfall:,.2f}."
    )
    if margin_req.expiry_additional_elm > 0:
        reason += f" Includes SEBI 2% Expiry ELM of ₹{margin_req.expiry_additional_elm:,.2f}."

    return (False, reason)
