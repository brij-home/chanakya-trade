"""
market/universe_depth_radar.py
──────────────────────────────
Institutional L2 Market Depth Radar & Universe Aggregator.

Provides broad-spectrum order book scanning (5/20 depth) across:
  1. Liquid Index F&O (NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY + ATM Options).
  2. Top liquid high-beta F&O Equities.
  3. Active Setup / Radar candidates from engine storage (auto_alerts.json).

Features:
  - Order Book Imbalance (OBI) spectrum & directional bias.
  - Micro-price skew (leading price direction indicator).
  - Spread friction in basis points (bps) & execution safety rating.
  - Depth capital notional (₹ Crores) & Bid/Ask asymmetry ratio.
  - Resting liquidity pocket & fortress wall detection.
  - Sub-second thread-locked in-memory caching to prevent broker overload.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("market.universe_depth_radar")

# ── Curated Universe Tiers ──────────────────────────────────────────

CORE_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "MIDCPNIFTY",
]

CORE_COMMODITIES = [
    "CRUDEOIL",
    "NATURALGAS",
    "GOLD",
    "SILVER",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
]

CORE_CURRENCIES = [
    "USDINR",
    "EURINR",
    "GBPINR",
    "JPYINR",
]

TOP_FNO_STOCKS = [
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "SBIN",
    "BHARTIARTL",
    "LT",
    "TATAMOTORS",
    "AXISBANK",
    "KOTAKBANK",
    "ITC",
    "SUNPHARMA",
    "TATASTEEL",
    "TITAN",
    "BAJFINANCE",
    "MARUTI",
    "M&M",
    "NTPC",
    "COALINDIA",
    "ONGC",
    "POWERGRID",
    "ADANIENT",
    "JSWSTEEL",
    "HINDALCO",
    "HAL",
    "BEL",
    "DLF",
    "PERSISTENT",
    "DIXON",
]

_RADAR_CACHE_LOCK = threading.Lock()
_RADAR_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_RADAR_CACHE_TTL = 4.0  # Seconds in-memory coalescing cache window


def _get_active_commodity_symbols() -> list[str]:
    """Retrieve active near-month contracts for core MCX commodities."""
    try:
        from brokers.fyers import _resolve_commodity_contract

        return [_resolve_commodity_contract(c) for c in CORE_COMMODITIES]
    except Exception as e:
        logger.debug(f"[universe_depth_radar] Commodity contract resolution error: {e}")
        return [f"MCX:{c}FUT" for c in CORE_COMMODITIES]


def _get_active_currency_symbols() -> list[str]:
    """Retrieve active near-month contracts for core CDS currencies."""
    try:
        from brokers.fyers import _resolve_currency_contract

        return [_resolve_currency_contract(c).replace("NSE:", "CDS:") for c in CORE_CURRENCIES]
    except Exception as e:
        logger.debug(f"[universe_depth_radar] Currency contract resolution error: {e}")
        return [f"CDS:{c}FUT" for c in CORE_CURRENCIES]


def _get_active_radar_symbols() -> list[str]:
    """Retrieve symbols from active alerts in auto_alerts.json."""
    active_syms: list[str] = []
    try:
        from engine.storage.alert_repository import AlertRepository

        alerts, _ = AlertRepository.load_alerts()
        for a in alerts:
            status = getattr(a, "status", "")
            sym = getattr(a, "canonical_symbol", "") or getattr(a, "symbol", "")
            if status in ("VALID_UNTRIGGERED", "TRIGGERED", "RUNNING") and sym:
                clean = (
                    sym.replace("NSE:", "")
                    .replace("BSE:", "")
                    .replace("NFO:", "")
                    .replace("MCX:", "")
                    .strip()
                    .upper()
                )
                if clean not in active_syms:
                    active_syms.append(clean)
    except Exception as e:
        logger.debug(f"[universe_depth_radar] Alert symbol resolution: {e}")
    return active_syms[:15]


def _build_l2_decision_intel(
    symbol: str,
    ltp: float,
    obi: float,
    spread_bps: float,
    micro_skew_bps: float,
    has_resting_wall: bool,
    wall_side: Optional[str],
    wall_price: Optional[float],
    wall_ratio: float,
    iceberg_detected: bool,
    iceberg_side: Optional[str],
) -> dict[str, Any]:
    """
    Translates raw L2 metrics into structured, actionable institutional intelligence.
    """
    # 1. Wall presence takes high precedence
    if has_resting_wall and wall_price:
        if wall_side == "BID":
            return {
                "bias": "BULLISH",
                "badge": "🛡️ BULLISH DEMAND FLOOR",
                "tag": f"WALL BID ({wall_ratio}x)",
                "headline": f"Resting Buy Floor @ ₹{wall_price:,.2f} ({wall_ratio}x depth)",
                "meaning": (
                    f"Substantial institutional limit bids clustered at ₹{wall_price:,.2f} absorbing sell volume. "
                    f"OBI is positive at {obi * 100:+.1f}%."
                ),
                "decision": (
                    f"FAVOR CALLS / LONGS: Dips toward ₹{wall_price:,.2f} are high-probability bounce zones. "
                    f"Anchor Invalidation Stop-Loss immediately below this floor."
                ),
            }
        elif wall_side == "ASK":
            return {
                "bias": "BEARISH",
                "badge": "🏰 BEARISH SUPPLY CEILING",
                "tag": f"WALL ASK ({wall_ratio}x)",
                "headline": f"Resting Sell Wall @ ₹{wall_price:,.2f} ({wall_ratio}x depth)",
                "meaning": (
                    f"Heavy institutional limit sell orders clustered at ₹{wall_price:,.2f} capping upside. "
                    f"OBI skew is negative at {obi * 100:+.1f}%."
                ),
                "decision": (
                    f"FAVOR PUTS / SHORTS: Take profit on longs. Do not chase breakouts directly into ₹{wall_price:,.2f} "
                    f"without confirmed absorption."
                ),
            }

    # 2. Iceberg absorption
    if iceberg_detected:
        if iceberg_side == "BUY":
            return {
                "bias": "BULLISH",
                "badge": "🧊 STEALTH BUY ABSORPTION",
                "tag": "ICEBERG BUY",
                "headline": "Hidden Institutional Accumulation Detected",
                "meaning": "Traded market volume on the bid tick significantly exceeds visible book depth. Large passive buyers absorbing liquidity.",
                "decision": "FAVOR LONGS: Follow smart money accumulation. Tighten SL as price gathers upward momentum.",
            }
        elif iceberg_side == "SELL":
            return {
                "bias": "BEARISH",
                "badge": "🧊 STEALTH SELL DISTRIBUTION",
                "tag": "ICEBERG SELL",
                "headline": "Hidden Institutional Distribution Detected",
                "meaning": "Large hidden sell orders are passively liquidating into market buy orders without displaying in the top book.",
                "decision": "FAVOR SHORTS / PROTECT LONGS: Prepare for rapid downside once aggressive buying halts.",
            }

    # 3. Spread shock / Illiquidity friction
    if spread_bps > 5.0:
        return {
            "bias": "CAUTION",
            "badge": "⚠️ SPREAD FRICTION SHOCK",
            "tag": f"SPREAD {spread_bps:.1f} bps",
            "headline": f"Wide Spread ({spread_bps:.1f} bps) — Liquidity Vacuum",
            "meaning": "Market makers have pulled bid/ask quotes, resulting in high slippage costs for aggressive market orders.",
            "decision": "AVOID MARKET ORDERS: High slippage friction. Use strictly limit orders or wait for spread contraction.",
        }

    # 4. Pure OBI & Micro-Price Skew
    if obi >= 0.40:
        return {
            "bias": "BULLISH",
            "badge": "🟢 AGGRESSIVE BUY PRESSURE",
            "tag": f"OBI {obi * 100:+.0f}%",
            "headline": f"Buyers Stacking Bids ({obi * 100:+.1f}% OBI, Micro-Skew {micro_skew_bps:+.1f} bps)",
            "meaning": (
                f"Bids heavily dominate asks across top 5 depth levels. "
                f"Micro-price is pulling {micro_skew_bps:+.1f} bps above LTP, signaling imminent ask lift."
            ),
            "decision": "FAVOR LONGS / MOMENTUM: Breakout probability is elevated. Trail stops tightly below VWAP.",
        }
    elif obi <= -0.40:
        return {
            "bias": "BEARISH",
            "badge": "🔴 AGGRESSIVE SELL PRESSURE",
            "tag": f"OBI {obi * 100:+.0f}%",
            "headline": f"Heavy Supply Overhang ({obi * 100:+.1f}% OBI, Micro-Skew {micro_skew_bps:+.1f} bps)",
            "meaning": (
                f"Offers heavily dominate bids across top 5 depth levels. "
                f"Micro-price is pulling {micro_skew_bps:+.1f} bps below LTP, signaling downward pressure."
            ),
            "decision": "FAVOR SHORTS / EXIT LONGS: Selling pressure is persistent. Look for breakdown continuation.",
        }
    elif obi >= 0.15:
        return {
            "bias": "BULLISH",
            "badge": "🟢 MILD BUY ACCUMULATION",
            "tag": f"OBI {obi * 100:+.0f}%",
            "headline": f"Mild Buyer Dominance ({obi * 100:+.1f}% OBI)",
            "meaning": "Bids moderately exceed asks; order flow leans positive with standard spread stability.",
            "decision": "BULLISH TILT: Support holding well; look for long pullbacks to key levels.",
        }
    elif obi <= -0.15:
        return {
            "bias": "BEARISH",
            "badge": "🔴 MILD SELL DISTRIBUTION",
            "tag": f"OBI {obi * 100:+.0f}%",
            "headline": f"Mild Supply Tilt ({obi * 100:+.1f}% OBI)",
            "meaning": "Asks moderately exceed bids; upside moves are meeting resting limit resistance.",
            "decision": "BEARISH TILT: Resistance active; favor selling on rallies or waiting for clarity.",
        }

    # 5. Equilibrium
    return {
        "bias": "NEUTRAL",
        "badge": "⚖️ BALANCED AUCTION",
        "tag": "EQUILIBRIUM",
        "headline": "Two-Sided Symmetric Order Book",
        "meaning": "Bids and asks are evenly matched with minimal depth skew. Market is in balanced price discovery.",
        "decision": "TRADE PRICE ACTION: No order book distortion detected. Rely on standard VWAP and technical levels.",
    }


def get_universe_depth_radar(
    segment: str = "ALL",
    query: Optional[str] = None,
    limit: int = 60,
    allow_rest_fallback: bool = False,
) -> list[dict[str, Any]]:
    """
    Main aggregator returning rich L2 Depth Radar metrics across curated market symbols.
    """
    now_mono = time.monotonic()
    cache_key = f"{segment}_{query or ''}_{limit}_{allow_rest_fallback}"

    with _RADAR_CACHE_LOCK:
        if cache_key in _RADAR_CACHE:
            ts, cached_rows = _RADAR_CACHE[cache_key]
            if (now_mono - ts) < _RADAR_CACHE_TTL:
                return cached_rows

    # 1. Resolve candidate symbols
    candidates: list[tuple[str, str]] = []  # (symbol, segment_tag)

    norm_seg = (segment or "ALL").upper().strip()

    try:
        from market.calendar import is_market_open

        mcx_open = is_market_open("MCX")
        nse_open = is_market_open("NSE")
    except Exception:
        mcx_open = True
        nse_open = True

    is_evening_session = bool(mcx_open and not nse_open)

    # In evening session or when explicitly requested, prioritize MCX Commodities and CDS Currencies at the top
    if norm_seg in ("ALL", "COMMODITIES", "COMMODITY", "MCX") and (
        norm_seg != "ALL" or is_evening_session
    ):
        for sym in _get_active_commodity_symbols():
            candidates.append((sym, "COMMODITY_MCX"))

    if norm_seg in ("ALL", "CURRENCY", "CURRENCIES", "CDS") and (
        norm_seg != "ALL" or is_evening_session
    ):
        for sym in _get_active_currency_symbols():
            candidates.append((sym, "CURRENCY_CDS"))

    if norm_seg in ("ALL", "INDICES"):
        for sym in CORE_INDICES:
            candidates.append((sym, "INDEX_FNO"))

    if norm_seg in ("ALL", "STOCK_FNO", "STOCKS"):
        for sym in TOP_FNO_STOCKS:
            candidates.append((sym, "STOCK_FNO"))

    if norm_seg in ("ALL", "ACTIVE_RADAR", "ALERTS"):
        for sym in _get_active_radar_symbols():
            if not any(c[0] == sym for c in candidates):
                candidates.append((sym, "ACTIVE_RADAR"))

    # During daytime sessions (when nse_open), append commodities & currency after stocks in ALL
    if norm_seg == "ALL" and not is_evening_session:
        for sym in _get_active_commodity_symbols():
            if not any(c[0] == sym for c in candidates):
                candidates.append((sym, "COMMODITY_MCX"))
        for sym in _get_active_currency_symbols():
            if not any(c[0] == sym for c in candidates):
                candidates.append((sym, "CURRENCY_CDS"))

    # Also check active Fyers TBT slots to include live ATM strikes
    try:
        from market.fyers_tbt_manager import FyersTbtManager

        tbt = FyersTbtManager()
        active_status = tbt.get_active_slots_status()
        slots_list = (
            active_status.get("slots", [])
            if isinstance(active_status, dict)
            else (active_status or [])
        )
        for slot in slots_list:
            sym = slot.get("symbol")
            if sym and not any(c[0] == sym for c in candidates):
                role = slot.get("role", "TBT_STREAM")
                tag = "ACTIVE_TBT" if role != "PRIMARY_CORE" else "INDEX_CORE"
                candidates.append((sym, tag))
    except Exception as e_tbt:
        logger.debug(f"[universe_depth_radar] TBT slot lookup: {e_tbt}")

    # Apply symbol search query filter if provided
    if query:
        q_upper = query.upper().strip()
        candidates = [c for c in candidates if q_upper in c[0].upper()]

    candidates = candidates[: max(10, limit)]

    # Auto-subscribe candidates to WebSocket data socket so ticks stream in RAM
    try:
        from market.websocket import ws_manager

        if ws_manager.connected:
            unsubbed = [
                c[0] for c in candidates if c[0] not in getattr(ws_manager, "_subscribed", set())
            ]
            if unsubbed:
                ws_manager.subscribe(unsubbed[:50])
    except Exception as e_sub:
        logger.debug(f"[universe_depth_radar] Auto-subscribe error: {e_sub}")

    from market.order_book import analyze_symbol_order_book

    from concurrent.futures import ThreadPoolExecutor

    def _process_candidate(cand: tuple[str, str]) -> Optional[dict[str, Any]]:
        sym, seg_tag = cand
        try:
            # During MCX hours, for MCX commodities, allow_rest_fallback=True so they fetch live 5-depth
            # (coalesced by the broker's 5-second TTL cache, using only ~35 req/min total across 7 commodities)
            is_commodity = seg_tag == "COMMODITY_MCX" or sym.startswith("MCX:")
            allow_rest = bool(allow_rest_fallback and is_commodity and mcx_open)
            snap = analyze_symbol_order_book(sym, allow_rest_fallback=allow_rest)
            ltp = float(snap.ltp or 0.0)
            spread = float(snap.spread or 0.0)
            spread_bps = round((spread / ltp * 10000), 1) if ltp > 0 else 0.0
            spread_status = (
                "TIGHT" if spread_bps <= 2.0 else "MODERATE" if spread_bps <= 5.0 else "WIDE"
            )

            tot_bid_qty = int(snap.total_bid_qty or 0)
            tot_ask_qty = int(snap.total_ask_qty or 0)
            bid_notional_cr = round((tot_bid_qty * ltp) / 10000000.0, 2)
            ask_notional_cr = round((tot_ask_qty * ltp) / 10000000.0, 2)
            notional_ratio = round(bid_notional_cr / max(0.01, ask_notional_cr), 2)

            obi = float(snap.obi_weighted if snap.obi_weighted is not None else (snap.obi_5 or 0.0))
            obi_pct = round(obi * 100.0, 1)

            # Micro price skew
            bids = snap.bids or []
            asks = snap.asks or []
            best_bid_p = (
                float(bids[0].get("price", 0.0))
                if bids
                else (ltp - spread / 2.0 if ltp > 0 else 0.0)
            )
            best_ask_p = (
                float(asks[0].get("price", 0.0))
                if asks
                else (ltp + spread / 2.0 if ltp > 0 else 0.0)
            )
            best_bid_q = float(bids[0].get("quantity", 1)) if bids else 1.0
            best_ask_q = float(asks[0].get("quantity", 1)) if asks else 1.0

            if (best_bid_q + best_ask_q) > 0 and best_ask_p > 0 and best_bid_p > 0:
                micro_price = round(
                    (best_bid_q * best_ask_p + best_ask_q * best_bid_p) / (best_bid_q + best_ask_q),
                    2,
                )
            else:
                micro_price = ltp

            micro_skew_bps = round(((micro_price - ltp) / ltp * 10000), 1) if ltp > 0 else 0.0

            # Resting wall
            has_wall = bool(getattr(snap, "has_resting_wall", False))
            wall_side = getattr(snap, "wall_side", None)
            wall_price = getattr(snap, "wall_price", None)
            wall_qty = int(getattr(snap, "wall_qty", 0) or 0)
            wall_ratio = float(getattr(snap, "wall_ratio", 1.0) or 1.0)

            # Iceberg
            iceberg_detected = bool(getattr(snap, "iceberg_detected", False))
            iceberg_side = getattr(snap, "iceberg_side", None)
            iceberg_price = getattr(snap, "iceberg_price", None)

            # Decision intel
            decision_intel = _build_l2_decision_intel(
                symbol=sym,
                ltp=ltp,
                obi=obi,
                spread_bps=spread_bps,
                micro_skew_bps=micro_skew_bps,
                has_resting_wall=has_wall,
                wall_side=wall_side,
                wall_price=wall_price,
                wall_ratio=wall_ratio,
                iceberg_detected=iceberg_detected,
                iceberg_side=iceberg_side,
            )

            # Top 5 bids & asks formatted for DepthLadderWidget compatibility
            formatted_bids = [
                {
                    "price": float(b.get("price", 0.0)),
                    "quantity": int(b.get("quantity", b.get("qty", 0))),
                    "orders": int(b.get("orders", b.get("ord", 1))),
                }
                for b in bids[:5]
            ]
            formatted_asks = [
                {
                    "price": float(a.get("price", 0.0)),
                    "quantity": int(a.get("quantity", a.get("qty", 0))),
                    "orders": int(a.get("orders", a.get("ord", 1))),
                }
                for a in asks[:5]
            ]

            return {
                "symbol": sym,
                "segment": seg_tag,
                "ltp": ltp,
                "spread": round(spread, 2),
                "spread_bps": spread_bps,
                "spread_status": spread_status,
                "total_bid_qty": tot_bid_qty,
                "total_ask_qty": tot_ask_qty,
                "bid_notional_cr": bid_notional_cr,
                "ask_notional_cr": ask_notional_cr,
                "notional_ratio": notional_ratio,
                "obi": obi,
                "obi_pct": obi_pct,
                "micro_price": micro_price,
                "micro_skew_bps": micro_skew_bps,
                "has_resting_wall": has_wall,
                "wall_side": wall_side,
                "wall_price": wall_price,
                "wall_qty": wall_qty,
                "wall_ratio": wall_ratio,
                "iceberg_detected": iceberg_detected,
                "iceberg_side": iceberg_side,
                "iceberg_price": iceberg_price,
                "decision_intel": decision_intel,
                "bids": formatted_bids,
                "asks": formatted_asks,
                "provenance": getattr(snap, "provenance", "BROKER_L2"),
                "updated_at": time.strftime("%H:%M:%S"),
            }
        except Exception as e_row:
            logger.debug(f"[universe_depth_radar] Error computing depth for {sym}: {e_row}")
            return None

    with ThreadPoolExecutor(max_workers=min(10, len(candidates) or 1)) as executor:
        computed = list(executor.map(_process_candidate, candidates))

    rows = [r for r in computed if r is not None]

    with _RADAR_CACHE_LOCK:
        _RADAR_CACHE[cache_key] = (now_mono, rows)

    return rows
