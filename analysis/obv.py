"""
analysis/obv.py
───────────────
Institutional On-Balance Volume (OBV) Engine & Multi-Timeframe Divergence Detector.
Implements Joseph Granville's On-Balance Volume, OBV-EMA Trend Bands, and
automated divergence/convergence detection across Intraday and Swing/Daily timeframes.

Core Quantitative Concepts:
  1. On-Balance Volume (OBV):
     OBV_t = OBV_{t-1} + Volume_t * sign(Close_t - Close_{t-1})
  2. OBV Trend Band:
     OBV_EMA = EMA(OBV, period)
     - Accumulation: OBV > OBV_EMA with positive slope
     - Distribution: OBV < OBV_EMA with negative slope
  3. Divergence Classification:
     - BULLISH_DIVERGENCE: Price near resistance / lower high while OBV makes New High.
       (Smart Money accumulating before price breakout).
     - BEARISH_DIVERGENCE: Price makes New High while OBV fails (Lower High).
       (Smart Money distributing into retail breakout buyers).
     - BULLISH_CONVERGENCE: Price HH + OBV HH (healthy sustained uptrend).
     - BEARISH_CONVERGENCE: Price LL + OBV LL (healthy sustained downtrend).
     - PIVOT_BREAKOUT: OBV breaking previous swing high before price.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.analysis.obv")


@dataclass
class OBVSnapshot:
    """Quantitative snapshot of OBV, trend regime, and divergence status."""

    symbol: str
    timeframe: str  # "INTRADAY" | "DAILY" | "SWING"
    current_obv: float
    obv_ema: float
    obv_slope_5bar: float
    regime: str  # "ACCUMULATION" | "DISTRIBUTION" | "NEUTRAL"
    divergence: str  # "BULLISH_DIVERGENCE" | "BEARISH_DIVERGENCE" | "BULLISH_CONVERGENCE" | "BEARISH_CONVERGENCE" | "NEUTRAL"
    is_pivot_breakout: bool
    conviction_modifier: int  # -25 to +25 score impact
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "current_obv": round(self.current_obv, 2),
            "obv_ema": round(self.obv_ema, 2),
            "obv_slope_5bar": round(self.obv_slope_5bar, 4),
            "regime": self.regime,
            "divergence": self.divergence,
            "is_pivot_breakout": self.is_pivot_breakout,
            "conviction_modifier": self.conviction_modifier,
            "summary": self.summary,
        }


def compute_obv_series(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    Vectorized computation of Granville's On-Balance Volume.
    Handles NaN, flat bars (close == prev_close), and zero volume safely.
    """
    if len(close) == 0 or len(volume) == 0:
        return pd.Series(dtype=float)

    price_diff = close.diff()
    direction = np.sign(price_diff).fillna(0.0)
    obv_deltas = direction * volume.fillna(0.0)
    obv = obv_deltas.cumsum()
    return obv


