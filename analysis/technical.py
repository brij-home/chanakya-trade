"""
analysis/technical.py
─────────────────────
Technical indicators computed on OHLCV pandas DataFrames.
Pure numpy/pandas — no external TA library dependency.

All functions accept a DataFrame with columns:
    open, high, low, close, volume  (index = datetime)

Main entry point: analyse(symbol) → TechnicalSnapshot
"""

from __future__ import annotations
import logging

logger = logging.getLogger("analysis.technical")


from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from market.history import get_ohlcv


# ── Result dataclass ─────────────────────────────────────────


@dataclass
class Signal:
    name: str
    value: float | str
    verdict: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    detail: str = ""


@dataclass
class TechnicalSnapshot:
    symbol: str
    ltp: float

    # Indicators
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_sig: Optional[float] = None
    macd_hist: Optional[float] = None
    macd_signal: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    macd_detail: str = ""  # e.g. "Bullish crossover", "Above signal line"
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    sma200: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    atr: Optional[float] = None
    volume_ratio: Optional[float] = None  # today's vol / 20-day avg vol
    roc: Optional[float] = None  # Rate of Change (12-period %)
    chop_index: Optional[float] = None  # Choppiness Index (0-100)

    # Timeframe & Provenance
    timeframe: str = "1D (Daily)"
    as_of: str = ""
    data_source: str = "NSE Historical EOD"
    is_valid: bool = True
    anomaly_notes: list[str] = field(default_factory=list)

    # Support / Resistance
    support: float = 0.0
    resistance: float = 0.0
    pivot: float = 0.0

    # Signals list
    signals: list[Signal] = field(default_factory=list)

    # Overall verdict
    verdict: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    score: int = 0  # -100 to +100
    summary: str = ""

    # OBV & Triple-Filtered DMI Indicators (Swingscape Advancements)
    obv: Optional[float] = None
    obv_ema: Optional[float] = None
    obv_regime: str = "NEUTRAL"  # ACCUMULATION | DISTRIBUTION | NEUTRAL
    obv_divergence: str = "NEUTRAL"  # BULLISH_DIVERGENCE | BEARISH_DIVERGENCE | BULLISH_CONVERGENCE | BEARISH_CONVERGENCE | NEUTRAL
    dmi_plus: Optional[float] = None
    dmi_minus: Optional[float] = None
    adx: Optional[float] = None
    adx_slope: Optional[float] = None
    dmi_triple_verdict: str = (
        "NEUTRAL"  # TRIPLE_BULLISH_CONFIRMED | TRIPLE_BEARISH_CONFIRMED | WEAK_OR_CHOPPY | NEUTRAL
    )
    roc_normalized: Optional[float] = None  # Volatility-normalized ROC (z-score)
    roc_acceleration: Optional[float] = None  # 2nd derivative of momentum (delta ROC)


