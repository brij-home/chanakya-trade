"""
engine/indicator_snapshot.py
─────────────────────────────
Canonical Institutional Indicator Snapshot Engine.

Single Source of Truth (SSOT) aggregator for all quantitative indicators
required by the 3Cs → 5Ws → 1H hierarchical signal pipeline.

Guarantees (AGENTS.md Invariants 10, 11, 13, 20):
  - Every field carries an explicit per-field provenance_tag:
      REAL_LIVE        → Live WebSocket / REST from active broker
      DEGRADED_CACHED  → Stale cache (> TTL), last-known value served
      COMPUTED_ESTIMATE → Deterministic BS/mathematical fallback, not live data
      UNAVAILABLE      → Data not available; fail-closed, never fabricated
  - Thread-safe 15s TTL cache prevents redundant broker REST calls across detectors.
  - Fail-closed contract: Returns `UNAVAILABLE` fields; never fabricates prices or Greeks.
  - Cold-start bootstrap: Fetches 5m OHLCV from Fyers REST at startup to seed
    MarketMatrix before intraday WebSocket bars accumulate.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.constants import IST_ZONE as IST
from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("engine.indicator_snapshot")

# ── Provenance Tags ───────────────────────────────────────────────────────────

PROVENANCE_REAL_LIVE = "REAL_LIVE"
PROVENANCE_DEGRADED_CACHED = "DEGRADED_CACHED"
PROVENANCE_COMPUTED_ESTIMATE = "COMPUTED_ESTIMATE"
PROVENANCE_UNAVAILABLE = "UNAVAILABLE"

# ── Canonical snapshot TTL ─────────────────────────────────────────────────────

_SNAPSHOT_CACHE_TTL = 15.0  # seconds — matches regime cache refresh interval
_SNAPSHOT_CACHE: dict[str, tuple[float, "IndicatorSnapshot"]] = {}
_SNAPSHOT_CACHE_LOCK = threading.Lock()


# ── Data Model ────────────────────────────────────────────────────────────────


@dataclass
class FieldValue:
    """A data value with explicit provenance tracing."""

    value: Optional[float]
    provenance: str  # One of the PROVENANCE_* constants above
    source: str = ""  # e.g. "fyers_rest", "market_matrix", "daily_levels", "black_scholes"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance, "source": self.source}


def _live(value: Optional[float], source: str = "") -> FieldValue:
    return FieldValue(value=value, provenance=PROVENANCE_REAL_LIVE, source=source)


def _degraded(value: Optional[float], source: str = "") -> FieldValue:
    return FieldValue(value=value, provenance=PROVENANCE_DEGRADED_CACHED, source=source)


def _estimated(value: Optional[float], source: str = "") -> FieldValue:
    return FieldValue(value=value, provenance=PROVENANCE_COMPUTED_ESTIMATE, source=source)


def _unavailable() -> FieldValue:
    return FieldValue(value=None, provenance=PROVENANCE_UNAVAILABLE, source="")


@dataclass
class IndicatorSnapshot:
    """
    Canonical per-symbol indicator snapshot with explicit per-field provenance.
    All fields are either live, degraded-cached, estimated, or explicitly UNAVAILABLE.
    Never fabricated.
    """

    symbol: str
    exchange: str
    evaluated_at: str = ""

    # ── Price & Volatility (C3: Company / Internal Asset Mechanics) ──────────
    cmp: FieldValue = field(default_factory=_unavailable)  # Current Market Price (LTP)
    atr_daily: FieldValue = field(default_factory=_unavailable)  # 14-period daily ATR (points)
    atr_5m: FieldValue = field(default_factory=_unavailable)  # Intraday ATR on 5m bars (points)
    adx_14: FieldValue = field(default_factory=_unavailable)  # 14-period Wilder ADX
    roc_3bar: FieldValue = field(default_factory=_unavailable)  # 3-bar 5m ROC % (momentum)
    chop_index: FieldValue = field(default_factory=_unavailable)  # 14-bar Choppiness Index
    vix: FieldValue = field(default_factory=_unavailable)  # India VIX

    # ── Daily Reference Levels ────────────────────────────────────────────────
    pdh: FieldValue = field(default_factory=_unavailable)  # Previous Day High
    pdl: FieldValue = field(default_factory=_unavailable)  # Previous Day Low
    pdc: FieldValue = field(default_factory=_unavailable)  # Previous Day Close
    cpr_pivot: FieldValue = field(default_factory=_unavailable)  # CPR Pivot = (H+L+C)/3
    cpr_top: FieldValue = field(default_factory=_unavailable)  # CPR Top (TC)
    cpr_bottom: FieldValue = field(default_factory=_unavailable)  # CPR Bottom (BC)
    cpr_regime: str = "UNKNOWN"  # NARROW_CPR | WIDE_CPR | AVERAGE_CPR
    adr_exhaustion_pct: FieldValue = field(default_factory=_unavailable)  # % of daily ADR consumed

    # ── Options Greeks (per ATM strike, latest chain) ─────────────────────────
    # Only populated for F&O eligible instruments when Fyers is connected
    atm_iv: FieldValue = field(default_factory=_unavailable)  # ATM IV % (annualized)
    atm_delta: FieldValue = field(default_factory=_unavailable)  # ATM CE Delta
    atm_gamma: FieldValue = field(default_factory=_unavailable)  # ATM CE Gamma
    atm_theta: FieldValue = field(default_factory=_unavailable)  # ATM CE Theta (daily)
    atm_vega: FieldValue = field(default_factory=_unavailable)  # ATM CE Vega

    # ── Index Futures (for index underlyings) ─────────────────────────────────
    futures_ltp: FieldValue = field(default_factory=_unavailable)  # Near-month futures LTP
    futures_volume: FieldValue = field(
        default_factory=_unavailable
    )  # Near-month futures day volume
    futures_oi: FieldValue = field(default_factory=_unavailable)  # Near-month futures OI
    futures_basis: FieldValue = field(default_factory=_unavailable)  # Basis = fut_ltp - spot_ltp

    # ── Overall Status ────────────────────────────────────────────────────────
    overall_status: str = "PARTIAL"  # FULL_LIVE | PARTIAL | DEGRADED | UNAVAILABLE
    degraded_fields: list[str] = field(default_factory=list)
    unavailable_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_flat_dict(self) -> dict[str, Any]:
        """Returns a flattened dict suitable for alert metrics / API responses."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "cmp": self.cmp.value,
            "atr_daily": self.atr_daily.value,
            "atr_5m": self.atr_5m.value,
            "adx_14": self.adx_14.value,
            "roc_3bar": self.roc_3bar.value,
            "chop_index": self.chop_index.value,
            "vix": self.vix.value,
            "pdh": self.pdh.value,
            "pdl": self.pdl.value,
            "pdc": self.pdc.value,
            "cpr_pivot": self.cpr_pivot.value,
            "cpr_top": self.cpr_top.value,
            "cpr_bottom": self.cpr_bottom.value,
            "cpr_regime": self.cpr_regime,
            "adr_exhaustion_pct": self.adr_exhaustion_pct.value,
            "atm_iv": self.atm_iv.value,
            "atm_delta": self.atm_delta.value,
            "atm_gamma": self.atm_gamma.value,
            "atm_theta": self.atm_theta.value,
            "atm_vega": self.atm_vega.value,
            "futures_ltp": self.futures_ltp.value,
            "futures_volume": self.futures_volume.value,
            "futures_oi": self.futures_oi.value,
            "futures_basis": self.futures_basis.value,
            "overall_status": self.overall_status,
            "evaluated_at": self.evaluated_at,
            "provenance": {
                "cmp": self.cmp.provenance,
                "atr_daily": self.atr_daily.provenance,
                "atr_5m": self.atr_5m.provenance,
                "adx_14": self.adx_14.provenance,
                "roc_3bar": self.roc_3bar.provenance,
                "vix": self.vix.provenance,
                "pdh": self.pdh.provenance,
                "pdl": self.pdl.provenance,
                "pdc": self.pdc.provenance,
                "cpr": self.cpr_pivot.provenance,
                "atm_iv": self.atm_iv.provenance,
                "futures_volume": self.futures_volume.provenance,
            },
        }


