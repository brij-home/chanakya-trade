/**
 * useRealtimeMarket.js — Single Source of Truth (SSOT) for real-time market data.
 *
 * Provides a shared, deduplicated market feed across the application:
 * - Single EventSource stream to /api/ticker/stream
 * - Sub-second visual price flash indicators (up/down)
 * - Transparent provenance tracking (Primary Broker vs Fallback Feed)
 * - Zero static fake prices; returns honest empty/null states when disconnected
 * - Reused by LiveTickerRibbon, ContextBar, TerminalView, and cards
 */

import { create } from 'zustand'
import { useEffect, useRef, useMemo, useCallback } from 'react'
import { useChatStore, getBaseUrl } from '../store/chatStore'

// Canonical symbol normalization for fast O(1) matching
function cleanSymbol(sym) {
  if (!sym) return ''
  return String(sym)
    .replace(/^(NSE:|BSE:|MCX:|CDS:|CRYPTO:)/i, '')
    .replace(/\s*\(.*?\)/g, '')
    .trim()
    .toUpperCase()
    .replace(/\s+/g, '')
}

export const useMarketStore = create((set, get) => ({
  tickers: [],
  tickerMap: {},
  flashMap: {}, // { [cleanSym]: 'up' | 'down' }
  connectionState: 'idle', // 'idle' | 'connecting' | 'live' | 'reconnecting' | 'error'
  lastUpdated: null,
  dataSource: 'FALLBACK',
  isRealtime: false,
  isInitialized: false,

  setTickers: (incomingTickers, source = 'REST') => {
    if (!Array.isArray(incomingTickers) || incomingTickers.length === 0) return

    const prev = get().tickers
    const prevMap = get().tickerMap
    const flashes = {}
    const newMap = {}

    for (const item of incomingTickers) {
      if (!item || !item.symbol) continue
      const k = cleanSymbol(item.symbol)
      newMap[k] = item
      if (item.inst) newMap[cleanSymbol(item.inst)] = item

      // Check tick price flash
      const old = prevMap[k]
      if (
        old &&
        typeof item.ltp === 'number' &&
        typeof old.ltp === 'number' &&
        item.ltp !== old.ltp &&
        item.ltp > 0 &&
        old.ltp > 0
      ) {
        flashes[item.symbol] = item.ltp > old.ltp ? 'up' : 'down'
      }
    }

    const isLive = source === 'SSE' || source === 'STREAM' || source === 'WS'

    set({
      tickers: incomingTickers,
      tickerMap: { ...prevMap, ...newMap },
      flashMap: Object.keys(flashes).length > 0 ? { ...get().flashMap, ...flashes } : get().flashMap,
      lastUpdated: new Date(),
      dataSource: source,
      isRealtime: isLive,
      isInitialized: true,
    })

    if (Object.keys(flashes).length > 0) {
      setTimeout(() => {
        set({ flashMap: {} })
      }, 750)
    }
  },

  getTicker: (sym) => {
    if (!sym) return null
    const k = cleanSymbol(sym)
    return get().tickerMap[k] || null
  },

  updateFromSnapshot: (incomingTickers, source = 'REST', isFallback = false) => {
    if (isFallback) {
      set({ isFallback: true, dataSource: 'FALLBACK', isRealtime: false })
      if (Array.isArray(incomingTickers) && incomingTickers.length > 0) {
        get().setTickers(incomingTickers, 'REST')
      }
      return
    }
    const isLive = source === 'SSE' || source === 'STREAM' || source === 'WS'
    set({ isFallback: false, isStreaming: isLive, dataSource: source })
    get().setTickers(incomingTickers, source)
  },

  setConnectionState: (connectionState) => set({ connectionState }),
}))


// Singleton connection controller
let activeEventSource = null
let subscriberCount = 0
let retryTimer = null
let fallbackTimer = null
let currentRetryDelay = 1000

async function fetchRestTickers(port) {
  if (!port && port !== 0) return
  const url = `${getBaseUrl(port)}/api/ticker/snapshot`
  try {
    const res = await fetch(url)
    if (res.ok) {
      const data = await res.json()
      const list = data?.tickers || data?.data?.tickers
      if (Array.isArray(list) && list.length > 0) {
        useMarketStore.getState().setTickers(list, 'REST')
      }
    }
  } catch {}
}

