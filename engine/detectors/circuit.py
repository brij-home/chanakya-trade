"""
Upper Circuit proximity detector.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

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
        return AutoAlert(
            alert_id=f"aa-cir-prox-{symbol}-{uuid.uuid4().hex[:6]}",
            alert_type="CIRCUIT_WARNING",
            stage="EARLY_WARNING",
            symbol=symbol,
            exchange=exchange,
            direction="BULLISH",
            headline=f"🔒 CIRCUIT WARNING: {symbol} at ₹{ltp:,.1f} ({dist_to_uc_pct:.1f}% below Upper Circuit)",
            summary=(
                f"Stock is surging (+{day_chg_pct:.1f}%) and trading {dist_to_uc_pct:.1f}% below "
                f"the ₹{upper_circuit:,.1f} circuit ceiling. Place limit orders before buyers freeze liquidity!"
            ),
            ltp=ltp,
            trigger_level=upper_circuit,
            target_level=upper_circuit,
            stop_loss=round(ltp * 0.97, 1),
            metrics={
                "prev_close": prev_close,
                "day_change_pct": round(day_chg_pct, 2),
                "upper_circuit": upper_circuit,
                "dist_to_uc_pct": round(dist_to_uc_pct, 2),
                "circuit_band_pct": circuit_band_pct,
            },
            actionable_plan={
                "action": "BUY_LIMIT_CIRCUIT",
                "price": f"₹{ltp:.1f}",
            },
            confidence=88,
            created_at=now_iso,
        )

    return None
