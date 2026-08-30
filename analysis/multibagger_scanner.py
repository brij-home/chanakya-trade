"""
analysis/multibagger_scanner.py
───────────────────────────────
High-Performance Institutional Batch Screener & Multibagger Ranking Engine.

Features:
  1. Parallel multi-threaded scanning across NIFTY 500, Microcap 250, BSE 500, or Custom Watchlists.
  2. Multi-Horizon Filtering:
     - "SHORT_TERM": Ranks by VCP pivot proximity, RVOL expansion, and immediate momentum.
     - "MID_TERM": Ranks by Weinstein Stage 2 markup, Minervini 8/8 template, and 52W High proximity.
     - "LONG_TERM": Ranks by Vijay Kedia SMILE, ROCE (>18%), and Forensic cleanliness.
     - "ALL_HORIZONS": Composite weighted rank.
  3. Conviction Tiers:
     - 🟢 HIGH_CONVICTION (Score >= 78)
     - 🟡 STALK_RADAR (Score 60 - 77)
     - ⚪ DEVELOPING (Score < 60)
  4. Integration with Analysis Cache & Fast In-Memory Pipelines.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Optional

import pandas as pd

from analysis.multibagger import MultibaggerReport, scan_multibagger_opportunity
from analysis.universe import THEMATIC_PRESETS, resolve_dynamic_universe


@dataclass
class MultibaggerCandidate:
    symbol: str
    ltp: float
    multibagger_score: int
    category: str
    best_horizon: str
    short_term_score: int
    short_term_verdict: str
    mid_term_score: int
    mid_term_verdict: str
    long_term_score: int
    long_term_verdict: str
    weinstein_stage: str
    vcp_detected: bool
    vcp_pivot_price: float
    sector: str
    sector_tailwind_score: int
    forensic_safe: bool
    conviction_tier: str  # "🟢 HIGH_CONVICTION" | "🟡 STALK_RADAR" | "⚪ DEVELOPING"
    catalyst_notes: str
    suggested_entry_strategy: str
    execution_ticket: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MultibaggerScanResult:
    universe_id: str
    universe_name: str
    horizon_filter: str
    total_scanned: int
    total_qualified: int
    candidates: list[MultibaggerCandidate] = field(default_factory=list)
    top_sectors: list[dict[str, Any]] = field(default_factory=list)
    scan_timestamp: str = ""
    execution_time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "universe_name": self.universe_name,
            "horizon_filter": self.horizon_filter,
            "total_scanned": self.total_scanned,
            "total_qualified": self.total_qualified,
            "candidates": [c.to_dict() for c in self.candidates],
            "top_sectors": self.top_sectors,
            "scan_timestamp": self.scan_timestamp,
            "execution_time_seconds": self.execution_time_seconds,
        }


def _process_single_stock(
    symbol: str,
    exchange: str = "NSE",
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
) -> Optional[MultibaggerReport]:
    """Worker task scanning a single symbol."""
    try:
        df = df_cache.get(symbol) if df_cache else None
        return scan_multibagger_opportunity(symbol, df=df, exchange=exchange)
    except Exception:
        return None


def scan_multibagger_universe(
    universe: str = "multibagger_hunters",
    horizon: str = "ALL_HORIZONS",
    min_conviction: int = 50,
    max_results: int = 25,
    exchange: str = "NSE",
    parallel_workers: int = 8,
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
) -> MultibaggerScanResult:
    """
    Executes a parallel multi-threaded scan across the requested universe,
    evaluating 3-horizon potential and ranking candidates.
    """
    t0 = time.perf_counter()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Resolve symbols from universe
    symbols, universe_desc = resolve_dynamic_universe(universe, max_stocks=120)
    if not symbols:
        symbols = THEMATIC_PRESETS.get("multibagger_hunters", {}).get("symbols", ["TRENT", "DIXON", "HAL", "BEL", "BSE"])

    u_name = THEMATIC_PRESETS.get(universe.lower(), {}).get("name", universe_desc)
    norm_horizon = horizon.upper().strip()
    if norm_horizon not in ("SHORT_TERM", "MID_TERM", "LONG_TERM", "ALL_HORIZONS"):
        norm_horizon = "ALL_HORIZONS"

    # 2. Parallel Evaluation
    reports: list[MultibaggerReport] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        future_map = {
            executor.submit(_process_single_stock, sym, exchange, df_cache): sym
            for sym in symbols
        }
        for future in concurrent.futures.as_completed(future_map):
            rep = future.result()
            if rep and rep.ltp > 0:
                reports.append(rep)

    # 3. Filter & Sort by Horizon
    candidates: list[MultibaggerCandidate] = []
    for r in reports:
        # Determine ranking score based on horizon
        if norm_horizon == "SHORT_TERM":
            rank_score = r.short_term_score
        elif norm_horizon == "MID_TERM":
            rank_score = r.mid_term_score
        elif norm_horizon == "LONG_TERM":
            rank_score = r.long_term_score
        else:
            rank_score = r.multibagger_score

        if rank_score < min_conviction:
            continue

        # Conviction Tier
        if rank_score >= 78:
            tier = "🟢 HIGH_CONVICTION"
        elif rank_score >= 60:
            tier = "🟡 STALK_RADAR"
        else:
            tier = "⚪ DEVELOPING"

        candidates.append(
            MultibaggerCandidate(
                symbol=r.symbol,
                ltp=r.ltp,
                multibagger_score=r.multibagger_score,
                category=r.category,
                best_horizon=r.best_horizon,
                short_term_score=r.short_term_score,
                short_term_verdict=r.short_term_verdict,
                mid_term_score=r.mid_term_score,
                mid_term_verdict=r.mid_term_verdict,
                long_term_score=r.long_term_score,
                long_term_verdict=r.long_term_verdict,
                weinstein_stage=r.weinstein_stage,
                vcp_detected=r.vcp_detected,
                vcp_pivot_price=r.vcp_pivot_price,
                sector=r.sector,
                sector_tailwind_score=r.sector_tailwind_score,
                forensic_safe=r.forensic_safe,
                conviction_tier=tier,
                catalyst_notes=r.catalyst_notes,
                suggested_entry_strategy=r.suggested_entry_strategy,
                execution_ticket=r.execution_ticket,
            )
        )

    # Sort descending by target horizon score
    if norm_horizon == "SHORT_TERM":
        candidates.sort(key=lambda x: x.short_term_score, reverse=True)
    elif norm_horizon == "MID_TERM":
        candidates.sort(key=lambda x: x.mid_term_score, reverse=True)
    elif norm_horizon == "LONG_TERM":
        candidates.sort(key=lambda x: x.long_term_score, reverse=True)
    else:
        candidates.sort(key=lambda x: x.multibagger_score, reverse=True)

    final_candidates = candidates[:max_results]

    # Sector summary
    sector_counts: dict[str, int] = {}
    for c in final_candidates:
        sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1

    top_sectors = [
        {"sector": sec, "count": count}
        for sec, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    t1 = time.perf_counter()

    return MultibaggerScanResult(
        universe_id=universe,
        universe_name=u_name,
        horizon_filter=norm_horizon,
        total_scanned=len(symbols),
        total_qualified=len(candidates),
        candidates=final_candidates,
        top_sectors=top_sectors,
        scan_timestamp=timestamp_str,
        execution_time_seconds=round(t1 - t0, 3),
    )
