import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import TerminalView from '../renderer/src/components/Views/TerminalView'
import ContextBar from '../renderer/src/components/Shell/ContextBar'
import { useChatStore } from '../renderer/src/store/chatStore'

// Mock ResizeObserver
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

describe('TerminalView Decision Cockpit & Zero Redundancy Standard', () => {
  beforeEach(() => {
    useChatStore.setState({
      activeView: 'terminal',
      selectedSymbol: 'NIFTY',
    })

    global.fetch = vi.fn().mockImplementation((url) => {
      const urlStr = String(url)
      if (urlStr.includes('/skills/dashboard_snapshot')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              data: {
                symbol: 'NIFTY',
                exchange: 'NSE',
                ltp: 24500,
                change_pct: 0.5,
                automated_setup: {
                  symbol: 'NIFTY (NSE)',
                  action: 'LONG (BUY)',
                  entry: 24480,
                  stop_loss: 24360,
                  target_1: 24720,
                  risk_reward: '2.0',
                  status: 'READY',
                },
                order_block: { bottom: 24400, top: 24450 },
                volume_profile: { poc: 24460, vah: 24520, val: 24380 },
                watchlist: [],
                flows: { fii_net: 0, dii_net: 0, net_total: 0 },
                sector_matrix: [],
              },
              status: 'ok',
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
  })

  it('renders clean Decision Cockpit without any embedded chart canvas or collapsed banner', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    // Candlestick canvas must NOT be rendered on Terminal
    expect(screen.queryByTestId('mock-candlestick-chart')).toBeNull()

    // No collapsed banner or legacy toggle buttons
    expect(screen.queryByText(/Interactive Chart Hidden/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /Chart OFF/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Chart ON/i })).toBeNull()
  })

  it('provides a sleek 1-click button to route traders to dedicated Chart Studio', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    // Look for the "Open in Chart Studio ↗" buttons (Command Strip & HUD)
    const chartStudioBtns = screen.getAllByRole('button', { name: /Open in Chart Studio ↗/i })
    expect(chartStudioBtns.length).toBeGreaterThanOrEqual(1)

    // Clicking routes activeView to 'charts'
    await act(async () => {
      fireEvent.click(chartStudioBtns[0])
    })

    expect(useChatStore.getState().activeView).toBe('charts')
  })

  it('renders sleek self-clickable Poll on Symbol and Debate buttons', async () => {
    const sendDraftSpy = vi.fn()
    useChatStore.setState({ sendDraft: sendDraftSpy })

    await act(async () => {
      render(<TerminalView />)
    })

    const pollBtns = screen.getAllByRole('button', { name: /Poll on NIFTY/i })
    expect(pollBtns.length).toBeGreaterThanOrEqual(1)

    await act(async () => {
      fireEvent.click(pollBtns[0])
    })

    expect(sendDraftSpy).toHaveBeenCalledWith(expect.stringContaining('council'))

    const debateBtns = screen.getAllByRole('button', { name: /Run Debate/i })
    expect(debateBtns.length).toBeGreaterThanOrEqual(1)

    await act(async () => {
      fireEvent.click(debateBtns[0])
    })

    expect(sendDraftSpy).toHaveBeenCalledWith('analyze NIFTY')
  })

  it('renders Actionable Institutional Key Levels HUD (OB, POC, Value Area, ATR)', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    expect(screen.getByText(/UNMITIGATED OB/i)).toBeTruthy()
    expect(screen.getByText(/POC \(Max Volume\)/i)).toBeTruthy()
    expect(screen.getByText(/VALUE AREA \(70%\)/i)).toBeTruthy()
    expect(screen.getByText(/14D ATR VOLATILITY/i)).toBeTruthy()
  })

  it('renders elevated Smart Order Staging execution button and collapsible risk drawer', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    // Execute order button should be immediately accessible
    expect(screen.getByRole('button', { name: /STAGE \/ EXECUTE ORDER \(BUY\)/i })).toBeTruthy()

    // Risk Telemetry drawer should be collapsible
    const riskDrawerBtn = screen.getByRole('button', { name: /Risk Telemetry & ATR Trails/i })
    expect(riskDrawerBtn).toBeTruthy()
    expect(screen.queryByText(/PORTFOLIO HEAT METER/i)).toBeNull()

    // Click to expand risk telemetry details
    await act(async () => {
      fireEvent.click(riskDrawerBtn)
    })

    expect(screen.getByText(/PORTFOLIO HEAT METER/i)).toBeTruthy()
  })

  it('renders interactive Quant Position Sizer and passes sized quantity to onOpenOrderTicket', async () => {
    const onOpenOrderTicket = vi.fn()
    await act(async () => {
      render(<TerminalView onOpenOrderTicket={onOpenOrderTicket} />)
    })

    // Sizer header and budget pills
    expect(screen.getByText(/QUANT POSITION SIZER/i)).toBeTruthy()
    expect(screen.getByText(/CAPPED RISK/i)).toBeTruthy()
    expect(screen.getByText(/T1 PROFIT \(2R\)/i)).toBeTruthy()

    // Test clicking budget pill ₹5k
    const pill5k = screen.getByRole('button', { name: /₹5k/i })
    expect(pill5k).toBeTruthy()
    await act(async () => {
      fireEvent.click(pill5k)
    })

    // Click execute order button and check payload
    const stageBtn = screen.getByRole('button', { name: /STAGE \/ EXECUTE ORDER \(BUY\)/i })
    await act(async () => {
      fireEvent.click(stageBtn)
    })

    expect(onOpenOrderTicket).toHaveBeenCalledTimes(1)
    const payload = onOpenOrderTicket.mock.calls[0][0]
    expect(payload).toHaveProperty('quantity')
    expect(payload.quantity).toBeGreaterThan(0)
    expect(payload).toHaveProperty('lotSize')
  })

  it('renders Multi-Horizon switcher, Options & Intraday Edge Bar, and Quick Universe bar', async () => {
    await act(async () => {
      render(<TerminalView />)
    })

    // Multi-horizon pills in top command strip
    expect(screen.getByRole('button', { name: /15m/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /1h/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /1D/i })).toBeTruthy()

    // Options & Intraday Edge Bar in HUD
    expect(screen.getByText(/PCR:/i)).toBeTruthy()
    expect(screen.getByText(/Max Pain:/i)).toBeTruthy()
    expect(screen.getByText(/VWAP:/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Options Desk ↗/i })).toBeTruthy()

    // Quick universe bar
    expect(screen.getByText(/QUICK:/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: /BANKNIFTY/i })).toBeTruthy()
  })
})

