"""
analysis/options.py
───────────────────
Options analytics: Black-Scholes Greeks, IV, IV Rank, payoff, PCR.
Uses py_vollib for Black-Scholes calculations.

All prices in INR. Rates in decimals (0.065 = 6.5%).
"""

from __future__ import annotations
import logging

logger = logging.getLogger("analysis.options")


import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np

try:
    from py_vollib.black_scholes.greeks.analytical import (
        delta as bs_delta,
        gamma as bs_gamma,
        theta as bs_theta,
        vega as bs_vega,
        rho as bs_rho,
    )
    from py_vollib.black_scholes.implied_volatility import implied_volatility as bs_iv

    PY_VOLLIB_AVAILABLE = True
except Exception:
    # Catch broad Exception: py_vollib depends on py_lets_be_rational/numba
    # which can crash (not just ImportError) on Python 3.13+ due to numba
    # cache/compilation issues. Graceful fallback to built-in BS formulas.
    PY_VOLLIB_AVAILABLE = False

from market.options import get_options_chain


# ── Risk-free rate (RBI repo rate) ────────────────────────────
RISK_FREE_RATE = 0.065  # 6.5%


# ── Greeks dataclass ─────────────────────────────────────────


@dataclass
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0  # per day in INR (divided by 365)
    vega: float = 0.0  # for 1% change in IV
    rho: float = 0.0
    iv: float = 0.0  # implied volatility as decimal
    iv_pct: float = 0.0  # iv as percentage


@dataclass
class OptionAnalysis:
    symbol: str
    underlying: str
    expiry: str
    strike: float
    option_type: str  # CE | PE
    spot: float
    ltp: float
    lot_size: int
    dte: int  # days to expiry

    greeks: Greeks = field(default_factory=Greeks)

    # Derived
    breakeven: float = 0.0
    intrinsic: float = 0.0
    time_value: float = 0.0
    moneyness: str = ""  # ITM | ATM | OTM
    max_loss: float = 0.0  # per lot (for buyer)


@dataclass
class PayoffLeg:
    option_type: str  # CE | PE | STOCK
    transaction: str  # BUY | SELL
    strike: float
    premium: float
    lot_size: int
    lots: int = 1
    iv: Optional[float] = None
    dte: Optional[int] = None


@dataclass
class PayoffPoint:
    spot: float
    pnl: float
    t0_pnl: Optional[float] = None


@dataclass
class StrategyPayoff:
    legs: list[PayoffLeg]
    max_profit: float
    max_loss: float
    breakevens: list[float]
    payoff: list[PayoffPoint]
    t0_payoff: list[PayoffPoint] = field(default_factory=list)
    net_greeks: dict[str, float] = field(default_factory=dict)
    friction_breakdown: dict[str, float] = field(default_factory=dict)
    net_max_profit: float = 0.0
    net_max_loss: float = 0.0


# ── Black-Scholes helpers ─────────────────────────────────────


def _dte_days(expiry_str: str) -> int:
    from datetime import datetime, date
    from config.constants import now_ist

    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except ValueError:
        exp = date.fromisoformat(expiry_str[:10])
    today_ist = now_ist().date()
    return max(0, (exp - today_ist).days)


def _dte_years(expiry_str: str, as_of: Optional[datetime] = None) -> float:
    """
    Days to expiry as fraction of year with intraday time-to-close resolution for 0-DTE.
    On expiry day (delta == 0), calculates fraction of trading day remaining until 15:30 IST.
    For expired contracts (delta < 0), returns 0.0.
    """
    from datetime import datetime, date, time as dtime
    from config.constants import now_ist, IST

    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except ValueError:
        exp = date.fromisoformat(expiry_str[:10])

    if as_of is not None:
        curr_ist = as_of.astimezone(IST) if hasattr(as_of, "astimezone") else as_of
    else:
        curr_ist = now_ist()
    today_ist = curr_ist.date()
    delta_days = (exp - today_ist).days

    if delta_days < 0:
        return 0.0

    now_time = curr_ist.time()
    market_close = dtime(15, 30)
    market_open = dtime(9, 15)

    if now_time < market_open:
        rem_mins = 375.0
    elif now_time >= market_close:
        rem_mins = 0.0
    else:
        rem_mins = (market_close.hour * 60 + market_close.minute) - (
            now_time.hour * 60 + now_time.minute
        )

    if delta_days == 0:
        # Clamp to at least 1 minute (1.0 / (375 * 365)) so T > 0 for BS calculations
        effective_mins = max(1.0, rem_mins)
        return (effective_mins / 375.0) / 365.0
    else:
        intraday_fraction = max(0.0, min(1.0, rem_mins / 375.0))
        return (delta_days + intraday_fraction) / 365.0


