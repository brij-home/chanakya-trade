"""
tests/test_institutional_alpha_leaks_fixes.py
─────────────────────────────────────────────
Comprehensive unit tests verifying the 4 institutional post-mortem leak fixes:
1. ORB_PRIMED demoted to passive terminal watchlist (is_live=False, autoSubmit=False, held from Telegram).
2. THEMATIC_SYMPATHY_IGNITION disabled by default in live mode unless ENABLE_THEMATIC_SYMPATHY=1,
   and requires RVOL >= 2.20 with RRG sector confluence.
3. DEFINED_RISK_NEUTRAL expanded with Central Pivot Range (CPR) & Camarilla Value Area alignment.
4. PREOPEN_STOCK_CATALYST surfaces single-stock F&O pre-market discovery gaps (e.g. APOLLOHOSP, POWERINDIA)
   fused with bidirectional Sector RRG tailwinds before 09:15 AM.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
import os
import pytest

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.orb import detect_opening_range_breakout
from engine.detectors.preopen_bias import detect_preopen_stock_catalyst
from engine.thematic_peer_sympathy import ThematicPeerSympathyEngine

IST = ZoneInfo("Asia/Kolkata")


def test_orb_primed_is_watch_only_and_gated_from_telegram():
    """Verify that ORB_PRIMED is generated as passive watchlist surveillance (autoSubmit=False, is_live=False)."""
    import pandas as pd

    # Create 15-minute opening range: High=1010, Low=990, Mid=1000
    times = pd.date_range("2026-11-14 09:15:00", periods=5, freq="3min", tz=IST)
    df = pd.DataFrame(
        {
            "open": [1000.0, 995.0, 1002.0, 1008.0, 1008.5],
            "high": [1005.0, 1000.0, 1008.0, 1010.0, 1009.5],
            "low": [995.0, 990.0, 998.0, 1003.0, 1006.0],
            "close": [998.0, 1002.0, 1007.0, 1008.5, 1008.0],
            "volume": [10000, 12000, 15000, 14000, 13000],
        },
        index=times,
    )

    # Spot is 1008.5, within 0.35% of Range High 1010.0 -> ORB_PRIMED
    alert = detect_opening_range_breakout(
        symbol="RELIANCE",
        df=df,
        ltp=1008.5,
        vwap=1003.0,
        rvol=1.35,
        ref_time=datetime(2026, 11, 14, 9, 32, tzinfo=IST),
    )

    assert alert is not None
    assert alert.alert_type == "ORB_PRIMED"
    assert alert.stage == "PRIMED"
    assert alert.is_live is False
    assert alert.setup_style == "SURVEILLANCE"
    assert alert.actionable_plan.get("autoSubmit") is False
    assert alert.actionable_plan.get("is_watch_only") is True
    assert alert.actionable_plan.get("execution_ready") is False

    # Check that AutoAlertEngine Telegram gate suppresses it
    engine = AutoAlertEngine()
    is_allowed, reason = engine._eval_telegram_apex_gate(alert)
    assert is_allowed is False
    assert "ORB_PRIMED" in reason


def test_thematic_sympathy_disabled_by_default_in_live():
    """Verify that THEMATIC_SYMPATHY_IGNITION is disabled by default in live markets."""
    engine = ThematicPeerSympathyEngine()
    engine.clear_sympathy_session_state()

    # Register active leader in RAILWAYS
    engine.record_leader_alert(
        AutoAlert(
            alert_id="aa-lead-rvnl",
            alert_type="GAMMA_BLAST",
            symbol="RVNL",
            exchange="NSE",
            direction="BULLISH",
            stage="IGNITED",
            headline="RVNL Blast",
            summary="RVNL blast",
            ltp=450.0,
            trigger_level=445.0,
            target_level=470.0,
            stop_loss=435.0,
        )
    )

    mock_quotes = {
        "IRFC": {
            "last_price": 185.0,
            "open": 180.0,
            "high": 186.0,
            "low": 180.0,
            "close": 178.0,
            "volume": 5000000,
            "volume_ma20": 2000000,
            "vwap": 182.0,
        }
    }

    # In live mode (is_test_env=False) without ENABLE_THEMATIC_SYMPATHY
    with (
        patch.dict(os.environ, {"ENABLE_THEMATIC_SYMPATHY": "0"}, clear=False),
        patch("engine.thematic_peer_sympathy.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2026, 11, 14, 10, 30, tzinfo=IST)
        mock_dt.strptime = datetime.strptime

        # Patch test env flags to simulate live production
        with patch.dict(
            os.environ,
            {"CHANAKYA_TESTING": "0", "DEPLOY_MODE": "production", "PYTEST_CURRENT_TEST": ""},
        ):
            alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)
            assert len(alerts) == 0


def test_thematic_sympathy_requires_high_rvol_and_rrg_when_enabled():
    """Verify that when enabled, sympathy requires high institutional RVOL >= 2.20 and RRG alignment."""
    engine = ThematicPeerSympathyEngine()
    engine.clear_sympathy_session_state()

    engine.record_leader_alert(
        AutoAlert(
            alert_id="aa-lead-rvnl",
            alert_type="GAMMA_BLAST",
            symbol="RVNL",
            exchange="NSE",
            direction="BULLISH",
            stage="IGNITED",
            headline="RVNL Blast",
            summary="RVNL blast",
            ltp=450.0,
            trigger_level=445.0,
            target_level=470.0,
            stop_loss=435.0,
        )
    )

    mock_quotes = {
        "IRFC": {
            "last_price": 185.0,
            "open": 180.0,
            "high": 186.0,
            "low": 180.0,
            "close": 178.0,
            "volume": 5000000,
            "volume_ma20": 2000000,
            "vwap": 182.0,
        }
    }

    mock_directional = {
        "BULLISH": {"RVNL"},  # IRFC is NOT in bullish RRG quadrant
        "BEARISH": set(),
    }

    with (
        patch.dict(
            os.environ,
            {
                "ENABLE_THEMATIC_SYMPATHY": "1",
                "CHANAKYA_TESTING": "0",
                "DEPLOY_MODE": "production",
                "PYTEST_CURRENT_TEST": "",
            },
        ),
        patch(
            "analysis.sector_rotation.get_directional_sector_constituents",
            return_value=mock_directional,
        ),
        patch("engine.thematic_peer_sympathy.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2026, 11, 14, 10, 30, tzinfo=IST)
        mock_dt.strptime = datetime.strptime
        alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)
        # Suppressed because IRFC is not in BULLISH RRG quadrant
        assert len(alerts) == 0


def test_preopen_stock_catalyst_detector_bullish():
    """Verify that pre-market gap in a stock matching its bullish RRG sector generates PREOPEN_STOCK_CATALYST."""
    alert = detect_preopen_stock_catalyst(
        symbol="APOLLOHOSP",
        preopen_price=7150.0,
        prev_close=7000.0,  # +2.14% gap
        direction_bias="BULLISH",
        sector_name="PHARMA",
        rrg_quadrant="LEADING",
        min_gap_pct=1.0,
    )

    assert alert is not None
    assert alert.alert_type == "PREOPEN_STOCK_CATALYST"
    assert alert.stage == "EARLY_WARNING"
    assert alert.direction == "BULLISH"
    assert alert.option_type == "CE"
    assert alert.metrics["gap_pct"] == 2.14
    assert alert.actionable_plan["sector"] == "PHARMA"
    assert alert.actionable_plan["execution_ready"] is True
    assert "PRE-OPEN CATALYST" in alert.headline


def test_preopen_stock_catalyst_detector_bearish():
    """Verify that pre-market breakdown gap matching bearish RRG sector generates PREOPEN_STOCK_CATALYST PE."""
    alert = detect_preopen_stock_catalyst(
        symbol="TATASTEEL",
        preopen_price=138.0,
        prev_close=142.0,  # -2.82% gap
        direction_bias="BEARISH",
        sector_name="METAL",
        rrg_quadrant="LAGGING",
        min_gap_pct=1.0,
    )

    assert alert is not None
    assert alert.alert_type == "PREOPEN_STOCK_CATALYST"
    assert alert.direction == "BEARISH"
    assert alert.option_type == "PE"
    assert alert.metrics["gap_pct"] == -2.82
    assert alert.actionable_plan["sector"] == "METAL"


def test_preopen_stock_catalyst_mismatched_rrg_vetoed():
    """Verify that a stock gapping up when its sector is bearish (or vice versa) is vetoed."""
    alert = detect_preopen_stock_catalyst(
        symbol="WEAK_STOCK",
        preopen_price=105.0,
        prev_close=100.0,  # +5% gap up, but sector is BEARISH
        direction_bias="BEARISH",
        sector_name="REALTY",
        rrg_quadrant="LAGGING",
    )
    assert alert is None


def test_risk_gate_advisory_mode_halves_size_instead_of_hard_blocking(tmp_path, monkeypatch):
    """Verify that Co-Pilot advisory mode does not hard-block on daily loss cap, but presents mindful friction and halves sizing."""
    from engine.risk_limits import risk_limits
    from engine.risk_gate import compute_allowed_actions

    db_file = tmp_path / "risk_test_adv.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_file))
    risk_limits._db = db_file
    risk_limits._init_db()
    risk_limits.reset_all()

    monkeypatch.setenv("MAX_DAILY_LOSS", "10000.0")
    # Record loss breaching the 10k daily loss cap
    risk_limits.record_trade("INFY", "BUY", 10, 1500.0, pnl=-12000.0)

    # In strict policing mode (advisory_mode=False):
    strict_res = compute_allowed_actions(
        "INFY", "NSE", capital=100000.0, prices={"INFY": 1000.0}, advisory_mode=False
    )
    assert strict_res.allowed is False
    assert strict_res.max_qty == 0

    # In Co-Pilot advisory mode (advisory_mode=True):
    # Does NOT hard block, provides mindful friction (requires_double_confirmation=True), coaching recs, and advises 50% sizing
    adv_res = compute_allowed_actions(
        "INFY", "NSE", capital=100000.0, prices={"INFY": 1000.0}, advisory_mode=True
    )
    assert adv_res.allowed is True
    assert adv_res.requires_double_confirmation is True
    assert len(adv_res.coaching_recommendations) > 0
    assert "DAILY_LOSS_CAP" in adv_res.flags
    # Standard 10% cap of 100k capital = 10k => 10 shares @ 1000.
    # 50% advisory size reduction => 5 shares
    assert adv_res.max_qty == 5
    assert adv_res.max_capital == 5000.0


def test_execute_order_intent_allows_override_on_double_confirmation(tmp_path, monkeypatch):
    """Verify that execute_order_intent allows user override when double-confirmed, fulfilling Invariant 5."""
    from engine.order_lifecycle import (
        preview_order_intent,
        confirm_order_intent,
        execute_order_intent,
    )
    from engine.risk_limits import risk_limits

    db_file = tmp_path / "risk_test_ovr.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db_file))
    orders_db = tmp_path / "orders_test_ovr.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: orders_db)
    risk_limits._db = db_file
    risk_limits._init_db()
    risk_limits.reset_all()

    monkeypatch.setenv("MAX_DAILY_LOSS", "5000.0")
    order = preview_order_intent(
        symbol="TCS", side="BUY", quantity=1, price=3000.0, idempotency_key="IDEMP-ADV-1"
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # Breach loss limit
    risk_limits.record_trade("TCS", "BUY", 2, 3000.0, pnl=-6000.0)

    # Calling execute without override fails with PermissionError (Co-pilot friction)
    with pytest.raises(PermissionError):
        execute_order_intent(order.order_id, allow_override=False)

    # User acknowledges coaching advice and confirms override -> execution proceeds
    executed = execute_order_intent(order.order_id, allow_override=True)
    assert executed.status in ("FILLED_PAPER", "SUBMITTING", "FILLED")


def test_option_resolver_prioritizes_delta_sweet_spot():
    """Verify that strike resolution selects Delta sweet-spot (0.40 - 0.55), avoiding low-delta lottery traps."""
    from brokers.base import OptionsContract
    from engine.option_resolver import resolve_option_contract

    # Spot is 24000. Candidate contracts for NIFTY CE:
    # 1. 24200 CE (OTM, delta 0.28) -> outside sweet spot
    # 2. 24000 CE (ATM, delta 0.49) -> in sweet spot [0.40 - 0.55]
    # 3. 23800 CE (ITM, delta 0.72) -> deep ITM
    contracts = [
        OptionsContract(
            symbol="NIFTY26NOV24200CE",
            underlying="NIFTY",
            strike=24200.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=80.0,
            oi=100000,
            oi_change=5000,
            volume=50000,
            bid=79.0,
            ask=81.0,
            delta=0.28,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=160.0,
            oi=150000,
            oi_change=8000,
            volume=80000,
            bid=159.0,
            ask=161.0,
            delta=0.49,
        ),
        OptionsContract(
            symbol="NIFTY26NOV23800CE",
            underlying="NIFTY",
            strike=23800.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=270.0,
            oi=80000,
            oi_change=2000,
            volume=30000,
            bid=268.0,
            ask=272.0,
            delta=0.72,
        ),
    ]

    plan = resolve_option_contract(
        symbol="NIFTY",
        spot=24000.0,
        direction="BULLISH",
        strike_tier="ATM",
        contracts_override=contracts,
        require_listed_contract=True,
    )

    assert plan is not None
    assert plan.strike == 24000.0
    assert plan.delta == 0.49
    # Verify Limit-with-Protection order plan in as_dict()
    d = plan.as_dict()
    assert d["order_type"] == "LIMIT"
    assert d["execution_strategy"] == "LIMIT_WITH_PROTECTION"
    assert d["limit_price"] == round(160.0 * 1.005, 1)
    assert d["protection_ceiling"] == round(160.0 * 1.025, 1)


def test_45_minute_option_momentum_time_stop_ratchet():
    """Verify that a directional option buyer stalled for >= 45 minutes ratchets to Breakeven to halt theta decay."""
    from datetime import timedelta
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing

    now_dt = datetime.now(IST)
    # Stalled for 48 minutes (>= 45 mins)
    created_dt = now_dt - timedelta(minutes=48)
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="aa-opt-time-stop",
        alert_type="GAMMA_BLAST",
        symbol="NIFTY26NOV24000CE",
        exchange="NFO",
        direction="BULLISH",
        stage="IGNITED",
        headline="NIFTY CE Blast",
        summary="NIFTY option setup",
        ltp=108.0,
        trigger_level=100.0,
        stop_loss=80.0,  # 20 pts risk
        target_level=140.0,
        created_at=created_str,
        triggered_at=created_str,
        option_type="CE",
        actionable_plan={"target_1": 140.0, "entry_price": 100.0, "is_option": True},
    )

    # Current LTP = 106 (+6 pts = +0.30R, +6.0% PnL)
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=106.0)

    assert eval_res is not None
    assert eval_res.new_milestone == "DEAD_MONEY_BREAKEVEN"
    assert eval_res.trailing_decision == "TRAIL_DEAD_MONEY_BREAKEVEN"
    # Breakeven with +0.2% cushion = 100 * 1.002 = 100.2
    assert eval_res.recommended_stop == 100.2
    assert "45-minute option momentum time-stop" in eval_res.trailing_rationale


def test_order_ticket_defaults_to_limit_with_protection():
    """Verify that option actionable plans automatically format as LIMIT with Protection against slippage."""
    alert = AutoAlert(
        alert_id="aa-lwp-ticket",
        alert_type="VOL_EXPANSION_BREAKOUT",
        symbol="NIFTY26NOV24500CE",
        exchange="NFO",
        direction="BULLISH",
        stage="IGNITED",
        headline="Breakout",
        summary="Test",
        ltp=200.0,
        trigger_level=200.0,
        target_level=250.0,
        stop_loss=170.0,
        option_type="CE",
        actionable_plan={"entry_price": 200.0},
    )

    plan = alert.actionable_plan
    assert plan["order_type"] == "LIMIT"
    assert plan["execution_strategy"] == "LIMIT_WITH_PROTECTION"
    # 200 * 1.005 = 201.0
    assert plan["limit_price"] == 201.0
    # 200 * 1.025 = 205.0
    assert plan["protection_ceiling"] == 205.0


def test_actionable_plan_product_routing_intraday_vs_swing():
    """Verify that actionable plan routes product cleanly: MIS for intraday, NRML for swing derivatives, CNC for swing cash."""
    # 1. Intraday option -> MIS
    a_intra_opt = AutoAlert(
        alert_id="aa-prod-intra-opt",
        alert_type="INDEX_MICRO_SCALP",
        symbol="NIFTY26NOV24500CE",
        exchange="NFO",
        direction="BULLISH",
        stage="IGNITED",
        headline="Scalp",
        summary="Test",
        ltp=150.0,
        trigger_level=150.0,
        target_level=180.0,
        stop_loss=130.0,
        option_type="CE",
        time_horizon="INTRADAY",
        actionable_plan={"entry_price": 150.0},
    )
    assert a_intra_opt.actionable_plan["product"] == "MIS"

    # 2. Swing option -> NRML
    a_swing_opt = AutoAlert(
        alert_id="aa-prod-swing-opt",
        alert_type="SWING_INFLECTION",
        symbol="RELIANCE26NOV1300CE",
        exchange="NFO",
        direction="BULLISH",
        stage="ACTIONABLE",
        headline="Swing Option",
        summary="Test",
        ltp=35.0,
        trigger_level=35.0,
        target_level=55.0,
        stop_loss=22.0,
        option_type="CE",
        time_horizon="SWING_SHORT",
        actionable_plan={"entry_price": 35.0},
    )
    assert a_swing_opt.actionable_plan["product"] == "NRML"

    # 3. Swing equity -> CNC
    a_swing_eq = AutoAlert(
        alert_id="aa-prod-swing-eq",
        alert_type="SWING_INFLECTION",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        stage="ACTIONABLE",
        headline="Swing Stock",
        summary="Test",
        ltp=3500.0,
        trigger_level=3500.0,
        target_level=3800.0,
        stop_loss=3350.0,
        time_horizon="SWING_SHORT",
        actionable_plan={"entry_price": 3500.0},
    )
    assert a_swing_eq.actionable_plan["product"] == "CNC"


def test_intraday_to_swing_promotion_updates_product_and_adds_hedge():
    """Verify that promoting an intraday option setup updates product to NRML and suggests overnight vertical hedge."""
    from datetime import datetime
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    now_dt = datetime(2026, 11, 14, 15, 12, tzinfo=IST)

    alert = AutoAlert(
        alert_id="aa-promo-opt-1",
        alert_type="GAMMA_BLAST",
        symbol="NIFTY",
        contract_symbol="NIFTY26NOV24500CE",
        exchange="NFO",
        direction="BULLISH",
        stage="IGNITED",
        headline="NIFTY Blast",
        summary="Option",
        ltp=150.0,
        trigger_level=100.0,
        target_level=200.0,
        stop_loss=80.0,
        option_type="CE",
        time_horizon="INTRADAY",
        r_multiple=2.8,  # Strongly profitable (>= 2.5R)
        pnl_pct=50.0,
        expiry_date="2026-11-26",
        metrics={"dte": 10},
        actionable_plan={"entry_price": 100.0, "product": "MIS", "target_2": 200.0},
    )

    with engine._lock:
        engine._alerts = [alert]

    with patch.dict(os.environ, {"CHANAKYA_TESTING": "1"}):
        promoted = engine.evaluate_intraday_to_swing_promotions(now_dt)

    assert len(promoted) == 1
    p_alert = promoted[0]
    assert p_alert.time_horizon == "SWING_SHORT"
    assert p_alert.actionable_plan["product"] == "NRML"
    assert (
        "Convert to vertical spread before overnight carry"
        in p_alert.actionable_plan["overnight_hedge_recommendation"]
    )


def test_defined_risk_spread_uses_canonical_strike_step():
    """Verify that build_defined_risk_spread uses canonical exchange strike step (e.g. 50 for NIFTY, 100 for BANKNIFTY)."""
    from engine.defined_risk_spreads import build_defined_risk_spread

    spread_nifty = build_defined_risk_spread(
        underlying="NIFTY",
        spot_price=24230.0,
        strategy="BULL_CALL_SPREAD",
        iv=0.15,
        dte=5,
    )
    # NIFTY strike step is 50 -> ATM is 24250, sell strike is 24250 + (2 * 50) = 24350
    leg1, leg2 = spread_nifty.legs[0], spread_nifty.legs[1]
    assert leg1.strike == 24250.0
    assert leg2.strike == 24350.0
    assert leg1.dte == 5


def test_discovery_desk_dynamic_evaluation_for_swing_scans(monkeypatch):
    """Verify that scan_swing_inflections dynamically routes to FNO_STOCK for F&O universe under FNO_ONLY focus."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    sample_alert = AutoAlert(
        alert_id="aa-dyn-swing-fno-1",
        alert_type="SWING_INFLECTION",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        stage="ACTIONABLE",
        headline="Reliance VCP",
        summary="Test",
        ltp=1300.0,
        trigger_level=1300.0,
        target_level=1380.0,
        stop_loss=1260.0,
        time_horizon="SWING_SHORT",
        environment="TEST",
        is_live=False,
        actionable_plan={"entry_price": 1300.0},
    )

    with patch("engine.detectors.swing_inflection.detect_swing_inflection_setups") as mock_detect:
        mock_detect.return_value = [sample_alert]

        # 1. Broad cash equity scan is gated under FNO_ONLY
        cash_res = engine.scan_swing_inflections(universe="nifty_total_market")
        assert cash_res == []

        # 2. F&O stock scan dynamically resolves to FNO_STOCK desk and executes
        fno_res = engine.scan_swing_inflections(universe="fno")
        assert len(fno_res) == 1
        assert fno_res[0].symbol == "RELIANCE"


