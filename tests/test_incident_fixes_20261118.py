"""
tests/test_incident_fixes_20261118.py
─────────────────────────────────────
Institutional regression test suite for incidents identified on 2026-11-18:
  1. Synthetic Spot SL Drawdown Invariant:
     Must evaluate drawdown against immutable entry anchors (initial_entry_premium / entry_price),
     never mutable option_premium overwritten by live tick feeds.
  2. Invalidation Priority Invariant:
     Stop-loss breaches and catastrophic option drawdowns (>15%) must precede Velocity Stagnation.
     Deep losing positions must never be intercepted or labeled as "stagnation scratches".
  3. Invalidation Post-Mortem Integrity:
     learning_engine.conduct_invalidation_post_mortem must preserve authentic alert.entry_price
     and compute true loss points/realized R, rather than collapsing to exit LTP.
  4. Honest Stagnation vs Loss Attribution:
     _handle_alert_exit must label exits with <= -15% loss as VELOCITY TIME-STOP LOSS,
     and update detector_circuit_breaker accordingly.
"""

from unittest.mock import MagicMock, patch
from engine.alert_model import AutoAlert
from engine.synthetic_sl import evaluate_synthetic_spot_sl
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.learning_engine import PatternLearningEngine
from engine.auto_alert_engine import AutoAlertEngine


def make_test_alert(**kwargs) -> AutoAlert:
    defaults = {
        "alert_id": "test-alert-id",
        "alert_type": "OPTIONS_MOMENTUM",
        "stage": "IGNITED",
        "symbol": "TESTSYM",
        "exchange": "NFO",
        "direction": "BULLISH",
        "headline": "Test Alert Headline",
        "summary": "Test Alert Summary",
        "ltp": 50.0,
        "trigger_level": 50.0,
        "target_level": 75.0,
        "stop_loss": 35.0,
    }
    dynamic_attrs = {}
    for k, v in list(kwargs.items()):
        if k not in AutoAlert.__dataclass_fields__:
            dynamic_attrs[k] = kwargs.pop(k)

    defaults.update(kwargs)
    alert = AutoAlert(**defaults)
    for k, v in dynamic_attrs.items():
        setattr(alert, k, v)
    return alert


def test_synthetic_sl_drawdown_uses_immutable_entry_not_overwritten_option_premium():
    """Verify synthetic SL computes true 40% drawdown when option_premium has been updated to current LTP."""
    alert = make_test_alert(
        alert_id="aa-options-momentum-maruti-ce-13000-0915-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="MARUTI",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=13000.0,
        contract_symbol="NSE:MARUTI26NOV13000CE",
        initial_entry_premium=67.9,
        trigger_level=67.9,
        option_premium=40.55,  # Overwritten by live tick updater to current LTP!
        ltp=40.55,
        stop_loss=52.96,
        underlying_spot=12654.0,
        metrics={
            "spot": 12654.0,
            "spot_invalidation_anchor": 12599.97,
            "dte": 5,
        },
        actionable_plan={
            "entry_price": 67.9,
            "spot_invalidation_anchor": 12599.97,
        },
        entry_price=67.9,
    )

    # Underlying spot 12654 is holding above 12600 (+0.43%), but option has suffered -40.3% loss
    res = evaluate_synthetic_spot_sl(alert, current_option_ltp=40.55)

    assert res.option_drawdown_pct == 40.28, (
        f"Expected 40.28% drawdown, got {res.option_drawdown_pct}%"
    )
    assert res.is_freak_wick_shielded is False, (
        "Catastrophic 40% drawdown must NOT be shielded as a momentary freak wick"
    )
    assert res.is_invalidated is True, (
        "Must be invalidated due to catastrophic drawdown exceeding risk threshold"
    )
    assert "catastrophic drawdown" in res.rejection_reason.lower()


