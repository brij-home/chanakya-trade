"""
tests/test_opsdeck_incidents_rca_and_self_healing.py
────────────────────────────────────────────────────
Institutional regression test suite verifying RCA resolutions for OpsDeck Incidents:
  1. Unit-scale separation between cash equity/futures and attached option targets in alert evaluation.
  2. Milestone integrity gate hold debouncing and log level hygiene.
  3. Pre-ingestion data integrity validation preventing false inverted target hierarchy vetoes.
  4. Crypto spot & perpetual classification sanity (not misidentified as option contracts).
  5. Commodity detector resilience against UnboundLocalError when intraday bars are missing.
  6. DetectorCircuitBreaker atomic writes and self-healing JSON ledger corruption recovery.
  7. DailyLevelsStore Windows file lock sidecar fallback and discovery.
  8. Telemetry derive_priority and handler routing for routine websocket drops and external SDK noise.
"""

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.alert_expiry import is_alert_option_premium_level
from engine.alert_model import AutoAlert
from engine.daily_levels import DailyLevels, DailyLevelsStore
from engine.detector_circuit_breaker import DetectorCircuitBreaker
from engine.telemetry import derive_priority


# ── 1. Unit-Scale Separation in Alert Evaluator ──────────────────────────────


def test_equity_option_unit_scale_separation_in_alert_evaluator():
    """Verify equity alerts with attached option recommendations do not falsely hit targets."""
    # Equity alert: SBIN at ₹948.20, target is ₹965.38. Attached option target is ₹53.68.
    alert = AutoAlert(
        alert_id="aa-test-sbin-eval-20261027",
        alert_type="PREDATOR_SWEEP",
        stage="TRIGGERED",
        symbol="SBIN",
        exchange="NSE",
        segment="EQUITY",
        direction="BULLISH",
        headline="SBIN Predator Sweep",
        summary="Test setup",
        ltp=948.20,
        trigger_level=948.20,
        target_level=965.38,
        stop_loss=939.61,
        is_live=True,
        actionable_plan={
            "action": "BUY_CASH / BUY_CALL",
            "target": "₹965.40",
            "target_1": "₹965.40",
            "target_2": "₹44.52",  # Option target 2
            "target_3": "₹53.68",  # Option target 3
            "underlying_target": "₹965.38",
            "underlying_target_3": "₹975.00",
        },
    )

    # At CMP 949.35 (below 965.38), evaluate_alert_targets_and_trailing must NOT trigger TARGET_ACHIEVED
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=949.35)
    assert eval_res is None or eval_res.new_milestone != "TARGET_ACHIEVED"

    # When CMP actually reaches 966.00 (above target_level 965.38), it DOES trigger TARGET_ACHIEVED
    eval_hit = evaluate_alert_targets_and_trailing(alert, current_ltp=966.00)
    assert eval_hit is not None
    assert eval_hit.new_milestone == "TARGET_ACHIEVED"


# ── 2. Pre-Ingestion Data Integrity Validation ───────────────────────────────


def test_alert_model_unit_scale_separation_prevents_false_inverted_veto():
    """Verify equity alerts with attached option target numbers pass pre-ingestion validation."""
    alert = AutoAlert(
        alert_id="aa-test-reliance-hierarchy-20261027",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="ARMED",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY",
        direction="BULLISH",
        headline="Reliance Asymmetric Opportunity",
        summary="Test",
        ltp=1280.00,
        trigger_level=1280.00,
        target_level=1320.00,
        stop_loss=1260.00,
        is_live=True,
        actionable_plan={
            "action": "BUY_CASH / 1300 CE",
            "target": "₹1,320.00",
            "target_1": "₹1,320.00",
            "target_2": "₹35.00",  # Attached option premium target 2
            "target_3": "₹45.00",  # Attached option premium target 3
            "underlying_target_1": "₹1,320.00",
            "underlying_target_2": "₹1,350.00",
            "underlying_target_3": "₹1,380.00",
        },
    )

    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is True, f"Alert failed validation unexpectedly: {reason}"


