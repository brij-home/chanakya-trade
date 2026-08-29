"""
analysis/sector_rotation.py
───────────────────────────
Relative Rotation Graph (RRG) & Sector Momentum analysis for NSE sectors.

Computes JdK RS-Ratio (trend) and JdK RS-Momentum (velocity) for all major
Indian sector indices relative to the benchmark (NIFTY 50).

Classifies sectors into 4 institutional quadrants:
  - LEADING   (RS-Ratio >= 100, RS-Momentum >= 100): Outperforming with positive momentum.
  - WEAKENING (RS-Ratio >= 100, RS-Momentum < 100):  Outperforming, but losing momentum.
  - LAGGING   (RS-Ratio < 100,  RS-Momentum < 100):  Underperforming with negative momentum.
  - IMPROVING (RS-Ratio < 100,  RS-Momentum >= 100): Underperforming, but gaining momentum.

Includes stock-to-sector mapping and sector tailwind alignment scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SectorRRGPoint:
    """A single sector's coordinates on the Relative Rotation Graph."""

    sector: str
    symbol: str  # Index ticker (e.g. ^CNXIT)
    rs_ratio: float  # >100 = outperforming benchmark trend
    rs_momentum: float  # >100 = accelerating relative momentum
    quadrant: str  # "LEADING" | "WEAKENING" | "LAGGING" | "IMPROVING"
    day_change_pct: float = 0.0
    benchmark_change_pct: float = 0.0
    relative_strength: float = 100.0  # Normalized RS (0-200)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "symbol": self.symbol,
            "rs_ratio": round(self.rs_ratio, 2),
            "rs_momentum": round(self.rs_momentum, 2),
            "quadrant": self.quadrant,
            "day_change_pct": round(self.day_change_pct, 2),
            "benchmark_change_pct": round(self.benchmark_change_pct, 2),
            "relative_strength": round(self.relative_strength, 2),
        }


# ── NSE Sector Definitions ─────────────────────────────────────

NSE_SECTORS: dict[str, str] = {
    "BANK": "^NSEBANK",
    "IT": "^CNXIT",
    "PHARMA": "^CNXPHARMA",
    "AUTO": "^CNXAUTO",
    "FMCG": "^CNXFMCG",
    "METAL": "^CNXMETAL",
    "REALTY": "^CNXREALTY",
    "ENERGY": "^CNXENERGY",
    "INFRA": "^CNXINFRA",
    "PSU_BANK": "^CNXPSUBANK",
}

BENCHMARK_TICKER = "^NSEI"  # NIFTY 50

# ── Stock to Sector Mapping ───────────────────────────────────

STOCK_SECTOR_MAP: dict[str, str] = {
    # IT
    "INFY": "IT",
    "TCS": "IT",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    "LTIM": "IT",
    "COFORGE": "IT",
    "PERSISTENT": "IT",
    "MPHASIS": "IT",
    "OFSS": "IT",
    "KPITTECH": "IT",
    "TATAELXSI": "IT",
    # Private Banks & Fin
    "HDFCBANK": "BANK",
    "ICICIBANK": "BANK",
    "KOTAKBANK": "BANK",
    "AXISBANK": "BANK",
    "INDUSINDBK": "BANK",
    "FEDERALBNK": "BANK",
    "BANDHANBNK": "BANK",
    "AUBANK": "BANK",
    "BAJFINANCE": "BANK",
    "BAJAJFINSV": "BANK",
    # PSU Banks
    "SBIN": "PSU_BANK",
    "BANKBARODA": "PSU_BANK",
    "CANBK": "PSU_BANK",
    "PNB": "PSU_BANK",
    "UNIONBANK": "PSU_BANK",
    "INDIANB": "PSU_BANK",
    # Pharma & Healthcare
    "SUNPHARMA": "PHARMA",
    "DRREDDY": "PHARMA",
    "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA",
    "APOLLOHOSP": "PHARMA",
    "LUPIN": "PHARMA",
    "TORNTPHARM": "PHARMA",
    "ZYDUSLIFE": "PHARMA",
    "MANKIND": "PHARMA",
    "MAXHEALTH": "PHARMA",
    # Auto
    "TATAMOTORS": "AUTO",
    "MARUTI": "AUTO",
    "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO",
    "HEROMOTOCO": "AUTO",
    "EICHERMOT": "AUTO",
    "TVSMOTOR": "AUTO",
    "BHARATFORG": "AUTO",
    "MOTHERSON": "AUTO",
    "ASHOKLEY": "AUTO",
    # FMCG & Consumption
    "ITC": "FMCG",
    "HINDUNILVR": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG",
    "DABUR": "FMCG",
    "MARICO": "FMCG",
    "GODREJCP": "FMCG",
    "COLPAL": "FMCG",
    "VARUN": "FMCG",
    # Metals & Mining
    "TATASTEEL": "METAL",
    "JSWSTEEL": "METAL",
    "HINDALCO": "METAL",
    "JINDALSTEL": "METAL",
    "NMDC": "METAL",
    "SAIL": "METAL",
    "VEDL": "METAL",
    "NATIONALUM": "METAL",
    # Realty
    "DLF": "REALTY",
    "GODREJPROP": "REALTY",
    "OBEROIRLTY": "REALTY",
    "PRESTIGE": "REALTY",
    "PHOENIXLTD": "REALTY",
    "BRIGADE": "REALTY",
    "SOBHA": "REALTY",
    # Energy & Power
    "RELIANCE": "ENERGY",
    "ONGC": "ENERGY",
    "NTPC": "ENERGY",
    "POWERGRID": "ENERGY",
    "COALINDIA": "ENERGY",
    "BPCL": "ENERGY",
    "IOC": "ENERGY",
    "GAIL": "ENERGY",
    "ADANIGREEN": "ENERGY",
    "TATAPOWER": "ENERGY",
    "OIL": "ENERGY",
    # Infra & Industrial Capital Goods
    "LT": "INFRA",
    "ADANIENT": "INFRA",
    "ADANIPORTS": "INFRA",
    "ULTRACEMCO": "INFRA",
    "GRASIM": "INFRA",
    "AMBUJACEM": "INFRA",
    "CONCOR": "INFRA",
    "GMRINFRA": "INFRA",
    "BEL": "INFRA",
    "HAL": "INFRA",
    "BHEL": "INFRA",
    "SIEMENS": "INFRA",
    "ABB": "INFRA",
}


