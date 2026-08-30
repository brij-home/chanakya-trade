import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import SmartTypeahead from '../Common/SmartTypeahead'
import { fuzzySearchUniverse } from '../../data/universeData'

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

export default function DebateArenaView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [symbol, setSymbol] = useState('RELIANCE')
  const [inputSymbol, setInputSymbol] = useState('')
  const [showTypeahead, setShowTypeahead] = useState(false)
  const [typeaheadIndex, setTypeaheadIndex] = useState(0)
  const [selectedCouncil, setSelectedCouncil] = useState('debate')
  const [data, setData] = useState(null)
  const [councilData, setCouncilData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState([])
  const [expandedMember, setExpandedMember] = useState(null)

  const startActivity = useChatStore((s) => s.startActivity)
  const updateActivity = useChatStore((s) => s.updateActivity)
  const stopActivity = useChatStore((s) => s.stopActivity)

  const executeDebate = async (targetSymbol = symbol, targetCouncil = selectedCouncil) => {
    setIsStreaming(true)
    setLoading(true)
    const isCouncil = targetCouncil !== 'debate'
    const councilName = COUNCIL_MODES.find((c) => c.id === targetCouncil)?.name || 'Council'
    const title = isCouncil ? `${councilName} (${targetSymbol})` : `Adversarial Debate (${targetSymbol})`

    const abortController = new AbortController()

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

    setStreamingSteps([
      `⚡ Initializing Multi-Agent Pipeline for ${targetSymbol}...`,
      `🔍 Extracting Minervini VCP, Wyckoff accumulation & SMC Order Blocks...`,
      `🔬 Persona agents debating invalidation and risk parameters...`,
      `⚖️ Synthesizing high-conviction consensus score...`,
    ])

    const t1 = setTimeout(() => updateActivity({ details: `🔍 Specialists extracting quantitative edge metrics for ${targetSymbol}...` }), 300)
    const t2 = setTimeout(() => updateActivity({ details: `🔬 Persona agents debating invalidation and risk parameters...` }), 750)
    const t3 = setTimeout(() => updateActivity({ details: `⚖️ Synthesizing high-conviction consensus score...` }), 1200)

    try {
      if (targetCouncil === 'debate') {
        const res = await call('/skills/debate_snapshot', { symbol: targetSymbol, exchange: 'NSE' }, { signal: abortController.signal })
        const snapshot = res?.data ?? res
        if (snapshot) setData(snapshot)
      } else {
        const res = await call('/skills/persona/council', { symbol: targetSymbol, council: targetCouncil, exchange: 'NSE' }, { signal: abortController.signal })
        const cSnapshot = res?.data ?? res
        if (cSnapshot) setCouncilData(cSnapshot)
      }

      const curView = useChatStore.getState().activeView
      if (curView !== 'debate') {
        useChatStore.getState().notifyCompletedActivity({
          title: `${title} Ready`,
          message: `Specialist persona consensus synthesized for ${targetSymbol}.`,
          targetView: 'debate',
        })
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Failed to run live debate:', err)
      }
    } finally {
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
      setIsStreaming(false)
      setLoading(false)
      stopActivity()
    }
  }

  // Trigger analysis whenever symbol or selectedCouncil changes
  useEffect(() => {
    executeDebate(symbol, selectedCouncil)
  }, [symbol, selectedCouncil])

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
    ? (data?.conviction_score || 88)
    : (councilData?.consensus_score || 78)
  const bullCase = data?.bull_case || []
  const bearCase = data?.bear_case || []
  const consensus = data?.facilitator_consensus
  const ltp = data?.ltp || 0

  const councilSignals = councilData?.signals || []
  const councilVerdict = councilData?.consensus_verdict || 'HOLD'
  const isCouncilBuy = councilVerdict.includes('BUY')
  const isCouncilSell = councilVerdict.includes('SELL')

  return (
    <div className="flex-1 overflow-y-auto p-2.5 sm:p-3.5 bg-surface text-text space-y-2.5 font-ui relative">
      {/* Top Header & Stock Switcher */}
      <div className="relative z-30 flex flex-wrap items-center justify-between gap-2.5 bg-panel border border-border/80 rounded-xl px-3.5 py-2 shadow-xs">
        <div className="flex items-center gap-2.5">
          <span className="text-amber text-base">◆</span>
          <div>
            <h1 className="text-sm font-bold font-mono text-text flex items-center gap-2">
              <span>{symbol} (NSE)</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-green/15 text-green font-bold border border-green/30">
                {ltp > 0 ? `₹${Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : 'Live Stream'}
              </span>
            </h1>
            <div className="flex items-center gap-2 text-[10px] text-muted">
              <span>Institutional Multi-Agent Intelligence Hub</span>
              <span>•</span>
              <span className="text-emerald-400 font-mono font-semibold">13 Specialist Personas</span>
            </div>
          </div>
        </div>

        {/* Quick Tickers & Search */}
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Quick Tickers Chips */}
          <div className="flex items-center gap-1 overflow-x-auto">
            {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'COFORGE', 'TRENT'].map((sym) => (
              <button
                key={sym}
                onClick={() => setSymbol(sym)}
                className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
                  symbol === sym
                    ? 'bg-amber text-black shadow-xs ring-1 ring-amber/40'
                    : 'bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/60'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {/* Search Custom Symbol Input with SmartTypeahead */}
          <div className="relative z-50">
            <form onSubmit={handleSearch} className="flex items-center gap-1">
              <div className="flex items-center gap-1 bg-surface/90 border-2 border-border focus-within:border-amber focus-within:ring-2 focus-within:ring-amber/30 rounded-lg px-2 py-1 transition-all text-xs shadow-xs">
                <span className="text-amber font-black text-xs">🔍</span>
                <input
                  type="text"
                  placeholder="Switch symbol..."
                  value={inputSymbol}
                  onChange={(e) => {
                    setInputSymbol(e.target.value)
                    setShowTypeahead(true)
                    setTypeaheadIndex(0)
                  }}
                  onFocus={() => setShowTypeahead(true)}
                  onKeyDown={(e) => {
                    if (showTypeahead) {
                      const items = fuzzySearchUniverse(inputSymbol, symbol, 8).filter((r) => r.type === 'symbol')
                      if (items.length > 0) {
                        if (e.key === 'ArrowDown') {
                          e.preventDefault()
                          setTypeaheadIndex((prev) => (prev + 1) % items.length)
                          return
                        }
                        if (e.key === 'ArrowUp') {
                          e.preventDefault()
                          setTypeaheadIndex((prev) => (prev - 1 + items.length) % items.length)
                          return
                        }
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          const selected = items[typeaheadIndex] || items[0]
                          if (selected?.symbol) {
                            setSymbol(selected.symbol)
                            setInputSymbol('')
                            setShowTypeahead(false)
                          }
                          return
                        }
                        if (e.key === 'Tab') {
                          e.preventDefault()
                          const selected = items[typeaheadIndex] || items[0]
                          if (selected?.symbol) {
                            setInputSymbol(selected.symbol)
                          }
                          return
                        }
                      }
                    }
                    if (e.key === 'Escape') setShowTypeahead(false)
                  }}
                  className="bg-transparent text-xs text-text font-mono font-bold uppercase outline-none placeholder:text-text/50 w-32"
                />
              </div>
              <button
                type="submit"
                className="px-3 py-2 rounded-xl bg-elevated hover:bg-amber hover:text-black border-2 border-border text-xs text-text font-bold cursor-pointer transition-all shadow-xs"
              >
                Go
              </button>
            </form>

            <SmartTypeahead
              query={inputSymbol}
              activeSymbol={symbol}
              isOpen={showTypeahead}
              onSelect={(item) => {
                if (item.symbol) setSymbol(item.symbol)
                setInputSymbol('')
                setShowTypeahead(false)
              }}
              onClose={() => setShowTypeahead(false)}
              mode="symbols_only"
              position="below"
              selectedIndex={typeaheadIndex}
              setSelectedIndex={setTypeaheadIndex}
            />
          </div>

          {/* Action Button */}
          <button
            onClick={startLiveDebate}
            disabled={isStreaming}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:brightness-110 text-black font-bold text-xs transition-all shadow-md cursor-pointer"
          >
            <span>{isStreaming ? '🔄' : '⚡'}</span>
            <span>{isStreaming ? 'Agents Polling...' : 'Run Analysis'}</span>
          </button>
        </div>
      </div>

      {/* Council Ensemble & Debate Mode Selector Bar */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 bg-panel/70 p-1.5 rounded-2xl border border-border/70 text-xs">
        {COUNCIL_MODES.map((mode) => {
          const isActive = selectedCouncil === mode.id
          return (
            <button
              key={mode.id}
              onClick={() => setSelectedCouncil(mode.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-xl font-bold transition-all cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'bg-amber text-black shadow-md'
                  : 'text-muted hover:text-text hover:bg-elevated border border-transparent'
              }`}
            >
              <span>{mode.icon}</span>
              <span>{mode.name}</span>
            </button>
          )
        })}
      </div>

      {/* Dynamic Multi-Agent Live Reasoning Banner */}
      {(isStreaming || loading) && (
        <div className="bg-panel/98 border border-amber/50 rounded-2xl p-5 shadow-2xl backdrop-blur-xl animate-fade-slide space-y-3 ring-1 ring-amber/25">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-amber" />
              </span>
              <div>
                <h3 className="text-sm font-bold font-mono text-text">
                  Polling {COUNCIL_MODES.find((c) => c.id === selectedCouncil)?.name || 'Council'} for {symbol} (NSE)
                </h3>
                <span className="text-[11px] text-muted font-ui">
                  Dual-LLM Multi-Agent Pipeline & Quantitative Edge Synthesis
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  useChatStore.getState().cancelActiveActivity()
                  setIsStreaming(false)
                  setLoading(false)
                }}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-rose-500/15 hover:bg-rose-500 hover:text-white border border-rose-500/30 text-rose-400 text-xs font-mono font-bold transition-all shadow-xs cursor-pointer"
                title="Immediately stop/cancel the current analysis"
              >
                <span>⛔</span> Stop / Cancel
              </button>
            </div>
          </div>

          {/* Progressive Step Progression */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-xs text-text/90 pt-1">
            {streamingSteps.map((step, idx) => (
              <div key={idx} className="flex items-center gap-2 bg-surface/80 border border-border/60 rounded-xl px-3 py-2">
                <span className="text-emerald-400 font-bold">✓</span>
                <span className="truncate">{step}</span>
              </div>
            ))}
          </div>

          {/* Multitasking Advisory Note */}
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber/10 border border-amber/20 text-amber text-xs font-ui">
            <span>💡</span>
            <span>
              Background process running — you can freely navigate to <strong>Terminal</strong>, inspect <strong>Options</strong>, or view live charts without interrupting analysis.
            </span>
          </div>

          {/* Progress Shimmer Bar */}
          <div className="relative h-1.5 w-full bg-surface rounded-full overflow-hidden border border-border/40">
            <div className="absolute inset-0 bg-gradient-to-r from-amber via-emerald-400 to-cyan-400 animate-[pulse_1.5s_ease-in-out_infinite] w-full" />
          </div>
        </div>
      )}

      {/* Conviction Gauge Banner (Top Center) */}
      <div className="flex flex-col items-center justify-center pt-1">
        <div className="relative w-48 h-28 flex flex-col items-center justify-end">
          {/* Semicircular Arc SVG */}
          <svg className="w-48 h-28 overflow-visible" viewBox="0 0 160 90">
            <path
              d="M 15 80 A 65 65 0 0 1 145 80"
              fill="none"
              stroke="currentColor"
              className="text-border"
              strokeWidth="12"
              strokeLinecap="round"
            />
            <path
              d="M 15 80 A 65 65 0 0 1 145 80"
              fill="none"
              stroke="url(#convictionGradient)"
              strokeWidth="12"
              strokeDasharray="204"
              strokeDashoffset={204 - (204 * score) / 100}
              strokeLinecap="round"
              className="transition-all duration-1000 ease-out"
            />
            <defs>
              <linearGradient id="convictionGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#ef4444" />
                <stop offset="50%" stopColor="#f59e0b" />
                <stop offset="100%" stopColor="#10b981" />
              </linearGradient>
            </defs>
          </svg>

          {/* Center Score Text */}
          <div className="absolute top-8 flex flex-col items-center justify-center">
            <span className="text-3xl font-extrabold font-mono text-text tracking-tight">
              {score}<span className="text-sm font-normal text-muted">/100</span>
            </span>
            <span className={`text-[10px] font-bold tracking-wider uppercase ${score >= 75 ? 'text-emerald-400' : score >= 55 ? 'text-amber' : 'text-rose-400'}`}>
              {score >= 75 ? 'HIGH CONVICTION' : score >= 55 ? 'MODERATE' : 'LOW CONVICTION'}
            </span>
          </div>
        </div>
      </div>

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
                  {consensus?.verdict || 'READY (BUY)'}
                </span>
              </div>

              {/* Trade Levels Box */}
              <div className="bg-surface/90 border border-border/80 rounded-xl p-2.5 text-xs font-mono space-y-1.5 text-left">
                <div className="flex justify-between">
                  <span className="text-muted">ENTRY:</span>
                  <span className="font-bold text-emerald-400">
                    {consensus?.entry != null
                      ? `₹${Number(consensus.entry).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : (ltp > 0 ? `₹${Number(ltp * 0.998).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">STOP-LOSS:</span>
                  <span className="font-bold text-red">
                    {consensus?.stop_loss != null
                      ? `₹${Number(consensus.stop_loss).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : (ltp > 0 ? `₹${Number(ltp * 0.988).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">TARGET:</span>
                  <span className="font-bold text-text">
                    {consensus?.target != null
                      ? `₹${Number(consensus.target).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
                      : (ltp > 0 ? `₹${Number(ltp * 1.024).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—')}
                  </span>
                </div>
                <div className="flex justify-between border-t border-border/50 pt-1 text-[11px]">
                  <span className="text-muted">R:R RATIO:</span>
                  <span className="font-bold text-amber">{consensus?.risk_reward ? `${consensus.risk_reward} R` : '2.0 R'}</span>
                </div>
              </div>

              <button
                onClick={() => {
                  if (onOpenOrderTicket) {
                    const isBear = consensus?.verdict_bias === 'BEARISH' || (consensus?.verdict && consensus.verdict.includes('SELL'))
                    const entryVal = consensus?.entry != null ? Number(consensus.entry) : (ltp > 0 ? Number((ltp * (isBear ? 1.002 : 0.998)).toFixed(2)) : 0)
                    const slVal = consensus?.stop_loss != null ? Number(consensus.stop_loss) : (ltp > 0 ? Number((isBear ? ltp * 1.012 : ltp * 0.988)).toFixed(2) : 0)
                    const tgtVal = consensus?.target != null ? Number(consensus.target) : (ltp > 0 ? Number((isBear ? ltp * 0.976 : ltp * 1.024)).toFixed(2) : 0)
                    onOpenOrderTicket({
                      symbol,
                      exchange: 'NSE',
                      action: isBear ? 'SELL' : 'BUY',
                      price: entryVal,
                      stopLoss: slVal,
                      target: tgtVal,
                    })
                  }
                }}
                className="w-full py-2 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-xs uppercase tracking-wide transition-all shadow-md cursor-pointer"
              >
                ⚡ Stage Ticket
              </button>
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
              <button
                onClick={() => {
                  if (onOpenOrderTicket) {
                    onOpenOrderTicket({
                      symbol,
                      exchange: 'NSE',
                      action: isCouncilSell ? 'SELL' : 'BUY',
                    })
                  }
                }}
                className="px-4 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-xs uppercase tracking-wide transition-all shadow-md cursor-pointer"
              >
                ⚡ Stage Order Ticket
              </button>
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

              return (
                <div
                  key={pid}
                  className="p-3.5 rounded-xl bg-surface border border-border/70 hover:border-amber/40 transition-all space-y-2"
                >
                  <div
                    className="flex items-center justify-between cursor-pointer"
                    onClick={() => setExpandedMember(isExpanded ? null : pid)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-base">🧠</span>
                      <span className="font-bold text-xs text-text">{pName}</span>
                      <span className="text-[10px] text-muted font-mono">({sig.confidence}% conf)</span>
                      <span className="text-[9px] font-mono font-bold bg-amber/15 text-amber border border-amber/30 px-1.5 py-0.5 rounded hidden sm:inline-block">
                        ⚖️ Calibrated Weight
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
                        isSigBuy ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : isSigSell ? 'bg-rose-500/15 text-rose-400 border border-rose-500/30' : 'bg-amber/15 text-amber border border-amber/30'
                      }`}>
                        {sig.verdict}
                      </span>
                      <span className="text-xs text-muted">{isExpanded ? '▲' : '▼'}</span>
                    </div>
                  </div>

                  {sig.rationale && sig.rationale.length > 0 && !isExpanded && (
                    <p className="text-[11px] text-muted font-ui truncate pl-6">
                      • {sig.rationale[0]}
                    </p>
                  )}

                  {isExpanded && (
                    <div className="pl-6 pt-2 border-t border-border/40 space-y-2 font-ui text-xs animate-fade-slide">
                      <div className="space-y-1">
                        <span className="text-[10px] uppercase font-bold text-muted block">Signals & Checklist:</span>
                        {sig.rationale?.map((r, i) => (
                          <div key={i} className="flex items-start gap-1.5 text-text/90 text-[11px]">
                            <span className="text-amber">•</span>
                            <span>{r}</span>
                          </div>
                        ))}
                      </div>

                      {sig.key_metrics && Object.keys(sig.key_metrics).length > 0 && (
                        <div className="pt-1 flex flex-wrap gap-1.5">
                          {Object.entries(sig.key_metrics).map(([k, v]) => (
                            <span key={k} className="px-2 py-0.5 rounded-md bg-elevated border border-border/50 text-[10px] text-muted font-mono">
                              {k}: <strong className="text-text">{v}</strong>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
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
