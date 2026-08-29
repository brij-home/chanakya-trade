import { useState, useRef, useEffect } from 'react'
import { useChatStore, getBaseUrl, getActiveSymbol } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'

// Maps typed commands → API endpoint + card type
function parseCommand(input, contextSymbol = null) {
  const parts = input.trim().split(/\s+/)
  const cmd   = parts[0].toLowerCase()
  const args  = parts.slice(1)

  switch (cmd) {
    case 'quote': case 'q': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol (e.g. quote INFY)' }
      return { endpoint: '/skills/quote', body: { symbol: sym }, cardType: 'quote' }
    }

    case 'analyze': case 'analyse': case 'a': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol to analyze (e.g. analyze INFY)' }
      return { stream: true, symbol: sym, exchange: args[1]?.toUpperCase() ?? 'NSE' }
    }

    case 'morning-brief': case 'brief': case 'mb':
      return { endpoint: '/skills/morning_brief', body: {}, cardType: 'morning_brief' }

    case 'flows': case 'flow':
      return { endpoint: '/skills/flows', body: {}, cardType: 'flows' }

    case 'holdings': case 'h':
      return { endpoint: '/skills/holdings', body: {}, cardType: 'holdings' }

    case 'positions': case 'pos':
      return { endpoint: '/skills/positions', body: {}, cardType: 'holdings' }

    case 'backtest': case 'bt': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol for backtesting (e.g. backtest INFY rsi)' }
      return {
        endpoint: '/skills/backtest',
        body: { symbol: sym, strategy: args[1] || 'rsi' },
        cardType: 'backtest',
      }
    }

    case 'macro':
      return { endpoint: '/skills/macro', body: {}, cardType: 'markdown' }

    case 'earnings':
      return { endpoint: '/skills/earnings', body: { symbols: args.length > 0 ? args : (contextSymbol ? [contextSymbol] : []) }, cardType: 'markdown' }

    // ── High-value additions ──────────────────────────────────

    case 'deep-analyze': case 'deep-analyse': case 'da': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol (e.g. deep-analyze INFY)' }
      return {
        endpoint: '/skills/deep_analyze',
        body: { symbol: sym, exchange: args[1]?.toUpperCase() ?? 'NSE' },
        cardType: 'markdown',
      }
    }

    case 'funds': case 'fund':
      return { endpoint: '/skills/funds', body: {}, cardType: 'funds' }

    case 'profile':
      return { endpoint: '/skills/profile', body: {}, cardType: 'profile' }

    case 'orders': case 'order':
      return { endpoint: '/skills/orders', body: {}, cardType: 'orders' }

    case 'alerts': case 'al':
      return { endpoint: '/skills/alerts/list', body: {}, cardType: 'alerts' }

    case 'alert':
      // alert SYMBOL above/below PRICE
      // alert remove ID
      if (args[0] === 'remove' || args[0] === 'rm') {
        if (!args[1]) return { error: 'Usage: alert remove ALERT_ID' }
        return { endpoint: '/skills/alerts/remove', body: { alert_id: args[1] }, cardType: 'markdown' }
      }
      if (args.length < 3) return { error: 'Usage: alert SYMBOL above|below PRICE' }
      return {
        endpoint: '/skills/alerts/add',
        body: {
          symbol:    args[0].toUpperCase(),
          condition: args[1].toLowerCase(),   // above / below / crosses
          threshold: Number(args[2]),
        },
        cardType: 'markdown',
      }

    case 'oi': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      return {
        endpoint: '/skills/oi_profile',
        body: { symbol: sym, exchange: args[1]?.toUpperCase() ?? 'NSE' },
        cardType: 'oi',
      }
    }

    case 'patterns': case 'pat':
      return { endpoint: '/skills/patterns', body: {}, cardType: 'patterns' }

    case 'greeks': case 'greek':
      return { endpoint: '/skills/greeks', body: {}, cardType: 'greeks' }

    case 'scan':
      return {
        endpoint: '/skills/scan',
        body: { scan_type: args[0] ?? 'options', filters: {} },
        cardType: 'scan',
      }

    case 'deals': case 'bulk-deals':
      return {
        endpoint: '/skills/deals',
        body: { symbol: args[0]?.toUpperCase() || contextSymbol || null, days: 5 },
        cardType: 'deals',
      }

    case 'iv-smile': case 'smile': case 'ivsmile': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      return { endpoint: '/skills/iv_smile', body: { symbol: sym, expiry: args[1] ?? null }, cardType: 'iv_smile' }
    }
    case 'gex': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      return { endpoint: '/skills/gex', body: { symbol: sym, expiry: args[1] ?? null }, cardType: 'gex' }
    }
    case 'delta-hedge': case 'dh': case 'deltahedge':
      return { endpoint: '/skills/delta_hedge', body: {}, cardType: 'delta_hedge' }
    case 'risk-report': case 'risk': case 'var':
      return { endpoint: '/skills/risk_report', body: {}, cardType: 'risk_report' }
    case 'walkforward': case 'wf': case 'walk-forward': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      const strat = args[1] ?? 'rsi'
      return { endpoint: '/skills/walkforward', body: { symbol: sym, strategy: strat, window_months: 6 }, cardType: 'walkforward' }
    }
    case 'whatif': case 'what-if': case 'scenario': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      const chg = parseFloat(args[1])
      if (sym && (sym === 'NIFTY' || sym === 'MARKET') && !isNaN(chg)) {
        return { endpoint: '/skills/whatif', body: { scenario: 'market', nifty_change: chg }, cardType: 'whatif' }
      } else if (sym && !isNaN(chg)) {
        return { endpoint: '/skills/whatif', body: { scenario: 'stock', symbol: sym, stock_change: chg }, cardType: 'whatif' }
      }
      return { endpoint: '/skills/whatif', body: { scenario: 'market' }, cardType: 'whatif' }
    }
    case 'strategy': case 'strat': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      const view = (args[1] ?? 'bullish').toUpperCase()
      const dte = parseInt(args[2]) || 30
      return { endpoint: '/skills/strategy', body: { symbol: sym, view, dte }, cardType: 'strategy' }
    }
    case 'payoff': case 'sim': case 'simulator': {
      const sym = args[0]?.toUpperCase() || contextSymbol || 'NIFTY'
      return { endpoint: '/skills/quote', body: { symbol: sym }, cardType: 'payoff' }
    }
    case 'drift':
      return { endpoint: '/skills/drift', body: {}, cardType: 'drift' }
    case 'memory': case 'mem':
      return { endpoint: '/skills/memory', body: {}, cardType: 'memory' }
    case 'audit': {
      const trade_id = args[0]
      if (!trade_id) return { endpoint: '/skills/memory', body: {}, cardType: 'memory' }
      return { endpoint: '/skills/audit', body: { trade_id }, cardType: 'audit' }
    }
    case 'telegram': case 'tg':
      return { endpoint: '/skills/telegram/status', body: null, cardType: 'telegram', method: 'GET' }
    case 'provider': {
      if (args[0]) {
        return { endpoint: '/skills/provider/switch', body: { provider: args[0], model: args[1] ?? null }, cardType: 'provider' }
      }
      return { endpoint: '/skills/provider', body: {}, cardType: 'provider' }
    }
    case 'rrg': case 'sector-rotation': case 'rotation': {
      const sym = args[0]?.toUpperCase() || contextSymbol || null
      return { endpoint: '/skills/rrg', body: { symbol: sym }, cardType: 'rrg' }
    }
    case 'forensic': case 'forensics': case 'fa': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol for forensic audit (e.g. forensic INFY or forensic TCS)' }
      return { endpoint: '/skills/forensic', body: { symbol: sym }, cardType: 'forensic' }
    }
    case 'size': case 'position-size': case 'sizing': {
      const sym = (args[0] || contextSymbol || 'NIFTY').toUpperCase()
      const entry = parseFloat(args[1]) || (sym === 'NIFTY' ? 24000 : 2000)
      const sl = parseFloat(args[2]) || null
      return { endpoint: '/skills/position_size', body: { symbol: sym, entry_price: entry, stop_loss: sl }, cardType: 'size' }
    }
    case 'funnel': case 'smart-funnel': case 'smartfunnel': {
      const syms = args[0] || (contextSymbol ? contextSymbol : 'nifty_50')
      return { endpoint: '/skills/funnel', body: { symbols: syms, top_n: 2 }, cardType: 'funnel' }
    }
    case 'structure': case 'market-structure': case 'smc': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol for SMC analysis (e.g. structure INFY)' }
      return { endpoint: '/skills/market_structure', body: { symbol: sym }, cardType: 'structure' }
    }
    case 'multibagger': case 'vcp': case 'stage2': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol for Minervini/Weinstein Stage 2 scan (e.g. multibagger TRENT)' }
      return { endpoint: '/skills/multibagger', body: { symbol: sym }, cardType: 'multibagger' }
    }
    case 'lifecycle': case 'trade-lifecycle': case 'trail': {
      const sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol for lifecycle tracking (e.g. lifecycle INFY 1800 1740)' }
      const entry = parseFloat(args[1]) || 2400
      const sl = parseFloat(args[2]) || (entry * 0.97)
      return { endpoint: '/skills/lifecycle', body: { symbol: sym, entry_price: entry, initial_stop_loss: sl }, cardType: 'lifecycle' }
    }
    case 'vpa': case 'volume-profile': {
      const sym = (args[0] || contextSymbol || 'NIFTY').toUpperCase()
      return { endpoint: '/skills/volume_profile', body: { symbol: sym }, cardType: 'markdown' }
    }
    case 'top10': case 'top-10': case 'conviction': case 'radar': {
      const u = args[0] || 'auto_market_aware'
      const refresh = args.includes('--refresh') || args.includes('-r')
      return { endpoint: '/skills/top_conviction', body: { universe: u, top_n: 10, refresh }, cardType: 'top_conviction' }
    }
    case 'bigmove': case 'big_move': case 'big-move': case 'squeeze': {
      const sym = (args[0] || contextSymbol || 'NIFTY').toUpperCase()
      return { endpoint: '/skills/big_move', body: { symbol: sym }, cardType: 'big_move' }
    }

    default:
      // Fall through to AI chat — session_id injected in submit()
      return { endpoint: '/skills/chat', body: { message: input }, cardType: 'markdown' }
  }
}

