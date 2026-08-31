import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  INDIAN_UNIVERSE,
  COUNCIL_REGISTRY,
  PERSONA_REGISTRY,
  QUANT_COMMANDS,
  fuzzySearchUniverse,
  normalizeQuery,
  getRecentSearches,
  saveRecentSearch,
  clearRecentSearches,
} from '../renderer/src/data/universeData'
import SmartTypeahead from '../renderer/src/components/Common/SmartTypeahead'

describe('Indian Market Universe & Fuzzy Search Engine', () => {
  beforeEach(() => {
    clearRecentSearches()
  })

  it('contains comprehensive institutional Indian market universe across all asset classes', () => {
    expect(INDIAN_UNIVERSE.length).toBeGreaterThan(100)
    expect(COUNCIL_REGISTRY.length).toBe(5)
    expect(PERSONA_REGISTRY.length).toBe(13)
    expect(QUANT_COMMANDS.length).toBeGreaterThan(15)

    // Verify all asset types are represented
    const types = new Set(INDIAN_UNIVERSE.map((u) => u.type))
    expect(types.has('stock')).toBe(true)
    expect(types.has('index')).toBe(true)
    expect(types.has('etf')).toBe(true)
    expect(types.has('commodity')).toBe(true)
    expect(types.has('currency')).toBe(true)
  })

  it('normalizes queries removing hyphens, underscores, dots, and spaces', () => {
    expect(normalizeQuery('Bajaj-Auto')).toBe('bajajauto')
    expect(normalizeQuery('bajaj_auto')).toBe('bajajauto')
    expect(normalizeQuery('BAJAJ AUTO')).toBe('bajajauto')
    expect(normalizeQuery('M&M')).toBe('mm')
    expect(normalizeQuery('NIFTY 50')).toBe('nifty50')
  })

  it('fuzzy searches BAJAJ-AUTO across all phonetic and punctuation variations', () => {
    const q1 = fuzzySearchUniverse('Bajaj-Auto')
    expect(q1.some((r) => r.symbol === 'BAJAJ-AUTO')).toBe(true)
    expect(q1[0].symbol).toBe('BAJAJ-AUTO')

    const q2 = fuzzySearchUniverse('bajaj auto')
    expect(q2.some((r) => r.symbol === 'BAJAJ-AUTO')).toBe(true)

    const q3 = fuzzySearchUniverse('bajaj_auto')
    expect(q3.some((r) => r.symbol === 'BAJAJ-AUTO')).toBe(true)

    const q4 = fuzzySearchUniverse('bajajauto')
    expect(q4.some((r) => r.symbol === 'BAJAJ-AUTO')).toBe(true)

    const q5 = fuzzySearchUniverse('bajaj')
    expect(q5.some((r) => r.symbol === 'BAJAJ-AUTO')).toBe(true)
  })

  it('fuzzy searches indices, ETFs, commodities, and currencies accurately', () => {
    const niftyRes = fuzzySearchUniverse('nifty 50')
    expect(niftyRes.some((r) => r.symbol === 'NIFTY50')).toBe(true)

    const goldbeesRes = fuzzySearchUniverse('goldbees')
    expect(goldbeesRes.some((r) => r.symbol === 'GOLDBEES')).toBe(true)

    const crudeRes = fuzzySearchUniverse('crude oil')
    expect(crudeRes.some((r) => r.symbol === 'CRUDEOIL')).toBe(true)

    const usdRes = fuzzySearchUniverse('usdinr')
    expect(usdRes.some((r) => r.symbol === 'USDINR')).toBe(true)
  })

  it('filters results by category when categoryFilter is provided', () => {
    const etfOnly = fuzzySearchUniverse('gold', null, 10, 'etf')
    expect(etfOnly.every((r) => r.stockType === 'etf' || r.type === 'etf')).toBe(true)
    expect(etfOnly.some((r) => r.symbol === 'GOLDBEES')).toBe(true)

    const commodityOnly = fuzzySearchUniverse('gold', null, 10, 'commodity')
    expect(commodityOnly.every((r) => r.stockType === 'commodity' || r.type === 'commodity')).toBe(true)
    expect(commodityOnly.some((r) => r.symbol === 'GOLD')).toBe(true)
  })

  it('fuzzy searches councils and personas accurately', () => {
    const councilResults = fuzzySearchUniverse('breakout')
    expect(councilResults.some((r) => r.id === 'breakout')).toBe(true)

    const personaResults = fuzzySearchUniverse('kedia')
    expect(personaResults.some((r) => r.id === 'kedia')).toBe(true)

    const minerviniResults = fuzzySearchUniverse('minervini')
    expect(minerviniResults.some((r) => r.id === 'minervini')).toBe(true)
  })

  it('fuzzy searches quantitative command keywords', () => {
    const funnelResults = fuzzySearchUniverse('funnel')
    expect(funnelResults.some((r) => r.cmd === 'funnel')).toBe(true)

    const whaleResults = fuzzySearchUniverse('whales')
    expect(whaleResults.some((r) => r.cmd === 'whales')).toBe(true)
  })

  it('handles recent search storage lifecycle and limits to max 8 items', () => {
    expect(getRecentSearches()).toEqual([])

    for (let i = 1; i <= 10; i++) {
      saveRecentSearch({
        text: `analyze SYMBOL_${i}`,
        symbol: `SYM_${i}`,
        label: `Symbol ${i}`,
        icon: '🏢',
      })
    }

    const recents = getRecentSearches()
    expect(recents.length).toBe(8)
    expect(recents[0].symbol).toBe('SYM_10')

    clearRecentSearches()
    expect(getRecentSearches()).toEqual([])
  })
})

describe('SmartTypeahead Component', () => {
  it('renders null when isOpen is false', () => {
    const { container } = render(
      <SmartTypeahead
        query="rel"
        isOpen={false}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders search matches and dispatches onSelect when item clicked', () => {
    const onSelect = vi.fn()
    const onClose = vi.fn()

    render(
      <SmartTypeahead
        query="bajaj auto"
        isOpen={true}
        onSelect={onSelect}
        onClose={onClose}
      />
    )

    const item = screen.getByText((content) => content.includes('BAJAJ-AUTO'))
    expect(item).toBeDefined()
    fireEvent.click(item)
    expect(onSelect).toHaveBeenCalled()
  })
})
