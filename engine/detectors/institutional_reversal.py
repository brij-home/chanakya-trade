# -*- coding: utf-8 -*-
"""
engine/detectors/institutional_reversal.py
──────────────────────────────────────────
Institutional Top & Bottom Reversal Detector.

Wraps the 3-phase verification protocol from analysis.reversal_engine:
  Phase 1: Exhaustion & Stopping Volume (VSA, RSI/Bollinger Band extremes)
  Phase 2: Liquidity Sweep & SMT Divergence (Turtle Soup swing purge, RSI divergence)
  Phase 3: Micro-CHoCH & Candlestick Confirmation (Hammer, Engulfing, lower-TF break)

Generates asymmetric reversal setups with stops anchored beyond the sweep extreme (+0.15x ATR),
enforcing R:R >= 1:2.5 (average 1:3.5 to 1:5.0+).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.reversal_engine import analyse_reversal
from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert
from engine.option_resolver import (
    build_spot_anchored_option_overlay,
    is_index_symbol,
    resolve_option_contract,
)
from engine.position_sizer import get_lot_size

logger = logging.getLogger("chanakya.detectors.institutional_reversal")
IST = ZoneInfo("Asia/Kolkata")


def detect_institutional_reversals(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: float = 0.0,
    exchange: str = "NSE",
    timeframe: str = "15m",
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans an instrument for 3-Phase Institutional Bottom and Top Reversals.

    Args:
        symbol: Clean symbol (e.g., 'NIFTY', 'RELIANCE')
        df: 15m, 5m, or Daily OHLCV DataFrame
        ltp: Current Last Traded Price
        exchange: 'NSE', 'BSE'
        timeframe: '5m', '15m', 'day'
        quotes_map: Optional live quote snapshot

    Returns:
        List of AutoAlert objects (0 or 1 per symbol).
    """
    is_test = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = canonical_alert_symbol(symbol)
    alerts: list[AutoAlert] = []

    is_intraday = timeframe in ("5m", "15m", "1h", "intraday")
    min_bars = 25

    # 1. Fetch OHLCV if missing
    if df is None or len(df) < min_bars:
        if is_test:
            return []
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(
                clean_sym,
                exchange=exchange,
                interval=timeframe,
                days=5 if is_intraday else 120,
            )
        except Exception as e_hist:
            logger.debug(f"[institutional_reversal] OHLCV fetch failed for {clean_sym}: {e_hist}")
            return []

    if df is None or len(df) < min_bars:
        return []

    # 2. Fetch LTP if missing
    if ltp <= 0:
        if is_test:
            return []
        try:
            from market.quotes import get_ltp

            fetched = get_ltp(f"{exchange}:{clean_sym}")
            if fetched and float(fetched) > 0:
                ltp = float(fetched)
        except Exception:
            return []

    if not ltp or ltp <= 0:
        return []

    is_idx = is_index_symbol(clean_sym)
    asset_class = "INDEX" if is_idx else "EQUITY"

    # 3. Call 3-Phase Reversal Engine
    try:
        rev_sig = analyse_reversal(
            df=df,
            symbol=clean_sym,
            is_intraday=is_intraday,
            asset_class=asset_class,
        )
    except Exception as e_rev:
        logger.debug(f"[institutional_reversal] Analysis error on {clean_sym}: {e_rev}")
        return []

    if not rev_sig or rev_sig.reversal_type == "NONE" or rev_sig.confidence < 70:
        return []

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    is_bullish = rev_sig.bias == "BULLISH"
    direction = "BULLISH" if is_bullish else "BEARISH"
    alert_type = "INSTITUTIONAL_BOTTOM_REVERSAL" if is_bullish else "INSTITUTIONAL_TOP_REVERSAL"
    variant_tag = "bottom" if is_bullish else "top"

    alert_id = generate_alert_id(
        clean_sym,
        "INSTITUTIONAL_REVERSAL",
        variant=variant_tag,
    )

    stage = "CONFIRMED" if rev_sig.phase3_confirmation else "EARLY_WARNING"
    stop_loss = rev_sig.stop_loss
    t1 = rev_sig.target_1
    t2 = rev_sig.target_2
    t3 = rev_sig.target_3
    rr = rev_sig.risk_reward_ratio

    # Directional SL geometry guard against live LTP (prevents inverted SL <= Entry when tick overtakes bar anchor)
    if (is_bullish and stop_loss >= ltp) or (not is_bullish and stop_loss <= ltp):
        logger.debug(
            f"[institutional_reversal] Suppressed {alert_type} on {clean_sym}: "
            f"live LTP ₹{ltp:,.2f} already invalidates structural SL ₹{stop_loss:,.2f}."
        )
        return []

    # Option Contract Resolution
    stock_lot = get_lot_size(clean_sym)
    resolved_opt = None
    if is_idx or stock_lot > 1:
        try:
            resolved_opt = resolve_option_contract(
                symbol=clean_sym,
                spot=ltp,
                direction=direction,
                underlying_sl=stop_loss,
                underlying_target=t1,
                prefer_options=True,
            )
        except Exception as e_opt:
            logger.debug(
                f"[institutional_reversal] Option resolution error for {clean_sym}: {e_opt}"
            )

    has_opt = resolved_opt is not None and getattr(resolved_opt, "entry_premium", 0) > 0

    if is_bullish:
        headline = (
            f"🔥 BOTTOM REVERSAL: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
            f"(Spot ₹{ltp:,.1f}, SL ₹{stop_loss:,.1f}, R:R 1:{rr:.1f})"
            if has_opt
            else f"🔥 BOTTOM REVERSAL: {clean_sym} LONG @ ₹{ltp:,.1f} (SL ₹{stop_loss:,.1f}, Target ₹{t1:,.1f})"
        )
    else:
        headline = (
            f"🔥 TOP REVERSAL: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
            f"(Spot ₹{ltp:,.1f}, SL ₹{stop_loss:,.1f}, R:R 1:{rr:.1f})"
            if has_opt
            else f"🔥 TOP REVERSAL: {clean_sym} SHORT @ ₹{ltp:,.1f} (SL ₹{stop_loss:,.1f}, Target ₹{t1:,.1f})"
        )

    metrics = {
        "spot": ltp,
        "reversal_type": rev_sig.reversal_type,
        "timeframe": rev_sig.timeframe,
        "asset_class": rev_sig.asset_class,
        "phase1_exhaustion": rev_sig.phase1_exhaustion,
        "phase1_details": rev_sig.phase1_details,
        "phase2_sweep_or_divergence": rev_sig.phase2_sweep_or_divergence,
        "phase2_details": rev_sig.phase2_details,
        "phase3_confirmation": rev_sig.phase3_confirmation,
        "phase3_details": rev_sig.phase3_details,
        "candlestick_pattern": rev_sig.candlestick_pattern,
        "candlestick_strength": rev_sig.candlestick_strength,
        "choch_detected": rev_sig.choch_detected,
        "choch_level": rev_sig.choch_level,
        "risk_reward_ratio": rr,
        "no_chase_limit": rev_sig.no_chase_limit,
        "market_regime": rev_sig.market_regime,
        "recommended_strategy": rev_sig.recommended_strategy,
        "target_1": t1,
        "target_2": t2,
        "target_3": t3,
    }

    act_plan = None
    if has_opt:
        opt_metrics, act_plan = build_spot_anchored_option_overlay(
            resolved_opt,
            clean_sym=clean_sym,
            spot=ltp,
            spot_sl=stop_loss,
            spot_target=t1,
        )
        metrics.update(opt_metrics)

    alert = AutoAlert(
        alert_id=alert_id,
        symbol=clean_sym,
        exchange=exchange,
        alert_type=alert_type,
        direction=direction,
        stage=stage,
        ltp=ltp,
        underlying_spot=ltp,
        trigger_level=ltp,
        stop_loss=stop_loss,
        target_level=t1,
        confidence=rev_sig.confidence,
        headline=headline,
        summary=rev_sig.summary,
        created_at=now_iso,
        metrics=metrics,
        actionable_plan=act_plan,
    )
    alerts.append(alert)
    return alerts
