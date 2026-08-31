import { useState, useEffect } from 'react'

/**
 * SetupScreen — Premium boot/loading screen shown during Electron sidecar init
 * Phases: initializing | progress | python_missing | error
 */
export default function SetupScreen({ phase, data }) {
  const [showDetails, setShowDetails] = useState(false)
  const [dotCount, setDotCount] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setDotCount((c) => (c + 1) % 4), 500)
    return () => clearInterval(t)
  }, [])

  const dots = '.'.repeat(dotCount)

  return (
    <div
      className="h-screen w-screen flex flex-col items-center justify-center px-8 text-center select-none relative overflow-hidden"
      style={{
        background: 'var(--color-void)',
        WebkitAppRegion: 'drag',
      }}
    >
      {/* Background radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(circle at 50% 45%, rgba(245,166,35,0.06) 0%, transparent 65%)',
        }}
      />

      {/* Grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      {/* Centered content */}
      <div className="relative z-10 flex flex-col items-center gap-6 w-full max-w-md" style={{ WebkitAppRegion: 'no-drag' }}>

        {/* Brand */}
        <div className="flex flex-col items-center gap-3 animate-slide-up-fade">
          <span
            className="text-5xl leading-none animate-gold-pulse"
            style={{
              color: 'var(--color-gold)',
              filter: 'drop-shadow(0 0 16px rgba(245,166,35,0.6))',
            }}
          >
            ◆
          </span>
          <div>
            <h1
              className="text-xl font-black tracking-tight"
              style={{ color: 'var(--color-text)', fontFamily: 'Inter, sans-serif' }}
            >
              ChanakyaTrade
            </h1>
            <p className="text-[10px] tracking-widest mt-1" style={{ color: 'var(--color-subtle)' }}>
              STRATEGIC QUANT TERMINAL
            </p>
          </div>
        </div>

        {/* ── Progress state ── */}
        {(phase === 'initializing' || phase === 'progress') && (
          <ProgressView data={data} dots={dots} />
        )}

        {/* ── Python missing ── */}
        {phase === 'python_missing' && <PythonMissingView data={data} />}

        {/* ── Error state ── */}
        {phase === 'error' && (
          <ErrorView
            data={data}
            showDetails={showDetails}
            setShowDetails={setShowDetails}
          />
        )}
      </div>

      {/* Version footer */}
      <div
        className="absolute bottom-4 left-0 right-0 text-center text-[9px]"
        style={{ color: 'var(--color-subtle)', WebkitAppRegion: 'no-drag' }}
      >
        ChanakyaTrade v0.2.0 · NSE · BSE · NFO · MCX
      </div>
    </div>
  )
}

/* ── Progress ────────────────────────────────────────────────────────────── */
const BOOT_STAGES = [
  { id: 'startup',        label: 'Starting intelligence engine' },
  { id: 'dependencies',   label: 'Verifying dependencies' },
  { id: 'installing_deps',label: 'Installing Python packages (first launch)' },
  { id: 'brokers',        label: 'Connecting broker sessions' },
  { id: 'ready',          label: 'Loading market data feeds' },
]

