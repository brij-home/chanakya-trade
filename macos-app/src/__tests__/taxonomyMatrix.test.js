import { describe, it, expect, beforeEach } from 'vitest'
import {
  resolveInstrument,
  getSymbolExchange,
  fuzzySearchUniverse,
} from '../renderer/src/data/universeData'
import { useChatStore } from '../renderer/src/store/chatStore'

describe('Frontend Holistic Instrument Taxonomy & Resolution Matrix', () => {
  const TEST_MATRIX = [
    { symbol: 'GOLD', rawExchange: 'NSE', expectedExchange: 'MCX', expectedType: 'commodity' },
    { symbol: 'CRUDEOIL', rawExchange: null, expectedExchange: 'MCX', expectedType: 'commodity' },
    { symbol: 'SILVER', rawExchange: 'NSE', expectedExchange: 'MCX', expectedType: 'commodity' },
    { symbol: 'NATURALGAS', rawExchange: 'NSE', expectedExchange: 'MCX', expectedType: 'commodity' },
    { symbol: 'COPPER', rawExchange: '', expectedExchange: 'MCX', expectedType: 'commodity' },
    { symbol: 'USDINR', rawExchange: 'NSE', expectedExchange: 'CDS', expectedType: 'currency' },
    { symbol: 'EURINR', rawExchange: null, expectedExchange: 'CDS', expectedType: 'currency' },
    { symbol: 'SENSEX', rawExchange: 'NSE', expectedExchange: 'BSE', expectedType: 'index' },
    { symbol: 'BANKEX', rawExchange: null, expectedExchange: 'BSE', expectedType: 'index' },
    { symbol: 'RELIANCE', rawExchange: 'NSE', expectedExchange: 'NSE', expectedType: 'equity' },
    { symbol: 'TCS', rawExchange: null, expectedExchange: 'NSE', expectedType: 'equity' },
    { symbol: 'GOLDBEES', rawExchange: 'NSE', expectedExchange: 'NSE', expectedType: 'etf' },
    { symbol: 'NIFTY50', rawExchange: null, expectedExchange: 'NSE', expectedType: 'index' },
  ]

  it('resolveInstrument canonical SSOT normalizes all asset classes', () => {
    for (const item of TEST_MATRIX) {
      const res = resolveInstrument(item.symbol, item.rawExchange)
      expect(res.symbol).toBe(item.symbol)
      expect(res.exchange).toBe(item.expectedExchange)
      expect(res.formatted).toBe(`${item.symbol} ${item.expectedExchange}`)
      expect(res.prefixKey).toBe(`${item.expectedExchange}:${item.symbol}`)
    }
  })

  it('resolveInstrument handles colon prefixes (e.g. MCX:GOLD, CDS:USDINR)', () => {
    const gold = resolveInstrument('MCX:GOLD')
    expect(gold.symbol).toBe('GOLD')
    expect(gold.exchange).toBe('MCX')

    const usd = resolveInstrument('CDS:USDINR')
    expect(usd.symbol).toBe('USDINR')
    expect(usd.exchange).toBe('CDS')

    const sensex = resolveInstrument('BSE:SENSEX')
    expect(sensex.symbol).toBe('SENSEX')
    expect(sensex.exchange).toBe('BSE')
  })

  it('fuzzySearchUniverse produces commands with explicit non-NSE exchange tags', () => {
    const crudeResults = fuzzySearchUniverse('crudeoil')
    const crudeItem = crudeResults.find((r) => r.symbol === 'CRUDEOIL')
    expect(crudeItem).toBeDefined()
    expect(crudeItem.exchange).toBe('MCX')
    expect(crudeItem.command).toBe('analyze CRUDEOIL MCX')

    const goldResults = fuzzySearchUniverse('gold')
    const goldItem = goldResults.find((r) => r.symbol === 'GOLD')
    expect(goldItem).toBeDefined()
    expect(goldItem.exchange).toBe('MCX')
    expect(goldItem.command).toBe('analyze GOLD MCX')

    const usdResults = fuzzySearchUniverse('usdinr')
    const usdItem = usdResults.find((r) => r.symbol === 'USDINR')
    expect(usdItem).toBeDefined()
    expect(usdItem.exchange).toBe('CDS')
    expect(usdItem.command).toBe('analyze USDINR CDS')
  })

  it('Zustand chat store startStreamingMessage normalizes exchange upon initial insertion', () => {
    const { startStreamingMessage, messages } = useChatStore.getState()
    const msgId = Date.now() + 999

    // Pass GOLD with fallback 'NSE'
    startStreamingMessage(msgId, 'GOLD', 'NSE')
    const latestMessages = useChatStore.getState().messages
    const msg = latestMessages.find((m) => m.id === msgId)

    expect(msg).toBeDefined()
    expect(msg.data.symbol).toBe('GOLD')
    expect(msg.data.exchange).toBe('MCX')
  })
})
