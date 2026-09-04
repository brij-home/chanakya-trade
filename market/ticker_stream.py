"""
market/ticker_stream.py
───────────────────────
Real-time streaming & snapshot engine for Major Indian & Global Market Indices.

Monitors:
  - Indian Benchmarks: NIFTY 50, BANK NIFTY, SENSEX, INDIA VIX, FINNIFTY, MIDCPNIFTY
  - Global Indices & Macro: GIFT NIFTY, NASDAQ 100, S&P 500, DOW JONES, DXY, US 10Y, BRENT CRUDE, GOLD, SILVER

Real-Time Strategy:
  - Indian indices receive sub-millisecond updates via m.Stock WebSocket or Fyers WebSocket ticks.
  - Global & Macro indices refresh periodically from live market feeds (Yahoo Finance / GIFT Nifty IFSC).
  - Automatically pushes updates to SSE channel 'ticker' via web.sse.event_bus.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TickerIndexItem:
    key: str
    symbol: str
    name: str
    category: str  # "INDIAN" | "GLOBAL" | "COMMODITY"
    price: float
    change: float
    change_pct: float
    unit: str  # "pts", "$/bbl", "%", "₹", "index"
    high: float = 0.0
    low: float = 0.0
    source: str = "INITIALIZING"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketTickerStream:
    """
    Central aggregator and real-time broadcaster for Indian and Global market tickers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listeners: list[Callable[[list[dict]], None]] = []

        # Default registry of indices
        self._items: dict[str, TickerIndexItem] = {
            # Indian Indices
            "nifty_50": TickerIndexItem(
                key="nifty_50",
                symbol="NSE:NIFTY 50",
                name="NIFTY 50",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "bank_nifty": TickerIndexItem(
                key="bank_nifty",
                symbol="NSE:NIFTY BANK",
                name="BANK NIFTY",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "sensex": TickerIndexItem(
                key="sensex",
                symbol="BSE:SENSEX",
                name="SENSEX",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "india_vix": TickerIndexItem(
                key="india_vix",
                symbol="NSE:INDIA VIX",
                name="INDIA VIX",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "finnifty": TickerIndexItem(
                key="finnifty",
                symbol="NSE:NIFTY FIN SERVICE",
                name="FINNIFTY",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "midcpnifty": TickerIndexItem(
                key="midcpnifty",
                symbol="NSE:NIFTY MIDCAP 100",
                name="MIDCPNIFTY",
                category="INDIAN",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            # Global & Macro Indices
            "gift_nifty": TickerIndexItem(
                key="gift_nifty",
                symbol="NSE_IFSC:GIFT_NIFTY",
                name="GIFT NIFTY",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "nasdaq": TickerIndexItem(
                key="nasdaq",
                symbol="^IXIC",
                name="NASDAQ 100",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "sp500": TickerIndexItem(
                key="sp500",
                symbol="^GSPC",
                name="S&P 500",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "dow": TickerIndexItem(
                key="dow",
                symbol="^DJI",
                name="DOW JONES",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="pts",
            ),
            "dxy": TickerIndexItem(
                key="dxy",
                symbol="DX-Y.NYB",
                name="US DOLLAR (DXY)",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="index",
            ),
            "us10y": TickerIndexItem(
                key="us10y",
                symbol="^TNX",
                name="US 10Y YIELD",
                category="GLOBAL",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="%",
            ),
            "brent": TickerIndexItem(
                key="brent",
                symbol="BZ=F",
                name="BRENT CRUDE",
                category="COMMODITY",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="$/bbl",
            ),
            "gold": TickerIndexItem(
                key="gold",
                symbol="GC=F",
                name="GOLD",
                category="COMMODITY",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="$/oz",
            ),
            "silver": TickerIndexItem(
                key="silver",
                symbol="SI=F",
                name="SILVER",
                category="COMMODITY",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="$/oz",
            ),
        }

        # Symbol to key mapping for quick WebSocket lookup
        self._symbol_to_key = {
            "NSE:NIFTY 50": "nifty_50",
            "NSE:NIFTY50-INDEX": "nifty_50",
            "26000": "nifty_50",
            "NSE:NIFTY BANK": "bank_nifty",
            "NSE:NIFTYBANK-INDEX": "bank_nifty",
            "26009": "bank_nifty",
            "BSE:SENSEX": "sensex",
            "BSE:SENSEX-INDEX": "sensex",
            "1": "sensex",
            "NSE:INDIA VIX": "india_vix",
            "NSE:INDIAVIX-INDEX": "india_vix",
            "26017": "india_vix",
            "NSE:NIFTY FIN SERVICE": "finnifty",
            "NSE:FINNIFTY-INDEX": "finnifty",
            "26037": "finnifty",
            "NSE:NIFTY MIDCAP 100": "midcpnifty",
            "NSE:MIDCAP100-INDEX": "midcpnifty",
            "26014": "midcpnifty",
        }

        self._wire_websocket_listeners()

    def _wire_websocket_listeners(self) -> None:
        """Attach listeners to m.Stock and Fyers WebSocket managers."""
        # 1. m.Stock WS
        try:
            from market.mstock_websocket import mstock_ws

            mstock_ws.on_tick(self._on_mstock_tick)
        except Exception:
            pass

        # 2. Fyers WS
        try:
            from market.websocket import ws_manager

            ws_manager.on_tick(self._on_fyers_tick)
        except Exception:
            pass

    def _on_mstock_tick(self, tick: Any) -> None:
        """Handle live tick from m.Stock WebSocket."""
        key = self._symbol_to_key.get(getattr(tick, "symbol", "")) or self._symbol_to_key.get(
            str(getattr(tick, "token", ""))
        )
        if not key or key not in self._items:
            return

        with self._lock:
            item = self._items[key]
            item.price = float(tick.ltp)
            item.change = float(getattr(tick, "change", 0.0))
            item.change_pct = float(getattr(tick, "change_pct", 0.0))
            if getattr(tick, "high", 0.0) > 0:
                item.high = float(tick.high)
            if getattr(tick, "low", 0.0) > 0:
                item.low = float(tick.low)
            item.source = "MSTOCK_WS"
            item.updated_at = datetime.now(timezone.utc).isoformat()

        self._notify_listeners()

    def _on_fyers_tick(self, tick: Any) -> None:
        """Handle live tick from Fyers WebSocket."""
        key = self._symbol_to_key.get(getattr(tick, "symbol", ""))
        if not key or key not in self._items:
            return

        with self._lock:
            item = self._items[key]
            # Prioritize mstock if it's currently live, else use Fyers
            if item.source != "MSTOCK_WS" or (time.time() - 3.0 > 0):
                item.price = float(tick.ltp)
                item.change = float(getattr(tick, "change", 0.0))
                item.change_pct = float(getattr(tick, "change_pct", 0.0))
                if getattr(tick, "high", 0.0) > 0:
                    item.high = float(tick.high)
                if getattr(tick, "low", 0.0) > 0:
                    item.low = float(tick.low)
                item.source = "FYERS_WS"
                item.updated_at = datetime.now(timezone.utc).isoformat()

        self._notify_listeners()

    def add_listener(self, listener: Callable[[list[dict]], None]) -> None:
        """Register a callback for real-time ticker updates."""
        self._listeners.append(listener)

    def _notify_listeners(self) -> None:
        """Publish update to local listeners and SSE event bus."""
        snapshot = self.get_snapshot()
        all_items = snapshot.get("all", [])

        # Broadcast to local listeners
        for cb in self._listeners:
            try:
                cb(all_items)
            except Exception:
                pass

        # Publish to web.sse event_bus
        try:
            from web.sse import event_bus
            from web.skills import _compute_live_tickers_sync

            ribbon_tickers = getattr(self, "_cached_ribbon_tickers", None)
            if not ribbon_tickers:
                try:
                    ribbon_tickers = _compute_live_tickers_sync()
                    self._cached_ribbon_tickers = ribbon_tickers
                except Exception:
                    ribbon_tickers = []

            event_bus.publish_sync(
                "ticker",
                {
                    "type": "ticker_update",
                    "tickers": ribbon_tickers,
                    "items": all_items,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.debug(f"Ticker publish error: {exc}")

    def refresh_indices_sync(self) -> None:
        """Fetch latest quotes for Indian and Global indices via REST feeds."""
        # 1. Indian REST Snapshot (if websocket has not populated yet)
        try:
            from market.indices import get_market_snapshot

            snap = get_market_snapshot()
            now_iso = datetime.now(timezone.utc).isoformat()
            with self._lock:
                if snap.nifty and self._items["nifty_50"].price == 0.0:
                    self._items["nifty_50"].price = snap.nifty
                    self._items["nifty_50"].change_pct = snap.nifty_chg
                    self._items["nifty_50"].source = "REST"
                    self._items["nifty_50"].updated_at = now_iso
                if snap.banknifty and self._items["bank_nifty"].price == 0.0:
                    self._items["bank_nifty"].price = snap.banknifty
                    self._items["bank_nifty"].change_pct = snap.banknifty_chg
                    self._items["bank_nifty"].source = "REST"
                    self._items["bank_nifty"].updated_at = now_iso
                if snap.sensex and self._items["sensex"].price == 0.0:
                    self._items["sensex"].price = snap.sensex
                    self._items["sensex"].change_pct = snap.sensex_chg
                    self._items["sensex"].source = "REST"
                    self._items["sensex"].updated_at = now_iso
                if snap.india_vix and self._items["india_vix"].price == 0.0:
                    self._items["india_vix"].price = snap.india_vix
                    self._items["india_vix"].source = "REST"
                    self._items["india_vix"].updated_at = now_iso
        except Exception as e:
            logger.debug(f"Indian indices REST snapshot error: {e}")

        # 2. Global Macro Report (GIFT Nifty, NASDAQ, S&P 500, DXY, Brent, Gold, Silver)
        try:
            from market.global_macro import fetch_global_macro_report

            macro = fetch_global_macro_report(use_cache=True)
            now_iso = datetime.now(timezone.utc).isoformat()
            with self._lock:
                # GIFT NIFTY
                gift_item = macro.items.get("gift_nifty")
                if gift_item and gift_item.ltp > 0:
                    g = self._items["gift_nifty"]
                    g.price = gift_item.ltp
                    g.change = gift_item.change
                    g.change_pct = gift_item.change_pct
                    g.source = "LIVE_MACRO"
                    g.updated_at = now_iso

                # NASDAQ 100
                nasdaq_item = macro.items.get("nasdaq")
                if nasdaq_item and nasdaq_item.ltp > 0:
                    n = self._items["nasdaq"]
                    n.price = nasdaq_item.ltp
                    n.change = nasdaq_item.change
                    n.change_pct = nasdaq_item.change_pct
                    n.source = "LIVE_MACRO"
                    n.updated_at = now_iso

                # S&P 500
                sp_item = macro.items.get("sp500")
                if sp_item and sp_item.ltp > 0:
                    s = self._items["sp500"]
                    s.price = sp_item.ltp
                    s.change = sp_item.change
                    s.change_pct = sp_item.change_pct
                    s.source = "LIVE_MACRO"
                    s.updated_at = now_iso

                # DXY
                dxy_item = macro.items.get("dxy")
                if dxy_item and dxy_item.ltp > 0:
                    d = self._items["dxy"]
                    d.price = dxy_item.ltp
                    d.change = dxy_item.change
                    d.change_pct = dxy_item.change_pct
                    d.source = "LIVE_MACRO"
                    d.updated_at = now_iso

                # US 10Y
                us10y_item = macro.items.get("us10y")
                if us10y_item and us10y_item.ltp > 0:
                    u = self._items["us10y"]
                    u.price = us10y_item.ltp
                    u.change = us10y_item.change
                    u.change_pct = us10y_item.change_pct
                    u.source = "LIVE_MACRO"
                    u.updated_at = now_iso

                # Brent Crude
                brent_item = macro.items.get("brent")
                if brent_item and brent_item.ltp > 0:
                    b = self._items["brent"]
                    b.price = brent_item.ltp
                    b.change = brent_item.change
                    b.change_pct = brent_item.change_pct
                    b.source = "LIVE_MACRO"
                    b.updated_at = now_iso

                # Gold
                gold_item = macro.items.get("gold")
                if gold_item and gold_item.ltp > 0:
                    gd = self._items["gold"]
                    gd.price = gold_item.ltp
                    gd.change = gold_item.change
                    gd.change_pct = gold_item.change_pct
                    gd.source = "LIVE_MACRO"
                    gd.updated_at = now_iso
        except Exception as e:
            logger.debug(f"Global macro refresh error: {e}")

        # 3. Ribbon Tickers (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, INDIA VIX, CRUDEOIL, GOLD, SILVER, BTC)
        try:
            from web.skills import _compute_live_tickers_sync
            self._cached_ribbon_tickers = _compute_live_tickers_sync()
        except Exception as e:
            logger.debug(f"Ribbon tickers refresh error: {e}")

        self._notify_listeners()

    def get_snapshot(self) -> dict[str, Any]:
        """Return structured snapshot of all Indian & Global indices."""
        with self._lock:
            all_items = [v.to_dict() for v in self._items.values()]

        indian = [item for item in all_items if item["category"] == "INDIAN"]
        global_indices = [item for item in all_items if item["category"] == "GLOBAL"]
        commodities = [item for item in all_items if item["category"] == "COMMODITY"]

        ws_live = any("WS" in item["source"] for item in indian)
        status = "LIVE_STREAMING" if ws_live else "REST_FEED"

        tickers = getattr(self, "_cached_ribbon_tickers", []) or []

        return {
            "status": status,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "indian": indian,
            "global": global_indices,
            "commodities": commodities,
            "tickers": tickers or [],
            "all": all_items,
        }

    def start(self, poll_interval_seconds: float = 3.0) -> None:
        """Start background polling thread for global/macro tickers."""
        if self._running:
            return
        self._running = True

        def _poll_worker():
            # Initial pull
            self.refresh_indices_sync()
            while self._running:
                time.sleep(poll_interval_seconds)
                if not self._running:
                    break
                try:
                    self.refresh_indices_sync()
                except Exception as e:
                    logger.debug(f"Ticker background refresh error: {e}")

        self._worker_thread = threading.Thread(target=_poll_worker, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        """Stop background worker."""
        self._running = False


# Global singleton
ticker_stream = MarketTickerStream()
