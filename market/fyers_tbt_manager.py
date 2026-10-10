"""
market/fyers_tbt_manager.py
───────────────────────────
Fyers Institutional 50-Level Depth (Tick-By-Tick / TBT) Manager.

Manages high-frequency 50-level Depth of Market (DOM) streams using Fyers
TBT WebSocket (`fyers_apiv3.FyersWebsocket.tbt_ws.FyersTbtSocket`).

Features:
- Dynamic subscription to active Index Options / Target Stock Contracts
- 50-slot Order Book Imbalance (OBI-50) calculation
- Institutional Iceberg / Resting Liquidity Wall detection
- Book Density & Liquidity Quality scoring
- Pre-Trade VWAP Slippage modeling through 50 price levels
- Deep Order Book Audit Gatekeeper for setup conviction
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional, Set

from engine.ring_buffer import RollingTickBuffer

logger = logging.getLogger("market.fyers_tbt")


class FyersTbtManager:
    """Singleton manager for Fyers 50-level Tick-By-Tick (TBT) market depth."""

    _instance: Optional[FyersTbtManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> FyersTbtManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._ws: Any = None
        self._connected: bool = False
        self._access_token: str = ""
        self._app_id: str = ""
        self._thread: Optional[threading.Thread] = None
        self._subscribed: Set[str] = set()
        self._depth_cache: dict[str, dict[str, Any]] = {}
        self._depth_lock = threading.Lock()
        self._tick_buffers: dict[str, RollingTickBuffer] = {}
        self._callbacks: list[Callable[[str, dict[str, Any]], None]] = []
        self._initialized = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, access_token: str, app_id: str) -> None:
        """Start Fyers TBT WebSocket connection in a background thread."""
        if self._connected:
            return

        self._access_token = access_token
        self._app_id = app_id

        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        logger.info("Fyers 50-Depth TBT Socket background thread started")

    def stop(self, timeout: float = 1.0) -> None:
        """Gracefully disconnect the TBT WebSocket without blocking."""
        ws_to_close = self._ws
        self._connected = False
        self._ws = None

        if ws_to_close:

            def _close():
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    ws_obj = getattr(ws_to_close, "_FyersTbtSocket__ws_object", None)
                    if ws_obj and hasattr(ws_obj, "close"):
                        try:
                            ws_obj.close()
                        except Exception:
                            pass
                except Exception:
                    pass

            t = threading.Thread(target=_close, daemon=True)
            t.start()
            t.join(timeout=timeout)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _connect(self) -> None:
        try:
            from fyers_apiv3.FyersWebsocket.tbt_ws import FyersTbtSocket

            auth_token = (
                f"{self._app_id}:{self._access_token}"
                if ":" not in self._access_token
                else self._access_token
            )

            self._ws = FyersTbtSocket(
                access_token=auth_token,
                on_depth_update=self._handle_depth_update,
                on_connect=self._handle_connect,
                on_close=self._handle_close,
                on_error=self._handle_error,
                reconnect=True,
            )
            self._ws.connect()
        except ImportError:
            logger.warning("fyers_apiv3 TBT module unavailable")
        except Exception as e:
            logger.warning(f"Fyers TBT Socket connect failed: {e}")

    def _handle_connect(self, *args, **kwargs) -> None:
        self._connected = True
        logger.info("Fyers TBT Socket: Handshake confirmed")
        if self._subscribed:
            self._do_subscribe(self._subscribed)

    def _handle_close(self, *args, **kwargs) -> None:
        self._connected = False
        logger.info("Fyers TBT Socket: Disconnected")

    def _handle_error(self, err, *args, **kwargs) -> None:
        logger.debug(f"Fyers TBT Socket error: {err}")

    def _handle_depth_update(self, symbol: str, depth_obj: Any) -> None:
        """Process incoming 50-depth packet from Fyers TBT socket."""
        try:
            parsed = self._parse_depth_object(symbol, depth_obj)
            with self._depth_lock:
                self._depth_cache[symbol] = parsed
                clean_sym = symbol.split(":")[-1]
                self._depth_cache[clean_sym] = parsed

            for cb in self._callbacks:
                try:
                    cb(symbol, parsed)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Error parsing 50-depth packet for {symbol}: {e}")

    def _parse_depth_object(self, symbol: str, depth: Any) -> dict[str, Any]:
        """Convert SDK Depth protobuf object to structured institutional dict."""
        bid_prices = list(getattr(depth, "bidprice", []))
        ask_prices = list(getattr(depth, "askprice", []))
        bid_qtys = list(getattr(depth, "bidqty", []))
        ask_qtys = list(getattr(depth, "askqty", []))
        bid_orders = list(getattr(depth, "bidordn", []))
        ask_orders = list(getattr(depth, "askordn", []))

        bids = []
        asks = []
        tot_bid_q = 0
        tot_ask_q = 0

        for i in range(min(50, len(bid_prices))):
            bp = float(bid_prices[i] or 0.0)
            bq = int(bid_qtys[i] or 0)
            bo = int(bid_orders[i] or 0)
            if bp > 0 and bq > 0:
                bids.append({"level": i + 1, "price": bp, "qty": bq, "orders": bo})
                tot_bid_q += bq

        for i in range(min(50, len(ask_prices))):
            ap = float(ask_prices[i] or 0.0)
            aq = int(ask_qtys[i] or 0)
            ao = int(ask_orders[i] or 0)
            if ap > 0 and aq > 0:
                asks.append({"level": i + 1, "price": ap, "qty": aq, "orders": ao})
                tot_ask_q += aq

        tbq = int(getattr(depth, "tbq", tot_bid_q) or tot_bid_q)
        tsq = int(getattr(depth, "tsq", tot_ask_q) or tot_ask_q)

        # 50-level Order Book Imbalance ratio [-1.0 to +1.0]
        denom = tbq + tsq
        obi_50 = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        # Book Density Score: active populated levels out of 100 total slots
        active_slots = len(bids) + len(asks)
        density_score = round((active_slots / 100.0) * 100, 1)

        # Institutional Iceberg / Resting Liquidity Walls
        # Flag any level with quantity >= 3x the average level and >= 2,500 shares
        avg_bid_q = (tot_bid_q / max(1, len(bids))) if bids else 0
        avg_ask_q = (tot_ask_q / max(1, len(asks))) if asks else 0

        bid_walls = [b for b in bids if b["qty"] >= max(2500, avg_bid_q * 3.0) and b["level"] > 2]
        ask_walls = [a for a in asks if a["qty"] >= max(2500, avg_ask_q * 3.0) and a["level"] > 2]

        ltp = bids[0]["price"] if bids else (asks[0]["price"] if asks else 0.0)
        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0
        micro_price = (
            round(
                (bids[0]["price"] * asks[0]["qty"] + asks[0]["price"] * bids[0]["qty"])
                / max(1, bids[0]["qty"] + asks[0]["qty"]),
                4,
            )
            if bids and asks
            else ltp
        )

        # Update O(1) rolling tick buffer for micro-price tracking
        buf = self._tick_buffers.setdefault(symbol, RollingTickBuffer(capacity=100))
        if micro_price > 0:
            buf.append(micro_price, max(1, tbq + tsq))

        rolling_vwap = round(buf.vwap, 4) if buf.count > 0 else micro_price
        rolling_vol = round(buf.std_dev, 4) if buf.count > 1 else 0.0

        return {
            "symbol": symbol,
            "status": "LIVE",
            "timestamp": getattr(depth, "timestamp", int(time.time())),
            "ltp": ltp,
            "micro_price": micro_price,
            "rolling_tick_vwap": rolling_vwap,
            "rolling_tick_volatility": rolling_vol,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi_50,
            "density_score": density_score,
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": bid_walls,
            "ask_walls": ask_walls,
            "has_bid_wall": len(bid_walls) > 0,
            "has_ask_wall": len(ask_walls) > 0,
        }

    def subscribe(self, symbols: list[str]) -> None:
        # Filter out crypto symbols — Fyers TBT only handles Indian exchange instruments
        filtered = [
            s
            for s in symbols
            if not str(s).upper().startswith("CRYPTO:")
            and not str(s).upper().endswith("USDT")
            and str(s).upper() not in ("BTC", "ETH", "SOL", "BNB", "DOGE")
        ]
        if not filtered:
            return

        from brokers.fyers import _to_fyers_symbol

        formatted = {_to_fyers_symbol(s) for s in filtered}
        new_syms = formatted - self._subscribed
        if not new_syms:
            return

        self._subscribed.update(new_syms)
        if self._connected and self._ws:
            self._do_subscribe(new_syms)

    def _do_subscribe(self, symbols: Set[str]) -> None:
        try:
            from fyers_apiv3.FyersWebsocket.tbt_ws import SubscriptionModes

            self._ws.subscribe(
                symbol_tickers=symbols,
                channelNo="1",
                mode=SubscriptionModes.DEPTH,
            )
            logger.info(f"Fyers TBT 50-Depth: Subscribed to {len(symbols)} symbols")
        except Exception as e:
            logger.warning(f"Fyers TBT subscribe failed: {e}")

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols to keep bandwidth minimal."""
        from brokers.fyers import _to_fyers_symbol

        formatted = {_to_fyers_symbol(s) for s in symbols}
        to_remove = self._subscribed.intersection(formatted)
        if not to_remove:
            return

        self._subscribed.difference_update(to_remove)
        if self._connected and self._ws:
            try:
                self._ws.unsubscribe(symbols=to_remove, channelNo="1")
            except Exception:
                pass

    def get_50_depth(self, symbol: str) -> dict[str, Any]:
        """
        Retrieve latest cached 50-depth for symbol.
        Falls back seamlessly to L2 5-depth if TBT packet is not yet populated.
        """
        from brokers.fyers import _to_fyers_symbol

        fyers_sym = _to_fyers_symbol(symbol)
        clean = symbol.split(":")[-1]

        with self._depth_lock:
            if fyers_sym in self._depth_cache:
                return self._depth_cache[fyers_sym]
            if clean in self._depth_cache:
                return self._depth_cache[clean]

        # Seamless Fallback to Broker L2 5-depth REST API
        try:
            from brokers.session import get_data_broker

            brk = get_data_broker()
            if brk and hasattr(brk, "get_market_depth"):
                d = brk.get_market_depth(symbol)
                if d.get("status") == "ok":
                    return self._convert_l2_to_depth_format(symbol, d)
        except Exception:
            pass

        return {
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "message": "50-depth data stream awaiting live packets",
            "tbq": 0,
            "tsq": 0,
            "obi_50": 0.0,
            "density_score": 0.0,
            "bids": [],
            "asks": [],
            "bid_walls": [],
            "ask_walls": [],
        }

    def _convert_l2_to_depth_format(self, symbol: str, l2: dict[str, Any]) -> dict[str, Any]:
        """Convert standard 5-level broker depth into compatible DOM structure."""
        raw_bids = l2.get("bids", []) or []
        raw_asks = l2.get("asks", []) or []

        bids = [
            {
                "level": i + 1,
                "price": float(b.get("price", 0.0)),
                "qty": int(b.get("volume", b.get("qty", 0))),
                "orders": int(b.get("orders", 1)),
            }
            for i, b in enumerate(raw_bids[:5])
            if float(b.get("price", 0.0)) > 0
        ]
        asks = [
            {
                "level": i + 1,
                "price": float(a.get("price", 0.0)),
                "qty": int(a.get("volume", a.get("qty", 0))),
                "orders": int(a.get("orders", 1)),
            }
            for i, a in enumerate(raw_asks[:5])
            if float(a.get("price", 0.0)) > 0
        ]

        tbq = int(l2.get("total_buy_qty", sum(b["qty"] for b in bids)))
        tsq = int(l2.get("total_sell_qty", sum(a["qty"] for a in asks)))
        denom = tbq + tsq
        obi = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        ltp = float(l2.get("ltp", bids[0]["price"] if bids else 0.0))
        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0

        return {
            "symbol": symbol,
            "status": "L2_FALLBACK",
            "timestamp": int(time.time()),
            "ltp": ltp,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi,
            "density_score": round((len(bids) + len(asks)) / 10.0 * 100, 1),
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": [],
            "ask_walls": [],
            "has_bid_wall": False,
            "has_ask_wall": False,
        }

    def simulate_slippage(self, symbol: str, quantity: int, side: str = "BUY") -> dict[str, Any]:
        """
        Calculate volume-weighted fill price and slippage through the order book.
        """
        depth = self.get_50_depth(symbol)
        book = depth.get("asks", []) if side.upper() == "BUY" else depth.get("bids", [])
        if not book:
            return {"status": "UNAVAILABLE", "message": "Order book empty"}

        remaining = int(quantity)
        total_cost = 0.0
        levels_filled = 0
        top_price = book[0]["price"]

        for row in book:
            avail = row["qty"]
            price = row["price"]
            levels_filled += 1
            if remaining <= avail:
                total_cost += remaining * price
                remaining = 0
                break
            else:
                total_cost += avail * price
                remaining -= avail

        if remaining > 0:
            return {
                "status": "PARTIAL_FILL",
                "message": f"Order book exhausted. Remaining unfilled: {remaining} contracts",
                "requested_qty": quantity,
                "unfilled_qty": remaining,
            }

        vwap_fill = round(total_cost / max(1, quantity), 4)
        slippage_pts = round(abs(vwap_fill - top_price), 4)
        slippage_pct = round((slippage_pts / max(0.01, top_price)) * 100, 3)

        return {
            "status": "ok",
            "symbol": symbol,
            "side": side.upper(),
            "requested_qty": quantity,
            "top_of_book_price": top_price,
            "expected_vwap_price": vwap_fill,
            "estimated_slippage_pts": slippage_pts,
            "estimated_slippage_pct": slippage_pct,
            "depth_levels_swept": levels_filled,
        }

    def audit_candidate_depth(
        self,
        symbol: str,
        side: str = "BUY",
        lot_size: int = 65,
    ) -> dict[str, Any]:
        """
        Tier 2 Institutional 50-Depth Gatekeeper.
        Evaluates candidate setup quality, iceberg barriers, OBI-50, and liquidity density.
        """
        # Ensure symbol is registered for depth
        self.subscribe([symbol])
        depth = self.get_50_depth(symbol)

        is_buy = side.upper() in ("BUY", "LONG")
        obi = depth.get("obi_50", 0.0)
        density = depth.get("density_score", 0.0)
        ltp = depth.get("ltp", 0.0)

        findings = []
        penalties = 0
        bonuses = 0

        # 1. Order Book Imbalance (OBI-50)
        if is_buy:
            if obi >= 0.25:
                bonuses += 20
                findings.append(f"Strong bid absorption (OBI-50: +{obi:.2f})")
            elif obi <= -0.30:
                penalties += 35
                findings.append(f"Severe ask pressure overhead (OBI-50: {obi:.2f})")
        else:
            if obi <= -0.25:
                bonuses += 20
                findings.append(f"Strong ask distribution (OBI-50: {obi:.2f})")
            elif obi >= 0.30:
                penalties += 35
                findings.append(f"Strong bid support absorbing sells (OBI-50: +{obi:.2f})")

        # 2. Iceberg / Resting Wall Barrier Check
        ask_walls = depth.get("ask_walls", [])
        bid_walls = depth.get("bid_walls", [])

        if is_buy and ask_walls:
            # Check if wall is within 2.5% of LTP (immediate roadblock)
            near_walls = [w for w in ask_walls if ltp > 0 and w["price"] <= ltp * 1.025]
            if near_walls:
                penalties += 30
                findings.append(
                    f"Institutional Ask Wall capping upside at ₹{near_walls[0]['price']} ({near_walls[0]['qty']:,} contracts)"
                )
            else:
                bonuses += 5
                findings.append("No immediate institutional ask walls within +2.5%")
        elif not is_buy and bid_walls:
            near_bid_walls = [w for w in bid_walls if ltp > 0 and w["price"] >= ltp * 0.975]
            if near_bid_walls:
                penalties += 30
                findings.append(
                    f"Institutional Bid Floor blocking downside at ₹{near_bid_walls[0]['price']} ({near_bid_walls[0]['qty']:,} contracts)"
                )

        # 3. Density / Liquidity Quality Check
        if density < 15.0 and depth.get("status") != "L2_FALLBACK":
            penalties += 25
            findings.append(f"Thin order book density ({density:.1f}% slots filled)")
        else:
            bonuses += 10
            findings.append(f"Adequate book liquidity density ({density:.1f}%)")

        # 4. Slippage Check for 1 standard lot
        slip = self.simulate_slippage(symbol, quantity=lot_size, side=side)
        if slip.get("status") == "ok":
            slip_pct = slip.get("estimated_slippage_pct", 0.0)
            if slip_pct > 0.45:
                penalties += 20
                findings.append(f"High market order impact slippage ({slip_pct:.2f}%)")
            else:
                bonuses += 10
                findings.append(f"Minimal execution slippage ({slip_pct:.2f}%)")

        raw_score = 50 + bonuses - penalties
        final_conviction = max(0, min(100, raw_score))

        verdict = (
            "PASS"
            if final_conviction >= 65
            else ("CAUTION" if final_conviction >= 45 else "REJECT")
        )

        return {
            "symbol": symbol,
            "side": side.upper(),
            "verdict": verdict,
            "depth_conviction_score": final_conviction,
            "obi_50": obi,
            "density_score": density,
            "findings": findings,
            "audit_timestamp": int(time.time()),
        }


# Global Singleton Instance
fyers_tbt_manager = FyersTbtManager()
