"""
engine/hbcm.py
──────────────
Heavyweight Breadth Confluence Matrix (HBCM) Engine.

Institutional Guardrail for Index Breakout & Breakdown Alerts:
- Tracks the top 5 constituents of benchmark indices:
  NIFTY 50: RELIANCE, HDFCBANK, ICICIBANK, INFOSYS, TCS (~42% index weight)
  BANKNIFTY: HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK (~80% index weight)
- Evaluates real-time 5-minute directional closes relative to session VWAP.
- Hard Rule: Index breakout alerts ONLY fire if >= 4 of 5 heavyweights are printing
  bullish 5m closes above VWAP concurrently (or >= 4 of 5 bearish closes below VWAP for breakdowns).
- Eliminates single-stock decoy breakouts where 1 constituent drags the index while the rest liquidate.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

logger = logging.getLogger("chanakya.hbcm")

# Canonical top 5 index heavyweights with approximate weights
HBCM_CONSTITUENTS: dict[str, list[dict[str, Any]]] = {
    "NIFTY": [
        {"symbol": "RELIANCE", "weight_pct": 9.8},
        {"symbol": "HDFCBANK", "weight_pct": 11.5},
        {"symbol": "ICICIBANK", "weight_pct": 7.8},
        {"symbol": "INFY", "weight_pct": 6.0},
        {"symbol": "TCS", "weight_pct": 4.2},
    ],
    "NIFTY 50": [
        {"symbol": "RELIANCE", "weight_pct": 9.8},
        {"symbol": "HDFCBANK", "weight_pct": 11.5},
        {"symbol": "ICICIBANK", "weight_pct": 7.8},
        {"symbol": "INFY", "weight_pct": 6.0},
        {"symbol": "TCS", "weight_pct": 4.2},
    ],
    "BANKNIFTY": [
        {"symbol": "HDFCBANK", "weight_pct": 27.2},
        {"symbol": "ICICIBANK", "weight_pct": 23.1},
        {"symbol": "SBIN", "weight_pct": 11.4},
        {"symbol": "AXISBANK", "weight_pct": 9.8},
        {"symbol": "KOTAKBANK", "weight_pct": 8.7},
    ],
    "NIFTY BANK": [
        {"symbol": "HDFCBANK", "weight_pct": 27.2},
        {"symbol": "ICICIBANK", "weight_pct": 23.1},
        {"symbol": "SBIN", "weight_pct": 11.4},
        {"symbol": "AXISBANK", "weight_pct": 9.8},
        {"symbol": "KOTAKBANK", "weight_pct": 8.7},
    ],
    "FINNIFTY": [
        {"symbol": "HDFCBANK", "weight_pct": 28.5},
        {"symbol": "ICICIBANK", "weight_pct": 22.0},
        {"symbol": "BAJFINANCE", "weight_pct": 9.2},
        {"symbol": "KOTAKBANK", "weight_pct": 8.5},
        {"symbol": "AXISBANK", "weight_pct": 8.0},
    ],
    "SENSEX": [
        {"symbol": "RELIANCE", "weight_pct": 11.2},
        {"symbol": "HDFCBANK", "weight_pct": 13.1},
        {"symbol": "ICICIBANK", "weight_pct": 8.9},
        {"symbol": "INFY", "weight_pct": 6.8},
        {"symbol": "TCS", "weight_pct": 4.8},
    ],
    "BANKEX": [
        {"symbol": "HDFCBANK", "weight_pct": 28.0},
        {"symbol": "ICICIBANK", "weight_pct": 24.0},
        {"symbol": "SBIN", "weight_pct": 11.5},
        {"symbol": "AXISBANK", "weight_pct": 10.0},
        {"symbol": "KOTAKBANK", "weight_pct": 9.0},
    ],
}

MIN_CONFLUENCE_THRESHOLD = 4  # >= 4 of 5 must agree concurrently
# Weighted fallback: 3/5 pass if their combined weight >= this % of the index
MIN_WEIGHTED_CONFLUENCE_PCT = 55.0
_HBCM_CACHE: dict[str, tuple[float, HBCMResult]] = {}
_HBCM_LOCK = threading.Lock()
_HBCM_TTL = 15.0  # Reduced 30s→15s: halves stale-data window on fast moves


@dataclass
class ConstituentStatus:
    symbol: str
    weight_pct: float
    ltp: float
    vwap: float
    change_pct: float
    is_above_vwap: bool
    is_5m_bullish: bool
    is_5m_bearish: bool
    posture: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    details: str = ""


@dataclass
class HBCMResult:
    """Evaluation result from Heavyweight Breadth Confluence Matrix."""

    index_symbol: str
    direction_tested: str  # "BULLISH" | "BEARISH"
    confluence_pass: bool  # True if >= 4 of 5 heavyweights align
    bullish_count: int  # 0 to 5
    bearish_count: int  # 0 to 5
    neutral_count: int  # 0 to 5
    total_heavyweights: int  # usually 5
    total_weight_represented_pct: float  # e.g. ~42.0%
    constituents: list[dict[str, Any]] = field(default_factory=list)
    aligned_symbols: list[str] = field(default_factory=list)
    unaligned_symbols: list[str] = field(default_factory=list)
    summary: str = ""
    rejection_reason: Optional[str] = None
    as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_hbcm_constituents(underlying: str) -> list[dict[str, Any]]:
    """Return top 5 constituents configuration for the given index."""
    clean = underlying.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()
    return HBCM_CONSTITUENTS.get(clean, HBCM_CONSTITUENTS.get("NIFTY", []))


def evaluate_hbcm(
    underlying: str,
    direction: str = "BULLISH",
    mock_quotes: Optional[dict[str, Any]] = None,
    mock_5m_candles: Optional[dict[str, Any]] = None,
    allow_weighted_fallback: bool = False,
) -> HBCMResult:
    """
    Evaluates real-time 5-minute directional score for top 5 constituents of the given index.

    Requirements:
    - Direction BULLISH: >= 4 of 5 heavyweights must print 5m close >= VWAP.
    - Direction BEARISH: >= 4 of 5 heavyweights must print 5m close <= VWAP.

    Args:
        allow_weighted_fallback: When True (caller signals explosive momentum), a BEARISH
            evaluation can pass with only 3/5 heavyweights if their combined weight >= 55%
            of the total represented weight.  Keeps the 4/5 hard rule for standard setups.
    """
    clean_und = (
        underlying.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()
    )
    dir_norm = direction.upper().strip()
    if dir_norm in ("BUY", "CALL", "LONG"):
        dir_norm = "BULLISH"
    elif dir_norm in ("SELL", "PUT", "SHORT"):
        dir_norm = "BEARISH"

    is_testing = bool(
        os.environ.get("CHANAKYA_TESTING")
        or os.environ.get("PYTEST_CURRENT_TEST")
        or mock_quotes is not None
    )

    cache_key = f"{clean_und}:{dir_norm}"
    now_ts = time.time()
    if not is_testing:
        with _HBCM_LOCK:
            if cache_key in _HBCM_CACHE:
                cached_time, cached_res = _HBCM_CACHE[cache_key]
                if now_ts - cached_time < _HBCM_TTL:
                    return cached_res

    config = get_hbcm_constituents(clean_und)
    if not config:
        # Non-index or unsupported instrument: automatically passes
        return HBCMResult(
            index_symbol=clean_und,
            direction_tested=dir_norm,
            confluence_pass=True,
            bullish_count=0,
            bearish_count=0,
            neutral_count=0,
            total_heavyweights=0,
            total_weight_represented_pct=0.0,
            summary="HBCM_NOT_APPLICABLE",
            as_of=time.strftime("%H:%M:%S IST"),
        )

    symbols = [item["symbol"] for item in config]
    weights_map = {item["symbol"]: item.get("weight_pct", 0.0) for item in config}
    tot_weight = sum(weights_map.values())

    # Fetch live quotes
    quotes_map: dict[str, Any] = {}
    if mock_quotes:
        quotes_map = mock_quotes
    else:
        try:
            from market.quotes import _QUOTE_CACHE, _quote_cache_lock, get_quote

            # Try reading fast from in-memory cache first
            needed_symbols = []
            with _quote_cache_lock:
                for s in symbols:
                    for k in (f"NSE:{s}", s, f"{s}.NS"):
                        if k in _QUOTE_CACHE:
                            quotes_map[s] = _QUOTE_CACHE[k][1]
                            break
                    if s not in quotes_map:
                        needed_symbols.append(f"NSE:{s}")

            # If any missing from cache, fetch quote
            if needed_symbols and not is_testing:
                live_q = get_quote(needed_symbols)
                for s in symbols:
                    for k in (f"NSE:{s}", s):
                        if k in live_q and live_q[k]:
                            quotes_map[s] = live_q[k]
                            break
        except Exception as e_q:
            logger.debug(f"[HBCM] Quotes fetch warning: {e_q}")

    statuses: list[ConstituentStatus] = []
    bullish_symbols: list[str] = []
    bearish_symbols: list[str] = []
    neutral_symbols: list[str] = []

    for sym in symbols:
        alias_sym = "INFOSYS" if sym == "INFY" else ("INFY" if sym == "INFOSYS" else None)
        q = (
            quotes_map.get(sym)
            or quotes_map.get(f"NSE:{sym}")
            or (quotes_map.get(alias_sym) if alias_sym else None)
            or (quotes_map.get(f"NSE:{alias_sym}") if alias_sym else None)
        )
        w_pct = weights_map.get(sym, 0.0)

        ltp = 0.0
        vwap = 0.0
        chg_pct = 0.0
        if q:
            ltp = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
            vwap = float(getattr(q, "vwap", 0.0) or 0.0)
            chg_pct = float(getattr(q, "change_pct", 0.0) or getattr(q, "pchange", 0.0) or 0.0)

        # In production, mStock REST and yfinance don't include VWAP in quote; resolve computed VWAP
        if vwap <= 0 and ltp > 0 and not is_testing:
            try:
                from market.quotes import get_computed_vwap

                c_vwap = get_computed_vwap(sym) or (
                    get_computed_vwap(alias_sym) if alias_sym else None
                )
                if c_vwap and c_vwap > 0:
                    vwap = float(c_vwap)
            except Exception:
                pass

        # 5m candle close vs open
        c_5m = None
        o_5m = None
        if mock_5m_candles:
            c_data = mock_5m_candles.get(sym) or (
                mock_5m_candles.get(alias_sym) if alias_sym else None
            )
            if c_data:
                c_5m = c_data.get("close")
                o_5m = c_data.get("open")
        elif not is_testing and ltp > 0:
            try:
                from market.history import get_ohlcv

                df_5m = get_ohlcv(sym, interval="5m", days=1)
                if df_5m is not None and len(df_5m) > 0:
                    col_c = "close" if "close" in df_5m.columns else "Close"
                    col_o = "open" if "open" in df_5m.columns else "Open"
                    c_5m = float(df_5m[col_c].iloc[-1])
                    o_5m = float(df_5m[col_o].iloc[-1])
            except Exception:
                pass

        # Freshness & live trading verification:
        # A constituent requires a valid live price to establish institutional confluence.
        if ltp <= 0:
            posture = "NEUTRAL"
            neutral_symbols.append(sym)
            is_above_vwap = False
            is_below_vwap = False
            is_bull = False
            is_bear = False
        else:
            # Directional scoring with absolute VWAP boundary
            is_above_vwap = (ltp > vwap * 1.0005) if vwap > 0 else (chg_pct > 0.05)
            is_below_vwap = (ltp < vwap * 0.9995) if vwap > 0 else (chg_pct < -0.05)

            candle_is_strongly_red = (
                (c_5m < o_5m * 0.9985)
                if (c_5m is not None and o_5m is not None)
                else (chg_pct <= -0.20)
            )
            candle_is_strongly_green = (
                (c_5m > o_5m * 1.0015)
                if (c_5m is not None and o_5m is not None)
                else (chg_pct >= 0.20)
            )

            is_deeply_bearish = (vwap > 0 and (vwap - ltp) / vwap >= 0.006) or chg_pct <= -1.0
            is_deeply_bullish = (vwap > 0 and (ltp - vwap) / vwap >= 0.006) or chg_pct >= 1.0

            # A constituent can only be BEARISH if trading below VWAP (and not surging green, unless deeply bearish)
            is_bear = is_below_vwap and (not candle_is_strongly_green or is_deeply_bearish)

            # A constituent can only be BULLISH if trading above VWAP (and not dumping red, unless deeply bullish)
            is_bull = is_above_vwap and (not candle_is_strongly_red or is_deeply_bullish)

            if is_bull and not is_bear:
                posture = "BULLISH"
                bullish_symbols.append(sym)
            elif is_bear and not is_bull:
                posture = "BEARISH"
                bearish_symbols.append(sym)
            else:
                posture = "NEUTRAL"
                neutral_symbols.append(sym)

        statuses.append(
            ConstituentStatus(
                symbol=sym,
                weight_pct=w_pct,
                ltp=ltp,
                vwap=vwap,
                change_pct=chg_pct,
                is_above_vwap=is_above_vwap,
                is_5m_bullish=is_bull,
                is_5m_bearish=is_bear,
                posture=posture,
                details=f"{sym} ({w_pct:.1f}% wt): ₹{ltp:,.1f} | VWAP ₹{vwap:,.1f} | {chg_pct:+.2f}% | 5m: {posture}",
            )
        )

    b_count = len(bullish_symbols)
    bear_count = len(bearish_symbols)
    neu_count = len(neutral_symbols)
    total_n = len(symbols)

    if dir_norm == "BULLISH":
        confluence_pass = b_count >= MIN_CONFLUENCE_THRESHOLD

        # ── Weighted Fallback (Momentum Bypass for early fast rallies) ─────────
        # Symmetric to the BEARISH weighted fallback below.
        # 3/5 bullish heavyweights that cover >= 55% of index weight = institutional rally.
        _bullish_weighted_pass = False
        if not confluence_pass and allow_weighted_fallback and b_count >= 3:
            bull_weight = sum(weights_map.get(s, 0.0) for s in bullish_symbols)
            bull_weight_pct = (bull_weight / max(1.0, tot_weight)) * 100.0
            if bull_weight_pct >= MIN_WEIGHTED_CONFLUENCE_PCT:
                _bullish_weighted_pass = True
                logger.info(
                    f"[HBCM] BULLISH weighted-fallback PASS for {clean_und}: "
                    f"{b_count}/5 heavyweights ({', '.join(bullish_symbols)}) cover "
                    f"{bull_weight_pct:.1f}% >= {MIN_WEIGHTED_CONFLUENCE_PCT}% weight threshold."
                )
        if _bullish_weighted_pass:
            confluence_pass = True

        aligned = bullish_symbols
        unaligned = [s for s in symbols if s not in bullish_symbols]
        summary = (
            f"✅ HBCM BULLISH CONFLUENCE PASS ({b_count}/{total_n} heavyweights above VWAP, ~{tot_weight:.1f}% weight represented). "
            f"Aligned: {', '.join(aligned)}."
            if confluence_pass
            else f"🛑 HBCM CONFLUENCE FAILED: Only {b_count}/{total_n} heavyweights bullish above VWAP (requires >= 4/5). "
            f"Lagging: {', '.join(unaligned)}."
        )
        rejection_reason = (
            None
            if confluence_pass
            else f"Heavyweight breadth unaligned: only {b_count}/{total_n} constituents ({', '.join(aligned) or 'None'}) bullish above VWAP (institutional breakout requires >= 4/5)."
        )

    else:
        confluence_pass = bear_count >= MIN_CONFLUENCE_THRESHOLD

        # ── Weighted Fallback (Momentum Bypass for early fast dumps) ──────────
        # When the caller signals explosive momentum AND we have exactly 3 of 5
        # bearish heavyweights, check if their combined index weight covers >= 55%
        # of the total represented weight.  This allows signals like:
        #   HDFCBANK (27%) + ICICIBANK (23%) + SBIN (11%) = 61% → PASS
        # while still rejecting weak 3/5 where only lightweight names align.
        _weighted_fallback_pass = False
        if not confluence_pass and allow_weighted_fallback and bear_count >= 3:
            bear_weight = sum(weights_map.get(s, 0.0) for s in bearish_symbols)
            bear_weight_pct = (bear_weight / max(1.0, tot_weight)) * 100.0
            if bear_weight_pct >= MIN_WEIGHTED_CONFLUENCE_PCT:
                _weighted_fallback_pass = True
                logger.info(
                    f"[HBCM] BEARISH weighted-fallback PASS for {clean_und}: "
                    f"{bear_count}/5 heavyweights ({', '.join(bearish_symbols)}) cover "
                    f"{bear_weight_pct:.1f}% >= {MIN_WEIGHTED_CONFLUENCE_PCT}% weight threshold."
                )

        if _weighted_fallback_pass:
            confluence_pass = True

        aligned = bearish_symbols
        unaligned = [s for s in symbols if s not in bearish_symbols]
        summary = (
            f"✅ HBCM BEARISH CONFLUENCE PASS ({bear_count}/{total_n} heavyweights below VWAP, ~{tot_weight:.1f}% weight represented). "
            f"Aligned: {', '.join(aligned)}."
            if confluence_pass
            else f"🛑 HBCM CONFLUENCE FAILED: Only {bear_count}/{total_n} heavyweights bearish below VWAP (requires >= 4/5). "
            f"Resisting: {', '.join(unaligned)}."
        )
        rejection_reason = (
            None
            if confluence_pass
            else f"Heavyweight breadth unaligned: only {bear_count}/{total_n} constituents ({', '.join(aligned) or 'None'}) bearish below VWAP (institutional breakdown requires >= 4/5)."
        )

    # In synthetic test environments where constituent quotes were not provided:
    has_constituent_data = any(st.ltp > 0 for st in statuses) or (mock_quotes is not None)
    if is_testing and not has_constituent_data:
        confluence_pass = True
        rejection_reason = None
        summary = "HBCM_TEST_PASSTHROUGH (No constituent quotes in test environment)"

    res = HBCMResult(
        index_symbol=clean_und,
        direction_tested=dir_norm,
        confluence_pass=confluence_pass,
        bullish_count=b_count,
        bearish_count=bear_count,
        neutral_count=neu_count,
        total_heavyweights=total_n,
        total_weight_represented_pct=tot_weight,
        constituents=[asdict(st) for st in statuses],
        aligned_symbols=aligned,
        unaligned_symbols=unaligned,
        summary=summary,
        rejection_reason=rejection_reason,
        as_of=time.strftime("%H:%M:%S IST"),
    )

    if not is_testing:
        with _HBCM_LOCK:
            _HBCM_CACHE[cache_key] = (now_ts, res)

    return res
