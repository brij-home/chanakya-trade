import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

/**
 * SmtDivergenceRadar
 * ──────────────────
 * Cross-Market Smart Money Technique (SMT) Inter-Index & Commodity Divergence Radar.
 * Detects institutional accumulation (bear traps), distribution (Judas swing bull traps),
 * locomotive polarization conflicts, and harmonious multi-market trends.
 */
export default function SmtDivergenceRadar({ isOpen, onClose }) {
  const { call } = useAPI()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const fetchSmt = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await call('/api/scanner/smt_divergences')
      const payload = res?.data ?? res
      setData(payload)
    } catch (err) {
      setError(err?.message || 'Failed to scan cross-market SMT divergences')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchSmt()
    }
  }, [isOpen])

  if (!isOpen) return null

  const summary = data?.summary || {}
  const pairs = data?.pairs || []

  return (
    <div className="bg-panel border border-border/80 rounded-xl p-4 space-y-4 mb-4 shadow-sm animate-in fade-in duration-150">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">⚖️</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold font-mono text-text">
                Cross-Market SMT Divergence Radar
              </h3>
              <span className="bg-amber/15 text-amber text-[10px] font-mono px-2 py-0.5 rounded font-bold border border-amber/30">
                Institutional Inter-Market Flow
              </span>
            </div>
            <p className="text-[11px] text-muted font-ui">
              Smart Money Technique (SMT) non-confirmation sweeps across Nifty, BankNifty, Sensex, Gold, Silver &amp; Crude.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchSmt}
            disabled={loading}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-border bg-elevated hover:bg-surface text-muted hover:text-text cursor-pointer transition-all"
            title="Refresh cross-market SMT scan"
          >
            <span className={loading ? 'animate-spin' : ''}>🔄</span>
            <span>{loading ? 'Scanning...' : 'Refresh'}</span>
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="text-muted hover:text-text p-1 text-sm font-bold cursor-pointer"
              title="Collapse SMT Radar"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Summary KPI Strip */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center font-mono text-xs">
          <div className="bg-elevated/40 p-2 rounded-lg border border-border/40">
            <span className="text-[10px] text-muted block">Pairs Monitored</span>
            <span className="text-sm font-bold text-text tabular-nums">
              {summary.total_pairs_scanned || pairs.length}
            </span>
          </div>

          <div className="bg-emerald-500/10 p-2 rounded-lg border border-emerald-500/20">
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 block">Bullish Accumulation</span>
            <span className="text-sm font-bold text-emerald-500 tabular-nums">
              {summary.bullish_divergences || 0}
            </span>
          </div>

          <div className="bg-rose-500/10 p-2 rounded-lg border border-rose-500/20">
            <span className="text-[10px] text-rose-600 dark:text-rose-400 block">Bearish Distribution</span>
            <span className="text-sm font-bold text-rose-500 tabular-nums">
              {summary.bearish_divergences || 0}
            </span>
          </div>

          <div className="bg-amber/10 p-2 rounded-lg border border-amber/20">
            <span className="text-[10px] text-amber block">Polarization Conflict</span>
            <span className="text-sm font-bold text-amber tabular-nums">
              {summary.polarized_conflicts || 0}
            </span>
          </div>

          <div className="bg-sky-500/10 p-2 rounded-lg border border-sky-500/20">
            <span className="text-[10px] text-sky-400 block">Harmonious Trends</span>
            <span className="text-sm font-bold text-sky-400 tabular-nums">
              {summary.harmonious_flows || 0}
            </span>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="p-3 rounded-lg bg-red/10 border border-red/30 text-red text-xs font-mono">
          {error}
        </div>
      )}

      {/* Pairs Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {loading && !data ? (
          <div className="col-span-full py-10 flex flex-col items-center justify-center gap-2 text-muted font-mono text-xs">
            <span className="animate-spin text-xl">⏳</span>
            <span>Scanning inter-market correlation feeds...</span>
          </div>
        ) : (
          pairs.map((p) => {
            const isBull = p.status === 'BULLISH_SMT_ACCUMULATION'
            const isBear = p.status === 'BEARISH_SMT_DISTRIBUTION'
            const isConflict = p.status === 'POLARIZED_CONFLICT'
            const isHarmony = p.status === 'HARMONIOUS_FLOW'

            const statusBadgeColor = isBull
              ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
              : isBear
              ? 'bg-rose-500/15 border-rose-500/30 text-rose-600 dark:text-rose-400'
              : isConflict
              ? 'bg-amber/15 border-amber/30 text-amber'
              : isHarmony
              ? 'bg-sky-500/15 border-sky-500/30 text-sky-400'
              : 'bg-elevated border-border text-muted'

            return (
              <div
                key={p.pair_id}
                className="bg-surface/70 border border-border/70 rounded-xl p-3 flex flex-col justify-between space-y-2.5 transition-all hover:border-amber/40 shadow-2xs"
              >
                <div>
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center gap-1.5 font-mono font-bold text-xs text-text">
                      <span>{p.asset_a}</span>
                      <span className="text-muted">/</span>
                      <span>{p.asset_b}</span>
                    </div>
                    <span
                      className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${statusBadgeColor}`}
                    >
                      {p.status.replace(/_/g, ' ')}
                    </span>
                  </div>

                  {/* Telemetry Comparison Table */}
                  <div className="mt-2 bg-elevated/40 rounded-lg p-2 border border-border/40 font-mono text-[10px] space-y-1">
                    <div className="flex items-center justify-between text-muted">
                      <span className="font-bold text-text">{p.asset_a}:</span>
                      <div className="flex items-center gap-2">
                        <span>₹{p.asset_a_metrics?.ltp?.toLocaleString('en-IN') || '—'}</span>
                        <span
                          className={`font-bold ${
                            (p.asset_a_metrics?.change_pct || 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          }`}
                        >
                          {(p.asset_a_metrics?.change_pct || 0) >= 0 ? '+' : ''}
                          {p.asset_a_metrics?.change_pct || 0}%
                        </span>
                        <span className="text-muted">VWAP ₹{p.asset_a_metrics?.vwap || '—'}</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-muted">
                      <span className="font-bold text-text">{p.asset_b}:</span>
                      <div className="flex items-center gap-2">
                        <span>₹{p.asset_b_metrics?.ltp?.toLocaleString('en-IN') || '—'}</span>
                        <span
                          className={`font-bold ${
                            (p.asset_b_metrics?.change_pct || 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          }`}
                        >
                          {(p.asset_b_metrics?.change_pct || 0) >= 0 ? '+' : ''}
                          {p.asset_b_metrics?.change_pct || 0}%
                        </span>
                        <span className="text-muted">VWAP ₹{p.asset_b_metrics?.vwap || '—'}</span>
                      </div>
                    </div>
                  </div>

                  {/* Rationale */}
                  <p className="mt-2 text-[11px] text-muted leading-relaxed font-ui">
                    {p.rationale}
                  </p>
                </div>

                {/* Footer Directive */}
                <div className="flex items-center justify-between pt-2 border-t border-border/30 text-[10px] font-mono">
                  <span className="text-muted">Directive:</span>
                  <span
                    className={`font-bold px-1.5 py-0.5 rounded ${
                      isBull
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : isBear
                        ? 'bg-rose-500/20 text-rose-400'
                        : isConflict
                        ? 'bg-amber/20 text-amber'
                        : 'bg-elevated text-text'
                    }`}
                  >
                    {p.actionable_directive.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
