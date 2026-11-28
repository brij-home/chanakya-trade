"""
engine/feature_bus.py
─────────────────────
Single-Pass Shared Feature Bus & Index Constituent Lead-Lag Engine.

Computes technical, compression, volatility, and ATR-normalized extension features
once per (symbol, latest_bar) in RAM so multiple detectors evaluate from a shared
feature vector instead of redundantly recomputing EMAs, RSI, ATR, VWAP, and squeeze metrics.

Also computes read-only heavy-constituent impulse & VWAP breadth for NIFTY / BANKNIFTY
index option timing without emitting cash-equity trade setups (honoring AGENTS.md cash-context policy).
"""

from __future__ import annotations

from collections import OrderedDict
import logging
import threading
from typing import Any, Optional

import pandas as pd

from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("engine.feature_bus")

_FEATURE_CACHE_LOCK = threading.Lock()
_FEATURE_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_MAX_FEATURE_CACHE = 1024

# Representative free-float constituent weight priors (SSOT across feature_bus, market_internals, index_contagion)
INDEX_CONSTITUENT_WEIGHTS: dict[str, dict[str, float]] = {
    "NIFTY": {
        "HDFCBANK": 0.125,
        "RELIANCE": 0.088,
        "ICICIBANK": 0.085,
        "INFY": 0.058,
        "BHARTIARTL": 0.044,
        "LT": 0.042,
        "TCS": 0.039,
        "ITC": 0.038,
        "AXISBANK": 0.031,
        "SBIN": 0.031,
    },
    "BANKNIFTY": {
        "HDFCBANK": 0.285,
        "ICICIBANK": 0.240,
        "SBIN": 0.105,
        "AXISBANK": 0.095,
        "KOTAKBANK": 0.090,
        "INDUSINDBK": 0.045,
    },
    "MIDCPNIFTY": {
        "PERSISTENT": 0.078,
        "FEDERALBNK": 0.069,
        "DIXON": 0.064,
        "POLYCAB": 0.061,
        "COFORGE": 0.058,
        "AUBANK": 0.055,
        "HDFCAMC": 0.052,
        "ASHOKLEY": 0.049,
        "MAXHEALTH": 0.047,
        "CONCOR": 0.044,
    },
    "SENSEX": {
        "HDFCBANK": 0.148,
        "RELIANCE": 0.122,
        "ICICIBANK": 0.105,
        "INFY": 0.072,
        "TCS": 0.052,
        "LT": 0.049,
        "BHARTIARTL": 0.045,
        "SBIN": 0.039,
        "AXISBANK": 0.038,
        "KOTAKBANK": 0.032,
    },
    "FINNIFTY": {
        "HDFCBANK": 0.280,
        "ICICIBANK": 0.220,
        "BAJFINANCE": 0.095,
        "SBIN": 0.075,
        "AXISBANK": 0.070,
        "KOTAKBANK": 0.065,
    },
}


def clear_feature_bus_cache() -> None:
    """Clear shared feature cache (used in tests and memory trim hooks)."""
    with _FEATURE_CACHE_LOCK:
        _FEATURE_CACHE.clear()


def _normalize_ohlcv_columns(df: pd.DataFrame) -> Optional[dict[str, pd.Series]]:
    cols = {str(c).lower(): c for c in df.columns}
    if not {"high", "low", "close"}.issubset(cols.keys()):
        return None
    out = {
        "high": df[cols["high"]].astype(float),
        "low": df[cols["low"]].astype(float),
        "close": df[cols["close"]].astype(float),
    }
    if "open" in cols:
        out["open"] = df[cols["open"]].astype(float)
    else:
        out["open"] = out["close"]
    if "volume" in cols:
        out["volume"] = df[cols["volume"]].astype(float)
    else:
        out["volume"] = pd.Series(0.0, index=df.index, dtype=float)
    return out


