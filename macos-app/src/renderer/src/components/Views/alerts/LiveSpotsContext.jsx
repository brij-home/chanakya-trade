import React, { createContext, useContext, useRef, useCallback, useMemo, useState, useEffect } from 'react'

export const LiveSpotsCtx = createContext(null)

export function LiveSpotsProvider({ children }) {
  const spotsRef = useRef({})
  const subscribersRef = useRef({})

  const subscribe = useCallback((symbol, forceUpdate) => {
    if (!symbol) return () => {}
    if (!subscribersRef.current[symbol]) subscribersRef.current[symbol] = new Set()
    subscribersRef.current[symbol].add(forceUpdate)
    return () => subscribersRef.current[symbol]?.delete(forceUpdate)
  }, [])

  const publish = useCallback((quotesMap) => {
    const prev = spotsRef.current
    const next = { ...prev }
    const changedSymbols = new Set()

    for (const [sym, q] of Object.entries(quotesMap)) {
      if (!q || q.ltp === undefined || q.ltp === null) continue
      const oldEntry = prev[sym]
      const ltp = Number(q.ltp)
      const flash = oldEntry?.ltp !== undefined && oldEntry.ltp !== ltp
        ? (ltp > oldEntry.ltp ? 'up' : 'down')
        : null
      next[sym] = { ltp, change_pct: q.change_pct, change: q.change, high: q.high, low: q.low, flash }
      changedSymbols.add(sym)
    }
    spotsRef.current = next

    for (const sym of changedSymbols) {
      subscribersRef.current[sym]?.forEach((fn) => fn())
    }

    if (changedSymbols.size > 0) {
      setTimeout(() => {
        const nowSpots = spotsRef.current
        const cleared = { ...nowSpots }
        let changed = false
        for (const sym of changedSymbols) {
          if (cleared[sym]?.flash) {
            cleared[sym] = { ...cleared[sym], flash: null }
            changed = true
          }
        }
        if (changed) {
          spotsRef.current = cleared
          for (const sym of changedSymbols) {
            subscribersRef.current[sym]?.forEach((fn) => fn())
          }
        }
      }, 750)
    }
  }, [])

  const get = useCallback((symbol) => spotsRef.current[symbol] ?? null, [])

  const ctx = useMemo(() => ({ subscribe, publish, get }), [subscribe, publish, get])

  return <LiveSpotsCtx.Provider value={ctx}>{children}</LiveSpotsCtx.Provider>
}

export function useLiveSpot(symbol) {
  const ctx = useContext(LiveSpotsCtx)
  const [, forceUpdate] = useState(0)
  const forceUpdateRef = useRef()
  forceUpdateRef.current = () => forceUpdate((n) => n + 1)

  useEffect(() => {
    if (!ctx || !symbol) return
    const fn = () => forceUpdateRef.current()
    return ctx.subscribe(symbol, fn)
  }, [ctx, symbol])

  return ctx?.get(symbol) ?? null
}
