# engine/market_regime_gate.py
# Institutional Decision Gate: EDGELESS CHOP - PRESERVE CAPITAL
#
# VIX < 12.5 AND A/D ratio 0.85-1.15 simultaneously -> market is edgeless.
# Thread-safe 60s TTL cached. Returns UNAVAILABLE when feeds are down.

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_VIX_EDGELESS_THRESHOLD: float = 12.5
_AD_LOW: float = 0.85
_AD_HIGH: float = 1.15
_LOW_VIX_SPREAD_THRESHOLD: float = 13.0

_CACHE_TTL: float = 60.0
_cache_lock = threading.Lock()
_cached_result: Optional["RegimeSnapshot"] = None
_cached_at: float = 0.0


@dataclass
class RegimeSnapshot:
    is_edgeless: bool
    vix: Optional[float]
    ad_ratio: Optional[float]
    vix_status: str
    ad_status: str
    banner: str
    reason: str
    prefer_spreads: bool
    data_quality: str
    evaluated_at: float
    is_locomotive_polarized: bool = False
    locomotive_detail: str = ""
    locomotive_direction: str = ""  # "BULLISH" | "BEARISH" | ""


def _fetch_vix() -> Optional[float]:
    try:
        from market.indices import get_vix

        val = get_vix()
        if val and float(val) > 0:
            return float(val)
    except Exception as exc:
        logger.debug("[MarketRegimeGate] VIX fetch error: %s", exc)
    return None


def _fetch_ad_ratio() -> Optional[float]:
    # 1. Primary: Direct sentiment API (Nifty 500 breadth from NSE / persistent cache)
    try:
        from market.sentiment import get_market_breadth

        mb = get_market_breadth()
        if mb and mb.verdict != "UNAVAILABLE" and getattr(mb, "ad_ratio", 0.0) > 0:
            return float(mb.ad_ratio)
    except Exception as exc:
        logger.debug("[MarketRegimeGate] Breadth sentiment fetch error: %s", exc)

    # 2. Secondary: Macro analysis cache
    try:
        from engine.analysis_cache import analysis_cache

        cached = analysis_cache.get_macro("market_breadth_nifty500")
        if cached and isinstance(cached, dict):
            ad = cached.get("ad_ratio")
            if ad and float(ad) > 0:
                return float(ad)
    except Exception as e_suppressed:
        logger.debug(f"[engine.market_regime_gate] Non-fatal exception suppressed: {e_suppressed}")

    # 3. Tertiary: Fallback to tool registry or active quote
    try:
        from agent.tools import get_tool_registry

        registry = get_tool_registry()
        if registry:
            result = registry.execute("get_market_breadth", {})
            if isinstance(result, dict):
                ad = result.get("ad_ratio") or result.get("advance_decline_ratio")
                if ad is not None:
                    return float(ad)
    except Exception as e_suppressed:
        logger.debug(f"[engine.market_regime_gate] Non-fatal exception suppressed: {e_suppressed}")

    try:
        from market.quotes import get_quote

        q = get_quote("NSE:NIFTY")
        if isinstance(q, dict):
            q_obj = q.get("NSE:NIFTY") or q.get("NIFTY")
        else:
            q_obj = q
        if q_obj:
            advances = getattr(q_obj, "advances", None) or getattr(q_obj, "advance", None)
            declines = getattr(q_obj, "declines", None) or getattr(q_obj, "decline", None)
            if advances and declines and float(declines) > 0:
                return float(advances) / float(declines)
    except Exception as e_suppressed:
        logger.debug(f"[engine.market_regime_gate] Non-fatal exception suppressed: {e_suppressed}")

    return None


