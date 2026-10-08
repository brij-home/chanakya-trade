"""
tests/test_telegram_threading_and_tone.py
──────────────────────────────────────────
Unit test suite verifying:
1. Telegram thread partitioning via reply_to_message_id linking updates to original calls.
2. Topic / Forum Supergroup partitioning via chat_id:topic_id syntax and message_thread_id.
3. Audio / Tone Differentiator (disable_notification=True for silent ratchets, False for actionable calls).
"""

import pytest
from bot.telegram_bot import (
    format_telegram_push_payload,
    get_signal_message_id,
    record_signal_message_id,
    clear_signal_message_ids,
)


@pytest.fixture(autouse=True)
def clean_threads(tmp_path, monkeypatch):
    """Ensure in-memory and disk threads run against an isolated temp file and are cleared before and after each test."""
    test_threads_file = tmp_path / "test_telegram_threads.json"
    monkeypatch.setattr("bot.telegram_bot._THREADS_FILE", test_threads_file)
    clear_signal_message_ids()
    yield
    clear_signal_message_ids()


def test_signal_message_id_registry():
    """Verify storing, retrieving, and normalizing signal-to-message mapping."""
    assert get_signal_message_id("SIG_RELIANCE_24SEP_1400") is None

    # Storing with leading '#' should be stripped and retrievable either way
    record_signal_message_id("#SIG_RELIANCE_24SEP_1400", 789101)
    assert get_signal_message_id("SIG_RELIANCE_24SEP_1400") == 789101
    assert get_signal_message_id("#SIG_RELIANCE_24SEP_1400") == 789101


def test_thread_partitioning_links_updates_to_initial_call():
    """
    Verify that an initial 'NEW CALL' sends as a top-level message,
    and subsequent 'UPDATE #1' messages automatically include reply_to_message_id.
    """
    initial_msg = (
        "🟢 [REAL/LIVE] NEW CALL · OPTIONS BREAKOUT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 <b>BSE 3200 CE</b> @ <code>₹72.50</code>\n"
        "• <b>Action:</b> BUY BSE 3200 CE\n"
        "🏷️ <code>#SIG_BSE_3200CE_24SEP_1415</code>"
    )

    # 1. Initial call: no prior message ID recorded -> top level
    p_initial = format_telegram_push_payload(
        initial_msg, chat_id="-1001234567890", signal_id="SIG_BSE_3200CE_24SEP_1415"
    )
    assert "reply_to_message_id" not in p_initial
    assert p_initial["chat_id"] == "-1001234567890"

    # Simulate Telegram responding with message_id=45001 for the initial call
    record_signal_message_id("SIG_BSE_3200CE_24SEP_1415", 45001)

    # 2. Update #1: Target 1 Hit -> automatically links to message_id=45001
    update_msg_1 = (
        "🎯 [REAL/LIVE] UPDATE #1 · TARGET 1 HIT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 BSE 3200 CE — TARGET 1 ACHIEVED\n"
        "🏷️ <code>#SIG_BSE_3200CE_24SEP_1415</code>"
    )
    p_up1 = format_telegram_push_payload(
        update_msg_1, chat_id="-1001234567890", signal_id="SIG_BSE_3200CE_24SEP_1415"
    )
    assert p_up1["reply_to_message_id"] == 45001
    assert p_up1["allow_sending_without_reply"] is True

    # 3. Update #2: Target 2 Hit (auto-extract signal_id from text)
    update_msg_2 = (
        "🎯 [REAL/LIVE] UPDATE #2 · TARGET 2 HIT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 BSE 3200 CE — TARGET 2 ACHIEVED\n"
        "🏷️ <code>#SIG_BSE_3200CE_24SEP_1415</code>"
    )
    p_up2 = format_telegram_push_payload(update_msg_2, chat_id="-1001234567890")
    assert p_up2["reply_to_message_id"] == 45001
    assert p_up2["allow_sending_without_reply"] is True


