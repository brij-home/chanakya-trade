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
    # Single-stock options only: within 4 calendar days (Mon-Thu of expiry week)
    return dte <= 4

