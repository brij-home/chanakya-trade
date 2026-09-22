"""
Expiry classification and option contract metadata helpers for ChanakyaTrade.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def classify_expiry_type(expiry_str: Optional[str], symbol: Optional[str] = None) -> str:
    """
    Classifies an Indian market option contract expiry into 'WEEKLY' or 'MONTHLY'.
    - Single-stock equities in NSE/BSE only have monthly options.
    - Index options have weekly expiries, with the final expiry of the month being 'MONTHLY'.
    """
    if not expiry_str:
        return "MONTHLY"
    try:
        dt = None
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(expiry_str.strip(), fmt)
                break
            except ValueError:
                continue
        if not dt:
            return "MONTHLY"
        sym = (symbol or "").upper()
        # Single-stock derivatives on NSE/BSE are strictly monthly contracts
        if sym and sym not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
            return "MONTHLY"
        # For index options, if adding 7 days changes month, it is the last expiry of that month -> MONTHLY
        if (dt + timedelta(days=7)).month != dt.month:
            return "MONTHLY"
        return "WEEKLY"
    except Exception:
        return "MONTHLY"


def get_expiry_metadata(
    expiry_str: Optional[str],
    expiry_type: Optional[str] = None,
    symbol: Optional[str] = None,
    contract_symbol: Optional[str] = None,
) -> dict[str, Any]:
    """
    Computes human-readable month name, weekly date indicator, DTE, and formatted badge string.
    """
    now = datetime.now(IST).date()
    dt = None
    if expiry_str:
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(expiry_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    # Fallback to contract_symbol parsing if expiry_str is missing or unparsed
    if not dt and contract_symbol:
        import re
        from datetime import date
        csym = str(contract_symbol).upper().replace("NSE:", "").replace("NFO:", "").replace("MCX:", "").replace("BSE:", "").strip()

        # 1. Weekly NSE Index Option: e.g. NIFTY2692425000CE
        m_weekly = re.search(r"^([A-Z]+)(\d{2})([1-9OND])(\d{2})", csym)
        if m_weekly:
            yr = 2000 + int(m_weekly.group(2))
            m_code = m_weekly.group(3)
            m_idx = 10 if m_code == "O" else (11 if m_code == "N" else (12 if m_code == "D" else int(m_code)))
            day = int(m_weekly.group(4))
            try:
                dt = date(yr, m_idx, day)
                if not expiry_type:
                    expiry_type = "WEEKLY"
            except ValueError:
                pass

        # 2. Monthly Contract: e.g. NIFTY26SEP25000CE, RELIANCE26SEPFUT, GOLD26SEP154000CE
        if not dt:
            m_monthly = re.search(r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", csym)
            if m_monthly:
                yr = 2000 + int(m_monthly.group(1))
                m_str = m_monthly.group(2)
                month_names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
                if m_str in month_names:
                    m_idx = month_names.index(m_str) + 1
                    clean_underlying = (symbol or "").upper().replace("MCX:", "").strip()
                    from market.instruments import COMMODITY_SYMBOLS
                    is_comm = (
                        clean_underlying in COMMODITY_SYMBOLS
                        or any(csym.startswith(c) for c in COMMODITY_SYMBOLS)
                    )
                    if is_comm:
                        try:
                            from engine.greeks_manager import get_mcx_prompt_expiry_and_dte
                            comm_sym = clean_underlying if clean_underlying in COMMODITY_SYMBOLS else next((c for c in COMMODITY_SYMBOLS if csym.startswith(c)), "CRUDEOIL")
                            exp_date_str, _ = get_mcx_prompt_expiry_and_dte(comm_sym)
                            dt = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                            if not expiry_type:
                                expiry_type = "MONTHLY"
                        except Exception:
                            pass
                    if not dt:
                        try:
                            dt = get_last_thursday_of_month(yr, m_idx)
                            if not expiry_type:
                                expiry_type = "MONTHLY"
                        except Exception:
                            pass

    if not dt:
        return {
            "formatted": None,
            "month_name": None,
            "dte": None,
            "is_weekly": expiry_type == "WEEKLY",
            "is_monthly": expiry_type != "WEEKLY",
            "weekday": None,
        }

    month_name = dt.strftime("%b %Y")
    weekday = dt.strftime("%a")
    dte = (dt - now).days
    is_weekly = (expiry_type == "WEEKLY") or (classify_expiry_type(expiry_str, symbol) == "WEEKLY")

    if is_weekly:
        formatted = f"{dt.strftime('%d-%b-%Y')} ({weekday}) Weekly Expiry"
    else:
        formatted = f"{month_name} Monthly Expiry ({dt.strftime('%d-%b-%Y')})"

    return {
        "formatted": formatted,
        "month_name": month_name,
        "dte": dte,
        "is_weekly": is_weekly,
        "is_monthly": not is_weekly,
        "weekday": weekday,
        "raw_date": dt.strftime("%Y-%m-%d"),
    }


def get_next_expiry_opportunity(
    alert: Any,
    exp_info: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Identifies if the trade benefits from rolling/targeting the next expiry
    with explicit institutional rationale (theta decay, multi-session hold, pin risk).
    """
    is_deriv = bool(
        getattr(alert, "strike", None)
        or getattr(alert, "option_type", None)
        or getattr(alert, "contract_symbol", None)
        or getattr(alert, "derivative_type", None) == "FUT"
        or getattr(alert, "alert_type", None) in ("GAMMA_BLAST", "FUTURES")
    )
    if not is_deriv:
        return None

    dte = exp_info.get("dte")
    plan = getattr(alert, "actionable_plan", {}) or {}
    trade_plan = plan.get("trade_plan", {}) if isinstance(plan, dict) else {}
    has_overrun_risk = trade_plan.get("session_overrun_risk", False)
    theta_drag = trade_plan.get("theta_drag_pct_of_gain", 0)

    # Opportunity triggers: DTE <= 4 days OR multi-session carry OR high theta drag
    if (dte is not None and dte <= 4) or has_overrun_risk or theta_drag >= 1.0:
        if exp_info.get("is_weekly"):
            rec = "Next Weekly or Monthly Expiry"
            justification = (
                f"Current weekly contract has elevated theta decay risk ({dte if dte is not None else '<4'} DTE). "
                "Targeting the next weekly or monthly expiry affords sufficient runway for the thesis to materialize "
                "without severe gamma pin-risk or rapid premium decay."
            )
        else:
            rec = "Next Monthly Expiry (Oct 2026)"
            justification = (
                f"Current monthly contract is in terminal decay cycle ({dte if dte is not None else '≤4'} DTE). "
                "Rolling to the next monthly cycle provides 30+ sessions of runway and eliminates overnight theta drain."
            )
        return {
            "recommended_contract": rec,
            "tag": "THETA-HEDGED ROLL",
            "justification": justification,
            "dte": dte,
        }
    return None


