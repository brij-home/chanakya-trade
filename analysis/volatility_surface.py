"""
analysis/volatility_surface.py
──────────────────────────────
IV Smile and Term Structure analysis.

IV Smile: IV across strikes for a given expiry (the skew).
Term Structure: ATM IV across expiries (contango/backwardation).

Usage:
    iv-smile NIFTY
    iv-term NIFTY
"""

from __future__ import annotations
import logging

logger = logging.getLogger("analysis.volatility_surface")


from typing import Optional

import numpy as np
import pandas as pd

from rich.console import Console
from rich.table import Table

console = Console()


# ── Skew & Term Structure Classification ─────────────────────


def classify_skew(otm_put_iv: float, atm_iv: float, otm_call_iv: float) -> str:
    """Classify the IV smile shape."""
    put_skew = otm_put_iv - atm_iv
    call_skew = otm_call_iv - atm_iv

    if put_skew > 3.0 and put_skew > call_skew + 2.0:
        return "PUT_SKEW"  # Crash protection premium — market fears downside
    elif call_skew > 3.0 and call_skew > put_skew + 2.0:
        return "CALL_SKEW"  # Rally expectation — market fears missing upside
    else:
        return "SYMMETRIC"  # Normal smile — balanced expectations


def classify_term_structure(near_iv: float, far_iv: float) -> str:
    """Classify IV term structure."""
    diff = far_iv - near_iv
    if diff > 1.5:
        return "CONTANGO"  # Normal — far expiry IV higher
    elif diff < -1.5:
        return "BACKWARDATION"  # Event risk — near expiry IV higher (unusual)
    return "FLAT"


# ── IV Smile Computation ────────────────────────────────────


