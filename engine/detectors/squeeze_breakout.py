"""
TTM Squeeze breakout and breakdown detector (Early Warning & Ignited).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def detect_squeeze_breakout(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects Volatility Squeeze coiling within 0.4% - 1.2% of resistance / 20D High.
    Triggers *before* the breakout candle runs away.
    """
    if df is None or len(df) < 25 or ltp <= 0:
        return None

    try:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volume"].values if "volume" in df.columns else None

        # 20-period Bollinger Bands
        period = 20
        sma20 = float(pd.Series(closes).rolling(period).mean().iloc[-1])
        std20 = float(pd.Series(closes).rolling(period).std().iloc[-1])
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # 20-period ATR & Keltner Channels
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr20 = float(pd.Series(tr).rolling(period).mean().iloc[-1]) if tr else (std20 * 0.8)
        keltner_upper = sma20 + (1.5 * atr20)
        keltner_lower = sma20 - (1.5 * atr20)

        # Squeeze is ON when BB is inside Keltner Channel
        is_squeeze_on = (bb_upper < keltner_upper) and (bb_lower > keltner_lower)

        # 20-day High and Low / Pivot levels
        lookback = min(20, len(highs) - 1)
        pivot_high = float(np.max(highs[-lookback - 1 : -1]))
        dist_to_pivot_pct = ((pivot_high - ltp) / pivot_high) * 100.0

        pivot_low = float(np.min(lows[-lookback - 1 : -1]))
        dist_to_low_pct = ((ltp - pivot_low) / pivot_low) * 100.0

        # RVOL 20D
        rvol = 1.0
        if volumes is not None and len(volumes) >= 20:
            avg_vol = float(np.mean(volumes[-21:-1]))
            cur_vol = float(volumes[-1])
            rvol = round(cur_vol / max(1.0, avg_vol), 2)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # ── EARLY WARNING (BULLISH): Coiled in squeeze, 0.2% - 1.5% below pivot high ───
        if is_squeeze_on and (0.2 <= dist_to_pivot_pct <= 1.5):
            target = round(pivot_high * 1.06, 1)
            sl = round(sma20, 1)
            conf = 72
            conf += min(10, int(rvol * 4))
            conf += 5 if dist_to_pivot_pct <= 0.7 else 0
            conf += 5 if ltp > sma20 else 0
            confidence_val = min(90, max(72, conf))
            return AutoAlert(
                alert_id=f"aa-sqz-early-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🎯 SQUEEZE COILING: {symbol} at ₹{ltp:,.1f} (Pivot ₹{pivot_high:,.1f})",
                summary=(
                    f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                    f"Price is only {dist_to_pivot_pct:.1f}% below pivot resistance. "
                    f"RVOL {rvol}x. Imminent explosive breakout setup!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_on": True,
                    "dist_to_pivot_pct": round(dist_to_pivot_pct, 2),
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "sma20": round(sma20, 1),
                    "atr20": round(atr20, 1),
                },
                actionable_plan={
                    "action": "BUY_ON_PIVOT",
                    "entry_range": f"₹{ltp:.1f} - ₹{pivot_high:.1f}",
                    "breakout_trigger": f"₹{pivot_high:.1f}",
                    "target": f"₹{target:.1f} (+6.0%)",
                    "stop_loss": f"₹{sl:.1f} (-{round(((ltp - sl) / ltp) * 100, 1)}%)",
                },
                confidence=confidence_val,
                created_at=now_iso,
            )

        # ── EARLY WARNING (BEARISH): Coiled in squeeze, 0.2% - 1.5% above pivot low support ───
        if is_squeeze_on and (0.2 <= dist_to_low_pct <= 1.5):
            target = round(pivot_low * 0.94, 1)
            sl = round(sma20, 1)
            conf_be = 72
            conf_be += min(10, int(rvol * 5))
            conf_be += 5 if dist_to_low_pct <= 0.7 else 0
            conf_be += 5 if ltp < sma20 else 0
            confidence_bear_ew = min(90, max(72, conf_be))
            return AutoAlert(
                alert_id=f"aa-sqz-bear-early-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKDOWN",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BEARISH",
                headline=f"⚠️ SQUEEZE BREAKDOWN COILING: {symbol} at ₹{ltp:,.1f} (Support ₹{pivot_low:,.1f})",
                summary=(
                    f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                    f"Price is only {dist_to_low_pct:.1f}% above 20D low support. "
                    f"RVOL {rvol}x. Imminent downside breakdown risk!"
                ),
                ltp=ltp,
                trigger_level=pivot_low,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_on": True,
                    "dist_to_low_pct": round(dist_to_low_pct, 2),
                    "pivot_low": pivot_low,
                    "rvol": rvol,
                    "sma20": round(sma20, 1),
                    "atr20": round(atr20, 1),
                },
                actionable_plan={
                    "action": "SELL_ON_BREAKDOWN",
                    "entry_range": f"₹{pivot_low:.1f} - ₹{ltp:.1f}",
                    "breakout_trigger": f"₹{pivot_low:.1f}",
                    "target": f"₹{target:.1f} (-6.0%)",
                    "stop_loss": f"₹{sl:.1f} (+{round(((sl - ltp) / ltp) * 100, 1)}%)",
                },
                confidence=confidence_bear_ew,
                created_at=now_iso,
            )

        # ── IGNITED (BULLISH): Squeeze Fired + Fresh Breakout above pivot ───
        if (
            ltp >= pivot_high
            and (ltp - pivot_high) / pivot_high <= 0.025
            and rvol >= 1.4
            and ltp > sma20
        ):
            target = round(ltp * 1.08, 1)
            sl = round(pivot_high * 0.985, 1)
            conf_ig = 82
            conf_ig += min(8, int(rvol * 4))
            conf_ig += 5 if (ltp - pivot_high) / pivot_high <= 0.01 else 0
            confidence_ignited = min(95, max(82, conf_ig))
            return AutoAlert(
                alert_id=f"aa-sqz-ignited-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="IGNITED",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🚀 SQUEEZE BREAKOUT IGNITED: {symbol} broke ₹{pivot_high:,.1f}",
                summary=(
                    f"TTM Squeeze fired with heavy institutional volume (RVOL {rvol}x). "
                    f"Price clearing 20-day high ₹{pivot_high:,.1f} (+{round(((ltp - pivot_high) / pivot_high) * 100, 1)}%). "
                    f"Primary breakout expansion phase active!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_fired": True,
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "breakout_pct": round(((ltp - pivot_high) / pivot_high) * 100, 2),
                },
                actionable_plan={
                    "action": "BUY_EXPANSION",
                    "entry_range": f"₹{ltp:.1f}",
                    "target": f"₹{target:.1f} (+8.0%)",
                    "stop_loss": f"₹{sl:.1f} (-1.5%)",
                },
                confidence=confidence_ignited,
                created_at=now_iso,
            )

        # ── IGNITED (BEARISH): Squeeze Fired + Fresh Breakdown below pivot low ───
        if (
            ltp <= pivot_low
            and (pivot_low - ltp) / pivot_low <= 0.025
            and rvol >= 1.4
            and ltp < sma20
        ):
            target = round(ltp * 0.92, 1)
            sl = round(pivot_low * 1.015, 1)
            conf_big = 82
            conf_big += min(8, int(rvol * 4))
            conf_big += 5 if (pivot_low - ltp) / pivot_low <= 0.01 else 0
            confidence_bear_ig = min(95, max(82, conf_big))
            return AutoAlert(
                alert_id=f"aa-sqz-bear-ignited-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKDOWN",
                stage="IGNITED",
                symbol=symbol,
                exchange=exchange,
                direction="BEARISH",
                headline=f"⚡ SQUEEZE BREAKDOWN IGNITED: {symbol} broke below ₹{pivot_low:,.1f}",
                summary=(
                    f"TTM Squeeze breakdown fired with institutional volume (RVOL {rvol}x). "
                    f"Price cracked 20-day low ₹{pivot_low:,.1f} (-{round(((pivot_low - ltp) / pivot_low) * 100, 1)}%). "
                    f"Downside expansion phase active!"
                ),
                ltp=ltp,
                trigger_level=pivot_low,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_fired": True,
                    "pivot_low": pivot_low,
                    "rvol": rvol,
                    "breakdown_pct": round(((pivot_low - ltp) / pivot_low) * 100, 2),
                },
                actionable_plan={
                    "action": "SELL_EXPANSION",
                    "entry_range": f"₹{ltp:.1f}",
                    "target": f"₹{target:.1f} (-8.0%)",
                    "stop_loss": f"₹{sl:.1f} (+1.5%)",
                },
                confidence=confidence_bear_ig,
                created_at=now_iso,
            )

    except Exception as e:
        logger.debug(f"[SqueezeBreakout] Error evaluating {symbol}: {e}")

    return None
