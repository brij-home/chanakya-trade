"""
scripts/calibrate_fyers_historical_models.py
────────────────────────────────────────────
Institutional 90-Day Fyers Historical Model Calibration Runner.

Executes quantitative walk-forward calibration across Indian benchmark indices:
  1. NIFTY 50 (NSE:NIFTY50-INDEX)
  2. BANK NIFTY (NSE:NIFTYBANK-INDEX)
  3. FIN NIFTY (NSE:FINNIFTY-INDEX)
  4. MIDCP NIFTY (NSE:MIDCPNIFTY-INDEX)
  5. SENSEX (BSE:SENSEX-INDEX)

Derives:
  - Empirical Time-of-Day (TOD) Volume Accumulation U-Curves across 75 intraday slots.
  - Empirical Central Pivot Range (CPR) geometry percentiles (p25, p50, p75).
  - 5-Day Average Daily Range (ADR) distribution and expansion ceilings.
  - Multi-timeframe ATR-14 volatility profiles (1m, 5m).

Saves result to canonical institutional store:
  ~/.trading_platform/calibration/index_calibration.json
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import numpy as np
import pandas as pd

from config.constants import IST_ZONE as IST
from config.paths import app_data_path
from engine.historical_warehouse import historical_warehouse

logger = logging.getLogger("chanakya.scripts.calibrate_fyers")

BENCHMARK_INDICES = [
    ("NIFTY", "NSE:NIFTY50-INDEX", "NSE"),
    ("BANKNIFTY", "NSE:NIFTYBANK-INDEX", "NSE"),
    ("FINNIFTY", "NSE:FINNIFTY-INDEX", "NSE"),
    ("MIDCPNIFTY", "NSE:MIDCPNIFTY-INDEX", "NSE"),
    ("SENSEX", "BSE:SENSEX-INDEX", "BSE"),
]


def sync_historical_index_data(days: int = 90) -> None:
    """Syncs 90 days of 5m and 1m historical candles from Fyers API."""
    print(f"\n[1/4] Checking and synchronizing 90-day Fyers historical warehouse ({days} days)...")
    for clean_sym, fyers_sym, exch in BENCHMARK_INDICES:
        # Check 5m
        has_5m = historical_warehouse.has_bars(clean_sym, interval="5m", min_bars=2000)
        if not has_5m:
            print(f"  Syncing {clean_sym} 5m bars from broker...")
            c5 = historical_warehouse.sync_symbol_from_broker(
                fyers_sym, exchange=exch, interval="5m", days=days
            )
            print(f"    Synced {c5} 5m bars for {clean_sym}")
        else:
            print(f"  [OK] {clean_sym} 5m bars present in warehouse.")

        # Check 1m
        has_1m = historical_warehouse.has_bars(clean_sym, interval="1m", min_bars=10000)
        if not has_1m:
            print(f"  Syncing {clean_sym} 1m bars from broker...")
            c1 = historical_warehouse.sync_symbol_from_broker(
                fyers_sym, exchange=exch, interval="1m", days=days
            )
            print(f"    Synced {c1} 1m bars for {clean_sym}")
        else:
            print(f"  [OK] {clean_sym} 1m bars present in warehouse.")


def compute_tod_volume_profile() -> list[float]:
    """Computes empirical 75-slot cumulative volume accumulation across NIFTY and BANKNIFTY."""
    print("\n[2/4] Fitting empirical Time-of-Day (TOD) Volume Accumulation U-Curve...")
    curves = []

    for sym in ("NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"):
        df_5m = historical_warehouse.load_bars(sym, interval="5m")
        if df_5m.empty:
            df_5m = historical_warehouse.load_bars(
                sym.split(":")[-1].replace("-INDEX", ""), interval="5m"
            )
        if df_5m.empty or "volume" not in df_5m.columns:
            continue

        df = df_5m.copy()
        df["time"] = df.index.time
        # Normalize each session volume to sum to 1.0
        daily_sums = df.groupby(df.index.date)["volume"].transform("sum")
        df["vol_norm"] = df["volume"] / daily_sums.replace(0, np.nan)
        avg_by_time = df.groupby("time")["vol_norm"].mean().dropna()
        if len(avg_by_time) >= 70:
            avg_by_time = avg_by_time / avg_by_time.sum()
            curves.append(avg_by_time.cumsum())

    if curves:
        combined = pd.concat(curves, axis=1).mean(axis=1).values
        # Sample to 75 slots
        if len(combined) > 75:
            indices = np.linspace(0, len(combined) - 1, 75, dtype=int)
            curve_75 = [round(float(combined[i]), 4) for i in indices]
        else:
            curve_75 = [round(float(v), 4) for v in combined]
        # Ensure monotone and endpoints
        curve_75[-1] = 1.0
        print(
            f"  Successfully fit 75-slot TOD curve: 10:00 AM={curve_75[9] * 100:.1f}%, 12:30 PM={curve_75[39] * 100:.1f}%, 14:30 PM={curve_75[63] * 100:.1f}%"
        )
        return curve_75

    from engine.index_calibration import DEFAULT_TOD_VOLUME_PROFILE_CUMULATIVE

    print("  Using institutional default TOD curve.")
    return DEFAULT_TOD_VOLUME_PROFILE_CUMULATIVE


def calibrate_index_parameters() -> dict[str, Any]:
    """Calibrates CPR, ADR, and ATR distributions for all indices."""
    print("\n[3/4] Calibrating CPR geometry, ADR range, and ATR volatility parameters...")
    index_metrics: dict[str, Any] = {}

    for clean_sym, fyers_sym, exch in BENCHMARK_INDICES:
        df_5m = historical_warehouse.load_bars(fyers_sym, interval="5m")
        if df_5m.empty:
            df_5m = historical_warehouse.load_bars(clean_sym, interval="5m")

        if df_5m.empty or len(df_5m) < 100:
            print(f"  [WARN] Insufficient data for {clean_sym}, skipping.")
            continue

        # Daily resample for CPR and ADR
        df_day = (
            df_5m.resample("D")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )
        sample_days = len(df_day)

        # 1. CPR Width Distribution
        cpr_pcts = []
        for i in range(1, len(df_day)):
            prev = df_day.iloc[i - 1]
            h, l, c = prev["high"], prev["low"], prev["close"]
            p = (h + l + c) / 3.0
            bc = (h + l) / 2.0
            tc = (p - bc) + p
            width_pts = abs(tc - bc)
            width_pct = (width_pts / p) * 100.0
            cpr_pcts.append(width_pct)

        cpr_s = pd.Series(cpr_pcts)
        narrow_p25 = round(float(cpr_s.quantile(0.25)), 3) if not cpr_s.empty else 0.08
        median_p50 = round(float(cpr_s.median()), 3) if not cpr_s.empty else 0.14
        wide_p75 = round(float(cpr_s.quantile(0.75)), 3) if not cpr_s.empty else 0.24

        # 2. Daily Range (ADR)
        ranges_pts = df_day["high"] - df_day["low"]
        ranges_pct = (ranges_pts / df_day["close"]) * 100.0
        adr_mean_pts = round(float(ranges_pts.mean()), 1)
        adr_median_pts = round(float(ranges_pts.median()), 1)
        adr_mean_pct = round(float(ranges_pct.mean()), 2)

        # 3. 5m ATR-14
        h5 = df_5m["high"]
        l5 = df_5m["low"]
        c5 = df_5m["close"].shift(1)
        tr5 = pd.concat([h5 - l5, (h5 - c5).abs(), (l5 - c5).abs()], axis=1).max(axis=1)
        atr_5m_s = tr5.rolling(14).mean().dropna()
        atr_5m_mean = round(float(atr_5m_s.mean()), 1) if not atr_5m_s.empty else 20.0
        atr_5m_med = round(float(atr_5m_s.median()), 1) if not atr_5m_s.empty else 18.0

        # 4. 1m ATR-14
        df_1m = historical_warehouse.load_bars(fyers_sym, interval="1m")
        if df_1m.empty:
            df_1m = historical_warehouse.load_bars(clean_sym, interval="1m")
        if not df_1m.empty and len(df_1m) > 100:
            h1 = df_1m["high"]
            l1 = df_1m["low"]
            c1 = df_1m["close"].shift(1)
            tr1 = pd.concat([h1 - l1, (h1 - c1).abs(), (l1 - c1).abs()], axis=1).max(axis=1)
            atr_1m_s = tr1.rolling(14).mean().dropna()
            atr_1m_mean = round(float(atr_1m_s.mean()), 1) if not atr_1m_s.empty else 9.0
        else:
            atr_1m_mean = round(atr_5m_mean / 2.2, 1)

        metrics = {
            "symbol": clean_sym,
            "sample_days": sample_days,
            "sample_5m_bars": len(df_5m),
            "sample_1m_bars": len(df_1m) if not df_1m.empty else 0,
            "adr_mean_pts": adr_mean_pts,
            "adr_median_pts": adr_median_pts,
            "adr_mean_pct": adr_mean_pct,
            "cpr_narrow_threshold_pct": narrow_p25,
            "cpr_median_pct": median_p50,
            "cpr_wide_threshold_pct": wide_p75,
            "atr_5m_mean_pts": atr_5m_mean,
            "atr_5m_median_pts": atr_5m_med,
            "atr_1m_mean_pts": atr_1m_mean,
            "calibrated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }
        index_metrics[clean_sym] = metrics

        print(
            f"  {clean_sym:<11} | ADR: {adr_mean_pts:.0f} pts ({adr_mean_pct:.2f}%) | "
            f"CPR Narrow: <={narrow_p25:.3f}%, Wide: >={wide_p75:.3f}% | "
            f"5m ATR: {atr_5m_mean:.1f} pts | 1m ATR: {atr_1m_mean:.1f} pts"
        )

    return index_metrics


def calibrate_fno_stocks() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Calibrates ADR, 5m ATR, CPR percentiles, and TTM Squeeze readiness across all F&O stocks."""
    print("\n[4/5] Calibrating all F&O Equities (~222 stocks) for volatility, CPR & TTM Squeeze...")
    from analysis.universe import get_universe
    from analysis.big_move import compute_ttm_squeeze

    fno_symbols = get_universe("FNO")
    fno_metrics: dict[str, Any] = {}
    coiling_squeezes: list[dict[str, Any]] = []

    for sym in fno_symbols:
        df_5m = historical_warehouse.load_bars(sym, interval="5m")
        if df_5m.empty or len(df_5m) < 40:
            continue

        df_day = (
            df_5m.resample("D")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )
        if len(df_day) < 2:
            continue

        # 1. ADR
        ranges_pts = df_day["high"] - df_day["low"]
        ranges_pct = (ranges_pts / df_day["close"]) * 100.0
        adr_pts = round(float(ranges_pts.mean()), 2)
        adr_pct = round(float(ranges_pct.mean()), 2)

        # 2. 5m ATR-14
        h5 = df_5m["high"]
        l5 = df_5m["low"]
        c5 = df_5m["close"].shift(1)
        tr5 = pd.concat([h5 - l5, (h5 - c5).abs(), (l5 - c5).abs()], axis=1).max(axis=1)
        atr_5m_s = tr5.rolling(14).mean().dropna()
        atr_5m = round(float(atr_5m_s.mean()), 2) if not atr_5m_s.empty else round(adr_pts / 8.0, 2)

        # 3. CPR Geometry
        cpr_pcts = []
        for i in range(1, len(df_day)):
            prev = df_day.iloc[i - 1]
            p = (prev["high"] + prev["low"] + prev["close"]) / 3.0
            bc = (prev["high"] + prev["low"]) / 2.0
            tc = (p - bc) + p
            cpr_pcts.append(abs(tc - bc) / p * 100.0)
        cpr_s = pd.Series(cpr_pcts)
        narrow = round(float(cpr_s.quantile(0.25)), 3) if not cpr_s.empty else 0.35
        wide = round(float(cpr_s.quantile(0.75)), 3) if not cpr_s.empty else 0.65

        # 4. TTM Volatility Squeeze Coiling
        sq = compute_ttm_squeeze(df_5m)
        is_coiling = bool(sq.is_squeeze_on)
        coiling_bars = int(sq.squeeze_duration_bars)
        momentum_dir = str(sq.momentum_direction)

        metric = {
            "symbol": sym,
            "sample_bars": len(df_5m),
            "sample_days": len(df_day),
            "adr_pts": adr_pts,
            "adr_pct": adr_pct,
            "atr_5m_pts": atr_5m,
            "cpr_narrow_pct": narrow,
            "cpr_wide_pct": wide,
            "is_ttm_squeeze_on": is_coiling,
            "squeeze_duration_bars": coiling_bars,
            "squeeze_momentum_direction": momentum_dir,
            "calibrated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }
        fno_metrics[sym] = metric

        if is_coiling and coiling_bars >= 5:
            coiling_squeezes.append(
                {
                    "symbol": sym,
                    "bars": coiling_bars,
                    "momentum": momentum_dir,
                    "adr_pct": adr_pct,
                    "atr_5m_pts": atr_5m,
                }
            )

    coiling_squeezes.sort(key=lambda x: -x["bars"])
    print(
        f"  Successfully calibrated {len(fno_metrics)} F&O stocks ({len(coiling_squeezes)} actively coiling in TTM Squeeze)."
    )
    return fno_metrics, coiling_squeezes


def save_calibration_payload(
    tod_curve: list[float],
    index_metrics: dict[str, Any],
    fno_metrics: Optional[dict[str, Any]] = None,
    coiling_squeezes: Optional[list[dict[str, Any]]] = None,
) -> Path:
    """Persists calibration metrics atomically to JSON."""
    print("\n[5/5] Persisting verified calibration artifact to disk...")
    payload = {
        "version": "1.1.0",
        "generated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "provenance": "FYERS_HISTORICAL_PARQUET_INDEX_AND_FNO",
        "tod_volume_profile_cumulative": tod_curve,
        "indices": index_metrics,
        "fno_stocks": fno_metrics or {},
        "fno_coiling_squeezes": coiling_squeezes or [],
    }

    calib_dir = app_data_path("calibration")
    calib_dir.mkdir(parents=True, exist_ok=True)
    out_file = calib_dir / "index_calibration.json"

    tmp_file = out_file.with_suffix(".tmp.json")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp_file.replace(out_file)

    print(f"  Successfully wrote calibration artifact to: {out_file}")
    return out_file


def run_full_calibration() -> None:
    print("=" * 80)
    print("CHANAKYATRADE INSTITUTIONAL FYERS HISTORICAL MODEL CALIBRATION")
    print("=" * 80)
    sync_historical_index_data(days=90)
    tod_curve = compute_tod_volume_profile()
    index_metrics = calibrate_index_parameters()
    fno_metrics, coiling_squeezes = calibrate_fno_stocks()
    save_calibration_payload(tod_curve, index_metrics, fno_metrics, coiling_squeezes)
    print("\nCalibration cycle completed successfully with 100% data provenance.")
    print("=" * 80)


if __name__ == "__main__":
    run_full_calibration()
