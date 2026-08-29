import { useEffect, useRef, useState } from 'react'
import { useChatStore, getActiveSymbol } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import Message from './Message'

const DEFAULT_TICKERS = [
  { symbol: 'NIFTY', name: 'NIFTY 50', cmd: 'quote NIFTY', tag: 'INDEX', ltp: 0, change_pct: 0 },
  { symbol: 'BANKNIFTY', name: 'BANK NIFTY', cmd: 'quote BANKNIFTY', tag: 'INDEX', ltp: 0, change_pct: 0 },
  { symbol: 'COFORGE', name: 'Coforge Ltd', cmd: 'analyze COFORGE', tag: 'READY', ltp: 0, change_pct: 0 },
  { symbol: 'TRENT', name: 'Trent Ltd', cmd: 'analyze TRENT', tag: 'STAGE 2', ltp: 0, change_pct: 0 },
  { symbol: 'RELIANCE', name: 'Reliance Ind', cmd: 'analyze RELIANCE', tag: 'LARGE CAP', ltp: 0, change_pct: 0 },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', cmd: 'analyze HDFCBANK', tag: 'LARGE CAP', ltp: 0, change_pct: 0 },
  { symbol: 'TCS', name: 'Tata Consultancy', cmd: 'analyze TCS', tag: 'LARGE CAP', ltp: 0, change_pct: 0 },
  { symbol: 'INFY', name: 'Infosys Ltd', cmd: 'analyze INFY', tag: 'LARGE CAP', ltp: 0, change_pct: 0 },
]

