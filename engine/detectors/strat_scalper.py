# -*- coding: utf-8 -*-
"""
engine/detectors/strat_scalper.py
─────────────────────────────────
Institutional Strat 2-1-2 & NR7 Volatility Compression Scalper.

Implements Rob Smith's 'The Strat' price action framework:
  - Strat 2-1-2 Bullish: 2-Up directional impulse -> 1-Inside consolidation bar -> 2-Up breakout.
  - Strat 2-1-2 Bearish: 2-Down directional impulse -> 1-Inside consolidation bar -> 2-Down breakdown.
  - Toby Crabel's NR7 / NR4 Volatility Compression: Narrowest range of 7 bars preceding explosive range expansion.

Provides sub-ATR micro-risk stops anchored to inside-bar extremes, yielding optimal R:R for
index scalping (NIFTY, BANKNIFTY) and high-beta F&O stocks.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.bar_patterns import analyze_bar_patterns
from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert
from engine.option_resolver import (
    build_spot_anchored_option_overlay,
    is_index_symbol,
    resolve_option_contract,
)
from engine.position_sizer import get_lot_size

logger = logging.getLogger("chanakya.detectors.strat_scalper")
IST = ZoneInfo("Asia/Kolkata")


def detect_strat_scalp_setups(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: float = 0.0,
    exchange: str = "NSE",
    timeframe: str = "5m",
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans for institutional Strat 2-1-2 and NR7 volatility compression scalping opportunities.
    """
    is_test = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = canonical_alert_symbol(symbol)
    alerts: list[AutoAlert] = []

    is_intraday = timeframe in ("1m", "3m", "5m", "15m", "intraday")
    min_bars = 7

    if df is None or len(df) < min_bars:
        if is_test:
            return []
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(
                clean_sym,
                exchange=exchange,
                interval=timeframe,
                days=3 if is_intraday else 30,
            )
        except Exception as e_hist:
            logger.debug(f"[strat_scalper] OHLCV fetch failed for {clean_sym}: {e_hist}")
            return []

    if df is None or len(df) < min_bars:
        return []

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

    try:
        sig = analyze_bar_patterns(df, symbol=clean_sym)
    except Exception as e_pat:
        logger.debug(f"[strat_scalper] Bar pattern analysis error on {clean_sym}: {e_pat}")
        return []

    if not sig or sig.bias == "NEUTRAL" or sig.confidence < 72:
        return []

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    is_bullish = sig.bias == "BULLISH"
    direction = "BULLISH" if is_bullish else "BEARISH"
    stage = "EARLY_WARNING" if sig.is_coiled_compression else "CONFIRMED"

    alert_type = sig.pattern_name
    alert_id = generate_alert_id(
        clean_sym,
        f"STRAT_{sig.pattern_name.lower()}",
        variant="bull" if is_bullish else "bear",
    )

    stop_loss = round(sig.stop_loss, 2)
    t1 = round(sig.target_1, 2)
    t2 = round(sig.target_2, 2)
    rr = round(sig.risk_reward_ratio, 2)
    trigger = round(sig.entry_trigger, 2) if sig.entry_trigger > 0 else ltp

    # Option contract resolution
    is_idx = is_index_symbol(clean_sym)
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
            logger.debug(f"[strat_scalper] Option resolution error for {clean_sym}: {e_opt}")

    has_opt = resolved_opt is not None and getattr(resolved_opt, "entry_premium", 0) > 0

    icon = "⚡" if "2_1_2" in sig.pattern_name else "🌀"
    if has_opt:
        headline = (
            f"{icon} {sig.pattern_name}: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
            f"(Spot ₹{ltp:,.1f}, SL ₹{stop_loss:,.1f}, R:R 1:{rr:.1f})"
        )
    else:
        headline = (
            f"{icon} {sig.pattern_name}: {clean_sym} {'LONG' if is_bullish else 'SHORT'} @ ₹{ltp:,.1f} "
            f"(Trigger ₹{trigger:,.1f}, SL ₹{stop_loss:,.1f})"
        )

    metrics = {
        "spot": ltp,
        "pattern_name": sig.pattern_name,
        "strat_sequence": sig.strat_sequence,
        "is_coiled_compression": sig.is_coiled_compression,
        "mother_bar_high": sig.mother_bar_high,
        "mother_bar_low": sig.mother_bar_low,
        "trigger_level": trigger,
        "stop_loss": stop_loss,
        "target_1": t1,
        "target_2": t2,
        "risk_reward_ratio": rr,
        "timeframe": timeframe,
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
        trigger_level=trigger,
        stop_loss=stop_loss,
        target_level=t1,
        confidence=sig.confidence,
        headline=headline,
        summary=sig.summary,
        created_at=now_iso,
        metrics=metrics,
        actionable_plan=act_plan,
    )
    alerts.append(alert)
    return alerts
