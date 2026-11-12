"""
tests/test_indicator_snapshot.py
─────────────────────────────────
Unit and integration tests for the Canonical Indicator Snapshot Engine,
Index Futures Snapshot, and Intraday MarketMatrix Bootstrap.

Validates:
  - Strict provenance tagging across all indicator fields (AGENTS.md Invariants 10, 11)
  - Fail-closed behavior on missing or unresolvable symbols
  - Zero fabricated or hardcoded numbers
  - Integration with 3Cs hierarchical market context evaluator
"""

from __future__ import annotations

from engine.indicator_snapshot import (
    PROVENANCE_COMPUTED_ESTIMATE,
    PROVENANCE_DEGRADED_CACHED,
    PROVENANCE_REAL_LIVE,
    PROVENANCE_UNAVAILABLE,
    FieldValue,
    IndicatorSnapshot,
    bootstrap_market_matrix_for_symbol,
    get_indicator_snapshot,
    invalidate_snapshot_cache,
)
from market.indices import get_index_futures_snapshot


class TestIndicatorSnapshot:
    """Test suite for IndicatorSnapshot dataclass and builder."""

    def setup_method(self) -> None:
        invalidate_snapshot_cache()

    def test_field_value_provenance_constants(self) -> None:
        """Ensure all valid provenance tags are recognized."""
        fv_live = FieldValue(100.0, PROVENANCE_REAL_LIVE, "fyers_ws")
        assert fv_live.provenance == "REAL_LIVE"
        assert fv_live.value == 100.0

        fv_unavail = FieldValue(None, PROVENANCE_UNAVAILABLE, "")
        assert fv_unavail.provenance == "UNAVAILABLE"
        assert fv_unavail.value is None

        d = fv_live.to_dict()
        assert d["value"] == 100.0
        assert d["provenance"] == "REAL_LIVE"
        assert d["source"] == "fyers_ws"

    def test_indicator_snapshot_nifty_structure(self) -> None:
        """Tests that NIFTY snapshot produces all required fields with explicit provenance."""
        snap = get_indicator_snapshot("NIFTY", exchange="NSE", force_refresh=True)

        assert isinstance(snap, IndicatorSnapshot)
        assert snap.symbol == "NIFTY"
        assert snap.exchange == "NSE"

        # Verify all required quantitative fields exist as FieldValue objects
        expected_fields = [
            "cmp",
            "atr_daily",
            "atr_5m",
            "adx_14",
            "roc_3bar",
            "chop_index",
            "vix",
            "pdh",
            "pdl",
            "pdc",
            "cpr_pivot",
            "cpr_top",
            "cpr_bottom",
            "adr_exhaustion_pct",
            "atm_iv",
            "atm_delta",
            "atm_gamma",
            "atm_theta",
            "atm_vega",
            "futures_ltp",
            "futures_volume",
            "futures_oi",
            "futures_basis",
        ]
        valid_provenance = {
            PROVENANCE_REAL_LIVE,
            PROVENANCE_DEGRADED_CACHED,
            PROVENANCE_COMPUTED_ESTIMATE,
            PROVENANCE_UNAVAILABLE,
        }

        for f_name in expected_fields:
            field_obj = getattr(snap, f_name)
            assert isinstance(field_obj, FieldValue), (
                f"Field {f_name} must be a FieldValue instance"
            )
            assert field_obj.provenance in valid_provenance, (
                f"Field {f_name} has invalid provenance: {field_obj.provenance}"
            )
            # Invariant: If provenance is UNAVAILABLE, value must be None
            if field_obj.provenance == PROVENANCE_UNAVAILABLE:
                assert field_obj.value is None, (
                    f"Field {f_name} marked UNAVAILABLE but has non-None value {field_obj.value}"
                )

        # Flat dict conversion
        flat = snap.to_flat_dict()
        assert flat["symbol"] == "NIFTY"
        assert "provenance" in flat
        assert isinstance(flat["provenance"], dict)
        assert "cmp" in flat["provenance"]
        assert "atr_daily" in flat["provenance"]

    def test_atm_greeks_derivation_fallback(self) -> None:
        """Verifies that when Greeks are derived from Black-Scholes, they carry valid numbers or explicit UNAVAILABLE."""
        snap = get_indicator_snapshot("NIFTY", exchange="NSE", force_refresh=True)
        # If Greeks are populated, they must be mathematically valid:
        # Delta for CE in [0.0, 1.0], Gamma >= 0.0, IV > 0.0
        if snap.atm_delta.value is not None:
            assert 0.0 <= snap.atm_delta.value <= 1.0, (
                f"CE Delta must be in [0, 1], got {snap.atm_delta.value}"
            )
            assert snap.atm_delta.provenance in (PROVENANCE_REAL_LIVE, PROVENANCE_COMPUTED_ESTIMATE)
        if snap.atm_gamma.value is not None:
            assert snap.atm_gamma.value >= 0.0, f"Gamma must be >= 0, got {snap.atm_gamma.value}"
        if snap.atm_iv.value is not None:
            assert snap.atm_iv.value > 0.0, f"IV must be > 0, got {snap.atm_iv.value}"

    def test_indicator_snapshot_fail_closed_unknown_symbol(self) -> None:
        """When an unknown symbol is provided, all fields fail closed with UNAVAILABLE."""
        snap = get_indicator_snapshot("UNKNOWN_SYMBOL_XYZ_99", exchange="NSE", force_refresh=True)
        assert snap.symbol == "UNKNOWN_SYMBOL_XYZ_99"
        assert snap.overall_status in ("UNAVAILABLE", "DEGRADED")
        assert snap.cmp.provenance == PROVENANCE_UNAVAILABLE
        assert snap.cmp.value is None

    def test_cpr_regime_validity(self) -> None:
        """CPR regime must be one of the known institutional classifications."""
        snap = get_indicator_snapshot("NIFTY", exchange="NSE", force_refresh=True)
        valid_cpr_regimes = {
            "NARROW_CPR (Trend Day Expected)",
            "WIDE_CPR (Range/Chop Expected)",
            "AVERAGE_CPR",
            "NARROW_CPR",
            "WIDE_CPR",
            "UNKNOWN",
        }
        assert snap.cpr_regime in valid_cpr_regimes or "CPR" in snap.cpr_regime, (
            f"Unexpected CPR regime: {snap.cpr_regime}"
        )


