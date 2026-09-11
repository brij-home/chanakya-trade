import { useState, useEffect, useCallback } from 'react'
import { useAPI } from '../../hooks/useAPI'

const SEGMENTS = [
  {
    id: 'FNO_INDEX',
    name: 'F&O Indices',
    icon: '⚡',
    badge: 'NIFTY / BANKNIFTY / SENSEX',
    desc: 'Index Options, 0DTE gamma scalps, Straddles, Index Futures (NSE & BSE)',
    color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30',
  },
  {
    id: 'FNO_STOCK',
    name: 'F&O Stocks',
    icon: '🎯',
    badge: 'NSE Stock Derivatives',
    desc: 'Single-stock futures and options momentum, volume breakouts, earnings gamma',
    color: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  },
  {
    id: 'EQUITY',
    name: 'Cash Equity',
    icon: '🏢',
    badge: 'NSE / BSE Cash',
    desc: 'Large, Mid & Small-cap breakouts, Precursor Radar setups, Squeeze Breakouts, Circuits',
    color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  },
  {
    id: 'COMMODITY',
    name: 'Commodity',
    icon: '🌙',
    badge: 'MCX Evening',
    desc: 'CRUDEOIL, GOLD, SILVER, NATURALGAS, COPPER momentum & inventory shifts',
    color: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  },
  {
    id: 'CURRENCY',
    name: 'Currency',
    icon: '💱',
    badge: 'CDS Desk',
    desc: 'USDINR, EURINR, GBPINR, JPYINR forex volatility & break-of-structure',
    color: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
  },
]

const ALL_CANONICAL_SEGMENTS = ['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY']

function normalizeSegs(list) {
  if (!Array.isArray(list)) return ALL_CANONICAL_SEGMENTS
  const out = []
  for (const s of list) {
    if (s === 'FNO' || s === 'F&O') {
      if (!out.includes('FNO_INDEX')) out.push('FNO_INDEX')
      if (!out.includes('FNO_STOCK')) out.push('FNO_STOCK')
    } else if (s === 'ALL') {
      return ALL_CANONICAL_SEGMENTS
    } else if (ALL_CANONICAL_SEGMENTS.includes(s)) {
      if (!out.includes(s)) out.push(s)
    }
  }
  return out.length > 0 ? out : ALL_CANONICAL_SEGMENTS
}

