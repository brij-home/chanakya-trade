"""
engine/option_resolver.py
─────────────────────────
Institutional Option Contract & Premium Resolver for Indian Derivatives (NSE / NFO / BSE).

Guarantees:
  1. Coordinate System Integrity: Resolves real Option Premiums for entry, stop-loss,
     and targets — NEVER leaks underlying spot levels into option fields.
  2. Index Derivative Policy: All index signals (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
     SENSEX, BANKEX) strictly resolve to defined-risk Options (CE / PE) instead of directional spot/futures.
  3. Dynamic ATM Resolution: Selects closest liquid ATM/near-the-money contract (within 2.0% of spot).
  4. Off-Market / Fallback Resilience: Deterministic mathematical strike & premium estimation
     if broker options chain is temporarily degraded or off-market.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("chanakya.engine.option_resolver")

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}


@dataclass
class ResolvedOptionPlan:
    contract_symbol: str
    strike: float
    option_type: str  # "CE" or "PE"
    entry_premium: float
    sl_premium: float
    t1_premium: float
    t2_premium: float
    lot_size: int
    underlying_spot: float
    underlying_sl: float
    underlying_target: float
    is_estimated: bool = False
    expiry: Optional[str] = None
    t0_5_premium: Optional[float] = None
    t3_premium: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_symbol": self.contract_symbol,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry": self.expiry,
            "expiry_date": self.expiry,
            "entry_premium": self.entry_premium,
            "sl_premium": self.sl_premium,
            "t0_5_premium": self.t0_5_premium,
            "t1_premium": self.t1_premium,
            "t2_premium": self.t2_premium,
            "t3_premium": self.t3_premium,
            "lot_size": self.lot_size,
            "underlying_spot": self.underlying_spot,
            "underlying_sl": self.underlying_sl,
            "underlying_target": self.underlying_target,
            "is_estimated": self.is_estimated,
        }


def is_index_symbol(symbol: str) -> bool:
    clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    return clean in INDEX_SYMBOLS


def get_strike_step(symbol: str) -> int:
    clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    if clean in ("BANKNIFTY", "SENSEX", "BANKEX"):
        return 100
    if clean == "MIDCPNIFTY":
        return 25
    return 50


def resolve_option_contract(
    symbol: str,
    spot: float,
    direction: str,  # "BULLISH" / "BUY" or "BEARISH" / "SELL"
    underlying_sl: Optional[float] = None,
    underlying_target: Optional[float] = None,
    prefer_options: bool = False,
) -> Optional[ResolvedOptionPlan]:
    """
    Resolves real option contract and premium levels for an index or F&O stock.
    Returns None for non-F&O cash equities unless prefer_options is explicitly requested.
    """
    if spot <= 0:
        return None

    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_idx = is_index_symbol(clean_sym)

    # Determine Option Type
    is_bull = direction.upper() in ("BULLISH", "BUY", "LONG")
    opt_type = "CE" if is_bull else "PE"

    lot_sz = 1
    try:
        from engine.position_sizer import get_lot_size

        lot_sz = get_lot_size(clean_sym) or (
            15 if clean_sym == "NIFTY" else (15 if clean_sym == "BANKNIFTY" else 1)
        )
    except Exception:
        lot_sz = 15 if is_idx else 1

    # If it's a cash equity with no F&O lot size and not requested, do not force options
    if not is_idx and not prefer_options and lot_sz <= 1:
        return None

    # Step 1: Query Live Options Chain
    chosen_contract = None
    opt_ltp = 0.0
    opt_strike = 0.0
    opt_sym = ""

    try:
        from market.options import get_options_chain

        raw_chain = get_options_chain(clean_sym)
        contracts = (
            raw_chain.contracts
            if hasattr(raw_chain, "contracts")
            else (raw_chain if isinstance(raw_chain, list) else [])
        )
        if contracts:
            matching = [
                c
                for c in contracts
                if getattr(c, "option_type", "").upper() == opt_type
                and float(getattr(c, "last_price", 0.0) or 0.0) > 0
                and (abs(float(getattr(c, "strike", 0.0)) - spot) / max(1.0, spot)) <= 0.025
            ]
            if matching:
                # Sort by proximity to spot
                matching.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - spot))
                chosen = matching[0]
                opt_sym = chosen.symbol
                opt_ltp = float(chosen.last_price)
                opt_strike = float(chosen.strike)
                chosen_contract = chosen
    except Exception as e:
        logger.debug(f"[OptionResolver] Options chain query error for {clean_sym}: {e}")

    # Step 2: Deterministic Fallback if Live Chain is Down / Degraded
    is_est = False
    if not chosen_contract or opt_ltp <= 0:
        step = get_strike_step(clean_sym)
        opt_strike = float(round(spot / step) * step)
        # Institutional estimation: 0.65% - 0.75% of spot for weekly ATM index options
        base_prem = spot * 0.007 if is_idx else max(15.0, spot * 0.015)
        opt_ltp = round(max(20.0 if is_idx else 5.0, base_prem), 1)
        opt_sym = f"{clean_sym} {int(opt_strike)} {opt_type}"
        is_est = True

    # Step 3: Compute Premium-Space Invalidation Stop and Targets with Tiered Feasibility
    if is_idx:
        # Index Options: disciplined -18% stop-loss floor
        disciplined_sl_floor = round(max(0.1, opt_ltp * 0.82), 2)
        if opt_ltp >= 350:
            # Expensive Index contracts (e.g. Bank Nifty ₹600-₹1200):
            # Capped to achievable intraday points (+20% T1, +36% T2, +55% T3)
            opt_t0_5 = round(opt_ltp * 1.08, 2)
            opt_t1 = round(opt_ltp * 1.20, 2)
            opt_t2 = round(opt_ltp * 1.36, 2)
            opt_t3 = round(opt_ltp * 1.55, 2)
            t1_ceiling = round(opt_ltp * 1.22, 2)
            t2_ceiling = round(opt_ltp * 1.38, 2)
        else:
            # Lower-premium Index contracts (e.g. Nifty ATM ₹80-₹200):
            opt_t0_5 = round(opt_ltp * 1.10, 2)
            opt_t1 = round(opt_ltp * 1.28, 2)
            opt_t2 = round(opt_ltp * 1.55, 2)
            opt_t3 = round(opt_ltp * 1.90, 2)
            t1_ceiling = round(opt_ltp * 1.60, 2)
            t2_ceiling = round(opt_ltp * 2.20, 2)
    else:
        # Stock Options: disciplined -22% stop-loss floor
        disciplined_sl_floor = round(max(0.1, opt_ltp * 0.78), 2)
        opt_t0_5 = round(opt_ltp * 1.10, 2)
        opt_t1 = round(opt_ltp * 1.22, 2)
        opt_t2 = round(opt_ltp * 1.38, 2)
        opt_t3 = round(opt_ltp * 1.60, 2)
        t1_ceiling = round(opt_ltp * 1.24, 2)
        t2_ceiling = round(opt_ltp * 1.42, 2)

    opt_sl = disciplined_sl_floor

    # If underlying SL is provided, calibrate option stop with estimated delta (~0.50 for ATM)
    if underlying_sl and underlying_sl > 0:
        spot_risk = abs(spot - underlying_sl)
        delta = 0.50
        estimated_prem_risk = spot_risk * delta
        if 0 < estimated_prem_risk < opt_ltp:
            opt_sl = round(max(disciplined_sl_floor, opt_ltp - estimated_prem_risk), 2)

    if underlying_target and underlying_target > 0:
        spot_gain = abs(underlying_target - spot)
        delta = 0.50
        estimated_prem_gain = spot_gain * delta
        if estimated_prem_gain > 0:
            opt_t1 = round(min(t1_ceiling, max(opt_t1, opt_ltp + estimated_prem_gain)), 2)
            opt_t2 = round(min(t2_ceiling, max(opt_t2, opt_ltp + 1.8 * estimated_prem_gain)), 2)

    opt_exp = getattr(chosen_contract, "expiry", None) if chosen_contract else None

    return ResolvedOptionPlan(
        contract_symbol=opt_sym,
        strike=opt_strike,
        option_type=opt_type,
        entry_premium=opt_ltp,
        sl_premium=opt_sl,
        t1_premium=opt_t1,
        t2_premium=opt_t2,
        lot_size=lot_sz,
        underlying_spot=spot,
        underlying_sl=underlying_sl
        or (round(spot * 0.99, 1) if is_bull else round(spot * 1.01, 1)),
        underlying_target=underlying_target
        or (round(spot * 1.02, 1) if is_bull else round(spot * 0.98, 1)),
        is_estimated=is_est,
        expiry=opt_exp,
        t0_5_premium=opt_t0_5,
        t3_premium=opt_t3,
    )
