import { describe, it, expect } from 'vitest'
import { resolveAlertProvenance } from '../renderer/src/components/Views/alerts/alertHelpers'

describe('resolveAlertProvenance Truthfulness & Invariant Gates', () => {
  it('resolves REAL/LIVE for live environment alerts even if legacy market_status was SESSION_CLOSED', () => {
    const alert = {
      alert_id: 'aa-index-micro-scalp-banknifty-ce-55700-20261015',
      symbol: 'BANKNIFTY',
      alert_type: 'INDEX_MICRO_SCALP',
      environment: 'LIVE',
      is_live: true,
      market_status: 'SESSION_CLOSED', // Legacy dataclass default
    }

    const res = resolveAlertProvenance(alert)
    expect(res.isLive).toBe(true)
    expect(res.isOffMarket).toBe(false)
    expect(res.isTest).toBe(false)
    expect(res.label).toBe('🟢 REAL / LIVE')
  })

  it('resolves REAL/LIVE for normal live alerts with market_status LIVE', () => {
    const alert = {
      alert_id: 'aa-gamma-blast-hindpetro-20261015',
      symbol: 'HINDPETRO',
      alert_type: 'GAMMA_BLAST',
      environment: 'LIVE',
      is_live: true,
      market_status: 'LIVE',
    }

    const res = resolveAlertProvenance(alert)
    expect(res.isLive).toBe(true)
    expect(res.isOffMarket).toBe(false)
    expect(res.label).toBe('🟢 REAL / LIVE')
  })

  it('resolves OFF-MARKET/EOD for genuine EOD_SCAN alerts', () => {
    const alert = {
      alert_id: 'aa-stage-1-to-2-expansion-zyduslife-pull-20261010',
      symbol: 'ZYDUSLIFE',
      alert_type: 'STAGE_1_TO_2_EXPANSION',
      environment: 'EOD_SCAN',
      is_live: true,
      market_status: 'SESSION_CLOSED',
    }

    const res = resolveAlertProvenance(alert)
    expect(res.isLive).toBe(false)
    expect(res.isOffMarket).toBe(true)
    expect(res.label).toBe('🌙 OFF-MARKET / EOD')
  })

  it('resolves OFF-MARKET/EOD for OFF-MARKET environment alerts', () => {
    const alert = {
      alert_id: 'aa-weekend-swing-1',
      symbol: 'RELIANCE',
      environment: 'OFF-MARKET',
      market_status: 'SESSION_CLOSED',
    }

    const res = resolveAlertProvenance(alert)
    expect(res.isOffMarket).toBe(true)
    expect(res.label).toBe('🌙 OFF-MARKET / EOD')
  })

  it('resolves TEST for test alerts', () => {
    const alert = {
      alert_id: 'test-index-scalp-1',
      symbol: 'NIFTY',
      environment: 'TEST',
      is_live: false,
    }

    const res = resolveAlertProvenance(alert)
    expect(res.isTest).toBe(true)
    expect(res.isLive).toBe(false)
    expect(res.label).toBe('🧪 TEST')
  })
})
