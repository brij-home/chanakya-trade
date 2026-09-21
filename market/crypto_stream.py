"""
market/crypto_stream.py
───────────────────────
Institutional 24x7 Real-Time Crypto Streaming Pipeline.

Ingests live tick-by-tick trades, best bid/offer (BBO), and OHLCV klines
from Binance's open public WebSocket streams (zero API key or KYC required).

Key Features:
  - 24x7 real-time market data across BTC, ETH, SOL, BNB
  - Microsecond in-memory quote caching for instant quant indicator calculation
  - Rolling in-memory candle buffer with REST bootstrapping on startup
  - Automatic reconnection with exponential backoff
  - Seamless integration with SMC (analysis/market_structure), quotes, and paper broker

Usage:
    from market.crypto_stream import crypto_stream

    # Start stream in background
    crypto_stream.start()

    # Instant live quote
    q = crypto_stream.get_quote("BTCUSDT")
    print(q.last_price, q.bid, q.ask)

    # OHLCV DataFrame for SMC or technical models
    df = crypto_stream.get_klines("BTCUSDT", interval="15m", limit=100)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from brokers.base import Quote
from market.http_pool import get_binance_client

logger = logging.getLogger(__name__)

# Supported core crypto pairs and canonical alias map
DEFAULT_CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

CRYPTO_ALIAS_MAP = {
    "BTC": "BTCUSDT",
    "BITCOIN": "BTCUSDT",
    "BTCUSD": "BTCUSDT",
    "BTC-USD": "BTCUSDT",
    "CRYPTO:BTC": "BTCUSDT",
    "CRYPTO:BITCOIN": "BTCUSDT",
    "CRYPTO:BTCUSD": "BTCUSDT",
    "CRYPTO:BTC-USD": "BTCUSDT",
    "CRYPTO:BTCUSDT": "BTCUSDT",
    "BTCUSDT": "BTCUSDT",
    "ETH": "ETHUSDT",
    "ETHEREUM": "ETHUSDT",
    "ETHUSD": "ETHUSDT",
    "ETH-USD": "ETHUSDT",
    "CRYPTO:ETH": "ETHUSDT",
    "CRYPTO:ETHEREUM": "ETHUSDT",
    "CRYPTO:ETHUSD": "ETHUSDT",
    "CRYPTO:ETH-USD": "ETHUSDT",
    "CRYPTO:ETHUSDT": "ETHUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOL": "SOLUSDT",
    "SOLANA": "SOLUSDT",
    "SOLUSD": "SOLUSDT",
    "SOL-USD": "SOLUSDT",
    "CRYPTO:SOL": "SOLUSDT",
    "CRYPTO:SOLANA": "SOLUSDT",
    "CRYPTO:SOLUSD": "SOLUSDT",
    "CRYPTO:SOL-USD": "SOLUSDT",
    "CRYPTO:SOLUSDT": "SOLUSDT",
    "SOLUSDT": "SOLUSDT",
    "BNB": "BNBUSDT",
    "BINANCECOIN": "BNBUSDT",
    "BNBUSD": "BNBUSDT",
    "BNB-USD": "BNBUSDT",
    "CRYPTO:BNB": "BNBUSDT",
    "CRYPTO:BNBUSDT": "BNBUSDT",
    "BNBUSDT": "BNBUSDT",
}

BINANCE_WS_URL = (
    "wss://stream.binance.com:9443/stream?streams="
    "btcusdt@ticker/ethusdt@ticker/solusdt@ticker/bnbusdt@ticker/"
    "btcusdt@bookTicker/ethusdt@bookTicker/solusdt@bookTicker/bnbusdt@bookTicker/"
    "btcusdt@kline_1m/ethusdt@kline_1m/solusdt@kline_1m/bnbusdt@kline_1m"
)

BINANCE_REST_KLINES = "https://api.binance.com/api/v3/klines"


def normalize_crypto_symbol(symbol: str) -> str:
    """Normalize any crypto alias into canonical Binance pair e.g. 'CRYPTO:BTC' -> 'BTCUSDT'."""
    clean = symbol.strip().upper()
    return CRYPTO_ALIAS_MAP.get(clean, clean.replace("CRYPTO:", "").replace("-USD", "USDT"))


class CryptoStreamManager:
    """
    Manages 24x7 real-time Binance WebSocket stream, candle maintenance,
    and instantaneous quote resolution.
    """

    def __init__(self, symbols: Optional[list[str]] = None) -> None:
        self.symbols = [s.upper() for s in (symbols or DEFAULT_CRYPTO_SYMBOLS)]
        self._lock = threading.Lock()
        self._running = False
        self._connected = False
        self._worker_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

        # Real-time state cache
        self._quotes: dict[str, Quote] = {}
        self._raw_ticks: dict[str, dict[str, Any]] = {}
        self._book_tickers: dict[str, dict[str, float]] = {}  # {symbol: {"bid": p, "ask": p}}

        # In-memory rolling candles: symbol -> deque of dicts
        self._klines: dict[str, deque] = {s: deque(maxlen=600) for s in self.symbols}
        self._last_tick_time: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected and self._running

    def start(self) -> None:
        """Start the background streaming worker."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._run_event_loop,
                name="CryptoStreamWorker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("CryptoStreamManager: started background thread.")

        # Bootstrap initial history asynchronously via thread pool
        threading.Thread(target=self._bootstrap_initial_klines, daemon=True).start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop background worker cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._connected = False

        if self._loop and self._loop.is_running():
            try:
                def _shutdown():
                    for t in asyncio.all_tasks(self._loop):
                        t.cancel()
                    self._loop.stop()

                self._loop.call_soon_threadsafe(_shutdown)
            except Exception:
                pass

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        logger.info("CryptoStreamManager: stopped.")

    def on_tick(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback invoked whenever a new tick or kline update occurs."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def _run_event_loop(self) -> None:
        """Background asyncio worker loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._stream_loop())
        except Exception as exc:
            logger.warning(f"CryptoStreamManager event loop terminated: {exc}")
        finally:
            self._loop.close()

    async def _stream_loop(self) -> None:
        """Main WebSocket loop with automated backoff and reconnects."""
        import websockets

        backoff = 1.0
        while self._running:
            try:
                logger.info(f"CryptoStreamManager: connecting to Binance streams...")
                async with websockets.connect(
                    BINANCE_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    with self._lock:
                        self._connected = True
                    backoff = 1.0
                    logger.info("CryptoStreamManager: WebSocket connected successfully.")

                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(msg)
                            self._handle_ws_message(data)
                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            pong_waiter = await ws.ping()
                            await asyncio.wait_for(pong_waiter, timeout=10.0)
            except Exception as e:
                with self._lock:
                    self._connected = False
                if not self._running:
                    break
                logger.warning(f"CryptoStreamManager: WS connection dropped ({e}), retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    def _handle_ws_message(self, data: dict[str, Any]) -> None:
        """Dispatch incoming WebSocket message to appropriate parser."""
        stream = data.get("stream", "")
        payload = data.get("data", {})
        if not payload:
            return

        now_ts = time.time()
        self._last_tick_time = now_ts

        # 1. 24h Ticker Stream: <symbol>@ticker
        if "@ticker" in stream:
            self._process_ticker_payload(payload, now_ts)

        # 2. Best Bid / Offer: <symbol>@bookTicker
        elif "@bookTicker" in stream:
            self._process_book_ticker_payload(payload, now_ts)

        # 3. Candlestick Stream: <symbol>@kline_1m
        elif "@kline" in stream:
            self._process_kline_payload(payload, now_ts)

    def _process_ticker_payload(self, p: dict[str, Any], now_ts: float) -> None:
        sym = p.get("s", "").upper()
        if not sym:
            return

        ltp = float(p.get("c", 0.0))
        change = float(p.get("p", 0.0))
        change_pct = float(p.get("P", 0.0))
        high = float(p.get("h", 0.0))
        low = float(p.get("l", 0.0))
        vol = float(p.get("v", 0.0))
        open_price = float(p.get("o", 0.0))
        prev_close = ltp - change

        # Extract best bid/ask if available in ticker payload
        bid = float(p.get("b", 0.0)) if p.get("b") else None
        ask = float(p.get("a", 0.0)) if p.get("a") else None

        quote = Quote(
            symbol=f"CRYPTO:{sym}",
            last_price=ltp,
            open=open_price,
            high=high,
            low=low,
            close=prev_close,
            volume=int(vol),
            bid=bid,
            ask=ask,
            change=change,
            change_pct=change_pct,
            provider="binance",
            source="STREAM",
            data_state="LIVE",
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._quotes[sym] = quote
            self._raw_ticks[sym] = {
                "symbol": sym,
                "inst": f"CRYPTO:{sym}",
                "ltp": ltp,
                "change": change,
                "change_pct": change_pct,
                "high": high,
                "low": low,
                "volume": vol,
                "timestamp": now_ts,
            }

        # Dispatch listeners
        self._notify_listeners(self._raw_ticks[sym])

    def _process_book_ticker_payload(self, p: dict[str, Any], now_ts: float) -> None:
        sym = p.get("s", "").upper()
        if not sym:
            return
        bid = float(p.get("b", 0.0))
        ask = float(p.get("a", 0.0))

        with self._lock:
            self._book_tickers[sym] = {"bid": bid, "ask": ask, "ts": now_ts}
            if sym in self._quotes:
                q = self._quotes[sym]
                q.bid = bid
                q.ask = ask

    def _process_kline_payload(self, p: dict[str, Any], now_ts: float) -> None:
        k = p.get("k", {})
        if not k:
            return
        sym = p.get("s", "").upper()
        start_time = int(k.get("t", 0))
        candle = {
            "date": pd.to_datetime(start_time, unit="ms"),
            "open": float(k.get("o", 0.0)),
            "high": float(k.get("h", 0.0)),
            "low": float(k.get("l", 0.0)),
            "close": float(k.get("c", 0.0)),
            "volume": float(k.get("v", 0.0)),
            "is_closed": bool(k.get("x", False)),
        }

        with self._lock:
            dq = self._klines[sym]
            if dq and dq[-1]["date"] == candle["date"]:
                # Update current forming candle
                dq[-1] = candle
            else:
                # New candle started
                dq.append(candle)

    def _notify_listeners(self, tick: dict[str, Any]) -> None:
        for cb in list(self._listeners):
            try:
                cb(tick)
            except Exception as e:
                logger.debug(f"Tick listener callback error: {e}")

    def _bootstrap_initial_klines(self) -> None:
        """REST bootstrapper: parallel-load 200 initial 1m klines per symbol for instant readiness."""
        def _fetch_one(sym: str) -> tuple[str, Any]:
            try:
                return sym, self.fetch_klines_rest(sym, interval="1m", limit=200)
            except Exception as exc:
                logger.warning(f"Initial klines bootstrap failed for {sym}: {exc}")
                return sym, None

        with ThreadPoolExecutor(
            max_workers=min(len(self.symbols), 4), thread_name_prefix="crypto-boot"
        ) as executor:
            futures = {executor.submit(_fetch_one, sym): sym for sym in self.symbols}
            for fut in as_completed(futures, timeout=20):
                sym, df = fut.result()
                if df is None or df.empty:
                    continue
                with self._lock:
                    dq = self._klines[sym]
                    existing_dates = {c["date"] for c in dq}
                    for _, row in df.iterrows():
                        d = row["date"]
                        if d not in existing_dates:
                            dq.append(
                                {
                                    "date": d,
                                    "open": float(row["open"]),
                                    "high": float(row["high"]),
                                    "low": float(row["low"]),
                                    "close": float(row["close"]),
                                    "volume": float(row["volume"]),
                                    "is_closed": True,
                                }
                            )

    def fetch_klines_rest(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 250,
    ) -> pd.DataFrame:
        """
        Fetch historical klines directly from Binance REST API (zero auth required).
        Intervals: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 1w.
        """
        canon_sym = normalize_crypto_symbol(symbol)
        binance_interval = interval.lower()
        if binance_interval in ("minute", "1min"):
            binance_interval = "1m"
        elif binance_interval in ("5minute", "5min"):
            binance_interval = "5m"
        elif binance_interval in ("15minute", "15min"):
            binance_interval = "15m"
        elif binance_interval in ("60minute", "hour", "1hour"):
            binance_interval = "1h"
        elif binance_interval in ("day", "1day"):
            binance_interval = "1d"

        params = {"symbol": canon_sym, "interval": binance_interval, "limit": min(limit, 1000)}
        try:
            client = get_binance_client()
            resp = client.get(BINANCE_REST_KLINES, params=params, timeout=8.0)
            if resp.status_code != 200:
                logger.warning(f"Binance REST klines returned {resp.status_code}: {resp.text[:200]}")
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            data = resp.json()

            rows = []
            for c in data:
                rows.append(
                    {
                        "date": pd.to_datetime(c[0], unit="ms"),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                )
            df = pd.DataFrame(rows)
            if not df.empty:
                df.set_index("date", inplace=True)
                df["date"] = df.index
            return df
        except Exception as e:
            logger.error(f"Error fetching Binance REST klines for {canon_sym}: {e}")
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """
        Instant sub-millisecond retrieval of cached Quote for a crypto pair.
        Supports 'BTC', 'BTCUSDT', 'CRYPTO:BTC', etc.
        """
        canon_sym = normalize_crypto_symbol(symbol)
        with self._lock:
            if canon_sym in self._quotes:
                return self._quotes[canon_sym]

        # If cache cold, try single fast REST ticker (reuse persistent Binance client)
        try:
            client = get_binance_client()
            resp = client.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                params={"symbol": canon_sym},
                timeout=4.0,
            )
            if resp.status_code == 200:
                p = resp.json()
                ltp = float(p.get("lastPrice", 0.0))
                chg = float(p.get("priceChange", 0.0))
                chg_pct = float(p.get("priceChangePercent", 0.0))
                high = float(p.get("highPrice", 0.0))
                low = float(p.get("lowPrice", 0.0))
                vol = float(p.get("volume", 0.0))
                open_p = float(p.get("openPrice", 0.0))
                quote = Quote(
                    symbol=f"CRYPTO:{canon_sym}",
                    last_price=ltp,
                    open=open_p,
                    high=high,
                    low=low,
                    close=ltp - chg,
                    volume=int(vol),
                    bid=float(p.get("bidPrice", 0.0)) or None,
                    ask=float(p.get("askPrice", 0.0)) or None,
                    change=chg,
                    change_pct=chg_pct,
                    provider="binance",
                    source="REST",
                    data_state="LIVE",
                    received_at=datetime.now(timezone.utc).isoformat(),
                )
                with self._lock:
                    self._quotes[canon_sym] = quote
                return quote
        except Exception as e:
            logger.debug(f"Fast REST fallback for crypto quote failed: {e}")
        return None

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Retrieve multiple quotes concurrently/from cache."""
        res = {}
        for s in symbols:
            q = self.get_quote(s)
            if q:
                res[s] = q
                res[f"CRYPTO:{normalize_crypto_symbol(s)}"] = q
        return res

    def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 250,
    ) -> pd.DataFrame:
        """
        Get OHLCV DataFrame for crypto analysis.
        Uses cached klines or fetches fresh history via REST.
        """
        canon_sym = normalize_crypto_symbol(symbol)

        # For 1m candles, check if we have enough rolling candles in memory
        if interval in ("1m", "minute"):
            with self._lock:
                candles = list(self._klines.get(canon_sym, []))
            if len(candles) >= min(limit, 100):
                df = pd.DataFrame(candles[-limit:])
                df.set_index("date", inplace=True)
                df["date"] = df.index
                return df

        # Otherwise fetch directly via REST API for instant verified multi-timeframe candles
        return self.fetch_klines_rest(canon_sym, interval=interval, limit=limit)

    def get_snapshot(self) -> dict[str, Any]:
        """Get full snapshot of all tracked crypto assets."""
        with self._lock:
            items = []
            for sym in self.symbols:
                q = self._quotes.get(sym)
                if q:
                    items.append(
                        {
                            "symbol": sym,
                            "display_name": sym.replace("USDT", ""),
                            "inst": f"CRYPTO:{sym}",
                            "category": "CRYPTO",
                            "ltp": q.last_price,
                            "change": q.change,
                            "change_pct": q.change_pct,
                            "high": q.high,
                            "low": q.low,
                            "volume": q.volume,
                            "bid": q.bid,
                            "ask": q.ask,
                            "direction": "up" if q.change_pct > 0 else ("down" if q.change_pct < 0 else "flat"),
                        }
                    )
            return {
                "status": "ONLINE" if self._connected else "OFFLINE",
                "count": len(items),
                "timestamp": self._last_tick_time or time.time(),
                "tickers": items,
            }

    def fetch_futures_metrics(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        Fetch live Binance Futures Open Interest, Mark Price, and 8h Funding Rate.
        Zero API key or authentication required.
        """
        canon_sym = normalize_crypto_symbol(symbol)
        oi_val = 0.0
        funding_rate = 0.0
        mark_price = 0.0
        index_price = 0.0
        next_funding_time = None

        try:
            client = get_binance_client()
            # 1. Open Interest
            r_oi = client.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": canon_sym},
                timeout=5.0,
            )
            if r_oi.status_code == 200:
                oi_val = float(r_oi.json().get("openInterest", 0.0))

            # 2. Premium Index & Funding Rate
            r_prem = client.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": canon_sym},
                timeout=5.0,
            )
            if r_prem.status_code == 200:
                prem_data = r_prem.json()
                funding_rate = float(prem_data.get("lastFundingRate", 0.0))
                mark_price = float(prem_data.get("markPrice", 0.0))
                index_price = float(prem_data.get("indexPrice", 0.0))
                next_funding_time = prem_data.get("nextFundingTime")
        except Exception as e:
            logger.debug(f"Futures metrics fetch failed for {canon_sym}: {e}")

        annualized_fr_pct = funding_rate * 3 * 365 * 100
        oi_usd_notional = oi_val * (mark_price or 1.0)

        if funding_rate <= -0.0002:
            fr_bias = "EXTREME_SHORT_CROWDED"
        elif funding_rate < 0.0:
            fr_bias = "SHORT_CROWDED"
        elif funding_rate >= 0.0003:
            fr_bias = "LONG_OVERHEATED"
        else:
            fr_bias = "NEUTRAL"

        return {
            "symbol": canon_sym,
            "open_interest_contracts": oi_val,
            "open_interest_usd": round(oi_usd_notional, 2),
            "mark_price": mark_price,
            "index_price": index_price,
            "funding_rate_8h": funding_rate,
            "funding_rate_pct": round(funding_rate * 100, 4),
            "annualized_funding_rate_pct": round(annualized_fr_pct, 2),
            "funding_bias": fr_bias,
            "next_funding_time": next_funding_time,
            "timestamp": time.time(),
        }

    def get_squeeze_metrics(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        Evaluate order flow and leverage positioning to generate an early squeeze warning.
        """
        f_data = self.fetch_futures_metrics(symbol)
        fr = f_data.get("funding_rate_8h", 0.0)

        if fr <= -0.0002:
            squeeze_signal = "SHORT_SQUEEZE_IMMINENT"
            signal_conviction = 88
            recommendation = (
                "Heavily short-crowded. Look for Bullish Liquidity Sweep or Demand OB bounce for violent upward squeeze."
            )
        elif fr <= -0.00005:
            squeeze_signal = "SHORT_SQUEEZE_POTENTIAL"
            signal_conviction = 75
            recommendation = "Shorts paying longs. Early absorption forming."
        elif fr >= 0.0004:
            squeeze_signal = "LONG_FLUSH_RISK"
            signal_conviction = 85
            recommendation = (
                "Longs overheated and overleveraged. Vulnerable to sudden cascade flush downward."
            )
        else:
            squeeze_signal = "NEUTRAL"
            signal_conviction = 50
            recommendation = "Funding equilibrium. Standard SMC structural levels apply."

        return {
            "symbol": f_data.get("symbol"),
            "squeeze_signal": squeeze_signal,
            "conviction": signal_conviction,
            "recommendation": recommendation,
            "futures_metrics": f_data,
        }


# Thread-safe global singleton
crypto_stream = CryptoStreamManager()
