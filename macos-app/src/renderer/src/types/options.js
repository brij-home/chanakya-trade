/**
 * @file options.js
 * Options Desk, Greeks & Payoff Simulation JSDoc Type Definitions
 * Aligns with engine/ and market/options.py backend schemas
 */

/**
 * @typedef {'CE' | 'PE'} OptionType
 */

/**
 * @typedef {'BUY' | 'SELL'} OptionAction
 */

/**
 * @typedef {Object} OptionLeg
 * @property {string|number} id - Unique leg identifier
 * @property {OptionType} type - 'CE' (Call) or 'PE' (Put)
 * @property {OptionAction} action - 'BUY' (Long) or 'SELL' (Short)
 * @property {number} strike - Option Strike Price
 * @property {number} premium - Market Premium (₹)
 * @property {number} lots - Number of lots traded
 * @property {number} lotSize - Underlying contract lot size (e.g. 50 for NIFTY)
 * @property {string} [expiry] - Expiry date label
 * @property {number} [iv] - Implied Volatility percentage
 * @property {number} [delta] - Option Delta
 * @property {number} [theta] - Daily Theta decay (₹)
 * @property {number} [gamma] - Option Gamma
 * @property {number} [vega] - Option Vega
 */

/**
 * @typedef {Object} PayoffPoint
 * @property {number} price - Underlying simulation price coordinate
 * @property {number} pnl - Net payoff profit / loss (₹)
 */

/**
 * @typedef {Object} PayoffMetrics
 * @property {number} maxProfit - Maximum possible profit (Infinity if uncapped)
 * @property {number} maxLoss - Maximum possible loss (Infinity if uncapped)
 * @property {number[]} breakevens - List of mathematical breakeven price points
 * @property {number} netOutlay - Total cash debit (<0) or credit (>0) (₹)
 * @property {number} [riskReward] - Risk to reward ratio
 * @property {number} [pop] - Probability of Profit (0-100%)
 */

/**
 * @typedef {Object} GEXLevel
 * @property {number} strike - Strike price
 * @property {number} callGex - Call Gamma Exposure (₹ Cr)
 * @property {number} putGex - Put Gamma Exposure (₹ Cr)
 * @property {number} netGex - Net Gamma Exposure
 * @property {number} callOI - Call Open Interest (Contracts)
 * @property {number} putOI - Put Open Interest (Contracts)
 */

export {}
