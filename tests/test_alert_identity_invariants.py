"""
tests/test_alert_identity_invariants.py
─────────────────────────────────────────
Institutional test suite verifying alert identity determinism, symbol normalization,
and static prevention of volatile ID anti-patterns across all detectors.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from engine.alert_identity import (
    canonical_alert_symbol,
    generate_alert_id,
    validate_alert_id,
)
from engine.alert_model import AutoAlert


def test_canonical_alert_symbol_prefixes():
    """Verify that canonical_alert_symbol uniformly cleans exchange prefixes."""
    assert canonical_alert_symbol("NSE:RELIANCE") == "RELIANCE"
    assert canonical_alert_symbol("BSE:TCS") == "TCS"
    assert canonical_alert_symbol("MCX:CRUDEOIL") == "CRUDEOIL"
    assert canonical_alert_symbol("NFO:NIFTY") == "NIFTY"
    assert canonical_alert_symbol("BFO:SENSEX") == "SENSEX"
    assert canonical_alert_symbol("CDS:USDINR") == "USDINR"
    assert canonical_alert_symbol("CRYPTO:BTCUSDT") == "BTCUSDT"
    assert canonical_alert_symbol("BINANCE:ETHUSDT") == "ETHUSDT"
    assert canonical_alert_symbol("DERIBIT:BTC-PERP") == "BTC-PERP"
    assert canonical_alert_symbol("RELIANCE.NS") == "RELIANCE"
    assert canonical_alert_symbol("TCS.BO") == "TCS"
    assert canonical_alert_symbol("^NSEI") == "NIFTY"
    assert canonical_alert_symbol("NSE:RELIANCE-EQ") == "RELIANCE"
    assert canonical_alert_symbol("NSE:NIFTY50-INDEX") == "NIFTY"
    assert canonical_alert_symbol("NSE:NIFTYBANK-INDEX") == "BANKNIFTY"
    assert canonical_alert_symbol("NSE:INDIAVIX-INDEX") == "INDIAVIX"
    assert canonical_alert_symbol("  nse:infy  ") == "INFY"
    assert canonical_alert_symbol("") == ""


def test_generate_alert_id_determinism():
    """Verify daily determinism and collision avoidance across variants."""
    d = date(2026, 9, 26)
    id1 = generate_alert_id("NSE:TATASTEEL", "ORB", session_date=d, variant="bull")
    id2 = generate_alert_id("TATASTEEL", "ORB", session_date=d, variant="bull")
    assert id1 == id2 == "aa-orb-tatasteel-bull-20260926"

    # Variant distinction
    id_bear = generate_alert_id("NSE:TATASTEEL", "ORB", session_date=d, variant="bear")
    assert id_bear == "aa-orb-tatasteel-bear-20260926"
    assert id1 != id_bear

    # Crypto slug
    id_crypto = generate_alert_id("CRYPTO:BTCUSDT", "CRYPTO_SQUEEZE", session_date=d)
    assert id_crypto == "aa-crypto-squeeze-btcusdt-20260926"

    # Options momentum with strike variant
    id_opt = generate_alert_id(
        "NSE:NIFTY",
        "OPTIONS_MOMENTUM",
        session_date=d,
        variant="ce-25000",
    )
    assert id_opt == "aa-options-momentum-nifty-ce-25000-20260926"


def test_validate_alert_id():
    """Verify validation against banned volatile patterns (timestamps and UUIDs)."""
    # Valid IDs
    is_valid, _ = validate_alert_id("aa-orb-reliance-bull-20260926")
    assert is_valid is True

    is_valid, _ = validate_alert_id("aa-options-momentum-nifty-ce-25000-20260926")
    assert is_valid is True

    # Invalid: Too short
    is_valid, reason = validate_alert_id("aa-rel")
    assert is_valid is False
    assert "too short" in reason

    # Invalid: Minute-level timestamp (12 digits)
    is_valid, reason = validate_alert_id("aa-orb-reliance-202609261230")
    assert is_valid is False
    assert "banned minute-level timestamp" in reason

    # Invalid: Random UUID suffix
    is_valid, reason = validate_alert_id("aa-orb-reliance-a1b2c3")
    assert is_valid is False
    assert "random UUID" in reason


def test_auto_alert_model_invariants():
    """Verify AutoAlert model properties and invariants."""
    alert = AutoAlert(
        alert_id="aa-test-promo-20260926",
        alert_type="INTRADAY_SPARK",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        stage="EARLY_WARNING",
        trigger_level=1500.0,
        ltp=1500.5,
        stop_loss=1480.0,
        target_level=1540.0,
        headline="Test promo",
        summary="Test promo summary",
        environment="TEST",
    )
    assert alert.stage == "EARLY_WARNING"
    # Verify is_active setter updates is_archived without AttributeError
    assert alert.is_archived is False
    alert.is_active = False
    assert alert.is_archived is True
    alert.is_active = True
    assert alert.is_archived is False


def test_all_detectors_use_canonical_identity():
    """
    Static code invariant: Parse all detector files in engine/detectors/
    to assert that NO detector uses volatile strftime timestamps or random UUIDs for alert IDs.
    """
    detectors_dir = Path(__file__).resolve().parent.parent / "engine" / "detectors"
    py_files = list(detectors_dir.glob("*.py"))
    assert len(py_files) > 0, "No detector files found"

    banned_substrings = [
        "%Y%m%d%H%M",
        "%Y%m%d_%H%M",
        "uuid.uuid4().hex[:6]",
        "uuid.uuid4().hex[:8]",
        'symbol=f"{exchange}:',
        "symbol=f'{exchange}:",
    ]

    violations = []
    for f in py_files:
        content = f.read_text(encoding="utf-8")
        for banned in banned_substrings:
            if banned in content:
                violations.append(f"{f.name}: contains banned pattern '{banned}'")

    assert not violations, "Banned alert identity patterns detected in detectors:\n" + "\n".join(
        violations
    )


def test_auto_alert_post_init_canonicalizes_symbol():
    """Verify AutoAlert.__post_init__ automatically normalizes symbols with exchange prefixes."""
    alert = AutoAlert(
        alert_id="aa-test-prefix-01",
        alert_type="PREDATOR_SWEEP",
        stage="IGNITED",
        symbol="NSE:LT",
        exchange="NSE",
        direction="BULLISH",
        headline="LT Predator Sweep",
        summary="Testing prefix cleanup",
        ltp=3600.0,
        trigger_level=3600.0,
        target_level=3700.0,
        stop_loss=3550.0,
    )
    assert alert.symbol == "LT"


def test_auto_alert_market_status_resolution():
    """Verify AutoAlert automatically resolves market_status for LIVE environment."""
    from unittest.mock import patch

    # 1. LIVE alert during open market -> market_status="LIVE"
    with patch("market.calendar.is_market_open", return_value=True):
        alert_live = AutoAlert(
            alert_id="aa-test-live-20260926",
            alert_type="INDEX_MICRO_SCALP",
            stage="IGNITED",
            symbol="BANKNIFTY",
            exchange="NFO",
            direction="BULLISH",
            trigger_level=55000.0,
            ltp=55000.0,
            stop_loss=54800.0,
            target_level=55400.0,
            headline="Test live",
            summary="Test summary",
            environment="LIVE",
        )
        assert alert_live.market_status == "LIVE"

    # 2. EOD_SCAN alert -> market_status="SESSION_CLOSED"
    alert_eod = AutoAlert(
        alert_id="aa-test-eod-20260926",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="STALK",
        symbol="ZYDUSLIFE",
        exchange="NSE",
        direction="BULLISH",
        trigger_level=1000.0,
        ltp=1000.0,
        stop_loss=980.0,
        target_level=1050.0,
        headline="Test eod",
        summary="Test summary",
        environment="EOD_SCAN",
    )
    assert alert_eod.market_status == "SESSION_CLOSED"


def test_scale_isolation_in_fno_enrichment():
    """Verify that _enrich_fno_contract_if_applicable isolates option premiums in option_plan without overwriting spot coordinates."""
    from unittest.mock import MagicMock, patch
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="aa-orb-breakdown-abb-bear-20261023",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="ABB",
        exchange="NSE",
        direction="BEARISH",
        ltp=6152.0,
        trigger_level=6150.0,
        stop_loss=6212.0,
        target_level=6050.0,
        headline="ABB Breakdown",
        summary="Bearish breakdown",
        actionable_plan={
            "action": "SELL_SHORT_OR_BUY_PUT",
            "stop_loss": "₹6,212.00",
            "target_1": "₹6,050.00",
            "target_2": "₹5,950.00",
            "no_chase_boundary": "₹6,120.00",
        },
    )

    mock_opt_plan = MagicMock()
    mock_opt_plan.contract_symbol = "NSE:ABB26OCT6200PE"
    mock_opt_plan.strike = 6200.0
    mock_opt_plan.expiry = "2026-10-29"
    mock_opt_plan.entry_premium = 139.55
    mock_opt_plan.sl_premium = 112.48
    mock_opt_plan.t1_premium = 168.0
    mock_opt_plan.t2_premium = 198.16
    mock_opt_plan.lot_size = 125
    mock_opt_plan.as_dict.return_value = {
        "contract_symbol": "NSE:ABB26OCT6200PE",
        "entry_premium": 139.55,
        "sl_premium": 112.48,
        "t1_premium": 168.0,
        "t2_premium": 198.16,
    }

    with patch("engine.option_resolver.resolve_option_contract", return_value=mock_opt_plan):
        engine._enrich_fno_contract_if_applicable(alert)

    # Invariant: Underlying spot coordinates preserved in underlying_sl and underlying_target
    assert alert.actionable_plan["underlying_sl"] == "₹6,212.00"
    assert alert.actionable_plan["underlying_target"] == "₹6,050.00"
    assert alert.actionable_plan["spot_invalidation_anchor"] == "₹6,212.00"
    # Actionable ticket adapted to option premium space
    assert alert.actionable_plan["stop_loss"] == "₹112.48"
    assert alert.actionable_plan["target_1"] == "₹168.00"

    # Invariant: Option premiums MUST be isolated in dedicated keys
    assert alert.actionable_plan["option_entry"] == "₹139.55"
    assert alert.actionable_plan["option_sl"] == "₹112.48"
    assert alert.actionable_plan["option_target_2"] == "₹198.16"
    assert "option_plan" in alert.actionable_plan
    assert alert.actionable_plan["option_plan"]["sl_premium"] == 112.48


def test_tri_directional_symmetry_in_target_properties():
    """Verify that target_1 and target_2 properties never return sub-scale option premiums for BEARISH or BULLISH spot setups."""
    # Spot stock alert with contaminated option target_2 in plan
    alert_bear = AutoAlert(
        alert_id="aa-test-bear-scale-01",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="ABB",
        exchange="NSE",
        direction="BEARISH",
        ltp=6152.0,
        trigger_level=6150.0,
        stop_loss=6212.0,
        target_level=6050.0,
        headline="ABB Breakdown",
        summary="Test",
        actionable_plan={
            "stop_loss": "₹6,212.00",
            "target_1": "₹6,050.00",
            "target_2": 198.16,  # Corrupted option premium
            "trade_plan": {
                "target_1": 6050.0,
                "target_2": 5950.0,  # Legitimate spot target_2
            },
        },
    )
    # The property MUST reject 198.16 (< 40% of spot 6152) and return genuine spot target
    assert alert_bear.target_2 == 5950.0
    assert alert_bear.target_2 != 198.16


def test_alert_evaluator_suppresses_scale_mismatch():
    """Verify that evaluate_alert_in_flight_decay suppresses evaluation when LTP and SL have > 50% scale mismatch."""
    from engine.alert_evaluator import evaluate_alert_in_flight_decay

    alert = AutoAlert(
        alert_id="aa-test-mismatch-01",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="ABB",
        exchange="NSE",
        direction="BEARISH",
        ltp=6152.0,
        trigger_level=6150.0,
        stop_loss=112.48,  # Option premium stop on a 6000 stock!
        target_level=6050.0,
        headline="Scale Mismatch Test",
        summary="Test",
        environment="TEST",
    )
    # Evaluation must return None instead of triggering a false 99% Danger Zone
    res = evaluate_alert_in_flight_decay(alert, current_ltp=6150.0)
    assert res is None


def test_option_resolver_rejects_illiquid_spreads():
    """Verify that resolve_option_contract rejects strikes with > 8% bid-ask spread on cash equity setups."""
    from unittest.mock import MagicMock, patch
    from engine.option_resolver import resolve_option_contract

    mock_contract = MagicMock()
    mock_contract.option_type = "PE"
    mock_contract.strike = 3000.0
    mock_contract.last_price = 10.0
    mock_contract.bid = 5.0
    mock_contract.ask = 35.0  # (35 - 5) / 10 = 300% spread!
    mock_contract.symbol = "NSE:KAYNES26OCT3000PE"

    mock_chain = MagicMock()
    mock_chain.contracts = [mock_contract]

    with patch("market.options.get_options_chain", return_value=mock_chain):
        res = resolve_option_contract(
            symbol="KAYNES",
            spot=3000.0,
            direction="BEARISH",
            prefer_options=False,  # Standard cash equity setup
        )
        # Must discard predatory illiquid option and return None for clean spot execution
        assert res is None
