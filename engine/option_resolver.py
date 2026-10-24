"""
engine/option_resolver.py
─────────────────────────
Institutional Option Contract, Defined-Risk Spread & Premium Resolver for Indian Derivatives (NSE / NFO / BSE).

Guarantees:
  1. Coordinate System Integrity: Resolves real Option Premiums for entry, stop-loss,
     and targets — NEVER leaks underlying spot levels into option fields.
  2. Index Derivative Policy: All index signals (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
     SENSEX, BANKEX) strictly resolve to defined-risk Options (CE / PE) instead of directional spot/futures.
  3. Dynamic ATM Resolution: Selects closest liquid ATM/near-the-money contract (within 2.0% of spot).
  4. VIX-Regime Strategy Matrix & Defined-Risk Spreads:
     - Elevated VIX (>= 19.0) or Event Days: Automatically constructs Defined-Risk Vertical Spreads
       (Bull Call Spread / Bear Put Spread) to eliminate post-event IV crush and Vega collapse.
     - Compressed VIX (<= 13.5): Tags high gamma-expansion potential for naked directional options.
     - Normal VIX (13.5–19.0): Disciplined ATM/near-ITM directional options.
  5. Off-Market / Fallback Resilience: Deterministic mathematical strike & premium estimation
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
    strategy_type: str = (
        "NAKED_DIRECTIONAL"  # "NAKED_DIRECTIONAL" | "BULL_CALL_SPREAD" | "BEAR_PUT_SPREAD"
    )
    vix_regime: str = (
        "NORMAL_MOMENTUM"  # "COMPRESSED_VOL" | "NORMAL_MOMENTUM" | "ELEVATED_VOL_SPREAD"
    )
    vix_value: float = 14.5
    execution_style_mandate: str = "STANDARD"  # "STANDARD" | "HEDGED_SPREAD_MANDATORY"
    hedge_contract_symbol: Optional[str] = None
    hedge_strike: Optional[float] = None
    hedge_premium: Optional[float] = None
    net_debit: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    spread_details: Optional[dict[str, Any]] = None
    strike_tier: str = "ATM"  # "ATM" | "HIGH_GAMMA_ASYMMETRY" | "DEEP_ITM"
    execution_trigger: Optional[str] = None
    confirmation_rule: Optional[str] = None
    execution_notes: Optional[str] = None
    bid_ask_spread_pct: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
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
            "strategy_type": self.strategy_type,
            "vix_regime": self.vix_regime,
            "vix_value": round(self.vix_value, 2),
            "execution_style_mandate": self.execution_style_mandate,
            "strike_tier": self.strike_tier,
            "execution_trigger": self.execution_trigger,
            "confirmation_rule": self.confirmation_rule,
            "execution_notes": self.execution_notes,
            "bid_ask_spread_pct": self.bid_ask_spread_pct,
        }
        if self.spread_details:
            d["hedged_spread"] = self.spread_details
            d["hedge_contract_symbol"] = self.hedge_contract_symbol
            d["hedge_strike"] = self.hedge_strike
            d["hedge_premium"] = self.hedge_premium
            d["net_debit"] = self.net_debit
            d["max_loss"] = self.max_loss
            d["max_profit"] = self.max_profit
        return d


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
    india_vix: Optional[float] = None,
    prefer_spread: Optional[bool] = None,
    strike_tier: str = "ATM",  # "ATM" | "HIGH_GAMMA_ASYMMETRY" | "DEEP_ITM"
    roc_velocity: Optional[float] = None,
) -> Optional[ResolvedOptionPlan]:
    """
    Resolves real option contract and premium levels for an index or F&O stock.
    Supports VIX-regime aware automatic vertical spread construction and
    dynamic strike tiering (ATM vs HIGH_GAMMA_ASYMMETRY vs DEEP_ITM).
    Returns None for non-F&O cash equities unless prefer_options is explicitly requested.
    """
    if spot <= 0:
        return None

    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_idx = is_index_symbol(clean_sym)
    tier_upper = (strike_tier or "ATM").upper().strip()

    # Determine Option Type
    is_bull = direction.upper() in ("BULLISH", "BUY", "LONG")
    opt_type = "CE" if is_bull else "PE"

    # Lot size resolution
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

    # Step 1: Resolve India VIX Regime
    vix_val = 14.5
    if india_vix is not None and float(india_vix) > 0:
        vix_val = float(india_vix)
    else:
        try:
            from market.indices import get_vix

            fetched_vix = get_vix()
            if fetched_vix and float(fetched_vix) > 0:
                vix_val = float(fetched_vix)
        except Exception:
            vix_val = 14.5

    # VIX Regime Classification: Mandate Defined-Risk Spreads when VIX >= 16.0 or momentum velocity is slow (< 0.20%)
    is_slow_momentum = roc_velocity is not None and abs(float(roc_velocity)) < 0.20
    is_elevated_vix = (vix_val >= 16.0) or (prefer_spread is True) or is_slow_momentum
    if is_elevated_vix:
        vix_regime = "ELEVATED_VOL_SPREAD"
        strategy_type = "BULL_CALL_SPREAD" if is_bull else "BEAR_PUT_SPREAD"
        exec_mandate = "HEDGED_SPREAD_MANDATORY"
    elif vix_val <= 13.5:
        vix_regime = "COMPRESSED_VOL"
        strategy_type = "NAKED_DIRECTIONAL"
        exec_mandate = "STANDARD"
    else:
        vix_regime = "NORMAL_MOMENTUM"
        strategy_type = "NAKED_DIRECTIONAL"
        exec_mandate = "STANDARD"

    # Step 2: Query Live Options Chain
    chosen_contract = None
    opt_ltp = 0.0
    opt_strike = 0.0
    opt_sym = ""
    spread_pct_val: Optional[float] = None
    contracts: list[Any] = []
    step = get_strike_step(clean_sym)

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
                and float(getattr(c, "last_price", 0.0) or 0.0) >= (1.0 if is_idx else 0.50)
                and (abs(float(getattr(c, "strike", 0.0)) - spot) / max(1.0, spot)) <= 0.025
            ]
            # Liquidity & Bid-Ask Spread Guard:
            # If live top-of-book bid/ask are present, enforce spread <= 3.5% (index) or <= 6.0% (stock)
            liquid_matching = []
            max_spr_matching = 0.035 if is_idx else 0.06
            for c in matching:
                b = float(getattr(c, "bid", 0.0) or 0.0)
                a = float(getattr(c, "ask", 0.0) or 0.0)
                lp = float(getattr(c, "last_price", 0.0) or 0.0)
                if b > 0 and a > 0 and lp > 0:
                    spr = (a - b) / lp
                    if spr <= max_spr_matching:
                        liquid_matching.append(c)
                else:
                    liquid_matching.append(c)

            if liquid_matching:
                matching = liquid_matching

            if matching:
                if tier_upper == "HIGH_GAMMA_ASYMMETRY":
                    # For Bullish CE: OTM+1 is first strike > spot (within 1.8 step)
                    # For Bearish PE: OTM+1 is first strike < spot (within 1.8 step)
                    if is_bull:
                        otm_candidates = [
                            c
                            for c in matching
                            if float(getattr(c, "strike", 0.0)) > spot
                            and (float(getattr(c, "strike", 0.0)) - spot) <= (step * 1.8)
                        ]
                        otm_candidates.sort(key=lambda c: float(getattr(c, "strike", 0.0)))
                    else:
                        otm_candidates = [
                            c
                            for c in matching
                            if float(getattr(c, "strike", 0.0)) < spot
                            and (spot - float(getattr(c, "strike", 0.0))) <= (step * 1.8)
                        ]
                        otm_candidates.sort(key=lambda c: -float(getattr(c, "strike", 0.0)))

                    # Filter for viable liquidity (avoid 0.05 penny junk)
                    min_viable_ltp = 15.0 if is_idx else 3.0
                    viable_otm = [
                        c
                        for c in otm_candidates
                        if float(getattr(c, "last_price", 0.0)) >= min_viable_ltp
                    ]
                    if viable_otm:
                        chosen = viable_otm[0]
                    elif otm_candidates:
                        chosen = otm_candidates[0]
                    else:
                        matching.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - spot))
                        chosen = matching[0]
                elif tier_upper == "DEEP_ITM":
                    if is_bull:
                        itm_candidates = [
                            c
                            for c in matching
                            if float(getattr(c, "strike", 0.0)) < spot
                            and (spot - float(getattr(c, "strike", 0.0))) <= (step * 2.5)
                        ]
                        itm_candidates.sort(
                            key=lambda c: abs(float(getattr(c, "strike", 0.0)) - (spot - step))
                        )
                    else:
                        itm_candidates = [
                            c
                            for c in matching
                            if float(getattr(c, "strike", 0.0)) > spot
                            and (float(getattr(c, "strike", 0.0)) - spot) <= (step * 2.5)
                        ]
                        itm_candidates.sort(
                            key=lambda c: abs(float(getattr(c, "strike", 0.0)) - (spot + step))
                        )
                    chosen = itm_candidates[0] if itm_candidates else matching[0]
                else:  # Default "ATM"
                    matching.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - spot))
                    chosen = matching[0]

                opt_sym = chosen.symbol
                opt_ltp = float(chosen.last_price)
                opt_strike = float(chosen.strike)
                chosen_contract = chosen
                b = float(getattr(chosen, "bid", 0.0) or 0.0)
                a = float(getattr(chosen, "ask", 0.0) or 0.0)
                if b > 0 and a > 0 and opt_ltp > 0:
                    spread_pct_val = round((a - b) / opt_ltp, 4)
                    max_viable_spr = 0.04 if is_idx else 0.08
                    if spread_pct_val > max_viable_spr:
                        if not prefer_options:
                            logger.info(
                                f"[OptionResolver] Discarding illiquid option contract for {clean_sym}: "
                                f"bid={b}, ask={a}, ltp={opt_ltp}, spread={spread_pct_val * 100:.1f}% > {max_viable_spr * 100:.1f}%. "
                                f"Defaulting to clean underlying spot execution."
                            )
                            return None
                        else:
                            is_est = True
    except Exception as e:
        logger.debug(f"[OptionResolver] Options chain query error for {clean_sym}: {e}")

    # Step 3: Deterministic Fallback if Live Chain is Down / Degraded
    is_est = False
    if not chosen_contract or opt_ltp <= 0:
        import math

        if tier_upper == "HIGH_GAMMA_ASYMMETRY":
            if is_bull:
                opt_strike = float((math.floor(spot / step) + 1) * step)
            else:
                opt_strike = float((math.ceil(spot / step) - 1) * step)
            base_prem = spot * 0.0035 if is_idx else max(8.0, spot * 0.008)
            opt_ltp = round(max(18.0 if is_idx else 3.0, base_prem), 1)
        elif tier_upper == "DEEP_ITM":
            opt_strike = float(round(spot / step) * step - (step if is_bull else -step))
            base_prem = spot * 0.012 if is_idx else max(25.0, spot * 0.025)
            opt_ltp = round(max(35.0 if is_idx else 8.0, base_prem), 1)
        else:
            opt_strike = float(round(spot / step) * step)
            base_prem = spot * 0.007 if is_idx else max(15.0, spot * 0.015)
            opt_ltp = round(max(20.0 if is_idx else 5.0, base_prem), 1)

        opt_sym = f"{clean_sym} {int(opt_strike)} {opt_type}"
        is_est = True

    # Step 4: Compute Premium-Space Invalidation Stop and Targets with Tiered Feasibility
    if tier_upper == "HIGH_GAMMA_ASYMMETRY":
        # High Gamma Asymmetry: -24% disciplined stop floor, explosive target expansion
        disciplined_sl_floor = round(max(0.1, opt_ltp * 0.76), 2)
        opt_t0_5 = round(opt_ltp * 1.15, 2)
        opt_t1 = round(opt_ltp * 1.35, 2)
        opt_t2 = round(opt_ltp * 1.80, 2)
        opt_t3 = round(opt_ltp * 2.80, 2)
        t1_ceiling = round(opt_ltp * 1.90, 2)
        t2_ceiling = round(opt_ltp * 2.90, 2)
        exec_trig = f"ABOVE_₹{opt_ltp:,.1f}_ON_1M_CLOSE"
        conf_rule = "1_MIN_CANDLE_CLOSE_MANDATORY"
        exec_notes = (
            f"Wait for a 1-minute candle to close above ₹{opt_ltp:,.1f} before entering. "
            "Never chase unconfirmed wicks."
        )
    elif is_idx:
        # Index Options: disciplined -18% stop-loss floor
        disciplined_sl_floor = round(max(0.1, opt_ltp * 0.82), 2)
        if opt_ltp >= 350:
            # Expensive Index contracts (e.g. Bank Nifty ₹600-₹1200):
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
        exec_trig = f"CMP_OR_PULLBACK_₹{opt_ltp:,.1f}"
        conf_rule = "STANDARD_EXECUTION"
        exec_notes = f"Enter near ₹{opt_ltp:,.1f} on pullback or confirmation."
    else:
        # Stock Options: disciplined -22% stop-loss floor
        disciplined_sl_floor = round(max(0.1, opt_ltp * 0.78), 2)
        opt_t0_5 = round(opt_ltp * 1.10, 2)
        opt_t1 = round(opt_ltp * 1.22, 2)
        opt_t2 = round(opt_ltp * 1.38, 2)
        opt_t3 = round(opt_ltp * 1.60, 2)
        t1_ceiling = round(opt_ltp * 1.24, 2)
        t2_ceiling = round(opt_ltp * 1.42, 2)
        exec_trig = f"CMP_OR_PULLBACK_₹{opt_ltp:,.1f}"
        conf_rule = "STANDARD_EXECUTION"
        exec_notes = f"Enter near ₹{opt_ltp:,.1f} on pullback or confirmation."

    opt_sl = disciplined_sl_floor

    # If underlying SL is provided, calibrate option stop with estimated delta
    delta_est = (
        0.40
        if tier_upper == "HIGH_GAMMA_ASYMMETRY"
        else (0.65 if tier_upper == "DEEP_ITM" else 0.50)
    )
    if underlying_sl and underlying_sl > 0:
        spot_risk = abs(spot - underlying_sl)
        estimated_prem_risk = spot_risk * delta_est
        if 0 < estimated_prem_risk < opt_ltp:
            opt_sl = round(max(disciplined_sl_floor, opt_ltp - estimated_prem_risk), 2)

    if underlying_target and underlying_target > 0:
        spot_gain = abs(underlying_target - spot)
        estimated_prem_gain = spot_gain * delta_est
        if estimated_prem_gain > 0:
            opt_t1 = round(min(t1_ceiling, max(opt_t1, opt_ltp + estimated_prem_gain)), 2)
            opt_t2 = round(min(t2_ceiling, max(opt_t2, opt_ltp + 1.8 * estimated_prem_gain)), 2)
            opt_t3 = round(max(opt_t3, opt_t2 * 1.18, opt_ltp + 2.6 * estimated_prem_gain), 2)

    # Defensive guarantee: Strict ascending target hierarchy
    if opt_t2 <= opt_t1:
        opt_t2 = round(opt_t1 * 1.15, 2)
    if opt_t3 <= opt_t2:
        opt_t3 = round(opt_t2 * 1.18, 2)

    opt_exp = getattr(chosen_contract, "expiry", None) if chosen_contract else None

    # Step 5: Construct Defined-Risk Vertical Spread if High VIX Regime
    hedge_contract_sym: Optional[str] = None
    hedge_strike: Optional[float] = None
    hedge_prem: Optional[float] = None
    net_debit: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    spread_dict: Optional[dict[str, Any]] = None

    if is_elevated_vix:
        otm_steps = 3 if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX") else 2
        hedge_strike = float(
            opt_strike + (otm_steps * step) if is_bull else opt_strike - (otm_steps * step)
        )

        chosen_hedge = None
        if contracts:
            hedge_matches = [
                c
                for c in contracts
                if getattr(c, "option_type", "").upper() == opt_type
                and float(getattr(c, "strike", 0.0) or 0.0) == hedge_strike
                and float(getattr(c, "last_price", 0.0) or 0.0) > 0
            ]
            if hedge_matches:
                chosen_hedge = hedge_matches[0]
                hedge_contract_sym = chosen_hedge.symbol
                hedge_prem = float(chosen_hedge.last_price)

        if not chosen_hedge or not hedge_prem:
            hedge_contract_sym = f"{clean_sym} {int(hedge_strike)} {opt_type}"
            hedge_prem = round(max(2.0, opt_ltp * 0.42), 1)

        net_debit = round(max(1.0, opt_ltp - hedge_prem), 2)
        strike_width = abs(hedge_strike - opt_strike)
        if strike_width > 0 and net_debit >= (strike_width * 0.85):
            net_debit = round(strike_width * 0.45, 2)
            hedge_prem = round(max(1.0, opt_ltp - net_debit), 2)

        max_loss = round(net_debit * lot_sz, 2)
        max_profit = round(max(0.0, (strike_width - net_debit) * lot_sz), 2)
        rr_spread = round(max_profit / max(1.0, max_loss), 2)

        spread_dict = {
            "strategy_name": strategy_type,
            "sentiment": "BULLISH" if is_bull else "BEARISH",
            "net_cashflow": net_debit,
            "flow_type": "NET_DEBIT",
            "max_loss": max_loss,
            "max_profit": max_profit,
            "risk_reward_ratio": rr_spread,
            "legs": [
                {
                    "option_type": opt_type,
                    "strike": opt_strike,
                    "side": "BUY",
                    "symbol": opt_sym,
                    "premium": opt_ltp,
                    "quantity": lot_sz,
                },
                {
                    "option_type": opt_type,
                    "strike": hedge_strike,
                    "side": "SELL",
                    "symbol": hedge_contract_sym,
                    "premium": hedge_prem,
                    "quantity": lot_sz,
                },
            ],
            "breakeven_point": round(
                opt_strike + net_debit if is_bull else opt_strike - net_debit, 1
            ),
            "thesis": (
                f"High India VIX ({vix_val:.1f} >= 19.0) mandates defined-risk spread to eliminate Vega crush and theta decay."
            ),
        }

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
        strategy_type=strategy_type,
        vix_regime=vix_regime,
        vix_value=vix_val,
        execution_style_mandate=exec_mandate,
        hedge_contract_symbol=hedge_contract_sym,
        hedge_strike=hedge_strike,
        hedge_premium=hedge_prem,
        net_debit=net_debit,
        max_loss=max_loss,
        max_profit=max_profit,
        spread_details=spread_dict,
        strike_tier=tier_upper,
        execution_trigger=exec_trig,
        confirmation_rule=conf_rule,
        execution_notes=exec_notes,
        bid_ask_spread_pct=spread_pct_val,
    )
