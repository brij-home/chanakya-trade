"""Regression tests for Telegram alert dedup, UPDATE # tagging, badge editing, and readability."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from bot import telegram_bot as tg_bot
from bot.alert_templates import render_auto_alert
from engine.alert_model import AutoAlert
from engine.outbox_worker import OutboxWorker
from engine.sqlite_store import SQLiteAlertStore


@pytest.mark.live_telegram
def test_send_push_deduplicates_root_signal_even_with_metric_drift(monkeypatch):
    """Same #SIG_* root NEW CALL to same chat_id must be suppressed within 30 min even if body differs."""
    with tg_bot._push_dedup_lock:
        tg_bot._recent_push_digests.clear()

    sent_payloads = []
    monkeypatch.setenv("CHANAKYA_TESTING", "0")
    monkeypatch.setattr(tg_bot, "_ALLOW_TEST_DISPATCH", True)
    monkeypatch.setattr(tg_bot, "_get_bot_token", lambda: "12345:test-token")
    monkeypatch.setattr(tg_bot, "_load_chat_id", lambda: "-100999")
    monkeypatch.setattr(tg_bot, "record_signal_message_id", lambda *a, **kw: None)

    def _fake_post(url, json=None, timeout=10.0):
        sent_payloads.append(json)
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 200
        resp.json.return_value = {"ok": True, "result": {"message_id": 9001}}
        return resp

    monkeypatch.setattr("httpx.post", _fake_post)

    sig = "SIG_BAJAJAUTO_10800PE_25NOV_1309"
    msg_a = (
        "🔴 <b>[LIVE] NEW CALL · OPTIONS PUT SURGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>BAJAJ-AUTO 10800 PE</b> | Opt CMP: <b>₹142.50</b>\n"
        f"🟢 <i>LIVE BROKER FEED</i> · 🏷️ <code>#{sig}</code>"
    )
    msg_b = (
        "🔴 <b>[LIVE] NEW CALL · OPTIONS PUT SURGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>BAJAJ-AUTO 10800 PE</b> | Opt CMP: <b>₹146.10</b>\n"
        f"🟢 <i>LIVE BROKER FEED</i> · 🏷️ <code>#{sig}</code>"
    )

    tg_bot.send_push(msg_a, chat_id="-100999", signal_id=sig, wait=True)
    # Slightly mutated body (different Opt CMP) arrives 2s later from OutboxWorker/retry -> MUST BE BLOCKED
    tg_bot.send_push(msg_b, chat_id="-100999", signal_id=sig, wait=True)

    assert len(sent_payloads) == 1

    # Different signal tag to same chat MUST still send
    sig2 = "SIG_BAJAJAUTO_10700PE_25NOV_1315"
    msg_c = msg_a.replace(sig, sig2)
    tg_bot.send_push(msg_c, chat_id="-100999", signal_id=sig2, wait=True)
    assert len(sent_payloads) == 2


@pytest.mark.live_telegram
def test_playbook_target_1_does_not_promote_root_call_badge(monkeypatch):
    """
    A SPREAD_FREE_ROLL / T0.5 update whose Playbook mentions 'Book 50% at Target 1'
    MUST NOT call update_root_signal_status with '[🏆 T1 HIT · SL TO COST]'.
    """
    with tg_bot._push_dedup_lock:
        tg_bot._recent_push_digests.clear()

    badge_calls = []
    monkeypatch.setattr(tg_bot, "_get_bot_token", lambda: "12345:test-token")
    monkeypatch.setattr(tg_bot, "_load_chat_id", lambda: "-100999")
    monkeypatch.setattr(tg_bot, "record_signal_message_id", lambda *a, **kw: None)
    monkeypatch.setattr(
        tg_bot,
        "update_root_signal_status",
        lambda **kw: badge_calls.append(kw.get("status_badge")) or True,
    )

    # Exercise live HTTP dispatch path with mocked _tg_post_with_retry
    monkeypatch.setattr(tg_bot, "_ALLOW_TEST_DISPATCH", True)

    def _fake_post(url, json=None, timeout=10.0):
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 200
        resp.json.return_value = {"ok": True, "result": {"message_id": 9102}}
        return resp

    monkeypatch.setattr("httpx.post", _fake_post)

    spread_upd = (
        "🛡️ <b>[LIVE] UPDATE #1 · SPREAD FREE-ROLL UNLOCKED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>MIDCPNIFTY 14275 PE</b>\n"
        "• Playbook: <i>Book 50% at Target 1 (₹405.8) and trail SL to Cost.</i>\n"
        "🏷️ <code>#SIG_MIDCPNIFTY_14275PE_25NOV_1206</code>"
    )
    tg_bot.send_push(
        spread_upd,
        chat_id="-100999",
        signal_id="SIG_MIDCPNIFTY_14275PE_25NOV_1206",
        is_update=True,
        wait=True,
    )
    assert badge_calls == ["[🛡️ SPREAD FREE-ROLL]"]

    # Genuine T1 hit in header MUST still stamp [🏆 T1 HIT · SL TO COST]
    badge_calls.clear()
    t1_upd = (
        "🎯 <b>[LIVE] UPDATE #2 · TARGET 1 HIT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>MIDCPNIFTY 14275 PE</b> @ ₹406.0\n"
        "🏷️ <code>#SIG_MIDCPNIFTY_14275PE_25NOV_1206</code>"
    )
    tg_bot.send_push(
        t1_upd,
        chat_id="-100999",
        signal_id="SIG_MIDCPNIFTY_14275PE_25NOV_1206",
        is_update=True,
        wait=True,
    )
    assert badge_calls == ["[🏆 T1 HIT · SL TO COST]"]


