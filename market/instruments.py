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

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal, Optional

from config.constants import IST

# Standard IST timezone offset (+05:30)
IST_OFFSET = IST

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
    "ABREL": 450,
    "CENTURYTEX": 450,
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
    "ICICILIFE": 925,
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

# Canonical Corporate Restructuring, Demerger, and Renaming Aliases (October 2026 Master)
CORPORATE_ALIASES: dict[str, str] = {
    # Commercial & Colloquial Aliases to Official Exchange Tickers
    "INFOSYS": "INFY",  # Infosys Ltd
    "BAJAJFINANCE": "BAJFINANCE",  # Bajaj Finance Ltd
    "BAJAJFINSERV": "BAJFINSV",  # Bajaj Finserv Ltd
    "HUL": "HINDUNILVR",  # Hindustan Unilever Ltd
    "AIRTEL": "BHARTIARTL",  # Bharti Airtel Ltd
    "BHARTI": "BHARTIARTL",
    "ULTRATECH": "ULTRACEMCO",  # UltraTech Cement Ltd
    "ULTRATECHCEMENT": "ULTRACEMCO",
    "EICHER": "EICHERMOT",  # Eicher Motors Ltd
    "EICHERMOTORS": "EICHERMOT",
    "HERO": "HEROMOTOCO",  # Hero MotoCorp Ltd
    "HEROHONDA": "HEROMOTOCO",
    "ASIANPAINTS": "ASIANPAINT",  # Asian Paints Ltd
    "DRREDDYS": "DRREDDY",  # Dr. Reddy's Laboratories
    "APOLLOHOSPITALS": "APOLLOHOSP",  # Apollo Hospitals Enterprise
    "TATACONSUMER": "TATACONSUM",  # Tata Consumer Products
    "MM": "M&M",  # Mahindra & Mahindra
    "M_M": "M&M",
    # Corporate Restructuring, Demerger, and Renaming Aliases
    "TATAMOTORS": "TMPV",  # Demerged into TMPV (PV) & TMCV (CV)
    "ZOMATO": "ETERNAL",  # Rebranded to Eternal Ltd
    "CENTURYTEX": "ABREL",  # Aditya Birla Real Estate
    "UNOINDA": "UNOMINDA",  # Uno Minda Ltd
    "REC": "RECLTD",  # REC Ltd
    "CEINFO": "MAPMYINDIA",  # C.E. Info Systems (MapMyIndia)
    "ASTRA": "ASTRAMICRO",  # Astra Microwave Products
    "SWANENERGY": "SWANCORP",  # Swan Energy / Swan Corp
    "CAPLIPHARM": "CAPLIPOINT",  # Caplin Point Laboratories
    "RPGPHILIFE": "RPGLIFE",  # RPG Life Sciences
    "METRO": "METROBRAND",  # Metro Brands
    "HITACHI": "POWERINDIA",  # Hitachi Energy India (Power India)
    "KALPATPOWR": "KPIL",  # Kalpataru Projects International
    "KBL": "KIRLOSBROS",  # Kirloskar Brothers Ltd
    "GSHIP": "GESHIP",  # Great Eastern Shipping
    "JUPITERWAG": "JWL",  # Jupiter Wagons Ltd
    "L&TFH": "LTF",  # L&T Finance Ltd (formerly L&T Finance Holdings)
    "LTFH": "LTF",
    "IBULHSGFIN": "SAMMAANCAP",  # Sammaan Capital (formerly Indiabulls Housing Finance)
    "MOTHERSUMI": "MOTHERSON",  # Samvardhana Motherson International
    "CADILAHC": "ZYDUSLIFE",  # Zydus Lifesciences
    "LTI": "LTIM",  # LTIMindtree
    "MINDTREE": "LTIM",
    "LTM": "LTIM",
    "PVR": "PVRINOX",  # PVR INOX Ltd
    "INOXLEISUR": "PVRINOX",
    "SRTRANSFIN": "SHRIRAMFIN",  # Shriram Finance (merged with Shriram Transport)
    "WELSPUNIND": "WELSPUNLIV",  # Welspun Living
    "IDFC": "IDFCFIRSTB",  # Merged into IDFC First Bank
    "HDFC": "HDFCBANK",  # Merged into HDFC Bank
    "ADANITRANS": "ADANIENSOL",  # Adani Transmission renamed to Adani Energy Solutions
    "MCDOWELL-N": "UNITDSPR",  # United Spirits (McDowell)
    "L&T": "LT",  # Larsen & Toubro
    "NAMINDIA": "NAM-INDIA",  # Nippon Life India Asset Management
    "BAJAJAUTO": "BAJAJ-AUTO",  # Bajaj Auto
    "BAJAJ_AUTO": "BAJAJ-AUTO",
    "TATASTEELBSL": "TATASTEEL",  # Tata Steel BSL merged into Tata Steel
    "NSLNISP": "NMDCSTEEL",  # NMDC Steel
    "NMDCSTEEL": "NSLNISP",  # NMDC Steel listed on NSE/Fyers as NSLNISP
    "ICICIPRULI": "ICICILIFE",  # ICICI Prudential Life Insurance -> ICICILIFE on Fyers / derivatives
    "HEG": "HEGAM",  # HEG Ltd demerger into HEGAM
    "SILLYMONKS": "CRESTO",  # Silly Monks Entertainment renamed to Cresto
}

