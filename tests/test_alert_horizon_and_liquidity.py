"""
tests/test_alert_horizon_and_liquidity.py
──────────────────────────────────────────
Unit tests for:
  1. Intraday auto-expiry at 15:15 IST (and 23:15 for MCX).
  2. Unignited setup time-stop invalidation (60-minute window).
  3. Real-time options liquidity watchdog (spread %, OI floor, slippage risk).
  4. Dynamic Strike Rolling recommendations upon reaching T2 and Final Target.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.alert_evaluator import (
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
    calculate_strike_roll_recommendation,
)
from market.options import audit_option_liquidity

IST = ZoneInfo("Asia/Kolkata")


def test_intraday_alert_auto_expires_at_session_cutoff():
    """Verify that INTRADAY alerts automatically expire past 15:15 IST same day or from a prior date."""
    now = datetime.now(IST)

    # 1. Alert created on prior calendar date must be expired immediately
    yesterday = now - timedelta(days=1)
    alert_yesterday = AutoAlert(
        alert_id="test-prior-date-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Surge",
        summary="Testing prior day expiration",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=yesterday.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    alert_yesterday._force_test_expiry = True
    assert alert_yesterday.is_expired is True

    # 2. Alert created today with time 15:20 IST must expire if now is after 15:15
    alert_today = AutoAlert(
        alert_id="test-today-cutoff-002",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Surge",
        summary="Testing today session cutoff",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=now.strftime("%Y-%m-%d 10:00:00 IST"),
    )
    alert_today._force_test_expiry = True
    if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
        assert alert_today.is_expired is True


def test_intraday_alert_invalidation_at_cutoff():
    """Verify evaluate_alert_invalidation returns session cutoff message for intraday trades."""
    now = datetime.now(IST)
    past_date = now - timedelta(days=1)

    alert = AutoAlert(
        alert_id="test-inval-cutoff-003",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma",
        summary="Testing cutoff invalidation",
        ltp=150.0,
        trigger_level=145.0,
        target_level=200.0,
        stop_loss=120.0,
        time_horizon="INTRADAY",
        created_at=past_date.strftime("%Y-%m-%d 11:00:00 IST"),
    )
    alert._force_test_expiry = True
    reason = evaluate_alert_invalidation(alert, current_ltp=152.0)
    assert reason is not None
    assert "Intraday session expired" in reason
    assert "15:15 IST cutoff reached" in reason


def test_unignited_early_warning_time_stop():
    """Verify that unignited EARLY_WARNING setups expire after 60 minutes."""
    now = datetime.now(IST)
    old_time = now - timedelta(minutes=75)

    alert = AutoAlert(
        alert_id="test-timestop-004",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Coiling",
        summary="Compression base",
        ltp=2500.0,
        trigger_level=2520.0,
        target_level=2600.0,
        stop_loss=2480.0,
        time_horizon="INTRADAY",
        ttl_seconds=3600,
        created_at=old_time.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    alert._force_test_expiry = True
    reason = evaluate_alert_invalidation(alert, current_ltp=2505.0)
    assert reason is not None
    assert "Time-Stop expired" in reason
    assert "60-minute momentum window" in reason


def test_options_liquidity_audit():
    """Verify audit_option_liquidity detects optimal vs wide spreads and flags slippage risks."""
    # 1. Optimal tight spread: LTP 120, Bid 119.80, Ask 120.20 (Spread = 0.33%)
    tight_contract = {
        "ltp": 120.0,
        "bid": 119.80,
        "ask": 120.20,
        "oi": 35000,
        "volume": 12000,
    }
    audit_tight = audit_option_liquidity(tight_contract, underlying="NIFTY")
    assert audit_tight["is_liquid"] is True
    assert audit_tight["liquidity_status"] == "OPTIMAL"
    assert audit_tight["slippage_risk"] == "LOW"
    assert audit_tight["bid_ask_spread_pct"] < 1.0

    # 2. Wide spread caution: LTP 80, Bid 76.0, Ask 84.0 (Spread = 10%)
    wide_contract = {
        "ltp": 80.0,
        "bid": 76.0,
        "ask": 84.0,
        "oi": 15000,
        "volume": 2000,
    }
    audit_wide = audit_option_liquidity(wide_contract, underlying="NIFTY")
    assert audit_wide["liquidity_status"] == "WIDE_SPREAD_CAUTION"
    assert audit_wide["slippage_risk"] == "HIGH"
    assert audit_wide["bid_ask_spread_pct"] == 10.0
    assert "Wide bid-ask spread" in audit_wide["execution_warning"]

    # 3. Illiquid order book: missing bids/asks
    empty_book = {
        "ltp": 45.0,
        "bid": 0.0,
        "ask": 0.0,
        "oi": 100,
        "volume": 10,
    }
    audit_empty = audit_option_liquidity(empty_book, underlying="NIFTY")
    assert audit_empty["is_liquid"] is False
    assert audit_empty["liquidity_status"] == "ILLIQUID"


def test_strike_roll_recommendation_generation():
    """Verify calculate_strike_roll_recommendation suggests ATM roll when option reaches deep ITM."""
    alert = AutoAlert(
        alert_id="test-roll-005",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE",
        summary="Nifty Gamma Blast",
        ltp=120.0,
        trigger_level=120.0,
        target_level=220.0,
        stop_loss=90.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY2692425000CE",
        underlying_spot=25380.0,  # Spot moved up by 380 points! 25000 CE is deep ITM
    )

    roll = calculate_strike_roll_recommendation(
        alert=alert,
        current_ltp=360.0,
        pnl_pct=200.0,
        is_bullish=True,
    )
    assert roll is not None
    assert roll["action"] == "ROLL_UP"
    assert roll["current_strike"] == 25000.0
    # 25380 spot with 50-step rounds to 25400 ATM
    assert roll["recommended_strike"] == 25400.0
    assert "25400" in roll["recommended_contract"]
    assert "Roll up to liquid ATM 25400 CE" in roll["reason"]


def test_calculate_strike_roll_put_deep_itm_rolls_down():
    """Verify deep ITM Put rolls DOWN to ATM to lock gains and restore gamma leverage."""
    alert = AutoAlert(
        alert_id="test-roll-pe-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23000 PE",
        summary="Nifty Put Momentum",
        ltp=120.0,
        trigger_level=120.0,
        target_level=220.0,
        stop_loss=90.0,
        strike=23000.0,
        option_type="PE",
        contract_symbol="NIFTY2692423000PE",
        underlying_spot=22620.0,  # Spot fell by 380 points! 23000 PE is deep ITM
    )

    roll = calculate_strike_roll_recommendation(
        alert=alert,
        current_ltp=450.0,
        pnl_pct=275.0,
        is_bullish=False,
    )
    assert roll is not None
    assert roll["action"] == "ROLL_DOWN"
    assert roll["current_strike"] == 23000.0
    # 22620 spot with 50-step rounds to 22600 ATM
    assert roll["recommended_strike"] == 22600.0
    assert "22600" in roll["recommended_contract"]
    assert "Roll down to liquid ATM 22600 PE" in roll["reason"]


def test_calculate_strike_roll_otm_put_is_suppressed():
    """Verify OTM Put (strike < spot) does NOT recommend strike roll to lock ITM gains."""
    alert = AutoAlert(
        alert_id="test-roll-pe-otm",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 22550 PE",
        summary="Nifty Put Momentum",
        ltp=76.65,
        trigger_level=76.65,
        target_level=118.8,
        stop_loss=61.3,
        strike=22550.0,
        option_type="PE",
        contract_symbol="NIFTY2026100622550PE",
        underlying_spot=22704.65,  # Spot is ABOVE strike, so 22550 PE is OTM!
    )

    roll = calculate_strike_roll_recommendation(
        alert=alert,
        current_ltp=201.5,
        pnl_pct=162.9,
        is_bullish=False,
    )
    # Should be None because 22550 PE is OTM when spot is 22704
    assert roll is None


def test_calculate_strike_roll_otm_put_missing_spot_no_spurious_roll():
    """Regression: OTM PE with NO underlying_spot must NOT generate a spurious ROLL_UP.

    Before the operator-precedence fix (Bug 1), the fallback approximation
    ``spot = cur_strike - current_ltp`` was always executed when underlying_spot was
    missing (regardless of option_type).  For a small-premium OTM PE this produced
    a *lower* spot than the strike, making the OTM PE appear deep ITM and triggering
    a wrong ROLL_UP recommendation.
    """
    alert = AutoAlert(
        alert_id="test-roll-pe-missing-spot",
        alert_type="INDEX_PUT_SETUP",
        stage="TARGET_ACHIEVED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 22550 PE",
        summary="Nifty Put Setup",
        ltp=76.65,
        trigger_level=76.65,
        target_level=118.8,
        stop_loss=61.3,
        strike=22550.0,
        option_type="PE",
        contract_symbol="NIFTY2026100622550PE",
        underlying_spot=None,  # Deliberately missing — triggers the approximation path
    )

    roll = calculate_strike_roll_recommendation(
        alert=alert,
        current_ltp=201.5,  # premium = 201.5 / 22550 = 0.89% << 10% threshold
        pnl_pct=162.9,
        is_bullish=False,
    )
    # Must be None: premium < 10% of strike → not deep ITM confirmed → no spurious roll
    assert roll is None, (
        f"Expected None (OTM PE without underlying_spot must not generate a roll), got: {roll}"
    )


def test_opening_drive_ignition_ce_header_is_not_put_surge():
    """Regression: OPENING_DRIVE_IGNITION CE alert header must read 'OPENING DRIVE IGNITION',
    not 'OPTIONS PUT SURGE'.

    Before Bug 2 fix, the generic fallback ``opt_tag = 'OPTIONS PUT SURGE' if is_put else ...``
    could fire for OPENING_DRIVE_IGNITION alerts if option_type was missing, because the
    direction fallback incorrectly classified BULLISH CE as PUT SURGE.
    """
    from bot.alert_templates import format_auto_alert_telegram

    alert = AutoAlert(
        alert_id="aa-opening-drive-ignition-solarinds-bull-20260930",
        alert_type="OPENING_DRIVE_IGNITION",
        stage="IGNITED",
        symbol="SOLARINDS",
        exchange="NFO",
        direction="BULLISH",
        headline="SOLARINDS Bullish Ignition (Open==Low)",
        summary="Opening Drive confirmed CE call",
        ltp=700.0,
        trigger_level=700.0,
        target_level=945.0,
        stop_loss=546.0,
        strike=19750.0,
        option_type="CE",
        contract_symbol="SOLARINDS2026102719750CE",
        underlying_spot=19670.0,
        lot_size=50,
        confidence=92,
        environment="LIVE",
        is_live=True,
        metrics={},
    )

    msg = format_auto_alert_telegram(alert)
    # The header must contain OPENING DRIVE IGNITION, not OPTIONS PUT SURGE
    assert "OPENING DRIVE IGNITION" in msg, (
        f"Expected 'OPENING DRIVE IGNITION' in header for CE OPENING_DRIVE_IGNITION alert.\n"
        f"Got header section: {msg[:300]}"
    )
    assert "OPTIONS PUT SURGE" not in msg, (
        f"CE OPENING_DRIVE_IGNITION alert must never display 'OPTIONS PUT SURGE'.\nGot: {msg[:300]}"
    )


def test_evaluate_targets_and_trailing_attaches_strike_roll():
    """Verify evaluate_alert_targets_and_trailing attaches strike_roll_recommendation upon T2 / Final Hit."""
    alert = AutoAlert(
        alert_id="test-roll-t2-006",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Momentum",
        summary="Testing strike roll attachment",
        ltp=100.0,
        trigger_level=100.0,
        target_level=180.0,
        stop_loss=75.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY2692425000CE",
        underlying_spot=25350.0,
        actionable_plan={
            "recommended_entry": 100.0,
            "stop_loss": 75.0,
            "target_1": 135.0,
            "target_2": 175.0,
            "target_3": 230.0,
        },
    )

    # Simulate price reaching T2 (180.0)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=180.0)
    assert res is not None
    assert res.new_milestone in ("T2_ACHIEVED", "TARGET_ACHIEVED")
    assert res.should_roll_strike is True
    assert res.strike_roll_recommendation is not None
    assert res.strike_roll_recommendation["action"] == "ROLL_UP"
    assert res.strike_roll_recommendation["recommended_strike"] == 25350.0


def test_multibagger_and_eta_metadata_in_auto_alert_and_telegram():
    """Verify AutoAlert derives MULTIBAGGER + ETA and Telegram template places them at the bottom."""
    from bot.alert_templates import format_auto_alert_telegram

    alert = AutoAlert(
        alert_id="aa-mb-titagarh-20260927",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="IGNITED",
        symbol="TITAGARH",
        exchange="NSE",
        direction="BULLISH",
        headline="TITAGARH · Stage 2 Breakout",
        summary="Institutional accumulation and multibagger base breakout.",
        ltp=1150.0,
        trigger_level=1140.0,
        target_level=1450.0,
        stop_loss=1020.0,
        actionable_plan={
            "action": "BUY",
            "entry_range": "₹1,140–1,155",
            "stop_loss": "₹1,020.0",
            "target": "₹1,450.0",
            "target_2": "₹1,750.0",
            "risk_reward": "1:4.8",
            "profit_rule": "Scale 50% at T1, move SL to breakeven.",
        },
    )
    # 1. Verify AutoAlert auto-derivation
    assert alert.time_horizon == "MULTIBAGGER"
    assert alert.eta_label == "6–24 Months"
    assert alert.is_expired is False

    # 2. Verify Telegram formatting layout
    msg = format_auto_alert_telegram(alert)
    assert "MULTIBAGGER ALPHA" in msg
    assert "<b>Action:</b>" in msg
    assert "<b>SL:</b>" in msg
    assert "<b>T1:</b>" in msg

    # Verify Horizon & ETA are at the bottom:
    lines = [l for l in msg.strip().split("\n") if l.strip()]
    action_line_idx = next(i for i, line in enumerate(lines) if "<b>Action:</b>" in line)
    # Action line must appear in the top 5 lines for instant trader visibility
    assert action_line_idx <= 5

    # Horizon line must appear in the footer block (within the last 3 non-empty lines)
    horizon_line_idx = next(i for i, line in enumerate(lines) if "<b>Horizon:</b>" in line)
    assert horizon_line_idx >= len(lines) - 3
    assert "🚀 MULTIBAGGER" in lines[horizon_line_idx]
    assert "6–24 Months" in lines[horizon_line_idx]


def test_crypto_24x7_intraday_rolling_expiry():
    """Verify that 24x7 Crypto alerts do not expire past 15:15 IST and obey 24-hour rolling expiry."""
    now = datetime.now(IST)

    # 1. Crypto alert created 2 hours ago (even after 15:15 IST) must remain ACTIVE
    two_hours_ago = now - timedelta(hours=2)
    crypto_active = AutoAlert(
        alert_id="test-crypto-btcusdt-active",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="CRYPTO",
        segment="CRYPTO",
        direction="BULLISH",
        headline="BTCUSDT Order Block Reclaim",
        summary="Testing 24x7 crypto active state",
        ltp=85000.0,
        trigger_level=84500.0,
        target_level=89000.0,
        stop_loss=83200.0,
        time_horizon="INTRADAY",
        created_at=two_hours_ago.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    crypto_active._force_test_expiry = True
    assert crypto_active.eta_label == "24h Rolling"
    assert crypto_active.is_expired is False
    assert crypto_active.is_active is True

    # 2. Crypto alert created 25 hours ago (>24h rolling limit) must expire
    old_crypto = AutoAlert(
        alert_id="test-crypto-btcusdt-old",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="CRYPTO",
        segment="CRYPTO",
        direction="BULLISH",
        headline="BTCUSDT Expired Setup",
        summary="Testing 24h rolling window expiration",
        ltp=85000.0,
        trigger_level=84500.0,
        target_level=89000.0,
        stop_loss=83200.0,
        time_horizon="INTRADAY",
        created_at=(now - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    old_crypto._force_test_expiry = True
    assert old_crypto.is_expired is True
    assert old_crypto.is_active is False
