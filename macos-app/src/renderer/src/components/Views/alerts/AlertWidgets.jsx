import React from 'react'

export function RRMiniBar({ sl, entry, t1, t2, t3, currentPrice, isUpward = true }) {
  if (!sl || !entry || !t1) return null
  const totalRange = Math.abs((t3 || t2 || t1) - sl)
  if (totalRange <= 0) return null
  const slW = Math.max(4, Math.round((Math.abs(entry - sl) / totalRange) * 100))
  const t1W = Math.max(4, Math.round((Math.abs(t1 - entry) / totalRange) * 100))
  const t2W = t2 ? Math.max(4, Math.round((Math.abs(t2 - t1) / totalRange) * 100)) : 0
  const t3W = t3 ? Math.max(4, Math.round((Math.abs((t3 || t2) - (t2 || t1)) / totalRange) * 100)) : 0
  const rem = 100 - slW - t1W - t2W - t3W

  let curPct = null
  if (currentPrice && totalRange > 0) {
    const dist = isUpward ? currentPrice - sl : sl - currentPrice
    curPct = Math.min(100, Math.max(0, Math.round((dist / totalRange) * 100)))
  }

  return (
    <div className="relative flex h-1.5 rounded-full overflow-hidden w-full bg-zinc-800" title={`SL→T1→T2→T3 R:R runway`}>
      <div style={{ width: `${slW}%` }} className="bg-rose-500/70" />
      <div style={{ width: `${t1W + Math.max(0, rem)}%` }} className="bg-emerald-500/60" />
      {t2W > 0 && <div style={{ width: `${t2W}%` }} className="bg-cyan-500/60" />}
      {t3W > 0 && <div style={{ width: `${t3W}%` }} className="bg-purple-500/50" />}
      {curPct !== null ? (
        <div
          className="absolute top-0 bottom-0 w-1 bg-white rounded-full shadow-[0_0_4px_rgba(255,255,255,1)]"
          style={{ left: `${curPct}%` }}
        />
      ) : null}
    </div>
  )
}

export function MilestoneDots({ targetStatus, stage, isSLHit = false }) {
  if (isSLHit || stage === 'INVALIDATED') {
    return (
      <span className="flex items-center gap-0.5 font-mono text-[9px] text-rose-400 font-bold" title="Stop-Loss Hit / Invalidated">
        <span>🛑</span>
      </span>
    )
  }

  const t1Hit = stage === 'T1_ACHIEVED' || targetStatus === 'T1_ACHIEVED' || targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED' || stage === 'COMPLETED'
  const t2Hit = stage === 'T2_ACHIEVED' || targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED' || stage === 'COMPLETED'
  const t3Hit = stage === 'TARGET_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED' || stage === 'COMPLETED'

  return (
    <span className="flex items-center gap-1 font-mono text-[9px]" title="Target Milestones: T1 → T2 → T3">
      <span className={`transition-all ${t1Hit ? 'text-emerald-400 font-black scale-110 drop-shadow-[0_0_4px_rgba(16,185,129,0.8)]' : 'text-zinc-600'}`}>
        ●
      </span>
      <span className={`transition-all ${t2Hit ? 'text-cyan-300 font-black scale-110 drop-shadow-[0_0_4px_rgba(6,182,212,0.8)]' : 'text-zinc-600'}`}>
        ●
      </span>
      <span className={`transition-all ${t3Hit ? 'text-purple-300 font-black scale-110 drop-shadow-[0_0_4px_rgba(168,85,247,0.8)]' : 'text-zinc-600'}`}>
        ●
      </span>
    </span>
  )
}
