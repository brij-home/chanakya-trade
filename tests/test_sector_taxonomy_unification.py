"""
tests/test_sector_taxonomy_unification.py
──────────────────────────────────────────
Verification suite for institutional sector and segment taxonomy unification:
  1. Prestige Estates (PRESTIGE) resolution across universe, sector rotation, and multi-agent debate.
  2. Elimination of "Sector mapping not available" for liquid NSE/BSE equities.
  3. Total Market dataset ingestion (755+ constituents).
  4. SEBI Large-Cap tier classification (Nifty 100 coverage).
  5. 11-sector institutional market snapshot coverage in market/indices.py.
  6. resolve_sector_taxonomy fix for Real Estate.
  7. Dynamic GICS/Industry metadata discovery fallback.
"""

from unittest.mock import MagicMock


from agent.multi_agent import SectorRotationAnalyst
from agent.tools import ToolRegistry
from analysis.universe import (
    get_stock_sector,
    get_stock_cap_tier,
    get_stock_segment_profile,
    resolve_sector_taxonomy,
    _STOCK_TO_SECTOR,
)
from market.indices import INDEX_INSTRUMENTS, _YF_SECTOR_MAP


class TestPrestigeAndLiquidUniverseResolution:
    def test_prestige_segment_profile(self):
        profile = get_stock_segment_profile("PRESTIGE")
        assert profile["symbol"] == "PRESTIGE"
        assert profile["sector_id"] == "realty"
        assert "Real Estate" in profile["sector_name"]
        assert profile["sector_index"] == "^CNXREALTY"
        assert profile["exchange"] == "NSE"
        assert profile["is_fo"] is True
        assert profile["cap_tier"] in ("LARGE", "MID")

    def test_prestige_sector_rotation_analyst_no_unavailable_message(self):
        analyst = SectorRotationAnalyst(ToolRegistry())
        report = analyst.analyze("PRESTIGE")
        assert report.verdict in ("BULLISH", "BEARISH", "NEUTRAL")
        assert report.score != 0.0
        # Crucial check: verify the old false warning is NEVER present
        for pt in report.key_points:
            assert "Sector mapping not available" not in pt
        assert any("REALTY" in pt or "Real Estate" in pt for pt in report.key_points)

    def test_realty_sector_drilldown_resolution(self):
        sec_id, sec_data = resolve_sector_taxonomy("realty")
        assert sec_id == "realty"
        assert "Real Estate" in sec_data["name"]

        sec_id2, _ = resolve_sector_taxonomy("real estate")
        assert sec_id2 == "realty"

    def test_previously_missing_stocks_coverage(self):
        """Verify that previously missing/misclassified stocks resolve properly."""
        test_cases = {
            "BEL": ("defence", "Defence & Aerospace"),
            "HAL": ("defence", "Defence & Aerospace"),
            "TRENT": ("fmcg", "FMCG, Retail & Consumption"),
            "ZOMATO": ("it", "IT, Software & Technology"),
            "DIXON": ("it", "IT, Software & Technology"),
            "SUZLON": ("energy", "Energy, Power & Green Transition"),
            "BSE": ("banking", "Banking & Financial Services"),
            "POLYCAB": ("infra", "Infrastructure & Capital Goods"),
            "OBEROIRLTY": ("realty", "Real Estate & Housing"),
            "BRIGADE": ("realty", "Real Estate & Housing"),
            "SOBHA": ("realty", "Real Estate & Housing"),
            "HUDCO": ("banking", "Banking & Financial Services"),
            "360ONE": ("banking", "Banking & Financial Services"),
            "NBCC": ("infra", "Infrastructure & Capital Goods"),
        }
        for sym, (expected_id, expected_name) in test_cases.items():
            sec_id, sec_name = get_stock_sector(sym)
            assert sec_id == expected_id, f"{sym} expected {expected_id} but got {sec_id}"
            assert expected_name in sec_name or sec_name in expected_name


class TestSEBIMarketCapTiers:
    def test_large_cap_includes_nifty_next_50(self):
        """Under SEBI classification, Nifty Next 50 (ranks 51-100) are Large Cap."""
        large_caps = ["ABB", "DMART", "HAL", "BEL", "ZOMATO", "TRENT", "ADANIPOWER"]
        for sym in large_caps:
            tier = get_stock_cap_tier(sym)
            assert tier == "LARGE", f"{sym} should be classified as LARGE cap, got {tier}"

    def test_mid_and_small_cap_tiers(self):
        assert get_stock_cap_tier("PRESTIGE") in ("LARGE", "MID")
        assert get_stock_cap_tier("KAYNES") in ("MID", "SMALL")


