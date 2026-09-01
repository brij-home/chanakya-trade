import { describe, it, expect } from 'vitest'
import { formatINR, formatINRFull, formatPct, formatVol } from '../renderer/src/utils/formatINR'

describe('formatINR utility tests', () => {
  it('formats Crores correctly', () => {
    expect(formatINR(12500000)).toBe('₹1.25Cr')
    expect(formatINR(50000000)).toBe('₹5.00Cr')
    expect(formatINR(-25000000)).toBe('-₹2.50Cr')
  })

  it('formats Lakhs correctly', () => {
    expect(formatINR(450000)).toBe('₹4.50L')
    expect(formatINR(100000)).toBe('₹1.00L')
    expect(formatINR(-350000)).toBe('-₹3.50L')
  })

  it('formats Thousands (K) correctly', () => {
    expect(formatINR(8200)).toBe('₹8.20K')
    expect(formatINR(1000)).toBe('₹1.00K')
  })

  it('formats smaller numbers with rupee symbol', () => {
    expect(formatINR(450.5)).toBe('₹450.50')
  })

  it('handles null, undefined, or NaN gracefully', () => {
    expect(formatINR(null)).toBe('—')
    expect(formatINR(undefined)).toBe('—')
    expect(formatINR('invalid')).toBe('—')
  })

  it('formatINRFull produces en-IN localized currency strings', () => {
    const formatted = formatINRFull(123456.78)
    expect(formatted).toContain('₹')
    expect(formatted).toContain('1,23,456.78')
  })

  it('formatPct returns structured text and polarity', () => {
    expect(formatPct(4.5)).toEqual({ text: '+4.50%', positive: true })
    expect(formatPct(-2.15)).toEqual({ text: '-2.15%', positive: false })
    expect(formatPct(null)).toEqual({ text: '—', positive: null })
  })

  it('formatVol formats volumes correctly into Cr, L, K', () => {
    expect(formatVol(25000000)).toBe('2.5Cr')
    expect(formatVol(150000)).toBe('1.5L')
    expect(formatVol(8000)).toBe('8.0K')
    expect(formatVol(500)).toBe('500')
    expect(formatVol(null)).toBe('—')
  })
})
