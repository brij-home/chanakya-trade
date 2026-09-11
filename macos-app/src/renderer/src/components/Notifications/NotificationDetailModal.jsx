import React from 'react'
import { useNotificationStore } from '../../store/notificationStore'
import { useChatStore } from '../../store/chatStore'

// Visual R:R breakdown bar
function RRMiniBar({ sl, entry, t1, t2, t3 }) {
  if (!sl || !entry || !t1) return null
  const totalRange = Math.abs((t3 || t2 || t1) - sl)
  if (totalRange <= 0) return null
  const slW = Math.max(5, Math.round((Math.abs(entry - sl) / totalRange) * 100))
  const t1W = Math.max(5, Math.round((Math.abs(t1 - entry) / totalRange) * 100))
  const t2W = t2 ? Math.max(5, Math.round((Math.abs(t2 - t1) / totalRange) * 100)) : 0
  const t3W = t3 ? Math.max(5, Math.round((Math.abs((t3 || t2) - (t2 || t1)) / totalRange) * 100)) : 0
  const rem = Math.max(0, 100 - slW - t1W - t2W - t3W)

  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden w-full bg-surface border border-border/50">
        <div style={{ width: `${slW}%` }} className="bg-rose-500" title={`Risk (SL): ₹${sl}`} />
        <div style={{ width: `${t1W + rem}%` }} className="bg-emerald-500" title={`Target 1: ₹${t1}`} />
        {t2W > 0 && <div style={{ width: `${t2W}%` }} className="bg-cyan-500" title={`Target 2: ₹${t2}`} />}
        {t3W > 0 && <div style={{ width: `${t3W}%` }} className="bg-purple-500" title={`Target 3: ₹${t3}`} />}
      </div>
      <div className="flex items-center justify-between text-[9px] font-mono text-muted">
        <span className="text-rose-400 font-bold">SL (Risk)</span>
        <span className="text-amber-400 font-bold">Entry</span>
        <span className="text-emerald-400 font-bold">T1 (2R)</span>
        {t2 && <span className="text-cyan-400 font-bold">T2 (4R)</span>}
        {t3 && <span className="text-purple-400 font-bold">T3 (Runner)</span>}
      </div>
    </div>
  )
}

