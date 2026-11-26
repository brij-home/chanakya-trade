/**
 * createVisibilityInterval — Lifecycle-safe interval helper that pauses polling
 * while the browser tab / Electron window is hidden, then catches up immediately
 * when focus/visibility resumes.
 */
export function createVisibilityInterval(fn, intervalMs, { immediateOnVisible = true } = {}) {
  const safeRun = () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return
    }
    fn()
  }

  const timer = setInterval(safeRun, intervalMs)

  const handleVisibility = () => {
    if (immediateOnVisible && document.visibilityState === 'visible') {
      fn()
    }
  }

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('visibilitychange', handleVisibility)
  }

  return () => {
    clearInterval(timer)
    if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }
}
