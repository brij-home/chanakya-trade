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

import bisect
from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
import threading
from typing import Any, Optional, Union

from engine.ring_buffer import RollingTickBuffer

logger = logging.getLogger("market.order_book")

from config.constants import IST

_DEPTH_BOOKS: dict[str, BisectDepthBook] = {}
_DEPTH_LOCK = threading.Lock()


def get_depth_book(symbol: str, max_depth: int = 50) -> BisectDepthBook:
    """
    Retrieve or initialize the high-frequency in-memory BisectDepthBook for a symbol.
    Maintains L2/L3 order book state streamed directly via WebSocket feeds.
    """
    canonical = (
        str(symbol)
        .upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .replace("MCX:", "")
        .strip()
    )
    with _DEPTH_LOCK:
        if canonical not in _DEPTH_BOOKS:
            _DEPTH_BOOKS[canonical] = BisectDepthBook(max_depth=max_depth)
        return _DEPTH_BOOKS[canonical]


def clear_depth_books() -> None:
    """Clear all registered in-memory depth books (primarily for test isolation)."""
    with _DEPTH_LOCK:
        _DEPTH_BOOKS.clear()


@dataclass
class DepthLevel:
    price: float
    quantity: int
    orders: int = 1

    @property
    def qty(self) -> int:
        return self.quantity


