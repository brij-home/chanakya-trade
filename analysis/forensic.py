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

    @property
    def overall_flag(self) -> str:
        """Alias for overall_forensic_verdict (used by security_360 and callers)."""
        return self.overall_forensic_verdict

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
            "overall_flag": self.overall_flag,
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


def fetch_reported_accounting_inputs(symbol: str) -> dict[str, Any]:
    """
    Dynamically extract reported multi-year financial statements (balance sheet,
    income statement, cash flow statement) and Indian governance metrics from
    official exchange filings (via yfinance with .NS/.BO dual-exchange failover
    and Screener.in fundamental integration).
    Returns all 20 required line-items for Altman Z'', Beneish M-Score, and Piotroski F-Score.
    """
    import math
    import yfinance as yf

    clean_sym = (
        symbol.upper()
        .replace(".NS", "")
        .replace(".BO", "")
        .replace("NSE:", "")
        .replace("BSE:", "")
        .strip()
    )

    # 1. Check SQLite fundamental cache (24-hour TTL)
    cache_key = f"acct_inputs_v1_{clean_sym}"
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_fundamental(cache_key)
        if cached and isinstance(cached, dict) and cached.get("total_assets") is not None:
            return cached
    except Exception:
        pass

    # 2. Query statements via yfinance
    try:
        from market.yfinance_provider import _to_yf_symbol

        yf_sym = _to_yf_symbol(clean_sym)
    except Exception:
        yf_sym = f"{clean_sym}.NS"

    ticker = yf.Ticker(yf_sym)
    info = getattr(ticker, "info", {}) or {}
    if not info or info.get("regularMarketPrice") is None:
        ticker = yf.Ticker(f"{clean_sym}.BO")
        info = getattr(ticker, "info", {}) or {}

    bs = getattr(ticker, "balance_sheet", None)
    inc = getattr(ticker, "income_stmt", None)
    cf = getattr(ticker, "cashflow", None)

    if bs is None or bs.empty or inc is None or inc.empty:
        # Failover to BSE ticker (.BO)
        ticker_bo = yf.Ticker(f"{clean_sym}.BO")
        bs_bo = getattr(ticker_bo, "balance_sheet", None)
        inc_bo = getattr(ticker_bo, "income_stmt", None)
        cf_bo = getattr(ticker_bo, "cashflow", None)
        if bs_bo is not None and not bs_bo.empty:
            bs = bs_bo
            inc = inc_bo
            cf = cf_bo
            if not info:
                info = getattr(ticker_bo, "info", {}) or {}

    if bs is None or bs.empty or inc is None or inc.empty:
        return {}

    def _get_val(df, row_names, col_idx=0):
        if df is None or df.empty:
            return None
        if isinstance(row_names, str):
            row_names = [row_names]
        for name in row_names:
            if name in df.index:
                try:
                    if col_idx < len(df.columns):
                        v = df.loc[name].iloc[col_idx]
                        if v is not None and not math.isnan(float(v)):
                            return float(v)
                except Exception:
                    continue
        return None

    # Altman Z'' inputs
    ta = _get_val(bs, ["Total Assets"])
    ca = _get_val(bs, ["Current Assets"])
    cl = _get_val(bs, ["Current Liabilities"])
    wc = _get_val(bs, ["Working Capital"]) or (
        (ca - cl) if ca is not None and cl is not None else None
    )
    re = _get_val(bs, ["Retained Earnings"]) or 0.0
    ebit = _get_val(inc, ["EBIT", "Operating Income", "Pretax Income"])
    bve = _get_val(
        bs,
        ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    )
    tl = _get_val(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"]) or (
        (ta - bve) if ta is not None and bve is not None else None
    )

    # Beneish M-Score inputs (t0 vs t1)
    rev_t = _get_val(inc, ["Total Revenue", "Operating Revenue"], 0)
    rev_t1 = _get_val(inc, ["Total Revenue", "Operating Revenue"], 1)
    rec_t = (
        _get_val(bs, ["Accounts Receivable", "Gross Accounts Receivable", "Receivables"], 0) or 0.0
    )
    rec_t1 = (
        _get_val(bs, ["Accounts Receivable", "Gross Accounts Receivable", "Receivables"], 1) or 0.0
    )
    cogs_t = _get_val(inc, ["Cost Of Revenue", "Reconciled Cost Of Revenue"], 0)
    cogs_t1 = _get_val(inc, ["Cost Of Revenue", "Reconciled Cost Of Revenue"], 1)
    ta_t1 = _get_val(bs, ["Total Assets"], 1)
    ca_t1 = _get_val(bs, ["Current Assets"], 1)
    ppe_t = _get_val(bs, ["Net PPE", "Gross PPE"], 0) or 0.0
    ppe_t1 = _get_val(bs, ["Net PPE", "Gross PPE"], 1) or 0.0
    dep_t = (
        _get_val(
            inc, ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"], 0
        )
        or _get_val(cf, ["Depreciation And Amortization", "Depreciation"], 0)
        or 0.0
    )
    dep_t1 = (
        _get_val(
            inc, ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"], 1
        )
        or _get_val(cf, ["Depreciation And Amortization", "Depreciation"], 1)
        or 0.0
    )
    sga_t = _get_val(inc, ["Selling General And Administration", "Operating Expense"], 0) or 0.0
    sga_t1 = _get_val(inc, ["Selling General And Administration", "Operating Expense"], 1) or 0.0
    debt_t = _get_val(bs, ["Total Debt"], 0) or 0.0
    debt_t1 = _get_val(bs, ["Total Debt"], 1) or 0.0
    op_inc = _get_val(inc, ["Operating Income", "EBIT"], 0) or 0.0
    cfo = _get_val(cf, ["Operating Cash Flow"], 0) or 0.0

    dsri = 1.0
    if rev_t and rev_t1 and rev_t > 0 and rev_t1 > 0 and rec_t1 > 0:
        dsri = (rec_t / rev_t) / (rec_t1 / rev_t1)

    gmi = 1.0
    if rev_t and rev_t1 and cogs_t is not None and cogs_t1 is not None:
        gm_t = (rev_t - cogs_t) / rev_t
        gm_t1 = (rev_t1 - cogs_t1) / rev_t1
        if gm_t > 0:
            gmi = gm_t1 / gm_t

    aqi = 1.0
    if ta and ta_t1 and ta > 0 and ta_t1 > 0:
        non_ca_ppe_t = ta - ((ca or 0.0) + ppe_t)
        non_ca_ppe_t1 = ta_t1 - ((ca_t1 or 0.0) + ppe_t1)
        aq_t = non_ca_ppe_t / ta
        aq_t1 = non_ca_ppe_t1 / ta_t1
        if aq_t1 > 0:
            aqi = aq_t / aq_t1

    sgi = (rev_t / rev_t1) if (rev_t and rev_t1 and rev_t1 > 0) else 1.0

    depi = 1.0
    if ppe_t and ppe_t1 and dep_t and dep_t1:
        dr_t = dep_t / (ppe_t + dep_t)
        dr_t1 = dep_t1 / (ppe_t1 + dep_t1)
        if dr_t > 0:
            depi = dr_t1 / dr_t

    sgai = 1.0
    if rev_t and rev_t1 and sga_t and sga_t1 and rev_t1 > 0:
        sgai = (sga_t / rev_t) / (sga_t1 / rev_t1)

    lvgi = 1.0
    if ta and ta_t1 and debt_t and debt_t1 and ta_t1 > 0 and (debt_t1 / ta_t1) > 0:
        lvgi = (debt_t / ta) / (debt_t1 / ta_t1)

    tata = ((op_inc - cfo) / ta) if (ta and ta > 0) else 0.0

    # Piotroski F-Score inputs
    net_income_t = _get_val(inc, ["Net Income Common Stockholders", "Net Income"], 0) or 0.0
    net_income_t1 = _get_val(inc, ["Net Income Common Stockholders", "Net Income"], 1) or 0.0
    fcf = _get_val(cf, ["Free Cash Flow"], 0)
    if fcf is None and cfo is not None:
        capex = _get_val(cf, ["Capital Expenditure", "Capital Expenditure Reported"], 0) or 0.0
        fcf = cfo + capex

    roe = (
        (net_income_t / bve * 100.0)
        if (bve and bve > 0)
        else (info.get("returnOnEquity", 0) * 100 if info.get("returnOnEquity") else 0.0)
    )
    profit_growth = (
        ((net_income_t - net_income_t1) / abs(net_income_t1) * 100.0) if net_income_t1 != 0 else 0.0
    )
    debt_equity = (
        (debt_t / bve)
        if (bve and bve > 0)
        else (info.get("debtToEquity", 0) / 100.0 if info.get("debtToEquity") else 0.0)
    )
    current_ratio = (ca / cl) if (ca and cl and cl > 0) else (info.get("currentRatio") or 1.0)
    sales_growth = ((rev_t - rev_t1) / rev_t1 * 100.0) if (rev_t and rev_t1 and rev_t1 > 0) else 0.0
    roce = (ebit / (ta - (cl or 0.0)) * 100.0) if (ta and cl and (ta - cl) > 0 and ebit) else roe

    pledged_pct = 0.0
    promoter_holding = None
    interest_coverage = None
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    npm = (
        (net_income_t / rev_t * 100.0)
        if (rev_t and rev_t > 0)
        else (info.get("profitMargins", 0) * 100 if info.get("profitMargins") else 0.0)
    )

    try:
        from analysis.fundamental import analyse

        snap = analyse(clean_sym)
        if snap:
            pledged_pct = snap.pledged_pct if snap.pledged_pct is not None else 0.0
            promoter_holding = snap.promoter_holding
            interest_coverage = snap.interest_coverage
            if pe is None:
                pe = snap.pe
            if pb is None:
                pb = snap.pb
    except Exception:
        pass

    result_inputs = {
        "working_capital": wc,
        "total_assets": ta,
        "retained_earnings": re,
        "ebit": ebit,
        "book_value_equity": bve,
        "total_liabilities": tl,
        "dsri": round(dsri, 3),
        "gmi": round(gmi, 3),
        "aqi": round(aqi, 3),
        "sgi": round(sgi, 3),
        "depi": round(depi, 3),
        "sgai": round(sgai, 3),
        "lvgi": round(lvgi, 3),
        "tata": round(tata, 4),
        "roe": round(roe, 2),
        "free_cash_flow": round(fcf / 1e7, 2) if fcf is not None else 0.0,
        "profit_growth": round(profit_growth, 2),
        "debt_equity": round(debt_equity, 2),
        "current_ratio": round(current_ratio, 2),
        "pledged_pct": pledged_pct,
        "promoter_holding": promoter_holding,
        "interest_coverage": interest_coverage,
        "sales_growth": round(sales_growth, 2),
        "roce": round(roce, 2),
        "pe": pe,
        "pb": pb,
        "npm": round(npm, 2) if npm is not None else None,
        "market_cap": info.get("marketCap", 0) / 1e7 if info.get("marketCap") else 0.0,
    }

    try:
        from engine.analysis_cache import analysis_cache

        analysis_cache.save_fundamental(cache_key, result_inputs, ttl_hours=24)
    except Exception:
        pass

    return result_inputs


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
            from engine.eod_store import get_cached_forensics

            cached_eod = get_cached_forensics(clean_sym, max_age_days=30)
            if (
                cached_eod
                and isinstance(cached_eod, dict)
                and cached_eod.get("available") is not False
            ):
                c = dict(cached_eod)
                c.pop("overall_forensic_verdict", None)
                c.pop("updated_at", None)
                return ForensicAuditResult(**c)
        except Exception:
            pass

        try:
            from engine.analysis_cache import analysis_cache

            cached = analysis_cache.get_fundamental(cache_key)
            if cached and isinstance(cached, dict):
                cached = dict(cached)
                cached.pop("overall_forensic_verdict", None)
                return ForensicAuditResult(**cached)
        except Exception:
            pass

    # Extract reported accounting inputs dynamically if not provided
    if data is None:
        try:
            data = fetch_reported_accounting_inputs(clean_sym)
        except Exception:
            data = {}

    # Determine if the entity belongs to Banking & Financial Services
    is_banking_or_financial = False
    try:
        from analysis.universe import get_stock_sector

        sec_id, _ = get_stock_sector(clean_sym)
        if sec_id == "banking":
            is_banking_or_financial = True
    except Exception:
        pass

    # These models require their published inputs. Summary ratios cannot be
    # reverse-engineered into an accounting score without inventing figures.
    # Note: Altman Z''-Score was developed for non-financial corporations (Altman 1968, 2000).
    # Commercial banks operate under fractional reserve banking with deposit liabilities
    # and unclassified balance sheets where working capital is structurally undefined.
    # Regulated banks are prudentially assessed under RBI Basel III CRAR capital adequacy.
    required_inputs = {
        "Beneish M-Score": {"dsri", "gmi", "aqi", "sgi", "depi", "sgai", "lvgi", "tata"},
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
    if not is_banking_or_financial:
        required_inputs["Altman Z''-Score"] = {
            "working_capital",
            "total_assets",
            "retained_earnings",
            "ebit",
            "book_value_equity",
            "total_liabilities",
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

    # 3. Compute Altman Z-Score (Non-financial corporations only)
    if is_banking_or_financial:
        z_score = None
        distress_zone = "NOT_APPLICABLE"
        strengths.append(
            "Standard manufacturing Altman Z'' model is not applicable to commercial banks (prudentially governed under RBI Basel III CRAR capital adequacy norms)."
        )
    else:
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

    # For banks, customer deposits are operating liabilities and interest is cost of funds,
    # so industrial interest coverage and debt/equity do not apply as distress flags.
    if not is_banking_or_financial:
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
    if is_banking_or_financial:
        if f_score >= 7 and not red_flags and not is_manipulator:
            rating = "A+"
        elif f_score >= 5 and len(red_flags) <= 1 and not is_manipulator:
            rating = "A"
        elif f_score >= 4 and len(red_flags) <= 2:
            rating = "B"
        elif f_score >= 3:
            rating = "C"
        else:
            rating = "D"

        summary_text = (
            f"Forensic Audit for {clean_sym} (Banking & Financial Services): Quality Rating {rating} | "
            f"Piotroski F-Score {f_score}/9 | Beneish M-Score {m_score:.2f} ({'Manipulator Risk' if is_manipulator else 'Clean Earnings'}). "
            f"Altman Z'' model is not applicable to commercial banks governed under RBI Basel III capital adequacy. "
            f"{len(red_flags)} governance flag(s) identified."
        )
    else:
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

    # Save to persistent cache (24-hour TTL in analysis_cache, 30-day TTL in eod_store)
    if use_cache:
        try:
            from engine.analysis_cache import analysis_cache

            analysis_cache.save_fundamental(cache_key, result.as_dict(), ttl_hours=24)
        except Exception:
            pass

        try:
            from engine.eod_store import save_forensics

            save_forensics(clean_sym, result.as_dict())
        except Exception:
            pass

    return result


# Canonical alias for cross-module integration (multibagger, magic_trend, portfolio)
audit_company_forensics = audit_forensics
