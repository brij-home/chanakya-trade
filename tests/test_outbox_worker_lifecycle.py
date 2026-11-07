"""
tests/test_outbox_worker_lifecycle.py
─────────────────────────────────────
Real-boundary regression tests for P0-2 acceptance:
1. AutoAlertEngine fails closed when transactional outbox staging fails:
   - publication_status == 'FAILED_STAGING'
   - audit trail records 'OUTBOX_STAGING_FAILED'
   - record_alert returns False
   - zero direct dispatch occurs
2. OutboxWorker claim -> dispatch -> acknowledge lifecycle.
3. OutboxWorker transport failure handling, retry budgeting, and terminal failure.
4. OutboxWorker lease expiration and crash recovery via reclaim_expired_leases.
5. Concurrent worker isolation: no duplicate claims on the same outbox entry.
"""

from __future__ import annotations

import concurrent.futures
import time
import uuid
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.outbox_worker import OutboxWorker
from engine.sqlite_store import SQLiteAlertStore
from engine.storage.alert_repository import AlertRepository


@pytest.fixture
def clean_outbox_env(tmp_path: Path):
    db_file = tmp_path / "test_outbox_worker.db"
    alerts_file = tmp_path / "test_outbox_alerts.json"
    store = SQLiteAlertStore(db_path=db_file)
    repo = AlertRepository(target_file_fn=lambda: alerts_file)
    return store, repo


def test_staging_failure_fails_closed_in_auto_alert_engine(clean_outbox_env):
    """Storage failure during save_alert_with_outbox must fail closed and stop dispatch."""
    store, repo = clean_outbox_env
    engine = AutoAlertEngine(repository=repo)
    engine._alerts = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    alert = AutoAlert(
        alert_id=f"aa-test-fail-staging-{uuid.uuid4().hex[:6]}",
        alert_type="OPTIONS_MOMENTUM",
        stage="CONFIRMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Momentum Breakout",
        summary="Test breakout",
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
        environment="TEST",
        is_live=False,
    )
    alert.segment = "FNO_INDEX"
    alert.option_target = 240.0
    alert.derivative_type = "OPT"
    alert.instrument_type = "OPTION"
    alert.metrics = {
        "volume": 200000.0,
        "oi": 1000000.0,
        "rvol": 2.5,
        "vix": 14.0,
    }
    alert.actionable_plan = {
        "recommended_lots": 1,
        "recommended_shares": 65,
        "lot_size": 65,
        "no_chase_boundary": 155.0,
    }

    # Simulate database crash or disk full on save_alert_with_outbox
    repo.save_alert_with_outbox = MagicMock(side_effect=RuntimeError("SQLite disk I/O error"))

    # Direct dispatch mock to prove zero dispatches happen
    engine._dispatch = MagicMock()

    recorded = engine.record_alert(alert)

    # 1. Pipeline returns False (fail-closed)
    assert recorded is False

    # 2. publication_status is marked FAILED_STAGING
    assert alert.publication_status == "FAILED_STAGING"

    # 3. Audit trail records OUTBOX_STAGING_FAILED
    audit_events = [e.get("event_type") or e.get("action") for e in alert.audit_trail]
    assert "OUTBOX_STAGING_FAILED" in audit_events

    # 4. Zero direct dispatch
    engine._dispatch.assert_not_called()


def test_outbox_worker_claim_and_acknowledge(clean_outbox_env):
    """Outbox worker claims pending entries, dispatches them, and marks them acknowledged."""
    store, _ = clean_outbox_env

    alert_dict = {
        "alert_id": "aa-worker-test-1",
        "symbol": "BANKNIFTY",
        "exchange": "NSE",
        "segment": "OPTIONS",
        "alert_type": "MOMENTUM",
        "stage": "CONFIRMED",
        "direction": "BULLISH",
        "ltp": 50000.0,
        "trigger_level": 50000.0,
        "target_level": 50500.0,
        "stop_loss": 49800.0,
        "confidence": 0.90,
        "version": 1,
    }
    outbox_entries = [
        {"channel": "TELEGRAM", "payload": {"headline": "BankNifty Breakout"}, "max_attempts": 3},
        {"channel": "SSE", "payload": {"headline": "BankNifty Breakout"}, "max_attempts": 3},
    ]

    store.save_alert_with_outbox(alert_dict, outbox_entries)

    dispatched_tg = []
    dispatched_sse = []

    worker = OutboxWorker(
        store=store,
        worker_id="worker-test-1",
        telegram_dispatcher=lambda payload: dispatched_tg.append(payload) or True,
        sse_dispatcher=lambda payload: dispatched_sse.append(payload) or True,
    )

    processed_count = worker.process_outbox_batch(limit=10)
    assert processed_count == 2
    assert len(dispatched_tg) == 1
    assert len(dispatched_sse) == 1

    # Pending entries should now be 0
    pending = store.get_pending_outbox_entries()
    assert len(pending) == 0


