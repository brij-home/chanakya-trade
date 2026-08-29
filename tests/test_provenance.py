"""
tests/test_provenance.py
────────────────────────
Unit tests for Universal Data Provenance Engine.
"""

from engine.provenance import create_provenance, attach_provenance, DataProvenance


def test_create_provenance_defaults():
    prov = create_provenance("LIVE_TICK")
    assert prov.data_source == "LIVE_TICK"
    assert prov.freshness_seconds == 0.0
    assert prov.completeness_pct == 100.0
    assert prov.is_indicative_proxy is False
    assert "IST" in prov.as_of_ist


def test_create_provenance_proxy():
    prov = create_provenance("SYNTHETIC_PROXY", is_proxy=True, fallback_reason="Simulated Black-Scholes chain")
    assert prov.data_source == "SYNTHETIC_PROXY"
    assert prov.is_indicative_proxy is True
    assert prov.fallback_reason == "Simulated Black-Scholes chain"


def test_attach_provenance():
    data = {"symbol": "NIFTY", "ltp": 24250.0}
    enriched = attach_provenance(data, source="NSE_SCRAPER", is_proxy=False)
    assert "_provenance" in enriched
    assert enriched["_provenance"]["data_source"] == "NSE_SCRAPER"
    assert enriched["symbol"] == "NIFTY"
