import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { AlertCompactRow } from '../renderer/src/components/Views/alerts/AlertCompactRow'

// Mock LiveSpotsContext to return predictable spot/contract quotes
vi.mock('../renderer/src/components/Views/alerts/LiveSpotsContext', () => ({
  useLiveSpot: vi.fn(() => null),
  LiveSpotsProvider: ({ children }) => children,
}))

describe('AlertCompactRow Horizon, Liquidity, and Strike Roll', () => {
  it('renders intraday session cutoff indicator in the horizon badge', () => {
    const alert = {
      alert_id: 'test-horizon-001',
      symbol: 'NIFTY',
      exchange: 'NSE',
      direction: 'BULLISH',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      ltp: 120.0,
      trigger_level: 120.0,
      target_level: 180.0,
      stop_loss: 90.0,
      time_horizon: 'INTRADAY',
      strike: 25000,
      option_type: 'CE',
      contract_symbol: 'NIFTY2692425000CE',
    }

    render(<AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />)
    expect(screen.getByText(/INTRADAY \(15:15\)/i)).toBeInTheDocument()
  })

  it('renders MCX 23:15 cutoff for commodity intraday alerts', () => {
    const alert = {
      alert_id: 'test-horizon-mcx-002',
      symbol: 'CRUDEOIL',
      exchange: 'MCX',
      direction: 'BULLISH',
      alert_type: 'COMMODITY_MOMENTUM',
      stage: 'IGNITED',
      ltp: 6500.0,
      trigger_level: 6500.0,
      target_level: 6600.0,
      stop_loss: 6450.0,
      time_horizon: 'INTRADAY',
    }

    render(<AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />)
    expect(screen.getByText(/INTRADAY \(23:15\)/i)).toBeInTheDocument()
  })

  it('renders optimal liquidity badge when spread is tight', () => {
    const alert = {
      alert_id: 'test-liq-tight-003',
      symbol: 'NIFTY',
      exchange: 'NFO',
      direction: 'BULLISH',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      ltp: 150.0,
      trigger_level: 150.0,
      target_level: 220.0,
      stop_loss: 110.0,
      strike: 25000,
      option_type: 'CE',
      contract_symbol: 'NIFTY2692425000CE',
      liquidity_status: 'OPTIMAL',
      bid_ask_spread_pct: 0.4,
    }

    render(<AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />)
    expect(screen.getByText(/🟢 LIQUID 0.4%/i)).toBeInTheDocument()
  })

  it('renders wide spread caution badge when spread is high', () => {
    const alert = {
      alert_id: 'test-liq-wide-004',
      symbol: 'NIFTY',
      exchange: 'NFO',
      direction: 'BULLISH',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      ltp: 150.0,
      trigger_level: 150.0,
      target_level: 220.0,
      stop_loss: 110.0,
      strike: 25000,
      option_type: 'CE',
      contract_symbol: 'NIFTY2692425000CE',
      liquidity_status: 'WIDE_SPREAD_CAUTION',
      bid_ask_spread_pct: 3.2,
    }

    render(<AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />)
    expect(screen.getByText(/⚠️ WIDE 3.2%/i)).toBeInTheDocument()
  })

  it('renders 1-click Roll Strike button when T2 is hit, and invokes onTrade with _isStrikeRoll', () => {
    const onTradeMock = vi.fn()
    const alert = {
      alert_id: 'test-roll-btn-005',
      symbol: 'NIFTY',
      exchange: 'NFO',
      direction: 'BULLISH',
      alert_type: 'OPTIONS_MOMENTUM',
      stage: 'T2_ACHIEVED',
      ltp: 210.0,
      trigger_level: 120.0,
      target_level: 220.0,
      stop_loss: 90.0,
      strike: 25000,
      option_type: 'CE',
      contract_symbol: 'NIFTY2692425000CE',
      underlying_spot: 25380,
      target_status: 'T2_ACHIEVED',
      strike_roll_recommendation: {
        action: 'ROLL_UP',
        current_strike: 25000,
        recommended_strike: 25400,
        recommended_contract: 'NIFTY2692425400CE',
        reason: 'Roll up to liquid ATM 25400 CE to restore gamma leverage and avoid wide bid-ask slippage.',
      },
    }

    render(
      <AlertCompactRow
        alert={alert}
        onTrade={onTradeMock}
        onExpand={() => {}}
        isExpanded={false}
      />
    )

    const rollBtn = screen.getByRole('button', { name: /🔄 Roll Strike/i })
    expect(rollBtn).toBeInTheDocument()

    fireEvent.click(rollBtn)
    expect(onTradeMock).toHaveBeenCalledTimes(1)
    expect(onTradeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        _isStrikeRoll: true,
        _rollRecommendation: expect.objectContaining({
          recommended_strike: 25400,
        }),
      })
    )
  })
})
