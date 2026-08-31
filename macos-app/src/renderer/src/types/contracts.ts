/**
 * @file contracts.ts
 * TypeScript Interface & Type Contracts for ChanakyaTrade
 * Provides static type safety for mixed TS/JS codebase.
 */

// ── Market & Trading Types ───────────────────────────────────────────────────

export type TradeAction = 'BUY' | 'SELL' | 'STAND_DOWN'
export type SignalStatus = 'READY' | 'STALK' | 'STAND_DOWN'
export type OrderBlockType = 'DEMAND' | 'SUPPLY'
export type RRGQuadrant = 'LEADING' | 'WEAKENING' | 'LAGGING' | 'IMPROVING'
export type ExchangeId = 'NSE' | 'BSE' | 'NFO' | 'MCX'

export interface OrderBlock {
  tf: string
  type: OrderBlockType
  top: number
  bottom: number
  midpoint: number
  ote_price?: number
  confluence_count?: number
}

export interface VolumeProfile {
  poc: number
  vah: number
  val: number
  tf?: string
}

export interface TradeSetup {
  symbol: string
  exchange?: ExchangeId
  action: TradeAction
  status?: SignalStatus
  price: number
  stopLoss: number
  target1: number
  target2: number
  rMultiple?: number
  timeline?: string
  thesis?: string
  volume_profile?: VolumeProfile
  demand_ob?: OrderBlock
  supply_ob?: OrderBlock
}

export interface SectorRRGPoint {
  sector: string
  rs_ratio: number
  rs_momentum: number
  quadrant: RRGQuadrant
  tail?: Array<{ rs_ratio: number; rs_momentum: number }>
}

// ── Options Desk Types ───────────────────────────────────────────────────────

export type OptionType = 'CE' | 'PE'
export type OptionAction = 'BUY' | 'SELL'

export interface OptionLeg {
  id: string | number
  type: OptionType
  action: OptionAction
  strike: number
  premium: number
  lots: number
  lotSize: number
  expiry?: string
  iv?: number
  delta?: number
  theta?: number
  gamma?: number
  vega?: number
}

export interface PayoffMetrics {
  maxProfit: number
  maxLoss: number
  breakevens: number[]
  netOutlay: number
  riskReward?: number
  pop?: number
}

export interface GEXLevel {
  strike: number
  callGex: number
  putGex: number
  netGex: number
  callOI: number
  putOI: number
}

// ── Multi-Agent Personas & Councils ─────────────────────────────────────────

export type PersonaVerdict = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'STAND_DOWN'

export type PersonaId =
  | 'buffett'
  | 'munger'
  | 'lynch'
  | 'jhunjhunwala'
  | 'kedia'
  | 'minervini'
  | 'wyckoff'
  | 'oneil'
  | 'soros'
  | 'simons'
  | 'taleb'
  | 'smc'
  | 'forensic'

export interface PersonaSignal {
  id: PersonaId
  name: string
  title: string
  icon: string
  verdict: PersonaVerdict
  confidence: number
  thesis: string
  metrics?: Record<string, number | string | boolean>
  reasons?: string[]
}

export type CouncilId =
  | 'breakout'
  | 'options_sniper'
  | 'multibagger'
  | 'macro_regime'
  | 'core_value'

export interface CouncilConsensus {
  id: CouncilId
  name: string
  icon: string
  desc: string
  badge: string
  verdict: PersonaVerdict
  score: number
  members: PersonaId[]
  thesis: string
  signals?: PersonaSignal[]
}

// ── Quantitative Backtesting Types ──────────────────────────────────────────

export type StrategyId = 'rsi' | 'ema' | 'bb' | 'supertrend' | 'donchian' | 'smc'
export type BarTimeframe = '1D' | '1H' | '15m' | '5m'
export type LookbackPeriod = '1Y' | '2Y' | '3Y' | '5Y' | 'YTD'

export interface BacktestConfig {
  symbol: string
  strategy: StrategyId
  timeframe: BarTimeframe
  period: LookbackPeriod
  initial_capital: number
  risk_pct: number
}

export interface BacktestTrade {
  date: string
  type: 'LONG' | 'SHORT'
  entry: number
  exit: number
  pnl: number
  pct: number
  r: number
  reason: string
}

export interface BacktestResult {
  total_return: number
  cagr: number
  sharpe_ratio: number
  max_drawdown: number
  win_rate: number
  total_trades: number
  profit_factor: number
  equity_curve?: number[]
  trades?: BacktestTrade[]
}
