"""
tests/test_oms_chaos_recovery.py
────────────────────────────────
Wave 5 OMS Chaos & Restart Recovery Acceptance Suite.

Exercises:
  1. Timeout/dropped ACK -> UNKNOWN_FREEZE fail-closed block -> restart recovery via recover_stale_inflight_orders().
  2. Incremental partial-fill polling across sync_execution_orders() when broker status remains PARTIALLY_FILLED.
  3. Idempotent duplicate trade fills vs conflicting fill replay rejection.
  4. Cross-account OrderSocket update/fill rejection.
  5. Live execution qualification gate enforcement (LIVE_EXECUTION_QUALIFIED unset blocks live execution while keeping status CONFIRMED).
  6. Telegram calibrated confidence suppression for HALTED / high-friction / single-pillar setups.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engine.alert_model import AutoAlert


def _seed_ledger_row(
    order_id: str,
    *,
    account_id: str = "FYERS_CHAOS_1",
    status: str = "OPEN",
    mode: str = "EXECUTE",
    broker_order_id: str | None = None,
    quantity: int = 75,
    filled_quantity: int = 0,
    parent_order_id: str | None = None,
):
    from engine.order_lifecycle import _get_orders_db, _init_orders_db

    _init_orders_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _get_orders_db() as conn:
        conn.execute("DELETE FROM execution_fills WHERE order_id = ?", (order_id,))
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger
            (order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
             order_type, product, status, mode, broker_order_id, account_id,
             filled_quantity, parent_order_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                f"idemp-{order_id}",
                "NIFTY26N2425000CE",
                "NFO",
                "FNO_INDEX",
                "BUY",
                quantity,
                140.0,
                "LIMIT",
                "MIS",
                status,
                mode,
                broker_order_id,
                account_id,
                filled_quantity,
                parent_order_id,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()


def test_oms_chaos_dropped_ack_freeze_and_recovery(monkeypatch):
    """UNKNOWN_FREEZE intent cannot be re-executed, and restart recovery syncs once broker reports final status."""
    from engine.modes import ModeInfo, TradingMode
    from engine.order_lifecycle import (
        execute_order_intent,
        recover_stale_inflight_orders,
    )

    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")
    _seed_ledger_row(
        "LIVE-FROZEN-1",
        status="UNKNOWN_FREEZE",
        broker_order_id="BRK-FROZEN-1",
    )

    with patch(
        "engine.order_lifecycle.get_trading_mode",
        return_value=ModeInfo(
            mode=TradingMode.EXECUTE,
            is_observe=False,
            is_simulate=False,
            is_execute=True,
            description="Live",
        ),
    ):
        with pytest.raises(ValueError):
            execute_order_intent("LIVE-FROZEN-1")

    mock_broker = MagicMock()
    mock_broker.get_orders.return_value = [
        SimpleNamespace(
            order_id="BRK-FROZEN-1",
            status="FILLED",
            filled_quantity=75,
            average_price=141.25,
        )
    ]
    with (
        patch("brokers.session.get_execution_broker", return_value=mock_broker),
        patch("brokers.session.get_execution_broker_key", return_value="fyers"),
    ):
        rec = recover_stale_inflight_orders("FYERS_CHAOS_1")

    assert rec["resolved_via_sync"] >= 1
    assert "LIVE-FROZEN-1" not in rec["remaining_unknown_freeze"]


def test_oms_chaos_incremental_partial_fill_polling():
    """Repeated sync_execution_orders polls with status=PARTIALLY_FILLED must still increment filled_quantity."""
    from engine.order_lifecycle import _get_orders_db, sync_execution_orders

    _seed_ledger_row(
        "LIVE-PART-POLL-1",
        status="PARTIALLY_FILLED",
        broker_order_id="BRK-PART-POLL-1",
        quantity=75,
        filled_quantity=25,
    )
    mock_broker = MagicMock()
    mock_broker.get_orders.return_value = [
        SimpleNamespace(
            order_id="BRK-PART-POLL-1",
            status="PARTIALLY_FILLED",
            filled_quantity=50,
            average_price=142.0,
        )
    ]
    with (
        patch("brokers.session.get_execution_broker", return_value=mock_broker),
        patch("brokers.session.get_execution_broker_key", return_value="fyers"),
    ):
        res = sync_execution_orders()

    assert res["ledger_orders_updated"] >= 1
    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT status, filled_quantity, average_fill_price FROM orders_ledger WHERE order_id = ?",
            ("LIVE-PART-POLL-1",),
        ).fetchone()
    assert row["status"] == "PARTIALLY_FILLED"
    assert int(row["filled_quantity"]) == 50
    assert abs(float(row["average_fill_price"]) - 142.0) < 0.01


def test_oms_chaos_duplicate_and_conflicting_fill_replay():
    """Identical broker_trade_id replay is idempotent; conflicting price/qty raises ValueError."""
    from engine.order_lifecycle import record_execution_fill

    _seed_ledger_row("LIVE-FILL-DUP", status="OPEN", broker_order_id="BRK-FILL-DUP")
    fixed_ts = "2026-11-26T06:30:00+00:00"
    first = record_execution_fill(
        account_id="FYERS_CHAOS_1",
        broker_name="fyers",
        order_id="LIVE-FILL-DUP",
        broker_order_id="BRK-FILL-DUP",
        broker_trade_id="TRD-IDEMP-99",
        symbol="NIFTY26N2425000CE",
        exchange="NFO",
        segment="FNO_INDEX",
        side="BUY",
        quantity=25,
        fill_price=140.5,
        fill_time=fixed_ts,
    )
    assert first.get("is_idempotent_retry", False) is False

    dup = record_execution_fill(
        account_id="FYERS_CHAOS_1",
        broker_name="fyers",
        order_id="LIVE-FILL-DUP",
        broker_order_id="BRK-FILL-DUP",
        broker_trade_id="TRD-IDEMP-99",
        symbol="NIFTY26N2425000CE",
        exchange="NFO",
        segment="FNO_INDEX",
        side="BUY",
        quantity=25,
        fill_price=140.5,
        fill_time=fixed_ts,
    )
    assert dup["is_idempotent_retry"] is True

    with pytest.raises(ValueError):
        record_execution_fill(
            account_id="FYERS_CHAOS_1",
            broker_name="fyers",
            order_id="LIVE-FILL-DUP",
            broker_order_id="BRK-FILL-DUP",
            broker_trade_id="TRD-IDEMP-99",
            symbol="NIFTY26N2425000CE",
            exchange="NFO",
            segment="FNO_INDEX",
            side="BUY",
            quantity=25,
            fill_price=199.0,  # conflicting fill price!
            fill_time=fixed_ts,
        )


def test_oms_chaos_cross_account_rejection():
    """OrderSocket update from a foreign clientId must be rejected without touching ledger."""
    from engine.order_lifecycle import apply_fyers_stream_order_update

    _seed_ledger_row("LIVE-ACCT-LOCK", account_id="ACC_OWNER", status="SUBMITTING")
    res = apply_fyers_stream_order_update(
        {
            "orders": {
                "id": "BRK-FOREIGN-1",
                "orderTag": "LIVE-ACCT-LOCK",
                "status": 2,
                "filledQty": 75,
                "tradedPrice": 140.0,
                "clientId": "ACC_INTRUDER",
            }
        }
    )
    assert res["updated"] is False
    assert res["reason"] == "ACCOUNT_MISMATCH"


def test_live_qualification_gate_blocks_unqualified_confirmed_order(monkeypatch):
    """When LIVE_EXECUTION_QUALIFIED is unset, EXECUTE mode stays fail-closed at CONFIRMED (no SUBMITTED call)."""
    from engine.modes import ModeInfo, TradingMode
    from engine.order_lifecycle import _get_orders_db, execute_order_intent

    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)
    _seed_ledger_row("LIVE-QUAL-BLK", status="CONFIRMED", mode="EXECUTE")

    with (
        patch(
            "engine.order_lifecycle.get_trading_mode",
            return_value=ModeInfo(
                mode=TradingMode.EXECUTE,
                is_observe=False,
                is_simulate=False,
                is_execute=True,
                description="Live",
            ),
        ),
        patch(
            "engine.order_lifecycle._resolve_order_instrument",
            return_value=("NIFTY26N2425000CE", "NFO", "FNO_INDEX"),
        ),
    ):
        with pytest.raises(PermissionError):
            execute_order_intent("LIVE-QUAL-BLK")

    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT status FROM orders_ledger WHERE order_id = ?", ("LIVE-QUAL-BLK",)
        ).fetchone()
    assert row["status"] == "CONFIRMED"


def test_telegram_calibration_gate_suppresses_high_friction_and_halted():
    """evaluate_telegram_confidence_calibration vetoes high-friction scalps and HALTED detectors."""
    from engine.confidence_calibrator import evaluate_telegram_confidence_calibration

    tight_wide = AutoAlert(
        alert_id="aa-test-tg-cal-fric-20261126",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Scalp",
        summary="Wide spread scalp",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,
        target_level=110.0,
        strike=25000.0,
        option_type="CE",
        lot_size=65,
        confidence=89,
        bid_ask_spread_pct=4.0,
        metrics={"signals": ["BREAKOUT_CONFIRMED", "VWAP_RECLAIM"]},
    )
    ok_fric, rep_fric, reason_fric = evaluate_telegram_confidence_calibration(tight_wide, 80)
    assert ok_fric is False
    assert rep_fric.high_friction_risk is True
    assert "friction" in reason_fric.lower()

    halted_alert = AutoAlert(
        alert_id="aa-test-tg-cal-halt-20261126",
        alert_type="BAD_DETECTOR",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY Setup",
        summary="Breakout above VWAP",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        lot_size=65,
        confidence=92,
        metrics={"signals": ["BREAKOUT_CONFIRMED", "VWAP_RECLAIM"]},
    )
    mock_metrics = SimpleNamespace(status="HALTED", sample_count=12, expectancy=-0.45)
    with patch(
        "engine.detector_circuit_breaker.detector_circuit_breaker.get_metrics",
        return_value=mock_metrics,
    ):
        ok_halt, rep_halt, reason_halt = evaluate_telegram_confidence_calibration(halted_alert, 80)
    assert ok_halt is False
    assert rep_halt.calibration_status == "HALTED"
    assert "HALTED" in reason_halt


def test_rate_gate_reactive_cooldown_preserves_order_priority():
    """notify_rate_limited() must pace DATA calls cleanly without stalling priority-0 ORDER execution."""
    from market.fyers_rate_gate import FyersCallCategory, UnifiedFyersRateGate

    gate = UnifiedFyersRateGate(
        plan="PRIME", max_per_sec=100.0, max_per_min=5000.0, max_per_day=500000.0
    )
    gate.reset_state()
    gate.notify_rate_limited(cooldown_sec=0.8)

    import time

    t_ord = gate._calculate_sleep_needed(time.time(), category=FyersCallCategory.ORDER)
    t_hist = gate._calculate_sleep_needed(time.time(), category=FyersCallCategory.HISTORICAL)
    assert t_ord < 0.05
    assert t_hist >= 0.65


def test_telegram_gate_clamps_uncalibrated_single_pillar_and_dict_alerts():
    """Uncalibrated <2-pillar AutoAlert AND dict alerts must not bypass min_conf>=85 calibration gates."""
    from types import SimpleNamespace
    from engine.alert_model import AutoAlert
    from engine.alert_preferences import AlertPreferencesManager
    from engine.confidence_calibrator import evaluate_telegram_confidence_calibration

    uncal_dm = SimpleNamespace(status="UNCALIBRATED", sample_count=2, expectancy=0.0)
    one_pillar_alert = AutoAlert(
        alert_id="aa-uncal-1p-20261126",
        alert_type="UNSEEN_NEW_DETECTOR",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Signal",
        summary="Single OB touch",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        strike=25000.0,
        option_type="CE",
        lot_size=65,
        confidence=92,
        metrics={"signals": ["PDH_TOUCH"]},
    )
    dict_alert = {
        "alert_id": "aa-dict-uncal-20261126",
        "alert_type": "UNSEEN_NEW_DETECTOR",
        "stage": "IGNITED",
        "symbol": "NIFTY",
        "exchange": "NFO",
        "segment": "FNO_INDEX",
        "direction": "BULLISH",
        "headline": "NIFTY 25000 CE Signal",
        "summary": "Single OB touch",
        "ltp": 150.0,
        "trigger_level": 150.0,
        "stop_loss": 120.0,
        "target_level": 240.0,
        "option_type": "CE",
        "lot_size": 65,
        "confidence": 92,
        "metrics": {"signals": ["PDH_TOUCH"]},
    }

    mgr = AlertPreferencesManager()
    orig_min_conf = mgr.telegram.min_confidence
    mgr.telegram.min_confidence = 85
    try:
        with patch(
            "engine.detector_circuit_breaker.detector_circuit_breaker.get_metrics",
            return_value=uncal_dm,
        ):
            ok_1p, rep_1p, reason_1p = evaluate_telegram_confidence_calibration(
                one_pillar_alert, 85
            )
            assert ok_1p is False
            assert rep_1p.calibrated_confidence <= 84
            assert "Uncalibrated" in reason_1p

            allowed_dict, dict_reason = mgr.explain_alert_allowed(dict_alert, channel="telegram")
            assert allowed_dict is False
            assert "Uncalibrated" in dict_reason
    finally:
        mgr.telegram.min_confidence = orig_min_conf


def test_extracted_intelligence_router_preserves_routes_and_reexports():
    """Strangler extraction of web/routers/intelligence_api.py must keep mounted routes & web.skills exports intact."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import web.skills as skills_mod
    from web.routers import intelligence_router, options_desk_router, macro_telemetry_router

    test_app = FastAPI()
    test_app.include_router(skills_mod.router)
    openapi_paths = set((test_app.openapi().get("paths") or {}).keys())
    for expected in (
        "/skills/security_360",
        "/skills/persona/council",
        "/skills/journal/list",
        "/skills/terminal/target_setup",
        "/skills/options_chain_integrity",
        "/skills/models/list",
        "/skills/gex_snapshot",
        "/skills/conviction_score",
        "/skills/trade_plan",
        "/skills/telegram_blast",
        "/skills/options/defined_risk_spreads",
        "/skills/dashboard_snapshot",
        "/skills/live_tickers",
        "/skills/global_macro",
        "/skills/market_overview",
        "/skills/tax/calculate",
        "/skills/fii_flow",
        "/skills/telemetry/summary",
        "/skills/portfolio/health",
    ):
        assert expected in openapi_paths, f"Missing expected route after extraction: {expected}"

    client = TestClient(test_app)
    resp = client.get("/skills/models/list")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"

    assert hasattr(skills_mod, "skill_security_360")
    assert hasattr(skills_mod, "Security360Request")
    assert hasattr(skills_mod, "skill_gex_snapshot")
    assert hasattr(skills_mod, "_fetch_options_and_spot")
    assert hasattr(skills_mod, "skill_dashboard_snapshot")
    assert hasattr(skills_mod, "_compute_live_tickers_sync")
    assert len(intelligence_router.routes) > 0
    assert len(options_desk_router.routes) > 0
    assert len(macro_telemetry_router.routes) > 0