def test_outbox_worker_skips_initial_when_already_dispatched_and_acknowledges(tmp_path):
    """
    OutboxWorker must skip sending a v1 initial TELEGRAM entry if the persisted alert
    already has telegram_dispatched=True, and store.acknowledge_outbox_by_alert_channel works.
    """
    db_file = tmp_path / "outbox_dedup.db"
    store = SQLiteAlertStore(db_path=str(db_file))

    alert_dict = {
        "alert_id": "aa-bajaj-test-1",
        "symbol": "BAJAJ-AUTO",
        "stage": "IGNITED",
        "alert_type": "OPTIONS_MOMENTUM",
        "environment": "LIVE",
        "is_live": True,
        "ltp": 142.5,
        "telegram_dispatched": True,
        "signal_ref": "SIG_BAJAJAUTO_10800PE_25NOV_1309",
    }
    store.save_alert_with_outbox(
        alert_dict,
        [{"channel": "TELEGRAM", "event_version": 1, "payload": alert_dict}],
    )

    with patch("bot.telegram_bot.get_telegram_bot") as mock_get_bot:
        mock_bot = MagicMock()
        mock_get_bot.return_value = mock_bot
        worker = OutboxWorker(store=store, worker_id="test-worker")
        worker.process_outbox_batch(limit=10)
        assert not mock_bot.send_push.called

    # Second alert: test explicit synchronous ack helper
    alert2 = dict(alert_dict, alert_id="aa-bajaj-test-2", telegram_dispatched=False)
    store.save_alert_with_outbox(
        alert2,
        [{"channel": "TELEGRAM", "event_version": 1, "payload": alert2}],
    )
    assert len(store.get_pending_outbox_entries(channel="TELEGRAM")) == 1
    updated = store.acknowledge_outbox_by_alert_channel("aa-bajaj-test-2", "TELEGRAM")
    assert updated == 1
    assert len(store.get_pending_outbox_entries(channel="TELEGRAM")) == 0


def test_render_auto_alert_readability_summary_gex_signals_and_completed():
    """
    Verify:
    1. Decimal prices in 'SL: ₹265.4 (-6%) | T1: ₹405.8 (+12%).' do NOT leave '2 (-6%) · 2 (+12%)'.
    2. Counter-directional Bullish OBV/DMI tags are suppressed on a Bearish PE alert.
    3. Equal GEX Call Wall == Put Wall collapses to 'GEX Structure: Pin ₹14,500'.
    4. No duplicate '| Opt CMP:' in headline when '(Opt CMP:' is already in Action line.
    5. COMPLETED stage renders UPDATE # prefix instead of 'NEW CALL'.
    """
    alert = AutoAlert(
        alert_id="aa-midcp-readability-1",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="MIDCPNIFTY 14275 PE (Lot: 120)",
        summary=(
            "Spot sliced cleanly below session VWAP (₹14,299.2). "
            "Entry: ₹312.2 | SL: ₹265.4 (-6%) | T1: ₹405.8 (+12%)."
        ),
        ltp=311.10,
        trigger_level=312.20,
        target_level=405.80,
        stop_loss=265.40,
        confidence=94,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        environment="LIVE",
        is_live=True,
    )
    alert.contract_symbol = "MIDCPNIFTY 14275 PE"
    alert.option_type = "PE"
    alert.strike = 14275.0
    alert.option_premium = 311.10
    alert.underlying_spot = 14272.85
    alert.lot_size = 120
    alert.actionable_plan = {
        "action": "BUY PE",
        "contract": "MIDCPNIFTY 14275 PE",
        "recommended_entry": "₹299.7 – ₹316.9",
        "stop_loss": "₹265.4",
        "target_1": "₹405.8",
        "target_2": "₹476.0",
        "regime_verdict": "DYNAMIC_SPREAD_RECOMMENDED",
        "iv_skew": {"status": "ACTIVE", "regime": "BALANCED_SYMMETRIC", "atm_skew": 0.0},
    }
    alert.metrics = {
        "obv_divergence": "BULLISH_DIVERGENCE",
        "dmi_triple_verdict": "BULLISH_ESTABLISHED",
        "avwap_bias": "BEARISH",
        "gex_call_wall": 14500.0,
        "gex_put_wall": 14500.0,
        "zero_gamma_level": 14500.0,
        "gamma_regime": "POSITIVE_GAMMA_PIN",
    }

    rendered = render_auto_alert(alert, in_market=True)
    assert "2 (-6%)" not in rendered
    assert "2 (+12%)" not in rendered
    assert "OBV: Bullish Divergence" not in rendered
    assert "Triple-DMI: Bullish Established" not in rendered
    assert "AVWAP: Bearish" in rendered
    assert "GEX Structure:</b> Pin ₹14,500" in rendered
    assert "Call Wall ₹14,500 | Put Wall ₹14,500" not in rendered
    assert rendered.count("Opt CMP:") == 1

    # Stage COMPLETED should NEVER render 'NEW CALL' without UPDATE #
    alert.stage = "COMPLETED"
    alert.update_number = 2
    rendered_done = render_auto_alert(alert, in_market=True)
    assert "UPDATE #2" in rendered_done
    assert "NEW CALL" not in rendered_done
