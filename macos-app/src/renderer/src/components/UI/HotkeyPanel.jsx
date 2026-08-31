import { useEffect, useCallback } from 'react'

const SECTIONS = [
  {
    title: '🔍 Navigation',
    keys: [
      { keys: ['Ctrl', 'K'],     desc: 'Universal symbol/command search' },
      { keys: ['1'],              desc: 'Go to Market Terminal' },
      { keys: ['2'],              desc: 'Go to Debate Arena' },
      { keys: ['3'],              desc: 'Go to Journal' },
      { keys: ['4'],              desc: 'Go to Portfolio' },
      { keys: ['5'],              desc: 'Go to Overview' },
      { keys: ['Esc'],            desc: 'Close modal / Return to chat' },
    ],
  },
  {
    title: '⚡ Analysis',
    keys: [
      { keys: ['A'],              desc: 'Analyze active symbol' },
      { keys: ['D'],              desc: 'Run Multi-Agent Debate' },
      { keys: ['S'],              desc: 'Scan NSE universe' },
      { keys: ['F'],              desc: 'Open FII/DII Flows' },
      { keys: ['B'],              desc: 'Run Backtest on active symbol' },
      { keys: ['O'],              desc: 'Open Options Payoff Builder' },
    ],
  },
  {
    title: '💼 Trade Desk',
    keys: [
      { keys: ['T'],              desc: 'Open Order Ticket' },
      { keys: ['P'],              desc: 'Show Position Tracker' },
      { keys: ['R'],              desc: 'Risk Gate Assessment' },
      { keys: ['Ctrl', 'Enter'],  desc: 'Submit / Send command' },
    ],
  },
  {
    title: '📋 Chat & Messages',
    keys: [
      { keys: ['↑ / ↓'],         desc: 'Navigate command history' },
      { keys: ['Tab'],            desc: 'Autocomplete suggestion' },
      { keys: ['Ctrl', 'L'],      desc: 'Clear chat history' },
      { keys: ['Ctrl', 'Z'],      desc: 'Stop streaming analysis' },
    ],
  },
  {
    title: '🎨 Interface',
    keys: [
      { keys: ['?'],              desc: 'Toggle this hotkey panel' },
      { keys: ['Ctrl', 'D'],      desc: 'Toggle dark / light theme' },
      { keys: ['F11'],            desc: 'Toggle fullscreen chart' },
    ],
  },
]

function Kbd({ children }) {
  return (
    <kbd
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono font-bold"
      style={{
        background: 'var(--color-elevated)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text)',
        boxShadow: '0 1px 0 var(--color-border)',
      }}
    >
      {children}
    </kbd>
  )
}

export default function HotkeyPanel({ open, onClose }) {
  const handleKey = useCallback(
    (e) => {
      if (e.key === 'Escape' || e.key === '?') {
        e.preventDefault()
        onClose()
      }
    },
    [onClose]
  )

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKey)
      return () => document.removeEventListener('keydown', handleKey)
    }
  }, [open, handleKey])

  if (!open) return null

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.72)', backdropFilter: 'blur(12px)' }}
      onClick={onClose}
    >
      {/* Panel */}
      <div
        className="relative w-full max-w-3xl max-h-[82vh] overflow-y-auto rounded-3xl animate-slide-up-fade"
        style={{
          background: 'var(--color-panel)',
          border: '1px solid var(--color-border)',
          boxShadow: '0 32px 80px rgba(0,0,0,0.6), var(--glow-gold)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b"
          style={{
            background: 'var(--color-panel)',
            borderColor: 'var(--color-border)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <div>
            <h2 className="text-sm font-black tracking-wide" style={{ color: 'var(--color-text)' }}>
              ⌨️ Keyboard Shortcuts
            </h2>
            <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-muted)' }}>
              ChanakyaTrade — AI Quant Terminal · Press <Kbd>?</Kbd> or <Kbd>Esc</Kbd> to close
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center text-sm transition-all hover:brightness-125"
            style={{ background: 'var(--color-elevated)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }}
          >
            ×
          </button>
        </div>

        {/* Sections grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-6">
          {SECTIONS.map((section) => (
            <div
              key={section.title}
              className="rounded-2xl p-4 space-y-2.5"
              style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border-subtle)' }}
            >
              <div
                className="text-[10px] font-black uppercase tracking-widest mb-3"
                style={{ color: 'var(--color-gold)' }}
              >
                {section.title}
              </div>
              {section.keys.map(({ keys: ks, desc }) => (
                <div key={desc} className="flex items-center justify-between gap-3">
                  <span className="text-xs" style={{ color: 'var(--color-muted)' }}>{desc}</span>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {ks.map((k, i) => (
                      <span key={i} className="flex items-center gap-1">
                        {i > 0 && <span className="text-[9px]" style={{ color: 'var(--color-muted)' }}>+</span>}
                        <Kbd>{k}</Kbd>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Footer tip */}
        <div
          className="px-6 py-3 border-t text-[10px] text-center"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}
        >
          💡 Single-key shortcuts work when the chat input is not focused · Press <Kbd>Ctrl+K</Kbd> to quickly search any command
        </div>
      </div>
    </div>
  )
}
