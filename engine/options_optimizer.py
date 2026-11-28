"""
engine/options_optimizer.py
────────────────────────────
Dynamic Options Greeks & IV Skew Surface (Strike Auto-Optimizer).

Institutional Capabilities:
  1. Black-Scholes Greeks Surface:
     Analytic computation of Delta, Gamma, Vega, Theta, and Rho using pure standard library
     math.erf (zero external C-extension overhead, 0ms latency).
  2. Dynamic Strike & Delta Selection:
     - MOMENTUM_BREAKOUT: Selects Delta ∈ [0.50, 0.65] (ATM / slight ITM) for maximum delta
       acceleration and minimal theta bleed.
     - PULLBACK_VALUE: Selects Delta ∈ [0.42, 0.52] (ATM / closest OTM) to balance leverage
       with discounted entry cost.
     - GAMMA_SQUEEZE: Selects Delta ∈ [0.35, 0.45] with accelerating gamma profile.
  3. IV Skew & Structure Recommender:
     - When IV is normal/low: Recommends NAKED_BUY with calibrated stop-loss and profit targets.
     - When IV is elevated (IV Rank >= 70% or VIX >= 18.0) or Call/Put Skew is stretched:
       Recommends VERTICAL_DEBIT_SPREAD (e.g. Bull Call Spread / Bear Put Spread), selling
       an expensive OTM wing (+1.5σ) to finance the long leg, eliminate IV crush vulnerability,
       and elevate R:R above 1:3.0.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

from market.instruments import canonical_symbol

logger = logging.getLogger("engine.options_optimizer")


# ── Standard Normal Cumulative Distribution & Density Functions ──


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution via math.erf."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal distribution."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass
class OptionGreeks:
    """Calculated Black-Scholes option pricing and Greeks."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    d1: float
    d2: float


def calculate_black_scholes_greeks(
    spot: float,
    strike: float,
    dte_days: float,
    iv: float,
    risk_free_rate: float = 0.065,  # RBI 91-day T-bill baseline (~6.5%)
    option_type: str = "CE",
) -> OptionGreeks:
    """
    Computes exact analytic Black-Scholes price and Greeks.
    Fail-safe against edge cases (zero/negative DTE, negative IV, zero spot).
    """
    opt_type = option_type.upper().strip()
    is_call = opt_type in ("CE", "CALL")

    if spot <= 0 or strike <= 0 or iv <= 0:
        intrinsic = max(0.0, spot - strike) if is_call else max(0.0, strike - spot)
        return OptionGreeks(
            price=intrinsic,
            delta=1.0
            if (is_call and spot > strike)
            else (-1.0 if (not is_call and spot < strike) else 0.0),
            gamma=0.0,
            vega=0.0,
            theta=0.0,
            rho=0.0,
            d1=0.0,
            d2=0.0,
        )

    t_years = max(dte_days, 0.5) / 365.0
    sigma = max(iv, 0.01)
    r = risk_free_rate

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = _norm_pdf(d1)
    exp_rt = math.exp(-r * t_years)

    if is_call:
        price = spot * _norm_cdf(d1) - strike * exp_rt * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (
            -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) - r * strike * exp_rt * _norm_cdf(d2)
        ) / 365.0
        rho = (strike * t_years * exp_rt * _norm_cdf(d2)) / 100.0
    else:
        price = strike * exp_rt * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (
            -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) + r * strike * exp_rt * _norm_cdf(-d2)
        ) / 365.0
        rho = (-strike * t_years * exp_rt * _norm_cdf(-d2)) / 100.0

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = (spot * sqrt_t * pdf_d1) / 100.0  # Per 1% change in vol

    return OptionGreeks(
        price=max(0.05, round(price, 2)),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        vega=round(vega, 4),
        theta=round(theta, 4),
        rho=round(rho, 4),
        d1=round(d1, 4),
        d2=round(d2, 4),
    )


