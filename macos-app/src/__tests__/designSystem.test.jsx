import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Button from '../renderer/src/components/Common/Button'
import Dialog from '../renderer/src/components/Common/Dialog'
import Metric from '../renderer/src/components/Common/Metric'
import Badge from '../renderer/src/components/Common/Badge'

describe('P2-A Accessible Design System Component Gates', () => {
  describe('Button Component', () => {
    it('renders with accessible role, text, and responds to click', () => {
      const handleClick = vi.fn()
      render(<Button onClick={handleClick}>Execute Trade</Button>)

      const btn = screen.getByRole('button', { name: /Execute Trade/i })
      expect(btn).toBeTruthy()
      expect(btn.getAttribute('aria-disabled')).toBe('false')

      fireEvent.click(btn)
      expect(handleClick).toHaveBeenCalledTimes(1)
    })

    it('displays loading spinner and sets aria-busy when isLoading is true', () => {
      render(<Button isLoading={true}>Submit Order</Button>)

      const btn = screen.getByRole('button')
      expect(btn.getAttribute('aria-busy')).toBe('true')
      expect(btn.getAttribute('disabled')).toBeDefined()
      expect(screen.getByText(/Processing.../i)).toBeTruthy()
    })

    it('prevents click when disabled', () => {
      const handleClick = vi.fn()
      render(
        <Button disabled={true} onClick={handleClick}>
          Disabled Action
        </Button>
      )

      const btn = screen.getByRole('button', { name: /Disabled Action/i })
      expect(btn.hasAttribute('disabled')).toBe(true)

      fireEvent.click(btn)
      expect(handleClick).not.toHaveBeenCalled()
    })
  })

  describe('Dialog Component', () => {
    it('does not render when isOpen is false', () => {
      render(
        <Dialog isOpen={false} title="Test Modal">
          Modal Content
        </Dialog>
      )
      expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('renders accessible dialog with title and dismisses on Escape key', () => {
      const handleClose = vi.fn()
      render(
        <Dialog isOpen={true} onClose={handleClose} title="Order Confirmation">
          <div>Order confirmation content</div>
        </Dialog>
      )

      const dialog = screen.getByRole('dialog')
      expect(dialog).toBeTruthy()
      expect(dialog.getAttribute('aria-modal')).toBe('true')
      expect(screen.getByRole('heading', { name: /Order Confirmation/i })).toBeTruthy()

      // Trigger Escape key
      fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' })
      expect(handleClose).toHaveBeenCalledTimes(1)
    })

    it('calls onClose when close button is clicked', () => {
      const handleClose = vi.fn()
      render(
        <Dialog isOpen={true} onClose={handleClose} title="Settings">
          <div>Settings body</div>
        </Dialog>
      )

      const closeBtn = screen.getByRole('button', { name: /Close dialog/i })
      expect(closeBtn).toBeTruthy()
      fireEvent.click(closeBtn)
      expect(handleClose).toHaveBeenCalledTimes(1)
    })
  })

  describe('Metric Component', () => {
    it('renders metric label, formatted value, and change badge', () => {
      render(
        <Metric
          label="NIFTY 50 Spot"
          value="24,520.40"
          changePct={0.65}
          unit="pts"
          subtext="NSE IFSC implied gap"
        />
      )

      expect(screen.getByText(/NIFTY 50 Spot/i)).toBeTruthy()
      expect(screen.getByText(/24,520.40/i)).toBeTruthy()
      expect(screen.getByText(/\+0.65%/i)).toBeTruthy()
      expect(screen.getByText(/NSE IFSC implied gap/i)).toBeTruthy()
    })

    it('renders "Unavailable" fallback gracefully when value is null', () => {
      render(<Metric label="FII Net Inflow" value={null} />)

      expect(screen.getByText(/FII Net Inflow/i)).toBeTruthy()
      expect(screen.getByText(/Unavailable/i)).toBeTruthy()
    })
  })

  describe('Badge Component ("Define Once and Reuse")', () => {
    it('renders text with default neutral styling', () => {
      render(<Badge>Default Tag</Badge>)
      const el = screen.getByText(/Default Tag/i)
      expect(el).toBeTruthy()
      expect(el.className).toContain('bg-panel')
    })

    it('renders semantic jewel-tone variants correctly', () => {
      const { rerender } = render(<Badge variant="emerald">Bullish</Badge>)
      expect(screen.getByText(/Bullish/i).className).toContain('text-emerald-700')

      rerender(<Badge variant="rose">Circuit Locked</Badge>)
      expect(screen.getByText(/Circuit Locked/i).className).toContain('text-rose-700')

      rerender(<Badge variant="gold">High Conviction</Badge>)
      expect(screen.getByText(/High Conviction/i).className).toContain('text-amber-600')

      rerender(<Badge variant="cyan">Coiling</Badge>)
      expect(screen.getByText(/Coiling/i).className).toContain('text-cyan-700')
    })

    it('renders with optional icon and size classes', () => {
      render(
        <Badge variant="emerald" size="md" icon={<span data-testid="badge-icon">🚀</span>}>
          Multibagger
        </Badge>
      )
      expect(screen.getByTestId('badge-icon')).toBeTruthy()
      expect(screen.getByText(/Multibagger/i).className).toContain('text-xs')
    })
  })
})
