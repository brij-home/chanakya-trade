"""
market/order_book.py
────────────────────
Real-Time Order Book Imbalance (OBI) & Market Microstructure Analytics.

Computes:
  1. Multi-Level Order Book Imbalance (OBI):
     OBI_N = (Sum(Bid_Qty) - Sum(Ask_Qty)) / (Sum(Bid_Qty) + Sum(Ask_Qty))
     Normalized from -1.0 (100% Ask Wall / Heavy Supply) to +1.0 (100% Bid Wall / Heavy Demand).
  2. Distance-Weighted OBI:
     Assigns exponential decay weights to levels closer to the inside spread to avoid spoofing tricks
     at outer levels.
  3. Iceberg / Hidden Order Detection:
     Compares traded volume at specific price levels against visible book quantity.
     If Traded_Volume >> Displayed_Depth_Quantity, an institutional execution algo is passively absorbing orders.
  4. Bid-Ask Spread Dynamics:
     Flags Spread Expansion Shock when spread widens beyond 3x normal, signalling market makers withdrawing quotes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Optional

logger = logging.getLogger("market.order_book")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class DepthLevel:
    price: float
    quantity: int
    orders: int = 1


@dataclass
class OrderBookSnapshot:
    symbol: str
    ltp: float
    spread: float
    spread_pct: float
    total_bid_qty: int
    total_ask_qty: int
    obi_5: float  # -1.0 to +1.0
    obi_weighted: float  # -1.0 to +1.0 with distance decay
    bias: str  # "HEAVY_ACCUMULATION" | "BUY_LEAN" | "BALANCED" | "SELL_LEAN" | "HEAVY_DISTRIBUTION"
    iceberg_detected: bool = False
    iceberg_side: Optional[str] = None  # "BUY" | "SELL"
    iceberg_price: Optional[float] = None
    absorption_score: int = 50  # 0 to 100
    liquidity_status: str = "NORMAL"  # "NORMAL" | "SPREAD_SHOCK" | "THIN_BOOK"
    live_broker_connected: bool = False
    provenance: str = "LIVE_BROKER_L2"  # "LIVE_BROKER_L2" | "FEED_L1_DEPTH" | "SYNTHETIC_L1_DISCONNECTED" | "DISCONNECTED"
    bids: list[dict[str, Any]] = field(default_factory=list)
    asks: list[dict[str, Any]] = field(default_factory=list)
    captured_at: str = ""

    def __post_init__(self) -> None:
        if not self.captured_at:
            self.captured_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_order_book_metrics(
    symbol: str,
    raw_depth: dict[str, Any],
    ltp: float = 0.0,
    recent_trades_volume: Optional[float] = None,
    live_broker_connected: bool = False,
    provenance: str = "LIVE_BROKER_L2",
) -> OrderBookSnapshot:
    """
    Computes institutional microstructure metrics from standard broker 5-depth or 20-depth dict:
    raw_depth format:
      {
        "buy": [{"price": 100.5, "quantity": 500, "orders": 3}, ...],
        "sell": [{"price": 100.6, "quantity": 300, "orders": 2}, ...]
      }
    """
    bids_raw = raw_depth.get("buy", []) or raw_depth.get("bids", [])
    asks_raw = raw_depth.get("sell", []) or raw_depth.get("asks", [])

    bids = [
        DepthLevel(
            price=float(b.get("price", 0.0) or 0.0),
            quantity=int(b.get("quantity", 0) or 0),
            orders=int(b.get("orders", 1) or 1),
        )
        for b in bids_raw
        if float(b.get("price", 0.0) or 0.0) > 0
    ]

    asks = [
        DepthLevel(
            price=float(a.get("price", 0.0) or 0.0),
            quantity=int(a.get("quantity", 0) or 0),
            orders=int(a.get("orders", 1) or 1),
        )
        for a in asks_raw
        if float(a.get("price", 0.0) or 0.0) > 0
    ]

    # Best bid & best ask
    best_bid = bids[0].price if bids else ltp
    best_ask = asks[0].price if asks else ltp
    calc_ltp = (
        ltp if ltp > 0 else ((best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0)
    )

    spread = max(0.0, best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0.0
    spread_pct = round((spread / calc_ltp * 100), 3) if calc_ltp > 0 else 0.0

    tot_bid_qty = sum(b.quantity for b in bids)
    tot_ask_qty = sum(a.quantity for a in asks)
    tot_depth = tot_bid_qty + tot_ask_qty

    # 1. Simple OBI across available levels (typically 5 levels)
    if tot_depth > 0:
        obi_5 = round((tot_bid_qty - tot_ask_qty) / tot_depth, 3)
    else:
        obi_5 = 0.0

    # 2. Distance-Weighted OBI: Closer levels have higher weight (w_1=1.0, w_2=0.8, w_3=0.6, w_4=0.4, w_5=0.2)
    weights = [1.0, 0.8, 0.6, 0.4, 0.2]
    weighted_bid = sum(
        b.quantity * (weights[i] if i < len(weights) else 0.1) for i, b in enumerate(bids)
    )
    weighted_ask = sum(
        a.quantity * (weights[i] if i < len(weights) else 0.1) for i, a in enumerate(asks)
    )
    w_tot = weighted_bid + weighted_ask
    obi_weighted = round((weighted_bid - weighted_ask) / max(1.0, w_tot), 3) if w_tot > 0 else 0.0

    # 3. Bias classification
    if obi_weighted >= 0.55:
        bias = "HEAVY_ACCUMULATION"
    elif obi_weighted >= 0.20:
        bias = "BUY_LEAN"
    elif obi_weighted <= -0.55:
        bias = "HEAVY_DISTRIBUTION"
    elif obi_weighted <= -0.20:
        bias = "SELL_LEAN"
    else:
        bias = "BALANCED"

    # 4. Iceberg / Hidden Order Detection
    iceberg_detected = False
    iceberg_side = None
    iceberg_price = None
    absorption_score = int(min(100, max(0, 50 + int(obi_weighted * 50))))

    if recent_trades_volume is not None and recent_trades_volume > 0:
        # If traded volume on bid tick is > 3x average bid depth, hidden bid is absorbing
        avg_bid_depth = tot_bid_qty / max(1, len(bids))
        if (
            best_bid > 0
            and recent_trades_volume > (avg_bid_depth * 2.8)
            and best_bid >= calc_ltp * 0.999
        ):
            iceberg_detected = True
            iceberg_side = "BUY"
            iceberg_price = best_bid
            absorption_score = min(98, absorption_score + 25)
        elif best_ask > 0 and recent_trades_volume > ((tot_ask_qty / max(1, len(asks))) * 2.8):
            iceberg_detected = True
            iceberg_side = "SELL"
            iceberg_price = best_ask
            absorption_score = max(5, absorption_score - 25)

    # 5. Liquidity status check
    if spread_pct > 0.4:
        liq_status = "SPREAD_SHOCK"
    elif tot_depth < 100:
        liq_status = "THIN_BOOK"
    else:
        liq_status = "NORMAL"

    return OrderBookSnapshot(
        symbol=symbol,
        ltp=calc_ltp,
        spread=round(spread, 2),
        spread_pct=spread_pct,
        total_bid_qty=tot_bid_qty,
        total_ask_qty=tot_ask_qty,
        obi_5=obi_5,
        obi_weighted=obi_weighted,
        bias=bias,
        iceberg_detected=iceberg_detected,
        iceberg_side=iceberg_side,
        iceberg_price=iceberg_price,
        absorption_score=absorption_score,
        liquidity_status=liq_status,
        live_broker_connected=live_broker_connected,
        provenance=provenance,
        bids=[asdict(b) for b in bids],
        asks=[asdict(a) for a in asks],
    )


def analyze_symbol_order_book(symbol: str) -> OrderBookSnapshot:
    """
    Fetches real-time quote depth for symbol from active broker integration or market engine.
    Clearly marks whether live broker L2 feed is connected or falling back to synthetic tick L1.
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").replace("NFO:", "").strip().upper()
    try:
        from brokers.session import get_execution_broker

        brk = get_execution_broker()
        if brk and hasattr(brk, "get_quote"):
            q = brk.get_quote(clean_sym)
            if q and hasattr(q, "depth") and q.depth:
                return compute_order_book_metrics(
                    clean_sym,
                    q.depth,
                    getattr(q, "last_price", 0.0),
                    live_broker_connected=True,
                    provenance="LIVE_BROKER_L2",
                )
    except Exception as e:
        logger.debug("Failed fetching broker depth for %s: %s", clean_sym, e)

    # Fallback to market.quotes
    try:
        from market.quotes import get_quote

        q_dict = get_quote([f"NSE:{clean_sym}"])
        q = q_dict.get(f"NSE:{clean_sym}")
        if q:
            ltp = float(getattr(q, "last_price", 0.0) or 0.0)
            depth = getattr(q, "depth", None) or {}
            if depth:
                return compute_order_book_metrics(
                    clean_sym,
                    depth,
                    ltp,
                    live_broker_connected=False,
                    provenance="FEED_L1_DEPTH",
                )
            # Synthetic 1-level depth reconstruction from high/low/close if depth unavailable
            bid_p = round(ltp * 0.9995, 2)
            ask_p = round(ltp * 1.0005, 2)
            synth_depth = {
                "buy": [{"price": bid_p, "quantity": 1000, "orders": 5}],
                "sell": [{"price": ask_p, "quantity": 1000, "orders": 5}],
            }
            return compute_order_book_metrics(
                clean_sym,
                synth_depth,
                ltp,
                live_broker_connected=False,
                provenance="SYNTHETIC_L1_DISCONNECTED",
            )
    except Exception as e:
        logger.debug("Quote depth fallback error for %s: %s", clean_sym, e)

    return OrderBookSnapshot(
        symbol=clean_sym,
        ltp=0.0,
        spread=0.0,
        spread_pct=0.0,
        total_bid_qty=0,
        total_ask_qty=0,
        obi_5=0.0,
        obi_weighted=0.0,
        bias="BALANCED",
        liquidity_status="THIN_BOOK",
        live_broker_connected=False,
        provenance="DISCONNECTED",
    )
