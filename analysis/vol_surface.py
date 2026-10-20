"""
analysis/vol_surface.py
────────────────────────
Institutional Quantitative Volatility Surface & Smile Modeler using Hagan's SABR (2002).

Implements:
1. Hagan et al. (2002) asymptotic expansion for Black-76 implied volatility.
2. Calibration of (alpha, beta, rho, nu) via bounded numerical optimization (L-BFGS-B / Nelder-Mead).
3. Arbitrage-free continuous smile interpolation across dense strike grids.
4. Quantitative strike mispricing detector (identifies overpriced/underpriced options wings).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger("analysis.vol_surface")


@dataclass(frozen=True)
class SABRParameters:
    alpha: float  # Volatility level (> 0)
    beta: float  # CEV elasticity (0.0 to 1.0, fixed)
    rho: float  # Spot-vol correlation (-1.0 to 1.0)
    nu: float  # Volatility of volatility (> 0)
    rmse: float  # Root Mean Squared Error (pts)
    mae: float  # Mean Absolute Error (pts)
    converged: bool = True


@dataclass(frozen=True)
class StrikeMispricing:
    strike: float
    market_iv: float
    sabr_iv: float
    iv_edge_pts: float  # market_iv - sabr_iv
    edge_pct: float
    verdict: Literal["OVERPRICED", "UNDERPRICED", "FAIR"]
    recommendation: str


@dataclass
class SABRCalibrationResult:
    underlying: str
    forward_price: float
    expiry_years: float
    dte_days: float
    parameters: SABRParameters
    mispricings: list[StrikeMispricing] = field(default_factory=list)
    fitted_strikes: list[float] = field(default_factory=list)
    fitted_ivs: list[float] = field(default_factory=list)
    skew_verdict: str = "SYMMETRIC"


def sabr_implied_volatility(
    f: float,
    k: float,
    t: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    """
    Computes Black-76 implied volatility using the Hagan et al. (2002) expansion.

    Args:
        f: Forward price of underlying (> 0)
        k: Strike price (> 0)
        t: Time to expiry in years (> 0)
        alpha: Initial volatility parameter (> 0)
        beta: CEV parameter [0.0, 1.0]
        rho: Correlation between asset price and volatility [-1.0, 1.0]
        nu: Volatility of volatility (> 0)

    Returns:
        Implied volatility in percentage points (e.g., 18.5 for 18.5%).
    """
    if f <= 0.0 or k <= 0.0 or t <= 0.0 or alpha <= 0.0:
        return 0.0

    # Near ATM boundary condition
    log_fk = math.log(f / k)
    one_minus_beta = 1.0 - beta

    if abs(log_fk) < 1e-6:
        # Exact ATM formula
        f_pow = f**one_minus_beta
        term1 = (one_minus_beta**2 / 24.0) * (alpha**2 / (f_pow**2))
        term2 = 0.25 * (rho * beta * nu * alpha) / f_pow
        term3 = ((2.0 - 3.0 * rho**2) / 24.0) * (nu**2)
        multiplier = 1.0 + (term1 + term2 + term3) * t
        atm_vol = (alpha / f_pow) * multiplier
        return max(0.001, atm_vol * 100.0)

    fk = f * k
    fk_beta = fk ** (one_minus_beta / 2.0)
    denom = fk_beta * (
        1.0
        + (one_minus_beta**2 / 24.0) * (log_fk**2)
        + ((one_minus_beta**4) / 1920.0) * (log_fk**4)
    )

    z = (nu / alpha) * fk_beta * log_fk

    # Numerical stability for x(z) as z -> 0
    disc = 1.0 - 2.0 * rho * z + z * z
    if disc < 0.0:
        disc = 0.0
    sqrt_disc = math.sqrt(disc)

    arg = (sqrt_disc + z - rho) / (1.0 - rho)
    if arg <= 0.0 or abs(z) < 1e-6:
        z_over_xz = 1.0
    else:
        xz = math.log(arg)
        z_over_xz = z / xz if abs(xz) > 1e-7 else 1.0

    term1 = (one_minus_beta**2 / 24.0) * (alpha**2 / (fk**one_minus_beta))
    term2 = 0.25 * (rho * beta * nu * alpha) / fk_beta
    term3 = ((2.0 - 3.0 * rho**2) / 24.0) * (nu**2)
    multiplier = 1.0 + (term1 + term2 + term3) * t

    vol = (alpha / denom) * z_over_xz * multiplier
    return max(0.001, vol * 100.0)


def calibrate_sabr(
    forward_price: float,
    strikes: Sequence[float],
    market_ivs: Sequence[float],
    t_years: float,
    beta: float = 0.7,
    weights: Optional[Sequence[float]] = None,
) -> SABRParameters:
    """
    Calibrates Hagan's SABR model parameters (alpha, rho, nu) to market quotes
    using bounded nonlinear least squares.

    Args:
        forward_price: Underlying forward or spot price.
        strikes: Sequence of strike prices.
        market_ivs: Corresponding market implied volatilities in percent (e.g. [15.2, 14.8, ...]).
        t_years: Time to expiration in years.
        beta: Fixed elasticity parameter (default 0.7 typical for Indian equity indices).
        weights: Optional weighting for each strike (e.g., inverse spread or open interest).

    Returns:
        SABRParameters with calibrated alpha, rho, nu and error metrics.
    """
    if len(strikes) != len(market_ivs) or len(strikes) < 3 or t_years <= 0:
        # Fallback parameters
        mean_iv = float(np.mean(market_ivs)) if len(market_ivs) > 0 else 15.0
        alpha_init = (mean_iv / 100.0) * (forward_price ** (1.0 - beta))
        return SABRParameters(
            alpha=alpha_init,
            beta=beta,
            rho=-0.3,
            nu=0.4,
            rmse=0.0,
            mae=0.0,
            converged=False,
        )

    k_arr = np.array(strikes, dtype=float)
    iv_arr = np.array(market_ivs, dtype=float)

    if weights is not None:
        w_arr = np.array(weights, dtype=float)
        w_arr = w_arr / (np.sum(w_arr) or 1.0)
    else:
        w_arr = np.ones_like(k_arr) / len(k_arr)

    # Initial guess: estimate alpha from ATM strike
    atm_idx = int(np.argmin(np.abs(k_arr - forward_price)))
    atm_iv_decimal = (iv_arr[atm_idx] or 15.0) / 100.0
    alpha_init = max(0.001, atm_iv_decimal * (forward_price ** (1.0 - beta)))

    # Objective function
    def objective(params: np.ndarray) -> float:
        a, r, n = params
        errors = []
        for i, k in enumerate(k_arr):
            model_iv = sabr_implied_volatility(forward_price, k, t_years, a, beta, r, n)
            err = (model_iv - iv_arr[i]) ** 2
            errors.append(err * w_arr[i])
        return float(np.sum(errors))

    # Parameter bounds: alpha in (0.001, 10.0), rho in (-0.999, 0.999), nu in (0.001, 10.0)
    bounds = [(0.001, 10.0), (-0.995, 0.995), (0.001, 8.0)]
    initial_guess = [alpha_init, -0.3, 0.5]

    try:
        res = minimize(
            objective,
            initial_guess,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 200, "ftol": 1e-7},
        )
        if not res.success:
            # Try Nelder-Mead if L-BFGS-B struggled
            res = minimize(
                objective,
                initial_guess,
                method="Nelder-Mead",
                bounds=bounds,
                options={"maxiter": 300},
            )
        opt_alpha, opt_rho, opt_nu = res.x
        converged = bool(res.success)
    except Exception as e:
        logger.warning(f"[analysis.vol_surface] Optimization fallback: {e}")
        opt_alpha, opt_rho, opt_nu = initial_guess
        converged = False

    # Calculate model IVs and error metrics
    model_ivs = [
        sabr_implied_volatility(forward_price, k, t_years, opt_alpha, beta, opt_rho, opt_nu)
        for k in k_arr
    ]
    diffs = np.array(model_ivs) - iv_arr
    rmse = float(np.sqrt(np.mean(diffs**2)))
    mae = float(np.mean(np.abs(diffs)))

    return SABRParameters(
        alpha=float(opt_alpha),
        beta=float(beta),
        rho=float(opt_rho),
        nu=float(opt_nu),
        rmse=round(rmse, 3),
        mae=round(mae, 3),
        converged=converged,
    )


def interpolate_sabr_smile(
    forward_price: float,
    t_years: float,
    params: SABRParameters,
    strike_min: float,
    strike_max: float,
    num_points: int = 50,
) -> tuple[list[float], list[float]]:
    """
    Generates a dense, smooth, arbitrage-free continuous volatility smile curve.

    Returns:
        (strikes, implied_volatilities)
    """
    if strike_min >= strike_max or num_points <= 1:
        return [], []

    dense_strikes = np.linspace(strike_min, strike_max, num_points).tolist()
    dense_ivs = [
        round(
            sabr_implied_volatility(
                forward_price,
                k,
                t_years,
                params.alpha,
                params.beta,
                params.rho,
                params.nu,
            ),
            2,
        )
        for k in dense_strikes
    ]
    return dense_strikes, dense_ivs


def detect_strike_mispricings(
    forward_price: float,
    strikes: Sequence[float],
    market_ivs: Sequence[float],
    t_years: float,
    params: SABRParameters,
    mispricing_threshold_pts: float = 1.5,
) -> list[StrikeMispricing]:
    """
    Identifies options strikes trading significantly disjoint from theoretical SABR smile.
    Flags overvalued (short vol edge) and undervalued (long vol edge) contracts.
    """
    mispricings: list[StrikeMispricing] = []

    for k, mkt_iv in zip(strikes, market_ivs):
        if mkt_iv <= 0:
            continue
        sabr_iv = sabr_implied_volatility(
            forward_price, k, t_years, params.alpha, params.beta, params.rho, params.nu
        )
        edge_pts = round(mkt_iv - sabr_iv, 2)
        edge_pct = round((edge_pts / max(0.01, sabr_iv)) * 100.0, 2)

        if edge_pts >= mispricing_threshold_pts:
            verdict: Literal["OVERPRICED", "UNDERPRICED", "FAIR"] = "OVERPRICED"
            rec = f"Sell Volatility / Credit Spread: Strike {k} IV exceeds theoretical smile by +{edge_pts:.1f} pts."
        elif edge_pts <= -mispricing_threshold_pts:
            verdict = "UNDERPRICED"
            rec = f"Buy Volatility / Debit Spread: Strike {k} IV discounted vs theoretical smile by {edge_pts:.1f} pts."
        else:
            verdict = "FAIR"
            rec = "Priced in equilibrium with smile curve."

        mispricings.append(
            StrikeMispricing(
                strike=float(k),
                market_iv=round(float(mkt_iv), 2),
                sabr_iv=round(sabr_iv, 2),
                iv_edge_pts=edge_pts,
                edge_pct=edge_pct,
                verdict=verdict,
                recommendation=rec,
            )
        )

    return mispricings


def analyze_volatility_surface(
    underlying: str,
    expiry: Optional[str] = None,
    beta: float = 0.7,
) -> Optional[SABRCalibrationResult]:
    """
    Full pipeline: Pulls options chain for underlying, fits Hagan's SABR model,
    detects edge mispricings, and returns complete institutional surface calibration.
    """
    try:
        from market.options import get_options_chain
        from market.quotes import get_ltp
        from analysis.options import _dte_days

        spot = get_ltp(f"NSE:{underlying}")
        if spot <= 0:
            return None

        chain = get_options_chain(underlying, expiry)
        if not chain:
            return None

        resolved_exp = chain[0].expiry if chain and chain[0].expiry else (expiry or "")
        dte = _dte_days(resolved_exp) if resolved_exp else 7.0
        t_years = max(1.0 / 365.0, dte / 365.0)

        # Build clean strike to IV map (prioritize OTM options for true smile)
        strike_data: dict[float, float] = {}
        for c in chain:
            s = float(c.strike)
            iv = c.iv
            if iv is None or iv <= 0:
                continue

            # Pure quantitative smile: use OTM put below spot, OTM call above spot
            if s <= spot and c.option_type == "PE":
                strike_data[s] = float(iv)
            elif s > spot and c.option_type == "CE":
                strike_data[s] = float(iv)
            elif s not in strike_data:
                strike_data[s] = float(iv)

        if len(strike_data) < 3:
            return None

        sorted_strikes = sorted(strike_data.keys())
        market_ivs = [strike_data[k] for k in sorted_strikes]

        # Calibrate SABR parameters
        params = calibrate_sabr(
            forward_price=spot,
            strikes=sorted_strikes,
            market_ivs=market_ivs,
            t_years=t_years,
            beta=beta,
        )

        # Detect mispricings
        mispricings = detect_strike_mispricings(
            forward_price=spot,
            strikes=sorted_strikes,
            market_ivs=market_ivs,
            t_years=t_years,
            params=params,
        )

        # Dense smile curve
        k_min = min(sorted_strikes) * 0.97
        k_max = max(sorted_strikes) * 1.03
        dense_k, dense_iv = interpolate_sabr_smile(
            forward_price=spot,
            t_years=t_years,
            params=params,
            strike_min=k_min,
            strike_max=k_max,
            num_points=40,
        )

        skew_label = (
            "PUT_SKEW"
            if params.rho < -0.15
            else ("CALL_SKEW" if params.rho > 0.15 else "SYMMETRIC")
        )

        return SABRCalibrationResult(
            underlying=underlying,
            forward_price=spot,
            expiry_years=round(t_years, 4),
            dte_days=dte,
            parameters=params,
            mispricings=mispricings,
            fitted_strikes=dense_k,
            fitted_ivs=dense_iv,
            skew_verdict=skew_label,
        )
    except Exception as e:
        logger.error(
            f"[analysis.vol_surface] Failed to analyze surface for {underlying}: {e}", exc_info=True
        )
        return None
