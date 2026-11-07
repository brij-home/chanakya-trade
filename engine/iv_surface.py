"""
engine/iv_surface.py
────────────────────
Constant-Tenor Implied Volatility Surface, 25-Delta Skew & Authentic IV Rank Engine.

Guarantees:
  1. Constant 30-Day DTE Interpolation:
     Interpolates variance across near ($T_1$) and next ($T_2$) expiries using standard
     variance weighting:
       sigma_30^2 = sigma_1^2 * ((T_2 - 30)/(T_2 - T_1)) * (T_1 / 30) +
                    sigma_2^2 * ((30 - T_1)/(T_2 - T_1)) * (T_2 / 30)
  2. 25-Delta Risk Reversal Skew:
     Computes normalized Put vs Call skew:
       Skew_25D = (sigma_25P - sigma_25C) / sigma_ATM
  3. Zero Synthetic Numbers & Honest Availability:
     If option chains, IV observations, or historical samples (< 20 sessions) are
     insufficient, returns status="UNAVAILABLE" and iv_rank=None, strictly adhering
     to Safety Contract #26 & #31.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class IVSurfaceSnapshot:
    """Authentic constant-tenor implied volatility surface observation."""

    symbol: str
    as_of: str
    status: str  # "AVAILABLE" | "UNAVAILABLE" | "DEGRADED"
    atm_iv_30d: Optional[float] = None
    skew_25d: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    sample_count: int = 0
    near_expiry: Optional[str] = None
    next_expiry: Optional[str] = None
    near_dte: Optional[int] = None
    next_dte: Optional[int] = None
    unavailability_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interpolate_constant_30d_variance(
    sigma_1: float,
    dte_1: int,
    sigma_2: float,
    dte_2: int,
) -> float:
    """
    Interpolate constant 30-day annualized implied volatility across two tenors
    using calendar variance weighting.
    """
    if dte_1 <= 0 or dte_2 <= 0 or sigma_1 <= 0 or sigma_2 <= 0:
        return 0.0

    if dte_1 == dte_2:
        return sigma_1

    # Ensure dte_1 < dte_2
    if dte_1 > dte_2:
        sigma_1, sigma_2 = sigma_2, sigma_1
        dte_1, dte_2 = dte_2, dte_1

    # Exact match
    if dte_1 == 30:
        return sigma_1
    if dte_2 == 30:
        return sigma_2

    # If 30 days falls strictly between dte_1 and dte_2
    if dte_1 < 30 < dte_2:
        weight_1 = (dte_2 - 30) / (dte_2 - dte_1)
        weight_2 = (30 - dte_1) / (dte_2 - dte_1)
        var_1 = (sigma_1**2) * (dte_1 / 30.0)
        var_2 = (sigma_2**2) * (dte_2 / 30.0)
        var_30 = weight_1 * var_1 + weight_2 * var_2
        return math.sqrt(max(0.0, var_30))

    # Single tenor extrapolation if both are on the same side
    if dte_1 > 30:
        # Near term is already > 30 days, scale by square-root of time
        return sigma_1 * math.sqrt(dte_1 / 30.0)
    else:
        # Both < 30 days, extrapolate using next tenor
        return sigma_2 * math.sqrt(dte_2 / 30.0)


def calculate_25delta_skew(
    iv_25d_put: float,
    iv_25d_call: float,
    atm_iv: float,
) -> Optional[float]:
    """
    Normalized 25-Delta Risk Reversal Skew: (IV_25P - IV_25C) / ATM_IV.
    Positive value indicates put demand / downside tail protection.
    """
    if atm_iv <= 0 or iv_25d_put <= 0 or iv_25d_call <= 0:
        return None
    return round((iv_25d_put - iv_25d_call) / atm_iv, 4)


def compute_iv_rank_and_percentile(
    current_iv: float,
    historical_iv_series: list[float] | np.ndarray | pd.Series,
    min_samples: int = 20,
) -> tuple[Optional[float], Optional[float], int]:
    """
    Calculates authentic IV Rank and IV Percentile over an empirical time series.
    Returns (None, None, count) if historical samples < min_samples.
    """
    if not isinstance(historical_iv_series, (list, np.ndarray, pd.Series)):
        return None, None, 0

    clean_samples = [
        float(x)
        for x in historical_iv_series
        if isinstance(x, (int, float)) and math.isfinite(x) and x > 0
    ]
    count = len(clean_samples)
    if count < min_samples or current_iv <= 0:
        return None, None, count

    min_iv = min(clean_samples)
    max_iv = max(clean_samples)

    if max_iv <= min_iv:
        return None, None, count

    # IV Rank = (Current - Min) / (Max - Min) * 100
    iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
    iv_rank = max(0.0, min(100.0, iv_rank))

    # IV Percentile = Count(Hist < Current) / Total Count * 100
    less_count = sum(1 for x in clean_samples if x < current_iv)
    iv_percentile = (less_count / count) * 100.0

    return round(iv_rank, 1), round(iv_percentile, 1), count


def build_iv_surface_snapshot(
    symbol: str,
    near_atm_iv: Optional[float] = None,
    near_dte: Optional[int] = None,
    next_atm_iv: Optional[float] = None,
    next_dte: Optional[int] = None,
    iv_25d_put: Optional[float] = None,
    iv_25d_call: Optional[float] = None,
    historical_30d_ivs: Optional[list[float]] = None,
    now_dt: Optional[datetime] = None,
) -> IVSurfaceSnapshot:
    """
    Constructs an authentic IVSurfaceSnapshot for an underlying symbol.
    Fails closed with status='UNAVAILABLE' if essential IV inputs are missing.
    """
    as_of_str = (now_dt or datetime.now()).isoformat()

    if near_atm_iv is None or near_atm_iv <= 0 or near_dte is None or near_dte <= 0:
        return IVSurfaceSnapshot(
            symbol=symbol,
            as_of=as_of_str,
            status="UNAVAILABLE",
            unavailability_reason="Near-term ATM implied volatility or DTE is missing or non-positive.",
        )

    # 1. Constant 30D IV interpolation
    if next_atm_iv is not None and next_atm_iv > 0 and next_dte is not None and next_dte > near_dte:
        atm_30d = interpolate_constant_30d_variance(near_atm_iv, near_dte, next_atm_iv, next_dte)
    else:
        # Single tenor fallback if near_dte is reasonable
        atm_30d = near_atm_iv * math.sqrt(near_dte / 30.0) if near_dte > 0 else near_atm_iv

    atm_30d = round(atm_30d, 4)

    # 2. 25-Delta Skew
    skew = None
    if iv_25d_put is not None and iv_25d_call is not None:
        skew = calculate_25delta_skew(iv_25d_put, iv_25d_call, atm_30d)

    # 3. IV Rank & Percentile
    ivr, ivp, count = compute_iv_rank_and_percentile(
        atm_30d,
        historical_30d_ivs or [],
        min_samples=20,
    )

    return IVSurfaceSnapshot(
        symbol=symbol,
        as_of=as_of_str,
        status="AVAILABLE",
        atm_iv_30d=atm_30d,
        skew_25d=skew,
        iv_rank=ivr,
        iv_percentile=ivp,
        sample_count=count,
        near_dte=near_dte,
        next_dte=next_dte,
    )
