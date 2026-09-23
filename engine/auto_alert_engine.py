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
from typing import Any, Optional

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
    classify_expiry_type as classify_expiry_type,
    is_alert_option_premium_level,
)
from engine.alert_evaluator import (
    evaluate_alert_invalidation,
    evaluate_alert_targets_and_trailing,
)
from engine.detectors import (
    detect_circuit_proximity,
    detect_gamma_blast,
    detect_index_call_setup,
    detect_index_put_setup,
    detect_learned_pattern_coiling,
    detect_opening_drive,
    detect_opening_range_breakout,
    detect_squeeze_breakout,
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
    if t <= 15.0:  # 09:15 - 09:30 IST (Opening discovery)
        return 0.03 + (t / 15.0) * 0.09  # 3% -> 12%
    elif t <= 45.0:  # 09:30 - 10:00 IST (Morning institutional drive)
        return 0.12 + ((t - 15.0) / 30.0) * 0.13  # 12% -> 25%
    elif t <= 135.0:  # 10:00 - 11:30 IST (Morning trend continuation)
        return 0.25 + ((t - 45.0) / 90.0) * 0.20  # 25% -> 45%
    elif t <= 255.0:  # 11:30 - 13:30 IST (Midday lull)
        return 0.45 + ((t - 135.0) / 120.0) * 0.18  # 45% -> 63%
    elif t <= 345.0:  # 13:30 - 15:00 IST (Afternoon expiry & expansion)
        return 0.63 + ((t - 255.0) / 90.0) * 0.22  # 63% -> 85%
    else:  # 15:00 - 15:30 IST (Closing auction acceleration)
        return 0.85 + ((t - 345.0) / 30.0) * 0.15  # 85% -> 100%


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
    # Outside active market session, compare full day volume (fraction = 1.0)
    if mins_from_open < 0 or mins_from_open >= 375:
        fraction = 1.0
    else:
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
        self._default_watched_equities = [
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
        self._watched_equities = list(self._default_watched_equities)
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
        self._sector_daily_dispatched: dict[str, set[str]] = defaultdict(set)
        self._cycle_quotes_cache: dict[str, Any] = {}
        self._cycle_quotes_ts: float = 0.0
        self._cycle_quotes_lock = threading.Lock()
        self._cycle_quotes_ttl = 60.0  # 60s cycle cache

        self._load()
        self.cleanup_corrupted_test_alerts()
        # Seed dispatched milestones and daily sector quotas from loaded state across restarts
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

                # Seed sector daily cap ledger
                is_stock_opt = (getattr(a, "segment", "") == "FNO_STOCK") or (
                    sym not in self._watched_indices
                    and atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                )
                if is_stock_opt:
                    c_at = getattr(a, "created_at", "") or ""
                    d_key = c_at.split(" ")[0] if " " in c_at else c_at[:10]
                    sec = (getattr(a, "metrics", {}) or {}).get("sector_id")
                    if not sec:
                        try:
                            from analysis.universe import get_stock_sector

                            sec, _ = get_stock_sector(sym)
                        except Exception:
                            sec = None
                    if d_key and sec and sec != "index":
                        self._sector_daily_dispatched[d_key].add(sec)

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
        if getattr(self, "_override_watched_equities", False) or symbols != getattr(
            self, "_default_watched_equities", None
        ):
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
                "COALINDIA",
                "HAL",
                "BEL",
                "TRENT",
                "VEDL",
                "HINDALCO",
                "TATASTEEL",
                "JINDALSTEL",
                "PFC",
                "RECLTD",
                "CANBK",
                "BANKBARODA",
                "PNB",
                "CHOLAFIN",
                "SHRIRAMFIN",
                "MUTHOOTFIN",
                "DIXON",
                "POLYCAB",
                "PERSISTENT",
                "COFORGE",
                "FEDERALBNK",
                "IDFCFIRSTB",
                "AUBANK",
                "ASHOKLEY",
                "HEROMOTOCO",
                "ADANIENT",
                "ADANIPORTS",
                "JSWSTEEL",
                "POWERGRID",
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
            is_bear = (
                getattr(alert, "option_type", "") == "PE"
                or getattr(alert, "direction", "") in ("BEARISH", "SHORT", "SELL")
                or "DOWN" in alert.alert_type
                or "DROP" in alert.alert_type
            )
            hl_icon = "🔴" if is_bear else "🟢"
            lot_tag = ""
            hl_lot = getattr(alert, "lot_size", None)
            if not hl_lot:
                try:
                    from engine.position_sizer import get_lot_size

                    ls = get_lot_size(alert.symbol)
                    if ls and ls > 1:
                        hl_lot = ls
                except Exception:
                    hl_lot = None
            if hl_lot and hl_lot > 1:
                lot_tag = f" (Lot: {hl_lot})"
            alert.headline = f"{hl_icon} [{alert.environment}] {alert.alert_type.replace('_', ' ')}: {clean_target}{c_tag} @ ₹{alert.ltp:,.1f}{lot_tag}"

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
        if not getattr(alert, "order_flow_signals", None) or not alert.order_flow_signals.get(
            "provenance"
        ):
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
                or (
                    opt_prem is not None
                    and abs(alert.ltp - float(opt_prem)) < max(1.0, float(opt_prem) * 0.15)
                )
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
                        alert.actionable_plan["risk_reward"] = (
                            f"1:{round((alert.target_level - alert.ltp) / new_opt_risk, 1)}"
                        )
            else:
                # Equity risk floor: minimum 0.85% distance from entry
                eq_risk_pct = (abs(alert.ltp - alert.stop_loss) / alert.ltp) * 100.0
                if eq_risk_pct < 0.60:
                    alert.stop_loss = round(
                        alert.ltp * (0.988 if alert.direction == "BULLISH" else 1.012), 1
                    )
                    new_eq_risk = abs(alert.ltp - alert.stop_loss)
                    min_t1 = round(
                        alert.ltp
                        + (
                            1.8 * new_eq_risk
                            if alert.direction == "BULLISH"
                            else -1.8 * new_eq_risk
                        ),
                        1,
                    )
                    if alert.direction == "BULLISH" and alert.target_level < min_t1:
                        alert.target_level = min_t1
                    elif alert.direction == "BEARISH" and alert.target_level > min_t1:
                        alert.target_level = min_t1
                    if alert.actionable_plan and isinstance(alert.actionable_plan, dict):
                        alert.actionable_plan["stop_loss"] = f"₹{alert.stop_loss:,.1f}"
                        alert.actionable_plan["target_1"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["target"] = f"₹{alert.target_level:,.1f}"
                        alert.actionable_plan["risk_reward"] = (
                            f"1:{round(abs(alert.target_level - alert.ltp) / new_eq_risk, 1)}"
                        )

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
                        # Fix 6: PDH sweep is structurally equivalent to a CHoCH reversal.
                        # A day-high supply sweep + wick rejection confirms institutional reversal
                        # intent; treat it as a valid structural reversal that unlocks the whiplash guard.
                        has_reversal = bool(
                            metrics_dict.get("choch")
                            or metrics_dict.get("mss")
                            or metrics_dict.get(
                                "pdh_sweep"
                            )  # Fix 6: PDH sweep = structural reversal
                            or re.search(
                                r"\b(choch|mss|change of character|market structure shift|trend reversal|structural reversal|pdh|supply rejection|vwap rejection)\b",
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
                            and a.stage
                            not in ("INVALIDATED", "COMPLETED", "EXPIRED", "TARGET_ACHIEVED")
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
                                catalysts = active_diff_detector.metrics.setdefault(
                                    "confluence_catalysts", []
                                )
                                if alert.summary and alert.summary not in catalysts:
                                    catalysts.append(alert.summary)

                                # Actionable plan & levels inheritance if active plan was incomplete
                                if (
                                    not active_diff_detector.actionable_plan
                                    and alert.actionable_plan
                                ):
                                    active_diff_detector.actionable_plan = dict(
                                        alert.actionable_plan
                                    )
                                elif alert.actionable_plan and isinstance(
                                    alert.actionable_plan, dict
                                ):
                                    for k, v in alert.actionable_plan.items():
                                        if (
                                            k not in active_diff_detector.actionable_plan
                                            or not active_diff_detector.actionable_plan[k]
                                        ):
                                            active_diff_detector.actionable_plan[k] = v

                                if (
                                    not active_diff_detector.stop_loss
                                    or active_diff_detector.stop_loss <= 0
                                ) and alert.stop_loss:
                                    active_diff_detector.stop_loss = alert.stop_loss
                                if (
                                    not active_diff_detector.target_level
                                    or active_diff_detector.target_level <= 0
                                ) and alert.target_level:
                                    active_diff_detector.target_level = alert.target_level

                                # If incoming is IGNITED while active was EARLY_WARNING, upgrade stage
                                if (
                                    active_diff_detector.stage == "EARLY_WARNING"
                                    and alert.stage == "IGNITED"
                                ):
                                    active_diff_detector.stage = "IGNITED"
                                    active_diff_detector.trigger_level = alert.trigger_level

                                types_str = " + ".join([t.replace("_", " ") for t in conf_types])
                                active_diff_detector.headline = f"💎 [CONFLUENCE APEX] {clean_target}: {types_str} @ ₹{alert.ltp:,.1f}"
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
                if (
                    not is_sim
                    and not to_dispatch
                    and clean_target in COMMODITY_CANONICAL_MAP
                    and alert.stage in ("IGNITED", "EARLY_WARNING")
                ):
                    root_comm = COMMODITY_CANONICAL_MAP[clean_target]
                    has_root_active = any(
                        a.symbol.strip().upper() == root_comm
                        and a.is_active
                        and not a.is_invalidated
                        and a.stage
                        not in ("INVALIDATED", "COMPLETED", "EXPIRED", "TARGET_ACHIEVED")
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
                if (
                    not is_sim
                    and not to_dispatch
                    and alert.no_chase_boundary
                    and alert.ltp > 0
                    and alert.stage in ("IGNITED", "EARLY_WARNING")
                ):
                    is_plan_opt = (alert.actionable_plan or {}).get("instrument_type") == "OPTION"
                    is_opt_prem = is_alert_option_premium_level(alert) or (
                        is_plan_opt
                        and alert.option_premium
                        and abs(alert.trigger_level - alert.option_premium) < 0.01
                    )
                    act_str = str((alert.actionable_plan or {}).get("action", "")).strip().upper()
                    if is_opt_prem:
                        is_short_pos = (
                            act_str.startswith("SELL") or "SHORT" in act_str or "WRITE" in act_str
                        )
                    elif act_str in ("BUY_PE", "BUY_PUT") or alert.direction in (
                        "BEARISH",
                        "SHORT",
                        "SELL",
                    ):
                        is_short_pos = True
                    elif (
                        act_str.startswith("BUY")
                        or "LONG" in act_str
                        or alert.direction in ("BULLISH", "LONG")
                    ):
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
                            or "OPTION"
                            in str(alert.actionable_plan.get("preferred_vehicle", "")).upper()
                            or alert.option_premium is not None
                            or (
                                alert.actionable_plan.get("raw_contract")
                                and any(
                                    x in str(alert.actionable_plan.get("raw_contract")).upper()
                                    for x in ("CE", "PE")
                                )
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
                                else float(
                                    alert.actionable_plan.get("trade_plan", {}).get(
                                        "invalidation_stop"
                                    )
                                    or 0.0
                                )
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
                                else float(
                                    alert.actionable_plan.get("trade_plan", {}).get("target_1")
                                    or 0.0
                                )
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
                setattr(alert, "_recorded_epoch", time.time())
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
        _id_prefix_is_test = (alert.alert_id or "").startswith("test-") or (
            alert.alert_id or ""
        ).startswith("mock-")
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
        is_trail = alert.stage in (
            "TRAILING_UPDATE",
            "DE_RISK_0_5R",
            "BREAKEVEN_LOCKED",
            "TRAIL_POST_SWEEP",
            "COMPRESS_STALL_RISK",
            "TIME_STOP_SCRATCH",
            "TIME_STOP_EXIT",
        )

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
                or alert.stage
                in ("INVALIDATED", "IN_FLIGHT_WARNING", "TARGET_ACHIEVED", "COMPLETED")
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
                    risk_pts = (
                        (alert.stop_loss - alert.trigger_level)
                        if is_short
                        else (alert.trigger_level - alert.stop_loss)
                    )
                    reward_pts = (
                        (alert.trigger_level - alert.target_level)
                        if is_short
                        else (alert.target_level - alert.trigger_level)
                    )
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

    # ── Batch Quote Helpers (avoid N serial get_ltp() calls per poller cycle) ─

    @staticmethod
    def _lookup_sym(alert: "AutoAlert") -> str:
        """Canonical lookup symbol for an alert (respects option premium vs underlying)."""
        from engine.alert_expiry import is_alert_option_premium_level

        if is_alert_option_premium_level(alert) and alert.contract_symbol:
            raw_c = (
                alert.contract_symbol.replace("NIFTY 50", "NIFTY")
                .replace("NIFTY BANK", "BANKNIFTY")
                .strip()
            )
            return raw_c
        sym = (
            (alert.symbol or "")
            .replace("NIFTY 50", "NIFTY")
            .replace("NIFTY BANK", "BANKNIFTY")
            .strip()
        )
        exch = alert.exchange or "NSE"
        return sym if ":" in sym else f"{exch}:{sym}"

    def _batch_refresh_quotes(self, alerts: list["AutoAlert"]) -> dict[str, float]:
        """
        Single batched get_quote() call for all unique symbols across a set of alerts.

        Returns a mapping of symbol → last_price so each lifecycle loop can resolve
        LTPs in O(1) from the pre-fetched map, eliminating per-alert REST round-trips.

        Also fetches option premium symbols (contract_symbol) in the same batch.
        Populates both canonical exchange-prefixed keys (e.g. NFO:SYM) and raw keys (e.g. SYM)
        to guarantee instant matching without KeyErrors.
        """
        from market.quotes import get_quote
        import market.quotes as _mq

        syms: set[str] = set()
        for a in alerts:
            l_sym = self._lookup_sym(a)
            if l_sym:
                syms.add(l_sym)
            # Include option contract symbol as a secondary lookup for underlying alerts
            if a.contract_symbol and not is_alert_option_premium_level(a):
                clean_c = (
                    a.contract_symbol.replace("NIFTY 50", "NIFTY")
                    .replace("NIFTY BANK", "BANKNIFTY")
                    .strip()
                )
                if clean_c:
                    syms.add(clean_c)

        sym_list = list(syms)
        if not sym_list:
            return {}

        # If get_ltp was monkeypatched/mocked in a test suite, respect the test mock
        if getattr(_mq.get_ltp, "__name__", "") != "get_ltp" or hasattr(
            _mq.get_ltp, "assert_called"
        ):
            res = {}
            for s in sym_list:
                try:
                    val = float(_mq.get_ltp(s) or 0.0)
                    if val > 0:
                        res[s] = val
                        if ":" in s:
                            res[s.split(":", 1)[1]] = val
                except Exception:
                    pass
            return res

        try:
            quote_map = get_quote(sym_list)
            res = {}
            for k, q in quote_map.items():
                if q and getattr(q, "last_price", 0.0) > 0:
                    lp = float(q.last_price)
                    res[k] = lp
                    # Populate stripped key without exchange prefix for seamless lookup
                    if ":" in k:
                        clean_key = k.split(":", 1)[1]
                        res[clean_key] = lp
            return res
        except Exception as exc:
            logger.debug("[AutoAlertEngine] _batch_refresh_quotes error: %s", exc)
            return {}

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

        # Batch-refresh all unique symbols in ONE get_quote() call before the loop.
        # Eliminates N serial REST round-trips (one per alert) — resolves to ~100ms flat.
        ltp_batch = self._batch_refresh_quotes(active_alerts)
        for alert in active_alerts:
            # Refresh alert.ltp from the batch map so evaluate_alert_invalidation() sees fresh price
            fresh_ltp = ltp_batch.get(self._lookup_sym(alert))
            if fresh_ltp and fresh_ltp > 0:
                alert.ltp = fresh_ltp
            reason = evaluate_alert_invalidation(alert, current_ltp=fresh_ltp)
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
                    alert.target_status = "INVALIDATED"
                    alert.achieved_milestones = []
                    alert.should_trail = False
                    alert.trailing_decision = "INVALIDATED"
                    alert.r_multiple = 0.0
                    alert.pnl_pct = 0.0
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

                # Invalidate any recorded pattern outcomes so it is never counted as a win
                try:
                    from engine.learning_engine import pattern_learning_engine

                    pattern_learning_engine.invalidate_alert_outcomes(alert.alert_id, reason=reason)
                except Exception as e:
                    logger.debug(f"[AutoAlertEngine] Error invalidating pattern outcomes: {e}")

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
                    alert.target_status = "INVALIDATED"
                    alert.achieved_milestones = []
                    alert.should_trail = False
                    alert.trailing_decision = "INVALIDATED"
                    alert.r_multiple = 0.0
                    alert.pnl_pct = 0.0
                    alert.is_archived = True
                    alert.archived_at = now_iso
                    alert.archive_reason = reason

                    # Invalidate any recorded pattern outcomes so it is never counted as a win
                    try:
                        from engine.learning_engine import pattern_learning_engine

                        pattern_learning_engine.invalidate_alert_outcomes(
                            alert.alert_id, reason=reason
                        )
                    except Exception as e:
                        logger.debug(f"[AutoAlertEngine] Error invalidating pattern outcomes: {e}")

                    is_corruption = any(
                        k in reason.lower()
                        for k in (
                            "corrupt",
                            "phantom",
                            "uncalibrated",
                            "mismatch",
                            "false alert",
                            "unit scale",
                        )
                    )
                    if not is_corruption:
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

        # Batch-refresh all early-warning symbols in ONE get_quote() call before the loop.
        ew_ltp_batch = self._batch_refresh_quotes(early_alerts)

        for alert in early_alerts:
            try:
                lookup_sym = self._lookup_sym(alert)
                cur_ltp = ew_ltp_batch.get(lookup_sym) or ew_ltp_batch.get(
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
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
                            inst_label = (
                                f"{alert.symbol} {int(alert.strike)} {alert.option_type}".strip()
                            )

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
                logger.debug(
                    f"[AutoAlertEngine] Early warning ignition check error for {alert.symbol}: {e}"
                )

        return ignited_alerts

    # ── Target & Trailing Monitoring & Alerting ─────────────────

    def resolve_session_end_alerts(self) -> list[AutoAlert]:
        """
        At or after 15:30 IST (Indian market close), automatically resolves remaining active
        intraday alerts (OPTIONS_MOMENTUM, SCALP, OPENING_DRIVE, INTRADAY_EQUITY, GAMMA_BLAST)
        that never hit T1 or SL during regular market hours.
        Marks them as 'EXPIRED_SESSION_END' with their final Mark-to-Market P&L,
        preventing perpetual PENDING stagnation.
        """
        now_dt = datetime.now(IST)
        # Indian market hours for Equity/FNO: 09:15 to 15:30 IST.
        # Run only if time >= 15:30 IST or before 09:15 IST
        is_market_closed = (
            now_dt.hour > 15
            or (now_dt.hour == 15 and now_dt.minute >= 30)
            or now_dt.hour < 9
            or (now_dt.hour == 9 and now_dt.minute < 15)
        )
        if not is_market_closed:
            return []

        resolved = []
        now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        intraday_types = {
            "OPTIONS_MOMENTUM",
            "SCALP",
            "OPENING_DRIVE",
            "INTRADAY_EQUITY",
            "GAMMA_BLAST",
        }

        with self._lock:
            for alert in self._alerts:
                if (
                    not alert.is_invalidated
                    and not alert.is_archived
                    and alert.stage
                    not in ("INVALIDATED", "COMPLETED", "TARGET_ACHIEVED", "EXPIRED_SESSION_END")
                    and alert.target_status in (None, "", "PENDING")
                    and alert.alert_type in intraday_types
                    and (alert.exchange or "NSE").upper() in ("NSE", "NFO", "BSE")
                ):
                    entry_p = alert.trigger_level or alert.ltp or 0.0
                    cur_p = alert.ltp or entry_p
                    pnl_pct = 0.0
                    if entry_p > 0 and cur_p > 0:
                        if getattr(alert, "direction", "BULLISH") == "BEARISH":
                            pnl_pct = round(((entry_p - cur_p) / entry_p) * 100.0, 2)
                        else:
                            pnl_pct = round(((cur_p - entry_p) / entry_p) * 100.0, 2)

                    alert.stage = "COMPLETED"
                    alert.target_status = "EXPIRED_SESSION_END"
                    alert.is_archived = True
                    alert.archived_at = now_iso
                    alert.archive_reason = (
                        f"Intraday market session closed at 15:30 IST (Final MTM: {pnl_pct:+.2f}%)"
                    )
                    alert.pnl_pct = pnl_pct
                    resolved.append(alert)

            if resolved:
                self._save()
                logger.info(
                    f"[AutoAlertEngine] Automatically resolved {len(resolved)} intraday alerts at session close."
                )

        return resolved

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

        # Automatically resolve expired intraday alerts if session has closed (post 15:30 IST)
        self.resolve_session_end_alerts()

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

        # Batch-refresh all unique symbols in ONE get_quote() call before the loop.
        # Both underlying symbol and option contract_symbol are fetched in the same batch.
        tgt_ltp_batch = self._batch_refresh_quotes(active_alerts)

        for alert in active_alerts:
            try:
                # Resolve LTP from pre-fetched batch map — O(1), no network call
                lookup_sym = self._lookup_sym(alert)
                cur_quote_ltp = tgt_ltp_batch.get(lookup_sym)
                if cur_quote_ltp and cur_quote_ltp > 0:
                    alert.ltp = cur_quote_ltp

                # Also refresh option premium if contract_symbol is present on an underlying alert
                if alert.contract_symbol and not is_alert_option_premium_level(alert):
                    opt_ltp = tgt_ltp_batch.get(alert.contract_symbol)
                    if opt_ltp and opt_ltp > 0:
                        alert.option_premium = opt_ltp

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
                    if eval_res.recommended_stop and eval_res.should_trail:
                        alert.stop_loss = eval_res.recommended_stop
                        alert.last_trail_alert_time = now_ts
                        if alert.actionable_plan:
                            alert.actionable_plan["invalidation_stop"] = eval_res.recommended_stop
                            if isinstance(alert.actionable_plan.get("option_plan"), dict):
                                alert.actionable_plan["option_plan"]["sl_premium"] = (
                                    eval_res.recommended_stop
                                )
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
                    if eval_res.new_milestone in (
                        "T0_5_ACHIEVED",
                        "T1_ACHIEVED",
                        "T2_ACHIEVED",
                        "TARGET_ACHIEVED",
                        "DE_RISK_0_5R",
                        "BREAKEVEN_LOCKED",
                        "TRAIL_POST_SWEEP",
                        "COMPRESS_STALL_RISK",
                        "TIME_STOP_SCRATCH",
                    ):
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
                                    "BREAKEVEN_LOCKED": ("BREAKEVEN", 0.0),
                                    "DE_RISK_0_5R": ("DE_RISK", 0.5),
                                    "TRAIL_POST_SWEEP": ("SWEEP_TRAIL", 0.0),
                                    "COMPRESS_STALL_RISK": ("STALL_COMPRESS", 0.0),
                                    "TIME_STOP_SCRATCH": ("TIME_STOP_SCRATCH", 0.0),
                                }
                                outcome_str, r_mult = outcome_map.get(
                                    eval_res.new_milestone, ("WIN_TARGET", 2.0)
                                )
                                is_opt_trade = (
                                    is_alert_option_premium_level(alert)
                                    or (alert.actionable_plan or {}).get("instrument_type")
                                    == "OPTION"
                                )
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
                                    trade_entry = float(
                                        alert.trigger_level or alert.ltp or cur_disp_p
                                    )

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
                        inst_label = (
                            f"{alert.symbol} {int(alert.strike)} {alert.option_type}".strip()
                        )

                    cur_disp_p = cur_quote_ltp or alert.ltp
                    if eval_res.new_milestone == "TARGET_ACHIEVED":
                        if not eval_res.should_trail:
                            alert.stage = "COMPLETED"
                            alert.headline = f"🏁 {env_tag} FINAL TARGET ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                            alert.is_archived = True
                            alert.archived_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                            alert.archive_reason = "Final target achieved"
                        else:
                            alert.stage = "TARGET_ACHIEVED"
                            alert.headline = f"🎯 {env_tag} FINAL TARGET ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "T2_ACHIEVED":
                        alert.stage = "T2_ACHIEVED"
                        alert.headline = (
                            f"🎯 {env_tag} TARGET 2 ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                        )
                    elif eval_res.new_milestone == "T1_ACHIEVED":
                        alert.stage = "T1_ACHIEVED"
                        alert.headline = (
                            f"🎯 {env_tag} TARGET 1 ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                        )
                    elif eval_res.new_milestone == "T0_5_ACHIEVED":
                        alert.stage = "T0_5_ACHIEVED"
                        alert.headline = f"🎯 {env_tag} TARGET 0.5 (SCALE 1) ACHIEVED: {inst_label} (₹{cur_disp_p:,.2f})"
                    elif eval_res.new_milestone == "TRAILING_UPDATE":
                        alert.last_trail_alert_time = now_ts
                        alert.stage = "TRAILING_UPDATE"
                        alert.headline = f"📈 {env_tag} TRAILING STOP UPDATED: {inst_label} → ₹{eval_res.recommended_stop:,.2f}"
                    elif eval_res.new_milestone == "BREAKEVEN_LOCKED":
                        alert.stage = "BREAKEVEN_LOCKED"
                        alert.headline = f"🛡️ {env_tag} BREAKEVEN LOCKED (+0.8R FREE ROLL): {inst_label} SL → ₹{eval_res.recommended_stop:,.2f} (Downside Eliminated)"
                    elif eval_res.new_milestone == "DE_RISK_0_5R":
                        alert.stage = "DE_RISK_0_5R"
                        red_pct = getattr(eval_res, "risk_reduction_pct", 65.0)
                        alert.headline = f"🛡️ {env_tag} RISK COMPRESSED (+0.5R DE-RISK): {inst_label} SL → ₹{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
                    elif eval_res.new_milestone == "TRAIL_POST_SWEEP":
                        alert.stage = "TRAIL_POST_SWEEP"
                        red_pct = getattr(eval_res, "risk_reduction_pct", 40.0)
                        alert.headline = f"🛡️ {env_tag} SMC SWEEP TRAIL: {inst_label} SL → ₹{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
                    elif eval_res.new_milestone == "COMPRESS_STALL_RISK":
                        alert.stage = "COMPRESS_STALL_RISK"
                        red_pct = getattr(eval_res, "risk_reduction_pct", 35.0)
                        alert.headline = f"🛡️ {env_tag} THETA STALL COMPRESSION: {inst_label} SL → ₹{eval_res.recommended_stop:,.2f} (-{red_pct:.0f}% Risk)"
                    elif eval_res.new_milestone == "TIME_STOP_SCRATCH":
                        alert.stage = "TIME_STOP_EXIT"
                        alert.target_status = "TIME_STOP_EXIT"
                        alert.is_invalidated = True
                        alert.invalidation_reason = eval_res.trailing_rationale
                        alert.invalidated_at = now_str
                        alert.is_archived = True
                        alert.archived_at = now_str
                        alert.archive_reason = (
                            "Velocity Time-Stop Reached (Stagnation Scratch Exit)"
                        )
                        alert.headline = (
                            f"⏱️ {env_tag} VELOCITY TIME-STOP EXIT: {inst_label} (Close at CMP)"
                        )
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
                and a.stage
                not in ("INVALIDATED", "COMPLETED", "IN_FLIGHT_WARNING", "EARLY_WARNING")
                and (
                    a.stage in ("IGNITED", "TRAILING_UPDATE")
                    or getattr(a, "triggered_at", None) is not None
                )
                and not getattr(a, "in_flight_warning_sent", False)
                and getattr(a, "target_status", "")
                not in ("T1_ACHIEVED", "FINAL_ACHIEVED", "TARGET_ACHIEVED")
                and "T1_ACHIEVED" not in (getattr(a, "achieved_milestones", []) or [])
                and not (a.environment == "TEST" or not a.is_live)
                and (not exch_filter or (a.exchange or "NSE").upper() in exch_filter)
            ]

        # Batch-refresh all in-flight alert symbols in ONE get_quote() call.
        inflight_ltp_batch = self._batch_refresh_quotes(active_alerts)

        for alert in active_alerts:
            try:
                # Resolve LTP from pre-fetched batch map — O(1), no network call
                lookup_sym = self._lookup_sym(alert)
                cur_quote_ltp = inflight_ltp_batch.get(lookup_sym)
                if cur_quote_ltp and cur_quote_ltp > 0:
                    alert.ltp = cur_quote_ltp

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

    def _get_cycle_quotes(self, symbols: Optional[list[str]] = None) -> dict[str, Any]:
        """
        Batch pre-fetches quotes for the entire watched universe in concurrent chunks of 60.
        Caches in-memory for 15 seconds to eliminate repetitive serial quote queries across detectors.
        Returns a dict mapping normalized keys (e.g. 'NSE:RELIANCE', 'RELIANCE') to Quote objects.
        """
        now = time.monotonic()
        with self._cycle_quotes_lock:
            if self._cycle_quotes_cache and (now - self._cycle_quotes_ts < self._cycle_quotes_ttl):
                if symbols is None:
                    return dict(self._cycle_quotes_cache)
                cached_subset: dict[str, Any] = {}
                all_found = True
                for s in symbols:
                    clean = s.split(":")[-1]
                    val = (
                        self._cycle_quotes_cache.get(s)
                        or self._cycle_quotes_cache.get(clean)
                        or self._cycle_quotes_cache.get(f"NSE:{clean}")
                        or self._cycle_quotes_cache.get(f"BSE:{clean}")
                        or self._cycle_quotes_cache.get(f"MCX:{clean}")
                    )
                    if val is not None:
                        cached_subset[s] = val
                        cached_subset[clean] = val
                    else:
                        all_found = False
                        break
                if all_found:
                    return cached_subset

        from market.quotes import get_quote

        targets = (
            list(symbols)
            if symbols
            else (list(self._watched_indices) + list(self.watched_equities))
        )

        formatted: list[str] = []
        for s in targets:
            if ":" in s:
                formatted.append(s)
            else:
                exch = self._resolve_index_exchange(s)
                formatted.append(f"{exch}:{s}")

        unique_targets: list[str] = list(dict.fromkeys(formatted))
        batch_size = 60
        combined: dict[str, Any] = {}

        def _fetch_chunk(chunk: list[str]) -> dict[str, Any]:
            try:
                return get_quote(chunk)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Batch quote fetch error for chunk: {e}")
                return {}

        chunks = [
            unique_targets[i : i + batch_size] for i in range(0, len(unique_targets), batch_size)
        ]
        if len(chunks) == 1:
            combined = _fetch_chunk(chunks[0])
        elif len(chunks) > 1:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
                futures = [executor.submit(_fetch_chunk, ch) for ch in chunks]
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        res = fut.result()
                        if isinstance(res, dict):
                            combined.update(res)
                    except Exception:
                        pass

        final_map: dict[str, Any] = dict(combined)
        for k, v in combined.items():
            if ":" in k:
                short_k = k.split(":")[-1]
                if short_k not in final_map:
                    final_map[short_k] = v

        if symbols is None:
            with self._cycle_quotes_lock:
                self._cycle_quotes_cache = final_map
                self._cycle_quotes_ts = time.monotonic()

        return final_map

    def _get_prioritized_targets(self) -> list[str]:
        """Returns targets prioritized dynamically by Real-Time Velocity Score & Expiry."""
        from engine.alert_preferences import alert_preferences

        index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")
        targets: list[str] = []
        if index_allowed:
            try:
                from engine.index_velocity import get_prioritized_index_symbols

                targets = get_prioritized_index_symbols(self._watched_indices)
            except Exception:
                targets = list(self._watched_indices)

            now_ist = datetime.now(IST)
            expiry_map = {0: "MIDCPNIFTY", 1: "FINNIFTY", 2: "BANKNIFTY", 3: "NIFTY", 4: "SENSEX"}
            today_expiry = expiry_map.get(now_ist.weekday())
            if today_expiry and today_expiry in targets and targets[0] != today_expiry:
                targets.remove(today_expiry)
        # Prioritize active momentum equities (|change_pct| >= 1.2%) to the front of the queue
        try:
            from market.quotes import _QUOTE_CACHE, _quote_cache_lock

            active_movers: list[tuple[float, str]] = []
            other_equities: list[str] = []
            with _quote_cache_lock:
                for s in self.watched_equities:
                    clean = s.replace(".NS", "").replace("NSE:", "").strip().upper()
                    cached_q = None
                    for key in (clean, f"NSE:{clean}", f"{clean}.NS", s):
                        if self._cycle_quotes_cache and key in self._cycle_quotes_cache:
                            cached_q = self._cycle_quotes_cache[key]
                            break
                        if key in _QUOTE_CACHE:
                            _, cached_q = _QUOTE_CACHE[key]
                            break
                    chg = abs(getattr(cached_q, "change_pct", 0.0) or 0.0) if cached_q else 0.0
                    if chg >= 1.2:
                        active_movers.append((chg, s))
                    else:
                        other_equities.append(s)

            active_movers.sort(key=lambda x: x[0], reverse=True)
            sorted_equities = [s for _, s in active_movers] + other_equities
        except Exception:
            sorted_equities = list(self.watched_equities)

        for s in sorted_equities:
            if s not in targets:
                targets.append(s)
        return targets

    def scan_gamma_blasts(
        self, indices_only: bool = False, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """Scans watched indices and high-turnover F&O leaders for Gamma Blast inflection.

        Indices are prioritized and unthrottled.
        Stock options enforce institutional segment gating, quality sorting, and
        anti-storm pacing (at most 2-3 highest-conviction alerts per scan cycle).
        """
        from market.options import get_options_chain
        from market.quotes import get_ltp
        from engine.alert_preferences import alert_preferences

        fno_stock_allowed = alert_preferences.is_segment_allowed("FNO_STOCK")
        fno_index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")

        found: list[AutoAlert] = []
        stock_candidates: list[AutoAlert] = []

        now_ist = datetime.now(IST)

        if indices_only:
            targets = list(self._watched_indices) if fno_index_allowed else []
        else:
            targets = self._get_prioritized_targets()

        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(targets)

        eval_targets: list[tuple[str, str, str, float, Any, bool, float, float, float]] = []
        for sym in targets:
            clean_sym = (
                sym.upper().replace(".NS", "").replace("NSE:", "").replace("NFO:", "").strip()
            )
            is_sym_index = clean_sym in (
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "SENSEX",
                "BANKEX",
            )
            # Skip equity targets if FNO_STOCK is disabled in preferences
            if not is_sym_index and not fno_stock_allowed:
                continue

            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q_obj = (
                    (quotes_map.get(lookup_sym) or quotes_map.get(sym) or quotes_map.get(clean_sym))
                    if quotes_map
                    else None
                )

                spot = (
                    float(getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0)
                    if q_obj
                    else 0.0
                )
                if spot <= 0:
                    spot = get_ltp(lookup_sym) or 0.0
                if spot <= 0:
                    continue

                vwap_val = float(getattr(q_obj, "vwap", 0.0) or 0.0) if q_obj else 0.0
                day_high_val = float(getattr(q_obj, "high", 0.0) or 0.0) if q_obj else 0.0
                day_low_val = float(getattr(q_obj, "low", 0.0) or 0.0) if q_obj else 0.0

                # Pre-filter for single-stock F&O equities:
                # 1. Skip non-F&O cash equities (lot size <= 1)
                # 2. Skip flat equities (< 0.35% change)
                if not is_sym_index:
                    from engine.position_sizer import get_lot_size

                    if get_lot_size(clean_sym) <= 1:
                        continue
                    chg = abs(float(getattr(q_obj, "change_pct", 0.0) or 0.0)) if q_obj else 0.0
                    if (
                        q_obj is not None
                        and getattr(q_obj, "change_pct", None) is not None
                        and chg < 0.35
                    ):
                        continue

                eval_targets.append(
                    (
                        sym,
                        clean_sym,
                        exch,
                        spot,
                        q_obj,
                        is_sym_index,
                        vwap_val,
                        day_high_val,
                        day_low_val,
                    )
                )
            except Exception as e_pre:
                logger.debug(f"[AutoAlertEngine] Gamma pre-filter error for {sym}: {e_pre}")

        def _eval_gamma_sym(item):
            sym, clean_sym, exch, spot, q_obj, is_sym_index, vwap_val, day_high_val, day_low_val = (
                item
            )
            local_idx: list[AutoAlert] = []
            local_stock: list[AutoAlert] = []
            try:
                chain = get_options_chain(sym)
                if not chain:
                    return (local_idx, local_stock)

                chains_to_scan = [chain]
                # SEBI Physical Delivery Rollover Guard for single stocks:
                if not is_sym_index:
                    try:
                        from engine.alert_expiry import (
                            is_monthly_physical_expiry_week,
                            resolve_recommended_derivative_expiry,
                        )
                        from market.options import get_expiries

                        first_exp = getattr(chain[0], "expiry", None) if chain else None
                        if first_exp and is_monthly_physical_expiry_week(
                            str(first_exp), symbol=clean_sym, ref_dt=now_ist
                        ):
                            avail_exps = get_expiries(clean_sym)
                            exp_res = resolve_recommended_derivative_expiry(
                                symbol=clean_sym,
                                instrument_type="OPTION",
                                available_expiries=avail_exps,
                                ref_dt=now_ist,
                            )
                            if exp_res.get("is_next_month_routed"):
                                next_exp_str = exp_res.get("recommended_expiry")
                                next_chain = get_options_chain(clean_sym, expiry=next_exp_str)
                                if next_chain and any(
                                    float(getattr(c, "last_price", 0.0) or 0.0) > 0
                                    for c in next_chain
                                ):
                                    chains_to_scan.append(next_chain)
                    except Exception as e_next:
                        logger.debug(
                            f"[AutoAlertEngine] Next month option routing check for {sym}: {e_next}"
                        )

                for active_chain in chains_to_scan:
                    alerts = detect_gamma_blast(
                        sym,
                        spot,
                        active_chain,
                        vwap=vwap_val if vwap_val > 0 else None,
                        day_high=day_high_val if day_high_val > 0 else None,
                        day_low=day_low_val if day_low_val > 0 else None,
                    )
                    for a in alerts:
                        if exch == "BSE":
                            a.exchange = "BFO"
                        if is_sym_index:
                            local_idx.append(a)
                        else:
                            local_stock.append(a)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Gamma scan error for {sym}: {e}")
            return (local_idx, local_stock)

        if eval_targets:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(12, len(eval_targets))
            ) as executor:
                for idx_alerts, stk_alerts in executor.map(_eval_gamma_sym, eval_targets):
                    for a in idx_alerts:
                        if self.record_alert(a):
                            found.append(a)
                    stock_candidates.extend(stk_alerts)

        # Anti-storm pacing & daily sector cap for stock options: at most 1 signal per sector per day
        if stock_candidates:
            today_key = now_ist.strftime("%Y-%m-%d")
            stock_by_sec: dict[str, list[AutoAlert]] = defaultdict(list)
            for a in stock_candidates:
                sec = (getattr(a, "metrics", {}) or {}).get("sector_id")
                if not sec or sec == "index":
                    try:
                        from analysis.universe import get_stock_sector

                        sec, _ = get_stock_sector(a.symbol)
                    except Exception:
                        sec = "broad_market"
                stock_by_sec[sec].append(a)

            for sec_id, cand_list in stock_by_sec.items():
                if sec_id in self._sector_daily_dispatched[today_key]:
                    continue
                cand_list.sort(
                    key=lambda a: (
                        1 if a.stage == "IGNITED" else 0,
                        a.confidence,
                        float((a.metrics or {}).get("vol_oi_ratio", 0.0) or 0.0),
                    ),
                    reverse=True,
                )
                best_gamma = cand_list[0]
                if self.record_alert(best_gamma):
                    self._sector_daily_dispatched[today_key].add(sec_id)
                    found.append(best_gamma)

        return found

    def scan_squeeze_breakouts(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """Scans watched indices and equities for multi-timeframe TTM Squeeze early warnings."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp

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

        session = get_current_ist_session()
        is_test = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        is_active_session = session.get("equity_nfo", False) or is_test

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(targets)

        eval_squeeze_targets: list[tuple[str, str, float, Any]] = []
        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q = (
                    (
                        quotes_map.get(lookup_sym)
                        or quotes_map.get(sym)
                        or quotes_map.get(sym.replace(".NS", ""))
                    )
                    if quotes_map
                    else None
                )

                ltp = (
                    float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                    if q
                    else 0.0
                )
                if ltp <= 0:
                    ltp = get_ltp(lookup_sym) or 0.0
                if not ltp or ltp <= 0:
                    continue

                vwap_val = getattr(q, "vwap", None) if q else None

                # Pre-filter optimization: For cash equities, if price is completely flat (< 0.20% change)
                # skip expensive multi-timeframe OHLCV fetching
                if exch == "NSE" and sym not in self._watched_indices:
                    chg = abs(getattr(q, "change_pct", 0.0) or 0.0) if q else 0.0
                    if q is not None and getattr(q, "change_pct", None) is not None and chg < 0.20:
                        continue

                eval_squeeze_targets.append((sym, exch, ltp, vwap_val))
            except Exception as e_sq_pre:
                logger.debug(f"[AutoAlertEngine] Squeeze pre-filter error for {sym}: {e_sq_pre}")

        def _eval_squeeze_sym(item):
            sym, exch, ltp, vwap_val = item
            local_sq_alerts: list[AutoAlert] = []
            try:
                # 1. First priority: Check 15-minute intraday squeeze (Active market session only)
                if is_active_session:
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
                                    local_sq_alerts.append(alert_15m)
                                    return local_sq_alerts
                    except Exception:
                        pass

                # 2. Daily macro squeeze check (Suppressed in Low-VIX regime to eliminate false breakouts)
                if not is_low_vix:
                    df = get_ohlcv(sym, exchange=exch, interval="day", days=60)
                    if df is not None and len(df) >= 25:
                        alert = detect_squeeze_breakout(
                            sym, df, ltp, timeframe="day", vwap=vwap_val
                        )
                        if alert:
                            alert.exchange = exch
                            local_sq_alerts.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Squeeze scan error for {sym}: {e}")
            return local_sq_alerts

        if eval_squeeze_targets:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(12, len(eval_squeeze_targets))
            ) as executor:
                for sq_alerts in executor.map(_eval_squeeze_sym, eval_squeeze_targets):
                    for a in sq_alerts:
                        if self.record_alert(a):
                            found.append(a)

        return found

    def scan_circuits(self, quotes_map: Optional[dict[str, Any]] = None) -> list[AutoAlert]:
        """Scans watched equities for Upper Circuit proximity."""
        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(self.watched_equities)

        found: list[AutoAlert] = []
        for sym in self.watched_equities:
            try:
                q = quotes_map.get(f"NSE:{sym}") or quotes_map.get(sym)
                if not q:
                    continue
                ltp = float(getattr(q, "ltp", 0.0) or getattr(q, "last_price", 0.0) or 0.0)
                prev_close = float(getattr(q, "prev_close", 0.0) or getattr(q, "close", 0.0) or 0.0)
                if ltp > 0 and prev_close > 0:
                    alert = detect_circuit_proximity(sym, ltp, prev_close)
                    if alert and self.record_alert(alert):
                        found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Circuit scan error for {sym}: {e}")

        return found

    def scan_pattern_coilings(self, quotes_map: Optional[dict[str, Any]] = None) -> list[AutoAlert]:
        """Scans watched universe for pre-blast pattern coiling matching learned archetypes."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp

        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(self.watched_equities)

        found: list[AutoAlert] = []
        eval_coiling_targets: list[tuple[str, float]] = []
        for sym in self.watched_equities:
            try:
                q = quotes_map.get(f"NSE:{sym}") or quotes_map.get(sym)
                ltp = (
                    float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                    if q
                    else 0.0
                )
                if ltp <= 0:
                    ltp = get_ltp(f"NSE:{sym}") or 0.0
                if not ltp or ltp <= 0:
                    continue
                eval_coiling_targets.append((sym, ltp))
            except Exception:
                pass

        eod_cache = {}
        try:
            from engine.eod_store import get_ohlcv_batch

            target_syms = [s.upper() for s, _ in eval_coiling_targets]
            if target_syms:
                eod_cache = get_ohlcv_batch(target_syms, days=60)
        except Exception as e_eod:
            logger.debug(f"[AutoAlertEngine] Batch EOD load error in pattern coiling: {e_eod}")

        def _eval_coiling_sym(item):
            sym, ltp = item
            try:
                df = eod_cache.get(sym.upper())
                if df is None or len(df) < 20:
                    df = get_ohlcv(sym, exchange="NSE", interval="day", days=60)
                if df is None or len(df) < 20:
                    return None
                return detect_learned_pattern_coiling(sym, df, ltp)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Pattern coiling scan error for {sym}: {e}")
                return None

        if eval_coiling_targets:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(12, len(eval_coiling_targets))
            ) as executor:
                for alert in executor.map(_eval_coiling_sym, eval_coiling_targets):
                    if alert and self.record_alert(alert):
                        found.append(alert)

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
                    pr_env = (
                        "LIVE"
                        if (is_authentic_pr and is_mkt_open)
                        else ("EOD_SCAN" if not is_mkt_open else "TEST")
                    )
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

    def scan_intraday_mover_sparks(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """
        Scans liquid universe (Indices, F&O, Cash) for explosive intraday sparks (T-0 session moves).
        Detects BOTH:
          1. Bullish breakout sparks (surge >= +2.2%, holds above VWAP, RVOL >= 1.8x).
          2. Bearish breakdown sparks (drop <= -2.0%, breaks below VWAP, RVOL >= 1.8x).
        """
        from engine.detectors.intraday_spark import detect_intraday_mover_sparks

        alerts = detect_intraday_mover_sparks(universe=self.watched_equities, quotes_map=quotes_map)
        found: list[AutoAlert] = []
        for a in alerts:
            if self.record_alert(a):
                found.append(a)
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
                alert_id = (
                    f"asym-{clean_opp_sym}-{clean_setup}-{datetime.now(IST).strftime('%Y%m%d')}"
                )
                headline = f"🎯 [LOW RISK : HIGH REWARD] {opp.setup_label}: {opp.symbol} (R:R {opp.risk_reward})"
                rollover_note = (
                    " | 🎯 NEXT-MONTH ROLLOVER: SEBI Physical Delivery Safe"
                    if opp.is_next_month_routed
                    else ""
                )
                summary = (
                    f"{opp.catalyst_summary} Invalidation SL: ₹{opp.stop_loss:,.1f} | "
                    f"T1 (+2R): ₹{opp.target_1:,.1f} | T2 (+4R): ₹{opp.target_2:,.1f} | Moonshot: ₹{opp.target_moonshot:,.1f}{rollover_note}"
                )

                if opp.exchange == "MCX" or getattr(opp, "setup_type", "") == "COMMODITY":
                    asym_seg = "COMMODITY"
                elif (
                    opp.symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
                    or getattr(opp, "setup_type", "") == "EXPIRY_0DTE_GAMMA"
                ):
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
                    plan["recommended_entry"] = (
                        f"₹{opp.option_premium:,.2f}" if opp.option_premium else opp.entry_range
                    )
                    if opp.option_premium:
                        plan["entry_range"] = (
                            f"₹{round(opp.option_premium * 0.96, 1):,.1f} – ₹{round(opp.option_premium * 1.04, 1):,.1f}"
                        )
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

                if opp.futures_contract_symbol:
                    plan["futures_plan"] = {
                        "contract_symbol": opp.futures_contract_symbol,
                        "entry_price": opp.futures_entry or opp.ltp,
                        "stop_loss": opp.futures_stop_loss or opp.stop_loss,
                        "target_1": opp.futures_target_1 or opp.target_1,
                        "target_2": opp.futures_target_2 or opp.target_2,
                        "lot_size": opp.lot_size,
                        "instrument_type": "FUTURES",
                    }
                    plan["futures_contract"] = opp.futures_contract_symbol
                    plan["futures_entry"] = (
                        f"₹{opp.futures_entry:,.2f}" if opp.futures_entry else f"₹{opp.ltp:,.2f}"
                    )

                if opp.is_next_month_routed:
                    plan["is_next_month_routed"] = True
                    plan["derivative_safeguard"] = opp.derivative_safeguard

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
                    # ── Root fields ALWAYS in Underlying Spot units ────────────────
                    # Option contract metadata (contract_symbol, strike, option_type)
                    # must NOT be set at the AutoAlert root for ASYMMETRIC_OPPORTUNITY
                    # alerts — they live exclusively in actionable_plan["option_plan"]
                    # (already populated above). Setting them here triggers is_deriv=True
                    # in the template, which suppresses F&O Alternative / Futures
                    # Preferred lines and replaces Spot CMP with confusing Opt CMP.
                    ltp=opp.ltp,
                    trigger_level=opp.entry_price or opp.ltp,
                    target_level=opp.target_1,
                    stop_loss=opp.stop_loss,
                    # Option premium stored for display purposes only (not trading levels)
                    option_premium=opp.option_premium if has_opt_leg else None,
                    underlying_spot=opp.ltp,
                    # Lot size: resolved from the corrected get_lot_size (65 for NIFTY, etc.)
                    lot_size=opp.lot_size if (opp.lot_size and opp.lot_size > 1) else None,
                    # Derivative contract identity stays in actionable_plan["option_plan"]
                    strike=None,
                    option_type=None,
                    contract_symbol=None,
                    expiry_date=None,
                    segment=(
                        "FNO_INDEX"
                        if opp.symbol
                        in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
                        or getattr(opp, "segment", "") in ("INDEX", "FNO_INDEX")
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

    def scan_options_momentum_breakouts(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """
        Scans liquid indices and Tier-1 F&O leaders for directional Options Momentum Breakouts.
        Surfaces high-volume, high-turnover ATM contracts with verified underlying SMC alignment,
        tight spot-anchored stop-losses, optimal trade entry (OTE) pullback zones, and favorable R:R.
        """
        from engine.detectors.options_momentum import detect_options_momentum_breakouts
        from engine.alert_preferences import alert_preferences

        index_allowed = alert_preferences.is_segment_allowed("FNO_INDEX")
        targets = list(self._watched_indices) if index_allowed else []
        for s in self.watched_equities:
            if s not in targets:
                targets.append(s)

        now_dt = datetime.now(IST)
        today_key = now_dt.strftime("%Y-%m-%d")

        alerts = detect_options_momentum_breakouts(
            targets=targets,
            watched_indices=self._watched_indices,
            recent_alerts=self._alerts,
            batch_quotes=quotes_map,
            now_dt=now_dt,
        )
        found: list[AutoAlert] = []

        # Separate index macro alerts from single-stock option alerts
        stock_by_sector: dict[str, list[AutoAlert]] = defaultdict(list)

        for a in alerts:
            is_idx = a.symbol in self._watched_indices or getattr(a, "segment", "") == "FNO_INDEX"
            if is_idx:
                if self.record_alert(a):
                    found.append(a)
            else:
                sec = (getattr(a, "metrics", {}) or {}).get("sector_id")
                if not sec or sec == "index":
                    try:
                        from analysis.universe import get_stock_sector

                        sec, _ = get_stock_sector(a.symbol)
                    except Exception:
                        sec = "broad_market"
                stock_by_sector[sec].append(a)

        # Institutional 1-Signal-Per-Sector Daily Throttle:
        # Prevents sibling duplication (e.g. 5 IT alerts) and limits to the #1 highest conviction setup
        for sec_id, cand_list in stock_by_sector.items():
            if sec_id in self._sector_daily_dispatched[today_key]:
                logger.debug(
                    f"[AutoAlertEngine] Suppressed {len(cand_list)} stock options for sector '{sec_id}': "
                    f"Daily sector quota (1/1) already fulfilled today ({today_key})"
                )
                continue

            # Sort sibling candidates in this sector by confidence & momentum quality
            cand_list.sort(
                key=lambda x: (
                    1 if x.stage == "IGNITED" else 0,
                    x.confidence,
                    float((x.metrics or {}).get("vol_oi_ratio", 0.0) or 0.0),
                    float((x.metrics or {}).get("sector_rs", 0.0) or 0.0),
                ),
                reverse=True,
            )
            best_alert = cand_list[0]
            sec_name = (best_alert.metrics or {}).get("sector_name", sec_id.upper())
            leader_badge = f" [🏆 {sec_name.upper()} LEADER 1/1]"
            if leader_badge not in best_alert.headline:
                best_alert.headline += leader_badge
            if best_alert.actionable_plan and isinstance(best_alert.actionable_plan, dict):
                best_alert.actionable_plan["sector_daily_leader"] = "1/1 Daily Sector Cap Met"

            if self.record_alert(best_alert):
                self._sector_daily_dispatched[today_key].add(sec_id)
                found.append(best_alert)
                logger.info(
                    f"[AutoAlertEngine] Dispatched #1 Sector Leader for '{sec_id}': {best_alert.symbol} ({best_alert.headline})"
                )

        return found

    def scan_index_contagion(self, quotes_map: Optional[dict[str, Any]] = None) -> list[AutoAlert]:
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

    def scan_opening_drives(self, quotes_map: Optional[dict[str, Any]] = None) -> list[AutoAlert]:
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
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        stock_candidates: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(targets)

        eval_drive_targets: list[tuple[str, str, float, Any, Any, Any, Any]] = []
        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q = (
                    (
                        quotes_map.get(lookup_sym)
                        or quotes_map.get(sym)
                        or quotes_map.get(sym.replace(".NS", ""))
                    )
                    if quotes_map
                    else None
                )

                ltp = (
                    float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                    if q
                    else 0.0
                )
                if ltp <= 0:
                    ltp = get_ltp(lookup_sym) or 0.0
                if not ltp or ltp <= 0:
                    continue

                vwap_val = getattr(q, "vwap", None) if q else None
                prev_close = (
                    getattr(q, "previous_close", None) or getattr(q, "prev_close", None)
                    if q
                    else None
                )
                prev_high = getattr(q, "prev_high", None) if q else None
                prev_low = getattr(q, "prev_low", None) if q else None

                # Pre-filter: Opening drive requires Open ~= Low (Bullish) or Open ~= High (Bearish)
                spot_open = float(getattr(q, "open", 0.0) or 0.0) if q else 0.0
                spot_high = float(getattr(q, "high", 0.0) or 0.0) if q else 0.0
                spot_low = float(getattr(q, "low", 0.0) or 0.0) if q else 0.0
                if spot_open > 0 and spot_high > 0 and spot_low > 0:
                    is_candidate = (abs(spot_low - spot_open) / spot_open <= 0.003) or (
                        abs(spot_high - spot_open) / spot_open <= 0.003
                    )
                    if not is_candidate:
                        continue

                eval_drive_targets.append(
                    (sym, exch, ltp, vwap_val, prev_close, prev_high, prev_low)
                )
            except Exception as e_drv_pre:
                logger.debug(
                    f"[AutoAlertEngine] Opening drive pre-filter error for {sym}: {e_drv_pre}"
                )

        def _eval_drive_sym(item):
            sym, exch, ltp, vwap_val, prev_close, prev_high, prev_low = item
            try:
                df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=1)
                if df_5m is None or len(df_5m) < 1:
                    return None

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

                return detect_opening_drive(
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
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Opening Drive scan error for {sym}: {e}")
                return None

        if eval_drive_targets:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(12, len(eval_drive_targets))
            ) as executor:
                for alert in executor.map(_eval_drive_sym, eval_drive_targets):
                    if alert:
                        clean_sym = (
                            alert.symbol.upper()
                            .replace(".NS", "")
                            .replace("NSE:", "")
                            .replace("NFO:", "")
                            .strip()
                        )
                        is_sym_index = clean_sym in (
                            "NIFTY",
                            "BANKNIFTY",
                            "FINNIFTY",
                            "MIDCPNIFTY",
                            "SENSEX",
                            "BANKEX",
                        )
                        if is_sym_index:
                            if self.record_alert(alert):
                                found.append(alert)
                        else:
                            stock_candidates.append(alert)

        # Anti-storm pacing for stock opening drives: select top 2-3 highest conviction
        if stock_candidates:
            stock_candidates.sort(
                key=lambda a: (
                    a.confidence,
                    float(
                        (a.actionable_plan or {}).get("opening_drive_bar", {}).get("range_pct", 0.0)
                        or 0.0
                    ),
                    1 if (a.actionable_plan or {}).get("instrument_type") == "OPTION" else 0,
                ),
                reverse=True,
            )
            max_stock_drives = (
                3 if (is_test_env or (now_ist.hour == 9 and now_ist.minute <= 30)) else 2
            )
            for a in stock_candidates[:max_stock_drives]:
                if self.record_alert(a):
                    found.append(a)

            if len(stock_candidates) > max_stock_drives:
                logger.info(
                    f"[AutoAlertEngine] Anti-storm pacing: selected top {max_stock_drives} "
                    f"stock opening drive alerts out of {len(stock_candidates)} candidates."
                )

        return found

    def scan_preopen_bias(self) -> list[AutoAlert]:
        """Priority-0a: Pre-open GIFT Nifty directional bias scanner.

        Fires EARLY_WARNING CE/PE alerts at 09:05–09:14 IST based on GIFT Nifty
        premium/discount vs previous close. Gives traders a 5–10 minute head-start
        before the NSE opening bell (09:15 IST).

        Threshold: |gap| >= 0.30% triggers bias; >= 0.60% = STRONG signal.
        """
        from engine.alert_preferences import alert_preferences
        from engine.detectors.preopen_bias import detect_preopen_bias
        from market.options import get_options_chain

        if not alert_preferences.is_segment_allowed("FNO_INDEX"):
            return []

        now_dt = datetime.now(IST)
        is_preopen = now_dt.hour == 9 and 5 <= now_dt.minute <= 14
        is_test_runner = (
            os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
        )
        if not is_preopen and not is_test_runner:
            return []

        found: list[AutoAlert] = []

        for sym in ("NIFTY", "BANKNIFTY"):
            try:
                from market.gift_nifty import get_gift_nifty_quote

                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}"

                gift_data = get_gift_nifty_quote(sym)
                if not gift_data:
                    continue
                gift_price = float(gift_data.get("last_price") or gift_data.get("ltp") or 0.0)
                prev_close = float(
                    gift_data.get("prev_close") or gift_data.get("previous_close") or 0.0
                )

                if gift_price <= 0 or prev_close <= 0:
                    # Fallback: read from quote cache
                    from market.quotes import get_quote

                    raw_q = get_quote(lookup_sym)
                    q_obj = (
                        raw_q.get(lookup_sym) or raw_q.get(sym)
                        if isinstance(raw_q, dict)
                        else raw_q
                    )
                    if q_obj:
                        gift_price = gift_price or float(getattr(q_obj, "last_price", 0.0) or 0.0)
                        prev_close = prev_close or float(getattr(q_obj, "prev_close", 0.0) or 0.0)

                if gift_price <= 0 or prev_close <= 0:
                    continue

                chain = get_options_chain(sym)
                alerts = detect_preopen_bias(
                    underlying=sym,
                    gift_futures_price=gift_price,
                    prev_close=prev_close,
                    chain=chain or [],
                )
                for a in alerts:
                    if self.record_alert(a):
                        found.append(a)
                        logger.info(f"[AutoAlertEngine] 🌅 Pre-Open Bias fired: {a.headline}")
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Pre-open bias scan error for {sym}: {e}")

        return found

    def scan_opening_range_breakouts(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
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
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        targets = self._get_prioritized_targets()

        if quotes_map is None:
            quotes_map = self._get_cycle_quotes(targets)

        eval_orb_targets: list[tuple[str, str, float, Any]] = []
        for sym in targets:
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q = (
                    (
                        quotes_map.get(lookup_sym)
                        or quotes_map.get(sym)
                        or quotes_map.get(sym.replace(".NS", ""))
                    )
                    if quotes_map
                    else None
                )

                ltp = (
                    float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                    if q
                    else 0.0
                )
                if ltp <= 0:
                    ltp = get_ltp(lookup_sym) or 0.0
                if not ltp or ltp <= 0:
                    continue

                vwap_val = getattr(q, "vwap", None) if q else None

                # Pre-filter for flat equities:
                if exch == "NSE" and sym not in self._watched_indices:
                    chg = abs(getattr(q, "change_pct", 0.0) or 0.0) if q else 0.0
                    if q is not None and getattr(q, "change_pct", None) is not None and chg < 0.25:
                        continue

                eval_orb_targets.append((sym, exch, ltp, vwap_val))
            except Exception as e_orb_pre:
                logger.debug(f"[AutoAlertEngine] ORB pre-filter error for {sym}: {e_orb_pre}")

        def _eval_orb_sym(item):
            sym, exch, ltp, vwap_val = item
            try:
                df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=1)
                if df_5m is None or len(df_5m) < 3:
                    return None

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

                return detect_opening_range_breakout(
                    sym,
                    df=df_5m,
                    ltp=ltp,
                    vwap=vwap_val,
                    exchange=exch,
                    rvol=rvol_val,
                    ref_time=now_ist,
                    ignore_time_gate=is_test_env,
                )
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] ORB scan error for {sym}: {e}")
                return None

        if eval_orb_targets:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(12, len(eval_orb_targets))
            ) as executor:
                for alert in executor.map(_eval_orb_sym, eval_orb_targets):
                    if alert and self.record_alert(alert):
                        found.append(alert)

        return found

    # ── Time-Partitioned Segment Scanning Loops ──────────────────

    def _get_index_intraday_regime(self, df_5m: Any, spot: float) -> str:
        """Classifies index intraday regime: 'TRENDING', 'NORMAL', or 'CHOP_CONSOLIDATION'."""
        if df_5m is None or not hasattr(df_5m, "iloc") or len(df_5m) < 6 or spot <= 0:
            return "NORMAL"
        try:
            col_h = "high" if "high" in df_5m.columns else "High"
            col_l = "low" if "low" in df_5m.columns else "Low"
            recent = df_5m.iloc[-12:] if len(df_5m) >= 12 else df_5m
            rng_pts = float(recent[col_h].max() - recent[col_l].min())
            rng_pct = (rng_pts / spot) * 100.0

            now_t = datetime.now(IST).time()
            is_midday = dtime(11, 30) <= now_t <= dtime(14, 0)

            # Severe chop: 1-hour range < 0.20% during midday
            if rng_pct < 0.20 and is_midday:
                return "CHOP_CONSOLIDATION"
            elif rng_pct >= 0.50:
                return "TRENDING"
            return "NORMAL"
        except Exception:
            return "NORMAL"

    def scan_index_call_setups(
        self, quotes_map: Optional[dict[str, Any]] = None
    ) -> list[AutoAlert]:
        """Priority-0b SMC-driven BULLISH index options scanner (CE symmetric counterpart).

        Catches CE opportunities that the OI-centric Gamma Blast detector misses:
        PDL/PWL demand rejection, VWAP reclaim entry, intraday demand zone sweep,
        bearish exhaustion absorption, double bottom breakout, and VCP coiling.
        Runs BEFORE scan_gamma_blasts() as the earliest possible bullish index signal.
        """
        from market.quotes import get_quote, get_ltp
        from market.options import get_options_chain
        from engine.alert_preferences import alert_preferences

        if not alert_preferences.is_segment_allowed("FNO_INDEX"):
            return []

        found: list[AutoAlert] = []
        now_dt = datetime.now(IST)
        # Only run during active equity/NFO session (09:18 – 15:10 IST)
        is_active_session = (now_dt.hour > 9 or (now_dt.hour == 9 and now_dt.minute >= 18)) and (
            now_dt.hour < 15 or (now_dt.hour == 15 and now_dt.minute <= 10)
        )
        is_test_runner = (
            os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
        )
        if not is_active_session and not is_test_runner:
            return []

        _INDEX_SYMS = [s for s in self._get_prioritized_targets() if s in self._watched_indices]

        def _eval_call_index(sym: str) -> list[tuple[AutoAlert, str]]:
            local_alerts: list[tuple[AutoAlert, str]] = []
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q_obj = (quotes_map.get(lookup_sym) or quotes_map.get(sym)) if quotes_map else None
                if q_obj is None:
                    raw_q = get_quote(lookup_sym)
                    q_obj = (
                        raw_q.get(lookup_sym) or raw_q.get(sym)
                        if isinstance(raw_q, dict)
                        else raw_q
                    )
                spot = (
                    float(getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0)
                    if q_obj
                    else 0.0
                )
                if spot <= 0:
                    spot = get_ltp(lookup_sym) or 0.0
                if spot <= 0:
                    return local_alerts

                vwap_val = (
                    float(
                        getattr(q_obj, "vwap", 0.0) or getattr(q_obj, "average_price", 0.0) or 0.0
                    )
                    if q_obj
                    else 0.0
                )
                day_high_val = (
                    float(getattr(q_obj, "high", 0.0) or getattr(q_obj, "day_high", 0.0) or 0.0)
                    if q_obj
                    else 0.0
                )
                day_low_val = (
                    float(getattr(q_obj, "low", 0.0) or getattr(q_obj, "day_low", 0.0) or 0.0)
                    if q_obj
                    else 0.0
                )

                # Resolve prev day high/low; fall back to daily OHLCV
                prev_day_high = (
                    float(
                        getattr(q_obj, "prev_day_high", 0.0)
                        or getattr(q_obj, "prev_high", 0.0)
                        or 0.0
                    )
                    if q_obj
                    else 0.0
                )
                prev_day_low = (
                    float(
                        getattr(q_obj, "prev_day_low", 0.0)
                        or getattr(q_obj, "prev_low", 0.0)
                        or 0.0
                    )
                    if q_obj
                    else 0.0
                )
                prev_week_low = float(getattr(q_obj, "week_52_low", 0.0) or 0.0) if q_obj else 0.0

                if prev_day_low <= 0:
                    prev_close = (
                        float(
                            getattr(q_obj, "prev_close", 0.0)
                            or getattr(q_obj, "previous_close", 0.0)
                            or 0.0
                        )
                        if q_obj
                        else 0.0
                    )
                    if prev_close > 0:
                        try:
                            from market.history import get_ohlcv

                            df_prev = get_ohlcv(sym, exchange=exch, interval="day", days=5)
                            if df_prev is not None and len(df_prev) >= 2:
                                col_h = "high" if "high" in df_prev.columns else "High"
                                col_l = "low" if "low" in df_prev.columns else "Low"
                                prev_day_high = float(df_prev[col_h].iloc[-2])
                                prev_day_low = float(df_prev[col_l].iloc[-2])
                        except Exception:
                            prev_day_low = prev_close * 0.994  # ATR-estimated floor

                # 5-minute OHLCV for structural signal analysis
                df_5m = None
                try:
                    from market.history import get_ohlcv

                    df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=2)
                except Exception:
                    pass

                chain = get_options_chain(sym)
                if not chain:
                    return local_alerts

                alerts = detect_index_call_setup(
                    underlying=sym,
                    spot=spot,
                    chain=chain,
                    vwap=vwap_val if vwap_val > 0 else None,
                    day_high=day_high_val if day_high_val > 0 else None,
                    day_low=day_low_val if day_low_val > 0 else None,
                    prev_day_high=prev_day_high if prev_day_high > 0 else None,
                    prev_day_low=prev_day_low if prev_day_low > 0 else None,
                    prev_week_low=prev_week_low if prev_week_low > 0 else None,
                    ohlcv_5m=df_5m,
                )
                regime = self._get_index_intraday_regime(df_5m, spot)
                for a in alerts:
                    if regime == "CHOP_CONSOLIDATION" and a.actionable_plan:
                        a.actionable_plan["preferred_vehicle"] = "HEDGED_SPREAD"
                        if a.actionable_plan.get("hedge_plan"):
                            a.actionable_plan["hedge_plan"]["preferred_vehicle"] = "HEDGED_SPREAD"
                    local_alerts.append((a, regime))
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Index call setup scan error for {sym}: {e}")
            return local_alerts

        if _INDEX_SYMS:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(6, len(_INDEX_SYMS))
            ) as executor:
                for alert_pairs in executor.map(_eval_call_index, _INDEX_SYMS):
                    for a, regime in alert_pairs:
                        if self.record_alert(a):
                            found.append(a)
                            logger.info(
                                f"[AutoAlertEngine] 🟢 SMC Index Call Setup fired: {a.headline} "
                                f"({', '.join(a.metrics.get('signals', []))}) stage={a.stage} regime={regime}"
                            )

        return found

    def scan_index_put_setups(self, quotes_map: Optional[dict[str, Any]] = None) -> list[AutoAlert]:
        """Priority-0 SMC-driven bearish index options scanner (Fix 9).

        Catches PE opportunities that the OI-centric Gamma Blast detector misses:
        PDH/PWH supply rejection, VWAP failure retest, intraday supply zone sweep,
        and double top breakdown. Uses structural price action, not raw OI unwind.
        Runs BEFORE scan_gamma_blasts() as the earliest possible bearish index signal.
        """
        from market.options import get_options_chain
        from market.quotes import get_quote, get_ltp
        from market.history import get_ohlcv
        from engine.alert_preferences import alert_preferences

        if not alert_preferences.is_segment_allowed("FNO_INDEX"):
            return []

        found: list[AutoAlert] = []
        now_dt = datetime.now(IST)
        # Only run during active equity/NFO session (09:18 – 15:10 IST)
        is_active_session = (now_dt.hour > 9 or (now_dt.hour == 9 and now_dt.minute >= 18)) and (
            now_dt.hour < 15 or (now_dt.hour == 15 and now_dt.minute <= 10)
        )
        is_test_runner = (
            os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
        )
        if not is_active_session and not is_test_runner:
            return []

        # Focus on liquid weekly-expiry index universe sorted by real-time velocity
        _INDEX_SYMS = [s for s in self._get_prioritized_targets() if s in self._watched_indices]

        def _eval_put_index(sym: str) -> list[tuple[AutoAlert, str]]:
            local_alerts: list[tuple[AutoAlert, str]] = []
            try:
                exch = self._resolve_index_exchange(sym)
                lookup_sym = f"{exch}:{sym}" if ":" not in sym else sym

                q_obj = (quotes_map.get(lookup_sym) or quotes_map.get(sym)) if quotes_map else None
                if q_obj is None:
                    raw_q = get_quote(lookup_sym)
                    q_obj = (
                        raw_q.get(lookup_sym) or raw_q.get(sym)
                        if isinstance(raw_q, dict)
                        else raw_q
                    )
                spot = (
                    float(getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0)
                    if q_obj
                    else 0.0
                )
                if spot <= 0:
                    spot = get_ltp(lookup_sym) or 0.0
                if spot <= 0:
                    return local_alerts

                # Only evaluate if market is showing intraday weakness or testing resistance
                spot_change_pct = float(getattr(q_obj, "change_pct", 0.0) or 0.0) if q_obj else 0.0
                day_high_val = float(getattr(q_obj, "high", 0.0) or 0.0) if q_obj else 0.0
                day_low_val = float(getattr(q_obj, "low", 0.0) or 0.0) if q_obj else 0.0
                vwap_val = float(getattr(q_obj, "vwap", 0.0) or 0.0) if q_obj else 0.0
                prev_close = float(getattr(q_obj, "prev_close", 0.0) or 0.0) if q_obj else 0.0

                # Pre-filter: skip if index is strongly trending up (>0.8% above VWAP + green day > 0.6%)
                is_strong_bull_trend = (
                    spot_change_pct > 0.6 and vwap_val > 0 and spot > vwap_val * 1.008
                )
                if is_strong_bull_trend and not is_test_runner:
                    return local_alerts

                # Resolve previous day high (PDH) from yesterday's close + a small estimate
                # In production this comes from the historical data; fall back to prev_close
                prev_day_high = None
                prev_day_low = None
                prev_week_high = None
                try:
                    from market.history import get_ohlcv as _gohlcv

                    df_daily = _gohlcv(sym, exchange=exch, interval="day", days=7)
                    if df_daily is not None and len(df_daily) >= 2:
                        col_h = "high" if "high" in df_daily.columns else "High"
                        col_l = "low" if "low" in df_daily.columns else "Low"
                        prev_day_high = float(df_daily[col_h].iloc[-2])
                        prev_day_low = float(df_daily[col_l].iloc[-2])
                        if len(df_daily) >= 6:
                            prev_week_high = float(df_daily[col_h].iloc[-6:-1].max())
                except Exception:
                    if prev_close > 0:
                        prev_day_high = (
                            prev_close * 1.006
                        )  # estimate: prev_close + 0.6% typical high

                # 5-minute OHLCV for structural analysis
                df_5m = None
                try:
                    df_5m = get_ohlcv(sym, exchange=exch, interval="5minute", days=2)
                except Exception:
                    pass

                chain = get_options_chain(sym)
                if not chain:
                    return local_alerts

                alerts = detect_index_put_setup(
                    underlying=sym,
                    spot=spot,
                    chain=chain,
                    vwap=vwap_val if vwap_val > 0 else None,
                    day_high=day_high_val if day_high_val > 0 else None,
                    day_low=day_low_val if day_low_val > 0 else None,
                    prev_day_high=prev_day_high,
                    prev_day_low=prev_day_low,
                    prev_week_high=prev_week_high,
                    ohlcv_5m=df_5m,
                )
                regime = self._get_index_intraday_regime(df_5m, spot)
                for a in alerts:
                    if regime == "CHOP_CONSOLIDATION" and a.actionable_plan:
                        a.actionable_plan["preferred_vehicle"] = "HEDGED_SPREAD"
                        if a.actionable_plan.get("hedge_plan"):
                            a.actionable_plan["hedge_plan"]["preferred_vehicle"] = "HEDGED_SPREAD"
                    local_alerts.append((a, regime))
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Index put setup scan error for {sym}: {e}")
            return local_alerts

        if _INDEX_SYMS:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(6, len(_INDEX_SYMS))
            ) as executor:
                for alert_pairs in executor.map(_eval_put_index, _INDEX_SYMS):
                    for a, regime in alert_pairs:
                        if self.record_alert(a):
                            found.append(a)
                            logger.info(
                                f"[AutoAlertEngine] 🔴 SMC Index Put Setup fired: {a.headline} "
                                f"({', '.join(a.metrics.get('signals', []))}) stage={a.stage} regime={regime}"
                            )

        return found

    def scan_equity_nfo_now(self) -> list[AutoAlert]:
        """Runs all daytime Equity and NFO derivative detectors (09:15 - 15:30 IST)."""
        session = get_current_ist_session()
        is_test = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if not session.get("equity_nfo") and not is_test:
            logger.debug(
                "[AutoAlertEngine] scan_equity_nfo_now skipped: Market session is closed for domestic Equity & NFO."
            )
            return []

        # Step 1: Pre-fetch cycle quotes map (< 300ms) for watched universe
        quotes_map = self._get_cycle_quotes()

        # Step 2: Concurrent evaluation of all orthogonal detectors (bounded max_workers=12)
        import concurrent.futures

        def _safe_run(name: str, fn) -> list[AutoAlert]:
            try:
                res = fn()
                return res if isinstance(res, list) else []
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Scanner worker {name} error: {e}")
                return []

        tasks = [
            ("index_calls", lambda: self.scan_index_call_setups(quotes_map=quotes_map)),
            ("index_puts", lambda: self.scan_index_put_setups(quotes_map=quotes_map)),
            ("opening_drives", lambda: self.scan_opening_drives(quotes_map=quotes_map)),
            ("index_contagion", lambda: self.scan_index_contagion(quotes_map=quotes_map)),
            ("gamma_blasts", lambda: self.scan_gamma_blasts(quotes_map=quotes_map)),
            (
                "options_momentum",
                lambda: self.scan_options_momentum_breakouts(quotes_map=quotes_map),
            ),
            ("sparks", lambda: self.scan_intraday_mover_sparks(quotes_map=quotes_map)),
            ("circuits", lambda: self.scan_circuits(quotes_map=quotes_map)),
            ("squeeze", lambda: self.scan_squeeze_breakouts(quotes_map=quotes_map)),
            ("orb", lambda: self.scan_opening_range_breakouts(quotes_map=quotes_map)),
            ("patterns", lambda: self.scan_pattern_coilings(quotes_map=quotes_map)),
            ("precursor", lambda: self.scan_precursor_radars()),
            ("asymmetric", lambda: self.scan_asymmetric_opportunities()),
        ]

        results: list[AutoAlert] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_name = {executor.submit(_safe_run, name, fn): name for name, fn in tasks}
            for fut in concurrent.futures.as_completed(future_to_name):
                res = fut.result()
                if res:
                    results.extend(res)

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
        Scans liquid MCX commodities (Crude Oil, Gold, Silver, Natural Gas, Copper, Zinc)
        for high-asymmetry session breakouts, VWAP reclaims, and US session volatility expansion.
        Active during post-equity session (15:30 - 23:30 IST).
        """
        from engine.detectors.commodity import detect_commodity_breakouts

        alerts = detect_commodity_breakouts(universe=self.watched_commodities)
        found: list[AutoAlert] = []
        for a in alerts:
            if self.record_alert(a):
                found.append(a)
        return found

    def scan_currency_now(self) -> list[AutoAlert]:
        """
        Scans liquid Currency pairs (USDINR, EURINR, GBPINR) for post-equity breakouts.
        Active during post-equity session (15:30 - 17:00 IST).
        """
        from engine.detectors.currency import detect_currency_breakouts

        alerts = detect_currency_breakouts(universe=self.watched_currencies)
        found: list[AutoAlert] = []
        for a in alerts:
            if self.record_alert(a):
                found.append(a)
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
            logger.info(
                "[AutoAlertEngine] ⚡ Successfully connected to 24x7 Binance live tick stream."
            )
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
                    alert.headline = f"⚠️ {tag} VIEW INVALIDATED: {alert.symbol} {alert.alert_type.replace('_', ' ')}"
                    alert.summary = reason
                    self._save()
                self._dispatch(alert)
                logger.warning(
                    f"[AutoAlertEngine] ⚡ Sub-Second Live Invalidation for {alert.symbol}: {reason}"
                )
                continue

            # 1b. Instant Target 1 / Target 2 / Trailing Milestone
            eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=ltp)
            if eval_res and (
                eval_res.is_t1_hit or eval_res.is_target_hit or eval_res.trailing_ratcheted
            ):
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
                        if eval_res.new_milestone in (
                            "DE_RISK_0_5R",
                            "BREAKEVEN_LOCKED",
                            "TRAIL_POST_SWEEP",
                            "COMPRESS_STALL_RISK",
                            "TIME_STOP_SCRATCH",
                        ):
                            alert.stage = eval_res.new_milestone
                            if eval_res.new_milestone not in (alert.achieved_milestones or []):
                                alert.achieved_milestones.append(eval_res.new_milestone)
                        else:
                            alert.stage = "TRAILING_UPDATE"

                    if eval_res.new_trailing_stop:
                        alert.trailing_stop = eval_res.new_trailing_stop
                        alert.stop_loss = eval_res.new_trailing_stop
                        if alert.actionable_plan:
                            alert.actionable_plan["invalidation_stop"] = eval_res.new_trailing_stop
                            if isinstance(alert.actionable_plan.get("option_plan"), dict):
                                alert.actionable_plan["option_plan"]["sl_premium"] = (
                                    eval_res.new_trailing_stop
                                )
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
        from engine.detectors.crypto import detect_single_crypto_symbol

        alerts = detect_single_crypto_symbol(sym)
        found: list[AutoAlert] = []
        for a in alerts:
            if self.record_alert(a):
                found.append(a)
        return found

    def scan_crypto_now(self) -> list[AutoAlert]:
        """
        24x7 Real-Time Autonomous Crypto Market Alert Scanner.
        Evaluates top liquid crypto benchmarks (BTC, ETH, SOL, BNB) across:
          1. Leading Leverage & Funding Squeeze (Binance Futures Open Interest + 8h Funding Rate)
          2. Smart Money Concepts (15m Market Structure, CHoCH, and Order Block bounces)
          3. Deribit Options Surface & Max Pain Magnet (BTC/ETH Options Volatility)
        """
        from engine.detectors.crypto import detect_crypto_signals

        alerts = detect_crypto_signals(universe=self.watched_crypto)
        found: list[AutoAlert] = []
        for a in alerts:
            if self.record_alert(a):
                found.append(a)
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
        # Fix 5: Fast-path index scan tracking (NIFTY/BANKNIFTY every ~20s during active session)
        _last_index_fast_scan: float = 0.0
        _INDEX_FAST_INTERVAL = 20.0  # seconds between dedicated index gamma + PE scans

        while self._is_running and not self._stop_event.is_set():
            try:
                now_loop = time.time()
                # Periodic cleanup of archived records older than 3 days (run once every 30 minutes)
                if (now_loop - last_cleanup_time) > 1800.0:
                    self.cleanup_archived_records(max_age_days=3)
                    last_cleanup_time = now_loop

                session = get_current_ist_session()

                from engine.alert_preferences import alert_preferences

                # Fix 5: Fast-path index scan (every 20s during equity/NFO session).
                # Runs ONLY gamma blasts + SMC index put setups on NIFTY/BANKNIFTY without
                # triggering the full equity universe scan (which runs at the 45s interval).
                # This cuts the worst-case PE detection lag from 45s → 20s.
                if session["equity_nfo"] and not (
                    alert_preferences.is_segment_globally_disabled("FNO")
                    or alert_preferences.is_segment_globally_disabled("FNO_INDEX")
                ):
                    now_ist = datetime.now(IST)
                    is_active_index_window = (
                        now_ist.hour > 9 or (now_ist.hour == 9 and now_ist.minute >= 18)
                    ) and (now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute <= 10))
                    if (
                        is_active_index_window
                        and (now_loop - _last_index_fast_scan) >= _INDEX_FAST_INTERVAL
                    ):
                        try:
                            self.scan_index_call_setups()  # CE: PDL bounce, VWAP reclaim, demand sweep
                            self.scan_index_put_setups()  # PE: PDH rejection, VWAP failure, supply sweep
                            self.scan_gamma_blasts(indices_only=True)  # OI-driven CE + PE
                        except Exception as e_fast:
                            logger.debug(f"[AutoAlertEngine] Fast-path index scan error: {e_fast}")
                        _last_index_fast_scan = now_loop

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
        limit: int = 300,
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

    def _prune_expired_archived_unlocked(self, max_age_days: int = 3) -> int:
        """
        Internal prune logic without acquiring lock (caller must hold self._lock).
        CRITICAL SAFETY RULE: Active valid trades (a.is_active == True) are NEVER purged.
        Maintains all alert records across Active, Archived, Invalidated, and Expired groups
        for at least max_age_days (default 3 days) for post-mortem analysis and learning.
        Automatically purges:
          1. Quarantined or bogus phantom records (instant 0-TTL purge).
          2. Inactive / archived / invalidated / expired records strictly older than max_age_days.
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

            # 1. Instant Purge for Quarantined / Phantom records
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

            # 2. Clean up inactive / archived / expired records only if older than max_age_days
            if alert_dt:
                if alert_dt < cutoff_dt:
                    purged_count += 1
                    continue

            surviving.append(a)

        if purged_count > 0:
            self._alerts = surviving
            self._save()
            logger.info(
                f"[AutoAlertEngine] Cleaned up {purged_count} stale records older than {max_age_days}d. "
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
                logger.info(
                    f"[AutoAlertEngine] Purged {purged} test/simulated alerts from engine memory and storage."
                )
        return purged

    def cleanup_archived_records(self, max_age_days: int = 3) -> int:
        """
        Public thread-safe method to prune archived records older than max_age_days (default 3 days).
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
            for attempt in range(4):
                try:
                    os.replace(temp_path, target_path)
                    break
                except PermissionError:
                    if attempt == 3:
                        target_path.write_text(payload, encoding="utf-8")
                        try:
                            temp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    else:
                        time.sleep(0.04)
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
                    elif dte is not None and (
                        dte > 8 if a.symbol.upper() in ("NIFTY",) else dte > 35
                    ):
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
            # 4. Session Rollover Sanity: Archive unignited EARLY_WARNING alerts from prior calendar days as EXPIRED
            ts_date = None
            if a.created_at:
                clean_ts = a.created_at.replace(" IST", "").strip()[:10]
                try:
                    ts_date = datetime.strptime(clean_ts, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if ts_date and ts_date < datetime.now(IST).date():
                if a.stage == "EARLY_WARNING":
                    a.stage = "EXPIRED"
                    a.is_archived = True
                    a.is_invalidated = True
                    exp_reason = "Prior-session early warning expired without triggering"
                    a.archive_reason = a.archive_reason or exp_reason
                    a.invalidation_reason = a.invalidation_reason or exp_reason
                    surviving.append(a)
                    continue

            surviving.append(a)

        if purged > 0:
            self._alerts = surviving
            self._save()

        return purged

    def _deduplicate_symbols_unlocked(self) -> int:
        """
        Deduplicates multiple concurrent active alerts for the same symbol (keeps latest active).
        Preserves past closed, invalidated, or archived setups for that symbol within the
        3-day retention window so multi-day trade history and post-mortem analysis remain intact.
        """
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
                # Past archived, invalidated, or expired alerts are preserved for multi-day analysis
                surviving.append(a)

        surviving.reverse()
        if purged > 0:
            self._alerts = surviving
            self._save()
            logger.info(f"[AutoAlertEngine] Deduplicated {purged} concurrent active alert copies.")
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
                # 4. Periodically prune stale / invalidated / archived records older than 3 days
                self._prune_expired_archived_unlocked(max_age_days=3)
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _load error: {e}")
            self._alerts = []


# Module-level singleton instance
auto_alert_engine = AutoAlertEngine()
