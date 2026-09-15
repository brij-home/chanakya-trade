import React, { useEffect } from 'react'
import { useNotificationStore } from '../../store/notificationStore'
import { useAPI } from '../../hooks/useAPI'
import NotificationDropdown from './NotificationDropdown'

/**
 * NotificationBell — institutional top-navigation bell icon with unread count badge
 * and dropdown popover for inspecting all recent & historical alerts in a glance.
 *
 * Alert fetching is fully delegated to notificationStore.startPolling() so there is
 * exactly ONE polling loop across the entire app (NotificationBell + AlertsView used
 * to each poll independently, creating a connection stampede).
 */
export default function NotificationBell({ onOpenOrderTicket }) {
  const isDropdownOpen = useNotificationStore((s) => s.isDropdownOpen)
  const toggleDropdown = useNotificationStore((s) => s.toggleDropdown)
  const setDropdownOpen = useNotificationStore((s) => s.setDropdownOpen)
  const unreadCount = useNotificationStore((s) => s.unreadCount)
  const isLoading = useNotificationStore((s) => s.isLoading)
  const startPolling = useNotificationStore((s) => s.startPolling)
  const fetchAlerts = useNotificationStore((s) => s.fetchAlerts)
  const stopPolling = useNotificationStore((s) => s.stopPolling)

  const { call } = useAPI()

  // Start the singleton polling loop on mount; stop on unmount.
  // startPolling is idempotent — safe even if AlertsView calls it too.
  useEffect(() => {
    startPolling(call)
    return () => stopPolling()
  }, [call, startPolling, stopPolling])

  const handleToggle = () => {
    if (!isDropdownOpen) {
      // On-demand refresh when user opens the dropdown
      fetchAlerts(call)
    }
    toggleDropdown()
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleToggle}
        className={`relative flex items-center justify-center w-8 h-8 rounded-lg text-sm transition-all cursor-pointer ${
          isDropdownOpen
            ? 'bg-elevated text-text shadow-sm'
            : 'text-muted hover:text-text hover:bg-elevated'
        }`}
        style={{
          border: '1px solid var(--color-border)',
        }}
        title={`Notifications & Alerts (${unreadCount} unread)`}
        aria-label="Toggle notifications center"
        aria-expanded={isDropdownOpen}
      >
        {/* Bell Icon */}
        <span className="select-none text-base">🔔</span>

        {/* Unread badge */}
        {unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-black font-mono text-white flex items-center justify-center shadow-md animate-pulse"
            style={{
              background: 'var(--color-rose)',
              boxShadow: '0 0 8px rgba(255, 79, 123, 0.6)',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Menu */}
      <NotificationDropdown
        isOpen={isDropdownOpen}
        onClose={() => setDropdownOpen(false)}
        onOpenOrderTicket={onOpenOrderTicket}
        onRefresh={() => fetchAlerts(call)}
        isLoading={isLoading}
      />
    </div>
  )
}
