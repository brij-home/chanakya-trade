"""
engine/cas_dispersion.py
────────────────────────
Effective-Dated Closing Auction Session (CAS) Dispersion & Expiry Settlement VWAP Guard.

Anchored strictly to `market/rule_schedule.py`:
  - Before 2026-12-07: post-cash CAS derivative dispersion window is INACTIVE (False),
    derivatives close per historical schedule (15:30 / 15:40 IST).
  - From 2026-12-07 (SEBI 23843/2026):
      * Cash equities close continuous session at 15:30 and run CAS 15:30-15:40 IST.
      * Expiring index derivatives halt at 15:30 IST with 15:00-15:30 closing VWAP settlement.
      * Non-expiring index & stock derivatives trade until 15:45 IST (`is_cas_derivative_dispersion_window`
        from 15:25-15:45 IST).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol
from engine.option_resolver import is_index_symbol
from market.rule_schedule import (
    closing_vwap_window,
    derivative_close,
    intraday_entry_cutoff,
    is_cas_derivative_dispersion_window,
    is_cas_window,
)


def assess_expiry_vwap_tracking(
    symbol: str,
    *,
    spot: float,
    bars_intraday: Optional[pd.DataFrame] = None,
    as_of: Optional[datetime] = None,
    is_expiry: bool = False,
    gex_pin_strike: Optional[float] = None,
) -> dict[str, Any]:
    """Compute expiry-day 15:00-15:30 closing VWAP tracking error & GEX pin diagnostics."""
    clean = canonical_alert_symbol(symbol).upper()
    ref_dt = as_of or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)

    in_vwap_win = closing_vwap_window(ref_dt, is_expiry=is_expiry)
    if not is_expiry or spot <= 0:
        return {
            "symbol": clean,
            "as_of": ref_dt.isoformat(),
            "is_expiry": bool(is_expiry),
            "in_closing_vwap_window": in_vwap_win,
            "settlement_vwap": None,
            "tracking_error_bps": None,
            "drift_flag": "NOT_APPLICABLE",
            "gex_pin_aligned": False,
        }

    settlement_vwap: Optional[float] = None
    if (
        bars_intraday is not None
        and not bars_intraday.empty
        and isinstance(bars_intraday.index, pd.DatetimeIndex)
    ):
        idx = bars_intraday.index
        if idx.tz is not None:
            idx_local = idx.tz_convert(IST).tz_localize(None)
        else:
            idx_local = idx
        ref_date = ref_dt.date()
        mask = (
            (idx_local.date == ref_date)
            & (idx_local.time >= time(15, 0))
            & (idx_local.time <= min(ref_dt.time(), time(15, 30)))
        )
        sub = bars_intraday.loc[mask]
        if not sub.empty:
            col_map = {str(c).lower(): c for c in sub.columns}
            if {"high", "low", "close"}.issubset(col_map):
                tp = (
                    sub[col_map["high"]].astype(float)
                    + sub[col_map["low"]].astype(float)
                    + sub[col_map["close"]].astype(float)
                ) / 3.0
            elif "close" in col_map:
                tp = sub[col_map["close"]].astype(float)
            else:
                tp = pd.Series(dtype=float)

            if not tp.empty:
                if "volume" in col_map:
                    vol = sub[col_map["volume"]].astype(float).clip(lower=0.0)
                    v_sum = float(vol.sum())
                    if v_sum > 0:
                        settlement_vwap = round(float((tp * vol).sum() / v_sum), 2)
                if settlement_vwap is None and len(tp) > 0:
                    settlement_vwap = round(float(np.mean(tp)), 2)

    if settlement_vwap is None or settlement_vwap <= 0:
        return {
            "symbol": clean,
            "as_of": ref_dt.isoformat(),
            "is_expiry": True,
            "in_closing_vwap_window": in_vwap_win,
            "settlement_vwap": None,
            "tracking_error_bps": None,
            "drift_flag": "UNAVAILABLE",
            "gex_pin_aligned": False,
        }

    err_bps = round(((float(spot) - settlement_vwap) / settlement_vwap) * 10000.0, 2)
    if abs(err_bps) >= 20.0:
        drift_flag = "VWAP_SETTLEMENT_DRIFT_HIGH"
    elif abs(err_bps) >= 10.0:
        drift_flag = "VWAP_SETTLEMENT_DRIFT_MODERATE"
    else:
        drift_flag = "TRACKING_TIGHT"

    pin_aligned = bool(
        gex_pin_strike is not None
        and gex_pin_strike > 0
        and abs(settlement_vwap - float(gex_pin_strike)) / settlement_vwap <= 0.0025
    )
    return {
        "symbol": clean,
        "as_of": ref_dt.isoformat(),
        "is_expiry": True,
        "in_closing_vwap_window": in_vwap_win,
        "settlement_vwap": settlement_vwap,
        "tracking_error_bps": err_bps,
        "drift_flag": drift_flag,
        "gex_pin_aligned": pin_aligned,
    }


def assess_cas_dispersion_regime(
    symbol: str,
    *,
    spot: float = 0.0,
    synthetic_spot: Optional[float] = None,
    future_price: Optional[float] = None,
    as_of: Optional[datetime] = None,
    is_expiry: bool = False,
) -> dict[str, Any]:
    """Evaluate effective-dated CAS / 15:45 derivative dispersion regime and entry cutoffs."""
    clean = canonical_alert_symbol(symbol).upper()
    ref_dt = as_of or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)

    expiring_idx = bool(is_expiry and is_index_symbol(clean))
    seg_close = derivative_close(ref_dt.date(), expiring_index=expiring_idx)
    entry_cutoff = intraday_entry_cutoff(
        ref_dt.date(), is_derivative=True, expiring_index=expiring_idx
    )
    cas_open = is_cas_window(ref_dt)
    dispersion_win = is_cas_derivative_dispersion_window(ref_dt)

    allow_new_entry = ref_dt.time() < entry_cutoff
    basis_bps: Optional[float] = None
    dispersion_signal = "INACTIVE"

    if dispersion_win and not expiring_idx:
        ref_px = synthetic_spot if (synthetic_spot and synthetic_spot > 0) else spot
        if future_price and future_price > 0 and ref_px and ref_px > 0:
            basis_bps = round(((float(future_price) - float(ref_px)) / float(ref_px)) * 10000.0, 2)
            if basis_bps >= 18.0:
                dispersion_signal = "PREMIUM_EXPANSION"
            elif basis_bps <= -18.0:
                dispersion_signal = "DISCOUNT_DRIFT"
            else:
                dispersion_signal = "BALANCED"
        else:
            dispersion_signal = "ACTIVE_NO_BASIS_FEED"
    elif dispersion_win and expiring_idx:
        dispersion_signal = "EXPIRING_INDEX_CLOSING_1530"

    return {
        "symbol": clean,
        "as_of": ref_dt.isoformat(),
        "is_expiry": bool(is_expiry),
        "expiring_index": expiring_idx,
        "segment_close": seg_close.strftime("%H:%M:%S"),
        "entry_cutoff": entry_cutoff.strftime("%H:%M:%S"),
        "allow_new_entry": allow_new_entry,
        "is_cas_window": cas_open,
        "is_cas_dispersion_window": dispersion_win,
        "basis_bps": basis_bps,
        "dispersion_signal": dispersion_signal,
    }