export default function InputBar() {
  const [value, setValue]   = useState('')
  const { call, get, ready } = useAPI()
  const port     = useChatStore((s) => s.port)
  const activeSessionId   = useChatStore((s) => s.activeSessionId)
  const draft             = useChatStore((s) => s.draft)
  const setDraft          = useChatStore((s) => s.setDraft)
  const autoSubmit        = useChatStore((s) => s.autoSubmit)
  const clearAutoSubmit   = useChatStore((s) => s.clearAutoSubmit)
  const streamCancel      = useChatStore((s) => s.streamCancel)
  const activeStreamId    = useChatStore((s) => s.activeStreamId)
  const setPendingContext = useChatStore((s) => s.setPendingContext)
  const {
    addUserMessage, addResponse, addError, isLoading,
    startStreamingMessage, updateStreamingMessage, finalizeStreamingMessage,
    setStreamCancel, setActiveStreamId,
  } = useChatStore()

  // True when an analysis is actively streaming — input stays active in "context mode"
  const isStreaming = isLoading && !!streamCancel
  const inputRef = useRef(null)

  // When a card pre-fills the draft or triggers auto-execution
  useEffect(() => {
    if (draft) {
      const textToRun = draft
      const shouldAuto = autoSubmit
      setValue(textToRun)
      setDraft('')
      clearAutoSubmit()
      inputRef.current?.focus()
      if (shouldAuto) {
        setTimeout(() => {
          submit(textToRun)
        }, 20)
      }
    }
  }, [draft, autoSubmit])

  function runStreaming(symbol, exchange) {
    const msgId = Date.now() + 1
    startStreamingMessage(msgId, symbol, exchange)

    const url = `${getBaseUrl(port)}/skills/analyze/stream?symbol=${symbol}&exchange=${exchange}`
    const es  = new EventSource(url)

    function applyEvent(event) {
      if (event.type === 'started') {
        updateStreamingMessage(msgId, (d) => ({ ...d, phase: 'started' }))
        // Track stream_id for mid-stream context injection (#113)
        if (event.stream_id) setActiveStreamId(event.stream_id)
      } else if (event.type === 'hint_ack') {
        // User hint was received — show confirmation in the card
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          hint_ack: event.hint,
        }))
      } else if (event.type === 'hint_applied') {
        // User hint was injected into synthesis
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          hint_applied: event.hint_text,
        }))
      } else if (event.type === 'analyst') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          analysts: [...d.analysts, {
            name: event.name, verdict: event.verdict,
            confidence: event.confidence, error: event.error,
            key_points: event.key_points ?? [],
          }],
        }))
      } else if (event.type === 'phase') {
        updateStreamingMessage(msgId, (d) => ({ ...d, phase: event.phase }))
      } else if (event.type === 'debate_step') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          debate_steps: [...(d.debate_steps ?? []), { step: event.step, label: event.label, text: event.text }],
        }))
      } else if (event.type === 'synthesis_text') {
        updateStreamingMessage(msgId, (d) => ({ ...d, synthesis_text: event.text }))
      } else if (event.type === 'done') {
        updateStreamingMessage(msgId, (d) => ({
          ...d, phase: 'done', report: event.report, trade_plans: event.trade_plans,
        }))
        es.close()
        setStreamCancel(null)
        finalizeStreamingMessage(msgId)
      } else if (event.type === 'error') {
        es.close()
        setStreamCancel(null)
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          phase: 'done',
          error: event.message,
          report: d.report || `⚠️ Analysis notice: ${event.message}\n\n💡 Tip: Check your AI provider configuration or run 'credentials setup'.`,
        }))
        addError(event.message)
        finalizeStreamingMessage(msgId)
      }
    }

    // Register cancel so the card's Stop button can close the stream
    setStreamCancel(() => {
      es.close()
      finalizeStreamingMessage(msgId)
    })

    es.onmessage = (e) => {
      try { applyEvent(JSON.parse(e.data)) } catch (err) { console.error('[SSE]', err) }
    }

    es.onerror = () => {
      es.close()
      setStreamCancel(null)
      updateStreamingMessage(msgId, (d) => ({
        ...d,
        phase: 'done',
        error: 'Stream connection closed or interrupted.',
      }))
      finalizeStreamingMessage(msgId)
    }
  }

  const messages = useChatStore((s) => s.messages)
  const activeSymbol = getActiveSymbol(messages)

  async function submit(customText = null) {
    const text = (customText != null ? customText : value).trim()
    if (!text || !ready) return

    // #113 — mid-stream context injection: POST hint to running analysis
    if (isStreaming) {
      setValue('')
      addUserMessage(text)
      if (activeStreamId) {
        fetch(`${getBaseUrl(port)}/skills/analyze/hint`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stream_id: activeStreamId, hint: text }),
        })
          .then((r) => r.json())
          .then((res) => {
            // If synthesis already started or stream gone, fall back to follow-up
            if (res.status === 'expired') setPendingContext(text)
          })
          .catch(() => setPendingContext(text))
      } else {
        setPendingContext(text) // fallback if no stream_id yet
      }
      return
    }

    if (isLoading) return

    useChatStore.getState().setShowDashboard(false)
    setValue('')
    addUserMessage(text)

    const currentActive = getActiveSymbol(useChatStore.getState().messages)
    const parsed = parseCommand(text, currentActive)

    if (parsed.error) {
      addError(parsed.error)
      return
    }

    // SSE streaming path for analyze
    if (parsed.stream) {
      runStreaming(parsed.symbol, parsed.exchange)
      return
    }

    try {
      // Inject session_id for chat and follow-up endpoints
      let body = parsed.body
      if (parsed.endpoint === '/skills/chat' && activeSessionId) {
        body = { ...body, session_id: activeSessionId }
      }
      const result = parsed.method === 'GET'
        ? await get(parsed.endpoint)
        : await call(parsed.endpoint, body)
      addResponse({ cardType: parsed.cardType, data: result.data ?? result })
    } catch (e) {
      addError(e.message)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const placeholder = !ready
    ? 'Starting API…'
    : isStreaming
    ? 'Type to add context for synthesis…'
    : activeSymbol
    ? `Context: ${activeSymbol} · Type 'forensic', 'structure', 'multibagger', 'oi', 'payoff' or another ticker…`
    : 'analyze INFY · forensic TCS · scan · flows · brief · funnel nifty_50 · …'

  const quickCommands = activeSymbol
    ? [
        `analyze ${activeSymbol}`,
        `forensic ${activeSymbol}`,
        `structure ${activeSymbol}`,
        `multibagger ${activeSymbol}`,
        'flows',
        'scan',
        'brief',
      ]
    : ['analyze RELIANCE', 'radar', 'flows', 'scan', 'brief', 'funnel nifty_50']

  return (
    <div className="flex-shrink-0 border-t border-border bg-panel px-4 py-3 shadow-lg">
      {/* #113 banner — visible while streaming */}
      {isStreaming && (
        <div className="mb-2 px-1 flex items-center gap-2">
          <span className="text-[10px] animate-pulse text-amber font-ui">◆</span>
          <span className="text-[11px] text-amber font-ui font-semibold">
            Multi-Agent Analysis in progress — type additional context or constraints to shape the synthesis
          </span>
        </div>
      )}
      <div className={`flex items-center gap-3 bg-surface border rounded-xl px-4 py-2.5 transition-all shadow-xs ${
        isStreaming
          ? 'border-amber/50 ring-1 ring-amber/20'
          : 'border-border/80 focus-within:border-amber/60 focus-within:ring-2 focus-within:ring-amber/10'
      }`}>
        <span className={`text-sm font-mono flex-shrink-0 ${isStreaming ? 'text-amber animate-pulse' : 'text-amber font-bold'}`}>
          ❯
        </span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          disabled={!ready || (isLoading && !isStreaming)}
          className="flex-1 bg-transparent text-text text-sm font-mono outline-none placeholder:text-muted/60 disabled:opacity-50"
          autoFocus
        />
        {value && (
          <button
            onClick={() => setValue('')}
            className="text-muted hover:text-text text-xs p-1 rounded transition-colors"
            title="Clear"
          >
            ✕
          </button>
        )}
        <button
          onClick={submit}
          disabled={!value.trim() || (isLoading && !isStreaming) || !ready}
          className="px-2.5 py-1 rounded-lg bg-amber hover:bg-amber/90 text-black font-ui font-bold text-xs shadow-xs disabled:opacity-30 disabled:hover:bg-amber transition-all cursor-pointer"
        >
          Send ↵
        </button>
      </div>
      <div className="flex items-center justify-between mt-2 px-1 text-[11px] font-ui text-muted">
        <div className="flex items-center gap-1.5 overflow-x-auto truncate">
          <span className="text-[10px] uppercase tracking-wider text-muted/70 font-semibold">
            {activeSymbol ? `Active (${activeSymbol}):` : 'Try:'}
          </span>
          {quickCommands.map((cmd) => (
            <button
              key={cmd}
              onClick={() => setValue(cmd)}
              className="text-muted hover:text-amber text-[10px] font-mono bg-elevated hover:bg-panel px-1.5 py-0.5 rounded border border-border/40 transition-colors cursor-pointer"
            >
              {cmd}
            </button>
          ))}
        </div>
        <BrokerRouting />
      </div>
    </div>
  )
}

function BrokerRouting() {
  const brokerStatuses = useChatStore((s) => s.brokerStatuses)
  const connected = Object.entries(brokerStatuses).filter(([, b]) => b.authenticated)
  if (connected.length < 2) return null

  const dataB = connected.find(([, b]) => b.role === 'data')
  const execB = connected.find(([, b]) => b.role === 'execution')
  if (!dataB && !execB) return null

  const names = { zerodha: 'Zerodha', fyers: 'Fyers', groww: 'Groww', angel_one: 'Angel One', upstox: 'Upstox' }
  return (
    <span className="text-[9px] text-muted font-ui flex-shrink-0 ml-2">
      {dataB && <><span className="text-blue">Data</span>: {names[dataB[0]] ?? dataB[0]}</>}
      {dataB && execB && ' · '}
      {execB && <><span className="text-amber">Exec</span>: {names[execB[0]] ?? execB[0]}</>}
    </span>
  )
}