def _fetch_locomotive_polarization(ad_ratio: Optional[float]) -> tuple[bool, str, str]:
    """
    Checks if top 3 NIFTY heavyweights (HDFCBANK, RELIANCE, ICICIBANK) are divergent from
    broader market breadth:
      1. Bullish Locomotive Trap: Heavyweights held green (avg > +0.10%) while A/D < 0.85
         (artificially masking broad market liquidation). Direction: "BULLISH"
      2. Bearish Reverse Locomotive Trap: Heavyweights dumped red (avg < -0.25%) while A/D > 1.25
         (artificially dragging index while broad market accumulates). Direction: "BEARISH"
    """
    if ad_ratio is None or (0.85 <= ad_ratio <= 1.25):
        return False, "", ""
    try:
        from market.quotes import get_quote

        quotes = get_quote(["NSE:HDFCBANK", "NSE:RELIANCE", "NSE:ICICIBANK"])
        if not quotes:
            return False, "", ""
        changes = []
        for sym in ("NSE:HDFCBANK", "NSE:RELIANCE", "NSE:ICICIBANK"):
            q = quotes.get(sym)
            if q:
                chg = float(getattr(q, "change_pct", 0.0) or getattr(q, "change", 0.0) or 0.0)
                changes.append(chg)
        if len(changes) >= 2:
            avg_chg = sum(changes) / len(changes)
            if ad_ratio < 0.85 and avg_chg > 0.10:
                detail = (
                    f"Locomotive Trap: Heavyweights (HDFC/RELIANCE/ICICI) avg {avg_chg:+.2f}% "
                    f"masking broad market liquidation (A/D {ad_ratio:.2f})."
                )
                return True, detail, "BULLISH"
            elif ad_ratio > 1.25 and avg_chg < -0.25:
                detail = (
                    f"Reverse Locomotive Trap: Heavyweights (HDFC/RELIANCE/ICICI) avg {avg_chg:+.2f}% "
                    f"dragging benchmark while broad market accumulates (A/D {ad_ratio:.2f})."
                )
                return True, detail, "BEARISH"
    except Exception as exc:
        logger.debug("[MarketRegimeGate] Locomotive check error: %s", exc)
    return False, "", ""


