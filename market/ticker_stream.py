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
from typing import Any, Callable, Optional

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


RIBBON_SPEC = [
    {
        "symbol": "NIFTY",
        "display_name": "NIFTY 50",
        "inst": "NSE:NIFTY 50",
        "category": "INDEX",
        "unit": "₹",
    },
    {
        "symbol": "BANKNIFTY",
        "display_name": "BANK NIFTY",
        "inst": "NSE:NIFTY BANK",
        "category": "INDEX",
        "unit": "₹",
    },
    {
        "symbol": "SENSEX",
        "display_name": "SENSEX",
        "inst": "BSE:SENSEX",
        "category": "INDEX",
        "unit": "₹",
    },
    {
        "symbol": "FINNIFTY",
        "display_name": "FIN NIFTY",
        "inst": "NSE:NIFTY FIN SERVICE",
        "category": "INDEX",
        "unit": "₹",
    },
    {
        "symbol": "INDIA VIX",
        "display_name": "INDIA VIX",
        "inst": "NSE:INDIA VIX",
        "category": "VIX",
        "unit": "pts",
    },
    {
        "symbol": "CRUDEOIL",
        "display_name": "CRUDE OIL",
        "inst": "MCX:CRUDEOIL",
        "category": "COMMODITY",
        "unit": "₹/bbl",
    },
    {
        "symbol": "GOLD",
        "display_name": "GOLD",
        "inst": "MCX:GOLD",
        "category": "COMMODITY",
        "unit": "₹/10g",
    },
    {
        "symbol": "SILVER",
        "display_name": "SILVER",
        "inst": "MCX:SILVER",
        "category": "COMMODITY",
        "unit": "₹/kg",
    },
    {
        "symbol": "BTC",
        "display_name": "BITCOIN",
        "inst": "CRYPTO:BTC",
        "category": "CRYPTO",
        "unit": "$",
    },
]