def test_topic_partitioning_chat_id_colon_syntax():
    """Verify that chat_id='-1001234567890:88' separates into chat_id and message_thread_id."""
    msg = "🟢 [REAL/LIVE] NEW CALL · NIFTY BREAKOUT"
    payload = format_telegram_push_payload(msg, chat_id="-1001234567890:88")

    assert payload["chat_id"] == "-1001234567890"
    assert payload["message_thread_id"] == 88


def test_topic_partitioning_environment_variable(monkeypatch):
    """Verify that TELEGRAM_TOPIC_ID env var sets message_thread_id when not in chat_id."""
    monkeypatch.setenv("TELEGRAM_TOPIC_ID", "42")
    msg = "🟢 [REAL/LIVE] NEW CALL · BANKNIFTY BREAKOUT"
    payload = format_telegram_push_payload(msg, chat_id="-1001234567890")

    assert payload["chat_id"] == "-1001234567890"
    assert payload["message_thread_id"] == 42


def test_audio_tone_differentiator_audible_vs_silent():
    """
    Verify:
    - NEW CALL, TARGET 1/2/FINAL, STOP LOSS, INVALIDATED are AUDIBLE (disable_notification=False).
    - TRAILING STOP RATCHET, PRECURSOR RADAR, MORNING BRIEF, EOD REPORT are SILENT (disable_notification=True).
    """
    # 1. NEW CALL -> Audible
    p_call = format_telegram_push_payload("🟢 [REAL/LIVE] NEW CALL · OPTIONS BREAKOUT")
    assert "disable_notification" not in p_call or p_call.get("disable_notification") is False

    # 2. TARGET 1 HIT -> Audible
    p_t1 = format_telegram_push_payload("🎯 [REAL/LIVE] UPDATE #1 · TARGET 1 HIT")
    assert "disable_notification" not in p_t1 or p_t1.get("disable_notification") is False

    # 3. STOP LOSS / INVALIDATED -> Audible
    p_sl = format_telegram_push_payload("⚠️ [REAL/LIVE] UPDATE #1 · VIEW INVALIDATED")
    assert "disable_notification" not in p_sl or p_sl.get("disable_notification") is False

    # 4. TRAIL RATCHET -> Silent!
    p_trail = format_telegram_push_payload("📈 [REAL/LIVE] UPDATE #2 · TRAILING STOP RATCHET")
    assert p_trail["disable_notification"] is True

    # 5. PRECURSOR RADAR -> Silent
    p_precursor = format_telegram_push_payload("📡 [REAL/LIVE] NEW CALL · PRECURSOR RADAR [FNO]")
    assert p_precursor["disable_notification"] is True

    # 6. Explicit override takes precedence
    p_explicit_silent = format_telegram_push_payload(
        "🟢 [REAL/LIVE] NEW CALL · TEST", disable_notification=True
    )
    assert p_explicit_silent["disable_notification"] is True

    p_explicit_loud = format_telegram_push_payload(
        "📈 [REAL/LIVE] UPDATE #2 · TRAILING STOP RATCHET", disable_notification=False
    )
    assert (
        "disable_notification" not in p_explicit_loud
        or p_explicit_loud.get("disable_notification") is False
    )


