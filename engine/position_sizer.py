"""
engine/position_sizer.py
────────────────────────
Institutional position sizing & risk parity calculation engine.

Supports three quantitative sizing methodologies:
  1. ATR Volatility Parity (`atr_volatility`): Equalizes dollar risk contribution based on stock volatility.
  2. Fixed Fractional Risk (`fixed_fractional`): Positions sized strictly on technical stop-loss distance.
  3. Half-Kelly Criterion (`half_kelly`): Optimal growth bet sizing based on empirical win rate & payoff ratio.

Includes Indian market lot-size rounding for F&O underlying derivatives.
"""

from __future__ import annotations
import logging
import math

logger = logging.getLogger("engine.position_sizer")


from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class MarketImpactEstimate:
    """Pre-trade market impact & liquidity horizon estimate (Almgren-Chriss formulation)."""

    order_shares: int
    top_depth_shares: int
    depth_coverage_pct: float
    expected_slippage_bps: float
    expected_slippage_pts: float
    impact_tier: str  # "LOW_IMPACT" | "MODERATE_SLIPPAGE" | "HIGH_IMPACT_SLICING_REQUIRED"
    execution_mode: str  # "DIRECT_MARKET" | "PASSIVE_LIMIT_BID_2" | "TWAP_ICEBERG_3_TRANCHES"
    recommendation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_shares": self.order_shares,
            "top_depth_shares": self.top_depth_shares,
            "depth_coverage_pct": round(self.depth_coverage_pct, 1),
            "expected_slippage_bps": round(self.expected_slippage_bps, 1),
            "expected_slippage_pts": round(self.expected_slippage_pts, 2),
            "impact_tier": self.impact_tier,
            "execution_mode": self.execution_mode,
            "recommendation": self.recommendation,
        }


def estimate_market_impact(
    symbol: str,
    shares: int,
    entry_price: float,
    depth_data: Optional[dict[str, Any]] = None,
    avg_5m_vol: Optional[float] = None,
) -> MarketImpactEstimate:
    """
    Computes pre-trade market impact and expected slippage using top-of-book depth
    and Almgren-Chriss power-law temporary impact estimation.
    """
    if shares <= 0 or entry_price <= 0:
        return MarketImpactEstimate(
            order_shares=0,
            top_depth_shares=1,
            depth_coverage_pct=0.0,
            expected_slippage_bps=0.0,
            expected_slippage_pts=0.0,
            impact_tier="LOW_IMPACT",
            execution_mode="DIRECT_MARKET",
            recommendation="Zero shares specified.",
        )

    # 1. Resolve Top-5 Depth Shares
    top_depth = 0
    spread_pts = max(0.05, round(entry_price * 0.0005, 2))  # baseline 5 bps spread
    if depth_data and isinstance(depth_data, dict):
        asks = depth_data.get("asks", [])
        bids = depth_data.get("bids", [])
        cand_list = asks if asks else bids
        if cand_list:
            top_depth = sum(int(x.get("quantity", 0) or 0) for x in cand_list[:5])
        if asks and bids and asks[0].get("price") and bids[0].get("price"):
            best_ask = float(asks[0]["price"])
            best_bid = float(bids[0]["price"])
            if best_ask > best_bid:
                spread_pts = best_ask - best_bid

    if top_depth <= 0:
        if avg_5m_vol and avg_5m_vol > 0:
            top_depth = max(500, int(avg_5m_vol * 0.08))
        else:
            top_depth = 5000  # Default baseline for liquid F&O equities

    depth_coverage = (shares / max(1, top_depth)) * 100.0
    spread_bps = (spread_pts / entry_price) * 10000.0

    # Almgren-Chriss Temporary Impact Power-Law:
    # Slippage (bps) = Half-Spread + gamma * (order_size / available_depth)^0.6 * base_impact
    gamma_factor = 12.0
    impact_bps = (spread_bps * 0.5) + (gamma_factor * ((shares / max(1, top_depth)) ** 0.6))
    expected_slippage_bps = round(float(impact_bps), 1)
    expected_slippage_pts = round(entry_price * (expected_slippage_bps / 10000.0), 2)

    if depth_coverage <= 5.0 and expected_slippage_bps <= 12.0:
        tier = "LOW_IMPACT"
        exec_mode = "DIRECT_MARKET"
        rec = "Liquid book. Direct market execution authorized with negligible slippage."
    elif depth_coverage <= 15.0 and expected_slippage_bps <= 25.0:
        tier = "MODERATE_SLIPPAGE"
        exec_mode = "PASSIVE_LIMIT_BID_2"
        rec = f"Moderate depth consumption ({depth_coverage:.1f}% of top-5 depth). Recommend limit order at Depth Level 1/2 to save ₹{expected_slippage_pts * shares:,.1f} slippage."
    else:
        tier = "HIGH_IMPACT_SLICING_REQUIRED"
        exec_mode = "TWAP_ICEBERG_3_TRANCHES"
        rec = f"⚠️ HIGH MARKET IMPACT: Order is {depth_coverage:.1f}% of top-5 depth (~{expected_slippage_bps:.1f} bps slippage). Mandate 3-tranche TWAP/Iceberg slicing over 2-3 minutes to prevent dislocation."

    return MarketImpactEstimate(
        order_shares=shares,
        top_depth_shares=top_depth,
        depth_coverage_pct=depth_coverage,
        expected_slippage_bps=expected_slippage_bps,
        expected_slippage_pts=expected_slippage_pts,
        impact_tier=tier,
        execution_mode=exec_mode,
        recommendation=rec,
    )


@dataclass
class PositionSizeResult:
    """Institutional position sizing output."""

    symbol: str
    shares: int
    lots: int
    lot_size: int
    capital_allocated: float
    capital_pct: float
    risk_amount: float
    risk_pct: float
    entry_price: float
    stop_loss: float
    target_price: float
    r_multiple: float
    sizing_model: str
    notes: str = ""
    market_impact: Optional[MarketImpactEstimate] = None
    status: str = "CALCULATED"
    capital_basis: str = "EXPLICIT_BUDGET"
    reason: Optional[str] = None
    recommended_structure: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        d = {
            "symbol": self.symbol,
            "shares": self.shares,
            "lots": self.lots,
            "lot_size": self.lot_size,
            "capital_allocated": round(self.capital_allocated, 2),
            "capital_pct": round(self.capital_pct, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct": round(self.risk_pct, 2),
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_price": round(self.target_price, 2),
            "r_multiple": round(self.r_multiple, 2),
            "sizing_model": self.sizing_model,
            "notes": self.notes,
            "status": self.status,
            "capital_basis": self.capital_basis,
            "reason": self.reason,
            "recommended_structure": self.recommended_structure,
        }
        if self.market_impact:
            d["market_impact"] = self.market_impact.as_dict()
        return d


# Standard F&O Lot Sizes for Indian Instruments (Imported from authoritative SSOT market.instruments)
from market.instruments import STANDARD_LOT_SIZES

_F_AND_O_LOT_SIZES: dict[str, int] = STANDARD_LOT_SIZES


_SORTED_FNO_KEYS: list[str] = sorted(_F_AND_O_LOT_SIZES.keys(), key=len, reverse=True)

# Canonical alias map: feed variants / display names → canonical ticker key
# Covers NSE data-feed quirks like "NIFTY 50" (with space) and "BANK NIFTY".
_SYMBOL_ALIASES: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY50": "NIFTY",
    "NSEI": "NIFTY",
    "CNX NIFTY": "NIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "BANKNIFTY50": "BANKNIFTY",
    "NSEBANK": "BANKNIFTY",
    "FIN NIFTY": "FINNIFTY",
    "MIDCP NIFTY": "MIDCPNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
}


