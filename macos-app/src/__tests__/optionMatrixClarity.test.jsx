import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { resolveAlertLifecycle } from '../renderer/src/components/Views/alerts/alertHelpers'
import { TradeExecutionMatrix } from '../renderer/src/components/Views/alerts/TradeExecutionMatrix'

describe('Option Matrix & Derivative Clarity (BankNifty PE Buy)', () => {
  const sampleBankNiftyAlert = {
    alert_id: 'aa-trend-pullback-banknifty-pe-54700-20261022',
    alert_type: 'TREND_DAY_PULLBACK',
    stage: 'IGNITED',
    symbol: 'BANKNIFTY',
    exchange: 'NSE',
    segment: 'FNO_INDEX',
    direction: 'BEARISH',
    headline: '🎯 [TREND PULLBACK] BANKNIFTY 54700 PE Buy: 20-EMA Resistance Reject (Spot ₹54,715.1)',
    summary: 'Enter BANKNIFTY 54700 PE @ ₹309.30. Stop loss: ₹253.60. Target 1: ₹494.90.',
    ltp: 309.3,
    trigger_level: 309.3,
    target_level: 494.98,
    stop_loss: 253.63,
    strike: 54700,
    option_type: 'PE',
    option_premium: 309.3,
    underlying_spot: 54715.1,
    contract_symbol: 'BANKNIFTY 54700 PE',
    actionable_plan: {
      action: 'BUY PE',
      instrument_type: 'OPTION',
      contract: 'BANKNIFTY 54700 PE',
      recommended_entry: '₹309.30',
      stop_loss: '₹253.6',
      target_1: '₹494.9',
      target_2: '₹588.6',
      target_3: '₹713.5',
      option_plan: {
        contract_symbol: 'BANKNIFTY 54700 PE',
        strike: 54700,
        option_type: 'PE',
        entry_premium: 309.3,
        sl_premium: 253.63,
        t1_premium: 494.98,
        t2_premium: 588.65,
        t3_premium: 713.55,
      },
      hedged_spread: {
        strategy_name: 'BEAR_PUT_SPREAD',
        sentiment: 'BEARISH',
        net_cashflow: 120.5,
        max_profit: 2842.5,
        risk_reward_ratio: 1.57,
        legs: [
          { side: 'BUY', strike: 54700, option_type: 'PE', premium: 309.3 },
          { side: 'SELL', strike: 54400, option_type: 'PE', premium: 188.8 },
        ],
      },
    },
  }

  it('correctly resolves lifecycle as a derivative with upward payoff and no spot contamination', () => {
    const lifecycle = resolveAlertLifecycle(sampleBankNiftyAlert, {
      liveSpot: { ltp: 54715.1 },
      liveContract: { ltp: 309.3 },
    })

    expect(lifecycle.isDerivative).toBe(true)
    expect(lifecycle.isOptionSell).toBe(false)
    expect(lifecycle.isUpwardPayoff).toBe(true)
    expect(lifecycle.currentPrice).toBe(309.3)
    expect(lifecycle.levels.entry).toBe(309.3)
    expect(lifecycle.levels.sl).toBe(253.63)
    expect(lifecycle.levels.t1).toBe(494.98)
    // Target hierarchy must be strictly ascending: T1 < T2 < T3
    expect(lifecycle.levels.t2).toBeGreaterThan(lifecycle.levels.t1)
    expect(lifecycle.levels.t3).toBeGreaterThan(lifecycle.levels.t2)
    // CMP 309.30 vs Entry 309.30 -> return should be 0.0% (not -17500%)
    expect(Number(lifecycle.liveReturn.pct)).toBeCloseTo(0.0, 1)
    // Stage must not be falsely marked as SL hit or Trail SL hit
    expect(lifecycle.isSLHit).toBe(false)
    expect(lifecycle.stagePill.label).not.toContain('SL HIT')
  })

  it('renders TradeExecutionMatrix with BUY badge, ascending targets, and non-empty vertical spread strikes', () => {
    const lifecycle = resolveAlertLifecycle(sampleBankNiftyAlert, {
      liveSpot: { ltp: 54715.1 },
      liveContract: { ltp: 309.3 },
    })

    render(
      <TradeExecutionMatrix
        alert={sampleBankNiftyAlert}
        levels={lifecycle.levels}
        isBull={lifecycle.isBull}
        isDerivative={lifecycle.isDerivative}
        currentPrice={lifecycle.currentPrice}
      />
    )

    // Entry Trigger badge must show BUY, not SELL
    expect(screen.getByText('BUY')).toBeDefined()
    // Spread section must display the strike numbers clearly
    expect(screen.getByText(/54700 PE/)).toBeDefined()
    expect(screen.getByText(/54400 PE/)).toBeDefined()
    expect(screen.getByText(/Net Debit:/)).toBeDefined()

    // Upgraded Institutional Spread Readability checks
    expect(screen.getByText('BUY +1')).toBeDefined()
    expect(screen.getByText('SELL -1')).toBeDefined()
    expect(screen.getByText('Long Leg')).toBeDefined()
    expect(screen.getByText('Hedge Leg')).toBeDefined()
    expect(screen.getByText(/BEAR PUT SPREAD/i)).toBeDefined()
    expect(screen.getByText(/THETA-NEUTRAL HEDGE/i)).toBeDefined()
    expect(screen.getByText(/Max Capital Risk/i)).toBeDefined()
    expect(screen.getAllByText(/Theta Decay Offset/i).length).toBeGreaterThanOrEqual(1)
  })
})


