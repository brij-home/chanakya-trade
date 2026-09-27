"""
engine/detectors/crypto.py
──────────────────────────
24x7 Real-Time Autonomous Crypto Market Alert Detector.

Evaluates top liquid crypto benchmarks (BTC, ETH, SOL, BNB) across:
  1. Leading Leverage & Funding Squeeze (Binance Futures Open Interest + 8h Funding Rate)
  2. Smart Money Concepts (15m Market Structure, CHoCH, and Order Block bounces)
  3. Deribit Options Surface & Max Pain Magnet (BTC/ETH Options Volatility)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
import pandas as pd

from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.crypto")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]


@dataclass
class CryptoTradeLevels:
    entry_min: float
    entry_max: float
    entry_ref: float
    sl_price: float
    t1_price: float
    t2_price: float
    t3_price: float
    no_chase: float
    risk_usd: float
    rr_1: float
    rr_2: float
    rr_3: float
    rr_str: str
    profit_rule: str


def compute_crypto_atr(df: Optional[pd.DataFrame], period: int = 14) -> float:
    """Computes true ATR(14) from OHLCV candles."""
    if df is None or len(df) < period:
        return 0.0
    try:
        req = {"high", "low", "close"}
        cols = {str(c).lower(): c for c in df.columns}
        if not req.issubset(set(cols.keys())):
            return 0.0
        h = df[cols["high"]].astype(float)
        l = df[cols["low"]].astype(float)
        c = df[cols["close"]].astype(float)
        prev_c = c.shift(1).fillna(c)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        val = float(tr.rolling(window=period).mean().iloc[-1])
        return round(val, 2) if not pd.isna(val) and val > 0 else 0.0
    except Exception:
        return 0.0


def derive_crypto_trade_plan(
    symbol: str,
    direction: str,
    ltp: float,
    *,
    df: Optional[pd.DataFrame] = None,
    ob_bottom: Optional[float] = None,
    ob_top: Optional[float] = None,
    swing_high: Optional[float] = None,
    swing_low: Optional[float] = None,
    opposing_zone: Optional[float] = None,
    wick_extreme: Optional[float] = None,
    anchor_target: Optional[float] = None,
    atr_val: Optional[float] = None,
) -> CryptoTradeLevels:
    """
    Logically derives Entry range, Stop-Loss, Targets (T1, T2, T3/Runner),
    and mathematical R:R ratios from real market structure, ATR, and liquidity zones.
    Eliminates all hardcoded R:R strings and arbitrary static multipliers.
    """
    atr = atr_val if (atr_val and atr_val > 0) else compute_crypto_atr(df)
    is_bull = str(direction).upper() in ("BULLISH", "LONG", "BUY")

    if is_bull:
        # 1. Structural Stop-Loss (Inval)
        if wick_extreme is not None and wick_extreme > 0:
            sl_candidate = wick_extreme * 0.997
        elif ob_bottom is not None and ob_bottom > 0:
            if swing_low is not None and (ob_bottom * 0.985 <= swing_low <= ob_bottom):
                sl_candidate = swing_low * 0.997
            else:
                buf = max(ob_bottom * 0.005, 0.35 * atr) if atr > 0 else ob_bottom * 0.008
                sl_candidate = ob_bottom - buf
        elif df is not None and len(df) >= 10:
            recent_low = float(df["low"].iloc[-15:].min())
            sl_candidate = min(recent_low * 0.998, ltp - 1.5 * max(atr, ltp * 0.01))
        else:
            sl_candidate = ltp - 1.5 * max(atr, ltp * 0.012)

        sl_price = round(sl_candidate, 2)
        if sl_price >= ltp:
            sl_price = round(ltp * 0.985, 2)
        risk_usd = round(max(0.5, ltp - sl_price), 2)

        # 2. Entry Range & No Chase
        if ob_bottom is not None and ob_top is not None:
            entry_min = round(ob_bottom, 2)
            entry_max = round(max(ob_top, ltp) * 1.002, 2)
        else:
            entry_min = round(ltp - min(0.25 * risk_usd, ltp * 0.003), 2)
            entry_max = round(ltp + min(0.25 * risk_usd, ltp * 0.003), 2)

        no_chase = round(min(ltp + 0.45 * risk_usd, ltp * 1.008), 2)

        # 3. Targets (T1, T2, T3)
        min_reward_t1 = 2.0 * risk_usd
        if anchor_target is not None and (anchor_target - ltp) >= min_reward_t1:
            t1_price = round(anchor_target, 2)
        elif opposing_zone is not None and (opposing_zone - ltp) >= min_reward_t1:
            t1_price = round(opposing_zone, 2)
        elif swing_high is not None and (swing_high - ltp) >= min_reward_t1:
            t1_price = round(swing_high, 2)
        elif df is not None and len(df) >= 20:
            prior_high = float(df["high"].iloc[-20:].max())
            if (prior_high - ltp) >= min_reward_t1:
                t1_price = round(prior_high, 2)
            else:
                t1_price = round(
                    ltp + max(2.3 * risk_usd, 2.5 * atr if atr > 0 else 2.5 * risk_usd), 2
                )
        else:
            t1_price = round(ltp + max(2.3 * risk_usd, 2.5 * atr if atr > 0 else 2.5 * risk_usd), 2)

        if t1_price <= ltp:
            t1_price = round(ltp + 2.3 * risk_usd, 2)

        t1_reward = t1_price - ltp
        t2_price = round(t1_price + 1.4 * t1_reward, 2)
        t3_price = round(ltp + max(2.6 * t1_reward, 5.8 * risk_usd), 2)

        rr_1 = round((t1_price - ltp) / max(0.01, risk_usd), 1)
        rr_2 = round((t2_price - ltp) / max(0.01, risk_usd), 1)
        rr_3 = round((t3_price - ltp) / max(0.01, risk_usd), 1)

    else:
        # BEARISH / SHORT
        # 1. Structural Stop-Loss (Inval)
        if wick_extreme is not None and wick_extreme > 0:
            sl_candidate = wick_extreme * 1.003
        elif ob_top is not None and ob_top > 0:
            if swing_high is not None and (ob_top <= swing_high <= ob_top * 1.015):
                sl_candidate = swing_high * 1.003
            else:
                buf = max(ob_top * 0.005, 0.35 * atr) if atr > 0 else ob_top * 0.008
                sl_candidate = ob_top + buf
        elif df is not None and len(df) >= 10:
            recent_high = float(df["high"].iloc[-15:].max())
            sl_candidate = max(recent_high * 1.002, ltp + 1.5 * max(atr, ltp * 0.01))
        else:
            sl_candidate = ltp + 1.5 * max(atr, ltp * 0.012)

        sl_price = round(sl_candidate, 2)
        if sl_price <= ltp:
            sl_price = round(ltp * 1.015, 2)
        risk_usd = round(max(0.5, sl_price - ltp), 2)

        # 2. Entry Range & No Chase
        if ob_bottom is not None and ob_top is not None:
            entry_min = round(min(ob_bottom, ltp) * 0.998, 2)
            entry_max = round(ob_top, 2)
        else:
            entry_min = round(ltp - min(0.25 * risk_usd, ltp * 0.003), 2)
            entry_max = round(ltp + min(0.25 * risk_usd, ltp * 0.003), 2)

        no_chase = round(max(ltp - 0.45 * risk_usd, ltp * 0.992), 2)

        # 3. Targets (T1, T2, T3)
        min_reward_t1 = 2.0 * risk_usd
        if anchor_target is not None and (ltp - anchor_target) >= min_reward_t1:
            t1_price = round(anchor_target, 2)
        elif opposing_zone is not None and (ltp - opposing_zone) >= min_reward_t1:
            t1_price = round(opposing_zone, 2)
        elif swing_low is not None and (ltp - swing_low) >= min_reward_t1:
            t1_price = round(swing_low, 2)
        elif df is not None and len(df) >= 20:
            prior_low = float(df["low"].iloc[-20:].min())
            if (ltp - prior_low) >= min_reward_t1:
                t1_price = round(prior_low, 2)
            else:
                t1_price = round(
                    ltp - max(2.3 * risk_usd, 2.5 * atr if atr > 0 else 2.5 * risk_usd), 2
                )
        else:
            t1_price = round(ltp - max(2.3 * risk_usd, 2.5 * atr if atr > 0 else 2.5 * risk_usd), 2)

        if t1_price >= ltp:
            t1_price = round(ltp - 2.3 * risk_usd, 2)

        t1_reward = ltp - t1_price
        t2_price = round(t1_price - 1.4 * t1_reward, 2)
        t3_price = round(ltp - max(2.6 * t1_reward, 5.8 * risk_usd), 2)

        rr_1 = round((ltp - t1_price) / max(0.01, risk_usd), 1)
        rr_2 = round((ltp - t2_price) / max(0.01, risk_usd), 1)
        rr_3 = round((ltp - t3_price) / max(0.01, risk_usd), 1)

    rr_str = f"1:{rr_1} (T1) | 1:{rr_2} (T2) | 1:{rr_3} (Runner)"
    profit_rule = (
        f"Scale 50% at T1 (+{rr_1}R) & trail stop to breakeven. "
        f"Scale 25% at T2 (+{rr_2}R). Trail runner to T3 (+{rr_3}R)."
    )

    return CryptoTradeLevels(
        entry_min=entry_min,
        entry_max=entry_max,
        entry_ref=ltp,
        sl_price=sl_price,
        t1_price=t1_price,
        t2_price=t2_price,
        t3_price=t3_price,
        no_chase=no_chase,
        risk_usd=risk_usd,
        rr_1=rr_1,
        rr_2=rr_2,
        rr_3=rr_3,
        rr_str=rr_str,
        profit_rule=profit_rule,
    )


def detect_single_crypto_symbol(sym: str) -> list[AutoAlert]:
    """Scans a single crypto symbol for Squeeze, SMC Momentum, and Options Volatility."""
    from market.crypto_stream import crypto_stream, normalize_crypto_symbol
    from analysis.market_structure import analyze_market_structure
    from engine.alert_preferences import alert_preferences
    from engine.alert_identity import generate_alert_id

    if alert_preferences.is_segment_globally_disabled("CRYPTO"):
        return []

    clean_sym = normalize_crypto_symbol(sym).replace("CRYPTO:", "").strip()
    found: list[AutoAlert] = []
    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    q = crypto_stream.get_quote(clean_sym)
    if not q or float(getattr(q, "last_price", 0.0) or 0.0) <= 0:
        return found

    ltp = float(q.last_price)
    chg_pct = float(getattr(q, "change_pct", 0.0) or 0.0)
    df = crypto_stream.get_klines(clean_sym, interval="15m", limit=120)

    # ── 1. SQUEEZE DETECTOR: Binance Futures 8h Funding Rate & Open Interest ──
    try:
        sq_metrics = crypto_stream.get_squeeze_metrics(clean_sym)
        sq_sig = sq_metrics.get("squeeze_signal", "NEUTRAL")
        fut_data = sq_metrics.get("futures_metrics", {})
        fr = float(fut_data.get("funding_rate_8h", 0.0) or 0.0)

        if sq_sig in ("SHORT_SQUEEZE_IMMINENT", "LONG_FLUSH_RISK"):
            is_bullish = sq_sig == "SHORT_SQUEEZE_IMMINENT"
            direction = "BULLISH" if is_bullish else "BEARISH"
            alert_type = "CRYPTO_SQUEEZE"
            alert_id = generate_alert_id(clean_sym, alert_type)
            squeeze_confidence = 91 if sq_sig == "SHORT_SQUEEZE_IMMINENT" else 90

            plan = derive_crypto_trade_plan(clean_sym, direction=direction, ltp=ltp, df=df)
            sl_price = plan.sl_price
            t1_price = plan.t1_price
            t2_price = plan.t2_price
            t3_price = plan.t3_price
            rr_str = plan.rr_str
            profit_rule = plan.profit_rule
            entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
            no_chase = plan.no_chase

            if is_bullish:
                headline = f"🪙 CRYPTO SQUEEZE: {clean_sym} Short-Squeeze Imminent @ ${ltp:,.2f}"
                summary = (
                    f"Heavily short-crowded funding (8h FR: {fr * 100:.4f}%). "
                    f"Extreme negative leverage positioning primed for upward cascade. Target: ${t1_price:,.2f}."
                )
                action = "BUY_SPOT / LONG"
                conf = "Binance Futures Short-Crowded Funding Imbalance (FR <= -0.02%)"
            else:
                headline = (
                    f"🪙 CRYPTO SQUEEZE: {clean_sym} Long-Flush Liquidation Risk @ ${ltp:,.2f}"
                )
                summary = (
                    f"Overheated long leverage (8h FR: +{fr * 100:.4f}%). "
                    f"Vulnerable to cascading long liquidations. Downside target: ${t1_price:,.2f}."
                )
                action = "SELL_SHORT_FUTURES / SHORT"
                conf = "Binance Futures Long-Overheated Leverage Imbalance (FR >= +0.04%)"

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED" if abs(chg_pct) >= 1.5 else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="CRYPTO",
                segment="CRYPTO",
                time_horizon="INTRADAY",
                eta_label="24h Rolling",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=squeeze_confidence,
                created_at=now_iso,
                is_live=True,
                environment="LIVE",
                market_status="LIVE",
                metrics={
                    "change_pct": chg_pct,
                    "segment": "CRYPTO",
                    "funding_rate_8h": fr,
                    "open_interest_usd": fut_data.get("open_interest_usd", 0.0),
                    "setup_confluence": conf,
                },
                actionable_plan={
                    "action": action,
                    "segment": "CRYPTO",
                    "contract": f"CRYPTO:{clean_sym}",
                    "entry_range": entry_range,
                    "stop_loss": f"${sl_price:,.2f}",
                    "target": f"${t1_price:,.2f}",
                    "target_2": f"${t2_price:,.2f}",
                    "target_3": f"${t3_price:,.2f}",
                    "runner": f"${t3_price:,.2f}",
                    "risk_reward": rr_str,
                    "when_to_buy": "Enter on order book spread with defined risk below invalidation SL.",
                    "when_to_wait": "Do not chase if price extends > 0.8% beyond entry.",
                    "no_chase_boundary": no_chase,
                    "setup_confluence": conf,
                    "profit_rule": profit_rule,
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "LONG" if is_bullish else "SHORT",
                        "timeframe": "15M",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "target_3": t3_price,
                        "risk_reward": rr_str,
                    },
                },
            )
            found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Squeeze check failed for {clean_sym}: {e}")

    # ── 2. SMC MOMENTUM DETECTOR: Order Block Reclaim & CHoCH Reversal ──
    try:
        if df is not None and not df.empty and len(df) >= 30:
            smc = analyze_market_structure(
                symbol=clean_sym, df=df, exchange="CRYPTO", timeframe="15m"
            )
            regime = (smc.regime or "").upper()

            if regime == "BULLISH" and smc.active_demand_zones:
                ob = smc.active_demand_zones[0]
                if ob.bottom <= ltp <= (ob.top * 1.025):
                    supplies = [s for s in smc.active_supply_zones if s.bottom > ltp]
                    opposing_target = (
                        min(supplies, key=lambda s: s.bottom).bottom if supplies else None
                    )
                    plan = derive_crypto_trade_plan(
                        clean_sym,
                        direction="BULLISH",
                        ltp=ltp,
                        df=df,
                        ob_bottom=ob.bottom,
                        ob_top=ob.top,
                        swing_high=smc.last_swing_high,
                        swing_low=smc.last_swing_low,
                        opposing_zone=opposing_target,
                    )
                    sl_price = plan.sl_price
                    t1_price = plan.t1_price
                    t2_price = plan.t2_price
                    t3_price = plan.t3_price
                    rr_str = plan.rr_str
                    profit_rule = plan.profit_rule
                    entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
                    no_chase = plan.no_chase
                    risk_usd = plan.risk_usd

                    if 0 < risk_usd <= (ltp * 0.05):
                        smc_stage = "IGNITED" if ltp > ob.top else "EARLY_WARNING"
                        smc_confidence = 91 if smc_stage == "IGNITED" else 85
                        alert_id = generate_alert_id(clean_sym, "CRYPTO_MOMENTUM", variant="demand")
                        headline = f"⚡ CRYPTO SMC ALPHA: {clean_sym} Demand Order Block Reclaim @ ${ltp:,.2f}"
                        summary = (
                            f"Smart Money structural reclaim at 15m Demand OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                            f"Bullish structure confirmed. Upside target: ${t1_price:,.2f}."
                        )
                        conf = f"15m Bullish Regime + Unmitigated Demand OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"

                        alert = AutoAlert(
                            alert_id=alert_id,
                            alert_type="CRYPTO_MOMENTUM",
                            stage=smc_stage,
                            symbol=clean_sym,
                            exchange="CRYPTO",
                            segment="CRYPTO",
                            time_horizon="INTRADAY",
                            eta_label="24h Rolling",
                            direction="BULLISH",
                            headline=headline,
                            summary=summary,
                            ltp=ltp,
                            trigger_level=round(ob.top, 2),
                            target_level=t1_price,
                            stop_loss=sl_price,
                            confidence=smc_confidence,
                            created_at=now_iso,
                            is_live=True,
                            environment="LIVE",
                            market_status="LIVE",
                            metrics={
                                "change_pct": chg_pct,
                                "segment": "CRYPTO",
                                "ob_bottom": ob.bottom,
                                "ob_top": ob.top,
                                "setup_confluence": conf,
                            },
                            actionable_plan={
                                "action": "BUY_SPOT / LONG",
                                "segment": "CRYPTO",
                                "contract": f"CRYPTO:{clean_sym}",
                                "entry_range": entry_range,
                                "stop_loss": f"${sl_price:,.2f}",
                                "target": f"${t1_price:,.2f}",
                                "target_2": f"${t2_price:,.2f}",
                                "target_3": f"${t3_price:,.2f}",
                                "runner": f"${t3_price:,.2f}",
                                "risk_reward": rr_str,
                                "when_to_buy": "Enter on order block retest or momentum breakout above OB top.",
                                "when_to_wait": f"Do not chase above ${no_chase:,.2f}.",
                                "no_chase_boundary": no_chase,
                                "setup_confluence": conf,
                                "profit_rule": profit_rule,
                                "trade_plan": {
                                    "symbol": clean_sym,
                                    "direction": "LONG",
                                    "timeframe": "15M",
                                    "entry_price": ltp,
                                    "invalidation_stop": sl_price,
                                    "target_1": t1_price,
                                    "target_2": t2_price,
                                    "target_3": t3_price,
                                    "risk_reward": rr_str,
                                },
                            },
                        )
                        found.append(alert)

            elif regime == "BEARISH" and smc.active_supply_zones:
                ob = smc.active_supply_zones[0]
                if (ob.bottom * 0.975) <= ltp <= ob.top:
                    demands = [d for d in smc.active_demand_zones if d.top < ltp]
                    opposing_target = max(demands, key=lambda d: d.top).top if demands else None
                    plan = derive_crypto_trade_plan(
                        clean_sym,
                        direction="BEARISH",
                        ltp=ltp,
                        df=df,
                        ob_bottom=ob.bottom,
                        ob_top=ob.top,
                        swing_high=smc.last_swing_high,
                        swing_low=smc.last_swing_low,
                        opposing_zone=opposing_target,
                    )
                    sl_price = plan.sl_price
                    t1_price = plan.t1_price
                    t2_price = plan.t2_price
                    t3_price = plan.t3_price
                    rr_str = plan.rr_str
                    profit_rule = plan.profit_rule
                    entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
                    no_chase = plan.no_chase
                    risk_usd = plan.risk_usd

                    if 0 < risk_usd <= (ltp * 0.05):
                        smc_stage = "IGNITED" if ltp < ob.bottom else "EARLY_WARNING"
                        smc_confidence = 91 if smc_stage == "IGNITED" else 85
                        alert_id = generate_alert_id(clean_sym, "CRYPTO_MOMENTUM", variant="supply")
                        headline = f"⚡ CRYPTO SMC BREAKDOWN: {clean_sym} Supply OB Rejection @ ${ltp:,.2f}"
                        summary = (
                            f"Smart Money rejection at 15m Supply OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                            f"Bearish structure confirmed. Downside target: ${t1_price:,.2f}."
                        )
                        conf = f"15m Bearish Regime + Active Supply OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"

                        alert = AutoAlert(
                            alert_id=alert_id,
                            alert_type="CRYPTO_MOMENTUM",
                            stage=smc_stage,
                            symbol=clean_sym,
                            exchange="CRYPTO",
                            segment="CRYPTO",
                            time_horizon="INTRADAY",
                            eta_label="24h Rolling",
                            direction="BEARISH",
                            headline=headline,
                            summary=summary,
                            ltp=ltp,
                            trigger_level=round(ob.bottom, 2),
                            target_level=t1_price,
                            stop_loss=sl_price,
                            confidence=smc_confidence,
                            created_at=now_iso,
                            is_live=True,
                            environment="LIVE",
                            market_status="LIVE",
                            metrics={
                                "change_pct": chg_pct,
                                "segment": "CRYPTO",
                                "ob_bottom": ob.bottom,
                                "ob_top": ob.top,
                                "setup_confluence": conf,
                            },
                            actionable_plan={
                                "action": "SELL_SHORT_FUTURES / SHORT",
                                "segment": "CRYPTO",
                                "contract": f"CRYPTO:{clean_sym}",
                                "entry_range": entry_range,
                                "stop_loss": f"${sl_price:,.2f}",
                                "target": f"${t1_price:,.2f}",
                                "target_2": f"${t2_price:,.2f}",
                                "target_3": f"${t3_price:,.2f}",
                                "runner": f"${t3_price:,.2f}",
                                "risk_reward": rr_str,
                                "when_to_buy": "Short on rejection wick from supply OB.",
                                "when_to_wait": f"Do not chase below ${no_chase:,.2f}.",
                                "no_chase_boundary": no_chase,
                                "setup_confluence": conf,
                                "profit_rule": profit_rule,
                                "trade_plan": {
                                    "symbol": clean_sym,
                                    "direction": "SHORT",
                                    "timeframe": "15M",
                                    "entry_price": ltp,
                                    "invalidation_stop": sl_price,
                                    "target_1": t1_price,
                                    "target_2": t2_price,
                                    "target_3": t3_price,
                                    "risk_reward": rr_str,
                                },
                            },
                        )
                        found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] SMC check failed for {clean_sym}: {e}")

    # ── 2b. CRYPTO MOMENTUM & VOLATILITY EXPANSION DETECTOR: 15m Donchian / EMA Trend ──
    try:
        if df is not None and not df.empty and len(df) >= 20:
            recent_20 = df.iloc[-21:-1]
            prior_high = float(recent_20["high"].max())
            prior_low = float(recent_20["low"].min())
            last_bar = df.iloc[-1]
            cur_close = float(last_bar.get("close", ltp))
            vols = df["volume"] if "volume" in df.columns else df.get("Volume")
            rvol = 1.0
            if vols is not None and len(vols) >= 20:
                avg_v = float(vols.iloc[-21:-1].mean())
                cur_v = float(last_bar.get("volume", 0.0) or 0.0)
                rvol = round(cur_v / max(1.0, avg_v), 2) if avg_v > 0 else 1.0

            ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
            is_breakout_long = (
                (ltp >= prior_high * 0.999 or cur_close >= prior_high)
                and ltp > ema20
                and rvol >= 1.25
                and chg_pct >= 0.8
            )
            is_breakdown_short = (
                (ltp <= prior_low * 1.001 or cur_close <= prior_low)
                and ltp < ema20
                and rvol >= 1.25
                and chg_pct <= -0.8
            )

            if is_breakout_long or is_breakdown_short:
                brk_dir = "BULLISH" if is_breakout_long else "BEARISH"
                swing_low = float(df["low"].iloc[-10:].min()) if is_breakout_long else None
                swing_high = float(df["high"].iloc[-10:].max()) if is_breakdown_short else None
                plan = derive_crypto_trade_plan(
                    clean_sym,
                    direction=brk_dir,
                    ltp=ltp,
                    df=df,
                    swing_high=swing_high,
                    swing_low=swing_low,
                )
                sl_price = plan.sl_price
                t1_price = plan.t1_price
                t2_price = plan.t2_price
                t3_price = plan.t3_price
                rr_str = plan.rr_str
                profit_rule = plan.profit_rule
                entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
                no_chase = plan.no_chase

                alert_id = generate_alert_id(
                    clean_sym,
                    "CRYPTO_BREAKOUT",
                    variant="long" if is_breakout_long else "short",
                )
                headline = (
                    f"🚀 CRYPTO MOMENTUM BREAKOUT: {clean_sym} Pierces 20-Bar High @ ${ltp:,.2f} (RVOL {rvol:.1f}x)"
                    if is_breakout_long
                    else f"🔻 CRYPTO MOMENTUM BREAKDOWN: {clean_sym} Pierces 20-Bar Low @ ${ltp:,.2f} (RVOL {rvol:.1f}x)"
                )
                summary = (
                    f"24x7 volume expansion breakout (RVOL {rvol:.1f}x, 24h: {chg_pct:+.2f}%). "
                    f"Structure confirmed above 20-EMA (${ema20:,.2f}). Target 1: ${t1_price:,.2f}."
                    if is_breakout_long
                    else f"24x7 volume expansion breakdown (RVOL {rvol:.1f}x, 24h: {chg_pct:+.2f}%). "
                    f"Structure confirmed below 20-EMA (${ema20:,.2f}). Target 1: ${t1_price:,.2f}."
                )
                action = "BUY_SPOT / LONG" if is_breakout_long else "SELL_SHORT_FUTURES / SHORT"
                conf = (
                    f"15m 20-Bar High Breakout + RVOL {rvol:.1f}x + 20-EMA Support"
                    if is_breakout_long
                    else f"15m 20-Bar Low Breakdown + RVOL {rvol:.1f}x + 20-EMA Resistance"
                )

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="CRYPTO_BREAKOUT",
                    stage="IGNITED" if rvol >= 1.5 else "EARLY_WARNING",
                    symbol=clean_sym,
                    exchange="CRYPTO",
                    segment="CRYPTO",
                    time_horizon="INTRADAY",
                    eta_label="24h Rolling",
                    direction=brk_dir,
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=prior_high if is_breakout_long else prior_low,
                    target_level=t1_price,
                    stop_loss=sl_price,
                    confidence=92 if rvol >= 1.5 else 86,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    market_status="LIVE",
                    metrics={
                        "change_pct": chg_pct,
                        "segment": "CRYPTO",
                        "rvol": rvol,
                        "ema20": ema20,
                        "prior_high": prior_high,
                        "prior_low": prior_low,
                        "setup_confluence": conf,
                    },
                    actionable_plan={
                        "action": action,
                        "segment": "CRYPTO",
                        "contract": f"CRYPTO:{clean_sym}",
                        "entry_range": entry_range,
                        "stop_loss": f"${sl_price:,.2f}",
                        "target": f"${t1_price:,.2f}",
                        "target_2": f"${t2_price:,.2f}",
                        "target_3": f"${t3_price:,.2f}",
                        "runner": f"${t3_price:,.2f}",
                        "risk_reward": rr_str,
                        "when_to_buy": "Execute on volume breakout or retest of pivot.",
                        "when_to_wait": "Do not chase beyond 0.8% from entry.",
                        "no_chase_boundary": no_chase,
                        "setup_confluence": conf,
                        "profit_rule": profit_rule,
                        "trade_plan": {
                            "symbol": clean_sym,
                            "direction": "LONG" if is_breakout_long else "SHORT",
                            "timeframe": "15M",
                            "entry_price": ltp,
                            "invalidation_stop": sl_price,
                            "target_1": t1_price,
                            "target_2": t2_price,
                            "target_3": t3_price,
                            "risk_reward": rr_str,
                        },
                    },
                )
                found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Momentum breakout check failed for {clean_sym}: {e}")

    # ── 3. OPTIONS VOLATILITY & MAX PAIN DETECTOR: Deribit Options Surface (BTC/ETH) ──
    if clean_sym in ("BTCUSDT", "BTC", "ETHUSDT", "ETH"):
        try:
            from market.crypto_options import get_crypto_options_summary

            base_curr = "BTC" if "BTC" in clean_sym else "ETH"
            opt_sum = get_crypto_options_summary(base_curr)
            max_pain = float(opt_sum.get("max_pain", 0.0) or 0.0)
            dist_pct = float(opt_sum.get("max_pain_distance_pct", 0.0) or 0.0)
            pcr_oi = float(opt_sum.get("pcr_open_interest", 1.0) or 1.0)
            net_gex = float(opt_sum.get("net_gex_usd", 0.0) or 0.0)
            gamma_regime = str(opt_sum.get("gamma_regime", "NEUTRAL"))
            gex_flip = float(opt_sum.get("gex_flip_strike", 0.0) or 0.0)

            if abs(dist_pct) >= 4.5 and max_pain > 0:
                # Correct Institutional Deribit Max Pain Gravitational Mechanics:
                # If dist_pct > 0 (Max Pain > Spot), spot is below Max Pain and pulled UP -> BULLISH
                # If dist_pct < 0 (Max Pain < Spot), spot is above Max Pain and pulled DOWN -> BEARISH
                is_bullish = dist_pct > 0
                direction = "BULLISH" if is_bullish else "BEARISH"
                alert_id = generate_alert_id(
                    clean_sym, "CRYPTO_VOLATILITY", variant="options-gravity"
                )
                plan = derive_crypto_trade_plan(
                    clean_sym,
                    direction=direction,
                    ltp=ltp,
                    df=df,
                    anchor_target=max_pain,
                )
                sl_price = plan.sl_price
                t1_price = plan.t1_price
                t2_price = plan.t2_price
                t3_price = plan.t3_price
                rr_str = plan.rr_str
                profit_rule = plan.profit_rule
                entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
                no_chase = plan.no_chase

                if is_bullish:
                    headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Max Pain Magnet at ${max_pain:,.0f}"
                    summary = (
                        f"Spot (${ltp:,.2f}) is {abs(dist_pct):.1f}% below Deribit Max Pain (${max_pain:,.0f}). "
                        f"Options dealer gamma position exerts strong upward gravitational pull into expiry."
                    )
                    action = "BUY_SPOT / LONG"
                else:
                    headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Overextended Above Max Pain (${max_pain:,.0f})"
                    summary = (
                        f"Spot (${ltp:,.2f}) is +{abs(dist_pct):.1f}% extended above Deribit Max Pain (${max_pain:,.0f}). "
                        f"Dealer gamma pull indicates mean-reversion pull down towards ${max_pain:,.0f}."
                    )
                    action = "SELL_SHORT_FUTURES / SHORT"

                conf = (
                    f"Deribit {base_curr} Max Pain Gravitational Magnet (${max_pain:,.0f} | "
                    f"PCR: {pcr_oi:.2f} | {gamma_regime} Net GEX: ${net_gex:+,.0f})"
                )

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="CRYPTO_VOLATILITY",
                    stage="EARLY_WARNING",
                    symbol=clean_sym,
                    exchange="CRYPTO",
                    segment="CRYPTO",
                    time_horizon="INTRADAY",
                    eta_label="24h Rolling",
                    direction=direction,
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=(
                        round(ltp * 1.0025, 2) if is_bullish else round(ltp * 0.9975, 2)
                    ),
                    target_level=t1_price,
                    stop_loss=sl_price,
                    confidence=85,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    market_status="LIVE",
                    metrics={
                        "change_pct": chg_pct,
                        "segment": "CRYPTO",
                        "time_horizon": "SWING",
                        "max_pain": max_pain,
                        "max_pain_dist_pct": dist_pct,
                        "pcr_oi": pcr_oi,
                        "net_gex_usd": net_gex,
                        "gamma_regime": gamma_regime,
                        "gex_flip_strike": gex_flip,
                        "setup_confluence": conf,
                    },
                    actionable_plan={
                        "action": action,
                        "segment": "CRYPTO",
                        "contract": f"CRYPTO:{clean_sym}",
                        "entry_range": entry_range,
                        "stop_loss": f"${sl_price:,.2f}",
                        "target": f"${t1_price:,.2f}",
                        "target_2": f"${t2_price:,.2f}",
                        "target_3": f"${t3_price:,.2f}",
                        "runner": f"${t3_price:,.2f}",
                        "risk_reward": rr_str,
                        "when_to_buy": "Execute on structural support with defined risk below SL.",
                        "when_to_wait": "Do not chase if price moves > 1% towards Max Pain without retest.",
                        "no_chase_boundary": no_chase,
                        "setup_confluence": conf,
                        "profit_rule": profit_rule,
                        "trade_plan": {
                            "symbol": clean_sym,
                            "direction": direction,
                            "timeframe": "SWING",
                            "entry_price": ltp,
                            "invalidation_stop": sl_price,
                            "target_1": t1_price,
                            "target_2": t2_price,
                            "target_3": t3_price,
                            "risk_reward": rr_str,
                        },
                    },
                )
                found.append(alert)
        except Exception as e:
            logger.debug(f"[CryptoDetector] Options gravity check failed for {clean_sym}: {e}")

    # ── 4. ORDER FLOW & CVD ABSORPTION DETECTOR: Cumulative Volume Delta & Divergence ──
    try:
        of_metrics = crypto_stream.get_order_flow_metrics(clean_sym, interval="15m", limit=50)
        abs_sig = of_metrics.get("absorption_signal", "NONE")
        if abs_sig in (
            "BULLISH_CVD_ABSORPTION",
            "BULLISH_DELTA_ABSORPTION",
            "BEARISH_CVD_EXHAUSTION",
            "BEARISH_DELTA_ABSORPTION",
        ):
            is_bull = abs_sig.startswith("BULLISH")
            direction = "BULLISH" if is_bull else "BEARISH"
            alert_id = generate_alert_id(
                clean_sym,
                "CRYPTO_CVD_ABSORPTION",
                variant="bull" if is_bull else "bear",
            )
            wick_extreme = None
            if df is not None and not df.empty and len(df) >= 2:
                wick_extreme = float(df["low"].iloc[-1]) if is_bull else float(df["high"].iloc[-1])

            plan = derive_crypto_trade_plan(
                clean_sym,
                direction=direction,
                ltp=ltp,
                df=df,
                wick_extreme=wick_extreme,
            )
            sl_price = plan.sl_price
            t1_price = plan.t1_price
            t2_price = plan.t2_price
            t3_price = plan.t3_price
            rr_str = plan.rr_str
            profit_rule = plan.profit_rule
            entry_range = f"${plan.entry_min:,.2f} – ${plan.entry_max:,.2f}"
            no_chase = plan.no_chase

            if is_bull:
                headline = f"🪙 CRYPTO ORDER FLOW: {clean_sym} Bullish CVD Absorption @ ${ltp:,.2f}"
                summary = (
                    f"Institutional CVD absorption confirmed: aggressive market sellers absorbed by passive limit bids. "
                    f"Delta: {of_metrics.get('current_delta', 0):+,.1f}, CVD: {of_metrics.get('cumulative_volume_delta', 0):+,.1f}. Target: ${t1_price:,.2f}."
                )
                action = "BUY_SPOT / LONG"
                conf = f"15m Order Flow CVD Absorption (Delta: {of_metrics.get('current_delta', 0):+,.1f})"
            else:
                headline = f"🪙 CRYPTO ORDER FLOW: {clean_sym} Bearish CVD Exhaustion @ ${ltp:,.2f}"
                summary = (
                    f"Institutional CVD exhaustion confirmed: aggressive market buyers absorbed by passive limit offers. "
                    f"Delta: {of_metrics.get('current_delta', 0):+,.1f}, CVD: {of_metrics.get('cumulative_volume_delta', 0):+,.1f}. Downside target: ${t1_price:,.2f}."
                )
                action = "SELL_SHORT_FUTURES / SHORT"
                conf = f"15m Order Flow CVD Exhaustion (Delta: {of_metrics.get('current_delta', 0):+,.1f})"

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type="CRYPTO_CVD_ABSORPTION",
                stage="IGNITED" if of_metrics.get("conviction", 50) >= 90 else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="CRYPTO",
                segment="CRYPTO",
                time_horizon="INTRADAY",
                eta_label="24h Rolling",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=int(of_metrics.get("conviction", 88)),
                created_at=now_iso,
                is_live=True,
                environment="LIVE",
                market_status="LIVE",
                metrics={
                    "change_pct": chg_pct,
                    "segment": "CRYPTO",
                    "current_delta": of_metrics.get("current_delta", 0.0),
                    "cumulative_volume_delta": of_metrics.get("cumulative_volume_delta", 0.0),
                    "delta_bias": of_metrics.get("delta_bias", "NEUTRAL"),
                    "cvd_trend": of_metrics.get("cvd_trend", "FLAT"),
                    "setup_confluence": conf,
                },
                actionable_plan={
                    "action": action,
                    "segment": "CRYPTO",
                    "contract": f"CRYPTO:{clean_sym}",
                    "entry_range": entry_range,
                    "stop_loss": f"${sl_price:,.2f}",
                    "target": f"${t1_price:,.2f}",
                    "target_2": f"${t2_price:,.2f}",
                    "target_3": f"${t3_price:,.2f}",
                    "runner": f"${t3_price:,.2f}",
                    "risk_reward": rr_str,
                    "when_to_buy": "Execute on order flow absorption confirmation.",
                    "when_to_wait": "Do not chase if price extends > 0.8% beyond entry.",
                    "no_chase_boundary": no_chase,
                    "setup_confluence": conf,
                    "profit_rule": profit_rule,
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": direction,
                        "timeframe": "15M",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "target_3": t3_price,
                        "risk_reward": rr_str,
                    },
                },
            )
            found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Order flow CVD check failed for {clean_sym}: {e}")

    # ── 5. LIQUIDATION CASCADE & FLUSH EXHAUSTION DETECTOR ──
    try:
        liq_metrics = crypto_stream.get_liquidation_cascade_metrics(clean_sym)
        flush_sig = liq_metrics.get("flush_signal", "NONE")
        if flush_sig in ("LONG_LIQUIDATION_FLUSH_REVERSAL", "SHORT_SQUEEZE_BLOWOFF_REVERSAL"):
            is_long_flush = flush_sig == "LONG_LIQUIDATION_FLUSH_REVERSAL"
            direction = "BULLISH" if is_long_flush else "BEARISH"
            alert_id = generate_alert_id(
                clean_sym,
                "CRYPTO_LIQUIDATION_FLUSH",
                variant="long" if is_long_flush else "short",
            )
            sl_price = float(liq_metrics.get("stop_loss", 0.0))
            t1_price = float(liq_metrics.get("target_1", 0.0))
            t2_price = float(liq_metrics.get("target_2", 0.0))
            risk_amt = max(0.5, abs(ltp - sl_price))
            t3_price = (
                round(ltp + 6.0 * risk_amt, 2) if is_long_flush else round(ltp - 6.0 * risk_amt, 2)
            )
            rvol = float(liq_metrics.get("rvol", 1.0))

            rr_1 = round(abs(t1_price - ltp) / risk_amt, 1)
            rr_2 = round(abs(t2_price - ltp) / risk_amt, 1)
            rr_3 = round(abs(t3_price - ltp) / risk_amt, 1)
            rr_str = f"1:{rr_1} (T1) | 1:{rr_2} (T2) | 1:{rr_3} (Runner)"
            profit_rule = (
                f"Scale 50% at T1 (+{rr_1}R) & trail stop to breakeven. "
                f"Scale 25% at T2 (+{rr_2}R). Trail runner to T3 (+{rr_3}R)."
            )
            entry_range = f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}"
            no_chase = round(ltp * 1.008, 2) if is_long_flush else round(ltp * 0.992, 2)

            if is_long_flush:
                headline = f"⚡ CRYPTO LIQUIDATION FLUSH: {clean_sym} Long Liquidation Reversal @ ${ltp:,.2f}"
                summary = (
                    f"Cascading long stop liquidations flushed into deep support before sharp wick reclaim (RVOL {rvol:.1f}x). "
                    f"Stops flushed, institutional bids absorbed. Target 1: ${t1_price:,.2f}."
                )
                action = "BUY_SPOT / LONG"
                conf = f"15m Forced Liquidation Sweep & Wick Reclaim (RVOL {rvol:.1f}x)"
            else:
                headline = f"⚡ CRYPTO LIQUIDATION FLUSH: {clean_sym} Short Blow-Off Exhaustion @ ${ltp:,.2f}"
                summary = (
                    f"Overleveraged shorts liquidated on violent spike before aggressive rejection wick (RVOL {rvol:.1f}x). "
                    f"Exhaustion top confirmed. Downside target: ${t1_price:,.2f}."
                )
                action = "SELL_SHORT_FUTURES / SHORT"
                conf = f"15m Parabolic Short Squeeze Blow-Off Rejection (RVOL {rvol:.1f}x)"

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type="CRYPTO_LIQUIDATION_FLUSH",
                stage="IGNITED",
                symbol=clean_sym,
                exchange="CRYPTO",
                segment="CRYPTO",
                time_horizon="INTRADAY",
                eta_label="24h Rolling",
                direction=direction,
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1_price,
                stop_loss=sl_price,
                confidence=int(liq_metrics.get("conviction", 92)),
                created_at=now_iso,
                is_live=True,
                environment="LIVE",
                market_status="LIVE",
                metrics={
                    "change_pct": chg_pct,
                    "segment": "CRYPTO",
                    "rvol": rvol,
                    "atr_14": liq_metrics.get("atr_14", 0.0),
                    "setup_confluence": conf,
                },
                actionable_plan={
                    "action": action,
                    "segment": "CRYPTO",
                    "contract": f"CRYPTO:{clean_sym}",
                    "entry_range": entry_range,
                    "stop_loss": f"${sl_price:,.2f}",
                    "target": f"${t1_price:,.2f}",
                    "target_2": f"${t2_price:,.2f}",
                    "target_3": f"${t3_price:,.2f}",
                    "runner": f"${t3_price:,.2f}",
                    "risk_reward": rr_str,
                    "when_to_buy": "Enter on flush reclaim wick confirmation.",
                    "when_to_wait": "Do not chase beyond 0.8% of entry.",
                    "no_chase_boundary": no_chase,
                    "setup_confluence": conf,
                    "profit_rule": profit_rule,
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": direction,
                        "timeframe": "15M",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "target_3": t3_price,
                        "risk_reward": rr_str,
                    },
                },
            )
            found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Liquidation cascade check failed for {clean_sym}: {e}")

    # ── 6. DELTA-NEUTRAL BASIS & FUNDING RATE ARBITRAGE DETECTOR ──
    try:
        f_data = crypto_stream.fetch_futures_metrics(clean_sym)
        fr = float(f_data.get("funding_rate_8h", 0.0) or 0.0)
        ann_fr = round(fr * 3 * 365 * 100, 2)
        mark_p = float(f_data.get("mark_price", 0.0) or ltp)
        basis_pct = round(((mark_p - ltp) / ltp) * 100, 3) if ltp > 0 else 0.0

        if abs(ann_fr) >= 18.0:
            is_pos_carry = ann_fr > 0
            alert_id = generate_alert_id(
                clean_sym,
                "CRYPTO_BASIS_ARBITRAGE",
                variant="carry" if is_pos_carry else "reverse-carry",
            )
            if is_pos_carry:
                headline = f"🌾 CRYPTO BASIS HARVEST: {clean_sym} Cash & Carry ({ann_fr:.1f}% APY)"
                summary = (
                    f"Delta-Neutral Cash & Carry opportunity: Long Spot + Short 1x Perp captures {ann_fr:.1f}% annualized "
                    f"funding yield paid every 8 hours with zero directional risk (Basis spread: {basis_pct:+.2f}%)."
                )
                action = "DELTA_NEUTRAL / CASH_AND_CARRY"
                conf = f"Annualized Perpetual Funding Rate Premium ({ann_fr:.1f}% APY >= 18%)"
            else:
                headline = (
                    f"🌾 CRYPTO BASIS HARVEST: {clean_sym} Reverse Cash & Carry ({ann_fr:.1f}% APY)"
                )
                summary = (
                    f"Delta-Neutral Reverse Cash & Carry opportunity: Borrow/Short Spot + Long 1x Perp captures "
                    f"{abs(ann_fr):.1f}% annualized payments from aggressive short sellers."
                )
                action = "DELTA_NEUTRAL / REVERSE_CASH_AND_CARRY"
                conf = f"Annualized Perpetual Funding Rate Discount ({ann_fr:.1f}% APY <= -18%)"

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type="CRYPTO_BASIS_ARBITRAGE",
                stage="EARLY_WARNING",
                symbol=clean_sym,
                exchange="CRYPTO",
                segment="CRYPTO",
                time_horizon="INTRADAY",
                eta_label="24h Rolling",
                direction="NEUTRAL",
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=ltp,
                stop_loss=0.0,
                confidence=95,
                created_at=now_iso,
                is_live=True,
                environment="LIVE",
                market_status="LIVE",
                metrics={
                    "change_pct": chg_pct,
                    "segment": "CRYPTO",
                    "annualized_funding_yield_pct": ann_fr,
                    "funding_rate_8h_pct": round(fr * 100, 4),
                    "basis_pct": basis_pct,
                    "perp_mark_price": mark_p,
                    "setup_confluence": conf,
                },
                actionable_plan={
                    "action": action,
                    "segment": "CRYPTO",
                    "contract": f"CRYPTO:{clean_sym}",
                    "entry_range": f"${round(ltp * 0.999, 2):,.2f} – ${round(ltp * 1.001, 2):,.2f}",
                    "stop_loss": "N/A (Delta Neutral)",
                    "target": f"Yield: {ann_fr:.1f}% APY",
                    "risk_reward": "Delta-Neutral Arbitrage",
                    "when_to_buy": "Execute simultaneous Buy Spot and Short 1x Perp at mark price.",
                    "when_to_wait": "Ensure maintaining >= 2.5x collateral on futures leg to prevent liquidation during flash rallies.",
                    "no_chase_boundary": round(ltp * 1.005, 2),
                    "setup_confluence": conf,
                    "profit_rule": "Collect funding yield every 8 hours. Unwind when funding returns below 6% APY.",
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "DELTA_NEUTRAL",
                        "timeframe": "SWING_CARRY",
                        "entry_price": ltp,
                        "invalidation_stop": 0.0,
                        "target_1": ltp,
                        "target_2": ltp,
                        "risk_reward": "Delta-Neutral",
                    },
                },
            )
            found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Basis arbitrage check failed for {clean_sym}: {e}")

    # ── 7. DERIBIT IV VS RV VOLATILITY ARBITRAGE DETECTOR ──
    if clean_sym in ("BTCUSDT", "BTC", "ETHUSDT", "ETH"):
        try:
            from market.crypto_options import get_crypto_options_summary

            base_curr = "BTC" if "BTC" in clean_sym else "ETH"
            opt_sum = get_crypto_options_summary(base_curr)
            vol_regime = opt_sum.get("volatility_regime", "")
            vol_spread = float(opt_sum.get("iv_rv_spread_pct", 0.0) or 0.0)
            atm_iv = float(opt_sum.get("atm_implied_volatility_pct", 50.0) or 50.0)
            rv_30d = float(opt_sum.get("realized_volatility_30d_pct", 50.0) or 50.0)

            if vol_regime in ("VOLATILITY_OVERPRICED_IV_RICH", "VOLATILITY_UNDERPRICED_IV_CHEAP"):
                is_iv_rich = vol_regime == "VOLATILITY_OVERPRICED_IV_RICH"
                alert_id = generate_alert_id(
                    clean_sym,
                    "CRYPTO_VOL_ARBITRAGE",
                    variant="iv-rich" if is_iv_rich else "iv-cheap",
                )
                if is_iv_rich:
                    headline = f"🎯 DERIBIT VOL ARBITRAGE: {clean_sym} IV Overpriced (+{vol_spread:.1f}% vs 30d RV)"
                    summary = (
                        f"Implied Volatility (IV: {atm_iv:.1f}%) trades at +{vol_spread:.1f}% premium over 30d Realized Vol "
                        f"(RV: {rv_30d:.1f}%). Statistical edge to sell options premium (Theta harvesting & Credit Spreads)."
                    )
                    action = "SELL_VOLATILITY / CREDIT_SPREADS"
                    conf = f"Deribit ATM IV ({atm_iv:.1f}%) vs 30d RV ({rv_30d:.1f}%) Rich Spread (+{vol_spread:.1f}%)"
                else:
                    headline = f"🎯 DERIBIT VOL ARBITRAGE: {clean_sym} IV Underpriced ({vol_spread:.1f}% vs 30d RV)"
                    summary = (
                        f"Implied Volatility (IV: {atm_iv:.1f}%) trades at {vol_spread:.1f}% discount to 30d Realized Vol "
                        f"(RV: {rv_30d:.1f}%). Options are underpriced, statistical edge to buy options volatility before expansion."
                    )
                    action = "BUY_VOLATILITY / STRADDLES"
                    conf = f"Deribit ATM IV ({atm_iv:.1f}%) vs 30d RV ({rv_30d:.1f}%) Cheap Spread ({vol_spread:.1f}%)"

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="CRYPTO_VOL_ARBITRAGE",
                    stage="EARLY_WARNING",
                    symbol=clean_sym,
                    exchange="CRYPTO",
                    segment="CRYPTO",
                    time_horizon="INTRADAY",
                    eta_label="24h Rolling",
                    direction="NEUTRAL" if is_iv_rich else "BULLISH",
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=ltp,
                    target_level=ltp,
                    stop_loss=0.0,
                    confidence=88,
                    created_at=now_iso,
                    is_live=True,
                    environment="LIVE",
                    market_status="LIVE",
                    metrics={
                        "change_pct": chg_pct,
                        "segment": "CRYPTO",
                        "atm_iv": atm_iv,
                        "rv_30d": rv_30d,
                        "iv_rv_spread": vol_spread,
                        "volatility_regime": vol_regime,
                        "setup_confluence": conf,
                    },
                    actionable_plan={
                        "action": action,
                        "segment": "CRYPTO",
                        "contract": f"CRYPTO:{clean_sym}",
                        "entry_range": f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}",
                        "stop_loss": "N/A (Options Volatility Spread)",
                        "target": "Vega / Theta Convergence",
                        "risk_reward": "Volatility Arbitrage",
                        "when_to_buy": "Execute defined-risk options spreads on Deribit or Delta Exchange.",
                        "when_to_wait": "Do not trade unhedged naked short gamma.",
                        "no_chase_boundary": round(ltp * 1.01, 2),
                        "setup_confluence": conf,
                        "profit_rule": "Close spread when IV vs RV spread normalizes within +/- 4%.",
                        "trade_plan": {
                            "symbol": clean_sym,
                            "direction": "VOLATILITY",
                            "timeframe": "SWING_OPTIONS",
                            "entry_price": ltp,
                            "invalidation_stop": 0.0,
                            "target_1": ltp,
                            "target_2": ltp,
                            "risk_reward": "Vol-Arbitrage",
                        },
                    },
                )
                found.append(alert)
        except Exception as e:
            logger.debug(f"[CryptoDetector] Volatility arbitrage check failed for {clean_sym}: {e}")

    return found


def detect_crypto_signals(universe: Optional[list[str]] = None) -> list[AutoAlert]:
    """
    24x7 Real-Time Autonomous Crypto Market Alert Scanner across provided universe.
    """
    targets = universe or DEFAULT_CRYPTO
    found: list[AutoAlert] = []
    for sym in targets:
        alerts = detect_single_crypto_symbol(sym)
        found.extend(alerts)
    return found
