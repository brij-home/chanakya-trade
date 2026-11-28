import { useState, useEffect, useCallback } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { createVisibilityInterval } from '../../utils/visibilityPoll'

const WATCHED_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'SENSEX', 'MIDCPNIFTY', 'RELIANCE', 'HDFCBANK', 'TCS']

function unwrapData(json) {
  if (!json || typeof json !== 'object') return null
  return json.data !== undefined ? json.data : json
}

function StatusChip({ label, tone = 'muted' }) {
  const palette = {
    profit: { bg: 'rgba(16,185,129,0.15)', fg: 'var(--color-profit)' },
    loss: { bg: 'rgba(244,63,94,0.15)', fg: 'var(--color-loss)' },
    gold: { bg: 'rgba(245,158,11,0.15)', fg: 'var(--color-gold)' },
    indigo: { bg: 'rgba(99,102,241,0.15)', fg: 'var(--color-indigo)' },
    sky: { bg: 'rgba(14,165,233,0.15)', fg: 'var(--color-sky)' },
    muted: { bg: 'rgba(148,163,184,0.12)', fg: 'var(--color-muted)' },
  }
  const c = palette[tone] || palette.muted
  return (
    <span
      className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold"
      style={{ background: c.bg, color: c.fg }}
    >
      {label}
    </span>
  )
}

