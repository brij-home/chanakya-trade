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
