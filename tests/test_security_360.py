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
    assert dossier.valuation_fair_value is not None
    assert dossier.valuation_fair_value > 2800.0
    assert dossier._status == "READY"
    assert "IST" in dossier._as_of or "+05:30" in dossier._as_of

    # Check Methodology Lenses
    assert len(dossier.methodology_lenses) >= 4
    lens_ids = [l.lens_id for l in dossier.methodology_lenses]
    assert "minervini_sepa" in lens_ids
    assert "buffett_moat" in lens_ids
    assert "smc_liquidity" in lens_ids
    assert "taleb_convexity" in lens_ids

    # Check Decision Summary
    assert dossier.decision is not None
    assert dossier.decision.action_eligibility == "ELIGIBLE"
    assert dossier.decision.invalidation_level < 2800.0
    assert dossier.decision.target_1 > 2800.0
    assert dossier.decision.target_2 > dossier.decision.target_1
    assert dossier.decision.max_planned_loss > 0


def test_security_360_to_dict_serializability():
    """Verify dossier converts cleanly to JSON-compatible dictionary."""
    dossier = build_security_360_dossier(symbol="TCS", current_price=4100.0)
    data = dossier.to_dict()

    assert isinstance(data, dict)
    assert data["symbol"] == "TCS"
    assert data["decision"]["action_eligibility"] == "ELIGIBLE"
    assert isinstance(data["methodology_lenses"], list)
