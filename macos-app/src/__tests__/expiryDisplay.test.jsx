import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { formatExpiryDetails } from '../renderer/src/components/Views/alerts/alertHelpers'
import { AlertCompactRow } from '../renderer/src/components/Views/alerts/AlertCompactRow'
import { AlertTriageCard } from '../renderer/src/components/Views/alerts/AlertTriageCard'
import { LiveSpotsProvider } from '../renderer/src/components/Views/alerts/LiveSpotsContext'

describe('Options Expiry Clarity & Badging (Weekly ⚡W vs Monthly 📅M)', () => {
  describe('formatExpiryDetails Helper', () => {
    it('accurately resolves an explicit weekly index option contract', () => {
      const alert = {
        symbol: 'NIFTY',
        contract_symbol: 'NIFTY2691725000CE',
        expiry_date: '2026-09-17',
        expiry_type: 'WEEKLY',
      }
      const details = formatExpiryDetails(alert)
      expect(details).not.toBeNull()
      expect(details.isWeekly).toBe(true)
      expect(details.isMonthly).toBe(false)
      expect(details.shortBadge).toBe('⚡W')
      expect(details.tag).toBe('WEEKLY')
      expect(details.fullDisplay).toContain('⚡W')
      expect(details.fullDisplay).toContain('17-Sep')
    })

    it('infers weekly vs monthly for index contracts from tokenized contract symbols', () => {
      // 17-Sep-2026 is mid-month weekly (+7d stays in Sep)
      const weeklyAlert = {
        symbol: 'NIFTY',
        contract_symbol: 'NIFTY2691725000CE',
      }
      const weeklyDetails = formatExpiryDetails(weeklyAlert)
      expect(weeklyDetails.isWeekly).toBe(true)
      expect(weeklyDetails.shortBadge).toBe('⚡W')

      // 24-Sep-2026 is the final Thursday of September (+7d enters October)
      const monthlyAlert = {
        symbol: 'NIFTY',
        contract_symbol: 'NIFTY2692425000CE',
      }
      const monthlyDetails = formatExpiryDetails(monthlyAlert)
      expect(monthlyDetails.isMonthly).toBe(true)
      expect(monthlyDetails.shortBadge).toBe('📅M')
    })

    it('strictly enforces MONTHLY for single-stock equity options per SEBI market mandate', () => {
      const stockAlert = {
        symbol: 'RELIANCE',
        contract_symbol: 'RELIANCE26SEP2900CE',
        expiry_date: '2026-09-24',
      }
      const details = formatExpiryDetails(stockAlert)
      expect(details).not.toBeNull()
      expect(details.isWeekly).toBe(false)
      expect(details.isMonthly).toBe(true)
      expect(details.shortBadge).toBe('📅M')
      expect(details.tag).toBe('MONTHLY')
      expect(details.fullDisplay).toContain('📅M')
    })

    it('resolves nested expiry details inside actionable_plan.option_plan for spot setups', () => {
      const spotAlert = {
        symbol: 'NIFTY',
        alert_type: 'ASYMMETRIC_OPPORTUNITY',
        actionable_plan: {
          option_plan: {
            contract_symbol: 'NIFTY2691725000CE',
            expiry_date: '2026-09-17',
            expiry_type: 'WEEKLY',
            strike: 25000,
            option_type: 'CE',
          },
        },
      }
      const details = formatExpiryDetails(spotAlert)
      expect(details).not.toBeNull()
      expect(details.isWeekly).toBe(true)
      expect(details.shortBadge).toBe('⚡W')
      expect(details.fullDisplay).toContain('⚡W')
      expect(details.fullDisplay).toContain('17-Sep')
    })
  })

  describe('AlertCompactRow Component', () => {
    it('renders weekly ⚡W badge for weekly index option alert', () => {
      const alert = {
        alert_id: 'test-weekly-1',
        symbol: 'NIFTY',
        alert_type: 'GAMMA_BLAST',
        stage: 'IGNITED',
        direction: 'BULLISH',
        contract_symbol: 'NIFTY2691725000CE',
        strike: 25000,
        option_type: 'CE',
        expiry_date: '2026-09-17',
        expiry_type: 'WEEKLY',
        option_premium: 185.0,
        underlying_spot: 25050.0,
      }

      render(
        <LiveSpotsProvider>
          <AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />
        </LiveSpotsProvider>
      )

      expect(screen.getByText(/⚡W/)).toBeTruthy()
      expect(screen.getByText(/25,000/)).toBeTruthy()
      expect(screen.getByText('CE')).toBeTruthy()
    })

    it('renders monthly 📅M badge for single-stock monthly option alert', () => {
      const alert = {
        alert_id: 'test-monthly-1',
        symbol: 'RELIANCE',
        alert_type: 'OPTIONS_MOMENTUM',
        stage: 'IGNITED',
        direction: 'BULLISH',
        contract_symbol: 'RELIANCE26SEP2900CE',
        strike: 2900,
        option_type: 'CE',
        expiry_date: '2026-09-24',
        expiry_type: 'MONTHLY',
        option_premium: 62.5,
        underlying_spot: 2915.0,
      }

      render(
        <LiveSpotsProvider>
          <AlertCompactRow alert={alert} onExpand={() => {}} isExpanded={false} />
        </LiveSpotsProvider>
      )

      expect(screen.getByText(/📅M/)).toBeTruthy()
      expect(screen.getByText(/2,900/)).toBeTruthy()
      expect(screen.getByText('CE')).toBeTruthy()
    })
  })

  describe('AlertTriageCard Component', () => {
    it('renders weekly ⚡W badge alongside strike in split-view triage rail', () => {
      const alert = {
        alert_id: 'test-triage-weekly-1',
        symbol: 'NIFTY',
        alert_type: 'GAMMA_BLAST',
        stage: 'IGNITED',
        direction: 'BULLISH',
        contract_symbol: 'NIFTY2691725000CE',
        strike: 25000,
        option_type: 'CE',
        expiry_date: '2026-09-17',
        expiry_type: 'WEEKLY',
        option_premium: 185.0,
        underlying_spot: 25050.0,
      }

      render(
        <LiveSpotsProvider>
          <AlertTriageCard alert={alert} isSelected={false} onSelect={() => {}} />
        </LiveSpotsProvider>
      )

      expect(screen.getByText(/⚡W/)).toBeTruthy()
      expect(screen.getByText(/₹25,000/)).toBeTruthy()
      expect(screen.getByText('CE')).toBeTruthy()
    })

    it('renders monthly 📅M badge for monthly index or stock options in triage rail', () => {
      const alert = {
        alert_id: 'test-triage-monthly-1',
        symbol: 'NIFTY',
        alert_type: 'OPTIONS_MOMENTUM',
        stage: 'IGNITED',
        direction: 'BULLISH',
        contract_symbol: 'NIFTY2692425000CE',
        strike: 25000,
        option_type: 'CE',
        expiry_date: '2026-09-24',
        expiry_type: 'MONTHLY',
        option_premium: 240.0,
        underlying_spot: 25050.0,
      }

      render(
        <LiveSpotsProvider>
          <AlertTriageCard alert={alert} isSelected={false} onSelect={() => {}} />
        </LiveSpotsProvider>
      )

      expect(screen.getByText(/📅M/)).toBeTruthy()
      expect(screen.getByText(/₹25,000/)).toBeTruthy()
      expect(screen.getByText('CE')).toBeTruthy()
    })
  })
})
