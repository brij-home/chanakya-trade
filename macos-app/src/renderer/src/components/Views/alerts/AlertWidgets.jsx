import React from 'react'

export function RRMiniBar({ sl, entry, t1, t2, t3, isUpward = true }) {
  if (!sl || !entry || !t1) return null
  const totalRange = Math.abs((t3 || t2 || t1) - sl)
  if (totalRange <= 0) return null
  const slW = Math.max(4, Math.round((Math.abs(entry - sl) / totalRange) * 100))
  const t1W = Math.max(4, Math.round((Math.abs(t1 - entry) / totalRange) * 100))
  const t2W = t2 ? Math.max(4, Math.round((Math.abs(t2 - t1) / totalRange) * 100)) : 0
  const t3W = t3 ? Math.max(4, Math.round((Math.abs((t3 || t2) - (t2 || t1)) / totalRange) * 100)) : 0
  const rem = 100 - slW - t1W - t2W - t3W
  return (
    <div className="flex h-1 rounded-full overflow-hidden w-full" title={`SL→T1→T2→T3 R:R breakdown`}>
      <div style={{ width: `${slW}%` }} className="bg-rose-500/70" />
      <div style={{ width: `${t1W + Math.max(0, rem)}%` }} className="bg-emerald-500/60" />
      {t2W > 0 && <div style={{ width: `${t2W}%` }} className="bg-cyan-500/60" />}
      {t3W > 0 && <div style={{ width: `${t3W}%` }} className="bg-purple-500/50" />}
    </div>
  )
}

export function MilestoneDots({ targetStatus, stage }) {
  const t1Hit = stage === 'T1_ACHIEVED' || targetStatus === 'T1_ACHIEVED' || targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED'
  const t2Hit = targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED'
  const t3Hit = targetStatus === 'TARGET_ACHIEVED'
  return (
    <span className="flex items-center gap-0.5 font-mono text-[9px]" title="T1 → T2 → T3 milestones">
      <span className={t1Hit ? 'text-emerald-400' : 'text-zinc-600'}>●</span>
      <span className={t2Hit ? 'text-cyan-400' : 'text-zinc-600'}>●</span>
      <span className={t3Hit ? 'text-purple-300' : 'text-zinc-600'}>●</span>
    </span>
  )
}
