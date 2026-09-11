"""
bot/alert_templates.py
──────────────────────
Institutional-grade, zero-redundancy Telegram alert template engine.

Designed for sub-3-second mobile readability:
  - Clean visual hierarchy with monospace data blocks for numbers.
  - Strict zero-redundancy: every price, target, and stop-loss appears exactly once.
  - Compact vertical footprint (10–13 lines max vs former 35–50 lines).
  - Strongly typed dataclasses with automatic dict fallback for seamless dynamic ingestion.
  - Standardized templates for F&O, Equity, Precursor Radar, Asymmetric Setups, and Milestones.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))

INDEX_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 3,       # Thursday
    "BANKNIFTY": 2,   # Wednesday
    "FINNIFTY": 1,    # Tuesday
    "MIDCPNIFTY": 0,  # Monday
    "SENSEX": 4,      # Friday
    "BANKEX": 0,      # Monday
}

INDEX_SYMBOLS = set(INDEX_EXPIRY_WEEKDAY.keys())


# ── Helper Utilities ─────────────────────────────────────────────────────────


def get_last_thursday_of_month(year: int, month: int) -> date:
    """Returns the date of the last Thursday of a given month and year."""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=offset)


def resolve_expiry_cycle(
    contract: str = "",
    expiry_date: Optional[str | datetime | date] = None,
    expiry_type: Optional[str] = None,
    dte: Optional[int | float] = None,
    underlying: str = "NIFTY",
    as_of: Optional[datetime | date] = None,
) -> dict[str, Any]:
    """
    Resolves Indian F&O contract expiry cycle and institutional badge:
      - 0DTE / Today's Expiry
      - Current Weekly
      - Next Weekly
      - Current Monthly
      - Next Monthly
      - Far Monthly

    Handles NSE/BSE Index rules (Weekly/Monthly) vs Single-stock equities (Strictly Monthly).
    Parses dates from ISO 'YYYY-MM-DD', 'DD-Mon-YYYY', or contract name patterns.
    """
    if as_of is None:
        as_of_dt = datetime.now(IST)
        today = as_of_dt.date()
    elif isinstance(as_of, datetime):
        as_of_dt = as_of
        today = as_of.date()
    else:
        as_of_dt = datetime.combine(as_of, datetime.min.time())
        today = as_of

    und = (underlying or "NIFTY").upper().strip()
    is_index = und in INDEX_SYMBOLS

    dt: Optional[date] = None

    # 1. Parse from expiry_date if provided
    if expiry_date:
        if isinstance(expiry_date, datetime):
            dt = expiry_date.date()
        elif isinstance(expiry_date, date):
            dt = expiry_date
        elif isinstance(expiry_date, str):
            clean_exp = expiry_date.strip()
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d%b%Y", "%d-%B-%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(clean_exp, fmt).date()
                    break
                except ValueError:
                    continue

    # 2. Extract from contract string if dt is still None
    if dt is None and contract:
        c_upper = contract.upper().strip()
        # Pattern A: e.g. "17-Sep-2026", "17SEP26", "17-09-2026", "17-Sep"
        m = re.search(r"\b(\d{1,2})[- ]?([A-Za-z]{3})[- ]?(\d{2,4})?\b", contract)
        if m:
            day_str, mon_str, yr_str = m.groups()
            month_map = {
                "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
            }
            mon = month_map.get(mon_str.upper())
            if mon:
                try:
                    day = int(day_str)
                    if yr_str:
                        yr = int("20" + yr_str) if len(yr_str) == 2 else int(yr_str)
                    else:
                        yr = today.year
                    dt = date(yr, mon, day)
                except ValueError:
                    dt = None

        # Pattern B: NSE Weekly format e.g. NIFTY2691725000CE (YY + M + DD)
        if dt is None:
            m_weekly = re.search(r"[A-Z]+(\d{2})([1-9OND])(\d{2})\d+(?:CE|PE)", c_upper)
            if m_weekly:
                yy_str, m_code, dd_str = m_weekly.groups()
                mon_conv = {
                    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
                    "7": 7, "8": 8, "9": 9, "O": 10, "N": 11, "D": 12,
                }
                mon = mon_conv.get(m_code)
                if mon:
                    try:
                        yr = int("20" + yy_str)
                        day = int(dd_str)
                        dt = date(yr, mon, day)
                    except ValueError:
                        dt = None

        # Pattern C: NSE Monthly format e.g. RELIANCE26SEP3000PE
        if dt is None:
            m_monthly = re.search(r"[A-Z]+(\d{2})([A-Z]{3})\d+(?:CE|PE)", c_upper)
            if m_monthly:
                yy_str, mon_str = m_monthly.groups()
                month_map = {
                    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
                }
                mon = month_map.get(mon_str)
                if mon:
                    yr = int("20" + yy_str)
                    dt = get_last_thursday_of_month(yr, mon)

    # 3. Infer target expiry date if still None
    if dt is None:
        if is_index:
            target_weekday = INDEX_EXPIRY_WEEKDAY.get(und, 3)
            days_ahead = (target_weekday - today.weekday()) % 7
            if days_ahead == 0:
                # If market has closed for today's session, next weekly is 7 days ahead
                if as_of_dt.hour > 15 or (as_of_dt.hour == 15 and as_of_dt.minute >= 30):
                    days_ahead = 7
            dt = today + timedelta(days=days_ahead)
        else:
            # Single-stock derivatives are strictly monthly
            cur_last_thu = get_last_thursday_of_month(today.year, today.month)
            if today <= cur_last_thu:
                dt = cur_last_thu
            else:
                next_m = 1 if today.month == 12 else today.month + 1
                next_y = today.year + 1 if today.month == 12 else today.year
                dt = get_last_thursday_of_month(next_y, next_m)

    # 4. Calculate DTE
    calc_dte = (dt - today).days if dt else 0
    final_dte = int(dte) if dte is not None else calc_dte

    # 5. Classify monthly vs weekly
    if not is_index:
        is_monthly = True
        is_weekly = False
    else:
        norm_exp_type = (expiry_type or "").upper()
        if "WEEKLY" in norm_exp_type:
            is_weekly = True
            is_monthly = False
        elif "MONTHLY" in norm_exp_type:
            is_monthly = True
            is_weekly = False
        elif dt:
            # Check if last expiry of calendar month
            is_monthly = (dt + timedelta(days=7)).month != dt.month
            is_weekly = not is_monthly
        else:
            is_weekly = True
            is_monthly = False

    # 6. Determine cycle classification
    cycle_override = (expiry_type or "").upper()
    cycle: str = ""

    if final_dte == 0:
        cycle = "0DTE / Today's Expiry"
    elif final_dte < 0:
        cycle = "Expired"
    elif cycle_override in ("CURRENT_WEEKLY", "NEXT_WEEKLY", "CURRENT_MONTHLY", "NEXT_MONTHLY", "FAR_MONTHLY"):
        cycle_name_map = {
            "CURRENT_WEEKLY": "Current Weekly",
            "NEXT_WEEKLY": "Next Weekly",
            "CURRENT_MONTHLY": "Current Monthly",
            "NEXT_MONTHLY": "Next Monthly",
            "FAR_MONTHLY": "Far Monthly",
        }
        cycle = cycle_name_map[cycle_override]
    elif is_weekly:
        if final_dte <= 7:
            cycle = "Current Weekly"
        elif 7 < final_dte <= 14:
            cycle = "Next Weekly"
        else:
            cycle = "Far Weekly"
    else:  # is_monthly
        month_diff = (dt.year - today.year) * 12 + (dt.month - today.month) if dt else 0
        if month_diff <= 0:
            if is_index and final_dte <= 7:
                cycle = "Current Weekly & Monthly"
            else:
                cycle = "Current Monthly"
        elif month_diff == 1:
            cycle = "Next Monthly"
        else:
            cycle = "Far Monthly"

    # 7. Construct crisp badge
    dt_str = dt.strftime("%d-%b-%Y") if dt else ""
    if final_dte == 0:
        badge = f"⚡ 0DTE / Today's Expiry · {dt_str}" if dt_str else "⚡ 0DTE / Today's Expiry"
    elif final_dte < 0:
        badge = f"Expired · {dt_str}" if dt_str else "Expired"
    else:
        dte_str = f" ({final_dte} DTE)" if final_dte is not None else ""
        badge = f"{cycle} · {dt_str}{dte_str}" if dt_str else f"{cycle}{dte_str}"

    return {
        "cycle": cycle,
        "expiry_date": dt_str,
        "raw_date": dt.strftime("%Y-%m-%d") if dt else "",
        "dte": final_dte,
        "is_weekly": is_weekly,
        "is_monthly": is_monthly,
        "is_0dte": final_dte == 0,
        "badge": badge,
    }


def _parse_ts_to_dt(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse various timestamp string formats into datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    cleaned = ts_str.replace(" IST", "").strip()
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fmt == "%H:%M:%S":
                now = datetime.now()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt
        except ValueError:
            continue
    return None


def _format_call_time_and_elapsed(
    call_time_str: Optional[str], update_time_str: Optional[str] = None
) -> tuple[str, str]:
    """
    Returns (formatted_call_time, elapsed_duration_str).
    e.g. ("9:42 AM IST (Today)", " (⏱️ 1h 03m ago)") or ("11 Sep, 9:42 AM IST", " (⏱️ 45m ago)")
    """
    if not call_time_str or not isinstance(call_time_str, str):
        return ("", "")
    dt_call = _parse_ts_to_dt(call_time_str)
    if not dt_call:
        return (call_time_str.strip(), "")

    dt_update = _parse_ts_to_dt(update_time_str) if update_time_str else datetime.now()
    if not dt_update:
        dt_update = datetime.now()

    same_day = (
        dt_call.year == dt_update.year
        and dt_call.month == dt_update.month
        and dt_call.day == dt_update.day
    )
    time_part = dt_call.strftime("%I:%M %p IST").lstrip("0")
    if same_day:
        formatted_call = f"{time_part} (Today)"
    else:
        formatted_call = f"{dt_call.strftime('%d %b')}, {time_part}"

    delta_seconds = int((dt_update - dt_call).total_seconds())
    if delta_seconds < 0:
        delta_seconds = 0

    if delta_seconds < 60:
        elapsed_str = f" (⏱️ {delta_seconds}s ago)"
    elif delta_seconds < 3600:
        mins = delta_seconds // 60
        elapsed_str = f" (⏱️ {mins}m ago)"
    elif delta_seconds < 86400:
        hours = delta_seconds // 3600
        mins = (delta_seconds % 3600) // 60
        elapsed_str = f" (⏱️ {hours}h {mins:02d}m ago)" if mins else f" (⏱️ {hours}h ago)"
    else:
        days = delta_seconds // 86400
        hours = (delta_seconds % 86400) // 3600
        elapsed_str = f" (⏱️ {days}d {hours}h ago)" if hours else f" (⏱️ {days}d ago)"

    return (formatted_call, elapsed_str)


def build_signal_ref(
    symbol: str,
    alert_id: str = "",
    contract: str = "",
    created_at: str = "",
) -> str:
    """
    Builds an institutional, human-readable, non-clashing Telegram-clickable hashtag reference.
    Telegram hashtags cannot contain hyphens or spaces (only alphanumeric and underscores).
    Uses Date + Time (IST) for instant cognitive recognition and one-click thread searchability:
      #SIG_HAL_4500CE_11SEP_0942
      #SIG_BANKNIFTY_52000PE_11SEP_0942
      #SIG_TRENT_11SEP_0942
    """
    clean_sym = re.sub(r"[^A-Za-z0-9]", "", symbol).upper() if symbol else "TRADE"

    # 1. Resolve Contract/Strike tag if available
    contract_tag = ""
    if contract and contract != symbol:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)", contract, re.IGNORECASE)
        if m:
            strike_str = m.group(1).replace(".0", "")
            opt_str = m.group(2).upper()
            contract_tag = f"{strike_str}{opt_str}"
        else:
            clean_c = re.sub(r"[^A-Za-z0-9]", "", contract).upper()
            if clean_c and clean_c != clean_sym:
                contract_tag = clean_c[-8:]

    # 2. Resolve Date & Time in IST
    dt: Optional[datetime] = None
    if created_at:
        dt = _parse_ts_to_dt(created_at)
    if not dt:
        dt = datetime.now(IST)

    day_str = dt.strftime("%d%b").upper()  # e.g. "11SEP"
    time_str = dt.strftime("%H%M")         # e.g. "0942"
    ts_tag = f"{day_str}_{time_str}"

    # 3. Assemble unique hashtag
    if contract_tag:
        return f"#SIG_{clean_sym}_{contract_tag}_{ts_tag}"

    return f"#SIG_{clean_sym}_{ts_tag}"


def escape_tg(text: Any) -> str:
    """Safely escape text for Telegram HTML mode."""
    if text is None:
        return ""
    s = str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_price(val: Any) -> str:
    """Format numeric value as Indian Rupee string or pass through if string."""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return f"₹{val:,.2f}"
    s = str(val).strip()
    if s.startswith("₹") or s.startswith("`") or s == "Open":
        return s
    try:
        f = float(s.replace(",", "").replace("₹", ""))
        return f"₹{f:,.2f}"
    except ValueError:
        return s


def format_short_pct(pct: Any) -> str:
    """Format percentage with +/- sign."""
    if pct is None:
        return ""
    s = str(pct).strip()
    if s.endswith("%"):
        return s
    try:
        f = float(s)
        sign = "+" if f > 0 else ""
        return f"{sign}{f:.1f}%"
    except ValueError:
        return s


def normalize_env_tag(env: Optional[str], in_market: bool = True) -> str:
    """Resolve unified [REAL/LIVE], [OFF-MARKET/EOD], or [TEST] provenance tag."""
    e = (env or "LIVE").upper()
    if e in ("TEST", "SIMULATED", "DEMO"):
        return "[TEST]"
    if not in_market or e in ("EOD", "OFF-MARKET", "OFF_MARKET"):
        return "[OFF-MARKET]"
    return "[REAL/LIVE]"


def strip_provenance_and_icons(text: str) -> str:
    """Strip redundant leading emojis and provenance tags ([REAL/LIVE], [TEST], etc.) from a headline."""
    if not text:
        return ""
    s = text.strip()
    # Strip any [REAL/LIVE], [REAL / LIVE], [TEST], [OFF-MARKET], [POST-MARKET ...]
    s = re.sub(
        r"\[(?:REAL\s*/\s*LIVE|TEST|OFF-MARKET|POST-MARKET[^\]]*)\]\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # Strip leading alert emojis followed by optional space
    s = re.sub(r"^[🚨🎯🚀⚡🛢️💱🟢⚠️🏆💎🔔🌙\s]+", "", s)
    return s.strip()


# ── Dataclasses for Dynamic Alert Ingestion ──────────────────────────────────


@dataclass
class FNOAlertData:
    """Data container for F&O (Options / Futures / Gamma Blast) alerts."""

    contract: str
    underlying: str = "NIFTY"
    spot: float = 0.0
    action: str = "BUY"
    score: int = 85
    option_type: str = "CE"
    entry_range: str = ""
    premium: float = 0.0
    stop_loss: float = 0.0
    stop_loss_pct: str = "-25.0%"
    target_1: float = 0.0
    target_1_pct: str = "+30.0%"
    target_2: float = 0.0
    target_2_pct: str = "+55.0%"
    risk_reward: str = "1:2.5"
    no_chase_limit: Optional[str] = None
    vol_oi: float = 2.5
    imbalance: float = 2.0
    oi_change: int = 0
    trigger_reason: str = "Institutional order flow surge"
    when_to_buy: str = ""
    profit_rule: str = "Scale 50% & SL to Cost"
    conviction_score: Optional[dict[str, Any]] = None
    environment: str = "LIVE"
    in_market: bool = True
    action_title: Optional[str] = None
    expiry_date: Optional[str] = None
    expiry_type: Optional[str] = None
    dte: Optional[int] = None
    expiry_cycle: Optional[str] = None
    expiry_badge: Optional[str] = None

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        underlying: str = "NIFTY",
        spot: float = 0.0,
        conviction_score: Optional[dict[str, Any]] = None,
        in_market: bool = True,
    ) -> FNOAlertData:
        prem = float(d.get("premium", d.get("entry_price", d.get("ask", 0.0))) or 50.0)
        e_low = d.get("entry_low") or round(max(0.5, prem * 0.95), 2)
        e_high = d.get("entry_high") or round(prem * 1.03, 2)
        entry_range = d.get("entry_range") or f"₹{e_low:,.2f} – ₹{e_high:,.2f}"

        sl = float(d.get("stop_loss", prem * 0.75))
        sl_pct = str(d.get("stop_loss_pct", "-25.0%"))
        t1 = float(d.get("target_1", prem * 1.35))
        t1_pct = str(d.get("target_1_pct", "+35.0%"))
        t2 = float(d.get("target_2", prem * 1.65))
        t2_pct = str(d.get("target_2_pct", "+65.0%"))
        rr = str(d.get("risk_reward", "1:2.5"))

        no_chase = d.get("no_chase_limit") or d.get("no_chase")
        if not no_chase:
            when_wait = d.get("when_to_wait", "")
            match = re.search(r"₹([\d,]+(?:\.\d+)?)", when_wait)
            if match:
                no_chase = f"₹{match.group(1)}"
            else:
                no_chase = f"₹{round(prem * 1.15, 2):,.2f}"

        contract = d.get("contract", f"{underlying} OPTION")
        action_title = d.get("action_title", f"BUY {contract}")

        und = d.get("underlying", underlying)
        exp_date = d.get("expiry_date", d.get("expiry", d.get("expiry_contract")))
        exp_type = d.get("expiry_type", d.get("contract_cycle", d.get("cycle")))
        raw_dte = d.get("dte", d.get("days_to_expiry"))
        exp_info = resolve_expiry_cycle(
            contract=contract,
            expiry_date=exp_date,
            expiry_type=exp_type,
            dte=raw_dte,
            underlying=und,
        )

        return cls(
            contract=contract,
            underlying=und,
            spot=float(d.get("spot", spot) or 0.0),
            action=d.get("action", "BUY"),
            score=int(d.get("score", d.get("conviction_score", 85))),
            option_type=d.get("option_type", "CE"),
            entry_range=entry_range,
            premium=prem,
            stop_loss=sl,
            stop_loss_pct=sl_pct,
            target_1=t1,
            target_1_pct=t1_pct,
            target_2=t2,
            target_2_pct=t2_pct,
            risk_reward=rr,
            no_chase_limit=no_chase,
            vol_oi=float(d.get("vol_oi_ratio", d.get("vol_oi", 2.5))),
            imbalance=float(d.get("imbalance_ratio", d.get("imbalance", 2.0))),
            oi_change=int(d.get("oi_change", 0)),
            trigger_reason=d.get(
                "blast_reason",
                d.get("reason", d.get("summary", "Institutional order flow surge")),
            ),
            when_to_buy=d.get("when_to_buy", ""),
            profit_rule=d.get("profit_rule", "Scale 50% & SL to Cost"),
            conviction_score=conviction_score or d.get("conviction_score_dict"),
            environment=d.get("environment", "LIVE"),
            in_market=in_market,
            action_title=action_title,
            expiry_date=exp_info.get("expiry_date"),
            expiry_type=d.get("expiry_type", exp_info.get("cycle")),
            dte=exp_info.get("dte"),
            expiry_cycle=exp_info.get("cycle"),
            expiry_badge=exp_info.get("badge"),
        )


@dataclass
class EquityAlertData:
    """Data container for Equity execution readiness, breakouts, and swing setups."""

    symbol: str
    sector: str = "General"
    sector_icon: str = "🏢"
    ltp: float = 0.0
    status: str = "READY"  # "READY" | "STALK" | "IGNITED" | "EARLY_WARNING"
    setup_title: str = "Stage 2 Breakout"
    action: str = "BUY"
    entry_range: str = ""
    stop_loss: float = 0.0
    risk_pct: float = 0.0
    target_1: float = 0.0
    t1_pct: float = 0.0
    target_2: float = 0.0
    t2_pct: float = 0.0
    target_moonshot: Optional[float] = None
    risk_reward: float = 2.5
    no_chase_limit: Optional[str] = None
    rvol: float = 1.5
    oi_regime: str = "LONG_BUILDUP"
    strategic_score: int = 80
    tactical_score: int = 80
    catalysts: list[str] = field(default_factory=list)
    timeline: str = "3–10 Trading Days"
    quick_command: Optional[str] = None
    environment: str = "LIVE"
    in_market: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any], in_market: bool = True) -> EquityAlertData:
        symbol = d.get("symbol", "UNKNOWN")
        ltp = float(d.get("ltp", 0.0))
        entry = float(d.get("entry_price", d.get("entry", ltp)))
        sl = float(d.get("stop_loss", ltp * 0.97))
        t1 = float(d.get("target_1", d.get("target", ltp * 1.05)))
        t2 = float(d.get("target_2", ltp * 1.08))
        rr = float(d.get("risk_reward_ratio", d.get("risk_reward", 2.0)))

        risk_pct = abs((entry - sl) / entry * 100) if entry else 0.0
        t1_pct = abs((t1 - entry) / entry * 100) if entry else 0.0
        t2_pct = abs((t2 - entry) / entry * 100) if entry else 0.0

        entry_range = d.get("entry_range") or f"₹{entry:,.2f}"

        no_chase = d.get("no_chase_limit") or d.get("no_chase")
        if not no_chase:
            when_wait = d.get("when_to_wait", "")
            match = re.search(r"₹([\d,]+(?:\.\d+)?)", when_wait)
            if match:
                no_chase = f"₹{match.group(1)}"
            elif entry > 0:
                no_chase = f"₹{entry * 1.018:,.2f}"

        catalysts = d.get("catalysts", [])
        if not catalysts and d.get("catalyst_summary"):
            catalysts = [c.strip() for c in d.get("catalyst_summary", "").split("·") if c.strip()]

        quick_cmd = d.get("quick_command") or f"/size {symbol} {entry:.2f} {sl:.2f}"

        strat_score = int(d.get("strategic_score", d.get("conviction_score", 80)))
        tact_score = int(d.get("tactical_score", strat_score))

        return cls(
            symbol=symbol,
            sector=d.get("sector", "General"),
            sector_icon=d.get("sector_icon", "🏢"),
            ltp=ltp,
            status=d.get("execution_status", d.get("stage", "READY")),
            setup_title=d.get("setup_title", d.get("headline", "Institutional Setup")),
            action=d.get("action", "BUY"),
            entry_range=entry_range,
            stop_loss=sl,
            risk_pct=risk_pct,
            target_1=t1,
            t1_pct=t1_pct,
            target_2=t2,
            t2_pct=t2_pct,
            target_moonshot=d.get("moonshot_target") or d.get("target_moonshot"),
            risk_reward=rr,
            no_chase_limit=no_chase,
            rvol=float(d.get("rvol", d.get("rvol_20d", 1.5))),
            oi_regime=d.get("options_oi_regime", "LONG_BUILDUP"),
            strategic_score=strat_score,
            tactical_score=tact_score,
            catalysts=catalysts,
            timeline=d.get("expected_timeline", "3–10 Trading Days"),
            quick_command=quick_cmd,
            environment=d.get("environment", "LIVE"),
            in_market=in_market,
        )


@dataclass
class MilestoneAlertData:
    """Data container for milestone events: Target Hit, Trailing Stop Ratchet, Invalidation."""

    milestone_type: str  # "TARGET_1" | "FINAL_TARGET" | "TRAIL_RATCHET" | "INVALIDATED"
    symbol: str
    alert_type: str = "SETUP"
    ltp: float = 0.0
    target_level: Optional[float] = None
    trailing_stop: Optional[float] = None
    locked_profit_pts: Optional[float] = None
    locked_profit_pct: Optional[float] = None
    decisive_action: str = ""
    rationale: Optional[str] = None
    invalidation_reason: Optional[str] = None
    should_trail: bool = True
    environment: str = "LIVE"
    in_market: bool = True
    timestamp: str = ""
    # Traceability & Baseline Context
    signal_id: Optional[str] = None
    contract: Optional[str] = None
    call_time: Optional[str] = None
    entry_price: Optional[float] = None
    entry_range: Optional[str] = None
    initial_sl: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    target_moonshot: Optional[float] = None
    pnl_pts: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    direction: Optional[str] = "BULLISH"
    segment: Optional[str] = None

    @classmethod
    def from_alert(
        cls,
        alert: Any,
        milestone_type: str,
        in_market: bool = True,
        timestamp: str = "",
    ) -> MilestoneAlertData:
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        trailing_stop = getattr(alert, "trailing_stop", None)
        target_level = getattr(alert, "target_level", getattr(alert, "target_price", None))
        created_at = getattr(alert, "created_at", "")
        alert_id = getattr(alert, "alert_id", getattr(alert, "id", ""))
        direction = getattr(alert, "direction", "BULLISH") or "BULLISH"
        is_bullish = str(direction).upper() in ("BULLISH", "LONG", "BUY")

        # Contract resolution
        act_plan = getattr(alert, "actionable_plan", {}) or {}
        if not isinstance(act_plan, dict):
            act_plan = {}
        contract = (
            getattr(alert, "contract_symbol", None)
            or getattr(alert, "contract", None)
            or act_plan.get("contract")
        )
        if not contract and getattr(alert, "strike", None) and getattr(alert, "option_type", None):
            contract = f"{getattr(alert, 'symbol', '')} {int(alert.strike)} {alert.option_type}".strip()

        # Signal Reference Tag
        sig_ref = getattr(alert, "signal_ref", None) or build_signal_ref(
            symbol=getattr(alert, "symbol", "STOCK"),
            alert_id=str(alert_id),
            contract=str(contract or ""),
            created_at=str(created_at or ""),
        )

        # Entry Price resolution
        entry_price = getattr(alert, "trigger_level", None)
        entry_range = act_plan.get("entry_range")
        if not entry_price or entry_price == 0.0:
            rec_entry = act_plan.get("recommended_entry")
            if rec_entry:
                m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
                if m:
                    entry_price = float(m.group(0).replace(",", ""))
        if not entry_price or entry_price == 0.0:
            entry_price = getattr(alert, "option_premium", None) or getattr(alert, "threshold", None)

        # Initial Stop Loss resolution
        initial_sl = getattr(alert, "stop_loss", None)
        if not initial_sl or initial_sl == 0.0:
            act_sl = act_plan.get("stop_loss")
            if act_sl:
                m = re.search(r"[\d,]+(?:\.\d+)?", str(act_sl))
                if m:
                    initial_sl = float(m.group(0).replace(",", ""))

        # Targets resolution (T1, T2, Moonshot)
        t1_val = None
        t2_val = None
        moon_val = None

        if "target_1" in act_plan:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(act_plan["target_1"]))
            if m:
                t1_val = float(m.group(0).replace(",", ""))
        elif "target" in act_plan:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(act_plan["target"]))
            if m:
                t1_val = float(m.group(0).replace(",", ""))

        if "target_2" in act_plan:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(act_plan["target_2"]))
            if m:
                t2_val = float(m.group(0).replace(",", ""))

        if "target_moonshot" in act_plan:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(act_plan["target_moonshot"]))
            if m:
                moon_val = float(m.group(0).replace(",", ""))

        tp_obj = act_plan.get("trade_plan")
        if tp_obj:
            if isinstance(tp_obj, dict):
                t1_val = t1_val or tp_obj.get("target_1")
                t2_val = t2_val or tp_obj.get("target_2")
                moon_val = moon_val or tp_obj.get("target_moonshot")
            else:
                t1_val = t1_val or getattr(tp_obj, "target_1", None)
                t2_val = t2_val or getattr(tp_obj, "target_2", None)
                moon_val = moon_val or getattr(tp_obj, "target_moonshot", None)

        raw_target_level = getattr(alert, "target_level", getattr(alert, "target_price", None))
        if not t2_val and raw_target_level:
            if t1_val and raw_target_level > t1_val:
                t2_val = raw_target_level
            elif not t1_val:
                if milestone_type == "TARGET_1":
                    if entry_price and abs(raw_target_level - entry_price) > abs(ltp - entry_price) * 1.3:
                        t1_val = ltp
                        t2_val = raw_target_level
                    else:
                        t1_val = raw_target_level
                else:
                    t2_val = raw_target_level

        if not t1_val and milestone_type == "TARGET_1":
            t1_val = ltp

        # Performance & Gain calculation
        pnl_pts = getattr(alert, "locked_profit_pts", None)
        pnl_pct = getattr(alert, "locked_profit_pct", None)
        r_multiple = getattr(alert, "r_multiple", None)

        if pnl_pts is None and entry_price and entry_price > 0 and ltp and ltp > 0:
            pnl_pts = round(ltp - entry_price, 2) if is_bullish else round(entry_price - ltp, 2)
            pnl_pct = round((pnl_pts / entry_price) * 100.0, 1)

        if r_multiple is None and pnl_pts is not None and entry_price and initial_sl:
            init_risk = abs(entry_price - initial_sl)
            if init_risk > 0:
                r_multiple = round(pnl_pts / init_risk, 1)

        if milestone_type == "TARGET_1":
            default_action = "BOOK 50% PROFIT NOW & HOLD RUNNER"
            ts_val = trailing_stop or getattr(alert, "stop_loss", None) or (ltp * 0.998)
            trailing_stop = ts_val
        elif milestone_type == "FINAL_TARGET":
            should_trail = getattr(alert, "should_trail", False)
            default_action = (
                "LET RUNNER RIDE (TRAIL SL)"
                if should_trail
                else "CLOSE ALL POSITIONS (BOOK FULL PROFIT)"
            )
        elif milestone_type == "TRAIL_RATCHET":
            default_action = f"UPDATE SL ORDER TO ₹{trailing_stop or 0:,.2f}"
        else:  # INVALIDATED
            default_action = "CANCEL PENDING ORDERS & CLOSE POSITIONS"

        return cls(
            milestone_type=milestone_type,
            symbol=getattr(alert, "symbol", "UNKNOWN"),
            alert_type=getattr(alert, "alert_type", "SETUP").replace("_", " "),
            ltp=ltp,
            target_level=target_level,
            trailing_stop=trailing_stop,
            locked_profit_pts=getattr(alert, "locked_profit_pts", None),
            locked_profit_pct=getattr(alert, "locked_profit_pct", None),
            decisive_action=getattr(alert, "trailing_decision", None) or default_action,
            rationale=getattr(alert, "trailing_rationale", None) or getattr(alert, "summary", ""),
            invalidation_reason=getattr(alert, "invalidation_reason", None)
            or getattr(alert, "summary", ""),
            should_trail=getattr(alert, "should_trail", True),
            environment=getattr(alert, "environment", "LIVE"),
            in_market=in_market,
            timestamp=timestamp or getattr(alert, "created_at", ""),
            signal_id=sig_ref,
            contract=contract,
            call_time=created_at,
            entry_price=entry_price,
            entry_range=entry_range,
            initial_sl=initial_sl,
            target_1=t1_val,
            target_2=t2_val,
            target_moonshot=moon_val,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            r_multiple=r_multiple,
            direction=direction,
            segment=getattr(alert, "segment", None),
        )


# ── Renderers: Standardized Institutional Telegram Cards ─────────────────────


def render_fno_alert(
    data: FNOAlertData | dict[str, Any],
    underlying: str = "NIFTY",
    spot: float = 0.0,
    conviction_score: Optional[dict[str, Any]] = None,
    in_market: bool = True,
) -> str:
    """
    Renders a high-density, institutional-grade F&O Gamma Blast / Options Squeeze alert.
    Fits in a single mobile screen (10–12 lines) with zero duplication.
    """
    if isinstance(data, dict):
        d = FNOAlertData.from_dict(
            data,
            underlying=underlying,
            spot=spot,
            conviction_score=conviction_score,
            in_market=in_market,
        )
    else:
        d = data

    env_tag = normalize_env_tag(d.environment, d.in_market)
    is_call = d.option_type == "CE" or "CE" in d.contract
    icon = "🔥" if is_call else "🚨"

    action_label = d.action_title or f"BUY {d.contract}"
    be_price = d.premium * 1.002 if d.premium else 0.0
    be_str = f" (Cost: ₹{be_price:,.2f})" if be_price else ""

    # Expiry contract & cycle resolution
    exp_badge = d.expiry_badge
    if not exp_badge:
        exp_info = resolve_expiry_cycle(
            contract=d.contract,
            expiry_date=d.expiry_date,
            expiry_type=d.expiry_type,
            dte=d.dte,
            underlying=d.underlying,
        )
        exp_badge = exp_info.get("badge", "")
    exp_line = f"⏳ <b>Expiry:</b> {exp_badge}\n" if exp_badge else ""

    # Conviction line
    conv_badge = ""
    if d.conviction_score and isinstance(d.conviction_score, dict):
        cs_total = d.conviction_score.get("total_score", d.score)
        cs_verdict = d.conviction_score.get("verdict", "HIGH")
        cs_pos = d.conviction_score.get("recommended_position_size", "")
        pos_str = f" · ⚡ {cs_pos} Size" if cs_pos else ""
        conv_badge = f"\n🧠 <b>Conviction:</b> <b>{cs_total}/100</b> ({cs_verdict}){pos_str}"
    else:
        conv_badge = f"\n🧠 <b>Score:</b> <b>{d.score}/100</b>"

    no_chase_str = (
        f" · 🚫 <b>DO NOT CHASE:</b> Above <code>{d.no_chase_limit}</code>" if d.no_chase_limit else ""
    )
    spot_str = f" · Spot: <b>₹{d.spot:,.2f}</b>" if d.spot else ""
    sig_ref = build_signal_ref(symbol=d.underlying or d.contract, contract=d.contract)

    msg = (
        f"{icon} <b>{env_tag} GAMMA BLAST SURGE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{d.contract}</b>{spot_str} · <code>{sig_ref}</code>\n"
        f"{exp_line}"
        f"🎯 <b>Action:</b> <b>{action_label}</b>\n"
        f"• <b>Entry Zone:</b> <code>{d.entry_range}</code>\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> ({d.stop_loss_pct})\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{d.target_1:,.2f}</code> ({d.target_1_pct}) — <i>Scale 50% & SL to Cost{be_str}</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{d.target_2:,.2f}</code> ({d.target_2_pct}) — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{d.risk_reward} R:R</b>{no_chase_str}\n"
        f"💡 <b>Reason:</b> {d.trigger_reason} · {d.vol_oi:.1f}x Vol/OI (Imbalance: {d.imbalance:.1f}x)\n"
        f"📋 <b>Playbook:</b> <i>{d.profit_rule}</i>"
        f"{conv_badge}"
    )
    return msg


def render_equity_alert(data: EquityAlertData | dict[str, Any], in_market: bool = True) -> str:
    """
    Renders an institutional-grade Equity execution readiness / breakout alert.
    Crisp, articulated, decisive with 1-click sizing command.
    """
    if isinstance(data, dict):
        d = EquityAlertData.from_dict(data, in_market=in_market)
    else:
        d = data

    env_tag = normalize_env_tag(d.environment, d.in_market)
    status_badge = (
        f"🚀 <b>{env_tag} READY TO EXECUTE</b>" if d.status == "READY" else f"🎯 <b>{env_tag} STALK ON RETEST</b>"
    )

    t2_str = (
        f"\n• <b>Target 2 (3.5R):</b> <code>₹{d.target_2:,.2f}</code> (+{d.t2_pct:.1f}%) — <i>Trail 20-EMA</i>"
        if d.target_2
        else ""
    )
    moon_str = (
        f"\n• <b>Moonshot (+6R+):</b> <code>₹{d.target_moonshot:,.2f}</code> — <i>Runner</i>"
        if d.target_moonshot
        else ""
    )

    no_chase_str = (
        f"\n🚫 <b>DO NOT CHASE:</b> Above <code>{d.no_chase_limit}</code>" if d.no_chase_limit else ""
    )
    cat_str = " · ".join(d.catalysts[:2]) if d.catalysts else "Confirmed Institutional Structure"

    sig_ref = build_signal_ref(symbol=d.symbol)
    msg = (
        f"{status_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{d.symbol}</b> ({d.sector_icon} {d.sector}) · <b>₹{d.ltp:,.2f}</b> · <code>{sig_ref}</code>\n"
        f"<i>{d.setup_title}</i>\n"
        f"🎯 <b>Action:</b> <b>{d.action}</b> @ <code>{d.entry_range}</code>\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> (-{d.risk_pct:.1f}%)\n"
        f"• <b>Target 1 (2R):</b> <code>₹{d.target_1:,.2f}</code> (+{d.t1_pct:.1f}%) — <i>Scale 50% & SL to Breakeven</i>"
        f"{t2_str}{moon_str}\n"
        f"• <b>Risk : Reward:</b> <b>1:{d.risk_reward:.1f} R:R</b>{no_chase_str}\n"
        f"📊 <b>Scores:</b> Strategic: <b>{d.strategic_score}/100</b> | Live Tactical: <b>{d.tactical_score}/100</b> · RVOL: <b>{d.rvol:.1f}x</b>\n"
        f"💡 <b>Reason:</b> {cat_str}\n"
        f"⚡ <b>Quick Size:</b> <code>{d.quick_command}</code>"
    )
    return msg


def render_precursor_alert(data: dict[str, Any], in_market: bool = True) -> str:
    """
    Renders a Precursor Radar alert (coiling, volume dry-up, squeeze before ignition).
    Guarantees <12 lines, decisive execution boundaries, and zero conversational filler.
    """
    sym = data.get("symbol", "STOCK")
    seg = data.get("segment", "FNO")
    score = data.get("conviction_score", 80)
    verdict = data.get("verdict", "HIGH_CONVICTION")
    ltp = float(data.get("ltp", 0.0))
    entry_range = data.get("entry_range", f"₹{ltp:,.1f}")
    sl = float(data.get("stop_loss", 0.0))
    t1 = float(data.get("target_1", 0.0))
    t2 = float(data.get("target_2", 0.0))
    rr = data.get("risk_reward", "1:2.5")

    icon = "🔥" if score >= 85 else "⚡"

    raw_factors = data.get(
        "matched_factors", ["Pre-ignition volume dry-up & squeeze coiling"]
    )
    factors_str = " · ".join(raw_factors[:3]) if raw_factors else "Pre-ignition coiling setup"

    when_wait = data.get("when_to_wait", "")
    no_chase_match = re.search(r"₹([\d,]+(?:\.\d+)?)", when_wait)
    no_chase = (
        f"Above <code>₹{no_chase_match.group(1)}</code>"
        if no_chase_match
        else "DO NOT CHASE if gaps > 1.8%"
    )

    env_tag = normalize_env_tag(data.get("environment", "LIVE"), in_market)
    if not in_market:
        header_line = f"🌙 <b>{env_tag} POST-MARKET EOD WATCHLIST [{seg}]</b>"
        off_note = "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
    else:
        header_line = f"{icon} <b>{env_tag} PRECURSOR RADAR [{seg}]</b>"
        off_note = ""

    sig_ref = build_signal_ref(symbol=sym)
    msg = (
        f"{header_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · <code>{sig_ref}</code> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
        f"🎯 <b>Action: BUY</b> @ <code>{entry_range}</code> (Ref: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code>\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 50% & SL to Cost</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{t2:,.2f}</code> — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{rr}</b>\n"
        f"🚫 <b>{no_chase}</b>\n"
        f"💡 <b>Reason:</b> {factors_str}"
        f"{off_note}"
    )
    return msg


def render_asymmetric_alert(data: dict[str, Any], in_market: bool = True) -> str:
    """
    Renders an Asymmetric Opportunity alert (1:3+ R:R setups with moonshot extension).
    """
    sym = data.get("symbol", "STOCK")
    seg = data.get("segment", "FNO")
    score = data.get("conviction_score", 85)
    verdict = data.get("verdict", "HIGH_CONVICTION")
    ltp = float(data.get("ltp", 0.0))
    entry_range = data.get("entry_range", f"₹{ltp:,.1f}")
    sl = float(data.get("stop_loss", 0.0))
    t1 = float(data.get("target_1", 0.0))
    t2 = float(data.get("target_2", 0.0))
    moonshot = float(data.get("moonshot_target", data.get("target_moonshot", 0.0)))
    rr = data.get("risk_reward_ratio", data.get("risk_reward", 3.0))

    env_tag = normalize_env_tag(data.get("environment", "LIVE"), in_market)
    confluences = data.get("confluences", data.get("metrics", {}).get("confluence_factors", []))
    conf_str = " · ".join(confluences[:3]) if confluences else "High asymmetric structural edge"

    moon_line = (
        f"\n• <b>Moonshot (+6R+):</b> <code>₹{moonshot:,.2f}</code> — <i>Runner Extension</i>"
        if moonshot
        else ""
    )

    if not in_market:
        header_line = f"🌙 <b>{env_tag} POST-MARKET EOD WATCHLIST [1:{rr} R:R]</b>"
        off_note = "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
    else:
        header_line = f"🎯 <b>{env_tag} ASYMMETRIC SETUP [1:{rr} R:R]</b>"
        off_note = ""

    sig_ref = build_signal_ref(symbol=sym)
    msg = (
        f"{header_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · <code>{sig_ref}</code> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
        f"🎯 <b>Action: BUY</b> @ <code>{entry_range}</code> (Ref: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code> (Risk: ₹{abs(ltp - sl):,.2f})\n"
        f"• <b>Target 1 (+2R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 40% & SL to Cost</i>\n"
        f"• <b>Target 2 (+4R):</b> <code>₹{t2:,.2f}</code> — <i>Scale 40% & Trail</i>{moon_line}\n"
        f"• <b>Risk : Reward:</b> <b>1:{rr} R:R</b>\n"
        f"💡 <b>Reason:</b> {conf_str}"
        f"{off_note}"
    )
    return msg


def render_milestone_alert(data: MilestoneAlertData | dict[str, Any], in_market: bool = True) -> str:
    """
    Renders a crisp lifecycle milestone alert: Target 1 Hit, Final Target, Trailing Ratchet, Invalidation.
    Instant clarity on which signal this update applies to, when the call was given, baseline setup levels,
    current performance gain, trailing stop, and decisive action required now.
    """
    if isinstance(data, dict):
        d = MilestoneAlertData(
            milestone_type=data.get("milestone_type", "TARGET_1"),
            symbol=data.get("symbol", "UNKNOWN"),
            alert_type=data.get("alert_type", "SETUP").replace("_", " "),
            ltp=float(data.get("ltp", 0.0)),
            target_level=data.get("target_level"),
            trailing_stop=data.get("trailing_stop"),
            locked_profit_pts=data.get("locked_profit_pts"),
            locked_profit_pct=data.get("locked_profit_pct"),
            decisive_action=data.get("decisive_action", ""),
            rationale=data.get("rationale") or data.get("trailing_rationale"),
            invalidation_reason=data.get("invalidation_reason"),
            should_trail=data.get("should_trail", True),
            environment=data.get("environment", "LIVE"),
            in_market=in_market,
            timestamp=data.get("timestamp", ""),
            signal_id=data.get("signal_id"),
            contract=data.get("contract") or data.get("contract_symbol"),
            call_time=data.get("call_time") or data.get("created_at"),
            entry_price=data.get("entry_price"),
            entry_range=data.get("entry_range"),
            initial_sl=data.get("initial_sl") or data.get("stop_loss"),
            target_1=data.get("target_1"),
            target_2=data.get("target_2"),
            target_moonshot=data.get("target_moonshot"),
            pnl_pts=data.get("pnl_pts"),
            pnl_pct=data.get("pnl_pct"),
            r_multiple=data.get("r_multiple"),
            direction=data.get("direction", "BULLISH"),
            segment=data.get("segment"),
        )
    else:
        d = data

    env_tag = normalize_env_tag(d.environment, d.in_market)
    contract_title = d.contract or d.symbol
    if d.symbol and d.symbol not in contract_title:
        contract_title = f"{d.symbol} {contract_title}"

    call_time_fmt, elapsed_fmt = _format_call_time_and_elapsed(d.call_time, d.timestamp)
    call_time_part = f" · 📞 <b>Call Given:</b> {call_time_fmt}{elapsed_fmt}" if call_time_fmt else ""
    ref_line = (
        f"🏷️ <b>Ref:</b> <code>{d.signal_id}</code>{call_time_part}\n"
        if d.signal_id
        else (f"📞 <b>Call Given:</b> {call_time_fmt}{elapsed_fmt}\n" if call_time_fmt else "")
    )

    update_ts = d.timestamp or datetime.now(IST).strftime("%H:%M:%S IST")

    if d.milestone_type == "INVALIDATED":
        plan_parts = []
        if d.entry_price:
            plan_parts.append(f"Entry: ₹{d.entry_price:,.2f}")
        elif d.entry_range:
            plan_parts.append(f"Entry: {d.entry_range}")
        if d.initial_sl:
            plan_parts.append(f"SL: ₹{d.initial_sl:,.2f}")
        orig_plan_line = f"🎯 <b>Original Plan:</b> {' | '.join(plan_parts)}\n" if plan_parts else ""

        return (
            f"⚠️ <b>{env_tag} VIEW INVALIDATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{contract_title} ({d.alert_type})</b> is <b>NO LONGER VALID</b>!\n"
            f"{ref_line}"
            f"{orig_plan_line}"
            f"🛑 <b>Reason:</b> {d.invalidation_reason or d.rationale or 'Stop-loss or invalidation floor breached'}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CANCEL PENDING ORDERS & CLOSE POSITIONS</code>"
        )

    if d.milestone_type == "TARGET_1":
        ts_val = d.trailing_stop or (d.ltp * 0.998)
        lock_pct = f" (+{d.locked_profit_pct:.1f}% Breakeven Lock)" if d.locked_profit_pct else ""

        plan_parts = []
        if d.entry_price:
            plan_parts.append(f"Entry: ₹{d.entry_price:,.2f}")
        elif d.entry_range:
            plan_parts.append(f"Entry: {d.entry_range}")
        if d.initial_sl:
            plan_parts.append(f"SL: ₹{d.initial_sl:,.2f}")
        t1_disp = d.target_1 or d.target_level or d.ltp
        if t1_disp:
            plan_parts.append(f"T1: ₹{t1_disp:,.2f}")
        if d.target_2:
            plan_parts.append(f"T2: ₹{d.target_2:,.2f}")
        orig_plan_line = f"🎯 <b>Original Plan:</b> {' | '.join(plan_parts)}\n" if plan_parts else ""

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"

        t2_runner_note = f" (Target 2: ₹{d.target_2:,.2f})" if d.target_2 else ""

        return (
            f"🎯 <b>{env_tag} TARGET 1 HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{contract_title} ({d.alert_type}) — TARGET 1 ACHIEVED</b>\n"
            f"{ref_line}"
            f"{orig_plan_line}"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Target 1:</b> ₹{t1_disp:,.2f}{move_str}\n"
            f"🛡️ <b>Trail Stop:</b> <code>₹{ts_val:,.2f}</code>{lock_pct} (100% risk-free)\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>BOOK 50% PROFIT NOW & HOLD RUNNER{t2_runner_note}</code>"
        )

    if d.milestone_type == "FINAL_TARGET":
        tgt_val = d.target_2 or d.target_level or d.ltp
        plan_parts = []
        if d.entry_price:
            plan_parts.append(f"Entry: ₹{d.entry_price:,.2f}")
        if d.initial_sl:
            plan_parts.append(f"SL: ₹{d.initial_sl:,.2f}")
        if tgt_val:
            plan_parts.append(f"Target: ₹{tgt_val:,.2f}")
        orig_plan_line = f"🎯 <b>Original Plan:</b> {' | '.join(plan_parts)}\n" if plan_parts else ""

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"

        if d.should_trail:
            ts_val = d.trailing_stop or d.ltp
            lock_str = (
                f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct is not None else ""
            )
            return (
                f"🚀 <b>{env_tag} RUNNER EXTENSION</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 <b>{contract_title} ({d.alert_type}) — INSTITUTIONAL RUNAWAY</b>\n"
                f"{ref_line}"
                f"{orig_plan_line}"
                f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Primary Target:</b> ₹{tgt_val:,.2f}{move_str}\n"
                f"🛡️ <b>Chandelier Trail SL:</b> <code>₹{ts_val:,.2f}</code>{lock_str}\n"
                f"⚡ <b>DECISIVE ACTION:</b> <code>LET RUNNER RIDE (TRAIL SL)</code>"
            )
        return (
            f"🏁 <b>{env_tag} FINAL TARGET ACHIEVED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{contract_title} ({d.alert_type}) — FINAL TARGET REACHED</b>\n"
            f"{ref_line}"
            f"{orig_plan_line}"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Final Target:</b> ₹{tgt_val:,.2f}{move_str}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CLOSE ALL POSITIONS (BOOK FULL PROFIT)</code>"
        )

    if d.milestone_type == "TRAIL_RATCHET":
        plan_parts = []
        if d.entry_price:
            plan_parts.append(f"Entry: ₹{d.entry_price:,.2f}")
        if d.initial_sl:
            plan_parts.append(f"Initial SL: ₹{d.initial_sl:,.2f}")
        orig_plan_line = f"🎯 <b>Original Plan:</b> {' | '.join(plan_parts)}\n" if plan_parts else ""

        lock_pts = f"+₹{d.locked_profit_pts:,.2f}/sh" if d.locked_profit_pts else ""
        lock_pct = f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct else ""
        lock_str = f"🔒 <b>Guaranteed Profit:</b> {lock_pts}{lock_pct}\n" if (lock_pts or lock_pct) else ""

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            move_str = f" · 📈 <b>Move:</b> {sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%)"

        return (
            f"📈 <b>{env_tag} TRAILING STOP RATCHET</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>{contract_title} Trailing Stop Ratcheted Higher!</b>\n"
            f"{ref_line}"
            f"{orig_plan_line}"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} · <b>New SL:</b> <code>₹{d.trailing_stop or 0:,.2f}</code>{move_str}\n"
            f"{lock_str}"
            f"⚡ <b>DECISIVE ACTION:</b> <code>UPDATE SL ORDER TO ₹{d.trailing_stop or 0:,.2f}</code>"
        )

    # Fallback
    return f"🔔 <b>{env_tag} {d.symbol}</b>: Milestone reached · LTP: ₹{d.ltp:,.2f}"


def render_price_alert(
    symbol: str,
    condition_desc: str,
    ltp: Optional[float] = None,
    environment: str = "LIVE",
    in_market: bool = True,
) -> str:
    """Renders a simple user-configured price or technical indicator alert."""
    env_tag = normalize_env_tag(environment, in_market)
    ltp_str = f" · LTP: <b>₹{ltp:,.2f}</b>" if ltp is not None else ""
    return (
        f"🟢 <b>{env_tag} ALERT TRIGGERED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 <b>{symbol}</b>: {condition_desc}{ltp_str}"
    )


def render_auto_alert(alert: Any, in_market: bool = True) -> str:
    """
    Renders an AutoAlert instance into a crisp, standardized Telegram message.
    Handles Invalidation, Target 1, Final Target, Trail Ratchet, Precursor, Asymmetric,
    Options contracts (GAMMA_BLAST), and Equity trade plans.
    """
    is_test = (getattr(alert, "environment", "LIVE") == "TEST") or (
        not getattr(alert, "is_live", True)
    )
    env_tag = normalize_env_tag(getattr(alert, "environment", "LIVE"), in_market)

    # 1. Invalidation
    if getattr(alert, "is_invalidated", False) or getattr(alert, "stage", "") == "INVALIDATED":
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "INVALIDATED", in_market=in_market),
            in_market=in_market,
        )

    # 2. Target 1
    is_t1 = "T1" in (getattr(alert, "target_status", "") or "") or getattr(
        alert, "stage", ""
    ) == "T1_ACHIEVED"
    if is_t1:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TARGET_1", in_market=in_market),
            in_market=in_market,
        )

    # 3. Final Target / Runner Extension
    is_target = (
        getattr(alert, "stage", "") in ("TARGET_ACHIEVED", "COMPLETED")
        or "TARGET" in (getattr(alert, "target_status", "") or "")
    )
    if is_target:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "FINAL_TARGET", in_market=in_market),
            in_market=in_market,
        )

    # 4. Trailing Stop Ratchet
    if getattr(alert, "stage", "") == "TRAILING_UPDATE":
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TRAIL_RATCHET", in_market=in_market),
            in_market=in_market,
        )

    # 5. Precursor Radar
    if getattr(alert, "alert_type", "") == "PRECURSOR_RADAR":
        d = alert.to_dict() if hasattr(alert, "to_dict") else vars(alert)
        return render_precursor_alert(d, in_market=in_market)

    # 6. Asymmetric Opportunity
    if getattr(alert, "alert_type", "") == "ASYMMETRIC_OPPORTUNITY":
        d = alert.to_dict() if hasattr(alert, "to_dict") else vars(alert)
        return render_asymmetric_alert(d, in_market=in_market)

    # 7. Options Contract (e.g. GAMMA_BLAST) or Equity/Commodity/Currency Trade Plan
    if is_test:
        tg_header = f"🧪 <b>{env_tag} TEST SETUP</b>"
    elif not in_market:
        tg_header = f"🌙 <b>{env_tag} EOD WATCHLIST</b>"
    else:
        if getattr(alert, "exchange", "") == "MCX" or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM":
            tg_header = f"🛢️ <b>{env_tag} MCX MOMENTUM</b>"
        elif getattr(alert, "exchange", "") == "CDS" or getattr(alert, "alert_type", "") == "CURRENCY_BREAKOUT":
            tg_header = f"💱 <b>{env_tag} CURRENCY BREAKOUT</b>"
        elif getattr(alert, "stage", "") == "EARLY_WARNING" or getattr(alert, "alert_type", "") in (
            "PATTERN_COILING",
            "CIRCUIT_WARNING",
        ):
            tg_header = f"⚡ <b>{env_tag} EARLY WARNING (COILING)</b>"
        elif getattr(alert, "alert_type", "") == "SQUEEZE_BREAKOUT" and getattr(
            alert, "stage", ""
        ) != "IGNITED":
            tg_header = f"⚡ <b>{env_tag} SQUEEZE COILING</b>"
        elif (
            getattr(alert, "alert_type", "") in ("GAMMA_BLAST", "OPTIONS_MOMENTUM")
            or getattr(alert, "option_type", None)
        ):
            tg_header = f"🟢 <b>{env_tag} OPTIONS BREAKOUT</b>"
        else:
            tg_header = f"🟢 <b>{env_tag} BREAKOUT IGNITED</b>"

    off_note = (
        "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
        if not in_market and not is_test
        else ""
    )

    actionable_plan = getattr(alert, "actionable_plan", {}) or {}
    plan_str = ""

    # Options Contract Plan
    if (
        getattr(alert, "option_type", None) or getattr(alert, "alert_type", "") == "GAMMA_BLAST"
    ) and actionable_plan:
        act = actionable_plan.get("action", "BUY")
        inst = (
            getattr(alert, "contract_symbol", None)
            or f"{alert.symbol} {int(getattr(alert, 'strike', 0) or 0)} {getattr(alert, 'option_type', '')}".strip()
        )
        entry = actionable_plan.get("recommended_entry") or f"₹{alert.ltp:.1f}"
        tgt = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0):.1f}")
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):.1f}")
        rr = actionable_plan.get("risk_reward", "1:3.0")
        spot_ref = (
            f" (Spot: ₹{alert.underlying_spot:,.1f})"
            if getattr(alert, "underlying_spot", None)
            else ""
        )
        exp_date = (
            getattr(alert, "expiry_date", None)
            or actionable_plan.get("expiry")
            or getattr(alert, "expiry", None)
        )
        exp_type = getattr(alert, "expiry_type", None) or actionable_plan.get("expiry_type")
        dte = getattr(alert, "dte", None) or actionable_plan.get("dte")
        exp_info = resolve_expiry_cycle(
            contract=inst,
            expiry_date=exp_date,
            expiry_type=exp_type,
            dte=dte,
            underlying=getattr(alert, "symbol", "NIFTY"),
        )
        exp_line = f"• <b>Expiry:</b> ⏳ {exp_info['badge']}\n" if exp_info.get("badge") else ""

        plan_str = (
            f"{exp_line}"
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>{spot_ref}\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
            f"• <b>Target:</b> <code>{tgt}</code>\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b>"
        )
    elif getattr(alert, "exchange", "") == "MCX" or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM":
        act = actionable_plan.get("action", "BUY_FUTURES")
        inst = actionable_plan.get("contract", f"MCX:{alert.symbol}")
        entry = actionable_plan.get("entry_range", f"₹{alert.ltp:,.1f}")
        tgt1 = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0):,.1f}")
        tgt2 = actionable_plan.get("target_2", "")
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):,.1f}")
        rr = actionable_plan.get("risk_reward", "1:2.4")
        lot = actionable_plan.get("lot_size", "")
        lot_str = f" | Lot: {lot}" if lot else ""
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Book 50% at T1, trail stop to cost.")

        opt_alt = actionable_plan.get("option_alternative")
        opt_str = ""
        if opt_alt and isinstance(opt_alt, dict):
            opt_str = (
                f"\n🎯 <b>Option Alternative:</b> BUY {opt_alt.get('contract', '')} @ ₹{opt_alt.get('ltp', 0):,.1f} "
                f"(SL: ₹{opt_alt.get('stop_loss', 0):,.1f} | Tgt: ₹{opt_alt.get('target_1', 0):,.1f})"
            )

        plan_str = (
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
            f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b>{lot_str}\n"
            f"• <b>Playbook:</b> <i>{rule}</i>"
            f"{opt_str}"
        )
    elif getattr(alert, "exchange", "") == "CDS" or getattr(alert, "alert_type", "") == "CURRENCY_BREAKOUT":
        act = actionable_plan.get("action", "BUY_FUTURES")
        inst = actionable_plan.get("contract", f"CDS:{alert.symbol}")
        entry = actionable_plan.get("entry_range", f"₹{alert.ltp:.4f}")
        tgt1 = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0):.4f}")
        tgt2 = actionable_plan.get("target_2", "")
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):.4f}")
        rr = actionable_plan.get("risk_reward", "1:2.2")
        lot = actionable_plan.get("lot_size", 1000)
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Scale 50% at T1, move SL to entry.")
        plan_str = (
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
            f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b> | Lot: {lot}\n"
            f"• <b>Playbook:</b> <i>{rule}</i>"
        )
    else:
        # Equity / Index Trade Plan
        try:
            from engine.trade_plan import TradePlan, calculate_trade_plan

            tp = None
            stored_tp = actionable_plan.get("trade_plan") if actionable_plan else None
            if stored_tp and isinstance(stored_tp, dict):
                try:
                    tp = TradePlan(**stored_tp)
                except Exception:
                    tp = None

            if not tp:
                clean_spot = (
                    alert.underlying_spot
                    if getattr(alert, "underlying_spot", None) and alert.underlying_spot > 0
                    else alert.ltp
                )
                tp = calculate_trade_plan(
                    alert.symbol,
                    direction=getattr(alert, "direction", "BULLISH"),
                    spot=clean_spot,
                    exchange=getattr(alert, "exchange", "NSE"),
                    has_active_blast=(getattr(alert, "alert_type", "") == "GAMMA_BLAST"),
                )

            if tp and tp.invalidation_stop > 0:
                asym_icon = "✅" if tp.is_asymmetry_viable else "⚠️"
                action = "BUY" if tp.direction == "LONG" else "SELL"
                sl_diff_sign = "-" if tp.direction == "LONG" else "+"
                t_diff_sign = "+" if tp.direction == "LONG" else "-"
                overrun_warn = (
                    f" (⚠️ <i>{tp.session_clock_note}</i>)" if tp.session_overrun_risk else ""
                )

                plan_str = (
                    f"• <b>Action:</b> {action} @ <code>₹{tp.entry_price:,.1f}</code>\n"
                    f"• <b>Invalidation SL:</b> <code>₹{tp.invalidation_stop:,.1f}</code> ({sl_diff_sign}{tp.stop_distance_pts:,.1f} pts)\n"
                    f"• <b>Target 1:</b> <code>₹{tp.target_1:,.1f}</code> ({t_diff_sign}{tp.t1_distance_pts:,.1f} pts | <b>{tp.rr_t1}:1 R:R</b>)\n"
                    f"• <b>Target 2:</b> <code>₹{tp.target_2:,.1f}</code> ({t_diff_sign}{tp.t2_distance_pts:,.1f} pts | <b>{tp.rr_t2}:1 R:R</b>){overrun_warn}\n"
                    f"• <b>Expectancy:</b> {asym_icon} <b>{tp.asymmetry_verdict}</b>"
                )
        except Exception:
            pass

        if not plan_str and actionable_plan:
            action = actionable_plan.get("action", "BUY")
            entry = actionable_plan.get("recommended_entry") or actionable_plan.get(
                "entry_range", f"₹{alert.ltp}"
            )
            target = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0)}")
            sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0)}")
            plan_str = f"• <b>Action:</b> {action} @ <code>{entry}</code>\n• <b>Target:</b> <code>{target}</code> | 🛑 <b>SL:</b> <code>{sl}</code>"

    now_ts_str = getattr(alert, "created_at", "") or datetime.now(IST).strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )

    raw_headline = getattr(alert, "headline", alert.symbol) or alert.symbol
    clean_hl = strip_provenance_and_icons(raw_headline)

    # Clean summary to serve as rationale AFTER the execution levels
    raw_summary = getattr(alert, "summary", "") or ""
    clean_summary = raw_summary
    if plan_str and clean_summary:
        # Strip redundant Entry/SL/Target lists if plan_str already formats them
        clean_summary = re.sub(
            r"\s*(?:Entry|SL|T1|T2|Target)\s*:[^|]+(?:\||$)", "", clean_summary
        ).strip()
        clean_summary = clean_summary.rstrip(" .|")

    reason_line = f"💡 <b>Reason:</b> <i>{clean_summary}</i>" if clean_summary else ""

    # Build clean headline line
    sig_ref = getattr(alert, "signal_ref", None) or build_signal_ref(
        symbol=getattr(alert, "symbol", ""),
        alert_id=str(getattr(alert, "alert_id", getattr(alert, "id", ""))),
        contract=str(getattr(alert, "contract_symbol", "")),
        created_at=now_ts_str,
    )
    hl_line = f"<b>{clean_hl}</b> · <code>{sig_ref}</code>" if clean_hl else f"<b>{alert.symbol}</b> · <code>{sig_ref}</code>"

    lines = [
        tg_header,
        "━━━━━━━━━━━━━━━━━━━━",
        hl_line,
    ]
    if plan_str:
        lines.append(plan_str.strip())
    if reason_line:
        lines.append(reason_line.strip())

    lines.append(
        f"📊 <b>Confidence:</b> {getattr(alert, 'confidence', 80)}% · 🕒 <b>Timestamp:</b> {now_ts_str}{off_note}"
    )

    return "\n".join(lines)