class BisectDepthBook:
    """
    High-frequency L3 (up to 50 levels) depth book utilizing binary search insertion.

    Invariants:
      1. Bids maintained in strictly descending price order (index 0 = best bid).
      2. Asks maintained in strictly ascending price order (index 0 = best ask).
      3. Quantity <= 0 deletes the level in O(log K).
      4. Incremental running totals for total_bid_qty and total_ask_qty in O(1).
      5. Bounded capacity: keeps at most max_depth (e.g. 50) levels per side.
      6. Integrated RollingTickBuffer for O(1) online rolling VWAP & tick volatility.
    """

    def __init__(self, max_depth: int = 50, tick_buffer_capacity: int = 1000) -> None:
        self.max_depth = int(max_depth)
        # Bids stored as (-price, price, quantity, orders) so bisect_left sorts highest price first
        self._bids: list[tuple[float, float, int, int]] = []
        # Asks stored as (price, quantity, orders) so bisect_left sorts lowest price first
        self._asks: list[tuple[float, int, int]] = []
        self._total_bid_qty = 0
        self._total_ask_qty = 0
        self._tick_buffer = RollingTickBuffer(capacity=tick_buffer_capacity)

    def update_level(self, side: str, price: float, quantity: int, orders: int = 1) -> None:
        """Update or remove a price level in O(log K) + bounded O(K) where K <= 50."""
        p = float(price)
        q = int(quantity)
        o = int(orders)
        if p <= 0:
            return

        is_bid = str(side).upper() in ("BUY", "BID", "1")

        if is_bid:
            key = -p
            idx = bisect.bisect_left(self._bids, (key, p, -1, -1))
            if idx < len(self._bids) and self._bids[idx][1] == p:
                old_q = self._bids[idx][2]
                self._total_bid_qty -= old_q
                if q <= 0:
                    del self._bids[idx]
                else:
                    self._bids[idx] = (key, p, q, o)
                    self._total_bid_qty += q
            elif q > 0:
                self._bids.insert(idx, (key, p, q, o))
                self._total_bid_qty += q
                if len(self._bids) > self.max_depth:
                    evicted = self._bids.pop()
                    self._total_bid_qty -= evicted[2]
        else:
            idx = bisect.bisect_left(self._asks, (p, -1, -1))
            if idx < len(self._asks) and self._asks[idx][0] == p:
                old_q = self._asks[idx][1]
                self._total_ask_qty -= old_q
                if q <= 0:
                    del self._asks[idx]
                else:
                    self._asks[idx] = (p, q, o)
                    self._total_ask_qty += q
            elif q > 0:
                self._asks.insert(idx, (p, q, o))
                self._total_ask_qty += q
                if len(self._asks) > self.max_depth:
                    evicted = self._asks.pop()
                    self._total_ask_qty -= evicted[1]

    def batch_update(self, bids: list[dict[str, Any]], asks: list[dict[str, Any]]) -> None:
        """Batch update depth levels."""
        self.clear()
        for b in bids:
            p = float(b.get("price") or b.get("bp") or 0.0)
            q = int(b.get("quantity") or b.get("qty") or b.get("bq") or b.get("volume") or 0)
            o = int(b.get("orders") or b.get("ord") or b.get("bno") or 1)
            if p > 0 and q > 0:
                self.update_level("BUY", p, q, o)
        for a in asks:
            p = float(a.get("price") or a.get("sp") or 0.0)
            q = int(a.get("quantity") or a.get("qty") or a.get("sq") or a.get("volume") or 0)
            o = int(a.get("orders") or a.get("ord") or a.get("sno") or 1)
            if p > 0 and q > 0:
                self.update_level("SELL", p, q, o)

    @property
    def best_bid(self) -> float:
        return self._bids[0][1] if self._bids else 0.0

    @property
    def best_ask(self) -> float:
        return self._asks[0][0] if self._asks else 0.0

    @property
    def spread(self) -> float:
        if self._bids and self._asks:
            return max(0.0, self.best_ask - self.best_bid)
        return 0.0

    @property
    def mid_price(self) -> float:
        """Arithmetic midpoint of best bid and best ask."""
        if self._bids and self._asks:
            return (self.best_bid + self.best_ask) / 2.0
        return self.best_bid or self.best_ask or 0.0

    @property
    def micro_price(self) -> float:
        """Volume-weighted micro-price based on top of book."""
        if not self._bids or not self._asks:
            return self.best_bid or self.best_ask or 0.0
        bb = self.best_bid
        ba = self.best_ask
        bq = self._bids[0][2]
        aq = self._asks[0][1]
        denom = bq + aq
        if denom <= 0:
            return (bb + ba) / 2.0
        return (bb * aq + ba * bq) / denom

    @property
    def total_bid_qty(self) -> int:
        return self._total_bid_qty

    @property
    def total_ask_qty(self) -> int:
        return self._total_ask_qty

    @property
    def bids(self) -> list[DepthLevel]:
        return [DepthLevel(price=b[1], quantity=b[2], orders=b[3]) for b in self._bids]

    @property
    def asks(self) -> list[DepthLevel]:
        return [DepthLevel(price=a[0], quantity=a[1], orders=a[2]) for a in self._asks]

    def obi(self, n: int = 5) -> float:
        """Calculate Order Book Imbalance across top N levels."""
        top_bids = self._bids[:n]
        top_asks = self._asks[:n]
        b_vol = sum(b[2] for b in top_bids)
        a_vol = sum(a[1] for a in top_asks)
        tot = b_vol + a_vol
        if tot <= 0:
            return 0.0
        return round((b_vol - a_vol) / tot, 4)

    def get_imbalance(self, n: int = 5) -> float:
        """Alias for obi(n) to maintain backward-compatibility with OMS order preview."""
        return self.obi(n=n)

    def get_bids(self, n: int = 50) -> list[dict[str, Any]]:
        return [
            {"level": i + 1, "price": b[1], "quantity": b[2], "orders": b[3]}
            for i, b in enumerate(self._bids[:n])
        ]

    def get_asks(self, n: int = 50) -> list[dict[str, Any]]:
        return [
            {"level": i + 1, "price": a[0], "quantity": a[1], "orders": a[2]}
            for i, a in enumerate(self._asks[:n])
        ]

    def simulate_sweep(self, side: str, quantity: int) -> dict[str, Any]:
        """
        Simulate an aggressive market order sweeping the depth book up to 50 levels.

        Args:
            side: "BUY" (sweeps ask levels starting from lowest ask)
                  or "SELL" (sweeps bid levels starting from highest bid).
            quantity: Number of units/shares to execute.

        Returns:
            Dict containing:
              - requested_qty: original target quantity
              - filled_qty: total quantity filled by depth
              - unfilled_qty: shortfall if quantity exceeds available depth
              - sweep_vwap: volume-weighted average execution price
              - benchmark_price: best inside price (best ask for BUY, best bid for SELL)
              - slippage_abs: absolute difference between sweep_vwap and benchmark_price
              - slippage_bps: slippage in basis points (1 bps = 0.01%)
              - levels_swept: count of price tiers consumed
              - is_fully_fillable: True if filled_qty == requested_qty
              - price_impact: worst price level touched vs benchmark price
        """
        target_qty = int(quantity)
        if target_qty <= 0:
            return {
                "requested_qty": 0,
                "filled_qty": 0,
                "unfilled_qty": 0,
                "sweep_vwap": 0.0,
                "benchmark_price": 0.0,
                "slippage_abs": 0.0,
                "slippage_bps": 0.0,
                "levels_swept": 0,
                "is_fully_fillable": True,
                "price_impact": 0.0,
            }

        is_buy = str(side).upper() in ("BUY", "B", "1")
        levels = self._asks if is_buy else [(b[0], b[1], b[2], b[3]) for b in self._bids]

        if not levels:
            return {
                "requested_qty": target_qty,
                "filled_qty": 0,
                "unfilled_qty": target_qty,
                "sweep_vwap": 0.0,
                "benchmark_price": 0.0,
                "slippage_abs": 0.0,
                "slippage_bps": 0.0,
                "levels_swept": 0,
                "is_fully_fillable": False,
                "price_impact": 0.0,
            }

        benchmark_p = self.best_ask if is_buy else self.best_bid
        remaining = target_qty
        accum_cost = 0.0
        filled = 0
        levels_swept = 0
        worst_p = benchmark_p

        for lvl in levels:
            p = lvl[0] if is_buy else lvl[1]
            q = lvl[1] if is_buy else lvl[2]
            if q <= 0:
                continue

            levels_swept += 1
            worst_p = p
            take = min(remaining, q)
            accum_cost += p * take
            filled += take
            remaining -= take
            if remaining <= 0:
                break

        sweep_vwap = round(accum_cost / filled, 4) if filled > 0 else 0.0
        slippage_abs = round(abs(sweep_vwap - benchmark_p), 4) if filled > 0 else 0.0
        slippage_bps = (
            round((slippage_abs / benchmark_p) * 10000.0, 2)
            if benchmark_p > 0 and filled > 0
            else 0.0
        )
        price_impact = round(abs(worst_p - benchmark_p), 4)

        return {
            "side": "BUY" if is_buy else "SELL",
            "requested_qty": target_qty,
            "filled_qty": filled,
            "unfilled_qty": remaining,
            "sweep_vwap": sweep_vwap,
            "benchmark_price": benchmark_p,
            "slippage_abs": slippage_abs,
            "slippage_bps": slippage_bps,
            "levels_swept": levels_swept,
            "is_fully_fillable": remaining == 0,
            "price_impact": price_impact,
            "worst_price": worst_p,
        }

    def simulate_market_order(self, side: str, quantity: int) -> dict[str, Any]:
        """Alias for simulate_sweep for compatibility with pretrade validation."""
        return self.simulate_sweep(side=side, quantity=quantity)

    def record_tick(self, price: float, volume: int = 1, timestamp: Optional[float] = None) -> None:
        """Record a price/volume tick into the internal circular ring buffer in O(1)."""
        if price > 0:
            self._tick_buffer.append(price, volume, timestamp)

    @property
    def rolling_tick_vwap(self) -> float:
        """O(1) online rolling VWAP of recent ticks."""
        return self._tick_buffer.vwap

    @property
    def rolling_tick_volatility(self) -> float:
        """O(1) online standard deviation of recent ticks via Welford algorithm."""
        return self._tick_buffer.std_dev

    def clear(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self._total_bid_qty = 0
        self._total_ask_qty = 0
        self._tick_buffer.clear()


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
    rolling_tick_vwap: Optional[float] = None
    rolling_tick_volatility: Optional[float] = None
    has_resting_wall: bool = False
    wall_side: Optional[str] = None  # "BID" | "ASK"
    wall_price: Optional[float] = None
    wall_qty: int = 0
    wall_ratio: float = 1.0
    greeks: Optional[dict[str, Any]] = None

    def simulate_sweep(self, side: str, quantity: int) -> dict[str, Any]:
        """Simulate pre-trade slippage and market sweep across snapshot depth."""
        book = BisectDepthBook(max_depth=50)
        book.batch_update(self.bids, self.asks)
        return book.simulate_sweep(side, quantity)

    def __post_init__(self) -> None:
        if not self.captured_at:
            self.captured_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_option_greeks(symbol: str, ltp: float = 0.0) -> Optional[dict[str, Any]]:
    """
    Resolve and compute option Greeks (delta, gamma, theta, vega, iv) if symbol is an option.
    Uses Black-Scholes analytical formulas with underlying spot resolution.
    """
    import re

    clean = (
        symbol.replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .replace("MCX:", "")
        .strip()
        .upper()
    )
    match = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)$", clean)
    if not match:
        return None
    try:
        from analysis.options import compute_greeks
        from market.quotes import get_quote

        strike = float(match.group(1))
        opt_type = match.group(2)
        prefix_part = clean[: match.start()].strip()
        und_match = re.match(r"^([A-Za-z0-9_&]+?)(?:\d{2}[A-Z]{3}|\d{2}\d{2}|\d{5})?$", prefix_part)
        und = (
            und_match.group(1).upper()
            if und_match
            else re.split(r"\d", prefix_part)[0].upper().strip()
        )
        if not und:
            und = "NIFTY"

        spot_p = strike
        try:
            spot_q = get_quote([und])
            q_obj = spot_q.get(und) if isinstance(spot_q, dict) else spot_q
            if q_obj and getattr(q_obj, "ltp", 0.0) > 0:
                spot_p = float(q_obj.ltp)
        except Exception as e_suppressed:
            logger.debug(f"[market.order_book] Spot quote lookup suppressed: {e_suppressed}")

        from datetime import date, timedelta

        today = date.today()
        days_to_thu = (3 - today.weekday()) % 7
        if days_to_thu == 0:
            days_to_thu = 7
        exp_date = (today + timedelta(days=days_to_thu)).isoformat()

        eval_ltp = (
            ltp
            if ltp > 0
            else max(
                0.5,
                abs(spot_p - strike)
                if (opt_type == "CE" and spot_p > strike) or (opt_type == "PE" and spot_p < strike)
                else 20.0,
            )
        )

        g = compute_greeks(
            spot=spot_p, strike=strike, expiry=exp_date, option_type=opt_type, ltp=eval_ltp
        )
        return {
            "delta": round(g.delta, 3),
            "gamma": round(g.gamma, 5),
            "theta": round(g.theta, 2),
            "vega": round(g.vega, 2),
            "iv_pct": round(g.iv_pct, 1),
            "spot": spot_p,
            "strike": strike,
            "option_type": opt_type,
            "dte": days_to_thu,
        }
    except Exception as e:
        logger.debug(f"[market.order_book] Failed computing Greeks for {symbol}: {e}")
        return None


