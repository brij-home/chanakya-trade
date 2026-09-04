"""
market/history.py
─────────────────
Historical OHLCV data. Fetches via the active broker (Zerodha/Groww/Mock).
Returns pandas DataFrames for downstream analysis.

Intervals supported (Zerodha notation):
    "minute", "3minute", "5minute", "10minute", "15minute",
    "30minute", "60minute", "day"
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


# ── Interval aliases ─────────────────────────────────────────

INTERVAL_MAP = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "60m": "60minute",
    "1d": "day",
    "day": "day",
    "1w": "week",
    "1wk": "week",
    "week": "week",
    "1M": "month",
    "1mo": "month",
    "month": "month",
}


import time
import threading

_df_memory_cache_lock = threading.Lock()
_df_memory_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_DF_TTL_SECONDS = 300.0  # 5 minutes in-memory cache


def get_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "day",
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    days: int = 365,
    *,
    as_of: Optional[datetime] = None,
    include_live_candle: bool = False,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV data as a DataFrame.

    Args:
        symbol:    Trading symbol e.g. "RELIANCE", "NIFTY 50"
        exchange:  "NSE" | "BSE" | "NFO" | "MCX"
        interval:  Candle size — "day", "1h", "15m", "5m", "1m" etc.
        from_date: Start date (default: today - days)
        to_date:   End date (default: today)
        days:      Lookback in days if from_date not given (max 2000 for day)
        as_of:     Explicit historical cutoff for a reproducible research run.
        include_live_candle: Explicitly add/refresh today's incomplete candle.
            This is disabled by default so backtests never blend live and EOD data.

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
        Index: date (datetime)
    """
    # Normalize interval alias
    kite_interval = INTERVAL_MAP.get(interval, interval)
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    effective_to = as_of or to_date
    cutoff_key = effective_to.strftime("%Y%m%d%H%M%S") if effective_to else "latest"
    cache_key = f"{clean_sym}_{exchange.upper()}_{kite_interval}_{days}_{cutoff_key}_{int(include_live_candle)}"
    now_ts = time.time()

    # Tier 1: Instant In-Memory DataFrame Cache (0.1ms latency)
    if kite_interval == "day" and not from_date and not to_date:
        with _df_memory_cache_lock:
            if cache_key in _df_memory_cache:
                stored_ts, cached_df = _df_memory_cache[cache_key]
                if now_ts - stored_ts < _DF_TTL_SECONDS and not cached_df.empty:
                    return cached_df.copy()

    to_date = effective_to or datetime.now()
    from_date = from_date or (to_date - timedelta(days=days))

    # Tier 2: Fast SQLite analysis_cache for recent daily candles (15m TTL)
    raw = None
    if kite_interval == "day":
        try:
            from engine.analysis_cache import cache_get

            cached_rows = cache_get(f"ohlcv_{cache_key}", namespace="history", max_age_seconds=900)
            if cached_rows and isinstance(cached_rows, list) and len(cached_rows) >= 10:
                raw = cached_rows
        except Exception:
            pass

    provider_name = "cache"
    snapshot_id: Optional[str] = None

    # A requested as-of daily analysis must replay a stored snapshot if one is
    # available.  It must not silently re-fetch changed vendor history.
    canonical_id = None
    if kite_interval == "day":
        try:
            from market.eod_store import load_eod_snapshot
            from market.instruments import resolve_canonical_instrument

            canonical_id = resolve_canonical_instrument(f"{exchange}:{clean_sym}").instrument_id
            snapshot = load_eod_snapshot(
                canonical_id,
                as_of_date=to_date.date().isoformat() if as_of else None,
            )
            if snapshot and as_of:
                raw = snapshot["rows"]
                provider_name = snapshot["provider"]
                snapshot_id = snapshot["snapshot_id"]
        except Exception:
            pass

    # Tier 3: explicit data-provider API → yfinance → disk cache.
    if not raw:
        try:
            from brokers.session import get_data_broker, get_data_broker_key

            broker = get_data_broker()
            # Only use broker for real data — skip if it's the mock broker
            if not getattr(broker, "_is_mock", False):
                raw = broker.get_historical_data(
                    symbol=symbol,
                    exchange=exchange,
                    interval=kite_interval,
                    from_date=from_date,
                    to_date=to_date,
                )
                provider_name = get_data_broker_key() or broker.__class__.__name__.lower()
            else:
                # Mock broker: use yfinance
                raw = _yfinance_fallback(symbol, exchange, kite_interval, from_date, to_date)
                provider_name = "yfinance"
        except Exception:
            pass

    if not raw:
        raw = _yfinance_fallback(symbol, exchange, kite_interval, from_date, to_date)
        provider_name = "yfinance"
        # Cache successful daily fetches to disk for offline fallback
        if raw and kite_interval == "day":
            save_ohlcv_cache(f"ohlcv_{symbol}", raw)

    if not raw:
        # Tier 4: disk cache — last-resort when both broker and yfinance fail
        raw, _ = load_ohlcv_cache(f"ohlcv_{symbol}")
        provider_name = "disk_cache"

    # Persist in SQLite cache for 15 minutes
    if raw and kite_interval == "day" and len(raw) >= 10:
        try:
            from engine.analysis_cache import cache_set

            cache_set(f"ohlcv_{cache_key}", raw, namespace="history", ttl_minutes=15)
        except Exception:
            pass

        # Persist an immutable local EOD snapshot for later reproducible runs.
        try:
            from market.eod_store import save_eod_snapshot
            from market.instruments import resolve_canonical_instrument

            canonical_id = (
                canonical_id
                or resolve_canonical_instrument(f"{exchange}:{clean_sym}").instrument_id
            )
            snapshot_id = save_eod_snapshot(
                canonical_instrument_id=canonical_id,
                provider=provider_name,
                provider_symbol=f"{exchange}:{clean_sym}",
                as_of_date=to_date.date().isoformat(),
                rows=raw,
                data_quality="DELAYED"
                if provider_name in {"yfinance", "disk_cache"}
                else "VERIFIED",
            )
        except Exception:
            pass

    if not raw:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(raw)
    df.rename(columns={"date": "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df.set_index("date", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")]
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df.sort_index(inplace=True)

    # Live/incomplete candle enrichment is opt-in and is never cached as EOD.
    if include_live_candle and kite_interval == "day" and not df.empty:
        df = inject_live_tick(df, symbol=symbol, exchange=exchange)

    df.attrs["provenance"] = {
        "data_source": "LIVE_ENRICHED" if include_live_candle else "HISTORICAL_EOD",
        "provider": provider_name,
        "as_of": to_date.isoformat(),
        "snapshot_id": snapshot_id,
        "reproducible": bool(snapshot_id) and not include_live_candle,
    }

    # Save into Tier 1 In-Memory Cache (bounded to 500 entries)
    if kite_interval == "day" and not df.empty:
        with _df_memory_cache_lock:
            if len(_df_memory_cache) > 500:
                # Prune entries older than _DF_TTL_SECONDS
                expired = [
                    k for k, (t, _) in _df_memory_cache.items() if now_ts - t > _DF_TTL_SECONDS
                ]
                for k in expired:
                    _df_memory_cache.pop(k, None)
                # If still over 500, drop oldest 100 entries
                if len(_df_memory_cache) > 500:
                    sorted_by_time = sorted(_df_memory_cache.items(), key=lambda item: item[1][0])
                    for k, _ in sorted_by_time[:100]:
                        _df_memory_cache.pop(k, None)
            _df_memory_cache[cache_key] = (now_ts, df.copy())

    return df