def is_alert_option_premium_level(alert: Any) -> bool:
    """
    Determines if an alert's primary numerical price levels (ltp, stop_loss, target_level)
    represent option contract premiums rather than underlying equity/spot prices.
    Returns True for pure option strategies (OPTIONS_MOMENTUM, OPTION_WRITE, GAMMA_BLAST with option_type)
    or when alert.contract_symbol represents an active option contract.
    Returns False for underlying stock/index setups even if an option recommendation is attached.
    """
    atype = str(getattr(alert, "alert_type", "") or "")
    if atype in ("OPTIONS_MOMENTUM", "OPTION_WRITE"):
        return True
    if atype == "GAMMA_BLAST" and getattr(alert, "option_type", None):
        return True

    # Underlying stock/index setups are always anchored to spot
    if atype in (
        "ASYMMETRIC_OPPORTUNITY",
        "SQUEEZE_BREAKOUT",
        "SQUEEZE_BREAKDOWN",
        "POCKET_PIVOT",
        "PRECURSOR_RADAR",
        "SMC_SWEEP",
        "CIRCUIT_WARNING",
        "COMMODITY_MOMENTUM",
    ):
        return False

    csym = str(getattr(alert, "contract_symbol", "") or "").upper()
    opt_t = str(getattr(alert, "option_type", "") or "").upper()

    if atype == "GAMMA_BLAST" and (
        opt_t in ("CE", "PE") or csym.endswith("CE") or csym.endswith("PE")
    ):
        return True

    has_opt_marker = bool(csym or opt_t in ("CE", "PE") or getattr(alert, "strike", None))
    if not has_opt_marker:
        return False

    # Check contract_symbol pattern for option contracts (e.g. NIFTY24500CE, MAZDOCK2400CE on NFO/NSE)
    if csym and (csym.endswith("CE") or csym.endswith("PE")):
        return True

    if opt_t in ("CE", "PE") and getattr(alert, "strike", None):
        return True

    # Check if ltp is close to option_premium (within 25% tolerance) for other derivatives
    ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
    opt_prem = getattr(alert, "option_premium", None)
    if opt_prem is not None and float(opt_prem) > 0 and ltp > 0:
        prem = float(opt_prem)
        return abs(ltp - prem) <= max(2.0, prem * 0.25)

    return False


