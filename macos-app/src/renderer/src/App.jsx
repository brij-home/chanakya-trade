import { useEffect, useState } from 'react'
import { useChatStore, getBaseUrl } from './store/chatStore'
import { useMarketClock } from './hooks/useMarketClock'
import Sidebar from './components/Sidebar'
import ChatArea from './components/Chat/ChatArea'
import InputBar from './components/Input/InputBar'
import TerminalView from './components/Views/TerminalView'
import DebateArenaView from './components/Views/DebateArenaView'
import OptionsDeskView from './components/Views/OptionsDeskView'
import SetupScreen from './components/SetupScreen'
import OnboardingWizard from './components/Onboarding/OnboardingWizard'
import CommandPalette from './components/Modals/CommandPalette'
import OrderTicketModal from './components/Modals/OrderTicketModal'
import TopOpportunitiesModal from './components/Modals/TopOpportunitiesModal'
import SectorDrilldownModal from './components/Modals/SectorDrilldownModal'
import MetricExplainerModal from './components/Modals/MetricExplainerModal'
import ActivityHUD from './components/Common/ActivityHUD'
import ErrorBoundary from './components/ErrorBoundary'

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
  const { setPort, setSidecarError, setBrokerStatuses, activeView, setActiveView } = useChatStore()
  const createSession = useChatStore((s) => s.createSession)
  const port = useChatStore((s) => s.port)
  const { theme, toggle: toggleTheme } = useTheme()

  // Setup phase state machine
  const [setupPhase, setSetupPhase] = useState('initializing')
  const [setupData, setSetupData] = useState(null)

  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false)
  const [isOrderTicketOpen, setIsOrderTicketOpen] = useState(false)
  const [orderTicketData, setOrderTicketData] = useState({
    symbol: 'RELIANCE',
    exchange: 'NSE',
    price: 2800,
    stopLoss: 2760,
    target: 2890,
  })
  const [isTopOppsOpen, setIsTopOppsOpen] = useState(false)
  const [sectorDrilldown, setSectorDrilldown] = useState({ isOpen: false, sector: null })

  // Listen for open-sector-drilldown & open-top-opportunities events
  useEffect(() => {
    const onOpenSector = (e) => {
      if (e.detail?.sector) {
        setSectorDrilldown({ isOpen: true, sector: e.detail.sector })
      }
    }
    const onOpenTop = () => setIsTopOppsOpen(true)
    const onCloseModals = () => {
      setIsCommandPaletteOpen(false)
      setIsTopOppsOpen(false)
      setSectorDrilldown({ isOpen: false, sector: null })
      setIsOrderTicketOpen(false)
    }

    window.addEventListener('open-sector-drilldown', onOpenSector)
    window.addEventListener('open-top-opportunities', onOpenTop)
    window.addEventListener('close-all-modals', onCloseModals)
    return () => {
      window.removeEventListener('open-sector-drilldown', onOpenSector)
      window.removeEventListener('open-top-opportunities', onOpenTop)
      window.removeEventListener('close-all-modals', onCloseModals)
    }
  }, [])

  useEffect(() => {
    // Web mode — no Electron IPC, just check if server is ready
    if (window.__CHANAKYA_TRADE_WEB__) {
      const checkReady = async () => {
        try {
          const res = await fetch('/api/onboarding/status')
          const currentPort = parseInt(window.location.port, 10) || 8765
          setPort(currentPort)
          if (res.ok) {
            const data = await res.json()
            if (data.onboarding_complete) {
              setSetupPhase('ready')
            } else {
              setSetupPhase('onboarding')
            }
          } else {
            setSetupPhase('ready')
          }
        } catch {
          const currentPort = parseInt(window.location.port, 10) || 8765
          setPort(currentPort)
          setSetupPhase('ready')
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

  // Keybindings: Cmd/Ctrl+1..4 for Workspaces, Cmd/Ctrl+N, Cmd/Ctrl+K, Cmd/Ctrl+O
  useEffect(() => {
    function onKeyDown(e) {
      if (e.metaKey || e.ctrlKey) {
        if (e.key === '1') {
          e.preventDefault()
          setActiveView('terminal')
        } else if (e.key === '2') {
          e.preventDefault()
          setActiveView('debate')
        } else if (e.key === '3') {
          e.preventDefault()
          setActiveView('options')
        } else if (e.key === '4') {
          e.preventDefault()
          setActiveView('copilot')
        } else if (e.key === 'n') {
          e.preventDefault()
          createSession()
        } else if (e.key.toLowerCase() === 'k') {
          e.preventDefault()
          setIsCommandPaletteOpen((prev) => !prev)
        } else if (e.key.toLowerCase() === 'o') {
          e.preventDefault()
          setIsTopOppsOpen((prev) => !prev)
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [createSession, setActiveView])

  const handleOpenOrderTicket = (ticketData) => {
    if (ticketData) {
      setOrderTicketData((prev) => ({ ...prev, ...ticketData }))
    }
    setIsOrderTicketOpen(true)
  }

  if (setupPhase === 'onboarding') {
    return <OnboardingWizard port={port} onComplete={() => setSetupPhase('ready')} />
  }

  if (setupPhase !== 'ready') {
    return <SetupScreen phase={setupPhase} data={setupData} />
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Top Main Navigation Bar */}
      <div className="drag flex items-center justify-between h-[56px] bg-panel border-b border-border flex-shrink-0 px-4 gap-3">
        {/* Brand & Logo */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          <span className="text-amber text-lg font-bold">◆</span>
          <span className="text-text text-sm font-bold tracking-wide font-ui hidden sm:inline">
            ChanakyaTrade
          </span>
        </div>

        {/* Center: Workspace Switcher Tabs */}
        <div className="no-drag flex items-center bg-elevated/80 border border-border/80 rounded-xl p-1 text-xs font-ui shadow-inner">
          <button
            type="button"
            onClick={() => setActiveView('terminal')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
              activeView === 'terminal'
                ? 'bg-amber text-black shadow-xs'
                : 'text-muted hover:text-text hover:bg-panel'
            }`}
            title="Strategic Quant Terminal (Ctrl+1)"
          >
            <span>📊</span>
            <span className="hidden md:inline">Terminal</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveView('debate')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
              activeView === 'debate'
                ? 'bg-emerald-500 text-black shadow-xs'
                : 'text-muted hover:text-text hover:bg-panel'
            }`}
            title="Multi-Agent Debate Arena (Ctrl+2)"
          >
            <span>⚔️</span>
            <span className="hidden md:inline">Debate Arena</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveView('options')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
              activeView === 'options'
                ? 'bg-cyan-400 text-black shadow-xs'
                : 'text-muted hover:text-text hover:bg-panel'
            }`}
            title="Quant & Options GEX Desk (Ctrl+3)"
          >
            <span>⚡</span>
            <span className="hidden md:inline">Options &amp; GEX</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveView('copilot')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
              activeView === 'copilot'
                ? 'bg-amber-light text-black shadow-xs'
                : 'text-muted hover:text-text hover:bg-panel'
            }`}
            title="AI Copilot Stream & Custom Quant (Ctrl+4)"
          >
            <span>💬</span>
            <span className="hidden md:inline">AI Copilot</span>
          </button>
        </div>

        {/* Omnibox / Search & Action Icons */}
        <div className="no-drag flex items-center gap-2">
          {/* Quick Search */}
          <button
            type="button"
            onClick={() => setIsCommandPaletteOpen(true)}
            className="hidden lg:flex items-center gap-2 bg-elevated/70 hover:bg-elevated text-muted hover:text-text border border-border/60 px-2.5 py-1.5 rounded-lg text-xs font-ui transition-all shadow-xs cursor-pointer"
          >
            <span>🔍 Search…</span>
            <kbd className="text-[10px] bg-panel border border-border px-1 rounded text-amber font-mono font-bold">
              ^K
            </kbd>
          </button>

          <button
            type="button"
            onClick={() => setIsTopOppsOpen(true)}
            className="hidden sm:flex items-center gap-1 bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 px-2.5 py-1 rounded-lg text-xs font-ui font-bold transition-colors cursor-pointer shadow-xs"
            title="Open Top 10 High-Conviction Opportunities Radar (Ctrl+O)"
          >
            <span>🎯</span> Radar
          </button>

          <button
            type="button"
            onClick={() => handleOpenOrderTicket()}
            className="hidden sm:flex items-center gap-1 bg-green/10 hover:bg-green/20 text-green border border-green/30 px-2.5 py-1 rounded-lg text-xs font-ui font-semibold transition-colors cursor-pointer"
          >
            <span>⚡</span> Order
          </button>

          <MarketBadge />
          <ThemeToggle theme={theme} toggle={toggleTheme} />
          <StatusDot />
        </div>
      </div>

      {/* Main Workspace Layout based on activeView */}
      <div className="flex flex-1 overflow-hidden">
        {/* If Copilot workspace, show the Sidebar */}
        {activeView === 'copilot' && <Sidebar />}

        {/* View Switcher Container with Error Boundary Protection */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <ErrorBoundary title="Strategic Quant Terminal">
            {activeView === 'terminal' && (
              <TerminalView onOpenOrderTicket={handleOpenOrderTicket} />
            )}

            {activeView === 'debate' && (
              <DebateArenaView onOpenOrderTicket={handleOpenOrderTicket} />
            )}

            {activeView === 'options' && (
              <OptionsDeskView onOpenOrderTicket={handleOpenOrderTicket} />
            )}

            {activeView === 'copilot' && (
              <>
                <ChatArea />
                <InputBar />
              </>
            )}
          </ErrorBoundary>
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
        initialData={orderTicketData}
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
      <ActivityHUD />
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