# Known Active NSE Trade-for-Trade (BE Series) Stocks in Top Benchmarks (Advisory fallback; prefer market.symbol_master)
BE_SERIES_STOCKS: frozenset[str] = frozenset(
    {
        "DIACABS",
        "HFCL",
        "LOTUSDEV",
        "RAMASTEEL",
        "STLTECH",
    }
)

_KNOWN_VENUE_PREFIXES: tuple[str, ...] = (
    "NSE:",
    "BSE:",
    "MCX:",
    "NFO:",
    "BFO:",
    "CDS:",
    "CRYPTO:",
    "BINANCE:",
    "DERIBIT:",
    "FX:",
    "FOREX:",
)


@lru_cache(maxsize=4096)
def resolve_corporate_alias(symbol: str) -> str:
    """Resolve symbol through canonical corporate action / renaming alias master.

    Handles:
      - Bare symbols: 'ZOMATO' -> 'ETERNAL', 'ICICIPRULI' -> 'ICICILIFE'
      - Qualified symbols: 'NSE:ZOMATO-EQ' -> 'NSE:ETERNAL-EQ'
      - Suffix-only symbols: 'ZOMATO-EQ' -> 'ETERNAL-EQ'
      - Prefix-only symbols: 'NSE:ZOMATO' -> 'NSE:ETERNAL'
    """
    clean = (symbol or "").strip().upper()
    if not clean:
        return ""
    if clean in CORPORATE_ALIASES:
        return CORPORATE_ALIASES[clean]

    prefix = ""
    for pfx in _KNOWN_VENUE_PREFIXES:
        if clean.startswith(pfx):
            prefix = pfx
            clean = clean[len(pfx) :]
            break

    suffix = ""
    for sfx in ("-EQ", "-BE", "-SM", "-BZ", "-GB", "-INDEX"):
        if clean.endswith(sfx):
            suffix = sfx
            clean = clean[: -len(sfx)]
            break

    resolved = CORPORATE_ALIASES.get(clean, clean)
    return f"{prefix}{resolved}{suffix}"


_INDEX_CANONICAL_MAP: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY50": "NIFTY",
    "CNX NIFTY": "NIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "FIN NIFTY": "FINNIFTY",
    "FINNIFTY": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "MIDCAP NIFTY": "MIDCPNIFTY",
    "MIDCP NIFTY": "MIDCPNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
    "NIFTY IT": "NIFTYIT",
    "NIFTYIT": "NIFTYIT",
    "CNXIT": "NIFTYIT",
    "INDIA VIX": "INDIAVIX",
    "INDIAVIX": "INDIAVIX",
    "BSE SENSEX": "SENSEX",
    "BSE BANKEX": "BANKEX",
    "NSEI": "NIFTY",
    "NSEBANK": "BANKNIFTY",
    "BSESN": "SENSEX",
}


