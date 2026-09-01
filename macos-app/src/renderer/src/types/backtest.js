/**
 * @file backtest.js
 * Quantitative Backtesting Engine JSDoc Type Definitions
 * Maps to engine/backtest.py backend schema
 */

/**
 * @typedef {'rsi' | 'ema' | 'bb' | 'supertrend' | 'donchian' | 'smc'} StrategyId
 */

/**
 * @typedef {'1D' | '1H' | '15m' | '5m'} BarTimeframe
 */

/**
 * @typedef {'1Y' | '2Y' | '3Y' | '5Y' | 'YTD'} LookbackPeriod
 */

/**
 * @typedef {Object} BacktestConfig
 * @property {string} symbol - NSE/BSE symbol under test
 * @property {StrategyId} strategy - Strategy algorithm identifier
 * @property {BarTimeframe} timeframe - Bar granularity
 * @property {LookbackPeriod} period - Historical lookback duration
 * @property {number} initial_capital - Simulation initial capital in ₹ (e.g. 1000000)
 * @property {number} risk_pct - Risk per trade percentage (e.g. 1.5)
 */

/**
 * @typedef {Object} BacktestTrade
 * @property {string} date - Trade exit date label
 * @property {'LONG' | 'SHORT'} type - Direction of position
 * @property {number} entry - Execution entry price (₹)
 * @property {number} exit - Execution exit price (₹)
 * @property {number} pnl - Realized Profit/Loss in ₹
 * @property {number} pct - Percentage return on capital
 * @property {number} r - Realized R-Multiple (e.g. 2.5)
 * @property {string} reason - Exit trigger (e.g. 'Target 1 (2R hit)', 'Trailing Stop')
 */

/**
 * @typedef {Object} BacktestResult
 * @property {number} total_return - Net return percentage
 * @property {number} cagr - Compound Annual Growth Rate percentage
 * @property {number} sharpe_ratio - Annualized Sharpe Ratio
 * @property {number} max_drawdown - Maximum peak-to-trough drawdown percentage (< 0)
 * @property {number} win_rate - Percentage of winning trades (0-100)
 * @property {number} total_trades - Total trade executions in period
 * @property {number} profit_factor - Gross Profit / Gross Loss ratio
 * @property {number[]} [equity_curve] - Cumulative portfolio value array
 * @property {BacktestTrade[]} [trades] - Itemized execution ledger
 */

export {}
