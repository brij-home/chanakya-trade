/**
 * ModeBanner — P0-A Truthful Data Envelope
 * Persistent top-of-app banner showing the current application mode.
 * Enforced server-side; this component only renders the mode it receives.
 *
 * Modes:
 *   PAPER — Real data sources (yfinance), simulated execution (default)
 *   DEMO  — Synthetic fixture data, clearly labelled, cannot touch real accounts
 *   LIVE  — Real data + real broker execution (requires activation)
 *
 * @param {'PAPER'|'DEMO'|'LIVE'} mode
 * @param {boolean} [loading]  — true while mode is being fetched from server
 * @param {object} [pilotSafety] — server-authoritative personal pilot limits
 */
export default function ModeBanner({ mode, loading = false, pilotSafety = null }) {
  if (loading) return null

  const cfg = MODE_CONFIG[mode] ?? MODE_CONFIG.PAPER

  return (
    <div
      id="app-mode-banner"
      className="flex items-center justify-center gap-2 px-4 py-1 text-[10px] font-mono font-bold tracking-widest border-b"
      style={{
        background: cfg.bg,
        borderColor: cfg.borderColor,
        color: cfg.color,
      }}
      role="status"
      aria-live="polite"
      aria-label={`Application mode: ${cfg.label}. ${cfg.description}`}
    >
      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: cfg.dotColor }} aria-hidden="true" />
      <span>{cfg.label}</span>
      <span className="opacity-60 font-normal normal-case tracking-normal">{cfg.description}</span>
      {mode === 'DEMO' && (
        <span
          className="ml-2 px-1.5 py-0.5 rounded border text-[9px] font-bold"
          style={{
            background: 'rgba(217, 70, 239, 0.15)',
            borderColor: 'rgba(217, 70, 239, 0.4)',
            color: '#e879f9',
          }}
        >
          DATA IS SYNTHETIC — NOT FOR TRADING
        </span>
      )}
      {pilotSafety && (
        <span
          className="ml-2 px-1.5 py-0.5 rounded border text-[9px] font-bold"
          style={{
            background: pilotSafety.live_execution_enabled ? 'rgba(255, 79, 123, 0.12)' : 'rgba(57, 217, 138, 0.10)',
            borderColor: pilotSafety.live_execution_enabled ? 'rgba(255, 79, 123, 0.45)' : 'rgba(57, 217, 138, 0.35)',
            color: pilotSafety.live_execution_enabled ? '#ff8aa6' : '#65e9a9',
          }}
          title={`Pilot profile: ${pilotSafety.profile}. Allowed: ${(pilotSafety.allowed_segments || []).join(', ')}. Max order: ₹${pilotSafety.max_order_notional ?? '—'}.`}
        >
          {pilotSafety.live_execution_enabled
            ? `PILOT LIMIT ₹${pilotSafety.max_order_notional ?? '—'}`
            : 'PILOT EXECUTION LOCKED'}
        </span>
      )}
    </div>
  )
}

// ── Configuration ──────────────────────────────────────────────────────────

const MODE_CONFIG = {
  PAPER: {
    label: '📋 PAPER MODE',
    description: 'Real data · Simulated execution · No real orders',
    bg: 'rgba(245, 166, 35, 0.06)',
    borderColor: 'rgba(245, 166, 35, 0.2)',
    color: 'rgba(245, 166, 35, 0.9)',
    dotColor: '#f5a623',
  },
  DEMO: {
    label: '✦ DEMO MODE',
    description: 'Synthetic data · For exploration only',
    bg: 'rgba(217, 70, 239, 0.06)',
    borderColor: 'rgba(217, 70, 239, 0.25)',
    color: 'rgba(217, 70, 239, 0.9)',
    dotColor: '#d946ef',
  },
  LIVE: {
    label: '🔴 LIVE MODE',
    description: 'Real data · Real execution · Real risk',
    bg: 'rgba(255, 79, 123, 0.06)',
    borderColor: 'rgba(255, 79, 123, 0.25)',
    color: 'rgba(255, 79, 123, 0.9)',
    dotColor: '#ff4f7b',
  },
}