@lru_cache(maxsize=4096)
def canonical_symbol(raw_symbol: str) -> str:
    """
    Universal Institutional Symbol Normalizer (SSOT).
    Normalizes any asset symbol into its canonical clean uppercase identifier:
      1. Strips broker/exchange prefixes (NSE:, BSE:, MCX:, NFO:, BFO:, CDS:, CRYPTO:, BINANCE:, DERIBIT:).
      2. Strips data vendor suffixes (.NS, .BO).
      3. Strips broker series suffixes (-EQ, -BE, -INDEX, -SM, -BZ, -GB, -A, -B).
      4. Strips index markers (^).
      5. Resolves corporate actions via CORPORATE_ALIASES (e.g. TATAMOTORS -> TMPV, ZOMATO -> ETERNAL).
      6. Maps standard index aliases to canonical identifiers (e.g. NIFTY 50 -> NIFTY).
    """
    if not raw_symbol:
        return ""
    s = str(raw_symbol).strip().upper()
    for pfx in _KNOWN_VENUE_PREFIXES:
        if s.startswith(pfx):
            s = s[len(pfx) :]
            break
    if s.endswith(".NS"):
        s = s[:-3]
    elif s.endswith(".BO"):
        s = s[:-3]
    for sfx in ("-INDEX", "-EQ", "-BE", "-SM", "-BZ", "-GB", "-A", "-B"):
        if s.endswith(sfx):
            s = s[: -len(sfx)]
            break
    if s.startswith("^"):
        s = s[1:]
    s = s.strip()
    s = resolve_corporate_alias(s)
    return _INDEX_CANONICAL_MAP.get(s, s)


WEEKLY_MONTH_CODES: dict[str, int] = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "O": 10,
    "N": 11,
    "D": 12,
}

MONTH_NAME_TO_INT: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_ISO_OPT_RE = re.compile(
    r"^([A-Za-z0-9_&]+?)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d+(?:\.\d+)?)(CE|PE)$"
)
_WEEKLY_OPT_RE = re.compile(
    r"^([A-Za-z0-9_&]+?)(\d{2})([1-9ONDond])(0[1-9]|[12]\d|3[01])(\d+(?:\.\d+)?)(CE|PE)$"
)
_MONTHLY_OPT_RE = re.compile(r"^([A-Za-z0-9_&]+?)(\d{2})([A-Za-z]{3})(\d+(?:\.\d+)?)(CE|PE)$")
_FUT_RE = re.compile(r"^([A-Za-z0-9_&]+?)(\d{2})([A-Za-z]{3})FUT$")
_SPACED_OPT_RE = re.compile(
    r"^([A-Za-z0-9_&]+)\s+(?:(\d{1,2}[A-Za-z]{3}|\d{2}[A-Za-z]{3})\s+)?(\d+(?:\.\d+)?)\s*(CE|PE|FUT)$"
)


@dataclass(frozen=True)
class ParsedDerivativeContract:
    raw_symbol: str
    exchange: str
    underlying: str
    contract_type: str  # "CE" | "PE" | "FUT"
    strike: Optional[float]
    expiry_date: Optional[date]
    expiry_tag: str
    is_option: bool
    is_future: bool
    is_weekly: bool
    lot_size: int
    tick_size: float
    strike_step: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_symbol": self.raw_symbol,
            "exchange": self.exchange,
            "underlying": self.underlying,
            "contract_type": self.contract_type,
            "strike": self.strike,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "expiry_tag": self.expiry_tag,
            "is_option": self.is_option,
            "is_future": self.is_future,
            "is_weekly": self.is_weekly,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
            "strike_step": self.strike_step,
        }