def extract_underlying_symbol(symbol: str) -> Optional[str]:
    """Extract the base underlying ticker from a cash or derivative symbol.

    Handles feed-variant names such as ``"NIFTY 50"`` (with space) by resolving
    them through ``_SYMBOL_ALIASES`` before performing the lot-size table lookup.
    """
    if not symbol:
        return None
    clean = (
        str(symbol)
        .upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("BSE:", "")
        .replace("BFO:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .strip()
    )
    if clean.endswith(("-EQ", "-BE")):
        clean = clean[:-3]
    # Resolve common feed variants / display-name aliases before lookup
    clean = _SYMBOL_ALIASES.get(clean, clean)

    if clean in _F_AND_O_LOT_SIZES:
        return clean
    import re

    for k in _SORTED_FNO_KEYS:
        if clean.startswith(k):
            rest = clean[len(k) :]
            if re.match(r"^\d{2}[A-Z\d]+", rest) or rest.endswith(("CE", "PE", "FUT")):
                return k
    return None


def is_fno_symbol(symbol: str) -> bool:
    """Return True if symbol is traded in the F&O derivatives segment."""
    if not symbol:
        return False
    return extract_underlying_symbol(symbol) is not None


def is_physical_delivery_fno(symbol: str) -> bool:
    """
    Return True if the symbol is a single-stock derivative subject to SEBI compulsory physical settlement.
    Returns False for cash-settled index derivatives (NIFTY, BANKNIFTY, etc.), commodities, and currencies.
    """
    und = extract_underlying_symbol(symbol)
    if not und:
        return False
    from market.instruments import INDEX_SYMBOLS, COMMODITY_SYMBOLS, CURRENCY_SYMBOLS

    clean_und = und.upper().replace(".NS", "").replace("NSE:", "").strip()
    if (
        clean_und in INDEX_SYMBOLS
        or clean_und in COMMODITY_SYMBOLS
        or clean_und in CURRENCY_SYMBOLS
    ):
        return False
    return clean_und in _F_AND_O_LOT_SIZES


def check_sebi_physical_settlement_risk(
    symbol: str,
    dte: Optional[int] = None,
    capital: Optional[float] = None,
    price: Optional[float] = None,
) -> dict[str, Any]:
    """
    Evaluates SEBI physical settlement delivery risk for single-stock derivatives in expiry week (DTE <= 4).
    Uses a conservative full-delivery-value capital check for stock derivatives; missing inputs block the risk decision.
    """
    if not is_physical_delivery_fno(symbol):
        return {
            "applicable": False,
            "blocked": False,
            "requires_full_margin": False,
            "warning": "",
            "required_delivery_capital": 0.0,
        }

    if dte is None:
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "UNAVAILABLE",
            "warning": f"Physical settlement risk for {symbol} is unavailable because contract DTE is missing.",
            "required_delivery_capital": None,
        }
    if dte < 0:
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "EXPIRED_CONTRACT",
            "warning": f"Physical settlement check refused for {symbol}: contract expiry is in the past.",
            "required_delivery_capital": None,
        }
    if dte > 4:
        return {
            "applicable": True,
            "blocked": False,
            "requires_full_margin": False,
            "warning": "",
            "required_delivery_capital": 0.0,
        }

    try:
        current_price = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        current_price = 0.0
    if not math.isfinite(current_price) or current_price <= 0:
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "UNAVAILABLE",
            "warning": f"Physical settlement risk for {symbol} is unavailable because a verified underlying price is missing.",
            "required_delivery_capital": None,
        }
    try:
        available_capital = float(capital) if capital is not None else 0.0
    except (TypeError, ValueError):
        available_capital = 0.0
    if not math.isfinite(available_capital) or available_capital <= 0:
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "UNAVAILABLE",
            "warning": f"Physical settlement risk for {symbol} is unavailable because account capital is missing.",
            "required_delivery_capital": None,
        }

    lot_size = get_lot_size(symbol)
    if lot_size <= 0:
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "UNAVAILABLE",
            "warning": (
                f"Physical settlement risk for {symbol} is unavailable because the exact "
                "contract lot size is not verified in the current exchange master."
            ),
            "required_delivery_capital": None,
        }
    required_capital = lot_size * current_price

    has_full_margin = available_capital >= required_capital
    if not has_full_margin:
        warning_msg = (
            f"SEBI Physical Delivery Risk: '{symbol}' is a single-stock derivative expiring in {dte} day(s). "
            f"The conservative full-delivery-value check is ₹{required_capital:,.2f}, but account "
            f"capital is ₹{available_capital:,.2f}. Prohibiting new overnight position without full delivery margin."
        )
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
            "status": "BLOCKED",
            "warning": warning_msg,
            "required_delivery_capital": required_capital,
        }

    warning_msg = (
        f"SEBI Physical Delivery Notice: '{symbol}' is within final expiry week (DTE={dte}). "
        f"Ensure sufficient delivery margin (₹{required_capital:,.2f}) if intending to hold into expiry."
    )
    return {
        "applicable": True,
        "blocked": False,
        "requires_full_margin": True,
        "status": "AVAILABLE",
        "warning": warning_msg,
        "required_delivery_capital": required_capital,
    }


def get_lot_size(symbol: str) -> int:
    """Resolve exact derivative lot size from the instrument master when available.

    The static underlying map is retained for research sizing and cash instruments,
    but an exact option/future contract must use its own active master row because
    lot sizes can change across contract transitions.
    """
    if not symbol:
        return 1
    raw = str(symbol).strip()
    body = raw.split(":", 1)[-1].upper()
    contract_like = body.endswith(("CE", "PE", "FUT")) and any(char.isdigit() for char in body)
    if contract_like:
        try:
            import market.symbol_master as symbol_master

            sym_info = symbol_master.get_symbol_info(raw)
            if not sym_info and ":" not in raw:
                sym_info = symbol_master.get_symbol_info(f"NFO:{raw}")
            if sym_info:
                lot = sym_info.get("minLotSize") or sym_info.get("lot_size")
                if lot and int(lot) > 0:
                    return int(lot)
        except Exception as e_sym:
            logger.debug("[engine.position_sizer] symbol_master lookup failed: %s", e_sym)

        try:
            from market.contract_selection import resolve_active_contract

            res = resolve_active_contract(raw, require_fresh=True)
            if res.is_valid and res.contract:
                return res.contract.lot_size

            # If this is an exact dated derivative contract, enforce fail-closed zero
            from market.instruments import parse_derivative_contract

            if parse_derivative_contract(raw):
                logger.warning(
                    "[engine.position_sizer] Exact contract has no valid active listed master lot: %s (%s)",
                    raw,
                    res.rejection_reason,
                )
                return 0
        except Exception as exc:
            logger.warning(
                "[engine.position_sizer] Current contract lot lookup degraded for %s: %s",
                raw,
                exc,
            )
            return 0
    # 1. Check verified contract master first if available
    try:
        from market.instrument_master import get_verified_contract

        vc = get_verified_contract(symbol)
        if vc and int(vc.get("lot_size", 0)) > 0:
            return int(vc["lot_size"])
    except Exception as e_suppressed:
        logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")

    # 2. Extract underlying and resolve from canonical lot sizes
    und = extract_underlying_symbol(symbol)
    if und and und in _F_AND_O_LOT_SIZES:
        return _F_AND_O_LOT_SIZES[und]

    return 1


def resolve_payoff_orientation(
    payoff_type: str = "LONG_ASSET",
    direction: Optional[str] = None,
    symbol: str = "",
) -> str:
    """
    Resolve whether the position coordinate orientation is LONG or SHORT.

    A bought option (whether Call or Put) is LONG premium (stop < entry < target).
    A sold option (whether Call or Put) is SHORT premium (target < entry < stop).
    An underlying asset follows directional exposure (Bullish=LONG, Bearish=SHORT).
    """
    p_up = str(payoff_type or "").upper().strip()
    d_up = str(direction or "").upper().strip()
    s_up = str(symbol or "").upper().split(":", 1)[-1].strip()

    if p_up in ("LONG_OPTION", "BUY_OPTION", "OPTION_BUYER", "DEBIT_SPREAD", "LONG_SPREAD"):
        return "LONG"
    if p_up in ("SHORT_OPTION", "SELL_OPTION", "OPTION_SELLER", "CREDIT_SPREAD", "SHORT_SPREAD"):
        return "SHORT"
    if p_up in ("SHORT_ASSET", "EQUITY_SHORT", "FUTURES_SHORT"):
        return "SHORT"

    # Contract ticker heuristics if payoff_type was left as default
    is_opt = s_up.endswith(("CE", "PE")) and any(c.isdigit() for c in s_up)
    if is_opt:
        if d_up in ("BEARISH", "SELL", "SHORT") and s_up.endswith("PE"):
            return "LONG"
        if d_up in ("BULLISH", "BUY", "LONG") and s_up.endswith("CE"):
            return "LONG"

    # If direction is bearish/sell on underlying asset, it is a SHORT position
    if d_up in ("BEARISH", "SELL", "SHORT"):
        return "SHORT"

    if p_up in ("LONG_ASSET", "EQUITY_LONG", "FUTURES_LONG"):
        return "LONG"

    return "LONG"


