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

### 3. Analyze Institutional Metrics & QuantStats Tear Sheets

Use [`engine.quantstats_report`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/quantstats_report.py) to generate hedge-fund grade tear sheets and risk metrics:

```python
from engine.quantstats_report import generate_html_tear_sheet, key_metrics

# Extract comprehensive metrics
metrics = key_metrics(returns_series, trades=closed_trades)

# Generate interactive HTML tear sheet (monthly returns heatmap, drawdown, underwater curve)
report_path = generate_html_tear_sheet(
    returns=returns_series,
    title="EMA Crossover — Strategy Tear Sheet",
    trades=closed_trades,
)
```

| Metric | Category | Description |
| :--- | :--- | :--- |
| **Total Return (%)** | Return | Net compounded strategy return |
| **CAGR (%)** | Return | Compound annual growth rate |
| **Sharpe Ratio** | Risk-Adjusted | Annualized return per unit of total risk (rf=0) |
| **Sortino Ratio** | Risk-Adjusted | Annualized return per unit of downside risk |
| **Calmar Ratio** | Risk-Adjusted | CAGR / Max Drawdown |
| **Max Drawdown (%)** | Risk | Peak-to-trough maximum decline |
| **Trade Win Rate (%)** | Trade-Level | % of winning closed roundtrips (wins / total trades) |
| **Positive Period %** | Period-Level | % of positive calendar trading days (daily win rate) |
| **Profit Factor** | Quality | Gross profits / Gross losses |
| **Robustness Score** | Anti-Overfit | Walk-Forward In-Sample vs Out-of-Sample Sharpe stability (0.0 to 1.0) |

---

## Critical Rules & Guardrails

1. **Disambiguate the Two Win Rates**:
   - **Trade Win Rate**: Evaluates trade execution edge (`winning_trades / total_trades`).
   - **Positive Period %**: Evaluates equity curve daily smoothness (`positive_days / total_days`).
   - Conflating them is prohibited — report both distinctly.
2. **Out-of-Sample Robustness Gate**:
   - A strategy variant with `robustness_score < 0.35` indicates severe curve-fitting or vanishing edge out-of-sample and fails the Backtest Integrity gate.
3. **Timezone Normalization**: All input OHLCV DataFrames must have tz-naive DatetimeIndex (`df.index.tz_localize(None)`). Never mix tz-aware and tz-naive timestamps.
4. **Deterministic Tests**: Always pass synthetic OHLCV data in unit tests — no network calls to Yahoo Finance or brokers.
5. **Cache Reuse**: Historical OHLCV cached via SQLite `analysis_cache` (15min TTL). Reuse across strategy iterations.

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
