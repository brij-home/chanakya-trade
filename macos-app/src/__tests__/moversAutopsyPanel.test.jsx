import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import MoversAutopsyPanel from '../renderer/src/components/Views/MoversAutopsyPanel'

// Mock useAPI
const mockCall = vi.fn()
vi.mock('../renderer/src/hooks/useAPI', () => ({
  useAPI: () => ({ call: mockCall }),
}))

// Mock useChatStore
const mockSendDraft = vi.fn()
const mockSetActiveView = vi.fn()
vi.mock('../renderer/src/store/chatStore', () => ({
  useChatStore: (selector) =>
    selector({
      sendDraft: mockSendDraft,
      setActiveView: mockSetActiveView,
    }),
}))

describe('MoversAutopsyPanel - Precursors & Institutional Mover Autopsies', () => {
  const sampleAutopsyData = {
    date: '2026-09-09',
    market_regime: 'NORMAL',
    gainers_count: 2,
    losers_count: 1,
    gainers: [
      {
        symbol: 'TATAMOTORS',
        exchange: 'NSE',
        change_pct: 6.8,
        turnover_cr: 850.4,
        is_trap: false,
        trap_reason: null,
        causal_attribution: 'Volume Contraction + RRG Leading Rotation',
        rvol: 3.4,
        coiling_score: 88,
        rrg_quadrant: 'LEADING',
        pre_move_setup: {
          vcp_forming: true,
          volume_dry_up: true,
          order_block_retest: true,
        },
      },
      {
        symbol: 'PENNYPUMP',
        exchange: 'NSE',
        change_pct: 19.9,
        turnover_cr: 2.1,
        is_trap: true,
        trap_reason: 'TRAP_LOW_LIQUIDITY_PUMP: Turnover ₹2.10 Cr < ₹10 Cr min institutional gate',
        causal_attribution: 'Operator Pump',
        rvol: 0.8,
        coiling_score: 20,
        rrg_quadrant: 'LAGGING',
        pre_move_setup: {
          vcp_forming: false,
          volume_dry_up: false,
          order_block_retest: false,
        },
      },
    ],
    losers: [
      {
        symbol: 'INFY',
        exchange: 'NSE',
        change_pct: -4.2,
        turnover_cr: 1200.5,
        is_trap: false,
        trap_reason: null,
        causal_attribution: 'Long Unwinding + Nasdaq Breakdown',
        rvol: 2.1,
        coiling_score: 75,
        rrg_quadrant: 'WEAKENING',
        pre_move_setup: {
          vcp_forming: false,
          volume_dry_up: false,
          order_block_retest: false,
        },
      },
    ],
    factor_snr_contrast: {
      volume_dry_up: { contrast_delta: 0.42, significant: true },
      vcp_pattern: { contrast_delta: 0.38, significant: true },
      order_block_confluence: { contrast_delta: 0.28, significant: true },
    },
    top_predictive_precursors: ['volume_dry_up', 'vcp_pattern'],
  }

  const samplePrecursors = [
    {
      symbol: 'BHARTIARTL',
      exchange: 'NSE',
      direction: 'BULLISH',
      ltp: 1620.0,
      conviction_score: 85,
      verdict: 'MAX_CONVICTION',
      sector_name: 'Telecom',
      rrg_quadrant: 'LEADING',
      turnover_cr: 420.0,
      matched_factors: [
        'Extreme Volume Dry-Up (20% of 20D SMA)',
        'Bollinger Bands tightly compressed in Keltner Squeeze (3 sessions coiled)',
      ],
      entry_range: '₹1,615.0 – ₹1,625.0',
      stop_loss: 1590.0,
      target_1: 1665.0,
      target_2: 1710.0,
      risk_reward: '1:3.0',
      coiling_pivot_high: 1625.0,
      when_to_buy: 'Break above ₹1,625 with expanding 15m volume',
      when_to_wait: 'DO NOT CHASE if price gaps past ₹1,635.0 without retest',
      profit_rule: 'Book 50% at T1 (₹1665.0), move SL to breakeven',
      closest_archetype: 'TRENT / ADANIENT VCP Precursor',
    },
  ]

  const sampleAsymmetricOpps = [
    {
      symbol: 'TRENT',
      exchange: 'NSE',
      segment: 'FNO',
      setup_type: 'POCKET_PIVOT',
      conviction_score: 88,
      verdict: 'HIGH_CONVICTION',
      ltp: 7120.0,
      entry_range: '₹7,110.0 – ₹7,140.0',
      stop_loss: 6980.0,
      target_1: 7400.0,
      target_2: 7680.0,
      moonshot_target: 7960.0,
      risk_reward_ratio: 4.0,
      risk_pts: 140.0,
      reward_t1_pts: 280.0,
      confluences: [
        'Pocket Pivot volume signature',
        'Tight base coiling < 12% width',
        'RRG Leading momentum',
      ],
      entry_rule: 'Enter inside base off 10-EMA support.',
      no_chase_rule: 'DO NOT CHASE if price exceeds ₹7,140.0.',
      profit_rule: 'Scale 40% at T1, 40% at T2, trail 20% runner.',
    },
  ]

  beforeEach(() => {
    mockCall.mockReset()
    mockCall.mockImplementation((endpoint) => {
      if (endpoint?.startsWith('/api/movers/autopsy')) {
        return Promise.resolve({ data: sampleAutopsyData })
      }
      if (endpoint?.startsWith('/api/movers/precursors')) {
        return Promise.resolve({ data: samplePrecursors })
      }
      if (endpoint?.startsWith('/api/opportunities/asymmetric')) {
        return Promise.resolve({ data: sampleAsymmetricOpps })
      }
      if (endpoint === '/api/movers/autopsy/run') {
        return Promise.resolve({ data: sampleAutopsyData })
      }
      return Promise.resolve({ data: null })
    })
  })

  it('renders Precursor Radar cards with conviction score, setup tags, and execution blueprint', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    // Conviction score badge
    expect(screen.getByText(/85\/100/)).toBeTruthy()
    expect(screen.getByText('MAX_CONVICTION')).toBeTruthy()

    // Matched factors
    expect(screen.getByText(/Extreme Volume Dry-Up/i)).toBeTruthy()
    expect(screen.getByText(/Bollinger Bands tightly compressed/i)).toBeTruthy()

    // Execution blueprint items
    expect(screen.getByText(/₹1,615\.0 – ₹1,625\.0/)).toBeTruthy()
    expect(screen.getByText(/₹1590/)).toBeTruthy()
    expect(screen.getByText(/₹1665/)).toBeTruthy()
    expect(screen.getByText(/1:3\.0/)).toBeTruthy()

    // No chase rule
    expect(screen.getByText(/DO NOT CHASE if price gaps past/i)).toBeTruthy()
  })

  it('switches to Mover Autopsies tab and displays causal factor decomposition', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    const autopsyTabBtn = screen.getByRole('button', { name: /Top Movers Autopsy/i })
    fireEvent.click(autopsyTabBtn)

    await waitFor(() => {
      expect(screen.getByText('TATAMOTORS')).toBeTruthy()
    })

    expect(screen.getByText('+6.8%')).toBeTruthy()
    expect(screen.getByText(/Volume Contraction \+ RRG Leading Rotation/i)).toBeTruthy()
    expect(screen.getByText(/LEADING/)).toBeTruthy()
  })

  it('switches to Filtered Traps tab and displays quarantined manipulation setups', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    const trapsTabBtn = screen.getByRole('button', { name: /Traps Filtered/i })
    fireEvent.click(trapsTabBtn)

    await waitFor(() => {
      expect(screen.getByText('PENNYPUMP')).toBeTruthy()
    })

    expect(screen.getByText(/Turnover ₹2\.10 Cr < ₹10 Cr min institutional gate/i)).toBeTruthy()
  })

  it('triggers on-demand autopsy calculation when clicking Run Autopsy Scan button', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    const runBtn = screen.getByRole('button', { name: /Run Autopsy Scan Now/i })
    fireEvent.click(runBtn)

    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith('/api/movers/autopsy/run', { top_n: 10 }, { method: 'POST' })
    })
  })

  it('renders universe switcher bar and allows switching between F&O, Cash, and Indices', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    // Verify universe switcher buttons exist
    const allBtn = screen.getByRole('button', { name: /All Universes/i })
    const fnoBtn = screen.getByRole('button', { name: /F&O Derivatives/i })
    const cashBtn = screen.getByRole('button', { name: /Non-F&O Cash/i })
    const indexBtn = screen.getByRole('button', { name: /Indices/i })

    expect(allBtn).toBeTruthy()
    expect(fnoBtn).toBeTruthy()
    expect(cashBtn).toBeTruthy()
    expect(indexBtn).toBeTruthy()

    // Click F&O Derivatives
    fireEvent.click(fnoBtn)
    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith('/api/movers/autopsy?segment=FNO', {}, { method: 'GET' })
      expect(mockCall).toHaveBeenCalledWith('/api/movers/precursors?limit=8&segment=FNO', {}, { method: 'GET' })
    })

    // Click Non-F&O Cash
    fireEvent.click(cashBtn)
    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith('/api/movers/autopsy?segment=NON_FNO', {}, { method: 'GET' })
      expect(mockCall).toHaveBeenCalledWith('/api/movers/precursors?limit=8&segment=NON_FNO', {}, { method: 'GET' })
    })

    // Click Indices
    fireEvent.click(indexBtn)
    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith('/api/movers/autopsy?segment=INDEX', {}, { method: 'GET' })
      expect(mockCall).toHaveBeenCalledWith('/api/movers/precursors?limit=8&segment=INDEX', {}, { method: 'GET' })
    })
  })

  it('switches to Asymmetric Setups tab and displays low risk : high reward cards (1:3+ R:R)', async () => {
    render(<MoversAutopsyPanel onOpenOrderTicket={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('BHARTIARTL')).toBeTruthy()
    })

    const asymTabBtn = screen.getByRole('button', { name: /Asymmetric Setups/i })
    fireEvent.click(asymTabBtn)

    await waitFor(() => {
      expect(screen.getByText('TRENT')).toBeTruthy()
    })

    expect(screen.getByText(/1:4\.0 R:R/i)).toBeTruthy()
    expect(screen.getAllByText(/Pocket Pivot/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/₹7,110\.0 – ₹7,140\.0/)).toBeTruthy()
    expect(screen.getByText(/₹6980/)).toBeTruthy()
    expect(screen.getByText(/₹7400/)).toBeTruthy()
    expect(screen.getByText(/Place Asymmetric Order/i)).toBeTruthy()
  })
})
