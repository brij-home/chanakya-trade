from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from market.calendar import is_trading_day
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor

IST = ZoneInfo("Asia/Kolkata")


def test_is_trading_day():
    """Verify is_trading_day logic for weekdays, weekends, and official holidays."""
    # Regular Thursday
    assert is_trading_day(date(2026, 10, 8), exchange="NSE") is True
    # Saturday
    assert is_trading_day(date(2026, 10, 10), exchange="NSE") is False
    # Sunday
    assert is_trading_day(date(2026, 10, 11), exchange="NSE") is False
    # Republic Day (Jan 26, 2025)
    assert is_trading_day(date(2025, 1, 26), exchange="NSE") is False
    # Holi (March 14, 2025)
    assert is_trading_day(date(2025, 3, 14), exchange="NSE") is False


def test_gated_detectors_include_all_breakouts():
    """Verify all major directional breakout detectors are included in is_gated."""
    import inspect
    from engine.auto_alert_engine import AutoAlertEngine

    src = inspect.getsource(AutoAlertEngine.record_alert)
    assert "STAGE_1_TO_2_EXPANSION" in src
    assert "PATTERN_COILING" in src
    assert "ORB_PRIMED" in src
    assert "INDEX_MICRO_SCALP" in src
    assert "ORB_BREAKDOWN" in src


def test_opening_auction_discovery_veto(monkeypatch):
    """Verify Opening Auction filter vetoes non-thrust breakouts between 09:15 and 09:25 IST."""
    monkeypatch.setenv("ENFORCE_OPENING_AUCTION_GATE", "1")

    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-stage-1-to-2-expansion-test-20261008",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="STALK",
        symbol="TESTSTOCK",
        exchange="NSE",
        direction="BULLISH",
        headline="Stage 1 to 2 Expansion Test",
        summary="Testing breakout",
        ltp=500.0,
        trigger_level=500.0,
        target_level=550.0,
        stop_loss=480.0,
        confidence=85,
        metrics={"rvol": 1.2, "is_institutional_thrust": False},
        created_at="2026-10-08 09:18:00 IST",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Opening Auction Discovery Veto" in reason
    assert flags.get("opening_auction_safe") is False

    # With institutional volume thrust (RVOL >= 2.0), opening breakout passes filter
    alert.metrics["rvol"] = 2.4
    passed2, _, flags2 = auditor.verify_tier1_sanity(alert)
    assert flags2.get("opening_auction_safe") is True


