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

  it('correctly extracts model-calculated SL and targets for SMT_SWEEP option alerts without falling back to 65% / 160% heuristics', () => {
    const sensexSmtAlert = {
      alert_id: 'aa-smt-sweep-sensex-pe-20261030',
      alert_type: 'SMT_SWEEP',
      stage: 'IGNITED',
      symbol: 'SENSEX',
      exchange: 'BFO',
      segment: 'FNO_INDEX',
      direction: 'BEARISH',
      headline: '🎯 [SMT REVERSAL] SMT INTER-INDEX DIVERGENCE: SENSEX 74200 PE @ ₹678.9',
      summary: 'Institutional liquidity sweep detected at Day High (₹74,304.9). Invalidation anchor pegged strictly above swing high at ₹74,324.9.',
      ltp: 593.8,
      entry_price: 678.85,
      trigger_level: 675.5,
      stop_loss: 556.7,
      target_level: 923.1,
      target_1: 923.1,
      target_2: 1167.4,
      strike: 74200.0,
      option_type: 'PE',
      contract_symbol: 'BSE:SENSEX26N0574200PE',
      underlying_spot: 74132.12,
      actionable_plan: {
        action: 'BUY_PUT_OR_BEAR_SPREAD',
        instrument_type: 'OPTION',
        entry_zone: '₹678.9 (Retest or Stop-Limit ₹675.5)',
        stop_loss: '₹556.7 (Spot invalidation ₹74,324.9)',
        target_1: '₹923.1',
        target_2: '₹1,167.4 (Spot Low ₹74,099.3)',
        target_3: '₹1,472.8 (Runner Extension)',
        no_chase_boundary: '₹709.3',
      },
    }

    const lifecycle = resolveAlertLifecycle(sensexSmtAlert, {
      liveSpot: { ltp: 74132.12 },
      liveContract: { ltp: 593.8 },
    })

    expect(lifecycle.isDerivative).toBe(true)
    expect(lifecycle.levels.entry).toBe(678.85)
    // Stop loss MUST be the detector model SL (556.7), NOT the 65% fallback (386.0)
    expect(lifecycle.levels.sl).toBe(556.7)
    expect(lifecycle.levels.sl).not.toBe(386.0)
    // Target 1 MUST be the detector model T1 (923.1), NOT the 160% fallback (950.1)
    expect(lifecycle.levels.t1).toBe(923.1)
    expect(lifecycle.levels.t1).not.toBe(950.1)
    // Target 2 MUST be the detector model T2 (1167.4), NOT the fallback (1163.8)
    expect(lifecycle.levels.t2).toBe(1167.4)
    expect(lifecycle.levels.t2).not.toBe(1163.8)
    // Target 3 MUST be the detector model T3 (1472.8), NOT the 250% fallback (1484.5)
    expect(lifecycle.levels.t3).toBe(1472.8)
    expect(lifecycle.levels.t3).not.toBe(1484.5)
    // No-chase limit must be option-denominated (709.3)
    expect(lifecycle.levels.no_chase_boundary).toBe(709.3)
  })
})


