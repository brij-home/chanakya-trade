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

    @classmethod
    def from_alert(
        cls,
        alert: Any,
        milestone_type: str,
        in_market: bool = True,
        timestamp: str = "",
    ) -> MilestoneAlertData:
        ltp = getattr(alert, "ltp", 0.0)
        trailing_stop = getattr(alert, "trailing_stop", None)
        target_level = getattr(alert, "target_level", getattr(alert, "target_price", None))

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
            default_action = "CANCEL PENDING ORDERS & EXIT POSITION"

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

    msg = (
        f"{icon} <b>CHANAKYA BLAST SURGE ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{d.contract}</b>{spot_str}\n"
        f"{exp_line}"
        f"🎯 <b>Action:</b> <b>{action_label}</b>\n"
        f"• <b>Entry Zone:</b> <code>{d.entry_range}</code>\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> ({d.stop_loss_pct})\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{d.target_1:,.2f}</code> ({d.target_1_pct}) — <i>Scale 50% & SL to Cost{be_str}</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{d.target_2:,.2f}</code> ({d.target_2_pct}) — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{d.risk_reward} R:R</b>{no_chase_str}\n"
        f"📊 <b>Order Flow:</b> {d.vol_oi:.1f}x Vol/OI · Imbalance {d.imbalance:.1f}x · Reason: <i>{d.trigger_reason}</i>"
        f"{conv_badge}\n"
        f"💡 <b>Trader Execution Playbook:</b> <i>{d.profit_rule}</i>\n"
        f"⚡ <i>Chanakya Institutional Gamma Desk</i>"
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

    status_badge = (
        "🚀 <b>READY TO EXECUTE</b>" if d.status == "READY" else "🎯 <b>STALK ON RETEST</b>"
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

    msg = (
        f"{status_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{d.symbol}</b> ({d.sector_icon} {d.sector}) · <b>₹{d.ltp:,.2f}</b>\n"
        f"<i>{d.setup_title}</i>\n"
        f"🎯 <b>Action:</b> <b>{d.action}</b> @ <code>{d.entry_range}</code>\n"
        f"• <b>Invalidation SL:</b> <code>₹{d.stop_loss:,.2f}</code> (-{d.risk_pct:.1f}%)\n"
        f"• <b>Target 1 (2R):</b> <code>₹{d.target_1:,.2f}</code> (+{d.t1_pct:.1f}%) — <i>Scale 50% & SL to Breakeven</i>"
        f"{t2_str}{moon_str}\n"
        f"• <b>Risk : Reward:</b> <b>1:{d.risk_reward:.1f} R:R</b>{no_chase_str}\n"
        f"📊 <b>Scores:</b> Strategic: <b>{d.strategic_score}/100</b> | Live Tactical: <b>{d.tactical_score}/100</b> · RVOL: <b>{d.rvol:.1f}x</b>\n"
        f"💡 <b>Catalysts:</b> {cat_str}\n"
        f"⚡ <b>Quick Size / Place Order:</b> <code>{d.quick_command}</code>"
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

    if not in_market:
        header_line = f"🌙 <b>[POST-MARKET EOD WATCHLIST] PRECURSOR RADAR [{seg}]</b>"
        off_note = "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
    else:
        header_line = f"{icon} <b>CHANAKYA HIGH-CONVICTION PRECURSOR RADAR [{seg}]</b>"
        off_note = ""

    msg = (
        f"{header_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
        f"🎯 <b>Action: BUY</b> @ <code>{entry_range}</code> (Ref: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code>\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 50% & SL to Cost</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{t2:,.2f}</code> — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{rr}</b>\n"
        f"🚫 <b>{no_chase}</b>\n"
        f"📊 <b>DNA:</b> {factors_str}\n"
        f"⚡ <i>Chanakya Institutional Momentum Intelligence</i>"
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
        header_line = f"🌙 <b>[POST-MARKET EOD WATCHLIST] ASYMMETRIC OPPORTUNITY [1:{rr} R:R]</b>"
        off_note = "\n\n⏸️ <i>Market is closed. Setup calibrated for tomorrow's opening gameplan.</i>"
    else:
        header_line = f"🎯 <b>{env_tag} CHANAKYA ASYMMETRIC OPPORTUNITY [1:{rr} R:R]</b>"
        off_note = ""

    msg = (
        f"{header_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n"
        f"🎯 <b>Action: BUY</b> @ <code>{entry_range}</code> (Ref: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code> (Risk: ₹{abs(ltp - sl):,.2f})\n"
        f"• <b>Target 1 (+2R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 40% & SL to Cost</i>\n"
        f"• <b>Target 2 (+4R):</b> <code>₹{t2:,.2f}</code> — <i>Scale 40% & Trail</i>{moon_line}\n"
        f"• <b>Risk : Reward:</b> <b>1:{rr} R:R</b>\n"
        f"📊 <b>Confluence:</b> {conf_str}\n"
        f"⚡ <i>Chanakya Low-Risk : High-Reward Radar</i>"
        f"{off_note}"
    )
    return msg


def render_milestone_alert(data: MilestoneAlertData | dict[str, Any], in_market: bool = True) -> str:
    """
    Renders a crisp lifecycle milestone alert: Target 1 Hit, Final Target, Trailing Ratchet, Invalidation.
    Instant clarity on what happened and the exact action required now.
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
        )
    else:
        d = data

    env_tag = normalize_env_tag(d.environment, d.in_market)

    if d.milestone_type == "INVALIDATED":
        return (
            f"⚠️ <b>{env_tag} VIEW INVALIDATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 <b>{d.symbol} ({d.alert_type})</b> is <b>NO LONGER VALID</b>!\n"
            f"🛑 <b>Reason:</b> {d.invalidation_reason or d.rationale or 'Stop-loss or invalidation floor breached'}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CANCEL PENDING ORDERS & CLOSE POSITIONS</code>"
        )

    if d.milestone_type == "TARGET_1":
        ts_val = d.trailing_stop or (d.ltp * 0.998)
        lock_pct = f" (+{d.locked_profit_pct:.1f}% Breakeven Lock)" if d.locked_profit_pct else ""
        return (
            f"🎯 <b>{env_tag} TARGET 1 HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{d.symbol} ({d.alert_type}) — TARGET 1 ACHIEVED</b>\n"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Target 1:</b> ₹{d.target_level or d.ltp:,.2f}\n"
            f"🛡️ <b>Trail Stop:</b> <code>₹{ts_val:,.2f}</code>{lock_pct} (100% risk-free)\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>BOOK 50% PROFIT NOW & HOLD RUNNER</code>"
        )

    if d.milestone_type == "FINAL_TARGET":
        if d.should_trail:
            ts_val = d.trailing_stop or d.ltp
            lock_str = (
                f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct is not None else ""
            )
            return (
                f"🚀 <b>{env_tag} RUNNER EXTENSION</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 <b>{d.symbol} ({d.alert_type}) — INSTITUTIONAL RUNAWAY</b>\n"
                f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Primary Target:</b> ₹{d.target_level or d.ltp:,.2f}\n"
                f"🛡️ <b>Chandelier Trail SL:</b> <code>₹{ts_val:,.2f}</code>{lock_str}\n"
                f"⚡ <b>DECISIVE ACTION:</b> <code>LET RUNNER RIDE (TRAIL SL)</code>"
            )
        return (
            f"🏁 <b>{env_tag} FINAL TARGET ACHIEVED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>{d.symbol} ({d.alert_type}) — FINAL TARGET REACHED</b>\n"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} | <b>Final Target:</b> ₹{d.target_level or d.ltp:,.2f}\n"
            f"⚡ <b>DECISIVE ACTION:</b> <code>CLOSE ALL POSITIONS (BOOK FULL PROFIT)</code>"
        )

    if d.milestone_type == "TRAIL_RATCHET":
        lock_pts = f"+₹{d.locked_profit_pts:,.2f}/sh" if d.locked_profit_pts else ""
        lock_pct = f" (+{d.locked_profit_pct:.1f}% locked)" if d.locked_profit_pct else ""
        lock_str = f"🔒 <b>Guaranteed Profit:</b> {lock_pts}{lock_pct}\n" if (lock_pts or lock_pct) else ""
        return (
            f"📈 <b>{env_tag} TRAILING STOP RATCHET</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>{d.symbol} Trailing Stop Ratcheted Higher!</b>\n"
            f"💰 <b>LTP:</b> ₹{d.ltp:,.2f} · <b>New SL:</b> <code>₹{d.trailing_stop or 0:,.2f}</code>\n"
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
        tg_header = "🧪 <b>[TEST SETUP]</b>"
    elif not in_market:
        tg_header = "🌙 <b>[POST-MARKET EOD WATCHLIST]</b>"
    else:
        if getattr(alert, "exchange", "") == "MCX" or getattr(alert, "alert_type", "") == "COMMODITY_MOMENTUM":
            tg_header = "🛢️ <b>[REAL / LIVE MCX COMMODITY SIGNAL]</b>"
        elif getattr(alert, "exchange", "") == "CDS" or getattr(alert, "alert_type", "") == "CURRENCY_BREAKOUT":
            tg_header = "💱 <b>[REAL / LIVE CURRENCY BREAKOUT]</b>"
        elif getattr(alert, "stage", "") == "EARLY_WARNING" or getattr(alert, "alert_type", "") in (
            "PATTERN_COILING",
            "CIRCUIT_WARNING",
        ):
            tg_header = "⚡ <b>[REAL / LIVE EARLY WARNING — COILING SETUP]</b>"
        elif getattr(alert, "alert_type", "") == "SQUEEZE_BREAKOUT" and getattr(
            alert, "stage", ""
        ) != "IGNITED":
            tg_header = "⚡ <b>[REAL / LIVE EARLY WARNING — SQUEEZE COILING]</b>"
        else:
            tg_header = "🟢 <b>[REAL / LIVE BREAKOUT IGNITED]</b>"

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
            f" (Spot ref: ₹{alert.underlying_spot:,.1f})"
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
            f"\n\n📐 <b>Data-Driven Options Plan (Zero Guesswork):</b>\n"
            f"{exp_line}"
            f"• <b>Action:</b> {act} {inst} @ {entry}{spot_ref}\n"
            f"• <b>Target:</b> {tgt}\n"
            f"• <b>Invalidation SL:</b> {sl}\n"
            f"• <b>R:R Expectancy:</b> {rr}"
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
        tgt2_str = f" | <b>T2:</b> {tgt2}" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Book 50% at T1, trail stop to cost.")

        opt_alt = actionable_plan.get("option_alternative")
        opt_str = ""
        if opt_alt and isinstance(opt_alt, dict):
            opt_str = (
                f"\n🎯 <b>Defined-Risk Option Alternative (Black-76):</b>\n"
                f"• <b>Contract:</b> BUY {opt_alt.get('contract', '')} @ ₹{opt_alt.get('ltp', 0):,.1f}\n"
                f"• <b>Option SL:</b> ₹{opt_alt.get('stop_loss', 0):,.1f} | <b>Target:</b> ₹{opt_alt.get('target_1', 0):,.1f}\n"
                f"• <b>Max Loss Capped:</b> <code>₹{opt_alt.get('max_loss_capped', 0):,.0f}</code> (Defined Risk)\n"
            )

        plan_str = (
            f"\n\n📐 <b>MCX Commodity Plan (Zero Guesswork):</b>\n"
            f"• <b>Action:</b> {act} {inst} @ {entry}\n"
            f"• <b>Target 1:</b> {tgt1}{tgt2_str}\n"
            f"• <b>Invalidation SL:</b> {sl}\n"
            f"• <b>R:R Expectancy:</b> {rr}{lot_str}\n"
            f"• <b>Execution Rule:</b> <i>{rule}</i>"
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
        tgt2_str = f" | <b>T2:</b> {tgt2}" if tgt2 else ""
        rule = actionable_plan.get("profit_rule", "Scale 50% at T1, move SL to entry.")
        plan_str = (
            f"\n\n📐 <b>Macro Currency Plan (Zero Guesswork):</b>\n"
            f"• <b>Action:</b> {act} {inst} @ {entry}\n"
            f"• <b>Target 1:</b> {tgt1}{tgt2_str}\n"
            f"• <b>Invalidation SL:</b> {sl}\n"
            f"• <b>R:R Expectancy:</b> {rr} | Lot: {lot}\n"
            f"• <b>Execution Rule:</b> <i>{rule}</i>"
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
                    f"\n  ⚠️ <i>{tp.session_clock_note}</i>" if tp.session_overrun_risk else ""
                )
                asym_note_str = f"\n  <i>{tp.asymmetry_note}</i>" if not tp.is_asymmetry_viable else ""

                plan_str = (
                    f"\n\n📐 <b>Data-Driven Trade Plan (Zero Guesswork):</b>\n"
                    f"• <b>Action:</b> {action} @ ₹{tp.entry_price:,.1f}\n"
                    f"• <b>Invalidation SL:</b> <code>₹{tp.invalidation_stop:,.1f}</code> ({sl_diff_sign}{tp.stop_distance_pts:,.1f} pts)\n"
                    f"  <i>{tp.sl_rationale}</i>\n"
                    f"• <b>Target 1:</b> <code>₹{tp.target_1:,.1f}</code> ({t_diff_sign}{tp.t1_distance_pts:,.1f} pts | <b>{tp.rr_t1}:1 R:R</b>)\n"
                    f"  ⏱️ <b>ETA T1:</b> {tp.eta_t1_str}\n"
                    f"• <b>Target 2:</b> <code>₹{tp.target_2:,.1f}</code> ({t_diff_sign}{tp.t2_distance_pts:,.1f} pts | <b>{tp.rr_t2}:1 R:R</b>)\n"
                    f"  ⏱️ <b>ETA T2:</b> {tp.eta_t2_str}{overrun_warn}\n"
                    f"• <b>Expectancy:</b> {asym_icon} <b>{tp.asymmetry_verdict}</b>{asym_note_str}"
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
            plan_str = f"\n\n⚡ <b>Trade Plan:</b> {action} @ {entry}\n🎯 <b>Target:</b> {target} | 🛑 <b>SL:</b> {sl}"

    now_ts_str = getattr(alert, "created_at", "") or datetime.now(IST).strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )
    return (
        f"{tg_header}\n"
        f"🚨 <b>{getattr(alert, 'headline', alert.symbol)}</b>\n\n"
        f"{getattr(alert, 'summary', '')}"
        f"{plan_str}\n\n"
        f"📊 <b>Confidence:</b> {getattr(alert, 'confidence', 80)}% | 🕒 <b>Timestamp:</b> {now_ts_str}{off_note}"
    )
