import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import OpsDeckView from '../renderer/src/components/Views/OpsDeckView'

const mockRadarData = {
  status: 'ok',
  segment: 'ALL',
  count: 3,
  data: [
    {
      symbol: 'NIFTY',
      segment: 'INDEX_FNO',
      ltp: 22850.0,
      spread: 0.5,
      spread_bps: 0.2,
      spread_status: 'TIGHT',
      total_bid_qty: 45000,
      total_ask_qty: 18000,
      bid_notional_cr: 10.28,
      ask_notional_cr: 4.11,
      notional_ratio: 2.5,
      obi: 0.43,
      obi_pct: 43.0,
      micro_price: 22851.2,
      micro_skew_bps: 0.5,
      has_resting_wall: true,
      wall_side: 'BID',
      wall_price: 22840.0,
      wall_qty: 32000,
      wall_ratio: 3.2,
      iceberg_detected: false,
      iceberg_side: null,
      iceberg_price: null,
      decision_intel: {
        bias: 'BULLISH',
        badge: '🛡️ BULLISH DEMAND FLOOR',
        tag: 'WALL BID (3.2x)',
        headline: 'Resting Buy Floor @ ₹22,840.00 (3.2x depth)',
        meaning: 'Institutional demand absorbing sell volume.',
        decision: 'FAVOR CALLS / LONGS: Anchor Invalidation Stop-Loss below ₹22,840.',
      },
      bids: [{ price: 22850.0, quantity: 1500, orders: 12 }],
      asks: [{ price: 22850.5, quantity: 900, orders: 8 }],
      provenance: 'LIVE_STREAM_L2',
      updated_at: '16:40:00',
    },
    {
      symbol: 'RELIANCE',
      segment: 'STOCK_FNO',
      ltp: 2950.0,
      spread: 0.25,
      spread_bps: 0.8,
      spread_status: 'TIGHT',
      total_bid_qty: 62000,
      total_ask_qty: 15000,
      bid_notional_cr: 18.29,
      ask_notional_cr: 4.42,
      notional_ratio: 4.14,
      obi: 0.61,
      obi_pct: 61.0,
      micro_price: 2950.8,
      micro_skew_bps: 2.7,
      has_resting_wall: false,
      wall_side: null,
      wall_price: null,
      wall_ratio: 1.0,
      iceberg_detected: false,
      iceberg_side: null,
      iceberg_price: null,
      decision_intel: {
        bias: 'BULLISH',
        badge: '🟢 AGGRESSIVE BUY PRESSURE',
        tag: 'OBI +61%',
        headline: 'Buyers Stacking Bids (+61.0% OBI)',
        meaning: 'Bids heavily dominate asks across top 5 depth levels.',
        decision: 'FAVOR LONGS / MOMENTUM: Breakout probability elevated.',
      },
      bids: [{ price: 2950.0, quantity: 5000, orders: 24 }],
      asks: [{ price: 2950.25, quantity: 1200, orders: 9 }],
      provenance: 'LIVE_BROKER_L2',
      updated_at: '16:40:00',
    },
    {
      symbol: 'INFY',
      segment: 'STOCK_FNO',
      ltp: 1820.0,
      spread: 0.5,
      spread_bps: 2.7,
      spread_status: 'MODERATE',
      total_bid_qty: 12000,
      total_ask_qty: 38000,
      bid_notional_cr: 2.18,
      ask_notional_cr: 6.91,
      notional_ratio: 0.32,
      obi: -0.52,
      obi_pct: -52.0,
      micro_price: 1819.2,
      micro_skew_bps: -4.4,
      has_resting_wall: true,
      wall_side: 'ASK',
      wall_price: 1825.0,
      wall_qty: 24000,
      wall_ratio: 3.5,
      iceberg_detected: false,
      iceberg_side: null,
      iceberg_price: null,
      decision_intel: {
        bias: 'BEARISH',
        badge: '🏰 BEARISH SUPPLY CEILING',
        tag: 'WALL ASK (3.5x)',
        headline: 'Resting Sell Wall @ ₹1,825.00 (3.5x depth)',
        meaning: 'Heavy institutional limit sell orders clustered.',
        decision: 'FAVOR PUTS / SHORTS: Take profit on calls.',
      },
      bids: [{ price: 1820.0, quantity: 800, orders: 5 }],
      asks: [{ price: 1820.5, quantity: 3200, orders: 18 }],
      provenance: 'LIVE_BROKER_L2',
      updated_at: '16:40:00',
    },
  ],
}

