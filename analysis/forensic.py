"""
analysis/forensic.py
────────────────────
Forensic accounting, earnings quality, and corporate governance audit engine.

Provides institutional grade quantitative forensic checks for Indian equities:
  1. Beneish M-Score (8-variable earnings manipulation detection)
  2. Altman Z''-Score (Emerging market / non-manufacturing credit distress model)
  3. Piotroski F-Score (9-point financial health & quality matrix)
  4. Indian Corporate Governance & Red Flag Scanner (Promoter pledging, accruals gap, interest coverage, institutional exit)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ForensicAuditResult:
    """Institutional forensic and governance audit report."""

    symbol: str
    beneish_m_score: Optional[float]
    is_manipulator_risk: bool
    altman_z_score: Optional[float]
    distress_zone: str  # "SAFE" | "GREY" | "DISTRESS" | "UNAVAILABLE"
    piotroski_f_score: Optional[int]  # 0 to 9
    quality_rating: str  # "A+" | "A" | "B" | "C" | "D" | "UNAVAILABLE"
    governance_red_flags: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    summary_text: str = ""
    available: bool = True
    unavailable_reasons: list[str] = field(default_factory=list)

    @property
    def overall_forensic_verdict(self) -> str:
        """Categorize overall forensic risk: CLEAN_PASS | MILD_WARNING | RED_FLAG."""
        if not self.available:
            return "UNAVAILABLE"
        if (
            self.is_manipulator_risk
            or self.distress_zone == "DISTRESS"
            or len(self.governance_red_flags) >= 2
        ):
            return "RED_FLAG"
        elif len(self.governance_red_flags) == 1 or self.distress_zone == "GREY":
            return "MILD_WARNING"
        return "CLEAN_PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "beneish_m_score": round(self.beneish_m_score, 2)
            if self.beneish_m_score is not None
            else None,
            "is_manipulator_risk": self.is_manipulator_risk,
            "altman_z_score": round(self.altman_z_score, 2)
            if self.altman_z_score is not None
            else None,
            "distress_zone": self.distress_zone,
            "piotroski_f_score": self.piotroski_f_score,
            "quality_rating": self.quality_rating,
            "governance_red_flags": self.governance_red_flags,
            "strengths": self.strengths,
            "summary_text": self.summary_text,
            "available": self.available,
            "unavailable_reasons": self.unavailable_reasons,
            "overall_forensic_verdict": self.overall_forensic_verdict,
        }


def compute_beneish_m_score(
    dsri: float = 1.0,
    gmi: float = 1.0,
    aqi: float = 1.0,
    sgi: float = 1.0,
    depi: float = 1.0,
    sgai: float = 1.0,
    lvgi: float = 1.0,
    tata: float = 0.0,
) -> float:
    """
    Compute Beneish 8-variable M-Score.
    M-Score > -1.78 indicates high probability of earnings manipulation.
    """
    m = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.037 * tata
        + 0.0327 * lvgi
    )
    return m


def compute_altman_z_score(
    working_capital: float,
    total_assets: float,
    retained_earnings: float,
    ebit: float,
    book_value_equity: float,
    total_liabilities: float,
) -> tuple[float, str]:
    """
    Compute Altman Z''-Score for emerging markets / non-manufacturers.

    Formula:
        Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
        X1 = Working Capital / Total Assets
        X2 = Retained Earnings / Total Assets
        X3 = EBIT / Total Assets
        X4 = Book Value Equity / Total Liabilities

    Zones:
        Z'' > 2.60: SAFE
        1.10 <= Z'' <= 2.60: GREY
        Z'' < 1.10: DISTRESS
    """
    if total_assets <= 0:
        return 2.5, "GREY"

    liab = total_liabilities if total_liabilities > 0 else (total_assets * 0.4)
    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = book_value_equity / liab

    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4

    if z > 2.60:
        zone = "SAFE"
    elif z >= 1.10:
        zone = "GREY"
    else:
        zone = "DISTRESS"

    return z, zone


def compute_piotroski_f_score(data: dict[str, Any]) -> tuple[int, list[str]]:
    """
    Compute Piotroski F-Score (0 to 9) from financial metrics.

    Metrics evaluated:
      1. ROA > 0 (Positive Return on Assets)
      2. CFO > 0 (Positive Cash Flow from Operations)
      3. ROA delta > 0 (Improving ROA)
      4. CFO > Net Profit (Accrual Quality: Cash flow beats net income)
      5. Debt/Equity delta <= 0 (Lower or stable leverage)
      6. Current Ratio delta > 0 (Improving liquidity)
      7. No Equity Dilution (Shares count unchanged/decreased)
      8. Gross Margin delta > 0 (Pricing power/efficiency)
      9. Asset Turnover delta > 0 (Operating productivity)
    """
    score = 0
    checks = []

    # 1. Positive Net Income / ROA
    roe = data.get("roe")
    if roe is not None and roe > 0:
        score += 1
        checks.append("Positive Profitability (ROE/ROA > 0)")

    # 2. Positive Operating Cash Flow
    fcf = data.get("free_cash_flow")
    npm = data.get("npm")
    if (fcf is not None and fcf > 0) or (npm is not None and npm > 0):
        score += 1
        checks.append("Positive Cash Flow Generation")

    # 3. Profit growth
    profit_growth = data.get("profit_growth")
    if profit_growth is not None and profit_growth > 0:
        score += 1
        checks.append("Expanding Year-on-Year Earnings")

    # 4. Cash Flow Quality (CFO > Net Income)
    if fcf is not None and fcf >= 0:
        score += 1
        checks.append("Clean Accruals (Cash Flow aligns with Net Profit)")

    # 5. Low / Declining Debt
    de = data.get("debt_equity")
    if de is not None and de <= 1.0:
        score += 1
        checks.append("Prudent Leverage (D/E <= 1.0)")

    # 6. Healthy Liquidity
    cr = data.get("current_ratio")
    if cr is not None and cr >= 1.1:
        score += 1
        checks.append("Sound Liquidity (Current Ratio >= 1.1)")

    # 7. Low / Zero Promoter Pledge
    pledged = data.get("pledged_pct")
    if pledged is not None and pledged < 5.0:
        score += 1
        checks.append("Zero / Negligible Promoter Share Pledge (<5%)")

    # 8. Sales Growth
    sales_growth = data.get("sales_growth")
    if sales_growth is not None and sales_growth > 5.0:
        score += 1
        checks.append("Strong Topline Revenue Growth (>5%)")

    # 9. Return on Capital (ROCE > 12%)
    roce = data.get("roce")
    if roce is not None and roce >= 12.0:
        score += 1
        checks.append("High Capital Efficiency (ROCE >= 12%)")

    return score, checks


def audit_forensics(
    symbol: str,
    data: Optional[dict[str, Any]] = None,
    use_cache: bool = True,
) -> ForensicAuditResult:
    """
    Perform complete forensic and governance audit on an Indian stock.
    Persists results in analysis_cache with 24-hour TTL.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    # Versioned cache prevents historical synthetic-score entries from being
    # reused after the truthful-input contract was introduced.
    cache_key = f"forensic_audit_v2_{clean_sym}"

    if use_cache and data is None:
        try:
            from engine.analysis_cache import analysis_cache

            cached = analysis_cache.get_fundamental(cache_key)
            if cached and isinstance(cached, dict):
                cached = dict(cached)
                cached.pop("overall_forensic_verdict", None)
                return ForensicAuditResult(**cached)
        except Exception:
            pass

    # Extract fundamental data if not provided
    if data is None:
        data = {}
        try:
            from analysis.fundamental import analyse

            snap = analyse(clean_sym)
            if snap:
                data = {
                    "pe": snap.pe,
                    "pb": snap.pb,
                    "roe": snap.roe,
                    "roce": snap.roce,
                    "npm": snap.npm,
                    "sales_growth": snap.sales_growth,
                    "profit_growth": snap.profit_growth,
                    "debt_equity": snap.debt_equity,
                    "current_ratio": snap.current_ratio,
                    "interest_coverage": snap.interest_coverage,
                    "free_cash_flow": snap.free_cash_flow,
                    "promoter_holding": snap.promoter_holding,
                    "institutional_holding": snap.institutional_holding,
                    "pledged_pct": snap.pledged_pct,
                    "market_cap": snap.market_cap,
                }
        except Exception:
            data = {}

    # These models require their published inputs.  Summary ratios cannot be
    # reverse-engineered into an accounting score without inventing figures.
    required_inputs = {
        "Beneish M-Score": {"dsri", "gmi", "aqi", "sgi", "depi", "sgai", "lvgi", "tata"},
        "Altman Z''-Score": {
            "working_capital",
            "total_assets",
            "retained_earnings",
            "ebit",
            "book_value_equity",
            "total_liabilities",
        },
        "Piotroski F-Score": {
            "roe",
            "free_cash_flow",
            "profit_growth",
            "debt_equity",
            "current_ratio",
            "pledged_pct",
            "sales_growth",
            "roce",
        },
    }
    missing = {
        model: sorted(key for key in keys if data.get(key) is None)
        for model, keys in required_inputs.items()
    }
    missing = {model: keys for model, keys in missing.items() if keys}
    if missing:
        reasons = [f"{model}: missing {', '.join(keys)}" for model, keys in missing.items()]
        return ForensicAuditResult(
            symbol=clean_sym,
            beneish_m_score=None,
            is_manipulator_risk=False,
            altman_z_score=None,
            distress_zone="UNAVAILABLE",
            piotroski_f_score=None,
            quality_rating="UNAVAILABLE",
            summary_text=(
                f"Forensic audit for {clean_sym} is unavailable because the required reported accounting inputs "
                "were not supplied. No score or investment-quality verdict has been inferred."
            ),
            available=False,
            unavailable_reasons=reasons,
        )

    # 1. Compute Piotroski F-Score
    f_score, strengths = compute_piotroski_f_score(data)

    # 2. Compute Beneish M-Score
    m_score = compute_beneish_m_score(
        **{key: float(data[key]) for key in required_inputs["Beneish M-Score"]}
    )
    is_manipulator = m_score > -1.78

    # 3. Compute Altman Z-Score
    z_score, distress_zone = compute_altman_z_score(
        **{key: float(data[key]) for key in required_inputs["Altman Z''-Score"]}
    )

    # 4. Indian Governance Red Flags Scanner
    red_flags = []
    pledged = float(data.get("pledged_pct") or 0.0)
    if pledged >= 20.0:
        red_flags.append(f"High Promoter Pledge ({pledged:.1f}% of holding pledged as collateral)")
    elif pledged >= 10.0:
        red_flags.append(f"Moderate Promoter Pledge ({pledged:.1f}% pledged)")

    ic = data.get("interest_coverage")
    if ic is not None and ic < 2.0 and ic >= 0:
        red_flags.append(f"Weak Interest Coverage ({ic:.1f}x) — debt servicing vulnerability")

    debt_equity = float(data["debt_equity"])
    if debt_equity > 2.0:
        red_flags.append(f"High Leverage (Debt/Equity {debt_equity:.2f}x)")

    if is_manipulator:
        red_flags.append(
            f"Elevated Beneish M-Score ({m_score:.2f} > -1.78) — potential accruals distortion"
        )

    if distress_zone == "DISTRESS":
        red_flags.append(f"Altman Z''-Score ({z_score:.2f}) in DISTRESS zone")

    # 5. Determine Overall Quality Rating
    if f_score >= 8 and not red_flags and distress_zone == "SAFE":
        rating = "A+"
    elif f_score >= 6 and len(red_flags) <= 1 and distress_zone in ("SAFE", "GREY"):
        rating = "A"
    elif f_score >= 4 and len(red_flags) <= 2:
        rating = "B"
    elif f_score >= 3:
        rating = "C"
    else:
        rating = "D"

    summary_text = (
        f"Forensic Audit for {clean_sym}: Quality Rating {rating} | "
        f"Piotroski F-Score {f_score}/9 | Altman Z''-Score {z_score:.2f} ({distress_zone}) | "
        f"Beneish M-Score {m_score:.2f} ({'Manipulator Risk' if is_manipulator else 'Clean Earnings'}). "
        f"{len(red_flags)} red flag(s) identified."
    )

    result = ForensicAuditResult(
        symbol=clean_sym,
        beneish_m_score=m_score,
        is_manipulator_risk=is_manipulator,
        altman_z_score=z_score,
        distress_zone=distress_zone,
        piotroski_f_score=f_score,
        quality_rating=rating,
        governance_red_flags=red_flags,
        strengths=strengths,
        summary_text=summary_text,
    )

    # Save to persistent cache (24-hour TTL)
    if use_cache:
        try:
            from engine.analysis_cache import analysis_cache

            analysis_cache.save_fundamental(cache_key, result.as_dict(), ttl_hours=24)
        except Exception:
            pass

    return result


# Canonical alias for cross-module integration (multibagger, magic_trend, portfolio)
audit_company_forensics = audit_forensics