def test_outbox_worker_transport_failure_and_retry_budget(clean_outbox_env):
    """Transport errors transition entry to FAILED_RETRY, and to terminal FAILED when max_attempts is reached."""
    store, _ = clean_outbox_env

    alert_dict = {
        "alert_id": "aa-worker-retry-1",
        "symbol": "NIFTY",
        "exchange": "NSE",
        "segment": "OPTIONS",
        "alert_type": "MOMENTUM",
        "stage": "CONFIRMED",
        "direction": "BULLISH",
        "ltp": 24000.0,
        "trigger_level": 24000.0,
        "target_level": 24200.0,
        "stop_loss": 23900.0,
        "confidence": 0.85,
        "version": 1,
    }
    outbox_entries = [
        {"channel": "TELEGRAM", "payload": {"headline": "Test Retry"}, "max_attempts": 2},
    ]

    store.save_alert_with_outbox(alert_dict, outbox_entries)

    def failing_tg_dispatcher(payload):
        raise ConnectionResetError("Telegram network timeout")

    worker = OutboxWorker(
        store=store,
        worker_id="worker-fail-1",
        telegram_dispatcher=failing_tg_dispatcher,
    )

    # Attempt 1: Fails -> status becomes FAILED_RETRY
    processed = worker.process_outbox_batch(limit=10)
    assert processed == 0

    pending = store.get_pending_outbox_entries()
    assert len(pending) == 1
    entry = pending[0]
    assert entry["status"] == "FAILED_RETRY"
    assert entry["attempts"] == 1
    assert "Telegram network timeout" in (entry.get("last_error") or "")

    # Attempt 2: Fails again -> reaches max_attempts (2) -> terminal FAILED
    processed2 = worker.process_outbox_batch(limit=10)
    assert processed2 == 0

    # Entry is now terminal FAILED, so it no longer appears in get_pending_outbox_entries()
    pending2 = store.get_pending_outbox_entries()
    assert len(pending2) == 0


def test_outbox_worker_lease_expiry_reclamation(clean_outbox_env):
    """Expired worker leases are reclaimed so crashed worker jobs can be recovered."""
    store, _ = clean_outbox_env

    alert_dict = {
        "alert_id": "aa-lease-recovery-1",
        "symbol": "FINNIFTY",
        "exchange": "NSE",
        "segment": "OPTIONS",
        "alert_type": "MOMENTUM",
        "stage": "CONFIRMED",
        "direction": "BULLISH",
        "ltp": 22000.0,
        "trigger_level": 22000.0,
        "target_level": 22200.0,
        "stop_loss": 21900.0,
        "confidence": 0.85,
        "version": 1,
    }
    outbox_entries = [
        {"channel": "TELEGRAM", "payload": {"headline": "Lease Test"}, "max_attempts": 3},
    ]

    store.save_alert_with_outbox(alert_dict, outbox_entries)

    # Worker 1 leases the entry with lease_seconds=0.1s
    crashed_worker = OutboxWorker(
        store=store,
        worker_id="crashed-worker-1",
        lease_seconds=0.1,
    )
    claimed = store.claim_pending_outbox_entries(
        worker_id=crashed_worker.worker_id,
        lease_seconds=0.1,
        limit=5,
    )
    assert len(claimed) == 1

    # While lease is active, other workers cannot claim it
    healthy_worker = OutboxWorker(
        store=store,
        worker_id="healthy-worker-2",
        lease_seconds=30.0,
    )
    claimed_early = store.claim_pending_outbox_entries(
        worker_id=healthy_worker.worker_id,
        lease_seconds=30.0,
        limit=5,
    )
    assert len(claimed_early) == 0

    # Wait for the 0.1s lease to expire
    time.sleep(0.2)

    # Healthy worker reclaims expired leases
    reclaimed_count = healthy_worker.reclaim_expired_leases(older_than_seconds=0.1)
    assert reclaimed_count == 1

    # Healthy worker can now claim and process the entry
    claimed_after = store.claim_pending_outbox_entries(
        worker_id=healthy_worker.worker_id,
        lease_seconds=30.0,
        limit=5,
    )
    assert len(claimed_after) == 1
    assert claimed_after[0]["alert_id"] == "aa-lease-recovery-1"