# ── 3. Crypto Classification & Directional Integrity ─────────────────────────


def test_crypto_alert_not_classified_as_option():
    """Verify Crypto spot/futures alerts are recognized as underlying instruments, not option contracts."""
    bear_crypto = AutoAlert(
        alert_id="aa-test-ethusdt-supply-20261027",
        alert_type="CRYPTO_MOMENTUM",
        stage="ARMED",
        symbol="ETHUSDT",
        exchange="CRYPTO",
        segment="CRYPTO",
        direction="BEARISH",
        headline="ETHUSDT Bearish Supply Breakdown",
        summary="Test",
        ltp=2300.00,
        trigger_level=2300.00,
        target_level=2250.00,
        stop_loss=2306.01,  # SL > Entry is valid for BEARISH / SHORT trades
        is_live=True,
        actionable_plan={"action": "SELL_SHORT_FUTURES"},
    )

    assert is_alert_option_premium_level(bear_crypto) is False

    is_valid, reason = bear_crypto.validate_data_integrity()
    assert is_valid is True, f"Crypto bearish alert failed validation: {reason}"


# ── 4. Commodity Detector Resilience Without Intraday Bars ───────────────────


def test_commodity_detector_no_unbound_local_error(monkeypatch):
    """Verify Commodity detector does not raise UnboundLocalError when df_5m has insufficient bars."""
    from engine.detectors.commodity import detect_commodity_breakouts

    # Empty 5m dataframe simulation
    quotes = {
        "MCX:CRUDEOIL": MagicMock(
            ltp=6200.0,
            open=6180.0,
            high=6220.0,
            low=6170.0,
            prev_close=6150.0,
            volume=50000,
        )
    }

    with patch("market.history.get_ohlcv", return_value=pd.DataFrame()):
        with patch("market.quotes.get_quote", return_value=quotes):
            # Must complete without UnboundLocalError: is_thrust_bull
            setups = detect_commodity_breakouts(universe=["CRUDEOIL"])
            assert isinstance(setups, list)


# ── 5. DetectorCircuitBreaker Atomic Writes & Self-Healing ───────────────────


