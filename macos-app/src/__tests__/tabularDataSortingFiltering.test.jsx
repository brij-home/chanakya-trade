import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useChatStore } from '../renderer/src/store/chatStore'
import InflectionScannerView from '../renderer/src/components/Views/InflectionScannerView'
import BacktestStudioView from '../renderer/src/components/Views/BacktestStudioView'
import PortfolioView from '../renderer/src/components/Views/PortfolioView'

// Mock ResizeObserver & matchMedia
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

// Sample Inflection Scan Result
const sampleInflectionData = {
  universe: 'multibagger_hunters',
  total_scanned: 3,
  qualified_count: 3,
  archetype_counts: {
    VCP_PIVOT_BREAKOUT: 1,
    TTM_SQUEEZE_EXPLOSION: 1,
    STAGE_1_TO_2_EXPANSION: 1,
  },
  top_sectors: [
    { sector: 'Electronics', count: 1, icon: '🔌' },
    { sector: 'Defense', count: 1, icon: '🛡️' },
    { sector: 'Retail', count: 1, icon: '🛍️' },
  ],
  candidates: [
    {
      symbol: 'DIXON',
      name: 'Dixon Technologies Ltd',
      sector: 'Electronics',
      sector_icon: '🔌',
      ltp: 14250.0,
      day_change_pct: 3.5,
      inflection_score: 88,
      primary_archetype: 'VCP_PIVOT_BREAKOUT',
      archetype_label: 'VCP Pivot Breakout',
      timing_state: 'TRIGGER_NOW',
      timing_label: '🔥 Trigger Now',
      weinstein_stage: 'STAGE_2_UPTREND',
      squeeze_state: 'NORMAL',
      rvol_20d: 2.2,
      trend_template_passed: 8,
      cap_tier: 'LARGE',
      entry_price: 14200.0,
      stop_loss: 13800.0,
      target_1: 15000.0,
      risk_reward_ratio: 3.2,
      circuit_state: 'NORMAL',
      executive_verdict: 'STRONG_BUY',
    },
    {
      symbol: 'BEL',
      name: 'Bharat Electronics Ltd',
      sector: 'Defense',
      sector_icon: '🛡️',
      ltp: 310.0,
      day_change_pct: -1.2,
      inflection_score: 72,
      primary_archetype: 'TTM_SQUEEZE_EXPLOSION',
      archetype_label: 'TTM Squeeze',
      timing_state: 'COILING_IMMINENT',
      timing_label: '⏳ Coiling (1–3d)',
      weinstein_stage: 'STAGE_2_UPTREND',
      squeeze_state: 'COILING',
      rvol_20d: 1.1,
      trend_template_passed: 7,
      cap_tier: 'MID',
      entry_price: 315.0,
      stop_loss: 300.0,
      target_1: 345.0,
      risk_reward_ratio: 2.0,
      circuit_state: 'NORMAL',
      executive_verdict: 'MOMENTUM_WATCH',
    },
    {
      symbol: 'TRENT',
      name: 'Trent Ltd',
      sector: 'Retail',
      sector_icon: '🛍️',
      ltp: 7200.0,
      day_change_pct: 4.8,
      inflection_score: 95,
      primary_archetype: 'STAGE_1_TO_2_EXPANSION',
      archetype_label: 'Stage 1→2 Markup',
      timing_state: 'TRIGGER_NOW',
      timing_label: '🔥 Trigger Now',
      weinstein_stage: 'STAGE_2_UPTREND',
      squeeze_state: 'COILING',
      rvol_20d: 2.8,
      trend_template_passed: 8,
      cap_tier: 'LARGE',
      entry_price: 7150.0,
      stop_loss: 6900.0,
      target_1: 7650.0,
      risk_reward_ratio: 4.0,
      circuit_state: 'UPPER_CIRCUIT_LOCKED',
      executive_verdict: 'UC_MOMENTUM',
    },
  ],
}

