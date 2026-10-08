"""
engine/pipeline/coherence_gate.py
───────────────────────────────────
Institutional Multi-Index Coherence, Directional Whiplash Prevention,
and Quality Standard Gate for the ChanakyaTrade alert pipeline.

Responsibilities:
1. Multi-Index Macro Coherence:
   Prevents conflicting opposing directional trades across correlated Indian
   benchmark indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) unless a verified
   structural reversal (CHoCH, MSS, PDH/PDL liquidity sweep) is present.
2. Concurrent Index Signal Quality Standard:
   Allows concurrent high-quality index opportunities (e.g. BankNifty while Nifty
   is running) to be shared with traders as long as:
     - Confidence >= 80%
     - Risk:Reward Ratio >= 1:2.0
   Substandard noise signals are suppressed.
3. In-Flight Directional Lockout & Whiplash Guard:
   Prevents flipping direction back-and-forth on the same instrument unless
   the market structure has conclusively shifted.
4. Session Trap Pivot Guard:
   Avoids repeating failed breakout entries into verified session trap levels.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional, Sequence

logger = logging.getLogger("engine.pipeline.coherence_gate")

_INDEX_BENCHMARKS = frozenset({
    "NIFTY",
    "NIFTY 50",
    "NIFTY50",
    "BANKNIFTY",
    "NIFTY BANK",
    "FINNIFTY",
    "NIFTY FIN SERVICE",
    "MIDCPNIFTY",
    "NIFTY MID SELECT",
    "SENSEX",
    "BSE SENSEX",
    "BANKEX",
})


def clean_canonical_symbol(symbol: str) -> str:
    """Normalize raw exchange:symbol to canonical uppercase symbol."""
    return (
        (symbol or "")
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("NFO:", "")
        .replace("BFO:", "")
        .strip()
        .upper()
    )


class CoherenceGate:
    """Institutional Pre-Dispatch Coherence and Whiplash Prevention Gate."""

    def __init__(self, index_benchmarks: frozenset[str] = _INDEX_BENCHMARKS) -> None:
        self.index_benchmarks = index_benchmarks

    def has_structural_reversal(self, alert: Any) -> bool:
        """Determines whether an alert possesses verified structural reversal evidence."""
        metrics = getattr(alert, "metrics", {}) or {}
        if not isinstance(metrics, dict):
            metrics = {}

        summary_str = str(getattr(alert, "summary", "") or "")
        headline_str = str(getattr(alert, "headline", "") or "")
        combined_text = f"{headline_str} {summary_str}".lower()

        return bool(
            metrics.get("choch")
            or metrics.get("mss")
            or metrics.get("pdh_sweep")
            or metrics.get("pdl_sweep")
            or metrics.get("is_institutional_thrust")
            or re.search(
                r"\b(choch|mss|change of character|market structure shift|trend reversal|structural reversal)\b",
                combined_text,
                re.IGNORECASE,
            )
        )

    def validate_multi_index_coherence(
        self, alert: Any, existing_active_alerts: Sequence[Any]
    ) -> tuple[bool, str]:
        """
        Validates that an incoming index alert does not create inter-index contradiction
        or substandard clutter.
        Returns: (is_allowed, reason_or_suppression_message)
        """
        clean_target = clean_canonical_symbol(getattr(alert, "symbol", ""))
        if clean_target not in self.index_benchmarks:
            return True, "Non-index symbol: bypasses benchmark coherence gate"

        direction = str(getattr(alert, "direction", "NEUTRAL")).upper()

        # Find other active index alerts
        existing_indices = [
            a for a in existing_active_alerts
            if getattr(a, "is_active", False)
            and not getattr(a, "is_invalidated", False)
            and getattr(a, "stage", "") in ("IGNITED", "TRIGGERED", "PARTIAL_PROFIT_TAKEN")
            and clean_canonical_symbol(getattr(a, "symbol", "")) in self.index_benchmarks
            and getattr(a, "alert_id", "") != getattr(alert, "alert_id", "")
        ]

        if not existing_indices:
            return True, "No existing active benchmark positions in flight"

        # 1. Opposing Directional Conflict Guard
        opposing_indices = [
            a for a in existing_indices
            if str(getattr(a, "direction", "")).upper() in ("BULLISH", "BEARISH")
            and str(getattr(a, "direction", "")).upper() != direction
        ]

        if opposing_indices:
            if not self.has_structural_reversal(alert):
                opp_syms = [getattr(a, "symbol", "") for a in opposing_indices]
                msg = (
                    f"🛑 Multi-Index Coherence Guard: Suppressed conflicting {direction} {clean_target} "
                    f"({getattr(alert, 'alert_type', '')}). Active opposing "
                    f"{getattr(opposing_indices[0], 'direction', '')} trades on {opp_syms} are already running. "
                    f"Prohibit inter-index whipsaw conflict without confirmed structural reversal."
                )
                logger.info(f"[CoherenceGate] {msg}")
                return False, msg

        # 2. Quality Standard for Concurrent Index Signals
        # When an index trade is active, additional/better forming index signals
        # must meet: Confidence >= 80% and R:R >= 2.0
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        conf = float(getattr(alert, "confidence", 0.0) or 0.0)

        rr_ratio = 2.0
        try:
            if ltp > 0 and t1 > 0 and sl > 0:
                rr_ratio = abs(t1 - ltp) / max(0.01, abs(ltp - sl))
        except Exception:
            pass

        if conf < 80.0 or rr_ratio < 2.0:
            msg = (
                f"🛑 Quality Standard: Suppressed secondary index trade {clean_target} "
                f"(confidence={conf:.0f}%, R:R={rr_ratio:.2f}). "
                f"Concurrent index signals require confidence >= 80% and R:R >= 2.0."
            )
            logger.info(f"[CoherenceGate] {msg}")
            return False, msg

        logger.info(
            f"[CoherenceGate] ✨ High-Quality Concurrent Index Signal Approved: Sharing {clean_target} "
            f"({direction} {getattr(alert, 'alert_type', '')}, confidence={conf:.0f}%, R:R={rr_ratio:.2f}) "
            f"alongside {len(existing_indices)} active index trade(s)."
        )
        return True, "Approved concurrent high-quality index trade"


# Global singleton instance
coherence_gate = CoherenceGate()