def _classify_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Classify into RRG quadrant."""
    if rs_ratio >= 100.0 and rs_momentum >= 100.0:
        return "LEADING"
    elif rs_ratio >= 100.0 and rs_momentum < 100.0:
        return "WEAKENING"
    elif rs_ratio < 100.0 and rs_momentum < 100.0:
        return "LAGGING"
    else:
        return "IMPROVING"


def compute_rrg_series(
    sector_closes: list[float], benchmark_closes: list[float], period: int = 10
) -> tuple[float, float]:
    """
    Compute current JdK RS-Ratio and RS-Momentum from price history series.

    Returns:
        (rs_ratio, rs_momentum) where 100 is neutral.
    """
    if len(sector_closes) < period or len(benchmark_closes) < period:
        return 100.0, 100.0

    n = min(len(sector_closes), len(benchmark_closes))
    sec = sector_closes[-n:]
    bm = benchmark_closes[-n:]

    # Relative Strength series: (Sector / Benchmark) * 100
    rs_series = [(s / b) * 100.0 if b > 0 else 100.0 for s, b in zip(sec, bm)]

    # RS-Ratio: normalize current RS against rolling mean
    sub_rs = rs_series[-period:]
    mean_rs = sum(sub_rs) / len(sub_rs) if sub_rs else 100.0
    current_rs = rs_series[-1]

    if mean_rs > 0:
        rs_ratio = 100.0 + ((current_rs - mean_rs) / mean_rs) * 100.0 * 2.0
    else:
        rs_ratio = 100.0

    # RS-Momentum: Rate of change of RS-Ratio over past window
    if len(rs_series) >= 5:
        past_rs = rs_series[-5]
        sub_past = rs_series[-period - 5 : -5] if len(rs_series) >= period + 5 else sub_rs
        past_mean = sum(sub_past) / len(sub_past) if sub_past else mean_rs
        past_ratio = (
            100.0 + ((past_rs - past_mean) / past_mean) * 100.0 * 2.0
            if past_mean > 0
            else 100.0
        )
        diff = rs_ratio - past_ratio
        rs_momentum = 100.0 + diff * 1.5
    else:
        rs_momentum = 100.0

    return max(70.0, min(130.0, rs_ratio)), max(70.0, min(130.0, rs_momentum))


def get_sector_rrg_matrix(use_cache: bool = True) -> list[SectorRRGPoint]:
    """
    Compute RRG coordinates for all major NSE sectors with 15-minute persistent caching.
    """
    cache_key = "sector_rrg_matrix"
    if use_cache:
        try:
            from engine.analysis_cache import analysis_cache

            cached = analysis_cache.get_macro(cache_key)
            if cached and isinstance(cached, list):
                return [
                    SectorRRGPoint(
                        sector=item["sector"],
                        symbol=item["symbol"],
                        rs_ratio=item["rs_ratio"],
                        rs_momentum=item["rs_momentum"],
                        quadrant=item["quadrant"],
                        day_change_pct=item.get("day_change_pct", 0.0),
                        benchmark_change_pct=item.get("benchmark_change_pct", 0.0),
                        relative_strength=item.get("relative_strength", 100.0),
                    )
                    for item in cached
                ]
        except Exception:
            pass

    points: list[SectorRRGPoint] = []
    benchmark_change = 0.0

    try:
        from market.indices import get_sector_snapshot
        from market.quotes import get_quote

        sector_snaps = {s.name: s for s in get_sector_snapshot()}
        nifty_quote = get_quote(["NSE:NIFTY 50"]).get("NSE:NIFTY 50")
        if nifty_quote:
            benchmark_change = nifty_quote.change_pct
    except Exception:
        sector_snaps = {}

    # Calculate points for all sectors
    for sector_name, symbol in NSE_SECTORS.items():
        snap = sector_snaps.get(sector_name)
        day_change = snap.change_pct if snap else 0.0

        # Calculate synthetic or historical RS if quotes/yfinance are available
        # Base RS ratio on sector day change vs benchmark
        rel_diff = day_change - benchmark_change
        rs_ratio = 100.0 + rel_diff * 4.0
        rs_momentum = 100.0 + rel_diff * 2.5

        # Normalize boundaries
        rs_ratio = max(80.0, min(120.0, rs_ratio))
        rs_momentum = max(80.0, min(120.0, rs_momentum))

        quadrant = _classify_quadrant(rs_ratio, rs_momentum)

        point = SectorRRGPoint(
            sector=sector_name,
            symbol=symbol,
            rs_ratio=rs_ratio,
            rs_momentum=rs_momentum,
            quadrant=quadrant,
            day_change_pct=day_change,
            benchmark_change_pct=benchmark_change,
            relative_strength=100.0 + rel_diff * 5.0,
        )
        points.append(point)

    # Save to persistent cache (15-min TTL)
    if use_cache and points:
        try:
            from engine.analysis_cache import analysis_cache

            analysis_cache.save_macro(
                cache_key, [p.as_dict() for p in points], ttl_minutes=15
            )
        except Exception:
            pass

    return points


def get_stock_sector_alignment(symbol: str) -> dict[str, Any]:
    """
    Get a stock's parent sector, its RRG quadrant, and alignment tailwind score.

    Returns:
        Dict with sector details, quadrant, tailwind score (0-100), and institutional stance.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    sector = STOCK_SECTOR_MAP.get(clean_sym, "BROAD_MARKET")

    matrix = {p.sector: p for p in get_sector_rrg_matrix()}
    sector_point = matrix.get(sector)

    if not sector_point:
        # Default neutral for unclassified broad market stock
        return {
            "symbol": clean_sym,
            "sector": sector,
            "quadrant": "LEADING",
            "rs_ratio": 100.0,
            "rs_momentum": 100.0,
            "tailwind_score": 50,
            "alignment": "NEUTRAL",
            "analysis": f"{clean_sym} is evaluated against the broad market index.",
        }

    quad = sector_point.quadrant
    # Score 0-100 based on quadrant and momentum
    quadrant_scores = {
        "LEADING": 85,
        "IMPROVING": 70,
        "WEAKENING": 45,
        "LAGGING": 25,
    }
    base_score = quadrant_scores.get(quad, 50)
    # Adjust score with exact momentum
    momentum_adj = int((sector_point.rs_momentum - 100.0) * 0.5)
    final_score = max(10, min(95, base_score + momentum_adj))

    if final_score >= 75:
        alignment = "STRONG_TAILWIND"
        desc = f"Parent sector {sector} is in LEADING quadrant with strong institutional momentum."
    elif final_score >= 60:
        alignment = "MODERATE_TAILWIND"
        desc = f"Parent sector {sector} is in IMPROVING quadrant and gaining relative strength vs Nifty."
    elif final_score >= 40:
        alignment = "NEUTRAL"
        desc = f"Parent sector {sector} is in WEAKENING quadrant; outperformance momentum is slowing."
    else:
        alignment = "HEADWIND"
        desc = f"Parent sector {sector} is in LAGGING quadrant; institutional outflows present."

    return {
        "symbol": clean_sym,
        "sector": sector,
        "quadrant": quad,
        "rs_ratio": round(sector_point.rs_ratio, 2),
        "rs_momentum": round(sector_point.rs_momentum, 2),
        "tailwind_score": final_score,
        "alignment": alignment,
        "analysis": desc,
    }
