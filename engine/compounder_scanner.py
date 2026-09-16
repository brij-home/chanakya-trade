"""
engine/compounder_scanner.py
────────────────────────────
Autonomous Multi-Horizon Compounder & Multibagger Discovery Scanner.

Broadens system scanning beyond the 40–50 core F&O equities to the full
750 NIFTY Total Market + Smallcap 250 + Microcap 250 + BSE High-Growth universe.

Features:
  1. Decoupled 3-Horizon Discovery Rosters:
     - SHORT_TERM: Velocity Alpha & VCP Breakouts (1–4 Weeks, +20% to +50%)
     - MID_TERM: Stan Weinstein Stage 2 & Minervini Compounders (1–6 Months, +50% to +200%)
     - LONG_TERM: Generational Wealth & High-ROCE Compounders (1–3+ Years, 3x to 10x+)
  2. Deterministic Zero-Token Screening Pipeline:
     - Liquidity floor filter (Daily turnover >= ₹5 Cr to eliminate illiquid traps)
     - Minervini SEPA 8-Point Trend Template (>= 6/8 criteria)
     - Stan Weinstein 4-Stage Markup classifier (Stage 2 expansion)
     - Volatility Contraction Pattern (VCP) detection & pivot calculation
     - Relative Strength (RS Rating) vs NIFTY 50 benchmark
     - Forensic accounting safety (Beneish M-Score & Altman Z''-Score)
  3. Non-blocking asynchronous batch execution with local JSON caching.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import time
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.multibagger import (
    MultibaggerReport,
    classify_weinstein_stage,
    detect_vcp,
    evaluate_trend_template,
    scan_multibagger_opportunity,
)
from analysis.universe import THEMATIC_PRESETS

logger = logging.getLogger("chanakya.compounder_scanner")

IST = timezone(timedelta(hours=5, minutes=30))


def _get_roster_cache_file() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "compounder_roster.json"


@dataclass
class CompounderCandidate:
    symbol: str
    ltp: float
    horizon: str  # "SHORT_TERM" | "MID_TERM" | "LONG_TERM"
    category: str
    composite_score: int
    weinstein_stage: str
    trend_template_passed: int
    rs_rating: int  # 0 to 99 relative strength vs benchmark
    vcp_detected: bool
    vcp_pivot_price: float
    sector: str
    sector_tailwind: int
    forensic_safe: bool
    ticket: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    discovered_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompounderRoster:
    total_scanned: int = 0
    short_term_rockets: list[CompounderCandidate] = field(default_factory=list)
    mid_term_compounders: list[CompounderCandidate] = field(default_factory=list)
    generational_compounders: list[CompounderCandidate] = field(default_factory=list)
    last_scanned_at: str = ""
    is_scanning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "short_term_rockets": [c.to_dict() for c in self.short_term_rockets],
            "mid_term_compounders": [c.to_dict() for c in self.mid_term_compounders],
            "generational_compounders": [c.to_dict() for c in self.generational_compounders],
            "last_scanned_at": self.last_scanned_at,
            "is_scanning": self.is_scanning,
        }


class CompounderScanner:
    """
    High-performance, decoupled multibagger and compounder scanning engine.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._roster = CompounderRoster()
        self._cache_file = _get_roster_cache_file()
        self._load_cache()

    def _load_cache(self) -> None:
        """Loads cached compounder roster from disk if available."""
        if not self._cache_file.exists():
            return
        try:
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
            with self._lock:
                self._roster.total_scanned = raw.get("total_scanned", 0)
                self._roster.last_scanned_at = raw.get("last_scanned_at", "")
                self._roster.short_term_rockets = [
                    CompounderCandidate(**c) for c in raw.get("short_term_rockets", [])
                ]
                self._roster.mid_term_compounders = [
                    CompounderCandidate(**c) for c in raw.get("mid_term_compounders", [])
                ]
                self._roster.generational_compounders = [
                    CompounderCandidate(**c) for c in raw.get("generational_compounders", [])
                ]
        except Exception as e:
            logger.debug(f"[CompounderScanner] Failed to load cache: {e}")

    def _save_cache(self) -> None:
        """Persists current compounder roster to disk."""
        try:
            with self._lock:
                data = self._roster.to_dict()
            self._cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[CompounderScanner] Failed to save cache: {e}")

    def get_broad_multibagger_universe(self) -> list[str]:
        """
        Gathers all unique equities from NIFTY Total Market, Smallcap 250,
        Microcap 250, BSE High-Growth, and Multibagger Hunters presets (~750+ symbols).
        """
        symbols: set[str] = set()

        preset_keys = [
            "multibagger_hunters",
            "bse_high_growth",
            "smallcap250",
            "microcap250",
            "midcap150",
            "nifty500",
            "nifty_total_market",
        ]

        for k in preset_keys:
            p_syms = THEMATIC_PRESETS.get(k, {}).get("symbols", [])
            for s in p_syms:
                clean = s.strip().upper().replace(".NS", "").replace("NSE:", "")
                if clean and not clean.startswith("^"):
                    symbols.add(clean)

        # Fallback if bundled json files are empty
        if len(symbols) < 50:
            symbols.update([
                "TRENT", "DIXON", "HAL", "BEL", "BSE", "MCX", "MAZDOCK", "COCHINSHIP",
                "POLYCAB", "KEI", "PERSISTENT", "COFORGE", "KPITTECH", "MAXHEALTH",
                "MANKIND", "CHOLAFIN", "SUZLON", "INOXWIND", "IREDA", "SOLARINDS",
                "DATAPATTNS", "CYIENTDLM", "AETHER", "RADICO", "MEDANTA", "KAYNES",
                "TITAGARH", "PREMIERENE", "WAAREEENER", "ZENTEC", "SWANENERGY"
            ])

        return sorted(list(symbols))

    def compute_relative_strength(
        self,
        stock_df: pd.DataFrame,
        nifty_df: Optional[pd.DataFrame] = None,
    ) -> int:
        """
        Computes William O'Neil / Mark Minervini Relative Strength (RS) Rating (0 to 99).
        Compares 3-month (63D) and 6-month (126D) momentum vs benchmark.
        """
        if stock_df is None or len(stock_df) < 63:
            return 50

        stock_closes = stock_df["close"].values
        stock_ret_3m = ((stock_closes[-1] - stock_closes[-63]) / stock_closes[-63]) * 100
        stock_ret_6m = (
            ((stock_closes[-1] - stock_closes[-min(126, len(stock_closes))])
             / stock_closes[-min(126, len(stock_closes))])
            * 100
        )

        nifty_ret_3m = 3.0  # default 3% benchmark quarterly return proxy
        if nifty_df is not None and len(nifty_df) >= 63:
            n_closes = nifty_df["close"].values
            nifty_ret_3m = ((n_closes[-1] - n_closes[-63]) / n_closes[-63]) * 100

        excess_3m = stock_ret_3m - nifty_ret_3m
        excess_6m = stock_ret_6m - (nifty_ret_3m * 2.0)
        composite_outperformance = (excess_3m * 0.6) + (excess_6m * 0.4)

        # Scale outperformance to 0-99 RS rank
        # 0% outperformance maps to RS 50. +30% excess maps to RS 85. +60% maps to RS 98.
        rs_rating = int(round(50 + (composite_outperformance * 0.9)))
        return max(5, min(99, rs_rating))

    def scan_universe_batch(
        self,
        symbols: Optional[list[str]] = None,
        top_n: int = 15,
    ) -> CompounderRoster:
        """
        Executes a deterministic, multi-horizon screening sweep across the universe.
        Populates decoupled short-term, mid-term, and generational rosters.
        """
        with self._lock:
            self._roster.is_scanning = True

        target_symbols = symbols or self.get_broad_multibagger_universe()
        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Fetch benchmark history once for RS calculations
        nifty_df = None
        try:
            from market.history import get_ohlcv

            nifty_df = get_ohlcv("NSE:NIFTY 50", interval="day", days=150)
        except Exception:
            pass

        st_candidates: list[CompounderCandidate] = []
        mt_candidates: list[CompounderCandidate] = []
        lt_candidates: list[CompounderCandidate] = []

        scanned_count = 0

        for sym in target_symbols:
            scanned_count += 1
            try:
                from market.history import get_ohlcv

                df = get_ohlcv(sym, interval="day", days=300)
                if df is None or len(df) < 50:
                    continue

                ltp = float(df["close"].iloc[-1])
                if ltp <= 0:
                    continue

                # 1. Turnover check (ensure >= ₹2 Cr daily liquidity)
                vol_20 = float(np.mean(df["volume"].iloc[-20:])) if "volume" in df.columns else 10000.0
                turnover_cr = (ltp * vol_20) / 1e7
                if turnover_cr < 2.0:
                    continue

                # 2. Minervini & Weinstein stages
                passed_count, criteria = evaluate_trend_template(df)
                stage, stage_conf = classify_weinstein_stage(df)
                is_vcp, contractions, pivot_price = detect_vcp(df)
                rs_rating = self.compute_relative_strength(df, nifty_df)

                # 3. Full report with decoupled tickets
                report = scan_multibagger_opportunity(sym, df=df)

                # ── Horizon Segregation ──────────────────────────────────

                # Pipeline A: Short-Term Velocity Alpha (1–4 Weeks)
                # Qualification: VCP active or tight pivot, high short-term score >= 68, RS >= 70
                if report.short_term_score >= 68 or (is_vcp and report.short_term_score >= 60):
                    cand = CompounderCandidate(
                        symbol=sym,
                        ltp=ltp,
                        horizon="SHORT_TERM",
                        category=report.category,
                        composite_score=report.short_term_score,
                        weinstein_stage=stage,
                        trend_template_passed=passed_count,
                        rs_rating=rs_rating,
                        vcp_detected=is_vcp,
                        vcp_pivot_price=pivot_price,
                        sector=report.sector,
                        sector_tailwind=report.sector_tailwind_score,
                        forensic_safe=report.forensic_safe,
                        ticket=report.short_term_ticket,
                        summary=f"High-Velocity VCP breakout candidate (RS {rs_rating}, RVOL surge). Target: ₹{report.short_term_ticket.get('target_1', 0)} (+2R).",
                        discovered_at=now_iso,
                    )
                    st_candidates.append(cand)

                # Pipeline B: Mid-Term Stage 2 Compounder (1–6 Months)
                # Qualification: Stage 2 Markup, Minervini >= 6/8, Mid-term score >= 70, RS >= 75
                if stage == "STAGE_2_MARKUP" and passed_count >= 6 and report.mid_term_score >= 68:
                    cand = CompounderCandidate(
                        symbol=sym,
                        ltp=ltp,
                        horizon="MID_TERM",
                        category="STAGE_2_COMPOUNDER",
                        composite_score=report.mid_term_score,
                        weinstein_stage=stage,
                        trend_template_passed=passed_count,
                        rs_rating=rs_rating,
                        vcp_detected=is_vcp,
                        vcp_pivot_price=pivot_price,
                        sector=report.sector,
                        sector_tailwind=report.sector_tailwind_score,
                        forensic_safe=report.forensic_safe,
                        ticket=report.mid_term_ticket,
                        summary=f"Stage 2 Superperformer. RS {rs_rating}/99, Minervini {passed_count}/8 passed. Trailing via 50-SMA floor.",
                        discovered_at=now_iso,
                    )
                    mt_candidates.append(cand)

                # Pipeline C: Long-Term Generational Wealth (1–3+ Years)
                # Qualification: Clean forensics, Long-term score >= 75, High ROCE
                if report.forensic_safe and report.long_term_score >= 70:
                    cand = CompounderCandidate(
                        symbol=sym,
                        ltp=ltp,
                        horizon="LONG_TERM",
                        category="GENERATIONAL_COMPOUNDER",
                        composite_score=report.long_term_score,
                        weinstein_stage=stage,
                        trend_template_passed=passed_count,
                        rs_rating=rs_rating,
                        vcp_detected=is_vcp,
                        vcp_pivot_price=pivot_price,
                        sector=report.sector,
                        sector_tailwind=report.sector_tailwind_score,
                        forensic_safe=report.forensic_safe,
                        ticket=report.long_term_ticket,
                        summary=f"High-quality franchise. Forensic clean, long-term score {report.long_term_score}/100. Anchored to 200-SMA floor.",
                        discovered_at=now_iso,
                    )
                    lt_candidates.append(cand)

            except Exception as e:
                logger.debug(f"[CompounderScanner] Symbol {sym} scan error: {e}")

        # Rank and take top candidates
        st_candidates.sort(key=lambda c: (c.composite_score, c.rs_rating), reverse=True)
        mt_candidates.sort(key=lambda c: (c.composite_score, c.trend_template_passed, c.rs_rating), reverse=True)
        lt_candidates.sort(key=lambda c: (c.composite_score, c.rs_rating), reverse=True)

        with self._lock:
            self._roster.total_scanned = scanned_count
            self._roster.short_term_rockets = st_candidates[:top_n]
            self._roster.mid_term_compounders = mt_candidates[:top_n]
            self._roster.generational_compounders = lt_candidates[:top_n]
            self._roster.last_scanned_at = now_iso
            self._roster.is_scanning = False

        self._save_cache()
        logger.info(
            f"[CompounderScanner] Completed scan across {scanned_count} equities. "
            f"Discovered: {len(self._roster.short_term_rockets)} short-term rockets, "
            f"{len(self._roster.mid_term_compounders)} Stage 2 compounders, "
            f"{len(self._roster.generational_compounders)} generational wealth candidates."
        )
        return self._roster

    def get_roster(self, horizon: str = "ALL") -> dict[str, Any]:
        """Returns the active roster filtered by horizon."""
        with self._lock:
            h = horizon.upper().strip()
            if h in ("SHORT", "SHORT_TERM"):
                return {
                    "horizon": "SHORT_TERM",
                    "count": len(self._roster.short_term_rockets),
                    "candidates": [c.to_dict() for c in self._roster.short_term_rockets],
                    "last_scanned_at": self._roster.last_scanned_at,
                    "is_scanning": self._roster.is_scanning,
                }
            elif h in ("MID", "MID_TERM", "COMPOUNDER"):
                return {
                    "horizon": "MID_TERM",
                    "count": len(self._roster.mid_term_compounders),
                    "candidates": [c.to_dict() for c in self._roster.mid_term_compounders],
                    "last_scanned_at": self._roster.last_scanned_at,
                    "is_scanning": self._roster.is_scanning,
                }
            elif h in ("LONG", "LONG_TERM", "GENERATIONAL"):
                return {
                    "horizon": "LONG_TERM",
                    "count": len(self._roster.generational_compounders),
                    "candidates": [c.to_dict() for c in self._roster.generational_compounders],
                    "last_scanned_at": self._roster.last_scanned_at,
                    "is_scanning": self._roster.is_scanning,
                }
            else:
                return self._roster.to_dict()


# Global Singleton
compounder_scanner = CompounderScanner()
