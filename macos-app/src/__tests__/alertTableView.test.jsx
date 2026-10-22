import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { AlertTableView } from '../renderer/src/components/Views/alerts/AlertTableView'

vi.mock('../renderer/src/components/Views/alerts/LiveSpotsContext', () => ({
  useLiveSpot: vi.fn(() => null),
  LiveSpotsProvider: ({ children }) => children,
}))

describe('AlertTableView Component', () => {
  const mockAlerts = [
    {
      alert_id: 'test-tbl-001',
      symbol: 'NIFTY',
      exchange: 'NFO',
      direction: 'BULLISH',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      strike: 25000,
      option_type: 'CE',
      expiry_date: '2026-09-17',
      expiry_type: 'WEEKLY',
      contract_symbol: 'NIFTY2691725000CE',
      option_premium: 185.0,
      ltp: 185.0,
      trigger_level: 185.0,
      target_level: 280.0,
      stop_loss: 130.0,
      confidence: 92,
      metrics: {
        conviction_tier: 'APEX_CONFLUENCE',
        rr_ratio: 3.2,
      },
      actionable_plan: {
        trade_plan: {
          entry_price: 185.0,
          stop_loss: 130.0,
          target_1: 280.0,
          rr_ratio: 3.2,
        },
      },
    },
    {
      alert_id: 'test-tbl-002',
      symbol: 'BANKNIFTY',
      exchange: 'NFO',
      direction: 'BEARISH',
      alert_type: 'OPTIONS_MOMENTUM',
      stage: 'PRIMED',
      strike: 54000,
      option_type: 'PE',
      expiry_date: '2026-09-24',
      expiry_type: 'MONTHLY',
      contract_symbol: 'BANKNIFTY2692454000PE',
      option_premium: 320.0,
      ltp: 320.0,
      trigger_level: 320.0,
      target_level: 480.0,
      stop_loss: 240.0,
      confidence: 84,
      metrics: {
        conviction_tier: 'HIGH_CONVICTION',
        rr_ratio: 2.0,
      },
      strike_roll_recommendation: {
        current_strike: 54000,
        recommended_strike: 53500,
        current_delta: 0.74,
      },
    },
  ]

  it('renders table headers and institutional columns properly', () => {
    render(<AlertTableView alerts={mockAlerts} onTrade={() => {}} />)

    expect(screen.getByText(/Stage/i)).toBeInTheDocument()
    expect(screen.getByText(/Symbol & Contract/i)).toBeInTheDocument()
    expect(screen.getByText(/Direction/i)).toBeInTheDocument()
    expect(screen.getByText(/LTP & Return/i)).toBeInTheDocument()
    expect(screen.getByText(/Blueprint/i)).toBeInTheDocument()
    expect(screen.getByText(/Conviction & Regimes/i)).toBeInTheDocument()
    expect(screen.getByText(/Execution CTAs/i)).toBeInTheDocument()
  })

  it('renders contract symbols, strikes, and weekly/monthly expiry badges', () => {
    render(<AlertTableView alerts={mockAlerts} onTrade={() => {}} />)

    // Symbol & strike
    expect(screen.getByText('NIFTY')).toBeInTheDocument()
    expect(screen.getByText(/25,000/)).toBeInTheDocument()
    expect(screen.getByText('CE')).toBeInTheDocument()
    expect(screen.getByText(/⚡W/)).toBeInTheDocument()

    expect(screen.getByText('BANKNIFTY')).toBeInTheDocument()
    expect(screen.getByText(/54,000/)).toBeInTheDocument()
    expect(screen.getByText('PE')).toBeInTheDocument()
    expect(screen.getByText(/📅M/)).toBeInTheDocument()
  })

  it('renders direction pills with proper color and text', () => {
    render(<AlertTableView alerts={mockAlerts} onTrade={() => {}} />)

    expect(screen.getByText(/▲ LONG/i)).toBeInTheDocument()
    expect(screen.getByText(/▼ SHORT/i)).toBeInTheDocument()
  })

  it('triggers onTrade when 1-Click Trade button is clicked', () => {
    const onTradeMock = vi.fn()
    render(<AlertTableView alerts={mockAlerts} onTrade={onTradeMock} />)

    const tradeButtons = screen.getAllByText(/⚡ Trade/i)
    expect(tradeButtons.length).toBeGreaterThanOrEqual(2)

    fireEvent.click(tradeButtons[0])
    expect(onTradeMock).toHaveBeenCalledWith(mockAlerts[0])
  })

  it('renders strike roll CTA and triggers rollover when clicked', () => {
    const onTradeMock = vi.fn()
    render(<AlertTableView alerts={mockAlerts} onTrade={onTradeMock} />)

    const rollButton = screen.getByText(/Roll Strike/i)
    expect(rollButton).toBeInTheDocument()

    fireEvent.click(rollButton)
    expect(onTradeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'BANKNIFTY',
        _isStrikeRoll: true,
      })
    )
  })

  it('sorts alerts when column headers are clicked', () => {
    render(<AlertTableView alerts={mockAlerts} onTrade={() => {}} />)

    const symbolHeader = screen.getByText(/Symbol & Contract/i)
    fireEvent.click(symbolHeader)

    // After clicking, BANKNIFTY should be first alphabetically
    const rows = screen.getAllByRole('row')
    expect(rows.length).toBe(3) // 1 header + 2 data rows
    expect(rows[1]).toHaveTextContent('BANKNIFTY')
    expect(rows[2]).toHaveTextContent('NIFTY')
  })
})
