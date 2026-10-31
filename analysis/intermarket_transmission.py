"""
analysis/intermarket_transmission.py — Institutional Cross-Asset Lead-Lag Macro Transmission Matrix

Quantifies real-time transmission of global macro drivers (Brent Crude, US 10Y Yield,
DXY Dollar Index, USDINR, GIFT Nifty Basis) onto domestic Indian equities and sector setups.

Indian Market Realities:
  1. Brent Crude Spikes:
     - Severe Negative Transmission to OMCs (BPCL, HPCL, IOC) and Paints (ASIANPAINT, BERGEPAINT)
       due to immediate raw material margin compression.
     - Positive Transmission to Upstream Producers (ONGC, OIL).
  2. US 10Y Yield Surges / Tech Selloff:
     - Multiple compression transmission to high-duration IT Services (TCS, INFY, HCLTECH).
  3. GIFT Nifty Basis Momentum:
     - Leading indicator for Nifty 50 cash index (3 to 8 minute transmission lead).
  4. USDINR Currency Depreciation:
     - Margin tailwind for US-revenue heavy IT & Pharma exporters.
     - Headwind for capital goods and fuel importers.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

from config.constants import IST

logger = logging.getLogger(__name__)

# Sector Sensitivity Map for Indian Equities
# Format: {symbol: (sector, primary_driver, beta_sensitivity, secondary_driver, sec_beta)}
SECTOR_TRANSMISSION_MAP: dict[str, tuple[str, str, float, Optional[str], float]] = {
    # Downstream OMCs (Severe negative crude sensitivity)
    "BPCL": ("OMC", "brent", -0.85, "usdinr", -0.30),
    "HPCL": ("OMC", "brent", -0.88, "usdinr", -0.35),
    "IOC": ("OMC", "brent", -0.80, "usdinr", -0.25),
    # Paints & Specialty Chemicals (Petrochemical input cost)
    "ASIANPAINT": ("PAINTS", "brent", -0.75, "dxy", -0.20),
    "BERGEPAINT": ("PAINTS", "brent", -0.72, "dxy", -0.20),
    "KANSAINER": ("PAINTS", "brent", -0.70, "dxy", -0.15),
    "PIDILITIND": ("CHEMICALS", "brent", -0.65, "dxy", -0.15),
    "AARTIIND": ("CHEMICALS", "brent", -0.60, "usdinr", 0.30),
    # Tyres & Aviation (ATF fuel / synthetic rubber)
    "INDIGO": ("AVIATION", "brent", -0.82, "usdinr", -0.40),
    "MRF": ("TYRES", "brent", -0.68, "usdinr", -0.20),
    "APOLLOTYRE": ("TYRES", "brent", -0.65, "usdinr", -0.20),
    "CEATLTD": ("TYRES", "brent", -0.62, "usdinr", -0.20),
    # Upstream Oil Producers (Direct crude beneficiaries)
    "ONGC": ("UPSTREAM_ENERGY", "brent", 0.82, "usdinr", 0.25),
    "OIL": ("UPSTREAM_ENERGY", "brent", 0.85, "usdinr", 0.30),
    "GAIL": ("GAS_UTILITY", "brent", 0.45, "usdinr", -0.15),
    # IT Services (Rates drag, currency boost)
    "TCS": ("IT", "us10y", -0.65, "usdinr", 0.55),
    "INFY": ("IT", "us10y", -0.68, "usdinr", 0.58),
    "HCLTECH": ("IT", "us10y", -0.60, "usdinr", 0.52),
    "WIPRO": ("IT", "us10y", -0.62, "usdinr", 0.50),
    "TECHM": ("IT", "us10y", -0.60, "usdinr", 0.50),
    "LTIM": ("IT", "us10y", -0.70, "usdinr", 0.55),
    "COFORGE": ("IT", "us10y", -0.72, "usdinr", 0.55),
    "PERSISTENT": ("IT", "us10y", -0.70, "usdinr", 0.52),
    # Metals (Global commodity dollar pricing)
    "TATASTEEL": ("METALS", "dxy", -0.72, "brent", -0.25),
    "JSWSTEEL": ("METALS", "dxy", -0.75, "brent", -0.25),
    "HINDALCO": ("METALS", "dxy", -0.78, "usdinr", 0.20),
    "VEDL": ("METALS", "dxy", -0.70, "brent", 0.20),
    "NATIONALUM": ("METALS", "dxy", -0.68, "usdinr", 0.25),
    # Pharma Exporters (Currency boost)
    "SUNPHARMA": ("PHARMA", "usdinr", 0.55, "us10y", -0.15),
    "DRREDDY": ("PHARMA", "usdinr", 0.58, "us10y", -0.15),
    "CIPLA": ("PHARMA", "usdinr", 0.50, "us10y", -0.10),
    "DIVISLAB": ("PHARMA", "usdinr", 0.60, "us10y", -0.20),
    "LUPIN": ("PHARMA", "usdinr", 0.52, "us10y", -0.15),
    # Indices (GIFT basis & global volatility)
    "NIFTY": ("INDEX", "gift_nifty", 0.92, "us_vix", -0.60),
    "BANKNIFTY": ("INDEX", "gift_nifty", 0.88, "us10y", -0.45),
    "FINNIFTY": ("INDEX", "gift_nifty", 0.86, "us10y", -0.45),
}


@dataclass
class MacroDriverState:
    key: str
    name: str
    ltp: float
    change_pct: float
    impulse_level: str  # NORMAL, MODERATE_IMPULSE, SEVERE_IMPULSE
    as_of: str


@dataclass
class SymbolMacroTransmission:
    symbol: str
    sector: str
    primary_driver: str
    primary_driver_change_pct: float
    net_transmission_score: float  # Bounded in [-100.0, +100.0]
    transmission_direction: str  # BULLISH_TAILWIND, BEARISH_HEADWIND, NEUTRAL
    transmission_lag_mins: int  # Estimated delay (3-15 min)
    is_spillover_active: bool
    actionable_guidance: str
    falsification_warning: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntermarketTransmissionMatrix:
    timestamp: str
    macro_drivers: dict[str, dict[str, Any]]
    active_sector_transmissions: list[dict[str, Any]]
    top_bearish_headwinds: list[dict[str, Any]]
    top_bullish_tailwinds: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_driver_impulse_level(driver_key: str, change_pct: float) -> str:
    abs_chg = abs(change_pct)
    if driver_key == "brent":
        return (
            "SEVERE_IMPULSE"
            if abs_chg >= 2.0
            else ("MODERATE_IMPULSE" if abs_chg >= 1.0 else "NORMAL")
        )
    elif driver_key == "us10y":
        return (
            "SEVERE_IMPULSE"
            if abs_chg >= 2.5
            else ("MODERATE_IMPULSE" if abs_chg >= 1.2 else "NORMAL")
        )
    elif driver_key in ("dxy", "usdinr"):
        return (
            "SEVERE_IMPULSE"
            if abs_chg >= 0.50
            else ("MODERATE_IMPULSE" if abs_chg >= 0.25 else "NORMAL")
        )
    elif driver_key == "gift_nifty":
        return (
            "SEVERE_IMPULSE"
            if abs_chg >= 0.60
            else ("MODERATE_IMPULSE" if abs_chg >= 0.30 else "NORMAL")
        )
    elif "vix" in driver_key:
        return (
            "SEVERE_IMPULSE"
            if abs_chg >= 5.0
            else ("MODERATE_IMPULSE" if abs_chg >= 2.5 else "NORMAL")
        )
    return (
        "SEVERE_IMPULSE" if abs_chg >= 2.0 else ("MODERATE_IMPULSE" if abs_chg >= 1.0 else "NORMAL")
    )


def get_macro_drivers_state() -> dict[str, MacroDriverState]:
    """Fetches real-time macro drivers state from global_macro report and GIFT Nifty."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    drivers: dict[str, MacroDriverState] = {}

    try:
        from market.global_macro import fetch_global_macro_report

        rep = fetch_global_macro_report(use_cache=True)
        if rep and rep.items:
            for k, item in rep.items.items():
                imp = _get_driver_impulse_level(k, item.change_pct)
                drivers[k] = MacroDriverState(
                    key=k,
                    name=item.label,
                    ltp=item.ltp,
                    change_pct=item.change_pct,
                    impulse_level=imp,
                    as_of=rep.as_of or now_str,
                )
    except Exception as e:
        logger.warning(f"[IntermarketTransmission] Failed to fetch global macro: {e}")

    # Add GIFT Nifty basis driver
    try:
        from market.gift_nifty import get_gift_nifty

        gn = get_gift_nifty()
        if gn and gn.status == "OK":
            gap_pct = gn.implied_gap_pct or 0.0
            imp = _get_driver_impulse_level("gift_nifty", gap_pct)
            drivers["gift_nifty"] = MacroDriverState(
                key="gift_nifty",
                name="GIFT Nifty Basis Lead",
                ltp=gn.gift_price,
                change_pct=gap_pct,
                impulse_level=imp,
                as_of=gn.as_of or now_str,
            )
    except Exception as e_gn:
        logger.debug(f"[IntermarketTransmission] GIFT Nifty driver note: {e_gn}")

    return drivers