def test_concurrent_worker_claim_isolation(clean_outbox_env):
    """Multiple workers claiming concurrently never receive duplicate leases for the same entry."""
    store, _ = clean_outbox_env

    # Stage 10 outbox entries
    for i in range(10):
        alert_dict = {
            "alert_id": f"aa-concur-{i}",
            "symbol": "NIFTY",
            "exchange": "NSE",
            "segment": "OPTIONS",
            "alert_type": "MOMENTUM",
            "stage": "CONFIRMED",
            "direction": "BULLISH",
            "ltp": 24000.0,
            "trigger_level": 24000.0,
            "target_level": 24200.0,
            "stop_loss": 23900.0,
            "confidence": 0.85,
            "version": 1,
        }
        outbox_entries = [
            {"channel": "TELEGRAM", "payload": {"index": i}, "max_attempts": 3},
        ]
        store.save_alert_with_outbox(alert_dict, outbox_entries)

    def _worker_claim(worker_num: int):
        w_id = f"worker-concur-{worker_num}"
        return store.claim_pending_outbox_entries(worker_id=w_id, lease_seconds=30.0, limit=10)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_worker_claim, i) for i in range(5)]
        results = [f.result() for f in futures]

    all_claimed_ids = []
    for batch in results:
        for entry in batch:
            all_claimed_ids.append(entry["outbox_id"])

    # Total claimed must equal 10, with zero duplicates across workers
    assert len(all_claimed_ids) == 10
    assert len(set(all_claimed_ids)) == 10


