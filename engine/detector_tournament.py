"""
engine/detector_tournament.py
─────────────────────────────
Purged Walk-Forward Detector Ablation Tournament across Index & Top Stock F&O.

Evaluates causal, bar-by-bar signal generators (with explicit execution delay `delay_bars >= 1`,
Apr-2026 statutory charges, and bid-ask/slippage friction) via `engine.options_replay` to
separate true out-of-sample expectancy from uncalibrated or negative-edge heuristics.

Per docs/SAFETY_CONTRACTS.md:
  - < 30 non-overlapping OOS trades OR one-sided winning samples remain UNCALIBRATED.
  - Never fabricates alpha or promotes filters without calibrated positive OOS delta.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

from config.constants import IST
from config.paths import app_data_path
from engine.level_state_machine import evaluate_symbol_stage
from engine.options_replay import (
    evaluate_triple_barrier_outcomes,
    purged_walk_forward_score,
    run_detector_ablation_comparison,
)

logger = logging.getLogger("engine.detector_tournament")


def _compute_atr14(bars: pd.DataFrame) -> pd.Series:
    h = bars["high"].astype(float)
    l = bars["low"].astype(float)
    c = bars["close"].astype(float)
    pc = c.shift(1).fillna(c)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(14, min_periods=5).mean().bfill().clip(lower=1e-6)


def _compute_session_vwap(bars: pd.DataFrame) -> pd.Series:
    tp = (
        bars["high"].astype(float) + bars["low"].astype(float) + bars["close"].astype(float)
    ) / 3.0
    vol = bars["volume"].astype(float).clip(lower=0.0)
    if isinstance(bars.index, pd.DatetimeIndex):
        dates = bars.index.date
        pv_cum = (tp * vol).groupby(dates).cumsum()
        v_cum = vol.groupby(dates).cumsum().replace(0.0, np.nan)
    else:
        pv_cum = (tp * vol).cumsum()
        v_cum = vol.cumsum().replace(0.0, np.nan)
    return (pv_cum / v_cum).fillna(tp)


def _compute_tod_rvol_series(bars: pd.DataFrame) -> pd.Series:
    vol = bars["volume"].astype(float)
    ma20 = vol.rolling(20, min_periods=5).mean().replace(0.0, np.nan)
    base_rvol = (vol / ma20).fillna(1.0)
    if not isinstance(bars.index, pd.DatetimeIndex):
        return base_rvol
    times = bars.index.time
    # Strictly causal expanding median of prior days at exact (hour, minute)
    tod_vals = np.ones(len(bars), dtype=float)
    by_time: dict[Any, list[float]] = {}
    for i, (t_val, v_val) in enumerate(zip(times, vol.to_numpy(dtype=float))):
        hist = by_time.get(t_val, [])
        pos = [x for x in hist if x > 0]
        if pos and v_val > 0:
            tod_vals[i] = max(float(base_rvol.iloc[i]), float(v_val / np.median(pos)))
        else:
            tod_vals[i] = float(base_rvol.iloc[i])
        by_time.setdefault(t_val, []).append(float(v_val))
    return pd.Series(tod_vals, index=bars.index)


def _signals_orb_breakout(bars: pd.DataFrame, *, direction: str = "BULLISH") -> list[int]:
    """Causal 15-minute (first 3 x 5m bars) Opening Range Breakout generator."""
    if not isinstance(bars.index, pd.DatetimeIndex) or len(bars) < 20:
        return []
    entries: list[int] = []
    close = bars["close"].to_numpy(dtype=float)
    dates = bars.index.date
    seen_dates: dict[Any, list[int]] = {}
    for idx, d in enumerate(dates):
        seen_dates.setdefault(d, []).append(idx)

    for d, idxs in seen_dates.items():
        if len(idxs) < 6:
            continue
        or_slice = bars.iloc[idxs[:3]]
        orh = float(or_slice["high"].max())
        orl = float(or_slice["low"].min())
        for j in idxs[3:]:
            if direction == "BULLISH" and close[j] > orh and close[j - 1] <= orh:
                entries.append(j)
            elif direction == "BEARISH" and close[j] < orl and close[j - 1] >= orl:
                entries.append(j)
    return entries


def _signals_squeeze_breakout(bars: pd.DataFrame, *, direction: str = "BULLISH") -> list[int]:
    """Causal Bollinger-Keltner squeeze release generator."""
    if len(bars) < 25:
        return []
    close = bars["close"].astype(float)
    atr = _compute_atr14(bars)
    bb_mid = close.rolling(20, min_periods=15).mean()
    bb_std = close.rolling(20, min_periods=15).std(ddof=0)
    ema20 = close.ewm(span=20, adjust=False).mean()
    sq_on = ((bb_mid + 2.0 * bb_std) < (ema20 + 1.5 * atr)) & (
        (bb_mid - 2.0 * bb_std) > (ema20 - 1.5 * atr)
    )
    entries: list[int] = []
    for i in range(21, len(bars)):
        if bool(sq_on.iloc[i - 1]) and not bool(sq_on.iloc[i]):
            if direction == "BULLISH" and float(close.iloc[i]) > float(ema20.iloc[i]):
                entries.append(i)
            elif direction == "BEARISH" and float(close.iloc[i]) < float(ema20.iloc[i]):
                entries.append(i)
    return entries


def _signals_vwap_pullback(bars: pd.DataFrame, *, direction: str = "BULLISH") -> list[int]:
    """Causal trend pullback & reclaim at session VWAP."""
    if len(bars) < 25:
        return []
    close = bars["close"].astype(float)
    low = bars["low"].astype(float)
    high = bars["high"].astype(float)
    vwap = _compute_session_vwap(bars)
    ema20 = close.ewm(span=20, adjust=False).mean()
    entries: list[int] = []
    for i in range(20, len(bars)):
        c_now = float(close.iloc[i])
        c_prev = float(close.iloc[i - 1])
        vw = float(vwap.iloc[i])
        e20 = float(ema20.iloc[i])
        if direction == "BULLISH":
            if (
                c_now > vw
                and c_now > e20
                and float(low.iloc[i - 1]) <= vw * 1.0015
                and c_prev <= vw * 1.002
            ):
                entries.append(i)
        else:
            if (
                c_now < vw
                and c_now < e20
                and float(high.iloc[i - 1]) >= vw * 0.9985
                and c_prev >= vw * 0.998
            ):
                entries.append(i)
    return entries


def _signals_failed_sweep_reversal(bars: pd.DataFrame, *, direction: str = "BULLISH") -> list[int]:
    """Causal prior-20-bar high/low liquidity sweep & immediate reclaim."""
    if len(bars) < 25:
        return []
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    roll_low = low.shift(2).rolling(18, min_periods=10).min()
    roll_high = high.shift(2).rolling(18, min_periods=10).max()
    entries: list[int] = []
    for i in range(20, len(bars)):
        if direction == "BULLISH":
            rl = float(roll_low.iloc[i]) if pd.notna(roll_low.iloc[i]) else 0.0
            if rl > 0 and float(low.iloc[i - 1]) < rl and float(close.iloc[i]) > rl:
                entries.append(i)
        else:
            rh = float(roll_high.iloc[i]) if pd.notna(roll_high.iloc[i]) else 0.0
            if rh > 0 and float(high.iloc[i - 1]) > rh and float(close.iloc[i]) < rh:
                entries.append(i)
    return entries


def _signals_level_state_machine_both(
    bars: pd.DataFrame,
    *,
    symbol: str = "NIFTY",
    max_eval_bars: int = 800,
) -> dict[str, list[int]]:
    """Evaluate causal WATCH -> ARMED -> TRIGGERED in one vectorized-feature pass for Bull & Bear."""
    if len(bars) < 25:
        return {"BULLISH": [], "BEARISH": []}

    close_s = bars["close"].astype(float)
    atr_s = _compute_atr14(bars)
    tod_rvol = _compute_tod_rvol_series(bars)
    bb_mid = close_s.rolling(20, min_periods=10).mean()
    bb_std = close_s.rolling(20, min_periods=10).std(ddof=0)
    ema20 = close_s.ewm(span=20, adjust=False).mean()
    sq_on = ((bb_mid + 2.0 * bb_std) < (ema20 + 1.5 * atr_s)) & (
        (bb_mid - 2.0 * bb_std) > (ema20 - 1.5 * atr_s)
    )

    start_bar = max(20, len(bars) - max(60, int(max_eval_bars)))
    bull_entries: list[int] = []
    bear_entries: list[int] = []
    prev_st = None
    for i in range(start_bar, len(bars)):
        prefix = bars.iloc[max(0, i - 120) : i + 1]
        feats = {
            "status": "AVAILABLE",
            "last_close": float(close_s.iloc[i]),
            "atr_14": float(atr_s.iloc[i]),
            "kc_squeeze_on": bool(sq_on.iloc[i]) if pd.notna(sq_on.iloc[i]) else False,
            "tod_rvol": float(tod_rvol.iloc[i]),
        }
        st = evaluate_symbol_stage(
            symbol,
            prefix,
            previous_state=prev_st,
            precomputed_features=feats,
            skip_normalization=True,
        )
        prev_st = st
        if st is not None and st.stage == "TRIGGERED":
            if st.direction == "BULLISH":
                bull_entries.append(i)
            elif st.direction == "BEARISH":
                bear_entries.append(i)
    return {"BULLISH": bull_entries, "BEARISH": bear_entries}


def _signals_level_state_machine(
    bars: pd.DataFrame,
    *,
    symbol: str = "NIFTY",
    direction: str = "BULLISH",
    max_eval_bars: int = 800,
) -> list[int]:
    """Evaluate causal WATCH -> ARMED -> TRIGGERED state machine sequentially over recent prefix."""
    both = _signals_level_state_machine_both(bars, symbol=symbol, max_eval_bars=max_eval_bars)
    return both.get(direction, [])


DETECTOR_FAMILIES: dict[str, Callable[..., list[int]]] = {
    "ORB_BREAKOUT": _signals_orb_breakout,
    "SQUEEZE_BREAKOUT": _signals_squeeze_breakout,
    "VWAP_PULLBACK": _signals_vwap_pullback,
    "FAILED_SWEEP_REVERSAL": _signals_failed_sweep_reversal,
    "LEVEL_ARMED_TRIGGER": _signals_level_state_machine,
}


def _apply_execution_delay(indices: Sequence[int], n_bars: int, delay_bars: int = 1) -> list[int]:
    shift = max(0, int(delay_bars))
    return sorted({i + shift for i in indices if 0 <= (i + shift) < (n_bars - 1)})


def _compute_mfe_mae_metrics(
    bars: pd.DataFrame,
    outcomes: list[dict[str, Any]],
    *,
    direction: str,
    risk_series: pd.Series,
) -> dict[str, Optional[float]]:
    if not outcomes:
        return {
            "mfe_median_r": None,
            "mae_median_r": None,
            "tail_loss_p05_r": None,
            "max_drawdown_r": None,
            "profit_factor": None,
        }
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    r_arr = risk_series.to_numpy(dtype=float)
    is_short = direction == "BEARISH"

    mfes: list[float] = []
    maes: list[float] = []
    net_rs: list[float] = []
    for o in outcomes:
        ei = int(o["entry_idx"])
        xi = int(o["exit_idx"])
        unit_r = float(r_arr[ei]) if ei < len(r_arr) else 0.0
        entry_px = float(close[ei])
        net_rs.append(float(o["net_r"]))
        if unit_r <= 0 or xi <= ei:
            continue
        span_h = float(np.max(high[ei + 1 : xi + 1]))
        span_l = float(np.min(low[ei + 1 : xi + 1]))
        if is_short:
            mfes.append(max(0.0, (entry_px - span_l) / unit_r))
            maes.append(max(0.0, (span_h - entry_px) / unit_r))
        else:
            mfes.append(max(0.0, (span_h - entry_px) / unit_r))
            maes.append(max(0.0, (entry_px - span_l) / unit_r))

    gross_win = sum(r for r in net_rs if r > 0)
    gross_loss = abs(sum(r for r in net_rs if r <= 0))
    eq_curve = np.cumsum(net_rs)
    peaks = np.maximum.accumulate(np.insert(eq_curve, 0, 0.0))[1:]
    max_dd = float(np.max(peaks - eq_curve)) if len(eq_curve) > 0 else 0.0

    return {
        "mfe_median_r": round(float(np.median(mfes)), 3) if mfes else None,
        "mae_median_r": round(float(np.median(maes)), 3) if maes else None,
        "tail_loss_p05_r": round(float(np.percentile(net_rs, 5)), 3) if net_rs else None,
        "max_drawdown_r": round(max_dd, 3),
        "profit_factor": round(gross_win / max(gross_loss, 1e-6), 2) if gross_loss > 0 else None,
    }


def _session_bucket_breakdown(
    bars: pd.DataFrame, outcomes: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    if not isinstance(bars.index, pd.DatetimeIndex) or not outcomes:
        return {}
    buckets: dict[str, list[float]] = {}
    for o in outcomes:
        ei = int(o["entry_idx"])
        if ei >= len(bars):
            continue
        t = bars.index[ei].time()
        if t < datetime.strptime("10:30", "%H:%M").time():
            b_name = "OPENING_0915_1030"
        elif t < datetime.strptime("12:00", "%H:%M").time():
            b_name = "MID_MORNING_1030_1200"
        elif t < datetime.strptime("13:30", "%H:%M").time():
            b_name = "MIDDAY_1200_1330"
        else:
            b_name = "AFTERNOON_1330_1545"
        buckets.setdefault(b_name, []).append(float(o["net_r"]))
    return {
        k: {
            "trades": len(vals),
            "win_rate_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100.0, 2),
            "net_expectancy_r": round(float(np.mean(vals)), 4),
        }
        for k, vals in buckets.items()
    }


def _classify_tournament_governance(is_calibrated: bool, net_exp: Optional[float]) -> str:
    if not is_calibrated:
        return "UNCALIBRATED"
    if net_exp is not None and net_exp > 0.05:
        return "PROMOTED_SHADOW"
    if net_exp is not None and net_exp <= 0.0:
        return "SHADOW_QUARANTINE"
    return "NEUTRAL_HOLD"


def run_detector_tournament(
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    detectors: Optional[Sequence[str]] = None,
    horizon_bars: int = 12,
    embargo_bars: int = 12,
    delay_bars: int = 1,
    pt_r: float = 2.0,
    sl_r: float = 1.0,
    slippage_bps: float = 8.0,
    risk_mode: str = "ATR_5M",
    collect_meta_samples: bool = False,
) -> dict[str, Any]:
    """
    Run Purged Walk-Forward Ablation Tournament across Index & Top Stock F&O symbols.

    Returns calibrated vs UNCALIBRATED telemetry, MFE/MAE, session-window segmentation,
    and TOD-RVOL + VWAP filter ablation results net of Apr-2026 statutory charges.
    """
    selected_detectors = list(detectors) if detectors else list(DETECTOR_FAMILIES.keys())
    detector_reports: dict[str, Any] = {}
    meta_samples: list[dict[str, Any]] = []

    for det_name in selected_detectors:
        gen_fn = DETECTOR_FAMILIES.get(det_name)
        if gen_fn is None:
            continue

        agg_oos_r: list[float] = []
        agg_oos_wins = 0
        agg_oos_losses = 0
        ablation_improved_votes = 0
        ablation_calibrated_pairs = 0
        per_asset_class: dict[str, list[float]] = {"INDEX": [], "STOCK_FNO": [], "COMMODITY": []}
        per_direction: dict[str, list[float]] = {"BULLISH": [], "BEARISH": []}
        per_session: dict[str, list[float]] = {}
        mfe_samples: list[float] = []
        mae_samples: list[float] = []

        for sym, raw_df in bars_by_symbol.items():
            if raw_df is None or len(raw_df) < 60:
                continue
            df = raw_df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            if not {"open", "high", "low", "close"}.issubset(df.columns):
                continue
            if "volume" not in df.columns:
                df["volume"] = 0.0
            df = df.sort_index()

            atr_s = _compute_atr14(df)
            tod_rvol = _compute_tod_rvol_series(df)
            vwap_s = _compute_session_vwap(df)
            close_s = df["close"].astype(float)
            if str(risk_mode).upper() == "STRUCTURAL_SWING":
                risk_s = np.maximum(atr_s * 2.5, close_s * 0.0022)
            else:
                risk_s = atr_s

            is_idx = sym.upper() in (
                "NIFTY",
                "BANKNIFTY",
                "SENSEX",
                "MIDCPNIFTY",
                "FINNIFTY",
                "BANKEX",
            )
            try:
                from market.instruments import COMMODITY_SYMBOLS

                is_comm = sym.upper() in COMMODITY_SYMBOLS
            except Exception:
                is_comm = sym.upper() in ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER")
            asset_cls = "INDEX" if is_idx else ("COMMODITY" if is_comm else "STOCK_FNO")
            replay_seg = "COMMODITY" if is_comm else "FUTURES"
            try:
                from market.instruments import get_fno_lot_size

                eval_qty = max(1, int(get_fno_lot_size(sym) or 1))
            except Exception:
                eval_qty = 1

            lsm_cache = (
                _signals_level_state_machine_both(df, symbol=sym)
                if det_name == "LEVEL_ARMED_TRIGGER"
                else None
            )

            for dir_label in ("BULLISH", "BEARISH"):
                if lsm_cache is not None:
                    raw_entries = lsm_cache.get(dir_label, [])
                else:
                    raw_entries = gen_fn(df, direction=dir_label)

                delayed_entries = _apply_execution_delay(
                    raw_entries, len(df), delay_bars=delay_bars
                )
                if not delayed_entries:
                    continue

                # Enriched ablation filter: TOD-RVOL >= 1.25x AND price aligned with session VWAP
                filtered_raw = [
                    idx
                    for idx in raw_entries
                    if float(tod_rvol.iloc[idx]) >= 1.25
                    and (
                        (
                            dir_label == "BULLISH"
                            and float(close_s.iloc[idx]) >= float(vwap_s.iloc[idx])
                        )
                        or (
                            dir_label == "BEARISH"
                            and float(close_s.iloc[idx]) <= float(vwap_s.iloc[idx])
                        )
                    )
                ]
                delayed_filtered = _apply_execution_delay(
                    filtered_raw, len(df), delay_bars=delay_bars
                )

                ablation = run_detector_ablation_comparison(
                    df,
                    delayed_entries,
                    delayed_filtered,
                    direction=dir_label,
                    horizon_bars=horizon_bars,
                    pt_r=pt_r,
                    sl_r=sl_r,
                    segment=replay_seg,
                    slippage_bps=slippage_bps,
                    quantity=eval_qty,
                )
                if ablation.get("status") == "CALIBRATED":
                    ablation_calibrated_pairs += 1
                    if ablation.get("improved"):
                        ablation_improved_votes += 1

                # Purged walk-forward evaluation on causal delayed baseline
                wf = purged_walk_forward_score(
                    df,
                    delayed_entries,
                    n_folds=3,
                    horizon_bars=horizon_bars,
                    embargo_bars=embargo_bars,
                    pt_r=pt_r,
                    sl_r=sl_r,
                    segment=replay_seg,
                    slippage_bps=slippage_bps,
                    quantity=eval_qty,
                )
                tb_full = evaluate_triple_barrier_outcomes(
                    df,
                    delayed_entries,
                    direction=dir_label,
                    horizon_bars=horizon_bars,
                    pt_r=pt_r,
                    sl_r=sl_r,
                    risk_series=risk_s,
                    segment=replay_seg,
                    slippage_bps=slippage_bps,
                    quantity=eval_qty,
                )
                outcomes = tb_full.get("outcomes", [])
                r_list = [float(o["net_r"]) for o in outcomes]
                if wf.get("heldout_trades", 0) > 0:
                    agg_oos_wins += int(wf.get("heldout_wins", 0))
                    agg_oos_losses += int(wf.get("heldout_losses", 0))
                agg_oos_r.extend(r_list)
                per_asset_class[asset_cls].extend(r_list)
                per_direction[dir_label].extend(r_list)

                mfe_mae = _compute_mfe_mae_metrics(
                    df, outcomes, direction=dir_label, risk_series=atr_s
                )
                if mfe_mae["mfe_median_r"] is not None:
                    mfe_samples.append(float(mfe_mae["mfe_median_r"]))
                if mfe_mae["mae_median_r"] is not None:
                    mae_samples.append(float(mfe_mae["mae_median_r"]))

                sess_map = _session_bucket_breakdown(df, outcomes)
                for b_k, b_val in sess_map.items():
                    if b_val["trades"] > 0:
                        per_session.setdefault(b_k, []).extend(
                            [float(b_val["net_expectancy_r"])] * int(b_val["trades"])
                        )

                if collect_meta_samples and outcomes:
                    high_arr = df["high"].to_numpy(dtype=float)
                    low_arr = df["low"].to_numpy(dtype=float)
                    open_arr = (
                        df["open"].to_numpy(dtype=float)
                        if "open" in df.columns
                        else close_s.to_numpy(dtype=float)
                    )
                    vol_arr = df["volume"].to_numpy(dtype=float)
                    vwap_arr = vwap_s.to_numpy(dtype=float)
                    close_arr = close_s.to_numpy(dtype=float)
                    tr_arr = high_arr - low_arr
                    is_short = dir_label == "BEARISH"
                    for o in outcomes:
                        ei = int(o["entry_idx"])
                        xi = int(o["exit_idx"])
                        sig_i = max(0, ei - max(0, int(delay_bars)))
                        unit_r = float(atr_s.iloc[sig_i]) if sig_i < len(atr_s) else 1.0
                        entry_px = float(close_s.iloc[ei])
                        mfe_v = 0.0
                        mae_v = 0.0
                        if unit_r > 0 and xi > ei:
                            span_h = float(np.max(high_arr[ei + 1 : xi + 1]))
                            span_l = float(np.min(low_arr[ei + 1 : xi + 1]))
                            if is_short:
                                mfe_v = max(0.0, (entry_px - span_l) / unit_r)
                                mae_v = max(0.0, (span_h - entry_px) / unit_r)
                            else:
                                mfe_v = max(0.0, (span_h - entry_px) / unit_r)
                                mae_v = max(0.0, (entry_px - span_l) / unit_r)

                        trig_ts = (
                            df.index[sig_i].isoformat()
                            if isinstance(df.index, pd.DatetimeIndex)
                            else str(sig_i)
                        )
                        ext_atr = abs(float(close_arr[sig_i]) - float(vwap_arr[sig_i])) / max(
                            1e-6, unit_r
                        )
                        win_start = max(0, sig_i - 19)
                        lvl_ref = (
                            float(np.min(low_arr[win_start:sig_i]))
                            if is_short and sig_i > win_start
                            else (
                                float(np.max(high_arr[win_start:sig_i]))
                                if sig_i > win_start
                                else float(close_arr[sig_i])
                            )
                        )
                        dist_lvl_atr = abs(float(close_arr[sig_i]) - lvl_ref) / max(1e-6, unit_r)
                        sq_bars = 0
                        for kb in range(sig_i, max(-1, sig_i - 12), -1):
                            if tr_arr[kb] < (0.85 * unit_r):
                                sq_bars += 1
                            else:
                                break
                        cvd_start = max(0, sig_i - 2)
                        v_mean_20 = max(1.0, float(np.mean(vol_arr[win_start : sig_i + 1])))
                        signed_v = np.where(
                            close_arr[cvd_start : sig_i + 1] >= open_arr[cvd_start : sig_i + 1],
                            vol_arr[cvd_start : sig_i + 1],
                            -vol_arr[cvd_start : sig_i + 1],
                        )
                        cvd_slope = float(np.sum(signed_v)) / (3.0 * v_mean_20)
                        vw_start = max(0, sig_i - 11)
                        pct_above_vw = float(
                            np.mean(
                                close_arr[vw_start : sig_i + 1] > vwap_arr[vw_start : sig_i + 1]
                            )
                            * 100.0
                        )
                        sb_num = 2.0
                        if isinstance(df.index, pd.DatetimeIndex):
                            tt = df.index[sig_i].time()
                            if tt.hour == 9 or (tt.hour == 10 and tt.minute < 15):
                                sb_num = 1.0
                            elif tt.hour == 10 or (tt.hour == 11 and tt.minute < 30):
                                sb_num = 2.0
                            elif tt.hour < 13 or (tt.hour == 13 and tt.minute < 15):
                                sb_num = 3.0
                            elif tt.hour < 15 or (tt.hour == 15 and tt.minute < 15):
                                sb_num = 4.0
                            else:
                                sb_num = 5.0
                        meta_samples.append(
                            {
                                "trigger_time": trig_ts,
                                "symbol": sym,
                                "detector": det_name,
                                "direction": dir_label,
                                "features": {
                                    "dist_to_level_atr": round(dist_lvl_atr, 4),
                                    "extension_from_vwap_atr": round(float(ext_atr), 4),
                                    "squeeze_duration_bars": float(sq_bars),
                                    "tod_rvol": round(float(tod_rvol.iloc[sig_i]), 4),
                                    "pct_above_vwap": round(pct_above_vw, 2),
                                    "delta_cvd_slope": round(cvd_slope, 4),
                                    "spread_bps": float(slippage_bps),
                                    "session_bucket_num": sb_num,
                                    "is_event_window": 0.0,
                                },
                                "net_r": round(float(o["net_r"]), 4),
                                "mae_r": round(float(mae_v), 4),
                                "mfe_r": round(float(mfe_v), 4),
                            }
                        )

        total_trades = len(agg_oos_r)
        wins = sum(1 for r in agg_oos_r if r > 0)
        losses = sum(1 for r in agg_oos_r if r <= 0)
        # Strict SAFETY_CONTRACTS.md calibration rule: >= 30 trades AND non-zero losses
        is_calibrated = total_trades >= 30 and losses > 0
        net_exp = round(float(np.mean(agg_oos_r)), 4) if total_trades > 0 else None
        win_rate = round((wins / total_trades) * 100.0, 2) if total_trades > 0 else None

        governance = _classify_tournament_governance(is_calibrated, net_exp)

        detector_reports[det_name] = {
            "status": "CALIBRATED" if is_calibrated else "UNCALIBRATED",
            "governance": governance,
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "net_expectancy_r": net_exp,
            "mfe_median_r": round(float(np.mean(mfe_samples)), 3) if mfe_samples else None,
            "mae_median_r": round(float(np.mean(mae_samples)), 3) if mae_samples else None,
            "tail_loss_p05_r": round(float(np.percentile(agg_oos_r, 5)), 3) if agg_oos_r else None,
            "ablation_calibrated_pairs": ablation_calibrated_pairs,
            "ablation_improved_pairs": ablation_improved_votes,
            "by_asset_class": {
                k: {
                    "trades": len(v),
                    "net_expectancy_r": round(float(np.mean(v)), 4) if v else None,
                }
                for k, v in per_asset_class.items()
            },
            "by_direction": {
                k: {
                    "trades": len(v),
                    "net_expectancy_r": round(float(np.mean(v)), 4) if v else None,
                }
                for k, v in per_direction.items()
            },
            "by_session_window": {
                k: {
                    "trades": len(v),
                    "net_expectancy_r": round(float(np.mean(v)), 4) if v else None,
                }
                for k, v in per_session.items()
            },
        }

    out = {
        "provenance": "RESEARCH_ONLY_PURGED_WALK_FORWARD",
        "risk_mode": risk_mode,
        "generated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "symbols_evaluated": sorted(bars_by_symbol.keys()),
        "delay_bars": delay_bars,
        "slippage_bps": slippage_bps,
        "detectors": detector_reports,
    }
    if collect_meta_samples:
        out["meta_samples"] = meta_samples
    return out


def _evaluate_option_atm_proxy_for_bars(
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    detectors: Optional[Sequence[str]] = None,
    expired_option_bars_by_symbol: Optional[dict[str, pd.DataFrame]] = None,
    horizon_bars: int = 24,
    delay_bars: int = 1,
) -> dict[str, Any]:
    """Evaluate detectors using Option premium economics (real expired tape or ATM Delta 0.55 proxy)."""
    from engine.charges import calculate_transaction_charges
    from market.instruments import get_fno_lot_size

    selected = list(detectors) if detectors else list(DETECTOR_FAMILIES.keys())
    det_map: dict[str, Any] = {}
    used_real_tape = False

    for det_name in selected:
        gen_fn = DETECTOR_FAMILIES.get(det_name)
        if gen_fn is None:
            continue
        r_all: list[float] = []

        for sym, raw_df in bars_by_symbol.items():
            if raw_df is None or len(raw_df) < 60:
                continue
            df = raw_df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            if not {"open", "high", "low", "close"}.issubset(df.columns):
                continue
            if "volume" not in df.columns:
                df["volume"] = 0.0
            df = df.sort_index()
            try:
                eval_qty = max(1, int(get_fno_lot_size(sym) or 1))
            except Exception:
                eval_qty = 1

            # Prefer authentic expired option OHLC bars if supplied
            opt_df = (expired_option_bars_by_symbol or {}).get(sym)
            if opt_df is not None and len(opt_df) >= 30:
                used_real_tape = True
                for dir_label in ("BULLISH",):
                    raw_entries = (
                        _signals_level_state_machine_both(opt_df, symbol=sym).get(dir_label, [])
                        if det_name == "LEVEL_ARMED_TRIGGER"
                        else gen_fn(opt_df, direction=dir_label)
                    )
                    delayed = _apply_execution_delay(
                        raw_entries, len(opt_df), delay_bars=delay_bars
                    )
                    ev = evaluate_triple_barrier_outcomes(
                        opt_df,
                        delayed,
                        direction="BULLISH",
                        horizon_bars=horizon_bars,
                        pt_r=2.0,
                        sl_r=1.0,
                        segment="OPTIONS",
                        slippage_bps=15.0,
                        quantity=eval_qty,
                    )
                    r_all.extend(float(o["net_r"]) for o in ev.get("outcomes", []))
                continue

            # Explicit research proxy: ATM Delta 0.55 option premium (1.0% of spot) with 0.15% Option STT
            close_arr = df["close"].to_numpy(dtype=float)
            high_arr = df["high"].to_numpy(dtype=float)
            low_arr = df["low"].to_numpy(dtype=float)
            risk_arr = np.maximum(
                _compute_atr14(df).to_numpy(dtype=float) * 2.5, close_arr * 0.0022
            )
            lsm_cache = (
                _signals_level_state_machine_both(df, symbol=sym)
                if det_name == "LEVEL_ARMED_TRIGGER"
                else None
            )

            for dir_label in ("BULLISH", "BEARISH"):
                raw_e = (
                    lsm_cache.get(dir_label, [])
                    if lsm_cache is not None
                    else gen_fn(df, direction=dir_label)
                )
                delayed = _apply_execution_delay(raw_e, len(df), delay_bars=delay_bars)
                last_exit = -1
                is_short = dir_label == "BEARISH"
                for ei in delayed:
                    if ei <= last_exit or ei >= len(df) - 1:
                        continue
                    spot_0 = float(close_arr[ei])
                    u_risk = float(risk_arr[ei])
                    if spot_0 <= 0 or u_risk <= 0:
                        continue
                    prem_0 = max(15.0, spot_0 * 0.01)
                    opt_risk = max(2.0, 0.55 * u_risk)
                    tp_spot = spot_0 - 2.0 * u_risk if is_short else spot_0 + 2.0 * u_risk
                    sl_spot = spot_0 + u_risk if is_short else spot_0 - u_risk
                    end_b = min(len(df) - 1, ei + horizon_bars)
                    exit_b = end_b
                    spot_move = float(close_arr[end_b] - spot_0)
                    for b in range(ei + 1, end_b + 1):
                        if is_short:
                            if float(high_arr[b]) >= sl_spot:
                                exit_b, spot_move = b, sl_spot - spot_0
                                break
                            if float(low_arr[b]) <= tp_spot:
                                exit_b, spot_move = b, tp_spot - spot_0
                                break
                        else:
                            if float(low_arr[b]) <= sl_spot:
                                exit_b, spot_move = b, sl_spot - spot_0
                                break
                            if float(high_arr[b]) >= tp_spot:
                                exit_b, spot_move = b, tp_spot - spot_0
                                break
                    last_exit = exit_b
                    signed_move = -spot_move if is_short else spot_move
                    bars_held = max(1, exit_b - ei)
                    theta_drag = prem_0 * 0.0005 * bars_held
                    spread_cost = prem_0 * 0.0020  # 20 bps round-trip option spread
                    exit_prem = max(0.05, prem_0 + (0.55 * signed_move) - theta_drag - spread_cost)
                    opt_charges = float(
                        calculate_transaction_charges(
                            prem_0, eval_qty, segment="OPTIONS", side="BUY"
                        ).total_charges
                        + calculate_transaction_charges(
                            exit_prem, eval_qty, segment="OPTIONS", side="SELL"
                        ).total_charges
                    )
                    net_pnl = ((exit_prem - prem_0) * eval_qty) - opt_charges
                    r_all.append(round(net_pnl / max(opt_risk * eval_qty, 1e-6), 4))

        wins = sum(1 for r in r_all if r > 0)
        losses = sum(1 for r in r_all if r <= 0)
        cal = len(r_all) >= 30 and losses > 0
        net_e = round(float(np.mean(r_all)), 4) if r_all else None
        det_map[det_name] = {
            "status": "CALIBRATED" if cal else "UNCALIBRATED",
            "governance": _classify_tournament_governance(cal, net_e),
            "trades": len(r_all),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round((wins / len(r_all)) * 100.0, 2) if r_all else None,
            "net_expectancy_r": net_e,
        }

    return {
        "provenance": "EXPIRED_OPTION_TAPE" if used_real_tape else "RESEARCH_PROXY_ATM_DELTA_055",
        "detectors": det_map,
    }


def run_multi_profile_tournament(
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    expired_option_bars_by_symbol: Optional[dict[str, pd.DataFrame]] = None,
    detectors: Optional[Sequence[str]] = None,
    collect_meta_samples: bool = False,
) -> dict[str, Any]:
    """Compare 5m Futures Scalps vs 15m Structural Swings vs ATM Option Economics."""
    scalp_res = run_detector_tournament(
        bars_by_symbol,
        detectors=detectors,
        horizon_bars=12,
        embargo_bars=12,
        slippage_bps=8.0,
        risk_mode="ATR_5M",
        collect_meta_samples=collect_meta_samples,
    )
    swing_res = run_detector_tournament(
        bars_by_symbol,
        detectors=detectors,
        horizon_bars=36,
        embargo_bars=36,
        slippage_bps=6.0,
        risk_mode="STRUCTURAL_SWING",
        collect_meta_samples=collect_meta_samples,
    )
    opt_res = _evaluate_option_atm_proxy_for_bars(
        bars_by_symbol,
        detectors=detectors,
        expired_option_bars_by_symbol=expired_option_bars_by_symbol,
    )

    combined_samples: list[dict[str, Any]] = []
    if collect_meta_samples:
        combined_samples.extend(swing_res.pop("meta_samples", []))
        combined_samples.extend(scalp_res.pop("meta_samples", []))

    out = {
        "provenance": "RESEARCH_ONLY_PURGED_WALK_FORWARD",
        "generated_at": scalp_res["generated_at"],
        "symbols_evaluated": scalp_res["symbols_evaluated"],
        "delay_bars": scalp_res["delay_bars"],
        "slippage_bps": scalp_res["slippage_bps"],
        # Keep top-level detectors populated from structural swing or 5m cleanly
        "detectors": swing_res["detectors"],
        "profiles": {
            "FUTURES_5M_SCALP": {"detectors": scalp_res["detectors"]},
            "FUTURES_15M_SWING": {"detectors": swing_res["detectors"]},
            "OPTIONS_ATM_EQUIVALENT": opt_res,
        },
    }
    if collect_meta_samples:
        out["meta_samples"] = combined_samples
    return out


def get_tournament_report_path() -> Path:
    return app_data_path("calibration", "tournament_report.json")


def save_tournament_report(report: dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or get_tournament_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return target


def load_tournament_report(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or get_tournament_report_path()
    if not target.exists():
        return {"status": "UNCALIBRATED", "reason": "NO_TOURNAMENT_REPORT", "detectors": {}}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug(f"[DetectorTournament] Load failed: {exc}")
        return {"status": "UNCALIBRATED", "reason": str(exc), "detectors": {}}
