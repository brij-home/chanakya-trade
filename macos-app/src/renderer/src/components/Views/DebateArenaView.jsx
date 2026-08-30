import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'

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
  const [selectedCouncil, setSelectedCouncil] = useState('debate')
  const [data, setData] = useState(null)
  const [councilData, setCouncilData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState([])
  const [expandedMember, setExpandedMember] = useState(null)

  useEffect(() => {
    let unmounted = false
    const fetchData = async () => {
      try {
        setLoading(true)
        if (selectedCouncil === 'debate') {
          const res = await call('/skills/debate_snapshot', { symbol, exchange: 'NSE' })
          const snapshot = res?.data ?? res
          if (!unmounted && snapshot) {
            setData(snapshot)
          }
        } else {
          const res = await call('/skills/persona/council', { symbol, council: selectedCouncil, exchange: 'NSE' })
          const cSnapshot = res?.data ?? res
          if (!unmounted && cSnapshot) {
            setCouncilData(cSnapshot)
          }
        }
      } catch (err) {
        console.error('Failed to load snapshot:', err)
      } finally {
        if (!unmounted) setLoading(false)
      }
    }
    fetchData()
    return () => {
      unmounted = true
    }
  }, [symbol, selectedCouncil])

  const handleSearch = (e) => {
    e.preventDefault()
    const clean = inputSymbol.trim().toUpperCase()
    if (clean) {
      setSymbol(clean)
      setInputSymbol('')
    }
  }

  const startActivity = useChatStore((s) => s.startActivity)
  const updateActivity = useChatStore((s) => s.updateActivity)
  const stopActivity = useChatStore((s) => s.stopActivity)

  const startLiveDebate = async () => {
    setIsStreaming(true)
    const isCouncil = selectedCouncil !== 'debate'
    const title = isCouncil
      ? `${COUNCIL_MODES.find(c => c.id === selectedCouncil)?.name || 'Council'} (${symbol})`
      : `Adversarial Debate (${symbol})`

    startActivity({
      title,
      details: `⚡ Initializing Multi-Agent Pipeline for ${symbol}...`,
      type: 'debate',
      cancelFn: () => {
        setIsStreaming(false)
        stopActivity()
      },
    })

    setStreamingSteps([
      '⚡ Initializing Multi-Agent Pipeline for ' + symbol + '...',
      '🔍 Specialists extracting quantitative edge metrics...',
      '🔬 Persona agents debating invalidation and risk parameters...',
      '⚖️ Synthesizing high-conviction consensus score...',
    ])

    const t1 = setTimeout(() => updateActivity({ details: '🔍 Specialists extracting quantitative edge metrics...' }), 400)
    const t2 = setTimeout(() => updateActivity({ details: '🔬 Persona agents debating invalidation and risk parameters...' }), 850)
    const t3 = setTimeout(() => updateActivity({ details: '⚖️ Synthesizing high-conviction consensus score...' }), 1300)

    try {
      if (selectedCouncil === 'debate') {
        const res = await call('/skills/debate_snapshot', { symbol, exchange: 'NSE' })
        const snapshot = res?.data ?? res
        if (snapshot) setData(snapshot)
      } else {
        const res = await call('/skills/persona/council', { symbol, council: selectedCouncil, exchange: 'NSE' })
        const cSnapshot = res?.data ?? res
        if (cSnapshot) setCouncilData(cSnapshot)
      }
    } catch (err) {
      console.error('Failed to run live debate:', err)
    } finally {
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
      setTimeout(() => {
        setIsStreaming(false)
        stopActivity()
      }, 1500)
    }
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
    <div className="flex-1 overflow-y-auto p-3 sm:p-6 bg-surface text-text space-y-5 font-ui relative">
      {/* Top Header & Stock Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-panel/90 border border-border/80 rounded-2xl px-5 py-3.5 shadow-md backdrop-blur-md">
        <div className="flex items-center gap-3">
          <span className="text-amber text-lg">◆</span>
          <div>
            <h1 className="text-lg font-bold font-mono text-text flex items-center gap-2">
              <span>{symbol} (NSE)</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green/15 text-green font-bold border border-green/30">
                {ltp > 0 ? `₹${Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : 'Live Stream'}
              </span>
            </h1>
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <span>Institutional Multi-Agent Intelligence Hub</span>
              <span>•</span>
              <span className="text-emerald-400 font-mono font-semibold">13 Specialist Personas</span>
            </div>
          </div>
        </div>

        {/* Quick Tickers & Search */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Quick Tickers Chips */}
          <div className="flex items-center gap-1 overflow-x-auto">
            {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'COFORGE', 'TRENT'].map((sym) => (
              <button
                key={sym}
                onClick={() => setSymbol(sym)}
                className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold transition-all cursor-pointer ${
                  symbol === sym
                    ? 'bg-amber text-black shadow-xs ring-1 ring-amber/40'
                    : 'bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/60'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {/* Search Custom Symbol Input */}
          <form onSubmit={handleSearch} className="flex items-center gap-1">
            <input
              type="text"
              placeholder="Custom symbol..."
              value={inputSymbol}
              onChange={(e) => setInputSymbol(e.target.value)}
              className="bg-surface border border-border/70 rounded-xl px-2.5 py-1.5 text-xs text-text placeholder:text-muted/60 focus:outline-none focus:border-amber font-mono w-28 uppercase"
            />
            <button
              type="submit"
              className="px-2.5 py-1.5 rounded-xl bg-elevated hover:bg-elevated/80 border border-border text-xs text-text font-bold cursor-pointer"
            >
              Go
            </button>
          </form>

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

      {/* Streaming Banner if active */}
      {isStreaming && (
        <div className="bg-elevated/90 border border-amber/40 rounded-2xl p-4 shadow-lg animate-fade-slide">
          <div className="flex items-center gap-2 text-xs font-bold text-amber mb-2">
            <span className="w-2.5 h-2.5 rounded-full bg-amber animate-ping" />
            <span>Multi-Agent Synthesis In Progress (Fast Extraction + Deep Reasoning)</span>
          </div>
          <div className="space-y-1 font-mono text-xs text-muted">
            {streamingSteps.map((step, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <span className="text-green">✓</span>
                <span>{step}</span>
              </div>
            ))}
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
              stroke="rgba(255,255,255,0.1)"
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
                      <span className="text-[10px] text-muted">({sig.confidence}% conf)</span>
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
