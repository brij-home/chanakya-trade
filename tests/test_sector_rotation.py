"""
tests/test_sector_rotation.py
──────────────────────────────
Unit tests for RRG (Relative Rotation Graph) and sector momentum calculations.
"""

from __future__ import annotations

import pytest
from analysis.sector_rotation import (
    SectorRRGPoint,
    _classify_quadrant,
    compute_rrg_series,
    get_sector_rrg_matrix,
    get_stock_sector_alignment,
)


class TestRRGCalculations:
    def test_classify_quadrant_leading(self):
        assert _classify_quadrant(105.0, 102.0) == "LEADING"

    def test_classify_quadrant_weakening(self):
        assert _classify_quadrant(105.0, 98.0) == "WEAKENING"

    def test_classify_quadrant_lagging(self):
        assert _classify_quadrant(95.0, 98.0) == "LAGGING"

    def test_classify_quadrant_improving(self):
        assert _classify_quadrant(95.0, 103.0) == "IMPROVING"

    def test_compute_rrg_series_insufficient_data(self):
        ratio, momentum = compute_rrg_series([100.0, 101.0], [200.0, 202.0], period=10)
        assert ratio == 100.0
        assert momentum == 100.0

    def test_compute_rrg_series_outperforming(self):
        # Sector steadily gaining on benchmark
        sector = [100.0 + i * 2.0 for i in range(20)]
        benchmark = [200.0 + i * 1.0 for i in range(20)]
        ratio, momentum = compute_rrg_series(sector, benchmark, period=10)
        assert ratio > 100.0
        assert momentum >= 90.0


class TestSectorMatrix:
    def test_get_sector_rrg_matrix_returns_all_sectors(self, monkeypatch):
        from market.indices import IndexSnapshot
        import market.indices as ind_mod
        import market.quotes as q_mod

        fake_snaps = [
            IndexSnapshot(
                name=k,
                instrument=f"^{k}",
                ltp=1000.0,
                change=10.0,
                change_pct=1.0,
                open=990.0,
                high=1010.0,
                low=985.0,
            )
            for k in ["BANK", "IT", "PHARMA", "AUTO", "FMCG", "METAL", "REALTY", "ENERGY", "INFRA", "PSU_BANK"]
        ]
        monkeypatch.setattr(ind_mod, "get_sector_snapshot", lambda: fake_snaps)
        monkeypatch.setattr(q_mod, "get_quote", lambda _: {})

        matrix = get_sector_rrg_matrix(use_cache=False)
        assert len(matrix) >= 8
        sector_names = [p.sector for p in matrix]
        assert "BANK" in sector_names
        assert "IT" in sector_names
        assert "PHARMA" in sector_names
        assert "AUTO" in sector_names
        assert "METAL" in sector_names

    def test_sector_rrg_point_dict(self):
        p = SectorRRGPoint(
            sector="IT",
            symbol="^CNXIT",
            rs_ratio=104.5,
            rs_momentum=101.2,
            quadrant="LEADING",
            day_change_pct=1.2,
            benchmark_change_pct=0.4,
            relative_strength=105.0,
        )
        d = p.as_dict()
        assert d["sector"] == "IT"
        assert d["quadrant"] == "LEADING"
        assert d["rs_ratio"] == 104.5
        assert d["rs_momentum"] == 101.2


class TestStockSectorAlignment:
    def test_known_stock_it(self, monkeypatch):
        from market.indices import IndexSnapshot
        import market.indices as ind_mod

        fake_snaps = [
            IndexSnapshot(
                name="IT",
                instrument="^CNXIT",
                ltp=30000.0,
                change=300.0,
                change_pct=1.0,
                open=29800.0,
                high=30200.0,
                low=29700.0,
            )
        ]
        monkeypatch.setattr(ind_mod, "get_sector_snapshot", lambda: fake_snaps)

        res = get_stock_sector_alignment("INFY")
        assert res["symbol"] == "INFY"
        assert res["sector"] == "IT"
        assert res["quadrant"] in ("LEADING", "WEAKENING", "LAGGING", "IMPROVING")
        assert 0 <= res["tailwind_score"] <= 100
        assert res["alignment"] in ("STRONG_TAILWIND", "MODERATE_TAILWIND", "NEUTRAL", "HEADWIND")

    def test_known_stock_metal(self, monkeypatch):
        from market.indices import IndexSnapshot
        import market.indices as ind_mod

        fake_snaps = [
            IndexSnapshot(
                name="METAL",
                instrument="^CNXMETAL",
                ltp=5000.0,
                change=50.0,
                change_pct=1.0,
                open=4950.0,
                high=5050.0,
                low=4920.0,
            )
        ]
        monkeypatch.setattr(ind_mod, "get_sector_snapshot", lambda: fake_snaps)

        res = get_stock_sector_alignment("TATASTEEL")
        assert res["symbol"] == "TATASTEEL"
        assert res["sector"] == "METAL"

    def test_unknown_stock_defaults_to_broad_market(self):
        res = get_stock_sector_alignment("UNKNOWN_TICKER_XYZ")
        assert res["sector"] == "BROAD_MARKET"
        assert res["alignment"] == "NEUTRAL"
        assert res["tailwind_score"] == 50