def calculate_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    capital: Optional[float] = None,
    target_price: Optional[float] = None,
    max_risk_pct: float = 1.5,  # Risk max 1.5% of total capital
    max_capital_pct: Optional[float] = 20.0,  # Max % capital in single stock
    atr: Optional[float] = None,
    sizing_model: str = "atr_volatility",
    win_rate: Optional[float] = None,
    profit_factor: Optional[float] = None,
    is_fno: bool = False,
    vix: Optional[float] = None,
    direction: Optional[str] = None,
    is_research: bool = False,
    account_snapshot: Optional[dict[str, Any]] = None,
    payoff_type: str = "LONG_ASSET",
    margin_required_per_lot: Optional[float] = None,
    max_risk_rupees: Optional[float] = None,
) -> PositionSizeResult:
    """
    Calculate optimal position size based on institutional risk parameters.

    Args:
        symbol: Ticker symbol (e.g. INFY, NIFTY)
        entry_price: Current market price or limit entry
        stop_loss: Technical stop-loss price
        capital: Total trading account capital
        target_price: Expected profit target (defaults to 2R)
        max_risk_pct: Max percentage of portfolio at risk (e.g. 1.5%)
        max_capital_pct: Hard ceiling for total capital allocated to this position
        atr: 14-day Average True Range (if available)
        sizing_model: "atr_volatility" | "fixed_fractional" | "half_kelly"
        win_rate: Historical win rate for Kelly calculation
        profit_factor: Historical win/loss ratio for Kelly calculation
        is_fno: True if trading F&O derivative contracts with lot multipliers
        vix: Current India VIX level for dynamic regime-adaptive risk scaling
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # Auto-detect indices as F&O derivatives
    raw_body = str(symbol or "").upper().split(":", 1)[-1]
    is_derivative_contract = raw_body.endswith(("CE", "PE", "FUT")) and any(
        char.isdigit() for char in raw_body
    )
    if (
        is_fno
        or clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
        or is_derivative_contract
    ):
        lot_size = get_lot_size(symbol)
    else:
        lot_size = 1

    if entry_price <= 0 or not math.isfinite(entry_price):
        if not is_research:
            return PositionSizeResult(
                symbol=clean_sym,
                shares=0,
                lots=0,
                lot_size=lot_size,
                capital_allocated=0.0,
                capital_pct=0.0,
                risk_amount=0.0,
                risk_pct=0.0,
                entry_price=0.0,
                stop_loss=stop_loss,
                target_price=target_price or 0.0,
                r_multiple=0.0,
                sizing_model=sizing_model,
                notes="Non-positive or non-finite entry price",
                status="BLOCKED_INVALID_PRICE",
                capital_basis="UNAVAILABLE",
                reason="Non-positive or non-finite entry price",
            )
        entry_price = 100.0

    # Resolve capital basis and budget
    capital_basis = "EXPLICIT_BUDGET"
    if account_snapshot and isinstance(account_snapshot, dict):
        curr = str(account_snapshot.get("currency") or "INR").upper().strip()
        if curr not in ("INR", "RS", "₹"):
            return PositionSizeResult(
                symbol=clean_sym,
                shares=0,
                lots=0,
                lot_size=lot_size,
                capital_allocated=0.0,
                capital_pct=0.0,
                risk_amount=0.0,
                risk_pct=0.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price or entry_price,
                r_multiple=0.0,
                sizing_model=sizing_model,
                notes=f"Unsupported account currency: {curr}",
                status="BLOCKED_INVALID_CURRENCY",
                capital_basis="UNAVAILABLE",
                reason=f"Unsupported account currency: {curr}",
            )
        avail = account_snapshot.get("available_balance")
        if avail is None:
            avail = account_snapshot.get("net_cash")
        try:
            avail_f = float(avail) if avail is not None else 0.0
        except (TypeError, ValueError):
            avail_f = 0.0
        if avail_f > 0 and math.isfinite(avail_f):
            capital = avail_f
            capital_basis = "ACCOUNT_SNAPSHOT"
        else:
            return PositionSizeResult(
                symbol=clean_sym,
                shares=0,
                lots=0,
                lot_size=lot_size,
                capital_allocated=0.0,
                capital_pct=0.0,
                risk_amount=0.0,
                risk_pct=0.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price or entry_price,
                r_multiple=0.0,
                sizing_model=sizing_model,
                notes="Account snapshot has zero or unverified available capital",
                status="BLOCKED_MISSING_CAPITAL",
                capital_basis="UNAVAILABLE",
                reason="Account snapshot has zero or unverified available capital",
            )
    elif capital is None:
        if not is_research:
            return PositionSizeResult(
                symbol=clean_sym,
                shares=0,
                lots=0,
                lot_size=lot_size,
                capital_allocated=0.0,
                capital_pct=0.0,
                risk_amount=0.0,
                risk_pct=0.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price or entry_price,
                r_multiple=0.0,
                sizing_model=sizing_model,
                notes="Mandatory trading capital budget missing for actionable order",
                status="BLOCKED_MISSING_CAPITAL",
                capital_basis="UNAVAILABLE",
                reason="Mandatory trading capital budget missing for actionable order",
            )
        capital = 100000.0
        capital_basis = "HYPOTHETICAL_RESEARCH"

    if capital <= 0 or not math.isfinite(capital):
        return PositionSizeResult(
            symbol=clean_sym,
            shares=0,
            lots=0,
            lot_size=lot_size,
            capital_allocated=0.0,
            capital_pct=0.0,
            risk_amount=0.0,
            risk_pct=0.0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price or entry_price,
            r_multiple=0.0,
            sizing_model=sizing_model,
            notes="Missing or non-positive capital budget",
            status="BLOCKED_MISSING_CAPITAL",
            capital_basis="UNAVAILABLE",
            reason="Missing or non-positive capital budget",
        )

    # Resolve coordinate orientation: Long vs Short instrument payoff
    orientation = resolve_payoff_orientation(
        payoff_type=payoff_type, direction=direction, symbol=symbol
    )

    if orientation == "LONG":
        if stop_loss <= 0 or stop_loss >= entry_price or not math.isfinite(stop_loss):
            if not is_research:
                return PositionSizeResult(
                    symbol=clean_sym,
                    shares=0,
                    lots=0,
                    lot_size=lot_size,
                    capital_allocated=0.0,
                    capital_pct=0.0,
                    risk_amount=0.0,
                    risk_pct=0.0,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target_price=target_price or entry_price,
                    r_multiple=0.0,
                    sizing_model=sizing_model,
                    notes=f"Invalid long stop-loss {stop_loss}: must be strictly below entry {entry_price}",
                    status="BLOCKED_INVALID_ANCHORS",
                    capital_basis=capital_basis,
                    reason=f"Invalid long stop-loss {stop_loss}: must be strictly below entry {entry_price}",
                )
            stop_loss = round(entry_price * 0.98, 2)

        stop_distance = max(entry_price * 0.001, entry_price - stop_loss)
        if target_price is not None:
            if target_price <= entry_price or not math.isfinite(target_price):
                if not is_research:
                    return PositionSizeResult(
                        symbol=clean_sym,
                        shares=0,
                        lots=0,
                        lot_size=lot_size,
                        capital_allocated=0.0,
                        capital_pct=0.0,
                        risk_amount=0.0,
                        risk_pct=0.0,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        target_price=target_price,
                        r_multiple=0.0,
                        sizing_model=sizing_model,
                        notes=f"Invalid long target {target_price}: must be strictly above entry {entry_price}",
                        status="BLOCKED_INVALID_ANCHORS",
                        capital_basis=capital_basis,
                        reason=f"Invalid long target {target_price}: must be strictly above entry {entry_price}",
                    )
                target_price = round(entry_price + (stop_distance * 2.0), 2)
        else:
            target_price = round(entry_price + (stop_distance * 2.0), 2)

        r_multiple = (target_price - entry_price) / stop_distance if stop_distance > 0 else 2.0

    else:
        if stop_loss <= 0 or stop_loss <= entry_price or not math.isfinite(stop_loss):
            if not is_research:
                return PositionSizeResult(
                    symbol=clean_sym,
                    shares=0,
                    lots=0,
                    lot_size=lot_size,
                    capital_allocated=0.0,
                    capital_pct=0.0,
                    risk_amount=0.0,
                    risk_pct=0.0,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target_price=target_price or entry_price,
                    r_multiple=0.0,
                    sizing_model=sizing_model,
                    notes=f"Invalid short stop-loss {stop_loss}: must be strictly above entry {entry_price}",
                    status="BLOCKED_INVALID_ANCHORS",
                    capital_basis=capital_basis,
                    reason=f"Invalid short stop-loss {stop_loss}: must be strictly above entry {entry_price}",
                )
            stop_loss = round(entry_price * 1.02, 2)

        stop_distance = max(entry_price * 0.001, stop_loss - entry_price)
        if target_price is not None:
            if target_price >= entry_price or target_price <= 0 or not math.isfinite(target_price):
                if not is_research:
                    return PositionSizeResult(
                        symbol=clean_sym,
                        shares=0,
                        lots=0,
                        lot_size=lot_size,
                        capital_allocated=0.0,
                        capital_pct=0.0,
                        risk_amount=0.0,
                        risk_pct=0.0,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        target_price=target_price,
                        r_multiple=0.0,
                        sizing_model=sizing_model,
                        notes=f"Invalid short target {target_price}: must be strictly below entry {entry_price}",
                        status="BLOCKED_INVALID_ANCHORS",
                        capital_basis=capital_basis,
                        reason=f"Invalid short target {target_price}: must be strictly below entry {entry_price}",
                    )
                target_price = round(entry_price - (stop_distance * 2.0), 2)
        else:
            target_price = round(entry_price - (stop_distance * 2.0), 2)

        r_multiple = (entry_price - target_price) / stop_distance if stop_distance > 0 else 2.0

    # Short option sizing check: requires margin and bounded-risk evidence
    if payoff_type == "SHORT_OPTION":
        if margin_required_per_lot is None or margin_required_per_lot <= 0:
            return PositionSizeResult(
                symbol=clean_sym,
                shares=0,
                lots=0,
                lot_size=lot_size,
                capital_allocated=0.0,
                capital_pct=0.0,
                risk_amount=0.0,
                risk_pct=0.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price,
                r_multiple=r_multiple,
                sizing_model=sizing_model,
                notes="Short option sizing requires margin and bounded-risk evidence",
                status="BLOCKED_UNBOUNDED_RISK",
                capital_basis=capital_basis,
                reason="Short option sizing requires margin and bounded-risk evidence",
            )

    # India VIX Volatility Regime Scaling
    effective_risk_pct = max_risk_pct
    vix_note = ""

    # If VIX is not explicitly passed, query the live/cached market regime gate
    if vix is None:
        try:
            from engine.market_regime_gate import get_cached_regime

            _reg = get_cached_regime()
            if _reg and _reg.vix:
                vix = float(_reg.vix)
        except Exception as e_suppressed:
            logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")

    if vix is not None and vix > 0:
        if vix >= 25.0:
            effective_risk_pct = round(
                max_risk_pct * 0.50, 2
            )  # Cut risk in half during extreme turbulence
            vix_note = f" [VIX={vix:.1f} EXTREME: Risk scaled down 50% to {effective_risk_pct}%]"
        elif vix >= 18.0:
            effective_risk_pct = round(
                max_risk_pct * 0.70, 2
            )  # Scale down 30% during elevated volatility
            vix_note = f" [VIX={vix:.1f} ELEVATED: Risk scaled down 30% to {effective_risk_pct}%]"
        elif vix < 12.0:
            effective_risk_pct = round(
                max_risk_pct * 0.75, 2
            )  # Scale down 25% during low-volatility compression (diminished follow-through)
            vix_note = (
                f" [VIX={vix:.1f} COMPRESSION: Risk scaled down 25% to {effective_risk_pct}%]"
            )

    # Market Regime Gate Sizing Coupling (Edgeless Chop / Locomotive Polarization)
    try:
        from engine.market_regime_gate import get_cached_regime

        _cached_reg = get_cached_regime()
        if _cached_reg:
            if _cached_reg.is_edgeless:
                effective_risk_pct = round(effective_risk_pct * 0.25, 2)
                vix_note += " [EDGELESS CHOP: Risk scaled down to 25% to preserve capital]"
            elif getattr(_cached_reg, "is_locomotive_polarized", False):
                effective_risk_pct = round(effective_risk_pct * 0.50, 2)
                vix_note += " [LOCOMOTIVE POLARIZATION: Risk scaled down 50%]"
    except Exception as e_suppressed:
        logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")

    # Dollar risk budget
    risk_budget = capital * (effective_risk_pct / 100.0) if capital else (max_risk_rupees or 1000.0)
    if max_risk_rupees is not None and max_risk_rupees > 0:
        vix_factor = (effective_risk_pct / max_risk_pct) if max_risk_pct > 0 else 1.0
        capped_rupees = max_risk_rupees * vix_factor
        if capital:
            risk_budget = min(risk_budget, capped_rupees)
        else:
            risk_budget = capped_rupees

    # 1. Compute Raw Shares based on chosen model
    if sizing_model == "atr_volatility":
        effective_atr = atr if atr and atr > 0 else (stop_distance * 0.8)
        vol_stop = max(stop_distance, effective_atr * 1.5)
        raw_shares = int(risk_budget / vol_stop)
        notes = f"Sized using ATR Volatility Parity ({vol_stop:.1f} pts risk per share).{vix_note}"

    elif sizing_model == "half_kelly":
        if win_rate is None or profit_factor is None:
            raise ValueError(
                "sizing_model='half_kelly' requires empirical win_rate and profit_factor; static defaults are prohibited."
            )
        b = max(0.01, profit_factor)
        p = max(0.0, min(1.0, win_rate))
        full_kelly = (p * b - (1.0 - p)) / b
        if full_kelly <= 0:
            half_kelly_frac = 0.0
            allocated = 0.0
            raw_shares = 0
            notes = f"Sized via Half-Kelly: Non-positive edge ({full_kelly:.3f}) — zero capital allocated.{vix_note}"
        else:
            cap_fraction = (max_capital_pct / 100.0) if max_capital_pct else 0.20
            half_kelly_frac = min(cap_fraction, full_kelly * 0.5)
            allocated = capital * half_kelly_frac
            raw_shares = int(allocated / entry_price)
            notes = f"Sized via Half-Kelly ({half_kelly_frac * 100:.1f}% capital allocation for {p * 100:.0f}% win-rate).{vix_note}"

    else:  # fixed_fractional
        raw_shares = int(risk_budget / stop_distance)
        notes = f"Sized strictly on stop distance ({stop_distance:.2f} pts) at {effective_risk_pct}% risk.{vix_note}"

    # 2. Apply Capital Ceiling if configured
    if max_capital_pct is not None and max_capital_pct > 0:
        max_capital_budget = capital * (max_capital_pct / 100.0)
        capital_limited_shares = int(max_capital_budget / entry_price)
        shares = min(raw_shares, capital_limited_shares)
    else:
        shares = raw_shares

    # 3. Lot-size rounding if derivative
    if is_derivative_contract and lot_size <= 0:
        shares = 0
        lots = 0
        notes += (
            " [UNAVAILABLE_CONTRACT_MASTER: Exact derivative lot size is not verified; "
            "no executable quantity is authorized.]"
        )
    elif lot_size > 1:
        lots = shares // lot_size
        shares = lots * lot_size
        if lots == 0:
            one_lot_risk = lot_size * stop_distance
            one_lot_capital = lot_size * entry_price
            notes += (
                " [ZERO_LOT_RISK_BUDGET: No order size is authorized; one lot would risk "
                f"₹{one_lot_risk:,.2f} against a ₹{risk_budget:,.2f} risk budget and require "
                f"₹{one_lot_capital:,.2f} capital before margin.]"
            )
    else:
        # Do not force a minimum share when the configured risk budget rounds
        # below one share. Zero is a valid, non-executable sizing result.
        shares = max(0, shares)
        lots = shares

    capital_allocated = shares * entry_price
    capital_pct = (capital_allocated / capital) * 100.0 if capital > 0 else 0.0
    actual_risk = shares * stop_distance
    actual_risk_pct = (actual_risk / capital) * 100.0 if capital > 0 else 0.0

    if (is_fno or lot_size > 1) and lots == 1 and actual_risk_pct > max_risk_pct:
        notes += f" [HIGH_TICKET_RISK: Single lot risk ({actual_risk_pct:.1f}%) exceeds max risk tolerance ({max_risk_pct:.1f}%). Consider cash equity shares or defined-risk spread.]"

    # 4. Pre-Trade Market Impact & Liquidity Horizon Evaluation
    impact = estimate_market_impact(
        symbol=clean_sym,
        shares=shares,
        entry_price=entry_price,
    )
    if impact.impact_tier == "HIGH_IMPACT_SLICING_REQUIRED":
        notes += f" [{impact.recommendation}]"

    status = "CALCULATED" if not is_research else "RESEARCH_ONLY"
    reason = None
    if is_derivative_contract and lot_size <= 0:
        status = "UNAVAILABLE_CONTRACT_MASTER"
        reason = "Exact derivative lot size is not verified in active master"
    elif lot_size > 1 and lots == 0:
        status = "ZERO_LOT_RISK_BUDGET"
        reason = f"Risk budget ₹{risk_budget:,.2f} insufficient for 1 lot"
    elif shares == 0:
        status = "ZERO_QUANTITY_RISK_BUDGET"
        reason = f"Risk budget ₹{risk_budget:,.2f} insufficient for 1 share"

    # 5. Market Dynamics Governor: Adaptive Volatility & Strategy Vehicle Alignment
    recommended_structure = None
    try:
        from engine.market_dynamics_governor import get_market_dynamics_governor

        calib = get_market_dynamics_governor().get_calibration(clean_sym, vix_override=vix)
        recommended_structure = calib.preferred_vehicle

        if calib.stock_options_quarantined and (is_fno or lot_size > 1):
            recommended_structure = "FUTURES_OR_FAR_MONTH"
            notes += " [DELIVERY_QUARANTINE: SEBI physical settlement risk; stock options quarantined to Futures/Far-Month]"

        if (
            (calib.volatility_regime == "CRISIS_VIX" or calib.mandate == "FADE_SPRING")
            and (is_fno or lot_size > 1)
            and lots > 1
        ):
            haircut_lots = max(1, int(lots * 0.50))
            if haircut_lots < lots:
                notes += f" [MARKET_GOVERNOR: {calib.volatility_regime} 50% lot haircut applied ({lots} -> {haircut_lots} lots)]"
                lots = haircut_lots
                shares = lots * lot_size if lot_size > 1 else lots
                capital_allocated = shares * entry_price
                capital_pct = (capital_allocated / capital) * 100.0 if capital > 0 else 0.0
                actual_risk = shares * stop_distance
                actual_risk_pct = (actual_risk / capital) * 100.0 if capital > 0 else 0.0
    except Exception as e_gov:
        logger.debug(f"[position_sizer] Market Dynamics Governor query suppressed: {e_gov}")

    return PositionSizeResult(
        symbol=clean_sym,
        shares=shares,
        lots=lots,
        lot_size=lot_size,
        capital_allocated=capital_allocated,
        capital_pct=capital_pct,
        risk_amount=actual_risk,
        risk_pct=actual_risk_pct,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_price=target_price,
        r_multiple=r_multiple,
        sizing_model=sizing_model,
        notes=notes,
        market_impact=impact,
        status=status,
        capital_basis=capital_basis,
        reason=reason,
        recommended_structure=recommended_structure,
    )


def calculate_volatility_risk_parity_size(
    symbol: str,
    entry_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    capital: Optional[float] = None,
    target_risk_pct: float = 1.0,
    max_margin_pct: float = 25.0,
    atr: Optional[float] = None,
    is_fno: Optional[bool] = None,
    alert_type: Optional[str] = None,
) -> PositionSizeResult:
    """
    Automated Volatility Risk-Parity Position Sizing Engine.

    Calculates lot sizing such that rupee risk contribution is equalized across all assets
    regardless of whether the instrument is a volatile midcap or a low-beta heavyweight.
    Automatically fetches 14-period daily ATR, live LTP, and available margin if omitted.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # 1. Resolve Capital from Broker Funds if omitted
    if capital is None or capital <= 0:
        try:
            from brokers.session import get_execution_broker

            exec_broker = get_execution_broker()
            if exec_broker:
                funds = exec_broker.get_funds()
                avail = float(
                    getattr(funds, "available_cash", 0.0)
                    or getattr(funds, "available_margin", 0.0)
                    or getattr(funds, "total_balance", 0.0)
                    or 0.0
                )
                if avail > 0:
                    capital = avail
        except Exception as e_suppressed:
            logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")
        if capital is None or capital <= 0:
            capital = 100000.0

    # 2. Resolve live entry price if omitted
    if entry_price is None or entry_price <= 0:
        try:
            from market.quotes import get_ltp

            entry_price = float(get_ltp(f"NSE:{clean_sym}") or get_ltp(clean_sym) or 0.0)
        except Exception as e_suppressed:
            logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")
        if entry_price is None or entry_price <= 0:
            entry_price = 100.0

    # 3. Resolve 14-period ATR if omitted
    if atr is None or atr <= 0:
        try:
            from market.history import get_historical_data
            from analysis.technical import atr as calc_atr

            df = get_historical_data(clean_sym, interval="1d", days=60)
            if df is not None and len(df) >= 14:
                atr_series = calc_atr(df, period=14).dropna()
                if not atr_series.empty:
                    val = float(atr_series.iloc[-1])
                    if val > 0:
                        atr = val
        except Exception as e_suppressed:
            logger.debug(f"[engine.position_sizer] Non-fatal exception suppressed: {e_suppressed}")
        if atr is None or atr <= 0:
            atr = max(round(entry_price * 0.015, 2), 1.0)

    # 4. Resolve stop-loss if omitted (1.5 x ATR structural trailing floor)
    if stop_loss is None or stop_loss <= 0 or stop_loss >= entry_price:
        stop_loss = round(max(0.05, entry_price - (atr * 1.5)), 2)

    # 5. Auto-detect F&O eligibility (derivatives / indices default to lots, stocks default to cash equity)
    if is_fno is None:
        import re

        is_derivative_contract = bool(re.search(r"(?:FUT|\d+(?:CE|PE))$", clean_sym))
        is_index = clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
        is_fno = is_derivative_contract or is_index

    # 6. Execute core ATR volatility parity calculation
    result = calculate_position_size(
        symbol=clean_sym,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=capital,
        max_risk_pct=target_risk_pct,
        max_capital_pct=max_margin_pct,
        atr=atr,
        sizing_model="atr_volatility",
        is_fno=is_fno,
    )

    # 7. Apply detector-specific conviction lot scaling if provided. A dampener
    # may reduce the result to zero; it must not reintroduce a minimum lot.
    if alert_type and result.lot_size > 1 and result.lots >= 1:
        mult = get_detector_lot_multiplier(alert_type)
        if mult != 1.0:
            adj_lots = max(0, int(round(result.lots * mult)))
            adj_shares = adj_lots * result.lot_size
            adj_capital = adj_shares * result.entry_price
            adj_risk = adj_shares * abs(result.entry_price - result.stop_loss)
            result = PositionSizeResult(
                symbol=result.symbol,
                shares=adj_shares,
                lots=adj_lots,
                lot_size=result.lot_size,
                capital_allocated=adj_capital,
                capital_pct=(adj_capital / capital) * 100.0 if capital > 0 else 0.0,
                risk_amount=adj_risk,
                risk_pct=(adj_risk / capital) * 100.0 if capital > 0 else 0.0,
                entry_price=result.entry_price,
                stop_loss=result.stop_loss,
                target_price=result.target_price,
                r_multiple=result.r_multiple,
                sizing_model="atr_volatility",
                notes=(
                    f"{result.notes} [Detector '{alert_type}' {mult:.2f}x sizing applied: "
                    f"{adj_lots} lots; no minimum lot is forced.]"
                ),
            )

    vol_pct = (atr / entry_price) * 100.0
    result.notes = f"Volatility Risk-Parity (14-ATR: ₹{atr:.2f} [{vol_pct:.2f}%]) | Margin Cap: {max_margin_pct}% | {result.notes}"
    return result


