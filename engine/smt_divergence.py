"""
engine/smt_divergence.py
────────────────────────
Smart Money Technique (SMT) Inter-Index Divergence & Non-Confirmation Engine.

In institutional Indian markets (NSE / NFO), benchmark indices (NIFTY 50 and BANK NIFTY,
which accounts for ~34% of NIFTY weight) move in high-correlation harmony.

When an apparent structural breakout or breakdown occurs on one index while the sibling
index fails to confirm (forming an opposite swing structure or remaining trapped on the
wrong side of VWAP):
  1. Breakout SMT Bearish Divergence (Judas Swing / Upthrust Bull Trap):
     - NIFTY prints higher high / Day High breakout.
     - BANKNIFTY prints a lower high or trades below VWAP with negative slope / negative OBI.
     - Action: VETO long breakouts (anti-trap shield).
  2. Breakdown SMT Bullish Divergence (Accumulation / Bear Trap):
     - NIFTY prints lower low / Day Low breakdown.
     - BANKNIFTY prints a higher low or holds above VWAP.
     - Action: VETO short breakdowns (anti-trap shield).
  3. SMT Structural Reversal Ignitions:
     - Signals high-probability institutional turning points before retail indicators catch on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.smt_divergence")

_SIBLING_MAP = {
    "NIFTY": "BANKNIFTY",
    "BANKNIFTY": "NIFTY",
    "FINNIFTY": "BANKNIFTY",
    "MIDCPNIFTY": "NIFTY",
    "SENSEX": "NIFTY",
    "BANKEX": "BANKNIFTY",
}


@dataclass
class SMTDivergenceResult:
    has_divergence: bool
    divergence_type: Optional[str] = (
        None  # "BEARISH_DIVERGENCE_BULL_TRAP" | "BULLISH_DIVERGENCE_BEAR_TRAP" | "CONFIRMED_HARMONY"
    )
    sibling_symbol: str = ""
    primary_symbol: str = ""
    is_trap: bool = False
    rationale: str = ""
    sibling_spot: float = 0.0
    sibling_vwap: float = 0.0
    sibling_high: float = 0.0
    sibling_low: float = 0.0
    sibling_obi: float = 0.0


def _extract_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_sibling_index(symbol: str) -> str:
    """Returns the primary correlated sibling index."""
    clean = canonical_alert_symbol(symbol).upper()
    return _SIBLING_MAP.get(clean, "NIFTY" if clean != "NIFTY" else "BANKNIFTY")


def evaluate_smt_divergence(
    primary_symbol: str,
    direction: str,
    primary_spot: float,
    primary_day_high: Optional[float] = None,
    primary_day_low: Optional[float] = None,
    primary_vwap: Optional[float] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> SMTDivergenceResult:
    """
    Evaluates whether the primary index setup is confirmed by its institutional sibling,
    or whether inter-market SMT divergence signals a high-risk Judas swing trap.
    """
    clean_primary = canonical_alert_symbol(primary_symbol).upper()
    sibling = get_sibling_index(clean_primary)

    if primary_spot <= 0:
        return SMTDivergenceResult(
            has_divergence=False,
            sibling_symbol=sibling,
            primary_symbol=clean_primary,
            rationale="Invalid primary spot price",
        )

    # 1. Fetch live sibling metrics
    s_ltp = 0.0
    s_vwap = 0.0
    s_high = 0.0
    s_low = 0.0

    if quotes_map:
        q = (
            quotes_map.get(sibling)
            or quotes_map.get(f"NSE:{sibling}")
            or quotes_map.get(f"NSE:{sibling}-INDEX")
            or quotes_map.get(f"BSE:{sibling}-INDEX")
        )
        if q:
            s_ltp = _extract_float(
                getattr(q, "last_price", None)
                or getattr(q, "ltp", None)
                or (q.get("ltp") if isinstance(q, dict) else None)
            )
            s_vwap = _extract_float(
                getattr(q, "vwap", None) or (q.get("vwap") if isinstance(q, dict) else None)
            )
            s_high = _extract_float(
                getattr(q, "high", None) or (q.get("high") if isinstance(q, dict) else None)
            )
            s_low = _extract_float(
                getattr(q, "low", None) or (q.get("low") if isinstance(q, dict) else None)
            )

    if s_ltp <= 0:
        try:
            from market.quotes import get_ltp, get_computed_vwap, get_quote

            inst = (
                f"BSE:{sibling}-INDEX"
                if sibling in ("SENSEX", "BANKEX")
                else f"NSE:{sibling}-INDEX"
            )
            s_ltp = get_ltp(inst) or get_ltp(sibling) or 0.0
            if s_ltp > 0:
                s_vwap = (
                    get_computed_vwap(
                        sibling, exchange="BSE" if sibling in ("SENSEX", "BANKEX") else "NSE"
                    )
                    or 0.0
                )
                q_obj = get_quote([inst]).get(inst)
                if q_obj:
                    s_high = _extract_float(getattr(q_obj, "high", 0.0))
                    s_low = _extract_float(getattr(q_obj, "low", 0.0))
        except Exception as e:
            logger.debug(f"[SMTDivergence] Sibling quote fetch failed for {sibling}: {e}")

    if s_ltp <= 0:
        return SMTDivergenceResult(
            has_divergence=False,
            sibling_symbol=sibling,
            primary_symbol=clean_primary,
            rationale=f"Sibling index {sibling} telemetry unavailable",
        )

    # Check TBT OBI-50 on sibling if available (or fallback to L2 5-depth)
    s_obi = 0.0
    try:
        from market.fyers_tbt_manager import FyersTbtManager, resolve_tradable_tbt_symbol

        tbt_mgr = FyersTbtManager()
        if tbt_mgr.is_connected:
            tradable_sibling = resolve_tradable_tbt_symbol(sibling)
            for sym_cand in (tradable_sibling, sibling):
                if sym_cand:
                    depth = tbt_mgr.get_50_depth(sym_cand)
                    if depth and depth.get("status") not in ("UNAVAILABLE", None):
                        s_obi = float(depth.get("obi_50", 0.0) or 0.0)
                        break
    except Exception:
        s_obi = 0.0

    if s_obi == 0.0:
        # Fallback to L2 5-depth for BSE/Sensex/Bankex or when TBT is unpopulated
        try:
            from market.order_book import get_depth_book

            b = get_depth_book(tradable_sibling or sibling)
            if b and b.total_bid_qty > 0 and b.total_ask_qty > 0:
                s_obi = b.obi(5)
        except Exception as e_ob:
            logger.debug(f"[smt_divergence] Order book sampling suppressed: {e_ob}")

    dir_up = direction.upper()
    is_bull = dir_up in ("BULLISH", "BUY", "LONG", "CALL", "CE")

    # ── CASE A: BULLISH BREAKOUT CONTEXT (Check for Bearish Divergence Trap) ──
    if is_bull:
        is_primary_at_high = False
        if primary_day_high and primary_day_high > 0:
            dist_to_high_pct = (primary_spot - primary_day_high) / primary_day_high * 100.0
            is_primary_at_high = dist_to_high_pct >= -0.20  # Testing or breaking day high

        # Check if sibling is failing to confirm:
        # Sibling is trapped below VWAP OR lagging significantly below its day high OR heavy ask OBI
        sibling_below_vwap = s_vwap > 0 and s_ltp < s_vwap
        sibling_lagging_high = False
        if s_high > 0:
            s_dist_to_high_pct = (s_high - s_ltp) / s_high * 100.0
            sibling_lagging_high = s_dist_to_high_pct >= 0.50  # Sibling is >0.50% below day high

        if is_primary_at_high and (sibling_below_vwap or (sibling_lagging_high and s_obi < -0.20)):
            reasons = []
            if sibling_below_vwap:
                reasons.append(
                    f"{sibling} is trapped below VWAP (₹{s_ltp:,.1f} vs VWAP ₹{s_vwap:,.1f})"
                )
            if sibling_lagging_high:
                reasons.append(f"{sibling} is lagging {s_dist_to_high_pct:.2f}% below day high")
            if s_obi < -0.20:
                reasons.append(
                    f"{sibling} order book has heavy ask pressure (OBI-50: {s_obi:+.2f})"
                )

            joined_reason = "; ".join(reasons)
            msg = (
                f"SMT Bearish Divergence Veto: {clean_primary} is testing Day High (₹{primary_spot:,.1f}), "
                f"but sibling {sibling} non-confirms: {joined_reason}. Classic institutional Judas swing bull trap."
            )
            return SMTDivergenceResult(
                has_divergence=True,
                divergence_type="BEARISH_DIVERGENCE_BULL_TRAP",
                sibling_symbol=sibling,
                primary_symbol=clean_primary,
                is_trap=True,
                rationale=msg,
                sibling_spot=s_ltp,
                sibling_vwap=s_vwap,
                sibling_high=s_high,
                sibling_low=s_low,
                sibling_obi=s_obi,
            )

    # ── CASE B: BEARISH BREAKDOWN CONTEXT (Check for Bullish Divergence Trap) ──
    else:
        is_primary_at_low = False
        if primary_day_low and primary_day_low > 0:
            dist_to_low_pct = (primary_spot - primary_day_low) / primary_day_low * 100.0
            is_primary_at_low = dist_to_low_pct <= 0.20  # Testing or breaking day low

        # Check if sibling is failing to confirm:
        # Sibling is holding above VWAP OR holding significantly above its day low OR strong bid OBI
        sibling_above_vwap = s_vwap > 0 and s_ltp > s_vwap
        sibling_holding_low = False
        if s_low > 0:
            s_dist_to_low_pct = (s_ltp - s_low) / s_low * 100.0
            sibling_holding_low = s_dist_to_low_pct >= 0.50  # Sibling is >0.50% above day low

        if is_primary_at_low and (sibling_above_vwap or (sibling_holding_low and s_obi > +0.20)):
            reasons = []
            if sibling_above_vwap:
                reasons.append(
                    f"{sibling} is holding above VWAP (₹{s_ltp:,.1f} vs VWAP ₹{s_vwap:,.1f})"
                )
            if sibling_holding_low:
                reasons.append(f"{sibling} is holding {s_dist_to_low_pct:.2f}% above day low")
            if s_obi > +0.20:
                reasons.append(
                    f"{sibling} order book has strong bid support (OBI-50: {s_obi:+.2f})"
                )

            joined_reason = "; ".join(reasons)
            msg = (
                f"SMT Bullish Divergence Veto: {clean_primary} is testing Day Low (₹{primary_spot:,.1f}), "
                f"but sibling {sibling} non-confirms: {joined_reason}. Classic institutional bear trap stop hunt."
            )
            return SMTDivergenceResult(
                has_divergence=True,
                divergence_type="BULLISH_DIVERGENCE_BEAR_TRAP",
                sibling_symbol=sibling,
                primary_symbol=clean_primary,
                is_trap=True,
                rationale=msg,
                sibling_spot=s_ltp,
                sibling_vwap=s_vwap,
                sibling_high=s_high,
                sibling_low=s_low,
                sibling_obi=s_obi,
            )

    return SMTDivergenceResult(
        has_divergence=False,
        divergence_type="CONFIRMED_HARMONY",
        sibling_symbol=sibling,
        primary_symbol=clean_primary,
        is_trap=False,
        rationale=f"Inter-market harmony confirmed between {clean_primary} and {sibling}",
        sibling_spot=s_ltp,
        sibling_vwap=s_vwap,
        sibling_high=s_high,
        sibling_low=s_low,
        sibling_obi=s_obi,
    )
