/**
 * Institutional Acoustic Micro-Feedback Synthesizer
 * Pure Web Audio API — 0ms latency, zero external asset requests, zero dependencies.
 */

let audioCtx = null

function getAudioContext() {
  if (typeof window === 'undefined') return null
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (!AudioContextClass) return null
    if (!audioCtx) {
      audioCtx = new AudioContextClass()
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {})
    }
    return audioCtx
  } catch {
    return null
  }
}

export function isAudioFeedbackEnabled() {
  try {
    return localStorage.getItem('chanakya_audio_feedback') !== 'false'
  } catch {
    return true
  }
}

export function toggleAudioFeedback(enable) {
  try {
    localStorage.setItem('chanakya_audio_feedback', enable ? 'true' : 'false')
  } catch {}
}

/**
 * Institutional Order Fill Chime
 * Harmonic 2-tone ascent: C5 (523.25 Hz) -> E5 (659.25 Hz) with warm decay
 */
export function playOrderFillSound() {
  if (!isAudioFeedbackEnabled()) return
  const ctx = getAudioContext()
  if (!ctx) return

  try {
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.type = 'sine'
    osc.frequency.setValueAtTime(523.25, now) // C5
    osc.frequency.exponentialRampToValueAtTime(659.25, now + 0.12) // E5

    gain.gain.setValueAtTime(0.14, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38)

    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.start(now)
    osc.stop(now + 0.4)
  } catch {}
}

/**
 * Critical Market Alert Ping
 * High-definition harmonic ping: D5 (587.33 Hz) -> A5 (880.00 Hz)
 */
export function playAlertChime() {
  if (!isAudioFeedbackEnabled()) return
  const ctx = getAudioContext()
  if (!ctx) return

  try {
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.type = 'sine'
    osc.frequency.setValueAtTime(587.33, now) // D5
    osc.frequency.exponentialRampToValueAtTime(880, now + 0.14) // A5

    gain.gain.setValueAtTime(0.12, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32)

    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.start(now)
    osc.stop(now + 0.35)
  } catch {}
}

/**
 * Risk Breach / Warning Chord
 * Dual-sine minor tension chord: A3 (220 Hz) + C#4 (277.18 Hz)
 */
export function playWarningTone() {
  if (!isAudioFeedbackEnabled()) return
  const ctx = getAudioContext()
  if (!ctx) return

  try {
    const now = ctx.currentTime
    const osc1 = ctx.createOscillator()
    const osc2 = ctx.createOscillator()
    const gain = ctx.createGain()

    osc1.type = 'sine'
    osc2.type = 'sine'
    osc1.frequency.setValueAtTime(220, now)
    osc2.frequency.setValueAtTime(277.18, now)

    gain.gain.setValueAtTime(0.10, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22)

    osc1.connect(gain)
    osc2.connect(gain)
    gain.connect(ctx.destination)

    osc1.start(now)
    osc2.start(now)
    osc1.stop(now + 0.25)
    osc2.stop(now + 0.25)
  } catch {}
}