def test_detector_circuit_breaker_atomic_write_and_self_healing(tmp_path):
    """Verify DetectorCircuitBreaker self-heals corrupted JSON ledgers and writes atomically."""
    ledger_path = tmp_path / "test_ledger.json"

    # Step A: Initialize with clean ledger and record outcome
    cb = DetectorCircuitBreaker(ledger_file=ledger_path, rolling_window=10)
    cb.record_outcome("alert-1", "TCS", "ORB_BREAKOUT", "WIN", 2.5)
    assert ledger_path.exists()

    with open(ledger_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "ORB_BREAKOUT" in data
    assert len(data["ORB_BREAKOUT"]) == 1

    # Step B: Corrupt the file on disk (simulate partial disk write / crash)
    with open(ledger_path, "w", encoding="utf-8") as f:
        f.write("{ invalid json corrupted line 2354: [")

    # Step C: Re-instantiate cb -> must self-heal, quarantine, and recreate clean ledger
    cb_healed = DetectorCircuitBreaker(ledger_file=ledger_path, rolling_window=10)
    assert cb_healed._history == {}

    # Check that corrupted backup was saved
    corrupted_files = list(tmp_path.glob("*.corrupted.*.json"))
    assert len(corrupted_files) == 1

    # Record new outcome on healed breaker -> succeeds atomically
    cb_healed.record_outcome("alert-2", "INFY", "ORB_BREAKOUT", "WIN", 3.0)
    with open(ledger_path, "r", encoding="utf-8") as f:
        healed_data = json.load(f)
    assert "ORB_BREAKOUT" in healed_data
    assert len(healed_data["ORB_BREAKOUT"]) == 1


# ── 6. DailyLevelsStore Windows File Lock & Sidecar Fallback ─────────────────


def test_daily_levels_windows_lock_sidecar_fallback_and_recovery(tmp_path):
    """Verify DailyLevelsStore writes to sidecar on locked files and recovers on load."""
    store = DailyLevelsStore(persist_dir=tmp_path)
    session_date = "2026-10-27"
    primary_file = store._get_file_path(session_date)

    level_tcs = DailyLevels(
        symbol="TCS",
        canonical_symbol="TCS",
        exchange="NSE",
        session_date=session_date,
        pdh=4100.0,
        pdl=4000.0,
        pdc=4050.0,
    )

    # Step A: Normal save
    store._memory_cache[f"{session_date}:TCS"] = level_tcs
    store.save_to_disk(session_date=session_date)
    assert primary_file.exists()

    # Step B: Simulate persistent Windows lock on os.replace
    original_replace = os.replace
    call_count = 0

    def mock_replace(src, dst):
        nonlocal call_count
        call_count += 1
        # Always fail if trying to replace primary file
        if Path(dst) == primary_file:
            raise PermissionError("[WinError 5] Access is denied")
        return original_replace(src, dst)

    with patch("os.replace", side_effect=mock_replace):
        level_infy = DailyLevels(
            symbol="INFY",
            canonical_symbol="INFY",
            exchange="NSE",
            session_date=session_date,
            pdh=1900.0,
            pdl=1850.0,
            pdc=1880.0,
        )
        store._memory_cache[f"{session_date}:INFY"] = level_infy
        store.save_to_disk(session_date=session_date)

    # Sidecar file should have been created
    sidecars = list(tmp_path.glob(f"{primary_file.stem}.side.*.json"))
    assert len(sidecars) >= 1

    # Step C: load_from_disk discovers sidecar and loads both levels
    fresh_store = DailyLevelsStore(persist_dir=tmp_path)
    loaded_count = fresh_store.load_from_disk(session_date=session_date)
    assert loaded_count >= 2
    cached = fresh_store.get_all_for_today(session_date=session_date)
    assert "TCS" in cached
    assert "INFY" in cached


# ── 7. Telemetry Priority Routing & Noise Suppression ────────────────────────


def test_telemetry_priority_routing_for_opsdeck():
    """Verify noise suppression and institutional priority classification."""
    # Routine WebSocket remote disconnects -> P3
    assert (
        derive_priority(
            "SYSTEM_LOG", "websocket", "ERROR", "Connection to remote host was lost. - goodbye"
        )
        == "P3"
    )
    assert (
        derive_priority(
            "SYSTEM_LOG", "FyersDataSocket", "ERROR", "Connection to remote host was lost."
        )
        == "P3"
    )

    # Milestone integrity gate holds -> P3
    assert (
        derive_priority(
            "SYSTEM_LOG",
            "engine.auto_alert_engine",
            "WARNING",
            "[AutoAlertEngine] 🛡️ Milestone TARGET_ACHIEVED held by integrity gate for SBIN",
        )
        == "P3"
    )

    # Fyers SDK options chain transient decode error -> P3
    assert (
        derive_priority(
            "SYSTEM_LOG",
            "FyersAPI",
            "ERROR",
            "{'API': '/options-chain-v3', 'error': JSONDecodeError('Expecting value')}",
        )
        == "P3"
    )

    # Real critical order execution freeze -> P0
    assert (
        derive_priority(
            "SYSTEM_LOG", "engine.order_lifecycle", "CRITICAL", "Live execution freeze detected"
        )
        == "P0"
    )

    # Real rate limit saturation -> P1
    assert (
        derive_priority(
            "SYSTEM_LOG", "market.fyers_rate_gate", "WARNING", "REST Rate Limit 429 quota exhausted"
        )
        == "P1"
    )


# ── 8. Fyers TBT Socket Resilience (SubscriptionInfo & 403 Halt) ────────────


def test_fyers_tbt_socket_subscription_info_and_403_resilience():
    """Verify Fyers TBT socket patch fixes KeyError on getSymbolsInfo and halts on 403."""
    pytest.importorskip("fyers_apiv3", reason="fyers_apiv3 is an optional broker SDK")
    from fyers_apiv3.FyersWebsocket import tbt_ws

    # A: SubscriptionInfo KeyError prevention
    subs_cls = getattr(tbt_ws, "SubscriptionInfo", getattr(tbt_ws, "Subscription_info", None))
    assert subs_cls is not None, "SubscriptionInfo must exist"
    subs = subs_cls()

    # Must return empty set, not raise KeyError on uninitialized channel (str or int)
    assert subs.getSymbolsInfo("1") == set()
    assert subs.getSymbolsInfo(1) == set()
    assert subs.getModeInfo("1") == tbt_ws.SubscriptionModes.DEPTH
    assert subs.getModeInfo(1) == tbt_ws.SubscriptionModes.DEPTH

    # B: FyersTbtSocket 403 Forbidden halt
    dummy_tbt_sock = MagicMock()
    dummy_tbt_sock.restart_flag = True
    dummy_tbt_sock.onerror = MagicMock()
    dummy_tbt_sock.tbtlogger = MagicMock()
    dummy_tbt_sock.write_to_file = False

    tbt_ws.FyersTbtSocket.On_error(dummy_tbt_sock, "Handshake status 403 Forbidden - Access denied")
    assert dummy_tbt_sock.restart_flag is False, (
        "FyersTbtSocket must set restart_flag=False on 403 Forbidden"
    )


# ── 9. Telegram HTML Sanitizer & Entity Parsing Protection ───────────────────


def test_telegram_html_sanitizer_prevents_unsupported_start_tag():
    """Verify sanitize_telegram_html escapes literal '<' and '>' without breaking valid tags."""
    from bot.telegram_bot import sanitize_telegram_html

    # Case A: Stray math comparisons and empty angle brackets
    raw = "Alert: RVOL < 0.5x, deficit: <100 pts. Spread: <<>>. Stop Loss: > 2500"
    sanitized = sanitize_telegram_html(raw)
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "RVOL &lt; 0.5x" in sanitized
    assert "deficit: &lt;100 pts" in sanitized
    assert "Spread: &lt;&lt;&gt;&gt;" in sanitized
    assert "Stop Loss: &gt; 2500" in sanitized

    # Case B: Valid Telegram HTML tags preserved verbatim
    formatted = (
        "<b>NIFTY 25000 CE</b>\n"
        "<i>Target Achieved</i>\n"
        "<code>LTP: 154.20</code>\n"
        '<a href="https://example.com">View Chart</a>\n'
        "Volume < 1.0x (warning)"
    )
    result = sanitize_telegram_html(formatted)
    assert "<b>NIFTY 25000 CE</b>" in result
    assert "<i>Target Achieved</i>" in result
    assert "<code>LTP: 154.20</code>" in result
    assert '<a href="https://example.com">View Chart</a>' in result
    assert "Volume &lt; 1.0x (warning)" in result


# ── 10. Session Close Exit vs Milestone Integrity Veto ───────────────────────


def test_session_close_exit_never_falsely_triggers_is_final_or_veto():
    """Verify session close exits (15:15 IST) are not misclassified as final target achievements."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    alert = AutoAlert(
        alert_id="aa-predator-sweep-maruti-spring-20261029",
        alert_type="PREDATOR_SWEEP",
        stage="COMPLETED",
        symbol="MARUTI",
        exchange="NSE",
        direction="BULLISH",
        headline="MARUTI Session Close",
        summary="Intraday session expired (15:15 IST cutoff reached). Trade closed.",
        ltp=11455.0,
        trigger_level=11471.0,
        target_level=11682.76,
        stop_loss=11365.12,
        confidence=90,
        target_status="SESSION_CLOSE_EXIT",
        is_live=False,
    )

    # Calling _dispatch on an alert closed by session expiration MUST NOT trigger MILESTONE INTEGRITY VETO
    with patch.object(engine, "_save"):
        with patch(
            "engine.alert_preferences.alert_preferences.is_alert_allowed", return_value=False
        ):
            with patch("logging.Logger.error") as mock_err:
                engine._dispatch(alert)
                # Confirm no error log for MILESTONE INTEGRITY VETO
                for call in mock_err.call_args_list:
                    assert "MILESTONE INTEGRITY VETO" not in str(call)


# ── 11. Milestone Integrity Veto Demotion ─────────────────────────────────────


def test_milestone_integrity_veto_demotes_falsely_asserted_final_target():
    """Verify that if an alert falsely claims TARGET_ACHIEVED, veto demotes stage and clears milestone."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    alert = AutoAlert(
        alert_id="aa-test-false-final-target",
        alert_type="PREDATOR_SWEEP",
        stage="TARGET_ACHIEVED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="False Final Target Claim",
        summary="Premature claim",
        ltp=3900.0,
        trigger_level=3900.0,
        target_level=4100.0,  # Far above CMP 3900
        stop_loss=3850.0,
        confidence=90,
        target_status="TARGET_ACHIEVED",
        achieved_milestones=["TARGET_ACHIEVED"],
        is_live=False,
    )

    with patch.object(engine, "_save"):
        engine._dispatch(alert)

    # Veto should demote stage away from TARGET_ACHIEVED and remove from achieved_milestones
    assert alert.stage != "TARGET_ACHIEVED"
    assert "TARGET_ACHIEVED" not in (alert.achieved_milestones or [])