def evaluate_market_regime(force_refresh: bool = False) -> RegimeSnapshot:
    global _cached_result, _cached_at
    now = time.time()

    with _cache_lock:
        if not force_refresh and _cached_result is not None and (now - _cached_at) < _CACHE_TTL:
            return _cached_result

    vix = _fetch_vix()
    ad_ratio = _fetch_ad_ratio()

    vix_available = vix is not None
    ad_available = ad_ratio is not None
    if vix_available and ad_available:
        data_quality = "LIVE"
    elif vix_available or ad_available:
        data_quality = "DEGRADED"
    else:
        data_quality = "UNAVAILABLE"

    if not vix_available:
        vix_status = "UNAVAILABLE"
        vix_condition = False
        prefer_spreads = False
    elif vix < _VIX_EDGELESS_THRESHOLD:
        vix_status = "LOW"
        vix_condition = True
        prefer_spreads = True
    elif vix < _LOW_VIX_SPREAD_THRESHOLD:
        vix_status = "LOW"
        vix_condition = False
        prefer_spreads = True
    elif vix < 15.0:
        vix_status = "NORMAL"
        vix_condition = False
        prefer_spreads = False
    elif vix < 20.0:
        vix_status = "ELEVATED"
        vix_condition = False
        prefer_spreads = False
    else:
        vix_status = "HIGH"
        vix_condition = False
        prefer_spreads = False

    if not ad_available:
        ad_status = "UNAVAILABLE"
        ad_condition = False
    elif _AD_LOW <= ad_ratio <= _AD_HIGH:
        ad_status = "NEUTRAL_CHOP"
        ad_condition = True
    elif ad_ratio > _AD_HIGH:
        ad_status = "BULLISH_BREADTH"
        ad_condition = False
    else:
        ad_status = "BEARISH_BREADTH"
        ad_condition = False

    is_edgeless = vix_condition and ad_condition and data_quality != "UNAVAILABLE"
    is_loco, loco_detail, loco_dir = _fetch_locomotive_polarization(ad_ratio)

    vix_str = "VIX %.1f" % vix if vix_available else "VIX UNAVAILABLE"
    ad_str = "A/D %.2f" % ad_ratio if ad_available else "A/D UNAVAILABLE"

    if is_edgeless:
        banner = "EDGELESS CHOP - PRESERVE CAPITAL"
        reason = (
            "Market is in confirmed edgeless chop: %s (< %.1f) + %s (neutral band %.2f-%.2f). "
            "Naked option buyers face maximum theta bleed with zero directional edge. "
            "Institutional action: hold cash, wait for breadth expansion or VIX spike."
            % (vix_str, _VIX_EDGELESS_THRESHOLD, ad_str, _AD_LOW, _AD_HIGH)
        )
    elif is_loco:
        if loco_dir == "BEARISH":
            banner = "REVERSE LOCOMOTIVE POLARIZATION — NAKED PUTS VETOED"
            reason = (
                "%s Top heavyweights artificially dragging benchmark while broad market advances. "
                "Naked index puts suppressed. Squeeze risk is elevated; mandate defined-risk hedges or individual longs."
                % loco_detail
            )
        else:
            banner = "LOCOMOTIVE POLARIZATION DETECTED — NAKED CALLS VETOED"
            reason = (
                "%s Top heavyweights artificially holding benchmark while broad market liquidates. "
                "Naked index calls suppressed. Mandate defined-risk hedges or short setups."
                % loco_detail
            )
    elif prefer_spreads:
        banner = "LOW VIX - USE DEFINED-RISK SPREADS (%s)" % vix_str
        reason = (
            "VIX below %.1f makes naked option buying theta-inefficient. "
            "System auto-configures Bull Call / Bear Put Spreads as primary vehicle. "
            "Market breadth: %s (%s)." % (_LOW_VIX_SPREAD_THRESHOLD, ad_str, ad_status)
        )
    elif data_quality == "UNAVAILABLE":
        banner = "MARKET DATA UNAVAILABLE - TRADE WITH CAUTION"
        reason = "VIX and A/D data feeds are both unavailable. Cannot confirm regime."
    else:
        banner = ""
        reason = (
            "Normal trading conditions: %s (%s), %s (%s). "
            "Directional trades with proper risk controls are appropriate."
            % (vix_str, vix_status, ad_str, ad_status)
        )

    snapshot = RegimeSnapshot(
        is_edgeless=is_edgeless,
        vix=vix,
        ad_ratio=ad_ratio,
        vix_status=vix_status,
        ad_status=ad_status,
        banner=banner,
        reason=reason,
        prefer_spreads=prefer_spreads,
        data_quality=data_quality,
        evaluated_at=now,
        is_locomotive_polarized=is_loco,
        locomotive_detail=loco_detail,
        locomotive_direction=loco_dir,
    )

    with _cache_lock:
        _cached_result = snapshot
        _cached_at = now

    if is_edgeless:
        logger.warning("[MarketRegimeGate] EDGELESS CHOP DETECTED: %s", reason)
    elif prefer_spreads:
        logger.info("[MarketRegimeGate] Low VIX regime: %s", banner)

    return snapshot


def get_cached_regime() -> Optional[RegimeSnapshot]:
    with _cache_lock:
        return _cached_result


def clear_cached_regime() -> None:
    """Clear cached market regime snapshot for hermetic test isolation."""
    global _cached_result, _cached_at
    with _cache_lock:
        _cached_result = None
        _cached_at = 0.0


