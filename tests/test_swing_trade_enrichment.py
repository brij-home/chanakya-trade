"""
tests/test_swing_trade_enrichment.py
────────────────────────────────────
Institutional regression test suite verifying swing trade discovery, lifecycle,
Actionable Blueprint contracts, horizon filtering, and multi-session persistence.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.alert_identity import validate_alert_id
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.swing_inflection import (
    _format_swing_inflection_alert,
)
from analysis.inflection_scanner import InflectionSetup
from market.yfinance_provider import _to_yf_symbol

IST = ZoneInfo("Asia/Kolkata")


def _make_dummy_inflection_setup(
    symbol: str = "TRENT",
    timing_state: str = "TRIGGER_NOW",
    archetype: str = "VCP_PIVOT_BREAKOUT",
    score: int = 88,
) -> InflectionSetup:
    return InflectionSetup(
        symbol=symbol,
        name=f"{symbol} Ltd.",
        sector="NIFTY CONSUMPTION",
        sector_icon="🛍️",
        ltp=1520.0,
        day_change_pct=2.5,
        inflection_score=score,
        primary_archetype=archetype,
        archetype_label="Minervini VCP Compression",
        timing_state=timing_state,
        timing_label="Trigger Ready",
        weinstein_stage="STAGE_2_MARKUP",
        vcp_detected=True,
        vcp_tightness_pct=2.4,
        vcp_pivot_price=1520.0,
        squeeze_state="SQUEEZE_FIRING",
        squeeze_duration=6,
        rvol_20d=2.4,
        trend_template_passed=8,
        sector_tailwind_score=85,
        rrg_quadrant="LEADING",
        forensic_safe=True,
        smc_regime="BULLISH_ORDER_BLOCK",
        smc_setup="Liquidity Sweep at Pivot",
        entry_price=1520.0,
        stop_loss=1440.0,
        target_1=1680.0,
        target_2=1800.0,
        target_moonshot=1960.0,
        risk_reward_ratio=3.0,
        risk_pts=80.0,
        reward_pts=280.0,
        horizon="SWING_SHORT",
        turnover_20d_cr=125.0,
        suggested_action="Aggressive Pivot Breakout Buy",
        catalyst_summary="Institutional VCP coil with 2.4x volume expansion",
    )


def test_swing_inflection_blueprint_and_active_stages():
    """Verify swing inflection setup generates a complete institutional Actionable Blueprint and active stage."""
    setup = _make_dummy_inflection_setup(symbol="TRENT", timing_state="TRIGGER_NOW")

    # 1. Off-market generation -> stage must be ACTIONABLE (never unignited EARLY_WARNING)
    alert = _format_swing_inflection_alert(setup, mkt_open=False)
    assert alert.stage == "ACTIONABLE", (
        f"Off-market swing setup stage should be ACTIONABLE, got {alert.stage}"
    )
    assert alert.is_active is True
    assert alert.time_horizon in ("SWING_SHORT", "SWING_MID")
    assert alert.ttl_seconds >= 86400 * 10

    # 2. Market-open generation -> stage must be IGNITED
    alert_open = _format_swing_inflection_alert(setup, mkt_open=True)
    assert alert_open.stage == "IGNITED"
    assert alert_open.is_active is True

    # 3. Pullback / Coiling setups -> stage must be PRIMED
    setup_pullback = _make_dummy_inflection_setup(symbol="BEL", timing_state="PULLBACK_RETEST")
    alert_pb = _format_swing_inflection_alert(setup_pullback)
    assert alert_pb.stage == "PRIMED"
    assert alert_pb.is_active is True

    # 4. Actionable Blueprint completeness
    plan = alert.actionable_plan
    assert plan["action"] == "BUY"
    assert plan["segment"] == "EQUITY"
    assert plan["recommended_entry"] == 1520.0
    assert plan["invalidation_stop"] == 1440.0
    assert "₹" in plan["stop_loss"]
    assert "₹" in plan["target_1"]
    assert "₹" in plan["target_2"]
    assert "₹" in plan["runner_target"]
    assert "no_chase_boundary" in plan
    assert plan["no_chase_boundary"] > 1520.0

    # 5. Deterministic alert ID validation
    is_valid, reason = validate_alert_id(alert.alert_id)
    assert is_valid, f"Alert ID '{alert.alert_id}' failed invariant check: {reason}"


def test_swing_multi_session_survival_in_is_expired():
    """Verify that multi-session setups (SWING_SHORT, SWING_MID) do not expire across daily calendar rollovers."""
    now_ist = datetime.now(IST)
    yesterday = now_ist - timedelta(days=2)
    yesterday_str = yesterday.strftime("%Y-%m-%d %H:%M:%S IST")

    # A swing alert created 2 days ago in PRIMED or ACTIONABLE stage
    swing_alert = AutoAlert(
        alert_id="ret-swing-test-01",
        alert_type="VCP_PIVOT_BREAKOUT",
        stage="PRIMED",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Trent VCP Primed",
        summary="Coiling base",
        ltp=1520.0,
        trigger_level=1520.0,
        target_level=1680.0,
        stop_loss=1440.0,
        time_horizon="SWING_MID",
        created_at=yesterday_str,
    )

    # Must NOT be expired! SWING_MID has a 25-trading-day shelf-life!
    assert swing_alert.is_expired is False, "Swing trade should not be expired after 2 days"
    assert swing_alert.is_active is True


def test_resolve_session_end_preserves_swing_trades():
    """Verify that resolve_session_end_alerts never resolves or archives multi-session swing setups."""
    now_ist = datetime.now(IST)
    yesterday_str = (now_ist - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S IST")

    engine = AutoAlertEngine()
    swing_alert = AutoAlert(
        alert_id="ret-swing-sess-end",
        alert_type="SQUEEZE_BREAKOUT",  # An alert_type that is in intraday_types!
        stage="ACTIONABLE",
        symbol="LUMAXTECH",
        exchange="NSE",
        direction="BULLISH",
        headline="Lumax Squeeze Breakout",
        summary="Daily squeeze firing",
        ltp=450.0,
        trigger_level=448.0,
        target_level=490.0,
        stop_loss=425.0,
        time_horizon="SWING_MID",  # Multi-session horizon!
        created_at=yesterday_str,
    )

    with engine._lock:
        engine._alerts = [swing_alert]

    resolved = engine.resolve_session_end_alerts()
    assert len(resolved) == 0, (
        "Multi-session swing trades must not be retired by resolve_session_end_alerts"
    )
    assert swing_alert.is_active is True
    assert swing_alert.is_archived is False


def test_get_alerts_horizon_filtering():
    """Verify that querying horizon='SWING' returns both SWING_SHORT and SWING_MID trades."""
    engine = AutoAlertEngine()
    a_short = AutoAlert(
        alert_id="hz-short",
        alert_type="SWING_TRADE",
        stage="ACTIONABLE",
        symbol="DYNAMATECH",
        exchange="NSE",
        direction="BULLISH",
        headline="Short Swing",
        summary="2-5 day trade",
        ltp=100.0,
        trigger_level=100.0,
        target_level=110.0,
        stop_loss=95.0,
        time_horizon="SWING_SHORT",
    )
    a_mid = AutoAlert(
        alert_id="hz-mid",
        alert_type="SWING_TRADE",
        stage="ACTIONABLE",
        symbol="ONEPOINT",
        exchange="NSE",
        direction="BULLISH",
        headline="Mid Swing",
        summary="1-4 week trade",
        ltp=200.0,
        trigger_level=200.0,
        target_level=230.0,
        stop_loss=185.0,
        time_horizon="SWING_MID",
    )
    a_intra = AutoAlert(
        alert_id="hz-intra",
        alert_type="SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Intraday scalp",
        summary="Today only",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25100.0,
        stop_loss=24950.0,
        time_horizon="INTRADAY",
    )

    with engine._lock:
        engine._alerts = [a_short, a_mid, a_intra]

    # Query horizon='SWING'
    swings = engine.get_alerts(horizon="SWING")
    swing_ids = {a.alert_id for a in swings}
    assert "hz-short" in swing_ids, "SWING_SHORT must be included in SWING filter"
    assert "hz-mid" in swing_ids, "SWING_MID must be included in SWING filter"
    assert "hz-intra" not in swing_ids, "INTRADAY must be excluded from SWING filter"

    # Query horizon='SWING_ALL'
    swings_all = engine.get_alerts(horizon="SWING_ALL")
    assert len(swings_all) == 2


def test_yfinance_symbol_suffix_deduplication():
    """Verify that _to_yf_symbol does not append duplicate .NS or .BO suffixes."""
    assert _to_yf_symbol("RELIANCE") == "RELIANCE.NS"
    assert _to_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"
    assert _to_yf_symbol("NSE:RELIANCE") == "RELIANCE.NS"
    assert _to_yf_symbol("TCS", exchange="BSE") == "TCS.BO"
    assert _to_yf_symbol("TCS.BO", exchange="BSE") == "TCS.BO"
    assert _to_yf_symbol("BSE:TCS") == "TCS.BO"


def test_eod_symbol_cleaning_and_bse_universe_broadening():
    """Verify that _clean_eod_symbol normalizes all broker prefixes and exchange suffixes for NSE and BSE."""
    from engine.eod_store import _clean_eod_symbol
    from analysis.universe import THEMATIC_PRESETS

    assert _clean_eod_symbol("RELIANCE") == "RELIANCE"
    assert _clean_eod_symbol("RELIANCE.NS") == "RELIANCE"
    assert _clean_eod_symbol("NSE:RELIANCE") == "RELIANCE"
    assert _clean_eod_symbol("BSE:500180") == "500180"
    assert _clean_eod_symbol("500180.BO") == "500180"
    assert _clean_eod_symbol("BSE:TCS") == "TCS"
    assert _clean_eod_symbol("TCS.BO") == "TCS"

    all_symbols = THEMATIC_PRESETS["all_equities_nse_bse"]["symbols"]
    assert len(all_symbols) >= 1000, (
        f"all_equities_nse_bse must contain broad universe, got {len(all_symbols)}"
    )
    # Verify BSE 500 constituents are present
    assert "BSE" in all_symbols
    assert "ABB" in all_symbols
