"""
engine/eod_rebalancer.py — Institutional SEBI Physical Delivery Risk Sentinel & MOC Guardian

Implements institutional compliance and risk management for Indian Markets:
  1. SEBI Mandatory Physical Delivery Audit:
     - Mandates physical delivery for in-the-money (ITM) and near-the-money stock derivatives.
     - Cash-settled Index options (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, etc.) are EXEMPT.
     - Escalating delivery margin schedule in expiry week (T-4: 20%, T-3: 40%, T-2: 60%, T-1: 80%, T-0: 100%).
     - Issues timely Rollover / Square-off directives before broker RMS liquidation.
  2. Market-On-Close (MOC 15:15–15:30 IST) Guardian:
     - Scans open intraday (MIS) positions.
     - Performs orderly execution before 15:20 IST broker auto-square-off cutoff, avoiding RMS penalty fees.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

from config.constants import (
    BANKNIFTY_LOT_SIZE,
    FINNIFTY_LOT_SIZE,
    IST,
    MIDCPNIFTY_LOT_SIZE,
    NIFTY_LOT_SIZE,
    SENSEX_LOT_SIZE,
)

INDEX_LOT_SIZES: dict[str, int] = {
    "NIFTY": NIFTY_LOT_SIZE,
    "BANKNIFTY": BANKNIFTY_LOT_SIZE,
    "FINNIFTY": FINNIFTY_LOT_SIZE,
    "MIDCPNIFTY": MIDCPNIFTY_LOT_SIZE,
    "SENSEX": SENSEX_LOT_SIZE,
}

logger = logging.getLogger(__name__)

# Excluded index underlyings (100% Cash-Settled per SEBI regulations)
CASH_SETTLED_INDICES = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "SENSEX",
    "BANKEX",
}


@dataclass
class DeliveryRiskAssessment:
    symbol: str
    underlying: str
    instrument_type: str  # CE, PE, FUT
    strike: float
    spot_price: float
    quantity: int
    lot_size: int
    days_to_expiry: int
    moneyness: str  # ITM, ATM, OTM
    moneyness_pct: float
    delivery_obligation_value: float
    required_margin_rate_pct: float
    required_margin_inr: float
    risk_level: str  # CRITICAL_DELIVERY_RISK, ELEVATED_MARGIN, LOW_RISK, EXEMPT
    actionable_directive: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MOCGuardianReport:
    timestamp: str
    session_status: str  # PRE_MOC, MOC_ACTIVE, POST_MOC
    total_positions_audited: int
    intraday_positions_pending_close: int
    physical_delivery_risks_detected: int
    delivery_risk_items: list[dict[str, Any]]
    action_items: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_cash_settled_index(symbol_or_underlying: str) -> bool:
    """Returns True if the underlying is an exempt cash-settled index."""
    clean = (
        symbol_or_underlying.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .strip()
    )
    for idx in CASH_SETTLED_INDICES:
        if clean.startswith(idx):
            return True
    return False


def calculate_delivery_margin_rate(days_to_expiry: int) -> float:
    """
    SEBI mandatory delivery margin progression in expiry week:
      T-4: 20%
      T-3: 40%
      T-2: 60%
      T-1: 80%
      T-0 (Expiry Day): 100%
    """
    if days_to_expiry <= 0:
        return 100.0
    elif days_to_expiry == 1:
        return 80.0
    elif days_to_expiry == 2:
        return 60.0
    elif days_to_expiry == 3:
        return 40.0
    elif days_to_expiry == 4:
        return 20.0
    return 0.0


def assess_position_delivery_risk(
    symbol: str,
    quantity: int,
    spot_price: float,
    strike: float,
    option_type: str,
    days_to_expiry: int,
    lot_size: int = 250,
) -> DeliveryRiskAssessment:
    """
    Assesses SEBI physical delivery exposure on a single derivative position.
    """
    clean_sym = symbol.upper().replace("NFO:", "").replace("NSE:", "").strip()
    underlying = clean_sym.split()[0] if " " in clean_sym else clean_sym

    # 1. Cash-settled index check
    if is_cash_settled_index(clean_sym) or is_cash_settled_index(underlying):
        return DeliveryRiskAssessment(
            symbol=clean_sym,
            underlying=underlying,
            instrument_type=option_type.upper(),
            strike=strike,
            spot_price=spot_price,
            quantity=quantity,
            lot_size=lot_size,
            days_to_expiry=days_to_expiry,
            moneyness="EXEMPT",
            moneyness_pct=0.0,
            delivery_obligation_value=0.0,
            required_margin_rate_pct=0.0,
            required_margin_inr=0.0,
            risk_level="EXEMPT",
            actionable_directive="Cash-settled index contract. Zero physical delivery exposure.",
        )

    # 2. Moneyness determination
    opt_t = option_type.upper().strip()
    if opt_t in ("CE", "CALL"):
        moneyness_pct = ((spot_price - strike) / strike) * 100.0 if strike > 0 else 0.0
        if spot_price > strike:
            moneyness = "ITM"
        elif abs(spot_price - strike) / max(1.0, strike) <= 0.015:
            moneyness = "ATM"
        else:
            moneyness = "OTM"
    elif opt_t in ("PE", "PUT"):
        moneyness_pct = ((strike - spot_price) / strike) * 100.0 if strike > 0 else 0.0
        if spot_price < strike:
            moneyness = "ITM"
        elif abs(strike - spot_price) / max(1.0, strike) <= 0.015:
            moneyness = "ATM"
        else:
            moneyness = "OTM"
    else:  # Futures
        moneyness = "FUT"
        moneyness_pct = 0.0

    # 3. Delivery obligation value = abs(quantity) * spot_price
    # In physical settlement, holding 1 lot ITM call requires taking delivery of shares at strike price
    shares_count = abs(quantity)
    contract_val = shares_count * (strike if strike > 0 else spot_price)

    margin_rate = calculate_delivery_margin_rate(days_to_expiry)
    required_margin = (margin_rate / 100.0) * contract_val

    # 4. Risk Level and Action Directive
    if days_to_expiry <= 4 and moneyness in ("ITM", "ATM", "FUT"):
        if days_to_expiry <= 1 and moneyness == "ITM":
            risk = "CRITICAL_DELIVERY_RISK"
            directive = (
                f"MANDATORY ACTION: Contract is ITM expiring in {days_to_expiry}d. "
                f"Full delivery obligation ₹{contract_val:,.0f}. "
                f"Square off or roll over to next month before 15:15 IST today to prevent broker RMS penalty."
            )
        else:
            risk = "ELEVATED_MARGIN"
            directive = (
                f"Expiry week approaching ({days_to_expiry}d to expiry). Required delivery margin: "
                f"{margin_rate:.0f}% (₹{required_margin:,.0f}). Monitor moneyness for rollover."
            )
    else:
        risk = "LOW_RISK"
        directive = "OTM or ample time to expiry. Maintain standard trailing stop."

    return DeliveryRiskAssessment(
        symbol=clean_sym,
        underlying=underlying,
        instrument_type=opt_t,
        strike=strike,
        spot_price=spot_price,
        quantity=quantity,
        lot_size=lot_size,
        days_to_expiry=days_to_expiry,
        moneyness=moneyness,
        moneyness_pct=round(moneyness_pct, 2),
        delivery_obligation_value=round(contract_val, 2),
        required_margin_rate_pct=margin_rate,
        required_margin_inr=round(required_margin, 2),
        risk_level=risk,
        actionable_directive=directive,
    )


def audit_open_positions_for_physical_delivery(
    positions: Optional[list[dict[str, Any]]] = None,
    broker: Optional[Any] = None,
) -> list[DeliveryRiskAssessment]:
    """
    Audits all open broker or paper positions for SEBI physical delivery risk.
    """
    if positions is None:
        if broker is not None and hasattr(broker, "get_positions"):
            try:
                positions = broker.get_positions()
            except Exception as e:
                logger.warning(f"[EODRebalancer] Failed to fetch broker positions: {e}")
                positions = []
        else:
            # Fall back to Paper broker positions if available
            try:
                from engine.paper import get_paper_broker

                pb = get_paper_broker()
                positions = pb.get_positions() if hasattr(pb, "get_positions") else []
            except Exception:
                positions = []

    if not positions:
        return []

    from market.quotes import get_ltp

    assessments: list[DeliveryRiskAssessment] = []

    for pos in positions:
        sym = pos.get("symbol", "")
        qty = int(pos.get("net_quantity", pos.get("quantity", 0)) or 0)
        if qty == 0 or not sym:
            continue

        # Parse option details if present
        strike = float(pos.get("strike", 0.0) or 0.0)
        opt_type = str(pos.get("option_type", "") or "")
        lot_sz = int(pos.get("lot_size", 250) or 250)

        # Estimate DTE (default to 4 days if near month-end)
        dte = int(pos.get("days_to_expiry", 4) or 4)

        underlying = sym.split()[0] if " " in sym else sym
        spot = float(pos.get("spot_price", 0.0) or 0.0)
        if spot <= 0:
            try:
                spot = get_ltp(underlying) or float(pos.get("last_price", 0.0) or 0.0)
            except Exception:
                spot = float(pos.get("last_price", 0.0) or 0.0)

        item = assess_position_delivery_risk(
            symbol=sym,
            quantity=qty,
            spot_price=spot,
            strike=strike,
            option_type=opt_type,
            days_to_expiry=dte,
            lot_size=lot_sz,
        )
        assessments.append(item)

    return assessments


def run_moc_guardian_audit(
    positions: Optional[list[dict[str, Any]]] = None,
    broker: Optional[Any] = None,
) -> MOCGuardianReport:
    """
    Runs the 15:15–15:30 IST Market-On-Close Guardian audit.
    Identifies pending intraday (MIS) orders and critical physical delivery risks.
    """
    now = datetime.now(IST)
    hhmm = now.hour * 100 + now.minute

    if hhmm < 1515:
        session_st = "PRE_MOC"
    elif 1515 <= hhmm <= 1530:
        session_st = "MOC_ACTIVE"
    else:
        session_st = "POST_MOC"

    delivery_risks = audit_open_positions_for_physical_delivery(positions=positions, broker=broker)
    critical_risks = [d for d in delivery_risks if d.risk_level == "CRITICAL_DELIVERY_RISK"]

    actions: list[str] = []
    if session_st == "MOC_ACTIVE":
        actions.append(
            "Session is in MOC window (15:15-15:30 IST). Square off all MIS intraday positions."
        )
    if critical_risks:
        actions.append(
            f"CRITICAL: {len(critical_risks)} stock option positions face mandatory SEBI physical delivery! "
            f"Action rollover immediately."
        )

    return MOCGuardianReport(
        timestamp=now.strftime("%Y-%m-%d %H:%M:%S IST"),
        session_status=session_st,
        total_positions_audited=len(delivery_risks),
        intraday_positions_pending_close=sum(
            1 for p in (positions or []) if str(p.get("product", "")).upper() in ("MIS", "INTRADAY")
        ),
        physical_delivery_risks_detected=len(critical_risks),
        delivery_risk_items=[d.to_dict() for d in delivery_risks],
        action_items=actions,
    )