def test_alert_evaluator_stop_loss_precedes_velocity_stagnation():
    """Verify options with breached SL after 50 minutes trigger SL Invalidation, not Velocity Stagnation."""
    from datetime import datetime, timedelta
    from config.constants import IST

    past_time = (datetime.now(IST) - timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = make_test_alert(
        alert_id="aa-options-momentum-apollohosp-ce-8900-0915-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="APOLLOHOSP",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=8900.0,
        contract_symbol="NSE:APOLLOHOSP26NOV8900CE",
        created_at=past_time,
        triggered_at=past_time,
        initial_entry_premium=62.0,
        trigger_level=62.0,
        stop_loss=48.36,
        ltp=41.25,
        stage="IGNITED",
        time_horizon="INTRADAY",
        metrics={
            "spot": 8744.0,
            "spot_invalidation_anchor": 8706.73,
            "dte": 5,
        },
        actionable_plan={
            "entry_price": 62.0,
            "spot_invalidation_anchor": 8706.73,
        },
        entry_price=62.0,
    )

    reason = evaluate_alert_invalidation(alert, current_ltp=41.25)
    assert reason is not None, "Alert must be invalidated when price is 41.25 vs SL 48.36"
    assert "velocity stagnation" not in reason.lower(), (
        f"Breached SL must NOT be intercepted as stagnation scratch: {reason}"
    )
    assert (
        "catastrophic drawdown" in reason.lower()
        or "breached stop-loss" in reason.lower()
        or "dropped to" in reason.lower()
    )


def test_alert_evaluator_velocity_stagnation_only_when_sl_not_breached(monkeypatch):
    """Verify Velocity Stagnation triggers ONLY when option is stalled near entry and SL is intact."""
    from datetime import datetime, timedelta
    from config.constants import IST
    import engine.alert_evaluator as ae_mod

    # Pin evaluator clock to mid-session (11:30 IST) so evening CI runs don't hit 15:15 squareoff before stagnation check
    fixed_now = datetime(2026, 11, 25, 11, 30, 0, tzinfo=IST)

    class _MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(ae_mod, "datetime", _MockDateTime)
    past_time = (fixed_now - timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = make_test_alert(
        alert_id="aa-options-momentum-test-stagnate-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="INFY",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=1900.0,
        contract_symbol="NSE:INFY26NOV1900CE",
        created_at=past_time,
        triggered_at=past_time,
        initial_entry_premium=45.0,
        trigger_level=45.0,
        stop_loss=33.0,
        ltp=44.0,  # Near entry, small loss (-2.2%), well above SL 33.0
        stage="IGNITED",
        time_horizon="INTRADAY",
        _force_test_expiry=True,
        metrics={
            "rvol": 0.70,  # Dried-up volume
        },
        entry_price=45.0,
    )

    reason = evaluate_alert_invalidation(alert, current_ltp=44.0)
    assert reason is not None, "Should trigger velocity stagnation time-stop"
    assert "velocity stagnation" in reason.lower()
    assert "scratch level" in reason.lower()


def test_learning_engine_post_mortem_preserves_real_entry_price_for_asymmetric_option():
    """Verify conduct_invalidation_post_mortem records true entry price and loss for asymmetric options."""
    engine = PatternLearningEngine(clock=lambda: 1794500000.0)

    alert = make_test_alert(
        alert_id="aa-asym-pocket-pivot-bluestarco-20261102",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        symbol="BLUESTARCO",
        direction="BULLISH",
        initial_entry_premium=47.7,
        trigger_level=0.0,  # Unanchored trigger
        stop_loss=40.3,
        ltp=25.35,
        actionable_plan={
            "contract": "NSE:BLUESTARCO26NOV1600CE",
            "option_type": "CE",
            "entry_price": 47.7,
            "option_stop_loss": "₹40.3",
        },
        entry_price=47.7,
    )

    with patch.object(engine, "_save_post_mortems"), patch.object(engine, "_save_lockouts"):
        pm = engine.conduct_invalidation_post_mortem(
            alert=alert,
            exit_price=25.35,
            exchange="NSE",
        )

        assert pm.entry_price == 47.7, f"Expected entry_price=47.7, got {pm.entry_price}"
        assert pm.stop_loss == 40.3, f"Expected stop_loss=40.3, got {pm.stop_loss}"
        assert pm.exit_price == 25.35, f"Expected exit_price=25.35, got {pm.exit_price}"
        assert pm.loss_pts == 22.35, f"Expected loss_pts=22.35, got {pm.loss_pts}"
        assert pm.loss_pct > 40.0, f"Expected loss_pct > 40%, got {pm.loss_pct}%"
        assert pm.realized_r < -1.5, f"Expected realized_r < -1.5, got {pm.realized_r}"


def test_auto_alert_engine_stagnation_loss_headline_and_circuit_breaker():
    """Verify _handle_alert_exit labels deep loss on time-stop as VELOCITY TIME-STOP LOSS, not SCRATCH."""
    engine = AutoAlertEngine()

    alert = make_test_alert(
        alert_id="aa-options-momentum-loss-test-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="MARUTI",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=13000.0,
        contract_symbol="NSE:MARUTI26NOV13000CE",
        initial_entry_premium=67.9,
        trigger_level=67.9,
        stop_loss=52.96,
        ltp=34.05,
        is_live=True,
        environment="LIVE",
        stage="IGNITED",
        entry_price=67.9,
    )

    reason = (
        "Velocity Stagnation Time-Stop: Option momentum stalled for 60m. Exited at level ₹34.05."
    )

    with (
        patch.object(engine, "_save"),
        patch.object(engine, "_dispatch"),
        patch(
            "engine.detector_circuit_breaker.detector_circuit_breaker.record_outcome"
        ) as mock_record_cb,
    ):
        engine._handle_alert_exit(
            alert=alert,
            reason=reason,
            current_ltp=34.05,
            loop_context="Test",
        )

        assert alert.stage == "TIME_STOP_EXIT"
        assert "VELOCITY TIME-STOP LOSS" in alert.headline, (
            f"Expected VELOCITY TIME-STOP LOSS headline, got '{alert.headline}'"
        )
        assert "SCRATCH" not in alert.headline
        # Verify circuit breaker was notified of the LOSS
        mock_record_cb.assert_called_once()
        call_kwargs = mock_record_cb.call_args[1]
        assert call_kwargs["outcome"] == "LOSS", (
            f"Expected circuit breaker outcome 'LOSS', got {call_kwargs['outcome']}"
        )


def test_stock_fno_call_rejected_on_adverse_order_book_imbalance():
    """Verify single-stock F&O Call setup is rejected when 50-depth OBI <= -0.20 or fortress ask wall exists."""
    from types import SimpleNamespace
    from datetime import datetime, timezone, timedelta
    from engine.detectors.options_momentum import detect_options_momentum_breakouts
    from analysis.sector_rotation import StockTailwind

    IST = timezone(timedelta(hours=5, minutes=30))
    now_dt = datetime(2026, 9, 23, 10, 30, tzinfo=IST)

    class DummyQuote:
        def __init__(self, ltp: float, open_p: float, vwap: float, chg: float = 1.2):
            self.last_price = ltp
            self.ltp = ltp
            self.open = open_p
            self.vwap = vwap
            self.change_pct = chg
            self.high = ltp * 1.005
            self.low = open_p * 0.998

    class DummyOptionContract:
        def __init__(
            self,
            symbol: str,
            strike: float,
            option_type: str,
            last_price: float,
            volume: int,
            oi: int,
            pchange: float = 12.0,
        ):
            self.symbol = symbol
            self.strike = strike
            self.option_type = option_type
            self.last_price = last_price
            self.volume = volume
            self.oi = oi
            self.pchange = pchange
            self.change_pct = pchange
            self.oi_change = -500
            self.bid = last_price * 0.99
            self.ask = last_price * 1.01
            self.expiry = "2026-09-29"

    quote = DummyQuote(ltp=1500.0, open_p=1480.0, vwap=1490.0, chg=1.35)
    contracts = [
        DummyOptionContract("INFY1520CE", 1520.0, "CE", 32.0, volume=3500, oi=2500, pchange=18.0)
    ]
    tailwind = StockTailwind(
        symbol="INFY",
        sector="IT",
        quadrant="LEADING",
        rs_ratio=103.5,
        rs_momentum=102.1,
        tailwind_score=85,
        alignment="STRONG_TAILWIND",
        analysis="Sector IT in strong tailwind",
        intraday_rs=1.1,
        intraday_alignment="STRONG_INTRADAY_TAILWIND",
    )

    adverse_depth = {
        "status": "LIVE",
        "obi_50": -0.54,  # Severe ask wall
        "fortress_ask_wall_confirmed": True,
        "fortress_bid_wall_confirmed": False,
    }

    mock_tbt = MagicMock()
    mock_tbt.is_connected = True
    mock_tbt.get_50_depth.return_value = adverse_depth

    with (
        patch(
            "market.quotes.get_quote",
            return_value={"NSE:INFY": quote, "NSE:NIFTY 50": DummyQuote(24500, 24450, 24480, 0.4)},
        ),
        patch("market.quotes.get_ltp", return_value=1500.0),
        patch("market.options.get_options_chain", return_value=contracts),
        patch("market.options.get_expiries", return_value=["2026-09-29"]),
        patch("market.history.get_ohlcv", return_value=None),
        patch(
            "engine.daily_levels.get_daily_levels",
            return_value=SimpleNamespace(cpr={}, camarilla={}),
        ),
        patch("analysis.sector_rotation.get_stock_tailwind", return_value=tailwind),
        patch(
            "analysis.universe.get_stock_sector", return_value=("it", "IT, Software & Technology")
        ),
        patch("market.fyers_tbt_manager.fyers_tbt_manager", mock_tbt),
        patch("market.fyers_tbt_manager.FyersTbtManager", return_value=mock_tbt),
    ):
        alerts = detect_options_momentum_breakouts(
            targets=["INFY"],
            watched_indices=[],
            now_dt=now_dt,
        )
        assert len(alerts) == 0, (
            f"INFY Call setup must be rejected due to adverse OBI=-0.54 ask wall, got {alerts}"
        )


def test_session_focus_fno_only_omits_cash_and_crypto_scans():
    """Verify SESSION_FOCUS_MODE=FNO_ONLY restricts scan_fresh_signals_now to scan_equity_nfo_now."""
    import os

    engine = AutoAlertEngine()

    mock_session = {
        "equity_nfo": True,
        "currency": False,
        "commodity": True,
    }

    env_overrides = {
        "SESSION_FOCUS_MODE": "FNO_ONLY",
        "CHANAKYA_TESTING": "0",
        "DEPLOY_MODE": "production",
    }

    with (
        patch.dict("os.environ", env_overrides),
        patch("engine.auto_alert_engine.get_current_ist_session", return_value=mock_session),
        patch(
            "config.discovery_policy.get_discovery_policy", return_value=MagicMock(fno_only=False)
        ),
        patch.object(engine, "scan_equity_nfo_now", return_value=["equity_alert"]) as mock_nfo,
        patch.object(engine, "scan_commodities_now", return_value=["commodity_alert"]) as mock_comm,
        patch.object(engine, "scan_crypto_now", return_value=["crypto_alert"]) as mock_crypto,
    ):
        orig_pytest = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            results = engine.scan_fresh_signals_now(segment="AUTO")
            mock_nfo.assert_called_once()
            mock_comm.assert_not_called()
            mock_crypto.assert_not_called()
            assert results == ["equity_alert"]
        finally:
            if orig_pytest is not None:
                os.environ["PYTEST_CURRENT_TEST"] = orig_pytest


def test_synthetic_sl_rejects_implausible_corrupted_spot_drop():
    """Verify Synthetic SL rejects impossible spot drops (>25% equity / >15% index) as corrupt feed anomalies."""
    alert = make_test_alert(
        alert_id="aa-options-momentum-mcx-ce-3700-0915-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="MCX",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=3700.0,
        contract_symbol="NSE:MCX26NOV3700CE",
        initial_entry_premium=104.15,
        trigger_level=104.15,
        stop_loss=81.24,
        ltp=102.8,
        underlying_spot=3762.3,
        metrics={
            "spot": 3762.3,
            "spot_invalidation_anchor": 3687.12,
            "dte": 5,
        },
        actionable_plan={
            "entry_price": 104.15,
            "spot_invalidation_anchor": 3687.12,
        },
        entry_price=104.15,
    )

    # Implausible spot drop to 364.1 (-90.13%) while option is completely healthy at 102.8
    eval_res = evaluate_synthetic_spot_sl(
        alert, current_option_ltp=102.8, current_spot_override=364.1
    )

    assert eval_res.is_invalidated is False, (
        "Must NOT invalidate on physically impossible 90% spot drop"
    )
    assert eval_res.is_freak_wick_shielded is True
    assert "feed anomaly" in (eval_res.shield_reason or "").lower()


def test_bearish_breakdown_put_option_payoff_is_positive_on_premium_expansion():
    """Verify that a BEARISH breakdown alert buying a Put option computes positive PnL when premium expands."""
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing

    alert = make_test_alert(
        alert_id="aa-intraday-breakdown-spark-polycab-bear-1130-20261118",
        alert_type="INTRADAY_BREAKDOWN_SPARK",
        symbol="POLYCAB",
        exchange="NSE",
        direction="BEARISH",
        option_type="PE",
        strike=7400.0,
        contract_symbol="NSE:POLYCAB26NOV7400PE",
        trigger_level=110.0,
        entry_price=110.0,
        stop_loss=85.80,
        target_level=136.4,
        ltp=139.35,
        underlying_spot=7332.5,
        time_horizon="INTRADAY",
        stage="IGNITED",
        actionable_plan={
            "action": "BUY_PUT",
            "recommended_entry": 110.0,
            "stop_loss": "₹85.80",
            "target": "₹136.4",
            "option_plan": {
                "contract_symbol": "NSE:POLYCAB26NOV7400PE",
                "entry_premium": 110.0,
                "initial_sl_premium": 85.80,
                "sl_premium": 85.80,
                "t1_premium": 136.4,
            },
            "trade_plan": {
                "entry_price": 7428.0,
                "invalidation_stop": 7562.01,
                "stop_distance_pts": 134.01,  # Spot risk points
            },
        },
    )

    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=139.35)

    assert eval_res is not None
    # Payoff on long Put must be positive when premium rose from 110.0 to 139.35 (+26.68%)
    assert eval_res.pnl_pct > 25.0, f"Expected positive pnl_pct > 25%, got {eval_res.pnl_pct}%"
    # Option risk is 110.0 - 85.8 = 24.2 pts; 29.35 / 24.2 = +1.21R, NOT deflated by spot risk (134.01 pts)!
    assert eval_res.r_multiple > 1.0, f"Expected r_multiple > 1.0R, got {eval_res.r_multiple}R"


def test_domestic_tick_rejects_venue_collision_and_spot_jump():
    """Verify AutoAlertEngine._on_domestic_tick rejects commodity venue ticks and >22% spot jumps on equity alerts."""
    engine = AutoAlertEngine()

    alert = make_test_alert(
        alert_id="aa-options-momentum-mcx-ce-3700-0915-20261118",
        alert_type="OPTIONS_MOMENTUM",
        symbol="MCX",
        exchange="NFO",
        direction="BULLISH",
        option_type="CE",
        strike=3700.0,
        contract_symbol="NSE:MCX26NOV3700CE",
        trigger_level=104.15,
        stop_loss=81.24,
        ltp=102.8,
        underlying_spot=3762.3,
        stage="IGNITED",
        is_live=True,
    )

    with engine._lock:
        engine._alerts.append(alert)

    # 1. Commodity tick collision: raw_sym has MCX: prefix or commodity symbol
    comm_tick = {
        "symbol": "MCX:NATGAS",
        "ltp": 298.0,
        "timestamp": 1794980000.0,
    }
    engine._on_domestic_tick(comm_tick)
    assert alert.underlying_spot == 3762.3, (
        f"Must not overwrite equity spot with commodity tick: {alert.underlying_spot}"
    )

    # 2. Implausible spot jump: tick ltp = 364.1 vs known spot 3762.3 (90% drop)
    corrupt_tick = {
        "symbol": "NSE:MCX",
        "ltp": 364.1,
        "timestamp": 1794980000.0,
    }
    engine._on_domestic_tick(corrupt_tick)
    assert alert.underlying_spot == 3762.3, (
        f"Must reject 90% corrupt spot jump: {alert.underlying_spot}"
    )
