"""
engine/options_replay.py
────────────────────────
Research-only expired F&O replay loader and Purged Walk-Forward Triple-Barrier
evaluator (with exact Apr-2026 statutory charges + slippage).

Per docs/SAFETY_CONTRACTS.md:
- Expired option history supports research replay only; missing Greeks stay null.
- Never fabricates current constant-tenor IV rank or claims live alpha from backtests.
- Samples below minimum outcomes or one-sided winning samples stay UNCALIBRATED.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from engine.charges import calculate_transaction_charges

logger = logging.getLogger("engine.options_replay")


def load_expired_option_bars(
    symbol: str,
    *,
    exchange: str = "NFO",
    interval: str = "5minute",
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    broker: Any = None,
) -> pd.DataFrame:
    """Fetch expired derivative bars via Fyers get_expired_fno_history without filling nulls."""
    brk = broker
    if brk is None:
        from brokers.session import get_data_broker

        brk = get_data_broker()

    if brk is None or not hasattr(brk, "get_expired_fno_history"):
        empty = pd.DataFrame()
        empty.attrs["provenance"] = "UNAVAILABLE"
        empty.attrs["constant_tenor_iv_available"] = False
        return empty

    rows = brk.get_expired_fno_history(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        include_oi=True,
        include_greeks=True,
    )
    if not rows:
        empty = pd.DataFrame()
        empty.attrs["provenance"] = "UNAVAILABLE"
        empty.attrs["constant_tenor_iv_available"] = False
        return empty

    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df = df.sort_values("date").set_index("date")
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.attrs["provenance"] = "RESEARCH_ONLY_EXPIRED_FNO"
    df.attrs["constant_tenor_iv_available"] = False
    return df


def evaluate_triple_barrier_outcomes(
    bars: pd.DataFrame,
    entry_indices: Sequence[int],
    *,
    direction: str = "BULLISH",
    horizon_bars: int = 12,
    pt_r: float = 2.0,
    sl_r: float = 1.0,
    risk_series: Optional[pd.Series] = None,
    segment: str = "FNO",
    slippage_bps: float = 5.0,
    quantity: int = 1,
) -> dict[str, Any]:
    """Evaluate causal Triple-Barrier (+pt_r*R vs -sl_r*R vs horizon_bars) net of charges & slippage."""
    if bars is None or bars.empty or not entry_indices:
        return {
            "status": "UNCALIBRATED",
            "trades": 0,
            "net_expectancy_r": None,
            "win_rate_pct": None,
            "outcomes": [],
        }

    cols = {str(c).lower(): c for c in bars.columns}
    if not {"high", "low", "close"}.issubset(cols.keys()):
        raise ValueError("bars DataFrame must contain high, low, close columns")

    high_arr = bars[cols["high"]].to_numpy(dtype=np.float64)
    low_arr = bars[cols["low"]].to_numpy(dtype=np.float64)
    close_arr = bars[cols["close"]].to_numpy(dtype=np.float64)
    n_bars = len(close_arr)
    slip_frac = max(0.0, float(slippage_bps)) / 10_000.0
    is_short = str(direction).upper() in ("BEARISH", "SHORT", "SELL")

    if risk_series is not None:
        risk_arr = risk_series.to_numpy(dtype=np.float64)
    else:
        tr = np.maximum(
            high_arr - low_arr,
            np.maximum(
                np.abs(high_arr - np.roll(close_arr, 1)),
                np.abs(low_arr - np.roll(close_arr, 1)),
            ),
        )
        tr[0] = high_arr[0] - low_arr[0]
        risk_arr = pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy(dtype=np.float64)

    outcomes: list[dict[str, Any]] = []
    last_exit_bar = -1

    for raw_idx in sorted(set(int(i) for i in entry_indices)):
        if raw_idx < 0 or raw_idx >= n_bars - 1:
            continue
        # Non-overlapping path guard (purge overlapping signal entries inside active trade window)
        if raw_idx <= last_exit_bar:
            continue

        raw_entry = float(close_arr[raw_idx])
        unit_risk = float(risk_arr[raw_idx])
        if raw_entry <= 0 or not np.isfinite(unit_risk) or unit_risk <= 0:
            continue

        eff_entry = raw_entry * (1.0 - slip_frac if is_short else 1.0 + slip_frac)
        tp_level = eff_entry - pt_r * unit_risk if is_short else eff_entry + pt_r * unit_risk
        sl_level = eff_entry + sl_r * unit_risk if is_short else eff_entry - sl_r * unit_risk

        end_bar = min(n_bars - 1, raw_idx + max(1, int(horizon_bars)))
        exit_bar = end_bar
        raw_exit = float(close_arr[end_bar])
        barrier_hit = "TIME_STOP"

        for b in range(raw_idx + 1, end_bar + 1):
            hi = float(high_arr[b])
            lo = float(low_arr[b])
            if is_short:
                if hi >= sl_level:
                    exit_bar, raw_exit, barrier_hit = b, sl_level, "SL_HIT"
                    break
                if lo <= tp_level:
                    exit_bar, raw_exit, barrier_hit = b, tp_level, "PT_HIT"
                    break
            else:
                if lo <= sl_level:
                    exit_bar, raw_exit, barrier_hit = b, sl_level, "SL_HIT"
                    break
                if hi >= tp_level:
                    exit_bar, raw_exit, barrier_hit = b, tp_level, "PT_HIT"
                    break

        last_exit_bar = exit_bar
        eff_exit = raw_exit * (1.0 + slip_frac if is_short else 1.0 - slip_frac)
        gross_pnl = (eff_entry - eff_exit if is_short else eff_exit - eff_entry) * quantity

        buy_px = eff_exit if is_short else eff_entry
        sell_px = eff_entry if is_short else eff_exit
        seg_u = str(segment or "OPTIONS").upper().strip()
        charge_seg: Any = (
            "OPTIONS"
            if seg_u in ("FNO", "OPT", "OPTIONS")
            else ("FUTURES" if seg_u in ("FUT", "FUTURES") else seg_u)
        )
        charges = float(
            calculate_transaction_charges(
                price=buy_px, quantity=quantity, segment=charge_seg, side="BUY"
            ).total_charges
            + calculate_transaction_charges(
                price=sell_px, quantity=quantity, segment=charge_seg, side="SELL"
            ).total_charges
        )
        net_pnl = gross_pnl - charges
        net_r = net_pnl / max(unit_risk * quantity, 1e-9)
        outcomes.append(
            {
                "entry_idx": raw_idx,
                "exit_idx": exit_bar,
                "barrier": barrier_hit,
                "net_r": round(float(net_r), 4),
                "charges": round(charges, 4),
            }
        )

    r_vals = [o["net_r"] for o in outcomes]
    n_trades = len(r_vals)
    wins = sum(1 for r in r_vals if r > 0)
    losses = sum(1 for r in r_vals if r <= 0)

    # SAFETY_CONTRACTS: <30 trades OR one-sided winning sample stays UNCALIBRATED
    if n_trades < 30 or (losses == 0 and wins > 0):
        status = "UNCALIBRATED"
    else:
        status = "CALIBRATED"

    return {
        "status": status,
        "trades": n_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round((wins / n_trades) * 100.0, 2) if n_trades > 0 else None,
        "net_expectancy_r": round(float(np.mean(r_vals)), 4) if n_trades > 0 else None,
        "outcomes": outcomes,
    }


def purged_walk_forward_score(
    bars: pd.DataFrame,
    entry_indices: Sequence[int],
    *,
    n_folds: int = 3,
    horizon_bars: int = 12,
    embargo_bars: int = 12,
    pt_r: float = 2.0,
    sl_r: float = 1.0,
    segment: str = "FNO",
    slippage_bps: float = 5.0,
    quantity: int = 1,
) -> dict[str, Any]:
    """Chronological Purged & Embargoed Walk-Forward evaluation across held-out folds."""
    if bars is None or len(bars) < max(30, n_folds * 15):
        return {
            "status": "UNCALIBRATED",
            "folds": [],
            "heldout_trades": 0,
            "heldout_expectancy_r": None,
        }

    fold_size = len(bars) // n_folds
    gap = max(0, int(embargo_bars)) + max(1, int(horizon_bars))
    folds: list[dict[str, Any]] = []
    all_oos_r: list[float] = []
    oos_wins = 0
    oos_losses = 0

    for k in range(n_folds):
        test_start = k * fold_size
        test_end = len(bars) if k == n_folds - 1 else (k + 1) * fold_size
        # Purge/embargo boundaries ensure test entries stay inside strictly disjoint test span
        local_entries = [
            i - test_start
            for i in entry_indices
            if (test_start + (gap if k > 0 else 0)) <= i < (test_end - 1)
        ]
        slice_df = bars.iloc[test_start:test_end]
        ev = evaluate_triple_barrier_outcomes(
            slice_df,
            local_entries,
            horizon_bars=horizon_bars,
            pt_r=pt_r,
            sl_r=sl_r,
            segment=segment,
            slippage_bps=slippage_bps,
            quantity=quantity,
        )
        fold_r = [o["net_r"] for o in ev["outcomes"]]
        all_oos_r.extend(fold_r)
        oos_wins += int(ev.get("wins", 0))
        oos_losses += int(ev.get("losses", 0))
        folds.append(
            {
                "fold": k + 1,
                "test_rows": len(slice_df),
                "trades": ev["trades"],
                "expectancy_r": ev["net_expectancy_r"],
            }
        )

    total_oos = len(all_oos_r)
    status = "CALIBRATED" if (total_oos >= 30 and oos_losses > 0) else "UNCALIBRATED"
    return {
        "status": status,
        "heldout_trades": total_oos,
        "heldout_wins": oos_wins,
        "heldout_losses": oos_losses,
        "heldout_expectancy_r": round(float(np.mean(all_oos_r)), 4) if total_oos > 0 else None,
        "folds": folds,
    }


def run_detector_ablation_comparison(
    bars: pd.DataFrame,
    baseline_entries: Sequence[int],
    enriched_entries: Sequence[int],
    *,
    direction: str = "BULLISH",
    horizon_bars: int = 12,
    pt_r: float = 2.0,
    sl_r: float = 1.0,
    segment: str = "FNO",
    slippage_bps: float = 5.0,
    quantity: int = 1,
) -> dict[str, Any]:
    """Compare baseline price-only entries vs enriched/filtered entries via Triple-Barrier outcomes."""
    base_res = evaluate_triple_barrier_outcomes(
        bars,
        baseline_entries,
        direction=direction,
        horizon_bars=horizon_bars,
        pt_r=pt_r,
        sl_r=sl_r,
        segment=segment,
        slippage_bps=slippage_bps,
        quantity=quantity,
    )
    enr_res = evaluate_triple_barrier_outcomes(
        bars,
        enriched_entries,
        direction=direction,
        horizon_bars=horizon_bars,
        pt_r=pt_r,
        sl_r=sl_r,
        segment=segment,
        slippage_bps=slippage_bps,
        quantity=quantity,
    )
    both_calibrated = base_res["status"] == "CALIBRATED" and enr_res["status"] == "CALIBRATED"
    delta_r = (
        round(float(enr_res["net_expectancy_r"]) - float(base_res["net_expectancy_r"]), 4)
        if base_res.get("net_expectancy_r") is not None
        and enr_res.get("net_expectancy_r") is not None
        else None
    )
    return {
        "status": "CALIBRATED" if both_calibrated else "UNCALIBRATED",
        "baseline": {k: v for k, v in base_res.items() if k != "outcomes"},
        "enriched": {k: v for k, v in enr_res.items() if k != "outcomes"},
        "expectancy_delta_r": delta_r,
        "improved": bool(both_calibrated and delta_r is not None and delta_r > 0),
    }
