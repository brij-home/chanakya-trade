import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import QuantRadarPanel from '../renderer/src/components/Views/QuantRadarPanel'
import { useChatStore } from '../renderer/src/store/chatStore'

describe('QuantRadarPanel UI Tests', () => {
  beforeEach(() => {
    useChatStore.setState({ port: 8765, sidecarError: null })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('renders readiness, armed radar, multi-profile tournament, and honest IV unavailable state', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      const s = String(url)
      if (s.includes('/skills/quant/readiness')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: 'ok',
              data: {
                execution_safety: { trading_mode: 'PAPER', live_orders_blocked: true },
                discovery_policy: { profile: 'FNO_PRIORITY', fno_only: false },
                broker_and_feed: { fyers_token: { fresh_since_0630_ist: true } },
                calibration_and_research: { meta_model_status: 'CALIBRATED', meta_model_samples: 17159, meta_model_oos_brier: 0.1398 },
                open_gaps: ['IV daily surface depth < 20 sessions'],
              },
            }),
        })
      }
      if (s.includes('/skills/quant/armed-radar')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: 'ok',
              data: {
                items: [
                  {
                    symbol: 'NIFTY',
                    stage: 'ARMED',
                    direction: 'BULLISH',
                    anchor_name: 'PDH',
                    anchor_price: 25100,
                    distance_atr: 0.21,
                    tbt_scout_promoted: true,
                  },
                ],
              },
            }),
        })
      }
      if (s.includes('/skills/quant/tournament')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: 'ok',
              data: {
                status: 'COMPLETED',
                profiles: {
                  FUTURES_15M_SWING: {
                    detectors: {
                      LEVEL_ARMED_TRIGGER: { trades: 120, win_rate_pct: 42.5, net_expectancy_r: 0.22, governance: 'PROMOTED_SHADOW' },
                    },
                  },
                },
              },
            }),
        })
      }
      if (s.includes('/skills/quant/meta-labeler')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', data: { model_status: 'CALIBRATED', model: { sample_count: 17159, oos_brier_score: 0.1398 } } }),
        })
      }
      if (s.includes('/skills/quant/iv-surface/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', data: { status: 'AVAILABLE', atm_iv_30d: 14.5, iv_rank: null, vrp: 1.9, skew_25d: 0.08 } }),
        })
      }
      if (s.includes('/skills/quant/cas-regime/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', data: { segment_close: '15:40:00', entry_cutoff: '15:15:00', allow_new_entry: true, is_cas_dispersion_window: false } }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'ok', data: { wins: 3, losses: 1, net_r: 2.4, why_top_driver: 'OPEN_DRIVE' } }),
      })
    })

    render(<QuantRadarPanel />)

    await waitFor(() => {
      expect(screen.getByText('MODE: PAPER')).toBeInTheDocument()
      expect(screen.getByText('SCOPE: FNO_PRIORITY')).toBeInTheDocument()
      expect(screen.getByText('IVR UNAVAILABLE')).toBeInTheDocument()
      expect(screen.getAllByText('NIFTY').length).toBeGreaterThanOrEqual(2)
      expect(screen.getByText('PROMOTED_SHADOW')).toBeInTheDocument()
      expect(screen.getByText(/IV daily surface depth < 20 sessions/)).toBeInTheDocument()
    })
  })
})
