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


def get_currency_tailored_risk_and_chase(clean_sym: str, ltp: float) -> tuple[float, float]:
    """
    Calculates asset-tailored risk points and maximum chase boundary in rupees (paise).
    Tailored so USDINR is not over-risked and GBPINR has sufficient room to breathe (1 solution doesn't fit all).
    Returns (risk_rupees, max_chase_paise).
    """
    sym = clean_sym.upper()
    if "USD" in sym:
        # USDINR daily range is typically 10-18 paise; tight risk 4-6.5 paise
        risk = round(max(0.0350, min(0.0650, ltp * 0.0006)), 4)
        chase = round(max(0.0100, min(risk * 0.30, 0.0180)), 4)
    elif "EUR" in sym:
        # EURINR daily range is 35-50 paise; risk 8-16 paise
        risk = round(max(0.0800, min(0.1600, ltp * 0.0014)), 4)
        chase = round(max(0.0200, min(risk * 0.30, 0.0450)), 4)
    elif "GBP" in sym:
        # GBPINR daily range is 50-80 paise; risk 12-25 paise
        risk = round(max(0.1200, min(0.2500, ltp * 0.0018)), 4)
        chase = round(max(0.0300, min(risk * 0.30, 0.0700)), 4)
    elif "JPY" in sym:
        # JPYINR (per 100 JPY) range is 30-60 paise; risk 9-20 paise
        risk = round(max(0.0900, min(0.2000, ltp * 0.0025)), 4)
        chase = round(max(0.0250, min(risk * 0.30, 0.0550)), 4)
    else:
        risk = round(max(0.0500, ltp * 0.0010), 4)
        chase = round(risk * 0.30, 4)
    return risk, chase


def detect_currency_breakouts(
    universe: Optional[list[str]] = None,
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans liquid Currency pairs (USDINR, EURINR, GBPINR, JPYINR) for macro session breakouts.
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

        # Pair-tailored dynamic risk & no-chase limit
        risk_rupees, chase_cap = get_currency_tailored_risk_and_chase(clean_sym, ltp)

        from engine.position_sizer import get_lot_size

        curr_lot = get_lot_size(clean_sym) or 1000
        direction = "BULLISH" if is_bullish else "BEARISH"

        if is_bullish:
            sl_price = round(ltp - risk_rupees, 4)
            t1_price = round(ltp + 2.5 * risk_rupees, 4)
            t2_price = round(ltp + 4.5 * risk_rupees, 4)
            t3_price = round(ltp + 6.5 * risk_rupees, 4)
            no_chase = round(ltp + chase_cap, 4)
            e_low = round(max(sl_price + 0.0025, ltp - 0.15 * risk_rupees), 4)
            e_high = round(min(no_chase - 0.0025, ltp + 0.10 * risk_rupees), 4)
            if e_high <= e_low:
                e_high = round(no_chase - 0.0025, 4)
                e_low = round(max(sl_price + 0.0025, ltp - 0.08 * risk_rupees), 4)
            headline = f"💱 CURRENCY BREAKOUT: {clean_sym} +{chg:.2f}% @ ₹{ltp:.4f}"
            summary = f"Macro currency surge in {clean_sym}: Moving +{chg:.2f}% to ₹{ltp:.4f}. Long thesis active."
            action = "BUY_FUTURES"
        else:
            sl_price = round(ltp + risk_rupees, 4)
            t1_price = round(ltp - 2.5 * risk_rupees, 4)
            t2_price = round(ltp - 4.5 * risk_rupees, 4)
            t3_price = round(ltp - 6.5 * risk_rupees, 4)
            no_chase = round(ltp - chase_cap, 4)
            e_high = round(min(sl_price - 0.0025, ltp + 0.15 * risk_rupees), 4)
            e_low = round(max(no_chase + 0.0025, ltp - 0.10 * risk_rupees), 4)
            if e_low >= e_high:
                e_low = round(no_chase + 0.0025, 4)
                e_high = round(min(sl_price - 0.0025, ltp + 0.08 * risk_rupees), 4)
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
            no_chase_boundary=round(no_chase, 4),
            confidence=min(92, int(75 + abs(chg) * 30)),
            created_at=now_iso,
            is_live=is_authentic_live,
            environment="LIVE" if is_authentic_live else "TEST",
            market_status=cds_status,
            metrics={
                "change_pct": chg,
                "segment": "CURRENCY",
                "lot_size": curr_lot,
                "no_chase_boundary": round(no_chase, 4),
                "target_1": t1_price,
                "target_2": t2_price,
                "target_3": t3_price,
                "runner_target": t3_price,
            },
            actionable_plan={
                "action": action,
                "segment": "CURRENCY",
                "contract": f"CDS:{clean_sym}",
                "entry_range": f"₹{e_low:.4f} – ₹{e_high:.4f}",
                "stop_loss": f"₹{sl_price:.4f}",
                "target": f"₹{t1_price:.4f}",
                "target_1": f"₹{t1_price:.4f}",
                "target_2": f"₹{t2_price:.4f}",
                "target_3": f"₹{t3_price:.4f}",
                "runner_target": f"₹{t3_price:.4f}",
                "no_chase_boundary": f"₹{no_chase:.4f}",
                "risk_reward": rr_str,
                "lot_size": curr_lot,
                "when_to_buy": "Execute on order book spread with defined risk below SL.",
                "when_to_wait": f"Do not chase if price moves beyond ₹{no_chase:.4f}.",
                "profit_rule": f"Scale 50% at T1 (+2.5R), move SL to entry, scale 25% at T2 (+4.5R), runner to T3 (+6.5R).",
                "trade_plan": {
                    "symbol": clean_sym,
                    "direction": "LONG" if is_bullish else "SHORT",
                    "timeframe": "INTRADAY",
                    "entry_price": ltp,
                    "invalidation_stop": sl_price,
                    "target_1": t1_price,
                    "target_2": t2_price,
                    "target_3": t3_price,
                    "runner_target": t3_price,
                    "no_chase_boundary": no_chase,
                    "risk_reward": rr_str,
                },
            },
        )
        found.append(alert)

    return found
