"""
analysis/universe.py
────────────────────
Comprehensive Institutional Equities Taxonomy & Dynamic Universe Manager.

Features:
  1. Categorizes 250+ top liquid Indian equities across 11 key institutional sectors.
  2. Sub-industry classification, market cap tier (LARGE / MID / SMALL), and F&O status.
  3. Dynamic Top-Down Universe Resolver:
     - "auto_market_aware": Dynamically routes to the day's top RRG leading sectors.
     - "most_liquid_today": Top turnover & institutional favorites.
     - "volume_surges_rvol": Stocks with unusual volume expansion (RVOL >= 1.5x).
     - "multibagger_hunters": High-growth Stage 2 compounders.
     - Sector-specific presets (banking, it, auto, defence, energy, metals, pharma, fmcg, infra, chemicals).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass
class StockProfile:
    symbol: str
    name: str
    sector_id: str
    sector_name: str
    sub_industry: str
    cap_tier: str  # "LARGE" | "MID" | "SMALL"
    is_fo: bool = True
    beta: float = 1.0


# ── Complete Institutional Equities Taxonomy ────────────────────────

SECTOR_TAXONOMY: dict[str, dict[str, Any]] = {
    "banking": {
        "name": "Banking & Financial Services",
        "icon": "🏦",
        "index_symbol": "^NSEBANK",
        "description": "Private Banks, PSU Banks, High-ROE NBFCs, and Capital Markets infrastructure.",
        "symbols": [
            "HDFCBANK",
            "ICICIBANK",
            "SBIN",
            "KOTAKBANK",
            "AXISBANK",
            "INDUSINDBK",
            "FEDERALBNK",
            "AUBANK",
            "BANDHANBNK",
            "IDFCFIRSTB",
            "BANKBARODA",
            "PNB",
            "CANBK",
            "UNIONBANK",
            "BAJFINANCE",
            "BAJAJFINSV",
            "CHOLAFIN",
            "MUTHOOTFIN",
            "SHRIRAMFIN",
            "JIOFIN",
            "BSE",
            "MCX",
            "ANGELONE",
            "CDSL",
            "CAMS",
            "HDFCAMC",
        ],
    },
    "it": {
        "name": "IT, Software & Technology",
        "icon": "💻",
        "index_symbol": "^CNXIT",
        "description": "Tier-1 IT Giants, High-Growth ER&D Midcaps, EMS, and New-Age Tech Platforms.",
        "symbols": [
            "TCS",
            "INFY",
            "HCLTECH",
            "WIPRO",
            "TECHM",
            "COFORGE",
            "PERSISTENT",
            "MPHASIS",
            "KPITTECH",
            "TATAELXSI",
            "OFSS",
            "CYIENT",
            "ZOMATO",
            "NAUKRI",
            "MAPMYINDIA",
            "DIXON",
            "POLICYBZR",
            "AFFLE",
            "BSOFT",
            "CEINFO",
            "HAPPSTMNDS",
            "INTELLECT",
            "JUSTDIAL",
            "LATENTVIEW",
            "LTTS",
            "MASTEK",
            "NEWGEN",
            "RATEGAIN",
            "ROUTE",
            "SONATSOFTW",
            "TANLA",
            "ZENSARTECH",
            "KAYNES",
            "SYRMA",
        ],
    },
    "auto": {
        "name": "Automobiles & Mobility",
        "icon": "🚗",
        "index_symbol": "^CNXAUTO",
        "description": "4W & 2W OEMs, Commercial Vehicles, EV Components, and Tyres.",
        "symbols": [
            "TATAMOTORS",
            "MARUTI",
            "M&M",
            "BAJAJ-AUTO",
            "HEROMOTOCO",
            "EICHERMOT",
            "TVSMOTOR",
            "ASHOKLEY",
            "BHARATFORG",
            "MOTHERSON",
            "SONACOMS",
            "UNOINDA",
            "EXIDEIND",
            "MRF",
            "APOLLOTYRE",
            "BALKRISIND",
            "BOSCHLTD",
            "LANDMARK",
        ],
    },
    "defence": {
        "name": "Defence & Aerospace",
        "icon": "🛡️",
        "index_symbol": "^CNXINFRA",
        "description": "Defence PSUs, Precision Aerospace, Drones, Shipbuilders, and Electronic Warfare.",
        "symbols": [
            "HAL",
            "BEL",
            "MAZDOCK",
            "COCHINSHIP",
            "GRSE",
            "BDL",
            "DATAPATTNS",
            "ZENTEC",
            "SOLARINDS",
            "MTARTECH",
            "PARAS",
            "ASTRA",
            "CYIENTDLM",
        ],
    },
    "energy": {
        "name": "Energy, Power & Green Transition",
        "icon": "⚡",
        "index_symbol": "^CNXENERGY",
        "description": "Oil & Gas, Power Generation, Solar/Wind Renewables, and Power Financing.",
        "symbols": [
            "RELIANCE",
            "ONGC",
            "NTPC",
            "POWERGRID",
            "COALINDIA",
            "BPCL",
            "IOC",
            "GAIL",
            "ADANIGREEN",
            "ADANIENT",
            "ADANIPOWER",
            "TATAPOWER",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "PFC",
            "REC",
            "NHPC",
            "SJVN",
            "TORNTPOWER",
            "PREMIERENE",
            "WAAREEENER",
            "SWANENERGY",
        ],
    },
    "metals": {
        "name": "Metals & Mining",
        "icon": "⛏️",
        "index_symbol": "^CNXMETAL",
        "description": "Integrated Steel, Aluminium, Copper, Base Metals, Pipes, and Mining.",
        "symbols": [
            "TATASTEEL",
            "JSWSTEEL",
            "HINDALCO",
            "JINDALSTEL",
            "NMDC",
            "SAIL",
            "VEDL",
            "NATIONALUM",
            "HINDZINC",
            "APLLTD",
            "RATNAMANI",
            "JINDALSAW",
            "GALLANTT",
            "GRAVITA",
            "HINDCOPPER",
            "RAMASTEEL",
            "SARDAEN",
            "SHYAMMETL",
            "WELCORP",
        ],
    },
    "pharma": {
        "name": "Pharma & Healthcare",
        "icon": "💊",
        "index_symbol": "^CNXPHARMA",
        "description": "Global Formulations, CDMO/API, Multi-speciality Hospitals, and Diagnostics.",
        "symbols": [
            "SUNPHARMA",
            "DRREDDY",
            "CIPLA",
            "DIVISLAB",
            "APOLLOHOSP",
            "LUPIN",
            "TORNTPHARM",
            "ZYDUSLIFE",
            "MANKIND",
            "MAXHEALTH",
            "FORTIS",
            "MEDANTA",
            "LALPATHLAB",
            "SYNGENE",
            "GLENMARK",
            "BIOCON",
            "AUROPHARMA",
            "IPCALAB",
            "AARTIDRUGS",
            "ABBOTINDIA",
            "AJANTPHARM",
            "ALKEM",
            "ASTRAZEN",
            "BLISSGVS",
            "CAPLIPHARM",
            "ERIS",
            "FDC",
            "GLAXO",
            "GRANULES",
            "JBCHEPHARM",
            "KIMS",
            "LAURUSLABS",
            "MARKSANS",
            "NATCOPHARM",
            "NEULANDLAB",
            "PFIZER",
            "POLYMED",
            "RAINBOW",
            "RPGPHILIFE",
            "SANOFI",
            "SEQUENT",
            "STAR",
            "SUVENPHAR",
            "THYROCARE",
            "VIJAYA",
            "YATHARTH",
        ],
    },
    "fmcg": {
        "name": "FMCG, Retail & Consumption",
        "icon": "🛒",
        "index_symbol": "^CNXFMCG",
        "description": "Staples, Discretionary Retail, Quick-Service Restaurants, and Footwear.",
        "symbols": [
            "ITC",
            "HINDUNILVR",
            "NESTLEIND",
            "BRITANNIA",
            "TATACONSUM",
            "DABUR",
            "MARICO",
            "GODREJCP",
            "COLPAL",
            "VBL",
            "TRENT",
            "DMART",
            "TITAN",
            "JUBLFOOD",
            "DEVYANI",
            "METRO",
            "PAGEIND",
            "BATAINDIA",
            "RADICO",
            "ASIANPAINT",
            "CAMPUS",
            "CARYSIL",
            "DREAMFOLKS",
            "ETHOSLTD",
            "MANYAVAR",
            "SAPPHIRE",
            "WESTLIFE",
            "AVANTIFEED",
        ],
    },
    "realty": {
        "name": "Real Estate & Housing",
        "icon": "🏢",
        "index_symbol": "^CNXREALTY",
        "description": "Top Real Estate Developers, Residential & Commercial Absorption.",
        "symbols": [
            "DLF",
            "GODREJPROP",
            "OBEROIRLTY",
            "PRESTIGE",
            "PHOENIXLTD",
            "BRIGADE",
            "SOBHA",
            "CENTURYTEX",
        ],
    },
    "infra": {
        "name": "Infrastructure & Capital Goods",
        "icon": "🏗️",
        "index_symbol": "^CNXINFRA",
        "description": "Heavy Engineering, EPC, Capital Goods, Cables & Electricals, Pipes and Building Materials.",
        "symbols": [
            "LT",
            "POLYCAB",
            "KEI",
            "RRKABEL",
            "ABB",
            "SIEMENS",
            "CGPOWER",
            "BHEL",
            "THERMAX",
            "KNRCON",
            "PNCINFRA",
            "NCC",
            "VOLTAS",
            "HAVELLS",
            "ULTRACEMCO",
            "GRASIM",
            "ASTRAL",
            "APLAPOLLO",
            "APOLLOPIPE",
            "FINPIPE",
            "PRINCEPIPE",
            "SUPREMEIND",
            "AIAENG",
            "CUMMINSIND",
            "ELECON",
            "ELECTCAST",
            "ENGINERSIN",
            "GEPIL",
            "HITACHI",
            "HONAUT",
            "ISGEC",
            "KALPATPOWR",
            "KBL",
            "KEC",
            "KIRLOSENG",
            "PRAJIND",
            "SCHAEFFLER",
            "SCHNEIDER",
            "SKFINDIA",
            "TDPOWERSYS",
            "TECHNOE",
            "TIMKEN",
            "TRITURBINE",
            "VOLTAMP",
            "RESPONIND",
            "GSHIP",
            "SCI",
            "GVT&D",
        ],
    },
    "chemicals": {
        "name": "Specialty Chemicals & Agriculture",
        "icon": "🧪",
        "index_symbol": "^CNXCHEM",
        "description": "Fluorochemicals, Specialty Chem, Agrochemicals, and Fertilizers.",
        "symbols": [
            "PIIND",
            "SRF",
            "NAVINFLUOR",
            "DEEPAKNTR",
            "ATUL",
            "COROMANDEL",
            "UPL",
            "TATACHEM",
            "FLUOROCHEM",
            "AETHER",
            "FINEORG",
            "GUJGASLTD",
            "CHAMBLFERT",
            "DEEPAKFERT",
            "DHANUKA",
            "FACT",
            "GNFC",
            "GSFC",
            "HIKAL",
            "NFL",
            "RCF",
            "SHARDACROP",
            "SUMICHEM",
            "TATVA",
        ],
    },
    "telecom": {
        "name": "Telecom, Ports & Logistics",
        "icon": "📡",
        "index_symbol": "^CNXINFRA",
        "description": "Telecom Giants, Major Ports, Air & Surface Freight Logistics.",
        "symbols": [
            "BHARTIARTL",
            "ADANIPORTS",
            "CONCOR",
            "DELHIVERY",
            "BLUEDART",
            "PVRINOX",
            "SUNTV",
            "ZEEL",
            "INDIGO",
            "TATACOMM",
        ],
    },
    "railways": {
        "name": "Railways, Wagons & Metros",
        "icon": "🚆",
        "index_symbol": "^CNXINFRA",
        "description": "Vande Bharat Coaches, Freight Wagons, Metro Bogies, and Railway EPC.",
        "symbols": [
            "TITAGARH",
            "TEXRAIL",
            "JUPITERWAG",
            "RVNL",
            "IRFC",
            "IRCON",
            "RITES",
            "RAILTEL",
            "BEML",
        ],
    },
}


_UNIVERSES_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "universes"


def _load_bundled_universe_symbols(filename: str, fallback_symbols: list[str]) -> list[str]:
    """Loads official index constituent symbols from bundled data/universes JSON, falling back to static list."""
    try:
        p = _UNIVERSES_DATA_DIR / filename
        if not p.exists():
            p = Path("data/universes") / filename
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                syms = [
                    d["symbol"].strip().upper()
                    for d in data
                    if isinstance(d, dict) and d.get("symbol")
                ]
                if syms:
                    return syms
    except Exception:
        pass
    return fallback_symbols


def _load_bundled_company_names() -> dict[str, str]:
    """Loads comprehensive company names from bundled JSON files."""
    names = {}
    for fn in ("nse_all_eq.json", "nifty_total_market.json", "nifty500.json"):
        p = _UNIVERSES_DATA_DIR / fn
        if not p.exists():
            p = Path("data/universes") / fn
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for d in data:
                    sym = d.get("symbol", "").strip().upper()
                    name = d.get("name", "").strip()
                    if sym and name:
                        names[sym] = name
            except Exception:
                pass
    return names


# ── Thematic Universe Presets ───────────────────────────────────────

THEMATIC_PRESETS: dict[str, dict[str, Any]] = {
    "auto_market_aware": {
        "name": "⚡ Dynamic Top-Down (Leading Sectors)",
        "description": "Automatically scans stocks in the day's 2-3 leading sectors + institutional volume breakouts.",
        "symbols": [],  # dynamically resolved at runtime
    },
    "most_liquid_today": {
        "name": "💧 High Liquidity (Top Turnover)",
        "description": "Highest daily turnover institutional favorites with minimum slippage.",
        "symbols": [
            "RELIANCE",
            "HDFCBANK",
            "ICICIBANK",
            "INFY",
            "TCS",
            "SBIN",
            "BHARTIARTL",
            "TATAMOTORS",
            "LT",
            "AXISBANK",
            "BAJFINANCE",
            "KOTAKBANK",
            "MARUTI",
            "TITAN",
            "TRENT",
            "M&M",
            "SUNPHARMA",
            "NTPC",
            "POWERGRID",
            "COALINDIA",
            "TATASTEEL",
            "HAL",
            "BEL",
            "ADANIENT",
            "ZOMATO",
        ],
    },
    "volume_surges_rvol": {
        "name": "🚀 Unusual Volume Surges",
        "description": "Stocks displaying massive institutional volume spikes (RVOL >= 1.5x).",
        "symbols": [
            "TRENT",
            "HAL",
            "BEL",
            "MAZDOCK",
            "COCHINSHIP",
            "DIXON",
            "POLYCAB",
            "BSE",
            "MCX",
            "ZOMATO",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "PERSISTENT",
            "COFORGE",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "FEDERALBNK",
        ],
    },
    "nifty50": {
        "name": "🏆 NIFTY 50 Bluechips",
        "description": "Top 50 largecap market leaders representing the benchmark index.",
        "symbols": [
            "RELIANCE",
            "TCS",
            "HDFCBANK",
            "INFY",
            "ICICIBANK",
            "SBIN",
            "BHARTIARTL",
            "ITC",
            "LT",
            "KOTAKBANK",
            "AXISBANK",
            "TATAMOTORS",
            "MARUTI",
            "SUNPHARMA",
            "BAJFINANCE",
            "TITAN",
            "HINDUNILVR",
            "NTPC",
            "ONGC",
            "POWERGRID",
            "TATASTEEL",
            "COALINDIA",
            "ASIANPAINT",
            "M&M",
            "ADANIENT",
            "ADANIPORTS",
            "TECHM",
            "HCLTECH",
            "WIPRO",
            "ULTRACEMCO",
            "JSWSTEEL",
            "GRASIM",
            "HEROMOTOCO",
            "EICHERMOT",
            "BAJAJ-AUTO",
            "APOLLOHOSP",
            "DRREDDY",
            "CIPLA",
            "TRENT",
            "BEL",
            "HAL",
            "ZOMATO",
            "NESTLEIND",
            "BRITANNIA",
            "DIVISLAB",
            "HINDALCO",
            "BPCL",
            "SHRIRAMFIN",
            "TATACONSUM",
        ],
    },
    "nifty500": {
        "name": "🇮🇳 NIFTY 500 Comprehensive Universe",
        "description": "Top 500 Indian listed equities across Large, Mid, and Smallcap spectrum.",
        "symbols": _load_bundled_universe_symbols(
            "nifty500.json",
            [
                "RELIANCE",
                "TCS",
                "HDFCBANK",
                "INFY",
                "ICICIBANK",
                "SBIN",
                "BHARTIARTL",
                "ITC",
                "LT",
                "KOTAKBANK",
                "AXISBANK",
                "TATAMOTORS",
                "MARUTI",
                "SUNPHARMA",
                "BAJFINANCE",
                "TITAN",
                "HINDUNILVR",
                "NTPC",
                "ONGC",
                "POWERGRID",
                "TATASTEEL",
                "COALINDIA",
                "ASIANPAINT",
                "M&M",
                "ADANIENT",
                "ADANIPORTS",
                "TECHM",
                "HCLTECH",
                "WIPRO",
                "ULTRACEMCO",
                "JSWSTEEL",
                "GRASIM",
                "HEROMOTOCO",
                "EICHERMOT",
                "BAJAJ-AUTO",
                "APOLLOHOSP",
                "DRREDDY",
                "CIPLA",
                "TRENT",
                "BEL",
                "HAL",
                "ZOMATO",
                "NESTLEIND",
                "BRITANNIA",
                "DIVISLAB",
                "HINDALCO",
                "BPCL",
                "SHRIRAMFIN",
                "TATACONSUM",
                "INDUSINDBK",
                "DLF",
                "GODREJPROP",
                "OBEROIRLTY",
                "PRESTIGE",
                "POLYCAB",
                "KEI",
                "DIXON",
                "BSE",
                "MCX",
                "PERSISTENT",
                "COFORGE",
                "KPITTECH",
                "TATAELXSI",
                "OFSS",
                "MAXHEALTH",
                "MANKIND",
                "CHOLAFIN",
                "MUTHOOTFIN",
                "JIOFIN",
                "SUZLON",
                "INOXWIND",
                "IREDA",
                "PFC",
                "REC",
                "NHPC",
                "SJVN",
                "TORNTPOWER",
                "SOLARINDS",
                "MAZDOCK",
                "COCHINSHIP",
                "BDL",
                "DATAPATTNS",
                "ZENTEC",
                "MTARTECH",
                "CYIENTDLM",
                "RADICO",
                "MEDANTA",
                "LALPATHLAB",
                "FORTIS",
                "SYNGENE",
                "GLENMARK",
                "BIOCON",
                "AUROPHARMA",
                "IPCALAB",
                "ZYDUSLIFE",
                "TORNTPHARM",
                "LUPIN",
                "ALKEM",
                "PIIND",
                "SRF",
                "NAVINFLUOR",
                "DEEPAKNTR",
                "ATUL",
                "COROMANDEL",
                "UPL",
                "TATACHEM",
                "FLUOROCHEM",
                "AETHER",
                "FINEORG",
                "GUJGASLTD",
                "ABB",
                "SIEMENS",
                "CGPOWER",
                "BHEL",
                "THERMAX",
                "KNRCON",
                "PNCINFRA",
                "NCC",
                "VOLTAS",
                "HAVELLS",
                "KAYNES",
                "SYRMA",
                "CENTURYTEX",
                "PREMIERENE",
                "WAAREEENER",
                "SWANENERGY",
                "MOTHERSON",
                "SONACOMS",
                "UNOINDA",
                "EXIDEIND",
                "MRF",
                "APOLLOTYRE",
                "BALKRISIND",
                "BOSCHLTD",
                "ASHOKLEY",
                "BHARATFORG",
                "TVSMOTOR",
                "CONCOR",
                "DELHIVERY",
                "BLUEDART",
                "INDIGO",
                "PVRINOX",
                "CDSL",
                "ANGELONE",
                "HDFCAMC",
                "CAMS",
                "FEDERALBNK",
                "AUBANK",
                "BANDHANBNK",
                "IDFCFIRSTB",
                "BANKBARODA",
                "PNB",
                "CANBK",
                "UNIONBANK",
                "SAIL",
                "NMDC",
                "NATIONALUM",
                "HINDZINC",
                "JINDALSTEL",
                "APLAPOLLO",
                "HINDCOPPER",
                "RATNAMANI",
                "JINDALSAW",
                "WELCORP",
                "VBL",
                "DMART",
                "JUBLFOOD",
                "DEVYANI",
                "METRO",
                "PAGEIND",
                "BATAINDIA",
                "DABUR",
                "MARICO",
                "GODREJCP",
                "COLPAL",
                "MAPMYINDIA",
                "NAUKRI",
                "POLICYBZR",
                "AFFLE",
                "ROUTE",
                "KPITTECH",
                "TATACOMM",
                "RATEGAIN",
                "NEWGEN",
                "TANLA",
                "CEINFO",
                "JUSTDIAL",
                "SONATSOFTW",
                "BSOFT",
                "MPHASIS",
                "LTTS",
                "CYIENT",
                "ZENSARTECH",
                "INTELLECT",
                "MASTEK",
                "HAPPSTMNDS",
                "LATENTVIEW",
                "TITAGARH",
                "RAILTEL",
                "RVNL",
                "IRFC",
                "RITES",
                "IRCON",
                "TEXRAIL",
                "JUPITERWAG",
                "BEML",
                "GRSE",
                "GSHIP",
                "SCI",
                "ELECON",
                "TRITURBINE",
                "KBL",
                "KIRLOSENG",
                "ENGINERSIN",
                "AIAENG",
                "TIMKEN",
                "SKFINDIA",
                "SCHAEFFLER",
                "CUMMINSIND",
                "VOLTAMP",
                "SCHNEIDER",
                "HITACHI",
                "HONAUT",
                "KEC",
                "KALPATPOWR",
                "TECHNOE",
                "PRAJIND",
                "GVT&D",
                "TDPOWERSYS",
                "GEPIL",
                "ISGEC",
                "DEEPAKFERT",
                "CHAMBLFERT",
                "GNFC",
                "GSFC",
                "RCF",
                "FACT",
                "NFL",
                "SUMICHEM",
                "SHARDACROP",
                "DHANUKA",
                "ASTRAZEN",
                "SANOFI",
                "PFIZER",
                "ABBOTINDIA",
                "GLAXO",
                "ERIS",
                "AJANTPHARM",
                "JBCHEPHARM",
                "NATCOPHARM",
                "GRANULES",
                "MARKSANS",
                "FDC",
                "CAPLIPHARM",
                "POLYMED",
                "NEULANDLAB",
                "SUVENPHAR",
                "LAURUSLABS",
                "DIVISLAB",
                "STAR",
                "SEQUENT",
                "HIKAL",
                "AARTIDRUGS",
                "RPGPHILIFE",
                "BLISSGVS",
            ],
        ),
    },
    "microcap250": {
        "name": "🌱 NIFTY Microcap 250 (High Asymmetry)",
        "description": "Nifty Microcap 250 emerging leaders before institutional discovery.",
        "symbols": _load_bundled_universe_symbols(
            "nifty_microcap250.json",
            [
                "KAYNES",
                "SYRMA",
                "DATAPATTNS",
                "ZENTEC",
                "MTARTECH",
                "CYIENTDLM",
                "PARAS",
                "ASTRA",
                "TITAGARH",
                "TEXRAIL",
                "JUPITERWAG",
                "PREMIERENE",
                "WAAREEENER",
                "SWANENERGY",
                "RATEGAIN",
                "NEWGEN",
                "MAPMYINDIA",
                "CEINFO",
                "LATENTVIEW",
                "HAPPSTMNDS",
                "AETHER",
                "TATVA",
                "FINEORG",
                "MEDANTA",
                "KIMS",
                "YATHARTH",
                "RAINBOW",
                "VIJAYA",
                "THYROCARE",
                "SHYAMMETL",
                "GALLANTT",
                "SARDAEN",
                "JINDALSAW",
                "WELCORP",
                "ELECTCAST",
                "RAMASTEEL",
                "GRAVITA",
                "DREAMFOLKS",
                "ETHOSLTD",
                "LANDMARK",
                "CAMPUS",
                "MANYAVAR",
                "SAPPHIRE",
                "WESTLIFE",
                "AVANTIFEED",
                "APOLLOPIPE",
                "PRINCEPIPE",
                "FINPIPE",
                "ASTRAL",
                "SUPREMEIND",
                "RESPONIND",
                "CARYSIL",
            ],
        ),
    },
    "smallcap250": {
        "name": "🚀 NIFTY Smallcap 250 Compounders",
        "description": "Nifty Smallcap 250 high-growth emerging corporate compounders.",
        "symbols": _load_bundled_universe_symbols(
            "nifty_smallcap250.json",
            [
                "KAYNES",
                "SYRMA",
                "DATAPATTNS",
                "ZENTEC",
                "MTARTECH",
                "CYIENTDLM",
                "PARAS",
                "ASTRA",
                "TITAGARH",
                "TEXRAIL",
                "JUPITERWAG",
                "PREMIERENE",
                "WAAREEENER",
                "SWANENERGY",
                "RATEGAIN",
                "NEWGEN",
                "MAPMYINDIA",
                "CEINFO",
                "LATENTVIEW",
                "HAPPSTMNDS",
                "AETHER",
                "TATVA",
                "FINEORG",
                "MEDANTA",
                "KIMS",
                "YATHARTH",
                "RAINBOW",
                "VIJAYA",
                "THYROCARE",
                "SHYAMMETL",
                "GALLANTT",
                "SARDAEN",
                "JINDALSAW",
                "WELCORP",
                "ELECTCAST",
                "RAMASTEEL",
                "GRAVITA",
                "DREAMFOLKS",
                "ETHOSLTD",
                "LANDMARK",
                "CAMPUS",
                "MANYAVAR",
                "SAPPHIRE",
                "WESTLIFE",
                "AVANTIFEED",
                "APOLLOPIPE",
                "PRINCEPIPE",
                "FINPIPE",
                "ASTRAL",
                "SUPREMEIND",
                "RESPONIND",
                "CARYSIL",
            ],
        ),
    },
    "midcap150": {
        "name": "📈 NIFTY Midcap 150 Growth",
        "description": "Nifty Midcap 150 high-conviction medium-sized industry champions.",
        "symbols": _load_bundled_universe_symbols(
            "nifty_midcap150.json",
            [
                "DIXON",
                "POLYCAB",
                "KEI",
                "COFORGE",
                "PERSISTENT",
                "KPITTECH",
                "TATAELXSI",
                "HAL",
                "BEL",
                "BSE",
                "MCX",
                "MAXHEALTH",
                "MANKIND",
                "CHOLAFIN",
                "SUZLON",
                "IREDA",
                "SOLARINDS",
                "MAZDOCK",
                "COCHINSHIP",
                "BDL",
                "MEDANTA",
                "AUROPHARMA",
                "LUPIN",
            ],
        ),
    },
    "nifty_total_market": {
        "name": "🏛️ NIFTY Total Market (750 Equities)",
        "description": "Top 750 Indian listed equities (Large 100 + Mid 150 + Small 250 + Micro 250).",
        "symbols": _load_bundled_universe_symbols("nifty_total_market.json", []),
    },
    "all_nse_liquid": {
        "name": "🇮🇳 All Liquid NSE Equities (~1,200+ Active)",
        "description": "Complete NSE actively listed Series EQ universe, dynamically turnover-filtered.",
        "symbols": _load_bundled_universe_symbols("nse_all_eq.json", []),
    },
    "bse_high_growth": {
        "name": "🚀 BSE & Turnaround Super-Cycles",
        "description": "High-conviction capex, deleveraging turnarounds, and thematic super-cycles (Solar, EMS, Defence, Rail, CDMO).",
        "symbols": [
            "BSE",
            "MCX",
            "CDSL",
            "ANGELONE",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "HAL",
            "BEL",
            "MAZDOCK",
            "COCHINSHIP",
            "GRSE",
            "BDL",
            "TITAGARH",
            "RVNL",
            "IRFC",
            "RAILTEL",
            "TRENT",
            "DIXON",
            "POLYCAB",
            "KEI",
            "RRKABEL",
            "KAYNES",
            "SYRMA",
            "PREMIERENE",
            "WAAREEENER",
            "PERSISTENT",
            "COFORGE",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "MUTHOOTFIN",
            "JIOFIN",
            "SOLARINDS",
            "RADICO",
        ],
    },
    "multibagger_hunters": {
        "name": "💎 Multibagger Compounders",
        "description": "High-growth Stage 2 mid/smallcaps with tight VCP bases and strong fundamentals.",
        "symbols": [
            "TRENT",
            "DIXON",
            "HAL",
            "BEL",
            "BSE",
            "MCX",
            "MAZDOCK",
            "COCHINSHIP",
            "POLYCAB",
            "KEI",
            "PERSISTENT",
            "COFORGE",
            "KPITTECH",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "SOLARINDS",
            "DATAPATTNS",
            "CYIENTDLM",
            "AETHER",
            "RADICO",
            "MEDANTA",
            "KAYNES",
            "TITAGARH",
        ],
    },
    "multibagger_all_horizons": {
        "name": "👑 All-Horizons Multibagger Master Watchlist",
        "description": "Full-spectrum institutional universe spanning Short-Term (VCP/RVOL), Mid-Term (Stage 2/CAN SLIM), and Long-Term (SMILE/ROCE).",
        "symbols": [
            "TRENT",
            "DIXON",
            "HAL",
            "BEL",
            "BSE",
            "MCX",
            "MAZDOCK",
            "COCHINSHIP",
            "GRSE",
            "BDL",
            "POLYCAB",
            "KEI",
            "RRKABEL",
            "PERSISTENT",
            "COFORGE",
            "KPITTECH",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "SOLARINDS",
            "DATAPATTNS",
            "CYIENTDLM",
            "KAYNES",
            "SYRMA",
            "TITAGARH",
            "TEXRAIL",
            "JUPITERWAG",
            "PREMIERENE",
            "WAAREEENER",
            "SWANENERGY",
            "RADICO",
            "MEDANTA",
            "KIMS",
            "YATHARTH",
            "NEWGEN",
            "RATEGAIN",
            "MAPMYINDIA",
            "CEINFO",
            "AETHER",
            "TATVA",
            "FINEORG",
            "DEEPAKNTR",
            "PIIND",
            "NAVINFLUOR",
            "ZOMATO",
            "JIOFIN",
            "CDSL",
            "ANGELONE",
            "CAMS",
            "HDFCAMC",
            "DLF",
            "PRESTIGE",
            "SOBHA",
            "BRIGADE",
        ],
    },
    "commodities": {
        "name": "🛢️ MCX Commodities Futures",
        "description": "Precious metals, energy, base metals and agricultural continuous contracts.",
        "symbols": [
            "GOLD",
            "SILVER",
            "CRUDEOIL",
            "NATURALGAS",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "COTTON",
        ],
    },
    "etfs": {
        "name": "📊 Leading Exchange Traded Funds (ETFs)",
        "description": "Benchmark equity indices, sectoral baskets, gold/silver bullion, and global tech ETFs.",
        "symbols": [
            "NIFTYBEES",
            "GOLDBEES",
            "SILVERBEES",
            "BANKBEES",
            "ITBEES",
            "AUTOBEES",
            "PHARMABEES",
            "CPSEETF",
            "JUNIORBEES",
            "MID150BEES",
            "MON100",
            "MAFANG",
            "LIQUIDBEES",
        ],
    },
    "currencies": {
        "name": "💱 Currency Derivatives (CDS / Forex)",
        "description": "Active currency pairs tracking the Indian Rupee against global major currencies.",
        "symbols": [
            "USDINR",
            "EURINR",
            "GBPINR",
            "JPYINR",
        ],
    },
    "indices": {
        "name": "📈 Benchmark & Sectoral Market Indices",
        "description": "Core broad market benchmarks and key sectoral rotation gauges.",
        "symbols": [
            "NIFTY50",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "NIFTYIT",
            "NIFTYAUTO",
            "NIFTYPHARMA",
            "NIFTYFMCG",
            "NIFTYMETAL",
            "NIFTYREALTY",
            "NIFTYENERGY",
            "NIFTYINFRA",
            "NIFTYPSE",
            "NIFTYPSU",
            "NIFTYPVTBANK",
            "INDIAVIX",
        ],
    },
    "fno_universe": {
        "name": "⚡ Complete Liquid F&O Universe",
        "description": "All ~180+ liquid derivatives contracts eligible for single-stock futures & options.",
        "symbols": [
            "RELIANCE",
            "TCS",
            "HDFCBANK",
            "INFY",
            "ICICIBANK",
            "SBIN",
            "BHARTIARTL",
            "ITC",
            "LT",
            "KOTAKBANK",
            "AXISBANK",
            "TATAMOTORS",
            "MARUTI",
            "SUNPHARMA",
            "BAJFINANCE",
            "TITAN",
            "HINDUNILVR",
            "NTPC",
            "ONGC",
            "POWERGRID",
            "TATASTEEL",
            "COALINDIA",
            "ASIANPAINT",
            "M&M",
            "ADANIENT",
            "ADANIPORTS",
            "TECHM",
            "HCLTECH",
            "WIPRO",
            "ULTRACEMCO",
            "JSWSTEEL",
            "GRASIM",
            "HEROMOTOCO",
            "EICHERMOT",
            "BAJAJ-AUTO",
            "APOLLOHOSP",
            "DRREDDY",
            "CIPLA",
            "TRENT",
            "BEL",
            "HAL",
            "ZOMATO",
            "NESTLEIND",
            "BRITANNIA",
            "DIVISLAB",
            "HINDALCO",
            "BPCL",
            "SHRIRAMFIN",
            "TATACONSUM",
            "INDUSINDBK",
            "DLF",
            "GODREJPROP",
            "OBEROIRLTY",
            "PRESTIGE",
            "POLYCAB",
            "KEI",
            "DIXON",
            "BSE",
            "MCX",
            "PERSISTENT",
            "COFORGE",
            "KPITTECH",
            "TATAELXSI",
            "OFSS",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "MUTHOOTFIN",
            "JIOFIN",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "PFC",
            "REC",
            "NHPC",
            "SJVN",
            "TORNTPOWER",
            "SOLARINDS",
            "MAZDOCK",
            "COCHINSHIP",
            "BDL",
            "DATAPATTNS",
            "ZENTEC",
            "MTARTECH",
            "CYIENTDLM",
            "RADICO",
            "MEDANTA",
            "LALPATHLAB",
            "FORTIS",
            "SYNGENE",
            "GLENMARK",
            "BIOCON",
            "AUROPHARMA",
            "IPCALAB",
            "ZYDUSLIFE",
            "TORNTPHARM",
            "LUPIN",
            "ALKEM",
            "PIIND",
            "SRF",
            "NAVINFLUOR",
            "DEEPAKNTR",
            "ATUL",
            "COROMANDEL",
            "UPL",
            "TATACHEM",
            "ABB",
            "SIEMENS",
            "CGPOWER",
            "BHEL",
            "THERMAX",
            "VOLTAS",
            "HAVELLS",
            "KAYNES",
            "MOTHERSON",
            "SONACOMS",
            "EXIDEIND",
            "MRF",
            "APOLLOTYRE",
            "BALKRISIND",
            "BOSCHLTD",
            "ASHOKLEY",
            "BHARATFORG",
            "TVSMOTOR",
            "CONCOR",
            "INDIGO",
            "PVRINOX",
            "CDSL",
            "ANGELONE",
            "HDFCAMC",
            "FEDERALBNK",
            "AUBANK",
            "BANDHANBNK",
            "IDFCFIRSTB",
            "BANKBARODA",
            "PNB",
            "CANBK",
            "UNIONBANK",
            "SAIL",
            "NMDC",
            "NATIONALUM",
            "HINDZINC",
            "JINDALSTEL",
            "VBL",
            "DMART",
            "JUBLFOOD",
            "DEVYANI",
            "PAGEIND",
            "BATAINDIA",
            "DABUR",
            "MARICO",
            "GODREJCP",
            "COLPAL",
            "NAUKRI",
            "POLICYBZR",
            "MPHASIS",
            "LTTS",
            "CYIENT",
            "TITAGARH",
            "RVNL",
            "IRFC",
            "CUMMINSIND",
        ],
    },
}

# ── Multi-Asset Taxonomies ──────────────────────────────────────────

COMMODITY_TAXONOMY: dict[str, dict[str, Any]] = {
    "precious_metals": {
        "name": "Precious Metals",
        "icon": "🪙",
        "symbols": ["GOLD", "GOLDM", "GOLDPETAL", "SILVER", "SILVERM", "SILVERMIC"],
    },
    "energy_commodities": {
        "name": "Energy Commodities",
        "icon": "🛢️",
        "symbols": ["CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI"],
    },
    "base_metals": {
        "name": "Industrial Base Metals",
        "icon": "🏗️",
        "symbols": ["COPPER", "ZINC", "ALUMINIUM", "LEAD"],
    },
    "agri_commodities": {
        "name": "Agricultural Contracts",
        "icon": "🌾",
        "symbols": ["COTTON"],
    },
}

ETF_TAXONOMY: dict[str, dict[str, Any]] = {
    "equity_etfs": {
        "name": "Equity Index ETFs",
        "icon": "📊",
        "symbols": ["NIFTYBEES", "BANKBEES", "JUNIORBEES", "MID150BEES", "CPSEETF"],
    },
    "gold_silver_etfs": {
        "name": "Gold & Silver Bullion ETFs",
        "icon": "✨",
        "symbols": ["GOLDBEES", "SILVERBEES"],
    },
    "sector_etfs": {
        "name": "Sectoral ETFs",
        "icon": "💼",
        "symbols": ["ITBEES", "AUTOBEES", "PHARMABEES"],
    },
    "global_etfs": {
        "name": "Global & US Tech ETFs",
        "icon": "🌐",
        "symbols": ["MON100", "MAFANG"],
    },
}

CURRENCY_TAXONOMY: dict[str, dict[str, Any]] = {
    "fx_pairs": {
        "name": "Currency Derivatives (CDS)",
        "icon": "💱",
        "symbols": ["USDINR", "EURINR", "GBPINR", "JPYINR"],
    },
}


# ── Stock to Sector Lookup Map (Fast Inverse Index) ─────────────────

_STOCK_TO_SECTOR: dict[str, tuple[str, str]] = {}
_STOCK_INDUSTRY: dict[str, str] = {}
_STOCK_SECTOR_SOURCE: dict[str, str] = {}

for sec_id, data in SECTOR_TAXONOMY.items():
    sec_name = data["name"]
    for sym in data["symbols"]:
        sym_clean = sym.upper().strip()
        _STOCK_TO_SECTOR[sym_clean] = (sec_id, sec_name)
        _STOCK_SECTOR_SOURCE[sym_clean] = "INSTITUTIONAL_TAXONOMY"

for com_group in COMMODITY_TAXONOMY.values():
    for sym in com_group["symbols"]:
        sym_clean = sym.upper().strip()
        _STOCK_TO_SECTOR[sym_clean] = ("commodity", "MCX Commodities")
        _STOCK_SECTOR_SOURCE[sym_clean] = "COMMODITY_TAXONOMY"

for etf_group in ETF_TAXONOMY.values():
    for sym in etf_group["symbols"]:
        sym_clean = sym.upper().strip()
        _STOCK_TO_SECTOR[sym_clean] = ("etf", "Exchange Traded Funds")
        _STOCK_SECTOR_SOURCE[sym_clean] = "ETF_TAXONOMY"

for fx_group in CURRENCY_TAXONOMY.values():
    for sym in fx_group["symbols"]:
        sym_clean = sym.upper().strip()
        _STOCK_TO_SECTOR[sym_clean] = ("currency", "Currency Derivatives")
        _STOCK_SECTOR_SOURCE[sym_clean] = "CURRENCY_TAXONOMY"


_NSE_INDUSTRY_TO_SECTOR: dict[str, tuple[str, str]] = {
    "Automobile and Auto Components": ("auto", "Automobiles & Mobility"),
    "Capital Goods": ("infra", "Infrastructure & Capital Goods"),
    "Construction": ("infra", "Infrastructure & Capital Goods"),
    "Construction Materials": ("infra", "Infrastructure & Capital Goods"),
    "Chemicals": ("chemicals", "Specialty Chemicals & Agriculture"),
    "Consumer Durables": ("fmcg", "FMCG, Retail & Consumption"),
    "Consumer Services": ("fmcg", "FMCG, Retail & Consumption"),
    "Diversified": ("infra", "Infrastructure & Capital Goods"),
    "Fast Moving Consumer Goods": ("fmcg", "FMCG, Retail & Consumption"),
    "Financial Services": ("banking", "Banking & Financial Services"),
    "Forest Materials": ("fmcg", "FMCG, Retail & Consumption"),
    "Healthcare": ("pharma", "Pharma & Healthcare"),
    "Information Technology": ("it", "IT, Software & Technology"),
    "Media Entertainment & Publication": ("telecom", "Telecom, Media & Logistics"),
    "Metals & Mining": ("metals", "Metals & Mining"),
    "Oil Gas & Consumable Fuels": ("energy", "Energy, Power & Green Transition"),
    "Power": ("energy", "Energy, Power & Green Transition"),
    "Realty": ("realty", "Real Estate & Housing"),
    "Services": ("infra", "Infrastructure & Capital Goods"),
    "Telecommunication": ("telecom", "Telecom, Ports & Logistics"),
    "Textiles": ("fmcg", "FMCG, Retail & Consumption"),
    "Utilities": ("energy", "Energy, Power & Green Transition"),
}

_GICS_SECTOR_TO_SECTOR: dict[str, tuple[str, str]] = {
    "Real Estate": ("realty", "Real Estate & Housing"),
    "Financial Services": ("banking", "Banking & Financial Services"),
    "Financials": ("banking", "Banking & Financial Services"),
    "Technology": ("it", "IT, Software & Technology"),
    "Information Technology": ("it", "IT, Software & Technology"),
    "Healthcare": ("pharma", "Pharma & Healthcare"),
    "Consumer Defensive": ("fmcg", "FMCG, Retail & Consumption"),
    "Consumer Cyclical": ("auto", "Automobiles & Mobility"),
    "Industrials": ("infra", "Infrastructure & Capital Goods"),
    "Basic Materials": ("metals", "Metals & Mining"),
    "Energy": ("energy", "Energy, Power & Green Transition"),
    "Utilities": ("energy", "Energy, Power & Green Transition"),
    "Communication Services": ("telecom", "Telecom, Ports & Logistics"),
}


def _load_bundled_index_sectors() -> None:
    """Ingests official constituent industry classifications from bundled Nifty datasets."""
    for fn in ("nifty_total_market.json", "nifty500.json"):
        p = _UNIVERSES_DATA_DIR / fn
        if not p.exists():
            p = Path("data/universes") / fn
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for d in data:
                    sym = d.get("symbol", "").strip().upper()
                    ind = d.get("industry", "").strip()
                    if sym and ind:
                        if sym not in _STOCK_INDUSTRY:
                            _STOCK_INDUSTRY[sym] = ind
                        if sym not in _STOCK_TO_SECTOR:
                            mapped = _NSE_INDUSTRY_TO_SECTOR.get(ind)
                            if mapped:
                                _STOCK_TO_SECTOR[sym] = mapped
                                _STOCK_SECTOR_SOURCE[sym] = "NIFTY_TOTAL_MARKET"
            except Exception:
                pass


_load_bundled_index_sectors()


def get_stock_sector(symbol: str) -> tuple[str, str]:
    """
    Returns (sector_id, sector_name) for a given symbol.
    Uses:
      1. Institutional in-memory fast inverse index (NIFTY Total Market 755+ constituents).
      2. Dynamic GICS/Industry metadata discovery for newly listed / BSE equities.
      3. Defaults to ("broad_market", "Broad Market") if completely unclassified.
    """
    clean = (
        symbol.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("BSE:", "")
        .strip()
    )
    if clean in _STOCK_TO_SECTOR:
        return _STOCK_TO_SECTOR[clean]

    # Dynamic fallback: check cached fundamentals or yfinance metadata
    try:
        from engine.analysis_cache import cache_get, cache_set

        cache_key = f"stock_sector:{clean}"
        cached = cache_get(cache_key, namespace="universe", max_age_seconds=86400 * 7)
        if cached and isinstance(cached, list) and len(cached) == 2:
            _STOCK_TO_SECTOR[clean] = (cached[0], cached[1])
            _STOCK_SECTOR_SOURCE[clean] = "CACHED_DYNAMIC_DISCOVERY"
            return cached[0], cached[1]

        # Inspect fundamental summary if available
        from analysis.fundamental import analyse

        fund = analyse(clean)
        if fund and fund.sector:
            gics_sec = fund.sector.strip()
            gics_ind = (fund.industry or "").lower()
            mapped = _GICS_SECTOR_TO_SECTOR.get(gics_sec)
            if not mapped:
                # Sub-industry heuristics
                if "bank" in gics_ind or "finance" in gics_ind or "insurance" in gics_ind:
                    mapped = ("banking", "Banking & Financial Services")
                elif "software" in gics_ind or "tech" in gics_ind:
                    mapped = ("it", "IT, Software & Technology")
                elif "pharma" in gics_ind or "health" in gics_ind or "hospital" in gics_ind:
                    mapped = ("pharma", "Pharma & Healthcare")
                elif "auto" in gics_ind or "vehicle" in gics_ind:
                    mapped = ("auto", "Automobiles & Mobility")
                elif "real estate" in gics_ind or "realt" in gics_ind:
                    mapped = ("realty", "Real Estate & Housing")
                elif "steel" in gics_ind or "metal" in gics_ind or "mining" in gics_ind:
                    mapped = ("metals", "Metals & Mining")
                elif (
                    "power" in gics_ind
                    or "energy" in gics_ind
                    or "oil" in gics_ind
                    or "solar" in gics_ind
                ):
                    mapped = ("energy", "Energy, Power & Green Transition")
                elif "chemical" in gics_ind or "fertiliz" in gics_ind:
                    mapped = ("chemicals", "Specialty Chemicals & Agriculture")
                else:
                    mapped = ("infra", "Infrastructure & Capital Goods")

            if mapped:
                _STOCK_TO_SECTOR[clean] = mapped
                _STOCK_SECTOR_SOURCE[clean] = "DYNAMIC_METADATA_DISCOVERY"
                if fund.industry:
                    _STOCK_INDUSTRY[clean] = fund.industry
                cache_set(cache_key, list(mapped), namespace="universe", ttl_minutes=60 * 24 * 7)
                return mapped
    except Exception:
        pass

    return ("broad_market", "Broad Market")


COMPANY_NAMES: dict[str, str] = {
    "RELIANCE": "Reliance Industries Ltd",
    "TCS": "Tata Consultancy Services Ltd",
    "HDFCBANK": "HDFC Bank Ltd",
    "ICICIBANK": "ICICI Bank Ltd",
    "INFY": "Infosys Ltd",
    "BHARTIARTL": "Bharti Airtel Ltd",
    "ITC": "ITC Ltd",
    "SBIN": "State Bank of India",
    "LICI": "Life Insurance Corp of India",
    "HINDUNILVR": "Hindustan Unilever Ltd",
    "LT": "Larsen & Toubro Ltd",
    "BAJFINANCE": "Bajaj Finance Ltd",
    "HCLTECH": "HCL Technologies Ltd",
    "MARUTI": "Maruti Suzuki India Ltd",
    "SUNPHARMA": "Sun Pharmaceutical Industries Ltd",
    "ADANIENT": "Adani Enterprises Ltd",
    "KOTAKBANK": "Kotak Mahindra Bank Ltd",
    "TATAMOTORS": "Tata Motors Ltd",
    "AXISBANK": "Axis Bank Ltd",
    "NTPC": "NTPC Ltd",
    "ONGC": "Oil & Natural Gas Corp Ltd",
    "POWERGRID": "Power Grid Corp of India Ltd",
    "TITAN": "Titan Company Ltd",
    "COALINDIA": "Coal India Ltd",
    "TATASTEEL": "Tata Steel Ltd",
    "BAJAJFINSV": "Bajaj Finserv Ltd",
    "M&M": "Mahindra & Mahindra Ltd",
    "ASIANPAINT": "Asian Paints Ltd",
    "SIEMENS": "Siemens Ltd",
    "HAL": "Hindustan Aeronautics Ltd",
    "BEL": "Bharat Electronics Ltd",
    "TRENT": "Trent Ltd",
    "DIXON": "Dixon Technologies Ltd",
    "BSE": "BSE Ltd",
    "MCX": "Multi Commodity Exchange of India Ltd",
    "COFORGE": "Coforge Ltd",
    "PERSISTENT": "Persistent Systems Ltd",
    "DIVISLAB": "Divi's Laboratories Ltd",
    "POLYCAB": "Polycab India Ltd",
    "ZOMATO": "Zomato Ltd",
    "TITAGARH": "Titagarh Rail Systems Ltd",
    "TEXRAIL": "Texmaco Rail & Engineering Ltd",
    "JUPITERWAG": "Jupiter Wagons Ltd",
    "RVNL": "Rail Vikas Nigam Ltd",
    "IRFC": "Indian Railway Finance Corp Ltd",
    "IRCON": "Ircon International Ltd",
    "RITES": "RITES Ltd",
    "RAILTEL": "RailTel Corporation of India Ltd",
    "BEML": "BEML Ltd",
    "KAYNES": "Kaynes Technology India Ltd",
    "SYRMA": "Syrma SGS Technology Ltd",
    "PREMIERENE": "Premier Energies Ltd",
    "WAAREEENER": "Waaree Energies Ltd",
    "SUZLON": "Suzlon Energy Ltd",
    "INOXWIND": "Inox Wind Ltd",
    "IREDA": "Indian Renewable Energy Development Agency Ltd",
    "MAZDOCK": "Mazagon Dock Shipbuilders Ltd",
    "COCHINSHIP": "Cochin Shipyard Ltd",
    "GRSE": "Garden Reach Shipbuilders Ltd",
    "BDL": "Bharat Dynamics Ltd",
    "ADANIPOWER": "Adani Power Ltd",
}

# Update company names from bundled official index constituent datasets
COMPANY_NAMES.update(_load_bundled_company_names())

_n500_symbols = set(THEMATIC_PRESETS.get("nifty500", {}).get("symbols", []))
_MID_CAP_SET = set(THEMATIC_PRESETS.get("midcap150", {}).get("symbols", []))
_SMALL_CAP_SET = set(THEMATIC_PRESETS.get("smallcap250", {}).get("symbols", []))
_MICRO_CAP_SET = set(THEMATIC_PRESETS.get("microcap250", {}).get("symbols", []))

# SEBI Categorization Standard: Top 100 Equities (Nifty 50 + Nifty Next 50) = Large Cap
_NIFTY_NEXT_50_CORE = {
    "ADANIPOWER",
    "ABB",
    "DMART",
    "HAL",
    "BEL",
    "ZOMATO",
    "TRENT",
    "AMBUJACEM",
    "BANKBARODA",
    "BOSCHLTD",
    "CANBK",
    "CHOLAFIN",
    "COLPAL",
    "DLF",
    "GAIL",
    "GODREJCP",
    "HAVELLS",
    "ICICIGI",
    "ICICIPRULI",
    "INDIGO",
    "IOC",
    "IRCTC",
    "JINDALSTEL",
    "JIOFIN",
    "LTIM",
    "MOTHERSON",
    "NAUKRI",
    "PIDILITIND",
    "PFC",
    "PNB",
    "RECLTD",
    "SHRIRAMFIN",
    "SIEMENS",
    "TORNTPHARM",
    "TVSHLTD",
    "UNITDSPR",
    "VBL",
    "VEDL",
    "ZYDUSLIFE",
}

_LARGE_CAP_SET = (
    set(THEMATIC_PRESETS.get("nifty50", {}).get("symbols", []))
    | set(s for s in _n500_symbols if s not in _MID_CAP_SET and s not in _SMALL_CAP_SET)
    | _NIFTY_NEXT_50_CORE
)


def get_stock_cap_tier(symbol: str) -> str:
    """Classifies stock as LARGE, MID, SMALL, or MICRO based on SEBI canonical market-cap rules."""
    clean = (
        symbol.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("BSE:", "")
        .strip()
    )
    if clean in _LARGE_CAP_SET:
        return "LARGE"
    if clean in _MID_CAP_SET:
        return "MID"
    if clean in _SMALL_CAP_SET:
        return "SMALL"
    if clean in _MICRO_CAP_SET:
        return "MICRO"
    return "MICRO" if clean in COMPANY_NAMES else "SMALL"


def get_stock_segment_profile(symbol: str) -> dict[str, Any]:
    """
    Unified multi-dimensional segment profile for any Indian equity, commodity, or currency:
      1. Asset & Exchange Segment (NSE, BSE, MCX, CDS)
      2. Market Capitalization Tier (LARGE, MID, SMALL, MICRO)
      3. F&O Eligibility (is_fo)
      4. Institutional Sector ID, Name, and Benchmark Index Symbol
      5. Official Industry Classification
      6. Data Authority Source
    """
    raw = symbol.strip().upper()
    clean = (
        raw.replace(".NS", "")
        .replace("NSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("BSE:", "")
        .strip()
    )

    sec_id, sec_name = get_stock_sector(clean)

    # Determine Exchange & Asset Segment
    if raw.startswith("MCX:") or sec_id == "commodity":
        exchange = "MCX"
        segment_type = "COMMODITY_FUTURES"
    elif raw.startswith("CDS:") or sec_id == "currency":
        exchange = "CDS"
        segment_type = "CURRENCY_DERIVATIVES"
    elif raw.startswith("BSE:"):
        exchange = "BSE"
        segment_type = "EQUITY_CASH"
    else:
        exchange = "NSE"
        segment_type = "EQUITY_CASH"

    # F&O contract eligibility
    fno_set = set(THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", []))
    is_fo = clean in fno_set or exchange in ("MCX", "CDS")

    # Sector benchmark index symbol
    sec_info = SECTOR_TAXONOMY.get(sec_id, {})
    sector_index = sec_info.get("index_symbol", "^CRSLDX")

    return {
        "symbol": clean,
        "full_symbol": f"{exchange}:{clean}" if not raw.startswith(f"{exchange}:") else raw,
        "company_name": get_stock_name(clean),
        "exchange": exchange,
        "segment_type": segment_type,
        "cap_tier": get_stock_cap_tier(clean),
        "is_fo": is_fo,
        "sector_id": sec_id,
        "sector_name": sec_name,
        "sector_index": sector_index,
        "industry": _STOCK_INDUSTRY.get(clean, sec_name),
        "classification_source": _STOCK_SECTOR_SOURCE.get(clean, "BROAD_MARKET_DEFAULT"),
    }


def get_stock_name(symbol: str) -> str:
    """Returns human-readable company name for symbol, or formatted symbol if unlisted."""
    clean = (
        symbol.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("BSE:", "")
        .strip()
    )
    return COMPANY_NAMES.get(clean, clean)


def resolve_sector_taxonomy(query: str) -> tuple[str, dict[str, Any]]:
    """
    Robust sector resolver mapping various names, symbols, or queries (e.g. 'IT', 'NIFTY IT', 'Bank', 'Metals', 'Auto')
    to (canonical_sector_id, sector_info).
    """
    if not query:
        return "banking", SECTOR_TAXONOMY["banking"]

    q = query.strip().lower().replace("nifty", "").replace("^", "").replace("_", " ").strip()

    # Exact or alias mapping
    alias_map = {
        "bank": "banking",
        "banking": "banking",
        "banknifty": "banking",
        "fin services": "banking",
        "financial services": "banking",
        "financials": "banking",
        "psu bank": "banking",
        "psubank": "banking",
        "it": "it",
        "tech": "it",
        "technology": "it",
        "software": "it",
        "auto": "auto",
        "automobile": "auto",
        "automobiles": "auto",
        "motor": "auto",
        "defence": "defence",
        "defense": "defence",
        "aerospace": "defence",
        "energy": "energy",
        "power": "energy",
        "oil": "energy",
        "gas": "energy",
        "metal": "metals",
        "metals": "metals",
        "mining": "metals",
        "pharma": "pharma",
        "healthcare": "pharma",
        "health": "pharma",
        "fmcg": "fmcg",
        "consumption": "fmcg",
        "retail": "fmcg",
        "infra": "infra",
        "infrastructure": "infra",
        "realty": "realty",
        "real estate": "realty",
        "housing": "realty",
        "capital goods": "infra",
        "chem": "chemicals",
        "chemical": "chemicals",
        "chemicals": "chemicals",
        "telecom": "telecom",
        "media": "telecom",
        "ports": "telecom",
        "logistics": "telecom",
        "railway": "railways",
        "railways": "railways",
        "rail": "railways",
        "wagon": "railways",
    }

    if q in alias_map and alias_map[q] in SECTOR_TAXONOMY:
        key = alias_map[q]
        return key, SECTOR_TAXONOMY[key]

    for k, info in SECTOR_TAXONOMY.items():
        if (
            k in q
            or q in k
            or q in info["name"].lower()
            or q in info.get("index_symbol", "").lower()
        ):
            return k, info

    return "banking", SECTOR_TAXONOMY["banking"]


def get_taxonomy_categories() -> list[dict[str, Any]]:
    """
    Returns all sector categories and thematic presets with their counts and icons.
    Useful for populating frontend dropdowns and cockpit selectors.
    """
    categories = []

    # 1. Thematic Presets
    for preset_id, info in THEMATIC_PRESETS.items():
        categories.append(
            {
                "id": preset_id,
                "name": info["name"],
                "description": info["description"],
                "type": "THEMATIC",
                "count": len(info["symbols"]) if info["symbols"] else "Dynamic",
                "icon": "⚡" if "Dynamic" in info["name"] else "🎯",
            }
        )

    # 2. Sector Categories
    for sec_id, info in SECTOR_TAXONOMY.items():
        categories.append(
            {
                "id": sec_id,
                "name": info["name"],
                "description": info["description"],
                "type": "SECTOR",
                "count": len(info["symbols"]),
                "icon": info.get("icon", "🏢"),
                "index_symbol": info.get("index_symbol", ""),
            }
        )

    return categories


def resolve_dynamic_universe(
    universe: str,
    top_n_sectors: int = 3,
    max_stocks: int = 40,
    use_cache: bool = True,
) -> tuple[list[str], str]:
    """
    Market-Aware Universe Resolver:
    - If universe == "auto_market_aware": Inspects the JdK RRG Sector matrix,
      pulls stocks belonging to the 2-3 LEADING/IMPROVING sectors, and includes volume surge leaders.
    - If universe is a thematic preset: Returns its curated list.
    - If universe is a sector ID (e.g. "defence", "banking"): Returns that sector's symbols.
    - If universe is a comma-separated list of symbols: Parses them.

    Returns:
        tuple of (resolved_symbols_list, resolution_reason_text)
    """
    key = universe.lower().strip()

    # 1. Dynamic Auto Market-Aware Mode
    if key in ("auto_market_aware", "dynamic", "leading_sectors", "market_aware"):
        try:
            from analysis.sector_rotation import get_sector_rrg_matrix

            rrg = get_sector_rrg_matrix(use_cache=use_cache)
            # Find leading / improving sectors
            leading_ids = []
            improving_ids = []
            sector_id_map = {
                "BANK": "banking",
                "IT": "it",
                "AUTO": "auto",
                "PHARMA": "pharma",
                "FMCG": "fmcg",
                "METAL": "metals",
                "REALTY": "infra",
                "ENERGY": "energy",
                "INFRA": "infra",
                "PSU_BANK": "banking",
                "DEFENCE": "defence",
            }

            for pt in rrg:
                sec_raw = getattr(pt, "sector", "")
                quad = getattr(pt, "quadrant", "")
                sec_k = sector_id_map.get(sec_raw, sec_raw.lower())

                if quad == "LEADING" and sec_k in SECTOR_TAXONOMY:
                    if sec_k not in leading_ids:
                        leading_ids.append(sec_k)
                elif quad == "IMPROVING" and sec_k in SECTOR_TAXONOMY:
                    if sec_k not in improving_ids:
                        improving_ids.append(sec_k)

            target_sectors = (leading_ids + improving_ids)[:top_n_sectors]
            if not target_sectors:
                return (
                    [],
                    "Market-aware universe unavailable: no live leading or improving sector evidence.",
                )

            symbols_set = set()
            for s_id in target_sectors:
                symbols_set.update(SECTOR_TAXONOMY[s_id]["symbols"][:5])

            # Always add high volume surge candidates
            symbols_set.update(THEMATIC_PRESETS["volume_surges_rvol"]["symbols"][:4])

            resolved = list(symbols_set)[:max_stocks]
            reason = f"Top-down routed to leading sectors ({', '.join([s.upper() for s in target_sectors])}) + volume surge leaders."
            return resolved, reason

        except Exception as e:
            return (
                [],
                f"Market-aware universe unavailable: sector rotation data could not be verified ({e}).",
            )

    # 2. Thematic Presets & Aliases
    preset_alias = {
        "commodity": "commodities",
        "commodities": "commodities",
        "mcx": "commodities",
        "etf": "etfs",
        "etfs": "etfs",
        "forex": "currencies",
        "currency": "currencies",
        "currencies": "currencies",
        "cds": "currencies",
        "index": "indices",
        "indices": "indices",
        "fno": "fno_universe",
        "fno_universe": "fno_universe",
        "derivatives": "fno_universe",
        "nifty_500": "nifty500",
        "nifty500": "nifty500",
        "microcap": "microcap250",
        "microcap250": "microcap250",
        "nifty_microcap": "microcap250",
        "nifty_microcap250": "microcap250",
        "microcap_250": "microcap250",
        "smallcap": "smallcap250",
        "smallcap250": "smallcap250",
        "nifty_smallcap": "smallcap250",
        "nifty_smallcap250": "smallcap250",
        "midcap": "midcap150",
        "midcap150": "midcap150",
        "nifty_midcap": "midcap150",
        "nifty_midcap150": "midcap150",
        "total_market": "nifty_total_market",
        "nifty_total_market": "nifty_total_market",
        "all_nse": "all_nse_liquid",
        "all_nse_liquid": "all_nse_liquid",
        "nse_all": "all_nse_liquid",
        "all_stocks": "all_nse_liquid",
    }
    canon_preset = preset_alias.get(key, key)
    if canon_preset in THEMATIC_PRESETS:
        symbols = THEMATIC_PRESETS[canon_preset]["symbols"]
        return symbols, f"Thematic preset: {THEMATIC_PRESETS[canon_preset]['name']}"

    # 3. Sector Categories
    if key in SECTOR_TAXONOMY:
        symbols = SECTOR_TAXONOMY[key]["symbols"]
        return symbols, f"Sector watchlist: {SECTOR_TAXONOMY[key]['name']} ({len(symbols)} tickers)"

    # 4. Comma-separated or single symbol
    if "," in universe:
        syms = [s.strip().upper() for s in universe.split(",") if s.strip()]
        return syms, f"Custom watchlist ({len(syms)} tickers)"

    clean_u = (
        universe.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .replace("BSE:", "")
        .strip()
    )
    if clean_u in _STOCK_TO_SECTOR:
        return [clean_u], f"Single ticker: {clean_u}"

    # Default fallback
    return THEMATIC_PRESETS["nifty50"]["symbols"][:max_stocks], "Default NIFTY 50 Universe"


def normalize_symbol_exchange(symbol: str, exchange: str | None = None) -> tuple[str, str]:
    """
    Canonical Single Source of Truth (SSOT) for Indian market instrument resolution.

    Transforms any raw input (e.g. 'crudeoil', 'GOLD', 'MCX:SILVER', 'USDINR', 'SENSEX', 'NSE:RELIANCE')
    into a normalized (clean_symbol, canonical_exchange) tuple.
    """
    if not symbol:
        return "", (exchange or "NSE").upper().strip()

    sym = str(symbol).upper().strip()
    exch = (exchange or "NSE").upper().strip() if exchange else "NSE"

    if ":" in sym:
        prefix, clean_sym = sym.split(":", 1)
        exch = prefix.upper().strip()
        sym = clean_sym.upper().strip()
    elif exch == "NSE":
        from market.quotes import _BSE_SYMBOLS, _CDS_SYMBOLS, _MCX_SYMBOLS, _CRYPTO_SYMBOLS

        if sym in _MCX_SYMBOLS:
            exch = "MCX"
        elif sym in _CDS_SYMBOLS:
            exch = "CDS"
        elif sym in _BSE_SYMBOLS:
            exch = "BSE"
        elif sym in _CRYPTO_SYMBOLS:
            exch = "CRYPTO"

    clean_sym = sym.replace("_", "-")
    return clean_sym, exch
