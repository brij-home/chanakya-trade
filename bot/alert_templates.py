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

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))

INDEX_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 3,  # Thursday
    "BANKNIFTY": 2,  # Wednesday
    "FINNIFTY": 1,  # Tuesday
    "MIDCPNIFTY": 0,  # Monday
    "SENSEX": 4,  # Friday
    "BANKEX": 0,  # Monday
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
                "JAN": 1,
                "FEB": 2,
                "MAR": 3,
                "APR": 4,
                "MAY": 5,
                "JUN": 6,
                "JUL": 7,
                "AUG": 8,
                "SEP": 9,
                "OCT": 10,
                "NOV": 11,
                "DEC": 12,
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
                    "1": 1,
                    "2": 2,
                    "3": 3,
                    "4": 4,
                    "5": 5,
                    "6": 6,
                    "7": 7,
                    "8": 8,
                    "9": 9,
                    "O": 10,
                    "N": 11,
                    "D": 12,
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
                    "JAN": 1,
                    "FEB": 2,
                    "MAR": 3,
                    "APR": 4,
                    "MAY": 5,
                    "JUN": 6,
                    "JUL": 7,
                    "AUG": 8,
                    "SEP": 9,
                    "OCT": 10,
                    "NOV": 11,
                    "DEC": 12,
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
    elif cycle_override in (
        "CURRENT_WEEKLY",
        "NEXT_WEEKLY",
        "CURRENT_MONTHLY",
        "NEXT_MONTHLY",
        "FAR_MONTHLY",
    ):
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

    now_ist = datetime.now(IST).replace(tzinfo=None)
    dt_update = _parse_ts_to_dt(update_time_str) if update_time_str else now_ist
    # If update timestamp is missing or erroneously identical to call time, measure against current IST time
    if not dt_update or dt_update == dt_call:
        dt_update = now_ist

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

    if delta_seconds < 15:
        elapsed_str = " (⏱️ Just now)"
    elif delta_seconds < 60:
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


def get_no_chase_comparator(
    alert: Any,
    actionable_plan: Optional[dict[str, Any]] = None,
    action_str: str = "",
) -> str:
    """
    Returns 'above' or 'below' for the no-chase limit boundary.
    - If buying (Long equity, Long futures, BUY CE, BUY PE, or target > entry): comparator is 'above'
      (trader should not chase if price/premium surges above the ceiling).
    - If selling / shorting (Short equity, Short futures, SELL CE, SELL PE, or target < entry): comparator is 'below'
      (trader should not chase if price drops below the floor).
    """
    plan = (
        actionable_plan
        if actionable_plan is not None
        else getattr(alert, "actionable_plan", {}) or {}
    )
    act = (action_str or plan.get("action") or "").strip().upper()

    # 1. Check explicit action verb
    if act.startswith("BUY") or "LONG" in act:
        return "above"
    if act.startswith("SELL") or "SHORT" in act:
        return "below"

    # 2. Check if option contract is being traded (defaults to long option)
    if getattr(alert, "option_type", None) or getattr(alert, "alert_type", "") in (
        "OPTIONS_MOMENTUM",
        "GAMMA_BLAST",
    ):
        return "above"

    # 3. Check target vs trigger/entry levels
    tgt = getattr(alert, "target_level", 0.0) or 0.0
    trig = getattr(alert, "trigger_level", 0.0) or getattr(alert, "ltp", 0.0) or 0.0
    if tgt > 0 and trig > 0 and tgt != trig:
        return "above" if tgt > trig else "below"

    # 4. Fallback to alert direction
    dir_val = str(getattr(alert, "direction", "BULLISH")).upper()
    return "above" if dir_val in ("BULLISH", "LONG", "BUY") else "below"


def format_contract_display(contract: str) -> str:
    """
    Convert raw broker/exchange contract tokens into clean, human-readable display strings.

    Handles all NSE/BSE/MCX naming conventions:
      - MStock YYYYMMDD:  HAL202609294800PE    → "HAL 4800 PE"
      - NSE Monthly:      HAL26SEP4800PE       → "HAL 4800 PE"
      - NSE Weekly:       NIFTY2692524800CE    → "NIFTY 24800 CE"
      - Compact no-date:  HDFCBANK680CE        → "HDFCBANK 680 CE"
      - Fyers prefixed:   NSE:HAL26SEP4800PE   → "HAL 4800 PE"
      - Already spaced:   NIFTY 24800 CE       → "NIFTY 24800 CE" (passthrough)
      - Futures:          HAL26SEPFUT          → "HAL FUT"

    Rules:
      - Strike is ALWAYS a plain integer with NO comma (4800, not 4,800)
      - Strikes >= 10000 are kept as-is (e.g. 25000, not 25,000)
      - Option type CE/PE is space-separated from strike
      - Expiry date/code is stripped from display (shown separately via expiry badge)
    """
    if not contract:
        return contract

    # Strip exchange prefixes (NSE:, BSE:, NFO:, MCX:, CDS:, BFO:)
    c = re.sub(r"^(?:NSE|BSE|NFO|MCX|CDS|BFO):", "", contract.strip(), flags=re.IGNORECASE)

    # Already well-formatted (has spaces): e.g. "HAL 4800 PE", "NIFTY 25000 CE"
    m_spaced = re.match(r"^([A-Z]+)\s+(\d+)\s*(CE|PE|FUT)$", c.upper().strip())
    if m_spaced:
        sym, strike, opt = m_spaced.groups()
        if opt == "FUT":
            return f"{sym} FUT"
        return f"{sym} {int(strike)} {opt}"

    c_upper = c.upper()

    # Futures: e.g. HAL26SEPFUT, NIFTY26OCTFUT
    m_fut = re.match(r"^([A-Z]+)\d{2}[A-Z]{3}FUT$", c_upper)
    if m_fut:
        return f"{m_fut.group(1)} FUT"

    # MStock / broker YYYYMMDD format: e.g. HAL202609294800PE
    # Must start with "20" (year 20xx) to distinguish from NSE weekly compact codes
    m_yyyymmdd = re.match(r"^([A-Z]+)(20\d{6})(\d+)(CE|PE)$", c_upper)
    if m_yyyymmdd:
        sym, _date, strike_str, opt = m_yyyymmdd.groups()
        return f"{sym} {int(strike_str)} {opt}"

    # NSE Weekly compact: e.g. NIFTY2692524800CE (YY + month-code(1-9/O/N/D) + DD(2) + strike + CE/PE)
    # Try weekly BEFORE monthly — weekly has 5-char date prefix vs monthly's 5-char (2+3) prefix
    m_weekly = re.match(r"^([A-Z]+)\d{2}[1-9OND]\d{2}(\d+)(CE|PE)$", c_upper)
    if m_weekly:
        sym, strike_str, opt = m_weekly.groups()
        return f"{sym} {int(strike_str)} {opt}"

    # NSE Monthly: e.g. HAL26SEP4800PE, RELIANCE26SEP3000CE
    m_monthly = re.match(r"^([A-Z]+)\d{2}[A-Z]{3}(\d+)(CE|PE)$", c_upper)
    if m_monthly:
        sym, strike_str, opt = m_monthly.groups()
        return f"{sym} {int(strike_str)} {opt}"

    # Compact without date: e.g. HDFCBANK680CE, MIDCPNIFTY14250CE
    m_compact = re.match(r"^([A-Z]+?)(\d+)(CE|PE)$", c_upper)
    if m_compact:
        sym, strike_str, opt = m_compact.groups()
        return f"{sym} {int(strike_str)} {opt}"

    # Fallback: return as-is (already clean or unrecognised format)
    return c.strip()


def format_signal_badge_and_lot(
    signal_or_headline: str,
    symbol: Optional[str] = None,
    lot_size: Optional[int] = None,
    direction: Optional[str] = None,
    option_type: Optional[str] = None,
    alert_type: Optional[str] = None,
    stage: Optional[str] = None,
    scenario: Optional[str] = None,
) -> str:
    """
    Institutional Telegram signal color coder & lot-size decorator.

    1. Color codes signals with standard scenario badges:
       - 🟢 Bullish / Call (CE) / Buy / Breakout
       - 🔴 Bearish / Put (PE) / Sell / Breakdown
       - 🟡 Neutral / Delta-Neutral / Iron Condor / Coiling
       - 🎯 Milestone (Target Achieved / Scale 1)
       - 🛑 Invalidation / Stop-Loss Hit
    2. Injects instrument lot size directly beside the price:
       e.g. "CONCOR 485 PE @ ₹7.2" → "🔴 CONCOR 485 PE @ ₹7.2 (Lot: 1250)"
       e.g. "OPTIONS MOMENTUM (PUT SURGE): BANKNIFTY 52000 PE @ ₹145.0"
            → "🔴 OPTIONS MOMENTUM (PUT SURGE): BANKNIFTY 52000 PE @ ₹145.0 (Lot: 30)"
    3. Idempotent: Never duplicates emojis or lot size tags.
    """
    if not signal_or_headline:
        return ""

    s = signal_or_headline.strip()

    # 1. Infer or lookup symbol
    inferred_sym = symbol
    if not inferred_sym:
        m_sym = re.search(r"\b([A-Z0-9_]{2,})\s+\d+\s*(?:CE|PE)\b", s)
        if m_sym:
            inferred_sym = m_sym.group(1)
        else:
            m_first = re.search(r"\b([A-Z0-9_]{2,})\b", s)
            if m_first and m_first.group(1) not in (
                "BUY",
                "SELL",
                "OPTIONS",
                "MOMENTUM",
                "GAMMA",
                "BLAST",
                "BREAKOUT",
                "BREAKDOWN",
                "PUT",
                "CALL",
            ):
                inferred_sym = m_first.group(1)

    # 2. Resolve lot size (from argument or position sizer master)
    resolved_lot = lot_size
    if resolved_lot is None:
        if inferred_sym:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(inferred_sym)
                if ls and ls > 1:
                    resolved_lot = ls
            except Exception:
                resolved_lot = None

    # 3. Determine Scenario & Directional Badge
    s_upper = s.upper()
    dir_upper = (direction or "").strip().upper()
    opt_upper = (option_type or "").strip().upper()
    alert_type_upper = (alert_type or "").strip().upper()
    stage_upper = (stage or "").strip().upper()
    scen_upper = (scenario or "").strip().upper()

    is_invalidation = (
        scen_upper in ("INVALIDATED", "STOPPED_OUT", "INVALIDATION", "STOP_LOSS")
        or stage_upper in ("INVALIDATED", "STOPPED_OUT", "CANCELLED")
        or "INVALIDATED" in s_upper
        or "NO LONGER VALID" in s_upper
        or "STOPPED OUT" in s_upper
        or "STOP LOSS HIT" in s_upper
    )
    is_target = (
        scen_upper in ("TARGET_HIT", "TARGET", "TARGET_ACHIEVED", "T1", "T2", "FINAL_TARGET")
        or stage_upper
        in (
            "TARGET_ACHIEVED",
            "FINAL_TARGET",
            "T1_ACHIEVED",
            "T2_ACHIEVED",
            "TARGET_0_5",
            "SCALE_1_ACHIEVED",
        )
        or "TARGET 1" in s_upper
        or "TARGET 2" in s_upper
        or "FINAL TARGET" in s_upper
        or "TARGET ACHIEVED" in s_upper
        or "DE-RISK SCALE HIT" in s_upper
    )
    is_neutral = (
        scen_upper in ("NEUTRAL", "DELTA_NEUTRAL", "IRON_CONDOR")
        or dir_upper in ("NEUTRAL", "DELTA_NEUTRAL")
        or "IRON_CONDOR" in alert_type_upper
        or "IRON CONDOR" in s_upper
        or "DELTA-NEUTRAL" in s_upper
        or "PINNING" in s_upper
    )
    is_coiling = (
        scen_upper in ("COILING", "PRECURSOR", "SQUEEZE", "EARLY_WARNING")
        or stage_upper in ("EARLY_WARNING", "COILING")
        or "COILING" in s_upper
        or "PRECURSOR" in s_upper
        or "PRECURSOR_RADAR" in alert_type_upper
        or "SQUEEZE COILING" in s_upper
    )

    is_bear = (
        scen_upper in ("BEAR", "BEARISH", "PUT", "SHORT", "SELL")
        or opt_upper == "PE"
        or bool(re.search(r"\b\d+\s*PE\b|\bPE\b", s_upper))
        or "PUT" in s_upper
        or "PUT" in alert_type_upper
        or dir_upper in ("BEARISH", "SHORT", "SELL", "DOWN")
        or "BREAKDOWN" in s_upper
        or "BREAKDOWN" in alert_type_upper
    )

    is_bull = (
        scen_upper in ("BULL", "BULLISH", "CALL", "LONG", "BUY")
        or opt_upper == "CE"
        or bool(re.search(r"\b\d+\s*CE\b|\bCE\b", s_upper))
        or "CALL" in s_upper
        or "CALL" in alert_type_upper
        or dir_upper in ("BULLISH", "LONG", "BUY", "UP")
        or "BREAKOUT" in s_upper
        or "BREAKOUT" in alert_type_upper
    )

    if is_invalidation:
        badge = "🛑"
    elif is_target:
        badge = "🎯"
    elif is_neutral:
        badge = "🟡"
    elif is_bear:
        badge = "🔴"
    elif is_bull:
        badge = "🟢"
    elif is_coiling:
        badge = "⚡"
    elif is_neutral:
        badge = "🟡"
    else:
        badge = "🟢"

    # 4. Inject Lot Size beside Price if not already present
    if (
        resolved_lot
        and resolved_lot > 1
        and not re.search(r"\(\s*Lot:?\s*\d+\s*\)", s, flags=re.IGNORECASE)
    ):
        pattern = r"(@\s*₹?\s*[\d,]+(?:\.\d+)?)"
        if re.search(pattern, s):
            s = re.sub(pattern, rf"\1 (Lot: {resolved_lot})", s, count=1)
        elif bool(re.search(r"\b\d+\s*(?:CE|PE)\b", s)):
            s = re.sub(r"(\b\d+\s*(?:CE|PE)\b)", rf"\1 (Lot: {resolved_lot})", s, count=1)

    # 5. Prepend Badge if not already present
    has_leading_badge = bool(re.match(r"^[🟢🔴🟡⚡🎯🏆🛑⚠️🚨💎🌙🛢️💱🪙]", s))
    if not has_leading_badge:
        s = f"{badge} {s}"
    elif (is_bear and s.startswith("🟢")) or (is_bull and s.startswith("🔴")):
        s = f"{badge} " + s[1:].lstrip()

    return s