# ── Detector-Specific Lot Quantization ───────────────────────────────────────
# Derived from EOD session diagnostics (2026-09-24): empirically-proven high-conviction
# detectors receive a 1.25x lot premium; low-conviction counter-trend detectors are
# dampened to 0.5x to preserve positive expected-value across the portfolio.
# These multipliers are applied AFTER standard lot-size rounding so F&O contract
# integrity is always maintained. A zero-lot result remains non-executable.

_DETECTOR_LOT_MULTIPLIERS: dict[str, float] = {
    # ── High-Conviction: 1.25× premium ──────────────────────────────────────
    # ORB_BREAKOUT: Opening Range Breakout with directional institutional commitment
    "ORB_BREAKOUT": 1.25,
    # INDEX_CALL_SETUP / INDEX_PUT_SETUP: Index-level momentum with broad beta confirmation
    "INDEX_CALL_SETUP": 1.25,
    "INDEX_PUT_SETUP": 1.25,
    # GAMMA_BLAST on index (vol OI unwind + VWAP reclaim): multi-confluence ignition
    "GAMMA_BLAST": 1.15,
    # OPENING_DRIVE: First 30-minute institutional momentum surge with volume expansion
    "OPENING_DRIVE": 1.15,
    # ── Standard: 1.0× (no adjustment) ─────────────────────────────────────
    "OPTIONS_MOMENTUM": 1.0,
    "SQUEEZE_BREAKOUT": 1.0,
    "SMC_SWEEP": 1.0,
    "CIRCUIT_WARNING": 1.0,
    "PRECURSOR_RADAR": 1.0,
    "CONFLUENCE_INFLECTION": 1.0,
    "COMMODITY_MOMENTUM": 1.0,
    "CURRENCY_BREAKOUT": 1.0,
    "MULTIBAGGER": 1.0,
    # ── Counter-Trend: 0.5× dampened (high false-positive rate) ─────────────
    # Pure counter-trend setups statistically fail 70%+ of the time on Indian
    # markets intraday, where momentum and trend regimes dominate.
    "COUNTER_TREND": 0.5,
    "REVERSAL_BULL": 0.5,
    "REVERSAL_BEAR": 0.5,
    "MEAN_REVERSION": 0.5,
    "INTRADAY_REVERSAL": 0.5,
}


