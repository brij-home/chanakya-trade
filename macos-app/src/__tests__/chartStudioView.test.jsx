import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import ChartStudioView from '../renderer/src/components/Views/ChartStudioView'
import { useChatStore } from '../renderer/src/store/chatStore'

// Mock ResizeObserver
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Mock CandlestickChart so canvas isn't rendered in jsdom
vi.mock('../renderer/src/components/Charts/CandlestickChart', () => {
  return {
    default: ({ symbol, timeframe }) => (
      <div data-testid="mock-candlestick-chart">
        Chart for {symbol} ({timeframe})
      </div>
    ),
  }
})

describe('ChartStudioView Component', () => {
  beforeEach(() => {
    useChatStore.setState({
      activeView: 'charts',
      selectedSymbol: 'NIFTY',
    })

    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            data: {
              symbol: 'NIFTY',
              live_quote: { ltp: 24500, change_pct: 0.75 },
              order_block: { bottom: 24400, top: 24450 },
              volume_profile: { poc: 24460, vah: 24520, val: 24380 },
              atr: 120,
              target_1: 24740,
              stop_loss: 24320,
            },
            status: 'ok',
          }),
      })
    )
  })

  it('renders full-screen chart canvas with symbol and timeframe controls', async () => {
    await act(async () => {
      render(<ChartStudioView initialSymbol="NIFTY" initialTimeframe="15m" />)
    })

    expect(screen.getByTestId('mock-candlestick-chart')).toBeTruthy()
    expect(screen.getByText('15m')).toBeTruthy()
    expect(screen.getByText('1D')).toBeTruthy()
    expect(screen.getByText('1W')).toBeTruthy()
  })

  it('switches between single and dual timeframe split', async () => {
    await act(async () => {
      render(<ChartStudioView initialSymbol="NIFTY" initialTimeframe="15m" />)
    })

    const dualBtn = screen.getByRole('button', { name: /Dual-TF/i })
    await act(async () => {
      fireEvent.click(dualBtn)
    })

    // Should render two mock charts in dual mode (15m and 1D)
    const charts = screen.getAllByTestId('mock-candlestick-chart')
    expect(charts.length).toBe(2)
  })

  it('renders sidecar intelligence deck with order actions', async () => {
    const handleOrder = vi.fn()
    await act(async () => {
      render(<ChartStudioView initialSymbol="NIFTY" onOpenOrderTicket={handleOrder} />)
    })

    expect(screen.getByText(/Market Intelligence & Order/i)).toBeTruthy()
    const buyBtn = screen.getByRole('button', { name: /Buy \/ Long/i })
    expect(buyBtn).toBeTruthy()

    await act(async () => {
      fireEvent.click(buyBtn)
    })

    expect(handleOrder).toHaveBeenCalledTimes(1)
  })
})
