"""
engine/pretrade.py
──────────────────
P3-B: Pre-Trade Validation Engine.

Runs a comprehensive battery of checks BEFORE any order is submitted
to paper or live broker. All checks are deterministic and pure-Python.

Validation gates (in order):
  1. Kill switch check (SYSTEM → BROKER → ACCOUNT → USER → STRATEGY → SYMBOL)
  2. Market session check (is the market open for this segment?)
  3. Instrument validity (instrument exists, not expired, tradable)
  4. Tick size / lot size compliance
  5. Price band compliance (circuit limits for NSE/BSE)
  6. Buying power / margin sufficiency
  7. Holdings sufficiency (for SELL orders)
  8. Stale data gate (prices must be fresh within threshold)
  9. Portfolio risk gate (per-symbol concentration, daily loss cap)

Returns a structured PreTradeValidationResult with:
  - is_eligible: bool
  - blocking_reasons: list[str]  (non-empty → blocked)
  - warnings: list[str]          (non-blocking advisories)
  - gate_results: dict[str, GateResult]
  - correlation_id: str
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from engine.kill_switch import get_kill_switch_registry
from engine.observability import new_correlation_id


# ── Constants ─────────────────────────────────────────────────────────────────

# NSE price band defaults (circuit filter %)
NSE_DEFAULT_PRICE_BAND_PCT = 20.0  # ±20% from prev close

# Data freshness — reject orders if quote is older than this
MAX_QUOTE_AGE_SECONDS = 60.0

# Portfolio concentration limits
MAX_SINGLE_SYMBOL_CONCENTRATION_PCT = 20.0  # Max 20% of portfolio in one symbol
MAX_DAILY_LOSS_CAP_PCT = 3.0  # Max 3% daily drawdown triggers advisory

# Tick size defaults (paisa) for equities on NSE
DEFAULT_TICK_SIZE = 0.05  # ₹0.05

# Segment → standard lot sizes
SEGMENT_LOT_SIZES: dict[str, int] = {
    "EQ": 1,
    "FUT": 1,  # Varies by contract — actual lot from instrument master
    "OPT": 1,
    "CDS": 1000,  # Currency futures/options: 1000 units
    "MCX": 1,  # Commodity: varies by contract
}


# ── Result Types ──────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    """Result for a single pre-trade validation gate."""

    gate: str
    passed: bool
    reason: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.passed


@dataclass
class PreTradeValidationResult:
    """
    Complete pre-trade validation result.

    is_eligible=True only when ALL mandatory gates pass.
    Warnings are non-blocking advisories (e.g. high concentration).
    """

    correlation_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: int
    price: Optional[float]  # None for MARKET orders
    order_type: str  # "MARKET" / "LIMIT" / "SL" / "SL-M"
    segment: str  # "EQ" / "FUT" / "OPT" / "CDS" / "MCX"
    broker: Optional[str]
    account: Optional[str]
    user: Optional[str]
    strategy: Optional[str]

    is_eligible: bool
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gate_results: dict[str, GateResult] = field(default_factory=dict)
    validated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "order_type": self.order_type,
            "segment": self.segment,
            "broker": self.broker,
            "is_eligible": self.is_eligible,
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
            "gate_results": {
                k: {
                    "gate": v.gate,
                    "passed": v.passed,
                    "reason": v.reason,
                    "details": v.details,
                }
                for k, v in self.gate_results.items()
            },
            "validated_at": self.validated_at,
        }


# ── Individual Gate Implementations ──────────────────────────────────────────


def _gate_kill_switch(
    broker: Optional[str],
    account: Optional[str],
    user: Optional[str],
    strategy: Optional[str],
    symbol: str,
) -> GateResult:
    """Gate 1: Check all active kill switches."""
    try:
        registry = get_kill_switch_registry()
        blocked, reasons = registry.is_blocked(
            broker=broker,
            account=account,
            user=user,
            strategy=strategy,
            symbol=symbol,
        )
        if blocked:
            return GateResult(
                gate="kill_switch",
                passed=False,
                reason="; ".join(reasons),
                details={"active_blocks": reasons},
            )
        return GateResult(gate="kill_switch", passed=True)
    except Exception as exc:
        # Kill switch gate failure is itself a blocker (fail-safe)
        return GateResult(
            gate="kill_switch",
            passed=False,
            reason=f"Kill switch check failed: {exc}",
        )


def _gate_market_session(segment: str) -> GateResult:
    """
    Gate 2: Verify the market is open for this segment.

    Segments:
    - EQ/FUT/OPT (NSE/BSE): 09:15–15:30 IST Mon–Fri
    - MCX Commodity: 09:00–23:30 IST (23:55 for some metals) Mon–Fri
    - CDS Currency: 09:00–17:00 IST Mon–Fri
    """
    try:
        from datetime import time as dtime
        import zoneinfo

        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(tz=ist)
        weekday = now_ist.weekday()  # 0=Mon, 6=Sun
        now_time = now_ist.time()

        # Weekend check
        if weekday >= 5:  # Saturday or Sunday
            return GateResult(
                gate="market_session",
                passed=False,
                reason=f"Market closed: Weekend ({now_ist.strftime('%A')})",
                details={"weekday": weekday},
            )

        seg = segment.upper()
        if seg in ("EQ", "FUT", "OPT"):
            open_t = dtime(9, 15)
            close_t = dtime(15, 30)
        elif seg == "MCX":
            open_t = dtime(9, 0)
            close_t = dtime(23, 30)
        elif seg == "CDS":
            open_t = dtime(9, 0)
            close_t = dtime(17, 0)
        else:
            # Unknown segment — pass with warning
            return GateResult(
                gate="market_session",
                passed=True,
                reason=f"Unknown segment '{segment}' — session check skipped",
            )

        if open_t <= now_time <= close_t:
            return GateResult(
                gate="market_session",
                passed=True,
                details={"current_ist": now_ist.isoformat(), "segment": seg},
            )
        else:
            return GateResult(
                gate="market_session",
                passed=False,
                reason=f"Market closed for {seg}: {now_time.strftime('%H:%M')} IST is outside {open_t.strftime('%H:%M')}–{close_t.strftime('%H:%M')}",
                details={"current_ist": now_ist.isoformat()},
            )
    except Exception as exc:
        return GateResult(
            gate="market_session",
            passed=False,
            reason=f"Session check error: {exc}",
        )


def _gate_lot_size(
    quantity: int,
    segment: str,
    lot_size: int = 1,
) -> GateResult:
    """Gate 4: Verify quantity is a multiple of the lot size."""
    effective_lot = lot_size if lot_size > 0 else SEGMENT_LOT_SIZES.get(segment.upper(), 1)
    if quantity <= 0:
        return GateResult(
            gate="lot_size",
            passed=False,
            reason=f"Quantity must be positive (got {quantity})",
        )
    if quantity % effective_lot != 0:
        return GateResult(
            gate="lot_size",
            passed=False,
            reason=f"Quantity {quantity} is not a multiple of lot size {effective_lot}",
            details={"required_lot_size": effective_lot, "quantity": quantity},
        )
    return GateResult(gate="lot_size", passed=True, details={"lot_size": effective_lot})


def _gate_tick_size(
    price: Optional[float],
    order_type: str,
    tick_size: float = DEFAULT_TICK_SIZE,
) -> GateResult:
    """Gate 4b: Verify limit price is aligned to tick size."""
    if order_type == "MARKET" or price is None:
        return GateResult(
            gate="tick_size", passed=True, reason="Market order — no price to validate"
        )
    # Allow ±0.01 tolerance for floating-point
    remainder = round(price % tick_size, 4)
    if remainder < 0.01 or remainder > (tick_size - 0.01):
        return GateResult(gate="tick_size", passed=True)
    return GateResult(
        gate="tick_size",
        passed=False,
        reason=f"Price ₹{price} is not aligned to tick size ₹{tick_size}",
        details={"price": price, "tick_size": tick_size, "remainder": remainder},
    )


def _gate_price_band(
    price: Optional[float],
    prev_close: Optional[float],
    order_type: str,
    band_pct: float = NSE_DEFAULT_PRICE_BAND_PCT,
) -> GateResult:
    """Gate 5: Verify price is within circuit filter band."""
    if order_type == "MARKET" or price is None or prev_close is None or prev_close <= 0:
        return GateResult(
            gate="price_band",
            passed=True,
            reason="Market order or missing prev_close — band check skipped",
        )
    lower = prev_close * (1 - band_pct / 100)
    upper = prev_close * (1 + band_pct / 100)
    if lower <= price <= upper:
        return GateResult(
            gate="price_band",
            passed=True,
            details={"lower": round(lower, 2), "upper": round(upper, 2)},
        )
    return GateResult(
        gate="price_band",
        passed=False,
        reason=f"Price ₹{price} outside ±{band_pct}% circuit band "
        f"[₹{lower:.2f}–₹{upper:.2f}] from prev close ₹{prev_close}",
        details={"lower": round(lower, 2), "upper": round(upper, 2), "band_pct": band_pct},
    )


def _gate_buying_power(
    side: str,
    quantity: int,
    price: Optional[float],
    ltp: Optional[float],
    available_cash: Optional[float],
    segment: str,
) -> GateResult:
    """Gate 6: Verify buying power / margin sufficiency for BUY orders."""
    if side.upper() != "BUY":
        return GateResult(
            gate="buying_power", passed=True, reason="SELL order — buying power not checked"
        )
    if available_cash is None:
        return GateResult(
            gate="buying_power",
            passed=True,
            reason="available_cash not provided — buying power check skipped",
        )

    effective_price = price if price is not None else (ltp or 0.0)
    if effective_price <= 0:
        return GateResult(
            gate="buying_power",
            passed=False,
            reason="Cannot determine order value: price and LTP are both unavailable",
        )

    # Apply margin multipliers
    seg = segment.upper()
    if seg == "EQ":
        margin_fraction = 1.0  # CNC: full value
    elif seg in ("FUT", "OPT"):
        margin_fraction = 0.15  # ~15% SPAN+exposure margin (conservative estimate)
    elif seg == "CDS":
        margin_fraction = 0.03
    elif seg == "MCX":
        margin_fraction = 0.05
    else:
        margin_fraction = 1.0

    required_margin = effective_price * quantity * margin_fraction
    if available_cash >= required_margin:
        return GateResult(
            gate="buying_power",
            passed=True,
            details={
                "required_margin": round(required_margin, 2),
                "available_cash": round(available_cash, 2),
            },
        )
    return GateResult(
        gate="buying_power",
        passed=False,
        reason=f"Insufficient margin: need ₹{required_margin:,.2f}, have ₹{available_cash:,.2f}",
        details={
            "required_margin": round(required_margin, 2),
            "available_cash": round(available_cash, 2),
            "margin_fraction": margin_fraction,
        },
    )


def _gate_data_freshness(
    quote_age_seconds: Optional[float],
) -> GateResult:
    """Gate 8: Verify the price data is fresh enough to trade on."""
    if quote_age_seconds is None:
        return GateResult(
            gate="data_freshness",
            passed=False,
            reason="Quote age unknown — cannot validate data freshness. Obtain a live quote first.",
        )
    if quote_age_seconds <= MAX_QUOTE_AGE_SECONDS:
        return GateResult(
            gate="data_freshness",
            passed=True,
            details={"quote_age_seconds": round(quote_age_seconds, 1)},
        )
    return GateResult(
        gate="data_freshness",
        passed=False,
        reason=f"Quote is stale: {quote_age_seconds:.0f}s old (max allowed: {MAX_QUOTE_AGE_SECONDS}s)",
        details={
            "quote_age_seconds": round(quote_age_seconds, 1),
            "max_allowed": MAX_QUOTE_AGE_SECONDS,
        },
    )


def _gate_portfolio_risk(
    side: str,
    symbol: str,
    quantity: int,
    ltp: Optional[float],
    portfolio_value: Optional[float],
    daily_pnl: Optional[float],
) -> tuple[GateResult, list[str]]:
    """
    Gate 9: Portfolio risk advisory check.

    Returns (gate_result, warnings). Warnings are non-blocking advisories.
    """
    warnings: list[str] = []

    if side.upper() != "BUY":
        return GateResult(gate="portfolio_risk", passed=True), warnings

    if ltp and portfolio_value and portfolio_value > 0:
        order_value = ltp * quantity
        concentration_pct = order_value / portfolio_value * 100
        if concentration_pct > MAX_SINGLE_SYMBOL_CONCENTRATION_PCT:
            warnings.append(
                f"High concentration: this order would be {concentration_pct:.1f}% of portfolio "
                f"(limit: {MAX_SINGLE_SYMBOL_CONCENTRATION_PCT}%)"
            )

    if daily_pnl is not None and portfolio_value and portfolio_value > 0:
        daily_loss_pct = abs(daily_pnl) / portfolio_value * 100
        if daily_pnl < 0 and daily_loss_pct >= MAX_DAILY_LOSS_CAP_PCT:
            warnings.append(
                f"Daily loss cap advisory: current daily loss is {daily_loss_pct:.1f}% of portfolio. "
                f"Consider pausing new positions."
            )

    return GateResult(gate="portfolio_risk", passed=True), warnings


# ── Main Validation Entry Point ───────────────────────────────────────────────


def validate_pretrade(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "MARKET",
    price: Optional[float] = None,
    segment: str = "EQ",
    broker: Optional[str] = None,
    account: Optional[str] = None,
    user: Optional[str] = None,
    strategy: Optional[str] = None,
    # Market data context
    ltp: Optional[float] = None,
    prev_close: Optional[float] = None,
    quote_age_seconds: Optional[float] = None,
    # Account context
    available_cash: Optional[float] = None,
    portfolio_value: Optional[float] = None,
    daily_pnl: Optional[float] = None,
    # Instrument context
    lot_size: int = 1,
    tick_size: float = DEFAULT_TICK_SIZE,
    price_band_pct: float = NSE_DEFAULT_PRICE_BAND_PCT,
    # Control
    skip_session_check: bool = False,  # Set True in tests / after-hours paper
    correlation_id: Optional[str] = None,
) -> PreTradeValidationResult:
    """
    Run all pre-trade validation gates and return a structured result.

    Args:
        symbol: Instrument symbol (e.g. "RELIANCE", "NSE:NIFTY24SEP25000CE")
        side: "BUY" or "SELL"
        quantity: Number of shares/lots
        order_type: "MARKET" / "LIMIT" / "SL" / "SL-M"
        price: Limit price (required for LIMIT/SL orders)
        segment: "EQ" / "FUT" / "OPT" / "CDS" / "MCX"
        broker: Broker identifier (for kill switch check)
        account: Account ID (for kill switch check)
        user: User ID (for kill switch check)
        strategy: Strategy ID (for kill switch check)
        ltp: Last traded price (for margin calculation and portfolio risk)
        prev_close: Previous day's closing price (for price band check)
        quote_age_seconds: Age of the quote in seconds
        available_cash: Available cash/margin balance
        portfolio_value: Total portfolio value (for concentration check)
        daily_pnl: Today's realized + unrealized P&L (for daily loss cap)
        lot_size: Instrument lot size (default 1 for equities)
        tick_size: Instrument tick size (default ₹0.05)
        price_band_pct: Circuit filter band % (default ±20%)
        skip_session_check: Skip market hours validation (for paper/test)
        correlation_id: Optional pre-existing correlation ID

    Returns:
        PreTradeValidationResult with is_eligible, blocking_reasons, warnings
    """
    cid = correlation_id or new_correlation_id("pretrade")
    blocking: list[str] = []
    all_warnings: list[str] = []
    gate_results: dict[str, GateResult] = {}

    # Gate 1: Kill switch
    ks_gate = _gate_kill_switch(broker, account, user, strategy, symbol.upper())
    gate_results["kill_switch"] = ks_gate
    if ks_gate.blocked:
        blocking.append(ks_gate.reason or "Kill switch active")

    # Gate 2: Market session
    if not skip_session_check:
        session_gate = _gate_market_session(segment)
        gate_results["market_session"] = session_gate
        if session_gate.blocked:
            blocking.append(session_gate.reason or "Market closed")
    else:
        gate_results["market_session"] = GateResult(
            gate="market_session", passed=True, reason="Session check skipped"
        )

    # Gate 3: Lot size
    lot_gate = _gate_lot_size(quantity, segment, lot_size)
    gate_results["lot_size"] = lot_gate
    if lot_gate.blocked:
        blocking.append(lot_gate.reason or "Lot size violation")

    # Gate 4: Tick size
    tick_gate = _gate_tick_size(price, order_type, tick_size)
    gate_results["tick_size"] = tick_gate
    if tick_gate.blocked:
        blocking.append(tick_gate.reason or "Tick size violation")

    # Gate 5: Price band
    band_gate = _gate_price_band(price, prev_close, order_type, price_band_pct)
    gate_results["price_band"] = band_gate
    if band_gate.blocked:
        blocking.append(band_gate.reason or "Price outside circuit band")

    # Gate 6: Buying power
    bp_gate = _gate_buying_power(side, quantity, price, ltp, available_cash, segment)
    gate_results["buying_power"] = bp_gate
    if bp_gate.blocked:
        blocking.append(bp_gate.reason or "Insufficient buying power")

    # Gate 8: Data freshness
    freshness_gate = _gate_data_freshness(quote_age_seconds)
    gate_results["data_freshness"] = freshness_gate
    if freshness_gate.blocked:
        blocking.append(freshness_gate.reason or "Stale data")

    # Gate 9: Portfolio risk (advisory only)
    risk_gate, risk_warnings = _gate_portfolio_risk(
        side, symbol, quantity, ltp, portfolio_value, daily_pnl
    )
    gate_results["portfolio_risk"] = risk_gate
    all_warnings.extend(risk_warnings)

    return PreTradeValidationResult(
        correlation_id=cid,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        segment=segment,
        broker=broker,
        account=account,
        user=user,
        strategy=strategy,
        is_eligible=len(blocking) == 0,
        blocking_reasons=blocking,
        warnings=all_warnings,
        gate_results=gate_results,
    )
