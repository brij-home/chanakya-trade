import { useState, useEffect, useRef } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import { getSymbolExchange } from '../../data/universeData'

const COUNCIL_MODES = [
  { id: 'debate', name: 'Bull vs Bear Debate', icon: '⚔️', desc: 'Adversarial Thesis & Anti-Thesis' },
  { id: 'breakout', name: 'Breakout Council', icon: '🚀', desc: 'Minervini + Wyckoff + O\'Neil + Forensic' },
  { id: 'options_sniper', name: 'Options Sniper', icon: '🎯', desc: 'SMC + Taleb + Simons' },
  { id: 'multibagger', name: 'Multibagger Hub', icon: '💎', desc: 'Kedia + Buffett + Munger + Jhunjhunwala' },
  { id: 'macro_regime', name: 'Macro Regime', icon: '🌐', desc: 'Soros + Jhunjhunwala + Simons + Forensic' },
  { id: 'core_value', name: 'Core Value', icon: '🏛️', desc: 'Buffett + Munger + Lynch + Forensic' },
]

const PERSONA_NAMES = {
  buffett: 'Warren Buffett',
  munger: 'Charlie Munger',
  lynch: 'Peter Lynch',
  jhunjhunwala: 'Rakesh Jhunjhunwala',
  kedia: 'Vijay Kedia',
  minervini: 'Mark Minervini',
  wyckoff: 'Richard Wyckoff',
  oneil: "William O'Neil",
  taleb: 'Nassim Taleb',
  simons: 'Jim Simons',
  smc: 'Smart Money Concepts',
  forensic: 'Forensic Auditor',
  soros: 'George Soros',
}

