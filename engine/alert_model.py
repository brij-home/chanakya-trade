"""
Core AutoAlert data model and Indian expiry calendar mapping.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from zoneinfo import ZoneInfo

from engine.alert_expiry import (
    get_expiry_metadata,
    get_next_expiry_opportunity,
)

IST = ZoneInfo("Asia/Kolkata")

# ── Interception Pipeline Stages ───────────────────────────────────────────
STAGE_STALK = "STALK"  # Radar tracking & coiling base identified
STAGE_PRIMED = "PRIMED"  # High-frequency surveillance (within ±0.35% of trigger)
STAGE_EARLY_WARNING = "EARLY_WARNING"  # Backward-compatible early warning
STAGE_IGNITED = "IGNITED"  # Trigger level crossed with micro-confirmation
STAGE_INVALIDATED = "INVALIDATED"  # Stop-loss breached or setup structure broken
STAGE_EXPIRED = "EXPIRED"  # Session or TTL expired
STAGE_COMPLETED = "COMPLETED"  # Final profit targets or runner exited

INDEX_WEEKLY_EXPIRY_WEEKDAY = {
    "MIDCPNIFTY": 0,  # Monday
    "BANKEX": 0,  # Monday
    "FINNIFTY": 1,  # Tuesday
    "BANKNIFTY": 2,  # Wednesday
    "NIFTY": 3,  # Thursday
    "SENSEX": 4,  # Friday
}


@dataclass
class ActionableBlueprint:
    """
    Institutional Single Source of Truth (SSOT) Actionable Blueprint (Invariants 12 & 20).
    Every trade setup, radar candidate, or alert must provide this complete actionable contract:
    Exact Entry Zone, Invalidation Stop-Loss, Target 1 (+2R Scale 50% & SL to Breakeven),
    Target 2 (+4R Extension), Runner (+6R+), R:R >= 1:3.0, and explicit NO CHASE boundary.
    """

    action: str  # "BUY" | "SELL" | "BUY_CALL" | "BUY_PUT" | "BEAR_PUT_SPREAD" | "BULL_CALL_SPREAD"
    entry_range: str  # e.g. "₹2,450.0 – ₹2,470.0"
    trigger_level: float
    invalidation_stop: float
    target_1: float  # +2R Scale 50% & SL to Breakeven
    target_2: float  # +4R Extension
    runner_target: Optional[float] = None  # +6R Runner
    risk_reward: str = "1:3.0"  # Minimum 1:3.0 per Invariant 12
    no_chase_boundary: Optional[float] = None
    execution_style: str = (
        "LIMIT_ON_PULLBACK"  # "LIMIT_ON_PULLBACK" | "BREAKOUT_STOP" | "DEFINED_RISK_SPREAD"
    )
    lot_size: int = 1
    when_to_buy: str = ""
    when_to_wait: str = ""
    profit_rule: str = ""
    segment: str = "EQUITY"
    contract: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry_date: Optional[str] = None
    hedged_spread: Optional[dict[str, Any]] = None
    extra_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializes blueprint to a dictionary with complete backward compatibility."""
        curr = "$" if self.segment == "CRYPTO" else "₹"
        d = {
            "action": self.action,
            "entry_range": self.entry_range,
            "trigger_level": self.trigger_level,
            "stop_loss": f"{curr}{self.invalidation_stop:,.2f}",
            "invalidation_stop": self.invalidation_stop,
            "initial_invalidation_stop": self.invalidation_stop,
            "target": f"{curr}{self.target_1:,.2f}",
            "target_1": f"{curr}{self.target_1:,.2f}",
            "target_2": f"{curr}{self.target_2:,.2f}",
            "runner_target": f"{curr}{self.runner_target:,.2f}" if self.runner_target else None,
            "risk_reward": self.risk_reward,
            "no_chase_boundary": self.no_chase_boundary,
            "execution_style_mandate": self.execution_style,
            "lot_size": self.lot_size,
            "when_to_buy": self.when_to_buy,
            "when_to_wait": self.when_to_wait,
            "profit_rule": self.profit_rule,
            "segment": self.segment,
            "contract": self.contract,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry_date": self.expiry_date,
            "hedged_spread": self.hedged_spread,
        }
        if self.extra_details:
            d.update(self.extra_details)
        return d


