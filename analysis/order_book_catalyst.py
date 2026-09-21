"""
analysis/order_book_catalyst.py
───────────────────────────────
SEBI Regulation 30 Corporate Order-Inflow & Book-to-Bill Multiplier Engine.

Provides institutional analysis on:
  1. Multi-Year Revenue Visibility: Book-to-Bill (Order Book / TTM Sales) & Book-to-Market-Cap.
  2. Operating Leverage Expansion: Fixed costs remain stable while expanding execution drops
     straight to PAT (operating leverage multiplier typically 1.8x - 3.5x).
  3. Real-Time SEBI Reg 30 Contract Win Parsing: Extracts contract values from corporate announcements
     and categorizes impact (TRANSFORMATIVE >= 50% sales, HIGH_IMPACT >= 25% sales).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("analysis.order_book_catalyst")


@dataclass
class ContractAnnouncement:
    """Parsed corporate contract / order win filing."""

    contract_value_cr: float
    client: str
    project_scope: str
    execution_months: int
    order_impact_ratio: float  # Contract Value / Annual Sales
    classification: str  # "TRANSFORMATIVE" | "HIGH_IMPACT" | "MODERATE" | "ROUTINE"
    raw_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderBookReport:
    """Comprehensive institutional order-book & revenue visibility intelligence."""

    symbol: str
    company_name: str
    sector: str
    current_order_book_cr: float
    ttm_revenue_cr: float
    market_cap_cr: float

    # Core Institutional Ratios
    book_to_bill_ratio: float  # Order Book / TTM Revenue
    book_to_mcap_ratio: float  # Order Book / Market Cap
    revenue_runway_years: float  # How many years of revenue locked in
    operating_leverage_tier: str  # "HYPER_EXPANSION" | "STRONG_LEVERAGE" | "STEADY"

    # Contract Catalyst & Status
    catalyst_verdict: str  # "ORDER_BOOK_TITAN" | "RAPID_EXPANSION" | "STABLE" | "UNKNOWN"
    latest_contract: Optional[ContractAnnouncement] = None
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.latest_contract:
            d["latest_contract"] = self.latest_contract.to_dict()
        return d


# ── Canonical Indian Order-Book Powerhouses Ledger ────────────────────────────
# Updated institutional baselines for premier Indian order-book compounders
ORDER_BOOK_TITANS_LEDGER: dict[str, dict[str, Any]] = {
    "MAZDOCK": {
        "name": "Mazagon Dock Shipbuilders",
        "sector": "Defense & Shipyards",
        "order_book_cr": 40500.0,
        "ttm_revenue_cr": 9500.0,
        "market_cap_cr": 88000.0,
    },
    "COCHINSHIP": {
        "name": "Cochin Shipyard",
        "sector": "Defense & Maritime",
        "order_book_cr": 22400.0,
        "ttm_revenue_cr": 4200.0,
        "market_cap_cr": 45000.0,
    },
    "GRSE": {
        "name": "Garden Reach Shipbuilders",
        "sector": "Defense & Naval",
        "order_book_cr": 24800.0,
        "ttm_revenue_cr": 3800.0,
        "market_cap_cr": 26000.0,
    },
    "HAL": {
        "name": "Hindustan Aeronautics",
        "sector": "Aerospace & Defense",
        "order_book_cr": 94000.0,
        "ttm_revenue_cr": 30500.0,
        "market_cap_cr": 310000.0,
    },
    "BEL": {
        "name": "Bharat Electronics",
        "sector": "Defense Electronics",
        "order_book_cr": 76000.0,
        "ttm_revenue_cr": 20800.0,
        "market_cap_cr": 215000.0,
    },
    "BDL": {
        "name": "Bharat Dynamics",
        "sector": "Missiles & Defense",
        "order_book_cr": 19500.0,
        "ttm_revenue_cr": 2600.0,
        "market_cap_cr": 42000.0,
    },
    "TITAGARH": {
        "name": "Titagarh Rail Systems",
        "sector": "Railways & Metro",
        "order_book_cr": 28000.0,
        "ttm_revenue_cr": 3900.0,
        "market_cap_cr": 18000.0,
    },
    "RVNL": {
        "name": "Rail Vikas Nigam",
        "sector": "Rail Infrastructure",
        "order_book_cr": 85000.0,
        "ttm_revenue_cr": 22000.0,
        "market_cap_cr": 95000.0,
    },
    "BHEL": {
        "name": "Bharat Heavy Electricals",
        "sector": "Power Equipment",
        "order_book_cr": 135000.0,
        "ttm_revenue_cr": 24000.0,
        "market_cap_cr": 98000.0,
    },
    "INOXWIND": {
        "name": "Inox Wind",
        "sector": "Renewable Energy EPC",
        "order_book_cr": 14000.0,
        "ttm_revenue_cr": 2800.0,
        "market_cap_cr": 28000.0,
    },
    "KAYNES": {
        "name": "Kaynes Technology",
        "sector": "Electronics EMS & Semiconductor",
        "order_book_cr": 5100.0,
        "ttm_revenue_cr": 1800.0,
        "market_cap_cr": 34000.0,
    },
    "KEC": {
        "name": "KEC International",
        "sector": "Power T&D & Railways",
        "order_book_cr": 32000.0,
        "ttm_revenue_cr": 20000.0,
        "market_cap_cr": 24000.0,
    },
    "KALPATPOWR": {
        "name": "Kalpataru Projects",
        "sector": "Infrastructure & T&D",
        "order_book_cr": 58000.0,
        "ttm_revenue_cr": 20500.0,
        "market_cap_cr": 21000.0,
    },
    "NCC": {
        "name": "NCC Limited",
        "sector": "Civil Construction & Water",
        "order_book_cr": 57500.0,
        "ttm_revenue_cr": 18500.0,
        "market_cap_cr": 19000.0,
    },
    "LT": {
        "name": "Larsen & Toubro",
        "sector": "EPC Conglomerate",
        "order_book_cr": 490000.0,
        "ttm_revenue_cr": 225000.0,
        "market_cap_cr": 485000.0,
    },
}


def parse_contract_announcement_text(
    text: str,
    annual_revenue_cr: Optional[float] = None,
) -> Optional[ContractAnnouncement]:
    """
    Parses corporate announcement filing text for order wins under SEBI Reg 30.
    Extracts contract amount in ₹ Crores, client name, and duration.
    """
    if not text or len(text.strip()) < 10:
        return None

    clean_text = text.replace(",", "")

    # 1. Regex search for contract values in ₹ Cr, Rs. Cr, or Millions
    cr_match = re.search(
        r"(?:Rs\.?|INR|₹)\s*([\d\.]+)\s*(?:Cr|Crore|crores)", clean_text, re.IGNORECASE
    )
    usd_match = re.search(
        r"(?:USD|\$)\s*([\d\.]+)\s*(?:Mn|Million|mn)", clean_text, re.IGNORECASE
    )

    contract_cr = 0.0
    if cr_match:
        try:
            contract_cr = float(cr_match.group(1))
        except ValueError:
            contract_cr = 0.0
    elif usd_match:
        try:
            # 1 USD Mn ~ 8.4 Cr INR
            contract_cr = round(float(usd_match.group(1)) * 8.4, 1)
        except ValueError:
            contract_cr = 0.0

    if contract_cr <= 0.0:
        return None

    # 2. Extract client or entity if mentioned
    client_match = re.search(
        r"(?:from|by|awarded by)\s+([A-Za-z0-9\s\.\-]{3,40}?)(?:for|worth|to|under|\.|\,)",
        clean_text,
        re.IGNORECASE,
    )
    client = client_match.group(1).strip() if client_match else "Major Institutional / Govt Entity"

    # 3. Execution duration in months
    months_match = re.search(r"(\d+)\s*(?:months|month)", clean_text, re.IGNORECASE)
    years_match = re.search(r"(\d+)\s*(?:years|year)", clean_text, re.IGNORECASE)
    exec_months = 24
    if months_match:
        try:
            exec_months = int(months_match.group(1))
        except ValueError:
            pass
    elif years_match:
        try:
            exec_months = int(years_match.group(1)) * 12
        except ValueError:
            pass

    # 4. Compute Order Impact Ratio
    rev = annual_revenue_cr or 1000.0
    impact_ratio = round((contract_cr / max(1.0, rev)) * 100.0, 1)

    # 5. Classify Impact
    if impact_ratio >= 50.0:
        classification = "TRANSFORMATIVE"
    elif impact_ratio >= 25.0:
        classification = "HIGH_IMPACT"
    elif impact_ratio >= 10.0:
        classification = "MODERATE"
    else:
        classification = "ROUTINE"

    return ContractAnnouncement(
        contract_value_cr=contract_cr,
        client=client,
        project_scope=text[:180].strip(),
        execution_months=exec_months,
        order_impact_ratio=impact_ratio,
        classification=classification,
        raw_snippet=text[:250].strip(),
    )


def analyze_order_book_catalyst(
    symbol: str,
    latest_announcement_text: Optional[str] = None,
) -> OrderBookReport:
    """
    Analyzes multi-year revenue visibility, Book-to-Bill, and order-book catalyst state.

    Args:
        symbol: NSE/BSE ticker symbol (e.g. "MAZDOCK", "HAL", "TITAGARH").
        latest_announcement_text: Optional recent filing text to extract fresh contract wins.
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()

    ledger_entry = ORDER_BOOK_TITANS_LEDGER.get(clean_sym)
    if ledger_entry:
        name = ledger_entry["name"]
        sector = ledger_entry["sector"]
        order_book_cr = ledger_entry["order_book_cr"]
        ttm_rev_cr = ledger_entry["ttm_revenue_cr"]
        mcap_cr = ledger_entry["market_cap_cr"]
    else:
        # Default estimation baseline for non-catalogued companies
        name = clean_sym
        sector = "Capital Goods / Infrastructure"
        order_book_cr = 2500.0
        ttm_rev_cr = 2000.0
        mcap_cr = 5000.0

    # 1. Parse announcement if provided
    contract_item = None
    if latest_announcement_text:
        contract_item = parse_contract_announcement_text(
            latest_announcement_text, annual_revenue_cr=ttm_rev_cr
        )
        if contract_item:
            order_book_cr += contract_item.contract_value_cr

    # 2. Key Ratios
    b_to_bill = round(order_book_cr / max(1.0, ttm_rev_cr), 2)
    b_to_mcap = round(order_book_cr / max(1.0, mcap_cr), 2)
    runway_years = round(b_to_bill * 0.85, 1)  # Normalized execution pace

    # 3. Operating Leverage Tier
    if b_to_bill >= 3.0:
        op_leverage = "HYPER_EXPANSION"
    elif b_to_bill >= 1.8:
        op_leverage = "STRONG_LEVERAGE"
    else:
        op_leverage = "STEADY"

    # 4. Verdict & Insights
    insights: list[str] = []
    if b_to_bill >= 2.5:
        verdict = "ORDER_BOOK_TITAN"
        insights.append(
            f"🏗️ Massive Revenue Visibility: ₹{order_book_cr:,.0f} Cr order book provides {b_to_bill:.1f}x book-to-bill (~{runway_years} years revenue lock-in)."
        )
        insights.append(
            f"High operating leverage potential: Fixed cost absorption expected to accelerate PAT expansion over FY26-FY28."
        )
    elif b_to_bill >= 1.5:
        verdict = "RAPID_EXPANSION"
        insights.append(
            f"Solid contract backlog: {b_to_bill:.1f}x book-to-bill ensures ~{runway_years} years execution runway."
        )
    else:
        verdict = "STABLE"
        insights.append(f"Standard order backlog ({b_to_bill:.1f}x book-to-bill).")

    if contract_item:
        insights.append(
            f"⚡ Fresh Contract Win: ₹{contract_item.contract_value_cr:,.0f} Cr ({contract_item.order_impact_ratio}% of annual sales) classified as {contract_item.classification}."
        )

    return OrderBookReport(
        symbol=clean_sym,
        company_name=name,
        sector=sector,
        current_order_book_cr=round(order_book_cr, 1),
        ttm_revenue_cr=round(ttm_rev_cr, 1),
        market_cap_cr=round(mcap_cr, 1),
        book_to_bill_ratio=b_to_bill,
        book_to_mcap_ratio=b_to_mcap,
        revenue_runway_years=runway_years,
        operating_leverage_tier=op_leverage,
        catalyst_verdict=verdict,
        latest_contract=contract_item,
        insights=insights,
    )


def get_top_order_book_titans(min_book_to_bill: float = 1.8) -> list[OrderBookReport]:
    """Retrieves all tracked order-book powerhouses sorted by Book-to-Bill ratio."""
    reports: list[OrderBookReport] = []
    for sym in ORDER_BOOK_TITANS_LEDGER:
        rep = analyze_order_book_catalyst(sym)
        if rep.book_to_bill_ratio >= min_book_to_bill:
            reports.append(rep)
    reports.sort(key=lambda r: r.book_to_bill_ratio, reverse=True)
    return reports
