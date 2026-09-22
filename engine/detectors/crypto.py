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
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.crypto")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


def detect_single_crypto_symbol(sym: str) -> list[AutoAlert]:
    """Scans a single crypto symbol for Squeeze, SMC Momentum, and Options Volatility."""
    from market.crypto_stream import crypto_stream, normalize_crypto_symbol
    from analysis.market_structure import analyze_market_structure
    from engine.alert_preferences import alert_preferences

    if alert_preferences.is_segment_globally_disabled("CRYPTO"):
        return []

    clean_sym = normalize_crypto_symbol(sym).replace("CRYPTO:", "").strip()
    found: list[AutoAlert] = []
    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    date_str = now_dt.strftime("%Y%m%d%H%M")

    q = crypto_stream.get_quote(clean_sym)
    if not q or float(getattr(q, "last_price", 0.0) or 0.0) <= 0:
        return found

    ltp = float(q.last_price)
    chg_pct = float(getattr(q, "change_pct", 0.0) or 0.0)

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
            alert_id = f"crypto-sq-{clean_sym.lower()}-{date_str}"
            squeeze_confidence = 91 if sq_sig == "SHORT_SQUEEZE_IMMINENT" else 90
            risk_usd = round(max(0.5, ltp * 0.018), 2)  # 1.8% structural risk stop

            if is_bullish:
                sl_price = round(ltp - risk_usd, 2)
                t1_price = round(ltp + 2.2 * risk_usd, 2)
                t2_price = round(ltp + 4.0 * risk_usd, 2)
                headline = f"🪙 CRYPTO SQUEEZE: {clean_sym} Short-Squeeze Imminent @ ${ltp:,.2f}"
                summary = (
                    f"Heavily short-crowded funding (8h FR: {fr*100:.4f}%). "
                    f"Extreme negative leverage positioning primed for upward cascade. Target: ${t1_price:,.2f}."
                )
                action = "BUY_SPOT / LONG"
                conf = "Binance Futures Short-Crowded Funding Imbalance (FR <= -0.02%)"
            else:
                sl_price = round(ltp + risk_usd, 2)
                t1_price = round(ltp - 2.2 * risk_usd, 2)
                t2_price = round(ltp - 4.0 * risk_usd, 2)
                headline = f"🪙 CRYPTO SQUEEZE: {clean_sym} Long-Flush Liquidation Risk @ ${ltp:,.2f}"
                summary = (
                    f"Overheated long leverage (8h FR: +{fr*100:.4f}%). "
                    f"Vulnerable to cascading long liquidations. Downside target: ${t1_price:,.2f}."
                )
                action = "SELL_SHORT_FUTURES / SHORT"
                conf = "Binance Futures Long-Overheated Leverage Imbalance (FR >= +0.04%)"

            rr_ratio = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
            rr_str = f"1:{rr_ratio}"

            alert = AutoAlert(
                alert_id=alert_id,
                alert_type=alert_type,
                stage="IGNITED" if abs(chg_pct) >= 1.5 else "EARLY_WARNING",
                symbol=clean_sym,
                exchange="CRYPTO",
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
                    "entry_range": f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}",
                    "stop_loss": f"${sl_price:,.2f}",
                    "target": f"${t1_price:,.2f}",
                    "target_2": f"${t2_price:,.2f}",
                    "risk_reward": rr_str,
                    "when_to_buy": "Enter on order book spread with defined risk below invalidation SL.",
                    "when_to_wait": "Do not chase if price extends > 0.8% beyond entry.",
                    "no_chase_boundary": round(ltp * 1.008, 2) if is_bullish else round(ltp * 0.992, 2),
                    "setup_confluence": conf,
                    "profit_rule": "Scale 50% at T1, trail remaining on 20-EMA / break-even.",
                    "trade_plan": {
                        "symbol": clean_sym,
                        "direction": "LONG" if is_bullish else "SHORT",
                        "timeframe": "15M",
                        "entry_price": ltp,
                        "invalidation_stop": sl_price,
                        "target_1": t1_price,
                        "target_2": t2_price,
                        "risk_reward": rr_str,
                    },
                },
            )
            found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] Squeeze check failed for {clean_sym}: {e}")

    # ── 2. SMC MOMENTUM DETECTOR: Order Block Reclaim & CHoCH Reversal ──
    try:
        df = crypto_stream.get_klines(clean_sym, interval="15m", limit=120)
        if not df.empty and len(df) >= 30:
            smc = analyze_market_structure(symbol=clean_sym, df=df, exchange="CRYPTO", timeframe="15m")
            regime = (smc.regime or "").upper()

            if regime == "BULLISH" and smc.active_demand_zones:
                ob = smc.active_demand_zones[0]
                if ob.bottom <= ltp <= (ob.top * 1.025):
                    sl_price = round(ob.bottom * 0.992, 2)
                    risk_usd = ltp - sl_price
                    if 0 < risk_usd <= (ltp * 0.045):
                        t1_price = round(ltp + 2.4 * risk_usd, 2)
                        t2_price = round(ltp + 4.2 * risk_usd, 2)
                        smc_stage = "IGNITED" if ltp > ob.top else "EARLY_WARNING"
                        smc_confidence = 91 if smc_stage == "IGNITED" else 85
                        alert_id = f"crypto-smc-{clean_sym.lower()}-{date_str}"
                        headline = f"⚡ CRYPTO SMC ALPHA: {clean_sym} Demand Order Block Reclaim @ ${ltp:,.2f}"
                        summary = (
                            f"Smart Money structural reclaim at 15m Demand OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                            f"Bullish structure confirmed. Upside target: ${t1_price:,.2f}."
                        )
                        conf = f"15m Bullish Regime + Unmitigated Demand OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"
                        rr_calc = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
                        rr_str = f"1:{rr_calc}"

                        alert = AutoAlert(
                            alert_id=alert_id,
                            alert_type="CRYPTO_MOMENTUM",
                            stage=smc_stage,
                            symbol=clean_sym,
                            exchange="CRYPTO",
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
                                "entry_range": f"${round(ob.bottom, 2):,.2f} – ${round(ob.top * 1.005, 2):,.2f}",
                                "stop_loss": f"${sl_price:,.2f}",
                                "target": f"${t1_price:,.2f}",
                                "target_2": f"${t2_price:,.2f}",
                                "risk_reward": rr_str,
                                "when_to_buy": "Enter on order block retest or momentum breakout above OB top.",
                                "when_to_wait": f"Do not chase above ${round(ob.top * 1.012, 2):,.2f}.",
                                "no_chase_boundary": round(ob.top * 1.012, 2),
                                "setup_confluence": conf,
                                "profit_rule": "Scale 50% at T1, trail remaining to breakeven.",
                                "trade_plan": {
                                    "symbol": clean_sym,
                                    "direction": "LONG",
                                    "timeframe": "15M",
                                    "entry_price": ltp,
                                    "invalidation_stop": sl_price,
                                    "target_1": t1_price,
                                    "target_2": t2_price,
                                    "risk_reward": rr_str,
                                },
                            },
                        )
                        found.append(alert)

            elif regime == "BEARISH" and smc.active_supply_zones:
                ob = smc.active_supply_zones[0]
                if (ob.bottom * 0.975) <= ltp <= ob.top:
                    sl_price = round(ob.top * 1.008, 2)
                    risk_usd = sl_price - ltp
                    if 0 < risk_usd <= (ltp * 0.045):
                        t1_price = round(ltp - 2.4 * risk_usd, 2)
                        t2_price = round(ltp - 4.2 * risk_usd, 2)
                        smc_stage = "IGNITED" if ltp < ob.bottom else "EARLY_WARNING"
                        smc_confidence = 91 if smc_stage == "IGNITED" else 85
                        alert_id = f"crypto-smc-{clean_sym.lower()}-{date_str}"
                        headline = f"⚡ CRYPTO SMC BREAKDOWN: {clean_sym} Supply OB Rejection @ ${ltp:,.2f}"
                        summary = (
                            f"Smart Money rejection at 15m Supply OB (${ob.bottom:,.2f} - ${ob.top:,.2f}). "
                            f"Bearish structure confirmed. Downside target: ${t1_price:,.2f}."
                        )
                        conf = f"15m Bearish Regime + Active Supply OB (${ob.bottom:,.1f} - ${ob.top:,.1f})"
                        rr_calc = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
                        rr_str = f"1:{rr_calc}"

                        alert = AutoAlert(
                            alert_id=alert_id,
                            alert_type="CRYPTO_MOMENTUM",
                            stage=smc_stage,
                            symbol=clean_sym,
                            exchange="CRYPTO",
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
                                "entry_range": f"${round(ob.bottom * 0.995, 2):,.2f} – ${round(ob.top, 2):,.2f}",
                                "stop_loss": f"${sl_price:,.2f}",
                                "target": f"${t1_price:,.2f}",
                                "target_2": f"${t2_price:,.2f}",
                                "risk_reward": rr_str,
                                "when_to_buy": "Short on rejection wick from supply OB.",
                                "when_to_wait": f"Do not chase below ${round(ob.bottom * 0.988, 2):,.2f}.",
                                "no_chase_boundary": round(ob.bottom * 0.988, 2),
                                "setup_confluence": conf,
                                "profit_rule": "Scale 50% at T1, trail stop to breakeven.",
                                "trade_plan": {
                                    "symbol": clean_sym,
                                    "direction": "SHORT",
                                    "timeframe": "15M",
                                    "entry_price": ltp,
                                    "invalidation_stop": sl_price,
                                    "target_1": t1_price,
                                    "target_2": t2_price,
                                    "risk_reward": rr_str,
                                },
                            },
                        )
                        found.append(alert)
    except Exception as e:
        logger.debug(f"[CryptoDetector] SMC check failed for {clean_sym}: {e}")

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
                is_bullish = dist_pct < 0
                direction = "BULLISH" if is_bullish else "BEARISH"
                alert_id = f"crypto-opt-{clean_sym.lower()}-{date_str}"
                risk_usd = round(max(1.0, ltp * 0.02), 2)  # 2% defined risk stop

                if is_bullish:
                    sl_price = round(ltp - risk_usd, 2)
                    t1_price = round(max_pain, 2)
                    t2_price = round(max_pain * 1.03, 2)
                    headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Max Pain Magnet at ${max_pain:,.0f}"
                    summary = (
                        f"Spot is {abs(dist_pct):.1f}% below Deribit Max Pain (${max_pain:,.0f}). "
                        f"Options dealer gamma position exerts strong upward gravitational pull into expiry."
                    )
                    action = "BUY_SPOT / LONG"
                else:
                    sl_price = round(ltp + risk_usd, 2)
                    t1_price = round(max_pain, 2)
                    t2_price = round(max_pain * 0.97, 2)
                    headline = f"🌊 DERIBIT OPTIONS GRAVITY: {clean_sym} Overextended Above Max Pain (${max_pain:,.0f})"
                    summary = (
                        f"Spot is +{dist_pct:.1f}% extended above Deribit Max Pain (${max_pain:,.0f}). "
                        f"Dealer gamma pull indicates mean-reversion pull towards ${max_pain:,.0f}."
                    )
                    action = "SELL_SHORT_FUTURES / SHORT"

                conf = (
                    f"Deribit {base_curr} Max Pain Gravitational Magnet (${max_pain:,.0f} | "
                    f"PCR: {pcr_oi:.2f} | {gamma_regime} Net GEX: ${net_gex:+,.0f})"
                )
                rr_calc = round(abs(t1_price - ltp) / max(0.01, abs(ltp - sl_price)), 1)
                rr_str = f"1:{rr_calc}"

                alert = AutoAlert(
                    alert_id=alert_id,
                    alert_type="CRYPTO_VOLATILITY",
                    stage="EARLY_WARNING",
                    symbol=clean_sym,
                    exchange="CRYPTO",
                    direction=direction,
                    headline=headline,
                    summary=summary,
                    ltp=ltp,
                    trigger_level=ltp,
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
                        "entry_range": f"${round(ltp * 0.995, 2):,.2f} – ${round(ltp * 1.005, 2):,.2f}",
                        "stop_loss": f"${sl_price:,.2f}",
                        "target": f"${t1_price:,.2f}",
                        "target_2": f"${t2_price:,.2f}",
                        "risk_reward": rr_str,
                        "when_to_buy": "Execute on structural support with defined risk below SL.",
                        "when_to_wait": "Do not chase if price moves > 1% towards Max Pain without retest.",
                        "no_chase_boundary": round(ltp * 1.01, 2) if is_bullish else round(ltp * 0.99, 2),
                        "setup_confluence": conf,
                        "profit_rule": f"Scale 50% at Max Pain magnet (${max_pain:,.0f}), trail remainder.",
                        "trade_plan": {
                            "symbol": clean_sym,
                            "direction": direction,
                            "timeframe": "SWING",
                            "entry_price": ltp,
                            "invalidation_stop": sl_price,
                            "target_1": t1_price,
                            "target_2": t2_price,
                            "risk_reward": rr_str,
                        },
                    },
                )
                found.append(alert)
        except Exception as e:
            logger.debug(f"[CryptoDetector] Options gravity check failed for {clean_sym}: {e}")

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