export default function AlertRoutingModal({ isOpen, onClose, onSaveSuccess }) {
  const { call } = useAPI()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [error, setError] = useState(null)

  // Preferences state
  const [uiSegments, setUiSegments] = useState(ALL_CANONICAL_SEGMENTS)
  const [tgSegments, setTgSegments] = useState(ALL_CANONICAL_SEGMENTS)
  const [tgEnabled, setTgEnabled] = useState(true)
  const [tgMinConfidence, setTgMinConfidence] = useState(80)
  const [soundSegments, setSoundSegments] = useState(ALL_CANONICAL_SEGMENTS)
  const [pauseDisabled, setPauseDisabled] = useState(true)

  // Load preferences from backend
  const loadPreferences = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await call('/skills/alerts/preferences')
      const data = res?.data || res || {}
      if (data.allowed_segments) {
        setUiSegments(normalizeSegs(data.ui?.allowed_segments || data.allowed_segments))
      }
      if (data.telegram) {
        setTgSegments(normalizeSegs(data.telegram.allowed_segments))
        setTgEnabled(data.telegram.enabled !== false)
        setTgMinConfidence(data.telegram.min_confidence || 80)
      }
      if (data.sound) {
        setSoundSegments(normalizeSegs(data.sound.allowed_segments))
      }
      if (data.pause_disabled_scanners !== undefined) {
        setPauseDisabled(Boolean(data.pause_disabled_scanners))
      }
    } catch (err) {
      setError('Could not load preferences from server. Using local defaults.')
    } finally {
      setLoading(false)
    }
  }, [call])

  useEffect(() => {
    if (isOpen) {
      setSaveSuccess(false)
      loadPreferences()
    }
  }, [isOpen, loadPreferences])

  // Keyboard shortcut: Escape to close
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  // Helpers to toggle segment for a specific channel
  const toggleSegment = (channel, segId) => {
    if (channel === 'ui') {
      setUiSegments((prev) =>
        prev.includes(segId) ? prev.filter((s) => s !== segId) : [...prev, segId]
      )
    } else if (channel === 'telegram') {
      setTgSegments((prev) =>
        prev.includes(segId) ? prev.filter((s) => s !== segId) : [...prev, segId]
      )
    } else if (channel === 'sound') {
      setSoundSegments((prev) =>
        prev.includes(segId) ? prev.filter((s) => s !== segId) : [...prev, segId]
      )
    }
  }

  // Presets
  const applyPreset = (preset) => {
    if (preset === 'ALL') {
      setUiSegments(ALL_CANONICAL_SEGMENTS)
      setTgSegments(ALL_CANONICAL_SEGMENTS)
      setSoundSegments(ALL_CANONICAL_SEGMENTS)
    } else if (preset === 'INDEX_ONLY') {
      const idx = ['FNO_INDEX']
      setUiSegments(idx)
      setTgSegments(idx)
      setSoundSegments(idx)
    } else if (preset === 'ALL_FNO') {
      const fno = ['FNO_INDEX', 'FNO_STOCK']
      setUiSegments(fno)
      setTgSegments(fno)
      setSoundSegments(fno)
    } else if (preset === 'FNO_EQUITY') {
      const fe = ['FNO_INDEX', 'FNO_STOCK', 'EQUITY']
      setUiSegments(fe)
      setTgSegments(fe)
      setSoundSegments(fe)
    } else if (preset === 'EQUITY_ONLY') {
      setUiSegments(['EQUITY'])
      setTgSegments(['EQUITY'])
      setSoundSegments(['EQUITY'])
    }
  }

  // Save handler
  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const payload = {
        allowed_segments: uiSegments.length > 0 ? uiSegments : ALL_CANONICAL_SEGMENTS,
        ui: {
          enabled: true,
          allowed_segments: uiSegments,
        },
        telegram: {
          enabled: tgEnabled,
          allowed_segments: tgSegments,
          min_confidence: tgMinConfidence,
        },
        sound: {
          enabled: true,
          allowed_segments: soundSegments,
        },
        desktop: {
          enabled: true,
          allowed_segments: uiSegments,
        },
        pause_disabled_scanners: pauseDisabled,
      }

      await call('/skills/alerts/preferences', payload)
      setSaveSuccess(true)
      if (onSaveSuccess) onSaveSuccess(payload)
      setTimeout(() => {
        onClose()
      }, 750)
    } catch (err) {
      setError(err?.message || 'Failed to save alert preferences.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm select-none animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="bg-panel border border-border/80 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl font-ui text-text flex flex-col max-h-[90vh] animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/60 bg-elevated/40">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚙️</span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md font-bold font-mono bg-gold/15 text-gold border border-gold/30">
                  Institutional Routing
                </span>
                <span className="text-[10px] text-muted font-mono">
                  Omni-Channel Filter
                </span>
              </div>
              <h2 className="text-base font-bold text-text mt-0.5">
                Alert Delivery & Market Segment Matrix
              </h2>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-muted hover:text-text hover:bg-elevated transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1 text-xs font-sans">
          {error && (
            <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
              <span>⚠️</span>
              <span>{error}</span>
            </div>
          )}

          {/* Quick Presets Bar */}
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-surface border border-border/60">
            <span className="text-[11px] font-bold text-muted uppercase tracking-wider">
              Quick Presets:
            </span>
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                type="button"
                onClick={() => applyPreset('ALL')}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-elevated hover:bg-gold/20 hover:text-gold transition-colors"
              >
                🌐 All Markets
              </button>
              <button
                type="button"
                onClick={() => applyPreset('INDEX_ONLY')}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-elevated hover:bg-indigo-500/20 hover:text-indigo-300 transition-colors"
              >
                ⚡ Index F&O Only
              </button>
              <button
                type="button"
                onClick={() => applyPreset('ALL_FNO')}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-elevated hover:bg-purple-500/20 hover:text-purple-300 transition-colors"
              >
                🎯 All F&O (Index + Stocks)
              </button>
              <button
                type="button"
                onClick={() => applyPreset('FNO_EQUITY')}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-elevated hover:bg-gold/20 hover:text-gold transition-colors"
              >
                ⚡ F&O + 🏢 Equity
              </button>
              <button
                type="button"
                onClick={() => applyPreset('EQUITY_ONLY')}
                className="px-2.5 py-1 rounded-lg text-xs font-medium bg-elevated hover:bg-emerald-500/20 hover:text-emerald-300 transition-colors"
              >
                🏢 Equity Only
              </button>
            </div>
          </div>

          {/* Segment Matrix Table */}
          <div className="rounded-xl border border-border/70 overflow-hidden bg-surface/50">
            <div className="grid grid-cols-12 px-3 py-2 bg-elevated/70 border-b border-border/70 text-[11px] font-bold text-muted uppercase tracking-wider">
              <div className="col-span-6">Market Segment</div>
              <div className="col-span-2 text-center">🖥️ UI Feed</div>
              <div className="col-span-2 text-center">📱 Telegram</div>
              <div className="col-span-2 text-center">🔔 Chime</div>
            </div>

            <div className="divide-y divide-border/40">
              {SEGMENTS.map((seg) => {
                const uiActive = uiSegments.includes(seg.id)
                const tgActive = tgSegments.includes(seg.id)
                const soundActive = soundSegments.includes(seg.id)

                return (
                  <div
                    key={seg.id}
                    className="grid grid-cols-12 px-3 py-3 items-center hover:bg-elevated/20 transition-colors"
                  >
                    {/* Segment Info */}
                    <div className="col-span-6 pr-2">
                      <div className="flex items-center gap-2">
                        <span className="text-base">{seg.icon}</span>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-text text-xs">{seg.name}</span>
                            <span
                              className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${seg.color}`}
                            >
                              {seg.badge}
                            </span>
                          </div>
                          <p className="text-[10px] text-muted line-clamp-1 mt-0.5">{seg.desc}</p>
                        </div>
                      </div>
                    </div>

                    {/* UI Toggle */}
                    <div className="col-span-2 flex justify-center">
                      <button
                        type="button"
                        onClick={() => toggleSegment('ui', seg.id)}
                        className={`w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs transition-all ${
                          uiActive
                            ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 shadow-sm'
                            : 'bg-elevated/40 text-muted hover:text-text border border-border'
                        }`}
                        title={uiActive ? 'Active in UI — Click to disable' : 'Disabled in UI — Click to enable'}
                      >
                        {uiActive ? '✓' : '—'}
                      </button>
                    </div>

                    {/* Telegram Toggle */}
                    <div className="col-span-2 flex justify-center">
                      <button
                        type="button"
                        onClick={() => toggleSegment('telegram', seg.id)}
                        className={`w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs transition-all ${
                          tgActive && tgEnabled
                            ? 'bg-indigo-500/25 text-indigo-300 border border-indigo-500/50 shadow-sm'
                            : 'bg-elevated/40 text-muted hover:text-text border border-border'
                        }`}
                        title={tgActive ? 'Pushed to Telegram — Click to disable' : 'Muted on Telegram — Click to enable'}
                      >
                        {tgActive && tgEnabled ? '✓' : '—'}
                      </button>
                    </div>

                    {/* Chime Toggle */}
                    <div className="col-span-2 flex justify-center">
                      <button
                        type="button"
                        onClick={() => toggleSegment('sound', seg.id)}
                        className={`w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs transition-all ${
                          soundActive
                            ? 'bg-amber-500/25 text-amber-300 border border-amber-500/50 shadow-sm'
                            : 'bg-elevated/40 text-muted hover:text-text border border-border'
                        }`}
                        title={soundActive ? 'Sound chime active — Click to mute' : 'Chime muted — Click to enable'}
                      >
                        {soundActive ? '🔔' : '—'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Telegram Settings Section */}
          <div className="p-3.5 rounded-xl bg-surface border border-border/70 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span>📱</span>
                <div>
                  <span className="font-bold text-xs">Telegram Push Master Control</span>
                  <p className="text-[10px] text-muted">Toggle all Telegram pushes or configure min conviction threshold</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={tgEnabled}
                  onChange={(e) => setTgEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-elevated peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-gold"></div>
              </label>
            </div>

            {tgEnabled && (
              <div className="flex items-center justify-between pt-2 border-t border-border/40 text-xs">
                <span className="text-muted">Minimum Conviction to Buzz Mobile:</span>
                <div className="flex items-center gap-2">
                  {[75, 80, 85, 90].map((conf) => (
                    <button
                      key={conf}
                      type="button"
                      onClick={() => setTgMinConfidence(conf)}
                      className={`px-2 py-0.5 rounded text-xs font-mono font-bold transition-all ${
                        tgMinConfidence === conf
                          ? 'bg-gold text-surface shadow-sm'
                          : 'bg-elevated text-muted hover:text-text'
                      }`}
                    >
                      {conf}%+
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Background Scanner Optimization Toggle */}
          <div className="flex items-center justify-between p-3 rounded-xl bg-surface/80 border border-border/60">
            <div className="flex items-center gap-2">
              <span>⚡</span>
              <div>
                <span className="font-bold text-xs">Auto-Pause Disabled Market Scanners</span>
                <p className="text-[10px] text-muted">
                  Skips background polling loops for segments disabled across all channels (saves CPU & API limits)
                </p>
              </div>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={pauseDisabled}
                onChange={(e) => setPauseDisabled(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-elevated peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
            </label>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-5 py-3.5 border-t border-border/60 bg-elevated/40">
          <span className="text-[11px] text-muted font-mono">
            {saveSuccess ? (
              <span className="text-emerald-400 font-bold">✓ Preferences saved & synced</span>
            ) : (
              'Synced with backend engine & Telegram'
            )}
          </span>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg border border-border text-xs text-muted hover:text-text hover:bg-elevated transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="btn btn-sm btn-gold text-xs font-bold px-4 py-1.5 flex items-center gap-1.5 shadow-sm"
            >
              {saving ? 'Saving…' : saveSuccess ? '✓ Saved!' : 'Save Preferences'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
