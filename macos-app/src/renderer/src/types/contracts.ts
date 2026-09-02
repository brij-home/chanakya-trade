/**
 * @file contracts.ts
 * TypeScript Interface & Type Contracts for ChanakyaTrade
 * Provides static type safety for mixed TS/JS codebase.
 */

// ── Data Envelope & Mode Contracts (P0-A) ────────────────────────────────────

/**
 * Server-authoritative application mode.
 * Mode is set server-side; a client flag alone is never sufficient.
 *   PAPER — real data, simulated execution (default for new installs)
 *   DEMO  — synthetic fixture data, clearly labelled, isolated from Paper/Live stores
 *   LIVE  — real data, real execution (requires explicit activation + broker certification)
 */
export type AppMode = 'PAPER' | 'DEMO' | 'LIVE'

/**
 * Field-level data quality status for every decision-relevant value.
 *   live            — fresh, directly from licensed/verified source
 *   delayed          — from source, but beyond expected freshness window
 *   cached_fresh     — from local/shared cache, within acceptable TTL
 *   stale            — cache expired or provider lag exceeded threshold
 *   derived_proxy    — computed/converted from a non-primary source (e.g. yfinance COMEX for MCX display)
 *   estimated        — model-derived inference, not a direct observation
 *   unavailable      — data cannot be fetched; source is down or not entitled
 *   demo             — synthetic fixture data; only valid in DEMO mode
 */
export type DataStatus =
  | 'live'
  | 'delayed'
  | 'cached_fresh'
  | 'stale'
  | 'derived_proxy'
  | 'estimated'
  | 'unavailable'
  | 'demo'

/**
 * Full data envelope wrapping any decision-relevant value.
 * Every API response field that influences a trade/recommendation MUST include this.
 */
export interface DataEnvelope<T = unknown> {
  /** The actual value; null when status is unavailable/demo with no safe fallback */
  value: T | null
  /** SI or display unit string (e.g. 'INR', '%', 'pts', '₹/10g') */
  unit?: string
  /** Current quality status of this specific field */
  status: DataStatus
  /** Human-readable source name (e.g. 'yfinance (COMEX proxy)', 'Fyers WebSocket') */
  source_name?: string
  /** Machine-readable source identifier */
  source_id?: string
  /** Exchange/venue where this data originates */
  venue?: string
  /** ISO-8601 timestamp of the exchange/provider event */
  exchange_timestamp?: string
  /** ISO-8601 timestamp when the server received this value */
  received_at?: string
  /** Age of value in milliseconds at time of API response */
  freshness_ms?: number
  /** Whether this value is tradable on the user's actual instrument/venue */
  tradable?: boolean
  /** For derived_proxy: the actual source ticker used (e.g. 'GC=F' for MCX Gold) */
  proxy_source_ticker?: string
  /** For derived_proxy: the actual source venue (e.g. 'COMEX') */
  proxy_source_venue?: string
  /** For derived_proxy: FX pair used in conversion (e.g. 'USD/INR') */
  proxy_fx_pair?: string
  /** For derived_proxy: FX rate applied */
  proxy_fx_rate?: number
  /** For derived_proxy: conversion formula description */
  proxy_conversion_formula?: string
  /** Opaque lineage/audit ID for tracing back to raw observation */
  lineage_id?: string
  /** Why the value is unavailable/stale (user-displayable, no credentials) */
  unavailable_reason?: string
}

/**
 * Determines whether a consequential action (order draft, recommendation, alert)
 * is eligible based on data quality.
 */
export interface ActionEligibility {
  /** Whether the action can proceed */
  eligible: boolean
  /** Current app mode context */
  mode: AppMode
  /** List of human-readable reasons why eligibility is blocked */
  blocked_reasons: string[]
  /** Minimum data status required for this action */
  required_status: DataStatus[]
}

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

export type PersonaVerdict = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'UNAVAILABLE' | 'STAND_DOWN'

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
