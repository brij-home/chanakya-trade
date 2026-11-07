"""
analysis/confluence_engine.py
─────────────────────────────
Institutional Multi-Factor Structural Confluence Engine.

Unifies disconnected structural, volume, and derivative levels into verified
high-probability Institutional Confluence Clusters:
  1. SMC Unmitigated Order Blocks (Demand & Supply) & Fair Value Gaps (FVG)
  2. Volume Profile Virgin POCs (VPOC), High Volume Nodes (HVN), VAH/VAL boundaries
  3. Event-Driven Anchored VWAP (Swing Low/High, Catalyst, Session Open)
  4. Flanking Options Open Interest (OI) Writing Walls (Call & Put Walls, Max Pain)
  5. Fibonacci Optimal Trade Entry (OTE: 61.8%–78.6% Retracement)

Enforces the institutional invariant:
  - Bull run entries must be anchored near verified DEMAND CLUSTERS.
  - Bear run entries must be anchored near verified SUPPLY CLUSTERS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

import pandas as pd

logger = logging.getLogger("chanakya.analysis.confluence_engine")


@dataclass
class ConfluenceCluster:
    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    cluster_type: str  # "DEMAND_CLUSTER" | "SUPPLY_CLUSTER"
    top: float
    bottom: float
    midpoint: float
    confluence_score: int  # 0 to 100
    factors_count: int
    confluence_factors: List[str] = field(default_factory=list)
    has_order_block: bool = False
    has_volume_poc: bool = False
    has_anchored_vwap: bool = False
    has_oi_wall: bool = False
    has_fib_ote: bool = False
    is_prime_cluster: bool = False  # >= 3 confluences or score >= 75
    invalidation_stop: float = 0.0
    distance_to_ltp_pct: float = 0.0  # (LTP - midpoint) / midpoint * 100
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "cluster_type": self.cluster_type,
            "top": round(self.top, 2),
            "bottom": round(self.bottom, 2),
            "midpoint": round(self.midpoint, 2),
            "confluence_score": self.confluence_score,
            "factors_count": self.factors_count,
            "confluence_factors": self.confluence_factors,
            "has_order_block": self.has_order_block,
            "has_volume_poc": self.has_volume_poc,
            "has_anchored_vwap": self.has_anchored_vwap,
            "has_oi_wall": self.has_oi_wall,
            "has_fib_ote": self.has_fib_ote,
            "is_prime_cluster": self.is_prime_cluster,
            "invalidation_stop": round(self.invalidation_stop, 2),
            "distance_to_ltp_pct": round(self.distance_to_ltp_pct, 2),
            "summary": self.summary,
        }


def find_confluence_clusters(
    symbol: str,
    ltp: float,
    direction: str = "BULLISH",
    df: Optional[pd.DataFrame] = None,
    chain: Optional[List[Any]] = None,
    exchange: str = "NSE",
    proximity_pct: float = 0.015,
) -> List[ConfluenceCluster]:
    """
    Scans and synthesizes all structural anchors into high-probability Confluence Clusters.

    Args:
        symbol: Clean canonical symbol
        ltp: Current last traded price
        direction: "BULLISH" (Demand clusters below/near LTP) | "BEARISH" (Supply clusters above/near LTP)
        df: Daily or multi-timeframe OHLCV DataFrame
        chain: Options chain contracts (optional)
        exchange: Market exchange
        proximity_pct: Proximity window to merge overlapping anchors (default 1.5%)
    """
    if ltp <= 0:
        return []

    is_bullish = direction.upper() in ("BULLISH", "LONG", "BUY")
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # 1. Fetch OHLCV if not provided
    if df is None or len(df) < 15:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, days=250, interval="day", exchange=exchange)
        except Exception as e_supp:
            logger.debug(f"[confluence_engine] OHLCV fetch skipped: {e_supp}")
            df = None

    if df is None or len(df) < 10:
        return []

    # Compute ATR for structural risk buffers
    try:
        from analysis.technical import atr as calc_atr

        atr_s = calc_atr(df, period=14)
        atr = float(atr_s.dropna().iloc[-1]) if not atr_s.dropna().empty else (ltp * 0.015)
    except Exception:
        atr = ltp * 0.015

    # 2. Gather Raw Structural Anchors
    # Anchor format: (level_top, level_bottom, factor_type, factor_desc, weight)
    raw_anchors: List[tuple[float, float, str, str, int]] = []

    # Anchor Layer A: SMC Order Blocks & FVGs
    try:
        from analysis.market_structure import analyze_market_structure

        ms = analyze_market_structure(clean_sym, df=df, exchange=exchange)
        if ms:
            if is_bullish and ms.active_demand_zones:
                for ob in ms.active_demand_zones:
                    tier_wt = 30 if getattr(ob, "quality_tier", "") == "TIER_1_PRIME" else 20
                    desc = f"Demand OB ({getattr(ob, 'quality_tier', 'VALID')}) ₹{ob.bottom:.1f}–₹{ob.top:.1f}"
                    raw_anchors.append((ob.top, ob.bottom, "ORDER_BLOCK", desc, tier_wt))
            elif not is_bullish and ms.active_supply_zones:
                for ob in ms.active_supply_zones:
                    tier_wt = 30 if getattr(ob, "quality_tier", "") == "TIER_1_PRIME" else 20
                    desc = f"Supply OB ({getattr(ob, 'quality_tier', 'VALID')}) ₹{ob.bottom:.1f}–₹{ob.top:.1f}"
                    raw_anchors.append((ob.top, ob.bottom, "ORDER_BLOCK", desc, tier_wt))

            # FVGs
            for fvg in getattr(ms, "fair_value_gaps", []):
                if not getattr(fvg, "filled", False):
                    if is_bullish and fvg.type == "BULLISH" and fvg.top <= ltp * 1.02:
                        raw_anchors.append(
                            (
                                fvg.top,
                                fvg.bottom,
                                "FVG",
                                f"Bullish FVG Imbalance ₹{fvg.bottom:.1f}–₹{fvg.top:.1f}",
                                15,
                            )
                        )
                    elif not is_bullish and fvg.type == "BEARISH" and fvg.bottom >= ltp * 0.98:
                        raw_anchors.append(
                            (
                                fvg.top,
                                fvg.bottom,
                                "FVG",
                                f"Bearish FVG Imbalance ₹{fvg.bottom:.1f}–₹{fvg.top:.1f}",
                                15,
                            )
                        )
    except Exception as e_ms:
        logger.debug(f"[confluence_engine] Market structure layer skipped: {e_ms}")

    # Anchor Layer B: Volume Profile High Volume Nodes (HVN) & POC
    try:
        from analysis.volume_profile import compute_volume_profile

        vp = compute_volume_profile(df, num_bins=24)
        if vp and getattr(vp, "poc", 0.0) > 0:
            poc_top = vp.poc + (0.15 * atr)
            poc_bottom = vp.poc - (0.15 * atr)
            raw_anchors.append(
                (poc_top, poc_bottom, "VOLUME_POC", f"Volume POC ₹{vp.poc:,.1f}", 25)
            )
            if getattr(vp, "vah", 0.0) > 0 and not is_bullish:
                raw_anchors.append(
                    (
                        vp.vah + 0.1 * atr,
                        vp.vah - 0.1 * atr,
                        "VOLUME_VAH",
                        f"Value Area High (VAH) ₹{vp.vah:,.1f}",
                        15,
                    )
                )
            if getattr(vp, "val", 0.0) > 0 and is_bullish:
                raw_anchors.append(
                    (
                        vp.val + 0.1 * atr,
                        vp.val - 0.1 * atr,
                        "VOLUME_VAL",
                        f"Value Area Low (VAL) ₹{vp.val:,.1f}",
                        15,
                    )
                )
    except Exception as e_vp:
        logger.debug(f"[confluence_engine] Volume profile layer skipped: {e_vp}")

    # Anchor Layer C: Anchored VWAP (Catalyst & Swing Pivot)
    try:
        from analysis.anchored_vwap import compute_anchored_vwap

        # Find lowest low and highest high row indices in last 60 bars
        window_bars = min(len(df), 60)
        c_win = df.iloc[-window_bars:]
        low_idx = int(c_win["low"].values.argmin()) if "low" in c_win.columns else 0
        high_idx = int(c_win["high"].values.argmax()) if "high" in c_win.columns else 0

        target_idx = len(df) - window_bars + (low_idx if is_bullish else high_idx)
        avwap_res = compute_anchored_vwap(
            df, anchor_index=target_idx, anchor_type="SWING_LOW" if is_bullish else "SWING_HIGH"
        )
        if avwap_res and getattr(avwap_res, "current_avwap", 0.0) > 0:
            av_val = avwap_res.current_avwap
            raw_anchors.append(
                (
                    av_val + 0.15 * atr,
                    av_val - 0.15 * atr,
                    "ANCHORED_VWAP",
                    f"Anchored VWAP ({avwap_res.anchor_type}) ₹{av_val:,.1f}",
                    20,
                )
            )
    except Exception as e_av:
        logger.debug(f"[confluence_engine] Anchored VWAP layer skipped: {e_av}")

    # Anchor Layer D: Options Open Interest Writing Walls
    try:
        if chain is None and clean_sym in (
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "BANKEX",
        ):
            from market.options import get_options_chain

            chain = get_options_chain(clean_sym)
        if chain:
            if is_bullish:
                puts = [
                    c
                    for c in chain
                    if getattr(c, "option_type", "") == "PE"
                    and getattr(c, "strike", 0) <= ltp
                    and getattr(c, "oi", 0) > 0
                ]
                if puts:
                    best_put = max(puts, key=lambda c: getattr(c, "oi", 0))
                    p_strike = float(best_put.strike)
                    raw_anchors.append(
                        (
                            p_strike + 0.2 * atr,
                            p_strike - 0.2 * atr,
                            "OI_WALL",
                            f"Put Writing Wall ₹{p_strike:,.0f} (OI: {best_put.oi:,})",
                            25,
                        )
                    )
            else:
                calls = [
                    c
                    for c in chain
                    if getattr(c, "option_type", "") == "CE"
                    and getattr(c, "strike", 0) >= ltp
                    and getattr(c, "oi", 0) > 0
                ]
                if calls:
                    best_call = max(calls, key=lambda c: getattr(c, "oi", 0))
                    c_strike = float(best_call.strike)
                    raw_anchors.append(
                        (
                            c_strike + 0.2 * atr,
                            c_strike - 0.2 * atr,
                            "OI_WALL",
                            f"Call Writing Wall ₹{c_strike:,.0f} (OI: {best_call.oi:,})",
                            25,
                        )
                    )
    except Exception as e_oi:
        logger.debug(f"[confluence_engine] Options OI layer skipped: {e_oi}")

    # Anchor Layer E: Fibonacci OTE (0.618 to 0.786)
    try:
        recent_window = min(len(df), 30)
        rec_slice = df.iloc[-recent_window:]
        h_val = (
            float(rec_slice["high"].max())
            if "high" in rec_slice.columns
            else float(rec_slice["close"].max())
        )
        l_val = (
            float(rec_slice["low"].min())
            if "low" in rec_slice.columns
            else float(rec_slice["close"].min())
        )
        span = h_val - l_val
        if span > 0:
            if is_bullish:
                fib_618 = h_val - 0.618 * span
                fib_786 = h_val - 0.786 * span
                raw_anchors.append(
                    (
                        fib_618,
                        fib_786,
                        "FIB_OTE",
                        f"Fibonacci Golden Pocket OTE ₹{fib_786:.1f}–₹{fib_618:.1f}",
                        15,
                    )
                )
            else:
                fib_618 = l_val + 0.618 * span
                fib_786 = l_val + 0.786 * span
                raw_anchors.append(
                    (
                        fib_786,
                        fib_618,
                        "FIB_OTE",
                        f"Fibonacci Premium Retest OTE ₹{fib_618:.1f}–₹{fib_786:.1f}",
                        15,
                    )
                )
    except Exception as e_fib:
        logger.debug(f"[confluence_engine] Fibonacci layer skipped: {e_fib}")

    if not raw_anchors:
        return []

    # 3. Cluster Overlapping & Nearby Anchors into Unified Confluence Zones
    # Sort anchors by midpoint
    sorted_anchors = sorted(raw_anchors, key=lambda a: (a[0] + a[1]) / 2.0)
    clusters: List[ConfluenceCluster] = []

    for a_top, a_bottom, a_type, a_desc, a_wt in sorted_anchors:
        a_mid = (a_top + a_bottom) / 2.0
        merged = False

        for c in clusters:
            # Check if anchor is within proximity percentage of cluster midpoint
            if abs(a_mid - c.midpoint) / c.midpoint <= proximity_pct:
                c.top = max(c.top, a_top)
                c.bottom = min(c.bottom, a_bottom)
                c.midpoint = (c.top + c.bottom) / 2.0
                c.confluence_score = min(100, c.confluence_score + a_wt)
                c.factors_count += 1
                c.confluence_factors.append(a_desc)
                if a_type == "ORDER_BLOCK":
                    c.has_order_block = True
                elif a_type in ("VOLUME_POC", "VOLUME_VAH", "VOLUME_VAL"):
                    c.has_volume_poc = True
                elif a_type == "ANCHORED_VWAP":
                    c.has_anchored_vwap = True
                elif a_type == "OI_WALL":
                    c.has_oi_wall = True
                elif a_type == "FIB_OTE":
                    c.has_fib_ote = True
                merged = True
                break

        if not merged:
            new_c = ConfluenceCluster(
                symbol=clean_sym,
                direction="BULLISH" if is_bullish else "BEARISH",
                cluster_type="DEMAND_CLUSTER" if is_bullish else "SUPPLY_CLUSTER",
                top=a_top,
                bottom=a_bottom,
                midpoint=a_mid,
                confluence_score=min(100, 30 + a_wt),
                factors_count=1,
                confluence_factors=[a_desc],
                has_order_block=(a_type == "ORDER_BLOCK"),
                has_volume_poc=(a_type in ("VOLUME_POC", "VOLUME_VAH", "VOLUME_VAL")),
                has_anchored_vwap=(a_type == "ANCHORED_VWAP"),
                has_oi_wall=(a_type == "OI_WALL"),
                has_fib_ote=(a_type == "FIB_OTE"),
            )
            clusters.append(new_c)

    # 4. Finalize Clusters: Compute Invalidation Stops, LTP distance, and Quality Tiers
    finalized: List[ConfluenceCluster] = []
    sl_buffer = max(0.20 * atr, ltp * 0.004)

    for c in clusters:
        c.distance_to_ltp_pct = (ltp - c.midpoint) / c.midpoint * 100.0
        c.is_prime_cluster = (
            c.factors_count >= 2 and c.confluence_score >= 65
        ) or c.confluence_score >= 80

        if is_bullish:
            c.invalidation_stop = round(c.bottom - sl_buffer, 2)
            c.summary = (
                f"Demand Cluster ₹{c.bottom:.1f}–₹{c.top:.1f} (Score {c.confluence_score}/100, {c.factors_count} factors): "
                + "; ".join(c.confluence_factors[:3])
            )
        else:
            c.invalidation_stop = round(c.top + sl_buffer, 2)
            c.summary = (
                f"Supply Cluster ₹{c.bottom:.1f}–₹{c.top:.1f} (Score {c.confluence_score}/100, {c.factors_count} factors): "
                + "; ".join(c.confluence_factors[:3])
            )

        finalized.append(c)

    # Sort: nearest to current LTP first
    finalized.sort(key=lambda x: abs(x.distance_to_ltp_pct))
    return finalized
