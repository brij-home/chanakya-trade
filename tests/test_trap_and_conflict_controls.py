"""
tests/test_trap_and_conflict_controls.py
────────────────────────────────────────
Validates trap prevention and opportunity preservation controls:
  1. Option ignition payoff: Put options ignite ONLY on premium breakout (cur_ltp >= trigger), never on decay.
  2. Directional conflict mutex on ignition: Opposing early warning ignition is suppressed if an active trade is running.
  3. Structural reversal bypass: Legitimate CHoCH/sweep cleanly supersedes older opposing alert.
  4. PDL Bear Trap prevention: Shallow pierce of PDL without breakdown momentum is suppressed.
  5. Gamma Blast sweep requirement: Requires verified bounce >= 0.10% off the low, not resting at day_low.
"""

from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.index_put_setup import detect_index_put_setup

IST = ZoneInfo("Asia/Kolkata")


def test_put_option_ignition_requires_premium_breakout(monkeypatch):
    """
    Validates that a Put option early warning (direction='BEARISH') requires the option premium
    to cross ABOVE the trigger level (cur_ltp >= trigger) and never ignites on premium decay.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    put_alert = AutoAlert(
        alert_id="pe-early-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        contract_symbol="NFO:NIFTY26OCT23000PE",
        exchange="NFO",
        direction="BEARISH",
        headline="PE Coiling",
        summary="Put coiling near trigger",
        option_type="PE",
        strike=23000,
        trigger_level=69.4,
        ltp=65.0,
        stop_loss=45.0,
        target_level=120.0,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(put_alert)

    # 1. Price drops to 65.6 (below trigger 69.4) -> MUST NOT IGNITE
    monkeypatch.setattr(
        engine, "_batch_refresh_quotes", lambda alerts: {"NFO:NIFTY26OCT23000PE": 65.6}
    )
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 0
    assert put_alert.stage == "EARLY_WARNING"

    # 2. Price surges to 71.0 (above trigger 69.4) -> MUST IGNITE AS PUT BREAKDOWN
    monkeypatch.setattr(
        engine, "_batch_refresh_quotes", lambda alerts: {"NFO:NIFTY26OCT23000PE": 71.0}
    )
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 1
    assert put_alert.stage == "IGNITED"
    assert "PUT BREAKDOWN IGNITED" in put_alert.headline
    assert put_alert.ltp == 71.0

    engine.clear_alerts()


def test_opposing_trade_mutex_suppresses_conflicting_ignition(monkeypatch):
    """
    Validates that if an active CE trade is already running on NIFTY,
    an incoming PE early warning is suppressed from igniting unless there is a confirmed reversal.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Active running Call trade
    active_ce = AutoAlert(
        alert_id="active-ce-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NFO:NIFTY26OCT23050CE",
        exchange="NFO",
        direction="BULLISH",
        headline="CE Ignited",
        summary="Call running",
        trigger_level=150.0,
        option_type="CE",
        strike=23050,
        ltp=155.0,
        stop_loss=120.0,
        target_level=220.0,
        is_live=True,
        environment="LIVE",
    )
    # Early warning Put on same index
    pe_early = AutoAlert(
        alert_id="early-pe-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        contract_symbol="NFO:NIFTY26OCT23000PE",
        exchange="NFO",
        direction="BEARISH",
        headline="PE Coiling",
        summary="Put coiling",
        trigger_level=70.0,
        option_type="PE",
        strike=23000,
        ltp=68.0,
        stop_loss=45.0,
        target_level=120.0,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.extend([active_ce, pe_early])

    # PE crosses trigger, but no CHoCH/reversal metric -> MUST BE SUPPRESSED
    monkeypatch.setattr(
        engine, "_batch_refresh_quotes", lambda alerts: {"NFO:NIFTY26OCT23000PE": 72.0}
    )
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 0
    assert pe_early.stage == "EARLY_WARNING"
    assert active_ce.is_active is True

    # Now give PE a confirmed structural reversal metric (choch=True)
    pe_early.metrics = {"choch": True}
    ignited = engine.check_and_ignite_early_warnings()
    assert len(ignited) == 1
    assert pe_early.stage == "IGNITED"
    # Older opposing CE trade should be atomically retired
    assert active_ce.stage == "INVALIDATED"
    assert "Superseded" in (active_ce.invalidation_reason or "")

    engine.clear_alerts()


def test_pdl_bear_trap_suppression():
    """
    Validates that when spot is shallowly piercing PDL by < 0.15% without verified breakdown momentum,
    IndexPutSetup suppresses the PE alert to protect traders from Bear Traps.
    """
    mock_pe = MagicMock()
    mock_pe.strike = 23000
    mock_pe.last_price = 70.0
    mock_pe.pchange = 4.0  # Weak change, not true momentum
    mock_pe.volume = 5000
    mock_pe.oi = 10000  # Vol/OI = 0.5 (low)
    mock_pe.option_type = "PE"
    mock_pe.symbol = "NIFTY26OCT23000PE"
    mock_pe.expiry = "2026-09-25"

    chain = [mock_pe]

    # PDL = 23020, spot = 23005 (shallow break of ~0.06%, no momentum)
    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=23005.0,
        chain=chain,
        vwap=23050.0,
        day_high=23120.0,
        day_low=23000.0,
        prev_day_high=23180.0,
        prev_day_low=23020.0,  # Spot is shallowly piercing PDL
        ignore_time_gate=True,
    )
    # Must be suppressed due to Bear Trap risk (pdl_break_pct < 0.15% without breakdown momentum)
    assert len(alerts) == 0