function startRealtimeStream(port) {
  if (!port && port !== 0) return
  if (activeEventSource) return

  const store = useMarketStore.getState()
  store.setConnectionState('connecting')

  const streamUrl = `${getBaseUrl(port)}/api/ticker/stream`

  try {
    const es = new EventSource(streamUrl)
    activeEventSource = es

    es.onopen = () => {
      currentRetryDelay = 1000
      useMarketStore.getState().setConnectionState('live')
      if (fallbackTimer) {
        clearInterval(fallbackTimer)
        fallbackTimer = null
      }
    }

    es.onmessage = (event) => {
      if (!event.data || event.data.startsWith(':')) return
      try {
        const payload = JSON.parse(event.data)
        const tickers = payload?.tickers || payload?.data?.tickers
        if (Array.isArray(tickers) && tickers.length > 0) {
          useMarketStore.getState().setTickers(tickers, 'SSE')
        }
      } catch {}
    }

    es.onerror = () => {
      useMarketStore.getState().setConnectionState('reconnecting')
      try {
        es.close()
      } catch {}
      activeEventSource = null

      // Start resilient quiet fallback polling if not already started
      if (!fallbackTimer) {
        fetchRestTickers(port)
        fallbackTimer = setInterval(() => fetchRestTickers(port), 6000)
      }

      // Exponential backoff reconnect for SSE
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = setTimeout(() => {
        if (subscriberCount > 0) {
          currentRetryDelay = Math.min(currentRetryDelay * 2, 30000)
          startRealtimeStream(port)
        }
      }, currentRetryDelay)
    }
  } catch {
    useMarketStore.getState().setConnectionState('error')
    if (!fallbackTimer) {
      fetchRestTickers(port)
      fallbackTimer = setInterval(() => fetchRestTickers(port), 6000)
    }
  }
}

function stopRealtimeStream() {
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (fallbackTimer) {
    clearInterval(fallbackTimer)
    fallbackTimer = null
  }
  if (activeEventSource) {
    try {
      activeEventSource.close()
    } catch {}
    activeEventSource = null
  }
  useMarketStore.getState().setConnectionState('idle')
}

/**
 * useRealtimeMarket — Primary hook to access institutional real-time market data.
 *
 * @param {string} [symbol] - Optional target symbol to track directly
 * @returns {{
 *   tickers: Array,
 *   tickerMap: Object,
 *   getTicker: (sym: string) => Object|null,
 *   targetTicker: Object|null,
 *   flashMap: Object,
 *   connectionState: string,
 *   isRealtime: boolean,
 *   dataSource: string,
 *   lastUpdated: Date|null,
 *   refresh: () => void,
 * }}
 */
export function useRealtimeMarket(symbol = null) {
  const port = useChatStore((s) => s.port)
  const tickers = useMarketStore((s) => s.tickers)
  const tickerMap = useMarketStore((s) => s.tickerMap)
  const flashMap = useMarketStore((s) => s.flashMap)
  const connectionState = useMarketStore((s) => s.connectionState)
  const isRealtime = useMarketStore((s) => s.isRealtime)
  const dataSource = useMarketStore((s) => s.dataSource)
  const lastUpdated = useMarketStore((s) => s.lastUpdated)

  useEffect(() => {
    subscriberCount++
    if (subscriberCount === 1) {
      // Immediate initial fetch to eliminate layout shift
      fetchRestTickers(port)
      startRealtimeStream(port)
    }
    return () => {
      subscriberCount = Math.max(0, subscriberCount - 1)
      if (subscriberCount === 0) {
        stopRealtimeStream()
      }
    }
  }, [port])

  const getTicker = useCallback(
    (sym) => {
      if (!sym) return null
      const k = cleanSymbol(sym)
      return tickerMap[k] || null
    },
    [tickerMap]
  )

  const targetTicker = useMemo(() => {
    if (!symbol) return null
    return getTicker(symbol)
  }, [symbol, getTicker])

  const refresh = useCallback(() => {
    fetchRestTickers(port)
  }, [port])

  return {
    tickers,
    tickerMap,
    getTicker,
    targetTicker,
    flashMap,
    connectionState,
    isRealtime,
    dataSource,
    lastUpdated,
    refresh,
  }
}

useRealtimeMarket.getState = useMarketStore.getState
useRealtimeMarket.setState = useMarketStore.setState
useRealtimeMarket.subscribe = useMarketStore.subscribe