def _flag(option_type: str) -> str:
    """py_vollib flag: 'c' for call, 'p' for put."""
    return "c" if option_type.upper() == "CE" else "p"


def compute_greeks(
    spot: float,
    strike: float,
    expiry: str,
    option_type: str,
    ltp: float,
    rate: float = RISK_FREE_RATE,
    as_of: Optional[datetime] = None,
) -> Greeks:
    """
    Compute full Greeks for a single options contract.
    Falls back to analytical approximations if py_vollib unavailable.
    """
    t = _dte_years(expiry, as_of=as_of)
    flag = _flag(option_type)

    if PY_VOLLIB_AVAILABLE and ltp > 0.01:
        try:
            iv = bs_iv(ltp, spot, strike, t, rate, flag)
            return Greeks(
                delta=bs_delta(flag, spot, strike, t, rate, iv),
                gamma=bs_gamma(flag, spot, strike, t, rate, iv),
                theta=bs_theta(flag, spot, strike, t, rate, iv) / 365,
                vega=bs_vega(flag, spot, strike, t, rate, iv) / 100,
                rho=bs_rho(flag, spot, strike, t, rate, iv),
                iv=iv,
                iv_pct=round(iv * 100, 2),
            )
        except Exception as e_suppressed:
            logger.debug(f"[analysis.options] Non-fatal exception suppressed: {e_suppressed}")

    # ── Analytical fallback (own Black-Scholes) ───────────────
    return _bs_greeks_manual(spot, strike, t, rate, ltp, option_type)


def _bs_greeks_manual(
    S: float,
    K: float,
    T: float,
    r: float,
    price: float,
    option_type: str,
) -> Greeks:
    """Minimal Black-Scholes implementation as fallback."""
    from scipy.stats import norm

    # Estimate sigma from price via Newton-Raphson with adaptive dampening
    sigma = 0.30  # initial guess (slightly higher for deep ITM)
    for _ in range(100):
        try:
            d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            if option_type.upper() == "CE":
                theo = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
                vega = S * norm.pdf(d1) * math.sqrt(T)
                delta = norm.cdf(d1)
            else:
                theo = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
                vega = S * norm.pdf(d1) * math.sqrt(T)
                delta = norm.cdf(d1) - 1

            # Convergence check
            if abs(theo - price) < 0.01:
                break

            if abs(vega) < 1e-10:
                break

            # Adaptive step dampening to avoid overshoot
            adjustment = (theo - price) / vega
            adjustment = max(-0.05, min(0.05, adjustment))
            sigma -= adjustment

            # Clamp sigma to valid bounds
            sigma = max(0.001, min(5.0, sigma))
        except Exception:
            break

    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
        if option_type.upper() == "CE":
            theta_val = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(
                -r * T
            ) * norm.cdf(d2)
        else:
            theta_val = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(
                -r * T
            ) * norm.cdf(-d2)
        return Greeks(
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta_val / 365, 4),
            vega=round(vega / 100, 4),
            iv=round(sigma, 4),
            iv_pct=round(sigma * 100, 2),
        )
    except Exception:
        return Greeks(iv=sigma, iv_pct=round(sigma * 100, 2))


# ── IV Rank ───────────────────────────────────────────────────


def iv_rank(
    current_iv: float,
    historical_ivs: list[float],
) -> Optional[float]:
    """
    IV Rank = (current_iv - 52w_low) / (52w_high - 52w_low) × 100

    Returns a rank only when a valid current IV and non-flat historical IV
    observations are available. Realized volatility is not an IV substitute.
    """
    import math

    if not math.isfinite(current_iv) or current_iv <= 0 or not historical_ivs:
        return None
    values = [float(value) for value in historical_ivs if math.isfinite(float(value)) and value > 0]
    if not values:
        return None
    iv_low = min(values)
    iv_high = max(values)
    if iv_high == iv_low:
        return None
    rank = (current_iv - iv_low) / (iv_high - iv_low) * 100
    return round(min(100.0, max(0.0, rank)), 1)


