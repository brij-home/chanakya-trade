"""
market/quotes.py
────────────────
Live market quotes — tries the active broker first, falls back to
Yahoo Finance (yfinance) for free ~15 min delayed data when no broker
is logged in or the broker call fails.
"""

from __future__ import annotations

from brokers.base import Quote
from brokers.session import get_data_broker


def _ws_quotes(instruments: list[str]) -> dict[str, Quote]:
    """Try WebSocket cache first (instant, no API call)."""
    try:
        from market.websocket import ws_manager

        if not ws_manager.connected:
            return {}

        result = {}
        missing = []
        for inst in instruments:
            tick = ws_manager.get_tick(inst)
            if tick and tick.ltp > 0:
                result[inst] = Quote(
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
                )
            else:
                missing.append(inst)

        # Subscribe to missing symbols for next time
        if missing:
            ws_manager.subscribe(missing)

        return result
    except Exception:
        return {}


def _yf_fallback_quotes(instruments: list[str]) -> dict[str, Quote]:
    """Try yfinance when broker is unavailable."""
    try:
        from market.yfinance_provider import yf_get_quotes, yf_available

        if yf_available():
            return yf_get_quotes(instruments)
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


def normalize_instrument(inst: str) -> str:
    """Intelligently prefix EXCHANGE: if omitted."""
    s = inst.strip()
    if ":" in s:
        return s
    upper = s.upper()
    if upper in _MCX_SYMBOLS:
        return f"MCX:{upper}"
    if upper in _CDS_SYMBOLS:
        return f"CDS:{upper}"
    if upper in _BSE_SYMBOLS:
        return f"BSE:{upper}"
    return f"NSE:{upper}"


def get_quote(instruments: list[str] | str) -> dict[str, Quote]:
    """
    Live quotes for one or more instruments.

    Priority: WebSocket cache (instant) → Broker REST API → yfinance fallback.

    Args:
        instruments: List of "EXCHANGE:SYMBOL" strings, or a single instrument string.
                     e.g. ["NSE:RELIANCE", "NSE:NIFTY 50", "NFO:NIFTY24APR22900CE", "GOLD", "USDINR"]

    Returns:
        Dict keyed by instrument string → Quote dataclass.
    """
    if isinstance(instruments, str):
        instruments = [instruments]

    # Map raw input to normalized canonical format
    input_to_canonical = {raw: normalize_instrument(raw) for raw in instruments}
    canonical_instruments = list(set(input_to_canonical.values()))

    # 1. Try WebSocket cache (instant)
    result = _ws_quotes(canonical_instruments)
    missing = [i for i in canonical_instruments if i not in result]

    # 2. Try broker REST API
    if missing:
        try:
            broker_quotes = get_data_broker().get_quote(missing)
            result.update(broker_quotes)
            missing = [i for i in canonical_instruments if i not in result]
        except (RuntimeError, Exception):
            pass

    # 3. yfinance fallback
    if missing:
        yf_quotes = _yf_fallback_quotes(missing)
        result.update(yf_quotes)

    # 4. Populate raw aliases so quotes["GOLD"] and quotes["MCX:GOLD"] both resolve
    final_result: dict[str, Quote] = dict(result)
    for raw_key, canon_key in input_to_canonical.items():
        if canon_key in result:
            final_result[raw_key] = result[canon_key]
            # Also ensure short symbol key without exchange is accessible
            sym_part = raw_key.split(":")[-1]
            if sym_part not in final_result:
                final_result[sym_part] = result[canon_key]

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
    try:
        val = get_data_broker().get_ltp(canon)
        if val and val > 0:
            return float(val)
    except (RuntimeError, Exception):
        pass

    quotes = _yf_fallback_quotes([canon])
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