export default function QuantRadarPanel() {
  const port = useChatStore((s) => s.port)
  const [selectedSymbol, setSelectedSymbol] = useState('NIFTY')
  const [stageFilter, setStageFilter] = useState('ALL')
  const [loading, setLoading] = useState(false)
  const [readiness, setReadiness] = useState(null)
  const [radar, setRadar] = useState(null)
  const [tournament, setTournament] = useState(null)
  const [metaLabeler, setMetaLabeler] = useState(null)
  const [ivSurface, setIvSurface] = useState(null)
  const [casRegime, setCasRegime] = useState(null)
  const [postmortem, setPostmortem] = useState(null)

  const fetchAll = useCallback(async () => {
    if (!port) return
    setLoading(true)
    const base = getBaseUrl(port)
    const stageQs = stageFilter !== 'ALL' ? `?stage=${encodeURIComponent(stageFilter)}` : ''
    try {
      const results = await Promise.allSettled([
        fetch(`${base}/skills/quant/readiness`, { signal: AbortSignal.timeout(5000) }),
        fetch(`${base}/skills/quant/armed-radar${stageQs}`, { signal: AbortSignal.timeout(5000) }),
        fetch(`${base}/skills/quant/tournament`, { signal: AbortSignal.timeout(5000) }),
        fetch(`${base}/skills/quant/meta-labeler`, { signal: AbortSignal.timeout(5000) }),
        fetch(`${base}/skills/quant/iv-surface/${encodeURIComponent(selectedSymbol)}`, {
          signal: AbortSignal.timeout(5000),
        }),
        fetch(`${base}/skills/quant/cas-regime/${encodeURIComponent(selectedSymbol)}`, {
          signal: AbortSignal.timeout(5000),
        }),
        fetch(`${base}/skills/quant/eod-5w-postmortem`, { signal: AbortSignal.timeout(5000) }),
      ])
      const setters = [
        setReadiness,
        setRadar,
        setTournament,
        setMetaLabeler,
        setIvSurface,
        setCasRegime,
        setPostmortem,
      ]
      await Promise.all(
        results.map(async (res, idx) => {
          if (res.status === 'fulfilled' && res.value.ok) {
            const payload = await res.value.json()
            setters[idx](unwrapData(payload))
          }
        })
      )
    } catch (_) {
      // Fail closed silently; card states stay null/UNAVAILABLE
    } finally {
      setLoading(false)
    }
  }, [port, selectedSymbol, stageFilter])

  useEffect(() => {
    fetchAll()
    return createVisibilityInterval(fetchAll, 8000)
  }, [fetchAll])

  const execSafety = readiness?.execution_safety || {}
  const discPolicy = readiness?.discovery_policy || {}
  const calResearch = readiness?.calibration_and_research || {}
  const brokerFeed = readiness?.broker_and_feed || {}
  const openGaps = Array.isArray(readiness?.open_gaps) ? readiness.open_gaps : []
  const radarItems = Array.isArray(radar?.items) ? radar.items : []
  const profiles = tournament?.profiles || calResearch?.tournament_profiles || {}
  const metaModel = metaLabeler?.model || null

  return (
    <div className="space-y-3 max-w-6xl mx-auto p-1">
      {/* Header & Controls */}
      <div className="p-3 rounded-xl border border-border bg-panel flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-text">
            Quant Engine & Qualification Radar
          </span>
          <StatusChip
            label={`MODE: ${execSafety.trading_mode || 'UNKNOWN'}`}
            tone={execSafety.live_orders_blocked !== false ? 'gold' : 'profit'}
          />
          <StatusChip
            label={`SCOPE: ${discPolicy.profile || 'UNKNOWN'}`}
            tone={discPolicy.fno_only ? 'indigo' : 'sky'}
          />
          <StatusChip
            label={brokerFeed.fyers_token?.fresh_since_0630_ist ? 'TOKEN FRESH' : 'TOKEN STALE'}
            tone={brokerFeed.fyers_token?.fresh_since_0630_ist ? 'profit' : 'loss'}
          />
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Symbol selector"
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
            className="px-2 py-1 rounded text-xs font-mono bg-surface border border-border text-text"
          >
            {WATCHED_SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={fetchAll}
            disabled={loading}
            className="px-2.5 py-1 rounded text-xs font-mono font-bold border border-border bg-elevated hover:bg-highlight text-text cursor-pointer"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Top KPI Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
        <div className="p-2.5 rounded-lg border border-border bg-panel space-y-1">
          <div className="text-[10px] font-mono uppercase text-muted">Meta-Labeler (P(Net Win))</div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-mono font-bold tabular-nums text-text">
              {metaModel?.sample_count ?? calResearch?.meta_model_samples ?? 0} OOS
            </span>
            <StatusChip
              label={metaLabeler?.model_status || calResearch?.meta_model_status || 'UNCALIBRATED'}
              tone={(metaLabeler?.model_status || calResearch?.meta_model_status) === 'CALIBRATED' ? 'profit' : 'gold'}
            />
          </div>
          <div className="text-[11px] font-mono text-muted tabular-nums">
            Brier: {metaModel?.oos_brier_score ?? calResearch?.meta_model_oos_brier ?? 'UNAVAILABLE'}
          </div>
        </div>

        <div className="p-2.5 rounded-lg border border-border bg-panel space-y-1">
          <div className="text-[10px] font-mono uppercase text-muted">{selectedSymbol} IV Surface</div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-mono font-bold tabular-nums text-text">
              {ivSurface?.atm_iv_30d ? `${ivSurface.atm_iv_30d}%` : 'UNAVAILABLE'}
            </span>
            <StatusChip
              label={ivSurface?.iv_rank != null ? `IVR ${ivSurface.iv_rank}` : 'IVR UNAVAILABLE'}
              tone={ivSurface?.iv_rank != null ? 'indigo' : 'muted'}
            />
          </div>
          <div className="text-[11px] font-mono text-muted tabular-nums">
            VRP: {ivSurface?.vrp ?? 'N/A'} | Skew25D: {ivSurface?.skew_25d ?? 'N/A'}
          </div>
        </div>

        <div className="p-2.5 rounded-lg border border-border bg-panel space-y-1">
          <div className="text-[10px] font-mono uppercase text-muted">{selectedSymbol} CAS / Close Rule</div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-mono font-bold tabular-nums text-text">
              {casRegime?.segment_close || 'N/A'}
            </span>
            <StatusChip
              label={casRegime?.is_cas_dispersion_window ? 'CAS DISPERSION' : 'STANDARD'}
              tone={casRegime?.is_cas_dispersion_window ? 'sky' : 'muted'}
            />
          </div>
          <div className="text-[11px] font-mono text-muted tabular-nums">
            Cutoff: {casRegime?.entry_cutoff || 'N/A'} | Allow: {casRegime?.allow_new_entry ? 'YES' : 'NO'}
          </div>
        </div>

        <div className="p-2.5 rounded-lg border border-border bg-panel space-y-1">
          <div className="text-[10px] font-mono uppercase text-muted">EOD 5W Post-Mortem</div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-mono font-bold tabular-nums text-text">
              {postmortem ? `${postmortem.wins ?? 0}W / ${postmortem.losses ?? 0}L` : 'UNAVAILABLE'}
            </span>
            <StatusChip
              label={postmortem?.net_r != null ? `${postmortem.net_r}R` : '0.0R'}
              tone={(postmortem?.net_r || 0) > 0 ? 'profit' : 'muted'}
            />
          </div>
          <div className="text-[11px] font-mono text-muted truncate">
            Lead WHY: {postmortem?.why_top_driver || 'NONE'}
          </div>
        </div>
      </div>

      {/* Causal Armed Radar */}
      <div className="p-3 rounded-xl border border-border bg-panel space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-text">
            Causal Armed Radar ({radarItems.length})
          </span>
          <div className="flex gap-1">
            {['ALL', 'WATCH', 'ARMED', 'TRIGGERED', 'VETOED'].map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setStageFilter(st)}
                className="px-2 py-0.5 rounded text-[10px] font-mono border border-border cursor-pointer"
                style={{
                  color: stageFilter === st ? 'var(--color-gold)' : 'var(--color-muted)',
                  background: stageFilter === st ? 'rgba(245,158,11,0.12)' : 'transparent',
                }}
              >
                {st}
              </button>
            ))}
          </div>
        </div>
        {radarItems.length === 0 ? (
          <div className="text-xs font-mono text-muted py-2">
            No symbols currently staged in {stageFilter} state.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono tabular-nums">
              <thead>
                <tr className="text-left text-[10px] uppercase text-muted border-b border-border">
                  <th className="py-1 px-2">Symbol</th>
                  <th className="py-1 px-2">Stage</th>
                  <th className="py-1 px-2">Dir</th>
                  <th className="py-1 px-2">Anchor</th>
                  <th className="py-1 px-2">Dist ATR</th>
                  <th className="py-1 px-2">TBT Scout</th>
                </tr>
              </thead>
              <tbody>
                {radarItems.slice(0, 20).map((it) => (
                  <tr key={`${it.symbol}-${it.anchor_name}`} className="border-b border-border/40">
                    <td className="py-1 px-2 font-bold text-text">{it.symbol}</td>
                    <td className="py-1 px-2">
                      <StatusChip
                        label={it.stage}
                        tone={
                          it.stage === 'TRIGGERED'
                            ? 'profit'
                            : it.stage === 'ARMED'
                            ? 'gold'
                            : it.stage === 'VETOED'
                            ? 'loss'
                            : 'muted'
                        }
                      />
                    </td>
                    <td
                      className="py-1 px-2"
                      style={{
                        color:
                          it.direction === 'BULLISH'
                            ? 'var(--color-profit)'
                            : 'var(--color-loss)',
                      }}
                    >
                      {it.direction}
                    </td>
                    <td className="py-1 px-2 text-muted">
                      {it.anchor_name} ({it.anchor_price})
                    </td>
                    <td className="py-1 px-2">{it.distance_atr}</td>
                    <td className="py-1 px-2">{it.tbt_scout_promoted ? 'ACTIVE' : 'NO'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Multi-Profile Purged Walk-Forward Tournament Comparison */}
      <div className="p-3 rounded-xl border border-border bg-panel space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-text">
            Multi-Profile Walk-Forward Detector Tournament
          </span>
          <StatusChip label={tournament?.status || calResearch?.tournament_status || 'UNCALIBRATED'} tone="sky" />
        </div>
        {Object.keys(profiles).length === 0 && Object.keys(tournament?.detectors || {}).length === 0 ? (
          <div className="text-xs font-mono text-muted py-2">Tournament report unavailable.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono tabular-nums">
              <thead>
                <tr className="text-left text-[10px] uppercase text-muted border-b border-border">
                  <th className="py-1 px-2">Profile / Detector</th>
                  <th className="py-1 px-2">Trades</th>
                  <th className="py-1 px-2">Win %</th>
                  <th className="py-1 px-2">Net Exp (R)</th>
                  <th className="py-1 px-2">Governance</th>
                </tr>
              </thead>
              <tbody>
                {(Object.keys(profiles).length > 0
                  ? Object.entries(profiles).flatMap(([profName, pBody]) =>
                      Object.entries(pBody?.detectors || {}).map(([det, dInfo]) => ({
                        key: `${profName} · ${det}`,
                        ...dInfo,
                      }))
                    )
                  : Object.entries(tournament?.detectors || {}).map(([det, dInfo]) => ({
                      key: det,
                      ...dInfo,
                    }))
                ).map((row) => (
                  <tr key={row.key} className="border-b border-border/40">
                    <td className="py-1 px-2 text-text">{row.key}</td>
                    <td className="py-1 px-2">{row.trades ?? 0}</td>
                    <td className="py-1 px-2">{row.win_rate_pct ?? 'N/A'}%</td>
                    <td
                      className="py-1 px-2 font-bold"
                      style={{
                        color:
                          (row.net_expectancy_r ?? -1) > 0
                            ? 'var(--color-profit)'
                            : 'var(--color-loss)',
                      }}
                    >
                      {row.net_expectancy_r ?? 'N/A'}R
                    </td>
                    <td className="py-1 px-2">
                      <StatusChip
                        label={row.governance || row.status || 'UNCALIBRATED'}
                        tone={row.governance === 'PROMOTED_SHADOW' ? 'profit' : 'gold'}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Qualification Blockers & Feed Capability */}
      {openGaps.length > 0 && (
        <div className="p-3 rounded-xl border border-border bg-panel space-y-1.5">
          <div className="text-xs font-mono font-bold uppercase tracking-wider" style={{ color: 'var(--color-gold)' }}>
            Open Qualification & Calibration Gates ({openGaps.length})
          </div>
          <ul className="space-y-1 text-xs font-mono text-muted">
            {openGaps.map((g, i) => (
              <li key={i}>• {g}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