export default function ChatArea() {
  const messages = useChatStore((s) => s.messages)
  const isLoading = useChatStore((s) => s.isLoading)
  const sidecarError = useChatStore((s) => s.sidecarError)
  const port = useChatStore((s) => s.port)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const showDashboard = useChatStore((s) => s.showDashboard)
  const setShowDashboard = useChatStore((s) => s.setShowDashboard)
  const createSession = useChatStore((s) => s.createSession)
  const activeSessionId = useChatStore((s) => s.activeSessionId)
  const sessions = useChatStore((s) => s.sessions)
  const activeSymbol = getActiveSymbol(messages)
  const bottomRef = useRef(null)

  const { call } = useAPI()
  const [trendingTickers, setTrendingTickers] = useState(DEFAULT_TICKERS)
  const [trendingLoading, setTrendingLoading] = useState(false)

  // Fetch dynamic trending market movers on mount
  useEffect(() => {
    let unmounted = false
    const fetchTrending = async () => {
      try {
        setTrendingLoading(true)
        const res = await call('/skills/trending', { limit: 10 })
        const data = res?.data ?? res
        if (!unmounted && data?.items && data.items.length > 0) {
          setTrendingTickers(data.items)
        }
      } catch {
        // Fall back gracefully to DEFAULT_TICKERS
      } finally {
        if (!unmounted) setTrendingLoading(false)
      }
    }
    fetchTrending()
    return () => {
      unmounted = true
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const isDashboardVisible = messages.length === 0 || showDashboard

  const quickPrompts = [
    {
      icon: '⚡',
      title: activeSymbol ? `Multi-Agent Debate (${activeSymbol})` : 'Multi-Agent Stock Debate',
      desc: '7 quant agents analyze technicals, fundamentals & trade plans.',
      cmd: activeSymbol ? `analyze ${activeSymbol}` : 'analyze RELIANCE',
    },
    {
      icon: '🎯',
      title: activeSymbol ? `Strategy Payoff (${activeSymbol})` : 'Options Strategy Payoff',
      desc: 'Interactive multi-leg simulator with live Greeks & DTE sliders.',
      cmd: activeSymbol ? `payoff ${activeSymbol}` : 'payoff NIFTY',
    },
    {
      icon: '🔍',
      title: 'Sector Breadth & Scanner',
      desc: 'Live NSE sector heatmap and unusual volume/OI breakouts.',
      cmd: 'scan',
    },
    {
      icon: '🌊',
      title: 'FII / DII Institutional Flows',
      desc: 'Daily institutional cash & derivative positioning breakdown.',
      cmd: 'flows',
    },
    {
      icon: '🌅',
      title: 'Morning Market Brief',
      desc: 'Pre-market snapshot, global cues, VIX posture & macro events.',
      cmd: 'brief',
    },
    {
      icon: '🧪',
      title: activeSymbol ? `Backtest Strategy (${activeSymbol})` : 'Algorithmic Backtesting',
      desc: 'Test RSI, EMA, and Bollinger Bands with equity progression curves.',
      cmd: activeSymbol ? `backtest ${activeSymbol} rsi` : 'backtest RELIANCE rsi',
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-5 bg-surface text-text">
      {/* Active Navigation Header (when in Chat / Cards view) */}
      {!isDashboardVisible && (
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 bg-surface/90 backdrop-blur border-b border-border/60 pb-3 mb-2 text-xs font-ui">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowDashboard(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-panel hover:bg-elevated border border-border text-text font-medium transition-colors cursor-pointer shadow-xs"
              title="Return to Home / Overview Dashboard"
            >
              <span>🏠</span>
              <span>Dashboard</span>
            </button>
            <div className="h-4 w-[1px] bg-border/80" />
            <span className="text-muted text-[11px] font-mono truncate max-w-[140px] sm:max-w-[200px]">
              {sessions[activeSessionId]?.title || 'Analysis'}
            </span>
          </div>

          {/* Quick Jump Launchers */}
          <div className="flex items-center gap-1.5 overflow-x-auto">
            <button
              onClick={() => window.dispatchEvent(new CustomEvent('open-top-opportunities'))}
              className="px-2.5 py-1 rounded-lg bg-green/10 hover:bg-green/20 text-green border border-green/30 text-[11px] font-semibold flex items-center gap-1 cursor-pointer transition-colors flex-shrink-0"
              title="Open Market-Aware High-Conviction Radar"
            >
              <span>🎯</span>
              <span className="hidden sm:inline">Top</span> Radar
            </button>
            <button
              onClick={() => sendDraft('scan')}
              className="px-2.5 py-1 rounded-lg bg-panel hover:bg-elevated text-text border border-border text-[11px] font-medium flex items-center gap-1 cursor-pointer transition-colors flex-shrink-0"
              title="Launch NSE Breadth & Breakout Heatmap"
            >
              <span>🌐</span>
              <span className="hidden sm:inline">Sector</span> Breadth
            </button>
            <button
              onClick={() => sendDraft('flows')}
              className="px-2.5 py-1 rounded-lg bg-panel hover:bg-elevated text-text border border-border text-[11px] font-medium flex items-center gap-1 cursor-pointer transition-colors flex-shrink-0"
              title="Track Institutional FII/DII Flows"
            >
              <span>🌊</span>
              <span>Flows</span>
            </button>
            <button
              onClick={() => sendDraft('brief')}
              className="px-2.5 py-1 rounded-lg bg-panel hover:bg-elevated text-text border border-border text-[11px] font-medium flex items-center gap-1 cursor-pointer transition-colors flex-shrink-0"
              title="Generate Morning Market Brief"
            >
              <span>🌅</span>
              <span className="hidden sm:inline">Morning</span> Brief
            </button>
            <button
              onClick={createSession}
              className="p-1.5 rounded-lg bg-panel hover:bg-elevated text-muted hover:text-text border border-border text-[11px] cursor-pointer transition-colors flex-shrink-0"
              title="New Analysis Session (⌘N)"
            >
              ＋
            </button>
          </div>
        </div>
      )}

      {/* Welcome Dashboard Overview */}
      {isDashboardVisible && (
        <div className="max-w-4xl mx-auto flex flex-col items-center justify-center min-h-[75vh] py-8 text-center space-y-6 animate-fade-slide">
          {/* If there are existing messages in session, show resume button */}
          {messages.length > 0 && (
            <div className="w-full flex items-center justify-between bg-elevated/80 border border-border px-4 py-2.5 rounded-xl shadow-xs">
              <div className="flex items-center gap-2 text-xs font-ui text-left">
                <span className="w-2 h-2 rounded-full bg-green animate-pulse" />
                <span className="text-text font-semibold">{sessions[activeSessionId]?.title || 'Active Session'}</span>
                <span className="text-muted">({messages.length} analysis cards loaded)</span>
              </div>
              <button
                onClick={() => setShowDashboard(false)}
                className="px-3 py-1.5 bg-amber hover:bg-amber-light text-black font-bold rounded-lg text-xs font-ui cursor-pointer transition-colors shadow-xs"
              >
                ← Return to Active View
              </button>
            </div>
          )}

          {/* Logo & Headline */}
          <div className="space-y-2">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-amber/10 border border-amber/30 text-amber text-2xl shadow-sm mb-1">
              ◆
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold font-ui tracking-tight text-text">
              Institutional Trading &amp; AI Intelligence
            </h1>
            <p className="text-sm font-ui text-muted max-w-xl mx-auto leading-relaxed">
              Real-time Indian market analytics, multi-agent quant debates, options payoff simulation, and institutional flow tracking.
            </p>
          </div>

          {/* Dynamic Trending / Market Movers Bar (1-Click Instant Execution) */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1 max-w-3xl">
            <span className="text-xs text-muted font-ui mr-1 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber animate-pulse" />
              <span className="font-semibold text-text">Trending Movers:</span>
            </span>
            {trendingTickers.map((ticker) => {
              const label = ticker.symbol || ticker.label
              const cmd = ticker.cmd || `analyze ${label}`
              const ltp = ticker.ltp
              const changePct = ticker.change_pct
              const tag = ticker.tag

              return (
                <button
                  key={label}
                  onClick={() => sendDraft(cmd)}
                  className="group inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-mono bg-panel hover:bg-elevated text-text border border-border/80 hover:border-amber/50 transition-all cursor-pointer shadow-xs hover:scale-102"
                  title={`Instant 1-click execution: ${cmd}`}
                >
                  <span className="font-bold text-amber group-hover:text-amber-light">{label}</span>
                  {ltp > 0 && (
                    <span className="text-[10px] text-muted hidden sm:inline">₹{Number(ltp).toLocaleString('en-IN')}</span>
                  )}
                  {changePct !== undefined && changePct !== 0 && (
                    <span className={`text-[10px] font-semibold ${Number(changePct) >= 0 ? 'text-green' : 'text-red'}`}>
                      {Number(changePct) >= 0 ? '+' : ''}{Number(changePct).toFixed(1)}%
                    </span>
                  )}
                  {tag && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-amber/10 text-amber border border-amber/20 hidden md:inline font-semibold">
                      {tag}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Quick Action Grid (1-Click Instant Execution) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 w-full text-left pt-2">
            {quickPrompts.map((item) => (
              <button
                key={item.title}
                onClick={() => sendDraft(item.cmd)}
                className="group relative p-4 rounded-xl bg-panel hover:bg-elevated border border-border/80 hover:border-amber/40 transition-all duration-200 shadow-xs hover:shadow-md cursor-pointer flex flex-col justify-between"
                title={`Launch ${item.title}`}
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xl p-2 rounded-lg bg-surface border border-border/50">{item.icon}</span>
                    <span className="text-[10px] font-mono text-muted group-hover:text-amber transition-colors flex items-center gap-0.5">
                      <span>{item.cmd}</span>
                      <span>⚡</span>
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold font-ui text-text group-hover:text-amber transition-colors">
                    {item.title}
                  </h3>
                  <p className="text-xs text-muted font-ui mt-1 leading-relaxed">
                    {item.desc}
                  </p>
                </div>
              </button>
            ))}
          </div>

          {/* Status Note */}
          {sidecarError ? (
            <p className="text-red text-xs font-ui max-w-sm mt-4 bg-red/10 border border-red/20 px-3 py-1.5 rounded-lg">
              {sidecarError}
            </p>
          ) : (
            <p className="text-muted text-xs font-ui pt-2">
              Tip: Press <kbd className="px-1.5 py-0.5 rounded bg-panel border border-border font-mono text-amber font-semibold">Ctrl + K</kbd> to search any of the 2,000+ NSE stocks or commands.
            </p>
          )}
        </div>
      )}

      {/* Message list (when in chat view) */}
      {!isDashboardVisible && messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}

      {/* Loading indicator */}
      {isLoading && !messages.some((m) => m.cardType === 'streaming_analysis') && (
        <ThinkingIndicator />
      )}

      <div ref={bottomRef} />
    </div>
  )
}

function ThinkingIndicator() {
  const [secs, setSecs] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const hint =
    secs > 15
      ? 'Running multi-agent analysis — synthesizing insights…'
      : secs > 5
      ? 'Calling quantitative AI reasoning agents…'
      : 'Computing institutional metrics…'

  return (
    <div className="flex items-center gap-3 bg-elevated border border-border rounded-xl px-4 py-3 max-w-sm shadow-md animate-fade-slide">
      <span className="text-amber animate-pulse text-lg">◆</span>
      <div>
        <p className="text-text text-sm font-ui font-medium">{hint}</p>
        <p className="text-muted text-xs font-mono mt-0.5">{secs}s elapsed</p>
      </div>
    </div>
  )
}
