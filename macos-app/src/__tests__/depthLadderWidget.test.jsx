import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DepthLadderWidget from '../renderer/src/components/Widgets/DepthLadderWidget'

describe('DepthLadderWidget — Institutional DOM Order Book Ladder', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('renders L2 depth book data, OBI meter, and resting fortress wall', async () => {
    const mockOrderBook = {
      status: 'success',
      data: {
        symbol: 'RELIANCE',
        timestamp: '2026-10-18T14:30:00Z',
        best_bid: 2950.0,
        best_ask: 2950.5,
        mid_price: 2950.25,
        spread: 0.5,
        spread_bps: 1.7,
        obi_5: 0.42,
        obi_50: 0.38,
        micro_price: 2950.35,
        has_resting_wall: true,
        wall_side: 'BID',
        wall_price: 2948.0,
        wall_qty: 25000,
        wall_ratio: 3.5,
        is_iceberg_suspected: true,
        broker_depth_status: 'LIVE_BROKER_L2',
        bids: [
          { price: 2950.0, qty: 1000, orders: 12 },
          { price: 2949.0, qty: 1500, orders: 20 },
          { price: 2948.0, qty: 35000, orders: 45 },
          { price: 2947.0, qty: 1200, orders: 10 },
          { price: 2946.0, qty: 1000, orders: 8 },
        ],
        asks: [
          { price: 2950.5, qty: 3000, orders: 8 },
          { price: 2951.0, qty: 4500, orders: 11 },
          { price: 2952.0, qty: 6000, orders: 15 },
          { price: 2953.0, qty: 5000, orders: 14 },
          { price: 2954.0, qty: 7000, orders: 18 },
        ],
      },
    }

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockOrderBook,
    })

    const onPriceSelect = vi.fn()

    render(
      <DepthLadderWidget
        symbol="NSE:RELIANCE"
        compact={false}
        onPriceSelect={onPriceSelect}
        currentPrice={2950.25}
        stopLoss={2935.0}
        target={2980.0}
      />
    )

    // Wait for depth data to populate
    await waitFor(() => {
      expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    })

    // Check symbol and provenance badge
    expect(screen.getByText(/LIVE L2/i)).toBeInTheDocument()

    // Check OBI meter rendering
    expect(screen.getByText(/0\.42/i)).toBeInTheDocument()

    // Check Fortress Wall badge (>= 2.8x average depth)
    expect(screen.getByText(/4\.4x/i)).toBeInTheDocument()

    // Check Iceberg suspected badge
    expect(screen.getByText(/ICEBERG/i)).toBeInTheDocument()

    // Check Spread and Mid-Price
    expect(screen.getByText(/1\.7 bps/i)).toBeInTheDocument()

    // Check price selection on click
    const bidRow = screen.getByText('₹2950.00')
    fireEvent.click(bidRow)
    expect(onPriceSelect).toHaveBeenCalledWith(2950.0)
  })

  it('renders synthetic L1 fallback banner gracefully when live L2 is unavailable', async () => {
    const mockFallbackBook = {
      status: 'success',
      data: {
        symbol: 'TCS',
        best_bid: 3800.0,
        best_ask: 3801.0,
        mid_price: 3800.5,
        spread: 1.0,
        spread_bps: 2.6,
        obi_5: -0.15,
        broker_depth_status: 'SYNTHETIC_L1_DISCONNECTED',
        bids: [{ price: 3800.0, qty: 100, orders: 1 }],
        asks: [{ price: 3801.0, qty: 100, orders: 1 }],
      },
    }

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockFallbackBook,
    })

    render(<DepthLadderWidget symbol="TCS" compact={true} />)

    await waitFor(() => {
      expect(screen.getByText(/SIM DEPTH/i)).toBeInTheDocument()
    })
  })

  it('renders Option Greeks ribbon when viewing an option contract with Greeks', async () => {
    const mockOptionBook = {
      status: 'success',
      data: {
        symbol: 'NIFTY26OCT25000CE',
        best_bid: 145.0,
        best_ask: 145.5,
        mid_price: 145.25,
        spread: 0.5,
        spread_bps: 34.4,
        obi_5: 0.25,
        broker_depth_status: 'LIVE_BROKER_L2',
        greeks: {
          delta: 0.52,
          gamma: 0.0012,
          theta: -14.5,
          vega: 18.2,
          iv_pct: 13.8,
          spot: 25050,
          strike: 25000,
          option_type: 'CE',
        },
        bids: [{ price: 145.0, qty: 500, orders: 4 }],
        asks: [{ price: 145.5, qty: 650, orders: 5 }],
      },
    }

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockOptionBook,
    })

    render(<DepthLadderWidget symbol="NFO:NIFTY26OCT25000CE" compact={true} />)

    await waitFor(() => {
      expect(screen.getByText(/CE ₹25000/i)).toBeInTheDocument()
    })

    expect(screen.getByText('0.52')).toBeInTheDocument()
    expect(screen.getByText(/13\.8%/i)).toBeInTheDocument()
  })
})
