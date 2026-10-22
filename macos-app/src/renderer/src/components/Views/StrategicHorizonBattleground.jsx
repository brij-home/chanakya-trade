import React, { useState, useEffect, useCallback } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const SUPPORTED_INDICES = ['NIFTY', 'BANKNIFTY', 'SENSEX']

export default function StrategicHorizonBattleground() {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)

  const [symbol, setSymbol] = useState('NIFTY')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)

  const fetchHorizon = useCallback(async (sym = symbol) => {
    setLoading(true)
    setError(null)
    try {
      const res = await call(`/api/market/strategic-horizon?symbol=${sym}`, {}, { method: 'GET' })
      if (res?.data) {
        setData(res.data)
        setLastRefreshed(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
      } else {
        setError('No strategic horizon data returned')
      }
    } catch (err) {
      console.warn('[StrategicHorizon] Failed to fetch:', err)
      setError(err?.message || 'Failed to load strategic horizon data')
    } finally {
      setLoading(false)
    }
  }, [call, symbol])

  useEffect(() => {
    fetchHorizon(symbol)
  }, [fetchHorizon, symbol])

  const spot = data?.spot ?? 0
  const vwap = data?.vwap ?? 0
  const vwapDelta = spot && vwap ? spot - vwap : 0
  const isAboveVwap = vwapDelta >= 0
  const bias = data?.bias_direction || 'NEUTRAL'
  const conviction = data?.conviction_score ?? 50
  const regime = data?.regime_verdict || 'NORMAL_SESSION'
  const smt = data?.smt_alignment || {}
  const options = data?.options_posture || {}
  const scenarios = data?.tactical_scenarios || {}
  const coaching = data?.actionable_coaching || ''

  const biasColor = bias === 'BULLISH'
    ? 'var(--color-emerald)'
    : bias === 'BEARISH'
    ? 'var(--color-rose)'
    : 'var(--color-gold)'

  const biasBg = bias === 'BULLISH'
    ? 'rgba(0, 214, 143, 0.12)'
    : bias === 'BEARISH'
    ? 'rgba(255, 79, 123, 0.12)'
    : 'rgba(245, 166, 35, 0.12)'

  return (
    <div
      className="rounded-xl p-2.5 sm:p-3 shadow-xs space-y-2.5 animate-slide-up-fade"
      style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
    >
      {/* Top Header & Symbol Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">🎯</span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-black uppercase tracking-wider text-text">
                Strategic Horizon &amp; Battleground Map
              </span>
              <span
                className="text-[11px] font-mono px-1.5 py-0.5 rounded font-bold uppercase tracking-wider"
                style={{ background: biasBg, color: biasColor, border: `1px solid ${biasColor}40` }}
              >
                {bias} • {conviction}% CONVICTION
              </span>
            </div>
            <p className="text-[10px] text-muted leading-tight">
              Forward-looking institutional map • SMT Inter-Market Alignment • Structural Walls
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex bg-surface rounded-lg p-0.5 border border-border/60">
            {SUPPORTED_INDICES.map((idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setSymbol(idx)}
                className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-md transition-all cursor-pointer ${
                  symbol === idx
                    ? 'bg-elevated text-text shadow-xs border border-border'
                    : 'text-muted hover:text-text'
                }`}
              >
                {idx}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => fetchHorizon(symbol)}
            disabled={loading}
            className="text-[10px] px-2 py-1 rounded-md border border-border bg-panel hover:bg-elevated text-muted hover:text-text cursor-pointer transition-all flex items-center gap-1"
            title="Refresh strategic horizon"
          >
            <span className={loading ? 'animate-spin' : ''}>🔄</span>
            {lastRefreshed && <span className="font-mono text-[11px] hidden sm:inline">{lastRefreshed}</span>}
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div className="py-8 text-center text-xs font-mono text-muted flex items-center justify-center gap-2">
          <span className="animate-spin text-base">🔄</span>
          <span>Synthesizing live coordinates, SMT divergence and option walls for {symbol}...</span>
        </div>
      ) : error && !data ? (
        <UnavailableState
          title={`Strategic Horizon unavailable for ${symbol}`}
          reason={error}
          onRetry={() => fetchHorizon(symbol)}
          size="sm"
        />
      ) : (
        <>
          {/* Key Metrics Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {/* Spot vs VWAP */}
            <div className="p-2 rounded-lg bg-surface/70 border border-border/60 space-y-0.5">
              <div className="flex items-center justify-between text-[10px] text-muted font-mono font-medium">
                <span>SPOT / VWAP</span>
                <span
                  className="font-bold text-[11px] px-1 rounded"
                  style={{
                    background: isAboveVwap ? 'rgba(0, 214, 143, 0.15)' : 'rgba(255, 79, 123, 0.15)',
                    color: isAboveVwap ? 'var(--color-emerald)' : 'var(--color-rose)'
                  }}
                >
                  {isAboveVwap ? '▲ ABOVE VWAP' : '▼ BELOW VWAP'}
                </span>
              </div>
              <div className="text-sm font-mono font-bold text-text tabular-nums">
                ₹{spot ? spot.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
              </div>
              <div className="text-[10px] font-mono text-muted flex items-center justify-between">
                <span>VWAP: ₹{vwap ? vwap.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}</span>
                <span style={{ color: isAboveVwap ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                  {isAboveVwap ? '+' : ''}{vwapDelta.toFixed(1)} pts
                </span>
              </div>
            </div>

            {/* Regime Verdict */}
            <div className="p-2 rounded-lg bg-surface/70 border border-border/60 space-y-0.5">
              <div className="text-[10px] text-muted font-mono font-medium">
                REGIME VERDICT
              </div>
              <div
                className="text-xs font-mono font-black truncate"
                style={{
                  color: regime.includes('TRAP') || regime.includes('LIQUIDATION')
                    ? 'var(--color-rose)'
                    : regime.includes('EXPANSION')
                    ? 'var(--color-emerald)'
                    : 'var(--color-gold)'
                }}
                title={regime}
              >
                {regime.replace(/_/g, ' ')}
              </div>
              <div className="text-[11px] text-muted truncate">
                Day Range: ₹{data?.day_low ? Number(data.day_low).toFixed(0) : '—'} – ₹{data?.day_high ? Number(data.day_high).toFixed(0) : '—'}
              </div>
            </div>

            {/* Options Strike Walls */}
            <div className="p-2 rounded-lg bg-surface/70 border border-border/60 space-y-0.5">
              <div className="flex items-center justify-between text-[10px] text-muted font-mono font-medium">
                <span>OPTIONS WALLS</span>
                <span className="font-bold text-[11px] text-indigo-400">
                  PCR: {options?.pcr ?? '—'}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs font-mono font-bold">
                <span style={{ color: 'var(--color-rose)' }} title="Call Wall (Ceiling)">
                  CW: {options?.call_wall ? Number(options.call_wall).toFixed(0) : '—'}
                </span>
                <span className="text-muted text-[10px]">|</span>
                <span style={{ color: 'var(--color-emerald)' }} title="Put Wall (Floor)">
                  PW: {options?.put_wall ? Number(options.put_wall).toFixed(0) : '—'}
                </span>
              </div>
              <div className="text-[11px] text-muted font-mono truncate">
                {options?.total_contracts ?? 0} strike contracts evaluated
              </div>
            </div>

            {/* Market Breadth Alignment */}
            <div className="p-2 rounded-lg bg-surface/70 border border-border/60 space-y-0.5">
              <div className="flex items-center justify-between text-[10px] text-muted font-mono font-medium">
                <span>BREADTH ALIGNMENT</span>
                <span className="font-bold text-[11px] text-sky-400">
                  A/D: {data?.market_breadth?.ad_ratio ?? '—'}x
                </span>
              </div>
              <div className="text-xs font-mono font-bold text-text truncate">
                {data?.market_breadth?.verdict || 'HARMONIOUS'}
              </div>
              <div className="text-[11px] text-muted font-mono flex justify-between">
                <span style={{ color: 'var(--color-emerald)' }}>▲ {data?.market_breadth?.advances ?? 0}</span>
                <span style={{ color: 'var(--color-rose)' }}>▼ {data?.market_breadth?.declines ?? 0}</span>
              </div>
            </div>
          </div>

          {/* SMT Inter-Market Divergence Banner */}
          {smt?.has_divergence ? (
            <div
              className="p-2 rounded-lg border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2"
              style={{
                background: 'rgba(245, 158, 11, 0.08)',
                borderColor: 'rgba(245, 158, 11, 0.35)'
              }}
            >
              <div className="flex items-start gap-2">
                <span className="text-base flex-shrink-0">⚡</span>
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-black text-amber-400">
                      SMT INTER-MARKET DIVERGENCE: {smt.divergence_type?.replace(/_/g, ' ')}
                    </span>
                    {smt.is_trap && (
                      <span className="text-[11px] font-mono px-1 rounded bg-rose-500/20 text-rose-400 font-bold border border-rose-500/40">
                        INSTITUTIONAL TRAP
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-muted leading-tight">
                    {smt.rationale || `Sibling ${smt.sibling_symbol} diverging at ₹${smt.sibling_spot}.`}
                  </p>
                </div>
              </div>
              <div className="text-[10px] font-mono text-muted flex-shrink-0 self-end sm:self-center">
                Sibling: <span className="font-bold text-text">{smt.sibling_symbol}</span> (₹{smt.sibling_spot})
              </div>
            </div>
          ) : (
            <div className="px-2.5 py-1.5 rounded-lg bg-surface/50 border border-border/40 flex items-center justify-between text-[10px] font-mono text-muted">
              <span className="flex items-center gap-1.5">
                <span className="text-emerald-400">✔</span>
                <span>Inter-Market Structure: Harmonious with {smt?.sibling_symbol || 'Sibling Index'} (No SMT divergence)</span>
              </span>
              <span className="text-text font-bold">SMT IN STEP</span>
            </div>
          )}

          {/* Institutional Price Corridor / Battleground Map */}
          <div className="p-2.5 rounded-lg bg-surface/70 border border-border/60 space-y-1.5">
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted flex items-center justify-between">
              <span>🗺️ Key Institutional Battleground Levels</span>
              <span className="text-[11px] text-text font-normal font-sans">
                {data?.battleground_zone || 'Active Session Corridor'}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center font-mono">
              <div className="p-1.5 rounded bg-panel border border-border/50">
                <div className="text-[11px] text-muted uppercase">Invalidation Boundary</div>
                <div className="text-xs font-bold" style={{ color: 'var(--color-rose)' }}>
                  ₹{data?.invalidation_level ? Number(data.invalidation_level).toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
                </div>
              </div>

              <div className="p-1.5 rounded bg-panel border border-border/50">
                <div className="text-[11px] text-muted uppercase">Immediate Resistance</div>
                <div className="text-xs font-bold text-amber-400">
                  ₹{data?.immediate_resistance ? Number(data.immediate_resistance).toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
                </div>
              </div>

              <div className="p-1.5 rounded bg-panel border border-border/50">
                <div className="text-[11px] text-muted uppercase">Pivot Equilibrium</div>
                <div className="text-xs font-bold text-sky-400">
                  ₹{data?.pivot_equilibrium ? Number(data.pivot_equilibrium).toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
                </div>
              </div>

              <div className="p-1.5 rounded bg-panel border border-border/50">
                <div className="text-[11px] text-muted uppercase">Immediate Support</div>
                <div className="text-xs font-bold" style={{ color: 'var(--color-emerald)' }}>
                  ₹{data?.immediate_support ? Number(data.immediate_support).toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
                </div>
              </div>
            </div>
          </div>

          {/* Forward-Looking Tactical Scenarios & Coaching */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {scenarios?.bull_case && (
              <div className="p-2 rounded-lg bg-surface/60 border border-emerald-500/20 text-[10.5px] space-y-1">
                <div className="flex items-center gap-1.5 font-bold font-mono text-emerald-400">
                  <span>🐂</span>
                  <span>BULL ROADMAP</span>
                </div>
                <p className="text-muted leading-relaxed font-ui">
                  {scenarios.bull_case}
                </p>
              </div>
            )}

            {scenarios?.bear_case && (
              <div className="p-2 rounded-lg bg-surface/60 border border-rose-500/20 text-[10.5px] space-y-1">
                <div className="flex items-center gap-1.5 font-bold font-mono text-rose-400">
                  <span>🐻</span>
                  <span>BEAR ROADMAP</span>
                </div>
                <p className="text-muted leading-relaxed font-ui">
                  {scenarios.bear_case}
                </p>
              </div>
            )}
          </div>

          {/* Actionable Coaching Bar & 1-Click Execution */}
          {coaching && (
            <div className="p-2 rounded-lg bg-elevated border border-border/70 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-base">🧭</span>
                <span className="text-[11px] text-text font-medium leading-tight">
                  <strong className="text-amber-400 font-mono font-bold mr-1">STRATEGIC DIRECTIVE:</strong>
                  {coaching}
                </span>
              </div>

              <div className="flex items-center gap-1.5 self-end sm:self-center flex-shrink-0">
                <button
                  type="button"
                  onClick={() => sendDraft(`analyse ${symbol}`, { autoSubmit: true })}
                  className="px-2.5 py-1 rounded bg-sky-500/15 hover:bg-sky-500/25 border border-sky-500/30 text-sky-400 text-[10px] font-mono font-bold transition-all cursor-pointer"
                >
                  Deep Scrutiny
                </button>
                <button
                  type="button"
                  onClick={() => sendDraft(`options ${symbol}`, { autoSubmit: true })}
                  className="px-2.5 py-1 rounded bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/30 text-indigo-400 text-[10px] font-mono font-bold transition-all cursor-pointer"
                >
                  Options Chain
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