def parse_contract_components(
    contract: str = "",
    underlying: str = "",
    strike: Any = None,
    option_type: str = "",
    expiry_date: Optional[str | datetime | date] = None,
    expiry_type: Optional[str] = None,
    dte: Optional[int | float] = None,
    spot: float = 0.0,
) -> dict[str, Any]:
    """
    Parses any raw broker or exchange contract string and extracts cleanly separated components:
      - underlying: e.g. "MIDCPNIFTY", "HDFCBANK", "HAL"
      - strike: float e.g. 14250.0 or None
      - strike_str: str e.g. "14250" or ""
      - option_type: "CE", "PE", or "FUT"
      - strike_display: "14250 CE"
      - display_contract: "MIDCPNIFTY 14250 CE"
      - is_option: bool
      - is_futures: bool
      - expiry_badge: "Current Monthly · 29-Sep-2026 (13 DTE)"
      - expiry_date: "29-Sep-2026"
      - dte: int
      - spot: float
    """
    c = re.sub(r"^(?:NSE|BSE|NFO|MCX|CDS|BFO):", "", (contract or "").strip(), flags=re.IGNORECASE)
    c_upper = c.upper()

    und = (underlying or "").strip().upper()
    stk: Optional[float] = None
    if strike is not None:
        try:
            stk = float(str(strike).replace(",", ""))
        except (ValueError, TypeError):
            stk = None
    opt = str(option_type or "").strip().upper()
    exp_extracted: Optional[str] = None

    # 1. Spaced format: e.g. "HAL 4800 PE", "HAL 26SEP 4500 CE", "MIDCPNIFTY 14250 CE"
    m_spaced = re.match(
        r"^([A-Z]+)\s+(?:(\d{1,2}[A-Z]{3}|\d{2}[A-Z]{3})\s+)?(\d+(?:\.\d+)?)\s*(CE|PE|FUT)$",
        c_upper,
    )
    if m_spaced:
        und_found, exp_raw, stk_raw, opt_found = m_spaced.groups()
        if not und:
            und = und_found
        if stk is None:
            try:
                stk = float(stk_raw)
            except ValueError:
                pass
        if not opt:
            opt = opt_found
        if exp_raw and not expiry_date:
            exp_extracted = exp_raw

    # 2. Broker YYYYMMDD format: e.g. HAL202609294800PE, MIDCPNIFTY2026092914250CE
    if stk is None:
        m_yyyymmdd = re.match(r"^([A-Z]+)(20\d{6})(\d+)(CE|PE)$", c_upper)
        if m_yyyymmdd:
            und_found, dt_str, stk_raw, opt_found = m_yyyymmdd.groups()
            if not und:
                und = und_found
            stk = float(stk_raw)
            opt = opt_found
            if not expiry_date:
                try:
                    exp_dt = datetime.strptime(dt_str, "%Y%m%d").date()
                    expiry_date = exp_dt
                except ValueError:
                    pass

    # 3. NSE Weekly compact: e.g. NIFTY2692524800CE
    if stk is None:
        m_weekly = re.match(r"^([A-Z]+)(\d{2}[1-9OND]\d{2})(\d+)(CE|PE)$", c_upper)
        if m_weekly:
            und_found, exp_code, stk_raw, opt_found = m_weekly.groups()
            if not und:
                und = und_found
            stk = float(stk_raw)
            opt = opt_found
            if not expiry_date:
                exp_extracted = exp_code

    # 4. NSE Monthly compact: e.g. HAL26SEP4800PE, RELIANCE26SEP3000CE
    if stk is None:
        m_monthly = re.match(r"^([A-Z]+)(\d{2}[A-Z]{3})(\d+)(CE|PE)$", c_upper)
        if m_monthly:
            und_found, exp_code, stk_raw, opt_found = m_monthly.groups()
            if not und:
                und = und_found
            stk = float(stk_raw)
            opt = opt_found
            if not expiry_date:
                exp_extracted = exp_code

    # 5. Compact no-date: e.g. HDFCBANK680CE, MIDCPNIFTY14250CE
    if stk is None:
        m_compact = re.match(r"^([A-Z]+?)(\d+)(CE|PE)$", c_upper)
        if m_compact:
            und_found, stk_raw, opt_found = m_compact.groups()
            if not und:
                und = und_found
            stk = float(stk_raw)
            opt = opt_found

    # 6. Futures: e.g. HAL FUT, HAL26SEPFUT
    is_futures = False
    if "FUT" in c_upper or opt == "FUT":
        is_futures = True
        opt = "FUT"
        if not und:
            m_fut = re.match(r"^([A-Z]+)(?:\d{2}[A-Z]{3}|\s+)?FUT$", c_upper)
            if m_fut:
                und = m_fut.group(1)

    # Fallback for underlying
    if not und:
        und = re.sub(r"[^A-Z]", "", c_upper) if c_upper else "STOCK"

    # Formatted strike string
    stk_str = ""
    if stk is not None and stk > 0:
        stk_str = f"{int(stk)}" if stk.is_integer() else f"{stk}"

    is_option = bool(stk_str and opt in ("CE", "PE"))

    # Display contract
    if is_futures:
        display_contract = f"{und} FUT"
    elif is_option:
        display_contract = f"{und} {stk_str} {opt}"
    elif c:
        display_contract = format_contract_display(c)
    else:
        display_contract = und

    # Expiry resolution
    exp_info = resolve_expiry_cycle(
        contract=c or display_contract,
        expiry_date=expiry_date or exp_extracted,
        expiry_type=expiry_type,
        dte=dte,
        underlying=und,
    )

    strike_display = f"{stk_str} {opt}".strip() if stk_str else opt

    return {
        "underlying": und,
        "strike": stk,
        "strike_str": stk_str,
        "option_type": opt,
        "strike_display": strike_display,
        "display_contract": display_contract,
        "is_option": is_option,
        "is_futures": is_futures,
        "expiry_badge": exp_info.get("badge", ""),
        "expiry_date": exp_info.get("expiry_date", ""),
        "dte": exp_info.get("dte"),
        "spot": spot,
    }


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
        comps = parse_contract_components(contract=contract, underlying=symbol)
        if comps["is_option"] and comps["strike_str"] and comps["option_type"]:
            contract_tag = f"{comps['strike_str']}{comps['option_type']}"
        elif comps["is_futures"]:
            contract_tag = "FUT"
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)", contract, re.IGNORECASE)
            if m:
                strike_str = m.group(1).replace(".0", "")
                opt_str = m.group(2).upper()
                contract_tag = f"{strike_str}{opt_str}"
            else:
                clean_c = re.sub(r"[^A-Za-z0-9]", "", contract).upper()
                # Only use trailing chars if contract has digits and is not generic like "NIFTYOPTION"
                if (
                    clean_c
                    and clean_c != clean_sym
                    and any(ch.isdigit() for ch in clean_c)
                    and not clean_c.endswith("OPTION")
                ):
                    contract_tag = clean_c[-8:]

    # 2. Resolve Date & Time in IST
    dt: Optional[datetime] = None
    if created_at:
        dt = _parse_ts_to_dt(created_at)
    if not dt:
        dt = datetime.now(IST)

    day_str = dt.strftime("%d%b").upper()  # e.g. "11SEP"
    time_str = dt.strftime("%H%M")  # e.g. "0942"
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
    lot_size: Optional[int] = None
    runner_strike: Optional[dict[str, Any]] = None

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        underlying: str = "NIFTY",
        spot: float = 0.0,
        conviction_score: Optional[dict[str, Any]] = None,
        in_market: bool = True,
    ) -> FNOAlertData:
        # Resolve contract first so we can query get_ltp if needed
        und = d.get("underlying", underlying)
        contract = d.get("contract")
        opt_type = str(d.get("option_type", d.get("type", "CE"))).upper()
        if not contract or contract.strip().endswith("OPTION"):
            strike = d.get("strike")
            if strike:
                contract = f"{und} {int(float(strike))} {opt_type}"
            elif spot and spot > 0:
                step = 100 if "BANK" in und.upper() else (50 if "NIFTY" in und.upper() else 10)
                atm_strike = int(round(spot / step) * step)
                contract = f"{und} {atm_strike} {opt_type}"
            else:
                contract = f"{und} OPTION"

        is_fallback = False
        prem = float(
            d.get("premium", d.get("entry_price", d.get("ask", d.get("bid", d.get("ltp", 0.0)))))
            or 0.0
        )
        if prem <= 0.0 and d.get("entry_range"):
            m_pr = re.search(r"[\d,]+(?:\.\d+)?", str(d.get("entry_range")))
            if m_pr:
                try:
                    prem = float(m_pr.group(0).replace(",", ""))
                except ValueError:
                    pass

        if prem <= 0.05:
            is_fallback = True
            if spot and spot > 0:
                prem = round(spot * 0.008, 2)
            else:
                prem = 50.0

        # Strict Data Provenance Contract:
        # Zero compromise on data quality for real signals.
        # If real-time option quote was missing and fallback had to be used,
        # or if caller explicitly marked test/simulated, enforce environment="TEST".
        raw_env = str(d.get("environment", "LIVE")).upper()
        is_realtime = d.get("is_realtime", True)
        is_live = d.get("is_live", True)
        if (
            is_fallback
            or not is_realtime
            or not is_live
            or raw_env in ("TEST", "SIMULATED", "DEMO")
        ):
            final_env = "TEST"
        else:
            final_env = raw_env

        e_low = d.get("entry_low") or round(max(0.5, prem * 0.95), 2)
        e_high = d.get("entry_high") or round(prem * 1.03, 2)
        entry_range = d.get("entry_range") or f"₹{e_low:,.2f} – ₹{e_high:,.2f}"

        sl = float(d.get("stop_loss", round(prem * 0.75, 2)))
        risk_pts = max(1.0, round(prem - sl, 2))
        sl_pct = str(
            d.get("stop_loss_pct", f"-{round(((prem - sl) / max(0.1, prem)) * 100.0, 1)}%")
        )
        t1 = float(d.get("target_1", round(prem + (risk_pts * 1.8), 2)))
        t1_pct = str(d.get("target_1_pct", f"+{round(((t1 - prem) / max(0.1, prem)) * 100.0, 1)}%"))
        t2 = float(d.get("target_2", round(prem + (risk_pts * 3.2), 2)))
        t2_pct = str(d.get("target_2_pct", f"+{round(((t2 - prem) / max(0.1, prem)) * 100.0, 1)}%"))
        rr = str(d.get("risk_reward", "1:3.2"))

        no_chase = d.get("no_chase_limit") or d.get("no_chase")
        if not no_chase:
            when_wait = d.get("when_to_wait", "")
            match = re.search(r"₹([\d,]+(?:\.\d+)?)", when_wait)
            if match:
                no_chase = f"₹{match.group(1)}"
            else:
                no_chase = f"₹{round(prem * 1.15, 2):,.2f}"

        action_title = d.get("action_title")
        if action_title:
            action_title = format_contract_display(action_title)

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

        lot_sz = d.get("lot_size")
        if not lot_sz:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(und or contract)
                if ls and ls > 1:
                    lot_sz = ls
            except Exception:
                lot_sz = None

        return cls(
            contract=contract,
            underlying=und,
            spot=float(d.get("spot", spot) or 0.0),
            action=d.get("action", "BUY"),
            score=int(d.get("score", d.get("conviction_score", 85))),
            option_type=opt_type,
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
            environment=final_env,
            in_market=in_market,
            action_title=action_title,
            expiry_date=exp_info.get("expiry_date"),
            expiry_type=d.get("expiry_type", exp_info.get("cycle")),
            dte=exp_info.get("dte"),
            expiry_cycle=exp_info.get("cycle"),
            expiry_badge=exp_info.get("badge"),
            lot_size=lot_sz,
            runner_strike=d.get("runner_strike")
            or (d.get("actionable_plan") or {}).get("runner_strike")
            or (d.get("metrics") or {}).get("runner_strike_info"),
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
        is_fallback = False

        if ltp <= 0.0 and symbol and symbol != "UNKNOWN":
            try:
                from market.quotes import get_ltp

                real_ltp = get_ltp(symbol)
                if real_ltp and real_ltp > 0:
                    ltp = float(real_ltp)
            except Exception:
                pass

        if ltp <= 0.0:
            is_fallback = True
            ltp = 100.0  # safe test placeholder

        # Strict Data Provenance Contract: Enforce TEST when realtime quote is missing
        raw_env = str(d.get("environment", "LIVE")).upper()
        is_realtime = d.get("is_realtime", True)
        is_live = d.get("is_live", True)
        if (
            is_fallback
            or not is_realtime
            or not is_live
            or raw_env in ("TEST", "SIMULATED", "DEMO")
        ):
            final_env = "TEST"
        else:
            final_env = raw_env

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
            environment=final_env,
            in_market=in_market,
        )


