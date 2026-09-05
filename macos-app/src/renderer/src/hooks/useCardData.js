/**
 * useCardData — Unified data-fetching hook for all card components.
 *
 * Replaces 50+ duplicated fetch/loading/error patterns across card components.
 *
 * Features:
 *  - Request deduplication: same endpoint + body → single in-flight request
 *  - Client-side TTL cache: avoids double-fetch when card remounts
 *  - Abort on unmount: no setState on unmounted component warnings
 *  - Configurable transform: normalise `res?.data ?? res` in one place
 *  - Auto-refetch when `dependencies` change
 *
 * Usage:
 *   const { data, loading, error, refetch } = useCardData(
 *     '/skills/forensic',
 *     { symbol: 'RELIANCE', exchange: 'NSE' },
 *     {
 *       ttl: 30_000,            // client-side cache TTL in ms (default: 0 = no cache)
 *       dependencies: [symbol], // refetch when these change
 *       transform: (res) => res?.data ?? res,
 *       method: 'POST',         // default POST
 *       enabled: !!symbol,      // skip fetch when falsy
 *     }
 *   )
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useAPI } from './useAPI'

// Module-level shared cache (survives remounts, lost on page reload)
const _cache = new Map() // key -> { data, ts }
// Module-level in-flight deduplication
const _inflight = new Map() // key -> Promise

function cacheKey(endpoint, body) {
  try {
    return `${endpoint}::${JSON.stringify(body)}`
  } catch {
    return endpoint
  }
}

export function useCardData(endpoint, body = {}, options = {}) {
  const {
    ttl = 0,             // ms; 0 = never cache
    dependencies = [],   // additional deps beyond endpoint/body
    transform = (res) => res?.data ?? res,
    method = 'POST',
    enabled = true,
    onSuccess,           // (data) => void — called after successful fetch
    onError: onErrorCb,  // (err) => void
  } = options

  const { call, ready } = useAPI()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const mountedRef = useRef(true)
  const abortRef = useRef(null)

  const fetch = useCallback(async (forceRefresh = false) => {
    if (!ready || !enabled || !endpoint) return

    const key = cacheKey(endpoint, body)

    // Check client-side cache
    if (!forceRefresh && ttl > 0) {
      const cached = _cache.get(key)
      if (cached && Date.now() - cached.ts < ttl) {
        if (mountedRef.current) {
          setData(cached.data)
          setLoading(false)
          setError(null)
        }
        return
      }
    }

    // Deduplicate in-flight requests
    if (_inflight.has(key)) {
      try {
        const result = await _inflight.get(key)
        if (mountedRef.current) {
          setData(result)
          setLoading(false)
        }
      } catch (err) {
        if (mountedRef.current) {
          setError(err.message || 'Request failed')
          setLoading(false)
        }
      }
      return
    }

    if (mountedRef.current) {
      setLoading(true)
      setError(null)
    }

    // Cancel previous request for this component instance
    if (abortRef.current) {
      try { abortRef.current() } catch {}
    }

    let cancelled = false
    abortRef.current = () => { cancelled = true }

    const promise = (async () => {
      const res = await call(endpoint, body, { method })
      const transformed = transform(res)
      return transformed
    })()

    _inflight.set(key, promise)

    try {
      const result = await promise
      if (ttl > 0) {
        _cache.set(key, { data: result, ts: Date.now() })
      }
      if (!cancelled && mountedRef.current) {
        setData(result)
        setLoading(false)
        setError(null)
        onSuccess?.(result)
      }
    } catch (err) {
      if (!cancelled && mountedRef.current) {
        setError(err.message || 'Failed to load data')
        setLoading(false)
        onErrorCb?.(err)
      }
    } finally {
      _inflight.delete(key)
    }
  }, [endpoint, ready, enabled, ttl, method, transform, call, ...dependencies]) // eslint-disable-line

  useEffect(() => {
    mountedRef.current = true
    fetch()
    return () => {
      mountedRef.current = false
      if (abortRef.current) {
        try { abortRef.current() } catch {}
      }
    }
  }, [fetch])

  const refetch = useCallback(() => fetch(true), [fetch])

  return { data, loading, error, refetch }
}

/**
 * Imperatively invalidate cache for a given endpoint prefix.
 * Useful after mutations (e.g., order placed → invalidate portfolio cache).
 */
export function invalidateCardCache(endpointPrefix) {
  for (const key of _cache.keys()) {
    if (key.startsWith(endpointPrefix)) {
      _cache.delete(key)
    }
  }
}