def compute_realized_volatility_rank_from_history(
    symbol: str, period: str = "1y"
) -> Optional[float]:
    """
    Compute a realized-volatility rank from historical underlying prices.

    Uses 30-day rolling annualized volatility as an IV proxy:
      IV Rank = (current_RV - 52w_low_RV) / (52w_high_RV - 52w_low_RV) * 100

    This is explicitly not implied-volatility rank and must not be used to
    infer option richness, IV crush, or premium-selling/buying edge.
    """
    try:
        import yfinance as yf
        import numpy as np

        # Use proper symbol mapping (handles NIFTY → ^NSEI etc.)
        try:
            from market.yfinance_provider import _to_yf_symbol

            yf_sym = _to_yf_symbol(symbol)
        except ImportError:
            yf_sym = f"{symbol.upper()}.NS"

        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(period=period)
        if hist.empty or len(hist) < 60:
            return None

        returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        rolling_vol = (returns.rolling(30).std() * np.sqrt(252) * 100).dropna()

        if rolling_vol.empty or len(rolling_vol) < 30:
            return None

        current = rolling_vol.iloc[-1]
        lo = rolling_vol.min()
        hi = rolling_vol.max()

        if hi == lo:
            return None

        rank = (current - lo) / (hi - lo) * 100
        return round(min(100.0, max(0.0, rank)), 1)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Realized volatility rank unavailable for %s: %s", symbol, exc
        )
        return None


def compute_iv_rank_from_history(symbol: str, period: str = "1y") -> Optional[float]:
    """Compatibility shim: underlying OHLC cannot establish historical IV rank."""
    del period
    import logging

    logging.getLogger(__name__).info(
        "IV rank unavailable for %s: no historical option-IV source is integrated", symbol
    )
    return None


# ── Payoff calculator ─────────────────────────────────────────


def black_scholes_price(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    vol: float,
    option_type: str,
) -> float:
    """Computes theoretical Black-Scholes price for European / Indian index options."""
    from scipy.stats import norm

    if t_years <= 0 or vol <= 0:
        return max(0.0, spot - strike) if option_type.upper() == "CE" else max(0.0, strike - spot)

    try:
        d1 = (math.log(spot / strike) + (rate + 0.5 * vol**2) * t_years) / (
            vol * math.sqrt(t_years)
        )
        d2 = d1 - vol * math.sqrt(t_years)
        if option_type.upper() == "CE":
            return max(0.0, spot * norm.cdf(d1) - strike * math.exp(-rate * t_years) * norm.cdf(d2))
        else:
            return max(
                0.0, strike * math.exp(-rate * t_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)
            )
    except Exception:
        return max(0.0, spot - strike) if option_type.upper() == "CE" else max(0.0, strike - spot)


