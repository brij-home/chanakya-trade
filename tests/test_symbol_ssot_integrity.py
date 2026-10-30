"""
tests/test_symbol_ssot_integrity.py
───────────────────────────────────
Institutional Invariant Test Suite for Universal Single Source of Truth (SSOT)
Symbol Normalization and Corporate Alias Resolution.

Verifies:
  1. Universal Canonicalization & Alias Resolution (INFOSYS -> INFY, ZOMATO -> ETERNAL, etc.)
  2. Prefix & Suffix Stripping across all exchanges & data vendors
  3. Zero un-canonical or obsolete symbols in INDEX_HEAVYWEIGHTS & HBCM_CONSTITUENTS
  4. Zero un-canonical or legacy aliases in SECTOR_TAXONOMY, THEMATIC_PRESETS, and STOCK_SECTOR_MAP
"""

import pytest
from market.instruments import resolve_corporate_alias, canonical_symbol
from market.indices import INDEX_HEAVYWEIGHTS
from engine.hbcm import HBCM_CONSTITUENTS
from analysis.universe import SECTOR_TAXONOMY, THEMATIC_PRESETS
from analysis.sector_rotation import STOCK_SECTOR_MAP


def test_colloquial_and_commercial_alias_resolution():
    """Verify common colloquial/commercial names resolve to canonical exchange tickers."""
    cases = {
        "INFOSYS": "INFY",
        "BAJAJFINANCE": "BAJFINANCE",
        "BAJAJFINSERV": "BAJFINSV",
        "HUL": "HINDUNILVR",
        "AIRTEL": "BHARTIARTL",
        "BHARTI": "BHARTIARTL",
        "ULTRATECH": "ULTRACEMCO",
        "ULTRATECHCEMENT": "ULTRACEMCO",
        "EICHER": "EICHERMOT",
        "EICHERMOTORS": "EICHERMOT",
        "HERO": "HEROMOTOCO",
        "HEROHONDA": "HEROMOTOCO",
        "ASIANPAINTS": "ASIANPAINT",
        "DRREDDYS": "DRREDDY",
        "APOLLOHOSPITALS": "APOLLOHOSP",
        "TATACONSUMER": "TATACONSUM",
        "MM": "M&M",
        "M_M": "M&M",
        "L&T": "LT",
        "L&TFH": "LTF",
        "IBULHSGFIN": "SAMMAANCAP",
        "MOTHERSUMI": "MOTHERSON",
        "CADILAHC": "ZYDUSLIFE",
        "ZOMATO": "ETERNAL",
        "CENTURYTEX": "ABREL",
        "UNOINDA": "UNOMINDA",
        "CEINFO": "MAPMYINDIA",
        "SWANENERGY": "SWANCORP",
        "JUPITERWAG": "JWL",
        "KALPATPOWR": "KPIL",
    }
    for raw, expected in cases.items():
        resolved = resolve_corporate_alias(raw)
        assert resolved == expected, f"resolve_corporate_alias({raw}) expected {expected}, got {resolved}"


def test_canonical_symbol_normalization_across_venues_and_formats():
    """Verify canonical_symbol strips prefixes, suffixes, and resolves aliases universally."""
    cases = {
        "NSE:INFOSYS-EQ": "INFY",
        "BSE:INFOSYS": "INFY",
        "INFOSYS.NS": "INFY",
        "INFOSYS.BO": "INFY",
        "NSE:ZOMATO-EQ": "ETERNAL",
        "BSE:ZOMATO-EQ": "ETERNAL",
        "ZOMATO.NS": "ETERNAL",
        "NSE:BAJAJFINANCE-EQ": "BAJFINANCE",
        "NSE:HUL-EQ": "HINDUNILVR",
        "NSE:AIRTEL-EQ": "BHARTIARTL",
        "NSE:CENTURYTEX-EQ": "ABREL",
        "NSE:JUPITERWAG-EQ": "JWL",
        "NSE:KALPATPOWR-EQ": "KPIL",
        "NSE:CEINFO-EQ": "MAPMYINDIA",
        "NSE:SWANENERGY-EQ": "SWANCORP",
        "NSE:UNOINDA-EQ": "UNOMINDA",
        "NIFTY 50": "NIFTY",
        "NIFTY50": "NIFTY",
        "^NSEI": "NIFTY",
        "BANK NIFTY": "BANKNIFTY",
        "^NSEBANK": "BANKNIFTY",
        "BSE SENSEX": "SENSEX",
    }
    for raw, expected in cases.items():
        normalized = canonical_symbol(raw)
        assert normalized == expected, f"canonical_symbol({raw}) expected {expected}, got {normalized}"


def test_index_heavyweights_purity():
    """Verify INDEX_HEAVYWEIGHTS contains only canonical tickers (e.g. INFY, never INFOSYS)."""
    disallowed = {"INFOSYS", "ZOMATO", "BAJAJFINANCE", "HUL", "AIRTEL", "CENTURYTEX", "JUPITERWAG", "CEINFO"}
    for idx_name, syms in INDEX_HEAVYWEIGHTS.items():
        for s in syms:
            assert s not in disallowed, f"Disallowed alias {s} found in INDEX_HEAVYWEIGHTS[{idx_name}]"
            # Must match its own canonical resolution
            assert canonical_symbol(s) == s, f"Symbol {s} in INDEX_HEAVYWEIGHTS[{idx_name}] is not in canonical form"


def test_hbcm_constituents_purity():
    """Verify HBCM_CONSTITUENTS contains strictly canonical symbols."""
    disallowed = {"INFOSYS", "ZOMATO", "BAJAJFINANCE", "HUL", "AIRTEL", "CENTURYTEX", "JUPITERWAG", "CEINFO"}
    for idx_name, items in HBCM_CONSTITUENTS.items():
        for item in items:
            s = item["symbol"]
            assert s not in disallowed, f"Disallowed alias {s} found in HBCM_CONSTITUENTS[{idx_name}]"
            assert canonical_symbol(s) == s, f"Symbol {s} in HBCM_CONSTITUENTS[{idx_name}] is not canonical"


def test_universe_and_sector_taxonomy_purity():
    """Verify SECTOR_TAXONOMY, THEMATIC_PRESETS, and STOCK_SECTOR_MAP have zero legacy un-canonical symbols."""
    disallowed = {
        "INFOSYS", "ZOMATO", "CENTURYTEX", "UNOINDA", "CEINFO",
        "SWANENERGY", "JUPITERWAG", "KALPATPOWR", "HITACHI", "GSHIP", "KBL"
    }

    # 1. SECTOR_TAXONOMY
    for sec_name, data in SECTOR_TAXONOMY.items():
        syms = data.get("symbols", [])
        for s in syms:
            assert s not in disallowed, f"Disallowed alias {s} found in SECTOR_TAXONOMY[{sec_name}]"

    # 2. THEMATIC_PRESETS
    for preset_name, data in THEMATIC_PRESETS.items():
        syms = data.get("symbols", [])
        for s in syms:
            assert s not in disallowed, f"Disallowed alias {s} found in THEMATIC_PRESETS[{preset_name}]"

    # 3. STOCK_SECTOR_MAP
    for s in STOCK_SECTOR_MAP:
        assert s not in disallowed, f"Disallowed alias {s} found in STOCK_SECTOR_MAP"