@dataclass
class MilestoneAlertData:
    """Data container for milestone events: Target Hit, Trailing Stop Ratchet, Invalidation."""

    milestone_type: (
        str  # "TARGET_1" | "TARGET_2" | "FINAL_TARGET" | "TRAIL_RATCHET" | "INVALIDATED"
    )
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
    target_0_5: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    target_moonshot: Optional[float] = None
    pnl_pts: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    direction: Optional[str] = "BULLISH"
    segment: Optional[str] = None
    lot_size: Optional[int] = None

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
        # Prefer original_call_time (immutable anchor set at signal creation) over created_at
        # to ensure "Call Given:" calculates elapsed time correctly on upgraded/ignited alerts
        created_at = getattr(alert, "original_call_time", None) or getattr(alert, "created_at", "")
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
            contract = (
                f"{getattr(alert, 'symbol', '')} {int(alert.strike)} {alert.option_type}".strip()
            )

        # Determine payoff direction (higher price = profit vs lower price = profit)
        alert_type_raw = str(getattr(alert, "alert_type", "SETUP") or "").upper()
        is_opt_contract = bool(
            getattr(alert, "option_type", None)
            or getattr(alert, "strike", None)
            or (contract and any(k in contract.upper() for k in ("CE", "PE", "OPTION")))
            or (
                getattr(alert, "symbol", "")
                and any(k in str(alert.symbol).upper() for k in ("CE", "PE", "OPTION"))
            )
            or alert_type_raw in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "OPTION_WRITE")
        )
        action_str = str(act_plan.get("action", "")).upper()
        if is_opt_contract:
            # Option sellers/writers profit on premium decay; Option buyers (both CE and PE) profit on premium expansion!
            is_option_seller = (
                any(k in action_str for k in ("SELL", "WRITE", "SHORT"))
                or alert_type_raw == "OPTION_WRITE"
            )
            is_payoff_bullish = not is_option_seller
        else:
            is_payoff_bullish = is_bullish

        # Signal Reference Tag
        # Verify existing_ref doesn't have an outdated strike/contract conflict
        existing_ref = getattr(alert, "signal_ref", None)
        if existing_ref and contract:
            m_c = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)", contract, re.IGNORECASE)
            if m_c:
                c_tag = f"{m_c.group(1).replace('.0', '')}{m_c.group(2).upper()}"
                m_ref = re.search(r"(\d+(?:\.\d+)?)(CE|PE)", existing_ref, re.IGNORECASE)
                if m_ref:
                    ref_tag = f"{m_ref.group(1)}{m_ref.group(2).upper()}"
                    if c_tag != ref_tag:
                        existing_ref = None

        sig_ref = existing_ref or build_signal_ref(
            symbol=getattr(alert, "symbol", "STOCK"),
            alert_id=str(alert_id),
            contract=str(contract or ""),
            created_at=str(created_at or ""),
        )

        # Entry Price resolution (Actionable plan recommended_entry takes canonical precedence)
        entry_price = None
        opt_plan = act_plan.get("option_plan") if isinstance(act_plan, dict) else None
        if is_opt_contract and isinstance(opt_plan, dict):
            if opt_plan.get("entry_premium"):
                entry_price = float(opt_plan["entry_premium"])

        entry_range = act_plan.get("entry_range")
        rec_entry = act_plan.get("recommended_entry")
        if not entry_price and rec_entry:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(rec_entry))
            if m:
                entry_price = float(m.group(0).replace(",", ""))
        if not entry_price and entry_range:
            matches = re.findall(r"[\d,]+(?:\.\d+)?", str(entry_range))
            if len(matches) >= 2:
                try:
                    entry_price = round(
                        (float(matches[0].replace(",", "")) + float(matches[1].replace(",", "")))
                        / 2.0,
                        2,
                    )
                except ValueError:
                    pass
            elif len(matches) == 1:
                try:
                    entry_price = float(matches[0].replace(",", ""))
                except ValueError:
                    pass
        if not entry_price or entry_price == 0.0:
            if is_opt_contract:
                entry_price = getattr(alert, "option_premium", None) or (
                    alert.ltp
                    if (
                        alert.ltp
                        and (not getattr(alert, "strike", None) or alert.ltp != alert.strike)
                    )
                    else None
                )
            else:
                entry_price = getattr(alert, "trigger_level", None) or getattr(alert, "ltp", None)
        if not entry_price or entry_price == 0.0:
            entry_price = getattr(alert, "option_premium", None) or getattr(
                alert, "threshold", None
            )

        # Initial Stop Loss resolution
        initial_sl = None
        if is_opt_contract and isinstance(opt_plan, dict) and opt_plan.get("sl_premium"):
            initial_sl = float(opt_plan["sl_premium"])
        if not initial_sl:
            act_sl = act_plan.get("stop_loss")
            if act_sl:
                m = re.search(r"[\d,]+(?:\.\d+)?", str(act_sl))
                if m:
                    initial_sl = float(m.group(0).replace(",", ""))
        if not initial_sl or initial_sl == 0.0:
            initial_sl = getattr(alert, "stop_loss", None)

        # Targets resolution (T0.5, T1, T2, Moonshot)
        t0_5_val = None
        t1_val = None
        t2_val = None
        moon_val = None

        if is_opt_contract and isinstance(opt_plan, dict):
            if opt_plan.get("t0_5_premium") or opt_plan.get("t05_premium"):
                t0_5_val = float(opt_plan.get("t0_5_premium") or opt_plan.get("t05_premium"))
            if opt_plan.get("t1_premium"):
                t1_val = float(opt_plan["t1_premium"])
            if opt_plan.get("t2_premium"):
                t2_val = float(opt_plan["t2_premium"])
            if opt_plan.get("t3_premium"):
                moon_val = float(opt_plan["t3_premium"])

        if "target_0_5" in act_plan:
            m = re.search(r"[\d,]+(?:\.\d+)?", str(act_plan["target_0_5"]))
            if m:
                t0_5_val = float(m.group(0).replace(",", ""))
        elif "target_05" in act_plan or "t0_5" in act_plan or "t05" in act_plan:
            m = re.search(
                r"[\d,]+(?:\.\d+)?",
                str(act_plan.get("target_05") or act_plan.get("t0_5") or act_plan.get("t05")),
            )
            if m:
                t0_5_val = float(m.group(0).replace(",", ""))

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

        # ONLY for non-option assets (Equity / Commodity / Currency directly), extract from trade_plan.
        # Option contracts must NEVER inherit underlying spot levels from trade_plan!
        if not is_opt_contract:
            tp_obj = act_plan.get("trade_plan")
            if tp_obj:
                if isinstance(tp_obj, dict):
                    t0_5_val = t0_5_val or tp_obj.get("target_0_5") or tp_obj.get("target_05")
                    t1_val = t1_val or tp_obj.get("target_1")
                    t2_val = t2_val or tp_obj.get("target_2")
                    moon_val = moon_val or tp_obj.get("target_moonshot")
                else:
                    t0_5_val = t0_5_val or getattr(
                        tp_obj, "target_0_5", getattr(tp_obj, "target_05", None)
                    )
                    t1_val = t1_val or getattr(tp_obj, "target_1", None)
                    t2_val = t2_val or getattr(tp_obj, "target_2", None)
                    moon_val = moon_val or getattr(tp_obj, "target_moonshot", None)

        raw_target_level = getattr(alert, "target_level", getattr(alert, "target_price", None))
        if not t2_val and raw_target_level:
            is_valid_raw_tgt = True
            if is_opt_contract and entry_price and entry_price > 0:
                if raw_target_level > entry_price * 10:
                    is_valid_raw_tgt = False
            if is_valid_raw_tgt:
                if t1_val and raw_target_level > t1_val:
                    t2_val = raw_target_level
                elif not t1_val:
                    if milestone_type == "TARGET_1":
                        if (
                            entry_price
                            and abs(raw_target_level - entry_price) > abs(ltp - entry_price) * 1.3
                        ):
                            t1_val = ltp
                            t2_val = raw_target_level
                        else:
                            t1_val = raw_target_level
                    else:
                        t2_val = raw_target_level

        # Strict Domain Sanity Filter for Option Contracts:
        # Prevent any stray underlying spot prices from polluting option target/SL fields.
        if is_opt_contract and entry_price and entry_price > 0:
            if t1_val and t1_val > entry_price * 10:
                t1_val = None
            if t2_val and t2_val > entry_price * 10:
                t2_val = None
            if moon_val and moon_val > entry_price * 15:
                moon_val = None
            if initial_sl and initial_sl > entry_price * 4:
                initial_sl = round(max(0.05, entry_price * 0.70), 2)

        if not t0_5_val and milestone_type == "TARGET_0_5":
            t0_5_val = ltp
        if not t1_val and milestone_type == "TARGET_1":
            t1_val = ltp
        if not t2_val and milestone_type == "TARGET_2":
            t2_val = ltp

        # Performance & Gain calculation
        # True market move is computed from actual price change (ltp - entry_price for long payoffs)
        pnl_pts = None
        pnl_pct = None
        if entry_price and entry_price > 0 and ltp and ltp > 0:
            pnl_pts = (
                round(ltp - entry_price, 2) if is_payoff_bullish else round(entry_price - ltp, 2)
            )
            pnl_pct = round((pnl_pts / entry_price) * 100.0, 1)

        # R-multiple calculation against initial risk
        r_multiple = getattr(alert, "r_multiple", None)
        if entry_price and initial_sl:
            init_risk = abs(entry_price - initial_sl)
            if init_risk > 0 and pnl_pts is not None:
                r_multiple = round(pnl_pts / init_risk, 2)

        if milestone_type == "TARGET_0_5":
            default_action = "SCALE 35% PARTIAL PROFIT NOW & HOLD RUNNER"
            ts_val = trailing_stop or getattr(alert, "stop_loss", None)
            if entry_price and is_payoff_bullish:
                be_clamp = round(entry_price * 1.002, 2)
                if not ts_val or ts_val < be_clamp:
                    ts_val = be_clamp
            elif entry_price and not is_payoff_bullish:
                be_clamp = round(entry_price * 0.998, 2)
                if not ts_val or ts_val > be_clamp:
                    ts_val = be_clamp
            if not ts_val:
                ts_val = ltp * 0.998 if is_payoff_bullish else ltp * 1.002
            trailing_stop = ts_val
        elif milestone_type == "TARGET_1":
            default_action = "BOOK 50% PROFIT NOW & HOLD RUNNER"
            ts_val = trailing_stop or getattr(alert, "stop_loss", None)
            # Breakeven stop for long buyers must be at least entry (+0.2% buffer), never below entry!
            if entry_price and is_payoff_bullish:
                be_clamp = round(entry_price * 1.002, 2)
                if not ts_val or ts_val < be_clamp:
                    ts_val = be_clamp
            elif entry_price and not is_payoff_bullish:
                be_clamp = round(entry_price * 0.998, 2)
                if not ts_val or ts_val > be_clamp:
                    ts_val = be_clamp
            if not ts_val:
                ts_val = ltp * 0.998 if is_payoff_bullish else ltp * 1.002
            trailing_stop = ts_val
        elif milestone_type == "TARGET_2":
            # For Target 2, trailing stop is locked at Target 1 level
            ts_val = trailing_stop or t1_val or getattr(alert, "stop_loss", None)
            if not ts_val and entry_price:
                ts_val = (
                    round(entry_price * 1.15, 2)
                    if is_payoff_bullish
                    else round(entry_price * 0.85, 2)
                )
            trailing_stop = ts_val
            default_action = (
                f"TRAIL STOP-LOSS TO T1 (₹{ts_val:,.2f}) & HOLD RUNNER"
                if ts_val
                else "TRAIL STOP-LOSS TO T1 & HOLD RUNNER"
            )
        elif milestone_type == "FINAL_TARGET":
            should_trail = getattr(alert, "should_trail", False)
            default_action = (
                "LET RUNNER RIDE (TRAIL SL)"
                if should_trail
                else "CLOSE ALL POSITIONS (BOOK FULL PROFIT)"
            )
        elif milestone_type == "TRAIL_RATCHET":
            default_action = f"UPDATE SL ORDER TO ₹{trailing_stop or 0:,.2f}"
        elif milestone_type in (
            "TIME_STOP_SCRATCH",
            "TIME_STOP_EXIT",
        ):
            default_action = "EXIT AT MARKET / SCRATCH NOW (STAGNATION TIME-STOP)"
        elif milestone_type in (
            "IN_FLIGHT_WARNING",
            "DANGER_ZONE",
            "THETA_STAGNATION",
            "0DTE_AFTERNOON_THETA_CLIFF",
            "0DTE_INTRADAY_DECAY",
            "VWAP_BAND_BREAKDOWN",
        ):
            default_action = (
                getattr(alert, "trailing_decision", None)
                or "SCRATCH POSITION AT MARKET OR TIGHTEN STOP"
            )
        else:  # INVALIDATED
            default_action = "CANCEL PENDING ORDERS & CLOSE POSITIONS"

        # Timestamp: prioritize updated/triggered time or current IST time over static created_at
        now_ist_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        update_ts = (
            timestamp
            or getattr(alert, "updated_at", None)
            or getattr(alert, "triggered_at", None)
            or now_ist_str
        )

        # Strict Data Provenance Contract:
        raw_env = str(getattr(alert, "environment", "LIVE")).upper()
        is_live = getattr(alert, "is_live", True)
        is_realtime = getattr(alert, "is_realtime", True)
        if not is_live or not is_realtime or raw_env in ("TEST", "SIMULATED", "DEMO") or ltp <= 0.0:
            final_env = "TEST"
        else:
            final_env = raw_env

        lot_sz = (
            getattr(alert, "lot_size", None)
            or act_plan.get("lot_size")
            or (
                getattr(alert, "metrics", {}).get("lot_size")
                if isinstance(getattr(alert, "metrics", None), dict)
                else None
            )
        )
        if not lot_sz and is_opt_contract:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(getattr(alert, "symbol", "") or contract or "")
                if ls and ls > 1:
                    lot_sz = ls
            except Exception:
                lot_sz = None

        return cls(
            milestone_type=milestone_type,
            symbol=getattr(alert, "symbol", "UNKNOWN"),
            alert_type=getattr(alert, "alert_type", "SETUP").replace("_", " "),
            ltp=ltp,
            target_level=target_level
            or (
                t2_val
                if milestone_type == "TARGET_2"
                else (t1_val if milestone_type == "TARGET_1" else None)
            ),
            trailing_stop=trailing_stop,
            locked_profit_pts=getattr(alert, "locked_profit_pts", None)
            or (
                round(abs(trailing_stop - entry_price), 2)
                if (
                    milestone_type in ("TARGET_1", "TARGET_2", "TRAIL_RATCHET")
                    and trailing_stop
                    and entry_price
                )
                else None
            ),
            locked_profit_pct=getattr(alert, "locked_profit_pct", None)
            or (
                round((abs(trailing_stop - entry_price) / entry_price) * 100.0, 1)
                if (
                    milestone_type in ("TARGET_1", "TARGET_2", "TRAIL_RATCHET")
                    and trailing_stop
                    and entry_price
                    and entry_price > 0
                )
                else None
            ),
            decisive_action=getattr(alert, "trailing_decision", None) or default_action,
            rationale=getattr(alert, "in_flight_warning_reason", None)
            or getattr(alert, "trailing_rationale", None)
            or getattr(alert, "summary", ""),
            invalidation_reason=getattr(alert, "invalidation_reason", None)
            or getattr(alert, "summary", ""),
            should_trail=getattr(alert, "should_trail", True),
            environment=final_env,
            in_market=in_market,
            timestamp=update_ts,
            signal_id=sig_ref,
            contract=contract,
            call_time=created_at,
            entry_price=entry_price,
            entry_range=entry_range,
            initial_sl=initial_sl,
            target_0_5=t0_5_val,
            target_1=t1_val,
            target_2=t2_val,
            target_moonshot=moon_val,
            pnl_pts=pnl_pts,
            pnl_pct=pnl_pct,
            r_multiple=r_multiple,
            direction=direction,
            segment=getattr(alert, "segment", None),
            lot_size=lot_sz,
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
    icon = "🟢" if is_call else "🔴"

    # Clean display contract: "HAL 4800 PE" not "HAL202609294800PE"
    display_contract = format_contract_display(d.contract)
    action_label = d.action_title or f"BUY {display_contract}"
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
        f" · 🚫 <b>DO NOT CHASE:</b> Above <code>{d.no_chase_limit}</code>"
        if d.no_chase_limit
        else ""
    )
    spot_part = f"Spot: <b>₹{d.spot:,.2f}</b>" if d.spot else ""
    opt_cmp_part = f"Opt CMP: <b>₹{d.premium:,.2f}</b>" if d.premium else ""
    if spot_part and opt_cmp_part:
        price_bar = f" · {spot_part} | {opt_cmp_part}"
    elif spot_part:
        price_bar = f" · {spot_part}"
    elif opt_cmp_part:
        price_bar = f" · {opt_cmp_part}"
    else:
        price_bar = ""
    sig_ref = build_signal_ref(symbol=d.underlying or d.contract, contract=d.contract)

    try:
        rr_match = re.search(r"[\d.]+$", str(d.risk_reward))
        rr_num = float(rr_match.group(0)) if rr_match else 2.5
    except Exception:
        rr_num = 2.5
    t1_r_label = "1.8R" if rr_num >= 3.0 else "1.5R"
    t2_r_label = "3.2R" if rr_num >= 3.0 else "2.5R"

    opt_cmp_entry = f" (Opt CMP: ₹{d.premium:,.2f})" if d.premium else ""
    lot_beside_p = f" (Lot: {d.lot_size})" if d.lot_size else ""
    lot_str = f" | <b>Lot:</b> {d.lot_size}" if d.lot_size else ""

    runner_str = ""
    if d.runner_strike and isinstance(d.runner_strike, dict):
        r_sym = format_contract_display(
            d.runner_strike.get("symbol")
            or f"{d.underlying} {int(d.runner_strike.get('strike', 0))} {d.runner_strike.get('option_type', d.option_type)}".strip()
        )
        r_ltp = float(d.runner_strike.get("ltp", 0.0) or 0.0)
        r_ltp_str = f" (Opt CMP: ₹{r_ltp:,.2f})" if r_ltp > 0 else ""
        runner_str = (
            f"\n• 🚀 <b>Runner Alternative (High Beta):</b> <code>{r_sym}</code>{r_ltp_str}"
        )

    msg = (
        f"{icon} <b>{env_tag} GAMMA BLAST SURGE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>{display_contract}</b> @ <code>₹{d.premium:,.2f}</code>{lot_beside_p}{price_bar}\n"
        f"{exp_line}"
        f"🎯 <b>Action:</b> <b>{action_label}</b>\n"
        f"• <b>Entry Zone:</b> <code>{d.entry_range}</code>{lot_beside_p}{opt_cmp_entry}\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> ({d.stop_loss_pct})\n"
        f"• <b>Target 1 ({t1_r_label}):</b> <code>₹{d.target_1:,.2f}</code> ({d.target_1_pct}) — <i>Scale 50% & SL to Cost{be_str}</i>\n"
        f"• <b>Target 2 ({t2_r_label}):</b> <code>₹{d.target_2:,.2f}</code> ({d.target_2_pct}) — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{d.risk_reward} R:R</b>{lot_str}{no_chase_str}"
        f"{runner_str}\n"
        f"💡 <b>Reason:</b> {d.trigger_reason} · {d.vol_oi:.1f}x Vol/OI (Imbalance: {d.imbalance:.1f}x)\n"
        f"📋 <b>Playbook:</b> <i>{d.profit_rule}</i>"
        f"{conv_badge}\n"
        f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
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
    is_bear = str(d.action).upper() in ("SELL", "SHORT") or "SHORT" in str(d.setup_title).upper()
    icon = "🔴" if is_bear else "🟢"
    status_badge = (
        f"{icon} <b>{env_tag} READY TO EXECUTE</b>"
        if d.status == "READY"
        else f"🎯 <b>{env_tag} STALK ON RETEST</b>"
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
        f"\n🚫 <b>DO NOT CHASE:</b> Above <code>{d.no_chase_limit}</code>"
        if d.no_chase_limit
        else ""
    )
    cat_str = " · ".join(d.catalysts[:2]) if d.catalysts else "Confirmed Institutional Structure"

    sig_ref = build_signal_ref(symbol=d.symbol)

    lot_sz = getattr(d, "lot_size", None)
    if not lot_sz:
        try:
            from engine.position_sizer import get_lot_size

            ls = get_lot_size(d.symbol)
            if ls and ls > 1:
                lot_sz = ls
        except Exception:
            lot_sz = None
    lot_beside_p = f" (Lot: {lot_sz})" if lot_sz else ""

    msg = (
        f"{status_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{d.symbol}</b> ({d.sector_icon} {d.sector}) · Spot CMP: <b>₹{d.ltp:,.2f}</b>\n"
        f"<i>{d.setup_title}</i>\n"
        f"🎯 <b>Action:</b> <b>{d.action}</b> @ <code>{d.entry_range}</code>{lot_beside_p} (Spot CMP: ₹{d.ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> (-{d.risk_pct:.1f}%)\n"
        f"• <b>Target 1 (2R):</b> <code>₹{d.target_1:,.2f}</code> (+{d.t1_pct:.1f}%) — <i>Scale 50% & SL to Breakeven</i>"
        f"{t2_str}{moon_str}\n"
        f"• <b>Risk : Reward:</b> <b>1:{d.risk_reward:.1f} R:R</b>{no_chase_str}\n"
        f"📊 <b>Scores:</b> Strategic: <b>{d.strategic_score}/100</b> | Live Tactical: <b>{d.tactical_score}/100</b> · RVOL: <b>{d.rvol:.1f}x</b>\n"
        f"💡 <b>Reason:</b> {cat_str}\n"
        f"⚡ <b>Quick Size:</b> <code>{d.quick_command}</code>\n"
        f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
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

    is_bear = (
        str(data.get("direction", "")).upper() in ("BEARISH", "SHORT", "SELL")
        or "SHORT" in str(data.get("setup_title", "")).upper()
        or "PE" in str(sym).upper()
    )
    dir_icon = "🔴" if is_bear else "🟢"
    act_verb = "SELL" if is_bear else "BUY"

    raw_factors = data.get("matched_factors", ["Pre-ignition volume dry-up & squeeze coiling"])
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
        off_note = (
            "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
        )
    else:
        header_line = f"{dir_icon} <b>{env_tag} PRECURSOR RADAR [{seg}]</b>"
        off_note = ""

    cmp_label = "Opt CMP" if seg == "FNO" else "Spot CMP"
    sig_ref = build_signal_ref(symbol=sym)

    lot_sz = data.get("lot_size") or (data.get("actionable_plan") or {}).get("lot_size")
    if not lot_sz and seg == "FNO":
        try:
            from engine.position_sizer import get_lot_size

            ls = get_lot_size(sym)
            if ls and ls > 1:
                lot_sz = ls
        except Exception:
            lot_sz = None
    lot_beside_p = f" (Lot: {lot_sz})" if lot_sz else ""
    lot_str = f" | <b>Lot:</b> {lot_sz}" if lot_sz else ""

    msg = (
        f"{header_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · {cmp_label}: <b>₹{ltp:,.2f}</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
        f"🎯 <b>Action: {act_verb}</b> @ <code>{entry_range}</code>{lot_beside_p} ({cmp_label}: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code>\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 50% & SL to Cost</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{t2:,.2f}</code> — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{rr}</b>{lot_str}\n"
        f"🚫 <b>{no_chase}</b>\n"
        f"💡 <b>Reason:</b> {factors_str}"
        f"{off_note}\n"
        f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
    )
    return msg


def render_asymmetric_alert(data: dict[str, Any], in_market: bool = True) -> str:
    """
    Renders an Asymmetric Opportunity alert (1:3+ R:R setups with moonshot extension).

    All primary trade levels (entry, SL, T1, T2, Moonshot) are rendered in **Underlying
    Spot units**.  Option and Futures execution vehicles are displayed as separate,
    clearly-labelled execution lines below the roadmap — they are NEVER mixed into the
    main spot price ladder.

    Level resolution priority (Spot context):
      underlying_spot / ltp  →  metrics["ltp"]  (never option premium from root)
      sl                     →  data["stop_loss"]  →  metrics["stop_loss"]
      t1                     →  metrics["target_1"]  →  actionable_plan["target_1"]
      t2                     →  metrics["target_2"]  →  actionable_plan["target_2"]
      moonshot               →  metrics["target_moonshot"] | moonshot_target
      entry_range            →  actionable_plan["entry_range"]  →  metrics["entry_range"]
    """
    sym = data.get("symbol", "STOCK")
    raw_seg = data.get("segment", "EQUITY")
    metrics = data.get("metrics") or {}
    act_plan = data.get("actionable_plan") or {}

    score = (
        data.get("conviction_score")
        or data.get("confidence")
        or metrics.get("conviction_score")
        or 85
    )
    verdict = data.get("verdict") or metrics.get("verdict") or "HIGH_CONVICTION"

    # ── Underlying Spot CMP ───────────────────────────────────────────────────
    # Always use the underlying spot price, NOT any option premium.
    # underlying_spot is the authoritative field; ltp falls back for direct dict usage.
    spot_ltp = float(data.get("underlying_spot") or metrics.get("ltp") or data.get("ltp") or 0.0)

    # ── Spot-Anchored Trade Levels ────────────────────────────────────────────
    # Resolution order: metrics (most authoritative for asymmetric setups,
    # directly from _enforce_monotonic_trade_levels) → actionable_plan → data root.
    # data["stop_loss"] at root is always Spot after Bug 1 fix.
    def _parse_price(val: Any) -> float:
        """Parse a price that may be a float, int, or ₹-prefixed string."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace("₹", "").replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    sl = _parse_price(
        data.get("stop_loss") or metrics.get("stop_loss") or act_plan.get("stop_loss")
    )
    t1 = _parse_price(
        metrics.get("target_1")
        or act_plan.get("target_1")
        or data.get("target_1")
        or data.get("target_level")
    )
    t2 = _parse_price(metrics.get("target_2") or act_plan.get("target_2") or data.get("target_2"))
    moonshot = _parse_price(
        metrics.get("target_moonshot")
        or metrics.get("moonshot_target")
        or act_plan.get("target_moonshot")
        or data.get("moonshot_target")
        or data.get("target_moonshot")
    )

    # ── Entry Range ───────────────────────────────────────────────────────────
    entry_range = (
        act_plan.get("entry_range")
        or metrics.get("entry_range")
        or data.get("entry_range")
        or f"₹{spot_ltp:,.1f}"
    )

    # ── R:R Display ───────────────────────────────────────────────────────────
    raw_rr = (
        data.get("risk_reward_ratio")
        or metrics.get("risk_reward_ratio")
        or data.get("risk_reward")
        or metrics.get("risk_reward")
        or act_plan.get("risk_reward")
        or 3.0
    )
    rr_str = str(raw_rr)
    rr_display = rr_str if rr_str.startswith("1:") else f"1:{rr_str}"

    env_tag = normalize_env_tag(data.get("environment", "LIVE"), in_market)
    confluences = (
        data.get("confluences")
        or metrics.get("confluence_factors")
        or data.get("confluence_factors")
        or []
    )
    conf_str = " · ".join(confluences[:3]) if confluences else "High asymmetric structural edge"

    moon_line = (
        f"\n• <b>Moonshot (+6R+):</b> <code>₹{moonshot:,.2f}</code> — <i>Runner Extension</i>"
        if moonshot
        else ""
    )

    direction = str(data.get("direction") or metrics.get("direction") or "BULLISH").upper()
    setup_type = str(data.get("setup_type") or metrics.get("setup_type") or "").upper()
    is_bearish = direction in ("BEARISH", "SHORT", "SELL") or "SHORT" in setup_type
    is_neutral = (
        direction in ("NEUTRAL", "DELTA_NEUTRAL")
        or "IRON_CONDOR" in setup_type
        or "PINNING" in setup_type
    )

    if "TURTLE_SOUP" in setup_type:
        setup_title_tag = "TURTLE SOUP SHORT"
    elif "IRON_CONDOR" in setup_type:
        setup_title_tag = "IRON CONDOR PINNING (DELTA-NEUTRAL)"
    elif is_bearish:
        setup_title_tag = "ASYMMETRIC SHORT SETUP"
    elif is_neutral:
        setup_title_tag = "ASYMMETRIC DELTA-NEUTRAL SETUP"
    else:
        setup_title_tag = "ASYMMETRIC SETUP"

    if not in_market:
        header_line = (
            f"🌙 <b>{env_tag} POST-MARKET EOD WATCHLIST — {setup_title_tag} [{rr_display} R:R]</b>"
        )
        off_note = (
            "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
        )
    else:
        icon = "🦅" if is_neutral else ("🔴" if is_bearish else "🟢")
        header_line = f"{icon} <b>{env_tag} {setup_title_tag} [{rr_display} R:R]</b>"
        off_note = ""

    # ── Segment classification ────────────────────────────────────────────────
    # For ASYMMETRIC_OPPORTUNITY the alert is always Spot-anchored, so we never
    # use "Opt CMP" for the header CMP label — always "Spot CMP".
    if raw_seg == "COMMODITY":
        clean_seg = "COMMODITY"
    elif raw_seg in ("INDEX", "FNO_INDEX") or sym in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    ):
        clean_seg = "FNO_INDEX"
    elif raw_seg in ("FNO", "FNO_STOCK") or metrics.get("segment") in ("FNO", "FNO_STOCK"):
        clean_seg = "FNO_STOCK"
    else:
        clean_seg = "EQUITY"

    # Asymmetric alerts are Spot setups: label is always "Spot CMP"
    cmp_label = "Spot CMP"
    sig_ref = build_signal_ref(symbol=sym)

    # ── Lot Size ──────────────────────────────────────────────────────────────
    lot_sz = data.get("lot_size") or metrics.get("lot_size") or act_plan.get("lot_size")
    if not lot_sz and clean_seg in ("FNO_INDEX", "FNO_STOCK"):
        try:
            from engine.position_sizer import get_lot_size

            ls = get_lot_size(sym)
            if ls and ls > 1:
                lot_sz = ls
        except Exception:
            lot_sz = None
    lot_beside_p = f" (Lot: {lot_sz})" if lot_sz else ""
    lot_str = f" | <b>Lot:</b> {lot_sz}" if lot_sz else ""

    # ── NEXT-MONTH ROLLOVER badge ─────────────────────────────────────────────
    is_next_month = bool(
        data.get("is_next_month_routed")
        or metrics.get("is_next_month_routed")
        or act_plan.get("is_next_month_routed")
    )
    safeguard_tag = " [🎯 NEXT-MONTH ROLLOVER · SEBI Physical Margin Safe]" if is_next_month else ""

    # ── F&O Alternative execution line ────────────────────────────────────────
    # Always rendered from actionable_plan["option_plan"] when present.
    # NOT gated behind is_deriv (which is no longer applicable here).
    opt_plan = act_plan.get("option_plan") or {}
    opt_line = ""
    if opt_plan and opt_plan.get("contract_symbol"):
        opt_sym = format_contract_display(opt_plan.get("contract_symbol"))
        opt_prem = opt_plan.get("entry_premium")
        opt_sl_prem = opt_plan.get("sl_premium")
        opt_t1_prem = opt_plan.get("t1_premium")
        opt_lot = opt_plan.get("lot_size")
        if not opt_lot:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(opt_sym or sym)
                if ls and ls > 1:
                    opt_lot = ls
            except Exception:
                opt_lot = None
        lot_tag = f" (Lot: {opt_lot})" if opt_lot else ""
        # Build a compact execution spec: premium | SL | T1
        exec_parts = []
        if opt_prem:
            exec_parts.append(f"@ ₹{opt_prem:,.1f}")
        if opt_sl_prem:
            exec_parts.append(f"SL: ₹{opt_sl_prem:,.1f}")
        if opt_t1_prem:
            exec_parts.append(f"T1: ₹{opt_t1_prem:,.1f}")
        exec_str = " | ".join(exec_parts)
        opt_line = (
            f"\n• <b>F&O Alternative:</b> <code>{opt_sym}</code>{lot_tag}"
            + (f" {exec_str}" if exec_str else "")
            + safeguard_tag
        )

    # ── Futures Preferred execution line ──────────────────────────────────────
    # Always rendered from actionable_plan["futures_plan"] when present.
    fut_plan = act_plan.get("futures_plan") or {}
    fut_line = ""
    fut_sym = (
        fut_plan.get("contract_symbol")
        or data.get("futures_contract_symbol")
        or metrics.get("futures_contract_symbol")
        or metrics.get("futures_contract")
    )
    if fut_sym:
        fut_lot = fut_plan.get("lot_size") or lot_sz
        fut_lot_tag = f" (Lot: {fut_lot})" if fut_lot else ""
        fut_entry = (
            fut_plan.get("entry_price") or data.get("futures_entry") or metrics.get("futures_entry")
        )
        fut_entry_str = f" @ ₹{fut_entry:,.1f}" if fut_entry else ""
        fut_line = (
            f"\n• <b>Futures Preferred:</b> <code>{fut_sym}</code>"
            f"{fut_entry_str}{fut_lot_tag} [Delta 1.0 · Zero Theta Decay]"
        )

    # ── Multi-directional message body ────────────────────────────────────────
    if is_neutral:
        metrics_dict = data.get("metrics") or {}
        spe = float(data.get("short_pe") or metrics_dict.get("short_pe") or sl or 0.0)
        sce = float(data.get("short_ce") or metrics_dict.get("short_ce") or t1 or 0.0)
        lpe = float(data.get("long_pe") or metrics_dict.get("long_pe") or 0.0)
        lce = float(data.get("long_ce") or metrics_dict.get("long_ce") or 0.0)
        net_credit = float(data.get("net_credit") or metrics_dict.get("net_credit") or 0.0)
        max_risk = float(data.get("max_risk") or metrics_dict.get("max_risk") or 0.0)
        corridor_low = float(data.get("corridor_low") or metrics_dict.get("corridor_low") or spe)
        corridor_high = float(data.get("corridor_high") or metrics_dict.get("corridor_high") or sce)

        wings_lines = []
        if spe and sce:
            wings_lines.append(
                f"• <b>Short Wing (Sell):</b> <code>{spe:,.0f} PE + {sce:,.0f} CE</code>"
            )
        if lpe and lce:
            wings_lines.append(
                f"• <b>Hedge Wing (Buy):</b> <code>{lpe:,.0f} PE + {lce:,.0f} CE</code>"
            )
        if net_credit:
            credit_str = f"• <b>Net Credit Harvest:</b> <code>+₹{net_credit:,.2f}/lot</code>"
            if max_risk:
                credit_str += f" | <b>Max Risk:</b> ₹{max_risk:,.2f}/lot"
            wings_lines.append(credit_str)
        wings_block = "\n" + "\n".join(wings_lines) if wings_lines else ""

        msg = (
            f"{header_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{sym} [{clean_seg}]</b> · {cmp_label}: <b>₹{spot_ltp:,.2f}</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
            f"🎯 <b>Action: SELL IRON CONDOR (DELTA-NEUTRAL)</b> @ Spot ₹{spot_ltp:,.2f}{lot_beside_p}\n"
            f"• <b>Corridor Pin Zone:</b> <code>₹{corridor_low:,.2f} – ₹{corridor_high:,.2f}</code>{wings_block}\n"
            f"• <b>Risk : Reward:</b> <b>{rr_display} R:R</b>{lot_str}{fut_line}{opt_line}\n"
            f"💡 <b>Reason:</b> {conf_str}"
            f"{off_note}\n"
            f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
        )
    elif is_bearish:
        msg = (
            f"{header_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{sym} [{clean_seg}]</b> · {cmp_label}: <b>₹{spot_ltp:,.2f}</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
            f"🎯 <b>Action: SHORT (SELL)</b> @ <code>{entry_range}</code>{lot_beside_p} ({cmp_label}: ₹{spot_ltp:,.2f})\n"
            f"• <b>Invalidation SL (Above High):</b> <code>₹{sl:,.2f}</code> (Risk: ₹{abs(sl - spot_ltp):,.2f})\n"
            f"• <b>Target 1 (Downside):</b> <code>₹{t1:,.2f}</code> — <i>Cover 40% & SL to Cost</i>\n"
            f"• <b>Target 2 (Downside):</b> <code>₹{t2:,.2f}</code> — <i>Cover 40% & Trail</i>{moon_line}\n"
            f"• <b>Risk : Reward:</b> <b>{rr_display} R:R</b>{lot_str}{fut_line}{opt_line}\n"
            f"💡 <b>Reason:</b> {conf_str}"
            f"{off_note}\n"
            f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
        )
    else:
        msg = (
            f"{header_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{sym} [{clean_seg}]</b> · {cmp_label}: <b>₹{spot_ltp:,.2f}</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
            f"🎯 <b>Action: BUY</b> @ <code>{entry_range}</code>{lot_beside_p} ({cmp_label}: ₹{spot_ltp:,.2f})\n"
            f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code> (Risk: ₹{abs(spot_ltp - sl):,.2f})\n"
            f"• <b>Target 1 (+2R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 40% & SL to Cost</i>\n"
            f"• <b>Target 2 (+4R):</b> <code>₹{t2:,.2f}</code> — <i>Scale 40% & Trail</i>{moon_line}\n"
            f"• <b>Risk : Reward:</b> <b>{rr_display} R:R</b>{lot_str}{fut_line}{opt_line}\n"
            f"💡 <b>Reason:</b> {conf_str}"
            f"{off_note}\n"
            f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
        )
    return msg


def render_milestone_alert(
    data: MilestoneAlertData | dict[str, Any], in_market: bool = True
) -> str:
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
            target_0_5=data.get("target_0_5"),
            target_1=data.get("target_1"),
            target_2=data.get("target_2"),
            target_moonshot=data.get("target_moonshot"),
            pnl_pts=data.get("pnl_pts"),
            pnl_pct=data.get("pnl_pct"),
            r_multiple=data.get("r_multiple"),
            direction=data.get("direction", "BULLISH"),
            segment=data.get("segment"),
            lot_size=data.get("lot_size"),
        )
    else:
        d = data

    env_tag = normalize_env_tag(d.environment, d.in_market)
    contract_title = format_contract_display(d.contract or d.symbol)
    if d.symbol and d.symbol not in contract_title:
        contract_title = f"{d.symbol} {contract_title}"

    is_pe = (
        "PE" in str(d.contract or "").upper()
        or "PE" in str(d.symbol or "").upper()
        or str(d.direction).upper() in ("BEARISH", "SHORT", "SELL")
    )
    color_icon = "🔴" if is_pe else "🟢"

    comps = parse_contract_components(contract=d.contract or "", underlying=d.symbol)
    is_fno = bool(
        comps["is_option"]
        or comps["is_futures"]
        or (d.contract and any(k in d.contract.upper() for k in ("CE", "PE", "FUT", "OPTION")))
        or (d.symbol and any(k in d.symbol.upper() for k in ("CE", "PE", "FUT", "OPTION")))
        or (d.segment and d.segment.upper() == "FNO")
        or "OPTION" in (d.alert_type or "").upper()
        or "GAMMA" in (d.alert_type or "").upper()
    )
    cmp_label = "Opt CMP" if is_fno else "Spot CMP"

    opt_spec_line = ""
    if comps["is_option"] and comps["strike_str"]:
        exp_badge_str = (
            f" | <b>Expiry:</b> ⏳ {comps['expiry_badge']}" if comps["expiry_badge"] else ""
        )
        opt_spec_line = f"• <b>Underlying:</b> {comps['underlying']} | <b>Strike:</b> {comps['strike_display']}{exp_badge_str}\n"

    call_time_fmt, elapsed_fmt = _format_call_time_and_elapsed(d.call_time, d.timestamp)
    call_time_part = (
        f" · 📞 <b>Call Given:</b> {call_time_fmt}{elapsed_fmt}" if call_time_fmt else ""
    )
    ref_line = (
        f"🏷️ <b>Ref:</b> <code>{d.signal_id}</code>{call_time_part}"
        if d.signal_id
        else (f"📞 <b>Call Given:</b> {call_time_fmt}{elapsed_fmt}" if call_time_fmt else "")
    )
    footer_line = f"\n{ref_line}" if ref_line else ""

    def _build_orig_plan(
        entry_p: Optional[float],
        entry_r: Optional[str],
        init_sl: Optional[float],
        t0_5: Optional[float] = None,
        t1: Optional[float] = None,
        t2: Optional[float] = None,
        tgt: Optional[float] = None,
        lot: Optional[int] = None,
    ) -> str:
        parts = []
        lot_tag = f" (Lot: {lot})" if (is_fno and lot and lot > 1) else ""
        if entry_p:
            parts.append(f"Entry: ₹{entry_p:,.2f}{lot_tag}")
        elif entry_r:
            parts.append(f"Entry: {entry_r}{lot_tag}")
        if init_sl:
            parts.append(f"SL: ₹{init_sl:,.2f}")
        if t0_5:
            parts.append(f"T0.5: ₹{t0_5:,.2f}")
        if t1:
            parts.append(f"T1: ₹{t1:,.2f}")
        if t2:
            parts.append(f"T2: ₹{t2:,.2f}")
        if tgt:
            parts.append(f"Target: ₹{tgt:,.2f}")
        if is_fno and lot and not (entry_p or entry_r):
            parts.append(f"Lot: {lot}")
        return f"\n🎯 <b>Original Plan:</b> {' | '.join(parts)}" if parts else ""

    if d.milestone_type in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH"):
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            lot=d.lot_size,
        )
        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · ⏱️ <b>P&L:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        return (
            f"⏱️ <b>{env_tag} VELOCITY TIME-STOP EXIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title} ({d.alert_type}) — STAGNATION TIME-STOP</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f}{move_str}\n"
            f"⏳ <b>Reason:</b> {d.invalidation_reason or d.rationale or 'Trade stagnant for >=20m without momentum expansion'}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>EXIT AT CMP / SCRATCH POSITION (HALT THETA DECAY)</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "INVALIDATED":
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            lot=d.lot_size,
        )

        return (
            f"⚠️ <b>{env_tag} VIEW INVALIDATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title} ({d.alert_type})</b> is <b>NO LONGER VALID</b>!\n"
            f"{opt_spec_line}"
            f"🛑 <b>Reason:</b> {d.invalidation_reason or d.rationale or 'Stop-loss or invalidation floor breached'}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CANCEL PENDING ORDERS & CLOSE POSITIONS</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type in (
        "IN_FLIGHT_WARNING",
        "DANGER_ZONE",
        "THETA_STAGNATION",
        "0DTE_AFTERNOON_THETA_CLIFF",
        "0DTE_INTRADAY_DECAY",
        "VWAP_BAND_BREAKDOWN",
    ):
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            lot=d.lot_size,
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · 📉 <b>P&L:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        m_type_upper = d.milestone_type.upper()
        diag_upper = str(d.rationale or "").upper()
        is_vwap = "VWAP" in m_type_upper or "VWAP" in diag_upper
        is_cliff = "CLIFF" in m_type_upper or "CLIFF" in diag_upper
        is_0dte = is_cliff or "0DTE" in m_type_upper or "0DTE" in diag_upper
        is_theta = is_0dte or "THETA" in m_type_upper or "THETA" in diag_upper

        if is_vwap:
            header_icon = "🌊"
            title_tag = "VWAP BAND WARNING"
            default_act = "SCRATCH POSITION AT MARKET OR TIGHTEN STOP TO VWAP BAND"
        elif is_cliff:
            header_icon = "⏳"
            title_tag = "0DTE THETA CLIFF WARNING"
            default_act = "EXIT 0DTE OPTION IMMEDIATELY TO AVOID PIN-RISK DECAY"
        elif is_theta:
            header_icon = "⏳"
            title_tag = "THETA DECAY WARNING"
            default_act = "EXIT / SCRATCH STAGNANT OPTION BEFORE FURTHER DECAY"
        else:
            header_icon = "⚠️"
            title_tag = "IN-FLIGHT DANGER WARNING"
            default_act = "SCRATCH POSITION AT MARKET OR TIGHTEN STOP"

        diag = d.rationale or d.invalidation_reason or "Risk budget eroding near stop-loss"
        decisive_act = d.decisive_action or default_act

        return (
            f"{header_icon} <b>{env_tag} {title_tag}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{color_icon} {contract_title} ({d.alert_type}) — ACTION REQUIRED</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f}{move_str}\n"
            f"⚠️ <b>Diagnosis:</b> {diag}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>{decisive_act}</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "TARGET_0_5":
        if d.trailing_stop is not None:
            ts_val = d.trailing_stop
        elif d.entry_price:
            is_buyer = not (
                (d.alert_type and "WRITE" in d.alert_type.upper())
                or (str(d.direction).upper() in ("SHORT", "SELL", "BEARISH") and not is_fno)
            )
            ts_val = (
                round(d.entry_price * 1.002, 2) if is_buyer else round(d.entry_price * 0.998, 2)
            )
        else:
            ts_val = d.ltp * 0.998

        t0_5_disp = d.target_0_5 or d.target_level or d.ltp
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            t0_5=t0_5_disp,
            t1=d.target_1,
            t2=d.target_2,
            lot=d.lot_size,
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        t1_runner_note = f" FOR T1 (₹{d.target_1:,.2f})" if d.target_1 else ""

        return (
            f"🎯 <b>{env_tag} TARGET 0.5 ACHIEVED (SCALE 1)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{color_icon} {contract_title} ({d.alert_type}) — DE-RISK SCALE HIT</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} | <b>Scale 1:</b> ₹{t0_5_disp:,.2f}{move_str}\n"
            f"🛡️ <b>Trail Stop:</b> <code>₹{ts_val:,.2f}</code> (Breakeven Cost Locked — 100% Risk-Free)\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>SCALE 35% PARTIAL PROFIT NOW & HOLD RUNNER{t1_runner_note}</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "TARGET_1":
        if d.trailing_stop is not None:
            ts_val = d.trailing_stop
        elif d.entry_price:
            is_buyer = not (
                (d.alert_type and "WRITE" in d.alert_type.upper())
                or (str(d.direction).upper() in ("SHORT", "SELL", "BEARISH") and not is_fno)
            )
            ts_val = (
                round(d.entry_price * 1.002, 2) if is_buyer else round(d.entry_price * 0.998, 2)
            )
        else:
            ts_val = d.ltp * 0.998
        lock_pct = f" (+{d.locked_profit_pct:.1f}% Breakeven Lock)" if d.locked_profit_pct else ""

        t1_disp = d.target_1 or d.target_level or d.ltp
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            t1=t1_disp,
            t2=d.target_2,
            lot=d.lot_size,
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        t2_runner_note = f" (Target 2: ₹{d.target_2:,.2f})" if d.target_2 else ""

        return (
            f"🎯 <b>{env_tag} TARGET 1 HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{color_icon} {contract_title} ({d.alert_type}) — TARGET 1 ACHIEVED</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} | <b>Target 1:</b> ₹{t1_disp:,.2f}{move_str}\n"
            f"🛡️ <b>Trail Stop:</b> <code>₹{ts_val:,.2f}</code>{lock_pct} (100% risk-free)\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>BOOK 50% PROFIT NOW & HOLD RUNNER{t2_runner_note}</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "TARGET_2":
        t2_disp = d.target_2 or d.target_level or d.ltp
        ts_val = d.trailing_stop or d.target_1 or d.entry_price or (d.ltp * 0.95)
        lock_pct = f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct else ""

        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            t1=d.target_1,
            t2=t2_disp,
            lot=d.lot_size,
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        t3_runner_note = (
            f" FOR T3 (₹{d.target_moonshot:,.2f})" if d.target_moonshot else " FOR FINAL TARGET"
        )

        return (
            f"🎯 <b>{env_tag} TARGET 2 HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{color_icon} {contract_title} ({d.alert_type}) — TARGET 2 ACHIEVED</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} | <b>Target 2:</b> ₹{t2_disp:,.2f}{move_str}\n"
            f"🛡️ <b>Trail Stop:</b> <code>₹{ts_val:,.2f}</code>{lock_pct} (T1 Locked)\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>TRAIL STOP-LOSS TO T1 (₹{ts_val:,.2f}) & HOLD RUNNER{t3_runner_note}</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "FINAL_TARGET":
        raw_tgt = d.target_2 or d.target_1 or d.target_level or d.ltp
        if is_fno and d.entry_price and d.entry_price > 0 and raw_tgt > d.entry_price * 10:
            tgt_val = d.target_1 or d.target_level or d.ltp
            if tgt_val > d.entry_price * 10:
                tgt_val = d.ltp
        else:
            tgt_val = raw_tgt

        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            tgt=tgt_val,
            lot=d.lot_size,
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = (
                f" · 📈 <b>Move:</b> <b>{sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})</b>"
            )

        if d.should_trail:
            ts_val = d.trailing_stop or d.ltp
            lock_str = (
                f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct is not None else ""
            )
            return (
                f"🚀 <b>{env_tag} RUNNER EXTENSION</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 <b>{color_icon} {contract_title} ({d.alert_type}) — INSTITUTIONAL RUNAWAY</b>\n"
                f"{opt_spec_line}"
                f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} | <b>Primary Target:</b> ₹{tgt_val:,.2f}{move_str}\n"
                f"🛡️ <b>Chandelier Trail SL:</b> <code>₹{ts_val:,.2f}</code>{lock_str}\n"
                f"⚡ <b>DECISIVE ACTION:</b> <code>LET RUNNER RIDE (TRAIL SL)</code>"
                f"{orig_plan_line}"
                f"{footer_line}"
            )
        return (
            f"🏁 <b>{env_tag} FINAL TARGET ACHIEVED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{color_icon} {contract_title} ({d.alert_type}) — FINAL TARGET REACHED</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} | <b>Final Target:</b> ₹{tgt_val:,.2f}{move_str}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CLOSE ALL POSITIONS (BOOK FULL PROFIT)</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    if d.milestone_type == "TRAIL_RATCHET":
        orig_plan_line = _build_orig_plan(
            entry_p=d.entry_price,
            entry_r=d.entry_range,
            init_sl=d.initial_sl,
            lot=d.lot_size,
        )

        lock_pts = f"+₹{d.locked_profit_pts:,.2f}/sh" if d.locked_profit_pts else ""
        lock_pct = f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct else ""
        lock_str = (
            f"🔒 <b>Guaranteed Profit:</b> {lock_pts}{lock_pct}\n" if (lock_pts or lock_pct) else ""
        )

        move_str = ""
        if d.pnl_pts is not None and d.pnl_pct is not None:
            sign = "+" if d.pnl_pts >= 0 else ""
            r_str = f" | {sign}{d.r_multiple}R" if d.r_multiple is not None else ""
            move_str = f" · 📈 <b>Move:</b> {sign}₹{d.pnl_pts:,.2f} ({sign}{d.pnl_pct:.1f}%{r_str})"

        # Dynamic Risk Compression Detection
        title_badge = "TRAILING STOP RATCHET"
        sub_title = f"{color_icon} {contract_title} Trailing Stop Ratcheted Higher!"
        if d.rationale and "BREAKEVEN" in d.rationale.upper():
            title_badge = "BREAKEVEN LOCKED (100% RISK-FREE)"
            sub_title = f"🛡️ {color_icon} {contract_title} Breakeven Locked — Free Trade!"
        elif d.rationale and (
            "DE-RISK" in d.rationale.upper()
            or "COMPRESS" in d.rationale.upper()
            or "SWEEP" in d.rationale.upper()
        ):
            title_badge = "RISK COMPRESSED (SL TIGHTENED)"
            sub_title = f"🛡️ {color_icon} {contract_title} Downside Risk Compressed!"

        diag_line = f"💡 <b>Rationale:</b> {d.rationale}\n" if d.rationale else ""

        return (
            f"📈 <b>{env_tag} {title_badge}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>{sub_title}</b>\n"
            f"{opt_spec_line}"
            f"💰 <b>{cmp_label}:</b> ₹{d.ltp:,.2f} · <b>New SL:</b> <code>₹{d.trailing_stop or 0:,.2f}</code>{move_str}\n"
            f"{lock_str}"
            f"{diag_line}"
            f"⚡ <b>DECISIVE ACTION:</b> <code>UPDATE SL ORDER TO ₹{d.trailing_stop or 0:,.2f}</code>"
            f"{orig_plan_line}"
            f"{footer_line}"
        )

    # Fallback
    return f"🔔 <b>{env_tag} {d.symbol}</b>: Milestone reached · {cmp_label}: ₹{d.ltp:,.2f}{footer_line}"


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


def render_in_flight_warning_alert(alert: Any, in_market: bool = True) -> str:
    """
    Renders a high-priority In-Flight Warning / Theta Decay alert for Telegram.
    Provides proactive risk coaching (scratch at breakeven or tighten stop)
    before an active position turns into a maximum loss.
    """
    diag = getattr(alert, "in_flight_warning_reason", "") or getattr(alert, "summary", "")
    diag_upper = str(diag).upper()
    if "VWAP" in diag_upper:
        m_type = "VWAP_BAND_BREAKDOWN"
    elif "CLIFF" in diag_upper or ("0DTE" in diag_upper and "AFTERNOON" in diag_upper):
        m_type = "0DTE_AFTERNOON_THETA_CLIFF"
    elif "0DTE" in diag_upper:
        m_type = "0DTE_INTRADAY_DECAY"
    elif "THETA" in diag_upper:
        m_type = "THETA_STAGNATION"
    else:
        m_type = "IN_FLIGHT_WARNING"
    data = MilestoneAlertData.from_alert(alert, m_type, in_market=in_market)
    return render_milestone_alert(data, in_market=in_market)


def render_auto_alert(alert: Any, in_market: bool = True) -> str:
    """
    Renders an AutoAlert instance into a crisp, standardized Telegram message.
    Handles Invalidation, Target 1, Final Target, Trail Ratchet, Precursor, Asymmetric,
    Options contracts (GAMMA_BLAST), Equity trade plans, and In-Flight Decay warnings.
    """
    is_test = (getattr(alert, "environment", "LIVE") == "TEST") or (
        not getattr(alert, "is_live", True)
    )
    env_tag = normalize_env_tag(getattr(alert, "environment", "LIVE"), in_market)

    # 0b. Velocity Time-Stop Exit (prioritized over standard invalidation)
    if getattr(alert, "stage", "") in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH") or (
        getattr(alert, "target_status", "") in ("TIME_STOP_EXIT", "TIME_STOP_SCRATCH")
    ):
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TIME_STOP_EXIT", in_market=in_market),
            in_market=in_market,
        )

    # 1. Invalidation
    if (
        getattr(alert, "is_invalidated", False)
        or getattr(alert, "stage", "") in ("INVALIDATED", "STOPPED_OUT", "CANCELLED")
        or getattr(alert, "status", "") in ("INVALIDATED", "STOPPED_OUT", "CANCELLED")
    ):
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "INVALIDATED", in_market=in_market),
            in_market=in_market,
        )

    # 1b. In-Flight Decay & Danger Zone Warning
    if getattr(alert, "stage", "") in ("IN_FLIGHT_WARNING", "DANGER_ZONE", "THETA_STAGNATION"):
        return render_in_flight_warning_alert(alert, in_market=in_market)

    # 1c. Target 0.5 (Scale 1) De-Risk Milestone
    is_t0_5 = (
        "T0_5" in (getattr(alert, "target_status", "") or "").upper()
        or "T0.5" in (getattr(alert, "target_status", "") or "").upper()
        or getattr(alert, "stage", "")
        in ("T0_5_ACHIEVED", "TARGET_0_5", "TARGET_0_5_HIT", "T0.5_ACHIEVED", "SCALE_1_ACHIEVED")
        or "TARGET 0.5" in (getattr(alert, "headline", "") or "").upper()
        or "T0.5 ACHIEVED" in (getattr(alert, "headline", "") or "").upper()
        or "SCALE 1" in (getattr(alert, "headline", "") or "").upper()
    )
    if is_t0_5:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TARGET_0_5", in_market=in_market),
            in_market=in_market,
        )

    # 2. Target 1
    is_t1 = "T1" in (getattr(alert, "target_status", "") or "").upper() or getattr(
        alert, "stage", ""
    ) in ("T1_ACHIEVED", "TARGET_1", "TARGET_1_HIT", "TARGET_1_ACHIEVED")
    if is_t1:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TARGET_1", in_market=in_market),
            in_market=in_market,
        )

    # 2b. Target 2
    is_t2 = "T2" in (getattr(alert, "target_status", "") or "").upper() or getattr(
        alert, "stage", ""
    ) in ("T2_ACHIEVED", "TARGET_2", "TARGET_2_HIT", "TARGET_2_ACHIEVED")
    if is_t2:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "TARGET_2", in_market=in_market),
            in_market=in_market,
        )

    # 3. Final Target / Runner Extension
    is_target = (
        getattr(alert, "is_target_hit", False)
        or getattr(alert, "stage", "")
        in ("TARGET_ACHIEVED", "COMPLETED", "TARGET_3_ACHIEVED", "FINAL_TARGET")
        or getattr(alert, "status", "") in ("TARGET_HIT", "TARGET_ACHIEVED", "COMPLETED")
        or (getattr(alert, "target_status", "") or "").upper()
        in ("TARGET", "TARGET_HIT", "TARGET_ACHIEVED", "FINAL_TARGET", "COMPLETED")
    )
    if is_target:
        return render_milestone_alert(
            MilestoneAlertData.from_alert(alert, "FINAL_TARGET", in_market=in_market),
            in_market=in_market,
        )

    # 4. Trailing Stop Ratchet & Dynamic Risk Compression
    if getattr(alert, "stage", "") in (
        "TRAILING_UPDATE",
        "DE_RISK_0_5R",
        "BREAKEVEN_LOCKED",
        "TRAIL_POST_SWEEP",
        "COMPRESS_STALL_RISK",
    ):
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

    is_crypto = (
        getattr(alert, "exchange", "") in ("CRYPTO", "BINANCE")
        or getattr(alert, "segment", "") == "CRYPTO"
        or str(getattr(alert, "symbol", "")).upper().startswith("CRYPTO:")
    )
    if is_test:
        tg_header = f"🧪 <b>{env_tag} TEST SETUP</b>"
    elif is_crypto:
        tg_header = "🪙 <b>[CRYPTO 24x7] ALPHA VORTEX</b>"
    elif not in_market:
        tg_header = f"🌙 <b>{env_tag} EOD WATCHLIST</b>"
    else:
        if (
            getattr(alert, "exchange", "") == "MCX"
            or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM"
        ):
            tg_header = f"🛢️ <b>{env_tag} MCX MOMENTUM</b>"
        elif (
            getattr(alert, "exchange", "") == "CDS"
            or getattr(alert, "alert_type", "") == "CURRENCY_BREAKOUT"
        ):
            tg_header = f"💱 <b>{env_tag} CURRENCY BREAKOUT</b>"
        elif getattr(alert, "stage", "") == "EARLY_WARNING" or getattr(alert, "alert_type", "") in (
            "PATTERN_COILING",
            "CIRCUIT_WARNING",
        ):
            tg_header = f"⚡ <b>{env_tag} EARLY WARNING (COILING)</b>"
        elif (
            getattr(alert, "alert_type", "") == "SQUEEZE_BREAKOUT"
            and getattr(alert, "stage", "") != "IGNITED"
        ):
            tg_header = f"⚡ <b>{env_tag} SQUEEZE COILING</b>"
        elif getattr(alert, "alert_type", "") in ("GAMMA_BLAST", "OPTIONS_MOMENTUM") or getattr(
            alert, "option_type", None
        ):
            is_put = (
                getattr(alert, "option_type", "") == "PE"
                or (getattr(alert, "direction", "") or "").upper() in ("BEARISH", "SHORT", "SELL")
                or "PE" in str(getattr(alert, "contract_symbol", "")).upper()
                or "PE" in str(getattr(alert, "headline", "")).upper()
            )
            opt_tag = "OPTIONS PUT SURGE" if is_put else "OPTIONS BREAKOUT"
            icon = "🔴" if is_put else "🟢"
            tg_header = f"{icon} <b>{env_tag} {opt_tag}</b>"
        else:
            is_bear = (
                (getattr(alert, "direction", "") or "").upper() in ("BEARISH", "SHORT", "SELL")
                or "BREAKDOWN" in str(getattr(alert, "alert_type", "")).upper()
                or "SHORT" in str(getattr(alert, "headline", "")).upper()
            )
            icon = "🔴" if is_bear else "🟢"
            tg_header = f"{icon} <b>{env_tag} BREAKOUT IGNITED</b>"

    is_crypto_alert = (
        getattr(alert, "exchange", "") in ("CRYPTO", "BINANCE")
        or getattr(alert, "segment", "") == "CRYPTO"
        or str(getattr(alert, "symbol", "")).upper().startswith("CRYPTO:")
    )
    off_note = (
        "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
        if not in_market and not is_test and not is_crypto_alert
        else ""
    )

    actionable_plan = getattr(alert, "actionable_plan", {}) or {}
    plan_str = ""

    # Options Contract Plan
    is_option_plan = bool(
        getattr(alert, "option_type", None)
        or getattr(alert, "alert_type", "") in ("GAMMA_BLAST", "OPTIONS_MOMENTUM")
        or actionable_plan.get("option_type")
        or actionable_plan.get("instrument_type") == "OPTION"
        or (
            actionable_plan.get("contract")
            and any(
                x in str(actionable_plan.get("contract")).upper()
                for x in (" CE", " PE", "CE", "PE")
            )
        )
        or (
            getattr(alert, "contract_symbol", None)
            and any(x in str(alert.contract_symbol).upper() for x in ("CE", "PE"))
        )
        or actionable_plan.get("option_plan")
    )
    is_mcx = bool(
        getattr(alert, "exchange", "") == "MCX"
        or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM"
    )
    if is_option_plan and not is_mcx and actionable_plan:
        act_raw = str(actionable_plan.get("action", "BUY"))
        act = (
            act_raw.replace("_MOMENTUM", "")
            .replace("BUY_CALL", "BUY CE")
            .replace("BUY_PUT", "BUY PE")
            .replace("_", " ")
            .strip()
        )
        opt_type_hint = getattr(alert, "option_type", None) or actionable_plan.get(
            "option_type", ""
        )
        inst = format_contract_display(
            actionable_plan.get("contract")
            or getattr(alert, "contract_symbol", None)
            or (
                f"{alert.symbol} {int(getattr(alert, 'strike', 0) or 0)} {opt_type_hint}".strip()
                if getattr(alert, "strike", None)
                else alert.symbol
            )
        )
        # Deduplicate option type from action verb if contract display already has it
        # e.g., act="BUY PE", inst="BSE 3200 PE" -> act="BUY", inst="BSE 3200 PE"
        inst_u = inst.upper()
        if any(tok in inst_u for tok in (" CE", " PE", "CE", "PE")) and any(
            tok in act.upper() for tok in (" CE", " PE")
        ):
            act = re.sub(r"\b(CE|PE)\b", "", act, flags=re.IGNORECASE).strip()
            act = re.sub(r"\s+", " ", act)
        entry = (
            actionable_plan.get("recommended_entry")
            or actionable_plan.get("entry_range")
            or f"₹{alert.ltp:.1f}"
        )
        tgt = (
            actionable_plan.get("target")
            or actionable_plan.get("target_1")
            or f"₹{getattr(alert, 'target_level', 0):.1f}"
        )
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):.1f}")

        # Spot-leakage defense: if entry or SL is in underlying spot units, rescue from option_plan
        opt_p = actionable_plan.get("option_plan") or {}
        if isinstance(opt_p, dict):
            try:
                m_e_val = float(re.findall(r"[\d,]+(?:\.\d+)?", str(entry))[0].replace(",", ""))
            except Exception:
                m_e_val = 0.0
            spot_val = float(getattr(alert, "underlying_spot", 0) or getattr(alert, "ltp", 0) or 0)
            if spot_val > 0 and m_e_val > (spot_val * 0.4):
                prem_entry = opt_p.get("entry_premium") or getattr(alert, "option_premium", None)
                if prem_entry and float(prem_entry) > 0:
                    entry = f"₹{float(prem_entry):,.2f}"
                sl_prem = opt_p.get("sl_premium") or opt_p.get("stop_loss")
                if sl_prem and float(sl_prem) > 0:
                    sl = f"₹{float(sl_prem):,.1f}"
                t1_prem = opt_p.get("t1_premium") or opt_p.get("target_1")
                if t1_prem and float(t1_prem) > 0:
                    tgt = f"₹{float(t1_prem):,.1f}"

        # Dynamic mathematical R:R calculation from levels
        calc_rr = None
        try:
            m_e = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)", str(entry))
            m_s = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)", str(sl))
            m_t = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)", str(tgt))
            if m_e and m_s and m_t:
                ve = float(m_e.group(1).replace(",", ""))
                vs = float(m_s.group(1).replace(",", ""))
                vt = float(m_t.group(1).replace(",", ""))
                risk_amt = abs(ve - vs)
                reward_amt = abs(vt - ve)
                if risk_amt > 0.01:
                    calc_rr = f"1:{round(reward_amt / risk_amt, 1)}"
        except Exception:
            calc_rr = None

        rr = calc_rr or actionable_plan.get("risk_reward", "1:3.0")
        opt_cmp = getattr(alert, "option_premium", None) or getattr(alert, "ltp", None)
        # Suppress redundant Opt CMP tag if entry already contains or closely matches it
        entry_val = None
        try:
            m = re.search(r"₹?\s*([\d,]+(?:\.\d+)?)", str(entry))
            if m:
                entry_val = float(m.group(1).replace(",", ""))
        except Exception:
            entry_val = None

        opt_cmp_match = (
            entry_val is not None and opt_cmp is not None and abs(opt_cmp - entry_val) <= 0.25
        )
        opt_cmp_str = (
            f" (Opt CMP: ₹{opt_cmp:,.2f})"
            if (
                opt_cmp
                and opt_cmp > 0
                and "Option Premium" not in str(entry)
                and f"₹{opt_cmp:.1f}" not in str(entry)
                and f"₹{opt_cmp:,.2f}" not in str(entry)
                and not opt_cmp_match
            )
            else ""
        )
        spot_ref = (
            f" (Spot: ₹{float(str(alert.underlying_spot).replace('₹', '').replace(',', '')):,.2f})"
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

        tgt2 = actionable_plan.get("target_2")
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if (tgt2 and tgt2 != tgt) else ""
        wait_rule = actionable_plan.get("when_to_wait")
        friday_warn = actionable_plan.get("friday_weekend_warning")
        warn_str = f"\n• {friday_warn}" if friday_warn else ""

        # Late session clock warning (post 15:15 IST until 15:30 close)
        now_dt = datetime.now(IST)
        session_clock_warn = ""
        if (
            in_market
            and getattr(alert, "exchange", "NSE") in ("NSE", "BSE", "NFO")
            and (now_dt.hour == 15 and 15 <= now_dt.minute < 30)
        ):
            mins_left = max(1, 30 - now_dt.minute)
            session_clock_warn = f"\n• ⚠️ <i>Market closes in {mins_left}m. Intraday MIS closed — Overnight Hold (NRML) or Next-Session Gameplan.</i>"

        spot_anchor = actionable_plan.get("spot_invalidation_anchor") or (
            alert.metrics.get("spot_invalidation_anchor")
            if isinstance(getattr(alert, "metrics", None), dict)
            else None
        )
        spot_anchor_str = (
            f" (Spot Anchor: <code>{spot_anchor}</code>)"
            if spot_anchor and str(spot_anchor) not in str(sl)
            else ""
        )
        profit_rule = actionable_plan.get("profit_rule")
        rule_str = f"\n• <b>Playbook:</b> <i>{profit_rule}</i>" if profit_rule else ""

        no_chase_val = getattr(alert, "no_chase_boundary", None)
        no_chase_inline = ""
        if no_chase_val and float(no_chase_val) > 0:
            comparator = get_no_chase_comparator(alert, actionable_plan, act)
            no_chase_inline = (
                f" | 🛑 <b>No-Chase:</b> <i>{comparator} ₹{float(no_chase_val):,.1f}</i>"
            )

        wait_str = ""
        if wait_rule:
            if no_chase_inline and (
                "DO NOT CHASE" in wait_rule.upper() or "NO CHASE" in wait_rule.upper()
            ):
                # Strip initial "Do not chase..." sentence without breaking on currency/percentage decimals like ₹13.0 or 1.5%
                clean_wait = re.sub(
                    r"^(?:DO NOT CHASE|NO CHASE).*?(?:\.(?!\d)|$)\s*",
                    "",
                    wait_rule,
                    flags=re.IGNORECASE,
                ).strip()
                # Sanitize: if clean_wait is empty or contains no letters (e.g. "0.", ".", "0"), suppress it
                has_letters = bool(re.search(r"[a-zA-Z]", clean_wait))
                wait_str = f"\n• <b>Discipline:</b> <i>{clean_wait}</i>" if has_letters else ""
            else:
                wait_str = f"\n• <b>Discipline:</b> <i>{wait_rule}</i>"

        lot_sz = (
            getattr(alert, "lot_size", None)
            or actionable_plan.get("lot_size")
            or (
                alert.metrics.get("lot_size")
                if isinstance(getattr(alert, "metrics", None), dict)
                else None
            )
        )
        if not lot_sz:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(getattr(alert, "symbol", "") or inst)
                if ls and ls > 1:
                    lot_sz = ls
            except Exception:
                lot_sz = None
        lot_beside_p = f" (Lot: {lot_sz})" if lot_sz else ""
        lot_str = f" | <b>Lot:</b> {lot_sz}" if lot_sz else ""

        runner_info = actionable_plan.get("runner_strike") or (
            alert.metrics.get("runner_strike_info")
            if isinstance(getattr(alert, "metrics", None), dict)
            else None
        )
        runner_str = ""
        if runner_info and isinstance(runner_info, dict):
            r_sym = format_contract_display(
                runner_info.get("symbol")
                or f"{alert.symbol} {int(runner_info.get('strike', 0))} {runner_info.get('option_type', '')}".strip()
            )
            r_ltp = float(runner_info.get("ltp", 0.0) or 0.0)
            r_ltp_str = f" (Opt CMP: ₹{r_ltp:,.2f})" if r_ltp > 0 else ""
            runner_str = (
                f"\n• 🚀 <b>Runner Alternative (High Beta):</b> <code>{r_sym}</code>{r_ltp_str}"
            )
        elif actionable_plan.get("runner_strike") and isinstance(
            actionable_plan.get("runner_strike"), (int, float)
        ):
            r_strike = int(actionable_plan["runner_strike"])
            r_sym = f"{alert.symbol} {r_strike} {getattr(alert, 'option_type', '')}".strip()
            runner_str = f"\n• 🚀 <b>Runner Alternative (High Beta):</b> <code>{r_sym}</code>"
        elif getattr(alert, "strike", None) and getattr(alert, "option_type", None):
            sym_clean = getattr(alert, "symbol", "")
            base_strike = float(alert.strike)
            opt_type = str(alert.option_type).upper()
            step = (
                50.0
                if "NIFTY" in sym_clean
                else (
                    100.0
                    if "BANK" in sym_clean or "SENSEX" in sym_clean
                    else (10.0 if base_strike < 1000 else (20.0 if base_strike < 2500 else 50.0))
                )
            )
            r_strike = base_strike + step if opt_type == "CE" else max(step, base_strike - step)
            r_sym = f"{sym_clean} {int(r_strike)} {opt_type}"
            runner_str = f"\n• 🚀 <b>Runner Alternative (High Beta OTM):</b> <code>{r_sym}</code>"

        plan_str = (
            f"{exp_line}"
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>{lot_beside_p}{opt_cmp_str}{spot_ref}\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>{spot_anchor_str}\n"
            f"• <b>Target:</b> <code>{tgt}</code>{tgt2_str}\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b>{lot_str}{no_chase_inline}"
            f"{runner_str}"
            f"{rule_str}"
            f"{wait_str}"
            f"{warn_str}"
            f"{session_clock_warn}"
        )
    elif (
        getattr(alert, "exchange", "") == "MCX"
        or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM"
    ):
        from market.options import format_readable_option_symbol

        pref_vehicle = actionable_plan.get("preferred_vehicle")
        is_opt_first = (
            pref_vehicle == "DEFINED_RISK_OPTION"
            or getattr(alert, "derivative_type", "") == "OPT"
            or "CE" in actionable_plan.get("action", "")
            or "PE" in actionable_plan.get("action", "")
        )

        act = actionable_plan.get("action", "BUY_FUTURES")
        inst = actionable_plan.get("contract", f"MCX:{alert.symbol}")
        # Clean display name for contract if not already formatted
        if ("CE" in inst or "PE" in inst) and "(" not in inst:
            inst = format_readable_option_symbol(inst)

        entry = actionable_plan.get("entry_range", f"₹{alert.ltp:,.1f}")
        tgt1 = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0):,.1f}")
        tgt2 = actionable_plan.get("target_2", "")
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):,.1f}")
        rr = actionable_plan.get("risk_reward", "1:2.4")
        lot = actionable_plan.get("lot_size", "")
        lot_beside_p = f" (Lot: {lot})" if lot else ""
        lot_str = f" | Lot: {lot}" if lot else ""
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Book 50% at T1, trail stop to cost.")
        confluence = actionable_plan.get("setup_confluence")
        confluence_str = f"\n🔬 <b>Confluence:</b> <i>{confluence}</i>" if confluence else ""

        max_loss = actionable_plan.get("max_loss_capped")
        capped_risk_str = (
            f"\n🛡️ <b>Capped Max Risk:</b> ₹{max_loss:,.0f} per lot (Zero overnight gap risk)"
            if max_loss
            else ""
        )

        fut_ref = actionable_plan.get("futures_reference")
        fut_ref_str = ""
        if fut_ref and isinstance(fut_ref, dict):
            fut_sym = fut_ref.get("contract", f"MCX:{alert.symbol}")
            fut_p = fut_ref.get("entry", 0.0)
            fut_sl = fut_ref.get("stop_loss", 0.0)
            fut_ref_str = (
                f"\n📍 <b>Underlying Anchor:</b> <code>{fut_sym}</code> @ ₹{fut_p:,.1f} "
                f"(Invalidation: ₹{fut_sl:,.1f})"
            )

        no_chase_val = getattr(alert, "no_chase_boundary", None)
        no_chase_inline = ""
        if no_chase_val and float(no_chase_val) > 0:
            comparator = get_no_chase_comparator(alert, actionable_plan, act)
            no_chase_inline = (
                f" | 🛑 <b>No-Chase:</b> <i>{comparator} ₹{float(no_chase_val):,.1f}</i>"
            )

        wait_rule = actionable_plan.get("when_to_wait")
        wait_str = ""
        if wait_rule:
            if no_chase_inline and (
                "DO NOT CHASE" in wait_rule.upper() or "NO CHASE" in wait_rule.upper()
            ):
                clean_wait = re.sub(
                    r"^(?:DO NOT CHASE|NO CHASE).*?(?:\.(?!\d)|$)\s*",
                    "",
                    wait_rule,
                    flags=re.IGNORECASE,
                ).strip()
                has_letters = bool(re.search(r"[a-zA-Z]", clean_wait))
                wait_str = f"\n• <b>Discipline:</b> <i>{clean_wait}</i>" if has_letters else ""
            else:
                wait_str = f"\n• <b>Discipline:</b> <i>{wait_rule}</i>"

        if is_opt_first:
            plan_str = (
                f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>{lot_beside_p}\n"
                f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
                f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
                f"• <b>R:R Expectancy:</b> <b>{rr}</b>{lot_str}{no_chase_inline}"
                f"{capped_risk_str}"
                f"{confluence_str}"
                f"{fut_ref_str}\n"
                f"• <b>Playbook:</b> <i>{rule}</i>"
                f"{wait_str}"
            )
        else:
            opt_alt = actionable_plan.get("option_alternative")
            opt_str = ""
            if opt_alt and isinstance(opt_alt, dict):
                raw_c = opt_alt.get("contract", "")
                readable_c = opt_alt.get("readable_contract") or format_readable_option_symbol(
                    raw_c,
                    strike=opt_alt.get("strike"),
                    option_type=opt_alt.get("option_type"),
                )
                opt_str = (
                    f"\n🎯 <b>Option Alternative:</b> BUY <b>{readable_c}</b> @ ₹{opt_alt.get('ltp', 0):,.1f} "
                    f"(SL: ₹{opt_alt.get('stop_loss', 0):,.1f} | Tgt: ₹{opt_alt.get('target_1', 0):,.1f})"
                )
            plan_str = (
                f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>{lot_beside_p}\n"
                f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
                f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
                f"• <b>R:R Expectancy:</b> <b>{rr}</b>{lot_str}{no_chase_inline}"
                f"{confluence_str}\n"
                f"• <b>Playbook:</b> <i>{rule}</i>"
                f"{wait_str}"
                f"{opt_str}"
            )
    elif (
        getattr(alert, "exchange", "") == "CDS"
        or getattr(alert, "alert_type", "") == "CURRENCY_BREAKOUT"
    ):
        act = actionable_plan.get("action", "BUY_FUTURES").replace("_", " ")
        inst = actionable_plan.get("contract", f"CDS:{alert.symbol}")
        entry = actionable_plan.get("entry_range", f"₹{alert.ltp:.4f}")
        tgt1 = actionable_plan.get("target", f"₹{getattr(alert, 'target_level', 0):.4f}")
        tgt2 = actionable_plan.get("target_2", "")
        sl = actionable_plan.get("stop_loss", f"₹{getattr(alert, 'stop_loss', 0):.4f}")
        rr = actionable_plan.get("risk_reward", "1:2.2")
        lot = actionable_plan.get("lot_size", 1000)
        lot_beside_p = f" (Lot: {lot})" if lot else ""
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Scale 50% at T1, move SL to entry.")
        no_chase_val = getattr(alert, "no_chase_boundary", None)
        no_chase_inline = ""
        if no_chase_val and float(no_chase_val) > 0:
            comparator = get_no_chase_comparator(alert, actionable_plan, act)
            no_chase_inline = (
                f" | 🛑 <b>No-Chase:</b> <i>{comparator} ₹{float(no_chase_val):.4f}</i>"
            )
        wait_rule = actionable_plan.get("when_to_wait")
        wait_str = ""
        if wait_rule:
            if no_chase_inline and (
                "DO NOT CHASE" in wait_rule.upper() or "NO CHASE" in wait_rule.upper()
            ):
                clean_wait = re.sub(
                    r"^(?:DO NOT CHASE|NO CHASE).*?(?:\.(?!\d)|$)\s*",
                    "",
                    wait_rule,
                    flags=re.IGNORECASE,
                ).strip()
                has_letters = bool(re.search(r"[a-zA-Z]", clean_wait))
                wait_str = f"\n• <b>Discipline:</b> <i>{clean_wait}</i>" if has_letters else ""
            else:
                wait_str = f"\n• <b>Discipline:</b> <i>{wait_rule}</i>"
        plan_str = (
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>{lot_beside_p}\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
            f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b> | Lot: {lot}{no_chase_inline}\n"
            f"• <b>Playbook:</b> <i>{rule}</i>"
            f"{wait_str}"
        )
    elif is_crypto_alert:
        act = actionable_plan.get("action", "BUY_SPOT / LONG").replace("_", " ")
        raw_inst = getattr(alert, "symbol", "BTCUSDT")
        inst = re.sub(r"^CRYPTO:", "", raw_inst, flags=re.IGNORECASE)
        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        entry = actionable_plan.get("entry_range", f"${ltp:,.2f}")
        tgt1 = actionable_plan.get(
            "target", f"${float(getattr(alert, 'target_level', 0.0) or 0.0):,.2f}"
        )
        tgt2 = actionable_plan.get("target_2", "")
        sl = actionable_plan.get(
            "stop_loss", f"${float(getattr(alert, 'stop_loss', 0.0) or 0.0):,.2f}"
        )
        rr = actionable_plan.get("risk_reward", "1:2.5")
        tgt2_str = f" | <b>T2:</b> <code>{tgt2}</code>" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Scale 50% at T1, trail stop on 20-EMA.")
        confluence = actionable_plan.get("setup_confluence") or "SMC Order Block + FVG Reclaim"
        no_chase_val = getattr(alert, "no_chase_boundary", None)
        no_chase_inline = ""
        if no_chase_val and float(no_chase_val) > 0:
            comparator = get_no_chase_comparator(alert, actionable_plan, act)
            no_chase_inline = (
                f" | 🛑 <b>No-Chase:</b> <i>{comparator} ${float(no_chase_val):,.2f}</i>"
            )
        wait_rule = actionable_plan.get("when_to_wait")
        wait_str = ""
        if wait_rule:
            if no_chase_inline and (
                "DO NOT CHASE" in wait_rule.upper() or "NO CHASE" in wait_rule.upper()
            ):
                clean_wait = re.sub(
                    r"^(?:DO NOT CHASE|NO CHASE).*?(?:\.(?!\d)|$)\s*",
                    "",
                    wait_rule,
                    flags=re.IGNORECASE,
                ).strip()
                has_letters = bool(re.search(r"[a-zA-Z]", clean_wait))
                wait_str = f"\n• <b>Discipline:</b> <i>{clean_wait}</i>" if has_letters else ""
            else:
                wait_str = f"\n• <b>Discipline:</b> <i>{wait_rule}</i>"
        plan_str = (
            f"• <b>Action:</b> {act} <b>{inst}</b> @ <code>{entry}</code>\n"
            f"• <b>Invalidation SL:</b> <code>{sl}</code>\n"
            f"• <b>Target 1:</b> <code>{tgt1}</code>{tgt2_str}\n"
            f"• <b>R:R Expectancy:</b> <b>{rr}</b> | 24x7 Continuous Liquidity{no_chase_inline}\n"
            f"• <b>Structure:</b> <i>{confluence}</i>\n"
            f"• <b>Playbook:</b> <i>{rule}</i>"
            f"{wait_str}"
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
                    timeframe=getattr(alert, "time_horizon", "INTRADAY"),
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

                no_chase_val = getattr(alert, "no_chase_boundary", None)
                no_chase_inline = ""
                if no_chase_val and float(no_chase_val) > 0:
                    comparator = get_no_chase_comparator(alert, actionable_plan, action)
                    no_chase_inline = (
                        f" | 🛑 <b>No-Chase:</b> <i>{comparator} ₹{float(no_chase_val):,.1f}</i>"
                    )

                runner_eq_str = ""
                opt_alt = actionable_plan.get("option_alternative") or actionable_plan.get(
                    "option_plan"
                )
                if opt_alt and isinstance(opt_alt, dict):
                    opt_c = opt_alt.get("contract") or opt_alt.get("contract_symbol")
                    if opt_c:
                        opt_c_disp = format_contract_display(opt_c)
                        opt_p = opt_alt.get("ltp") or opt_alt.get("entry_premium")
                        opt_p_str = f" @ ₹{float(opt_p):,.1f}" if opt_p else ""
                        runner_eq_str = f"\n• 🚀 <b>F&O Alternative (High Beta):</b> <code>{opt_c_disp}</code>{opt_p_str}"
                elif tp and getattr(tp, "target_moonshot", 0) and tp.target_moonshot > tp.target_2:
                    runner_eq_str = f"\n• 🚀 <b>Moonshot Runner (+6R+):</b> <code>₹{tp.target_moonshot:,.1f}</code> (Trend Extension)"

                eq_lot = getattr(alert, "lot_size", None)
                if not eq_lot:
                    try:
                        from engine.position_sizer import get_lot_size

                        ls = get_lot_size(getattr(alert, "symbol", ""))
                        if ls and ls > 1:
                            eq_lot = ls
                    except Exception:
                        eq_lot = None
                lot_beside_p = f" (Lot: {eq_lot})" if eq_lot else ""

                plan_str = (
                    f"• <b>Action:</b> {action} @ <code>₹{tp.entry_price:,.1f}</code>{lot_beside_p}\n"
                    f"• <b>Invalidation SL:</b> <code>₹{tp.invalidation_stop:,.1f}</code> ({sl_diff_sign}{tp.stop_distance_pts:,.1f} pts)\n"
                    f"• <b>Target 1:</b> <code>₹{tp.target_1:,.1f}</code> ({t_diff_sign}{tp.t1_distance_pts:,.1f} pts | <b>{tp.rr_t1}:1 R:R</b>)\n"
                    f"• <b>Target 2:</b> <code>₹{tp.target_2:,.1f}</code> ({t_diff_sign}{tp.t2_distance_pts:,.1f} pts | <b>{tp.rr_t2}:1 R:R</b>){overrun_warn}\n"
                    f"• <b>Expectancy:</b> {asym_icon} <b>{tp.asymmetry_verdict}</b>{no_chase_inline}"
                    f"{runner_eq_str}"
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

    now_ts_str = (
        getattr(alert, "triggered_at", None)
        or getattr(alert, "created_at", "")
        or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    raw_headline = getattr(alert, "headline", alert.symbol) or alert.symbol
    clean_hl = strip_provenance_and_icons(raw_headline)

    # Reformat any raw broker contract token embedded in the headline.
    # e.g. "OPTIONS MOMENTUM: HAL202609294800PE @ ₹54.2" → "OPTIONS MOMENTUM: HAL 4800 PE @ ₹54.2"
    def _replace_contract_token(m: re.Match) -> str:
        return format_contract_display(m.group(0))

    clean_hl = re.sub(
        r"\b[A-Z]{2,}(?:\d{8}|\d{2}[A-Z]{3}|\d{2}[1-9OND]\d{2})\d+(?:CE|PE)\b",
        _replace_contract_token,
        clean_hl,
    )
    if (
        not clean_hl
        or len(clean_hl.strip()) <= 3
        or clean_hl.strip().lower() in ("h", "test", "dummy")
    ):
        strike_val = getattr(alert, "strike", None)
        opt_type_val = getattr(alert, "option_type", "") or ""
        sym_val = getattr(alert, "symbol", "ALERT")
        if strike_val and opt_type_val:
            clean_hl = f"{sym_val} {int(strike_val)} {opt_type_val} · Momentum Surge"
        else:
            clean_hl = f"{sym_val} · {getattr(alert, 'alert_type', 'BREAKOUT').replace('_', ' ')}"

    # Clean summary to serve as rationale AFTER the execution levels
    raw_summary = getattr(alert, "summary", "") or ""
    clean_summary = raw_summary
    if plan_str and clean_summary:
        # Strip redundant Entry/SL/Target lists if plan_str already formats them
        clean_summary = re.sub(
            r"\s*(?:Entry|SL|T1|T2|Target)\s*:[^|]+(?:\||$)", "", clean_summary
        ).strip()
        clean_summary = clean_summary.rstrip(" .|")

    if (
        not clean_summary
        or len(clean_summary.strip()) <= 3
        or clean_summary.strip().lower() in ("s", "test", "dummy")
    ):
        metrics = getattr(alert, "metrics", {}) or {}
        scrutiny = metrics.get("scrutiny", {}) if isinstance(metrics, dict) else {}
        logic_conf = scrutiny.get("logic_confirmation") if isinstance(scrutiny, dict) else None
        if logic_conf and len(str(logic_conf).strip()) > 5:
            clean_summary = str(logic_conf).strip()
        else:
            opt_type_val = getattr(alert, "option_type", "")
            if opt_type_val:
                clean_summary = f"Institutional {opt_type_val} order flow and volatility expansion on {getattr(alert, 'symbol', '')}."
            else:
                clean_summary = f"Technical momentum surge and volume expansion on {getattr(alert, 'symbol', '')}."

    reason_line = f"💡 <b>Reason:</b> <i>{clean_summary}</i>" if clean_summary else ""

    is_options_alert = bool(
        getattr(alert, "option_type", None)
        or getattr(alert, "alert_type", "") in ("GAMMA_BLAST", "OPTIONS_MOMENTUM")
    )

    # Build clean headline line
    inst_contract = (
        getattr(alert, "contract_symbol", "")
        or getattr(alert, "contract", "")
        or (inst if (is_options_alert and "inst" in locals()) else "")
    )
    sig_ref = getattr(alert, "signal_ref", None) or build_signal_ref(
        symbol=getattr(alert, "symbol", ""),
        alert_id=str(getattr(alert, "alert_id", getattr(alert, "id", ""))),
        contract=str(inst_contract),
        created_at=now_ts_str,
    )
    if is_options_alert:
        opt_cmp = getattr(alert, "option_premium", None) or getattr(alert, "ltp", None)
        # Check if clean_hl already mentions entry or CMP price to avoid confusing duplicates
        hl_price = None
        try:
            m = re.search(r"@\s*₹?\s*([\d,]+(?:\.\d+)?)", clean_hl)
            if m:
                hl_price = float(m.group(1).replace(",", ""))
        except Exception:
            hl_price = None

        has_matching_hl_price = (
            hl_price is not None and opt_cmp is not None and abs(opt_cmp - hl_price) <= 0.25
        )
        opt_bar = (
            f" | Opt CMP: <b>₹{opt_cmp:,.2f}</b>"
            if (
                opt_cmp
                and opt_cmp > 0
                and f"₹{opt_cmp:.1f}" not in clean_hl
                and f"₹{opt_cmp:,.2f}" not in clean_hl
                and not has_matching_hl_price
                and "@ ₹" not in clean_hl
            )
            else ""
        )
        # Suppress Spot bar in headline if Spot is already detailed in the Action plan line
        has_spot_in_plan = bool(plan_str and "(Spot:" in plan_str)
        spot_bar = (
            f" · Spot: <b>₹{float(str(alert.underlying_spot).replace('₹', '').replace(',', '')):,.2f}</b>"
            if (
                getattr(alert, "underlying_spot", None)
                and "Spot:" not in clean_hl
                and not has_spot_in_plan
            )
            else ""
        )
        # Ensure clean_hl includes full display contract if strike is missing
        if (
            "inst" in locals()
            and inst
            and (
                inst not in clean_hl
                and (not getattr(alert, "strike", None) or str(int(alert.strike)) not in clean_hl)
            )
        ):
            if clean_hl and clean_hl != alert.symbol and "·" not in clean_hl:
                clean_hl = f"{inst} · {clean_hl}"
            else:
                clean_hl = inst

        hl_lot_sz = (
            getattr(alert, "lot_size", None)
            or (actionable_plan.get("lot_size") if isinstance(actionable_plan, dict) else None)
            or (lot_sz if "lot_sz" in locals() else None)
        )
        if not hl_lot_sz:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(getattr(alert, "symbol", "") or inst_contract)
                if ls and ls > 1:
                    hl_lot_sz = ls
            except Exception:
                hl_lot_sz = None

        clean_hl = format_signal_badge_and_lot(
            clean_hl,
            symbol=getattr(alert, "symbol", ""),
            lot_size=hl_lot_sz,
            direction=getattr(alert, "direction", ""),
        )
        hl_line = f"<b>{clean_hl}</b>{spot_bar}{opt_bar}" if clean_hl else f"<b>{alert.symbol}</b>"
    else:
        is_curr = (
            getattr(alert, "exchange", "") == "CDS"
            or getattr(alert, "segment", "") == "CURRENCY"
            or getattr(alert, "alert_type", "") in ("CURRENCY_BREAKOUT", "CURRENCY_BREAKDOWN")
        )
        is_comm = (
            getattr(alert, "exchange", "") == "MCX"
            or getattr(alert, "segment", "") == "COMMODITY"
            or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM"
        )
        if is_crypto:
            spot_bar = (
                f" · Spot CMP: <b>${alert.ltp:,.2f}</b>"
                if (alert.ltp and "CMP:" not in clean_hl)
                else ""
            )
        elif is_curr:
            # Currency pair CMP with 4 decimal places
            spot_bar = (
                f" · Pair CMP: <b>₹{alert.ltp:.4f}</b>"
                if (alert.ltp and f"₹{alert.ltp:.4f}" not in clean_hl and "CMP:" not in clean_hl)
                else ""
            )
        elif is_comm:
            spot_bar = (
                f" · CMP: <b>₹{alert.ltp:,.2f}</b>"
                if (
                    alert.ltp
                    and f"₹{alert.ltp:,.2f}" not in clean_hl
                    and f"₹{alert.ltp:,.1f}" not in clean_hl
                    and "CMP:" not in clean_hl
                )
                else ""
            )
        else:
            spot_bar = (
                f" · Spot CMP: <b>₹{alert.ltp:,.2f}</b>"
                if (
                    alert.ltp
                    and f"₹{alert.ltp}" not in clean_hl
                    and f"₹{alert.ltp:,.1f}" not in clean_hl
                    and f"₹{alert.ltp:,.2f}" not in clean_hl
                    and "Spot CMP:" not in clean_hl
                )
                else ""
            )

        eq_lot_sz = getattr(alert, "lot_size", None) or (
            actionable_plan.get("lot_size") if isinstance(actionable_plan, dict) else None
        )
        if not eq_lot_sz:
            try:
                from engine.position_sizer import get_lot_size

                ls = get_lot_size(getattr(alert, "symbol", "") or inst_contract)
                if ls and ls > 1:
                    eq_lot_sz = ls
            except Exception:
                eq_lot_sz = None

        clean_hl = format_signal_badge_and_lot(
            clean_hl,
            symbol=getattr(alert, "symbol", ""),
            lot_size=eq_lot_sz,
            direction=getattr(alert, "direction", ""),
        )
        hl_line = f"<b>{clean_hl}</b>{spot_bar}" if clean_hl else f"<b>{alert.symbol}</b>"

    # Time Horizon, Setup Style, and Prominent Confidence Score
    horizon_val = getattr(alert, "time_horizon", None) or "INTRADAY"
    setup_style_val = getattr(alert, "setup_style", None) or "MOMENTUM_BREAKOUT"
    horizon_icons = {
        "INTRADAY": "⏱️ INTRADAY (15m–60m)",
        "SWING_SHORT": "⚡ 2–5D SWING",
        "SWING_MID": "📈 1–4W SWING",
        "POSITIONAL": "🏛️ 1–6M POSITIONAL",
    }
    horizon_display = horizon_icons.get(horizon_val, f"⏱️ {horizon_val}")
    conf_val = getattr(alert, "confidence", None)
    if conf_val is None:
        metrics_dict = getattr(alert, "metrics", None)
        if isinstance(metrics_dict, dict):
            conf_val = metrics_dict.get("conviction_score") or metrics_dict.get("confidence")
    conf_badge = f" | 🧠 <b>Confidence:</b> <b>{conf_val or 85}%</b>"
    horizon_line = f"• <b>Horizon:</b> {horizon_display} | <b>Style:</b> <i>{setup_style_val.replace('_', ' ')}</i>{conf_badge}"

    # Order flow / broker depth provenance
    order_flow = getattr(alert, "order_flow_signals", None) or {}
    live_broker = order_flow.get("live_broker_connected", False)
    provenance = order_flow.get("provenance", "")
    obi = order_flow.get("obi_ratio", 0.0)

    # Check segment coverage for connected broker
    from brokers.session import get_data_broker_key

    active_broker_key = (get_data_broker_key() or "").lower()
    exch_upper = str(getattr(alert, "exchange", "") or "").upper()
    is_non_equity_segment = exch_upper in ("MCX", "CDS", "CRYPTO", "BINANCE")
    is_broker_unsupported_segment = is_non_equity_segment and active_broker_key in (
        "mstock",
        "groww",
    )

    if (live_broker and not is_broker_unsupported_segment) or provenance in (
        "LIVE_BROKER_L2",
        "LIVE_BROKER_REST",
        "LIVE_BROKER_FEED",
        "REAL_FEED",
        "LIVE_QUOTE",
    ):
        if obi and abs(float(obi)) > 0:
            depth_badge = f"🟢 <i>L2 Depth (OBI: {obi:+.2f})</i>"
        else:
            depth_badge = "🟢 <i>LIVE BROKER FEED</i>"
    elif is_non_equity_segment and is_broker_unsupported_segment:
        depth_badge = (
            "⚠️ <i>DELAYED FEED (yfinance)</i>"
            if exch_upper in ("MCX", "CDS")
            else "⚡ <i>CRYPTO TICK STREAM</i>"
        )
    elif provenance == "SYNTHETIC_L1" or not live_broker:
        depth_badge = "⚠️ <i>SYNTHETIC L1</i>"
    else:
        depth_badge = f"ℹ️ <i>{provenance}</i>"

    lines = [
        tg_header,
        "━━━━━━━━━━━━━━━━━━━━",
        hl_line,
        horizon_line,
    ]
    if plan_str:
        lines.append(plan_str.strip())
    if reason_line:
        lines.append(reason_line.strip())

    lines.append(
        f"{depth_badge} · 🕒 <b>Timestamp:</b> {now_ts_str}{off_note}\n"
        f"🏷️ <b>Ref:</b> <code>{sig_ref}</code>"
    )

    return "\n".join(lines)


# ── Backward Compatibility Alias ──────────────────────────────
format_auto_alert_telegram = render_auto_alert