def payoff(
    legs: list[PayoffLeg],
    spot_range: Optional[tuple[float, float]] = None,
    steps: int = 50,
    rate: float = RISK_FREE_RATE,
    iv_shift_pct: float = 0.0,
) -> StrategyPayoff:
    """
    Calculate P&L payoff at expiry and theoretical T+0 curve for a multi-leg options strategy.
    Includes statutory transaction cost deduction and aggregated net Greeks.

    Args:
        legs:          List of PayoffLeg (CE/PE/STOCK + BUY/SELL + premium)
        spot_range:    (min_spot, max_spot) — defaults to ±20% of avg strike
        steps:         Number of price points to evaluate
        rate:          Risk-free rate (default RBI repo 6.5%)
        iv_shift_pct:  Simulated IV shift percentage (e.g. +2.0 or -2.0)

    Returns:
        StrategyPayoff with max_profit, max_loss, breakevens, payoff list, t0_payoff, and net Greeks
    """
    if not legs:
        return StrategyPayoff([], 0, 0, [], [])

    avg_strike = sum(l.strike for l in legs) / len(legs)
    lo = spot_range[0] if spot_range else avg_strike * 0.80
    hi = spot_range[1] if spot_range else avg_strike * 1.20
    spots = np.linspace(lo, hi, steps)

    def leg_expiry_pnl(leg: PayoffLeg, spot: float) -> float:
        qty = leg.lots * leg.lot_size
        sign = 1 if leg.transaction == "BUY" else -1
        if leg.option_type == "CE":
            intrinsic = max(0.0, spot - leg.strike)
        elif leg.option_type == "PE":
            intrinsic = max(0.0, leg.strike - spot)
        else:  # STOCK
            intrinsic = spot - leg.strike
        return sign * (intrinsic - leg.premium) * qty

    def leg_t0_pnl(leg: PayoffLeg, spot: float) -> float:
        qty = leg.lots * leg.lot_size
        sign = 1 if leg.transaction == "BUY" else -1
        if leg.option_type == "STOCK":
            return sign * (spot - leg.strike) * qty

        # If DTE or IV not specified, fallback to intrinsic
        dte_val = leg.dte if leg.dte is not None else 0
        iv_val = leg.iv if leg.iv is not None else 0.0
        eff_iv = max(0.01, iv_val + (iv_shift_pct / 100.0)) if iv_val > 0 else 0.0
        t_years = max(0.0, dte_val / 365.0)

        bs_price = black_scholes_price(
            spot=spot,
            strike=leg.strike,
            t_years=t_years,
            rate=rate,
            vol=eff_iv,
            option_type=leg.option_type,
        )
        return sign * (bs_price - leg.premium) * qty

    has_t0 = any(l.dte is not None and l.iv is not None for l in legs)
    payoff_points = []
    t0_points = []
    pnls = []
    t0_pnls = []

    for spot in spots:
        s_flt = float(spot)
        exp_total = sum(leg_expiry_pnl(l, s_flt) for l in legs)
        t0_total = sum(leg_t0_pnl(l, s_flt) for l in legs) if has_t0 else None

        payoff_points.append(
            PayoffPoint(
                round(s_flt, 2),
                round(exp_total, 2),
                round(t0_total, 2) if t0_total is not None else None,
            )
        )
        pnls.append(exp_total)
        if t0_total is not None:
            t0_points.append(PayoffPoint(round(s_flt, 2), round(t0_total, 2)))
            t0_pnls.append(t0_total)

    pnls_arr = np.array(pnls)
    max_profit = float(np.max(pnls_arr))
    max_loss = float(np.min(pnls_arr))

    # Breakevens: sign changes in expiry P&L
    breakevens = []
    for i in range(len(pnls) - 1):
        if pnls[i] * pnls[i + 1] <= 0:
            be = spots[i] + (spots[i + 1] - spots[i]) * (-pnls[i]) / (pnls[i + 1] - pnls[i] + 1e-9)
            breakevens.append(round(float(be), 2))

    # Statutory friction calculation
    tot_charges = 0.0
    try:
        from engine.charges import calculate_roundtrip_charges

        for l in legs:
            qty = l.lots * l.lot_size
            seg = "OPTIONS" if l.option_type in ("CE", "PE") else "EQUITY_INTRADAY"
            _, _, cost = calculate_roundtrip_charges(
                entry_price=l.premium,
                exit_price=l.premium,
                quantity=qty,
                segment=seg,
                entry_side=l.transaction,
            )
            tot_charges += float(cost)
    except Exception as e_fric:
        logger.debug(f"[analysis.options] Statutory friction calculation error: {e_fric}")

    friction_summary = {
        "total_statutory_friction": round(tot_charges, 2),
    }

    # Aggregate Portfolio Greeks
    net_delta = 0.0
    net_gamma = 0.0
    net_theta = 0.0
    net_vega = 0.0
    try:
        for l in legs:
            if l.option_type in ("CE", "PE") and l.iv and l.dte:
                qty = l.lots * l.lot_size
                sign = 1 if l.transaction == "BUY" else -1
                g = compute_greeks(
                    spot=avg_strike,
                    strike=l.strike,
                    expiry="",
                    option_type=l.option_type,
                    ltp=l.premium,
                    rate=rate,
                )
                net_delta += sign * g.delta * qty
                net_gamma += sign * g.gamma * qty
                net_theta += sign * g.theta * qty
                net_vega += sign * g.vega * qty
    except Exception as e_greeks:
        logger.debug(f"[analysis.options] Aggregate Greeks calculation error: {e_greeks}")

    greeks_dict = {
        "portfolio_delta": round(net_delta, 2),
        "portfolio_gamma": round(net_gamma, 4),
        "portfolio_theta": round(net_theta, 2),
        "portfolio_vega": round(net_vega, 2),
    }

    return StrategyPayoff(
        legs=legs,
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        breakevens=breakevens,
        payoff=payoff_points,
        t0_payoff=t0_points,
        net_greeks=greeks_dict,
        friction_breakdown=friction_summary,
        net_max_profit=round(max_profit - tot_charges, 2),
        net_max_loss=round(max_loss - tot_charges, 2),
    )


