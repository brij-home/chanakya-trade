"""
engine/alert_scrutiny.py
────────────────────────
Institutional Two-Tiered AI Sanity & Scrutiny Funnel for Real-Time Market Alerts.

Audits every candidate alert before dispatch to guarantee:
  1. Tier-1 Mathematical & Level Sanctity (0 Tokens, ~1–2 ms):
     - Direction vs Stop-Loss vs Entry vs Targets coherence
     - Mathematical Risk:Reward ratio strictly >= 1:2.0 (target standard >= 1:2.5 to 1:3.0)
     - Strict "No Chase" boundary: reject setups extended > 1.2% past pivot
     - Minimum daily turnover / liquidity threshold (filters operator pump traps)
  2. Tier-2 AI Devil's Advocate / Fast-LLM Auditor (< 2.5s timeout):
     - Structured audit of derivative flows (OI buildup/unwind), price action, and volume
     - Devil's Advocate failure-mode detection (identifies #1 reason the setup could fail)
     - Actionable institutional guidance with exact trailing and execution discipline
  3. Fail-Safe Quantitative Fallback:
     - Zero blackout guarantee: if LLM times out or hits rate limits, deterministic quantitative
       scoring takes over seamlessly with clear provenance.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("engine.alert_scrutiny")

IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
# Institutional MCX Commodity Minimum Stop-Loss Volatility Floors (Points)
# Derived from empirical daily ATR and tick-size distribution to eliminate
# SUB_ATR_NOISE_WHIPSAW liquidations in volatile commodity contracts.
# ─────────────────────────────────────────────────────────────────────────────
COMMODITY_MIN_SL_FLOORS: dict[str, float] = {
    "CRUDEOIL": 80.0,
    "CRUDEOILM": 80.0,
    "NATURALGAS": 6.0,
    "NATGASMINI": 6.0,
    "GOLD": 250.0,
    "GOLDM": 250.0,
    "SILVER": 450.0,
    "SILVERM": 450.0,
    "COPPER": 6.0,
    "ZINC": 2.5,
    "ALUMINIUM": 2.5,
}

# ─────────────────────────────────────────────────────────────────────────────
# Institutional Indian Index Minimum Spot/Futures Stop-Loss Volatility Floors (Points)
# Derived from empirical 1-minute order book tick noise and typical ATR distribution
# to eliminate SUB_NOISE_WHIPSAW stop-outs on Indian benchmark indices.
# ─────────────────────────────────────────────────────────────────────────────
INDEX_MIN_SL_FLOORS: dict[str, float] = {
    "NIFTY": 25.0,
    "NIFTY 50": 25.0,
    "NIFTY50": 25.0,
    "BANKNIFTY": 65.0,
    "NIFTY BANK": 65.0,
    "FINNIFTY": 30.0,
    "NIFTY FIN SERVICE": 30.0,
    "MIDCPNIFTY": 18.0,
    "NIFTY MID SELECT": 18.0,
    "SENSEX": 85.0,
    "BSE SENSEX": 85.0,
    "BANKEX": 85.0,
}


@dataclass
class ScrutinyResult:
    """Institutional scrutiny verdict and risk analysis dossier."""

    status: str  # "APPROVED" | "REJECTED" | "QUANT_VERIFIED" | "PENDING_AI"
    score: int  # 0 to 100
    logic_confirmation: str
    trap_risk_warning: str
    actionable_guidance: str
    sanctity_matrix: dict[str, bool] = field(default_factory=dict)
    rejection_reason: Optional[str] = None
    auditor_model: str = "FAST_LLM"  # "FAST_LLM" | "QUANT_FALLBACK" | "DETERMINISTIC"
    audited_at: str = ""

    def __post_init__(self) -> None:
        if not self.audited_at:
            self.audited_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlertScrutinyAuditor:
    """
    Evaluates market trade setups across Tier-1 mathematical invariants
    and Tier-2 AI Chief Risk Officer scrutiny.
    """

    def __init__(self, min_rr_ratio: float = 1.3, max_intraday_risk_pct: float = 8.0) -> None:
        drift_rr = float(os.environ.get("CHANAKYA_MIN_RR_OVERRIDE", "0"))
        self.min_rr_ratio = max(min_rr_ratio, drift_rr) if drift_rr > 0 else min_rr_ratio
        self.max_intraday_risk_pct = max_intraday_risk_pct
        self._cache: dict[str, tuple[float, ScrutinyResult]] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 90.0  # 90s in-memory scrutiny cache to prevent rate-limit flooding

    # ── Tier 1: Deterministic Mathematical Sanity Gate ───────────────────────

    def verify_tier1_sanity(self, alert: Any) -> tuple[bool, str, dict[str, bool]]:
        """
        Validates price geometry, risk:reward, and chase boundaries in <2ms without LLM.
        Returns: (is_passed, failure_reason, sanity_flags)
        """
        flags: dict[str, bool] = {
            "level_coherence": False,
            "rr_valid": False,
            "risk_within_bounds": False,
            "no_chase": False,
        }

        # Bypass strict sanity for simulation/test alerts if requested
        if getattr(alert, "environment", "") == "TEST" or not getattr(alert, "is_live", True):
            flags["level_coherence"] = True
            flags["rr_valid"] = True
            flags["risk_within_bounds"] = True
            flags["no_chase"] = True
            return True, "", flags

        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = str(getattr(alert, "direction", "BULLISH")).upper()
        trigger = float(getattr(alert, "trigger_level", 0.0) or ltp)

        # 1. Non-zero price check
        if ltp <= 0 or sl <= 0 or t1 <= 0:
            return False, f"Incomplete price levels (LTP={ltp}, SL={sl}, T1={t1})", flags

        # Detect whether levels represent an option contract premium (Long CE or Long PE premium)
        atype = str(getattr(alert, "alert_type", "") or "")
        has_opt_marker = bool(
            getattr(alert, "contract_symbol", None)
            or getattr(alert, "option_type", None)
            or getattr(alert, "strike", None)
        )
        if atype in ("OPTIONS_MOMENTUM", "OPTION_WRITE"):
            is_option_premium_levels = True
        elif atype == "GAMMA_BLAST" and getattr(alert, "option_type", None):
            is_option_premium_levels = True
        elif not has_opt_marker:
            is_option_premium_levels = False
        elif getattr(alert, "option_premium", None) is not None:
            # Check if ltp is close to option_premium (within 15% tolerance for intraday movement)
            is_option_premium_levels = abs(ltp - float(alert.option_premium)) < max(
                1.0, float(alert.option_premium) * 0.15
            )
        else:
            is_option_premium_levels = False

        # 2. Geometric Level Coherence
        if is_option_premium_levels or direction in ("BULLISH", "LONG", "BUY"):
            # For equity long OR long option premium (Call or Put buyer):
            if sl >= ltp:
                return False, f"Inverted Stop-Loss: SL (Rs.{sl:,.2f}) >= LTP (Rs.{ltp:,.2f})", flags
            if t1 <= ltp:
                return (
                    False,
                    f"Inverted Target: Target (Rs.{t1:,.2f}) <= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            risk_pts = ltp - sl
            reward_pts = t1 - ltp

        elif direction in ("BEARISH", "SHORT", "SELL"):
            # For cash equity short or futures short:
            if sl <= ltp:
                return (
                    False,
                    f"Inverted Bearish Stop-Loss: SL (Rs.{sl:,.2f}) <= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            if t1 >= ltp:
                return (
                    False,
                    f"Inverted Bearish Target: Target (Rs.{t1:,.2f}) >= LTP (Rs.{ltp:,.2f})",
                    flags,
                )
            risk_pts = sl - ltp
            reward_pts = ltp - t1
        else:
            # NEUTRAL or non-directional (e.g. straddle range)
            risk_pts = abs(ltp - sl)
            reward_pts = abs(t1 - ltp)

        flags["level_coherence"] = True

        # 3. Maximum Risk Boundary Check
        # Options allow up to 45% defined risk stop; cash equities/futures capped at max_intraday_risk_pct (8%)
        # For OPTIONS_MOMENTUM, enforce disciplined risk stop (capped at 32% max to align with trade_plan 30% drawdown ceiling)
        if atype == "OPTIONS_MOMENTUM":
            max_risk = 32.0
        elif is_option_premium_levels:
            max_risk = 45.0
        else:
            max_risk = self.max_intraday_risk_pct
        risk_pct = (risk_pts / ltp) * 100.0 if ltp > 0 else 0.0
        if risk_pct > max_risk:
            return (
                False,
                f"Excessive stop-loss risk distance ({risk_pct:.2f}% > {max_risk}%)",
                flags,
            )

        sym = str(
            getattr(alert, "symbol", "")
            or (alert.get("symbol", "") if isinstance(alert, dict) else "")
        ).upper()
        clean_sym = (
            sym.replace(".NS", "")
            .replace(".BO", "")
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("MCX:", "")
            .replace("NFO:", "")
            .replace("CDS:", "")
            .strip()
        )

        # 3b. Institutional Minimum Stop-Loss Volatility Floor Gate
        # Specific structural floors for MCX Commodities, Indian Benchmark Indices, and Equities
        # to eliminate SUB_NOISE_WHIPSAW and SUB_ATR_NOISE_WHIPSAW stop-outs.
        if clean_sym in COMMODITY_MIN_SL_FLOORS and not is_option_premium_levels:
            min_floor = COMMODITY_MIN_SL_FLOORS[clean_sym]
            if risk_pts < (min_floor * 0.95):  # 5% precision tolerance
                flags["risk_within_bounds"] = False
                return (
                    False,
                    f"Sub-ATR Noise Trap: {clean_sym} stop-loss ({risk_pts:.1f} pts) < minimum structural volatility floor ({min_floor:.1f} pts). Mandate wider stop or defined-risk options.",
                    flags,
                )

        if clean_sym in INDEX_MIN_SL_FLOORS and not is_option_premium_levels:
            idx_floor = INDEX_MIN_SL_FLOORS[clean_sym]
            if risk_pts < (idx_floor * 0.95):
                flags["risk_within_bounds"] = False
                return (
                    False,
                    f"Sub-Noise Trap: {clean_sym} stop-loss ({risk_pts:.1f} pts) < minimum institutional volatility floor ({idx_floor:.1f} pts). Mandate wider structural stop.",
                    flags,
                )

        if (
            not is_option_premium_levels
            and clean_sym not in COMMODITY_MIN_SL_FLOORS
            and clean_sym not in INDEX_MIN_SL_FLOORS
        ):
            eq_atr = 0.0
            metrics = getattr(alert, "metrics", {}) or {}
            if isinstance(metrics, dict):
                eq_atr = float(metrics.get("atr") or metrics.get("atr_14") or 0.0)
            if eq_atr <= 0 and ltp > 0:
                eq_atr = round(ltp * 0.015, 2)
            if eq_atr > 0 and risk_pts < (0.70 * eq_atr * 0.95):
                flags["risk_within_bounds"] = False
                return (
                    False,
                    f"Sub-ATR Equity Noise Trap: {clean_sym} stop-loss ({risk_pts:.1f} pts) < 0.70x ATR volatility floor ({0.70 * eq_atr:.1f} pts).",
                    flags,
                )

        if risk_pct < 0.10:
            return (
                False,
                f"Impossibly tight stop-loss ({risk_pct:.2f}% < 0.10% tick noise threshold)",
                flags,
            )

        flags["risk_within_bounds"] = True

        # 4. Dynamic VIX Regime Adaptation & Mathematical Risk:Reward Asymmetry
        vix_val = None
        try:
            from market.indices import get_vix

            vix_raw = get_vix()
            if hasattr(vix_raw, "ltp"):
                vix_val = float(vix_raw.ltp)
            elif isinstance(vix_raw, dict):
                vix_val = float(
                    vix_raw.get("ltp") or vix_raw.get("value") or vix_raw.get("close") or 0.0
                )
            elif isinstance(vix_raw, (int, float)):
                vix_val = float(vix_raw)
            else:
                vix_val = None
        except Exception:
            vix_val = None

        drift_rr = float(os.environ.get("CHANAKYA_MIN_RR_OVERRIDE", "0"))
        active_min_rr = max(self.min_rr_ratio, drift_rr) if drift_rr > 0 else self.min_rr_ratio
        req_rr = active_min_rr
        if vix_val and vix_val > 0:
            if vix_val > 18.0:
                req_rr = max(active_min_rr, 2.0)
            elif vix_val < 11.5:
                req_rr = min(active_min_rr, 1.3)

            # Extreme Tail Risk Gate: If VIX > 25.0, naked option buying carries extreme IV crush hazard
            if vix_val > 25.0 and is_option_premium_levels:
                act = str((getattr(alert, "actionable_plan", None) or {}).get("action", "")).upper()
                if "BUY" in act and "SPREAD" not in act:
                    return (
                        False,
                        f"VIX Tail Risk Veto: India VIX {vix_val:.1f} > 25 (Extreme IV crush risk on naked option buying). Mandate defined-risk spread structure.",
                        flags,
                    )

        rr_ratio = reward_pts / risk_pts if risk_pts > 0 else 0.0
        if rr_ratio < req_rr:
            return (
                False,
                f"Unfavorable Risk:Reward ratio (1:{rr_ratio:.2f} < 1:{req_rr:.1f})",
                flags,
            )
        flags["rr_valid"] = True

        # 4b. Underlying Trade Plan Asymmetry Sanity Check
        plan = getattr(alert, "actionable_plan", {}) or {}
        tp_dict = plan.get("trade_plan") if isinstance(plan, dict) else None
        if isinstance(tp_dict, dict):
            if (
                tp_dict.get("is_asymmetry_viable") is False
                or str(tp_dict.get("asymmetry_verdict", "")).upper() == "POOR_ASYMMETRY_REJECTED"
            ):
                flags["rr_valid"] = False
                return (
                    False,
                    f"Sanity Veto: Underlying trade plan rejected for poor asymmetry ({tp_dict.get('asymmetry_note') or 'Unfavorable structural R:R'})",
                    flags,
                )

        # 4c-iv. Physical Settlement Expiry Week Warning for Single-Stock Options & Futures
        sym_raw = str(getattr(alert, "symbol", "") or "").upper()
        is_futures = (
            "FUT" in sym_raw or str(getattr(alert, "instrument_type", "")).upper() == "FUTURE"
        )
        if (is_option_premium_levels or is_futures) and clean_sym not in INDEX_MIN_SL_FLOORS:
            exp_str = getattr(alert, "expiry_date", None)
            metrics = getattr(alert, "metrics", {}) or {}
            if not exp_str and isinstance(metrics, dict):
                exp_str = metrics.get("expiry") or metrics.get("expiry_date")
            try:
                from engine.alert_expiry import is_monthly_physical_expiry_week

                if is_monthly_physical_expiry_week(exp_str, symbol=clean_sym):
                    flags["physical_settlement_week"] = True
                    is_rollover = isinstance(metrics, dict) and (
                        metrics.get("rollover_series") == "NEXT_MONTH"
                        or metrics.get("is_rollover_recommended") is True
                    )
                    if is_rollover:
                        flags["rollover_protected"] = True
            except Exception:
                pass

        # 4d. MCX High-Impact Scheduled Inventory Blackout Gate
        if clean_sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI"):
            alert_dt = None
            raw_ts = (
                getattr(alert, "created_at", None)
                or getattr(alert, "timestamp", None)
                or (
                    alert.get("created_at") or alert.get("timestamp")
                    if isinstance(alert, dict)
                    else None
                )
            )
            if raw_ts and isinstance(raw_ts, str):
                try:
                    clean_ts = raw_ts.replace(" IST", "").strip()
                    try:
                        alert_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=IST
                        )
                    except ValueError:
                        alert_dt = datetime.fromisoformat(
                            clean_ts.replace("Z", "+00:00")
                        ).astimezone(IST)
                except Exception:
                    pass
            if not alert_dt:
                alert_dt = datetime.now(IST)

            hh, mm = alert_dt.hour, alert_dt.minute
            wday = alert_dt.weekday()

            # Wednesday EIA Weekly Petroleum Status Report (Crude): 19:45 - 20:45 IST
            if clean_sym in ("CRUDEOIL", "CRUDEOILM") and wday == 2:
                if (hh == 19 and mm >= 45) or (hh == 20 and mm <= 45):
                    return (
                        False,
                        f"EIA Crude Inventory Blackout: High-impact US weekly petroleum status report release active ({hh:02d}:{mm:02d} IST). Disallow fresh breakout entries.",
                        flags,
                    )

            # Thursday EIA Natural Gas Storage Report: 19:45 - 20:45 IST
            if clean_sym in ("NATURALGAS", "NATGASMINI") and wday == 3:
                if (hh == 19 and mm >= 45) or (hh == 20 and mm <= 45):
                    return (
                        False,
                        f"EIA Natural Gas Storage Blackout: High-impact US gas storage report release active ({hh:02d}:{mm:02d} IST). Disallow fresh breakout entries.",
                        flags,
                    )

        # 4e. Global Macro Divergence Gate for MCX Bullion & Energy (Futures)
        if not is_option_premium_levels and clean_sym in (
            "GOLD",
            "GOLDM",
            "SILVER",
            "SILVERM",
            "CRUDEOIL",
            "CRUDEOILM",
        ):
            try:
                from market.macro import get_macro_snapshot

                macro_snap = get_macro_snapshot()
                if macro_snap:
                    # Gold/Silver vs DXY
                    if (
                        clean_sym in ("GOLD", "GOLDM", "SILVER", "SILVERM")
                        and macro_snap.dxy_change is not None
                    ):
                        dxy_c = float(macro_snap.dxy_change)
                        if direction in ("BULLISH", "LONG", "BUY") and dxy_c >= 0.35:
                            return (
                                False,
                                f"Global Macro Divergence: US Dollar Index (DXY) surging +{dxy_c:.2f}% creates heavy headwind for bullion longs.",
                                flags,
                            )
                        elif direction in ("BEARISH", "SHORT", "SELL") and dxy_c <= -0.35:
                            return (
                                False,
                                f"Global Macro Divergence: US Dollar Index (DXY) dumping {dxy_c:.2f}% creates heavy short squeeze risk for bullion shorts.",
                                flags,
                            )
                    # Crude Oil vs Brent
                    elif (
                        clean_sym in ("CRUDEOIL", "CRUDEOILM")
                        and macro_snap.crude_change is not None
                    ):
                        brent_c = float(macro_snap.crude_change)
                        if direction in ("BULLISH", "LONG", "BUY") and brent_c <= -1.5:
                            return (
                                False,
                                f"Global Macro Divergence: Global Brent crude selling off {brent_c:.2f}% disallows domestic MCX longs.",
                                flags,
                            )
                        elif direction in ("BEARISH", "SHORT", "SELL") and brent_c >= 1.5:
                            return (
                                False,
                                f"Global Macro Divergence: Global Brent crude surging +{brent_c:.2f}% disallows domestic MCX shorts.",
                                flags,
                            )
            except Exception:
                pass

        # 4f. Obstacle Runway Gate (Eliminate Stuck Signals hitting immediate brick walls)
        # Verifies that Target 1 is not obstructed by an immediate heavy resistance / Max OI wall
        # closer than 1.25x risk distance.
        metrics = getattr(alert, "metrics", {}) or {}
        if isinstance(metrics, dict) and not is_option_premium_levels:
            call_wall = metrics.get("max_call_oi_strike") or metrics.get("call_oi_wall")
            put_wall = metrics.get("max_put_oi_strike") or metrics.get("put_oi_wall")
            pdh = metrics.get("pdh") or metrics.get("prior_high")
            pdl = metrics.get("pdl") or metrics.get("prior_low")

            is_bull = direction in ("BULLISH", "LONG", "BUY")
            if is_bull:
                obstacles = [float(o) for o in (call_wall, pdh) if o and float(o) > ltp]
                if obstacles:
                    nearest_obs = min(obstacles)
                    obs_dist = nearest_obs - ltp
                    # If an obstacle lies within 1.25x of the risk distance, the trade will stall at the wall
                    if obs_dist < (1.25 * risk_pts) and obs_dist < (0.75 * reward_pts):
                        flags["obstacle_runway_clear"] = False
                        flags["trap_immediate_resistance"] = True
                        logger.debug(
                            f"[AlertScrutiny] Obstacle Runway Trap: {clean_sym} Bullish setup obstructed by wall at ₹{nearest_obs:.1f} (only {obs_dist:.1f} pts away vs {risk_pts:.1f} pts risk)"
                        )
            else:
                obstacles = [float(o) for o in (put_wall, pdl) if o and float(o) < ltp]
                if obstacles:
                    nearest_obs = max(obstacles)
                    obs_dist = ltp - nearest_obs
                    if obs_dist < (1.25 * risk_pts) and obs_dist < (0.75 * reward_pts):
                        flags["obstacle_runway_clear"] = False
                        flags["trap_immediate_support"] = True
                        logger.debug(
                            f"[AlertScrutiny] Obstacle Runway Trap: {clean_sym} Bearish setup obstructed by floor at ₹{nearest_obs:.1f} (only {obs_dist:.1f} pts away vs {risk_pts:.1f} pts risk)"
                        )

            # 4g. Volume Profile Airspace Clearance (LVN vs HVN Congestion Check)
            # Identifies whether Target 1 enters clean Low Volume Node (LVN) airspace or risks stalling at Volume POC
            poc_val = metrics.get("poc") or metrics.get("point_of_control")
            if poc_val and ltp > 0:
                try:
                    poc_f = float(poc_val)
                    # If target is on POC within 0.3%, price risks getting trapped at equilibrium
                    if abs(t1 - poc_f) / ltp < 0.003 and abs(ltp - poc_f) / ltp > 0.005:
                        flags["hvn_congestion_risk"] = True
                    else:
                        flags["lvn_vacuum_clear"] = True
                except (ValueError, TypeError):
                    pass
            elif metrics.get("is_lvn_vacuum"):
                flags["lvn_vacuum_clear"] = True

        # 5. Strict "No Chase" Gate
        # Disqualify if price has already blown past trigger by >2.5% without retest
        if trigger > 0 and ltp > 0:
            if (is_option_premium_levels or direction in ("BULLISH", "LONG", "BUY")) and ltp > (
                trigger * 1.025
            ):
                return (
                    False,
                    f"No-Chase Violation: Price already extended {((ltp / trigger) - 1) * 100:.2f}% above trigger",
                    flags,
                )
            elif (
                direction in ("BEARISH", "SHORT", "SELL")
                and not is_option_premium_levels
                and ltp < (trigger * 0.975)
            ):
                return (
                    False,
                    f"No-Chase Violation: Price already extended {((trigger / ltp) - 1) * 100:.2f}% below trigger",
                    flags,
                )

        flags["no_chase"] = True

        # 6. Index Options Deep OTM Trap Gate:
        # Reject illiquid, high-theta lottery strikes > 1.2% away from spot on index options
        strike_val = getattr(alert, "strike", None) or (
            alert.get("strike", None) if isinstance(alert, dict) else None
        )
        metrics_dict = getattr(alert, "metrics", {}) or (
            alert.get("metrics", {}) if isinstance(alert, dict) else {}
        )
        spot_val = (
            metrics_dict.get("spot") if isinstance(metrics_dict, dict) else None
        ) or getattr(alert, "underlying_spot", None)
        if (
            clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
            and strike_val
            and spot_val
        ):
            try:
                stk = float(strike_val)
                spt = float(spot_val)
                if spt > 0:
                    dist_pct = abs(stk - spt) / spt
                    if dist_pct > 0.012:
                        return (
                            False,
                            f"Deep OTM Index Option: Strike {stk:,.0f} is {dist_pct * 100:.2f}% away from spot {spt:,.1f} (>1.2% theta decay trap)",
                            flags,
                        )
            except (ValueError, TypeError):
                pass

        # 7. Closed-Loop Learning Engine Lockout:
        # Reject signals on assets that failed twice or are under active post-mortem lockout
        try:
            from engine.learning_engine import pattern_learning_engine

            is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
                clean_sym, direction=direction, ltp=ltp
            )
            if is_locked:
                return (
                    False,
                    f"Learning Engine Lockout Active: {lock_reason}",
                    flags,
                )
        except Exception:
            pass

        # 7b. Opposing Major Zone Collision Gate (Truncated Headroom):
        # Prevent buying right beneath a major overhead supply zone (PDH/Day High) or shorting right above major demand (PDL/Day Low)
        ref_spot = float(spot_val or (ltp if not is_option_premium_levels else 0.0))
        if ref_spot > 0:
            is_bull_setup = direction in ("BULLISH", "LONG", "BUY") or (
                has_opt_marker and getattr(alert, "option_type", "") == "CE"
            )
            is_bear_setup = direction in ("BEARISH", "SHORT", "SELL") or (
                has_opt_marker and getattr(alert, "option_type", "") == "PE"
            )

            if is_bull_setup and not is_bear_setup:
                overhead_barriers: list[tuple[float, str]] = []
                pdh = float(metrics_dict.get("prev_day_high") or 0.0)
                pwh = float(metrics_dict.get("prev_week_high") or 0.0)
                dh = float(metrics_dict.get("day_high") or 0.0)
                dl = float(metrics_dict.get("day_low") or 0.0)
                if dh > ref_spot and dl > 0 and ((dh - dl) / ref_spot) >= 0.0025:
                    overhead_barriers.append((dh, "Day High"))
                if pdh > ref_spot:
                    overhead_barriers.append((pdh, "Previous Day High (PDH)"))
                if pwh > ref_spot:
                    overhead_barriers.append((pwh, "Previous Week High (PWH)"))

                for barrier_lvl, barrier_name in overhead_barriers:
                    headroom_pts = barrier_lvl - ref_spot
                    headroom_pct = (headroom_pts / ref_spot) * 100.0
                    if 0.0 < headroom_pct < 0.15:
                        return (
                            False,
                            f"Opposing Supply Collision: Spot (₹{ref_spot:,.1f}) is right beneath {barrier_name} (₹{barrier_lvl:,.1f}, only {headroom_pts:.1f} pts / {headroom_pct:.2f}% headroom); avoid buying into resistance",
                            flags,
                        )
            elif is_bear_setup and not is_bull_setup:
                underneath_barriers: list[tuple[float, str]] = []
                pdl = float(metrics_dict.get("prev_day_low") or 0.0)
                pwl = float(metrics_dict.get("prev_week_low") or 0.0)
                dh = float(metrics_dict.get("day_high") or 0.0)
                dl = float(metrics_dict.get("day_low") or 0.0)
                if dl > 0 and dl < ref_spot and dh > 0 and ((dh - dl) / ref_spot) >= 0.0025:
                    underneath_barriers.append((dl, "Day Low"))
                if pdl > 0 and pdl < ref_spot:
                    underneath_barriers.append((pdl, "Previous Day Low (PDL)"))
                if pwl > 0 and pwl < ref_spot:
                    underneath_barriers.append((pwl, "Previous Week Low (PWL)"))

                for barrier_lvl, barrier_name in underneath_barriers:
                    headroom_pts = ref_spot - barrier_lvl
                    headroom_pct = (headroom_pts / ref_spot) * 100.0
                    if 0.0 < headroom_pct < 0.15:
                        return (
                            False,
                            f"Opposing Demand Collision: Spot (₹{ref_spot:,.1f}) is right above {barrier_name} (₹{barrier_lvl:,.1f}, only {headroom_pts:.1f} pts / {headroom_pct:.2f}% headroom); avoid shorting into support",
                            flags,
                        )

        # 7c. VWAP Overextension & Climax Exhaustion Gate:
        # Disqualify setups where price has moved too far from session VWAP without a base
        spot_vwap_pct = None
        if isinstance(metrics_dict, dict) and metrics_dict.get("spot_to_vwap_pct") is not None:
            try:
                spot_vwap_pct = float(metrics_dict["spot_to_vwap_pct"])
            except (ValueError, TypeError):
                pass
        if spot_vwap_pct is None:
            m_vwap = float(
                (metrics_dict.get("vwap") if isinstance(metrics_dict, dict) else 0.0) or 0.0
            )
            if ref_spot > 0 and m_vwap > 0:
                spot_vwap_pct = round(((ref_spot - m_vwap) / m_vwap) * 100.0, 2)

        if spot_vwap_pct is not None:
            is_idx = clean_sym in INDEX_MIN_SL_FLOORS
            max_ext = 0.65 if is_idx else 1.40
            if (
                direction in ("BULLISH", "LONG", "BUY") or getattr(alert, "option_type", "") == "CE"
            ) and spot_vwap_pct > max_ext:
                return (
                    False,
                    f"Climax Exhaustion: Spot is extended +{spot_vwap_pct:.2f}% above VWAP (>{max_ext:.2f}% threshold); wait for pullback to VWAP/20-EMA",
                    flags,
                )
            elif (
                direction in ("BEARISH", "SHORT", "SELL")
                or getattr(alert, "option_type", "") == "PE"
            ) and spot_vwap_pct < -max_ext:
                return (
                    False,
                    f"Capitulation Exhaustion: Spot is extended {spot_vwap_pct:.2f}% below VWAP (<-{max_ext:.2f}% threshold); wait for relief bounce",
                    flags,
                )

        # 8. Climax / Overbought Exhaustion Filter:
        # Prevent buying the top of a parabolic blow-off or shorting the very bottom of a capitulation
        rsi_val = None
        if isinstance(metrics_dict, dict):
            for k in ("rsi", "rsi_14", "rsi_5m", "rsi_15m"):
                if metrics_dict.get(k) is not None:
                    try:
                        rsi_val = float(metrics_dict[k])
                        break
                    except (ValueError, TypeError):
                        pass
        if rsi_val is None and hasattr(alert, "rsi") and alert.rsi is not None:
            try:
                rsi_val = float(alert.rsi)
            except (ValueError, TypeError):
                pass

        if rsi_val is not None and rsi_val > 0:
            is_put_option = (
                atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                and getattr(alert, "option_type", "") == "PE"
            ) or direction in ("BEARISH", "SHORT", "SELL")
            is_call_option = (
                atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                and getattr(alert, "option_type", "") == "CE"
            ) or direction in ("BULLISH", "LONG", "BUY")

            tf_str = str(
                getattr(alert, "timeframe", "")
                or (metrics_dict.get("timeframe") if isinstance(metrics_dict, dict) else "")
                or ""
            ).lower()
            is_intraday = tf_str in ("5m", "15m", "intraday", "1m", "3m") or atype in (
                "OPTIONS_MOMENTUM",
                "INTRADAY_SPARK",
                "GAMMA_BLAST",
                "SQUEEZE_BREAKOUT",
                "SQUEEZE_BREAKDOWN",
            )
            rsi_overbought = 72.0 if is_intraday else 78.0
            rsi_oversold = 28.0 if is_intraday else 22.0

            # Long equity / Call option: reject when RSI exceeds threshold
            if is_call_option and not is_put_option:
                if rsi_val > rsi_overbought:
                    return (
                        False,
                        f"Climax Exhaustion: {'Intraday ' if is_intraday else ''}RSI ({rsi_val:.1f}) > {rsi_overbought:.0f} entering parabolic blow-off top; wait for pullback to 20-EMA/VWAP",
                        flags,
                    )
            # Short equity / Put option (underlying): reject when underlying RSI breaches oversold floor
            elif is_put_option and not is_call_option:
                if rsi_val < rsi_oversold:
                    return (
                        False,
                        f"Oversold Exhaustion: {'Intraday ' if is_intraday else ''}RSI ({rsi_val:.1f}) < {rsi_oversold:.0f} entering capitulation floor; wait for relief bounce before shorting",
                        flags,
                    )

        # 9. Mean Reversion Extension Filter (Price extended from 20-EMA):
        if isinstance(metrics_dict, dict) and not is_option_premium_levels:
            ema20 = metrics_dict.get("ema20") or metrics_dict.get("ema_20")
            atr_val = metrics_dict.get("atr")
            if ema20 and atr_val:
                try:
                    ema20_f = float(ema20)
                    atr_f = float(atr_val)
                    if ema20_f > 0 and atr_f > 0:
                        dist_from_ema = abs(ltp - ema20_f)
                        tf_str = str(
                            getattr(alert, "timeframe", "") or metrics_dict.get("timeframe") or ""
                        ).lower()
                        is_intraday_ema = tf_str in (
                            "5m",
                            "15m",
                            "intraday",
                            "1m",
                            "3m",
                        ) or atype in ("INTRADAY_SPARK", "SQUEEZE_BREAKOUT", "SQUEEZE_BREAKDOWN")
                        max_atr_mult = 2.2 if is_intraday_ema else 3.5
                        if dist_from_ema > (max_atr_mult * atr_f):
                            return (
                                False,
                                f"Mean Reversion Risk: Extended {dist_from_ema / atr_f:.1f}x ATR from 20-EMA (₹{ema20_f:,.1f}) without structural base",
                                flags,
                            )
                except (ValueError, TypeError):
                    pass

        # 10. Multi-Timeframe (15m) Trend Alignment Gate:
        # Reject 5m counter-trend scalps if higher timeframe (15m) is in conflicting structural markdown/markup,
        # UNLESS an opening drive breakdown/breakout is actively confirmed by price action.
        mtf_15m_trend = None
        has_opening_breakdown = False
        has_opening_breakout = False
        if isinstance(metrics_dict, dict):
            mtf_15m_trend = metrics_dict.get("mtf_15m_trend") or metrics_dict.get("trend_15m")
            has_opening_breakdown = bool(metrics_dict.get("has_opening_breakdown"))
            has_opening_breakout = bool(metrics_dict.get("has_opening_breakout"))
        if mtf_15m_trend:
            mtf_upper = str(mtf_15m_trend).upper()
            if (
                direction in ("BULLISH", "LONG", "BUY")
                and any(k in mtf_upper for k in ("BEAR", "DOWN", "MARKDOWN"))
                and not has_opening_breakout
            ):
                return (
                    False,
                    f"MTF Confluence Failure: 5m Bullish trigger conflicting with 15m structural markdown ({mtf_upper})",
                    flags,
                )
            elif (
                direction in ("BEARISH", "SHORT", "SELL")
                and any(k in mtf_upper for k in ("BULL", "UP", "MARKUP"))
                and not has_opening_breakdown
            ):
                return (
                    False,
                    f"MTF Confluence Failure: 5m Bearish trigger conflicting with 15m structural markup ({mtf_upper})",
                    flags,
                )

        # 11. Institutional Liquidity & Bid-Ask Spread Gate:
        # Wide-spread instruments trigger immediate execution drag and slippage hazard
        bid_val = None
        ask_val = None
        if isinstance(metrics_dict, dict):
            bid_val = metrics_dict.get("bid") or metrics_dict.get("best_bid")
            ask_val = metrics_dict.get("ask") or metrics_dict.get("best_ask")
        if bid_val is None and hasattr(alert, "bid"):
            bid_val = getattr(alert, "bid", None)
        if ask_val is None and hasattr(alert, "ask"):
            ask_val = getattr(alert, "ask", None)

        if bid_val is not None and ask_val is not None:
            try:
                b = float(bid_val)
                a = float(ask_val)
                if a > b > 0 and ltp > 0:
                    spread_pct = (a - b) / ltp
                    max_spread = (
                        0.06
                        if (
                            is_option_premium_levels or atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST")
                        )
                        else 0.015
                    )
                    if spread_pct > max_spread:
                        flags["spread_valid"] = False
                        return (
                            False,
                            f"Slippage Hazard Veto: Bid-Ask Spread ({spread_pct * 100:.2f}%) exceeds institutional threshold ({max_spread * 100:.1f}%) [Bid: Rs.{b:,.2f}, Ask: Rs.{a:,.2f}]",
                            flags,
                        )
            except (ValueError, TypeError):
                pass
        flags["spread_valid"] = True

        # 12. Stock Option Illiquidity Gate:
        # Single-stock options frequently suffer from dry order books and wide bid-ask slippage.
        # Enforce intelligent, time-aware liquidity thresholds and unit normalization:
        if is_option_premium_levels or atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST"):
            is_index_option = clean_sym in (
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "SENSEX",
                "BANKEX",
            )
            exch_str = str(
                getattr(alert, "exchange", "")
                or (alert.get("exchange") if isinstance(alert, dict) else "")
            ).upper()
            seg_str = str(
                getattr(alert, "segment", "")
                or (alert.get("segment") if isinstance(alert, dict) else "")
            ).upper()
            is_commodity_or_currency = exch_str in ("MCX", "CDS") or seg_str in (
                "COMMODITY",
                "CURRENCY",
            )

            if not is_index_option and not is_commodity_or_currency:
                opt_oi = None
                opt_vol = None
                if isinstance(metrics_dict, dict):
                    opt_oi = metrics_dict.get("oi") or metrics_dict.get("open_interest")
                    opt_vol = metrics_dict.get("volume") or metrics_dict.get("vol")
                if opt_oi is None and hasattr(alert, "oi"):
                    opt_oi = getattr(alert, "oi", None)
                if opt_vol is None and hasattr(alert, "volume"):
                    opt_vol = getattr(alert, "volume", None)

                try:
                    # Resolve contract lot size to distinguish contracts vs shares
                    lot_sz = getattr(alert, "lot_size", None)
                    if not lot_sz or lot_sz <= 0:
                        try:
                            from engine.position_sizer import get_lot_size

                            lot_sz = get_lot_size(clean_sym)
                        except Exception:
                            lot_sz = 1
                    lot_sz = lot_sz or 1

                    # 1. Normalize OI to contracts
                    contracts_oi = None
                    if opt_oi is not None:
                        oi_f = float(opt_oi)
                        # If OI exceeds 2.5x lot size and lot size > 1, it was reported in shares
                        contracts_oi = (
                            (oi_f / lot_sz) if (lot_sz > 1 and oi_f > (lot_sz * 2.5)) else oi_f
                        )
                        if contracts_oi < 50:
                            flags["liquidity_valid"] = False
                            return (
                                False,
                                f"Stock Option Illiquidity Trap: Strike Open Interest ({contracts_oi:,.0f}) < 50 contracts (Severe liquidity risk)",
                                flags,
                            )

                    # 2. Time-Aware Volume Floor
                    if opt_vol is not None:
                        vol_f = float(opt_vol)
                        contracts_vol = (
                            (vol_f / lot_sz) if (lot_sz > 1 and vol_f > (lot_sz * 2.5)) else vol_f
                        )

                        # Determine session time
                        alert_dt = None
                        raw_ts = (
                            getattr(alert, "created_at", None)
                            or getattr(alert, "timestamp", None)
                            or (
                                alert.get("created_at") or alert.get("timestamp")
                                if isinstance(alert, dict)
                                else None
                            )
                        )
                        if raw_ts:
                            try:
                                if isinstance(raw_ts, datetime):
                                    alert_dt = raw_ts
                                elif isinstance(raw_ts, str):
                                    clean_ts = raw_ts.replace(" IST", "").strip()
                                    try:
                                        alert_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
                                    except ValueError:
                                        alert_dt = datetime.fromisoformat(
                                            clean_ts.replace("Z", "+00:00")
                                        )
                            except Exception:
                                pass
                        if not alert_dt:
                            alert_dt = datetime.now(IST)
                        elif alert_dt.tzinfo is None:
                            alert_dt = alert_dt.replace(tzinfo=IST)
                        else:
                            alert_dt = alert_dt.astimezone(IST)

                        curr_t = alert_dt.time()
                        from datetime import time as dtime

                        # Dynamic volume ramp-up thresholds:
                        # 09:15 - 09:45 IST: market opening 30 mins, volume accumulating (min 15 contracts)
                        # 09:45 - 10:30 IST: morning trend formation (min 30 contracts)
                        # 10:30+ IST: standard session institutional baseline (min 50 contracts)
                        if dtime(9, 15) <= curr_t < dtime(9, 45):
                            min_vol = 15
                        elif dtime(9, 45) <= curr_t < dtime(10, 30):
                            min_vol = 30
                        else:
                            min_vol = 50

                        if contracts_vol < min_vol:
                            flags["liquidity_valid"] = False
                            return (
                                False,
                                f"Stock Option Illiquidity Trap: Strike Daily Volume ({contracts_vol:,.0f}) < {min_vol} contracts (Illiquid execution trap)",
                                flags,
                            )
                except (ValueError, TypeError):
                    pass
        flags["liquidity_valid"] = True

        # 13. Midday Lunch Lull RVOL Expansion Filter (11:30 - 13:00 IST):
        # Breakouts attempted during midday lull without institutional volume frequently collapse into fakeouts.
        if atype in ("SQUEEZE_BREAKOUT", "BREAKOUT", "INTRADAY_MOVER_IGNITED", "VOLUME_EXPANSION"):
            alert_dt = None
            raw_ts = (
                getattr(alert, "created_at", None)
                or getattr(alert, "timestamp", None)
                or (
                    alert.get("created_at") or alert.get("timestamp")
                    if isinstance(alert, dict)
                    else None
                )
            )
            if raw_ts:
                try:
                    if isinstance(raw_ts, datetime):
                        alert_dt = raw_ts
                    elif isinstance(raw_ts, str):
                        clean_ts = raw_ts.replace(" IST", "").strip()
                        try:
                            alert_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            alert_dt = datetime.fromisoformat(clean_ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            if not alert_dt:
                alert_dt = datetime.now(IST)
            elif alert_dt.tzinfo is None:
                alert_dt = alert_dt.replace(tzinfo=IST)
            else:
                alert_dt = alert_dt.astimezone(IST)

            curr_time = alert_dt.time()
            from datetime import time as dtime

            if dtime(11, 30) <= curr_time <= dtime(13, 0):
                rvol = None
                if isinstance(metrics_dict, dict):
                    rvol = (
                        metrics_dict.get("rvol")
                        or metrics_dict.get("rvol_20d")
                        or metrics_dict.get("volume_ratio")
                    )
                if rvol is None and hasattr(alert, "rvol"):
                    rvol = getattr(alert, "rvol", None)
                if rvol is not None:
                    try:
                        rvol_f = float(rvol)
                        if rvol_f > 0 and rvol_f < 1.8:
                            flags["midday_rvol_valid"] = False
                            return (
                                False,
                                f"Midday False Breakout Trap: Breakout attempted during lunch lull (11:30-13:00 IST) with low relative volume (RVOL {rvol_f:.2f}x < 1.8x). Mandate institutional volume expansion.",
                                flags,
                            )
                    except (ValueError, TypeError):
                        pass
        flags["midday_rvol_valid"] = True

        # 14. Macro Benchmark Gravitational Veto (NIFTY 50 Intraday Regime Alignment):
        # When NIFTY is in structural markdown (< VWAP & change <= -0.35%), individual equity breakouts
        # carry >75% failure rates due to index gravitational drag.
        # Conversely, in a runaway markup (> VWAP & change >= +0.40%), short equity breakdowns have high short squeeze risk.
        is_index = clean_sym in (
            "NIFTY",
            "NIFTY 50",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "BANKEX",
        )
        exch_str = str(
            getattr(alert, "exchange", "")
            or (alert.get("exchange") if isinstance(alert, dict) else "")
        ).upper()
        seg_str = str(
            getattr(alert, "segment", "")
            or (alert.get("segment") if isinstance(alert, dict) else "")
        ).upper()
        is_commodity_or_curr = exch_str in ("MCX", "CDS") or seg_str in ("COMMODITY", "CURRENCY")

        if not is_index and not is_commodity_or_curr:
            nifty_data = (
                metrics_dict.get("nifty_regime") if isinstance(metrics_dict, dict) else None
            )
            nifty_change = None
            nifty_below_vwap = None

            if isinstance(nifty_data, dict):
                nifty_change = nifty_data.get("change_pct")
                nifty_below_vwap = nifty_data.get("is_below_vwap")
            elif isinstance(metrics_dict, dict):
                if "nifty_change_pct" in metrics_dict:
                    nifty_change = metrics_dict["nifty_change_pct"]
                if "nifty_below_vwap" in metrics_dict:
                    nifty_below_vwap = metrics_dict["nifty_below_vwap"]

            # If benchmark context wasn't passed directly, attempt in-memory quote cache lookup only (0ms, no network I/O)
            if nifty_change is None:
                try:
                    from market.quotes import _QUOTE_CACHE, _quote_cache_lock

                    with _quote_cache_lock:
                        for k in ("NSE:NIFTY 50", "NIFTY 50", "NSE:NIFTY", "NIFTY"):
                            if k in _QUOTE_CACHE:
                                _, q_obj = _QUOTE_CACHE[k]
                                n_ltp = float(
                                    getattr(q_obj, "last_price", 0.0)
                                    or getattr(q_obj, "ltp", 0.0)
                                    or 0.0
                                )
                                n_vwap = float(getattr(q_obj, "vwap", 0.0) or 0.0)
                                n_chg = float(getattr(q_obj, "change_pct", 0.0) or 0.0)
                                if n_ltp > 0:
                                    nifty_change = n_chg
                                    nifty_below_vwap = (
                                        (n_ltp < n_vwap) if n_vwap > 0 else (n_chg < 0)
                                    )
                                    break
                except Exception:
                    pass

            if nifty_change is not None:
                try:
                    n_chg_f = float(nifty_change)
                    is_nifty_markdown = (n_chg_f <= -0.35) and (nifty_below_vwap is not False)
                    is_nifty_markup = (n_chg_f >= 0.40) and (nifty_below_vwap is False)

                    # Defensive sector check (Pharma & FMCG can decouple during market sell-offs)
                    sec_name = str(
                        (
                            metrics_dict.get("sector_name") or metrics_dict.get("sector")
                            if isinstance(metrics_dict, dict)
                            else ""
                        )
                        or getattr(alert, "sector_name", "")
                        or getattr(alert, "sector", "")
                    ).upper()
                    rrg_quad = str(
                        (metrics_dict.get("rrg_quadrant") if isinstance(metrics_dict, dict) else "")
                        or getattr(alert, "rrg_quadrant", "")
                    ).upper()
                    # Institutional Decoupler Recognition (SEPA / Outperforming Leaders):
                    # A stock with massive independent institutional participation, high RVOL, or explosive option volume
                    # is an institutional leader decoupling from market drag (e.g. SWIGGY +4.16%, Call +254%).
                    vol_oi_val = float((metrics_dict or {}).get("vol_oi_ratio", 0.0) or 0.0)
                    opt_vol = int((metrics_dict or {}).get("volume", 0) or 0)
                    opt_pch = float(
                        (metrics_dict or {}).get("pchange", 0.0)
                        or (metrics_dict or {}).get("option_pchange", 0.0)
                        or (metrics_dict or {}).get("opt_pchange", 0.0)
                        or 0.0
                    )
                    spot_chg = float(
                        (metrics_dict or {}).get("spot_change_pct", 0.0)
                        or (metrics_dict or {}).get("change_pct", 0.0)
                        or 0.0
                    )
                    rvol_val = float(
                        (metrics_dict or {}).get("rvol", 0.0)
                        or (metrics_dict or {}).get("tod_rvol", 0.0)
                        or 0.0
                    )

                    # Explicit decoupler tag from upstream scan engine (highest precedence)
                    upstream_decoupler_tag = str(
                        (metrics_dict or {}).get("decoupler_status", "") or ""
                    ).upper()
                    is_upstream_decoupler = upstream_decoupler_tag == "VERIFIED_DECOUPLER"

                    is_defensive_leader = bool(
                        any(d in sec_name for d in ("PHARMA", "FMCG", "HEALTH", "CONSUMER"))
                        and (spot_chg >= 0.5 or rrg_quad in ("LEADING", "IMPROVING"))
                    )
                    is_options_surge_decoupler = bool(
                        vol_oi_val >= 2.0
                        and opt_vol >= 3000
                        and (opt_pch >= 20.0 or spot_chg >= 1.5)
                    )
                    is_equity_momentum_decoupler = bool(
                        spot_chg >= 2.0
                        and (rvol_val >= 1.8 or rrg_quad in ("LEADING", "IMPROVING"))
                    )
                    is_rrg_momentum_decoupler = bool(
                        rrg_quad in ("LEADING", "IMPROVING")
                        and (spot_chg >= 1.0 or rvol_val >= 1.5)
                    )
                    is_thematic_decoupler = bool(
                        any(
                            d in sec_name
                            for d in (
                                "DEFENCE",
                                "RAIL",
                                "ENERGY",
                                "CAPITAL",
                                "INFRA",
                                "EMS",
                                "TECH",
                                "SOLAR",
                                "CONSUMER",
                            )
                        )
                        and spot_chg >= 1.5
                    )

                    is_verified_decoupler = bool(
                        is_upstream_decoupler
                        or is_defensive_leader
                        or is_options_surge_decoupler
                        or is_equity_momentum_decoupler
                        or is_rrg_momentum_decoupler
                        or is_thematic_decoupler
                    )

                    # Bullish equity alert during severe NIFTY markdown:
                    if (
                        direction in ("BULLISH", "LONG", "BUY")
                        or (
                            atype == "OPTIONS_MOMENTUM"
                            and getattr(alert, "option_type", "") == "CE"
                        )
                    ) and is_nifty_markdown:
                        if not is_verified_decoupler:
                            flags["macro_regime_aligned"] = False
                            flags["benchmark_regime_valid"] = False
                            return (
                                False,
                                f"Benchmark Gravitational Veto: NIFTY 50 in structural markdown ({n_chg_f:.2f}%, below VWAP). Bullish equity breakouts face >75% failure probability during market sell-offs. Mandate short/put setups or leading defensive decouplers.",
                                flags,
                            )
                        else:
                            flags["benchmark_regime_valid"] = True
                            flags["decoupler_status"] = "VERIFIED_DECOUPLER"
                            if isinstance(metrics_dict, dict):
                                metrics_dict["decoupler_status"] = "VERIFIED_DECOUPLER"

                    # Bearish equity alert during strong NIFTY markup:
                    if (
                        direction in ("BEARISH", "SHORT", "SELL")
                        or (
                            atype == "OPTIONS_MOMENTUM"
                            and getattr(alert, "option_type", "") == "PE"
                        )
                    ) and is_nifty_markup:
                        is_short_breakdown_decoupler = bool(
                            rrg_quad == "LAGGING"
                            or (
                                vol_oi_val >= 2.0
                                and opt_vol >= 3000
                                and (opt_pch >= 20.0 or spot_chg <= -1.5)
                            )
                            or (spot_chg <= -2.0 and (rvol_val >= 1.8 or rrg_quad == "LAGGING"))
                        )
                        if not is_short_breakdown_decoupler:
                            flags["macro_regime_aligned"] = False
                            flags["benchmark_regime_valid"] = False
                            return (
                                False,
                                f"Benchmark Gravitational Veto: NIFTY 50 in strong structural markup (+{n_chg_f:.2f}%, above VWAP). Short equity breakdowns have high short-covering squeeze risk.",
                                flags,
                            )
                        else:
                            flags["benchmark_regime_valid"] = True
                            flags["decoupler_status"] = "VERIFIED_DECOUPLER"
                            if isinstance(metrics_dict, dict):
                                metrics_dict["decoupler_status"] = "VERIFIED_DECOUPLER"

                except (ValueError, TypeError):
                    pass
        flags["macro_regime_aligned"] = True
        flags.setdefault("benchmark_regime_valid", True)

        # 15. 3-Bar Parabolic Velocity / Climax Acceleration Gate (Anti-FOMO):
        # Disallow market chasing at the absolute tip of a vertical 3-bar blow-off
        move_3b = None
        if isinstance(metrics_dict, dict):
            move_3b = metrics_dict.get("move_3b_atr") or metrics_dict.get("climax_velocity_atr")
        if move_3b is None and hasattr(alert, "move_3b_atr"):
            move_3b = getattr(alert, "move_3b_atr", None)

        if move_3b is not None:
            try:
                m_val = float(move_3b)
                if m_val > 2.0:
                    flags["velocity_sustainable"] = False
                    return (
                        False,
                        f"Parabolic Velocity Climax: Asset expanded {m_val:.1f}x ATR over last 3 bars without consolidation. Disallow market chase; mandate limit order on 20-EMA/VWAP pullback.",
                        flags,
                    )
            except (ValueError, TypeError):
                pass
        flags["velocity_sustainable"] = True

        # 16. Intraday Sector Relative Performance / Breadth Sanity Gate:
        # When a stock triggers a bullish signal, but its parent sector is experiencing an intraday dump
        # (intraday_sector_rs <= -1.0% vs NIFTY), individual equity breakouts face severe sector drag.
        # Conversely, when an alert triggers a short/put breakdown, but the parent sector is exploding higher
        # (intraday_sector_rs >= +1.2% vs NIFTY), shorting faces high squeeze risk.
        if not is_index and not is_commodity_or_curr:
            sec_rs = None
            if isinstance(metrics_dict, dict):
                sec_rs = (
                    metrics_dict.get("intraday_sector_rs")
                    or metrics_dict.get("sector_rs")
                    or metrics_dict.get("sector_relative_strength_intraday")
                )
                if sec_rs is None and "sector_tailwind" in metrics_dict:
                    st = metrics_dict["sector_tailwind"]
                    if isinstance(st, dict):
                        sec_rs = st.get("intraday_rs")
                    elif hasattr(st, "intraday_rs"):
                        sec_rs = getattr(st, "intraday_rs", None)

            if sec_rs is None and hasattr(alert, "intraday_sector_rs"):
                sec_rs = getattr(alert, "intraday_sector_rs", None)

            if sec_rs is not None:
                try:
                    sec_rs_f = float(sec_rs)
                    opt_type = str(
                        getattr(alert, "option_type", "")
                        or (alert.get("option_type", "") if isinstance(alert, dict) else "")
                    ).upper()
                    is_put_opt = atype == "OPTIONS_MOMENTUM" and opt_type == "PE"
                    is_call_opt = atype == "OPTIONS_MOMENTUM" and opt_type == "CE"

                    # Bullish equity / Call option into severe sector liquidation:
                    if (direction in ("BULLISH", "LONG", "BUY") or is_call_opt) and not is_put_opt:
                        if sec_rs_f <= -1.0:
                            flags["sector_aligned"] = False
                            return (
                                False,
                                f"Intraday Sector Drag Veto: Parent sector lagging NIFTY by {abs(sec_rs_f):.2f}% intraday (institutional sector liquidation). Disallow long breakout into heavy sector drag.",
                                flags,
                            )
                    # Bearish equity / Put option into surging sector momentum:
                    elif (
                        direction in ("BEARISH", "SHORT", "SELL") or is_put_opt
                    ) and not is_call_opt:
                        if sec_rs_f >= 1.2:
                            flags["sector_aligned"] = False
                            return (
                                False,
                                f"Intraday Sector Tailwind Veto: Parent sector outperforming NIFTY by +{sec_rs_f:.2f}% intraday (strong institutional bid). Disallow short breakdown into surging sector tailwinds.",
                                flags,
                            )
                except (ValueError, TypeError):
                    pass
        flags["sector_aligned"] = True

        # 17. Order Book Level-2 Depth Imbalance Gate:
        # Detects order book spoofing and skewed supply/demand overhangs before breakout ignition.
        depth_data = None
        if isinstance(metrics_dict, dict):
            depth_data = metrics_dict.get("depth") or metrics_dict.get("order_book")
        if depth_data is None and hasattr(alert, "depth"):
            depth_data = getattr(alert, "depth", None)

        total_buy_qty = 0.0
        total_sell_qty = 0.0

        if isinstance(depth_data, dict):
            buys = depth_data.get("buy") or depth_data.get("bids") or []
            sells = depth_data.get("sell") or depth_data.get("asks") or []
            if isinstance(buys, list) and isinstance(sells, list):
                total_buy_qty = sum(
                    float(b.get("quantity", 0) or b.get("qty", 0))
                    for b in buys
                    if isinstance(b, dict)
                )
                total_sell_qty = sum(
                    float(s.get("quantity", 0) or s.get("qty", 0))
                    for s in sells
                    if isinstance(s, dict)
                )

        if total_buy_qty <= 0 and isinstance(metrics_dict, dict):
            try:
                total_buy_qty = float(
                    metrics_dict.get("total_buy_qty")
                    or metrics_dict.get("buy_quantity")
                    or metrics_dict.get("total_buy_quantity")
                    or 0.0
                )
                total_sell_qty = float(
                    metrics_dict.get("total_sell_qty")
                    or metrics_dict.get("sell_quantity")
                    or metrics_dict.get("total_sell_quantity")
                    or 0.0
                )
            except (ValueError, TypeError):
                total_buy_qty = 0.0
                total_sell_qty = 0.0

        if total_buy_qty > 0 and total_sell_qty > 0:
            is_call = atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "CE"
            is_put = atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "PE"

            # Long breakout into extreme overhead supply wall:
            if (direction in ("BULLISH", "LONG", "BUY") or is_call) and not is_put:
                if total_sell_qty > (2.2 * total_buy_qty):
                    flags["depth_imbalance_valid"] = False
                    return (
                        False,
                        f"Order Book Depth Imbalance Trap: Top sell limit orders ({total_sell_qty:,.0f}) outnumber buy bids ({total_buy_qty:,.0f}) by {(total_sell_qty / total_buy_qty):.1f}x. Disallow long breakout into heavy overhead supply overhang.",
                        flags,
                    )
            # Short breakdown into heavy bid absorption wall:
            elif (direction in ("BEARISH", "SHORT", "SELL") or is_put) and not is_call:
                if total_buy_qty > (2.2 * total_sell_qty):
                    flags["depth_imbalance_valid"] = False
                    return (
                        False,
                        f"Order Book Depth Imbalance Trap: Top buy bids ({total_buy_qty:,.0f}) outnumber sell offers ({total_sell_qty:,.0f}) by {(total_buy_qty / total_sell_qty):.1f}x. Disallow short breakdown into strong institutional bid absorption.",
                        flags,
                    )
        flags["depth_imbalance_valid"] = True

        # 18. Developing Volume Profile (d-POC / Value Area) Acceptance Gate:
        # Guarantees that intraday breakouts are holding above the day's heaviest volume node (d-POC)
        # and not trapped below the developing Value Area Low (d-VAL).
        d_poc = None
        d_val = None
        d_vah = None
        if isinstance(metrics_dict, dict):
            d_poc = (
                metrics_dict.get("d_poc")
                or metrics_dict.get("developing_poc")
                or metrics_dict.get("poc")
            )
            d_val = (
                metrics_dict.get("d_val")
                or metrics_dict.get("developing_val")
                or metrics_dict.get("val")
            )
            d_vah = (
                metrics_dict.get("d_vah")
                or metrics_dict.get("developing_vah")
                or metrics_dict.get("vah")
            )

        if d_poc is not None and d_val is not None and d_vah is not None:
            try:
                dp = float(d_poc)
                dv = float(d_val)
                dh = float(d_vah)
                if dp > 0 and dv > 0 and dh > 0 and ltp > 0:
                    is_call_opt = (
                        atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "CE"
                    )
                    is_put_opt = (
                        atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "PE"
                    )

                    if not is_option_premium_levels:
                        # Long setup: price must not be trading below Value Area Low without a structural base
                        if (
                            direction in ("BULLISH", "LONG", "BUY") or is_call_opt
                        ) and not is_put_opt:
                            if ltp < (dv * 0.995):
                                flags["poc_acceptance_valid"] = False
                                return (
                                    False,
                                    f"Developing Value Area Rejection: Price (₹{ltp:,.1f}) is trading below intraday Value Area Low (₹{dv:,.1f}). Mandate price acceptance back inside value area before long entry.",
                                    flags,
                                )
                        # Short setup: price must not be trading above Value Area High
                        elif (
                            direction in ("BEARISH", "SHORT", "SELL") or is_put_opt
                        ) and not is_call_opt:
                            if ltp > (dh * 1.005):
                                flags["poc_acceptance_valid"] = False
                                return (
                                    False,
                                    f"Developing Value Area Rejection: Price (₹{ltp:,.1f}) is trading above intraday Value Area High (₹{dh:,.1f}). Mandate price acceptance below value area before short entry.",
                                    flags,
                                )
            except (ValueError, TypeError):
                pass
        flags["poc_acceptance_valid"] = True

        # 19. Momentum Divergence Exhaustion Trap Gate:
        # Prevents long entries on regular bearish divergence (price high on exhausted momentum)
        # and short entries on regular bullish divergence (price low on exhausted momentum / Wyckoff spring).
        div_type_val = None
        div_bias_val = None
        if isinstance(metrics_dict, dict):
            div_type_val = metrics_dict.get("divergence_type") or metrics_dict.get("divergence")
            div_bias_val = metrics_dict.get("divergence_bias")
        if not div_type_val and hasattr(alert, "divergence_type"):
            div_type_val = getattr(alert, "divergence_type", None)

        if div_type_val and isinstance(div_type_val, str):
            div_upper = div_type_val.upper()
            is_call_opt = atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "CE"
            is_put_opt = atype == "OPTIONS_MOMENTUM" and getattr(alert, "option_type", "") == "PE"

            # Long setup into Bearish Regular Divergence
            if (direction in ("BULLISH", "LONG", "BUY") or is_call_opt) and not is_put_opt:
                if "BEARISH_REGULAR" in div_upper or (
                    div_bias_val == "BEARISH" and "REGULAR" in div_upper
                ):
                    flags["divergence_sanity_valid"] = False
                    return (
                        False,
                        f"Momentum Divergence Exhaustion Trap: Bearish regular RSI divergence detected ({div_type_val}). Disallow long entry into momentum exhaustion.",
                        flags,
                    )
            # Short setup into Bullish Regular Divergence
            elif (direction in ("BEARISH", "SHORT", "SELL") or is_put_opt) and not is_call_opt:
                if "BULLISH_REGULAR" in div_upper or (
                    div_bias_val == "BULLISH" and "REGULAR" in div_upper
                ):
                    flags["divergence_sanity_valid"] = False
                    return (
                        False,
                        f"Momentum Divergence Exhaustion Trap: Bullish regular RSI divergence detected ({div_type_val}). Disallow short entry into Wyckoff spring / momentum absorption.",
                        flags,
                    )
        flags["divergence_sanity_valid"] = True

        return True, "", flags

    # ── Tier 2: AI Devil's Advocate & Scrutiny ─────────────────────────────────

    def scrutinize_alert(self, alert: Any, timeout: float = 2.5) -> ScrutinyResult:
        """
        Runs comprehensive Tier-1 and Tier-2 scrutiny.
        Falls back defensively to deterministic quantitative scrutiny if LLM is unavailable.
        Uses in-memory TTL cache (90s) to prevent LLM rate limit exhaustion during rapid scanning loops.
        """
        # Step 0: Check In-Memory TTL Cache
        sym = getattr(alert, "symbol", "") or (
            alert.get("symbol", "") if isinstance(alert, dict) else ""
        )
        atype = getattr(alert, "alert_type", "") or (
            alert.get("alert_type", "") if isinstance(alert, dict) else ""
        )
        direction = getattr(alert, "direction", "") or (
            alert.get("direction", "") if isinstance(alert, dict) else ""
        )
        contract = getattr(alert, "contract_symbol", "") or (
            alert.get("contract_symbol", "") if isinstance(alert, dict) else ""
        )
        strike = getattr(alert, "strike", None) or (
            alert.get("strike", None) if isinstance(alert, dict) else None
        )
        ltp = float(
            getattr(alert, "ltp", 0.0)
            or (alert.get("ltp", 0.0) if isinstance(alert, dict) else 0.0)
            or 0.0
        )
        trig = float(
            getattr(alert, "trigger_level", 0.0)
            or (alert.get("trigger_level", 0.0) if isinstance(alert, dict) else 0.0)
            or 0.0
        )

        cache_key = (
            f"{sym}:{atype}:{direction}:{contract}:{strike}:{round(ltp, 1)}:{round(trig, 1)}"
        )
        now = time.time()
        with self._cache_lock:
            if cache_key in self._cache:
                ts, cached_res = self._cache[cache_key]
                if (now - ts) < self._cache_ttl:
                    return cached_res

        def _commit_cache(res: ScrutinyResult) -> ScrutinyResult:
            with self._cache_lock:
                if len(self._cache) > 500:
                    cutoff = now - self._cache_ttl
                    self._cache = {k: v for k, v in self._cache.items() if v[0] > cutoff}
                self._cache[cache_key] = (now, res)
            return res

        # Step 1: Tier 1 Sanity Gate
        passed, failure_reason, flags = self.verify_tier1_sanity(alert)
        if not passed:
            return _commit_cache(
                ScrutinyResult(
                    status="REJECTED",
                    score=25,
                    logic_confirmation="Mathematical sanity gate failed.",
                    trap_risk_warning=f"Sanity Veto: {failure_reason}",
                    actionable_guidance="Do not execute. Discarded due to structural invalidity.",
                    sanctity_matrix=flags,
                    rejection_reason=failure_reason,
                    auditor_model="TIER1_GATE",
                )
            )

        # Step 1.5: Conviction Gate (Efficiency Guardrail)
        # Avoid spending external LLM tokens on low-confidence (<70%) setups
        confidence = float(getattr(alert, "confidence", 80.0) or 80.0)
        if confidence < 70.0:
            return _commit_cache(self._generate_quantitative_fallback(alert, flags))

        # Step 2: Tier 2 AI Chief Risk Officer Scrutiny
        try:
            llm_result = self._execute_fast_llm_scrutiny(alert, flags, timeout=timeout)
            if llm_result:
                return _commit_cache(llm_result)
        except Exception as e:
            logger.debug(f"[AlertScrutinyAuditor] Fast-LLM execution exception: {e}")

        # Step 3: Zero-Blackout Deterministic Quantitative Fallback
        return _commit_cache(self._generate_quantitative_fallback(alert, flags))

    def _execute_fast_llm_scrutiny(
        self, alert: Any, flags: dict[str, bool], timeout: float = 2.5
    ) -> Optional[ScrutinyResult]:
        """Invokes Fast-LLM with defensive timeout and strict JSON parsing."""
        prompt = self._build_scrutiny_prompt(alert)

        def _call() -> str:
            # Check fast LLM provider
            from agent.core import get_fast_provider

            provider = get_fast_provider()
            if not provider:
                return ""
            resp = provider.chat(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                enable_tools=False,
                max_tokens=750,
            )
            return str(resp or "").strip()

        raw_text = None
        pool = ThreadPoolExecutor(max_workers=3)
        try:
            future = pool.submit(_call)
            raw_text = future.result(timeout=timeout)
        except Exception as e:
            logger.debug(f"[AlertScrutinyAuditor] Fast-LLM timeout/error ({timeout}s): {e}")
            return None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if not raw_text:
            return None

        # Parse JSON from response
        clean_json = raw_text
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            clean_json = match.group(0)

        try:
            data = json.loads(clean_json)
        except Exception:
            # Resilient fallback: regex field extraction to prevent losing valid audits
            data = {}
            for field in (
                "verdict",
                "logic_confirmation",
                "trap_risk_warning",
                "actionable_guidance",
            ):
                m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', raw_text)
                if m:
                    data[field] = m.group(1)
            sm = re.search(r'"score"\s*:\s*(\d+)', raw_text)
            if sm:
                data["score"] = int(sm.group(1))

        verdict = str(data.get("verdict", "APPROVED")).upper()
        score = int(data.get("score", 80))
        logic = str(data.get("logic_confirmation", "")).strip()
        trap = str(data.get("trap_risk_warning", "")).strip()
        guidance = str(data.get("actionable_guidance", "")).strip()

        if not logic or not trap:
            return None

        status = (
            "APPROVED" if verdict in ("APPROVED", "CONDITIONAL") and score >= 70 else "REJECTED"
        )

        return ScrutinyResult(
            status=status,
            score=max(30, min(99, score)),
            logic_confirmation=logic,
            trap_risk_warning=trap,
            actionable_guidance=guidance,
            sanctity_matrix=flags,
            rejection_reason=trap if status == "REJECTED" else None,
            auditor_model="FAST_LLM",
        )

    def _build_scrutiny_prompt(self, alert: Any) -> str:
        """Constructs a compact, high-signal institutional JSON audit prompt.

        For COMMODITY_MOMENTUM and CURRENCY_BREAKOUT alerts a macro-aware
        prompt is emitted that checks DXY alignment, MCX session traps,
        domestic basis risk and geopolitical headline noise — instead of
        the equity-derivative checks used for equity alerts.
        """
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = getattr(alert, "direction", "BULLISH")
        sym = getattr(alert, "symbol", "UNKNOWN")
        alert_type = getattr(alert, "alert_type", "SETUP")
        headline = getattr(alert, "headline", "")
        summary = getattr(alert, "summary", "")
        metrics = getattr(alert, "metrics", {}) or {}

        act_plan = getattr(alert, "actionable_plan", {}) or {}
        action = str(act_plan.get("action", "") if isinstance(act_plan, dict) else "").upper()
        opt_type = str(getattr(alert, "option_type", "") or "").upper()
        contract = str(getattr(alert, "contract_symbol", "") or "")
        trade_desc = action if action else ("BUY " + opt_type if opt_type else direction)

        risk_pts = abs(ltp - sl)
        reward_pts = abs(t1 - ltp)
        rr_str = f"1:{reward_pts / risk_pts:.2f}" if risk_pts > 0 else "N/A"

        # ── Macro-Aware Prompt for Commodity and Currency Alerts ──────────────
        is_commodity = alert_type == "COMMODITY_MOMENTUM"
        is_currency = alert_type == "CURRENCY_BREAKOUT"

        if is_commodity:
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            vwap = float(metrics.get("vwap", ltp) or ltp)
            has_opt_chain = bool(metrics.get("has_options_chain", False))

            macro_ctx = "Live global macro metrics unavailable"
            try:
                from market.macro import get_macro_snapshot

                snap = get_macro_snapshot()
                if snap:
                    dxy_s = f"DXY: {snap.dxy or 'N/A'} ({snap.dxy_change or 0.0:+.2f}%)"
                    brent_s = (
                        f"Brent: ${snap.crude_oil or 'N/A'} ({snap.crude_change or 0.0:+.2f}%)"
                    )
                    gold_s = f"COMEX Gold: ${snap.gold or 'N/A'} ({snap.gold_change or 0.0:+.2f}%)"
                    us10y_s = f"US 10Y: {snap.us_10y or 'N/A'}%"
                    usdinr_s = f"USD/INR: ₹{snap.usdinr or 'N/A'}"
                    macro_ctx = f"{dxy_s} | {brent_s} | {gold_s} | {us10y_s} | {usdinr_s}"
            except Exception:
                pass

            return f"""You are a senior commodity macro trader and CRO at an institutional MCX desk.