def build_spread_recommendation(
    underlying: str,
    spot: float,
    direction: str,
    iv: float = 0.14,
    dte: int = 7,
) -> dict:
    try:
        from engine.defined_risk_spreads import build_defined_risk_spread

        strategy = "BULL_CALL_SPREAD" if direction == "BULLISH" else "BEAR_PUT_SPREAD"
        spread = build_defined_risk_spread(
            underlying=underlying,
            spot_price=spot,
            strategy=strategy,
            iv=iv,
            dte=dte,
        )
        opt_type = "CE" if direction == "BULLISH" else "PE"
        return {
            "primary_strategy": strategy,
            "spread_detail": spread.to_dict(),
            "naked_alternative": "Buy ATM %s (higher risk, higher reward)" % opt_type,
            "mandate_reason": (
                "India VIX < %.1f - naked option buyers face negative EV from "
                "theta decay. Defined-risk spread recommended as primary. Choose naked only if "
                "you expect strong momentum continuation." % _LOW_VIX_SPREAD_THRESHOLD
            ),
        }
    except Exception as exc:
        logger.debug("[MarketRegimeGate] Spread build error for %s: %s", underlying, exc)
        opt_type = "CE" if direction == "BULLISH" else "PE"
        strategy = "BULL_CALL_SPREAD" if direction == "BULLISH" else "BEAR_PUT_SPREAD"
        return {
            "primary_strategy": strategy,
            "naked_alternative": "Buy ATM %s" % opt_type,
            "mandate_reason": "Low VIX regime - prefer defined-risk spread.",
        }


# ─── Gate 31: Institutional Index Tide & Regime Alignment Gate ───────────────


@dataclass
class IndexTideGateResult:
    """Institutional evaluation of equity setup alignment against benchmark index tide."""

    is_vetoed: bool = False
    veto_reason: Optional[str] = None
    benchmark_symbol: str = "NIFTY"
    benchmark_ltp: float = 0.0
    benchmark_vwap: float = 0.0
    benchmark_change_pct: float = 0.0
    is_decoupled: bool = False


_index_tide_lock = threading.Lock()
_index_tide_cache: dict[str, tuple[float, Any]] = {}
_INDEX_TIDE_TTL: float = 30.0

BANKING_SYMBOLS = frozenset(
    {
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "AXISBANK",
        "KOTAKBANK",
        "BANKBARODA",
        "PNB",
        "FEDERALBNK",
        "INDUSINDBK",
        "AUBANK",
        "BANDHANBNK",
        "IDFCFIRSTB",
        "CANBK",
    }
)

INDEX_EXCLUSIONS = frozenset(
    {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
        "NIFTYNXT50",
    }
)


def clear_index_tide_cache() -> None:
    """Clear benchmark index tide cache. Used in conftest test isolation."""
    global _index_tide_cache
    with _index_tide_lock:
        _index_tide_cache.clear()