def inject_live_tick(
    df: pd.DataFrame,
    symbol: str,
    exchange: str = "NSE",
) -> pd.DataFrame:
    """
    Overlays the current second's live tick (LTP, Day High/Low, Volume) onto the OHLCV DataFrame.
    Ensures all quantitative models evaluate the latest real-time market state.
    """
    try:
        from market.quotes import get_quote

        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        inst = f"{exchange}:{symbol}"
        quotes = get_quote([inst])
        q = quotes.get(inst)
        if not q or q.last_price <= 0:
            return df

        now = datetime.now()
        today_date = pd.Timestamp(now.date())

        if df.empty:
            new_row = pd.DataFrame(
                [
                    {
                        "open": q.open or q.last_price,
                        "high": q.high or q.last_price,
                        "low": q.low or q.last_price,
                        "close": q.last_price,
                        "volume": q.volume or 0.0,
                    }
                ],
                index=[today_date],
            )
            return new_row

        last_idx = df.index[-1]
        last_date = pd.Timestamp(last_idx).date() if hasattr(last_idx, "date") else None

        if last_date == now.date():
            # Update today's existing candle with live tick
            df.loc[last_idx, "close"] = float(q.last_price)
            if q.high and q.high > 0:
                df.loc[last_idx, "high"] = max(float(df.loc[last_idx, "high"]), float(q.high))
            else:
                df.loc[last_idx, "high"] = max(float(df.loc[last_idx, "high"]), float(q.last_price))
            if q.low and q.low > 0:
                df.loc[last_idx, "low"] = min(float(df.loc[last_idx, "low"]), float(q.low))
            else:
                df.loc[last_idx, "low"] = min(float(df.loc[last_idx, "low"]), float(q.last_price))
            if q.volume and q.volume > 0:
                df.loc[last_idx, "volume"] = float(q.volume)
        else:
            # Append today's active bar
            new_row = pd.DataFrame(
                [
                    {
                        "open": float(q.open or q.last_price),
                        "high": float(q.high or q.last_price),
                        "low": float(q.low or q.last_price),
                        "close": float(q.last_price),
                        "volume": float(q.volume or 0.0),
                    }
                ],
                index=[today_date],
            )
            df = pd.concat([df, new_row])

        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return df
    except Exception:
        return df


def save_ohlcv_cache(key: str, data: list) -> None:
    """Save OHLCV rows to disk cache (daily interval only)."""
    from market.disk_cache import save_cache

    save_cache(key, data)


def load_ohlcv_cache(key: str) -> tuple[list, None]:
    """Load OHLCV rows from disk cache."""
    from market.disk_cache import load_cache

    return load_cache(key)


def _yfinance_fallback(
    symbol: str,
    exchange: str,
    interval: str,
    from_date: datetime,
    to_date: datetime,
) -> list[dict]:
    """Try yfinance for real market data when broker API is unavailable."""
    try:
        from market.yfinance_provider import yf_get_ohlcv, yf_available

        if not yf_available():
            return []
        return yf_get_ohlcv(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception:
        return []


def _get_instrument_token(symbol: str, exchange: str) -> int:
    """Look up instrument token from broker's instrument list."""
    from brokers.session import get_broker

    broker = get_broker()
    if not hasattr(broker, "kite"):
        return 0
    instruments = broker.kite.instruments(exchange)
    for inst in instruments:
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Instrument not found: {exchange}:{symbol}")


# NOTE: _mock_ohlcv and get_ohlcv_mock were removed.
# All market data now comes from real sources (broker API or yfinance).
# No synthetic/random data is ever served to users.

get_historical_data = get_ohlcv