class TestIndexFuturesSnapshot:
    """Test suite for get_index_futures_snapshot."""

    def test_nifty_futures_snapshot(self) -> None:
        """NIFTY futures snapshot returns valid contract and status."""
        fut = get_index_futures_snapshot("NIFTY")
        assert isinstance(fut, dict)
        assert "status" in fut
        assert "provenance" in fut
        assert "contract" in fut
        assert "basis" in fut
        assert fut["status"] in ("REAL_LIVE", "DEGRADED_CACHED", "UNAVAILABLE")

    def test_banknifty_futures_snapshot(self) -> None:
        """BANKNIFTY futures snapshot returns valid contract and status."""
        fut = get_index_futures_snapshot("BANKNIFTY")
        assert isinstance(fut, dict)
        assert fut["status"] in ("REAL_LIVE", "DEGRADED_CACHED", "UNAVAILABLE")

    def test_unknown_index_futures_fail_closed(self) -> None:
        """Unknown index fails closed with status=UNAVAILABLE."""
        fut = get_index_futures_snapshot("INVALID_INDEX_99")
        assert fut["status"] == "UNAVAILABLE"
        assert fut["provenance"] == "UNAVAILABLE"


class TestMarketMatrixBootstrap:
    """Test suite for MarketMatrix cold-start bootstrap."""

    def test_bootstrap_index_symbol(self) -> None:
        """Bootstrapping NIFTY does not raise and handles warm/cold state safely."""
        res = bootstrap_market_matrix_for_symbol("NIFTY", min_bars=5)
        # Result can be True (bootstrapped) or False (already warm or skipped in test)
        assert isinstance(res, bool)


class TestHierarchicalEngineC3Enrichment:
    """Test suite verifying C3 Market Context incorporates indicator snapshot."""

    def test_c3_populates_atr_and_cpr(self) -> None:
        """Hierarchical engine evaluate_market_context_3cs populates C3 ATR and CPR."""
        from engine.pipeline.hierarchical_engine import hierarchical_pipeline

        ctx = hierarchical_pipeline.evaluate_market_context_3cs("NIFTY", exchange="NSE")
        assert ctx is not None
        assert hasattr(ctx, "atr_val")
        assert hasattr(ctx, "cpr_regime")
        assert hasattr(ctx, "vix_val")
        # Invariant: atr_val must be non-negative float
        assert isinstance(ctx.atr_val, float)
        assert ctx.atr_val >= 0.0
        # CPR regime must not be blank
        assert len(ctx.cpr_regime) > 0