def _calc_monthly_expiry_date(exch: str, underlying: str, yr: int, mo: int) -> date:
    """Calculate the precise monthly expiry date for NSE, BSE, MCX, or CDS with calendar adjustment."""
    from calendar import monthrange

    _, num_days = monthrange(yr, mo)
    exch_up = (exch or "NSE").upper()
    und_up = underlying.upper()
    if exch_up == "BSE" or und_up in ("SENSEX", "BANKEX"):
        d = date(yr, mo, num_days)
        while d.weekday() != 4:  # Last Friday
            d -= timedelta(days=1)
    elif exch_up == "MCX" or und_up in COMMODITY_SYMBOLS:
        if "CRUDE" in und_up:
            exp_day = min(19, num_days)
            d = date(yr, mo, exp_day)
        else:
            d = date(yr, mo, num_days)
    else:
        d = date(yr, mo, num_days)
        while d.weekday() != 3:  # Last Thursday
            d -= timedelta(days=1)
    try:
        from market.calendar import get_adjusted_expiry_date

        venue = (
            "BSE"
            if (exch_up == "BSE" or und_up in ("SENSEX", "BANKEX"))
            else ("MCX" if (exch_up == "MCX" or und_up in COMMODITY_SYMBOLS) else "NFO")
        )
        return get_adjusted_expiry_date(d, venue)
    except Exception:
        return d


