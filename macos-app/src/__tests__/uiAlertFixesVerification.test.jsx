import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import {
  formatAlertTriggerTime,
  computeExecutionLevels,
  resolveAlertLifecycle
} from '../renderer/src/components/Views/alerts/alertHelpers'
import { AlertCompactRow } from '../renderer/src/components/Views/alerts/AlertCompactRow'
import { TradeExecutionMatrix } from '../renderer/src/components/Views/alerts/TradeExecutionMatrix'
import { LiveSpotsProvider } from '../renderer/src/components/Views/alerts/LiveSpotsContext'

describe('UI Alert Fixes - Holistic Verification', () => {
  describe('1. Timestamp Formatting (formatAlertTriggerTime)', () => {
    it('accurately parses UTC ISO string into Asia/Kolkata (IST)', () => {
      const res = formatAlertTriggerTime('2026-11-03T06:43:16.608Z')
      expect(res).not.toBeNull()
      expect(res.display).toContain('12:13:16 IST')
      expect(res.timeOnly).toBe('12:13:16')
    })

    it('correctly handles naive strings and preserves IST hours', () => {
      const res = formatAlertTriggerTime('2026-11-03 11:51:13 IST')
      expect(res).not.toBeNull()
      expect(res.display).toContain('11:51:13 IST')
      expect(res.timeOnly).toBe('11:51:13')
    })
  })

  describe('2. Level Derivation (computeExecutionLevels)', () => {
    it('extracts net credit, max loss, and decay targets for Defined-Risk Iron Condor', () => {
      const condorAlert = {
        alert_id: 'aa-defined-risk-neutral-banknifty-condor-20261103',
        alert_type: 'DEFINED_RISK_NEUTRAL',
        symbol: 'BANKNIFTY',
        headline: '🛡 DEFINED-RISK CONDOR: BANKNIFTY @ ₹55,452.7 | Corridor [₹55,300 – ₹55,700] (Credit ₹4,631)',
        summary: 'Hedged Iron Condor collects ₹4,631 net credit.',
        underlying_spot: 55452.7,
        ltp: 55452.7,
        lot_size: 30,
        actionable_plan: {
          entry_price: 154.37,
          stop_loss: 145.63,
          target_1: 77.18,
          target_2: 30.87,
          target_3: 0
        }
      }

      const levels = computeExecutionLevels(condorAlert)
      expect(levels.entry).toBe(154.37)
      expect(levels.sl).toBe(145.63)
      expect(levels.t1).toBe(77.18)
      expect(levels.t2).toBe(30.87)
      expect(levels.t3).toBe(0)
      expect(levels.isNeutralSpread).toBe(true)
    })

    it('extracts strike and optType from headline for Micro Scalp and resolves levels', () => {
      const scalpAlert = {
        alert_id: 'aa-index-micro-scalp-nifty-ce-23600-20261103',
        alert_type: 'INDEX_MICRO_SCALP',
        symbol: 'NIFTY',
        headline: '⚡ NIFTY 23600 CE 1m Micro Breakout',
        summary: 'NIFTY 23600 CE micro breakout ignited at ₹185.0. Buy above ₹185.0. SL ₹165.0, T1 ₹225.0, T2 ₹255.0, Runner ₹295.0.',
        underlying_spot: 23580.5,
        ltp: 185.0,
        trigger_level: 185.0,
        stop_loss: 165.0,
        target_level: 225.0,
        segment: 'FNO_INDEX',
        actionable_plan: {
          trigger_level: 185.0,
          invalidation_stop: 165.0,
          target_1: 225.0,
          target_2: 255.0,
          runner_target: 295.0
        }
      }

      const life = resolveAlertLifecycle(scalpAlert)
      expect(life.strikeNum).toBe(23600)
      expect(life.optType).toBe('CE')
      expect(life.entryNum).toBe(185)
      expect(life.slNum).toBe(165)
      expect(life.t1Num).toBe(225)
    })

    it('preserves underlying spot levels for FNO_INDEX alerts without option contracts', () => {
      const precursorAlert = {
        alert_id: 'aa-precursor-radar-midcpnifty-20261103',
        alert_type: 'PRECURSOR_RADAR',
        symbol: 'MIDCPNIFTY',
        headline: '⚡ PRECURSOR RADAR (INDEX): MIDCPNIFTY Coiling at ₹13,482.0 (80/100)',
        summary: 'MIDCPNIFTY pre-inflection coiling: Healthy volume contraction. Entry: ₹13,482.0, SL: ₹13,380.0, T1: ₹13,680.0.',
        underlying_spot: 13482.0,
        ltp: 13482.0,
        trigger_level: 13482.0,
        stop_loss: 13380.0,
        target_level: 13680.0,
        target_1: 13680.0,
        target_2: 13850.0,
        segment: 'FNO_INDEX',
        actionable_plan: {
          trigger_level: 13482.0,
          invalidation_stop: 13380.0,
          target_1: 13680.0,
          target_2: 13850.0
        }
      }

      const life = resolveAlertLifecycle(precursorAlert)
      expect(life.entryNum).toBe(13482)
      expect(life.slNum).toBe(13380)
      expect(life.t1Num).toBe(13680)
    })
  })

  describe('3. Text-Fallback Extraction on All 6 Production Alerts', () => {
    it('successfully extracts levels and metadata from raw notification objects', () => {
      const alerts = [
        {
          symbol: 'BANKNIFTY',
          headline: '🛡 DEFINED-RISK CONDOR: BANKNIFTY @ ₹55,452.7 | Corridor [₹55,300 – ₹55,700] (Credit ₹4,631)',
          summary: 'Range-bound consolidation regime (VIX 16.1). Hedged Iron Condor collects ₹4,631 net credit. Safe corridor ₹55,300 to ₹55,700. Capped max loss ₹4,369.'
        },
        {
          symbol: 'NIFTY',
          headline: '⚡ NIFTY 23600 CE 1m Micro Breakout',
          summary: 'NIFTY 23600 CE micro breakout ignited at ₹185.0. Buy above ₹185.0 (1-min close basis). SL ₹165.0, T1 (+2R) ₹225.0, T2 (+3.5R) ₹255.0, Runner ₹295.0. High-Delta torque.'
        },
        {
          symbol: 'MIDCPNIFTY',
          headline: '⚡ PRECURSOR RADAR [INDEX]: MIDCPNIFTY Coiling at ₹13,482.0 (80/100)',
          summary: '[INDEX] Pre-ignition coiling: Healthy Volume Contraction (39% of 20D SMA). Entry: ₹13,450 – ₹13,485. SL ₹13,380.0, T1 ₹13,680.0, T2 ₹13,800.0.'
        },
        {
          symbol: 'BANKEX',
          headline: '⚡ PRECURSOR RADAR [INDEX]: BANKEX Coiling at ₹62,157.9 (93/100)',
          summary: '[INDEX] Pre-ignition coiling: Squeeze expansion. Entry: ₹62,100 – ₹62,250. SL ₹61,800.0, T1 ₹62,600.0.'
        },
        {
          symbol: 'FINNIFTY',
          headline: '⚡ HEAVYWEIGHT CONTAGION: NSE:FINNIFTY28NOV25100CE @ ₹394.4 (92% Weight BULLISH)',
          summary: 'Heavyweight contagion bullish impulse: NSE:FINNIFTY28NOV25100CE @ ₹394.4. SL ₹340.0, T1 ₹480.0, T2 ₹530.0.'
        },
        {
          symbol: 'SENSEX',
          headline: '⚡ PUT GAMMA BLAST EARLY WARNING: SENSEX 75300 PE',
          summary: 'Put gamma blast early warning: SENSEX 75300 PE ignited at ₹450.0. SL ₹380.0, T1 ₹600.0, T2 ₹690.0.'
        }
      ]

      // 1. BANKNIFTY
      const bn = resolveAlertLifecycle(alerts[0])
      expect(bn.condorCorridor).toBe('₹55,300 – ₹55,700')
      expect(bn.isNeutralSpread).toBe(true)
      expect(bn.spotNum).toBe(55452.7)
      expect(bn.entryNum).toBe(154.37)
      expect(bn.slNum).toBe(145.63)

      // 2. NIFTY
      const nf = resolveAlertLifecycle(alerts[1])
      expect(nf.strikeNum).toBe(23600)
      expect(nf.optType).toBe('CE')
      expect(nf.entryNum).toBe(185)
      expect(nf.slNum).toBe(165)
      expect(nf.t1Num).toBe(225)
      expect(nf.t2Num).toBe(255)
      expect(nf.t3Num).toBe(295)

      // 3. MIDCPNIFTY
      const mid = resolveAlertLifecycle(alerts[2])
      expect(mid.currentPrice).toBe(13482)
      expect(mid.entryNum).toBe(13482)
      expect(mid.slNum).toBe(13380)
      expect(mid.t1Num).toBe(13680)
      expect(mid.t2Num).toBe(13800)

      // 4. BANKEX
      const bx = resolveAlertLifecycle(alerts[3])
      expect(bx.currentPrice).toBe(62157.9)
      expect(bx.entryNum).toBe(62157.9)
      expect(bx.slNum).toBe(61800)
      expect(bx.t1Num).toBe(62600)

      // 5. FINNIFTY
      const fn = resolveAlertLifecycle(alerts[4])
      expect(fn.strikeNum).toBe(25100)
      expect(fn.optType).toBe('CE')
      expect(fn.isDerivative).toBe(true)
      expect(fn.entryNum).toBe(394.4)
      expect(fn.slNum).toBe(340)
      expect(fn.t1Num).toBe(480)
      expect(fn.t2Num).toBe(530)

      // 6. SENSEX
      const sx = resolveAlertLifecycle(alerts[5])
      expect(sx.strikeNum).toBe(75300)
      expect(sx.optType).toBe('PE')
      expect(sx.isDerivative).toBe(true)
      expect(sx.entryNum).toBe(450)
      expect(sx.slNum).toBe(380)
      expect(sx.t1Num).toBe(600)
      expect(sx.t2Num).toBe(690)
    })
  })

  describe('4. Component Rendering (AlertCompactRow)', () => {
    it('renders corridor badge and credit levels for Defined-Risk Condor', () => {
      const condorAlert = {
        alert_id: 'aa-defined-risk-neutral-banknifty-condor-20261103',
        alert_type: 'DEFINED_RISK_NEUTRAL',
        symbol: 'BANKNIFTY',
        headline: '🛡 DEFINED-RISK CONDOR: BANKNIFTY @ ₹55,452.7 | Corridor [₹55,300 – ₹55,700] (Credit ₹4,631)',
        summary: 'Hedged Iron Condor collects ₹4,631 net credit.',
        underlying_spot: 55452.7,
        ltp: 55452.7,
        lot_size: 30,
        actionable_plan: {
          entry_price: 154.37,
          stop_loss: 145.63,
          target_1: 77.18,
          target_2: 30.87,
          target_3: 0
        },
        timestamp: '2026-11-03T06:43:16.608Z'
      }

      render(
        <LiveSpotsProvider value={{}}>
          <AlertCompactRow alert={condorAlert} onExpand={() => {}} isExpanded={false} />
        </LiveSpotsProvider>
      )

      // Row 1 Corridor badge check
      expect(screen.getByText(/Corridor \[₹55,300 – ₹55,700\]/i)).toBeInTheDocument()

      // Row 1 Timestamp check
      expect(screen.getByText(/12:13:16 IST/i)).toBeInTheDocument()

      // Row 2 Credit & MaxLoss levels check
      expect(screen.getAllByText(/Credit/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText(/154\.4/i)).toBeInTheDocument()
      expect(screen.getAllByText(/MaxLoss/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText(/145\.6/i)).toBeInTheDocument()
    })

    it('renders strike badge and premium levels for Micro Scalp', () => {
      const scalpAlert = {
        alert_id: 'aa-index-micro-scalp-nifty-ce-23600-20261103',
        alert_type: 'INDEX_MICRO_SCALP',
        symbol: 'NIFTY',
        headline: '⚡ NIFTY 23600 CE 1m Micro Breakout',
        summary: 'NIFTY 23600 CE micro breakout ignited at ₹185.0. Buy above ₹185.0. SL ₹165.0, T1 (+2R) ₹225.0.',
        underlying_spot: 23580.5,
        ltp: 185.0,
        trigger_level: 185.0,
        stop_loss: 165.0,
        target_level: 225.0,
        segment: 'FNO_INDEX',
        actionable_plan: {
          trigger_level: 185.0,
          invalidation_stop: 165.0,
          target_1: 225.0,
          target_2: 255.0,
          runner_target: 295.0
        },
        timestamp: '2026-11-03T06:43:08.000Z'
      }

      render(
        <LiveSpotsProvider value={{}}>
          <AlertCompactRow alert={scalpAlert} onExpand={() => {}} isExpanded={false} />
        </LiveSpotsProvider>
      )

      // Row 1 Strike & OptType badges
      expect(screen.getByText(/₹23,600/i)).toBeInTheDocument()
      expect(screen.getByText('CE')).toBeInTheDocument()

      // Row 1 Timestamp
      expect(screen.getByText(/12:13:08 IST/i)).toBeInTheDocument()

      // Row 2 Prem & SL
      expect(screen.getByText(/Prem/i)).toBeInTheDocument()
      expect(screen.getAllByText(/185/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/SL/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/165/i).length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('5. Expanded TradeExecutionMatrix & Actionable Execution Protocol', () => {
    it('synthesizes complete 4-leg grid and renders execution protocol for Iron Condor', () => {
      const condorAlert = {
        alert_id: 'aa-defined-risk-neutral-banknifty-condor-20261103',
        alert_type: 'DEFINED_RISK_NEUTRAL',
        symbol: 'BANKNIFTY',
        headline: '🛡 DEFINED-RISK CONDOR: BANKNIFTY @ ₹55,452.7 | Corridor [₹55,300 – ₹55,700] (Credit ₹4,631)',
        summary: 'Range-bound consolidation regime (VIX 16.1). Hedged Iron Condor collects ₹4,631 net credit. Safe corridor ₹55,300 to ₹55,700. Capped max loss ₹4,369.',
        underlying_spot: 55452.7,
        ltp: 55452.7,
        lot_size: 30,
        condor_corridor: '₹55,300 – ₹55,700',
        profit_corridor: '₹55,300 – ₹55,700',
        actionable_plan: {
          entry_price: 154.37,
          stop_loss: 145.63,
          target_1: 77.18,
          target_2: 30.87,
          target_3: 0,
        },
      }

      const life = resolveAlertLifecycle(condorAlert)

      render(
        <LiveSpotsProvider value={{}}>
          <TradeExecutionMatrix
            alert={condorAlert}
            levels={life.levels}
            lifecycle={life}
            isDerivative={life.isDerivative}
          />
        </LiveSpotsProvider>
      )

      // 1. 4-Leg Grid verification
      expect(screen.getAllByText(/BUY \+1/).length).toBe(2)
      expect(screen.getAllByText(/SELL \-1/).length).toBe(2)
      expect(screen.getAllByText(/55000 PE/).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/55300 PE/).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/55700 CE/).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/56000 CE/).length).toBeGreaterThanOrEqual(1)

      // 2. Safe Corridor and Breakevens Strip
      expect(screen.getAllByText(/Safe Corridor/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/₹55,300 – ₹55,700/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/Breakevens/i).length).toBeGreaterThanOrEqual(1)

      // 3. Actionable Execution Protocol 4 Steps
      expect(screen.getByText(/Actionable Execution & Profit Capture Protocol/i)).toBeInTheDocument()
      expect(screen.getByText(/1\. Entry Execution/i)).toBeInTheDocument()
      expect(screen.getByText(/2\. T1 Milestone/i)).toBeInTheDocument()
      expect(screen.getByText(/3\. Target 2 \/ Runner/i)).toBeInTheDocument()
      expect(screen.getByText(/4\. Strict Invalidation/i)).toBeInTheDocument()

      // 4. Institutional Trader Action Directive
      expect(screen.getByText(/Institutional Trader Action Directive/i)).toBeInTheDocument()
      expect(screen.getByText(/RECOMMENDATION:/i)).toBeInTheDocument()
      expect(screen.getAllByText(/Execute 4-leg condor/i).length).toBeGreaterThanOrEqual(1)
    })

    it('renders informative calibrating card and execution protocol when levels are pending for micro breakout', () => {
      const pendingAlert = {
        alert_id: 'aa-index-micro-scalp-nifty-ce-23600-20261103',
        alert_type: 'INDEX_MICRO_SCALP',
        symbol: 'NIFTY',
        headline: '⚡ NIFTY 23600 CE 1m Micro Breakout',
        summary: 'NIFTY 23600 CE 1m Micro Breakout',
        segment: 'FNO_INDEX',
        strike: 23600,
        option_type: 'CE',
        lot_size: 65,
      }

      render(
        <LiveSpotsProvider value={{}}>
          <TradeExecutionMatrix
            alert={pendingAlert}
            levels={{}}
            isDerivative={true}
          />
        </LiveSpotsProvider>
      )

      // 1. Calibrating card
      expect(screen.getByText(/CALIBRATING/i)).toBeInTheDocument()
      expect(screen.getByText(/AWAITING L2 ORDER BOOK DEPTH/i)).toBeInTheDocument()
      expect(screen.getByText(/BUY NIFTY 23600 CE/i)).toBeInTheDocument()
      expect(screen.getByText(/Lot Size: 65 units/i)).toBeInTheDocument()

      // 2. Actionable Execution Protocol & Trader Directive
      expect(screen.getByText(/Actionable Execution & Profit Capture Protocol/i)).toBeInTheDocument()
      expect(screen.getByText(/Institutional Trader Action Directive/i)).toBeInTheDocument()
      expect(screen.getByText(/High-torque breakout detected on NIFTY 23600 CE/i)).toBeInTheDocument()
    })
  })
})
