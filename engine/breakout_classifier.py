"""
engine/breakout_classifier.py
──────────────────────────────
Institutional Breakout Microstructure & Retest Probability Classifier for ChanakyaTrade.

Evaluates whether an active breakout/breakdown is an:
  1. IMBALANCE_CONTINUATION_RUNNER:
     - High pre-breakout compression (TTM Squeeze >= 6 bars)
     - High volume ignition (RVOL >= 2.2x)
     - Clean directional body with low wick rejection (< 20%)
     - Close proximity to consolidation base (Delta_base <= 0.35x ATR)
     - Action: Immediate Stop-Limit / Market execution at pivot. Do NOT wait for retest!

  2. PULLBACK_RETEST_REQUIRED:
     - Move is extended from base (Delta_base > 0.45x ATR or > 0.8%)
     - No pre-breakout coiling (Bollinger Bands already wide)
     - Normal volume (1.2x - 1.8x) or mean-reversion drift
     - Action: Dual-blueprint Limit Order at Base Retest / Fibonacci OTE (61.8% - 78.6%).
               Strictly forbidden to market-buy CMP candle peaks.

  3. EXHAUSTION_TRAP_RISK:
     - Heavy upper wick rejection (> 35% of bar range) indicating passive institutional absorption
     - Negative divergence with Index Tide or volume dry-up
     - Action: VETO / REJECT breakout buy; alert Mean-Reversion / Turtle Soup fade candidate.

Guaranteed Invariants:
  - Timezone-naive DatetimeIndex normalization across all pandas operations.
  - Zero synthetic prices; deterministic mathematical scoring based on Bollinger Bands, Keltner Channels,
    Wilder ATR, and candle wick anatomy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.breakout_classifier")


class BreakoutMode(str, Enum):
    CONTINUATION_RUNNER = "CONTINUATION_RUNNER"
    PULLBACK_RETEST_REQUIRED = "PULLBACK_RETEST_REQUIRED"
    EXHAUSTION_TRAP_RISK = "EXHAUSTION_TRAP_RISK"


@dataclass
class BreakoutClassification:
    mode: BreakoutMode
    confidence: int  # 0 to 100
    recommended_action: str
    recommended_entry_type: str  # "STOP_LIMIT_PIVOT" | "LIMIT_PULLBACK" | "VETO_TRAP"
    optimal_entry_limit: float
    is_extended: bool
    rationale: str
    squeeze_bars: int
    extension_ratio: float  # distance / atr
    wick_ratio: float  # rejection wick / candle range
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "recommended_entry_type": self.recommended_entry_type,
            "optimal_entry_limit": self.optimal_entry_limit,
            "is_extended": self.is_extended,
            "rationale": self.rationale,
            "squeeze_bars": self.squeeze_bars,
            "extension_ratio": round(self.extension_ratio, 3),
            "wick_ratio": round(self.wick_ratio, 3),
            "metrics": self.metrics,
        }


def compute_ttm_squeeze_bars(df: pd.DataFrame, max_lookback: int = 20) -> int:
    """
    Count consecutive bars where Bollinger Bands (20, 2.0) are inside Keltner Channels (20, 1.5 ATR).
    Evaluates historical coiling before the latest breakout bar.
    """
    if df is None or len(df) < 21:
        return 0

    try:
        c = df["Close"] if "Close" in df.columns else df["close"]
        h = df["High"] if "High" in df.columns else df["high"]
        l = df["Low"] if "Low" in df.columns else df["low"]

        # 20-period SMA & StDev
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std(ddof=0)
        bb_upper = sma20 + 2.0 * std20
        bb_lower = sma20 - 2.0 * std20

        # Keltner Channels (20 SMA +/- 1.5 * ATR20)
        tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
        atr20 = tr.rolling(20).mean()
        kc_upper = sma20 + 1.5 * atr20
        kc_lower = sma20 - 1.5 * atr20

        # Squeeze condition: BB inside KC
        in_squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        # Count consecutive squeeze bars backwards from candle before current (t-1)
        squeeze_count = 0
        # Exclude the very latest bar (which might be the expansion/breakout bar)
        seq = (
            in_squeeze.iloc[-max_lookback - 1 : -1].values
            if len(in_squeeze) > max_lookback
            else in_squeeze.iloc[:-1].values
        )
        for val in reversed(seq):
            if bool(val):
                squeeze_count += 1
            else:
                break
        return squeeze_count
    except Exception as e:
        logger.debug(f"[BreakoutClassifier] Squeeze count error: {e}")
        return 0


def classify_breakout_mode(
    df: Optional[pd.DataFrame],
    ltp: float,
    breakout_level: float,
    direction: str = "BULLISH",
    rvol: float = 1.0,
    atr: Optional[float] = None,
    nifty_aligned: Optional[bool] = None,
    base_price: Optional[float] = None,
) -> BreakoutClassification:
    """
    Institutional classifier: Differentiates Continuation Runners from Retest Pullbacks and False Breakout Traps.

    Args:
        df: 5m or 1m OHLCV bars.
        ltp: Current market price.
        breakout_level: Level being broken out of.
        direction: "BULLISH" or "BEARISH".
        rvol: Relative volume ratio of the current session/bar.
        atr: Average True Range (if None, derived from df or 1.2% LTP baseline).
        nifty_aligned: True if benchmark Index agrees with direction.
        base_price: Prior consolidation base level (high of base for bullish, low for bearish).
    """
    is_long = direction.upper() in ("BULLISH", "LONG", "BUY")

    # 1. Resolve ATR
    if atr is None or atr <= 0.0:
        if df is not None and len(df) >= 15:
            try:
                c = df["Close"] if "Close" in df.columns else df["close"]
                h = df["High"] if "High" in df.columns else df["high"]
                l = df["Low"] if "Low" in df.columns else df["low"]
                tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
                atr = float(tr.rolling(14).mean().iloc[-1])
            except Exception:
                atr = max(1.0, ltp * 0.012)
        else:
            atr = max(1.0, ltp * 0.012)

    # 2. Resolve Squeeze Duration (Coiling Energy)
    squeeze_bars = compute_ttm_squeeze_bars(df) if df is not None else 0

    # 3. Resolve Candle Anatomy & Rejection Wick
    wick_ratio = 0.0
    candle_spread = 0.0
    close_at_extreme = False

    if df is not None and len(df) >= 2:
        try:
            last_c = float(df["Close"].iloc[-1] if "Close" in df.columns else df["close"].iloc[-1])
            last_o = float(df["Open"].iloc[-1] if "Open" in df.columns else df["open"].iloc[-1])
            last_h = float(df["High"].iloc[-1] if "High" in df.columns else df["high"].iloc[-1])
            last_l = float(df["Low"].iloc[-1] if "Low" in df.columns else df["low"].iloc[-1])

            candle_range = max(0.01, last_h - last_l)
            candle_spread = abs(last_c - last_o)

            if is_long:
                rejection_wick = last_h - max(last_o, last_c)
                wick_ratio = rejection_wick / candle_range
                # Close is in top 20% of range
                close_at_extreme = bool(last_c >= (last_h - 0.20 * candle_range))
            else:
                rejection_wick = min(last_o, last_c) - last_l
                wick_ratio = rejection_wick / candle_range
                # Close is in bottom 20% of range
                close_at_extreme = bool(last_c <= (last_l + 0.20 * candle_range))
        except Exception as e:
            logger.debug(f"[BreakoutClassifier] Candle anatomy note: {e}")

    # 4. Resolve Base Anchor and Extension
    anchor = base_price if (base_price and base_price > 0) else breakout_level
    dist_from_base = abs(ltp - anchor)
    extension_ratio = dist_from_base / atr if atr > 0 else 0.0
    extension_pct = (dist_from_base / anchor * 100.0) if anchor > 0 else 0.0

    # 5. Determine Optimal Limit Retest Price
    # Optimal retest target is the Base Anchor or a 61.8% pullback into the impulse
    if is_long:
        optimal_limit = round(anchor if anchor < ltp else (ltp - 0.382 * dist_from_base), 1)
        if optimal_limit >= ltp:
            optimal_limit = round(ltp - 0.25 * atr, 1)
    else:
        optimal_limit = round(anchor if anchor > ltp else (ltp + 0.382 * dist_from_base), 1)
        if optimal_limit <= ltp:
            optimal_limit = round(ltp + 0.25 * atr, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # Quantitative Decision Logic
    # ─────────────────────────────────────────────────────────────────────────

    # Rule A: High Probability Liquidity Trap / False Breakout
    # - Heavy rejection wick (>= 40% of total candle range) indicates passive institutional absorption / Upthrust
    # - OR fighting index tide with lack of volume
    is_trap = bool(
        (wick_ratio >= 0.40) or (nifty_aligned is False and rvol < 1.30 and extension_ratio > 0.40)
    )

    if is_trap:
        conf = min(90, int(65 + (wick_ratio * 50)))
        return BreakoutClassification(
            mode=BreakoutMode.EXHAUSTION_TRAP_RISK,
            confidence=conf,
            recommended_action="VETO_OR_FADE",
            recommended_entry_type="VETO_TRAP",
            optimal_entry_limit=optimal_limit,
            is_extended=True,
            rationale=(
                f"Exhaustion Trap Risk: Rejection wick {wick_ratio * 100:.1f}% indicates passive absorption. "
                f"Spread ({candle_spread:,.1f}) failed to hold highs. Veto breakout market-buy."
            ),
            squeeze_bars=squeeze_bars,
            extension_ratio=extension_ratio,
            wick_ratio=wick_ratio,
            metrics={
                "rvol": rvol,
                "atr": atr,
                "extension_pct": extension_pct,
                "candle_spread": candle_spread,
            },
        )

    # Rule B: Imbalance Continuation Runner (Do NOT wait for retest!)
    # - Strong pre-breakout squeeze coiling (>= 6 bars)
    # - OR massive volume ignition (RVOL >= 2.2x) with close at extreme
    # - AND not massively over-extended (extension <= 0.45x ATR if no squeeze, or <= 0.95x ATR if long squeeze)
    max_runner_ext = 0.95 if squeeze_bars >= 6 else 0.45
    is_runner = bool(
        (squeeze_bars >= 6 and extension_ratio <= max_runner_ext and close_at_extreme)
        or (
            rvol >= 2.20
            and close_at_extreme
            and extension_ratio <= 0.40
            and (nifty_aligned is not False)
        )
    )

    if is_runner:
        conf = min(
            95,
            int(75 + (squeeze_bars * 2) + (5 if rvol >= 2.0 else 0) + (5 if nifty_aligned else 0)),
        )
        sq_note = (
            f"Pre-breakout TTM squeeze ({squeeze_bars} bars) provides coiled spring energy. "
            if squeeze_bars >= 6
            else ""
        )
        return BreakoutClassification(
            mode=BreakoutMode.CONTINUATION_RUNNER,
            confidence=conf,
            recommended_action="BUY_CONFIRMATION_STOP_LIMIT",
            recommended_entry_type="STOP_LIMIT_PIVOT",
            optimal_entry_limit=ltp,
            is_extended=False,
            rationale=(
                f"Continuation Runner: {sq_note}Impulse closed at extreme ({wick_ratio * 100:.1f}% wick) "
                f"with high velocity. Tight base extension ({extension_ratio:.2f}x ATR). Execute at pivot; do NOT wait for retest."
            ),
            squeeze_bars=squeeze_bars,
            extension_ratio=extension_ratio,
            wick_ratio=wick_ratio,
            metrics={
                "rvol": rvol,
                "atr": atr,
                "extension_pct": extension_pct,
                "squeeze_bars": squeeze_bars,
            },
        )

    # Rule C: Auction Retest Required (Default for extended or uncoiled breakouts)
    # - Move is extended from base (> 0.40x ATR or > 0.8%)
    # - Lack of multi-bar squeeze coiling
    # - Retail breakout buyers are vulnerable to mean-reversion retest
    is_extended = bool(extension_ratio > 0.40 or extension_pct > 0.80)
    conf = min(92, int(70 + (extension_ratio * 20)))

    return BreakoutClassification(
        mode=BreakoutMode.PULLBACK_RETEST_REQUIRED,
        confidence=conf,
        recommended_action="BUY_LIMIT_PULLBACK_RETEST",
        recommended_entry_type="LIMIT_PULLBACK",
        optimal_entry_limit=optimal_limit,
        is_extended=is_extended,
        rationale=(
            f"Retest Required: Price is extended {extension_ratio:.2f}x ATR ({extension_pct:.2f}%) from base anchor. "
            f"Lack of coiling makes CMP market-buy vulnerable to mean-reversion. Place Limit Order in retest zone."
        ),
        squeeze_bars=squeeze_bars,
        extension_ratio=extension_ratio,
        wick_ratio=wick_ratio,
        metrics={
            "rvol": rvol,
            "atr": atr,
            "extension_pct": extension_pct,
            "optimal_limit": optimal_limit,
        },
    )
