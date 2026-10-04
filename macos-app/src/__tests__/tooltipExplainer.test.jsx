import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Tooltip, { HelpHint, InfoBadge } from '../renderer/src/components/UI/Tooltip'
import { METRIC_ENCYCLOPEDIA } from '../renderer/src/data/metricEncyclopedia'
import { useInspectorStore } from '../renderer/src/store/inspectorStore'

describe('Plain-English Financial & Technical Term Tooltips & Decision Guidance', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useInspectorStore.setState({ isOpen: false, activeMetric: null, contextData: null })
  })

  describe('METRIC_ENCYCLOPEDIA Glossary Integrity', () => {
    const requiredKeys = [
      'century_score',
      'twin_engines',
      'pat_expansion',
      'pe_rerating',
      'ten_year_multiple',
      'roce',
      'operating_leverage',
      'anti_fomo',
      'fair_value_zone',
      'no_chase_boundary',
      'pullback_limit',
      'risk_reward_ratio',
      'rvol',
      'timing_state',
      'vcp_pivot',
      'ttm_squeeze',
      'smc_spring_sweep',
      'rrg_leaders',
      'max_pain',
      'pcr',
      'gex',
      'iv_smile',
      'sharpe_ratio',
      'sortino_ratio',
      'max_drawdown',
      'profit_factor',
      'beneish_m_score',
      'altman_z_score',
      'piotroski_f_score',
    ]

    it.each(requiredKeys)('term "%s" defines plain-English explanation and actionable institutional decision guide', (key) => {
      const entry = METRIC_ENCYCLOPEDIA[key]
      expect(entry, `Entry for ${key} must exist`).toBeDefined()
      expect(entry.title).toBeTruthy()
      expect(entry.category).toBeTruthy()
      expect(typeof entry.explanation).toBe('string')
      expect(entry.explanation.length).toBeGreaterThan(20)
      expect(typeof entry.institutionalGuide).toBe('string')
      expect(entry.institutionalGuide.length).toBeGreaterThan(20)
    })
  })

  describe('Tooltip Component', () => {
    it('renders children and displays tooltip with decision guide on hover', () => {
      render(
        <Tooltip
          title="Twin Engines of Multibaggers"
          content="Stock Price = Earnings (EPS) × Valuation Multiple (P/E)."
          decisionHelp="Look for companies where PAT CAGR ≥ 25%."
        >
          <span data-testid="trigger-btn">Twin Engines</span>
        </Tooltip>
      )

      expect(screen.getByTestId('trigger-btn')).toBeTruthy()
      expect(screen.queryByRole('tooltip')).toBeNull()

      // Hover to trigger
      fireEvent.mouseEnter(screen.getByTestId('trigger-btn').parentElement)
      act(() => {
        vi.advanceTimersByTime(150)
      })

      const tooltip = screen.getByRole('tooltip')
      expect(tooltip).toBeTruthy()
      expect(screen.getByText('Twin Engines of Multibaggers')).toBeTruthy()
      expect(screen.getByText('Stock Price = Earnings (EPS) × Valuation Multiple (P/E).')).toBeTruthy()
      expect(screen.getByText('How It Helps You Decide:')).toBeTruthy()
      expect(screen.getByText('Look for companies where PAT CAGR ≥ 25%.')).toBeTruthy()
    })

    it('auto-resolves title, explanation, and decision takeaway from metricKey', () => {
      render(
        <Tooltip metricKey="anti_fomo">
          <span data-testid="anti-fomo-badge">Anti-FOMO State</span>
        </Tooltip>
      )

      fireEvent.mouseEnter(screen.getByTestId('anti-fomo-badge').parentElement)
      act(() => {
        vi.advanceTimersByTime(150)
      })

      const tooltip = screen.getByRole('tooltip')
      expect(tooltip).toBeTruthy()
      // Title resolved from METRIC_ENCYCLOPEDIA
      expect(screen.getByText(METRIC_ENCYCLOPEDIA.anti_fomo.title)).toBeTruthy()
      // Explanation resolved
      expect(screen.getByText(METRIC_ENCYCLOPEDIA.anti_fomo.explanation)).toBeTruthy()
      // Decision guide resolved
      expect(screen.getByText(METRIC_ENCYCLOPEDIA.anti_fomo.institutionalGuide)).toBeTruthy()
    })

    it('opens MetricExplainerModal inspector on click when metricKey is provided', () => {
      render(
        <Tooltip metricKey="gex">
          <button data-testid="gex-trigger">GEX Regime</button>
        </Tooltip>
      )

      fireEvent.click(screen.getByTestId('gex-trigger'))
      const state = useInspectorStore.getState()
      expect(state.isOpen).toBe(true)
      expect(state.activeMetric.key).toBe('gex')
      expect(state.activeMetric.title).toBe(METRIC_ENCYCLOPEDIA.gex.title)
    })
  })

  describe('HelpHint Component', () => {
    it('renders compact accessible button and displays decision guide on hover', () => {
      render(<HelpHint metricKey="pat_expansion" size="xs" />)

      const btn = screen.getByRole('button')
      expect(btn).toBeTruthy()
      expect(btn.textContent).toBe('?')

      // Hover over trigger container
      fireEvent.mouseEnter(btn.parentElement)
      act(() => {
        vi.advanceTimersByTime(150)
      })

      expect(screen.getByRole('tooltip')).toBeTruthy()
      expect(screen.getByText(METRIC_ENCYCLOPEDIA.pat_expansion.title)).toBeTruthy()
      expect(screen.getByText(METRIC_ENCYCLOPEDIA.pat_expansion.institutionalGuide)).toBeTruthy()
    })

    it('stops click propagation and opens full model inspector on click', () => {
      const parentClickHandler = vi.fn()
      render(
        <div onClick={parentClickHandler} data-testid="parent-header">
          <span>PAT CAGR Header</span>
          <HelpHint metricKey="pat_expansion" size="xs" />
        </div>
      )

      const btn = screen.getByRole('button')
      fireEvent.click(btn)

      // Parent click (e.g. column sorting) should not be triggered
      expect(parentClickHandler).not.toHaveBeenCalled()

      // Inspector store should be opened for pat_expansion
      const state = useInspectorStore.getState()
      expect(state.isOpen).toBe(true)
      expect(state.activeMetric.key).toBe('pat_expansion')
    })
  })

  describe('InfoBadge Component', () => {
    it('renders ℹ badge and opens inspector when clicked', () => {
      render(<InfoBadge metricKey="sharpe_ratio" />)

      const badge = screen.getByRole('button', { name: /Click for deep explanation/i })
      expect(badge).toBeTruthy()
      expect(badge.textContent).toBe('ℹ')

      fireEvent.click(badge)
      const state = useInspectorStore.getState()
      expect(state.isOpen).toBe(true)
      expect(state.activeMetric.key).toBe('sharpe_ratio')
    })
  })
})
