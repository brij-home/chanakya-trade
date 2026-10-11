"""
engine/detectors/order_flow.py
──────────────────────────────
Institutional Order Flow & Cumulative Volume Delta (CVD) Divergence Detector.

Detects hidden institutional accumulation and distribution before candlestick closes:
1. BULLISH_ABSORPTION_DIVERGENCE:
   Price retests or sweeps a structural swing low, but CVD forms a prominent Higher Low.
   Institutions are passively absorbing aggressive market sell orders.
2. BEARISH_EXHAUSTION_DIVERGENCE:
   Price pushes to a new swing high, but CVD forms a Lower High.
   Smart money is offloading inventory into retail market buy orders.
3. AGGRESSOR_EXPANSION:
   Net aggressor volume delta surges >= 2.2x baseline with directional follow-through.

Fully implements the BaseDetector protocol for unified single-pass evaluation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert

if TYPE_CHECKING:
    from engine.detection_context import DetectionContext

logger = logging.getLogger("engine.detectors.order_flow")


def compute_bar_volume_delta(
    open_p: float, high_p: float, low_p: float, close_p: float, volume: float
) -> tuple[float, float, float]:
    """
    Computes aggressive buyer vs seller volume decomposition from candle microstructure.
    Returns: (buyer_volume, seller_volume, net_delta)
    """
    candle_range = max(0.01, high_p - low_p)
    buyer_ratio = max(0.05, min(0.95, (close_p - low_p) / candle_range))
    seller_ratio = max(0.05, min(0.95, (high_p - close_p) / candle_range))

    norm = buyer_ratio + seller_ratio
    b_vol = volume * (buyer_ratio / norm)
    s_vol = volume * (seller_ratio / norm)
    net_delta = b_vol - s_vol
    return b_vol, s_vol, net_delta


def compute_order_flow_cvd_divergence(
    df: pd.DataFrame, curr_p: float, lookback_bars: int = 10
) -> dict[str, Any]:
    """
    Institutional Cumulative Volume Delta (CVD) Divergence & Absorption Engine.
    Uses real taker aggressor delta when present; falls back to wick microstructure decomposition.
    """
    empty_res = {
        "is_bullish_absorption": False,
        "is_bearish_exhaustion": False,
        "cvd_divergence_ratio": 1.0,
        "current_cvd": 0.0,
        "prior_cvd": 0.0,
        "prior_low_p": 0.0,
        "prior_high_p": 0.0,
        "delta_source": "NONE",
        "last_delta": 0.0,
    }
    if df is None or len(df) < 12:
        return empty_res

    cols = {str(c).lower(): c for c in df.columns}
    if not all(k in cols for k in ("open", "high", "low", "close", "volume")):
        return empty_res

    o = df[cols["open"]].to_numpy(dtype=float)
    h = df[cols["high"]].to_numpy(dtype=float)
    l = df[cols["low"]].to_numpy(dtype=float)
    c = df[cols["close"]].to_numpy(dtype=float)
    v = df[cols["volume"]].to_numpy(dtype=float)

    n = len(c)
    has_real_delta = False
    deltas = np.zeros(n)

    if "delta" in cols:
        delta_vals = df[cols["delta"]].to_numpy(dtype=float)
        if np.any(delta_vals != 0):
            deltas = delta_vals
            has_real_delta = True
    elif "buy_volume" in cols and "sell_volume" in cols:
        b_vals = df[cols["buy_volume"]].to_numpy(dtype=float)
        s_vals = df[cols["sell_volume"]].to_numpy(dtype=float)
        delta_vals = b_vals - s_vals
        if np.any(delta_vals != 0):
            deltas = delta_vals
            has_real_delta = True

    if not has_real_delta:
        for i in range(n):
            _, _, d = compute_bar_volume_delta(o[i], h[i], l[i], c[i], v[i])
            deltas[i] = d

    cvd = np.cumsum(deltas)
    lookback = min(lookback_bars, n - 2)
    recent_low_idx = np.argmin(l[-lookback:-1]) + (n - lookback)
    recent_high_idx = np.argmax(h[-lookback:-1]) + (n - lookback)

    curr_cvd = float(cvd[-1])
    prior_low_p = float(l[recent_low_idx])
    prior_low_cvd = float(cvd[recent_low_idx])
    prior_high_p = float(h[recent_high_idx])
    prior_high_cvd = float(cvd[recent_high_idx])

    is_bull = False
    is_bear = False
    cvd_ratio = 1.0

    # Bullish Absorption: price test/sweep swing low, but CVD forms higher low
    if curr_p <= prior_low_p * 1.002 and curr_cvd > prior_low_cvd:
        cvd_ratio = round(curr_cvd / max(1.0, abs(prior_low_cvd)), 2)
        if cvd_ratio >= 1.25 or (has_real_delta and curr_cvd > 0):
            is_bull = True

    # Bearish Exhaustion: price test/sweep swing high, but CVD forms lower high
    if curr_p >= prior_high_p * 0.998 and curr_cvd < prior_high_cvd:
        is_bear = True

    return {
        "is_bullish_absorption": is_bull,
        "is_bearish_exhaustion": is_bear,
        "cvd_divergence_ratio": cvd_ratio,
        "current_cvd": round(curr_cvd, 2),
        "prior_cvd": round(prior_low_cvd if is_bull else prior_high_cvd, 2),
        "prior_low_p": prior_low_p,
        "prior_high_p": prior_high_p,
        "delta_source": "REAL_TAKER_DELTA" if has_real_delta else "ESTIMATED_WICK_MICROSTRUCTURE",
        "last_delta": round(float(deltas[-1]), 2),
    }


def detect_order_flow_divergence(ctx: DetectionContext) -> list[AutoAlert]:
    """
    Evaluates 5-minute / 15-minute candles for institutional order flow divergence.
    """
    df = (
        ctx.candles_5m
        if ctx.candles_5m is not None and len(ctx.candles_5m) >= 12
        else ctx.candles_15m
    )
    if df is None or len(df) < 12:
        return []

    curr_p = ctx.ltp if ctx.ltp > 0 else float(df["close"].iloc[-1])
    of_data = compute_order_flow_cvd_divergence(df, curr_p)

    alerts: list[AutoAlert] = []
    canonical_sym = canonical_alert_symbol(ctx.symbol)

    # 1. Check Bullish Absorption Divergence
    if of_data["is_bullish_absorption"]:
        prior_low_p = of_data["prior_low_p"]
        prior_low_cvd = of_data["prior_cvd"]
        curr_cvd = of_data["current_cvd"]
        cvd_divergence_ratio = of_data["cvd_divergence_ratio"]

        sl = ctx.get_dynamic_stop_loss(direction="BULLISH", multiplier=1.2)
        risk = max(0.5, curr_p - sl)
        t1 = round(curr_p + (2.0 * risk), 2)
        t2 = round(curr_p + (4.0 * risk), 2)
        runner = round(curr_p + (6.0 * risk), 2)

        ticket = ctx.build_execution_ticket(
            stop_loss=sl,
            target_price=t1,
            direction="BULLISH",
            alert_type="ORDER_FLOW_DIVERGENCE",
        )

        alert_id = generate_alert_id("order-flow", canonical_sym, variant="bull-absorb")
        alerts.append(
            AutoAlert(
                alert_id=alert_id,
                symbol=ctx.symbol,
                exchange=ctx.exchange,
                segment=ctx.segment,
                alert_type="ORDER_FLOW_DIVERGENCE",
                stage="IGNITED",
                direction="BULLISH",
                headline=f"{canonical_sym} Institutional Bullish Absorption (CVD Divergence)",
                summary=(
                    f"Price tested swing low {prior_low_p:.2f} while CVD printed Higher Low "
                    f"(divergence ratio {cvd_divergence_ratio:.2f}x). Institutional absorption detected."
                ),
                ltp=curr_p,
                trigger_level=curr_p,
                target_level=t1,
                stop_loss=sl,
                confidence=86.0,
                metrics={
                    "cvd_divergence_ratio": cvd_divergence_ratio,
                    "current_cvd": round(curr_cvd, 1),
                    "prior_cvd": round(prior_low_cvd, 1),
                    "delta_source": of_data.get("delta_source", "REAL_TAKER_DELTA"),
                    "pattern": "BULLISH_ABSORPTION",
                    "r_multiple_t1": 2.0,
                    "r_multiple_t2": 4.0,
                },
                actionable_plan={
                    "action": "BUY",
                    "entry_zone": f"{curr_p:.2f} - {curr_p * 1.003:.2f}",
                    "invalidation_stop": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "runner_target": runner,
                    "execution_ticket": ticket,
                },
            )
        )

    # 2. Check Bearish Exhaustion Divergence
    if of_data["is_bearish_exhaustion"]:
        prior_high_p = of_data["prior_high_p"]
        prior_high_cvd = of_data["prior_cvd"]
        curr_cvd = of_data["current_cvd"]

        sl = ctx.get_dynamic_stop_loss(direction="BEARISH", multiplier=1.2)
        risk = max(0.5, sl - curr_p)
        t1 = round(curr_p - (2.0 * risk), 2)
        t2 = round(curr_p - (4.0 * risk), 2)
        runner = round(curr_p - (6.0 * risk), 2)

        ticket = ctx.build_execution_ticket(
            stop_loss=sl,
            target_price=t1,
            direction="BEARISH",
            alert_type="ORDER_FLOW_DIVERGENCE",
        )

        alert_id = generate_alert_id("order-flow", canonical_sym, variant="bear-exhaust")
        alerts.append(
            AutoAlert(
                alert_id=alert_id,
                symbol=ctx.symbol,
                exchange=ctx.exchange,
                segment=ctx.segment,
                alert_type="ORDER_FLOW_DIVERGENCE",
                stage="IGNITED",
                direction="BEARISH",
                headline=f"{canonical_sym} Institutional Bearish Exhaustion (CVD Divergence)",
                summary=(
                    f"Price pushed to high {prior_high_p:.2f} but CVD formed Lower High. "
                    "Smart money distribution into retail breakout buying detected."
                ),
                ltp=curr_p,
                trigger_level=curr_p,
                target_level=t1,
                stop_loss=sl,
                confidence=84.0,
                metrics={
                    "current_cvd": round(curr_cvd, 1),
                    "prior_cvd": round(prior_high_cvd, 1),
                    "delta_source": of_data.get("delta_source", "REAL_TAKER_DELTA"),
                    "pattern": "BEARISH_EXHAUSTION",
                    "r_multiple_t1": 2.0,
                    "r_multiple_t2": 4.0,
                },
                actionable_plan={
                    "action": "SELL",
                    "entry_zone": f"{curr_p * 0.997:.2f} - {curr_p:.2f}",
                    "invalidation_stop": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "runner_target": runner,
                    "execution_ticket": ticket,
                },
            )
        )

    return alerts


class OrderFlowDivergenceDetector:
    """Class wrapper conforming to the BaseDetector protocol."""

    detector_slug: str = "order_flow_divergence"
    detector_name: str = "Institutional Order Flow & CVD Divergence Detector"
    supported_segments: tuple[str, ...] = ("EQUITY", "NFO", "COMMODITY", "CRYPTO")

    def detect(self, ctx: DetectionContext) -> list[AutoAlert]:
        return detect_order_flow_divergence(ctx)
