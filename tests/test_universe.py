from unittest.mock import patch

from analysis.universe import (
    SECTOR_TAXONOMY,
    get_stock_sector,
    get_taxonomy_categories,
    resolve_dynamic_universe,
)
from analysis.sector_rotation import SectorRRGPoint


def test_sector_taxonomy_completeness():
    assert len(SECTOR_TAXONOMY) >= 10
    required_sectors = [
        "banking",
        "it",
        "auto",
        "defence",
        "energy",
        "metals",
        "pharma",
        "fmcg",
        "infra",
        "chemicals",
    ]
    for sec in required_sectors:
        assert sec in SECTOR_TAXONOMY
        assert len(SECTOR_TAXONOMY[sec]["symbols"]) >= 8
        assert "name" in SECTOR_TAXONOMY[sec]
        assert "icon" in SECTOR_TAXONOMY[sec]


def test_get_stock_sector():
    sec_id, sec_name = get_stock_sector("HDFCBANK")
    assert sec_id == "banking"
    assert "Banking" in sec_name

    sec_id, sec_name = get_stock_sector("TCS")
    assert sec_id == "it"

    sec_id, sec_name = get_stock_sector("HAL")
    assert sec_id == "defence"

    sec_id, sec_name = get_stock_sector("UNKNOWN_TICKER_XYZ")
    assert sec_id == "broad_market"


def test_get_taxonomy_categories():
    cats = get_taxonomy_categories()
    assert len(cats) >= 15
    types = {c["type"] for c in cats}
    assert "THEMATIC" in types
    assert "SECTOR" in types

    thematics = [c for c in cats if c["type"] == "THEMATIC"]
    assert any(t["id"] == "auto_market_aware" for t in thematics)
    assert any(t["id"] == "most_liquid_today" for t in thematics)


def test_resolve_dynamic_universe_sector_and_presets():
    # 1. Sector lookup
    defence_syms, reason = resolve_dynamic_universe("defence")
    assert "HAL" in defence_syms
    assert "BEL" in defence_syms
    assert "Sector watchlist" in reason

    # 2. Preset lookup
    multibaggers, reason = resolve_dynamic_universe("multibagger_hunters")
    assert "TRENT" in multibaggers
    assert "Thematic preset" in reason

    # 3. Comma-separated list
    custom_syms, reason = resolve_dynamic_universe("INFY, TCS, RELIANCE")
    assert custom_syms == ["INFY", "TCS", "RELIANCE"]
    assert "Custom watchlist" in reason


def test_resolve_dynamic_universe_auto_market_aware():
    fake_rrg = [
        SectorRRGPoint(
            sector="DEFENCE",
            symbol="^CNXDEFENCE",
            rs_ratio=105.0,
            rs_momentum=108.0,
            quadrant="LEADING",
        ),
        SectorRRGPoint(
            sector="IT", symbol="^CNXIT", rs_ratio=102.0, rs_momentum=103.0, quadrant="LEADING"
        ),
        SectorRRGPoint(
            sector="BANK", symbol="^NSEBANK", rs_ratio=98.0, rs_momentum=95.0, quadrant="LAGGING"
        ),
    ]

    with patch("analysis.sector_rotation.get_sector_rrg_matrix", return_value=fake_rrg):
        resolved, reason = resolve_dynamic_universe("auto_market_aware")
        assert len(resolved) > 0
        assert "Top-down routed to leading sectors" in reason
        # Should include symbols from leading sectors (defence or it)
        assert any(sym in ["HAL", "BEL", "TCS", "INFY"] for sym in resolved)


def test_resolve_dynamic_universe_multi_asset_presets():
    # Commodities preset
    comm_syms, comm_reason = resolve_dynamic_universe("commodities")
    assert "GOLD" in comm_syms
    assert "CRUDEOIL" in comm_syms
    assert "Thematic preset" in comm_reason
    assert get_stock_sector("GOLD")[0] == "commodity"

    # ETF preset
    etf_syms, etf_reason = resolve_dynamic_universe("etfs")
    assert "NIFTYBEES" in etf_syms
    assert "GOLDBEES" in etf_syms
    assert "Thematic preset" in etf_reason
    assert get_stock_sector("NIFTYBEES")[0] == "etf"

    # Currency preset
    curr_syms, curr_reason = resolve_dynamic_universe("currencies")
    assert "USDINR" in curr_syms
    assert "Thematic preset" in curr_reason
    assert get_stock_sector("USDINR")[0] == "currency"

    # Index preset
    idx_syms, idx_reason = resolve_dynamic_universe("indices")
    assert "NIFTY50" in idx_syms
    assert "BANKNIFTY" in idx_syms
    assert "Thematic preset" in idx_reason

    # Single ticker resolution
    gold_single, r1 = resolve_dynamic_universe("MCX:GOLD")
    assert gold_single == ["GOLD"]
    assert "Single ticker" in r1

    usd_single, r2 = resolve_dynamic_universe("CDS:USDINR")
    assert usd_single == ["USDINR"]
    assert "Single ticker" in r2


def test_resolve_dynamic_universe_auto_sector():
    # Ensure "auto" resolves to Automobile sector taxonomy, NOT auto_market_aware
    auto_syms, reason = resolve_dynamic_universe("auto")
    assert "TATAMOTORS" in auto_syms
    assert "MARUTI" in auto_syms
    assert "M&M" in auto_syms
    assert "Sector watchlist: Automobiles & Mobility" in reason