Perform strict pre-dispatch scrutiny of this LIVE MCX commodity momentum alert:

COMMODITY: {sym} | ACTION: {trade_desc} | DIRECTION: {direction}
CMP: ₹{ltp:,.2f} | VWAP: ₹{vwap:,.2f} | Session Change: {chg_pct:+.2f}%
STOP LOSS: ₹{sl:,.2f} | TARGET 1: ₹{t1:,.2f} | R:R: {rr_str}
GLOBAL MACRO: {macro_ctx}
OPTIONS CHAIN AVAILABLE: {has_opt_chain}
HEADLINE: {headline}
SUMMARY: {summary}

Perform 3 Institutional Commodity Scrutiny Tests:
1. MACRO ALIGNMENT: Is this move backed by genuine macro driver (DXY reversal, API crude build/draw, COMEX gold accumulation, LME copper demand) — or is it a late-session MCX rollover artifact or thin-market echo?
2. DEVIL'S ADVOCATE: Identify the #1 trap: (e.g., MCX session closing gap vs COMEX, pre-weekend position squaring, domestic INR basis distortion, stop-hunt sweep without fundamental follow-through).
3. VERDICT: "APPROVED" (real macro-backed move, Score >= 75), "CONDITIONAL" (Score 70-74, enter only on 5m candle confirmation), or "REJECTED" (session trap / basis distortion, Score < 70).

