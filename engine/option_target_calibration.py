"""Option target ADR/Greek calibration and pre-creation friction viability gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import math
from typing import Any, Optional

from config.constants import IST
from engine.charges import SegmentType, calculate_net_expectancy
from engine.options_backtest import bs_delta, bs_gamma
from market.rule_schedule import derivative_close


@dataclass(frozen=True)
class OptionTargetCalibrationResult:
    """Calibrated intraday option levels bounded by underlying ADR headroom and Greeks."""

    delta: float
    gamma: float
    remaining_spot_headroom: float
    max_adr_opt_gain: float
    max_adr_t1: float
    calibrated_t1: float
    calibrated_t2: float
    calibrated_t3: float
    calibrated_rr: float
    was_adr_capped: bool
    viable_rr: bool


def _compute_remaining_session_factor(
    now_dt: Optional[datetime],
    *,
    is_commodity: bool = False,
) -> float:
    """Return remaining diffusive expansion factor in [0.22, 1.0] using rule_schedule."""
    dt = now_dt or datetime.now(IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)

    session_date = dt.date()
    close_t = time(23, 30) if is_commodity else derivative_close(session_date, expiring_index=False)
    close_dt = dt.replace(
        hour=close_t.hour,
        minute=close_t.minute,
        second=0,
        microsecond=0,
    )
    mins_left = max(15.0, (close_dt - dt).total_seconds() / 60.0)
    total_mins = 855.0 if is_commodity else 375.0
    ratio = min(1.0, max(0.03, mins_left / total_mins))
    return min(1.0, max(0.22, math.sqrt(ratio) * 1.15))


def _resolve_option_greeks(
    spot: float,
    strike: float,
    dte_days: Optional[int],
    iv: Optional[float],
    option_type: str,
) -> tuple[float, float]:
    """Compute finite |delta| and gamma with defensive fallback for sparse quotes."""
    clean_type = (
        "PE" if str(option_type).upper().strip() in ("PE", "PUT", "BEARISH", "BEAR") else "CE"
    )
    eff_dte = 1 if dte_days is None else max(0, int(dte_days))
    eff_iv = float(iv) if (iv is not None and iv > 0) else 0.22
    if eff_iv > 3.0:
        eff_iv = eff_iv / 100.0
    eff_iv = max(0.05, min(2.5, eff_iv))

    if spot > 0 and strike > 0:
        delta = abs(float(bs_delta(spot, strike, eff_dte, eff_iv, clean_type)))
        gamma = max(0.0, float(bs_gamma(spot, strike, max(0.5, float(eff_dte or 0.5)), eff_iv)))
        if math.isfinite(delta) and delta > 0.01:
            return min(0.98, max(0.15, delta)), gamma if math.isfinite(gamma) else 0.0

    # Conservative moneyness fallback when IV/strike is missing
    if spot > 0 and strike > 0:
        dist = (spot - strike) / spot if clean_type == "CE" else (strike - spot) / spot
        approx = 1.0 / (1.0 + math.exp(-15.0 * dist))
        return min(0.92, max(0.18, approx)), 0.0
    return 0.50, 0.0


def compute_option_adr_headroom_targets(
    *,
    spot: float,
    opt_ltp: float,
    opt_sl: float,
    raw_t1: float,
    option_type: str,
    strike: float,
    dte_days: Optional[int] = None,
    iv: Optional[float] = None,
    spot_atr: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    now_dt: Optional[datetime] = None,
    segment: str = "FNO_STOCK",
    min_rr: float = 1.25,
) -> OptionTargetCalibrationResult:
    """Scale and bound option T1/T2/T3 against realistic remaining intraday ADR & Delta/Gamma.

    Prevents systemic 45m stagnation exits caused by anchoring option buyers to multi-day ATR targets
    late in the session or after the stock has already consumed most of its Average Daily Range.
    """
    risk_pts = max(0.05, opt_ltp - opt_sl)
    delta, gamma = _resolve_option_greeks(spot, strike, dte_days, iv, option_type)
    is_commodity = str(segment).upper().strip() == "COMMODITY"
    time_factor = _compute_remaining_session_factor(now_dt, is_commodity=is_commodity)

    eff_iv = float(iv) if (iv is not None and iv > 0) else 0.22
    if eff_iv > 3.0:
        eff_iv = eff_iv / 100.0
    eff_iv = max(0.06, min(2.0, eff_iv))

    if spot_atr is not None and spot_atr > 0:
        base_adr = float(spot_atr)
    else:
        base_adr = max(1.0, spot * (eff_iv / math.sqrt(252.0)) * 1.15)

    used_range = 0.0
    if day_high is not None and day_low is not None and day_high > day_low > 0:
        used_range = float(day_high - day_low)

    # Allow expansion up to 1.35x ADR on breakout days, less already-consumed intraday travel
    remaining_spot = max(base_adr * 0.35, (base_adr * 1.35) - (used_range * 0.65)) * time_factor

    # Projected option gain for that realistic remaining spot move, guarding OTM gamma explosion
    linear_opt_gain = delta * remaining_spot
    gamma_bonus = 0.5 * gamma * (remaining_spot**2)
    capped_opt_gain = min(
        linear_opt_gain + min(gamma_bonus, linear_opt_gain * 0.45),
        remaining_spot * max(0.32, min(0.88, delta + 0.16)),
    )
    # Near-term minimum movement envelope so cheap options still clear realistic spread/fees
    max_adr_opt_gain = round(max(risk_pts * 1.25, capped_opt_gain), 2)
    max_adr_t1 = round(opt_ltp + max_adr_opt_gain, 2)

    was_adr_capped = bool(raw_t1 > max_adr_t1)
    cal_t1 = max_adr_t1 if was_adr_capped else round(raw_t1, 2)
    t1_gain = max(0.05, cal_t1 - opt_ltp)
    cal_t2 = round(max(cal_t1 + risk_pts * 0.75, opt_ltp + t1_gain * 1.55), 2)
    cal_t3 = round(max(cal_t2 + risk_pts * 0.95, opt_ltp + t1_gain * 2.25), 2)
    cal_rr = round(t1_gain / risk_pts, 2)

    return OptionTargetCalibrationResult(
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        remaining_spot_headroom=round(remaining_spot, 2),
        max_adr_opt_gain=max_adr_opt_gain,
        max_adr_t1=max_adr_t1,
        calibrated_t1=cal_t1,
        calibrated_t2=cal_t2,
        calibrated_t3=cal_t3,
        calibrated_rr=cal_rr,
        was_adr_capped=was_adr_capped,
        viable_rr=cal_rr >= min_rr,
    )


def evaluate_option_friction_viability(
    *,
    entry_price: float,
    target_1: float,
    stop_loss: float,
    quantity: int = 1,
    bid: float = 0.0,
    ask: float = 0.0,
    segment: SegmentType = "OPTIONS",
    max_spread_pct: float = 4.5,
    max_friction_drag_pct: float = 28.0,
    min_net_rr: float = 1.05,
) -> dict[str, Any]:
    """Verify option trade clears bid-ask spread and statutory round-trip friction before emission."""
    if entry_price <= 0 or target_1 <= entry_price or stop_loss <= 0 or stop_loss >= entry_price:
        return {
            "viable": False,
            "reason": "Invalid entry/target/stop price geometry for long option trade",
            "spread_pct": 0.0,
            "friction_drag_pct": 100.0,
            "net_rr": 0.0,
            "total_friction_target": 0.0,
        }

    spread_pct = 0.0
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        denom = max(entry_price, mid, 0.05)
        spread_pct = round(((ask - bid) / denom) * 100.0, 2)
        if spread_pct > max_spread_pct:
            return {
                "viable": False,
                "reason": (
                    f"Option bid-ask spread shock {spread_pct:.2f}% exceeds limit {max_spread_pct:.2f}%"
                ),
                "spread_pct": spread_pct,
                "friction_drag_pct": 100.0,
                "net_rr": 0.0,
                "total_friction_target": 0.0,
            }

    half_spread = (spread_pct / 200.0) if spread_pct > 0 else 0.001
    net_eval = calculate_net_expectancy(
        entry_price=entry_price,
        target_price=target_1,
        stop_price=stop_loss,
        quantity=max(1, int(quantity)),
        segment=segment,
        entry_side="BUY",
        half_spread_pct=half_spread,
    )
    drag_pct = float(net_eval.get("friction_drag_pct", 0.0) or 0.0)
    net_rr = float(net_eval.get("net_rr", 0.0) or 0.0)

    if drag_pct > max_friction_drag_pct:
        return {
            "viable": False,
            "reason": (
                f"Statutory + spread friction {drag_pct:.1f}% of T1 exceeds {max_friction_drag_pct:.1f}% threshold"
            ),
            "spread_pct": spread_pct,
            "friction_drag_pct": drag_pct,
            "net_rr": net_rr,
            "total_friction_target": float(net_eval.get("total_friction_target", 0.0) or 0.0),
        }

    if net_rr < min_net_rr or not net_eval.get("is_positive_expectancy", False):
        return {
            "viable": False,
            "reason": f"Net post-cost R:R ({net_rr:.2f}) below viable floor {min_net_rr:.2f}",
            "spread_pct": spread_pct,
            "friction_drag_pct": drag_pct,
            "net_rr": net_rr,
            "total_friction_target": float(net_eval.get("total_friction_target", 0.0) or 0.0),
        }

    return {
        "viable": True,
        "reason": None,
        "spread_pct": spread_pct,
        "friction_drag_pct": drag_pct,
        "net_rr": net_rr,
        "total_friction_target": float(net_eval.get("total_friction_target", 0.0) or 0.0),
    }
