"""
engine/rule_schedule_signals.py
───────────────────────────────
Causal, effective-dated signal context helpers for SEBI Dec 7, 2026 CAS & Expiry Settlement windows.

Enforces docs/SAFETY_CONTRACTS.md:
- Never activate Dec 7, 2026 CAS/post-cash derivative windows before 2026-12-07.
- Expiry 30-min VWAP determination window (15:00-15:30 IST) applies only when `is_expiry=True`.
- Research/shadow context only until validated on held-out causal replay.
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.constants import IST
from market.rule_schedule import (
    closing_vwap_window,
    is_cas_derivative_dispersion_window,
    is_cas_window,
)


def evaluate_expiry_vwap_window(
    symbol: str,
    df_5m: Optional[pd.DataFrame],
    spot: float,
    ref_dt: Optional[datetime] = None,
    *,
    is_expiry: bool = False,
) -> dict[str, Any]:
    """Compute causal 15:00-15:30 IST expiry VWAP tracking metrics without look-ahead."""
    now_dt = (ref_dt or datetime.now(IST)).astimezone(IST)
    if not closing_vwap_window(now_dt, is_expiry=is_expiry) or spot <= 0:
        return {"status": "INACTIVE", "symbol": symbol, "is_expiry": bool(is_expiry)}

    if df_5m is None or len(df_5m) == 0:
        return {"status": "UNAVAILABLE", "symbol": symbol, "reason": "NO_INTRADAY_BARS"}

    try:
        df_sub = df_5m
        if hasattr(df_5m.index, "date") and hasattr(df_5m.index, "time"):
            mask = (
                (df_5m.index.date == now_dt.date())
                & (df_5m.index.time >= dtime(15, 0))
                & (df_5m.index.time <= now_dt.time())
            )
            filtered = df_5m[mask]
            if len(filtered) >= 1:
                df_sub = filtered
            else:
                return {"status": "UNAVAILABLE", "symbol": symbol, "reason": "NO_1500_WINDOW_BARS"}

        col_h = "high" if "high" in df_sub.columns else "High"
        col_l = "low" if "low" in df_sub.columns else "Low"
        col_c = "close" if "close" in df_sub.columns else "Close"
        col_v = "volume" if "volume" in df_sub.columns else "Volume"

        tp = (
            df_sub[col_h].astype(float) + df_sub[col_l].astype(float) + df_sub[col_c].astype(float)
        ) / 3.0
        vols = (
            df_sub[col_v].astype(float)
            if col_v in df_sub.columns
            else pd.Series(1.0, index=df_sub.index)
        )
        tot_v = float(np.sum(vols))
        vwap_1500 = float(np.sum(tp * vols) / tot_v) if tot_v > 0 else float(np.mean(tp))
        div_pct = ((spot - vwap_1500) / vwap_1500 * 100.0) if vwap_1500 > 0 else 0.0
        return {
            "status": "AVAILABLE",
            "research_only": True,
            "symbol": symbol,
            "vwap_1500": round(vwap_1500, 2),
            "spot": round(float(spot), 2),
            "divergence_pct": round(div_pct, 4),
            "bars_sampled": int(len(df_sub)),
        }
    except Exception as exc:
        return {"status": "UNAVAILABLE", "symbol": symbol, "reason": str(exc)}


def evaluate_cas_derivative_dispersion(
    symbol: str,
    fut_ltp: Optional[float],
    spot_ltp: Optional[float],
    ref_dt: Optional[datetime] = None,
) -> dict[str, Any]:
    """Measure futures vs cash basis during post-Dec 7, 2026 CAS dispersion window (15:25-15:45 IST)."""
    now_dt = (ref_dt or datetime.now(IST)).astimezone(IST)
    if not is_cas_derivative_dispersion_window(now_dt):
        return {
            "status": "INACTIVE",
            "symbol": symbol,
            "cas_active": is_cas_window(now_dt),
        }

    if not fut_ltp or not spot_ltp or fut_ltp <= 0 or spot_ltp <= 0:
        return {"status": "UNAVAILABLE", "symbol": symbol, "reason": "MISSING_FUT_OR_SPOT"}

    basis_pts = float(fut_ltp) - float(spot_ltp)
    basis_bps = (basis_pts / float(spot_ltp)) * 10000.0
    if basis_bps >= 15.0:
        regime = "FUTURES_PREMIUM_EXPANSION"
    elif basis_bps <= -15.0:
        regime = "FUTURES_DISCOUNT_EXPANSION"
    else:
        regime = "BASIS_EQUILIBRIUM"

    return {
        "status": "AVAILABLE",
        "research_only": True,
        "symbol": symbol,
        "cas_active": is_cas_window(now_dt),
        "basis_pts": round(basis_pts, 2),
        "basis_bps": round(basis_bps, 2),
        "dispersion_regime": regime,
    }