@dataclass
class OptimizedContractPlan:
    """Complete institutional option execution blueprint."""

    symbol: str
    underlying_spot: float
    direction: str
    regime: str
    option_type: str
    contract_symbol: str
    strike: float
    target_delta: float
    actual_delta: float
    greeks: dict[str, float]
    iv_percentile: Optional[float]
    iv_crush_risk: str  # "LOW" | "MODERATE" | "HIGH" | "UNAVAILABLE"
    execution_structure: (
        str  # "NAKED_BUY" | "VERTICAL_DEBIT_SPREAD" | "IRON_CONDOR" | "UNAVAILABLE"
    )
    limit_entry_premium: float
    stop_loss_premium: float
    target_1_premium: float
    target_2_premium: float
    risk_reward: str
    hedge_contract_symbol: Optional[str] = None
    hedge_strike: Optional[float] = None
    net_debit_per_share: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    coaching_note: str = ""
    resolved_from_master: bool = False
    exchange: str = "NSE"
    expiry: Optional[str] = None
    lot_size: int = 1
    tick_size: float = 0.05
    iv_source: str = "UNAVAILABLE"
    iv_rank: Optional[float] = None
    vrp: Optional[float] = None
    bid_ask_spread_pct: Optional[float] = None
    status: str = "AVAILABLE"
    unavailability_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_underlying_strike_step(symbol: str, spot: float) -> float:
    """Returns canonical strike step size via market.symbol_master SSOT."""
    from market.symbol_master import get_strike_step

    clean = canonical_symbol(symbol).upper()
    try:
        step = float(get_strike_step(clean, spot=spot))
        if step > 0:
            return step
    except Exception as exc:
        logger.debug(f"[options_optimizer] Step resolution note for {clean}: {exc}")

    # Fallback to standard benchmark step if master is unavailable
    if clean in ("BANKNIFTY", "SENSEX", "BANKEX"):
        return 100.0
    if clean in ("NIFTY", "FINNIFTY"):
        return 50.0
    if clean in ("MIDCPNIFTY",):
        return 25.0
    return 50.0 if spot >= 2500 else (20.0 if spot >= 1000 else 10.0)


