import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import LiveTickerRibbon from '../renderer/src/components/Common/LiveTickerRibbon'

const MOCK_TICKERS = [
  { symbol: 'NIFTY', display_name: 'NIFTY 50', category: 'INDEX', unit: '₹', ltp: 23897.70, change: 24.25, change_pct: 0.10, direction: 'up' },
  { symbol: 'BANKNIFTY', display_name: 'BANK NIFTY', category: 'INDEX', unit: '₹', ltp: 57369.65, change: -10.95, change_pct: -0.02, direction: 'down' },
  { symbol: 'CRUDEOIL', display_name: 'CRUDE OIL', category: 'COMMODITY', unit: '₹/bbl', ltp: 8539.55, change: -154.96, change_pct: -1.78, direction: 'down' },
  { symbol: 'GOLD', display_name: 'GOLD', category: 'COMMODITY', unit: '₹/10g', ltp: 134973.91, change: -2144.64, change_pct: -1.56, direction: 'down' },
  { symbol: 'SILVER', display_name: 'SILVER', category: 'COMMODITY', unit: '₹/kg', ltp: 201206.25, change: -2977.00, change_pct: -1.46, direction: 'down' },
  { symbol: 'BTC', display_name: 'BITCOIN', category: 'CRYPTO', unit: '$', ltp: 79419.90, change: -1852.56, change_pct: -2.28, direction: 'down' },
  { symbol: 'INDIA VIX', display_name: 'INDIA VIX', category: 'VIX', unit: 'pts', ltp: 10.68, change: -0.69, change_pct: -6.07, direction: 'down' },
]

describe('LiveTickerRibbon Component', () => {
  it('renders all multi-asset tickers with display names and units', () => {
    render(<LiveTickerRibbon tickers={MOCK_TICKERS} selectedSymbol="NIFTY" onSelectSymbol={() => {}} />)

    expect(screen.getByText('NIFTY 50')).toBeInTheDocument()
    expect(screen.getByText('BANK NIFTY')).toBeInTheDocument()
    expect(screen.getByText('CRUDE OIL')).toBeInTheDocument()
    expect(screen.getByText('GOLD')).toBeInTheDocument()
    expect(screen.getByText('SILVER')).toBeInTheDocument()
    expect(screen.getByText('BITCOIN')).toBeInTheDocument()
    expect(screen.getByText('INDIA VIX')).toBeInTheDocument()
  })

  it('formats Bitcoin price with $ and Indian assets with ₹', () => {
    render(<LiveTickerRibbon tickers={MOCK_TICKERS} selectedSymbol="NIFTY" onSelectSymbol={() => {}} />)

    // Bitcoin formatted with $
    expect(screen.getByText('$79,419.90')).toBeInTheDocument()
    // Indian index formatted with ₹
    expect(screen.getByText('₹23,897.70')).toBeInTheDocument()
  })

  it('shows green up arrow for positive change and red down arrow for negative change', () => {
    render(<LiveTickerRibbon tickers={MOCK_TICKERS} selectedSymbol="NIFTY" onSelectSymbol={() => {}} />)

    // NIFTY is +0.10% (up)
    expect(screen.getByText('+0.10%')).toBeInTheDocument()
    // CRUDE OIL is -1.78% (down)
    expect(screen.getByText('-1.78%')).toBeInTheDocument()
  })

  it('calls onSelectSymbol callback when a ticker is clicked', () => {
    const handleSelect = vi.fn()
    render(<LiveTickerRibbon tickers={MOCK_TICKERS} selectedSymbol="NIFTY" onSelectSymbol={handleSelect} />)

    const crudeBtn = screen.getByText('CRUDE OIL').closest('button')
    fireEvent.click(crudeBtn)

    expect(handleSelect).toHaveBeenCalledWith('CRUDEOIL')
  })

  it('applies active ring to selected symbol', () => {
    render(<LiveTickerRibbon tickers={MOCK_TICKERS} selectedSymbol="BTC" onSelectSymbol={() => {}} />)

    const btcBtn = screen.getByText('BITCOIN').closest('button')
    expect(btcBtn.className).toContain('ring-2 ring-amber/80')
  })
})