# ── Full option analysis ──────────────────────────────────────


def analyse_option(
    underlying: str,
    strike: float,
    option_type: str,
    expiry: str,
    spot: float,
) -> OptionAnalysis:
    """Analyse a single option contract — Greeks, breakeven, moneyness."""
    chain = get_options_chain(underlying, expiry)
    contract = next(
        (c for c in chain if c.strike == strike and c.option_type.upper() == option_type.upper()),
        None,
    )
    ltp = contract.last_price if contract else 0.0
    lot_size = contract.lot_size if contract else 1

    greeks = compute_greeks(spot, strike, expiry, option_type, ltp)
    dte = _dte_days(expiry)

    intrinsic = max(0.0, spot - strike) if option_type == "CE" else max(0.0, strike - spot)
    time_value = max(0.0, ltp - intrinsic)

    if option_type == "CE":
        breakeven = strike + ltp
        moneyness = "ITM" if spot > strike else "OTM" if spot < strike else "ATM"
    else:
        breakeven = strike - ltp
        moneyness = "ITM" if spot < strike else "OTM" if spot > strike else "ATM"

    return OptionAnalysis(
        symbol=contract.symbol if contract else f"{underlying}{expiry}{option_type}{strike}",
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        spot=spot,
        ltp=ltp,
        lot_size=lot_size,
        dte=dte,
        greeks=greeks,
        breakeven=round(breakeven, 2),
        intrinsic=round(intrinsic, 2),
        time_value=round(time_value, 2),
        moneyness=moneyness,
        max_loss=round(ltp * lot_size, 2),
    )


# ── Advanced Strategy Builders ───────────────────────────────


def build_iron_condor(
    spot: float,
    lot_size: int,
    call_sell_strike: float,
    call_buy_strike: float,
    put_sell_strike: float,
    put_buy_strike: float,
    call_sell_prem: float,
    call_buy_prem: float,
    put_sell_prem: float,
    put_buy_prem: float,
) -> list[PayoffLeg]:
    """Build an iron condor — sell OTM call spread + sell OTM put spread."""
    return [
        PayoffLeg("CE", "SELL", call_sell_strike, call_sell_prem, lot_size),
        PayoffLeg("CE", "BUY", call_buy_strike, call_buy_prem, lot_size),
        PayoffLeg("PE", "SELL", put_sell_strike, put_sell_prem, lot_size),
        PayoffLeg("PE", "BUY", put_buy_strike, put_buy_prem, lot_size),
    ]


def build_butterfly(
    spot: float,
    lot_size: int,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    lower_prem: float,
    middle_prem: float,
    upper_prem: float,
    option_type: str = "CE",
) -> list[PayoffLeg]:
    """Build a butterfly spread — buy 1 lower, sell 2 middle, buy 1 upper."""
    return [
        PayoffLeg(option_type, "BUY", lower_strike, lower_prem, lot_size, lots=1),
        PayoffLeg(option_type, "SELL", middle_strike, middle_prem, lot_size, lots=2),
        PayoffLeg(option_type, "BUY", upper_strike, upper_prem, lot_size, lots=1),
    ]


def build_calendar_spread(
    strike: float,
    lot_size: int,
    near_prem: float,
    far_prem: float,
    option_type: str = "CE",
) -> list[PayoffLeg]:
    """
    Calendar spread — sell near-term, buy far-term at same strike.
    Profits from faster theta decay of near-term option.
    Note: payoff at near expiry only (far-term value estimated).
    """
    return [
        PayoffLeg(option_type, "SELL", strike, near_prem, lot_size, lots=1),
        PayoffLeg(option_type, "BUY", strike, far_prem, lot_size, lots=1),
    ]


def build_ratio_spread(
    lot_size: int,
    buy_strike: float,
    sell_strike: float,
    buy_prem: float,
    sell_prem: float,
    option_type: str = "CE",
    ratio: int = 2,
) -> list[PayoffLeg]:
    """
    Ratio spread — buy 1 option, sell N options at different strike.
    E.g. buy 1 ATM call, sell 2 OTM calls (1:2 ratio).
    High risk if stock moves beyond short strikes.
    """
    return [
        PayoffLeg(option_type, "BUY", buy_strike, buy_prem, lot_size, lots=1),
        PayoffLeg(option_type, "SELL", sell_strike, sell_prem, lot_size, lots=ratio),
    ]


