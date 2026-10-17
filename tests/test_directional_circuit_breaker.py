"""
tests/test_directional_circuit_breaker.py
────────────────────────────────────────
Institutional invariant tests for:
1. In-Flight Index Thesis Shield (Zero strike-stacking: exactly one active thesis per index underlying).
2. Consecutive Directional Failure Circuit Breaker (Lockout after >=2 consecutive failures).
3. Dynamic Reversal Flip Override (Allow BULLISH setups when prior BEARISH setup failed on structural bounce).
4. Benchmark Decoupling vs Session Low Bounce Guard.
"""

import time
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def clean_engine(tmp_path, monkeypatch):
    """Creates an isolated AutoAlertEngine instance with temporary persistence."""
    from engine.alert_scrutiny import alert_scrutiny_auditor

    monkeypatch.setattr(alert_scrutiny_auditor, "verify_tier1_sanity", lambda a: (True, "", {}))
    data_file = tmp_path / "test_auto_alerts.json"
    engine = AutoAlertEngine()
    engine._data_file = data_file
    engine.clear_alerts()
    return engine


def _make_index_alert(
    symbol: str,
    direction: str,
    strike: float,
    option_type: str,
    alert_type: str = "INDEX_PUT_SETUP",
    alert_id: str = "test-1",
    entry_p: float = 100.0,
    sl: float = 85.0,
    underlying_spot: float = 13600.0,
    day_low: float = 13550.0,
    day_high: float = 13700.0,
) -> AutoAlert:
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    return AutoAlert(
        alert_id=alert_id,
        symbol=symbol,
        alert_type=alert_type,
        exchange="NFO",
        direction=direction,
        ltp=entry_p,
        trigger_level=entry_p,
        stop_loss=sl,
        target_level=entry_p + 30.0,
        strike=strike,
        option_type=option_type,
        contract_symbol=f"NSE:{symbol}26OCT{int(strike)}{option_type}",
        headline=f"Test {symbol} {int(strike)} {option_type}",
        summary=f"Test summary for {symbol}",
        stage="IGNITED",
        confidence=85,
        created_at=now_iso,
        is_live=True,
        environment="LIVE",
        underlying_spot=underlying_spot,
        metrics={
            "underlying": symbol,
            "day_low": day_low,
            "day_high": day_high,
        },
    )


def test_in_flight_index_thesis_shield(clean_engine):
    """
    Ensures that if an index (e.g. MIDCPNIFTY) already has an active BEARISH setup (e.g. 13650 PE),
    subsequent strike-drifted setups (e.g. 13675 PE) are suppressed to prevent position-stacking on a losing thesis.
    """
    engine = clean_engine

    # 1. First alert fires: MIDCPNIFTY 13650 PE
    alert1 = _make_index_alert(
        symbol="MIDCPNIFTY",
        direction="BEARISH",
        strike=13650.0,
        option_type="PE",
        alert_type="INDEX_MICRO_SCALP",
        alert_id="aa-midcp-pe-13650",
    )
    assert engine.record_alert(alert1) is True
    assert len(engine.get_alerts()) == 1

    # 2. Second alert attempts to fire 5 minutes later on strike 13675 PE while alert1 is active
    alert2 = _make_index_alert(
        symbol="MIDCPNIFTY",
        direction="BEARISH",
        strike=13675.0,
        option_type="PE",
        alert_type="INDEX_PUT_SETUP",
        alert_id="aa-midcp-pe-13675",
    )
    # Must be suppressed by In-Flight Index Thesis Shield
    assert engine.record_alert(alert2) is False
    assert len(engine.get_alerts()) == 1


def test_consecutive_directional_failure_circuit_breaker(clean_engine):
    """
    Ensures that when an index suffers >= 2 consecutive failures in the same direction within 45m,
    the circuit breaker activates and suppresses further alerts in that direction.
    """
    engine = clean_engine
    now = time.time()

    # Simulate 2 consecutive BEARISH failures on MIDCPNIFTY
    engine._directional_failure_history[("MIDCPNIFTY", "BEARISH")] = [
        now - 600.0,  # 10 minutes ago
        now - 120.0,  # 2 minutes ago
    ]

    # Incoming 3rd BEARISH setup must be blocked by the circuit breaker
    alert_bear = _make_index_alert(
        symbol="MIDCPNIFTY",
        direction="BEARISH",
        strike=13650.0,
        option_type="PE",
        alert_id="aa-midcp-pe-third-try",
    )
    assert engine.record_alert(alert_bear) is False

    # Incoming BULLISH setup should NOT be blocked by the bearish failure circuit breaker
    alert_bull = _make_index_alert(
        symbol="MIDCPNIFTY",
        direction="BULLISH",
        strike=13650.0,
        option_type="CE",
        alert_type="INDEX_CALL_SETUP",
        alert_id="aa-midcp-ce-first",
        underlying_spot=13640.0,
        day_low=13596.0,  # +0.32% bounce off low
    )
    assert engine.record_alert(alert_bull) is True


def test_dynamic_reversal_flip_override(clean_engine):
    """
    Ensures that when a BEARISH view was invalidated because the market reversed upwards (+0.30% from low),
    the system dynamically allows the opposing BULLISH setup through rather than locking the trader out for 20 minutes.
    """
    engine = clean_engine
    now = time.time()

    # Prior BEARISH setup on MIDCPNIFTY was invalidated 5 minutes ago
    engine._directional_quarantine["MIDCPNIFTY"] = (now - 300.0, "BEARISH")

    # Incoming BULLISH alert with confirmed bounce (+0.32% off low 13,596 to 13,640)
    alert_bull = _make_index_alert(
        symbol="MIDCPNIFTY",
        direction="BULLISH",
        strike=13650.0,
        option_type="CE",
        alert_type="INDEX_CALL_SETUP",
        alert_id="aa-midcp-ce-reversal",
        underlying_spot=13640.0,
        day_low=13596.0,
    )
    # Dynamic reversal flip override must bypass the 20m quarantine!
    assert engine.record_alert(alert_bull) is True
