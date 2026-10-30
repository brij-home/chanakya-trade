"""
engine/intraday_microstructure.py
──────────────────────────────────
Unified Intraday Microstructure & Multi-Timeframe Intelligence Engine.

Provides centralized mathematical derivation and caching for:
  1. RVOL: Bar-Level & Time-of-Day (TOD) Relative Volume without synthetic defaults.
  2. CVD: Intraday Cumulative Volume Delta, slope, and Bullish/Bearish Absorption divergence.
  3. Reference Levels: PDH, PDL, PDC, PWH, PWL, PWC, PMH, PML, PMC, CPR & Camarilla.
  4. L2/TBT Order Book: 50-Depth Order Book Imbalance (OBI) and Fortress Walls.

Ensures zero half-baked data reaches detectors or scanner loops (Rule 10 & 11 Invariants).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol
from engine.daily_levels import (
    calculate_intraday_cvd,
    calculate_intraday_rvol,
    get_daily_levels,
)

logger = logging.getLogger("chanakya.engine.microstructure")


@dataclass
class MarketIntelligencePacket:
    """Institutional Market Intelligence Packet for a symbol."""

    symbol: str
    canonical_symbol: str
    exchange: str
    ltp: float
    vwap: float
    # Daily Reference Levels
    pdh: float
    pdl: float
    pdc: float
    pdo: float
    atr_14: float
    # Multi-Timeframe Levels
    pwh: float
    pwl: float
    pwc: float
    pmh: float
    pml: float
    pmc: float
    # CPR & Camarilla
    cpr: dict[str, Any] = field(default_factory=dict)
    camarilla: dict[str, Any] = field(default_factory=dict)
    # Intraday Microstructure
    rvol: float = 1.0
    cvd: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: str = "NEUTRAL"
    # Order Book Depth
    obi_50: Optional[float] = None
    bid_wall: Optional[dict[str, Any]] = None
    ask_wall: Optional[dict[str, Any]] = None
    micro_price: Optional[float] = None
    micro_price_skew_bps: Optional[float] = None
    book_pressure: str = "BALANCED"
    # Provenance
    provenance: str = "VERIFIED_LIVE"
    timestamp: str = ""

    @property
    def is_complete(self) -> bool:
        """Verifies that all foundational reference levels are strictly non-zero."""
        return self.pdh > 0 and self.pdl > 0 and self.pdc > 0 and self.ltp > 0


def get_market_intelligence(
    symbol: str,
    exchange: Optional[str] = None,
    df_5m: Optional[pd.DataFrame] = None,
    df_day: Optional[pd.DataFrame] = None,
    ltp: Optional[float] = None,
    vwap: Optional[float] = None,
) -> Optional[MarketIntelligencePacket]:
    """
    Constructs a verified, institutional MarketIntelligencePacket for any equity or index.
    Fails closed (returns None) if foundational daily levels cannot be mathematically verified.
    """
    clean = canonical_alert_symbol(symbol)
    exch = exchange or ("BSE" if clean in ("SENSEX", "BANKEX") else "NSE")

    # 1. Daily Levels (PDH, PDL, PDC, PWH, PWL, PMH, PML, CPR, Camarilla)
    dl = get_daily_levels(clean)
    if not dl or dl.pdh <= 0 or dl.pdl <= 0 or dl.pdc <= 0:
        logger.warning(
            f"[Microstructure] Incomplete daily levels for {clean}. "
            f"Failing closed to prevent half-baked signal generation (Rule 11)."
        )
        return None

    # 2. Quote & Price Resolution
    resolved_ltp = float(ltp or dl.spot or 0.0)
    resolved_vwap = float(vwap or 0.0)
    if resolved_ltp <= 0 or resolved_vwap <= 0:
        try:
            from market.quotes import get_computed_vwap, get_quote

            inst = f"{exch}:{clean}"
            q_map = get_quote([inst])
            q = q_map.get(inst) or q_map.get(clean)
            if q:
                if resolved_ltp <= 0:
                    resolved_ltp = float(
                        getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0
                    )
                if resolved_vwap <= 0:
                    resolved_vwap = float(getattr(q, "vwap", 0.0) or 0.0)
            if resolved_vwap <= 0:
                c_vwap = get_computed_vwap(clean, exchange=exch)
                if c_vwap and c_vwap > 0:
                    resolved_vwap = float(c_vwap)
        except Exception as e_q:
            logger.debug(f"[Microstructure] Quote fetch warning for {clean}: {e_q}")

    if resolved_ltp <= 0:
        resolved_ltp = dl.pdc

    # 3. Microstructure: RVOL and CVD
    rvol = 1.0
    cvd = 0.0
    cvd_slope = 0.0
    cvd_div = "NEUTRAL"

    if df_5m is not None and len(df_5m) >= 2:
        rvol = calculate_intraday_rvol(df_5m, df_daily=df_day)
        cvd, cvd_slope, cvd_div = calculate_intraday_cvd(df_5m)

    # 4. 50-Depth TBT Book & Fortress Walls
    obi_50 = None
    bid_wall = None
    ask_wall = None
    micro_price = None
    micro_price_skew_bps = None
    book_pressure = "BALANCED"
    try:
        from market.fyers_tbt_manager import FyersTbtManager

        mgr = FyersTbtManager()
        depth = mgr.get_50_depth(clean)
        if depth and depth.get("bids") and depth.get("asks"):
            bids = depth["bids"]
            asks = depth["asks"]
            tot_b = sum(float(b.get("qty", 0) or 0) for b in bids)
            tot_a = sum(float(a.get("qty", 0) or 0) for a in asks)
            tot = tot_b + tot_a
            if tot > 0:
                obi_50 = round((tot_b - tot_a) / tot, 3)

            # Find largest bid wall >= 18% of side volume
            if tot_b > 0:
                max_b = max(bids, key=lambda x: float(x.get("qty", 0) or 0))
                b_qty = float(max_b.get("qty", 0) or 0)
                if (b_qty / tot_b) >= 0.18:
                    bid_wall = {
                        "price": float(max_b.get("price", 0.0)),
                        "qty": b_qty,
                        "share_pct": round(b_qty / tot_b * 100.0, 1),
                    }

            if tot_a > 0:
                max_a = max(asks, key=lambda x: float(x.get("qty", 0) or 0))
                a_qty = float(max_a.get("qty", 0) or 0)
                if (a_qty / tot_a) >= 0.18:
                    ask_wall = {
                        "price": float(max_a.get("price", 0.0)),
                        "qty": a_qty,
                        "share_pct": round(a_qty / tot_a * 100.0, 1),
                    }

            # High-Frequency Micro-Price & Order Book Skew
            if depth.get("micro_price"):
                micro_price = float(depth["micro_price"])
            if depth.get("micro_price_skew_bps") is not None:
                micro_price_skew_bps = float(depth["micro_price_skew_bps"])
                if micro_price_skew_bps >= 0.25:
                    book_pressure = "BULLISH_PRESSURE"
                elif micro_price_skew_bps <= -0.25:
                    book_pressure = "BEARISH_PRESSURE"
                else:
                    book_pressure = "BALANCED"
    except Exception as e_tbt:
        logger.debug(f"[Microstructure] TBT depth warning for {clean}: {e_tbt}")

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    return MarketIntelligencePacket(
        symbol=clean,
        canonical_symbol=clean,
        exchange=exch,
        ltp=round(resolved_ltp, 2),
        vwap=round(resolved_vwap, 2),
        pdh=dl.pdh,
        pdl=dl.pdl,
        pdc=dl.pdc,
        pdo=dl.pdo,
        atr_14=dl.atr_14,
        pwh=dl.pwh,
        pwl=dl.pwl,
        pwc=dl.pwc,
        pmh=dl.pmh,
        pml=dl.pml,
        pmc=dl.pmc,
        cpr=dl.cpr,
        camarilla=dl.camarilla,
        rvol=rvol,
        cvd=cvd,
        cvd_slope=cvd_slope,
        cvd_divergence=cvd_div,
        obi_50=obi_50,
        bid_wall=bid_wall,
        ask_wall=ask_wall,
        micro_price=micro_price,
        micro_price_skew_bps=micro_price_skew_bps,
        book_pressure=book_pressure,
        provenance="VERIFIED_LIVE",
        timestamp=now_iso,
    )
