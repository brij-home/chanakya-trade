"""
analysis/whale_tracker.py
─────────────────────────
Indian Marquee Superstar Investors & Institutional Whale Flow Tracker.

Monitors Bulk Deals, Block Deals, and SAST Disclosures from marquee Indian market
superstars (Ashish Kacholia, Mukul Agrawal, Rekha Jhunjhunwala, Sunil Singhania,
Dolly Khanna, Porinju Veliyath) and Tier-1 Institutional Mutual Funds / FIIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MARQUEE_INVESTORS = [
    {
        "name": "Ashish Kacholia",
        "category": "Marquee Smallcap Hunter",
        "style": "High-growth niche leaders, specialty chemicals, industrial engineering.",
        "icon": "🎯",
    },
    {
        "name": "Mukul Agrawal",
        "category": "Aggressive Multibagger Specialist",
        "style": "Fast-growing smallcaps, turnaround stories, defense & aerospace.",
        "icon": "⚡",
    },
    {
        "name": "Sunil Singhania (Abakkus)",
        "category": "Institutional Value & Growth",
        "style": "Midcap manufacturing, capital goods, structural export themes.",
        "icon": "🏛️",
    },
    {
        "name": "Rekha Jhunjhunwala (Rare Ent.)",
        "category": "Mega-Cap & Consumer Compounders",
        "style": "Consumer discretionary, private banks, structural India growth.",
        "icon": "👑",
    },
    {
        "name": "Dolly Khanna",
        "category": "Cyclical & High Beta Value",
        "style": "Textiles, fertilizers, chemicals, commodity turnarounds.",
        "icon": "💎",
    },
    {
        "name": "Porinju Veliyath",
        "category": "Microcap Value Turnaround",
        "style": "Deep value, overlooked microcaps, beaten-down asset plays.",
        "icon": "🚀",
    },
    {
        "name": "HDFC Mutual Fund",
        "category": "Domestic Institutional Pillar (DII)",
        "style": "Heavyweight compounders, core banking, capital allocation moats.",
        "icon": "🏦",
    },
    {
        "name": "Morgan Stanley / Nomura / FII",
        "category": "Foreign Institutional Inflow (FII)",
        "style": "Index heavyweights, clean ESG, liquid tech & private lenders.",
        "icon": "🌐",
    },
]

# Baseline curated institutional disclosures fixture
CURATED_WHALE_DEALS: list[dict[str, Any]] = [
    {
        "id": "wd-01",
        "symbol": "KAYNES",
        "company_name": "Kaynes Technology India Ltd",
        "investor_name": "Ashish Kacholia",
        "investor_category": "Marquee Smallcap Hunter",
        "deal_type": "BULK_BUY",
        "stake_pct": 1.85,
        "shares_quantity": 1080000,
        "trade_price": 5420.0,
        "current_ltp": 5650.0,
        "deal_value_cr": 58.5,
        "date": "2026-08-25",
        "conviction_score": 88,
        "sector": "Electronics Manufacturing (EMS)",
        "key_thesis": "Surging order book in defense & semiconductor packaging with 40%+ EBITDA CAGR.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-02",
        "symbol": "DATAPATTNS",
        "company_name": "Data Patterns (India) Ltd",
        "investor_name": "Mukul Agrawal",
        "investor_category": "Aggressive Multibagger Specialist",
        "deal_type": "BLOCK_BUY",
        "stake_pct": 2.10,
        "shares_quantity": 1150000,
        "trade_price": 2840.0,
        "current_ltp": 2980.0,
        "deal_value_cr": 32.6,
        "date": "2026-08-20",
        "conviction_score": 85,
        "sector": "Defense & Aerospace",
        "key_thesis": "Indigenous radar electronics and space avionics programs expanding order pipeline.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-03",
        "symbol": "TATACOMM",
        "company_name": "Tata Communications Ltd",
        "investor_name": "Rekha Jhunjhunwala (Rare Ent.)",
        "investor_category": "Mega-Cap & Consumer Compounders",
        "deal_type": "SAST_ACCUMULATION",
        "stake_pct": 1.45,
        "shares_quantity": 4120000,
        "trade_price": 1910.0,
        "current_ltp": 1965.0,
        "deal_value_cr": 78.7,
        "date": "2026-08-18",
        "conviction_score": 82,
        "sector": "Telecommunications & Cloud",
        "key_thesis": "Digital platform transformation and submarine cable data traffic monetization.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-04",
        "symbol": "IONEXCHANG",
        "company_name": "Ion Exchange (India) Ltd",
        "investor_name": "Sunil Singhania (Abakkus)",
        "investor_category": "Institutional Value & Growth",
        "deal_type": "BULK_BUY",
        "stake_pct": 2.40,
        "shares_quantity": 350000,
        "trade_price": 580.0,
        "current_ltp": 612.0,
        "deal_value_cr": 20.3,
        "date": "2026-08-12",
        "conviction_score": 80,
        "sector": "Water & Industrial Engineering",
        "key_thesis": "Industrial effluent zero-liquid-discharge capex wave across chemical & pharma plants.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-05",
        "symbol": "KEC",
        "company_name": "KEC International Ltd",
        "investor_name": "HDFC Mutual Fund",
        "investor_category": "Domestic Institutional Pillar (DII)",
        "deal_type": "BLOCK_BUY",
        "stake_pct": 1.65,
        "shares_quantity": 4250000,
        "trade_price": 935.0,
        "current_ltp": 968.0,
        "deal_value_cr": 39.7,
        "date": "2026-08-10",
        "conviction_score": 78,
        "sector": "Power T&D & Infrastructure",
        "key_thesis": "Global green energy transmission corridor buildout and rail electrification execution.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-06",
        "symbol": "GRAVITA",
        "company_name": "Gravita India Ltd",
        "investor_name": "Ashish Kacholia",
        "investor_category": "Marquee Smallcap Hunter",
        "deal_type": "SAST_ACCUMULATION",
        "stake_pct": 2.15,
        "shares_quantity": 1480000,
        "trade_price": 2150.0,
        "current_ltp": 2310.0,
        "deal_value_cr": 31.8,
        "date": "2026-08-05",
        "conviction_score": 86,
        "sector": "Circular Economy & Recycling",
        "key_thesis": "Battery Waste Management Rules (BWMR) enforcing formal recycling channel dominance.",
        "stage_status": "STAGE_2_MARKUP",
    },
    {
        "id": "wd-07",
        "symbol": "APARINDS",
        "company_name": "Apar Industries Ltd",
        "investor_name": "Mukul Agrawal",
        "investor_category": "Aggressive Multibagger Specialist",
        "deal_type": "BULK_BUY",
        "stake_pct": 1.70,
        "shares_quantity": 650000,
        "trade_price": 9200.0,
        "current_ltp": 9650.0,
        "deal_value_cr": 59.8,
        "date": "2026-07-28",
        "conviction_score": 90,
        "sector": "Specialty Conductors & Cables",
        "key_thesis": "US/Europe grid modernization driving high-margin premium cable export surge.",
        "stage_status": "STAGE_2_MARKUP",
    },
]


def get_whale_flows(
    investor_filter: str | None = None,
    sector_filter: str | None = None,
    min_deal_cr: float = 0.0,
) -> dict[str, Any]:
    """Return filtered whale transactions and marquee investor profiles."""
    filtered_deals = []
    total_capital_cr = 0.0

    for deal in CURATED_WHALE_DEALS:
        if investor_filter and investor_filter.lower() not in deal["investor_name"].lower():
            continue
        if sector_filter and sector_filter.lower() not in deal["sector"].lower():
            continue
        if deal["deal_value_cr"] < min_deal_cr:
            continue

        deal_copy = dict(deal)
        # Calculate real-time gain/loss since transaction
        p_diff = deal_copy["current_ltp"] - deal_copy["trade_price"]
        deal_copy["gain_pct_since_deal"] = round((p_diff / deal_copy["trade_price"]) * 100, 1)
        deal_copy["pnl_status"] = "PROFIT" if p_diff >= 0 else "LOSS"

        filtered_deals.append(deal_copy)
        total_capital_cr += deal["deal_value_cr"]

    # Calculate summary statistics
    stage_2_count = sum(1 for d in filtered_deals if d["stage_status"] == "STAGE_2_MARKUP")
    avg_conviction = round(
        sum(d["conviction_score"] for d in filtered_deals) / max(1, len(filtered_deals)), 1
    )

    return {
        "status": "success",
        "as_of_date": datetime.now(timezone.utc).strftime("%d %b %Y"),
        "total_deals": len(filtered_deals),
        "total_capital_deployed_cr": round(total_capital_cr, 1),
        "stage_2_alignment_pct": round((stage_2_count / max(1, len(filtered_deals))) * 100, 1),
        "avg_conviction_score": avg_conviction,
        "marquee_investors": MARQUEE_INVESTORS,
        "deals": filtered_deals,
    }