_CONVICTION_TIER_LOT_MULTIPLIERS: dict[str, float] = {
    "APEX_CONFLUENCE": 1.25,  # +25% sizing for institutional alpha setups (>=90% conviction)
    "HIGH_CONVICTION": 1.0,  # Baseline institutional sizing (80-89% conviction)
    "DEFINED_RISK_ONLY": 0.65,  # -35% risk compression for tier-3 defined-risk setups (70-79% conviction)
    "LOW_CONVICTION": 0.50,  # Damped sizing for marginal setups (<70%)
}

_CHEETAH_MANDATE_MULTIPLIERS: dict[str, float] = {
    "CHEETAH_POUNCE_MOMENTUM": 1.15,  # Trending expansion confirmation -> +15% size
    "CHEETAH_SPRING_INVERSION": 1.0,  # Asymmetric Wyckoff trap inversion -> baseline size
    "CHEETAH_SELECTIVE_SNIPER": 0.70,  # Selective sniper mode in mixed chop -> 30% risk compression
    "CHEETAH_STALKING_PRESERVE_CAPITAL": 0.50,  # Capital preservation stalk -> 50% risk compression
}


def get_detector_lot_multiplier(alert_type: str) -> float:
    """
    Returns the detector-specific lot quantization multiplier for ``alert_type``.

    High-conviction setups (ORB_BREAKOUT, INDEX_CALL_SETUP, INDEX_PUT_SETUP) → 1.25×
    Standard momentum setups → 1.0×
    Counter-trend / reversal setups → 0.5×
    Unknown alert types → 1.0× (safe default)
    """
    return _DETECTOR_LOT_MULTIPLIERS.get(str(alert_type).upper(), 1.0)


