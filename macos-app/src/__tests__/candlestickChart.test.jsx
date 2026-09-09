import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, act } from '@testing-library/react'

if (typeof window !== 'undefined') {
  global.ResizeObserver =
    global.ResizeObserver ||
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
}

// Mock lightweight-charts
vi.mock('lightweight-charts', () => {
  const mockSeries = {
    setData: vi.fn(),
    update: vi.fn(),
    setMarkers: vi.fn(),
    createPriceLine: vi.fn(() => ({})),
    removePriceLine: vi.fn(),
    priceToCoordinate: vi.fn(() => 100),
    priceScale: () => ({ applyOptions: vi.fn() }),
  }

  const mockTimeScale = {
    fitContent: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    subscribeVisibleTimeRangeChange: vi.fn(),
    setVisibleLogicalRange: vi.fn(),
  }

  const mockChart = {
    addSeries: vi.fn(() => mockSeries),
    addLineSeries: vi.fn(() => mockSeries),
    addCandlestickSeries: vi.fn(() => mockSeries),
    addHistogramSeries: vi.fn(() => mockSeries),
    timeScale: () => mockTimeScale,
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }

  return {
    createChart: vi.fn(() => mockChart),
    ColorType: { Solid: 'solid' },
    CandlestickSeries: 'CandlestickSeries',
    HistogramSeries: 'HistogramSeries',
    LineSeries: 'LineSeries',
  }
})

describe('CandlestickChart Component', () => {
  it('starts with Stochastic RSI disabled by default (opacity-70 toggle pill)', async () => {
    const CandlestickChart = (await import('../renderer/src/components/Charts/CandlestickChart')).default
    let res
    await act(async () => {
      res = render(<CandlestickChart symbol="NIFTY" exchange="NSE" height={280} />)
    })

    const stochBtn = res.getByTitle(/Stochastic RSI Indicator/i)
    expect(stochBtn).toBeTruthy()
    // Stoch RSI starts disabled with the opacity-70 inactive CSS class
    expect(stochBtn.className).toContain('opacity-70')
    expect(stochBtn.className).not.toContain('bg-cyan-500/20')
  })
})
