import { useEffect, useRef, useState } from 'react'

/**
 * Cinematic Welcome Step — Phase 9: Onboarding
 * Features: animated particle field, staggered text reveal, glowing brand mark
 */

function StarField({ count = 120 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf

    const resize = () => {
      canvas.width = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
    }
    resize()
    window.addEventListener('resize', resize)

    const stars = Array.from({ length: count }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.3,
      speed: Math.random() * 0.2 + 0.05,
      opacity: Math.random() * 0.7 + 0.2,
      pulse: Math.random() * Math.PI * 2,
    }))

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      stars.forEach((s) => {
        s.pulse += 0.02
        const op = s.opacity * (0.7 + 0.3 * Math.sin(s.pulse))
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(245, 166, 35, ${op})`
        ctx.fill()
        s.y -= s.speed
        if (s.y < -5) { s.y = canvas.height + 5; s.x = Math.random() * canvas.width }
      })
      raf = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [count])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ opacity: 0.6 }}
    />
  )
}

const CAPABILITIES = [
  { icon: '⚔️', label: '13 AI Personas', sub: 'Bull/Bear debate + council' },
  { icon: '📊', label: 'SMC + VPA Engine', sub: 'Order Blocks, FVGs, Sweeps' },
  { icon: '⚡', label: 'Options & GEX', sub: 'Live chain + IV Smile' },
  { icon: '🔍', label: 'Multibagger Screen', sub: 'Minervini + Forensics' },
  { icon: '🌐', label: 'Market Overview', sub: 'VIX, FII/DII, Breadth' },
  { icon: '📋', label: 'Trade Journal', sub: 'Pattern analytics & R-multiple' },
]

export default function WelcomeStep({ onNext }) {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 300),
      setTimeout(() => setPhase(2), 800),
      setTimeout(() => setPhase(3), 1400),
    ]
    return () => timers.forEach(clearTimeout)
  }, [])

  return (
    <div
      className="relative flex flex-col items-center justify-center flex-1 gap-8 overflow-hidden"
      style={{ background: 'var(--color-void)' }}
    >
      {/* Star particle field */}
      <StarField count={140} />

      {/* Radial glow behind brand mark */}
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
        style={{
          width: '400px',
          height: '400px',
          background: 'radial-gradient(circle, rgba(245,166,35,0.12) 0%, transparent 70%)',
          filter: 'blur(20px)',
        }}
      />

      {/* Brand mark */}
      <div
        className="relative z-10 flex flex-col items-center gap-3 transition-all"
        style={{
          opacity: phase >= 1 ? 1 : 0,
          transform: phase >= 1 ? 'translateY(0) scale(1)' : 'translateY(20px) scale(0.9)',
          transition: 'all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}
      >
        <div
          className="text-7xl leading-none animate-gold-pulse"
          style={{
            color: 'var(--color-gold)',
            filter: 'drop-shadow(0 0 20px rgba(245,166,35,0.7))',
            fontFamily: 'serif',
          }}
        >
          ◆
        </div>

        <div
          className="text-center"
          style={{
            opacity: phase >= 2 ? 1 : 0,
            transform: phase >= 2 ? 'translateY(0)' : 'translateY(10px)',
            transition: 'all 0.6s cubic-bezier(0.16, 1, 0.3, 1)',
          }}
        >
          <h1
            className="font-black tracking-tight leading-none"
            style={{
              fontSize: '36px',
              color: 'var(--color-text)',
              fontFamily: 'Inter, sans-serif',
            }}
          >
            ChanakyaTrade
          </h1>
          <p className="text-sm font-medium mt-2" style={{ color: 'var(--color-muted)', letterSpacing: '0.12em' }}>
            AI-POWERED STRATEGIC QUANT TERMINAL
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--color-subtle)' }}>
            NSE · BSE · NFO · MCX  ·  Institutional-Grade Intelligence
          </p>
        </div>
      </div>

      {/* Capabilities grid */}
      <div
        className="relative z-10 grid grid-cols-2 sm:grid-cols-3 gap-2 max-w-lg px-4 transition-all"
        style={{
          opacity: phase >= 3 ? 1 : 0,
          transform: phase >= 3 ? 'translateY(0)' : 'translateY(16px)',
          transition: 'all 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.2s',
        }}
      >
        {CAPABILITIES.map((c, i) => (
          <div
            key={c.label}
            className="flex items-start gap-2.5 px-3 py-2.5 rounded-xl"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.06)',
              animationDelay: `${i * 80}ms`,
            }}
          >
            <span className="text-xl leading-none flex-shrink-0">{c.icon}</span>
            <div>
              <div className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>{c.label}</div>
              <div className="text-[9px]" style={{ color: 'var(--color-subtle)' }}>{c.sub}</div>
            </div>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div
        className="relative z-10 flex flex-col items-center gap-3 transition-all"
        style={{
          opacity: phase >= 3 ? 1 : 0,
          transform: phase >= 3 ? 'translateY(0)' : 'translateY(12px)',
          transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1) 0.5s',
        }}
      >
        <button
          onClick={onNext}
          className="btn btn-lg btn-gold transition-all"
          style={{
            boxShadow: '0 0 32px rgba(245, 166, 35, 0.4), 0 8px 24px rgba(0,0,0,0.6)',
            fontSize: '15px',
            letterSpacing: '0.04em',
          }}
        >
          ⚡ Launch Setup  →
        </button>
        <p className="text-[10px]" style={{ color: 'var(--color-subtle)' }}>
          Takes about 2 minutes · Securely stored locally
        </p>
      </div>
    </div>
  )
}
