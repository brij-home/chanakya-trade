import { useEffect } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import { useChatStore } from '../../store/chatStore'

export default function MetricExplainerModal() {
  const { isOpen, activeMetric, contextData, closeInspector } = useInspectorStore()
  const sendDraft = useChatStore((s) => s.sendDraft)

  // Keyboard shortcut: Escape to close
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        closeInspector()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, closeInspector])

  if (!isOpen || !activeMetric) return null

  const m = activeMetric
  const sym = contextData?.symbol || 'RELIANCE'

  const handleAction = (cmd) => {
    closeInspector()
    sendDraft(cmd)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm select-none animate-in fade-in duration-200"
      onClick={closeInspector}
    >
      <div
        className="bg-panel border border-border/80 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl font-ui text-text flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/60 bg-elevated/40">
          <div className="flex items-center gap-3">
            <span className="text-xl">📊</span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md font-bold font-mono bg-amber/15 text-amber border border-amber/30">
                  {m.category || 'Institutional Metric'}
                </span>
                {contextData?.symbol && (
                  <span className="text-xs font-mono font-bold text-text bg-panel px-2 py-0.5 rounded border border-border">
                    {contextData.symbol}
                  </span>
                )}
              </div>
              <h2 className="text-lg font-bold text-text mt-1">{m.title}</h2>
            </div>
          </div>

          <button
            type="button"
            onClick={closeInspector}
            className="w-8 h-8 rounded-lg bg-panel hover:bg-elevated text-muted hover:text-text flex items-center justify-center text-lg transition-colors cursor-pointer border border-border/60"
            title="Close (Esc)"
          >
            ×
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs">
          {/* Plain English Meaning */}
          <div className="bg-elevated/60 border border-border/60 rounded-xl p-3.5 space-y-1.5">
            <span className="text-[11px] font-bold text-amber font-ui uppercase tracking-wider">
              📌 What This Metric Measures
            </span>
            <p className="text-text text-sm leading-relaxed font-ui">
              {m.explanation}
            </p>
          </div>

          {/* Mathematical Formula Block */}
          {m.formula && (
            <div className="bg-panel border border-border/80 rounded-xl p-3.5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-text font-ui uppercase tracking-wider">
                  📐 Quantitative Formula
                </span>
                <span className="text-[10px] text-muted font-mono">Standardized Model</span>
              </div>
              <div className="bg-elevated p-3 rounded-lg border border-border/50 font-mono text-xs text-amber font-semibold overflow-x-auto whitespace-pre-wrap">
                {m.formula}
              </div>
            </div>
          )}

          {/* Variables Breakdown */}
          {m.variables && m.variables.length > 0 && (
            <div className="bg-panel border border-border/60 rounded-xl p-3.5 space-y-2">
              <span className="text-[11px] font-bold text-text font-ui uppercase tracking-wider">
                🔬 Model Parameters & Variables
              </span>
              <div className="grid grid-cols-1 gap-2">
                {m.variables.map((v, idx) => (
                  <div key={idx} className="bg-elevated/50 p-2.5 rounded-lg border border-border/40 space-y-0.5">
                    <p className="font-mono font-bold text-text text-xs">{v.name}</p>
                    <p className="text-muted text-[11px] font-ui">{v.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Thresholds Interpretation Table */}
          {m.thresholds && m.thresholds.length > 0 && (
            <div className="bg-panel border border-border/60 rounded-xl p-3.5 space-y-2">
              <span className="text-[11px] font-bold text-text font-ui uppercase tracking-wider">
                ⚖️ Institutional Thresholds & Regimes
              </span>
              <div className="space-y-1.5">
                {m.thresholds.map((t, idx) => {
                  const badgeColor = t.color === 'green' ? 'bg-green/10 text-green border-green/30' : t.color === 'red' ? 'bg-red/10 text-red border-red/30' : t.color === 'blue' ? 'bg-blue/10 text-blue border-blue/30' : 'bg-amber/10 text-amber border-amber/30'
                  return (
                    <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 bg-elevated/40 p-2.5 rounded-lg border border-border/30">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-text text-xs">{t.condition}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${badgeColor}`}>
                          {t.label}
                        </span>
                      </div>
                      <p className="text-muted text-[11px] font-ui">{t.desc}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Institutional Decision-Making Playbook */}
          {m.institutionalGuide && (
            <div className="bg-blue/10 border border-blue/30 rounded-xl p-3.5 space-y-1.5">
              <div className="flex items-center gap-2 text-blue font-bold text-xs uppercase tracking-wider">
                <span>💡</span>
                <span>Institutional Trader's Playbook</span>
              </div>
              <p className="text-text text-xs leading-relaxed font-ui">
                {m.institutionalGuide}
              </p>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-t border-border/60 bg-elevated/40">
          <span className="text-[11px] text-muted font-ui hidden sm:inline">
            Quick Actions for <strong className="text-text">{sym}</strong>:
          </span>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleAction(`forensic ${sym}`)}
              className="bg-panel hover:bg-elevated text-text border border-border px-3 py-1.5 rounded-lg text-xs font-semibold font-ui transition-colors cursor-pointer"
            >
              🛡️ Audit Forensics
            </button>
            <button
              type="button"
              onClick={() => handleAction(`analyze ${sym}`)}
              className="bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 px-3 py-1.5 rounded-lg text-xs font-semibold font-ui transition-colors cursor-pointer"
            >
              ⚔️ 7-Agent Debate
            </button>
            <button
              type="button"
              onClick={() => handleAction(`size ${sym} 24000 23600`)}
              className="bg-green/15 hover:bg-green/25 text-green border border-green/30 px-3 py-1.5 rounded-lg text-xs font-semibold font-ui transition-colors cursor-pointer"
            >
              ⚖️ Sizer
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
