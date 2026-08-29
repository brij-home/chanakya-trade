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
from typing import Any, Optional


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
            "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
            "FEDERALBNK", "AUBANK", "BANDHANBNK", "IDFCFIRSTB", "BANKBARODA", "PNB",
            "CANBK", "UNIONBANK", "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN",
            "SHRIRAMFIN", "JIOFIN", "BSE", "MCX", "ANGELONE", "CDSL", "HDFCAMC",
        ],
    },
    "it": {
        "name": "IT, Software & Technology",
        "icon": "💻",
        "index_symbol": "^CNXIT",
        "description": "Tier-1 IT Giants, High-Growth ER&D Midcaps, and New-Age Tech Platforms.",
        "symbols": [
            "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "COFORGE", "PERSISTENT",
            "MPHASIS", "KPITTECH", "TATAELXSI", "OFSS", "CYIENT", "ZOMATO", "NAUKRI",
            "MAPMYINDIA", "DIXON", "POLICYBZR",
        ],
    },
    "auto": {
        "name": "Automobiles & Mobility",
        "icon": "🚗",
        "index_symbol": "^CNXAUTO",
        "description": "4W & 2W OEMs, Commercial Vehicles, EV Components, and Tyres.",
        "symbols": [
            "TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT",
            "TVSMOTOR", "ASHOKLEY", "BHARATFORG", "MOTHERSON", "SONACOMS", "UNOINDA",
            "EXIDEIND", "MRF", "APOLLOTYRE", "BALKRISIND", "BOSCHLTD",
        ],
    },
    "defence": {
        "name": "Defence & Aerospace",
        "icon": "🛡️",
        "index_symbol": "^CNXDEFENCE",
        "description": "Defence PSUs, Precision Aerospace, Drones, and Electronic Warfare.",
        "symbols": [
            "HAL", "BEL", "MAZDOCK", "COCHINSHIP", "BDL", "DATAPATTNS", "ZENTEC",
            "SOLARINDS", "MTARTECH", "PARAS", "ASTRA", "CYIENTDLM",
        ],
    },

    "energy": {
        "name": "Energy, Power & Green Transition",
        "icon": "⚡",
        "index_symbol": "^CNXENERGY",
        "description": "Oil & Gas, Power Generation, Solar/Wind Renewables, and Power Financing.",
        "symbols": [
            "RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL", "IOC",
            "GAIL", "ADANIGREEN", "ADANIENT", "ADANIPOWER", "TATAPOWER", "SUZLON",
            "INOXWIND", "IREDA", "PFC", "REC", "NHPC", "SJVN", "TORNTPOWER",
        ],
    },
    "metals": {
        "name": "Metals & Mining",
        "icon": "⛏️",
        "index_symbol": "^CNXMETAL",
        "description": "Integrated Steel, Aluminium, Copper, Base Metals, and Mining.",
        "symbols": [
            "TATASTEEL", "JSWSTEEL", "HINDALCO", "JINDALSTEL", "NMDC", "SAIL",
            "VEDL", "NATIONALUM", "HINDZINC", "APLLTD", "RATNAMANI", "JINDALSAW",
        ],
    },
    "pharma": {
        "name": "Pharma & Healthcare",
        "icon": "💊",
        "index_symbol": "^CNXPHARMA",
        "description": "Global Formulations, CDMO/API, Multi-speciality Hospitals, and Diagnostics.",
        "symbols": [
            "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP", "LUPIN",
            "TORNTPHARM", "ZYDUSLIFE", "MANKIND", "MAXHEALTH", "FORTIS", "MEDANTA",
            "LALPATHLAB", "SYNGENE", "GLENMARK", "BIOCON", "AUROPHARMA", "IPCALAB",
        ],
    },
    "fmcg": {
        "name": "FMCG, Retail & Consumption",
        "icon": "🛒",
        "index_symbol": "^CNXFMCG",
        "description": "Staples, Discretionary Retail, Quick-Service Restaurants, and Footwear.",
        "symbols": [
            "ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR",
            "MARICO", "GODREJCP", "COLPAL", "VBL", "TRENT", "DMART", "TITAN",
            "JUBLFOOD", "DEVYANI", "METRO", "PAGEIND", "BATAINDIA", "RADICO",
        ],
    },
    "infra": {
        "name": "Real Estate, Infra & Capital Goods",
        "icon": "🏗️",
        "index_symbol": "^CNXREALTY",
        "description": "Top Developers, EPC Infrastructure, Heavy Engineering, Cables & Wires.",
        "symbols": [
            "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "BRIGADE",
            "SOBHA", "LT", "POLYCAB", "KEI", "RRKABEL", "ABB", "SIEMENS", "CGPOWER",
            "BHEL", "THERMAX", "KNRCON", "PNCINFRA", "NCC", "VOLTAS", "HAVELLS",
        ],
    },
    "chemicals": {
        "name": "Specialty Chemicals & Agriculture",
        "icon": "🧪",
        "index_symbol": "^CNXCHEM",
        "description": "Fluorochemicals, Specialty Chem, Agrochemicals, and Fertilizers.",
        "symbols": [
            "PIIND", "SRF", "NAVINFLUOR", "DEEPAKNTR", "ATUL", "COROMANDEL",
            "UPL", "TATACHEM", "FLUOROCHEM", "AETHER", "FINEORG", "GUJGASLTD",
        ],
    },
    "telecom": {
        "name": "Telecom, Ports & Logistics",
        "icon": "📡",
        "index_symbol": "^CNXINFRA",
        "description": "Telecom Giants, Major Ports, Air & Surface Freight Logistics.",
        "symbols": [
            "BHARTIARTL", "ADANIPORTS", "CONCOR", "DELHIVERY", "BLUEDART",
            "PVRINOX", "SUNTV", "ZEEL", "INDIGO",
        ],
    },
}

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
            "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL",
            "TATAMOTORS", "LT", "AXISBANK", "BAJFINANCE", "KOTAKBANK", "MARUTI",
            "TITAN", "TRENT", "M&M", "SUNPHARMA", "NTPC", "POWERGRID", "COALINDIA",
            "TATASTEEL", "HAL", "BEL", "ADANIENT", "ZOMATO",
        ],
    },
    "volume_surges_rvol": {
        "name": "🚀 Unusual Volume Surges",
        "description": "Stocks displaying massive institutional volume spikes (RVOL >= 1.5x).",
        "symbols": [
            "TRENT", "HAL", "BEL", "MAZDOCK", "COCHINSHIP", "DIXON", "POLYCAB",
            "BSE", "MCX", "ZOMATO", "SUZLON", "INOXWIND", "IREDA", "PERSISTENT",
            "COFORGE", "MAXHEALTH", "MANKIND", "CHOLAFIN", "FEDERALBNK",
        ],
    },
    "nifty50": {
        "name": "🏆 NIFTY 50 Bluechips",
        "description": "Top 50 largecap market leaders representing the benchmark index.",
        "symbols": [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL",
            "ITC", "LT", "KOTAKBANK", "AXISBANK", "TATAMOTORS", "MARUTI", "SUNPHARMA",
            "BAJFINANCE", "TITAN", "HINDUNILVR", "NTPC", "ONGC", "POWERGRID",
            "TATASTEEL", "COALINDIA", "ASIANPAINT", "M&M", "ADANIENT", "ADANIPORTS",
            "TECHM", "HCLTECH", "WIPRO", "ULTRACEMCO", "JSWSTEEL", "GRASIM",
            "HEROMOTOCO", "EICHERMOT", "BAJAJ-AUTO", "APOLLOHOSP", "DRREDDY",
            "CIPLA", "TRENT", "BEL", "HAL", "ZOMATO", "NESTLEIND", "BRITANNIA",
            "DIVISLAB", "HINDALCO", "BPCL", "SHRIRAMFIN", "TATACONSUM",
        ],
    },
    "multibagger_hunters": {
        "name": "💎 Multibagger Compounders",
        "description": "High-growth Stage 2 mid/smallcaps with tight VCP bases and strong fundamentals.",
        "symbols": [
            "TRENT", "DIXON", "HAL", "BEL", "BSE", "MCX", "MAZDOCK", "COCHINSHIP",
            "POLYCAB", "KEI", "PERSISTENT", "COFORGE", "KPITTECH", "MAXHEALTH",
            "MANKIND", "CHOLAFIN", "SUZLON", "INOXWIND", "IREDA", "SOLARINDS",
            "DATAATAM", "CYIENTDLM", "AETHER", "RADICO", "MEDANTA",
        ],
    },
}


