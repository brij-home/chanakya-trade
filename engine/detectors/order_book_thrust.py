"""
engine/detectors/order_book_thrust.py
──────────────────────────────────────
Institutional Microstructure Order Book Thrust & Iceberg Absorption Detector.

Leverages Fyers Prime 50-Level Depth of Market (DOM / TBT) and L2 5-depth to detect:
1. BULLISH_ORDER_BOOK_THRUST:
   - High 50-level Order Book Imbalance (OBI-50 >= +0.50).
   - Resting institutional Iceberg Bid Floor (FORTRESS/STRONG/MODERATE wall) within 0.85% below LTP.
   - Book density >= 20% across 100 slots with tight bid-ask spread (<= 0.35%).
   - Native exchange ATP confluence: LTP >= ATP * 0.998 (price above or reclaiming session VWAP).
2. BEARISH_ORDER_BOOK_EXHAUSTION:
   - Severe negative Order Book Imbalance (OBI-50 <= -0.50).
   - Resting institutional Iceberg Ask Ceiling (FORTRESS/STRONG/MODERATE wall) within 0.85% above LTP.
   - Spread <= 0.35%, price failing below exchange ATP: LTP <= ATP * 1.002.

Fully implements the BaseDetector protocol for unified single-pass evaluation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert

if TYPE_CHECKING:
    from engine.detection_context import DetectionContext

logger = logging.getLogger("engine.detectors.order_book_thrust")


def detect_order_book_thrust(ctx: DetectionContext) -> list[AutoAlert]:
    """
    Evaluates institutional 50-depth / 5-depth microstructure for order book thrust.
    Returns AutoAlert instances with actionable execution blueprints.
    """
    if ctx.ltp <= 0:
        return []

    curr_p = ctx.ltp
    canonical_sym = canonical_alert_symbol(ctx.symbol)

    # 1. Retrieve 50-level depth from context or FyersTbtManager singleton
    depth_data: Optional[dict[str, Any]] = None
    if ctx.extra_metrics:
        depth_data = ctx.extra_metrics.get("depth_50") or ctx.extra_metrics.get("order_book")

    if not depth_data or not isinstance(depth_data, dict) or not depth_data.get("bids"):
        try:
            from market.fyers_tbt_manager import FyersTbtManager

            mgr = FyersTbtManager()
            depth_data = mgr.get_50_depth(ctx.symbol)
        except Exception as e:
            logger.debug(f"[order_book_thrust] TBT lookup exception for {ctx.symbol}: {e}")
            depth_data = None

    if not depth_data or not isinstance(depth_data, dict):
        return []

    bids = depth_data.get("bids", [])
    asks = depth_data.get("asks", [])
    if not bids or not asks:
        return []

    # 2. Extract Microstructure Metrics
    obi_50 = float(depth_data.get("obi_50", 0.0) or 0.0)
    density_score = float(depth_data.get("density_score", 0.0) or 0.0)
    tbq = int(depth_data.get("tbq", 0) or 0)
    tsq = int(depth_data.get("tsq", 0) or 0)

    # Extract Institutional Wall Durability & Micro-Price Flow Metrics
    fleeing_bid = bool(depth_data.get("fleeing_bid_wall_detected", False))
    fleeing_ask = bool(depth_data.get("fleeing_ask_wall_detected", False))
    fortress_bid = bool(depth_data.get("fortress_bid_wall_confirmed", False))
    fortress_ask = bool(depth_data.get("fortress_ask_wall_confirmed", False))
    micro_skew = float(depth_data.get("micro_price_skew_bps", 0.0) or 0.0)
    flow_posture = str(depth_data.get("order_flow_posture", "BALANCED"))

    # If obi_50 is not precomputed, compute from total quantity
    if obi_50 == 0.0 and (tbq + tsq) > 0:
        obi_50 = round((tbq - tsq) / max(1, tbq + tsq), 4)

    # Bid-Ask spread audit
    best_bid = float(bids[0].get("price", 0.0))
    best_ask = float(asks[0].get("price", 0.0))
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return []

    spread = round(best_ask - best_bid, 2)
    spread_pct = round((spread / curr_p) * 100.0, 3)

    # Require tight institutional spread (<= 0.35%) to prevent slippage traps
    if spread_pct > 0.35:
        return []

    # 3. Native ATP Confluence (Exchange-Authoritative Session VWAP)
    atp: Optional[float] = None
    if ctx.vwap and ctx.vwap > 0:
        atp = ctx.vwap
    elif ctx.extra_metrics and ctx.extra_metrics.get("atp"):
        atp = float(ctx.extra_metrics["atp"])
    else:
        try:
            from engine.market_matrix import MarketMatrix

            matrix_atp = MarketMatrix().get_atp(canonical_sym)
            if matrix_atp and matrix_atp > 0:
                atp = matrix_atp
        except Exception as e_suppressed:
            logger.debug(f"[order_book_thrust] Matrix ATP lookup notice: {e_suppressed}")

    # Walls / Iceberg absorption evaluation
    strongest_bid_wall = depth_data.get("strongest_bid_wall")
    strongest_ask_wall = depth_data.get("strongest_ask_wall")
    bid_walls = depth_data.get("bid_walls", [])
    ask_walls = depth_data.get("ask_walls", [])

    alerts: list[AutoAlert] = []

    # ──────────────────────────────────────────────────────────────────────────
    # SETUP 1: BULLISH ORDER BOOK THRUST
    # ──────────────────────────────────────────────────────────────────────────
    # Condition:
    # 1. Heavy buying pressure: OBI-50 >= +0.50 (buyers outweigh sellers 3:1)
    # 2. Resting iceberg support: bid wall exists or solid depth density >= 20%
    # 3. Exchange ATP alignment: LTP >= ATP * 0.998 (not fighting falling session VWAP)
    # 4. Zero Fleeing Bid Spoof: Ensure the resting bid wall didn't vanish as price approached!
    # 5. Non-negative Micro-Price Skew: Micro-price must not be dragged down by aggressive market sells
    is_bullish_thrust = (
        obi_50 >= 0.50
        and (len(bid_walls) > 0 or density_score >= 20.0)
        and not fleeing_bid  # Anti-Spoof Rug-Pull Veto
        and micro_skew >= -4.0  # Anti-Aggressive Market Sell Skew Veto
    )

    if is_bullish_thrust:
        # Check ATP posture
        atp_aligned = True
        if atp and atp > 0:
            atp_aligned = curr_p >= (atp * 0.998)

        if atp_aligned:
            # Stop Loss calculation anchored to resting iceberg wall or dynamic ATR
            wall_p = strongest_bid_wall.get("price") if strongest_bid_wall else None
            wall_str = (
                strongest_bid_wall.get("strength", "MODERATE") if strongest_bid_wall else "NONE"
            )

            if wall_p and 0 < wall_p < curr_p and ((curr_p - wall_p) / curr_p) <= 0.015:
                # Place stop just below the institutional bid wall
                sl = round(wall_p * 0.9985, 2)
            else:
                sl = ctx.get_dynamic_stop_loss(direction="BULLISH", multiplier=1.1)

            risk = max(0.5, curr_p - sl)
            # Ensure risk is tightly controlled (<= 2.5% of spot)
            if risk <= (curr_p * 0.025):
                t1 = round(curr_p + (2.0 * risk), 2)
                t2 = round(curr_p + (4.0 * risk), 2)
                runner = round(curr_p + (6.0 * risk), 2)

                confidence = 85.0
                if wall_str in ("FORTRESS", "STRONG"):
                    confidence += 5.0
                if fortress_bid:
                    confidence += 4.0
                if fleeing_ask:
                    confidence += 3.0
                if atp and curr_p > atp:
                    confidence += 3.0
                if density_score >= 40.0:
                    confidence += 2.0
                confidence = min(96.0, confidence)

                ticket = ctx.build_execution_ticket(
                    stop_loss=sl,
                    target_price=t1,
                    direction="BULLISH",
                    alert_type="ORDER_BOOK_THRUST",
                )

                alert_id = generate_alert_id("ob-thrust", canonical_sym, variant="bull-thrust")
                alerts.append(
                    AutoAlert(
                        alert_id=alert_id,
                        symbol=ctx.symbol,
                        exchange=ctx.exchange,
                        segment=ctx.segment,
                        alert_type="ORDER_BOOK_THRUST",
                        stage="IGNITED",
                        direction="BULLISH",
                        headline=f"{canonical_sym} Institutional Order Book Thrust (OBI: {obi_50:+.2f})",
                        summary=(
                            f"Microstructure surge: 50-depth OBI at {obi_50:+.2f} with {tbq:,} bids vs {tsq:,} asks. "
                            f"Resting iceberg bid support {wall_str} at {wall_p if wall_p else sl:.2f}."
                            + (" | 🧱 Fortress Bid Floor Verified." if fortress_bid else "")
                            + (" | ⚡ Ask Resistance Fled (Bluff Cleared)." if fleeing_ask else "")
                        ),
                        ltp=curr_p,
                        underlying_spot=curr_p,
                        trigger_level=curr_p,
                        target_level=t1,
                        stop_loss=sl,
                        confidence=confidence,
                        metrics={
                            "obi_50": obi_50,
                            "tbq": tbq,
                            "tsq": tsq,
                            "density_score": density_score,
                            "spread_pct": spread_pct,
                            "atp": round(atp, 2) if atp else None,
                            "micro_price_skew_bps": micro_skew,
                            "order_flow_posture": flow_posture,
                            "fortress_bid_confirmed": fortress_bid,
                            "fleeing_ask_confirmed": fleeing_ask,
                            "iceberg_wall_strength": wall_str,
                            "iceberg_wall_price": wall_p,
                            "r_multiple_t1": 2.0,
                            "r_multiple_t2": 4.0,
                            "provenance": depth_data.get("provenance", "LIVE_TBT_50"),
                        },
                        actionable_plan={
                            "action": "BUY",
                            "entry_zone": f"{curr_p:.2f} - {curr_p * 1.0025:.2f}",
                            "invalidation_stop": sl,
                            "target_1": t1,
                            "target_2": t2,
                            "runner_target": runner,
                            "no_chase_level": round(curr_p + (0.5 * risk), 2),
                            "execution_ticket": ticket,
                        },
                    )
                )

    # ──────────────────────────────────────────────────────────────────────────
    # SETUP 2: BEARISH ORDER BOOK EXHAUSTION / ASYMMETRIC SHORT
    # ──────────────────────────────────────────────────────────────────────────
    is_bearish_exhaustion = (
        obi_50 <= -0.50
        and (len(ask_walls) > 0 or density_score >= 20.0)
        and not fleeing_ask  # Anti-Spoof Bear-Trap Veto
        and micro_skew <= 4.0  # Anti-Aggressive Market Buy Skew Veto
    )

    if is_bearish_exhaustion:
        atp_aligned = True
        if atp and atp > 0:
            atp_aligned = curr_p <= (atp * 1.002)

        if atp_aligned:
            wall_p = strongest_ask_wall.get("price") if strongest_ask_wall else None
            wall_str = (
                strongest_ask_wall.get("strength", "MODERATE") if strongest_ask_wall else "NONE"
            )

            if wall_p and wall_p > curr_p and ((wall_p - curr_p) / curr_p) <= 0.015:
                # Place stop just above the institutional ask wall
                sl = round(wall_p * 1.0015, 2)
            else:
                sl = ctx.get_dynamic_stop_loss(direction="BEARISH", multiplier=1.1)

            risk = max(0.5, sl - curr_p)
            if risk <= (curr_p * 0.025):
                t1 = round(curr_p - (2.0 * risk), 2)
                t2 = round(curr_p - (4.0 * risk), 2)
                runner = round(curr_p - (6.0 * risk), 2)

                confidence = 85.0
                if wall_str in ("FORTRESS", "STRONG"):
                    confidence += 5.0
                if fortress_ask:
                    confidence += 4.0
                if fleeing_bid:
                    confidence += 3.0
                if atp and curr_p < atp:
                    confidence += 3.0
                if density_score >= 40.0:
                    confidence += 2.0
                confidence = min(96.0, confidence)

                ticket = ctx.build_execution_ticket(
                    stop_loss=sl,
                    target_price=t1,
                    direction="BEARISH",
                    alert_type="ORDER_BOOK_THRUST",
                )

                alert_id = generate_alert_id("ob-thrust", canonical_sym, variant="bear-exhaust")
                alerts.append(
                    AutoAlert(
                        alert_id=alert_id,
                        symbol=ctx.symbol,
                        exchange=ctx.exchange,
                        segment=ctx.segment,
                        alert_type="ORDER_BOOK_THRUST",
                        stage="IGNITED",
                        direction="BEARISH",
                        headline=f"{canonical_sym} Institutional Order Book Exhaustion (OBI: {obi_50:+.2f})",
                        summary=(
                            f"Microstructure exhaustion: 50-depth OBI at {obi_50:+.2f} with {tsq:,} asks overpowering {tbq:,} bids. "
                            f"Resting iceberg ask ceiling {wall_str} at {wall_p if wall_p else sl:.2f}."
                            + (" | 🧱 Fortress Ask Ceiling Verified." if fortress_ask else "")
                            + (" | ⚡ Bid Floor Fled (Rug-Pull Confirmed)." if fleeing_bid else "")
                        ),
                        ltp=curr_p,
                        underlying_spot=curr_p,
                        trigger_level=curr_p,
                        target_level=t1,
                        stop_loss=sl,
                        confidence=confidence,
                        metrics={
                            "obi_50": obi_50,
                            "tbq": tbq,
                            "tsq": tsq,
                            "density_score": density_score,
                            "spread_pct": spread_pct,
                            "atp": round(atp, 2) if atp else None,
                            "micro_price_skew_bps": micro_skew,
                            "order_flow_posture": flow_posture,
                            "fortress_ask_confirmed": fortress_ask,
                            "fleeing_bid_confirmed": fleeing_bid,
                            "iceberg_wall_strength": wall_str,
                            "iceberg_wall_price": wall_p,
                            "r_multiple_t1": 2.0,
                            "r_multiple_t2": 4.0,
                            "provenance": depth_data.get("provenance", "LIVE_TBT_50"),
                        },
                        actionable_plan={
                            "action": "SELL",
                            "entry_zone": f"{curr_p * 0.9975:.2f} - {curr_p:.2f}",
                            "invalidation_stop": sl,
                            "target_1": t1,
                            "target_2": t2,
                            "runner_target": runner,
                            "no_chase_level": round(curr_p - (0.5 * risk), 2),
                            "execution_ticket": ticket,
                        },
                    )
                )

    return alerts


class OrderBookThrustDetector:
    """Class wrapper conforming to the BaseDetector protocol."""

    detector_slug: str = "order_book_thrust"
    detector_name: str = "Microstructure Order Book Thrust & Iceberg Absorption"
    supported_segments: tuple[str, ...] = ("EQUITY", "FNO_STOCK", "FNO_INDEX", "COMMODITY")

    def detect(self, ctx: DetectionContext) -> list[AutoAlert]:
        return detect_order_book_thrust(ctx)
