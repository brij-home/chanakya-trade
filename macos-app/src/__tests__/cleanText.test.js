import { describe, it, expect } from 'vitest'
import { cleanMojibake, sanitizeCouncilMeta, sanitizeData } from '../renderer/src/utils/cleanText'

describe('cleanText utility tests', () => {
  it('repairs corrupted emoji sequences back to authentic UTF-8 symbols', () => {
    // Mojibake: \u00f0\u0178\u0161\u20ac is ðŸš€ (rocket)
    const rawBreakout = '\u00f0\u0178\u0161\u20ac Breakout Council'
    expect(cleanMojibake(rawBreakout)).toBe('🚀 Breakout Council')

    // Mojibake: \u00f0\u0178\u2019\u017d is ðŸ’Ž (gem / multibagger)
    const rawKedia = '\u00f0\u0178\u2019\u017d Multibagger Hub'
    expect(cleanMojibake(rawKedia)).toBe('💎 Multibagger Hub')

    // Mojibake: \u00e2\u0161\u00a1 is âš¡ (lightning)
    const rawOneil = '\u00e2\u0161\u00a1 High Momentum'
    expect(cleanMojibake(rawOneil)).toBe('⚡ High Momentum')

    // Mojibake: \u00e2\u20ac\u201d is â€” (em dash)
    const rawDash = 'Phase 1 \u00e2\u20ac\u201d 7 Analysts'
    expect(cleanMojibake(rawDash)).toBe('Phase 1 — 7 Analysts')
  })

  it('repairs Greek letters and math symbols (e.g. Jim Simons Z-Score Ïƒ -> σ)', () => {
    // Mojibake: \u00cf\u0192 is Ïƒ (sigma / standard deviation)
    const rawSimonsZScore = 'Z-Score: -3.96\u00cf\u0192 | EV: +2.1R'
    expect(cleanMojibake(rawSimonsZScore)).toBe('Z-Score: -3.96σ | EV: +2.1R')

    const rawSimonsThesis = 'Jim Simons quant statistical edge on NIFTY: 20-day price mean reversion Z-score is -3.96\u00cf\u0192 against the regression channel.'
    expect(cleanMojibake(rawSimonsThesis)).toBe('Jim Simons quant statistical edge on NIFTY: 20-day price mean reversion Z-score is -3.96σ against the regression channel.')

    // Arrows and bullets
    const rawArrow = 'Quote \u00e2\u2020\u2019 Live price'
    expect(cleanMojibake(rawArrow)).toBe('Quote → Live price')

    const rawBullet = '\u00e2\u20ac\u00a2 Minervini: PASS (75%)'
    expect(cleanMojibake(rawBullet)).toBe('• Minervini: PASS (75%)')
  })

  it('handles clean strings without altering them', () => {
    expect(cleanMojibake('🚀 Breakout Council')).toBe('🚀 Breakout Council')
    expect(cleanMojibake('Z-Score: -3.96σ | EV: +2.1R')).toBe('Z-Score: -3.96σ | EV: +2.1R')
    expect(cleanMojibake('Clean String')).toBe('Clean String')
    expect(cleanMojibake('')).toBe('')
    expect(cleanMojibake(null)).toBe('')
  })

  it('sanitizeCouncilMeta cleans council names and default icons', () => {
    const meta = sanitizeCouncilMeta('\u00f0\u0178\u0161\u20ac Breakout Council', '\u00f0\u0178\u0161\u20ac')
    expect(meta.cleanName).toBe('Breakout Council')
    expect(meta.icon).toBe('🚀')
  })

  it('sanitizeData recursively purges all mojibake from complex nested backend payloads', () => {
    const rawPayload = {
      symbol: 'NIFTY',
      personas: [
        {
          id: 'simons',
          name: 'Jim Simons',
          key_metric: 'Z-Score: -3.96\u00cf\u0192 | EV: +2.1R',
          thesis: 'Mean reversion Z-score is -3.96\u00cf\u0192',
          checklist: [
            'Z-Score: -3.96\u00cf\u0192',
            'Kelly Risk-Parity \u00e2\u2020\u2019 Sized',
          ],
        },
      ],
      councils: [
        {
          id: 'breakout',
          name: '\u00f0\u0178\u0161\u20ac Breakout Council',
          desc: 'Minervini \u00e2\u2020\u2019 Wyckoff',
        },
      ],
      setup: {
        thesis: 'High probability setup \u00e2\u20ac\u201d Defined Risk',
      },
    }

    const clean = sanitizeData(rawPayload)
    expect(clean.personas[0].key_metric).toBe('Z-Score: -3.96σ | EV: +2.1R')
    expect(clean.personas[0].thesis).toBe('Mean reversion Z-score is -3.96σ')
    expect(clean.personas[0].checklist[0]).toBe('Z-Score: -3.96σ')
    expect(clean.personas[0].checklist[1]).toBe('Kelly Risk-Parity → Sized')
    expect(clean.councils[0].name).toBe('🚀 Breakout Council')
    expect(clean.councils[0].desc).toBe('Minervini → Wyckoff')
    expect(clean.setup.thesis).toBe('High probability setup — Defined Risk')
  })
})
