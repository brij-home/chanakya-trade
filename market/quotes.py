"""
market/quotes.py
────────────────
Live market quotes — tries the active broker first, falls back to
Yahoo Finance (yfinance) for free ~15 min delayed data when no broker
is logged in or the broker call fails.
"""

from __future__ import annotations

import re
import time
import threading
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from brokers.base import Quote
from brokers.session import get_data_broker, get_data_broker_key
from engine.observability import get_registry, new_correlation_id
from market.data_events import classify_data_state, utc_now_iso

_OPTION_PATTERN = re.compile(
    r"^(?:NFO:|BFO:|NSE:|BSE:)?([A-Za-z]+?)(?:\d{2}[A-Z]{3}|\d{5}(?=\d{3,}))?(\d{1,6}(?:\.\d+)?)(CE|PE)$",
    re.IGNORECASE,
)


_FUT_PATTERN = re.compile(
    r"^(?:NFO:|NSE:)?([A-Za-z]+?)(?:\d{2}[A-Z]{3})?FUT(?:URES)?$",
    re.IGNORECASE,
)

_quote_cache_lock = threading.Lock()
_QUOTE_CACHE: OrderedDict[str, tuple[float, Quote]] = OrderedDict()
_QUOTE_TTL_SECONDS = 3.0  # 3.0-second coalescing cache window
_MAX_QUOTE_CACHE_ITEMS = 1000


def clear_quote_cache() -> int:
    """Evict all cached live quotes from memory. Used by memory_guard under memory pressure."""
    with _quote_cache_lock:
        cnt = len(_QUOTE_CACHE)
        _QUOTE_CACHE.clear()
        return cnt


# Register with memory guard sentinel
try:
    from engine.memory_guard import register_trim_callback

    register_trim_callback(clear_quote_cache)
except Exception:
    pass


def _enrich_quote(
    quote: Quote,
    *,
    instrument: str,
    provider: str,
    source: str,
    correlation_id: str,
    quality_flags: tuple[str, ...] = (),
) -> Quote:
    """Attach explicit provenance without mutating adapter-owned instances."""
    try:
        from market.instruments import resolve_canonical_instrument

        canonical_id = resolve_canonical_instrument(instrument).instrument_id
    except Exception:
        canonical_id = None
    price = float(getattr(quote, "last_price", 0.0) or 0.0)
    source_kind = (
        source if source in {"STREAM", "REST", "EOD_SNAPSHOT", "FALLBACK", "CACHE"} else "FALLBACK"
    )
    return replace(
        quote,
        provider=provider,
        source=source_kind,
        data_state=classify_data_state(source=source_kind, provider=provider, price=price),
        canonical_instrument_id=canonical_id,
        provider_symbol=quote.provider_symbol or instrument,
        received_at=quote.received_at if quote.received_at else utc_now_iso(),
        received_monotonic_ns=quote.received_monotonic_ns or time.monotonic_ns(),
        quality_flags=tuple(sorted(set(quote.quality_flags).union(quality_flags))),
        correlation_id=correlation_id,
    )


def _ws_quotes(instruments: list[str], *, correlation_id: str) -> dict[str, Quote]:
    """Try WebSocket cache first (instant, no API call)."""
    try:
        # Fyers' legacy singleton cache must never outrank a selected non-Fyers
        # data provider.  Other providers can register their own normalized stream.
        if get_data_broker_key() != "fyers":
            return {}

        from market.websocket import ws_manager

        if not ws_manager.connected:
            return {}

        result = {}
        missing = []
        for inst in instruments:
            tick = ws_manager.get_tick(inst)
            if tick and tick.ltp > 0:
                result[inst] = _enrich_quote(
                    Quote(
                        symbol=tick.symbol.split(":")[-1].split("-")[0]
                        if ":" in tick.symbol
                        else tick.symbol,
                        last_price=tick.ltp,
                        open=tick.open,
                        high=tick.high,
                        low=tick.low,
                        close=tick.close,
                        volume=tick.volume,
                        change=tick.change,
                        change_pct=tick.change_pct,
                        exchange_timestamp=(
                            datetime.fromtimestamp(tick.timestamp, tz=timezone.utc).isoformat()
                            if tick.timestamp and tick.timestamp > 0
                            else None
                        ),
                    ),
                    instrument=inst,
                    provider="fyers",
                    source="STREAM",
                    correlation_id=correlation_id,
                )
            else:
                missing.append(inst)

        # Subscribe to missing symbols for next time
        if missing:
            ws_manager.subscribe(missing)

        return result
    except Exception:
        return {}