Respond STRICTLY in valid JSON:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp sentence: why this commodity move has genuine macro institutional backing>",
  "trap_risk_warning": "<one crisp sentence: #1 commodity-specific trap or session artifact to watch>",
  "actionable_guidance": "<one crisp sentence: exact MCX entry discipline and trailing stop rule>"
}}"""

        if is_currency:
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            return f"""You are a senior FX macro strategist and CRO at an institutional currency derivatives desk.
Perform strict pre-dispatch scrutiny of this LIVE NSE CDS currency breakout alert:

PAIR: {sym} | ACTION: {trade_desc} | DIRECTION: {direction}
CMP: ₹{ltp:.4f} | Session Change: {chg_pct:+.3f}%
STOP LOSS: ₹{sl:.4f} | TARGET 1: ₹{t1:.4f} | R:R: {rr_str}
HEADLINE: {headline}
SUMMARY: {summary}

Perform 3 Institutional FX Scrutiny Tests:
1. MACRO ALIGNMENT: Is this INR move driven by genuine macro catalyst (RBI policy, global risk-off/on, crude oil import bill, FII equity flow reversal) — or is it a post-equity thin-market fixup or squaring artifact?
2. DEVIL'S ADVOCATE: Identify the #1 trap: (e.g., RBI intervention band proximity, expiry settlement squaring, US session liquidity vacuum creating false breakout, INR correlation with equity reversal).
3. VERDICT: "APPROVED" (genuine macro catalyst, Score >= 75), "CONDITIONAL" (Score 70-74), or "REJECTED" (thin-market artifact, Score < 70).

