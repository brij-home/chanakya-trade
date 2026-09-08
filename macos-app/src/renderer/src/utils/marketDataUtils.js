/**
 * marketDataUtils.js — Unified market data formatting and provenance helpers.
 *
 * Ensures consistent handling of real-time prices, percentage changes,
 * and data state badges across all trading terminal screens and cards.
 * Never fabricates numbers: returns '—' when data is unavailable.
 */

import { formatINR } from './formatINR'

/**
 * Formats a live price with appropriate currency symbol and decimals.
 * Returns '—' if price is null, undefined, NaN, or <= 0 (unless zeroAllowed is true).
 *
 * @param {number|string|null|undefined} price
 * @param {object|string} [options={}] - Options object or unit string (e.g. '₹', '$', 'pts')
 * @param {number} [options.decimals=2]
 * @param {string} [options.unit='₹'] - '₹', '$', 'pts', '%', etc.
 * @param {boolean} [options.zeroAllowed=false]
 * @param {boolean} [options.compact=false] - Use formatINR (e.g. ₹1.25Cr)
 * @returns {string} e.g. "₹24,850.50", "$82,410.00", "12.45 pts", or "—"
 */
export function formatLivePrice(price, options = {}) {
  const opts = typeof options === 'string' ? { unit: options } : options
  const { decimals = 2, unit = '₹', zeroAllowed = false, compact = false } = opts
  if (price === null || price === undefined || price === '') return '—'
  const num = Number(price)
  if (isNaN(num)) return '—'
  if (!zeroAllowed && num <= 0) return '—'

  if (compact) {
    return formatINR(num, decimals)
  }

  const locale = unit === '$' ? 'en-US' : 'en-IN'
  const formatted = num.toLocaleString(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })

  if (unit === '₹') return `₹${formatted}`
  if (unit === '$') return `$${formatted}`
  if (unit === 'pts') return `${formatted} pts`
  if (unit && unit.startsWith('₹/')) return `₹${formatted} ${unit.slice(1)}`
  if (unit) return `${formatted} ${unit}`
  return formatted
}

/**
 * Formats a price change with sign, percentage, and direction color classes.
 *
 * @param {number|string|null|undefined} change
 * @param {number|string|null|undefined} changePct
 * @param {number|object} [optionsOrDecimals=2]
 * @returns {{ text: string, changeText: string, pctText: string, direction: 'up'|'down'|'flat'|'none', colorClass: string, isPositive: boolean }}
 */
export function formatLiveChange(change, changePct, optionsOrDecimals = 2) {
  const decimals = typeof optionsOrDecimals === 'number'
    ? Math.min(10, Math.max(0, Math.floor(optionsOrDecimals)))
    : (optionsOrDecimals?.decimals ?? 2)

  const hasChange = change !== null && change !== undefined && !isNaN(Number(change))
  const hasPct = changePct !== null && changePct !== undefined && !isNaN(Number(changePct))

  if (!hasChange && !hasPct) {
    return {
      text: '—',
      changeText: '—',
      pctText: '—',
      direction: 'none',
      colorClass: 'text-muted',
      isPositive: false,
    }
  }

  const cNum = hasChange ? Number(change) : 0
  const pNum = hasPct ? Number(changePct) : (cNum !== 0 ? cNum : 0)
  const isUp = pNum > 0
  const isDown = pNum < 0
  const direction = isUp ? 'up' : isDown ? 'down' : 'flat'

  const sign = isUp ? '+' : ''
  const cStr = hasChange ? `${sign}${cNum.toFixed(decimals)}` : ''
  const pStr = hasPct ? `${sign}${pNum.toFixed(decimals)}%` : ''

  const text = cStr && pStr ? `${cStr} (${pStr})` : (pStr || cStr || '—')
  const colorClass = isUp
    ? 'text-emerald-500 dark:text-emerald-400'
    : isDown
    ? 'text-rose-500 dark:text-rose-400'
    : 'text-muted'

  return {
    text,
    changeText: cStr || '—',
    pctText: pStr || '—',
    direction,
    colorClass,
    isPositive: isUp,
  }
}

/**
 * Classifies institutional data provenance:
 * - LIVE: Authenticated Broker API (Primary)
 * - DELAYED: Public Fallback Feed (Secondary, only when trading account missing)
 * - UNAVAILABLE: Neither source has data
 *
 * @param {string|object|null} dataStateOrObj
 * @param {string|null} [provider]
 * @param {boolean} [isRealtime=false]
 * @returns {{ label: string, badgeText: string, status: 'live'|'delayed'|'unavailable', color: string, bg: string, border: string, isLive: boolean, isFallback: boolean }}
 */
export function classifyDataSource(dataStateOrObj, provider, isRealtime = false) {
  let ds = ''
  let prov = ''
  let real = isRealtime

  if (typeof dataStateOrObj === 'object' && dataStateOrObj !== null) {
    ds = dataStateOrObj.dataState || dataStateOrObj.source || dataStateOrObj.status || ''
    prov = dataStateOrObj.provider || ''
    real = Boolean(dataStateOrObj.isRealtime || dataStateOrObj.isLive)
  } else {
    ds = dataStateOrObj || ''
    prov = provider || ''
  }

  const dsUpper = String(ds).toUpperCase()
  const provLower = String(prov).toLowerCase()

  if (real || dsUpper === 'LIVE' || dsUpper === 'STREAM') {
    const name = provLower && provLower !== 'none' ? prov.toUpperCase() : 'BROKER'
    const label = `● LIVE (${name})`
    return {
      label,
      badgeText: label,
      status: 'live',
      color: 'var(--color-emerald)',
      bg: 'rgba(0, 214, 143, 0.12)',
      border: 'rgba(0, 214, 143, 0.35)',
      isLive: true,
      isFallback: false,
    }
  }

  if (dsUpper === 'DELAYED' || dsUpper === 'FALLBACK' || dsUpper === 'EOD' || provLower === 'yfinance' || provLower.includes('scraper')) {
    const name = prov ? prov.toUpperCase() : 'FALLBACK'
    const label = `⏱️ DELAYED (${name})`
    return {
      label,
      badgeText: label,
      status: 'delayed',
      color: 'var(--color-gold)',
      bg: 'rgba(245, 166, 35, 0.12)',
      border: 'rgba(245, 166, 35, 0.35)',
      isLive: false,
      isFallback: true,
    }
  }

  return {
    label: '○ UNAVAILABLE',
    badgeText: '○ UNAVAILABLE',
    status: 'unavailable',
    color: 'var(--color-muted)',
    bg: 'rgba(120, 120, 120, 0.12)',
    border: 'rgba(120, 120, 120, 0.35)',
    isLive: false,
    isFallback: false,
  }
}

/**
 * Returns the metric formatted with suffix or '—' if unavailable.
 *
 * @param {number|string|null|undefined} val
 * @param {string} [suffix='']
 * @param {string} [fallback='—']
 * @returns {string}
 */
export function formatMetricOrUnavailable(val, suffix = '', fallback = '—') {
  if (val === null || val === undefined || val === '') return fallback
  const num = Number(val)
  if (isNaN(num)) return `${val}${suffix}`
  return `${val}${suffix}`
}
