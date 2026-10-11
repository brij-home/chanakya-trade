"""
tests/test_equities_quality_guardrails.py
────────────────────────────────────────
Regression & Invariant test suite for Equities Alert Quality & Safety Guardrails.
Guarantees:
  1. Swing Equities Stop-Loss Volatility Floor (>= 1.20x ATR)
  2. Intraday Equities Stop-Loss Volatility Floor (>= 0.70x ATR)
  3. Late-Session Exhaustion Gate (post-15:05 IST rejection for intraday momentum)
  4. ORB Volatility Noise Floor & ATR Provenance
  5. Alert Post-Mortem Runner preserves active multi-session swing setups (zero premature Day-1 UNFULFILLED_EOD)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest
import pandas as pd

from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlert
from engine.detectors.orb import detect_opening_range_breakout
from engine.alert_postmortem_runner import (
    generate_session_scorecard,
    run_eod_alert_postmortems,
)

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)


def test_swing_equities_sub_atr_noise_floor_veto(auditor: AlertScrutinyAuditor):
    """
    Swing equity setups (e.g. MULTIBAGGER, STAGE_1_TO_2_EXPANSION, PATTERN_COILING)
    must enforce stop distance >= 1.20x ATR to survive normal inter-day noise oscillations.
    """
    # 1. Alert with stop distance only 30 pts (0.6x ATR) when ATR is 50 pts -> MUST BE VETOED
    alert_tight = AutoAlert(
        alert_id="aa-swing-tight-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:DYNAMATECH",
        exchange="NSE",
        direction="BULLISH",
        headline="Dynamatic Tech Stage 2 Expansion",
        summary="Volume breakout from 6-month base",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2470.0,  # 30 pts stop distance
        target_level=2700.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 50.0, "atr_14": 50.0},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_tight)
    assert passed is False
    assert "Sub-ATR Equity Noise Trap" in reason
    assert "1.20x ATR" in reason

    # 2. Alert with stop distance 65 pts (1.30x ATR) -> MUST PASS
    alert_adequate = AutoAlert(
        alert_id="aa-swing-adequate-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:DYNAMATECH",
        exchange="NSE",
        direction="BULLISH",
        headline="Dynamatic Tech Stage 2 Expansion",
        summary="Volume breakout from 6-month base",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2435.0,  # 65 pts stop distance (1.30x ATR)
        target_level=2700.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 50.0, "atr_14": 50.0},
    )
    passed_ok, reason_ok, flags_ok = auditor.verify_tier1_sanity(alert_adequate)
    assert passed_ok is True
    assert reason_ok == ""


def test_intraday_equities_sub_atr_noise_floor_veto(auditor: AlertScrutinyAuditor):
    """
    Intraday cash equity momentum/breakout setups must enforce stop distance >= 0.70x ATR
    to avoid sub-ATR opening chop whipsaws.
    """
    # ATR is 40.0 pts. Stop distance is 15.0 pts (0.375x ATR) -> VETOED
    alert_tight = AutoAlert(
        alert_id="aa-intra-tight-1",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance ORB Breakout",
        summary="Reclaimed opening high",
        ltp=2800.0,
        trigger_level=2800.0,
        stop_loss=2785.0,  # 15 pts stop distance (< 0.70 * 40 = 28 pts)
        target_level=2880.0,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 40.0, "atr_14": 40.0},
    )
    passed, reason, _ = auditor.verify_tier1_sanity(alert_tight)
    assert passed is False
    assert "Sub-ATR Equity Noise Trap" in reason
    assert "0.70x ATR" in reason

    # Stop distance 30.0 pts (0.75x ATR) -> PASS
    alert_ok = AutoAlert(
        alert_id="aa-intra-ok-1",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance ORB Breakout",
        summary="Reclaimed opening high",
        ltp=2800.0,
        trigger_level=2800.0,
        stop_loss=2770.0,  # 30 pts stop distance (>= 28.0 pts)
        target_level=2880.0,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 40.0, "atr_14": 40.0},
    )
    passed_ok, reason_ok, _ = auditor.verify_tier1_sanity(alert_ok)
    assert passed_ok is True
    assert reason_ok == ""


def test_late_session_exhaustion_gate(auditor: AlertScrutinyAuditor):
    """
    Intraday equity momentum setups triggered post-15:05 IST are vetoed to avoid
    broker MIS auto-square-off (15:15 IST) liquidity cliffs.
    Swing setups remain permitted.
    """
    late_time = "2026-10-12 15:08:00 IST"

    # 1. Intraday equity setup at 15:08 IST -> VETOED
    alert_intra = AutoAlert(
        alert_id="aa-intra-late-1",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Breakout",
        summary="Late momentum breakout",
        ltp=900.0,
        trigger_level=900.0,
        stop_loss=885.0,
        target_level=940.0,
        time_horizon="INTRADAY",
        created_at=late_time,
        is_live=True,
        environment="LIVE",
        metrics={"atr": 15.0},
    )
    passed_intra, reason_intra, _ = auditor.verify_tier1_sanity(alert_intra)
    assert passed_intra is False
    assert "Late-Session Exhaustion Gate" in reason_intra

    # 2. Swing equity setup at 15:08 IST -> ALLOWED
    alert_swing = AutoAlert(
        alert_id="aa-swing-late-1",
        alert_type="MULTIBAGGER",
        stage="ACTIONABLE",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Multi-Week Squeeze",
        summary="Position for multi-week expansion",
        ltp=900.0,
        trigger_level=900.0,
        stop_loss=870.0,  # 30 pts (> 1.20 * 15 = 18 pts)
        target_level=1020.0,
        time_horizon="SWING",
        created_at=late_time,
        is_live=True,
        environment="LIVE",
        metrics={"atr": 15.0},
    )
    passed_swing, reason_swing, _ = auditor.verify_tier1_sanity(alert_swing)
    assert passed_swing is True
    assert reason_swing == ""


def test_orb_detector_volatility_noise_floor():
    """
    Verify ORB detector respects minimum risk floor on narrow ranges and records ATR metrics.
    """
    # Construct 6 bars with 0.3% range (LTP=1000, high=1001.5, low=998.5, range=3.0)
    dates = pd.date_range("2026-10-12 09:15", periods=6, freq="5min")
    df = pd.DataFrame(
        {
            "open": [1000.0] * 6,
            "high": [1001.5] * 6,
            "low": [998.5] * 6,
            "close": [1000.0] * 6,
            "volume": [10000] * 6,
        },
        index=dates,
    )
    ref_time = datetime(2026, 10, 12, 9, 35, tzinfo=IST)

    alert = detect_opening_range_breakout(
        symbol="SBIN",
        df=df,
        ltp=1002.0,
        vwap=1000.0,
        rvol=1.8,
        ref_time=ref_time,
    )

    assert alert is not None
    assert alert.alert_type == "ORB_BREAKOUT"
    # Spot is 1002, range is 3.0, mid is 1000.
    # Without floor, stop_loss would be 1000.0 (only 2 pts risk, 0.2%).
    # With min_orb_risk = max(1.0, 0.25 * atr, 0.004 * 1002 = 4.0 pts):
    # stop_loss must be <= 1002 - 4.0 = 998.0 (at least 4.0 pts risk).
    assert (alert.trigger_level - alert.stop_loss) >= 3.0
    assert "atr" in alert.metrics
    assert "min_noise_sl_pts" in alert.metrics


def test_postmortem_runner_preserves_active_multi_session_swing():
    """
    Verify that evaluate_eod_alert_post_mortems does NOT mark active swing setups
    as UNFULFILLED_EOD on Day 1.
    """
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")

    # Swing alert created today, trading flat (+0.1R), neither invalidated nor expired
    active_swing = AutoAlert(
        alert_id="aa-swing-active-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="APLAPOLLO",
        exchange="NSE",
        direction="BULLISH",
        headline="APL Apollo Structural Breakout",
        summary="Multi-week stage 2 ignition",
        ltp=1620.0,
        trigger_level=1600.0,
        stop_loss=1520.0,
        target_level=1800.0,
        time_horizon="SWING",
        created_at=f"{today_str} 11:30:00 IST",
        is_invalidated=False,
        r_multiple=0.1,
    )

    # Intraday alert created today, flat at EOD -> genuinely unfulfilled
    unfulfilled_intra = AutoAlert(
        alert_id="aa-intra-flat-1",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Trent ORB Breakout",
        summary="Intraday scalp setup",
        ltp=6010.0,
        trigger_level=6000.0,
        stop_loss=5960.0,
        target_level=6100.0,
        time_horizon="INTRADAY",
        created_at=f"{today_str} 09:45:00 IST",
        is_invalidated=False,
        r_multiple=0.1,
    )

    mock_engine = MagicMock()
    mock_engine.get_alerts.return_value = [active_swing, unfulfilled_intra]

    # Run scorecard
    scorecard = generate_session_scorecard(
        [active_swing, unfulfilled_intra], session_date=today_str
    )
    assert scorecard["total_alerts"] == 2
    assert scorecard["active_swings"] == 1
    assert scorecard["unfulfilled"] == 1

    # Run EOD post-mortems
    res = run_eod_alert_postmortems(auto_engine=mock_engine, force=True)
    assert res["status"] == "COMPLETED"

    # Only the intraday alert should have received post-mortem; swing alert must be skipped
    evaluated_ids = [d["alert_id"] for d in res["details"]]
    assert "aa-intra-flat-1" in evaluated_ids
    assert "aa-swing-active-1" not in evaluated_ids


def test_falcon_cheetah_severe_chop_breakout_veto(auditor: AlertScrutinyAuditor):
    """
    Falcon Eye & Cheetah Pounce Invariant:
    When an equity stock is in severe consolidation chop (CHOP >= 61.8 or ADX < 20.0),
    routine breakout attempts must be VETOED to avoid false breakouts and whipsaw traps,
    UNLESS backed by confirmed institutional thrust (RVOL >= 2.2x or is_institutional_thrust).
    """
    # 1. Breakout setup in severe chop with ordinary volume (RVOL = 1.2x) -> VETOED
    alert_chop = AutoAlert(
        alert_id="aa-chop-trap-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:KALYANKJIL",
        exchange="NSE",
        direction="BULLISH",
        headline="Kalyan Jewellers Breakout Attempt",
        summary="Stage expansion in consolidation",
        ltp=550.0,
        trigger_level=550.0,
        stop_loss=535.0,  # 15 pts risk
        target_level=600.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 10.0,
            "chop_index": 68.5,  # Severe chop (>= 61.8)
            "adx_14": 15.2,  # Non-trending (< 20.0)
            "rvol": 1.20,
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_chop)
    assert passed is False
    assert "Falcon Chop Trap Veto" in reason
    assert "severe consolidation chop" in reason
    assert flags["equity_regime_valid"] is False

    # 2. Same setup with confirmed institutional thrust (RVOL = 2.6x, thrust badge) -> PASSES
    alert_thrust = AutoAlert(
        alert_id="aa-thrust-ok-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:KALYANKJIL",
        exchange="NSE",
        direction="BULLISH",
        headline="Kalyan Jewellers Institutional Breakout",
        summary="High-volume thrust out of base",
        ltp=550.0,
        trigger_level=550.0,
        stop_loss=535.0,
        target_level=600.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 10.0,
            "chop_index": 68.5,
            "adx_14": 15.2,
            "rvol": 2.60,
            "is_institutional_thrust": True,
        },
    )
    passed_ok, reason_ok, flags_ok = auditor.verify_tier1_sanity(alert_thrust)
    assert passed_ok is True
    assert reason_ok == ""
    assert flags_ok["equity_regime_valid"] is True


def test_falcon_cheetah_trending_momentum_expansion_passes(auditor: AlertScrutinyAuditor):
    """
    When Falcon Eye confirms strong trending expansion (CHOP <= 38.2 and ADX >= 25.0),
    Cheetah Pounce authorizes momentum breakouts with high follow-through expectation.
    """
    alert_trend = AutoAlert(
        alert_id="aa-trend-pounce-1",
        alert_type="BREAKOUT",
        stage="IGNITED",
        symbol="NSE:DIXON",
        exchange="NSE",
        direction="BULLISH",
        headline="Dixon Trend Expansion",
        summary="Directional breakout in trending market",
        ltp=15000.0,
        trigger_level=15000.0,
        stop_loss=14700.0,  # 300 pts risk (2.0%)
        target_level=16000.0,  # 1000 pts reward
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 250.0,
            "chop_index": 32.0,  # Trending expansion (<= 38.2)
            "adx_14": 31.5,  # Strong trend (>= 25.0)
            "rvol": 1.60,
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_trend)
    assert passed is True
    assert reason == ""
    assert flags["cheetah_mandate"] == "CHEETAH_POUNCE_MOMENTUM"
    assert flags["equity_regime_valid"] is True


def test_order_flow_cvd_bearish_exhaustion_absorption_veto(auditor: AlertScrutinyAuditor):
    """
    Order Flow CVD Delta Gate Invariant:
    A bullish breakout where CVD delta is declining while price tests the highs indicates
    passive institutional limit sellers absorbing aggressive retail buyers.
    This absorption trap must be strictly VETOED.
    """
    alert_cvd_trap = AutoAlert(
        alert_id="aa-cvd-trap-1",
        alert_type="BREAKOUT",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Motors Breakout",
        summary="Testing resistance",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1060.0,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 18.0,
            "cvd_divergence": "BEARISH_EXHAUSTION",  # Passive iceberg sell absorption!
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_cvd_trap)
    assert passed is False
    assert "Order Flow CVD Exhaustion Veto" in reason
    assert "passive institutional limit asks" in reason
    assert flags["cvd_flow_valid"] is False


def test_order_flow_cvd_bullish_absorption_veto(auditor: AlertScrutinyAuditor):
    """
    Order Flow CVD Delta Gate Invariant:
    A bearish breakdown where CVD delta is rising while price tests the lows indicates
    passive institutional limit buyers absorbing aggressive retail sellers (Wyckoff spring).
    This breakdown trap must be strictly VETOED.
    """
    alert_cvd_short_trap = AutoAlert(
        alert_id="aa-cvd-short-trap-1",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="NSE:TATAMOTORS",
        exchange="NSE",
        direction="BEARISH",
        headline="Tata Motors Breakdown",
        summary="Testing day low",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=1020.0,
        target_level=940.0,
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 18.0,
            "cvd_divergence": "BULLISH_ABSORPTION",  # Passive iceberg buy accumulation!
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_cvd_short_trap)
    assert passed is False
    assert "Order Flow CVD Absorption Veto" in reason
    assert "passive institutional limit bids" in reason
    assert flags["cvd_flow_valid"] is False


def test_reward_to_obstacle_headroom_veto(auditor: AlertScrutinyAuditor):
    """
    Reward-to-Obstacle (R:Obs >= 1.5R) Headroom Invariant:
    A setup where the nearest HTF resistance (Daily 200-EMA, Prior Week High, Daily Supply OB)
    provides less than 1.5R headroom must be VETOED to eliminate stuck setups hitting brick walls.
    """
    # 1. Spot = 1000, SL = 980 (Risk = 20 pts). Target 1 = 1060 (+3.0R).
    # Nearest HTF obstacle (Daily 200-EMA) is at 1014 (only 14 pts = 0.70R headroom < 1.5R) -> VETOED
    alert_blocked = AutoAlert(
        alert_id="aa-obstacle-blocked-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:CIPLA",
        exchange="NSE",
        direction="BULLISH",
        headline="Cipla Stage Expansion",
        summary="Expansion into resistance",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1060.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 15.0,
            "nearest_resistance": 1014.0,  # Only 0.70R headroom!
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_blocked)
    assert passed is False
    assert "Truncated Obstacle Headroom Veto" in reason
    assert "0.70R headroom" in reason
    assert flags["obstacle_runway_clear"] is False

    # 2. Same setup with clear obstacle runway (nearest resistance at 1050 = 2.50R headroom >= 1.5R) -> PASSES
    alert_clear = AutoAlert(
        alert_id="aa-obstacle-clear-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:CIPLA",
        exchange="NSE",
        direction="BULLISH",
        headline="Cipla Stage Expansion Clear Runway",
        summary="Expansion into clear runway",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1060.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 15.0,
            "nearest_resistance": 1050.0,  # 2.50R headroom!
        },
    )
    passed_ok, reason_ok, flags_ok = auditor.verify_tier1_sanity(alert_clear)
    assert passed_ok is True
    assert reason_ok == ""


def test_parent_sector_rrg_lagging_quadrant_headwind_veto(
    auditor: AlertScrutinyAuditor, monkeypatch
):
    """
    Parent Sector RRG Alignment Invariant:
    A bottom-up equity breakout whose parent sector is in the RRG LAGGING quadrant
    with downward momentum and active intraday bearish divergence must be VETOED.
    Verified decouplers remain permitted.
    """
    from analysis.sector_rotation import StockTailwind

    # Mock get_stock_tailwind returning a lagging sector with active bearish divergence
    mock_tailwind = StockTailwind(
        symbol="VOLTAS",
        sector="CONSUMER",
        quadrant="LAGGING",
        rs_ratio=96.5,
        rs_momentum=94.0,  # Momentum < 98.0
        tailwind_score=25,
        alignment="HEADWIND",
        analysis="Lagging sector undergoing institutional rotation",
        status="AVAILABLE",
        intraday_rs=-1.2,
        intraday_alignment="INTRADAY_BEARISH_DIVERGENCE",
    )
    monkeypatch.setattr("analysis.sector_rotation.get_stock_tailwind", lambda sym: mock_tailwind)

    # 1. Non-decoupled stock in lagging sector -> VETOED
    alert_lagging = AutoAlert(
        alert_id="aa-sector-lag-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:VOLTAS",
        exchange="NSE",
        direction="BULLISH",
        headline="Voltas Base Breakout",
        summary="Breakout in lagging sector",
        ltp=1500.0,
        trigger_level=1500.0,
        stop_loss=1470.0,
        target_level=1600.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 20.0},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_lagging)
    assert passed is False
    assert "Sector RRG Headwind Veto" in reason
    assert "RRG LAGGING quadrant" in reason
    assert flags["sector_rrg_valid"] is False

    # 2. Stock flagged as verified decoupler (is_decoupler=True) -> PASSES
    alert_decoupled = AutoAlert(
        alert_id="aa-sector-decoupled-1",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="ACTIONABLE",
        symbol="NSE:VOLTAS",
        exchange="NSE",
        direction="BULLISH",
        headline="Voltas Decoupled Breakout",
        summary="Outperforming parent sector",
        ltp=1500.0,
        trigger_level=1500.0,
        stop_loss=1470.0,
        target_level=1600.0,
        time_horizon="SWING",
        is_live=True,
        environment="LIVE",
        metrics={"atr": 20.0, "is_decoupler": True},
    )
    passed_dec, reason_dec, flags_dec = auditor.verify_tier1_sanity(alert_decoupled)
    assert passed_dec is True
    assert reason_dec == ""


def test_turtle_soup_sweep_inverts_chop_trap():
    """
    Wyckoff Trap Inversion / Turtle Soup Detector Invariant:
    When an asset sweeps below 20-bar swing low by < 0.75%, creates a large lower wick (>= 35%),
    and closes back above the level, detect_turtle_soup_sweep must invert the false breakdown
    into an asymmetric institutional long setup (R:R >= 1:3.0) with SL below the wick.
    """
    from engine.detectors.turtle_soup import detect_turtle_soup_sweep

    # Construct 25 bars: rangebound around 500, with prior 20-bar low at 495.0
    dates = pd.date_range("2026-10-12 09:15", periods=25, freq="5min")
    opens = [500.0] * 25
    highs = [503.0] * 25
    lows = [497.0] * 25
    closes = [500.0] * 25

    # Bar 10 establishes prior swing low at 495.0
    lows[10] = 495.0

    # Bar 24 (the sweep bar): pierces below 495.0 to 493.5 (0.3% sweep),
    # then closes back up at 497.0 (strong lower rejection wick)
    opens[24] = 496.0
    highs[24] = 497.5
    lows[24] = 493.5  # Sweep low
    closes[24] = 497.0  # Reclaimed above 495.0

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [10000] * 25},
        index=dates,
    )

    alert = detect_turtle_soup_sweep(
        symbol="NSE:TCS",
        df=df,
        ltp=497.0,
        vwap=500.0,
        exchange="NSE",
        rvol=1.5,
    )

    assert alert is not None
    assert alert.alert_type == "TURTLE_SOUP_SWEEP"
    assert alert.direction == "BULLISH"
    assert alert.stop_loss <= 493.5  # SL protected below the sweep wick
    assert alert.target_level >= 505.0  # Asymmetric target
    assert (alert.target_level - alert.trigger_level) / (
        alert.trigger_level - alert.stop_loss
    ) >= 2.0


def test_predatory_pipeline_6_seat_dossier_compilation(auditor: AlertScrutinyAuditor):
    """
    Predatory Execution Pipeline Invariant:
    Verifies that every alert passing scrutiny compiles and stamps the complete 6-seat dossier:
      🦅 EAGLE: Macro + Sector RRG alignment
      🐅 TIGER: Stalking phase + Kill Zone proximity
      🧠 CHANAKYA: De-trapping verification (wick rejection, OI walls, theta safety)
      🎯 SNIPER: Laser entry confirmation (R:R >= 1:2.5, no-chase limit)
      🐆 CHEETAH: Target 1 50% scale-out & Risk-Free SL ratchet mandate
      🐘 ELEPHANT: Institutional footprint (RVOL, Order Blocks, FVGs, POC clearance)
    """
    alert = AutoAlert(
        alert_id="aa-predatory-test-1",
        alert_type="BREAKOUT",
        stage="IGNITED",
        symbol="NSE:LT",
        exchange="NSE",
        direction="BULLISH",
        headline="Larsen & Toubro Institutional Breakout",
        summary="High conviction trend breakout",
        ltp=3600.0,
        trigger_level=3600.0,
        stop_loss=3540.0,  # 60 pts risk (1.67%)
        target_level=3780.0,  # 180 pts reward (3.0R)
        time_horizon="INTRADAY",
        is_live=True,
        environment="LIVE",
        metrics={
            "atr": 45.0,
            "chop_index": 35.0,  # Trending expansion
            "adx_14": 28.0,  # Trending
            "rvol": 2.2,  # RVOL >= 2.0x institutional thrust
            "order_block": True,
            "fvg": True,
            "upper_wick_ratio": 0.15,  # Clean candle (<40%)
            "nifty_change_pct": 0.45,  # Eagle macro aligned
            "sector_rrg_phase": "LEADING",
        },
    )

    scrutiny = auditor.scrutinize_alert(alert)
    assert scrutiny.status in ("APPROVED", "QUANT_VERIFIED")

    # Verify that alert.metrics contains predatory_pipeline
    pipeline = alert.metrics.get("predatory_pipeline")
    assert pipeline is not None
    assert pipeline["status"] == "APPROVED_PREDATORY_SANCTIONED"

    # 1. 🦅 EAGLE
    assert pipeline["eagle"]["seat"] == "🦅 EAGLE"
    assert pipeline["eagle"]["status"] == "ALIGNED"
    assert pipeline["eagle"]["macro_aligned"] is True

    # 2. 🐅 TIGER
    assert pipeline["tiger"]["seat"] == "🐅 TIGER"
    assert pipeline["tiger"]["in_kill_zone"] is True
    assert pipeline["tiger"]["status"] == "KILL_ZONE_LOCKED"

    # 3. 🧠 CHANAKYA
    assert pipeline["chanakya"]["seat"] == "🧠 CHANAKYA"
    assert pipeline["chanakya"]["status"] == "DE_TRAPPED"
    assert pipeline["chanakya"]["theta_safe"] is True

    # 4. 🎯 SNIPER
    assert pipeline["sniper"]["seat"] == "🎯 SNIPER"
    assert pipeline["sniper"]["status"] == "LASER_ENTRY"
    assert pipeline["sniper"]["rr_ratio"] >= 2.5
    assert pipeline["sniper"]["no_chase_passed"] is True

    # 5. 🐆 CHEETAH
    assert pipeline["cheetah"]["seat"] == "🐆 CHEETAH"
    assert pipeline["cheetah"]["status"] == "FREE_ROLL_READY"
    assert pipeline["cheetah"]["mandate"] == "CHEETAH_POUNCE_MOMENTUM"

    # 6. 🐘 ELEPHANT
    assert pipeline["elephant"]["seat"] == "🐘 ELEPHANT"
    assert pipeline["elephant"]["status"] == "INSTITUTIONAL_FOOTPRINT"
    assert pipeline["elephant"]["rvol"] >= 2.0
    assert pipeline["elephant"]["has_order_block"] is True


def test_circuit_ceiling_veto_rejects_target_exceeding_upper_circuit():
    """Gate 21 must veto long alerts where Target 1 breaches the upper circuit band."""
    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-eq-tata-20261012",
        alert_type="INTRADAY_EQUITY",
        stage="IGNITED",
        symbol="TATAPOWER",
        exchange="NSE",
        segment="EQUITY",
        direction="BULLISH",
        headline="Tata Power Long Breakout",
        summary="High conviction test setup",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=245.0,
        target_level=265.0,  # > upper circuit 260.0
        confidence=88,
        metrics={
            "upper_circuit": 260.0,
            "lower_circuit": 225.0,
            "rvol": 2.2,
        },
    )

    scrutiny = auditor.scrutinize_alert(alert)
    assert scrutiny.status == "REJECTED"
    assert "Circuit Ceiling Veto" in scrutiny.rejection_reason
    assert "mathematically unreachable" in scrutiny.rejection_reason


def test_circuit_floor_veto_rejects_target_below_lower_circuit():
    """Gate 21 must veto short alerts where Target 1 breaches the lower circuit band."""
    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-eq-tata-short-20261012",
        alert_type="INTRADAY_EQUITY",
        stage="IGNITED",
        symbol="TATAPOWER",
        exchange="NSE",
        segment="EQUITY",
        direction="BEARISH",
        headline="Tata Power Short Breakdown",
        summary="High conviction test setup",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=255.0,
        target_level=230.0,  # < lower circuit 235.0
        confidence=88,
        metrics={
            "upper_circuit": 275.0,
            "lower_circuit": 235.0,
            "rvol": 2.2,
        },
    )

    scrutiny = auditor.scrutinize_alert(alert)
    assert scrutiny.status == "REJECTED"
    assert "Circuit Floor Veto" in scrutiny.rejection_reason
    assert "mathematically unreachable" in scrutiny.rejection_reason


def test_option_plan_free_roll_time_stop():
    """build_option_plan must configure time_stop_minutes in free_roll_plan and root dict."""
    from engine.trade_plan import build_option_plan, create_trade_plan

    # 1. Index contract (NIFTY) -> 25 mins time stop
    tp_index = create_trade_plan("NIFTY", spot=25000.0, direction="BUY")
    opt_index = build_option_plan(
        contract_symbol="NIFTY26OCT25000CE",
        option_type="CE",
        strike=25000.0,
        expiry="2026-10-29",
        option_ltp=150.0,
        trade_plan=tp_index,
    )
    assert opt_index["time_stop_minutes"] == 25
    assert opt_index["free_roll_plan"]["time_stop_minutes"] == 25
    assert "25m if stagnation occurs" in opt_index["free_roll_plan"]["protocol_summary"]

    # 2. Equity contract (RELIANCE) -> 35 mins time stop
    tp_eq = create_trade_plan("RELIANCE", spot=3000.0, direction="BUY")
    opt_eq = build_option_plan(
        contract_symbol="RELIANCE26OCT3000CE",
        option_type="CE",
        strike=3000.0,
        expiry="2026-10-29",
        option_ltp=65.0,
        trade_plan=tp_eq,
    )
    assert opt_eq["time_stop_minutes"] == 35
    assert opt_eq["free_roll_plan"]["time_stop_minutes"] == 35
    assert "35m if stagnation occurs" in opt_eq["free_roll_plan"]["protocol_summary"]