def compute_iv_smile(underlying: str, expiry: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Compute IV across strikes for a given expiry.

    Returns DataFrame with columns: strike, ce_iv, pe_iv, moneyness.
    Returns None if data unavailable.
    """
    try:
        from market.options import get_options_chain
        from market.quotes import get_ltp

        chain = get_options_chain(underlying, expiry)
        if not chain:
            return None

        spot = get_ltp(f"NSE:{underlying}")
        if spot <= 0:
            return None

        # Build strike → IV mapping
        strikes = {}
        for c in chain:
            s = c.strike
            if s not in strikes:
                strikes[s] = {"strike": s, "ce_iv": None, "pe_iv": None}

            iv_val = c.iv
            # If IV not in chain, try computing from premium
            if (iv_val is None or iv_val <= 0) and c.last_price > 0:
                try:
                    from analysis.options import compute_greeks

                    exp_str = c.expiry if c.expiry else expiry
                    if exp_str:
                        g = compute_greeks(spot, s, exp_str, c.option_type, c.last_price)
                        iv_val = g.iv_pct if g.iv_pct > 0 else None
                except Exception as e_suppressed:
                    logger.debug(
                        f"[analysis.volatility_surface] Non-fatal exception suppressed: {e_suppressed}"
                    )

            if c.option_type == "CE":
                strikes[s]["ce_iv"] = iv_val
            else:
                strikes[s]["pe_iv"] = iv_val

        if not strikes:
            return None

        df = pd.DataFrame(sorted(strikes.values(), key=lambda x: x["strike"]))
        df["moneyness"] = ((df["strike"] - spot) / spot * 100).round(1)
        return df

    except Exception:
        return None


def compute_iv_term_structure(underlying: str) -> Optional[pd.DataFrame]:
    """
    Compute ATM IV across multiple expiries.

    Returns DataFrame with columns: expiry, dte, atm_strike, ce_iv, pe_iv.
    """
    try:
        from market.options import get_options_chain, get_expiries, get_atm_strike
        from market.quotes import get_ltp

        spot = get_ltp(f"NSE:{underlying}")
        expiries = get_expiries(underlying)
        if not expiries or spot <= 0:
            return None

        rows = []
        for exp in expiries[:5]:  # first 5 expiries
            chain = get_options_chain(underlying, exp)
            if not chain:
                continue

            atm = get_atm_strike(underlying, spot)
            ce_iv = None
            pe_iv = None

            for c in chain:
                if c.strike == atm:
                    iv = c.iv
                    if (iv is None or iv <= 0) and c.last_price > 0:
                        try:
                            from analysis.options import compute_greeks

                            g = compute_greeks(spot, atm, exp, c.option_type, c.last_price)
                            iv = g.iv_pct
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[analysis.volatility_surface] Non-fatal exception suppressed: {e_suppressed}"
                            )
                    if c.option_type == "CE":
                        ce_iv = iv
                    else:
                        pe_iv = iv

            if ce_iv or pe_iv:
                from analysis.options import _dte_days

                rows.append(
                    {
                        "expiry": exp,
                        "dte": _dte_days(exp),
                        "atm_strike": atm,
                        "ce_iv": ce_iv,
                        "pe_iv": pe_iv,
                    }
                )

        return pd.DataFrame(rows) if rows else None
    except Exception:
        return None


def print_iv_smile(underlying: str, expiry: Optional[str] = None) -> None:
    """Display IV smile as Rich table."""
    df = compute_iv_smile(underlying, expiry)
    if df is None or df.empty:
        console.print("[dim]IV smile data unavailable.[/dim]")
        return

    table = Table(title=f"IV Smile — {underlying}")
    table.add_column("Strike", justify="right", style="bold")
    table.add_column("CE IV%", justify="right")
    table.add_column("PE IV%", justify="right")
    table.add_column("Moneyness", justify="right", style="dim")

    for _, row in df.iterrows():
        table.add_row(
            f"{row['strike']:,.0f}",
            f"{row['ce_iv']:.1f}%" if pd.notna(row.get("ce_iv")) and row["ce_iv"] else "—",
            f"{row['pe_iv']:.1f}%" if pd.notna(row.get("pe_iv")) and row["pe_iv"] else "—",
            f"{row['moneyness']:+.1f}%",
        )

    console.print(table)

    # Classify skew
    valid = df.dropna(subset=["ce_iv", "pe_iv"])
    if len(valid) >= 3:
        atm_idx = valid["moneyness"].abs().idxmin()
        atm_iv = valid.loc[atm_idx, "pe_iv"] or valid.loc[atm_idx, "ce_iv"] or 0
        otm_put = (
            valid[valid["moneyness"] < -3]["pe_iv"].mean()
            if len(valid[valid["moneyness"] < -3])
            else atm_iv
        )
        otm_call = (
            valid[valid["moneyness"] > 3]["ce_iv"].mean()
            if len(valid[valid["moneyness"] > 3])
            else atm_iv
        )
        skew = classify_skew(otm_put, atm_iv, otm_call)
        console.print(f"  Skew: [bold]{skew}[/bold]")


# ── Institutional Hagan's SABR (2002) Volatility Surface Re-exports ───
from analysis.vol_surface import (
    sabr_implied_volatility,
    calibrate_sabr,
    interpolate_sabr_smile,
    detect_strike_mispricings,
    analyze_volatility_surface,
    SABRParameters,
    StrikeMispricing,
    SABRCalibrationResult,
)


from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class VolatilitySkewReport:
    underlying: str
    spot_price: float
    expiry: str
    atm_strike: float
    atm_iv: float
    put_25d_strike: float
    put_25d_iv: float
    call_25d_strike: float
    call_25d_iv: float
    risk_reversal_skew: float  # Put IV - Call IV
    butterfly_curvature: float  # (Put IV + Call IV) / 2 - ATM IV
    realized_vol_20d: float
    volatility_risk_premium: float  # ATM IV - RV 20d
    skew_regime: str  # PUT_SKEW_CRASH_FEAR, CALL_SKEW_SHORT_SQUEEZE, BALANCED_SMILE
    trading_edge: str  # GAMMA_BUYING, THETA_HARVESTING, SPREAD_ARBITRAGE, NEUTRAL
    actionable_directive: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_25delta_skew_and_vrp(
    underlying: str,
    expiry: Optional[str] = None,
    options_chain: Optional[list[Any]] = None,
    spot_price: Optional[float] = None,
    realized_vol_20d: Optional[float] = None,
) -> Optional[VolatilitySkewReport]:
    """
    Computes 25-Delta Risk Reversal Skew, 25-Delta Butterfly Smile Curvature,
    and Volatility Risk Premium (VRP = Implied Vol - Realized Vol).
    """
    clean_sym = underlying.upper().replace("NSE:", "").replace("BSE:", "").strip()

    try:
        from market.quotes import get_ltp
        from market.options import get_options_chain, get_atm_strike

        spot = spot_price if (spot_price and spot_price > 0) else get_ltp(f"NSE:{clean_sym}")
        if not spot or spot <= 0:
            return None

        chain = options_chain or get_options_chain(clean_sym, expiry)
        if not chain:
            return None

        atm_strike = get_atm_strike(clean_sym, spot)
        resolved_exp = expiry or getattr(chain[0], "expiry", "NEAR") or "NEAR"

        # 25-Delta is roughly -2.5% to -3.0% OTM for Puts, +2.5% to +3.0% OTM for Calls
        target_put_strike = spot * 0.975
        target_call_strike = spot * 1.025

        # Find closest strikes
        strikes = sorted(list({c.strike for c in chain if getattr(c, "strike", 0) > 0}))
        if not strikes:
            return None

        closest_atm = min(strikes, key=lambda s: abs(s - atm_strike))
        closest_put = min(strikes, key=lambda s: abs(s - target_put_strike))
        closest_call = min(strikes, key=lambda s: abs(s - target_call_strike))

        # Extract IVs
        atm_ivs = [
            c.iv for c in chain if c.strike == closest_atm and getattr(c, "iv", None) and c.iv > 0
        ]
        atm_iv = float(np.mean(atm_ivs)) if atm_ivs else 15.0

        put_ivs = [
            c.iv
            for c in chain
            if c.strike == closest_put
            and c.option_type == "PE"
            and getattr(c, "iv", None)
            and c.iv > 0
        ]
        put_iv = float(put_ivs[0]) if put_ivs else (atm_iv * 1.08)

        call_ivs = [
            c.iv
            for c in chain
            if c.strike == closest_call
            and c.option_type == "CE"
            and getattr(c, "iv", None)
            and c.iv > 0
        ]
        call_iv = float(call_ivs[0]) if call_ivs else (atm_iv * 0.96)

        # Realized volatility
        if realized_vol_20d is None or realized_vol_20d <= 0:
            try:
                from market.history import get_ohlcv

                df_hist = get_ohlcv(clean_sym, interval="day", days=30)
                if df_hist is not None and len(df_hist) >= 20:
                    rets = np.log(df_hist["close"] / df_hist["close"].shift(1)).dropna()
                    rv_20 = float(rets.iloc[-20:].std() * np.sqrt(252) * 100.0)
                else:
                    rv_20 = 13.5
            except Exception:
                rv_20 = 13.5
        else:
            rv_20 = realized_vol_20d

        risk_reversal = round(put_iv - call_iv, 2)
        butterfly = round(((put_iv + call_iv) / 2.0) - atm_iv, 2)
        vrp = round(atm_iv - rv_20, 2)

        # Skew Regime & Directives
        if risk_reversal >= 3.5:
            regime = "PUT_SKEW_CRASH_FEAR"
            directive = (
                f"Elevated downside Put Skew ({risk_reversal:+.1f} vol pts). "
                f"Smart money paying high premium for crash hedges. Veto unhedged breakout longs."
            )
        elif risk_reversal <= -1.5:
            regime = "CALL_SKEW_SHORT_SQUEEZE"
            directive = (
                f"Call Skew Inversion ({risk_reversal:+.1f} vol pts). "
                f"Aggressive call wing demand indicates impending short squeeze. Favor call momentum."
            )
        else:
            regime = "BALANCED_SMILE"
            directive = "Normal volatility smile. Standard symmetric delta-neutral or directional setups apply."

        # Trading Edge
        if vrp >= 4.0:
            edge = "THETA_HARVESTING"
            directive += f" High Vol Risk Premium (+{vrp:.1f} pts) favors selling credit spreads / iron condors."
        elif vrp <= -2.5:
            edge = "GAMMA_BUYING"
            directive += f" Negative Vol Risk Premium ({vrp:.1f} pts) means options are underpriced; favor long gamma / straddles."
        else:
            edge = "NEUTRAL"

        return VolatilitySkewReport(
            underlying=clean_sym,
            spot_price=round(spot, 2),
            expiry=resolved_exp,
            atm_strike=closest_atm,
            atm_iv=round(atm_iv, 2),
            put_25d_strike=closest_put,
            put_25d_iv=round(put_iv, 2),
            call_25d_strike=closest_call,
            call_25d_iv=round(call_iv, 2),
            risk_reversal_skew=risk_reversal,
            butterfly_curvature=butterfly,
            realized_vol_20d=round(rv_20, 2),
            volatility_risk_premium=vrp,
            skew_regime=regime,
            trading_edge=edge,
            actionable_directive=directive,
        )

    except Exception as e:
        logger.warning(f"[VolatilitySurface] Error computing 25d skew: {e}")
        return None


__all__ = [
    "classify_skew",
    "classify_term_structure",
    "compute_iv_smile",
    "compute_iv_term_structure",
    "print_iv_smile",
    "compute_25delta_skew_and_vrp",
    "VolatilitySkewReport",
    "sabr_implied_volatility",
    "calibrate_sabr",
    "interpolate_sabr_smile",
    "detect_strike_mispricings",
    "analyze_volatility_surface",
    "SABRParameters",
    "StrikeMispricing",
    "SABRCalibrationResult",
]
