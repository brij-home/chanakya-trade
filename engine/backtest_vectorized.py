"""
engine/backtest_vectorized.py
──────────────────────────────
Vectorized backtesting engine for fast signal research (#158).

Uses pandas array operations — no bar-by-bar loop.
Trade-off: no slippage/fill simulation (use event-driven for final validation).

Target: <1 second for 1-year daily data.

Usage:
    from engine.backtest_vectorized import run_vectorized_backtest, vectorized_backtest
    import pandas as pd

    # With live data fetch:
    result = run_vectorized_backtest("RELIANCE", "rsi", "1y")

    # With pre-built DataFrame (for testing):
    result = vectorized_backtest(df, strategy_name="rsi", symbol="TEST")
"""

from __future__ import annotations
import logging

logger = logging.getLogger("engine.backtest_vectorized")


import math

import numpy as np
import pandas as pd

from engine.backtest import BacktestResult

# ── Data fetcher (thin shim — reuses yfinance or broker quotes) ─


def _fetch_ohlcv(symbol: str, period: str = "1y", exchange: str = "NSE") -> pd.DataFrame:
    """
    Fetch daily OHLCV data for the symbol.
    Returns a DataFrame indexed by date with columns: open, high, low, close, volume.
    Raises ValueError on empty result.
    """
    # Map period string to lookback days
    period_days = {
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 365,
        "2y": 730,
        "3y": 1095,
        "5y": 1825,
        "10y": 3650,
    }
    days = period_days.get(period, 365)

    # Tier 1: Try unified market.history get_ohlcv (which hits eod_store L1/L2 and local cache)
    try:
        from market.history import get_ohlcv

        df = get_ohlcv(symbol=symbol, exchange=exchange, interval="day", days=days)
        if df is not None and not df.empty and len(df) >= 15:
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            return df
    except Exception as e_suppressed:
        logger.debug(f"[engine.backtest_vectorized] Non-fatal exception suppressed: {e_suppressed}")

    # Tier 2: yfinance fallback
    try:
        import yfinance as yf

        suffix = ".NS" if exchange.upper() in ("NSE", "NFO") else ".BO"
        ticker = f"{symbol}{suffix}"
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        # yfinance may return MultiIndex columns like ('Close', 'INFY.NS') — flatten to plain strings
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if df.empty:
            raise ValueError(f"No data returned for {ticker}")
        return df
    except ImportError:
        raise ImportError("yfinance is required for vectorized backtest. Run: pip install yfinance")


# ── Signal generators ──────────────────────────────────────────


def _signals_rsi(
    close: pd.Series, period: int = 14, oversold: int = 30, overbought: int = 70
) -> pd.Series:
    """RSI strategy: buy on oversold→above cross, sell on overbought→below cross."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Signal: +1 = buy, -1 = sell, 0 = hold
    signal = pd.Series(0, index=close.index)
    signal[rsi > overbought] = -1  # sell/exit
    signal[rsi < oversold] = 1  # buy/enter
    return signal


def _signals_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9
) -> pd.Series:
    """MACD crossover: buy when MACD crosses above signal, sell on reverse."""
    ema_fast = close.ewm(span=fast, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal_period, min_periods=signal_period).mean()
    hist = macd - sig

    # Cross detection
    signal = pd.Series(0, index=close.index)
    signal[(hist > 0) & (hist.shift(1) <= 0)] = 1  # bullish cross
    signal[(hist < 0) & (hist.shift(1) >= 0)] = -1  # bearish cross
    return signal


def _signals_bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    """Bollinger Bands: buy when price crosses above lower band, sell on upper."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    lower = sma - std_dev * std
    upper = sma + std_dev * std

    signal = pd.Series(0, index=close.index)
    signal[(close < lower) & (close.shift(1) >= lower.shift(1))] = 1
    signal[(close > upper) & (close.shift(1) <= upper.shift(1))] = -1
    return signal


def _signals_ma_cross(close: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    """Moving average crossover: buy on fast>slow cross, sell on reverse."""
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()

    signal = pd.Series(0, index=close.index)
    signal[(ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))] = 1
    signal[(ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))] = -1
    return signal


_STRATEGY_MAP = {
    "rsi": _signals_rsi,
    "macd": _signals_macd,
    "bollinger": _signals_bollinger,
    "bb": _signals_bollinger,
    "ma": _signals_ma_cross,
    "ema": _signals_ma_cross,
}


# ── Metrics helpers ─────────────────────────────────────────────