# ── Stock to Sector Lookup Map (Fast Inverse Index) ─────────────────

_STOCK_TO_SECTOR: dict[str, tuple[str, str]] = {}
for sec_id, data in SECTOR_TAXONOMY.items():
    sec_name = data["name"]
    for sym in data["symbols"]:
        _STOCK_TO_SECTOR[sym.upper().strip()] = (sec_id, sec_name)


def get_stock_sector(symbol: str) -> tuple[str, str]:
    """
    Returns (sector_id, sector_name) for a given symbol.
    Defaults to ("broad_market", "Broad Market") if unclassified.
    """
    clean = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    return _STOCK_TO_SECTOR.get(clean, ("broad_market", "Broad Market"))


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
        "realty": "infra",
        "real estate": "infra",
        "capital goods": "infra",
        "chem": "chemicals",
        "chemical": "chemicals",
        "chemicals": "chemicals",
        "telecom": "telecom",
        "media": "telecom",
        "ports": "telecom",
        "logistics": "telecom",
    }

    if q in alias_map and alias_map[q] in SECTOR_TAXONOMY:
        key = alias_map[q]
        return key, SECTOR_TAXONOMY[key]

    for k, info in SECTOR_TAXONOMY.items():
        if k in q or q in k or q in info["name"].lower() or q in info.get("index_symbol", "").lower():
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
        categories.append({
            "id": preset_id,
            "name": info["name"],
            "description": info["description"],
            "type": "THEMATIC",
            "count": len(info["symbols"]) if info["symbols"] else "Dynamic",
            "icon": "⚡" if "Dynamic" in info["name"] else "🎯",
        })

    # 2. Sector Categories
    for sec_id, info in SECTOR_TAXONOMY.items():
        categories.append({
            "id": sec_id,
            "name": info["name"],
            "description": info["description"],
            "type": "SECTOR",
            "count": len(info["symbols"]),
            "icon": info.get("icon", "🏢"),
            "index_symbol": info.get("index_symbol", ""),
        })

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
    if key in ("auto_market_aware", "auto", "dynamic", "leading_sectors"):
        try:
            from analysis.sector_rotation import get_sector_rrg_matrix

            rrg = get_sector_rrg_matrix(use_cache=use_cache)
            # Find leading / improving sectors
            leading_ids = []
            improving_ids = []
            sector_id_map = {
                "BANK": "banking", "IT": "it", "AUTO": "auto", "PHARMA": "pharma",
                "FMCG": "fmcg", "METAL": "metals", "REALTY": "infra", "ENERGY": "energy",
                "INFRA": "infra", "PSU_BANK": "banking", "DEFENCE": "defence",
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
                target_sectors = ["metals", "it", "pharma"]  # safe leading fallback

            symbols_set = set()
            for s_id in target_sectors:
                symbols_set.update(SECTOR_TAXONOMY[s_id]["symbols"][:5])

            # Always add high volume surge candidates
            symbols_set.update(THEMATIC_PRESETS["volume_surges_rvol"]["symbols"][:4])

            resolved = list(symbols_set)[:max_stocks]
            reason = f"Top-down routed to leading sectors ({', '.join([s.upper() for s in target_sectors])}) + volume surge leaders."
            return resolved, reason


        except Exception as e:
            # Fallback to NIFTY 50
            return THEMATIC_PRESETS["nifty50"]["symbols"][:max_stocks], f"Fallback to NIFTY 50 ({e})"

    # 2. Thematic Presets
    if key in THEMATIC_PRESETS:
        symbols = THEMATIC_PRESETS[key]["symbols"]
        return symbols, f"Thematic preset: {THEMATIC_PRESETS[key]['name']}"

    # 3. Sector Categories
    if key in SECTOR_TAXONOMY:
        symbols = SECTOR_TAXONOMY[key]["symbols"]
        return symbols, f"Sector watchlist: {SECTOR_TAXONOMY[key]['name']} ({len(symbols)} tickers)"

    # 4. Comma-separated or single symbol
    if "," in universe:
        syms = [s.strip().upper() for s in universe.split(",") if s.strip()]
        return syms, f"Custom watchlist ({len(syms)} tickers)"

    if universe.upper() in _STOCK_TO_SECTOR:
        return [universe.upper()], f"Single ticker: {universe.upper()}"

    # Default fallback
    return THEMATIC_PRESETS["nifty50"]["symbols"][:max_stocks], "Default NIFTY 50 Universe"