def test_multichannel_chat_scoped_and_alias_threading():
    """
    Verify that:
    1. Chat-scoped message mapping distinguishes same or different signals across channels.
    2. Internal alert_id (e.g. spark-naukri-...) links to updates using #SIG_NAUKRI_... hashtag alias.
    """
    eq_chat = "-1003524867091"
    fno_chat = "-1004393392375"

    # Initial alert in Equity channel with internal ID and text containing hashtag
    internal_id = "spark-naukri-202609240930"
    tag_alias = "SIG_NAUKRI_24SEP_0930"
    record_signal_message_id(internal_id, 403, chat_id=eq_chat)
    record_signal_message_id(tag_alias, 403, chat_id=eq_chat)

    # Initial alert in FNO Stock channel
    fno_internal = "aa-gb-pe-HAL-4800-9716c9"
    fno_tag = "SIG_HAL_4800PE_24SEP_1102"
    record_signal_message_id(fno_internal, 1185, chat_id=fno_chat)
    record_signal_message_id(fno_tag, 1185, chat_id=fno_chat)

    # Update in Equity channel referencing hashtag in message text
    eq_update = (
        "🎯 [REAL/LIVE] UPDATE #1 · TARGET 1 HIT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 NAUKRI — TARGET 1 ACHIEVED\n"
        "🏷️ <code>#SIG_NAUKRI_24SEP_0930</code>"
    )
    p_eq = format_telegram_push_payload(eq_update, chat_id=eq_chat)
    assert p_eq["reply_to_message_id"] == 403

    # Update in FNO channel referencing internal alert_id as signal_id
    fno_update = (
        "🛑 [REAL/LIVE] UPDATE · STOP LOSS HIT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "HAL 4800 PE — Stop Loss Hit\n"
        "🏷️ <code>#SIG_HAL_4800PE_24SEP_1102</code>"
    )
    p_fno = format_telegram_push_payload(fno_update, chat_id=fno_chat, signal_id=fno_internal)
    assert p_fno["reply_to_message_id"] == 1185


def test_spread_freeroll_threading_and_timestamp_fallback():
    """
    Verify:
    1. Initial BANKNIFTY 54300 PE signal recorded with message ID 88001.
    2. UPDATE #2 with SPREAD FREE-ROLL UNLOCKED links to message 88001 even if
       the minute timestamp shifted (e.g. _1243 vs _1244) or lookup uses alert_id.
    """
    chat_fno = "-1004380788314"
    orig_sig = "SIG_BANKNIFTY_54300PE_29SEP_1243"
    alert_id = "aa-options_momentum-banknifty_54300pe-20260929"

    # Record root message
    record_signal_message_id(orig_sig, 88001, chat_id=chat_fno, alert_id=alert_id)

    # 1. Exact lookup
    assert get_signal_message_id(orig_sig, chat_id=chat_fno) == 88001

    # 2. Lookup via alert_id
    assert get_signal_message_id("", chat_id=chat_fno, alert_id=alert_id) == 88001

    # 3. Lookup when timestamp shifted by 1 minute (_1244 instead of _1243)
    shifted_sig = "SIG_BANKNIFTY_54300PE_29SEP_1244"
    assert get_signal_message_id(shifted_sig, chat_id=chat_fno) == 88001

    # 4. Message format with UPDATE and FREE-ROLL automatically finds root message
    update_msg = (
        "[REAL/LIVE] UPDATE #2 · SPREAD FREE-ROLL UNLOCKED\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 🔴 BANKNIFTY 54300 PE — 100% RISK-FREE SPREAD\n"
        "• Underlying: BANKNIFTY | Strike: 54300 PE\n"
        "💰 Spread Net Value: ₹196.30 · 📈 Spread P&L: +₹62.89 (+64.4%)\n"
        "⚡️ DECISIVE ACTION: SCALE 50% LONG LEG & MOVE SL TO BREAKEVEN (FREE-ROLL)\n"
        "🏷️ Ref: #SIG_BANKNIFTY_54300PE_29SEP_1244"
    )
    payload = format_telegram_push_payload(update_msg, chat_id=chat_fno, alert_id=alert_id)
    assert payload["reply_to_message_id"] == 88001
    assert payload["reply_parameters"]["message_id"] == 88001


