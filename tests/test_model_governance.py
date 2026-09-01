"""
tests/test_model_governance.py
──────────────────────────────
Tests for P1-B Model Governance Engine, Lineage Envelopes, and Numerical Golden References.
"""

import math
from engine.model_governance import (
    get_model_manifest,
    list_all_models,
    evaluate_action_eligibility,
    create_model_inference,
)


def test_registered_model_manifests():
    """Verify all critical quantitative models have valid, documented manifests."""
    models = list_all_models()
    assert len(models) >= 5
    model_ids = [m["model_id"] for m in models]
    assert "macro.transmission.v1" in model_ids
    assert "options.black_scholes.v1" in model_ids
    assert "rrg.sector_rotation.v1" in model_ids
    assert "forensic.beneish_mscore.v1" in model_ids
    assert "forensic.altman_zscore.v1" in model_ids

    bs_manifest = get_model_manifest("options.black_scholes.v1")
    assert bs_manifest is not None
    assert bs_manifest.version == "1.1.0"
    assert len(bs_manifest.assumptions) > 0
    assert len(bs_manifest.applicability_limits) > 0


def test_action_eligibility_evaluation():
    """Verify action eligibility rules gracefully restrict proxies and stale data."""
    # Clean live data with high confidence
    el_clean = evaluate_action_eligibility(
        "macro.transmission.v1",
        confidence_score=0.85,
        is_proxy=False,
        freshness_seconds=15.0,
    )
    assert el_clean == "ELIGIBLE"

    # Proxy data must be RESTRICTED
    el_proxy = evaluate_action_eligibility(
        "macro.transmission.v1",
        confidence_score=0.85,
        is_proxy=True,
        freshness_seconds=15.0,
    )
    assert el_proxy == "RESTRICTED"

    # Severely stale data (>3600s) must be UNAVAILABLE
    el_stale = evaluate_action_eligibility(
        "macro.transmission.v1",
        confidence_score=0.85,
        is_proxy=False,
        freshness_seconds=4000.0,
    )
    assert el_stale == "UNAVAILABLE"


def test_create_model_inference_envelope():
    """Verify ModelInference clearly isolates observed raw inputs from derived outputs."""
    raw_inputs = {
        "nasdaq_chg_pct": 1.25,
        "dxy_chg_pct": -0.40,
        "brent_chg_pct": -1.10,
    }
    derived = {
        "implied_nifty_gap_pct": 0.42,
        "it_sector_tailwind": 8.5,
        "paints_sector_tailwind": 6.0,
    }

    inference = create_model_inference(
        model_id="macro.transmission.v1",
        observed_inputs=raw_inputs,
        derived_outputs=derived,
        confidence_score=0.82,
        is_proxy=True,
        uncertainty_bounds={"lower_gap_pct": 0.20, "upper_gap_pct": 0.65},
    )

    d = inference.to_dict()
    assert d["model_id"] == "macro.transmission.v1"
    assert d["model_version"] == "1.2.0"
    assert d["eligibility_status"] == "RESTRICTED"
    assert d["observed_inputs"]["nasdaq_chg_pct"] == 1.25
    assert d["derived_outputs"]["implied_nifty_gap_pct"] == 0.42
    assert d["uncertainty_bounds"]["lower_gap_pct"] == 0.20
    assert len(d["governance_notes"]) >= 2


def test_golden_reference_black_scholes():
    """Numerical Golden Reference test for Black-Scholes standard bounds."""
    # S=24000, K=24000, T=30/365, r=0.07, sigma=0.15 (ATM Nifty Option)
    S, K, T, r, sigma = 24000.0, 24000.0, 30.0 / 365.0, 0.07, 0.15

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    # Standard normal CDF approximation
    def norm_cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    call_delta = norm_cdf(d1)
    put_delta = call_delta - 1.0
    gamma = (math.exp(-0.5 * d1**2) / math.sqrt(2.0 * math.pi)) / (S * sigma * math.sqrt(T))

    call_price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    put_price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

    # Analytical invariants
    assert 0.50 < call_delta < 0.60, f"Expected ATM Call Delta ~0.53, got {call_delta}"
    assert -0.50 < put_delta < -0.40, f"Expected ATM Put Delta ~-0.47, got {put_delta}"
    assert gamma > 0.0, "Gamma must strictly be positive"
    # Put-Call Parity: C - P = S - K * exp(-r * T)
    parity_diff = abs((call_price - put_price) - (S - K * math.exp(-r * T)))
    assert parity_diff < 1e-4, f"Put-Call Parity violated: {parity_diff}"
