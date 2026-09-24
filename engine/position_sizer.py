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


# Standard F&O Lot Sizes for Indian Instruments (Official NSE September 2026 Master: 216 Equity F&O + Commodities + Currencies)
_F_AND_O_LOT_SIZES: dict[str, int] = {
    "360ONE": 500,
    "ABB": 125,
    "ABCAPITAL": 3100,
    "ADANIENSOL": 675,
    "ADANIENT": 309,
    "ADANIGREEN": 600,
    "ADANIPORTS": 475,
    "ADANIPOWER": 3550,
    "ALKEM": 125,
    "ALUMINIUM": 5000,
    "AMBER": 100,
    "AMBUJACEM": 1200,
    "ANGELONE": 2500,
    "APLAPOLLO": 350,
    "APOLLOHOSP": 125,
    "ASHOKLEY": 5000,
    "ASIANPAINT": 250,
    "ASTRAL": 425,
    "ATHERENERG": 375,
    "AUBANK": 1000,
    "AUROPHARMA": 550,
    "AXISBANK": 625,
    "BAJAJ-AUTO": 75,
    "BAJAJFINSV": 300,
    "BAJAJHLDNG": 75,
    "BAJFINANCE": 750,
    "BANDHANBNK": 3600,
    "BANKBARODA": 2925,
    "BANKEX": 30,
    "BANKINDIA": 5200,
    "BANKNIFTY": 30,
    "BDL": 425,
    "BEL": 1425,
    "BHARATFORG": 500,
    "BHARTIARTL": 475,
    "BHEL": 2625,
    "BIOCON": 2500,
    "BLUESTARCO": 325,
    "BOSCHLTD": 25,
    "BPCL": 1975,
    "BRITANNIA": 125,
    "BSE": 200,
    "CAMS": 825,
    "CANBK": 6750,
    "CDSL": 475,
    "CGPOWER": 850,
    "CHOLAFIN": 625,
    "CIPLA": 425,
    "COALINDIA": 1350,
    "COCHINSHIP": 400,
    "COFORGE": 475,
    "COLPAL": 275,
    "CONCOR": 1250,
    "COPPER": 2500,
    "COTTON": 25,
    "CROMPTON": 2150,
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,
    "CUMMINSIND": 200,
    "DABUR": 1250,
    "DELHIVERY": 2075,
    "DIVISLAB": 100,
    "DIXON": 50,
    "DLF": 950,
    "DMART": 150,
    "DRREDDY": 625,
    "EICHERMOT": 100,
    "ETERNAL": 2425,
    "EURINR": 1000,
    "FEDERALBNK": 2500,
    "FINNIFTY": 60,
    "FORCEMOT": 25,
    "FORTIS": 775,
    "GAIL": 3550,
    "GBPINR": 1000,
    "GLENMARK": 375,
    "GMRAIRPORT": 6975,
    "GODFRYPHLP": 275,
    "GODREJCP": 500,
    "GODREJPROP": 325,
    "GOLD": 100,
    "GOLDM": 10,
    "GOLDPETAL": 1,
    "GRASIM": 250,
    "GVT&D": 125,
    "HAL": 150,
    "HAVELLS": 500,
    "HCLTECH": 400,
    "HDFCAMC": 300,
    "HDFCBANK": 650,
    "HDFCLIFE": 1100,
    "HEROMOTOCO": 150,
    "HINDALCO": 700,
    "HINDPETRO": 2025,
    "HINDUNILVR": 300,
    "HINDZINC": 1225,
    "HYUNDAI": 275,
    "ICICIBANK": 700,
    "ICICIGI": 325,
    "ICICIPRULI": 925,
    "IDEA": 71475,
    "IDFCFIRSTB": 9275,
    "IEX": 4350,
    "INDHOTEL": 1000,
    "INDIANB": 1000,
    "INDIGO": 150,
    "INDUSINDBK": 700,
    "INDUSTOWER": 1700,
    "INFY": 400,
    "INOXWIND": 6400,
    "IOC": 4875,
    "IREDA": 4525,
    "IRFC": 5425,
    "ITC": 1725,
    "JINDALSTEL": 625,
    "JIOFIN": 2350,
    "JPYINR": 1000,
    "JSWENERGY": 1075,
    "JSWSTEEL": 675,
    "JUBLFOOD": 1250,
    "KALYANKJIL": 1350,
    "KAYNES": 150,
    "KEI": 175,
    "KFINTECH": 575,
    "KOTAKBANK": 2000,
    "KPITTECH": 775,
    "LAURUSLABS": 850,
    "LEAD": 5000,
    "LICHSGFIN": 1000,
    "LICI": 1400,
    "LODHA": 625,
    "LT": 175,
    "LTF": 2250,
    "LTM": 150,
    "LUPIN": 425,
    "M&M": 200,
    "MAHABANK": 6500,
    "MANAPPURAM": 3000,
    "MANKIND": 250,
    "MARICO": 1200,
    "MARUTI": 50,
    "MAXHEALTH": 525,
    "MAZDOCK": 225,
    "MCX": 225,
    "MFSL": 400,
    "MIDCPNIFTY": 120,
    "MOTHERSON": 6150,
    "MOTILALOFS": 775,
    "MPHASIS": 275,
    "MUTHOOTFIN": 275,
    "NAM-INDIA": 625,
    "NATGASMINI": 250,
    "NATIONALUM": 1875,
    "NATURALGAS": 1250,
    "NAUKRI": 550,
    "NBCC": 6500,
    "NESTLEIND": 500,
    "NHPC": 6950,
    "NIFTY": 65,
    "NIFTY50": 65,
    "NIFTYFPI": 1100,
    "NIFTYNXT50": 25,
    "NMDC": 6750,
    "NTPC": 1500,
    "NYKAA": 3125,
    "OBEROIRLTY": 350,
    "OFSS": 100,
    "OIL": 1400,
    "ONGC": 2250,
    "PAGEIND": 20,
    "PATANJALI": 1075,
    "PAYTM": 725,
    "PERSISTENT": 125,
    "PETRONET": 1900,
    "PFC": 1300,
    "PGEL": 950,
    "PHOENIXLTD": 350,
    "PIDILITIND": 500,
    "PIIND": 175,
    "PNB": 8000,
    "PNBHOUSING": 650,
    "POLICYBZR": 350,
    "POLYCAB": 125,
    "POWERGRID": 1900,
    "POWERINDIA": 25,
    "PREMIERENE": 650,
    "PRESTIGE": 450,
    "RADICO": 150,
    "RBLBANK": 3175,
    "RECLTD": 1575,
    "RELIANCE": 500,
    "RVNL": 1925,
    "SAGILITY": 12000,
    "SAIL": 4700,
    "SBICARD": 800,
    "SBILIFE": 375,
    "SBIN": 750,
    "SENSEX": 20,
    "SHREECEM": 25,
    "SHRIRAMFIN": 825,
    "SIEMENS": 175,
    "SILVER": 30,
    "SILVERM": 5,
    "SILVERMIC": 1,
    "SOLARINDS": 50,
    "SONACOMS": 1225,
    "SRF": 200,
    "SUNPHARMA": 350,
    "SUPREMEIND": 175,
    "SUZLON": 12700,
    "SWIGGY": 1825,
    "TATACONSUM": 550,
    "TATAELXSI": 125,
    "TATAMOTORS": 575,
    "TATAPOWER": 1450,
    "TATASTEEL": 2750,
    "TCS": 225,
    "TECHM": 600,
    "TIINDIA": 200,
    "TITAN": 175,
    "TMPV": 1600,
    "TORNTPHARM": 125,
    "TRENT": 225,
    "TVSMOTOR": 175,
    "ULTRACEMCO": 50,
    "UNIONBANK": 4425,
    "UNITDSPR": 400,
    "UNOMINDA": 550,
    "UPL": 1355,
    "USDINR": 1000,
    "VBL": 1275,
    "VEDL": 1150,
    "VMM": 4850,
    "VOLTAS": 375,
    "WAAREEENER": 175,
    "WIPRO": 3000,
    "YESBANK": 31100,
    "ZINC": 5000,
    "ZYDUSLIFE": 900,
}


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
    except Exception:
        pass

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