def optimize_option_contract(
    symbol: str,
    direction: str,
    spot: float,
    regime: str = "MOMENTUM_BREAKOUT",
    iv: Optional[float] = None,
    iv_percentile: Optional[float] = None,
    dte_days: float = 6.0,
    target_delta: Optional[float] = None,
    lot_size: int = 1,
) -> OptimizedContractPlan:
    """
    Optimizes strike selection, target delta, and spread hedge structure
    based on live spot price, market regime, and implied volatility.
    """
    clean_sym = canonical_symbol(symbol).upper()
    norm_dir = direction.upper().strip()
    is_bull = norm_dir in ("BULLISH", "BUY", "CALL", "LONG")
    opt_type = "CE" if is_bull else "PE"

    # 1. Resolve IV & IV Percentile
    resolved_iv = iv if (iv is not None and iv > 0) else 0.165  # Default ~16.5% normal IV
    resolved_ivp = iv_percentile if (iv_percentile is not None and iv_percentile >= 0) else 45.0

    # 2. Determine Optimal Target Delta based on Regime
    norm_regime = regime.upper().strip()
    if target_delta is not None and 0.20 <= target_delta <= 0.85:
        chosen_target_delta = target_delta
    elif norm_regime == "MOMENTUM_BREAKOUT":
        chosen_target_delta = 0.54 if is_bull else -0.54
    elif norm_regime == "PULLBACK_VALUE":
        chosen_target_delta = 0.46 if is_bull else -0.46
    elif norm_regime == "GAMMA_SQUEEZE":
        chosen_target_delta = 0.40 if is_bull else -0.40
    else:
        chosen_target_delta = 0.50 if is_bull else -0.50

    # 3. Find Optimal Primary Strike
    step = get_underlying_strike_step(clean_sym, spot)
    atm_strike = round(spot / step) * step

    # Candidate strikes: ATM, +1 step, -1 step, +2 steps, -2 steps
    candidate_offsets = [0, 1, -1, 2, -2] if is_bull else [0, -1, 1, -2, 2]
    best_strike = atm_strike
    best_greeks = calculate_black_scholes_greeks(
        spot=spot,
        strike=atm_strike,
        dte_days=dte_days,
        iv=resolved_iv,
        option_type=opt_type,
    )
    min_delta_diff = abs(abs(best_greeks.delta) - abs(chosen_target_delta))

    for offset in candidate_offsets:
        cand_strike = atm_strike + (offset * step)
        g = calculate_black_scholes_greeks(
            spot=spot,
            strike=cand_strike,
            dte_days=dte_days,
            iv=resolved_iv,
            option_type=opt_type,
        )
        diff = abs(abs(g.delta) - abs(chosen_target_delta))
        if diff < min_delta_diff:
            min_delta_diff = diff
            best_strike = cand_strike
            best_greeks = g

    # 4. Formulate Option Contract Symbol (prefer BSE for SENSEX/BANKEX)
    exch = "BSE" if clean_sym in ("SENSEX", "BANKEX") else "NSE"
    expiry_code = ""
    resolved_exp_iso = None
    try:
        from market.symbol_master import get_active_expiries

        exp_dates = get_active_expiries(clean_sym)
        if exp_dates:
            expiry_code = exp_dates[0].strftime("%y%b").upper()
            resolved_exp_iso = exp_dates[0].isoformat()
    except Exception as exc:
        logger.debug(f"[options_optimizer] Expiry resolution note for {clean_sym}: {exc}")

    if not expiry_code:
        from datetime import datetime

        expiry_code = datetime.now().strftime("%y%b").upper()

    contract_sym = f"{exch}:{clean_sym}{expiry_code}{int(best_strike)}{opt_type}"

    # 5. Assess IV Crush Vulnerability & Execution Structure
    is_high_iv = resolved_ivp >= 70.0 or resolved_iv >= 0.22
    iv_crush_risk = "HIGH" if resolved_ivp >= 80.0 else ("MODERATE" if is_high_iv else "LOW")

    limit_entry = best_greeks.price
    sl_premium = round(max(0.05, limit_entry * 0.72), 2)  # 28% risk on premium
    risk_pts = round(limit_entry - sl_premium, 2)
    t1_premium = round(limit_entry + (2.0 * risk_pts), 2)  # +2R
    t2_premium = round(limit_entry + (4.0 * risk_pts), 2)  # +4R

    # Structure Recommendation: Mandate spread when IV is elevated
    hedge_contract_sym = None
    hedge_strike = None
    net_debit = None
    max_loss = None
    max_profit = None
    rr_str = "1:2.0"

    if is_high_iv:
        exec_structure = "VERTICAL_DEBIT_SPREAD"
        # Short wing: 2 steps OTM
        hedge_offset = 2 if is_bull else -2
        hedge_strike = best_strike + (hedge_offset * step)
        hedge_contract_sym = f"{exch}:{clean_sym}{expiry_code}{int(hedge_strike)}{opt_type}"
        hedge_greeks = calculate_black_scholes_greeks(
            spot=spot,
            strike=hedge_strike,
            dte_days=dte_days,
            iv=resolved_iv,
            option_type=opt_type,
        )
        net_debit = round(max(0.5, limit_entry - hedge_greeks.price), 2)
        spread_width = abs(hedge_strike - best_strike)
        max_loss = round(net_debit * lot_size, 2)
        max_profit = round((spread_width - net_debit) * lot_size, 2)
        spread_rr_val = round((spread_width - net_debit) / net_debit, 1) if net_debit > 0 else 2.5
        rr_str = f"1:{spread_rr_val}"
        note = (
            f"High IV regime (IVP: {resolved_ivp:.1f}%). Mandating Bull/Bear Debit Spread "
            f"to neutralize theta/vega crush. Sold OTM wing @ {int(hedge_strike)} finances long leg."
        )
    else:
        exec_structure = "NAKED_BUY"
        note = (
            f"Normal IV regime (IVP: {resolved_ivp:.1f}%). High-conviction naked option buyer "
            f"setup with Delta {best_greeks.delta:.2f} accelerating into trend."
        )

    return OptimizedContractPlan(
        symbol=clean_sym,
        underlying_spot=round(spot, 2),
        direction="BULLISH" if is_bull else "BEARISH",
        regime=norm_regime,
        option_type=opt_type,
        contract_symbol=contract_sym,
        strike=best_strike,
        target_delta=round(chosen_target_delta, 2),
        actual_delta=best_greeks.delta,
        greeks={
            "delta": best_greeks.delta,
            "gamma": best_greeks.gamma,
            "vega": best_greeks.vega,
            "theta": best_greeks.theta,
            "rho": best_greeks.rho,
        },
        iv_percentile=round(resolved_ivp, 1),
        iv_crush_risk=iv_crush_risk,
        execution_structure=exec_structure,
        limit_entry_premium=limit_entry,
        stop_loss_premium=sl_premium,
        target_1_premium=t1_premium,
        target_2_premium=t2_premium,
        risk_reward=rr_str,
        hedge_contract_symbol=hedge_contract_sym,
        hedge_strike=hedge_strike,
        net_debit_per_share=net_debit,
        max_loss=max_loss,
        max_profit=max_profit,
        coaching_note=note,
        resolved_from_master=False,
        exchange=exch,
        expiry=resolved_exp_iso,
        lot_size=max(1, int(lot_size)),
        iv_source="CALLER_INPUT" if iv is not None else "FALLBACK_BASELINE",
    )