@dataclass
class AutoAlert:
    alert_id: str
    alert_type: (
        str  # GAMMA_BLAST | SQUEEZE_BREAKOUT | CIRCUIT_WARNING | SMC_SWEEP | CONFLUENCE_INFLECTION
    )
    stage: str  # "STALK" | "PRIMED" | "EARLY_WARNING" | "IGNITED" | "INVALIDATED" | "EXPIRED"
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
    derivative_type: Optional[str] = None  # "OPT" | "FUT"
    option_stop_loss: Optional[float] = None
    option_target_level: Optional[float] = None
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
    time_horizon: str = "INTRADAY"  # "SCALP" | "INTRADAY" | "SWING_SHORT" | "SWING_MID" | "LONG_TERM" | "POSITIONAL" | "MULTIBAGGER" | "ROLLING_24H"
    eta_label: Optional[str] = None
    setup_style: str = "CONTINUATION"  # "CONTINUATION" | "REVERSAL"
    entry_type: str = "LIMIT_ON_PULLBACK"  # "LIMIT_ON_PULLBACK" | "BREAKOUT_STOP" | "MARKET_NOW"
    anchored_levels: dict[str, float] = field(default_factory=dict)
    order_flow_signals: dict[str, Any] = field(default_factory=dict)
    no_chase_boundary: Optional[float] = None
    telegram_dispatched: bool = False
    dispatched_channels: list[str] = field(default_factory=list)
    telegram_suppression_reason: Optional[str] = None
    telegram_message_id: Optional[int] = None
    telegram_root_message_id: Optional[int] = None
    trace_id: Optional[str] = None
    quant_snapshot: Optional[dict[str, Any]] = None
    ttl_seconds: Optional[int] = None
    liquidity_status: Optional[str] = (
        None  # "OPTIMAL" | "MODERATE" | "WIDE_SPREAD_CAUTION" | "ILLIQUID"
    )
    bid_ask_spread_pct: Optional[float] = None
    strike_roll_recommendation: Optional[dict[str, Any]] = None
    initial_stop_loss: Optional[float] = None
    initial_entry_premium: Optional[float] = None
    update_count: int = 0
    telegram_update_count: int = 0
    update_number: Optional[int] = None
    audit_trail: list[dict[str, Any]] = field(default_factory=list)
    confluence_alignment: Optional[str] = None  # "TRIPLE_HORIZON" | "DUAL_HORIZON"
    stagnation_warning: Optional[str] = None
    physical_delivery_risk: bool = False
    premarket_gap_risk: Optional[str] = None  # "GAP_OVER_SL" | "GAP_NO_CHASE"
    details: dict[str, Any] = field(default_factory=dict)

    def record_audit(
        self,
        event_type: str,
        message: str,
        actor: str = "ENGINE",
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Records an immutable audit event in the alert's chronological trail."""
        evt = {
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "event_type": event_type,
            "message": message,
            "actor": actor,
            "stage": self.stage,
            "ltp": self.ltp,
            "trace_id": self.trace_id,
            "details": details or {},
        }
        if self.audit_trail is None:
            self.audit_trail = []
        self.audit_trail.append(evt)
        if len(self.audit_trail) > 50:
            self.audit_trail = self.audit_trail[-50:]
        return evt

    def __post_init__(self) -> None:
        if self.initial_stop_loss is None:
            if (
                self.actionable_plan
                and isinstance(self.actionable_plan.get("option_plan"), dict)
                and self.actionable_plan["option_plan"].get("sl_premium")
            ):
                try:
                    self.initial_stop_loss = float(
                        self.actionable_plan["option_plan"]["sl_premium"]
                    )
                except (ValueError, TypeError):
                    pass
            elif self.actionable_plan and self.actionable_plan.get("invalidation_stop"):
                try:
                    self.initial_stop_loss = float(self.actionable_plan["invalidation_stop"])
                except (ValueError, TypeError):
                    pass
            elif self.stop_loss is not None and self.stop_loss > 0:
                self.initial_stop_loss = float(self.stop_loss)

        if self.initial_entry_premium is None:
            if (
                self.actionable_plan
                and isinstance(self.actionable_plan.get("option_plan"), dict)
                and self.actionable_plan["option_plan"].get("entry_premium")
            ):
                try:
                    self.initial_entry_premium = float(
                        self.actionable_plan["option_plan"]["entry_premium"]
                    )
                except (ValueError, TypeError):
                    pass
            elif self.option_premium is not None and self.option_premium > 0:
                self.initial_entry_premium = float(self.option_premium)
            elif (self.strike or self.option_type) and self.trigger_level > 0:
                self.initial_entry_premium = float(self.trigger_level)

        if not self.created_at:
            self.created_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        if not self.trace_id:
            try:
                date_compact = (
                    self.created_at[:10]
                    if self.created_at
                    else datetime.now(IST).strftime("%Y-%m-%d")
                ).replace("-", "")
                sym_clean = (
                    self.symbol.replace("NSE:", "")
                    .replace("BSE:", "")
                    .replace("MCX:", "")
                    .strip()
                    .upper()
                )
                type_short = (self.alert_type[:4] if self.alert_type else "ALRT").upper()
                id_suffix = self.alert_id[-4:].upper() if len(self.alert_id) >= 4 else "0001"
                self.trace_id = f"TRC-{date_compact}-{self.exchange or 'NSE'}-{sym_clean}-{type_short}-{id_suffix}"
            except Exception:
                self.trace_id = f"TRC-{self.alert_id}"

        if not self.audit_trail:
            self.record_audit(
                event_type="INITIALIZED",
                message=f"Alert {self.alert_id} initialized with stage {self.stage} (confidence: {self.confidence}%)",
                actor="ALERT_FACTORY",
                details={
                    "confidence": self.confidence,
                    "trigger_level": self.trigger_level,
                    "stop_loss": self.stop_loss,
                    "target_level": self.target_level,
                },
            )
        if not self.signal_ref:
            try:
                from bot.alert_templates import build_signal_ref

                contract_val = self.contract_symbol
                if not contract_val and self.strike and self.option_type:
                    contract_val = f"{self.symbol} {int(self.strike)} {self.option_type}".strip()
                self.signal_ref = build_signal_ref(
                    symbol=self.symbol,
                    alert_id=self.alert_id,
                    contract=contract_val or "",
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
            if (
                self.lot_size is None
                and self.actionable_plan
                and "lot_size" in self.actionable_plan
                and self.actionable_plan["lot_size"]
            ):
                try:
                    self.lot_size = int(self.actionable_plan["lot_size"])
                except (ValueError, TypeError):
                    pass
            if self.lot_size is None:
                try:
                    from engine.position_sizer import get_lot_size

                    ls = get_lot_size(self.contract_symbol or self.symbol)
                    if ls and ls > 1:
                        self.lot_size = ls
                except Exception:
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

        # Auto-resolve expiry_date and expiry_type if not provided
        if not self.expiry_date:
            plan_opt = (
                self.actionable_plan.get("option_plan")
                if isinstance(self.actionable_plan, dict)
                else {}
            ) or {}
            plan_dict = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
            eff_exp = (
                plan_opt.get("expiry_date")
                or plan_opt.get("expiry")
                or plan_dict.get("expiry_date")
                or plan_dict.get("expiry")
            )
            eff_contract = (
                self.contract_symbol or plan_opt.get("contract_symbol") or plan_dict.get("contract")
            )
            if eff_exp:
                self.expiry_date = str(eff_exp)
            elif eff_contract:
                from engine.alert_expiry import get_expiry_metadata

                exp_info = get_expiry_metadata(None, self.expiry_type, self.symbol, eff_contract)
                if exp_info.get("raw_date"):
                    self.expiry_date = exp_info["raw_date"]
                    if not self.expiry_type:
                        self.expiry_type = "WEEKLY" if exp_info.get("is_weekly") else "MONTHLY"

        if not self.expiry_type and self.expiry_date:
            from engine.alert_expiry import classify_expiry_type

            self.expiry_type = classify_expiry_type(self.expiry_date, self.symbol)

        # Auto-infer horizon if default
        if self.time_horizon == "INTRADAY":
            atype = (self.alert_type or "").upper()
            if atype == "MULTIBAGGER":
                self.time_horizon = "MULTIBAGGER"
            elif atype == "STAGE_1_TO_2_EXPANSION":
                text = f"{self.headline or ''} {self.summary or ''} {self.alert_id or ''}".upper()
                if "MULTIBAGGER" in text:
                    self.time_horizon = "MULTIBAGGER"
                else:
                    self.time_horizon = "POSITIONAL"
            elif atype in (
                "SQUEEZE_BREAKOUT",
                "SQUEEZE_BREAKDOWN",
                "VCP_PIVOT_BREAKOUT",
                "RRG_SECTOR_ROTATION",
            ):
                self.time_horizon = "SWING_MID"
            elif atype == "ASYMMETRIC_OPPORTUNITY":
                setup_action = str((self.actionable_plan or {}).get("action", "")).upper()
                if "POCKET_PIVOT" in setup_action:
                    self.time_horizon = "SWING_MID"
                elif "0DTE" in setup_action or "INTRADAY" in setup_action:
                    self.time_horizon = "INTRADAY"
                else:
                    self.time_horizon = "SWING_SHORT"
            elif atype in ("CIRCUIT_WARNING", "PATTERN_COILING", "PRECURSOR_RADAR"):
                self.time_horizon = "SWING_SHORT"
            elif (
                "CRYPTO" in atype
                or (self.exchange or "").upper() in ("CRYPTO", "BINANCE", "DERIBIT")
                or (getattr(self, "segment", "") or "").upper() == "CRYPTO"
            ):
                self.time_horizon = "ROLLING_24H"
            elif atype in ("OPTIONS_MOMENTUM", "GAMMA_BLAST") and (
                "SCALP" in (self.headline or "").upper()
                or "SCALP" in (self.summary or "").upper()
                or "0DTE" in (self.headline or "").upper()
            ):
                self.time_horizon = "SCALP"
            elif atype in ("INTRADAY_SCALP_ONLY", "FAST_SCALP"):
                self.time_horizon = "SCALP"
            elif atype in (
                "GAMMA_BLAST",
                "INTRADAY_SPARK",
                "INTRADAY_BREAKDOWN_SPARK",
                "INDEX_CONTAGION",
            ):
                self.time_horizon = "INTRADAY"

        # Auto-derive or sanitize ETA label
        exch = (self.exchange or "NSE").upper()
        seg = (getattr(self, "segment", "") or "").upper()
        sym_u = (self.symbol or "").upper()
        is_crypto = (
            exch in ("CRYPTO", "BINANCE", "DERIBIT", "COINBASE")
            or seg == "CRYPTO"
            or sym_u.startswith("CRYPTO:")
            or sym_u.endswith("USDT")
            or sym_u.endswith("USDC")
            or sym_u.endswith("BTC")
        )
        if is_crypto and (not self.eta_label or "15:15" in str(self.eta_label)):
            self.eta_label = "24h Rolling"
        elif not self.eta_label:
            th = (self.time_horizon or "INTRADAY").upper()
            if th in ("SCALP", "INTRADAY_SCALP_ONLY"):
                self.eta_label = "15–45m Scalp"
            elif th == "INTRADAY":
                if exch == "MCX":
                    self.eta_label = "Today 23:15 IST"
                else:
                    self.eta_label = "Today 15:15 IST"
            elif th == "SWING_SHORT":
                if self.expiry_date and self.segment in ("FNO", "OPTIONS"):
                    self.eta_label = f"2–5 Sessions ({self.expiry_type or 'Weekly'} Exp)"
                else:
                    self.eta_label = "2–5 Sessions"
            elif th == "SWING_MID":
                if self.expiry_date and self.segment in ("FNO", "OPTIONS"):
                    self.eta_label = f"1–4 Weeks ({self.expiry_type or 'Monthly'} Exp)"
                else:
                    self.eta_label = "1–4 Weeks"
            elif th in ("LONG_TERM", "POSITIONAL"):
                self.eta_label = "1–6 Months"
            elif th == "MULTIBAGGER":
                self.eta_label = "6–24 Months"
            elif th == "ROLLING_24H":
                self.eta_label = "24h Rolling"
            else:
                self.eta_label = "Today 15:15 IST"

        # Calculate no-chase boundary if not provided
        if self.no_chase_boundary is None and self.trigger_level > 0:
            act_str = str((self.actionable_plan or {}).get("action", "")).strip().upper()
            is_plan_opt = (self.actionable_plan or {}).get("instrument_type") == "OPTION"
            is_opt_level = bool(
                self.option_type
                or self.alert_type
                in ("OPTIONS_MOMENTUM", "GAMMA_BLAST", "INDEX_CALL_SETUP", "INDEX_PUT_SETUP")
                or (self.segment in ("FNO", "OPTIONS") and (self.strike or self.option_type))
            )
            # If the alert coordinates themselves are option premium levels
            is_option_prem = is_opt_level or (
                is_plan_opt
                and self.option_premium
                and abs(self.trigger_level - self.option_premium) < 0.01
            )

            # Determine if this position is LONG (price expected to increase) or SHORT (price expected to decrease)
            is_short_trade = False
            if is_option_prem:
                if act_str.startswith("SELL") or "SHORT" in act_str or "WRITE" in act_str:
                    is_short_trade = True
                else:
                    is_short_trade = False  # Long option premium
            elif act_str in ("BUY_PE", "BUY_PUT") or str(self.direction).upper() in (
                "BEARISH",
                "SHORT",
                "SELL",
            ):
                is_short_trade = True
            elif (
                act_str.startswith("BUY")
                or "LONG" in act_str
                or str(self.direction).upper() in ("BULLISH", "LONG")
            ):
                is_short_trade = False
            elif self.target_level > 0 and self.target_level != self.trigger_level:
                is_short_trade = self.target_level < self.trigger_level

            th = (self.time_horizon or "INTRADAY").upper()
            if is_option_prem:
                if is_short_trade:
                    # Option Writing / Credit Spread
                    mult = 0.95 if th == "INTRADAY" else 0.92
                else:
                    # Option Buying: Intraday capped at +5% of premium; Swing capped at +8%
                    mult = 1.05 if th == "INTRADAY" else 1.08
                self.no_chase_boundary = round(self.trigger_level * mult, 2)
            else:
                # Cash Equity / Futures standard 1.2% institutional buffer
                mult = 0.988 if is_short_trade else 1.012
                self.no_chase_boundary = round(self.trigger_level * mult, 2)

        if self.stage == "IGNITED" and not self.triggered_at:
            self.triggered_at = self.created_at

        # Model invariant: validate institutional alert ID determinism in live/real environments
        if (
            self.alert_id
            and self.environment not in ("TEST", "SIMULATION")
            and not self.alert_id.startswith(("test-", "mock-", "sim-", "yb-"))
        ):
            try:
                from engine.alert_identity import validate_alert_id

                is_valid, reason = validate_alert_id(self.alert_id)
                if not is_valid:
                    import logging

                    logging.getLogger(__name__).debug(
                        "Alert ID invariant notice for %s: %s", self.alert_id, reason
                    )
            except Exception:
                pass

        # Record data invariant audit if validation fails
        is_data_valid, val_reason = self.validate_data_integrity()
        if not is_data_valid:
            self.record_audit(
                event_type="DATA_SANITY_WARNING",
                message=f"Data integrity notice: {val_reason}",
                actor="INTEGRITY_GUARD",
                details={"reason": val_reason},
            )

    def validate_data_integrity(self) -> tuple[bool, str]:
        """
        Validates institutional data invariants on the alert:
          1. Level sanity: ltp, stop_loss, target_level > 0.
          2. Geometric consistency: for long/option, stop_loss < ltp < target_level.
             for short equity/futures, target_level < ltp < stop_loss.
          3. Contract vs Expiry Date Coherence: if contract_symbol encodes a date, it must match expiry_date.
          4. Non-negative DTE: expiry_date must not be in the past for live signals.
          5. Option Coordinate Boundary Sanctity: option premium cannot exceed spot price;
             option SL/target cannot be underlying spot levels.
        Returns: (is_valid, failure_reason)
        """
        is_test = (
            self.environment in ("TEST", "SIMULATION")
            or not self.is_live
            or self.alert_id.startswith(("test-", "sim-", "mock-", "yb-"))
            or ("PYTEST_CURRENT_TEST" in os.environ)
            or (os.environ.get("CHANAKYA_TESTING") == "1")
        )

        ltp = float(self.ltp or 0.0)
        sl = float(self.stop_loss or 0.0)
        t1 = float(self.target_level or 0.0)

        if ltp <= 0 or sl <= 0 or t1 <= 0:
            return False, f"Incomplete price levels (LTP={ltp}, SL={sl}, Target={t1})"

        try:
            from engine.alert_expiry import is_alert_option_premium_level

            is_opt = is_alert_option_premium_level(self)
        except Exception:
            is_opt = bool(
                self.alert_type in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
                or (
                    self.contract_symbol
                    and (self.contract_symbol.endswith("CE") or self.contract_symbol.endswith("PE"))
                )
            )
        is_long = is_opt or str(self.direction).upper() in ("BULLISH", "LONG", "BUY")
        is_short = not is_opt and str(self.direction).upper() in ("BEARISH", "SHORT", "SELL")

        # Option Coordinate Sanctity
        if is_opt:
            spot = float(self.underlying_spot or 0.0)
            if spot > 0:
                if ltp >= spot:
                    return (
                        False,
                        f"Option Coordinate Veto: Option premium (₹{ltp:,.2f}) cannot exceed underlying spot (₹{spot:,.2f})",
                    )
                if abs(ltp - spot) / spot < 0.005:
                    return (
                        False,
                        f"Option Coordinate Veto: Option premium (₹{ltp:,.2f}) matches spot price (₹{spot:,.2f}); spot coordinate leakage detected",
                    )
                if sl > (2.5 * ltp):
                    return (
                        False,
                        f"Option Coordinate Veto: Option SL (₹{sl:,.2f}) > 2.5x premium (₹{ltp:,.2f}); spot SL leakage detected",
                    )
                if t1 > (10.0 * ltp):
                    return (
                        False,
                        f"Option Coordinate Veto: Option Target (₹{t1:,.2f}) > 10x premium (₹{ltp:,.2f}); spot target leakage detected",
                    )

            if is_opt and self.option_type == "PE" and self.strike:
                try:
                    stk = float(self.strike)
                    if stk > 0 and ltp >= stk:
                        return (
                            False,
                            f"Option Coordinate Veto: Put premium (₹{ltp:,.2f}) cannot exceed strike (₹{stk:,.2f})",
                        )
                except (ValueError, TypeError):
                    pass

        has_trailing_ratchet = bool(
            getattr(self, "should_trail", False)
            or (getattr(self, "achieved_milestones", None))
            or (
                self.stage
                in (
                    "RUNNER_EXIT",
                    "COMPLETED",
                    "INVALIDATED",
                    "TARGET_ACHIEVED",
                    "TRAILING_UPDATE",
                    "T1_ACHIEVED",
                    "T2_ACHIEVED",
                    "DE_RISK_0_5R",
                    "BREAKEVEN_LOCKED",
                )
            )
            or (
                getattr(self, "target_status", "")
                in ("RUNNER_CLOSED", "T1_ACHIEVED", "T2_ACHIEVED", "TARGET_ACHIEVED")
            )
        )

        if not has_trailing_ratchet:
            if is_long:
                if sl >= ltp:
                    return False, f"Inverted Stop-Loss: SL (₹{sl:,.2f}) >= LTP (₹{ltp:,.2f})"
                if t1 <= ltp:
                    return False, f"Inverted Target: Target (₹{t1:,.2f}) <= LTP (₹{ltp:,.2f})"
            elif is_short:
                if sl <= ltp:
                    return False, f"Inverted Bearish Stop-Loss: SL (₹{sl:,.2f}) <= LTP (₹{ltp:,.2f})"
                if t1 >= ltp:
                    return False, f"Inverted Bearish Target: Target (₹{t1:,.2f}) >= LTP (₹{ltp:,.2f})"

            # Multi-Target Monotonicity Guard
            # Enforce that Target 2 and Target 3 extend strictly beyond preceding targets in the trade's direction
            plan_dict = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
            opt_plan_dict = (
                plan_dict.get("option_plan", {})
                if isinstance(plan_dict.get("option_plan"), dict)
                else {}
            )
            raw_t1 = (
                opt_plan_dict.get("t1_premium")
                or opt_plan_dict.get("target_1")
                or plan_dict.get("target_1")
                or plan_dict.get("target")
                or getattr(self, "target_1", None)
                or self.target_level
            )
            raw_t2 = (
                opt_plan_dict.get("t2_premium")
                or opt_plan_dict.get("target_2")
                or plan_dict.get("target_2")
                or getattr(self, "target_2", None)
            )
            raw_t3 = (
                opt_plan_dict.get("t3_premium")
                or opt_plan_dict.get("target_3")
                or plan_dict.get("target_3")
                or plan_dict.get("runner_target")
                or getattr(self, "target_3", None)
            )
            t1_f, t2_f, t3_f = None, None, None
            if raw_t1:
                try:
                    t1_f = float(str(raw_t1).replace(",", "").replace("₹", "").replace("$", ""))
                except Exception:
                    pass
            if raw_t2:
                try:
                    t2_f = float(str(raw_t2).replace(",", "").replace("₹", "").replace("$", ""))
                except Exception:
                    pass
            if raw_t3:
                try:
                    t3_f = float(str(raw_t3).replace(",", "").replace("₹", "").replace("$", ""))
                except Exception:
                    pass

            # Check if the trade plan itself is buying an option (even if direction is BEARISH)
            is_buying_option = bool(
                is_opt
                or plan_dict.get("instrument_type") == "OPTION"
                or str(plan_dict.get("action", "")).startswith("BUY")
                or (
                    getattr(self, "derivative_type", "") == "OPT"
                    and str((self.actionable_plan or {}).get("action", "")).startswith("BUY")
                )
            )
            if t1_f and t2_f:
                if is_buying_option or is_long:
                    if t2_f <= t1_f:
                        return (
                            False,
                            f"Inverted Target Hierarchy: Target 2 (₹{t2_f:,.2f}) <= Target 1 (₹{t1_f:,.2f})",
                        )
                elif is_short:
                    if t2_f >= t1_f:
                        return (
                            False,
                            f"Inverted Bearish Target Hierarchy: Target 2 (₹{t2_f:,.2f}) >= Target 1 (₹{t1_f:,.2f})",
                        )
            if t2_f and t3_f:
                if is_buying_option or is_long:
                    if t3_f <= t2_f:
                        return (
                            False,
                            f"Inverted Target Hierarchy: Target 3 (₹{t3_f:,.2f}) <= Target 2 (₹{t2_f:,.2f})",
                        )
                elif is_short:
                    if t3_f >= t2_f:
                        return (
                            False,
                            f"Inverted Bearish Target Hierarchy: Target 3 (₹{t3_f:,.2f}) >= Target 2 (₹{t2_f:,.2f})",
                        )

            # Zero / Micro Risk Guard:
            entry_ref = float(self.trigger_level or getattr(self, "entry_price", 0.0) or ltp)
            risk_dist = abs(entry_ref - sl)
            if entry_ref > 0 and (risk_dist / entry_ref) < 0.0005:
                return (
                    False,
                    f"Micro-Risk Noise Trap: Stop-loss distance (₹{risk_dist:,.2f}) is < 0.05% of entry (₹{entry_ref:,.2f})",
                )

            # Cash Equity Daily Circuit Limit Guard (NSE/BSE max 20% single-day bands)
            exch_str = str(self.exchange or "NSE").upper()
            is_cash_equity = (
                not is_opt
                and exch_str in ("NSE", "BSE")
                and not str(self.symbol).endswith("FUT")
                and getattr(self, "time_horizon", "INTRADAY") == "INTRADAY"
            )
            if is_cash_equity and entry_ref > 0 and not is_test:
                move_pct = (abs(t1 - entry_ref) / entry_ref) * 100.0
                if move_pct > 25.0:
                    return (
                        False,
                        f"Circuit Limit Violation: Intraday cash equity target move ({move_pct:.1f}%) exceeds maximum daily circuit band (20%)",
                    )

        else:
            # For trailing stops, validate that initial stop was geometrically sound
            init_sl = float(getattr(self, "initial_stop_loss", 0.0) or 0.0)
            entry_p = float(self.trigger_level or getattr(self, "entry_price", 0.0) or 0.0)
            if init_sl > 0 and entry_p > 0:
                if is_long and init_sl >= entry_p:
                    return (
                        False,
                        f"Inverted Initial Stop-Loss: Initial SL (₹{init_sl:,.2f}) >= Entry (₹{entry_p:,.2f})",
                    )
                elif is_short and init_sl <= entry_p:
                    return (
                        False,
                        f"Inverted Initial Bearish Stop-Loss: Initial SL (₹{init_sl:,.2f}) <= Entry (₹{entry_p:,.2f})",
                    )

        # Contract vs Expiry Date Coherence
        if self.contract_symbol and self.expiry_date:
            m_iso = re.search(
                r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", self.contract_symbol
            )
            if m_iso:
                c_date = f"{m_iso.group(1)}-{m_iso.group(2)}-{m_iso.group(3)}"
                if self.expiry_date != c_date:
                    return (
                        False,
                        f"Contract/Expiry Mismatch: contract_symbol encodes {c_date} but alert.expiry_date is {self.expiry_date}",
                    )

        # Non-negative DTE check for live/production alerts
        if self.expiry_date and not is_test:
            try:
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_d = datetime.strptime(self.expiry_date.strip(), fmt).date()
                        today = datetime.now(IST).date()
                        if exp_d < today:
                            return (
                                False,
                                f"Historical Expiry Veto: Expiry date {self.expiry_date} is in the past (< {today.isoformat()})",
                            )
                        break
                    except ValueError:
                        pass
            except Exception:
                pass

        return True, ""

    def normalize_target_hierarchy(self) -> None:
        """
        Institutional self-healing target normalizer:
        Ensures strict monotonic hierarchy across all internal and displayed target fields:
        - For Long / Option Buying: SL < Entry < T1 < T2 < T3 (Runner)
        - For Short: SL > Entry > T1 > T2 > T3 (Runner)
        Synchronizes actionable_plan['target_1'], actionable_plan['target'],
        actionable_plan['target_2'], actionable_plan['target_3'], and self.target_level
        so that actionable_plan['target'] NEVER aliases T3, preventing T1 > T2 inversions.
        """
        if not isinstance(self.actionable_plan, dict):
            return

        try:
            from engine.alert_expiry import is_alert_option_premium_level
            is_opt = is_alert_option_premium_level(self)
        except Exception:
            is_opt = bool(
                self.alert_type in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
                or (self.contract_symbol and (self.contract_symbol.endswith("CE") or self.contract_symbol.endswith("PE")))
            )

        act_str = str(self.actionable_plan.get("action", "")).upper()
        plan_is_option = self.actionable_plan.get("instrument_type") == "OPTION"
        is_buying_option = bool(
            is_opt
            or plan_is_option
            or act_str.startswith("BUY")
            or (getattr(self, "derivative_type", "") == "OPT" and act_str.startswith("BUY"))
        )
        is_short = not is_buying_option and (
            act_str.startswith("SELL")
            or act_str.startswith("SHORT")
            or str(self.direction).upper() in ("BEARISH", "SHORT", "SELL")
        )

        plan_dict = self.actionable_plan
        opt_plan = plan_dict.get("option_plan") if isinstance(plan_dict.get("option_plan"), dict) else {}

        # If the actionable plan represents an option vehicle (option buying/selling):
        if plan_is_option:
            opt_entry = float(
                getattr(self, "option_premium", 0.0)
                or (plan_dict.get("trade_plan") or {}).get("entry_price", 0.0)
                or (plan_dict.get("option_alternative") or {}).get("ltp", 0.0)
                or 0.0
            )
            entry_ref = opt_entry if opt_entry > 0 else float(self.trigger_level or getattr(self, "entry_price", 0.0) or self.ltp or 0.0)
            target_sources = [
                plan_dict.get("target_1"),
                plan_dict.get("target_2"),
                plan_dict.get("target_3"),
                plan_dict.get("runner_target"),
                plan_dict.get("target"),
                getattr(self, "option_target_level", None),
                getattr(self, "option_target_1", None),
                getattr(self, "option_target_2", None),
                opt_plan.get("t1_premium"),
                opt_plan.get("t2_premium"),
                opt_plan.get("t3_premium"),
                opt_plan.get("target_1"),
                opt_plan.get("target_2"),
            ]
            # If this is a pure option alert, self.target_level also represents option premium target
            if is_opt:
                target_sources.append(self.target_level)
        else:
            entry_ref = float(self.trigger_level or getattr(self, "entry_price", 0.0) or self.ltp or 0.0)
            target_sources = [
                plan_dict.get("target_1"),
                plan_dict.get("target_2"),
                plan_dict.get("target_3"),
                plan_dict.get("runner_target"),
                plan_dict.get("target"),
                self.target_level,
            ]

        # Collect raw target candidates from all plan keys
        candidates: list[float] = []
        for src in target_sources:
            if src is None:
                continue
            try:
                clean_num = float(str(src).replace(",", "").replace("₹", "").replace("$", "").strip())
                if clean_num > 0 and clean_num not in candidates:
                    # Avoid duplicates within 0.05
                    if not any(abs(clean_num - c) < 0.05 for c in candidates):
                        candidates.append(clean_num)
            except Exception:
                pass

        if not candidates:
            return

        # Directional filter: profit targets must extend beyond entry
        if entry_ref > 0:
            if not is_short:
                # Long / option buying: targets must be >= entry
                valid_tgts = [c for c in candidates if c >= entry_ref * 0.999]
            else:
                # Short: targets must be <= entry
                valid_tgts = [c for c in candidates if c <= entry_ref * 1.001]
            if valid_tgts:
                candidates = valid_tgts

        # Sort monotonically
        candidates.sort(reverse=is_short)

        if not candidates:
            return

        curr = "$" if self.segment == "CRYPTO" else "₹"
        dec = 4 if self.segment == "CDS" else (2 if self.ltp < 100 or (plan_is_option and entry_ref < 100) else 1)

        t1 = candidates[0]
        if not plan_is_option or is_opt:
            self.target_level = t1
        else:
            self.option_target_level = t1
            self.option_target_1 = t1

        plan_dict["target"] = f"{curr}{t1:,.{dec}f}"
        plan_dict["target_1"] = f"{curr}{t1:,.{dec}f}"

        if len(candidates) >= 2:
            t2 = candidates[1]
            plan_dict["target_2"] = f"{curr}{t2:,.{dec}f}"
            if plan_is_option and not is_opt:
                self.option_target_2 = t2
        if len(candidates) >= 3:
            t3 = candidates[2]
            plan_dict["target_3"] = f"{curr}{t3:,.{dec}f}"
            plan_dict["runner_target"] = f"{curr}{t3:,.{dec}f}"

        if opt_plan:
            opt_plan["t1_premium"] = t1
            if len(candidates) >= 2:
                opt_plan["t2_premium"] = candidates[1]
            if len(candidates) >= 3:
                opt_plan["t3_premium"] = candidates[2]

    @property
    def is_expired(self) -> bool:
        """
        Determines whether an alert, derivative contract, or intraday trade has expired.
        1. Checks explicit expiry_date (15:30 IST on expiry day).
        2. Intraday Session Cutoff: All INTRADAY setups strictly expire at 15:15 IST (NSE/BSE/NFO)
           or 23:15 IST (MCX) on the session date, or immediately if created on a prior date.
        3. Configured TTL: Checks if (now - created_dt) exceeds explicit ttl_seconds.
        4. Stale Setup Time-Stop: Unignited EARLY_WARNING setups expire after 60 mins during session.
        5. Weekly Index expiry calendar and 24h Gamma Blast fallback.
        """
        if self.stage == "EXPIRED":
            return True

        # Test and simulation alerts do not expire based on wall-clock time unless explicitly tested
        if (
            self.environment in ("TEST", "SIMULATION")
            or not self.is_live
            or self.alert_id.startswith("test-")
        ) and not getattr(self, "_force_test_expiry", False):
            return False

        now = datetime.now(IST)

        is_deriv = bool(
            self.strike
            or self.option_type
            or self.contract_symbol
            or self.alert_type
            in ("GAMMA_BLAST", "OPTIONS_MOMENTUM", "INDEX_CALL_SETUP", "INDEX_PUT_SETUP")
        )

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

        # 2. Check creation timestamp for intraday cutoff, TTL, and time-stops
        created_dt = None
        if self.created_at:
            clean_ts = self.created_at.replace(" IST", "").strip()[:19]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    created_dt = datetime.strptime(clean_ts, fmt).replace(tzinfo=IST)
                    break
                except ValueError:
                    pass

        if created_dt:
            # 2a. Explicit Time-To-Live (TTL)
            if self.ttl_seconds and self.ttl_seconds > 0:
                if (now - created_dt).total_seconds() >= self.ttl_seconds:
                    return True

            # 2b. Intraday Session Cutoff (15:15 IST for NSE/BSE/NFO, 23:15 IST for MCX)
            # Intraday setups belong strictly to their trading session and cannot carry overnight.
            # Derivative contracts with future expiry dates remain active until their contract expiry date.
            th = (self.time_horizon or "INTRADAY").upper()
            is_test_env = (
                (os.environ.get("CHANAKYA_TESTING") == "1")
                or (os.environ.get("DEPLOY_MODE") == "test")
                or ("PYTEST_CURRENT_TEST" in os.environ)
                or (self.environment == "TEST")
            )
            if th in ("SCALP", "INTRADAY", "INTRADAY_SCALP_ONLY", "ROLLING_24H") and (
                not is_test_env or getattr(self, "_force_test_expiry", False)
            ):
                has_future_expiry = False
                if self.expiry_date:
                    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                        try:
                            exp_dt = datetime.strptime(self.expiry_date.strip(), fmt).replace(
                                hour=15, minute=30, second=0, tzinfo=IST
                            )
                            if exp_dt.date() > now.date():
                                has_future_expiry = True
                            break
                        except ValueError:
                            pass

                is_active_deriv = (
                    is_deriv
                    and self.stage in ("IGNITED", "TRAILING_UPDATE", "T1_ACHIEVED", "T2_ACHIEVED")
                    and not getattr(self, "_force_test_expiry", False)
                )

                exch = (self.exchange or "NSE").upper()
                seg = (getattr(self, "segment", "") or "").upper()
                is_crypto = (
                    exch in ("CRYPTO", "BINANCE", "DERIBIT", "COINBASE")
                    or seg == "CRYPTO"
                    or self.symbol.upper().startswith("CRYPTO:")
                    or self.symbol.upper().endswith("USDT")
                )

                if not has_future_expiry and not is_active_deriv:
                    if is_crypto:
                        # Crypto is a 24x7 continuous global market; intraday alerts have a 24-hour rolling expiry window
                        if (now - created_dt).total_seconds() >= 86400:
                            return True
                    elif created_dt.date() < now.date():
                        return True
                    elif exch == "MCX":
                        if now.hour > 23 or (now.hour == 23 and now.minute >= 15):
                            return True
                    else:
                        if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
                            return True
                elif getattr(self, "_force_test_expiry", False):
                    if is_crypto:
                        if (now - created_dt).total_seconds() >= 86400:
                            return True
                    elif created_dt.date() < now.date():
                        return True
                    elif exch == "MCX":
                        if now.hour > 23 or (now.hour == 23 and now.minute >= 15):
                            return True
                    else:
                        if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
                            return True

            # 2c. Unignited Early Warning Setup Time-Stop:
            # Pre-breakout early warnings expire if left unignited from a prior day,
            # or if 60 minutes have elapsed without triggering during an active session (4h for 24x7 crypto).
            # Multi-session setups (SWING, POSITIONAL, MULTIBAGGER) are explicitly exempt from single-session cutoff.
            is_multi_session = th in (
                "SWING",
                "SWING_SHORT",
                "SWING_MID",
                "LONG_TERM",
                "POSITIONAL",
                "MULTIBAGGER",
            )
            if self.stage in ("EARLY_WARNING", "STALK", "PRIMED") and not is_multi_session:
                exch = (self.exchange or "NSE").upper()
                seg = (getattr(self, "segment", "") or "").upper()
                is_crypto = (
                    exch in ("CRYPTO", "BINANCE", "DERIBIT", "COINBASE")
                    or seg == "CRYPTO"
                    or self.symbol.upper().startswith("CRYPTO:")
                    or self.symbol.upper().endswith("USDT")
                )
                if is_crypto:
                    if (now - created_dt).total_seconds() >= 14400:
                        return True
                elif created_dt.date() < now.date():
                    return True
                elif th in ("SCALP", "INTRADAY_SCALP_ONLY") and (now - created_dt).total_seconds() >= 1800:
                    return True
                elif th == "INTRADAY" and (now - created_dt).total_seconds() >= 3600:
                    return True

            # 2d. Swing, Positional, and Multibagger Trading-Session Shelf-Life:
            # Strictly counts market TRADING DAYS, excluding weekends and official trading holidays.
            # Avoids premature signal expiry across non-trading periods.
            if (
                th in ("SWING_SHORT", "SWING_MID", "LONG_TERM", "POSITIONAL", "MULTIBAGGER")
                and not self.expiry_date
            ):
                from market.calendar import get_trading_days_elapsed

                t_days = get_trading_days_elapsed(
                    created_dt.date(), now.date(), exchange=self.exchange or "NSE"
                )
                # SWING_SHORT: 2–5 trading sessions (allowed up to 7 trading sessions before stale time-stop)
                if th == "SWING_SHORT" and t_days > 7:
                    return True
                # SWING_MID: 1–4 weeks (allowed up to 25 trading sessions before stale time-stop)
                elif th == "SWING_MID" and t_days > 25:
                    return True
                # LONG_TERM / POSITIONAL: 1–6 months (allowed up to 130 trading sessions)
                elif th in ("LONG_TERM", "POSITIONAL") and t_days > 130:
                    return True
                # MULTIBAGGER: 6–24 months (allowed up to 520 trading sessions)
                elif th == "MULTIBAGGER" and t_days > 520:
                    return True

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

                # Gamma blast & index setups shelf-life: intraday momentum spike expires after 24 hours only if no explicit expiry date
                if (
                    self.alert_type in ("GAMMA_BLAST", "INDEX_CALL_SETUP", "INDEX_PUT_SETUP")
                    and not self.expiry_date
                ):
                    if (now - created_dt).total_seconds() > 24 * 3600:
                        return True

        return False

    @property
    def is_active(self) -> bool:
        """A trade is active if it is not archived, not invalidated, not expired, and has not completed final target, runner exit, sl hit, or time stop."""
        if self.is_expired:
            return False
        return (
            not self.is_archived
            and not self.is_invalidated
            and self.stage
            not in (
                "INVALIDATED",
                "TARGET_ACHIEVED",
                "COMPLETED",
                "EXPIRED",
                "RUNNER_EXIT",
                "PROFIT_SECURED",
                "SL_HIT",
                "TIME_STOP_EXIT",
            )
            and self.target_status
            not in ("TARGET_ACHIEVED", "RUNNER_CLOSED", "SL_HIT", "TIME_STOP_EXIT")
        )

    @is_active.setter
    def is_active(self, val: bool) -> None:
        self.is_archived = not val

    @property
    def is_stalk(self) -> bool:
        """True if the alert is in radar stalking or precursor mode."""
        return self.stage in ("STALK", "PRECURSOR")

    @property
    def is_primed(self) -> bool:
        """True if the alert is in high-priority proximity surveillance (within ±0.35% of trigger)."""
        return self.stage == "PRIMED"

    @property
    def is_ignited(self) -> bool:
        """True if the alert has fired its execution trigger."""
        return self.stage in ("IGNITED", "TRIGGERED")

    def promote_stage(
        self,
        new_stage: str,
        reason: str = "",
        ltp: Optional[float] = None,
        actor: str = "INTERCEPTION_ENGINE",
    ) -> bool:
        """
        Transitions alert across the 3-stage interception pipeline:
        STALK -> PRIMED -> IGNITED (or EARLY_WARNING -> PRIMED -> IGNITED).
        Records an audit event and updates timestamps.
        """
        valid_stages = (
            "STALK",
            "PRIMED",
            "EARLY_WARNING",
            "IGNITED",
            "INVALIDATED",
            "EXPIRED",
            "COMPLETED",
        )
        if new_stage not in valid_stages and not hasattr(self, "_custom_stages"):
            return False
        if self.stage == new_stage:
            return False

        old_stage = self.stage
        self.stage = new_stage
        if ltp is not None and ltp > 0:
            self.ltp = float(ltp)
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        self.updated_at = now_str

        if new_stage == "IGNITED" and not self.triggered_at:
            self.triggered_at = now_str

        self.record_audit(
            event_type="STAGE_PROMOTION",
            message=f"Stage transitioned: {old_stage} -> {new_stage} ({reason})",
            actor=actor,
            details={
                "old_stage": old_stage,
                "new_stage": new_stage,
                "reason": reason,
                "ltp": self.ltp,
            },
        )
        return True

    @property
    def entry_price(self) -> float:
        """
        Canonical entry price coordinate.
        For options, returns initial_entry_premium if available; otherwise trigger_level,
        option_premium, or ltp. For equities/futures, returns trigger_level or ltp.
        Guarantees that live option quote refreshes do NOT mutate initial entry price.
        """
        is_opt_primary = bool(
            self.alert_type in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
            or (
                (self.strike or self.option_type or self.contract_symbol)
                and self.option_premium
                and self.ltp
                and abs(self.ltp - float(self.option_premium)) < max(1.0, float(self.option_premium) * 0.15)
            )
        )
        if is_opt_primary and self.initial_entry_premium and self.initial_entry_premium > 0:
            return float(self.initial_entry_premium)
        if self.trigger_level and self.trigger_level > 0:
            return float(self.trigger_level)
        if is_opt_primary and self.option_premium and self.option_premium > 0:
            return float(self.option_premium)
        return float(self.ltp or 0.0)

    @property
    def target_1(self) -> Optional[float]:
        """Canonical Target 1 price level."""
        plan = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
        t1_val = plan.get("target_1")
        if t1_val:
            try:
                import re

                m = re.findall(r"[\d.]+", str(t1_val).replace(",", ""))
                if m:
                    return float(m[0])
            except Exception:
                pass

        # If not explicitly defined as target_1, compute canonical +2R milestone if entry & SL exist
        ep = self.entry_price
        sl = getattr(self, "initial_stop_loss", None) or self.stop_loss
        if ep and sl and ep != sl:
            risk = abs(ep - sl)
            tgt_lvl = float(self.target_level or 0.0)
            if tgt_lvl > 0 and tgt_lvl != ep:
                is_expanding_up = tgt_lvl > ep
            else:
                is_opt = bool(
                    self.strike
                    or self.option_type
                    or self.contract_symbol
                    or self.alert_type
                    in ("GAMMA_BLAST", "OPTIONS_MOMENTUM", "INDEX_CALL_SETUP", "INDEX_PUT_SETUP")
                )
                is_opt_prem = bool(
                    self.alert_type in ("OPTIONS_MOMENTUM", "OPTION_WRITE")
                    or (
                        is_opt
                        and getattr(self, "option_premium", None)
                        and abs(ep - float(self.option_premium)) < max(1.0, float(self.option_premium) * 0.15)
                    )
                )
                is_option_buyer = is_opt_prem and str(getattr(self, "option_write", False)).lower() not in ("true", "1")
                dir_str = str(getattr(self, "direction", "BULLISH")).upper()
                is_bullish = dir_str not in ("BEARISH", "SELL", "SHORT")
                is_expanding_up = is_option_buyer or is_bullish
            t1_calc = round(ep + (risk * 2.0) if is_expanding_up else ep - (risk * 2.0), 2)
            if tgt_lvl > 0:
                if is_expanding_up and tgt_lvl > ep and t1_calc >= tgt_lvl:
                    return round(ep + (tgt_lvl - ep) * 0.5, 2)
                elif not is_expanding_up and tgt_lvl < ep and t1_calc <= tgt_lvl:
                    return round(ep - (ep - tgt_lvl) * 0.5, 2)
            return t1_calc

        fallback = plan.get("target") or self.target_level
        if fallback:
            try:
                import re

                m = re.findall(r"[\d.]+", str(fallback).replace(",", ""))
                if m:
                    return float(m[0])
            except Exception:
                pass
        return self.target_level if (self.target_level and self.target_level > 0) else None

    @property
    def target_2(self) -> Optional[float]:
        """Canonical Target 2 price level with strict monotonicity guardrails."""
        plan = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
        t2_val = plan.get("target_2")
        t2_num = None
        if t2_val:
            try:
                import re

                m = re.findall(r"[\d.]+", str(t2_val).replace(",", ""))
                if m:
                    t2_num = float(m[0])
            except Exception:
                pass
        t1 = self.target_1
        ep = self.entry_price
        sl = getattr(self, "initial_stop_loss", None) or self.stop_loss
        if t1 and ep and sl and ep != sl:
            risk = abs(ep - sl)
            is_expanding_up = (t1 > ep)
            # Enforce strict monotonicity relative to t1
            if t2_num is not None:
                if is_expanding_up and t2_num > t1:
                    return t2_num
                elif not is_expanding_up and t2_num < t1:
                    return t2_num
            # If t2 was missing, zero, or inverted, calculate mathematically sound T2 (+3.0R)
            return round(t1 + (1.2 * risk) if is_expanding_up else max(0.05, t1 - (1.2 * risk)), 2)
        return t2_num

    @property
    def conviction_tier(self) -> str:
        """Institutional conviction tier (APEX_CONFLUENCE, HIGH_CONVICTION, DEFINED_RISK_ONLY, or LOW_CONVICTION)."""
        if self.metrics and isinstance(self.metrics, dict):
            tier = self.metrics.get("conviction_tier")
            if tier:
                return str(tier)
        plan = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
        if plan.get("conviction_tier"):
            return str(plan["conviction_tier"])
        if self.confidence >= 90:
            return "APEX_CONFLUENCE"
        elif self.confidence >= 80:
            return "HIGH_CONVICTION"
        elif self.confidence >= 70:
            return "DEFINED_RISK_ONLY"
        return "LOW_CONVICTION"

    @property
    def execution_style_mandate(self) -> Optional[str]:
        """Returns mandatory execution restriction (e.g. HEDGED_SPREAD_MANDATORY) if assigned."""
        if self.metrics and isinstance(self.metrics, dict):
            mandate = self.metrics.get("execution_style_mandate")
            if mandate:
                return str(mandate)
        plan = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
        if plan.get("execution_style_mandate"):
            return str(plan["execution_style_mandate"])
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.stage
        d["scrutiny"] = (self.metrics or {}).get("scrutiny") if isinstance(self.metrics, dict) else None
        d["entry_price"] = self.entry_price
        d["target_1"] = self.target_1
        d["target_2"] = self.target_2
        d["conviction_tier"] = self.conviction_tier
        d["execution_style_mandate"] = self.execution_style_mandate
        d["timestamp"] = (
            self.invalidated_at
            or self.created_at
            or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        )
        d["is_active"] = self.is_active
        d["is_expired"] = self.is_expired

        plan_opt = (
            (self.actionable_plan or {}).get("option_plan", {})
            if isinstance(self.actionable_plan, dict)
            else {}
        )
        plan_dict = self.actionable_plan if isinstance(self.actionable_plan, dict) else {}
        d["hedged_spread"] = plan_dict.get("hedged_spread") or plan_opt.get("hedged_spread")
        d["free_roll_plan"] = plan_dict.get("free_roll_plan") or plan_opt.get("free_roll_plan")
        eff_exp_date = (
            self.expiry_date
            or plan_opt.get("expiry_date")
            or plan_opt.get("expiry")
            or plan_dict.get("expiry_date")
            or plan_dict.get("expiry")
        )
        eff_exp_type = (
            self.expiry_type or plan_opt.get("expiry_type") or plan_dict.get("expiry_type")
        )
        eff_contract = (
            self.contract_symbol or plan_opt.get("contract_symbol") or plan_dict.get("contract")
        )
        if not eff_exp_type and eff_exp_date:
            from engine.alert_expiry import classify_expiry_type

            eff_exp_type = classify_expiry_type(eff_exp_date, self.symbol)

        # Rich expiry details & next-expiry opportunities
        exp_info = get_expiry_metadata(eff_exp_date, eff_exp_type, self.symbol, eff_contract)
        resolved_date = eff_exp_date or exp_info.get("raw_date")
        resolved_type = eff_exp_type or (
            "WEEKLY"
            if exp_info.get("is_weekly")
            else "MONTHLY"
            if exp_info.get("is_monthly")
            else None
        )
        d["expiry_date"] = resolved_date
        d["expiry_type"] = resolved_type
        d["expiry_details"] = exp_info
        d["expiry_month_name"] = exp_info.get("month_name")
        d["expiry_formatted"] = exp_info.get("formatted")
        d["dte"] = exp_info.get("dte")

        next_opp = get_next_expiry_opportunity(self, exp_info)
        if next_opp:
            d["next_expiry_opportunity"] = next_opp

        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutoAlert:
        """Constructs an AutoAlert from a dict, filtering out computed properties and extra keys."""
        from dataclasses import fields

        valid_keys = {f.name for f in fields(cls)}
        clean_kwargs = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**clean_kwargs)
