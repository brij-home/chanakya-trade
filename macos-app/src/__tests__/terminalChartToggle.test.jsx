import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import TerminalView from '../renderer/src/components/Views/TerminalView'
import ContextBar from '../renderer/src/components/Shell/ContextBar'
import { useChatStore } from '../renderer/src/store/chatStore'

// Mock ResizeObserver
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Mock CandlestickChart so we don't render canvas in jsdom
vi.mock('../renderer/src/components/Charts/CandlestickChart', () => {
  return {
    default: ({ symbol, timeframe }) => (
      <div data-testid="mock-candlestick-chart">
        Chart for {symbol} ({timeframe})
      </div>
    ),
  }
})

describe('TerminalView Chart Toggle & Default Hidden State', () => {
  beforeEach(() => {
    useChatStore.setState({
      terminalShowChart: false,
      activeView: 'terminal',
      selectedSymbol: 'NIFTY',
    })

    global.fetch = vi.fn().mockImplementation((url) => {
      const urlStr = String(url)
      if (urlStr.includes('/skills/dashboard_snapshot')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              data: {
                symbol: 'NIFTY',
                exchange: 'NSE',
                ltp: 24500,
                change_pct: 0.5,
                automated_setup: {
                  symbol: 'NIFTY (NSE)',
                  action: 'LONG (BUY)',
                  entry: 24480,
                  stop_loss: 24360,
                  target_1: 24720,
                  status: 'READY',
                },
                order_block: { bottom: 24400, top: 24450 },
                volume_profile: { poc: 24460, vah: 24520, val: 24380 },
                watchlist: [],
                flows: { fii_net: 0, dii_net: 0, net_total: 0 },
                sector_matrix: [],
              },
              status: 'ok',
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
  })

  it('keeps chart hidden by default and renders collapsed banner', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    // The chart canvas should NOT be rendered
    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()

    // The collapsed banner must be visible
    expect(screen.getByText(/Interactive Chart Hidden/i)).toBeTruthy()

    // Both Show Chart buttons should exist (Header badge & Collapsed banner button)
    const showBtns = screen.getAllByRole('button', { name: /Show Chart/i })
    expect(showBtns.length).toBeGreaterThanOrEqual(2)

    // The toolbar button should indicate Chart OFF
    expect(screen.getByRole('button', { name: /Chart OFF/i })).toBeTruthy()
  })

  it('toggles chart ON when clicking Show Chart banner button and displays CandlestickChart', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()

    // Click the collapsed banner button to show chart
    const showBtns = screen.getAllByRole('button', { name: /Show Chart/i })
    await act(async () => {
      fireEvent.click(showBtns[1])
    })

    // Chart should now be visible
    expect(screen.getByTestId('mock-candlestick-chart')).toBeTruthy()

    // Buttons should now indicate Chart ON / HIDE CHART
    expect(screen.getByRole('button', { name: /Chart ON/i })).toBeTruthy()
    const hideBtns = screen.getAllByRole('button', { name: /Hide Chart/i })
    expect(hideBtns.length).toBeGreaterThanOrEqual(2)

    // Clicking Hide Chart collapses it back
    await act(async () => {
      fireEvent.click(hideBtns[0])
    })

    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()
    expect(screen.getByText(/Interactive Chart Hidden/i)).toBeTruthy()
  })

  it('toggles chart via top toolbar Chart OFF / ON button', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()

    const toolbarBtn = screen.getByRole('button', { name: /Chart OFF/i })
    await act(async () => {
      fireEvent.click(toolbarBtn)
    })

    expect(screen.getByTestId('mock-candlestick-chart')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Chart ON/i })).toBeTruthy()

    // Click again to turn off
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Chart ON/i }))
    })

    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()
    expect(screen.getByRole('button', { name: /Chart OFF/i })).toBeTruthy()
  })

  it('toggles chart via ContextBar quick toggle button', async () => {
    await act(async () => {
      render(<ContextBar />)
    })

    const toggleBtn = screen.getByRole('button', { name: /Chart OFF/i })
    expect(toggleBtn).toBeTruthy()

    await act(async () => {
      fireEvent.click(toggleBtn)
    })

    expect(useChatStore.getState().terminalShowChart).toBe(true)
    expect(screen.getByRole('button', { name: /Chart ON/i })).toBeTruthy()
  })
})