def _find_recent_pivots(
    series: pd.Series, lookback: int = 15
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Locates the most recent two swing peaks (highs) and two swing troughs (lows)
    within the lookback window.
    Returns: (peak_recent, peak_prior, trough_recent, trough_prior)
    """
    if len(series) < 6:
        return None, None, None, None

    window = series.iloc[-min(len(series), lookback + 10) :]
    vals = window.values

    peaks = []
    troughs = []

    # Simple 3-bar fractal pivot detection: vals[i-1] < vals[i] > vals[i+1]
    for i in range(1, len(vals) - 1):
        if vals[i] > vals[i - 1] and vals[i] >= vals[i + 1]:
            peaks.append(float(vals[i]))
        elif vals[i] < vals[i - 1] and vals[i] <= vals[i + 1]:
            troughs.append(float(vals[i]))

    peak_recent = peaks[-1] if len(peaks) >= 1 else None
    peak_prior = peaks[-2] if len(peaks) >= 2 else None
    trough_recent = troughs[-1] if len(troughs) >= 1 else None
    trough_prior = troughs[-2] if len(troughs) >= 2 else None

    return peak_recent, peak_prior, trough_recent, trough_prior


def analyse_obv(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    is_intraday: bool = False,
    ema_period: Optional[int] = None,
    lookback_bars: Optional[int] = None,
) -> OBVSnapshot:
    """
    Evaluates On-Balance Volume dynamics and divergences.
    Tuned and calibrated based on Intraday vs Daily/Swing timeframes:
      - Intraday (e.g. 1m, 3m, 5m, 15m):
          Fast responsive smoothing (EMA-10 or EMA-14), tighter pivot lookback (12-15 bars).
      - Daily / Swing (e.g. EOD, weekly, multi-day F&O):
          Standard Granville smoothing (EMA-20), deeper pivot lookback (20-30 bars).
    """
    if df is None or len(df) < 5:
        return OBVSnapshot(
            symbol=symbol,
            timeframe="INTRADAY" if is_intraday else "DAILY",
            current_obv=0.0,
            obv_ema=0.0,
            obv_slope_5bar=0.0,
            regime="NEUTRAL",
            divergence="NEUTRAL",
            is_pivot_breakout=False,
            conviction_modifier=0,
            summary="Insufficient data for OBV computation (<5 bars).",
        )

    # Standardize column naming
    close_col = (
        "close" if "close" in df.columns else ("Close" if "Close" in df.columns else df.columns[3])
    )
    vol_col = (
        "volume"
        if "volume" in df.columns
        else ("Volume" if "Volume" in df.columns else df.columns[4])
    )

    close = df[close_col].astype(float)
    vol = df[vol_col].astype(float)

    # Check for cash index zero-volume condition (Dalal Street spot indices carry 0 native volume)
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    is_index = clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")

    if (vol.sum() == 0 or vol.max() == 0) and is_index:
        try:
            from market.history import get_ohlcv

            fut_df = get_ohlcv(
                symbol=f"{clean_sym}",
                exchange="NFO",
                interval="5m" if is_intraday else "day",
                days=30,
            )
            if (
                fut_df is not None
                and not fut_df.empty
                and ("volume" in fut_df.columns or "Volume" in fut_df.columns)
            ):
                v_col = "volume" if "volume" in fut_df.columns else "Volume"
                if fut_df[v_col].sum() > 0:
                    aligned_vol = fut_df[v_col].reindex(df.index, method="nearest")
                    if aligned_vol.notna().any() and aligned_vol.sum() > 0:
                        vol = aligned_vol.fillna(0.0).astype(float)
        except Exception as e_suppressed:
            logger.debug(
                f"[analysis.obv] Futures volume mapping for index {clean_sym} not available: {e_suppressed}"
            )

    if vol.sum() == 0 or vol.max() == 0:
        return OBVSnapshot(
            symbol=symbol,
            timeframe="INTRADAY" if is_intraday else "DAILY",
            current_obv=0.0,
            obv_ema=0.0,
            obv_slope_5bar=0.0,
            regime="NEUTRAL",
            divergence="NEUTRAL",
            is_pivot_breakout=False,
            conviction_modifier=0,
            summary=f"Zero traded volume for {symbol} (Cash index requires active futures volume proxy for OBV).",
        )

    obv = compute_obv_series(close, vol)
    if obv.empty or len(obv) < 2:
        return OBVSnapshot(
            symbol=symbol,
            timeframe="INTRADAY" if is_intraday else "DAILY",
            current_obv=0.0,
            obv_ema=0.0,
            obv_slope_5bar=0.0,
            regime="NEUTRAL",
            divergence="NEUTRAL",
            is_pivot_breakout=False,
            conviction_modifier=0,
            summary="Empty OBV series.",
        )

    # Adaptive parameters for Intraday vs Daily
    if is_intraday:
        ema_p = ema_period or 10
        lookback = lookback_bars or 15
        timeframe_label = "INTRADAY"
    else:
        ema_p = ema_period or 20
        lookback = lookback_bars or 25
        timeframe_label = "DAILY"

    # OBV EMA Band
    obv_ema_series = obv.ewm(span=ema_p, adjust=False).mean()
    curr_obv = float(obv.iloc[-1])
    curr_obv_ema = float(obv_ema_series.iloc[-1])

    # 5-bar OBV normalized slope (relative to recent volatility)
    if len(obv) >= 6:
        prior_obv = float(obv.iloc[-5])
        obv_std = float(obv.iloc[-ema_p:].std()) if len(obv) >= ema_p else 1.0
        obv_slope_5bar = (curr_obv - prior_obv) / max(1.0, obv_std)
    else:
        obv_slope_5bar = 0.0

    # Trend Regime
    if curr_obv > curr_obv_ema and obv_slope_5bar >= 0.0:
        regime = "ACCUMULATION"
    elif curr_obv < curr_obv_ema and obv_slope_5bar <= 0.0:
        regime = "DISTRIBUTION"
    else:
        regime = "NEUTRAL"

    # Check for OBV Pivot Breakout:
    # Current OBV is higher than the max OBV in the prior lookback window
    window_obv_prior = obv.iloc[-lookback - 1 : -1] if len(obv) > lookback else obv.iloc[:-1]
    window_close_prior = (
        close.iloc[-lookback - 1 : -1] if len(close) > lookback else close.iloc[:-1]
    )

    prior_obv_high = float(window_obv_prior.max()) if not window_obv_prior.empty else curr_obv
    prior_close_high = (
        float(window_close_prior.max()) if not window_close_prior.empty else float(close.iloc[-1])
    )
    curr_close = float(close.iloc[-1])

    is_obv_new_high = curr_obv >= prior_obv_high
    is_close_new_high = curr_close > prior_close_high

    is_pivot_breakout = is_obv_new_high and (
        not is_close_new_high or (curr_close >= prior_close_high * 0.995)
    )

    # Detect Divergences using local swing peaks & troughs
    price_pk_rec, price_pk_prior, price_tr_rec, price_tr_prior = _find_recent_pivots(
        close, lookback=lookback
    )
    obv_pk_rec, obv_pk_prior, obv_tr_rec, obv_tr_prior = _find_recent_pivots(obv, lookback=lookback)

    divergence = "NEUTRAL"
    conviction_mod = 0
    summary_parts = []

    # 1. Bullish Divergence (Leading Accumulation):
    # Price makes lower high or equal resistance, while OBV makes higher high
    if (is_obv_new_high and curr_close < prior_close_high) or (
        price_pk_rec is not None
        and price_pk_prior is not None
        and obv_pk_rec is not None
        and obv_pk_prior is not None
        and price_pk_rec <= price_pk_prior * 1.002
        and obv_pk_rec > obv_pk_prior
    ):
        divergence = "BULLISH_DIVERGENCE"
        conviction_mod = 20
        summary_parts.append(
            "Bullish OBV Divergence: Institutional volume accumulating before price breakout"
        )

    # 2. Bearish Divergence (Distribution Trap):
    # Price makes higher high, but OBV makes lower high (drying volume / passive selling)
    elif (is_close_new_high and curr_obv < prior_obv_high) or (
        price_pk_rec is not None
        and price_pk_prior is not None
        and obv_pk_rec is not None
        and obv_pk_prior is not None
        and price_pk_rec > price_pk_prior
        and obv_pk_rec < obv_pk_prior
    ):
        divergence = "BEARISH_DIVERGENCE"
        conviction_mod = -20
        summary_parts.append(
            "Bearish OBV Divergence: Price making new high on declining volume (Distribution Trap)"
        )

    # 3. Bullish Convergence (Healthy Uptrend):
    elif is_close_new_high and is_obv_new_high:
        divergence = "BULLISH_CONVERGENCE"
        conviction_mod = 10
        summary_parts.append(
            "Bullish OBV Convergence: Price and OBV both breaking out (Healthy Uptrend)"
        )

    # 4. Bearish Convergence (Healthy Downtrend):
    elif curr_close < float(
        window_close_prior.min() if not window_close_prior.empty else curr_close
    ) and (curr_obv < float(window_obv_prior.min() if not window_obv_prior.empty else curr_obv)):
        divergence = "BEARISH_CONVERGENCE"
        conviction_mod = -10
        summary_parts.append(
            "Bearish OBV Convergence: Heavy volume accompanying lower prices (Selling Dominance)"
        )

    if is_pivot_breakout and divergence != "BEARISH_DIVERGENCE":
        if conviction_mod < 15:
            conviction_mod = 15
        summary_parts.append(
            "OBV broke previous swing high pivot (Smart money participation confirmed)"
        )

    if regime == "ACCUMULATION" and conviction_mod >= 0:
        conviction_mod = min(25, conviction_mod + 5)
    elif regime == "DISTRIBUTION" and conviction_mod <= 0:
        conviction_mod = max(-25, conviction_mod - 5)

    summary = (
        "; ".join(summary_parts) if summary_parts else f"OBV in {regime} regime ({timeframe_label})"
    )

    return OBVSnapshot(
        symbol=symbol,
        timeframe=timeframe_label,
        current_obv=curr_obv,
        obv_ema=curr_obv_ema,
        obv_slope_5bar=obv_slope_5bar,
        regime=regime,
        divergence=divergence,
        is_pivot_breakout=is_pivot_breakout,
        conviction_modifier=conviction_mod,
        summary=summary,
    )