def _parse_expiry_date(expiry_str: Optional[str]) -> Optional[datetime.date]:
    """Internal helper to parse varied Indian exchange expiry string formats."""
    if not expiry_str:
        return None
    clean = str(expiry_str).split("T")[0].strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def is_0dte_expiry(expiry_str: Optional[str], ref_dt: Optional[datetime] = None) -> bool:
    """Returns True if the option contract expires on the current session date (0 DTE)."""
    exp_d = _parse_expiry_date(expiry_str)
    if not exp_d:
        return False
    now_d = (ref_dt or datetime.now(IST)).date()
    return exp_d == now_d


def is_0dte_afternoon(expiry_str: Optional[str], ref_dt: Optional[datetime] = None) -> bool:
    """
    Returns True if today is expiry day AND the current session is in the afternoon
    theta decay acceleration phase (>= 12:30 IST).
    """
    now_dt = ref_dt or datetime.now(IST)
    if not is_0dte_expiry(expiry_str, ref_dt=now_dt):
        return False
    from datetime import time as dtime
    return now_dt.time() >= dtime(12, 30)


def is_monthly_physical_expiry_week(
    expiry_str: Optional[str],
    symbol: Optional[str] = None,
    ref_dt: Optional[datetime] = None,
) -> bool:
    """
    Returns True if a single-stock option is in the final 4 trading days of its monthly physical
    settlement expiry week, where SEBI margin requirements surge 300%-500% and liquidity dries up.
    """
    exp_d = _parse_expiry_date(expiry_str)
    if not exp_d:
        return False
    now_d = (ref_dt or datetime.now(IST)).date()
    dte = (exp_d - now_d).days
    if dte < 0:
        return False
    # If symbol is index, physical delivery does not apply (indices are cash settled in India)
    is_idx = (symbol or "").upper() in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    if is_idx:
        return False
    # Single-stock derivatives only: within 4 calendar days (Mon-Thu of expiry week)
    return dte <= 4


def get_last_thursday_of_month(year: int, month: int) -> "date":
    """
    Calculates the last Thursday of a given month (canonical NSE/BSE monthly derivatives expiry).
    """
    import calendar
    from datetime import date as ddate

    _, last_day = calendar.monthrange(year, month)
    d = ddate(year, month, last_day)
    # weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    offset = (d.weekday() - 3) % 7
    return d - timedelta(days=offset)


def get_next_monthly_expiry_date(ref_dt: Optional[datetime] = None) -> "date":
    """
    Returns the last Thursday of the subsequent month (Next-Month Expiry).
    Used during monthly settlement week to route stock options and stock futures
    into the next series, bypassing SEBI physical delivery margin surges and gamma crush.
    """
    now_d = (ref_dt or datetime.now(IST)).date()
    if now_d.month == 12:
        next_year = now_d.year + 1
        next_month = 1
    else:
        next_year = now_d.year
        next_month = now_d.month + 1
    return get_last_thursday_of_month(next_year, next_month)