@lru_cache(maxsize=4096)
def parse_derivative_contract(symbol: str) -> Optional[ParsedDerivativeContract]:
    """
    Authoritative Derivative Contract Parser (SSOT).
    Parses any Indian equity, index, commodity, or currency derivative symbol (NSE, BSE, MCX, CDS).
    """
    if not symbol or not isinstance(symbol, str):
        return None
    s = symbol.strip()
    exch = "NSE"
    if ":" in s:
        parts = s.split(":", 1)
        exch = parts[0].upper().strip()
        clean = parts[1].strip()
    else:
        clean = s

    # 1. Broker YYYYMMDD Option (e.g. HAL202609294800PE, ASHOKLEY20261126142.5PE)
    m_iso = _ISO_OPT_RE.match(clean)
    if m_iso:
        und_raw, yyyy, mm, dd, stk_str, opt_type = m_iso.groups()
        und = canonical_symbol(und_raw)
        stk = float(stk_str)
        try:
            exp_d = date(int(yyyy), int(mm), int(dd))
        except ValueError:
            exp_d = None
        exp_tag = f"{yyyy[2:]}{mm}{dd}"
        lot = get_fno_lot_size(und)
        tick = STANDARD_TICK_SIZES.get("FNO", 0.05)
        from market.symbol_master import get_strike_step

        step = get_strike_step(und, spot=stk)
        return ParsedDerivativeContract(
            raw_symbol=symbol,
            exchange=exch,
            underlying=und,
            contract_type=opt_type.upper(),
            strike=stk,
            expiry_date=exp_d,
            expiry_tag=exp_tag,
            is_option=True,
            is_future=False,
            is_weekly=False,
            lot_size=lot,
            tick_size=tick,
            strike_step=step,
        )

    # 2. Weekly Option (e.g. NIFTY26O1922900CE or SENSEX26O0872000PE)
    m_w = _WEEKLY_OPT_RE.match(clean)
    if m_w:
        und_raw, yy, mo_code, dd, stk_str, opt_type = m_w.groups()
        und = canonical_symbol(und_raw)
        yr = 2000 + int(yy)
        mo = WEEKLY_MONTH_CODES.get(mo_code.upper(), 1)
        stk = float(stk_str)
        try:
            exp_d = date(yr, mo, int(dd))
        except ValueError:
            exp_d = None
        exp_tag = f"{yy}{mo_code}{dd}"
        lot = get_fno_lot_size(und)
        tick = STANDARD_TICK_SIZES.get("FNO", 0.05)
        from market.symbol_master import get_strike_step

        step = get_strike_step(und, spot=stk)
        return ParsedDerivativeContract(
            raw_symbol=symbol,
            exchange=exch,
            underlying=und,
            contract_type=opt_type.upper(),
            strike=stk,
            expiry_date=exp_d,
            expiry_tag=exp_tag,
            is_option=True,
            is_future=False,
            is_weekly=True,
            lot_size=lot,
            tick_size=tick,
            strike_step=step,
        )

    # 2. Monthly Option (e.g. NIFTY26OCT23000CE, CRUDEOIL26NOV6500CE)
    m_m = _MONTHLY_OPT_RE.match(clean)
    if m_m:
        und_raw, yy, mo_str, stk_str, opt_type = m_m.groups()
        und = canonical_symbol(und_raw)
        yr = 2000 + int(yy)
        mo = MONTH_NAME_TO_INT.get(mo_str.upper(), 1)
        stk = float(stk_str)
        exp_d = _calc_monthly_expiry_date(exch, und, yr, mo)
        exp_tag = f"{yy}{mo_str.upper()}"
        lot = get_fno_lot_size(und)
        tick = STANDARD_TICK_SIZES.get("FNO", 0.05)
        from market.symbol_master import get_strike_step

        step = get_strike_step(und, spot=stk)
        return ParsedDerivativeContract(
            raw_symbol=symbol,
            exchange=exch,
            underlying=und,
            contract_type=opt_type.upper(),
            strike=stk,
            expiry_date=exp_d,
            expiry_tag=exp_tag,
            is_option=True,
            is_future=False,
            is_weekly=False,
            lot_size=lot,
            tick_size=tick,
            strike_step=step,
        )

    # 3. Monthly Future (e.g. NIFTY26OCTFUT, GOLD26OCTFUT)
    m_f = _FUT_RE.match(clean)
    if m_f:
        und_raw, yy, mo_str = m_f.groups()
        und = canonical_symbol(und_raw)
        yr = 2000 + int(yy)
        mo = MONTH_NAME_TO_INT.get(mo_str.upper(), 1)
        exp_d = _calc_monthly_expiry_date(exch, und, yr, mo)
        exp_tag = f"{yy}{mo_str.upper()}"
        lot = get_fno_lot_size(und)
        tick = STANDARD_TICK_SIZES.get("FNO", 0.05)
        from market.symbol_master import get_strike_step

        step = get_strike_step(und, spot=0.0)
        return ParsedDerivativeContract(
            raw_symbol=symbol,
            exchange=exch,
            underlying=und,
            contract_type="FUT",
            strike=None,
            expiry_date=exp_d,
            expiry_tag=exp_tag,
            is_option=False,
            is_future=True,
            is_weekly=False,
            lot_size=lot,
            tick_size=tick,
            strike_step=step,
        )

    # 4. Spaced format (e.g. "NIFTY 24800 CE", "MIDCPNIFTY 14250 PE")
    m_s = _SPACED_OPT_RE.match(clean)
    if m_s:
        und_raw, exp_raw, stk_str, opt_type = m_s.groups()
        und = canonical_symbol(und_raw)
        stk = float(stk_str) if stk_str else None
        opt_up = opt_type.upper()
        is_opt = opt_up in ("CE", "PE")
        lot = get_fno_lot_size(und)
        tick = STANDARD_TICK_SIZES.get("FNO", 0.05)
        from market.symbol_master import get_strike_step

        step = get_strike_step(und, spot=stk or 0.0)
        return ParsedDerivativeContract(
            raw_symbol=symbol,
            exchange=exch,
            underlying=und,
            contract_type=opt_up,
            strike=stk,
            expiry_date=None,
            expiry_tag=exp_raw or "",
            is_option=is_opt,
            is_future=opt_up == "FUT",
            is_weekly=False,
            lot_size=lot,
            tick_size=tick,
            strike_step=step,
        )

    return None