def _calc_sharpe(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    """Annualised Sharpe ratio from daily returns."""
    excess = returns - risk_free / periods
    std = excess.std()
    if std == 0 or math.isnan(std):
        return 0.0
    return float((excess.mean() / std) * math.sqrt(periods))


def _calc_max_drawdown(equity: pd.Series) -> float:
    """Maximum drawdown as a negative percentage."""
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100
    return float(drawdown.min())


def _calc_cagr(total_return: float, years: float) -> float:
    """CAGR from total return % and holding years."""
    if years <= 0:
        return total_return
    return ((1 + total_return / 100) ** (1 / years) - 1) * 100


# ── Vectorized backtest core ────────────────────────────────────


def vectorized_backtest(
    df: pd.DataFrame,
    strategy_name: str = "rsi",
    symbol: str = "UNKNOWN",
    *,
    segment: str = "EQUITY_DELIVERY",
    slippage_bps: float = 5.0,
    include_charges: bool = True,
) -> BacktestResult:
    """
    Run genuinely vectorized NumPy/pandas backtest on OHLCV DataFrame with statutory charges & slippage.
    Returns BacktestResult matching event-driven schema.
    """
    from engine.charges import calculate_transaction_charges

    close = df["close"].astype(float)
    if len(close) < 30:
        raise ValueError(f"Not enough data: {len(close)} bars (need ≥30)")

    signal_fn = _STRATEGY_MAP.get(strategy_name.lower(), _signals_rsi)
    signals = signal_fn(close).fillna(0).astype(int)

    # Vectorized state propagation: replace 0 with NaN, ffill active direction, clamp flat (0) where -1
    sig_arr = signals.to_numpy(dtype=np.int8)
    raw_state = np.where(sig_arr != 0, sig_arr, np.nan)
    pos_series = pd.Series(raw_state, index=close.index).ffill().fillna(0.0)
    pos_arr = (pos_series.to_numpy(dtype=np.float64) == 1.0).astype(np.int8)

    # Close any open position on final bar cleanly so trade round-trips are balanced
    prev_pos = np.roll(pos_arr, 1)
    prev_pos[0] = 0
    entry_mask = (pos_arr == 1) & (prev_pos == 0)
    exit_mask = (pos_arr == 0) & (prev_pos == 1)

    if pos_arr[-1] == 1:
        pos_arr[-1] = 0
        exit_mask[-1] = True

    entry_indices = np.flatnonzero(entry_mask)
    exit_indices = np.flatnonzero(exit_mask)
    close_arr = close.to_numpy(dtype=np.float64)
    idx_arr = close.index

    slip_frac = max(0.0, float(slippage_bps)) / 10_000.0
    entries: list[tuple] = []
    exits: list[tuple] = []
    trade_bar_costs = np.zeros(len(close_arr), dtype=np.float64)

    n_pairs = min(len(entry_indices), len(exit_indices))
    for k in range(n_pairs):
        e_idx = int(entry_indices[k])
        x_idx = int(exit_indices[k])
        if x_idx <= e_idx:
            continue
        raw_e = float(close_arr[e_idx])
        raw_x = float(close_arr[x_idx])
        eff_e = raw_e * (1.0 + slip_frac)
        eff_x = raw_x * (1.0 - slip_frac)

        cost_pct = 0.0
        if include_charges and eff_e > 0:
            buy_c = float(
                calculate_transaction_charges(
                    price=eff_e, quantity=1, segment=segment, side="BUY"
                ).total_charges
            )
            sell_c = float(
                calculate_transaction_charges(
                    price=eff_x, quantity=1, segment=segment, side="SELL"
                ).total_charges
            )
            cost_pct = (buy_c + sell_c) / eff_e
            trade_bar_costs[x_idx] = cost_pct

        net_pct = ((eff_x / max(eff_e, 1e-9)) - 1.0 - cost_pct) * 100.0
        entries.append((idx_arr[e_idx], round(eff_e, 4)))
        exits.append((idx_arr[x_idx], round(eff_x, 4), net_pct))

    # Vectorized net strategy return stream (apply execution slippage & statutory drag on transitions)
    position = pd.Series(pos_arr, index=close.index, dtype=float)
    daily_returns = close.pct_change().fillna(0.0)
    entry_drag = pd.Series(np.where(entry_mask, slip_frac, 0.0), index=close.index)
    exit_drag = pd.Series(np.where(exit_mask, slip_frac, 0.0) + trade_bar_costs, index=close.index)
    strategy_returns = (daily_returns * position.shift(1).fillna(0.0)) - entry_drag - exit_drag
    equity = (1.0 + strategy_returns).cumprod() * 100.0
    equity_list = equity.tolist()

    # ── Metrics ────────────────────────────────────────────────
    trade_rets = [e[2] for e in exits]
    wins = [r for r in trade_rets if r > 0]
    losses = [r for r in trade_rets if r <= 0]

    total_return = float(equity.iloc[-1] - 100.0)
    bh_return = (float(close.iloc[-1]) / float(close.iloc[0]) - 1.0) * 100.0

    years = len(close) / 252.0
    cagr = _calc_cagr(total_return, years)
    sharpe = _calc_sharpe(strategy_returns)
    max_dd = _calc_max_drawdown(equity)

    win_rate = len(wins) / max(len(trade_rets), 1) * 100
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    profit_factor = (
        abs(sum(wins)) / max(abs(sum(losses)), 1e-9)
        if losses
        else float(sum(wins))
        if wins
        else 0.0
    )

    start_date = str(close.index[0])[:10]
    end_date = str(close.index[-1])[:10]

    return BacktestResult(
        symbol=symbol.upper(),
        strategy_name=strategy_name.lower(),
        period=f"{round(years, 1)}y",
        start_date=start_date,
        end_date=end_date,
        total_return=round(total_return, 2),
        cagr=round(cagr, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown=round(max_dd, 2),
        total_trades=len(trade_rets),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        avg_hold_days=0.0,
        buy_hold_return=round(bh_return, 2),
        equity_curve=equity_list,
    )


# ── Public entry point ──────────────────────────────────────────


def run_vectorized_backtest(
    symbol: str,
    strategy_name: str = "rsi",
    period: str = "1y",
    exchange: str = "NSE",
) -> BacktestResult:
    """
    Fetch OHLCV data and run vectorized backtest.
    Uses yfinance for data. Returns BacktestResult.
    """
    df = _fetch_ohlcv(symbol, period=period, exchange=exchange)
    return vectorized_backtest(df, strategy_name=strategy_name, symbol=symbol)
