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
    r"^(?:NFO:|BFO:|NSE:|BSE:)?(?P<underlying>[A-Za-z0-9_& -]+?)(?:(?P<exp_iso>20\d{6})|(?P<exp_nfo>\d{2}[A-Z]{3})|(?P<exp_num>\d{5}(?=\d{3,})))?\s*(?P<strike>\d{1,6}(?:\.\d+)?)\s*(?P<opt_type>CE|PE)$",
    re.IGNORECASE,
)


_FUT_PATTERN = re.compile(
    r"^(?:NFO:|NSE:)?([A-Za-z&]+?)(?:\d{2}[A-Z]{3})?FUT(?:URES)?$",
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


# ── Computed VWAP cache ────────────────────────────────────────────────────────
# mStock REST API does not return VWAP in its quote response (mode=FULL or OHLC).
# We compute it locally from today's 5-minute OHLCV bars using the standard
# intraday TWAP formula: sum(typical_price × volume) / sum(volume)
# where typical_price = (High + Low + Close) / 3.
# Cache TTL: 30s — balances freshness vs repeated history fetches.
_vwap_cache_lock = threading.Lock()
_VWAP_CACHE: dict[str, tuple[float, float]] = {}  # symbol → (computed_at, vwap)
_VWAP_CACHE_TTL = 30.0


def get_computed_vwap(symbol: str, exchange: str = "NSE") -> Optional[float]:
    """
    Compute session VWAP for a symbol from today's 5-minute bars.

    Returns None if: no 5m data available, all bars have zero volume (indices),
    or the formula produces a degenerate result.

    Cached for 30s per symbol to avoid repeated history fetches on every quote call.
    """
    clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    now_ts = time.monotonic()
    with _vwap_cache_lock:
        cached = _VWAP_CACHE.get(clean)
        if cached and (now_ts - cached[0]) < _VWAP_CACHE_TTL:
            return cached[1] if cached[1] > 0 else None

    try:
        from market.history import get_ohlcv
        from zoneinfo import ZoneInfo

        IST = ZoneInfo("Asia/Kolkata")
        today_str = datetime.now(IST).strftime("%Y-%m-%d")

        df = get_ohlcv(clean, exchange=exchange, interval="5minute", days=1)
        if df is None or len(df) < 1:
            return None

        # Isolate today's bars only
        if hasattr(df.index, "strftime"):
            df = df[df.index.strftime("%Y-%m-%d") == today_str]
        if len(df) < 1:
            return None

        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"
        col_v = "volume" if "volume" in df.columns else "Volume"

        h = df[col_h].astype(float)
        lo = df[col_l].astype(float)
        c = df[col_c].astype(float)
        v = df[col_v].astype(float)

        typical = (h + lo + c) / 3.0
        total_vol = v.sum()

        if total_vol <= 0:
            # Indices have zero volume in the exchange feed — fall back to simple
            # time-weighted average price (equal-weight TWAP) as best proxy.
            vwap_val = float(typical.mean()) if len(typical) > 0 else 0.0
        else:
            vwap_val = float((typical * v).sum() / total_vol)

        if vwap_val > 0:
            with _vwap_cache_lock:
                _VWAP_CACHE[clean] = (now_ts, vwap_val)
            return vwap_val
    except Exception:
        pass
    return None


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

    vwap_val = getattr(quote, "vwap", None)
    clean_sym = instrument.split(":")[-1].strip().upper()
    if (vwap_val is None or vwap_val <= 0) and not _OPTION_PATTERN.match(clean_sym):
        # 1. Fast cache check
        with _vwap_cache_lock:
            cached_vwap = _VWAP_CACHE.get(clean_sym)
            if cached_vwap and (time.monotonic() - cached_vwap[0]) < _VWAP_CACHE_TTL:
                vwap_val = cached_vwap[1] if cached_vwap[1] > 0 else None
        # 2. If it's a primary benchmark index and still missing, compute on-demand
        if (vwap_val is None or vwap_val <= 0) and clean_sym in {
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "NIFTY 50",
            "NIFTY BANK",
        }:
            vwap_val = get_computed_vwap(
                clean_sym, exchange="BSE" if clean_sym == "SENSEX" else "NSE"
            )

    return replace(
        quote,
        provider=provider,
        source=source_kind,
        vwap=vwap_val or quote.vwap,
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
        broker_key = get_data_broker_key()
        result: dict[str, Quote] = {}

        # 1. m.Stock WebSocket
        if broker_key == "mstock":
            try:
                from market.mstock_websocket import mstock_ws
                from market.websocket import ws_manager

                missing = []
                for inst in instruments:
                    clean = inst.split(":")[-1].strip().upper()
                    tick = mstock_ws.get_tick(inst) or mstock_ws.get_tick(clean)
                    if not tick or getattr(tick, "ltp", 0.0) <= 0:
                        c_tick = ws_manager.get_tick(inst) or ws_manager.get_tick(clean)
                        if c_tick and getattr(c_tick, "ltp", 0.0) > 0:
                            tick = c_tick
                    if tick and getattr(tick, "ltp", 0.0) > 0:
                        ws_vwap = (
                            float(getattr(tick, "atp", 0.0) or getattr(tick, "vwap", 0.0) or 0.0)
                            or None
                        )
                        result[inst] = _enrich_quote(
                            Quote(
                                symbol=clean,
                                last_price=float(tick.ltp),
                                open=getattr(tick, "open", None),
                                high=getattr(tick, "high", None),
                                low=getattr(tick, "low", None),
                                close=getattr(tick, "close", None),
                                volume=int(getattr(tick, "volume", 0) or 0),
                                change=float(getattr(tick, "change", 0.0) or 0.0),
                                change_pct=float(getattr(tick, "change_pct", 0.0) or 0.0),
                                vwap=ws_vwap,
                                exchange_timestamp=(
                                    datetime.fromtimestamp(
                                        tick.timestamp, tz=timezone.utc
                                    ).isoformat()
                                    if getattr(tick, "timestamp", 0) and tick.timestamp > 0
                                    else None
                                ),
                            ),
                            instrument=inst,
                            provider="mstock",
                            source="STREAM",
                            correlation_id=correlation_id,
                        )
                    else:
                        missing.append(inst)

                # Auto-subscribe missing instruments to mstock_ws if connected
                if missing and getattr(mstock_ws, "is_connected", False):
                    mstock_ws.subscribe(missing)

                return result
            except Exception:
                return {}

        # 2. Kotak Neo WebSocket
        if broker_key == "kotak":
            try:
                from market.kotak_websocket import kotak_ws
                from market.websocket import ws_manager

                missing = []
                for inst in instruments:
                    clean = inst.split(":")[-1].strip().upper()
                    tick = kotak_ws.get_tick(inst) or kotak_ws.get_tick(clean)
                    if not tick or getattr(tick, "ltp", 0.0) <= 0:
                        c_tick = ws_manager.get_tick(inst) or ws_manager.get_tick(clean)
                        if c_tick and getattr(c_tick, "ltp", 0.0) > 0:
                            tick = c_tick
                    if tick and getattr(tick, "ltp", 0.0) > 0:
                        ws_vwap = (
                            float(getattr(tick, "atp", 0.0) or getattr(tick, "vwap", 0.0) or 0.0)
                            or None
                        )
                        result[inst] = _enrich_quote(
                            Quote(
                                symbol=clean,
                                last_price=float(tick.ltp),
                                open=getattr(tick, "open", None),
                                high=getattr(tick, "high", None),
                                low=getattr(tick, "low", None),
                                close=getattr(tick, "close", None),
                                volume=int(getattr(tick, "volume", 0) or 0),
                                change=float(getattr(tick, "change", 0.0) or 0.0),
                                change_pct=float(getattr(tick, "change_pct", 0.0) or 0.0),
                                vwap=ws_vwap,
                                exchange_timestamp=(
                                    datetime.fromtimestamp(
                                        tick.timestamp, tz=timezone.utc
                                    ).isoformat()
                                    if getattr(tick, "timestamp", 0) and tick.timestamp > 0
                                    else None
                                ),
                            ),
                            instrument=inst,
                            provider="kotak",
                            source="STREAM",
                            correlation_id=correlation_id,
                        )
                    else:
                        missing.append(inst)

                if missing and getattr(kotak_ws, "is_connected", lambda: False)():
                    kotak_ws.subscribe(missing)

                return result
            except Exception:
                return {}

        # 3. Fyers WebSocket
        if broker_key != "fyers":
            return {}

        from market.websocket import ws_manager

        if not ws_manager.connected:
            return {}

        missing = []
        for inst in instruments:
            tick = ws_manager.get_tick(inst)
            if tick and tick.ltp > 0:
                ws_vwap = (
                    float(getattr(tick, "atp", 0.0) or getattr(tick, "vwap", 0.0) or 0.0) or None
                )
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
                        vwap=ws_vwap,
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
        by_und_exp: dict[
            tuple[str, Optional[str]], list[tuple[str, str, float, str, Optional[str]]]
        ] = {}
        for inst in instruments:
            clean = inst.split(":")[-1].strip().upper()
            m = _OPTION_PATTERN.match(clean)
            if not m:
                continue
            und, exp_iso, exp_nfo, exp_num, strike_str, opt_type = m.groups()
            exp_date_str = None
            if exp_iso:
                # 20261027 -> 2026-10-27
                exp_date_str = f"{exp_iso[:4]}-{exp_iso[4:6]}-{exp_iso[6:8]}"
            by_und_exp.setdefault((und.upper(), exp_date_str), []).append(
                (inst, clean, float(strike_str), opt_type.upper(), exp_date_str)
            )

        for (und, exp_date_str), items in by_und_exp.items():
            try:
                contracts, spot, expiries, src_info = get_options_snapshot(und, expiry=exp_date_str)
                for inst, clean, strike, opt_type, target_exp in items:
                    for c in contracts:
                        if c.option_type == opt_type and abs(c.strike - strike) < 0.01:
                            if target_exp and getattr(c, "expiry", None) and c.expiry != target_exp:
                                continue
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


from config.market_universes import (
    BSE_EQUITY_SYMBOLS as _BSE_SYMBOLS,
    CDS_CURRENCY_SYMBOLS as _CDS_SYMBOLS,
    CRYPTO_SYMBOLS as _CRYPTO_SYMBOLS,
    MCX_COMMODITY_SYMBOLS as _MCX_SYMBOLS,
)


def _yf_fallback_quotes(
    instruments: list[str], *, correlation_id: Optional[str] = None
) -> dict[str, Quote]:
    """Try yfinance when broker is unavailable (skips Indian options & futures which yfinance does not host)."""
    try:
        from market.yfinance_provider import yf_get_quotes, yf_available, is_yf_rate_limited

        if not yf_available() or is_yf_rate_limited():
            return {}

        yf_eligible = [
            i
            for i in instruments
            if not (
                i.startswith("NFO:")
                or i.startswith("BFO:")
                or i.startswith("CRYPTO:")
                or i.startswith("BINANCE:")
                or i.split(":")[-1].upper() in _CRYPTO_SYMBOLS
                or _OPTION_PATTERN.match(i.split(":")[-1])
                or _OPTION_PATTERN.match(
                    i.split(":")[-1].replace("NIFTY 50", "NIFTY").replace("NIFTY BANK", "BANKNIFTY")
                )
                or _FUT_PATTERN.match(i.split(":")[-1])
            )
        ]

        if not yf_eligible:
            return {}

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
    # Standardize index names with spaces (e.g. NIFTY 50 -> NIFTY) before option matching
    clean_deriv = upper.replace("NIFTY 50", "NIFTY").replace("NIFTY BANK", "BANKNIFTY")
    if (
        _OPTION_PATTERN.match(upper)
        or _OPTION_PATTERN.match(clean_deriv)
        or _FUT_PATTERN.match(upper)
    ):
        if any(upper.startswith(x) for x in ("SENSEX", "BANKEX")):
            return f"BFO:{upper}"
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

    # 2.5. Try 24x7 Crypto Stream (instant in-memory Binance ticks)
    if missing:
        crypto_missing = [
            i
            for i in missing
            if i.startswith("CRYPTO:")
            or any(i.replace("CRYPTO:", "") == s for s in _CRYPTO_SYMBOLS)
        ]
        if crypto_missing:
            try:
                from market.crypto_stream import crypto_stream

                for c_inst in crypto_missing:
                    q = crypto_stream.get_quote(c_inst)
                    if q and getattr(q, "last_price", 0.0) > 0:
                        result[c_inst] = q
                missing = [i for i in canonical_instruments if i not in result]
            except Exception:
                pass

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
