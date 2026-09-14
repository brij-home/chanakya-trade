import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import OptionsDeskView from '../renderer/src/components/Views/OptionsDeskView'

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

describe('OptionsDeskView - Blast Badge Interaction & Theme-Adaptive Popover', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url) => {
      const urlStr = String(url)
      if (urlStr.includes('/skills/gex_snapshot')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              symbol: 'NIFTY',
              spot_price: 23163.25,
              spot_change: '+142.50',
              spot_change_pct: '+0.62%',
              data_state: 'LIVE',
              is_realtime: true,
              call_wall: 23400,
              put_wall: 22800,
              max_pain: 23400,
              pcr: 1.15,
              options_chain: [
                {
                  strike: 23150,
                  is_atm: true,
                  calls_oi: '42.7k',
                  calls_oi_chg: '+28.4k',
                  calls_gex: '+135604.0Cr',
                  calls_iv: '15.2%',
                  calls_bid: 210.5,
                  calls_ask: 212.0,
                  calls_blast: true,
                  calls_blast_reason: 'Heavy Call Buy Aggression (4.0x Bids) with 128.2x Vol/OI turnover',
                  puts_oi: '32.7k',
                  puts_oi_chg: '+22.5k',
                  puts_gex: '-68693.8Cr',
                  puts_iv: '16.1%',
                  puts_bid: 98.4,
                  puts_ask: 99.2,
                  puts_blast: false,
                },
              ],
              blast_radar: [
                {
                  strike: 23150,
                  option_type: 'CE',
                  contract: 'NIFTY 23150 CE',
                  score: 92,
                  action_title: 'BUY NIFTY 23150 CE',
                  blast_reason: 'Heavy Call Buy Aggression (4.0x Bids) with 128.2x Vol/OI turnover',
                  bid: 210.5,
                  ask: 212.0,
                  entry_range: '₹198.98 – ₹215.73',
                  stop_loss: '157.09',
                  stop_loss_pct: '-25.0%',
                  target_1: '303.70',
                  target_1_pct: '+45.0%',
                  target_2: '377.00',
                  target_2_pct: '+80.0%',
                  when_to_buy: 'Enter on Ask/Retest (₹198.98 – ₹215.73) while Spot holds > ₹23,082.2',
                  when_to_wait: 'DO NOT CHASE if premium > ₹240.9. Wait for pullback to ₹198.98',
                  profit_rule: 'Book 50% profit at Target 1 (₹303.70), trail Stop Loss to Cost for Target 2 (₹377.00)',
                },
              ],
            }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: {}, status: 'ok' }),
      })
    })
  })

  it('does NOT auto-popup Blast Action Popover on mouse over / hover', async () => {
    render(<OptionsDeskView selectedSymbol="NIFTY" />)

    // Wait for the strike button to render
    const bidBtn = await screen.findByTitle(/BLAST ALERT/i)
    expect(bidBtn).toBeTruthy()

    // Hover over the bid button
    fireEvent.mouseEnter(bidBtn)

    // Verify popover did NOT automatically open
    expect(screen.queryByText(/BUY NIFTY 23150 CE/i)).toBeNull()
    expect(screen.queryByText(/Stage BUY Order/i)).toBeNull()
  })

  it('opens theme-adaptive Blast Action Popover when clicking BLAST badge', async () => {
    const handleOpenOrder = vi.fn()
    render(<OptionsDeskView selectedSymbol="NIFTY" onOpenOrderTicket={handleOpenOrder} />)

    // Find the BLAST badge uniquely by title
    const blastBadge = await screen.findByTitle('Click to view Actionable Profit Roadmap')
    expect(blastBadge).toBeTruthy()

    // Click the BLAST badge
    fireEvent.click(blastBadge)

    // Popover should now be open - verify unique popover elements
    const closeBtn = await screen.findByTitle('Close Popover')
    expect(closeBtn).toBeTruthy()

    const stageBtn = screen.getByRole('button', { name: /Stage BUY Order/i })
    expect(stageBtn).toBeTruthy()

    // Verify the popover container uses bg-panel (not hardcoded dark background)
    const popoverContainer = stageBtn.closest('.bg-panel')
    expect(popoverContainer).toBeTruthy()
    expect(popoverContainer.style.background).not.toBe('rgba(15, 23, 42, 0.96)')

    // Verify Actionable Blueprint and Rules are rendered
    expect(screen.getByText(/Target 1 \(1\.5R Scalp\)/i)).toBeTruthy()
    expect(screen.getByText(/Target 2 \(2\.5R Runner\)/i)).toBeTruthy()
    expect(screen.getAllByText(/🟢 BUY:/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/🟡 WAIT:/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/💰 PROFIT:/i).length).toBeGreaterThanOrEqual(1)

    // Click Stage BUY Order button
    fireEvent.click(stageBtn)
    expect(handleOpenOrder).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'NIFTY 23150 CE',
      })
    )

    // After clicking stage order, popover closes
    await waitFor(() => {
      expect(screen.queryByTitle('Close Popover')).toBeNull()
    })
  })

  it('closes Blast Action Popover when clicking close button ✕', async () => {
    render(<OptionsDeskView selectedSymbol="NIFTY" />)

    const blastBadge = await screen.findByTitle('Click to view Actionable Profit Roadmap')
    fireEvent.click(blastBadge)

    const closeBtn = await screen.findByTitle('Close Popover')
    expect(closeBtn).toBeTruthy()

    fireEvent.click(closeBtn)

    await waitFor(() => {
      expect(screen.queryByTitle('Close Popover')).toBeNull()
    })
  })
})
