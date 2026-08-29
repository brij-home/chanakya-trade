import { useEffect, useState } from 'react'
import { useChatStore, getBaseUrl } from './store/chatStore'
import { useMarketClock } from './hooks/useMarketClock'
import Sidebar from './components/Sidebar'
import ChatArea from './components/Chat/ChatArea'
import InputBar from './components/Input/InputBar'
import SetupScreen from './components/SetupScreen'
import OnboardingWizard from './components/Onboarding/OnboardingWizard'
import CommandPalette from './components/Modals/CommandPalette'
import OrderTicketModal from './components/Modals/OrderTicketModal'
import MetricExplainerModal from './components/Modals/MetricExplainerModal'
import TopOpportunitiesModal from './components/Modals/TopOpportunitiesModal'
import SectorDrilldownModal from './components/Modals/SectorDrilldownModal'

function useTheme() {
  const [theme, setThemeState] = useState(() => {
    try {
      return localStorage.getItem('vt-theme') || 'dark'
    } catch {
      return 'dark'
    }
  })

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('dark', 'light')
    if (theme === 'light') {
      root.classList.add('light')
    } else {
      root.classList.add('dark')
    }
    try {
      localStorage.setItem('vt-theme', theme)
    } catch {}
  }, [theme])

  const toggle = () => setThemeState((t) => (t === 'light' ? 'dark' : 'light'))
  return { theme, toggle }
}

export default function App() {
  const { setPort, setSidecarError, setBrokerStatuses } = useChatStore()
  const createSession = useChatStore((s) => s.createSession)
  const port = useChatStore((s) => s.port)
  const { theme, toggle: toggleTheme } = useTheme()

  // Setup phase state machine
  const [setupPhase, setSetupPhase] = useState('initializing')
  // 'initializing' | 'progress' | 'python_missing' | 'error' | 'onboarding' | 'ready'
  const [setupData, setSetupData] = useState(null)

  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false)
  const [isOrderTicketOpen, setIsOrderTicketOpen] = useState(false)
  const [isTopOppsOpen, setIsTopOppsOpen] = useState(false)
  const [sectorDrilldown, setSectorDrilldown] = useState({ isOpen: false, sector: null })

  // Listen for open-sector-drilldown events
  useEffect(() => {
    const onOpenSector = (e) => {
      if (e.detail?.sector) {
        setSectorDrilldown({ isOpen: true, sector: e.detail.sector })
      }
    }
    window.addEventListener('open-sector-drilldown', onOpenSector)
    return () => window.removeEventListener('open-sector-drilldown', onOpenSector)
  }, [])

  useEffect(() => {
    // Web mode — no Electron IPC, just check if server is ready
    if (window.__CHANAKYA_TRADE_WEB__) {
      const checkReady = async () => {
        try {
          const res = await fetch('/api/onboarding/status')
          if (res.status === 401) {
            window.location.href = '/'
            return
          }
          const data = await res.json()
          const currentPort = parseInt(window.location.port, 10) || 8765
          setPort(currentPort)
          if (data.onboarding_complete) {
            setSetupPhase('ready')
          } else {
            setSetupPhase('onboarding')
          }
        } catch {
          setSetupPhase('error')
          setSetupData({ message: 'Cannot connect to server' })
        }
      }
      checkReady()
      return
    }

    window.electronAPI?.onSetupProgress((data) => {
      setSetupPhase('progress')
      setSetupData(data)
    })

    window.electronAPI?.onSetupPythonMissing((data) => {
      setSetupPhase('python_missing')
      setSetupData(data)
    })

    window.electronAPI?.onSidecarReady(async ({ port }) => {
      setPort(port)
      try {
        const res = await fetch(`${getBaseUrl(port)}/api/onboarding/status`)
        const data = await res.json()
        if (data.onboarding_complete) {
          setSetupPhase('ready')
        } else {
          setSetupPhase('onboarding')
        }
      } catch {
        setSetupPhase('ready')
      }
    })

    window.electronAPI?.onSidecarError(({ message, details }) => {
      setSidecarError(message)
      if (setupPhase !== 'ready') {
        setSetupPhase('error')
        setSetupData({ message, details })
      }
    })

    window.electronAPI?.getPort().then(async (port) => {
      if (port) {
        setPort(port)
        try {
          const res = await fetch(`${getBaseUrl(port)}/api/onboarding/status`)
          const data = await res.json()
          if (data.onboarding_complete) {
            setSetupPhase('ready')
          } else {
            setSetupPhase('onboarding')
          }
        } catch {
          setSetupPhase('ready')
        }
      }
    })
  }, [])

  // Poll /api/status every 8s once sidecar is up
  useEffect(() => {
    if (!port && port !== 0) return
    const statusUrl = `${getBaseUrl(port)}/api/status`
    const fetchStatus = () =>
      fetch(statusUrl)
        .then((r) => r.json())
        .then(setBrokerStatuses)
        .catch(() => {})
    fetchStatus()
    const t = setInterval(fetchStatus, 8000)
    return () => clearInterval(t)
  }, [port])

  // Keybindings: Cmd/Ctrl+N, Cmd/Ctrl+K, Cmd/Ctrl+O (Top Opps)
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault()
        createSession()
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setIsCommandPaletteOpen((prev) => !prev)
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'o') {
        e.preventDefault()
        setIsTopOppsOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [createSession])

  if (setupPhase === 'onboarding') {
    return <OnboardingWizard port={port} onComplete={() => setSetupPhase('ready')} />
  }

  if (setupPhase !== 'ready') {
    return <SetupScreen phase={setupPhase} data={setupData} />
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Title bar */}
      <div className="drag flex items-center h-[52px] bg-panel border-b border-border flex-shrink-0 px-4">
        <div className="flex items-center gap-2 pointer-events-none">
          <span className="text-amber text-[15px]">◆</span>
          <span className="text-text text-[13px] font-semibold tracking-wide font-ui">
            ChanakyaTrade
          </span>
        </div>

        {/* Center: Command Palette Trigger Omnibox */}
        <div className="no-drag flex-1 max-w-sm mx-auto px-4">
          <button
            type="button"
            onClick={() => setIsCommandPaletteOpen(true)}
            className="w-full flex items-center justify-between bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/60 hover:border-amber/40 px-3 py-1.5 rounded-lg text-xs font-ui transition-all shadow-xs cursor-pointer"
          >
            <span className="flex items-center gap-2 truncate">
              <span>🔍</span> Search stocks, options, indicators…
            </span>
            <kbd className="text-[10px] bg-panel border border-border px-1.5 py-0.5 rounded text-amber font-mono font-bold">
              Ctrl+K
            </kbd>
          </button>
        </div>

        {/* Right Action Icons */}
        <div className="no-drag flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setIsTopOppsOpen(true)}
            className="hidden sm:flex items-center gap-1.5 bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 px-2.5 py-1 rounded-lg text-xs font-ui font-bold transition-colors cursor-pointer shadow-xs"
            title="Open Top 10 High-Conviction Opportunities Radar (Ctrl+O)"
          >
            <span>🎯</span> Top 10 Radar
          </button>

          <button
            type="button"
            onClick={() => setIsOrderTicketOpen(true)}
            className="hidden sm:flex items-center gap-1.5 bg-green/10 hover:bg-green/20 text-green border border-green/30 px-2.5 py-1 rounded-lg text-xs font-ui font-semibold transition-colors cursor-pointer"
          >
            <span>⚡</span> Stage Order
          </button>
          <MarketBadge />
          <ThemeToggle theme={theme} toggle={toggleTheme} />
          <StatusDot />
        </div>
      </div>

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <ChatArea />
          <InputBar />
        </div>
      </div>

      {/* Global Modals */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onOpenOrderTicket={() => {
          setIsCommandPaletteOpen(false)
          setIsOrderTicketOpen(true)
        }}
      />
      <OrderTicketModal
        isOpen={isOrderTicketOpen}
        onClose={() => setIsOrderTicketOpen(false)}
        initialData={{ symbol: 'RELIANCE', exchange: 'NSE', price: 2800, stopLoss: 2760, target: 2890 }}
      />
      <TopOpportunitiesModal
        isOpen={isTopOppsOpen}
        onClose={() => setIsTopOppsOpen(false)}
      />
      <SectorDrilldownModal
        isOpen={sectorDrilldown.isOpen}
        sector={sectorDrilldown.sector}
        onClose={() => setSectorDrilldown({ isOpen: false, sector: null })}
      />
      <MetricExplainerModal />
    </div>
  )
}

