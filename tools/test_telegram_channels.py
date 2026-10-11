#!/usr/bin/env python3
"""
tools/test_telegram_channels.py
───────────────────────────────
Institutional Telegram Multi-Channel Connectivity & Permission Audit Tool.

Audits bot token credentials, channel memberships, posting permissions,
and optionally dispatches live diagnostic heartbeat pings across all configured channels:
  1. Cash Equity (-1003524867091)
  2. F&O Stocks (-1004393392375)
  3. F&O Index (-1004380788314)
  4. Free Index Signals (-1004298387260)
  5. MCX Commodities & Currency (-1004320002599)
  6. 24x7 Crypto Majors (-1004323607372)

Usage:
    python tools/test_telegram_channels.py           # Audit permissions & connectivity (read-only)
    python tools/test_telegram_channels.py --ping    # Audit + send test heartbeat messages
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from config.constants import IST


def get_configured_channels() -> list[dict[str, Any]]:
    from engine.alert_preferences import alert_preferences

    return [
        {
            "segment": "EQUITY",
            "name": "Equity_Premium_Alpha_Vortex",
            "chat_id": alert_preferences.get_telegram_chat_id("EQUITY"),
            "desc": "Cash Equities & High-Momentum SEPA Breakouts",
            "icon": "🏢",
        },
        {
            "segment": "FNO_STOCK",
            "name": "FnO_Stocks_Premium_Alpha_Vortex",
            "chat_id": alert_preferences.get_telegram_chat_id("FNO_STOCK"),
            "desc": "Single-Stock Options (CE/PE) & Stock Futures",
            "icon": "🎯",
        },
        {
            "segment": "FNO_INDEX",
            "name": "FnO_Index_Premium_Alpha_Vortex",
            "chat_id": alert_preferences.get_telegram_chat_id("FNO_INDEX"),
            "desc": "Index Options (NIFTY, BANKNIFTY, MIDCP, SENSEX)",
            "icon": "⚡",
        },
        {
            "segment": "FREE_INDEX",
            "name": "Nifty BankNifty Free Signals",
            "chat_id": alert_preferences.get_telegram_chat_id("FREE_INDEX"),
            "desc": "Public Broadcast Index Signals",
            "icon": "📢",
        },
        {
            "segment": "COMMODITY",
            "name": "MCX_Premium_Alpha_Vortex",
            "chat_id": alert_preferences.get_telegram_chat_id("COMMODITY"),
            "desc": "Crude Oil, Natural Gas, Gold, Silver & CDS",
            "icon": "🌙",
        },
        {
            "segment": "CRYPTO",
            "name": "Crypto_Premium_Alpha_Vortex",
            "chat_id": alert_preferences.get_telegram_chat_id("CRYPTO"),
            "desc": "24x7 Crypto Majors (BTC, ETH, SOL, BNB)",
            "icon": "💎",
        },
    ]


def audit_channels(send_ping: bool = False, target_segment: str | None = None) -> int:
    from bot.telegram_bot import _get_bot_token

    try:
        token = _get_bot_token()
    except Exception as e:
        print(f"[FAIL] Failed to retrieve bot token: {e}")
        return 1

    if not token:
        print("[FAIL] Bot token is empty.")
        return 1

    print("\n=======================================================")
    print("  CHANAKYA-TRADE TELEGRAM MULTI-CHANNEL AUDIT")
    print("=======================================================")

    # 1. Verify Bot Identity
    base_url = f"https://api.telegram.org/bot{token}"
    try:
        resp = httpx.get(f"{base_url}/getMe", timeout=10)
        bot_data = resp.json()
        if not bot_data.get("ok"):
            print(f"[FAIL] getMe failed: {bot_data}")
            return 1
        bot_user = bot_data.get("result", {})
        bot_id = bot_user.get("id")
        bot_name = bot_user.get("username")
        print(f"Bot Identity : @{bot_name} (ID: {bot_id})")
    except Exception as e:
        print(f"[FAIL] Cannot connect to Telegram Bot API: {e}")
        return 1

    channels = get_configured_channels()
    if target_segment:
        channels = [c for c in channels if c["segment"].upper() == target_segment.upper()]
        if not channels:
            print(f"[FAIL] Segment '{target_segment}' not found.")
            return 1

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"Timestamp    : {now_iso}")
    print(f"Channels     : {len(channels)} registered")
    print(f"Mode         : {'SEND LIVE PING' if send_ping else 'READ-ONLY AUDIT'}")
    print("-------------------------------------------------------\n")

    overall_ok = True

    for ch in channels:
        seg = ch["segment"]
        name = ch["name"]
        cid = ch["chat_id"]
        icon = ch["icon"]

        print(f"{icon} [{seg}] {name}")
        print(f"    Chat ID     : {cid}")

        if not cid:
            print("    Status      : [FAIL] chat_id not configured")
            overall_ok = False
            print()
            continue

        # Check getChat
        chat_ok = False
        chat_title = ""
        try:
            c_resp = httpx.get(f"{base_url}/getChat", params={"chat_id": cid}, timeout=10)
            c_data = c_resp.json()
            if c_data.get("ok"):
                chat_ok = True
                chat_title = c_data.get("result", {}).get("title", "")
                chat_type = c_data.get("result", {}).get("type", "")
                print(f"    Title       : {chat_title} (Type: {chat_type})")
            else:
                print(f"    getChat     : [FAIL] {c_data.get('description', 'Unknown error')}")
                overall_ok = False
        except Exception as e:
            print(f"    getChat     : [FAIL] Exception: {e}")
            overall_ok = False

        # Check getChatMember (bot permissions)
        if chat_ok:
            try:
                m_resp = httpx.get(
                    f"{base_url}/getChatMember",
                    params={"chat_id": cid, "user_id": bot_id},
                    timeout=10,
                )
                m_data = m_resp.json()
                if m_data.get("ok"):
                    res = m_data.get("result", {})
                    status = res.get("status", "")
                    can_post = res.get("can_post_messages", False)
                    print(f"    Bot Role    : {status.upper()} (Can Post: {can_post})")
                    if status != "administrator" and not can_post:
                        print("    Permissions : [WARN] Bot is not administrator or cannot post")
                else:
                    print(f"    Permissions : [WARN] {m_data.get('description', '')}")
            except Exception as e:
                print(f"    Permissions : [WARN] Exception: {e}")

        # Send test ping if requested
        if send_ping and chat_ok:
            ping_msg = (
                f"📡 <b>[ALPHA VORTEX CHANNEL AUDIT]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ <b>Channel:</b> {name}\n"
                f"🎯 <b>Segment:</b> <code>{seg}</code>\n"
                f"🕒 <b>Timestamp:</b> <code>{now_iso}</code>\n"
                f"⚡ <b>Gateway:</b> Automated Multi-Channel Pipeline Verified\n"
                f"<i>Diagnostic test message — no trade action required.</i>"
            )
            try:
                p_resp = httpx.post(
                    f"{base_url}/sendMessage",
                    json={"chat_id": cid, "text": ping_msg, "parse_mode": "HTML"},
                    timeout=10,
                )
                p_data = p_resp.json()
                if p_data.get("ok"):
                    msg_id = p_data.get("result", {}).get("message_id")
                    print(f"    Ping Status : [OK] Message ID {msg_id} delivered successfully")
                else:
                    print(f"    Ping Status : [FAIL] {p_data.get('description')}")
                    overall_ok = False
            except Exception as e:
                print(f"    Ping Status : [FAIL] Exception sending ping: {e}")
                overall_ok = False

        print()

    print("=======================================================")
    if overall_ok:
        print("  [SUCCESS] All checked Telegram channels are fully verified!")
    else:
        print("  [WARNING] Some channels experienced issues. Check logs above.")
    print("=======================================================\n")
    return 0 if overall_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and test Telegram multi-channel routing.")
    parser.add_argument("--ping", action="store_true", help="Send live test heartbeat to channels")
    parser.add_argument("--segment", type=str, help="Filter audit to a single segment")
    args = parser.parse_args()

    exit_code = audit_channels(send_ping=args.ping, target_segment=args.segment)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
