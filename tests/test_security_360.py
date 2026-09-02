"""
tests/test_security_360.py
───────────────────────────
Unit tests for P2-B Security 360 Institutional Decision Dossier.
"""

from engine.security_360 import build_security_360_dossier


def test_build_security_360_dossier_equity():
    """Verify dossier compilation for standard Indian equity."""
    dossier = build_security_360_dossier(symbol="RELIANCE", current_price=2800.0)

    assert dossier.symbol == "RELIANCE"
    assert dossier.canonical_symbol == "NSE:RELIANCE:EQUITY"
    assert dossier.exchange == "NSE"
    assert dossier.segment == "EQUITY"
    assert dossier.lot_size == 1
    assert dossier.current_price == 2800.0
    # Truthfulness contract: without a live DCF + all methodology lenses,
    # the dossier must expose an unavailable state rather than invent advice.
    assert dossier.valuation_fair_value is None
    assert dossier._status == "PARTIAL"
    assert "IST" in dossier._as_of or "+05:30" in dossier._as_of

    # Check Methodology Lenses
    assert dossier.methodology_lenses == []

    # Check Decision Summary
    assert dossier.decision is None


def test_security_360_to_dict_serializability():
    """Verify dossier converts cleanly to JSON-compatible dictionary."""
    dossier = build_security_360_dossier(symbol="TCS", current_price=4100.0)
    data = dossier.to_dict()

    assert isinstance(data, dict)
    assert data["symbol"] == "TCS"
    assert data["decision"] is None
    assert isinstance(data["methodology_lenses"], list)
