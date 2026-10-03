"""
tests/test_regime_governor.py
─────────────────────────────
Unit tests for the Dynamic Market Regime Governor.
Verifies regime classification, detector eligibility, and scrutiny integration.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from analysis.regime_governor import (
    classify_market_regime,
    is_detector_eligible_for_regime,
)
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor

IST = ZoneInfo("Asia/Kolkata")


def test_classify_market_regime_trend_expansion():
    """Verify classification of standard trend expansion regime."""
    dt = datetime(2026, 10, 1, 10, 0, tzinfo=IST)  # Thursday 10:00 IST
    regime = classify_market_regime(vix=15.0, nifty_spot=25000.0, ref_dt=dt)
    assert regime.regime == "TREND_EXPANSION"
    assert regime.min_scrutiny_score == 70
    assert regime.dominant_bias == "TREND_FRIENDLY"


def test_classify_market_regime_balanced_chop_compressed_vix():
    """Verify that low VIX (<12.5) classifies as BALANCED_CHOP with raised scrutiny threshold."""
    dt = datetime(2026, 10, 1, 10, 0, tzinfo=IST)
    regime = classify_market_regime(vix=11.2, nifty_spot=25000.0, ref_dt=dt)
    assert regime.regime == "BALANCED_CHOP"
    assert regime.min_scrutiny_score == 80
    assert regime.dominant_bias == "MEAN_REVERSION"


def test_classify_market_regime_orb_trapped():
    """Verify that tight ORB containment during midday classifies as BALANCED_CHOP."""
    dt = datetime(2026, 10, 1, 11, 45, tzinfo=IST)  # Midday 11:45 IST
    # Nifty trapped between 24980 and 25020 (range = 40 pts = 0.16% of spot)
    regime = classify_market_regime(
        vix=13.0,
        nifty_spot=25000.0,
        orb_high=25020.0,
        orb_low=24980.0,
        ref_dt=dt,
    )
    assert regime.regime == "BALANCED_CHOP"
    assert regime.min_scrutiny_score == 80


def test_classify_market_regime_macro_shock():
    """Verify that VIX >= 19.0 or macro_score <= -50 classifies as MACRO_SHOCK."""
    dt = datetime(2026, 10, 1, 10, 0, tzinfo=IST)
    regime = classify_market_regime(vix=21.5, nifty_spot=24500.0, ref_dt=dt)
    assert regime.regime == "MACRO_SHOCK"
    assert regime.min_scrutiny_score == 85
    assert regime.dominant_bias == "CAPITAL_PRESERVATION"


def test_classify_market_regime_expiry_afternoon():
    """Verify that expiry afternoon session classifies as VOLATILITY_EXPANSION_EXPIRY."""
    dt = datetime(2026, 10, 1, 14, 0, tzinfo=IST)  # Thursday (Nifty Expiry) 14:00 IST
    regime = classify_market_regime(vix=14.0, nifty_spot=25000.0, ref_dt=dt)
    assert regime.regime == "VOLATILITY_EXPANSION_EXPIRY"
    assert regime.min_scrutiny_score == 75
    assert regime.is_expiry_session is True


def test_detector_eligibility_in_chop():
    """Verify that breakouts in BALANCED_CHOP require RVOL >= 2.0x."""
    dt = datetime(2026, 10, 1, 10, 0, tzinfo=IST)
    regime = classify_market_regime(vix=11.5, ref_dt=dt)

    # Low RVOL breakout -> suppressed
    is_elig, reason = is_detector_eligible_for_regime("SQUEEZE_BREAKOUT", regime, rvol=1.3)
    assert is_elig is False
    assert "BALANCED_CHOP" in reason

    # High institutional RVOL breakout -> approved
    is_elig_high, _ = is_detector_eligible_for_regime("SQUEEZE_BREAKOUT", regime, rvol=2.4)
    assert is_elig_high is True

    # Mean reversion setup (Turtle Soup) -> always approved in chop
    is_elig_ts, _ = is_detector_eligible_for_regime("TURTLE_SOUP_SWEEP", regime, rvol=1.1)
    assert is_elig_ts is True
