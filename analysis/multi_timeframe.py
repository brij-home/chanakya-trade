"""
analysis/multi_timeframe.py
───────────────────────────
Multi-timeframe analysis — check daily + hourly confluence.

A signal is stronger when both timeframes agree:
  - Daily RSI oversold + Hourly MACD bullish crossover = strong buy
  - Daily bearish + Hourly bearish = confirmed downtrend
  - Daily bullish + Hourly bearish = wait for hourly to align

Usage:
    from analysis.multi_timeframe import multi_timeframe_analysis

    result = multi_timeframe_analysis("RELIANCE")
    result.print_analysis()
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class TimeframeSignal:
    """Signal from a single timeframe."""

    timeframe: str  # "15m" / "1h" / "1D" / "Weekly"
    verdict: str  # BULLISH / BEARISH / NEUTRAL
    score: float
    rsi: float = 0.0
    macd_signal: str = ""  # "BULLISH_CROSS" / "BEARISH_CROSS" / "NEUTRAL"
    ema_trend: str = ""  # "ABOVE" (EMA20 > EMA50) / "BELOW"
    key_points: list[str] = field(default_factory=list)
    signal_name: str = ""
    key_level: str = ""
    ema20: float = 0.0


@dataclass
class MultiTimeframeResult:
    """Result of multi-timeframe analysis."""

    symbol: str
    signals: list[TimeframeSignal]
    confluence: str  # "STRONG_BUY" / "BUY" / "NEUTRAL" / "SELL" / "STRONG_SELL"
    confluence_score: float
    alignment: str  # "ALIGNED" / "CONFLICTING" / "MIXED"
    recommendation: str

    def to_dict(self) -> dict:
        stance_str = (
            "HIGH ALIGNMENT (STRONG LONG)"
            if self.confluence in ("STRONG_BUY", "BUY") and self.alignment == "ALIGNED"
            else (
                "HIGH ALIGNMENT (STRONG SHORT)"
                if self.confluence in ("STRONG_SELL", "SELL") and self.alignment == "ALIGNED"
                else (
                    "MODERATE ALIGNMENT (STALK)"
                    if self.alignment == "ALIGNED"
                    else "MIXED SIGNALS (STAND DOWN)"
                )
            )
        )
        conf_pct = int(min(98, max(20, int(self.confluence_score + 50))))
        tf_items = []
        for s in self.signals:
            tf_tag = (
                "15m"
                if s.timeframe in ("15m", "15minute")
                else (
                    "1h"
                    if s.timeframe in ("Hourly", "60minute", "1h")
                    else ("1D" if s.timeframe in ("Daily", "day", "1D") else s.timeframe)
                )
            )
            label_tag = (
                "Intraday Execution"
                if tf_tag == "15m"
                else (
                    "Swing Structure"
                    if tf_tag == "1h"
                    else ("Institutional Trend" if tf_tag == "1D" else f"{s.timeframe} Trend")
                )
            )
            tf_items.append(
                {
                    "tf": tf_tag,
                    "label": label_tag,
                    "bias": s.verdict,
                    "signal": s.signal_name or f"{s.verdict} Momentum",
                    "rsi": round(s.rsi, 1) if s.rsi > 0 else None,
                    "key_level": s.key_level or (f"EMA20 ₹{s.ema20:.1f}" if s.ema20 > 0 else "—"),
                }
            )
        return {
            "symbol": self.symbol,
            "confluence_score": conf_pct,
            "stance": stance_str,
            "timeframes": tf_items,
            "alignment": self.alignment,
            "recommendation": self.recommendation,
        }

    def print_analysis(self) -> None:
        table = Table(title=f"Multi-Timeframe: {self.symbol}", show_lines=True)
        table.add_column("Timeframe", style="bold", width=10)
        table.add_column("Verdict", width=10)
        table.add_column("Score", justify="right", width=8)
        table.add_column("RSI", justify="right", width=6)
        table.add_column("MACD", width=14)
        table.add_column("EMA Trend", width=10)

        for s in self.signals:
            v_style = {"BULLISH": "green", "BEARISH": "red"}.get(s.verdict, "yellow")
            table.add_row(
                s.timeframe,
                f"[{v_style}]{s.verdict}[/{v_style}]",
                f"{s.score:+.0f}",
                f"{s.rsi:.0f}",
                s.macd_signal,
                s.ema_trend,
            )

        console.print(table)

        conf_style = (
            "green"
            if "BUY" in self.confluence
            else "red"
            if "SELL" in self.confluence
            else "yellow"
        )
        console.print(
            f"\n  Confluence : [{conf_style}]{self.confluence}[/{conf_style}] "
            f"(score: {self.confluence_score:+.1f})"
        )
        console.print(f"  Alignment  : {self.alignment}")
        console.print(f"  Action     : {self.recommendation}\n")


def multi_timeframe_analysis(
    symbol: str,
    exchange: str = "NSE",
) -> MultiTimeframeResult:
    """
    Run technical analysis on multiple timeframes (15m, 1h, 1D) and check confluence.
    """
    from market.history import get_ohlcv

    signals = []

    # ── 15m Intraday ──────────────────────────────────────────
    try:
        df_15 = get_ohlcv(symbol, exchange, interval="15minute", days=10, include_live_candle=True)
        if not df_15.empty and len(df_15) >= 15:
            sig_15 = _analyze_timeframe(df_15, "15m")
            signals.append(sig_15)
    except Exception:
        pass

    # ── Hourly (60m) ──────────────────────────────────────────
    try:
        df_h = get_ohlcv(symbol, exchange, interval="60minute", days=30, include_live_candle=True)
        if not df_h.empty and len(df_h) >= 20:
            sig_h = _analyze_timeframe(df_h, "1h")
            signals.append(sig_h)
    except Exception:
        pass

    # ── Daily ────────────────────────────────────────────────
    try:
        df_d = get_ohlcv(symbol, exchange, interval="day", days=250, include_live_candle=True)
        if not df_d.empty and len(df_d) >= 20:
            sig_d = _analyze_timeframe(df_d, "1D")
            signals.append(sig_d)
    except Exception:
        pass

    # ── Confluence ───────────────────────────────────────────
    if not signals:
        return MultiTimeframeResult(
            symbol=symbol,
            signals=[],
            confluence="NEUTRAL",
            confluence_score=0,
            alignment="NO_DATA",
            recommendation="Insufficient data for multi-timeframe analysis.",
        )

    avg_score = sum(s.score for s in signals) / len(signals)
    verdicts = [s.verdict for s in signals]
    all_bull = all(v == "BULLISH" for v in verdicts)
    all_bear = all(v == "BEARISH" for v in verdicts)
    mixed = not all_bull and not all_bear and len(set(verdicts)) > 1

    if all_bull and avg_score > 30:
        confluence = "STRONG_BUY"
        alignment = "ALIGNED"
        rec = "All timeframes bullish — high-confidence entry. Use daily levels for entry, hourly for timing."
    elif all_bull:
        confluence = "BUY"
        alignment = "ALIGNED"
        rec = "Timeframes aligned bullish. Enter on hourly pullback to support."
    elif all_bear and avg_score < -30:
        confluence = "STRONG_SELL"
        alignment = "ALIGNED"
        rec = "All timeframes bearish — avoid longs. Consider puts or short if available."
    elif all_bear:
        confluence = "SELL"
        alignment = "ALIGNED"
        rec = "Timeframes aligned bearish. Exit longs or tighten stop-losses."
    elif mixed:
        confluence = "NEUTRAL"
        alignment = "CONFLICTING"
        rec = "Timeframes conflicting — wait for alignment before entering. Daily is the primary trend."
    else:
        confluence = "NEUTRAL"
        alignment = "MIXED"
        rec = "No clear signal across timeframes. Wait for clarity."

    return MultiTimeframeResult(
        symbol=symbol,
        signals=signals,
        confluence=confluence,
        confluence_score=round(avg_score, 1),
        alignment=alignment,
        recommendation=rec,
    )


def _analyze_timeframe(df: pd.DataFrame, label: str) -> TimeframeSignal:
    """Run basic technical indicators on a dataframe."""
    from analysis.technical import rsi as calc_rsi, ema as calc_ema

    if df is None or len(df) < 14:
        return TimeframeSignal(
            timeframe=label,
            verdict="UNAVAILABLE",
            score=0.0,
            rsi=0.0,
            trend="UNKNOWN",
            macd="UNAVAILABLE",
            signal_type="Awaiting Data",
            key_level="—",
        )

    close = df["close"]
    rsi_series = calc_rsi(close)
    rsi_val = (
        float(rsi_series.iloc[-1])
        if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1])
        else 0.0
    )
    has_ema20 = len(close) >= 20
    has_ema50 = len(close) >= 50
    ema20 = float(calc_ema(close, 20).iloc[-1]) if has_ema20 else 0.0
    ema50 = float(calc_ema(close, 50).iloc[-1]) if has_ema50 else 0.0

    # MACD
    has_macd = len(close) >= 26
    if has_macd:
        ema12 = calc_ema(close, 12)
        ema26 = calc_ema(close, 26)
        macd_line = ema12 - ema26
        signal_line = calc_ema(macd_line, 9)
        macd_hist = float((macd_line - signal_line).iloc[-1])
    else:
        macd_hist = 0.0

    # Score only available indicators without false penalties for missing data
    score = 0.0
    if rsi_val > 0:
        if rsi_val < 30:
            score += 20
        elif rsi_val > 70:
            score -= 20
    if has_ema20 and has_ema50:
        if ema20 > ema50:
            score += 15
        elif ema20 < ema50:
            score -= 15
    if has_macd:
        if macd_hist > 0:
            score += 15
        elif macd_hist < 0:
            score -= 15

    verdict = "BULLISH" if score > 10 else "BEARISH" if score < -10 else "NEUTRAL"

    signal_desc = (
        "Higher Highs (HH) Breakout"
        if verdict == "BULLISH" and macd_hist > 0
        else (
            "Lower Lows (LL) Distribution"
            if verdict == "BEARISH" and macd_hist < 0
            else (f"{verdict} Momentum" if verdict != "NEUTRAL" else "Range Compression")
        )
    )
    key_level_str = f"EMA20 ₹{ema20:.1f}" if ema20 > 0 else "—"

    return TimeframeSignal(
        timeframe=label,
        verdict=verdict,
        score=score,
        rsi=rsi_val,
        macd_signal="BULLISH_CROSS" if macd_hist > 0 else "BEARISH_CROSS",
        ema_trend="ABOVE" if ema20 > ema50 else "BELOW",
        signal_name=signal_desc,
        key_level=key_level_str,
        ema20=ema20,
    )