function MarketBadge() {
  const { status, nifty } = useMarketClock()

  const cfg = {
    'open':       { dot: 'bg-green animate-pulse', label: 'Market Open',      text: 'text-green', bg: 'bg-green/10 border-green/30' },
    'pre-open':   { dot: 'bg-amber animate-pulse', label: 'Pre-Market',       text: 'text-amber', bg: 'bg-amber/10 border-amber/30' },
    'post-close': { dot: 'bg-amber',               label: 'Post-Market',      text: 'text-amber', bg: 'bg-amber/10 border-amber/30' },
    'closed':     { dot: 'bg-subtle',              label: 'Market Closed',    text: 'text-muted', bg: 'bg-panel border-border' },
  }[status] ?? { dot: 'bg-subtle', label: 'Closed', text: 'text-muted', bg: 'bg-panel border-border' }

  return (
    <div className={`hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-ui ${cfg.bg}`}>
      <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      <span className={`font-semibold ${cfg.text}`}>
        {nifty ? `NIFTY ${nifty}` : cfg.label}
      </span>
    </div>
  )
}

function ThemeToggle({ theme, toggle }) {
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      className="flex items-center gap-1.5 bg-panel hover:bg-elevated text-text border border-border/80 px-2.5 py-1 rounded-lg text-xs font-ui transition-all shadow-xs cursor-pointer"
      title={`Current: ${isDark ? 'Dark Theme' : 'Light Theme'} — Click to toggle`}
    >
      <span className="text-sm">{isDark ? '🌙' : '☀️'}</span>
      <span className="text-[11px] font-medium hidden sm:inline">{isDark ? 'Dark' : 'Light'}</span>
    </button>
  )
}

function StatusDot() {
  const { port, sidecarError } = useChatStore()
  const connected = !!port && !sidecarError

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-panel border border-border/60 text-xs font-ui">
      <span
        className={`w-2 h-2 rounded-full transition-all ${
          connected ? 'bg-green shadow-[0_0_6px_rgba(16,185,129,0.7)]' : 'bg-red'
        }`}
      />
      <span className="text-muted text-[11px]">
        {sidecarError ? 'Offline' : connected ? 'Live' : 'Starting…'}
      </span>
    </div>
  )
}