class TestIndicesSectorSnapshotCoverage:
    def test_all_11_canonical_sectors_present(self):
        expected_sectors = [
            "BANK",
            "IT",
            "PHARMA",
            "AUTO",
            "FMCG",
            "REALTY",
            "METAL",
            "ENERGY",
            "INFRA",
            "PSU_BANK",
            "MEDIA",
        ]
        for sec in expected_sectors:
            assert sec in INDEX_INSTRUMENTS, f"INDEX_INSTRUMENTS missing {sec}"
            assert sec in _YF_SECTOR_MAP, f"_YF_SECTOR_MAP missing {sec}"


class TestDynamicGICSFallback:
    def test_unlisted_stock_dynamic_lookup_and_caching(self, monkeypatch):
        """Simulates an unlisted/newly listed stock with mock fundamentals."""
        mock_fund = MagicMock()
        mock_fund.sector = "Real Estate"
        mock_fund.industry = "Real Estate Development"

        monkeypatch.setattr(
            "analysis.fundamental.analyse",
            lambda sym: mock_fund if sym == "NEW_REALTY_IPO" else None,
        )

        sec_id, sec_name = get_stock_sector("NEW_REALTY_IPO")
        assert sec_id == "realty"
        assert "Real Estate" in sec_name
        # Verified cached into in-memory fast inverse index
        assert "NEW_REALTY_IPO" in _STOCK_TO_SECTOR


class TestStockProfileEndpointAndFrontendSync:
    def test_get_stock_profile_prestige(self):
        import asyncio
        from web.api import get_stock_profile

        res = asyncio.run(get_stock_profile("PRESTIGE"))
        assert res["status"] == "success"
        data = res["data"]
        assert data["symbol"] == "PRESTIGE"
        assert data["sector_id"] == "realty"
        assert "Real Estate" in data["sector_name"]
        assert data["sector_index"] == "^CNXREALTY"
        assert data["exchange"] == "NSE"
        assert data["is_fo"] is True

    def test_get_stock_profile_multi_asset(self):
        import asyncio
        from web.api import get_stock_profile

        gold = asyncio.run(get_stock_profile("GOLD"))
        assert gold["data"]["exchange"] == "MCX"
        assert gold["data"]["sector_id"] == "commodity"

        usdinr = asyncio.run(get_stock_profile("USDINR"))
        assert usdinr["data"]["exchange"] == "CDS"
        assert usdinr["data"]["sector_id"] == "currency"


class TestPrestigeForensicDynamicAudit:
    def test_prestige_forensic_audit_resolution(self):
        from analysis.forensic import audit_forensics

        audit = audit_forensics("PRESTIGE", use_cache=False)
        assert audit.available is True
        assert audit.quality_rating in ("A+", "A", "B", "C", "D")
        assert 1 <= audit.piotroski_f_score <= 9
        assert isinstance(audit.altman_z_score, float)
        assert isinstance(audit.beneish_m_score, float)
        assert audit.overall_flag == audit.overall_forensic_verdict


class TestFrontendUniverseDataIntegrity:
    def test_prestige_canonical_sector_in_frontend(self):
        import re

        with open("macos-app/src/renderer/src/data/universeData.js", "r", encoding="utf-8") as f:
            content = f.read()

        # PRESTIGE must have sector: 'Realty', isFO: true, lotSize: 475
        m = re.search(r"symbol:\s*'PRESTIGE'[^}]+", content)
        assert m is not None, "PRESTIGE must be present in universeData.js"
        prestige_entry = m.group(0)
        assert "sector: 'Realty'" in prestige_entry
        assert "isFO: true" in prestige_entry
        assert "lotSize: 475" in prestige_entry

        # No whimsical non-standard sectors in universeData.js
        disallowed = [
            "Realty & South India",
            "Realty & Mumbai Luxury",
            "Realty & Luxury Housing",
            "Auto Batteries & Lithium Cells",
            "Commercial Malls & Leases",
        ]
        for bad_sec in disallowed:
            assert f"sector: '{bad_sec}'" not in content, f"Found disallowed sector: {bad_sec}"
