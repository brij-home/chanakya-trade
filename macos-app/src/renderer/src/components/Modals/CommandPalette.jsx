import { useState, useEffect, useRef } from 'react'
import { useChatStore, getActiveSymbol } from '../../store/chatStore'

const POPULAR_SYMBOLS = [
  { symbol: 'NIFTY50', name: 'NIFTY 50 Index', type: 'Index' },
  { symbol: 'BANKNIFTY', name: 'NIFTY Bank Index', type: 'Index' },
  { symbol: 'FINNIFTY', name: 'NIFTY Financial Services', type: 'Index' },
  { symbol: 'RELIANCE', name: 'Reliance Industries', type: 'Energy' },
  { symbol: 'HDFCBANK', name: 'HDFC Bank Ltd', type: 'Banking' },
  { symbol: 'TCS', name: 'Tata Consultancy Services', type: 'IT' },
  { symbol: 'INFY', name: 'Infosys Ltd', type: 'IT' },
  { symbol: 'ICICIBANK', name: 'ICICI Bank Ltd', type: 'Banking' },
  { symbol: 'TATAMOTORS', name: 'Tata Motors Ltd', type: 'Auto' },
  { symbol: 'SBIN', name: 'State Bank of India', type: 'PSU Bank' },
  { symbol: 'BHARTIARTL', name: 'Bharti Airtel', type: 'Telecom' },
  { symbol: 'ITC', name: 'ITC Ltd', type: 'FMCG' },
  { symbol: 'LT', name: 'Larsen & Toubro', type: 'Infra' },
]

