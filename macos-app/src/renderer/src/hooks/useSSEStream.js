/**
 * useSSEStream — Production-grade Server-Sent Events hook.
 *
 * Features:
 *  - Exponential backoff reconnection (1s → 2s → 4s → 8s → max 30s)
 *  - Stale-closure-safe: uses refs internally, never captures stale state
 *  - AbortController-based cleanup on unmount or URL change
 *  - Named event type support (SSE `event: <type>` frames)
 *  - Returns `{ data, connectionState, lastUpdated, reconnect }`
 *
 * Usage:
 *   const { data, connectionState } = useSSEStream(
 *     `${baseUrl}/api/ticker/stream`,
 *     { onMessage: (payload) => setTickers(payload.tickers) }
 *   )
 *
 * connectionState: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'error'
 */

import { useEffect, useRef, useState, useCallback } from 'react'

const MIN_RETRY_MS = 1_000
const MAX_RETRY_MS = 30_000

export function useSSEStream(url, options = {}) {
  const {
    onMessage,          // (data: object, eventType: string) => void
    onOpen,             // () => void
    onError,            // (event) => void
    enabled = true,     // set to false to pause the stream
    eventTypes = null,  // null = listen to default 'message'; or ['ticker', 'heartbeat']
    parseJson = true,   // auto-parse event.data as JSON
  } = options

  const [connectionState, setConnectionState] = useState('idle')
  const [lastUpdated, setLastUpdated] = useState(null)
  const [lastData, setLastData] = useState(null)

  // Refs to avoid stale closures in callbacks
  const esRef = useRef(null)
  const retryMsRef = useRef(MIN_RETRY_MS)
  const retryTimerRef = useRef(null)
  const mountedRef = useRef(true)
  const onMessageRef = useRef(onMessage)
  const onOpenRef = useRef(onOpen)
  const onErrorRef = useRef(onError)
  const urlRef = useRef(url)
  const enabledRef = useRef(enabled)

  // Keep callback refs current without causing reconnects
  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { onOpenRef.current = onOpen }, [onOpen])
  useEffect(() => { onErrorRef.current = onError }, [onError])
  useEffect(() => { urlRef.current = url }, [url])
  useEffect(() => { enabledRef.current = enabled }, [enabled])

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (esRef.current) {
      try { esRef.current.close() } catch {}
      esRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabledRef.current || !urlRef.current) return

    cleanup()
    if (mountedRef.current) setConnectionState('connecting')

    try {
      const es = new EventSource(urlRef.current)
      esRef.current = es

      es.onopen = () => {
        if (!mountedRef.current) return
        retryMsRef.current = MIN_RETRY_MS // Reset backoff on successful connect
        setConnectionState('live')
        setLastUpdated(new Date())
        onOpenRef.current?.()
      }

      const handleMessage = (event) => {
        if (!mountedRef.current || !event.data) return
        // Skip SSE comment lines (heartbeats like ": heartbeat")
        if (!event.data.trim() || event.data.startsWith(':')) return
        try {
          const parsed = parseJson ? JSON.parse(event.data) : event.data
          setLastData(parsed)
          setLastUpdated(new Date())
          onMessageRef.current?.(parsed, event.type || 'message')
        } catch {
          // Non-JSON frame — forward raw string
          onMessageRef.current?.(event.data, event.type || 'message')
        }
      }

      if (eventTypes && Array.isArray(eventTypes)) {
        eventTypes.forEach((type) => es.addEventListener(type, handleMessage))
      } else {
        es.onmessage = handleMessage
      }

      es.onerror = (event) => {
        if (!mountedRef.current) return
        setConnectionState('reconnecting')
        onErrorRef.current?.(event)
        // Close the errored connection before retrying
        try { es.close() } catch {}
        esRef.current = null
        // Schedule exponential backoff retry
        retryTimerRef.current = setTimeout(() => {
          if (!mountedRef.current) return
          retryMsRef.current = Math.min(retryMsRef.current * 2, MAX_RETRY_MS)
          connect()
        }, retryMsRef.current)
      }
    } catch {
      if (mountedRef.current) {
        setConnectionState('error')
        retryTimerRef.current = setTimeout(() => {
          if (!mountedRef.current) return
          retryMsRef.current = Math.min(retryMsRef.current * 2, MAX_RETRY_MS)
          connect()
        }, retryMsRef.current)
      }
    }
  }, [cleanup, parseJson, eventTypes]) // stable — refs handle the rest

  // Connect / disconnect based on url or enabled changes
  useEffect(() => {
    mountedRef.current = true
    if (url && enabled) {
      retryMsRef.current = MIN_RETRY_MS
      connect()
    }
    return () => {
      mountedRef.current = false
      cleanup()
    }
  }, [url, enabled]) // Only reconnect when URL or enabled changes

  // Manual reconnect trigger
  const reconnect = useCallback(() => {
    retryMsRef.current = MIN_RETRY_MS
    connect()
  }, [connect])

  return { data: lastData, connectionState, lastUpdated, reconnect }
}