def build_diagonal_spread(
    lot_size: int,
    near_strike: float,
    far_strike: float,
    near_prem: float,
    far_prem: float,
    option_type: str = "CE",
) -> list[PayoffLeg]:
    """
    Diagonal spread — sell near-term at one strike, buy far-term at different strike.
    Combines calendar + vertical spread characteristics.
    """
    return [
        PayoffLeg(option_type, "SELL", near_strike, near_prem, lot_size, lots=1),
        PayoffLeg(option_type, "BUY", far_strike, far_prem, lot_size, lots=1),
    ]


def suggest_earnings_straddle(
    underlying: str,
    spot: float,
    lot_size: int,
    atm_ce_prem: float,
    atm_pe_prem: float,
    avg_earnings_move: float = 3.0,
) -> dict:
    """
    Evaluate an earnings straddle — buy ATM call + ATM put before results.

    Returns profitability analysis:
    - Total cost of straddle
    - Required move to break even
    - Historical avg move vs breakeven
    - Verdict: FAVORABLE / UNFAVORABLE / MARGINAL
    """
    total_cost = (atm_ce_prem + atm_pe_prem) * lot_size
    breakeven_pct = (atm_ce_prem + atm_pe_prem) / spot * 100
    move_vs_be = avg_earnings_move / breakeven_pct if breakeven_pct > 0 else 0

    if move_vs_be > 1.3:
        verdict = "FAVORABLE"
        reason = f"Avg move ({avg_earnings_move:.1f}%) > breakeven ({breakeven_pct:.1f}%) by {(move_vs_be - 1) * 100:.0f}%"
    elif move_vs_be > 0.9:
        verdict = "MARGINAL"
        reason = (
            f"Avg move ({avg_earnings_move:.1f}%) roughly equals breakeven ({breakeven_pct:.1f}%)"
        )
    else:
        verdict = "UNFAVORABLE"
        reason = f"Avg move ({avg_earnings_move:.1f}%) < breakeven ({breakeven_pct:.1f}%) — straddle too expensive"

    return {
        "underlying": underlying,
        "spot": spot,
        "straddle_cost": round(total_cost, 2),
        "breakeven_pct": round(breakeven_pct, 2),
        "avg_earnings_move": avg_earnings_move,
        "move_vs_breakeven": round(move_vs_be, 2),
        "verdict": verdict,
        "reason": reason,
    }


