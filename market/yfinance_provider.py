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
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "NIFTY FIN SERVICE": "NIFTY_FIN_SERVICE.NS",
    "NIFTY FINANCIAL SERVICES": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "NIFTY MIDCAP SELECT": "NIFTY_MID_SELECT.NS",
    "NIFTY MIDCAP 100": "^NSEMDCP50",
    "NIFTY MIDCAP 50": "^NSEMDCP50",
    "NIFTY NEXT 50": "^NSMIDCP",
    "NIFTYNXT50": "^NSMIDCP",
    "NEXT50": "^NSMIDCP",
    "NIFTY 100": "^CNX100",
    "NIFTY100": "^CNX100",
    "NIFTY 200": "^CNX200",
    "NIFTY200": "^CNX200",
    "NIFTY 500": "^CRSLDX",
    "NIFTY500": "^CRSLDX",
    "NIFTY SMALLCAP 100": "^CNXSC",
    "NIFTYSMLCAP100": "^CNXSC",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "BANKEX": "BSE-BANK.BO",
    "BSE BANKEX": "BSE-BANK.BO",
    "INDIA VIX": "^INDIAVIX",
    "INDIAVIX": "^INDIAVIX",
    "VIX": "^INDIAVIX",
    "NIFTY IT": "^CNXIT",
    "NIFTYIT": "^CNXIT",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTYREALTY": "^CNXREALTY",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTYENERGY": "^CNXENERGY",
    "NIFTY INFRA": "^CNXINFRA",
    "NIFTYINFRA": "^CNXINFRA",
    "NIFTY COMMODITIES": "^CNXCOMMODITIES",
    "NIFTYCOMMODITIES": "^CNXCOMMODITIES",
    "NIFTY PSE": "^CNXPSE",
    "NIFTYPSE": "^CNXPSE",
    "NIFTY PSU BANK": "^CNXPSUBANK",
    "NIFTY PSU": "^CNXPSUBANK",
    "NIFTYPSU": "^CNXPSUBANK",
    "NIFTY PRIVATE BANK": "NIFTY_PVT_BANK.NS",
    "NIFTY PVT BANK": "NIFTY_PVT_BANK.NS",
    "NIFTYPVTBANK": "NIFTY_PVT_BANK.NS",
    "NIFTY MEDIA": "^CNXMEDIA",
    "NIFTYMEDIA": "^CNXMEDIA",
    "MEDIA": "^CNXMEDIA",
    "NIFTY CONSUMPTION": "^CNXCONSUMP",
    "NIFTYCONSUMPTION": "^CNXCONSUMP",
    "NIFTY HEALTHCARE": "^CNXHEALTH",
    "NIFTYHEALTHCARE": "^CNXHEALTH",
    "NIFTY OIL AND GAS": "^CNXOILGAS",
    "NIFTY OIL & GAS": "^CNXOILGAS",
    "NIFTYOILGAS": "^CNXOILGAS",
}

