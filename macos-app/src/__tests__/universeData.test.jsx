import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  INDIAN_UNIVERSE,
  COUNCIL_REGISTRY,
  PERSONA_REGISTRY,
  QUANT_COMMANDS,
  fuzzySearchUniverse,
  getRecentSearches,
  saveRecentSearch,
  clearRecentSearches,
} from '../renderer/src/data/universeData'
import SmartTypeahead from '../renderer/src/components/Common/SmartTypeahead'

describe('Indian Market Universe & Fuzzy Search Engine', () => {
  beforeEach(() => {
    clearRecentSearches()
  })

  it('contains institutional Indian equity universe, councils, and personas', () => {
    expect(INDIAN_UNIVERSE.length).toBeGreaterThan(40)
    expect(COUNCIL_REGISTRY.length).toBe(5)
    expect(PERSONA_REGISTRY.length).toBe(13)
    expect(QUANT_COMMANDS.length).toBeGreaterThan(15)
  })

  it('fuzzy searches stock symbols by ticker, name, and sector', () => {
    const relResults = fuzzySearchUniverse('rel')
    expect(relResults.some((r) => r.symbol === 'RELIANCE')).toBe(true)

    const tataResults = fuzzySearchUniverse('tat')
    expect(tataResults.some((r) => r.symbol === 'TATAMOTORS')).toBe(true)
    expect(tataResults.some((r) => r.symbol === 'TCS')).toBe(true)

    const itResults = fuzzySearchUniverse('software')
    expect(itResults.length).toBeGreaterThan(0)
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
        query="trent"
        isOpen={true}
        onSelect={onSelect}
        onClose={onClose}
      />
    )

    const matches = screen.getAllByText(/TRENT/i)
    expect(matches.length).toBeGreaterThan(0)

    fireEvent.click(matches[0])
    expect(onSelect).toHaveBeenCalled()
  })

  it('renders in symbols_only mode for quick ticker switcher', () => {
    const onSelect = vi.fn()

    render(
      <SmartTypeahead
        query="nifty"
        isOpen={true}
        mode="symbols_only"
        onSelect={onSelect}
        onClose={vi.fn()}
      />
    )

    const matches = screen.getAllByText(/NIFTY/i)
    expect(matches.length).toBeGreaterThan(0)
  })
})