def _options_quotes(instruments: list[str], *, correlation_id: str) -> dict[str, Quote]:
    """Resolve derivative option contract quotes directly from options snapshot (mStock / NSE scraper) without hitting yfinance."""
    try:
        from market.options import get_options_snapshot

        res: dict[str, Quote] = {}
        by_und: dict[str, list[tuple[str, str, float, str]]] = {}
        for inst in instruments:
            clean = inst.split(":")[-1].strip().upper()
            m = _OPTION_PATTERN.match(clean)
            if not m:
                continue
            und, strike_str, opt_type = m.groups()
            by_und.setdefault(und.upper(), []).append(
                (inst, clean, float(strike_str), opt_type.upper())
            )

        for und, items in by_und.items():
            try:
                contracts, spot, expiries, src_info = get_options_snapshot(und)
                for inst, clean, strike, opt_type in items:
                    for c in contracts:
                        if c.option_type == opt_type and abs(c.strike - strike) < 0.01:
                            chg_pct = (
                                getattr(c, "pchange", 0.0) or getattr(c, "change_pct", 0.0) or 0.0
                            )
                            last_p = float(c.last_price or 0.0)
                            chg_val = round((last_p * chg_pct / 100.0), 2) if chg_pct else 0.0
                            q = Quote(
                                symbol=clean,
                                last_price=last_p,
                                open=getattr(c, "open", None),
                                high=getattr(c, "high", None),
                                low=getattr(c, "low", None),
                                close=getattr(c, "close", None),
                                volume=int(c.volume or 0),
                                change=chg_val,
                                change_pct=round(chg_pct, 2),
                            )
                            enriched = _enrich_quote(
                                q,
                                instrument=inst,
                                provider=src_info.get("provider", "mstock"),
                                source="REST",
                                correlation_id=correlation_id,
                            )
                            res[inst] = enriched
                            res[clean] = enriched
                            break
            except Exception:
                pass
        return res
    except Exception:
        return {}


def _futures_quotes(instruments: list[str], *, correlation_id: str) -> dict[str, Quote]:
    """Resolve derivative futures contract quotes when broker feed is offline or in paper mode."""
    res: dict[str, Quote] = {}
    for inst in instruments:
        clean = inst.split(":")[-1].strip().upper()
        m = _FUT_PATTERN.match(clean)
        if not m:
            continue
        und = m.group(1).upper()
        try:
            spot_quotes = get_quote([und])
            spot_q = spot_quotes.get(und) or spot_quotes.get(f"NSE:{und}")
            if spot_q and getattr(spot_q, "last_price", 0.0) > 0:
                fut_price = round(spot_q.last_price * 1.0035, 2)
                q = Quote(
                    symbol=clean,
                    last_price=fut_price,
                    open=round(spot_q.open * 1.0035, 2) if spot_q.open else None,
                    high=round(spot_q.high * 1.0035, 2) if spot_q.high else None,
                    low=round(spot_q.low * 1.0035, 2) if spot_q.low else None,
                    close=round(spot_q.close * 1.0035, 2) if spot_q.close else None,
                    volume=spot_q.volume or 0,
                    change=round((spot_q.change or 0.0) * 1.0035, 2),
                    change_pct=spot_q.change_pct or 0.0,
                )
                enriched = _enrich_quote(
                    q,
                    instrument=inst,
                    provider="synthetic_fut",
                    source="FALLBACK",
                    correlation_id=correlation_id,
                )
                res[inst] = enriched
                res[clean] = enriched
        except Exception:
            pass
    return res