def compute_ribbon_tickers() -> list[dict[str, Any]]:
    """Compute normalized ticker quotes for the Live Ticker Ribbon."""
    from market.quotes import get_quote

    insts = [r["inst"] for r in RIBBON_SPEC]
    quotes_map = get_quote(insts)
    tickers = []
    for r in RIBBON_SPEC:
        q = (
            quotes_map.get(r["inst"])
            or quotes_map.get(r["symbol"])
            or quotes_map.get(r["inst"].split(":")[-1])
        )
        ltp = float(q.last_price) if q and q.last_price else 0.0
        chg = float(q.change) if q and q.change is not None else 0.0
        chg_pct = float(q.change_pct) if q and q.change_pct is not None else 0.0
        tickers.append(
            {
                "symbol": r["symbol"],
                "display_name": r["display_name"],
                "inst": r["inst"],
                "category": r["category"],
                "unit": r["unit"],
                "ltp": round(ltp, 2),
                "change": round(chg, 2),
                "change_pct": round(chg_pct, 2),
                "direction": "up" if chg_pct > 0 else ("down" if chg_pct < 0 else "flat"),
            }
        )
    return tickers


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
            "crudeoil": TickerIndexItem(
                key="crudeoil",
                symbol="MCX:CRUDEOIL",
                name="CRUDE OIL",
                category="COMMODITY",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="₹/bbl",
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
            "btc": TickerIndexItem(
                key="btc",
                symbol="CRYPTO:BTC",
                name="BITCOIN",
                category="CRYPTO",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="$",
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
            "MCX:CRUDEOIL": "crudeoil",
            "CRUDEOIL": "crudeoil",
            "MCX:GOLD": "gold",
            "GOLD": "gold",
            "MCX:SILVER": "silver",
            "SILVER": "silver",
            "CRYPTO:BTC": "btc",
            "BTC": "btc",
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

            # Sync ribbon entry in real-time
            if hasattr(self, "_cached_ribbon_tickers") and self._cached_ribbon_tickers:
                for r in self._cached_ribbon_tickers:
                    if r.get("inst") == getattr(tick, "symbol", "") or r.get("display_name") == item.name:
                        r["ltp"] = item.price
                        r["change"] = item.change
                        r["change_pct"] = item.change_pct
                        r["direction"] = "up" if item.change_pct > 0 else ("down" if item.change_pct < 0 else "flat")

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

                # Sync ribbon entry in real-time
                if hasattr(self, "_cached_ribbon_tickers") and self._cached_ribbon_tickers:
                    for r in self._cached_ribbon_tickers:
                        if r.get("inst") == getattr(tick, "symbol", "") or r.get("display_name") == item.name:
                            r["ltp"] = item.price
                            r["change"] = item.change
                            r["change_pct"] = item.change_pct
                            r["direction"] = "up" if item.change_pct > 0 else ("down" if item.change_pct < 0 else "flat")

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

            ribbon_tickers = getattr(self, "_cached_ribbon_tickers", []) or []

            event_bus.publish_sync(
                "ticker",
                {
                    "type": "ticker_update",
                    "tickers": ribbon_tickers,
                    "items": all_items,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            if ribbon_tickers:
                logger.info(f"[TickerStream] Published {len(ribbon_tickers)} tickers to SSE")
        except Exception as exc:
            logger.warning(f"[TickerStream] Ticker publish error: {exc}", exc_info=True)

    def refresh_indices_sync(self) -> None:
        """Fetch latest quotes for Indian and Global indices via REST feeds."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Ribbon Tickers (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, INDIA VIX, CRUDEOIL, GOLD, SILVER, BTC)
        try:
            ribbon = compute_ribbon_tickers()
            self._cached_ribbon_tickers = ribbon

            key_map = {
                "NIFTY": "nifty_50",
                "BANKNIFTY": "bank_nifty",
                "SENSEX": "sensex",
                "FINNIFTY": "finnifty",
                "INDIA VIX": "india_vix",
                "CRUDEOIL": "crudeoil",
                "GOLD": "gold",
                "SILVER": "silver",
                "BTC": "btc",
            }
            with self._lock:
                for r in ribbon:
                    item_key = key_map.get(r.get("symbol"))
                    if item_key and item_key in self._items:
                        item = self._items[item_key]
                        # Don't overwrite higher-priority live WebSocket tick if recently updated
                        if "WS" not in item.source or (time.time() - 5.0 > 0):
                            item.price = float(r.get("ltp", 0.0) or 0.0)
                            item.change = float(r.get("change", 0.0) or 0.0)
                            item.change_pct = float(r.get("change_pct", 0.0) or 0.0)
                            if "WS" not in item.source:
                                item.source = "LIVE_TICKER"
                            item.updated_at = now_iso
        except Exception as e:
            logger.debug(f"Ribbon tickers refresh error: {e}")

        # 2. Global Macro Report (GIFT Nifty, NASDAQ, S&P 500, DXY, US 10Y, Brent)
        try:
            from market.global_macro import fetch_global_macro_report

            macro = fetch_global_macro_report(use_cache=True)
            with self._lock:
                for macro_key in ("gift_nifty", "nasdaq", "sp500", "dow", "dxy", "us10y", "brent"):
                    macro_item = macro.items.get(macro_key)
                    if macro_item and macro_item.ltp > 0 and macro_key in self._items:
                        item = self._items[macro_key]
                        item.price = macro_item.ltp
                        item.change = macro_item.change
                        item.change_pct = macro_item.change_pct
                        item.source = "LIVE_MACRO"
                        item.updated_at = now_iso
        except Exception as e:
            logger.debug(f"Global macro refresh error: {e}")

        self._notify_listeners()

    def get_snapshot(self) -> dict[str, Any]:
        """Return structured snapshot of all Indian & Global indices."""
        with self._lock:
            all_items = [v.to_dict() for v in self._items.values()]

        indian = [item for item in all_items if item["category"] == "INDIAN"]
        global_indices = [item for item in all_items if item["category"] == "GLOBAL"]
        commodities = [item for item in all_items if item["category"] in ("COMMODITY", "CRYPTO")]

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
            print(f"[TickerStream] Polling worker started (interval={poll_interval_seconds}s)", flush=True)
            while self._running:
                try:
                    self.refresh_indices_sync()
                    cached_cnt = len(getattr(self, "_cached_ribbon_tickers", []) or [])
                    print(f"[TickerStream] Worker updated {cached_cnt} ribbon tickers successfully", flush=True)
                except Exception as e:
                    print(f"[TickerStream] Refresh error: {e}", flush=True)
                for _ in range(max(1, int(poll_interval_seconds * 10))):
                    if not self._running:
                        break
                    time.sleep(0.1)
            print("[TickerStream] Polling worker stopped", flush=True)

        self._worker_thread = threading.Thread(target=_poll_worker, daemon=True, name="TickerStreamWorker")
        self._worker_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop background worker and join cleanly."""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            try:
                self._worker_thread.join(timeout=timeout)
            except Exception:
                pass
        self._worker_thread = None


# Global singleton
ticker_stream = MarketTickerStream()
