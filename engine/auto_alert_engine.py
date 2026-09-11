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


# ── Data Models ─────────────────────────────────────────────────────────────


INDEX_WEEKLY_EXPIRY_WEEKDAY = {
    "MIDCPNIFTY": 0,  # Monday
    "BANKEX": 0,  # Monday
    "FINNIFTY": 1,  # Tuesday
    "BANKNIFTY": 2,  # Wednesday
    "NIFTY": 3,  # Thursday
    "SENSEX": 4,  # Friday
}


@dataclass
class AutoAlert:
    alert_id: str
    alert_type: (
        str  # GAMMA_BLAST | SQUEEZE_BREAKOUT | CIRCUIT_WARNING | SMC_SWEEP | CONFLUENCE_INFLECTION
    )
    stage: str  # "EARLY_WARNING" | "IGNITED" | "INVALIDATED" | "EXPIRED"
    symbol: str
    exchange: str
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    headline: str
    summary: str
    ltp: float
    trigger_level: float
    target_level: float
    stop_loss: float
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CE" | "PE"
    contract_symbol: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    actionable_plan: dict[str, Any] = field(default_factory=dict)
    confidence: int = 75  # 0 - 100
    created_at: str = ""
    read: bool = False
    is_live: bool = True  # True if generated from real live market data; False if TEST/simulation
    environment: str = "LIVE"  # "LIVE" | "TEST"
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    invalidated_at: Optional[str] = None
    achieved_milestones: list[str] = field(default_factory=list)
    target_status: str = "PENDING"  # "PENDING" | "T1_ACHIEVED" | "T2_ACHIEVED" | "TARGET_ACHIEVED"
    should_trail: bool = False  # Explicit recommendation: whether to trail or not
    trailing_decision: Optional[str] = (
        None  # "BOOK_50_TRAIL_BREAKEVEN" | "TRAIL_DYNAMIC_ATR" | "BOOK_FULL_PROFIT_NO_TRAIL" | "DO_NOT_TRAIL_HOLD_STOP"
    )
    trailing_stop: Optional[float] = None  # Exact rupee level recommended for trailing stop-loss
    trailing_rationale: Optional[str] = None  # Institutional rationale explaining trailing decision
    locked_profit_pts: Optional[float] = None
    locked_profit_pct: Optional[float] = None
    last_trail_alert_time: Optional[float] = None
    is_archived: bool = False
    archived_at: Optional[str] = None
    archive_reason: Optional[str] = None
    expiry_date: Optional[str] = None
    expiry_type: Optional[str] = None  # "WEEKLY" | "MONTHLY"
    underlying_spot: Optional[float] = None
    option_premium: Optional[float] = None
    market_status: str = "SESSION_CLOSED"  # "LIVE" | "PRE_MARKET" | "SESSION_CLOSED"
    lot_size: Optional[int] = None  # Contract market lot size (SEBI 2026 active)
    segment: str = ""  # "FNO" | "EQUITY" | "COMMODITY" | "CURRENCY"
    signal_ref: Optional[str] = None
    r_multiple: Optional[float] = None
    pnl_pct: Optional[float] = None
    updated_at: Optional[str] = None
    triggered_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        if not self.signal_ref:
            try:
                from bot.alert_templates import build_signal_ref
                self.signal_ref = build_signal_ref(
                    symbol=self.symbol,
                    alert_id=self.alert_id,
                    contract=self.contract_symbol or "",
                    created_at=self.created_at,
                )
            except Exception:
                pass
        if not self.segment:
            try:
                from engine.alert_preferences import classify_alert_segment

                self.segment = classify_alert_segment(self)
            except Exception:
                self.segment = "EQUITY"
        if self.lot_size is None:
            if self.metrics and "lot_size" in self.metrics and self.metrics["lot_size"]:
                try:
                    self.lot_size = int(self.metrics["lot_size"])
                except (ValueError, TypeError):
                    pass
            if self.lot_size is None:
                from market.instruments import STANDARD_LOT_SIZES

                clean = (
                    (self.symbol or "")
                    .replace("NSE:", "")
                    .replace("NFO:", "")
                    .replace("BSE:", "")
                    .replace("MCX:", "")
                    .strip()
                    .upper()
                )
                self.lot_size = STANDARD_LOT_SIZES.get(clean)

    @property
    def is_expired(self) -> bool:
        """
        Determines whether a derivative contract or Gamma Blast alert has expired.
        1. Checks explicit expiry_date (15:30 IST on expiry day).
        2. For index options without explicit date, resolves against the weekly expiry calendar.
        3. Gamma blast intraday spikes expire after 24 hours of market time.
        """
        if self.stage == "EXPIRED":
            return True

        # Test and simulation alerts do not expire based on wall-clock time
        if self.environment == "TEST" or not self.is_live or self.alert_id.startswith("test-"):
            return False

        now = datetime.now(IST)

        # 1. Check explicit expiry_date
        if self.expiry_date:
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                try:
                    exp_dt = datetime.strptime(self.expiry_date.strip(), fmt).replace(
                        hour=15, minute=30, second=0, tzinfo=IST
                    )
                    if now >= exp_dt:
                        return True
                    break
                except ValueError:
                    pass

        # 2. Check derivative alerts (options/futures/gamma blast) & Intraday Early Warnings
        created_dt = None
        if self.created_at:
            clean_ts = self.created_at.replace(" IST", "").strip()[:19]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    created_dt = datetime.strptime(clean_ts, fmt).replace(tzinfo=IST)
                    break
                except ValueError:
                    pass

        # 2a. Intraday Session Rollover Invariant:
        # Pre-breakout coiling/early-warning setups belong strictly to their trading session.
        # If created on a prior calendar date (created_dt.date() < now.date()),
        # unignited early warnings expire immediately so yesterday's stale coils never pollute today.
        if self.stage == "EARLY_WARNING" and created_dt and created_dt.date() < now.date():
            return True

        is_deriv = bool(
            self.strike
            or self.option_type
            or self.contract_symbol
            or self.alert_type == "GAMMA_BLAST"
        )

        if is_deriv:
            if created_dt:
                clean_sym = self.symbol.replace("NSE:", "").replace("NFO:", "").strip().upper()
                # Indian index weekly options expiry mapping (only if no explicit expiry date)
                if not self.expiry_date and clean_sym in INDEX_WEEKLY_EXPIRY_WEEKDAY:
                    target_weekday = INDEX_WEEKLY_EXPIRY_WEEKDAY[clean_sym]
                    days_ahead = (target_weekday - created_dt.weekday()) % 7
                    exp_dt = created_dt.replace(hour=15, minute=30, second=0) + timedelta(
                        days=days_ahead
                    )
                    if now >= exp_dt:
                        return True

                # Gamma blast shelf-life: intraday momentum spike expires after 24 hours only if no explicit expiry date
                if self.alert_type == "GAMMA_BLAST" and not self.expiry_date:
                    if (now - created_dt).total_seconds() > 24 * 3600:
                        return True

        return False

    @property
    def is_active(self) -> bool:
        """A trade is active if it is not archived, not invalidated, not expired, and has not completed final target."""
        if self.is_expired:
            return False
        return (
            not self.is_archived
            and not self.is_invalidated
            and self.stage not in ("INVALIDATED", "TARGET_ACHIEVED", "EXPIRED")
            and self.target_status != "TARGET_ACHIEVED"
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = (
            self.invalidated_at
            or self.created_at
            or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        )
        d["is_active"] = self.is_active
        d["is_expired"] = self.is_expired

        # Rich expiry details & next-expiry opportunities
        exp_info = get_expiry_metadata(
            self.expiry_date, self.expiry_type, self.symbol, self.contract_symbol
        )
        d["expiry_details"] = exp_info
        d["expiry_month_name"] = exp_info.get("month_name")
        d["expiry_formatted"] = exp_info.get("formatted")
        d["dte"] = exp_info.get("dte")

        next_opp = get_next_expiry_opportunity(self, exp_info)
        if next_opp:
            d["next_expiry_opportunity"] = next_opp

        return d


def classify_expiry_type(expiry_str: Optional[str], symbol: Optional[str] = None) -> str:
    """
    Classifies an Indian market option contract expiry into 'WEEKLY' or 'MONTHLY'.
    - Single-stock equities in NSE/BSE only have monthly options.
    - Index options have weekly expiries, with the final expiry of the month being 'MONTHLY'.
    """
    if not expiry_str:
        return "MONTHLY"
    try:
        from datetime import datetime, timedelta

        dt = None
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(expiry_str.strip(), fmt)
                break
            except ValueError:
                continue
        if not dt:
            return "MONTHLY"
        sym = (symbol or "").upper()
        # Single-stock derivatives on NSE/BSE are strictly monthly contracts
        if sym and sym not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
            return "MONTHLY"
        # For index options, if adding 7 days changes month, it is the last expiry of that month -> MONTHLY
        if (dt + timedelta(days=7)).month != dt.month:
            return "MONTHLY"
        return "WEEKLY"
    except Exception:
        return "MONTHLY"


def get_expiry_metadata(
    expiry_str: Optional[str],
    expiry_type: Optional[str] = None,
    symbol: Optional[str] = None,
    contract_symbol: Optional[str] = None,
) -> dict[str, Any]:
    """
    Computes human-readable month name, weekly date indicator, DTE, and formatted badge string.
    """
    now = datetime.now(IST).date()
    dt = None
    if expiry_str:
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(expiry_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    if not dt:
        return {
            "formatted": None,
            "month_name": None,
            "dte": None,
            "is_weekly": expiry_type == "WEEKLY",
            "is_monthly": expiry_type != "WEEKLY",
            "weekday": None,
        }

    month_name = dt.strftime("%b %Y")
    weekday = dt.strftime("%a")
    dte = (dt - now).days
    is_weekly = (expiry_type == "WEEKLY") or (classify_expiry_type(expiry_str, symbol) == "WEEKLY")

    if is_weekly:
        formatted = f"{dt.strftime('%d-%b-%Y')} ({weekday}) Weekly Expiry"
    else:
        formatted = f"{month_name} Monthly Expiry ({dt.strftime('%d-%b-%Y')})"

    return {
        "formatted": formatted,
        "month_name": month_name,
        "dte": dte,
        "is_weekly": is_weekly,
        "is_monthly": not is_weekly,
        "weekday": weekday,
        "raw_date": dt.strftime("%Y-%m-%d"),
    }


def get_next_expiry_opportunity(
    alert: "AutoAlert",
    exp_info: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Identifies if the trade benefits from rolling/targeting the next expiry
    with explicit institutional rationale (theta decay, multi-session hold, pin risk).
    """
    is_deriv = bool(
        alert.strike
        or alert.option_type
        or alert.contract_symbol
        or getattr(alert, "derivative_type", None) == "FUT"
        or alert.alert_type in ("GAMMA_BLAST", "FUTURES")
    )
    if not is_deriv:
        return None

    dte = exp_info.get("dte")
    plan = alert.actionable_plan or {}
    trade_plan = plan.get("trade_plan", {}) if isinstance(plan, dict) else {}
    has_overrun_risk = trade_plan.get("session_overrun_risk", False)
    theta_drag = trade_plan.get("theta_drag_pct_of_gain", 0)

    # Opportunity triggers: DTE <= 4 days OR multi-session carry OR high theta drag
    if (dte is not None and dte <= 4) or has_overrun_risk or theta_drag >= 1.0:
        if exp_info.get("is_weekly"):
            rec = "Next Weekly or Monthly Expiry"
            justification = (
                f"Current weekly contract has elevated theta decay risk ({dte if dte is not None else '<4'} DTE). "
                "Targeting the next weekly or monthly expiry affords sufficient runway for the thesis to materialize "
                "without severe gamma pin-risk or rapid premium decay."
            )
        else:
            rec = "Next Monthly Expiry (Oct 2026)"
            justification = (
                f"Current monthly contract is in terminal decay cycle ({dte if dte is not None else '≤4'} DTE). "
                "Rolling to the next monthly cycle provides 30+ sessions of runway and eliminates overnight theta drain."
            )
        return {
            "recommended_contract": rec,
            "tag": "THETA-HEDGED ROLL",
            "justification": justification,
            "dte": dte,
        }
    return None


# ── Invalidation Evaluator ──────────────────────────────────────────────────


def is_alert_option_premium_level(alert: Any) -> bool:
    """
    Determines if an alert's primary numerical price levels (ltp, stop_loss, target_level)
    represent option contract premiums rather than underlying equity/spot prices.
    Returns True for pure option strategies (OPTIONS_MOMENTUM, OPTION_WRITE, GAMMA_BLAST with option_type)
    or when alert.contract_symbol represents an active option contract.
    Returns False for underlying stock/index setups even if an option recommendation is attached.
    """
    atype = str(getattr(alert, "alert_type", "") or "")
    if atype in ("OPTIONS_MOMENTUM", "OPTION_WRITE"):
        return True
    if atype == "GAMMA_BLAST" and getattr(alert, "option_type", None):
        return True

    # Underlying stock/index setups are always anchored to spot
    if atype in (
        "ASYMMETRIC_OPPORTUNITY",
        "SQUEEZE_BREAKOUT",
        "SQUEEZE_BREAKDOWN",
        "POCKET_PIVOT",
        "PRECURSOR_RADAR",
        "SMC_SWEEP",
        "CIRCUIT_WARNING",
        "COMMODITY_MOMENTUM",
    ):
        return False

    has_opt_marker = bool(
        getattr(alert, "contract_symbol", None)
        or getattr(alert, "option_type", None)
        or getattr(alert, "strike", None)
    )
    if not has_opt_marker:
        return False

    # Check contract_symbol pattern for option contracts (e.g. NIFTY24500CE or MAZDOCK2400CE on NFO)
    csym = str(getattr(alert, "contract_symbol", "") or "").upper()
    exch = str(getattr(alert, "exchange", "") or "").upper()
    if csym and (csym.endswith("CE") or csym.endswith("PE")) and exch == "NFO":
        return True

    # Check if ltp is close to option_premium (within 25% tolerance) for other derivatives
    ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
    opt_prem = getattr(alert, "option_premium", None)
    if opt_prem is not None and float(opt_prem) > 0 and ltp > 0:
        prem = float(opt_prem)
        return abs(ltp - prem) <= max(2.0, prem * 0.25)

    return False


def evaluate_alert_invalidation(
    alert: AutoAlert,
    current_ltp: Optional[float] = None,
    current_vwap: Optional[float] = None,
) -> Optional[str]:
    """
    Evaluates if an active AutoAlert has become invalidated.
    Returns the specific invalidation reason string if invalidated, or None if still valid.
    """
    if alert.is_invalidated or alert.stage == "INVALIDATED":
        return None

    is_option = is_alert_option_premium_level(alert)

    # Determine current LTP if not provided
    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            if is_option:
                lookup_sym = alert.contract_symbol or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            else:
                lookup_sym = (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None  # Cannot evaluate without live price quote

    # 1. Stop-Loss Invalidation
    if alert.stop_loss and alert.stop_loss > 0:
        if is_option:
            # Check if option writing / selling position:
            act = str((alert.actionable_plan or {}).get("action", "")).upper()
            is_option_sell = act in ("SELL", "WRITE", "SHORT")
            if not is_option_sell and alert.stop_loss > 0 and alert.target_level > 0:
                ref_entry = alert.option_premium or alert.ltp
                if ref_entry and alert.stop_loss > ref_entry and alert.target_level < ref_entry:
                    is_option_sell = True

            if is_option_sell:
                # Option writing / selling (Short CE / Short PE):
                # Stop-loss is above entry. Breached IF AND ONLY IF premium surges above SL.
                if current_ltp > alert.stop_loss:
                    opt_desc = (
                        "Call"
                        if (alert.option_type == "CE" or alert.direction == "BULLISH")
                        else "Put"
                    )
                    return (
                        f"Option premium surged to ₹{current_ltp:.1f} "
                        f"(breached stop-loss ₹{alert.stop_loss:.1f}). {opt_desc} writing thesis invalidated."
                    )
            else:
                # Option buying (Long CE / Long PE):
                # The stop-loss on the option premium is breached IF AND ONLY IF premium drops below SL.
                if current_ltp < alert.stop_loss:
                    opt_desc = (
                        "Call"
                        if (alert.option_type == "CE" or alert.direction == "BULLISH")
                        else "Put"
                    )
                    return (
                        f"Option premium collapsed to ₹{current_ltp:.1f} "
                        f"(breached stop-loss ₹{alert.stop_loss:.1f}). {opt_desc} gamma thesis invalidated."
                    )
        else:
            # Non-option instruments (Equities / Futures)
            # Dynamic Volatility Noise Margin (0.15x ATR or 0.25% floor)
            # Prevents premature panic invalidations on single-tick 10-paise / sub-cent micro-chop.
            atr_val = 0.0
            if alert.metrics and isinstance(alert.metrics, dict):
                atr_val = float(alert.metrics.get("atr_14d") or alert.metrics.get("atr") or 0.0)
            if atr_val <= 0 and alert.stop_loss > 0:
                atr_val = alert.stop_loss * 0.012

            vol_noise_margin = (
                max(0.15, min(alert.stop_loss * 0.003, 0.15 * atr_val))
                if alert.stop_loss > 0
                else 0.20
            )

            if alert.direction == "BEARISH":
                # For short positions, stop loss is above entry
                ref_entry = alert.ltp or alert.trigger_level or 0.0
                if alert.stop_loss > ref_entry:
                    if current_ltp > (alert.stop_loss + vol_noise_margin):
                        return (
                            f"Price surged to ₹{current_ltp:,.1f} "
                            f"(breached stop-loss ₹{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
                else:
                    if current_ltp < (alert.stop_loss - vol_noise_margin):
                        return (
                            f"Price dropped to ₹{current_ltp:,.1f} "
                            f"(breached stop-loss ₹{alert.stop_loss:,.1f}). Bearish thesis invalidated."
                        )
            else:
                # Bullish / Neutral long positions
                if current_ltp < (alert.stop_loss - vol_noise_margin):
                    return (
                        f"Price dropped to ₹{current_ltp:,.1f} "
                        f"(breached stop-loss ₹{alert.stop_loss:,.1f}). Bullish thesis invalidated."
                    )

    # 2. Detector-Specific Structural Breakdown
    if alert.alert_type == "SQUEEZE_BREAKOUT":
        if alert.trigger_level > 0 and current_ltp < (alert.trigger_level * 0.965):
            retreat_pct = round(
                ((alert.trigger_level - current_ltp) / alert.trigger_level) * 100, 1
            )
            return (
                f"Price retreated {retreat_pct}% below breakout pivot ₹{alert.trigger_level:,.1f} "
                f"(LTP ₹{current_ltp:,.1f}). Squeeze compression lost momentum."
            )
        sma20 = alert.metrics.get("sma20") if alert.metrics else None
        if sma20 and current_ltp < sma20:
            return f"Price broke down below 20-SMA base support ₹{sma20:,.1f} (LTP ₹{current_ltp:,.1f}). Squeeze invalidated."

    elif alert.alert_type == "CIRCUIT_WARNING":
        upper_circuit = alert.trigger_level or (
            alert.metrics.get("upper_circuit", 0.0) if alert.metrics else 0.0
        )
        if upper_circuit > 0:
            dist_to_uc = ((upper_circuit - current_ltp) / upper_circuit) * 100.0
            if dist_to_uc > 3.0:
                return (
                    f"Price backed off {dist_to_uc:.1f}% from upper circuit ceiling ₹{upper_circuit:,.1f} "
                    f"(LTP ₹{current_ltp:,.1f}). Circuit lock threat subsided."
                )

    elif alert.alert_type == "GAMMA_BLAST":
        # Ensure underlying spot price is used for VWAP comparison, not option premium
        underlying_price = None
        if is_option:
            underlying_price = alert.underlying_spot or (
                alert.metrics.get("spot") if alert.metrics else None
            )
            if not underlying_price or underlying_price <= 0:
                try:
                    from market.quotes import get_ltp

                    underlying_price = get_ltp(
                        f"NSE:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                    )
                except Exception:
                    underlying_price = None
        else:
            underlying_price = current_ltp

        if underlying_price and underlying_price > 0 and current_vwap and current_vwap > 0:
            if alert.direction == "BULLISH" and underlying_price < (current_vwap * 0.992):
                return (
                    f"Underlying broke below intraday VWAP ₹{current_vwap:,.1f} "
                    f"(Spot ₹{underlying_price:,.1f}). Long gamma setup invalidated."
                )
            elif alert.direction == "BEARISH" and underlying_price > (current_vwap * 1.008):
                return (
                    f"Underlying reclaimed above intraday VWAP ₹{current_vwap:,.1f} "
                    f"(Spot ₹{underlying_price:,.1f}). Short gamma setup invalidated."
                )

    return None


# ── Target Progression & Decisive Trailing Evaluator ────────────────────────


@dataclass
class TargetTrailingEvaluation:
    new_milestone: Optional[str] = (
        None  # "T1_ACHIEVED" | "TARGET_ACHIEVED" | "TRAILING_UPDATE" | None
    )
    target_status: str = "PENDING"
    should_trail: bool = False
    trailing_decision: str = "DO_NOT_TRAIL_HOLD_STOP"
    recommended_stop: float = 0.0
    trailing_rationale: str = ""
    locked_profit_pts: float = 0.0
    locked_profit_pct: float = 0.0
    r_multiple: float = 0.0
    pnl_pct: float = 0.0
    is_superperforming: bool = False


def evaluate_alert_targets_and_trailing(
    alert: AutoAlert,
    current_ltp: Optional[float] = None,
    current_volume_ratio: Optional[float] = None,
) -> Optional[TargetTrailingEvaluation]:
    """
    Evaluates an active AutoAlert against current market price to determine:
      1. Target milestones reached (Target 1 / 2R Breakeven vs Final Target).
      2. Clear, decisive trailing stop recommendation: WHETHER TO TRAIL OR NOT.
      3. Exact price level to trail stop loss to and profit locked.
    """
    if alert.is_invalidated or alert.stage in ("INVALIDATED", "COMPLETED"):
        return None

    is_option = is_alert_option_premium_level(alert)

    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            if is_option:
                lookup_sym = alert.contract_symbol or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            else:
                lookup_sym = (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None

    if is_option:
        # Check if option buyer or option writer/seller:
        act = str((alert.actionable_plan or {}).get("action", "")).upper()
        is_option_sell = act in ("SELL", "WRITE", "SHORT")
        if not is_option_sell and alert.stop_loss and alert.target_level:
            ref_entry = alert.option_premium or alert.ltp
            if ref_entry and alert.stop_loss > ref_entry and alert.target_level < ref_entry:
                is_option_sell = True

        # For option buyers, payoff is upward (is_bullish = True, profit on premium expansion).
        # For option writers/sellers, payoff is downward (is_bullish = False, profit on premium decay).
        is_bullish = not is_option_sell

        # Canonical entry resolution for options:
        # 1. actionable_plan.recommended_entry (if provided, it is the calibrated trade entry)
        entry = None
        if alert.actionable_plan:
            rec_entry = alert.actionable_plan.get("recommended_entry", "")
            m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
            if m:
                try:
                    entry = float(m.group(0).replace(",", ""))
                except ValueError:
                    pass
            if not entry and alert.actionable_plan.get("entry_range"):
                matches = re.findall(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["entry_range"]))
                if len(matches) >= 2:
                    try:
                        entry = round(
                            (float(matches[0].replace(",", "")) + float(matches[1].replace(",", ""))) / 2.0,
                            2,
                        )
                    except ValueError:
                        pass
                elif len(matches) == 1:
                    try:
                        entry = float(matches[0].replace(",", ""))
                    except ValueError:
                        pass
        # 2. alert.option_premium (the canonical option contract premium)
        if not entry and alert.option_premium and alert.option_premium > 0:
            entry = alert.option_premium
        # 3. alert.ltp (only if realistic option premium, not underlying spot or strike)
        if not entry:
            if alert.ltp and alert.ltp > 0 and (not alert.strike or alert.ltp != alert.strike):
                entry = alert.ltp
            elif alert.stop_loss and alert.stop_loss > 0:
                entry = round(alert.stop_loss * 1.4, 2)
            else:
                entry = current_ltp
    else:
        entry = None
        if alert.actionable_plan:
            rec_entry = alert.actionable_plan.get("recommended_entry", "")
            m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
            if m:
                try:
                    entry = float(m.group(0).replace(",", ""))
                except ValueError:
                    pass
            if not entry and alert.actionable_plan.get("entry_range"):
                matches = re.findall(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["entry_range"]))
                if len(matches) >= 2:
                    try:
                        entry = round(
                            (float(matches[0].replace(",", "")) + float(matches[1].replace(",", ""))) / 2.0,
                            2,
                        )
                    except ValueError:
                        pass
                elif len(matches) == 1:
                    try:
                        entry = float(matches[0].replace(",", ""))
                    except ValueError:
                        pass
        if not entry and alert.trigger_level and alert.trigger_level > 0:
            entry = alert.trigger_level
        if not entry:
            entry = alert.ltp if alert.ltp > 0 else current_ltp
        is_bullish = alert.direction.upper() != "BEARISH"

    # Reference stop loss (actionable plan stop_loss takes precedence)
    stop = None
    if alert.actionable_plan and alert.actionable_plan.get("stop_loss"):
        m_sl = re.search(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["stop_loss"]))
        if m_sl:
            try:
                stop = float(m_sl.group(0).replace(",", ""))
            except ValueError:
                pass
    if not stop and alert.stop_loss and alert.stop_loss > 0:
        stop = alert.stop_loss
    if not stop:
        stop = round(entry * 0.98 if is_bullish else entry * 1.02, 2)

    initial_risk = max(0.01, abs(entry - stop))

    # PnL & R-multiple
    if is_bullish:
        pnl_pts = current_ltp - entry
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        r_multiple = pnl_pts / initial_risk
    else:
        pnl_pts = entry - current_ltp
        pnl_pct = (pnl_pts / entry) * 100 if entry > 0 else 0.0
        r_multiple = pnl_pts / initial_risk

    # Target levels resolution (Actionable plan targets take precedence)
    plan_t1 = None
    plan_t2 = None
    if alert.actionable_plan:
        if "target_1" in alert.actionable_plan:
            m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["target_1"]))
            if m_t1:
                plan_t1 = float(m_t1.group(0).replace(",", ""))
        elif "target" in alert.actionable_plan:
            m_t1 = re.search(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["target"]))
            if m_t1:
                plan_t1 = float(m_t1.group(0).replace(",", ""))

        if "target_2" in alert.actionable_plan:
            m_t2 = re.search(r"[\d,]+(?:\.\d+)?", str(alert.actionable_plan["target_2"]))
            if m_t2:
                plan_t2 = float(m_t2.group(0).replace(",", ""))

    target_final = (
        plan_t2
        or (alert.target_level if alert.target_level > 0 else None)
        or round(entry + (initial_risk * 3.0) if is_bullish else entry - (initial_risk * 3.0), 2)
    )

    if plan_t1:
        t1_level = plan_t1
    elif is_bullish:
        t1_level = round(entry + (initial_risk * 1.8), 2)
        if target_final > entry:
            t1_level = min(t1_level, round(entry + (target_final - entry) * 0.5, 2))
    else:
        t1_level = round(entry - (initial_risk * 1.8), 2)
        if target_final < entry:
            t1_level = max(t1_level, round(entry - (entry - target_final) * 0.5, 2))

    achieved = set(alert.achieved_milestones or [])

    # Volume / Momentum check for extension
    vol_ratio = current_volume_ratio or (
        alert.metrics.get("vol_oi_ratio", alert.metrics.get("rvol", 1.0)) if alert.metrics else 1.0
    )
    is_superperforming = (vol_ratio >= 2.0) or (alert.confidence >= 88 and r_multiple >= 2.5)

    # Hard Profitability Invariant: A target milestone (T1 or Final) CAN NEVER be reached
    # if the position is sitting at or below entry price (loss or breakeven).
    if is_bullish:
        if current_ltp <= entry or pnl_pts <= 0 or t1_level <= entry:
            is_final_hit = False
            is_t1_hit = False
        else:
            is_final_hit = (current_ltp >= target_final)
            is_t1_hit = (current_ltp >= t1_level)
    else:
        if current_ltp >= entry or pnl_pts <= 0 or t1_level >= entry:
            is_final_hit = False
            is_t1_hit = False
        else:
            is_final_hit = (current_ltp <= target_final)
            is_t1_hit = (current_ltp <= t1_level)
    if is_final_hit and "TARGET_ACHIEVED" not in achieved:
        if is_superperforming:
            # Superperforming momentum: do NOT exit all, trail runner with Chandelier ATR
            if is_bullish:
                rec_stop = max(t1_level, round(current_ltp - (initial_risk * 1.5), 2))
                locked_pts = rec_stop - entry
            else:
                rec_stop = min(t1_level, round(current_ltp + (initial_risk * 1.5), 2))
                locked_pts = entry - rec_stop

            locked_pct = round((locked_pts / entry) * 100, 2)
            rationale = (
                f"Primary target ₹{target_final:,.2f} reached (+{pnl_pct:.1f}%, +{r_multiple:.1f}R) with runaway volume ({vol_ratio:.1f}x). "
                f"DECISION: TRAIL STOP-LOSS TO ₹{rec_stop:,.2f} (Chandelier ATR Trail). "
                f"DO NOT FULLY EXIT RUNNER — Heavy institutional flow is extending breakout. Let runners ride!"
            )
            return TargetTrailingEvaluation(
                new_milestone="TARGET_ACHIEVED",
                target_status="TARGET_ACHIEVED",
                should_trail=True,
                trailing_decision="TRAIL_DYNAMIC_ATR",
                recommended_stop=rec_stop,
                trailing_rationale=rationale,
                locked_profit_pts=round(locked_pts, 2),
                locked_profit_pct=locked_pct,
                r_multiple=round(r_multiple, 2),
                pnl_pct=round(pnl_pct, 2),
                is_superperforming=True,
            )
        else:
            # Normal target hit: resistance reached, book full profit! Do not trail.
            rec_stop = current_ltp
            locked_pts = pnl_pts
            locked_pct = round(pnl_pct, 2)
            rationale = (
                f"Final target ₹{target_final:,.2f} reached (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
                f"DECISION: FULL PROFIT BOOKING RECOMMENDED. Close all open positions at market. "
                f"DO NOT TRAIL FURTHER — high probability of mean-reversion exhaustion at major resistance."
            )
            return TargetTrailingEvaluation(
                new_milestone="TARGET_ACHIEVED",
                target_status="TARGET_ACHIEVED",
                should_trail=False,
                trailing_decision="BOOK_FULL_PROFIT_NO_TRAIL",
                recommended_stop=rec_stop,
                trailing_rationale=rationale,
                locked_profit_pts=round(locked_pts, 2),
                locked_profit_pct=locked_pct,
                r_multiple=round(r_multiple, 2),
                pnl_pct=round(pnl_pct, 2),
                is_superperforming=False,
            )

    # 2. Target 1 (T1) Check
    is_t1_hit = (current_ltp >= t1_level) if is_bullish else (current_ltp <= t1_level)
    if is_t1_hit and "T1_ACHIEVED" not in achieved and "TARGET_ACHIEVED" not in achieved:
        # T1 reached -> Book 50% & Trail SL to Breakeven (+0.2% buffer)
        be_stop = round(entry * 1.002 if is_bullish else entry * 0.998, 2)
        rec_stop = be_stop
        locked_pts = abs(rec_stop - entry)
        locked_pct = 0.2
        rationale = (
            f"Target 1 reached at ₹{current_ltp:,.2f} (+{pnl_pct:.1f}%, +{r_multiple:.1f}R). "
            f"DECISION: BOOK 50% PARTIAL PROFIT NOW & TRAIL STOP-LOSS TO BREAKEVEN (₹{rec_stop:,.2f}). "
            f"Trade is now 100% risk-free. Hold remaining 50% runner for Target 2 (₹{target_final:,.2f})."
        )
        return TargetTrailingEvaluation(
            new_milestone="T1_ACHIEVED",
            target_status="T1_ACHIEVED",
            should_trail=True,
            trailing_decision="BOOK_50_TRAIL_BREAKEVEN",
            recommended_stop=rec_stop,
            trailing_rationale=rationale,
            locked_profit_pts=round(locked_pts, 2),
            locked_profit_pct=locked_pct,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=is_superperforming,
        )

    # 3. Trailing Stop Ratchet Higher (Dynamic Trail)
    if (
        alert.should_trail
        and alert.trailing_stop
        and alert.trailing_stop > 0
        and alert.stage != "COMPLETED"
    ):
        if is_bullish:
            higher_trail = round(max(alert.trailing_stop, current_ltp - (initial_risk * 1.8)), 2)
            min_dist = 0.5 if is_option else 2.0
            # Must ratchet higher by at least 0.75% and at least min_dist
            if (
                higher_trail >= round(alert.trailing_stop * 1.0075, 2)
                and (higher_trail - alert.trailing_stop) >= min_dist
            ):
                locked_pts = higher_trail - entry
                locked_pct = round((locked_pts / entry) * 100, 2)
                unit_str = "pts" if is_option else "/sh"
                rationale = (
                    f"Price expanded to ₹{current_ltp:,.2f}. "
                    f"DECISION: RATCHET TRAILING STOP HIGHER from ₹{alert.trailing_stop:,.2f} to ₹{higher_trail:,.2f}. "
                    f"Guaranteed locked profit increased to +₹{locked_pts:,.2f} {unit_str} (+{locked_pct:.1f}%)."
                )
                return TargetTrailingEvaluation(
                    new_milestone="TRAILING_UPDATE",
                    target_status=alert.target_status or "T1_ACHIEVED",
                    should_trail=True,
                    trailing_decision="TRAIL_DYNAMIC_ATR",
                    recommended_stop=higher_trail,
                    trailing_rationale=rationale,
                    locked_profit_pts=round(locked_pts, 2),
                    locked_profit_pct=locked_pct,
                    r_multiple=round(r_multiple, 2),
                    pnl_pct=round(pnl_pct, 2),
                    is_superperforming=is_superperforming,
                )
        else:
            lower_trail = round(min(alert.trailing_stop, current_ltp + (initial_risk * 1.8)), 2)
            if (
                lower_trail <= round(alert.trailing_stop * 0.9925, 2)
                and (alert.trailing_stop - lower_trail) >= 2.0
            ):
                locked_pts = entry - lower_trail
                locked_pct = round((locked_pts / entry) * 100, 2)
                rationale = (
                    f"Price dropped to ₹{current_ltp:,.2f}. "
                    f"DECISION: RATCHET TRAILING STOP LOWER from ₹{alert.trailing_stop:,.2f} to ₹{lower_trail:,.2f}. "
                    f"Guaranteed locked profit increased to +₹{locked_pts:,.2f}/sh (+{locked_pct:.1f}%)."
                )
                return TargetTrailingEvaluation(
                    new_milestone="TRAILING_UPDATE",
                    target_status=alert.target_status or "T1_ACHIEVED",
                    should_trail=True,
                    trailing_decision="TRAIL_DYNAMIC_ATR",
                    recommended_stop=lower_trail,
                    trailing_rationale=rationale,
                    locked_profit_pts=round(locked_pts, 2),
                    locked_profit_pct=locked_pct,
                    r_multiple=round(r_multiple, 2),
                    pnl_pct=round(pnl_pct, 2),
                    is_superperforming=is_superperforming,
                )

    # 4. Early Sub-Target Phase (< 1.5R)
    if r_multiple < 1.5:
        rationale = (
            f"Payoff is +{r_multiple:.1f}R (+{pnl_pct:.1f}%). "
            f"DECISION: DO NOT TRAIL YET. Maintain initial Stop Loss at ₹{stop:,.2f}. "
            f"Premature trailing in early stage causes whipsaws and unnecessary shakeouts."
        )
        return TargetTrailingEvaluation(
            new_milestone=None,
            target_status=alert.target_status or "PENDING",
            should_trail=False,
            trailing_decision="DO_NOT_TRAIL_HOLD_STOP",
            recommended_stop=stop,
            trailing_rationale=rationale,
            locked_profit_pts=0.0,
            locked_profit_pct=0.0,
            r_multiple=round(r_multiple, 2),
            pnl_pct=round(pnl_pct, 2),
            is_superperforming=False,
        )

    return None


# ── Detector 1: Gamma Blast (Early Warning & Ignited) ───────────────────────


def detect_gamma_blast(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Evaluates options chain for explosive Gamma Blast early-warning and ignite triggers.

    Leading Indicators:
      - Negative Change in OI (Call/Put writers closing positions in panic).
      - Volume / OI Ratio >= 1.8x (massive intraday turnover vs accumulated open interest).
      - Spot price reclaiming or breaking away from intraday VWAP.
      - ATM & near-OTM strike proximity (within ±1.5% of spot).
    """
    if not chain or spot <= 0:
        return []

    alerts: list[AutoAlert] = []
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Institutional Liquidity & Significance Filters (SEBI / F&O standard):
    # Prevents illiquid strikes with tiny volume from generating false percentage spikes.
    is_index = underlying.upper() in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    min_strike_oi = 15000 if is_index else 500
    min_abs_oi_change = 3000 if is_index else 150
    min_volume = 10000 if is_index else 500

    # Group contracts by strike and type
    ce_contracts = [c for c in chain if getattr(c, "option_type", "") == "CE"]
    pe_contracts = [c for c in chain if getattr(c, "option_type", "") == "PE"]

    # Effective VWAP proxy if not provided (assume spot is close to VWAP within 0.2%)
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Analyze CALL Gamma Blast (Bullish Upside Explosion) ───
    for c in ce_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        # Strict ATM to 0.8% OTM proximity (Gamma explosion requires near-the-money proximity)
        if not (-0.5 <= strike_diff_pct <= 0.8):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}CE")

        # Minimum Liquidity & Absolute Contract Shedding Gate:
        if oi < min_strike_oi or volume < min_volume or abs(oi_change) < min_abs_oi_change:
            continue

        exp_date = getattr(c, "expiry", "") or None
        # Gamma Physics Gate: Gamma explosion requires DTE <= 5 days for weekly indices or front-month (<= 35 days) for stocks
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = 5 if is_index else 35
                    if dte_days > max_gamma_dte:
                        continue
            except Exception:
                pass

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )

        # Writer panic criteria:
        is_oi_shedding = oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000)
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_above_vwap = spot >= (effective_vwap * 0.998)

        if is_oi_shedding and is_high_turnover and spot_above_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (
                day_high and spot >= day_high * 0.999
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            exp_type = classify_expiry_type(exp_date, underlying)

            # ── Dynamic Trade Plan: replace hardcoded 2.2x/0.65x with structural SMC levels ──
            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="BUY",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange="NFO",
                    has_active_blast=is_ignited,
                )

                # Expectancy & Asymmetry Gate: reject trades with unviable R:R geometry unless ignited
                if tp and not tp.is_asymmetry_viable and not is_ignited:
                    continue

                mkt_status = get_market_status("NFO")
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="CE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.8, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(1.0, opt_ltp * 0.7), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:2"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+90%"
                )
                sl_pct_str = (
                    f"{opt_plan['sl_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("sl_pct"))
                    else "-30%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast CE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.8, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
                )
                sl_premium = round(max(1.0, opt_ltp * 0.70), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:2"
                t1_pct_str = "+80%"
                sl_pct_str = "-30%"

            headline = (
                f"⚡ CALL GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} CE"
            )
            summary = (
                f"Call writers shedding {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} holding VWAP. "
                f"{'Explosive short-covering underway!' if is_ignited else 'Early-warning coiling before gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp
                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-ce-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BULLISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="CE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "strike": strike,
                        "option_type": "CE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:.1f} (Option Premium)"
                        if opt_ltp
                        else "Market",
                        "target": f"₹{target_premium:.1f} ({t1_pct_str})",
                        "stop_loss": f"₹{sl_premium:.1f} ({sl_pct_str})",
                        "risk_reward": rr_str,
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "market_status": mkt_status,
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    # ── Analyze PUT Gamma Blast (Bearish Downside Panic) ───────
    for c in pe_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        # Strict ATM to 0.8% OTM proximity (Gamma explosion requires near-the-money proximity)
        if not (-0.8 <= strike_diff_pct <= 0.5):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}PE")

        # Minimum Liquidity & Absolute Contract Shedding Gate:
        if oi < min_strike_oi or volume < min_volume or abs(oi_change) < min_abs_oi_change:
            continue

        exp_date = getattr(c, "expiry", "") or None
        # Gamma Physics Gate: Gamma explosion requires DTE <= 5 days for weekly indices or front-month (<= 35 days) for stocks
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = 5 if is_index else 35
                    if dte_days > max_gamma_dte:
                        continue
            except Exception:
                pass

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )

        is_oi_shedding = oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000)
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_below_vwap = spot <= (effective_vwap * 1.002)

        if is_oi_shedding and is_high_turnover and spot_below_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (
                day_low and spot <= day_low * 1.001
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            exp_type = classify_expiry_type(exp_date, underlying)

            # ── Dynamic Trade Plan: replace hardcoded 2.2x/0.65x with structural SMC levels ──
            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="SELL",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange="NFO",
                    has_active_blast=is_ignited,
                )

                # Expectancy & Asymmetry Gate: reject trades with unviable R:R geometry unless ignited
                if tp and not tp.is_asymmetry_viable and not is_ignited:
                    continue

                mkt_status = get_market_status("NFO")
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="PE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.8, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(1.0, opt_ltp * 0.7), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:2"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+90%"
                )
                sl_pct_str = (
                    f"{opt_plan['sl_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("sl_pct"))
                    else "-30%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast PE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.8, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
                )
                sl_premium = round(max(1.0, opt_ltp * 0.70), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:2"
                t1_pct_str = "+80%"
                sl_pct_str = "-30%"

            headline = (
                f"⚡ PUT GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} PE"
            )
            summary = (
                f"Put writers capitulating {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} below VWAP. "
                f"{'Aggressive long put / short spot momentum!' if is_ignited else 'Early-warning coiling before put gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp
                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-pe-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BEARISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="PE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "strike": strike,
                        "option_type": "PE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} ({t1_pct_str})",
                        "stop_loss": f"₹{sl_premium:.1f} ({sl_pct_str})",
                        "risk_reward": rr_str,
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "market_status": mkt_status,
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    return alerts


# ── Detector 2: Squeeze Breakout (Early Warning) ───────────────────────────


def detect_squeeze_breakout(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects Volatility Squeeze coiling within 0.4% - 1.2% of resistance / 20D High.
    Triggers *before* the breakout candle runs away.
    """
    if df is None or len(df) < 25 or ltp <= 0:
        return None

    try:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volume"].values if "volume" in df.columns else None

        # 20-period Bollinger Bands
        period = 20
        sma20 = float(pd.Series(closes).rolling(period).mean().iloc[-1])
        std20 = float(pd.Series(closes).rolling(period).std().iloc[-1])
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # 20-period ATR & Keltner Channels
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr20 = float(pd.Series(tr).rolling(period).mean().iloc[-1]) if tr else (std20 * 0.8)
        keltner_upper = sma20 + (1.5 * atr20)
        keltner_lower = sma20 - (1.5 * atr20)

        # Squeeze is ON when BB is inside Keltner Channel
        is_squeeze_on = (bb_upper < keltner_upper) and (bb_lower > keltner_lower)

        # 20-day High and Low / Pivot levels
        lookback = min(20, len(highs) - 1)
        pivot_high = float(np.max(highs[-lookback - 1 : -1]))
        dist_to_pivot_pct = ((pivot_high - ltp) / pivot_high) * 100.0

        pivot_low = float(np.min(lows[-lookback - 1 : -1]))
        dist_to_low_pct = ((ltp - pivot_low) / pivot_low) * 100.0

        # RVOL 20D
        rvol = 1.0
        if volumes is not None and len(volumes) >= 20:
            avg_vol = float(np.mean(volumes[-21:-1]))
            cur_vol = float(volumes[-1])
            rvol = round(cur_vol / max(1.0, avg_vol), 2)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # ── EARLY WARNING (BULLISH): Coiled in squeeze, 0.2% - 1.5% below pivot high ───
        if is_squeeze_on and (0.2 <= dist_to_pivot_pct <= 1.5):
            target = round(pivot_high * 1.06, 1)
            sl = round(sma20, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-early-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🎯 SQUEEZE COILING: {symbol} at ₹{ltp:,.1f} (Pivot ₹{pivot_high:,.1f})",
                summary=(
                    f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                    f"Price is only {dist_to_pivot_pct:.1f}% below pivot resistance. "
                    f"RVOL {rvol}x. Imminent explosive breakout setup!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_on": True,
                    "dist_to_pivot_pct": round(dist_to_pivot_pct, 2),
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "sma20": round(sma20, 1),
                    "atr20": round(atr20, 1),
                },
                actionable_plan={
                    "action": "BUY_ON_PIVOT",
                    "entry_range": f"₹{ltp:.1f} - ₹{pivot_high:.1f}",
                    "breakout_trigger": f"₹{pivot_high:.1f}",
                    "target": f"₹{target:.1f} (+6.0%)",
                    "stop_loss": f"₹{sl:.1f} (-{round(((ltp - sl) / ltp) * 100, 1)}%)",
                },
                confidence=84,
                created_at=now_iso,
            )

        # ── EARLY WARNING (BEARISH): Coiled in squeeze, 0.2% - 1.5% above pivot low support ───
        if is_squeeze_on and (0.2 <= dist_to_low_pct <= 1.5):
            target = round(pivot_low * 0.94, 1)
            sl = round(sma20, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-bear-early-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKDOWN",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BEARISH",
                headline=f"⚠️ SQUEEZE BREAKDOWN COILING: {symbol} at ₹{ltp:,.1f} (Support ₹{pivot_low:,.1f})",
                summary=(
                    f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                    f"Price is only {dist_to_low_pct:.1f}% above 20D low support. "
                    f"RVOL {rvol}x. Imminent downside breakdown risk!"
                ),
                ltp=ltp,
                trigger_level=pivot_low,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_on": True,
                    "dist_to_low_pct": round(dist_to_low_pct, 2),
                    "pivot_low": pivot_low,
                    "rvol": rvol,
                    "sma20": round(sma20, 1),
                    "atr20": round(atr20, 1),
                },
                actionable_plan={
                    "action": "SELL_ON_BREAKDOWN",
                    "entry_range": f"₹{pivot_low:.1f} - ₹{ltp:.1f}",
                    "breakout_trigger": f"₹{pivot_low:.1f}",
                    "target": f"₹{target:.1f} (-6.0%)",
                    "stop_loss": f"₹{sl:.1f} (+{round(((sl - ltp) / ltp) * 100, 1)}%)",
                },
                confidence=84,
                created_at=now_iso,
            )

        # ── IGNITED (BULLISH): Squeeze Fired + Fresh Breakout above pivot ───
        if (
            ltp >= pivot_high
            and (ltp - pivot_high) / pivot_high <= 0.025
            and rvol >= 1.4
            and ltp > sma20
        ):
            target = round(ltp * 1.08, 1)
            sl = round(pivot_high * 0.985, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-ignited-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="IGNITED",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🚀 SQUEEZE BREAKOUT IGNITED: {symbol} broke ₹{pivot_high:,.1f}",
                summary=(
                    f"TTM Squeeze fired with heavy institutional volume (RVOL {rvol}x). "
                    f"Price clearing 20-day high ₹{pivot_high:,.1f} (+{round(((ltp - pivot_high) / pivot_high) * 100, 1)}%). "
                    f"Primary breakout expansion phase active!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_fired": True,
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "breakout_pct": round(((ltp - pivot_high) / pivot_high) * 100, 2),
                },
                actionable_plan={
                    "action": "BUY_EXPANSION",
                    "entry_range": f"₹{ltp:.1f}",
                    "target": f"₹{target:.1f} (+8.0%)",
                    "stop_loss": f"₹{sl:.1f} (-1.5%)",
                },
                confidence=91,
                created_at=now_iso,
            )

        # ── IGNITED (BEARISH): Squeeze Fired + Fresh Breakdown below pivot low ───
        if (
            ltp <= pivot_low
            and (pivot_low - ltp) / pivot_low <= 0.025
            and rvol >= 1.4
            and ltp < sma20
        ):
            target = round(ltp * 0.92, 1)
            sl = round(pivot_low * 1.015, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-bear-ignited-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKDOWN",
                stage="IGNITED",
                symbol=symbol,
                exchange=exchange,
                direction="BEARISH",
                headline=f"⚡ SQUEEZE BREAKDOWN IGNITED: {symbol} broke below ₹{pivot_low:,.1f}",
                summary=(
                    f"TTM Squeeze breakdown fired with institutional volume (RVOL {rvol}x). "
                    f"Price cracked 20-day low ₹{pivot_low:,.1f} (-{round(((pivot_low - ltp) / pivot_low) * 100, 1)}%). "
                    f"Downside expansion phase active!"
                ),
                ltp=ltp,
                trigger_level=pivot_low,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_fired": True,
                    "pivot_low": pivot_low,
                    "rvol": rvol,
                    "breakdown_pct": round(((pivot_low - ltp) / pivot_low) * 100, 2),
                },
                actionable_plan={
                    "action": "SELL_EXPANSION",
                    "entry_range": f"₹{ltp:.1f}",
                    "target": f"₹{target:.1f} (-8.0%)",
                    "stop_loss": f"₹{sl:.1f} (+1.5%)",
                },
                confidence=91,
                created_at=now_iso,
            )

    except Exception as e:
        logger.debug(f"[SqueezeBreakout] Error evaluating {symbol}: {e}")

    return None


# ── Detector 3: Circuit Proximity Alert ─────────────────────────────────────


def detect_circuit_proximity(
    symbol: str,
    ltp: float,
    prev_close: float,
    high: Optional[float] = None,
    exchange: str = "NSE",
    circuit_band_pct: float = 5.0,
) -> Optional[AutoAlert]:
    """
    Early warning when stock is approaching Upper Circuit (<1.5% from ceiling).
    Enables user to place limit orders or enter before 100% buyers freeze liquidity.
    """
    if ltp <= 0 or prev_close <= 0:
        return None

    day_chg_pct = ((ltp - prev_close) / prev_close) * 100.0
    upper_circuit = round(prev_close * (1.0 + (circuit_band_pct / 100.0)), 2)
    dist_to_uc_pct = ((upper_circuit - ltp) / upper_circuit) * 100.0

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # If within 1.5% of upper circuit ceiling and gaining strongly
    if 0.1 <= dist_to_uc_pct <= 1.5 and day_chg_pct >= (circuit_band_pct * 0.7):
        return AutoAlert(
            alert_id=f"aa-cir-prox-{symbol}-{uuid.uuid4().hex[:6]}",
            alert_type="CIRCUIT_WARNING",
            stage="EARLY_WARNING",
            symbol=symbol,
            exchange=exchange,
            direction="BULLISH",
            headline=f"🔒 CIRCUIT WARNING: {symbol} at ₹{ltp:,.1f} ({dist_to_uc_pct:.1f}% below Upper Circuit)",
            summary=(
                f"Stock is surging (+{day_chg_pct:.1f}%) and trading {dist_to_uc_pct:.1f}% below "
                f"the ₹{upper_circuit:,.1f} circuit ceiling. Place limit orders before buyers freeze liquidity!"
            ),
            ltp=ltp,
            trigger_level=upper_circuit,
            target_level=upper_circuit,
            stop_loss=round(ltp * 0.97, 1),
            metrics={
                "prev_close": prev_close,
                "day_change_pct": round(day_chg_pct, 2),
                "upper_circuit": upper_circuit,
                "dist_to_uc_pct": round(dist_to_uc_pct, 2),
                "circuit_band_pct": circuit_band_pct,
            },
            actionable_plan={
                "action": "BUY_LIMIT_CIRCUIT",
                "price": f"₹{ltp:.1f}",
            },
            confidence=88,
            created_at=now_iso,
        )

    return None


# ── Detector 4: Learned Pattern Coiling (Early Warning) ───────────────────


def detect_learned_pattern_coiling(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects pre-blast coiling based on learned explosive move archetypes
    (Volume dry-up + Squeeze coiling + Order Block anchor).
    """
    if df is None or len(df) < 20 or ltp <= 0:
        return None

    try:
        from engine.learning_engine import pattern_learning_engine

        # Negative Feedback Invalidation Lockout Gate: Prevent knife-catching after stop-loss breach
        # Supports adaptive early unlocking if price structurally reclaims above failed level & VWAP
        is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
            symbol, direction="BULLISH", ltp=ltp
        )
        if is_locked:
            logger.info(
                f"[PatternCoiling] Gating alert for {symbol}: Under invalidation lockout ({lock_reason})"
            )
            return None

        res = pattern_learning_engine.evaluate_candidate(symbol=symbol, df=df, chain=None)
        if res.is_explosive_candidate:
            now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

            from engine.trade_plan import calculate_trade_plan

            tp = calculate_trade_plan(symbol, direction="BULLISH", spot=ltp, exchange=exchange)

            # Mathematical Expectancy Gate: Reject candidates with poor structural asymmetry
            if tp and not tp.is_asymmetry_viable:
                logger.info(
                    f"[PatternCoiling] Gating alert for {symbol}: Failed structural asymmetry ({tp.asymmetry_verdict})"
                )
                return None

            archetype_txt = (
                f" ({res.similarity_score}% match to {res.closest_archetype})"
                if res.closest_archetype
                else ""
            )
            headline = f"💎 PRE-BLAST COILING: {symbol} at ₹{ltp:,.1f}{archetype_txt}"
            factor_summary = (
                "; ".join(res.matched_factors[:2])
                if res.matched_factors
                else "High-conviction coiling"
            )
            summary = f"Pre-blast footprint match: {factor_summary}. Asymmetric coiling detected with minimum risk anchor."

            t1 = tp.target_1 if (tp and tp.target_1 > 0) else round(ltp * 1.05, 1)
            sl = (
                tp.invalidation_stop if (tp and tp.invalidation_stop > 0) else round(ltp * 0.985, 1)
            )

            # Volatility Noise Floor: Ensure stop-loss is not placed within intraday noise chop
            # Minimum buffer: at least 1.2% of price or 1.2x ATR
            min_sl_dist = round(max(ltp * 0.012, 1.0), 2)
            if (ltp - sl) < min_sl_dist:
                sl = round(ltp - min_sl_dist, 2)

            rr_str = f"{tp.rr_t1:.1f}:1" if tp else "3.0:1"

            act_plan = {
                "action": res.recommended_entry_action,
                "entry_range": f"₹{ltp:.1f}",
                "target": f"₹{t1:.1f}",
                "stop_loss": f"₹{sl:.1f}",
                "risk_reward": rr_str,
            }
            if tp:
                act_plan["trade_plan"] = tp.as_dict()

            return AutoAlert(
                alert_id=f"aa-coiling-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="PATTERN_COILING",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1,
                stop_loss=sl,
                metrics={
                    "similarity_score": res.similarity_score,
                    "closest_archetype": res.closest_archetype,
                    "matched_factors": res.matched_factors,
                    "expected_rr": res.expected_asymmetry_rr,
                },
                actionable_plan=act_plan,
                confidence=res.similarity_score,
                created_at=now_iso,
            )
    except Exception as e:
        logger.debug(f"[PatternCoiling] Error evaluating {symbol}: {e}")

    return None


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

            tg_msg = render_auto_alert(alert, in_market=in_market)
            target_seg = getattr(alert, "segment", None)
            if not target_seg:
                from engine.alert_preferences import classify_alert_segment
                target_seg = classify_alert_segment(alert)
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
                    headline = f"⚡ [REAL/LIVE] PRECURSOR RADAR {seg_tag}: {c.symbol} Coiling at ₹{c.ltp:,.1f} ({c.conviction_score}/100)"
                    summary = f"{seg_tag} Pre-ignition coiling: {'; '.join(c.matched_factors[:2])}. Entry: {c.entry_range}."
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
                        is_live=True,
                        environment="LIVE",
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
                headline = f"🚀 [REAL/LIVE] INTRADAY SPARK {seg_tag}: {clean_sym} +{chg:.1f}% with {rvol:.1f}x Volume Surge"
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
                headline = f"⚡ [REAL/LIVE] INTRADAY BREAKDOWN {seg_tag}: {clean_sym} {chg:.1f}% with {rvol:.1f}x Volume Surge"
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
                is_live=True,
                environment="LIVE",
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
                    if oi_change and oi_change < 0:
                        conf_score += 5
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
                        headline = f"🎯 [REAL/LIVE] OPTIONS MOMENTUM (PUT SURGE): {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
                        summary = (
                            f"Institutional Put surge in {clean_sym} {strike:,.0f} PE. "
                            f"Underlying spot ₹{spot:,.1f}{spot_anchor_str}. Turnover: {vol:,} contracts ({vol_oi}x OI). "
                            f"Entry: ₹{opt_ltp:,.1f} | SL: ₹{opt_sl:,.1f} | T1: ₹{opt_t1:,.1f} | T2: ₹{opt_t2:,.1f}.{friday_tag}"
                        )
                    else:
                        headline = f"🚀 [REAL/LIVE] OPTIONS MOMENTUM: {contract_sym} @ ₹{opt_ltp:,.1f} (Vol/OI {vol_oi}x)"
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
                        option_premium=opt_ltp,
                        underlying_spot=spot,
                        confidence=confidence,
                        created_at=now_iso,
                        is_live=True,
                        environment="LIVE",
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

            # Minimum move threshold for commodity trigger (0.6% for Gold/Silver/Copper, 1.0% for Crude/NatGas)
            min_chg = 1.0 if clean_sym in ("CRUDEOIL", "NATURALGAS") else 0.6

            is_bullish = (chg >= min_chg) and (ltp >= (vwap * 0.998))
            is_bearish = (chg <= -min_chg) and (ltp <= (vwap * 1.002))

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
                if has_real_vwap:
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
                if has_real_vwap:
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
                headline = f"💱 [REAL/LIVE] CURRENCY BREAKOUT: {clean_sym} +{chg:.2f}% @ ₹{ltp:.4f}"
                summary = f"Macro currency surge in {clean_sym}: Moving +{chg:.2f}% to ₹{ltp:.4f}. Long thesis active."
                action = "BUY_FUTURES"
            else:
                sl_price = round(ltp + risk_rupees, 4)
                t1_price = round(ltp - 1.8 * risk_rupees, 4)
                t2_price = round(ltp - 3.0 * risk_rupees, 4)
                headline = f"💱 [REAL/LIVE] CURRENCY BREAKDOWN: {clean_sym} {chg:.2f}% @ ₹{ltp:.4f}"
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
        # 2. Check target milestones & trailing stop updates on existing alerts
        self.check_and_alert_targets_and_trailing(exchanges=active_exchanges or None)
        # 3. Check for fresh market signals
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
                    self.check_and_alert_targets_and_trailing(exchanges=["NSE", "BSE", "NFO"])
                    self.scan_equity_nfo_now()

                # Phase 2: Currency Desk (15:30 - 17:00 IST strictly post-equity)
                if session["currency"] and not alert_preferences.is_segment_globally_disabled("CURRENCY"):
                    self.check_and_alert_invalidations(exchanges=["CDS"])
                    self.check_and_alert_targets_and_trailing(exchanges=["CDS"])
                    self.scan_currency_now()

                # Phase 3: MCX Commodities Desk (15:30 - 23:30 IST strictly post-equity)
                if session["commodity"] and not alert_preferences.is_segment_globally_disabled("COMMODITY"):
                    self.check_and_alert_invalidations(exchanges=["MCX"])
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
            data = [a.to_dict() for a in self._alerts]
            target_path.write_text(json.dumps(data, indent=2))
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
                data = json.loads(target_path.read_text())
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
