"""
tests/test_smt_divergence.py
────────────────────────────
Unit & integration tests for Smart Money Technique (SMT) Inter-Index Divergence
and Non-Confirmation Engine.
"""

from engine.smt_divergence import evaluate_smt_divergence, get_sibling_index, SMTDivergenceResult
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import alert_scrutiny_auditor


def test_sibling_index_mapping():
    assert get_sibling_index("NIFTY") == "BANKNIFTY"
    assert get_sibling_index("BANKNIFTY") == "NIFTY"
    assert get_sibling_index("FINNIFTY") == "BANKNIFTY"
    assert get_sibling_index("MIDCPNIFTY") == "NIFTY"
    assert get_sibling_index("SENSEX") == "NIFTY"


def test_smt_bearish_divergence_bull_trap(monkeypatch):
    """
    NIFTY tests day high (25,000), but BANKNIFTY is trapped below VWAP (51,500 vs VWAP 51,800).
    Must trigger SMT Bearish Divergence (Judas swing bull trap veto).
    """
    mock_quotes = {
        "BANKNIFTY": {
            "ltp": 51500.0,
            "vwap": 51800.0,
            "high": 52100.0,
            "low": 51400.0,
        }
    }

    res = evaluate_smt_divergence(
        primary_symbol="NIFTY",
        direction="BULLISH",
        primary_spot=25000.0,
        primary_day_high=25005.0,
        primary_day_low=24800.0,
        primary_vwap=24900.0,
        quotes_map=mock_quotes,
    )

    assert res.has_divergence is True
    assert res.is_trap is True
    assert res.divergence_type == "BEARISH_DIVERGENCE_BULL_TRAP"
    assert "trapped below VWAP" in res.rationale
    assert "Judas swing" in res.rationale


def test_smt_bullish_divergence_bear_trap(monkeypatch):
    """
    NIFTY breaks down to day low (24,800), but BANKNIFTY is holding above VWAP (52,000 vs VWAP 51,800).
    Must trigger SMT Bullish Divergence (bear trap stop hunt veto).
    """
    mock_quotes = {
        "BANKNIFTY": {
            "ltp": 52000.0,
            "vwap": 51800.0,
            "high": 52200.0,
            "low": 51750.0,
        }
    }

    res = evaluate_smt_divergence(
        primary_symbol="NIFTY",
        direction="BEARISH",
        primary_spot=24800.0,
        primary_day_high=25050.0,
        primary_day_low=24805.0,
        primary_vwap=24950.0,
        quotes_map=mock_quotes,
    )

    assert res.has_divergence is True
    assert res.is_trap is True
    assert res.divergence_type == "BULLISH_DIVERGENCE_BEAR_TRAP"
    assert "holding above VWAP" in res.rationale
    assert "bear trap" in res.rationale


def test_smt_confirmed_harmony(monkeypatch):
    """
    Both NIFTY and BANKNIFTY are trading above VWAP and testing highs.
    Must confirm inter-market harmony (no trap).
    """
    mock_quotes = {
        "BANKNIFTY": {
            "ltp": 52180.0,
            "vwap": 51800.0,
            "high": 52200.0,
            "low": 51700.0,
        }
    }

    res = evaluate_smt_divergence(
        primary_symbol="NIFTY",
        direction="BULLISH",
        primary_spot=25000.0,
        primary_day_high=25005.0,
        primary_day_low=24800.0,
        primary_vwap=24900.0,
        quotes_map=mock_quotes,
    )

    assert res.has_divergence is False
    assert res.is_trap is False
    assert res.divergence_type == "CONFIRMED_HARMONY"


