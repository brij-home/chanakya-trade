import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AlertsView from '../renderer/src/components/Views/AlertsView'

// Mock useAPI hook
const mockCall = vi.fn()
vi.mock('../renderer/src/hooks/useAPI', () => ({
  useAPI: () => ({ call: mockCall }),
}))

// Mock matchMedia and ResizeObserver
if (typeof window !== 'undefined') {
  window.matchMedia =
    window.matchMedia ||
    function () {
      return {
        matches: false,
        addListener: function () {},
        removeListener: function () {},
        addEventListener: function () {},
        removeEventListener: function () {},
        dispatchEvent: function () {},
      }
    }

  global.ResizeObserver =
    global.ResizeObserver ||
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
}

describe('AlertsView - Institutional Active/Archived standard & Derivative Clarity', () => {
  const sampleAutoAlerts = [
    // 1. Active Option Trade (Weekly CE)
    {
      alert_id: 'alert-opt-active-1',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      symbol: 'NIFTY',
      exchange: 'NSE',
      direction: 'BULLISH',
      headline: 'NIFTY 24500 CE Gamma Blast Breakout',
      summary: 'Aggressive Call writing short covering explosion underway',
      ltp: 145.5,
      trigger_level: 140.0,
      target_level: 210.0,
      stop_loss: 110.0,
      strike: 24500,
      option_type: 'CE',
      contract_symbol: 'NIFTY2691124500CE',
      expiry_date: '2026-09-11',
      expiry_type: 'WEEKLY',
      underlying_spot: 24580.0,
      option_premium: 145.5,
      is_active: true,
      is_archived: false,
      is_invalidated: false,
      target_status: 'PENDING',
      confidence: 90,
      created_at: '2026-09-09 13:30:00',
    },
    // 2. Active Future Trade (Monthly Long Future)
    {
      alert_id: 'alert-fut-active-2',
      alert_type: 'SQUEEZE_BREAKOUT',
      stage: 'IGNITED',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      direction: 'BULLISH',
      headline: 'RELIANCE Sep Future Squeeze Breakout',
      summary: 'Coiling broken out with expanding RVOL',
      ltp: 3025.0,
      trigger_level: 3010.0,
      target_level: 3120.0,
      stop_loss: 2975.0,
      contract_symbol: 'RELIANCE26SEPFUT',
      expiry_date: '2026-09-24',
      expiry_type: 'MONTHLY',
      underlying_spot: 3015.0,
      option_premium: 3025.0,
      is_active: true,
      is_archived: false,
      is_invalidated: false,
      target_status: 'PENDING',
      confidence: 88,
      created_at: '2026-09-09 13:45:00',
    },
    // 3. Inactive / Archived Trade (Invalidated setup)
    {
      alert_id: 'alert-invalidated-3',
      alert_type: 'SMC_SWEEP',
      stage: 'INVALIDATED',
      symbol: 'TCS',
      exchange: 'NSE',
      direction: 'BEARISH',
      headline: 'TCS Order Block Failure',
      summary: 'Invalidated as price surged past invalidation SL',
      ltp: 4420.0,
      trigger_level: 4380.0,
      target_level: 4200.0,
      stop_loss: 4410.0,
      is_active: false,
      is_archived: true,
      is_invalidated: true,
      invalidation_reason: 'Stop loss breached at 4410.0',
      target_status: 'PENDING',
      confidence: 70,
      created_at: '2026-09-08 10:00:00',
    },
    // 4. Inactive / Archived Trade (Target Achieved)
    {
      alert_id: 'alert-target-hit-4',
      alert_type: 'GAMMA_BLAST',
      stage: 'TARGET_ACHIEVED',
      symbol: 'INFY',
      exchange: 'NSE',
      direction: 'BULLISH',
      headline: 'INFY 1900 CE Final Target Achieved',
      summary: 'Target hit, full profit booked',
      ltp: 65.0,
      trigger_level: 35.0,
      target_level: 65.0,
      stop_loss: 25.0,
      strike: 1900,
      option_type: 'CE',
      contract_symbol: 'INFY26SEP1900CE',
      expiry_date: '2026-09-24',
      expiry_type: 'MONTHLY',
      underlying_spot: 1945.0,
      option_premium: 65.0,
      is_active: false,
      is_archived: true,
      is_invalidated: false,
      target_status: 'TARGET_ACHIEVED',
      confidence: 95,
      created_at: '2026-09-08 11:30:00',
    },
  ]

  beforeEach(() => {
    mockCall.mockReset()
    mockCall.mockImplementation((endpoint) => {
      if (endpoint === '/skills/alerts/list') {
        return Promise.resolve({ data: [] })
      }
      if (endpoint === '/skills/alerts/auto/list') {
        return Promise.resolve({ data: sampleAutoAlerts })
      }
      if (endpoint === '/skills/alerts/auto/archive') {
        return Promise.resolve({ status: 'ok' })
      }
      if (endpoint === '/skills/alerts/auto/cleanup') {
        return Promise.resolve({
          status: 'ok',
          data: { purged_count: 2, remaining_count: 2, max_age_days: 3 },
        })
      }
      if (endpoint === '/skills/quotes/batch') {
        return Promise.resolve({
          status: 'ok',
          // Flat dict: backend now returns _ok(out) — both sym_clean and NSE:sym keys present
          // extractQuotes() in AlertsView handles both flat and { quotes: {...} } wrapped formats
          data: {
            NIFTY: { ltp: 24650.0, change: 70.0, change_pct: 0.28, high: 24700.0, low: 24550.0 },
            'NSE:NIFTY': { ltp: 24650.0, change: 70.0, change_pct: 0.28, high: 24700.0, low: 24550.0 },
            RELIANCE: { ltp: 3040.0, change: 25.0, change_pct: 0.83, high: 3050.0, low: 3010.0 },
            'NSE:RELIANCE': { ltp: 3040.0, change: 25.0, change_pct: 0.83, high: 3050.0, low: 3010.0 },
            NIFTY2691124500CE: { ltp: 165.5, change: 20.0, change_pct: 13.75 },
            'NFO:NIFTY2691124500CE': { ltp: 165.5, change: 20.0, change_pct: 13.75 },
            RELIANCE26SEPFUT: { ltp: 3055.0, change: 30.0, change_pct: 0.99 },
            'NFO:RELIANCE26SEPFUT': { ltp: 3055.0, change: 30.0, change_pct: 0.99 },
          },
        })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('renders Active Valid Trades by default and filters out archived clutter', async () => {
    render(<AlertsView />)

    // Verify Active Mode button is active by default with count
    await waitFor(() => {
      expect(screen.getByText(/Active Valid Trades/i)).toBeTruthy()
    })
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1) // 2 active trades badge

    // Both active trades (NIFTY option & RELIANCE future) should be visible
    expect(screen.getByText('NIFTY')).toBeTruthy()
    expect(screen.getByText('RELIANCE')).toBeTruthy()

    // Archived/Invalidated trades should NOT be visible in Active mode
    expect(screen.queryByText('TCS')).toBeNull()
    expect(screen.queryByText('INFY')).toBeNull()
  })

  it('displays crystal clear Option details (strike, premium LTP vs spot, direction, weekly contract, moneyness)', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    // Direction & Option Type
    expect(screen.getByText(/CALL OPTION \(CE\)/i)).toBeTruthy()

    // Strike specification
    expect(screen.getByText(/Strike: ₹24,500/i)).toBeTruthy()

    expect(screen.getByText(/WEEKLY CONTRACT/i)).toBeTruthy()
    expect(screen.getByText(/2026-09-11/i)).toBeTruthy()
    expect(screen.getByText('[ITM]')).toBeTruthy()
    expect(screen.getByText(/Option Premium \(LTP\)/i)).toBeTruthy()
    expect(screen.getAllByText(/₹(165\.50|145\.50)/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/Underlying Spot/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/₹(24,650\.0|24,580\.0)/).length).toBeGreaterThanOrEqual(1)
  })

  it('displays crystal clear Future details (long future direction, future price LTP vs spot, monthly contract)', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('RELIANCE')).toBeTruthy()
    })

    expect(screen.getByText(/LONG FUTURE \(BUY\)/i)).toBeTruthy()
    expect(screen.getByText(/MONTHLY CONTRACT/i)).toBeTruthy()
    expect(screen.getByText(/Futures Price \(LTP\)/i)).toBeTruthy()
    expect(screen.getAllByText(/₹(3,055\.00|3,025\.00)/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/₹(3,040\.0|3,015\.0)/).length).toBeGreaterThanOrEqual(1)
  })

  it('switches to Archived & History mode to view archived and completed setups', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText(/Archived & History/i)).toBeTruthy()
    })

    fireEvent.click(screen.getByText(/Archived & History/i))

    expect(screen.getByText('TCS')).toBeTruthy()
    expect(screen.getByText('INFY')).toBeTruthy()
    expect(screen.queryByText('NIFTY')).toBeNull()
  })

  it('executes manual archive action when clicking Archive on an active card', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    const archiveBtns = screen.getAllByTitle('Archive trade to avoid clutter')
    expect(archiveBtns.length).toBeGreaterThanOrEqual(1)

    fireEvent.click(archiveBtns[0])

    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith(
        '/skills/alerts/auto/archive',
        expect.objectContaining({
          alert_id: 'alert-opt-active-1',
          archive: true,
        })
      )
    })
  })

  it('executes 3-day cleanup when clicking Clean >3d Old button and displays feedback toast', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText(/Clean >3d Old/i)).toBeTruthy()
    })

    const cleanBtn = screen.getByText(/Clean >3d Old/i)
    fireEvent.click(cleanBtn)

    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith(
        '/skills/alerts/auto/cleanup',
        expect.objectContaining({ max_age_days: 3 })
      )
    })

    await waitFor(() => {
      expect(screen.getByText(/Cleaned up 2 archived records older than 3 days/i)).toBeTruthy()
    })
  })

  it('streams real-time batch spot prices for active alerts and renders live pulse badge and live distance', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith(
        '/skills/quotes/batch',
        expect.objectContaining({
          symbols: expect.arrayContaining(['NIFTY', 'RELIANCE']),
        })
      )
    })

    await waitFor(() => {
      expect(screen.getAllByText(/24,650\.0/).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('preserves alert cards in-place without flashing full-screen loading state on periodic updates', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    expect(screen.queryByText(/Checking market feeds/i)).toBeNull()
    expect(screen.getByText('NIFTY')).toBeTruthy()
  })

  it('updates cards in-place and prevents duplicates when new live market alert arrives', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    window.dispatchEvent(
      new CustomEvent('new-market-alert', {
        detail: {
          alert: {
            ...sampleAutoAlerts[0],
            ltp: 185.0,
            headline: 'NIFTY 24500 CE [UPDATED] Gamma Blast Breakout',
          },
        },
      })
    )

    await waitFor(() => {
      expect(screen.getByText(/\[UPDATED\]/i)).toBeTruthy()
    })

    const afterNiftyHeaders = screen.getAllByText('NIFTY')
    expect(afterNiftyHeaders.length).toBe(1)
  })

  it('streams live option and future contract prices alongside underlying spot prices', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    await waitFor(() => {
      expect(mockCall).toHaveBeenCalledWith(
        '/skills/quotes/batch',
        expect.objectContaining({
          symbols: expect.arrayContaining(['NIFTY', 'RELIANCE', 'NIFTY2691124500CE', 'RELIANCE26SEPFUT']),
        })
      )
    })

    await waitFor(() => {
      expect(screen.getAllByText(/₹165\.50/).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/₹3,055\.00/).length).toBeGreaterThanOrEqual(1)
    })

    expect(screen.getAllByText(/₹24,650\.0/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/₹3,040\.0/).length).toBeGreaterThanOrEqual(1)
  })

  it('displays 5-tier Trade Execution Matrix (Entry, SL, T1, T2, T3) and Next Expiry Opportunity with justification', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    expect(screen.getAllByText(/Trade Execution Matrix & Target Milestones/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/⚡ Entry Trigger/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/🛑 Invalidation SL/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/🎯 Target 1 \(T1\)/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/🏁 Target 2 \(T2\)/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/🚀 Target 3 \(T3\)/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/Next Expiry Opportunity/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/Institutional Justification:/i).length).toBeGreaterThanOrEqual(1)
  })

  it('segregates F&O alerts vs Cash Equity alerts with market segment switcher and dedicated section headers', async () => {
    render(<AlertsView />)

    await waitFor(() => {
      expect(screen.getByText('NIFTY')).toBeTruthy()
    })

    expect(screen.getByRole('button', { name: /All Segments/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Derivatives & F&O/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Cash Equity/i })).toBeTruthy()
    expect(screen.getByText(/Institutional Derivatives & Options\/Futures Alerts/i)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Derivatives & F&O/i }))
    expect(screen.getByText(/Filtered to F&O Only/i)).toBeTruthy()
    expect(screen.getByText('NIFTY')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Cash Equity/i }))
    expect(screen.getByText(/Filtered to Cash Equity Only/i)).toBeTruthy()
  })
})
