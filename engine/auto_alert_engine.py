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
import math
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
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


@dataclass
class AutoAlert:
    alert_id: str
    alert_type: str  # GAMMA_BLAST | SQUEEZE_BREAKOUT | CIRCUIT_WARNING | SMC_SWEEP | CONFLUENCE_INFLECTION
    stage: str  # "EARLY_WARNING" | "IGNITED" | "INVALIDATED"
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
    trailing_decision: Optional[str] = None  # "BOOK_50_TRAIL_BREAKEVEN" | "TRAIL_DYNAMIC_ATR" | "BOOK_FULL_PROFIT_NO_TRAIL" | "DO_NOT_TRAIL_HOLD_STOP"
    trailing_stop: Optional[float] = None  # Exact rupee level recommended for trailing stop-loss
    trailing_rationale: Optional[str] = None  # Institutional rationale explaining trailing decision
    locked_profit_pts: Optional[float] = None
    locked_profit_pct: Optional[float] = None
    last_trail_alert_time: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.invalidated_at or self.created_at or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        return d


# ── Invalidation Evaluator ──────────────────────────────────────────────────


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

    # Determine current LTP if not provided
    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            lookup_sym = alert.contract_symbol or (
                f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
            )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None  # Cannot evaluate without live price quote

    # 1. Stop-Loss Invalidation
    if alert.stop_loss and alert.stop_loss > 0:
        if alert.direction == "BULLISH" and current_ltp < alert.stop_loss:
            if alert.option_type:
                return (
                    f"Option premium collapsed to ₹{current_ltp:.1f} "
                    f"(breached stop-loss ₹{alert.stop_loss:.1f}). Call gamma thesis invalidated."
                )
            return (
                f"Price dropped to ₹{current_ltp:,.1f} "
                f"(breached stop-loss ₹{alert.stop_loss:,.1f}). Bullish thesis invalidated."
            )
        elif alert.direction == "BEARISH" and current_ltp > alert.stop_loss:
            if alert.option_type:
                return (
                    f"Option premium collapsed to ₹{current_ltp:.1f} "
                    f"(breached stop-loss ₹{alert.stop_loss:.1f}). Put gamma thesis invalidated."
                )
            return (
                f"Price surged to ₹{current_ltp:,.1f} "
                f"(breached stop-loss ₹{alert.stop_loss:,.1f}). Bearish thesis invalidated."
            )

    # 2. Detector-Specific Structural Breakdown
    if alert.alert_type == "SQUEEZE_BREAKOUT":
        if alert.trigger_level > 0 and current_ltp < (alert.trigger_level * 0.965):
            retreat_pct = round(((alert.trigger_level - current_ltp) / alert.trigger_level) * 100, 1)
            return (
                f"Price retreated {retreat_pct}% below breakout pivot ₹{alert.trigger_level:,.1f} "
                f"(LTP ₹{current_ltp:,.1f}). Squeeze compression lost momentum."
            )
        sma20 = alert.metrics.get("sma20") if alert.metrics else None
        if sma20 and current_ltp < sma20:
            return f"Price broke down below 20-SMA base support ₹{sma20:,.1f} (LTP ₹{current_ltp:,.1f}). Squeeze invalidated."

    elif alert.alert_type == "CIRCUIT_WARNING":
        upper_circuit = alert.trigger_level or (alert.metrics.get("upper_circuit", 0.0) if alert.metrics else 0.0)
        if upper_circuit > 0:
            dist_to_uc = ((upper_circuit - current_ltp) / upper_circuit) * 100.0
            if dist_to_uc > 3.0:
                return (
                    f"Price backed off {dist_to_uc:.1f}% from upper circuit ceiling ₹{upper_circuit:,.1f} "
                    f"(LTP ₹{current_ltp:,.1f}). Circuit lock threat subsided."
                )

    elif alert.alert_type == "GAMMA_BLAST":
        if current_vwap and current_vwap > 0:
            if alert.direction == "BULLISH" and current_ltp < (current_vwap * 0.992):
                return f"Underlying broke below intraday VWAP ₹{current_vwap:,.1f}. Long gamma setup invalidated."
            elif alert.direction == "BEARISH" and current_ltp > (current_vwap * 1.008):
                return f"Underlying reclaimed above intraday VWAP ₹{current_vwap:,.1f}. Short gamma setup invalidated."

    return None