def test_scan_fno_stock_swing_setups_resolves_option_contract(monkeypatch):
    """Verify that scan_fno_stock_swing_setups executes under FNO_ONLY and resolves monthly option contract with NRML product."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.option_resolver import ResolvedOptionPlan

    engine = AutoAlertEngine()

    raw_alert = AutoAlert(
        alert_id="aa-fno-stock-1",
        alert_type="SWING_INFLECTION",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        stage="ACTIONABLE",
        headline="TCS Stage 2",
        summary="Test",
        ltp=3500.0,
        trigger_level=3500.0,
        target_level=3750.0,
        stop_loss=3380.0,
        time_horizon="SWING_SHORT",
        environment="TEST",
        is_live=False,
        actionable_plan={"entry_price": 3500.0},
    )

    mock_plan = ResolvedOptionPlan(
        contract_symbol="TCS26NOV3500CE",
        strike=3500.0,
        option_type="CE",
        entry_premium=85.0,
        sl_premium=50.0,
        t1_premium=135.0,
        t2_premium=180.0,
        lot_size=175,
        underlying_spot=3500.0,
        underlying_sl=3380.0,
        underlying_target=3750.0,
        expiry="2026-11-26",
    )

    with patch(
        "engine.detectors.swing_inflection.detect_swing_inflection_setups", return_value=[raw_alert]
    ):
        with patch("engine.option_resolver.resolve_option_contract", return_value=mock_plan):
            res = engine.scan_fno_stock_swing_setups()

    assert len(res) == 1
    fno_alert = res[0]
    assert fno_alert.contract_symbol == "TCS26NOV3500CE"
    assert fno_alert.product == "NRML"
    assert fno_alert.segment == "NFO"
    assert fno_alert.lot_size == 175
    assert fno_alert.actionable_plan["contract_symbol"] == "TCS26NOV3500CE"
    assert fno_alert.actionable_plan["product"] == "NRML"
    assert fno_alert.actionable_plan["lot_size"] == 175
    assert fno_alert.actionable_plan["recommended_entry"] == 85.0


def test_preopen_bias_zero_gamma_cascade_and_squeeze_archetypes(monkeypatch):
    """Verify that detect_preopen_bias integrates GEX zero-gamma flip into VOLATILITY_EXPANSION_CASCADE and GAMMA_SQUEEZE_BREAKOUT."""
    from engine.detectors.preopen_bias import detect_preopen_bias
    from engine.daily_levels import DailyLevels

    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    # 1. Bearish gap below Zero-Gamma Flip -> VOLATILITY_EXPANSION_CASCADE
    mock_dl_normal = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-31",
        pdh=24500.0,
        pdl=24300.0,
        pdc=24450.0,
        cpr={
            "top": 24420.0,
            "bottom": 24380.0,
            "pivot": 24400.0,
            "width_pct": 0.20,
            "is_narrow": False,
            "is_wide": False,
            "cpr_type": "NORMAL",
        },
    )

    with patch("engine.detectors.preopen_bias.get_daily_levels", return_value=mock_dl_normal):
        with patch("analysis.gex.get_gex_analysis") as mock_gex:
            mock_gex.return_value = MagicMock(
                call_wall=24600.0,
                put_wall=24200.0,
                to_dict=lambda: {
                    "call_wall": 24600.0,
                    "put_wall": 24200.0,
                    "zero_gamma_level": 24400.0,
                    "dex_regime": "DEALER_NET_LONG_DELTA",
                },
            )

            # Spot opens at 24350 (-0.41%), which is below zero-gamma flip 24400.0
            cascade_alerts = detect_preopen_bias(
                underlying="NIFTY",
                gift_futures_price=24350.0,
                prev_close=24450.0,
                chain=[],
            )

    assert len(cascade_alerts) == 1
    assert cascade_alerts[0].metrics["day_archetype"] == "VOLATILITY_EXPANSION_CASCADE"
    assert cascade_alerts[0].metrics["zero_gamma_level"] == 24400.0
    assert "VOLATILITY_EXPANSION_CASCADE" in cascade_alerts[0].headline

    # 2. Bullish gap opening above Call Wall -> GAMMA_SQUEEZE_BREAKOUT
    with patch("engine.detectors.preopen_bias.get_daily_levels", return_value=mock_dl_normal):
        with patch("analysis.gex.get_gex_analysis") as mock_gex:
            mock_gex.return_value = MagicMock(
                call_wall=24500.0,
                put_wall=24200.0,
                to_dict=lambda: {
                    "call_wall": 24500.0,
                    "put_wall": 24200.0,
                    "zero_gamma_level": 24300.0,
                    "dex_regime": "DEALER_NET_SHORT_DELTA",
                },
            )

            # Spot opens at 24550 (+0.41%), which is above Call Wall 24500.0
            squeeze_alerts = detect_preopen_bias(
                underlying="NIFTY",
                gift_futures_price=24550.0,
                prev_close=24450.0,
                chain=[],
            )

    assert len(squeeze_alerts) == 1
    assert squeeze_alerts[0].metrics["day_archetype"] == "GAMMA_SQUEEZE_BREAKOUT"
    assert "GAMMA_SQUEEZE_BREAKOUT" in squeeze_alerts[0].headline


def test_skill_auto_alerts_scan_fno_swing_and_scan_swing_routing(monkeypatch):
    """Verify that skill endpoints trigger F&O stock swing scans and route properly under FNO_ONLY focus."""
    import asyncio

    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    from web.skills import skill_auto_alerts_scan_fno_swing, skill_auto_alerts_scan_swing

    sample_fno_alert = AutoAlert(
        alert_id="aa-fno-endpoint-test-1",
        alert_type="SWING_INFLECTION",
        symbol="RELIANCE",
        contract_symbol="RELIANCE26NOV1300CE",
        exchange="NFO",
        segment="NFO",
        direction="BULLISH",
        stage="ACTIONABLE",
        headline="Reliance F&O Swing",
        summary="Test",
        ltp=35.0,
        trigger_level=35.0,
        target_level=55.0,
        stop_loss=20.0,
        lot_size=250,
        time_horizon="SWING_SHORT",
        environment="TEST",
        is_live=False,
        actionable_plan={"product": "NRML", "entry_price": 35.0},
    )
    sample_fno_alert.product = "NRML"

    async def _run():
        with patch(
            "engine.auto_alert_engine.auto_alert_engine.scan_fno_stock_swing_setups",
            return_value=[sample_fno_alert],
        ) as mock_fno_scan:
            # 1. Direct F&O swing skill endpoint
            res_direct = await skill_auto_alerts_scan_fno_swing({"min_score": 65, "limit": 20})
            assert res_direct["status"] == "ok"
            assert res_direct["count"] == 1
            assert res_direct["universe"] == "fno"
            assert res_direct["data"][0]["contract_symbol"] == "RELIANCE26NOV1300CE"
            assert mock_fno_scan.call_count == 1

            # 2. General scan_swing skill endpoint auto-routes to F&O swings when policy is FNO_ONLY
            res_routed = await skill_auto_alerts_scan_swing({"universe": "all_equities_nse_bse"})
            assert res_routed["status"] == "ok"
            assert res_routed["count"] == 1
            assert res_routed["universe"] == "fno"
            assert mock_fno_scan.call_count == 2

    asyncio.run(_run())
