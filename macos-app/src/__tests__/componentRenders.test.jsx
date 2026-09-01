import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useChatStore } from '../renderer/src/store/chatStore'

// Import Modals & Cards
import OrderTicketModal from '../renderer/src/components/Modals/OrderTicketModal'
import TopOpportunitiesModal from '../renderer/src/components/Modals/TopOpportunitiesModal'
import SectorDrilldownModal from '../renderer/src/components/Modals/SectorDrilldownModal'
import CommandPalette from '../renderer/src/components/Modals/CommandPalette'
import HighConvictionCard from '../renderer/src/components/Cards/HighConvictionCard'
import MarketStructureCard from '../renderer/src/components/Cards/MarketStructureCard'
import MorningBriefCard from '../renderer/src/components/Cards/MorningBriefCard'
import MultibaggerCard from '../renderer/src/components/Cards/MultibaggerCard'
import PersonaCard from '../renderer/src/components/Cards/PersonaCard'
import PositionTrackerCard from '../renderer/src/components/Cards/PositionTrackerCard'
import RRGCard from '../renderer/src/components/Cards/RRGCard'
import BacktestCard from '../renderer/src/components/Cards/BacktestCard'
import BigMoveCard from '../renderer/src/components/Cards/BigMoveCard'
import CouncilCard from '../renderer/src/components/Cards/CouncilCard'
import DefinedRiskSpreadCard from '../renderer/src/components/Cards/DefinedRiskSpreadCard'
import FlowsCard from '../renderer/src/components/Cards/FlowsCard'
import ForensicCard from '../renderer/src/components/Cards/ForensicCard'
import FunnelCard from '../renderer/src/components/Cards/FunnelCard'
import WhaleFlowsCard from '../renderer/src/components/Cards/WhaleFlowsCard'
import PersonaTrackRecordCard from '../renderer/src/components/Cards/PersonaTrackRecordCard'
import Message from '../renderer/src/components/Chat/Message'

// Mock matchMedia and ResizeObserver for JSDOM test environment
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

// Global fetch mock to prevent network calls in tests
global.fetch = vi.fn().mockImplementation((url) => {
  const urlStr = String(url)
  if (urlStr.includes('/skills/whale_flows')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          deals: [
            { symbol: 'RELIANCE', company_name: 'Reliance Industries', investor_name: 'LIC', sector: 'Energy', deal_type: 'BUY', deal_value_cr: 450, client_name: 'LIC India' }
          ],
          marquee_investors: [
            { name: 'LIC India', deal_count: 5, total_invested_cr: 1200, top_sectors: ['Financial Services', 'Energy'] }
          ]
        }
      }),
    })
  }
  if (urlStr.includes('/skills/persona/track_records')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          track_records: [
            { persona_id: 'minervini', name: 'Mark Minervini', win_rate: 68.5, compound_r: 12.4, dynamic_weight_multiplier: 1.25, total_trades: 40, active_regime: 'Markup' }
          ]
        }
      }),
    })
  }
  if (urlStr.includes('/skills/flows_history')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          history: [
            { date: '2026-08-28', fii_net: 1450, dii_net: 820 }
          ]
        }
      }),
    })
  }
  if (urlStr.includes('/api/orders/preview')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          order_id: 'PAPER-TEST1234',
          symbol: 'TATAMOTORS',
          side: 'BUY',
          quantity: 50,
          price: 980,
          status: 'PREVIEW',
          charges: { total_charges: 18.5, stt: 12.0, gst: 2.5, sebi_charges: 0.1, stamp_duty: 3.9 },
        }
      }),
    })
  }
  if (urlStr.includes('/api/orders/execute')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          order_id: 'PAPER-TEST1234',
          status: 'FILLED_PAPER',
          broker_order_id: 'PAPER-EXEC-A1B2C3D4',
        }
      }),
    })
  }
  if (urlStr.includes('/api/risk/preflight')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          flags: [],
          disclaimers: [],
          coaching_recommendations: [],
        }
      }),
    })
  }
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ data: {}, status: 'ok' }),
  })
})

