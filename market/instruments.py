"""
market/instruments.py
─────────────────────
Canonical Instrument Master & Exchange Session State Engine for Indian Markets.

Provides:
  1. Strongly-typed CanonicalInstrument model with venue, segment, type, tick & lot sizes.
  2. Multi-Asset resolution: Equities, Indices, F&O, MCX Commodities, and Currency Pairs.
  3. Market session state resolution (PRE_OPEN, OPEN, POST_CLOSE, CLOSED) for NSE, BSE, MCX, CDS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Any, Literal, Optional

# Standard IST timezone offset (+05:30)
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

Venue = Literal["NSE", "BSE", "MCX", "CDS", "NSE_IFSC"]
Segment = Literal["EQUITY", "FNO", "COMMODITY", "CURRENCY", "INDEX"]
InstrumentType = Literal["EQUITY", "INDEX", "FUTURE", "OPTION", "ETF", "COMMODITY"]
SessionState = Literal["PRE_OPEN", "OPEN", "POST_CLOSE", "CLOSED"]

# Standard Indian F&O & Commodity Lot Sizes
STANDARD_LOT_SIZES: dict[str, int] = {
    # Benchmark & Sectoral Indices
    "NIFTY": 25,
    "NIFTY 50": 25,
    "BANKNIFTY": 15,
    "NIFTY BANK": 15,
    "FINNIFTY": 25,
    "NIFTY FINANCIAL SERVICES": 25,
    "MIDCPNIFTY": 50,
    "NIFTY MID SELECT": 50,
    "SENSEX": 10,
    "BANKEX": 15,
    # MCX Commodities
    "CRUDEOIL": 100,
    "NATURALGAS": 1250,
    "GOLD": 1,
    "GOLDM": 1,
    "SILVER": 30,
    "SILVERM": 5,
    "COPPER": 2500,
    "ZINC": 5000,
    "ALUMINIUM": 5000,
    # Currency Derivatives
    "USDINR": 1000,
    "EURINR": 1000,
    "GBPINR": 1000,
    "JPYINR": 1000,
}

# Standard Tick Sizes
STANDARD_TICK_SIZES: dict[str, float] = {
    "EQUITY": 0.05,
    "FNO": 0.05,
    "INDEX": 0.05,
    "COMMODITY": 0.05,
    "CURRENCY": 0.0025,
}

COMMODITY_SYMBOLS = {
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
    "CRUDEOIL",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
    "LEAD",
    "NICKEL",
    "COTTON",
    "MCXBULLDEX",
}

CURRENCY_SYMBOLS = {
    "USDINR",
    "EURINR",
    "GBPINR",
    "JPYINR",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
}

INDEX_SYMBOLS = {
    "NIFTY",
    "NIFTY 50",
    "NIFTY50",
    "^NSEI",
    "BANKNIFTY",
    "NIFTY BANK",
    "^NSEBANK",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTY IT",
    "^CNXIT",
    "NIFTY AUTO",
    "^CNXAUTO",
    "NIFTY PHARMA",
    "^CNXPHARMA",
    "NIFTY FMCG",
    "^CNXFMCG",
    "NIFTY METAL",
    "^CNXMETAL",
    "NIFTY REALTY",
    "^CNXREALTY",
    "NIFTY ENERGY",
    "^CNXENERGY",
    "SENSEX",
    "^BSESN",
    "BANKEX",
    "BSE:SENSEX",
    "BSE:BANKEX",
    "INDIA VIX",
    "INDIAVIX",
}


@dataclass
class CanonicalInstrument:
    """Canonical Instrument representation across all trading venues."""

    instrument_id: str  # e.g., "NSE:RELIANCE:EQUITY", "NSE:NIFTY:INDEX", "MCX:GOLD:COMMODITY"
    symbol: str  # e.g., "RELIANCE"
    exchange: Venue  # "NSE", "BSE", "MCX", "CDS", "NSE_IFSC"
    segment: Segment  # "EQUITY", "FNO", "COMMODITY", "CURRENCY", "INDEX"
    instrument_type: InstrumentType  # "EQUITY", "INDEX", "FUTURE", "OPTION", "ETF", "COMMODITY"
    lot_size: int = 1
    tick_size: float = 0.05
    currency: str = "INR"
    is_tradable: bool = True
    is_proxy: bool = False
    proxy_source: Optional[str] = None
    status: str = "ACTIVE"
    underlying: Optional[str] = None
    expiry_date: Optional[str] = None
    strike_price: Optional[float] = None
    option_type: Optional[str] = None  # "CE" | "PE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketSessionState:
    """Live operational state for an exchange trading venue."""

    exchange: Venue
    session_state: SessionState  # "PRE_OPEN" | "OPEN" | "POST_CLOSE" | "CLOSED"
    is_open: bool
    as_of_ist: str
    current_time_ist: str
    session_open_ist: str
    session_close_ist: str
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_current_ist_time(now_utc: Optional[datetime] = None) -> datetime:
    """Return the current time converted accurately to Asia/Kolkata (UTC+05:30)."""
    utc_dt = now_utc or datetime.now(timezone.utc)
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(IST_OFFSET)


def resolve_canonical_instrument(query: str) -> CanonicalInstrument:
    """
    Resolve and normalize any user/symbol query into a canonical instrument master record.

    Examples:
        "RELIANCE"       → NSE:RELIANCE:EQUITY (Lot: 1, Tick: 0.05)
        "NIFTY"          → NSE:NIFTY:INDEX (Lot: 25, Tick: 0.05)
        "MCX:GOLD"       → MCX:GOLD:COMMODITY (Lot: 1, Tick: 0.05)
        "USDINR"         → CDS:USDINR:CURRENCY (Lot: 1000, Tick: 0.0025)
        "SENSEX"         → BSE:SENSEX:INDEX (Lot: 10, Tick: 0.05)
    """
    raw = (query or "NIFTY").strip().upper()

    # Split venue prefix if supplied
    venue: Venue = "NSE"
    clean_sym = raw

    if ":" in raw:
        parts = raw.split(":", 1)
        prefix = parts[0].strip()
        clean_sym = parts[1].strip()
        if prefix in ("BSE", "MCX", "CDS", "NSE_IFSC", "NSE"):
            venue = prefix  # type: ignore

    # Detect Indices
    if clean_sym in INDEX_SYMBOLS or clean_sym.startswith("^"):
        exch: Venue = (
            "BSE" if clean_sym in ("SENSEX", "^BSESN", "BANKEX") or venue == "BSE" else "NSE"
        )
        sym_name = clean_sym.replace("^", "").replace("NSEI", "NIFTY").replace("BSESN", "SENSEX")
        if sym_name == "NSEBANK":
            sym_name = "BANKNIFTY"
        lot = STANDARD_LOT_SIZES.get(sym_name, 1)
        return CanonicalInstrument(
            instrument_id=f"{exch}:{sym_name}:INDEX",
            symbol=sym_name,
            exchange=exch,
            segment="INDEX",
            instrument_type="INDEX",
            lot_size=lot,
            tick_size=0.05,
            currency="INR",
            is_tradable=False,  # Spot index is not directly tradable (derivatives are)
            status="ACTIVE",
        )

    # Detect MCX Commodities
    if clean_sym in COMMODITY_SYMBOLS or venue == "MCX":
        lot = STANDARD_LOT_SIZES.get(clean_sym, 1)
        return CanonicalInstrument(
            instrument_id=f"MCX:{clean_sym}:COMMODITY",
            symbol=clean_sym,
            exchange="MCX",
            segment="COMMODITY",
            instrument_type="COMMODITY",
            lot_size=lot,
            tick_size=0.05,
            currency="INR",
            is_tradable=True,
            status="ACTIVE",
        )

    # Detect Currency Pairs
    if clean_sym in CURRENCY_SYMBOLS or venue == "CDS":
        lot = STANDARD_LOT_SIZES.get(clean_sym, 1000)
        return CanonicalInstrument(
            instrument_id=f"CDS:{clean_sym}:CURRENCY",
            symbol=clean_sym,
            exchange="CDS",
            segment="CURRENCY",
            instrument_type="FUTURE",
            lot_size=lot,
            tick_size=0.0025,
            currency="INR",
            is_tradable=True,
            status="ACTIVE",
        )

    # Default: NSE/BSE Equity
    lot = STANDARD_LOT_SIZES.get(clean_sym, 1)
    return CanonicalInstrument(
        instrument_id=f"{venue}:{clean_sym}:EQUITY",
        symbol=clean_sym,
        exchange=venue,
        segment="EQUITY",
        instrument_type="EQUITY",
        lot_size=lot,
        tick_size=0.05,
        currency="INR",
        is_tradable=True,
        status="ACTIVE",
    )


def get_market_session_state(
    exchange: Venue = "NSE",
    now_utc: Optional[datetime] = None,
) -> MarketSessionState:
    """
    Evaluate the live exchange operational session state for NSE, BSE, MCX, or CDS.

    Market Hours:
      - NSE / BSE: Pre-Open 09:00-09:15 IST | Open 09:15-15:30 IST | Post-Close 15:30-16:00 IST
      - MCX: Open 09:00-23:30 IST
      - CDS: Open 09:00-17:00 IST
      - Weekends (Saturday, Sunday): CLOSED
    """
    ist_now = get_current_ist_time(now_utc)
    weekday = ist_now.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
    current_t = ist_now.time()
    as_of_str = ist_now.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    formatted_time = ist_now.strftime("%H:%M:%S IST")

    # Weekend check
    if weekday in (5, 6):
        return MarketSessionState(
            exchange=exchange,
            session_state="CLOSED",
            is_open=False,
            as_of_ist=as_of_str,
            current_time_ist=formatted_time,
            session_open_ist="09:15:00 IST",
            session_close_ist="15:30:00 IST",
            reason="Market closed on weekends",
        )

    # Exchange Specific Timings
    if exchange in ("NSE", "BSE", "NSE_IFSC"):
        pre_open_start = dtime(9, 0)
        open_time = dtime(9, 15)
        close_time = dtime(15, 30)
        post_close_end = dtime(16, 0)

        if current_t < pre_open_start:
            return MarketSessionState(
                exchange=exchange,
                session_state="CLOSED",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:15:00 IST",
                session_close_ist="15:30:00 IST",
                reason="Pre-market hours (opens 09:15 IST)",
            )
        elif pre_open_start <= current_t < open_time:
            return MarketSessionState(
                exchange=exchange,
                session_state="PRE_OPEN",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:15:00 IST",
                session_close_ist="15:30:00 IST",
                reason="Exchange pre-open order matching session",
            )
        elif open_time <= current_t <= close_time:
            return MarketSessionState(
                exchange=exchange,
                session_state="OPEN",
                is_open=True,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:15:00 IST",
                session_close_ist="15:30:00 IST",
            )
        elif close_time < current_t <= post_close_end:
            return MarketSessionState(
                exchange=exchange,
                session_state="POST_CLOSE",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:15:00 IST",
                session_close_ist="15:30:00 IST",
                reason="Post-closing session",
            )
        else:
            return MarketSessionState(
                exchange=exchange,
                session_state="CLOSED",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:15:00 IST",
                session_close_ist="15:30:00 IST",
                reason="Market closed for the day",
            )

    elif exchange == "MCX":
        mcx_open = dtime(9, 0)
        mcx_close = dtime(23, 30)

        if mcx_open <= current_t <= mcx_close:
            return MarketSessionState(
                exchange=exchange,
                session_state="OPEN",
                is_open=True,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:00:00 IST",
                session_close_ist="23:30:00 IST",
            )
        else:
            return MarketSessionState(
                exchange=exchange,
                session_state="CLOSED",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:00:00 IST",
                session_close_ist="23:30:00 IST",
                reason="MCX evening session closed",
            )

    elif exchange == "CDS":
        cds_open = dtime(9, 0)
        cds_close = dtime(17, 0)

        if cds_open <= current_t <= cds_close:
            return MarketSessionState(
                exchange=exchange,
                session_state="OPEN",
                is_open=True,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:00:00 IST",
                session_close_ist="17:00:00 IST",
            )
        else:
            return MarketSessionState(
                exchange=exchange,
                session_state="CLOSED",
                is_open=False,
                as_of_ist=as_of_str,
                current_time_ist=formatted_time,
                session_open_ist="09:00:00 IST",
                session_close_ist="17:00:00 IST",
                reason="Currency derivatives market closed",
            )

    return MarketSessionState(
        exchange=exchange,
        session_state="CLOSED",
        is_open=False,
        as_of_ist=as_of_str,
        current_time_ist=formatted_time,
        session_open_ist="09:15:00 IST",
        session_close_ist="15:30:00 IST",
    )