describe('OpsDeckView — Universe Depth Radar Master-Detail Integration', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/api/market/depth-radar')) {
          return Promise.resolve({
            ok: true,
            json: async () => mockRadarData,
          })
        }
        if (urlStr.includes('/api/market/order-book/')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: 'ok',
              data: {
                symbol: 'RELIANCE',
                ltp: 2950.0,
                spread: 0.25,
                bids: [{ price: 2950.0, quantity: 5000, orders: 24 }],
                asks: [{ price: 2950.25, quantity: 1200, orders: 9 }],
                obi_weighted: 0.61,
                provenance: 'LIVE_BROKER_L2',
              },
            }),
          })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            timestamp: new Date().toISOString(),
            status: 'HEALTHY',
            incidents: [],
            circuit_breaker: { state: 'CLOSED' },
            rate_gate: { status: 'HEALTHY' },
            ws_capacity: { total_subscribed: 120 },
            tbt: { active_total: 10, slots: [] },
            host_vitals: { memory: {}, storage: {} },
            telemetry: {},
          }),
        })
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders Universe Depth Radar tab and displays sortable L2 metrics', async () => {
    const handleOpenOrder = vi.fn()
    render(<OpsDeckView onOpenOrderTicket={handleOpenOrder} />)

    // Find and click the Universe Depth Radar tab
    const radarTab = screen.getByTestId('tab-depth-radar')
    expect(radarTab).toBeInTheDocument()
    fireEvent.click(radarTab)

    // Verify radar header
    await waitFor(() => {
      expect(screen.getByText(/Institutional L2 Market Depth Radar/i)).toBeInTheDocument()
    })

    // Verify rows rendered
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getByText('+61%')).toBeInTheDocument()
    expect(screen.getByText('-52%')).toBeInTheDocument()

    // Verify search filtering
    const searchInput = screen.getByPlaceholderText(/Search symbol/i)
    fireEvent.change(searchInput, { target: { value: 'INFY' } })

    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.queryByText('RELIANCE')).not.toBeInTheDocument()

    // Clear search
    fireEvent.change(searchInput, { target: { value: '' } })
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()

    // Click Stage order on RELIANCE
    const stageButtons = screen.getAllByRole('button', { name: /^stage$/i })
    expect(stageButtons.length).toBeGreaterThan(0)
    fireEvent.click(stageButtons[0])

    expect(handleOpenOrder).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: expect.any(String),
      })
    )
  })

  it('toggles Active Inspector dock and expands table to full-width when collapsed', async () => {
    localStorage.clear()
    const handleOpenOrder = vi.fn()
    render(<OpsDeckView onOpenOrderTicket={handleOpenOrder} />)

    // Switch to Universe Depth Radar tab
    fireEvent.click(screen.getByTestId('tab-depth-radar'))

    await waitFor(() => {
      expect(screen.getByText(/Institutional L2 Market Depth Radar/i)).toBeInTheDocument()
    })

    // By default, Active Inspector is collapsed to maximize tabular viewing space
    expect(screen.queryByText('ACTIVE INSPECTOR')).not.toBeInTheDocument()
    expect(screen.getByText(/Inspector: Hidden/i)).toBeInTheDocument()

    // Clicking DOM → button opens the Active Inspector
    const domBtn = screen.getByTestId('inspect-dom-RELIANCE')
    expect(domBtn).toBeInTheDocument()
    fireEvent.click(domBtn)

    // Now Active Inspector is visible
    expect(screen.getByText('ACTIVE INSPECTOR')).toBeInTheDocument()
    expect(screen.getByText(/Inspector: Docked/i)).toBeInTheDocument()

    // Clicking close (✕) button collapses the inspector back
    const closeBtn = screen.getByTestId('close-radar-inspector')
    expect(closeBtn).toBeInTheDocument()
    fireEvent.click(closeBtn)

    expect(screen.queryByText('ACTIVE INSPECTOR')).not.toBeInTheDocument()
    expect(screen.getByText(/Inspector: Hidden/i)).toBeInTheDocument()

    // Clicking toolbar toggle button re-opens the inspector
    const toggleBtn = screen.getByTestId('toggle-radar-inspector')
    fireEvent.click(toggleBtn)

    expect(screen.getByText('ACTIVE INSPECTOR')).toBeInTheDocument()
    expect(screen.getByText(/Inspector: Docked/i)).toBeInTheDocument()
  })

  it('isolates Sentinel hover card to column with screen-adaptive solid opaque portal', async () => {
    render(<OpsDeckView />)

    // Switch to Universe Depth Radar tab
    fireEvent.click(screen.getByTestId('tab-depth-radar'))

    await waitFor(() => {
      expect(screen.getByText(/Institutional L2 Market Depth Radar/i)).toBeInTheDocument()
    })

    // Find Sentinel cell
    const sentinelCells = document.querySelectorAll('td.group\\/sentinel')
    expect(sentinelCells.length).toBeGreaterThan(0)

    // Initially portal card is not rendered
    expect(screen.queryByTestId('sentinel-portal-card')).not.toBeInTheDocument()

    // Hover over the first Sentinel column cell
    fireEvent.mouseEnter(sentinelCells[0])

    // Verify portal card appears with 100% solid opaque styling and fixed positioning
    const portalCard = screen.getByTestId('sentinel-portal-card')
    expect(portalCard).toBeInTheDocument()
    expect(portalCard.style.position).toBe('fixed')
    expect(portalCard.style.backgroundColor).toBe('rgb(13, 21, 39)')
    expect(screen.getByText(/Trading Decision Blueprint:/i)).toBeInTheDocument()

    // Mouse leave unmounts the portal card
    fireEvent.mouseLeave(sentinelCells[0])
    expect(screen.queryByTestId('sentinel-portal-card')).not.toBeInTheDocument()
  })
})
