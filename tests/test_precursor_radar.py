"""
tests/test_precursor_radar.py
─────────────────────────────
Unit tests for the Precursor Radar Scanner.
Tests orthogonal conviction scoring, VWAP knife-catching penalty, lockout gating, and trade plans.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from engine.precursor_radar import PrecursorRadarScanner


@pytest.fixture
def scanner():
    return PrecursorRadarScanner()


def test_evaluate_symbol_high_conviction(scanner):
    """Test that a stock with severe volume dry-up, TTM squeeze, order block anchor, and leading sector qualifies as HIGH CONVICTION."""
    # Synthetic Quote
    mock_quote = MagicMock()
    mock_quote.ltp = 3000.0
    mock_quote.volume = 1500000
    mock_quote.vwap = 2990.0  # LTP > VWAP -> passes knife-catching check

    # Synthetic Daily OHLCV with dry-up and squeeze
    dates = pd.date_range("2026-08-01", periods=25, freq="B")
    df = pd.DataFrame(
        {
            "open": np.linspace(2900, 3000, 25),
            "high": np.linspace(2920, 3010, 25),
            "low": np.linspace(2880, 2980, 25),
            "close": np.linspace(2900, 3000, 25),
            "volume": [1000000] * 23 + [180000, 1500000],  # Penultimate day volume is 18% of avg
        },
        index=dates,
    )

    mock_squeeze = MagicMock()
    mock_squeeze.is_squeeze_on = True
    mock_squeeze.squeeze_fired = False
    mock_squeeze.squeeze_duration_bars = 4

    with (
        patch("market.quotes.get_quote", return_value=mock_quote),
        patch("market.history.get_ohlcv", return_value=df),
        patch("analysis.big_move.compute_ttm_squeeze", return_value=mock_squeeze),
        patch(
            "analysis.sector_rotation.get_stock_sector_alignment",
            return_value={"sector_name": "IT", "quadrant": "LEADING"},
        ),
        patch("market.options.get_options_chain", return_value=None),
        patch(
            "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
            return_value=(False, ""),
        ),
    ):
        cand = scanner.evaluate_symbol("INFY", df=df)

        assert cand is not None
        assert cand.symbol == "INFY"
        assert cand.conviction_score >= 75
        assert cand.verdict in ("HIGH_CONVICTION", "MAX_CONVICTION")
        assert cand.stop_loss < cand.ltp
        assert cand.target_1 > cand.ltp
        assert "DO NOT CHASE" in cand.when_to_wait
        assert len(cand.matched_factors) >= 2


def test_evaluate_symbol_vwap_knife_catching_penalty(scanner):
    """Test that a stock trading below its intraday VWAP receives a 25-point penalty and gets rejected or demoted."""
    mock_quote = MagicMock()
    mock_quote.ltp = 2950.0
    mock_quote.volume = 1000000
    mock_quote.vwap = 2990.0  # LTP is below VWAP!

    df = pd.DataFrame(
        {
            "open": [2950] * 25,
            "high": [2970] * 25,
            "low": [2930] * 25,
            "close": [2950] * 25,
            "volume": [1000000] * 25,
        }
    )

    with (
        patch("market.quotes.get_quote", return_value=mock_quote),
        patch("market.history.get_ohlcv", return_value=df),
        patch("market.options.get_options_chain", return_value=None),
        patch(
            "analysis.sector_rotation.get_stock_sector_alignment",
            return_value={"sector_name": "IT", "quadrant": "LAGGING"},
        ),
        patch(
            "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
            return_value=(False, ""),
        ),
    ):
        cand = scanner.evaluate_symbol("INFY", df=df)
        # Because of the below-VWAP penalty, score should drop below threshold (75) and return None
        assert cand is None


def test_evaluate_symbol_lockout_gate(scanner):
    """Test that a symbol on active post-mortem invalidation lockout is immediately blocked."""
    with patch(
        "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
        return_value=(True, "Stop-loss breach cooldown"),
    ):
        cand = scanner.evaluate_symbol("ADANIENT")
        assert cand is None


def test_classify_symbol_segment():
    """Verify accurate multi-universe taxonomy classification across Indices, F&O, and Cash equities."""
    from engine.precursor_radar import classify_symbol_segment

    assert classify_symbol_segment("NIFTY 50") == "INDEX"
    assert classify_symbol_segment("BANKNIFTY") == "INDEX"
    assert classify_symbol_segment("^NSEI") == "INDEX"
    assert classify_symbol_segment("NIFTY IT") == "INDEX"

    assert classify_symbol_segment("RELIANCE") == "FNO"
    assert classify_symbol_segment("TATAMOTORS") == "FNO"
    assert classify_symbol_segment("HDFCBANK") == "FNO"

    assert classify_symbol_segment("SWANENERGY") == "NON_FNO"
    assert classify_symbol_segment("ZENTEC") == "NON_FNO"
    assert classify_symbol_segment("MEDANTA") == "NON_FNO"

    assert classify_symbol_segment("BTC") == "CRYPTO"
    assert classify_symbol_segment("CRYPTO:ETHUSDT") == "CRYPTO"
    assert classify_symbol_segment("SOL") == "CRYPTO"
    assert classify_symbol_segment("MCX:CRUDEOIL") == "COMMODITY"


def test_get_scan_universe_segments():
    """Verify segment-filtered scan universes."""
    from engine.precursor_radar import get_scan_universe, classify_symbol_segment

    fno_univ = get_scan_universe(segment="FNO")
    assert "RELIANCE" in fno_univ
    assert "NIFTY 50" not in fno_univ
    assert len(fno_univ) >= 20

    cash_univ = get_scan_universe(segment="NON_FNO")
    assert "ARE&M" in cash_univ or "KALYANKJIL" in cash_univ or "SUZLON" in cash_univ
    assert "RELIANCE" not in cash_univ

    index_univ = get_scan_universe(segment="INDEX")
    assert "NIFTY 50" in index_univ
    assert "BANKNIFTY" in index_univ
    assert "RELIANCE" not in index_univ

    crypto_univ = get_scan_universe(segment="CRYPTO")
    assert "BTC" in crypto_univ
    assert "ETH" in crypto_univ
    assert "SOL" in crypto_univ

    comm_univ = get_scan_universe(segment="COMMODITY")
    assert "CRUDEOIL" in comm_univ
    assert "GOLD" in comm_univ

    all_univ = get_scan_universe(segment=None)
    assert any(classify_symbol_segment(s) == "INDEX" for s in all_univ)
    assert any(classify_symbol_segment(s) == "FNO" for s in all_univ)
    assert any(classify_symbol_segment(s) == "NON_FNO" for s in all_univ)
    assert any(classify_symbol_segment(s) == "CRYPTO" for s in all_univ)
    assert any(classify_symbol_segment(s) == "COMMODITY" for s in all_univ)


def test_precursor_radar_internal_sla_timeout_and_graceful_completion(scanner):
    """
    RCA Regression:
    Ensure scan_precursors obeys timeout_sec and returns whatever candidates completed
    without blocking in executor.shutdown or stalling the master scan cycle.
    """
    import time

    def slow_evaluate(sym, quote=None):
        time.sleep(0.5)
        return None

    with patch.object(scanner, "evaluate_symbol", side_effect=slow_evaluate):
        t0 = time.time()
        # Scan 20 symbols with tight 0.3s timeout
        candidates = scanner.scan_precursors(
            universe=[f"SYM{i}" for i in range(20)],
            timeout_sec=0.3,
            force_refresh=True,
        )
        elapsed = time.time() - t0
        # Elapsed must be close to timeout (bounded under 3.0s), never hanging for 20 * 0.5s = 10s
        assert elapsed < 3.0, (
            f"scan_precursors blocked for {elapsed:.2f}s instead of adhering to SLA timeout"
        )
        assert isinstance(candidates, list)


def test_precursor_radar_uses_passed_quotes_map(scanner):
    """Verify that passing pre-fetched quotes_map eliminates redundant get_quote network calls."""
    mock_q = MagicMock(last_price=2500.0, ltp=2500.0, volume=100000, vwap=2490.0)
    quotes_map = {"NSE:TESTSTOCK": mock_q, "TESTSTOCK": mock_q}

    with (
        patch("market.quotes.get_quote") as mock_get_quote,
        patch.object(scanner, "evaluate_symbol", return_value=None) as mock_eval,
    ):
        scanner.scan_precursors(
            universe=["TESTSTOCK"],
            quotes_map=quotes_map,
            force_refresh=True,
        )
        mock_get_quote.assert_not_called()
        assert mock_eval.call_count == 1
        assert mock_eval.call_args.args[0] == "TESTSTOCK"
        assert mock_eval.call_args.kwargs.get("quote") == mock_q


def test_commodity_adaptive_regime_callable_ref_time_guard():
    """
    RCA Regression for: 'function' object has no attribute 'strftime'
    Verify evaluate_commodity_adaptive_regime safely resolves callable ref_time
    (e.g., now_ist imported as a function from config.constants) without crashing.
    """
    from datetime import datetime
    from config.constants import IST
    from engine.commodity_adaptive_regime import evaluate_commodity_adaptive_regime

    def fake_now_ist_fn():
        return datetime(2026, 11, 4, 10, 30, tzinfo=IST)

    # Pass the function itself (uncalled) as ref_time
    decision = evaluate_commodity_adaptive_regime(
        symbol="CRUDEOIL",
        spot=6200.0,
        ref_time=fake_now_ist_fn,  # callable function
    )
    assert decision is not None
    assert "2026-11-04 10:30:00 IST" in decision.evaluated_at