function ProgressView({ data, dots }) {
  const message = data?.message ?? `Initializing${dots}`
  const percent = data?.percent ?? null
  const currentStage = data?.stage ?? 'startup'

  return (
    <div className="w-full space-y-5 animate-slide-up-fade" style={{ animationDelay: '100ms' }}>

      {/* Stage progress steps */}
      <div className="space-y-2">
        {BOOT_STAGES.map((stage, i) => {
          const stageIndex = BOOT_STAGES.findIndex((s) => s.id === currentStage)
          const isDone = i < stageIndex
          const isActive = stage.id === currentStage || (stageIndex === -1 && i === 0)

          return (
            <div key={stage.id} className="pipeline-step" style={isDone ? { color: 'var(--color-emerald)' } : isActive ? { color: 'var(--color-gold)' } : {}}>
              <div className="dot" style={isDone ? { background: 'var(--color-emerald)' } : isActive ? { background: 'var(--color-gold)', boxShadow: '0 0 8px rgba(245,166,35,0.7)', animation: 'gold-pulse 1.5s ease-in-out infinite' } : {}} />
              <span className={`text-[11px] ${isActive ? 'font-bold' : 'font-normal'}`}>{stage.label}</span>
              {isDone && <span style={{ color: 'var(--color-emerald)', marginLeft: 'auto', fontSize: '12px' }}>✓</span>}
              {isActive && <span style={{ color: 'var(--color-gold)', marginLeft: 'auto', fontSize: '10px' }}>●</span>}
            </div>
          )
        })}
      </div>

      {/* Progress bar */}
      <div className="w-full h-1 rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
        {percent != null ? (
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${percent}%`,
              background: 'linear-gradient(90deg, var(--color-gold), var(--color-gold-bright))',
              boxShadow: '0 0 8px rgba(245,166,35,0.6)',
            }}
          />
        ) : (
          <div
            className="h-full rounded-full w-1/3"
            style={{
              background: 'var(--color-gold)',
              animation: 'skeleton-shimmer 1.6s ease-in-out infinite',
            }}
          />
        )}
      </div>

      {/* Status message */}
      <div className="text-center">
        <p className="text-xs font-mono" style={{ color: 'var(--color-muted)' }}>{message}</p>
        {percent != null && (
          <p className="text-[10px] font-mono mt-1" style={{ color: 'var(--color-subtle)' }}>{percent}%</p>
        )}
        {currentStage === 'installing_deps' && (
          <p className="text-[10px] mt-2" style={{ color: 'var(--color-subtle)' }}>
            First launch takes ~2 min · Subsequent starts are instant
          </p>
        )}
      </div>
    </div>
  )
}

/* ── Python Missing ──────────────────────────────────────────────────────── */
function PythonMissingView({ data }) {
  const [copied, setCopied] = useState(false)

  function copyCommand() {
    navigator.clipboard.writeText(data?.brewCommand ?? 'brew install python@3.12')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="w-full space-y-4 animate-slide-up-fade">
      <div
        className="p-4 rounded-2xl text-left"
        style={{
          background: 'rgba(245,166,35,0.08)',
          border: '1px solid rgba(245,166,35,0.35)',
        }}
      >
        <p className="text-sm font-bold" style={{ color: 'var(--color-gold)' }}>
          ⚠️ Python 3.11+ Required
        </p>
        <p className="text-xs mt-1.5" style={{ color: 'var(--color-muted)' }}>
          ChanakyaTrade needs Python to run its analysis engine. Install it using one of the options below, then click Retry.
        </p>
      </div>

      <div className="space-y-2">
        <button
          onClick={() => window.electronAPI?.openExternal(data?.installUrl ?? 'https://www.python.org/downloads/')}
          className="w-full text-left p-3.5 rounded-xl transition-all cursor-pointer"
          style={{
            background: 'var(--color-panel)',
            border: '1px solid var(--color-border)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-gold)' }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)' }}
        >
          <p className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>🔗 Download from python.org</p>
          <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-muted)' }}>Official installer — works on all platforms</p>
        </button>

        <div className="p-3.5 rounded-xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
          <p className="text-xs font-bold mb-2" style={{ color: 'var(--color-text)' }}>🍺 Install with Homebrew</p>
          <div className="flex items-center gap-2">
            <code
              className="flex-1 text-[11px] font-mono px-3 py-2 rounded-lg"
              style={{
                background: 'var(--color-elevated)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-gold)',
              }}
            >
              {data?.brewCommand ?? 'brew install python@3.12'}
            </code>
            <button
              onClick={copyCommand}
              className="text-[10px] px-2.5 py-2 rounded-lg transition-all cursor-pointer font-bold"
              style={{
                background: copied ? 'rgba(0,214,143,0.15)' : 'var(--color-elevated)',
                border: `1px solid ${copied ? 'rgba(0,214,143,0.4)' : 'var(--color-border)'}`,
                color: copied ? 'var(--color-emerald)' : 'var(--color-muted)',
              }}
            >
              {copied ? '✓' : 'Copy'}
            </button>
          </div>
        </div>
      </div>

      <button
        onClick={() => window.electronAPI?.retrySetup()}
        className="btn btn-md btn-gold w-full"
      >
        ↻ Retry Setup
      </button>
    </div>
  )
}

/* ── Error ───────────────────────────────────────────────────────────────── */
function ErrorView({ data, showDetails, setShowDetails }) {
  return (
    <div className="w-full space-y-4 animate-slide-up-fade">
      <div
        className="p-4 rounded-2xl text-left"
        style={{
          background: 'rgba(255,79,123,0.08)',
          border: '1px solid rgba(255,79,123,0.35)',
        }}
      >
        <p className="text-sm font-bold" style={{ color: 'var(--color-rose)' }}>
          ✕ Setup Failed
        </p>
        <p className="text-xs mt-1.5" style={{ color: 'var(--color-muted)' }}>
          {data?.message ?? 'An unknown error occurred during initialization.'}
        </p>
      </div>

      {data?.details && (
        <div>
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="text-xs cursor-pointer transition-colors"
            style={{ color: 'var(--color-muted)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--color-text)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--color-muted)' }}
          >
            {showDetails ? '▼ Hide details' : '▶ Show technical details'}
          </button>
          {showDetails && (
            <pre
              className="mt-2 p-3 rounded-xl text-[10px] font-mono max-h-48 overflow-y-auto whitespace-pre-wrap text-left animate-slide-down-fade"
              style={{
                background: 'var(--color-panel)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-rose)',
              }}
            >
              {data.details}
            </pre>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => window.electronAPI?.retrySetup()}
          className="btn btn-md flex-1"
          style={{
            background: 'rgba(245,166,35,0.12)',
            border: '1px solid rgba(245,166,35,0.4)',
            color: 'var(--color-gold)',
            fontWeight: 700,
          }}
        >
          ↻ Retry
        </button>
        <button
          onClick={() => window.electronAPI?.resetVenv()}
          className="btn btn-md flex-1"
          style={{
            background: 'rgba(255,79,123,0.10)',
            border: '1px solid rgba(255,79,123,0.35)',
            color: 'var(--color-rose)',
            fontWeight: 700,
          }}
        >
          Reset Environment
        </button>
      </div>
    </div>
  )
}
