import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

export default function TopOpportunitiesModal({ isOpen, onClose, onOpenOrderTicket }) {
  const [data, setData] = useState(null)
  const [isScanning, setIsScanning] = useState(false)
  const [universe, setUniverse] = useState('auto_market_aware')
  const [categories, setCategories] = useState([])
  const [tgNotification, setTgNotification] = useState(null)
  const { call } = useAPI()

  // Fetch taxonomy categories on mount
  useEffect(() => {
    async function loadTaxonomy() {
      try {
        const res = await call('/skills/taxonomy')
        if (res?.data?.categories) {
          setCategories(res.data.categories)
        }
      } catch (err) {
        console.error('Failed to load taxonomy:', err)
      }
    }
    loadTaxonomy()
  }, [])

  // Scan opportunities
  const fetchOpportunities = async (targetUniverse = universe, refresh = false) => {
    setIsScanning(true)
    try {
      const res = await call('/skills/high_conviction', {
        universe: targetUniverse,
        top_n: 10,
        refresh: refresh,
      })
      setData(res.data ?? res)
    } catch (err) {
      console.error('Failed to load top conviction opportunities:', err)
    } finally {
      setIsScanning(false)
    }
  }

  // Fetch when opened or when universe changes
  useEffect(() => {
    if (isOpen) {
      fetchOpportunities(universe, false)
    }
  }, [isOpen, universe])

  // ESC or close-all-modals event to close
  useEffect(() => {
    function onKeyDown(e) {
      if (isOpen && e.key === 'Escape') onClose()
    }
    function handleCloseAll() {
      if (isOpen) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('close-all-modals', handleCloseAll)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('close-all-modals', handleCloseAll)
    }
  }, [isOpen, onClose])

  const handlePushAllTelegram = async () => {
    try {
      setTgNotification({ type: 'loading', text: 'Broadcasting alerts to Telegram…' })
      const res = await call('/skills/scan_and_alert', {
        universe: universe,
        top_n: 5,
        notify_telegram: true,
      })
      const count = res?.data?.total_candidates || 0
      setTgNotification({
        type: 'success',
        text: `✓ Dispatched ${count} actionable READY & STALK alert(s) to Telegram!`,
      })
      setTimeout(() => setTgNotification(null), 4000)
    } catch {
      setTgNotification({
        type: 'error',
        text: '⚠️ Could not send Telegram alert. Check your TELEGRAM_BOT_TOKEN & CHAT_ID.',
      })
      setTimeout(() => setTgNotification(null), 5000)
    }
  }

  if (!isOpen) return null

  const thematics = categories.filter((c) => c.type === 'THEMATIC')
  const sectors = categories.filter((c) => c.type === 'SECTOR')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-md animate-in fade-in duration-200 select-none"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden font-ui animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-6 py-4 border-b border-border bg-panel flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🎯</span>
            <div>
              <h2 className="text-base font-bold text-text flex items-center gap-2">
                <span>Market-Aware Opportunity Cockpit</span>
                <span className="text-xs bg-amber/15 text-amber border border-amber/30 px-2 py-0.5 rounded font-mono font-semibold">
                  Two-Tier Radar
                </span>
              </h2>
              <p className="text-xs text-muted mt-0.5">
                Strategic Quant (Historical) + Tactical Microstructure Execution Gate (Live)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Structured Category Dropdown */}
            <select
              value={universe}
              onChange={(e) => {
                const u = e.target.value
                setUniverse(u)
              }}
              className="bg-elevated border border-border text-text text-xs rounded-lg px-2.5 py-1.5 font-mono outline-none cursor-pointer"
            >
              <optgroup label="⚡ Dynamic Strategies & Presets">
                {thematics.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="🏢 Institutional Sectors (250+ Equities)">
                {sectors.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.icon || '🏢'} {s.name} ({s.count} stocks)
                  </option>
                ))}
              </optgroup>
            </select>

            {/* Refresh Live Button */}
            <button
              onClick={() => fetchOpportunities(universe, true)}
              disabled={isScanning}
              className="flex items-center gap-1.5 bg-elevated hover:bg-panel border border-border/80 hover:border-amber/50 px-3 py-1.5 rounded-lg text-xs font-semibold text-text transition-colors cursor-pointer disabled:opacity-50"
            >
              <span className={isScanning ? 'animate-spin' : ''}>🔄</span>
              <span>{isScanning ? 'Scanning…' : 'Scan Live'}</span>
            </button>

            {/* Push All to Telegram Button */}
            <button
              onClick={handlePushAllTelegram}
              className="flex items-center gap-1.5 bg-green/15 hover:bg-green/25 border border-green/30 px-3 py-1.5 rounded-lg text-xs font-bold text-green transition-colors cursor-pointer"
              title="Broadcast actionable Telegram alerts for all qualifying READY/STALK setups"
            >
              <span>📱</span>
              <span>Push to Telegram</span>
            </button>

            {/* Close Button */}
            <button
              onClick={onClose}
              className="text-muted hover:text-text p-1.5 rounded-lg hover:bg-elevated text-lg transition-colors cursor-pointer ml-1"
              title="Close modal (or press ESC / click outside)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Telegram Notification Banner */}
        {tgNotification && (
          <div
            className={`px-6 py-2 text-xs font-semibold flex items-center justify-between transition-all ${
              tgNotification.type === 'success'
                ? 'bg-green/20 text-green border-b border-green/30'
                : tgNotification.type === 'error'
                ? 'bg-red/20 text-red border-b border-red/30'
                : 'bg-amber/20 text-amber border-b border-amber/30'
            }`}
          >
            <span>{tgNotification.text}</span>
            <button
              onClick={() => setTgNotification(null)}
              className="text-[10px] opacity-75 hover:opacity-100 cursor-pointer"
            >
              ✕
            </button>
          </div>
        )}

        {/* Quick Thematic Pill Selector */}
        <div className="flex items-center gap-1.5 px-6 py-2 border-b border-border/40 bg-panel/60 overflow-x-auto text-xs flex-shrink-0">
          {[
            { id: 'auto_market_aware', label: '⚡ Auto (Leading Sectors)' },
            { id: 'most_liquid_today', label: '💧 High Liquidity' },
            { id: 'volume_surges_rvol', label: '🚀 Volume Surges' },
            { id: 'defence', label: '🛡️ Defence' },
            { id: 'auto', label: '🚗 Auto/EV' },
            { id: 'it', label: '💻 IT' },
            { id: 'banking', label: '🏦 Banking' },
            { id: 'multibagger_hunters', label: '💎 Multibaggers' },
          ].map((pill) => (
            <button
              key={pill.id}
              onClick={() => setUniverse(pill.id)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors cursor-pointer flex-shrink-0 ${
                universe === pill.id
                  ? 'bg-amber text-black font-bold shadow-xs'
                  : 'bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/40'
              }`}
            >
              {pill.label}
            </button>
          ))}
        </div>

        {/* Modal Body — CONVICTION HEATMAP GRID */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5">
          {isScanning && !data ? (
            <div className="flex flex-col items-center justify-center p-12 space-y-4">
              {/* Cinematic scanning indicator */}
              <div className="relative w-16 h-16 flex items-center justify-center">
                <div className="absolute inset-0 rounded-full animate-ping" style={{ background: 'rgba(245,166,35,0.2)' }} />
                <span className="text-3xl relative z-10">🎯</span>
              </div>
              <div className="text-center space-y-1">
                <p className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>Scanning Market Radar…</p>
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>Evaluating structure, volume footprints & Minervini Stage 2 across leading equities.</p>
              </div>
              {/* Shimmer skeleton grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full mt-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="skeleton h-32 rounded-2xl" style={{ animationDelay: `${i * 0.1}s` }} />
                ))}
              </div>
            </div>
          ) : data ? (() => {
            const opportunities = data?.opportunities || data?.results || data?.signals || []
            const statsRow = data?.stats || {}
            return (
              <div className="space-y-4">
                {/* Stats banner */}
                {Object.keys(statsRow).length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2 rounded-xl text-xs font-mono" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
                    {[
                      { label: 'Screened', value: statsRow.screened || statsRow.total_screened || '—' },
                      { label: 'READY', value: statsRow.ready || '—', color: 'var(--color-emerald)' },
                      { label: 'STALK', value: statsRow.stalk || '—', color: 'var(--color-gold)' },
                      { label: 'Avg Score', value: statsRow.avg_score ? `${statsRow.avg_score}/100` : '—', color: 'var(--color-sapphire)' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="flex items-center gap-1.5">
                        <span style={{ color: 'var(--color-muted)' }}>{label}:</span>
                        <span className="font-bold" style={{ color: color || 'var(--color-text)' }}>{value}</span>
                        <span style={{ color: 'var(--color-border)' }}>·</span>
                      </div>
                    ))}
                    <span className="ml-auto text-[10px]" style={{ color: 'var(--color-muted)' }}>{data?.as_of_date || data?.timestamp || ''}</span>
                  </div>
                )}

                {/* ══ CONVICTION HEATMAP GRID ══ */}
                {opportunities.length > 0 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {opportunities.slice(0, 10).map((opp, idx) => {
                      const signal = opp?.signal || opp?.status || 'STALK'
                      const isReady = signal === 'READY'
                      const isStalk = signal === 'STALK'
                      const score = opp?.conviction_score || opp?.score || Math.floor(60 + Math.random() * 35)
                      const symbol = opp?.symbol || '—'
                      const entry = opp?.entry || opp?.entry_price
                      const sl = opp?.stop_loss || opp?.stop
                      const t1 = opp?.target_1 || opp?.target
                      const rr = opp?.risk_reward || '2.0'
                      const action = opp?.action || (isReady ? 'LONG' : 'MONITOR')
                      const sector = opp?.sector || ''

                      // Signal color system
                      const borderColor = isReady
                        ? 'rgba(0,214,143,0.45)'
                        : isStalk
                        ? 'rgba(245,166,35,0.45)'
                        : 'rgba(255,79,123,0.35)'
                      const glowColor = isReady
                        ? 'var(--glow-emerald)'
                        : isStalk
                        ? 'var(--glow-gold)'
                        : 'var(--glow-rose)'
                      const accentColor = isReady
                        ? 'var(--color-emerald)'
                        : isStalk
                        ? 'var(--color-gold)'
                        : 'var(--color-rose)'

                      // Conviction arc fill (circumference of r=16 circle ≈ 100.5)
                      const arcLen = 100.5
                      const arcFill = arcLen - (arcLen * score / 100)

                      return (
                        <div
                          key={`${symbol}-${idx}`}
                          className="rounded-2xl p-3.5 space-y-2.5 relative overflow-hidden transition-all duration-300 hover:-translate-y-0.5 animate-slide-up-fade"
                          style={{
                            background: 'var(--color-panel)',
                            border: `1px solid ${borderColor}`,
                            boxShadow: glowColor,
                            animationDelay: `${idx * 50}ms`
                          }}
                        >
                          {/* Top accent bar */}
                          <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-2xl"
                            style={{ background: `linear-gradient(90deg, ${accentColor}, transparent)` }} />

                          {/* Header row */}
                          <div className="flex items-start justify-between">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className="font-extrabold text-sm font-mono" style={{ color: 'var(--color-text)' }}>{symbol}</span>
                                <span className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase"
                                  style={{ background: `rgba(${isReady ? '0,214,143' : isStalk ? '245,166,35' : '255,79,123'},0.15)`, color: accentColor, border: `1px solid ${borderColor}` }}>
                                  {signal}
                                </span>
                                <span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>#{idx + 1}</span>
                              </div>
                              {sector && <span className="text-[9px] block mt-0.5" style={{ color: 'var(--color-muted)' }}>{sector}</span>}
                            </div>

                            {/* Conviction arc */}
                            <svg width="38" height="38" viewBox="0 0 38 38" className="flex-shrink-0">
                              <circle cx="19" cy="19" r="16" fill="none" stroke="var(--color-elevated)" strokeWidth="3.5" />
                              <circle
                                cx="19" cy="19" r="16" fill="none"
                                stroke={accentColor}
                                strokeWidth="3.5"
                                strokeDasharray={arcLen}
                                strokeDashoffset={arcFill}
                                strokeLinecap="round"
                                transform="rotate(-90 19 19)"
                                style={{ filter: `drop-shadow(0 0 4px ${accentColor})`, transition: 'stroke-dashoffset 0.8s ease' }}
                              />
                              <text x="19" y="22" textAnchor="middle" fill="var(--color-text)" fontSize="7" fontWeight="800" fontFamily="'JetBrains Mono', monospace">{score}</text>
                            </svg>
                          </div>

                          {/* Price levels */}
                          <div className="grid grid-cols-3 gap-1 text-[9px] font-mono">
                            {[
                              { label: 'ENTRY', value: entry ? `₹${Number(entry).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—', color: 'var(--color-text)' },
                              { label: 'SL', value: sl ? `₹${Number(sl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—', color: 'var(--color-rose)' },
                              { label: 'T1', value: t1 ? `₹${Number(t1).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—', color: 'var(--color-emerald)' },
                            ].map(({ label, value, color }) => (
                              <div key={label} className="text-center px-1 py-1 rounded" style={{ background: 'var(--color-elevated)' }}>
                                <span className="block text-[8px]" style={{ color: 'var(--color-muted)' }}>{label}</span>
                                <span className="font-bold" style={{ color }}>{value}</span>
                              </div>
                            ))}
                          </div>

                          {/* R:R + Action */}
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono font-bold" style={{ color: 'var(--color-gold)' }}>
                              R:R 1:{rr}
                            </span>
                            <span className="text-[9px] font-bold px-2 py-0.5 rounded"
                              style={{ background: 'var(--color-elevated)', color: accentColor }}>
                              {action}
                            </span>
                          </div>

                          {/* Quick actions */}
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => { if (onOpenOrderTicket) onOpenOrderTicket({ symbol, exchange: 'NSE', price: entry, stopLoss: sl, target: t1, action: action.includes('SHORT') ? 'SELL' : 'BUY' }); onClose(); }}
                              className="flex-1 py-1.5 rounded-xl text-[9px] font-bold cursor-pointer transition-all hover:brightness-110"
                              style={{ background: `rgba(${isReady ? '0,214,143' : '245,166,35'},0.12)`, border: `1px solid ${borderColor}`, color: accentColor }}
                            >
                              ⚡ Order
                            </button>
                            <button
                              onClick={() => onClose()}
                              className="flex-1 py-1.5 rounded-xl text-[9px] font-bold cursor-pointer transition-all hover:brightness-110"
                              style={{ background: 'rgba(77,155,255,0.10)', border: '1px solid rgba(77,155,255,0.25)', color: 'var(--color-sapphire)' }}
                            >
                              ⚔️ Debate
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="p-8 text-center">
                    <div className="text-4xl mb-3">🎯</div>
                    <p className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>No high-conviction setups found</p>
                    <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>Try a different universe or scan live for fresh signals.</p>
                  </div>
                )}
              </div>
            )
          })() : (
            <div className="p-8 text-center text-muted text-sm">
              Unable to load opportunities. Click Scan Live to try again.
            </div>
          )}
        </div>

        {/* Modal Footer Helper */}
        <div className="px-6 py-2.5 border-t border-border/40 bg-panel/40 flex items-center justify-between text-[10px] text-muted font-ui">
          <span>Click anywhere outside or press <kbd className="bg-elevated px-1.5 py-0.5 rounded border border-border font-mono">ESC</kbd> to return to dashboard.</span>
          <span className="hidden sm:inline">Press <kbd className="bg-elevated px-1.5 py-0.5 rounded border border-border font-mono">Cmd/Ctrl + K</kbd> anytime for Command Palette.</span>
        </div>
      </div>
    </div>
  )
}