def test_gamma_blast_sweep_requires_actual_bounce():
    """
    Validates that Gamma Blast requires an actual verified bounce >= 0.10% off the low
    and does NOT claim a PDL sweep when spot is resting at the absolute session low.
    """
    mock_ce = MagicMock()
    mock_ce.strike = 23050
    mock_ce.last_price = 145.0
    mock_ce.pchange = 12.0
    mock_ce.volume = 200000
    mock_ce.oi = 50000
    mock_ce.oi_change = -5000
    mock_ce.option_type = "CE"
    mock_ce.symbol = "NIFTY26OCT23050CE"
    mock_ce.expiry = "2026-09-25"

    chain = [mock_ce]

    # Spot is sitting AT day_low (zero bounce: 23000 == 23000)
    # vwap is high (23100), spot is far below vwap
    alerts = detect_gamma_blast(
        underlying="NIFTY",
        spot=23000.0,
        chain=chain,
        vwap=23100.0,
        day_high=23150.0,
        day_low=23000.0,
        prev_day_high=23200.0,
        prev_day_low=23010.0,
    )
    # Since spot has 0% bounce from day_low, _pdl_sweep_active is False.
    # Therefore, VWAP bypass cannot activate for CE when spot is 100 pts below VWAP!
    assert len(alerts) == 0


