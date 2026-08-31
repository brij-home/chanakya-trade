import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'

export default function ActivityHUD() {
  const activeActivity = useChatStore((s) => s.activeActivity)
  const cancelActiveActivity = useChatStore((s) => s.cancelActiveActivity)
  const completedNotification = useChatStore((s) => s.completedNotification)
  const dismissNotification = useChatStore((s) => s.dismissNotification)
  const activeView = useChatStore((s) => s.activeView)
  const setActiveView = useChatStore((s) => s.setActiveView)

  const [elapsedSec, setElapsedSec] = useState(0)
  const [isMinimized, setIsMinimized] = useState(false)

  // Track elapsed time while active
  useEffect(() => {
    if (!activeActivity) {
      setElapsedSec(0)
      return
    }

    const interval = setInterval(() => {
      const sec = Math.floor((Date.now() - activeActivity.startedAt) / 1000)
      setElapsedSec(sec)
    }, 500)

    return () => clearInterval(interval)
  }, [activeActivity])

  const formatTime = (sec) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}:${s < 10 ? '0' : ''}${s}s`
  }

  // 1. If completed notification is active (e.g. user was in another tab when analysis completed)
  const renderNotificationToast = () => {
    if (!completedNotification) return null

    return (
      <div className="fixed bottom-5 right-5 z-50 max-w-sm w-full animate-in fade-in slide-in-from-bottom-3 duration-200">
        <div className="bg-panel/98 border border-emerald-500/40 rounded-2xl p-3.5 shadow-2xl backdrop-blur-xl space-y-2 ring-1 ring-emerald-500/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 text-xs">
                ✓
              </span>
              <span className="text-xs font-bold text-text font-mono truncate max-w-[210px]">
                {completedNotification.title}
              </span>
            </div>
            <button
              onClick={dismissNotification}
              className="text-muted hover:text-text text-xs p-1 rounded transition-colors cursor-pointer"
              title="Dismiss"
            >
              ✕
            </button>
          </div>

          <p className="text-[11px] text-muted font-ui leading-relaxed">
            {completedNotification.message}
          </p>

          <div className="flex items-center justify-end gap-2 pt-1 border-t border-border/40">
            <button
              onClick={() => {
                if (completedNotification.targetView) {
                  setActiveView(completedNotification.targetView)
                }
                dismissNotification()
              }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-amber hover:bg-amber-light text-black text-xs font-bold font-ui transition-all shadow-xs cursor-pointer"
            >
              {completedNotification.actionLabel || 'View Analysis →'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!activeActivity) {
    return renderNotificationToast()
  }

  const isDebate = activeActivity.type === 'debate'
  const isDifferentView = activeActivity.targetView && activeActivity.targetView !== activeView

  if (isMinimized) {
    return (
      <>
        {renderNotificationToast()}
        <div className="fixed bottom-4 right-4 z-50 animate-in fade-in slide-in-from-bottom-2">
          <button
            onClick={() => setIsMinimized(false)}
            className="flex items-center gap-2 px-3.5 py-2.5 rounded-2xl bg-panel/98 border border-amber/60 shadow-2xl backdrop-blur-xl text-text text-xs font-mono cursor-pointer hover:border-amber transition-all ring-1 ring-amber/25"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber" />
            </span>
            <span className="font-bold text-amber truncate max-w-[150px]">{activeActivity.title}</span>
            <span className="text-muted text-[10px] font-bold bg-surface/80 px-1.5 py-0.5 rounded border border-border/50">
              {formatTime(elapsedSec)}
            </span>
            <span className="text-[10px] text-amber font-semibold">▲ Expand</span>
          </button>
        </div>
      </>
    )
  }

  return (
    <>
      {renderNotificationToast()}
      <div className="fixed bottom-5 right-5 z-50 max-w-sm w-full animate-in fade-in slide-in-from-bottom-3 duration-200">
        <div className="bg-panel/98 border border-amber/40 rounded-2xl p-4 shadow-2xl backdrop-blur-xl space-y-3 ring-1 ring-amber/20">
          {/* Top Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber" />
              </span>
              <span className="text-xs font-bold text-text font-mono truncate max-w-[200px]">
                {activeActivity.title}
              </span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono font-bold text-muted bg-surface/80 px-2 py-0.5 rounded-lg border border-border/50">
                ⏱ {formatTime(elapsedSec)}
              </span>
              <button
                onClick={() => setIsMinimized(true)}
                className="text-muted hover:text-text text-xs p-1 rounded transition-colors cursor-pointer"
                title="Minimize to background badge"
              >
                ▼
              </button>
            </div>
          </div>

          {/* Live Step / Detail Description */}
          <div className="bg-surface/80 border border-border/60 rounded-xl p-2.5 text-xs font-mono text-text/90">
            <p className="line-clamp-2 text-[11px] leading-relaxed text-amber/95 font-medium">
              {activeActivity.details || 'Processing multi-agent intelligence...'}
            </p>
          </div>

          {/* Non-Blocking Institutional Hint */}
          <div className="flex items-center gap-1.5 text-[10px] text-muted font-ui bg-panel/50 px-2 py-1 rounded-lg border border-border/40">
            <span>✨</span>
            <span className="leading-tight">
              Running in background — you can switch screens, view charts, or perform any action.
            </span>
          </div>

          {/* Animated Progress Shimmer Bar */}
          <div className="relative h-1.5 w-full bg-surface rounded-full overflow-hidden border border-border/40">
            <div className="absolute inset-0 bg-gradient-to-r from-amber via-emerald-400 to-cyan-400 animate-[pulse_1.5s_ease-in-out_infinite] w-full" />
          </div>

          {/* Action Controls */}
          <div className="flex items-center justify-between pt-0.5 gap-2">
            {isDifferentView ? (
              <button
                onClick={() => setActiveView(activeActivity.targetView)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-surface hover:bg-elevated border border-border text-text text-[11px] font-mono font-bold transition-all shadow-xs cursor-pointer"
                title="Switch to active analysis view"
              >
                <span>👁️</span> Switch View
              </button>
            ) : (
              <span className="text-[10px] text-muted font-ui">
                {isDebate ? 'Dual-LLM Debate' : 'Quant Engine'}
              </span>
            )}

            <button
              onClick={() => {
                cancelActiveActivity()
              }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-rose-500/15 hover:bg-rose-500 hover:text-white border border-rose-500/30 text-rose-400 text-xs font-mono font-bold transition-all shadow-xs cursor-pointer ml-auto"
              title="Immediately stop/cancel the current background task"
            >
              <span>⛔</span> Stop / Cancel
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
