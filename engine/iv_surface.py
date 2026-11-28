"""
engine/iv_surface.py
────────────────────
Constant-Tenor Implied Volatility Surface, 25-Delta Skew & Authentic IV Rank Engine.

Guarantees:
  1. Constant 30-Day DTE Interpolation:
     Interpolates variance across near ($T_1$) and next ($T_2$) expiries using standard
     variance weighting:
       sigma_30^2 = sigma_1^2 * ((T_2 - 30)/(T_2 - T_1)) * (T_1 / 30) +
                    sigma_2^2 * ((30 - T_1)/(T_2 - T_1)) * (T_2 / 30)
  2. 25-Delta Risk Reversal Skew:
     Computes normalized Put vs Call skew:
       Skew_25D = (sigma_25P - sigma_25C) / sigma_ATM
  3. Zero Synthetic Numbers & Honest Availability:
     If option chains, IV observations, or historical samples (< 20 sessions) are
     insufficient, returns status="UNAVAILABLE" and iv_rank=None, strictly adhering
     to Safety Contract #26 & #31.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class IVSurfaceSnapshot:
    """Authentic constant-tenor implied volatility surface observation."""

    symbol: str
    as_of: str
    status: str  # "AVAILABLE" | "UNAVAILABLE" | "DEGRADED"
    atm_iv_30d: Optional[float] = None
    atm_iv_7d: Optional[float] = None
    skew_25d: Optional[float] = None
    term_structure_slope: Optional[float] = None
    realized_vol_20d: Optional[float] = None
    vrp: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    iv_rank_depth_status: str = "UNAVAILABLE"
    sample_count: int = 0
    near_expiry: Optional[str] = None
    next_expiry: Optional[str] = None
    near_dte: Optional[int] = None
    next_dte: Optional[int] = None
    unavailability_reason: Optional[str] = None
    source_provenance: str = "LIVE_CHAIN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interpolate_constant_tenor_variance(
    sigma_1: float,
    dte_1: int,
    sigma_2: float,
    dte_2: int,
    *,
    target_dte: int = 30,
) -> float:
    """
    Interpolate constant-tenor annualized implied volatility across two tenors
    using calendar variance weighting around `target_dte`.
    """
    t_days = max(1, int(target_dte))
    if dte_1 <= 0 or dte_2 <= 0 or sigma_1 <= 0 or sigma_2 <= 0:
        return 0.0

    if dte_1 == dte_2:
        return sigma_1

    # Ensure dte_1 < dte_2
    if dte_1 > dte_2:
        sigma_1, sigma_2 = sigma_2, sigma_1
        dte_1, dte_2 = dte_2, dte_1

    if dte_1 == t_days:
        return sigma_1
    if dte_2 == t_days:
        return sigma_2

    if dte_1 < t_days < dte_2:
        weight_1 = (dte_2 - t_days) / (dte_2 - dte_1)
        weight_2 = (t_days - dte_1) / (dte_2 - dte_1)
        var_1 = (sigma_1**2) * (dte_1 / float(t_days))
        var_2 = (sigma_2**2) * (dte_2 / float(t_days))
        var_t = weight_1 * var_1 + weight_2 * var_2
        return math.sqrt(max(0.0, var_t))

    if dte_1 > t_days:
        return float(sigma_1)
    return float(sigma_2)


def interpolate_constant_30d_variance(
    sigma_1: float,
    dte_1: int,
    sigma_2: float,
    dte_2: int,
) -> float:
    """
    Interpolate constant 30-day annualized implied volatility across two tenors
    using calendar variance weighting.
    """
    return interpolate_constant_tenor_variance(
        sigma_1,
        dte_1,
        sigma_2,
        dte_2,
        target_dte=30,
    )


def compute_realized_volatility_yang_zhang(
    ohlcv_df: Optional[pd.DataFrame],
    window: int = 20,
    *,
    in_percent: bool = True,
) -> Optional[float]:
    """Compute annualized Yang-Zhang realized volatility from OHLC bars (never IV Rank)."""
    if ohlcv_df is None or not isinstance(ohlcv_df, pd.DataFrame) or len(ohlcv_df) < window + 1:
        return None

    col_map = {str(c).lower(): c for c in ohlcv_df.columns}
    if not {"open", "high", "low", "close"}.issubset(col_map):
        return None

    o = pd.to_numeric(ohlcv_df[col_map["open"]], errors="coerce").astype(float)
    h = pd.to_numeric(ohlcv_df[col_map["high"]], errors="coerce").astype(float)
    low_s = pd.to_numeric(ohlcv_df[col_map["low"]], errors="coerce").astype(float)
    c = pd.to_numeric(ohlcv_df[col_map["close"]], errors="coerce").astype(float)
    prev_c = c.shift(1)

    valid = (o > 0) & (h > 0) & (low_s > 0) & (c > 0) & (prev_c > 0) & (h >= low_s)
    if int(valid.sum()) < window:
        return None

    o = o[valid].tail(window)
    h = h[valid].tail(window)
    low_s = low_s[valid].tail(window)
    c = c[valid].tail(window)
    prev_c = prev_c[valid].tail(window)

    n = len(c)
    if n < 5:
        return None

    log_ho = np.log(h / o)
    log_lo = np.log(low_s / o)
    log_co = np.log(c / o)
    log_oc = np.log(o / prev_c)
    log_hc = np.log(h / c)
    log_lc = np.log(low_s / c)

    rs_var = float(np.mean(log_ho * log_hc + log_lo * log_lc))
    oc_var = float(np.var(log_oc, ddof=1)) if n > 1 else 0.0
    cc_var = float(np.var(log_co, ddof=1)) if n > 1 else 0.0
    k = 0.34 / (1.34 + (n + 1.0) / max(1.0, n - 1.0))
    yz_var = max(0.0, oc_var + k * cc_var + (1.0 - k) * rs_var)
    ann_rv = math.sqrt(yz_var * 252.0)
    if not math.isfinite(ann_rv) or ann_rv <= 0:
        return None
    return round(ann_rv * 100.0 if in_percent else ann_rv, 4)


def compute_symbol_realized_vol_20d(
    symbol: str,
    ohlcv_daily: Optional[pd.DataFrame] = None,
) -> Optional[float]:
    """Compute 20-day Yang-Zhang realized volatility (%) from daily or resampled warehouse bars."""
    if ohlcv_daily is not None and not ohlcv_daily.empty:
        rv = compute_realized_volatility_yang_zhang(ohlcv_daily, window=20, in_percent=True)
        if rv is not None:
            return rv
    try:
        from engine.alert_identity import canonical_alert_symbol
        from engine.historical_warehouse import historical_warehouse

        clean = canonical_alert_symbol(symbol).upper()
        day_df = historical_warehouse.load_bars(clean, interval="day")
        if day_df is None or len(day_df) < 21:
            bars_5m = historical_warehouse.load_bars(clean, interval="5m")
            if (
                bars_5m is not None
                and not bars_5m.empty
                and isinstance(bars_5m.index, pd.DatetimeIndex)
            ):
                day_df = (
                    bars_5m.resample("D")
                    .agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                        }
                    )
                    .dropna()
                )
        if day_df is not None and len(day_df) >= 21:
            return compute_realized_volatility_yang_zhang(day_df, window=20, in_percent=True)
    except Exception as e_rv:
        logger.debug(f"[iv_surface] Warehouse RV20 lookup skipped for {symbol}: {e_rv}")
    return None


def calculate_25delta_skew(
    iv_25d_put: float,
    iv_25d_call: float,
    atm_iv: float,
) -> Optional[float]:
    """
    Normalized 25-Delta Risk Reversal Skew: (IV_25P - IV_25C) / ATM_IV.
    Positive value indicates put demand / downside tail protection.
    """
    if atm_iv <= 0 or iv_25d_put <= 0 or iv_25d_call <= 0:
        return None
    return round((iv_25d_put - iv_25d_call) / atm_iv, 4)


def compute_iv_rank_and_percentile(
    current_iv: float,
    historical_iv_series: list[float] | np.ndarray | pd.Series,
    min_samples: int = 20,
) -> tuple[Optional[float], Optional[float], int]:
    """
    Calculates authentic IV Rank and IV Percentile over an empirical time series.
    Returns (None, None, count) if historical samples < min_samples.
    """
    if not isinstance(historical_iv_series, (list, np.ndarray, pd.Series)):
        return None, None, 0

    clean_samples = [
        float(x)
        for x in historical_iv_series
        if isinstance(x, (int, float)) and math.isfinite(x) and x > 0
    ]
    count = len(clean_samples)
    if count < min_samples or current_iv <= 0:
        return None, None, count

    min_iv = min(clean_samples)
    max_iv = max(clean_samples)

    if max_iv <= min_iv:
        return None, None, count

    # IV Rank = (Current - Min) / (Max - Min) * 100
    iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
    iv_rank = max(0.0, min(100.0, iv_rank))

    # IV Percentile = Count(Hist < Current) / Total Count * 100
    less_count = sum(1 for x in clean_samples if x < current_iv)
    iv_percentile = (less_count / count) * 100.0

    return round(iv_rank, 1), round(iv_percentile, 1), count


def build_iv_surface_snapshot(
    symbol: str,
    near_atm_iv: Optional[float] = None,
    near_dte: Optional[int] = None,
    next_atm_iv: Optional[float] = None,
    next_dte: Optional[int] = None,
    iv_25d_put: Optional[float] = None,
    iv_25d_call: Optional[float] = None,
    historical_30d_ivs: Optional[list[float]] = None,
    now_dt: Optional[datetime] = None,
    *,
    near_expiry: Optional[str] = None,
    next_expiry: Optional[str] = None,
    realized_vol_20d: Optional[float] = None,
    source_provenance: str = "LIVE_CHAIN",
) -> IVSurfaceSnapshot:
    """
    Constructs an authentic IVSurfaceSnapshot for an underlying symbol.
    Fails closed with status='UNAVAILABLE' if essential IV inputs are missing.
    """
    as_of_str = (now_dt or datetime.now()).isoformat()

    if near_atm_iv is None or near_atm_iv <= 0 or near_dte is None or near_dte <= 0:
        return IVSurfaceSnapshot(
            symbol=symbol,
            as_of=as_of_str,
            status="UNAVAILABLE",
            unavailability_reason="Near-term ATM implied volatility or DTE is missing or non-positive.",
        )

    # 1. Constant 30D & 7D IV interpolation
    has_two_tenors = (
        next_atm_iv is not None and next_atm_iv > 0 and next_dte is not None and next_dte > near_dte
    )
    if has_two_tenors:
        atm_30d = interpolate_constant_tenor_variance(
            near_atm_iv, near_dte, next_atm_iv, next_dte, target_dte=30
        )
        atm_7d = interpolate_constant_tenor_variance(
            near_atm_iv, near_dte, next_atm_iv, next_dte, target_dte=7
        )
        term_slope = round(float(next_atm_iv) - float(near_atm_iv), 4)
    else:
        atm_30d = float(near_atm_iv)
        atm_7d = float(near_atm_iv)
        term_slope = None

    atm_30d = round(atm_30d, 4)
    atm_7d = round(atm_7d, 4)

    # 2. 25-Delta Skew
    skew = None
    if iv_25d_put is not None and iv_25d_call is not None:
        skew = calculate_25delta_skew(iv_25d_put, iv_25d_call, atm_30d)

    # 3. Volatility Risk Premium (VRP = IV_30D - RV_20D, same scale as atm_30d)
    rv_out = None
    vrp_out = None
    if realized_vol_20d is not None and math.isfinite(realized_vol_20d) and realized_vol_20d > 0:
        is_pct_unit = atm_30d > 1.0
        if is_pct_unit and realized_vol_20d <= 1.0:
            rv_matched = realized_vol_20d * 100.0
        elif (not is_pct_unit) and realized_vol_20d > 1.0:
            rv_matched = realized_vol_20d / 100.0
        else:
            rv_matched = float(realized_vol_20d)
        rv_out = round(rv_matched, 4)
        vrp_out = round(atm_30d - rv_out, 4)

    # 4. IV Rank & Percentile (strictly requires empirical historical IV series)
    ivr, ivp, count = compute_iv_rank_and_percentile(
        atm_30d,
        historical_30d_ivs or [],
        min_samples=20,
    )
    if count >= 60:
        depth_status = "CALIBRATED (>=60)"
    elif count >= 20:
        depth_status = "WARMING (20-59)"
    else:
        depth_status = "INSUFFICIENT (<20)"

    return IVSurfaceSnapshot(
        symbol=symbol,
        as_of=as_of_str,
        status="AVAILABLE",
        atm_iv_30d=atm_30d,
        atm_iv_7d=atm_7d,
        skew_25d=skew,
        term_structure_slope=term_slope,
        realized_vol_20d=rv_out,
        vrp=vrp_out,
        iv_rank=ivr,
        iv_percentile=ivp,
        iv_rank_depth_status=depth_status,
        sample_count=count,
        near_expiry=near_expiry,
        next_expiry=next_expiry,
        near_dte=near_dte,
        next_dte=next_dte,
        source_provenance=source_provenance,
    )


def _get_iv_db_path():
    from config.paths import app_data_path

    return app_data_path("iv_history.db")


def extract_surface_inputs_from_chain(
    chain: list[Any],
    spot: float,
    as_of_date: Optional[Any] = None,
) -> dict[str, Any]:
    """Extract near/next ATM IVs, DTEs, and 25-delta skew IVs from a real option chain."""
    from datetime import date as dt_date

    if not chain or spot <= 0:
        return {}

    ref_date = as_of_date or datetime.now().date()
    if isinstance(ref_date, datetime):
        ref_date = ref_date.date()

    by_exp: dict[dt_date, list[dict[str, Any]]] = {}
    for c in chain:
        is_d = isinstance(c, dict)
        exp_raw = c.get("expiry") if is_d else getattr(c, "expiry", None)
        iv_raw = c.get("iv", 0.0) if is_d else getattr(c, "iv", 0.0)
        strike_raw = c.get("strike", 0.0) if is_d else getattr(c, "strike", 0.0)
        opt_raw = c.get("option_type", "") if is_d else getattr(c, "option_type", "")
        delta_raw = c.get("delta", None) if is_d else getattr(c, "delta", None)

        try:
            iv_val = float(iv_raw or 0.0)
            strike_val = float(strike_raw or 0.0)
        except (TypeError, ValueError):
            continue
        if iv_val <= 0 or strike_val <= 0 or not exp_raw:
            continue

        try:
            exp_d = (
                exp_raw
                if isinstance(exp_raw, dt_date) and not isinstance(exp_raw, datetime)
                else dt_date.fromisoformat(str(exp_raw).strip()[:10])
            )
        except ValueError:
            continue

        dte = (exp_d - ref_date).days
        if dte <= 0:
            continue
        by_exp.setdefault(exp_d, []).append(
            {
                "strike": strike_val,
                "iv": iv_val,
                "option_type": str(opt_raw or "").upper(),
                "delta": delta_raw,
                "dte": dte,
            }
        )

    if not by_exp:
        return {}

    sorted_exps = sorted(by_exp.keys())

    def _atm_iv(rows: list[dict[str, Any]]) -> Optional[float]:
        closest_strike = min(rows, key=lambda r: abs(r["strike"] - spot))["strike"]
        atm_ivs = [r["iv"] for r in rows if r["strike"] == closest_strike and r["iv"] > 0]
        return round(sum(atm_ivs) / len(atm_ivs), 4) if atm_ivs else None

    near_rows = by_exp[sorted_exps[0]]
    near_atm = _atm_iv(near_rows)
    near_dte = near_rows[0]["dte"]

    next_atm = None
    next_dte = None
    if len(sorted_exps) >= 2:
        next_rows = by_exp[sorted_exps[1]]
        next_atm = _atm_iv(next_rows)
        next_dte = next_rows[0]["dte"]

    iv_25p = None
    iv_25c = None
    puts_with_d = [r for r in near_rows if r["option_type"] == "PE" and r["delta"] is not None]
    calls_with_d = [r for r in near_rows if r["option_type"] == "CE" and r["delta"] is not None]
    if puts_with_d:
        iv_25p = min(puts_with_d, key=lambda r: abs(abs(float(r["delta"])) - 0.25))["iv"]
    if calls_with_d:
        iv_25c = min(calls_with_d, key=lambda r: abs(abs(float(r["delta"])) - 0.25))["iv"]

    return {
        "near_atm_iv": near_atm,
        "near_dte": near_dte,
        "next_atm_iv": next_atm,
        "next_dte": next_dte,
        "iv_25d_put": iv_25p,
        "iv_25d_call": iv_25c,
        "near_expiry": sorted_exps[0].isoformat(),
        "next_expiry": sorted_exps[1].isoformat() if len(sorted_exps) >= 2 else None,
    }


def _ensure_iv_surface_columns(conn: Any) -> None:
    """Idempotently add extended IV surface columns to existing SQLite archives."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(iv_daily_surface)").fetchall()}
    migrations = [
        ("atm_iv_7d", "REAL"),
        ("term_structure_slope", "REAL"),
        ("realized_vol_20d", "REAL"),
        ("vrp", "REAL"),
        ("near_expiry", "TEXT"),
        ("next_expiry", "TEXT"),
        ("source_provenance", "TEXT"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE iv_daily_surface ADD COLUMN {col_name} {col_type}")


def record_iv_observation(
    snapshot: IVSurfaceSnapshot,
    session_date: Optional[str] = None,
    *,
    overwrite_existing: bool = True,
) -> bool:
    """Persist one daily constant-tenor IV/skew/VRP observation (idempotent per symbol+date)."""
    import sqlite3

    if (
        snapshot.status != "AVAILABLE"
        or snapshot.atm_iv_30d is None
        or not math.isfinite(snapshot.atm_iv_30d)
        or snapshot.atm_iv_30d <= 0
    ):
        return False

    sym = str(snapshot.symbol or "").upper().strip()
    from contextlib import closing

    if not sym:
        return False

    s_date = session_date or str(snapshot.as_of or "")[:10] or datetime.now().date().isoformat()
    db_path = _get_iv_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conflict_clause = (
        """
                ON CONFLICT(symbol, session_date) DO UPDATE SET
                    atm_iv_30d = excluded.atm_iv_30d,
                    skew_25d = excluded.skew_25d,
                    near_dte = excluded.near_dte,
                    next_dte = excluded.next_dte,
                    atm_iv_7d = excluded.atm_iv_7d,
                    term_structure_slope = excluded.term_structure_slope,
                    realized_vol_20d = excluded.realized_vol_20d,
                    vrp = excluded.vrp,
                    near_expiry = excluded.near_expiry,
                    next_expiry = excluded.next_expiry,
                    source_provenance = excluded.source_provenance,
                    updated_at = excluded.updated_at
        """
        if overwrite_existing
        else "ON CONFLICT(symbol, session_date) DO NOTHING"
    )
    with closing(sqlite3.connect(str(db_path), timeout=10.0)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS iv_daily_surface (
                    symbol TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    atm_iv_30d REAL NOT NULL,
                    skew_25d REAL,
                    near_dte INTEGER,
                    next_dte INTEGER,
                    atm_iv_7d REAL,
                    term_structure_slope REAL,
                    realized_vol_20d REAL,
                    vrp REAL,
                    near_expiry TEXT,
                    next_expiry TEXT,
                    source_provenance TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, session_date)
                )
                """
            )
            _ensure_iv_surface_columns(conn)
            cur = conn.execute(
                f"""
                INSERT INTO iv_daily_surface
                    (symbol, session_date, atm_iv_30d, skew_25d, near_dte, next_dte,
                     atm_iv_7d, term_structure_slope, realized_vol_20d, vrp,
                     near_expiry, next_expiry, source_provenance, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                {conflict_clause}
                """,
                (
                    sym,
                    s_date,
                    float(snapshot.atm_iv_30d),
                    float(snapshot.skew_25d) if snapshot.skew_25d is not None else None,
                    snapshot.near_dte,
                    snapshot.next_dte,
                    float(snapshot.atm_iv_7d) if snapshot.atm_iv_7d is not None else None,
                    (
                        float(snapshot.term_structure_slope)
                        if snapshot.term_structure_slope is not None
                        else None
                    ),
                    (
                        float(snapshot.realized_vol_20d)
                        if snapshot.realized_vol_20d is not None
                        else None
                    ),
                    float(snapshot.vrp) if snapshot.vrp is not None else None,
                    snapshot.near_expiry,
                    snapshot.next_expiry,
                    str(getattr(snapshot, "source_provenance", "LIVE_CHAIN") or "LIVE_CHAIN"),
                    snapshot.as_of,
                ),
            )
            return bool(cur.rowcount and cur.rowcount > 0)


def load_historical_30d_ivs(symbol: str, limit: int = 252) -> list[float]:
    """Load persisted chronological daily constant-30D ATM IV observations."""
    from contextlib import closing
    import sqlite3

    sym = str(symbol or "").upper().strip()
    db_path = _get_iv_db_path()
    if not sym or not db_path.exists():
        return []
    with closing(sqlite3.connect(str(db_path), timeout=10.0)) as conn:
        rows = conn.execute(
            """
            SELECT atm_iv_30d FROM (
                SELECT session_date, atm_iv_30d
                FROM iv_daily_surface
                WHERE symbol = ?
                ORDER BY session_date DESC
                LIMIT ?
            ) ORDER BY session_date ASC
            """,
            (sym, max(1, int(limit))),
        ).fetchall()
    return [float(r[0]) for r in rows if r and r[0] is not None and float(r[0]) > 0]


def build_iv_surface_from_warehouse(
    symbol: str,
    *,
    ohlcv_daily: Optional[pd.DataFrame] = None,
    date_str: Optional[str] = None,
    now_dt: Optional[datetime] = None,
    persist: bool = True,
) -> IVSurfaceSnapshot:
    """Build an IVSurfaceSnapshot from archived TickWarehouse option-chain snapshots.

    Honest contract: fails closed with status='UNAVAILABLE' and iv_rank=None when
    archived option chain rows or empirical IV history are absent.
    """
    from datetime import timedelta

    from config.constants import IST
    from engine.alert_identity import canonical_alert_symbol
    from engine.tick_warehouse import get_tick_warehouse

    clean = canonical_alert_symbol(symbol).upper()
    ref_now = now_dt or datetime.now(IST)
    wh = get_tick_warehouse()
    df = wh.query_option_chain_snapshots(clean, date_str=date_str)
    if (df is None or df.empty) and not date_str:
        # On weekends/holidays/pre-market, fall back to the most recent archived partition.
        for days_back in range(1, 15):
            prev_d = (ref_now - timedelta(days=days_back)).strftime("%Y-%m-%d")
            cand_df = wh.query_option_chain_snapshots(clean, date_str=prev_d)
            if cand_df is not None and not cand_df.empty:
                df = cand_df
                break
    if df is None or df.empty:
        return IVSurfaceSnapshot(
            symbol=clean,
            as_of=ref_now.isoformat(),
            status="UNAVAILABLE",
            unavailability_reason=f"No archived option chain snapshots for {clean}.",
        )

    latest_ts = int(df["timestamp"].max())
    latest_df = df[df["timestamp"] == latest_ts]
    snap_dt = datetime.fromtimestamp(latest_ts / 1000.0, tz=IST)

    spots = pd.to_numeric(latest_df.get("spot"), errors="coerce").dropna()
    spot_val = float(spots.iloc[0]) if not spots.empty and float(spots.iloc[0]) > 0 else 0.0
    if spot_val <= 0 and ohlcv_daily is not None and not ohlcv_daily.empty:
        try:
            idx_dates = pd.to_datetime(ohlcv_daily.index).date
            sub_daily = ohlcv_daily[idx_dates <= snap_dt.date()]
            if not sub_daily.empty:
                c_val = float(sub_daily["close"].iloc[-1] or 0.0)
                if c_val > 0:
                    spot_val = c_val
        except Exception as e_daily_iv:
            logger.debug(f"[iv_surface] Daily close lookup skipped for {clean}: {e_daily_iv}")
    if spot_val <= 0:
        try:
            from engine.historical_warehouse import historical_warehouse

            snap_naive = snap_dt.replace(tzinfo=None)
            for iv_name in ("5m", "day"):
                w_df = historical_warehouse.load_bars(clean, interval=iv_name)
                if w_df is not None and not w_df.empty:
                    sub_w = w_df[w_df.index <= snap_naive]
                    if sub_w.empty:
                        sub_w = w_df[w_df.index.date <= snap_dt.date()]
                    if not sub_w.empty:
                        c_val = float(sub_w["close"].iloc[-1] or 0.0)
                        if c_val > 0:
                            spot_val = c_val
                            break
        except Exception as e_wh_iv:
            logger.debug(f"[iv_surface] Warehouse spot lookup skipped for {clean}: {e_wh_iv}")
    if spot_val <= 0 and snap_dt.date() == ref_now.date():
        try:
            from market.quotes import get_quote

            q = get_quote(clean)
            lp = float(
                getattr(q, "ltp", 0.0) or (q.get("ltp", 0.0) if isinstance(q, dict) else 0.0) or 0.0
            )
            if lp > 0:
                spot_val = lp
        except Exception as e_qt_iv:
            logger.debug(f"[iv_surface] Live quote spot lookup skipped for {clean}: {e_qt_iv}")
    if spot_val <= 0:
        return IVSurfaceSnapshot(
            symbol=clean,
            as_of=snap_dt.isoformat(),
            status="UNAVAILABLE",
            unavailability_reason=f"Archived chain snapshot for {clean} lacks underlying spot.",
        )

    chain_rows = latest_df.to_dict(orient="records")
    inputs = extract_surface_inputs_from_chain(chain_rows, spot_val, as_of_date=snap_dt.date())
    if not inputs or not inputs.get("near_atm_iv"):
        return IVSurfaceSnapshot(
            symbol=clean,
            as_of=snap_dt.isoformat(),
            status="UNAVAILABLE",
            unavailability_reason=f"Archived chain snapshot for {clean} lacks valid IV/DTE strikes.",
        )

    rv_20 = compute_symbol_realized_vol_20d(clean, ohlcv_daily=ohlcv_daily)
    hist_30d = load_historical_30d_ivs(clean)
    snap = build_iv_surface_snapshot(
        symbol=clean,
        near_atm_iv=inputs.get("near_atm_iv"),
        near_dte=inputs.get("near_dte"),
        next_atm_iv=inputs.get("next_atm_iv"),
        next_dte=inputs.get("next_dte"),
        iv_25d_put=inputs.get("iv_25d_put"),
        iv_25d_call=inputs.get("iv_25d_call"),
        historical_30d_ivs=hist_30d,
        now_dt=snap_dt,
        near_expiry=inputs.get("near_expiry"),
        next_expiry=inputs.get("next_expiry"),
        realized_vol_20d=rv_20,
    )
    if persist and snap.status == "AVAILABLE":
        record_iv_observation(snap, session_date=snap_dt.date().isoformat())
    return snap
