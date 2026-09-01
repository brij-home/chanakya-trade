"""
tests/test_provenance_timezone.py
──────────────────────────────────
Tests for universal data provenance and mathematical UTC to Asia/Kolkata (+05:30) conversion.
"""

from engine.provenance import (
    create_provenance,
    attach_provenance,
    DataProvenance,
)


def test_provenance_utc_to_ist_conversion():
    """Verify that a given UTC timestamp converts exactly to +05:30 IST string."""
    # 2026-09-02 04:00:00 UTC = 2026-09-02 09:30:00 IST
    utc_iso = "2026-09-02T04:00:00+00:00"
    prov = DataProvenance(data_source="LIVE_TICK", as_of=utc_iso)

    assert "02 Sep 2026, 09:30:00 IST" == prov.as_of_ist
    assert prov.data_source == "LIVE_TICK"
    assert prov.is_tradable is True
    assert prov.venue == "NSE"


def test_provenance_proxy_sets_non_tradable():
    """Verify that synthetic proxy provenance automatically sets is_tradable to False."""
    prov = create_provenance(
        source="SYNTHETIC_PROXY",
        is_proxy=True,
        fallback_reason="No real-time NFO feed",
    )
    assert prov.is_indicative_proxy is True
    assert prov.is_tradable is False
    assert prov.fallback_reason == "No real-time NFO feed"


def test_attach_provenance_to_dict():
    """Verify attach_provenance wraps payload with valid _provenance dictionary."""
    data = {"symbol": "INFY", "ltp": 1850.0}
    enriched = attach_provenance(data, source="LIVE_BROKER", venue="NSE")

    assert "_provenance" in enriched
    meta = enriched["_provenance"]
    assert meta["data_source"] == "LIVE_BROKER"
    assert meta["venue"] == "NSE"
    assert "IST" in meta["as_of_ist"]
