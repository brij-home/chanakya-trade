"""
analysis/relative_strength.py
──────────────────────────────
Institutional Intraday Relative Strength (RS) & Relative Weakness (RW) Radar.

Compares underlying liquid equities (F&O / Top Market Cap) against the benchmark index
(NSE:NIFTY50-INDEX) in real-time:
  - Relative Strength (RS): Stocks outperforming the benchmark, trading above intraday VWAP,
    and exhibiting institutional accumulation (especially "Decoupled Alpha" when Nifty is flat/red).
  - Relative Weakness (RW): Stocks underperforming the benchmark, trading below intraday VWAP,
    and exhibiting institutional distribution (especially "Systemic Breakdown" when Nifty is green).

Incorporates Sector RRG (Relative Rotation Graph) quadrant confluence and provides sub-second
cached lookups for high-density terminal UIs and auto-alert engines.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import market.quotes as market_quotes
from brokers.base import Quote

logger = logging.getLogger("analysis.relative_strength")
IST = ZoneInfo("Asia/Kolkata")

_CACHE_LOCK = None
_RSRW_CACHE: dict[str, Any] = {}
_CACHE_TTL_SECONDS = 15.0


def _get_lock():
    global _CACHE_LOCK
    if _CACHE_LOCK is None:
        import threading

        _CACHE_LOCK = threading.Lock()
    return _CACHE_LOCK


@dataclass
class StockRSRWItem:
    symbol: str
    clean_symbol: str
    ltp: float
    change_pct: float
    net_rs: float  # Stock change % minus benchmark change %
    vwap: Optional[float] = None
    above_vwap: Optional[bool] = None
    volume: int = 0
    sector: str = "BROAD_MARKET"
    sector_quadrant: str = "UNKNOWN"
    bias: str = "NEUTRAL"  # "RELATIVE_STRENGTH" | "RELATIVE_WEAKNESS" | "NEUTRAL"
    catalyst_badge: str = (
        ""  # "DECOUPLED_ALPHA" | "ACCUMULATION" | "DISTRIBUTION" | "SYSTEMIC_BREAKDOWN"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RSRWReport:
    status: str
    benchmark_symbol: str
    benchmark_ltp: float
    benchmark_change_pct: float
    benchmark_state: str  # "BULLISH" | "BEARISH" | "SIDEWAYS"
    leaders: list[StockRSRWItem] = field(default_factory=list)
    laggards: list[StockRSRWItem] = field(default_factory=list)
    total_scanned: int = 0
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["leaders"] = [
            item.to_dict() if hasattr(item, "to_dict") else item for item in self.leaders
        ]
        d["laggards"] = [
            item.to_dict() if hasattr(item, "to_dict") else item for item in self.laggards
        ]
        return d


def compute_intraday_rs_rw(
    universe: Optional[list[str]] = None,
    benchmark_symbol: str = "NSE:NIFTY50-INDEX",
    top_n: int = 15,
    bypass_cache: bool = False,
    quotes_map: Optional[dict[str, Quote]] = None,
) -> RSRWReport:
    """
    Computes real-time Intraday Relative Strength (RS) and Relative Weakness (RW)
    for a given universe vs the benchmark index.

    Returns an institutional RSRWReport separating top institutional accumulation leaders
    from distribution laggards.
    """
    now = time.time()
    cache_key = f"rs_rw_{benchmark_symbol}_{top_n}_{len(universe or [])}"

    if not bypass_cache and quotes_map is None:
        with _get_lock():
            cached = _RSRW_CACHE.get(cache_key)
            if cached and (now - cached.get("timestamp", 0.0)) < _CACHE_TTL_SECONDS:
                return cached["report"]

    # 1. Resolve Universe Symbols
    if universe:
        symbols_to_scan = list(universe)
    else:
        try:
            from analysis.universe import THEMATIC_PRESETS

            symbols_to_scan = list(THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", []))
            if not symbols_to_scan:
                symbols_to_scan = list(THEMATIC_PRESETS.get("nifty50", {}).get("symbols", []))
        except Exception as e_univ:
            logger.debug(f"[analysis.relative_strength] Universe resolution notice: {e_univ}")
            symbols_to_scan = [
                "RELIANCE",
                "TCS",
                "HDFCBANK",
                "INFY",
                "ICICIBANK",
                "SBIN",
                "BHARTIARTL",
            ]

    # Normalize symbols to have exchange prefix
    norm_symbols: list[str] = []
    clean_map: dict[str, str] = {}
    for s in symbols_to_scan:
        clean = s.replace("NSE:", "").replace("BSE:", "").strip().upper()
        if not clean:
            continue
        full_sym = f"NSE:{clean}" if ":" not in s else s
        norm_symbols.append(full_sym)
        clean_map[full_sym] = clean

    # 2. Fetch or Extract Quotes
    all_needed = norm_symbols + [benchmark_symbol]
    if quotes_map is not None:
        raw_quotes = quotes_map
    else:
        try:
            raw_quotes = market_quotes.get_quote(all_needed, priority="NORMAL")
        except Exception as e_quotes:
            logger.warning(f"[analysis.relative_strength] Quotes fetch failed: {e_quotes}")
            return RSRWReport(
                status="UNAVAILABLE",
                benchmark_symbol=benchmark_symbol,
                benchmark_ltp=0.0,
                benchmark_change_pct=0.0,
                benchmark_state="UNKNOWN",
                generated_at=datetime.now(IST).isoformat(),
            )

    # 3. Benchmark Snapshot
    bench_quote = raw_quotes.get(benchmark_symbol)
    if not bench_quote or not getattr(bench_quote, "last_price", 0.0):
        # Try fallback lookup without prefix
        bench_clean = benchmark_symbol.replace("NSE:", "").replace("BSE:", "")
        bench_quote = raw_quotes.get(bench_clean)

    if not bench_quote or not getattr(bench_quote, "last_price", 0.0):
        return RSRWReport(
            status="UNAVAILABLE",
            benchmark_symbol=benchmark_symbol,
            benchmark_ltp=0.0,
            benchmark_change_pct=0.0,
            benchmark_state="UNKNOWN",
            generated_at=datetime.now(IST).isoformat(),
        )

    bench_ltp = float(getattr(bench_quote, "last_price", 0.0) or 0.0)
    bench_chg_pct = float(getattr(bench_quote, "change_pct", 0.0) or 0.0)

    if bench_chg_pct > 0.35:
        bench_state = "BULLISH"
    elif bench_chg_pct < -0.35:
        bench_state = "BEARISH"
    else:
        bench_state = "SIDEWAYS"

    # 4. Resolve Sector Mappings & RRG Matrix
    from analysis.sector_rotation import STOCK_SECTOR_MAP, get_sector_rrg_matrix

    sector_quad_map: dict[str, str] = {}
    try:
        rrg_pts = get_sector_rrg_matrix(use_cache=True)
        if isinstance(rrg_pts, list):
            for pt in rrg_pts:
                sec_name = getattr(pt, "sector", "") or (
                    pt.get("sector") if isinstance(pt, dict) else ""
                )
                quad = getattr(pt, "quadrant", "") or (
                    pt.get("quadrant") if isinstance(pt, dict) else ""
                )
                if sec_name:
                    sector_quad_map[sec_name.upper()] = quad
    except Exception as e_sec:
        logger.debug(f"[analysis.relative_strength] Sector RRG resolution notice: {e_sec}")

    # 5. Evaluate Equities
    items: list[StockRSRWItem] = []

    for full_sym in norm_symbols:
        q = raw_quotes.get(full_sym)
        if not q:
            clean_s = clean_map.get(full_sym, "")
            q = raw_quotes.get(clean_s)

        if not q or not getattr(q, "last_price", 0.0):
            continue

        ltp = float(getattr(q, "last_price", 0.0) or 0.0)
        chg_pct = float(getattr(q, "change_pct", 0.0) or 0.0)
        net_rs = round(chg_pct - bench_chg_pct, 2)
        vwap = getattr(q, "vwap", None)
        vol = int(getattr(q, "volume", 0) or 0)

        above_vwap = None
        if vwap and float(vwap) > 0:
            above_vwap = ltp >= float(vwap)

        clean_sym = clean_map.get(full_sym, full_sym)
        sector = STOCK_SECTOR_MAP.get(clean_sym, "BROAD_MARKET")
        quadrant = sector_quad_map.get(sector.upper(), "UNKNOWN")

        # Classify Bias and Badges
        bias = "NEUTRAL"
        badge = ""

        if net_rs > 0:
            bias = "RELATIVE_STRENGTH"
            if bench_chg_pct <= -0.15 and chg_pct >= 0.40:
                badge = "DECOUPLED_ALPHA"
            elif above_vwap is True and chg_pct >= 1.0:
                badge = "ACCUMULATION"
            elif quadrant in ("LEADING", "IMPROVING"):
                badge = "SECTOR_TAILWIND"
        elif net_rs < 0:
            bias = "RELATIVE_WEAKNESS"
            if bench_chg_pct >= 0.15 and chg_pct <= -0.40:
                badge = "SYSTEMIC_BREAKDOWN"
            elif above_vwap is False and chg_pct <= -1.0:
                badge = "DISTRIBUTION"
            elif quadrant in ("LAGGING", "WEAKENING"):
                badge = "SECTOR_DRAG"

        items.append(
            StockRSRWItem(
                symbol=full_sym,
                clean_symbol=clean_sym,
                ltp=ltp,
                change_pct=round(chg_pct, 2),
                net_rs=net_rs,
                vwap=round(float(vwap), 2) if vwap else None,
                above_vwap=above_vwap,
                volume=vol,
                sector=sector,
                sector_quadrant=quadrant,
                bias=bias,
                catalyst_badge=badge,
            )
        )

    # 6. Partition into Leaders and Laggards
    leaders = sorted(
        [i for i in items if i.bias == "RELATIVE_STRENGTH"],
        key=lambda x: x.net_rs,
        reverse=True,
    )[:top_n]

    laggards = sorted(
        [i for i in items if i.bias == "RELATIVE_WEAKNESS"],
        key=lambda x: x.net_rs,
    )[:top_n]

    report = RSRWReport(
        status="OK",
        benchmark_symbol=benchmark_symbol,
        benchmark_ltp=round(bench_ltp, 2),
        benchmark_change_pct=round(bench_chg_pct, 2),
        benchmark_state=bench_state,
        leaders=leaders,
        laggards=laggards,
        total_scanned=len(items),
        generated_at=datetime.now(IST).isoformat(),
    )

    # Cache report
    if quotes_map is None:
        with _get_lock():
            _RSRW_CACHE[cache_key] = {"report": report, "timestamp": now}

    return report
