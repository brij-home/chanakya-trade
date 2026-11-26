"""
analysis/pullback_engine.py
───────────────────────────
Institutional Pullback, Retest & Continuation Engine.

Differentiates healthy institutional pullbacks from dangerous liquidation traps:
  1. Verifies origin impulse momentum (ADX >= 20, displacement >= 2.0x ATR).
  2. Enforces Volume Dry-Up during retracement (Vol <= 0.80x SMA20) — heavy volume on pullbacks indicates distribution.
  3. Validates structural anchor retest (Prior resistance-turned-support, 20 EMA, Anchored VWAP, or 0.50-0.618 Fib OTE).
  4. Requires re-ignition candlestick trigger (rejection pin bar or breakout above retest bar high).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.technical import atr, ema
from analysis.fibonacci import compute_fib_levels

logger = logging.getLogger("chanakya.analysis.pullback_engine")


@dataclass
class PullbackSignal:
    symbol: str
    pullback_type: (
        str  # "BREAKOUT_RETEST" | "EMA20_PULLBACK" | "VWAP_PULLBACK" | "FIB_OTE_PULLBACK" | "NONE"
    )
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: int  # 0 to 100
    anchor_level: float
    pullback_depth_fib: float
    is_volume_dryup: bool
    reignition_candle: str
    entry_zone: tuple[float, float]
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "pullback_type": self.pullback_type,
            "bias": self.bias,
            "confidence": self.confidence,
            "anchor_level": round(self.anchor_level, 2),
            "pullback_depth_fib": round(self.pullback_depth_fib, 3),
            "is_volume_dryup": self.is_volume_dryup,
            "reignition_candle": self.reignition_candle,
            "entry_zone": [round(x, 2) for x in self.entry_zone],
            "stop_loss": round(self.stop_loss, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "summary": self.summary,
        }


def evaluate_pullback(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    breakout_level: Optional[float] = None,
    vwap_series: Optional[pd.Series] = None,
    atr_val: Optional[float] = None,
) -> Optional[PullbackSignal]:
    """
    Evaluates whether the current market action represents a confirmed institutional
    pullback/retest or an invalidated breakdown/liquidation.
    """
    if df is None or len(df) < 20:
        return None

    cols = {c.lower(): c for c in df.columns}
    h_series = df[cols["high"]].astype(float)
    l_series = df[cols["low"]].astype(float)
    c_series = df[cols["close"]].astype(float)
    o_series = df[cols["open"]].astype(float) if "open" in cols else c_series
    v_series = (
        df[cols["volume"]].astype(float) if "volume" in cols else pd.Series(1000.0, index=df.index)
    )

    c_curr = float(c_series.iloc[-1])
    h_curr = float(h_series.iloc[-1])
    l_curr = float(l_series.iloc[-1])
    o_curr = float(o_series.iloc[-1])

    h_prev = float(h_series.iloc[-2])
    l_prev = float(l_series.iloc[-2])

    # Dynamic ATR
    if atr_val is None or atr_val <= 0:
        atr_s = atr(df, period=14)
        atr_val = (
            float(atr_s.iloc[-1])
            if not atr_s.empty and not np.isnan(atr_s.iloc[-1])
            else c_curr * 0.015
        )
    if atr_val <= 0:
        atr_val = max(c_curr * 0.01, 1.0)

    # Moving Averages
    ema20_s = ema(c_series, 20)
    curr_ema20 = float(ema20_s.iloc[-1]) if not ema20_s.empty else c_curr

    # Volume Baseline
    avg_vol_20 = float(v_series.rolling(20, min_periods=5).mean().iloc[-1])
    curr_vol = float(v_series.iloc[-1])
    prev_vol = float(v_series.iloc[-2])

    # Volume dry-up check on retracement (pullback bars should have vol <= 0.85x avg)
    is_volume_dryup = (prev_vol <= 0.85 * max(avg_vol_20, 1.0)) or (
        curr_vol <= 0.90 * max(avg_vol_20, 1.0)
    )

    # Identify recent swing impulse (last 15 bars)
    recent_high = float(h_series.iloc[-15:-2].max())
    recent_low = float(l_series.iloc[-15:-2].min())
    impulse_span = max(recent_high - recent_low, 0.001)

    # ─────────────────────────────────────────────────────────
    # 1. BULLISH PULLBACK EVALUATION
    # ─────────────────────────────────────────────────────────
    # Impulse must be upward (recent_high higher than older lows)
    if recent_high > recent_low + (1.5 * atr_val):
        fib_bull = compute_fib_levels(recent_high, recent_low, direction="BULLISH")
        pullback_depth = (recent_high - l_prev) / impulse_span

        # Candidate anchors
        anchors: list[tuple[str, float, float]] = []  # (type, level, proximity_pts)

        if breakout_level and breakout_level > 0:
            anchors.append(("BREAKOUT_RETEST", breakout_level, abs(l_prev - breakout_level)))
        anchors.append(("EMA20_PULLBACK", curr_ema20, abs(l_prev - curr_ema20)))
        anchors.append(("FIB_OTE_PULLBACK", fib_bull.level_618, abs(l_prev - fib_bull.level_618)))

        if vwap_series is not None and not vwap_series.empty:
            curr_vwap = float(vwap_series.iloc[-1])
            anchors.append(("VWAP_PULLBACK", curr_vwap, abs(l_prev - curr_vwap)))

        # Find best-matched anchor within 0.40x ATR
        anchors.sort(key=lambda x: x[2])
        best_anchor_type, best_anchor_lvl, best_dist = anchors[0]

        # Valid pullback conditions:
        # - Pullback did not break below 0.786 Fib (healthy depth 0.382 to 0.705)
        # - Tested anchor within 0.50x ATR
        # - Current candle re-ignites (closes green, or breaks above prev bar high)
        is_depth_healthy = 0.20 <= pullback_depth <= 0.786
        is_anchor_tested = best_dist <= (0.60 * atr_val)
        is_reignited = (c_curr > o_curr and c_curr > l_prev) or (c_curr > h_prev)

        if is_depth_healthy and is_anchor_tested and is_reignited:
            candle_tag = (
                "BULLISH_ENGULFING"
                if (c_curr > h_prev and o_curr <= l_prev)
                else (
                    "HAMMER_REVERSAL"
                    if (min(o_curr, c_curr) - l_curr) >= 0.4 * (h_curr - l_curr)
                    else "GREEN_REIGNITION"
                )
            )

            sl = round(min(l_curr, l_prev, best_anchor_lvl) - (0.15 * atr_val), 2)
            risk = max(c_curr - sl, atr_val * 0.4)
            t1 = round(c_curr + (2.0 * risk), 2)
            t2 = round(c_curr + (3.5 * risk), 2)
            rr = round((t1 - c_curr) / risk, 2)
            entry_zone = (round(c_curr - 0.15 * atr_val, 2), round(c_curr + 0.10 * atr_val, 2))

            conf = (
                75
                + (10 if is_volume_dryup else 0)
                + (10 if best_anchor_type == "BREAKOUT_RETEST" else 5)
            )
            conf = min(95, conf)

            summary = (
                f"Bullish {best_anchor_type} ({conf}% Conf): Shallow pullback ({pullback_depth:.2f} Fib) into "
                f"anchor ₹{best_anchor_lvl:.2f}. Volume dryup: {is_volume_dryup}. Re-ignited with {candle_tag}."
            )

            return PullbackSignal(
                symbol=symbol,
                pullback_type=best_anchor_type,
                bias="BULLISH",
                confidence=conf,
                anchor_level=best_anchor_lvl,
                pullback_depth_fib=pullback_depth,
                is_volume_dryup=is_volume_dryup,
                reignition_candle=candle_tag,
                entry_zone=entry_zone,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=summary,
            )

    # ─────────────────────────────────────────────────────────
    # 2. BEARISH RETRACEMENT EVALUATION
    # ─────────────────────────────────────────────────────────
    if recent_low < recent_high - (1.5 * atr_val):
        fib_bear = compute_fib_levels(recent_high, recent_low, direction="BEARISH")
        bounce_depth = (h_prev - recent_low) / impulse_span

        anchors_bear: list[tuple[str, float, float]] = []
        if breakout_level and breakout_level > 0:
            anchors_bear.append(("BREAKOUT_RETEST", breakout_level, abs(h_prev - breakout_level)))
        anchors_bear.append(("EMA20_PULLBACK", curr_ema20, abs(h_prev - curr_ema20)))
        anchors_bear.append(
            ("FIB_OTE_PULLBACK", fib_bear.level_618, abs(h_prev - fib_bear.level_618))
        )

        if vwap_series is not None and not vwap_series.empty:
            curr_vwap = float(vwap_series.iloc[-1])
            anchors_bear.append(("VWAP_PULLBACK", curr_vwap, abs(h_prev - curr_vwap)))

        anchors_bear.sort(key=lambda x: x[2])
        best_anchor_type_b, best_anchor_lvl_b, best_dist_b = anchors_bear[0]

        is_depth_healthy_b = 0.20 <= bounce_depth <= 0.786
        is_anchor_tested_b = best_dist_b <= (0.60 * atr_val)
        is_reignited_b = (c_curr < o_curr and c_curr < h_prev) or (c_curr < l_prev)

        if is_depth_healthy_b and is_anchor_tested_b and is_reignited_b:
            candle_tag_b = (
                "BEARISH_ENGULFING"
                if (c_curr < l_prev and o_curr >= h_prev)
                else (
                    "SHOOTING_STAR"
                    if (h_curr - max(o_curr, c_curr)) >= 0.4 * (h_curr - l_curr)
                    else "RED_REIGNITION"
                )
            )

            sl = round(max(h_curr, h_prev, best_anchor_lvl_b) + (0.15 * atr_val), 2)
            risk = max(sl - c_curr, atr_val * 0.4)
            t1 = round(c_curr - (2.0 * risk), 2)
            t2 = round(c_curr - (3.5 * risk), 2)
            rr = round((c_curr - t1) / risk, 2)
            entry_zone = (round(c_curr - 0.10 * atr_val, 2), round(c_curr + 0.15 * atr_val, 2))

            conf = (
                75
                + (10 if is_volume_dryup else 0)
                + (10 if best_anchor_type_b == "BREAKOUT_RETEST" else 5)
            )
            conf = min(95, conf)

            summary = (
                f"Bearish {best_anchor_type_b} ({conf}% Conf): Shallow bounce ({bounce_depth:.2f} Fib) into "
                f"anchor ₹{best_anchor_lvl_b:.2f}. Volume dryup: {is_volume_dryup}. Re-ignited with {candle_tag_b}."
            )

            return PullbackSignal(
                symbol=symbol,
                pullback_type=best_anchor_type_b,
                bias="BEARISH",
                confidence=conf,
                anchor_level=best_anchor_lvl_b,
                pullback_depth_fib=bounce_depth,
                is_volume_dryup=is_volume_dryup,
                reignition_candle=candle_tag_b,
                entry_zone=entry_zone,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=summary,
            )

    return None


@dataclass
class AntiFomoEntryAssessment:
    """Deterministic institutional anti-FOMO entry & structural extension verdict."""

    extension_status: str  # "AT_PIVOT" | "IN_BASE_CHEAT" | "PULLBACK_RETEST" | "OVEREXTENDED_WAIT"
    is_extended: bool
    recommended_entry: float
    pullback_limit_entry: float
    no_chase_boundary: float
    structural_anchor: float
    ema20: float
    sma50: float
    sma200: float
    avwap_anchor: float
    dist_pivot_pct: float
    dist_ema20_atr: float
    dist_sma50_pct: float
    atr_14: float
    pullback_signal: Optional[PullbackSignal] = None
    action_directive: str = "ENTER_AT_PIVOT"


def evaluate_anti_fomo_entry(
    df: pd.DataFrame,
    ltp: float,
    *,
    pivot_price: float = 0.0,
    direction: str = "BULLISH",
    symbol: str = "",
) -> AntiFomoEntryAssessment:
    """Evaluate price extension against structural anchors (Pivot, 20-EMA, 50-SMA, AVWAP).

    Strictly prevents chasing extended price action by locking `no_chase_boundary`
    to the structural anchor (+2.5% for longs, -2.5% for shorts) and anchoring
    `pullback_limit_entry` to reachable support/resistance levels rather than `ltp`.
    """
    ltp_val = float(ltp or 0.0)
    is_bearish = str(direction).upper() == "BEARISH"
    if df is None or df.empty or ltp_val <= 0:
        anchor = float(pivot_price or ltp_val)
        nc = round(anchor * (0.975 if is_bearish else 1.025), 2) if anchor > 0 else 0.0
        return AntiFomoEntryAssessment(
            extension_status="AT_PIVOT",
            is_extended=False,
            recommended_entry=round(ltp_val, 2),
            pullback_limit_entry=round(anchor, 2),
            no_chase_boundary=nc,
            structural_anchor=round(anchor, 2),
            ema20=0.0,
            sma50=0.0,
            sma200=0.0,
            avwap_anchor=0.0,
            dist_pivot_pct=0.0,
            dist_ema20_atr=0.0,
            dist_sma50_pct=0.0,
            atr_14=0.0,
            pullback_signal=None,
            action_directive="WAIT_FOR_DATA",
        )

    close_s = df["close"].astype(float)
    high_s = df["high"].astype(float) if "high" in df.columns else close_s
    low_s = df["low"].astype(float) if "low" in df.columns else close_s

    ema20_val = 0.0
    sma50_val = 0.0
    sma200_val = 0.0
    atr_val = 0.0
    avwap_val = 0.0

    if len(close_s) >= 20:
        ema20_val = float(ema(close_s, 20).iloc[-1])
        if np.isnan(ema20_val):
            ema20_val = float(close_s.tail(20).mean())
    elif len(close_s) > 0:
        ema20_val = float(close_s.mean())

    if len(close_s) >= 50:
        sma50_val = float(close_s.rolling(50).mean().iloc[-1])
    elif len(close_s) >= 20:
        sma50_val = float(close_s.mean())

    if len(close_s) >= 200:
        sma200_val = float(close_s.rolling(200).mean().iloc[-1])

    if len(df) >= 15 and {"high", "low", "close"}.issubset(df.columns):
        atr_series = atr(df, period=14)
        atr_last = float(atr_series.iloc[-1])
        if not np.isnan(atr_last) and atr_last > 0:
            atr_val = atr_last
    if atr_val <= 0:
        atr_val = max(0.01, float((high_s.tail(14) - low_s.tail(14)).mean()))

    try:
        from analysis.anchored_vwap import compute_anchored_vwap

        if len(df) >= 20 and "volume" in df.columns:
            lookback = min(60, len(df))
            tail_df = df.tail(lookback)
            if is_bearish:
                anchor_pos = int(np.argmax(tail_df["high"].astype(float).values))
                anchor_type = "SWING_HIGH"
            else:
                anchor_pos = int(np.argmin(tail_df["low"].astype(float).values))
                anchor_type = "SWING_LOW"
            abs_idx = max(0, len(df) - lookback + anchor_pos)
            avwap_res = compute_anchored_vwap(df, anchor_index=abs_idx, anchor_type=anchor_type)
            if avwap_res is not None and getattr(avwap_res, "current_avwap", 0.0) > 0:
                avwap_val = float(avwap_res.current_avwap)
    except Exception:
        avwap_val = 0.0

    pivot_val = float(pivot_price or 0.0)
    if pivot_val > 0:
        structural_anchor = pivot_val
    else:
        ma_candidates = [v for v in (ema20_val, avwap_val, sma50_val) if v > 0]
        if is_bearish:
            above_ltp = [v for v in ma_candidates if v >= ltp_val]
            structural_anchor = (
                min(above_ltp) if above_ltp else (max(ma_candidates) if ma_candidates else ltp_val)
            )
        else:
            below_ltp = [v for v in ma_candidates if v <= ltp_val]
            structural_anchor = (
                max(below_ltp) if below_ltp else (min(ma_candidates) if ma_candidates else ltp_val)
            )

    if is_bearish:
        dist_pivot_pct = (
            ((structural_anchor - ltp_val) / structural_anchor * 100.0)
            if structural_anchor > 0
            else 0.0
        )
        dist_ema20_atr = (
            ((ema20_val - ltp_val) / atr_val) if (ema20_val > 0 and atr_val > 0) else 0.0
        )
        dist_sma50_pct = ((sma50_val - ltp_val) / sma50_val * 100.0) if sma50_val > 0 else 0.0
    else:
        dist_pivot_pct = (
            ((ltp_val - structural_anchor) / structural_anchor * 100.0)
            if structural_anchor > 0
            else 0.0
        )
        dist_ema20_atr = (
            ((ltp_val - ema20_val) / atr_val) if (ema20_val > 0 and atr_val > 0) else 0.0
        )
        dist_sma50_pct = ((ltp_val - sma50_val) / sma50_val * 100.0) if sma50_val > 0 else 0.0

    pullback_sig: Optional[PullbackSignal] = None
    if not is_bearish and len(df) >= 20:
        try:
            pullback_sig = evaluate_pullback(
                df,
                symbol=symbol or "ASSET",
                breakout_level=structural_anchor,
                atr_val=atr_val,
            )
        except Exception:
            pullback_sig = None

    pivot_extended = pivot_val > 0 and dist_pivot_pct > 2.5
    ema_extended = ema20_val > 0 and atr_val > 0 and dist_ema20_atr > 2.0
    sma_extended = sma50_val > 0 and dist_sma50_pct > 18.0
    is_extended = bool(pivot_extended or ema_extended or sma_extended)

    if is_bearish:
        no_chase_boundary = round(structural_anchor * 0.975, 2)
        res_candidates = [v for v in (structural_anchor, ema20_val, avwap_val) if v > ltp_val]
        if pullback_limit := (min(res_candidates) if res_candidates else 0.0):
            pullback_limit_entry = round(min(pullback_limit, ltp_val * 1.15), 2)
        else:
            pullback_limit_entry = round(max(structural_anchor, ltp_val * 1.015), 2)
    else:
        no_chase_boundary = round(structural_anchor * 1.025, 2)
        sup_candidates = [v for v in (structural_anchor, ema20_val, avwap_val) if 0 < v < ltp_val]
        if pullback_sig is not None and 0 < pullback_sig.anchor_level < ltp_val:
            sup_candidates.append(float(pullback_sig.anchor_level))
        reachable_supports = [v for v in sup_candidates if v >= ltp_val * 0.85]
        if reachable_supports:
            pullback_limit_entry = round(max(reachable_supports), 2)
        elif sup_candidates:
            pullback_limit_entry = round(max(sup_candidates), 2)
        elif ema20_val > 0:
            pullback_limit_entry = round(min(ltp_val * 0.975, ema20_val), 2)
        else:
            pullback_limit_entry = round(ltp_val * 0.975, 2)

    if is_extended:
        extension_status = "OVEREXTENDED_WAIT"
        recommended_entry = pullback_limit_entry
        action_directive = "WAIT_FOR_PULLBACK"
    elif pullback_sig is not None:
        extension_status = "PULLBACK_RETEST"
        recommended_entry = round(
            min(ltp_val, float(pullback_sig.anchor_level))
            if pullback_sig.anchor_level > 0
            else ltp_val,
            2,
        )
        action_directive = "ENTER_AT_RETEST"
    elif -6.0 <= dist_pivot_pct < -1.0:
        extension_status = "IN_BASE_CHEAT"
        recommended_entry = round(ltp_val, 2)
        action_directive = "STALK_CHEAT_OR_PIVOT"
    else:
        extension_status = "AT_PIVOT"
        recommended_entry = round(ltp_val, 2)
        action_directive = "ENTER_AT_PIVOT"

    return AntiFomoEntryAssessment(
        extension_status=extension_status,
        is_extended=is_extended,
        recommended_entry=round(recommended_entry, 2),
        pullback_limit_entry=round(pullback_limit_entry, 2),
        no_chase_boundary=no_chase_boundary,
        structural_anchor=round(structural_anchor, 2),
        ema20=round(ema20_val, 2),
        sma50=round(sma50_val, 2),
        sma200=round(sma200_val, 2),
        avwap_anchor=round(avwap_val, 2),
        dist_pivot_pct=round(dist_pivot_pct, 2),
        dist_ema20_atr=round(dist_ema20_atr, 2),
        dist_sma50_pct=round(dist_sma50_pct, 2),
        atr_14=round(atr_val, 2),
        pullback_signal=pullback_sig,
        action_directive=action_directive,
    )


def check_base_quality_and_supply(
    df: pd.DataFrame,
    entry_price: float,
    risk_pts: float,
    *,
    pivot_price: float = 0.0,
) -> dict[str, Any]:
    """Check institutional base-quality clues (3-Weeks-Tight, Pocket Pivot) and overhead supply.

    Returns runway distance in R-multiples to the nearest multi-month overhead
    resistance above the pivot/entry so cramped setups with <2.0R headroom are flagged.
    """
    result: dict[str, Any] = {
        "is_tight_flag": False,
        "has_pocket_pivot": False,
        "nearest_overhead_resistance": 0.0,
        "overhead_supply_r": None,
        "has_clear_runway": True,
    }
    if df is None or df.empty or entry_price <= 0:
        return result

    close_s = df["close"].astype(float)
    high_s = df["high"].astype(float) if "high" in df.columns else close_s
    open_s = df["open"].astype(float) if "open" in df.columns else close_s
    vol_s = df["volume"].astype(float) if "volume" in df.columns else None

    # 1. 3-Weeks-Tight / Tight Consolidation Flag
    if len(close_s) >= 25:
        w1 = float(close_s.iloc[-15:-10].iloc[-1])
        w2 = float(close_s.iloc[-10:-5].iloc[-1])
        w3 = float(close_s.iloc[-5:].iloc[-1])
        w_min = min(w1, w2, w3)
        w_max = max(w1, w2, w3)
        prior_move = (w1 - float(close_s.iloc[-25])) / max(1e-6, float(close_s.iloc[-25]))
        if w_min > 0 and ((w_max - w_min) / w_min) <= 0.018 and prior_move >= 0.05:
            result["is_tight_flag"] = True

    if not result["is_tight_flag"] and len(close_s) >= 20:
        recent_high = float(high_s.tail(10).max())
        recent_low = (
            float(df["low"].astype(float).tail(10).min())
            if "low" in df.columns
            else float(close_s.tail(10).min())
        )
        prior_close = float(close_s.iloc[-20])
        if recent_low > 0 and prior_close > 0:
            range_pct = (recent_high - recent_low) / recent_low
            prior_gain = (recent_low - prior_close) / prior_close
            if range_pct <= 0.06 and prior_gain >= 0.08:
                result["is_tight_flag"] = True

    # 2. Pocket Pivot inside base (up-bar volume > max down-day volume of prior 10 days)
    if vol_s is not None and len(df) >= 16:
        for offset in range(1, 6):
            idx = len(df) - offset
            if idx < 11:
                continue
            bar_close = float(close_s.iloc[idx])
            bar_open = float(open_s.iloc[idx])
            prev_close = float(close_s.iloc[idx - 1])
            bar_vol = float(vol_s.iloc[idx])
            if bar_close > bar_open and bar_close > prev_close and bar_vol > 0:
                win_c = close_s.iloc[idx - 10 : idx]
                win_prev = close_s.iloc[idx - 11 : idx - 1]
                win_v = vol_s.iloc[idx - 10 : idx]
                down_mask = win_c.values < win_prev.values
                if np.any(down_mask):
                    max_down_vol = float(np.max(win_v.values[down_mask]))
                    if bar_vol > max_down_vol > 0:
                        result["has_pocket_pivot"] = True
                        break

    # 3. Overhead Supply Check (exclude the current 20-bar breakout base itself)
    if len(high_s) >= 40 and risk_pts > 0:
        ref_level = max(entry_price, pivot_price) * 1.02
        hist_highs = high_s.iloc[-120:-20] if len(high_s) >= 120 else high_s.iloc[:-20]
        if not hist_highs.empty:
            # Find local swing highs strictly above current pivot zone
            vals = hist_highs.values
            swing_res: list[float] = []
            for i in range(2, len(vals) - 2):
                if (
                    vals[i] >= vals[i - 1]
                    and vals[i] >= vals[i - 2]
                    and vals[i] >= vals[i + 1]
                    and vals[i] >= vals[i + 2]
                ):
                    if vals[i] > ref_level:
                        swing_res.append(float(vals[i]))
            if swing_res:
                nearest_res = min(swing_res)
                overhead_r = (nearest_res - entry_price) / risk_pts
                result["nearest_overhead_resistance"] = round(nearest_res, 2)
                result["overhead_supply_r"] = round(overhead_r, 2)
                if overhead_r < 2.0:
                    result["has_clear_runway"] = False

    return result
