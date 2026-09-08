import { describe, it, expect, beforeEach } from 'vitest'
import {
  formatLivePrice,
  formatLiveChange,
  classifyDataSource,
  formatMetricOrUnavailable,
} from '../renderer/src/utils/marketDataUtils'
import { useRealtimeMarket } from '../renderer/src/hooks/useRealtimeMarket'

describe('Market Data Utilities & SSOT Guardrails', () => {
  describe('formatLivePrice', () => {
    it('returns "—" for missing, zero, negative, or invalid prices', () => {
      expect(formatLivePrice(null)).toBe('—')
      expect(formatLivePrice(undefined)).toBe('—')
      expect(formatLivePrice(0)).toBe('—')
      expect(formatLivePrice(-150)).toBe('—')
      expect(formatLivePrice(NaN)).toBe('—')
      expect(formatLivePrice('')).toBe('—')
      expect(formatLivePrice('invalid')).toBe('—')
    })

    it('formats valid positive numbers with Indian grouping and unit', () => {
      expect(formatLivePrice(24150.5, '₹')).toBe('₹24,150.50')
      expect(formatLivePrice(79419.9, '$')).toBe('$79,419.90')
      expect(formatLivePrice(12.45, 'pts')).toBe('12.45 pts')
      expect(formatLivePrice(8500, '₹/bbl')).toBe('₹8,500.00 /bbl')
    })

    it('handles numeric string inputs correctly', () => {
      expect(formatLivePrice('24500.25', '₹')).toBe('₹24,500.25')
    })
  })

  describe('formatLiveChange', () => {
    it('returns "—" and neutral styling for invalid or missing changes', () => {
      const result = formatLiveChange(null, null, 0)
      expect(result.text).toBe('—')
      expect(result.colorClass).toBe('text-muted')
      expect(result.isPositive).toBe(false)
    })

    it('formats positive change and percentage with + sign', () => {
      const result = formatLiveChange(120.5, 0.52)
      expect(result.text).toBe('+120.50 (+0.52%)')
      expect(result.colorClass).toContain('emerald')
      expect(result.isPositive).toBe(true)
    })

    it('formats negative change and percentage', () => {
      const result = formatLiveChange(-85.2, -0.35)
      expect(result.text).toBe('-85.20 (-0.35%)')
      expect(result.colorClass).toContain('rose')
      expect(result.isPositive).toBe(false)
    })
  })

  describe('classifyDataSource', () => {
    it('accurately identifies live stream vs fallback vs unavailable', () => {
      const live = classifyDataSource({ source: 'STREAM', isFallback: false })
      expect(live.isLive).toBe(true)
      expect(live.badgeText).toContain('LIVE')

      const fallback = classifyDataSource({ source: 'FALLBACK', isFallback: true })
      expect(fallback.isFallback).toBe(true)
      expect(fallback.badgeText).toContain('DELAYED')

      const unavail = classifyDataSource({ source: 'UNAVAILABLE', isFallback: true })
      expect(unavail.badgeText).toContain('UNAVAILABLE')
    })
  })

  describe('formatMetricOrUnavailable', () => {
    it('returns "—" for falsy or unprovided values', () => {
      expect(formatMetricOrUnavailable(null)).toBe('—')
      expect(formatMetricOrUnavailable(undefined)).toBe('—')
      expect(formatMetricOrUnavailable('')).toBe('—')
    })

    it('returns formatted value with suffix when valid', () => {
      expect(formatMetricOrUnavailable(18.5, '%')).toBe('18.5%')
      expect(formatMetricOrUnavailable(281.5, ' Cr')).toBe('281.5 Cr')
    })
  })
})

describe('useRealtimeMarket Hook & Store', () => {
  beforeEach(() => {
    useRealtimeMarket.setState({
      tickers: [],
      tickerMap: {},
      isStreaming: false,
      isFallback: false,
      lastUpdated: null,
      error: null,
      dataSource: 'REST',
    })
  })

  it('initializes with empty tickers and zero fake seed prices', () => {
    const state = useRealtimeMarket.getState()
    expect(state.tickers).toEqual([])
    expect(state.tickerMap).toEqual({})
    expect(state.getTicker('NIFTY')).toBeNull()
  })

  it('updates state honestly when snapshot is received', () => {
    const incomingData = [
      {
        symbol: 'NIFTY',
        display_name: 'NIFTY 50',
        category: 'INDEX',
        unit: '₹',
        ltp: 24200.5,
        change: 50.5,
        change_pct: 0.21,
        direction: 'up',
      },
    ]

    useRealtimeMarket.getState().updateFromSnapshot(incomingData, 'STREAM', false)

    const state = useRealtimeMarket.getState()
    expect(state.tickers.length).toBe(1)
    expect(state.isStreaming).toBe(true)
    expect(state.isFallback).toBe(false)
    expect(state.dataSource).toBe('STREAM')

    const nifty = state.getTicker('NIFTY')
    expect(nifty).toBeDefined()
    expect(nifty.ltp).toBe(24200.5)
  })

  it('clears error and tags fallback when fallback feed is used', () => {
    useRealtimeMarket.getState().updateFromSnapshot([], 'FALLBACK', true)

    const state = useRealtimeMarket.getState()
    expect(state.isFallback).toBe(true)
    expect(state.dataSource).toBe('FALLBACK')
  })
})
