"""
tests/test_production_vertical_slice.py
───────────────────────────────────────
Verifies the complete production vertical slice:
1. Detector signal ingestion -> AutoAlertEngine.record_alert
2. Executable R:R and position sizing computation
3. Signal policy evaluation:
   - REJECT: records POLICY_VETO in audit trail, rejects candidate, zero outbox staging
   - ACCEPT: records POLICY_ACCEPT in audit trail, computes net executable R:R, stages outbox intent
4. Atomic alert persistence + outbox delivery intent staging in a single SQLite transaction
5. Pre-dispatch revalidation (quote freshness SLA & anti-FOMO no-chase boundary)
6. Worker claim, dispatch, and acknowledgement lifecycle
7. Broker fill ingestion -> record_execution_fill -> get_internal_ledger_snapshot
"""

from __future__ import annotations

import time
import uuid
import pytest
from datetime import datetime
from pathlib import Path

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.order_lifecycle import (
    record_execution_fill,
    set_ledger_cash_baseline,
    get_internal_ledger_snapshot,
)
from engine.sqlite_store import SQLiteAlertStore
from engine.storage.alert_repository import AlertRepository


@pytest.fixture
def clean_engine(tmp_path: Path):
    db_file = tmp_path / "test_ledger.db"
    alerts_file = tmp_path / "test_alerts.json"
    store = SQLiteAlertStore(db_path=db_file)
    repo = AlertRepository(target_file_fn=lambda: alerts_file)
    engine = AutoAlertEngine(repository=repo)
    engine._alerts = []
    return engine, store, repo


def test_production_vertical_slice_veto_flow(clean_engine):
    engine, store, repo = clean_engine

    # 1. Candidate lacking verified option volume & OI should fail policy
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    unique_suffix = uuid.uuid4().hex[:6]
    veto_alert = AutoAlert(
        alert_id=f"aa-veto-{unique_suffix}",
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Unverified Momentum",
        summary="Missing turnover",
        ltp=150.0,
        trigger_level=150.0,
        target_level=240.0,
        stop_loss=135.0,
        confidence=88,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV24500CE",
        option_premium=150.0,
        option_stop_loss=135.0,
        created_at=now_str,
        environment="LIVE",
        is_live=True,
    )
    veto_alert.segment = "FNO_INDEX"
    veto_alert.metrics = {}  # Missing volume & OI

    recorded = engine.record_alert(veto_alert)
    assert recorded is False

    # Audit trail records POLICY_VETO
    audit_events = [e.get("event_type") or e.get("action") for e in veto_alert.audit_trail]
    assert "POLICY_VETO" in audit_events

    # No live outbox entry staged for vetoed alert
    from engine.sqlite_store import alert_sqlite_store

    pending = alert_sqlite_store.get_pending_outbox_entries()
    assert not any(e["alert_id"] == veto_alert.alert_id for e in pending)