// Sample Backtest Data
const sampleBacktestData = {
  data: {
    total_return: 42.5,
    cagr: 28.3,
    sharpe_ratio: 1.85,
    max_drawdown: -8.4,
    win_rate: 65.0,
    total_trades: 4,
    profit_factor: 2.1,
    equity_curve: [{ step: 0, value: 1000000 }, { step: 1, value: 1425000 }],
    trades: [
      {
        entry_date: '2026-01-10',
        type: 'LONG',
        entry: 1000,
        exit: 1100,
        pnl: 10000,
        pct: 10.0,
        r: 2.5,
        reason: 'Target 1 hit',
      },
      {
        entry_date: '2026-02-15',
        type: 'LONG',
        entry: 1200,
        exit: 1150,
        pnl: -5000,
        pct: -4.1,
        r: -1.0,
        reason: 'Stop Loss triggered',
      },
      {
        entry_date: '2026-03-20',
        type: 'LONG',
        entry: 1180,
        exit: 1350,
        pnl: 17000,
        pct: 14.4,
        r: 3.5,
        reason: 'Trailing 20-EMA exit',
      },
      {
        entry_date: '2026-04-05',
        type: 'SHORT',
        entry: 1320,
        exit: 1300,
        pnl: 2000,
        pct: 1.5,
        r: 0.8,
        reason: 'Target 1 hit',
      },
    ],
  },
}

// Sample Portfolio Data
const samplePortfolioData = {
  brokers: ['Zerodha'],
  funds: {
    total_balance: 1500000,
    available_cash: 500000,
  },
  total_pnl: 45000,
  holdings: [
    {
      symbol: 'TCS',
      broker: 'Zerodha',
      product: 'CNC',
      qty: 50,
      avg_price: 3800.0,
      ltp: 4100.0,
      pnl: 15000.0,
    },
    {
      symbol: 'INFY',
      broker: 'Zerodha',
      product: 'CNC',
      qty: 100,
      avg_price: 1850.0,
      ltp: 1780.0,
      pnl: -7000.0,
    },
  ],
  positions: [
    {
      symbol: 'RELIANCE',
      broker: 'Zerodha',
      product: 'MIS',
      qty: 100,
      avg_price: 2900.0,
      ltp: 2950.0,
      pnl: 5000.0,
    },
  ],
}

// Global fetch mock
global.fetch = vi.fn().mockImplementation((url, opts) => {
  const urlStr = String(url)
  if (urlStr.includes('/skills/inflection_scan')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ data: sampleInflectionData }),
    })
  }
  if (urlStr.includes('/skills/inflection_universes')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ data: { universes: [{ id: 'multibagger_hunters', name: 'Multibagger Hunters', count: 45 }] } }),
    })
  }
  if (urlStr.includes('/skills/eod_store_status')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ data: { cached_symbols_count: 100, total_bars_count: 50000 } }),
    })
  }
  if (urlStr.includes('/skills/backtest')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(sampleBacktestData),
    })
  }
  if (urlStr.includes('/api/portfolio')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(samplePortfolioData),
    })
  }
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({}),
  })
})

