import pytest
from unittest.mock import patch

from analysis.universe import (
    SECTOR_TAXONOMY,
    THEMATIC_PRESETS,
    get_stock_sector,
    get_taxonomy_categories,
    resolve_dynamic_universe,
)
from analysis.sector_rotation import SectorRRGPoint


def test_sector_taxonomy_completeness():
    assert len(SECTOR_TAXONOMY) >= 10
    required_sectors = ["banking", "it", "auto", "defence", "energy", "metals", "pharma", "fmcg", "infra", "chemicals"]
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
        SectorRRGPoint(sector="DEFENCE", symbol="^CNXDEFENCE", rs_ratio=105.0, rs_momentum=108.0, quadrant="LEADING"),
        SectorRRGPoint(sector="IT", symbol="^CNXIT", rs_ratio=102.0, rs_momentum=103.0, quadrant="LEADING"),
        SectorRRGPoint(sector="BANK", symbol="^NSEBANK", rs_ratio=98.0, rs_momentum=95.0, quadrant="LAGGING"),
    ]

    with patch("analysis.sector_rotation.get_sector_rrg_matrix", return_value=fake_rrg):
        resolved, reason = resolve_dynamic_universe("auto_market_aware")
        assert len(resolved) > 0
        assert "Top-down routed to leading sectors" in reason
        # Should include symbols from leading sectors (defence or it)
        assert any(sym in ["HAL", "BEL", "TCS", "INFY"] for sym in resolved)
