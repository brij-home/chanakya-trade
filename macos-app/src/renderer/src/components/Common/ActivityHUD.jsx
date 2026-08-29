import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'

export default function ActivityHUD() {
  const activeActivity = useChatStore((s) => s.activeActivity)
  const cancelActiveActivity = useChatStore((s) => s.cancelActiveActivity)
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

  if (!activeActivity) return null

  const formatTime = (sec) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}:${s < 10 ? '0' : ''}${s}s`
  }

  const isDebate = activeActivity.type === 'debate'

  if (isMinimized) {
    return (
      <div className="fixed bottom-4 right-4 z-50 animate-in fade-in slide-in-from-bottom-2">
        <button
          onClick={() => setIsMinimized(false)}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-panel/95 border border-amber/50 shadow-2xl backdrop-blur-md text-text text-xs font-mono cursor-pointer hover:border-amber transition-all"
        >
          <span className="w-2 h-2 rounded-full bg-amber animate-ping" />
          <span className="font-bold text-amber truncate max-w-[140px]">{activeActivity.title}</span>
          <span className="text-muted text-[10px]">{formatTime(elapsedSec)}</span>
          <span className="text-[10px] text-muted">▲ Expand</span>
        </button>
      </div>
    )
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 max-w-sm w-full animate-in fade-in slide-in-from-bottom-3 duration-200">
      <div className="bg-panel/95 border border-amber/40 rounded-2xl p-3.5 shadow-2xl backdrop-blur-xl space-y-2.5 ring-1 ring-amber/20">
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
            <span className="text-[10px] font-mono text-muted bg-surface/80 px-1.5 py-0.5 rounded border border-border/50">
              ⏱ {formatTime(elapsedSec)}
            </span>
            <button
              onClick={() => setIsMinimized(true)}
              className="text-muted hover:text-text text-xs px-1 rounded transition-colors"
              title="Minimize HUD"
            >
              ▼
            </button>
          </div>
        </div>

        {/* Live Step / Detail Description */}
        <div className="bg-surface/80 border border-border/60 rounded-xl p-2 text-xs font-mono text-text/90">
          <p className="line-clamp-2 text-[11px] leading-relaxed text-amber/90">
            {activeActivity.details || 'Processing multi-agent intelligence...'}
          </p>
        </div>

        {/* Animated Progress Shimmer Bar */}
        <div className="relative h-1.5 w-full bg-surface rounded-full overflow-hidden border border-border/40">
          <div className="absolute inset-0 bg-gradient-to-r from-amber via-emerald-400 to-cyan-400 animate-[pulse_1.5s_ease-in-out_infinite] w-full" />
        </div>

        {/* Action Controls */}
        <div className="flex items-center justify-between pt-0.5">
          <span className="text-[10px] text-muted font-ui">
            {isDebate ? 'Dual-LLM Multi-Agent Debate' : 'Institutional Quant Engine'}
          </span>
          <button
            onClick={() => {
              cancelActiveActivity()
            }}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-rose-500/15 hover:bg-rose-500 hover:text-white border border-rose-500/30 text-rose-400 text-xs font-mono font-bold transition-all shadow-xs cursor-pointer"
            title="Immediately stop the current activity"
          >
            <span>⛔</span> Stop / Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
