import { useChatStore } from '../store/chatStore'

let cachedCsrfToken = null

export async function fetchCsrfToken(baseUrl) {
  try {
    if (!window.__CHANAKYA_TRADE_WEB__ && window.electronAPI?.sidecarRequest) {
      const res = await window.electronAPI.sidecarRequest({ endpoint: '/api/csrf-token' })
      cachedCsrfToken = res.ok ? (res.data?.csrf_token || null) : null
      return cachedCsrfToken
    }
    const fetchOpts = window.__CHANAKYA_TRADE_WEB__ ? { credentials: 'include' } : {}
    const res = await fetch(`${baseUrl}/api/csrf-token`, { ...fetchOpts })
    if (res.ok) {
      const data = await res.json()
      cachedCsrfToken = data.csrf_token || null
      return cachedCsrfToken
    }
  } catch {}
  return null
}

export function getCachedCsrfToken() {
  return cachedCsrfToken
}

export function useAPI() {
  const port = useChatStore((s) => s.port)

  // Web mode: use same origin (no port needed)
  // Electron mode: use port from IPC with fallback to default 8765
  const base = (window.__CHANAKYA_TRADE_WEB__ && window.location.port !== '5173')
    ? window.location.origin
    : (port ? `http://127.0.0.1:${port}` : 'http://127.0.0.1:8765')

  // In web mode, include credentials (cookies) with every request
  const fetchOpts = window.__CHANAKYA_TRADE_WEB__ ? { credentials: 'include' } : {}
  const useSidecarIpc = !window.__CHANAKYA_TRADE_WEB__ && Boolean(window.electronAPI?.sidecarRequest)

  const call = async (endpoint, body = {}, options = {}) => {
    if (!base) throw new Error('API not ready — sidecar is still starting')

    const method = (options.method || 'POST').toUpperCase()
    const isMutation = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)

    if (isMutation && !cachedCsrfToken) {
      await fetchCsrfToken(base)
    }

    const headers = {
      'Content-Type': 'application/json',
      ...(cachedCsrfToken ? { 'X-CSRF-Token': cachedCsrfToken } : {}),
      ...(options.headers || {}),
    }

    if (useSidecarIpc) {
      try {
        const response = await window.electronAPI.sidecarRequest({
          endpoint,
          method,
          headers,
          body: options.body !== undefined ? options.body : body,
          timeoutMs: options.timeoutMs,
        })
        if (!response.ok) throw new Error(`API ${response.status}: ${JSON.stringify(response.data)}`)
        return response.data
      } catch (ipcErr) {
        if (!ipcErr.message?.includes('API is not ready')) throw ipcErr
      }
    }

    let res = await fetch(`${base}${endpoint}`, {
      method,
      headers,
      body: options.body !== undefined ? options.body : JSON.stringify(body),
      ...fetchOpts,
      ...options,
    })

    // If 403 on mutation in web mode, try refreshing the CSRF token once and retry
    if (res.status === 403 && isMutation) {
      const freshToken = await fetchCsrfToken(base)
      if (freshToken && freshToken !== headers['X-CSRF-Token']) {
        res = await fetch(`${base}${endpoint}`, {
          method,
          headers: {
            ...headers,
            'X-CSRF-Token': freshToken,
          },
          body: options.body !== undefined ? options.body : JSON.stringify(body),
          ...fetchOpts,
          ...options,
        })
      }
    }

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
    if (useSidecarIpc) {
      try {
        const response = await window.electronAPI.sidecarRequest({
          endpoint,
          method: 'GET',
          headers: options.headers,
          timeoutMs: options.timeoutMs,
        })
        if (!response.ok) throw new Error(`API ${response.status}: ${JSON.stringify(response.data)}`)
        return response.data
      } catch (ipcErr) {
        if (!ipcErr.message?.includes('API is not ready')) throw ipcErr
      }
    }
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

  return { call, get, ready: !!base, base, fetchCsrfToken: () => fetchCsrfToken(base) }
}