def compute_symbol_transmission(
    symbol: str,
    drivers: Optional[dict[str, MacroDriverState]] = None,
) -> SymbolMacroTransmission:
    """
    Computes real-time lead-lag transmission for a given stock or index symbol.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    if clean_sym.endswith(".NS") or clean_sym.endswith(".BO"):
        clean_sym = clean_sym.split(".")[0]

    if drivers is None:
        drivers = get_macro_drivers_state()

    spec = SECTOR_TRANSMISSION_MAP.get(clean_sym)
    if not spec:
        # Default fallback for unmapped symbols
        return SymbolMacroTransmission(
            symbol=clean_sym,
            sector="GENERAL_EQUITY",
            primary_driver="gift_nifty",
            primary_driver_change_pct=0.0,
            net_transmission_score=0.0,
            transmission_direction="NEUTRAL",
            transmission_lag_mins=5,
            is_spillover_active=False,
            actionable_guidance="No pronounced cross-asset macro spillover detected.",
        )

    sector, prim_driver, prim_beta, sec_driver, sec_beta = spec

    prim_state = drivers.get(prim_driver)
    prim_chg = prim_state.change_pct if prim_state else 0.0

    sec_chg = 0.0
    if sec_driver:
        sec_state = drivers.get(sec_driver)
        sec_chg = sec_state.change_pct if sec_state else 0.0

    # Calculate transmission score: Beta * % Change * Scaling Factor
    raw_prim = prim_beta * prim_chg * 25.0
    raw_sec = (sec_beta * sec_chg * 15.0) if sec_driver else 0.0
    net_score = max(-100.0, min(100.0, round(raw_prim + raw_sec, 1)))

    # Direction and guidance
    is_active = abs(net_score) >= 30.0
    falsification: Optional[str] = None

    if net_score >= 35.0:
        direction = "BULLISH_TAILWIND"
        guidance = (
            f"Strong macro tailwind from {prim_driver.upper()} ({prim_chg:+.2f}%). "
            f"Favors upside continuation; lower probability of false breakouts."
        )
    elif net_score <= -35.0:
        direction = "BEARISH_HEADWIND"
        guidance = (
            f"Pronounced macro headwind from {prim_driver.upper()} ({prim_chg:+.2f}%). "
            f"VETO aggressive longs or demand limit-order retest discounts."
        )
        falsification = (
            f"Cross-asset macro resistance: {prim_driver.upper()} impulse ({prim_chg:+.2f}%) "
            f"creates {abs(net_score):.0f}pts adverse sector drag."
        )
    else:
        direction = "NEUTRAL"
        guidance = (
            "Macro drivers are within balanced equilibrium; trade on pure price-action/order-flow."
        )

    # Estimated transmission lag window (Indian market empirical transmission)
    lag_mins = 5
    if prim_driver == "brent":
        lag_mins = 12  # Crude inventory & refinery adjustments transmit over 10-15 mins
    elif prim_driver == "us10y":
        lag_mins = 10
    elif prim_driver == "gift_nifty":
        lag_mins = 3  # GIFT leads spot cash within 3-5 mins

    return SymbolMacroTransmission(
        symbol=clean_sym,
        sector=sector,
        primary_driver=prim_driver,
        primary_driver_change_pct=round(prim_chg, 2),
        net_transmission_score=net_score,
        transmission_direction=direction,
        transmission_lag_mins=lag_mins,
        is_spillover_active=is_active,
        actionable_guidance=guidance,
        falsification_warning=falsification,
    )


def compute_intermarket_transmission_matrix() -> IntermarketTransmissionMatrix:
    """
    Computes global intermarket transmission across all watched sectors and symbols.
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    drivers = get_macro_drivers_state()

    transmissions: list[SymbolMacroTransmission] = []
    for sym in SECTOR_TRANSMISSION_MAP:
        res = compute_symbol_transmission(sym, drivers=drivers)
        transmissions.append(res)

    # Sort into top headwinds and tailwinds
    headwinds = [t.to_dict() for t in transmissions if t.net_transmission_score <= -25.0]
    headwinds.sort(key=lambda x: x["net_transmission_score"])

    tailwinds = [t.to_dict() for t in transmissions if t.net_transmission_score >= 25.0]
    tailwinds.sort(key=lambda x: x["net_transmission_score"], reverse=True)

    drivers_dict = {k: asdict(v) for k, v in drivers.items()}

    return IntermarketTransmissionMatrix(
        timestamp=now_str,
        macro_drivers=drivers_dict,
        active_sector_transmissions=[t.to_dict() for t in transmissions if t.is_spillover_active],
        top_bearish_headwinds=headwinds[:6],
        top_bullish_tailwinds=tailwinds[:6],
    )
