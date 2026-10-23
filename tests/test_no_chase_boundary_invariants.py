"""
tests/test_no_chase_boundary_invariants.py
───────────────────────────────────────────
Institutional test suite verifying that option derivative alerts enforce
option-denominated no_chase_boundary and preserve spot ceiling in spot_no_chase_boundary.
"""

from __future__ import annotations

from engine.alert_model import AutoAlert


def test_option_alert_scale_guard_normalization():
    """Verify that an option alert created with spot-denominated no_chase_boundary is normalized."""
    alert = AutoAlert(
        alert_id="aa-precursor-radar-tatasteel-20261022",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="PRECURSOR RADAR: TATASTEEL",
        summary="Test summary",
        ltp=170.41,
        trigger_level=172.0,
        target_level=185.0,
        stop_loss=165.0,
        option_premium=2.82,
        strike=170.0,
        option_type="CE",
        contract_symbol="NSE:TATASTEEL26OCT170CE",
        no_chase_boundary=180.34,  # Spot-denominated boundary
    )

    # Invariant: no_chase_boundary must be normalized to option premium scale (2.82 * 1.05 = 2.96)
    assert alert.no_chase_boundary == 2.96
    # Invariant: underlying spot boundary must be preserved in spot_no_chase_boundary
    assert alert.spot_no_chase_boundary == 180.34


def test_option_alert_from_dict_and_to_dict():
    """Verify that AutoAlert.from_dict and to_dict preserve both option premium and spot boundaries."""
    raw_dict = {
        "alert_id": "aa-precursor-radar-coforge-20261022",
        "alert_type": "PRECURSOR_RADAR",
        "stage": "EARLY_WARNING",
        "symbol": "COFORGE",
        "exchange=": "NSE",
        "direction": "BULLISH",
        "headline": "PRECURSOR RADAR: COFORGE",
        "summary": "Coiling test",
        "ltp": 1918.4,
        "trigger_level": 1970.0,
        "target_level": 2100.0,
        "stop_loss": 1880.0,
        "option_premium": 22.05,
        "strike": 1980.0,
        "option_type": "CE",
        "contract_symbol": "NSE:COFORGE26OCT1980CE",
        "no_chase_boundary": 1993.64,  # Spot boundary
    }

    alert = AutoAlert.from_dict(raw_dict)
    assert alert.no_chase_boundary == round(22.05 * 1.05, 2)
    assert alert.spot_no_chase_boundary == 1993.64

    exported = alert.to_dict()
    assert exported["no_chase_boundary"] == round(22.05 * 1.05, 2)
    assert exported["spot_no_chase_boundary"] == 1993.64


def test_equity_alert_unaffected():
    """Verify that pure equity cash alerts keep their original no_chase_boundary unmodified."""
    alert = AutoAlert(
        alert_id="aa-orb-reliance-bull-20261022",
        alert_type="ORB",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="ORB BREAKOUT: RELIANCE",
        summary="Equity test",
        ltp=1410.0,
        trigger_level=1412.0,
        target_level=1450.0,
        stop_loss=1390.0,
        no_chase_boundary=1420.0,
    )

    assert alert.no_chase_boundary == 1420.0
    assert alert.spot_no_chase_boundary is None


def test_bearish_put_option_scale_guard():
    """Verify that bearish PE option alerts compute ceiling with 5% tolerance on buy side."""
    alert = AutoAlert(
        alert_id="aa-afternoon-thrust-banknifty-bear-20261022",
        alert_type="AFTERNOON_THRUST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="AFTERNOON THRUST: BANKNIFTY 54700 PE",
        summary="Bearish PE test",
        ltp=250.0,
        trigger_level=250.0,
        target_level=400.0,
        stop_loss=180.0,
        option_premium=250.0,
        strike=54700.0,
        option_type="PE",
        contract_symbol="NSE:BANKNIFTY26OCT54700PE",
        no_chase_boundary=55100.0,  # Underlying spot boundary
    )

    # For PE option buy, option entry is 250, so option ceiling is 250 * 1.05 = 262.5
    # (Since direction is BEARISH on market, but contract is PE bought at premium, PE buyers pay premium)
    assert alert.no_chase_boundary == 262.5
    assert alert.spot_no_chase_boundary == 55100.0
