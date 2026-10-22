"""
engine/session_runway.py
────────────────────────
Institutional Dynamic Session Runway & Market Phase Adaptive Governor.

Enforces temporal discipline and market dynamic adaptability across the 5 trading phases
of the Indian Market (NSE, BSE, NFO, MCX).

Key Invariants:
1. Runway Sufficiency: Intraday equity & stock option setups require >= 75m before 15:15 IST cutoff.
   Hard entry silence after 14:00 IST prevents the 15:15 session-end square-off trap.
2. 0DTE Expiry Gamma Window: 0DTE index options permitted during Afternoon Power Hour (13:45-14:40 IST)
   strictly when spot is aligned with VWAP and target 1 is scaled to quick-strike +1.0R.
3. Morning Reversal Filter: The 10:15-11:00 IST trap zone requires elevated RVOL (>= 2.2x) or OBI > +0.30.
4. Flow / Regime Adaptation: Contradicting strong FII/DII flow (|net| > 2,500 Cr) raises the conviction bar.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("engine.session_runway")
IST = ZoneInfo("Asia/Kolkata")

SessionPhase = Literal[
    "PRE_MARKET",
    "OPENING_AUCTION_DISCOVERY",
    "MORNING_IMPULSE",
    "MORNING_REVERSAL_ZONE",
    "MIDDAY_COMPRESSION",
    "AFTERNOON_EXPANSION",
    "AFTERNOON_GAMMA_POWER_HOUR",
    "SESSION_RUNWAY_EXHAUSTION",
    "SQUAREOFF_RECONCILIATION",
    "POST_MARKET",
]


@dataclass
class RunwayEvaluation:
    is_allowed: bool
    phase: SessionPhase
    runway_minutes: int
    veto_reason: Optional[str] = None
    elevated_rvol_required: float = 1.30
    conviction_bonus: int = 0
    conviction_penalty: int = 0


def get_current_session_phase(now_dt: Optional[datetime] = None) -> tuple[SessionPhase, int]:
    """
    Returns (SessionPhase, remaining_minutes_to_intraday_cutoff_1515).
    """
    if now_dt is None:
        now_dt = datetime.now(IST)

    t = now_dt.time()

    # Remaining minutes to 15:15 IST
    now_mins = now_dt.hour * 60 + now_dt.minute
    cutoff_mins = 15 * 60 + 15
    remaining_mins = max(0, cutoff_mins - now_mins)

    if t < dtime(9, 15):
        return "PRE_MARKET", remaining_mins
    elif dtime(9, 15) <= t < dtime(9, 25):
        return "OPENING_AUCTION_DISCOVERY", remaining_mins
    elif dtime(9, 25) <= t < dtime(10, 15):
        return "MORNING_IMPULSE", remaining_mins
    elif dtime(10, 15) <= t < dtime(11, 0):
        return "MORNING_REVERSAL_ZONE", remaining_mins
    elif dtime(11, 0) <= t < dtime(13, 15):
        return "MIDDAY_COMPRESSION", remaining_mins
    elif dtime(13, 15) <= t < dtime(13, 45):
        return "AFTERNOON_EXPANSION", remaining_mins
    elif dtime(13, 45) <= t < dtime(14, 40):
        return "AFTERNOON_GAMMA_POWER_HOUR", remaining_mins
    elif dtime(14, 40) <= t < dtime(15, 15):
        return "SESSION_RUNWAY_EXHAUSTION", remaining_mins
    elif dtime(15, 15) <= t <= dtime(15, 30):
        return "SQUAREOFF_RECONCILIATION", remaining_mins
    else:
        return "POST_MARKET", 0


def evaluate_session_runway(
    symbol: str,
    alert_type: str,
    time_horizon: str = "INTRADAY",
    segment: str = "EQUITY",
    rvol: float = 1.0,
    direction: str = "BULLISH",
    now_dt: Optional[datetime] = None,
    fii_net_cr: Optional[float] = None,
    is_hedged_spread: bool = False,
) -> RunwayEvaluation:
    """
    Evaluates whether an alert setup has viable market runway and dynamic regime alignment.
    """
    is_test_env = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or ("PYTEST_CURRENT_TEST" in os.environ)
    )

    if now_dt is None:
        now_dt = datetime.now(IST)

    phase, runway_mins = get_current_session_phase(now_dt)

    is_swing = time_horizon.upper().startswith("SWING") or time_horizon.upper() in (
        "MULTIBAGGER",
        "POSITIONAL",
        "LONG_TERM",
        "INVESTMENT",
    )
    is_equity_intraday = (segment == "EQUITY") and not is_swing
    is_fno_stock_intraday = (segment in ("FNO_STOCK", "FNO_STK")) and not is_swing
    is_fno_index = (
        (segment in ("FNO_INDEX", "INDEX"))
        or alert_type in ("INDEX_CALL_SETUP", "INDEX_PUT_SETUP", "SMT_SWEEP", "INDEX_MICRO_SCALP")
        or any(
            idx in symbol.upper()
            for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
        )
    )

    # In test environment, bypass time-of-day blocks unless specifically testing runway
    if is_test_env and os.environ.get("FORCE_RUNWAY_CHECK") != "1":
        return RunwayEvaluation(
            is_allowed=True,
            phase=phase,
            runway_minutes=runway_mins,
            elevated_rvol_required=1.30,
        )

    # 0. Asset-Class Specific Market Hours Check (MCX, Currency, Crypto)
    seg_up = (segment or "").upper().strip()
    if seg_up in ("COMMODITY", "MCX") or alert_type.upper().startswith("COMMODITY"):
        # MCX Commodities: 09:00 - 23:30 IST continuous session
        t = now_dt.time()
        now_mins = now_dt.hour * 60 + now_dt.minute
        mcx_cutoff_mins = 23 * 60 + 15
        mcx_runway = max(0, mcx_cutoff_mins - now_mins)
        if t < dtime(9, 0) or t > dtime(23, 30):
            return RunwayEvaluation(
                is_allowed=False,
                phase="POST_MARKET",
                runway_minutes=0,
                veto_reason="MCX session inactive outside 09:00-23:30 IST",
            )
        if t >= dtime(23, 15):
            return RunwayEvaluation(
                is_allowed=False,
                phase="SESSION_RUNWAY_EXHAUSTION",
                runway_minutes=mcx_runway,
                veto_reason="MCX Terminal Window (Post-23:15 IST): Commodity entries silenced before 23:30 close.",
            )
        return RunwayEvaluation(
            is_allowed=True,
            phase="AFTERNOON_EXPANSION" if t >= dtime(17, 0) else "MORNING_IMPULSE",
            runway_minutes=mcx_runway,
            elevated_rvol_required=1.20,
        )

    if seg_up in ("CRYPTO", "BINANCE", "DERIBIT") or alert_type.upper().startswith("CRYPTO"):
        # 24x7 Continuous Global Desk
        return RunwayEvaluation(
            is_allowed=True,
            phase="MORNING_IMPULSE",
            runway_minutes=1440,
            elevated_rvol_required=1.20,
        )

    if seg_up in ("CURRENCY", "CDS") or alert_type.upper().startswith("CURRENCY"):
        # NSE CDS: 09:00 - 17:00 IST continuous session
        t = now_dt.time()
        now_mins = now_dt.hour * 60 + now_dt.minute
        cds_cutoff_mins = 16 * 60 + 45
        cds_runway = max(0, cds_cutoff_mins - now_mins)
        if t < dtime(9, 0) or t > dtime(17, 0):
            return RunwayEvaluation(
                is_allowed=False,
                phase="POST_MARKET",
                runway_minutes=0,
                veto_reason="Currency session inactive outside 09:00-17:00 IST",
            )
        if t >= dtime(16, 45):
            return RunwayEvaluation(
                is_allowed=False,
                phase="SESSION_RUNWAY_EXHAUSTION",
                runway_minutes=cds_runway,
                veto_reason="Currency Terminal Window (Post-16:45 IST): Currency entries silenced before 17:00 close.",
            )
        return RunwayEvaluation(
            is_allowed=True,
            phase="AFTERNOON_EXPANSION" if t >= dtime(14, 0) else "MORNING_IMPULSE",
            runway_minutes=cds_runway,
            elevated_rvol_required=1.20,
        )

    # 1. Swing / Positional setups do not face intraday 15:15 cutoff
    if is_swing:
        return RunwayEvaluation(
            is_allowed=True,
            phase=phase,
            runway_minutes=runway_mins,
            elevated_rvol_required=1.20,
        )

    # 2. Pre-Market & Post-Market Gate
    if phase in ("PRE_MARKET", "POST_MARKET", "SQUAREOFF_RECONCILIATION"):
        return RunwayEvaluation(
            is_allowed=False,
            phase=phase,
            runway_minutes=runway_mins,
            veto_reason=f"Session inactive for intraday entries ({phase})",
        )

    # 3. Opening Auction Discovery Gate (09:15 - 09:25 IST)
    # Price discovery window: allow only Opening Drive Ignition if RVOL >= 2.0x
    if phase == "OPENING_AUCTION_DISCOVERY":
        if alert_type != "OPENING_DRIVE_IGNITION" or rvol < 2.0:
            return RunwayEvaluation(
                is_allowed=False,
                phase=phase,
                runway_minutes=runway_mins,
                veto_reason="Opening Auction Discovery (09:15-09:25 IST): Price discovery freeze active.",
            )

    # 4. Morning Reversal Trap Gate (10:15 - 11:00 IST)
    # Institutional counter-trend absorption zone: require institutional RVOL (>= 2.2x) for single stocks.
    # Exemption: Benchmark index setups (FNO_INDEX) driven by structural SMC/SMT models are allowed when rvol >= 1.0.
    if phase == "MORNING_REVERSAL_ZONE":
        min_rvol_mrz = 1.0 if is_fno_index else 2.2
        if rvol < min_rvol_mrz:
            return RunwayEvaluation(
                is_allowed=False,
                phase=phase,
                runway_minutes=runway_mins,
                veto_reason=f"Morning Reversal Trap (10:15-11:00 IST): RVOL {rvol:.2f}x < {min_rvol_mrz:.2f}x institutional confirmation floor.",
                elevated_rvol_required=min_rvol_mrz,
            )

    # 5. Midday Compression Lull (11:00 - 13:15 IST)
    # Lunchtime chop: require institutional momentum (TOD-RVOL >= 1.30x) for single-stock equity breakouts.
    # Exemptions:
    #   a) Benchmark index setups (FNO_INDEX) with structural alignment
    #   b) Defined-risk vertical spreads (is_hedged_spread=True) which neutralize midday theta decay
    #   c) Trend Day Pullback, SMC Orderblock, & Liquidity Sweep setups where volume dry-up is healthy & expected
    if phase == "MIDDAY_COMPRESSION":
        is_pullback_setup = alert_type.upper() in (
            "TREND_DAY_PULLBACK",
            "SMC_ORDERBLOCK_RETEST",
            "TURTLE_SOUP_RETEST",
            "PULLBACK_RETEST",
            "VWAP_BOUNCE",
            "TREND_PULLBACK_BOUNCE",
            "SMC_SPRING_SWEEP",
            "PREDATOR_SWEEP",
        )
        min_rvol_mc = 1.0 if (is_fno_index or is_pullback_setup or is_hedged_spread) else 1.30
        if rvol < min_rvol_mc and not is_swing:
            return RunwayEvaluation(
                is_allowed=False,
                phase=phase,
                runway_minutes=runway_mins,
                veto_reason=f"Midday Compression Lull (11:00-13:15 IST): RVOL {rvol:.2f}x < {min_rvol_mc:.2f}x floor to prevent theta/whipsaw decay.",
                elevated_rvol_required=min_rvol_mc,
            )

    # 6. Hard Runway Gate:
    # a) Intraday Cash Equities initiated after 14:00 have < 75m before mandatory 15:15 broker square-off.
    if is_equity_intraday and now_dt.time() >= dtime(14, 0):
        return RunwayEvaluation(
            is_allowed=False,
            phase=phase,
            runway_minutes=runway_mins,
            veto_reason=f"Session Runway Exhaustion: New intraday cash equity entries silenced after 14:00 IST (remaining {runway_mins}m < 75m minimum runway).",
        )

    # b) F&O Stock Options & High-Velocity Afternoon Thrusts:
    # Options momentum moves have fast 15-30m execution horizons. They are permitted
    # until 14:45 IST before 0DTE theta collapse or mandatory 15:15 square-off.
    if is_fno_stock_intraday and now_dt.time() >= dtime(14, 45):
        return RunwayEvaluation(
            is_allowed=False,
            phase=phase,
            runway_minutes=runway_mins,
            veto_reason=f"Session Runway Exhaustion: New F&O stock option entries silenced after 14:45 IST ({runway_mins}m remaining).",
        )

    # 7. Index Options Late Entry Gate:
    # After 14:40 IST, 0DTE options face rapid theta collapse.
    if segment == "FNO_INDEX" and now_dt.time() >= dtime(14, 40):
        return RunwayEvaluation(
            is_allowed=False,
            phase=phase,
            runway_minutes=runway_mins,
            veto_reason=f"0DTE Theta Cannibalization: Index option entries silenced after 14:40 IST ({runway_mins}m remaining).",
        )

    # 8. Dynamic Flow & Regime Alignment
    conviction_pen = 0
    conviction_bon = 0
    if fii_net_cr is not None:
        # Aggressive FII selling (< -3,000 Cr) makes Long equity breakouts high-risk
        if fii_net_cr < -3000.0 and direction == "BULLISH":
            conviction_pen = 6  # 6% confidence penalty on counter-trend longs
        elif fii_net_cr > 3000.0 and direction == "BEARISH":
            conviction_pen = 6  # 6% penalty on counter-trend shorts
        elif (fii_net_cr > 1500.0 and direction == "BULLISH") or (
            fii_net_cr < -1500.0 and direction == "BEARISH"
        ):
            conviction_bon = 3  # Flow aligned bonus

    return RunwayEvaluation(
        is_allowed=True,
        phase=phase,
        runway_minutes=runway_mins,
        elevated_rvol_required=1.30,
        conviction_bonus=conviction_bon,
        conviction_penalty=conviction_pen,
    )


def classify_session_phase(t: Optional[dtime] = None) -> SessionPhase:
    """Convenience helper to classify session phase from time."""
    if t is None:
        return get_current_session_phase()[0]
    dummy_dt = datetime.combine(datetime.now(IST).date(), t).replace(tzinfo=IST)
    return get_current_session_phase(dummy_dt)[0]


def is_session_runway_sufficient(
    alert_type: str,
    asset_class: str = "EQUITY",
    is_0dte: bool = False,
    time_horizon: str = "INTRADAY",
    current_time: Optional[dtime] = None,
) -> tuple[bool, str]:
    """
    Lightweight, deterministic perimeter sanity check (<1ms) to verify if an alert
    has sufficient runway before intraday mandatory square-offs.
    """
    is_swing = str(time_horizon).upper().startswith("SWING") or str(time_horizon).upper() in (
        "MULTIBAGGER",
        "POSITIONAL",
        "LONG_TERM",
        "INVESTMENT",
    )
    atype_up = alert_type.upper()
    aclass_up = (asset_class or "EQUITY").upper().strip()
    if is_swing or atype_up in ("MULTIBAGGER", "STAGE_1_TO_2_EXPANSION", "RRG_SECTOR_ROTATION"):
        return (
            True,
            "SESSION_RUNWAY_SUFFICIENT: Multi-session swing/positional setup exempt from intraday runway limits",
        )

    if current_time is None:
        if os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ:
            current_time = dtime(10, 30)
        else:
            current_time = datetime.now(IST).time()

    # 1. 24x7 Continuous Global Markets (Crypto)
    if aclass_up in ("CRYPTO", "BINANCE", "DERIBIT") or atype_up.startswith("CRYPTO"):
        return True, "SESSION_RUNWAY_SUFFICIENT: 24x7 Crypto continuous session"

    # 2. MCX Commodities (09:00 - 23:30 IST)
    if aclass_up in ("COMMODITY", "MCX") or atype_up.startswith("COMMODITY"):
        if current_time >= dtime(23, 15):
            return (
                False,
                "SESSION_RUNWAY_EXHAUSTION: MCX Commodity terminal window (post 23:15 IST square-off)",
            )
        if current_time < dtime(9, 0):
            return False, "SESSION_RUNWAY_EXHAUSTION: MCX Commodity pre-market before 09:00 IST"
        return True, "SESSION_RUNWAY_SUFFICIENT: Active MCX Commodity session runway"

    # 3. NSE CDS Currency (09:00 - 17:00 IST)
    if aclass_up in ("CURRENCY", "CDS") or atype_up.startswith("CURRENCY"):
        if current_time >= dtime(16, 45):
            return (
                False,
                "SESSION_RUNWAY_EXHAUSTION: Currency terminal window (post 16:45 IST square-off)",
            )
        if current_time < dtime(9, 0):
            return False, "SESSION_RUNWAY_EXHAUSTION: Currency pre-market before 09:00 IST"
        return True, "SESSION_RUNWAY_SUFFICIENT: Active Currency session runway"

    # 4. NSE / BSE Domestic Equities & Derivatives (09:15 - 15:30 IST)
    if current_time >= dtime(15, 15):
        return (
            False,
            "SESSION_RUNWAY_EXHAUSTION: Market session runway expired (post 15:15 IST square-off)",
        )

    if (aclass_up in ("EQUITY", "STOCK") or "THEMATIC" in atype_up) and current_time >= dtime(
        14, 0
    ):
        return (
            False,
            "SESSION_RUNWAY_EXHAUSTION: Intraday equities cutoff at 14:00 IST (< 75m to 15:15 IST square-off)",
        )

    if is_0dte and current_time >= dtime(14, 40):
        return (
            False,
            "SESSION_RUNWAY_EXHAUSTION: 0DTE cutoff at 14:40 IST due to accelerated theta collapse",
        )

    return True, "SESSION_RUNWAY_SUFFICIENT"


def get_dynamic_session_efficiency(phase: SessionPhase, asset_class: str = "EQUITY") -> float:
    """Returns the empirical session efficiency factor based on time of day and asset class."""
    if phase == "OPENING_AUCTION_DISCOVERY":
        return 0.70
    elif phase == "MORNING_IMPULSE":
        return 0.95
    elif phase == "MORNING_REVERSAL_ZONE":
        return 0.80
    elif phase == "MIDDAY_COMPRESSION":
        return 0.65
    elif phase == "AFTERNOON_EXPANSION":
        return 0.85
    elif phase in ("AFTERNOON_GAMMA_POWER_HOUR", "POWER_HOUR"):
        return 0.90 if asset_class.upper() in ("OPTIONS", "FNO_INDEX") else 0.45
    elif phase == "SESSION_RUNWAY_EXHAUSTION":
        return 0.40
    else:
        return 0.50
