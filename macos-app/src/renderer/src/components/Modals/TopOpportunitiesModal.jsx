import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import HighConvictionCard from '../Cards/HighConvictionCard'

export default function TopOpportunitiesModal({ isOpen, onClose }) {
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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200 select-none"
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

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {isScanning && !data ? (
            <div className="flex flex-col items-center justify-center p-12 space-y-3">
              <span className="text-3xl animate-spin">⏳</span>
              <p className="text-sm font-semibold text-text">Performing top-down sector analysis & liquidity screening…</p>
              <p className="text-xs text-muted">Evaluating structure, volume footprints & Minervini Stage 2 across leading equities.</p>
            </div>
          ) : data ? (
            <HighConvictionCard data={data} />
          ) : (
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
