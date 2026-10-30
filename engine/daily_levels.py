"""
engine/daily_levels.py
──────────────────────
Centralized Pre-Market & Daily Reference Levels Engine.

Computes, maintains in memory (L1), and persists daily (L2) institutional
reference levels for Indian Markets (Indices & Equities):
  1. Previous Day Levels: PDH, PDL, PDC, PDO, ATR-14.
  2. Central Pivot Range (CPR): Pivot, TC, BC, Top, Bottom, Width %,
     Regime classification (NARROW_CPR, WIDE_CPR, AVERAGE_CPR).
  3. Camarilla Pivots: H5, H4, H3, L3, L4, L5.
  4. Classical Floor Pivots: R1, R2, R3, S1, S2, S3.
  5. Weekly Reference Levels: PWH, PWL, PWC.
  6. Pre-Market Indicative Auction Discovery (09:08–09:12 IST):
     - Indicative Open, Opening Gap Points, Gap %, Gap Classification
       (PRO_GAP_UP, PRO_GAP_DOWN, COMMON_GAP_UP, COMMON_GAP_DOWN, FLAT).
  7. Actionable Execution Blueprints with exact entry/exit/SL boundaries.

Provides sub-millisecond retrieval across detectors (index micro-scalp, swing inflections,
gap invalidation sentinel, etc.) eliminating redundant historical data fetching.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.constants import IST
from config.paths import app_data_path
from engine.alert_identity import canonical_alert_symbol
from market.instruments import format_strike

logger = logging.getLogger("chanakya.engine.daily_levels")

BENCHMARK_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "SENSEX",
    "BANKEX",
]

INDEX_INSTRUMENT_MAP: dict[str, str] = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "SENSEX": "BSE:SENSEX",
    "BANKEX": "BSE:BANKEX",
}


@dataclass
class CPRGateResult:
    """Institutional Central Pivot Range (CPR) evaluation and safety gate result."""

    is_vetoed: bool = False
    veto_reason: Optional[str] = None
    is_narrow: bool = False
    is_wide: bool = False
    cpr_type: str = "NORMAL"  # NARROW | WIDE | NORMAL
    cpr_top: float = 0.0
    cpr_bottom: float = 0.0
    cpr_pivot: float = 0.0
    cpr_width_pct: float = 0.0
    cpr_data: dict[str, Any] = field(default_factory=dict)
    has_confluence: bool = False
    confluence_tag: Optional[str] = None


@dataclass
class DailyLevels:
    """Institutional Daily Reference Levels & Pre-Market Bias Data."""

    symbol: str
    canonical_symbol: str
    exchange: str
    session_date: str  # YYYY-MM-DD
    pdh: float
    pdl: float
    pdc: float
    pdo: float = 0.0
    atr_14: float = 0.0
    spot: float = 0.0
    cpr: dict[str, Any] = field(default_factory=dict)
    camarilla: dict[str, Any] = field(default_factory=dict)
    classic_pivots: dict[str, Any] = field(default_factory=dict)
    weekly: dict[str, Any] = field(default_factory=dict)
    monthly: dict[str, Any] = field(default_factory=dict)
    pre_open: dict[str, Any] = field(default_factory=dict)
    blueprint: dict[str, Any] = field(default_factory=dict)
    straddle: dict[str, Any] = field(default_factory=dict)
    virgin_cpr: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    @property
    def atm_straddle_price(self) -> float:
        """Priced ATM Straddle (CE LTP + PE LTP) from nearest options chain."""
        return float(self.straddle.get("straddle_price", 0.0) or 0.0)

    @property
    def straddle_expected_high(self) -> float:
        """Upper boundary of expected move based on ATM Straddle."""
        return float(self.straddle.get("expected_high", 0.0) or 0.0)

    @property
    def straddle_expected_low(self) -> float:
        """Lower boundary of expected move based on ATM Straddle."""
        return float(self.straddle.get("expected_low", 0.0) or 0.0)

    @property
    def straddle_expansion_threshold(self) -> float:
        """Threshold where price move breaks out of expected noise into gamma expansion."""
        return float(self.straddle.get("expansion_threshold", 0.0) or 0.0)

    @property
    def pwh(self) -> float:
        """Previous Week High."""
        return float(self.weekly.get("pwh", 0.0) or 0.0)

    @property
    def pwl(self) -> float:
        """Previous Week Low."""
        return float(self.weekly.get("pwl", 0.0) or 0.0)

    @property
    def pwc(self) -> float:
        """Previous Week Close."""
        return float(self.weekly.get("pwc", 0.0) or 0.0)

    @property
    def pmh(self) -> float:
        """Previous Month High."""
        return float(self.monthly.get("pmh", 0.0) or 0.0)

    @property
    def pml(self) -> float:
        """Previous Month Low."""
        return float(self.monthly.get("pml", 0.0) or 0.0)

    @property
    def pmc(self) -> float:
        """Previous Month Close."""
        return float(self.monthly.get("pmc", 0.0) or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evaluate_cpr_gate(
        self,
        spot: float,
        direction: str = "BULLISH",
        boundary_proximity_pct: float = 0.0035,
    ) -> CPRGateResult:
        """Evaluates CPR overhead and core chop containment for this DailyLevels instance."""
        return evaluate_cpr_gate(
            symbol=self.canonical_symbol or self.symbol,
            spot=spot,
            direction=direction,
            dl=self,
            boundary_proximity_pct=boundary_proximity_pct,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyLevels:
        return cls(
            symbol=data.get("symbol", ""),
            canonical_symbol=data.get("canonical_symbol", ""),
            exchange=data.get("exchange", "NSE"),
            session_date=data.get("session_date", ""),
            pdh=float(data.get("pdh", 0.0)),
            pdl=float(data.get("pdl", 0.0)),
            pdc=float(data.get("pdc", 0.0)),
            pdo=float(data.get("pdo", 0.0)),
            atr_14=float(data.get("atr_14", 0.0)),
            spot=float(data.get("spot", 0.0)),
            cpr=data.get("cpr") or {},
            camarilla=data.get("camarilla") or {},
            classic_pivots=data.get("classic_pivots") or {},
            weekly=data.get("weekly") or {},
            monthly=data.get("monthly") or {},
            pre_open=data.get("pre_open") or {},
            blueprint=data.get("blueprint") or {},
            virgin_cpr=data.get("virgin_cpr") or {},
            updated_at=data.get("updated_at", ""),
        )


class DailyLevelsStore:
    """
    Thread-safe Two-Tier Daily Levels Repository:
      - L1 In-Memory Fast Lookup: < 0.01 ms
      - L2 Daily File Persistence: data/daily_levels/{YYYY-MM-DD}.json
    """

    def __init__(self, persist_dir: Optional[Path] = None):
        self._lock = threading.RLock()
        self._memory_cache: dict[str, DailyLevels] = {}  # key: f"{session_date}:{canonical_symbol}"
        if persist_dir:
            self._persist_dir = Path(persist_dir)
        elif os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ:
            self._persist_dir = app_data_path("daily_levels")
            self._persist_dir.mkdir(parents=True, exist_ok=True)
        else:
            override = os.environ.get("TRADING_PLATFORM_DATA") or os.environ.get(
                "TRADING_PLATFORM_HOME"
            )
            if override:
                self._persist_dir = app_data_path("daily_levels")
            else:
                local_data = Path("data/daily_levels")
                try:
                    local_data.mkdir(parents=True, exist_ok=True)
                    self._persist_dir = local_data
                except Exception:
                    self._persist_dir = app_data_path("daily_levels")
            self._persist_dir.mkdir(parents=True, exist_ok=True)

        # Automatically load today's persisted levels if present
        today_str = self._get_today_session_date()
        self.load_from_disk(today_str)

    def _store_in_memory_cache(self, cache_key: str, dl: DailyLevels) -> None:
        """Store DailyLevels in memory cache with bounded capacity."""
        if len(self._memory_cache) >= 500:
            keys_to_drop = list(self._memory_cache.keys())[:100]
            for k in keys_to_drop:
                self._memory_cache.pop(k, None)
        self._memory_cache[cache_key] = dl

    def _get_today_session_date(self) -> str:
        return datetime.now(IST).strftime("%Y-%m-%d")

    def _get_file_path(self, session_date: str) -> Path:
        return self._persist_dir / f"daily_levels_{session_date}.json"

    def get_levels(
        self,
        symbol: str,
        session_date: Optional[str] = None,
        compute_if_missing: bool = True,
    ) -> Optional[DailyLevels]:
        """
        Retrieves daily levels for a given symbol.
        Checks L1 in-memory cache first, then disk L2, and optionally computes on-demand.
        """
        clean = canonical_alert_symbol(symbol)
        s_date = session_date or self._get_today_session_date()
        cache_key = f"{s_date}:{clean}"

        with self._lock:
            if cache_key in self._memory_cache:
                dl = self._memory_cache[cache_key]
                if dl.pdh > 0 and dl.pdl > 0 and dl.pdc > 0:
                    return dl

        # Try loading from disk if not yet in memory
        self.load_from_disk(s_date)
        with self._lock:
            if cache_key in self._memory_cache:
                dl = self._memory_cache[cache_key]
                if dl.pdh > 0 and dl.pdl > 0 and dl.pdc > 0:
                    return dl

        if compute_if_missing:
            return self.compute_and_store(symbol=clean, session_date=s_date)

        return None

    def compute_and_store(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        session_date: Optional[str] = None,
        persist: bool = True,
        preloaded_quote: Any = None,
        preloaded_df: Optional[pd.DataFrame] = None,
    ) -> Optional[DailyLevels]:
        """
        Computes previous day levels, CPR, Camarilla, Classical, Weekly, and Blueprint.
        Stores in L1 memory and persists to L2 disk file.
        """
        clean = canonical_alert_symbol(symbol)
        s_date = session_date or self._get_today_session_date()
        exch = exchange if exchange else ("BSE" if clean in ("SENSEX", "BANKEX") else "NSE")

        from market.history import get_ohlcv
        from market.quotes import get_quote

        # 1. Fetch quote for LTP & Prev Close
        inst = INDEX_INSTRUMENT_MAP.get(clean, f"{exch}:{clean}")
        if preloaded_quote is not None:
            q = preloaded_quote
        elif s_date == self._get_today_session_date():
            quotes = get_quote([inst])
            q = quotes.get(inst) or quotes.get(f"{exch}:{clean}") or quotes.get(clean)
        else:
            q = None

        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0) if q else 0.0
        prev_close_q = float(getattr(q, "close", 0.0) or 0.0) if q else 0.0

        # 2. Daily OHLCV to extract historical completed PDH, PDL, PDC, PDO
        pdh, pdl, pdc, pdo = 0.0, 0.0, prev_close_q, 0.0
        atr_14 = 0.0

        try:
            if preloaded_df is not None and not preloaded_df.empty:
                df_day = preloaded_df
            else:
                df_day = get_ohlcv(clean, exchange=exch, interval="day", days=100)
            if df_day is not None and len(df_day) >= 2:
                col_h = "high" if "high" in df_day.columns else "High"
                col_l = "low" if "low" in df_day.columns else "Low"
                col_c = "close" if "close" in df_day.columns else "Close"
                col_o = "open" if "open" in df_day.columns else "Open"

                # Check if last bar is today's incomplete candle
                last_dt = df_day.index[-1]
                last_dt_str = (
                    last_dt.strftime("%Y-%m-%d")
                    if hasattr(last_dt, "strftime")
                    else str(last_dt)[:10]
                )
                bar_idx = -2 if last_dt_str == s_date else -1

                pdh = float(df_day[col_h].iloc[bar_idx])
                pdl = float(df_day[col_l].iloc[bar_idx])
                pdc = float(df_day[col_c].iloc[bar_idx])
                pdo = float(df_day[col_o].iloc[bar_idx])

                # Compute ATR-14
                if len(df_day) >= 15:
                    tr1 = df_day[col_h] - df_day[col_l]
                    tr2 = (df_day[col_h] - df_day[col_c].shift()).abs()
                    tr3 = (df_day[col_l] - df_day[col_c].shift()).abs()
                    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr_14 = float(tr.rolling(14).mean().iloc[-1])
        except Exception as e:
            logger.debug(f"[DailyLevels] OHLCV fetch error for {clean}: {e}")

        # Defensive resolution: check quote prev_close and memory cache before failing closed
        if pdc <= 0 and q:
            pdc = float(getattr(q, "prev_close", 0.0) or getattr(q, "close", 0.0) or 0.0)

        if pdh <= 0 or pdl <= 0 or pdc <= 0:
            # Check previous persisted daily levels if available in memory cache
            with self._lock:
                for k, v in self._memory_cache.items():
                    if k.endswith(f":{clean}") and v.pdh > 0 and v.pdl > 0 and v.pdc > 0:
                        pdh, pdl, pdc = v.pdh, v.pdl, v.pdc
                        pdo = v.pdo
                        atr_14 = v.atr_14
                        break

        # Fail-closed: Never fabricate arbitrary synthetic price ranges (Rule 11 Invariant)
        if pdh <= 0 or pdl <= 0 or pdc <= 0:
            logger.warning(
                f"[DailyLevels] Incomplete daily data for {clean}: pdh={pdh}, pdl={pdl}, pdc={pdc}. "
                f"Returning None to avoid fabricating synthetic levels (Rule 11)."
            )
            return None

        # 3. Weekly & Monthly Reference Levels derived deterministically from real daily bars
        pwh, pwl, pwc = 0.0, 0.0, 0.0
        pmh, pml, pmc = 0.0, 0.0, 0.0

        if df_day is not None and len(df_day) >= 5:
            try:
                # Ensure DatetimeIndex for clean pandas resampling
                df_resample = df_day.copy()
                if not isinstance(df_resample.index, pd.DatetimeIndex):
                    df_resample.index = pd.to_datetime(df_resample.index)

                col_map = {col_o: "first", col_h: "max", col_l: "min", col_c: "last"}
                if "volume" in df_resample.columns:
                    col_map["volume"] = "sum"
                elif "Volume" in df_resample.columns:
                    col_map["Volume"] = "sum"

                # 3a. Weekly OHLCV (Friday-ending weeks)
                df_wk = df_resample.resample("W-FRI").agg(col_map).dropna()
                if len(df_wk) >= 2:
                    pwh = float(df_wk[col_h].iloc[-2])
                    pwl = float(df_wk[col_l].iloc[-2])
                    pwc = float(df_wk[col_c].iloc[-2])
                elif len(df_wk) == 1:
                    pwh = float(df_wk[col_h].iloc[-1])
                    pwl = float(df_wk[col_l].iloc[-1])
                    pwc = float(df_wk[col_c].iloc[-1])

                # 3b. Monthly OHLCV (Month-End)
                # Handle pandas version compatibility ('ME' for >= 2.2, 'M' for older)
                freq_month = "ME"
                try:
                    df_mo = df_resample.resample(freq_month).agg(col_map).dropna()
                except ValueError:
                    df_mo = df_resample.resample("M").agg(col_map).dropna()

                if len(df_mo) >= 2:
                    pmh = float(df_mo[col_h].iloc[-2])
                    pml = float(df_mo[col_l].iloc[-2])
                    pmc = float(df_mo[col_c].iloc[-2])
                elif len(df_mo) == 1:
                    pmh = float(df_mo[col_h].iloc[-1])
                    pml = float(df_mo[col_l].iloc[-1])
                    pmc = float(df_mo[col_c].iloc[-1])
            except Exception as e_resample:
                logger.debug(f"[DailyLevels] Resampling error for {clean}: {e_resample}")

        # Fallback to broker weekly endpoint if resampling was unavailable
        if pwh <= 0:
            try:
                df_wk = get_ohlcv(clean, exchange=exch, interval="week", days=30)
                if df_wk is not None and len(df_wk) >= 2:
                    col_h = "high" if "high" in df_wk.columns else "High"
                    col_l = "low" if "low" in df_wk.columns else "Low"
                    col_c = "close" if "close" in df_wk.columns else "Close"
                    pwh = float(df_wk[col_h].iloc[-2])
                    pwl = float(df_wk[col_l].iloc[-2])
                    pwc = float(df_wk[col_c].iloc[-2])
            except Exception as e_suppressed:
                logger.debug(
                    f"[engine.daily_levels] Non-fatal exception suppressed: {e_suppressed}"
                )

        # 4. CPR (Central Pivot Range) Calculation
        cpr_pivot = (pdh + pdl + pdc) / 3.0
        cpr_bc = (pdh + pdl) / 2.0
        cpr_tc = (cpr_pivot - cpr_bc) + cpr_pivot
        cpr_top = max(cpr_tc, cpr_bc)
        cpr_bottom = min(cpr_tc, cpr_bc)
        cpr_width_pct = abs(cpr_tc - cpr_bc) / max(1.0, cpr_pivot) * 100.0

        is_index = clean in BENCHMARK_INDICES
        is_narrow = cpr_width_pct <= (
            0.22 if clean in ("BANKNIFTY", "SENSEX", "BANKEX") else (0.15 if is_index else 0.25)
        )
        is_wide = cpr_width_pct >= (0.35 if is_index else 0.60)
        cpr_regime = (
            "NARROW_CPR (Trend Day Expected)"
            if is_narrow
            else ("WIDE_CPR (Range/Chop Expected)" if is_wide else "AVERAGE_CPR")
        )

        cpr_dict = {
            "tc": round(cpr_tc, 2),
            "pivot": round(cpr_pivot, 2),
            "bc": round(cpr_bc, 2),
            "top": round(cpr_top, 2),
            "bottom": round(cpr_bottom, 2),
            "width_pct": round(cpr_width_pct, 4),
            "is_narrow": is_narrow,
            "is_wide": is_wide,
            "regime": cpr_regime,
        }

        # 5. Camarilla Pivots Calculation
        cam_range = max(0.01, pdh - pdl)
        cam_h5 = round((pdh / max(0.01, pdl)) * pdc, 2)
        cam_h4 = round(pdc + (cam_range * 1.1 / 2.0), 2)
        cam_h3 = round(pdc + (cam_range * 1.1 / 4.0), 2)
        cam_l3 = round(pdc - (cam_range * 1.1 / 4.0), 2)
        cam_l4 = round(pdc - (cam_range * 1.1 / 2.0), 2)
        cam_l5 = round(max(0.0, pdc - (cam_h5 - pdc)), 2)

        camarilla_dict = {
            "h5": cam_h5,
            "h4": cam_h4,
            "h3": cam_h3,
            "l3": cam_l3,
            "l4": cam_l4,
            "l5": cam_l5,
            "range": round(cam_range, 2),
        }

        # 6. Classical Floor Pivots
        r1 = round((2.0 * cpr_pivot) - pdl, 2)
        s1 = round((2.0 * cpr_pivot) - pdh, 2)
        r2 = round(cpr_pivot + cam_range, 2)
        s2 = round(cpr_pivot - cam_range, 2)
        r3 = round(pdh + 2.0 * (cpr_pivot - pdl), 2)
        s3 = round(pdl - 2.0 * (pdh - cpr_pivot), 2)

        classic_dict = {
            "r1": r1,
            "r2": r2,
            "r3": r3,
            "s1": s1,
            "s2": s2,
            "s3": s3,
        }

        # 7. Pre-Open & Gap Analysis
        pre_open_dict = {
            "price": 0.0,
            "gap_points": 0.0,
            "gap_pct": 0.0,
            "gap_type": "UNKNOWN",
            "opening_bias": "NEUTRAL",
            "auction_settled": False,
        }
        # If live quote has open price during pre-market or open market
        curr_open = float(getattr(q, "open", 0.0) or 0.0) if q else 0.0
        if curr_open > 0 and pdc > 0:
            gap_pts = curr_open - pdc
            gap_pct = round((gap_pts / pdc) * 100.0, 3)
            if curr_open > pdh:
                gap_type = "PRO_GAP_UP (Above PDH)"
                opening_bias = "BULLISH"
            elif curr_open < pdl:
                gap_type = "PRO_GAP_DOWN (Below PDL)"
                opening_bias = "BEARISH"
            elif gap_pct >= 0.20:
                gap_type = "COMMON_GAP_UP"
                opening_bias = "MILD_BULLISH"
            elif gap_pct <= -0.20:
                gap_type = "COMMON_GAP_DOWN"
                opening_bias = "MILD_BEARISH"
            else:
                gap_type = "FLAT_OPEN"
                opening_bias = "RANGEBOUND"

            pre_open_dict = {
                "price": round(curr_open, 2),
                "gap_points": round(gap_pts, 2),
                "gap_pct": gap_pct,
                "gap_type": gap_type,
                "opening_bias": opening_bias,
                "auction_settled": True,
            }

        # 8. Actionable Execution Blueprint & Pre-Market Strike Pre-Calculation
        from market.symbol_master import get_strike_step

        spot_price = ltp if ltp > 0 else pdc
        strike_step = get_strike_step(clean, spot=spot_price)
        bull_strike = round(round(cam_h4 / strike_step) * strike_step, 2)
        if bull_strike == int(bull_strike):
            bull_strike = int(bull_strike)
        bear_strike = round(round(cam_l4 / strike_step) * strike_step, 2)
        if bear_strike == int(bear_strike):
            bear_strike = int(bear_strike)

        blueprint = {
            "trend_long": f"Buy CE on 5m close above H4 (₹{cam_h4:,.1f}) target H5 (₹{cam_h5:,.1f})",
            "trend_short": f"Buy PE on 5m close below L4 (₹{cam_l4:,.1f}) target L5 (₹{cam_l5:,.1f})",
            "reversal_long": f"Buy CE on bullish rejection wick at L3/PDL (₹{cam_l3:,.1f} - ₹{pdl:,.1f}) with tight SL",
            "reversal_short": f"Buy PE on bearish rejection wick at H3/PDH (₹{cam_h3:,.1f} - ₹{pdh:,.1f}) with tight SL",
            "bull_strike": bull_strike,
            "bear_strike": bear_strike,
            "bull_contract": f"{clean} {format_strike(bull_strike)} CE",
            "bear_contract": f"{clean} {format_strike(bear_strike)} PE",
            "h4_trigger": round(cam_h4, 1),
            "l4_trigger": round(cam_l4, 1),
            "h5_target": round(cam_h5, 1),
            "l5_target": round(cam_l5, 1),
            "no_chase_boundary": round(cam_h4 * 1.008, 1),
            "action_guidance": "Wait for spot to reach key boundaries. Never chase in chop zone between L3 and H3.",
        }

        weekly_dict = {
            "pwh": round(pwh, 2),
            "pwl": round(pwl, 2),
            "pwc": round(pwc, 2),
        }

        monthly_dict = {
            "pmh": round(pmh, 2),
            "pml": round(pml, 2),
            "pmc": round(pmc, 2),
        }

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # 9. Institutional ATM Straddle Price & Expected Move Boundaries
        straddle_dict: dict[str, Any] = {}
        is_test = (
            os.environ.get("CHANAKYA_TESTING") == "1"
            or os.environ.get("DEPLOY_MODE") == "test"
            or ("PYTEST_CURRENT_TEST" in os.environ)
        )
        if (
            is_index or clean in ("RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "TCS")
        ) and not is_test:
            try:
                from market.options import get_atm_straddle_metrics

                s_metrics = get_atm_straddle_metrics(clean, spot=spot_price)
                if s_metrics:
                    straddle_dict = s_metrics.to_dict()
            except Exception as e_straddle:
                logger.debug(f"[DailyLevels] Straddle calculation note for {clean}: {e_straddle}")

        # 10. Untested Virgin CPR Detection across previous sessions
        virgin_cpr_data: dict[str, Any] = {}
        try:
            virgin_cpr_data = detect_virgin_cpr(
                symbol=clean,
                history_df=df_day,
                current_price=spot_price,
                session_date=s_date,
            )
            cpr_dict["virgin_cpr"] = virgin_cpr_data
        except Exception as e_vcpr:
            logger.debug(f"[DailyLevels] Virgin CPR calculation note for {clean}: {e_vcpr}")

        dl = DailyLevels(
            symbol=clean,
            canonical_symbol=clean,
            exchange=exch,
            session_date=s_date,
            pdh=round(pdh, 2),
            pdl=round(pdl, 2),
            pdc=round(pdc, 2),
            pdo=round(pdo, 2),
            atr_14=round(atr_14, 2),
            spot=round(ltp, 2),
            cpr=cpr_dict,
            camarilla=camarilla_dict,
            classic_pivots=classic_dict,
            weekly=weekly_dict,
            monthly=monthly_dict,
            pre_open=pre_open_dict,
            straddle=straddle_dict,
            virgin_cpr=virgin_cpr_data,
            blueprint=blueprint,
            updated_at=now_iso,
        )

        cache_key = f"{s_date}:{clean}"
        with self._lock:
            self._store_in_memory_cache(cache_key, dl)

        if persist:
            self.save_to_disk(s_date)
        return dl

    def update_preopen(
        self,
        symbol: str,
        pre_open_price: float,
        session_date: Optional[str] = None,
    ) -> Optional[DailyLevels]:
        """
        Updates pre-market auction open price and re-evaluates gap classification.
        """
        if pre_open_price <= 0:
            return None
        clean = canonical_alert_symbol(symbol)
        s_date = session_date or self._get_today_session_date()
        dl = self.get_levels(clean, session_date=s_date, compute_if_missing=True)
        if not dl:
            return None

        gap_pts = pre_open_price - dl.pdc
        gap_pct = round((gap_pts / max(1.0, dl.pdc)) * 100.0, 3)

        if pre_open_price > dl.pdh:
            gap_type = "PRO_GAP_UP (Above PDH)"
            bias = "BULLISH"
        elif pre_open_price < dl.pdl:
            gap_type = "PRO_GAP_DOWN (Below PDL)"
            bias = "BEARISH"
        elif gap_pct >= 0.20:
            gap_type = "COMMON_GAP_UP"
            bias = "MILD_BULLISH"
        elif gap_pct <= -0.20:
            gap_type = "COMMON_GAP_DOWN"
            bias = "MILD_BEARISH"
        else:
            gap_type = "FLAT_OPEN"
            bias = "RANGEBOUND"

        dl.pre_open = {
            "price": round(pre_open_price, 2),
            "gap_points": round(gap_pts, 2),
            "gap_pct": gap_pct,
            "gap_type": gap_type,
            "opening_bias": bias,
            "auction_settled": True,
        }
        dl.updated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        cache_key = f"{s_date}:{clean}"
        with self._lock:
            self._store_in_memory_cache(cache_key, dl)

        self.save_to_disk(s_date)
        return dl

    def prime_universe(
        self,
        symbols: Optional[list[str]] = None,
        session_date: Optional[str] = None,
    ) -> dict[str, DailyLevels]:
        """
        Pre-computes and caches daily levels for benchmark indices and watchlist symbols
        using high-throughput batch OHLCV and batch quote retrieval.
        """
        from engine.eod_store import get_ohlcv_batch
        from market.quotes import get_quote

        target_syms = symbols or BENCHMARK_INDICES
        s_date = session_date or self._get_today_session_date()
        results: dict[str, DailyLevels] = {}

        # 1. High-throughput single-pass batch fetch of daily historical bars from SQLite L1/L2
        clean_syms = [canonical_alert_symbol(s) for s in target_syms]
        try:
            df_batch = get_ohlcv_batch(clean_syms, days=100)
        except Exception as e_batch:
            logger.warning(f"[DailyLevels] Batch OHLCV fetch failed: {e_batch}")
            df_batch = {}

        # 2. Batch fetch quotes in chunks to keep HTTP payloads bounded (<100 items per call)
        quote_map: dict[str, Any] = {}
        try:
            chunk_size = 50
            for i in range(0, len(clean_syms), chunk_size):
                chunk = clean_syms[i : i + chunk_size]
                chunk_insts = [INDEX_INSTRUMENT_MAP.get(s, f"NSE:{s}") for s in chunk]
                q_res = get_quote(chunk_insts)
                for k, v in q_res.items():
                    c_k = canonical_alert_symbol(k)
                    quote_map[c_k] = v
        except Exception as e_quotes:
            logger.debug(f"[DailyLevels] Batch quote fetch note: {e_quotes}")

        # 3. Compute and store in-memory for each symbol
        for sym in target_syms:
            clean = canonical_alert_symbol(sym)
            try:
                p_quote = quote_map.get(clean)
                p_df = df_batch.get(clean)
                dl = self.compute_and_store(
                    sym,
                    session_date=s_date,
                    persist=False,
                    preloaded_quote=p_quote,
                    preloaded_df=p_df,
                )
                if dl:
                    results[sym] = dl
            except Exception as e:
                logger.warning(f"[DailyLevels] Priming failed for {sym}: {e}")

        self.save_to_disk(s_date)
        return results

    def save_to_disk(self, session_date: Optional[str] = None) -> None:
        """Persists today's in-memory levels to daily JSON file with Windows file-lock resilience."""
        s_date = session_date or self._get_today_session_date()
        file_path = self._get_file_path(s_date)

        with self._lock:
            payload: dict[str, Any] = {}
            prefix = f"{s_date}:"
            for k, dl in self._memory_cache.items():
                if k.startswith(prefix):
                    clean = k[len(prefix) :]
                    payload[clean] = dl.to_dict()

            if not payload:
                return

            temp_path = None
            try:
                self._persist_dir.mkdir(parents=True, exist_ok=True)
                # Sibling unique temp path with PID and monotonic timestamp to prevent concurrent collisions
                temp_path = file_path.with_name(
                    f"{file_path.name}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
                )
                serialized = json.dumps(payload, indent=2, ensure_ascii=False)
                temp_path.write_text(serialized, encoding="utf-8")

                # Resilient atomic replace with exponential retry & sidecar fallback for Windows file locks
                replaced = False
                for attempt in range(5):
                    try:
                        os.replace(temp_path, file_path)
                        replaced = True
                        break
                    except (PermissionError, OSError) as pe:
                        if attempt == 4:
                            # Final fallback: sidecar write to guarantee zero data loss under stubborn Windows locks
                            side_path = file_path.with_suffix(f".side.{int(time.time())}.json")
                            try:
                                os.replace(temp_path, side_path)
                                replaced = True
                                logger.warning(
                                    f"[DailyLevels] Atomic replace locked ({pe}); safely persisted {len(payload)} levels to sidecar {side_path.name}"
                                )
                            except Exception as side_err:
                                logger.warning(
                                    f"[DailyLevels] Sidecar save failed ({side_err}); attempting direct write"
                                )
                                try:
                                    file_path.write_text(serialized, encoding="utf-8")
                                    replaced = True
                                except Exception as direct_err:
                                    logger.warning(
                                        f"[DailyLevels] Direct write degraded ({direct_err})"
                                    )
                        else:
                            time.sleep(0.08 * (2**attempt))

                if replaced:
                    logger.debug(f"[DailyLevels] Persisted {len(payload)} levels to {file_path}")
            except Exception as e:
                logger.error(f"[DailyLevels] Failed saving levels to {file_path}: {e}")
            finally:
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink(missing_ok=True)
                    except Exception as e_unlink:
                        logger.debug("Failed unlinking temp_path %s: %s", temp_path, e_unlink)

    def load_from_disk(self, session_date: Optional[str] = None) -> int:
        """Loads levels from daily JSON file (or newest sidecar) into L1 in-memory cache."""
        s_date = session_date or self._get_today_session_date()
        file_path = self._get_file_path(s_date)

        target_path = file_path if file_path.exists() else None
        sidecars = list(file_path.parent.glob(f"{file_path.stem}.side.*.json"))
        if sidecars:
            newest_sidecar = max(sidecars, key=lambda p: p.stat().st_mtime)
            if not target_path or newest_sidecar.stat().st_mtime > target_path.stat().st_mtime:
                target_path = newest_sidecar
                # Try promoting sidecar to primary
                try:
                    os.replace(newest_sidecar, file_path)
                    target_path = file_path
                except Exception as e_replace:
                    logger.debug("Failed replacing sidecar to %s: %s", file_path, e_replace)

        if not target_path or not target_path.exists():
            return 0

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_count = 0
            with self._lock:
                for clean_sym, d in data.items():
                    dl = DailyLevels.from_dict(d)
                    cache_key = f"{s_date}:{clean_sym}"
                    self._store_in_memory_cache(cache_key, dl)
                    loaded_count += 1
            logger.info(
                f"[DailyLevels] Loaded {loaded_count} levels for {s_date} from {target_path.name}"
            )
            return loaded_count
        except Exception as e:
            logger.warning(f"[DailyLevels] Failed loading levels from {target_path}: {e}")
            return 0

    def get_all_for_today(self, session_date: Optional[str] = None) -> dict[str, DailyLevels]:
        """Returns all cached levels for today's session."""
        s_date = session_date or self._get_today_session_date()
        self.load_from_disk(s_date)
        prefix = f"{s_date}:"
        with self._lock:
            return {
                k[len(prefix) :]: dl for k, dl in self._memory_cache.items() if k.startswith(prefix)
            }

    def get_daily_levels(
        self, symbol: str, session_date: Optional[str] = None
    ) -> Optional[DailyLevels]:
        """Alias for get_levels to maintain unified API parity."""
        return self.get_levels(symbol, session_date=session_date)