def evaluate_index_tide_gate(
    symbol: str,
    direction: str,
    ltp: float = 0.0,
    rvol: float = 1.0,
    change_pct: float = 0.0,
    quotes_map: Optional[dict[str, Any]] = None,
) -> IndexTideGateResult:
    """
    Gate 31: Institutional Index Tide & Regime Alignment Gate.
    Vetoes non-decoupled equity setups that fight directly against the prevailing benchmark tide:
      1. Vetoes BEARISH equity breakdowns when the benchmark index is advancing above VWAP.
      2. Vetoes BULLISH equity breakouts when the benchmark index is liquidating below VWAP.

    Exemption (Invariant 10/22): Stocks with explosive volume (RVOL >= 2.5x) or major price moves
    (|change_pct| >= 2.5%) are recognized as genuine decoupled movers and exempted from index tide vetoes.
    """
    from engine.alert_identity import canonical_alert_symbol

    clean_sym = canonical_alert_symbol(symbol)
    if clean_sym in INDEX_EXCLUSIONS:
        return IndexTideGateResult()

    # Outlier Decoupling Exemption: Explosive volume or major catalyst breakout
    is_decoupled = (rvol >= 2.50) or (abs(change_pct) >= 2.50)
    if is_decoupled:
        return IndexTideGateResult(is_decoupled=True)

    # Determine primary benchmark
    bench_sym = "BANKNIFTY" if clean_sym in BANKING_SYMBOLS else "NIFTY"
    canonical_dir = direction.upper()

    now = time.time()
    bench_q = None

    # Check caller-provided quotes map first
    if quotes_map:
        bench_q = (
            quotes_map.get(bench_sym)
            or quotes_map.get(f"NSE:{bench_sym}")
            or quotes_map.get(f"NSE:{bench_sym}50-INDEX")
            or quotes_map.get(f"NSE:{bench_sym}-INDEX")
            or quotes_map.get("NSE:NIFTY 50")
            or quotes_map.get("NSE:NIFTY BANK")
        )

    # Fast in-memory cache lookup
    if bench_q is None:
        with _index_tide_lock:
            cached_item = _index_tide_cache.get(bench_sym)
            if cached_item and (now - cached_item[0] < _INDEX_TIDE_TTL):
                bench_q = cached_item[1]

    # Live query fallback
    if bench_q is None:
        try:
            from market.quotes import get_quote

            query_sym = "NSE:NIFTYBANK-INDEX" if bench_sym == "BANKNIFTY" else "NSE:NIFTY50-INDEX"
            q_res = get_quote([query_sym])
            bench_q = q_res.get(query_sym) or next(iter(q_res.values()), None)
            if bench_q:
                with _index_tide_lock:
                    _index_tide_cache[bench_sym] = (now, bench_q)
        except Exception as e_quote:
            logger.debug(f"[IndexTideGate] Benchmark quote query error for {bench_sym}: {e_quote}")

    if not bench_q:
        return IndexTideGateResult(benchmark_symbol=bench_sym)

    b_ltp = float(getattr(bench_q, "last_price", 0.0) or getattr(bench_q, "ltp", 0.0) or 0.0)
    b_vwap = float(getattr(bench_q, "vwap", 0.0) or 0.0)
    b_chg = float(getattr(bench_q, "change_pct", 0.0) or getattr(bench_q, "pchange", 0.0) or 0.0)

    if b_ltp <= 0:
        return IndexTideGateResult(benchmark_symbol=bench_sym)

    # 1. BEARISH Setup into Bullish Benchmark Tide Check
    if canonical_dir in ("BEARISH", "SELL", "SHORT"):
        # Benchmark is advancing with positive change and holding firmly above VWAP
        is_bench_bullish = (b_chg >= 0.25) and (b_vwap > 0 and b_ltp >= b_vwap * 1.0010)
        if is_bench_bullish:
            reason = (
                f"Index Tide Veto: Benchmark {bench_sym} is advancing (+{b_chg:.2f}%, above VWAP ₹{b_vwap:,.1f}); "
                f"non-decoupled breakdown on {clean_sym} (RVOL {rvol:.1f}x) suppressed to avoid beta-drag stopout."
            )
            return IndexTideGateResult(
                is_vetoed=True,
                veto_reason=reason,
                benchmark_symbol=bench_sym,
                benchmark_ltp=b_ltp,
                benchmark_vwap=b_vwap,
                benchmark_change_pct=b_chg,
                is_decoupled=False,
            )

    # 2. BULLISH Setup into Bearish Benchmark Tide Check
    elif canonical_dir in ("BULLISH", "BUY", "LONG"):
        # Benchmark is liquidating with negative change and trading firmly below VWAP
        is_bench_bearish = (b_chg <= -0.35) and (b_vwap > 0 and b_ltp <= b_vwap * 0.9990)
        if is_bench_bearish:
            reason = (
                f"Index Tide Veto: Benchmark {bench_sym} is falling ({b_chg:.2f}%, below VWAP ₹{b_vwap:,.1f}); "
                f"non-decoupled breakout on {clean_sym} (RVOL {rvol:.1f}x) suppressed to avoid beta-drag stopout."
            )
            return IndexTideGateResult(
                is_vetoed=True,
                veto_reason=reason,
                benchmark_symbol=bench_sym,
                benchmark_ltp=b_ltp,
                benchmark_vwap=b_vwap,
                benchmark_change_pct=b_chg,
                is_decoupled=False,
            )

    return IndexTideGateResult(
        is_vetoed=False,
        benchmark_symbol=bench_sym,
        benchmark_ltp=b_ltp,
        benchmark_vwap=b_vwap,
        benchmark_change_pct=b_chg,
        is_decoupled=is_decoupled,
    )
