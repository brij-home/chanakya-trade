/**
 * @file market.js
 * Institutional Market & Technical Analysis JSDoc Type Definitions
 * Maps 1:1 with Python Pydantic models in engine/ and analysis/
 */

/**
 * @typedef {'BUY' | 'SELL' | 'STAND_DOWN'} TradeAction
 */

/**
 * @typedef {'READY' | 'STALK' | 'STAND_DOWN'} SignalStatus
 */

/**
 * @typedef {'DEMAND' | 'SUPPLY'} OrderBlockType
 */

/**
 * @typedef {'LEADING' | 'WEAKENING' | 'LAGGING' | 'IMPROVING'} RRGQuadrant
 */

/**
 * @typedef {Object} OrderBlock
 * @property {string} tf - Timeframe of the order block (e.g. '15m', '1D')
 * @property {OrderBlockType} type - 'DEMAND' or 'SUPPLY'
 * @property {number} top - Upper price boundary
 * @property {number} bottom - Lower price boundary
 * @property {number} midpoint - 50% equilibrium level
 * @property {number} [ote_price] - Optimal Trade Entry (62-79% fibonacci retracement level)
 * @property {number} [confluence_count] - Multi-timeframe confluence multiplier
 */

/**
 * @typedef {Object} VolumeProfile
 * @property {number} poc - Point of Control (Highest traded volume price level)
 * @property {number} vah - Value Area High (70% upper volume distribution)
 * @property {number} val - Value Area Low (70% lower volume distribution)
 * @property {string} [tf] - Profile calculation timeframe
 */

/**
 * @typedef {Object} TradeSetup
 * @property {string} symbol - NSE/BSE Trading Symbol (e.g. 'RELIANCE')
 * @property {'NSE' | 'BSE' | 'NFO' | 'MCX'} [exchange] - Target exchange
 * @property {TradeAction} action - 'BUY' or 'SELL'
 * @property {SignalStatus} [status] - 'READY' | 'STALK' | 'STAND_DOWN'
 * @property {number} price - Suggested Entry Price
 * @property {number} stopLoss - Invalidation price level
 * @property {number} target1 - Target 1 (2R scaled profit booking)
 * @property {number} target2 - Target 2 (3.5R runner profit booking)
 * @property {number} [rMultiple] - Reward to risk ratio
 * @property {string} [timeline] - Expected holding duration (e.g. '3-8 Sessions')
 * @property {string} [thesis] - Qualitative institutional rationale
 * @property {VolumeProfile} [volume_profile] - Dynamic POC/VAH/VAL profile
 * @property {OrderBlock} [demand_ob] - Active demand order block
 * @property {OrderBlock} [supply_ob] - Active supply order block
 */

/**
 * @typedef {Object} SectorRRGPoint
 * @property {string} sector - Sector name (e.g. 'NIFTY IT', 'NIFTY AUTO')
 * @property {number} rs_ratio - JdK Relative Strength Ratio (Benchmark normalized)
 * @property {number} rs_momentum - JdK RS-Momentum rate of change
 * @property {RRGQuadrant} quadrant - Current rotation quadrant
 * @property {Array<{rs_ratio: number, rs_momentum: number}>} [tail] - 5-period historical trail points
 */

export {}
