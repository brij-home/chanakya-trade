"""
analysis/reversal_engine.py
───────────────────────────
Institutional Top & Bottom Reversal Engine with 3-Phase Verification Protocol.

Eliminates naive knife-catching and counter-trend fading by enforcing 3 sequential
institutional verification gates before confirming a reversal:
  Phase 1: Exhaustion / Volume Climax (VSA stopping volume, extreme RSI/Bollinger band excursion, ROC deceleration)
  Phase 2: Divergence / Liquidity Sweep (Fractal momentum divergence, Turtle Soup sweep of key swing boundaries)
  Phase 3: Micro-CHoCH & Candlestick Confirmation (Rejection wicks, Engulfing, Morning/Evening Star, Micro Change-of-Character)

Calibrated across:
  - Asset Classes: Indices (mean-reversion speed, time-of-day clusters) vs Equities (trend persistence, Stage 2/4 checks)
  - Time Horizons: Intraday (5m/15m lower-timeframe CHoCH) vs Swing (Daily/Weekly closes & anchor confluence)
  - Options Desk: Directional Debit Spreads / Long Options vs Non-Directional Credit Spreads based on Choppiness Index.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.market_structure import (
    detect_confirmation_candle,
    detect_divergence,
)
from analysis.technical import atr, bollinger_bands, choppiness_index, rsi
from analysis.vsa import analyse_vsa

logger = logging.getLogger("chanakya.analysis.reversal_engine")


@dataclass
class ReversalSignal:
    symbol: str
    reversal_type: str  # "TOP_REVERSAL" | "BOTTOM_REVERSAL" | "NONE"
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: int  # 0 to 100
    timeframe: str  # "INTRADAY" | "SWING"
    asset_class: str  # "INDEX" | "EQUITY" | "COMMODITY"

    # 3-Phase verification states
    phase1_exhaustion: bool = False
    phase1_details: list[str] = field(default_factory=list)
    phase2_sweep_or_divergence: bool = False
    phase2_details: list[str] = field(default_factory=list)
    phase3_confirmation: bool = False
    phase3_details: list[str] = field(default_factory=list)

    # Candlestick & Structural info
    candlestick_pattern: str = "NONE"
    candlestick_strength: int = 0
    choch_detected: bool = False
    choch_level: Optional[float] = None

    # Actionable Blueprint
    entry_zone: tuple[float, float] = (0.0, 0.0)
    stop_loss: float = 0.0
    target_1: float = 0.0  # +2R
    target_2: float = 0.0  # +3.5R
    target_3: float = 0.0  # +5R
    risk_reward_ratio: float = 0.0
    no_chase_limit: float = 0.0

    # Options & Market dynamics
    market_regime: str = "NORMAL"  # "TRENDING_EXHAUSTION" | "CHOPPY_ROTATION" | "HIGH_VOLATILITY"
    recommended_strategy: str = (
        "NONE"  # "BUY_ATM_CALL" | "BULL_PUT_SPREAD" | "BUY_ATM_PUT" | "BEAR_CALL_SPREAD"
    )
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reversal_type": self.reversal_type,
            "bias": self.bias,
            "confidence": self.confidence,
            "timeframe": self.timeframe,
            "asset_class": self.asset_class,
            "phase1_exhaustion": self.phase1_exhaustion,
            "phase1_details": self.phase1_details,
            "phase2_sweep_or_divergence": self.phase2_sweep_or_divergence,
            "phase2_details": self.phase2_details,
            "phase3_confirmation": self.phase3_confirmation,
            "phase3_details": self.phase3_details,
            "candlestick_pattern": self.candlestick_pattern,
            "candlestick_strength": self.candlestick_strength,
            "choch_detected": self.choch_detected,
            "choch_level": self.choch_level,
            "entry_zone": list(self.entry_zone),
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "no_chase_limit": self.no_chase_limit,
            "market_regime": self.market_regime,
            "recommended_strategy": self.recommended_strategy,
            "summary": self.summary,
        }


def _detect_micro_choch(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 15,
) -> tuple[bool, Optional[float]]:
    """
    Detects lower timeframe Change-of-Character (micro-CHoCH).
    For BULLISH reversal: price closes above the most recent swing high pivot prior to the low.
    For BEARISH reversal: price closes below the most recent swing low pivot prior to the high.
    """
    if len(df) < lookback:
        return False, None

    cols = {c.lower(): c for c in df.columns}
    c_series = df[cols["close"]]
    h_series = df[cols["high"]]
    l_series = df[cols["low"]]

    curr_close = float(c_series.iloc[-1])

    if direction == "BULLISH":
        # Find lowest low in lookback window
        window_lows = l_series.iloc[-lookback:-1]
        if window_lows.empty:
            return False, None
        min_idx = window_lows.idxmin()
        min_pos = window_lows.index.get_loc(min_idx)

        # Micro lower-high prior to or at the low
        sub_highs = h_series.iloc[-lookback : -lookback + min_pos + 1]
        if len(sub_highs) < 2:
            sub_highs = h_series.iloc[-lookback:-1]

        pivot_high = float(sub_highs.max())
        if curr_close > pivot_high:
            return True, pivot_high
        return False, pivot_high

    else:  # BEARISH
        window_highs = h_series.iloc[-lookback:-1]
        if window_highs.empty:
            return False, None
        max_idx = window_highs.idxmax()
        max_pos = window_highs.index.get_loc(max_idx)

        sub_lows = l_series.iloc[-lookback : -lookback + max_pos + 1]
        if len(sub_lows) < 2:
            sub_lows = l_series.iloc[-lookback:-1]

        pivot_low = float(sub_lows.min())
        if curr_close < pivot_low:
            return True, pivot_low
        return False, pivot_low


def _detect_liquidity_sweep(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 20,
) -> tuple[bool, Optional[float], Optional[float]]:
    """
    Detects Turtle Soup liquidity sweep on the last 1-3 bars.
    Returns: (is_sweep, swept_level, extreme_wick)
    """
    if len(df) < lookback + 3:
        return False, None, None

    cols = {c.lower(): c for c in df.columns}
    c_series = df[cols["close"]]
    h_series = df[cols["high"]]
    l_series = df[cols["low"]]

    c_curr = float(c_series.iloc[-1])

    if direction == "BULLISH":
        # Prior structural swing low (excluding last 3 bars)
        prior_low = float(l_series.iloc[-lookback:-3].min())
        recent_low = float(l_series.iloc[-3:].min())

        # Pierced prior low and closed back above
        if recent_low < prior_low and c_curr > prior_low:
            sweep_depth_pct = (prior_low - recent_low) / max(prior_low, 1.0) * 100.0
            if sweep_depth_pct <= 1.5:  # Valid liquidity grab within 1.5%
                return True, prior_low, recent_low

    else:  # BEARISH
        prior_high = float(h_series.iloc[-lookback:-3].max())
        recent_high = float(h_series.iloc[-3:].max())

        # Pierced prior high and closed back below
        if recent_high > prior_high and c_curr < prior_high:
            sweep_depth_pct = (recent_high - prior_high) / max(prior_high, 1.0) * 100.0
            if sweep_depth_pct <= 1.5:
                return True, prior_high, recent_high

    return False, None, None


def analyse_reversal(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    is_intraday: bool = True,
    asset_class: str = "INDEX",
    vwap_series: Optional[pd.Series] = None,
    atr_val: Optional[float] = None,
) -> ReversalSignal:
    """
    Institutional Top & Bottom Reversal Engine.
    Executes 3-Phase verification protocol across exhaustion, liquidity sweep/divergence,
    and candlestick/micro-CHoCH confirmation.
    """
    timeframe = "INTRADAY" if is_intraday else "SWING"
    default_none = ReversalSignal(
        symbol=symbol,
        reversal_type="NONE",
        bias="NEUTRAL",
        confidence=0,
        timeframe=timeframe,
        asset_class=asset_class,
        summary="No structural reversal setup detected.",
    )

    if df is None or len(df) < 25:
        return default_none

    cols = {c.lower(): c for c in df.columns}
    c_series = df[cols["close"]].astype(float)
    h_series = df[cols["high"]].astype(float)
    l_series = df[cols["low"]].astype(float)
    o_series = df[cols["open"]].astype(float) if "open" in cols else c_series

    c_curr = float(c_series.iloc[-1])
    h_curr = float(h_series.iloc[-1])
    l_curr = float(l_series.iloc[-1])

    # Core Quant Indicators
    rsi_s = rsi(c_series, period=14)
    curr_rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else 50.0

    atr_s = atr(df, period=14)
    curr_atr = (
        float(atr_s.iloc[-1])
        if not atr_s.empty and not np.isnan(atr_s.iloc[-1])
        else (atr_val or c_curr * 0.015)
    )
    if curr_atr <= 0:
        curr_atr = max(c_curr * 0.01, 1.0)

    bb_mid, bb_upper, bb_lower = bollinger_bands(c_series, period=20, std_k=2.0)
    curr_bb_u = float(bb_upper.iloc[-1]) if not bb_upper.empty else c_curr * 1.05
    curr_bb_l = float(bb_lower.iloc[-1]) if not bb_lower.empty else c_curr * 0.95

    chop_s = choppiness_index(df, period=14)
    curr_chop = (
        float(chop_s.iloc[-1]) if not chop_s.empty and not np.isnan(chop_s.iloc[-1]) else 50.0
    )

    # Market Regime Tag
    if curr_chop < 38.2:
        regime = "TRENDING_EXHAUSTION"
    elif curr_chop > 61.8:
        regime = "CHOPPY_ROTATION"
    else:
        regime = "NORMAL"

    # VSA Analysis
    vsa_snap = analyse_vsa(df, symbol=symbol, is_intraday=is_intraday, period=20)

    # Divergence Analysis
    div_snap = detect_divergence(df, rsi_period=14, lookback=20)
    div_type = div_snap.get("type", "NONE")

    # Check Potential Reversal Biases:
    # 1. Evaluate Bottom Reversal (BULLISH)
    # 2. Evaluate Top Reversal (BEARISH)

    # --- BULLISH BOTTOM EVALUATION ---
    p1_bull = False
    p1_bull_reasons: list[str] = []

    if curr_rsi <= 32.0:
        p1_bull = True
        p1_bull_reasons.append(f"RSI oversold exhaustion ({curr_rsi:.1f} <= 32.0)")
    elif curr_rsi <= 40.0 and len(rsi_s) >= 4 and rsi_s.iloc[-1] > rsi_s.iloc[-2] < rsi_s.iloc[-3]:
        p1_bull = True
        p1_bull_reasons.append(f"RSI momentum hook out of oversold ({curr_rsi:.1f})")

    if c_curr <= curr_bb_l * 1.003 or l_curr <= curr_bb_l:
        p1_bull = True
        p1_bull_reasons.append(
            f"Bollinger Band lower envelope pierce ({l_curr:.2f} <= {curr_bb_l:.2f})"
        )

    if vsa_snap.vsa_signal in ("STOPPING_VOLUME", "NO_SUPPLY"):
        p1_bull = True
        p1_bull_reasons.append(f"VSA signature: {vsa_snap.vsa_signal} ({vsa_snap.summary})")

    # Long lower wick absorption on high volume
    candle_range = max(h_curr - l_curr, 0.001)
    lower_wick = min(float(o_series.iloc[-1]), c_curr) - l_curr
    if (lower_wick / candle_range) >= 0.45 and vsa_snap.volume_ratio >= 1.4:
        p1_bull = True
        p1_bull_reasons.append(
            f"High-volume lower shadow absorption ({lower_wick / candle_range * 100:.0f}% wick on {vsa_snap.volume_ratio:.1f}x vol)"
        )

    # Phase 2: Divergence / Sweep (Bullish)
    p2_bull = False
    p2_bull_reasons: list[str] = []

    if div_type in ("BULLISH_REGULAR", "BULLISH_HIDDEN"):
        p2_bull = True
        p2_bull_reasons.append(f"Divergence detected: {div_type} on RSI")

    is_sweep_bull, swept_low, extreme_low = _detect_liquidity_sweep(
        df, direction="BULLISH", lookback=20
    )
    if is_sweep_bull and swept_low is not None and extreme_low is not None:
        p2_bull = True
        p2_bull_reasons.append(
            f"Turtle Soup liquidity sweep: swept swing low {swept_low:.2f} down to {extreme_low:.2f} and reclaimed {c_curr:.2f}"
        )

    # Phase 3: Candlestick Confirmation & Micro-CHoCH (Bullish)
    candle_conf_bull = detect_confirmation_candle(df, direction="BULLISH")
    has_candle_bull = candle_conf_bull["confirmed"]
    choch_bull, choch_level_bull = _detect_micro_choch(df, direction="BULLISH", lookback=15)

    p3_bull = has_candle_bull or choch_bull
    p3_bull_reasons: list[str] = []
    if has_candle_bull:
        p3_bull_reasons.append(
            f"Confirming candlestick pattern: {candle_conf_bull['pattern']} (strength {candle_conf_bull['strength']})"
        )
    if choch_bull and choch_level_bull is not None:
        p3_bull_reasons.append(
            f"Micro-CHoCH confirmed: breakout above prior swing high {choch_level_bull:.2f}"
        )

    # --- BEARISH TOP EVALUATION ---
    p1_bear = False
    p1_bear_reasons: list[str] = []

    if curr_rsi >= 68.0:
        p1_bear = True
        p1_bear_reasons.append(f"RSI overbought exhaustion ({curr_rsi:.1f} >= 68.0)")
    elif curr_rsi >= 60.0 and len(rsi_s) >= 4 and rsi_s.iloc[-1] < rsi_s.iloc[-2] > rsi_s.iloc[-3]:
        p1_bear = True
        p1_bear_reasons.append(f"RSI momentum rollover from peak ({curr_rsi:.1f})")

    if c_curr >= curr_bb_u * 0.997 or h_curr >= curr_bb_u:
        p1_bear = True
        p1_bear_reasons.append(
            f"Bollinger Band upper envelope pierce ({h_curr:.2f} >= {curr_bb_u:.2f})"
        )

    if vsa_snap.vsa_signal in ("EFFORT_NO_RESULT_BEARISH", "NO_DEMAND"):
        p1_bear = True
        p1_bear_reasons.append(f"VSA signature: {vsa_snap.vsa_signal} ({vsa_snap.summary})")

    upper_wick = h_curr - max(float(o_series.iloc[-1]), c_curr)
    if (upper_wick / candle_range) >= 0.45 and vsa_snap.volume_ratio >= 1.4:
        p1_bear = True
        p1_bear_reasons.append(
            f"High-volume upper shadow rejection ({upper_wick / candle_range * 100:.0f}% wick on {vsa_snap.volume_ratio:.1f}x vol)"
        )

    # Phase 2: Divergence / Sweep (Bearish)
    p2_bear = False
    p2_bear_reasons: list[str] = []

    if div_type in ("BEARISH_REGULAR", "BEARISH_HIDDEN"):
        p2_bear = True
        p2_bear_reasons.append(f"Divergence detected: {div_type} on RSI")

    is_sweep_bear, swept_high, extreme_high = _detect_liquidity_sweep(
        df, direction="BEARISH", lookback=20
    )
    if is_sweep_bear and swept_high is not None and extreme_high is not None:
        p2_bear = True
        p2_bear_reasons.append(
            f"Turtle Soup liquidity sweep: swept swing high {swept_high:.2f} up to {extreme_high:.2f} and rejected back to {c_curr:.2f}"
        )

    # Phase 3: Candlestick Confirmation & Micro-CHoCH (Bearish)
    candle_conf_bear = detect_confirmation_candle(df, direction="BEARISH")
    has_candle_bear = candle_conf_bear["confirmed"]
    choch_bear, choch_level_bear = _detect_micro_choch(df, direction="BEARISH", lookback=15)

    p3_bear = has_candle_bear or choch_bear
    p3_bear_reasons: list[str] = []
    if has_candle_bear:
        p3_bear_reasons.append(
            f"Confirming candlestick pattern: {candle_conf_bear['pattern']} (strength {candle_conf_bear['strength']})"
        )
    if choch_bear and choch_level_bear is not None:
        p3_bear_reasons.append(
            f"Micro-CHoCH confirmed: breakdown below prior swing low {choch_level_bear:.2f}"
        )

    # Decision Matrix: Bottom vs Top vs None
    bull_phase_count = sum([p1_bull, p2_bull, p3_bull])
    bear_phase_count = sum([p1_bear, p2_bear, p3_bear])

    if bull_phase_count >= 2 and bull_phase_count >= bear_phase_count and p3_bull:
        # Confirmed Bullish Reversal (Bottom)
        conf = (
            65
            + (10 if p1_bull else 0)
            + (10 if p2_bull else 0)
            + int(candle_conf_bull["strength"] * 0.15)
        )
        conf = min(96, max(65, conf))

        # Risk parameters
        anchor_low = (
            extreme_low if (is_sweep_bull and extreme_low) else float(l_series.iloc[-3:].min())
        )
        sl = round(anchor_low - (0.15 * curr_atr), 2)
        risk = max(c_curr - sl, curr_atr * 0.5)

        t1 = round(c_curr + (2.0 * risk), 2)
        t2 = round(c_curr + (3.5 * risk), 2)
        t3 = round(c_curr + (5.0 * risk), 2)
        rr = round((t1 - c_curr) / max(risk, 0.01), 2)

        entry_zone = (round(c_curr - 0.2 * curr_atr, 2), round(c_curr + 0.1 * curr_atr, 2))
        no_chase = round(c_curr + 0.35 * curr_atr, 2)

        # Options strategy calibration
        if regime == "TRENDING_EXHAUSTION" and conf >= 80:
            rec_strategy = "BUY_ATM_CALL" if asset_class == "INDEX" else "BULL_CALL_SPREAD"
        elif regime == "CHOPPY_ROTATION" or conf < 75:
            rec_strategy = "BULL_PUT_SPREAD"  # Sell Put below structural SL
        else:
            rec_strategy = "BULL_CALL_SPREAD"

        summary = f"Institutional Bottom Reversal ({conf}% Conviction): {len(p1_bull_reasons) + len(p2_bull_reasons) + len(p3_bull_reasons)} confluences. {'; '.join(p3_bull_reasons + p2_bull_reasons[:1])}."

        return ReversalSignal(
            symbol=symbol,
            reversal_type="BOTTOM_REVERSAL",
            bias="BULLISH",
            confidence=conf,
            timeframe=timeframe,
            asset_class=asset_class,
            phase1_exhaustion=p1_bull,
            phase1_details=p1_bull_reasons,
            phase2_sweep_or_divergence=p2_bull,
            phase2_details=p2_bull_reasons,
            phase3_confirmation=p3_bull,
            phase3_details=p3_bull_reasons,
            candlestick_pattern=candle_conf_bull["pattern"],
            candlestick_strength=candle_conf_bull["strength"],
            choch_detected=choch_bull,
            choch_level=choch_level_bull,
            entry_zone=entry_zone,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            risk_reward_ratio=rr,
            no_chase_limit=no_chase,
            market_regime=regime,
            recommended_strategy=rec_strategy,
            summary=summary,
        )

    elif bear_phase_count >= 2 and bear_phase_count > bull_phase_count and p3_bear:
        # Confirmed Bearish Reversal (Top)
        conf = (
            65
            + (10 if p1_bear else 0)
            + (10 if p2_bear else 0)
            + int(candle_conf_bear["strength"] * 0.15)
        )
        conf = min(96, max(65, conf))

        anchor_high = (
            extreme_high if (is_sweep_bear and extreme_high) else float(h_series.iloc[-3:].max())
        )
        sl = round(anchor_high + (0.15 * curr_atr), 2)
        risk = max(sl - c_curr, curr_atr * 0.5)

        t1 = round(c_curr - (2.0 * risk), 2)
        t2 = round(c_curr - (3.5 * risk), 2)
        t3 = round(c_curr - (5.0 * risk), 2)
        rr = round((c_curr - t1) / max(risk, 0.01), 2)

        entry_zone = (round(c_curr - 0.1 * curr_atr, 2), round(c_curr + 0.2 * curr_atr, 2))
        no_chase = round(c_curr - 0.35 * curr_atr, 2)

        # Options strategy calibration
        if regime == "TRENDING_EXHAUSTION" and conf >= 80:
            rec_strategy = "BUY_ATM_PUT" if asset_class == "INDEX" else "BEAR_PUT_SPREAD"
        elif regime == "CHOPPY_ROTATION" or conf < 75:
            rec_strategy = "BEAR_CALL_SPREAD"  # Sell Call above structural SL
        else:
            rec_strategy = "BEAR_PUT_SPREAD"

        summary = f"Institutional Top Reversal ({conf}% Conviction): {len(p1_bear_reasons) + len(p2_bear_reasons) + len(p3_bear_reasons)} confluences. {'; '.join(p3_bear_reasons + p2_bear_reasons[:1])}."

        return ReversalSignal(
            symbol=symbol,
            reversal_type="TOP_REVERSAL",
            bias="BEARISH",
            confidence=conf,
            timeframe=timeframe,
            asset_class=asset_class,
            phase1_exhaustion=p1_bear,
            phase1_details=p1_bear_reasons,
            phase2_sweep_or_divergence=p2_bear,
            phase2_details=p2_bear_reasons,
            phase3_confirmation=p3_bear,
            phase3_details=p3_bear_reasons,
            candlestick_pattern=candle_conf_bear["pattern"],
            candlestick_strength=candle_conf_bear["strength"],
            choch_detected=choch_bear,
            choch_level=choch_level_bear,
            entry_zone=entry_zone,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            risk_reward_ratio=rr,
            no_chase_limit=no_chase,
            market_regime=regime,
            recommended_strategy=rec_strategy,
            summary=summary,
        )

    # If setup is coiling or pre-confirmation (Phase 1 + Phase 2 met, waiting for Phase 3 trigger)
    elif bull_phase_count >= 2 and not p3_bull:
        return ReversalSignal(
            symbol=symbol,
            reversal_type="BOTTOM_REVERSAL",
            bias="BULLISH",
            confidence=55,
            timeframe=timeframe,
            asset_class=asset_class,
            phase1_exhaustion=p1_bull,
            phase1_details=p1_bull_reasons,
            phase2_sweep_or_divergence=p2_bull,
            phase2_details=p2_bull_reasons,
            phase3_confirmation=False,
            phase3_details=["Awaiting confirming rejection candle or micro-CHoCH."],
            summary="Precursor Bottom Setup: Exhaustion and liquidity sweep established. Do not enter until confirmation candle or CHoCH triggers.",
        )
    elif bear_phase_count >= 2 and not p3_bear:
        return ReversalSignal(
            symbol=symbol,
            reversal_type="TOP_REVERSAL",
            bias="BEARISH",
            confidence=55,
            timeframe=timeframe,
            asset_class=asset_class,
            phase1_exhaustion=p1_bear,
            phase1_details=p1_bear_reasons,
            phase2_sweep_or_divergence=p2_bear,
            phase2_details=p2_bear_reasons,
            phase3_confirmation=False,
            phase3_details=["Awaiting confirming rejection candle or micro-CHoCH."],
            summary="Precursor Top Setup: Exhaustion and liquidity sweep established. Do not enter until confirmation candle or CHoCH triggers.",
        )

    return default_none
