"""
engine/detection_context.py
────────────────────────────
Standardized Detection Context and Base Detector Protocol for ChanakyaTrade.

Institutional Intent:
1. Separation of Concerns: Decouples market data retrieval (REST/WebSocket/Cache)
   from detection mathematics and pattern recognition.
2. Functional Purity: Detectors receive an immutable DetectionContext and return
   AutoAlert instances without performing hidden network calls or side effects.
3. Deterministic Testing: Any detector can be verified in isolation with synthetic
   candles and quotes without monkeypatching external brokers.
4. Concurrency: Stateless detectors can be executed across thread pools safely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import pandas as pd

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol
from engine.alert_model import AutoAlert

logger = logging.getLogger("chanakya.detectors.context")


@dataclass(frozen=True)
class DetectionContext:
    """
    Strongly-typed, immutable market snapshot provided to quantitative detectors.
    """

    symbol: str
    canonical_symbol: str
    exchange: str = "NSE"
    segment: str = "EQUITY"
    ltp: float = 0.0
    prev_close: Optional[float] = None
    vwap: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    candles_5m: Optional[pd.DataFrame] = None
    candles_15m: Optional[pd.DataFrame] = None
    candles_daily: Optional[pd.DataFrame] = None
    option_chain: Optional[list[dict[str, Any]]] = None
    rvol: Optional[float] = None
    vix: Optional[float] = None
    regime: Optional[Any] = None
    session_status: Optional[dict[str, bool]] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(IST))
    environment: str = "LIVE"
    extra_metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_index(self) -> bool:
        """Determines if the canonical symbol represents a benchmark index."""
        from engine.option_resolver import is_index_symbol

        return is_index_symbol(self.canonical_symbol)

    @property
    def day_change_pct(self) -> float:
        """Percentage price change against previous session close."""
        if self.prev_close and self.prev_close > 0 and self.ltp > 0:
            return round(((self.ltp - self.prev_close) / self.prev_close) * 100.0, 2)
        return 0.0

    @property
    def bid_ask_spread_pct(self) -> Optional[float]:
        """Calculates bid-ask spread percentage if bid & ask are in extra_metrics."""
        bid = self.extra_metrics.get("bid")
        ask = self.extra_metrics.get("ask")
        if bid is not None and ask is not None and self.ltp > 0:
            try:
                b, a = float(bid), float(ask)
                if a >= b and b > 0:
                    return round(((a - b) / self.ltp) * 100.0, 2)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def liquidity_warning(self) -> Optional[str]:
        """Flags illiquid options or wide spreads to enforce limit orders."""
        spread = self.bid_ask_spread_pct
        if spread is not None and spread > 3.0:
            return f"⚠️ WIDE BID-ASK SPREAD ({spread:.1f}%) — High slippage risk! Use strict limit orders."
        return None

    def compute_atr(self, period: int = 14) -> Optional[float]:
        """Computes Average True Range (ATR) across available candles."""
        df = self.candles_5m if self.candles_5m is not None else self.candles_daily
        if df is None or len(df) < period:
            return None
        try:
            req_cols = {"high", "low", "close"}
            cols_lower = {str(c).lower(): c for c in df.columns}
            if not req_cols.issubset(set(cols_lower.keys())):
                return None
            h = df[cols_lower["high"]]
            l = df[cols_lower["low"]]
            c = df[cols_lower["close"]]
            prev_c = c.shift(1)
            tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
            atr_series = tr.rolling(window=period).mean()
            val = float(atr_series.iloc[-1])
            return round(val, 2) if not pd.isna(val) and val > 0 else None
        except Exception:
            return None

    def get_dynamic_stop_loss(self, direction: str = "BULLISH", multiplier: float = 1.5) -> float:
        """
        Dynamically scales stop-loss based on local ATR(14) and India VIX regime.
        Prevents static stops from being whipped out by volatility noise.
        """
        atr_val = self.compute_atr()
        vix_val = self.vix or 13.5
        vix_mult = max(0.8, min(1.6, 1.0 + ((vix_val - 13.0) / 30.0)))

        if atr_val and atr_val > 0:
            stop_dist = round(atr_val * multiplier * vix_mult, 2)
        else:
            # Fallback to standard 1.2% buffer
            stop_dist = round(max(0.5, self.ltp * 0.012), 2)

        if str(direction).upper() in ("BEARISH", "SHORT", "SELL", "PUT", "PE"):
            return round(self.ltp + stop_dist, 2)
        return round(max(0.05, self.ltp - stop_dist), 2)

    def build_execution_ticket(
        self,
        stop_loss: float,
        target_price: Optional[float] = None,
        direction: str = "BULLISH",
        alert_type: Optional[str] = None,
        capital: float = 100000.0,
        max_risk_pct: float = 1.0,
    ) -> dict[str, Any]:
        """
        Builds a capital-calibrated institutional execution ticket directly from this context.
        """
        from engine.position_sizer import generate_execution_ticket

        return generate_execution_ticket(
            symbol=self.symbol,
            entry_price=self.ltp,
            stop_loss=stop_loss,
            target_price=target_price,
            capital=capital,
            max_risk_pct=max_risk_pct,
            direction=direction,
            alert_type=alert_type,
            is_fno=self.segment in ("NFO", "BFO", "F&O"),
        )


@runtime_checkable
class BaseDetector(Protocol):
    """
    Standard protocol implemented by all institutional detectors.
    """

    detector_slug: str
    detector_name: str
    supported_segments: tuple[str, ...]

    def detect(self, ctx: DetectionContext) -> list[AutoAlert]:
        """
        Pure detection method. Evaluates pattern against context and returns
        zero or more AutoAlert objects.
        """
        ...


class FunctionalDetectorAdapter:
    """
    Adapts legacy procedural detector functions into the BaseDetector protocol.
    """

    def __init__(
        self,
        slug: str,
        name: str,
        supported_segments: tuple[str, ...],
        func: Callable[..., Any],
    ) -> None:
        self.detector_slug = slug
        self.detector_name = name
        self.supported_segments = supported_segments
        self._func = func

    def detect(self, ctx: DetectionContext) -> list[AutoAlert]:
        try:
            res = self._func(ctx)
            if res is None:
                return []
            if isinstance(res, list):
                return [a for a in res if isinstance(a, AutoAlert)]
            if isinstance(res, AutoAlert):
                return [res]
            return []
        except Exception as e:
            logger.debug(f"[{self.detector_slug}] Execution error for {ctx.canonical_symbol}: {e}")
            return []


class DetectorRegistry:
    """
    Centralized registry of institutional detectors.
    """

    def __init__(self) -> None:
        self._detectors: dict[str, BaseDetector] = {}

    def register(self, detector: BaseDetector) -> None:
        """Registers a detector instance."""
        self._detectors[detector.detector_slug] = detector
        logger.debug(f"[DetectorRegistry] Registered detector: {detector.detector_slug}")

    def unregister(self, slug: str) -> None:
        """Removes a detector from the registry."""
        self._detectors.pop(slug, None)

    def list_registered_slugs(self) -> list[str]:
        """Returns sorted list of all registered detector slugs."""
        return sorted(self._detectors.keys())

    def get_detectors(self, segment: Optional[str] = None) -> list[BaseDetector]:
        """Returns all detectors, optionally filtered by market segment."""
        if segment is None:
            return list(self._detectors.values())
        seg = segment.upper()
        return [d for d in self._detectors.values() if seg in d.supported_segments or "ALL" in d.supported_segments]

    def evaluate_all(self, ctx: DetectionContext) -> list[AutoAlert]:
        """
        Executes all eligible registered detectors sequentially against the context.
        """
        alerts: list[AutoAlert] = []
        for detector in self.get_detectors():
            try:
                found = detector.detect(ctx)
                if found:
                    alerts.extend(found)
            except Exception as e:
                logger.debug(f"[DetectorRegistry] Error running {detector.detector_slug}: {e}")
        return alerts


# Global singleton registry instance
detector_registry = DetectorRegistry()


def build_detection_context(
    symbol: str,
    *,
    exchange: str = "NSE",
    segment: str = "EQUITY",
    ltp: float = 0.0,
    prev_close: Optional[float] = None,
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    candles_5m: Optional[pd.DataFrame] = None,
    candles_15m: Optional[pd.DataFrame] = None,
    candles_daily: Optional[pd.DataFrame] = None,
    option_chain: Optional[list[dict[str, Any]]] = None,
    rvol: Optional[float] = None,
    vix: Optional[float] = None,
    regime: Optional[Any] = None,
    session_status: Optional[dict[str, bool]] = None,
    timestamp: Optional[datetime] = None,
    environment: str = "LIVE",
    extra_metrics: Optional[dict[str, Any]] = None,
) -> DetectionContext:
    """
    Factory helper to construct a normalized DetectionContext.
    """
    clean_sym = canonical_alert_symbol(symbol)
    ts = timestamp or datetime.now(IST)
    return DetectionContext(
        symbol=symbol,
        canonical_symbol=clean_sym,
        exchange=exchange.upper(),
        segment=segment.upper(),
        ltp=float(ltp),
        prev_close=float(prev_close) if prev_close is not None else None,
        vwap=float(vwap) if vwap is not None else None,
        day_high=float(day_high) if day_high is not None else None,
        day_low=float(day_low) if day_low is not None else None,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        candles_daily=candles_daily,
        option_chain=option_chain,
        rvol=float(rvol) if rvol is not None else None,
        vix=float(vix) if vix is not None else None,
        regime=regime,
        session_status=session_status,
        timestamp=ts,
        environment=environment,
        extra_metrics=extra_metrics or {},
    )


def register_default_detectors() -> None:
    """
    Wraps existing detectors into BaseDetector adapters and registers them
    with the global detector_registry singleton.
    """
    from engine.detectors.circuit import detect_circuit_proximity
    from engine.detectors.orb import detect_opening_range_breakout
    from engine.detectors.squeeze_breakout import detect_squeeze_breakout
    from engine.detectors.gamma_blast import detect_gamma_blast
    from engine.detectors.opening_drive import detect_opening_drive
    from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup
    from engine.detectors.pattern_coiling import detect_learned_pattern_coiling
    from engine.detectors.index_call_setup import detect_index_call_setup
    from engine.detectors.index_put_setup import detect_index_put_setup
    from engine.detectors.commodity import detect_commodity_breakouts
    from engine.detectors.currency import detect_currency_breakouts
    from engine.detectors.crypto import detect_single_crypto_symbol

    def _circuit_adapter(ctx: DetectionContext):
        if ctx.ltp > 0 and ctx.prev_close and ctx.prev_close > 0:
            return detect_circuit_proximity(
                symbol=ctx.symbol,
                ltp=ctx.ltp,
                prev_close=ctx.prev_close,
                high=ctx.day_high,
                exchange=ctx.exchange,
            )
        return None

    def _orb_adapter(ctx: DetectionContext):
        if ctx.candles_5m is not None and len(ctx.candles_5m) >= 3:
            return detect_opening_range_breakout(
                symbol=ctx.symbol,
                df=ctx.candles_5m,
                ltp=ctx.ltp,
                vwap=ctx.vwap,
                exchange=ctx.exchange,
                rvol=ctx.rvol or 1.5,
                ref_time=ctx.timestamp,
            )
        return None

    def _squeeze_adapter(ctx: DetectionContext):
        if ctx.candles_5m is not None and len(ctx.candles_5m) >= 20:
            return detect_squeeze_breakout(
                symbol=ctx.symbol,
                df=ctx.candles_5m,
                ltp=ctx.ltp,
                exchange=ctx.exchange,
                vwap=ctx.vwap,
            )
        return None

    def _gamma_adapter(ctx: DetectionContext):
        if ctx.option_chain:
            return detect_gamma_blast(
                underlying=ctx.canonical_symbol,
                spot=ctx.ltp,
                chain=ctx.option_chain,
                vwap=ctx.vwap,
                day_high=ctx.day_high,
                day_low=ctx.day_low,
            )
        return None

    def _opening_drive_adapter(ctx: DetectionContext):
        if ctx.candles_5m is not None and len(ctx.candles_5m) >= 3:
            return detect_opening_drive(
                symbol=ctx.canonical_symbol,
                df_5m=ctx.candles_5m,
                ltp=ctx.ltp,
                exchange=ctx.exchange,
            )
        return None

    def _dryup_adapter(ctx: DetectionContext):
        df = ctx.candles_daily if ctx.candles_daily is not None else ctx.candles_5m
        if df is not None and len(df) >= 10:
            return detect_pre_inflection_dryup(
                symbol=ctx.canonical_symbol,
                df=df,
                ltp=ctx.ltp,
                exchange=ctx.exchange,
            )
        return None

    def _pattern_coiling_adapter(ctx: DetectionContext):
        if ctx.candles_5m is not None and len(ctx.candles_5m) >= 15:
            return detect_learned_pattern_coiling(
                symbol=ctx.canonical_symbol,
                df=ctx.candles_5m,
                ltp=ctx.ltp,
                exchange=ctx.exchange,
            )
        return None

    def _index_call_adapter(ctx: DetectionContext):
        if ctx.is_index and ctx.option_chain:
            return detect_index_call_setup(
                underlying=ctx.canonical_symbol,
                spot=ctx.ltp,
                chain=ctx.option_chain,
                ohlcv_5m=ctx.candles_5m,
                vwap=ctx.vwap,
            )
        return None

    def _index_put_adapter(ctx: DetectionContext):
        if ctx.is_index and ctx.option_chain:
            return detect_index_put_setup(
                underlying=ctx.canonical_symbol,
                spot=ctx.ltp,
                chain=ctx.option_chain,
                ohlcv_5m=ctx.candles_5m,
                vwap=ctx.vwap,
            )
        return None

    def _commodity_adapter(ctx: DetectionContext):
        if ctx.exchange == "MCX" and ctx.candles_5m is not None:
            return detect_commodity_breakouts(ctx.canonical_symbol, ctx.candles_5m, ctx.ltp)
        return None

    def _currency_adapter(ctx: DetectionContext):
        if ctx.exchange in ("CDS", "CURRENCY") and ctx.candles_5m is not None:
            return detect_currency_breakouts(ctx.canonical_symbol, ctx.candles_5m, ctx.ltp)
        return None

    def _crypto_adapter(ctx: DetectionContext):
        if ctx.exchange in ("CRYPTO", "BINANCE", "DERIBIT"):
            return detect_single_crypto_symbol(
                symbol=ctx.canonical_symbol,
                ltp=ctx.ltp,
                ohlcv_15m=ctx.candles_15m or ctx.candles_5m,
            )
        return None

    adapters = [
        FunctionalDetectorAdapter("circuit_proximity", "Upper Circuit Proximity", ("EQUITY",), _circuit_adapter),
        FunctionalDetectorAdapter("orb", "Opening Range Breakout (15m)", ("EQUITY", "FNO_STOCK", "FNO_INDEX"), _orb_adapter),
        FunctionalDetectorAdapter("squeeze_breakout", "TTM Squeeze Breakout", ("EQUITY", "FNO_STOCK", "FNO_INDEX"), _squeeze_adapter),
        FunctionalDetectorAdapter("gamma_blast", "Options Gamma Blast", ("FNO_INDEX", "FNO_STOCK"), _gamma_adapter),
        FunctionalDetectorAdapter("opening_drive", "Opening Drive Ignition", ("EQUITY", "FNO_STOCK", "FNO_INDEX"), _opening_drive_adapter),
        FunctionalDetectorAdapter("pre_inflection_dryup", "Pre-Inflection Dryup", ("EQUITY", "FNO_STOCK"), _dryup_adapter),
        FunctionalDetectorAdapter("pattern_coiling", "Pattern Coiling", ("EQUITY", "FNO_STOCK"), _pattern_coiling_adapter),
        FunctionalDetectorAdapter("index_call_setup", "Institutional Index Call Setup", ("FNO_INDEX",), _index_call_adapter),
        FunctionalDetectorAdapter("index_put_setup", "Institutional Index Put Setup", ("FNO_INDEX",), _index_put_adapter),
        FunctionalDetectorAdapter("commodity_breakout", "Commodity Momentum Breakout", ("COMMODITY",), _commodity_adapter),
        FunctionalDetectorAdapter("currency_breakout", "Currency Macro Breakout", ("CURRENCY",), _currency_adapter),
        FunctionalDetectorAdapter("crypto_signal", "24x7 Crypto Squeeze & Flow", ("CRYPTO",), _crypto_adapter),
    ]

    for ad in adapters:
        detector_registry.register(ad)

    # Register class-based BaseDetector protocols
    from engine.detectors.order_flow import OrderFlowDivergenceDetector
    detector_registry.register(OrderFlowDivergenceDetector())


# Auto-populate default institutional detectors into registry
register_default_detectors()