# ── Core indicators ──────────────────────────────────────────


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))

    zero_loss = (avg_loss == 0) & (avg_gain > 0)
    zero_gain = (avg_gain == 0) & (avg_loss > 0)
    flat = (avg_gain == 0) & (avg_loss == 0)

    rsi_series = rsi_series.where(~zero_loss, 100.0)
    rsi_series = rsi_series.where(~zero_gain, 0.0)
    rsi_series = rsi_series.where(~flat, 50.0)
    return rsi_series


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_span: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_span)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_k: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, mid, lower)."""
    mid = sma(close, period)
    std = close.rolling(window=period).std()
    upper = mid + std_k * std
    lower = mid - std_k * std
    return upper, mid, lower


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = (
        df["high"]
        if "high" in df.columns
        else (df["High"] if "High" in df.columns else df.iloc[:, 1])
    )
    l = df["low"] if "low" in df.columns else (df["Low"] if "Low" in df.columns else df.iloc[:, 2])
    c = (
        df["close"]
        if "close" in df.columns
        else (df["Close"] if "Close" in df.columns else df.iloc[:, 3])
    )
    high_low = h - l
    high_close = (h - c.shift()).abs()
    low_close = (l - c.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def pivot_points(df: pd.DataFrame) -> dict[str, float]:
    """
    Classic floor pivot points from the last completed candle.
    Returns: pivot, r1, r2, r3, s1, s2, s3
    """
    prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    h, l, c = prev["high"], prev["low"], prev["close"]
    pivot = (h + l + c) / 3
    return {
        "pivot": round(pivot, 2),
        "r1": round(2 * pivot - l, 2),
        "r2": round(pivot + (h - l), 2),
        "r3": round(h + 2 * (pivot - l), 2),
        "s1": round(2 * pivot - h, 2),
        "s2": round(pivot - (h - l), 2),
        "s3": round(l - 2 * (h - pivot), 2),
    }


def roc(series: pd.Series, period: int = 12) -> pd.Series:
    """
    Rate of Change (ROC): Percentage price change over N periods.
    Formula: ((Price_t - Price_{t-n}) / Price_{t-n}) * 100
    """
    shifted = series.shift(period)
    return ((series - shifted) / shifted.replace(0, np.nan)) * 100.0


def normalized_roc(series: pd.Series, atr_series: pd.Series, period: int = 12) -> pd.Series:
    """
    Volatility-normalized Rate of Change.
    Measures price velocity relative to expected price volatility:
    Formula: ROC / ((ATR / Close) * 100 * sqrt(period / 12))
    Values > +1.8 = Exceptional bullish velocity; < -1.8 = Exceptional bearish velocity.
    """
    raw_roc = roc(series, period=period)
    atr_pct = (atr_series / series.replace(0, np.nan)) * 100.0
    scale = (atr_pct * np.sqrt(period / 12.0)).replace(0, np.nan)
    return (raw_roc / scale).fillna(0.0)


def roc_acceleration(series: pd.Series, period: int = 12) -> pd.Series:
    """
    2nd derivative of price momentum: rate of change of ROC (delta ROC).
    Detects momentum exhaustion and explosive gamma expansion before price peaks.
    """
    roc_s = roc(series, period=period)
    return roc_s.diff().fillna(0.0)


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Dreiss Choppiness Index (0 to 100).
    Values > 61.8 indicate a choppy, sideways, consolidative market (breakout risk).
    Values < 38.2 indicate a strong directional trend (trending market).
    Formula: 100 * LOG10( SUM(TrueRange, n) / (MaxHigh_n - MinLow_n) ) / LOG10(n)
    """
    h = (
        df["high"]
        if "high" in df.columns
        else (df["High"] if "High" in df.columns else df.iloc[:, 1])
    )
    l = df["low"] if "low" in df.columns else (df["Low"] if "Low" in df.columns else df.iloc[:, 2])
    c = (
        df["close"]
        if "close" in df.columns
        else (df["Close"] if "Close" in df.columns else df.iloc[:, 3])
    )
    high_low = h - l
    high_close = (h - c.shift()).abs()
    low_close = (l - c.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    atr_sum = true_range.rolling(window=period).sum()
    highest_h = h.rolling(window=period).max()
    lowest_l = l.rolling(window=period).min()
    price_range = (highest_h - lowest_l).replace(0, np.nan)

    ratio = (atr_sum / price_range).replace(0, np.nan)
    chop = 100.0 * (np.log10(ratio) / np.log10(period))
    return chop.clip(lower=0.0, upper=100.0)


def relative_strength(stock_close: pd.Series, benchmark_close: pd.Series) -> pd.Series:
    """
    Relative Strength (RS) ratio of stock vs benchmark index (e.g. NIFTY 50).
    Rising RS indicates stock outperforming the benchmark.
    """
    aligned_stock, aligned_bench = stock_close.align(benchmark_close, join="inner")
    return (aligned_stock / aligned_bench.replace(0, np.nan)) * 100.0


# ── Main analyser ────────────────────────────────────────────


def analyse(
    symbol: str,
    exchange: str = "NSE",
    days: int = 365,
    df: Optional[pd.DataFrame] = None,
    is_intraday: bool = False,
) -> TechnicalSnapshot:
    """
    Full technical analysis for a symbol.

    Fetches OHLCV, computes all indicators, generates signals,
    and returns a TechnicalSnapshot with a score and verdict.

    Score:  +10 per bullish signal, -10 per bearish signal.
    Verdict:
        score > 30  → BULLISH
        score < -30 → BEARISH
        else        → NEUTRAL
    """
    # ── Fetch data ────────────────────────────────────────────
    if df is None:
        try:
            df = get_ohlcv(symbol=symbol, exchange=exchange, days=days)
        except Exception:
            df = pd.DataFrame()

    if (df.empty or len(df) < 30) and exchange.upper() == "NSE":
        # Cross-exchange fallback: if symbol is listed exclusively on BSE
        try:
            bse_df = get_ohlcv(symbol=symbol, exchange="BSE", days=days)
            if not bse_df.empty and len(bse_df) >= 30:
                df = bse_df
                exchange = "BSE"
        except Exception as e_suppressed:
            logger.debug(f"[analysis.technical] Non-fatal exception suppressed: {e_suppressed}")

    if df.empty or len(df) < 30:
        return TechnicalSnapshot(
            symbol=symbol,
            ltp=0.0,
            rsi=None,
            macd=None,
            macd_sig=None,
            macd_hist=None,
            verdict="INSUFFICIENT DATA",
            summary=f"Insufficient historical bars for {exchange}:{symbol} (minimum 30 required).",
            is_valid=False,
        )

    close = df["close"]
    ltp = float(close.iloc[-1])

    # ── Compute indicators ────────────────────────────────────
    from analysis.obv import analyse_obv
    from analysis.dmi_filter import evaluate_triple_dmi

    obv_snap = analyse_obv(df, symbol=symbol, is_intraday=is_intraday)
    dmi_res = evaluate_triple_dmi(df, symbol=symbol, is_intraday=is_intraday)
    rsi_series = rsi(close)
    rsi_val = float(rsi_series.iloc[-1])

    macd_line, sig_line, histogram = macd(close)
    macd_val = float(macd_line.iloc[-1])
    sig_val = float(sig_line.iloc[-1])
    hist_val = float(histogram.iloc[-1])

    ema20_val = float(ema(close, 20).iloc[-1])
    ema50_val = float(ema(close, 50).iloc[-1])
    sma200_val = (
        float(sma(close, 200).iloc[-1]) if len(df) >= 200 else float(sma(close, len(df)).iloc[-1])
    )

    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    bb_u = float(bb_upper.iloc[-1])
    bb_m = float(bb_mid.iloc[-1])
    bb_l = float(bb_lower.iloc[-1])

    roc_series = roc(close, 12)
    roc_val = float(roc_series.iloc[-1]) if not pd.isna(roc_series.iloc[-1]) else 0.0

    atr_series = atr(df)
    atr_val = float(atr_series.iloc[-1])

    norm_roc_series = normalized_roc(close, atr_series, 12)
    norm_roc_val = float(norm_roc_series.iloc[-1]) if not pd.isna(norm_roc_series.iloc[-1]) else 0.0

    roc_acc_series = roc_acceleration(close, 12)
    roc_acc_val = float(roc_acc_series.iloc[-1]) if not pd.isna(roc_acc_series.iloc[-1]) else 0.0

    chop_series = choppiness_index(df, 14)
    chop_val = float(chop_series.iloc[-1]) if not pd.isna(chop_series.iloc[-1]) else 50.0

    vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_today = float(df["volume"].iloc[-1])
    vol_ratio = round(vol_today / vol_avg, 2) if vol_avg else 1.0

    pivots = pivot_points(df)

    # ── Build signals ─────────────────────────────────────────
    signals: list[Signal] = []
    score = 0

    # Volatility-Normalized Rate of Change (ROC-12) & Momentum Acceleration
    if norm_roc_val > 1.8:
        signals.append(
            Signal(
                "ROC",
                f"{roc_val:+.1f}% ({norm_roc_val:+.1f}σ)",
                "BULLISH",
                "Strong volatility-expanded upward momentum velocity (>+1.8σ)",
            )
        )
        score += 8
    elif norm_roc_val < -1.8:
        signals.append(
            Signal(
                "ROC",
                f"{roc_val:+.1f}% ({norm_roc_val:+.1f}σ)",
                "BEARISH",
                "Strong volatility-expanded downward momentum velocity (<-1.8σ)",
            )
        )
        score -= 8
    elif roc_val > 4.0:
        signals.append(
            Signal("ROC", f"{roc_val:+.1f}%", "BULLISH", "Positive momentum velocity (>+4%)")
        )
        score += 5
    elif roc_val < -4.0:
        signals.append(
            Signal("ROC", f"{roc_val:+.1f}%", "BEARISH", "Negative momentum velocity (<-4%)")
        )
        score -= 5
    else:
        signals.append(Signal("ROC", f"{roc_val:+.1f}%", "NEUTRAL", "Moderate momentum velocity"))

    # Choppiness Index (Regime: Trending vs Choppy)
    if chop_val > 61.8:
        signals.append(
            Signal(
                "ChoppinessIndex",
                round(chop_val, 1),
                "NEUTRAL",
                "High chop / rangebound consolidation (>61.8) — avoid breakout chasing",
            )
        )
    elif chop_val < 38.2:
        chop_dir = "BULLISH" if ltp > ema20_val else "BEARISH"
        signals.append(
            Signal(
                "ChoppinessIndex",
                round(chop_val, 1),
                chop_dir,
                f"Strong directional expansion trend (<38.2) aligned with {chop_dir}",
            )
        )
        score += 5 if chop_dir == "BULLISH" else -5
    else:
        signals.append(
            Signal(
                "ChoppinessIndex",
                round(chop_val, 1),
                "NEUTRAL",
                "Transitional volatility regime (38.2–61.8)",
            )
        )

    # Trend-Adaptive RSI Evaluation (Cardwell/Brown Institutional Range Rules)
    is_bull_trend = (ltp > ema50_val) and (ema20_val >= ema50_val)
    is_bear_trend = (ltp < ema50_val) and (ema20_val <= ema50_val)

    if is_bull_trend:
        if 60.0 <= rsi_val <= 75.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BULLISH",
                    "Strong Bullish Momentum Range (60-75) in established uptrend",
                )
            )
            score += 15
        elif rsi_val > 75.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "NEUTRAL",
                    "Bullish Overextension (>75) — trail stops, avoid late chase",
                )
            )
            score += 5
        elif 40.0 <= rsi_val < 60.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BULLISH",
                    "Bull Market Support Zone (40-60) — healthy pullback area",
                )
            )
            score += 10
        else:  # rsi_val < 40
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BEARISH",
                    "Momentum Breakdown below Bull Support (<40)",
                )
            )
            score -= 10
    elif is_bear_trend:
        if 25.0 <= rsi_val <= 40.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BEARISH",
                    "Strong Bearish Momentum Range (25-40) in established downtrend",
                )
            )
            score -= 15
        elif rsi_val < 25.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "NEUTRAL",
                    "Extreme Capitulation Oversold (<25) — short covering risk",
                )
            )
            score -= 5
        elif 40.0 < rsi_val <= 60.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BEARISH",
                    "Bear Market Resistance Ceiling (40-60) — supply bounce zone",
                )
            )
            score -= 10
        else:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BULLISH",
                    "Momentum Breakout above Bear Resistance (>60)",
                )
            )
            score += 10
    else:  # Range-bound / Mean-reverting regime
        if rsi_val < 30.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BULLISH",
                    "Range Support Oversold (<30) — mean-reversion long",
                )
            )
            score += 15
        elif rsi_val > 70.0:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "BEARISH",
                    "Range Resistance Overbought (>70) — mean-reversion short",
                )
            )
            score -= 15
        else:
            signals.append(
                Signal(
                    "RSI",
                    round(rsi_val, 1),
                    "NEUTRAL",
                    "Bullish zone (50-70)" if rsi_val > 50 else "Bearish zone (30-50)",
                )
            )
            score += 5 if rsi_val > 50 else -5

    # MACD crossover & positioning
    prev_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 else 0
    if hist_val > 0 and prev_hist <= 0:
        macd_detail = "Bullish crossover"
        macd_signal_str = "BULLISH"
        signals.append(Signal("MACD", round(macd_val, 2), "BULLISH", "Bullish crossover"))
        score += 15
    elif hist_val < 0 and prev_hist >= 0:
        macd_detail = "Bearish crossover"
        macd_signal_str = "BEARISH"
        signals.append(Signal("MACD", round(macd_val, 2), "BEARISH", "Bearish crossover"))
        score -= 15
    elif hist_val > 0:
        macd_detail = "Above signal line"
        macd_signal_str = "BULLISH"
        signals.append(Signal("MACD", round(macd_val, 2), "BULLISH", "Above signal line"))
        score += 8
    else:
        macd_detail = "Below signal line"
        macd_signal_str = "BEARISH"
        signals.append(Signal("MACD", round(macd_val, 2), "BEARISH", "Below signal line"))
        score -= 8

    # Price vs MAs
    if ltp > ema20_val:
        signals.append(Signal("EMA20", round(ema20_val, 2), "BULLISH", "Price above EMA20"))
        score += 8
    else:
        signals.append(Signal("EMA20", round(ema20_val, 2), "BEARISH", "Price below EMA20"))
        score -= 8

    if ltp > ema50_val:
        signals.append(Signal("EMA50", round(ema50_val, 2), "BULLISH", "Price above EMA50"))
        score += 8
    else:
        signals.append(Signal("EMA50", round(ema50_val, 2), "BEARISH", "Price below EMA50"))
        score -= 8

    if ltp > sma200_val:
        signals.append(Signal("SMA200", round(sma200_val, 2), "BULLISH", "Price above 200 DMA"))
        score += 10
    else:
        signals.append(Signal("SMA200", round(sma200_val, 2), "BEARISH", "Price below 200 DMA"))
        score -= 10

    # Bollinger Bands
    if ltp < bb_l:
        signals.append(
            Signal(
                "BollingerBands",
                round(ltp, 2),
                "BULLISH",
                "Price below lower band — potential reversal",
            )
        )
        score += 10
    elif ltp > bb_u:
        signals.append(
            Signal(
                "BollingerBands",
                round(ltp, 2),
                "BEARISH",
                "Price above upper band — potential reversal",
            )
        )
        score -= 10
    else:
        bb_pos = (ltp - bb_l) / (bb_u - bb_l) if (bb_u - bb_l) else 0.5
        signals.append(
            Signal(
                "BollingerBands",
                f"{bb_pos:.0%} of band",
                "NEUTRAL",
                f"Upper={bb_u:.2f} Mid={bb_m:.2f} Lower={bb_l:.2f}",
            )
        )

    # Volume confirmation
    if vol_ratio > 1.5:
        dir_signal = "BULLISH" if ltp >= float(df["open"].iloc[-1]) else "BEARISH"
        signals.append(
            Signal(
                "Volume",
                f"{vol_ratio:.1f}x avg",
                dir_signal,
                f"High volume day ({vol_ratio:.1f}× 20-day avg)",
            )
        )
        score += 8 if dir_signal == "BULLISH" else -8
    else:
        signals.append(Signal("Volume", f"{vol_ratio:.1f}x avg", "NEUTRAL", "Normal volume"))

    # OBV Signals (Accumulation/Distribution & Divergences)
    if obv_snap.divergence == "BULLISH_DIVERGENCE":
        signals.append(Signal("OBV", "Bullish Divergence", "BULLISH", obv_snap.summary))
        score += 15
    elif obv_snap.divergence == "BEARISH_DIVERGENCE":
        signals.append(Signal("OBV", "Bearish Divergence", "BEARISH", obv_snap.summary))
        score -= 15
    elif obv_snap.divergence == "BULLISH_CONVERGENCE":
        signals.append(Signal("OBV", "Bullish Convergence", "BULLISH", obv_snap.summary))
        score += 8
    elif obv_snap.divergence == "BEARISH_CONVERGENCE":
        signals.append(Signal("OBV", "Bearish Convergence", "BEARISH", obv_snap.summary))
        score -= 8
    elif obv_snap.regime == "ACCUMULATION":
        signals.append(Signal("OBV", "Accumulation", "BULLISH", "OBV above 20-EMA"))
        score += 5
    elif obv_snap.regime == "DISTRIBUTION":
        signals.append(Signal("OBV", "Distribution", "BEARISH", "OBV below 20-EMA"))
        score -= 5

    # Triple-Filtered DMI Signals (Swingscape 3-Tier Filter)
    if dmi_res.verdict == "TRIPLE_BULLISH_CONFIRMED":
        signals.append(
            Signal(
                "TripleDMI",
                f"+DI {dmi_res.plus_di:.1f} >= {dmi_res.threshold}",
                "BULLISH",
                dmi_res.summary,
            )
        )
        score += 15
    elif dmi_res.verdict == "TRIPLE_BEARISH_CONFIRMED":
        signals.append(
            Signal(
                "TripleDMI",
                f"-DI {dmi_res.minus_di:.1f} >= {dmi_res.threshold}",
                "BEARISH",
                dmi_res.summary,
            )
        )
        score -= 15
    elif dmi_res.verdict == "WEAK_OR_CHOPPY":
        signals.append(
            Signal("TripleDMI", f"Chop (<{dmi_res.threshold})", "NEUTRAL", dmi_res.summary)
        )

    # ── Verdict ───────────────────────────────────────────────
    score = max(-100, min(100, score))
    verdict = "BULLISH" if score > 30 else "BEARISH" if score < -30 else "NEUTRAL"

    bullish_count = sum(1 for s in signals if s.verdict == "BULLISH")
    bearish_count = sum(1 for s in signals if s.verdict == "BEARISH")
    summary = (
        f"{bullish_count} bullish / {bearish_count} bearish signals | "
        f"Score: {score:+d} | RSI {rsi_val:.1f} | "
        f"{'Above' if ltp > sma200_val else 'Below'} 200 DMA"
    )

    as_of_str = (
        str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])[:10]
    )
    data_source_str = df.attrs.get("provenance", {}).get("provider", "NSE Historical EOD")
    anomaly_notes = []
    is_valid = True
    if rsi_val >= 95.0 or rsi_val <= 5.0:
        anomaly_notes.append(f"Extreme RSI ({rsi_val:.1f}) detected - verify price continuity")
        is_valid = False

    return TechnicalSnapshot(
        symbol=symbol,
        ltp=round(ltp, 2),
        rsi=round(rsi_val, 2),
        macd=round(macd_val, 4),
        macd_sig=round(sig_val, 4),
        macd_hist=round(hist_val, 4),
        macd_signal=macd_signal_str,
        macd_detail=macd_detail,
        ema20=round(ema20_val, 2),
        ema50=round(ema50_val, 2),
        sma200=round(sma200_val, 2),
        bb_upper=round(bb_u, 2),
        bb_lower=round(bb_l, 2),
        bb_mid=round(bb_m, 2),
        atr=round(atr_val, 2),
        volume_ratio=vol_ratio,
        roc=round(roc_val, 2),
        chop_index=round(chop_val, 2),
        timeframe="1D (Daily)",
        as_of=as_of_str,
        data_source=data_source_str,
        is_valid=is_valid,
        anomaly_notes=anomaly_notes,
        support=pivots["s1"],
        resistance=pivots["r1"],
        pivot=pivots["pivot"],
        signals=signals,
        verdict=verdict,
        score=score,
        summary=summary,
        obv=round(obv_snap.current_obv, 2),
        obv_ema=round(obv_snap.obv_ema, 2),
        obv_regime=obv_snap.regime,
        obv_divergence=obv_snap.divergence,
        dmi_plus=round(dmi_res.plus_di, 2),
        dmi_minus=round(dmi_res.minus_di, 2),
        adx=round(dmi_res.adx, 2),
        adx_slope=round(getattr(dmi_res, "adx_slope_3bar", 0.0), 2),
        dmi_triple_verdict=dmi_res.verdict,
        roc_normalized=round(norm_roc_val, 2),
        roc_acceleration=round(roc_acc_val, 2),
    )
