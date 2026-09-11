"""
engine/auto_alert_engine.py
───────────────────────────
Real-Time Autonomous Market Alert Engine with Early-Warning Detection.

Monitors live quotes, options chains, and price structures to deliver
actionable alerts *on or before time* so traders can catch high-asymmetry
movements early rather than chasing extended breakouts.

Key Early-Warning Detectors:
  1. GAMMA_BLAST: Options Expiry Day OI unwinding (negative ΔOI) + Volume/OI
     turnover surge (>= 1.8x) + Spot reclaiming intraday VWAP.
     Detects both "EARLY_WARNING" (coiling) and "IGNITED" (active breakout).
  2. SQUEEZE_BREAKOUT: TTM Squeeze (Bollinger inside Keltner) with price coiled
     within 0.4% - 1.2% of VCP pivot / 20-day high with expanding RVOL.
  3. CIRCUIT_WARNING: Upper Circuit proximity alert (<1.5% below circuit ceiling)
     warning traders before liquidity locks and sellers vanish.
  4. SMC_SWEEP: Previous Day High/Low liquidity sweep with immediate wick rejection
     and Lower Timeframe CHoCH at institutional Order Blocks.
  5. CONFLUENCE_INFLECTION: Top-tier quantitative confluence triggers (Score >= 80).

Multi-Channel Dispatch:
  - Server-Sent Events (SSE) via `web.sse.event_bus` -> React Terminal UI
  - In-memory queryable circular buffer
  - Desktop notifications & optional Telegram push
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("engine.auto_alert_engine")

IST = timezone(timedelta(hours=5, minutes=30))


def get_auto_alerts_file() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    return base / "auto_alerts.json"


AUTO_ALERTS_FILE = get_auto_alerts_file()


# ── Modular Subsystems & Re-exports ─────────────────────────────────────────

from engine.alert_model import INDEX_WEEKLY_EXPIRY_WEEKDAY, AutoAlert
from engine.alert_expiry import (
    classify_expiry_type,
    get_expiry_metadata,
    get_next_expiry_opportunity,
    is_alert_option_premium_level,
)
from engine.alert_evaluator import (
    TargetTrailingEvaluation,
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
)
from engine.detectors import (
    detect_gamma_blast,
    detect_squeeze_breakout,
    detect_circuit_proximity,
    detect_learned_pattern_coiling,
)



def get_current_ist_session(ref_dt: Optional[datetime] = None) -> dict[str, bool]:
    """
    Evaluates current IST operational session status per institutional schedule & user discipline:
      - 'equity_nfo': Mon-Fri 09:15 - 15:30 IST (Prime domestic equities & NFO derivatives).
      - 'currency':   Mon-Fri 15:30 - 17:00 IST (Strictly post-equity, active until CDS close).
                      Also active 09:00 - 09:15 IST (Pre-equity opening window).
      - 'commodity':  Mon-Fri 15:30 - 23:30 IST (Strictly post-equity, active through US overlap).
    All markets are dormant on weekends and outside operational hours.
    """
    now = ref_dt or datetime.now(IST)
    if now.weekday() >= 5:  # Saturday/Sunday closed
        return {"equity_nfo": False, "currency": False, "commodity": False}

    current_t = now.time()

    # 09:15 to 15:30 IST: Pure Domestic Equity & NFO Desk (Zero clutter from other assets)
    is_equity_nfo = dtime(9, 15) <= current_t <= dtime(15, 30)

    # Post-Equity Session: Currency (15:30 - 17:00 IST) and Commodities (15:30 - 23:30 IST)
    # Currency is also valid 09:00 - 09:15 IST before domestic equity opens
    is_currency = (dtime(9, 0) <= current_t < dtime(9, 15)) or (
        dtime(15, 30) < current_t <= dtime(17, 0)
    )
    is_commodity = dtime(15, 30) < current_t <= dtime(23, 30)

    return {
        "equity_nfo": is_equity_nfo,
        "currency": is_currency,
        "commodity": is_commodity,
    }


# ── Auto Alert Engine Core Class ───────────────────────────────────────────


class AutoAlertEngine:
    """
    Autonomous background monitoring and dispatch engine.
    Continuously evaluates watched indices and liquid universe for early-warning signals.
    """

    def __init__(self, max_buffer: int = 150) -> None:
        self._lock = threading.RLock()
        self._max_buffer = max_buffer
        self._alerts: list[AutoAlert] = []
        self._cooldowns: dict[str, float] = {}  # signature -> timestamp
        self._cooldown_ttl = 900.0  # 15 minutes anti-spam per signature
        self._dispatched_milestones: set[str] = set()
        self._dispatch_cooldowns: dict[str, float] = {}
        self._stop_event = threading.Event()
        self._poller_thread: Optional[threading.Thread] = None
        self._is_running = False

        # Watched indices & top liquid universe
        self._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
        self._watched_equities = [
            "RELIANCE",
            "TCS",
            "INFY",
            "HDFCBANK",
            "ICICIBANK",
            "MARUTI",
            "SBIN",
            "BHARTIARTL",
            "LT",
            "ITC",
        ]
        # Watched commodities & currency universe for post-equity sessions
        self._watched_commodities = [
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "COPPER",
        ]
        self._watched_currencies = [
            "USDINR",
            "EURINR",
            "GBPINR",
        ]
        self._load()
        self.cleanup_corrupted_test_alerts()

    @property
    def watched_commodities(self) -> list[str]:
        """Returns liquid MCX commodity symbols for evening monitoring."""
        return list(self._watched_commodities)

    @property
    def watched_currencies(self) -> list[str]:
        """Returns liquid Currency CDS pairs for post-equity monitoring."""
        return list(self._watched_currencies)

    @property
    def watched_equities(self) -> list[str]:
        """
        Dynamically returns the comprehensive high-liquidity universe to monitor.
        Combines:
          1. Default core bluechips (RELIANCE, TCS, INFY, etc.)
          2. Highest turnover institutional leaders (most_liquid_today, includes ADANIENT)
          3. Unusual volume surge candidates (volume_surges_rvol)
        """
        symbols = list(self._watched_equities)
        if getattr(self, "_override_watched_equities", False):
            return symbols
        try:
            from analysis.universe import THEMATIC_PRESETS

            most_liquid = THEMATIC_PRESETS.get("most_liquid_today", {}).get("symbols", [])
            vol_surges = THEMATIC_PRESETS.get("volume_surges_rvol", {}).get("symbols", [])
            for s in most_liquid + vol_surges:
                if s not in symbols:
                    symbols.append(s)
        except Exception:
            pass
        return symbols

    @watched_equities.setter
    def watched_equities(self, val: list[str]) -> None:
        self._watched_equities = list(val)
        self._override_watched_equities = True

    # ── Dispatch and Record ─────────────────────────────────────

    def record_alert(self, alert: AutoAlert) -> bool:
        """
        Records alert if not within cooldown window. Dispatches to SSE and multi-channels.
        Strictly prevents duplicate active alerts for the same symbol & alert_type.
        """
        now = time.time()
        to_dispatch = None

        clean_target = (
            alert.symbol.replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .replace("CDS:", "")
            .strip()
            .upper()
        )
        is_sim = (
            (alert.environment == "TEST")
            or (not alert.is_live)
            or alert.alert_id.startswith("test-")
        )

        # 00. Content Sanity Gate: Intercept and repair degenerate / placeholder fields (e.g. 'h', 's')
        raw_hl = (alert.headline or "").strip()
        if not raw_hl or len(raw_hl) <= 3 or raw_hl.lower() in ("h", "test", "dummy"):
            c_tag = f" {int(alert.strike)} {alert.option_type}" if alert.strike and alert.option_type else ""
            alert.headline = f"🎯 [{alert.environment}] {alert.alert_type.replace('_', ' ')}: {clean_target}{c_tag} @ ₹{alert.ltp:,.1f}"

        raw_sm = (alert.summary or "").strip()
        if not raw_sm or len(raw_sm) <= 3 or raw_sm.lower() in ("s", "test", "dummy"):
            scrutiny = (alert.metrics or {}).get("scrutiny", {}) if isinstance(alert.metrics, dict) else {}
            logic_conf = scrutiny.get("logic_confirmation") if isinstance(scrutiny, dict) else None
            if logic_conf and len(str(logic_conf).strip()) > 5:
                alert.summary = str(logic_conf).strip()
            else:
                c_tag = f"{clean_target} {int(alert.strike)} {alert.option_type}" if alert.strike and alert.option_type else clean_target
                alert.summary = f"Institutional momentum surge on {c_tag}. Invalidation anchor: ₹{alert.stop_loss:,.1f}."

        # 0a. Market Session Timing Gate (Opening Range Discovery & Closing Cutoff)
        is_test_runner = (
            is_sim
            or (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if not is_test_runner and alert.stage in ("IGNITED",) and alert.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "SQUEEZE_BREAKOUT"):
            now_t = datetime.now(IST).time()
            # 09:15 - 09:25 IST: Morning Opening Discovery Quiet Window (Mute early opening auction whipsaws)
            if dtime(9, 15) <= now_t < dtime(9, 25):
                logger.info(
                    f"[AutoAlertEngine] 🛑 Suppressed opening auction breakout alert for {clean_target} ({alert.alert_type}): "
                    f"Market Opening Quiet Window (09:15–09:25 IST) active to avoid whipsaws."
                )
                return False

            # Post-15:10 IST: Hard Closing Cutoff for domestic equity/NFO intraday options
            if alert.exchange in ("NSE", "BSE", "NFO", "") and alert.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST") and now_t >= dtime(15, 10):
                logger.info(
                    f"[AutoAlertEngine] 🛑 Suppressed late-session intraday option alert for {clean_target} ({alert.alert_type}): "
                    f"Post-15:10 IST cutoff active (MIS closed, terminal theta decay risk)."
                )
                return False

        # 0. Closed-Loop Invalidation Lockout Guard (Negative Feedback Loop)
        if not is_sim:

            underlying_sym = (
                (alert.metrics or {}).get("underlying") if isinstance(alert.metrics, dict) else None
            )
            if not underlying_sym:
                try:
                    from market.quotes import _OPTION_PATTERN

                    m = _OPTION_PATTERN.match(clean_target)
                    underlying_sym = m.group(1) if m else clean_target
                except Exception:
                    underlying_sym = clean_target

            try:
                from engine.learning_engine import pattern_learning_engine

                for candidate_sym in set([clean_target, underlying_sym, alert.symbol]):
                    if not candidate_sym:
                        continue
                    is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
                        candidate_sym, direction=alert.direction, ltp=alert.ltp
                    )
                    if is_locked:
                        logger.info(
                            f"[AutoAlertEngine] 🛑 Suppressed alert insertion for locked-out {candidate_sym} ({alert.alert_type}): {lock_reason}"
                        )
                        return False
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Lockout check exception: {e}")

        # 1. Structural Pre-Checks & Deduplication (Inside Lock)
        with self._lock:
            # Check for existing alert with identical ID
            if any(a.alert_id == alert.alert_id for a in self._alerts):
                return False

            def _alert_date(al: AutoAlert) -> Optional[datetime.date]:
                ts = (al.created_at or al.triggered_at or "").replace(" IST", "").strip()[:10]
                if ts:
                    try:
                        return datetime.strptime(ts, "%Y-%m-%d").date()
                    except ValueError:
                        pass
                return None

            alert_dt_date = _alert_date(alert) or datetime.now(IST).date()

            # 1a. Check for existing active (in-flight) alert on the same symbol and strategy
            existing_active = next(
                (
                    a
                    for a in self._alerts
                    if a.symbol.replace("NSE:", "")
                    .replace("BSE:", "")
                    .replace("MCX:", "")
                    .replace("NFO:", "")
                    .strip()
                    .upper()
                    == clean_target
                    and a.alert_type == alert.alert_type
                    and (
                        (a.contract_symbol or "") == (alert.contract_symbol or "")
                        or (
                            (a.strike or 0) == (alert.strike or 0)
                            and (a.option_type or "") == (alert.option_type or "")
                        )
                    )
                    and not a.is_invalidated
                    and a.stage not in ("INVALIDATED", "COMPLETED", "EXPIRED")
                ),
                None,
            )
            if existing_active:
                ex_date = _alert_date(existing_active)
                # If existing alert is from a prior calendar session, retire it and treat incoming as fresh!
                if ex_date and ex_date < alert_dt_date:
                    existing_active.stage = "EXPIRED"
                    existing_active.is_archived = True
                    existing_active.archive_reason = "Prior session record retired"
                    existing_active = None

            if existing_active:
                # If existing is EARLY_WARNING and incoming is IGNITED, upgrade it!
                if existing_active.stage == "EARLY_WARNING" and alert.stage == "IGNITED":
                    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                    # Preserve original call time BEFORE overwriting created_at (prevents '0s ago' bug)
                    if not existing_active.original_call_time:
                        existing_active.original_call_time = existing_active.created_at
                    existing_active.stage = "IGNITED"
                    existing_active.triggered_at = now_iso
                    existing_active.created_at = now_iso  # Synchronize to exact ignition moment!
                    existing_active.timestamp = now_iso
                    existing_active.headline = alert.headline
                    existing_active.summary = alert.summary
                    existing_active.ltp = alert.ltp
                    existing_active.trigger_level = alert.trigger_level
                    existing_active.target_level = alert.target_level
                    existing_active.stop_loss = alert.stop_loss
                    existing_active.option_premium = alert.option_premium or alert.ltp
                    existing_active.underlying_spot = alert.underlying_spot
                    existing_active.metrics = alert.metrics
                    existing_active.actionable_plan = alert.actionable_plan
                    existing_active.confidence = max(existing_active.confidence, alert.confidence)
                    existing_active.signal_ref = None  # Force fresh signal ref with today's date & time
                    existing_active.achieved_milestones = []
                    existing_active.target_status = "PENDING"
                    existing_active.trailing_stop = None
                    self._save()
                    to_dispatch = existing_active
                else:
                    # Existing alert is already active/ignited/tracking targets -> suppress duplicate insertion!
                    return False
            else:
                # 1b. Symbol-Level Options Momentum Consolidation:
                # Prevent firing multiple separate strike cards for the same stock within the same session
                if alert.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST") and not is_sim:
                    existing_opt = next(
                        (
                            a
                            for a in self._alerts
                            if a.symbol.replace("NSE:", "")
                            .replace("BSE:", "")
                            .replace("MCX:", "")
                            .replace("NFO:", "")
                            .strip()
                            .upper()
                            == clean_target
                            and a.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                            and a.direction == alert.direction
                            and not a.is_invalidated
                            and a.stage not in ("INVALIDATED", "COMPLETED", "EXPIRED")
                            and (_alert_date(a) is None or _alert_date(a) == alert_dt_date)
                        ),
                        None,
                    )
                    if existing_opt:
                        if not isinstance(existing_opt.metrics, dict):
                            existing_opt.metrics = {}
                        rel_strikes = existing_opt.metrics.setdefault("related_strikes", [])
                        c_tag = alert.contract_symbol or f"{alert.strike}{alert.option_type}"
                        if c_tag not in rel_strikes:
                            rel_strikes.append(c_tag)

                        # Trade Immutability Invariant:
                        # If existing_opt is already IGNITED or tracking live milestones (stage != EARLY_WARNING)
                        # or has achieved milestones / target_status, NEVER mutate its contract symbol, strike, or entry!
                        is_active_trade = (
                            existing_opt.stage not in ("EARLY_WARNING",)
                            or bool(existing_opt.achieved_milestones)
                            or bool(existing_opt.target_status)
                        )
                        if is_active_trade:
                            logger.info(
                                f"[AutoAlertEngine] Active option momentum trade already running for {clean_target} "
                                f"({existing_opt.contract_symbol} stage={existing_opt.stage}). "
                                f"Preserving active trade and suppressing alternate strike {c_tag}."
                            )
                            self._save()
                            return False

                        inc_vol_oi = float((alert.metrics or {}).get("vol_oi_ratio", 0.0) or 0.0)
                        cur_vol_oi = float(
                            (existing_opt.metrics or {}).get("vol_oi_ratio", 0.0) or 0.0
                        )
                        if alert.confidence > existing_opt.confidence or inc_vol_oi > (
                            cur_vol_oi * 1.25
                        ):
                            now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                            existing_opt.contract_symbol = alert.contract_symbol
                            existing_opt.strike = alert.strike
                            existing_opt.option_type = alert.option_type
                            existing_opt.ltp = alert.ltp
                            existing_opt.trigger_level = alert.trigger_level
                            existing_opt.target_level = alert.target_level
                            existing_opt.stop_loss = alert.stop_loss
                            existing_opt.option_premium = alert.option_premium or alert.ltp
                            existing_opt.underlying_spot = alert.underlying_spot
                            existing_opt.headline = alert.headline
                            existing_opt.summary = alert.summary
                            existing_opt.actionable_plan = alert.actionable_plan
                            existing_opt.confidence = max(existing_opt.confidence, alert.confidence)
                            existing_opt.created_at = alert.created_at or now_iso
                            existing_opt.timestamp = alert.created_at or now_iso
                            existing_opt.signal_ref = None
                            existing_opt.achieved_milestones = []
                            existing_opt.target_status = None
                            existing_opt.trailing_stop = None
                            existing_opt.metrics["vol_oi_ratio"] = inc_vol_oi
                            if "strike" in existing_opt.metrics:
                                existing_opt.metrics["strike"] = alert.strike
                            if "spot" in existing_opt.metrics and "spot" in (alert.metrics or {}):
                                existing_opt.metrics["spot"] = alert.metrics["spot"]
                        self._save()
                        return False

                # 1c. Directional Whiplash Guard:
                # Prevent conflicting bull/bear flip-flops on the same stock within the same session
                # unless there is an explicit structural trend reversal (CHoCH / MSS / Break of Structure)
                if not is_sim:
                    existing_opp = next(
                        (
                            a
                            for a in self._alerts
                            if a.symbol.replace("NSE:", "")
                            .replace("BSE:", "")
                            .replace("MCX:", "")
                            .replace("NFO:", "")
                            .strip()
                            .upper()
                            == clean_target
                            and a.is_active
                            and not a.is_invalidated
                            and a.stage not in ("INVALIDATED", "COMPLETED", "EXPIRED")
                            and a.direction != alert.direction
                            and a.direction in ("BULLISH", "BEARISH")
                            and alert.direction in ("BULLISH", "BEARISH")
                            and (_alert_date(a) is None or _alert_date(a) == alert_dt_date)
                        ),
                        None,
                    )
                    if existing_opp:
                        metrics_dict = alert.metrics if isinstance(alert.metrics, dict) else {}
                        summary_str = f"{alert.headline or ''} {alert.summary or ''}"
                        has_reversal = bool(
                            metrics_dict.get("choch")
                            or metrics_dict.get("mss")
                            or re.search(
                                r"\b(choch|mss|change of character|market structure shift|trend reversal|structural reversal)\b",
                                summary_str,
                                re.IGNORECASE,
                            )
                        )
                        if not has_reversal:
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Suppressed conflicting directional whiplash for {clean_target}: "
                                f"Active {existing_opp.direction} alert ({existing_opp.alert_type}) in flight. "
                                f"Incoming {alert.direction} alert ({alert.alert_type}) lacks verified CHoCH reversal."
                            )
                            return False
                        else:
                            logger.info(
                                f"[AutoAlertEngine] ⚡ Structural Reversal (CHoCH) detected on {clean_target}! "
                                f"Superseding older {existing_opp.direction} alert with new {alert.direction} alert."
                            )
                            existing_opp.is_invalidated = True
                            existing_opp.stage = "INVALIDATED"
                            existing_opp.invalidation_reason = f"Superseded by structural {alert.direction} reversal ({alert.alert_type})"
                            self._save()

                # 2. Signature-based cooldown check (differentiating options contracts by symbol/strike)
                c_tag = alert.contract_symbol or (
                    f"{alert.strike}_{alert.option_type}" if alert.strike else ""
                )
                sig = f"{alert.symbol}:{alert.alert_type}:{c_tag}:{alert.direction}:{alert.stage}"
                last_time = self._cooldowns.get(sig, 0.0)
                if (now - last_time) < self._cooldown_ttl:
                    return False  # Cooldown active, suppress repetitive spam

                # 2b. Underlying Directional Cooldown: Prevent redundant same-direction alerts on the same stock
                sym_sig = f"{clean_target}:{alert.direction}"
                if not is_sim and alert.stage in ("IGNITED", "EARLY_WARNING"):
                    last_sym_time = self._cooldowns.get(sym_sig, 0.0)
                    if (now - last_sym_time) < self._cooldown_ttl:
                        has_active_same_dir = any(
                            a.symbol.replace("NSE:", "")
                            .replace("BSE:", "")
                            .replace("MCX:", "")
                            .replace("NFO:", "")
                            .strip()
                            .upper()
                            == clean_target
                            and a.direction == alert.direction
                            and a.is_active
                            and a.alert_id != alert.alert_id
                            and (_alert_date(a) is None or _alert_date(a) == alert_dt_date)
                            for a in self._alerts
                        )
                        if has_active_same_dir:
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Suppressed redundant alert for {clean_target} ({alert.alert_type}): "
                                f"Active {alert.direction} trade already running within {int(self._cooldown_ttl/60)}m window."
                            )
                            return False

                # 2c. Learning Engine Invalidation Lockout Gate:
                # Prevent re-triggering on assets that were stopped out / invalidated in the current session
                if not is_sim:
                    try:
                        from engine.learning_engine import pattern_learning_engine

                        is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
                            clean_target, direction=alert.direction, ltp=alert.ltp
                        )
                        if is_locked:
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Suppressed alert for {clean_target} ({alert.direction}): "
                                f"Negative learning lockout active ({lock_reason})"
                            )
                            return False
                    except Exception as e:
                        logger.debug(f"[AutoAlertEngine] Error checking learning lockout: {e}")

        # 3. Only if alert passed deduplication & cooldown: sanitize actionable plan
        if (
            alert.actionable_plan
            and isinstance(alert.actionable_plan, dict)
            and alert.stop_loss > 0
        ):
            entry_rg = alert.actionable_plan.get("entry_range")
            if entry_rg and isinstance(entry_rg, str):
                nums = re.findall(r"[\d,]+(?:\.\d+)?", entry_rg)
                if len(nums) >= 2:
                    try:
                        lower_val = float(nums[0].replace(",", ""))
                        upper_val = float(nums[1].replace(",", ""))

                        act = str(alert.actionable_plan.get("action", "")).upper()
                        is_opt = is_alert_option_premium_level(alert)
                        is_long = (
                            alert.direction in ("BULLISH", "LONG", "BUY")
                            or "BUY" in act
                            or (is_opt and "SELL" not in act and "WRITE" not in act)
                        )

                        if is_long:
                            # Long position (Long Equity, Long Call CE, or Long Put PE):
                            # Entry Range must be strictly above Stop-Loss (StopLoss < Entry <= Target)
                            if lower_val <= alert.stop_loss or lower_val <= 0:
                                step = (
                                    max(0.5, (alert.ltp - alert.stop_loss) * 0.15)
                                    if alert.ltp > alert.stop_loss
                                    else max(0.5, alert.stop_loss * 0.05)
                                )
                                corr_lower = round(alert.stop_loss + step, 1)
                                corr_upper = max(upper_val, round(corr_lower + max(0.5, step), 1))
                                if alert.ltp > 0:
                                    corr_lower = min(corr_lower, round(alert.ltp * 0.98, 1))
                                    corr_upper = max(corr_lower + 0.1, round(alert.ltp * 1.02, 1))
                                    # Strict target clamping: Long entry range must NEVER exceed or touch Target 1
                                    if alert.target_level > alert.ltp:
                                        max_allowed_upper = round(
                                            alert.ltp + 0.35 * (alert.target_level - alert.ltp), 1
                                        )
                                        corr_upper = min(
                                            corr_upper,
                                            max(corr_lower + 0.1, max_allowed_upper),
                                        )
                                    if corr_lower <= alert.stop_loss:
                                        corr_lower = round(alert.stop_loss + 0.5, 1)
                                        corr_upper = max(corr_lower + 0.5, corr_upper)
                                alert.actionable_plan["entry_range"] = (
                                    f"₹{corr_lower:,.1f} – ₹{corr_upper:,.1f}"
                                )
                        else:
                            # Short position (Cash Equity / Futures Short):
                            # Entry Range must be strictly below Stop-Loss (Target < Entry < StopLoss)
                            if upper_val >= alert.stop_loss or upper_val <= 0:
                                step = (
                                    max(0.5, (alert.stop_loss - alert.ltp) * 0.15)
                                    if alert.stop_loss > alert.ltp
                                    else max(0.5, alert.stop_loss * 0.05)
                                )
                                corr_upper = round(alert.stop_loss - step, 1)
                                corr_lower = min(lower_val, round(corr_upper - max(0.5, step), 1))
                                if corr_lower <= 0:
                                    corr_lower = max(0.5, round(corr_upper * 0.95, 1))
                                if alert.ltp > 0:
                                    corr_upper = max(corr_upper, round(alert.ltp * 1.02, 1))
                                    corr_lower = min(corr_lower, round(alert.ltp * 0.98, 1))
                                    # Strict target clamping: Short entry range must NEVER drop below or touch Target 1
                                    if 0 < alert.target_level < alert.ltp:
                                        min_allowed_lower = round(
                                            alert.ltp - 0.35 * (alert.ltp - alert.target_level), 1
                                        )
                                        corr_lower = max(
                                            corr_lower,
                                            min(corr_upper - 0.1, min_allowed_lower),
                                        )
                                alert.actionable_plan["entry_range"] = (
                                    f"₹{corr_lower:,.1f} – ₹{corr_upper:,.1f}"
                                )
                    except Exception:
                        pass

        # 4. Institutional AI Sanity & Scrutiny Funnel (Fresh Setups Only)
        if not to_dispatch:
            is_fresh_setup = (
                not alert.is_invalidated
                and alert.stage
                not in ("TRAILING_UPDATE", "T1_ACHIEVED", "TARGET_ACHIEVED", "COMPLETED", "EXPIRED")
                and "TARGET" not in (alert.target_status or "")
            )
            if is_fresh_setup and not is_sim:
                from engine.alert_scrutiny import alert_scrutiny_auditor

                # Tier 1 Deterministic Mathematical Sanity Gate
                passed, failure_reason, sanity_flags = alert_scrutiny_auditor.verify_tier1_sanity(
                    alert
                )
                if not passed:
                    logger.info(
                        f"[AutoAlertEngine] Tier-1 Sanity Veto for {alert.symbol} ({alert.alert_type}): {failure_reason}"
                    )
                    return False

                # Gated Alerts: Synchronously scrutinize with AI before posting
                is_gated = alert.alert_type in (
                    "PRECURSOR_RADAR",
                    "SQUEEZE_BREAKOUT",
                    "CONFLUENCE_INFLECTION",
                    "ASYMMETRIC_OPPORTUNITY",
                    "OPTIONS_MOMENTUM",
                    # Commodity and currency alerts must pass macro-aware AI scrutiny
                    # to filter session noise, DXY artifacts, and thin-market traps.
                    "COMMODITY_MOMENTUM",
                    "CURRENCY_BREAKOUT",
                )
                if is_gated:
                    scrutiny = alert_scrutiny_auditor.scrutinize_alert(alert, timeout=2.5)
                    if scrutiny.status == "REJECTED" or scrutiny.score < 70:
                        logger.info(
                            f"[AutoAlertEngine] Tier-2 AI Scrutiny Rejection for {alert.symbol}: {scrutiny.trap_risk_warning or scrutiny.rejection_reason}"
                        )
                        return False
                    if not isinstance(alert.metrics, dict):
                        alert.metrics = {}
                    alert.metrics["scrutiny"] = scrutiny.to_dict()
                    alert.confidence = max(alert.confidence, scrutiny.score)
                else:
                    # Urgent signals (Gamma Blast, Circuit Warning): attach initial verified status and trigger async AI enrichment
                    if not isinstance(alert.metrics, dict):
                        alert.metrics = {}
                    alert.metrics["scrutiny"] = {
                        "status": "QUANT_VERIFIED",
                        "score": alert.confidence,
                        "logic_confirmation": f"Tier-1 math & level sanity passed for {alert.alert_type}.",
                        "trap_risk_warning": "Urgent microsecond trigger; monitor structural pivot.",
                        "actionable_guidance": "Execute according to actionable plan; do not chase beyond trigger.",
                        "sanctity_matrix": sanity_flags,
                        "auditor_model": "TIER1_QUANT",
                        "audited_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
                    }
                    self._async_enrich_scrutiny(alert)

            # 5. Insert alert into active list
            with self._lock:
                self._cooldowns[sig] = now
                if 'sym_sig' in locals():
                    self._cooldowns[sym_sig] = now
                # Retire prior-session alerts for the same underlying when a fresh session alert arrives
                for a in self._alerts:
                    if (
                        a.symbol.replace("NSE:", "")
                        .replace("BSE:", "")
                        .replace("MCX:", "")
                        .replace("NFO:", "")
                        .strip()
                        .upper()
                        == clean_target
                        and a.alert_id != alert.alert_id
                        and _alert_date(a) is not None
                        and _alert_date(a) < alert_dt_date
                    ):
                        a.stage = "EXPIRED"
                        a.is_archived = True
                        a.archive_reason = f"Superseded by fresh session alert {alert.alert_id}"

                self._alerts = [
                    a
                    for a in self._alerts
                    if not (
                        a.symbol.replace("NSE:", "")
                        .replace("BSE:", "")
                        .replace("MCX:", "")
                        .replace("NFO:", "")
                        .strip()
                        .upper()
                        == clean_target
                        and not a.is_active
                    )
                ]
                # Stamp original_call_time on first insertion (immutable anchor for milestone 'Call Given:' display)
                if not alert.original_call_time:
                    alert.original_call_time = alert.created_at
                self._alerts.insert(0, alert)
                if len(self._alerts) > self._max_buffer:
                    self._alerts.pop()
                self._save()
                to_dispatch = alert

        # Multi-channel notification outside lock
        if to_dispatch:
            self._dispatch(to_dispatch)
            return True
        return False

    def _async_enrich_scrutiny(self, alert: AutoAlert) -> None:
        """Asynchronously runs Tier-2 AI Scrutiny for urgent signals and broadcasts SSE update."""

        def _worker():
            try:
                from engine.alert_scrutiny import alert_scrutiny_auditor

                scrutiny = alert_scrutiny_auditor.scrutinize_alert(alert, timeout=3.0)
                if scrutiny and scrutiny.status != "REJECTED":
                    with self._lock:
                        target = next(
                            (a for a in self._alerts if a.alert_id == alert.alert_id), None
                        )
                        if target:
                            if not isinstance(target.metrics, dict):
                                target.metrics = {}
                            target.metrics["scrutiny"] = scrutiny.to_dict()
                            target.confidence = max(target.confidence, scrutiny.score)
                            self._save()
                    # Broadcast SSE update so React UI updates in place
                    try:
                        from web.sse import event_bus

                        event_bus.publish_sync(
                            "system",
                            {
                                "type": "alert_scrutiny_update",
                                "alert_id": alert.alert_id,
                                "symbol": alert.symbol,
                                "scrutiny": scrutiny.to_dict(),
                                "confidence": max(alert.confidence, scrutiny.score),
                                "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
                            },
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Async scrutiny error for {alert.alert_id}: {e}")

        t = threading.Thread(target=_worker, daemon=True, name=f"scrutiny-{alert.alert_id[:8]}")
        t.start()

    def _dispatch(self, alert: AutoAlert) -> None:
        """Broadcasts alert across all communication channels with clear REAL/LIVE vs TEST tagging."""
        from engine.alerts import _is_market_hours

        in_market = _is_market_hours(alert.exchange)
        is_test = (alert.environment == "TEST") or (not alert.is_live)
        if is_test:
            env_tag = "[TEST]"
        elif not in_market:
            env_tag = "[OFF-MARKET/EOD]"
        else:
            env_tag = "[REAL/LIVE]"

        is_t1 = "T1" in (alert.target_status or "") or alert.stage == "T1_ACHIEVED"
        is_target = (
            is_t1
            or alert.stage in ("TARGET_ACHIEVED", "COMPLETED")
            or "TARGET" in (alert.target_status or "")
        )
        is_trail = alert.stage == "TRAILING_UPDATE"

        from engine.alert_preferences import alert_preferences

        ui_allowed = alert_preferences.is_alert_allowed(alert, channel="ui")
        desktop_allowed = alert_preferences.is_alert_allowed(alert, channel="desktop")
        sound_allowed = alert_preferences.is_alert_allowed(alert, channel="sound")
        telegram_allowed = alert_preferences.is_alert_allowed(alert, channel="telegram")

        alert_dict = alert.to_dict()
        alert_dict["segment"] = getattr(alert, "segment", None) or alert_preferences.classify_alert_segment(alert)
        alert_dict["ui_allowed"] = ui_allowed
        alert_dict["sound_allowed"] = sound_allowed
        alert_dict["env_tag"] = env_tag
        alert_dict["is_live"] = not is_test
        alert_dict["environment"] = "TEST" if is_test else ("EOD" if not in_market else "LIVE")
        alert_dict["is_target"] = is_target
        alert_dict["is_trail"] = is_trail

        now_ts_str = (
            alert.invalidated_at
            or alert.created_at
            or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        )
        alert_dict["timestamp"] = now_ts_str

        # 1. Server-Sent Events (SSE) stream -> pushes to React UI Toast & Alerts View
        try:
            from web.sse import event_bus

            sys_type = "market_alert"
            if alert.is_invalidated:
                sys_type = "invalidation_alert"
            elif is_t1:
                sys_type = "target_1_achieved"
            elif is_target:
                sys_type = "target_achieved"
            elif is_trail:
                sys_type = "trailing_update"

            event_bus.publish_sync("alert", alert_dict)
            event_bus.publish_sync(
                "system",
                {
                    "type": sys_type,
                    "alert": alert_dict,
                    "is_invalidated": alert.is_invalidated,
                    "is_target": is_target,
                    "is_trail": is_trail,
                    "environment": alert.environment,
                    "segment": alert_dict["segment"],
                    "ui_allowed": ui_allowed,
                    "sound_allowed": sound_allowed,
                },
            )
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] SSE publish error: {e}")

        # 2. Desktop notification
        try:
            if desktop_allowed:
                from engine.alerts import _desktop_notify

                ts_short = now_ts_str.split(" ")[-2] if " " in now_ts_str else now_ts_str
                item_label = alert.contract_symbol or alert.symbol
                if alert.is_invalidated:
                    desktop_title = f"⚠️ {env_tag} [{ts_short}] VIEW INVALIDATED: {item_label}"
                    desktop_msg = alert.invalidation_reason or alert.summary
                elif is_t1:
                    desktop_title = f"🎯 {env_tag} [{ts_short}] TARGET 1 HIT: {item_label}"
                    desktop_msg = f"{alert.trailing_decision or 'BOOK 50% & TRAIL TO BREAKEVEN'}: {alert.trailing_rationale or alert.summary}"
                elif is_target:
                    desktop_title = f"🏁 {env_tag} [{ts_short}] FINAL TARGET HIT: {item_label}"
                    desktop_msg = f"{alert.trailing_decision or 'TARGET ACHIEVED'}: {alert.trailing_rationale or alert.summary}"
                elif is_trail:
                    desktop_title = f"📈 {env_tag} [{ts_short}] TRAIL STOP: {item_label} → ₹{alert.trailing_stop or 0:,.2f}"
                    desktop_msg = alert.trailing_rationale or alert.summary
                else:
                    desktop_title = f"{env_tag} [{ts_short}] {alert.headline}"
                    desktop_msg = alert.summary

                _desktop_notify(
                    title=desktop_title,
                    message=desktop_msg,
                )
        except Exception:
            pass

        # 3. Telegram push with multi-layer deduplication & decisive institutional formatting
        try:
            # STRICT PROVENANCE ISOLATION: Never push TEST, mock, or simulated alerts to user's real Telegram
            if (
                is_test
                or getattr(alert, "environment", "LIVE") == "TEST"
                or not getattr(alert, "is_live", True)
                or alert.alert_id.startswith("test-")
                or alert.alert_id.startswith("mock-")
            ):
                return

            # Ad-hoc / Scratch Script Protection:
            # Prevent python -c or scratch one-liners from broadcasting live Telegram messages
            # unless ALLOW_MANUAL_TELEGRAM_DISPATCH=1 is explicitly set in environment.
            is_cli_adhoc = bool(sys.argv and sys.argv[0] == "-c")
            if is_cli_adhoc and os.environ.get("ALLOW_MANUAL_TELEGRAM_DISPATCH", "0").lower() not in ("1", "true"):
                logger.info(
                    f"[AutoAlertEngine] Suppressed Telegram dispatch for ad-hoc script run of {alert.symbol} ({alert.alert_id})"
                )
                return

            # Check Alert Preferences routing gate
            if not telegram_allowed:
                return

            # OPTION B: Curated Post-Market Telegram Discipline
            # When the market is closed for this asset's exchange (e.g. NSE/BSE/NFO outside 09:15-15:30 IST):
            # 1. Strictly suppress intraday fast-derivatives / scalps (Gamma Blasts, Options Momentum, Intraday Sparks, Circuit Proximity).
            # 2. Only permit high-conviction positional swing setups (Precursor Radar, Asymmetric Opportunity, Squeeze) with confidence >= 90%.
            # 3. Existing position lifecycle updates (Invalidations, Targets, Trailing stops) remain permitted.
            is_milestone = (
                alert.is_invalidated
                or alert.stage == "INVALIDATED"
                or is_t1
                or is_target
                or is_trail
            )
            if not in_market and not is_milestone:
                if alert.alert_type in (
                    "GAMMA_BLAST",
                    "OPTIONS_MOMENTUM",
                    "INTRADAY_MOVER_SPARK",
                    "INTRADAY_BREAKDOWN_SPARK",
                    "CIRCUIT_WARNING",
                ):
                    return
                if alert.confidence < 90:
                    return

            from engine.alerts import _telegram_notify

            # Anti-flood / deduplication filter for Telegram channel
            now_ts = time.time()
            with self._lock:
                if alert.is_invalidated or alert.stage == "INVALIDATED":
                    m_key = f"{alert.symbol}:{alert.alert_type}:INVALIDATED"
                    if m_key in self._dispatched_milestones:
                        return
                    self._dispatched_milestones.add(m_key)

                elif is_t1:
                    m_key = f"{alert.symbol}:{alert.alert_type}:T1"
                    if m_key in self._dispatched_milestones:
                        return
                    self._dispatched_milestones.add(m_key)

                elif is_target:
                    m_key = f"{alert.symbol}:{alert.alert_type}:FINAL"
                    if m_key in self._dispatched_milestones:
                        return
                    self._dispatched_milestones.add(m_key)

                elif is_trail:
                    # Significant Updates Only: Intermediate trail ratchets are kept in Terminal UI
                    # and silenced on Telegram unless explicitly enabled by user preference
                    allow_trails = getattr(
                        alert_preferences.telegram, "allow_intermediate_trails", False
                    ) or (os.environ.get("TELEGRAM_ALLOW_TRAILING_UPDATES", "0").lower() in ("1", "true"))
                    if not allow_trails:
                        return
                    m_key = f"{alert.symbol}:{alert.alert_type}:TRAIL"
                    last_t = self._dispatch_cooldowns.get(m_key, 0.0)
                    if (now_ts - last_t) < 900.0:  # 15 min cooldown
                        return
                    self._dispatch_cooldowns[m_key] = now_ts

                elif alert.stage == "EARLY_WARNING":
                    # Early warnings are preliminary coiling signals -> keep in SSE / Terminal,
                    # do not buzz Telegram unless exceptionally high confidence (>= 90 for general, >= 80 for PRECURSOR_RADAR / ASYMMETRIC_OPPORTUNITY)
                    min_conf = (
                        80
                        if alert.alert_type
                        in (
                            "PRECURSOR_RADAR",
                            "ASYMMETRIC_OPPORTUNITY",
                            "OPTIONS_MOMENTUM",
                            "GAMMA_BLAST",
                            "COMMODITY_MOMENTUM",
                            "CURRENCY_BREAKOUT",
                        )
                        else 90
                    )
                    if alert.confidence < min_conf:
                        return
                    m_key = f"{alert.symbol}:{alert.alert_type}:EARLY"
                    last_e = self._dispatch_cooldowns.get(m_key, 0.0)
                    if (now_ts - last_e) < 1800.0:
                        return
                    self._dispatch_cooldowns[m_key] = now_ts

                elif alert.stage == "IGNITED":
                    m_key = f"{alert.symbol}:{alert.alert_type}:IGNITED"
                    last_i = self._dispatch_cooldowns.get(m_key, 0.0)
                    if (now_ts - last_i) < 1800.0:
                        return
                    self._dispatch_cooldowns[m_key] = now_ts

            from bot.alert_templates import render_auto_alert

            from engine.alert_preferences import classify_alert_segment

            tg_msg = render_auto_alert(alert, in_market=in_market)
            target_seg = getattr(alert, "segment", None)
            if not target_seg or target_seg == "EQUITY":
                detected = classify_alert_segment(alert)
                if detected != "EQUITY" or not target_seg:
                    target_seg = detected
            tg_target_chat_id = alert_preferences.get_telegram_chat_id(target_seg)
            if tg_target_chat_id:
                try:
                    _telegram_notify(tg_msg, chat_id=tg_target_chat_id)
                except TypeError:
                    _telegram_notify(tg_msg)
            else:
                _telegram_notify(tg_msg)
        except Exception:
            pass

        # 4. Terminal Notification (Rich Panel)
        try:
            from rich.console import Console
            from rich.panel import Panel

            _console = Console()
            if alert.is_invalidated:
                panel_title = f"[bold red]⚠️ {env_tag} ALERT / VIEW INVALIDATED[/bold red]"
                border_color = "red"
            elif alert.stage == "IN_FLIGHT_WARNING":
                panel_title = f"[bold yellow]⚠️ {env_tag} IN-FLIGHT WARNING / DECAY[/bold yellow]"
                border_color = "yellow"
            elif is_target:
                panel_title = f"[bold cyan]🎯 {env_tag} TARGET ACHIEVED[/bold cyan]"
                border_color = "cyan"
            elif is_trail:
                panel_title = f"[bold blue]📈 {env_tag} TRAILING STOP UPDATE[/bold blue]"
                border_color = "blue"
            else:
                panel_title = f"[bold {'magenta' if is_test else 'green'}]🔔 {env_tag} ALERT TRIGGERED[/bold {'magenta' if is_test else 'green'}]"
                border_color = "magenta" if is_test else "green"

            _console.print()
            _console.print(
                Panel(
                    f"[bold white]{alert.headline}[/bold white]\n"
                    f"{alert.summary}\n\n"
                    f"[bold yellow]DECISION:[/bold yellow] {alert.trailing_decision or 'MONITOR_SETUP'} | "
                    f"[bold yellow]TRAIL SL:[/bold yellow] ₹{alert.trailing_stop or alert.stop_loss:,.2f}\n"
                    f"[dim]🕒 Timestamp: {now_ts_str}[/dim]",
                    title=panel_title,
                    border_style=border_color,
                )
            )
            print("\a", end="", flush=True)  # Audio chime
        except Exception:
            pass

    # ── Invalidation Monitoring & Alerting ──────────────────────

    def check_and_alert_invalidations(
        self, exchanges: Optional[list[str]] = None
    ) -> list[AutoAlert]:
        """
        Scans all active (non-invalidated) alerts to check if their trade thesis
        or levels have been invalidated by recent market price action.
        Dispatches high-priority Invalidation Alerts across all channels.
        Optionally filters by list of active exchange names (e.g. ['NSE', 'NFO']).
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        invalidated_alerts: list[AutoAlert] = []
        exch_filter = {e.upper() for e in exchanges} if exchanges else None

        with self._lock:
            # Exclude synthetic TEST alerts from live market price invalidation checks!
            active_alerts = [
                a
                for a in self._alerts
                if not a.is_invalidated
                and a.stage != "INVALIDATED"
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        for alert in active_alerts:
            reason = evaluate_alert_invalidation(alert)
            if reason:
                # Conduct forensic post-mortem retrospective
                pm_dict = None
                try:
                    from engine.learning_engine import pattern_learning_engine

                    pm = pattern_learning_engine.conduct_invalidation_post_mortem(
                        alert, exit_price=alert.ltp, exchange=alert.exchange
                    )
                    pm_dict = pm.to_dict()
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] Post-mortem error for {alert.symbol}: {e}")

                with self._lock:
                    alert.is_invalidated = True
                    alert.invalidation_reason = reason
                    alert.invalidated_at = now_iso
                    alert.stage = "INVALIDATED"
                    alert.is_archived = True
                    alert.archived_at = now_iso
                    alert.archive_reason = reason
                    if pm_dict:
                        alert.metrics["post_mortem"] = pm_dict
                    is_test = (alert.environment == "TEST") or (not alert.is_live)
                    tag = "[TEST]" if is_test else "[REAL/LIVE]"
                    alert.headline = f"⚠️ {tag} VIEW INVALIDATED: {alert.symbol} {alert.alert_type.replace('_', ' ')}"
                    alert.summary = reason
                    self._save()

                # Dispatch the invalidation notification immediately!
                self._dispatch(alert)
                invalidated_alerts.append(alert)
                logger.warning(f"[AutoAlertEngine] Alert {alert.alert_id} INVALIDATED: {reason}")

        return invalidated_alerts

    def invalidate_alert_by_id(
        self, alert_id: str, reason: str = "Manually invalidated by user"
    ) -> Optional[AutoAlert]:
        """Manually invalidates an alert and broadcasts the invalidation warning."""
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        target_alert: Optional[AutoAlert] = None

        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id and not alert.is_invalidated:
                    alert.is_invalidated = True
                    alert.invalidation_reason = reason
                    alert.invalidated_at = now_iso
                    alert.stage = "INVALIDATED"
                    alert.is_archived = True
                    alert.archived_at = now_iso
                    alert.archive_reason = reason

                    try:
                        from engine.learning_engine import pattern_learning_engine

                        pm = pattern_learning_engine.conduct_invalidation_post_mortem(
                            alert, exit_price=alert.ltp, exchange=alert.exchange
                        )
                        alert.metrics["post_mortem"] = pm.to_dict()
                    except Exception as e:
                        logger.debug(
                            f"[AutoAlertEngine] Error in manual invalidation post-mortem: {e}"
                        )

                    is_test = (alert.environment == "TEST") or (not alert.is_live)
                    tag = "[TEST]" if is_test else "[REAL/LIVE]"
                    alert.headline = f"⚠️ {tag} VIEW INVALIDATED: {alert.symbol} {alert.alert_type.replace('_', ' ')}"
                    alert.summary = reason
                    target_alert = alert
                    break
            if target_alert:
                self._save()

        if target_alert:
            self._dispatch(target_alert)
        return target_alert

    # ── Target & Trailing Monitoring & Alerting ─────────────────

    def check_and_alert_targets_and_trailing(
        self, exchanges: Optional[list[str]] = None
    ) -> list[AutoAlert]:
        """
        Scans all active (non-invalidated, non-completed) alerts against live quotes to evaluate:
          1. Target milestones (Target 1 / Breakeven vs Final Target).
          2. Trailing stop ratchets.
        Dispatches high-priority target & trailing alerts with strict deduplication.
        Optionally filters by list of active exchange names (e.g. ['NSE', 'NFO']).
        """
        updated_alerts: list[AutoAlert] = []
        now_ts = time.time()
        exch_filter = {e.upper() for e in exchanges} if exchanges else None

        with self._lock:
            active_alerts = [
                a
                for a in self._alerts
                if not a.is_invalidated
                and a.stage not in ("INVALIDATED", "COMPLETED")
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        for alert in active_alerts:
            try:
                # Refresh current quote LTP
                is_opt_prem = is_alert_option_premium_level(alert)
                if is_opt_prem:
                    lookup_sym = alert.contract_symbol or (
                        f"{alert.exchange}:{alert.symbol}"
                        if ":" not in alert.symbol
                        else alert.symbol
                    )
                else:
                    lookup_sym = (
                        f"{alert.exchange}:{alert.symbol}"
                        if ":" not in alert.symbol
                        else alert.symbol
                    )
                from market.quotes import get_ltp

                try:
                    cur_quote_ltp = get_ltp(lookup_sym)
                    if cur_quote_ltp and cur_quote_ltp > 0:
                        alert.ltp = cur_quote_ltp
                except Exception:
                    cur_quote_ltp = None

                # Also refresh option premium if contract_symbol is attached to an underlying alert
                if alert.contract_symbol and not is_opt_prem:
                    try:
                        opt_quote = get_ltp(alert.contract_symbol)
                        if opt_quote and opt_quote > 0:
                            alert.option_premium = opt_quote
                    except Exception:
                        pass

                eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=cur_quote_ltp)
                if not eval_res or not eval_res.new_milestone:
                    continue

                # Cooldown check for trailing updates (suppress repeat within 5 minutes)
                if eval_res.new_milestone == "TRAILING_UPDATE":
                    last_alert_time = alert.last_trail_alert_time or 0.0
                    if (now_ts - last_alert_time) < 300.0:
                        continue  # Cooldown active

                with self._lock:
                    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                    alert.updated_at = now_str
                    alert.triggered_at = now_str
                    alert.should_trail = eval_res.should_trail
                    alert.trailing_decision = eval_res.trailing_decision
                    alert.trailing_stop = eval_res.recommended_stop
                    alert.trailing_rationale = eval_res.trailing_rationale
                    alert.locked_profit_pts = eval_res.locked_profit_pts
                    alert.locked_profit_pct = eval_res.locked_profit_pct
                    alert.target_status = eval_res.target_status
                    alert.r_multiple = eval_res.r_multiple
                    alert.pnl_pct = eval_res.pnl_pct

                    env_tag = (
                        "[TEST]"
                        if (alert.environment == "TEST" or not alert.is_live)
                        else "[REAL/LIVE]"
                    )

                    if eval_res.new_milestone in ("T1_ACHIEVED", "TARGET_ACHIEVED"):
                        if eval_res.new_milestone not in alert.achieved_milestones:
                            alert.achieved_milestones.append(eval_res.new_milestone)

                        if eval_res.new_milestone == "TARGET_ACHIEVED":
                            if not eval_res.should_trail:
                                alert.stage = "COMPLETED"
                                alert.headline = f"🏁 {env_tag} FINAL TARGET ACHIEVED: {alert.symbol} (₹{eval_res.recommended_stop:,.2f})"
                                alert.is_archived = True
                                alert.archived_at = datetime.now(IST).strftime(
                                    "%Y-%m-%d %H:%M:%S IST"
                                )
                                alert.archive_reason = "Final target achieved"
                            else:
                                alert.stage = "TARGET_ACHIEVED"
                                alert.headline = f"🎯 {env_tag} FINAL TARGET ACHIEVED: {alert.symbol} (₹{eval_res.recommended_stop:,.2f})"
                        else:
                            alert.stage = "T1_ACHIEVED"
                            alert.headline = f"🎯 {env_tag} TARGET 1 ACHIEVED: {alert.symbol} (₹{eval_res.recommended_stop:,.2f})"
                        alert.summary = eval_res.trailing_rationale

                    elif eval_res.new_milestone == "TRAILING_UPDATE":
                        alert.last_trail_alert_time = now_ts
                        alert.stage = "TRAILING_UPDATE"
                        alert.headline = f"📈 {env_tag} TRAILING STOP UPDATED: {alert.symbol} → ₹{eval_res.recommended_stop:,.2f}"
                        alert.summary = eval_res.trailing_rationale

                    self._save()

                self._dispatch(alert)
                updated_alerts.append(alert)
                logger.info(
                    f"[AutoAlertEngine] Alert {alert.alert_id} milestone {eval_res.new_milestone}: {eval_res.trailing_decision}"
                )

            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Target eval error for {alert.symbol}: {e}")

        return updated_alerts

    # ── In-Flight Decay & Danger Zone Warning Monitoring ────────

    def check_and_alert_in_flight_decay(
        self, exchanges: Optional[list[str]] = None
    ) -> list[AutoAlert]:
        """
        Scans all active (non-invalidated, non-completed) alerts against live market price to detect:
          1. Danger Zone Proximity: >= 70% risk budget consumed or within <= 1.5% of Stop-Loss.
          2. Theta Decay Stagnation: Option positions active >= 15m with P&L <= 0%.
        Dispatches high-priority IN_FLIGHT_WARNING alerts with strict one-shot latching.
        """
        from engine.alert_evaluator import evaluate_alert_in_flight_decay

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        warning_alerts: list[AutoAlert] = []
        exch_filter = {e.upper() for e in exchanges} if exchanges else None

        with self._lock:
            active_alerts = [
                a
                for a in self._alerts
                if not a.is_invalidated
                and a.stage not in ("INVALIDATED", "COMPLETED")
                and not getattr(a, "in_flight_warning_sent", False)
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        for alert in active_alerts:
            try:
                # Refresh current quote LTP
                is_opt_prem = is_alert_option_premium_level(alert)
                lookup_sym = (
                    (alert.contract_symbol or (f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol))
                    if is_opt_prem
                    else (f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol)
                )
                from market.quotes import get_ltp

                cur_quote_ltp = None
                try:
                    cur_quote_ltp = get_ltp(lookup_sym)
                    if cur_quote_ltp and cur_quote_ltp > 0:
                        alert.ltp = cur_quote_ltp
                except Exception:
                    cur_quote_ltp = None

                eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=cur_quote_ltp)
                if not eval_res or not eval_res.triggered:
                    continue

                with self._lock:
                    alert.in_flight_warning_sent = True
                    alert.in_flight_warning_reason = eval_res.reason
                    alert.in_flight_warning_at = now_iso
                    alert.updated_at = now_iso
                    alert.stage = "IN_FLIGHT_WARNING"
                    alert.headline = eval_res.headline
                    alert.summary = eval_res.summary
                    alert.trailing_decision = eval_res.coaching_decision
                    alert.pnl_pct = eval_res.pnl_pct
                    self._save()

                self._dispatch(alert)
                warning_alerts.append(alert)
                logger.warning(
                    f"[AutoAlertEngine] Alert {alert.alert_id} IN-FLIGHT WARNING: {eval_res.reason}"
                )

            except Exception as e:
                logger.debug(f"[AutoAlertEngine] In-flight decay check error for {alert.symbol}: {e}")

        return warning_alerts

    def create_test_in_flight_warning_alert(
        self,
        warning_type: str = "DANGER_ZONE",  # "DANGER_ZONE" | "THETA_STAGNATION"
        symbol: str = "RELIANCE",
    ) -> AutoAlert:
        """
        Generates a simulated test In-Flight Decay / Danger Zone Warning alert clearly tagged as [TEST].
        Verifies notifications, toasts, and UI cards for proactive risk coaching.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        alert_id = f"test-decay-{uuid.uuid4().hex[:6]}"

        w_type = warning_type.upper()
        if "VWAP" in w_type:
            stage = "IN_FLIGHT_WARNING"
            headline = f"🌊 [TEST] IN-FLIGHT WARNING: {symbol} (VWAP -1.0σ Institutional Band Breakdown)"
            decision = "SCRATCH_OR_TIGHTEN_TO_VWAP"
            summary = (
                f"Price ₹2,810.00 crossed below intraday VWAP -1.0σ band (₹2,822.00, VWAP ₹2,835.00, -0.9%). "
                f"Institutional order flow distribution confirmed before nominal Stop-Loss (₹2,800.00) is hit. "
                f"DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO VWAP LOWER BAND (₹2,822.00)."
            )
            ltp = 2810.0
            trigger_level = 2840.0
            stop_loss = 2800.0
            target_level = 2920.0
            pnl_pct = -1.1
        elif "CLIFF" in w_type or ("0DTE" in w_type and "AFTERNOON" in w_type):
            stage = "IN_FLIGHT_WARNING"
            headline = f"⏳ [TEST] IN-FLIGHT WARNING: {symbol} (0DTE Theta Cliff: 9m No Progress)"
            decision = "EXIT_0DTE_OPTION_IMMEDIATELY"
            summary = (
                f"0DTE option position active for 9m post-13:30 IST with zero momentum (P&L: -5.5%). "
                f"Rapid afternoon pin-risk & gamma collapse underway. "
                f"DECISION: EXIT 0DTE OPTION IMMEDIATELY TO AVOID PIN-RISK PREMIUM EVAPORATION."
            )
            ltp = 38.0
            trigger_level = 42.0
            stop_loss = 25.0
            target_level = 65.0
            pnl_pct = -5.5
        elif "THETA" in w_type:
            stage = "IN_FLIGHT_WARNING"
            headline = f"⏳ [TEST] IN-FLIGHT WARNING: {symbol} (Theta Stagnation: 18m No Progress)"
            decision = "EXIT_STAGNANT_OPTION"
            summary = (
                f"Option position {symbol} 2900 CE active for 18m without upside momentum (P&L: -4.2%). "
                f"Accelerating theta decay threatens capital. "
                f"DECISION: SCRATCH / EXIT AT MARKET BEFORE THETA EROSION REACHES STOP-LOSS."
            )
            ltp = 48.0
            trigger_level = 50.0
            stop_loss = 35.0
            target_level = 75.0
            pnl_pct = -4.2
        else:  # DANGER_ZONE
            stage = "IN_FLIGHT_WARNING"
            headline = f"⚠️ [TEST] IN-FLIGHT WARNING: {symbol} (Danger Zone: 75% Risk Consumed)"
            decision = "SCRATCH_OR_TIGHTEN_STOP"
            summary = (
                f"LTP ₹2,830.00 is within 0.4% of Stop-Loss (₹2,820.00). "
                f"75% of risk budget is eroded (P&L: -1.0%). "
                f"DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO PREVENT FULL CAPITAL LOSS."
            )
            ltp = 2830.0
            trigger_level = 2860.0
            stop_loss = 2820.0
            target_level = 3050.0
            pnl_pct = -1.0

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type="SQUEEZE_BREAKOUT",
            stage=stage,
            symbol=symbol,
            exchange="NSE",
            direction="BULLISH",
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=trigger_level,
            target_level=target_level,
            stop_loss=stop_loss,
            confidence=88,
            created_at=now_iso,
            is_live=False,
            environment="TEST",
            is_invalidated=False,
            is_archived=False,
            trailing_decision=decision,
            trailing_stop=stop_loss,
            pnl_pct=pnl_pct,
            in_flight_warning_sent=True,
            in_flight_warning_reason=summary,
            in_flight_warning_at=now_iso,
        )
        with self._lock:
            self._alerts.append(alert)
            self._save()
        self._dispatch(alert)
        return alert

    def create_test_target_alert(
        self,
        milestone: str = "T1",  # "T1" | "FINAL" | "TRAIL"
        should_trail: bool = True,
        symbol: str = "RELIANCE",
    ) -> AutoAlert:
        """
        Generates a simulated test Target Achieved or Trailing Stop alert clearly tagged as [TEST].
        Verifies notifications, toasts, and UI cards for target progression and trailing guidance.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        alert_id = f"test-target-{uuid.uuid4().hex[:6]}"

        if milestone.upper() == "T1":
            stage = "T1_ACHIEVED"
            headline = f"🎯 [TEST] TARGET 1 ACHIEVED: {symbol} (₹2,920.00, +2.0R)"
            decision = "BOOK_50_TRAIL_BREAKEVEN"
            trail_sl = 2865.0
            locked_pts = 5.0
            locked_pct = 0.2
            rationale = (
                f"Target 1 reached at ₹2,920.00 (+2.1%, +2.0R). "
                f"DECISION: BOOK 50% PARTIAL PROFIT NOW & TRAIL STOP-LOSS TO BREAKEVEN (₹{trail_sl:,.2f}). "
                f"Trade is now 100% risk-free. Hold remaining 50% runner for Target 2."
            )
            achieved = ["T1_ACHIEVED"]
        elif milestone.upper() == "TRAIL":
            stage = "TRAILING_UPDATE"
            trail_sl = 2950.0
            headline = f"📈 [TEST] TRAILING STOP UPDATED: {symbol} → ₹{trail_sl:,.2f}"
            decision = "TRAIL_DYNAMIC_ATR"
            locked_pts = 90.0
            locked_pct = 3.1
            rationale = (
                f"Price expanded to ₹2,990.00 (+4.5%, +3.8R). "
                f"DECISION: RATCHET TRAILING STOP HIGHER to ₹{trail_sl:,.2f} (Chandelier ATR Trail). "
                f"Guaranteed locked profit increased to +₹{locked_pts:,.2f}/sh (+{locked_pct:.1f}%)."
            )
            achieved = ["T1_ACHIEVED"]
        else:  # FINAL
            stage = "TARGET_ACHIEVED"
            headline = f"🏁 [TEST] FINAL TARGET ACHIEVED: {symbol} (₹3,050.00, +6.6%)"
            if should_trail:
                decision = "TRAIL_DYNAMIC_ATR"
                trail_sl = 2980.0
                locked_pts = 120.0
                locked_pct = 4.2
                rationale = (
                    f"Primary target reached with runaway volume (+2.4x). "
                    f"DECISION: TRAIL STOP-LOSS TO ₹{trail_sl:,.2f} (Chandelier ATR Trail). "
                    f"DO NOT FULLY EXIT RUNNER — Let runners ride!"
                )
            else:
                decision = "BOOK_FULL_PROFIT_NO_TRAIL"
                trail_sl = 3050.0
                locked_pts = 190.0
                locked_pct = 6.6
                rationale = (
                    "Final target reached at major resistance. "
                    "DECISION: FULL PROFIT BOOKING RECOMMENDED. Close all positions at market. "
                    "DO NOT TRAIL FURTHER — high probability of mean-reversion exhaustion."
                )
            achieved = ["T1_ACHIEVED", "TARGET_ACHIEVED"]

        is_archived_final = stage == "TARGET_ACHIEVED" and not should_trail
        alert = AutoAlert(
            alert_id=alert_id,
            alert_type="SQUEEZE_BREAKOUT",
            stage=stage,
            symbol=symbol,
            exchange="NSE",
            direction="BULLISH",
            headline=headline,
            summary=rationale,
            ltp=2920.0
            if milestone.upper() == "T1"
            else (2990.0 if milestone.upper() == "TRAIL" else 3050.0),
            trigger_level=2860.0,
            target_level=3050.0,
            stop_loss=2820.0,
            confidence=92,
            created_at=now_iso,
            is_live=False,
            environment="TEST",
            is_invalidated=False,
            is_archived=is_archived_final,
            archived_at=now_iso if is_archived_final else None,
            archive_reason="Final target achieved (Full exit)" if is_archived_final else None,
            achieved_milestones=achieved,
            target_status=stage if stage in ("T1_ACHIEVED", "TARGET_ACHIEVED") else "T1_ACHIEVED",
            should_trail=should_trail if milestone.upper() != "T1" else True,
            trailing_decision=decision,
            trailing_stop=trail_sl,
            trailing_rationale=rationale,
            locked_profit_pts=locked_pts,
            locked_profit_pct=locked_pct,
            metrics={"is_test": True, "rvol": 2.4, "vol_oi_ratio": 2.2},
            actionable_plan={"action": decision, "recommended_stop": trail_sl},
        )

        with self._lock:
            self._alerts.insert(0, alert)
            if len(self._alerts) > self._max_buffer:
                self._alerts.pop()
            self._save()

        self._dispatch(alert)
        return alert

    # ── Test Alert Generator ────────────────────────────────────

    def create_test_alert(
        self,
        alert_type: str = "GAMMA_BLAST",
        stage: str = "EARLY_WARNING",
        symbol: str = "RELIANCE",
        is_invalidation: bool = False,
    ) -> AutoAlert:
        """
        Generates an explicit TEST alert to verify notifications, Toasts, and SSE streams.
        Always clearly tagged as [TEST] so it can never be mistaken for real live market action.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        alert_id = f"test-alert-{uuid.uuid4().hex[:6]}"

        if is_invalidation:
            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="INVALIDATED",
                symbol=symbol,
                exchange="NSE",
                direction="BULLISH",
                headline=f"⚠️ [TEST] VIEW INVALIDATED: {symbol} {alert_type.replace('_', ' ')}",
                summary=(
                    "Stop-loss level breached at ₹2,840.00 (LTP ₹2,835.00). "
                    "Squeeze breakout thesis is no longer valid. Close active positions."
                ),
                ltp=2835.0,
                trigger_level=2880.0,
                target_level=3020.0,
                stop_loss=2840.0,
                confidence=90,
                created_at=now_iso,
                is_live=False,
                environment="TEST",
                is_invalidated=True,
                is_archived=True,
                archived_at=now_iso,
                archive_reason="Stop-loss level breached at ₹2,840.00 (LTP ₹2,835.00). Trade setup invalidated.",
                invalidation_reason=(
                    "Stop-loss level breached at ₹2,840.00 (LTP ₹2,835.00). "
                    "Trade setup invalidated."
                ),
                invalidated_at=now_iso,
                metrics={"is_test": True, "test_mode": "invalidation_simulation"},
            )
        else:
            is_opt = alert_type == "GAMMA_BLAST"
            strike_val = 24500.0 if symbol in ("NIFTY", "BANKNIFTY") else 2900.0
            contract_sym = f"{symbol}26SEP{int(strike_val)}CE" if is_opt else None
            exp_date_val = "2026-09-24" if is_opt else None
            exp_type_val = "MONTHLY" if is_opt else None
            spot_val = 24450.0 if symbol in ("NIFTY", "BANKNIFTY") else 2860.0
            prem_val = 145.0 if is_opt else 2860.0

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage=stage,
                symbol=symbol,
                exchange="NFO" if is_opt else "NSE",
                direction="BULLISH",
                headline=f"🧪 [TEST] ⚡ {alert_type.replace('_', ' ')} {stage.replace('_', ' ')}: {symbol}",
                summary=(
                    "Call writers shedding 14.5% OI with 2.4x turnover holding intraday VWAP. "
                    "Coiling for momentum expansion."
                ),
                ltp=prem_val,
                trigger_level=strike_val if is_opt else 2880.0,
                target_level=320.0 if is_opt else 3050.0,
                stop_loss=95.0 if is_opt else 2820.0,
                strike=strike_val if is_opt else None,
                option_type="CE" if is_opt else None,
                contract_symbol=contract_sym,
                expiry_date=exp_date_val,
                expiry_type=exp_type_val,
                underlying_spot=spot_val if is_opt else None,
                option_premium=prem_val if is_opt else None,
                confidence=88,
                created_at=now_iso,
                is_live=False,
                environment="TEST",
                is_invalidated=False,
                is_archived=False,
                metrics={"is_test": True, "vol_oi_ratio": 2.4, "oi_change_pct": -14.5, "rvol": 1.8},
                actionable_plan={
                    "action": "BUY" if is_opt else "TEST_ONLY",
                    "instrument": contract_sym or symbol,
                    "strike": strike_val if is_opt else None,
                    "option_type": "CE" if is_opt else None,
                    "expiry_date": exp_date_val,
                    "expiry_type": exp_type_val,
                    "recommended_entry": f"₹{prem_val:.1f} (Option Premium)"
                    if is_opt
                    else "Market",
                    "target": "₹320.0 (+120%)" if is_opt else "₹3050.0",
                    "stop_loss": "₹95.0 (-35%)" if is_opt else "₹2820.0",
                    "note": "SIMULATED TEST ALERT - DO NOT PLACE REAL ORDER",
                },
            )

        with self._lock:
            self._alerts.insert(0, alert)
            if len(self._alerts) > self._max_buffer:
                self._alerts.pop()
            self._save()

        self._dispatch(alert)
        return alert

    # ── Scanning Loops ──────────────────────────────────────────

    def scan_gamma_blasts(self) -> list[AutoAlert]:
        """Scans watched indices and high-turnover F&O leaders for Gamma Blast inflection."""
        from market.options import get_options_chain
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        targets = list(self._watched_indices)
        for s in self.watched_equities:
            if s not in targets:
                targets.append(s)

        for sym in targets:
            try:
                spot = get_ltp(f"NSE:{sym}")
                if not spot or spot <= 0:
                    continue
                chain = get_options_chain(sym)
                if not chain:
                    continue

                alerts = detect_gamma_blast(sym, spot, chain)
                for a in alerts:
                    if self.record_alert(a):
                        found.append(a)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Gamma scan error for {sym}: {e}")

        return found

    def scan_squeeze_breakouts(self) -> list[AutoAlert]:
        """Scans equities for TTM Squeeze breakout early warnings."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        for sym in self.watched_equities:
            try:
                ltp = get_ltp(f"NSE:{sym}")
                if not ltp or ltp <= 0:
                    continue
                df = get_ohlcv(sym, exchange="NSE", interval="day", days=60)
                if df is None or len(df) < 25:
                    continue

                alert = detect_squeeze_breakout(sym, df, ltp)
                if alert and self.record_alert(alert):
                    found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Squeeze scan error for {sym}: {e}")

        return found

    def scan_circuits(self) -> list[AutoAlert]:
        """Scans watched equities for Upper Circuit proximity."""
        from market.quotes import get_quote

        found: list[AutoAlert] = []
        for sym in self.watched_equities:
            try:
                q = get_quote(f"NSE:{sym}")
                if not q:
                    continue
                ltp = getattr(q, "ltp", 0.0) or getattr(q, "last_price", 0.0)
                prev_close = getattr(q, "prev_close", 0.0) or getattr(q, "close", 0.0)
                if ltp > 0 and prev_close > 0:
                    alert = detect_circuit_proximity(sym, ltp, prev_close)
                    if alert and self.record_alert(alert):
                        found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Circuit scan error for {sym}: {e}")

        return found

    def scan_pattern_coilings(self) -> list[AutoAlert]:
        """Scans watched universe for pre-blast pattern coiling matching learned archetypes."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        for sym in self.watched_equities:
            try:
                ltp = get_ltp(f"NSE:{sym}")
                if not ltp or ltp <= 0:
                    continue
                df = get_ohlcv(sym, exchange="NSE", interval="day", days=60)
                if df is None or len(df) < 20:
                    continue

                alert = detect_learned_pattern_coiling(sym, df, ltp)
                if alert and self.record_alert(alert):
                    found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Pattern coiling scan error for {sym}: {e}")

        return found

    def scan_precursor_radars(self) -> list[AutoAlert]:
        """Scans liquid universe across F&O, Cash Equities, and Indices for high-conviction pre-ignition candidates."""
        from engine.precursor_radar import precursor_radar

        found: list[AutoAlert] = []
        try:
            candidates = precursor_radar.scan_precursors(top_n=6)
            for c in candidates:
                if c.conviction_score >= 80:
                    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                    alert_id = (
                        f"precursor-{c.symbol.lower()}-{datetime.now(IST).strftime('%Y%m%d')}"
                    )
                    seg_tag = f"[{c.segment}]"
                    headline = f"⚡ PRECURSOR RADAR {seg_tag}: {c.symbol} Coiling at ₹{c.ltp:,.1f} ({c.conviction_score}/100)"
                    summary = f"{seg_tag} Pre-ignition coiling: {'; '.join(c.matched_factors[:2])}. Entry: {c.entry_range}."
                    # Provenance gate: mark as TEST if LTP is zero/mock
                    is_authentic_pr = bool(c.ltp and c.ltp > 0 and not getattr(c, "_is_mock", False))
                    alert = AutoAlert(
                        alert_id=alert_id,
                        alert_type="PRECURSOR_RADAR",
                        stage="EARLY_WARNING",
                        symbol=c.symbol,
                        exchange=c.exchange,
                        direction=c.direction,
                        headline=headline,
                        summary=summary,
                        ltp=c.ltp,
                        trigger_level=c.coiling_pivot_high or c.ltp,
                        target_level=c.target_1,
                        stop_loss=c.stop_loss,
                        confidence=c.conviction_score,
                        created_at=now_iso,
                        is_live=is_authentic_pr,
                        environment="LIVE" if is_authentic_pr else "TEST",
                        metrics={
                            "conviction_score": c.conviction_score,
                            "segment": c.segment,
                            "prior_vol_ratio": c.prior_vol_ratio,
                            "squeeze_bars": c.squeeze_bars,
                            "sector_name": c.sector_name,
                            "rrg_quadrant": c.rrg_quadrant,
                            "matched_factors": c.matched_factors,
                            "closest_archetype": c.closest_archetype,
                        },
                        actionable_plan={
                            "action": "BUY",
                            "segment": c.segment,
                            "entry_range": c.entry_range,
                            "target": f"₹{c.target_1:,.1f}",
                            "target_2": f"₹{c.target_2:,.1f}",
                            "stop_loss": f"₹{c.stop_loss:,.1f}",
                            "risk_reward": c.risk_reward,
                            "when_to_buy": c.when_to_buy,
                            "when_to_wait": c.when_to_wait,
                            "profit_rule": c.profit_rule,
                        },
                    )
                    if self.record_alert(alert):
                        found.append(alert)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Precursor scan error: {e}")
        return found

    def scan_intraday_mover_sparks(self) -> list[AutoAlert]:
        """
        Scans liquid universe (Indices, F&O, Cash) for explosive intraday sparks (T-0 session moves).
        Detects BOTH:
          1. Bullish breakout sparks (surge >= +2.2%, holds above VWAP, RVOL >= 1.8x).
          2. Bearish breakdown sparks (drop <= -2.0%, breaks below VWAP, RVOL >= 1.8x).
        """
        from engine.precursor_radar import precursor_radar, classify_symbol_segment
        from market.quotes import get_quote
        from market.history import get_ohlcv

        found: list[AutoAlert] = []
        universe = precursor_radar.get_scan_universe(segment="ALL")
        for s in self.watched_equities:
            if s not in universe:
                universe.append(s)

        # Batch fetch quotes
        formatted = [f"NSE:{s}" if ":" not in s else s for s in universe]
        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Quotes fetch error in spark scan: {e}")
            return found

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        for sym in universe:
            clean_sym = sym.upper().replace("NSE:", "").replace(".NS", "").strip()
            q = quotes_map.get(f"NSE:{clean_sym}") or quotes_map.get(clean_sym)
            if not q:
                continue

            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            if ltp <= 0:
                continue

            chg = float(getattr(q, "change_pct", 0.0) or 0.0)
            vol = int(getattr(q, "volume", 0) or 0)
            vwap = float(getattr(q, "vwap", 0.0) or ltp)

            # Move thresholds: indices >= 0.8% / <= -0.8%, equities >= 2.2% / <= -2.0%
            seg = classify_symbol_segment(clean_sym)
            min_pos_chg = 0.8 if seg == "INDEX" else 2.2
            min_neg_chg = -0.8 if seg == "INDEX" else -2.0

            is_bullish = (chg >= min_pos_chg) and (vwap <= 0 or ltp >= (vwap * 0.998))
            is_bearish = (chg <= min_neg_chg) and (vwap > 0 and ltp < vwap)

            if not (is_bullish or is_bearish):
                continue

            # Check turnover gate for equities (₹8 Cr min)
            turnover_cr = round((ltp * vol) / 1e7, 2)
            if seg != "INDEX" and turnover_cr < 8.0:
                continue

            # Calculate RVOL
            try:
                df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=30)
                if df is None or len(df) < 15:
                    continue
                vols = df["volume"].values
                avg_vol = (
                    float(np.mean(vols[-21:-1])) if len(vols) >= 21 else float(np.mean(vols[:-1]))
                )
                rvol = round(vol / max(1.0, avg_vol), 2)
            except Exception:
                rvol = 1.0

            if rvol < 1.8:
                continue

            seg_tag = f"[{seg}]"

            if is_bullish:
                direction = "BULLISH"
                alert_type = "INTRADAY_SPARK"
                alert_id = (
                    f"spark-bull-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"
                )
                sl_price = round(max(vwap * 0.995, ltp * 0.985), 2)
                t1_price = round(ltp + 1.5 * (ltp - sl_price), 2)
                headline = f"🚀 INTRADAY SPARK {seg_tag}: {clean_sym} +{chg:.1f}% with {rvol:.1f}x Volume Surge"
                summary = f"{seg_tag} Session breakout underway: Reclaimed VWAP (₹{vwap:,.1f}) with {rvol:.1f}x RVOL. Momentum entry active."
                plan = {
                    "action": "BUY_MOMENTUM",
                    "segment": seg,
                    "entry_range": f"₹{round(ltp * 0.998, 1):,.1f} - ₹{round(ltp * 1.005, 1):,.1f}",
                    "stop_loss": f"₹{sl_price:,.1f}",
                    "target": f"₹{t1_price:,.1f}",
                    "when_to_buy": f"Buy on 5m VWAP holding above ₹{vwap:,.1f}",
                    "when_to_wait": f"Do not chase if price extends > {round(chg + 1.5, 1)}%",
                }
            else:
                direction = "BEARISH"
                alert_type = "INTRADAY_BREAKDOWN_SPARK"
                alert_id = (
                    f"spark-bear-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"
                )
                sl_price = round(min(vwap * 1.005, ltp * 1.015), 2)
                risk_pts = max(1.0, sl_price - ltp)
                t1_price = round(max(1.0, ltp - 1.5 * risk_pts), 2)
                headline = f"⚡ INTRADAY BREAKDOWN {seg_tag}: {clean_sym} {chg:.1f}% with {rvol:.1f}x Volume Surge"
                summary = f"{seg_tag} Severe session breakdown underway: Lost VWAP (₹{vwap:,.1f}) with {rvol:.1f}x RVOL. Short / Put entry active."
                plan = {
                    "action": "SELL_SHORT_OR_BUY_PUT",
                    "segment": seg,
                    "entry_range": f"₹{round(ltp * 1.002, 1):,.1f} - ₹{round(ltp * 0.995, 1):,.1f}",
                    "stop_loss": f"₹{sl_price:,.1f}",
                    "target": f"₹{t1_price:,.1f}",
                    "when_to_buy": f"Enter short or ATM Put on pullbacks to ₹{vwap:,.1f} with tight stop above VWAP.",
                    "when_to_wait": f"Do not chase if breakdown extends > {round(abs(chg) + 1.5, 1)}% without retest.",
                }

            # Provenance gate: validate quote is from a real broker, not mock/test stub
            is_mock_spark = (
                type(q).__name__ == "MagicMock"
                or getattr(q, "_is_mock", False)
                or getattr(q, "provider", "") in ("mock", "TEST")
                or getattr(q, "data_state", "") == "UNAVAILABLE"
            )
            is_test_env = (
                os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test"
            )
            is_authentic_spark = not (is_mock_spark or is_test_env)

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED",
                symbol=clean_sym,
                exchange="NSE",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=min(95, int(75 + rvol * 5)),
                created_at=now_iso,
                is_live=is_authentic_spark,
                environment="LIVE" if is_authentic_spark else "TEST",
                metrics={
                    "rvol": rvol,
                    "turnover_cr": turnover_cr,
                    "vwap": vwap,
                    "change_pct": chg,
                    "segment": seg,
                },
                actionable_plan=plan,
            )
            if self.record_alert(alert):
                found.append(alert)

        return found

    def scan_asymmetric_opportunities(self) -> list[AutoAlert]:
        """Scans for high-asymmetry (min 1:3.0 R:R) setups: Pocket Pivot, MWPL Squeeze, 200-EMA dip, 0DTE Gamma."""
        found: list[AutoAlert] = []
        try:
            from engine.asymmetric_radar import asymmetric_radar

            opps = asymmetric_radar.scan_asymmetric_opportunities(top_n=6)
            now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

            for opp in opps:
                alert_id = f"auto-asym-{opp.symbol}-{uuid.uuid4().hex[:6]}"
                headline = f"🎯 [LOW RISK : HIGH REWARD] {opp.setup_label}: {opp.symbol} (R:R {opp.risk_reward})"
                summary = (
                    f"{opp.catalyst_summary} Invalidation SL: ₹{opp.stop_loss:,.1f} | "
                    f"T1 (+2R): ₹{opp.target_1:,.1f} | T2 (+4R): ₹{opp.target_2:,.1f} | Moonshot: ₹{opp.target_moonshot:,.1f}"
                )

                plan = {
                    "action": opp.setup_type,
                    "segment": opp.segment,
                    "entry_range": opp.entry_range,
                    "stop_loss": f"₹{opp.stop_loss:,.1f}",
                    "target": f"₹{opp.target_1:,.1f}",
                    "target_2": f"₹{opp.target_2:,.1f}",
                    "target_moonshot": f"₹{opp.target_moonshot:,.1f}",
                    "risk_reward": opp.risk_reward,
                    "when_to_buy": opp.when_to_buy,
                    "when_to_wait": opp.when_to_wait,
                    "profit_rule": opp.profit_rule,
                    "trade_plan": {
                        "entry_price": opp.entry_price,
                        "invalidation_stop": opp.stop_loss,
                        "target_1": opp.target_1,
                        "target_2": opp.target_2,
                        "target_3": opp.target_moonshot,
                        "risk_reward": opp.risk_reward,
                    },
                }
                if opp.contract_symbol:
                    plan["option_plan"] = {
                        "contract_symbol": opp.contract_symbol,
                        "strike": opp.strike,
                        "option_type": opp.option_type,
                        "expiry_date": opp.expiry_date,
                        "entry_premium": opp.option_premium,
                        "sl_premium": opp.option_stop_loss,
                        "t1_premium": opp.option_target_1,
                        "t2_premium": opp.option_target_2,
                        "lot_size": opp.lot_size,
                    }
                    plan["option_contract"] = opp.contract_symbol
                    plan["option_entry"] = (
                        f"₹{opp.option_premium:,.1f}" if opp.option_premium else None
                    )
                    plan["option_target_1"] = (
                        f"₹{opp.option_target_1:,.1f}" if opp.option_target_1 else None
                    )
                    plan["option_target_2"] = (
                        f"₹{opp.option_target_2:,.1f}" if opp.option_target_2 else None
                    )
                    plan["option_stop_loss"] = (
                        f"₹{opp.option_stop_loss:,.1f}" if opp.option_stop_loss else None
                    )
                    plan["lot_size"] = opp.lot_size

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="ASYMMETRIC_OPPORTUNITY",
                    stage="EARLY_WARNING",
                    symbol=opp.symbol,
                    exchange=opp.exchange,
                    direction=opp.direction,
                    headline=headline,
                    summary=summary,
                    ltp=opp.ltp,
                    trigger_level=opp.entry_price,
                    target_level=opp.target_1,
                    stop_loss=opp.stop_loss,
                    strike=None,  # Keep primary alert anchored to underlying spot price levels
                    option_type=None,
                    contract_symbol=None,
                    expiry_date=None,
                    option_premium=None,
                    confidence=opp.conviction_score,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    metrics=opp.to_dict(),
                    actionable_plan=plan,
                )
                if self.record_alert(alert):
                    found.append(alert)

        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Asymmetric opportunities scan error: {e}")

        return found

    def scan_options_momentum_breakouts(self) -> list[AutoAlert]:
        """
        Scans liquid indices and Tier-1 F&O leaders for directional Options Momentum Breakouts.
        Surfaces high-volume, high-turnover ATM contracts with verified underlying SMC alignment,
        tight spot-anchored stop-losses, optimal trade entry (OTE) pullback zones, and favorable R:R.
        """
        from market.options import get_options_chain
        from market.quotes import get_ltp
        from engine.position_sizer import get_lot_size

        found: list[AutoAlert] = []
        targets = list(self._watched_indices)
        for s in self.watched_equities:
            if s not in targets:
                targets.append(s)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        now_dt = datetime.now(IST)
        is_friday_late = (now_dt.weekday() == 4) and (now_dt.hour > 14 or (now_dt.hour == 14 and now_dt.minute >= 30))

        for sym in targets:
            clean_sym = sym.replace("NSE:", "").replace("NFO:", "").strip().upper()
            try:
                from market.quotes import get_quote, get_ltp
                spot = get_ltp(f"NSE:{clean_sym}")
                if not spot or spot <= 0:
                    continue
                quote_obj = None
                try:
                    raw_q = get_quote(f"NSE:{clean_sym}")
                    if isinstance(raw_q, dict):
                        quote_obj = raw_q.get(f"NSE:{clean_sym}") or raw_q.get(clean_sym) or (next(iter(raw_q.values())) if raw_q else None)
                    else:
                        quote_obj = raw_q
                except Exception:
                    pass
                if quote_obj:
                    q_ltp = getattr(quote_obj, "last_price", None)
                    if q_ltp and abs(q_ltp - spot) / max(1.0, spot) > 0.005:
                        quote_obj = None

                spot_change_pct = getattr(quote_obj, "change_pct", None) if quote_obj else None
                spot_open = getattr(quote_obj, "open", None) if quote_obj else None
                spot_vwap = getattr(quote_obj, "vwap", None) if quote_obj else None

                # ── Underlying Price Action & SMC Due Diligence ──────────────
                from market.history import get_ohlcv
                df_5m = None
                try:
                    df_5m = get_ohlcv(clean_sym, exchange="NSE", interval="5minute", days=2)
                except Exception:
                    pass

                if df_5m is not None and len(df_5m) >= 1:
                    try:
                        last_c = float(df_5m.iloc[-1].get("close", df_5m.iloc[-1].get("Close", 0.0)))
                        if last_c > 0 and abs(last_c - spot) / max(1.0, spot) > 0.02:
                            df_5m = None
                    except Exception:
                        pass

                # Derive 5m intraday VWAP if not provided by quote
                if (not spot_vwap or spot_vwap <= 0) and df_5m is not None and len(df_5m) >= 2:
                    try:
                        vols = df_5m["volume"].values
                        highs = df_5m["high"].values if "high" in df_5m.columns else df_5m["High"].values
                        lows = df_5m["low"].values if "low" in df_5m.columns else df_5m["Low"].values
                        closes = df_5m["close"].values if "close" in df_5m.columns else df_5m["Close"].values
                        typical_price = (highs + lows + closes) / 3.0
                        cum_vol = np.cumsum(vols)
                        cum_pv = np.cumsum(typical_price * vols)
                        if cum_vol[-1] > 0:
                            spot_vwap = float(cum_pv[-1] / cum_vol[-1])
                    except Exception:
                        pass

                # Compute recent 5m candle wick ratios (Exhaustion & Climax Filter)
                upper_wick_ratio = 0.0
                lower_wick_ratio = 0.0
                if df_5m is not None and len(df_5m) >= 1:
                    try:
                        last_bar = df_5m.iloc[-1]
                        b_high = float(last_bar.get("high", last_bar.get("High", 0.0)))
                        b_low = float(last_bar.get("low", last_bar.get("Low", 0.0)))
                        b_open = float(last_bar.get("open", last_bar.get("Open", 0.0)))
                        b_close = float(last_bar.get("close", last_bar.get("Close", 0.0)))
                        b_rng = max(0.01, b_high - b_low)
                        upper_wick_ratio = (b_high - max(b_open, b_close)) / b_rng
                        lower_wick_ratio = (min(b_open, b_close) - b_low) / b_rng
                    except Exception:
                        pass

                chain = get_options_chain(clean_sym)
                if not chain:
                    continue

                is_idx = clean_sym in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                # Determine canonical segment for routing and display (cached on the alert object)
                alert_segment = "FNO_INDEX" if is_idx else "FNO_STOCK"
                strike_range_pct = 0.015 if is_idx else 0.035
                min_opt_volume = 3000 if is_idx else 500
                min_oi = 10000 if is_idx else 300

                # Max allowed distance from spot to avoid deep OTM lottery traps:
                # Indices: at most 2 strike intervals from ATM (e.g. 100 pts for NIFTY/FINNIFTY, 200 pts for BANKNIFTY)
                max_strike_dist = (
                    (100.0 if clean_sym in ("NIFTY", "FINNIFTY") else (200.0 if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX") else 50.0))
                    if is_idx
                    else spot * 0.025
                )
                min_opt_price = 10.0 if is_idx else 2.0

                # Filter ATM and near-the-money contracts within tight range
                atm_contracts = [
                    c
                    for c in chain
                    if abs(getattr(c, "strike", 0.0) - spot) <= max_strike_dist
                    and getattr(c, "last_price", 0.0) >= min_opt_price
                    and getattr(c, "volume", 0) >= min_opt_volume
                ]
                # Sort ATM contracts by proximity to spot (closest to ATM first!)
                atm_contracts.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - spot))

                # Check for top volume / turnover momentum
                for c in atm_contracts:
                    vol = getattr(c, "volume", 0)
                    oi = getattr(c, "oi", 0)
                    oi_change = getattr(c, "oi_change", 0)
                    vol_oi = round(vol / max(1, oi), 2)
                    opt_ltp = float(getattr(c, "last_price", 0.0) or 0.0)
                    opt_type = getattr(c, "option_type", "")
                    strike = float(getattr(c, "strike", 0.0))
                    contract_sym = getattr(c, "symbol", f"{clean_sym}{int(strike)}{opt_type}")
                    expiry_date = getattr(c, "expiry", None)
                    lot_sz = get_lot_size(clean_sym)

                    # Liquidity significance: Ensure strike has real participation, not an illiquid ghost strike
                    if oi < min_oi:
                        continue

                    # Momentum DTE Gate: Indices demand active weekly liquidity (DTE <= 7), stocks allow front-month (DTE <= 35)
                    max_dte = 7 if is_idx else 35
                    if expiry_date:
                        try:
                            exp_str = str(expiry_date).split("T")[0].strip()
                            exp_dt = None
                            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                                try:
                                    exp_dt = datetime.strptime(exp_str, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            if exp_dt and (exp_dt - datetime.now(IST).date()).days > max_dte:
                                continue
                        except Exception:
                            pass

                    # Momentum criteria: active turnover (vol_oi >= 1.0) and volume >= threshold
                    if vol_oi < 1.0:
                        continue

                    # 1. Bid/Ask Spread Sanity Gate: Avoid illiquid traps with huge bid-ask gaps (> 35%)
                    bid = getattr(c, "bid", None)
                    ask = getattr(c, "ask", None)
                    if bid and ask and bid > 0 and ask > 0 and ask > bid * 1.35:
                        continue

                    # 2. Strict Directional Price Expansion & Underlying Trend Alignment:
                    # An option momentum breakout MUST have positive price expansion (gainers, not decaying/dumping)
                    # AND the underlying stock must be aligned with the trade direction.
                    pchange = getattr(c, "pchange", None)
                    if opt_type == "CE":
                        # CALL SURGE: Option premium must be expanding positively
                        if pchange is not None and pchange < 2.0:
                            continue
                        # Underlying stock must NOT be collapsing in a severe downtrend (reject crashing stocks like MAZDOCK)
                        if spot_change_pct is not None and spot_change_pct < -2.0:
                            continue
                        if spot_open and spot_open > 0 and spot < spot_open * 0.98:
                            continue
                        # Spot must hold intraday VWAP (reject buying calls below VWAP)
                        if spot_vwap and spot_vwap > 0 and spot < spot_vwap * 0.998:
                            continue
                        # Upper-wick rejection / buying climax gate (reject false breakouts/sweeps)
                        if upper_wick_ratio > 0.35:
                            continue
                        direction = "BULLISH"
                    elif opt_type == "PE":
                        # PUT SURGE: Option premium must be expanding positively
                        if pchange is not None and pchange < 2.0:
                            continue
                        # Underlying stock must NOT be surging in a severe uptrend
                        if spot_change_pct is not None and spot_change_pct > 2.0:
                            continue
                        if spot_open and spot_open > 0 and spot > spot_open * 1.02:
                            continue
                        # Spot must be below intraday VWAP (reject buying puts above VWAP)
                        if spot_vwap and spot_vwap > 0 and spot > spot_vwap * 1.002:
                            continue
                        # Lower-wick rejection / selling climax gate (reject hammer rejections)
                        if lower_wick_ratio > 0.35:
                            continue
                        direction = "BEARISH"
                    else:
                        continue

                    # 2b. MTF Confluence on Underlying Spot (15m OHLCV)
                    mtf_15m_trend = "NEUTRAL"
                    try:
                        from market.history import get_ohlcv
                        df_15m = get_ohlcv(clean_sym, days=4, interval="15minute")
                        if df_15m is not None and len(df_15m) >= 15:
                            c_15 = df_15m["close"] if "close" in df_15m.columns else df_15m["Close"]
                            ema20_15 = float(c_15.ewm(span=20, adjust=False).mean().iloc[-1])
                            ema50_15 = float(c_15.ewm(span=50, adjust=False).mean().iloc[-1]) if len(c_15) >= 40 else ema20_15
                            if spot >= (ema20_15 * 0.998) and ema20_15 >= (ema50_15 * 0.998):
                                mtf_15m_trend = "BULLISH"
                            elif spot <= (ema20_15 * 1.002) and ema20_15 <= (ema50_15 * 1.002):
                                mtf_15m_trend = "BEARISH"
                    except Exception as e_mtf:
                        logger.debug(f"[AutoAlertEngine] MTF 15m fetch failed for {clean_sym}: {e_mtf}")

                    # Reject counter-trend breakout traps against 15m structural trend
                    if opt_type == "CE" and mtf_15m_trend == "BEARISH":
                        logger.debug(f"[AutoAlertEngine] Suppressed Call breakout on {clean_sym}: 15m trend is BEARISH")
                        continue
                    if opt_type == "PE" and mtf_15m_trend == "BULLISH":
                        logger.debug(f"[AutoAlertEngine] Suppressed Put surge on {clean_sym}: 15m trend is BULLISH")
                        continue

                    # 2c. Options Delta-OI Institutional Confirmation Gate:
                    # For Calls: If Call writers are aggressively stacking fresh OI while spot is below VWAP,
                    # this is an institutional Call Writing Resistance Wall, NOT a bullish breakout!
                    is_gamma_squeeze = False
                    if opt_type == "CE":
                        if oi_change and oi_change < 0:
                            is_gamma_squeeze = True  # Call short covering
                        elif oi_change and oi_change > 0 and spot_vwap and spot < spot_vwap:
                            logger.debug(f"[AutoAlertEngine] Suppressed CE on {clean_sym}: Call writing resistance wall (OI +{oi_change} below VWAP)")
                            continue
                    elif opt_type == "PE":
                        if oi_change and oi_change < 0:
                            is_gamma_squeeze = True  # Put short covering / long liquidation

                    # 2d. India VIX Volatility Regime Adaptation
                    vix_val = None
                    try:
                        from market.indices import get_vix
                        vix_val = get_vix()
                    except Exception:
                        vix_val = None

                    if vix_val and vix_val > 0:
                        if vix_val < 12.0:
                            vix_regime = "LOW_VOLATILITY"
                        elif vix_val <= 18.0:
                            vix_regime = "NORMAL_VOLATILITY"
                        elif vix_val <= 24.0:
                            vix_regime = "ELEVATED_VOLATILITY"
                        else:
                            vix_regime = "EXTREME_VOLATILITY"
                    else:
                        vix_regime = "NORMAL_VOLATILITY"

                    alert_id = f"aa-optmom-{opt_type.lower()}-{clean_sym}-{int(strike)}-{uuid.uuid4().hex[:6]}"

                    # 3. Dynamic Spot-Anchored Trade Plan & Invalidation (Institutional Greeks)
                    tp = None
                    opt_plan = None
                    try:
                        from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan
                        tp = calculate_trade_plan(
                            symbol=clean_sym,
                            direction="BUY" if opt_type == "CE" else "SELL",
                            spot=spot,
                            timeframe="INTRADAY",
                            exchange="NFO",
                            has_active_blast=(vol_oi >= 2.0),
                        )
                        if tp and tp.invalidation_stop > 0:
                            opt_plan = calculate_option_execution_plan(
                                trade_plan=tp,
                                option_type=opt_type,
                                strike=strike,
                                expiry=str(expiry_date) if expiry_date else "",
                                option_ltp=opt_ltp,
                                lot_size=lot_sz,
                            )
                    except Exception as e_tp:
                        logger.debug(f"[OptionsBreakout] Trade plan calculation failed: {e_tp}")

                    if opt_plan and opt_plan.get("sl_premium") and opt_plan.get("t1_premium"):
                        opt_sl = float(opt_plan["sl_premium"])
                        opt_t1 = float(opt_plan["t1_premium"])
                        # Enforce defined risk tight stop for Options Momentum (cap risk at 15% of premium to honor small SL):
                        max_opt_sl_risk = round(opt_ltp * 0.15, 2)
                        opt_sl = max(opt_sl, round(opt_ltp - max_opt_sl_risk, 2))
                        opt_risk = max(0.2, opt_ltp - opt_sl)
                        opt_t1 = max(opt_t1, round(opt_ltp + 2.5 * opt_risk, 2))
                        opt_t2 = float(opt_plan.get("t2_premium") or round(opt_ltp + 4.0 * opt_risk, 2))
                        opt_moonshot = float(opt_plan.get("t3_premium") or round(opt_ltp + 6.0 * opt_risk, 2))
                        rr_str = str(opt_plan.get("option_rr") or f"1:{round((opt_t1 - opt_ltp) / opt_risk, 1)}")
                    else:
                        # Tight structural defined risk stop (10%–14% risk instead of arbitrary 25%)
                        risk_pts = round(max(0.20, min(opt_ltp * 0.12, opt_ltp - 0.05)), 2)
                        opt_sl = round(max(0.05, opt_ltp - risk_pts), 2)
                        opt_t1 = round(opt_ltp + 2.5 * risk_pts, 2)
                        opt_t2 = round(opt_ltp + 4.0 * risk_pts, 2)
                        opt_moonshot = round(opt_ltp + 6.0 * risk_pts, 2)
                        rr_str = "1:2.5"

                    # 4. Friday Session Clock & Weekend Theta Decay Filter
                    friday_tag = " ⚠️ FRIDAY POST-14:30: Weekend theta decay risk; Intraday Quick Scalp only (Square off by 15:20 IST) or trade Bull Call Spread." if is_friday_late else ""

                    # 5. Multi-factor Institutional Conviction Scoring (0-95, replaces naive 72 + vol_oi * 8)
                    conf_score = 65
                    conf_score += min(15, int(vol_oi * 3.5))
                    if opt_type == "CE" and spot_vwap and spot >= spot_vwap:
                        conf_score += 10
                    elif opt_type == "PE" and spot_vwap and spot <= spot_vwap:
                        conf_score += 10
                    if tp and tp.is_asymmetry_viable:
                        conf_score += 10
                    if upper_wick_ratio <= 0.20 and lower_wick_ratio <= 0.20:
                        conf_score += 5
                    if is_gamma_squeeze:
                        conf_score += 8
                    elif oi_change and oi_change < 0:
                        conf_score += 5
                    if mtf_15m_trend == ("BULLISH" if opt_type == "CE" else "BEARISH"):
                        conf_score += 7
                    confidence = min(94, max(72, conf_score))

                    # 6. Optimal Trade Entry (OTE) & Strict No-Chase Boundaries
                    ote_lower = round(max(0.05, opt_ltp * 0.96), 1)
                    ote_upper = round(opt_ltp * 1.01, 1)
                    max_chase = round(opt_ltp * 1.08, 1)
                    entry_range_str = f"₹{ote_lower:,.1f} – ₹{ote_upper:,.1f}"
                    when_to_wait_str = f"DO NOT CHASE if premium surges > 8% past entry (> ₹{max_chase:,.1f}). Wait for 5m consolidation retest."
                    spot_anchor_str = f" (Spot Anchor: ₹{tp.invalidation_stop:,.1f})" if (tp and tp.invalidation_stop > 0) else ""
                    when_to_buy_str = f"Buy on ask/limit within entry range with spot invalidation anchor at ₹{tp.invalidation_stop:,.1f} (Option SL ₹{opt_sl:,.1f})." if (tp and tp.invalidation_stop > 0) else f"Buy on ask/limit within entry range with tight defined risk below ₹{opt_sl:,.1f}."

                    if opt_type == "PE":
                        headline = f"🎯 OPTIONS MOMENTUM (PUT SURGE): {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
                        summary = (
                            f"Institutional Put surge in {clean_sym} {strike:,.0f} PE. "
                            f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} | T2: ₹{opt_t2:,.1f}.{friday_tag}"
                        )
                    else:
                        headline = f"🚀 OPTIONS MOMENTUM: {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
                        summary = (
                            f"Institutional Call surge in {clean_sym} {strike:,.0f} CE. "
                            f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} | T2: ₹{opt_t2:,.1f}.{friday_tag}"
                        )

                    alert = AutoAlert(
                        alert_id=alert_id,
                        alert_type="OPTIONS_MOMENTUM",
                        stage="IGNITED" if vol_oi >= 2.0 else "EARLY_WARNING",
                        symbol=clean_sym,
                        exchange="NFO",
                        direction=direction,
                        headline=headline,
                        summary=summary,
                        ltp=opt_ltp,
                        trigger_level=opt_ltp,
                        target_level=opt_t1,
                        stop_loss=opt_sl,
                        strike=strike,
                        option_type=opt_type,
                        contract_symbol=contract_sym,
                        expiry_date=expiry_date,
                        expiry_type=classify_expiry_type(expiry_date, clean_sym),
                        segment=alert_segment,
                        option_premium=opt_ltp,
                        underlying_spot=spot,
                        confidence=confidence,
                        created_at=now_iso,
                        is_live=True,
                        environment="LIVE",
                        mtf_confluence=mtf_15m_trend,
                        vix_regime=vix_regime,
                        metrics={
                            "vol_oi_ratio": vol_oi,
                            "volume": vol,
                            "oi": oi,
                            "oi_change": oi_change,
                            "spot": spot,
                            "strike": strike,
                            "lot_size": lot_sz,
                            "spot_vwap": spot_vwap,
                            "spot_invalidation_anchor": tp.invalidation_stop if tp else None,
                            "spot_target_1": tp.target_1 if tp else None,
                            "spot_target_2": tp.target_2 if tp else None,
                            "upper_wick_ratio": round(upper_wick_ratio, 2),
                            "lower_wick_ratio": round(lower_wick_ratio, 2),
                            "is_friday_late": is_friday_late,
                            "mtf_15m_trend": mtf_15m_trend,
                            "vix_regime": vix_regime,
                            "india_vix": vix_val,
                            "is_gamma_squeeze": is_gamma_squeeze,
                        },
                        actionable_plan={
                            "action": f"BUY {opt_type}",
                            "segment": "FNO",
                            "contract": contract_sym,
                            "recommended_entry": f"₹{opt_ltp:,.2f}",
                            "entry_range": entry_range_str,
                            "stop_loss": f"₹{opt_sl:,.1f}",
                            "target_1": f"₹{opt_t1:,.1f}",
                            "target": f"₹{opt_t1:,.1f}",
                            "target_2": f"₹{opt_t2:,.1f}",
                            "target_moonshot": f"₹{opt_moonshot:,.1f}",
                            "risk_reward": rr_str,
                            "when_to_buy": when_to_buy_str,
                            "when_to_wait": when_to_wait_str,
                            "profit_rule": f"Book 50% at T1 (₹{opt_t1:,.1f}), move SL to Cost, let remainder ride to T2 (₹{opt_t2:,.1f}).",
                            "lot_size": lot_sz,
                            "spot_invalidation_anchor": f"₹{tp.invalidation_stop:,.1f}" if (tp and tp.invalidation_stop > 0) else None,
                            "friday_weekend_warning": friday_tag.strip() if friday_tag else None,
                        },
                    )
                    if self.record_alert(alert):
                        found.append(alert)
                        break  # 1 best contract per underlying per scan cycle
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Options momentum scan error for {sym}: {e}")

        return found

    # ── Time-Partitioned Segment Scanning Loops ──────────────────

    def scan_equity_nfo_now(self) -> list[AutoAlert]:
        """Runs all daytime Equity and NFO derivative detectors (09:15 - 15:30 IST)."""
        results: list[AutoAlert] = []
        results.extend(self.scan_gamma_blasts())
        results.extend(self.scan_options_momentum_breakouts())
        results.extend(self.scan_squeeze_breakouts())
        results.extend(self.scan_circuits())
        results.extend(self.scan_pattern_coilings())
        results.extend(self.scan_precursor_radars())
        results.extend(self.scan_intraday_mover_sparks())
        results.extend(self.scan_asymmetric_opportunities())
        return results

    def scan_post_market_digest(self) -> list[AutoAlert]:
        """
        Runs curated EOD post-market watchlist scans (0-token deterministic screening).
        Surfaces high-conviction positional swing setups for the next trading session:
          - Precursor Radars (VCP, Stage 2 breakouts, delivery accumulation)
          - Asymmetric Opportunities (1:3+ R:R at structural support)
          - Squeeze Breakouts (Daily TTM Squeeze coiling)
        Excludes closed intraday options chains and circuit proximity checks.
        """
        results: list[AutoAlert] = []
        results.extend(self.scan_precursor_radars())
        results.extend(self.scan_asymmetric_opportunities())
        results.extend(self.scan_squeeze_breakouts())
        return results

    def scan_commodities_now(self) -> list[AutoAlert]:
        """
        Scans liquid MCX commodities (Crude Oil, Gold, Silver, Natural Gas, Copper)
        for high-asymmetry session breakouts, VWAP reclaims, and US session volatility expansion.
        Active during post-equity session (15:30 - 23:30 IST).
        """
        from market.quotes import get_quote

        found: list[AutoAlert] = []
        universe = self.watched_commodities
        formatted = [f"MCX:{s}" if ":" not in s else s for s in universe]
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Commodity quotes fetch error: {e}")
            return found

        for sym in universe:
            clean_sym = sym.upper().replace("MCX:", "").strip()
            q = quotes_map.get(f"MCX:{clean_sym}") or quotes_map.get(clean_sym)
            if not q:
                continue

            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            if ltp <= 0:
                continue

            chg = float(getattr(q, "change_pct", 0.0) or 0.0)
            vol = int(getattr(q, "volume", 0) or 0)
            # 1. Sanitize VWAP: discard corrupted/mock zero or sub-50% values
            raw_vwap = getattr(q, "vwap", None)
            try:
                vwap = (
                    float(raw_vwap)
                    if (raw_vwap is not None and float(raw_vwap) > (ltp * 0.5))
                    else ltp
                )
            except Exception:
                vwap = ltp

            # Check Learning Engine Lockout first (Kill repetitive invalidation loops)
            from engine.learning_engine import pattern_learning_engine
            is_locked_bull, _ = pattern_learning_engine.is_symbol_locked_out(
                clean_sym, direction="BULLISH", ltp=ltp, vwap=vwap
            )
            is_locked_bear, _ = pattern_learning_engine.is_symbol_locked_out(
                clean_sym, direction="BEARISH", ltp=ltp, vwap=vwap
            )

            # Minimum move threshold for commodity trigger (0.6% for Gold/Silver/Copper, 1.0% for Crude/NatGas)
            min_chg = 1.0 if clean_sym in ("CRUDEOIL", "NATURALGAS") else 0.6

            # 20-Bar Donchian Channel Breakout & Wick Rejection Verification on 5m OHLCV
            df_5m = None
            try:
                from market.history import get_ohlcv
                df_5m = get_ohlcv(clean_sym, exchange="MCX", interval="5minute", days=2)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Error fetching 5m OHLCV for MCX:{clean_sym}: {e}")

            is_bullish = False
            is_bearish = False
            is_donchian_breakout = False

            if df_5m is not None and len(df_5m) >= 20:
                recent_20 = df_5m.iloc[-21:-1]
                prior_high = float(recent_20["high"].max())
                prior_low = float(recent_20["low"].min())
                last_bar = df_5m.iloc[-1]
                cur_open = float(last_bar.get("open", ltp))
                cur_high = max(float(last_bar.get("high", ltp)), ltp)
                cur_low = min(float(last_bar.get("low", ltp)), ltp)
                bar_range = max(1.0, cur_high - cur_low)

                upper_wick_ratio = (cur_high - max(cur_open, ltp)) / bar_range
                lower_wick_ratio = (min(cur_open, ltp) - cur_low) / bar_range

                # Bullish: breaking 20-bar high, small upper wick (no shooting star rejection), holding above VWAP
                if (
                    not is_locked_bull
                    and chg >= min_chg
                    and ltp >= prior_high * 0.999
                    and upper_wick_ratio <= 0.35
                    and ltp >= vwap * 0.998
                ):
                    is_bullish = True
                    is_donchian_breakout = True

                # Bearish: breaking 20-bar low, small lower wick (no hammer absorption), trading below VWAP
                elif (
                    not is_locked_bear
                    and chg <= -min_chg
                    and ltp <= prior_low * 1.001
                    and lower_wick_ratio <= 0.35
                    and ltp <= vwap * 1.002
                ):
                    is_bearish = True
                    is_donchian_breakout = True
            else:
                # Fallback when historical 5m bars are unavailable:
                # Enforce stricter move threshold and clear VWAP separation
                strict_min_chg = max(min_chg * 1.5, 1.2)
                has_real_vwap_diff = (vwap > 0) and (abs(ltp - vwap) >= 2.0)
                if has_real_vwap_diff:
                    is_bullish = not is_locked_bull and (chg >= strict_min_chg) and (ltp >= (vwap * 0.998))
                    is_bearish = not is_locked_bear and (chg <= -strict_min_chg) and (ltp <= (vwap * 1.002))
                else:
                    is_bullish = not is_locked_bull and (chg >= strict_min_chg)
                    is_bearish = not is_locked_bear and (chg <= -strict_min_chg)

            if not (is_bullish or is_bearish):
                continue

            # 2. Calibrated Intraday Commodity Stop Loss Risk (Points)
            # Intraday commodities require nimble, structural risk aligned with live contract CMP:
            # - CRUDEOIL (₹9,700): 18-35 pts (~0.35% = ₹1,800 to ₹3,500 risk per 100-bbl lot)
            # - NATURALGAS (₹270): 2.0-4.5 pts (~1.0% = ₹2,500 to ₹5,625 risk per 1250-MMBtu lot)
            # - GOLD (₹1,52,400): 250-650 pts (~0.25% = ₹25,000 to ₹65,000 per 1-kg lot, ₹2,500 to ₹6,500 per GoldM)
            # - SILVER (₹2,46,700): 600-1500 pts (~0.30% = ₹18,000 to ₹45,000 per 30-kg lot)
            # - COPPER (₹1,375): 3.0-7.5 pts (~0.4% = ₹7,500 to ₹18,750 per 2500-kg lot)
            intraday_risk_map = {
                "CRUDEOIL": max(18.0, min(35.0, round(ltp * 0.0035, 1))),
                "CRUDEOILM": max(18.0, min(35.0, round(ltp * 0.0035, 1))),
                "NATURALGAS": max(2.0, min(4.5, round(ltp * 0.010, 1))),
                "NATGASMINI": max(2.0, min(4.5, round(ltp * 0.010, 1))),
                "GOLD": max(250.0, min(650.0, round(ltp * 0.0025, 0))),
                "GOLDM": max(250.0, min(650.0, round(ltp * 0.0025, 0))),
                "SILVER": max(600.0, min(1500.0, round(ltp * 0.0030, 0))),
                "SILVERM": max(600.0, min(1500.0, round(ltp * 0.0030, 0))),
                "COPPER": max(3.0, min(7.5, round(ltp * 0.0040, 1))),
            }
            risk_pts = intraday_risk_map.get(clean_sym, round(max(5.0, ltp * 0.0035), 1))
            atr = risk_pts
            direction = "BULLISH" if is_bullish else "BEARISH"
            alert_type = "COMMODITY_MOMENTUM"
            alert_id = f"comm-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"

            # Contract lot sizes: Standard GOLD = 100 (1 kg = 100 x 10g units), GOLDM = 10 (100g)
            lot_map = {
                "CRUDEOIL": 100,
                "GOLD": 100,
                "GOLDM": 10,
                "SILVER": 30,
                "SILVERM": 5,
                "NATURALGAS": 1250,
                "COPPER": 2500,
            }
            lot_sz = lot_map.get(clean_sym, 1)

            has_real_vwap = abs(ltp - vwap) >= 2.0 and vwap != ltp
            if is_bullish:
                sl_price = round(ltp - risk_pts, 2)
                t1_price = round(ltp + 1.8 * risk_pts, 2)
                t2_price = round(ltp + 3.2 * risk_pts, 2)
                if is_donchian_breakout:
                    headline = f"🛢️ MCX BREAKOUT: {clean_sym} +{chg:.1f}% Breaking 20-bar High (₹{ltp:,.1f})"
                    summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). 20-bar 5m Donchian high broken with VWAP support at ₹{vwap:,.1f}."
                elif has_real_vwap:
                    headline = (
                        f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Reclaiming VWAP (₹{vwap:,.1f})"
                    )
                    summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). VWAP support at ₹{vwap:,.1f}."
                else:
                    headline = f"MCX MOMENTUM: {clean_sym} +{chg:.1f}% Breakout @ ₹{ltp:,.1f}"
                    summary = f"Institutional breakout in {clean_sym}: Trading at ₹{ltp:,.1f} (+{chg:.1f}%). Session momentum active."
                action = "BUY_FUTURES"
            else:
                sl_price = round(ltp + risk_pts, 2)
                t1_price = round(ltp - 1.8 * risk_pts, 2)
                t2_price = round(ltp - 3.2 * risk_pts, 2)
                if is_donchian_breakout:
                    headline = f"🛢️ MCX BREAKDOWN: {clean_sym} {chg:.1f}% Breaking 20-bar Low (₹{ltp:,.1f})"
                    summary = f"Institutional breakdown in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). 20-bar 5m Donchian low broken below VWAP ₹{vwap:,.1f}."
                elif has_real_vwap:
                    headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Lost VWAP (₹{vwap:,.1f})"
                    summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Broken below VWAP ₹{vwap:,.1f}."
                else:
                    headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Drop @ ₹{ltp:,.1f}"
                    summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Session selling active."
                action = "SELL_SHORT_FUTURES"

            # 3. Resolve defined-risk options contract alternative (ATM/near-OTM Call/Put)
            # Scale option stop loss by Delta (~0.50) so option risk matches the futures invalidation
            opt_recommendation = None
            try:
                from market.options import get_options_chain

                chain = get_options_chain(clean_sym)
                opt_type = "CE" if is_bullish else "PE"
                filtered = [c for c in chain if c.option_type == opt_type and c.last_price > 0]
                if filtered:
                    closest_opt = min(filtered, key=lambda c: abs(c.strike - ltp))
                    opt_prem = closest_opt.last_price
                    # Scale option risk to underlying futures riskpts (Delta approx 0.50)
                    opt_risk = round(max(1.0, min(opt_prem * 0.35, risk_pts * 0.52)), 1)
                    opt_t1 = round(opt_prem + 1.8 * opt_risk, 1)
                    opt_t2 = round(opt_prem + 3.2 * opt_risk, 1)
                    opt_recommendation = {
                        "contract": closest_opt.symbol,
                        "strike": closest_opt.strike,
                        "option_type": opt_type,
                        "ltp": opt_prem,
                        "stop_loss": round(max(0.05, opt_prem - opt_risk), 1),
                        "target_1": opt_t1,
                        "target_2": opt_t2,
                        "risk_reward": "1:2.4",
                        "max_loss_capped": round(opt_prem * lot_sz, 0),
                    }
            except Exception:
                opt_recommendation = None

            # Bounded Entry Range: strictly clamped within Stop-Loss and Target 1
            rr_ratio_t1 = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
            if is_bullish:
                e_low = round(max(sl_price + 0.5, ltp - 0.25 * risk_pts), 1)
                e_high = round(min(t1_price - 0.25 * risk_pts, ltp + 0.25 * risk_pts), 1)
            else:
                e_high = round(min(sl_price - 0.5, ltp + 0.25 * risk_pts), 1)
                e_low = round(max(t1_price + 0.25 * risk_pts, ltp - 0.25 * risk_pts), 1)

            plan_dict = {
                "action": action,
                "segment": "COMMODITY",
                "contract": f"MCX:{clean_sym}",
                "entry_range": f"₹{e_low:,.1f} – ₹{e_high:,.1f}",
                "stop_loss": f"₹{sl_price:,.1f}",
                "target": f"₹{t1_price:,.1f}",
                "target_2": f"₹{t2_price:,.1f}",
                "risk_reward": f"1:{rr_ratio_t1}",
                "lot_size": lot_sz,
                "when_to_buy": f"Enter on 5m candle closing in direction above/below VWAP ₹{vwap:,.1f}.",
                "when_to_wait": f"Do not chase if move exceeds {round(abs(chg) + 1.0, 1)}%.",
                "profit_rule": "Book 50% at T1, trail stop to cost, let runner target T2.",
            }
            if opt_recommendation:
                plan_dict["option_alternative"] = opt_recommendation

            # Strict Data Provenance Gate: Verify if quote is authentic live broker data vs synthetic/mock
            is_mock_quote = (
                type(q).__name__ == "MagicMock"
                or getattr(q, "_is_mock", False)
                or getattr(q, "provider", "") in ("mock", "TEST")
                or getattr(q, "data_state", "") == "UNAVAILABLE"
            )
            is_test_env = (
                os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test"
            )
            is_authentic_live = not (is_mock_quote or is_test_env)

            from engine.trade_plan import get_market_status

            mcx_status_dict = get_market_status("MCX")
            mcx_status = mcx_status_dict.get("status", "LIVE")

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED" if abs(chg) >= (min_chg * 1.5) else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="MCX",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=min(95, int(75 + abs(chg) * 6)),
                created_at=now_iso,
                is_live=is_authentic_live,
                environment="LIVE" if is_authentic_live else "TEST",
                market_status=mcx_status,
                metrics={
                    "change_pct": chg,
                    "volume": vol,
                    "vwap": vwap,
                    "atr": atr,
                    "lot_size": lot_sz,
                    "segment": "COMMODITY",
                    "has_options_chain": bool(opt_recommendation),
                },
                actionable_plan=plan_dict,
            )
            if self.record_alert(alert):
                found.append(alert)

        return found

    def scan_currency_now(self) -> list[AutoAlert]:
        """
        Scans liquid Currency pairs (USDINR, EURINR, GBPINR) for post-equity breakouts.
        Active during post-equity session (15:30 - 17:00 IST).
        """
        from market.quotes import get_quote

        found: list[AutoAlert] = []
        universe = self.watched_currencies
        formatted = [f"CDS:{s}" if ":" not in s else s for s in universe]
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Currency quotes fetch error: {e}")
            return found

        for sym in universe:
            clean_sym = sym.upper().replace("CDS:", "").strip()
            q = quotes_map.get(f"CDS:{clean_sym}") or quotes_map.get(clean_sym)
            if not q:
                continue

            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            if ltp <= 0:
                continue

            chg = float(getattr(q, "change_pct", 0.0) or 0.0)
            # Significant currency move threshold (>= 0.10% is a multi-tick macro expansion)
            if abs(chg) < 0.10:
                continue

            is_bullish = chg > 0
            direction = "BULLISH" if is_bullish else "BEARISH"
            alert_type = "CURRENCY_BREAKOUT"
            alert_id = f"curr-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"

            # Currency standard risk: 0.08 to 0.12 paise
            risk_rupees = round(max(0.08, ltp * 0.0012), 4)
            if is_bullish:
                sl_price = round(ltp - risk_rupees, 4)
                t1_price = round(ltp + 1.8 * risk_rupees, 4)
                t2_price = round(ltp + 3.0 * risk_rupees, 4)
                headline = f"💱 CURRENCY BREAKOUT: {clean_sym} +{chg:.2f}% @ ₹{ltp:.4f}"
                summary = f"Macro currency surge in {clean_sym}: Moving +{chg:.2f}% to ₹{ltp:.4f}. Long thesis active."
                action = "BUY_FUTURES"
            else:
                sl_price = round(ltp + risk_rupees, 4)
                t1_price = round(ltp - 1.8 * risk_rupees, 4)
                t2_price = round(ltp - 3.0 * risk_rupees, 4)
                headline = f"💱 CURRENCY BREAKDOWN: {clean_sym} {chg:.2f}% @ ₹{ltp:.4f}"
                summary = f"Macro currency drop in {clean_sym}: Moving {chg:.2f}% to ₹{ltp:.4f}. Short thesis active."
                action = "SELL_SHORT_FUTURES"

            # Strict Data Provenance Gate: Verify if quote is authentic live broker data vs synthetic/mock
            is_mock_quote = (
                type(q).__name__ == "MagicMock"
                or getattr(q, "_is_mock", False)
                or getattr(q, "provider", "") in ("mock", "TEST")
                or getattr(q, "data_state", "") == "UNAVAILABLE"
            )
            is_test_env = (
                os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test"
            )
            is_authentic_live = not (is_mock_quote or is_test_env)

            from engine.trade_plan import get_market_status

            cds_status_dict = get_market_status("CDS")
            cds_status = cds_status_dict.get("status", "LIVE")

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED" if abs(chg) >= 0.20 else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="CDS",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=min(92, int(75 + abs(chg) * 30)),
                created_at=now_iso,
                is_live=is_authentic_live,
                environment="LIVE" if is_authentic_live else "TEST",
                market_status=cds_status,
                metrics={
                    "change_pct": chg,
                    "segment": "CURRENCY",
                    "lot_size": 1000,
                },
                actionable_plan={
                    "action": action,
                    "segment": "CURRENCY",
                    "contract": f"CDS:{clean_sym}",
                    "entry_range": f"₹{round(ltp - 0.02, 4):.4f} – ₹{round(ltp + 0.02, 4):.4f}",
                    "stop_loss": f"₹{sl_price:.4f}",
                    "target": f"₹{t1_price:.4f}",
                    "target_2": f"₹{t2_price:.4f}",
                    "risk_reward": "1:2.2",
                    "lot_size": 1000,
                    "when_to_buy": "Execute on order book spread with defined risk below SL.",
                    "when_to_wait": "Do not chase if spread widens > 0.05 paise.",
                    "profit_rule": "Scale 50% at T1, move SL to entry.",
                },
            )
            if self.record_alert(alert):
                found.append(alert)

        return found

    def scan_fresh_signals_now(self, segment: str = "AUTO") -> list[AutoAlert]:
        """
        Scans watched universe for fresh market signals across detectors.
        segment: 'AUTO' (matches active IST session) | 'EQUITY' | 'COMMODITY' | 'CURRENCY' | 'ALL'
        """
        results: list[AutoAlert] = []
        seg = (segment or "AUTO").upper()

        if seg == "ALL":
            results.extend(self.scan_equity_nfo_now())
            results.extend(self.scan_commodities_now())
            results.extend(self.scan_currency_now())
            return results

        if seg in ("EQUITY", "NFO"):
            return self.scan_equity_nfo_now()
        if seg in ("COMMODITY", "MCX"):
            return self.scan_commodities_now()
        if seg in ("CURRENCY", "CDS"):
            return self.scan_currency_now()

        # Default AUTO: respect strict time-partitioned operational session
        session = get_current_ist_session()
        if session["equity_nfo"]:
            results.extend(self.scan_equity_nfo_now())
        if session["currency"]:
            results.extend(self.scan_currency_now())
        if session["commodity"]:
            results.extend(self.scan_commodities_now())

        # If completely outside all market hours, run curated post-market swing digest
        if not (session["equity_nfo"] or session["currency"] or session["commodity"]):
            results.extend(self.scan_post_market_digest())

        return results

    def scan_all_now(self, segment: str = "AUTO") -> list[AutoAlert]:
        """Executes full diagnostic scan across all detectors and returns new alerts."""
        session = get_current_ist_session()
        active_exchanges: list[str] = []
        if session["equity_nfo"]:
            active_exchanges.extend(["NSE", "BSE", "NFO"])
        if session["currency"]:
            active_exchanges.append("CDS")
        if session["commodity"]:
            active_exchanges.append("MCX")

        # 1. Check invalidations on existing alerts first
        self.check_and_alert_invalidations(exchanges=active_exchanges or None)
        # 2. Check in-flight decay & danger zones on existing alerts
        self.check_and_alert_in_flight_decay(exchanges=active_exchanges or None)
        # 3. Check target milestones & trailing stop updates on existing alerts
        self.check_and_alert_targets_and_trailing(exchanges=active_exchanges or None)
        # 4. Check for fresh market signals
        return self.scan_fresh_signals_now(segment=segment)

    # ── Daemon Thread Poller ────────────────────────────────────

    def start_polling(self, interval_seconds: int = 45) -> None:
        """Starts background evaluation loop."""
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._poller_thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds,),
            name="AutoAlertEnginePoller",
            daemon=True,
        )
        self._poller_thread.start()
        logger.info(f"[AutoAlertEngine] Background poller started (interval={interval_seconds}s)")

    def stop_polling(self) -> None:
        """Stops background loop cleanly."""
        self._is_running = False
        self._stop_event.set()
        if self._poller_thread and self._poller_thread.is_alive():
            try:
                self._poller_thread.join(timeout=1.5)
            except Exception:
                pass
        self._poller_thread = None
        logger.info("[AutoAlertEngine] Background poller stopped cleanly")

    def _run_loop(self, interval: int) -> None:
        last_cleanup_time = 0.0
        while self._is_running and not self._stop_event.is_set():
            try:
                now_loop = time.time()
                # Periodic cleanup of archived records older than 3 days (run once every 30 minutes)
                if (now_loop - last_cleanup_time) > 1800.0:
                    self.cleanup_archived_records(max_age_days=3)
                    last_cleanup_time = now_loop

                session = get_current_ist_session()

                from engine.alert_preferences import alert_preferences

                # Phase 1: Pure Domestic Equity & NFO Desk (09:15 - 15:30 IST)
                if session["equity_nfo"] and not (
                    alert_preferences.is_segment_globally_disabled("EQUITY")
                    and alert_preferences.is_segment_globally_disabled("FNO")
                ):
                    self.check_and_alert_invalidations(exchanges=["NSE", "BSE", "NFO"])
                    self.check_and_alert_in_flight_decay(exchanges=["NSE", "BSE", "NFO"])
                    self.check_and_alert_targets_and_trailing(exchanges=["NSE", "BSE", "NFO"])
                    self.scan_equity_nfo_now()

                # Phase 2: Currency Desk (15:30 - 17:00 IST strictly post-equity)
                if session["currency"] and not alert_preferences.is_segment_globally_disabled("CURRENCY"):
                    self.check_and_alert_invalidations(exchanges=["CDS"])
                    self.check_and_alert_in_flight_decay(exchanges=["CDS"])
                    self.check_and_alert_targets_and_trailing(exchanges=["CDS"])
                    self.scan_currency_now()

                # Phase 3: MCX Commodities Desk (15:30 - 23:30 IST strictly post-equity)
                if session["commodity"] and not alert_preferences.is_segment_globally_disabled("COMMODITY"):
                    self.check_and_alert_invalidations(exchanges=["MCX"])
                    self.check_and_alert_in_flight_decay(exchanges=["MCX"])
                    self.check_and_alert_targets_and_trailing(exchanges=["MCX"])
                    self.scan_commodities_now()

            except Exception as e:
                logger.warning(f"[AutoAlertEngine] Error in poll cycle: {e}")

            if self._stop_event.wait(timeout=interval):
                break

    # ── Query API ───────────────────────────────────────────────

    def get_alerts(
        self,
        limit: int = 50,
        alert_type: Optional[str] = None,
        stage: Optional[str] = None,
        environment: Optional[str] = None,
        is_invalidated: Optional[bool] = None,
        target_status: Optional[str] = None,
        view_mode: str = "ALL",  # "ACTIVE" | "ARCHIVED" | "ALL"
        is_archived: Optional[bool] = None,
        segment: Optional[str | list[str]] = None,
    ) -> list[AutoAlert]:
        """Returns buffered alerts with optional filtering and active/archived partitioning."""
        with self._lock:
            self._load()
            seen_ids = set()
            res = []
            for a in self._alerts:
                aid = a.alert_id or ""
                if aid and aid in seen_ids:
                    continue
                if aid:
                    seen_ids.add(aid)
                res.append(a)

        if view_mode.upper() == "ACTIVE":
            res = [a for a in res if a.is_active]
        elif view_mode.upper() == "ARCHIVED":
            res = [a for a in res if not a.is_active]

        if segment:
            from engine.alert_preferences import classify_alert_segment, normalize_segment_list

            allowed_segs = set(normalize_segment_list(segment))
            raw_tokens = [segment.upper()] if isinstance(segment, str) else [str(s).upper() for s in segment]
            if "ALL" not in raw_tokens:
                res = [
                    a
                    for a in res
                    if (getattr(a, "segment", None) or classify_alert_segment(a)).upper() in allowed_segs
                ]

        if is_archived is not None:
            res = [a for a in res if a.is_archived == is_archived]
        if alert_type:
            res = [a for a in res if a.alert_type.upper() == alert_type.upper()]
        if stage:
            res = [a for a in res if a.stage.upper() == stage.upper()]
        if environment:
            res = [a for a in res if a.environment.upper() == environment.upper()]
        if is_invalidated is not None:
            res = [a for a in res if a.is_invalidated == is_invalidated]
        if target_status:
            res = [a for a in res if a.target_status.upper() == target_status.upper()]

        return res[:limit]

    def archive_alert_by_id(
        self,
        alert_id: str,
        archive: bool = True,
        reason: Optional[str] = None,
    ) -> Optional[AutoAlert]:
        """Manually archives or unarchives an alert by ID."""
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        target_alert: Optional[AutoAlert] = None
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.is_archived = archive
                    if archive:
                        alert.archived_at = now_iso
                        alert.archive_reason = reason or "Manually archived by user"
                    else:
                        alert.archived_at = None
                        alert.archive_reason = None
                    target_alert = alert
                    break
            if target_alert:
                self._save()
        return target_alert

    def _prune_expired_archived_unlocked(self, max_age_days: int = 1) -> int:
        """
        Internal prune logic without acquiring lock (caller must hold self._lock).
        CRITICAL SAFETY RULE: Active valid trades (a.is_active == True) are NEVER purged.
        Automatically purges:
          1. Expired derivative contracts (shelf-life / expiry passed).
          2. Quarantined or bogus phantom records (instant 0-TTL purge).
          3. Inactive / archived / invalidated records older than max_age_days.
        """
        from datetime import timedelta

        now = datetime.now(IST)
        cutoff_dt = now - timedelta(days=max_age_days)
        purged_count = 0
        surviving: list[AutoAlert] = []

        for a in self._alerts:
            # Active valid trades are NEVER purged, regardless of age
            if a.is_active:
                surviving.append(a)
                continue

            # 1. Instant Purge for Expired Derivatives
            if a.is_expired or a.stage == "EXPIRED":
                purged_count += 1
                continue

            # 2. Instant Purge for Quarantined / Phantom records
            if a.archive_reason and "Quarantined" in a.archive_reason:
                purged_count += 1
                continue

            # Inactive candidate for archival cleanup: check age
            ts_str = a.invalidated_at or a.archived_at or a.created_at or ""
            alert_dt = None
            if ts_str:
                clean_ts = ts_str.replace(" IST", "").strip()
                for fmt in (
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d",
                ):
                    try:
                        alert_dt = datetime.strptime(clean_ts[:19], fmt).replace(tzinfo=IST)
                        break
                    except Exception:
                        continue

            # 3. Clean up records older than max_age_days or prior calendar session invalidations
            if alert_dt:
                if alert_dt < cutoff_dt:
                    purged_count += 1
                    continue
                if (
                    max_age_days <= 1
                    and (a.is_invalidated or a.stage == "INVALIDATED")
                    and alert_dt.date() < now.date()
                ):
                    purged_count += 1
                    continue

            surviving.append(a)

        if purged_count > 0:
            self._alerts = surviving
            self._save()
            logger.info(
                f"[AutoAlertEngine] Cleaned up {purged_count} stale/expired records. "
                f"Surviving: {len(surviving)}"
            )

        return purged_count

    def _reap_expired_alerts_unlocked(self, purge: bool = False) -> int:
        """
        Internal reap logic without acquiring lock (caller must hold self._lock).
        Scans all buffered alerts and archives or purges any derivative contract or gamma blast
        whose contract expiry date or trading shelf-life has passed.
        If purge=True, permanently removes them from memory and disk.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        if purge:
            purged = 0
            surviving: list[AutoAlert] = []
            for a in self._alerts:
                if a.is_expired or a.stage == "EXPIRED":
                    purged += 1
                else:
                    surviving.append(a)
            if purged > 0:
                self._alerts = surviving
                self._save()
                logger.info(f"[AutoAlertEngine] Permanently purged {purged} expired alerts.")
            return purged

        reaped = 0
        for a in self._alerts:
            if not a.is_archived and a.is_expired:
                a.is_archived = True
                a.archived_at = now_iso
                a.stage = "EXPIRED"
                exp_label = a.expiry_date or "weekly/intraday shelf-life passed"
                a.archive_reason = f"Contract expired ({exp_label})"
                reaped += 1
        if reaped > 0:
            self._save()
            logger.info(f"[AutoAlertEngine] Reaped {reaped} expired alerts.")
        return reaped

    def reap_expired_alerts(self, purge: bool = False) -> int:
        """
        Public thread-safe method to reap and archive (or purge) expired derivative alerts.
        Returns count of reaped/purged alerts.
        """
        with self._lock:
            return self._reap_expired_alerts_unlocked(purge=purge)

    def purge_expired_alerts(self) -> int:
        """
        Public thread-safe method to permanently purge all expired alerts from memory and disk.
        Returns count of purged alerts.
        """
        with self._lock:
            return self._reap_expired_alerts_unlocked(purge=True)

    def cleanup_corrupted_test_alerts(self) -> int:
        """
        Removes or archives synthetic test alerts that were incorrectly marked invalidated
        by live market sweeps (e.g. test-target-0893fa).
        """
        purged = 0
        with self._lock:
            surviving: list[AutoAlert] = []
            for a in self._alerts:
                if (
                    a.environment == "TEST" or not a.is_live or a.alert_id.startswith("test-")
                ) and a.is_invalidated:
                    purged += 1
                else:
                    surviving.append(a)
            if purged > 0:
                self._alerts = surviving
                self._save()
                logger.info(f"[AutoAlertEngine] Purged {purged} corrupted synthetic test alerts.")
        return purged

    def cleanup_archived_records(self, max_age_days: int = 1) -> int:
        """
        Public thread-safe method to prune archived records older than max_age_days.
        Active valid trades are never deleted.
        Returns the number of purged records.
        """
        with self._lock:
            return self._prune_expired_archived_unlocked(max_age_days=max_age_days)

    def clear_alerts(self) -> None:
        """Clears all buffered alerts, cooldown signatures, and dispatch milestone latches."""
        with self._lock:
            self._alerts.clear()
            self._cooldowns.clear()
            self._dispatched_milestones.clear()
            self._dispatch_cooldowns.clear()
            self._save()

    # ── Persistence ─────────────────────────────────────────────

    def _save(self) -> None:
        try:
            target_path = get_auto_alerts_file()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = [a.to_dict() for a in self._alerts]
            # Atomic persistence: write to sibling PID-tagged temp file then atomic replace
            payload = json.dumps(data, indent=2)
            temp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, target_path)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _save error: {e}")

    def _sanitize_legacy_alerts_unlocked(self) -> int:
        """
        Permanently purges bogus/quarantined alerts that violate newly established
        institutional quality gates (e.g. illiquid index strikes or distant gamma expiries).
        Excludes synthetic test alerts.
        """
        purged = 0
        surviving: list[AutoAlert] = []
        for a in self._alerts:
            # Skip test alerts from live index liquidity checks!
            if (
                a.environment == "TEST"
                or not a.is_live
                or a.alert_id.startswith("test-")
                or a.alert_id.startswith("vm-")
                or a.alert_id.startswith("inv-")
            ):
                surviving.append(a)
                continue

            # 1. Reject already quarantined or corrupted records
            if a.archive_reason and "Quarantined" in a.archive_reason:
                purged += 1
                logger.info(f"[AutoAlertEngine] Purged quarantined alert {a.alert_id} ({a.symbol})")
                continue

            # 2. Gate for Index GAMMA_BLAST: Must have >= 15,000 OI and <= 5 DTE
            if a.alert_type == "GAMMA_BLAST":
                is_index = a.symbol.upper() in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                if is_index:
                    oi = a.metrics.get("oi", 0) if a.metrics else 0
                    dte = a.metrics.get("dte") if a.metrics else None
                    if dte is None:
                        dte = getattr(a, "dte", None)
                    if dte is None and a.expiry_date:
                        try:
                            exp_str = str(a.expiry_date).split("T")[0].strip()
                            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                                try:
                                    exp_dt = datetime.strptime(exp_str, fmt).date()
                                    dte = (exp_dt - datetime.now(IST).date()).days
                                    break
                                except ValueError:
                                    pass
                        except Exception:
                            pass

                    if oi < 15000:
                        purged += 1
                        logger.info(
                            f"[AutoAlertEngine] Purged illiquid index gamma alert {a.alert_id} "
                            f"({a.symbol} {a.strike}): OI {oi} < 15,000"
                        )
                        continue
                    elif dte is not None and dte > 5:
                        purged += 1
                        logger.info(
                            f"[AutoAlertEngine] Purged distant gamma alert {a.alert_id} "
                            f"({a.symbol} {a.strike}): DTE {dte} > 5"
                        )
                        continue

            # 3. Gate for OPTIONS_MOMENTUM
            elif a.alert_type == "OPTIONS_MOMENTUM":
                is_index = a.symbol.upper() in (
                    "NIFTY",
                    "BANKNIFTY",
                    "FINNIFTY",
                    "MIDCPNIFTY",
                    "SENSEX",
                    "BANKEX",
                )
                if is_index:
                    oi = a.metrics.get("oi", 0) if a.metrics else 0
                    if oi < 5000:
                        purged += 1
                        logger.info(
                            f"[AutoAlertEngine] Purged illiquid option momentum alert {a.alert_id} "
                            f"({a.symbol}): OI {oi} < 5,000"
                        )
            # 4. Session Rollover Sanity: Purge unignited EARLY_WARNING alerts from prior calendar days
            ts_date = None
            if a.created_at:
                clean_ts = a.created_at.replace(" IST", "").strip()[:10]
                try:
                    ts_date = datetime.strptime(clean_ts, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if ts_date and ts_date < datetime.now(IST).date():
                if a.stage == "EARLY_WARNING":
                    purged += 1
                    logger.info(
                        f"[AutoAlertEngine] Purged stale prior-session early warning {a.alert_id} ({a.symbol})"
                    )
                    continue

            surviving.append(a)

        if purged > 0:
            self._alerts = surviving
            self._save()

        return purged

    def _deduplicate_symbols_unlocked(self) -> int:
        """
        Deduplicates alerts by symbol. If a symbol has an active setup, any dead/invalidated/archived
        iterations of that symbol are permanently purged so old zombies never linger.
        """
        active_symbols = {
            a.symbol.replace("NSE:", "").replace("NFO:", "").strip().upper()
            for a in self._alerts
            if a.is_active
        }
        surviving = []
        purged = 0
        seen_active = set()

        for a in reversed(self._alerts):
            # Skip synthetic test alerts from symbol deduplication
            is_test = (
                a.environment == "TEST"
                or not a.is_live
                or a.alert_id.startswith("test-")
                or a.alert_id.startswith("vm-")
                or a.alert_id.startswith("inv-")
                or a.alert_id.startswith("t-")
            )
            if is_test:
                surviving.append(a)
                continue

            clean_sym = a.symbol.replace("NSE:", "").replace("NFO:", "").strip().upper()
            if a.is_active:
                if clean_sym in seen_active:
                    purged += 1
                    continue
                seen_active.add(clean_sym)
                surviving.append(a)
            else:
                # If there is already an active alert for this symbol, discard old dead copies
                if clean_sym in active_symbols:
                    purged += 1
                    continue
                surviving.append(a)

        surviving.reverse()
        if purged > 0:
            self._alerts = surviving
            self._save()
            logger.info(f"[AutoAlertEngine] Deduplicated and purged {purged} stale alert copies.")
        return purged

    def _load(self) -> None:
        try:
            target_path = get_auto_alerts_file()
            if target_path.exists():
                content = target_path.read_text(encoding="utf-8").strip()
                if not content:
                    logger.debug("[AutoAlertEngine] auto_alerts.json is empty; initializing clean state.")
                    return
                try:
                    data = json.loads(content)
                except Exception as parse_err:
                    logger.warning(
                        f"[AutoAlertEngine] Corrupted auto_alerts.json detected ({parse_err}); backing up and initializing clean state."
                    )
                    try:
                        backup_path = target_path.with_name(f"{target_path.name}.corrupt.{int(time.time())}")
                        os.replace(target_path, backup_path)
                    except Exception:
                        pass
                    return
                alerts = []
                seen_ids = set()
                for d in data:
                    if isinstance(d, dict):
                        aid = d.get("alert_id", "")
                        if aid and aid in seen_ids:
                            continue
                        if aid:
                            seen_ids.add(aid)
                        alerts.append(
                            AutoAlert(
                                alert_id=d.get("alert_id", ""),
                                alert_type=d.get("alert_type", "GENERAL"),
                                stage=d.get("stage", "EARLY_WARNING"),
                                symbol=d.get("symbol", ""),
                                exchange=d.get("exchange", "NSE"),
                                direction=d.get("direction", "NEUTRAL"),
                                headline=d.get("headline", ""),
                                summary=d.get("summary", ""),
                                ltp=float(d.get("ltp", 0.0)),
                                trigger_level=float(d.get("trigger_level", 0.0)),
                                target_level=float(d.get("target_level", 0.0)),
                                stop_loss=float(d.get("stop_loss", 0.0)),
                                strike=d.get("strike"),
                                option_type=d.get("option_type"),
                                contract_symbol=d.get("contract_symbol"),
                                metrics=d.get("metrics", {}),
                                actionable_plan=d.get("actionable_plan", {}),
                                confidence=int(d.get("confidence", 75)),
                                created_at=d.get("created_at", ""),
                                read=d.get("read", False),
                                is_live=d.get("is_live", True),
                                environment=d.get("environment", "LIVE"),
                                is_invalidated=d.get("is_invalidated", False),
                                invalidation_reason=d.get("invalidation_reason"),
                                invalidated_at=d.get("invalidated_at"),
                                achieved_milestones=d.get("achieved_milestones", []),
                                target_status=d.get("target_status", "PENDING"),
                                should_trail=d.get("should_trail", False),
                                trailing_decision=d.get("trailing_decision"),
                                trailing_stop=d.get("trailing_stop"),
                                trailing_rationale=d.get("trailing_rationale"),
                                locked_profit_pts=d.get("locked_profit_pts"),
                                locked_profit_pct=d.get("locked_profit_pct"),
                                last_trail_alert_time=d.get("last_trail_alert_time"),
                                is_archived=bool(d.get("is_archived", False)),
                                archived_at=d.get("archived_at"),
                                archive_reason=d.get("archive_reason"),
                                expiry_date=d.get("expiry_date"),
                                expiry_type=d.get("expiry_type"),
                                underlying_spot=d.get("underlying_spot"),
                                option_premium=d.get("option_premium"),
                                market_status=d.get("market_status", "SESSION_CLOSED"),
                                lot_size=d.get("lot_size"),
                                segment=d.get("segment", ""),
                                signal_ref=d.get("signal_ref"),
                                r_multiple=d.get("r_multiple"),
                                pnl_pct=d.get("pnl_pct"),
                                updated_at=d.get("updated_at"),
                                triggered_at=d.get("triggered_at"),
                                original_call_time=d.get("original_call_time") or d.get("created_at"),
                            )
                        )
                # Rehabilitate alerts erroneously invalidated by the inverted Put option stop-loss bug
                rehab_count = 0
                for a in alerts:
                    if a.is_invalidated and a.invalidation_reason:
                        # Match "Option premium collapsed to ₹X (breached stop-loss ₹Y)"
                        m = re.search(
                            r"Option premium collapsed to ₹([\d.]+)\s*\(breached stop-loss ₹([\d.]+)\)",
                            a.invalidation_reason,
                        )
                        if m:
                            try:
                                reported_ltp = float(m.group(1))
                                reported_sl = float(m.group(2))
                                if reported_ltp >= reported_sl:
                                    logger.info(
                                        f"[AutoAlertEngine] Rehabilitating falsely invalidated option alert {a.symbol} ({a.alert_id}): "
                                        f"reported LTP ₹{reported_ltp} >= SL ₹{reported_sl}"
                                    )
                                    a.is_invalidated = False
                                    a.invalidation_reason = None
                                    a.invalidated_at = None
                                    a.is_archived = False
                                    a.archived_at = None
                                    a.archive_reason = None
                                    vol_oi = float(
                                        a.metrics.get("vol_oi_ratio", 0.0) if a.metrics else 0.0
                                    )
                                    a.stage = "IGNITED" if vol_oi >= 2.5 else "EARLY_WARNING"
                                    tag = (
                                        "[TEST]"
                                        if (a.environment == "TEST" or not a.is_live)
                                        else "[REAL/LIVE]"
                                    )
                                    opt_type = a.option_type or (
                                        "PE" if a.direction == "BEARISH" else "CE"
                                    )
                                    strike_int = int(a.strike) if a.strike else ""
                                    a.headline = (
                                        f"⚡ {tag} {opt_type} GAMMA BLAST {a.stage.replace('_', ' ')}: "
                                        f"{a.symbol} {strike_int} {opt_type}"
                                    ).strip()
                                    a.summary = f"{opt_type} gamma setup active. Holding above stop-loss ₹{a.stop_loss:.1f}."
                                    rehab_count += 1
                                    try:
                                        from engine.learning_engine import pattern_learning_engine

                                        pattern_learning_engine.clear_symbol_lockout(a.symbol)
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                self._alerts = alerts
                if rehab_count > 0:
                    self._save()
                # 1. Automatically reap and purge expired derivative alerts
                self._reap_expired_alerts_unlocked(purge=True)
                # 2. Permanently purge legacy alerts violating institutional quality gates
                self._sanitize_legacy_alerts_unlocked()
                # 3. Deduplicate multiple iterations of the same symbol (keep only latest active)
                self._deduplicate_symbols_unlocked()
                # 4. Periodically prune stale / invalidated / archived records older than 1 day
                self._prune_expired_archived_unlocked(max_age_days=1)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _load error: {e}")
            self._alerts = []


# Module-level singleton instance
auto_alert_engine = AutoAlertEngine()
