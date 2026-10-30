import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import MultiSelectDropdown from '../renderer/src/components/Common/MultiSelectDropdown'

describe('MultiSelectDropdown Component', () => {
  const options = [
    { value: 'GAMMA_BLAST', label: 'Gamma Blast', count: 4, icon: '⚡' },
    { value: 'SQUEEZE_BREAKOUT', label: 'Squeeze Breakout', count: 2, icon: '🚀' },
    { value: 'MULTIBAGGER', label: 'Multibagger Alpha', count: 5, icon: '🌟' },
    { value: 'TURTLE_SOUP', label: 'Turtle Soup Sweep', count: 1, icon: '🐢' },
    { value: 'SMC_SWEEP', label: 'SMC Liquidity Sweep', count: 3, icon: '🌊' },
    { value: 'ORDER_BOOK_TITAN', label: 'Order-Book Titan', count: 7, icon: '🏗️' },
  ]

  afterEach(() => {
    cleanup()
  })

  it('renders default all state with allLabel and border styling', () => {
    render(
      <MultiSelectDropdown
        title="Category"
        allLabel="All Categories / Setups"
        options={options}
        selected={new Set()}
        onChange={vi.fn()}
      />
    )

    expect(screen.getByText('All Categories / Setups')).toBeInTheDocument()
  })

  it('opens floating popover on trigger click and displays search box when >= 6 options', () => {
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set()}
        onChange={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /all category/i })
    fireEvent.click(trigger)

    expect(screen.getByPlaceholderText(/search category…/i)).toBeInTheDocument()
    expect(screen.getByText('Gamma Blast')).toBeInTheDocument()
    expect(screen.getByText('Squeeze Breakout')).toBeInTheDocument()
  })

  it('filters option list in real-time as user types in search box', () => {
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set()}
        onChange={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /all category/i }))
    const searchInput = screen.getByPlaceholderText(/search category…/i)

    fireEvent.change(searchInput, { target: { value: 'turtle' } })
    expect(screen.getByText('Turtle Soup Sweep')).toBeInTheDocument()
    expect(screen.queryByText('Gamma Blast')).not.toBeInTheDocument()
  })

  it('solos an option when clicking the "only" button on row hover', () => {
    const handleChange = vi.fn()
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set(['GAMMA_BLAST', 'SQUEEZE_BREAKOUT'])}
        onChange={handleChange}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /category/i }))

    // Click "only" for Turtle Soup
    const onlyBtns = screen.getAllByRole('button', { name: /^only$/i })
    const turtleOnlyBtn = onlyBtns.find((b) => b.getAttribute('title')?.includes('Turtle Soup'))
    expect(turtleOnlyBtn).toBeDefined()

    fireEvent.click(turtleOnlyBtn)
    expect(handleChange).toHaveBeenCalledWith(new Set(['TURTLE_SOUP']))
  })

  it('toggles selection when row is clicked and resets to ALL when last selected is unchecked', () => {
    const handleChange = vi.fn()
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set(['GAMMA_BLAST'])}
        onChange={handleChange}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /gamma blast/i }))
    // Target the option row inside the dropdown list (not the trigger button)
    const gammaElements = screen.getAllByText('Gamma Blast')
    const gammaRow = gammaElements[1].closest('div[class*="cursor-pointer"]')
    fireEvent.click(gammaRow)

    // Deselecting the only selected option resets back to ALL (empty set)
    expect(handleChange).toHaveBeenCalledWith(new Set())
  })

  it('provides quick reset ✕ icon on trigger when filtered', () => {
    const handleChange = vi.fn()
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set(['GAMMA_BLAST', 'SQUEEZE_BREAKOUT'])}
        onChange={handleChange}
      />
    )

    const resetBtn = screen.getByTitle('Reset filter to All')
    expect(resetBtn).toBeInTheDocument()

    fireEvent.click(resetBtn)
    expect(handleChange).toHaveBeenCalledWith(new Set())
  })

  it('synchronizes hidden select for test compatibility and automated change events', () => {
    const handleChange = vi.fn()
    render(
      <MultiSelectDropdown
        title="Category"
        hiddenSelectTitle="Filter by setup / strategy category"
        options={options}
        selected={new Set()}
        onChange={handleChange}
      />
    )

    const hiddenSelect = screen.getByTitle('Filter by setup / strategy category')
    expect(hiddenSelect).toBeInTheDocument()

    fireEvent.change(hiddenSelect, { target: { value: 'GAMMA_BLAST' } })
    expect(handleChange).toHaveBeenCalledWith(new Set(['GAMMA_BLAST']))
  })

  it('closes popover when Escape key is pressed', () => {
    render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set()}
        onChange={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /all category/i })
    fireEvent.click(trigger)
    expect(screen.getByPlaceholderText(/search category…/i)).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByPlaceholderText(/search category…/i)).not.toBeInTheDocument()
  })

  it('guarantees opaque background and elevated z-index on popover to prevent background bleeding', () => {
    const { container } = render(
      <MultiSelectDropdown
        title="Category"
        options={options}
        selected={new Set()}
        onChange={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /all category/i })
    fireEvent.click(trigger)

    const popover = screen.getByRole('listbox')
    expect(popover).toBeInTheDocument()
    expect(popover.className).toContain('z-[9999]')
    expect(popover.style.backgroundColor).toBe('var(--color-panel, #0d1320)')

    // Verify parent container elevates z-index
    const parent = container.firstChild
    expect(parent.className).toContain('z-[9999]')
  })
})

