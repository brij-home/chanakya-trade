import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ConvictionScoreCard from '../renderer/src/components/Cards/ConvictionScoreCard'

// Mock useAPI hook
vi.mock('../renderer/src/hooks/useAPI', () => ({
  useAPI: () => ({
    call: vi.fn().mockResolvedValue({ data: null }),
  }),
}))

const mockScoreData = {
  total_score: 82,
  verdict: 'HIGH',
  recommended_position_size: 'NORMAL',
  summary: 'Strong institutional alignment with positive gamma posture and favorable risk-reward.',
  as_of: '15:30 IST',
  bullish_count: 8,
  bearish_count: 2,
  unavailable_count: 2,
  veto: { vetoed: false, reason: '' },
  trade_plan: {
    direction: 'LONG',
    entry_price: 24500,
    invalidation_stop: 24350,
    target_1: 24700,
    target_2: 25000,
    stop_distance_pts: 150,
    t1_distance_pts: 200,
    t2_distance_pts: 500,
    rr_t1: '1.3',
    rr_t2: '3.3',
    is_asymmetry_viable: true,
    sl_rationale: 'Institutional Put Writing Wall at 24300',
    t1_rationale: 'Max Pain Pivot & Intraday VWAP Resistance',
    t2_rationale: 'Unfilled Bullish Fair Value Gap',
    eta_t1_str: '~45 mins',
    eta_t2_str: '~90 mins',
    velocity_pts_per_bar: 32.5,
    session_clock_note: 'Active Normal Trading Session',
    structure_advice: 'Theta decay is low (<1% of move over 35m). Naked ATM Call offers high capital velocity.',
  },
  factors: [
    {
      factor_id: 'fii_cash_flow',
      label: 'FII/DII Cash Flow Streak',
      axis: 'INSTITUTIONAL',
      score: 8,
      weight: 10,
      signal: 'BULLISH',
      detail: 'FII net buying today: +2,450 Cr with 3-day consecutive expansion.',
    },
    {
      factor_id: 'vix_regime',
      label: 'India VIX Direction & Level',
      axis: 'MACRO',
      score: 7,
      weight: 10,
      signal: 'BULLISH',
      detail: 'VIX 13.2 — calm volatility ideal for directional option longs.',
    },
    {
      factor_id: 'gex_dealers',
      label: 'GEX Dealer Positioning',
      axis: 'OPTIONS',
      score: 9,
      weight: 10,
      signal: 'BULLISH',
      detail: 'Negative GEX environment creates dealer buying momentum on rallies.',
    },
    {
      factor_id: 'smc_structure',
      label: 'SMC Market Structure',
      axis: 'PRICE',
      score: 5,
      weight: 10,
      signal: 'NEUTRAL',
      detail: 'Price oscillating within range; awaiting clean 15m BOS expansion.',
    },
    {
      factor_id: 'sector_momentum',
      label: 'Sector RRG Momentum',
      axis: 'TIMING',
      score: 4,
      weight: 10,
      signal: 'BEARISH',
      detail: 'Banking sector entering Lagging quadrant on 20D velocity matrix.',
    },
  ],
}

describe('ConvictionScoreCard Institutional Tabular Layout & View Modes', () => {
  it('renders collapsed card header with score, verdict, and counts', () => {
    render(
      <ConvictionScoreCard
        underlying="NIFTY"
        spot={24500}
        pcr={1.12}
        convictionScore={mockScoreData}
      />
    )

    expect(screen.getByText('82')).toBeTruthy()
    expect(screen.getByText(/HIGH CONVICTION/i)).toBeTruthy()
    expect(screen.getByText(/Normal Sizing/i)).toBeTruthy()
    expect(screen.getByText(/8▲ Bullish/i)).toBeTruthy()
    expect(screen.getByText(/2▼ Bearish/i)).toBeTruthy()
  })

  it('expands on click and defaults to high-density Institutional Tabular view', () => {
    render(
      <ConvictionScoreCard
        underlying="NIFTY"
        spot={24500}
        pcr={1.12}
        convictionScore={mockScoreData}
      />
    )

    // Click header to expand
    const headerBtn = screen.getByTitle(/Click to toggle 12-factor orthogonal breakdown/i)
    fireEvent.click(headerBtn)

    // Verify table headers exist
    expect(screen.getByText(/Factor \/ Dimension/i)).toBeTruthy()
    expect(screen.getByText(/Pillar/i)).toBeTruthy()
    expect(screen.getByText(/Score/i)).toBeTruthy()
    expect(screen.getByText(/Live Empirical Reading/i)).toBeTruthy()
    expect(screen.getByText(/Signal/i)).toBeTruthy()

    // Verify table mode is active and renders factor rows
    expect(screen.getByText('FII/DII Cash Flow Streak')).toBeTruthy()
    expect(screen.getByText(/FII net buying today: \+2,450 Cr/i)).toBeTruthy()
    expect(screen.getByText('GEX Dealer Positioning')).toBeTruthy()
    expect(screen.getByText(/Negative GEX environment/i)).toBeTruthy()

    // Verify Trade Plan section rendered
    expect(screen.getByText(/Data-Driven Trade Plan/i)).toBeTruthy()
    expect(screen.getByText(/Structure Guidance:/i)).toBeTruthy()
  })

  it('toggles seamlessly between Table view and Cards view', () => {
    render(
      <ConvictionScoreCard
        underlying="NIFTY"
        spot={24500}
        pcr={1.12}
        convictionScore={mockScoreData}
      />
    )

    // Expand
    const headerBtn = screen.getByTitle(/Click to toggle 12-factor orthogonal breakdown/i)
    fireEvent.click(headerBtn)

    // Click "☰ Cards" toggle button
    const cardsToggle = screen.getByRole('button', { name: /Cards/i })
    fireEvent.click(cardsToggle)

    // In card mode, table element should not exist
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByText('FII/DII Cash Flow Streak')).toBeTruthy()

    // Click "☷ Table" toggle button to return to table
    const tableToggle = screen.getByRole('button', { name: /Table/i })
    fireEvent.click(tableToggle)

    // Table should be restored
    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getByText(/Live Empirical Reading/i)).toBeTruthy()
  })

  it('filters factors when an axis pill is selected', () => {
    render(
      <ConvictionScoreCard
        underlying="NIFTY"
        spot={24500}
        pcr={1.12}
        convictionScore={mockScoreData}
      />
    )

    // Expand
    const headerBtn = screen.getByTitle(/Click to toggle 12-factor orthogonal breakdown/i)
    fireEvent.click(headerBtn)

    // All factors initially present
    expect(screen.getByText('FII/DII Cash Flow Streak')).toBeTruthy()
    expect(screen.getByText('India VIX Direction & Level')).toBeTruthy()
    expect(screen.getByText('GEX Dealer Positioning')).toBeTruthy()

    // Filter by Options Intel axis
    const optionsAxisBtn = screen.getByRole('button', { name: /Options Intel/i })
    fireEvent.click(optionsAxisBtn)

    // Options factor should remain, but others should be filtered out
    expect(screen.getByText('GEX Dealer Positioning')).toBeTruthy()
    expect(screen.queryByText('FII/DII Cash Flow Streak')).toBeNull()
    expect(screen.queryByText('India VIX Direction & Level')).toBeNull()

    // Reset back to All Factors
    const allBtn = screen.getByRole('button', { name: /All 12 Factors/i })
    fireEvent.click(allBtn)
    expect(screen.getByText('FII/DII Cash Flow Streak')).toBeTruthy()
    expect(screen.getByText('India VIX Direction & Level')).toBeTruthy()
  })
})
