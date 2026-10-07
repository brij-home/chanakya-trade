"""
engine/free_index_router.py
───────────────────────────
Dedicated router for the "Nifty BankNifty Free Signals" Telegram channel (Chat ID: -1004298387260).

Architecture & Invariants:
1. Strict Boundary: Only whitelisted Index setups (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX)
   route to the Free Channel. Stock F&O, commodities, currency, and crypto are strictly excluded.
2. Full SEBI Compliance: Every message is rendered using bot.free_index_templates,
   incorporating mandatory SEBI derivatives risk disclosure and educational safe harbors.
3. Thread Partitioning: Replies and milestones in the Free Channel thread under the initial call
   specifically in that channel, maintaining clean discussions.
4. Independent Anti-Flood & Pacing: Maintains dedicated cooldown and deduplication state
   so free channel subscribers receive clean, non-spammy alerts without impacting other groups.
5. Zero Shadow Dispatches (Invariant 19): All dispatches are routed through centralized
   _telegram_notify and recorded in the alert's audit_trail.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable, Optional

from bot.free_index_templates import (
    DEFAULT_FREE_INDEX_CHAT_ID,
    FREE_INDEX_CHANNEL_NAME,
    FREE_INDEX_CHANNEL_LINK,
    render_free_index_alert,
)

logger = logging.getLogger("engine.free_index_router")


class FreeIndexRouter:
    """
    Dedicated routing controller for the Free Index Signals Telegram channel.
    Manages channel gating, formatting, threading, and rate-limiting.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dispatched_free_milestones: set[str] = set()
        self._dispatch_cooldowns: dict[str, float] = {}

    def get_chat_id(self) -> Optional[str]:
        """
        Retrieves the target Telegram chat ID for the Free Index Channel.
        Honors environment variable TELEGRAM_FREE_INDEX_CHAT_ID,
        alert preferences, or default '-1004298387260'.
        """
        env_id = os.environ.get("TELEGRAM_FREE_INDEX_CHAT_ID", "").strip()
        if env_id:
            return env_id
        try:
            from engine.alert_preferences import alert_preferences

            pref_id = alert_preferences.get_free_index_chat_id()
            if pref_id:
                return pref_id
        except Exception:
            pass

        # In live production runtime, default to the canonical Free Index Channel ID.
        # In test environments (CHANAKYA_TESTING=1), return None unless explicitly set.
        if os.environ.get("CHANAKYA_TESTING") != "1":
            return DEFAULT_FREE_INDEX_CHAT_ID
        return None

    def is_enabled(self) -> bool:
        """Checks if Free Index Channel routing is active."""
        env_flag = os.environ.get("TELEGRAM_FREE_INDEX_ENABLED", "").strip().lower()
        if env_flag in ("0", "false", "no"):
            return False
        if env_flag in ("1", "true", "yes"):
            return True
        try:
            from engine.alert_preferences import alert_preferences

            return alert_preferences.is_free_index_enabled()
        except Exception:
            return True

    def is_candidate(self, alert: Any) -> bool:
        """
        Validates if an alert is eligible for the Free Index Channel:
        - Must be an Index call (NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX).
        - Must NOT be a disallowed index (FINNIFTY, BANKEX, etc.).
        - Must NOT be an equity stock, commodity, currency, or crypto.
        - Must meet minimum confidence threshold.
        """
        if not self.is_enabled():
            return False

        chat_id = self.get_chat_id()
        if not chat_id:
            return False

        # Segment check
        try:
            from engine.alert_preferences import classify_alert_segment, is_fno_index_channel_allowed

            seg = getattr(alert, "segment", None) or classify_alert_segment(alert)
            if seg not in ("FNO_INDEX", "INDEX_FNO", "FNO_INDICES"):
                return False

            symbol = getattr(alert, "symbol", "") or ""
            # Whitelist check: strictly Nifty, BankNifty, Midcp, Sensex
            if not is_fno_index_channel_allowed(symbol):
                return False

            # Explicit check to block FINNIFTY, BANKEX, etc.
            clean_sym = re.sub(r"[^A-Za-z0-9]", "", symbol).upper()
            if any(b in clean_sym for b in ("FINNIFTY", "BANKEX", "NIFTYNXT50", "CNXIT", "NIFTYIT")):
                return False

            # Confidence threshold check
            conf = getattr(alert, "confidence", 0) or 0
            if conf and conf < 75:
                return False

            # ── Intraday & Scalping Strict Guardrails ──
            # Free Index Channel (t.me/IndiaIndexSignals) is strictly for Intraday & Scalping setups.
            # Multi-session/positional setups and wide stops (>28 pts on Nifty opt, >45 pts on spot)
            # are strictly prohibited to prevent insane unrealistic levels from leaking to subscribers.
            timeframe = (
                getattr(alert, "time_horizon", "")
                or getattr(alert, "timeframe", "")
                or ""
            )
            is_pos = getattr(alert, "is_positional", False)
            setup_tp = (
                getattr(alert, "setup_type", "")
                or getattr(alert, "alert_type", "")
                or (getattr(alert, "actionable_plan", {}) or {}).get("action", "")
            )
            if (
                is_pos
                or str(timeframe).upper() in ("POSITIONAL", "SWING", "SWING_MID", "SWING_SHORT", "DAILY", "WEEKLY", "MULTIBAGGER")
                or "200EMA" in str(setup_tp).upper()
                or "RUBBER_BAND" in str(setup_tp).upper()
            ):
                logger.debug(
                    f"[FreeIndexRouter] Suppressed positional/swing setup for {symbol}: "
                    f"setup_type={setup_tp}, timeframe={timeframe}"
                )
                return False

            # Intraday Stop Loss Sanity Ceilings (Max allowed risk points)
            max_opt_sl_pts = {
                "NIFTY": 35.0,
                "BANKNIFTY": 75.0,
                "MIDCPNIFTY": 20.0,
                "SENSEX": 110.0,
            }.get(clean_sym, 40.0)

            max_spot_sl_pts = {
                "NIFTY": 55.0,
                "BANKNIFTY": 140.0,
                "MIDCPNIFTY": 35.0,
                "SENSEX": 200.0,
            }.get(clean_sym, 60.0)

            plan = getattr(alert, "actionable_plan", {}) or {}
            opt_p = plan.get("option_plan") or {}
            is_opt = bool(
                getattr(alert, "option_type", None)
                or getattr(alert, "contract_symbol", None)
                or opt_p.get("contract_symbol")
                or plan.get("contract")
            )

            # 1. Option Stop Loss distance check
            prem_e = (
                opt_p.get("entry_premium")
                or getattr(alert, "option_premium", None)
                or (getattr(alert, "trigger_level", None) if is_opt else None)
            )
            prem_sl = (
                opt_p.get("sl_premium")
                or opt_p.get("stop_loss")
                or (getattr(alert, "stop_loss", None) if is_opt else None)
            )
            if is_opt and prem_e is not None and prem_sl is not None:
                try:
                    p_e = float(str(prem_e).replace("₹", "").replace(",", "").strip())
                    p_sl = float(str(prem_sl).replace("₹", "").replace(",", "").strip())
                    if p_e > 0 and p_sl > 0:
                        opt_risk = abs(p_e - p_sl)
                        if opt_risk > max_opt_sl_pts:
                            logger.warning(
                                f"[FreeIndexRouter] Suppressed {getattr(alert, 'alert_id', '')} for {symbol}: "
                                f"Option SL distance ({opt_risk:.1f} pts) exceeds intraday ceiling ({max_opt_sl_pts:.1f} pts)"
                            )
                            return False
                except (ValueError, TypeError):
                    pass

            # 2. Spot Stop Loss distance check
            spot_p = float(getattr(alert, "underlying_spot", 0.0) or getattr(alert, "ltp", 0.0) or 0.0)
            spot_sl_val = (
                plan.get("spot_stop_loss")
                or plan.get("underlying_sl")
                or (getattr(alert, "stop_loss", None) if not is_opt else None)
            )
            if spot_p > 0 and spot_sl_val is not None:
                try:
                    s_sl = float(str(spot_sl_val).replace("₹", "").replace(",", "").strip())
                    if s_sl > 0:
                        spot_risk = abs(spot_p - s_sl)
                        if spot_risk > max_spot_sl_pts:
                            logger.warning(
                                f"[FreeIndexRouter] Suppressed {getattr(alert, 'alert_id', '')} for {symbol}: "
                                f"Spot SL distance ({spot_risk:.1f} pts) exceeds intraday ceiling ({max_spot_sl_pts:.1f} pts)"
                            )
                            return False
                except (ValueError, TypeError):
                    pass

            return True
        except Exception as e:
            logger.warning(f"[FreeIndexRouter] Candidate validation failed for {getattr(alert, 'symbol', '')}: {e}")
            return False

    def dispatch(
        self,
        alert: Any,
        in_market: bool = True,
        is_milestone: bool = False,
        sig_id: Optional[str] = None,
        disable_notification: Optional[bool] = None,
    ) -> bool:
        """
        Formats and dispatches the alert to the Free Index Channel with thread linkage.
        """
        chat_id = self.get_chat_id()
        if not chat_id:
            return False

        aid = str(getattr(alert, "alert_id", "") or getattr(alert, "id", "") or "")
        symbol = str(getattr(alert, "symbol", "") or "")
        stage = str(getattr(alert, "stage", "") or "")
        c_tag = str(getattr(alert, "contract_symbol", "") or symbol)

        # Anti-flood & deduplication for the Free Channel
        now_ts = time.time()
        with self._lock:
            # Pacing check for free channel
            pacing_key = f"PACING:{symbol}"
            last_pacing = self._dispatch_cooldowns.get(pacing_key, 0.0)
            if not is_milestone and (now_ts - last_pacing) < 300.0:  # 5 min cooldown per symbol for free channel
                logger.debug(f"[FreeIndexRouter] Suppressed free channel pacing for {symbol}")
                return False

            # Milestone dedup and zero ghost lifecycle check (Invariant 19)
            if is_milestone:
                dispatched_ch = getattr(alert, "dispatched_channels", []) or []
                if "free_telegram" not in dispatched_ch:
                    logger.debug(
                        f"[FreeIndexRouter] Suppressed milestone {stage} for {aid}: "
                        f"Original setup was never dispatched to Free Channel."
                    )
                    return False
                m_key = f"FREE:{aid}:{stage}"
                if m_key in self._dispatched_free_milestones:
                    return False
                self._dispatched_free_milestones.add(m_key)
            else:
                self._dispatch_cooldowns[pacing_key] = now_ts

        # Render message using dedicated Free Index Template
        try:
            free_msg = render_free_index_alert(alert, in_market=in_market)
        except Exception as e:
            logger.error(f"[FreeIndexRouter] Failed to render free index message for {symbol}: {e}", exc_info=True)
            return False

        # Resolve threading reply-to message ID in the Free Channel
        reply_to_message_id = None
        if is_milestone:
            try:
                from bot.telegram_bot import get_signal_message_id

                reply_to_message_id = get_signal_message_id(
                    sig_id,
                    chat_id=chat_id,
                    alert_id=aid,
                )
            except Exception as e:
                logger.debug(f"[FreeIndexRouter] Could not resolve reply_to for {sig_id}: {e}")

        # Callback on successful Telegram dispatch to record thread message ID in Free Channel
        def _on_free_tg_sent(msg_id: int) -> None:
            try:
                from bot.telegram_bot import record_signal_message_id

                record_signal_message_id(
                    sig_id,
                    int(msg_id),
                    chat_id=chat_id,
                    alert_id=aid,
                )
                logger.info(
                    f"[FreeIndexRouter] Recorded Free Channel thread root msg_id={msg_id} "
                    f"for {sig_id} in {chat_id}"
                )
            except Exception as e:
                logger.warning(f"[FreeIndexRouter] Failed to record free channel msg_id: {e}")

        # Dispatch via centralized _telegram_notify
        try:
            from engine.alerts import _telegram_notify

            _telegram_notify(
                free_msg,
                chat_id=chat_id,
                signal_id=sig_id,
                disable_notification=disable_notification,
                reply_to_message_id=reply_to_message_id,
                on_success=_on_free_tg_sent,
                alert_id=aid,
                is_update=is_milestone,
            )

            # Record audit trail
            if hasattr(alert, "record_audit"):
                alert.record_audit(
                    "FREE_INDEX_TELEGRAM_SENT",
                    f"Dispatched SEBI-compliant signal to Free Index Channel ({chat_id})",
                    actor="FREE_INDEX_ROUTER",
                    details={"chat_id": chat_id, "confidence": getattr(alert, "confidence", 0), "stage": stage},
                )
            if hasattr(alert, "dispatched_channels") and isinstance(alert.dispatched_channels, list):
                if "free_telegram" not in alert.dispatched_channels:
                    alert.dispatched_channels.append("free_telegram")

            logger.info(
                f"[FreeIndexRouter] Dispatched SEBI-compliant setup for {symbol} ({aid}) "
                f"to Free Channel {chat_id}"
            )
            return True
        except Exception as e:
            logger.error(f"[FreeIndexRouter] Dispatch failed for {symbol} ({aid}): {e}", exc_info=True)
            return False


# Global singleton instance
free_index_router = FreeIndexRouter()