def resolve_recommended_derivative_expiry(
    symbol: str,
    instrument_type: str = "OPTION",
    current_expiry: Optional[str] = None,
    available_expiries: Optional[list[str]] = None,
    ref_dt: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Institutional expiry selector for Indian Equities and Indices (Options & Futures).

    - Indices (NIFTY/BANKNIFTY/FINNIFTY/SENSEX):
      Cash settled by SEBI. Zero physical delivery risk. Preserves nearest weekly or monthly expiry.

    - Equities (Single-Stock Options & Single-Stock Futures):
      Mandatory SEBI Physical Delivery settlement.
      During settlement week (DTE <= 4), exchanges enforce staggered margins (25% -> 100% full lot value).
      Automatically routes trade intent to the Next-Month series to ensure:
        1. Zero physical delivery margin risk (30+ DTE).
        2. Zero broker RMS forced midday square-off.
        3. Alignment with institutional FII/DII rollover liquidity.
        4. Elimination of severe gamma/theta decay traps.
    """
    now_dt = ref_dt or datetime.now(IST)
    now_d = now_dt.date()
    clean_sym = (
        (symbol or "")
        .upper()
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("BSE:", "")
        .replace("BFO:", "")
        .strip()
    )
    is_idx = clean_sym in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )

    # 1. Parse current near expiry
    near_exp_d = None
    if current_expiry:
        near_exp_d = _parse_expiry_date(current_expiry)
    elif available_expiries:
        for exp in available_expiries:
            p = _parse_expiry_date(exp)
            if p and p >= now_d:
                near_exp_d = p
                break

    if not near_exp_d:
        # Default to current month's last Thursday
        near_exp_d = get_last_thursday_of_month(now_d.year, now_d.month)
        if near_exp_d < now_d:
            near_exp_d = get_next_monthly_expiry_date(now_dt)

    dte = (near_exp_d - now_d).days

    # 2. Indices: Cash settled -> remain on current weekly or monthly expiry
    if is_idx:
        return {
            "recommended_expiry": near_exp_d.strftime("%Y-%m-%d"),
            "is_next_month_routed": False,
            "series": "CURRENT_SERIES",
            "reason": "Cash settled index — no physical delivery margin risk.",
            "margin_risk": "NORMAL",
            "badge": "CASH_SETTLED_INDEX",
        }

    # 3. Single-Stock Derivatives: Check for SEBI Physical Settlement Expiry Week (DTE <= 4)
    if dte <= 4:
        # Find next-month expiry date from available_expiries if provided, else compute
        next_exp_d = None
        if available_expiries:
            for exp in available_expiries:
                p = _parse_expiry_date(exp)
                # Next monthly expiry must be at least 15 days out
                if p and (p - now_d).days > 15:
                    next_exp_d = p
                    break

        if not next_exp_d:
            next_exp_d = get_next_monthly_expiry_date(now_dt)

        inst_label = "stock futures" if instrument_type.upper().startswith("FUT") else "stock options"
        return {
            "recommended_expiry": next_exp_d.strftime("%Y-%m-%d"),
            "near_expiry": near_exp_d.strftime("%Y-%m-%d"),
            "is_next_month_routed": True,
            "series": "NEXT_MONTH",
            "reason": (
                f"SEBI Physical Settlement Week (DTE={dte}): Near-month {inst_label} carry staggered delivery "
                f"margin risk (25%->100% full stock value). Automatically routed to Next-Month series."
            ),
            "margin_risk": "PROTECTED",
            "badge": "🎯 NEXT-MONTH ROLLOVER",
        }

    # Normal trading period (DTE > 4)
    return {
        "recommended_expiry": near_exp_d.strftime("%Y-%m-%d"),
        "is_next_month_routed": False,
        "series": "CURRENT_MONTH",
        "reason": "Normal trading cycle (DTE > 4) — high near-month liquidity.",
        "margin_risk": "NORMAL",
        "badge": "CURRENT_MONTH",
    }