def is_contract_expired(symbol: str, ref_dt: Optional[datetime] = None) -> bool:
    """
    Determine if a derivative contract is expired relative to current IST market time.
    Equities, benchmark indices, and cash symbols return False (never expire).
    """
    parsed = parse_derivative_contract(symbol)
    if not parsed or not parsed.expiry_date:
        return False
    from config.constants import IST_ZONE as IST

    now = ref_dt or datetime.now(IST)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        else:
            now = now.astimezone(IST)
        today = now.date()
        current_time = now.time()
    else:
        today = now
        current_time = dtime(16, 0)

    if today > parsed.expiry_date:
        return True
    if today < parsed.expiry_date:
        return False

    # Today is expiry date: verify session close cutoff
    exch = parsed.exchange
    if exch == "MCX":
        close_cutoff = dtime(23, 30)
    elif exch in ("CDS", "CURRENCY"):
        close_cutoff = dtime(17, 0)
    else:
        close_cutoff = dtime(15, 30)

    return current_time >= close_cutoff


# Standard Tick Sizes
STANDARD_TICK_SIZES: dict[str, float] = {
    "EQUITY": 0.05,
    "FNO": 0.05,
    "INDEX": 0.05,
    "COMMODITY": 0.05,
    "CURRENCY": 0.0025,
}

from config.market_universes import (
    MCX_COMMODITY_SYMBOLS,
    CDS_CURRENCY_SYMBOLS,
)

COMMODITY_SYMBOLS = set(MCX_COMMODITY_SYMBOLS) | {"MCXBULLDEX"}

CURRENCY_SYMBOLS = set(CDS_CURRENCY_SYMBOLS) | {
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


def resolve_canonical_instrument(query: str, price: Optional[float] = None) -> CanonicalInstrument:
    """
    Resolve and normalize any user/symbol query into a canonical instrument master record.
    Respects SEBI 1-paisa tick size rule for cash equities <= ₹250 when price is known.

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

    clean_sym = resolve_corporate_alias(clean_sym)

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
    # SEBI Circular: Cash equities trading at <= ₹250 have 1-paisa (₹0.01) tick size.
    equity_tick = 0.01 if (price is not None and price <= 250.0) else 0.05
    return CanonicalInstrument(
        instrument_id=f"{venue}:{clean_sym}:EQUITY",
        symbol=clean_sym,
        exchange=venue,
        segment="EQUITY",
        instrument_type="EQUITY",
        lot_size=1,
        tick_size=equity_tick,
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


@lru_cache(maxsize=1024)
def get_fno_lot_size(symbol: str) -> int:
    """
    Return the canonical institutional F&O contract lot size for a symbol.
    Queries the centralized STANDARD_LOT_SIZES exchange master (SSOT).
    Falls back to 1 for equities without F&O contracts.
    """
    clean = canonical_symbol(symbol)
    return STANDARD_LOT_SIZES.get(clean, 1)


@lru_cache(maxsize=2048)
def is_derivative_eligible(symbol: str) -> bool:
    """
    Return True if the instrument is an approved derivative underlying (F&O equity, index, MCX commodity, or currency).
    Queries the centralized STANDARD_LOT_SIZES and COMMODITY_SYMBOLS exchange masters (SSOT).
    Cash-only equities without derivative contracts return False.
    """
    clean = canonical_symbol(symbol)
    if not clean:
        return False

    if clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        return True
    if clean in COMMODITY_SYMBOLS or (symbol or "").upper().startswith("MCX:"):
        return True

    return clean in STANDARD_LOT_SIZES


def format_strike(strike: float | int | str | None) -> str:
    """
    Canonical Institutional Strike Formatter (SSOT).
    Preserves exact fractional strikes (e.g., 142.5 in ASHOKLEY, 7.5 in IDEA, 83.25 in USDINR)
    while cleanly stripping decimal points for integer strikes (e.g., 140.0 -> "140", 24500 -> "24500").
    """
    if strike is None:
        return ""
    if isinstance(strike, str) and not strike.strip():
        return ""
    try:
        val = float(str(strike).replace(",", "").strip())
        if val == int(val):
            return str(int(val))
        return f"{val:.4f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return str(strike).strip()
