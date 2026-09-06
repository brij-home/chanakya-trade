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


# Standard F&O Lot Sizes for Indian Instruments (180+ Active Derivatives)
_F_AND_O_LOT_SIZES: dict[str, int] = {
    "ABB": 125,
    "ADANIENT": 300,
    "ADANIGREEN": 375,
    "ADANIPORTS": 400,
    "ADANIPOWER": 1350,
    "ALUMINIUM": 5000,
    "ANGELONE": 250,
    "APOLLOHOSP": 125,
    "APOLLOTYRE": 1700,
    "ASHOKLEY": 3500,
    "ASIANPAINT": 200,
    "ATUL": 75,
    "AUBANK": 1000,
    "AUROPHARMA": 550,
    "AXISBANK": 625,
    "BAJAJ-AUTO": 75,
    "BAJAJFINSV": 500,
    "BAJFINANCE": 125,
    "BALKRISIND": 200,
    "BANKBARODA": 2925,
    "BANKEX": 15,
    "BANKNIFTY": 15,
    "BDL": 300,
    "BEL": 2850,
    "BHARATFORG": 500,
    "BHARTIARTL": 950,
    "BHEL": 2625,
    "BIOCON": 2500,
    "BOSCHLTD": 25,
    "BPCL": 1800,
    "BRITANNIA": 200,
    "BSE": 375,
    "CANBK": 3375,
    "CDSL": 400,
    "CGPOWER": 850,
    "CHOLAFIN": 500,
    "CIPLA": 650,
    "COALINDIA": 2100,
    "COCHINSHIP": 350,
    "COFORGE": 150,
    "COLPAL": 200,
    "CONCOR": 1000,
    "COPPER": 2500,
    "COROMANDEL": 700,
    "COTTON": 25,
    "CROMPTON": 1800,
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,
    "DATAPATTNS": 100,
    "DEEPAKNTR": 300,
    "DELHIVERY": 400,
    "DEVYANI": 1250,
    "DIVISLAB": 150,
    "DIXON": 100,
    "DMART": 1200,
    "DRREDDY": 125,
    "EICHERMOT": 150,
    "EURINR": 1000,
    "FINNIFTY": 65,
    "FORCEMOT": 125,
    "FORTIS": 425,
    "GBPINR": 1000,
    "GODFRYPHLP": 125,
    "GODREJCP": 500,
    "GODREJPROP": 225,
    "GOLD": 100,
    "GOLDM": 1,
    "GOLDPETAL": 1,
    "GRASIM": 250,
    "HAL": 150,
    "HAVELLS": 350,
    "HCLTECH": 350,
    "HDFCAMC": 150,
    "HDFCBANK": 550,
    "HEROMOTOCO": 150,
    "HINDALCO": 1400,
    "HINDCOPPER": 2650,
    "HINDUNILVR": 300,
    "HINDZINC": 700,
    "HYUNDAI": 250,
    "ICICIBANK": 700,
    "IDFCFIRSTB": 7500,
    "INDUSINDBK": 500,
    "INFY": 400,
    "INOXWIND": 2400,
    "IRFC": 625,
    "ITC": 1600,
    "JINDALSTEL": 625,
    "JIOFIN": 1800,
    "JPYINR": 1000,
    "JSWSTEEL": 675,
    "JUBLFOOD": 1250,
    "KAYNES": 150,
    "KEI": 150,
    "KOTAKBANK": 400,
    "KPITTECH": 400,
    "LEAD": 5000,
    "LT": 150,
    "LTIM": 150,
    "LTTS": 100,
    "M&M": 350,
    "MANKIND": 250,
    "MARICO": 1200,
    "MARUTI": 50,
    "MAXHEALTH": 525,
    "MAZDOCK": 175,
    "MCX": 125,
    "MIDCPNIFTY": 120,
    "MOTHERSON": 4400,
    "MOTILALOFS": 250,
    "MPHASIS": 275,
    "MRF": 5,
    "MUTHOOTFIN": 350,
    "NAM-INDIA": 800,
    "NATGASMINI": 250,
    "NATIONALUM": 3750,
    "NATURALGAS": 1250,
    "NAVINFLUOR": 175,
    "NESTLEIND": 200,
    "NIFTY": 25,
    "NIFTY50": 25,
    "NIFTYBEES": 1,
    "NIFTYNXT50": 100,
    "NMDC": 4500,
    "NTPC": 1500,
    "OBEROIRLTY": 350,
    "OFSS": 100,
    "ONGC": 3850,
    "PAGEIND": 15,
    "PERSISTENT": 100,
    "PFC": 1300,
    "PIIND": 250,
    "PNB": 4000,
    "POLYCAB": 125,
    "POWERGRID": 2700,
    "PRESTIGE": 5000,
    "RATNAMANI": 300,
    "RECLTD": 1400,
    "RELIANCE": 250,
    "RVNL": 1750,
    "SAIL": 8000,
    "SBIN": 750,
    "SENSEX": 20,
    "SHRIRAMFIN": 300,
    "SIEMENS": 125,
    "SILVER": 1,
    "SILVERM": 1,
    "SILVERMIC": 1,
    "SONACOMS": 1200,
    "SRF": 375,
    "SUNPHARMA": 350,
    "SUNTV": 1500,
    "SUZLON": 7500,
    "TATACHEM": 550,
    "TATACONSUM": 900,
    "TATAELXSI": 100,
    "TATAMOTORS": 575,
    "TATAPOWER": 1350,
    "TATASTEEL": 5500,
    "TATATECH": 500,
    "TCS": 175,
    "TECHM": 600,
    "TITAGARH": 825,
    "TITAN": 175,
    "TORNTPHARM": 250,
    "TRENT": 100,
    "TVSMOTOR": 250,
    "ULTRACEMCO": 100,
    "UNIONBANK": 4250,
    "UPL": 1300,
    "USDINR": 1000,
    "VBL": 500,
    "VEDL": 1150,
    "VISHAL": 2500,
    "VOLTAS": 375,
    "WIPRO": 1500,
    "ZEEL": 3000,
    "ZINC": 5000,
    "ZOMATO": 2000,
    "ZYDUSLIFE": 900,
}


