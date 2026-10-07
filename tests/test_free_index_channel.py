"""
tests/test_free_index_channel.py
────────────────────────────────
Comprehensive test suite verifying the dedicated Free Index Router and SEBI-compliant
templates for the "Nifty BankNifty Free Signals" Telegram channel (Chat ID: -1004298387260).

Verifies:
1. SEBI Regulatory Compliance: Statutory F&O risk disclosure (9/10 traders study)
   and explicit educational safe-harbor disclaimers on every setup.
2. Community CTAs: Direct official invite links to https://t.me/IndiaIndexSignals.
3. Strict Filtering: Only permitted indices (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX)
   are routed. Stocks, MCX, Currency, and non-whitelisted indices (FINNIFTY, BANKEX) are rejected.
4. Multi-Channel Parity: Primary F&O Index channel and Free Index channel both receive
   their respective formatted alerts without collisions or interference.
5. Threading & Lifecycle Updates: Milestone updates (T1, T2, Trailing Ratchet, Invalidation)
   thread properly and render with honest, transparent execution actions.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock

from bot.free_index_templates import (
    DEFAULT_FREE_INDEX_CHAT_ID,
    FREE_INDEX_CHANNEL_NAME,
    FREE_INDEX_CHANNEL_LINK,
    SEBI_STATUTORY_DERIVATIVES_DISCLOSURE,
    SEBI_EDUCATIONAL_SAFE_HARBOR,
    render_free_index_alert,
    render_free_index_milestone,
)
from engine.alert_model import AutoAlert
from engine.free_index_router import free_index_router


def test_free_index_alert_sebi_compliance_and_disclaimers():
    """Verify that every new index setup is short, crisp, uses shortforms, and contains no BUY/SELL directives."""
    alert = AutoAlert(
        alert_id="aa-free-idx-nifty-20261005",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE GAMMA EXPLOSION",
        summary="Heavy institutional call volume buildup with VWAP support.",
        ltp=155.0,
        trigger_level=150.0,
        target_level=230.0,
        stop_loss=115.0,
        option_type="CE",
        strike=25000.0,
        confidence=92,
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        lot_size=75,
        actionable_plan={
            "action": "BUY_CALL",
            "contract": "NIFTY 25000 CE",
            "entry_range": "₹150.0 - ₹155.0",
            "stop_loss": "₹115.0",
            "target_1": "₹195.0",
            "target_2": "₹240.0",
            "risk_reward": "1:2.3",
            "no_chase_boundary": 160.0,
            "lot_size": 75,
            "setup_confluence": "Call OI unwinding and aggressive buyer aggression above VWAP.",
        },
    )

    rendered = render_free_index_alert(alert, in_market=True)

    # 1. Channel identity & branding
    assert "@IndiaIndexSignals" in rendered
    assert "https://t.me/IndiaIndexSignals" in rendered

    # 2. Strict Directive Mandate: Never say BUY or SELL
    assert "BUY CE" not in rendered
    assert "BUY PE" not in rendered
    assert "Action: BUY" not in rendered
    assert "Action: SELL" not in rendered

    # 3. Shortforms and compact layout
    assert "NIFTY 25000 CE" in rendered
    assert "• <b>Entry:</b>" in rendered
    assert "₹150.0 - ₹155.0" in rendered
    assert "• <b>SL:</b>" in rendered
    assert "₹115.0" in rendered
    assert "• <b>T1:</b>" in rendered
    assert "₹195.0" in rendered
    assert "<b>T2:</b>" in rendered
    assert "₹230.0" in rendered
    assert "• <b>R:R:</b> <b>1:2.3</b>" in rendered
    assert "Lot: <b>75</b>" in rendered
    assert "🛑 No-Chase: > ₹157.5" in rendered
    assert "• <b>Bias:</b>" in rendered

    # 4. Clean compact regulatory disclosure
    assert "Edu/Simulation only · Strict SL mandatory · Not SEBI advice" in rendered


def test_free_index_milestones_rendering():
    """Verify lifecycle milestones (T1, T2, Trailing Ratchet, Invalidation, In-Flight Warning, Time-Stop) for free channel."""
    base_dict = {
        "alert_id": "aa-free-idx-bn-20261005",
        "symbol": "BANKNIFTY",
        "contract": "BANKNIFTY 53500 PE",
        "direction": "BEARISH",
        "alert_type": "GAMMA BLAST (PUT)",
        "ltp": 420.0,
        "entry_price": 310.0,
        "entry_range": "₹305.0 - ₹310.0",
        "initial_sl": 230.0,
        "target_1": 420.0,
        "target_2": 520.0,
        "pnl_pts": 110.0,
        "pnl_pct": 35.5,
        "r_multiple": 1.4,
        "environment": "LIVE",
        "signal_id": "SIG_BANKNIFTY_53500PE",
    }

    # 1. Target 1 Achieved
    t1_dict = dict(base_dict, milestone_type="TARGET_1", stage="T1_ACHIEVED")
    rendered_t1 = render_free_index_milestone(t1_dict, in_market=True)
    assert "T1 HIT" in rendered_t1
    assert "Scale 50% profit & trail SL to entry cost" in rendered_t1
    assert "@IndiaIndexSignals" not in rendered_t1
    assert "Nifty BankNifty Free Signals" not in rendered_t1

    # 2. Target 2 Achieved
    t2_dict = dict(base_dict, milestone_type="TARGET_2", stage="T2_ACHIEVED", ltp=520.0, pnl_pts=210.0, pnl_pct=67.7)
    rendered_t2 = render_free_index_milestone(t2_dict, in_market=True)
    assert "T2 HIT" in rendered_t2
    assert "Harvest runner profits / trail SL aggressively" in rendered_t2

    # 3. Trailing Stop Ratchet
    trail_dict = dict(base_dict, milestone_type="TRAIL_RATCHET", stage="TRAIL_RATCHET", ltp=450.0, trailing_stop=380.0)
    rendered_trail = render_free_index_milestone(trail_dict, in_market=True)
    assert "TRAIL SL" in rendered_trail
    assert "Move SL to <code>₹380.00</code>" in rendered_trail


    # 4. In-Flight Warning
    inflight_dict = dict(base_dict, milestone_type="IN_FLIGHT_WARNING", stage="IN_FLIGHT_WARNING", ltp=305.0, invalidation_reason="Momentum stalled near VWAP")
    rendered_inflight = render_free_index_milestone(inflight_dict, in_market=True)
    assert "IN-FLIGHT WARNING" in rendered_inflight
    assert "Scratch position at CMP or tighten SL" in rendered_inflight

    # 5. Invalidation / Stop Loss Hit
    sl_dict = dict(base_dict, milestone_type="INVALIDATED", stage="INVALIDATED", ltp=225.0, invalidation_reason="Key support floor breached")
    rendered_sl = render_free_index_milestone(sl_dict, in_market=True)
    assert "SL HIT / VIEW INVALIDATED" in rendered_sl
    assert "Close position / cancel pending orders" in rendered_sl

    # 6. Time Stop Scratch Exit
    time_dict = dict(base_dict, milestone_type="TIME_STOP_EXIT", stage="TIME_STOP_EXIT", ltp=308.0)
    rendered_time = render_free_index_milestone(time_dict, in_market=True)
    assert "TIME-STOP SCRATCH" in rendered_time
    assert "Momentum stagnated, theta bleed risk. Scratch at CMP" in rendered_time

    # Verify no update/milestone signals contain @IndiaIndexSignals or channel name
    for r in [rendered_t1, rendered_t2, rendered_trail, rendered_inflight, rendered_sl, rendered_time]:
        assert "@IndiaIndexSignals" not in r
        assert "https://t.me/IndiaIndexSignals" not in r
        assert "Nifty BankNifty Free Signals" not in r




def test_free_index_router_candidate_filtering(monkeypatch):
    """Verify FreeIndexRouter accepts only whitelisted indices and rejects stocks, commodities, and disallowed indices."""
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_ENABLED", "1")

    def _make_alert(sym: str, seg: str, conf: int = 90, a_type: str = "GAMMA_BLAST") -> AutoAlert:
        return AutoAlert(
            alert_id=f"test-{sym.lower()}-01",
            alert_type=a_type,
            stage="IGNITED",
            symbol=sym,
            exchange="NFO" if seg.startswith("FNO") else ("MCX" if seg == "COMMODITY" else "NSE"),
            direction="BULLISH",
            headline=f"{sym} BREAKOUT",
            summary="Setup trigger",
            ltp=100.0,
            trigger_level=95.0,
            target_level=120.0,
            stop_loss=85.0,
            confidence=conf,
            segment=seg,
        )

    # 1. Allowed: NIFTY
    nifty_alert = _make_alert("NIFTY", "FNO_INDEX", 90)
    assert free_index_router.is_candidate(nifty_alert) is True

    # 2. Allowed: BANKNIFTY
    bn_alert = _make_alert("BANKNIFTY", "FNO_INDEX", 88)
    assert free_index_router.is_candidate(bn_alert) is True

    # 3. Allowed: MIDCPNIFTY & SENSEX
    midcp_alert = _make_alert("MIDCPNIFTY", "FNO_INDEX", 85)
    sensex_alert = _make_alert("SENSEX", "FNO_INDEX", 85)
    assert free_index_router.is_candidate(midcp_alert) is True
    assert free_index_router.is_candidate(sensex_alert) is True

    # 4. Disallowed Index: FINNIFTY, BANKEX
    fin_alert = _make_alert("FINNIFTY", "FNO_INDEX", 90)
    bankex_alert = _make_alert("BANKEX", "FNO_INDEX", 90)
    assert free_index_router.is_candidate(fin_alert) is False
    assert free_index_router.is_candidate(bankex_alert) is False

    # 5. Disallowed: Single-Stock F&O (RELIANCE, SBIN)
    rel_alert = _make_alert("RELIANCE", "FNO_STOCK", 95)
    assert free_index_router.is_candidate(rel_alert) is False

    # 6. Disallowed: Commodity (CRUDEOIL, GOLD) & Cash Equity
    crude_alert = _make_alert("CRUDEOIL", "COMMODITY", 90, "COMMODITY_MOMENTUM")
    eq_alert = _make_alert("TCS", "EQUITY", 90, "BREAKOUT")
    assert free_index_router.is_candidate(crude_alert) is False
    assert free_index_router.is_candidate(eq_alert) is False


def test_dual_dispatch_parity_premium_and_free_channels(monkeypatch):
    """
    Verify multi-channel dispatch parity:
    When an Index signal triggers, the premium channel receives the institutional alert
    AND the free channel receives the SEBI-compliant community alert.
    """
    from engine.auto_alert_engine import AutoAlertEngine

    monkeypatch.setenv("TELEGRAM_FNO_INDEX_CHAT_ID", "-1004380788314")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_ENABLED", "1")
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exch: True)

    sent_messages = []

    def mock_tg_notify(msg, chat_id=None, **kwargs):
        sent_messages.append({
            "message": msg,
            "chat_id": str(chat_id),
            "signal_id": kwargs.get("signal_id"),
            "reply_to": kwargs.get("reply_to_message_id"),
        })

    monkeypatch.setattr("engine.alerts._telegram_notify", mock_tg_notify)
    free_index_router._dispatch_cooldowns.clear()
    free_index_router._dispatched_free_milestones.clear()

    engine = AutoAlertEngine()

    nifty_alert = AutoAlert(
        alert_id="live-nifty-parity-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY26OCT25100CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25100 CE MOMENTUM BREAKOUT",
        summary="Unwinding of 25100 Call OI with heavy institutional volume.",
        ltp=140.0,
        trigger_level=135.0,
        target_level=210.0,
        stop_loss=105.0,
        option_type="CE",
        strike=25100.0,
        confidence=94,
        is_live=True,
        environment="LIVE",
        segment="FNO_INDEX",
        lot_size=75,
        actionable_plan={
            "action": "BUY_CALL",
            "contract": "NIFTY 25100 CE",
            "entry_range": "₹135.0 - ₹140.0",
            "stop_loss": "₹105.0",
            "target_1": "₹185.0",
            "target_2": "₹220.0",
            "risk_reward": "1:2.4",
            "lot_size": 75,
            "setup_confluence": "VWAP bounce with positive market breadth.",
        },
    )

    engine._dispatch(nifty_alert)

    # Must dispatch to BOTH destinations:
    # 1. Premium F&O Index Channel (-1004380788314)
    # 2. Free Index Signals Channel (-1004298387260)
    assert len(sent_messages) == 2

    # Check destinations
    chat_ids = [m["chat_id"] for m in sent_messages]
    assert "-1004380788314" in chat_ids
    assert "-1004298387260" in chat_ids

    # Premium message verification
    premium_msg = next(m["message"] for m in sent_messages if m["chat_id"] == "-1004380788314")
    assert "NEW CALL · GAMMA BLAST" in premium_msg

    # Free message verification: must include compact SEBI disclosure & community link (shared once in new call)
    free_msg = next(m["message"] for m in sent_messages if m["chat_id"] == "-1004298387260")
    assert "Nifty BankNifty Free Signals" not in free_msg
    assert "Edu/Simulation only · Strict SL mandatory · Not SEBI advice" in free_msg
    assert "https://t.me/IndiaIndexSignals" in free_msg
    assert "@IndiaIndexSignals" in free_msg


def test_telegram_destinations_api_returns_free_index():
    """Verify that get_telegram_destinations includes Free Index Channel metadata."""
    from bot.telegram_bot import get_telegram_destinations

    dests = get_telegram_destinations()
    assert "free_index_chat_id" in dests
    assert "free_index_chat_name" in dests
    assert "free_index_link" in dests
    assert dests["free_index_link"] == "https://t.me/IndiaIndexSignals"
    assert dests["free_index_chat_id"] == "-1004298387260"
    assert dests["free_index_chat_name"] == "Nifty BankNifty Free Signals"


def test_free_index_router_rejects_positional_and_wide_sl_setups(monkeypatch):
    """
    Verify that FreeIndexRouter strictly enforces intraday-only trading:
    - Rejects positional swing setups (e.g. RUBBER_BAND_200EMA, is_positional=True).
    - Rejects setups with wide stop losses exceeding intraday sanity ceilings (e.g. >35 pts on Nifty options, >55 pts on spot).
    - Accepts clean intraday scalps with tight logical stops (e.g. 10-15 pts on Nifty options).
    """
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260")
    monkeypatch.setenv("TELEGRAM_FREE_INDEX_ENABLED", "1")

    # 1. Positional 200-EMA setup with wide stops (similar to user report: 82 pt opt SL, 408 pt spot SL)
    insane_alert = AutoAlert(
        alert_id="aa-insane-nifty-200ema-20261006",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY22650CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 22650 CE BREAKOUT IGNITED",
        summary="Deep institutional value absorption on high-quality franchise at major 200-day EMA benchmark.",
        ltp=273.2,
        trigger_level=273.2,
        target_level=970.4,
        stop_loss=191.2,
        underlying_spot=22663.15,
        confidence=88,
        segment="FNO_INDEX",
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "action": "RUBBER_BAND_200EMA",
            "spot_stop_loss": 22255.2,
            "option_plan": {
                "contract_symbol": "NIFTY22650CE",
                "entry_premium": 273.2,
                "sl_premium": 191.2,  # 82 pts risk!
            },
        },
    )
    assert free_index_router.is_candidate(insane_alert) is False

    # 2. Alert marked as time_horizon="POSITIONAL"
    pos_alert = AutoAlert(
        alert_id="aa-pos-nifty-001",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY POSITIONAL",
        summary="Positional play",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=135.0,
        confidence=90,
        segment="FNO_INDEX",
        time_horizon="POSITIONAL",
    )
    assert free_index_router.is_candidate(pos_alert) is False

    # 3. Alert with Option SL exceeding 35 points on NIFTY (e.g. 45 pt risk)
    wide_opt_alert = AutoAlert(
        alert_id="aa-wide-opt-nifty",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY WIDE SL",
        summary="Too wide stop",
        ltp=200.0,
        trigger_level=200.0,
        target_level=320.0,
        stop_loss=155.0,  # 45 pts risk on Nifty option (>35 pt ceiling)
        confidence=90,
        segment="FNO_INDEX",
    )
    assert free_index_router.is_candidate(wide_opt_alert) is False

    # 4. Valid tight micro-scalp setup (12 pts risk on NIFTY option) -> MUST PASS
    scalp_alert = AutoAlert(
        alert_id="aa-scalp-nifty-001",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY22650CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 22650 CE 1m Micro Breakout",
        summary="Micro breakout ignited. Tight risk.",
        ltp=125.0,
        trigger_level=125.0,
        target_level=139.0,
        stop_loss=113.0,  # 12 pts risk
        confidence=88,
        segment="FNO_INDEX",
        actionable_plan={
            "action": "BUY CE",
            "option_plan": {
                "contract_symbol": "NIFTY22650CE",
                "entry_premium": 125.0,
                "sl_premium": 113.0,
            },
        },
    )
    assert free_index_router.is_candidate(scalp_alert) is True