# Special corporate ticker mappings (corporate restructuring / demergers / rebranding)
_CORPORATE_ALIAS_MAP = {
    "TATAMOTORS": "TMPV.NS",
    "ZOMATO": "ETERNAL.NS",
    "CEINFO": "MAPMYINDIA.NS",
    "UNOINDA": "UNOMINDA.NS",
    "REC": "RECLTD.NS",
    "ASTRA": "ASTRAMICRO.NS",
    "SWANENERGY": "SWANCORP.NS",
    "CAPLIPHARM": "CAPLIPOINT.NS",
    "RPGPHILIFE": "RPGLIFE.NS",
    "METRO": "METROBRAND.NS",
    "CENTURYTEX": "ABREL.NS",
    "HITACHI": "POWERINDIA.NS",
    "KALPATPOWR": "KPIL.NS",
    "KBL": "KIRLOSBROS.NS",
    "GSHIP": "GESHIP.NS",
    "JUPITERWAG": "JWL.NS",
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

    # Special corporate ticker mappings (e.g. corporate restructuring / rebranding)
    if upper in _CORPORATE_ALIAS_MAP:
        return _CORPORATE_ALIAS_MAP[upper]

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


import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger("chanakya.yfinance")

_quote_cache_lock = threading.Lock()
_quote_cache: dict[str, tuple[float, Quote]] = {}  # key -> (timestamp, Quote)
_QUOTE_TTL_SECONDS = 30.0

# 6-hour negative cache for delisted or 404 dead tickers to avoid synchronous network stalls
# Uses a SEPARATE lock from _quote_cache_lock to prevent cross-blocking.
_dead_ticker_lock = threading.Lock()
_DEAD_TICKER_CACHE: dict[str, float] = {}  # ticker -> timestamp
_DEAD_TICKER_TTL = 6 * 3600.0  # 6 hours (matches config.constants.DELISTED_SYMBOL_TTL_SECONDS)

# Process-level circuit breaker for Yahoo Finance 429/401 crumb rate-limiting
_yf_rate_limit_lock = threading.Lock()
_yf_rate_limited_until: float = 0.0
_yf_consecutive_rate_limits: int = 0

# USD-denominated yfinance futures tickers mapped to their MCX contract quotation factor
# COMEX/NYMEX futures are quoted in US units (troy oz, lbs, barrels), whereas MCX quotes in Indian standard units:
# - GOLD: COMEX USD/troy oz (31.1035g) → MCX ₹ per 10 grams with Indian landed customs tariff/duty basis (~1.1288x) → ~₹1,52,400 matching Zerodha GOLD OCT FUT
# - SILVER: COMEX USD/troy oz (31.1035g) → MCX ₹ per 1 kilogram with Indian landed customs tariff/duty basis (~1.2427x) → ~₹2,46,700 matching Zerodha SILVER SEP FUT
# - COPPER: COMEX USD/lb → MCX ₹ per 1 kilogram (1 kg = 2.20462 lbs, factor = 2.20462262)
# - CRUDEOIL: WTI USD/barrel → MCX ₹ per 1 barrel (factor = 1.0)
# - BRENT: Brent USD/barrel → MCX ₹ per 1 barrel (factor = 1.0)
# - NATURALGAS: NYMEX USD/MMBtu → MCX ₹ per 1 MMBtu (factor = 1.0)
_USD_COMMODITY_FACTORS: dict[str, float] = {
    "GC=F": (10.0 / 31.1034768)
    * 1.1288,  # GOLD landed (COMEX USD/troy oz → MCX ₹/10 grams with duty/basis)
    "SI=F": (1000.0 / 31.1034768)
    * 1.2427,  # SILVER landed (COMEX USD/troy oz → MCX ₹/1 kg with duty/basis)
    "HG=F": 2.20462262
    * 0.9785,  # COPPER landed (COMEX USD/lb → MCX ₹/1 kg with LME/MCX basis ~0.9785x)
    "CL=F": 1.0,  # CRUDE OIL (NYMEX USD/bbl → MCX ₹/bbl)
    "BZ=F": 1.0,  # BRENT CRUDE OIL (ICE USD/bbl → MCX ₹/bbl)
    "NG=F": 1.0,  # NATURAL GAS (NYMEX USD/MMBtu → MCX ₹/MMBtu)
    "ZNC=F": 1.0 / 1000.0,  # ZINC (LME/COMEX USD/metric ton → MCX ₹/1 kg)
    "ALI=F": 1.0 / 1000.0,  # ALUMINIUM (LME/COMEX USD/metric ton → MCX ₹/1 kg)
    "LED=F": 1.0 / 1000.0,  # LEAD (LME USD/metric ton → MCX ₹/1 kg)
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
    global _yf_rate_limited_until, _yf_consecutive_rate_limits
    cache_key = f"{exchange.upper()}:{symbol.upper()}"
    now = time.time()

    with _quote_cache_lock:
        if cache_key in _quote_cache:
            ts, cached_q = _quote_cache[cache_key]
            if now - ts < _QUOTE_TTL_SECONDS:
                return cached_q

    with _yf_rate_limit_lock:
        if _yf_rate_limited_until > now:
            raise RuntimeError(
                f"yfinance rate-limited (circuit open until {int(_yf_rate_limited_until)})"
            )

    yf = _get_yf()
    ticker = _to_yf_symbol(symbol, exchange)

    with _dead_ticker_lock:
        if ticker in _DEAD_TICKER_CACHE:
            if now - _DEAD_TICKER_CACHE[ticker] < _DEAD_TICKER_TTL:
                raise RuntimeError(f"Ticker {ticker} is in 6h negative cache (delisted/404)")

    try:
        t = yf.Ticker(ticker)
        info = t.fast_info

        last_price = float(info.get("lastPrice", 0) or info.get("last_price", 0) or 0)
        prev_close = float(info.get("previousClose", 0) or info.get("previous_close", 0) or 0)
        open_price = float(info.get("open", 0) or 0)
        day_high = float(info.get("dayHigh", 0) or info.get("day_high", 0) or 0)
        day_low = float(info.get("dayLow", 0) or info.get("day_low", 0) or 0)
        volume = int(info.get("lastVolume", 0) or info.get("last_volume", 0) or 0)

        # If fast_info is sparse or volume is missing, try history for today
        if not last_price or volume <= 0:
            with _yf_rate_limit_lock:
                can_fetch_hist = _yf_rate_limited_until <= time.time()
            if can_fetch_hist:
                try:
                    hist = t.history(period="1d")
                    if not hist.empty:
                        row = hist.iloc[-1]
                        if not last_price:
                            last_price = float(row.get("Close", 0))
                            open_price = float(row.get("Open", 0))
                            day_high = float(row.get("High", 0))
                            day_low = float(row.get("Low", 0))
                        if volume <= 0:
                            volume = int(row.get("Volume", 0))
                except Exception as e_hist:
                    err_str = str(e_hist).lower()
                    if (
                        "429" in err_str
                        or "crumb" in err_str
                        or "rate" in err_str
                        or "401" in err_str
                    ):
                        with _yf_rate_limit_lock:
                            _yf_consecutive_rate_limits += 1
                            if _yf_consecutive_rate_limits >= 2:
                                _yf_rate_limited_until = time.time() + 60.0

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
        err_str = str(e).lower()
        if (
            "404" in err_str
            or "not found" in err_str
            or "delisted" in err_str
            or isinstance(e, (KeyError, IndexError))
        ):
            with _dead_ticker_lock:
                if ticker not in _DEAD_TICKER_CACHE:  # first detection — log it
                    logger.warning(
                        "yfinance_symbol_delisted",
                        extra={"ticker": ticker, "symbol": symbol, "ttl_hours": 6},
                    )
                _DEAD_TICKER_CACHE[ticker] = now
        elif (
            "429" in err_str
            or "crumb" in err_str
            or "rate" in err_str
            or "401" in err_str
            or "unauthorized" in err_str
        ):
            with _yf_rate_limit_lock:
                _yf_consecutive_rate_limits += 1
                if _yf_consecutive_rate_limits >= 2:
                    _yf_rate_limited_until = time.time() + 60.0
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

    # Instant circuit breaker backoff: don't hammer Yahoo Finance when rate-limited
    with _yf_rate_limit_lock:
        if _yf_rate_limited_until > now:
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
    global _yf_rate_limited_until, _yf_consecutive_rate_limits
    yf = _get_yf()
    ticker = _to_yf_symbol(symbol, exchange)

    now_ts = time.time()
    with _yf_rate_limit_lock:
        if _yf_rate_limited_until > now_ts:
            return []
    with _dead_ticker_lock:
        if ticker in _DEAD_TICKER_CACHE:
            if now_ts - _DEAD_TICKER_CACHE[ticker] < _DEAD_TICKER_TTL:
                return []

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

            kwargs = {
                "start": clamped_from.strftime("%Y-%m-%d"),
                "interval": yf_interval,
            }
            # Yahoo Finance `end` date is strictly exclusive.
            # Only supply `end` if caller explicitly specified a cutoff strictly in the past.
            # If to_date is not provided or is today/future, omit `end` so Yahoo Finance
            # returns all completed bars up to the current moment (including today's intraday sessions).
            if to_date and to_date.date() < now.date():
                from datetime import timedelta

                kwargs["end"] = (to_date + timedelta(days=1)).strftime("%Y-%m-%d")

            hist = t.history(**kwargs)
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

        import math

        rows = []
        for idx, row in hist.iterrows():
            c_val = row.get("Close")
            o_val = row.get("Open")
            h_val = row.get("High")
            l_val = row.get("Low")
            if (
                c_val is None
                or o_val is None
                or h_val is None
                or l_val is None
                or math.isnan(float(c_val))
                or math.isnan(float(o_val))
                or math.isnan(float(h_val))
                or math.isnan(float(l_val))
            ):
                continue
            v_val = row.get("Volume", 0)
            vol_int = int(v_val) if (v_val is not None and not math.isnan(float(v_val))) else 0
            rows.append(
                {
                    "date": idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
                    "open": round(float(o_val) * fx, 2),
                    "high": round(float(h_val) * fx, 2),
                    "low": round(float(l_val) * fx, 2),
                    "close": round(float(c_val) * fx, 2),
                    "volume": vol_int,
                }
            )
        with _yf_rate_limit_lock:
            _yf_consecutive_rate_limits = 0
        return rows
    except Exception as e:
        err_str = str(e).lower()
        if "404" in err_str or "not found" in err_str or "delisted" in err_str:
            with _quote_cache_lock:
                _DEAD_TICKER_CACHE[ticker] = time.time()
        elif (
            "429" in err_str
            or "crumb" in err_str
            or "rate" in err_str
            or "401" in err_str
            or "unauthorized" in err_str
        ):
            with _yf_rate_limit_lock:
                _yf_consecutive_rate_limits += 1
                if _yf_consecutive_rate_limits >= 2:
                    _yf_rate_limited_until = time.time() + 60.0
        return []


# ── Convenience ──────────────────────────────────────────────


def yf_available() -> bool:
    """Check if yfinance is installed."""
    try:
        import yfinance  # noqa: F401

        return True
    except ImportError:
        return False


def is_yf_rate_limited() -> bool:
    """Check if yfinance is currently in rate-limit backoff cooldown."""
    with _yf_rate_limit_lock:
        return _yf_rate_limited_until > time.time()