def get_conviction_tier_lot_multiplier(conviction_tier: Optional[str]) -> float:
    """Returns lot sizing multiplier based on institutional conviction tier."""
    if not conviction_tier:
        return 1.0
    return _CONVICTION_TIER_LOT_MULTIPLIERS.get(str(conviction_tier).upper(), 1.0)


def calculate_position_size_for_alert(
    alert_type: str,
    symbol: str,
    entry_price: float,
    stop_loss: float,
    capital: Optional[float] = None,
    target_price: Optional[float] = None,
    max_risk_pct: float = 1.5,
    max_capital_pct: Optional[float] = 20.0,
    atr: Optional[float] = None,
    sizing_model: str = "atr_volatility",
    win_rate: Optional[float] = None,
    profit_factor: Optional[float] = None,
    is_fno: bool = False,
    vix: Optional[float] = None,
    conviction_tier: Optional[str] = None,
    is_physical_expiry_week: bool = False,
    cheetah_mandate: Optional[str] = None,
    strike_clock_zone: Optional[str] = None,
    direction: Optional[str] = None,
    is_research: bool = False,
    account_snapshot: Optional[dict[str, Any]] = None,
    payoff_type: str = "LONG_ASSET",
    margin_required_per_lot: Optional[float] = None,
    max_risk_rupees: Optional[float] = None,
) -> PositionSizeResult:
    """
    Detector-aware and conviction-tier-calibrated position sizing.

    Combines detector-specific historical edge multipliers with conviction tier
    allocations (APEX_CONFLUENCE: 1.25×, DEFINED_RISK_ONLY: 0.65×), cheetah regime multipliers,
    and predatory strike clock kill zone timing calibration (Lunchtime chop: 0.75×, Power Hour: 1.10×).
    Applies regulatory SEBI physical settlement discount (0.50×) for single-stock
    F&O during expiry week.

    Lot counts are always rounded down to maintain F&O contract integrity.
    The multiplier is logged in ``PositionSizeResult.notes`` for full traceability.
    """
    # 1. Compute baseline position size using standard engine
    base = calculate_position_size(
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=capital,
        target_price=target_price,
        max_risk_pct=max_risk_pct,
        max_capital_pct=max_capital_pct,
        atr=atr,
        sizing_model=sizing_model,
        win_rate=win_rate,
        profit_factor=profit_factor,
        is_fno=is_fno,
        vix=vix,
        direction=direction,
        is_research=is_research,
        account_snapshot=account_snapshot,
        payoff_type=payoff_type,
        margin_required_per_lot=margin_required_per_lot,
        max_risk_rupees=max_risk_rupees,
    )

    # 2. Resolve combined detector, conviction tier, cheetah regime & strike clock multiplier
    detector_multiplier = get_detector_lot_multiplier(alert_type)
    tier_multiplier = get_conviction_tier_lot_multiplier(conviction_tier)
    cheetah_mult = (
        _CHEETAH_MANDATE_MULTIPLIERS.get(str(cheetah_mandate).upper(), 1.0)
        if cheetah_mandate
        else 1.0
    )
    clock_mult = 1.0
    if strike_clock_zone:
        sc_upper = str(strike_clock_zone).upper()
        if "LUNCH" in sc_upper or "CHOP_ZONE" in sc_upper:
            clock_mult = 0.75  # Midday turnover vacuum capital preservation
        elif "POWER_HOUR" in sc_upper or "GAMMA_POWER" in sc_upper:
            clock_mult = 1.10  # Power hour institutional breakout thrust

    combined_multiplier = round(
        detector_multiplier * tier_multiplier * cheetah_mult * clock_mult, 2
    )

    # 3. SEBI Physical Delivery Settlement Protection for single-stock options
    physical_discount_applied = False
    is_index = any(
        idx in symbol.upper()
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    )
    if is_physical_expiry_week and is_fno and not is_index:
        combined_multiplier = round(combined_multiplier * 0.50, 2)
        physical_discount_applied = True

    # 4. No adjustment needed for standard multiplier (1.0×)
    if combined_multiplier == 1.0:
        return base
    if base.lots <= 0:
        if combined_multiplier != 1.0:
            base.notes = (
                f"{base.notes} | [Sizing modifier {conviction_tier or alert_type}: "
                f"{combined_multiplier:.2f}x; risk budget remains zero lots, "
                "so no minimum lot is forced.]"
            )
        if physical_discount_applied:
            base.notes = (
                f"{base.notes} | [SEBI Physical Settlement] 50% lot discount applied; "
                "risk budget already sizes to zero lots."
            )
        return base

    # 4. Apply combined multiplier to lots (always round down to whole contracts)
    raw_lots = base.lots * combined_multiplier
    adjusted_lots = max(0, int(raw_lots))  # Zero lots when the risk budget cannot fund one lot

    # Bound by exact rupee risk cap if specified
    if max_risk_rupees is not None and max_risk_rupees > 0:
        stop_dist = abs(base.entry_price - base.stop_loss)
        if base.lot_size > 0 and stop_dist > 0:
            max_allowed_lots = int(max_risk_rupees / (base.lot_size * stop_dist))
            adjusted_lots = min(adjusted_lots, max_allowed_lots)

    # 5. Recompute derived fields from adjusted lots
    adjusted_shares = adjusted_lots * base.lot_size
    adjusted_capital = adjusted_shares * base.entry_price
    adjusted_capital_pct = (adjusted_capital / capital) * 100.0 if capital > 0 else 0.0
    stop_distance = abs(base.entry_price - base.stop_loss)
    adjusted_risk = adjusted_shares * stop_distance
    adjusted_risk_pct = (adjusted_risk / capital) * 100.0 if capital > 0 else 0.0

    mult_label = (
        f"+{int((combined_multiplier - 1.0) * 100)}%"
        if combined_multiplier > 1.0
        else f"-{int((1.0 - combined_multiplier) * 100)}%"
    )
    tier_tag = f"Tier [{conviction_tier}] {tier_multiplier:.2f}x | " if conviction_tier else ""
    adjusted_notes = (
        f"{base.notes} | {tier_tag}Detector [{alert_type}] combined multiplier {combined_multiplier:.2f}x ({mult_label}): "
        f"{base.lots} → {adjusted_lots} lots."
    )
    if physical_discount_applied:
        adjusted_notes += " | [SEBI Physical Settlement] 50% lot discount applied"

    return PositionSizeResult(
        symbol=base.symbol,
        shares=adjusted_shares,
        lots=adjusted_lots,
        lot_size=base.lot_size,
        capital_allocated=adjusted_capital,
        capital_pct=adjusted_capital_pct,
        risk_amount=adjusted_risk,
        risk_pct=adjusted_risk_pct,
        entry_price=base.entry_price,
        stop_loss=base.stop_loss,
        target_price=base.target_price,
        r_multiple=base.r_multiple,
        sizing_model=base.sizing_model,
        notes=adjusted_notes,
        market_impact=base.market_impact,
        status=base.status,
        capital_basis=base.capital_basis,
        reason=base.reason,
        recommended_structure=base.recommended_structure,
    )