def test_spread_freeroll_humanized_decisive_action_and_net_debit():
    """
    Verify:
    1. Raw enum SCALE_50_PCT_LOCK_BREAKEVEN is humanized to crystal-clear trader directive.
    2. Spread net debit is clearly distinguished from single leg entry in Original Plan line.
    3. Zero raw enum strings leak to user-facing template.
    """
    from bot.alert_templates import humanize_decisive_action
    from engine.alert_model import AutoAlert

    # Verify action humanizer
    assert (
        humanize_decisive_action("SCALE_50_PCT_LOCK_BREAKEVEN")
        == "SCALE 50% LONG LEG & MOVE SL TO BREAKEVEN (FREE-ROLL)"
    )
    assert (
        humanize_decisive_action("BOOK_SPREAD_70_PCT")
        == "CLOSE BOTH LEGS AT MARKET (LOCK 70% PROFIT)"
    )
    assert (
        humanize_decisive_action("SCRATCH_SPREAD_AT_MARKET")
        == "EXIT BOTH LEGS AT MARKET (CAPITAL DEFENSE)"
    )

    alert = AutoAlert(
        alert_id="aa-options_momentum-banknifty_54300pe-20260929",
        alert_type="OPTIONS_MOMENTUM",
        stage="SPREAD_FREE_ROLL",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="BANKNIFTY 54300 PE SPREAD FREE-ROLL UNLOCKED",
        summary="Net spread value expanded by +64.4%. 100% capital risk-free.",
        ltp=196.30,
        trigger_level=192.40,
        target_level=350.0,
        stop_loss=153.90,
        contract_symbol="BANKNIFTY 54300 PE",
        target_status="SPREAD_FREE_ROLL",
        option_premium=192.40,
        lot_size=30,
        pnl_pct=64.4,
        trailing_decision="SCALE_50_PCT_LOCK_BREAKEVEN",
        trailing_rationale="Net spread value expanded to ₹160.5 (Entry: ₹97.7, +64.4%). Trade is 100% capital risk-free.",
        actionable_plan={
            "hedge_plan": {
                "net_debit_per_share": 97.70,
                "buy_strike": 54300,
                "sell_strike": 54000,
            }
        },
        update_number=2,
        signal_ref="#SIG_BANKNIFTY_54300PE_29SEP_1243",
    )
    alert.pnl_pts = 62.89

    from bot.alert_templates import render_auto_alert

    rendered = render_auto_alert(alert, in_market=True)

    # Assert decisive action is humanized (no raw enum)
    assert "SCALE_50_PCT_LOCK_BREAKEVEN" not in rendered
    assert "SCALE 50% LONG LEG & MOVE SL TO BREAKEVEN (FREE-ROLL)" in rendered

    # Assert spread debit is clearly displayed alongside long leg entry
    assert "Spread Debit: ₹97.70 (Long Leg: ₹192.40)" in rendered
    assert "UPDATE #2 · SPREAD FREE-ROLL UNLOCKED" in rendered


def test_auto_alert_upgrade_preserves_telegram_root(tmp_path, monkeypatch):
    """
    Verify that when an EARLY_WARNING alert is upgraded to IGNITED,
    any prior telegram_root_message_id is preserved so updates thread properly.
    """
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    early = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-1700-coiling",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK Early Warning Setup",
        summary="High conviction early warning options momentum",
        ltp=24.70,
        trigger_level=24.70,
        target_level=35.0,
        stop_loss=18.0,
        strike=1700.0,
        option_type="CE",
        contract_symbol="HDFCBANK1700CE",
        confidence=85,
        created_at=now_str,
        telegram_root_message_id=99001,
        telegram_message_id=99001,
        signal_ref="#SIG_HDFCBANK_1700CE_11SEP_1000",
        environment="TEST",
        is_live=False,
    )
    engine.record_alert(early)

    ignited = AutoAlert(
        alert_id="aa-optmom-ce-HDFCBANK-1700-ignite",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="HDFCBANK Ignited Breakout",
        summary="Breakout ignited on heavy volume",
        ltp=22.10,
        trigger_level=22.10,
        target_level=33.2,
        stop_loss=16.6,
        strike=1700.0,
        option_type="CE",
        contract_symbol="HDFCBANK1700CE",
        confidence=90,
        created_at=now_str,
        environment="TEST",
        is_live=False,
    )

    recorded = engine.record_alert(ignited)
    assert recorded is True

    upgraded = next(a for a in engine.get_alerts() if a.symbol == "HDFCBANK")
    assert upgraded.stage == "IGNITED"
    assert upgraded.telegram_root_message_id == 99001


