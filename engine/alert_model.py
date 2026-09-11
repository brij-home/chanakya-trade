"""
Core AutoAlert data model and Indian expiry calendar mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_expiry import (
    classify_expiry_type,
    get_expiry_metadata,
    get_next_expiry_opportunity,
)

IST = ZoneInfo("Asia/Kolkata")

INDEX_WEEKLY_EXPIRY_WEEKDAY = {
    "MIDCPNIFTY": 0,  # Monday
    "BANKEX": 0,  # Monday
    "FINNIFTY": 1,  # Tuesday
    "BANKNIFTY": 2,  # Wednesday
    "NIFTY": 3,  # Thursday
    "SENSEX": 4,  # Friday
}


@dataclass
class AutoAlert:
    alert_id: str
    alert_type: (
        str  # GAMMA_BLAST | SQUEEZE_BREAKOUT | CIRCUIT_WARNING | SMC_SWEEP | CONFLUENCE_INFLECTION
    )
    stage: str  # "EARLY_WARNING" | "IGNITED" | "INVALIDATED" | "EXPIRED"
    symbol: str
    exchange: str
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    headline: str
    summary: str
    ltp: float
    trigger_level: float
    target_level: float
    stop_loss: float
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CE" | "PE"
    contract_symbol: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    actionable_plan: dict[str, Any] = field(default_factory=dict)
    confidence: int = 75  # 0 - 100
    created_at: str = ""
    read: bool = False
    is_live: bool = True  # True if generated from real live market data; False if TEST/simulation
    environment: str = "LIVE"  # "LIVE" | "TEST"
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    invalidated_at: Optional[str] = None
    achieved_milestones: list[str] = field(default_factory=list)
    target_status: str = "PENDING"  # "PENDING" | "T1_ACHIEVED" | "T2_ACHIEVED" | "TARGET_ACHIEVED"
    should_trail: bool = False  # Explicit recommendation: whether to trail or not
    trailing_decision: Optional[str] = (
        None  # "BOOK_50_TRAIL_BREAKEVEN" | "TRAIL_DYNAMIC_ATR" | "BOOK_FULL_PROFIT_NO_TRAIL" | "DO_NOT_TRAIL_HOLD_STOP"
    )
    trailing_stop: Optional[float] = None  # Exact rupee level recommended for trailing stop-loss
    trailing_rationale: Optional[str] = None  # Institutional rationale explaining trailing decision
    locked_profit_pts: Optional[float] = None
    locked_profit_pct: Optional[float] = None
    last_trail_alert_time: Optional[float] = None
    is_archived: bool = False
    archived_at: Optional[str] = None
    archive_reason: Optional[str] = None
    expiry_date: Optional[str] = None
    expiry_type: Optional[str] = None  # "WEEKLY" | "MONTHLY"
    underlying_spot: Optional[float] = None
    option_premium: Optional[float] = None
    market_status: str = "SESSION_CLOSED"  # "LIVE" | "PRE_MARKET" | "SESSION_CLOSED"
    lot_size: Optional[int] = None  # Contract market lot size (SEBI 2026 active)
    segment: str = ""  # "FNO" | "EQUITY" | "COMMODITY" | "CURRENCY"
    signal_ref: Optional[str] = None
    r_multiple: Optional[float] = None
    pnl_pct: Optional[float] = None
    updated_at: Optional[str] = None
    triggered_at: Optional[str] = None
    # Immutable first-signal timestamp: set once at insertion, NEVER overwritten on stage upgrades.
    # Used as "Call Given:" anchor in milestone alerts to avoid "0s ago" confusion.
    original_call_time: Optional[str] = None
    in_flight_warning_sent: bool = False
    in_flight_warning_reason: Optional[str] = None
    in_flight_warning_at: Optional[str] = None
    mtf_confluence: Optional[str] = None
    vix_regime: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        if not self.signal_ref:
            try:
                from bot.alert_templates import build_signal_ref
                self.signal_ref = build_signal_ref(
                    symbol=self.symbol,
                    alert_id=self.alert_id,
                    contract=self.contract_symbol or "",
                    created_at=self.created_at,
                )
            except Exception:
                pass
        if not self.segment:
            try:
                from engine.alert_preferences import classify_alert_segment

                self.segment = classify_alert_segment(self)
            except Exception:
                self.segment = "EQUITY"
        if self.lot_size is None:
            if self.metrics and "lot_size" in self.metrics and self.metrics["lot_size"]:
                try:
                    self.lot_size = int(self.metrics["lot_size"])
                except (ValueError, TypeError):
                    pass
            if self.lot_size is None:
                from market.instruments import STANDARD_LOT_SIZES

                clean = (
                    (self.symbol or "")
                    .replace("NSE:", "")
                    .replace("NFO:", "")
                    .replace("BSE:", "")
                    .replace("MCX:", "")
                    .strip()
                    .upper()
                )
                self.lot_size = STANDARD_LOT_SIZES.get(clean)

    @property
    def is_expired(self) -> bool:
        """
        Determines whether a derivative contract or Gamma Blast alert has expired.
        1. Checks explicit expiry_date (15:30 IST on expiry day).
        2. For index options without explicit date, resolves against the weekly expiry calendar.
        3. Gamma blast intraday spikes expire after 24 hours of market time.
        """
        if self.stage == "EXPIRED":
            return True

        # Test and simulation alerts do not expire based on wall-clock time
        if self.environment == "TEST" or not self.is_live or self.alert_id.startswith("test-"):
            return False

        now = datetime.now(IST)

        # 1. Check explicit expiry_date
        if self.expiry_date:
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                try:
                    exp_dt = datetime.strptime(self.expiry_date.strip(), fmt).replace(
                        hour=15, minute=30, second=0, tzinfo=IST
                    )
                    if now >= exp_dt:
                        return True
                    break
                except ValueError:
                    pass

        # 2. Check derivative alerts (options/futures/gamma blast) & Intraday Early Warnings
        created_dt = None
        if self.created_at:
            clean_ts = self.created_at.replace(" IST", "").strip()[:19]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    created_dt = datetime.strptime(clean_ts, fmt).replace(tzinfo=IST)
                    break
                except ValueError:
                    pass

        # 2a. Intraday Session Rollover Invariant:
        # Pre-breakout coiling/early-warning setups belong strictly to their trading session.
        # If created on a prior calendar date (created_dt.date() < now.date()),
        # unignited early warnings expire immediately so yesterday's stale coils never pollute today.
        if self.stage == "EARLY_WARNING" and created_dt and created_dt.date() < now.date():
            return True

        is_deriv = bool(
            self.strike
            or self.option_type
            or self.contract_symbol
            or self.alert_type == "GAMMA_BLAST"
        )

        if is_deriv:
            if created_dt:
                clean_sym = self.symbol.replace("NSE:", "").replace("NFO:", "").strip().upper()
                # Indian index weekly options expiry mapping (only if no explicit expiry date)
                if not self.expiry_date and clean_sym in INDEX_WEEKLY_EXPIRY_WEEKDAY:
                    target_weekday = INDEX_WEEKLY_EXPIRY_WEEKDAY[clean_sym]
                    days_ahead = (target_weekday - created_dt.weekday()) % 7
                    exp_dt = created_dt.replace(hour=15, minute=30, second=0) + timedelta(
                        days=days_ahead
                    )
                    if now >= exp_dt:
                        return True

                # Gamma blast shelf-life: intraday momentum spike expires after 24 hours only if no explicit expiry date
                if self.alert_type == "GAMMA_BLAST" and not self.expiry_date:
                    if (now - created_dt).total_seconds() > 24 * 3600:
                        return True

        return False

    @property
    def is_active(self) -> bool:
        """A trade is active if it is not archived, not invalidated, not expired, and has not completed final target."""
        if self.is_expired:
            return False
        return (
            not self.is_archived
            and not self.is_invalidated
            and self.stage not in ("INVALIDATED", "TARGET_ACHIEVED", "EXPIRED")
            and self.target_status != "TARGET_ACHIEVED"
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = (
            self.invalidated_at
            or self.created_at
            or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        )
        d["is_active"] = self.is_active
        d["is_expired"] = self.is_expired

        # Rich expiry details & next-expiry opportunities
        exp_info = get_expiry_metadata(
            self.expiry_date, self.expiry_type, self.symbol, self.contract_symbol
        )
        d["expiry_details"] = exp_info
        d["expiry_month_name"] = exp_info.get("month_name")
        d["expiry_formatted"] = exp_info.get("formatted")
        d["dte"] = exp_info.get("dte")

        next_opp = get_next_expiry_opportunity(self, exp_info)
        if next_opp:
            d["next_expiry_opportunity"] = next_opp

        return d