def generate_execution_ticket(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    target_price: Optional[float] = None,
    capital: float = 100000.0,
    max_risk_pct: float = 1.0,
    direction: str = "BULLISH",
    alert_type: Optional[str] = None,
    is_fno: bool = False,
    order_type: str = "LIMIT",
    conviction_tier: Optional[str] = None,
    execution_friction_badge: Optional[str] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    segment: str | None = None,
) -> dict[str, Any]:
    """
    Builds a capital-calibrated order draft. It is executable only when the risk
    budget funds a positive canonical quantity and a master-backed routing plan exists.
    """
    raw_symbol = str(symbol or "").strip()
    clean_sym = raw_symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # An actionable ticket must contain explicit, directionally valid levels.
    # The research sizing helper retains its historical convenience defaults,
    # but those defaults must never be promoted to an execution ticket.
    if not math.isfinite(float(entry_price)) or entry_price <= 0:
        raise ValueError("A finite positive entry price is required for an execution ticket")
    if not math.isfinite(float(stop_loss)) or stop_loss <= 0:
        raise ValueError(
            "A finite positive structural stop-loss is required for an execution ticket"
        )
    if target_price is None or not math.isfinite(float(target_price)) or target_price <= 0:
        raise ValueError("An explicit finite positive target is required for an execution ticket")
    is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")
    if (is_bullish and not (stop_loss < entry_price < target_price)) or (
        not is_bullish and not (target_price < entry_price < stop_loss)
    ):
        raise ValueError("Entry, stop-loss and target are not directionally coherent")

    # Execution sizing must use a current exact contract master row; the
    # underlying static research map cannot authorize an order ticket.
    raw_body = raw_symbol.split(":", 1)[-1].upper()
    contract_like = raw_body.endswith(("CE", "PE", "FUT")) and any(
        char.isdigit() for char in raw_body
    )
    if contract_like:
        from market.symbol_master import get_symbol_info

        contract_info = get_symbol_info(raw_symbol, require_fresh=True)
        try:
            canonical_lot_size = int((contract_info or {}).get("minLotSize", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Current contract lot size is invalid for {raw_symbol}") from exc
        if canonical_lot_size <= 0:
            raise RuntimeError(f"Current contract lot size is unavailable for {raw_symbol}")

    if alert_type:
        res = calculate_position_size_for_alert(
            symbol=raw_symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            alert_type=alert_type,
            capital=capital,
            target_price=target_price,
            max_risk_pct=max_risk_pct,
            is_fno=is_fno or contract_like,
            conviction_tier=conviction_tier,
        )
    else:
        res = calculate_position_size(
            symbol=raw_symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            capital=capital,
            target_price=target_price,
            max_risk_pct=max_risk_pct,
            is_fno=is_fno or contract_like,
        )

    side = "BUY" if direction.upper() in ("BULLISH", "BUY", "LONG") else "SELL"

    # Strict Limit & Midpoint Enforcer for F&O derivatives
    is_opt = (
        is_fno
        or any(token in clean_sym for token in ("CE", "PE", "CALL", "PUT"))
        or (alert_type and "OPTION" in alert_type.upper())
    )
    final_order_type = order_type
    ticket_notes = res.notes
    final_limit_price = round(entry_price, 2)
    midpoint_price = None

    if is_opt and str(final_order_type).upper() == "MARKET":
        final_order_type = "LIMIT"
        f_note = "Market order prohibited on F&O options; converted to LIMIT"
        ticket_notes = f"{ticket_notes} | {f_note}" if ticket_notes else f_note

    if execution_friction_badge and (
        "STRICT LIMIT" in execution_friction_badge.upper()
        or "WIDE SPREAD" in execution_friction_badge.upper()
    ):
        final_order_type = "LIMIT"
        f_note = "Strict LIMIT order enforced due to wide bid-ask spread"
        ticket_notes = f"{ticket_notes} | {f_note}" if ticket_notes else f_note

    if bid is not None and ask is not None and bid > 0 and ask > 0:
        midpoint_price = round((bid + ask) / 2.0, 2)
        spread_pct = round(((ask - bid) / ask) * 100.0, 2)
        if spread_pct > 1.8 or is_opt:
            final_order_type = "LIMIT"
            final_limit_price = midpoint_price
            f_note = f"Pegged to midpoint limit ₹{midpoint_price:,.2f} ({spread_pct:.1f}% B/A spread) to eliminate slippage"
            ticket_notes = f"{ticket_notes} | {f_note}" if ticket_notes else f_note

    # Tick-size quantization (0.05 standard NSE/NFO)
    final_limit_price = round(round(final_limit_price / 0.05) * 0.05, 2)

    # A zero-lot result is a blocked sizing outcome, never a forced minimum
    # order. Keep the setup visible for review without creating an executable
    # SOR plan. Preserve the caller's exchange-qualified symbol for master lookup.
    execution_status = "READY"
    sor_payload: dict[str, Any] | None = None
    auto_submit_ready = True
    if res.shares <= 0 or res.lots <= 0:
        execution_status = "BLOCKED_RISK_BUDGET"
        auto_submit_ready = False
        ticket_notes = (
            f"{ticket_notes} | Order blocked: risk budget cannot fund one canonical share/lot."
            if ticket_notes
            else "Order blocked: risk budget cannot fund one canonical share/lot."
        )
    else:
        from engine.smart_order_router import build_smart_execution_plan

        sor_plan = build_smart_execution_plan(
            symbol=raw_symbol,
            side=side,
            total_quantity=res.shares,
            ltp=entry_price,
            lot_size=res.lot_size,
            segment=segment,
        )
        sor_payload = sor_plan.to_dict()

    return {
        "symbol": clean_sym,
        "side": side,
        "order_type": final_order_type,
        "limit_price": final_limit_price,
        "bid": bid,
        "ask": ask,
        "midpoint_price": midpoint_price,
        "shares": res.shares,
        "lots": res.lots,
        "lot_size": res.lot_size,
        "stop_loss": round(stop_loss, 2),
        "target_price": round(res.target_price, 2),
        "risk_amount_inr": round(res.risk_amount, 2),
        "capital_allocated_inr": round(res.capital_allocated, 2),
        "capital_pct": round(res.capital_pct, 2),
        "risk_pct": round(res.risk_pct, 2),
        "risk_reward_ratio": round(res.r_multiple, 2),
        "sizing_model": res.sizing_model,
        "execution_status": execution_status,
        "auto_submit_ready": auto_submit_ready,
        "smart_routing": sor_payload,
        "notes": ticket_notes,
        "conviction_tier": conviction_tier,
        "execution_friction_badge": execution_friction_badge,
    }


def calibrate_off_number_stop(
    direction: str,
    raw_stop: float,
    atr: float,
    tick_size: float = 0.05,
) -> float:
    """
    Calibrates stop-loss placement away from psychological round numbers (magnets for stop-runs).
    Institutional market makers run stops 2-5 ticks through major round numbers before reversing.
    If the calculated raw stop is within 0.15% of a round number (e.g. 50, 100, 500, 1000, 2500),
    this buffers the stop outside the liquidity hunting pool.
    """
    if raw_stop <= 0:
        return raw_stop

    is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")
    buffer = max(0.15 * atr, 3 * tick_size, raw_stop * 0.0015)

    # Determine relevant round intervals based on magnitude
    if raw_stop >= 1000:
        intervals = [500.0, 100.0, 50.0]
    elif raw_stop >= 100:
        intervals = [50.0, 10.0, 5.0]
    else:
        intervals = [5.0, 1.0, 0.5]

    for interval in intervals:
        nearest_round = round(raw_stop / interval) * interval
        dist_to_round = abs(raw_stop - nearest_round)
        # If raw_stop is within 0.15% of this psychological round level
        if dist_to_round <= (raw_stop * 0.0015):
            if is_bullish:
                # For Long trades, stop must be placed BELOW the round level
                calibrated = min(raw_stop, nearest_round - buffer)
                return round(round(calibrated / tick_size) * tick_size, 2)
            else:
                # For Short trades, stop must be placed ABOVE the round level
                calibrated = max(raw_stop, nearest_round + buffer)
                return round(round(calibrated / tick_size) * tick_size, 2)

    return round(round(raw_stop / tick_size) * tick_size, 2)


# ── Hierarchical Dynamic Risk Scaling Re-exports ─────────────────────────────


# ── Episodic Memory Quarter-Kelly Optimal Position Sizer ─────────────────────


@dataclass
class EpisodicKellySizingResult:
    symbol: str
    direction: str
    allocated_shares: int
    allocated_lots: int
    lot_size: int
    risk_inr: float
    risk_pct_of_capital: float
    capital_allocated_inr: float
    raw_kelly_fraction: float
    quarter_kelly_multiplier: float
    empirical_win_rate_pct: float
    empirical_avg_mfe_r: float
    empirical_avg_mae_r: float
    sample_size: int
    confidence_calibration: str
    heuristic_guidance: str
    base_result: PositionSizeResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "allocated_shares": self.allocated_shares,
            "allocated_lots": self.allocated_lots,
            "lot_size": self.lot_size,
            "risk_inr": self.risk_inr,
            "risk_pct_of_capital": self.risk_pct_of_capital,
            "capital_allocated_inr": self.capital_allocated_inr,
            "kelly_fraction": self.raw_kelly_fraction,
            "kelly_multiplier": self.quarter_kelly_multiplier,
            "empirical_win_rate_pct": self.empirical_win_rate_pct,
            "empirical_avg_mfe_r": self.empirical_avg_mfe_r,
            "empirical_avg_mae_r": self.empirical_avg_mae_r,
            "sample_size": self.sample_size,
            "confidence_calibration": self.confidence_calibration,
            "heuristic_guidance": self.heuristic_guidance,
            "base_position_size": self.base_result.as_dict(),
        }


def calculate_episodic_kelly_position_size(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_price: Optional[float] = None,
    capital: float = 100000.0,
    day_archetype: str = "NORMAL_DAY",
    vix_regime: str = "NORMAL_IV",
    vpin_regime: str = "LOW_TOXICITY",
    max_risk_pct: float = 1.5,
    is_fno: bool = False,
    alert_type: str = "MOMENTUM",
) -> EpisodicKellySizingResult:
    """
    Computes Kelly-Optimal position sizing grounded in Episodic Memory empirical win rates.
    Applies Quarter-Kelly calibration to prevent ruin and scale capital intelligently.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    norm_dir = "BULLISH" if direction.upper() in ("BULLISH", "BUY", "LONG", "CE") else "BEARISH"

    sample_size = 0
    win_rate = 55.0
    avg_mfe = 2.0
    avg_mae = 0.8
    calib = "NEUTRAL_CALIBRATION"
    heuristic = "Standard baseline volatility risk-parity allocation."

    try:
        from engine.episodic_memory import get_episodic_memory_store

        store = get_episodic_memory_store()
        analogies = store.query_analogous_episodes(
            symbol=clean_sym,
            direction=norm_dir,
            vix_regime=vix_regime,
            day_archetype=day_archetype,
            vpin_regime=vpin_regime,
            top_k=8,
        )
        sample_size = analogies.sample_size
        if sample_size >= 3:
            win_rate = analogies.win_rate_pct
            avg_mfe = max(0.5, analogies.avg_mfe_r)
            avg_mae = max(0.2, analogies.avg_mae_r)
            calib = analogies.confidence_calibration
            heuristic = analogies.heuristic_recommendation
    except Exception as e_mem:
        logger.debug(f"[PositionSizer] Episodic memory query bypassed: {e_mem}")

    p = win_rate / 100.0
    b = avg_mfe / avg_mae if avg_mae > 0 else 1.8

    # Raw Kelly Fraction: f* = (p * b - (1 - p)) / b
    if b > 0:
        raw_kelly = (p * b - (1.0 - p)) / b
    else:
        raw_kelly = 0.10

    # Institutional Quarter-Kelly dampener
    if sample_size >= 3:
        if raw_kelly <= 0 or p < 0.40 or calib == "HIGH_MAE_DRAWDOWN_PRONE":
            quarter_kelly = 0.35  # Capital preservation throttle
        elif p >= 0.75 and avg_mfe >= 2.0:
            quarter_kelly = min(1.50, max(1.15, raw_kelly * 2.0))  # Conviction scale-up
        else:
            quarter_kelly = max(0.50, min(1.20, raw_kelly * 1.5))
    else:
        quarter_kelly = 1.0  # Neutral baseline when sample size < 3

    base = calculate_position_size_for_alert(
        alert_type=alert_type,
        symbol=clean_sym,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=capital,
        target_price=target_price,
        max_risk_pct=max_risk_pct,
        win_rate=p,
        profit_factor=round(b, 2),
        is_fno=is_fno,
    )

    if is_fno:
        raw_adj_lots = base.lots * quarter_kelly
        adj_lots = (
            max(0, int(raw_adj_lots)) if quarter_kelly >= 0.50 else max(0, round(raw_adj_lots))
        )
        adj_shares = adj_lots * base.lot_size
    else:
        adj_shares = max(0, int(base.shares * quarter_kelly))
        adj_lots = int(adj_shares / max(1, base.lot_size)) if base.lot_size > 1 else adj_shares

    stop_dist = max(0.01, abs(entry_price - stop_loss))
    adj_risk = round(adj_shares * stop_dist, 2)
    adj_risk_pct = round((adj_risk / capital) * 100.0, 2) if capital > 0 else 0.0
    adj_cap = round(adj_shares * entry_price, 2)

    return EpisodicKellySizingResult(
        symbol=clean_sym,
        direction=norm_dir,
        allocated_shares=adj_shares,
        allocated_lots=adj_lots,
        lot_size=base.lot_size,
        risk_inr=adj_risk,
        risk_pct_of_capital=adj_risk_pct,
        capital_allocated_inr=adj_cap,
        raw_kelly_fraction=round(raw_kelly, 4),
        quarter_kelly_multiplier=round(quarter_kelly, 2),
        empirical_win_rate_pct=round(win_rate, 1),
        empirical_avg_mfe_r=round(avg_mfe, 2),
        empirical_avg_mae_r=round(avg_mae, 2),
        sample_size=sample_size,
        confidence_calibration=calib,
        heuristic_guidance=heuristic,
        base_result=base,
    )