# Global Singleton Instance
daily_levels_store = DailyLevelsStore()
DailyLevelsEngine = DailyLevelsStore  # Class alias for detector compatibility


def get_daily_levels(symbol: str, session_date: Optional[str] = None) -> Optional[DailyLevels]:
    """Public helper to get daily levels with L1 in-memory caching and L2 persistence."""
    return daily_levels_store.get_levels(symbol, session_date=session_date)


def compute_daily_levels_from_prices(
    symbol: str,
    pdh: float,
    pdl: float,
    pdc: float,
    pdo: float = 0.0,
    atr_14: float = 0.0,
    session_date: str = "",
    exchange: str = "NSE",
) -> DailyLevels:
    """
    Computes institutional DailyLevels (CPR, Camarilla, Classical Floor Pivots)
    directly from previous session OHLC prices.
    Eliminates duplicate mathematical formulas and ad-hoc dictionary builders across detectors.
    """
    clean = canonical_alert_symbol(symbol)
    s_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")

    # 1. CPR Calculation
    cpr_pivot = (pdh + pdl + pdc) / 3.0
    cpr_bc = (pdh + pdl) / 2.0
    cpr_tc = (cpr_pivot - cpr_bc) + cpr_pivot
    cpr_top = max(cpr_tc, cpr_bc)
    cpr_bottom = min(cpr_tc, cpr_bc)
    cpr_width_pct = abs(cpr_tc - cpr_bc) / max(1.0, cpr_pivot) * 100.0

    is_index = clean in BENCHMARK_INDICES
    is_narrow = cpr_width_pct <= (
        0.22 if clean in ("BANKNIFTY", "SENSEX", "BANKEX") else (0.15 if is_index else 0.25)
    )
    is_wide = cpr_width_pct >= (0.35 if is_index else 0.60)
    cpr_type = "NARROW" if is_narrow else ("WIDE" if is_wide else "NORMAL")
    cpr_regime = (
        "NARROW_CPR (Trend Day Expected)"
        if is_narrow
        else ("WIDE_CPR (Range/Chop Expected)" if is_wide else "AVERAGE_CPR")
    )

    cpr_dict = {
        "tc": round(cpr_tc, 2),
        "pivot": round(cpr_pivot, 2),
        "bc": round(cpr_bc, 2),
        "top": round(cpr_top, 2),
        "bottom": round(cpr_bottom, 2),
        "cpr_top": round(cpr_top, 2),
        "cpr_bottom": round(cpr_bottom, 2),
        "width_pct": round(cpr_width_pct, 4),
        "cpr_width_pct": round(cpr_width_pct, 4),
        "is_narrow": is_narrow,
        "is_wide": is_wide,
        "cpr_type": cpr_type,
        "regime": cpr_regime,
    }

    # 2. Camarilla Pivots
    cam_range = max(0.01, pdh - pdl)
    cam_h5 = round((pdh / max(0.01, pdl)) * pdc, 2)
    cam_h4 = round(pdc + (cam_range * 1.1 / 2.0), 2)
    cam_h3 = round(pdc + (cam_range * 1.1 / 4.0), 2)
    cam_l3 = round(pdc - (cam_range * 1.1 / 4.0), 2)
    cam_l4 = round(pdc - (cam_range * 1.1 / 2.0), 2)
    cam_l5 = round(max(0.0, pdc - (cam_h5 - pdc)), 2)

    camarilla_dict = {
        "h5": cam_h5,
        "h4": cam_h4,
        "h3": cam_h3,
        "l3": cam_l3,
        "l4": cam_l4,
        "l5": cam_l5,
        "range": round(cam_range, 2),
    }

    # 3. Classical Floor Pivots
    r1 = round((2.0 * cpr_pivot) - pdl, 2)
    s1 = round((2.0 * cpr_pivot) - pdh, 2)
    r2 = round(cpr_pivot + cam_range, 2)
    s2 = round(cpr_pivot - cam_range, 2)
    r3 = round(pdh + 2.0 * (cpr_pivot - pdl), 2)
    s3 = round(pdl - 2.0 * (pdh - cpr_pivot), 2)

    classic_dict = {
        "r1": r1,
        "r2": r2,
        "r3": r3,
        "s1": s1,
        "s2": s2,
        "s3": s3,
    }

    return DailyLevels(
        symbol=symbol,
        canonical_symbol=clean,
        exchange=exchange,
        session_date=s_date,
        pdh=pdh,
        pdl=pdl,
        pdc=pdc,
        pdo=pdo,
        atr_14=atr_14,
        cpr=cpr_dict,
        camarilla=camarilla_dict,
        classic_pivots=classic_dict,
    )