def test_gravitational_regime_veto_on_bear_trend_day():
    """Verify bullish breakouts are vetoed during severe NIFTY markdown unless verified decoupler."""
    auditor = AlertScrutinyAuditor()

    # Bullish setup during -1.5% NIFTY selloff
    alert = AutoAlert(
        alert_id="aa-stage-1-to-2-expansion-schneider-20261008",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="STALK",
        symbol="SCHNEIDER",
        exchange="NSE",
        direction="BULLISH",
        headline="Schneider Electric Breakout",
        summary="Stage 1 to 2 Expansion",
        ltp=1275.0,
        trigger_level=1275.0,
        target_level=1365.0,
        stop_loss=1230.0,
        confidence=85,
        metrics={
            "nifty_change_pct": -1.50,
            "nifty_below_vwap": True,
            "sector": "Infrastructure & Capital Goods",
            "spot_change_pct": 1.2,
            "rvol": 1.1,
            "sector_rs": -0.2,
        },
        created_at="2026-10-08 10:15:00 IST",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Benchmark Gravitational Veto" in reason
    assert flags.get("macro_regime_aligned") is False
    assert flags.get("benchmark_regime_valid") is False

    # Outperforming decoupler with genuine Sector RS (+1.2%) and high volume passes
    alert.metrics["sector_rs"] = 1.2
    alert.metrics["rvol"] = 2.5
    alert.metrics["spot_change_pct"] = 2.2
    passed2, _, flags2 = auditor.verify_tier1_sanity(alert)
    assert passed2 is True
    assert flags2.get("decoupler_status") == "VERIFIED_DECOUPLER"


def test_quant_fallback_vetoes_counter_trend_longs():
    """Verify QUANT_FALLBACK rejects bullish breakouts when Nifty is down >= -0.50%."""
    auditor = AlertScrutinyAuditor()
    alert = AutoAlert(
        alert_id="aa-pattern-coiling-gail-20261008",
        alert_type="PATTERN_COILING",
        stage="STALK",
        symbol="GAIL",
        exchange="NSE",
        direction="BULLISH",
        headline="GAIL Pattern Coiling",
        summary="Coiling base near highs",
        ltp=170.0,
        trigger_level=170.0,
        target_level=182.0,
        stop_loss=165.0,
        confidence=80,
        metrics={"nifty_change_pct": -1.64},
        created_at="2026-10-08 10:30:00 IST",
    )

    flags = {"rr_valid": True, "nifty_change_pct": -1.64, "decoupler_status": "NONE"}
    res = auditor._generate_quantitative_fallback(alert, flags)
    assert res.status == "REJECTED"
    assert res.auditor_model == "QUANT_FALLBACK"
    assert "Quant Gravitational Veto" in res.logic_confirmation


def test_defined_risk_spread_construction_for_hedged_mandate():
    """Verify defined-risk vertical spread is attached when HEDGED_SPREAD_MANDATORY."""
    from engine.defined_risk_spreads import build_defined_risk_spread

    spread = build_defined_risk_spread(
        underlying="BANKNIFTY",
        spot_price=54500.0,
        strategy="BEAR_PUT_SPREAD",
        dte=7,
        lot_size=15,
    )
    assert spread.strategy_name == "BEAR_PUT_SPREAD"
    assert spread.sentiment == "BEARISH"
    assert len(spread.legs) == 2
    assert spread.legs[0].side == "BUY"
    assert spread.legs[0].option_type == "PE"
    assert spread.legs[1].side == "SELL"
    assert spread.legs[1].option_type == "PE"
    assert spread.max_loss > 0
    assert spread.max_profit > 0


def test_trend_day_adaptive_time_stop_bypass():
    """Verify that on confirmed trend days with intact VWAP structure, time-stop is bypassed."""
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing

    now = datetime.now(IST)
    # Set created_at 22 minutes ago so elapsed_mins is 22.0
    created_time = (now - timedelta(minutes=22)).strftime("%Y-%m-%d %H:%M:%S IST")
    alert = AutoAlert(
        alert_id="aa-index-put-setup-nifty-pe-22450-20261008",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="NIFTY 22450 PE Ignition",
        summary="Bearish trend continuation",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=120.0,
        strike=22450.0,
        option_type="PE",
        created_at=created_time,
        confidence=95,
        underlying_spot=22420.0,
        metrics={
            "is_narrow_cpr": True,
            "market_regime": "TRENDING_EXPANSION",
            "chop_index": 34.5,
            "vwap": 22480.0,
            "spot": 22420.0,
        },
    )

    eval_res = evaluate_alert_targets_and_trailing(
        alert=alert,
        current_ltp=148.0,  # Slight consolidation (-1.3% pnl)
    )

    # Must NOT scratch via TIME_STOP_SCRATCH; must compress risk and hold base!
    assert eval_res is not None
    assert eval_res.new_milestone == "COMPRESS_STALL_RISK"
    assert eval_res.target_status != "TIME_STOP_EXIT"
    assert eval_res.is_risk_compression is True
    assert eval_res.recommended_stop > 120.0  # Stop tightened
    assert "20M CONSOLIDATION COIL" in eval_res.trailing_rationale


def test_opening_drive_heavyweight_calibration():
    """Verify mega-cap heavyweights qualify with 0.20% range while generic equities require 0.35%."""
    import pandas as pd
    from engine.detectors.opening_drive import detect_opening_drive

    now_ist = datetime.now(IST).replace(hour=9, minute=20)

    # Create synthetic 5m opening candle with 0.26% range and Open == High
    # RELIANCE: Open 1380.0, High 1380.0, Low 1376.4, Close 1376.5 (range = 3.6 / 1380 = 0.26%)
    df_rel = pd.DataFrame(
        [{"Open": 1380.0, "High": 1380.0, "Low": 1376.4, "Close": 1376.5, "Volume": 500000}]
    )

    # RELIANCE (Heavyweight) must qualify with 0.26% range
    res_rel = detect_opening_drive(
        symbol="RELIANCE",
        df_5m=df_rel,
        ltp=1376.4,
        vwap=1378.0,
        rvol=2.1,
        ref_time=now_ist,
        prev_close=1390.0,
        prev_low=1385.0,
        ignore_time_gate=True,
    )
    assert res_rel is not None
    assert res_rel.direction == "BEARISH"
    assert "Open==High" in res_rel.headline

    # General midcap stock with identical 0.26% range must NOT qualify (requires >= 0.35%)
    df_midcap = pd.DataFrame(
        [{"Open": 500.0, "High": 500.0, "Low": 498.7, "Close": 498.8, "Volume": 50000}]
    )
    res_midcap = detect_opening_drive(
        symbol="ABC_MIDCAP",
        df_5m=df_midcap,
        ltp=498.7,
        vwap=499.5,
        rvol=2.1,
        ref_time=now_ist,
        prev_close=505.0,
        prev_low=502.0,
        ignore_time_gate=True,
    )
    assert res_midcap is None, "Midcap with 0.26% range must be filtered out by 0.35% floor"


def test_prioritized_targets_opening_drive_heavyweights(monkeypatch):
    """Verify AutoAlertEngine prioritizes heavyweights in target queue during opening drive window."""
    from engine.auto_alert_engine import AutoAlertEngine
    from types import SimpleNamespace

    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY"]
    engine.watched_equities.clear()
    engine.watched_equities.extend(["ABC_STOCK", "RELIANCE", "XYZ_STOCK", "TATASTEEL"])

    # Mock quotes: RELIANCE moving -0.30%, ABC_STOCK flat
    quotes = {
        "RELIANCE": SimpleNamespace(change_pct=-0.30, last_price=1376.0),
        "TATASTEEL": SimpleNamespace(change_pct=-0.25, last_price=168.0),
        "ABC_STOCK": SimpleNamespace(change_pct=0.10, last_price=500.0),
        "XYZ_STOCK": SimpleNamespace(change_pct=-0.05, last_price=200.0),
    }

    with patch("market.quotes._QUOTE_CACHE", {k: (0, v) for k, v in quotes.items()}):
        with patch(
            "engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=False
        ):
            # Simulate 09:20 IST opening session
            with patch("engine.auto_alert_engine.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 10, 8, 9, 20, tzinfo=IST)
                engine._prioritized_targets_cache = []
                engine._prioritized_targets_ts = 0.0

                targets = engine._get_prioritized_targets()
                # Heavyweights RELIANCE and TATASTEEL must be at the very front of equities!
                assert targets[0] in ("RELIANCE", "TATASTEEL")
                assert targets[1] in ("RELIANCE", "TATASTEEL")


def test_limit_on_pullback_and_primed_decoupler_ignition():
    """Verify LIMIT_ON_PULLBACK and PRIMED decoupler setups trigger cleanly."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine._alerts.clear()

    # Alert with LIMIT_ON_PULLBACK entry style
    alert_pp = AutoAlert(
        alert_id="aa-asym-pocket-pivot-coforge-20261008",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="PRIMED",
        symbol="COFORGE",
        exchange="NSE",
        direction="BULLISH",
        headline="COFORGE Pocket Pivot",
        summary="Pocket Pivot Base",
        ltp=1866.80,
        trigger_level=1869.80,
        stop_loss=1713.40,
        target_level=2182.60,
        confidence=85,
        entry_type="LIMIT_ON_PULLBACK",
        metrics={"relative_strength_score": 1.2},
        actionable_plan={"entry_type": "LIMIT_ON_PULLBACK", "action": "BUY"},
        is_live=True,
    )
    engine._alerts.append(alert_pp)

    # Current LTP is 1866.80 (at or below limit entry 1869.80, holding above SL 1713.40)
    with patch.object(engine, "_batch_refresh_quotes", return_value={"NSE:COFORGE": 1866.80}):
        with patch.object(engine, "_dispatch"):
            ignited = engine.check_and_ignite_early_warnings()

    assert len(ignited) == 1
    assert ignited[0].stage == "IGNITED"
    assert "Limit entry" in ignited[0].audit_trail[-1]["message"]


def test_mcx_opening_drive_detection():
    """Verify MCX commodities detect Open==Low opening drives (09:00-09:45 IST)."""
    import pandas as pd
    from engine.detectors.commodity import detect_commodity_breakouts
    from types import SimpleNamespace

    q_crude = SimpleNamespace(
        symbol="CRUDEOIL",
        last_price=8665.0,
        open=8637.0,
        high=8670.0,
        low=8637.0,  # Open == Low
        close=8552.0,
        volume=5000,
        change=113.0,
        change_pct=1.32,
        vwap=8650.0,
        provider="mock",
        data_state="TEST",
    )

    dates = pd.date_range("2026-10-08 09:00", periods=25, freq="5min")
    closes = [8637.0 + i * 1.5 for i in range(25)]
    opens = [c - 1.0 for c in closes]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    volumes = [1000.0] * 24 + [4500.0]
    df_synthetic = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    with (
        patch("engine.detectors.commodity.datetime") as mock_dt,
        patch("analysis.market_structure.analyze_market_structure", return_value=None),
    ):
        mock_dt.now.return_value = datetime(2026, 10, 8, 9, 20, tzinfo=IST)
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL"],
            quotes_map={"MCX:CRUDEOIL": q_crude, "CRUDEOIL": q_crude},
            ohlcv_map={"CRUDEOIL": df_synthetic},
        )
    assert len(alerts) >= 1
    a = alerts[0]
    assert a.direction == "BULLISH"
    assert a.exchange == "MCX"
    assert any(
        "Opening Drive" in tag for tag in a.actionable_plan.get("setup_confluence", "").split(" • ")
    )


def test_commodity_telegram_confidence_calibration():
    """Verify calibrated COMMODITY_MOMENTUM with score 84% passes Telegram dispatch gate."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    alert_crude = AutoAlert(
        alert_id="aa-commodity-momentum-crudeoil-bullish-8700ce-20261008",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX OPTION: CRUDEOIL 8700 CE @ 259.3",
        summary="Quant-validated momentum",
        ltp=259.3,
        trigger_level=259.3,
        stop_loss=205.1,
        target_level=421.9,
        confidence=84,  # Scrutiny score 84%
        is_live=True,
    )

    with patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True):
        allowed, reason = engine._eval_telegram_apex_gate(alert_crude)
        assert allowed is True, f"Expected allowed=True, got reason: {reason}"