def is_fno_symbol(symbol: str) -> bool:
    """Return True if symbol is traded in the F&O derivatives segment."""
    clean = (
        symbol.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .strip()
    )
    return clean in _F_AND_O_LOT_SIZES


def get_lot_size(symbol: str) -> int:
    """Get the standard lot size for a stock/index/future (1 for cash equity)."""
    clean = (
        symbol.upper()
        .replace(".NS", "")
        .replace("NSE:", "")
        .replace("NFO:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("CDS:", "")
        .strip()
    )
    return _F_AND_O_LOT_SIZES.get(clean, 1)


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

    # Dollar risk budget
    risk_budget = capital * (max_risk_pct / 100.0)

    # 1. Compute Raw Shares based on chosen model
    if sizing_model == "atr_volatility":
        effective_atr = atr if atr and atr > 0 else (stop_distance * 0.8)
        vol_stop = max(stop_distance, effective_atr * 1.5)
        raw_shares = int(risk_budget / vol_stop)
        notes = f"Sized using ATR Volatility Parity ({vol_stop:.1f} pts risk per share)."

    elif sizing_model == "half_kelly":
        b = max(1.0, profit_factor)
        p = max(0.1, min(0.9, win_rate))
        full_kelly = (p * b - (1.0 - p)) / b
        cap_fraction = (max_capital_pct / 100.0) if max_capital_pct else 0.20
        half_kelly_frac = max(0.02, min(cap_fraction, full_kelly * 0.5))
        allocated = capital * half_kelly_frac
        raw_shares = int(allocated / entry_price)
        notes = f"Sized via Half-Kelly ({half_kelly_frac * 100:.1f}% capital allocation for {p * 100:.0f}% win-rate)."

    else:  # fixed_fractional
        raw_shares = int(risk_budget / stop_distance)
        notes = (
            f"Sized strictly on stop distance ({stop_distance:.2f} pts) at {max_risk_pct}% risk."
        )

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