export default function CommandPalette({ isOpen, onClose, onOpenOrderTicket }) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const messages = useChatStore((s) => s.messages)
  const activeSymbol = getActiveSymbol(messages)
  const inputRef = useRef(null)

  const quickActions = [
    { label: 'Morning Market Brief & Macro Posture', cmd: 'brief', icon: '🌅', cat: 'Intelligence' },
    { label: `High-Probability Big Move Predictor (${activeSymbol || 'NIFTY'})`, cmd: `bigmove ${activeSymbol || 'NIFTY'}`, icon: '🚀', cat: 'Prediction' },
    { label: 'Top 10 High-Conviction Opportunity Radar', cmd: 'radar', icon: '🎯', cat: 'Screening' },
    { label: `Smart Funnel Multi-Agent Screening (${activeSymbol ? activeSymbol : 'NIFTY 50'})`, cmd: activeSymbol ? `funnel ${activeSymbol}` : 'funnel nifty_50', icon: '🎯', cat: 'Screening' },
    { label: `Market Structure & Smart Money Concepts (${activeSymbol || 'RELIANCE'})`, cmd: `structure ${activeSymbol || 'RELIANCE'}`, icon: '🏛️', cat: 'Price Action' },
    { label: `Multibagger & Minervini Trend Template (${activeSymbol || 'TRENT'})`, cmd: `multibagger ${activeSymbol || 'TRENT'}`, icon: '💎', cat: 'Positional' },
    { label: `Sector Relative Rotation Graph (${activeSymbol ? activeSymbol + ' Momentum' : 'RRG Matrix'})`, cmd: activeSymbol ? `rrg ${activeSymbol}` : 'rrg', icon: '🌐', cat: 'Quant' },
    { label: `Forensic Accounting & Governance Audit (${activeSymbol || 'RELIANCE'})`, cmd: `forensic ${activeSymbol || 'RELIANCE'}`, icon: '🛡️', cat: 'Forensic' },
    { label: `Position Lifecycle & Dynamic Trailing SL (${activeSymbol || 'RELIANCE'})`, cmd: `lifecycle ${activeSymbol || 'RELIANCE'} 2400 2340`, icon: '📡', cat: 'Management' },
    { label: `Volatility Risk-Parity & Position Sizer (${activeSymbol || 'NIFTY'})`, cmd: `size ${activeSymbol || 'NIFTY'} 24000 23600`, icon: '⚖️', cat: 'Risk' },
    { label: 'FII / DII Institutional Flows & Signals', cmd: 'flows', icon: '🌊', cat: 'Intelligence' },
    { label: `Options Open Interest Profile (${activeSymbol || 'NIFTY'})`, cmd: `oi ${activeSymbol || 'NIFTY'}`, icon: '📊', cat: 'Options' },
    { label: `Multi-Leg Strategy Payoff Simulator (${activeSymbol || 'NIFTY'})`, cmd: `payoff ${activeSymbol || 'NIFTY'}`, icon: '🎯', cat: 'Options' },
    { label: 'Live Market Scanner & Heatmap', cmd: 'scan', icon: '🔍', cat: 'Screening' },
    { label: 'Institutional Risk & Greeks Report', cmd: 'risk-report', icon: '🛡️', cat: 'Risk' },
    { label: 'View Active Holdings & Portfolio Margin', cmd: 'holdings', icon: '💼', cat: 'Portfolio' },
    { label: `Backtest Strategy (${activeSymbol || 'RELIANCE'} rsi)`, cmd: `backtest ${activeSymbol || 'RELIANCE'} rsi`, icon: '🧪', cat: 'Quant' },
  ]

  // Focus input on open
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  if (!isOpen) return null

  // Filter actions and symbols
  const filteredActions = quickActions.filter(
    (a) => a.label.toLowerCase().includes(query.toLowerCase()) || a.cmd.toLowerCase().includes(query.toLowerCase())
  )

  const filteredSymbols = POPULAR_SYMBOLS.filter(
    (s) => s.symbol.toLowerCase().includes(query.toLowerCase()) || s.name.toLowerCase().includes(query.toLowerCase())
  )

  const allItems = [
    ...filteredActions.map((a) => ({ type: 'action', ...a })),
    ...filteredSymbols.map((s) => ({ type: 'symbol', ...s })),
  ]

  const executeQuery = (text) => {
    const cleanText = (text || query).trim()
    if (!cleanText) return
    sendDraft(cleanText)
    onClose()
  }

  const selectItem = (item) => {
    if (item.type === 'action') {
      sendDraft(item.cmd)
    } else if (item.type === 'symbol') {
      sendDraft(`analyze ${item.symbol}`)
    }
    onClose()
  }

  const handleFormSubmit = (e) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }
    const cleanQuery = query.trim()
    const item = allItems[selectedIndex]
    if (cleanQuery) {
      executeQuery(cleanQuery)
    } else if (item) {
      selectItem(item)
    }
  }

  // Keyboard navigation handler
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((idx) => (idx + 1) % (allItems.length || 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((idx) => (idx - 1 + (allItems.length || 1)) % (allItems.length || 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      handleFormSubmit()
    } else if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/75 backdrop-blur-xs p-4 select-none"
      onClick={onClose}
    >
      <div
        className="bg-panel border border-border rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl font-ui"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Bar Form */}
        <form
          onSubmit={handleFormSubmit}
          className="flex items-center gap-2.5 px-4 py-3.5 border-b border-border/60 bg-panel/30"
        >
          <span className="text-amber text-base flex-shrink-0">🔍</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a command, tool, or NSE stock name… (e.g. funnel nifty_50, analyze INFY, brief)"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
            className="w-full bg-transparent border-none outline-none text-text text-sm font-ui placeholder:text-muted"
          />
          {query.trim() ? (
            <button
              type="submit"
              onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onClick={handleFormSubmit}
              className="px-2.5 py-1 rounded-lg bg-amber hover:bg-amber-light active:scale-95 text-black font-ui font-bold text-xs cursor-pointer transition-all shadow-xs flex-shrink-0 flex items-center gap-1"
              title="Execute command immediately"
            >
              <span>Send</span>
              <span>↵</span>
            </button>
          ) : (
            <kbd className="hidden sm:inline text-[10px] bg-panel border border-border px-1.5 py-0.5 rounded text-muted flex-shrink-0">
              ESC
            </kbd>
          )}
        </form>

        {/* Results List */}
        <div className="max-h-80 overflow-y-auto p-2 space-y-1">
          {filteredActions.length > 0 && (
            <div>
              <p className="text-muted text-[10px] uppercase font-ui tracking-wider px-2 py-1">Quick Actions</p>
              {filteredActions.map((action, idx) => {
                const isSelected = selectedIndex === idx
                return (
                  <button
                    key={action.cmd}
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                    }}
                    onClick={() => selectItem({ type: 'action', ...action })}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left text-xs transition-colors cursor-pointer ${
                      isSelected ? 'bg-amber/15 text-text border border-amber/30' : 'text-text hover:bg-panel/60'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="text-sm">{action.icon}</span>
                      <span className="font-semibold">{action.label}</span>
                    </div>
                    <code className="text-[10px] text-amber bg-panel px-1.5 py-0.5 rounded font-mono border border-border/50">
                      {action.cmd}
                    </code>
                  </button>
                )
              })}
            </div>
          )}

          {filteredSymbols.length > 0 && (
            <div className="pt-2 border-t border-border/30">
              <p className="text-muted text-[10px] uppercase font-ui tracking-wider px-2 py-1">Popular Equities &amp; Indices</p>
              {filteredSymbols.map((sym, idx) => {
                const actualIdx = filteredActions.length + idx
                const isSelected = selectedIndex === actualIdx
                return (
                  <button
                    key={sym.symbol}
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                    }}
                    onClick={() => selectItem({ type: 'symbol', ...sym })}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left text-xs transition-colors cursor-pointer ${
                      isSelected ? 'bg-amber/15 text-text border border-amber/30' : 'text-text hover:bg-panel/60'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="font-mono font-bold text-amber">{sym.symbol}</span>
                      <span className="text-muted text-[11px]">{sym.name}</span>
                    </div>
                    <span className="text-[10px] text-muted bg-panel px-1.5 py-0.5 rounded border border-border/50">
                      {sym.type}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {allItems.length === 0 && (
            <div className="p-3 text-center">
              {query.trim() ? (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                  }}
                  onClick={() => executeQuery(query.trim())}
                  className="w-full flex items-center justify-between p-3 rounded-xl bg-amber/15 hover:bg-amber/25 border border-amber/40 text-left transition-all cursor-pointer group shadow-sm"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg">⚡</span>
                    <div>
                      <p className="text-xs font-semibold text-text group-hover:text-amber">
                        Execute Custom Command or Prompt
                      </p>
                      <p className="text-xs font-mono text-amber font-bold">
                        {query.trim()}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs font-bold bg-amber text-black px-2.5 py-1 rounded-lg">Execute ↵</span>
                </button>
              ) : (
                <div className="text-muted text-xs font-ui py-4">
                  Type any command (e.g. <span className="text-amber font-mono">funnel nifty_50</span>, <span className="text-amber font-mono">analyze INFY</span>) or stock name.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-border/40 bg-panel/40 flex items-center justify-between text-[10px] text-muted font-ui">
          <span>Navigate with <kbd className="bg-panel px-1 rounded border border-border">↑</kbd> <kbd className="bg-panel px-1 rounded border border-border">↓</kbd></span>
          <span>Select or execute with <kbd className="bg-panel px-1 rounded border border-border">↵ Enter</kbd></span>
        </div>
      </div>
    </div>
  )
}