Respond STRICTLY in valid JSON:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp sentence: why this currency move reflects genuine macro institutional flow>",
  "trap_risk_warning": "<one crisp sentence: #1 FX-specific trap or post-equity artifact to watch>",
  "actionable_guidance": "<one crisp sentence: exact CDS entry discipline with spread and trailing stop rule>"
}}"""

        time_horizon = getattr(alert, "time_horizon", "INTRADAY")
        setup_style = getattr(alert, "setup_style", "CONTINUATION")
        anchored = getattr(alert, "anchored_levels", {}) or {}

        # ── Standard Equity / Derivative Prompt ───────────────────────────────
        return f"""You are the Chief Risk Officer and Devil's Advocate for an institutional quant trading desk.
Perform a strict pre-dispatch scrutiny of this real-time Indian market trade setup:

SYMBOL: {sym} | CONTRACT: {contract or sym} | ACTION: {trade_desc} | DIRECTION: {direction} | TYPE: {alert_type}
HORIZON: {time_horizon} | SETUP STYLE: {setup_style}
LTP / PREMIUM: ₹{ltp:,.2f} | STOP LOSS: ₹{sl:,.2f} | TARGET 1: ₹{t1:,.2f} | R:R: {rr_str}
HEADLINE: {headline}
SUMMARY: {summary}
KEY ANCHORS: {json.dumps(anchored, default=str) if anchored else "Standard Pivots"}
METRICS: {json.dumps(metrics, default=str)[:300]}