def compute_shared_features(
    symbol: str,
    df_intraday: Optional[pd.DataFrame],
    *,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Compute vectorized technical + pre-breakout staging features once per symbol/bar."""
    clean = canonical_alert_symbol(symbol).upper()
    if df_intraday is None or len(df_intraday) < 15:
        return {"symbol": clean, "status": "INSUFFICIENT_DATA"}

    norm = _normalize_ohlcv_columns(df_intraday)
    if norm is None:
        return {"symbol": clean, "status": "INVALID_SCHEMA"}

    close = norm["close"]
    last_close = float(close.iloc[-1])
    last_idx = str(df_intraday.index[-1])
    cache_key = (clean, len(df_intraday), last_idx, round(last_close, 4))

    if use_cache:
        with _FEATURE_CACHE_LOCK:
            if cache_key in _FEATURE_CACHE:
                _FEATURE_CACHE.move_to_end(cache_key)
                return dict(_FEATURE_CACHE[cache_key])

    high = norm["high"]
    low = norm["low"]
    vol = norm["volume"]

    ema_9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema_20_s = close.ewm(span=20, adjust=False).mean()
    ema_20 = float(ema_20_s.iloc[-1])
    ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

    # ATR(14)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_series = tr.rolling(14, min_periods=5).mean()
    atr_14 = (
        float(atr_series.iloc[-1])
        if not pd.isna(atr_series.iloc[-1])
        else max(0.01, last_close * 0.005)
    )
    atr_14 = max(1e-6, atr_14)
    natr_pct = (atr_14 / max(last_close, 1e-6)) * 100.0

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0.0).ewm(com=13, min_periods=5).mean()
    loss = (-delta).clip(lower=0.0).ewm(com=13, min_periods=5).mean()
    rs = float(gain.iloc[-1]) / max(float(loss.iloc[-1]), 1e-9)
    rsi_14 = 100.0 - (100.0 / (1.0 + rs))

    # Session VWAP approximation across available intraday bars
    tp = (high + low + close) / 3.0
    cum_vol = float(vol.sum())
    vwap = float((tp * vol).sum() / cum_vol) if cum_vol > 0 else float(tp.mean())
    vwap_dist_atr = (last_close - vwap) / atr_14

    # Bollinger-Keltner Squeeze & NR7 Compression
    bb_mid = close.rolling(20, min_periods=10).mean()
    bb_std = close.rolling(20, min_periods=10).std(ddof=0)
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    kc_upper = ema_20_s + 1.5 * atr_series
    kc_lower = ema_20_s - 1.5 * atr_series
    squeeze_on = bool(
        not pd.isna(bb_upper.iloc[-1])
        and not pd.isna(kc_upper.iloc[-1])
        and float(bb_upper.iloc[-1]) < float(kc_upper.iloc[-1])
        and float(bb_lower.iloc[-1]) > float(kc_lower.iloc[-1])
    )
    bb_width_pct = (
        float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / max(float(bb_mid.iloc[-1]), 1e-6)) * 100.0
        if not pd.isna(bb_upper.iloc[-1])
        else 0.0
    )

    bar_range = (high - low).abs()
    nr7 = bool(
        len(bar_range) >= 7 and float(bar_range.iloc[-1]) <= float(bar_range.iloc[-7:].min()) + 1e-9
    )

    vol_ma20 = float(vol.rolling(20, min_periods=5).mean().iloc[-1])
    vol_ratio = (float(vol.iloc[-1]) / vol_ma20) if vol_ma20 > 0 else 0.0

    # Time-of-Day Normalized RVOL (TOD-RVOL): compares latest bar against prior sessions'
    # same (hour, minute) volume baseline when multi-day intraday timestamps exist.
    tod_rvol = vol_ratio
    if hasattr(df_intraday.index, "time") and hasattr(df_intraday.index, "date") and len(vol) >= 2:
        try:
            cur_ts = df_intraday.index[-1]
            cur_date = cur_ts.date()
            cur_time = cur_ts.time()
            same_tod = vol[
                (df_intraday.index.time == cur_time) & (df_intraday.index.date < cur_date)
            ]
            same_tod_pos = same_tod[same_tod > 0]
            if len(same_tod_pos) >= 1:
                tod_base = float(same_tod_pos.median())
                if tod_base > 0:
                    tod_rvol = float(vol.iloc[-1]) / tod_base
        except Exception:
            tod_rvol = vol_ratio
    eff_vol_ratio = max(vol_ratio, tod_rvol)

    # Universal STALK -> PRIMED -> IGNITED -> EXTENDED timing hint
    ema_dist_atr = abs(last_close - ema_20) / atr_14
    if ema_dist_atr > 1.75:
        pre_breakout_stage = "EXTENDED"
    elif (squeeze_on or nr7) and ema_dist_atr <= 0.60 and eff_vol_ratio < 1.3:
        pre_breakout_stage = "STALK"
    elif (squeeze_on or nr7 or ema_dist_atr <= 0.45) and eff_vol_ratio >= 1.15:
        pre_breakout_stage = "PRIMED"
    elif eff_vol_ratio >= 1.50 and ema_dist_atr <= 1.35:
        pre_breakout_stage = "IGNITED"
    else:
        pre_breakout_stage = "STALK" if ema_dist_atr <= 0.80 else "NEUTRAL"

    features: dict[str, Any] = {
        "symbol": clean,
        "status": "AVAILABLE",
        "last_close": round(last_close, 4),
        "ema_9": round(ema_9, 4),
        "ema_20": round(ema_20, 4),
        "ema_50": round(ema_50, 4),
        "rsi_14": round(float(rsi_14), 2),
        "atr_14": round(atr_14, 4),
        "natr_pct": round(natr_pct, 4),
        "vwap": round(vwap, 4),
        "vwap_dist_atr": round(vwap_dist_atr, 3),
        "bb_width_pct": round(bb_width_pct, 4),
        "kc_squeeze_on": squeeze_on,
        "nr7": nr7,
        "vol_ratio": round(vol_ratio, 3),
        "tod_rvol": round(tod_rvol, 3),
        "ema20_dist_atr": round(ema_dist_atr, 3),
        "pre_breakout_stage": pre_breakout_stage,
    }

    with _FEATURE_CACHE_LOCK:
        while len(_FEATURE_CACHE) >= _MAX_FEATURE_CACHE:
            _FEATURE_CACHE.popitem(last=False)
        _FEATURE_CACHE[cache_key] = dict(features)

    return features


def compute_constituent_lead_lag(
    index_symbol: str,
    quotes_map: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compute read-only constituent-weighted impulse & VWAP leadership for NIFTY / BANKNIFTY.

    Strictly an analytical predictor for Index Options/Futures; never generates cash-equity setups.
    """
    clean_idx = canonical_alert_symbol(index_symbol).upper()
    weights = INDEX_CONSTITUENT_WEIGHTS.get(clean_idx)
    if not weights:
        return {"index": clean_idx, "status": "UNSUPPORTED", "lead_bias": "NEUTRAL"}

    q_source = quotes_map
    if q_source is None:
        try:
            from market.quotes import get_quote

            req = [f"NSE:{sym}" for sym in weights]
            q_source = get_quote(req, ws_only=True) or {}
        except Exception as exc_q:
            logger.debug("[FeatureBus] Constituent WS quote lookup unavailable: %s", exc_q)
            q_source = {}

    total_w = 0.0
    weighted_chg = 0.0
    bullish_vwap_w = 0.0
    bearish_vwap_w = 0.0
    reporting = 0

    for sym, w in weights.items():
        q = q_source.get(f"NSE:{sym}") or q_source.get(sym)
        if q is None:
            continue
        if isinstance(q, dict):
            ltp = float(q.get("last_price") or q.get("ltp") or 0.0)
            vwap = float(q.get("vwap") or 0.0)
            chg = float(q.get("change_pct") or 0.0)
        else:
            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            vwap = float(getattr(q, "vwap", 0.0) or 0.0)
            chg = float(getattr(q, "change_pct", 0.0) or 0.0)

        if ltp <= 0:
            continue
        reporting += 1
        total_w += w
        weighted_chg += w * chg
        if vwap > 0:
            if ltp > vwap:
                bullish_vwap_w += w
            elif ltp < vwap:
                bearish_vwap_w += w

    if reporting == 0 or total_w <= 0.0:
        return {
            "index": clean_idx,
            "status": "UNAVAILABLE",
            "lead_bias": "NEUTRAL",
            "constituents_reporting": 0,
        }

    norm_impulse = weighted_chg / total_w
    bull_pct = (bullish_vwap_w / total_w) * 100.0
    bear_pct = (bearish_vwap_w / total_w) * 100.0

    if norm_impulse >= 0.25 and bull_pct >= 60.0:
        bias = "BULLISH_LEAD"
    elif norm_impulse <= -0.25 and bear_pct >= 60.0:
        bias = "BEARISH_LEAD"
    else:
        bias = "NEUTRAL"

    return {
        "index": clean_idx,
        "status": "AVAILABLE",
        "constituents_reporting": reporting,
        "coverage_weight_pct": round(total_w * 100.0, 1),
        "weighted_impulse_pct": round(norm_impulse, 3),
        "bullish_vwap_weight_pct": round(bull_pct, 1),
        "bearish_vwap_weight_pct": round(bear_pct, 1),
        "lead_bias": bias,
    }


def evaluate_index_constituent_confluence(
    index_symbol: str,
    direction: str,
    quotes_map: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate whether index heavyweight constituents lead or oppose a directional thesis."""
    ll = compute_constituent_lead_lag(index_symbol, quotes_map=quotes_map)
    if ll.get("status") != "AVAILABLE":
        return {
            **ll,
            "aligned": False,
            "strongly_aligned": False,
            "opposed": False,
        }

    is_bull = str(direction or "BULLISH").upper() in ("BULLISH", "BUY", "LONG", "CE")
    lb = ll.get("lead_bias", "NEUTRAL")
    w_imp = float(ll.get("weighted_impulse_pct", 0.0) or 0.0)
    bull_w = float(ll.get("bullish_vwap_weight_pct", 0.0) or 0.0)
    bear_w = float(ll.get("bearish_vwap_weight_pct", 0.0) or 0.0)

    if is_bull:
        aligned = lb == "BULLISH_LEAD" or (w_imp >= 0.20 and bull_w >= 60.0)
        strongly_aligned = lb == "BULLISH_LEAD" and w_imp >= 0.35 and bull_w >= 65.0
        opposed = lb == "BEARISH_LEAD" and w_imp <= -0.30 and bear_w >= 65.0
    else:
        aligned = lb == "BEARISH_LEAD" or (w_imp <= -0.20 and bear_w >= 60.0)
        strongly_aligned = lb == "BEARISH_LEAD" and w_imp <= -0.35 and bear_w >= 65.0
        opposed = lb == "BULLISH_LEAD" and w_imp >= 0.30 and bull_w >= 65.0

    return {
        **ll,
        "aligned": aligned,
        "strongly_aligned": strongly_aligned,
        "opposed": opposed,
    }


def classify_setup_lifecycle(
    shared_features: Optional[dict[str, Any]],
    *,
    distance_atr: Optional[float] = None,
    extension_atr: Optional[float] = None,
    breakout_confirmed: bool = False,
    lead_aligned: bool = False,
    no_chase_atr: float = 0.35,
) -> str:
    """Universal 7-archetype staging classifier: STALK -> PRIMED -> IGNITED -> EXPIRED_STALK."""
    if extension_atr is not None and extension_atr > no_chase_atr:
        return "EXPIRED_STALK"

    feats = shared_features or {}
    coiling = bool(feats.get("kc_squeeze_on") or feats.get("nr7"))
    vol_ratio = float(feats.get("vol_ratio") or 0.0)

    if breakout_confirmed:
        return "IGNITED"
    if distance_atr is not None:
        d_abs = abs(float(distance_atr))
        if d_abs <= 0.35 and (coiling or lead_aligned or vol_ratio >= 1.15):
            return "PRIMED"
        if d_abs <= 0.80:
            return "STALK"
    hint = str(feats.get("pre_breakout_stage") or "").upper()
    if hint in ("STALK", "PRIMED", "IGNITED"):
        return hint
    return "STALK"