def _unavailable_option_plan(
    symbol: str,
    spot: float,
    direction: str,
    regime: str,
    opt_type: str,
    reason: str,
) -> OptimizedContractPlan:
    exch = "BSE" if symbol in ("SENSEX", "BANKEX") else "NSE"
    return OptimizedContractPlan(
        symbol=symbol,
        underlying_spot=round(float(spot or 0.0), 2),
        direction=direction,
        regime=regime,
        option_type=opt_type,
        contract_symbol="",
        strike=0.0,
        target_delta=0.0,
        actual_delta=0.0,
        greeks={},
        iv_percentile=None,
        iv_crush_risk="UNAVAILABLE",
        execution_structure="UNAVAILABLE",
        limit_entry_premium=0.0,
        stop_loss_premium=0.0,
        target_1_premium=0.0,
        target_2_premium=0.0,
        risk_reward="UNAVAILABLE",
        coaching_note=reason,
        resolved_from_master=False,
        exchange=exch,
        iv_source="UNAVAILABLE",
        status="UNAVAILABLE",
        unavailability_reason=reason,
    )


def optimize_listed_option_contract(
    symbol: str,
    direction: str,
    spot: float,
    regime: str = "MOMENTUM_BREAKOUT",
    *,
    listed_contracts: Optional[list[Any]] = None,
    option_chain: Optional[list[Any]] = None,
    iv_snapshot: Optional[Any] = None,
    iv: Optional[float] = None,
    gex_regime: Optional[str] = None,
    is_event_window: bool = False,
    target_delta: Optional[float] = None,
    min_dte: int = 0,
    as_of: Optional[Any] = None,
    require_iv_truth: bool = True,
) -> OptimizedContractPlan:
    """Resolve and optimize a strictly master-listed NSE/BSE option contract & structure.

    Enforces Safety Contracts #25 & #26:
      - Never constructs %y%b calendar strings; requires `ListedContract` from canonical master.
      - Never invents IV Rank 50 or substitutes realized vol for implied volatility rank.
      - Routes structures dynamically from IV Rank / VRP / 25D skew / GEX / Event Risk & spreads.
    """
    from datetime import datetime
    from config.constants import IST
    from engine.iv_surface import build_iv_surface_from_warehouse, extract_surface_inputs_from_chain
    from market.contract_selection import get_listed_contracts

    clean_sym = canonical_symbol(symbol).upper()
    norm_dir = str(direction or "BULLISH").upper().strip()
    is_neutral = norm_dir == "NEUTRAL" or str(regime or "").upper().strip() in (
        "NEUTRAL",
        "RANGE_BOUND",
    )
    is_bull = norm_dir in ("BULLISH", "BUY", "CALL", "LONG")
    opt_type = "CE" if (is_bull or is_neutral) else "PE"
    norm_regime = str(regime or "MOMENTUM_BREAKOUT").upper().strip()

    if not spot or not math.isfinite(spot) or spot <= 0:
        return _unavailable_option_plan(
            clean_sym, 0.0, norm_dir, norm_regime, opt_type, "MISSING_UNDERLYING_SPOT"
        )

    ref_dt = as_of or datetime.now(IST)
    if getattr(ref_dt, "tzinfo", None) is None:
        ref_dt = ref_dt.replace(tzinfo=IST)

    contracts = listed_contracts
    if contracts is None:
        contracts = get_listed_contracts(clean_sym, as_of=ref_dt)

    opt_contracts = [
        c
        for c in (contracts or [])
        if getattr(c, "option_type", None) in ("CE", "PE")
        and getattr(c, "strike", None) is not None
        and getattr(c, "expiry", None) is not None
        and (c.expiry - ref_dt.date()).days >= max(0, int(min_dte))
    ]
    if not opt_contracts:
        return _unavailable_option_plan(
            clean_sym, spot, norm_dir, norm_regime, opt_type, "NO_LISTED_CONTRACTS_FOUND"
        )

    # Index chain quotes by (expiry_iso, round(strike,2), opt_type)
    chain_lookup: dict[tuple[str, float, str], dict[str, Any]] = {}
    for row in option_chain or []:
        is_d = isinstance(row, dict)
        st = float((row.get("strike") if is_d else getattr(row, "strike", 0.0)) or 0.0)
        ot = str(
            (row.get("option_type") if is_d else getattr(row, "option_type", "")) or ""
        ).upper()
        exp = str((row.get("expiry") if is_d else getattr(row, "expiry", "")) or "")[:10]
        if st > 0 and ot in ("CE", "PE"):
            payload = {
                "last_price": float(
                    (row.get("last_price") if is_d else getattr(row, "last_price", 0.0)) or 0.0
                ),
                "bid": row.get("bid") if is_d else getattr(row, "bid", None),
                "ask": row.get("ask") if is_d else getattr(row, "ask", None),
                "iv": row.get("iv") if is_d else getattr(row, "iv", None),
                "delta": row.get("delta") if is_d else getattr(row, "delta", None),
            }
            chain_lookup[(exp, round(st, 2), ot)] = payload
            chain_lookup[("", round(st, 2), ot)] = payload

    # Resolve authentic IV & VRP
    surf = iv_snapshot
    if surf is None:
        try:
            surf = build_iv_surface_from_warehouse(clean_sym, now_dt=ref_dt, persist=False)
        except Exception:
            surf = None

    chain_inputs = (
        extract_surface_inputs_from_chain(option_chain, spot, as_of_date=ref_dt.date())
        if option_chain
        else {}
    )

    raw_iv: Optional[float] = None
    iv_source = "UNAVAILABLE"
    if iv is not None and iv > 0:
        raw_iv = float(iv) / 100.0 if float(iv) > 1.5 else float(iv)
        iv_source = "CALLER_INPUT"
    elif chain_inputs.get("near_atm_iv"):
        v = float(chain_inputs["near_atm_iv"])
        raw_iv = v / 100.0 if v > 1.5 else v
        iv_source = "LIVE_CHAIN"
    elif surf is not None and getattr(surf, "status", "") == "AVAILABLE" and surf.atm_iv_30d:
        v = float(surf.atm_iv_30d)
        raw_iv = v / 100.0 if v > 1.5 else v
        iv_source = "IV_WAREHOUSE_SURFACE"

    if raw_iv is None or raw_iv <= 0:
        if require_iv_truth:
            return _unavailable_option_plan(
                clean_sym, spot, norm_dir, norm_regime, opt_type, "IV_SURFACE_UNAVAILABLE"
            )
        raw_iv = 0.16
        iv_source = "UNCALIBRATED_FALLBACK"

    iv_rank = getattr(surf, "iv_rank", None) if surf is not None else None
    iv_pct = getattr(surf, "iv_percentile", None) if surf is not None else None
    vrp_val = getattr(surf, "vrp", None) if surf is not None else None
    skew_25d = getattr(surf, "skew_25d", None) if surf is not None else None

    # Choose earliest expiry that has both CE and PE near ATM
    expiries = sorted({c.expiry for c in opt_contracts})
    chosen_expiry = expiries[0]
    for exp_cand in expiries:
        same_exp = [c for c in opt_contracts if c.expiry == exp_cand and c.option_type == opt_type]
        if same_exp:
            chosen_expiry = exp_cand
            break

    dte_days = max(0.5, float((chosen_expiry - ref_dt.date()).days))
    pool = [c for c in opt_contracts if c.expiry == chosen_expiry and c.option_type == opt_type]
    if not pool:
        return _unavailable_option_plan(
            clean_sym,
            spot,
            norm_dir,
            norm_regime,
            opt_type,
            f"NO_LISTED_{opt_type}_FOR_{chosen_expiry.isoformat()}",
        )

    if target_delta is not None and 0.20 <= abs(target_delta) <= 0.85:
        chosen_delta = abs(target_delta) if is_bull else -abs(target_delta)
    elif norm_regime == "MOMENTUM_BREAKOUT":
        chosen_delta = 0.54 if is_bull else -0.54
    elif norm_regime == "PULLBACK_VALUE":
        chosen_delta = 0.46 if is_bull else -0.46
    elif norm_regime == "GAMMA_SQUEEZE":
        chosen_delta = 0.40 if is_bull else -0.40
    else:
        chosen_delta = 0.30 if is_bull else -0.30

    def _quote_for(c: Any) -> dict[str, Any]:
        return (
            chain_lookup.get((c.expiry.isoformat(), round(float(c.strike), 2), c.option_type))
            or chain_lookup.get(("", round(float(c.strike), 2), c.option_type))
            or {}
        )

    # Pick listed contract closest to target delta (within +/- 8% of spot)
    near_pool = [c for c in pool if abs(float(c.strike) - spot) / spot <= 0.08] or pool
    best_contract = near_pool[0]
    best_greeks = calculate_black_scholes_greeks(
        spot=spot,
        strike=float(best_contract.strike),
        dte_days=dte_days,
        iv=raw_iv,
        option_type=opt_type,
    )
    min_diff = 999.0
    for c in near_pool:
        q = _quote_for(c)
        c_iv = (
            float(q["iv"]) / 100.0
            if (q.get("iv") and float(q["iv"]) > 1.5)
            else float(q.get("iv") or raw_iv)
        )
        g = calculate_black_scholes_greeks(
            spot=spot, strike=float(c.strike), dte_days=dte_days, iv=c_iv, option_type=opt_type
        )
        diff = abs(abs(g.delta) - abs(chosen_delta))
        if diff < min_diff:
            min_diff = diff
            best_contract = c
            best_greeks = g

    q_primary = _quote_for(best_contract)
    bid_p = q_primary.get("bid")
    ask_p = q_primary.get("ask")
    ltp_p = float(q_primary.get("last_price") or 0.0)
    spread_pct: Optional[float] = None
    if (
        bid_p is not None
        and ask_p is not None
        and float(bid_p) > 0
        and float(ask_p) >= float(bid_p)
    ):
        mid_p = (float(bid_p) + float(ask_p)) / 2.0
        spread_pct = (
            round(((float(ask_p) - float(bid_p)) / mid_p) * 100.0, 2) if mid_p > 0 else None
        )
        limit_entry = round(mid_p, 2)
    elif ltp_p > 0:
        limit_entry = round(ltp_p, 2)
    else:
        limit_entry = best_greeks.price

    # Structure decision: VRP / IVR / Skew / Event Risk / GEX Regime
    gex_u = str(gex_regime or "").upper()
    vrp_pct = (
        vrp_val * 100.0
        if (vrp_val is not None and abs(vrp_val) < 1.0 and raw_iv <= 1.0)
        else vrp_val
    )
    is_high_iv = bool(
        (iv_rank is not None and iv_rank >= 70.0)
        or (iv_pct is not None and iv_pct >= 70.0)
        or raw_iv >= 0.22
        or is_event_window
    )
    iv_crush_risk = (
        "HIGH"
        if (is_event_window or (iv_rank is not None and iv_rank >= 80.0))
        else ("MODERATE" if is_high_iv else "LOW")
    )

    sl_premium = round(max(0.05, limit_entry * 0.72), 2)
    risk_pts = round(max(0.05, limit_entry - sl_premium), 2)
    t1_premium = round(limit_entry + 2.0 * risk_pts, 2)
    t2_premium = round(limit_entry + 4.0 * risk_pts, 2)
    rr_str = "1:2.0"

    hedge_contract = None
    hedge_contract_sym = None
    hedge_strike = None
    net_debit = None
    max_loss = None
    max_profit = None

    # Neutral + Positive GEX + Rich VRP -> Defined-risk IRON_CONDOR
    if is_neutral and (gex_u == "POSITIVE_GEX" or (vrp_pct is not None and vrp_pct >= 2.0)):
        exec_structure = "IRON_CONDOR"
        otm_wings = (
            [c for c in pool if float(c.strike) > float(best_contract.strike)]
            if is_bull
            else [c for c in pool if float(c.strike) < float(best_contract.strike)]
        )
        if otm_wings:
            hedge_contract = min(
                otm_wings, key=lambda c: abs(float(c.strike) - float(best_contract.strike))
            )
            hedge_strike = float(hedge_contract.strike)
            hedge_contract_sym = hedge_contract.symbol
        note = f"Defined-risk Iron Condor ({best_contract.symbol}) under {gex_u or 'NEUTRAL'} / VRP regime."
    elif (
        is_high_iv
        or (gex_u == "POSITIVE_GEX" and norm_regime != "GAMMA_SQUEEZE")
        or (skew_25d is not None and abs(skew_25d) >= 0.22)
    ):
        # Find listed OTM short wing (~1-3 strikes OTM on same expiry)
        otm_candidates = sorted(
            [
                c
                for c in pool
                if (
                    float(c.strike) > float(best_contract.strike)
                    if is_bull
                    else float(c.strike) < float(best_contract.strike)
                )
            ],
            key=lambda c: abs(float(c.strike) - float(best_contract.strike)),
        )
        if otm_candidates:
            exec_structure = "VERTICAL_DEBIT_SPREAD"
            hedge_contract = otm_candidates[min(1, len(otm_candidates) - 1)]
            hedge_contract_sym = hedge_contract.symbol
            hedge_strike = float(hedge_contract.strike)
            qh = _quote_for(hedge_contract)
            h_ltp = float(qh.get("last_price") or 0.0)
            if h_ltp <= 0:
                hg = calculate_black_scholes_greeks(
                    spot=spot,
                    strike=hedge_strike,
                    dte_days=dte_days,
                    iv=raw_iv,
                    option_type=opt_type,
                )
                h_ltp = hg.price
            net_debit = round(max(0.5, limit_entry - h_ltp), 2)
            spread_width = abs(hedge_strike - float(best_contract.strike))
            lot_sz = max(1, int(best_contract.lot_size))
            max_loss = round(net_debit * lot_sz, 2)
            max_profit = round(max(0.0, spread_width - net_debit) * lot_sz, 2)
            rr_val = round(max_profit / max_loss, 1) if max_loss > 0 else 2.0
            rr_str = f"1:{rr_val}"
            note = (
                f"Listed Vertical Debit Spread ({best_contract.symbol} / {hedge_contract_sym}) "
                f"mitigating IV/GEX/event crush."
            )
        else:
            exec_structure = "NAKED_BUY"
            note = f"Listed {best_contract.symbol} long option (no OTM hedge wing available)."
    else:
        exec_structure = "NAKED_BUY"
        note = (
            f"Listed {best_contract.symbol} long option (Delta {best_greeks.delta:.2f}, "
            f"IV source={iv_source}, spread={spread_pct if spread_pct is not None else 'N/A'}%)."
        )

    exch = best_contract.symbol.split(":", 1)[0] if ":" in best_contract.symbol else "NSE"
    return OptimizedContractPlan(
        symbol=clean_sym,
        underlying_spot=round(float(spot), 2),
        direction="BULLISH" if is_bull else ("NEUTRAL" if is_neutral else "BEARISH"),
        regime=norm_regime,
        option_type=opt_type,
        contract_symbol=best_contract.symbol,
        strike=float(best_contract.strike),
        target_delta=round(chosen_delta, 2),
        actual_delta=best_greeks.delta,
        greeks={
            "delta": best_greeks.delta,
            "gamma": best_greeks.gamma,
            "vega": best_greeks.vega,
            "theta": best_greeks.theta,
            "rho": best_greeks.rho,
        },
        iv_percentile=round(iv_pct, 1) if iv_pct is not None else None,
        iv_crush_risk=iv_crush_risk,
        execution_structure=exec_structure,
        limit_entry_premium=limit_entry,
        stop_loss_premium=sl_premium,
        target_1_premium=t1_premium,
        target_2_premium=t2_premium,
        risk_reward=rr_str,
        hedge_contract_symbol=hedge_contract_sym,
        hedge_strike=hedge_strike,
        net_debit_per_share=net_debit,
        max_loss=max_loss,
        max_profit=max_profit,
        coaching_note=note,
        resolved_from_master=True,
        exchange=exch,
        expiry=chosen_expiry.isoformat(),
        lot_size=int(best_contract.lot_size),
        tick_size=float(best_contract.tick_size),
        iv_source=iv_source,
        iv_rank=round(iv_rank, 1) if iv_rank is not None else None,
        vrp=vrp_val,
        bid_ask_spread_pct=spread_pct,
        status="AVAILABLE",
    )