def _yf_fallback_quotes(
    instruments: list[str], *, correlation_id: Optional[str] = None
) -> dict[str, Quote]:
    """Try yfinance when broker is unavailable (skips Indian options & futures which yfinance does not host)."""
    try:
        from market.yfinance_provider import yf_get_quotes, yf_available

        yf_eligible = [
            i
            for i in instruments
            if not (
                i.startswith("NFO:")
                or i.startswith("BFO:")
                or _OPTION_PATTERN.match(i.split(":")[-1])
                or _FUT_PATTERN.match(i.split(":")[-1])
            )
        ]
        if not yf_eligible:
            return {}

        if yf_available():
            raw = yf_get_quotes(yf_eligible)
            cid = correlation_id or new_correlation_id("quote")
            return {
                instrument: _enrich_quote(
                    quote,
                    instrument=instrument,
                    provider="yfinance",
                    source="FALLBACK",
                    correlation_id=cid,
                    quality_flags=("DELAYED_SOURCE",),
                )
                for instrument, quote in raw.items()
            }
    except Exception:
        pass
    return {}


_MCX_SYMBOLS = {
    "GOLD",
    "GOLDM",
    "GOLDPETAL",
    "SILVER",
    "SILVERM",
    "SILVERMIC",
    "CRUDEOIL",
    "CRUDEOILM",
    "CRUDE",
    "BRENT",
    "NATURALGAS",
    "NATGASMINI",
    "NATGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
    "ALUMINUM",
    "LEAD",
    "COTTON",
}
_CDS_SYMBOLS = {
    "USDINR",
    "USD/INR",
    "EURINR",
    "EUR/INR",
    "GBPINR",
    "GBP/INR",
    "JPYINR",
    "JPY/INR",
}
_BSE_SYMBOLS = {"SENSEX", "BANKEX", "BSE SENSEX", "BSE BANKEX"}
_CRYPTO_SYMBOLS = {
    "BTC",
    "BITCOIN",
    "BTCUSD",
    "BTC-USD",
    "BTCINR",
    "ETH",
    "ETHEREUM",
    "SOL",
}


def normalize_instrument(inst: str) -> str:
    """Intelligently prefix EXCHANGE: if omitted."""
    s = inst.strip()
    if ":" in s:
        return s
    upper = s.upper()
    if upper in _CRYPTO_SYMBOLS:
        return f"CRYPTO:{upper}"
    if upper in _MCX_SYMBOLS:
        return f"MCX:{upper}"
    if upper in _CDS_SYMBOLS:
        return f"CDS:{upper}"
    if upper in _BSE_SYMBOLS:
        return f"BSE:{upper}"
    if _OPTION_PATTERN.match(upper) or _FUT_PATTERN.match(upper):
        return f"NFO:{upper}"
    return f"NSE:{upper}"


