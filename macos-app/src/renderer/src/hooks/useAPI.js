import { useChatStore } from '../store/chatStore'

export function useAPI() {
  const port = useChatStore((s) => s.port)

  // Web mode: use same origin (no port needed)
  // Electron mode: use port from IPC with fallback to default 8765
  const base = window.__CHANAKYA_TRADE_WEB__
    ? window.location.origin
    : (port ? `http://127.0.0.1:${port}` : 'http://127.0.0.1:8765')

  // In web mode, include credentials (cookies) with every request
  const fetchOpts = window.__CHANAKYA_TRADE_WEB__ ? { credentials: 'include' } : {}

  const call = async (endpoint, body = {}, options = {}) => {
    if (!base) throw new Error('API not ready — sidecar is still starting')
    const res = await fetch(`${base}${endpoint}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
      ...fetchOpts,
      ...options,
    })
    if (!res.ok) {
      if (res.status === 401 && window.__CHANAKYA_TRADE_WEB__) {
        window.location.href = '/'
        return
      }
      const err = await res.text()
      throw new Error(`API ${res.status}: ${err}`)
    }
    return res.json()
  }

  const get = async (endpoint, options = {}) => {
    if (!base) throw new Error('API not ready')
    const res = await fetch(`${base}${endpoint}`, {
      ...fetchOpts,
      ...options,
    })
    if (!res.ok) {
      if (res.status === 401 && window.__CHANAKYA_TRADE_WEB__) {
        window.location.href = '/'
        return
      }
      throw new Error(`API ${res.status}`)
    }
    return res.json()
  }

  return { call, get, ready: !!base, base }
}