def test_cross_day_signals_do_not_hijack_threads():
    """
    Verify that an alert from yesterday (e.g. 30SEP) does not thread
    into a fresh alert for the same symbol on today (e.g. 01OCT).
    """
    chat_id = "-1004393392375"
    yesterday_sig = "SIG_ICICIPRULI_30SEP_1459"
    yesterday_alert_id = "aa-squeeze-breakdown-icicipruli-bear-20260930"

    # Yesterday's alert sent with msg_id 955
    record_signal_message_id(yesterday_sig, 955, chat_id=chat_id, alert_id=yesterday_alert_id)
    assert get_signal_message_id(yesterday_sig, chat_id=chat_id) == 955

    # Today's alert for the same symbol must NOT match yesterday's message
    today_sig = "SIG_ICICIPRULI_01OCT_0938"
    today_alert_id = "aa-squeeze-breakdown-icicipruli-bear-20261001"
    assert get_signal_message_id(today_sig, chat_id=chat_id, alert_id=today_alert_id) is None


def test_new_calls_across_all_categories_never_thread_as_updates():
    """
    Verify that across ALL categories (Crypto, F&O Options, MCX, Currency, Radar),
    a new call message containing full execution playbook words ('Scale', 'trail', 'stop', 'target')
    never attaches reply_to_message_id, even when an earlier morning signal exists for the symbol today.
    """
    chat_crypto = "-1004323607372"
    chat_fno = "-1004393392375"
    chat_mcx = "-1004351234567"
    chat_cds = "-1004367890123"

    # Simulate earlier morning alerts on same symbols today
    record_signal_message_id("SIG_BTCUSDT_02OCT_0712", 216, chat_id=chat_crypto)
    record_signal_message_id("SIG_RELIANCE_2600CE_02OCT_0915", 301, chat_id=chat_fno)
    record_signal_message_id("SIG_CRUDEOIL_02OCT_0900", 401, chat_id=chat_mcx)
    record_signal_message_id("SIG_USDINR_02OCT_0900", 501, chat_id=chat_cds)

    # 1. Crypto 24x7 New Call with full playbook
    crypto_msg = (
        "🪙 <b>[CRYPTO 24x7] NEW CALL · ALPHA VORTEX</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 CRYPTO SMC ALPHA: BTCUSDT Demand Order Block Reclaim @ $85,600.00\n"
        "• Action: BUY SPOT / LONG BTCUSDT @ $83,400.00 – $85,771.20\n"
        "• SL: $82,983.00\n"
        "• T1: $91,619.10 | T2: $100,045.84 | Runner: $101,249.66\n"
        "• Playbook: Scale 50% at T1 (+2.3R) & trail stop to breakeven. Scale 25% at T2 (+5.5R). Trail runner to T3.\n"
        "💡 Reason: Structural reclaim at 15m Demand OB. Upside target: $91,619.10\n"
        "🏷️ #SIG_BTCUSDT_02OCT_0931"
    )
    p_crypto = format_telegram_push_payload(
        crypto_msg, chat_id=chat_crypto, signal_id="SIG_BTCUSDT_02OCT_0931", is_update=False
    )
    assert "reply_to_message_id" not in p_crypto

    # Also verify fallback heuristic without explicit is_update (detects NEW CALL header)
    p_crypto_auto = format_telegram_push_payload(
        crypto_msg, chat_id=chat_crypto, signal_id="SIG_BTCUSDT_02OCT_0931"
    )
    assert "reply_to_message_id" not in p_crypto_auto

    # 2. Equity F&O Options New Call
    fno_msg = (
        "🟢 <b>[REAL/LIVE] NEW CALL · OPTIONS BREAKOUT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 <b>RELIANCE 2600 CE</b> @ ₹42.50\n"
        "• SL: ₹32.00\n"
        "• T1: ₹58.00 | T2: ₹75.00\n"
        "• Playbook: Scale 50% at T1 & trail stop to breakeven.\n"
        "🏷️ #SIG_RELIANCE_2600CE_02OCT_1130"
    )
    p_fno = format_telegram_push_payload(
        fno_msg, chat_id=chat_fno, signal_id="SIG_RELIANCE_2600CE_02OCT_1130", is_update=False
    )
    assert "reply_to_message_id" not in p_fno

    # 3. MCX Commodity New Call
    mcx_msg = (
        "🛢️ <b>[REAL/LIVE] NEW CALL · MCX MOMENTUM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 CRUDEOIL @ ₹6,150.00\n"
        "• SL: ₹6,080.00 | T1: ₹6,280.00\n"
        "• Playbook: Scale 50% at T1 & trail stop to breakeven.\n"
        "🏷️ #SIG_CRUDEOIL_02OCT_1400"
    )
    p_mcx = format_telegram_push_payload(
        mcx_msg, chat_id=chat_mcx, signal_id="SIG_CRUDEOIL_02OCT_1400", is_update=False
    )
    assert "reply_to_message_id" not in p_mcx

    # 4. Currency CDS New Call
    cds_msg = (
        "𒒱 <b>[REAL/LIVE] NEW CALL · CURRENCY BREAKOUT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 USDINR @ ₹83.95\n"
        "• SL: ₹83.80 | T1: ₹84.20\n"
        "• Playbook: Scale 50% at T1 & trail stop to breakeven.\n"
        "🏷️ #SIG_USDINR_02OCT_1015"
    )
    p_cds = format_telegram_push_payload(
        cds_msg, chat_id=chat_cds, signal_id="SIG_USDINR_02OCT_1015", is_update=False
    )
    assert "reply_to_message_id" not in p_cds


