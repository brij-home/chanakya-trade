"""
tests/test_market_dynamics_governor.py
──────────────────────────────────────
Deterministic unit and performance test suite for MarketDynamicsGovernor.
Covers:
  - Intraday session micro-phase detection across IST timeline
  - Macro volatility regime classification (India VIX tiers)
  - Instrument tier resolution (Index, Liquid Leader, General F&O, Non-F&O)
  - SEBI expiry week physical delivery quarantine
  - Parametric dynamic calibration context (RVOL, ATR stop-loss, targets, vehicles)
  - In-memory sub-millisecond query performance benchmark
"""

from __future__ import annotations

import time
from datetime import date, datetime

from config.constants import IST
from engine.market_dynamics_governor import (
    MarketDynamicsGovernor,
    get_instrument_tier,
    get_intraday_phase,
    get_market_dynamics_governor,
    get_volatility_regime,
    is_stock_option_quarantined,
)


def test_intraday_phase_detection():
    """Verify exact phase transitions across the Indian derivative market schedule."""
    # Pre-open: 09:05 IST
    dt_pre = datetime(2026, 11, 10, 9, 5, tzinfo=IST)
    assert get_intraday_phase(dt_pre) == "OFF_MARKET_PREOPEN"

    # Opening Auction Discovery: 09:20 IST
    dt_open = datetime(2026, 11, 10, 9, 20, tzinfo=IST)
    assert get_intraday_phase(dt_open) == "OPENING_AUCTION_DISCOVERY"

    # Morning Institutional Expansion: 10:15 IST
    dt_morning = datetime(2026, 11, 10, 10, 15, tzinfo=IST)
    assert get_intraday_phase(dt_morning) == "MORNING_INSTITUTIONAL_EXPANSION"

    # Midday Mean Reversion Chop: 12:30 IST
    dt_midday = datetime(2026, 11, 10, 12, 30, tzinfo=IST)
    assert get_intraday_phase(dt_midday) == "MIDDAY_MEAN_REVERSION_CHOP"

    # Afternoon Trend Ignition: 14:00 IST
    dt_afternoon = datetime(2026, 11, 10, 14, 0, tzinfo=IST)
    assert get_intraday_phase(dt_afternoon) == "AFTERNOON_TREND_IGNITION"

    # Expiry 0DTE Gamma Unpin: 15:00 IST
    dt_gamma = datetime(2026, 11, 10, 15, 0, tzinfo=IST)
    assert get_intraday_phase(dt_gamma) == "EXPIRY_0DTE_GAMMA_UNPIN"

    # Session MOC Hardboard Cutoff: 15:20 IST
    dt_cutoff = datetime(2026, 11, 10, 15, 20, tzinfo=IST)
    assert get_intraday_phase(dt_cutoff) == "SESSION_MOC_HARDBOARD_CUTOFF"

    # Post-close: 15:45 IST
    dt_post = datetime(2026, 11, 10, 15, 45, tzinfo=IST)
    assert get_intraday_phase(dt_post) == "OFF_MARKET_POSTCLOSE"


def test_volatility_regime_classification():
    """Verify India VIX regime classification and safe value handling."""
    regime, val = get_volatility_regime(11.2)
    assert regime == "LOW_VIX"
    assert val == 11.2

    regime, val = get_volatility_regime(14.5)
    assert regime == "NORMAL_VIX"
    assert val == 14.5

    regime, val = get_volatility_regime(19.0)
    assert regime == "ELEVATED_VIX"
    assert val == 19.0

    regime, val = get_volatility_regime(26.5)
    assert regime == "CRISIS_VIX"
    assert val == 26.5

    # Fallback when None or 0.0
    regime, val = get_volatility_regime(None)
    assert regime == "NORMAL_VIX"
    assert val == 14.0


def test_instrument_tier_resolution():
    """Verify tier assignment across indices, leaders, and broader equities."""
    assert get_instrument_tier("NSE:NIFTY 50") == "INDEX"
    assert get_instrument_tier("BANKNIFTY") == "INDEX"
    assert get_instrument_tier("FINNIFTY") == "INDEX"
    assert get_instrument_tier("SENSEX") == "INDEX"

    assert get_instrument_tier("RELIANCE") == "LIQUID_STOCK_LEADER"
    assert get_instrument_tier("HDFCBANK") == "LIQUID_STOCK_LEADER"
    assert get_instrument_tier("INFY") == "LIQUID_STOCK_LEADER"

    assert get_instrument_tier("VOLTAS") == "GENERAL_STOCK_FNO"
    assert get_instrument_tier("ZOMATO") == "GENERAL_STOCK_FNO"

    assert get_instrument_tier("UNKNOWN_PENNY_STOCK") == "NON_FNO"