describe('Tabular Data Sorting and Multi-Criteria Filtering', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useChatStore.setState({
      port: 8765,
      appMode: 'PAPER',
      activeView: 'scanner',
    })
  })

  describe('InflectionScannerView Sorting & Filtering', () => {
    it('renders sortable headers with aria-sort and directional arrows', async () => {
      render(<InflectionScannerView />)

      // Trigger initial scan to load candidates
      const rescanBtn = screen.getByRole('button', { name: /rescan|scanning/i })
      fireEvent.click(rescanBtn)

      await waitFor(() => {
        expect(screen.getByText('DIXON')).toBeInTheDocument()
      })

      // Check sortable headers
      const symbolHeader = screen.getByTitle(/sort by symbol \/ asset/i)
      expect(symbolHeader).toBeInTheDocument()

      const scoreHeader = screen.getByTitle(/sort by inflection score/i)
      expect(scoreHeader).toBeInTheDocument()
      expect(scoreHeader).toHaveAttribute('aria-sort', 'descending')

      const ltpHeader = screen.getByTitle(/sort by ltp/i)
      expect(ltpHeader).toBeInTheDocument()

      // Click Symbol header to sort alphabetically
      fireEvent.click(symbolHeader)
      expect(symbolHeader).toHaveAttribute('aria-sort', 'ascending')

      // Click Symbol header again to reverse sort direction
      fireEvent.click(symbolHeader)
      expect(symbolHeader).toHaveAttribute('aria-sort', 'descending')
    })

    it('filters candidates by archetype and timing tabs', async () => {
      render(<InflectionScannerView />)

      // Load data
      fireEvent.click(screen.getByRole('button', { name: /rescan|scanning/i }))
      await waitFor(() => {
        expect(screen.getByText('DIXON')).toBeInTheDocument()
      })

      // Click VCP Pivots archetype tab
      const vcpTab = screen.getByRole('button', { name: /vcp pivots/i })
      fireEvent.click(vcpTab)

      // Only DIXON should be visible (BEL and TRENT filtered out)
      expect(screen.getByText('DIXON')).toBeInTheDocument()
      expect(screen.queryByText('BEL')).not.toBeInTheDocument()
      expect(screen.queryByText('TRENT')).not.toBeInTheDocument()

      // Reset back to All Inflections
      fireEvent.click(screen.getByRole('button', { name: /all inflections/i }))
      expect(screen.getByText('DIXON')).toBeInTheDocument()
      expect(screen.getByText('BEL')).toBeInTheDocument()
      expect(screen.getByText('TRENT')).toBeInTheDocument()
    })

    it('supports quick condition toggles (e.g. Squeeze Coiling, Exclude UC)', async () => {
      render(<InflectionScannerView />)

      fireEvent.click(screen.getByRole('button', { name: /rescan|scanning/i }))
      await waitFor(() => {
        expect(screen.getByText('DIXON')).toBeInTheDocument()
      })

      // Toggle Exclude UC Locked
      const excludeUCBtn = screen.getByRole('button', { name: /exclude uc locked/i })
      fireEvent.click(excludeUCBtn)

      // TRENT is UC locked, so it should be excluded
      expect(screen.queryByText('TRENT')).not.toBeInTheDocument()
      expect(screen.getByText('DIXON')).toBeInTheDocument()
      expect(screen.getByText('BEL')).toBeInTheDocument()

      // Verify Reset Filters button appears and resets filters
      const resetBtn = screen.getByRole('button', { name: /reset filters/i })
      fireEvent.click(resetBtn)
      expect(screen.getByText('TRENT')).toBeInTheDocument()
    })
  })

  describe('BacktestStudioView Execution Ledger Sorting & Filtering', () => {
    it('renders execution ledger with sortable columns and search filter', async () => {
      render(<BacktestStudioView />)

      await waitFor(() => {
        expect(screen.getByText(/simulated trade history/i)).toBeInTheDocument()
      })

      // Verify search input exists
      const searchInput = screen.getByPlaceholderText(/search trades/i)
      expect(searchInput).toBeInTheDocument()

      // Search for 'Stop Loss'
      fireEvent.change(searchInput, { target: { value: 'Stop Loss' } })
      expect(screen.getByText(/stop loss triggered/i)).toBeInTheDocument()
      expect(screen.queryByText(/trailing 20-ema exit/i)).not.toBeInTheDocument()

      // Clear search
      const clearBtn = screen.getByTitle(/clear search/i)
      fireEvent.click(clearBtn)
      expect(screen.getByText(/trailing 20-ema exit/i)).toBeInTheDocument()

      // Click P&L header to sort by P&L
      const pnlHeader = screen.getByTitle(/sort by p&l/i)
      expect(pnlHeader).toBeInTheDocument()
      fireEvent.click(pnlHeader)
    })
  })

  describe('PortfolioView Holdings & Positions Sorting & Filtering', () => {
    it('renders positions table with search bar and sortable headers', async () => {
      render(<PortfolioView />)

      await waitFor(() => {
        expect(screen.getByText('Positions & Holdings')).toBeInTheDocument()
      })

      // Search for INFY
      const searchInput = screen.getByPlaceholderText(/search instruments/i)
      expect(searchInput).toBeInTheDocument()

      fireEvent.change(searchInput, { target: { value: 'INFY' } })
      expect(screen.getByText('INFY')).toBeInTheDocument()
      expect(screen.queryByText('TCS')).not.toBeInTheDocument()
      expect(screen.queryByText('RELIANCE')).not.toBeInTheDocument()

      // Clear search
      fireEvent.change(searchInput, { target: { value: '' } })
      expect(screen.getByText('TCS')).toBeInTheDocument()
      expect(screen.getByText('RELIANCE')).toBeInTheDocument()

      // Click Instrument header to sort
      const instHeader = screen.getByTitle(/sort by instrument/i)
      fireEvent.click(instHeader)
    })
  })
})
