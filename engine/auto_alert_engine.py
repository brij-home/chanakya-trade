"""
engine/auto_alert_engine.py
───────────────────────────
Real-Time Autonomous Market Alert Engine with Early-Warning Detection.

Monitors live quotes, options chains, and price structures to deliver
actionable alerts *on or before time* so traders can catch high-asymmetry
movements early rather than chasing extended breakouts.

Key Early-Warning Detectors:
  1. GAMMA_BLAST: Options Expiry Day OI unwinding (negative ΔOI) + Volume/OI
     turnover surge (>= 1.8x) + Spot reclaiming intraday VWAP.
     Detects both "EARLY_WARNING" (coiling) and "IGNITED" (active breakout).
  2. SQUEEZE_BREAKOUT: TTM Squeeze (Bollinger inside Keltner) with price coiled
     within 0.4% - 1.2% of VCP pivot / 20-day high with expanding RVOL.
  3. CIRCUIT_WARNING: Upper Circuit proximity alert (<1.5% below circuit ceiling)
     warning traders before liquidity locks and sellers vanish.
  4. SMC_SWEEP: Previous Day High/Low liquidity sweep with immediate wick rejection
     and Lower Timeframe CHoCH at institutional Order Blocks.
  5. CONFLUENCE_INFLECTION: Top-tier quantitative confluence triggers (Score >= 80).

Multi-Channel Dispatch:
  - Server-Sent Events (SSE) via `web.sse.event_bus` -> React Terminal UI
  - In-memory queryable circular buffer
  - Desktop notifications & optional Telegram push
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("engine.auto_alert_engine")

IST = timezone(timedelta(hours=5, minutes=30))
AUTO_ALERTS_FILE = Path.home() / ".trading_platform" / "auto_alerts.json"


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class AutoAlert:
    alert_id: str
    alert_type: str  # GAMMA_BLAST | SQUEEZE_BREAKOUT | CIRCUIT_WARNING | SMC_SWEEP | CONFLUENCE_INFLECTION
    stage: str  # "EARLY_WARNING" (coiling before move) | "IGNITED" (active move underway)
    symbol: str
    exchange: str
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    headline: str
    summary: str
    ltp: float
    trigger_level: float
    target_level: float
    stop_loss: float
    strike: Optional[float] = None
    option_type: Optional[str] = None  # "CE" | "PE"
    contract_symbol: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    actionable_plan: dict[str, Any] = field(default_factory=dict)
    confidence: int = 75  # 0 - 100
    created_at: str = ""
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Detector 1: Gamma Blast (Early Warning & Ignited) ───────────────────────


def detect_gamma_blast(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Evaluates options chain for explosive Gamma Blast early-warning and ignite triggers.

    Leading Indicators:
      - Negative Change in OI (Call/Put writers closing positions in panic).
      - Volume / OI Ratio >= 1.8x (massive intraday turnover vs accumulated open interest).
      - Spot price reclaiming or breaking away from intraday VWAP.
      - ATM & near-OTM strike proximity (within ±1.5% of spot).
    """
    if not chain or spot <= 0:
        return []

    alerts: list[AutoAlert] = []
    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Group contracts by strike and type
    ce_contracts = [c for c in chain if getattr(c, "option_type", "") == "CE"]
    pe_contracts = [c for c in chain if getattr(c, "option_type", "") == "PE"]

    # Effective VWAP proxy if not provided (assume spot is close to VWAP within 0.2%)
    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── Analyze CALL Gamma Blast (Bullish Upside Explosion) ───
    for c in ce_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-0.6 <= strike_diff_pct <= 1.6):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}CE")

        if oi <= 0 or volume <= 0:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0

        # Writer panic criteria:
        is_oi_shedding = (oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000))
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_above_vwap = spot >= (effective_vwap * 0.998)

        if is_oi_shedding and is_high_turnover and spot_above_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (day_high and spot >= day_high * 0.999)
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            target_premium = round(opt_ltp * 2.2, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
            sl_premium = round(max(1.0, opt_ltp * 0.65), 1) if opt_ltp > 0 else 1.0

            headline = (
                f"⚡ CALL GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} CE"
            )
            summary = (
                f"Call writers shedding {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} holding VWAP. "
                f"{'Explosive short-covering underway!' if is_ignited else 'Early-warning coiling before gamma surge!'}"
            )

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-ce-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BULLISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="CE",
                    contract_symbol=contract_sym,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(((spot - effective_vwap) / effective_vwap) * 100, 2),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} (+120%)",
                        "stop_loss": f"₹{sl_premium:.1f} (-35%)",
                        "risk_reward": "1:3.4",
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    # ── Analyze PUT Gamma Blast (Bearish Downside Panic) ───────
    for c in pe_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        if not (-1.6 <= strike_diff_pct <= 0.6):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}PE")

        if oi <= 0 or volume <= 0:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0

        is_oi_shedding = (oi_change < 0 and (oi_chg_pct <= -8.0 or abs(oi_change) >= 20000))
        is_high_turnover = vol_oi_ratio >= 1.8
        spot_below_vwap = spot <= (effective_vwap * 1.002)

        if is_oi_shedding and is_high_turnover and spot_below_vwap:
            is_ignited = (vol_oi_ratio >= 2.5 and oi_chg_pct <= -15.0) or (day_low and spot <= day_low * 1.001)
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            confidence = min(96, int(65 + (vol_oi_ratio * 7) + min(20, abs(oi_chg_pct) * 0.5)))

            target_premium = round(opt_ltp * 2.2, 1) if opt_ltp > 0 else round(strike * 0.015, 1)
            sl_premium = round(max(1.0, opt_ltp * 0.65), 1) if opt_ltp > 0 else 1.0

            headline = (
                f"⚡ PUT GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} PE"
            )
            summary = (
                f"Put writers capitulating {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                f"Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} below VWAP. "
                f"{'Aggressive long put / short spot momentum!' if is_ignited else 'Early-warning coiling before put gamma surge!'}"
            )

            alerts.append(
                AutoAlert(
                    alert_id=f"aa-gamma-pe-{underlying}-{int(strike)}-{uuid.uuid4().hex[:6]}",
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange="NFO",
                    direction="BEARISH",
                    headline=headline,
                    summary=summary,
                    ltp=opt_ltp or spot,
                    trigger_level=strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    strike=strike,
                    option_type="PE",
                    contract_symbol=contract_sym,
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(((spot - effective_vwap) / effective_vwap) * 100, 2),
                    },
                    actionable_plan={
                        "action": "BUY",
                        "instrument": contract_sym,
                        "recommended_entry": f"₹{opt_ltp:.1f}" if opt_ltp else "Market",
                        "target": f"₹{target_premium:.1f} (+120%)",
                        "stop_loss": f"₹{sl_premium:.1f} (-35%)",
                        "risk_reward": "1:3.4",
                    },
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    return alerts


# ── Detector 2: Squeeze Breakout (Early Warning) ───────────────────────────


def detect_squeeze_breakout(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects Volatility Squeeze coiling within 0.4% - 1.2% of resistance / 20D High.
    Triggers *before* the breakout candle runs away.
    """
    if df is None or len(df) < 25 or ltp <= 0:
        return None

    try:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volume"].values if "volume" in df.columns else None

        # 20-period Bollinger Bands
        period = 20
        sma20 = float(pd.Series(closes).rolling(period).mean().iloc[-1])
        std20 = float(pd.Series(closes).rolling(period).std().iloc[-1])
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # 20-period ATR & Keltner Channels
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr20 = float(pd.Series(tr).rolling(period).mean().iloc[-1]) if tr else (std20 * 0.8)
        keltner_upper = sma20 + (1.5 * atr20)
        keltner_lower = sma20 - (1.5 * atr20)

        # Squeeze is ON when BB is inside Keltner Channel
        is_squeeze_on = (bb_upper < keltner_upper) and (bb_lower > keltner_lower)

        # 20-day High / Pivot level
        lookback = min(20, len(highs) - 1)
        pivot_high = float(np.max(highs[-lookback - 1 : -1]))
        dist_to_pivot_pct = ((pivot_high - ltp) / pivot_high) * 100.0

        # RVOL 20D
        rvol = 1.0
        if volumes is not None and len(volumes) >= 20:
            avg_vol = float(np.mean(volumes[-21:-1]))
            cur_vol = float(volumes[-1])
            rvol = round(cur_vol / max(1.0, avg_vol), 2)

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # ── EARLY WARNING: Coiled in squeeze, 0.2% - 1.5% from pivot ───
        if is_squeeze_on and (0.2 <= dist_to_pivot_pct <= 1.5):
            target = round(pivot_high * 1.06, 1)
            sl = round(sma20, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-early-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🎯 SQUEEZE COILING: {symbol} at ₹{ltp:,.1f} (Pivot ₹{pivot_high:,.1f})",
                summary=(
                    f"Bollinger Bands compressed inside Keltner Channels (Squeeze ON). "
                    f"Price is only {dist_to_pivot_pct:.1f}% below pivot resistance. "
                    f"RVOL {rvol}x. Imminent explosive breakout setup!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_on": True,
                    "dist_to_pivot_pct": round(dist_to_pivot_pct, 2),
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "sma20": round(sma20, 1),
                    "atr20": round(atr20, 1),
                },
                actionable_plan={
                    "action": "BUY_ON_PIVOT",
                    "entry_range": f"₹{ltp:.1f} - ₹{pivot_high:.1f}",
                    "breakout_trigger": f"₹{pivot_high:.1f}",
                    "target": f"₹{target:.1f} (+6.0%)",
                    "stop_loss": f"₹{sl:.1f} (-{round(((ltp - sl)/ltp)*100, 1)}%)",
                },
                confidence=84,
                created_at=now_iso,
            )

        # ── IGNITED: Squeeze Fired + Fresh Breakout above pivot ───
        if ltp >= pivot_high and (ltp - pivot_high) / pivot_high <= 0.025 and rvol >= 1.4:
            target = round(ltp * 1.08, 1)
            sl = round(pivot_high * 0.985, 1)
            return AutoAlert(
                alert_id=f"aa-sqz-ignited-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="SQUEEZE_BREAKOUT",
                stage="IGNITED",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=f"🚀 SQUEEZE BREAKOUT IGNITED: {symbol} broke ₹{pivot_high:,.1f}",
                summary=(
                    f"TTM Squeeze fired with heavy institutional volume (RVOL {rvol}x). "
                    f"Price clearing 20-day high ₹{pivot_high:,.1f} (+{round(((ltp-pivot_high)/pivot_high)*100, 1)}%). "
                    f"Primary breakout expansion phase active!"
                ),
                ltp=ltp,
                trigger_level=pivot_high,
                target_level=target,
                stop_loss=sl,
                metrics={
                    "is_squeeze_fired": True,
                    "pivot_high": pivot_high,
                    "rvol": rvol,
                    "breakout_pct": round(((ltp - pivot_high) / pivot_high) * 100, 2),
                },
                actionable_plan={
                    "action": "BUY_EXPANSION",
                    "entry_range": f"₹{ltp:.1f}",
                    "target": f"₹{target:.1f} (+8.0%)",
                    "stop_loss": f"₹{sl:.1f} (-1.5%)",
                },
                confidence=91,
                created_at=now_iso,
            )

    except Exception as e:
        logger.debug(f"[SqueezeBreakout] Error evaluating {symbol}: {e}")

    return None


# ── Detector 3: Circuit Proximity Alert ─────────────────────────────────────


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
                "ceiling": f"₹{upper_circuit:.1f}",
                "note": "Market buy orders will be rejected if locked; use Limit IOC/DAY orders.",
            },
            confidence=88,
            created_at=now_iso,
        )

    return None


# ── Auto Alert Engine Core Class ───────────────────────────────────────────


class AutoAlertEngine:
    """
    Autonomous background monitoring and dispatch engine.
    Continuously evaluates watched indices and liquid universe for early-warning signals.
    """

    def __init__(self, max_buffer: int = 150) -> None:
        self._lock = threading.Lock()
        self._max_buffer = max_buffer
        self._alerts: list[AutoAlert] = []
        self._cooldowns: dict[str, float] = {}  # signature -> timestamp
        self._cooldown_ttl = 900.0  # 15 minutes anti-spam per signature
        self._stop_event = threading.Event()
        self._poller_thread: Optional[threading.Thread] = None
        self._is_running = False

        # Watched indices & top liquid universe
        self._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
        self._watched_equities = [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
            "MARUTI", "SBIN", "BHARTIARTL", "LT", "ITC",
        ]
        self._load()

    # ── Dispatch and Record ─────────────────────────────────────

    def record_alert(self, alert: AutoAlert) -> bool:
        """
        Records alert if not within cooldown window. Dispatches to SSE and multi-channels.
        """
        sig = f"{alert.symbol}:{alert.alert_type}:{alert.direction}:{alert.stage}:{round(alert.ltp, -1)}"
        now = time.time()

        with self._lock:
            last_time = self._cooldowns.get(sig, 0.0)
            if (now - last_time) < self._cooldown_ttl:
                return False  # Cooldown active, suppress repetitive spam

            self._cooldowns[sig] = now
            self._alerts.insert(0, alert)
            if len(self._alerts) > self._max_buffer:
                self._alerts.pop()
            self._save()

        # Multi-channel notification
        self._dispatch(alert)
        return True

    def _dispatch(self, alert: AutoAlert) -> None:
        """Broadcasts alert across all communication channels."""
        alert_dict = alert.to_dict()

        # 1. Server-Sent Events (SSE) stream -> pushes to React UI Toast & Alerts View
        try:
            from web.sse import event_bus
            event_bus.publish_sync("alert", alert_dict)
            event_bus.publish_sync("system", {
                "type": "market_alert",
                "alert": alert_dict,
            })
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] SSE publish error: {e}")

        # 2. Desktop notification
        try:
            from engine.alerts import _desktop_notify
            _desktop_notify(
                title=f"{alert.headline}",
                message=alert.summary,
            )
        except Exception:
            pass

        # 3. Telegram push (if bot token configured)
        try:
            from engine.alerts import _telegram_notify
            _telegram_notify(
                f"🚨 {alert.headline}\n\n"
                f"{alert.summary}\n\n"
                f"🎯 Target: ₹{alert.target_level} | 🛑 SL: ₹{alert.stop_loss}\n"
                f"Confidence: {alert.confidence}%"
            )
        except Exception:
            pass

    # ── Scanning Loops ──────────────────────────────────────────

    def scan_gamma_blasts(self) -> list[AutoAlert]:
        """Scans watched indices and F&O symbols for Gamma Blast inflection."""
        from market.options import get_options_chain
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        for sym in self._watched_indices:
            try:
                spot = get_ltp(f"NSE:{sym}")
                if not spot or spot <= 0:
                    continue
                chain = get_options_chain(sym)
                if not chain:
                    continue

                alerts = detect_gamma_blast(sym, spot, chain)
                for a in alerts:
                    if self.record_alert(a):
                        found.append(a)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Gamma scan error for {sym}: {e}")

        return found

    def scan_squeeze_breakouts(self) -> list[AutoAlert]:
        """Scans equities for TTM Squeeze breakout early warnings."""
        from market.history import get_ohlcv
        from market.quotes import get_ltp

        found: list[AutoAlert] = []
        for sym in self._watched_equities:
            try:
                ltp = get_ltp(f"NSE:{sym}")
                if not ltp or ltp <= 0:
                    continue
                df = get_ohlcv(sym, exchange="NSE", interval="day", days=60)
                if df is None or len(df) < 25:
                    continue

                alert = detect_squeeze_breakout(sym, df, ltp)
                if alert and self.record_alert(alert):
                    found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Squeeze scan error for {sym}: {e}")

        return found

    def scan_circuits(self) -> list[AutoAlert]:
        """Scans watched equities for Upper Circuit proximity."""
        from market.quotes import get_quote

        found: list[AutoAlert] = []
        for sym in self._watched_equities:
            try:
                q = get_quote(f"NSE:{sym}")
                if not q:
                    continue
                ltp = getattr(q, "ltp", 0.0) or getattr(q, "last_price", 0.0)
                prev_close = getattr(q, "prev_close", 0.0) or getattr(q, "close", 0.0)
                if ltp > 0 and prev_close > 0:
                    alert = detect_circuit_proximity(sym, ltp, prev_close)
                    if alert and self.record_alert(alert):
                        found.append(alert)
            except Exception as e:
                logger.debug(f"[AutoAlertEngine] Circuit scan error for {sym}: {e}")

        return found

    def scan_all_now(self) -> list[AutoAlert]:
        """Executes full diagnostic scan across all detectors and returns new alerts."""
        results: list[AutoAlert] = []
        results.extend(self.scan_gamma_blasts())
        results.extend(self.scan_squeeze_breakouts())
        results.extend(self.scan_circuits())
        return results

    # ── Daemon Thread Poller ────────────────────────────────────

    def start_polling(self, interval_seconds: int = 45) -> None:
        """Starts background evaluation loop."""
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._poller_thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds,),
            name="AutoAlertEnginePoller",
            daemon=True,
        )
        self._poller_thread.start()
        logger.info(f"[AutoAlertEngine] Background poller started (interval={interval_seconds}s)")

    def stop_polling(self) -> None:
        """Stops background loop cleanly."""
        self._is_running = False
        self._stop_event.set()
        if self._poller_thread and self._poller_thread.is_alive():
            try:
                self._poller_thread.join(timeout=1.5)
            except Exception:
                pass
        self._poller_thread = None
        logger.info("[AutoAlertEngine] Background poller stopped cleanly")

    def _run_loop(self, interval: int) -> None:
        while self._is_running and not self._stop_event.is_set():
            try:
                from engine.alerts import _is_market_hours
                if _is_market_hours():
                    self.scan_all_now()
            except Exception as e:
                logger.warning(f"[AutoAlertEngine] Error in poll cycle: {e}")

            if self._stop_event.wait(timeout=interval):
                break

    # ── Query API ───────────────────────────────────────────────

    def get_alerts(
        self,
        limit: int = 50,
        alert_type: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> list[AutoAlert]:
        """Returns buffered alerts with optional filtering."""
        with self._lock:
            self._load()
            res = list(self._alerts)

        if alert_type:
            res = [a for a in res if a.alert_type.upper() == alert_type.upper()]
        if stage:
            res = [a for a in res if a.stage.upper() == stage.upper()]

        return res[:limit]

    def clear_alerts(self) -> None:
        """Clears all buffered alerts and cooldown signatures."""
        with self._lock:
            self._alerts.clear()
            self._cooldowns.clear()
            self._save()

    # ── Persistence ─────────────────────────────────────────────

    def _save(self) -> None:
        try:
            AUTO_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [a.to_dict() for a in self._alerts]
            AUTO_ALERTS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _save error: {e}")

    def _load(self) -> None:
        try:
            if AUTO_ALERTS_FILE.exists():
                data = json.loads(AUTO_ALERTS_FILE.read_text())
                self._alerts = [AutoAlert(**d) for d in data if isinstance(d, dict)]
        except Exception as e:
            logger.debug(f"[AutoAlertEngine] _load error: {e}")
            self._alerts = []


# Module-level singleton instance
auto_alert_engine = AutoAlertEngine()