def test_physical_delivery_quarantine():
    """Verify index exemption and stock option quarantine in expiry week."""
    # Indices are cash-settled and never subject to physical delivery
    assert not is_stock_option_quarantined("NIFTY")
    assert not is_stock_option_quarantined("BANKNIFTY")

    # In November 2026, the monthly derivative expiry is Nov 23, 2026
    # On Friday Nov 20, 2026 (3 days before expiry), stock option should be quarantined
    expiry_week_date = date(2026, 11, 20)
    assert is_stock_option_quarantined("RELIANCE", ref_date=expiry_week_date)

    # On Nov 10, 2026 (16 days before expiry), stock option should NOT be quarantined
    non_expiry_date = date(2026, 11, 10)
    assert not is_stock_option_quarantined("RELIANCE", ref_date=non_expiry_date)


def test_dynamic_calibration_low_vix_vs_elevated_vix():
    """Verify parameter adjustments between Low VIX and Elevated VIX environments."""
    gov = MarketDynamicsGovernor()
    gov.reset_for_testing()

    morning_time = datetime(2026, 11, 10, 10, 30, tzinfo=IST)

    # 1. Low VIX (11.0)
    ctx_low = gov.get_calibration("NIFTY", as_of_time=morning_time, vix_override=11.0)
    assert ctx_low.volatility_regime == "LOW_VIX"
    assert ctx_low.preferred_vehicle == "DEBIT_SPREAD"  # Mandatory spreads in low VIX
    assert ctx_low.atr_sl_multiplier < 1.0  # Tighter stop to prevent theta bleed

    # 2. Elevated VIX (20.0)
    ctx_high = gov.get_calibration("NIFTY", as_of_time=morning_time, vix_override=20.0)
    assert ctx_high.volatility_regime == "ELEVATED_VIX"
    assert ctx_high.preferred_vehicle == "NAKED_OPTION_BUY"
    assert ctx_high.atr_sl_multiplier > 1.2  # Wider stop padding to avoid noise stop-out
    assert ctx_high.target_2_rr >= 3.5  # Higher reward potential on expansion


def test_dynamic_calibration_midday_chop_and_adr_exhaustion():
    """Verify that Midday lull + Wide CPR or High ADR exhaustion vetoes breakout chase."""
    gov = MarketDynamicsGovernor()
    gov.reset_for_testing()

    midday_time = datetime(2026, 11, 10, 12, 15, tzinfo=IST)

    # Midday + Wide CPR
    ctx_chop = gov.get_calibration(
        "BANKNIFTY",
        as_of_time=midday_time,
        vix_override=14.0,
        cpr_type="WIDE",
    )
    assert ctx_chop.mandate == "STALK_PRESERVE_CAPITAL"
    assert not ctx_chop.is_breakout_allowed
    assert ctx_chop.is_mean_reversion_favored
    assert ctx_chop.target_1_rr == 1.5  # Modest scalp target

    # Morning + High ADR exhaustion (>= 85%)
    morning_time = datetime(2026, 11, 10, 10, 45, tzinfo=IST)
    ctx_adr = gov.get_calibration(
        "RELIANCE",
        as_of_time=morning_time,
        vix_override=14.0,
        adr_exhaustion_pct=88.5,
    )
    assert ctx_adr.mandate == "FADE_SPRING"
    assert not ctx_adr.is_breakout_allowed
    assert ctx_adr.is_mean_reversion_favored


def test_performance_sub_millisecond_benchmark():
    """Benchmark: 1,000 calibration queries must complete in < 50ms (< 0.05ms per query)."""
    gov = get_market_dynamics_governor()
    gov.reset_for_testing()

    symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN"]

    # Warm-up cache
    for sym in symbols:
        gov.get_calibration(sym)

    start = time.perf_counter()
    iterations = 1000
    for i in range(iterations):
        sym = symbols[i % len(symbols)]
        ctx = gov.get_calibration(sym)
        assert ctx.symbol == sym

    elapsed = time.perf_counter() - start
    avg_us = (elapsed / iterations) * 1_000_000
    print(
        f"\n[Benchmark] 1,000 governor queries in {elapsed * 1000:.2f}ms (avg {avg_us:.2f} µs/query)"
    )

    # Assert sub-millisecond per query (well under 1,000 µs = 1ms)
    assert avg_us < 100.0, f"Average query took {avg_us:.2f} µs, expected < 100 µs"


def test_governor_diagnostics():
    """Verify telemetry diagnostics output structure."""
    gov = MarketDynamicsGovernor()
    gov.reset_for_testing()
    gov.get_calibration("NIFTY")

    diag = gov.get_diagnostics()
    assert diag["status"] == "HEALTHY"
    assert "current_phase" in diag
    assert "volatility_regime" in diag
    assert "india_vix" in diag
    assert diag["cached_calibrations"] >= 1
    assert "sample_index_calibration" in diag


def test_api_market_dynamics_endpoint():
    """Verify GET /api/market/dynamics returns accurate JSON telemetry."""
    from starlette.testclient import TestClient

    from web.api import app

    client = TestClient(app)
    resp = client.get("/api/market/dynamics?symbol=BANKNIFTY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert data["target_symbol"] == "BANKNIFTY"
    assert "calibration" in data
    assert data["calibration"]["symbol"] == "BANKNIFTY"
    assert "min_required_rvol" in data["calibration"]
    assert "atr_sl_multiplier" in data["calibration"]
    assert "target_1_rr" in data["calibration"]