def test_same_day_distinct_calls_maintain_independent_threads():
    """
    Verify that two distinct calls for the same symbol on the same day:
    1. Both send as independent top-level root messages (no reply_to_message_id).
    2. Milestone updates for Call #1 link strictly to Call #1's message ID.
    3. Milestone updates for Call #2 link strictly to Call #2's message ID.
    """
    chat_id = "-1004323607372"

    # Call #1 at 07:12 IST
    sig_1 = "SIG_BTCUSDT_02OCT_0712"
    msg_1 = f"🪙 <b>[CRYPTO 24x7] NEW CALL · ALPHA VORTEX</b>\n🟢 BTCUSDT @ $85,000.00\n🏷️ #{sig_1}"
    p_1 = format_telegram_push_payload(msg_1, chat_id=chat_id, signal_id=sig_1, is_update=False)
    assert "reply_to_message_id" not in p_1

    # Simulate Call #1 sent with message ID 216
    record_signal_message_id(sig_1, 216, chat_id=chat_id)

    # Call #2 at 09:31 IST
    sig_2 = "SIG_BTCUSDT_02OCT_0931"
    msg_2 = f"🪙 <b>[CRYPTO 24x7] NEW CALL · ALPHA VORTEX</b>\n🟢 BTCUSDT @ $85,600.00\n🏷️ #{sig_2}"
    p_2 = format_telegram_push_payload(msg_2, chat_id=chat_id, signal_id=sig_2, is_update=False)
    assert "reply_to_message_id" not in p_2, "Call #2 must NOT thread under Call #1!"

    # Simulate Call #2 sent with message ID 221
    record_signal_message_id(sig_2, 221, chat_id=chat_id)

    # Milestone for Call #1 (e.g. Target 1 for Call #1) -> must thread to 216
    up_1 = f"🎯 [REAL/LIVE] UPDATE #1 · TARGET 1 HIT\n🏆 BTCUSDT Target 1 Hit\n🏷️ Ref: #{sig_1}"
    p_up_1 = format_telegram_push_payload(up_1, chat_id=chat_id, signal_id=sig_1, is_update=True)
    assert p_up_1["reply_to_message_id"] == 216

    # Milestone for Call #2 (e.g. Target 1 for Call #2) -> must thread to 221
    up_2 = f"🎯 [REAL/LIVE] UPDATE #1 · TARGET 1 HIT\n🏆 BTCUSDT Target 1 Hit\n🏷️ Ref: #{sig_2}"
    p_up_2 = format_telegram_push_payload(up_2, chat_id=chat_id, signal_id=sig_2, is_update=True)
    assert p_up_2["reply_to_message_id"] == 221
