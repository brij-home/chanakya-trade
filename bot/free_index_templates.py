"""
bot/free_index_templates.py
───────────────────────────
Institutional, SEBI-compliant Telegram message templates and formatter specifically
crafted for the "Nifty BankNifty Free Signals" Telegram channel (https://t.me/IndiaIndexSignals).

Chat ID: -1004298387260
Channel Name: Nifty BankNifty Free Signals
Link: https://t.me/IndiaIndexSignals

Compliance & Regulatory Standards:
- SEBI Mandatory Derivatives Risk Disclosure (Circular SEBI/HO/MRD/MRD-PoD-1/P/CIR/2023/155):
  Statutory disclosure regarding the 9 out of 10 individual traders incurring net losses in F&O.
- Safe-Harbor Educational Declaration:
  Explicit statement that signals are algorithmic research/paper-trading case studies,
  NOT SEBI registered Research Analyst (RA) or Investment Advisor (IA) recommendations.
- Capital Protection & Risk Management:
  Clear blueprint with mandatory invalidation stop loss, target 1 (+2R de-risking),
  trailing stops, risk:reward, and strict "NO CHASE" discipline to safeguard retail traders.
- Community Growth:
  Crisp, high-value presentation, educational confluence, and direct channel links.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from bot.alert_templates import (
    format_contract_display,
    build_signal_ref,
    normalize_env_tag,
    _format_call_time_and_elapsed,
    _resolve_monotonic_display_targets,
    MilestoneAlertData,
)

logger = logging.getLogger("bot.free_index_templates")

IST = timezone(timedelta(hours=5, minutes=30))

# ── Channel Metadata ────────────────────────────────────────────────────────
FREE_INDEX_CHANNEL_NAME = "Nifty BankNifty Free Signals"
FREE_INDEX_CHANNEL_LINK = "https://t.me/IndiaIndexSignals"
FREE_INDEX_CHANNEL_HANDLE = "@IndiaIndexSignals"
DEFAULT_FREE_INDEX_CHAT_ID = "-1004298387260"

# ── SEBI Disclaimers & Statutory Safe Harbors ────────────────────────────────
SEBI_STATUTORY_DERIVATIVES_DISCLOSURE = (
    "• <b>SEBI F&O Study:</b> <i>9 out of 10 individual traders in equity Futures and "
    "Options incur net losses (average loss ~₹50,000 + 28% transaction costs). "
    "Trade with strict stop loss and disciplined risk management.</i>"
)

SEBI_EDUCATIONAL_SAFE_HARBOR = (
    "• <b>Educational Only:</b> <i>This setup is shared strictly for educational, case-study, "
    "and paper-trading simulation purposes. We are NOT a SEBI-registered Research Analyst (RA) "
    "or Investment Advisor (IA). No guaranteed profits, financial advisory, or execution services "
    "are offered. Consult your SEBI-registered financial advisor before taking any financial decisions.</i>"
)

SEBI_FULL_DISCLAIMER_BLOCK = (
    f"⚖️ <b>SEBI COMPLIANCE & RISK DISCLOSURE:</b>\n"
    f"{SEBI_EDUCATIONAL_SAFE_HARBOR}\n"
    f"{SEBI_STATUTORY_DERIVATIVES_DISCLOSURE}"
)

SEBI_COMPACT_DISCLAIMER = (
    "⚖️ <i>Edu/Simulation only · Strict SL mandatory · Not SEBI advice</i>"
)

COMMUNITY_CTA_BLOCK = (
    f"👥 <a href=\"{FREE_INDEX_CHANNEL_LINK}\">{FREE_INDEX_CHANNEL_HANDLE}</a>"
)


# ── Milestone / Lifecycle Template Formatter ────────────────────────────────
def render_free_index_milestone(
    data: MilestoneAlertData | dict[str, Any], in_market: bool = True
) -> str:
    """
    Renders a short, crisp, institutional lifecycle update for the free index channel.
    Covers: Target 0.5, Target 1, Target 2, Final Target, Trailing Ratchet, Invalidation (SL Hit),
    In-Flight Warning, Runner Exit, and Time-Stop Scratch.
    """
    if isinstance(data, dict):
        d = MilestoneAlertData(
            milestone_type=data.get("milestone_type", "TRAIL_RATCHET"),
            symbol=data.get("symbol", "INDEX"),
            alert_type=data.get("alert_type", "SETUP").replace("_", " "),
            ltp=float(data.get("ltp", 0.0)),
            target_level=data.get("target_level"),
            trailing_stop=data.get("trailing_stop"),
            locked_profit_pts=data.get("locked_profit_pts"),
            locked_profit_pct=data.get("locked_profit_pct"),
            decisive_action=data.get("decisive_action", ""),
            rationale=data.get("rationale") or data.get("trailing_rationale"),
            invalidation_reason=data.get("invalidation_reason"),
            should_trail=data.get("should_trail", True),
            environment=data.get("environment", "LIVE"),
            in_market=in_market,
            timestamp=data.get("timestamp", ""),
            signal_id=data.get("signal_id"),
            contract=data.get("contract") or data.get("contract_symbol"),
            call_time=data.get("call_time") or data.get("created_at"),
            entry_price=data.get("entry_price"),
            entry_range=data.get("entry_range"),
            initial_sl=data.get("initial_sl") or data.get("stop_loss"),
            target_0_5=data.get("target_0_5"),
            target_1=data.get("target_1"),
            target_2=data.get("target_2"),
            target_moonshot=data.get("target_moonshot"),
            pnl_pts=data.get("pnl_pts"),
            pnl_pct=data.get("pnl_pct"),
            r_multiple=data.get("r_multiple"),
            direction=data.get("direction", "BULLISH"),
            segment=data.get("segment", "FNO_INDEX"),
            exchange=data.get("exchange", "NFO"),
            lot_size=data.get("lot_size"),
            strike_roll_recommendation=data.get("strike_roll_recommendation"),
            update_number=data.get("update_number"),
            is_t1_achieved=bool(data.get("is_t1_achieved", False)),
        )
    else:
        d = data

    up_num = getattr(d, "update_number", None)
    if up_num is None:
        type_order_map = {
            "TARGET_0_5": 1,
            "TARGET_1": 1,
            "TARGET_2": 2,
            "FINAL_TARGET": 3,
            "TRAIL_RATCHET": 1,
            "RUNNER_EXIT": 2,
            "PROFIT_SECURED": 2,
            "BREAKEVEN_EXIT": 2,
            "TIME_STOP_SCRATCH": 1,
            "TIME_STOP_EXIT": 1,
            "INVALIDATED": 1,
            "IN_FLIGHT_WARNING": 1,
        }
        up_num = type_order_map.get(str(d.milestone_type).upper(), 1)
    update_prefix = f"UPDATE #{up_num} · " if up_num else "UPDATE · "

    contract_title = format_contract_display(d.contract or d.symbol)
    if d.symbol and d.symbol not in contract_title:
        contract_title = f"{d.symbol} {contract_title}"

    contract_upper = str(d.contract or "").upper()
    is_pe = "PE" in contract_upper or str(d.direction).upper() in ("BEARISH", "SHORT", "SELL")
    color_icon = "🔴" if is_pe else "🟢"

    call_time_fmt, elapsed_fmt = _format_call_time_and_elapsed(d.call_time, d.timestamp)
    call_time_part = (
        f" · 📞 {call_time_fmt}{elapsed_fmt}" if call_time_fmt else ""
    )
    ref_line = (
        f"🏷️ <code>{d.signal_id}</code>{call_time_part}"
        if d.signal_id
        else (f"📞 {call_time_fmt}{elapsed_fmt}" if call_time_fmt else "")
    )
    footer_line = f"\n{ref_line}" if ref_line else ""

    # Movement and P&L string
    move_str = ""
    if d.pnl_pts is not None and d.pnl_pct is not None:
        sign = "+" if d.pnl_pts >= 0 else ""
        r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
        move_str = f" · 🚀 <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"

    # Determine if this trade's payoff direction is downward (short/sell)
    # Option contracts: Buyers (both Call CE and Put PE) profit on premium expansion (UPWARD); Writers profit on decay (DOWNWARD).
    # Cash/Futures: Short positions profit on price decline (DOWNWARD).
    is_opt = bool(
        getattr(d, "option_type", None)
        or "PE" in str(d.contract or "").upper()
        or "CE" in str(d.contract or "").upper()
        or getattr(d, "alert_type", "") in ("OPTIONS MOMENTUM", "GAMMA BLAST", "INDEX CALL SETUP", "INDEX PUT SETUP")
    )
    if is_opt:
        act_str = str(getattr(d, "decisive_action", "") or "").upper()
        is_option_seller = any(k in act_str for k in ("SELL", "WRITE", "SHORT"))
        is_downward_target = is_option_seller
    else:
        if d.target_1 and d.entry_price and d.entry_price > 0:
            is_downward_target = d.target_1 < d.entry_price
        else:
            is_downward_target = str(d.direction).upper() in ("BEARISH", "SHORT", "SELL")

    # Invariant Guard: Defense-in-depth physical price reach validation (Rules 6, 10, & 23).
    # Prevent rendering false target achievements if market price has not physically reached target level.
    if d.milestone_type in ("TARGET_2", "TARGET_2_HIT", "T2_ACHIEVED"):
        is_t2_downward = is_downward_target
        has_hit_t2 = (
            d.target_2 is not None
            and d.target_2 > 0
            and d.ltp > 0
            and (
                (not is_t2_downward and d.ltp >= d.target_2 * 0.998)
                or (is_t2_downward and d.ltp <= d.target_2 * 1.002)
            )
        )
        if not has_hit_t2:
            logger.warning(
                f"[FreeIndexTemplates] Defensively vetoed false TARGET_2 render for {d.symbol}: "
                f"LTP={d.ltp} vs T2={d.target_2} (downward={is_t2_downward}). Checking T1 reach."
            )
            has_hit_t1 = (
                d.target_1 is not None
                and d.target_1 > 0
                and d.ltp > 0
                and (
                    (not is_downward_target and d.ltp >= d.target_1 * 0.998)
                    or (is_downward_target and d.ltp <= d.target_1 * 1.002)
                )
            )
            if has_hit_t1:
                d.milestone_type = "TARGET_1"
            else:
                d.milestone_type = "TARGET_0_5"

    if d.milestone_type in ("TARGET_1", "TARGET_1_HIT", "T1_ACHIEVED"):
        has_hit_t1 = (
            d.target_1 is not None
            and d.target_1 > 0
            and d.ltp > 0
            and (
                (not is_downward_target and d.ltp >= d.target_1 * 0.998)
                or (is_downward_target and d.ltp <= d.target_1 * 1.002)
            )
        )
        if not has_hit_t1:
            logger.warning(
                f"[FreeIndexTemplates] Defensively vetoed false TARGET_1 render for {d.symbol}: "
                f"LTP={d.ltp} vs T1={d.target_1} (downward={is_downward_target}). Re-routing to TARGET_0_5."
            )
            d.milestone_type = "TARGET_0_5"

    # 1. Target 1 Achieved
    if d.milestone_type in ("TARGET_1", "TARGET_1_HIT", "T1_ACHIEVED"):
        return (
            f"🎯 <b>{update_prefix}T1 HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> hit T1 @ <code>₹{d.ltp:,.2f}</code>!{move_str}\n"
            f"• <b>Action:</b> Scale 50% profit & trail SL to entry cost.\n"
            f"• <b>Next:</b> Remaining 50% runner targeting T2.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 2. Target 2 / Final Target Achieved
    if d.milestone_type in ("TARGET_2", "FINAL_TARGET", "TARGET_ACHIEVED", "COMPLETED"):
        target_name = "FINAL TARGET" if d.milestone_type in ("FINAL_TARGET", "COMPLETED") else "T2"
        return (
            f"🚀 <b>{update_prefix}{target_name} HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> reached {target_name} @ <code>₹{d.ltp:,.2f}</code>!{move_str}\n"
            f"• <b>Action:</b> Harvest runner profits / trail SL aggressively.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 3. Target 0.5 (De-Risking)
    if d.milestone_type in ("TARGET_0_5", "T0_5_ACHIEVED", "DE_RISK_0_5R", "TARGET_0_5_HIT", "SCALE_1_ACHIEVED", "T0.5_ACHIEVED"):
        return (
            f"⚡ <b>{update_prefix}T0.5 DE-RISK</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> @ <code>₹{d.ltp:,.2f}</code>{move_str}\n"
            f"• <b>Action:</b> Tighten SL to reduce risk; prepare to scale 50% at T1.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 3c. Breakeven Locked (Free Roll)
    if d.milestone_type == "BREAKEVEN_LOCKED":
        trail_sl = d.trailing_stop or "COST / BREAKEVEN"
        trail_val_str = f"₹{trail_sl:,.2f}" if isinstance(trail_sl, (int, float)) else str(trail_sl)
        return (
            f"🛡️ <b>{update_prefix}BREAKEVEN LOCKED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> (CMP: <code>₹{d.ltp:,.2f}</code>){move_str}\n"
            f"• <b>Action:</b> Move SL to <code>{trail_val_str}</code> (Downside Eliminated · Free Roll).\n"
            f"• <b>Next:</b> Holding runner for T1 / T2.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 4. Trailing Stop Ratchet
    if d.milestone_type in ("TRAIL_RATCHET", "TRAILING_UPDATE", "TRAIL_POST_SWEEP", "COMPRESS_STALL_RISK"):
        trail_sl = d.trailing_stop or "COST / BREAKEVEN"
        trail_val_str = f"₹{trail_sl:,.2f}" if isinstance(trail_sl, (int, float)) else str(trail_sl)
        return (
            f"⚡ <b>{update_prefix}TRAIL SL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> (CMP: <code>₹{d.ltp:,.2f}</code>){move_str}\n"
            f"• <b>Action:</b> Move SL to <code>{trail_val_str}</code> to lock profit.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 5. In-Flight Warning
    if d.milestone_type in ("IN_FLIGHT_WARNING", "VWAP_BAND_BREAKDOWN", "DANGER_ZONE"):
        reason = d.invalidation_reason or d.rationale or "Momentum stalled / band breakdown warning"
        return (
            f"⚠️ <b>{update_prefix}IN-FLIGHT WARNING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>⚠️ {contract_title}</b> (CMP: <code>₹{d.ltp:,.2f}</code>)\n"
            f"• <b>Alert:</b> <i>{reason}</i>\n"
            f"• <b>Action:</b> Scratch position at CMP or tighten SL.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 6. Invalidation / Stop Loss Hit
    if d.milestone_type in ("INVALIDATED", "STOPPED_OUT", "CANCELLED"):
        reason = d.invalidation_reason or d.rationale or "Invalidation level / stop loss breached"
        return (
            f"🛑 <b>{update_prefix}SL HIT / VIEW INVALIDATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> exited @ <code>₹{d.ltp:,.2f}</code>\n"
            f"• <b>Reason:</b> <i>{reason}</i>\n"
            f"• <b>Action:</b> Close position / cancel pending orders. Capital preserved.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 7. Runner Exit / Breakeven Exit
    if d.milestone_type in ("RUNNER_EXIT", "PROFIT_SECURED", "BREAKEVEN_EXIT", "TRAILING_STOP_EXIT"):
        is_runner_profit = bool(d.pnl_pts is not None and d.pnl_pts > 0)
        action_title = "PROFIT SECURED" if is_runner_profit else "CAPITAL PRESERVED"
        return (
            f"🏁 <b>{update_prefix}RUNNER CLOSED ({action_title})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> closed @ <code>₹{d.ltp:,.2f}</code>{move_str}\n"
            f"• <b>Action:</b> Trade completed. Capital preserved.\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # 8. Time-Stop Scratch Exit & Setup Expiry
    if d.milestone_type in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH", "EXPIRED", "TIME_EXPIRED"):
        inv_text = str(getattr(d, "invalidation_reason", "") or getattr(d, "rationale", "") or "").lower()
        is_untriggered = (
            "did not trigger" in inv_text
            or "setup did not trigger" in inv_text
            or getattr(d, "stage", "") == "EXPIRED"
            or getattr(d, "target_status", "") == "TIME_EXPIRED"
        )
        header_text = f"⏳ <b>{update_prefix}SETUP EXPIRED</b>" if is_untriggered else f"⏳ <b>{update_prefix}TIME-STOP SCRATCH</b>"
        reason_text = "Setup did not trigger within momentum window. Cancel pending orders." if is_untriggered else "Momentum stagnated, theta bleed risk. Scratch at CMP."
        return (
            f"{header_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title}</b> @ <code>₹{d.ltp:,.2f}</code>\n"
            f"• <b>Reason:</b> {reason_text}\n\n"
            f"{SEBI_COMPACT_DISCLAIMER}"
            f"{footer_line}"
        )

    # Default fallback milestone
    return (
        f"⚡ <b>{update_prefix}LIFECYCLE UPDATE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚨 <b>{color_icon} {contract_title}</b> @ <code>₹{d.ltp:,.2f}</code>\n"
        f"• <b>Status:</b> {d.decisive_action or d.milestone_type}\n\n"
        f"{SEBI_COMPACT_DISCLAIMER}"
        f"{footer_line}"
    )


# ── Primary Free Index Alert Formatter ──────────────────────────────────────
def render_free_index_alert(alert: Any, in_market: bool = True) -> str:
    """
    Renders an AutoAlert instance into a short, crisp, high-density SEBI-compliant
    Telegram message for the 'Nifty BankNifty Free Signals' channel.
    
    Standards:
    - Zero direct 'BUY' or 'SELL' directives (shares Entry Zone, SL, T1, T2 levels).
    - Uses shortforms (CMP, SL, T1, T2, R:R, Lot, No-Chase).
    - Removes bulky disclaimer paragraphs & boilerplate discipline notes.
    - High institutional density that fits cleanly on a mobile screen.
    """
    if isinstance(alert, dict):
        from engine.alert_model import AutoAlert
        alert = AutoAlert.from_dict(alert)

    symbol = getattr(alert, "symbol", "INDEX").upper()

    # 1. Check for milestone / lifecycle state first
    stage_str = str(getattr(alert, "stage", "")).upper()
    target_status = str(getattr(alert, "target_status", "")).upper()
    up_num = getattr(alert, "update_number", None)
    is_update_flag = bool(getattr(alert, "is_update", False) or (up_num is not None and up_num > 0))

    is_milestone = (
        is_update_flag
        or getattr(alert, "is_invalidated", False)
        or stage_str in (
            "INVALIDATED", "STOPPED_OUT", "CANCELLED",
            "T0_5_ACHIEVED", "TARGET_0_5", "TARGET_0_5_HIT", "SCALE_1_ACHIEVED",
            "T1_ACHIEVED", "TARGET_1", "TARGET_1_HIT",
            "T2_ACHIEVED", "TARGET_2", "TARGET_2_HIT",
            "TARGET_ACHIEVED", "COMPLETED", "FINAL_TARGET",
            "TRAILING_UPDATE", "DE_RISK_0_5R", "BREAKEVEN_LOCKED", "TRAIL_RATCHET",
            "RUNNER_EXIT", "PROFIT_SECURED", "BREAKEVEN_EXIT", "TRAILING_STOP_EXIT",
            "TIME_STOP_EXIT", "TIME_STOP_SCRATCH", "EXPIRED",
            "IN_FLIGHT_WARNING",
        )
        or target_status in (
            "T0_5", "T0.5", "T1", "T2", "TARGET", "TARGET_HIT", "TARGET_ACHIEVED",
            "FINAL_TARGET", "COMPLETED", "RUNNER_CLOSED", "RUNNER_EXIT", "PROFIT_SECURED",
            "TIME_EXPIRED", "TIME_STOP_EXIT", "TIME_STOP_SCRATCH",
        )
        or "time-stop expired" in str(getattr(alert, "archive_reason", "") or "").lower()
        or "time-stop expired" in str(getattr(alert, "summary", "") or "").lower()
        or "time-stop expired" in str(getattr(alert, "invalidation_reason", "") or "").lower()
        or getattr(alert, "is_target_hit", False)
    )

    if is_milestone:
        m_type = "TRAIL_RATCHET"
        if getattr(alert, "milestone_type", None):
            m_type = str(alert.milestone_type).upper()
        elif getattr(alert, "is_invalidated", False) or stage_str in ("INVALIDATED", "STOPPED_OUT", "CANCELLED"):
            m_type = "INVALIDATED"
        elif stage_str == "IN_FLIGHT_WARNING":
            m_type = "IN_FLIGHT_WARNING"
        elif (
            stage_str in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH", "EXPIRED")
            or target_status in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH", "TIME_EXPIRED")
            or "time-stop expired" in str(getattr(alert, "archive_reason", "") or "").lower()
            or "time-stop expired" in str(getattr(alert, "summary", "") or "").lower()
            or "time-stop expired" in str(getattr(alert, "invalidation_reason", "") or "").lower()
        ):
            m_type = "TIME_STOP_EXIT"
        elif stage_str in ("RUNNER_EXIT", "PROFIT_SECURED", "BREAKEVEN_EXIT") or target_status in ("RUNNER_CLOSED", "RUNNER_EXIT", "PROFIT_SECURED"):
            m_type = "RUNNER_EXIT"
        elif stage_str in ("FINAL_TARGET", "TARGET_ACHIEVED", "COMPLETED") or target_status in ("FINAL_TARGET", "COMPLETED"):
            m_type = "FINAL_TARGET"
        elif stage_str in ("T2_ACHIEVED", "TARGET_2", "TARGET_2_HIT") or target_status == "T2":
            m_type = "TARGET_2"
        elif stage_str in ("T1_ACHIEVED", "TARGET_1", "TARGET_1_HIT") or target_status == "T1":
            m_type = "TARGET_1"
        elif (
            stage_str in ("T0_5_ACHIEVED", "TARGET_0_5", "TARGET_0_5_HIT", "SCALE_1_ACHIEVED", "DE_RISK_0_5R", "T0.5_ACHIEVED")
            or target_status in ("T0_5", "T0.5")
            or "TARGET 0.5" in str(getattr(alert, "headline", "") or "").upper()
            or "T0.5" in str(getattr(alert, "headline", "") or "").upper()
        ):
            m_type = "TARGET_0_5"
        elif stage_str == "BREAKEVEN_LOCKED":
            m_type = "BREAKEVEN_LOCKED"
        elif stage_str in ("TRAILING_UPDATE", "TRAIL_RATCHET", "TRAIL_POST_SWEEP", "COMPRESS_STALL_RISK"):
            m_type = "TRAIL_RATCHET"

        # Physical reach validation guard for TARGET_1 and TARGET_2
        if m_type in ("TARGET_1", "TARGET_2"):
            cur_p = float(getattr(alert, "ltp", 0.0) or getattr(alert, "current_ltp", 0.0) or 0.0)
            entry_p = getattr(alert, "entry_price", None) or getattr(alert, "initial_entry_premium", None)
            act_p = getattr(alert, "actionable_plan", {}) or {}
            if not entry_p and isinstance(act_p, dict):
                rec_e = act_p.get("recommended_entry")
                if rec_e:
                    m_e = re.search(r"[\d,]+(?:\.\d+)?", str(rec_e))
                    if m_e:
                        entry_p = float(m_e.group(0).replace(",", ""))
            if entry_p:
                try:
                    entry_p = float(entry_p)
                except (ValueError, TypeError):
                    entry_p = None

            # Determine downward target payoff accurately
            alert_type_raw = str(getattr(alert, "alert_type", "") or "").upper()
            act_str = str((getattr(alert, "actionable_plan", {}) or {}).get("action", "")).upper()
            is_opt = bool(
                getattr(alert, "option_type", None)
                or getattr(alert, "strike", None)
                or "PE" in str(getattr(alert, "contract_symbol", "") or "")
                or "CE" in str(getattr(alert, "contract_symbol", "") or "")
                or alert_type_raw in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "INDEX_CALL_SETUP", "INDEX_PUT_SETUP")
            )
            if is_opt:
                is_option_seller = (
                    any(k in act_str for k in ("SELL", "WRITE", "SHORT"))
                    or alert_type_raw == "OPTION_WRITE"
                    or str(getattr(alert, "option_write", False)).lower() in ("true", "1")
                )
                is_downward = is_option_seller
            else:
                if entry_p and entry_p > 0 and getattr(alert, "target_1", None):
                    t1_cand = None
                    try:
                        t1_cand = float(alert.target_1)
                    except Exception:
                        pass
                    if t1_cand:
                        is_downward = t1_cand < entry_p
                    else:
                        is_downward = str(getattr(alert, "direction", "BULLISH")).upper() in ("BEARISH", "SHORT", "SELL")
                else:
                    is_downward = str(getattr(alert, "direction", "BULLISH")).upper() in ("BEARISH", "SHORT", "SELL")

            if m_type == "TARGET_1":
                t1_raw = (
                    getattr(alert, "target_1", None)
                    or (act_p.get("target_1") if isinstance(act_p, dict) else None)
                    or getattr(alert, "target_level", None)
                )
                t1_num = None
                if t1_raw:
                    m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(t1_raw))
                    if m_t1:
                        try:
                            t1_num = float(m_t1.group(0).replace(",", ""))
                        except ValueError:
                            pass
                if not t1_num and entry_p and getattr(alert, "stop_loss", None):
                    try:
                        sl_val = float(alert.stop_loss)
                        r_val = abs(entry_p - sl_val)
                        if r_val > 0:
                            t1_num = round(entry_p + (r_val * 2.0) if not is_downward else entry_p - (r_val * 2.0), 2)
                    except Exception:
                        pass

                has_hit_t1 = (
                    t1_num is not None
                    and t1_num > 0
                    and cur_p > 0
                    and (
                        (not is_downward and cur_p >= t1_num * 0.998)
                        or (is_downward and cur_p <= t1_num * 1.002)
                    )
                )

                if not has_hit_t1:
                    logger.warning(
                        f"[FreeIndexTemplates] Defensively vetoed false TARGET_1 in render_free_index_alert for {symbol}: "
                        f"LTP={cur_p} vs T1={t1_num} (downward={is_downward})."
                    )
                    m_type = "TARGET_0_5"

            elif m_type == "TARGET_2":
                t2_raw = getattr(alert, "target_2", None) or (act_p.get("target_2") if isinstance(act_p, dict) else None)
                t2_num = None
                if t2_raw:
                    m_t2 = re.search(r"[\d,]+(?:\.\d+)?", str(t2_raw))
                    if m_t2:
                        try:
                            t2_num = float(m_t2.group(0).replace(",", ""))
                        except ValueError:
                            pass
                has_hit_t2 = (
                    t2_num is not None
                    and t2_num > 0
                    and cur_p > 0
                    and (
                        (not is_downward and cur_p >= t2_num * 0.998)
                        or (is_downward and cur_p <= t2_num * 1.002)
                    )
                )
                if not has_hit_t2:
                    logger.warning(
                        f"[FreeIndexTemplates] Defensively vetoed false TARGET_2 in render_free_index_alert for {symbol}: "
                        f"LTP={cur_p} vs T2={t2_num} (downward={is_downward})."
                    )
                    t1_raw = getattr(alert, "target_1", None) or (act_p.get("target_1") if isinstance(act_p, dict) else None)
                    t1_num = None
                    if t1_raw:
                        m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(t1_raw))
                        if m_t1:
                            try:
                                t1_num = float(m_t1.group(0).replace(",", ""))
                            except ValueError:
                                pass
                    has_hit_t1 = (
                        t1_num is not None
                        and t1_num > 0
                        and cur_p > 0
                        and (
                            (not is_downward and cur_p >= t1_num * 0.998)
                            or (is_downward and cur_p <= t1_num * 1.002)
                        )
                    )
                    if has_hit_t1:
                        m_type = "TARGET_1"
                    else:
                        m_type = "TARGET_0_5"

        data = MilestoneAlertData.from_alert(alert, m_type, in_market=in_market)
        return render_free_index_milestone(data, in_market=in_market)

    # 2. Build Crisp New Call Message
    env_tag = normalize_env_tag(getattr(alert, "environment", "LIVE"), in_market)
    symbol = getattr(alert, "symbol", "INDEX").upper()
    direction = (getattr(alert, "direction", "BULLISH") or "BULLISH").upper()
    is_bear = direction in ("BEARISH", "SHORT", "SELL")

    actionable_plan = getattr(alert, "actionable_plan", {}) or {}
    option_type = (getattr(alert, "option_type", "") or actionable_plan.get("option_type", "") or "").upper()
    raw_contract = (
        getattr(alert, "contract_symbol", "")
        or actionable_plan.get("contract", "")
        or ""
    )

    # Strict CE/PE determination
    if option_type == "PE" or raw_contract.endswith("PE") or is_bear:
        is_put = True
        opt_type_str = "PE"
        icon = "🔴"
        setup_label = "INDEX PUT SETUP"
    else:
        is_put = False
        opt_type_str = "CE"
        icon = "🟢"
        setup_label = "INDEX CALL SETUP"

    # Contract Display
    strike_val = getattr(alert, "strike", None) or actionable_plan.get("strike")
    if raw_contract:
        display_contract = format_contract_display(raw_contract)
    elif strike_val:
        display_contract = f"{symbol} {int(strike_val)} {opt_type_str}"
    else:
        display_contract = f"{symbol} {opt_type_str}"

    # Price levels
    spot_p = float(getattr(alert, "underlying_spot", 0.0) or getattr(alert, "ltp", 0.0) or 0.0)
    opt_cmp = getattr(alert, "option_premium", None)
    entry_range = (
        actionable_plan.get("recommended_entry")
        or actionable_plan.get("entry_range")
        or (f"₹{opt_cmp:.1f}" if opt_cmp else f"₹{alert.ltp:.1f}")
    )
    sl_val = actionable_plan.get("stop_loss") or f"₹{getattr(alert, 'stop_loss', 0):.1f}"
    t1_val = (
        actionable_plan.get("target_1")
        or actionable_plan.get("target")
        or f"₹{getattr(alert, 'target_level', 0):.1f}"
    )
    t2_val = actionable_plan.get("target_2", "")

    # Rescue spot leakage from option_plan if needed
    opt_p = actionable_plan.get("option_plan") or {}
    if isinstance(opt_p, dict):
        prem_e = opt_p.get("entry_premium")
        if prem_e and float(prem_e) > 0:
            entry_range = f"₹{float(prem_e):,.2f}"
        sl_prem = opt_p.get("sl_premium") or opt_p.get("stop_loss")
        if sl_prem and float(sl_prem) > 0:
            sl_val = f"₹{float(sl_prem):,.1f}"
        t1_prem = opt_p.get("t1_premium") or opt_p.get("target_1")
        if t1_prem and float(t1_prem) > 0:
            t1_val = f"₹{float(t1_prem):,.1f}"
        t2_prem = opt_p.get("t2_premium") or opt_p.get("target_2")
        if t2_prem and float(t2_prem) > 0:
            t2_val = f"₹{float(t2_prem):,.1f}"

    # Strict Monotonic Target Resolution (Enforces T1 < T2)
    entry_val_num = None
    m_e = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)", str(entry_range))
    if m_e:
        try:
            entry_val_num = float(m_e.group(1).replace(",", ""))
        except Exception:
            pass

    t1_disp, t2_disp, _ = _resolve_monotonic_display_targets(
        actionable_plan=actionable_plan,
        alert=alert,
        entry_val=entry_val_num,
        is_short=False,
        currency_symbol="₹",
    )
    if t1_disp:
        t1_val = t1_disp
    if t2_disp:
        t2_val = t2_disp

    # Risk-to-Reward and Lot Size
    rr_val = actionable_plan.get("risk_reward", "1:2.5")
    lot_sz = getattr(alert, "lot_size", None) or actionable_plan.get("lot_size")
    if not lot_sz:
        try:
            from engine.position_sizer import get_lot_size
            lot_sz = get_lot_size(symbol)
        except Exception:
            lot_sz = None
    lot_str = f" | Lot: <b>{lot_sz}</b>" if lot_sz else ""

    # No Chase Boundary
    no_chase_val = getattr(alert, "no_chase_boundary", None) or actionable_plan.get("no_chase_boundary")
    no_chase_str = ""
    if no_chase_val and float(no_chase_val) > 0:
        no_chase_str = f" | 🛑 No-Chase: > ₹{float(no_chase_val):,.1f}"

    # Targets line
    targets_line = f"• <b>T1:</b> <code>{t1_val}</code>"
    if t2_val and t2_val != t1_val:
        targets_line += f" | <b>T2:</b> <code>{t2_val}</code>"

    # Spot & Opt CMP info
    price_info_parts = []
    if opt_cmp and float(opt_cmp) > 0:
        price_info_parts.append(f"CMP: <b>₹{opt_cmp:,.2f}</b>")
    if spot_p > 0:
        price_info_parts.append(f"Spot: <b>₹{spot_p:,.2f}</b>")
    price_meta = f" ({' | '.join(price_info_parts)})" if price_info_parts else ""

    # Confluence (clean, short 1-line)
    confluence = (
        actionable_plan.get("setup_confluence")
        or getattr(alert, "summary", "")
        or "Institutional order flow buildup with VWAP support and momentum expansion."
    )
    confluence = re.sub(r"^(?:T-0\s+)?Explosive\s+(?:Up|Down)side\s+Mover:\s*", "", confluence, flags=re.IGNORECASE)
    confluence = re.sub(r"^(?:Intraday\s+)?(?:Momentum|Breakdown)\s+Spark:\s*", "", confluence, flags=re.IGNORECASE)
    confluence = re.sub(r"\s*\|\s*OTE:.*$", "", confluence)
    confluence = confluence.strip().rstrip(" .|")

    # Reference and Timestamp
    now_ts_str = (
        getattr(alert, "triggered_at", None)
        or getattr(alert, "created_at", "")
        or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )
    sig_ref = getattr(alert, "signal_ref", None) or build_signal_ref(
        symbol=symbol,
        alert_id=str(getattr(alert, "alert_id", getattr(alert, "id", ""))),
        contract=str(raw_contract or display_contract),
        created_at=now_ts_str,
    )

    alert_tag = "OPTIONS MOMENTUM" if is_put else "BREAKOUT IGNITED"
    if getattr(alert, "alert_type", "") in ("GAMMA_BLAST", "OPTIONS_MOMENTUM"):
        alert_tag = "GAMMA BLAST"

    lines = [
        f"{icon} <b>{env_tag} NEW CALL · {setup_label} · {alert_tag}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>{display_contract}</b>{price_meta}",
        f"• <b>Entry:</b> <code>{entry_range}</code>",
        f"• <b>SL:</b> <code>{sl_val}</code>",
        targets_line,
        f"• <b>R:R:</b> <b>{rr_val}</b>{lot_str}{no_chase_str}",
        f"• <b>Bias:</b> <i>{confluence}</i>",
        f"\n{SEBI_COMPACT_DISCLAIMER}",
        f"{COMMUNITY_CTA_BLOCK}",
        f"🏷️ <code>{sig_ref}</code>",
    ]


    return "\n".join(lines)