def test_telegram_outbox_dispatch_renders_dict_to_string(clean_outbox_env):
    """
    Regression: OutboxWorker TELEGRAM dispatch must render the dict payload to a
    string before calling send_push().  Passing the raw dict caused:
        TypeError: expected string or bytes-like object, got 'dict'

    Invariants verified:
    1. The captured argument received by send_push is a str, never a dict.
    2. The str is non-empty.
    3. The outbox entry is acknowledged (processed_count == 1).
    """
    store, _ = clean_outbox_env

    alert_dict = {
        "alert_id": "aa-crypto-momentum-ethusdt-demand-20261104-v1",
        "symbol": "ETHUSDT",
        "exchange": "NSE",
        "segment": "CRYPTO",
        "alert_type": "CRYPTO_MOMENTUM",
        "stage": "CONFIRMED",
        "direction": "BULLISH",
        "headline": "ETHUSDT Demand Zone Activation",
        "summary": "ETH/USDT reclaiming institutional demand zone at 2800.",
        "ltp": 2850.0,
        "trigger_level": 2800.0,
        "target_level": 3200.0,
        "stop_loss": 2700.0,
        "confidence": 82,
        "version": 1,
        "is_live": True,
        "environment": "LIVE",
    }
    outbox_entries = [
        {
            "channel": "TELEGRAM",
            "event_version": 1,
            "payload": {
                "alert_id": alert_dict["alert_id"],
                "symbol": alert_dict["symbol"],
                "headline": alert_dict["headline"],
                "executable_rr": 4.0,
                "is_live": True,
                "environment": "LIVE",
            },
            "max_attempts": 3,
        },
    ]

    store.save_alert_with_outbox(alert_dict, outbox_entries)

    received_args: list = []

    def _capture_telegram(payload: dict) -> bool:
        # This is the custom telegram_dispatcher injected for test isolation.
        # It should NOT be called — OutboxWorker should NOT be passing raw dicts
        # to send_push.  If this is ever called with a dict, the bug is back.
        received_args.append(("DICT_DISPATCHER", payload))
        return True

    # Build a worker WITHOUT a custom telegram_dispatcher so the real
    # render path runs, but intercept send_push via monkeypatching.
    captured_send_push_calls: list = []

    original_dispatch = OutboxWorker.dispatch_channel_entry

    def _patched_dispatch(self, entry):
        """Wraps dispatch_channel_entry to intercept the final send_push call."""
        channel = str(entry.get("channel") or "").upper().strip()
        if channel != "TELEGRAM":
            return original_dispatch(self, entry)

        # Patch send_push at the module level for this call

        # Inject fake telegram_dispatcher to capture the rendered string
        self._telegram_dispatcher = lambda payload: captured_send_push_calls.append(payload) or True
        return original_dispatch(self, entry)

    # Instead: use a custom telegram_dispatcher that checks the type
    type_checked_calls: list = []

    def _type_checking_dispatcher(payload) -> bool:
        type_checked_calls.append(payload)
        # The dispatcher receives the raw dict payload (from outbox_worker's
        # _telegram_dispatcher shortcut path at line 67-68), so we need to
        # test the *non-shortcut* path.  Set dispatcher to None to force the
        # render path, then intercept send_push.
        return True

    # To test the render path specifically, we need to NOT inject a
    # telegram_dispatcher and instead mock bot.telegram_bot.send_push.
    import unittest.mock as _mock

    string_received: list = []

    with _mock.patch("bot.telegram_bot.get_telegram_bot") as mock_get_bot:
        mock_bot = _mock.MagicMock()

        def _capture_send_push(msg, **kwargs):
            string_received.append(msg)
            return True

        mock_bot.send_push.side_effect = _capture_send_push
        mock_get_bot.return_value = mock_bot

        worker = OutboxWorker(store=store, worker_id="worker-render-test")
        processed_count = worker.process_outbox_batch(limit=10)

    # 1. The entry was processed successfully
    assert processed_count == 1, f"Expected 1 processed entry, got {processed_count}"

    # 2. send_push was called exactly once
    assert len(string_received) == 1, (
        f"Expected send_push called once, got {len(string_received)} calls"
    )

    # 3. The argument is a str (not a dict) — this is the core regression guard
    rendered = string_received[0]
    assert isinstance(rendered, str), (
        f"send_push must receive a str; got {type(rendered).__name__!r}. "
        "Regression: OutboxWorker passed raw dict payload to send_push."
    )

    # 4. The rendered string is non-empty
    assert rendered.strip(), "send_push received an empty string — rendering failed silently"


