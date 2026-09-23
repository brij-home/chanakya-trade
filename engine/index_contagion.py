"""
engine/index_contagion.py
─────────────────────────
Index Heavyweight Lead-Lag Contagion & Constituent Synchronization Engine.

Continuously monitors top weighted constituents of NIFTY 50 and BANKNIFTY:
  - BANKNIFTY: HDFCBANK (~28%), ICICIBANK (~24%), SBIN (~10%), AXISBANK (~9%), KOTAKBANK (~9%)
  - NIFTY 50: HDFCBANK (~11%), RELIANCE (~9.5%), ICICIBANK (~8%), INFY (~5.5%), TCS (~4%), LT (~3.8%), SBIN (~3%), BHARTIARTL (~3.5%)

When >= 70% of constituent weighting synchronizes directionally (reclaiming VWAP,
surging on Time-of-Day RVOL, and pressing Day Highs), fires an institutional
early-warning alert for the parent index 60-120 seconds *before* the index spot confirms.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert

logger = logging.getLogger("engine.index_contagion")
IST = ZoneInfo("Asia/Kolkata")

# ── Institutional Constituent Weightings (Active 2026) ───────────────────────

INDEX_CONSTITUENTS: dict[str, dict[str, float]] = {
    "BANKNIFTY": {
        "HDFCBANK": 0.285,
        "ICICIBANK": 0.240,
        "SBIN": 0.102,
        "AXISBANK": 0.092,
        "KOTAKBANK": 0.088,
    },
    "NIFTY": {
        "HDFCBANK": 0.112,
        "RELIANCE": 0.096,
        "ICICIBANK": 0.081,
        "INFY": 0.054,
        "TCS": 0.040,
        "LT": 0.038,
        "BHARTIARTL": 0.035,
        "SBIN": 0.030,
    },
    "FINNIFTY": {
        "HDFCBANK": 0.280,
        "ICICIBANK": 0.220,
        "BAJFINANCE": 0.095,
        "SBIN": 0.075,
        "AXISBANK": 0.070,
        "KOTAKBANK": 0.065,
    },
}


@dataclass
class ConstituentStatus:
    symbol: str
    weight: float
    ltp: float
    change_pct: float
    vwap: float
    is_above_vwap: bool
    tod_rvol: float
    dist_from_high_pct: float
    dist_from_low_pct: float
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    score: float  # -3.0 to +3.0


@dataclass
class IndexContagionResult:
    index_name: str
    spot: float
    vwap: float
    change_pct: float
    bullish_weight_pct: float
    bearish_weight_pct: float
    net_impulse_score: float
    leading_constituents: list[str] = field(default_factory=list)
    alert: Optional[AutoAlert] = None


class IndexContagionEngine:
    """
    Evaluates institutional constituent synchronization for major Indian indices.
    """

    def __init__(self) -> None:
        self._cooldowns: dict[str, float] = {}
        self._cooldown_ttl = 600.0  # 10 minutes between duplicate contagion alerts

    def evaluate_index(
        self,
        index_name: str,
        quotes_map: Optional[dict[str, Any]] = None,
        ref_dt: Optional[datetime] = None,
    ) -> Optional[IndexContagionResult]:
        """
        Evaluates constituent synchronization for a specific index.
        """
        clean_idx = index_name.upper().replace("NSE:", "").strip()
        weights = INDEX_CONSTITUENTS.get(clean_idx)
        if not weights:
            return None

        from market.quotes import get_quote, get_ltp
        from engine.auto_alert_engine import compute_time_of_day_rvol

        now_dt = ref_dt or datetime.now(IST)
        now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        # 1. Resolve index quote
        idx_sym = f"NSE:{clean_idx}"
        symbols_to_fetch = [idx_sym] + [f"NSE:{s}" for s in weights.keys()]

        if not quotes_map:
            try:
                quotes_map = get_quote(symbols_to_fetch)
            except Exception as e:
                logger.debug(f"[IndexContagion] Failed to fetch quotes: {e}")
                return None

        idx_q = quotes_map.get(idx_sym) or quotes_map.get(clean_idx)
        idx_ltp = float(getattr(idx_q, "last_price", 0.0) or getattr(idx_q, "ltp", 0.0) or 0.0)
        if idx_ltp <= 0:
            idx_ltp = get_ltp(idx_sym) or get_ltp(clean_idx)
        if idx_ltp <= 0:
            return None

        idx_vwap = float(getattr(idx_q, "vwap", 0.0) or idx_ltp)
        idx_chg = float(getattr(idx_q, "change_pct", 0.0) or 0.0)

        # 2. Evaluate each constituent
        total_tracked_weight = sum(weights.values())
        bullish_weight = 0.0
        bearish_weight = 0.0
        weighted_impulse = 0.0
        leading_bulls: list[str] = []
        leading_bears: list[str] = []

        for sym, weight in weights.items():
            q = quotes_map.get(f"NSE:{sym}") or quotes_map.get(sym)
            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            if ltp <= 0:
                continue

            vwap = float(getattr(q, "vwap", 0.0) or ltp)
            chg = float(getattr(q, "change_pct", 0.0) or 0.0)
            vol = int(getattr(q, "volume", 0) or 0)
            day_high = float(getattr(q, "high", 0.0) or ltp)
            day_low = float(getattr(q, "low", 0.0) or ltp)

            # 20D average volume fallback (standard 5M shares for big banks, 3M for Reliance/Infy)
            avg_daily_vol = 5_000_000.0 if "BANK" in sym else 3_000_000.0
            rvol = compute_time_of_day_rvol(vol, avg_daily_vol, ref_dt=now_dt)

            dist_from_high = max(0.0, (day_high - ltp) / max(1.0, day_high) * 100.0)
            dist_from_low = max(0.0, (ltp - day_low) / max(1.0, day_low) * 100.0)

            # Score logic:
            # Bullish impulse: Above VWAP, positive change, near day high, active RVOL
            c_score = 0.0
            is_above_vwap = ltp >= (vwap * 0.999)
            is_below_vwap = ltp <= (vwap * 1.001)

            # Institutional impulse bar:
            # Minimum 0.40% move required, OR 0.25% if confirmed by active volume (RVOL >= 1.2x).
            # Flat sub-0.35% noise with zero volume is disqualified from triggering contagion.
            is_bull_impulse = is_above_vwap and (chg >= 0.40 or (chg >= 0.25 and rvol >= 1.2))
            is_bear_impulse = is_below_vwap and (chg <= -0.40 or (chg <= -0.25 and rvol >= 1.2))

            if is_bull_impulse:
                c_score += 1.0
                if chg >= 0.70:
                    c_score += 1.0
                if dist_from_high <= 0.35:
                    c_score += 0.5
                if rvol >= 1.2:
                    c_score += 0.5
                bullish_weight += weight
                rvol_tag = f", RVOL {rvol:.1f}x" if vol > 0 else ""
                leading_bulls.append(f"{sym} (+{chg:.1f}%{rvol_tag})")
            elif is_bear_impulse:
                c_score -= 1.0
                if chg <= -0.70:
                    c_score -= 1.0
                if dist_from_low <= 0.35:
                    c_score += 0.5
                if rvol >= 1.2:
                    c_score += 0.5
                bearish_weight += weight
                rvol_tag = f", RVOL {rvol:.1f}x" if vol > 0 else ""
                leading_bears.append(f"{sym} ({chg:.1f}%{rvol_tag})")

            weighted_impulse += c_score * weight

        bullish_pct = round((bullish_weight / total_tracked_weight) * 100.0, 1)
        bearish_pct = round((bearish_weight / total_tracked_weight) * 100.0, 1)
        net_score = round(weighted_impulse / total_tracked_weight, 2)

        result = IndexContagionResult(
            index_name=clean_idx,
            spot=idx_ltp,
            vwap=idx_vwap,
            change_pct=idx_chg,
            bullish_weight_pct=bullish_pct,
            bearish_weight_pct=bearish_pct,
            net_impulse_score=net_score,
            leading_constituents=leading_bulls if bullish_pct >= bearish_pct else leading_bears,
        )

        # 3. Generate Alert if Synchronization threshold (>= 68% weight) is met
        # AND Index spot is directionally aligned with VWAP (not sitting dead-flat at VWAP)
        # For Bullish: spot must hold above VWAP (>= vwap * 1.0003) or index change >= +0.10%
        # For Bearish: spot must hold below VWAP (<= vwap * 0.9997) or index change <= -0.10%
        alert = None
        is_index_bull_active = idx_ltp >= (idx_vwap * 1.0003) or idx_chg >= 0.10
        is_index_bear_active = idx_ltp <= (idx_vwap * 0.9997) or idx_chg <= -0.10

        if bullish_pct >= 68.0 and net_score >= 1.2 and is_index_bull_active:
            alert = self._create_contagion_alert(
                index_name=clean_idx,
                direction="BULLISH",
                spot=idx_ltp,
                vwap=idx_vwap,
                change_pct=idx_chg,
                sync_pct=bullish_pct,
                leading=leading_bulls,
                now_iso=now_iso,
            )
        elif bearish_pct >= 68.0 and net_score <= -1.2 and is_index_bear_active:
            alert = self._create_contagion_alert(
                index_name=clean_idx,
                direction="BEARISH",
                spot=idx_ltp,
                vwap=idx_vwap,
                change_pct=idx_chg,
                sync_pct=bearish_pct,
                leading=leading_bears,
                now_iso=now_iso,
            )

        result.alert = alert
        return result

    def _create_contagion_alert(
        self,
        index_name: str,
        direction: str,
        spot: float,
        vwap: float,
        change_pct: float,
        sync_pct: float,
        leading: list[str],
        now_iso: str,
    ) -> Optional[AutoAlert]:
        """Creates an early-warning institutional contagion alert."""
        from engine.trade_plan import calculate_trade_plan

        is_bull = direction == "BULLISH"
        act_dir = "BUY" if is_bull else "SELL"

        tp = None
        try:
            tp = calculate_trade_plan(
                symbol=index_name,
                direction=act_dir,
                spot=spot,
                timeframe="INTRADAY",
                exchange="NFO",
                has_active_blast=True,
            )
        except Exception as e_tp:
            logger.debug(f"[IndexContagion] Trade plan failed: {e_tp}")

        if tp and tp.is_asymmetry_viable:
            sl = tp.invalidation_stop
            t1 = tp.target_1
            t2 = tp.target_2
            t3 = tp.target_3
            rr_str = f"1:{tp.rr_t1}"
            tp_dict = tp.as_dict()
        else:
            # High-precision ATR anchor for indices (BankNifty ~140 pts, Nifty ~60 pts)
            risk_pts = 140.0 if "BANK" in index_name else 60.0
            if is_bull:
                sl = round(max(vwap * 0.998, spot - risk_pts), 1)
                t1 = round(spot + 1.8 * risk_pts, 1)
                t2 = round(spot + 3.0 * risk_pts, 1)
                t3 = round(spot + 4.5 * risk_pts, 1)
            else:
                sl = round(min(vwap * 1.002, spot + risk_pts), 1)
                t1 = round(spot - 1.8 * risk_pts, 1)
                t2 = round(spot - 3.0 * risk_pts, 1)
                t3 = round(spot - 4.5 * risk_pts, 1)
            rr_str = "1:2.2"
            tp_dict = None

        leaders_str = ", ".join(leading[:3]) if leading else "Core heavyweights"
        tag = "🚀 HEAVYWEIGHT CONTAGION" if is_bull else "🔻 HEAVYWEIGHT BREAKDOWN"

        # Resolve live ATM Option Contract for the index
        opt_type = "CE" if is_bull else "PE"
        atm_contract = None
        opt_plan = None
        opt_ltp = None
        opt_strike = None
        opt_contract_sym = None
        opt_expiry = None
        opt_sl = None
        opt_t1 = None
        opt_t2 = None
        opt_t3 = None
        try:
            from market.options import get_options_chain
            from engine.position_sizer import get_lot_size
            from engine.trade_plan import calculate_option_execution_plan

            chain = get_options_chain(index_name)
            if chain:
                # Institutional ATM Proximity Gate:
                # Strike must be within 2.0% of index spot (typically within 150-500 pts for 20k-25k indices).
                # Rejects strikes that are 1000-2000 points OTM (which Zerodha and exchange RMS reject).
                max_allowed_dist_pct = 0.020
                matching = [
                    c
                    for c in chain
                    if getattr(c, "option_type", "") == opt_type
                    and float(getattr(c, "last_price", 0.0) or 0.0) > 0
                    and (abs(float(getattr(c, "strike", 0.0)) - spot) / max(1.0, spot))
                    <= max_allowed_dist_pct
                ]
                # Prioritize liquid contracts with open interest or volume if available
                liquid_matching = [
                    c
                    for c in matching
                    if int(getattr(c, "oi", 0) or 0) > 0 or int(getattr(c, "volume", 0) or 0) > 0
                ]
                chosen_pool = liquid_matching if liquid_matching else matching
                if chosen_pool:
                    chosen_pool.sort(key=lambda c: abs(float(getattr(c, "strike", 0.0)) - spot))
                    atm_contract = chosen_pool[0]
                    opt_ltp = float(atm_contract.last_price)
                    opt_strike = float(atm_contract.strike)
                    opt_contract_sym = atm_contract.symbol
                    opt_expiry = getattr(atm_contract, "expiry", None)
                    lot_sz = get_lot_size(index_name)
                    if tp and getattr(tp, "invalidation_stop", 0) > 0:
                        opt_plan = calculate_option_execution_plan(
                            trade_plan=tp,
                            option_type=opt_type,
                            strike=opt_strike,
                            expiry=str(opt_expiry) if opt_expiry else "",
                            option_ltp=opt_ltp,
                            lot_size=lot_sz or 15,
                        )
                        if opt_plan and opt_plan.get("sl_premium"):
                            opt_sl = float(opt_plan["sl_premium"])
                            opt_t1 = float(opt_plan.get("t1_premium") or round(opt_ltp * 1.25, 2))
                            opt_t2 = float(opt_plan.get("t2_premium") or round(opt_ltp * 1.45, 2))
                            opt_t3 = float(opt_plan.get("t3_premium") or round(opt_ltp * 1.75, 2))
                            rr_str = str(opt_plan.get("option_rr") or rr_str)
                    if not opt_sl:
                        opt_sl = round(max(0.05, opt_ltp * 0.85), 2)
                        opt_t1 = round(opt_ltp * 1.25, 2)
                        opt_t2 = round(opt_ltp * 1.45, 2)
                        opt_t3 = round(opt_ltp * 1.75, 2)
        except Exception as e_opt:
            logger.debug(f"[IndexContagion] Option resolution failed for {index_name}: {e_opt}")

        if opt_ltp and opt_contract_sym:
            headline = (
                f"{tag}: {opt_contract_sym} @ ₹{opt_ltp:,.1f} ({sync_pct:.0f}% Weight {direction})"
            )
            summary = (
                f"Institutional {index_name} constituent synchronization ({sync_pct:.0f}% aligned). "
                f"ATM Option: {opt_contract_sym} @ ₹{opt_ltp:,.1f} (SL ₹{opt_sl:,.1f} | T1 ₹{opt_t1:,.1f}). "
                f"Leaders: {leaders_str}. Index spot at ₹{spot:,.1f} (VWAP ₹{vwap:,.1f})."
            )
            alert_ltp = opt_ltp
            alert_sl = opt_sl
            alert_t1 = opt_t1
            entry_range_str = f"₹{round(opt_ltp * 0.98, 1):,.1f} – ₹{round(opt_ltp * 1.02, 1):,.1f}"
            when_to_buy_str = f"Buy {opt_contract_sym} on limit/ask while {index_name} spot holds above ₹{vwap:,.1f}."
        else:
            # Estimate ATM strike from index spot (50 pt step for NIFTY, 100 pt for BANKNIFTY/SENSEX)
            step = 100 if index_name in ("BANKNIFTY", "SENSEX", "BANKEX") else 50
            est_strike = round(spot / step) * step
            est_premium = round(max(20.0, spot * 0.0065), 1)
            est_sl = round(est_premium * 0.82, 1)
            est_t1 = round(est_premium * 1.35, 1)
            est_t2 = round(est_premium * 1.70, 1)
            est_t3 = round(est_premium * 2.10, 1)
            opt_contract_sym = f"{index_name} {int(est_strike)} {opt_type}"
            opt_ltp = est_premium
            opt_sl = est_sl
            opt_t1 = est_t1
            opt_t2 = est_t2
            opt_t3 = est_t3
            opt_strike = est_strike
            headline = (
                f"{tag}: {opt_contract_sym} ~₹{opt_ltp:,.1f} ({sync_pct:.0f}% Weight {direction})"
            )
            summary = (
                f"Institutional {index_name} constituent synchronization ({sync_pct:.0f}% aligned). "
                f"ATM Option: {opt_contract_sym} ~₹{opt_ltp:,.1f} (SL ₹{opt_sl:,.1f} | T1 ₹{opt_t1:,.1f}). "
                f"Leaders: {leaders_str}. Index spot at ₹{spot:,.1f} (VWAP ₹{vwap:,.1f})."
            )
            alert_ltp = opt_ltp
            alert_sl = opt_sl
            alert_t1 = opt_t1
            entry_range_str = f"₹{round(opt_ltp * 0.96, 1):,.1f} – ₹{round(opt_ltp * 1.04, 1):,.1f}"
            when_to_buy_str = f"Buy {opt_contract_sym} on ask while {index_name} spot holds above ₹{vwap:,.1f} (Spot SL: ₹{sl:,.1f})."

        # Calibrated institutional confidence scoring (0 - 95%)
        # Base: 60 pts
        # + Synchronization contribution (up to 16 pts): sync_pct * 0.16
        # + Leader impulse strength: average move of leaders >= 0.8% gets +10 pts, >= 0.5% gets +5 pts
        # + Volume confirmation: +5 pts if active RVOL observed in leaders
        # + Index trend: +4 pts if spot clearly extended from VWAP (>0.15%)
        conf_score = 60.0 + (sync_pct * 0.16)

        # Evaluate leader magnitude
        import re

        leader_chgs = []
        for l_str in leading:
            m = re.search(r"([+-]?\d+\.?\d*)%", l_str)
            if m:
                try:
                    leader_chgs.append(abs(float(m.group(1))))
                except Exception:
                    pass
        avg_lead_chg = (sum(leader_chgs) / len(leader_chgs)) if leader_chgs else 0.0
        if avg_lead_chg >= 0.8:
            conf_score += 10.0
        elif avg_lead_chg >= 0.5:
            conf_score += 5.0

        # Volume confirmation
        has_active_rvol = any("RVOL" in l_str for l_str in leading)
        if has_active_rvol:
            conf_score += 5.0

        # VWAP trend separation
        vwap_dist_pct = abs(spot - vwap) / max(1.0, vwap) * 100.0
        if vwap_dist_pct >= 0.15:
            conf_score += 4.0

        final_conf = min(95, max(65, int(conf_score)))

        return AutoAlert(
            alert_id=f"aa-contagion-{index_name.lower()}-{uuid.uuid4().hex[:6]}",
            alert_type="INDEX_CONTAGION",
            stage="EARLY_WARNING",
            symbol=index_name,
            exchange="NFO",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=alert_ltp,
            trigger_level=alert_ltp,
            target_level=alert_t1,
            stop_loss=alert_sl,
            strike=opt_strike,
            option_type=opt_type if opt_strike else None,
            contract_symbol=opt_contract_sym,
            expiry_date=opt_expiry,
            option_premium=opt_ltp,
            underlying_spot=spot,
            segment="FNO_INDEX",
            metrics={
                "sync_pct": sync_pct,
                "direction": direction,
                "leaders": leading[:4],
                "vwap": round(vwap, 1),
                "change_pct": round(change_pct, 2),
                "option_contract": opt_contract_sym,
                "option_premium": opt_ltp,
            },
            actionable_plan={
                "action": f"BUY {opt_type}",
                "instrument": opt_contract_sym,
                "instrument_type": "OPTION",
                "segment": "FNO_INDEX",
                "contract": opt_contract_sym,
                "strike": opt_strike,
                "option_type": opt_type,
                "recommended_entry": f"₹{alert_ltp:,.2f}",
                "entry_range": entry_range_str,
                "stop_loss": f"₹{alert_sl:,.1f}",
                "target": f"₹{alert_t1:,.1f}",
                "target_1": f"₹{alert_t1:,.1f}",
                "target_2": f"₹{opt_t2:,.1f}" if opt_t2 else f"₹{round(alert_t1 * 1.3, 1):,.1f}",
                "target_3": f"₹{opt_t3:,.1f}" if opt_t3 else f"₹{round(alert_t1 * 1.6, 1):,.1f}",
                "underlying_spot": f"₹{spot:,.1f}",
                "underlying_sl": f"₹{sl:,.1f}",
                "underlying_target": f"₹{t1:,.1f}",
                "underlying_target_2": f"₹{t2:,.1f}" if t2 else None,
                "underlying_target_3": f"₹{t3:,.1f}" if t3 else None,
                "risk_reward": rr_str,
                "trade_plan": tp_dict,
                "option_plan": opt_plan,
                "when_to_buy": when_to_buy_str,
                "when_to_wait": "Do not chase if spot extends > 0.6% from VWAP without retest",
                "profit_rule": "Scale 50% at T1, move SL to breakeven, trail runner on 5m 20-EMA.",
            },
            confidence=final_conf,
            created_at=now_iso,
        )


index_contagion_engine = IndexContagionEngine()