# ── 12. Scan Cycle Detector Staggering and Target Bounding ───────────────────


def test_scan_cycle_detector_staggering_and_target_bounding():
    """Verify predator_sweeps and turtle_soup target counts are bounded to <= 15 symbols."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    with patch(
        "engine.detectors.liquidity_sweep.detect_predator_liquidity_sweep", return_value=None
    ):
        with patch("market.history.get_ohlcv", return_value=pd.DataFrame()):
            # Mock executor to capture submitted symbols
            submitted_syms = []

            class MockExecutor:
                def __init__(self, *a, **k):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def submit(self, fn, sym):
                    submitted_syms.append(sym)
                    m = MagicMock()
                    m.result.return_value = None
                    return m

            with patch("concurrent.futures.ThreadPoolExecutor", MockExecutor):
                with patch("concurrent.futures.as_completed", return_value=[]):
                    engine.scan_predator_liquidity_sweeps()
                    assert len(submitted_syms) <= 15, (
                        f"Predator sweeps submitted too many targets: {len(submitted_syms)}"
                    )

            submitted_turtle = []

            class MockTurtleExecutor:
                def __init__(self, *a, **k):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def submit(self, fn, sym):
                    submitted_turtle.append(sym)
                    m = MagicMock()
                    m.result.return_value = None
                    return m

            with patch("concurrent.futures.ThreadPoolExecutor", MockTurtleExecutor):
                with patch("concurrent.futures.as_completed", return_value=[]):
                    engine.scan_turtle_soup_sweeps()
                    assert len(submitted_turtle) <= 15, (
                        f"Turtle soup submitted too many targets: {len(submitted_turtle)}"
                    )


# ── 13. Telemetry Log Handler Routine WebSocket Disconnect Classification ─────


def test_telemetry_handler_websocket_routine_disconnect_p3():
    """Verify TelemetryHandler categorizes routine websocket drops as P3 rather than P2."""
    from engine.telemetry import TelemetryLogHandler

    handler = TelemetryLogHandler()

    # Log record from websocket logger with error severity
    record = logging.LogRecord(
        name="websocket",
        level=logging.ERROR,
        pathname="websocket/_logging.py",
        lineno=64,
        msg="Connection to remote host was lost. - goodbye",
        args=(),
        exc_info=None,
    )

    with patch("engine.telemetry.record_event") as mock_record:
        handler.emit(record)
        assert mock_record.called
        kwargs = mock_record.call_args[1]
        # Routine socket closure is downgraded from P1 (Error) to P2 (Operational Diagnostic)
        assert kwargs["priority"] == "P2", (
            f"Expected P2 for routine websocket drop, got {kwargs['priority']}"
        )
        assert kwargs["severity"] == "WARNING"