def get_detector_lot_multiplier(alert_type: str) -> float:
    """
    Returns the detector-specific lot quantization multiplier for ``alert_type``.

    High-conviction setups (ORB_BREAKOUT, INDEX_CALL_SETUP, INDEX_PUT_SETUP) → 1.25×
    Standard momentum setups → 1.0×
    Counter-trend / reversal setups → 0.5×
    Unknown alert types → 1.0× (safe default)
    """
    return _DETECTOR_LOT_MULTIPLIERS.get(str(alert_type).upper(), 1.0)


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
) -> PositionSizeResult:
    """
    Detector-aware position sizing with empirically-calibrated lot multipliers.

    Wraps ``calculate_position_size()`` with a detector-specific multiplier
    applied to the resulting lot count.  Multipliers are defined in
    ``_DETECTOR_LOT_MULTIPLIERS`` and derived from EOD session diagnostics:

    - High-conviction setups (ORB_BREAKOUT, INDEX_CALL_SETUP, INDEX_PUT_SETUP):
      lots × 1.25 — rewarding structurally proven edges with larger sizing.
    - Counter-trend setups (COUNTER_TREND, REVERSAL_BEAR, REVERSAL_BULL):
      lots × 0.5 — dampening risk on historically lower-conviction signals.
    - Standard setups: lots × 1.0 (no change).

    Lot counts are always rounded down to maintain F&O contract integrity.
    The multiplier is logged in ``PositionSizeResult.notes`` for full traceability.

    Args:
        alert_type: The detector type string (e.g. ``"ORB_BREAKOUT"``).
        All other args mirror ``calculate_position_size()``.

    Returns:
        PositionSizeResult with detector-adjusted lots, shares, capital, and risk fields.
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

    # 2. Resolve detector multiplier
    multiplier = get_detector_lot_multiplier(alert_type)

    # 3. No adjustment needed for standard multiplier (1.0×)
    if multiplier == 1.0 or base.lots <= 0:
        return base

    # 4. Apply multiplier to lots (always round down to whole contracts)
    raw_lots = base.lots * multiplier
    adjusted_lots = max(1, int(raw_lots))  # Never go below 1 lot

    # 5. Recompute derived fields from adjusted lots
    adjusted_shares = adjusted_lots * base.lot_size
    adjusted_capital = adjusted_shares * base.entry_price
    adjusted_capital_pct = (adjusted_capital / capital) * 100.0 if capital > 0 else 0.0
    stop_distance = abs(base.entry_price - base.stop_loss)
    adjusted_risk = adjusted_shares * stop_distance
    adjusted_risk_pct = (adjusted_risk / capital) * 100.0 if capital > 0 else 0.0

    mult_label = f"+{int((multiplier - 1.0) * 100)}%" if multiplier > 1.0 else f"-{int((1.0 - multiplier) * 100)}%"
    adjusted_notes = (
        f"{base.notes} | Detector [{alert_type}] multiplier {multiplier:.2f}x ({mult_label}): "
        f"{base.lots} → {adjusted_lots} lots."
    )

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