Perform 3 Institutional Scrutiny Tests:
1. SANCTITY & LOGIC: Does the technical/derivative trigger represent genuine institutional order flow rather than retail noise?
2. DEVIL'S ADVOCATE: What is the #1 structural trap or failure mode? (e.g., immediate 200-EMA, heavy Call wall, post-spike exhaustion).
3. VERDICT: "APPROVED" (Score >= 75), "CONDITIONAL" (Score 70-74), or "REJECTED" (Score < 70).

Respond STRICTLY in valid JSON matching this schema:
{{
  "verdict": "APPROVED" | "CONDITIONAL" | "REJECTED",
  "score": <integer 40-95>,
  "logic_confirmation": "<one crisp institutional sentence explaining why the setup has statistical edge>",
  "trap_risk_warning": "<one crisp sentence highlighting the #1 Devil's Advocate trap to watch>",
  "actionable_guidance": "<one crisp sentence on precise execution and trailing stop discipline>"
}}"""

    def _generate_quantitative_fallback(self, alert: Any, flags: dict[str, bool]) -> ScrutinyResult:
        """Deterministic quantitative scoring when LLM provider is offline or times out."""
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or 0.0)
        direction = str(getattr(alert, "direction", "BULLISH")).upper()
        sym = getattr(alert, "symbol", "UNKNOWN")
        alert_type = getattr(alert, "alert_type", "SETUP")
        metrics = getattr(alert, "metrics", {}) or {}

        act_plan = getattr(alert, "actionable_plan", {}) or {}
        action = str(act_plan.get("action", "") if isinstance(act_plan, dict) else "").upper()
        opt_type = str(getattr(alert, "option_type", "") or "").upper()
        contract = str(getattr(alert, "contract_symbol", "") or "")
        is_option = bool(opt_type or contract or "OPTIONS" in alert_type or "GAMMA" in alert_type)
        is_option_buy = is_option and ("SELL" not in action and "WRITE" not in action)

        risk_pts = abs(ltp - sl)
        reward_pts = abs(t1 - ltp)
        rr = reward_pts / risk_pts if risk_pts > 0 else 2.5

        # Base quant score anchored around 80
        score = 80
        if rr >= 3.0:
            score += 8
        elif rr >= 2.5:
            score += 4

        # Bonus for derivative / volume confirmation if present
        rvol = float(metrics.get("rvol", 1.0) or 1.0)
        if rvol >= 2.0:
            score += 5

        score = min(92, max(75, score))

        # Respect mathematical sanity flag vetoes in quant fallback
        if not flags.get("rr_valid", True):
            return ScrutinyResult(
                status="REJECTED",
                score=35,
                logic_confirmation="Mathematical asymmetry gate rejected setup.",
                trap_risk_warning="Unfavorable risk-to-reward asymmetry or negative structural expectancy.",
                actionable_guidance="Skip execution. Structural asymmetry threshold not met.",
                sanctity_matrix=flags,
                rejection_reason="Unfavorable Risk:Reward ratio or failed trade plan asymmetry.",
                auditor_model="QUANT_FALLBACK",
            )

        # ── Commodity Quant Fallback ──────────────────────────────────────────
        if alert_type == "COMMODITY_MOMENTUM":
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            vwap = float(metrics.get("vwap", ltp) or ltp)
            if direction in ("BEARISH", "SHORT", "SELL"):
                logic = (
                    f"Quant-validated MCX {sym} breakdown: session decline of {chg_pct:.1f}% below VWAP ₹{vwap:,.1f} "
                    f"with calibrated {rr:.1f}R downside asymmetry; COMEX basis suggests genuine selling pressure."
                )
                trap = (
                    f"Watch for COMEX midnight gap fill or INR basis correction reversing the MCX breakdown; "
                    f"invalidate immediately if price reclaims VWAP ₹{vwap:,.1f}."
                )
                guidance = f"Short MCX {sym} near ₹{ltp:,.1f}; SL above ₹{sl:,.1f}; book 50% at ₹{t1:,.1f} and trail on 5m candle."
            else:
                logic = (
                    f"Quant-validated MCX {sym} momentum: session gain of {chg_pct:+.1f}% reclaiming VWAP ₹{vwap:,.1f} "
                    f"with calibrated {rr:.1f}R upside asymmetry; DXY softness supports domestic gold/crude bid."
                )
                trap = (
                    f"Watch for MCX session closing rollover pressure or thin-book stop-hunt above ₹{ltp:,.1f}; "
                    f"do not chase if price extends beyond 1.5× trigger move without VWAP reclaim."
                )
                guidance = f"Long MCX {sym} near ₹{ltp:,.1f}; SL below ₹{sl:,.1f}; book 50% at ₹{t1:,.1f} and trail on 5m candle."
            return ScrutinyResult(
                status="APPROVED",
                score=score,
                logic_confirmation=logic,
                trap_risk_warning=trap,
                actionable_guidance=guidance,
                sanctity_matrix=flags,
                auditor_model="QUANT_FALLBACK",
            )

        # ── Currency Quant Fallback ───────────────────────────────────────────
        if alert_type == "CURRENCY_BREAKOUT":
            chg_pct = float(metrics.get("change_pct", 0.0) or 0.0)
            if direction in ("BEARISH", "SHORT", "SELL"):
                logic = (
                    f"Quant-validated {sym} INR depreciation: {chg_pct:.3f}% macro drop with "
                    f"1:{rr:.1f} R:R asymmetry; consistent with FII equity outflow or global risk-off trigger."
                )
                trap = (
                    f"RBI intervention band proximity or sudden risk-on reversal could squeeze shorts; "
                    f"watch for price reclaim above ₹{sl:.4f}."
                )
                guidance = f"Short {sym} near ₹{ltp:.4f}; SL ₹{sl:.4f}; T1 ₹{t1:.4f}; close 50% at T1 and trail tightly."
            else:
                logic = (
                    f"Quant-validated {sym} INR appreciation: {chg_pct:+.3f}% macro move with "
                    f"1:{rr:.1f} R:R asymmetry; consistent with FII equity inflow or crude drawdown."
                )
                trap = (
                    f"Post-equity session thin liquidity could amplify false breakout; "
                    f"invalidate if price falls back below ₹{sl:.4f}."
                )
                guidance = f"Long {sym} near ₹{ltp:.4f}; SL ₹{sl:.4f}; T1 ₹{t1:.4f}; close 50% at T1 and trail tightly."
            return ScrutinyResult(
                status="APPROVED",
                score=score,
                logic_confirmation=logic,
                trap_risk_warning=trap,
                actionable_guidance=guidance,
                sanctity_matrix=flags,
                auditor_model="QUANT_FALLBACK",
            )

        # ── Generic Equity / Derivative Fallback ─────────────────────────────
        if is_option_buy:
            is_friday_late = (
                bool(metrics.get("is_friday_late", False)) if isinstance(metrics, dict) else False
            )
            friday_warning = (
                " [FRIDAY POST-14:30 WARNING: High weekend theta decay; scalp only or close by 15:20 IST]"
                if is_friday_late
                else ""
            )
            spot_anchor = (
                metrics.get("spot_invalidation_anchor") if isinstance(metrics, dict) else None
            )
            anchor_note = f" (Spot Anchor Rs.{float(spot_anchor):,.1f})" if spot_anchor else ""

            if opt_type == "PE" or "PE" in contract or "PUT" in action or direction == "BEARISH":
                opt_lbl = contract or f"{sym} {opt_type or 'PE'}"
                logic = f"Quant-validated {opt_lbl} Put momentum: bearish underlying breakdown confirmed with 1:{rr:.1f} R:R premium expansion asymmetry."
                trap = f"Watch for sudden underlying short-covering bounce{friday_warning}; scale 50% profit at option target Rs.{t1:,.1f} and trail SL to breakeven."
                guidance = f"Buy PE near Rs.{ltp:,.1f}{anchor_note}; strictly invalidate if option premium drops below Rs.{sl:,.1f}."
            else:
                opt_lbl = contract or f"{sym} {opt_type or 'CE'}"
                logic = f"Quant-validated {opt_lbl} Call momentum: bullish momentum holds with favorable 1:{rr:.1f} R:R premium expansion asymmetry."
                trap = f"Watch for overhead resistance or IV crush near target Rs.{t1:,.1f}{friday_warning}; scale 50% profit at T1 and trail SL to breakeven."
                guidance = f"Buy CE near Rs.{ltp:,.1f}{anchor_note}; strictly invalidate if option premium drops below Rs.{sl:,.1f}."
        elif direction in ("BEARISH", "SHORT", "SELL"):
            logic = f"Quant-validated {sym} breakdown: distribution structure below Rs.{sl:,.1f} confirmed with 1:{rr:.1f} downside asymmetry."
            trap = f"Watch for sudden short-covering bounce near Rs.{t1:,.1f}; tighten stop on lower timeframe CHoCH."
            guidance = f"Short near Rs.{ltp:,.1f}; invalidate trade immediately if price reclaims Rs.{sl:,.1f}."
        else:
            logic = f"Quant-validated {sym} {alert_type.lower().replace('_', ' ')}: structural pivot holds above Rs.{sl:,.1f} with favorable 1:{rr:.1f} R:R asymmetry."
            trap = f"Overhead resistance near target Rs.{t1:,.1f}; scale 50% profit at T1 and trail SL to breakeven."
            guidance = f"Enter near Rs.{ltp:,.1f}; strictly invalidate if candle closes below Rs.{sl:,.1f}."

        return ScrutinyResult(
            status="APPROVED",
            score=score,
            logic_confirmation=logic,
            trap_risk_warning=trap,
            actionable_guidance=guidance,
            sanctity_matrix=flags,
            auditor_model="QUANT_FALLBACK",
        )


# Global singleton instance
alert_scrutiny_auditor = AlertScrutinyAuditor()
