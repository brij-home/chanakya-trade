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
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from brokers.base import Quote
from market.http_pool import get_binance_client

logger = logging.getLogger(__name__)

# Supported core crypto pairs and canonical alias map
DEFAULT_CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

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
    "XRP": "XRPUSDT",
    "RIPPLE": "XRPUSDT",
    "XRPUSD": "XRPUSDT",
    "XRP-USD": "XRPUSDT",
    "CRYPTO:XRP": "XRPUSDT",
    "CRYPTO:RIPPLE": "XRPUSDT",
    "CRYPTO:XRPUSDT": "XRPUSDT",
    "XRPUSDT": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "DOGECOIN": "DOGEUSDT",
    "DOGEUSD": "DOGEUSDT",
    "DOGE-USD": "DOGEUSDT",
    "CRYPTO:DOGE": "DOGEUSDT",
    "CRYPTO:DOGECOIN": "DOGEUSDT",
    "CRYPTO:DOGEUSDT": "DOGEUSDT",
    "DOGEUSDT": "DOGEUSDT",
}

BINANCE_WS_URL = (
    "wss://stream.binance.com:9443/stream?streams="
    "btcusdt@ticker/ethusdt@ticker/solusdt@ticker/bnbusdt@ticker/xrpusdt@ticker/dogeusdt@ticker/"
    "btcusdt@bookTicker/ethusdt@bookTicker/solusdt@bookTicker/bnbusdt@bookTicker/xrpusdt@bookTicker/dogeusdt@bookTicker/"
    "btcusdt@kline_1m/ethusdt@kline_1m/solusdt@kline_1m/bnbusdt@kline_1m/xrpusdt@kline_1m/dogeusdt@kline_1m"
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
                logger.info("CryptoStreamManager: connecting to Binance streams...")
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
                logger.warning(
                    f"CryptoStreamManager: WS connection dropped ({e}), retrying in {backoff:.1f}s..."
                )
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
        tot_vol = float(k.get("v", 0.0))
        buy_vol = float(k.get("V", 0.0)) if "V" in k else tot_vol * 0.5
        sell_vol = max(0.0, tot_vol - buy_vol)
        delta = buy_vol - sell_vol
        candle = {
            "date": pd.to_datetime(start_time, unit="ms"),
            "open": float(k.get("o", 0.0)),
            "high": float(k.get("h", 0.0)),
            "low": float(k.get("l", 0.0)),
            "close": float(k.get("c", 0.0)),
            "volume": tot_vol,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "delta": delta,
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
                logger.warning(
                    f"Binance REST klines returned {resp.status_code}: {resp.text[:200]}"
                )
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            data = resp.json()

            rows = []
            for c in data:
                tot_vol = float(c[5])
                buy_vol = float(c[9]) if len(c) > 9 else tot_vol * 0.5
                sell_vol = max(0.0, tot_vol - buy_vol)
                delta = buy_vol - sell_vol
                rows.append(
                    {
                        "date": pd.to_datetime(c[0], unit="ms"),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": tot_vol,
                        "buy_volume": buy_vol,
                        "sell_volume": sell_vol,
                        "delta": delta,
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
                            "direction": "up"
                            if q.change_pct > 0
                            else ("down" if q.change_pct < 0 else "flat"),
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
            recommendation = "Heavily short-crowded. Look for Bullish Liquidity Sweep or Demand OB bounce for violent upward squeeze."
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

    def get_order_flow_metrics(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "15m",
        limit: int = 60,
    ) -> dict[str, Any]:
        """
        Institutional Cumulative Volume Delta (CVD) & Order Flow Absorption Engine.
        Computes aggressive taker buy vs sell delta, cumulative delta slope,
        and identifies institutional absorption divergences.
        """
        canon_sym = normalize_crypto_symbol(symbol)
        df = self.get_klines(canon_sym, interval=interval, limit=limit)
        if df.empty or len(df) < 10:
            return {
                "symbol": canon_sym,
                "interval": interval,
                "status": "INSUFFICIENT_DATA",
                "current_delta": 0.0,
                "cvd": 0.0,
                "absorption_signal": "NONE",
                "delta_bias": "NEUTRAL",
                "bars": [],
            }

        # Ensure buy_volume, sell_volume, and delta columns exist
        if "buy_volume" not in df.columns or "delta" not in df.columns:
            tot_v = df["volume"]
            df["buy_volume"] = tot_v * 0.5
            df["sell_volume"] = tot_v * 0.5
            df["delta"] = 0.0

        df["cvd"] = df["delta"].cumsum()
        last_bar = df.iloc[-1]
        cur_close = float(last_bar["close"])
        cur_delta = float(last_bar["delta"])
        cur_vol = float(last_bar["volume"])
        cur_cvd = float(last_bar["cvd"])
        delta_ratio = cur_delta / max(1.0, cur_vol)

        # 1. Delta Bias
        if delta_ratio >= 0.25:
            delta_bias = "BULLISH_AGGRESSIVE"
        elif delta_ratio <= -0.25:
            delta_bias = "BEARISH_AGGRESSIVE"
        else:
            delta_bias = "NEUTRAL"

        # 2. CVD Trend over last 10 bars
        recent_10 = df.iloc[-10:]
        cvd_change_10 = float(recent_10["cvd"].iloc[-1] - recent_10["cvd"].iloc[0])
        price_change_10 = float(
            (recent_10["close"].iloc[-1] - recent_10["close"].iloc[0])
            / max(1e-6, recent_10["close"].iloc[0])
            * 100
        )
        cvd_trend = "RISING" if cvd_change_10 > 0 else ("FALLING" if cvd_change_10 < 0 else "FLAT")

        # 3. Absorption / Divergence Scanner
        absorption_signal = "NONE"
        conviction = 50
        absorption_note = "Order flow in equilibrium."

        if len(df) >= 20:
            p_prior = df.iloc[-25:-10]
            p_recent = df.iloc[-10:]

            p_prior_min = float(p_prior["low"].min())
            p_recent_min = float(p_recent["low"].min())
            cvd_prior_min = float(p_prior["cvd"].min())
            cvd_recent_min = float(p_recent["cvd"].min())

            p_prior_max = float(p_prior["high"].max())
            p_recent_max = float(p_recent["high"].max())
            cvd_prior_max = float(p_prior["cvd"].max())
            cvd_recent_max = float(p_recent["cvd"].max())

            # Bullish absorption: Price lower low, CVD higher low
            if p_recent_min < p_prior_min * 0.998 and cvd_recent_min > cvd_prior_min:
                absorption_signal = "BULLISH_CVD_ABSORPTION"
                conviction = 90
                absorption_note = (
                    f"Bullish Absorption: Price swept lows to ${p_recent_min:,.2f}, but CVD formed a higher low. "
                    "Aggressive sellers were absorbed by institutional passive limit bids."
                )
            # Bearish exhaustion: Price higher high, CVD lower high
            elif p_recent_max > p_prior_max * 1.002 and cvd_recent_max < cvd_prior_max:
                absorption_signal = "BEARISH_CVD_EXHAUSTION"
                conviction = 90
                absorption_note = (
                    f"Bearish Exhaustion: Price swept highs to ${p_recent_max:,.2f}, but CVD formed a lower high. "
                    "Aggressive buyers were absorbed by institutional passive limit offers."
                )
            # Immediate bar-level absorption
            elif cur_vol > float(df["volume"].iloc[-21:-1].mean()) * 1.5:
                if price_change_10 < -1.0 and delta_ratio > 0.15:
                    absorption_signal = "BULLISH_DELTA_ABSORPTION"
                    conviction = 86
                    absorption_note = "High-volume downward move where taker delta flipped positive (buyers absorbing supply)."
                elif price_change_10 > 1.0 and delta_ratio < -0.15:
                    absorption_signal = "BEARISH_DELTA_ABSORPTION"
                    conviction = 86
                    absorption_note = "High-volume upward move where taker delta flipped negative (sellers capping advance)."

        bars_summary = []
        for _, r in df.iloc[-15:].iterrows():
            bars_summary.append(
                {
                    "time": str(r["date"]),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                    "volume": round(float(r["volume"]), 2),
                    "buy_volume": round(float(r.get("buy_volume", 0.0)), 2),
                    "sell_volume": round(float(r.get("sell_volume", 0.0)), 2),
                    "delta": round(float(r.get("delta", 0.0)), 2),
                    "cvd": round(float(r.get("cvd", 0.0)), 2),
                }
            )

        return {
            "symbol": canon_sym,
            "interval": interval,
            "status": "ONLINE",
            "current_price": cur_close,
            "current_delta": round(cur_delta, 2),
            "current_volume": round(cur_vol, 2),
            "delta_ratio": round(delta_ratio, 3),
            "delta_bias": delta_bias,
            "cumulative_volume_delta": round(cur_cvd, 2),
            "cvd_trend": cvd_trend,
            "absorption_signal": absorption_signal,
            "conviction": conviction,
            "absorption_note": absorption_note,
            "recent_bars_count": len(df),
            "bars": bars_summary,
        }

    def get_liquidation_cascade_metrics(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        Institutional Liquidation Cascade & Flush Exhaustion Engine.
        Scans for extreme volume anomalies accompanied by long/short rejection wicks
        and Open Interest drain to identify high R:R counter-trend reversal entries.
        """
        canon_sym = normalize_crypto_symbol(symbol)
        f_data = self.fetch_futures_metrics(canon_sym)
        df = self.get_klines(canon_sym, interval="15m", limit=40)

        if df.empty or len(df) < 20:
            return {
                "symbol": canon_sym,
                "status": "INSUFFICIENT_DATA",
                "flush_signal": "NONE",
                "conviction": 50,
            }

        ltp = float(df["close"].iloc[-1])
        vol_series = df["volume"]
        avg_vol = float(vol_series.iloc[-21:-1].mean())
        cur_vol = float(vol_series.iloc[-1])
        rvol = round(cur_vol / max(1.0, avg_vol), 2) if avg_vol > 0 else 1.0

        # ATR calculation
        highs = df["high"]
        lows = df["low"]
        closes = df["close"]
        prev_closes = closes.shift(1).fillna(closes)
        tr = pd.concat(
            [highs - lows, (highs - prev_closes).abs(), (lows - prev_closes).abs()], axis=1
        ).max(axis=1)
        atr = float(tr.iloc[-15:-1].mean()) if len(tr) >= 15 else float(tr.mean())

        flush_signal = "NONE"
        conviction = 50
        recommendation = "Normal liquidity conditions."
        sl_price = 0.0
        t1_price = 0.0
        t2_price = 0.0

        for idx in (-1, -2):
            bar = df.iloc[idx]
            b_open = float(bar["open"])
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_close = float(bar["close"])
            b_vol = float(bar["volume"])
            b_rvol = b_vol / max(1.0, avg_vol) if avg_vol > 0 else 1.0
            rng = max(1e-6, b_high - b_low)
            lower_wick = min(b_open, b_close) - b_low
            upper_wick = b_high - max(b_open, b_close)
            lower_wick_ratio = lower_wick / rng
            upper_wick_ratio = upper_wick / rng

            prior_low = float(df["low"].iloc[-25:idx].min()) if len(df) >= 25 else b_low
            prior_high = float(df["high"].iloc[-25:idx].max()) if len(df) >= 25 else b_high

            # Long Liquidation Flush Reversal
            if (
                b_rvol >= 1.8
                and rng >= (1.2 * atr)
                and lower_wick_ratio >= 0.38
                and b_low <= prior_low
            ):
                flush_signal = "LONG_LIQUIDATION_FLUSH_REVERSAL"
                conviction = 92
                risk = max(0.5, (ltp - b_low) * 1.05)
                sl_price = round(b_low * 0.996, 2)
                t1_price = round(ltp + 2.5 * risk, 2)
                t2_price = round(ltp + 4.5 * risk, 2)
                recommendation = (
                    f"Cascading long liquidations flushed into ${b_low:,.2f} before violent wick reclaim "
                    f"({lower_wick_ratio * 100:.0f}% lower shadow, RVOL {b_rvol:.1f}x). Institutional buyers absorbed stops."
                )
                break

            # Short Squeeze Blowoff Reversal
            if (
                b_rvol >= 1.8
                and rng >= (1.2 * atr)
                and upper_wick_ratio >= 0.38
                and b_high >= prior_high
            ):
                flush_signal = "SHORT_SQUEEZE_BLOWOFF_REVERSAL"
                conviction = 92
                risk = max(0.5, (b_high - ltp) * 1.05)
                sl_price = round(b_high * 1.004, 2)
                t1_price = round(ltp - 2.5 * risk, 2)
                t2_price = round(ltp - 4.5 * risk, 2)
                recommendation = (
                    f"Overleveraged shorts liquidated on parabolic wick to ${b_high:,.2f} "
                    f"({upper_wick_ratio * 100:.0f}% upper shadow, RVOL {b_rvol:.1f}x). Exhaustion blow-off top."
                )
                break

        return {
            "symbol": canon_sym,
            "status": "ONLINE",
            "flush_signal": flush_signal,
            "conviction": conviction,
            "recommendation": recommendation,
            "rvol": rvol,
            "atr_14": round(atr, 2),
            "stop_loss": sl_price,
            "target_1": t1_price,
            "target_2": t2_price,
            "futures_metrics": f_data,
        }

    def get_basis_arbitrage_matrix(self) -> dict[str, Any]:
        """
        Institutional Delta-Neutral Basis & Funding Rate Arbitrage Engine.
        Scans all major crypto benchmarks (BTC, ETH, SOL, BNB, XRP, DOGE)
        for Cash-and-Carry (Long Spot + Short Perp) delta-neutral yield opportunities.
        """
        opportunities = []
        for sym in self.symbols:
            q = self.get_quote(sym)
            if not q or float(getattr(q, "last_price", 0.0) or 0.0) <= 0:
                continue

            spot = float(q.last_price)
            f_data = self.fetch_futures_metrics(sym)
            perp_price = float(f_data.get("mark_price", 0.0) or spot)
            fr = float(f_data.get("funding_rate_8h", 0.0) or 0.0)
            ann_yield = round(fr * 3 * 365 * 100, 2)
            basis_pct = round(((perp_price - spot) / spot) * 100, 3) if spot > 0 else 0.0
            daily_yield_pct = round(fr * 3 * 100, 3)

            # Determine opportunity regime
            if ann_yield >= 18.0:
                strategy = "CASH_AND_CARRY_PRIME"
                action = "BUY_SPOT_AND_SHORT_PERP"
                rating = "HIGH_YIELD"
                note = f"Delta-Neutral Cash & Carry: earn {ann_yield:.1f}% annualized APY paid every 8 hours with zero directional risk."
            elif ann_yield >= 10.0:
                strategy = "CASH_AND_CARRY_MODERATE"
                action = "BUY_SPOT_AND_SHORT_PERP"
                rating = "ATTRACTIVE"
                note = f"Moderate delta-neutral funding yield: {ann_yield:.1f}% annualized APY."
            elif ann_yield <= -12.0:
                strategy = "REVERSE_CASH_AND_CARRY"
                action = "BORROW_SELL_SPOT_AND_LONG_PERP"
                rating = "OPPORTUNITY"
                note = f"Deeply negative funding ({ann_yield:.1f}% APY): longs receive payments from short sellers."
            else:
                strategy = "NEUTRAL_EQUILIBRIUM"
                action = "MONITOR"
                rating = "BALANCED"
                note = f"Equilibrium funding ({ann_yield:.1f}% APY). Spread within normal market bounds."

            daily_usd_per_10k = round(10000 * (daily_yield_pct / 100.0), 2)

            opportunities.append(
                {
                    "symbol": sym,
                    "display_name": sym.replace("USDT", ""),
                    "spot_price": spot,
                    "perp_price": perp_price,
                    "basis_pct": basis_pct,
                    "funding_rate_8h_pct": round(fr * 100, 4),
                    "annualized_funding_yield_pct": ann_yield,
                    "daily_yield_pct": daily_yield_pct,
                    "daily_usd_per_10k": daily_usd_per_10k,
                    "strategy": strategy,
                    "action": action,
                    "rating": rating,
                    "note": note,
                    "open_interest_usd": f_data.get("open_interest_usd", 0.0),
                    "next_funding_time": f_data.get("next_funding_time"),
                }
            )

        opportunities.sort(key=lambda x: abs(x["annualized_funding_yield_pct"]), reverse=True)

        return {
            "status": "ONLINE",
            "pairs_scanned": len(opportunities),
            "timestamp": time.time(),
            "best_opportunity": opportunities[0] if opportunities else None,
            "matrix": opportunities,
        }


# Thread-safe global singleton
crypto_stream = CryptoStreamManager()
