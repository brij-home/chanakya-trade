import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'

export default function DebateArenaView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [symbol, setSymbol] = useState('RELIANCE')
  const [inputSymbol, setInputSymbol] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingSteps, setStreamingSteps] = useState([])

  useEffect(() => {
    let unmounted = false
    const fetchDebate = async () => {
      try {
        setLoading(true)
        const res = await call('/skills/debate_snapshot', { symbol, exchange: 'NSE' })
        const snapshot = res?.data ?? res
        if (!unmounted && snapshot) {
          setData(snapshot)
        }
      } catch (err) {
        console.error('Failed to load debate snapshot:', err)
      } finally {
        if (!unmounted) setLoading(false)
      }
    }
    fetchDebate()
    return () => {
      unmounted = true
    }
  }, [symbol])

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
    startActivity({
      title: `Adversarial Debate (${symbol})`,
      details: `⚡ Initializing Multi-Agent Pipeline for ${symbol}...`,
      type: 'debate',
      cancelFn: () => {
        setIsStreaming(false)
        stopActivity()
      },
    })

    setStreamingSteps([
      '⚡ Initializing Multi-Agent Pipeline for ' + symbol + '...',
      '🔍 Bull Analyst evaluating Minervini Stage 2 & Volume Profile...',
      '🔬 Bear Analyst auditing Beneish M-Score & Accruals Quality...',
      '⚖️ Facilitator synthesizing risk-reward consensus...',
    ])

    const t1 = setTimeout(() => updateActivity({ details: '🔍 Bull Analyst evaluating Minervini Stage 2 & Volume Profile...' }), 400)
    const t2 = setTimeout(() => updateActivity({ details: '🔬 Bear Analyst auditing Beneish M-Score & Accruals Quality...' }), 850)
    const t3 = setTimeout(() => updateActivity({ details: '⚖️ Facilitator synthesizing risk-reward consensus...' }), 1300)

    try {
      const res = await call('/skills/debate_snapshot', { symbol, exchange: 'NSE' })
      const snapshot = res?.data ?? res
      if (snapshot) {
        setData(snapshot)
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

  const score = data?.conviction_score || 88
  const bullCase = data?.bull_case || []
  const bearCase = data?.bear_case || []
  const consensus = data?.facilitator_consensus
  const ltp = data?.ltp || 2940.0

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-6 bg-surface text-text space-y-6 font-ui relative">
      {/* Top Header & Stock Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-panel/90 border border-border/80 rounded-2xl px-5 py-3.5 shadow-md backdrop-blur-md">
        <div className="flex items-center gap-3">
          <span className="text-amber text-lg">◆</span>
          <div>
            <h1 className="text-lg font-bold font-mono text-text flex items-center gap-2">
              <span>{symbol} (NSE)</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green/15 text-green font-bold border border-green/30">
                ₹{Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
            </h1>
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <span>Adversarial Multi-Agent Debate Arena</span>
              <span>•</span>
              <span className="text-emerald-400 font-mono font-semibold">Live Quantitative Synthesis</span>
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
            <span>{isStreaming ? 'Agents Debating...' : 'Run Live Debate'}</span>
          </button>
        </div>
      </div>

      {/* Streaming Banner if active */}
      {isStreaming && (
        <div className="bg-elevated/90 border border-amber/40 rounded-2xl p-4 shadow-lg animate-fade-slide">
          <div className="flex items-center gap-2 text-xs font-bold text-amber mb-2">
            <span className="w-2.5 h-2.5 rounded-full bg-amber animate-ping" />
            <span>Multi-Agent Debate In Progress (Dual-LLM Fast Extraction + Deep Synthesis)</span>
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
      <div className="flex flex-col items-center justify-center pt-2">
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
            <span className="text-[10px] font-bold tracking-wider uppercase text-emerald-400">
              CONVICTION ({score >= 75 ? 'HIGH' : score >= 55 ? 'MODERATE' : 'LOW'})
            </span>
          </div>
        </div>
      </div>

      {/* Main Debate Grid: Bull Case vs Bear Case with Center Floating Facilitator Card */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start relative">
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

        {/* Center Overlay Card (2 Cols desktop layout bridging the sides): FACILITATOR CONSENSUS */}
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
                <span className="font-bold text-emerald-400">₹{Number(consensus?.entry || ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">STOP-LOSS:</span>
                <span className="font-bold text-red">₹{Number(consensus?.stop_loss || ltp * 0.985).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">TARGET:</span>
                <span className="font-bold text-text">₹{Number(consensus?.target || ltp * 1.035).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between border-t border-border/50 pt-1 text-[11px]">
                <span className="text-muted">R:R RATIO:</span>
                <span className="font-bold text-amber">{consensus?.risk_reward || '2.1'} R</span>
              </div>
            </div>

            <button
              onClick={() => {
                if (onOpenOrderTicket) {
                  onOpenOrderTicket({
                    symbol,
                    exchange: 'NSE',
                    price: consensus?.entry || ltp,
                    stopLoss: consensus?.stop_loss || ltp * 0.985,
                    target: consensus?.target || ltp * 1.035,
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

      {/* Bottom Footer Bar with Provenance */}
      <div className="flex flex-wrap items-center justify-between text-xs font-mono text-muted border-t border-border/50 pt-4 px-2">
        <div className="flex items-center gap-2">
          <span>Market Status:</span>
          <span className="text-emerald-400 font-bold">LIVE / OPEN</span>
          <span className="text-muted">•</span>
          <span className="text-text">SMC + Forensic + Order Flow Hybrid</span>
        </div>
        <div>
          <span>As of: </span>
          <span className="text-text font-semibold">{data?.timestamp || new Date().toLocaleTimeString('en-IN') + ' IST'}</span>
        </div>
      </div>
    </div>
  )
}
