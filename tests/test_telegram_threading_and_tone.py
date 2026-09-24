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
    assert "disable_notification" not in p_explicit_loud or p_explicit_loud.get("disable_notification") is False


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