def compute_order_book_metrics(
    symbol: str,
    raw_depth: Union[dict[str, Any], BisectDepthBook],
    ltp: float = 0.0,
    recent_trades_volume: Optional[float] = None,
    live_broker_connected: bool = False,
    provenance: str = "LIVE_BROKER_L2",
    greeks: Optional[dict[str, Any]] = None,
) -> OrderBookSnapshot:
    """
    Computes institutional microstructure metrics from standard broker 5-depth or 20-depth dict,
    or directly from a live streaming BisectDepthBook instance.
    raw_depth format (if dict):
      {
        "buy": [{"price": 100.5, "quantity": 500, "orders": 3}, ...],
        "sell": [{"price": 100.6, "quantity": 300, "orders": 2}, ...]
      }
    """
    if isinstance(raw_depth, BisectDepthBook):
        book = raw_depth
    else:
        bids_raw = raw_depth.get("buy", []) or raw_depth.get("bids", [])
        asks_raw = raw_depth.get("sell", []) or raw_depth.get("asks", [])
        book = BisectDepthBook(max_depth=50)
        book.batch_update(bids_raw, asks_raw)

    bids = [
        DepthLevel(
            price=b["price"],
            quantity=b["quantity"],
            orders=b["orders"],
        )
        for b in book.get_bids(50)
    ]

    asks = [
        DepthLevel(
            price=a["price"],
            quantity=a["quantity"],
            orders=a["orders"],
        )
        for a in book.get_asks(50)
    ]

    # Best bid & best ask
    best_bid = book.best_bid if book.best_bid > 0 else ltp
    best_ask = book.best_ask if book.best_ask > 0 else ltp
    calc_ltp = (
        ltp if ltp > 0 else ((best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0)
    )

    spread = book.spread if best_ask > 0 and best_bid > 0 else 0.0
    spread_pct = round((spread / calc_ltp * 100), 3) if calc_ltp > 0 else 0.0

    tot_bid_qty = book.total_bid_qty
    tot_ask_qty = book.total_ask_qty
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

    # 6. Resting fortress wall detection (>= 2.8x average depth)
    has_resting_wall = False
    wall_side = None
    wall_qty = 0
    wall_price = None
    wall_ratio = 1.0
    avg_bid_depth = tot_bid_qty / max(1, len(bids)) if bids else 0
    avg_ask_depth = tot_ask_qty / max(1, len(asks)) if asks else 0
    for b in bids:
        if avg_bid_depth > 0 and b.quantity / avg_bid_depth >= 2.8 and b.quantity >= 100:
            has_resting_wall = True
            wall_side = "BID"
            wall_qty = b.quantity
            wall_price = b.price
            wall_ratio = round(b.quantity / avg_bid_depth, 1)
            break
    if not has_resting_wall:
        for a in asks:
            if avg_ask_depth > 0 and a.quantity / avg_ask_depth >= 2.8 and a.quantity >= 100:
                has_resting_wall = True
                wall_side = "ASK"
                wall_qty = a.quantity
                wall_price = a.price
                wall_ratio = round(a.quantity / avg_ask_depth, 1)
                break

    # Record micro-price tick into book's RollingTickBuffer
    tick_p = book.micro_price if book.micro_price > 0 else calc_ltp
    if tick_p > 0:
        book.record_tick(tick_p, max(1, int(recent_trades_volume or 1)))

    rolling_vwap = round(book.rolling_tick_vwap, 4) if book.rolling_tick_vwap > 0 else None
    rolling_vol = (
        round(book.rolling_tick_volatility, 4) if book.rolling_tick_volatility > 0 else 0.0
    )

    if greeks is None:
        greeks = resolve_option_greeks(symbol, calc_ltp)

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
        rolling_tick_vwap=rolling_vwap,
        rolling_tick_volatility=rolling_vol,
        has_resting_wall=has_resting_wall,
        wall_side=wall_side,
        wall_price=wall_price,
        wall_qty=wall_qty,
        wall_ratio=wall_ratio,
        greeks=greeks,
    )