def test_tier2_scrutiny_smt_divergence_gate(monkeypatch):
    """
    Verify that AlertScrutinyAuditor vetoes an index breakout setup when SMT divergence is active.
    """
    mock_smt = SMTDivergenceResult(
        has_divergence=True,
        divergence_type="BEARISH_DIVERGENCE_BULL_TRAP",
        sibling_symbol="BANKNIFTY",
        primary_symbol="NIFTY",
        is_trap=True,
        rationale="SMT Bearish Divergence Veto: BANKNIFTY trapped below VWAP.",
    )

    monkeypatch.setattr(
        "engine.smt_divergence.evaluate_smt_divergence",
        lambda *args, **kwargs: mock_smt,
    )

    alert = AutoAlert(
        alert_id="test-smt-veto",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Squeeze Breakout",
        summary="Test breakout",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25150.0,
        stop_loss=24920.0,
        metrics={
            "spot": 25000.0,
            "vwap": 24950.0,
            "day_high": 25000.0,
            "day_low": 24800.0,
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags.get("smt_divergence_trap") is True
    assert "SMT Bearish Divergence" in reason


def test_smt_locomotive_polarization_bear_trap():
    """
    NIFTY is trading below VWAP (24,900 vs 24,950), but 34%-weighted locomotive BANKNIFTY
    is holding above VWAP (52,000 vs 51,800).
    Must trigger SMT Locomotive Polarization (bear trap veto).
    """
    mock_quotes = {
        "BANKNIFTY": {
            "ltp": 52000.0,
            "vwap": 51800.0,
            "high": 52200.0,
            "low": 51750.0,
        }
    }

    res = evaluate_smt_divergence(
        primary_symbol="NIFTY",
        direction="BEARISH",
        primary_spot=24900.0,
        primary_day_high=25050.0,
        primary_day_low=24700.0,  # Spot 24,900 is >0.35% from Day Low 24,700
        primary_vwap=24950.0,
        quotes_map=mock_quotes,
    )

    assert res.has_divergence is True
    assert res.is_trap is True
    assert res.divergence_type == "LOCOMOTIVE_POLARIZATION_BEAR_TRAP"
    assert "firmly holding above VWAP" in res.rationale
    assert "bear trap" in res.rationale


def test_smt_locomotive_polarization_bull_trap():
    """
    NIFTY is trading above VWAP (25,000 vs 24,950), but BANKNIFTY is trapped below VWAP (51,500 vs 51,800).
    Must trigger SMT Locomotive Polarization (bull trap veto).
    """
    mock_quotes = {
        "BANKNIFTY": {
            "ltp": 51500.0,
            "vwap": 51800.0,
            "high": 52200.0,
            "low": 51400.0,
        }
    }

    res = evaluate_smt_divergence(
        primary_symbol="NIFTY",
        direction="BULLISH",
        primary_spot=25000.0,
        primary_day_high=25200.0,  # Spot 25,000 is >0.35% from Day High 25,200
        primary_day_low=24800.0,
        primary_vwap=24950.0,
        quotes_map=mock_quotes,
    )

    assert res.has_divergence is True
    assert res.is_trap is True
    assert res.divergence_type == "LOCOMOTIVE_POLARIZATION_BULL_TRAP"
    assert "trapped below VWAP" in res.rationale


def test_dynamic_index_min_sl_floor_scaling():
    """Verify that get_dynamic_index_min_sl_floor scales with India VIX regime."""
    from engine.alert_scrutiny import get_dynamic_index_min_sl_floor

    # Normal VIX (15.0) -> baseline
    assert get_dynamic_index_min_sl_floor("BANKNIFTY", vix=15.0) == 65.0
    assert get_dynamic_index_min_sl_floor("NIFTY", vix=15.0) == 25.0

    # High VIX (24.0) -> expands by ~sqrt(24/15) = 1.265x
    high_floor = get_dynamic_index_min_sl_floor("BANKNIFTY", vix=24.0)
    assert high_floor > 80.0, f"Expected >80.0, got {high_floor}"

    # Low VIX (10.0) -> contracts by ~sqrt(10/15) = 0.816x
    low_floor = get_dynamic_index_min_sl_floor("BANKNIFTY", vix=10.0)
    assert low_floor < 55.0, f"Expected <55.0, got {low_floor}"


def test_tier1_sanity_rejects_sub_noise_spot_anchor():
    """Verify that alert scrutiny rejects index options with spot anchors placed inside candle noise."""
    alert = AutoAlert(
        alert_id="test-spot-anchor-sub-noise",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="BankNifty Call",
        summary="Test",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=120.0,  # 30 pt option risk
        underlying_spot=53850.0,
        structural_spot_sl=53845.0,  # Only 5 pts below spot on BankNifty! Inside noise!
        metrics={
            "spot": 53850.0,
            "spot_invalidation_anchor": 53845.0,
            "india_vix": 15.0,
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert flags.get("risk_within_bounds") is False
    assert "Sub-Noise Spot Trap" in reason
