# -*- coding: utf-8 -*-
"""
engine/detectors/chart_pattern_detector.py
──────────────────────────────────────────
Institutional Classical & Geometric Chart Pattern Detector.

Wraps analysis.chart_patterns to detect high-conviction structural formations:
  1. Double Bottom (W-Pattern) & Double Top (M-Pattern)
  2. Inverse Head & Shoulders (Accumulation) & Head & Shoulders (Distribution)
  3. High-Tight Bull & Bear Flags (Impulse pole + dry volume consolidation)
  4. Ascending & Descending Triangles

Supports dual-stage interception:
  - Stage 1 (COILING): Right shoulder / flag consolidation before neckline breach (EARLY_WARNING).
  - Stage 2 (CONFIRMED): Decisive neckline breach with measured move target expansion.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.chart_patterns import detect_chart_patterns
from engine.alert_identity import canonical_alert_symbol, generate_alert_id
from engine.alert_model import AutoAlert
from engine.option_resolver import (
    build_spot_anchored_option_overlay,
    is_index_symbol,
    resolve_option_contract,
)
from engine.position_sizer import get_lot_size

logger = logging.getLogger("chanakya.detectors.chart_pattern_detector")
IST = ZoneInfo("Asia/Kolkata")


def detect_chart_pattern_setups(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: float = 0.0,
    exchange: str = "NSE",
    timeframe: str = "15m",
    quotes_map: Optional[dict[str, Any]] = None,
) -> list[AutoAlert]:
    """
    Scans for geometric chart pattern setups across indices and equities.
    """
    is_test = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = canonical_alert_symbol(symbol)
    alerts: list[AutoAlert] = []

    is_intraday = timeframe in ("5m", "15m", "1h", "intraday")
    min_bars = 15 if is_intraday else 20

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
            logger.debug(f"[chart_pattern] OHLCV fetch failed for {clean_sym}: {e_hist}")
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

    # Detect Chart Patterns
    try:
        patterns = detect_chart_patterns(df, ltp=ltp, lookback_bars=60)
    except Exception as e_pat:
        logger.debug(f"[chart_pattern] Pattern detection error on {clean_sym}: {e_pat}")
        return []

    if not patterns:
        return []

    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    is_idx = is_index_symbol(clean_sym)
    stock_lot = get_lot_size(clean_sym)

    for p in patterns[:2]:
        is_bullish = p.bias == "BULLISH"
        direction = "BULLISH" if is_bullish else "BEARISH"
        stage = "CONFIRMED" if p.status == "CONFIRMED" else "EARLY_WARNING"

        alert_type = f"CHART_{p.name}"
        alert_id = generate_alert_id(
            clean_sym,
            f"CHART_{p.name.lower()}",
            variant="bull" if is_bullish else "bear",
        )

        stop_loss = round(p.invalidation_stop, 2)
        target = round(p.measured_target, 2)
        neckline = round(p.neckline_or_pivot, 2)
        rr = round(p.risk_reward_ratio, 2)

        entry_anchor = neckline if stage == "EARLY_WARNING" else ltp
        if is_bullish:
            if not (target > ltp > stop_loss and target > entry_anchor > stop_loss):
                logger.debug(
                    f"[chart_pattern] Skipping invalid/exhausted bullish {p.name} on {clean_sym}: "
                    f"ltp={ltp}, anchor={entry_anchor}, sl={stop_loss}, target={target}"
                )
                continue
        else:
            if not (target < ltp < stop_loss and target < entry_anchor < stop_loss):
                logger.debug(
                    f"[chart_pattern] Skipping invalid/exhausted bearish {p.name} on {clean_sym}: "
                    f"ltp={ltp}, anchor={entry_anchor}, sl={stop_loss}, target={target}"
                )
                continue

        # Option contract resolution
        resolved_opt = None
        if is_idx or stock_lot > 1:
            try:
                resolved_opt = resolve_option_contract(
                    symbol=clean_sym,
                    spot=ltp,
                    direction=direction,
                    underlying_sl=stop_loss,
                    underlying_target=target,
                    prefer_options=True,
                )
            except Exception as e_opt:
                logger.debug(f"[chart_pattern] Option resolution error for {clean_sym}: {e_opt}")

        has_opt = resolved_opt is not None and getattr(resolved_opt, "entry_premium", 0) > 0

        icon = "📐" if stage == "CONFIRMED" else "⏳"
        if has_opt:
            headline = (
                f"{icon} {p.name.replace('_', ' ')}: {resolved_opt.contract_symbol} @ ₹{resolved_opt.entry_premium:,.1f} "
                f"(Spot ₹{ltp:,.1f}, Neckline ₹{neckline:,.1f})"
            )
        else:
            headline = (
                f"{icon} {p.name.replace('_', ' ')}: {clean_sym} {'LONG' if is_bullish else 'SHORT'} @ ₹{ltp:,.1f} "
                f"(Neckline ₹{neckline:,.1f}, Target ₹{target:,.1f})"
            )

        metrics = {
            "spot": ltp,
            "pattern_name": p.name,
            "pattern_type": p.pattern_type,
            "status": p.status,
            "neckline": neckline,
            "measured_target": target,
            "invalidation_stop": stop_loss,
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
                spot_target=target,
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
            trigger_level=neckline if stage == "EARLY_WARNING" else ltp,
            stop_loss=stop_loss,
            target_level=target,
            confidence=p.confidence,
            headline=headline,
            summary=p.summary,
            created_at=now_iso,
            metrics=metrics,
            actionable_plan=act_plan,
        )
        alerts.append(alert)

    return alerts