export default function DebateArenaView({ onOpenOrderTicket, externalSymbol, onSymbolChange }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [symbol, setSymbolState] = useState(externalSymbol || 'RELIANCE')
  const [inputSymbol, setInputSymbol] = useState('')
  const [selectedCouncil, setSelectedCouncil] = useState('debate')
  const [data, setData] = useState(null)
  const [councilData, setCouncilData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState([])
  const [expandedMember, setExpandedMember] = useState(null)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (externalSymbol && externalSymbol !== symbol) {
      setSymbolState(externalSymbol)
    }
  }, [externalSymbol])

  const setSymbol = (sym) => {
    setSymbolState(sym)
    onSymbolChange?.(sym)
  }

  const startActivity = useChatStore((s) => s.startActivity)
  const updateActivity = useChatStore((s) => s.updateActivity)
  const stopActivity = useChatStore((s) => s.stopActivity)

  const executeDebate = async (targetSymbol = symbol, targetCouncil = selectedCouncil) => {
    if (abortRef.current) {
      try {
        abortRef.current.abort()
      } catch (e) {}
    }
    const abortController = new AbortController()
    abortRef.current = abortController

    setError(null)
    setIsStreaming(true)
    setLoading(true)
    const isCouncil = targetCouncil !== 'debate'
    const councilName = COUNCIL_MODES.find((c) => c.id === targetCouncil)?.name || 'Council'
    const title = isCouncil ? `${councilName} (${targetSymbol})` : `Adversarial Debate (${targetSymbol})`

    startActivity({
      title,
      details: `⚡ Polling ${councilName} for ${targetSymbol}...`,
      type: 'debate',
      targetView: 'debate',
      cancelFn: () => {
        try {
          abortController.abort()
        } catch (e) {}
        setIsStreaming(false)
        setLoading(false)
        stopActivity()
      },
    })

    setStreamingSteps([`⚡ Initializing Multi-Agent Pipeline for ${targetSymbol}...`])

    const stepTimer1 = setTimeout(() => {
      setStreamingSteps((prev) => [
        ...prev,
        `🔍 Extracting Minervini VCP, Wyckoff accumulation & SMC Order Blocks...`,
      ])
    }, 450)
    const stepTimer2 = setTimeout(() => {
      setStreamingSteps((prev) => [
        ...prev,
        `🔬 Persona agents debating invalidation and risk parameters...`,
      ])
    }, 1100)
    const stepTimer3 = setTimeout(() => {
      setStreamingSteps((prev) => [
        ...prev,
        `⚖️ Synthesizing high-conviction consensus score...`,
      ])
    }, 2000)

    const t1 = setTimeout(() => updateActivity({ details: `🔍 Specialists extracting quantitative edge metrics for ${targetSymbol}...` }), 300)
    const t2 = setTimeout(() => updateActivity({ details: `🔬 Persona agents debating invalidation and risk parameters...` }), 750)
    const t3 = setTimeout(() => updateActivity({ details: `⚖️ Synthesizing high-conviction consensus score...` }), 1200)

    try {
      const targetExchange = getSymbolExchange(targetSymbol)
      const callOpts = { signal: abortController.signal, timeoutMs: 18000 }
      if (targetCouncil === 'debate') {
        const res = await call('/skills/debate_snapshot', { symbol: targetSymbol, exchange: targetExchange }, callOpts)
        const snapshot = res?.data ?? res
        if (snapshot) {
          setData(snapshot)
          setError(null)
        }
      } else {
        const res = await call('/skills/persona/council', { symbol: targetSymbol, council: targetCouncil, exchange: targetExchange }, callOpts)
        const cSnapshot = res?.data ?? res
        if (cSnapshot) {
          setCouncilData(cSnapshot)
          setError(null)
        }
      }

      setStreamingSteps([
        `⚡ Initializing Multi-Agent Pipeline for ${targetSymbol}...`,
        `🔍 Extracting Minervini VCP, Wyckoff accumulation & SMC Order Blocks...`,
        `🔬 Persona agents debating invalidation and risk parameters...`,
        `⚖️ Synthesizing high-conviction consensus score...`,
      ])

      const curView = useChatStore.getState().activeView
      if (curView !== 'debate') {
        useChatStore.getState().notifyCompletedActivity({
          title: `${title} Ready`,
          message: `Specialist persona consensus synthesized for ${targetSymbol}.`,
          targetView: 'debate',
        })
      }
    } catch (err) {
      if (err.name !== 'AbortError' && !err.message?.includes('aborted')) {
        console.error('Failed to run live debate:', err)
        setError(err.message || 'Analysis timed out or failed to load. Please verify sidecar connection.')
      }
    } finally {
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
      clearTimeout(stepTimer1)
      clearTimeout(stepTimer2)
      clearTimeout(stepTimer3)
      setIsStreaming(false)
      setLoading(false)
      stopActivity()
    }
  }

  // Note: Analysis is triggered manually by user via 'Run Analysis' button
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        try {
          abortRef.current.abort()
        } catch (e) {}
      }
    }
  }, [])

  const handleSearch = (e) => {
    e.preventDefault()
    const clean = inputSymbol.trim().toUpperCase()
    if (clean) {
      setSymbol(clean)
      setInputSymbol('')
    }
  }

  const startLiveDebate = () => {
    executeDebate(symbol, selectedCouncil)
  }

  const score = selectedCouncil === 'debate'
    ? data?.conviction_score
    : councilData?.consensus_score
  const hasScore = score != null && Number.isFinite(Number(score))
  const bullCase = data?.bull_case || []
  const bearCase = data?.bear_case || []
  const consensus = data?.facilitator_consensus
  const ltp = data?.ltp || 0

  const councilSignals = councilData?.signals || []
  const councilVerdict = councilData?.consensus_verdict || 'UNAVAILABLE'
  const isCouncilBuy = councilVerdict.includes('BUY')
  const isCouncilSell = councilVerdict.includes('SELL')

  return (
    <div className="flex-1 overflow-y-auto p-2.5 sm:p-3.5 font-ui relative" style={{ background: 'var(--color-surface)', color: 'var(--color-text)' }}>
      {/* Top Header & Stock Switcher (Streamlined 36px) */}
      <div className="relative z-30 flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-1.5 mb-2 bg-panel border border-border shadow-card">
        <div className="flex items-center gap-2">
          <span className="text-base animate-gold-pulse text-amber-500">◆</span>
          <div>
            <h1 className="text-xs font-bold font-mono flex items-center gap-1.5 text-text">
              <span>{symbol}</span>
              {ltp > 0 && (
                <span className="text-[10px] px-1.5 py-0.2 rounded-full font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  ₹{Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              )}
            </h1>
          </div>
          <span className="text-[10px] text-muted hidden md:inline">• Multi-Agent Intelligence Hub (13 Specialists)</span>
        </div>

        {/* Quick Tickers & Action */}
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-1 overflow-x-auto">
            {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'COFORGE', 'TRENT'].map((sym) => (
              <button
                key={sym}
                onClick={() => setSymbol(sym)}
                className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold transition-all cursor-pointer ${
                  symbol === sym
                    ? 'bg-amber text-black shadow-xs'
                    : 'bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/50'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          <button
            onClick={startLiveDebate}
            disabled={isStreaming}
            className={`btn btn-sm py-1 px-3 text-xs font-bold transition-all cursor-pointer ${
              !data && !councilData && !isStreaming
                ? 'btn-emerald shadow-md ring-1 ring-emerald-400/50 animate-pulse'
                : 'btn-emerald'
            }`}
            title={`Run live multi-agent analysis for ${symbol}`}
          >
            <span>{isStreaming ? '🔄' : '⚡'}</span>
            <span>{isStreaming ? 'Polling...' : 'Run Analysis'}</span>
          </button>
        </div>
      </div>

      {/* Council Ensemble & Debate Mode Selector Bar */}
      <div className="tab-bar mb-2.5 py-1" style={{ gap: '4px', overflowX: 'auto' }}>
        {COUNCIL_MODES.map((mode) => {
          const isActive = selectedCouncil === mode.id
          return (
            <button
              key={mode.id}
              onClick={() => setSelectedCouncil(mode.id)}
              className={`tab-item whitespace-nowrap text-xs py-1 px-2.5 ${isActive ? 'active' : ''}`}
            >
              <span>{mode.icon}</span>
              <span>{mode.name}</span>
            </button>
          )
        })}
      </div>

      {/* Error / Timeout Notification Banner */}
      {error && !loading && (
        <div className="rounded-xl p-3 mb-3 border border-rose-500/40 bg-rose-500/10 flex items-center justify-between gap-3 text-xs animate-slide-up-fade">
          <div className="flex items-center gap-2 text-rose-400">
            <span className="text-base">⚠️</span>
            <span className="font-medium">{error}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => executeDebate(symbol, selectedCouncil)}
              className="px-3 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 font-bold border border-rose-500/30 transition-all cursor-pointer"
            >
              Retry
            </button>
            <button
              onClick={() => setError(null)}
              className="text-muted hover:text-text px-1 py-1"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Dynamic Multi-Agent Live Reasoning Banner */}
      {(isStreaming || loading) && (
        <div className="rounded-2xl p-4 animate-slide-up-fade space-y-4" style={{ background: 'var(--color-panel)', border: '1px solid rgba(245,166,35,0.5)', boxShadow: 'var(--glow-gold)' }}>
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-3" style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: '12px' }}>
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full" style={{ background: 'var(--color-gold)', opacity: 0.75 }} />
                <span className="relative inline-flex rounded-full h-3 w-3" style={{ background: 'var(--color-gold)' }} />
              </span>
              <div>
                <h3 className="text-sm font-bold font-mono" style={{ color: 'var(--color-text)' }}>
                  Polling {COUNCIL_MODES.find((c) => c.id === selectedCouncil)?.name || 'Council'} for {symbol}
                </h3>
                <span className="text-[11px]" style={{ color: 'var(--color-muted)' }}>
                  Dual-LLM Pipeline · Quantitative Edge Synthesis
                </span>
              </div>
            </div>
            <button
              onClick={() => {
                useChatStore.getState().cancelActiveActivity()
                setIsStreaming(false)
                setLoading(false)
              }}
              className="btn btn-sm btn-rose"
            >
              ⛔ Stop
            </button>
          </div>

          {/* ══ CINEMATIC HORIZONTAL PIPELINE STEPPER ══ */}
          <div className="relative">
            {/* Connector line */}
            <div className="absolute top-4 left-0 right-0 h-px" style={{ background: 'var(--color-border)' }} />
            <div
              className="absolute top-4 left-0 h-px animate-rotate-gradient"
              style={{
                background: 'linear-gradient(90deg, var(--color-gold), var(--color-emerald), var(--color-cyan))',
                width: `${Math.min(100, ((streamingSteps.length) / 4) * 100)}%`,
                transition: 'width 0.8s cubic-bezier(0.16,1,0.3,1)',
                boxShadow: '0 0 8px rgba(245,166,35,0.6)'
              }}
            />
            <div className="relative flex items-start justify-between gap-1">
              {[
                { id: 'init', icon: '⚡', label: 'INITIALIZE', sub: 'Pipeline start' },
                { id: 'quant', icon: '🔍', label: 'QUANTITATIVE', sub: 'VCP · SMC · OB' },
                { id: 'debate', icon: '🤖', label: 'DEBATE', sub: 'Bull ⚔ Bear' },
                { id: 'consensus', icon: '⚖️', label: 'CONSENSUS', sub: 'Fund Manager' },
              ].map((stage, idx) => {
                const stepCount = streamingSteps.length
                const isDone = idx < stepCount
                const isActive = idx === stepCount - 1
                return (
                  <div key={stage.id} className="flex flex-col items-center gap-1.5 flex-1 min-w-0">
                    {/* Stage dot */}
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center text-sm relative z-10 transition-all duration-500"
                      style={{
                        background: isDone
                          ? 'linear-gradient(135deg, var(--color-gold), #c47a00)'
                          : isActive
                          ? 'rgba(245,166,35,0.2)'
                          : 'var(--color-elevated)',
                        border: isDone
                          ? '2px solid var(--color-gold)'
                          : isActive
                          ? '2px solid rgba(245,166,35,0.6)'
                          : '2px solid var(--color-border)',
                        boxShadow: isDone ? 'var(--glow-gold)' : isActive ? '0 0 12px rgba(245,166,35,0.3)' : 'none',
                      }}
                    >
                      {isActive && !isDone ? (
                        <span className="w-2 h-2 rounded-full animate-ping" style={{ background: 'var(--color-gold)' }} />
                      ) : (
                        <span>{isDone ? '✓' : stage.icon}</span>
                      )}
                    </div>
                    <div className="text-center min-w-0 px-0.5">
                      <span
                        className="text-[9px] font-extrabold uppercase tracking-wider block truncate"
                        style={{ color: isDone || isActive ? 'var(--color-gold)' : 'var(--color-muted)' }}
                      >
                        {stage.label}
                      </span>
                      <span className="text-[8px] truncate block" style={{ color: 'var(--color-muted)' }}>
                        {isDone ? stage.sub : '...'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Advisory */}
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs" style={{ background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.2)', color: 'var(--color-gold)' }}>
            <span>💡</span>
            <span>Background running — navigate freely without interrupting analysis.</span>
          </div>

          {/* Animated shimmer bar */}
          <div className="relative h-0.5 w-full rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
            <div className="absolute inset-0 rounded-full animate-rotate-gradient" style={{ background: 'linear-gradient(90deg, var(--color-gold), var(--color-emerald), var(--color-cyan), var(--color-gold))', backgroundSize: '200% 100%', width: '100%' }} />
          </div>
        </div>
      )}

      {/* Conviction Gauge Banner (Top Center) */}
      {hasScore ? <div className="flex flex-col items-center justify-center py-2">
        <div className="relative w-48 h-28 flex flex-col items-center justify-end">
          <svg className="w-48 h-28 overflow-visible" viewBox="0 0 160 90">
            <path d="M 15 80 A 65 65 0 0 1 145 80" fill="none" stroke="var(--color-border)" strokeWidth="10" strokeLinecap="round" />
            <path
              d="M 15 80 A 65 65 0 0 1 145 80"
              fill="none"
              stroke="url(#convictionGradient2)"
              strokeWidth="10"
              strokeDasharray="204"
              strokeDashoffset={204 - (204 * score) / 100}
              strokeLinecap="round"
              style={{ transition: 'stroke-dashoffset 1s cubic-bezier(0.16,1,0.3,1)', filter: score >= 75 ? 'drop-shadow(0 0 8px rgba(0,214,143,0.6))' : score >= 55 ? 'drop-shadow(0 0 8px rgba(245,166,35,0.6))' : 'drop-shadow(0 0 8px rgba(255,79,123,0.6))' }}
            />
            <defs>
              <linearGradient id="convictionGradient2" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="var(--color-rose)" />
                <stop offset="50%" stopColor="var(--color-gold)" />
                <stop offset="100%" stopColor="var(--color-emerald)" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute top-8 flex flex-col items-center justify-center">
            <span className="text-3xl font-extrabold font-mono tabular-nums" style={{ color: 'var(--color-text)' }}>
              {score}<span className="text-sm font-normal" style={{ color: 'var(--color-muted)' }}>/100</span>
            </span>
            <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: score >= 75 ? 'var(--color-emerald)' : score >= 55 ? 'var(--color-gold)' : 'var(--color-rose)' }}>
              {score >= 75 ? 'HIGH CONVICTION' : score >= 55 ? 'MODERATE' : 'LOW CONVICTION'}
            </span>
          </div>
        </div>
      </div> : loading ? (
        <div className="mx-auto my-3 max-w-md rounded-xl border border-amber/40 bg-panel px-4 py-3 text-center text-xs text-amber flex items-center justify-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber animate-ping" />
          <span>Synthesizing multi-agent specialist consensus for {symbol}...</span>
        </div>
      ) : null}

      {/* Standby State when no analysis has been run yet */}
      {!data && !councilData && !loading && !isStreaming ? (
        <div className="flex flex-col items-center justify-center h-80 rounded-2xl border border-dashed border-border bg-panel/50 text-center p-6 my-4 shadow-sm font-ui">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-center text-2xl mb-3 shadow-inner">
            ⚔️
          </div>
          <h3 className="text-sm font-bold text-text">
            Multi-Agent Intelligence Standby
          </h3>
          <p className="text-xs text-muted mt-1.5 max-w-md leading-relaxed">
            Target stock: <strong className="text-text font-mono">{symbol}</strong> · Council Mode:{' '}
            <strong className="text-amber-500 font-mono">
              {COUNCIL_MODES.find((c) => c.id === selectedCouncil)?.name}
            </strong>
            . Click <strong className="text-emerald-500">Run Analysis</strong> when you are ready to initiate dual-LLM adversarial debate, Wyckoff/SMC order-block extractions, and multi-persona consensus.
          </p>
          <button
            type="button"
            onClick={startLiveDebate}
            className="mt-4 flex items-center gap-2 text-xs font-bold px-5 py-2.5 rounded-xl border border-emerald-500/40 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/25 shadow-md hover:shadow-emerald-500/10 transition-all cursor-pointer font-mono"
          >
            <span>⚡</span>
            <span>Run Analysis on {symbol}</span>
          </button>
        </div>
      ) : (
        <>
          {/* VIEW MODE 1: ADVERSARIAL BULL VS BEAR DEBATE */}
          {selectedCouncil === 'debate' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start relative animate-fade-slide">
          {/* Left Column (5 Cols): BULL CASE */}
          <div className="lg:col-span-5 space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm tracking-wide uppercase border-b border-emerald-500/30 pb-2">
              <span>↑</span>
              <span>BULL CASE (CONVICTION PILLARS)</span>
            </div>

            <div className="space-y-3">
              {bullCase.map((item, idx) => (
                <div
                  key={idx}
                  className="bg-panel border border-emerald-500/20 hover:border-emerald-500/40 rounded-2xl p-4 shadow-sm flex items-start gap-3.5 transition-all hover:bg-elevated/40"
                >
                  <div className="w-10 h-10 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-lg flex-shrink-0">
                    {item.avatar === 'robot-tech' && '📈'}
                    {item.avatar === 'robot-flow' && '🌊'}
                    {item.avatar === 'robot-inst' && '🏦'}
                  </div>
                  <div className="space-y-1">
                    <span className="text-xs font-bold text-emerald-400 tracking-wide uppercase block">
                      {item.title}
                    </span>
                    <p className="text-xs text-text/90 leading-relaxed font-ui">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Center Overlay Card: FACILITATOR CONSENSUS */}
          <div className="lg:col-span-2 flex flex-col items-center justify-center self-center z-10 my-2 lg:my-0">
            <div className="w-full bg-panel/95 border-2 border-emerald-500/50 rounded-2xl p-4 shadow-xl backdrop-blur-xl space-y-3.5 text-center">
              <div className="bg-emerald-500/20 text-emerald-400 text-[10px] font-extrabold uppercase py-1 px-3 rounded-full border border-emerald-500/40 inline-block tracking-wider">
                FACILITATOR CONSENSUS
              </div>

              <div>
                <span className="text-[10px] text-muted uppercase font-bold block mb-1">FINAL TRADE VERDICT</span>
                <span className="text-base font-black text-emerald-400 tracking-wide bg-emerald-500/10 px-3 py-1 rounded-xl border border-emerald-500/30 block">
                  {consensus?.verdict || 'UNAVAILABLE'}
                </span>
              </div>

              {/* Trade Levels Box */}
              <div className="bg-surface/90 border border-border/80 rounded-xl p-2.5 text-xs font-mono space-y-1.5 text-left">
                <div className="flex justify-between">
                  <span className="text-muted">ENTRY:</span>
                  <span className="font-bold text-emerald-400">
                    {consensus?.entry != null
                      ? `₹${Number(consensus.entry).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">STOP-LOSS:</span>
                  <span className="font-bold text-red">
                    {consensus?.stop_loss != null
                      ? `₹${Number(consensus.stop_loss).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">TARGET:</span>
                  <span className="font-bold text-text">
                    {consensus?.target != null
                      ? `₹${Number(consensus.target).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between border-t border-border/50 pt-1 text-[11px]">
                  <span className="text-muted">R:R RATIO:</span>
                  <span className="font-bold text-amber">{consensus?.risk_reward ? `${consensus.risk_reward} R` : '—'}</span>
                </div>
              </div>

            </div>
          </div>

          {/* Right Column (5 Cols): BEAR CASE */}
          <div className="lg:col-span-5 space-y-4">
            <div className="flex items-center gap-2 text-rose-400 font-bold text-sm tracking-wide uppercase border-b border-rose-500/30 pb-2">
              <span>BEAR CASE (RISK AUDIT)</span>
              <span>↓</span>
            </div>

            <div className="space-y-3">
              {bearCase.map((item, idx) => (
                <div
                  key={idx}
                  className="bg-panel border border-rose-500/20 hover:border-rose-500/40 rounded-2xl p-4 shadow-sm flex items-start gap-3.5 transition-all hover:bg-elevated/40"
                >
                  <div className="w-10 h-10 rounded-full bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-lg flex-shrink-0">
                    {item.avatar === 'robot-forensic' && '🔍'}
                    {item.avatar === 'robot-val' && '📊'}
                    {item.avatar === 'robot-news' && '📰'}
                  </div>
                  <div className="space-y-1">
                    <span className="text-xs font-bold text-rose-400 tracking-wide uppercase block">
                      {item.title}
                    </span>
                    <p className="text-xs text-text/90 leading-relaxed font-ui">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* VIEW MODE 2: SPECIALIST COUNCIL ENSEMBLE */}
      {selectedCouncil !== 'debate' && (
        <div className="bg-panel border border-border/80 rounded-2xl p-5 shadow-sm space-y-4 animate-fade-slide">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
            <div>
              <span className="text-[10px] uppercase font-bold text-muted font-ui tracking-wider block">
                Council Ensemble Poll Results
              </span>
              <h2 className="text-base font-bold text-text font-ui">
                {COUNCIL_MODES.find(c => c.id === selectedCouncil)?.name} on {symbol}
              </h2>
            </div>

            <div className="flex items-center gap-3">
              <span className={`px-3 py-1 rounded-xl text-xs uppercase font-extrabold ${
                isCouncilBuy ? 'bg-emerald-500 text-black' : isCouncilSell ? 'bg-rose-500 text-white' : 'bg-amber text-black'
              }`}>
                {councilVerdict}
              </span>
            </div>
          </div>

          {/* Members Breakdown Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {councilSignals.map((sig) => {
              const pid = sig.persona?.toLowerCase() || ''
              const pName = PERSONA_NAMES[pid] || sig.persona
              const isSigBuy = sig.verdict?.includes('BUY')
              const isSigSell = sig.verdict?.includes('SELL')
              const isExpanded = expandedMember === pid

              const verdictColor = isSigBuy
                ? { bg: 'rgba(0,214,143,0.12)', border: 'rgba(0,214,143,0.35)', text: 'var(--color-emerald)' }
                : isSigSell
                ? { bg: 'rgba(255,79,123,0.12)', border: 'rgba(255,79,123,0.35)', text: 'var(--color-rose)' }
                : { bg: 'rgba(245,166,35,0.12)', border: 'rgba(245,166,35,0.35)', text: 'var(--color-gold)' }

              const PERSONA_ICONS = {
                buffett: '🏛️', munger: '🔭', lynch: '🎯', jhunjhunwala: '🦁',
                kedia: '💡', minervini: '🚀', wyckoff: '📊', oneil: '📈',
                taleb: '🌊', simons: '🤖', smc: '🎪', forensic: '🔍', soros: '🌐',
              }

              return (
                <div key={pid} className="persona-card-container" style={{ height: '160px' }}>
                  <div className="persona-card-inner">

                    {/* FRONT: Identity + Verdict + Confidence */}
                    <div
                      className="persona-card-front p-4 flex flex-col justify-between"
                      style={{ background: 'var(--color-elevated)', border: `1px solid ${verdictColor.border}` }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <span className="text-2xl">{PERSONA_ICONS[pid] || '🧠'}</span>
                          <div>
                            <div className="font-black text-xs" style={{ color: 'var(--color-text)' }}>{pName}</div>
                            <div className="text-[9px] mt-0.5 font-mono" style={{ color: 'var(--color-muted)' }}>
                              {sig.confidence}% confidence
                            </div>
                          </div>
                        </div>
                        <span
                          className="text-[9px] px-2 py-0.5 rounded-md font-black"
                          style={{ background: verdictColor.bg, color: verdictColor.text, border: `1px solid ${verdictColor.border}` }}
                        >
                          {sig.verdict}
                        </span>
                      </div>

                      {/* Confidence bar */}
                      <div className="mt-2">
                        <div className="h-1 rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${sig.confidence || 0}%`, background: verdictColor.text }}
                          />
                        </div>
                      </div>

                      {sig.rationale?.[0] && (
                        <p className="text-[10px] mt-2 leading-relaxed line-clamp-2" style={{ color: 'var(--color-muted)' }}>
                          {sig.rationale[0]}
                        </p>
                      )}

                      <div className="text-[8px] mt-2 text-center" style={{ color: 'var(--color-muted)' }}>
                        Hover to see full analysis ↻
                      </div>
                    </div>

                    {/* BACK: Full rationale + key metrics */}
                    <div
                      className="persona-card-back p-3.5 overflow-y-auto flex flex-col gap-2"
                      style={{ background: 'var(--color-panel)', border: `1px solid ${verdictColor.border}` }}
                    >
                      <div className="text-[9px] font-black uppercase tracking-widest mb-1" style={{ color: verdictColor.text }}>
                        {PERSONA_ICONS[pid] || '🧠'} {pName} — Signals
                      </div>
                      <div className="space-y-1">
                        {(sig.rationale || []).slice(0, 4).map((r, i) => (
                          <div key={i} className="flex items-start gap-1.5 text-[10px]" style={{ color: 'var(--color-text)' }}>
                            <span style={{ color: verdictColor.text }}>•</span>
                            <span className="leading-snug">{r}</span>
                          </div>
                        ))}
                      </div>
                      {sig.key_metrics && typeof sig.key_metrics === 'object' && Object.keys(sig.key_metrics).length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-1">
                          {Object.entries(sig.key_metrics).slice(0, 4).map(([k, v]) => (
                            <span key={k} className="px-1.5 py-0.5 rounded text-[8px] font-mono" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}>
                              {k}: <strong style={{ color: 'var(--color-text)' }}>{String(v)}</strong>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
        </>
      )}

      {/* Bottom Footer Bar with Provenance */}
      <div className="flex flex-wrap items-center justify-between text-xs font-mono text-muted border-t border-border/50 pt-4 px-2">
        <div className="flex items-center gap-2">
          <span>Multi-Agent Framework:</span>
          <span className="text-emerald-400 font-bold">13 Institutional Personas & 5 Councils</span>
          <span className="text-muted">•</span>
          <span className="text-text">Fast LLM + Deep NIM Dual Routing</span>
        </div>
        <div>
          <span>As of: </span>
          <span className="text-text font-semibold">{data?.timestamp || new Date().toLocaleTimeString('en-IN') + ' IST'}</span>
        </div>
      </div>
    </div>
  )
}