# ── Bootstrap Helpers ──────────────────────────────────────────────────────────

_BOOTSTRAP_INDEX_SYMBOLS = [
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "SENSEX",
    "BANKEX",
]
_BOOTSTRAP_DONE: set[str] = set()
_BOOTSTRAP_LOCK = threading.Lock()


def bootstrap_market_matrix_for_symbol(symbol: str, min_bars: int = 15) -> bool:
    """
    Warm-up the in-RAM MarketMatrix for `symbol` by pre-seeding it with
    Fyers REST 5m OHLCV bars if fewer than `min_bars` are available.

    This bridges the cold-start gap between system startup and WebSocket bar
    accumulation so that ADX / ATR / ROC indicators are immediately available.

    Returns True if bootstrapping was needed and completed, False if already warm.
    """
    sym = canonical_alert_symbol(symbol)
    with _BOOTSTRAP_LOCK:
        if sym in _BOOTSTRAP_DONE:
            return False

    try:
        from engine.market_matrix import get_market_matrix

        mm = get_market_matrix()
        existing = mm.get_candles_df(sym, timeframe="5m", limit=min_bars + 5)
        if existing is not None and len(existing) >= min_bars:
            with _BOOTSTRAP_LOCK:
                _BOOTSTRAP_DONE.add(sym)
            return False  # Already warm

        # Determine exchange
        exch = "BSE" if sym in ("SENSEX", "BANKEX") else "NSE"

        # Fetch historical 5m bars from primary broker
        from market.history import get_ohlcv

        df_5m = get_ohlcv(sym, exchange=exch, interval="5m", days=2)
        if df_5m is None or df_5m.empty:
            logger.debug(
                f"[IndicatorSnapshot] Bootstrap skipped for {sym}: no 5m history from broker"
            )
            return False

        # Feed bars into MarketMatrix candle weaver using historical timestamps
        import time as _time

        bars_fed = 0
        for dt_idx, row in df_5m.iterrows():
            try:
                ltp = float(row.get("close", 0.0) or 0.0)
                vol = float(row.get("volume", 0.0) or 0.0)
                if ltp <= 0:
                    continue
                # Convert datetime index to epoch seconds for tick_ts
                if hasattr(dt_idx, "timestamp"):
                    tick_ts = dt_idx.timestamp()
                else:
                    tick_ts = _time.time()
                mm.candle_weaver.on_tick(symbol=sym, ltp=ltp, day_volume=int(vol), tick_ts=tick_ts)
                bars_fed += 1
            except Exception as e_feed:
                logger.debug(f"[IndicatorSnapshot] Bootstrap feed error for {sym}: {e_feed}")

        with _BOOTSTRAP_LOCK:
            _BOOTSTRAP_DONE.add(sym)

        provenance = getattr(df_5m, "attrs", {}).get("provenance", {})
        data_source = provenance.get("data_source", "BROKER_REST") if provenance else "BROKER_REST"
        logger.info(
            f"[IndicatorSnapshot] ✅ Bootstrapped MarketMatrix for {sym} with {bars_fed} 5m bars "
            f"(source={data_source})"
        )
        return True

    except Exception as exc:
        logger.warning(
            f"[IndicatorSnapshot] Bootstrap failed for {sym}: {exc}",
            exc_info=False,
        )
        return False