def optimize_defined_risk_strategies(
    underlying: str,
    spot: float,
    lot_size: int,
    chain: Optional[list[dict[str, Any]]] = None,
    regime: str = "NEUTRAL",
    dte_days: int = 5,
    iv_atm: float = 15.0,
    strike_step: Optional[float] = None,
) -> dict[str, Any]:
    """
    Evaluates and ranks institutional defined-risk options strategies:
      1. Bull Call Spread (Debit)
      2. Bear Put Spread (Debit)
      3. Bull Put Credit Spread (Credit)
      4. Bear Call Credit Spread (Credit)
      5. Iron Condor (Credit)
      6. Iron Butterfly (Credit)

    Calculates net cashflow, maximum profit, maximum loss, risk:reward,
    exact breakevens, net Greeks, probability of profit (POP), and suitability score.
    """
    if spot <= 0 or lot_size <= 0:
        return {"underlying": underlying, "spot": spot, "strategies": [], "regime": regime}

    clean_sym = (
        underlying.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .replace("-INDEX", "")
    )
    if not strike_step or strike_step <= 0:
        if clean_sym == "NIFTY":
            step = 50.0
        elif clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX"):
            step = 100.0
        elif clean_sym in ("FINNIFTY", "MIDCPNIFTY"):
            step = 50.0
        elif spot > 2500:
            step = 50.0
        elif spot > 1000:
            step = 20.0
        elif spot > 500:
            step = 10.0
        else:
            step = 5.0
    else:
        step = float(strike_step)

    atm_strike = round(spot / step) * step

    # Pre-calculate required strikes
    call_atm = atm_strike
    call_otm_1 = atm_strike + step
    call_otm_2 = atm_strike + (2 * step)

    put_atm = atm_strike
    put_otm_1 = atm_strike - step
    put_otm_2 = atm_strike - (2 * step)

    # Option premium resolver (uses live chain quotes when provided, else Black-Scholes)
    def _resolve_prem(strike: float, opt_type: str) -> float:
        if chain:
            for row in chain:
                stk = float(row.get("strike_price") or row.get("strike") or 0.0)
                typ = str(row.get("option_type") or row.get("type") or "").upper()
                if abs(stk - strike) < 0.1 and typ == opt_type:
                    ltp = float(row.get("last_price") or row.get("ltp") or row.get("close") or 0.0)
                    if ltp > 0:
                        return round(ltp, 2)
        # Fallback to Black-Scholes
        t_yrs = max(0.5 / 365.0, dte_days / 365.0)
        p = black_scholes_price(
            spot=spot,
            strike=strike,
            t_years=t_yrs,
            rate=RISK_FREE_RATE,
            vol=max(0.05, iv_atm / 100.0),
            option_type=opt_type,
        )
        return max(1.0, round(float(p), 2))

    c_atm_prem = _resolve_prem(call_atm, "CE")
    c_otm1_prem = _resolve_prem(call_otm_1, "CE")
    c_otm2_prem = _resolve_prem(call_otm_2, "CE")

    p_atm_prem = _resolve_prem(put_atm, "PE")
    p_otm1_prem = _resolve_prem(put_otm_1, "PE")
    p_otm2_prem = _resolve_prem(put_otm_2, "PE")

    # Standard deviation for Probability of Profit (POP) calculation
    t_yrs = max(0.5 / 365.0, dte_days / 365.0)
    sigma = spot * (iv_atm / 100.0) * math.sqrt(t_yrs)

    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    regime_up = regime.upper()

    strategy_specs = [
        {
            "id": "BULL_CALL_SPREAD",
            "name": f"Bull Call Spread ({call_atm:.0f} / {call_otm_1:.0f} CE)",
            "bias": "BULLISH",
            "legs": [
                PayoffLeg(
                    "CE", "BUY", call_atm, c_atm_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "SELL", call_otm_1, c_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "Defined-risk bullish strategy with reduced theta decay via short OTM wing.",
        },
        {
            "id": "BEAR_PUT_SPREAD",
            "name": f"Bear Put Spread ({put_atm:.0f} / {put_otm_1:.0f} PE)",
            "bias": "BEARISH",
            "legs": [
                PayoffLeg(
                    "PE", "BUY", put_atm, p_atm_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "PE", "SELL", put_otm_1, p_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "Defined-risk bearish strategy with capped downside and reduced theta cost.",
        },
        {
            "id": "BULL_PUT_CREDIT_SPREAD",
            "name": f"Bull Put Credit Spread ({put_otm_1:.0f} / {put_otm_2:.0f} PE)",
            "bias": "MODERATE_BULLISH",
            "legs": [
                PayoffLeg(
                    "PE", "SELL", put_otm_1, p_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "PE", "BUY", put_otm_2, p_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "Bullish credit spread collecting premium as long as underlying holds above short put.",
        },
        {
            "id": "BEAR_CALL_CREDIT_SPREAD",
            "name": f"Bear Call Credit Spread ({call_otm_1:.0f} / {call_otm_2:.0f} CE)",
            "bias": "MODERATE_BEARISH",
            "legs": [
                PayoffLeg(
                    "CE", "SELL", call_otm_1, c_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "BUY", call_otm_2, c_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "Bearish credit spread profiting from time decay as long as underlying stays below short call.",
        },
        {
            "id": "IRON_CONDOR",
            "name": f"Iron Condor ({put_otm_2:.0f}P/{put_otm_1:.0f}P & {call_otm_1:.0f}C/{call_otm_2:.0f}C)",
            "bias": "NEUTRAL",
            "legs": [
                PayoffLeg(
                    "PE", "BUY", put_otm_2, p_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "PE", "SELL", put_otm_1, p_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "SELL", call_otm_1, c_otm1_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "BUY", call_otm_2, c_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "Market-neutral range harvest collecting dual OTM credit wings with defined risk.",
        },
        {
            "id": "IRON_BUTTERFLY",
            "name": f"Iron Butterfly ({put_otm_2:.0f}P/{atm_strike:.0f} ATM/{call_otm_2:.0f}C)",
            "bias": "NEUTRAL_PINNED",
            "legs": [
                PayoffLeg(
                    "PE", "BUY", put_otm_2, p_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "PE", "SELL", put_atm, p_atm_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "SELL", call_atm, c_atm_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
                PayoffLeg(
                    "CE", "BUY", call_otm_2, c_otm2_prem, lot_size, dte=dte_days, iv=iv_atm / 100.0
                ),
            ],
            "desc": "High-credit neutral play designed for low-volatility sessions pinning at ATM strike.",
        },
    ]

    evaluated_strategies = []

    for spec in strategy_specs:
        legs: list[PayoffLeg] = spec["legs"]
        po = payoff(legs, spot_range=(spot * 0.85, spot * 1.15))

        # Net cashflow: positive = credit, negative = debit
        net_prem_unit = sum((l.premium if l.transaction == "SELL" else -l.premium) for l in legs)
        net_cashflow = round(net_prem_unit * lot_size, 2)
        flow_type = "CREDIT" if net_cashflow > 0 else "DEBIT"

        max_profit = round(po.max_profit, 2)
        max_loss = round(po.max_loss, 2)
        abs_loss = max(1.0, abs(max_loss))
        rr = round(abs(max_profit / abs_loss), 2)

        # Probability of profit (POP) estimation
        if po.breakevens and sigma > 0:
            if len(po.breakevens) >= 2:
                be_low = min(po.breakevens)
                be_high = max(po.breakevens)
                z_low = (be_low - spot) / sigma
                z_high = (be_high - spot) / sigma
                prob = _norm_cdf(z_high) - _norm_cdf(z_low)
            else:
                be = po.breakevens[0]
                z = (be - spot) / sigma
                prob = (
                    (1.0 - _norm_cdf(z))
                    if spec["bias"] in ("BULLISH", "MODERATE_BULLISH")
                    else _norm_cdf(z)
                )
            pop_pct = round(max(5.0, min(95.0, prob * 100.0)), 1)
        else:
            pop_pct = 50.0

        # Suitability scoring (0-100)
        score = 50.0
        # 1. Regime alignment (up to 40 pts)
        if spec["bias"] in ("BULLISH", "MODERATE_BULLISH"):
            if any(k in regime_up for k in ("BULL", "UP", "BREAKOUT")):
                score += 35
            elif any(k in regime_up for k in ("BEAR", "DOWN", "BREAKDOWN")):
                score -= 30
        elif spec["bias"] in ("BEARISH", "MODERATE_BEARISH"):
            if any(k in regime_up for k in ("BEAR", "DOWN", "BREAKDOWN")):
                score += 35
            elif any(k in regime_up for k in ("BULL", "UP", "BREAKOUT")):
                score -= 30
        elif spec["bias"] in ("NEUTRAL", "NEUTRAL_PINNED"):
            if any(k in regime_up for k in ("NEUTRAL", "RANGE", "SIDEWAYS", "CHOP", "LOW_VOL")):
                score += 35
            elif any(k in regime_up for k in ("BREAKOUT", "TREND", "MOMENTUM")):
                score -= 25

        # 2. Risk/Reward & POP balance (up to 25 pts)
        if flow_type == "CREDIT":
            score += min(20.0, pop_pct * 0.25)
        else:
            score += min(20.0, rr * 8.0)

        suitability = int(max(10, min(98, score)))

        legs_summary = [
            {
                "strike": l.strike,
                "option_type": l.option_type,
                "action": l.transaction,
                "premium": round(l.premium, 2),
                "lots": l.lots,
                "quantity": l.lots * l.lot_size,
            }
            for l in legs
        ]

        evaluated_strategies.append(
            {
                "strategy_id": spec["id"],
                "name": spec["name"],
                "bias": spec["bias"],
                "flow_type": flow_type,
                "net_cashflow": net_cashflow,
                "net_premium_per_share": round(abs(net_prem_unit), 2),
                "max_profit": max_profit,
                "max_loss": max_loss,
                "risk_reward": rr,
                "probability_of_profit_pct": pop_pct,
                "suitability_score": suitability,
                "breakevens": po.breakevens,
                "legs": legs_summary,
                "description": spec["desc"],
            }
        )

    # Sort primarily by suitability score descending
    evaluated_strategies.sort(key=lambda s: s["suitability_score"], reverse=True)

    return {
        "underlying": underlying,
        "spot": spot,
        "lot_size": lot_size,
        "regime": regime,
        "dte_days": dte_days,
        "iv_atm": iv_atm,
        "strike_step": step,
        "atm_strike": atm_strike,
        "strategies": evaluated_strategies,
    }
