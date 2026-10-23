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

logger = logging.getLogger("engine.position_sizer")


from dataclasses import dataclass
from typing import Any, Optional


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

    def as_dict(self) -> dict[str, Any]:
        return {
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
        }


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
    capital: float = 100000.0,
    price: Optional[float] = None,
) -> dict[str, Any]:
    """
    Evaluates SEBI physical settlement delivery risk for single-stock derivatives in expiry week (DTE <= 4).
    Mandates 100% margin delivery coverage or warns against holding overnight to prevent auction penalties.
    """
    if not is_physical_delivery_fno(symbol):
        return {
            "applicable": False,
            "blocked": False,
            "requires_full_margin": False,
            "warning": "",
            "required_delivery_capital": 0.0,
        }

    if dte is None or dte > 4:
        return {
            "applicable": True,
            "blocked": False,
            "requires_full_margin": False,
            "warning": "",
            "required_delivery_capital": 0.0,
        }

    lot_size = get_lot_size(symbol)
    current_price = price or 100.0
    required_capital = lot_size * current_price

    has_full_margin = capital >= required_capital
    if not has_full_margin:
        warning_msg = (
            f"SEBI Physical Delivery Risk: '{symbol}' is a single-stock derivative expiring in {dte} day(s). "
            f"Holding to expiry requires 100% physical delivery margin (₹{required_capital:,.2f}), but account "
            f"capital is ₹{capital:,.2f}. Prohibiting new overnight position without full delivery margin."
        )
        return {
            "applicable": True,
            "blocked": True,
            "requires_full_margin": True,
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
        "warning": warning_msg,
        "required_delivery_capital": required_capital,
    }


def get_lot_size(symbol: str) -> int:
    """Get the standard lot size for a stock/index/future/option (1 for cash equity)."""
    if not symbol:
        return 1
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


def calculate_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    capital: float = 100000.0,
    target_price: Optional[float] = None,
    max_risk_pct: float = 1.5,  # Risk max 1.5% of total capital
    max_capital_pct: Optional[float] = 20.0,  # Max % capital in single stock
    atr: Optional[float] = None,
    sizing_model: str = "atr_volatility",
    win_rate: float = 0.55,
    profit_factor: float = 1.8,
    is_fno: bool = False,
    vix: Optional[float] = None,
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
    if is_fno or clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
        lot_size = get_lot_size(clean_sym)
    else:
        lot_size = 1

    if entry_price <= 0:
        entry_price = 100.0

    # Stop distance calculation
    if stop_loss <= 0 or stop_loss >= entry_price:
        stop_loss = round(entry_price * 0.98, 2)

    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        stop_distance = entry_price * 0.01

    # Default 2R target if omitted
    if target_price is None or target_price <= entry_price:
        target_price = round(entry_price + (stop_distance * 2.0), 2)

    r_multiple = (target_price - entry_price) / stop_distance if stop_distance > 0 else 2.0

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
    risk_budget = capital * (effective_risk_pct / 100.0)

    # 1. Compute Raw Shares based on chosen model
    if sizing_model == "atr_volatility":
        effective_atr = atr if atr and atr > 0 else (stop_distance * 0.8)
        vol_stop = max(stop_distance, effective_atr * 1.5)
        raw_shares = int(risk_budget / vol_stop)
        notes = f"Sized using ATR Volatility Parity ({vol_stop:.1f} pts risk per share).{vix_note}"

    elif sizing_model == "half_kelly":
        b = max(1.0, profit_factor)
        p = max(0.1, min(0.9, win_rate))
        full_kelly = (p * b - (1.0 - p)) / b
        cap_fraction = (max_capital_pct / 100.0) if max_capital_pct else 0.20
        half_kelly_frac = max(0.02, min(cap_fraction, full_kelly * 0.5))
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
    if lot_size > 1:
        lots = shares // lot_size
        shares = lots * lot_size
        if shares == 0 and capital >= (entry_price * lot_size):
            lots = 1
            shares = lot_size
    else:
        shares = max(1, shares)
        lots = 1

    capital_allocated = shares * entry_price
    capital_pct = (capital_allocated / capital) * 100.0 if capital > 0 else 0.0
    actual_risk = shares * stop_distance
    actual_risk_pct = (actual_risk / capital) * 100.0 if capital > 0 else 0.0

    if (is_fno or lot_size > 1) and lots == 1 and actual_risk_pct > max_risk_pct:
        notes += f" [HIGH_TICKET_RISK: Single lot risk ({actual_risk_pct:.1f}%) exceeds max risk tolerance ({max_risk_pct:.1f}%). Consider cash equity shares or defined-risk spread.]"

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

    # 7. Apply detector-specific conviction lot scaling if provided
    if alert_type and result.lot_size > 1 and result.lots >= 1:
        mult = get_detector_lot_multiplier(alert_type)
        if mult != 1.0:
            adj_lots = max(1, int(round(result.lots * mult)))
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
                notes=f"{result.notes} [Detector '{alert_type}' {mult:.2f}x sizing applied: {adj_lots} lots]",
            )

    vol_pct = (atr / entry_price) * 100.0
    result.notes = f"Volatility Risk-Parity (14-ATR: ₹{atr:.2f} [{vol_pct:.2f}%]) | Margin Cap: {max_margin_pct}% | {result.notes}"
    return result