def analyze_symbol_order_book(
    symbol: str,
    *,
    allow_rest_fallback: bool = False,
) -> OrderBookSnapshot:
    """
    Fetches real-time quote depth for symbol from in-memory stream, active broker integration, or market engine.
    Prioritizes sub-millisecond in-memory streaming depth book populated by WebSocket ticks.

    Args:
        symbol: Ticker or canonical exchange symbol (e.g. "RELIANCE", "MCX:CRUDEOIL26NOVFUT").
        allow_rest_fallback: If False (institutional default), resolves strictly from RAM (WebSocket
            BisectDepthBook, TBT 50-level cache, or in-memory quote cache) with ZERO REST API consumption.
            Set to True only on deliberate single-symbol user requests.
    """
    is_mcx = symbol.upper().startswith("MCX:")
    is_bse = symbol.upper().startswith("BSE:")
    is_cds = symbol.upper().startswith("CDS:")
    clean_sym = (
        symbol.replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .strip()
        .upper()
    )
    if is_mcx or clean_sym.startswith(
        ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER", "ZINC", "ALUMINIUM")
    ):
        is_mcx = True
        query_sym = f"MCX:{clean_sym}" if not symbol.upper().startswith("MCX:") else symbol
        sym_to_report = query_sym
    elif is_cds or clean_sym.startswith(("USDINR", "EURINR", "GBPINR", "JPYINR")):
        is_cds = True
        query_sym = symbol if symbol.upper().startswith(("NSE:", "CDS:")) else f"NSE:{clean_sym}"
        sym_to_report = symbol if symbol.upper().startswith("CDS:") else f"CDS:{clean_sym}"
    else:
        query_sym = symbol if is_bse else clean_sym
        sym_to_report = clean_sym

    # 1. Fast in-memory check: Sub-millisecond live WebSocket streaming BisectDepthBook
    cached_book = get_depth_book(clean_sym)
    if not (cached_book.best_bid > 0 and cached_book.best_ask > 0):
        cached_book = get_depth_book(query_sym)
    if cached_book.best_bid > 0 and cached_book.best_ask > 0:
        stream_ltp = cached_book.rolling_tick_vwap or (
            (cached_book.best_bid + cached_book.best_ask) / 2.0
        )
        return compute_order_book_metrics(
            sym_to_report,
            cached_book,
            ltp=stream_ltp,
            live_broker_connected=True,
            provenance="LIVE_STREAM_L2",
        )

    # 1b. Check Fyers TBT 50-Level Depth cache (sub-millisecond L3 memory resolution, 0 REST calls)
    try:
        from market.fyers_tbt_manager import FyersTbtManager

        tbt = FyersTbtManager()
        with tbt._depth_lock:
            tbt_obj = (
                tbt._depth_cache.get(symbol)
                or tbt._depth_cache.get(query_sym)
                or tbt._depth_cache.get(clean_sym)
                or tbt._depth_cache.get(f"NSE:{clean_sym}")
                or tbt._depth_cache.get(f"BSE:{clean_sym}")
                or tbt._depth_cache.get(f"MCX:{clean_sym}")
                or tbt._depth_cache.get(f"CDS:{clean_sym}")
            )
        if tbt_obj and (tbt_obj.get("bids") or tbt_obj.get("asks")):
            raw_depth = {
                "buy": [
                    {"price": b["price"], "quantity": b["qty"], "orders": b.get("orders", 1)}
                    for b in tbt_obj.get("bids", [])
                ],
                "sell": [
                    {"price": a["price"], "quantity": a["qty"], "orders": a.get("orders", 1)}
                    for a in tbt_obj.get("asks", [])
                ],
            }
            return compute_order_book_metrics(
                sym_to_report,
                raw_depth,
                tbt_obj.get("ltp", 0.0),
                live_broker_connected=True,
                provenance="LIVE_STREAM_TBT_50",
            )
    except Exception as e_tbt:
        logger.debug(f"[market.order_book] TBT depth lookup suppressed: {e_tbt}")

    # 1c. Broker in-memory depth cache lookup (0 REST calls, checks RAM cache)
    try:
        from brokers.session import get_data_broker, get_execution_broker

        brk = None
        try:
            brk = get_data_broker()
        except Exception as e:
            logger.debug(f"[market.order_book] get_data_broker lookup suppressed: {e}")
        if not brk:
            try:
                brk = get_execution_broker()
            except Exception as e:
                logger.debug(f"[market.order_book] get_execution_broker lookup suppressed: {e}")
        if brk and hasattr(brk, "_depth_cache") and hasattr(brk, "_depth_cache_lock"):
            with brk._depth_cache_lock:
                cand_cached = (
                    brk._depth_cache.get(symbol)
                    or brk._depth_cache.get(query_sym)
                    or brk._depth_cache.get(clean_sym)
                    or brk._depth_cache.get(f"MCX:{clean_sym}")
                )
                if cand_cached:
                    ts, depth_dict = cand_cached
                    import time as _t

                    # Accept cached depth if within 30.0s
                    if (
                        (_t.monotonic() - ts) < 30.0
                        and depth_dict
                        and (depth_dict.get("bids") or depth_dict.get("buy"))
                    ):
                        raw_depth = {
                            "buy": depth_dict.get("bids") or depth_dict.get("buy", []),
                            "sell": depth_dict.get("asks") or depth_dict.get("sell", []),
                        }
                        return compute_order_book_metrics(
                            sym_to_report,
                            raw_depth,
                            depth_dict.get("ltp", 0.0),
                            live_broker_connected=True,
                            provenance=f"CACHED_{brk.name.upper()}_L2"
                            if hasattr(brk, "name")
                            else "CACHED_BROKER_L2",
                        )
    except Exception as e_cache:
        logger.debug(f"[market.order_book] Broker depth cache lookup error: {e_cache}")

    # 2. Broker REST fallback — ONLY if explicitly requested (e.g. single-symbol manual inspection)
    if allow_rest_fallback:
        try:
            from brokers.session import get_data_broker, get_execution_broker

            brk = None
            try:
                brk = get_data_broker()
            except Exception as e_suppressed:
                logger.debug(f"[market.order_book] Non-fatal exception suppressed: {e_suppressed}")
            if not brk:
                try:
                    brk = get_execution_broker()
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.order_book] Non-fatal exception suppressed: {e_suppressed}"
                    )

            if brk and hasattr(brk, "get_market_depth"):
                depth_dict = brk.get_market_depth(query_sym)
                if depth_dict and (depth_dict.get("bids") or depth_dict.get("buy")):
                    raw_depth = {
                        "buy": depth_dict.get("bids") or depth_dict.get("buy", []),
                        "sell": depth_dict.get("asks") or depth_dict.get("sell", []),
                    }
                    return compute_order_book_metrics(
                        sym_to_report,
                        raw_depth,
                        depth_dict.get("ltp", 0.0),
                        live_broker_connected=True,
                        provenance=f"LIVE_{brk.name.upper()}_L2"
                        if hasattr(brk, "name")
                        else "LIVE_BROKER_L2",
                    )

            if brk and hasattr(brk, "get_quote"):
                q = brk.get_quote(query_sym)
                if q and hasattr(q, "depth") and q.depth:
                    return compute_order_book_metrics(
                        sym_to_report,
                        q.depth,
                        getattr(q, "last_price", 0.0),
                        live_broker_connected=True,
                        provenance="LIVE_BROKER_L2",
                    )
        except Exception as e:
            logger.debug("Failed fetching broker depth for %s: %s", clean_sym, e)

    # 3. Fast in-memory quote / tick fallback (WS-only if allow_rest_fallback is False)
    try:
        from market.quotes import get_quote

        q_sym = symbol if is_mcx else (f"BSE:{clean_sym}" if is_bse else f"NSE:{clean_sym}")
        q_dict = get_quote([q_sym], ws_only=(not allow_rest_fallback))
        q = q_dict.get(q_sym) or q_dict.get(clean_sym)
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
            if ltp > 0:
                is_stream = getattr(q, "source", "") == "STREAM"
                return OrderBookSnapshot(
                    symbol=clean_sym,
                    ltp=ltp,
                    spread=0.0,
                    spread_pct=0.0,
                    total_bid_qty=0,
                    total_ask_qty=0,
                    obi_5=0.0,
                    obi_weighted=0.0,
                    bias="BALANCED",
                    liquidity_status="THIN_BOOK",
                    live_broker_connected=is_stream,
                    provenance="LIVE_STREAM_L1" if is_stream else "CACHED_L1",
                    greeks=resolve_option_greeks(clean_sym, ltp),
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
        greeks=resolve_option_greeks(clean_sym, 0.0),
    )


fetch_order_book_metrics = analyze_symbol_order_book
