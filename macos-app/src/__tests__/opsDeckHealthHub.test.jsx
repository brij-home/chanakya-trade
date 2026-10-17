import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'
import SystemHealthPill from '../renderer/src/components/Common/SystemHealthPill'
import OpsDrawer from '../renderer/src/components/Common/OpsDrawer'
import OpsDeckView from '../renderer/src/components/Views/OpsDeckView'
import { useChatStore } from '../renderer/src/store/chatStore'

describe('OpsDeck & System Health Hub UI Tests', () => {
  beforeEach(() => {
    useChatStore.setState({ port: 8765, sidecarError: null })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('SystemHealthPill renders nominal state when healthy', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            overall_status: 'HEALTHY',
            incident_counts: { P0: 0, P1: 0, P2: 0, P3: 0 },
            circuit_breaker: { state: 'CLOSED', remaining_cooldown_seconds: 0 },
          }),
      })
    )

    const onOpenDrawer = vi.fn()
    const onOpenOpsDeck = vi.fn()

    render(
      <SystemHealthPill onOpenDrawer={onOpenDrawer} onOpenOpsDeck={onOpenOpsDeck} />
    )

    await waitFor(() => {
      expect(screen.getByText('NOMINAL')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('NOMINAL'))
    expect(onOpenDrawer).toHaveBeenCalledTimes(1)
  })

  it('SystemHealthPill renders critical state and countdown when circuit breaker is tripped', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            overall_status: 'CRITICAL',
            incident_counts: { P0: 1, P1: 0, P2: 0, P3: 0 },
            circuit_breaker: { state: 'OPEN', remaining_cooldown_seconds: 45 },
          }),
      })
    )

    render(
      <SystemHealthPill onOpenDrawer={vi.fn()} onOpenOpsDeck={vi.fn()} />
    )

    await waitFor(() => {
      expect(screen.getByText(/BREAKER/i)).toBeInTheDocument()
    })
  })

  it('OpsDrawer renders circuit breaker controls and active incidents when open', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            overall_status: 'CRITICAL',
            incident_counts: { P0: 1, P1: 1, P2: 0, P3: 0 },
            circuit_breaker: {
              state: 'OPEN',
              remaining_cooldown_seconds: 30,
              last_trip_reason: 'Fyers REST Rate Limit Exceeded: 429',
            },
            websocket: { total_subscribed: 250, max_capacity: 5000, utilization_pct: 5.0 },
            incidents: [
              {
                priority: 'P0',
                component: 'FYERS_API',
                event_type: 'CIRCUIT_TRIP',
                reason: 'Fyers REST Rate Limit Exceeded: 429',
                action_taken: 'Trip to OPEN mode',
                timestamp: new Date().toISOString(),
              },
            ],
          }),
      })
    )

    const onClose = vi.fn()
    const onOpenOpsDeck = vi.fn()

    render(
      <OpsDrawer isOpen={true} onClose={onClose} onOpenOpsDeck={onOpenOpsDeck} />
    )

    await waitFor(() => {
      expect(screen.getByText('OpsDeck & Health Hub')).toBeInTheDocument()
      expect(screen.getAllByText(/CRITICAL/i).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/Fyers REST Rate Limit Exceeded/i).length).toBeGreaterThan(0)
    })

    const wsBtn = screen.getByText('Workspace ↗')
    fireEvent.click(wsBtn)
    expect(onClose).toHaveBeenCalled()
    expect(onOpenOpsDeck).toHaveBeenCalled()
  })

  it('OpsDeckView renders full institutional dashboard with tabs', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            overall_status: 'HEALTHY',
            incident_counts: { P0: 0, P1: 0, P2: 2, P3: 5 },
            circuit_breaker: { state: 'CLOSED', remaining_cooldown_seconds: 0 },
            websocket: { total_subscribed: 150, max_capacity: 5000, utilization_pct: 3.0, core_count: 96, dynamic_count: 54 },
            memory: { process_rss_mb: 450, system_ram_pct: 55 },
            storage: { ssd_free_gb: 80, total_size_mb: 120, tiers: { business: { size_mb: 20, wal_mb: 2 } } },
            incidents: [
              {
                priority: 'P2',
                component: 'MARKET_QUOTES',
                event_type: 'LATENCY',
                reason: 'Quote fetch latency slightly elevated (620ms)',
                action_taken: 'Logged to SLO buffer',
                timestamp: new Date().toISOString(),
              },
            ],
            provider_health: {
              overall_health: 'HEALTHY',
              providers: {
                fyers: {
                  health: 'HEALTHY',
                  total_requests: 120,
                  age_seconds: 4,
                  error_count: 0,
                  error_rate_pct: 0,
                },
              },
            },
            brokers: {
              fyers: { authenticated: true, configured: true, role: 'Data & Execution' },
              zerodha: { authenticated: false, configured: true, role: 'Execution' },
            },
            slo_report: {
              journeys: {
                quote_fetch: { description: 'Live Quote Fetch', availability_pct: 99.8, p95_latency_ms: 450, status: 'OK' },
              },
            },
            telemetry_summary: { recommendations: ['All indicators nominal.'] },
          }),
      })
    )

    render(<OpsDeckView />)

    await waitFor(() => {
      expect(screen.getByText('OpsDeck & System Health Terminal')).toBeInTheDocument()
      expect(screen.getByText(/HEALTHY/i)).toBeInTheDocument()
      expect(screen.getByTestId('tab-incidents')).toBeInTheDocument()
    })

    const feedsTab = screen.getByTestId('tab-feeds')
    await act(async () => {
      fireEvent.click(feedsTab)
    })

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Data Providers & Freshness Health/i })).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: /Broker Integrations & Session Status/i })).toBeInTheDocument()
      expect(screen.getAllByText(/fyers/i).length).toBeGreaterThan(0)
    })

    const storageTab = screen.getByTestId('tab-maintenance')
    await act(async () => {
      fireEvent.click(storageTab)
    })

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Disk Storage Allocations/i })).toBeInTheDocument()
      expect(screen.getByText(/Purge Ephemeral Cache/i)).toBeInTheDocument()
      expect(screen.getByText(/Sync Fundamentals/i)).toBeInTheDocument()
    })
  })
})
