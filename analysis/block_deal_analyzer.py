"""
analysis/block_deal_analyzer.py
───────────────────────────────
Institutional Block Deal Absorption vs. Distribution Anchoring.

Evaluates institutional cost basis from NSE Bulk and Block Deals:
  1. Identifies large block transactions executed by FIIs, Mutual Funds, DIIs, and Promoters.
  2. Computes the Volume-Weighted Institutional Block Price (VWAP_block).
  3. Classifies real-time price action:
     - INSTITUTIONAL_ABSORPTION: Price consolidates or trends ABOVE the block deal execution price.
       Validates the block level as an institutional support wall.
     - INSTITUTIONAL_DISTRIBUTION: Price breaks BELOW the block deal level, indicating smart-money
       exit / supply overhang.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Optional

from market.bulk_deals import Deal, get_bulk_deals

logger = logging.getLogger("analysis.block_deal_analyzer")


@dataclass
class BlockDealAbsorptionReport:
    """Institutional block deal absorption and support anchor analysis."""

    symbol: str
    ltp: float
    status: str  # "INSTITUTIONAL_ABSORPTION" | "DISTRIBUTION_BREAKDOWN" | "NEUTRAL_CONSOLIDATION" | "NO_RECENT_BLOCKS"
    vwap_institutional_buy_price: Optional[float]
    vwap_institutional_sell_price: Optional[float]
    support_anchor_price: Optional[float]
    net_institutional_qty: int
    total_institutional_turnover_cr: float
    deal_count: int
    deals: list[dict[str, Any]] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_block_deal_absorption(
    symbol: str,
    current_price: Optional[float] = None,
    days: int = 30,
    deals_list: Optional[list[Deal]] = None,
) -> BlockDealAbsorptionReport:
    """
    Analyzes whether current market price is absorbing or distributing around recent institutional block deals.

    Args:
        symbol: NSE stock symbol (e.g. "TRENT", "MAZDOCK", "INFY").
        current_price: Current market price (LTP).
        days: Historical lookback in calendar days (default 30).
        deals_list: Optional pre-fetched list of Deal objects (for deterministic unit tests).
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()
    ltp = float(current_price or 1000.0)

    # 1. Fetch or use provided deals
    if deals_list is None:
        try:
            all_deals = get_bulk_deals(days=days)
            sym_deals = [d for d in all_deals if d.symbol.upper() == clean_sym]
        except Exception as e:
            logger.debug(f"[BlockDealAnalyzer] get_bulk_deals failed: {e}")
            sym_deals = []
    else:
        sym_deals = [d for d in deals_list if d.symbol.upper() == clean_sym]

    # Filter for institutional and promoter transactions
    inst_deals = [d for d in sym_deals if d.entity_type in ("FII", "MF", "DII", "PROMOTER")]

    if not inst_deals:
        return BlockDealAbsorptionReport(
            symbol=clean_sym,
            ltp=round(ltp, 2),
            status="NO_RECENT_BLOCKS",
            vwap_institutional_buy_price=None,
            vwap_institutional_sell_price=None,
            support_anchor_price=None,
            net_institutional_qty=0,
            total_institutional_turnover_cr=0.0,
            deal_count=0,
            deals=[],
            insights=[
                f"No major institutional block/bulk deals recorded for {clean_sym} in last {days} days."
            ],
        )

    # 2. Compute Volume-Weighted Institutional Execution Prices
    buy_deals = [d for d in inst_deals if d.deal_type.upper() == "BUY"]
    sell_deals = [d for d in inst_deals if d.deal_type.upper() == "SELL"]

    total_buy_qty = sum(d.quantity for d in buy_deals)
    total_sell_qty = sum(d.quantity for d in sell_deals)
    net_qty = total_buy_qty - total_sell_qty

    vwap_buy = (
        round(sum(d.price * d.quantity for d in buy_deals) / max(1, total_buy_qty), 2)
        if total_buy_qty > 0
        else None
    )
    vwap_sell = (
        round(sum(d.price * d.quantity for d in sell_deals) / max(1, total_sell_qty), 2)
        if total_sell_qty > 0
        else None
    )

    total_turnover_cr = round(sum(d.price * d.quantity for d in inst_deals) / 10_000_000.0, 2)

    # 3. Determine Absorption vs Distribution Status
    insights: list[str] = []
    support_anchor = None

    if vwap_buy is not None:
        support_anchor = vwap_buy
        pct_diff = ((ltp - vwap_buy) / vwap_buy) * 100.0

        if ltp >= vwap_buy * 0.99:
            status = "INSTITUTIONAL_ABSORPTION"
            insights.append(
                f"🛡️ Institutional Absorption: Price (₹{ltp:.2f}) holding firmly above institutional buy block VWAP (₹{vwap_buy:.2f}, {pct_diff:+.1f}%)."
            )
            insights.append(
                f"₹{vwap_buy:.2f} serves as an asymmetric institutional support anchor for stop-loss calibration."
            )
        elif ltp < vwap_buy * 0.95:
            status = "DISTRIBUTION_BREAKDOWN"
            insights.append(
                f"⚠️ Distribution Breakdown: Price cracked -{abs(pct_diff):.1f}% below institutional buy block level ₹{vwap_buy:.2f}."
            )
        else:
            status = "NEUTRAL_CONSOLIDATION"
            insights.append(
                f"Price consolidating right at institutional block cost basis ₹{vwap_buy:.2f}."
            )
    elif vwap_sell is not None:
        if ltp < vwap_sell:
            status = "DISTRIBUTION_BREAKDOWN"
            insights.append(
                f"Heavy institutional selling block at ₹{vwap_sell:.2f} acting as overhead supply ceiling."
            )
        else:
            status = "INSTITUTIONAL_ABSORPTION"
            insights.append(
                f"Price absorbed institutional supply block at ₹{vwap_sell:.2f} and expanded above it."
            )
    else:
        status = "NEUTRAL_CONSOLIDATION"

    serialized_deals = [
        {
            "date": d.date,
            "client": d.client,
            "deal_type": d.deal_type,
            "quantity": d.quantity,
            "price": d.price,
            "entity_type": d.entity_type,
            "deal_class": d.deal_class,
        }
        for d in inst_deals[:10]
    ]

    return BlockDealAbsorptionReport(
        symbol=clean_sym,
        ltp=round(ltp, 2),
        status=status,
        vwap_institutional_buy_price=vwap_buy,
        vwap_institutional_sell_price=vwap_sell,
        support_anchor_price=support_anchor,
        net_institutional_qty=net_qty,
        total_institutional_turnover_cr=total_turnover_cr,
        deal_count=len(inst_deals),
        deals=serialized_deals,
        insights=insights,
    )