export default function NotificationDetailModal({ onOpenOrderTicket }) {
  const selected = useNotificationStore((s) => s.selectedNotification)
  const setSelected = useNotificationStore((s) => s.setSelectedNotification)

  const setSelectedSymbol = useChatStore((s) => s.setSelectedSymbol)
  const setActiveView = useChatStore((s) => s.setActiveView)

  if (!selected) return null

  const isBull = selected.direction === 'BULLISH'
  const scrutiny = selected.metrics?.scrutiny || null
  const conviction = Number(selected.confidence || scrutiny?.score || 75)
  const isInvalidated = selected.is_invalidated || selected.stage === 'INVALIDATED'

  const fmt = (n, dec = 1) =>
    n != null && !isNaN(n)
      ? Number(n).toLocaleString('en-IN', {
          minimumFractionDigits: Number(n) < 100 ? dec : 0,
          maximumFractionDigits: dec,
        })
      : '—'

  const handleTrade = () => {
    if (onOpenOrderTicket) {
      onOpenOrderTicket({
        symbol: selected.contract_symbol || selected.symbol,
        exchange: selected.symbol?.includes('MCX') ? 'MCX' : 'NSE',
        price: selected.entry || selected.premium || selected.ltp || selected.spot || 100,
        stopLoss: selected.sl,
        target: selected.t1,
      })
    }
    setSelected(null)
  }

  const handleViewInTerminal = () => {
    setSelectedSymbol(selected.symbol)
    setActiveView('terminal')
    setSelected(null)
  }

  const handleCopyBlueprint = () => {
    const text = [
      `SIGNAL: ${selected.contract_symbol || selected.symbol} (${selected.direction})`,
      selected.spot ? `Spot: ₹${fmt(selected.spot, 0)}` : '',
      selected.premium ? `Premium: ₹${fmt(selected.premium)}` : '',
      selected.sl ? `Stop Loss: ₹${fmt(selected.sl)}` : '',
      selected.entry ? `Entry: ₹${fmt(selected.entry)}` : '',
      selected.t1 ? `Target 1: ₹${fmt(selected.t1)}` : '',
      selected.t2 ? `Target 2: ₹${fmt(selected.t2)}` : '',
      selected.t3 ? `Target 3: ₹${fmt(selected.t3)}` : '',
      `Conviction: ${conviction}/100`,
      selected.summary ? `Rationale: ${selected.summary}` : '',
    ]
      .filter(Boolean)
      .join('\n')
    navigator.clipboard?.writeText(text).catch(() => {})
  }

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(10px)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) setSelected(null)
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden font-ui animate-scale-up"
        style={{
          background: 'var(--color-panel)',
          borderColor: isBull ? 'rgba(0,214,143,0.3)' : 'rgba(255,79,123,0.3)',
        }}
      >
        {/* ── Modal Header ────────────────────────────────────────── */}
        <div
          className="flex items-center justify-between px-5 py-3.5 border-b"
          style={{
            background: 'var(--color-elevated)',
            borderColor: 'var(--color-border)',
          }}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-xl">{isBull ? '🚀' : '🔻'}</span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-black font-mono text-text">
                  {selected.contract_symbol || selected.symbol}
                </span>
                <span
                  className={`text-[9px] font-black px-2 py-0.5 rounded-full border ${
                    isBull
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                  }`}
                >
                  {selected.direction}
                </span>
                {selected.is_test && (
                  <span className="text-[8px] font-black px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
                    TEST
                  </span>
                )}
              </div>
              <div className="text-[11px] text-muted font-mono mt-0.5">
                {selected.alert_type?.replace(/_/g, ' ')} · Stage: {selected.stage}
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setSelected(null)}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-muted hover:text-text hover:bg-surface text-sm font-bold transition-all cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* ── Modal Body ──────────────────────────────────────────── */}
        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Key Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {selected.spot && (
              <div className="p-2.5 rounded-xl bg-surface border border-border">
                <div className="text-[10px] text-muted font-bold uppercase">Spot Price</div>
                <div className="text-sm font-mono font-black text-text mt-0.5">
                  ₹{fmt(selected.spot, 0)}
                </div>
              </div>
            )}
            {selected.premium && (
              <div className="p-2.5 rounded-xl bg-surface border border-border">
                <div className="text-[10px] text-gold font-bold uppercase">Option Premium</div>
                <div className="text-sm font-mono font-black text-gold mt-0.5">
                  ₹{fmt(selected.premium)}
                </div>
              </div>
            )}
            <div className="p-2.5 rounded-xl bg-surface border border-border">
              <div className="text-[10px] text-rose-400 font-bold uppercase">Stop-Loss</div>
              <div className="text-sm font-mono font-black text-rose-400 mt-0.5">
                ₹{fmt(selected.sl)}
              </div>
            </div>
            <div className="p-2.5 rounded-xl bg-surface border border-border">
              <div className="text-[10px] text-emerald-400 font-bold uppercase">Target 1 (+2R)</div>
              <div className="text-sm font-mono font-black text-emerald-400 mt-0.5">
                ₹{fmt(selected.t1)}
              </div>
            </div>
          </div>

          {/* R:R Breakdown Bar */}
          <div className="p-3 rounded-xl bg-surface border border-border space-y-2">
            <div className="flex items-center justify-between text-xs font-bold">
              <span className="text-muted">Mathematical Risk:Reward Setup</span>
              <span className="font-mono text-gold">Conviction {conviction}/100</span>
            </div>
            <RRMiniBar
              sl={selected.sl}
              entry={selected.entry || selected.premium || selected.ltp}
              t1={selected.t1}
              t2={selected.t2}
              t3={selected.t3}
            />
          </div>

          {/* AI Scrutiny Dossier */}
          {scrutiny && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-bold text-text">
                <span>🛡️ Institutional AI Scrutiny Dossier</span>
                <span className="text-[10px] font-mono text-muted">
                  Model: {scrutiny.auditor_model || 'Fast-LLM'}
                </span>
              </div>

              {scrutiny.logic_confirmation && (
                <div className="p-3 rounded-xl bg-emerald-500/8 border border-emerald-500/25 space-y-1">
                  <div className="text-[10px] font-black uppercase text-emerald-400 tracking-wider">
                    ✅ Structural Logic Confirmation
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">
                    {scrutiny.logic_confirmation}
                  </p>
                </div>
              )}

              {scrutiny.trap_risk_warning && (
                <div className="p-3 rounded-xl bg-amber-500/8 border border-amber-500/25 space-y-1">
                  <div className="text-[10px] font-black uppercase text-amber-400 tracking-wider">
                    ⚠️ Liquidity / Trap Risk Warning
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">
                    {scrutiny.trap_risk_warning}
                  </p>
                </div>
              )}

              {scrutiny.actionable_guidance && (
                <div className="p-3 rounded-xl bg-sky-500/8 border border-sky-500/25 space-y-1">
                  <div className="text-[10px] font-black uppercase text-sky-400 tracking-wider">
                    🎯 Execution Playbook & Trailing Strategy
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed">
                    {scrutiny.actionable_guidance}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Invalidation / Summary Note */}
          {selected.summary && !scrutiny && (
            <div className="p-3 rounded-xl bg-surface border border-border">
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">
                Alert Summary & Rationale
              </div>
              <p className="text-xs text-text leading-relaxed">
                {selected.summary}
              </p>
            </div>
          )}

          {/* Expiry & Lot metadata */}
          <div className="flex items-center gap-3 text-[11px] font-mono text-muted flex-wrap">
            {selected.expiry_date && <span>📅 Expiry: <strong className="text-text">{selected.expiry_date}</strong></span>}
            {selected.lot_size && <span>📦 Lot Size: <strong className="text-text">{selected.lot_size}</strong></span>}
            <span>🕒 Triggered: <strong className="text-text">{selected.timestamp}</strong></span>
          </div>
        </div>

        {/* ── Modal Footer / Action Bar ────────────────────────────── */}
        <div
          className="flex items-center justify-between px-5 py-3.5 border-t gap-2"
          style={{
            background: 'var(--color-elevated)',
            borderColor: 'var(--color-border)',
          }}
        >
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopyBlueprint}
              className="text-xs font-bold px-3 py-1.5 rounded-xl border border-border text-muted hover:text-text hover:bg-surface transition-all cursor-pointer"
            >
              📋 Copy Blueprint
            </button>
            <button
              type="button"
              onClick={handleViewInTerminal}
              className="text-xs font-bold px-3 py-1.5 rounded-xl border border-border text-muted hover:text-gold hover:bg-surface transition-all cursor-pointer"
            >
              📈 View in Terminal
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-xs font-bold px-3 py-1.5 rounded-xl text-muted hover:text-text cursor-pointer"
            >
              Close
            </button>
            <button
              type="button"
              onClick={handleTrade}
              className="text-xs font-black px-4 py-1.5 rounded-xl text-black transition-all cursor-pointer shadow-lg flex items-center gap-1.5"
              style={{
                background: 'var(--color-emerald)',
                boxShadow: '0 0 16px rgba(0,214,143,0.4)',
              }}
            >
              <span>⚡</span>
              <span>1-Click Trade</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
