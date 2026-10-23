"""
market/cross_asset_lead_lag.py
──────────────────────────────
Institutional Cross-Asset Macro Lead-Lag Arbitrage Engine.

Indian financial markets exhibit rapid, high-probability lead-lag transmission
from key macro variables:
  1. MCX Crude Oil Fast Pulse (15m delta >= ±1.0%):
     - Inverse transmission to Paints (ASIANPAINT, BERGEPAINT), Tyres (MRF, APOLLOTYRE),
       and Aviation (INDIGO). Raw material & ATF cost shock.
     - Direct transmission to Upstream Energy (ONGC, OIL).
  2. USD/INR Fast Pulse (15m delta >= ±0.15%):
     - Inverse transmission to Banking Benchmark (BANKNIFTY) and large financials
       (HDFCBANK, ICICIBANK, SBIN, KOTAKBANK) due to FII currency flight.
     - Direct transmission to IT Exporters (INFY, TCS, HCLTECH, WIPRO, TECHM)
       due to immediate USD revenue translation benefit.

Lead-Lag Arbitrage:
  - Macro fast-pulses print 5 to 25 minutes BEFORE domestic equities complete
    their repricing, offering an institutional predictive edge.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("market.cross_asset_lead_lag")

# Sensitivity Beta Mappings
# Negative beta = inverse relation (e.g. crude up -> stock down)
# Positive beta = direct relation (e.g. crude up -> stock up)
CRUDE_SENSITIVITY: dict[str, float] = {
    # Paints (severe negative beta)
    "ASIANPAINT": -0.85,
    "BERGEPAINT": -0.85,
    "KANSAINER": -0.80,
    "PIDILITIND": -0.60,
    # Tyres
    "MRF": -0.75,
    "APOLLOTYRE": -0.75,
    "CEATLTD": -0.70,
    "BALKRISIND": -0.65,
    # Aviation
    "INDIGO": -0.90,
    "SPICEJET": -0.85,
    # Auto & Logistics
    "MARUTI": -0.45,
    "TATAMOTORS": -0.40,
    "M&M": -0.40,
    # Upstream Oil & Gas (strong positive beta)
    "ONGC": +0.85,
    "OIL": +0.80,
    "GAIL": +0.40,
}

USDINR_SENSITIVITY: dict[str, float] = {
    # Banking & Financials (negative beta against INR depreciation)
    "BANKNIFTY": -0.70,
    "NIFTY BANK": -0.70,
    "FINNIFTY": -0.65,
    "HDFCBANK": -0.65,
    "ICICIBANK": -0.65,
    "KOTAKBANK": -0.60,
    "AXISBANK": -0.60,
    "SBIN": -0.55,
    # IT Exporters (strong positive beta against INR depreciation)
    "NIFTY IT": +0.85,
    "INFY": +0.80,
    "TCS": +0.80,
    "HCLTECH": +0.75,
    "WIPRO": +0.75,
    "TECHM": +0.75,
    "LTIM": +0.70,
    "PERSISTENT": +0.70,
    "COFORGE": +0.70,
}

CRUDE_FAST_PULSE_THRESHOLD_PCT = 1.00  # 1.0% in 15m
USDINR_FAST_PULSE_THRESHOLD_PCT = 0.15  # 0.15% in 15m


@dataclass
class LeadLagShock:
    """Quantitative evaluation of macro lead-lag impact on a specific ticker."""

    symbol: str
    proposed_direction: str
    status: str  # "HEADWIND_VETO" | "TAILWIND_BOOST" | "NEUTRAL_CLEAR"
    is_headwind: bool = False
    is_tailwind: bool = False
    veto_recommended: bool = False
    conviction_adj: int = 0  # e.g. -15 or +8
    macro_factor: str = "NONE"  # "CRUDE_OIL" | "USDINR" | "COMBINED"
    factor_pulse_pct: float = 0.0
    rationale: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "proposed_direction": self.proposed_direction,
            "status": self.status,
            "is_headwind": self.is_headwind,
            "is_tailwind": self.is_tailwind,
            "veto_recommended": self.veto_recommended,
            "conviction_adj": self.conviction_adj,
            "macro_factor": self.macro_factor,
            "factor_pulse_pct": self.factor_pulse_pct,
            "rationale": self.rationale,
            "evaluated_at": self.evaluated_at,
        }


class CrossAssetLeadLagSentinel:
    """
    Monitors high-frequency pulses on macro lead indicators and transmits
    institutional tailwinds / headwind vetoes to equity and index trading setups.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Fast pulse state: (delta_pct, timestamp)
        self._crude_pulse: tuple[float, float] = (0.0, 0.0)
        self._usdinr_pulse: tuple[float, float] = (0.0, 0.0)
        self._pulse_ttl = 1800.0  # 30 minutes active lead window

    def update_pulses(
        self,
        crude_delta_pct: Optional[float] = None,
        usdinr_delta_pct: Optional[float] = None,
    ) -> None:
        """Explicitly update or mock macro fast-pulse deltas."""
        now = time.time()
        with self._lock:
            if crude_delta_pct is not None:
                self._crude_pulse = (float(crude_delta_pct), now)
            if usdinr_delta_pct is not None:
                self._usdinr_pulse = (float(usdinr_delta_pct), now)

    def get_active_pulses(self) -> dict[str, float]:
        """Returns currently active fast pulses if within TTL."""
        now = time.time()
        with self._lock:
            c_val = self._crude_pulse[0] if (now - self._crude_pulse[1]) < self._pulse_ttl else 0.0
            u_val = (
                self._usdinr_pulse[0] if (now - self._usdinr_pulse[1]) < self._pulse_ttl else 0.0
            )
            return {"crude_delta_pct": c_val, "usdinr_delta_pct": u_val}

    def _resolve_clean_symbol(self, symbol: str) -> str:
        s = str(symbol).upper().strip()
        if ":" in s:
            s = s.split(":")[-1]
        if " " in s:
            s = s.split()[0]
        return s

    def evaluate_lead_lag_shock(
        self,
        symbol: str,
        direction: str,
    ) -> LeadLagShock:
        """
        Evaluates whether a proposed trade setup on `symbol` is facing a high-conviction
        macro lead-lag shock headwind or tailwind.
        """
        clean_sym = self._resolve_clean_symbol(symbol)
        is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")
        pulses = self.get_active_pulses()
        crude_delta = pulses["crude_delta_pct"]
        usdinr_delta = pulses["usdinr_delta_pct"]

        # 1. Crude Oil Transmission Check
        if clean_sym in CRUDE_SENSITIVITY and abs(crude_delta) >= CRUDE_FAST_PULSE_THRESHOLD_PCT:
            beta = CRUDE_SENSITIVITY[clean_sym]
            expected_stock_impact = crude_delta * beta

            # If expected stock impact opposes the trade direction:
            # e.g., crude surged (+2.0%) on Asian Paint (beta -0.85) -> expected impact = -1.7% (drop)
            # If trade is BULLISH: that is a HEADWIND!
            if is_bullish and expected_stock_impact < -0.60:
                action_desc = "Long entry suppressed"
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="HEADWIND_VETO",
                    is_headwind=True,
                    veto_recommended=True,
                    conviction_adj=-15,
                    macro_factor="CRUDE_OIL",
                    factor_pulse_pct=crude_delta,
                    rationale=(
                        f"🛑 Macro Shock VETO: MCX Crude Oil surging ({crude_delta:+.2f}% fast pulse). "
                        f"Direct margin compression shock on {clean_sym} (Beta {beta:+.2f}). {action_desc}."
                    ),
                )
            elif not is_bullish and expected_stock_impact < -0.60:
                # Bearish trade aligned with crude surge hurting the stock -> TAILWIND!
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="TAILWIND_BOOST",
                    is_tailwind=True,
                    veto_recommended=False,
                    conviction_adj=+8,
                    macro_factor="CRUDE_OIL",
                    factor_pulse_pct=crude_delta,
                    rationale=(
                        f"⚡ Macro Shock TAILWIND: Short setup aligned with surging Crude Oil "
                        f"({crude_delta:+.2f}% fast pulse). Downside margin expansion favored on {clean_sym}."
                    ),
                )
            elif is_bullish and expected_stock_impact > +0.60:
                # Bullish trade aligned with crude surge helping the stock (e.g. ONGC) -> TAILWIND!
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="TAILWIND_BOOST",
                    is_tailwind=True,
                    veto_recommended=False,
                    conviction_adj=+8,
                    macro_factor="CRUDE_OIL",
                    factor_pulse_pct=crude_delta,
                    rationale=(
                        f"⚡ Macro Shock TAILWIND: Long setup on {clean_sym} aligned with surging Crude Oil "
                        f"({crude_delta:+.2f}% fast pulse). Upstream revenue expansion tailwind."
                    ),
                )
            elif not is_bullish and expected_stock_impact > +0.60:
                # Shorting an upstream stock when crude is surging -> HEADWIND!
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="HEADWIND_VETO",
                    is_headwind=True,
                    veto_recommended=True,
                    conviction_adj=-15,
                    macro_factor="CRUDE_OIL",
                    factor_pulse_pct=crude_delta,
                    rationale=(
                        f"🛑 Macro Shock VETO: Shorting {clean_sym} while Crude Oil is surging "
                        f"({crude_delta:+.2f}% fast pulse) violates upstream macro expansion."
                    ),
                )

        # 2. USD/INR Currency Transmission Check
        if clean_sym in USDINR_SENSITIVITY and abs(usdinr_delta) >= USDINR_FAST_PULSE_THRESHOLD_PCT:
            beta = USDINR_SENSITIVITY[clean_sym]
            expected_stock_impact = usdinr_delta * beta

            # If USDINR spikes (e.g. +0.25%, INR weakening) and symbol is BANKNIFTY (beta -0.70):
            # expected_impact = -0.175% (outflow pressure)
            # If trade is BULLISH on BANKNIFTY: HEADWIND!
            if is_bullish and expected_stock_impact < -0.10:
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="HEADWIND_VETO",
                    is_headwind=True,
                    veto_recommended=True,
                    conviction_adj=-12,
                    macro_factor="USDINR",
                    factor_pulse_pct=usdinr_delta,
                    rationale=(
                        f"🛑 Currency Flight VETO: USD/INR surging ({usdinr_delta:+.2f}% fast pulse, INR weakening). "
                        f"Foreign capital flight pressure on {clean_sym}. Long entry vetoed."
                    ),
                )
            elif is_bullish and expected_stock_impact > +0.10:
                # Bullish on IT (e.g. INFY, TCS) when USDINR is spiking -> TAILWIND!
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="TAILWIND_BOOST",
                    is_tailwind=True,
                    veto_recommended=False,
                    conviction_adj=+8,
                    macro_factor="USDINR",
                    factor_pulse_pct=usdinr_delta,
                    rationale=(
                        f"⚡ Export Currency TAILWIND: Long setup on {clean_sym} aligned with USD/INR "
                        f"depreciation ({usdinr_delta:+.2f}% fast pulse). Revenue translation tailwind."
                    ),
                )
            elif not is_bullish and expected_stock_impact < -0.10:
                # Shorting Bank Nifty when USDINR is spiking -> TAILWIND!
                return LeadLagShock(
                    symbol=clean_sym,
                    proposed_direction=direction,
                    status="TAILWIND_BOOST",
                    is_tailwind=True,
                    veto_recommended=False,
                    conviction_adj=+8,
                    macro_factor="USDINR",
                    factor_pulse_pct=usdinr_delta,
                    rationale=(
                        f"⚡ Macro Breakdown TAILWIND: Short setup on {clean_sym} aligned with currency flight "
                        f"(USD/INR {usdinr_delta:+.2f}%). FII distribution pressure accelerates downside."
                    ),
                )

        # Clear / Neutral
        return LeadLagShock(
            symbol=clean_sym,
            proposed_direction=direction,
            status="NEUTRAL_CLEAR",
            is_headwind=False,
            is_tailwind=False,
            veto_recommended=False,
            conviction_adj=0,
            macro_factor="NONE",
            factor_pulse_pct=0.0,
            rationale="No adverse macro lead-lag shock detected; clearance granted.",
        )


# Global singleton instance
cross_asset_lead_lag_sentinel = CrossAssetLeadLagSentinel()
