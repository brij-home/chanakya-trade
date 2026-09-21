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

from collections import defaultdict, deque
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("engine.auto_alert_engine")

IST = timezone(timedelta(hours=5, minutes=30))


def get_auto_alerts_file() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    return base / "auto_alerts.json"


AUTO_ALERTS_FILE = get_auto_alerts_file()


# ── Modular Subsystems & Re-exports ─────────────────────────────────────────

from engine.alert_model import AutoAlert
from engine.alert_expiry import (
    classify_expiry_type,
    is_alert_option_premium_level,
)
from engine.alert_evaluator import (
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
)
from engine.detectors import (
    detect_gamma_blast,
    detect_opening_drive,
    detect_squeeze_breakout,
    detect_circuit_proximity,
    detect_learned_pattern_coiling,
    detect_opening_range_breakout,
)



def get_current_ist_session(ref_dt: Optional[datetime] = None) -> dict[str, bool]:
    """
    Evaluates current IST operational session status per institutional schedule & user discipline.
    Respects market trading holidays (Ganesh Chaturthi, Republic Day, etc.), weekends,
    and operational market windows.
    """
    from market.calendar import get_current_ist_session as _cal_get_current_ist_session

    return _cal_get_current_ist_session(ref_dt=ref_dt)


def expected_volume_fraction(minutes_from_open: float) -> float:
    """
    Returns expected cumulative volume fraction (0.03 to 1.0)
    for Indian equity/NFO markets (09:15 - 15:30 IST, total 375 minutes).
    Models the institutional U-shaped cumulative volume profile.
    """
    if minutes_from_open <= 0:
        return 0.03
    if minutes_from_open >= 375.0:
        return 1.0

    t = minutes_from_open
    if t <= 15.0:       # 09:15 - 09:30 IST (Opening discovery)
        return 0.03 + (t / 15.0) * 0.09         # 3% -> 12%
    elif t <= 45.0:     # 09:30 - 10:00 IST (Morning institutional drive)
        return 0.12 + ((t - 15.0) / 30.0) * 0.13 # 12% -> 25%
    elif t <= 135.0:    # 10:00 - 11:30 IST (Morning trend continuation)
        return 0.25 + ((t - 45.0) / 90.0) * 0.20 # 25% -> 45%
    elif t <= 255.0:    # 11:30 - 13:30 IST (Midday lull)
        return 0.45 + ((t - 135.0) / 120.0) * 0.18 # 45% -> 63%
    elif t <= 345.0:    # 13:30 - 15:00 IST (Afternoon expiry & expansion)
        return 0.63 + ((t - 255.0) / 90.0) * 0.22 # 63% -> 85%
    else:               # 15:00 - 15:30 IST (Closing auction acceleration)
        return 0.85 + ((t - 345.0) / 30.0) * 0.15 # 85% -> 100%


