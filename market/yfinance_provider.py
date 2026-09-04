"""
market/yfinance_provider.py
───────────────────────────
Free market data via Yahoo Finance — no broker login required.

Provides:
  - Historical OHLCV (daily, weekly — 20+ years of history)
  - Live quotes (~15 min delayed)
  - Index data (NIFTY 50, BANKNIFTY, SENSEX, India VIX)
  - Basic fundamentals (PE, market cap, sector)

Usage:
    from market.yfinance_provider import yf_get_quote, yf_get_ohlcv, yf_get_ltp

    # Live quote
    quote = yf_get_quote("RELIANCE")

    # Historical data
    df = yf_get_ohlcv("RELIANCE", period="1y", interval="1d")

    # LTP
    price = yf_get_ltp("RELIANCE")

Symbol mapping:
    NSE stocks  → append ".NS"  (RELIANCE → RELIANCE.NS)
    BSE stocks  → append ".BO"  (RELIANCE → RELIANCE.BO)
    NIFTY 50    → ^NSEI
    BANKNIFTY   → ^NSEBANK
    SENSEX      → ^BSESN
    India VIX   → ^INDIAVIX

Install:
    pip install yfinance
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from brokers.base import Quote


# ── Symbol mapping ───────────────────────────────────────────

# ── Symbol mapping ───────────────────────────────────────────

# Commodities continuous futures mapping for MCX / commodity tickers
_COMMODITY_MAP = {
    "GOLD": "GC=F",
    "GOLDM": "GC=F",
    "GOLDPETAL": "GC=F",
    "SILVER": "SI=F",
    "SILVERM": "SI=F",
    "SILVERMIC": "SI=F",
    "CRUDEOIL": "CL=F",
    "CRUDEOILM": "CL=F",
    "CRUDE": "CL=F",
    "BRENT": "BZ=F",
    "NATURALGAS": "NG=F",
    "NATGASMINI": "NG=F",
    "NATGAS": "NG=F",
    "COPPER": "HG=F",
    "ZINC": "ZNC=F",
    "ALUMINIUM": "ALI=F",
    "ALUMINUM": "ALI=F",
    "LEAD": "LED=F",
    "COTTON": "CT=F",
}

# CDS / Forex currency derivatives mapping
_CURRENCY_MAP = {
    "USDINR": "INR=X",
    "USD/INR": "INR=X",
    "EURINR": "EURINR=X",
    "EUR/INR": "EURINR=X",
    "GBPINR": "GBPINR=X",
    "GBP/INR": "GBPINR=X",
    "JPYINR": "JPYINR=X",
    "JPY/INR": "JPYINR=X",
}

# Index symbols that don't follow the .NS convention
_INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "^CNXFIN",
    "NIFTY FIN SERVICE": "^CNXFIN",
    "NIFTY FINANCIAL SERVICES": "^CNXFIN",
    "MIDCPNIFTY": "^CNXMIDCAP",
    "NIFTY MIDCAP 100": "^CNXMIDCAP",
    "NIFTY MIDCAP 50": "^NSEMDCP50",
    "NIFTY NEXT 50": "^NSMIDCP",
    "NIFTY 100": "^CNX100",
    "NIFTY 200": "^CNX200",
    "NIFTY 500": "^CRSLDX",
    "NIFTY SMALLCAP 100": "^CNXSC",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "INDIA VIX": "^INDIAVIX",
    "INDIAVIX": "^INDIAVIX",
    "VIX": "^INDIAVIX",
    "NIFTY IT": "^CNXIT",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY INFRA": "^CNXINFRA",
    "NIFTY COMMODITIES": "^CNXCOMMODITIES",
    "NIFTY PSE": "^CNXPSE",
    "NIFTY PSU BANK": "^CNXPSUBANK",
    "NIFTY PRIVATE BANK": "^CNXPVTBANK",
}


# Crypto benchmark mapping
_CRYPTO_MAP = {
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "BTC-USD": "BTC-USD",
    "BTCINR": "BTC-INR",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
}


def _to_yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    """Convert NSE/BSE/MCX/Crypto symbol to Yahoo Finance ticker."""
    # Strip exchange prefix if present (e.g. "MCX:GOLD" → "GOLD", "NSE:RELIANCE" → "RELIANCE", "CRYPTO:BTC" → "BTC")
    if ":" in symbol:
        exchange, symbol = symbol.split(":", 1)

    upper = symbol.upper().strip()

    # Strip Fyers-specific suffixes before lookup
    if upper.endswith("-EQ"):
        upper = upper[:-3]
        symbol = symbol[:-3]
    elif upper.endswith("-INDEX"):
        upper = upper[:-6]
        symbol = symbol[:-6]
    elif upper.endswith("-FUT") or upper.endswith("FUT"):
        # Match base commodity if derivative contract e.g. GOLD24NOVFUT
        for c in _COMMODITY_MAP:
            if upper.startswith(c):
                return _COMMODITY_MAP[c]

    # 0. Check Crypto Map (BTC, ETH, SOL)
    if upper in _CRYPTO_MAP:
        return _CRYPTO_MAP[upper]

    # 1. Check Commodity Map (Gold, Silver, Crude Oil, Natural Gas, Copper, etc.)
    if upper in _COMMODITY_MAP:
        return _COMMODITY_MAP[upper]

    # 2. Check Currency Map (USD/INR, EUR/INR, GBP/INR, JPY/INR)
    if upper in _CURRENCY_MAP:
        return _CURRENCY_MAP[upper]

    # 3. Check Index Map (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, sectoral indices)
    if upper in _INDEX_MAP:
        return _INDEX_MAP[upper]

    # 4. Check exchange overrides
    exch_upper = (exchange or "NSE").upper().strip()
    if exch_upper in ("CRYPTO", "BINANCE", "COINBASE"):
        if upper in _CRYPTO_MAP:
            return _CRYPTO_MAP[upper]
        if not upper.endswith("-USD") and not upper.endswith("-INR"):
            return f"{upper}-USD"
        return upper

    if exch_upper == "MCX":
        for c in _COMMODITY_MAP:
            if upper.startswith(c):
                return _COMMODITY_MAP[c]
        return upper

    if exch_upper in ("CDS", "FX", "FOREX"):
        if f"{upper}=X" in ("INR=X", "USDINR=X", "EURINR=X", "GBPINR=X", "JPYINR=X"):
            return f"{upper}=X"
        return upper

    if exch_upper == "BSE":
        return f"{symbol}.BO"
    return f"{symbol}.NS"


def _from_instrument(instrument: str) -> str:
    """Convert 'NSE:RELIANCE', 'MCX:GOLD', or 'NSE:RELIANCE-EQ' format to yfinance ticker."""
    if ":" in instrument:
        exchange, symbol = instrument.split(":", 1)
        if symbol.endswith("-EQ"):
            symbol = symbol[:-3]
        return _to_yf_symbol(symbol, exchange)
    return _to_yf_symbol(instrument)


# ── Lazy import ──────────────────────────────────────────────


def _get_yf():
    """Lazy import yfinance to avoid import overhead when not needed."""
    try:
        import yfinance as yf

        return yf
    except ImportError:
        raise RuntimeError(
            "yfinance not installed. Run: pip install yfinance\n"
            "This is needed for free market data without a broker login."
        )


# ── Quote functions ──────────────────────────────────────────


import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

_quote_cache_lock = threading.Lock()
_quote_cache: dict[str, tuple[float, Quote]] = {}  # key -> (timestamp, Quote)
_QUOTE_TTL_SECONDS = 300.0

# USD-denominated yfinance futures tickers mapped to their MCX contract quotation factor
# COMEX/NYMEX futures are quoted in US units (troy oz, lbs, barrels), whereas MCX quotes in Indian standard units:
# - GOLD: COMEX USD/troy oz (31.1035g) → MCX ₹ per 10 grams (factor = 10 / 31.1034768 ≈ 0.3215)
# - SILVER: COMEX USD/troy oz (31.1035g) → MCX ₹ per 1 kilogram (factor = 1000 / 31.1034768 ≈ 32.1507)
# - COPPER: COMEX USD/lb → MCX ₹ per 1 kilogram (1 kg = 2.20462 lbs, factor = 2.20462262)
# - CRUDEOIL: WTI USD/barrel → MCX ₹ per 1 barrel (factor = 1.0)
# - BRENT: Brent USD/barrel → MCX ₹ per 1 barrel (factor = 1.0)
# - NATURALGAS: NYMEX USD/MMBtu → MCX ₹ per 1 MMBtu (factor = 1.0)
_USD_COMMODITY_FACTORS: dict[str, float] = {
    "GC=F": 10.0 / 31.1034768,  # GOLD (USD/troy oz → ₹/10 grams)
    "SI=F": 1000.0 / 31.1034768,  # SILVER (USD/troy oz → ₹/1 kg)
    "HG=F": 2.20462262,  # COPPER (USD/lb → ₹/1 kg)
    "CL=F": 1.0,  # CRUDE OIL (USD/bbl → ₹/bbl)
    "BZ=F": 1.0,  # BRENT CRUDE OIL (USD/bbl → ₹/bbl)
    "NG=F": 1.0,  # NATURAL GAS (USD/MMBtu → ₹/MMBtu)
    "ZNC=F": 2.20462262,  # ZINC (USD/lb → ₹/1 kg)
    "ALI=F": 2.20462262,  # ALUMINIUM (USD/lb → ₹/1 kg)
    "LED=F": 2.20462262,  # LEAD (USD/lb → ₹/1 kg)
    "CT=F": 3.74786,  # COTTON (cents/lb → ₹/bale)
}

_usdinr_cache: dict[str, tuple[float, float]] = {}  # key -> (timestamp, rate)
_usdinr_lock = threading.Lock()
_USDINR_TTL = 60.0  # seconds


def _get_usdinr_rate() -> float:
    """Fetch a live USD/INR exchange rate, or fail rather than inventing one."""
    with _usdinr_lock:
        if "rate" in _usdinr_cache:
            ts, rate = _usdinr_cache["rate"]
            if time.time() - ts < _USDINR_TTL:
                return rate
    try:
        yf = _get_yf()
        t = yf.Ticker("INR=X")
        info = t.fast_info
        rate = float(info.get("lastPrice", 0) or info.get("last_price", 0) or 0)
        if not rate or rate < 60:
            # Fallback: try 1-day history
            hist = t.history(period="1d")
            rate = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
        if rate <= 60:
            raise RuntimeError("Live USD/INR rate is unavailable")
    except Exception as exc:
        raise RuntimeError("Live USD/INR rate is unavailable") from exc
    with _usdinr_lock:
        _usdinr_cache["rate"] = (time.time(), rate)
    return rate


def yf_get_quote(symbol: str, exchange: str = "NSE") -> Quote:
    """
    Get a live quote for a single stock/index with in-memory caching.
    ~15 min delayed for Indian markets when no broker is connected.
    MCX commodity prices are converted from USD to INR automatically.
    """
    cache_key = f"{exchange.upper()}:{symbol.upper()}"
    now = time.time()

    with _quote_cache_lock:
        if cache_key in _quote_cache:
            ts, cached_q = _quote_cache[cache_key]
            if now - ts < _QUOTE_TTL_SECONDS:
                return cached_q

    yf = _get_yf()
    ticker = _to_yf_symbol(symbol, exchange)

    try:
        t = yf.Ticker(ticker)
        info = t.fast_info

        last_price = float(info.get("lastPrice", 0) or info.get("last_price", 0) or 0)
        prev_close = float(info.get("previousClose", 0) or info.get("previous_close", 0) or 0)
        open_price = float(info.get("open", 0) or 0)
        day_high = float(info.get("dayHigh", 0) or info.get("day_high", 0) or 0)
        day_low = float(info.get("dayLow", 0) or info.get("day_low", 0) or 0)
        volume = int(info.get("lastVolume", 0) or info.get("last_volume", 0) or 0)

        # If fast_info is sparse, try history for today
        if not last_price:
            hist = t.history(period="1d")
            if not hist.empty:
                row = hist.iloc[-1]
                last_price = float(row.get("Close", 0))
                open_price = float(row.get("Open", 0))
                day_high = float(row.get("High", 0))
                day_low = float(row.get("Low", 0))
                volume = int(row.get("Volume", 0))

        # ── MCX Commodity USD → INR conversion with unit multiplier ────
        # yfinance returns USD-denominated prices for commodity futures
        # (CL=F, GC=F, etc.). MCX prices these in INR with standard Indian quotation units.
        if ticker in _USD_COMMODITY_FACTORS and last_price > 0:
            fx = _get_usdinr_rate() * _USD_COMMODITY_FACTORS[ticker]
            last_price = round(last_price * fx, 2)
            prev_close = round(prev_close * fx, 2) if prev_close else 0.0
            open_price = round(open_price * fx, 2) if open_price else 0.0
            day_high = round(day_high * fx, 2) if day_high else 0.0
            day_low = round(day_low * fx, 2) if day_low else 0.0
        # ─────────────────────────────────────────────────────────────────

        change = round(last_price - prev_close, 2) if prev_close else 0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        q = Quote(
            symbol=symbol,
            last_price=last_price,
            open=open_price,
            high=day_high,
            low=day_low,
            close=prev_close,
            volume=volume,
            change=change,
            change_pct=change_pct,
        )

        with _quote_cache_lock:
            _quote_cache[cache_key] = (now, q)

        return q
    except Exception as e:
        raise RuntimeError(f"yfinance quote failed for {symbol}: {e}") from e


def yf_get_quotes(instruments: list[str]) -> dict[str, Quote]:
    """
    Get quotes for multiple instruments in parallel with threadpool execution.
    Per-symbol isolation: one failing ticker doesn't drop the entire batch.
    """
    if not instruments:
        return {}

    result = {}
    missing = []
    now = time.time()

    # Fast path: in-memory cache lookup
    with _quote_cache_lock:
        for inst in instruments:
            norm_key = inst.upper()
            if norm_key in _quote_cache:
                ts, q = _quote_cache[norm_key]
                if now - ts < _QUOTE_TTL_SECONDS:
                    result[inst] = q
                    continue
            missing.append(inst)

    if not missing:
        return result

    def _fetch_single(inst_str: str) -> tuple[str, Optional[Quote]]:
        if ":" in inst_str:
            ex, sym = inst_str.split(":", 1)
        else:
            ex, sym = "NSE", inst_str
        if sym.endswith("-EQ"):
            sym = sym[:-3]
        try:
            return inst_str, yf_get_quote(sym, ex)
        except Exception:
            return inst_str, None

    max_workers = min(32, len(missing))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_single, inst): inst for inst in missing}
        for fut in as_completed(futures):
            try:
                inst_key, quote_obj = fut.result()
                if quote_obj:
                    result[inst_key] = quote_obj
            except Exception:
                pass

    return result


def yf_get_ltp(symbol: str, exchange: str = "NSE") -> float:
    """Get last traded price for a single symbol."""
    q = yf_get_quote(symbol, exchange)
    return q.last_price


# ── Historical OHLCV ─────────────────────────────────────────


def yf_get_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period: str = "1y",
) -> list[dict]:
    """
    Fetch historical OHLCV data from Yahoo Finance.

    Args:
        symbol:    NSE symbol (e.g. "RELIANCE")
        exchange:  "NSE" or "BSE"
        interval:  "1d", "1wk", "1mo", "5m", "15m", "1h"
        from_date: Start date (if provided, period is ignored)
        to_date:   End date (default: now)
        period:    yfinance period string: "1d","5d","1mo","3mo","6mo","1y","2y","5y","max"

    Returns:
        List of dicts with keys: date, open, high, low, close, volume
    """
    yf = _get_yf()
    ticker = _to_yf_symbol(symbol, exchange)

    # Map our interval names to yfinance format
    interval_map = {
        "day": "1d",
        "1d": "1d",
        "week": "1wk",
        "1wk": "1wk",
        "month": "1mo",
        "1mo": "1mo",
        "minute": "1m",
        "1m": "1m",
        "5minute": "5m",
        "5m": "5m",
        "15minute": "15m",
        "15m": "15m",
        "30minute": "30m",
        "30m": "30m",
        "60minute": "1h",
        "1h": "1h",
        "ONE_DAY": "1d",
    }
    yf_interval = interval_map.get(interval, interval)

    now = datetime.now()
    try:
        t = yf.Ticker(ticker)

        if from_date:
            clamped_from = from_date
            if yf_interval == "1m" and (now - from_date).days > 6:
                from datetime import timedelta

                clamped_from = now - timedelta(days=6)
            elif yf_interval in ("5m", "15m", "30m", "1h", "60m") and (now - from_date).days > 58:
                from datetime import timedelta

                clamped_from = now - timedelta(days=58)

            hist = t.history(
                start=clamped_from.strftime("%Y-%m-%d"),
                end=(to_date or now).strftime("%Y-%m-%d"),
                interval=yf_interval,
            )
        else:
            p = period
            if yf_interval == "1m" and p in ("1mo", "3mo", "6mo", "1y", "2y", "5y", "max"):
                p = "7d"
            elif yf_interval in ("5m", "15m", "30m", "1h", "60m") and p in (
                "3mo",
                "6mo",
                "1y",
                "2y",
                "5y",
                "max",
            ):
                p = "60d"
            hist = t.history(period=p, interval=yf_interval)

        if hist.empty:
            return []

        # ── MCX Commodity USD → INR conversion for OHLCV ────────────────
        needs_inr = ticker in _USD_COMMODITY_FACTORS
        fx = (_get_usdinr_rate() * _USD_COMMODITY_FACTORS[ticker]) if needs_inr else 1.0
        # ─────────────────────────────────────────────────────────────────

        rows = []
        for idx, row in hist.iterrows():
            rows.append(
                {
                    "date": idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
                    "open": round(float(row["Open"]) * fx, 2),
                    "high": round(float(row["High"]) * fx, 2),
                    "low": round(float(row["Low"]) * fx, 2),
                    "close": round(float(row["Close"]) * fx, 2),
                    "volume": int(row["Volume"]),
                }
            )
        return rows
    except Exception:
        return []


# ── Convenience ──────────────────────────────────────────────


def yf_available() -> bool:
    """Check if yfinance is installed."""
    try:
        import yfinance  # noqa: F401

        return True
    except ImportError:
        return False
