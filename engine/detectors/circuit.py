"""
Upper Circuit proximity detector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert

IST = ZoneInfo("Asia/Kolkata")


def detect_circuit_proximity(
    symbol: str,
    ltp: float,
    prev_close: float,
    high: Optional[float] = None,
    exchange: str = "NSE",
    circuit_band_pct: float = 5.0,
) -> Optional[AutoAlert]:
    """
    Early warning when stock is approaching Upper Circuit (<1.5% from ceiling).
    Enables user to place limit orders or enter before 100% buyers freeze liquidity.
    """
    if ltp <= 0 or prev_close <= 0:
        return None

    day_chg_pct = ((ltp - prev_close) / prev_close) * 100.0
    upper_circuit = round(prev_close * (1.0 + (circuit_band_pct / 100.0)), 2)
    dist_to_uc_pct = ((upper_circuit - ltp) / upper_circuit) * 100.0

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # If within 1.5% of upper circuit ceiling and gaining strongly
    if 0.1 <= dist_to_uc_pct <= 1.5 and day_chg_pct >= (circuit_band_pct * 0.7):
        # Model structural continuation targets (circuit lock momentum carrying into next session)
        risk_pts = max(1.0, round(ltp * 0.015, 2))
        sl_price = round(ltp - risk_pts, 2)
        t1_price = round(upper_circuit + (1.8 * risk_pts), 2)
        t2_price = round(upper_circuit + (3.2 * risk_pts), 2)
        rr_str = f"1:{round((t1_price - ltp) / risk_pts, 1)}"

        return AutoAlert(
            alert_id=generate_alert_id(symbol, "CIRCUIT_WARNING", variant="prox"),
            alert_type="CIRCUIT_WARNING",
            stage="EARLY_WARNING",
            symbol=symbol,
            exchange=exchange,
            direction="BULLISH",
            headline=f"🔒 CIRCUIT WARNING: {symbol} at ₹{ltp:,.1f} ({dist_to_uc_pct:.1f}% below Upper Circuit)",
            summary=(
                f"Stock is surging (+{day_chg_pct:.1f}%) and trading {dist_to_uc_pct:.1f}% below "
                f"the ₹{upper_circuit:,.1f} circuit ceiling. Limit entry before buyer lock; T1 continuation ₹{t1_price:,.1f}."
            ),
            ltp=ltp,
            trigger_level=upper_circuit,
            target_level=t1_price,
            stop_loss=sl_price,
            metrics={
                "prev_close": prev_close,
                "day_change_pct": round(day_chg_pct, 2),
                "upper_circuit": upper_circuit,
                "dist_to_uc_pct": round(dist_to_uc_pct, 2),
                "circuit_band_pct": circuit_band_pct,
                "continuation_t1": t1_price,
                "continuation_t2": t2_price,
            },
            actionable_plan={
                "action": "BUY_LIMIT_CIRCUIT",
                "price": f"₹{ltp:.1f}",
                "entry_range": f"₹{round(ltp * 0.998, 1):.1f} – ₹{upper_circuit:.1f}",
                "circuit_ceiling": f"₹{upper_circuit:.1f}",
                "target": f"₹{t1_price:.1f} (Next Session Continuation)",
                "target_2": f"₹{t2_price:.1f}",
                "stop_loss": f"₹{sl_price:.1f}",
                "risk_reward": rr_str,
                "profit_rule": "Lock in before seller liquidity evaporates; ride continuation into next session opening auction.",
            },
            confidence=88,
            created_at=now_iso,
        )

    return None
