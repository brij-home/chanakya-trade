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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

    return None


def _fetch_locomotive_polarization(ad_ratio: Optional[float]) -> tuple[bool, str]:
    """
    Checks if top 3 NIFTY heavyweights (HDFCBANK, RELIANCE, ICICIBANK) are artificially
    holding up the index while broader market breadth is collapsing (A/D < 0.85).
    """
    if ad_ratio is None or ad_ratio >= 0.85:
        return False, ""
    try:
        from market.quotes import get_quote

        quotes = get_quote(["NSE:HDFCBANK", "NSE:RELIANCE", "NSE:ICICIBANK"])
        if not quotes:
            return False, ""
        changes = []
        for sym in ("NSE:HDFCBANK", "NSE:RELIANCE", "NSE:ICICIBANK"):
            q = quotes.get(sym)
            if q:
                chg = float(getattr(q, "change_pct", 0.0) or getattr(q, "change", 0.0) or 0.0)
                changes.append(chg)
        if len(changes) >= 2:
            avg_chg = sum(changes) / len(changes)
            if avg_chg > 0.10:
                detail = (
                    f"Locomotive Trap: Heavyweights (HDFC/RELIANCE/ICICI) avg {avg_chg:+.2f}%% "
                    f"masking broad market liquidation (A/D {ad_ratio:.2f})."
                )
                return True, detail
    except Exception as exc:
        logger.debug("[MarketRegimeGate] Locomotive check error: %s", exc)
    return False, ""


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
    is_loco, loco_detail = _fetch_locomotive_polarization(ad_ratio)

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
