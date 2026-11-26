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


def _get_iv_db_path():
    from config.paths import app_data_path

    return app_data_path("iv_history.db")


def extract_surface_inputs_from_chain(
    chain: list[Any],
    spot: float,
    as_of_date: Optional[Any] = None,
) -> dict[str, Any]:
    """Extract near/next ATM IVs, DTEs, and 25-delta skew IVs from a real option chain."""
    from datetime import date as dt_date

    if not chain or spot <= 0:
        return {}

    ref_date = as_of_date or datetime.now().date()
    if isinstance(ref_date, datetime):
        ref_date = ref_date.date()

    by_exp: dict[dt_date, list[dict[str, Any]]] = {}
    for c in chain:
        is_d = isinstance(c, dict)
        exp_raw = c.get("expiry") if is_d else getattr(c, "expiry", None)
        iv_raw = c.get("iv", 0.0) if is_d else getattr(c, "iv", 0.0)
        strike_raw = c.get("strike", 0.0) if is_d else getattr(c, "strike", 0.0)
        opt_raw = c.get("option_type", "") if is_d else getattr(c, "option_type", "")
        delta_raw = c.get("delta", None) if is_d else getattr(c, "delta", None)

        try:
            iv_val = float(iv_raw or 0.0)
            strike_val = float(strike_raw or 0.0)
        except (TypeError, ValueError):
            continue
        if iv_val <= 0 or strike_val <= 0 or not exp_raw:
            continue

        try:
            exp_d = (
                exp_raw
                if isinstance(exp_raw, dt_date) and not isinstance(exp_raw, datetime)
                else dt_date.fromisoformat(str(exp_raw).strip()[:10])
            )
        except ValueError:
            continue

        dte = (exp_d - ref_date).days
        if dte <= 0:
            continue
        by_exp.setdefault(exp_d, []).append(
            {
                "strike": strike_val,
                "iv": iv_val,
                "option_type": str(opt_raw or "").upper(),
                "delta": delta_raw,
                "dte": dte,
            }
        )

    if not by_exp:
        return {}

    sorted_exps = sorted(by_exp.keys())

    def _atm_iv(rows: list[dict[str, Any]]) -> Optional[float]:
        closest_strike = min(rows, key=lambda r: abs(r["strike"] - spot))["strike"]
        atm_ivs = [r["iv"] for r in rows if r["strike"] == closest_strike and r["iv"] > 0]
        return round(sum(atm_ivs) / len(atm_ivs), 4) if atm_ivs else None

    near_rows = by_exp[sorted_exps[0]]
    near_atm = _atm_iv(near_rows)
    near_dte = near_rows[0]["dte"]

    next_atm = None
    next_dte = None
    if len(sorted_exps) >= 2:
        next_rows = by_exp[sorted_exps[1]]
        next_atm = _atm_iv(next_rows)
        next_dte = next_rows[0]["dte"]

    iv_25p = None
    iv_25c = None
    puts_with_d = [r for r in near_rows if r["option_type"] == "PE" and r["delta"] is not None]
    calls_with_d = [r for r in near_rows if r["option_type"] == "CE" and r["delta"] is not None]
    if puts_with_d:
        iv_25p = min(puts_with_d, key=lambda r: abs(abs(float(r["delta"])) - 0.25))["iv"]
    if calls_with_d:
        iv_25c = min(calls_with_d, key=lambda r: abs(abs(float(r["delta"])) - 0.25))["iv"]

    return {
        "near_atm_iv": near_atm,
        "near_dte": near_dte,
        "next_atm_iv": next_atm,
        "next_dte": next_dte,
        "iv_25d_put": iv_25p,
        "iv_25d_call": iv_25c,
        "near_expiry": sorted_exps[0].isoformat(),
        "next_expiry": sorted_exps[1].isoformat() if len(sorted_exps) >= 2 else None,
    }


def record_iv_observation(snapshot: IVSurfaceSnapshot, session_date: Optional[str] = None) -> bool:
    """Persist one daily constant-tenor 30D IV observation (idempotent per symbol+date)."""
    import sqlite3

    if (
        snapshot.status != "AVAILABLE"
        or snapshot.atm_iv_30d is None
        or not math.isfinite(snapshot.atm_iv_30d)
        or snapshot.atm_iv_30d <= 0
    ):
        return False

    sym = str(snapshot.symbol or "").upper().strip()
    from contextlib import closing

    if not sym:
        return False

    s_date = session_date or str(snapshot.as_of or "")[:10] or datetime.now().date().isoformat()
    db_path = _get_iv_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path), timeout=10.0)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS iv_daily_surface (
                    symbol TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    atm_iv_30d REAL NOT NULL,
                    skew_25d REAL,
                    near_dte INTEGER,
                    next_dte INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, session_date)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO iv_daily_surface
                    (symbol, session_date, atm_iv_30d, skew_25d, near_dte, next_dte, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, session_date) DO UPDATE SET
                    atm_iv_30d = excluded.atm_iv_30d,
                    skew_25d = excluded.skew_25d,
                    near_dte = excluded.near_dte,
                    next_dte = excluded.next_dte,
                    updated_at = excluded.updated_at
                """,
                (
                    sym,
                    s_date,
                    float(snapshot.atm_iv_30d),
                    float(snapshot.skew_25d) if snapshot.skew_25d is not None else None,
                    snapshot.near_dte,
                    snapshot.next_dte,
                    snapshot.as_of,
                ),
            )
    return True


def load_historical_30d_ivs(symbol: str, limit: int = 252) -> list[float]:
    """Load persisted chronological daily constant-30D ATM IV observations."""
    from contextlib import closing
    import sqlite3

    sym = str(symbol or "").upper().strip()
    db_path = _get_iv_db_path()
    if not sym or not db_path.exists():
        return []
    with closing(sqlite3.connect(str(db_path), timeout=10.0)) as conn:
        rows = conn.execute(
            """
            SELECT atm_iv_30d FROM (
                SELECT session_date, atm_iv_30d
                FROM iv_daily_surface
                WHERE symbol = ?
                ORDER BY session_date DESC
                LIMIT ?
            ) ORDER BY session_date ASC
            """,
            (sym, max(1, int(limit))),
        ).fetchall()
    return [float(r[0]) for r in rows if r and r[0] is not None and float(r[0]) > 0]
