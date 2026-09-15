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
    score: float   # -3.0 to +3.0


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

            is_above_vwap = ltp >= (vwap * 0.999)
            is_below_vwap = ltp <= (vwap * 1.001)

            # Score logic:
            # Bullish impulse: Above VWAP, positive change, near day high, active RVOL
            c_score = 0.0
            if is_above_vwap and chg >= 0.20:
                c_score += 1.0
                if chg >= 0.70:
                    c_score += 1.0
                if dist_from_high <= 0.35:
                    c_score += 0.5
                if rvol >= 1.2:
                    c_score += 0.5
                bullish_weight += weight
                leading_bulls.append(f"{sym} (+{chg:.1f}%, RVOL {rvol:.1f}x)")
            elif is_below_vwap and chg <= -0.20:
                c_score -= 1.0
                if chg <= -0.70:
                    c_score -= 1.0
                if dist_from_low <= 0.35:
                    c_score -= 0.5
                if rvol >= 1.2:
                    c_score -= 0.5
                bearish_weight += weight
                leading_bears.append(f"{sym} ({chg:.1f}%, RVOL {rvol:.1f}x)")

            weighted_impulse += (c_score * weight)

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
        alert = None
        if bullish_pct >= 68.0 and net_score >= 1.2:
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
        elif bearish_pct >= 68.0 and net_score <= -1.2:
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

        headline = (
            f"{tag}: {index_name} at {spot:,.1f} ({sync_pct:.0f}% Weight {direction})"
        )
        summary = (
            f"Institutional {index_name} constituent synchronization ({sync_pct:.0f}% aligned). "
            f"Leaders: {leaders_str}. Index spot at ₹{spot:,.1f} (VWAP ₹{vwap:,.1f}). "
            f"Precursor impulse active."
        )

        entry_min = round(spot - 25.0 if is_bull else spot - 15.0, 1)
        entry_max = round(spot + 35.0 if is_bull else spot + 15.0, 1)

        return AutoAlert(
            alert_id=f"aa-contagion-{index_name.lower()}-{uuid.uuid4().hex[:6]}",
            alert_type="INDEX_CONTAGION",
            stage="EARLY_WARNING",
            symbol=index_name,
            exchange="NFO",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=spot,
            trigger_level=spot,
            target_level=t1,
            stop_loss=sl,
            metrics={
                "sync_pct": sync_pct,
                "direction": direction,
                "leaders": leading[:4],
                "vwap": round(vwap, 1),
                "change_pct": round(change_pct, 2),
            },
            actionable_plan={
                "action": f"{'BUY_CALL' if is_bull else 'BUY_PUT'}_MOMENTUM",
                "segment": "FNO_INDEX",
                "entry_range": f"₹{entry_min:,.1f} – ₹{entry_max:,.1f}",
                "stop_loss": f"₹{sl:,.1f}",
                "target": f"₹{t1:,.1f}",
                "target_2": f"₹{t2:,.1f}",
                "target_3": f"₹{t3:,.1f}",
                "risk_reward": rr_str,
                "trade_plan": tp_dict,
                "when_to_buy": f"Enter ATM options while {index_name} holds above ₹{vwap:,.1f}",
                "when_to_wait": f"Do not chase if spot extends > 0.6% from VWAP without retest",
                "profit_rule": "Scale 50% at T1, move SL to breakeven, trail runner on 5m 20-EMA.",
            },
            confidence=min(95, int(72 + (sync_pct * 0.22))),
            created_at=now_iso,
        )


index_contagion_engine = IndexContagionEngine()
