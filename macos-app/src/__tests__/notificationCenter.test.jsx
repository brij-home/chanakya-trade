import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useNotificationStore, normalizeNotification } from '../renderer/src/store/notificationStore'
import { useToastStore } from '../renderer/src/hooks/useToast'
import NotificationBell from '../renderer/src/components/Notifications/NotificationBell'
import NotificationDropdown from '../renderer/src/components/Notifications/NotificationDropdown'

describe('Notification Center & Store Invariants', () => {
  beforeEach(() => {
    localStorage.clear()
    useNotificationStore.getState().clearAll()
    useNotificationStore.getState().setDropdownOpen(false)
    useToastStore.getState().clearAll()
  })

  it('normalizes incoming alert payloads correctly', () => {
    const rawAlert = {
      alert_id: 'test-gamma-1',
      symbol: 'NSE:NIFTY',
      strike: 24500,
      option_type: 'CE',
      alert_type: 'GAMMA_BLAST',
      stage: 'IGNITED',
      direction: 'BULLISH',
      underlying_spot: 24580,
      option_premium: 142.5,
      stop_loss: 110,
      target_level: 210,
      confidence: 88,
      headline: 'NIFTY 24500 CE Gamma Blast',
      summary: 'Call gamma squeeze ignited',
      environment: 'LIVE',
    }

    const item = normalizeNotification(rawAlert)
    expect(item.id).toBe('test-gamma-1')
    expect(item.symbol).toBe('NIFTY')
    expect(item.strike).toBe(24500)
    expect(item.option_type).toBe('CE')
    expect(item.direction).toBe('BULLISH')
    expect(item.stage).toBe('IGNITED')
    expect(item.spot).toBe(24580)
    expect(item.premium).toBe(142.5)
    expect(item.sl).toBe(110)
    expect(item.t1).toBe(210)
    expect(item.confidence).toBe(88)
    expect(item.read).toBe(false)
  })

  it('adds notification and increments unread count', () => {
    const store = useNotificationStore.getState()
    expect(store.unreadCount).toBe(0)
    expect(store.notifications.length).toBe(0)

    store.addNotification({
      id: 'alert-1',
      symbol: 'RELIANCE',
      direction: 'BEARISH',
      alert_type: 'SMC_SWEEP',
      stage: 'ACTIVE',
      summary: 'Bearish liquidity sweep',
      ltp: 2840,
    })

    const after = useNotificationStore.getState()
    expect(after.notifications.length).toBe(1)
    expect(after.unreadCount).toBe(1)
    expect(after.notifications[0].symbol).toBe('RELIANCE')
    expect(after.notifications[0].read).toBe(false)
  })

  it('marks single notification as read and all as read', () => {
    const store = useNotificationStore.getState()
    store.addNotification({ id: 'a1', symbol: 'NIFTY' })
    store.addNotification({ id: 'a2', symbol: 'BANKNIFTY' })

    expect(useNotificationStore.getState().unreadCount).toBe(2)

    store.markAsRead('a1')
    expect(useNotificationStore.getState().unreadCount).toBe(1)
    expect(useNotificationStore.getState().notifications.find((n) => n.id === 'a1').read).toBe(true)

    store.markAllAsRead()
    expect(useNotificationStore.getState().unreadCount).toBe(0)
    expect(useNotificationStore.getState().notifications.every((n) => n.read)).toBe(true)
  })

  it('removes a notification and clears all', () => {
    const store = useNotificationStore.getState()
    store.addNotification({ id: 'a1', symbol: 'NIFTY' })
    store.addNotification({ id: 'a2', symbol: 'BANKNIFTY' })

    store.removeNotification('a1')
    expect(useNotificationStore.getState().notifications.length).toBe(1)
    expect(useNotificationStore.getState().notifications[0].id).toBe('a2')

    store.clearAll()
    expect(useNotificationStore.getState().notifications.length).toBe(0)
    expect(useNotificationStore.getState().unreadCount).toBe(0)
  })
})

describe('Toast Graceful Eviction Queue', () => {
  beforeEach(() => {
    useToastStore.getState().clearAll()
  })

  it('gracefully evicts the oldest toast when queue limit is reached', () => {
    const store = useToastStore.getState()

    // Add 3 toasts
    store.addToast({ title: 'Alert 1' })
    store.addToast({ title: 'Alert 2' })
    store.addToast({ title: 'Alert 3' })

    let state = useToastStore.getState()
    expect(state.toasts.length).toBe(3)
    expect(state.toasts.every((t) => !t.exiting)).toBe(true)

    // Add 4th toast -> oldest toast should be marked exiting: true
    store.addToast({ title: 'Alert 4' })
    state = useToastStore.getState()

    // Oldest toast (Alert 1) should now have exiting: true
    const alert1 = state.toasts.find((t) => t.title === 'Alert 1')
    expect(alert1.exiting).toBe(true)

    // The new toast is present and active
    const alert4 = state.toasts.find((t) => t.title === 'Alert 4')
    expect(alert4.exiting).toBe(false)
  })
})

describe('Notification UI Components', () => {
  beforeEach(() => {
    localStorage.clear()
    useNotificationStore.getState().clearAll()
    useNotificationStore.getState().setDropdownOpen(false)
  })

  it('renders NotificationBell with unread badge when unread > 0', () => {
    useNotificationStore.getState().addNotification({
      id: 'ui-test-1',
      symbol: 'TCS',
      direction: 'BULLISH',
    })

    render(<NotificationBell />)
    expect(screen.getByText('🔔')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('toggles NotificationDropdown and triggers 1-Click trade', () => {
    const handleTrade = vi.fn()
    useNotificationStore.getState().addNotification({
      id: 'trade-test-1',
      symbol: 'INFY',
      contract_symbol: 'INFY',
      direction: 'BULLISH',
      entry: 1850,
      sl: 1820,
      t1: 1910,
    })

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        onOpenOrderTicket={handleTrade}
      />
    )

    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getByText('⚡ Trade')).toBeInTheDocument()

    fireEvent.click(screen.getByText('⚡ Trade'))
    expect(handleTrade).toHaveBeenCalledTimes(1)
    expect(handleTrade).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'INFY',
        price: 1850,
        stopLoss: 1820,
        target: 1910,
      })
    )
  })
})
