"""
engine/detectors/currency.py
────────────────────────────
Autonomous NSE CDS Currency Breakout Detector.

Monitors liquid currency pairs (USDINR, EURINR, GBPINR, JPYINR) for macro session breakouts,
tight order book spread execution, and volatility expansions.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.currency")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_CURRENCIES = ["USDINR", "EURINR", "GBPINR", "JPYINR"]


def detect_currency_breakouts(
    universe: Optional[list[str]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans liquid Currency pairs (USDINR, EURINR, GBPINR) for post-equity breakouts.
    Active during post-equity session (15:30 - 17:00 IST).
    """
    from market.quotes import get_quote

    found: list[AutoAlert] = []
    targets = universe or DEFAULT_CURRENCIES
    formatted = [f"CDS:{s}" if ":" not in s else s for s in targets]
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    if quotes_map is None:
        try:
            quotes_map = get_quote(formatted)
        except Exception as e:
            logger.debug(f"[CurrencyDetector] Currency quotes fetch error: {e}")
            return found

    for sym in targets:
        clean_sym = sym.upper().replace("CDS:", "").strip()
        q = quotes_map.get(f"CDS:{clean_sym}") or quotes_map.get(clean_sym)
        if not q:
            continue

        ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
        if ltp <= 0:
            continue

        chg = float(getattr(q, "change_pct", 0.0) or 0.0)
        # Significant currency move threshold (>= 0.10% is a multi-tick macro expansion)
        if abs(chg) < 0.10:
            continue

        is_bullish = chg > 0
        alert_type = "CURRENCY_BREAKOUT"
        from engine.alert_identity import generate_alert_id

        alert_id = generate_alert_id(clean_sym, alert_type)

        # Currency dynamic risk: based on CMP volatility
        risk_rupees = round(max(0.06, ltp * 0.0012), 4)
        from engine.position_sizer import get_lot_size

        curr_lot = get_lot_size(clean_sym) or 1000

        if is_bullish:
            sl_price = round(ltp - risk_rupees, 4)
            t1_price = round(ltp + 1.8 * risk_rupees, 4)
            t2_price = round(ltp + 3.0 * risk_rupees, 4)
            headline = f"💱 CURRENCY BREAKOUT: {clean_sym} +{chg:.2f}% @ ₹{ltp:.4f}"
            summary = f"Macro currency surge in {clean_sym}: Moving +{chg:.2f}% to ₹{ltp:.4f}. Long thesis active."
            action = "BUY_FUTURES"
        else:
            sl_price = round(ltp + risk_rupees, 4)
            t1_price = round(ltp - 1.8 * risk_rupees, 4)
            t2_price = round(ltp - 3.0 * risk_rupees, 4)
            headline = f"💱 CURRENCY BREAKDOWN: {clean_sym} {chg:.2f}% @ ₹{ltp:.4f}"
            summary = f"Macro currency drop in {clean_sym}: Moving {chg:.2f}% to ₹{ltp:.4f}. Short thesis active."
            action = "SELL_SHORT_FUTURES"

        # Empirical mathematical R:R calculation
        rr_calc = round(abs(t1_price - ltp) / max(0.0001, abs(ltp - sl_price)), 1)
        rr_str = f"1:{rr_calc}"

        # Strict Data Provenance Gate: Verify if quote is authentic live broker data vs synthetic/mock
        is_mock_quote = (
            type(q).__name__ == "MagicMock"
            or getattr(q, "_is_mock", False)
            or getattr(q, "provider", "") in ("mock", "TEST")
            or getattr(q, "data_state", "") == "UNAVAILABLE"
        )
        is_test_env = (
            os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test"
        )
        is_authentic_live = not (is_mock_quote or is_test_env)

        from engine.trade_plan import get_market_status

        cds_status_dict = get_market_status("CDS")
        cds_status = cds_status_dict.get("status", "LIVE")

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            stage="IGNITED" if abs(chg) >= 0.20 else "EARLY_WARNING",
            symbol=clean_sym,
            exchange="CDS",
            direction=direction,
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=ltp,
            target_level=t1_price,
            stop_loss=sl_price,
            confidence=min(92, int(75 + abs(chg) * 30)),
            created_at=now_iso,
            is_live=is_authentic_live,
            environment="LIVE" if is_authentic_live else "TEST",
            market_status=cds_status,
            metrics={
                "change_pct": chg,
                "segment": "CURRENCY",
                "lot_size": curr_lot,
            },
            actionable_plan={
                "action": action,
                "segment": "CURRENCY",
                "contract": f"CDS:{clean_sym}",
                "entry_range": f"₹{round(ltp - 0.02, 4):.4f} – ₹{round(ltp + 0.02, 4):.4f}",
                "stop_loss": f"₹{sl_price:.4f}",
                "target": f"₹{t1_price:.4f}",
                "target_2": f"₹{t2_price:.4f}",
                "risk_reward": rr_str,
                "lot_size": curr_lot,
                "when_to_buy": "Execute on order book spread with defined risk below SL.",
                "when_to_wait": "Do not chase if spread widens > 0.05 paise.",
                "profit_rule": "Scale 50% at T1, move SL to entry.",
                "trade_plan": {
                    "symbol": clean_sym,
                    "direction": "LONG" if is_bullish else "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "risk_reward": rr_str,
                },
            },
        )
        found.append(alert)

    return found
