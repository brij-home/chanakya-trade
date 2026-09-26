"""
tests/test_alert_identity_invariants.py
─────────────────────────────────────────
Institutional test suite verifying alert identity determinism, symbol normalization,
and static prevention of volatile ID anti-patterns across all detectors.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
import pytest

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
    ]

    violations = []
    for f in py_files:
        content = f.read_text(encoding="utf-8")
        for banned in banned_substrings:
            if banned in content:
                violations.append(f"{f.name}: contains banned pattern '{banned}'")

    assert not violations, f"Banned alert identity patterns detected in detectors:\n" + "\n".join(violations)
