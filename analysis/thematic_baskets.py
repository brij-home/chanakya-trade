"""
analysis/thematic_baskets.py
────────────────────────────
Institutional Super-Investor Thematic Baskets & Strategy Stacks.

Baskets:
  1. "mayer_100_baggers": Christopher Mayer Framework
     - Small/Midcap base (market cap <= 25,000 Cr), ROCE >= 20%, low debt <= 0.5, high reinvestment.
  2. "lynch_garp_fast_growers": Peter Lynch Fast-Growers (GARP)
     - PEG ratio <= 1.0, EPS growth >= 25%, high market share expansion.
  3. "jhunjhunwala_operating_leverage": Rakesh Jhunjhunwala Operating Leverage
     - Fixed asset turnover expansion, massive capex cycle, domestic Indian tailwinds.
  4. "canslim_high_momentum": William O'Neil CAN SLIM Leaders
     - 52-Week High breakout within 15%, RS Rating >= 80, institutional accumulation.
  5. "order_book_powerhouses": Mega Order-Book Titans
     - Order-Book to Market-Cap ratio >= 1.5x - 3.0x (Defence, Railways, Power EPC).
  6. "value_migration_leaders": Structural Profit-Pool Shift
     - Themes gaining market share from unorganized/legacy players (EMS, Solar, CDMO, Exchanges).
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.magic_trend import MagicTrendReport, calculate_magic_trend_score


@dataclass
class ThematicBasketMetadata:
    basket_id: str
    name: str
    icon: str
    investor_philosophy: str
    target_cagr: str
    min_holding_horizon: str
    core_criteria: list[str]
    symbols: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


THEMATIC_BASKETS: dict[str, ThematicBasketMetadata] = {
    "mayer_100_baggers": ThematicBasketMetadata(
        basket_id="mayer_100_baggers",
        name="💎 Christopher Mayer 100-Baggers",
        icon="💎",
        investor_philosophy="Christopher Mayer's '100 Baggers': Small/Midcap base with high ROCE (>20%), high reinvestment of retained earnings, and long growth runway.",
        target_cagr="25% – 35% CAGR (5x – 10x Potential)",
        min_holding_horizon="3 – 7 Years",
        core_criteria=[
            "Market Cap <= ₹25,000 Cr (Long runway for growth)",
            "ROCE >= 20% & ROE >= 18%",
            "Debt-to-Equity <= 0.5 (Self-funded growth)",
            "Founder / Promoter Skin-in-the-game >= 50%",
            "High reinvestment rate of operating cashflow",
        ],
        symbols=[
            "KAYNES",
            "DIXON",
            "SYRMA",
            "DATAPATTNS",
            "ZENTEC",
            "MTARTECH",
            "CYIENTDLM",
            "AETHER",
            "TATVA",
            "FINEORG",
            "MEDANTA",
            "KIMS",
            "NEWGEN",
            "RATEGAIN",
            "MAPMYINDIA",
            "CEINFO",
            "RADICO",
            "JUPITERWAG",
            "TITAGARH",
        ],
    ),
    "lynch_garp_fast_growers": ThematicBasketMetadata(
        basket_id="lynch_garp_fast_growers",
        name="🚀 Peter Lynch Fast-Growers (GARP)",
        icon="🚀",
        investor_philosophy="Peter Lynch's 'Growth at a Reasonable Price' (GARP): High double-digit EPS growth (>25%) trading at PEG <= 1.0.",
        target_cagr="20% – 30% CAGR (2x – 4x Potential)",
        min_holding_horizon="1 – 3 Years",
        core_criteria=[
            "PEG Ratio <= 1.0 (Valuation Asymmetry)",
            "EPS & Sales CAGR >= 25% for 3+ consecutive quarters",
            "Low institutional ownership expanding QoQ",
            "Product expansion with high pricing power",
        ],
        symbols=[
            "TRENT",
            "POLYCAB",
            "KEI",
            "RRKABEL",
            "MAXHEALTH",
            "MANKIND",
            "CHOLAFIN",
            "PERSISTENT",
            "COFORGE",
            "KPITTECH",
            "VBL",
            "DMART",
            "JUBLFOOD",
            "TITAN",
            "SOLARINDS",
        ],
    ),
    "jhunjhunwala_operating_leverage": ThematicBasketMetadata(
        basket_id="jhunjhunwala_operating_leverage",
        name="🐘 Rakesh Jhunjhunwala Operating Leverage",
        icon="🐘",
        investor_philosophy="Rakesh Jhunjhunwala's Big Bull Compounders: Manufacturing, defence, and infrastructure players where 15% revenue growth expands operating profit by 40%+.",
        target_cagr="22% – 32% CAGR (3x – 5x Potential)",
        min_holding_horizon="2 – 5 Years",
        core_criteria=[
            "Heavy fixed assets with rising capacity utilization (>80%)",
            "Rapid deleveraging (Debt/Equity dropping from >1.5 to <0.5)",
            "Indian domestic infrastructure & capex super-cycle tailwinds",
            "Massive operating margin expansion",
        ],
        symbols=[
            "HAL",
            "BEL",
            "MAZDOCK",
            "COCHINSHIP",
            "GRSE",
            "BDL",
            "TITAGARH",
            "TEXRAIL",
            "JUPITERWAG",
            "BHEL",
            "CGPOWER",
            "ABB",
            "SIEMENS",
            "TATASTEEL",
            "JSWSTEEL",
            "HINDALCO",
        ],
    ),
    "canslim_high_momentum": ThematicBasketMetadata(
        basket_id="canslim_high_momentum",
        name="📈 William O'Neil CAN SLIM Leaders",
        icon="📈",
        investor_philosophy="William O'Neil's CAN SLIM: Leading market winners breaking out to 52-week new highs with institutional volume surges and top Relative Strength.",
        target_cagr="30% – 50% Momentum Velocity",
        min_holding_horizon="2 – 8 Months",
        core_criteria=[
            "Current quarterly EPS & Sales growth >= 25%",
            "Stock price within 15% of 52-week new high",
            "Relative Strength Rating (RS) >= 80",
            "Institutional delivery accumulation on breakout days",
        ],
        symbols=[
            "BSE",
            "MCX",
            "CDSL",
            "ANGELONE",
            "TRENT",
            "DIXON",
            "HAL",
            "BEL",
            "PREMIERENE",
            "WAAREEENER",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "PERSISTENT",
            "COFORGE",
        ],
    ),
    "order_book_powerhouses": ThematicBasketMetadata(
        basket_id="order_book_powerhouses",
        name="🏗️ Mega Order-Book Titans",
        icon="🏗️",
        investor_philosophy="Multi-year revenue visibility: Companies with Order Book to Market Cap ratio >= 1.5x - 3.0x providing rock-solid 3 to 5-year revenue certainty.",
        target_cagr="20% – 28% CAGR (2x – 3.5x Potential)",
        min_holding_horizon="1 – 4 Years",
        core_criteria=[
            "Order Book to Market Cap >= 1.5x (Multi-year revenue visibility)",
            "Government PLI / Make in India / Defence Indigenization mandates",
            "Clean balance sheet with low working capital drag",
            "Expanding execution EBITDA margins",
        ],
        symbols=[
            "HAL",
            "BEL",
            "MAZDOCK",
            "COCHINSHIP",
            "GRSE",
            "BDL",
            "TITAGARH",
            "RVNL",
            "IRFC",
            "RAILTEL",
            "BHEL",
            "KEC",
            "KALPATPOWR",
            "TECHNOE",
            "PRAJIND",
            "ISGEC",
            "NCC",
            "LT",
        ],
    ),
    "value_migration_leaders": ThematicBasketMetadata(
        basket_id="value_migration_leaders",
        name="🛡️ Structural Value Migration Leaders",
        icon="🛡️",
        investor_philosophy="Adrian Slywotzky's Value Migration: Capturing massive profit pools shifting from outdated/unorganized business models into agile high-ROCE disruptors.",
        target_cagr="25% – 35% CAGR (4x – 8x Potential)",
        min_holding_horizon="2 – 6 Years",
        core_criteria=[
            "Profit pool migrating from fragmented/legacy unorganized peers",
            "Global China+1 / EMS / CDMO manufacturing shift to India",
            "Financialization of Indian household savings (Exchanges/Depositories)",
            "Green energy transition (Solar/Wind/Transformers)",
        ],
        symbols=[
            "BSE",
            "MCX",
            "SUZLON",
            "INOXWIND",
            "IREDA",
            "KAYNES",
            "DIXON",
            "SYRMA",
            "PREMIERENE",
            "WAAREEENER",
            "ZOMATO",
            "POLICYBZR",
            "MAXHEALTH",
            "MANKIND",
            "NEULANDLAB",
        ],
    ),
}


@dataclass
class ThematicBasketScanResult:
    basket_id: str
    basket_name: str
    icon: str
    investor_philosophy: str
    target_cagr: str
    min_holding_horizon: str
    total_scanned: int
    top_candidates: list[MagicTrendReport] = field(default_factory=list)
    average_basket_score: float = 0.0
    scan_timestamp: str = ""
    execution_time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "basket_id": self.basket_id,
            "basket_name": self.basket_name,
            "icon": self.icon,
            "investor_philosophy": self.investor_philosophy,
            "target_cagr": self.target_cagr,
            "min_holding_horizon": self.min_holding_horizon,
            "total_scanned": self.total_scanned,
            "top_candidates": [c.to_dict() for c in self.top_candidates],
            "average_basket_score": round(self.average_basket_score, 1),
            "scan_timestamp": self.scan_timestamp,
            "execution_time_seconds": self.execution_time_seconds,
        }


def scan_thematic_basket(
    basket_id: str = "mayer_100_baggers",
    min_score: int = 50,
    max_results: int = 15,
    exchange: str = "NSE",
    parallel_workers: int = 8,
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
) -> ThematicBasketScanResult:
    """
    Scans an institutional thematic basket, evaluates Magic Trend scores, and ranks candidates.
    """
    t0 = time.perf_counter()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    meta = THEMATIC_BASKETS.get(basket_id.lower())
    if not meta:
        meta = THEMATIC_BASKETS["mayer_100_baggers"]

    symbols = [s for s in meta.symbols if s in df_cache] if df_cache else meta.symbols

    reports: list[MagicTrendReport] = []

    def _worker(sym: str) -> Optional[MagicTrendReport]:
        try:
            df = df_cache.get(sym) if df_cache else None
            return calculate_magic_trend_score(sym, df=df, exchange=exchange)
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {executor.submit(_worker, sym): sym for sym in symbols}
        for f in concurrent.futures.as_completed(futures):
            rep = f.result()
            if rep and rep.ltp > 0 and rep.magic_trend_score >= min_score:
                reports.append(rep)

    reports.sort(key=lambda x: x.magic_trend_score, reverse=True)
    top_candidates = reports[:max_results]
    avg_score = (
        float(np.mean([r.magic_trend_score for r in top_candidates])) if top_candidates else 0.0
    )
    t1 = time.perf_counter()

    return ThematicBasketScanResult(
        basket_id=meta.basket_id,
        basket_name=meta.name,
        icon=meta.icon,
        investor_philosophy=meta.investor_philosophy,
        target_cagr=meta.target_cagr,
        min_holding_horizon=meta.min_holding_horizon,
        total_scanned=len(symbols),
        top_candidates=top_candidates,
        average_basket_score=avg_score,
        scan_timestamp=timestamp_str,
        execution_time_seconds=round(t1 - t0, 3),
    )


def list_all_thematic_baskets() -> list[dict[str, Any]]:
    """Returns metadata for all 6 institutional thematic baskets."""
    return [b.to_dict() for b in THEMATIC_BASKETS.values()]