# ── Detector-Specific Lot Quantization ───────────────────────────────────────
# Derived from EOD session diagnostics (2026-09-24): empirically-proven high-conviction
# detectors receive a 1.25x lot premium; low-conviction counter-trend detectors are
# dampened to 0.5x to preserve positive expected-value across the portfolio.
# These multipliers are applied AFTER standard lot-size rounding so F&O contract
# integrity is always maintained (always a whole number of lots ≥ 1).

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
    capital: float = 100000.0,
    target_price: Optional[float] = None,
    max_risk_pct: float = 1.5,
    max_capital_pct: Optional[float] = 20.0,
    atr: Optional[float] = None,
    sizing_model: str = "atr_volatility",
    win_rate: float = 0.55,
    profit_factor: float = 1.8,
    is_fno: bool = False,
    vix: Optional[float] = None,
    conviction_tier: Optional[str] = None,
    is_physical_expiry_week: bool = False,
    cheetah_mandate: Optional[str] = None,
    strike_clock_zone: Optional[str] = None,
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
    if combined_multiplier == 1.0 or base.lots <= 0:
        return base

    # 4. Apply combined multiplier to lots (always round down to whole contracts)
    raw_lots = base.lots * combined_multiplier
    adjusted_lots = max(1, int(raw_lots))  # Never go below 1 lot

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
) -> dict[str, Any]:
    """
    Builds a capital-calibrated, ready-to-execute institutional order ticket.
    Translates raw quantitative alert price levels into an actionable order payload
    with lot-size quantization, max INR risk cap, and 1-click execution support.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    if alert_type:
        res = calculate_position_size_for_alert(
            symbol=clean_sym,
            entry_price=entry_price,
            stop_loss=stop_loss,
            alert_type=alert_type,
            capital=capital,
            target_price=target_price,
            max_risk_pct=max_risk_pct,
            is_fno=is_fno,
            conviction_tier=conviction_tier,
        )
    else:
        res = calculate_position_size(
            symbol=clean_sym,
            entry_price=entry_price,
            stop_loss=stop_loss,
            capital=capital,
            target_price=target_price,
            max_risk_pct=max_risk_pct,
            is_fno=is_fno,
        )

    side = "BUY" if direction.upper() in ("BULLISH", "BUY", "LONG") else "SELL"

    # Strict Limit Mandate: wide bid-ask spread or option orders mandate LIMIT orders
    final_order_type = order_type
    ticket_notes = res.notes
    if execution_friction_badge and (
        "STRICT LIMIT" in execution_friction_badge.upper()
        or "WIDE SPREAD" in execution_friction_badge.upper()
    ):
        final_order_type = "LIMIT"
        f_note = "Strict LIMIT order enforced due to wide bid-ask spread"
        ticket_notes = f"{ticket_notes} | {f_note}" if ticket_notes else f_note

    # Generate Smart Order Router (SOR) execution plan
    from engine.smart_order_router import build_smart_execution_plan

    sor_plan = build_smart_execution_plan(
        symbol=clean_sym,
        side=side,
        total_quantity=res.shares,
        ltp=entry_price,
        lot_size=res.lot_size,
    )

    return {
        "symbol": clean_sym,
        "side": side,
        "order_type": final_order_type,
        "limit_price": round(entry_price, 2),
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
        "auto_submit_ready": True,
        "smart_routing": sor_plan.to_dict(),
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
