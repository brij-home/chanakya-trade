---
name: backtesting
description: >-
  Develop, execute, and analyze quantitative trading strategies using the
  vectorized and event-driven backtesting engines in engine/, including
  options backtesting, market regime filtering, and performance reporting.
---

# Backtesting & Strategy Engine Runbook

## Engine Components

| Module | File | Purpose |
| :--- | :--- | :--- |
| **Vectorized Backtester** | [`engine/backtest_vectorized.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest_vectorized.py) | Ultra-fast NumPy/Pandas array calculations for broad-market sweeps |
| **Event-Driven Backtester** | [`engine/backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest.py) | Bar-by-bar execution, slippage, commissions, intraday stops |
| **Options Backtester** | [`engine/options_backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/options_backtest.py) | Black-Scholes Greeks, IV decay, delta hedging, multi-leg strategies |
| **Regime Detector** | [`engine/backtest_regime.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest_regime.py) | Filters by macro regime (Trending Bull/Bear, High/Low Vol) |
| **Strategy Library** | [`engine/strategy_library.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/strategy_library.py) | Pre-built technical, momentum, and mean-reversion strategies |

---

## Standard Workflow

### 1. Define Strategy
Subclass `Strategy` or implement `generate_signals(df: pd.DataFrame) -> pd.Series`.

### 2. Execute Backtest
```python
from engine.backtest_vectorized import VectorizedBacktester
from engine.strategy_library import EMACrossoverStrategy

strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)
tester = VectorizedBacktester(strategy=strategy, initial_capital=200000)
result = tester.run(symbol="INFY", df=ohlcv_df)
```

### 3. Analyze Metrics

| Metric | Description |
| :--- | :--- |
| Total Return (%) | Net portfolio return |
| CAGR (%) | Compound annual growth rate |
| Max Drawdown (MDD %) | Largest peak-to-trough decline |
| Sharpe Ratio | Risk-adjusted return (annualized) |
| Sortino Ratio | Downside-only risk-adjusted return |
| Calmar Ratio | Return / Max Drawdown |
| Win Rate (%) | Percentage of profitable trades |
| Profit Factor | Gross profit / Gross loss |

---

## Performance Characteristics

- **Vectorized engine**: ~2s per ticker on 250-day dataset (single-core).
- **Event-driven engine**: ~5s per ticker with commission + slippage modeling.
- **No LLM dependency**: Pure numeric compute — no AI model calls required.
- **Recommended**: Use `openai/gpt-oss-120b` (Groq) only for narrative backtest *report* generation, not for compute.

---

## Critical Rules

1. **Timezone Normalization**: All input OHLCV DataFrames must have tz-naive DatetimeIndex (`df.index.tz_localize(None)`). Never mix tz-aware and tz-naive timestamps.
2. **Deterministic Tests**: Always pass synthetic OHLCV data in unit tests — no network calls to Yahoo Finance or brokers.
3. **Cache Reuse**: Historical OHLCV cached via SQLite `analysis_cache` (15min TTL). Reuse across strategy iterations.

---

## Testing

```powershell
# Vectorized backtest tests
.venv\Scripts\pytest.exe tests/test_backtest_vectorized.py -v

# Regime filter tests
.venv\Scripts\pytest.exe tests/test_backtest_regime.py -v

# Options analytics and backtest tests
.venv\Scripts\pytest.exe tests/test_options_backtest.py -v
```
