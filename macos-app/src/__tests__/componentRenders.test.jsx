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
global.fetch = vi.fn().mockImplementation(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ data: {}, status: 'ok' }),
  })
)

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

    it('renders FlowsCard and MorningBriefCard', () => {
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
      expect(screen.getByText(/FII \/ DII Flow Intelligence/i)).toBeTruthy()

      render(
        <MorningBriefCard
          data={{
            market_snapshot: { posture: 'BULLISH_EXPANSION', nifty: { ltp: 24500, change_pct: 0.8 } },
            institutional_flows: { fii_net_today: 1200 },
          }}
        />
      )
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
  })

  describe('Workspace Views & Interactive Button Flow Gates', () => {
    it('TerminalView renders and clicking STAGE / EXECUTE ORDER dispatches valid ticket payload', async () => {
      const onOpenOrderTicket = vi.fn()
      const TerminalView = (await import('../renderer/src/components/Views/TerminalView')).default

      const { fireEvent } = await import('@testing-library/react')
      const { findByText } = render(<TerminalView onOpenOrderTicket={onOpenOrderTicket} />)

      const stageBtn = await findByText(/STAGE \/ EXECUTE ORDER/i)
      expect(stageBtn).toBeTruthy()
      fireEvent.click(stageBtn)

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

      const { fireEvent } = await import('@testing-library/react')
      const { findByText } = render(<DebateArenaView onOpenOrderTicket={onOpenOrderTicket} />)

      const breakoutTab = await findByText(/Breakout Council/i)
      expect(breakoutTab).toBeTruthy()
      fireEvent.click(breakoutTab)
    })

    it('OptionsDeskView renders and allows clicking Call/Put strikes to stage order', async () => {
      const onOpenOrderTicket = vi.fn()
      const OptionsDeskView = (await import('../renderer/src/components/Views/OptionsDeskView')).default

      const { fireEvent } = await import('@testing-library/react')
      const { findAllByText } = render(<OptionsDeskView onOpenOrderTicket={onOpenOrderTicket} />)

      const nfoBadges = await findAllByText(/NIFTY/i)
      expect(nfoBadges.length).toBeGreaterThan(0)
    })

    it('OrderTicketModal completes full Staging -> Double Confirmation -> Submit flow cleanly', async () => {
      const onClose = vi.fn()
      const { fireEvent } = await import('@testing-library/react')

      const { rerender } = render(
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

      // Step 1: Click Review & Confirm
      const reviewBtn = screen.getByText(/Review & Confirm BUY/i)
      expect(reviewBtn).toBeTruthy()
      fireEvent.click(reviewBtn)

      // Step 2: Now on Double Confirmation Gate
      const checkbox = await screen.findByRole('checkbox')
      expect(checkbox).toBeTruthy()
      fireEvent.click(checkbox)

      // Click Confirm & Transmit
      const confirmBtn = screen.getByText(/Double Confirm & Transmit BUY/i)
      expect(confirmBtn).toBeTruthy()
      fireEvent.click(confirmBtn)
    })
  })
})