def get_quote(
    instruments: list[str] | str,
    *,
    bypass_cache: bool = False,
) -> dict[str, Quote]:
    """
    Live quotes for one or more instruments.

    Priority: Short-TTL in-memory cache (3.0s) → WebSocket cache (instant) → Broker REST API → yfinance fallback.

    Args:
        instruments: List of "EXCHANGE:SYMBOL" strings, or a single instrument string.
                     e.g. ["NSE:RELIANCE", "NSE:NIFTY 50", "NFO:NIFTY24APR22900CE", "GOLD", "USDINR"]
        bypass_cache: Explicitly bypass the 3.0s coalesced cache to force a fresh quote query.

    Returns:
        Dict keyed by instrument string → Quote dataclass.
    """
    if isinstance(instruments, str):
        instruments = [instruments]

    correlation_id = new_correlation_id("quote")
    started = time.monotonic()
    now_wall = time.time()

    # Map raw input to normalized canonical format
    input_to_canonical = {raw: normalize_instrument(raw) for raw in instruments}
    canonical_instruments = list(set(input_to_canonical.values()))

    # 1. Try short-TTL in-memory cache (0.01ms) unless explicitly bypassed
    result: dict[str, Quote] = {}
    if not bypass_cache:
        with _quote_cache_lock:
            for inst in canonical_instruments:
                if inst in _QUOTE_CACHE:
                    ts, cached_q = _QUOTE_CACHE[inst]
                    if (
                        now_wall - ts < _QUOTE_TTL_SECONDS
                        and getattr(cached_q, "last_price", 0.0) > 0
                    ):
                        result[inst] = cached_q

    missing = [i for i in canonical_instruments if i not in result]

    # 2. Try WebSocket cache (instant)
    if missing:
        ws_quotes = _ws_quotes(missing, correlation_id=correlation_id)
        result.update(ws_quotes)
        missing = [i for i in canonical_instruments if i not in result]

    # 3. Try broker REST API
    if missing:
        try:
            provider = get_data_broker_key() or "broker"
            broker_quotes = get_data_broker().get_quote(missing)
            result.update(
                {
                    instrument: _enrich_quote(
                        quote,
                        instrument=instrument,
                        provider=provider,
                        source="REST",
                        correlation_id=correlation_id,
                    )
                    for instrument, quote in broker_quotes.items()
                }
            )
            get_registry().record_provider_success(provider)
            missing = [i for i in canonical_instruments if i not in result]
        except Exception:
            get_registry().record_provider_error(get_data_broker_key() or "broker")

    # 3.5. Try derivative options snapshot (mStock / NSE options scraper) for any missing options
    if missing:
        opt_quotes = _options_quotes(missing, correlation_id=correlation_id)
        if opt_quotes:
            result.update(opt_quotes)
            missing = [i for i in canonical_instruments if i not in result]

    # 4. yfinance fallback
    if missing:
        yf_quotes = _yf_fallback_quotes(missing, correlation_id=correlation_id)
        result.update(yf_quotes)
        if yf_quotes:
            get_registry().record_provider_success("yfinance")
        else:
            get_registry().record_provider_error("yfinance", is_stale=True)
        missing = [i for i in canonical_instruments if i not in result]

    # 4.5. Futures fallback for remaining missing futures
    if missing:
        fut_quotes = _futures_quotes(missing, correlation_id=correlation_id)
        if fut_quotes:
            result.update(fut_quotes)
            missing = [i for i in canonical_instruments if i not in result]

    # 5. Populate cache with newly fetched quotes
    if result:
        with _quote_cache_lock:
            for k, q in result.items():
                if q and getattr(q, "last_price", 0.0) > 0:
                    _QUOTE_CACHE[k] = (now_wall, q)
                    _QUOTE_CACHE.move_to_end(k)
            while len(_QUOTE_CACHE) > _MAX_QUOTE_CACHE_ITEMS:
                _QUOTE_CACHE.popitem(last=False)

    # 6. Populate raw aliases so quotes["GOLD"] and quotes["MCX:GOLD"] both resolve
    final_result: dict[str, Quote] = dict(result)
    for raw_key, canon_key in input_to_canonical.items():
        if canon_key in result:
            final_result[raw_key] = result[canon_key]
            # Also ensure short symbol key without exchange is accessible
            sym_part = raw_key.split(":")[-1]
            if sym_part not in final_result:
                final_result[sym_part] = result[canon_key]

    get_registry().record_metric(
        "quote_fetch",
        latency_ms=(time.monotonic() - started) * 1000,
        success=bool(result),
        correlation_id=correlation_id,
        provider=get_data_broker_key() or "fallback",
        error_type=None if result else "QUOTE_UNAVAILABLE",
        metadata={"requested": len(canonical_instruments), "resolved": len(result)},
    )
    return final_result


def get_ltp(instrument: str) -> float:
    """
    Last traded price for a single instrument.

    Args:
        instrument: "EXCHANGE:SYMBOL" or "SYMBOL"  e.g. "NSE:INFY", "GOLD", "USDINR"

    Returns:
        Last traded price as float.
    """
    canon = normalize_instrument(instrument)
    quotes = get_quote([canon])
    if canon in quotes and quotes[canon].last_price > 0:
        return quotes[canon].last_price
    if instrument in quotes and quotes[instrument].last_price > 0:
        return quotes[instrument].last_price
    return 0.0


def get_ltp_many(instruments: list[str]) -> dict[str, float]:
    """
    Last traded prices for multiple instruments in one call.

    Returns:
        Dict of instrument → ltp float.
    """
    quotes = get_quote(instruments)
    return {sym: q.last_price for sym, q in quotes.items()}


def get_ohlc(instrument: str) -> dict:
    """
    Today's OHLC + volume for a single instrument.

    Returns:
        Dict with keys: open, high, low, close, last_price, volume
    """
    quotes = get_quote([instrument])
    q = quotes.get(instrument)
    if not q:
        return {
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 0,
            "last_price": 0,
            "volume": 0,
            "change": 0,
            "change_pct": 0,
        }
    return {
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "close": q.close,
        "last_price": q.last_price,
        "volume": q.volume,
        "change": q.change,
        "change_pct": q.change_pct,
    }