def test_index_macro_confluence_vetoes_secondary_index_put_when_nifty_is_green():
    """
    Validates that a Put setup on a secondary index (e.g. MIDCPNIFTY) is vetoed by Tier-1
    Scrutiny when the primary benchmark (NIFTY 50) is green (+0.08%) and holding above VWAP.
    """
    from engine.alert_scrutiny import alert_scrutiny_auditor

    midcp_put = AutoAlert(
        alert_id="midcp-pe-counter",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        contract_symbol="NFO:MIDCPNIFTY26OCT12500PE",
        exchange="NFO",
        direction="BEARISH",
        headline="Midcap Put Breakdown",
        summary="Midcap drifting down",
        option_type="PE",
        strike=12500,
        ltp=85.0,
        trigger_level=85.0,
        stop_loss=60.0,
        target_level=145.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "nifty_change_pct": 0.08,
            "vwap": 12520.0,
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(midcp_put)
    assert passed is False
    assert "Benchmark Divergence Trap" in reason
    assert "MIDCPNIFTY" in reason
    assert flags.get("benchmark_regime_valid") is False


def test_banknifty_locomotive_tug_of_war_vetoes_naked_options(monkeypatch):
    """
    Validates that when HDFCBANK and ICICIBANK (>52% Bank Nifty weight) are in opposing
    momentum conflict in low VIX (<14.0), naked directional option breakouts are vetoed.
    """
    from engine.alert_scrutiny import alert_scrutiny_auditor
    from market.indices import IndexPolarization

    # Mock low VIX and polarized Bank Nifty
    monkeypatch.setattr(
        "market.indices.get_vix",
        lambda: 12.2,
    )
    mock_pol = IndexPolarization(
        index="BANKNIFTY",
        is_polarized=True,
        regime="TUG_OF_WAR_CHOP",
        dispersion_std=1.8,
        max_gainer=("HDFCBANK", 0.95),
        max_loser=("ICICIBANK", -0.72),
        spread_pct=1.67,
        heavyweight_changes={"HDFCBANK": 0.95, "ICICIBANK": -0.72},
        summary="HDFCBANK (+0.95%) vs ICICIBANK (-0.72%) conflict",
    )
    monkeypatch.setattr(
        "market.indices.get_index_polarization",
        lambda idx: mock_pol,
    )

    bank_call = AutoAlert(
        alert_id="bn-call-chop",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        contract_symbol="NFO:BANKNIFTY26OCT55500CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Bank Nifty Call Breakout",
        summary="Testing 55500 resistance",
        option_type="CE",
        strike=55500,
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=190.0,
        target_level=390.0,
        is_live=True,
        environment="LIVE",
        actionable_plan={"action": "BUY_CALL"},  # Naked option
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(bank_call)
    assert passed is False
    assert "Locomotive Tug-of-War Veto" in reason
    assert flags.get("heavyweight_confluence_valid") is False


def test_in_flight_directional_lockout_blocks_opposing_alert():
    """
    Validates that an in-flight trade commitment (stage='IGNITED') on an index (e.g. MIDCPNIFTY CE)
    strictly blocks incoming opposing alerts (e.g. MIDCPNIFTY PE) from entering or superseding the trade.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Active in-flight Call trade
    active_ce = AutoAlert(
        alert_id="midcp-ce-inflight",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        contract_symbol="NFO:MIDCPNIFTY26OCT12500CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Midcap CE In-Flight",
        summary="Call ignited and trailing",
        option_type="CE",
        strike=12500,
        ltp=90.0,
        trigger_level=88.0,
        stop_loss=72.0,
        target_level=140.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={"nifty_change_pct": 0.0},
    )
    res_ce = engine.record_alert(active_ce)
    assert res_ce is True
    assert len([a for a in engine._alerts if a.is_active and not a.is_invalidated]) == 1

    # Incoming opposing PE alert arrives 5 minutes later
    incoming_pe = AutoAlert(
        alert_id="midcp-pe-incoming",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        contract_symbol="NFO:MIDCPNIFTY26OCT12450PE",
        exchange="NFO",
        direction="BEARISH",
        headline="Midcap PE Breakdown",
        summary="5m candle breakdown",
        option_type="PE",
        strike=12450,
        ltp=75.0,
        trigger_level=75.0,
        stop_loss=60.0,
        target_level=120.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={"nifty_change_pct": 0.0},
    )
    res_pe = engine.record_alert(incoming_pe)
    # MUST BE BLOCKED by In-Flight Directional Lockout
    assert res_pe is False
    # Active CE trade must be completely preserved and untouched
    assert active_ce.is_invalidated is False
    assert active_ce.stage == "IGNITED"

    engine.clear_alerts()


def test_directional_quarantine_blocks_rapid_flip_flop(monkeypatch):
    """
    Validates that after an index trade (e.g. MIDCPNIFTY) is invalidated,
    a 20-minute directional quarantine suppresses opposing setups to prevent whipsaws.
    """
    import time

    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Create an alert and invalidate it
    bull_alert = AutoAlert(
        alert_id="nifty-bull-stop",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NFO:NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Bullish",
        summary="Bullish setup",
        option_type="CE",
        strike=25000,
        ltp=150.0,
        trigger_level=149.0,
        stop_loss=120.0,
        target_level=220.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={"nifty_change_pct": 0.0},
    )
    res = engine.record_alert(bull_alert)
    assert res is True
    engine.invalidate_alert_by_id("nifty-bull-stop", reason="SL Hit")

    assert bull_alert.stage == "INVALIDATED"
    assert "NIFTY" in engine._directional_quarantine
    inval_time, inval_dir = engine._directional_quarantine["NIFTY"]
    assert inval_dir == "BULLISH"

    # 1. Incoming opposing BEARISH alert arrives 5 minutes later (elapsed = 300s < 1200s)
    bear_alert = AutoAlert(
        alert_id="nifty-bear-early",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NFO:NIFTY26OCT24800PE",
        exchange="NFO",
        direction="BEARISH",
        headline="Nifty Bear Breakdown",
        summary="Bear setup",
        option_type="PE",
        strike=24800,
        ltp=140.0,
        trigger_level=140.0,
        stop_loss=115.0,
        target_level=210.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={"nifty_change_pct": 0.0},
    )
    # Monkeypatch time to simulate 5 minutes later
    monkeypatch.setattr(time, "time", lambda: inval_time + 300.0)
    res_5m = engine.record_alert(bear_alert)
    # MUST BE SUPPRESSED by Directional Quarantine Gate
    assert res_5m is False

    # 2. Incoming opposing BEARISH alert arrives 25 minutes later (elapsed = 1500s > 1200s)
    monkeypatch.setattr(time, "time", lambda: inval_time + 1500.0)
    # Also ensure it passes timing and macro gates
    bear_alert.alert_id = "nifty-bear-later"
    res_25m = engine.record_alert(bear_alert)
    # Should now pass directional quarantine
    assert res_25m is True

    engine.clear_alerts()


def test_tier1_sanity_at_step_00e_protects_existing_trades():
    """
    Validates that if an incoming opposing alert fails Tier-1 Sanity (e.g. macro confluence veto),
    it is rejected at Step 00e BEFORE Step 1c can touch or invalidate existing active trades.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Active Call trade on radar
    radar_ce = AutoAlert(
        alert_id="radar-ce-step00e",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="FINNIFTY",
        contract_symbol="NFO:FINNIFTY26OCT24000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Finnifty CE Radar",
        summary="Call radar",
        option_type="CE",
        strike=24000,
        ltp=70.0,
        trigger_level=70.0,
        stop_loss=56.0,
        target_level=110.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={"nifty_change_pct": 0.0},
    )
    res = engine.record_alert(radar_ce)
    assert res is True
    assert len([a for a in engine._alerts if a.is_active and not a.is_invalidated]) == 1

    # Incoming opposing PE setup that fails Tier-1 Macro Sanity (e.g. NIFTY is green +0.10%)
    invalid_pe = AutoAlert(
        alert_id="invalid-pe-step00e",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="FINNIFTY",
        contract_symbol="NFO:FINNIFTY26OCT23800PE",
        exchange="NFO",
        direction="BEARISH",
        headline="Finnifty PE Counter-Trend",
        summary="Counter trend put",
        option_type="PE",
        strike=23800,
        ltp=80.0,
        trigger_level=80.0,
        stop_loss=64.0,
        target_level=130.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={
            "nifty_change_pct": 0.10,
            "vwap": 23900.0,
        },
    )

    res = engine.record_alert(invalid_pe)
    # Incoming alert rejected at Step 00e
    assert res is False
    # The existing radar setup MUST STILL BE ACTIVE and NOT invalidated
    assert radar_ce.is_invalidated is False
    assert radar_ce.stage == "EARLY_WARNING"

    engine.clear_alerts()


def test_hbcm_contradiction_veto_blocks_counter_heavyweight_reversals():
    """
    Validates that even if an index alert carries reversal tags (e.g. DAY_HIGH_SUPPLY_REJECTION),
    if heavyweights are overwhelmingly bullish (e.g. 3/5 or 4/5 bullish), HBCM Locomotive
    Contradiction Veto strictly kills the put setup.
    """
    from engine.alert_scrutiny import alert_scrutiny_auditor

    alert = AutoAlert(
        alert_id="bn-pe-reversal-trap",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Supply Rejection Put",
        summary="Testing day high",
        option_type="PE",
        strike=54400.0,
        underlying_spot=54850.0,
        ltp=548.0,
        trigger_level=548.0,
        stop_loss=438.0,
        target_level=712.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "signals": ["DAY_HIGH_SUPPLY_REJECTION"],
            "day_high": 54900.0,
            "vwap": 54750.0,
            "hbcm": {
                "total_heavyweights": 5,
                "bullish_count": 3,
                "bearish_count": 1,
                "confluence_pass": False,
                "rejection_reason": "Only 1/5 heavyweights bearish",
            },
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "HBCM Locomotive Contradiction Veto" in (reason or "")
    assert flags.get("heavyweight_confluence_valid") is False


def test_active_opposing_direction_conflict_gate_blocks_simultaneous_opposite_alerts(monkeypatch):
    """
    Validates that if MIDCPNIFTY has an active BULLISH (CE) alert in-flight,
    an incoming BEARISH (PE) alert within 30 minutes is automatically suppressed at Step 00f-2.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Provide aligned HBCM metrics so Tier-1 Perimeter passes
    call_alert = AutoAlert(
        alert_id="midcp-ce-active",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        contract_symbol="NFO:MIDCPNIFTY26OCT13600CE",
        exchange="NFO",
        direction="BULLISH",
        headline="Midcap Bull Call",
        summary="Bull setup",
        option_type="CE",
        strike=13600,
        ltp=140.0,
        trigger_level=140.0,
        stop_loss=112.0,
        target_level=183.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={
            "hbcm": {
                "confluence_pass": True,
                "total_heavyweights": 5,
                "bullish_count": 4,
                "bearish_count": 0,
            }
        },
    )
    ok1 = engine.record_alert(call_alert)
    assert ok1 is True

    # 7 seconds later, another detector generates an opposing PE setup on MIDCPNIFTY
    put_alert = AutoAlert(
        alert_id="midcp-pe-conflict",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        contract_symbol="NFO:MIDCPNIFTY26OCT13650PE",
        exchange="NFO",
        direction="BEARISH",
        headline="Midcap Bear Put",
        summary="Bear setup",
        option_type="PE",
        strike=13650,
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=200.0,
        is_live=True,
        environment="LIVE",
        confidence=85,
        metrics={
            "hbcm": {
                "confluence_pass": True,
                "total_heavyweights": 5,
                "bullish_count": 0,
                "bearish_count": 4,
            }
        },
    )
    ok2 = engine.record_alert(put_alert)
    # MUST be suppressed by Active Opposing Direction Conflict Gate
    assert ok2 is False

    engine.clear_alerts()


def test_market_breadth_rally_veto_blocks_index_put_without_breakdown(monkeypatch):
    """
    Validates that when market breadth A/D ratio is >= 1.50 (e.g. 317 Adv / 182 Dec = 1.74),
    an index PUT setup is vetoed unless constituent breakdown is confirmed.
    """
    monkeypatch.setenv("ENFORCE_TEST_BREADTH", "1")
    from engine.alert_scrutiny import alert_scrutiny_auditor
    from market.sentiment import MarketBreadth

    mock_mb = MarketBreadth(
        advances=317,
        declines=182,
        unchanged=1,
        ad_ratio=1.74,
        verdict="BROAD_RALLY",
    )
    monkeypatch.setattr("market.sentiment.get_market_breadth", lambda: mock_mb)

    alert = AutoAlert(
        alert_id="test-breadth-rally-put",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Bank Nifty Put into Rally",
        summary="Put setup into breadth rally",
        option_type="PE",
        strike=54400.0,
        underlying_spot=54900.0,
        ltp=500.0,
        trigger_level=500.0,
        stop_loss=400.0,
        target_level=680.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "day_high": 54920.0,  # drop is only (54920 - 54900)/54920 = 0.036% < 0.40%
            "signals": ["DAY_HIGH_SUPPLY_REJECTION"],
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Market Breadth Rally Veto" in (reason or "")
    assert flags.get("market_breadth_valid") is False


def test_day_high_supply_rejection_suppressed_when_above_vwap_without_rejection_candle(monkeypatch):
    """
    Validates that when spot is cleanly above session VWAP in an ongoing bull trend,
    a trivial 0.08% pause at Day High without a confirmed rejection candle is SUPPRESSED.
    This permanently prevents false Put signals when the market is rallying.
    """
    import pandas as pd
    from engine.detectors.index_put_setup import detect_index_put_setup

    mock_pe = MagicMock()
    mock_pe.strike = 22800.0
    mock_pe.option_type = "PE"
    mock_pe.last_price = 120.0
    mock_pe.volume = 50000
    mock_pe.oi = 30000
    mock_pe.pchange = -12.0  # Put premium is depreciating (-12%) as market rallies
    mock_pe.symbol = "NIFTY22800PE"
    mock_pe.expiry = "2026-10-06"

    # Spot is at 22,790, VWAP is at 22,725 (+65 pts above VWAP), Day High is 22,805 (0.06% retreat)
    # The last 5m candle is a green bullish candle with tiny upper wick (not a supply rejection)
    ohlcv = pd.DataFrame(
        [
            {"open": 22750.0, "high": 22770.0, "low": 22745.0, "close": 22765.0, "volume": 10000},
            {"open": 22765.0, "high": 22795.0, "low": 22760.0, "close": 22790.0, "volume": 12000},
            {
                "open": 22790.0,
                "high": 22805.0,
                "low": 22785.0,
                "close": 22800.0,
                "volume": 15000,
            },  # Green bar, close near high
        ]
    )

    # Mock heavyweights to passthrough
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda sym: {"heavyweights": [], "bear_count": 0, "bull_count": 0},
    )

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=22790.0,
        chain=[mock_pe],
        vwap=22725.0,
        day_high=22805.0,
        day_low=22680.0,
        ohlcv_5m=ohlcv,
        ignore_time_gate=True,
    )
    # Must be completely suppressed — zero false Put signals during an active bull trend above VWAP
    assert len(alerts) == 0


def test_put_setup_suppressed_when_heavyweights_net_bullish(monkeypatch):
    """
    Validates that when index heavyweights are net bullish (e.g. 4 bulls vs 1 bear),
    IndexPutSetup suppresses PE setups to avoid fighting index locomotive thrust.
    """
    from engine.detectors.index_put_setup import detect_index_put_setup

    mock_pe = MagicMock()
    mock_pe.strike = 22800.0
    mock_pe.option_type = "PE"
    mock_pe.last_price = 120.0
    mock_pe.volume = 50000
    mock_pe.oi = 30000
    mock_pe.pchange = 5.0
    mock_pe.symbol = "NIFTY22800PE"
    mock_pe.expiry = "2026-10-06"

    # 4 heavyweights bullish, 1 bearish
    hw_posture = {
        "heavyweights": [
            {"symbol": "RELIANCE", "change_pct": 1.5},
            {"symbol": "HDFCBANK", "change_pct": 1.2},
            {"symbol": "ICICIBANK", "change_pct": 0.8},
            {"symbol": "INFY", "change_pct": 0.5},
            {"symbol": "TCS", "change_pct": -0.1},
        ],
        "bull_count": 4,
        "bear_count": 1,
        "all_bullish": False,
        "all_bearish": False,
    }
    monkeypatch.setattr("market.indices.get_heavyweights_posture", lambda sym: hw_posture)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=22750.0,
        chain=[mock_pe],
        vwap=22760.0,
        day_high=22800.0,
        day_low=22700.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0


def test_call_setup_suppressed_when_heavyweights_net_bearish(monkeypatch):
    """
    Validates that when index heavyweights are net bearish (e.g. 4 bears vs 1 bull),
    IndexCallSetup suppresses CE setups to avoid catching falling knives.
    """
    from engine.detectors.index_call_setup import detect_index_call_setup

    mock_ce = MagicMock()
    mock_ce.strike = 22750.0
    mock_ce.option_type = "CE"
    mock_ce.last_price = 140.0
    mock_ce.volume = 50000
    mock_ce.oi = 30000
    mock_ce.pchange = 5.0
    mock_ce.symbol = "NIFTY22750CE"
    mock_ce.expiry = "2026-10-06"

    hw_posture = {
        "heavyweights": [
            {"symbol": "RELIANCE", "change_pct": -1.5},
            {"symbol": "HDFCBANK", "change_pct": -1.2},
            {"symbol": "ICICIBANK", "change_pct": -0.8},
            {"symbol": "INFY", "change_pct": -0.5},
            {"symbol": "TCS", "change_pct": 0.1},
        ],
        "bull_count": 1,
        "bear_count": 4,
        "all_bullish": False,
        "all_bearish": False,
    }
    monkeypatch.setattr("market.indices.get_heavyweights_posture", lambda sym: hw_posture)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=22750.0,
        chain=[mock_ce],
        vwap=22740.0,
        day_high=22800.0,
        day_low=22700.0,
        ignore_time_gate=True,
    )
    assert len(alerts) == 0


def test_in_flight_directional_lockout_protects_profitable_spreads():
    """
    Validates that an active in-flight index trade in SPREAD_PROFIT_70, RUNNER, or SPREAD_FREE_ROLL
    blocks opposing directional signals from entering, preventing whipsaws.
    """
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    # Active winning NIFTY Bull Call Spread capturing 70% max profit
    active_spread_ce = AutoAlert(
        alert_id="aa-call-setup-nifty-20260930",
        alert_type="INDEX_CALL_SETUP",
        stage="SPREAD_PROFIT_70",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="70% MAX PROFIT CAPTURED: NIFTY Hedged Spread",
        summary="Active runner secured",
        ltp=183.4,
        trigger_level=141.0,
        stop_loss=141.0,
        target_level=218.6,
        is_live=True,
        environment="LIVE",
    )
    engine._alerts.append(active_spread_ce)

    # Incoming conflicting Bearish Put setup
    conflicting_pe = AutoAlert(
        alert_id="aa-put-setup-nifty-20260930",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="DAY HIGH SUPPLY REJECTION: NIFTY 22800 PE",
        summary="Conflicting put setup",
        ltp=120.8,
        trigger_level=120.8,
        stop_loss=96.7,
        target_level=157.1,
        is_live=True,
        environment="LIVE",
    )

    # Must be blocked by In-Flight Directional Lockout
    result = engine.record_alert(conflicting_pe)
    assert result is False
    assert len(engine._alerts) == 1
    assert engine._alerts[0].direction == "BULLISH"
    assert engine._alerts[0].stage == "SPREAD_PROFIT_70"