def test_outbox_gate_suppression_and_chat_id_routing(clean_outbox_env):
    """
    Regression: Alerts held by the Apex Channel Gate must NEVER be staged for TELEGRAM.
    Eligible alerts must include segment-specific chat_id to prevent leaking into default chat.
    """
    store, repo = clean_outbox_env
    engine = AutoAlertEngine(repository=repo)
    engine._alerts = []

    # 1. Early warning with confidence 75% (held by Apex Gate)
    held_alert = AutoAlert(
        alert_id="aa-pfc-held-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="PFC",
        exchange="NSE",
        direction="BULLISH",
        headline="PFC Early Warning",
        summary="PFC consolidating near CPR",
        ltp=6.0,
        trigger_level=6.0,
        target_level=9.6,
        stop_loss=4.2,
        confidence=75,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        environment="LIVE",
        is_live=True,
    )
    held_alert.segment = "FNO_STOCK"
    held_alert.strike = 325.0
    held_alert.option_type = "CE"
    held_alert.option_premium = 6.0
    held_alert.underlying_spot = 318.0
    held_alert.metrics = {"volume": 200000, "oi": 2500000, "vol_oi_ratio": 2.0}

    # Capture staged entries
    staged_calls = []

    def _mock_save(a, entries):
        staged_calls.append((a, entries))
        a_dict = a.to_dict() if hasattr(a, "to_dict") else a
        return store.save_alert_with_outbox(a_dict, entries)

    repo.save_alert_with_outbox = _mock_save

    import unittest.mock as _mock
    import types

    mock_policy_res = types.SimpleNamespace(
        decision="ACCEPT",
        conviction_tier="HIGH_CONVICTION",
        to_dict=lambda: {},
        blocking_gate=None,
    )
    mock_scrutiny_held = types.SimpleNamespace(
        status="APPROVED",
        score=75,
        trap_risk_warning=None,
        rejection_reason=None,
        to_dict=lambda: {"status": "APPROVED", "score": 75},
    )
    mock_scrutiny_qual = types.SimpleNamespace(
        status="APPROVED",
        score=92,
        trap_risk_warning=None,
        rejection_reason=None,
        to_dict=lambda: {"status": "APPROVED", "score": 92},
    )
    with (
        _mock.patch("engine.signal_policy.evaluate_candidate_policy", return_value=mock_policy_res),
        _mock.patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.scrutinize_alert",
            return_value=mock_scrutiny_held,
        ),
        _mock.patch("engine.alerts._is_market_hours", return_value=True),
    ):
        engine.record_alert(held_alert)

    assert len(staged_calls) == 1
    _, entries_held = staged_calls[0]
    channels_held = [e["channel"] for e in entries_held]
    assert "SSE" in channels_held
    assert "TELEGRAM" not in channels_held, (
        "Alert held by Apex Gate must not be staged for TELEGRAM"
    )

    # 2. Apex alert that qualifies for Telegram
    qual_alert = AutoAlert(
        alert_id="aa-pfc-qual-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="ACTIONABLE",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Confirmed Breakout",
        summary="INFY confirmed breakout",
        ltp=6.0,
        trigger_level=6.0,
        target_level=10.0,
        stop_loss=4.2,
        confidence=92,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        environment="LIVE",
        is_live=True,
    )
    qual_alert.segment = "FNO_STOCK"
    qual_alert.strike = 325.0
    qual_alert.option_type = "CE"
    qual_alert.option_premium = 6.0
    qual_alert.underlying_spot = 318.0
    qual_alert.metrics = {"volume": 200000, "oi": 2500000, "vol_oi_ratio": 2.0}

    staged_calls.clear()
    with (
        _mock.patch("engine.signal_policy.evaluate_candidate_policy", return_value=mock_policy_res),
        _mock.patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.scrutinize_alert",
            return_value=mock_scrutiny_held,
        ),
        _mock.patch("engine.alerts._is_market_hours", return_value=True),
    ):
        pass
    with (
        _mock.patch("engine.signal_policy.evaluate_candidate_policy", return_value=mock_policy_res),
        _mock.patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.scrutinize_alert",
            return_value=mock_scrutiny_qual,
        ),
        _mock.patch("engine.alerts._is_market_hours", return_value=True),
    ):
        engine.record_alert(qual_alert)

    assert len(staged_calls) == 1
    _, entries_qual = staged_calls[0]
    channels_qual = [e["channel"] for e in entries_qual]
    assert "TELEGRAM" in channels_qual

    tg_entry = next(e for e in entries_qual if e["channel"] == "TELEGRAM")
    assert tg_entry["payload"].get("chat_id") is not None
    assert tg_entry["payload"]["segment"] == "FNO_STOCK"

    # 3. Verify OutboxWorker routes with exact chat_id
    import unittest.mock as _mock

    captured_chats = []

    with _mock.patch("bot.telegram_bot.get_telegram_bot") as mock_get_bot:
        mock_bot = _mock.MagicMock()

        def _capture_send_push(msg, chat_id=None, **kwargs):
            captured_chats.append(chat_id)
            return True

        mock_bot.send_push.side_effect = _capture_send_push
        mock_get_bot.return_value = mock_bot

        worker = OutboxWorker(store=store, worker_id="worker-routing-test")
        worker.process_outbox_batch(limit=10)

    assert len(captured_chats) >= 1
    assert captured_chats[0] is not None
    assert captured_chats[0] != "", "chat_id must not be empty or None"
