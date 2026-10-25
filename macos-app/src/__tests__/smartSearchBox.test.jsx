import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import SmartSearchBox from '../renderer/src/components/Common/SmartSearchBox'
import {
  parseSearchQuery,
  matchesSmartSearchAlert,
  matchesSmartSearchCandidate,
  extractRiskRewardRatio,
  extractConvictionScore,
} from '../renderer/src/utils/smartSearchParser'

describe('Smart Search Parser & Directives Evaluator', () => {
  it('parses symbols, strikes, R:R thresholds, score, direction, and stages', () => {
    const q = 'sym:RELIANCE strike:2500CE rr:>3.0 score:>85 dir:bull stage:ignited'
    const parsed = parseSearchQuery(q)

    expect(parsed.hasDirectives).toBe(true)
    expect(parsed.directives.symbols).toEqual(['RELIANCE'])
    expect(parsed.directives.strikes).toEqual(['2500CE'])
    expect(parsed.directives.minRR).toBe(3.0)
    expect(parsed.directives.minScore).toBe(85)
    expect(parsed.directives.directions).toEqual(['BULLISH'])
    expect(parsed.directives.stages).toEqual(['IGNITED'])
  })

  it('handles fractional thresholds and alias resolution', () => {
    const q = 'rr:>=2.5 zomato'
    const parsed = parseSearchQuery(q)

    expect(parsed.directives.minRR).toBe(2.5)
    expect(parsed.terms).toEqual(['zomato'])
    expect(parsed.resolvedSymbols).toContain('ETERNAL')
  })

  it('evaluates alert against R:R, score, and symbol directives', () => {
    const alertA = {
      symbol: 'NSE:RELIANCE',
      contract_symbol: 'RELIANCE25FEB2500CE',
      direction: 'BULLISH',
      stage: 'IGNITED',
      confidence: 88,
      risk_reward: '1:3.4',
    }

    const alertB = {
      symbol: 'NSE:TCS',
      contract_symbol: 'TCS25FEB4000PE',
      direction: 'BEARISH',
      stage: 'PRIMED',
      confidence: 72,
      risk_reward: '1:2.0',
    }

    const queryHighRR = parseSearchQuery('rr:>3')
    expect(matchesSmartSearchAlert(alertA, queryHighRR)).toBe(true)
    expect(matchesSmartSearchAlert(alertB, queryHighRR)).toBe(false)

    const queryScore = parseSearchQuery('score:>80')
    expect(matchesSmartSearchAlert(alertA, queryScore)).toBe(true)
    expect(matchesSmartSearchAlert(alertB, queryScore)).toBe(false)

    const queryDir = parseSearchQuery('dir:bear')
    expect(matchesSmartSearchAlert(alertA, queryDir)).toBe(false)
    expect(matchesSmartSearchAlert(alertB, queryDir)).toBe(true)

    const querySym = parseSearchQuery('sym:RELIANCE')
    expect(matchesSmartSearchAlert(alertA, querySym)).toBe(true)
    expect(matchesSmartSearchAlert(alertB, querySym)).toBe(false)
  })

  it('matches free-text aliases like "zomato" to ETERNAL alert', () => {
    const alertZomato = {
      symbol: 'ETERNAL',
      headline: 'Q-Commerce delivery inflection volume surge',
      direction: 'BULLISH',
      confidence: 84,
    }

    const parsed = parseSearchQuery('zomato')
    expect(matchesSmartSearchAlert(alertZomato, parsed)).toBe(true)
  })

  it('matches scanner candidate using matchesSmartSearchCandidate', () => {
    const candidate = {
      symbol: 'INFY',
      name: 'Infosys Ltd',
      sector: 'IT & Software',
      archetype_label: 'Minervini SEPA',
      inflection_score: 82,
    }

    const queryIT = parseSearchQuery('IT')
    expect(matchesSmartSearchCandidate(candidate, queryIT)).toBe(true)

    const queryHigh = parseSearchQuery('score:>85')
    expect(matchesSmartSearchCandidate(candidate, queryHigh)).toBe(false)
  })
})

describe('SmartSearchBox UI Component', () => {
  const activeItems = [
    { symbol: 'RELIANCE', stage: 'IGNITED', contract_symbol: 'RELIANCE 2500 CE' },
    { symbol: 'HDFCBANK', stage: 'PRIMED', contract_symbol: 'HDFCBANK 1800 PE' },
  ]

  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    cleanup()
  })

  it('renders input with placeholder and opens popover on focus', () => {
    const handleChange = vi.fn()
    render(
      <SmartSearchBox
        value=""
        onChange={handleChange}
        placeholder="Search setups…"
        activeItems={activeItems}
      />
    )

    const input = screen.getByPlaceholderText('Search setups…')
    expect(input).toBeInTheDocument()

    // Focus opens popover
    fireEvent.focus(input)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getByText('Quick Directives')).toBeInTheDocument()
  })

  it('displays active radar symbols with setup counts and stage badges on zero-query', () => {
    render(
      <SmartSearchBox
        value=""
        onChange={vi.fn()}
        activeItems={activeItems}
      />
    )

    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    expect(screen.getByText('Active on Radar')).toBeInTheDocument()
    expect(screen.getByText('RELIANCE (1 setup)')).toBeInTheDocument()
    expect(screen.getByText('IGNITED')).toBeInTheDocument()
  })

  it('suggests matching universe tickers and company names when user types', () => {
    render(
      <SmartSearchBox
        value="infy"
        onChange={vi.fn()}
        activeItems={activeItems}
      />
    )

    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getByText(/Infosys Ltd/i)).toBeInTheDocument()
  })

  it('selects suggestion and invokes onChange with directive format on click', () => {
    const handleChange = vi.fn()
    render(
      <SmartSearchBox
        value="infy"
        onChange={handleChange}
        activeItems={activeItems}
      />
    )

    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    const infyOption = screen.getByText('INFY')
    fireEvent.click(infyOption)

    expect(handleChange).toHaveBeenCalledWith('sym:INFY')
  })

  it('clears query and refocuses input when clicking clear button', () => {
    const handleChange = vi.fn()
    render(
      <SmartSearchBox
        value="RELIANCE"
        onChange={handleChange}
      />
    )

    const clearBtn = screen.getByTitle(/clear search/i)
    fireEvent.click(clearBtn)

    expect(handleChange).toHaveBeenCalledWith('')
  })

  it('guarantees opaque background and elevated z-index on popover to prevent background bleeding', () => {
    const { container } = render(
      <SmartSearchBox
        value=""
        onChange={vi.fn()}
      />
    )

    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    const popover = screen.getByRole('listbox')
    expect(popover).toBeInTheDocument()
    expect(popover.className).toContain('z-[9999]')
    expect(popover.style.backgroundColor).toBe('var(--color-panel, #0d1320)')

    // Verify parent container elevates z-index
    const parent = container.firstChild
    expect(parent.className).toContain('z-[9999]')
  })
})