# ── Target Progression & Decisive Trailing Evaluator ────────────────────────


@dataclass
class TargetTrailingEvaluation:
    new_milestone: Optional[str] = None  # "T1_ACHIEVED" | "TARGET_ACHIEVED" | "TRAILING_UPDATE" | None
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

    if current_ltp is None or current_ltp <= 0:
        try:
            from market.quotes import get_ltp

            lookup_sym = alert.contract_symbol or (
                f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
            )
            current_ltp = get_ltp(lookup_sym)
        except Exception:
            current_ltp = None

    if current_ltp is None or current_ltp <= 0:
        return None

    entry = alert.trigger_level if alert.trigger_level > 0 else alert.ltp
    if entry <= 0:
        entry = current_ltp

    is_bullish = alert.direction.upper() != "BEARISH"

    # Reference stop loss
    if alert.stop_loss and alert.stop_loss > 0:
        stop = alert.stop_loss
    else:
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

    # Target levels
    target_final = alert.target_level if alert.target_level > 0 else (
        round(entry + (initial_risk * 3.0) if is_bullish else entry - (initial_risk * 3.0), 2)
    )

    # Target 1 (T1) calculation: 1.8R milestone or midpoint towards target
    if is_bullish:
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

    # 1. Final Target Check
    is_final_hit = (current_ltp >= target_final) if is_bullish else (current_ltp <= target_final)
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
    if alert.should_trail and alert.trailing_stop and alert.trailing_stop > 0 and alert.stage != "COMPLETED":
        if is_bullish:
            higher_trail = round(max(alert.trailing_stop, current_ltp - (initial_risk * 1.8)), 2)
            # Must ratchet higher by at least 0.75% and at least 2 pts
            if higher_trail >= round(alert.trailing_stop * 1.0075, 2) and (higher_trail - alert.trailing_stop) >= 2.0:
                locked_pts = higher_trail - entry
                locked_pct = round((locked_pts / entry) * 100, 2)
                rationale = (
                    f"Price expanded to ₹{current_ltp:,.2f}. "
                    f"DECISION: RATCHET TRAILING STOP HIGHER from ₹{alert.trailing_stop:,.2f} to ₹{higher_trail:,.2f}. "
                    f"Guaranteed locked profit increased to +₹{locked_pts:,.2f}/sh (+{locked_pct:.1f}%)."
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
            if lower_trail <= round(alert.trailing_stop * 0.9925, 2) and (alert.trailing_stop - lower_trail) >= 2.0:
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

    # Group contracts by strike and type
    ce_contracts = [c for c in chain if getattr(c, "option_type", "") == "CE"]
    pe_contracts = [c for c in chain if getattr(c, "option_type", "") == "PE"]

    # Effective VWAP proxy if not provided (assume spot is close to VWAP within 0.2%)
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Analyze CALL Gamma Blast (Bullish Upside Explosion) ───
    for c in ce_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-0.6 <= strike_diff_pct <= 1.6):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}CE")

        if oi <= 0 or volume <= 0:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0

        # Writer panic criteria:
        is_oi_shedding = (oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000))
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_above_vwap = spot >= (effective_vwap * 0.998)

        if is_oi_shedding and is_high_turnover and spot_above_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (day_high and spot >= day_high * 0.999)
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            target_premium = round(opt_ltp * 2.2, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
            sl_premium = round(max(1.0, opt_ltp * 0.65), 1) if opt_ltp > 0 else 1.0

            headline = (
                f"⚡ CALL GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} CE"
            )
            summary = (
                f"Call writers shedding {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} holding VWAP. "
                f"{'Explosive short-covering underway!' if is_ignited else 'Early-warning coiling before gamma surge!'}"
            )

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
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(((spot - effective_vwap) / effective_vwap) * 100, 2),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} (+120%)",
                        "stop_loss": f"₹{sl_premium:.1f} (-35%)",
                        "risk_reward": "1:3.4",
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    # ── Analyze PUT Gamma Blast (Bearish Downside Panic) ───────
    for c in pe_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-1.6 <= strike_diff_pct <= 0.6):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}PE")

        if oi <= 0 or volume <= 0:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0

        is_oi_shedding = (oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000))
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_below_vwap = spot <= (effective_vwap * 1.002)

        if is_oi_shedding and is_high_turnover and spot_below_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (day_low and spot <= day_low * 1.001)
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            target_premium = round(opt_ltp * 2.2, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
            sl_premium = round(max(1.0, opt_ltp * 0.65), 1) if opt_ltp > 0 else 1.0

            headline = (
                f"⚡ PUT GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} PE"
            )
            summary = (
                f"Put writers capitulating {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} below VWAP. "
                f"{'Aggressive long put / short spot momentum!' if is_ignited else 'Early-warning coiling before put gamma surge!'}"
            )

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
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(((spot - effective_vwap) / effective_vwap) * 100, 2),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} (+120%)",
                        "stop_loss": f"₹{sl_premium:.1f} (-35%)",
                        "risk_reward": "1:3.4",
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

        # 20-day High / Pivot level
        lookback = min(20, len(highs) - 1)
        pivot_high = float(np.max(highs[-lookback - 1 : -1]))
        dist_to_pivot_pct = ((pivot_high - ltp) / pivot_high) * 100.0

        # RVOL 20D
        rvol = 1.0
        if volumes is not None and len(volumes) >= 20:
            avg_vol = float(np.mean(volumes[-21:-1]))
            cur_vol = float(volumes[-1])
            rvol = round(cur_vol / max(1.0, avg_vol), 2)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # ── EARLY WARNING: Coiled in squeeze, 0.2% - 1.5% from pivot ───
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
                    "stop_loss": f"₹{sl:.1f} (-{round(((ltp - sl)/ltp)*100, 1)}%)",
                },
                confidence=84,
                created_at=now_iso,
            )

        # ── IGNITED: Squeeze Fired + Fresh Breakout above pivot ───
        if ltp >= pivot_high and (ltp - pivot_high) / pivot_high <= 0.025 and rvol >= 1.4 and ltp > sma20:
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
                    f"Price clearing 20-day high ₹{pivot_high:,.1f} (+{round(((ltp-pivot_high)/pivot_high)*100, 1)}%). "
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
                "ceiling": f"₹{upper_circuit:.1f}",
                "note": "Market buy orders will be rejected if locked; use Limit IOC/DAY orders.",
            },
            confidence=88,
            created_at=now_iso,
        )

    return None


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
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
            "MARUTI", "SBIN", "BHARTIARTL", "LT", "ITC",
        ]
        self._load()

    # ── Dispatch and Record ─────────────────────────────────────

    def record_alert(self, alert: AutoAlert) -> bool:
        """
        Records alert if not within cooldown window. Dispatches to SSE and multi-channels.
        Strictly prevents duplicate active alerts for the same symbol & alert_type.
        """
        now = time.time()
        to_dispatch = None

        with self._lock:
            # 1. Active Alert Uniqueness Guard:
            # Check for existing active (in-flight) alert on the same symbol and strategy
            existing_active = next(
                (
                    a for a in self._alerts
                    if a.symbol == alert.symbol
                    and a.alert_type == alert.alert_type
                    and not a.is_invalidated
                    and a.stage not in ("INVALIDATED", "COMPLETED")
                ),
                None,
            )
            if existing_active:
                # If existing is EARLY_WARNING and incoming is IGNITED, upgrade it!
                if existing_active.stage == "EARLY_WARNING" and alert.stage == "IGNITED":
                    existing_active.stage = "IGNITED"
                    existing_active.headline = alert.headline
                    existing_active.summary = alert.summary
                    existing_active.ltp = alert.ltp
                    existing_active.trigger_level = alert.trigger_level
                    existing_active.target_level = alert.target_level
                    existing_active.stop_loss = alert.stop_loss
                    existing_active.metrics = alert.metrics
                    existing_active.actionable_plan = alert.actionable_plan
                    existing_active.confidence = max(existing_active.confidence, alert.confidence)
                    self._save()
                    to_dispatch = existing_active
                else:
                    # Existing alert is already active/ignited/tracking targets -> suppress duplicate insertion!
                    return False
            else:
                # 2. Signature-based cooldown check (removed volatile price noise from signature)
                sig = f"{alert.symbol}:{alert.alert_type}:{alert.direction}:{alert.stage}"
                last_time = self._cooldowns.get(sig, 0.0)
                if (now - last_time) < self._cooldown_ttl:
                    return False  # Cooldown active, suppress repetitive spam

                self._cooldowns[sig] = now
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

    def _dispatch(self, alert: AutoAlert) -> None:
        """Broadcasts alert across all communication channels with clear REAL/LIVE vs TEST tagging."""
        is_test = (alert.environment == "TEST") or (not alert.is_live)
        env_tag = "[TEST]" if is_test else "[REAL/LIVE]"
        is_t1 = "T1" in (alert.target_status or "") or alert.stage == "T1_ACHIEVED"
        is_target = is_t1 or alert.stage in ("TARGET_ACHIEVED", "COMPLETED") or "TARGET" in (alert.target_status or "")
        is_trail = alert.stage == "TRAILING_UPDATE"

        alert_dict = alert.to_dict()
        alert_dict["env_tag"] = env_tag
        alert_dict["is_live"] = not is_test
        alert_dict["environment"] = "TEST" if is_test else "LIVE"
        alert_dict["is_target"] = is_target
        alert_dict["is_trail"] = is_trail

        now_ts_str = alert.invalidated_at or alert.created_at or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
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
            event_bus.publish_sync("system", {
                "type": sys_type,
                "alert": alert_dict,
                "is_invalidated": alert.is_invalidated,
                "is_target": is_target,
                "is_trail": is_trail,
                "environment": alert.environment,
            })
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] SSE publish error: {e}")

        # 2. Desktop notification
        try:
            from engine.alerts import _desktop_notify

            ts_short = now_ts_str.split(" ")[-2] if " " in now_ts_str else now_ts_str
            if alert.is_invalidated:
                desktop_title = f"⚠️ {env_tag} [{ts_short}] VIEW INVALIDATED: {alert.symbol}"
                desktop_msg = alert.invalidation_reason or alert.summary
            elif is_t1:
                desktop_title = f"🎯 {env_tag} [{ts_short}] TARGET 1 HIT: {alert.symbol}"
                desktop_msg = f"{alert.trailing_decision or 'BOOK 50% & TRAIL TO BREAKEVEN'}: {alert.trailing_rationale or alert.summary}"
            elif is_target:
                desktop_title = f"🏁 {env_tag} [{ts_short}] FINAL TARGET HIT: {alert.symbol}"
                desktop_msg = f"{alert.trailing_decision or 'TARGET ACHIEVED'}: {alert.trailing_rationale or alert.summary}"
            elif is_trail:
                desktop_title = f"📈 {env_tag} [{ts_short}] TRAIL STOP: {alert.symbol} → ₹{alert.trailing_stop or 0:,.2f}"
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
                    m_key = f"{alert.symbol}:{alert.alert_type}:TRAIL"
                    last_t = self._dispatch_cooldowns.get(m_key, 0.0)
                    if (now_ts - last_t) < 900.0:  # 15 min cooldown
                        return
                    self._dispatch_cooldowns[m_key] = now_ts

                elif alert.stage == "EARLY_WARNING":
                    # Early warnings are preliminary coiling signals -> keep in SSE / Terminal,
                    # do not buzz Telegram unless exceptionally high confidence (>= 90)
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

            if alert.is_invalidated:
                tg_msg = (
                    f"⚠️ <b>{env_tag} VIEW INVALIDATED</b>\n\n"
                    f"🚨 <b>{alert.symbol} ({alert.alert_type.replace('_', ' ')})</b> is <b>NO LONGER VALID</b>!\n\n"
                    f"🛑 <b>Reason:</b> {alert.invalidation_reason or alert.summary}\n"
                    f"🕒 <b>Invalidated At:</b> {alert.invalidated_at or alert.created_at}\n\n"
                    f"⚡ <b>DECISIVE ACTION:</b> <code>CANCEL PENDING ORDERS & CLOSE POSITIONS</code>"
                )
            elif is_t1:
                tg_header = "🎯 <b>[TEST TARGET 1 HIT]</b>" if is_test else "🎯 <b>[REAL / LIVE TARGET 1 HIT]</b>"
                trail_stop_val = alert.trailing_stop or alert.stop_loss or (alert.trigger_level * 1.002)
                tg_msg = (
                    f"{tg_header}\n\n"
                    f"🏆 <b>{alert.symbol} ({alert.alert_type.replace('_', ' ')}) — TARGET 1 ACHIEVED</b>\n\n"
                    f"💰 <b>LTP:</b> ₹{alert.ltp:,.2f} | <b>Target 1:</b> ₹{alert.target_level:,.2f}\n"
                    f"🛡️ <b>Trail Stop:</b> ₹{trail_stop_val:,.2f} (+{alert.locked_profit_pct or 0.2:.1f}% Breakeven Lock)\n"
                    f"⚡ <b>DECISIVE ACTION:</b> <code>BOOK 50% PROFIT NOW & HOLD RUNNER</code>\n\n"
                    f"💡 <b>Institutional Guidance:</b> {alert.trailing_rationale or alert.summary}\n\n"
                    f"🕒 <b>Timestamp:</b> {now_ts_str}"
                )
            elif is_target:
                if alert.should_trail:
                    tg_header = "🚀 <b>[TEST RUNNER EXTENSION]</b>" if is_test else "🚀 <b>[REAL / LIVE RUNNER EXTENSION]</b>"
                    tg_msg = (
                        f"{tg_header}\n\n"
                        f"🏆 <b>{alert.symbol} ({alert.alert_type.replace('_', ' ')}) — INSTITUTIONAL RUNAWAY</b>\n\n"
                        f"💰 <b>LTP:</b> ₹{alert.ltp:,.2f} | <b>Primary Target:</b> ₹{alert.target_level:,.2f}\n"
                        f"🛡️ <b>Chandelier Trail SL:</b> ₹{alert.trailing_stop:,.2f} (+{alert.locked_profit_pct or 0:.1f}% locked)\n"
                        f"⚡ <b>DECISIVE ACTION:</b> <code>LET RUNNER RIDE (TRAIL SL)</code>\n\n"
                        f"💡 <b>Institutional Guidance:</b> {alert.trailing_rationale or alert.summary}\n\n"
                        f"🕒 <b>Timestamp:</b> {now_ts_str}"
                    )
                else:
                    tg_header = "🏁 <b>[TEST FINAL TARGET ACHIEVED]</b>" if is_test else "🏁 <b>[REAL / LIVE FINAL TARGET ACHIEVED]</b>"
                    tg_msg = (
                        f"{tg_header}\n\n"
                        f"🏆 <b>{alert.symbol} ({alert.alert_type.replace('_', ' ')}) — FINAL TARGET REACHED</b>\n\n"
                        f"💰 <b>LTP:</b> ₹{alert.ltp:,.2f} | <b>Final Target:</b> ₹{alert.target_level:,.2f}\n"
                        f"⚡ <b>DECISIVE ACTION:</b> <code>CLOSE ALL POSITIONS (BOOK FULL PROFIT)</code>\n\n"
                        f"💡 <b>Institutional Guidance:</b> {alert.trailing_rationale or alert.summary}\n\n"
                        f"🕒 <b>Timestamp:</b> {now_ts_str}"
                    )
            elif is_trail:
                tg_header = "📈 <b>[TEST TRAILING STOP RATCHET]</b>" if is_test else "📈 <b>[REAL / LIVE TRAILING STOP RATCHET]</b>"
                tg_msg = (
                    f"{tg_header}\n\n"
                    f"🛡️ <b>{alert.symbol} Trailing Stop Ratcheted Higher!</b>\n\n"
                    f"💰 <b>LTP:</b> ₹{alert.ltp:,.2f}\n"
                    f"🛡️ <b>New Stop-Loss:</b> ₹{alert.trailing_stop:,.2f}\n"
                    f"🔒 <b>Guaranteed Profit:</b> +₹{alert.locked_profit_pts or 0:,.2f}/sh (+{alert.locked_profit_pct or 0:.1f}% locked)\n"
                    f"⚡ <b>DECISIVE ACTION:</b> <code>UPDATE SL ORDER TO ₹{alert.trailing_stop:,.2f}</code>\n\n"
                    f"💡 <i>{alert.trailing_rationale or alert.summary}</i>\n\n"
                    f"🕒 <b>Timestamp:</b> {now_ts_str}"
                )
            else:
                plan_str = ""
                if alert.actionable_plan:
                    action = alert.actionable_plan.get("action", "")
                    entry = alert.actionable_plan.get("recommended_entry") or alert.actionable_plan.get("entry_range", "")
                    target = alert.actionable_plan.get("target", f"₹{alert.target_level}")
                    sl = alert.actionable_plan.get("stop_loss", f"₹{alert.stop_loss}")
                    plan_str = f"\n\n⚡ <b>Trade Plan:</b> {action} @ {entry}\n🎯 <b>Target:</b> {target} | 🛑 <b>SL:</b> {sl}"

                tg_header = "🧪 <b>[TEST BREAKOUT IGNITED]</b>" if is_test else "🟢 <b>[REAL / LIVE BREAKOUT IGNITED]</b>"
                tg_msg = (
                    f"{tg_header}\n"
                    f"🚨 <b>{alert.headline}</b>\n\n"
                    f"{alert.summary}"
                    f"{plan_str}\n\n"
                    f"📊 <b>Confidence:</b> {alert.confidence}% | 🕒 <b>Timestamp:</b> {now_ts_str}"
                )
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

    def check_and_alert_invalidations(self) -> list[AutoAlert]:
        """
        Scans all active (non-invalidated) alerts to check if their trade thesis
        or levels have been invalidated by recent market price action.
        Dispatches high-priority Invalidation Alerts across all channels.
        """
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        invalidated_alerts: list[AutoAlert] = []

        with self._lock:
            active_alerts = [a for a in self._alerts if not a.is_invalidated and a.stage != "INVALIDATED"]

        for alert in active_alerts:
            reason = evaluate_alert_invalidation(alert)
            if reason:
                with self._lock:
                    alert.is_invalidated = True
                    alert.invalidation_reason = reason
                    alert.invalidated_at = now_iso
                    alert.stage = "INVALIDATED"
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

    def invalidate_alert_by_id(self, alert_id: str, reason: str = "Manually invalidated by user") -> Optional[AutoAlert]:
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

    def check_and_alert_targets_and_trailing(self) -> list[AutoAlert]:
        """
        Scans all active (non-invalidated, non-completed) alerts against live quotes to evaluate:
          1. Target milestones (Target 1 / Breakeven vs Final Target).
          2. Trailing stop ratchets.
        Dispatches high-priority target & trailing alerts with strict deduplication.
        """
        updated_alerts: list[AutoAlert] = []
        now_ts = time.time()

        with self._lock:
            active_alerts = [
                a for a in self._alerts
                if not a.is_invalidated and a.stage not in ("INVALIDATED", "COMPLETED")
            ]

        for alert in active_alerts:
            try:
                # Refresh current quote LTP
                lookup_sym = alert.contract_symbol or (
                    f"{alert.exchange}:{alert.symbol}" if ":" not in alert.symbol else alert.symbol
                )
                from market.quotes import get_ltp
                try:
                    cur_quote_ltp = get_ltp(lookup_sym)
                    if cur_quote_ltp and cur_quote_ltp > 0:
                        alert.ltp = cur_quote_ltp
                except Exception:
                    cur_quote_ltp = None

                eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=cur_quote_ltp)
                if not eval_res or not eval_res.new_milestone:
                    continue

                # Cooldown check for trailing updates (suppress repeat within 5 minutes)
                if eval_res.new_milestone == "TRAILING_UPDATE":
                    last_alert_time = alert.last_trail_alert_time or 0.0
                    if (now_ts - last_alert_time) < 300.0:
                        continue  # Cooldown active

                with self._lock:
                    alert.should_trail = eval_res.should_trail
                    alert.trailing_decision = eval_res.trailing_decision
                    alert.trailing_stop = eval_res.recommended_stop
                    alert.trailing_rationale = eval_res.trailing_rationale
                    alert.locked_profit_pts = eval_res.locked_profit_pts
                    alert.locked_profit_pct = eval_res.locked_profit_pct
                    alert.target_status = eval_res.target_status

                    env_tag = "[TEST]" if (alert.environment == "TEST" or not alert.is_live) else "[REAL/LIVE]"

                    if eval_res.new_milestone in ("T1_ACHIEVED", "TARGET_ACHIEVED"):
                        if eval_res.new_milestone not in alert.achieved_milestones:
                            alert.achieved_milestones.append(eval_res.new_milestone)

                        if eval_res.new_milestone == "TARGET_ACHIEVED":
                            if not eval_res.should_trail:
                                alert.stage = "COMPLETED"
                                alert.headline = f"🏁 {env_tag} FINAL TARGET ACHIEVED: {alert.symbol} (₹{eval_res.recommended_stop:,.2f})"
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
                logger.info(f"[AutoAlertEngine] Alert {alert.alert_id} milestone {eval_res.new_milestone}: {eval_res.trailing_decision}")

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
                    f"Final target reached at major resistance. "
                    f"DECISION: FULL PROFIT BOOKING RECOMMENDED. Close all positions at market. "
                    f"DO NOT TRAIL FURTHER — high probability of mean-reversion exhaustion."
                )
            achieved = ["T1_ACHIEVED", "TARGET_ACHIEVED"]

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type="SQUEEZE_BREAKOUT",
            stage=stage,
            symbol=symbol,
            exchange="NSE",
            direction="BULLISH",
            headline=headline,
            summary=rationale,
            ltp=2920.0 if milestone.upper() == "T1" else (2990.0 if milestone.upper() == "TRAIL" else 3050.0),
            trigger_level=2860.0,
            target_level=3050.0,
            stop_loss=2820.0,
            confidence=92,
            created_at=now_iso,
            is_live=False,
            environment="TEST",
            is_invalidated=False,
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
                    f"Stop-loss level breached at ₹2,840.00 (LTP ₹2,835.00). "
                    f"Squeeze breakout thesis is no longer valid. Close active positions."
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
                invalidation_reason=(
                    f"Stop-loss level breached at ₹2,840.00 (LTP ₹2,835.00). "
                    f"Trade setup invalidated."
                ),
                invalidated_at=now_iso,
                metrics={"is_test": True, "test_mode": "invalidation_simulation"},
            )
        else:
            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage=stage,
                symbol=symbol,
                exchange="NSE",
                direction="BULLISH",
                headline=f"🧪 [TEST] ⚡ {alert_type.replace('_', ' ')} {stage.replace('_', ' ')}: {symbol}",
                summary=(
                    f"Call writers shedding 14.5% OI with 2.4x turnover holding intraday VWAP. "
                    f"Coiling for momentum expansion."
                ),
                ltp=2860.0,
                trigger_level=2880.0,
                target_level=3050.0,
                stop_loss=2820.0,
                confidence=88,
                created_at=now_iso,
                is_live=False,
                environment="TEST",
                is_invalidated=False,
                metrics={"is_test": True, "vol_oi_ratio": 2.4, "oi_change_pct": -14.5, "rvol": 1.8},
                actionable_plan={
                    "action": "TEST_ONLY",
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
        """Scans watched indices and F&O symbols for Gamma Blast inflection."""
        from market.options import get_options_chain
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        for sym in self._watched_indices:
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
        for sym in self._watched_equities:
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
        for sym in self._watched_equities:
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

    def scan_fresh_signals_now(self) -> list[AutoAlert]:
        """Scans watched universe for fresh market signals across all detectors."""
        results: list[AutoAlert] = []
        results.extend(self.scan_gamma_blasts())
        results.extend(self.scan_squeeze_breakouts())
        results.extend(self.scan_circuits())
        return results

    def scan_all_now(self) -> list[AutoAlert]:
        """Executes full diagnostic scan across all detectors and returns new alerts."""
        # 1. Check invalidations on existing alerts first
        self.check_and_alert_invalidations()
        # 2. Check target milestones & trailing stop updates on existing alerts
        self.check_and_alert_targets_and_trailing()
        # 3. Check for fresh market signals
        return self.scan_fresh_signals_now()

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
        while self._is_running and not self._stop_event.is_set():
            try:
                # 1. Proactively check for invalidated trade views/alerts
                self.check_and_alert_invalidations()

                # 2. Proactively check for target achievements & trailing stop ratchets
                self.check_and_alert_targets_and_trailing()

                # 3. Check for fresh market signals during market hours
                from engine.alerts import _is_market_hours

                if _is_market_hours():
                    self.scan_fresh_signals_now()
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
    ) -> list[AutoAlert]:
        """Returns buffered alerts with optional filtering."""
        with self._lock:
            self._load()
            res = list(self._alerts)

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

    def _load(self) -> None:
        try:
            target_path = get_auto_alerts_file()
            if target_path.exists():
                data = json.loads(target_path.read_text())
                alerts = []
                for d in data:
                    if isinstance(d, dict):
                        alerts.append(AutoAlert(
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
                        ))
                self._alerts = alerts
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _load error: {e}")
            self._alerts = []


# Module-level singleton instance
auto_alert_engine = AutoAlertEngine()

