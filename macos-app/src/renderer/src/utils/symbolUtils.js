/**
 * symbolUtils.js — Canonical symbol normalization utilities.
 *
 * Single source of truth for symbol/exchange resolution.
 * Previously duplicated across: TerminalView.jsx, chatStore.js, universeData.js,
 * and many card components. Always use these utilities — never write local
 * `if (symbol === '...')` guards in individual components.
 */

import { getSymbolExchange as _getSymbolExchange } from '../data/universeData'

/**
 * Strip exchange prefixes, parenthetical suffixes, and normalise spacing.
 * Returns an uppercase, clean symbol string.
 *
 * Examples:
 *   cleanSymbol('NSE:NIFTY 50') → 'NIFTY'
 *   cleanSymbol('BANK NIFTY (Index)') → 'BANKNIFTY'
 *   cleanSymbol('MCX:GOLD') → 'GOLD'
 */
export function cleanSymbol(s) {
  if (!s) return ''
  let str = String(s)
    .replace(/^(NSE:|BSE:|MCX:|CDS:|CRYPTO:|BINANCE:|FX:|FOREX:)/i, '')
    .replace(/\s*\(.*?\)/g, '')
    .trim()
    .toUpperCase()
  // Canonical alias normalisation
  if (str.includes('BANK') && str.includes('NIFTY')) return 'BANKNIFTY'
  if (str.includes('FIN') && str.includes('NIFTY')) return 'FINNIFTY'
  if (str.includes('MID') && str.includes('NIFTY')) return 'MIDCPNIFTY'
  if (str.includes('VIX')) return 'INDIA VIX'
  if (str === 'NIFTY 50' || str === 'NIFTY50') return 'NIFTY'
  return str.replace(/\s+/g, '')
}

/**
 * Resolve the canonical exchange for a symbol.
 * Delegates to universeData.js which contains the full multi-asset taxonomy.
 */
export function resolveExchange(symbol) {
  if (!symbol) return 'NSE'
  return _getSymbolExchange(cleanSymbol(symbol))
}

/**
 * Format a symbol for display in the UI (preserves spaces like "INDIA VIX").
 */
export function formatSymbolDisplay(symbol) {
  if (!symbol) return ''
  const clean = cleanSymbol(symbol)
  // Restore readable forms
  if (clean === 'INDIAVIX') return 'INDIA VIX'
  if (clean === 'BANKNIFTY') return 'BANK NIFTY'
  if (clean === 'FINNIFTY') return 'FIN NIFTY'
  if (clean === 'MIDCPNIFTY') return 'MIDCAP NIFTY'
  return clean
}

/**
 * Check whether two symbols refer to the same instrument.
 * Exchange-prefix and spacing agnostic.
 */
export function symbolsMatch(a, b) {
  return cleanSymbol(a) === cleanSymbol(b)
}

/**
 * Parse a user-typed string like "analyze RELIANCE" or "q GOLD" into parts.
 * Returns { cmd, symbol, rest } or null if not a command-like string.
 */
export function parseCommandSymbol(text) {
  if (!text) return null
  const parts = text.trim().split(/\s+/)
  if (parts.length < 2) return null
  return {
    cmd: parts[0].toLowerCase(),
    symbol: cleanSymbol(parts[1]),
    rest: parts.slice(2).join(' '),
  }
}