def evaluate_cpr_gate(
    symbol: str,
    spot: float,
    direction: str = "BULLISH",
    dl: Optional[DailyLevels] = None,
    session_date: Optional[str] = None,
    boundary_proximity_pct: float = 0.0035,
    is_reversal: bool = False,
) -> CPRGateResult:
    """
    Universal Single Source of Truth (SSOT) CPR Overhead, Chop Containment & Confluence Gate.

    Eliminates duplicated CPR unpacking, threshold parsing, and boundary testing across detectors.

    Rules Enforced:
      1. Wide CPR Core Chop Containment:
         - Spot trapped strictly inside Wide CPR core [Bottom < spot < Top] -> VETO
      2. Wide CPR Boundary Wall Collision (Breakouts):
         - Bullish: Spot testing Wide CPR Top resistance from below within boundary_proximity_pct -> VETO
         - Bearish: Spot testing Wide CPR Bottom support from above within boundary_proximity_pct -> VETO
      3. Reversal Setups (is_reversal=True, e.g. SMT Sweep):
         - Bearish reversal at/above CPR Top is an institutional short rejection -> Confluence tag CPR_TOP_CONFLUENCE
         - Bullish reversal at/below CPR Bottom is an institutional spring -> Confluence tag CPR_BOTTOM_CONFLUENCE
      4. Narrow CPR Expansion:
         - Identifies high-momentum trending regime for conviction boosting.
    """
    clean_sym = canonical_alert_symbol(symbol)
    if dl is None:
        try:
            dl = get_daily_levels(clean_sym, session_date=session_date)
        except Exception as e_dl:
            logger.debug(f"[CPRGate] get_daily_levels failed for {clean_sym}: {e_dl}")
            return CPRGateResult()

    if not dl or not dl.cpr:
        return CPRGateResult()

    cpr_data = dict(dl.cpr)
    cpr_width_pct = float(cpr_data.get("width_pct", 0.0) or 0.0)
    cpr_top = float(cpr_data.get("top", 0.0) or cpr_data.get("tc", 0.0) or 0.0)
    cpr_bottom = float(cpr_data.get("bottom", 0.0) or cpr_data.get("bc", 0.0) or 0.0)
    cpr_pivot = float(cpr_data.get("pivot", 0.0) or 0.0)

    is_idx = clean_sym in BENCHMARK_INDICES
    is_narrow = bool(cpr_data.get("is_narrow")) or (
        cpr_width_pct
        <= (0.22 if clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX") else (0.15 if is_idx else 0.25))
    )
    is_wide = bool(cpr_data.get("is_wide")) or (cpr_width_pct >= (0.35 if is_idx else 0.60))
    cpr_type = str(
        cpr_data.get("cpr_type", "NARROW" if is_narrow else ("WIDE" if is_wide else "NORMAL"))
    )

    dir_upper = direction.upper()
    is_vetoed = False
    veto_reason = None
    has_confluence = False
    confluence_tag = None

    # Check extrema confluence for reversal setups (SMT Sweep, Pinbar, Spring, Upthrust)
    if spot > 0:
        if cpr_top > 0 and abs(spot - cpr_top) / max(1.0, spot) <= 0.0025:
            has_confluence = True
            confluence_tag = "CPR_TOP_CONFLUENCE"
        elif cpr_bottom > 0 and abs(spot - cpr_bottom) / max(1.0, spot) <= 0.0025:
            has_confluence = True
            confluence_tag = "CPR_BOTTOM_CONFLUENCE"
        else:
            v_cpr = getattr(dl, "virgin_cpr", None) or cpr_data.get("virgin_cpr") or {}
            if v_cpr.get("has_virgin_cpr"):
                nearest_m = v_cpr.get("nearest_magnet") or {}
                m_pivot = float(nearest_m.get("pivot", 0.0) or 0.0)
                if m_pivot > 0 and abs(spot - m_pivot) / max(1.0, spot) <= 0.0025:
                    has_confluence = True
                    confluence_tag = "VIRGIN_CPR_MAGNET_CONFLUENCE"

    if is_wide and cpr_bottom > 0 and cpr_top > 0 and spot > 0:
        # Core chop containment: spot is strictly inside the CPR range
        if cpr_bottom < spot < cpr_top:
            is_vetoed = True
            veto_reason = f"Spot ₹{spot:,.1f} trapped inside Wide CPR core [₹{cpr_bottom:,.1f} - ₹{cpr_top:,.1f}]"
        elif not is_reversal:
            if dir_upper in ("BULLISH", "LONG", "CE", "BUY"):
                if spot < cpr_top and (cpr_top - spot) / max(1.0, spot) <= boundary_proximity_pct:
                    is_vetoed = True
                    veto_reason = f"Spot ₹{spot:,.1f} testing Wide CPR Top resistance ₹{cpr_top:,.1f} (Proximity < {boundary_proximity_pct * 100:.2f}%)"
            elif dir_upper in ("BEARISH", "SHORT", "PE", "SELL"):
                if (
                    spot > cpr_bottom
                    and (spot - cpr_bottom) / max(1.0, spot) <= boundary_proximity_pct
                ):
                    is_vetoed = True
                    veto_reason = f"Spot ₹{spot:,.1f} testing Wide CPR Bottom support ₹{cpr_bottom:,.1f} (Proximity < {boundary_proximity_pct * 100:.2f}%)"

    return CPRGateResult(
        is_vetoed=is_vetoed,
        veto_reason=veto_reason,
        is_narrow=is_narrow,
        is_wide=is_wide,
        cpr_type=cpr_type,
        cpr_top=cpr_top,
        cpr_bottom=cpr_bottom,
        cpr_pivot=cpr_pivot,
        cpr_width_pct=cpr_width_pct,
        cpr_data=cpr_data,
        has_confluence=has_confluence,
        confluence_tag=confluence_tag,
    )


def detect_virgin_cpr(
    symbol: str,
    history_df: Optional[pd.DataFrame] = None,
    current_price: float = 0.0,
    lookback_days: int = 5,
    session_date: Optional[str] = None,
) -> dict[str, Any]:
    """
    Detects Untested / Virgin Central Pivot Ranges (Virgin CPR) across recent sessions.

    A Virgin CPR is defined as a historical completed session where the entire intraday price
    range [Low, High] NEVER touched or intersected the CPR corridor [CPR Bottom, CPR Top].
    Furthermore, subsequent completed sessions must NOT have traded through or filled that corridor.

    Because the Central Pivot Range represents institutional fair value, an untested corridor
    leaves high-density latent liquidity and acts as a powerful mean-reversion magnet.

    Returns:
        dict containing:
          - has_virgin_cpr: bool
          - virgin_cprs: list of active virgin CPR records (sorted by proximity)
          - nearest_magnet: dict of the closest active virgin CPR
          - magnet_target: float (pivot price of closest virgin CPR)
          - magnet_bias: "MAGNET_ABOVE" | "MAGNET_BELOW" | "AT_MAGNET" | None
          - distance_pts: float
          - distance_pct: float
          - summary: str
    """
    clean = canonical_alert_symbol(symbol)
    s_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")

    df = history_df
    if df is None or df.empty:
        try:
            from market.history import get_ohlcv

            exch = "BSE" if clean in ("SENSEX", "BANKEX") else "NSE"
            df = get_ohlcv(clean, exchange=exch, interval="day", days=max(20, lookback_days + 15))
        except Exception as e:
            logger.debug(f"[VirginCPR] Could not fetch daily bars for {clean}: {e}")
            df = None

    if df is None or len(df) < 2:
        return {
            "has_virgin_cpr": False,
            "virgin_cprs": [],
            "nearest_magnet": None,
            "magnet_target": None,
            "magnet_bias": None,
            "distance_pts": 0.0,
            "distance_pct": 0.0,
            "summary": "Insufficient historical daily data for Virgin CPR detection.",
        }

    # Normalize column names
    col_h = "high" if "high" in df.columns else "High"
    col_l = "low" if "low" in df.columns else "Low"
    col_c = "close" if "close" in df.columns else "Close"

    if not all(k in df.columns for k in (col_h, col_l, col_c)):
        return {
            "has_virgin_cpr": False,
            "virgin_cprs": [],
            "nearest_magnet": None,
            "magnet_target": None,
            "magnet_bias": None,
            "distance_pts": 0.0,
            "distance_pct": 0.0,
            "summary": "Missing OHLC columns for Virgin CPR detection.",
        }

    # If the last bar represents today's incomplete session, exclude it
    last_dt = df.index[-1]
    last_dt_str = (
        last_dt.strftime("%Y-%m-%d") if hasattr(last_dt, "strftime") else str(last_dt)[:10]
    )
    completed_df = df.iloc[:-1] if last_dt_str == s_date and len(df) > 1 else df

    total_bars = len(completed_df)
    if total_bars < 2:
        return {
            "has_virgin_cpr": False,
            "virgin_cprs": [],
            "nearest_magnet": None,
            "magnet_target": None,
            "magnet_bias": None,
            "distance_pts": 0.0,
            "distance_pct": 0.0,
            "summary": "Insufficient completed daily bars for Virgin CPR detection.",
        }

    max_scan = min(lookback_days, total_bars - 1)
    active_virgin_cprs: list[dict[str, Any]] = []

    ref_price = current_price if current_price > 0 else float(completed_df[col_c].iloc[-1])

    # Scan backwards from yesterday (idx = total_bars - 1)
    for offset in range(1, max_scan + 1):
        target_idx = total_bars - offset
        if target_idx < 1:
            break

        # Day target_idx CPR is calculated from target_idx - 1
        prev_h = float(completed_df[col_h].iloc[target_idx - 1])
        prev_l = float(completed_df[col_l].iloc[target_idx - 1])
        prev_c = float(completed_df[col_c].iloc[target_idx - 1])

        p = (prev_h + prev_l + prev_c) / 3.0
        bc = (prev_h + prev_l) / 2.0
        tc = (p - bc) + p
        cpr_top = max(tc, bc)
        cpr_bottom = min(tc, bc)

        # On day target_idx: did price touch this CPR corridor?
        day_h = float(completed_df[col_h].iloc[target_idx])
        day_l = float(completed_df[col_l].iloc[target_idx])

        # Virgin condition: day's Low was strictly above CPR Top, OR day's High was strictly below CPR Bottom
        is_virgin_on_day = (day_l > cpr_top) or (day_h < cpr_bottom)
        if not is_virgin_on_day:
            continue

        # Day target_idx was virgin. Check if any subsequent completed day filled/touched it
        filled = False
        for sub_idx in range(target_idx + 1, total_bars):
            sub_h = float(completed_df[col_h].iloc[sub_idx])
            sub_l = float(completed_df[col_l].iloc[sub_idx])
            if sub_l <= cpr_top and sub_h >= cpr_bottom:
                filled = True
                break

        if filled:
            continue

        # Still virgin and untouched
        target_dt = completed_df.index[target_idx]
        target_dt_str = (
            target_dt.strftime("%Y-%m-%d")
            if hasattr(target_dt, "strftime")
            else str(target_dt)[:10]
        )

        if ref_price > cpr_top:
            m_bias = "MAGNET_BELOW"
            dist_pts = round(ref_price - p, 2)
        elif ref_price < cpr_bottom:
            m_bias = "MAGNET_ABOVE"
            dist_pts = round(p - ref_price, 2)
        else:
            m_bias = "AT_MAGNET"
            dist_pts = 0.0

        dist_pct = round((dist_pts / max(1.0, ref_price)) * 100.0, 3)

        active_virgin_cprs.append(
            {
                "session_date": target_dt_str,
                "age_days": offset,
                "pivot": round(p, 2),
                "tc": round(tc, 2),
                "bc": round(bc, 2),
                "top": round(cpr_top, 2),
                "bottom": round(cpr_bottom, 2),
                "status": "UNTOUCHED",
                "magnet_bias": m_bias,
                "distance_pts": dist_pts,
                "distance_pct": dist_pct,
            }
        )

    if not active_virgin_cprs:
        return {
            "has_virgin_cpr": False,
            "virgin_cprs": [],
            "nearest_magnet": None,
            "magnet_target": None,
            "magnet_bias": None,
            "distance_pts": 0.0,
            "distance_pct": 0.0,
            "summary": f"No active untested Virgin CPR found in the last {max_scan} sessions.",
        }

    # Sort by absolute distance to ref_price
    active_virgin_cprs.sort(key=lambda x: x["distance_pts"])
    nearest = active_virgin_cprs[0]

    return {
        "has_virgin_cpr": True,
        "virgin_cprs": active_virgin_cprs,
        "nearest_magnet": nearest,
        "magnet_target": nearest["pivot"],
        "magnet_bias": nearest["magnet_bias"],
        "distance_pts": nearest["distance_pts"],
        "distance_pct": nearest["distance_pct"],
        "summary": (
            f"Active Untested Virgin CPR ({nearest['session_date']}) at ₹{nearest['pivot']:,.1f} "
            f"[₹{nearest['bottom']:,.1f} - ₹{nearest['top']:,.1f}] serves as {nearest['magnet_bias'].replace('_', ' ').lower()} "
            f"({nearest['distance_pts']:,.1f} pts / {nearest['distance_pct']:.2f}% away)."
        ),
    }


def prime_daily_levels(symbols: Optional[list[str]] = None) -> dict[str, DailyLevels]:
    """Public helper to prime daily levels for all major benchmarks and symbols."""
    return daily_levels_store.prime_universe(symbols)


def calculate_intraday_rvol(
    df_5m: Optional[pd.DataFrame],
    df_daily: Optional[pd.DataFrame] = None,
    current_vol: Optional[float] = None,
) -> float:
    """
    Calculates genuine Relative Volume (RVOL) using real intraday volume bars.
    Combines Bar-Level Volume Expansion and Time-of-Day (TOD) Relative Volume.
    Returns verified RVOL (e.g. 1.85 for 1.85x volume).
    If volume data is completely absent or 0, returns 1.0 (unexpanded baseline)
    with no synthetic exaggeration.
    """
    if df_5m is None or len(df_5m) < 2:
        return 1.0

    col_v = (
        "volume" if "volume" in df_5m.columns else ("Volume" if "Volume" in df_5m.columns else None)
    )
    if not col_v:
        return 1.0

    vols = df_5m[col_v].astype(float).values
    if len(vols) == 0 or vols.sum() <= 0:
        return 1.0

    latest_v = (
        float(current_vol) if (current_vol is not None and current_vol > 0) else float(vols[-1])
    )

    # 1. Bar-level RVOL vs rolling 20-bar SMA on 5m
    lookback = min(20, len(vols) - 1)
    if lookback >= 1:
        ma_20 = float(np.mean(vols[-lookback - 1 : -1]))
    else:
        ma_20 = float(vols[0])

    bar_rvol = round(latest_v / max(1.0, ma_20), 2) if ma_20 > 0 else 1.0

    # 2. Time-of-Day (TOD) cumulative RVOL if df_daily is present
    if df_daily is not None and len(df_daily) >= 10:
        col_vd = (
            "volume"
            if "volume" in df_daily.columns
            else ("Volume" if "Volume" in df_daily.columns else None)
        )
        if col_vd:
            d_vols = df_daily[col_vd].astype(float).values
            avg_daily_vol = (
                float(np.mean(d_vols[-20:])) if len(d_vols) >= 20 else float(np.mean(d_vols))
            )
            if avg_daily_vol > 0:
                # Time-of-Day (TOD) Relative Volume calibrated against 90-day institutional Fyers volume U-curve
                from engine.index_calibration import get_empirical_tod_volume_fraction

                intraday_bars = len(df_5m)
                expected_tod_fraction = get_empirical_tod_volume_fraction(intraday_bars)
                expected_tod_vol = avg_daily_vol * expected_tod_fraction
                cum_today_vol = float(vols.sum())
                tod_rvol = round(cum_today_vol / max(1.0, expected_tod_vol), 2)
                return round(0.60 * bar_rvol + 0.40 * tod_rvol, 2)

    return bar_rvol


def calculate_intraday_cvd(
    df_5m: Optional[pd.DataFrame],
) -> tuple[float, float, str]:
    """
    Computes Cumulative Volume Delta (CVD) and institutional absorption/exhaustion tags
    from intraday 5m candle microstructure.

    Formula:
        Delta_i = Volume_i * ((Close - Low) - (High - Close)) / max(0.01, High - Low)
        CVD_t = Sum(Delta_i)

    Returns:
        (current_cvd, cvd_5bar_slope, cvd_divergence_tag)
        where cvd_divergence_tag is 'BULLISH_ABSORPTION', 'BEARISH_EXHAUSTION', or 'NEUTRAL'.
    """
    if df_5m is None or len(df_5m) < 3:
        return 0.0, 0.0, "NEUTRAL"

    col_h = "high" if "high" in df_5m.columns else "High"
    col_l = "low" if "low" in df_5m.columns else "Low"
    col_c = "close" if "close" in df_5m.columns else "Close"
    col_v = (
        "volume" if "volume" in df_5m.columns else ("Volume" if "Volume" in df_5m.columns else None)
    )

    if not all(k in df_5m.columns for k in (col_h, col_l, col_c)) or not col_v:
        return 0.0, 0.0, "NEUTRAL"

    highs = df_5m[col_h].astype(float).values
    lows = df_5m[col_l].astype(float).values
    closes = df_5m[col_c].astype(float).values
    volumes = df_5m[col_v].astype(float).values

    ranges = np.maximum(0.01, highs - lows)
    # Price close relative to bar extremes: -1.0 at absolute low, +1.0 at absolute high
    bar_pos = ((closes - lows) - (highs - closes)) / ranges
    deltas = volumes * bar_pos
    cvd_series = np.cumsum(deltas)
    current_cvd = float(cvd_series[-1])

    # 5-bar slope
    lookback = min(5, len(cvd_series) - 1)
    slope = (
        float((cvd_series[-1] - cvd_series[-1 - lookback]) / float(lookback))
        if lookback > 0
        else 0.0
    )

    divergence = "NEUTRAL"
    if len(closes) >= 6:
        price_change = float(closes[-1] - closes[-6])
        cvd_change = float(cvd_series[-1] - cvd_series[-6])

        # Bullish Absorption: Price falling or flat, but CVD delta rising strongly
        if price_change <= 0 and cvd_change > 0:
            divergence = "BULLISH_ABSORPTION"
        # Bearish Exhaustion: Price rising or flat, but CVD delta falling strongly
        elif price_change >= 0 and cvd_change < 0:
            divergence = "BEARISH_EXHAUSTION"

    return round(current_cvd, 1), round(slope, 2), divergence


def get_daily_levels_store() -> DailyLevelsStore:
    """Return global DailyLevelsStore singleton."""
    return daily_levels_store


def clear_daily_levels_cache() -> int:
    """Evicts all cached DailyLevels from RAM. Used by memory_guard."""
    store = get_daily_levels_store()
    with store._lock:
        cnt = len(store._memory_cache)
        store._memory_cache.clear()
        return cnt


try:
    from engine.memory_guard import register_trim_callback

    register_trim_callback(clear_daily_levels_cache)
except Exception as e_suppressed:
    logger.debug(f"[engine.daily_levels] Memory guard registration suppressed: {e_suppressed}")
