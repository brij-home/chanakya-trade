"""
tests/test_strategy_lab_p2c.py
───────────────────────────────
P2-C unit tests: Immutable Strategy Run Manifest and Options Chain Integrity Gate.
"""

import pytest
from engine.strategy_manifest import (
    create_run_manifest,
    verify_manifest_integrity,
    CostAssumptions,
    ExecutionAssumptions,
)
from engine.options_chain_integrity import validate_options_chain


# ── Strategy Manifest Tests ─────────────────────────────────────────────────

def test_manifest_creation_and_hash_binding():
    """Verify manifest is created with deterministic hash and bias guard flags."""
    manifest = create_run_manifest(
        strategy_id="minervini_vcp_v1",
        strategy_name="Minervini VCP Breakout Strategy",
        strategy_version="1.0.0",
        universe=["RELIANCE", "TCS", "INFY"],
        data_snapshot_start="2022-01-01",
        data_snapshot_end="2024-01-01",
        benchmark="NIFTY50",
        parameters={"lookback_days": 252, "rs_threshold": 85},
    )

    assert manifest.strategy_id == "minervini_vcp_v1"
    assert manifest.strategy_version == "1.0.0"
    assert manifest.universe == sorted(["RELIANCE", "TCS", "INFY"])
    assert len(manifest.manifest_hash) == 64  # SHA-256 hex
    assert len(manifest.run_id) == 36         # UUID4
    assert manifest.bias_prevention["look_ahead_guard_active"] is True
    assert manifest.bias_prevention["survivorship_bias_guard_active"] is True
    assert manifest.bias_prevention["corporate_action_adjusted"] is True
    assert manifest.bias_prevention["fill_delay_bars"] is True  # fill_delay >= 1


def test_manifest_hash_integrity_verification():
    """Verify that manifest hash verification detects tampering."""
    manifest = create_run_manifest(
        strategy_id="macd_cross_v2",
        strategy_name="MACD Signal Crossover",
        strategy_version="2.1.0",
        universe=["SBIN", "HDFCBANK"],
        data_snapshot_start="2023-01-01",
        data_snapshot_end="2024-06-01",
    )

    valid, reason = verify_manifest_integrity(manifest)
    assert valid is True
    assert reason == "VALID"

    # Tamper with the manifest
    manifest.universe = ["SBIN", "HDFCBANK", "ICICIBANK"]  # add symbol after sealing
    valid_after_tamper, reason_after = verify_manifest_integrity(manifest)
    assert valid_after_tamper is False
    assert "HASH_MISMATCH" in reason_after


def test_manifest_cost_assumptions_are_realistic():
    """Verify default cost model reflects real Indian statutory costs."""
    costs = CostAssumptions()
    round_trip_bps = costs.total_round_trip_bps()

    # Real round-trip for Indian equity delivery should be ~25–80 bps
    assert 15.0 <= round_trip_bps <= 150.0, f"Round-trip cost {round_trip_bps} bps seems unrealistic"
    assert costs.stt_delivery_pct == 0.001       # 0.1% STT on sell side
    assert costs.gst_on_brokerage_pct == 0.18    # 18% GST


def test_manifest_reproducibility_same_inputs_same_hash():
    """Same inputs must always produce the same manifest_hash (determinism)."""
    kwargs = dict(
        strategy_id="rsi_reversal_v1",
        strategy_name="RSI Reversal",
        strategy_version="1.0.0",
        universe=["NIFTY50"],
        data_snapshot_start="2023-01-01",
        data_snapshot_end="2024-01-01",
        parameters={"rsi_buy": 30, "rsi_sell": 70},
    )
    m1 = create_run_manifest(**kwargs)
    m2 = create_run_manifest(**kwargs)

    # UUIDs differ (each run is unique) but manifest_hash must match
    assert m1.run_id != m2.run_id
    assert m1.manifest_hash == m2.manifest_hash


# ── Options Chain Integrity Tests ───────────────────────────────────────────

def _sample_chain(n_strikes: int = 21, base_price: float = 22000.0) -> list[dict]:
    """Generate synthetic clean options chain rows around a spot price."""
    rows = []
    for i in range(-(n_strikes // 2), n_strikes // 2 + 1):
        strike = base_price + (i * 50)
        for opt_type in ("CE", "PE"):
            rows.append({
                "strike": strike,
                "option_type": opt_type,
                "bid": 100.0 + i * 5,
                "ask": 102.0 + i * 5,
                "iv_pct": 15.5 + abs(i) * 0.3,
                "oi": 50000 + i * 1000,
                "volume": 5000,
            })
    return rows


def test_clean_chain_is_actionable():
    """A fresh, well-formed chain with sufficient strikes must be ELIGIBLE."""
    chain = _sample_chain(n_strikes=25, base_price=22000.0)
    report = validate_options_chain(
        symbol="NIFTY",
        expiry="2027-09-25",
        underlying_price=22000.0,
        chain_rows=chain,
        chain_timestamp_utc=None,  # fresh
    )

    assert report.is_actionable is True
    assert report.action_eligibility == "ELIGIBLE"
    assert report.quality_score >= 70.0
    assert report.atm_strike == 22000.0


def test_stale_chain_blocks_execution():
    """A chain older than MAX_CHAIN_AGE_SECONDS must be UNAVAILABLE."""
    chain = _sample_chain(n_strikes=25, base_price=22000.0)
    report = validate_options_chain(
        symbol="BANKNIFTY",
        expiry="2027-09-25",
        underlying_price=48000.0,
        chain_rows=chain,
        chain_timestamp_utc="2020-01-01T00:00:00Z",  # artificially old
    )

    assert report.is_actionable is False
    assert report.action_eligibility in ("UNAVAILABLE", "RESTRICTED")
    assert any("STALE_CHAIN" in issue for issue in report.issues)


def test_insufficient_strikes_restricts_chain():
    """Chain with fewer than MIN_STRIKES_REQUIRED around ATM must be RESTRICTED/UNAVAILABLE."""
    sparse_chain = _sample_chain(n_strikes=7, base_price=22000.0)
    report = validate_options_chain(
        symbol="NIFTY",
        expiry="2027-09-25",
        underlying_price=22000.0,
        chain_rows=sparse_chain,
    )

    assert report.is_actionable is False
    assert any("INSUFFICIENT_STRIKES" in issue or "STRIKE" in issue for issue in report.issues)


def test_wide_spread_chain_flagged():
    """Options with excessively wide bid/ask spread must be flagged as invalid."""
    wide_chain = _sample_chain(n_strikes=25, base_price=22000.0)
    # Inflate ask massively to simulate wide spread
    for row in wide_chain:
        row["ask"] = row["bid"] * 3.0

    report = validate_options_chain(
        symbol="NIFTY",
        expiry="2027-09-25",
        underlying_price=22000.0,
        chain_rows=wide_chain,
    )

    assert report.flagged_strikes > 0
    assert report.valid_strikes < report.total_strikes_checked


def test_expired_chain_blocks_execution():
    """An expired option expiry date must block execution."""
    chain = _sample_chain(n_strikes=25, base_price=22000.0)
    report = validate_options_chain(
        symbol="NIFTY",
        expiry="2020-01-16",  # expired in the past
        underlying_price=22000.0,
        chain_rows=chain,
    )

    assert report.is_actionable is False
    assert any("EXPIRED" in issue for issue in report.issues)
