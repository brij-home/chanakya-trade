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

# Standard Indian F&O, Commodity & Currency Lot Sizes (Official NSE/BSE/MCX October 2026 Master: 219 NSE Derivatives + Indices + Commodities + Currencies)
STANDARD_LOT_SIZES: dict[str, int] = {
    # ── Benchmark & Sectoral Indices ──────────────────────────────────────────
    "NIFTY": 65,
    "NIFTY 50": 65,
    "NIFTY50": 65,
    "^NSEI": 65,
    "NSEI": 65,
    "CNX NIFTY": 65,
    "BANKNIFTY": 30,
    "NIFTY BANK": 30,
    "^NSEBANK": 30,
    "NSEBANK": 30,
    "FINNIFTY": 60,
    "NIFTY FINANCIAL SERVICES": 60,
    "MIDCPNIFTY": 120,
    "NIFTY MID SELECT": 120,
    "NIFTYNXT50": 25,
    "NIFTYFPI": 1100,
    "SENSEX": 20,
    "BANKEX": 30,

    # ── MCX Commodities ──────────────────────────────────────────────────────
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,
    "NATURALGAS": 1250,
    "NATGASMINI": 250,
    "GOLD": 100,
    "GOLDM": 10,
    "GOLDPETAL": 1,
    "SILVER": 30,
    "SILVERM": 5,
    "SILVERMIC": 1,
    "COPPER": 2500,
    "ZINC": 5000,
    "ALUMINIUM": 5000,
    "LEAD": 5000,
    "COTTON": 25,

    # ── Currency Derivatives ──────────────────────────────────────────────────
    "USDINR": 1000,
    "EURINR": 1000,
    "GBPINR": 1000,
    "JPYINR": 1000,

    # ── NSE Single-Stock F&O Equities ─────────────────────────────────────────
    "360ONE": 500,
    "ABB": 125,
    "ABCAPITAL": 3100,
    "ADANIENSOL": 675,
    "ADANIENT": 309,
    "ADANIGREEN": 600,
    "ADANIPORTS": 475,
    "ADANIPOWER": 3550,
    "ALKEM": 125,
    "AMBER": 100,
    "AMBUJACEM": 1200,
    "ANANDRATHI": 250,
    "ANGELONE": 2500,
    "APLAPOLLO": 350,
    "APOLLOHOSP": 125,
    "ASHOKLEY": 5000,
    "ASIANPAINT": 250,
    "ASTRAL": 425,
    "ATHERENERG": 375,
    "AUBANK": 1000,
    "AUROPHARMA": 550,
    "AXISBANK": 625,
    "BAJAJ-AUTO": 75,
    "BAJAJFINSV": 300,
    "BAJAJHLDNG": 75,
    "BAJFINANCE": 750,
    "BANDHANBNK": 3600,
    "BANKBARODA": 2925,
    "BANKINDIA": 5200,
    "BDL": 425,
    "BEL": 1425,
    "BHARATFORG": 500,
    "BHARTIARTL": 475,
    "BHEL": 2625,
    "BIOCON": 2500,
    "BLUESTARCO": 325,
    "BOSCHLTD": 25,
    "BPCL": 1975,
    "BRITANNIA": 125,
    "BSE": 200,
    "CAMS": 825,
    "CANBK": 6750,
    "CDSL": 475,
    "CGPOWER": 850,
    "CHOLAFIN": 625,
    "CIPLA": 425,
    "COALINDIA": 1350,
    "COCHINSHIP": 400,
    "COFORGE": 475,
    "COLPAL": 275,
    "CONCOR": 1250,
    "CROMPTON": 2150,
    "CUMMINSIND": 200,
    "DABUR": 1250,
    "DELHIVERY": 2075,
    "DIVISLAB": 100,
    "DIXON": 50,
    "DLF": 950,
    "DMART": 150,
    "DRREDDY": 625,
    "EICHERMOT": 100,
    "ENRIN": 175,
    "ETERNAL": 2425,
    "FEDERALBNK": 2500,
    "FORCEMOT": 25,
    "FORTIS": 775,
    "GAIL": 3550,
    "GLENMARK": 375,
    "GMRAIRPORT": 6975,
    "GODFRYPHLP": 275,
    "GODREJCP": 500,
    "GODREJPROP": 325,
    "GRASIM": 250,
    "GVT&D": 125,
    "HAL": 150,
    "HAVELLS": 500,
    "HCLTECH": 400,
    "HDFCAMC": 300,
    "HDFCBANK": 650,
    "HDFCLIFE": 1100,
    "HEROMOTOCO": 150,
    "HINDALCO": 700,
    "HINDPETRO": 2025,
    "HINDUNILVR": 300,
    "HINDZINC": 1225,
    "HYUNDAI": 275,
    "ICICIBANK": 700,
    "ICICIGI": 325,
    "ICICIPRULI": 925,
    "IDEA": 71475,
    "IDFCFIRSTB": 9275,
    "IEX": 4350,
    "INDHOTEL": 1000,
    "INDIANB": 1000,
    "INDIGO": 150,
    "INDUSINDBK": 700,
    "INDUSTOWER": 1700,
    "INFY": 400,
    "INOXWIND": 6400,
    "IOC": 4875,
    "IREDA": 4525,
    "IRFC": 5425,
    "ITC": 1725,
    "JINDALSTEL": 625,
    "JIOFIN": 2350,
    "JSWENERGY": 1075,
    "JSWSTEEL": 675,
    "JUBLFOOD": 1250,
    "KALYANKJIL": 1350,
    "KAYNES": 150,
    "KEI": 175,
    "KFINTECH": 575,
    "KOTAKBANK": 2000,
    "KPITTECH": 775,
    "LAURUSLABS": 850,
    "LICHSGFIN": 1000,
    "LICI": 1400,
    "LODHA": 625,
    "LT": 175,
    "LTF": 2250,
    "LTM": 150,
    "LUPIN": 425,
    "M&M": 200,
    "MAHABANK": 6500,
    "MANAPPURAM": 3000,
    "MANKIND": 250,
    "MARICO": 1200,
    "MARUTI": 50,
    "MAXHEALTH": 525,
    "MAZDOCK": 225,
    "MCX": 225,
    "MFSL": 400,
    "MOTHERSON": 6150,
    "MOTILALOFS": 775,
    "MPHASIS": 275,
    "MUTHOOTFIN": 275,
    "NAM-INDIA": 625,
    "NATIONALUM": 1875,
    "NAUKRI": 550,
    "NBCC": 6500,
    "NESTLEIND": 500,
    "NHPC": 6950,
    "NMDC": 6750,
    "NTPC": 1500,
    "NYKAA": 3125,
    "OBEROIRLTY": 350,
    "OFSS": 100,
    "OIL": 1400,
    "ONGC": 2250,
    "PAGEIND": 20,
    "PATANJALI": 1075,
    "PAYTM": 725,
    "PERSISTENT": 125,
    "PETRONET": 1900,
    "PFC": 1300,
    "PGEL": 950,
    "PHOENIXLTD": 350,
    "PIDILITIND": 500,
    "PIIND": 175,
    "PNB": 8000,
    "PNBHOUSING": 650,
    "POLICYBZR": 350,
    "POLYCAB": 125,
    "POWERGRID": 1900,
    "POWERINDIA": 25,
    "PREMIERENE": 650,
    "PRESTIGE": 450,
    "RADICO": 150,
    "RBLBANK": 3175,
    "RECLTD": 1575,
    "RELIANCE": 500,
    "RVNL": 1925,
    "SAGILITY": 12000,
    "SAIL": 4700,
    "SBICARD": 800,
    "SBILIFE": 375,
    "SBIN": 750,
    "SHREECEM": 25,
    "SHRIRAMFIN": 825,
    "SIEMENS": 175,
    "SOLARINDS": 50,
    "SONACOMS": 1225,
    "SRF": 200,
    "SUNPHARMA": 350,
    "SUPREMEIND": 175,
    "SUZLON": 12700,
    "SWIGGY": 1825,
    "TATACONSUM": 550,
    "TATAELXSI": 125,
    "TATAMOTORS": 575,
    "TATAPOWER": 1450,
    "TATASTEEL": 2750,
    "TCS": 225,
    "TECHM": 600,
    "TIINDIA": 200,
    "TITAN": 175,
    "TMPV": 1600,
    "TORNTPHARM": 125,
    "TRENT": 225,
    "TVSMOTOR": 175,
    "UJJIVANSFB": 8000,
    "ULTRACEMCO": 50,
    "UNIONBANK": 4425,
    "UNITDSPR": 400,
    "UNOMINDA": 550,
    "UPL": 1355,
    "VBL": 1275,
    "VEDL": 1150,
    "VMM": 4850,
    "VOLTAS": 375,
    "WAAREEENER": 175,
    "WIPRO": 3000,
    "YESBANK": 31100,
    "ZYDUSLIFE": 900,
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

    # Detect F&O Derivative vs Cash Equity
    import re
    is_option = bool(re.search(r"\d+(?:CE|PE)$", clean_sym))
    is_future = clean_sym.endswith("FUT") or clean_sym.endswith("FUTURES")
    is_fno = venue in ("NFO", "BFO") or is_option or is_future
    if is_fno:
        und = clean_sym
        if is_option or is_future:
            match = re.match(r"^([A-Za-z0-9_&]+?)(?:\d{2}[A-Z]{3}|\d{5})", clean_sym)
            if match:
                und = match.group(1).upper()
            else:
                und = re.split(r"\d", clean_sym)[0].upper().rstrip("FUT")
        lot = STANDARD_LOT_SIZES.get(clean_sym, STANDARD_LOT_SIZES.get(und, 1))
        seg = "FNO"
        itype = "OPTION" if is_option else "FUTURE"
        return CanonicalInstrument(
            instrument_id=f"{venue}:{clean_sym}:{seg}",
            symbol=clean_sym,
            exchange=venue,
            segment=seg,
            instrument_type=itype,
            lot_size=lot,
            tick_size=0.05,
            currency="INR",
            is_tradable=True,
            status="ACTIVE",
            underlying=und if und != clean_sym else None,
        )

    # Default: NSE/BSE Cash Equity (Always trades in units of 1 share)
    return CanonicalInstrument(
        instrument_id=f"{venue}:{clean_sym}:EQUITY",
        symbol=clean_sym,
        exchange=venue,
        segment="EQUITY",
        instrument_type="EQUITY",
        lot_size=1,
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


def get_fno_lot_size(symbol: str) -> int:
    """
    Return the canonical institutional F&O contract lot size for a symbol.
    Queries the centralized STANDARD_LOT_SIZES exchange master (SSOT).
    Falls back to 1 for equities without F&O contracts.
    """
    clean = (symbol or "").upper().split(":")[-1].strip()
    # Normalize index aliases if present
    alias_map = {
        "NIFTY 50": "NIFTY",
        "NIFTY50": "NIFTY",
        "NSEI": "NIFTY",
        "CNX NIFTY": "NIFTY",
        "NIFTY BANK": "BANKNIFTY",
        "NSEBANK": "BANKNIFTY",
        "NIFTY FINANCIAL SERVICES": "FINNIFTY",
        "NIFTY MID SELECT": "MIDCPNIFTY",
    }
    canonical = alias_map.get(clean, clean)
    return STANDARD_LOT_SIZES.get(canonical, STANDARD_LOT_SIZES.get(clean, 1))