def test_production_vertical_slice_acceptance_flow(clean_engine, tmp_path):
    engine, store, repo = clean_engine

    # 1. Create a well-formed confirmed option candidate with verified volume & OI
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    unique_suffix = uuid.uuid4().hex[:6]
    alert_id = f"aa-slice-nifty-{unique_suffix}"

    alert = AutoAlert(
        alert_id=alert_id,
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Bullish Momentum Breakout",
        summary="High conviction call option momentum trigger",
        ltp=150.0,
        trigger_level=150.0,
        target_level=240.0,
        stop_loss=135.0,
        confidence=88,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY26NOV24500CE",
        option_premium=150.0,
        option_stop_loss=135.0,
        created_at=now_str,
        environment="LIVE",
        is_live=True,
    )
    alert.segment = "FNO_INDEX"
    alert.option_target = 240.0
    alert.derivative_type = "OPT"
    alert.instrument_type = "OPTION"
    alert.metrics = {
        "volume": 250000.0,
        "oi": 1500000.0,
        "rvol": 2.5,
        "vix": 14.5,
        "hbcm": {
            "confluence_pass": True,
            "total_heavyweights": 5,
            "bullish_count": 5,
            "bearish_count": 0,
        },
    }
    alert.actionable_plan = {
        "recommended_lots": 1,
        "recommended_shares": 65,
        "lot_size": 65,
        "no_chase_boundary": 155.0,
    }
    alert._live_quote_snapshot = {
        "ltp": 150.0,
        "bid": 149.5,
        "ask": 150.5,
        "timestamp": time.time(),
    }

    # 2. Record alert through real AutoAlertEngine
    recorded = engine.record_alert(alert)
    assert recorded is True

    # 3. Verify executable R:R was populated
    assert "net_executable_rr" in alert.metrics
    assert alert.metrics["net_executable_rr"] is not None
    assert alert.metrics["net_executable_rr"] > 1.5

    # 4. Verify policy acceptance audit
    audit_events = [e.get("event_type") or e.get("action") for e in alert.audit_trail]
    assert "POLICY_ACCEPT" in audit_events

    # 5. Verify alert outbox has staged delivery intents in SQLite
    from engine.sqlite_store import alert_sqlite_store

    pending_entries = alert_sqlite_store.get_pending_outbox_entries()
    tg_entry = next(
        (
            e
            for e in pending_entries
            if e["alert_id"] == alert.alert_id and e["channel"] == "TELEGRAM"
        ),
        None,
    )
    assert tg_entry is not None
    assert tg_entry["status"] == "PENDING"
    assert tg_entry["payload"]["symbol"] == "NIFTY"
    assert tg_entry["payload"]["executable_rr"] is not None

    # 6. Pre-dispatch revalidation checks:
    # A. Fresh quote within boundary passes
    fresh_quote = {"ltp": 151.0, "timestamp": time.time()}
    ok, msg = engine.revalidate_pre_dispatch(alert, current_quote=fresh_quote)
    assert ok is True

    # B. Stale quote (>15s) in production mode fails
    stale_quote = {"ltp": 151.0, "timestamp": time.time() - 30.0}
    alert_prod = AutoAlert(
        alert_id=f"aa-prod-nifty-{unique_suffix}",
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Live Test",
        summary="Live test alert",
        ltp=150.0,
        trigger_level=150.0,
        target_level=240.0,
        stop_loss=135.0,
        environment="LIVE",
        is_live=True,
    )
    ok_stale, msg_stale = engine.revalidate_pre_dispatch(alert_prod, current_quote=stale_quote)
    assert ok_stale is False
    assert "exceeds 15.0s SLA" in msg_stale

    # C. Price breaching no-chase boundary fails
    chased_quote = {"ltp": 160.0, "timestamp": time.time()}  # > 155.0
    ok_chase, msg_chase = engine.revalidate_pre_dispatch(alert, current_quote=chased_quote)
    assert ok_chase is False
    assert "breached" in msg_chase

    # 7. Worker claim and lifecycle progression
    claimed = alert_sqlite_store.claim_pending_outbox_entries(worker_id="dispatcher-1", limit=10)
    assert len(claimed) >= 1
    oid = tg_entry["outbox_id"]

    assert alert_sqlite_store.mark_outbox_dispatched(oid, worker_id="dispatcher-1") is True
    assert alert_sqlite_store.mark_outbox_acknowledged(oid, worker_id="dispatcher-1") is True
    entry_done = alert_sqlite_store.get_outbox_entry(oid)
    assert entry_done["status"] == "ACKNOWLEDGED"

    # 8. Execution fill ingestion and ledger snapshot update
    account_id = f"test-slice-{uuid.uuid4().hex[:8]}"
    set_ledger_cash_baseline(account_id, 500000.0, actor="SYSTEM_TEST")

    # Order executed: Buy 65 qty @ 150.0, charges = 45.0
    fill = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ord-slice-001",
        broker_order_id="brk-slice-001",
        broker_trade_id=f"trd-{uuid.uuid4().hex[:6]}",
        symbol=alert.contract_symbol,
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=65,
        fill_price=150.0,
        charges=45.0,
        product="INTRADAY",
    )
    assert fill["sequence_num"] == 1

    # Ledger snapshot reflects position and updated cash
    snap = get_internal_ledger_snapshot(account_id)
    assert snap is not None
    assert snap["status"] == "AVAILABLE"
    assert snap["total_fills_count"] == 1
    # Cost = 65 * 150 = 9,750 + 45 charges = 9,795. Cash = 500,000 - 9,795 = 490,205
    assert snap["cash_balance"] == 490205.0
    assert len(snap["positions"]) == 1
    pos = snap["positions"][0]
    assert pos["symbol"] == "NIFTY26NOV24500CE"
    assert pos["quantity"] == 65
    assert pos["average_price"] == 150.0
