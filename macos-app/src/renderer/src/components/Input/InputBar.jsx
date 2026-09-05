import { useState, useRef, useEffect } from 'react'
import { useChatStore, getBaseUrl, getActiveSymbol } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import SmartTypeahead from '../Common/SmartTypeahead'
import { fuzzySearchUniverse, getSymbolExchange } from '../../data/universeData'

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

    case 'analyze': case 'analyse': case 'debate': case 'a': {
      let sym = args[0]?.toUpperCase() || contextSymbol
      if (!sym) return { error: 'Please specify a stock symbol to analyze (e.g. analyze INFY)' }
      let exch = args[1]?.toUpperCase()
      if (!exch) {
        if (sym.includes(':')) {
          const [prefix, s] = sym.split(':')
          exch = prefix
          sym = s
        } else {
          exch = getSymbolExchange(sym)
        }
      }
      return { stream: true, symbol: sym, exchange: exch }
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
      const exch = args[1]?.toUpperCase() || getSymbolExchange(sym)
      return {
        endpoint: '/skills/deep_analyze',
        body: { symbol: sym, exchange: exch },
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
      const exch = args[1]?.toUpperCase() || getSymbolExchange(sym)
      return {
        endpoint: '/skills/oi_profile',
        body: { symbol: sym, exchange: exch },
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
    case 'rrg': case 'sector-rotation': case 'rotation': case 'sector': case 'sectors': {
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
      let topN = 2
      const filteredArgs = []
      for (let i = 0; i < args.length; i++) {
        const a = args[i]
        if (a === '--top' || a === '-n' || a === 'top') {
          const next = parseInt(args[i + 1], 10)
          if (!isNaN(next)) { topN = next; i++; continue }
        } else if (a && a.startsWith('--top=')) {
          const val = parseInt(a.split('=')[1], 10)
          if (!isNaN(val)) { topN = val; continue }
        } else {
          filteredArgs.push(a)
        }
      }

      let syms = 'nifty_50'
      if (filteredArgs.length > 0) {
        if (filteredArgs[0].toLowerCase() === 'sector' || filteredArgs[0].toLowerCase() === 'sec') {
          const sectorName = filteredArgs.slice(1).join('_').toLowerCase()
          syms = sectorName || 'nifty_50'
        } else if (filteredArgs.length === 1) {
          syms = filteredArgs[0]
        } else {
          syms = filteredArgs.join(',')
        }
      } else if (contextSymbol) {
        syms = contextSymbol
      }
      return { endpoint: '/skills/funnel', body: { symbols: syms, top_n: topN }, cardType: 'funnel' }
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

    case 'council': case 'councils': {
      let cName = 'breakout'
      let sym = contextSymbol || 'RELIANCE'
      if (args.length >= 2) {
        cName = args[0].toLowerCase()
        sym = args[1].toUpperCase()
      } else if (args.length === 1) {
        if (['breakout', 'options_sniper', 'options', 'multibagger', 'macro_regime', 'core_value'].includes(args[0].toLowerCase())) {
          cName = args[0].toLowerCase() === 'options' ? 'options_sniper' : args[0].toLowerCase()
        } else {
          sym = args[0].toUpperCase()
        }
      }
      return { endpoint: '/skills/persona/council', body: { symbol: sym, council: cName }, cardType: 'council' }
    }

    case 'persona': case 'personas': {
      const pId = args[0]?.toLowerCase() || 'buffett'
      const sym = args[1]?.toUpperCase() || contextSymbol || 'RELIANCE'
      return { endpoint: '/skills/persona/analyze', body: { symbol: sym, persona_id: pId }, cardType: 'persona' }
    }

    case 'spread': case 'spreads': case 'spread_builder': {
      const sym = (args[0] || contextSymbol || 'NIFTY').toUpperCase()
      const strat = (args[1] || 'BULL_CALL_SPREAD').toUpperCase()
      return { endpoint: '/skills/options/defined_risk_spreads', body: { underlying: sym, strategy: strat }, cardType: 'defined_risk_spread' }
    }

    case 'tax': {
      const pnl = parseFloat(args[0]) || 50000
      const days = parseInt(args[1]) || 90
      return { endpoint: '/skills/tax/calculate', body: { gross_pnl: pnl, holding_period_days: days }, cardType: 'markdown' }
    }

    case 'harvest': case 'tax-harvest': {
      return { endpoint: '/skills/tax/harvesting', body: {}, cardType: 'markdown' }
    }

    case 'tilt': case 'risk-status': {
      return { endpoint: '/api/risk/preflight', body: { action: 'BUY', symbol: contextSymbol || 'NIFTY', qty: 50, price: 24500 }, cardType: 'markdown' }
    }

    default: {
      // Check if the user typed a single symbol name like 'Bajaj-Auto', 'BAJAJ_AUTO', 'RELIANCE', 'MCX:CRUDEOIL', 'CRUDEOIL'
      let rawSym = input.trim().toUpperCase()
      let exch = 'NSE'
      if (rawSym.startsWith('MCX:')) {
        exch = 'MCX'
        rawSym = rawSym.slice(4)
      } else if (rawSym.startsWith('CDS:') || rawSym.startsWith('FX:') || rawSym.startsWith('FOREX:')) {
        exch = 'CDS'
        rawSym = rawSym.split(':')[1]
      } else if (rawSym.startsWith('BSE:')) {
        exch = 'BSE'
        rawSym = rawSym.slice(4)
      } else if (rawSym.startsWith('NSE:')) {
        exch = 'NSE'
        rawSym = rawSym.slice(4)
      } else {
        exch = getSymbolExchange(rawSym)
      }
      const cleanSingle = rawSym.replace(/_/g, '-')
      if (/^[A-Z0-9&-]{2,15}$/.test(cleanSingle) && !['HELLO', 'HI', 'HELP', 'CLEAR', 'RESET', 'YES', 'NO', 'CANCEL'].includes(cleanSingle)) {
        return { stream: true, symbol: cleanSingle, exchange: exch }
      }
      // Fall through to AI chat — session_id injected in submit()
      return { endpoint: '/skills/chat', body: { message: input }, cardType: 'markdown' }
    }
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
    startActivity, updateActivity, stopActivity,
  } = useChatStore()

  // True when an analysis is actively streaming — input stays active in "context mode"
  const isStreaming = isLoading && !!streamCancel
  const inputRef = useRef(null)
  const isSubmittingRef = useRef(false)

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
        const timer = setTimeout(() => {
          submit(textToRun)
        }, 20)
        return () => clearTimeout(timer)
      }
    }
  }, [draft, autoSubmit])

  function runStreaming(symbol, exchange) {
    const rawSym = (symbol || '').toUpperCase().trim()
    const resolvedExch = (!exchange || exchange === 'NSE') ? getSymbolExchange(rawSym) : exchange

    // Concurrency Deduplication Guard: Never run multiple concurrent analyses for the same symbol
    const activeMessages = useChatStore.getState().messages || []
    const isAlreadyStreamingThis = activeMessages.some(
      (m) => m.cardType === 'streaming_analysis' && m.data?.symbol === rawSym && m.data?.phase !== 'done' && !m.data?.error
    )
    if (isAlreadyStreamingThis) {
      console.warn(`[InputBar] Analysis for ${rawSym} is already actively in progress. Suppressing duplicate execution.`)
      return
    }

    // If another analysis is active on a different symbol, cancel previous stream before starting new one
    const existingCancel = useChatStore.getState().streamCancel
    if (existingCancel) {
      existingCancel()
    }

    const msgId = Date.now() + 1
    startStreamingMessage(msgId, rawSym, resolvedExch)

    startActivity({
      title: `Multi-Agent Debate (${rawSym})`,
      details: 'Connecting to multi-agent intelligence pipeline...',
      type: 'debate',
      targetView: 'copilot',
      cancelFn: () => {
        if (es) es.close()
        setStreamCancel(null)
        finalizeStreamingMessage(msgId)
        stopActivity()
      },
    })

    const url = `${getBaseUrl(port)}/skills/analyze/stream?symbol=${rawSym}&exchange=${resolvedExch}`
    const es  = new EventSource(url)

    function applyEvent(event) {
      if (event.type === 'started') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          phase: 'started',
          symbol: event.symbol || d.symbol,
          exchange: event.exchange || d.exchange,
        }))
        updateActivity({ details: `Evaluating quantitative models for ${rawSym}...` })
        // Track stream_id for mid-stream context injection (#113)
        if (event.stream_id) setActiveStreamId(event.stream_id)
      } else if (event.type === 'hint_ack') {
        // User hint was received — show confirmation in the card
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          hint_ack: event.hint,
        }))
        updateActivity({ details: `Context injected: ${event.hint}` })
      } else if (event.type === 'hint_applied') {
        // User hint was injected into synthesis
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          hint_applied: event.hint_text,
        }))
        updateActivity({ details: `Synthesis adapting to user context...` })
      } else if (event.type === 'analyst') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          analysts: [...d.analysts, {
            name: event.name, verdict: event.verdict,
            confidence: event.confidence, error: event.error,
            key_points: event.key_points ?? [],
          }],
        }))
        updateActivity({ details: `Analyst ${event.name} finished: ${event.verdict} (${event.confidence}% confidence)` })
      } else if (event.type === 'phase') {
        updateStreamingMessage(msgId, (d) => ({ ...d, phase: event.phase }))
        updateActivity({ details: `Entering ${event.phase} stage...` })
      } else if (event.type === 'debate_step') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          debate_steps: [...(d.debate_steps ?? []), { step: event.step, label: event.label, text: event.text }],
        }))
        updateActivity({ details: `${event.label}: ${event.text ? event.text.slice(0, 45) + '...' : 'Rebuttal in progress'}` })
      } else if (event.type === 'synthesis_text') {
        updateStreamingMessage(msgId, (d) => ({ ...d, synthesis_text: event.text }))
        updateActivity({ details: 'Synthesizing final institutional trade plan...' })
      } else if (event.type === 'done') {
        updateStreamingMessage(msgId, (d) => ({
          ...d,
          phase: 'done',
          symbol: event.symbol || d.symbol,
          exchange: event.exchange || d.exchange,
          report: event.report,
          trade_plans: event.trade_plans,
        }))
        es.close()
        setStreamCancel(null)
        finalizeStreamingMessage(msgId)
        stopActivity()

        const curView = useChatStore.getState().activeView
        if (curView !== 'copilot') {
          useChatStore.getState().notifyCompletedActivity({
            title: `Multi-Agent Debate (${rawSym}) Complete`,
            message: `Consensus synthesis & trade plan for ${rawSym} are ready.`,
            targetView: 'copilot',
          })
        }
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
        stopActivity()
      }
    }

    // Register cancel so the card's Stop button can close the stream
    setStreamCancel(() => {
      es.close()
      finalizeStreamingMessage(msgId)
      stopActivity()
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
      stopActivity()
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

    const store = useChatStore.getState()
    if (store.isLoading || isSubmittingRef.current) {
      console.warn('[InputBar] Submission suppressed: previous action still in progress.')
      return
    }
    isSubmittingRef.current = true
    setTimeout(() => { isSubmittingRef.current = false }, 350)

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

    const abortController = new AbortController()

    try {
      const isFunnel = parsed.cardType === 'funnel'
      startActivity({
        title: isFunnel ? 'Smart Funnel Intelligence' : `Quant Intelligence (${parsed.cardType?.toUpperCase() || 'QUERY'})`,
        details: isFunnel ? `Screening ${parsed.body?.symbols || 'watchlist'} & evaluating top setups...` : `Computing ${text}...`,
        type: 'quant',
        targetView: 'copilot',
        cancelFn: () => {
          try { abortController.abort() } catch (e) {}
          stopActivity()
        },
      })
      // Inject session_id for chat and follow-up endpoints
      let body = parsed.body
      if (parsed.endpoint === '/skills/chat' && activeSessionId) {
        body = { ...body, session_id: activeSessionId }
      }
      const result = parsed.method === 'GET'
        ? await get(parsed.endpoint, { signal: abortController.signal })
        : await call(parsed.endpoint, body, { signal: abortController.signal })
      addResponse({ cardType: parsed.cardType, data: result.data ?? result })

      const curView = useChatStore.getState().activeView
      if (curView !== 'copilot') {
        useChatStore.getState().notifyCompletedActivity({
          title: `${parsed.cardType?.toUpperCase() || 'Quant'} Analysis Ready`,
          message: `Results for "${text}" are available in AI Copilot.`,
          targetView: 'copilot',
        })
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        addError(e.message)
      }
    } finally {
      stopActivity()
    }
  }

  const [showTypeahead, setShowTypeahead] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)

  const typeaheadItems = fuzzySearchUniverse(value, activeSymbol, 10)

  function onKeyDown(e) {
    if (showTypeahead && typeaheadItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex((prev) => (prev + 1) % typeaheadItems.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex((prev) => (prev - 1 + typeaheadItems.length) % typeaheadItems.length)
        return
      }
      if (e.key === 'Tab') {
        e.preventDefault()
        const selected = typeaheadItems[selectedIndex]
        if (selected) {
          setValue(selected.command || selected.symbol || selected.text || selected.label || '')
        }
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setShowTypeahead(false)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        const selected = typeaheadItems[selectedIndex]
        if (selected) {
          setShowTypeahead(false)
          submit(selected.command || (selected.symbol ? `analyze ${selected.symbol}` : selected.text || selected.label))
          return
        }
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      setShowTypeahead(false)
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
    <div className="flex-shrink-0 border-t border-border bg-panel px-4 py-3 shadow-lg relative">
      {/* Smart Typeahead Floating Autocomplete Overlay */}
      <div className="relative max-w-4xl mx-auto">
        <SmartTypeahead
          query={value}
          activeSymbol={activeSymbol}
          isOpen={showTypeahead && value.trim().length > 0}
          onSelect={(item) => {
            setShowTypeahead(false)
            submit(item.command || (item.symbol ? `analyze ${item.symbol}` : item.text || item.label))
          }}
          onClose={() => setShowTypeahead(false)}
          position="above"
          selectedIndex={selectedIndex}
          setSelectedIndex={setSelectedIndex}
        />
      </div>

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
          onChange={(e) => {
            setValue(e.target.value)
            setShowTypeahead(true)
            setSelectedIndex(0)
          }}
          onFocus={() => {
            if (value.trim()) setShowTypeahead(true)
          }}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          disabled={!ready || (isLoading && !isStreaming)}
          className="flex-1 bg-transparent text-text text-sm font-mono outline-none placeholder:text-muted/60 disabled:opacity-50"
          autoFocus
        />
        {value && (
          <button
            onClick={() => {
              setValue('')
              setShowTypeahead(false)
            }}
            className="text-muted hover:text-text text-xs p-1 rounded transition-colors cursor-pointer"
            title="Clear input"
          >
            ✕
          </button>
        )}
        <button
          onClick={() => {
            setShowTypeahead(false)
            submit()
          }}
          disabled={!value.trim() || (isLoading && !isStreaming) || !ready}
          className="px-3 py-1.5 rounded-lg bg-amber hover:bg-amber/90 text-black font-ui font-extrabold text-xs shadow-xs disabled:opacity-30 disabled:hover:bg-amber transition-all cursor-pointer"
        >
          Send ↵
        </button>
      </div>
      <div className="flex items-center justify-between mt-2.5 px-1 text-[11px] font-ui text-muted">
        <div className="flex items-center gap-1.5 overflow-x-auto truncate">
          <span className="text-[10px] uppercase tracking-wider text-muted font-bold">
            {activeSymbol ? `Active (${activeSymbol}):` : 'Quick Actions:'}
          </span>
          {quickCommands.map((cmd) => (
            <button
              key={cmd}
              onClick={() => useChatStore.getState().sendDraft(cmd)}
              className="text-text hover:text-amber text-[10px] font-mono bg-elevated hover:bg-panel px-2 py-0.5 rounded-md border border-border transition-colors cursor-pointer shadow-xs"
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
