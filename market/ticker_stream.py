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
    updated_ts: float = 0.0

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
        "symbol": "MIDCPNIFTY",
        "display_name": "MIDCAP NIFTY",
        "inst": "NSE:NIFTY MID SELECT",
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
        "symbol": "NATURALGAS",
        "display_name": "NATURAL GAS",
        "inst": "MCX:NATURALGAS",
        "category": "COMMODITY",
        "unit": "₹",
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
    {
        "symbol": "ETH",
        "display_name": "ETHEREUM",
        "inst": "CRYPTO:ETH",
        "category": "CRYPTO",
        "unit": "$",
    },
    {
        "symbol": "SOL",
        "display_name": "SOLANA",
        "inst": "CRYPTO:SOL",
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
        self._conflation_interval: float = 0.05  # 50ms (20 Hz max SSE broadcast rate)
        self._dirty_event = threading.Event()
        self._conflation_thread: Optional[threading.Thread] = None
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
            "naturalgas": TickerIndexItem(
                key="naturalgas",
                symbol="MCX:NATURALGAS",
                name="NATURAL GAS",
                category="COMMODITY",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="₹",
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
            "eth": TickerIndexItem(
                key="eth",
                symbol="CRYPTO:ETH",
                name="ETHEREUM",
                category="CRYPTO",
                price=0.0,
                change=0.0,
                change_pct=0.0,
                unit="$",
            ),
            "sol": TickerIndexItem(
                key="sol",
                symbol="CRYPTO:SOL",
                name="SOLANA",
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
            "NSE:NIFTYMIDCAP100-INDEX": "midcpnifty",
            "NSE:MIDCPNIFTY-INDEX": "midcpnifty",
            "NSE:MIDCAP100-INDEX": "midcpnifty",
            "26014": "midcpnifty",
            "MCX:CRUDEOIL": "crudeoil",
            "CRUDEOIL": "crudeoil",
            "MCX:NATURALGAS": "naturalgas",
            "NATURALGAS": "naturalgas",
            "NG=F": "naturalgas",
            "MCX:GOLD": "gold",
            "GOLD": "gold",
            "MCX:SILVER": "silver",
            "SILVER": "silver",
            "CRYPTO:BTC": "btc",
            "BTC": "btc",
            "BTCUSDT": "btc",
            "CRYPTO:BTCUSDT": "btc",
            "CRYPTO:ETH": "eth",
            "ETH": "eth",
            "ETHUSDT": "eth",
            "CRYPTO:ETHUSDT": "eth",
            "CRYPTO:SOL": "sol",
            "SOL": "sol",
            "SOLUSDT": "sol",
            "CRYPTO:SOLUSDT": "sol",
        }

        self._wire_websocket_listeners()

    def _wire_websocket_listeners(self) -> None:
        """Attach listeners to m.Stock and Fyers WebSocket managers."""
        # 1. m.Stock WS
        try:
            from market.mstock_websocket import mstock_ws

            mstock_ws.on_tick(self._on_mstock_tick)
        except Exception as exc:
            logger.warning(f"[TickerStream] Could not wire m.Stock WS listener: {exc}")

        # 2. Fyers WS
        try:
            from market.websocket import ws_manager

            ws_manager.on_tick(self._on_fyers_tick)
        except Exception as exc:
            logger.warning(f"[TickerStream] Could not wire Fyers WS listener: {exc}")

        # 3. Binance Crypto WS (24x7)
        try:
            from market.crypto_stream import crypto_stream

            crypto_stream.on_tick(self._on_crypto_tick)
        except Exception as exc:
            logger.warning(f"[TickerStream] Could not wire Crypto WS listener: {exc}")

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
            item.updated_ts = time.time()

            # Sync ribbon entry in real-time
            if hasattr(self, "_cached_ribbon_tickers") and self._cached_ribbon_tickers:
                for r in self._cached_ribbon_tickers:
                    if (
                        r.get("inst") == getattr(tick, "symbol", "")
                        or r.get("display_name") == item.name
                    ):
                        r["ltp"] = item.price
                        r["change"] = item.change
                        r["change_pct"] = item.change_pct
                        r["direction"] = (
                            "up"
                            if item.change_pct > 0
                            else ("down" if item.change_pct < 0 else "flat")
                        )

        self._schedule_conflated_notify()

    def _on_fyers_tick(self, tick: Any) -> None:
        """Handle live tick from Fyers WebSocket."""
        key = self._symbol_to_key.get(getattr(tick, "symbol", ""))
        if not key or key not in self._items:
            return

        with self._lock:
            item = self._items[key]
            # Prioritize mstock if it was received within the last 3 seconds
            now_ts = time.time()
            mstock_fresh = item.source == "MSTOCK_WS" and (now_ts - item.updated_ts <= 3.0)
            if not mstock_fresh:
                item.price = float(tick.ltp)
                item.change = float(getattr(tick, "change", 0.0))
                item.change_pct = float(getattr(tick, "change_pct", 0.0))
                if getattr(tick, "high", 0.0) > 0:
                    item.high = float(tick.high)
                if getattr(tick, "low", 0.0) > 0:
                    item.low = float(tick.low)
                item.source = "FYERS_WS"
                item.updated_at = datetime.now(timezone.utc).isoformat()
                item.updated_ts = now_ts

                # Sync ribbon entry in real-time
                if hasattr(self, "_cached_ribbon_tickers") and self._cached_ribbon_tickers:
                    for r in self._cached_ribbon_tickers:
                        if (
                            r.get("inst") == getattr(tick, "symbol", "")
                            or r.get("display_name") == item.name
                        ):
                            r["ltp"] = item.price
                            r["change"] = item.change
                            r["change_pct"] = item.change_pct
                            r["direction"] = (
                                "up"
                                if item.change_pct > 0
                                else ("down" if item.change_pct < 0 else "flat")
                            )

        self._schedule_conflated_notify()

    def _on_crypto_tick(self, tick: dict[str, Any]) -> None:
        """Handle live tick from Binance Crypto WebSocket."""
        sym = tick.get("symbol", "").upper()
        key = self._symbol_to_key.get(sym) or self._symbol_to_key.get(f"CRYPTO:{sym}")
        if not key or key not in self._items:
            return

        with self._lock:
            item = self._items[key]
            item.price = float(tick.get("ltp", 0.0))
            item.change = float(tick.get("change", 0.0))
            item.change_pct = float(tick.get("change_pct", 0.0))
            if float(tick.get("high", 0.0)) > 0:
                item.high = float(tick.get("high", 0.0))
            if float(tick.get("low", 0.0)) > 0:
                item.low = float(tick.get("low", 0.0))
            item.source = "BINANCE_WS"
            item.updated_at = datetime.now(timezone.utc).isoformat()
            item.updated_ts = time.time()

            # Sync ribbon entry in real-time
            if hasattr(self, "_cached_ribbon_tickers") and self._cached_ribbon_tickers:
                for r in self._cached_ribbon_tickers:
                    if r.get("display_name") == item.name or r.get("inst") == item.symbol:
                        r["ltp"] = item.price
                        r["change"] = item.change
                        r["change_pct"] = item.change_pct
                        r["direction"] = (
                            "up"
                            if item.change_pct > 0
                            else ("down" if item.change_pct < 0 else "flat")
                        )

        self._schedule_conflated_notify()

    def add_listener(self, listener: Callable[[list[dict]], None]) -> None:
        """Register a callback for real-time ticker updates."""
        self._listeners.append(listener)

    def _schedule_conflated_notify(self) -> None:
        """Mark state dirty for conflated SSE broadcast. If conflation thread is inactive, notifies directly."""
        if self._running and self._conflation_thread and self._conflation_thread.is_alive():
            self._dirty_event.set()
        else:
            self._notify_listeners()

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

    def is_ws_alive(self, max_staleness_seconds: float = 8.0) -> bool:
        """Check if any Indian market WS ticks have been received recently."""
        now = time.time()
        with self._lock:
            return any(
                "WS" in item.source and (now - item.updated_ts) <= max_staleness_seconds
                for item in self._items.values()
                if item.category == "INDIAN"
            )

    def refresh_indices_sync(self, force_ribbon: bool = False) -> None:
        """Fetch latest quotes for Indian and Global indices via REST feeds."""
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        ws_active = self.is_ws_alive()

        # 1. Ribbon Tickers (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, INDIA VIX, CRUDEOIL, GOLD, SILVER, BTC)
        # Skip heavy REST fetch if WebSockets are actively streaming Indian market data, unless forced or periodic fallback
        if force_ribbon or not ws_active:
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
                    "NATURALGAS": "naturalgas",
                    "GOLD": "gold",
                    "SILVER": "silver",
                    "BTC": "btc",
                    "ETH": "eth",
                    "SOL": "sol",
                }
                with self._lock:
                    for r in ribbon:
                        item_key = key_map.get(r.get("symbol"))
                        if item_key and item_key in self._items:
                            item = self._items[item_key]
                            # Don't overwrite higher-priority live WebSocket tick if recently updated (< 5.0s)
                            ws_fresh = "WS" in item.source and (now_ts - item.updated_ts <= 5.0)
                            if not ws_fresh:
                                item.price = float(r.get("ltp", 0.0) or 0.0)
                                item.change = float(r.get("change", 0.0) or 0.0)
                                item.change_pct = float(r.get("change_pct", 0.0) or 0.0)
                                if "WS" not in item.source:
                                    item.source = "LIVE_TICKER"
                                item.updated_at = now_iso
                                item.updated_ts = now_ts
            except Exception as e:
                logger.warning(f"[TickerStream] Ribbon tickers refresh error: {e}", exc_info=True)

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
                        item.updated_ts = now_ts
        except Exception as e:
            logger.warning(f"[TickerStream] Global macro refresh error: {e}", exc_info=True)

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
        """Start background polling thread for global/macro tickers with adaptive intervals and conflated SSE broadcaster."""
        if self._running:
            return
        self._running = True

        def _conflate_worker():
            logger.info(
                f"[TickerStream] Conflation worker started (interval={self._conflation_interval}s / {int(1.0 / self._conflation_interval)}Hz)"
            )
            while self._running:
                if self._dirty_event.wait(timeout=self._conflation_interval):
                    if not self._running:
                        break
                    self._dirty_event.clear()
                    try:
                        self._notify_listeners()
                    except Exception as e:
                        logger.warning(
                            f"[TickerStream] Conflation broadcast error: {e}", exc_info=True
                        )
                time.sleep(self._conflation_interval)
            logger.info("[TickerStream] Conflation worker stopped")

        self._conflation_thread = threading.Thread(
            target=_conflate_worker, daemon=True, name="TickerStreamConflater"
        )
        self._conflation_thread.start()

        def _poll_worker():
            logger.info(
                f"[TickerStream] Polling worker started (interval={poll_interval_seconds}s)"
            )
            last_macro_fetch = 0.0
            last_ribbon_reconcile = 0.0
            while self._running:
                try:
                    now = time.time()
                    ws_active = self.is_ws_alive()
                    # When WS is active: refresh macro every 15s, ribbon reconcile every 60s
                    # When WS is inactive: poll ribbon every 6s, macro every 10s to prevent REST thread starvation
                    ribbon_interval = 6.0 if not ws_active else 60.0
                    macro_interval = 15.0 if ws_active else 10.0
                    need_ribbon = (now - last_ribbon_reconcile) >= ribbon_interval
                    need_macro = (now - last_macro_fetch) >= macro_interval

                    if need_ribbon:
                        last_ribbon_reconcile = now
                    if need_macro:
                        last_macro_fetch = now

                    if need_ribbon or need_macro:
                        self.refresh_indices_sync(force_ribbon=need_ribbon)
                except Exception as e:
                    logger.warning(f"[TickerStream] Refresh worker error: {e}", exc_info=True)
                    if (
                        "interpreter shutdown" in str(e).lower()
                        or "cannot schedule new futures" in str(e).lower()
                    ):
                        break
                for _ in range(max(1, int(poll_interval_seconds * 10))):
                    if not self._running:
                        break
                    time.sleep(0.1)
            logger.info("[TickerStream] Polling worker stopped")

        self._worker_thread = threading.Thread(
            target=_poll_worker, daemon=True, name="TickerStreamWorker"
        )
        self._worker_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop background workers and join cleanly."""
        self._running = False
        self._dirty_event.set()
        if self._conflation_thread and self._conflation_thread.is_alive():
            try:
                self._conflation_thread.join(timeout=timeout)
            except Exception as exc:
                logger.warning(
                    f"[TickerStream] Error joining conflation thread: {exc}", exc_info=True
                )
        self._conflation_thread = None

        if self._worker_thread and self._worker_thread.is_alive():
            try:
                self._worker_thread.join(timeout=timeout)
            except Exception as exc:
                logger.warning(f"[TickerStream] Error joining worker thread: {exc}", exc_info=True)
        self._worker_thread = None


# Global singleton
ticker_stream = MarketTickerStream()