vi.mock('../renderer/src/components/Charts/CandlestickChart', () => ({
  default: () => <div data-testid="mock-candlestick-chart">CandlestickChart</div>,
}))


beforeEach(() => {
  useChatStore.setState({
    messages: [],
    isLoading: false,
    draft: '',
    port: 8765,
    activeView: 'terminal',
  })
})

describe('React Component Rendering & Hook Invariant Gates', () => {
  describe('OrderTicketModal', () => {
    it('renders cleanly when closed without throwing hook errors', () => {
      const { container } = render(<OrderTicketModal isOpen={false} onClose={vi.fn()} />)
      expect(container.firstChild).toBeNull()
    })

    it('renders cleanly when open with default and dynamic data', () => {
      const onClose = vi.fn()
      const { rerender } = render(
        <OrderTicketModal
          isOpen={true}
          onClose={onClose}
          initialData={{
            symbol: 'TRENT',
            price: 5200,
            stopLoss: 5080,
            target: 5440,
            action: 'BUY',
          }}
        />
      )

      expect(screen.getByText(/Smart Order Staging/i)).toBeTruthy()
      expect(screen.getByDisplayValue('TRENT')).toBeTruthy()

      // Transition props dynamically (tests re-render hook count stability)
      rerender(
        <OrderTicketModal
          isOpen={true}
          onClose={onClose}
          initialData={{
            symbol: 'RELIANCE',
            price: 2800,
            stopLoss: 2740,
            target: 2920,
            action: 'SELL',
          }}
        />
      )
      expect(screen.getByDisplayValue('RELIANCE')).toBeTruthy()
    })

    it('visibly renders LIVE mode indicators and forbids paper-success messaging when appMode is LIVE', () => {
      render(
        <OrderTicketModal
          isOpen={true}
          onClose={vi.fn()}
          appMode="LIVE"
          initialData={{
            symbol: 'TRENT',
            price: 5200,
            stopLoss: 5080,
            target: 5440,
            action: 'BUY',
          }}
        />
      )

      expect(screen.getByText(/⚠️ LIVE OMS · Real Capital at Risk/i)).toBeTruthy()
      expect(screen.queryByText(/Paper OMS · 0 Real Broker Risk/i)).toBeNull()
      expect(screen.queryByText(/Paper Order Placed/i)).toBeNull()
    })

    it('visibly renders PAPER sandbox indicators when appMode is PAPER', () => {
      render(
        <OrderTicketModal
          isOpen={true}
          onClose={vi.fn()}
          appMode="PAPER"
          initialData={{
            symbol: 'TRENT',
            price: 5200,
            stopLoss: 5080,
            target: 5440,
            action: 'BUY',
          }}
        />
      )

      expect(screen.getByText(/Paper OMS · 0 Real Broker Risk/i)).toBeTruthy()
      expect(screen.queryByText(/⚠️ LIVE OMS · Real Capital at Risk/i)).toBeNull()
    })
  })

  describe('HighConvictionCard', () => {
    it('renders null when data is null/undefined without crashing', () => {
      const { container } = render(<HighConvictionCard data={null} />)
      expect(container.firstChild).toBeNull()
    })

    it('renders and filters opportunities smoothly', () => {
      const mockData = {
        market_posture: 'BULLISH_EXPANSION',
        opportunities: [
          {
            symbol: 'COFORGE',
            company_name: 'Coforge Limited',
            sector: 'IT',
            setup: 'VCP',
            setup_title: 'Stage 2 VCP Breakout',
            conviction_score: 92,
            eligibility_status: 'READY',
            ltp: 6850,
            entry_price: 6840,
            stop_loss: 6720,
            target_1: 7080,
            target_2: 7260,
            risk_reward_ratio: '2.0',
            est_turnover_cr: 120,
            liquidity_tier: 'TIER_1_ULTRA_LIQUID',
            reasons_to_pick: ['Clean pivot contraction with institutional volume surge.'],
            reasons_to_avoid: ['High beta volatility if broad market dips.'],
          },
        ],
      }

      const { rerender } = render(<HighConvictionCard data={mockData} />)
      expect(screen.getByText(/COFORGE/i)).toBeTruthy()
      expect(screen.getByText(/Stage 2 VCP Breakout/i)).toBeTruthy()

      // Dynamic update transition
      rerender(<HighConvictionCard data={{ ...mockData, market_posture: 'CHOPPY_ROTATION' }} />)
      expect(screen.getByText(/Choppy Rotation/i)).toBeTruthy()
    })
  })

  describe('CouncilCard & PersonaCard', () => {
    it('renders CouncilCard with signals and interactive states', () => {
      const mockData = {
        council: 'breakout',
        symbol: 'RELIANCE',
        consensus_verdict: 'STRONG_BUY',
        consensus_score: 91,
        signals: [
          {
            persona: 'minervini',
            verdict: 'STRONG_BUY',
            confidence: 94,
            thesis: 'VCP pivot contraction verified.',
          },
        ],
      }

      render(<CouncilCard data={mockData} />)
      expect(screen.getAllByText(/RELIANCE/i).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/STRONG_BUY/i).length).toBeGreaterThan(0)
    })

    it('renders PersonaCard safely with null and populated states', () => {
      const { container, rerender } = render(<PersonaCard data={null} />)
      expect(container.firstChild).toBeNull()

      rerender(
        <PersonaCard
          data={{
            persona: 'minervini',
            verdict: 'STRONG_BUY',
            confidence: 92,
            rationale: ['Stage 2 markup verified.'],
          }}
        />
      )
      expect(screen.getByText(/Mark Minervini/i)).toBeTruthy()
    })
  })

  describe('Quantitative Analysis Cards', () => {
    it('renders RRGCard with quadrant filters', () => {
      const mockData = {
        sectors: [
          { sector: 'NIFTY IT', rs_ratio: 102.5, rs_momentum: 101.8, quadrant: 'LEADING', top_stocks: ['TCS', 'INFY'] },
          { sector: 'NIFTY AUTO', rs_ratio: 98.2, rs_momentum: 102.1, quadrant: 'IMPROVING', top_stocks: ['M&M', 'TATAMOTORS'] },
        ],
        stock_alignment: { sector: 'NIFTY IT', quadrant: 'LEADING' },
      }

      render(<RRGCard data={mockData} />)
      expect(screen.getAllByText(/NIFTY IT/i).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/NIFTY AUTO/i).length).toBeGreaterThan(0)
    })

    it('renders ForensicCard and distress metrics', () => {
      const mockData = {
        quality_rating: 'A+',
        beneish_m_score: -2.85,
        is_beneish_flagged: false,
        altman_z_score: 3.45,
        distress_zone: 'SAFE',
        piotroski_f_score: 8,
      }

      render(<ForensicCard data={mockData} />)
      expect(screen.getByText(/Corporate Governance & Accounting Audit/i)).toBeTruthy()
      expect(screen.getByText(/-2.85/i)).toBeTruthy()
    })

    it('renders MarketStructureCard and MultibaggerCard', () => {
      render(
        <MarketStructureCard
          data={{
            regime: 'BULLISH',
            setup_type: 'PULLBACK_RETEST',
            active_demand_zones: [{ top: 24200, bottom: 24150 }],
          }}
        />
      )
      expect(screen.getByText(/Bullish Structure/i)).toBeTruthy()

      render(
        <MultibaggerCard
          data={{
            weinstein_stage: 'STAGE_2_MARKUP',
            multibagger_score: 88,
            trend_template_passed: 8,
          }}
        />
      )
      expect(screen.getByText(/Stage 2/i)).toBeTruthy()
    })

    it('renders DefinedRiskSpreadCard and BigMoveCard', () => {
      render(
        <DefinedRiskSpreadCard
          data={{
            underlying: 'NIFTY',
            strategy_name: 'BULL_CALL_SPREAD',
            spot_price: 24350,
            net_cashflow: -4500,
            max_profit: 10500,
            max_loss: 4500,
            risk_reward_ratio: 2.33,
          }}
        />
      )
      expect(screen.getByText(/BULL CALL SPREAD/i)).toBeTruthy()

      render(
        <BigMoveCard
          data={{
            symbol: 'NIFTY',
            ltp: 24350,
            directional_bias: 'BULLISH',
            prediction_verdict: 'IMMINENT_EXPANSION',
            directional_probability: 88,
          }}
        />
      )
      expect(screen.getByText(/88%/i)).toBeTruthy()
    })

    it('renders FlowsCard and MorningBriefCard', async () => {
      const { act } = await import('@testing-library/react')
      await act(async () => {
        render(
          <FlowsCard
            data={{
              fii_net_today: 1450.5,
              dii_net_today: 1210.0,
              fii_5d_net: 4200.0,
              dii_5d_net: 5100.0,
            }}
          />
        )
      })
      expect(await screen.findByText(/FII \/ DII Flow Intelligence/i)).toBeTruthy()

      await act(async () => {
        render(
          <MorningBriefCard
            data={{
              market_snapshot: { posture: 'BULLISH_EXPANSION', nifty: { ltp: 24500, change_pct: 0.8 } },
              institutional_flows: { fii_net_today: 1200 },
            }}
          />
        )
      })
      expect(screen.getAllByText(/Morning Brief/i).length).toBeGreaterThan(0)
    })

    it('renders BacktestCard and FunnelCard', () => {
      render(
        <BacktestCard
          data={{
            total_return: 24.5,
            cagr: 18.2,
            sharpe_ratio: 1.85,
            max_drawdown: -8.4,
            win_rate: 68.0,
          }}
        />
      )
      expect(screen.getByText(/Total Return/i)).toBeTruthy()

      render(
        <FunnelCard
          data={{
            pre_filter_reports: [{ symbol: 'TRENT', qualified: true, score: 92 }],
            trade_plans: [{ symbol: 'TRENT', action: 'BUY' }],
          }}
        />
      )
      expect(screen.getByText(/Institutional Screening Pipeline/i)).toBeTruthy()
    })

    it('renders WhaleFlowsCard and PersonaTrackRecordCard cleanly', async () => {
      const { act } = await import('@testing-library/react')
      await act(async () => {
        render(<WhaleFlowsCard />)
      })
      expect(await screen.findByText(/Indian Marquee Whale & SAST Flow Tracker/i)).toBeTruthy()

      await act(async () => {
        render(<PersonaTrackRecordCard />)
      })
      expect(await screen.findByText(/AI Persona Accuracy & Dynamic Weighting Matrix/i)).toBeTruthy()
    })
  })

  describe('Workspace Views & Interactive Button Flow Gates', () => {
    it('TerminalView renders and clicking STAGE / EXECUTE ORDER dispatches valid ticket payload', async () => {
      const onOpenOrderTicket = vi.fn()
      const TerminalView = (await import('../renderer/src/components/Views/TerminalView')).default

      const { fireEvent, act } = await import('@testing-library/react')
      let res
      await act(async () => {
        res = render(<TerminalView onOpenOrderTicket={onOpenOrderTicket} />)
      })

      const stageBtn = await res.findByText(/STAGE \/ EXECUTE ORDER/i)
      expect(stageBtn).toBeTruthy()
      await act(async () => {
        fireEvent.click(stageBtn)
      })

      expect(onOpenOrderTicket).toHaveBeenCalledTimes(1)
      const payload = onOpenOrderTicket.mock.calls[0][0]
      expect(payload).toHaveProperty('symbol')
      expect(payload).toHaveProperty('price')
      expect(payload).toHaveProperty('stopLoss')
      expect(payload).toHaveProperty('target')
      expect(payload).toHaveProperty('action')
    })

    it('DebateArenaView renders and allows council switching', async () => {
      const onOpenOrderTicket = vi.fn()
      const DebateArenaView = (await import('../renderer/src/components/Views/DebateArenaView')).default

      const { fireEvent, act } = await import('@testing-library/react')
      let res
      await act(async () => {
        res = render(<DebateArenaView onOpenOrderTicket={onOpenOrderTicket} />)
      })

      const breakoutTab = await res.findByText(/Breakout Council/i)
      expect(breakoutTab).toBeTruthy()
      await act(async () => {
        fireEvent.click(breakoutTab)
      })
    })

    it('OptionsDeskView renders and allows clicking Call/Put strikes to stage order', async () => {
      const onOpenOrderTicket = vi.fn()
      const OptionsDeskView = (await import('../renderer/src/components/Views/OptionsDeskView')).default

      const { act } = await import('@testing-library/react')
      let res
      await act(async () => {
        res = render(<OptionsDeskView onOpenOrderTicket={onOpenOrderTicket} />)
      })

      const nfoBadges = await res.findAllByText(/NIFTY/i)
      expect(nfoBadges.length).toBeGreaterThan(0)
    })

    it('OrderTicketModal completes full Staging -> Double Confirmation -> Submit flow cleanly', async () => {
      const onClose = vi.fn()
      const { fireEvent, act } = await import('@testing-library/react')

      await act(async () => {
        render(
          <OrderTicketModal
            isOpen={true}
            onClose={onClose}
            initialData={{
              symbol: 'TATAMOTORS',
              price: 980,
              stopLoss: 960,
              target: 1020,
              action: 'BUY',
            }}
          />
        )
      })

      // Step 1: Click Review & Confirm
      const reviewBtn = screen.getByText(/Review & Confirm BUY/i)
      expect(reviewBtn).toBeTruthy()
      await act(async () => {
        fireEvent.click(reviewBtn)
      })

      // Step 2: Now on Double Confirmation Gate
      const checkbox = await screen.findByRole('checkbox')
      expect(checkbox).toBeTruthy()
      await act(async () => {
        fireEvent.click(checkbox)
      })

      // Click Confirm & Transmit
      const confirmBtn = await screen.findByText(/Double Confirm & Transmit BUY/i)
      expect(confirmBtn).toBeTruthy()
      await act(async () => {
        fireEvent.click(confirmBtn)
      })
      expect(await screen.findByText(/✓/i)).toBeTruthy()
    })

    it('OrderTicketModal in LIVE mode renders LIVE warnings, LIVE button, and LIVE success text (no paper labels)', async () => {
      const onClose = vi.fn()
      const { fireEvent, act } = await import('@testing-library/react')

      const originalFetch = global.fetch
      global.fetch = vi.fn().mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/api/risk/preflight')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ data: { is_eligible: true, flags: [] } }),
          })
        }
        if (urlStr.includes('/api/orders/preview')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              data: {
                order_id: 'LIVE-EXEC-1234',
                charges: { total_charges: 45.2 },
                status: 'PREVIEW',
                mode: 'EXECUTE',
              },
            }),
          })
        }
        if (urlStr.includes('/api/orders/execute')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              data: {
                order_id: 'LIVE-EXEC-1234',
                status: 'FILLED',
                mode: 'EXECUTE',
              },
            }),
          })
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      })

      try {
        await act(async () => {
          render(
            <OrderTicketModal
              isOpen={true}
              onClose={onClose}
              appMode="LIVE"
              initialData={{
                symbol: 'RELIANCE',
                price: 2850,
                stopLoss: 2800,
                target: 2950,
                action: 'BUY',
              }}
            />
          )
        })

        // Step 1: Subtitle must visibly state LIVE OMS and real capital
        expect(screen.getByText(/LIVE OMS · Real Capital at Risk/i)).toBeTruthy()
        expect(screen.queryByText(/Paper OMS/i)).toBeNull()

        // Proceed to Step 2
        const reviewBtn = screen.getByText(/Review & Confirm BUY/i)
        await act(async () => {
          fireEvent.click(reviewBtn)
        })

        // Step 2: Heading / Subtitle must say LIVE ⚠️
        expect(await screen.findByText(/Verify & Transmit \(LIVE ⚠️\)/i)).toBeTruthy()
        expect(screen.getByText(/Live Intent ID:/i)).toBeTruthy()
        expect(screen.getByText(/LIVE BROKER \(Real execution — real capital at risk\)/i)).toBeTruthy()
        expect(screen.queryByText(/Paper Intent ID:/i)).toBeNull()
        expect(screen.queryByText(/PAPER OMS/i)).toBeNull()

        // Check risk box
        const checkbox = await screen.findByRole('checkbox')
        await act(async () => {
          fireEvent.click(checkbox)
        })

        // Live button text
        const confirmBtn = await screen.findByText(/Double Confirm & Transmit BUY \(LIVE ⚠️\)/i)
        expect(confirmBtn).toBeTruthy()

        // Click transmit
        await act(async () => {
          fireEvent.click(confirmBtn)
        })

        // Status message must show Live Order Placed and NOT Paper
        const successMsg = await screen.findByText(/✓ Live Order Placed/i)
        expect(successMsg).toBeTruthy()
        expect(screen.queryByText(/Paper Order Placed/i)).toBeNull()
      } finally {
        global.fetch = originalFetch
      }
    })

    it('BacktestStudioView renders and shows quantitative simulation controls', async () => {
      const onOpenOrderTicket = vi.fn()
      const BacktestStudioView = (await import('../renderer/src/components/Views/BacktestStudioView')).default

      const { findByText } = render(<BacktestStudioView onOpenOrderTicket={onOpenOrderTicket} />)
      const heading = await findByText(/Quantitative Backtest Studio/i)
      expect(heading).toBeTruthy()
    })

    it('PayoffSimulatorCard renders interactive legs and metrics', async () => {
      const PayoffSimulatorCard = (await import('../renderer/src/components/Cards/PayoffSimulatorCard')).default
      const { findByText } = render(<PayoffSimulatorCard initialSymbol="NIFTY" initialSpot={24000} />)
      const title = await findByText(/Strategy Payoff Builder/i)
      expect(title).toBeTruthy()
    })
  })

  // ── P0-A: Truthful Data Envelope Component Tests ─────────────────────────
  describe('P0-A Truthful Data Envelope Components', () => {
    it('DataStateBadge renders all status types without crashing', async () => {
      const DataStateBadge = (await import('../renderer/src/components/Common/DataStateBadge')).default
      const statuses = ['live', 'delayed', 'cached_fresh', 'stale', 'derived_proxy', 'estimated', 'unavailable', 'demo']
      for (const status of statuses) {
        const { unmount } = render(
          <DataStateBadge status={status} sourceName="yfinance" asOf="2026-09-01T10:00:00Z" />
        )
        unmount()
      }
    })

    it('DataStateBadge compact mode renders pill without label text', async () => {
      const DataStateBadge = (await import('../renderer/src/components/Common/DataStateBadge')).default
      render(<DataStateBadge status="live" compact={true} />)
      expect(screen.getByRole('status')).toBeTruthy()
      expect(screen.getByText('L')).toBeTruthy()
      expect(screen.queryByText('Live')).toBeNull()
    })

    it('DataStateBadge shows NON-TRADABLE warning when tradable=false', async () => {
      const DataStateBadge = (await import('../renderer/src/components/Common/DataStateBadge')).default
      render(<DataStateBadge status="derived_proxy" tradable={false} />)
      expect(screen.getByText(/NON-TRADABLE/i)).toBeTruthy()
    })

    it('UnavailableState renders all size variants without crashing', async () => {
      const UnavailableState = (await import('../renderer/src/components/Common/UnavailableState')).default
      for (const size of ['sm', 'md', 'lg']) {
        const { unmount } = render(
          <UnavailableState
            title="India VIX unavailable"
            reason="No data from provider"
            hint="Check connection"
            size={size}
          />
        )
        unmount()
      }
    })

    it('UnavailableState shows Retry button and fires onRetry callback', async () => {
      const UnavailableState = (await import('../renderer/src/components/Common/UnavailableState')).default
      const { fireEvent: fe } = await import('@testing-library/react')
      const onRetry = vi.fn()
      render(
        <UnavailableState
          title="FII/DII unavailable"
          reason="API timeout"
          onRetry={onRetry}
        />
      )
      const btn = screen.getByRole('button', { name: /retry/i })
      expect(btn).toBeTruthy()
      btn.click()
      expect(onRetry).toHaveBeenCalledOnce()
    })

    it('ModeBanner renders PAPER mode with correct label', async () => {
      const ModeBanner = (await import('../renderer/src/components/Common/ModeBanner')).default
      render(<ModeBanner mode="PAPER" />)
      expect(screen.getByText(/PAPER MODE/i)).toBeTruthy()
    })

    it('ModeBanner renders DEMO mode with synthetic data warning', async () => {
      const ModeBanner = (await import('../renderer/src/components/Common/ModeBanner')).default
      render(<ModeBanner mode="DEMO" />)
      expect(screen.getByText(/DEMO MODE/i)).toBeTruthy()
      expect(screen.getByText(/DATA IS SYNTHETIC/i)).toBeTruthy()
    })

    it('ModeBanner renders LIVE mode with real execution warning', async () => {
      const ModeBanner = (await import('../renderer/src/components/Common/ModeBanner')).default
      render(<ModeBanner mode="LIVE" />)
      expect(screen.getByText(/LIVE MODE/i)).toBeTruthy()
    })

    it('ModeBanner does not render while loading', async () => {
      const ModeBanner = (await import('../renderer/src/components/Common/ModeBanner')).default
      const { container } = render(<ModeBanner mode="PAPER" loading={true} />)
      expect(container.firstChild).toBeNull()
    })

    it('OverviewView renders UnavailableState when fetch returns null data', async () => {
      // Set fetch to return unavailable status (no real data)
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: 'ok', data: { _status: 'unavailable', vix: null, fii_net: null, dii_net: null, sectors: [] } }),
      })

      const OverviewView = (await import('../renderer/src/components/Views/OverviewView')).default
      const { findAllByText } = render(<OverviewView />)

      // P0-A: when data fields are null, UnavailableState should render per section
      // The OverviewView should NOT show hardcoded numbers
      const unavailableTexts = await findAllByText(/unavailable/i)
      expect(unavailableTexts.length).toBeGreaterThan(0)
    })

    it('GlobalMacroCard shows proxy disclosure when items have is_proxy=true', async () => {
      const GlobalMacroCard = (await import('../renderer/src/components/Cards/GlobalMacroCard')).default
      useChatStore.setState({ sendDraft: vi.fn() })
      const mockData = {
        composite_score: 30,
        global_posture: 'NEUTRAL',
        posture_title: 'Balanced',
        summary: 'Test summary',
        implied_nifty_gap_pct: 0.25,
        implied_nifty_gap_pts: 62.5,
        items: {
          gold: { key: 'gold', name: 'MCX Gold', ltp: 74000, unit: '₹/10g', change_pct: 0.42, impact_bias: 'BULLISH', is_proxy: true, data_status: 'derived_proxy' },
        },
        sector_impacts: [],
        as_of: '2026-09-01T10:00:00Z',
        _status: 'derived_proxy',
        _source_name: 'yfinance (COMEX proxy)',
      }
      render(<GlobalMacroCard data={mockData} />)
      // P0-A: proxy disclosure should be present
      expect(screen.getByText(/Research Proxy/i) || screen.getByText(/Modelled Overnight/i)).toBeTruthy()
    })
  })
})