def bootstrap_all_index_symbols() -> None:
    """
    Pre-seeds MarketMatrix for all benchmark index symbols from Fyers REST.
    Called at application startup, non-blocking (spawns background thread per symbol).
    """
    for sym in _BOOTSTRAP_INDEX_SYMBOLS:
        t = threading.Thread(
            target=bootstrap_market_matrix_for_symbol,
            args=(sym,),
            kwargs={"min_bars": 20},
            name=f"bootstrap-{sym}",
            daemon=True,
        )
        t.start()
    logger.info(
        f"[IndicatorSnapshot] Bootstrap threads launched for {len(_BOOTSTRAP_INDEX_SYMBOLS)} index symbols"
    )


# ── Core Snapshot Builder ─────────────────────────────────────────────────────


def get_indicator_snapshot(
    symbol: str,
    exchange: str = "NSE",
    time_horizon: str = "INTRADAY",
    force_refresh: bool = False,
) -> IndicatorSnapshot:
    """
    Returns a canonical indicator snapshot for `symbol` with all fields
    provenance-tagged. Thread-safe, 15s TTL cached.

    Args:
        symbol:        Canonical symbol (e.g. "NIFTY", "RELIANCE")
        exchange:      "NSE" | "BSE" | "NFO"
        time_horizon:  "INTRADAY" | "SWING" | "POSITIONAL"
        force_refresh: Bypass TTL cache for real-time use cases

    Returns:
        IndicatorSnapshot with per-field provenance tags.
        Never raises; always returns a valid (possibly UNAVAILABLE) snapshot.
    """
    sym = canonical_alert_symbol(symbol)
    cache_key = f"{sym}:{exchange.upper()}"
    now_ts = time.time()

    if not force_refresh:
        with _SNAPSHOT_CACHE_LOCK:
            if cache_key in _SNAPSHOT_CACHE:
                cached_ts, cached_snap = _SNAPSHOT_CACHE[cache_key]
                if now_ts - cached_ts < _SNAPSHOT_CACHE_TTL:
                    return cached_snap

    # Bootstrap MarketMatrix if needed (non-blocking: returns immediately if already warm)
    if sym in _BOOTSTRAP_INDEX_SYMBOLS:
        try:
            bootstrap_market_matrix_for_symbol(sym, min_bars=20)
        except Exception as e_boot:
            logger.debug(
                f"[IndicatorSnapshot] Bootstrap market matrix for {sym} bypassed: {e_boot}"
            )

    snap = IndicatorSnapshot(
        symbol=sym,
        exchange=exchange.upper(),
        evaluated_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    degraded: list[str] = []
    unavailable: list[str] = []

    # ── 1. CMP ──────────────────────────────────────────────────────────────
    try:
        from market.quotes import get_quote
        from market.indices import INDEX_INSTRUMENTS

        clean_sym = sym.upper()
        if clean_sym in INDEX_INSTRUMENTS:
            exch_sym = INDEX_INSTRUMENTS[clean_sym]
        else:
            exch_sym = f"{exchange.upper()}:{sym}"

        quotes = get_quote([exch_sym])
        q = quotes.get(exch_sym) or quotes.get(clean_sym) or quotes.get(sym)
        if q and float(getattr(q, "last_price", 0.0) or 0.0) > 0:
            ltp = float(q.last_price)
            provider = str(getattr(q, "provider", "broker_ws"))
            provenance = (
                PROVENANCE_REAL_LIVE if "ws" in provider.lower() else PROVENANCE_DEGRADED_CACHED
            )
            snap.cmp = FieldValue(value=ltp, provenance=provenance, source=provider)
        else:
            snap.cmp = _unavailable()
            unavailable.append("cmp")
    except Exception as e_cmp:
        logger.debug(f"[IndicatorSnapshot] CMP fetch error for {sym}: {e_cmp}")
        snap.cmp = _unavailable()
        unavailable.append("cmp")

    # ── 2. Daily Levels: PDH, PDL, PDC, ATR-14, CPR ──────────────────────
    try:
        from engine.daily_levels import get_daily_levels_store

        store = get_daily_levels_store()
        dl = store.get_levels(sym, compute_if_missing=True)
        if dl and dl.pdh > 0 and dl.pdl > 0 and dl.pdc > 0:
            src = "daily_levels"
            snap.pdh = _live(dl.pdh, src)
            snap.pdl = _live(dl.pdl, src)
            snap.pdc = _live(dl.pdc, src)
            snap.atr_daily = _live(dl.atr_14 if dl.atr_14 > 0 else None, src)
            if dl.atr_14 <= 0:
                unavailable.append("atr_daily")
            cpr = dl.cpr or {}
            snap.cpr_pivot = _live(cpr.get("pivot") or None, src)
            snap.cpr_top = _live(cpr.get("top") or None, src)
            snap.cpr_bottom = _live(cpr.get("bottom") or None, src)
            snap.cpr_regime = str(cpr.get("regime", "AVERAGE_CPR"))
        else:
            for f in ("pdh", "pdl", "pdc", "atr_daily", "cpr_pivot", "cpr_top", "cpr_bottom"):
                unavailable.append(f)
    except Exception as e_dl:
        logger.debug(f"[IndicatorSnapshot] DailyLevels fetch error for {sym}: {e_dl}")
        for f in ("pdh", "pdl", "pdc", "atr_daily", "cpr_pivot", "cpr_top", "cpr_bottom"):
            unavailable.append(f)

    # ── 3. ADR Exhaustion % ──────────────────────────────────────────────
    try:
        if snap.cmp.value and snap.pdh.value and snap.pdl.value and snap.pdh.value > snap.pdl.value:
            cmp_v = snap.cmp.value
            pdh_v = snap.pdh.value
            pdl_v = snap.pdl.value
            adr = pdh_v - pdl_v
            # Exhaustion = how much of daily range has been consumed from open
            # Use cmp deviation from midpoint vs full ADR as proxy
            mid = (pdh_v + pdl_v) / 2.0
            consumed = abs(cmp_v - mid) / (adr / 2.0) * 100.0
            snap.adr_exhaustion_pct = _estimated(
                round(min(consumed, 100.0), 1), "midpoint_heuristic"
            )
        else:
            snap.adr_exhaustion_pct = _unavailable()
            unavailable.append("adr_exhaustion_pct")
    except Exception:
        snap.adr_exhaustion_pct = _unavailable()

    # ── 4. Intraday ATR, ADX, Choppiness, ROC (from MarketMatrix + index_velocity) ──
    try:
        from engine.market_matrix import get_market_matrix
        from engine.index_adaptive_regime import compute_adx, compute_choppiness_index

        mm = get_market_matrix()
        df_5m = mm.get_candles_df(sym, timeframe="5m", limit=80)

        if df_5m is not None and len(df_5m) >= 5:
            # Intraday ATR (Wilder's, same formula as compute_adx TR)
            try:
                import pandas as pd

                h = df_5m["high"].astype(float)
                lo = df_5m["low"].astype(float)
                c = df_5m["close"].astype(float)
                prev_c = c.shift(1)
                tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(
                    axis=1
                )
                atr_period = min(14, len(df_5m) - 1)
                atr_v = float(
                    tr.ewm(alpha=1.0 / atr_period, min_periods=atr_period).mean().iloc[-1]
                )
                snap.atr_5m = _live(round(atr_v, 2), "market_matrix_5m")
            except Exception as e_atr5m:
                logger.debug(f"[IndicatorSnapshot] Intraday ATR calc error: {e_atr5m}")
                snap.atr_5m = _unavailable()
                unavailable.append("atr_5m")

            # ADX
            adx_v = compute_adx(df_5m, period=14)
            if adx_v is not None:
                snap.adx_14 = _live(adx_v, "market_matrix_5m")
            else:
                snap.adx_14 = _unavailable()
                unavailable.append("adx_14")

            # Choppiness Index
            chop_v = compute_choppiness_index(df_5m, period=14)
            if chop_v is not None:
                snap.chop_index = _live(chop_v, "market_matrix_5m")
            else:
                snap.chop_index = _unavailable()
                unavailable.append("chop_index")

            # ROC (3-bar on 5m)
            try:
                closes = df_5m["close"].astype(float)
                if len(closes) >= 4:
                    roc_3bar = float((closes.iloc[-1] - closes.iloc[-4]) / closes.iloc[-4] * 100.0)
                    snap.roc_3bar = _live(round(roc_3bar, 3), "market_matrix_5m")
                else:
                    snap.roc_3bar = _unavailable()
                    unavailable.append("roc_3bar")
            except Exception:
                snap.roc_3bar = _unavailable()
                unavailable.append("roc_3bar")
        else:
            # MarketMatrix is cold — degrade gracefully
            for f in ("atr_5m", "adx_14", "chop_index", "roc_3bar"):
                degraded.append(f)
            logger.debug(
                f"[IndicatorSnapshot] MarketMatrix cold for {sym}: {len(df_5m) if df_5m is not None else 0} 5m bars. "
                f"Bootstrap should populate soon."
            )

    except Exception as e_mm:
        logger.debug(f"[IndicatorSnapshot] MarketMatrix indicator calc error for {sym}: {e_mm}")
        for f in ("atr_5m", "adx_14", "chop_index", "roc_3bar"):
            unavailable.append(f)

    # ── 5. India VIX ─────────────────────────────────────────────────────
    try:
        from market.indices import get_vix

        vix_v = get_vix()
        if vix_v and float(vix_v) > 0:
            snap.vix = _live(float(vix_v), "market.indices.get_vix")
        else:
            snap.vix = _unavailable()
            unavailable.append("vix")
    except Exception as e_vix:
        logger.debug(f"[IndicatorSnapshot] VIX fetch error: {e_vix}")
        snap.vix = _unavailable()
        unavailable.append("vix")

    # ── 6. Options Greeks (ATM CE from latest options chain) ─────────────
    _fno_eligible = {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "TCS",
        "AXISBANK",
        "SBIN",
        "KOTAKBANK",
        "LT",
        "BAJFINANCE",
    }
    if sym in _fno_eligible:
        try:
            from market.options import get_options_chain

            spot_price = snap.cmp.value or 0.0
            if spot_price <= 0 and snap.pdc.value and snap.pdc.value > 0:
                spot_price = snap.pdc.value
            chain = get_options_chain(sym)
            calls = [c for c in chain if getattr(c, "option_type", "") == "CE"] if chain else []
            if calls:
                # Find ATM strike (nearest to spot)
                ref_spot = (
                    spot_price if spot_price > 0 else float(getattr(calls[0], "strike", 0.0) or 0.0)
                )
                nearest_ce = min(
                    calls,
                    key=lambda c: abs(float(getattr(c, "strike", 0.0) or 0.0) - ref_spot),
                )
                if nearest_ce:
                    src = getattr(nearest_ce, "provider", "") or "options_chain"
                    # Determine whether Greeks were natively delivered (Fyers Prime) or mathematically derived (Black-Scholes)
                    is_derived = (
                        "fyers" not in src.lower()
                        and getattr(nearest_ce, "delta", None) is not None
                    )
                    prov = PROVENANCE_COMPUTED_ESTIMATE if is_derived else PROVENANCE_REAL_LIVE

                    iv_v = getattr(nearest_ce, "iv", None)
                    delta_v = getattr(nearest_ce, "delta", None)
                    gamma_v = getattr(nearest_ce, "gamma", None)
                    theta_v = getattr(nearest_ce, "theta", None)
                    vega_v = getattr(nearest_ce, "vega", None)

                    # If Greeks are missing from contract, derive via Black-Scholes
                    if (
                        delta_v is None
                        and spot_price > 0
                        and float(getattr(nearest_ce, "last_price", 0.0) or 0.0) > 0
                    ):
                        try:
                            from analysis.options import compute_greeks

                            g = compute_greeks(
                                spot=spot_price,
                                strike=float(nearest_ce.strike),
                                expiry=str(getattr(nearest_ce, "expiry", "")),
                                option_type="CE",
                                ltp=float(nearest_ce.last_price),
                            )
                            if g:
                                delta_v = g.delta
                                gamma_v = g.gamma
                                theta_v = g.theta
                                vega_v = g.vega
                                if iv_v is None and g.iv_pct > 0:
                                    iv_v = g.iv_pct
                                prov = PROVENANCE_COMPUTED_ESTIMATE
                                src = "black_scholes_analytical"
                        except Exception as e_bs:
                            logger.debug(
                                f"[IndicatorSnapshot] Black-Scholes derivation error: {e_bs}"
                            )

                    snap.atm_iv = (
                        FieldValue(float(iv_v), prov, src or "black_scholes")
                        if iv_v is not None
                        else _unavailable()
                    )
                    snap.atm_delta = (
                        FieldValue(float(delta_v), prov, src or "black_scholes")
                        if delta_v is not None
                        else _unavailable()
                    )
                    snap.atm_gamma = (
                        FieldValue(float(gamma_v), prov, src or "black_scholes")
                        if gamma_v is not None
                        else _unavailable()
                    )
                    snap.atm_theta = (
                        FieldValue(float(theta_v), prov, src or "black_scholes")
                        if theta_v is not None
                        else _unavailable()
                    )
                    snap.atm_vega = (
                        FieldValue(float(vega_v), prov, src or "black_scholes")
                        if vega_v is not None
                        else _unavailable()
                    )

                    # Mark UNAVAILABLE if Greeks are None
                    for gk in ("atm_iv", "atm_delta", "atm_gamma", "atm_theta", "atm_vega"):
                        fv: FieldValue = getattr(snap, gk)
                        if fv.value is None:
                            setattr(snap, gk, _unavailable())
                            unavailable.append(gk)
            else:
                for gk in ("atm_iv", "atm_delta", "atm_gamma", "atm_theta", "atm_vega"):
                    setattr(snap, gk, _unavailable())
                    unavailable.append(gk)
        except Exception as e_greeks:
            logger.debug(f"[IndicatorSnapshot] Greeks fetch error for {sym}: {e_greeks}")
            for gk in ("atm_iv", "atm_delta", "atm_gamma", "atm_theta", "atm_vega"):
                setattr(snap, gk, _unavailable())
                unavailable.append(gk)

    # ── 7. Index Futures Snapshot (via market.indices helper) ─────────────
    _index_syms = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}
    if sym in _index_syms:
        try:
            from market.indices import get_index_futures_snapshot

            fut = get_index_futures_snapshot(sym)
            if fut and fut.get("status") != "UNAVAILABLE":
                prov = (
                    PROVENANCE_REAL_LIVE
                    if fut.get("provenance") == "REAL_LIVE"
                    else PROVENANCE_DEGRADED_CACHED
                )
                snap.futures_ltp = FieldValue(fut.get("ltp") or None, prov, "index_futures_quote")
                snap.futures_volume = FieldValue(
                    fut.get("volume") or None, prov, "index_futures_quote"
                )
                snap.futures_oi = FieldValue(fut.get("oi") or None, prov, "index_futures_quote")
                snap.futures_basis = FieldValue(
                    fut.get("basis") or None, prov, "index_futures_quote"
                )
                for fk in ("futures_ltp", "futures_volume", "futures_oi", "futures_basis"):
                    if getattr(snap, fk).value is None:
                        setattr(snap, fk, _unavailable())
                        unavailable.append(fk)
            else:
                for fk in ("futures_ltp", "futures_volume", "futures_oi", "futures_basis"):
                    setattr(snap, fk, _unavailable())
                    unavailable.append(fk)
        except Exception as e_fut:
            logger.debug(f"[IndicatorSnapshot] Index futures snapshot error for {sym}: {e_fut}")
            for fk in ("futures_ltp", "futures_volume", "futures_oi", "futures_basis"):
                setattr(snap, fk, _unavailable())
                unavailable.append(fk)

    # ── Overall Status Computation ─────────────────────────────────────────
    snap.degraded_fields = list(set(degraded))
    snap.unavailable_fields = list(set(unavailable))

    critical_fields = {"cmp", "pdh", "pdl", "pdc"}
    critical_unavail = critical_fields.intersection(set(unavailable))
    if critical_unavail:
        snap.overall_status = "UNAVAILABLE"
    elif unavailable:
        snap.overall_status = "DEGRADED" if len(unavailable) > 4 else "PARTIAL"
    else:
        snap.overall_status = "FULL_LIVE"

    # Cache result
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE[cache_key] = (now_ts, snap)

    return snap


# ── Singleton Accessor ────────────────────────────────────────────────────────


def invalidate_snapshot_cache(symbol: Optional[str] = None) -> None:
    """Clears snapshot cache. If symbol is None, clears all entries."""
    with _SNAPSHOT_CACHE_LOCK:
        if symbol:
            sym = canonical_alert_symbol(symbol)
            keys_to_del = [k for k in _SNAPSHOT_CACHE if k.startswith(f"{sym}:")]
            for k in keys_to_del:
                _SNAPSHOT_CACHE.pop(k, None)
        else:
            _SNAPSHOT_CACHE.clear()