def compute_time_of_day_rvol(
    current_vol: float,
    avg_daily_vol: float,
    ref_dt: Optional[datetime] = None,
) -> float:
    """
    Computes accurate Time-of-Day Relative Volume (TOD-RVOL).
    Normalizes intraday cumulative volume against the expected volume up to the current minute,
    preventing early-morning breakout disqualification.
    """
    if avg_daily_vol <= 0:
        return 1.0
    now_ist = ref_dt or datetime.now(IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)
    else:
        now_ist = now_ist.astimezone(IST)

    # Minutes elapsed from 09:15 IST
    mins_from_open = (now_ist.hour * 60 + now_ist.minute) - (9 * 60 + 15)
    fraction = expected_volume_fraction(float(mins_from_open))
    expected_vol = max(1.0, avg_daily_vol * fraction)
    return round(float(current_vol) / expected_vol, 2)


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
        self._watched_indices = [
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "BANKEX",
        ]
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
        # Watched commodities & currency universe (continuous monitoring 09:00 - 23:30 IST)
        self._watched_commodities = [
            "CRUDEOIL",
            "CRUDEOILM",
            "GOLD",
            "GOLDM",
            "SILVER",
            "SILVERM",
            "NATURALGAS",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
        ]
        self._watched_currencies = [
            "USDINR",
            "EURINR",
            "GBPINR",
        ]
        # Watched 24x7 Crypto universe (Binance Spot/Futures & Deribit Options benchmarks)
        self._watched_crypto = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
        ]
        self._crypto_listener_initialized = False
        self._crypto_tick_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._crypto_last_surge_eval: dict[str, float] = {}

        self._load()
        self.cleanup_corrupted_test_alerts()
        # Seed dispatched milestones from loaded state to prevent duplicate dispatches across restarts
        with self._lock:
            for a in self._alerts:
                aid = getattr(a, "alert_id", "")
                sym = getattr(a, "symbol", "")
                atype = getattr(a, "alert_type", "")
                if getattr(a, "in_flight_warning_sent", False) or a.stage == "IN_FLIGHT_WARNING":
                    self._dispatched_milestones.add(f"{sym}:{aid}:IN_FLIGHT_WARNING")
                if a.is_invalidated or a.stage == "INVALIDATED":
                    self._dispatched_milestones.add(f"{sym}:{aid}:INVALIDATED")
                achieved = getattr(a, "achieved_milestones", []) or []
                if "T1_ACHIEVED" in achieved:
                    self._dispatched_milestones.add(f"{sym}:{atype}:T1")
                if "FINAL_ACHIEVED" in achieved:
                    self._dispatched_milestones.add(f"{sym}:{atype}:FINAL")

    @property
    def watched_crypto(self) -> list[str]:
        """Returns liquid 24x7 Crypto pairs for continuous monitoring."""
        return list(self._watched_crypto)

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

            # 1. Complete liquid NSE F&O Universe (single-stock equities, excluding indices)
            fno_all = THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", [])
            for s in fno_all:
                if (
                    s not in symbols
                    and s not in self._watched_indices
                    and s not in ("NIFTYFPI", "NIFTYNXT50")
                ):
                    symbols.append(s)

            most_liquid = THEMATIC_PRESETS.get("most_liquid_today", {}).get("symbols", [])
            vol_surges = THEMATIC_PRESETS.get("volume_surges_rvol", {}).get("symbols", [])
            for s in most_liquid + vol_surges:
                if s not in symbols:
                    symbols.append(s)

            # High-turnover liquid F&O leaders across key sectors
            fno_leaders = [
                "COALINDIA", "HAL", "BEL", "TRENT", "VEDL", "HINDALCO", "TATASTEEL",
                "JINDALSTEL", "PFC", "RECLTD", "CANBK", "BANKBARODA", "PNB",
                "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN", "DIXON", "POLYCAB", "PERSISTENT",
                "COFORGE", "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "ASHOKLEY", "HEROMOTOCO",
                "ADANIENT", "ADANIPORTS", "JSWSTEEL", "POWERGRID"
            ]
            for s in fno_leaders:
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
        now_t = datetime.now(IST).time()
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
            c_tag = (
                f" {int(alert.strike)} {alert.option_type}"
                if alert.strike and alert.option_type
                else ""
            )
            alert.headline = f"🎯 [{alert.environment}] {alert.alert_type.replace('_', ' ')}: {clean_target}{c_tag} @ ₹{alert.ltp:,.1f}"

        raw_sm = (alert.summary or "").strip()
        if not raw_sm or len(raw_sm) <= 3 or raw_sm.lower() in ("s", "test", "dummy"):
            scrutiny = (
                (alert.metrics or {}).get("scrutiny", {}) if isinstance(alert.metrics, dict) else {}
            )
            logic_conf = scrutiny.get("logic_confirmation") if isinstance(scrutiny, dict) else None
            if logic_conf and len(str(logic_conf).strip()) > 5:
                alert.summary = str(logic_conf).strip()
            else:
                c_tag = (
                    f"{clean_target} {int(alert.strike)} {alert.option_type}"
                    if alert.strike and alert.option_type
                    else clean_target
                )
                alert.summary = f"Institutional momentum surge on {c_tag}. Invalidation anchor: ₹{alert.stop_loss:,.1f}."

        # 00b. Broker Feed & Provenance Calibration
        if not getattr(alert, "order_flow_signals", None) or not alert.order_flow_signals.get("provenance"):
            try:
                from brokers.session import get_all_brokers
                all_b = get_all_brokers()
                is_live_b = any(
                    k != "mock" and getattr(b, "is_authenticated", lambda: True)()
                    for k, b in all_b.items()
                )
                if not getattr(alert, "order_flow_signals", None):
                    alert.order_flow_signals = {}
                alert.order_flow_signals.setdefault("live_broker_connected", is_live_b)
                alert.order_flow_signals.setdefault(
                    "provenance", "LIVE_BROKER_FEED" if is_live_b else "REAL_MARKET_FEED"
                )
                alert.order_flow_signals.setdefault(
                    "broker_depth_status", "LIVE_L2" if is_live_b else "LIVE_REST"
                )
            except Exception:
                pass

        # 00c. Quantitative State Snapshot & Traceability
        if not getattr(alert, "quant_snapshot", None):
            vix_val = None
            try:
                from market.indices import get_vix
                vix_val = get_vix()
            except Exception:
                pass
            alert.quant_snapshot = {
                "ltp": alert.ltp,
                "trigger_level": alert.trigger_level,
                "stop_loss": alert.stop_loss,
                "target_level": alert.target_level,
                "vix": vix_val,
                "feed_provenance": (alert.order_flow_signals or {}).get("provenance", "LIVE_FEED"),
                "recorded_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            }

        # 00d. Invalidation Noise Floor Gate (Anti-Whipsaw Guard):
        # Enforces that stop-loss is not placed inside sub-ATR noise (< 1.0% on equities or < 12% on options).
        # Eliminates the 60.4% SUB_ATR_NOISE_WHIPSAW invalidation failures.
        if alert.ltp and alert.ltp > 0 and alert.stop_loss and alert.stop_loss > 0:
            opt_prem = getattr(alert, "option_premium", None)
            is_opt = bool(
                alert.alert_type in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
                or (alert.alert_type == "GAMMA_BLAST" and alert.option_type)
                or (opt_prem is not None and abs(alert.ltp - float(opt_prem)) < max(1.0, float(opt_prem) * 0.15))
            )
            if is_opt:
                # Option premium risk floor: SL must give at least 15% breathing room from entry
                opt_risk_pct = (abs(alert.ltp - alert.stop_loss) / alert.ltp) * 100.0
                if opt_risk_pct < 10.0:
                    alert.stop_loss = round(max(0.1, alert.ltp * 0.85), 2)
                    new_opt_risk = max(0.2, alert.ltp - alert.stop_loss)
                    min_t1 = round(alert.ltp + 1.8 * new_opt_risk, 2)
                    if alert.target_level < min_t1:
                        alert.target_level = min_t1
                    if alert.actionable_plan and isinstance(alert.actionable_plan, dict):
                        alert.actionable_plan["stop_loss"] = f"₹{alert.stop_loss:,.1f}"
                        alert.actionable_plan["target_1"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["target"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["risk_reward"] = f"1:{round((alert.target_level - alert.ltp) / new_opt_risk, 1)}"
            else:
                # Equity risk floor: minimum 0.85% distance from entry
                eq_risk_pct = (abs(alert.ltp - alert.stop_loss) / alert.ltp) * 100.0
                if eq_risk_pct < 0.60:
                    alert.stop_loss = round(
                        alert.ltp * (0.988 if alert.direction == "BULLISH" else 1.012), 1
                    )
                    new_eq_risk = abs(alert.ltp - alert.stop_loss)
                    min_t1 = round(alert.ltp + (1.8 * new_eq_risk if alert.direction == "BULLISH" else -1.8 * new_eq_risk), 1)
                    if alert.direction == "BULLISH" and alert.target_level < min_t1:
                        alert.target_level = min_t1
                    elif alert.direction == "BEARISH" and alert.target_level > min_t1:
                        alert.target_level = min_t1
                    if alert.actionable_plan and isinstance(alert.actionable_plan, dict):
                        alert.actionable_plan["stop_loss"] = f"₹{alert.stop_loss:,.1f}"
                        alert.actionable_plan["target_1"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["target"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["risk_reward"] = f"1:{round(abs(alert.target_level - alert.ltp) / new_eq_risk, 1)}"

        # 0a. Market Session Timing Gate (Opening Range Discovery & Closing Cutoff)
        is_test_runner = (

            is_sim
            or (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if (
            not is_test_runner
            and alert.stage in ("IGNITED",)
            and alert.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "SQUEEZE_BREAKOUT")
        ):
            # 09:15 - 09:18 IST: Morning Opening Discovery Quiet Window (3-min auction settlement)
            # From 09:18 onwards, opening range is formed; allow verified high-volume momentum and index explosions.
            is_idx_alert = (getattr(alert, "segment", "") == "FNO_INDEX") or clean_target in (
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "SENSEX",
                "BANKEX",
            )
            quiet_cutoff = dtime(9, 18) if is_idx_alert else dtime(9, 20)
            if dtime(9, 15) <= now_t < quiet_cutoff:
                logger.info(
                    f"[AutoAlertEngine] 🛑 Suppressed opening auction breakout alert for {clean_target} ({alert.alert_type}): "
                    f"Market Opening Quiet Window (09:15–{quiet_cutoff.strftime('%H:%M')} IST) active to avoid auction whipsaws."
                )
                return False

            # Post-15:10 IST: Hard Closing Cutoff for domestic equity/NFO intraday options
            if (
                alert.exchange in ("NSE", "BSE", "NFO", "")
                and alert.alert_type in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                and now_t >= dtime(15, 10)
            ):
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
                    existing_active.signal_ref = (
                        None  # Force fresh signal ref with today's date & time
                    )
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

                # 2b. Cross-Detector Active Trade Mutex:
                # If a different detector is already tracking an active trade for this stock in the same direction today,
                # suppress new initial alerts from other detectors (e.g. don't fire GAMMA_BLAST if
                # OPTIONS_MOMENTUM or INTRADAY_SPARK is already active).
                if not is_sim and alert.stage in ("IGNITED", "EARLY_WARNING"):
                    active_diff_detector = next(
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
                            and a.direction == alert.direction
                            and a.alert_type != alert.alert_type
                            and a.is_active
                            and not a.is_invalidated
                            and a.stage not in ("INVALIDATED", "COMPLETED", "EXPIRED", "TARGET_ACHIEVED")
                            and a.alert_id != alert.alert_id
                            and (_alert_date(a) is None or _alert_date(a) == alert_dt_date)
                        ),
                        None,
                    )
                    if active_diff_detector:
                        CONFLUENCE_RADARS = {
                            "PRECURSOR_RADAR",
                            "ASYMMETRIC_OPPORTUNITY",
                            "POCKET_PIVOT",
                            "SMC_SWEEP",
                            "VOLUME_PROFILE",
                            "SQUEEZE_BREAKOUT",
                        }
                        is_orthogonal_confluence = (
                            active_diff_detector.alert_type in CONFLUENCE_RADARS
                            and alert.alert_type in CONFLUENCE_RADARS
                        )

                        if is_orthogonal_confluence:
                            # Cross-Radar Confluence Aggregation: Elevate active alert to multi-model confluence
                            if not isinstance(active_diff_detector.metrics, dict):
                                active_diff_detector.metrics = {}
                            conf_types = active_diff_detector.metrics.setdefault(
                                "confluence_types", [active_diff_detector.alert_type]
                            )
                            if alert.alert_type not in conf_types:
                                conf_types.append(alert.alert_type)
                                old_conf = active_diff_detector.confidence
                                active_diff_detector.confidence = min(
                                    99, max(active_diff_detector.confidence, alert.confidence) + 6
                                )
                                catalysts = active_diff_detector.metrics.setdefault("confluence_catalysts", [])
                                if alert.summary and alert.summary not in catalysts:
                                    catalysts.append(alert.summary)

                                # Actionable plan & levels inheritance if active plan was incomplete
                                if not active_diff_detector.actionable_plan and alert.actionable_plan:
                                    active_diff_detector.actionable_plan = dict(alert.actionable_plan)
                                elif alert.actionable_plan and isinstance(alert.actionable_plan, dict):
                                    for k, v in alert.actionable_plan.items():
                                        if k not in active_diff_detector.actionable_plan or not active_diff_detector.actionable_plan[k]:
                                            active_diff_detector.actionable_plan[k] = v

                                if (not active_diff_detector.stop_loss or active_diff_detector.stop_loss <= 0) and alert.stop_loss:
                                    active_diff_detector.stop_loss = alert.stop_loss
                                if (not active_diff_detector.target_level or active_diff_detector.target_level <= 0) and alert.target_level:
                                    active_diff_detector.target_level = alert.target_level

                                # If incoming is IGNITED while active was EARLY_WARNING, upgrade stage
                                if active_diff_detector.stage == "EARLY_WARNING" and alert.stage == "IGNITED":
                                    active_diff_detector.stage = "IGNITED"
                                    active_diff_detector.trigger_level = alert.trigger_level

                                types_str = " + ".join([t.replace("_", " ") for t in conf_types])
                                active_diff_detector.headline = (
                                    f"💎 [CONFLUENCE APEX] {clean_target}: {types_str} @ ₹{alert.ltp:,.1f}"
                                )
                                logger.info(
                                    f"[AutoAlertEngine] 💎 Confluence Apex formed for {clean_target}: "
                                    f"Added {alert.alert_type} to existing {active_diff_detector.alert_type} "
                                    f"(Conviction boosted: {old_conf} -> {active_diff_detector.confidence})"
                                )
                                self._save()
                                to_dispatch = active_diff_detector
                                try:
                                    from web.sse import event_bus
                                    event_bus.publish_sync(
                                        "alerts",
                                        {
                                            "type": "alert_confluence_update",
                                            "alert": active_diff_detector.to_dict(),
                                        },
                                    )
                                except Exception:
                                    pass
                            else:
                                logger.info(
                                    f"[AutoAlertEngine] 🛑 Suppressed redundant {alert.alert_type} for {clean_target}: "
                                    f"Active {active_diff_detector.alert_type} ({active_diff_detector.stage}) already tracking."
                                )
                            if not to_dispatch:
                                return False
                        else:
                            # Cross-Detector Active Trade Mutex: Suppress duplicate execution triggers
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Active trade mutex: Suppressed {alert.alert_type} for {clean_target} "
                                f"(Already tracking active {active_diff_detector.alert_type} in {alert.direction} direction)."
                            )
                            return False

                    if not to_dispatch:
                        # Cooldown check: prevent duplicate same-direction alerts for the same stock today
                        sym_sig = f"{clean_target}:{alert.direction}"
                        last_sym_time = self._cooldowns.get(sym_sig, 0.0)
                        if (now - last_sym_time) < self._cooldown_ttl:
                            has_active_today = any(
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
                            if has_active_today:
                                logger.info(
                                    f"[AutoAlertEngine] 🛑 Suppressed redundant alert for {clean_target} ({alert.alert_type}): "
                                    f"Active {alert.direction} trade already running within {int(self._cooldown_ttl / 60)}m window."
                                )
                                return False

                # 2bb. Base Commodity Canonicalization Gate:
                # Suppress mini/micro contract duplicates if base commodity has an active trade or recent alert
                COMMODITY_CANONICAL_MAP = {
                    "SILVERM": "SILVER",
                    "SILVERMIC": "SILVER",
                    "GOLDM": "GOLD",
                    "GOLDGUINEA": "GOLD",
                    "CRUDEOILM": "CRUDEOIL",
                }
                if not is_sim and not to_dispatch and clean_target in COMMODITY_CANONICAL_MAP and alert.stage in ("IGNITED", "EARLY_WARNING"):
                    root_comm = COMMODITY_CANONICAL_MAP[clean_target]
                    has_root_active = any(
                        a.symbol.strip().upper() == root_comm
                        and a.is_active
                        and not a.is_invalidated
                        and a.stage not in ("INVALIDATED", "COMPLETED", "EXPIRED", "TARGET_ACHIEVED")
                        for a in self._alerts
                    )
                    last_root_t = self._cooldowns.get(f"{root_comm}:{alert.direction}", 0.0)
                    if has_root_active or (now - last_root_t) < 3600.0:
                        logger.info(
                            f"[AutoAlertEngine] 🛑 Suppressed derivative commodity {clean_target} ({alert.alert_type}): "
                            f"Primary commodity {root_comm} is already active or recently alerted."
                        )
                        return False

                # 2bc. Strict 'On/Before Time' No-Chase Guard:
                # Disqualify setups where the market price has already run past the defined no-chase boundary.
                if not is_sim and not to_dispatch and alert.no_chase_boundary and alert.ltp > 0 and alert.stage in ("IGNITED", "EARLY_WARNING"):
                    is_plan_opt = (alert.actionable_plan or {}).get("instrument_type") == "OPTION"
                    is_opt_prem = is_alert_option_premium_level(alert) or (
                        is_plan_opt and alert.option_premium and abs(alert.trigger_level - alert.option_premium) < 0.01
                    )
                    act_str = str((alert.actionable_plan or {}).get("action", "")).strip().upper()
                    if is_opt_prem:
                        is_short_pos = act_str.startswith("SELL") or "SHORT" in act_str or "WRITE" in act_str
                    elif act_str in ("BUY_PE", "BUY_PUT") or alert.direction in ("BEARISH", "SHORT", "SELL"):
                        is_short_pos = True
                    elif act_str.startswith("BUY") or "LONG" in act_str or alert.direction in ("BULLISH", "LONG"):
                        is_short_pos = False
                    elif alert.target_level > 0 and alert.target_level != alert.trigger_level:
                        is_short_pos = alert.target_level < alert.trigger_level
                    else:
                        is_short_pos = False

                    if not is_short_pos and alert.ltp > alert.no_chase_boundary:
                        logger.info(
                            f"[AutoAlertEngine] 🛑 Disqualified chased entry for {clean_target} ({alert.alert_type}): "
                            f"LTP ₹{alert.ltp:,.1f} has surged past no-chase boundary ₹{alert.no_chase_boundary:,.1f}."
                        )
                        return False
                    elif is_short_pos and alert.ltp < alert.no_chase_boundary:
                        logger.info(
                            f"[AutoAlertEngine] 🛑 Disqualified chased short entry for {clean_target} ({alert.alert_type}): "
                            f"LTP ₹{alert.ltp:,.1f} has dropped past short no-chase boundary ₹{alert.no_chase_boundary:,.1f}."
                        )
                        return False

                # 2c. Learning Engine Invalidation Lockout Gate:
                # Prevent re-triggering on assets that were stopped out / invalidated in the current session
                if not is_sim and not to_dispatch:
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

        # If an existing active alert was upgraded or aggregated with multi-radar confluence, dispatch immediately!
        if to_dispatch:
            self._dispatch(to_dispatch)
            return True

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
                        is_plan_opt = (
                            is_opt
                            or alert.actionable_plan.get("instrument_type") == "OPTION"
                            or "OPTION" in str(alert.actionable_plan.get("preferred_vehicle", "")).upper()
                            or alert.option_premium is not None
                            or (
                                alert.actionable_plan.get("raw_contract")
                                and any(x in str(alert.actionable_plan.get("raw_contract")).upper() for x in ("CE", "PE"))
                            )
                        )

                        # Isolate price coordinate system:
                        # If actionable plan is for an option vehicle while alert price levels are in spot/futures space,
                        # reference levels must be sourced from the option plan, NOT the underlying stock!
                        if is_plan_opt and not is_opt:
                            opt_sl_str = str(alert.actionable_plan.get("stop_loss", ""))
                            m_sl = re.findall(r"[\d,]+(?:\.\d+)?", opt_sl_str)
                            ref_sl = (
                                float(m_sl[0].replace(",", ""))
                                if m_sl
                                else float(alert.actionable_plan.get("trade_plan", {}).get("invalidation_stop") or 0.0)
                            )
                            ref_ltp = float(
                                alert.option_premium
                                or alert.actionable_plan.get("trade_plan", {}).get("entry_price")
                                or ((lower_val + upper_val) / 2.0)
                            )
                            opt_t_str = str(alert.actionable_plan.get("target", ""))
                            m_t = re.findall(r"[\d,]+(?:\.\d+)?", opt_t_str)
                            ref_target = (
                                float(m_t[0].replace(",", ""))
                                if m_t
                                else float(alert.actionable_plan.get("trade_plan", {}).get("target_1") or 0.0)
                            )
                            if ref_sl <= 0:
                                ref_sl = round(max(0.1, ref_ltp * 0.72), 1)
                        else:
                            ref_sl = alert.stop_loss
                            ref_ltp = alert.ltp
                            ref_target = alert.target_level

                        is_long = (
                            alert.direction in ("BULLISH", "LONG", "BUY")
                            or "BUY" in act
                            or (is_plan_opt and "SELL" not in act and "WRITE" not in act)
                        )

                        if is_long:
                            # Long position (Long Equity, Long Call CE, or Long Put PE):
                            # Entry Range must be strictly above Stop-Loss (StopLoss < Entry <= Target)
                            if lower_val <= ref_sl or lower_val <= 0:
                                step = (
                                    max(0.5, (ref_ltp - ref_sl) * 0.15)
                                    if ref_ltp > ref_sl
                                    else max(0.5, ref_sl * 0.05)
                                )
                                corr_lower = round(ref_sl + step, 1)
                                corr_upper = max(upper_val, round(corr_lower + max(0.5, step), 1))
                                if ref_ltp > 0:
                                    corr_lower = min(corr_lower, round(ref_ltp * 0.98, 1))
                                    corr_upper = max(corr_lower + 0.1, round(ref_ltp * 1.02, 1))
                                    # Strict target clamping: Long entry range must NEVER exceed or touch Target 1
                                    if ref_target > ref_ltp:
                                        max_allowed_upper = round(
                                            ref_ltp + 0.35 * (ref_target - ref_ltp), 1
                                        )
                                        corr_upper = min(
                                            corr_upper,
                                            max(corr_lower + 0.1, max_allowed_upper),
                                        )
                                    if corr_lower <= ref_sl:
                                        corr_lower = round(ref_sl + 0.5, 1)
                                        corr_upper = max(corr_lower + 0.5, corr_upper)
                                alert.actionable_plan["entry_range"] = (
                                    f"₹{corr_lower:,.1f} – ₹{corr_upper:,.1f}"
                                )
                        else:
                            # Short position (Cash Equity / Futures Short):
                            # Entry Range must be strictly below Stop-Loss (Target < Entry < StopLoss)
                            if upper_val >= ref_sl or upper_val <= 0:
                                step = (
                                    max(0.5, (ref_sl - ref_ltp) * 0.15)
                                    if ref_sl > ref_ltp
                                    else max(0.5, ref_sl * 0.05)
                                )
                                corr_upper = round(ref_sl - step, 1)
                                corr_lower = min(lower_val, round(corr_upper - max(0.5, step), 1))
                                if corr_lower <= 0:
                                    corr_lower = max(0.5, round(corr_upper * 0.95, 1))
                                if ref_ltp > 0:
                                    corr_upper = max(corr_upper, round(ref_ltp * 1.02, 1))
                                    corr_lower = min(corr_lower, round(ref_ltp * 0.98, 1))
                                    # Strict target clamping: Short entry range must NEVER drop below or touch Target 1
                                    if 0 < ref_target < ref_ltp:
                                        min_allowed_lower = round(
                                            ref_ltp - 0.35 * (ref_ltp - ref_target), 1
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
                if "sym_sig" in locals():
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
        # Provenance: treat alerts with test-/mock- IDs as TEST regardless of stored environment field.
        # This closes the inconsistency where a manually-injected test alert has environment="LIVE"
        # but a test- prefix, causing it to show as LIVE in the UI while being Telegram-blocked.
        _id_prefix_is_test = (alert.alert_id or "").startswith("test-") or (alert.alert_id or "").startswith("mock-")
        is_test = (alert.environment == "TEST") or (not alert.is_live) or _id_prefix_is_test
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
        alert_dict["segment"] = getattr(
            alert, "segment", None
        ) or alert_preferences.classify_alert_segment(alert)
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
            if is_cli_adhoc and os.environ.get(
                "ALLOW_MANUAL_TELEGRAM_DISPATCH", "0"
            ).lower() not in ("1", "true"):
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
                or alert.stage in ("INVALIDATED", "IN_FLIGHT_WARNING", "TARGET_ACHIEVED", "COMPLETED")
                or is_t1
                or is_target
                or is_trail
            )

            # ZERO-GHOST LIFECYCLE INVARIANT:
            # Downstream lifecycle updates (Invalidations, Targets, Trailing stops, In-flight warnings)
            # must NEVER be dispatched to Telegram if the original signal was not dispatched to Telegram!
            if is_milestone:
                if not getattr(alert, "telegram_dispatched", False):
                    logger.info(
                        f"[AutoAlertEngine] 🛑 Suppressed Telegram lifecycle milestone ({alert.stage} / is_invalidated={alert.is_invalidated}) "
                        f"for {alert.symbol} ({alert.alert_id}): Original signal was never broadcast to Telegram."
                    )
                    return

            # "SIGNAL ONCE" DISCIPLINE:
            # If an early warning trade card was already dispatched to Telegram for this alert,
            # suppress duplicate full card on subsequent ignition. The ignition is captured in Terminal UI/SSE.
            if alert.stage == "IGNITED" and getattr(alert, "telegram_dispatched", False):
                logger.info(
                    f"[AutoAlertEngine] 🛑 Suppressed duplicate IGNITED Telegram card for {alert.symbol} ({alert.alert_id}): "
                    f"Actionable trade setup was already dispatched once on Telegram."
                )
                return

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

            if not is_milestone:
                # Institutional Telegram Conviction Bar:
                # Respect alert_preferences.telegram.min_confidence (defaults to 85, configured to 90+ in production).
                tg_min = getattr(alert_preferences.telegram, "min_confidence", 85)
                if alert.confidence < tg_min:
                    logger.info(
                        f"[AutoAlertEngine] 🛑 Suppressed setup for {alert.symbol} on Telegram: "
                        f"Confidence {alert.confidence}% below Telegram bar ({tg_min}%)."
                    )
                    return

                # Risk:Reward Quality Filter (Favor setups with R:R >= 1:1.4)
                if alert.stop_loss > 0 and alert.target_level > 0 and alert.trigger_level > 0:
                    is_short = alert.direction in ("BEARISH", "SHORT", "SELL")
                    risk_pts = (alert.stop_loss - alert.trigger_level) if is_short else (alert.trigger_level - alert.stop_loss)
                    reward_pts = (alert.trigger_level - alert.target_level) if is_short else (alert.target_level - alert.trigger_level)
                    if risk_pts > 0 and reward_pts > 0:
                        rr_ratio = reward_pts / risk_pts
                        if rr_ratio < 1.4:
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Suppressed unfavorable R:R setup for {alert.symbol} on Telegram: "
                                f"R:R 1:{rr_ratio:.1f} below minimum 1:1.4 threshold."
                            )
                            return

                # Segment-level Pacing Throttle:
                # Prevent bursting multiple initial signals within a 45-second window on the same segment,
                # unless the candidate has exceptional conviction (>= 90).
                seg_label = alert_dict.get("segment") or "GENERAL"
                pacing_key = f"PACING:{seg_label}"
                last_pace_t = self._dispatch_cooldowns.get(pacing_key, 0.0)
                if (time.time() - last_pace_t) < 45.0 and alert.confidence < 90:
                    logger.info(
                        f"[AutoAlertEngine] 🛑 Telegram pacing throttle active on {seg_label} "
                        f"({int(time.time() - last_pace_t)}s elapsed < 45s). Holding setup in Terminal UI."
                    )
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
                    ) or (
                        os.environ.get("TELEGRAM_ALLOW_TRAILING_UPDATES", "0").lower()
                        in ("1", "true")
                    )
                    if not allow_trails:
                        return
                    m_key = f"{alert.symbol}:{alert.alert_type}:TRAIL"
                    last_t = self._dispatch_cooldowns.get(m_key, 0.0)
                    if (now_ts - last_t) < 900.0:  # 15 min cooldown
                        return
                    self._dispatch_cooldowns[m_key] = now_ts

                elif alert.stage == "EARLY_WARNING":
                    # Early warnings are preliminary coiling signals -> keep in SSE / Terminal,
                    # do not buzz Telegram unless exceptionally high confidence (>= 90 for general, >= 82 for
                    # PRECURSOR_RADAR / ASYMMETRIC_OPPORTUNITY / crypto early warnings)
                    _ew_whitelist = (
                        "PRECURSOR_RADAR",
                        "ASYMMETRIC_OPPORTUNITY",
                        "OPTIONS_MOMENTUM",
                        "GAMMA_BLAST",
                        "COMMODITY_MOMENTUM",
                        "CURRENCY_BREAKOUT",
                        # Crypto early-warning types: funding squeeze build-up,
                        # Deribit max pain gravity pull — structurally high-conviction
                        "CRYPTO_SQUEEZE",
                        "CRYPTO_MOMENTUM",
                        "CRYPTO_VOLATILITY",
                    )
                    if alert.alert_type in _ew_whitelist:
                        # Whitelisted type — 82% bar. Block if below, pass through to dispatch if met.
                        if alert.confidence < 82:
                            return
                    else:
                        # General early warning — require 90%
                        if alert.confidence < 90:
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

                elif alert.stage == "IN_FLIGHT_WARNING":
                    m_key = f"{alert.symbol}:{getattr(alert, 'alert_id', '')}:IN_FLIGHT_WARNING"
                    if m_key in self._dispatched_milestones:
                        return
                    self._dispatched_milestones.add(m_key)

            from bot.alert_templates import render_auto_alert

            from engine.alert_preferences import classify_alert_segment

            tg_msg = render_auto_alert(alert, in_market=in_market)
            target_seg = getattr(alert, "segment", None) or classify_alert_segment(alert)
            tg_target_chat_id = alert_preferences.get_telegram_chat_id(target_seg)
            if tg_target_chat_id:
                try:
                    _telegram_notify(tg_msg, chat_id=tg_target_chat_id)
                except TypeError:
                    _telegram_notify(tg_msg)
            else:
                _telegram_notify(tg_msg)

            # Record channel delivery provenance and segment pacing timestamp
            with self._lock:
                alert.telegram_dispatched = True
                if not isinstance(alert.dispatched_channels, list):
                    alert.dispatched_channels = []
                if "telegram" not in alert.dispatched_channels:
                    alert.dispatched_channels.append("telegram")
                if not is_milestone:
                    seg_lbl = alert_dict.get("segment") or "GENERAL"
                    self._dispatch_cooldowns[f"PACING:{seg_lbl}"] = now_ts
                self._save()
        except Exception as e:
            logger.warning(f"[AutoAlertEngine] Telegram dispatch failed: {e}", exc_info=True)

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

    # ── Early Warning Ignition Monitoring ───────────────────────

    def check_and_ignite_early_warnings(
        self, exchanges: Optional[list[str]] = None
    ) -> list[AutoAlert]:
        """
        Scans all active EARLY_WARNING alerts against live market price to detect
        when the price crosses the breakout/breakdown trigger level.
        Transitions the alert to stage="IGNITED", updates headline/summary,
        and dispatches high-priority breakout notifications.
        """
        ignited_alerts: list[AutoAlert] = []
        exch_filter = {e.upper() for e in exchanges} if exchanges else None

        with self._lock:
            early_alerts = [
                a
                for a in self._alerts
                if not a.is_invalidated
                and a.stage == "EARLY_WARNING"
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        for alert in early_alerts:
            try:
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

                cur_ltp = get_ltp(lookup_sym)
                if not cur_ltp or cur_ltp <= 0:
                    continue

                trigger = float(alert.trigger_level or 0.0)
                if trigger <= 0:
                    continue

                is_bullish = (alert.direction or "BULLISH").upper() == "BULLISH"
                has_ignited = False

                if is_bullish and cur_ltp >= trigger:
                    has_ignited = True
                elif not is_bullish and cur_ltp <= trigger:
                    has_ignited = True

                if has_ignited:
                    with self._lock:
                        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                        alert.stage = "IGNITED"
                        alert.ltp = cur_ltp
                        alert.updated_at = now_str
                        alert.triggered_at = now_str
                        env_tag = (
                            "[TEST]"
                            if (alert.environment == "TEST" or not alert.is_live)
                            else "[REAL/LIVE]"
                        )
                        inst_label = alert.symbol
                        if alert.contract_symbol:
                            from bot.alert_templates import format_contract_display
                            inst_label = format_contract_display(alert.contract_symbol)
                        elif getattr(alert, "strike", None) and getattr(alert, "option_type", None):
                            inst_label = f"{alert.symbol} {int(alert.strike)} {alert.option_type}".strip()

                        dir_str = "BREAKOUT" if is_bullish else "BREAKDOWN"
                        alert.headline = f"🔥 {env_tag} {dir_str} IGNITED: {inst_label} crossed ₹{trigger:,.1f} (LTP: ₹{cur_ltp:,.1f})"
                        alert.summary = (
                            f"Early warning coiling confirmed! {inst_label} triggered {dir_str.lower()} past ₹{trigger:,.1f}. "
                            f"Live quote: ₹{cur_ltp:,.1f}. Invalidation SL: ₹{alert.stop_loss:,.1f} | Target 1: ₹{alert.target_level:,.1f}."
                        )
                        self._save()

                    self._dispatch(alert)
                    ignited_alerts.append(alert)
                    logger.info(
                        f"[AutoAlertEngine] Alert {alert.alert_id} IGNITED: {alert.symbol} crossed trigger {trigger} (LTP={cur_ltp})"
                    )
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Early warning ignition check error for {alert.symbol}: {e}")

        return ignited_alerts

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
        # First, check and ignite any pending early warnings that crossed trigger levels
        self.check_and_ignite_early_warnings(exchanges=exchanges)

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
                    if getattr(eval_res, "strike_roll_recommendation", None):
                        alert.strike_roll_recommendation = eval_res.strike_roll_recommendation

                    env_tag = (
                        "[TEST]"
                        if (alert.environment == "TEST" or not alert.is_live)
                        else "[REAL/LIVE]"
                    )

                    cur_disp_p = cur_quote_ltp or alert.ltp or 0.0
                    if eval_res.new_milestone in ("T0_5_ACHIEVED", "T1_ACHIEVED", "T2_ACHIEVED", "TARGET_ACHIEVED"):
                        if eval_res.new_milestone not in alert.achieved_milestones:
                            alert.achieved_milestones.append(eval_res.new_milestone)
                            try:
                                from engine.learning_engine import pattern_learning_engine

                                outcome_map = {
                                    "T0_5_ACHIEVED": ("WIN_T0_5", 1.0),
                                    "T1_ACHIEVED": ("WIN_T1", 2.0),
                                    "T2_ACHIEVED": ("WIN_T2", 3.5),
                                    "TARGET_ACHIEVED": (
                                        "WIN_TARGET",
                                        max(2.5, float(eval_res.r_multiple or 4.0)),
                                    ),
                                }
                                outcome_str, r_mult = outcome_map.get(
                                    eval_res.new_milestone, ("WIN_TARGET", 2.0)
                                )
                                is_opt_trade = is_alert_option_premium_level(alert) or (
                                    alert.actionable_plan or {}
                                ).get("instrument_type") == "OPTION"
                                if is_opt_trade:
                                    trade_entry = float(
                                        alert.option_premium
                                        or (alert.actionable_plan or {})
                                        .get("trade_plan", {})
                                        .get("entry_price")
                                        or alert.trigger_level
                                        or cur_disp_p
                                    )
                                else:
                                    trade_entry = float(alert.trigger_level or alert.ltp or cur_disp_p)

                                m_factors = (
                                    (alert.metrics or {}).get("matched_factors")
                                    or (alert.metrics or {}).get("confluence_types")
                                    or [alert.alert_type]
                                )
                                pattern_learning_engine.record_trade_outcome(
                                    alert_id=alert.alert_id,
                                    symbol=alert.symbol,
                                    archetype=alert.alert_type,
                                    entry_price=trade_entry,
                                    exit_price=float(cur_disp_p),
                                    outcome=outcome_str,
                                    realized_rr=float(r_mult),
                                    factors_present=m_factors,
                                )
                            except Exception as e_learn:
                                logger.debug(
                                    f"[AutoAlertEngine] Error recording milestone outcome to learning engine: {e_learn}"
                                )

                    inst_label = alert.symbol
                    if alert.contract_symbol:
                        from bot.alert_templates import format_contract_display
                        inst_label = format_contract_display(alert.contract_symbol)
                    elif getattr(alert, "strike", None) and getattr(alert, "option_type", None):
                        inst_label = f"{alert.symbol} {int(alert.strike)} {alert.option_type}".strip()

                    cur_disp_p = cur_quote_ltp or alert.ltp
                    if eval_res.new_milestone == "TARGET_ACHIEVED":
                        if not eval_res.should_trail:
                            alert.stage = "COMPLETED"
                            alert.headline = f"🏁 {env_tag} FINAL TARGET ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                            alert.is_archived = True
                            alert.archived_at = datetime.now(IST).strftime(
                                "%Y-%m-%d %H:%M:%S IST"
                            )
                            alert.archive_reason = "Final target achieved"
                        else:
                            alert.stage = "TARGET_ACHIEVED"
                            alert.headline = f"🎯 {env_tag} FINAL TARGET ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "T2_ACHIEVED":
                        alert.stage = "T2_ACHIEVED"
                        alert.headline = f"🎯 {env_tag} TARGET 2 ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "T1_ACHIEVED":
                        alert.stage = "T1_ACHIEVED"
                        alert.headline = f"🎯 {env_tag} TARGET 1 ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "T0_5_ACHIEVED":
                        alert.stage = "T0_5_ACHIEVED"
                        alert.headline = f"🎯 {env_tag} TARGET 0.5 (SCALE 1) ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "TRAILING_UPDATE":
                        alert.last_trail_alert_time = now_ts
                        alert.stage = "TRAILING_UPDATE"
                        alert.headline = f"📈 {env_tag} TRAILING STOP UPDATED: {inst_label} → ₹{eval_res.recommended_stop:,.2f}"
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
                and a.stage not in ("INVALIDATED", "COMPLETED", "IN_FLIGHT_WARNING", "EARLY_WARNING")
                and (a.stage in ("IGNITED", "TRAILING_UPDATE") or getattr(a, "triggered_at", None) is not None)
                and not getattr(a, "in_flight_warning_sent", False)
                and getattr(a, "target_status", "")
                not in ("T1_ACHIEVED", "FINAL_ACHIEVED", "TARGET_ACHIEVED")
                and "T1_ACHIEVED" not in (getattr(a, "achieved_milestones", []) or [])
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        for alert in active_alerts:
            try:
                # Refresh current quote LTP
                is_opt_prem = is_alert_option_premium_level(alert)
                lookup_sym = (
                    (
                        alert.contract_symbol
                        or (
                            f"{alert.exchange}:{alert.symbol}"
                            if ":" not in alert.symbol
                            else alert.symbol
                        )
                    )
                    if is_opt_prem
                    else (
                        f"{alert.exchange}:{alert.symbol}"
                        if ":" not in alert.symbol
                        else alert.symbol
                    )
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
                logger.debug(
                    f"[AutoAlertEngine] In-flight decay check error for {alert.symbol}: {e}"
                )

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
            headline = (
                f"🌊 [TEST] IN-FLIGHT WARNING: {symbol} (VWAP -1.0σ Institutional Band Breakdown)"
            )
            decision = "SCRATCH_OR_TIGHTEN_TO_VWAP"
            summary = (
                "Price ₹2,810.00 crossed below intraday VWAP -1.0σ band (₹2,822.00, VWAP ₹2,835.00, -0.9%). "
                "Institutional order flow distribution confirmed before nominal Stop-Loss (₹2,800.00) is hit. "
                "DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO VWAP LOWER BAND (₹2,822.00)."
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
                "0DTE option position active for 9m post-13:30 IST with zero momentum (P&L: -5.5%). "
                "Rapid afternoon pin-risk & gamma collapse underway. "
                "DECISION: EXIT 0DTE OPTION IMMEDIATELY TO AVOID PIN-RISK PREMIUM EVAPORATION."
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
                "LTP ₹2,830.00 is within 0.4% of Stop-Loss (₹2,820.00). "
                "75% of risk budget is eroded (P&L: -1.0%). "
                "DECISION: SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO PREVENT FULL CAPITAL LOSS."
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

    def _resolve_index_exchange(self, sym: str) -> str:
        """Resolves BSE for SENSEX/BANKEX, MCX for commodities, otherwise NSE."""
        clean = sym.replace("NSE:", "").replace("BSE:", "").replace("MCX:", "").strip().upper()
        if clean in ("SENSEX", "BANKEX"):
            return "BSE"
        if clean in ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER"):
            return "MCX"
        return "NSE"

    def _get_prioritized_targets(self) -> list[str]:
        """Returns targets with today's expiring index prioritized at position 0."""
        from engine.alert_preferences import alert_preferences

        index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")
        targets = list(self._watched_indices) if index_allowed else []
        if index_allowed:
            now_ist = datetime.now(IST)
            expiry_map = {0: "MIDCPNIFTY", 1: "FINNIFTY", 2: "BANKNIFTY", 3: "NIFTY", 4: "SENSEX"}
            today_expiry = expiry_map.get(now_ist.weekday())
            if today_expiry and today_expiry in targets:
                targets.remove(today_expiry)
                targets.insert(0, today_expiry)
        for s in self.watched_equities:
            if s not in targets:
                targets.append(s)
        return targets

    def scan_gamma_blasts(self) -> list[AutoAlert]:
        """Scans watched indices and high-turnover F&O leaders for Gamma Blast inflection."""
        from market.options import get_options_chain
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym
                spot = get_ltp(lookup_sym)
                if not spot or spot <= 0:
                    continue
                chain = get_options_chain(sym)
                if not chain:
                    continue

                alerts = detect_gamma_blast(sym, spot, chain)
                for a in alerts:
                    if exch == "BSE":
                        a.exchange = "BFO"
                    if self.record_alert(a):
                        found.append(a)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Gamma scan error for {sym}: {e}")

        return found

    def scan_squeeze_breakouts(self) -> list[AutoAlert]:
        """Scans watched indices and equities for multi-timeframe TTM Squeeze early warnings."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp, get_quote

        # Adaptive Market Dynamics: Query India VIX
        vix_val = 14.0
        try:
            from market.indices import get_vix
            v_val = get_vix()
            if v_val and v_val > 0:
                vix_val = float(v_val)
        except Exception:
            pass

        # Low VIX Regime Filter (VIX < 12.5):
        # Under ultra-low volatility, daily Bollinger compressions fail due to whipsaw chop (0% win rate).
        # Daily squeeze is suppressed when VIX < 12.5; 15m squeezes require strict RVOL >= 1.8x and conf >= 85.
        is_low_vix = vix_val < 12.5

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym
                ltp = get_ltp(lookup_sym)
                if not ltp or ltp <= 0:
                    continue

                raw_q = get_quote(lookup_sym)
                q = raw_q.get(lookup_sym) if isinstance(raw_q, dict) else raw_q
                vwap_val = getattr(q, "vwap", None) if q else None

                # Pre-filter optimization: For cash equities, if price is completely flat (< 0.15% change)
                # skip expensive multi-timeframe OHLCV fetching
                if exch == "NSE" and sym not in self._watched_indices:
                    chg = abs(getattr(q, "change_pct", 0.0) or 0.0) if q else 0.0
                    if chg < 0.15:
                        continue

                # 1. First priority: Check 15-minute intraday squeeze
                try:
                    df_15m = get_ohlcv(sym, exchange=exch, interval="15minute", days=5)
                    if df_15m is not None and len(df_15m) >= 20:
                        alert_15m = detect_squeeze_breakout(
                            sym, df_15m, ltp, timeframe="15m", vwap=vwap_val
                        )
                        if alert_15m:
                            # Low-VIX filter on intraday squeezes
                            rvol_15m = (alert_15m.metrics or {}).get("rvol", 1.0)
                            if is_low_vix and (rvol_15m < 1.8 or alert_15m.confidence < 85):
                                pass
                            else:
                                alert_15m.exchange = exch
                                if self.record_alert(alert_15m):
                                    found.append(alert_15m)
                                    continue  # If 15m alert fired, skip daily
                except Exception:
                    pass

                # 2. Daily macro squeeze check (Suppressed in Low-VIX regime to eliminate false breakouts)
                if is_low_vix:
                    continue

                df = get_ohlcv(sym, exchange=exch, interval="day", days=60)
                if df is None or len(df) < 25:
                    continue

                alert = detect_squeeze_breakout(sym, df, ltp, timeframe="day", vwap=vwap_val)
                if alert:
                    alert.exchange = exch
                    if self.record_alert(alert):
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
                    # Provenance & Session gate: mark as TEST if LTP is zero/mock; EOD_SCAN if session closed
                    from market.calendar import is_market_open
                    is_mkt_open = is_market_open(c.exchange or "NSE")
                    is_authentic_pr = bool(
                        c.ltp and c.ltp > 0 and not getattr(c, "_is_mock", False)
                    )
                    pr_env = "LIVE" if (is_authentic_pr and is_mkt_open) else ("EOD_SCAN" if not is_mkt_open else "TEST")
                    pr_live = is_authentic_pr and is_mkt_open

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
                        is_live=pr_live,
                        environment=pr_env,
                        market_status="LIVE" if is_mkt_open else "SESSION_CLOSED",
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

        # Resolve benchmark NIFTY status once for the whole scan batch
        nifty_q = (
            quotes_map.get("NSE:NIFTY 50")
            or quotes_map.get("NSE:NIFTY")
            or quotes_map.get("NIFTY 50")
            or quotes_map.get("NIFTY")
        )
        nifty_chg = float(getattr(nifty_q, "change_pct", 0.0) or 0.0) if nifty_q else 0.0
        nifty_ltp = (
            float(getattr(nifty_q, "last_price", 0.0) or getattr(nifty_q, "ltp", 0.0) or 0.0)
            if nifty_q
            else 0.0
        )
        nifty_vwap = float(getattr(nifty_q, "vwap", 0.0) or 0.0) if nifty_q else 0.0
        is_nifty_markdown = (nifty_chg <= -0.35) and (
            (nifty_ltp < nifty_vwap) if nifty_vwap > 0 else True
        )
        is_nifty_markup = (nifty_chg >= 0.40) and (
            (nifty_ltp > nifty_vwap) if nifty_vwap > 0 else True
        )

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

            seg = classify_symbol_segment(clean_sym)

            # Check turnover gate for equities (₹5 Cr min, or active volume)
            turnover_cr = round((ltp * vol) / 1e7, 2)
            if seg != "INDEX" and turnover_cr < 5.0 and vol < 50000:
                continue

            # Calculate TOD-RVOL (Time-of-Day Relative Volume)
            df = None
            try:
                df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=30)
                if df is not None and len(df) >= 15:
                    vols = df["volume"].values
                    avg_vol = (
                        float(np.mean(vols[-21:-1])) if len(vols) >= 21 else float(np.mean(vols[:-1]))
                    )
                    rvol = compute_time_of_day_rvol(vol, avg_vol, ref_dt=datetime.now(IST))
                else:
                    rvol = 1.0
            except Exception:
                rvol = 1.0

            # Dynamic Inflection Thresholds:
            # Indices: Early coiling at 0.22%, Ignited at 0.50%, RVOL >= 1.35x
            # Equities: Early coiling at 0.85%, Ignited at 1.80%, RVOL >= 1.50x
            min_pos_chg = 0.22 if seg == "INDEX" else 0.85
            min_neg_chg = -0.22 if seg == "INDEX" else -0.80
            min_rvol = 1.35 if seg == "INDEX" else 1.50

            # Opening Range & Session Time Gates (09:15 - 09:45 IST):
            # Before 09:30 IST: Opening 15m range is discovering price — suppress single-stock sparks unless institutional surge (RVOL >= 2.0x, |chg| >= 1.5%).
            # Between 09:30 and 09:45 IST: Require strict institutional confirmation (RVOL >= 2.0x, chg >= 1.2%).
            is_test_env = (os.environ.get("CHANAKYA_TESTING") == "1") or ("PYTEST_CURRENT_TEST" in os.environ)
            if not is_test_env:
                now_dt = datetime.now(IST)
                time_hm = now_dt.hour * 60 + now_dt.minute
                if 555 <= time_hm < 570 and seg != "INDEX":
                    if not (rvol >= 2.0 and abs(chg) >= 1.5):
                        continue
                if 570 <= time_hm < 585:
                    min_rvol = max(min_rvol, 2.0)
                    if seg != "INDEX" and abs(chg) < 1.20:
                        continue

            # Exhaustion & Extension Guard:
            # Reject chasing breakouts/breakdowns that are already stretched >2.5% from VWAP without a base consolidation.
            # Exception: High volume institutional moves (RVOL >= 2.0x) are allowed up to 4.5% extension.
            if vwap > 0:
                vwap_dist_pct = (abs(ltp - vwap) / vwap) * 100.0
                max_allowed_ext = 1.20 if seg == "INDEX" else (4.50 if rvol >= 2.0 else 2.50)
                if vwap_dist_pct > max_allowed_ext:
                    continue


            is_bullish = (chg >= min_pos_chg) and (vwap <= 0 or ltp >= (vwap * 0.998)) and (rvol >= min_rvol)
            is_bearish = (chg <= min_neg_chg) and (vwap > 0 and ltp < (vwap * 1.002)) and (rvol >= min_rvol)

            if not (is_bullish or is_bearish):
                continue

            # Circuit Ceiling / Floor Freeze Guard:
            # If stock is within 0.8% of Upper Circuit, avoid buying into liquidity freeze or circuit dump
            uc = float(getattr(q, "upper_circuit", 0.0) or getattr(q, "circuit_limit", 0.0) or 0.0)
            if uc > 0 and ltp >= (uc * 0.992) and is_bullish:
                continue
            lc = float(getattr(q, "lower_circuit", 0.0) or 0.0)
            if lc > 0 and ltp <= (lc * 1.008) and is_bearish:
                continue

            sec_id = None
            sec_name = None
            sector_tailwind_bonus = 0
            if seg != "INDEX":
                try:
                    from analysis.universe import get_stock_sector

                    sec_id, sec_name = get_stock_sector(clean_sym)
                except Exception:
                    pass

                try:
                    from analysis.sector_rotation import get_stock_tailwind

                    tailwind = get_stock_tailwind(clean_sym)
                    if tailwind and hasattr(tailwind, "quadrant"):
                        if is_bullish:
                            if tailwind.quadrant in ("LEADING", "IMPROVING"):
                                sector_tailwind_bonus = 8
                            elif tailwind.quadrant == "LAGGING" and rvol < 2.2:
                                continue
                        elif is_bearish:
                            if tailwind.quadrant == "LAGGING":
                                sector_tailwind_bonus = 8
                            elif tailwind.quadrant == "LEADING" and rvol < 2.2:
                                continue
                except Exception:
                    pass

            # Benchmark Gravitational Filter: If Nifty in markdown, suppress non-defensive equity sparks
            # Decoupled Exemption: Allow thematic leaders if stock belongs to an RRG Leading / High-Growth sector
            # or exhibits high relative volume (rvol >= 2.0) or strong sector tailwind.
            if is_bullish and is_nifty_markdown and seg != "INDEX" and sec_name:
                is_defensive = any(d in sec_name.upper() for d in ("PHARMA", "FMCG", "HEALTH"))
                is_thematic_leader = any(
                    d in sec_name.upper()
                    for d in ("DEFENCE", "RAIL", "ENERGY", "CAPITAL", "INFRA", "EMS", "TECH", "SOLAR")
                ) or (rvol >= 2.0) or (sector_tailwind_bonus > 0)
                if not (is_defensive or is_thematic_leader):
                    continue

            # Benchmark Gravitational Filter: If Nifty in strong markup, suppress non-lagging equity breakdowns
            if is_bearish and is_nifty_markup and seg != "INDEX" and sec_name:
                is_lagging = any(d in sec_name.upper() for d in ("MEDIA", "REALTY"))
                if not (is_lagging or sector_tailwind_bonus > 0):
                    continue

            # Stage classification: Early Warning (coiling/first thrust) vs Ignited (expanding)
            is_early = (abs(chg) < 0.50) if seg == "INDEX" else (abs(chg) < 1.80)
            stage = "EARLY_WARNING" if is_early else "IGNITED"

            seg_tag = f"[{seg}]"

            if is_bullish:
                direction = "BULLISH"
                alert_type = "INTRADAY_SPARK"
                alert_id = (
                    f"spark-bull-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"
                )
                tp = None
                try:
                    from engine.trade_plan import calculate_trade_plan

                    tp = calculate_trade_plan(
                        symbol=clean_sym,
                        direction="BUY",
                        spot=ltp,
                        timeframe="INTRADAY",
                        exchange="NSE",
                        has_active_blast=True,
                        df=df,
                    )
                except Exception as e_tp:
                    logger.debug(f"[IntradaySpark] Trade plan calculation failed for {clean_sym}: {e_tp}")

                atr_val = max(1.0, ltp * 0.015)
                if df is not None and len(df) >= 5 and "high" in df.columns and "low" in df.columns:
                    try:
                        tr = np.maximum(
                            df["high"] - df["low"],
                            np.maximum(
                                abs(df["high"] - df["close"].shift(1)),
                                abs(df["low"] - df["close"].shift(1)),
                            ),
                        )
                        atr_calc = float(tr.tail(14).mean())
                        if atr_calc > 0:
                            atr_val = round(atr_calc, 2)
                    except Exception:
                        pass
                min_risk = max(1.0, round(0.70 * atr_val, 2)) if seg != "INDEX" else max(1.0, round(0.50 * atr_val, 2))

                if tp and tp.is_asymmetry_viable and tp.target_1 > ltp and tp.invalidation_stop < ltp:
                    risk_pts = max(min_risk, round(ltp - tp.invalidation_stop, 2))
                    sl_price = round(ltp - risk_pts, 2)
                    t1_price = max(tp.target_1, round(ltp + 1.5 * risk_pts, 2))
                    t2_price = max(tp.target_2, round(ltp + 2.5 * risk_pts, 2))
                    t3_price = max(tp.target_3, round(ltp + 4.0 * risk_pts, 2))
                    rr_str = f"1:{round((t1_price - ltp) / risk_pts, 2)}"
                    tp_dict = tp.as_dict()
                else:
                    risk_pts = max(min_risk, round(max(0.8 * atr_val, ltp - vwap if ltp > vwap else ltp * 0.012), 2))
                    sl_price = round(ltp - risk_pts, 2)
                    t1_price = round(ltp + 2.0 * risk_pts, 2)
                    t2_price = round(ltp + 3.5 * risk_pts, 2)
                    t3_price = round(ltp + 5.0 * risk_pts, 2)
                    rr_str = "1:2.0"
                    tp_dict = None

                tick_offset = max(0.05, min(0.5, round(ltp * 0.001, 2)))
                e_min = round(max(sl_price + tick_offset, ltp * 0.998), 1)
                e_max = round(min(t1_price - tick_offset, ltp * 1.005), 1)
                if e_min >= e_max:
                    e_min = round(ltp * 0.998, 1)
                    e_max = round(ltp * 1.005, 1)

                fut_advice = None
                if seg != "INDEX":
                    try:
                        from engine.alert_expiry import (
                            is_monthly_physical_expiry_week,
                            get_last_thursday_of_month,
                            get_next_monthly_expiry_date,
                        )

                        curr_exp_d = get_last_thursday_of_month(now_dt.year, now_dt.month)
                        if is_monthly_physical_expiry_week(
                            curr_exp_d.strftime("%Y-%m-%d"), symbol=clean_sym, ref_dt=now_dt
                        ):
                            next_exp_d = get_next_monthly_expiry_date(now_dt)
                            fut_advice = {
                                "recommended_futures": f"{clean_sym}{next_exp_d.strftime('%y%b').upper()}FUT",
                                "expiry": next_exp_d.strftime("%Y-%m-%d"),
                                "rollover_status": "NEXT_MONTH_FUTURES_RECOMMENDED",
                                "warning": "⚠️ SEBI Physical Settlement Expiry Week: Trade NEXT-MONTH futures to bypass staggered delivery margins (25%->100%).",
                            }
                    except Exception:
                        pass

                headline = f"🚀 INTRADAY SPARK {seg_tag}: {clean_sym} +{chg:.1f}% with {rvol:.1f}x Volume Surge"
                summary = f"{seg_tag} Session breakout underway: Reclaimed VWAP (₹{vwap:,.1f}) with {rvol:.1f}x RVOL. Momentum entry active."
                plan = {
                    "action": "BUY_MOMENTUM",
                    "segment": seg,
                    "entry_range": f"₹{e_min:,.1f} – ₹{e_max:,.1f}",
                    "stop_loss": f"₹{sl_price:,.1f}",
                    "target": f"₹{t1_price:,.1f}",
                    "target_2": f"₹{t2_price:,.1f}",
                    "target_3": f"₹{t3_price:,.1f}",
                    "risk_reward": rr_str,
                    "trade_plan": tp_dict,
                    "derivatives_advice": fut_advice,
                    "when_to_buy": f"Buy on 5m VWAP holding above ₹{vwap:,.1f}",
                    "when_to_wait": f"Do not chase if price extends > {round(chg + 1.5, 1)}%",
                    "profit_rule": "Book 50% at T1 and trail SL to cost; let runner target T2/T3.",
                }
            else:
                direction = "BEARISH"
                alert_type = "INTRADAY_BREAKDOWN_SPARK"
                alert_id = (
                    f"spark-bear-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"
                )
                tp = None
                try:
                    from engine.trade_plan import calculate_trade_plan

                    tp = calculate_trade_plan(
                        symbol=clean_sym,
                        direction="SELL",
                        spot=ltp,
                        timeframe="INTRADAY",
                        exchange="NSE",
                        has_active_blast=True,
                        df=df,
                    )
                except Exception as e_tp:
                    logger.debug(f"[IntradaySpark] Trade plan calculation failed for {clean_sym}: {e_tp}")

                atr_val = max(1.0, ltp * 0.015)
                if df is not None and len(df) >= 5 and "high" in df.columns and "low" in df.columns:
                    try:
                        tr = np.maximum(
                            df["high"] - df["low"],
                            np.maximum(
                                abs(df["high"] - df["close"].shift(1)),
                                abs(df["low"] - df["close"].shift(1)),
                            ),
                        )
                        atr_calc = float(tr.tail(14).mean())
                        if atr_calc > 0:
                            atr_val = round(atr_calc, 2)
                    except Exception:
                        pass
                min_risk = max(1.0, round(0.70 * atr_val, 2)) if seg != "INDEX" else max(1.0, round(0.50 * atr_val, 2))

                if tp and tp.is_asymmetry_viable and tp.target_1 < ltp and tp.invalidation_stop > ltp:
                    risk_pts = max(min_risk, round(tp.invalidation_stop - ltp, 2))
                    sl_price = round(ltp + risk_pts, 2)
                    t1_price = min(tp.target_1, round(max(0.05, ltp - 1.5 * risk_pts), 2))
                    t2_price = min(tp.target_2, round(max(0.05, ltp - 2.5 * risk_pts), 2))
                    t3_price = min(tp.target_3, round(max(0.05, ltp - 4.0 * risk_pts), 2))
                    rr_str = f"1:{round((ltp - t1_price) / risk_pts, 2)}"
                    tp_dict = tp.as_dict()
                else:
                    risk_pts = max(min_risk, round(max(0.8 * atr_val, vwap - ltp if vwap > ltp else ltp * 0.012), 2))
                    sl_price = round(ltp + risk_pts, 2)
                    t1_price = round(max(0.05, ltp - 2.0 * risk_pts), 2)
                    t2_price = round(max(0.05, ltp - 3.5 * risk_pts), 2)
                    t3_price = round(max(0.05, ltp - 5.0 * risk_pts), 2)
                    rr_str = "1:2.0"
                    tp_dict = None

                tick_offset = max(0.05, min(0.5, round(ltp * 0.001, 2)))
                e_max = round(min(sl_price - tick_offset, ltp * 1.002), 1)
                e_min = round(max(t1_price + tick_offset, ltp * 0.995), 1)
                if e_min >= e_max:
                    e_min = round(ltp * 0.995, 1)
                    e_max = round(ltp * 1.002, 1)

                fut_advice = None
                if seg != "INDEX":
                    try:
                        from engine.alert_expiry import (
                            is_monthly_physical_expiry_week,
                            get_last_thursday_of_month,
                            get_next_monthly_expiry_date,
                        )

                        curr_exp_d = get_last_thursday_of_month(now_dt.year, now_dt.month)
                        if is_monthly_physical_expiry_week(
                            curr_exp_d.strftime("%Y-%m-%d"), symbol=clean_sym, ref_dt=now_dt
                        ):
                            next_exp_d = get_next_monthly_expiry_date(now_dt)
                            fut_advice = {
                                "recommended_futures": f"{clean_sym}{next_exp_d.strftime('%y%b').upper()}FUT",
                                "expiry": next_exp_d.strftime("%Y-%m-%d"),
                                "rollover_status": "NEXT_MONTH_FUTURES_RECOMMENDED",
                                "warning": "⚠️ SEBI Physical Settlement Expiry Week: Short NEXT-MONTH futures to bypass staggered delivery margins (25%->100%).",
                            }
                    except Exception:
                        pass

                headline = f"⚡ INTRADAY BREAKDOWN {seg_tag}: {clean_sym} {chg:.1f}% with {rvol:.1f}x Volume Surge"
                summary = f"{seg_tag} Severe session breakdown underway: Lost VWAP (₹{vwap:,.1f}) with {rvol:.1f}x RVOL. Short / Put entry active."
                plan = {
                    "action": "SELL_SHORT_OR_BUY_PUT",
                    "segment": seg,
                    "entry_range": f"₹{e_min:,.1f} – ₹{e_max:,.1f}",
                    "stop_loss": f"₹{sl_price:,.1f}",
                    "target": f"₹{t1_price:,.1f}",
                    "target_2": f"₹{t2_price:,.1f}",
                    "target_3": f"₹{t3_price:,.1f}",
                    "risk_reward": rr_str,
                    "trade_plan": tp_dict,
                    "derivatives_advice": fut_advice,
                    "when_to_buy": f"Enter short or ATM Put on pullbacks to ₹{vwap:,.1f} with tight stop above VWAP.",
                    "when_to_wait": f"Do not chase if breakdown extends > {round(abs(chg) + 1.5, 1)}% without retest.",
                    "profit_rule": "Book 50% at T1 and trail SL to cost; let runner target T2/T3.",
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

            # Multi-Timeframe Alignment, Confirmation Candle, & RSI Divergence on 5m OHLCV
            df_5m = None
            try:
                from market.history import get_ohlcv

                df_5m = get_ohlcv(clean_sym, exchange="NSE", interval="5minute", days=2)
            except Exception:
                df_5m = None

            alignment_count = 1
            if df_5m is not None and len(df_5m) >= 5:
                try:
                    from analysis.market_structure import check_mtf_structural_alignment

                    mtf_info = check_mtf_structural_alignment(
                        clean_sym,
                        exchange="NSE",
                        ltp=ltp,
                        direction=direction,
                        df_5m=df_5m,
                    )
                    alignment_count = mtf_info.get("alignment_count", 1)
                    if mtf_info.get("wall_collision"):
                        logger.debug(
                            f"[AutoAlertEngine] Suppressed spark on {clean_sym}: Proximity to 1H structural wall"
                        )
                        continue
                    if alignment_count < 1 and seg != "INDEX":
                        logger.debug(
                            f"[AutoAlertEngine] Suppressed spark on {clean_sym}: Opposed by 15m/1H structural trend"
                        )
                        continue
                except Exception as e_mtf:
                    logger.debug(f"[AutoAlertEngine] MTF check error for {clean_sym}: {e_mtf}")

            confirmation_bonus = 0
            divergence_bonus = 0
            conf_candle = None
            is_confirmed = False
            div_type = None
            div_bias = None
            if df_5m is not None and len(df_5m) >= 5:
                try:
                    from analysis.market_structure import (
                        detect_confirmation_candle,
                        detect_divergence,
                    )

                    conf_res = detect_confirmation_candle(df_5m, direction=direction)
                    is_confirmed = bool(conf_res.get("confirmed")) if isinstance(conf_res, dict) else False
                    conf_candle = conf_res.get("pattern") if isinstance(conf_res, dict) else None
                    if is_confirmed:
                        confirmation_bonus = 8

                    div_res = detect_divergence(df_5m)
                    div_type = div_res.get("type") if isinstance(div_res, dict) else None
                    div_bias = div_res.get("bias") if isinstance(div_res, dict) else None
                    if div_type == "NONE":
                        div_type = None
                    if div_bias == "NONE":
                        div_bias = None

                    if div_type:
                        if is_bullish and div_bias == "BEARISH" and "REGULAR" in div_type:
                            logger.debug(
                                f"[AutoAlertEngine] Suppressed bullish spark on {clean_sym}: Bearish regular RSI divergence trap ({div_type})"
                            )
                            continue
                        elif is_bearish and div_bias == "BULLISH" and "REGULAR" in div_type:
                            logger.debug(
                                f"[AutoAlertEngine] Suppressed bearish spark on {clean_sym}: Bullish regular RSI divergence trap ({div_type})"
                            )
                            continue
                        elif (is_bullish and div_bias == "BULLISH") or (
                            is_bearish and div_bias == "BEARISH"
                        ):
                            divergence_bonus = 6
                except Exception as e_smc:
                    logger.debug(f"[AutoAlertEngine] Spark candle/divergence check error: {e_smc}")

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage=stage,
                symbol=clean_sym,
                exchange="NSE",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=min(
                    95,
                    int(
                        75
                        + rvol * 5
                        + sector_tailwind_bonus
                        + confirmation_bonus
                        + divergence_bonus
                    ),
                ),
                created_at=now_iso,
                is_live=is_authentic_spark,
                environment="LIVE" if is_authentic_spark else "TEST",
                metrics={
                    "rvol": rvol,
                    "turnover_cr": turnover_cr,
                    "vwap": vwap,
                    "change_pct": chg,
                    "segment": seg,
                    "atr": atr_val,
                    "nifty_change_pct": nifty_chg if nifty_q else None,
                    "nifty_below_vwap": (
                        ((nifty_ltp < nifty_vwap) if nifty_vwap > 0 else (nifty_chg < 0))
                        if nifty_q
                        else None
                    ),
                    "nifty_regime": (
                        (
                            "MARKDOWN"
                            if is_nifty_markdown
                            else ("MARKUP" if is_nifty_markup else "NORMAL")
                        )
                        if nifty_q
                        else "NORMAL"
                    ),
                    "sector_id": sec_id,
                    "sector_name": sec_name,
                    "confirmation_candle": conf_candle,
                    "confirmation_confirmed": is_confirmed,
                    "divergence_type": div_type,
                    "divergence_bias": div_bias,
                    "alignment_count": alignment_count,
                    "sector_tailwind_bonus": sector_tailwind_bonus,
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
                clean_opp_sym = opp.symbol.lower().replace("nse:", "").replace("mcx:", "").strip()
                clean_setup = (getattr(opp, "setup_type", "") or "opp").lower().replace("_", "-")
                alert_id = f"asym-{clean_opp_sym}-{clean_setup}-{datetime.now(IST).strftime('%Y%m%d')}"
                headline = f"🎯 [LOW RISK : HIGH REWARD] {opp.setup_label}: {opp.symbol} (R:R {opp.risk_reward})"
                summary = (
                    f"{opp.catalyst_summary} Invalidation SL: ₹{opp.stop_loss:,.1f} | "
                    f"T1 (+2R): ₹{opp.target_1:,.1f} | T2 (+4R): ₹{opp.target_2:,.1f} | Moonshot: ₹{opp.target_moonshot:,.1f}"
                )

                if opp.exchange == "MCX" or getattr(opp, "setup_type", "") == "COMMODITY":
                    asym_seg = "COMMODITY"
                elif opp.symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX") or getattr(opp, "setup_type", "") == "EXPIRY_0DTE_GAMMA":
                    asym_seg = "FNO_INDEX"
                else:
                    asym_seg = "EQUITY"

                plan = {
                    "action": opp.setup_type,
                    "segment": asym_seg,
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
                    plan["contract"] = opp.contract_symbol
                    plan["instrument"] = opp.contract_symbol
                    plan["instrument_type"] = "OPTION"
                    plan["action"] = f"BUY {opp.option_type}" if opp.option_type else "BUY_OPTION"
                    plan["option_type"] = opp.option_type
                    plan["recommended_entry"] = f"₹{opp.option_premium:,.2f}" if opp.option_premium else opp.entry_range
                    if opp.option_premium:
                        plan["entry_range"] = f"₹{round(opp.option_premium * 0.96, 1):,.1f} – ₹{round(opp.option_premium * 1.04, 1):,.1f}"
                    if opp.option_stop_loss:
                        plan["stop_loss"] = f"₹{opp.option_stop_loss:,.1f}"
                    if opp.option_target_1:
                        plan["target"] = f"₹{opp.option_target_1:,.1f}"
                        plan["target_1"] = f"₹{opp.option_target_1:,.1f}"
                    if opp.option_target_2:
                        plan["target_2"] = f"₹{opp.option_target_2:,.1f}"
                    plan["underlying_spot"] = f"₹{opp.ltp:,.1f}"
                    plan["underlying_sl"] = f"₹{opp.stop_loss:,.1f}"
                    plan["underlying_target"] = f"₹{opp.target_1:,.1f}"
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

                has_opt_leg = bool(opp.contract_symbol and opp.option_premium)
                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="ASYMMETRIC_OPPORTUNITY",
                    stage="EARLY_WARNING",
                    symbol=opp.symbol,
                    exchange=opp.exchange,
                    direction=opp.direction,
                    headline=headline,
                    summary=summary,
                    ltp=opp.option_premium if has_opt_leg else opp.ltp,
                    trigger_level=opp.option_premium if has_opt_leg else opp.entry_price,
                    target_level=opp.option_target_1 if has_opt_leg else opp.target_1,
                    stop_loss=opp.option_stop_loss if has_opt_leg else opp.stop_loss,
                    strike=opp.strike if has_opt_leg else None,
                    option_type=opp.option_type if has_opt_leg else None,
                    contract_symbol=opp.contract_symbol if has_opt_leg else None,
                    expiry_date=opp.expiry_date if has_opt_leg else None,
                    option_premium=opp.option_premium if has_opt_leg else None,
                    underlying_spot=opp.ltp,
                    lot_size=opp.lot_size if has_opt_leg else None,
                    segment=(
                        "FNO_INDEX"
                        if opp.symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
                        or getattr(opp, "segment", "") == "INDEX"
                        else asym_seg
                    ),
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
        from engine.alert_preferences import alert_preferences

        found: list[AutoAlert] = []
        index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")
        targets = list(self._watched_indices) if index_allowed else []
        for s in self.watched_equities:
            if s not in targets:
                targets.append(s)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        now_dt = datetime.now(IST)
        is_friday_late = (now_dt.weekday() == 4) and (
            now_dt.hour > 14 or (now_dt.hour == 14 and now_dt.minute >= 30)
        )
        is_opening_drive = (now_dt.hour == 9 and now_dt.minute <= 45)

        # Resolve benchmark NIFTY regime once for the scan cycle
        nifty_change = None
        nifty_below_vwap = None
        try:
            from market.quotes import get_quote

            nq = get_quote("NSE:NIFTY 50")
            q_obj = nq.get("NSE:NIFTY 50") or nq.get("NIFTY 50") if isinstance(nq, dict) else nq
            if q_obj:
                n_ltp = float(
                    getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0
                )
                n_vwap = float(getattr(q_obj, "vwap", 0.0) or 0.0)
                n_chg = float(getattr(q_obj, "change_pct", 0.0) or 0.0)
                if n_ltp > 0:
                    nifty_change = n_chg
                    nifty_below_vwap = (n_ltp < n_vwap) if n_vwap > 0 else (n_chg < 0)
        except Exception:
            pass
        is_nifty_markdown = (
            nifty_change is not None and nifty_change <= -0.35 and nifty_below_vwap is not False
        )
        is_nifty_markup = (
            nifty_change is not None and nifty_change >= 0.40 and nifty_below_vwap is False
        )

        # Stage 1: Fast Batch-fetch underlying spot quotes for all targets in one call (<150ms)
        from market.quotes import get_quote, get_ltp

        formatted_targets = [f"{self._resolve_index_exchange(s)}:{s}" for s in targets]
        batch_quotes = {}
        try:
            batch_quotes = get_quote(formatted_targets)
        except Exception as e_batch:
            logger.debug(f"[AutoAlertEngine] Batch quote pre-fetch error: {e_batch}")

        for sym in targets:
            clean_sym = sym.replace("NSE:", "").replace("NFO:", "").replace("BSE:", "").strip().upper()
            try:
                exch = self._resolve_index_exchange(clean_sym)
                lookup_sym = f"{exch}:{clean_sym}"
                quote_obj = batch_quotes.get(lookup_sym) or batch_quotes.get(clean_sym)
                spot = (
                    float(getattr(quote_obj, "last_price", 0.0) or getattr(quote_obj, "ltp", 0.0) or 0.0)
                    if quote_obj
                    else 0.0
                )
                if spot <= 0:
                    spot = get_ltp(lookup_sym) or 0.0
                if spot <= 0:
                    continue

                spot_change_pct = float(getattr(quote_obj, "change_pct", 0.0) or 0.0) if quote_obj else 0.0
                spot_open = float(getattr(quote_obj, "open", 0.0) or 0.0) if quote_obj else 0.0
                spot_high = float(getattr(quote_obj, "high", 0.0) or 0.0) if quote_obj else 0.0
                spot_low = float(getattr(quote_obj, "low", 0.0) or 0.0) if quote_obj else 0.0
                spot_vwap = float(getattr(quote_obj, "vwap", 0.0) or 0.0) if quote_obj else 0.0

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

                # ── STAGE 1: SPOT MOVEMENT & OPENING DRIVE PRE-FILTER ──
                # For single-stock F&O, skip expensive options chain extraction if the underlying stock
                # is completely flat and inactive today (0 momentum, 0 displacement from VWAP).
                is_bear_drive = False
                is_bull_drive = False
                if not is_idx:
                    if spot_open > 0:
                        if (
                            spot_high > 0
                            and (abs(spot_high - spot_open) / spot_open <= 0.0015)
                            and spot_change_pct <= -0.4
                        ):
                            is_bear_drive = True  # Open = High Bearish Liquidation Drive (e.g. OFSS)
                        elif (
                            spot_low > 0
                            and (abs(spot_low - spot_open) / spot_open <= 0.0015)
                            and spot_change_pct >= 0.4
                        ):
                            is_bull_drive = True  # Open = Low Bullish Institutional Sweep (e.g. MFSL/HDFCLIFE)

                    is_vwap_displaced = bool(spot_vwap > 0 and abs(spot - spot_vwap) / spot_vwap >= 0.005)
                    is_momentum_active = bool(abs(spot_change_pct) >= 0.80)

                    if (spot_open > 0 or spot_vwap > 0 or spot_change_pct != 0.0) and not (
                        is_momentum_active or is_bear_drive or is_bull_drive or is_vwap_displaced
                    ):
                        # Stock is flat and inactive today (skips ~180 sideways stocks in 0.0001s)
                        continue

                # Institutional Single-Stock Expiry Protection:
                # Under SEBI regulations, single-stock options are physically settled.
                # In settlement week (DTE <= 4), automatically route stock options to Next-Month
                # series to eliminate staggered physical delivery margins (25%->100%) and near-month theta collapse.
                chain = None
                is_next_month_routed = False
                if not is_idx:
                    try:
                        from engine.alert_expiry import (
                            is_monthly_physical_expiry_week,
                            resolve_recommended_derivative_expiry,
                        )
                        from market.options import get_expiries

                        available_exps = get_expiries(clean_sym)
                        exp_res = resolve_recommended_derivative_expiry(
                            symbol=clean_sym,
                            instrument_type="OPTION",
                            available_expiries=available_exps,
                            ref_dt=now_dt,
                        )
                        if exp_res.get("is_next_month_routed"):
                            next_exp_str = exp_res.get("recommended_expiry")
                            next_chain = get_options_chain(clean_sym, expiry=next_exp_str)
                            if next_chain and any(
                                float(getattr(c, "last_price", 0.0) or 0.0) > 0 for c in next_chain
                            ):
                                chain = next_chain
                                is_next_month_routed = True
                    except Exception as e_exp:
                        logger.debug(
                            f"[AutoAlertEngine] Next-month rollover check failed for {clean_sym}: {e_exp}"
                        )

                if chain is None:
                    chain = get_options_chain(clean_sym)

                if not chain:
                    continue
                min_opt_volume = (
                    (2000 if is_idx else 300) if is_opening_drive else (3000 if is_idx else 500)
                )
                min_oi = 10000 if is_idx else 300

                # Delta-Gated Sweet-Spot Filter: Restrict primary index alerts to ATM and near-the-money (<= 2 strikes)
                # Avoids far OTM lottery traps (e.g. 23100 PE when spot is 23395) while capturing high-delta institutional momentum.
                max_strike_dist = (
                    (
                        120.0
                        if clean_sym in ("NIFTY", "FINNIFTY")
                        else (
                            250.0
                            if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX")
                            else (75.0 if clean_sym in ("MIDCPNIFTY",) else 100.0)
                        )
                    )
                    if is_idx
                    else spot * 0.02
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
                if not atm_contracts:
                    continue

                # Sort ATM contracts by proximity to spot (closest to ATM first!)
                atm_contracts.sort(key=lambda c: abs(getattr(c, "strike", 0.0) - spot))

                # ── Underlying Price Action & SMC Due Diligence (computed only if liquid ATM contracts exist) ──
                from market.history import get_ohlcv

                df_5m = None
                try:
                    df_5m = get_ohlcv(clean_sym, exchange=exch, interval="5minute", days=2)
                except Exception:
                    pass

                if df_5m is not None and len(df_5m) >= 1:
                    try:
                        last_c = float(
                            df_5m.iloc[-1].get("close", df_5m.iloc[-1].get("Close", 0.0))
                        )
                        if last_c > 0 and abs(last_c - spot) / max(1.0, spot) > 0.02:
                            df_5m = None
                    except Exception:
                        pass

                # Derive 5m intraday VWAP if not provided by quote
                if (not spot_vwap or spot_vwap <= 0) and df_5m is not None and len(df_5m) >= 2:
                    try:
                        vols = df_5m["volume"].values
                        highs = (
                            df_5m["high"].values
                            if "high" in df_5m.columns
                            else df_5m["High"].values
                        )
                        lows = (
                            df_5m["low"].values if "low" in df_5m.columns else df_5m["Low"].values
                        )
                        closes = (
                            df_5m["close"].values
                            if "close" in df_5m.columns
                            else df_5m["Close"].values
                        )
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
                candle_range = 0.0
                if df_5m is not None and len(df_5m) >= 1:
                    try:
                        last_bar = df_5m.iloc[-1]
                        b_high = float(last_bar.get("high", last_bar.get("High", 0.0)))
                        b_low = float(last_bar.get("low", last_bar.get("Low", 0.0)))
                        b_open = float(last_bar.get("open", last_bar.get("Open", 0.0)))
                        b_close = float(last_bar.get("close", last_bar.get("Close", 0.0)))
                        candle_range = max(0.01, b_high - b_low)
                        upper_wick_ratio = (b_high - max(b_open, b_close)) / candle_range
                        lower_wick_ratio = (min(b_open, b_close) - b_low) / candle_range
                    except Exception:
                        pass

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

                    # 0DTE Expiry Day Afternoon Theta Guard:
                    # After 12:30 IST on expiry day, exponential theta decay rapidly destroys OTM value.
                    # Restrict option buying to strictly ATM or In-The-Money (ITM) contracts only.
                    is_zero_dte_pm = False
                    if expiry_date:
                        try:
                            from engine.alert_expiry import is_0dte_afternoon
                            is_zero_dte_pm = is_0dte_afternoon(str(expiry_date), ref_dt=now_dt)
                            if is_zero_dte_pm:
                                if opt_type == "CE" and strike > (spot * 1.002):
                                    continue
                                if opt_type == "PE" and strike < (spot * 0.998):
                                    continue
                        except Exception:
                            pass

                    # Momentum DTE Gate: NIFTY allows weekly (DTE <= 8), monthly indices/stocks allow front-month & next-month rollovers (DTE <= 45)
                    max_dte = 8 if clean_sym in ("NIFTY",) else 45
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
                            if exp_dt and (exp_dt - now_dt.date()).days > max_dte:
                                continue
                        except Exception:
                            pass

                    # Momentum criteria: active turnover and volume velocity.
                    # During opening drive (09:15 - 09:45 IST), volume builds rapidly but cumulative OI
                    # Momentum criteria: active turnover and volume velocity.
                    # Require authentic institutional participation:
                    # Minimum 1.0x Vol/OI during opening drive, 1.2x post-opening, with contract turnover floor.
                    if is_opening_drive:
                        min_vol_oi = 0.60 if is_idx else 1.00
                        min_contracts = 2000 if is_idx else 500
                    else:
                        min_vol_oi = 1.00 if is_idx else 1.20
                        min_contracts = 2500 if is_idx else 600

                    if vol_oi < min_vol_oi or vol < min_contracts:
                        continue

                    # 1. Bid/Ask Spread Sanity Gate:
                    # Index options allow up to 30% spread friction; single-stock options strictly <= 15%
                    bid = getattr(c, "bid", None)
                    ask = getattr(c, "ask", None)
                    max_spread_mult = 1.30 if is_idx else 1.15
                    if bid and ask and bid > 0 and ask > 0 and ask > (bid * max_spread_mult):
                        continue

                    # 1b. Physical Delivery Expiry Week Detection for Stock Options
                    is_physical_expiry_week = False
                    if not is_idx and expiry_date:
                        try:
                            from engine.alert_expiry import is_monthly_physical_expiry_week
                            is_physical_expiry_week = is_monthly_physical_expiry_week(str(expiry_date), symbol=clean_sym, ref_dt=now_dt)
                        except Exception:
                            pass

                    # 2. Strict Directional Price Expansion & Underlying Trend Alignment:
                    # An option momentum breakout MUST have positive price expansion (gainers, not decaying/dumping)
                    # AND the underlying stock must be aligned with the trade direction.
                    pchange = getattr(c, "pchange", None)
                    min_pchange = 8.0 if is_opening_drive else 6.0
                    if opt_type == "CE":
                        # CALL SURGE: Option premium must be expanding positively (minimum 6% expansion, 8% at open)
                        if pchange is not None and pchange < min_pchange:
                            continue
                        # Underlying stock must NOT be collapsing in a severe downtrend (reject crashing stocks)
                        if spot_change_pct is not None and spot_change_pct < -1.5:
                            continue
                        if spot_open and spot_open > 0 and spot < spot_open * 0.995:
                            continue
                        # Spot must hold intraday VWAP
                        if is_idx:
                            if spot_vwap and spot_vwap > 0 and spot < spot_vwap:
                                continue
                        else:
                            if spot_vwap and spot_vwap > 0 and spot < spot_vwap * 1.0005:
                                continue
                        # Upper-wick rejection / buying climax gate (reject shooting star rejections on wide bars)
                        if candle_range >= (spot * 0.0025) and upper_wick_ratio > 0.50:
                            continue
                        direction = "BULLISH"
                    elif opt_type == "PE":
                        # PUT SURGE: Option premium must be expanding positively (minimum 6% expansion, 8% at open)
                        if pchange is not None and pchange < min_pchange:
                            continue
                        # Underlying stock must NOT be surging in a severe uptrend
                        if spot_change_pct is not None and spot_change_pct > 1.5:
                            continue
                        if spot_open and spot_open > 0 and spot > spot_open * 1.005:
                            continue
                        # Spot must be below intraday VWAP
                        if is_idx:
                            if spot_vwap and spot_vwap > 0 and spot > spot_vwap:
                                continue
                        else:
                            if spot_vwap and spot_vwap > 0 and spot > spot_vwap * 0.9995:
                                continue
                        # Lower-wick rejection / selling climax gate (reject hammer absorption on wide bars)
                        if candle_range >= (spot * 0.0025) and lower_wick_ratio > 0.50:
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
                            ema50_15 = (
                                float(c_15.ewm(span=50, adjust=False).mean().iloc[-1])
                                if len(c_15) >= 40
                                else ema20_15
                            )
                            if spot >= (ema20_15 * 0.998) and ema20_15 >= (ema50_15 * 0.998):
                                mtf_15m_trend = "BULLISH"
                            elif spot <= (ema20_15 * 1.002) and ema20_15 <= (ema50_15 * 1.002):
                                mtf_15m_trend = "BEARISH"
                    except Exception as e_mtf:
                        logger.debug(
                            f"[AutoAlertEngine] MTF 15m fetch failed for {clean_sym}: {e_mtf}"
                        )

                    # Reject counter-trend breakout traps against 15m structural trend,
                    # UNLESS intraday price action has decisively confirmed an opening breakout/breakdown:
                    # (For PE: spot broken below Day Open or below intraday VWAP)
                    # (For CE: spot broken above Day Open or above intraday VWAP)
                    has_opening_breakdown = bool(
                        (spot_open and spot <= spot_open * 0.998)
                        or (spot_vwap and spot <= spot_vwap * 1.001)
                    )
                    has_opening_breakout = bool(
                        (spot_open and spot >= spot_open * 1.002)
                        or (spot_vwap and spot >= spot_vwap * 0.999)
                    )

                    if opt_type == "CE" and mtf_15m_trend == "BEARISH" and not has_opening_breakout:
                        logger.debug(
                            f"[AutoAlertEngine] Suppressed Call breakout on {clean_sym}: 15m trend is BEARISH"
                        )
                        continue
                    if opt_type == "PE" and mtf_15m_trend == "BULLISH" and not has_opening_breakdown:
                        logger.debug(
                            f"[AutoAlertEngine] Suppressed Put surge on {clean_sym}: 15m trend is BULLISH (Opening breakdown active: {has_opening_breakdown})"
                        )
                        continue

                    # Benchmark Gravitational & Sector RRG Tailwind Filter on single-stock options:
                    sector_tailwind_bonus = 0
                    if not is_idx:
                        try:
                            from analysis.sector_rotation import get_stock_tailwind

                            tailwind = get_stock_tailwind(clean_sym)
                            if tailwind and hasattr(tailwind, "quadrant"):
                                if opt_type == "CE":
                                    if tailwind.quadrant in ("LEADING", "IMPROVING"):
                                        sector_tailwind_bonus = 8
                                    elif tailwind.quadrant == "LAGGING" and not (vol_oi >= 2.5):
                                        logger.debug(
                                            f"[AutoAlertEngine] Suppressed Call on {clean_sym}: Sector in LAGGING RRG quadrant ({getattr(tailwind, 'sector', '')})"
                                        )
                                        continue
                                elif opt_type == "PE":
                                    if tailwind.quadrant == "LAGGING":
                                        sector_tailwind_bonus = 8
                                    elif tailwind.quadrant == "LEADING" and not (vol_oi >= 2.5):
                                        logger.debug(
                                            f"[AutoAlertEngine] Suppressed Put on {clean_sym}: Sector in LEADING RRG quadrant ({getattr(tailwind, 'sector', '')})"
                                        )
                                        continue
                        except Exception as e_rrg:
                            logger.debug(
                                f"[AutoAlertEngine] RRG tailwind check error for {clean_sym}: {e_rrg}"
                            )

                    if not is_idx and is_nifty_markdown and opt_type == "CE":
                        from analysis.universe import get_stock_sector

                        sec_id, sec_name = get_stock_sector(clean_sym)
                        is_defensive = any(
                            d in (sec_name or "").upper() for d in ("PHARMA", "FMCG", "HEALTH")
                        )
                        is_thematic = any(
                            d in (sec_name or "").upper()
                            for d in ("DEFENCE", "RAIL", "ENERGY", "CAPITAL", "INFRA", "EMS", "TECH", "SOLAR")
                        )
                        if not (is_defensive or is_thematic or sector_tailwind_bonus > 0):
                            logger.debug(
                                f"[AutoAlertEngine] Suppressed Call breakout on {clean_sym}: NIFTY in structural markdown ({nifty_change:.2f}%)"
                            )
                            continue

                    if not is_idx and is_nifty_markup and opt_type == "PE":
                        from analysis.universe import get_stock_sector

                        sec_id, sec_name = get_stock_sector(clean_sym)
                        is_lagging = any(d in sec_name.upper() for d in ("MEDIA", "REALTY"))
                        if not (is_lagging or sector_tailwind_bonus > 0):
                            logger.debug(
                                f"[AutoAlertEngine] Suppressed Put surge on {clean_sym}: NIFTY in structural markup (+{nifty_change:.2f}%)"
                            )
                            continue

                    # 2c. Options Delta-OI Institutional Confirmation Gate:
                    # For Calls: If Call writers are aggressively stacking fresh OI while spot is below VWAP,
                    # this is an institutional Call Writing Resistance Wall, NOT a bullish breakout!
                    is_gamma_squeeze = False
                    if opt_type == "CE":
                        if oi_change and oi_change < 0:
                            is_gamma_squeeze = True  # Call short covering
                        elif oi_change and oi_change > 0 and spot_vwap and spot < spot_vwap:
                            logger.debug(
                                f"[AutoAlertEngine] Suppressed CE on {clean_sym}: Call writing resistance wall (OI +{oi_change} below VWAP)"
                            )
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

                    # 2e. Candlestick Trigger Confirmation & RSI Divergence Trap Gate on Underlying Spot
                    confirmation_bonus = 0
                    divergence_bonus = 0
                    conf_candle = None
                    is_confirmed = False
                    div_type = None
                    div_bias = None
                    if df_5m is not None and len(df_5m) >= 5:
                        try:
                            from analysis.market_structure import (
                                detect_confirmation_candle,
                                detect_divergence,
                            )

                            conf_res = detect_confirmation_candle(
                                df_5m, direction=direction
                            )
                            is_confirmed = bool(conf_res.get("confirmed")) if isinstance(conf_res, dict) else False
                            conf_candle = conf_res.get("pattern") if isinstance(conf_res, dict) else None
                            if is_confirmed:
                                confirmation_bonus = 8

                            div_res = detect_divergence(df_5m)
                            div_type = div_res.get("type") if isinstance(div_res, dict) else None
                            div_bias = div_res.get("bias") if isinstance(div_res, dict) else None
                            if div_type == "NONE":
                                div_type = None
                            if div_bias == "NONE":
                                div_bias = None

                            if div_type:
                                if opt_type == "CE" and div_bias == "BEARISH" and "REGULAR" in div_type:
                                    logger.debug(
                                        f"[AutoAlertEngine] Suppressed CE on {clean_sym}: Bearish regular RSI divergence trap ({div_type})"
                                    )
                                    continue
                                elif opt_type == "PE" and div_bias == "BULLISH" and "REGULAR" in div_type:
                                    logger.debug(
                                        f"[AutoAlertEngine] Suppressed PE on {clean_sym}: Bullish regular RSI divergence trap ({div_type})"
                                    )
                                    continue
                                elif (opt_type == "CE" and div_bias == "BULLISH") or (
                                    opt_type == "PE" and div_bias == "BEARISH"
                                ):
                                    divergence_bonus = 6
                        except Exception as e_smc:
                            logger.debug(
                                f"[AutoAlertEngine] SMC candle/divergence check error for {clean_sym}: {e_smc}"
                            )

                    # 2f. 5-Strategy Signal Ensemble Veto Gate
                    if df_5m is not None and len(df_5m) >= 10:
                        try:
                            from analysis.market_structure import ensemble_signal

                            ens = ensemble_signal(df_5m)
                            if ens and getattr(ens, "confidence", 0) >= 55:
                                ens_sig = str(getattr(ens, "signal", "")).upper()
                                if (opt_type == "CE" and "SELL" in ens_sig) or (
                                    opt_type == "PE" and "BUY" in ens_sig
                                ):
                                    logger.debug(
                                        f"[AutoAlertEngine] Suppressed {opt_type} on {clean_sym}: Ensemble veto ({ens_sig} {ens.confidence}%)"
                                    )
                                    continue
                        except Exception as e_ens:
                            logger.debug(
                                f"[AutoAlertEngine] Ensemble veto error for {clean_sym}: {e_ens}"
                            )

                    # 2g. Volume Profile POC Proximity & Confluence Bonus
                    vp_bonus = 0
                    vp_tags = []
                    if df_5m is not None and len(df_5m) >= 10:
                        try:
                            from analysis.volume_profile import compute_volume_profile

                            vp = compute_volume_profile(df_5m)
                            if vp and getattr(vp, "poc", 0) > 0:
                                poc_dist = abs(spot - vp.poc) / max(1.0, spot)
                                if opt_type == "CE" and spot >= vp.vah * 0.998:
                                    vp_bonus += 5
                                    vp_tags.append("VAH_BREAKOUT")
                                elif opt_type == "CE" and poc_dist <= 0.003:
                                    vp_bonus += 4
                                    vp_tags.append("POC_SUPPORT_BOUNCE")
                                elif opt_type == "PE" and spot <= vp.val * 1.002:
                                    vp_bonus += 5
                                    vp_tags.append("VAL_BREAKDOWN")
                                elif opt_type == "PE" and poc_dist <= 0.003:
                                    vp_bonus += 4
                                    vp_tags.append("POC_RESISTANCE_REJECT")
                        except Exception as e_vp:
                            logger.debug(
                                f"[AutoAlertEngine] Volume profile error for {clean_sym}: {e_vp}"
                            )

                    alert_id = f"aa-optmom-{opt_type.lower()}-{clean_sym}-{int(strike)}-{uuid.uuid4().hex[:6]}"

                    # 3. Dynamic Spot-Anchored Trade Plan & Invalidation (Institutional Greeks)
                    tp = None
                    opt_plan = None
                    try:
                        from engine.trade_plan import (
                            calculate_trade_plan,
                            calculate_option_execution_plan,
                        )

                        opt_exchange = "BFO" if exch == "BSE" else "NFO"
                        tp = calculate_trade_plan(
                            symbol=clean_sym,
                            direction="BUY" if opt_type == "CE" else "SELL",
                            spot=spot,
                            timeframe="INTRADAY",
                            exchange=opt_exchange,
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
                        # Enforce defined risk realistic stop for Options Momentum (cap risk at 28% of premium to prevent noise stops):
                        max_opt_sl_risk = round(opt_ltp * 0.28, 2)
                        opt_sl = max(opt_sl, round(opt_ltp - max_opt_sl_risk, 2))
                        opt_risk = max(0.2, opt_ltp - opt_sl)
                        opt_t0_5 = round(opt_ltp + 1.0 * opt_risk, 2)
                        opt_t1 = max(float(opt_plan.get("t1_premium") or 0.0), round(opt_ltp + 1.8 * opt_risk, 2))
                        opt_t2 = max(
                            float(opt_plan.get("t2_premium") or 0.0), round(opt_ltp + 3.0 * opt_risk, 2)
                        )
                        opt_moonshot = max(
                            float(opt_plan.get("t3_premium") or 0.0), round(opt_ltp + 5.0 * opt_risk, 2)
                        )
                        rr_val = round((opt_t1 - opt_ltp) / max(0.01, opt_risk), 1)
                        rr_str = f"1:{rr_val}"
                    else:
                        # Structural defined risk stop for intraday options (25%–28% risk buffer)
                        risk_pts = round(max(0.20, min(opt_ltp * 0.28, opt_ltp - 0.05)), 2)
                        opt_sl = round(max(0.05, opt_ltp - risk_pts), 2)
                        opt_t0_5 = round(opt_ltp + 1.0 * risk_pts, 2)
                        opt_t1 = round(opt_ltp + 1.8 * risk_pts, 2)
                        opt_t2 = round(opt_ltp + 3.0 * risk_pts, 2)
                        opt_moonshot = round(opt_ltp + 5.0 * risk_pts, 2)
                        rr_str = "1:1.8"

                    # 4. Friday Session Clock & Weekend Theta Decay Filter
                    friday_tag = (
                        " ⚠️ FRIDAY POST-14:30: Weekend theta decay risk; Intraday Quick Scalp only (Square off by 15:20 IST) or trade Bull Call Spread."
                        if is_friday_late
                        else ""
                    )
                    dte_pm_tag = (
                        " ⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by 15:15 IST."
                        if is_zero_dte_pm
                        else ""
                    )
                    phys_tag = (
                        " ⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). INTRADAY SCALP ONLY — MANDATORY EXIT BY 15:00 IST."
                        if (is_physical_expiry_week and not is_next_month_routed)
                        else ""
                    )
                    rollover_tag = (
                        f" 🎯 NEXT-MONTH ROLLOVER ({expiry_date}): Bypasses SEBI physical delivery margin surge & near-month theta collapse."
                        if is_next_month_routed
                        else ""
                    )

                    # 5. Multi-factor Institutional Conviction Scoring (Earned 50-96 scale)
                    # Lower base score from 65 to 50 so mediocre setups don't falsely max out at 95%
                    conf_score = 50

                    # A. Volume / OI Ratio conviction (up to +20 pts)
                    if vol_oi >= 3.0:
                        conf_score += 20
                    elif vol_oi >= 2.0:
                        conf_score += 15
                    elif vol_oi >= 1.5:
                        conf_score += 10
                    elif vol_oi >= 1.2:
                        conf_score += 5

                    # B. Option Price Expansion (+5 to +15 pts)
                    opt_pch = getattr(c, "pchange", 0.0) or 0.0
                    if opt_pch >= 20.0:
                        conf_score += 15
                    elif opt_pch >= 12.0:
                        conf_score += 10
                    elif opt_pch >= 6.0:
                        conf_score += 5

                    # C. Underlying Stock Expansion from VWAP (+5 to +12 pts)
                    if spot_vwap and spot_vwap > 0:
                        vwap_dist_pct = abs(spot - spot_vwap) / spot_vwap * 100.0
                        if opt_type == "CE" and spot >= spot_vwap * 1.005:
                            conf_score += 12 if vwap_dist_pct >= 0.8 else 8
                        elif opt_type == "PE" and spot <= spot_vwap * 0.995:
                            conf_score += 12 if vwap_dist_pct >= 0.8 else 8
                        elif (opt_type == "CE" and spot >= spot_vwap) or (opt_type == "PE" and spot <= spot_vwap):
                            conf_score += 4

                    # D. Mathematical Asymmetry Viability (+8 pts)
                    if tp and tp.is_asymmetry_viable:
                        conf_score += 8

                    # E. Candlestick Cleanliness (low wicks = clean trend, +5 pts)
                    if upper_wick_ratio <= 0.20 and lower_wick_ratio <= 0.20:
                        conf_score += 5

                    # F. Gamma Squeeze / Short Covering (+7 pts)
                    if is_gamma_squeeze:
                        conf_score += 7
                    elif oi_change and oi_change < 0:
                        conf_score += 4

                    # G. MTF 15m Alignment (+7 pts)
                    if mtf_15m_trend == ("BULLISH" if opt_type == "CE" else "BEARISH"):
                        conf_score += 7

                    # H. Macro Tailwind (+6 pts)
                    if is_nifty_markdown and opt_type == "PE":
                        conf_score += 6
                    elif is_nifty_markup and opt_type == "CE":
                        conf_score += 6

                    # I. Opening Drive Institutional Bonus (+10 pts)
                    opening_drive_bonus = 0
                    drive_tag = ""
                    if is_bear_drive and opt_type == "PE":
                        opening_drive_bonus = 10
                        drive_tag = " ⚡ OPENING DRIVE (Open=High)"
                    elif is_bull_drive and opt_type == "CE":
                        opening_drive_bonus = 10
                        drive_tag = " ⚡ OPENING DRIVE (Open=Low)"

                    conf_score += confirmation_bonus
                    conf_score += divergence_bonus
                    conf_score += vp_bonus
                    conf_score += sector_tailwind_bonus
                    conf_score += opening_drive_bonus

                    confidence = min(96, max(50, conf_score))

                    # 6. Optimal Trade Entry (OTE) & Strict No-Chase Boundaries
                    ote_lower = round(max(0.05, opt_ltp * 0.96), 1)
                    ote_upper = round(opt_ltp * 1.01, 1)
                    max_chase = round(opt_ltp * 1.08, 1)
                    entry_range_str = f"₹{ote_lower:,.1f} – ₹{ote_upper:,.1f}"
                    when_to_wait_str = f"DO NOT CHASE if premium surges > 8% past entry (> ₹{max_chase:,.1f}). Wait for 5m consolidation retest."
                    spot_anchor_str = (
                        f" (Spot Anchor: ₹{tp.invalidation_stop:,.1f})"
                        if (tp and tp.invalidation_stop > 0)
                        else ""
                    )
                    when_to_buy_str = (
                        f"Buy on ask/limit within entry range with spot invalidation anchor at ₹{tp.invalidation_stop:,.1f} (Option SL ₹{opt_sl:,.1f})."
                        if (tp and tp.invalidation_stop > 0)
                        else f"Buy on ask/limit within entry range with tight defined risk below ₹{opt_sl:,.1f}."
                    )

                    if opt_type == "PE":
                        headline = f"🎯 OPTIONS MOMENTUM (PUT SURGE): {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
                        summary = (
                            f"Institutional Put surge in {clean_sym} {int(strike)} PE. "
                            f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}"
                        )
                    else:
                        headline = f"🚀 OPTIONS MOMENTUM: {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
                        summary = (
                            f"Institutional Call surge in {clean_sym} {int(strike)} CE. "
                            f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} (Scale 50% & SL to Cost) | T2: ₹{opt_t2:,.1f}.{drive_tag}{friday_tag}{dte_pm_tag}{phys_tag}{rollover_tag}"
                        )

                    alert = AutoAlert(
                        alert_id=alert_id,
                        alert_type="OPTIONS_MOMENTUM",
                        stage=(
                            "IGNITED"
                            if (
                                vol_oi >= 2.0
                                or (is_opening_drive and (vol_oi >= 0.50 or vol >= 6000))
                            )
                            else "EARLY_WARNING"
                        ),
                        symbol=clean_sym,
                        exchange=opt_exchange,
                        direction=direction,
                        headline=headline,
                        summary=summary,
                        ltp=opt_ltp,
                        trigger_level=opt_ltp,
                        target_level=opt_t1,
                        stop_loss=opt_sl,
                        no_chase_boundary=max_chase,
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
                        mtf_confluence=(
                            "BEARISH_BREAKDOWN"
                            if has_opening_breakdown
                            else ("BULLISH_BREAKOUT" if has_opening_breakout else mtf_15m_trend)
                        ),
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
                            "high": getattr(c, "high", None),
                            "low": getattr(c, "low", None),
                            "open": getattr(c, "open", None),
                            "close": getattr(c, "close", None),
                            "is_friday_late": is_friday_late,
                            "is_opening_drive": bool(is_bear_drive or is_bull_drive),
                            "opening_drive_type": "BEARISH_OPEN_EQUALS_HIGH" if is_bear_drive else ("BULLISH_OPEN_EQUALS_LOW" if is_bull_drive else None),
                            "mtf_15m_trend": (
                                "BEARISH_BREAKDOWN"
                                if has_opening_breakdown
                                else (
                                    "BULLISH_BREAKOUT" if has_opening_breakout else mtf_15m_trend
                                )
                            ),
                            "has_opening_breakdown": has_opening_breakdown,
                            "has_opening_breakout": has_opening_breakout,
                            "vix_regime": vix_regime,
                            "india_vix": vix_val,
                            "is_gamma_squeeze": is_gamma_squeeze,
                            "nifty_change_pct": nifty_change,
                            "nifty_below_vwap": nifty_below_vwap,
                            "nifty_regime": (
                                "MARKDOWN"
                                if is_nifty_markdown
                                else ("MARKUP" if is_nifty_markup else "NORMAL")
                            ),
                            "confirmation_candle": conf_candle,
                            "confirmation_confirmed": is_confirmed,
                            "divergence_type": div_type,
                            "divergence_bias": div_bias,
                            "volume_profile_tags": vp_tags,
                            "is_0dte_afternoon": is_zero_dte_pm,
                            "physical_settlement_week": is_physical_expiry_week or is_next_month_routed,
                            "rollover_series": "NEXT_MONTH" if is_next_month_routed else "CURRENT_MONTH",
                            "is_rollover_recommended": is_next_month_routed,
                            "rollover_protected": is_next_month_routed,
                            "sector_tailwind_bonus": sector_tailwind_bonus,
                        },
                        actionable_plan={
                            "action": f"BUY {opt_type}",
                            "segment": "FNO",
                            "contract": contract_sym,
                            "recommended_entry": f"₹{opt_ltp:,.2f}",
                            "entry_range": entry_range_str,
                            "stop_loss": f"₹{opt_sl:,.1f}",
                            "target_0_5": f"₹{opt_t0_5:,.1f}",
                            "target_1": f"₹{opt_t1:,.1f}",
                            "target": f"₹{opt_t1:,.1f}",
                            "target_2": f"₹{opt_t2:,.1f}",
                            "target_moonshot": f"₹{opt_moonshot:,.1f}",
                            "risk_reward": rr_str,
                            "when_to_buy": when_to_buy_str,
                            "when_to_wait": when_to_wait_str,
                            "profit_rule": (
                                f"🏆 3-TIER PROFIT-TAKING: "
                                f"1) Scale 50% at T1 (₹{opt_t1:,.1f}) & move SL to Breakeven (0 Risk). "
                                f"2) Scale 25% at T2 (₹{opt_t2:,.1f}). "
                                f"3) Trail final 25% on 15m VWAP / 20-EMA to Moonshot (₹{opt_moonshot:,.1f})."
                            ),
                            "option_plan": opt_plan,
                            "lot_size": lot_sz,
                            "spot_invalidation_anchor": f"₹{tp.invalidation_stop:,.1f}"
                            if (tp and tp.invalidation_stop > 0)
                            else None,
                            "friday_weekend_warning": friday_tag.strip() if friday_tag else None,
                            "zero_dte_afternoon_guard": (
                                "⚠️ 0DTE AFTERNOON: Accelerated theta decay active. Deep ATM/ITM only; mandatory square-off by 15:15 IST."
                                if is_zero_dte_pm
                                else None
                            ),
                            "rollover_notice": (
                                f"🎯 NEXT-MONTH ROLLOVER: Contract {contract_sym} expires {expiry_date} (bypasses SEBI delivery margin surge & theta decay)."
                                if is_next_month_routed
                                else None
                            ),
                            "physical_settlement_warning": (
                                "⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). Mandatory exit by 15:00 IST — DO NOT CARRY OVERNIGHT."
                                if (is_physical_expiry_week and not is_next_month_routed)
                                else None
                            ),
                        },
                    )
                    if self.record_alert(alert):
                        found.append(alert)
                        break  # 1 best contract per underlying per scan cycle
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Options momentum scan error for {sym}: {e}")

        return found

    def scan_index_contagion(self) -> list[AutoAlert]:
        """
        Scans institutional constituent synchronization for major indices (BANKNIFTY, NIFTY, FINNIFTY).
        Detects synchronized momentum in heavyweights (HDFCBANK, ICICIBANK, RELIANCE, SBIN)
        to alert 60-120s before the parent index confirms.
        """
        found: list[AutoAlert] = []
        try:
            from engine.index_contagion import index_contagion_engine

            for idx in ("BANKNIFTY", "NIFTY", "FINNIFTY"):
                try:
                    res = index_contagion_engine.evaluate_index(idx)
                    if res and res.alert:
                        if self.record_alert(res.alert):
                            found.append(res.alert)
                except Exception as e_sub:
                    logger.debug(f"[AutoAlertEngine] Index contagion error for {idx}: {e_sub}")
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Index contagion scan failure: {e}")
        return found

    def scan_opening_drives(self) -> list[AutoAlert]:
        """
        Scans watched indices and comprehensive F&O universe for explosive Opening Drive ignitions
        (09:16 - 09:45 IST) based on Open==Low (Bullish) or Open==High (Bearish) institutional setups.
        """
        now_ist = datetime.now(IST)
        curr_t = now_ist.time()
        is_test_env = (
            (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if not is_test_env and (curr_t < dtime(9, 16) or curr_t > dtime(9, 45)):
            return []

        from market.history import get_ohlcv
        from market.quotes import get_ltp, get_quote

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym
                ltp = get_ltp(lookup_sym)
                if not ltp or ltp <= 0:
                    continue

                raw_q = get_quote(lookup_sym)
                q = raw_q.get(lookup_sym) if isinstance(raw_q, dict) else raw_q
                vwap_val = getattr(q, "vwap", None) if q else None
                prev_close = getattr(q, "previous_close", None) if q else None
                prev_high = getattr(q, "prev_high", None) if q else None
                prev_low = getattr(q, "prev_low", None) if q else None

                # Fetch 5-minute intraday OHLCV for opening drive pattern
                df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=1)
                if df_5m is None or len(df_5m) < 1:
                    continue

                # Compute RVOL
                rvol_val = 1.8
                try:
                    vols = df_5m["volume"].values if "volume" in df_5m.columns else None
                    if vols is not None and len(vols) >= 3:
                        cur_v = float(vols[-1])
                        avg_v = float(np.mean(vols[:-1]))
                        if avg_v > 0:
                            rvol_val = round(cur_v / avg_v, 2)
                except Exception:
                    pass

                alert = detect_opening_drive(
                    symbol=sym,
                    df_5m=df_5m,
                    ltp=ltp,
                    vwap=vwap_val,
                    rvol=rvol_val,
                    ref_time=now_ist,
                    prev_close=prev_close,
                    prev_high=prev_high,
                    prev_low=prev_low,
                    ignore_time_gate=is_test_env,
                )
                if alert and self.record_alert(alert):
                    found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Opening Drive scan error for {sym}: {e}")

        return found

    def scan_opening_range_breakouts(self) -> list[AutoAlert]:
        """
        Scans watched indices and high-liquidity equities for 15-minute Opening Range Breakouts (ORB-15).
        Active post-09:30 IST (09:30 - 11:30 IST) when opening range is fully established.
        """
        now_ist = datetime.now(IST)
        curr_t = now_ist.time()
        is_test_env = (
            (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if not is_test_env and (curr_t < dtime(9, 30) or curr_t > dtime(11, 30)):
            return []

        from market.history import get_ohlcv
        from market.quotes import get_ltp, get_quote

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym
                ltp = get_ltp(lookup_sym)
                if not ltp or ltp <= 0:
                    continue

                raw_q = get_quote(lookup_sym)
                q = raw_q.get(lookup_sym) if isinstance(raw_q, dict) else raw_q
                vwap_val = getattr(q, "vwap", None) if q else None

                # Fetch 5-minute intraday OHLCV for opening range calculation
                df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=1)
                if df_5m is None or len(df_5m) < 3:
                    continue

                # Compute TOD-RVOL from volume series
                rvol_val = 1.5
                try:
                    vols = df_5m["volume"].values if "volume" in df_5m.columns else None
                    if vols is not None and len(vols) >= 3:
                        cur_v = float(vols[-1])
                        avg_v = float(np.mean(vols[:-1]))
                        if avg_v > 0:
                            rvol_val = round(cur_v / avg_v, 2)
                except Exception:
                    pass

                alert = detect_opening_range_breakout(
                    sym,
                    df=df_5m,
                    ltp=ltp,
                    vwap=vwap_val,
                    exchange=exch,
                    rvol=rvol_val,
                    ref_time=now_ist,
                    ignore_time_gate=is_test_env,
                )
                if alert and self.record_alert(alert):
                    found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] ORB scan error for {sym}: {e}")

        return found

    # ── Time-Partitioned Segment Scanning Loops ──────────────────

    def scan_equity_nfo_now(self) -> list[AutoAlert]:
        """Runs all daytime Equity and NFO derivative detectors (09:15 - 15:30 IST)."""
        results: list[AutoAlert] = []
        results.extend(self.scan_opening_drives())  # Priority 0: 09:16 - 09:45 Morning Institutional Drive
        results.extend(self.scan_index_contagion())  # Priority 1: Heavyweight lead-lag sync!
        results.extend(self.scan_gamma_blasts())
        results.extend(self.scan_options_momentum_breakouts())
        results.extend(self.scan_squeeze_breakouts())
        results.extend(self.scan_opening_range_breakouts())
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

            # Strict Data Provenance Gate: Verify if quote is authentic live broker data vs synthetic/mock
            is_mock_quote = (
                type(q).__name__ == "MagicMock"
                or getattr(q, "_is_mock", False)
                or getattr(q, "provider", "") in ("mock", "TEST")
                or getattr(q, "data_state", "") == "UNAVAILABLE"
            )
            is_test_env = (
                os.environ.get("CHANAKYA_TESTING") == "1"
                or os.environ.get("DEPLOY_MODE") == "test"
            )
            is_authentic_live = not (is_mock_quote or is_test_env)

            chg_prev = float(getattr(q, "change_pct", 0.0) or 0.0)
            open_p = float(getattr(q, "open", 0.0) or 0.0)
            high_p = float(getattr(q, "high", 0.0) or 0.0)
            low_p = float(getattr(q, "low", 0.0) or 0.0)
            vol = int(getattr(q, "volume", 0) or 0)

            chg_open = round(((ltp - open_p) / open_p * 100), 2) if open_p > 0 else chg_prev
            chg_from_low = round(((ltp - low_p) / low_p * 100), 2) if low_p > 0 else 0.0
            chg_from_high = round(((high_p - ltp) / high_p * 100), 2) if high_p > 0 else 0.0
            chg = chg_open if abs(chg_open) > abs(chg_prev) else chg_prev

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

            # High-Impact Scheduled US Inventory Event Blackout Window (Live market only)
            now_ist = datetime.now(IST)
            if is_authentic_live:
                hh, mm = now_ist.hour, now_ist.minute
                weekday = now_ist.weekday()  # Monday=0, Wednesday=2, Thursday=3

                # 1. Wednesday EIA Weekly Petroleum Status Report (Crude): 19:45 - 20:45 IST
                if clean_sym in ("CRUDEOIL", "CRUDEOILM") and weekday == 2:
                    if (hh == 19 and mm >= 45) or (hh == 20 and mm <= 45):
                        logger.info(
                            f"[AutoAlertEngine] Suppressing {clean_sym} during Wednesday EIA Crude inventory blackout window ({hh:02d}:{mm:02d} IST)"
                        )
                        continue

                # 2. Thursday EIA Natural Gas Storage Report: 19:45 - 20:45 IST
                if clean_sym in ("NATURALGAS", "NATGASMINI") and weekday == 3:
                    if (hh == 19 and mm >= 45) or (hh == 20 and mm <= 45):
                        logger.info(
                            f"[AutoAlertEngine] Suppressing {clean_sym} during Thursday EIA NatGas storage blackout window ({hh:02d}:{mm:02d} IST)"
                        )
                        continue

                # 3. Tuesday API Weekly Crude Inventory (American Petroleum Institute): 20:00 - 21:30 IST
                if clean_sym in ("CRUDEOIL", "CRUDEOILM") and weekday == 1:
                    if (hh == 20) or (hh == 21 and mm <= 30):
                        logger.info(
                            f"[AutoAlertEngine] Suppressing {clean_sym} during Tuesday API crude inventory blackout window ({hh:02d}:{mm:02d} IST)"
                        )
                        continue

                # 4. US FOMC / Fed Rate Decisions (typically 23:30 IST — hard blackout all commodities)
                # Non-scheduled: handled by macro_blackouts in alert_scrutiny

            # Minimum move threshold for commodity trigger (0.6% for Gold/Silver/Copper, 1.0% for Crude/NatGas)
            min_chg = 1.0 if clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI") else 0.6

            # 20-Bar Donchian Channel Breakout & Wick Rejection Verification on 5m OHLCV
            df_5m = None
            try:
                from market.history import get_ohlcv

                df_5m = get_ohlcv(clean_sym, exchange="MCX", interval="5minute", days=2)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Error fetching 5m OHLCV for MCX:{clean_sym}: {e}")

            # US Open Transition Gate (18:15 to 19:15 IST):
            # High risk of opening range sweep / Judas swing fakeouts before COMEX/NYMEX regular trading hours.
            is_us_open_transition = (now_ist.hour == 18 and now_ist.minute >= 15) or (
                now_ist.hour == 19 and now_ist.minute < 15
            )

            is_bullish = False
            is_bearish = False
            is_donchian_breakout = False
            rvol = 1.0

            roc_15m = 0.0
            if df_5m is not None and len(df_5m) >= 4:
                try:
                    c_ago = float(df_5m.iloc[-4]["close"])
                    if c_ago > 0:
                        roc_15m = round(((ltp - c_ago) / c_ago * 100), 2)
                except Exception:
                    pass

            has_bull_chg = (
                (chg_prev >= min_chg)
                or (chg_open >= min_chg)
                or (chg_from_low >= min_chg * 1.2 and roc_15m >= 0.5)
            )
            has_bear_chg = (
                (chg_prev <= -min_chg)
                or (chg_open <= -min_chg)
                or (chg_from_high >= min_chg * 1.2 and roc_15m <= -0.5)
            )

            if df_5m is not None and len(df_5m) >= 20:
                recent_20 = df_5m.iloc[-21:-1]
                prior_high = float(recent_20["high"].max())
                prior_low = float(recent_20["low"].min())
                last_bar = df_5m.iloc[-1]
                cur_open = float(last_bar.get("open", ltp))
                cur_high = max(float(last_bar.get("high", ltp)), ltp)
                cur_low = min(float(last_bar.get("low", ltp)), ltp)
                cur_close = float(last_bar.get("close", ltp))
                bar_range = max(1.0, cur_high - cur_low)

                # Compute Relative Volume (RVOL) against 20-bar rolling average
                try:
                    vols_s = df_5m["volume"] if "volume" in df_5m.columns else df_5m.get("Volume")
                    if vols_s is not None and len(vols_s) >= 20:
                        avg_v = float(vols_s.iloc[-21:-1].mean())
                        cur_v = float(last_bar.get("volume", 0.0) or 0.0)
                        rvol = round(cur_v / max(1.0, avg_v), 2) if avg_v > 0 else 1.0
                except Exception:
                    rvol = 1.0

                upper_wick_ratio = (cur_high - max(cur_open, cur_close)) / bar_range
                lower_wick_ratio = (min(cur_open, cur_close) - cur_low) / bar_range
                bull_close_ratio = (cur_close - cur_low) / bar_range
                bear_close_ratio = (cur_high - cur_close) / bar_range

                # Allow wick up to 0.45 when accompanied by strong RVOL >= 1.2
                max_wick = 0.45 if (is_us_open_transition and rvol >= 1.2) else 0.40
                req_bull_close = 0.55 if is_us_open_transition else 0.50
                req_bear_close = 0.55 if is_us_open_transition else 0.50

                # Bullish: breaking 20-bar high, acceptable upper wick, closing in upper half
                if (
                    not is_locked_bull
                    and has_bull_chg
                    and (ltp >= prior_high * 0.999 or cur_close >= prior_high)
                    and upper_wick_ratio <= max_wick
                    and bull_close_ratio >= req_bull_close
                    and ltp >= vwap * 0.998
                ):
                    if not is_us_open_transition or rvol >= 1.2:
                        is_bullish = True
                        is_donchian_breakout = True

                # Bearish: breaking 20-bar low, acceptable lower wick, closing in lower half
                elif (
                    not is_locked_bear
                    and has_bear_chg
                    and (ltp <= prior_low * 1.001 or cur_close <= prior_low)
                    and lower_wick_ratio <= max_wick
                    and bear_close_ratio >= req_bear_close
                    and ltp <= vwap * 1.002
                ):
                    if not is_us_open_transition or rvol >= 1.2:
                        is_bearish = True
                        is_donchian_breakout = True
            else:
                # Fallback when historical 5m bars are unavailable:
                strict_min_chg = max(min_chg * 1.2, 0.9)
                has_real_vwap_diff = (vwap > 0) and (abs(ltp - vwap) >= 2.0)
                is_bull_thrust = (
                    (chg_prev >= strict_min_chg)
                    or (chg_open >= strict_min_chg)
                    or (chg_from_low >= strict_min_chg * 1.2)
                )
                is_bear_thrust = (
                    (chg_prev <= -strict_min_chg)
                    or (chg_open <= -strict_min_chg)
                    or (chg_from_high >= strict_min_chg * 1.2)
                )
                if has_real_vwap_diff:
                    is_bullish = (
                        not is_locked_bull and is_bull_thrust and (ltp >= (vwap * 0.998))
                    )
                    is_bearish = (
                        not is_locked_bear and is_bear_thrust and (ltp <= (vwap * 1.002))
                    )
                else:
                    is_bullish = not is_locked_bull and is_bull_thrust
                    is_bearish = not is_locked_bear and is_bear_thrust

            if not (is_bullish or is_bearish):
                continue

            # Global Macro Pre-Filter (Live market only: DXY for Bullion, Brent for Crude Oil)
            if is_authentic_live:
                try:
                    from market.macro import get_macro_snapshot

                    macro_snap = get_macro_snapshot()
                    if macro_snap:
                        # Gold / Silver vs DXY (Dollar Index)
                        if clean_sym in ("GOLD", "GOLDM", "SILVER", "SILVERM"):
                            dxy_chg = macro_snap.dxy_change
                            if dxy_chg is not None:
                                if is_bullish and dxy_chg >= 0.25:
                                    logger.debug(
                                        f"[AutoAlertEngine] Bullish {clean_sym} vetoed by surging DXY (+{dxy_chg:.2f}%)"
                                    )
                                    continue
                                elif is_bearish and dxy_chg <= -0.25:
                                    logger.debug(
                                        f"[AutoAlertEngine] Bearish {clean_sym} vetoed by collapsing DXY ({dxy_chg:.2f}%)"
                                    )
                                    continue
                        # Crude Oil vs Brent Crude
                        elif clean_sym in ("CRUDEOIL", "CRUDEOILM"):
                            brent_chg = macro_snap.crude_change
                            if brent_chg is not None:
                                if is_bullish and brent_chg <= -1.2:
                                    logger.debug(
                                        f"[AutoAlertEngine] Bullish {clean_sym} vetoed by collapsing Brent ({brent_chg:.2f}%)"
                                    )
                                    continue
                                elif is_bearish and brent_chg >= 1.2:
                                    logger.debug(
                                        f"[AutoAlertEngine] Bearish {clean_sym} vetoed by surging Brent (+{brent_chg:.2f}%)"
                                    )
                                    continue
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] Macro snapshot check exception: {e}")

            # 2. Noise-Safe Quantitative Commodity Volatility Risk (Points)
            # Recalibrated to eliminate SUB_ATR_NOISE_WHIPSAW invalidations
            atr_calc = None
            if df_5m is not None and len(df_5m) >= 14:
                try:
                    highs_s = df_5m["high"] if "high" in df_5m.columns else df_5m["High"]
                    lows_s = df_5m["low"] if "low" in df_5m.columns else df_5m["Low"]
                    closes_s = df_5m["close"] if "close" in df_5m.columns else df_5m["Close"]
                    tr1 = highs_s - lows_s
                    tr2 = (highs_s - closes_s.shift(1)).abs()
                    tr3 = (lows_s - closes_s.shift(1)).abs()
                    tr_s = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr_calc = float(tr_s.rolling(14).mean().iloc[-1])
                except Exception:
                    atr_calc = None

            is_energy = clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI")
            # Volatility floor percentages: 0.8% for Energy, 0.5% for Bullion/Metals
            min_vol_pct = 0.008 if is_energy else 0.005
            min_noise_floor_pts = round(ltp * min_vol_pct, 1)

            base_atr = atr_calc if (atr_calc and atr_calc > 0) else min_noise_floor_pts

            # Multi-timeframe structural noise floor:
            from engine.alert_scrutiny import COMMODITY_MIN_SL_FLOORS

            min_structural_pts = COMMODITY_MIN_SL_FLOORS.get(
                clean_sym, round(ltp * min_vol_pct, 1)
            )

            # 1b. Institutional Smart Money Concepts (SMC) & Price Action Confluence
            smc_tags: list[str] = []
            smc_report = None
            if df_5m is not None and len(df_5m) >= 14:
                try:
                    from analysis.market_structure import analyze_market_structure

                    smc_report = analyze_market_structure(
                        clean_sym, df=df_5m, exchange="MCX", timeframe="5m"
                    )
                    if smc_report:
                        if smc_report.bos_detected:
                            if is_bullish and smc_report.bos_type == "BULLISH_BOS":
                                smc_tags.append("SMC Bullish BOS")
                            elif is_bearish and smc_report.bos_type == "BEARISH_BOS":
                                smc_tags.append("SMC Bearish BOS")
                        if smc_report.choch_detected:
                            if is_bullish and smc_report.choch_type == "BULLISH_CHOCH":
                                smc_tags.append("SMC Bullish CHoCH Reversal")
                            elif is_bearish and smc_report.choch_type == "BEARISH_CHOCH":
                                smc_tags.append("SMC Bearish CHoCH Reversal")
                        if smc_report.liquidity_sweeps:
                            sweep_types = [s.type for s in smc_report.liquidity_sweeps]
                            if is_bullish and "BULLISH_SWEEP" in sweep_types:
                                smc_tags.append("SMC Liquidity Sweep (Spring Reclaim)")
                            elif is_bearish and "BEARISH_SWEEP" in sweep_types:
                                smc_tags.append("SMC Liquidity Sweep (Upthrust Reclaim)")
                        if is_bullish and smc_report.active_demand_zones:
                            smc_tags.append("Demand Order Block Support")
                        elif is_bearish and smc_report.active_supply_zones:
                            smc_tags.append("Supply Order Block Resistance")
                        if is_bullish and smc_report.in_discount_zone:
                            smc_tags.append("Discount Zone (≤50% Eq)")
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] SMC analysis error: {e}")

            # Candlestick & Price Action Patterns + Confirmation Candle Gate
            if df_5m is not None and len(df_5m) >= 2:
                try:
                    last_b = df_5m.iloc[-1]
                    prev_b = df_5m.iloc[-2]
                    c_o = float(last_b.get("open", ltp))
                    c_c = float(last_b.get("close", ltp))
                    c_h = float(last_b.get("high", ltp))
                    c_l = float(last_b.get("low", ltp))
                    p_o = float(prev_b.get("open", ltp))
                    p_c = float(prev_b.get("close", ltp))
                    b_range = max(0.5, c_h - c_l)

                    u_wick = (c_h - max(c_o, c_c)) / b_range
                    l_wick = (min(c_o, c_c) - c_l) / b_range
                    if is_bullish and l_wick >= 0.45 and (c_c >= c_o):
                        smc_tags.append("Hammer / Absorption Wick")
                    elif is_bearish and u_wick >= 0.45 and (c_c <= c_o):
                        smc_tags.append("Shooting Star / Rejection Wick")

                    if is_bullish and (c_c > c_o) and (p_c < p_o) and (c_c >= p_o) and (c_o <= p_c):
                        smc_tags.append("Bullish Engulfing Expansion")
                    elif is_bearish and (c_c < c_o) and (p_c > p_o) and (c_c <= p_o) and (c_o >= p_c):
                        smc_tags.append("Bearish Engulfing Expansion")
                except Exception:
                    pass

            # SMC Confirmation Candle Gate (from analyze_market_structure)
            if smc_report is not None:
                if smc_report.confirmation_confirmed and smc_report.confirmation_candle:
                    smc_tags.append(f"Confirmed: {smc_report.confirmation_candle}")

                # RSI Divergence tags — add as confluence or contra-signal
                if smc_report.divergence_type and smc_report.divergence_bias:
                    div_bias = smc_report.divergence_bias
                    div_type = smc_report.divergence_type
                    if (is_bullish and div_bias == "BULLISH") or (is_bearish and div_bias == "BEARISH"):
                        smc_tags.append(f"RSI Divergence ({div_type.replace('_', ' ').title()})")
                    elif (is_bullish and div_bias == "BEARISH") or (is_bearish and div_bias == "BULLISH"):
                        # Opposite divergence = trap warning → raise bar for entry
                        if rvol < 1.5:
                            logger.info(
                                f"[AutoAlertEngine] ⚠️ Contra divergence ({div_type}) on {clean_sym} — RVOL {rvol:.1f}x below 1.5x threshold; suppressing."
                            )
                            is_bullish = False
                            is_bearish = False

            # For PULLBACK_RETEST / BOTTOM_FISHING setups require confirmation candle
            if smc_report and smc_report.setup_type in ("PULLBACK_RETEST", "BOTTOM_FISHING_SPRING", "TOP_FISHING_UTAD"):
                if smc_report.confirmation_confirmed is False and rvol < 1.5:
                    # No candle confirmation AND low volume — strong trap risk; demote to EARLY_WARNING only
                    if is_bullish or is_bearish:
                        smc_tags.append("⚠️ Awaiting Candle Confirmation")

            # Volume Profile — POC / VAH / VAL proximity tags
            if df_5m is not None and len(df_5m) >= 10:
                try:
                    from analysis.volume_profile import compute_volume_profile
                    poc_price, vah_price, val_price, _ = compute_volume_profile(df_5m, num_bins=10)
                    if poc_price > 0 and ltp > 0:
                        poc_dist_pct = abs(ltp - poc_price) / ltp * 100
                        if poc_dist_pct <= 0.30:
                            smc_tags.append(f"POC Magnet (₹{poc_price:,.1f})")
                        if is_bullish:
                            if vah_price > 0 and ltp >= vah_price * 0.999:
                                smc_tags.append(f"Breaking VAH ₹{vah_price:,.1f} (Volume Breakout)")
                            elif val_price > 0 and abs(ltp - val_price) / ltp <= 0.003:
                                smc_tags.append(f"VAL Support ₹{val_price:,.1f}")
                        elif is_bearish:
                            if val_price > 0 and ltp <= val_price * 1.001:
                                smc_tags.append(f"Breaking VAL ₹{val_price:,.1f} (Volume Breakdown)")
                            elif vah_price > 0 and abs(ltp - vah_price) / ltp <= 0.003:
                                smc_tags.append(f"VAH Resistance ₹{vah_price:,.1f}")
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] Volume profile error for {clean_sym}: {e}")

            # Signal Ensemble Gate — 5-strategy weighted vote must agree with direction
            if df_5m is not None and len(df_5m) >= 50:
                try:
                    from engine.signal_ensemble import ensemble_signal
                    ens = ensemble_signal(df_5m)
                    if ens.confidence > 0:
                        if (is_bullish and ens.verdict == "BEARISH" and ens.confidence >= 0.55) or \
                           (is_bearish and ens.verdict == "BULLISH" and ens.confidence >= 0.55):
                            logger.info(
                                f"[AutoAlertEngine] 🛑 Ensemble VETO on {clean_sym}: "
                                f"Signal is {direction} but ensemble says {ens.verdict} (conf={ens.confidence:.0%}). Suppressing."
                            )
                            is_bullish = False
                            is_bearish = False
                        elif (is_bullish and ens.verdict == "BULLISH") or (is_bearish and ens.verdict == "BEARISH"):
                            smc_tags.append(f"Ensemble ✓ ({ens.verdict} {ens.confidence:.0%})")
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] Ensemble signal error for {clean_sym}: {e}")

            if not (is_bullish or is_bearish):
                continue

            # Volume Spread Analysis (VPA)
            if rvol >= 1.5:
                smc_tags.append(f"Institutional Surge (RVOL {rvol:.1f}x)")
            elif rvol >= 1.2:
                smc_tags.append(f"Volume Expansion (RVOL {rvol:.1f}x)")

            # Volatility noise-safe stop: at least 1.5x realized 5m ATR, minimum structural floor, or volatility % floor
            noise_safe_pts = max(base_atr * 1.5, min_structural_pts, min_noise_floor_pts)
            if smc_report and smc_report.invalidation_level and smc_report.invalidation_level > 0:
                smc_inval_pts = abs(ltp - smc_report.invalidation_level)
                if smc_inval_pts >= min_structural_pts:
                    noise_safe_pts = max(noise_safe_pts, round(smc_inval_pts, 1))

            risk_pts = round(max(1.0, noise_safe_pts), 1)
            atr = round(base_atr, 1)
            direction = "BULLISH" if is_bullish else "BEARISH"
            alert_type = "COMMODITY_MOMENTUM"
            alert_id = f"comm-{clean_sym.lower()}-{datetime.now(IST).strftime('%Y%m%d%H%M')}"

            # Contract lot sizes: resolved canonically from position sizer master
            from engine.position_sizer import get_lot_size

            lot_sz = get_lot_size(clean_sym) or 1

            has_real_vwap = abs(ltp - vwap) >= 2.0 and vwap != ltp
            if is_bullish:
                sl_price = round(ltp - risk_pts, 2)
                t1_price = round(ltp + 2.0 * risk_pts, 2)
                t2_price = round(ltp + 3.5 * risk_pts, 2)
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
                t1_price = round(ltp - 2.0 * risk_pts, 2)
                t2_price = round(ltp - 3.5 * risk_pts, 2)
                if is_donchian_breakout:
                    headline = (
                        f"🛢️ MCX BREAKDOWN: {clean_sym} {chg:.1f}% Breaking 20-bar Low (₹{ltp:,.1f})"
                    )
                    summary = f"Institutional breakdown in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). 20-bar 5m Donchian low broken below VWAP ₹{vwap:,.1f}."
                elif has_real_vwap:
                    headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Lost VWAP (₹{vwap:,.1f})"
                    summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Broken below VWAP ₹{vwap:,.1f}."
                else:
                    headline = f"MCX BREAKDOWN: {clean_sym} {chg:.1f}% Drop @ ₹{ltp:,.1f}"
                    summary = f"Severe session weakness in {clean_sym}: Trading at ₹{ltp:,.1f} ({chg:.1f}%). Session selling active."
                action = "SELL_SHORT_FUTURES"

            # 3. Resolve defined-risk options contract (Delta-aware strike selection)
            # Target: Delta 0.35–0.50 for momentum plays (near ATM). Flag < 5 DTE with theta risk.
            opt_recommendation = None
            readable_contract = None
            try:
                from market.options import get_options_chain, format_readable_option_symbol

                chain = get_options_chain(clean_sym)
                opt_type = "CE" if is_bullish else "PE"
                filtered = [c for c in chain if c.option_type == opt_type and c.last_price > 0]
                if filtered:
                    # Delta-aware selection: prefer near-ATM contracts (strike within ±3% of spot)
                    # as a proxy for Delta 0.35–0.50 when actual Greeks are unavailable
                    atm_band = ltp * 0.03
                    atm_candidates = [
                        c for c in filtered
                        if abs(c.strike - ltp) <= atm_band and c.last_price >= 1.0
                    ]
                    # Fall back to all filtered if no ATM candidates
                    candidates = atm_candidates if atm_candidates else filtered

                    # Sort: prefer strike closest to spot (best delta proxy)
                    candidates.sort(key=lambda c: abs(c.strike - ltp))
                    closest_opt = candidates[0]

                    # Delta tier classification (by moneyness as proxy)
                    moneyness_pct = (ltp - closest_opt.strike) / ltp * 100 if is_bullish else (closest_opt.strike - ltp) / ltp * 100
                    if -1.0 <= moneyness_pct <= 1.0:
                        delta_tier = "ATM (Δ≈0.50)"
                    elif moneyness_pct > 1.0:
                        delta_tier = "ITM (Δ>0.50)"
                    else:
                        delta_tier = "OTM (Δ<0.40)"

                    # DTE warning
                    dte_warning = None
                    try:
                        expiry = getattr(closest_opt, "expiry", None)
                        if expiry:
                            from datetime import date as _date
                            exp_date = expiry if isinstance(expiry, _date) else _date.fromisoformat(str(expiry)[:10])
                            dte = (exp_date - _date.today()).days
                            if dte <= 5:
                                dte_warning = f"⚠️ THETA RISK: Only {dte} DTE — rapid premium decay."
                    except Exception:
                        pass

                    opt_prem = closest_opt.last_price
                    opt_risk = round(max(1.0, min(opt_prem * 0.35, risk_pts * 0.52)), 1)
                    opt_t1 = round(opt_prem + 2.0 * opt_risk, 1)
                    opt_t2 = round(opt_prem + 3.5 * opt_risk, 1)
                    readable_contract = format_readable_option_symbol(
                        closest_opt.symbol,
                        strike=closest_opt.strike,
                        option_type=opt_type,
                        expiry=getattr(closest_opt, "expiry", None),
                    )
                    opt_recommendation = {
                        "contract": closest_opt.symbol,
                        "readable_contract": readable_contract,
                        "strike": closest_opt.strike,
                        "option_type": opt_type,
                        "ltp": opt_prem,
                        "stop_loss": round(max(0.05, opt_prem - opt_risk), 1),
                        "target_1": opt_t1,
                        "target_2": opt_t2,
                        "risk_reward": "1:2.4",
                        "max_loss_capped": round(opt_prem * lot_sz, 0),
                        "delta_tier": delta_tier,
                        "dte_warning": dte_warning,
                    }
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Options chain resolution error: {e}")
                opt_recommendation = None

            # Bounded Entry Range for continuous futures
            rr_ratio_t1 = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
            if is_bullish:
                e_low = round(max(sl_price + 0.5, ltp - 0.25 * risk_pts), 1)
                e_high = round(min(t1_price - 0.25 * risk_pts, ltp + 0.25 * risk_pts), 1)
            else:
                e_high = round(min(sl_price - 0.5, ltp + 0.25 * risk_pts), 1)
                e_low = round(max(t1_price + 0.25 * risk_pts, ltp - 0.25 * risk_pts), 1)

            confluence_str = " + ".join(smc_tags) if smc_tags else "Donchian Breakout + VWAP Confirmation"

            # Build Options-First Plan when liquid option contracts exist
            if opt_recommendation:
                opt_contract_name = (
                    opt_recommendation.get("readable_contract")
                    or readable_contract
                    or opt_recommendation["contract"]
                )
                opt_sl = opt_recommendation["stop_loss"]
                opt_t1 = opt_recommendation["target_1"]
                opt_t2 = opt_recommendation["target_2"]
                opt_entry_low = round(max(0.5, opt_recommendation["ltp"] - 0.15 * opt_risk), 1)
                opt_entry_high = round(opt_recommendation["ltp"] + 0.15 * opt_risk, 1)

                _delta_tier = opt_recommendation.get("delta_tier", "ATM (Δ≈0.50)")
                _dte_warn = opt_recommendation.get("dte_warning") or ""
                plan_dict = {
                    "action": f"BUY_{opt_type}",
                    "segment": "COMMODITY",
                    "instrument_type": "OPTION",
                    "contract": opt_contract_name,
                    "raw_contract": opt_recommendation["contract"],
                    "entry_range": f"₹{opt_entry_low:,.1f} – ₹{opt_entry_high:,.1f}",
                    "stop_loss": f"₹{opt_sl:,.1f}",
                    "target": f"₹{opt_t1:,.1f}",
                    "target_2": f"₹{opt_t2:,.1f}",
                    "risk_reward": "1:2.4",
                    "lot_size": lot_sz,
                    "preferred_vehicle": "DEFINED_RISK_OPTION",
                    "delta_tier": _delta_tier,
                    "max_loss_capped": opt_recommendation["max_loss_capped"],
                    "setup_confluence": confluence_str,
                    "when_to_buy": (
                        f"Enter {_delta_tier} {opt_contract_name} on 5m candle closing in breakout direction above/below VWAP ₹{vwap:,.1f}."
                        + (f" {_dte_warn}" if _dte_warn else "")
                    ),
                    "when_to_wait": f"Do not chase if option premium moves >15% beyond ₹{opt_recommendation['ltp']:,.1f}.",
                    "profit_rule": f"Book 50% at T1 (₹{opt_t1:,.1f}), trail stop to cost, hold runner for T2 (₹{opt_t2:,.1f}). Capped risk ₹{opt_recommendation['max_loss_capped']:,.0f} per lot.",
                    "vehicle_rationale": (
                        f"Defined-risk option vehicle: {_delta_tier} {opt_recommendation['option_type']} "
                        f"caps maximum loss to ₹{opt_recommendation['max_loss_capped']:,.0f} per lot against sub-ATR noise whipsaws and gap risk."
                    ),
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "LONG" if is_bullish else "SHORT",
                        "timeframe": "INTRADAY",
                        "entry_price": opt_recommendation["ltp"],
                        "invalidation_stop": opt_sl,
                        "target_1": opt_t1,
                        "target_2": opt_t2,
                        "risk_reward": "1:2.4",
                    },
                    "futures_reference": {
                        "contract": f"MCX:{clean_sym}",
                        "entry": ltp,
                        "stop_loss": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "risk_reward": f"1:{rr_ratio_t1}",
                    },
                    "option_alternative": opt_recommendation,  # backward compatibility
                }
                headline = f"🛢️ MCX OPTION: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} ({'Breakout' if is_bullish else 'Breakdown'} @ ₹{ltp:,.1f})"
                summary = (
                    f"Institutional {'breakout' if is_bullish else 'breakdown'} in {clean_sym} ({chg:+.1f}%). "
                    f"Preferred Vehicle: {opt_contract_name} @ ₹{opt_recommendation['ltp']:,.1f} with capped risk ₹{opt_recommendation['max_loss_capped']:,.0f}. "
                    f"Confluence: {confluence_str}."
                )
            else:
                # Standard futures plan if no liquid options chain exists
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
                    "setup_confluence": confluence_str,
                    "when_to_buy": f"Enter on 5m candle closing in direction above/below VWAP ₹{vwap:,.1f}.",
                    "when_to_wait": f"Do not chase if move exceeds {round(abs(chg) + 1.0, 1)}%.",
                    "profit_rule": "Book 50% at T1 (+2.0R), trail stop to breakeven, hold runner for T2 (+3.5R).",
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "LONG" if is_bullish else "SHORT",
                        "timeframe": "INTRADAY",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "risk_reward": f"1:{rr_ratio_t1}",
                    },
                }

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

            trigger_p = ltp
            sl_p = sl_price
            tgt_p = t1_price

            # Composite confidence: base + SMC confluence + MTF alignment + divergence boost
            n_smc_tags = len(smc_tags)
            base_conf = min(95, int(75 + abs(chg) * 6))
            conf_boost = min(15, n_smc_tags * 3)
            # RSI divergence in same direction adds +5 conviction
            if smc_report and smc_report.divergence_bias:
                if (is_bullish and smc_report.divergence_bias == "BULLISH") or \
                   (is_bearish and smc_report.divergence_bias == "BEARISH"):
                    conf_boost = min(15, conf_boost + 5)
            final_conf = min(95, base_conf + conf_boost)
            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED" if abs(chg) >= (min_chg * 1.5) else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="MCX",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=trigger_p,
                trigger_level=trigger_p,
                target_level=tgt_p,
                stop_loss=sl_p,
                confidence=final_conf,
                created_at=now_iso,
                is_live=is_authentic_live,
                environment="LIVE" if is_authentic_live else "TEST",
                market_status=mcx_status,
                option_premium=opt_recommendation["ltp"] if opt_recommendation else None,
                contract_symbol=opt_recommendation["contract"] if opt_recommendation else None,
                metrics={
                    "change_pct": chg,
                    "volume": vol,
                    "vwap": vwap,
                    "atr": atr,
                    "atr_14d": atr,
                    "rvol": rvol,
                    "lot_size": lot_sz,
                    "segment": "COMMODITY",
                    "has_options_chain": bool(opt_recommendation),
                    "confluence": confluence_str,
                    "spot": ltp,
                },
                actionable_plan=plan_dict,
            )
            if opt_recommendation:
                alert.derivative_type = "OPT"
                alert.strike = opt_recommendation["strike"]
                alert.option_type = opt_recommendation["option_type"]
                alert.option_premium = opt_recommendation["ltp"]
                alert.option_stop_loss = opt_recommendation["stop_loss"]
                alert.option_target_1 = opt_recommendation["target_1"]
                alert.option_target_2 = opt_recommendation["target_2"]
                alert.underlying_spot = ltp
                alert.raw_contract = opt_recommendation["contract"]

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

            # Currency dynamic risk: based on CMP volatility
            risk_rupees = round(max(0.06, ltp * 0.0012), 4)
            from engine.position_sizer import get_lot_size

            curr_lot = get_lot_size(clean_sym) or 1000

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
                    "lot_size": curr_lot,
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
                    "lot_size": curr_lot,
                    "when_to_buy": "Execute on order book spread with defined risk below SL.",
                    "when_to_wait": "Do not chase if spread widens > 0.05 paise.",
                    "profit_rule": "Scale 50% at T1, move SL to entry.",
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "LONG" if is_bullish else "SHORT",
                        "timeframe": "INTRADAY",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "risk_reward": "1:2.2",
                    },
                },
            )
            if self.record_alert(alert):
                found.append(alert)

        return found

    # ── 24x7 Real-Time Crypto Streaming & Autonomous Detection ─────────

    def _init_crypto_stream_listener(self) -> None:
        """Hooks AutoAlertEngine into the 24x7 live Binance tick stream for sub-second event triggers."""
        if getattr(self, "_crypto_listener_initialized", False):
            return
        try:
            from market.crypto_stream import crypto_stream

            crypto_stream.on_tick(self._on_crypto_tick)
            self._crypto_listener_initialized = True
            logger.info("[AutoAlertEngine] ⚡ Successfully connected to 24x7 Binance live tick stream.")
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Failed to register crypto tick listener: {e}")

    def _on_crypto_tick(self, tick: dict[str, Any]) -> None:
        """
        Sub-second event-driven handler for live Binance crypto ticks.
        Executes instant invalidations, target milestone ratchets,
        and impulse surge fast-path detection without waiting for the 45s poller.
        """
        if not tick or not isinstance(tick, dict):
            return

        raw_sym = str(tick.get("symbol") or "").upper()
        clean_sym = raw_sym.replace("CRYPTO:", "").replace("BINANCE:", "").strip()
        ltp = float(tick.get("ltp") or 0.0)
        if not clean_sym or ltp <= 0:
            return

        now_ts = float(tick.get("timestamp") or time.time())

        # 1. Instant Lifecycle Checks on Active Crypto Alerts
        with self._lock:
            active_crypto_alerts = [
                a
                for a in self._alerts
                if not a.is_invalidated
                and a.stage not in ("INVALIDATED", "COMPLETED", "TARGET_ACHIEVED")
                and (a.exchange or "").upper() in ("CRYPTO", "BINANCE")
                and a.symbol.upper().replace("CRYPTO:", "").strip()
                in (clean_sym, f"{clean_sym}USDT", clean_sym.replace("USDT", ""))
            ]

        for alert in active_crypto_alerts:
            # 1a. Instant Invalidation
            reason = evaluate_alert_invalidation(alert, current_ltp=ltp)
            if reason:
                now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                pm_dict = None
                try:
                    from engine.learning_engine import pattern_learning_engine

                    pm = pattern_learning_engine.conduct_invalidation_post_mortem(
                        alert, exit_price=ltp, exchange=alert.exchange
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
                    alert.headline = (
                        f"⚠️ {tag} VIEW INVALIDATED: {alert.symbol} {alert.alert_type.replace('_', ' ')}"
                    )
                    alert.summary = reason
                    self._save()
                self._dispatch(alert)
                logger.warning(
                    f"[AutoAlertEngine] ⚡ Sub-Second Live Invalidation for {alert.symbol}: {reason}"
                )
                continue

            # 1b. Instant Target 1 / Target 2 / Trailing Milestone
            eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=ltp)
            if eval_res and (eval_res.is_t1_hit or eval_res.is_target_hit or eval_res.trailing_ratcheted):
                now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                with self._lock:
                    alert.current_ltp = ltp
                    alert.ltp = ltp
                    if eval_res.is_t1_hit:
                        alert.stage = "T1_ACHIEVED"
                        alert.target_status = "T1_HIT"
                        if "T1_ACHIEVED" not in (alert.achieved_milestones or []):
                            alert.achieved_milestones.append("T1_ACHIEVED")
                    elif eval_res.is_target_hit:
                        alert.stage = "TARGET_ACHIEVED"
                        alert.target_status = "TARGET_HIT"
                        if "FINAL_ACHIEVED" not in (alert.achieved_milestones or []):
                            alert.achieved_milestones.append("FINAL_ACHIEVED")
                    elif eval_res.trailing_ratcheted:
                        alert.stage = "TRAILING_UPDATE"

                    if eval_res.new_trailing_stop:
                        alert.trailing_stop = eval_res.new_trailing_stop
                    alert.trailing_decision = eval_res.action_decision
                    alert.trailing_rationale = eval_res.rationale
                    self._save()
                self._dispatch(alert)
                logger.info(
                    f"[AutoAlertEngine] ⚡ Sub-Second Target/Trail Hit for {alert.symbol}: {eval_res.action_decision}"
                )

        # 2. Impulse Velocity / Sudden Volatility Spike Detection
        history = self._crypto_tick_history[clean_sym]
        history.append((now_ts, ltp))
        if history:
            oldest_ts, oldest_price = history[0]
            if (now_ts - oldest_ts) >= 10.0 and oldest_price > 0:
                price_delta_pct = abs(ltp - oldest_price) / oldest_price * 100.0
                last_surge = self._crypto_last_surge_eval.get(clean_sym, 0.0)
                if price_delta_pct >= 0.65 and (now_ts - last_surge) >= 120.0:
                    self._crypto_last_surge_eval[clean_sym] = now_ts
                    logger.info(
                        f"[AutoAlertEngine] ⚡ Live Crypto Impulse Spike on {clean_sym} "
                        f"({price_delta_pct:.2f}% in {int(now_ts - oldest_ts)}s)! Fast scan triggered."
                    )
                    threading.Thread(
                        target=self._scan_single_crypto_symbol, args=(clean_sym,), daemon=True
                    ).start()

    def _scan_single_crypto_symbol(self, sym: str) -> list[AutoAlert]:
        """Scans a single crypto symbol for Squeeze, SMC Momentum, and Options Volatility."""
        from market.crypto_stream import crypto_stream, normalize_crypto_symbol
        from analysis.market_structure import analyze_market_structure
        from engine.alert_preferences import alert_preferences

        if alert_preferences.is_segment_globally_disabled("CRYPTO"):
            return []

        clean_sym = normalize_crypto_symbol(sym).replace("CRYPTO:", "").strip()
        found: list[AutoAlert] = []
        now_dt = datetime.now(IST)
        now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        date_str = now_dt.strftime("%Y%m%d%H%M")

        q = crypto_stream.get_quote(clean_sym)
        if not q or float(q.last_price or 0.0) <= 0:
            return found

        ltp = float(q.last_price)
        chg_pct = float(q.change_pct or 0.0)

        # ── 1. SQUEEZE DETECTOR: Binance Futures 8h Funding Rate & Open Interest ──
        try:
            sq_metrics = crypto_stream.get_squeeze_metrics(clean_sym)
            sq_sig = sq_metrics.get("squeeze_signal", "NEUTRAL")
            fut_data = sq_metrics.get("futures_metrics", {})
            fr = float(fut_data.get("funding_rate_8h", 0.0) or 0.0)

            if sq_sig in ("SHORT_SQUEEZE_IMMINENT", "LONG_FLUSH_RISK"):
                is_bullish = sq_sig == "SHORT_SQUEEZE_IMMINENT"
                direction = "BULLISH" if is_bullish else "BEARISH"
                alert_type = "CRYPTO_SQUEEZE"
                alert_id = f"crypto-sq-{clean_sym.lower()}-{date_str}"
                # Funding rate squeeze at extreme thresholds is a high-conviction structural setup
                squeeze_confidence = 91 if sq_sig == "SHORT_SQUEEZE_IMMINENT" else 90
                risk_usd = round(max(0.5, ltp * 0.018), 2)  # 1.8% structural risk stop

                if is_bullish:
                    sl_price = round(ltp - risk_usd, 2)
                    t1_price = round(ltp + 2.2 * risk_usd, 2)
                    t2_price = round(ltp + 4.0 * risk_usd, 2)
                    headline = f"🪙 CRYPTO SQUEEZE: {clean_sym} Short-Squeeze Imminent @ ${ltp:,.2f}"
                    summary = (
                        f"Heavily short-crowded funding (8h FR: {fr*100:.4f}%). "
                        f"Extreme negative leverage positioning primed for upward cascade. Target: ${t1_price:,.2f}."
                    )
                    action = "BUY_SPOT / LONG"
                    conf = "Binance Futures Short-Crowded Funding Imbalance (FR <= -0.02%)"
                else:
                    sl_price = round(ltp + risk_usd, 2)
                    t1_price = round(ltp - 2.2 * risk_usd, 2)
                    t2_price = round(ltp - 4.0 * risk_usd, 2)
                    headline = f"🪙 CRYPTO SQUEEZE: {clean_sym} Long-Flush Liquidation Risk @ ${ltp:,.2f}"
                    summary = (
                        f"Overheated long leverage (8h FR: +{fr*100:.4f}%). "
                        f"Vulnerable to cascading long liquidations. Downside target: ${t1_price:,.2f}."
                    )
                    action = "SELL_SHORT_FUTURES / SHORT"
                    conf = "Binance Futures Long-Overheated Leverage Imbalance (FR >= +0.04%)"

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type=alert_type,
                    stage="IGNITED" if abs(chg_pct) >= 1.5 else "EARLY_WARNING",
                    symbol=clean_sym,
                    exchange="CRYPTO",
                    direction=direction,
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=ltp,
                    target_level=t1_price,
                    stop_loss=sl_price,
                    confidence=squeeze_confidence,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    market_status="LIVE",
                    metrics={
                        "change_pct": chg_pct,
                        "segment": "CRYPTO",
                        "funding_rate_8h": fr,
                        "open_interest_usd": fut_data.get("open_interest_usd", 0.0),
                        "setup_confluence": conf,
                    },
                    actionable_plan={
                        "action": action,
                        "segment": "CRYPTO",
                        "contract": f"CRYPTO:{clean_sym}",
                        "entry_range": f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}",
                        "stop_loss": f"${sl_price:,.2f}",
                        "target": f"${t1_price:,.2f}",
                        "target_2": f"${t2_price:,.2f}",
                        "risk_reward": "1:2.2",
                        "when_to_buy": "Enter on order book spread with defined risk below invalidation SL.",
                        "when_to_wait": "Do not chase if price extends > 0.8% beyond entry.",
                        "no_chase_boundary": round(ltp * 1.008, 2) if is_bullish else round(ltp * 0.992, 2),
                        "setup_confluence": conf,
                        "profit_rule": "Scale 50% at T1, trail remaining on 20-EMA / break-even.",
                        "trade_plan": {
                            "symbol": clean_sym,
                            "direction": "LONG" if is_bullish else "SHORT",
                            "timeframe": "15M",
                            "entry_price": ltp,
                            "invalidation_stop": sl_price,
                            "target_1": t1_price,
                            "target_2": t2_price,
                            "risk_reward": "1:2.2",
                        },
                    },
                )
                if self.record_alert(alert):
                    found.append(alert)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] Squeeze check failed for {clean_sym}: {e}")

        # ── 2. SMC MOMENTUM DETECTOR: Order Block Reclaim & CHoCH Reversal ──
        try:
            df = crypto_stream.get_klines(clean_sym, interval="15m", limit=120)
            if not df.empty and len(df) >= 30:
                smc = analyze_market_structure(symbol=clean_sym, df=df, exchange="CRYPTO", timeframe="15m")
                regime = (smc.regime or "").upper()

                if regime == "BULLISH" and smc.active_demand_zones:
                    ob = smc.active_demand_zones[0]
                    if ob.bottom <= ltp <= (ob.top * 1.025):
                        sl_price = round(ob.bottom * 0.992, 2)
                        risk_usd = ltp - sl_price
                        if 0 < risk_usd <= (ltp * 0.045):
                            t1_price = round(ltp + 2.4 * risk_usd, 2)
                            t2_price = round(ltp + 4.2 * risk_usd, 2)
                            # IGNITED stage = price already inside OB = confirmed entry trigger
                            # EARLY_WARNING = approaching OB but not yet inside
                            smc_stage = "IGNITED" if ltp > ob.top else "EARLY_WARNING"
                            smc_confidence = 91 if smc_stage == "IGNITED" else 85
                            alert_id = f"crypto-smc-{clean_sym.lower()}-{date_str}"
                            headline = f"⚡ CRYPTO SMC ALPHA: {clean_sym} Demand Order Block Reclaim @ ${ltp:,.2f}"
                            summary = (
                                f"Smart Money structural reclaim at 15m Demand OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                                f"Bullish structure confirmed. Upside target: ${t1_price:,.2f}."
                            )
                            conf = f"15m Bullish Regime + Unmitigated Demand OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"
                            alert = AutoAlert(
                                alert_id=alert_id,
                                alert_type="CRYPTO_MOMENTUM",
                                stage=smc_stage,
                                symbol=clean_sym,
                                exchange="CRYPTO",
                                direction="BULLISH",
                                headline=headline,
                                summary=summary,
                                ltp=ltp,
                                trigger_level=round(ob.top, 2),
                                target_level=t1_price,
                                stop_loss=sl_price,
                                confidence=smc_confidence,
                                created_at=now_iso,
                                is_live=True,
                                environment="LIVE",
                                market_status="LIVE",
                                metrics={
                                    "change_pct": chg_pct,
                                    "segment": "CRYPTO",
                                    "ob_bottom": ob.bottom,
                                    "ob_top": ob.top,
                                    "setup_confluence": conf,
                                },
                                actionable_plan={
                                    "action": "BUY_SPOT / LONG",
                                    "segment": "CRYPTO",
                                    "contract": f"CRYPTO:{clean_sym}",
                                    "entry_range": f"${round(ob.bottom, 2):,.2f} – ${round(ob.top * 1.005, 2):,.2f}",
                                    "stop_loss": f"${sl_price:,.2f}",
                                    "target": f"${t1_price:,.2f}",
                                    "target_2": f"${t2_price:,.2f}",
                                    "risk_reward": "1:2.4",
                                    "when_to_buy": "Enter on order block retest or momentum breakout above OB top.",
                                    "when_to_wait": f"Do not chase above ${round(ob.top * 1.012, 2):,.2f}.",
                                    "no_chase_boundary": round(ob.top * 1.012, 2),
                                    "setup_confluence": conf,
                                    "profit_rule": "Scale 50% at T1 (+2.4R), trail remaining to breakeven.",
                                    "trade_plan": {
                                        "symbol": clean_sym,
                                        "direction": "LONG",
                                        "timeframe": "15M",
                                        "entry_price": ltp,
                                        "invalidation_stop": sl_price,
                                        "target_1": t1_price,
                                        "target_2": t2_price,
                                        "risk_reward": "1:2.4",
                                    },
                                },
                            )
                            if self.record_alert(alert):
                                found.append(alert)

                elif regime == "BEARISH" and smc.active_supply_zones:
                    ob = smc.active_supply_zones[0]
                    if (ob.bottom * 0.975) <= ltp <= ob.top:
                        sl_price = round(ob.top * 1.008, 2)
                        risk_usd = sl_price - ltp
                        if 0 < risk_usd <= (ltp * 0.045):
                            t1_price = round(ltp - 2.4 * risk_usd, 2)
                            t2_price = round(ltp - 4.2 * risk_usd, 2)
                            smc_stage = "IGNITED" if ltp < ob.bottom else "EARLY_WARNING"
                            smc_confidence = 91 if smc_stage == "IGNITED" else 85
                            alert_id = f"crypto-smc-{clean_sym.lower()}-{date_str}"
                            headline = f"⚡ CRYPTO SMC BREAKDOWN: {clean_sym} Supply OB Rejection @ ${ltp:,.2f}"
                            summary = (
                                f"Smart Money rejection at 15m Supply OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                                f"Bearish structure confirmed. Downside target: ${t1_price:,.2f}."
                            )
                            conf = f"15m Bearish Regime + Active Supply OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"
                            alert = AutoAlert(
                                alert_id=alert_id,
                                alert_type="CRYPTO_MOMENTUM",
                                stage=smc_stage,
                                symbol=clean_sym,
                                exchange="CRYPTO",
                                direction="BEARISH",
                                headline=headline,
                                summary=summary,
                                ltp=ltp,
                                trigger_level=round(ob.bottom, 2),
                                target_level=t1_price,
                                stop_loss=sl_price,
                                confidence=smc_confidence,
                                created_at=now_iso,
                                is_live=True,
                                environment="LIVE",
                                market_status="LIVE",
                                metrics={
                                    "change_pct": chg_pct,
                                    "segment": "CRYPTO",
                                    "ob_bottom": ob.bottom,
                                    "ob_top": ob.top,
                                    "setup_confluence": conf,
                                },
                                actionable_plan={
                                    "action": "SELL_SHORT_FUTURES / SHORT",
                                    "segment": "CRYPTO",
                                    "contract": f"CRYPTO:{clean_sym}",
                                    "entry_range": f"${round(ob.bottom * 0.995, 2):,.2f} – ${round(ob.top, 2):,.2f}",
                                    "stop_loss": f"${sl_price:,.2f}",
                                    "target": f"${t1_price:,.2f}",
                                    "target_2": f"${t2_price:,.2f}",
                                    "risk_reward": "1:2.4",
                                    "when_to_buy": "Short on rejection wick from supply OB.",
                                    "when_to_wait": f"Do not chase below ${round(ob.bottom * 0.988, 2):,.2f}.",
                                    "no_chase_boundary": round(ob.bottom * 0.988, 2),
                                    "setup_confluence": conf,
                                    "profit_rule": "Scale 50% at T1, trail stop to breakeven.",
                                    "trade_plan": {
                                        "symbol": clean_sym,
                                        "direction": "SHORT",
                                        "timeframe": "15M",
                                        "entry_price": ltp,
                                        "invalidation_stop": sl_price,
                                        "target_1": t1_price,
                                        "target_2": t2_price,
                                        "risk_reward": "1:2.4",
                                    },
                                },
                            )
                            if self.record_alert(alert):
                                found.append(alert)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] SMC check failed for {clean_sym}: {e}")

        # ── 3. OPTIONS VOLATILITY & MAX PAIN DETECTOR: Deribit Options Surface (BTC/ETH) ──
        if clean_sym in ("BTCUSDT", "BTC", "ETHUSDT", "ETH"):
            try:
                from market.crypto_options import get_crypto_options_summary

                base_curr = "BTC" if "BTC" in clean_sym else "ETH"
                opt_sum = get_crypto_options_summary(base_curr)
                max_pain = float(opt_sum.get("max_pain", 0.0) or 0.0)
                dist_pct = float(opt_sum.get("max_pain_distance_pct", 0.0) or 0.0)
                pcr_oi = float(opt_sum.get("pcr_open_interest", 1.0) or 1.0)

                if abs(dist_pct) >= 4.5 and max_pain > 0:
                    is_bullish = dist_pct < 0
                    direction = "BULLISH" if is_bullish else "BEARISH"
                    alert_id = f"crypto-opt-{clean_sym.lower()}-{date_str}"
                    risk_usd = round(max(1.0, ltp * 0.02), 2)  # 2% defined risk stop

                    if is_bullish:
                        sl_price = round(ltp - risk_usd, 2)
                        t1_price = round(max_pain, 2)
                        t2_price = round(max_pain * 1.03, 2)
                        headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Max Pain Magnet at ${max_pain:,.0f}"
                        summary = (
                            f"Spot is {abs(dist_pct):.1f}% below Deribit Max Pain (${max_pain:,.0f}). "
                            f"Options dealer gamma position exerts strong upward gravitational pull into expiry."
                        )
                        action = "BUY_SPOT / LONG"
                    else:
                        sl_price = round(ltp + risk_usd, 2)
                        t1_price = round(max_pain, 2)
                        t2_price = round(max_pain * 0.97, 2)
                        headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Overextended Above Max Pain (${max_pain:,.0f})"
                        summary = (
                            f"Spot is +{dist_pct:.1f}% extended above Deribit Max Pain (${max_pain:,.0f}). "
                            f"Dealer gamma pull indicates mean-reversion pull towards ${max_pain:,.0f}."
                        )
                        action = "SELL_SHORT_FUTURES / SHORT"

                    conf = f"Deribit {base_curr} Max Pain Gravitational Magnet (${max_pain:,.0f} | PCR: {pcr_oi:.2f})"
                    alert = AutoAlert(
                        alert_id=alert_id,
                        alert_type="CRYPTO_VOLATILITY",
                        stage="EARLY_WARNING",
                        symbol=clean_sym,
                        exchange="CRYPTO",
                        direction=direction,
                        headline=headline,
                        summary=summary,
                        ltp=ltp,
                        trigger_level=ltp,
                        target_level=t1_price,
                        stop_loss=sl_price,
                        confidence=85,
                        created_at=now_iso,
                        is_live=True,
                        environment="LIVE",
                        market_status="LIVE",
                        metrics={
                            "change_pct": chg_pct,
                            "segment": "CRYPTO",
                            "max_pain": max_pain,
                            "max_pain_dist_pct": dist_pct,
                            "pcr_oi": pcr_oi,
                            "setup_confluence": conf,
                        },
                        actionable_plan={
                            "action": action,
                            "segment": "CRYPTO",
                            "contract": f"CRYPTO:{clean_sym}",
                            "entry_range": f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}",
                            "stop_loss": f"${sl_price:,.2f}",
                            "target": f"${t1_price:,.2f}",
                            "target_2": f"${t2_price:,.2f}",
                            "risk_reward": f"1:{round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)}",
                            "when_to_buy": "Execute on structural support with defined risk below SL.",
                            "when_to_wait": "Do not chase if price moves > 1% towards Max Pain without retest.",
                            "no_chase_boundary": round(ltp * 1.01, 2) if is_bullish else round(ltp * 0.99, 2),
                            "setup_confluence": conf,
                            "profit_rule": f"Scale 50% at Max Pain magnet (${max_pain:,.0f}), trail remainder.",
                            "trade_plan": {
                                "symbol": clean_sym,
                                "direction": direction,
                                "timeframe": "SWING",
                                "entry_price": ltp,
                                "invalidation_stop": sl_price,
                                "target_1": t1_price,
                                "target_2": t2_price,
                                "risk_reward": f"1:{round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)}",
                            },
                        },
                    )
                    if self.record_alert(alert):
                        found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Options gravity check failed for {clean_sym}: {e}")

        return found

    def scan_crypto_now(self) -> list[AutoAlert]:
        """
        24x7 Real-Time Autonomous Crypto Market Alert Scanner.
        Evaluates top liquid crypto benchmarks (BTC, ETH, SOL, BNB) across:
          1. Leading Leverage & Funding Squeeze (Binance Futures Open Interest + 8h Funding Rate)
          2. Smart Money Concepts (15m Market Structure, CHoCH, and Order Block bounces)
          3. Deribit Options Surface & Max Pain Magnet (BTC/ETH Options Volatility)
        """
        found: list[AutoAlert] = []
        universe = self.watched_crypto
        for sym in universe:
            alerts = self._scan_single_crypto_symbol(sym)
            found.extend(alerts)
        return found

    def scan_fresh_signals_now(self, segment: str = "AUTO") -> list[AutoAlert]:
        """
        Scans watched universe for fresh market signals across detectors.
        segment: 'AUTO' (matches active IST session) | 'EQUITY' | 'COMMODITY' | 'CURRENCY' | 'CRYPTO' | 'ALL'
        """
        results: list[AutoAlert] = []
        seg = (segment or "AUTO").upper()

        if seg == "ALL":
            results.extend(self.scan_equity_nfo_now())
            results.extend(self.scan_commodities_now())
            results.extend(self.scan_currency_now())
            results.extend(self.scan_crypto_now())
            return results

        if seg in ("EQUITY", "NFO"):
            return self.scan_equity_nfo_now()
        if seg in ("COMMODITY", "MCX"):
            return self.scan_commodities_now()
        if seg in ("CURRENCY", "CDS"):
            return self.scan_currency_now()
        if seg in ("CRYPTO", "BINANCE"):
            return self.scan_crypto_now()

        # Default AUTO: respect strict operational sessions
        session = get_current_ist_session()
        if session["equity_nfo"]:
            results.extend(self.scan_equity_nfo_now())
        if session["currency"]:
            results.extend(self.scan_currency_now())
        if session["commodity"]:
            results.extend(self.scan_commodities_now())

        # 24x7 Continuous Global Desk: Crypto
        from engine.alert_preferences import alert_preferences

        if not alert_preferences.is_segment_globally_disabled("CRYPTO"):
            results.extend(self.scan_crypto_now())

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

        # Crypto is 24x7 continuous global exchange
        active_exchanges.append("CRYPTO")

        is_test_runner = (
            (os.environ.get("CHANAKYA_TESTING") == "1")
            or (os.environ.get("DEPLOY_MODE") == "test")
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )

        if not active_exchanges and not is_test_runner:
            logger.info(
                "[AutoAlertEngine] All market sessions currently closed (holiday/after-hours). Skipping live market scans."
            )
            return []

        eval_exchanges = active_exchanges if active_exchanges else None

        # 1. Check invalidations on existing alerts first
        self.check_and_alert_invalidations(exchanges=eval_exchanges)
        # 2. Check in-flight decay & danger zones on existing alerts
        self.check_and_alert_in_flight_decay(exchanges=eval_exchanges)
        # 3. Check target milestones & trailing stop updates on existing alerts
        self.check_and_alert_targets_and_trailing(exchanges=eval_exchanges)
        # 4. Check for fresh market signals
        return self.scan_fresh_signals_now(segment=segment)

    # ── Daemon Thread Poller ────────────────────────────────────

    def start_polling(self, interval_seconds: int = 45) -> None:
        """Starts background evaluation loop."""
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        # Initialize 24x7 real-time crypto stream listener for sub-second event execution
        self._init_crypto_stream_listener()
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
                if session["currency"] and not alert_preferences.is_segment_globally_disabled(
                    "CURRENCY"
                ):
                    self.check_and_alert_invalidations(exchanges=["CDS"])
                    self.check_and_alert_in_flight_decay(exchanges=["CDS"])
                    self.check_and_alert_targets_and_trailing(exchanges=["CDS"])
                    self.scan_currency_now()

                # Phase 3: MCX Commodities Desk (09:00 - 23:30 IST continuous session)
                if session["commodity"] and not alert_preferences.is_segment_globally_disabled(
                    "COMMODITY"
                ):
                    self.check_and_alert_invalidations(exchanges=["MCX"])
                    self.check_and_alert_in_flight_decay(exchanges=["MCX"])
                    self.check_and_alert_targets_and_trailing(exchanges=["MCX"])
                    self.scan_commodities_now()

                # Phase 4: Automated Post-Market EOD Report (triggers at/after 15:45 IST)
                try:
                    from engine.eod_report_generator import check_and_trigger_daily_eod

                    check_and_trigger_daily_eod()
                except Exception as _eod_err:
                    logger.debug(f"[AutoAlertEngine] EOD trigger check: {_eod_err}")

                # Phase 5: 24x7 Continuous Crypto Intelligence Desk (Binance Spot/Futures & Deribit Options)
                if not alert_preferences.is_segment_globally_disabled("CRYPTO"):
                    self.check_and_alert_invalidations(exchanges=["CRYPTO"])
                    self.check_and_alert_in_flight_decay(exchanges=["CRYPTO"])
                    self.check_and_alert_targets_and_trailing(exchanges=["CRYPTO"])
                    self.scan_crypto_now()

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
        horizon: Optional[str] = None,
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
            raw_tokens = (
                [segment.upper()] if isinstance(segment, str) else [str(s).upper() for s in segment]
            )
            if "ALL" not in raw_tokens:
                res = [
                    a
                    for a in res
                    if (getattr(a, "segment", None) or classify_alert_segment(a)).upper()
                    in allowed_segs
                ]

        if horizon:
            res = [
                a
                for a in res
                if (getattr(a, "time_horizon", "INTRADAY") or "INTRADAY").upper() == horizon.upper()
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

    def archive_all_invalidated(self, reason: Optional[str] = None) -> int:
        """Bulk archives all currently invalidated auto-alerts."""
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        archived_count = 0
        with self._lock:
            for alert in self._alerts:
                if (alert.is_invalidated or alert.stage == "INVALIDATED") and not alert.is_archived:
                    alert.is_archived = True
                    alert.archived_at = now_iso
                    alert.archive_reason = reason or "Bulk archived invalidated setups"
                    archived_count += 1
            if archived_count > 0:
                self._save()
        logger.info(f"[AutoAlertEngine] Bulk archived {archived_count} invalidated setups.")
        return archived_count

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
                a.is_invalidated = True
                exp_label = a.expiry_date or "weekly/intraday shelf-life passed"
                if a.time_horizon == "INTRADAY":
                    cutoff = (
                        "23:15 IST"
                        if (
                            a.exchange == "MCX"
                            or (a.symbol or "").upper()
                            in (
                                "GOLD",
                                "GOLDM",
                                "SILVER",
                                "SILVERM",
                                "CRUDEOIL",
                                "CRUDEOILM",
                                "COPPER",
                            )
                        )
                        else "15:15 IST"
                    )
                    reason = f"Intraday session expired ({cutoff} cutoff reached). Trade closed."
                else:
                    reason = f"Contract expired ({exp_label})"
                a.archive_reason = a.archive_reason or reason
                a.invalidation_reason = a.invalidation_reason or reason
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

    def clear_test_alerts(self) -> int:
        """
        Purges all synthetic test, simulated, or mock alerts from buffer and persistent storage.
        Guarantees zero contamination of live trading screens.
        """
        purged = 0
        with self._lock:
            surviving: list[AutoAlert] = []
            for a in self._alerts:
                aid = (getattr(a, "alert_id", "") or "").lower()
                sym = (getattr(a, "symbol", "") or "").upper()
                contract = (getattr(a, "contract_symbol", "") or "").upper()
                headline = (getattr(a, "headline", "") or "").upper()
                summary = (getattr(a, "summary", "") or "").upper()
                env = (getattr(a, "environment", "") or "").upper()
                is_test = getattr(a, "is_test", False) or getattr(a, "isTest", False)
                is_live = getattr(a, "is_live", True)
                metrics = getattr(a, "metrics", {}) or {}
                if isinstance(metrics, dict) and metrics.get("is_test"):
                    is_test = True

                is_sim = (
                    is_test
                    or env in ("TEST", "SIMULATE", "DEMO")
                    or not is_live
                    or aid.startswith("test-")
                    or aid.startswith("sim-")
                    or "[TEST]" in headline
                    or "🧪" in headline
                    or "SIMULAT" in headline
                    or "SIMULAT" in summary
                    or "RELIANCE" in sym
                    or "RELIANCE" in contract
                    or "2900CE" in contract
                    or "SHEDDING 14.5%" in summary
                    or "COILING FOR MOMENTUM" in summary
                )

                if is_sim:
                    purged += 1
                else:
                    surviving.append(a)

            if purged > 0 or len(surviving) != len(self._alerts):
                self._alerts = surviving
                self._save()
                logger.info(f"[AutoAlertEngine] Purged {purged} test/simulated alerts from engine memory and storage.")
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
                    elif dte is not None and (dte > 8 if a.symbol.upper() in ("NIFTY",) else dte > 35):
                        purged += 1
                        logger.info(
                            f"[AutoAlertEngine] Purged distant gamma alert {a.alert_id} "
                            f"({a.symbol} {a.strike}): DTE {dte}"
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
                    logger.debug(
                        "[AutoAlertEngine] auto_alerts.json is empty; initializing clean state."
                    )
                    return
                try:
                    data = json.loads(content)
                except Exception as parse_err:
                    logger.warning(
                        f"[AutoAlertEngine] Corrupted auto_alerts.json detected ({parse_err}); backing up and initializing clean state."
                    )
                    try:
                        backup_path = target_path.with_name(
                            f"{target_path.name}.corrupt.{int(time.time())}"
                        )
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
                                original_call_time=d.get("original_call_time")
                                or d.get("created_at"),
                                in_flight_warning_sent=bool(d.get("in_flight_warning_sent", False)),
                                in_flight_warning_reason=d.get("in_flight_warning_reason"),
                                in_flight_warning_at=d.get("in_flight_warning_at"),
                                mtf_confluence=d.get("mtf_confluence"),
                                vix_regime=d.get("vix_regime"),
                                telegram_dispatched=bool(d.get("telegram_dispatched", False)),
                                dispatched_channels=list(d.get("dispatched_channels", [])),
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
                # 1. Automatically reap and archive expired derivative alerts
                self._reap_expired_alerts_unlocked(purge=False)
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
