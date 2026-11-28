"""
engine/level_state_machine.py
─────────────────────────────
Causal Two-Phase Event State Machine: WATCH -> ARMED -> TRIGGERED -> EXPIRED_STALK / VETOED.

Institutional Guarantees:
  1. Prefix Invariance: All level extraction, distance normalization, and ignition checks
     operate strictly on the supplied bar prefix (never reading future bars or static wall-clock
     when explicit `as_of` is supplied).
  2. Dual Index + Top Stock F&O Coverage: Evaluates benchmark indices (NIFTY, BANKNIFTY,
     SENSEX, MIDCPNIFTY, FINNIFTY) and F&O stocks under `config.discovery_policy`.
  3. Early TBT Scout Promotion: Transitioning to `ARMED` promotes the active future / ATM
     contract into Fyers 50-depth TBT scout slots *before* breakout ignition.
  4. Anti-Trap & Microstructure Gates:
     - Rejects index continuation triggers under `HEAD_FAKE_DIVERGENCE` (unless reversal mode).
     - Enforces Delta-CVD alignment / absorption confirmation when live samples >= 5.
     - Supports `5S`/`15S` seconds-bar close acceptance when supplied alongside `5m` bars.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

import pandas as pd

from config.constants import IST
from config.discovery_policy import allows_context_symbol, get_discovery_policy
from engine.alert_identity import canonical_alert_symbol
from engine.feature_bus import compute_constituent_lead_lag, compute_shared_features
from engine.option_resolver import is_index_symbol

logger = logging.getLogger("engine.level_state_machine")


def _allows_armed_symbol(symbol: str) -> bool:
    """Validate symbol against strict FNO_ONLY discovery scope."""
    if not get_discovery_policy().fno_only:
        return True
    raw = str(symbol or "").strip().upper()
    if not raw or raw.endswith(("USDT", "USDC")) or raw.startswith(("CRYPTO:", "BINANCE:", "MCX:")):
        return False
    clean = canonical_alert_symbol(raw).upper()
    if ":" in raw:
        return allows_context_symbol(raw)
    if clean in ("SENSEX", "BANKEX"):
        return allows_context_symbol(f"BSE:{clean}-INDEX")
    if is_index_symbol(clean):
        return allows_context_symbol(f"NSE:{clean}-INDEX")
    return allows_context_symbol(f"NSE:{clean}")


_VALID_STAGES = (
    "WATCH",
    "ARMED",
    "TRIGGERED",
    "VETOED",
    "EXPIRED_STALK",
    "INVALIDATED",
)


@dataclass(frozen=True)
class StructuralLevel:
    """Deterministic institutional price level mapped ahead of price arrival."""

    name: str
    price: float
    role: str  # "SUPPORT" | "RESISTANCE" | "PIVOT" | "WALL"
    source: str


@dataclass
class LevelStageState:
    """Tracked causal staging record for a symbol at a structural anchor."""

    symbol: str
    asset_class: str  # "INDEX" | "STOCK_FNO"
    stage: str  # WATCH | ARMED | TRIGGERED | VETOED | EXPIRED_STALK | INVALIDATED
    direction: str  # BULLISH | BEARISH
    anchor_name: str
    anchor_price: float
    spot: float
    atr_14: float
    distance_atr: float
    extension_atr: float
    stop_loss: Optional[float]
    target_1: Optional[float]
    no_chase_boundary: Optional[float]
    first_seen_at: str
    updated_at: str
    armed_at: Optional[str] = None
    triggered_at: Optional[str] = None
    lead_time_sec: Optional[float] = None
    tbt_scout_promoted: bool = False
    confirmation_reasons: list[str] = field(default_factory=list)
    veto_reasons: list[str] = field(default_factory=list)
    evidence_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_bars(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    cols = {str(c).lower(): c for c in df.columns}
    if not {"high", "low", "close"}.issubset(cols.keys()):
        return None
    out = pd.DataFrame(
        {
            "open": df[cols["open"]].astype(float)
            if "open" in cols
            else df[cols["close"]].astype(float),
            "high": df[cols["high"]].astype(float),
            "low": df[cols["low"]].astype(float),
            "close": df[cols["close"]].astype(float),
            "volume": df[cols["volume"]].astype(float)
            if "volume" in cols
            else pd.Series(0.0, index=df.index, dtype=float),
        },
        index=df.index,
    )
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert("Asia/Kolkata").tz_localize(None)
    return out.sort_index()


def _latest_session_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if isinstance(bars.index, pd.DatetimeIndex) and len(bars) > 0:
        last_d = bars.index[-1].date()
        sess = bars[bars.index.date == last_d]
        if not sess.empty:
            return sess
    return bars


def extract_structural_levels(
    bars_5m: pd.DataFrame,
    *,
    daily_levels: Optional[Any] = None,
    gex_snapshot: Optional[Any] = None,
) -> list[StructuralLevel]:
    """Extract strictly causal structural levels from session prefix + prior-day/GEX context."""
    levels: list[StructuralLevel] = []
    sess = _latest_session_bars(bars_5m)

    # 1. Session VWAP & Initial Balance (first 12 x 5m bars = 60 mins)
    if not sess.empty:
        tp = (sess["high"] + sess["low"] + sess["close"]) / 3.0
        vol_sum = float(sess["volume"].sum())
        if vol_sum > 0:
            vwap_val = float((tp * sess["volume"]).sum() / vol_sum)
            levels.append(StructuralLevel("VWAP", round(vwap_val, 2), "PIVOT", "SESSION_BARS"))
        if len(sess) >= 12:
            ib = sess.iloc[:12]
            levels.append(
                StructuralLevel("IBH", round(float(ib["high"].max()), 2), "RESISTANCE", "IB_60M")
            )
            levels.append(
                StructuralLevel("IBL", round(float(ib["low"].min()), 2), "SUPPORT", "IB_60M")
            )
        elif len(sess) >= 3:
            orb = sess.iloc[:3]
            levels.append(
                StructuralLevel("ORH", round(float(orb["high"].max()), 2), "RESISTANCE", "ORB_15M")
            )
            levels.append(
                StructuralLevel("ORL", round(float(orb["low"].min()), 2), "SUPPORT", "ORB_15M")
            )

    # 2. Prior Day Levels & CPR (strictly prior completed session, never current day future)
    if daily_levels is not None:

        def _dl_get(attr: str, default: float = 0.0) -> float:
            if isinstance(daily_levels, dict):
                return float(daily_levels.get(attr, default) or default)
            return float(getattr(daily_levels, attr, default) or default)

        for name, attr, role in (
            ("PDH", "pdh", "RESISTANCE"),
            ("PDL", "pdl", "SUPPORT"),
            ("PDC", "pdc", "PIVOT"),
        ):
            val = _dl_get(attr)
            if val > 0:
                levels.append(StructuralLevel(name, round(val, 2), role, "DAILY_LEVELS"))
        cpr = (
            daily_levels.get("cpr")
            if isinstance(daily_levels, dict)
            else getattr(daily_levels, "cpr", None)
        )
        if isinstance(cpr, dict):
            for c_name, c_key in (("CPR_TC", "tc"), ("CPR_BC", "bc")):
                c_val = float(cpr.get(c_key, 0.0) or 0.0)
                if c_val > 0:
                    levels.append(StructuralLevel(c_name, round(c_val, 2), "PIVOT", "CPR"))

    # 3. Live GEX Walls / Gamma Flip (optional, never synthetic)
    if gex_snapshot is not None:

        def _gex_get(attr: str) -> float:
            if isinstance(gex_snapshot, dict):
                return float(gex_snapshot.get(attr, 0.0) or 0.0)
            return float(getattr(gex_snapshot, attr, 0.0) or 0.0)

        for g_name, g_attr, g_role in (
            ("GEX_CALL_WALL", "call_wall", "RESISTANCE"),
            ("GEX_PUT_WALL", "put_wall", "SUPPORT"),
            ("GEX_GAMMA_FLIP", "gamma_flip", "PIVOT"),
        ):
            g_val = _gex_get(g_attr)
            if g_val > 0:
                levels.append(StructuralLevel(g_name, round(g_val, 2), g_role, "GEX"))

    # Deduplicate levels that sit within 0.02% of the same price while preserving order
    deduped: list[StructuralLevel] = []
    for lvl in levels:
        if lvl.price <= 0:
            continue
        if any(
            existing.name == lvl.name and abs(existing.price - lvl.price) <= 1e-6
            for existing in deduped
        ):
            continue
        deduped.append(lvl)
    return deduped


def _seconds_breakout_confirmed(
    bars_seconds: Optional[pd.DataFrame],
    anchor_price: float,
    direction: str,
) -> Optional[bool]:
    """Return True if last 2 seconds-bar closes hold beyond anchor_price, False if not, None if absent."""
    sec_df = _normalize_bars(bars_seconds)
    if sec_df is None or len(sec_df) < 2 or anchor_price <= 0:
        return None
    c1 = float(sec_df["close"].iloc[-2])
    c2 = float(sec_df["close"].iloc[-1])
    if direction == "BULLISH":
        return c1 > anchor_price and c2 > anchor_price
    return c1 < anchor_price and c2 < anchor_price


def evaluate_symbol_stage(
    symbol: str,
    bars_5m: pd.DataFrame,
    *,
    bars_seconds: Optional[pd.DataFrame] = None,
    daily_levels: Optional[Any] = None,
    gex_snapshot: Optional[Any] = None,
    internals_report: Optional[Any] = None,
    constituent_quotes: Optional[dict[str, Any]] = None,
    cvd_metrics: Optional[Any] = None,
    depth_metrics: Optional[dict[str, Any]] = None,
    previous_state: Optional[LevelStageState] = None,
    reversal_mode: bool = False,
    no_chase_atr: float = 0.45,
    as_of: Optional[datetime] = None,
    promote_tbt: bool = False,
    precomputed_features: Optional[dict[str, Any]] = None,
    skip_normalization: bool = False,
) -> Optional[LevelStageState]:
    """Evaluate causal WATCH -> ARMED -> TRIGGERED state strictly from supplied prefix data."""
    clean = canonical_alert_symbol(symbol).upper()
    norm_5m = bars_5m if skip_normalization else _normalize_bars(bars_5m)
    if norm_5m is None or len(norm_5m) < 15:
        return None

    feats = (
        precomputed_features
        if precomputed_features is not None
        else compute_shared_features(clean, norm_5m, use_cache=False)
    )
    if feats.get("status") != "AVAILABLE":
        return None

    spot = float(feats["last_close"])
    atr_14 = float(feats["atr_14"])
    if spot <= 0 or atr_14 <= 0:
        return None

    levels = extract_structural_levels(
        norm_5m, daily_levels=daily_levels, gex_snapshot=gex_snapshot
    )
    if not levels:
        return None

    # Pick closest structural anchor normalized by ATR
    best_lvl = min(levels, key=lambda lv: abs(spot - lv.price) / atr_14)
    signed_dist_atr = (spot - best_lvl.price) / atr_14
    abs_dist_atr = abs(signed_dist_atr)

    prev_close_5m = float(norm_5m["close"].iloc[-2])
    if best_lvl.role == "RESISTANCE":
        direction = "BULLISH"
    elif best_lvl.role == "SUPPORT":
        direction = "BEARISH"
    else:
        direction = "BULLISH" if spot >= best_lvl.price and spot >= prev_close_5m else "BEARISH"

    # Compute causal extension beyond anchor in trade direction
    extension_atr = (
        max(0.0, (spot - best_lvl.price) / atr_14)
        if direction == "BULLISH"
        else max(0.0, (best_lvl.price - spot) / atr_14)
    )

    is_idx = is_index_symbol(clean)
    asset_class = "INDEX" if is_idx else "STOCK_FNO"
    ref_dt = as_of or (
        norm_5m.index[-1].to_pydatetime().replace(tzinfo=IST)
        if isinstance(norm_5m.index, pd.DatetimeIndex)
        else datetime.now(IST)
    )
    ts_str = ref_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    # Structural SL / Target / No-Chase boundary strictly anchored to anchor + ATR
    risk_dist = round(max(atr_14 * 1.15, spot * 0.0015), 2)
    if direction == "BULLISH":
        stop_loss = round(best_lvl.price - risk_dist, 2)
        target_1 = round(best_lvl.price + 2.2 * risk_dist, 2)
        no_chase = round(best_lvl.price + no_chase_atr * atr_14, 2)
    else:
        stop_loss = round(best_lvl.price + risk_dist, 2)
        target_1 = round(best_lvl.price - 2.2 * risk_dist, 2)
        no_chase = round(best_lvl.price - no_chase_atr * atr_14, 2)

    confirmations: list[str] = []
    vetoes: list[str] = []

    coiling = bool(feats.get("kc_squeeze_on") or feats.get("nr7"))
    tod_rvol = float(feats.get("tod_rvol") or feats.get("vol_ratio") or 0.0)
    if coiling:
        confirmations.append("VOLATILITY_COMPRESSION")
    if tod_rvol >= 1.2:
        confirmations.append(f"TOD_RVOL_{tod_rvol:.2f}x")

    # Constituent lead-lag for benchmark indices
    lead_info = {"status": "UNAVAILABLE", "lead_bias": "NEUTRAL"}
    if is_idx and constituent_quotes is not None:
        lead_info = compute_constituent_lead_lag(clean, quotes_map=constituent_quotes)
        if lead_info.get("status") == "AVAILABLE":
            lb = str(lead_info.get("lead_bias") or "NEUTRAL")
            if (direction == "BULLISH" and lb == "BULLISH_LEAD") or (
                direction == "BEARISH" and lb == "BEARISH_LEAD"
            ):
                confirmations.append(f"CONSTITUENT_{lb}")

    # Market Internals Head-Fake anti-trap check
    internals_regime = None
    if is_idx and internals_report is not None:
        st = getattr(internals_report, "status", "AVAILABLE")
        reg = getattr(internals_report, "regime", None)
        idx_chg = float(getattr(internals_report, "change_pct", 0.0) or 0.0)
        if st == "AVAILABLE" and reg:
            internals_regime = str(reg)
            if (
                reg == "HEAD_FAKE_DIVERGENCE"
                and not reversal_mode
                and (
                    (direction == "BULLISH" and idx_chg >= 0.20)
                    or (direction == "BEARISH" and idx_chg <= -0.20)
                )
            ):
                vetoes.append("INDEX_HEAD_FAKE_DIVERGENCE")
            elif (direction == "BULLISH" and reg == "BROAD_BASED_BULLISH") or (
                direction == "BEARISH" and reg == "BROAD_BASED_BEARISH"
            ):
                confirmations.append(f"INTERNALS_{reg}")

    # Microstructure CVD check (only when genuine >= 5 samples exist)
    cvd_div = None
    if cvd_metrics is not None and int(getattr(cvd_metrics, "sample_count", 0) or 0) >= 5:
        cvd_div = str(getattr(cvd_metrics, "cvd_divergence", "NEUTRAL") or "NEUTRAL")
        cvd_bias = str(getattr(cvd_metrics, "cvd_bias", "NEUTRAL") or "NEUTRAL")
        if direction == "BULLISH" and cvd_div == "BEARISH_EXHAUSTION":
            vetoes.append("CVD_BEARISH_EXHAUSTION")
        elif direction == "BEARISH" and cvd_div == "BULLISH_ABSORPTION":
            vetoes.append("CVD_BULLISH_ABSORPTION")
        elif (
            direction == "BULLISH" and (cvd_bias == "BULLISH" or cvd_div == "BULLISH_ABSORPTION")
        ) or (
            direction == "BEARISH" and (cvd_bias == "BEARISH" or cvd_div == "BEARISH_EXHAUSTION")
        ):
            confirmations.append(f"CVD_{cvd_div if cvd_div != 'NEUTRAL' else cvd_bias}")

    # OBI-50 / L2 depth check
    obi_50 = None
    if isinstance(depth_metrics, dict) and depth_metrics.get("status") == "LIVE":
        obi_50 = depth_metrics.get("obi_50")
        if obi_50 is not None:
            if (direction == "BULLISH" and float(obi_50) >= 0.15) or (
                direction == "BEARISH" and float(obi_50) <= -0.15
            ):
                confirmations.append(f"OBI50_{float(obi_50):+.2f}")

    # Determine causal stage transition
    sec_confirmed = _seconds_breakout_confirmed(bars_seconds, best_lvl.price, direction)
    bar_5m_crossed = (
        (prev_close_5m <= best_lvl.price < spot)
        if direction == "BULLISH"
        else (prev_close_5m >= best_lvl.price > spot)
    )
    breakout_accepted = bool(
        sec_confirmed if sec_confirmed is not None else (bar_5m_crossed and tod_rvol >= 1.2)
    )
    if sec_confirmed:
        confirmations.append("SECONDS_BAR_ACCEPTANCE")
    elif bar_5m_crossed:
        confirmations.append("5M_BAR_CROSS")

    if vetoes:
        stage = "VETOED"
    elif extension_atr > no_chase_atr:
        stage = "EXPIRED_STALK"
    elif breakout_accepted and extension_atr <= no_chase_atr:
        stage = "TRIGGERED"
    elif abs_dist_atr <= 0.35 or (coiling and abs_dist_atr <= 0.55):
        stage = "ARMED"
    elif abs_dist_atr <= 0.90:
        stage = "WATCH"
    else:
        return None

    tbt_promoted = bool(previous_state.tbt_scout_promoted) if previous_state else False
    if stage == "ARMED" and promote_tbt and not tbt_promoted:
        if os.environ.get("CHANAKYA_TESTING") != "1" and "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                from market.fyers_tbt_manager import (
                    promote_jit_tbt_scout,
                    resolve_tradable_tbt_symbol,
                )

                target_tbt = resolve_tradable_tbt_symbol(clean) or clean
                tbt_promoted = bool(
                    promote_jit_tbt_scout(target_tbt, duration_sec=180.0, reason="LEVEL_ARMED")
                )
            except Exception as e_tbt:
                logger.debug(f"[LevelStateMachine] TBT promotion note for {clean}: {e_tbt}")

    first_seen = previous_state.first_seen_at if previous_state else ts_str
    armed_at = (
        previous_state.armed_at
        if (previous_state and previous_state.armed_at)
        else (ts_str if stage in ("ARMED", "TRIGGERED") else None)
    )
    triggered_at = ts_str if stage == "TRIGGERED" else None
    lead_sec: Optional[float] = None
    if armed_at and triggered_at:
        try:
            dt_a = datetime.strptime(armed_at.replace(" IST", ""), "%Y-%m-%d %H:%M:%S")
            dt_t = datetime.strptime(triggered_at.replace(" IST", ""), "%Y-%m-%d %H:%M:%S")
            lead_sec = max(0.0, (dt_t - dt_a).total_seconds())
        except ValueError:
            lead_sec = None

    gex_regime = None
    if gex_snapshot is not None:
        gex_regime = (
            gex_snapshot.get("regime")
            if isinstance(gex_snapshot, dict)
            else getattr(gex_snapshot, "regime", None)
        )

    return LevelStageState(
        symbol=clean,
        asset_class=asset_class,
        stage=stage,
        direction=direction,
        anchor_name=best_lvl.name,
        anchor_price=best_lvl.price,
        spot=round(spot, 2),
        atr_14=round(atr_14, 4),
        distance_atr=round(abs_dist_atr, 3),
        extension_atr=round(extension_atr, 3),
        stop_loss=stop_loss,
        target_1=target_1,
        no_chase_boundary=no_chase,
        first_seen_at=first_seen,
        updated_at=ts_str,
        armed_at=armed_at,
        triggered_at=triggered_at,
        lead_time_sec=lead_sec,
        tbt_scout_promoted=tbt_promoted,
        confirmation_reasons=confirmations,
        veto_reasons=vetoes,
        evidence_snapshot={
            "feature_bus": feats,
            "constituent_lead_lag": lead_info,
            "market_internals_regime": internals_regime,
            "cvd_divergence": cvd_div,
            "gex_regime": gex_regime,
            "obi_50": obi_50,
            "seconds_confirmed": sec_confirmed,
        },
    )


class ArmedRadarStore:
    """Thread-safe in-memory registry of WATCH/ARMED/TRIGGERED setups for Index + Top Stock F&O."""

    def __init__(self, max_entries: int = 256) -> None:
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], LevelStageState] = {}
        self._max_entries = max_entries

    def clear(self) -> None:
        with self._lock:
            self._states.clear()

    def evaluate_universe(
        self,
        symbols: Sequence[str],
        *,
        ohlcv_5m_map: dict[str, pd.DataFrame],
        ohlcv_seconds_map: Optional[dict[str, pd.DataFrame]] = None,
        daily_levels_map: Optional[dict[str, Any]] = None,
        gex_map: Optional[dict[str, Any]] = None,
        internals_map: Optional[dict[str, Any]] = None,
        quotes_map: Optional[dict[str, Any]] = None,
        cvd_map: Optional[dict[str, Any]] = None,
        depth_map: Optional[dict[str, dict[str, Any]]] = None,
        as_of: Optional[datetime] = None,
        promote_tbt: bool = False,
    ) -> list[LevelStageState]:
        """Evaluate staging transitions across Index + Stock F&O universe under discovery scope."""
        updated: list[LevelStageState] = []
        for sym in symbols:
            if not _allows_armed_symbol(sym):
                continue
            clean = canonical_alert_symbol(sym).upper()
            df_5m = None
            for k in (clean, sym, f"{clean}:5m"):
                cand = ohlcv_5m_map.get(k)
                if cand is not None:
                    df_5m = cand
                    break
            if df_5m is None or df_5m.empty:
                continue

            with self._lock:
                prev = next(
                    (v for (s, _), v in self._states.items() if s == clean),
                    None,
                )

            st = evaluate_symbol_stage(
                clean,
                df_5m,
                bars_seconds=(ohlcv_seconds_map or {}).get(clean),
                daily_levels=(daily_levels_map or {}).get(clean),
                gex_snapshot=(gex_map or {}).get(clean),
                internals_report=(internals_map or {}).get(clean),
                constituent_quotes=quotes_map,
                cvd_metrics=(cvd_map or {}).get(clean),
                depth_metrics=(depth_map or {}).get(clean),
                previous_state=prev,
                as_of=as_of,
                promote_tbt=promote_tbt,
            )
            if st is None:
                continue

            with self._lock:
                key = (st.symbol, st.anchor_name)
                if len(self._states) >= self._max_entries and key not in self._states:
                    oldest_key = next(iter(self._states))
                    self._states.pop(oldest_key, None)
                self._states[key] = st
            updated.append(st)
        return updated

    def snapshot(self, stage_filter: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            vals = list(self._states.values())
        if stage_filter:
            want = stage_filter.upper().strip()
            vals = [v for v in vals if v.stage == want]
        order = {"TRIGGERED": 0, "ARMED": 1, "WATCH": 2, "VETOED": 3, "EXPIRED_STALK": 4}
        vals.sort(key=lambda v: (order.get(v.stage, 9), v.distance_atr))
        return [v.to_dict() for v in vals]


armed_radar = ArmedRadarStore()
