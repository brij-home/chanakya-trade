/**
 * formatINR — Indian Financial Number Formatting Utilities
 * Formats numbers into ₹Cr / ₹L / ₹K abbreviations for institutional density.
 */

/**
 * Format a number with Indian abbreviations (Cr / L / K).
 * @param {number} value - The amount in rupees
 * @param {number} decimals - Decimal places (default 2)
 * @returns {string} e.g. "₹1.25Cr", "₹45.3L", "₹8.2K"
 */
export function formatINR(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(Number(value))) return '—'
  const n = Number(value)
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''

  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(decimals)}Cr`
  if (abs >= 1_00_000)    return `${sign}₹${(abs / 1_00_000).toFixed(decimals)}L`
  if (abs >= 1_000)       return `${sign}₹${(abs / 1_000).toFixed(decimals)}K`
  return `${sign}₹${abs.toFixed(decimals)}`
}

/**
 * Format with full en-IN locale (₹1,23,456.78 style).
 */
export function formatINRFull(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

/**
 * Format a percentage change with +/- sign.
 * @returns {{ text: string, positive: boolean|null }}
 */
export function formatPct(pct) {
  if (pct === null || pct === undefined || isNaN(Number(pct))) {
    return { text: '—', positive: null }
  }
  const n = Number(pct)
  return { text: `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`, positive: n >= 0 }
}

/**
 * Format volume (shares) to abbreviated form.
 */
export function formatVol(vol) {
  if (vol === null || vol === undefined || isNaN(Number(vol))) return '—'
  const n = Number(vol)
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(1)}Cr`
  if (n >= 1_00_000)    return `${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000)       return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
