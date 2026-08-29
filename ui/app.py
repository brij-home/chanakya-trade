"""
ui/app.py
─────────
Textual TUI — split-panel terminal UI.

Layout (Claude Code-inspired):
  ┌──────────────────────────────────┬────────────────────┐
  │                                  │  Live Indices      │
  │   Chat / Guidance Panel          │  (NIFTY, VIX...)   │
  │   (scrollable conversation       ├────────────────────┤
  │    with the AI agent)            │  Portfolio + Greeks│
  │                                  ├────────────────────┤
  │                                  │  Risk Meter        │
  ├──────────────────────────────────┴────────────────────┤
  │  Input ❯                                              │
  └────────────────────────────────────────────────────────┘

Keyboard shortcuts:
  Ctrl+B    Toggle morning brief
  Ctrl+O    Load options chain (prompts for symbol)
  Ctrl+R    Refresh all data panels
  Ctrl+P    Toggle paper / live mode display
  Ctrl+Q    Quit
  F1        Show help

Launch:
  python -m ui.app
  or from the REPL: `tui` command (added to repl.py)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import ClassVar

import pytz
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    Input,
    Static,
    Label,
    RichLog,
)

from ui.widgets.portfolio import PortfolioWidget
from ui.widgets.risk_meter import RiskMeterWidget
from ui.widgets.sector_rrg import SectorRRGWidget
from ui.widgets.forensic_view import ForensicWidget

IST = pytz.timezone("Asia/Kolkata")

REFRESH_INTERVAL = 30  # seconds between auto-refresh of market panels


class MarketTickerWidget(Static):
    """
    Top-right widget: live index levels + VIX.
    Auto-refreshes every REFRESH_INTERVAL seconds.
    """

    DEFAULT_CSS = """
    MarketTickerWidget {
        height: auto;
        border: round $primary;
        padding: 0 1;
    }
    MarketTickerWidget Label {
        color: $primary;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Market")
        yield Static(id="ticker-body", markup=True)

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(REFRESH_INTERVAL, self.refresh_data)

    def refresh_data(self) -> None:
        try:
            from market.indices import get_market_snapshot

            snap = get_market_snapshot()
            now = datetime.now(IST).strftime("%H:%M")

            def _row(name, val, chg):
                c = "green" if chg >= 0 else "red"
                s = "+" if chg >= 0 else ""
                return f"{name:<12} [bold]{val:>8,.0f}[/bold]  [{c}]{s}{chg:.2f}%[/{c}]"

            lines = [f"[dim]{now} IST[/dim]"]
            if snap.nifty:
                lines.append(_row("NIFTY 50", snap.nifty, snap.nifty_chg))
            if snap.banknifty:
                lines.append(_row("BANKNIFTY", snap.banknifty, snap.banknifty_chg))
            if snap.sensex:
                lines.append(_row("SENSEX", snap.sensex, snap.sensex_chg))
            if snap.india_vix:
                vc = "red" if snap.india_vix > 20 else "yellow" if snap.india_vix > 15 else "green"
                lines.append(f"India VIX    [{vc}]{snap.india_vix:>8.2f}[/{vc}]")

            posture_color = {"BULLISH": "green", "BEARISH": "red", "VOLATILE": "yellow"}.get(
                snap.posture, "white"
            )
            lines.append(f"\n[{posture_color}]{snap.posture}[/{posture_color}]")

            self.query_one("#ticker-body", Static).update("\n".join(lines))
        except Exception:
            self.query_one("#ticker-body", Static).update("[dim]Fetching...[/dim]")


class ChatPanel(RichLog):
    """
    Left panel: scrollable AI conversation output.
    Written to by the agent as it streams responses.
    """

    DEFAULT_CSS = """
    ChatPanel {
        border: round $surface;
        padding: 0 1;
        height: 1fr;
    }
    """


class TradingTUI(App):
    """
    The main Textual TUI application.

    All trading analysis flows through the chat panel — the right panels
    show live data that auto-refreshes, while the left panel is where
    the AI agent's guidance appears.
    """

    TITLE = "TradeAI — Institutional Trading Terminal"
    SUB_TITLE = f"Paper Mode | {datetime.now(IST).strftime('%d %b %Y')}"

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-row {
        layout: horizontal;
        height: 1fr;
    }

    #left-col {
        width: 2fr;
        layout: vertical;
    }

    #right-col {
        width: 1fr;
        layout: vertical;
        overflow-y: auto;
    }

    #chat-panel {
        height: 1fr;
        border: round $surface;
        padding: 0 1;
    }

    #input-bar {
        height: 3;
        border: round $accent;
        padding: 0 1;
    }

    #input-field {
        border: none;
        height: 1;
    }

    MarketTickerWidget {
        height: auto;
        max-height: 11;
    }

    SectorRRGWidget {
        height: auto;
        max-height: 12;
    }

    PortfolioWidget {
        height: auto;
        min-height: 8;
    }

    ForensicWidget {
        height: auto;
        max-height: 10;
    }

    RiskMeterWidget {
        height: auto;
        max-height: 8;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+b", "morning_brief", "Brief", show=True),
        Binding("ctrl+s", "sector_rrg", "RRG", show=True),
        Binding("ctrl+f", "forensic_audit", "Forensic", show=True),
        Binding("ctrl+o", "options_chain", "Options", show=True),
        Binding("ctrl+r", "refresh_all", "Refresh", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("f1", "show_help", "Help", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-row"):
            # Left: chat + input
            with Vertical(id="left-col"):
                yield ChatPanel(id="chat-panel", highlight=True, markup=True)
                with Static(id="input-bar"):
                    yield Input(
                        placeholder="Ask the agent, or type /rrg, /forensic INFY, /size NIFTY...",
                        id="input-field",
                    )

            # Right: live data panels
            with Vertical(id="right-col"):
                yield MarketTickerWidget(id="market-ticker")
                yield SectorRRGWidget(id="sector-rrg-widget")
                yield PortfolioWidget(id="portfolio-widget")
                yield ForensicWidget(id="forensic-widget")
                yield RiskMeterWidget(id="risk-widget")

        yield Footer()

    def on_mount(self) -> None:
        """Show welcome message and initialise the agent."""
        chat = self.query_one("#chat-panel", ChatPanel)
        mode = os.environ.get("TRADING_MODE", "PAPER")

        chat.write(
            f"[bold cyan]🚀  TradeAI — Institutional Trading Terminal[/bold cyan]\n"
            f"[dim]Mode: [bold]{mode}[/bold]   "
            f"Date: {datetime.now(IST).strftime('%d %b %Y  %I:%M %p IST')}[/dim]\n"
        )
        chat.write(
            "Type your question or command below.\n"
            "[dim]Commands:[/dim]\n"
            "  [cyan]rrg[/cyan]                  → Sector Relative Rotation Graph\n"
            "  [cyan]forensic RELIANCE[/cyan]    → Beneish & Altman Governance Audit\n"
            "  [cyan]size NIFTY 24000[/cyan]     → Volatility Risk-Parity Position Sizer\n"
            "  [cyan]funnel nifty_50[/cyan]       → 3-Stage Smart Funnel Screening\n"
            "  [cyan]brief[/cyan]                → Morning Market Brief\n"
        )

        # Pre-init the agent in background
        self.init_agent()

    @work(thread=True)
    def init_agent(self) -> None:
        try:
            from agent.core import get_agent

            get_agent()
        except Exception:
            pass

    # ── Input handling ────────────────────────────────────────

    @on(Input.Submitted, "#input-field")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self._handle_command(text)

    @work(thread=True)
    def _handle_command(self, text: str) -> None:
        """
        Route the input to direct local quantitative utilities or the AI agent.
        """
        chat = self.query_one("#chat-panel", ChatPanel)
        chat.write(f"\n[bold cyan]You ❯[/bold cyan] {text}\n")

        parts = text.split()
        cmd = parts[0].lower().lstrip("/") if parts else ""
        args = parts[1:]

        # Direct quantitative & analytical commands
        if cmd in ("refresh", "r"):
            self.call_from_thread(self.action_refresh_all)
            return
        if cmd in ("help", "?"):
            self.call_from_thread(self.action_show_help)
            return
        if cmd in ("rrg", "sector", "rotation"):
            try:
                from analysis.sector_rotation import get_sector_rrg_matrix

                points = get_sector_rrg_matrix(use_cache=True)
                chat.write("[bold green]🌐 Relative Rotation Graph (RRG) Sectors vs NIFTY 50:[/bold green]")
                for p in points:
                    q_col = "green" if p.quadrant == "LEADING" else "yellow" if p.quadrant == "WEAKENING" else "cyan" if p.quadrant == "IMPROVING" else "red"
                    chat.write(f"  • [bold]{p.sector:<10}[/bold] Ratio: {p.rs_ratio:>5.1f} | Mom: {p.rs_momentum:>5.1f} | [{q_col}]{p.quadrant}[/{q_col}]")
                return
            except Exception as exc:
                chat.write(f"[red]RRG error: {exc}[/red]")
                return

        if cmd in ("forensic", "audit", "fa"):
            sym = (args[0] if args else "RELIANCE").upper()
            try:
                from analysis.forensic import audit_forensics

                res = audit_forensics(sym)
                chat.write(f"[bold green]🛡️ Forensic Audit: {res.symbol} (Grade: {res.quality_rating})[/bold green]")
                chat.write(f"  • Beneish M-Score: {res.beneish_m_score:.2f} ({'FLAGGED' if res.is_beneish_flagged else 'CLEAN'})")
                chat.write(f"  • Altman Z''-Score: {res.altman_z_score:.2f} ({res.distress_zone} zone)")
                chat.write(f"  • Piotroski F-Score: {res.piotroski_f_score}/9")
                if res.governance_red_flags:
                    chat.write(f"  [red]⚠️ Red Flags: {'; '.join(res.governance_red_flags)}[/red]")
                return
            except Exception as exc:
                chat.write(f"[red]Forensic error: {exc}[/red]")
                return

        if cmd in ("size", "sizing", "position"):
            sym = (args[0] if args else "NIFTY").upper()
            entry = float(args[1]) if len(args) > 1 else 24000.0
            sl = float(args[2]) if len(args) > 2 else round(entry * 0.98, 2)
            try:
                from engine.position_sizer import calculate_position_size

                res = calculate_position_size(symbol=sym, entry_price=entry, stop_loss=sl)
                chat.write(f"[bold green]⚖️ Position Sizer: {res.symbol}[/bold green]")
                chat.write(f"  • Shares: [bold]{res.shares}[/bold] ({res.lots} lot{'s' if res.lots > 1 else ''})")
                chat.write(f"  • Capital: ₹{res.capital_allocated:,.0f} ({res.capital_pct:.1f}%) | Max Risk: ₹{res.risk_amount:,.0f}")
                return
            except Exception as exc:
                chat.write(f"[red]Sizing error: {exc}[/red]")
                return

        # Route everything else to the agent
        try:
            from agent.core import get_agent

            agent = get_agent()
            agent.chat(text)

            # Refresh side panels after agent response
            self.call_from_thread(self._refresh_side_panels)

        except Exception as e:
            chat.write(f"[red]Error: {e}[/red]\n")

    def _refresh_side_panels(self) -> None:
        try:
            self.query_one("#market-ticker", MarketTickerWidget).refresh_data()
            self.query_one("#sector-rrg-widget", SectorRRGWidget).refresh_data()
            self.query_one("#portfolio-widget", PortfolioWidget).refresh_data()
            self.query_one("#forensic-widget", ForensicWidget).refresh_data("RELIANCE")
            self.query_one("#risk-widget", RiskMeterWidget).refresh_data()
        except Exception:
            pass

    # ── Actions (keyboard shortcuts) ──────────────────────────

    def action_morning_brief(self) -> None:
        self._handle_command("brief")

    def action_sector_rrg(self) -> None:
        self._handle_command("rrg")

    def action_forensic_audit(self) -> None:
        self._handle_command("forensic RELIANCE")

    def action_options_chain(self) -> None:
        self._handle_command("Show me the NIFTY options chain")

    def action_refresh_all(self) -> None:
        self._refresh_side_panels()

    def action_show_help(self) -> None:
        chat = self.query_one("#chat-panel", ChatPanel)
        chat.write("""
[bold cyan]Keyboard Shortcuts:[/bold cyan]
  Ctrl+B  — Morning market brief
  Ctrl+S  — Sector RRG rotation matrix
  Ctrl+F  — Forensic quality audit (RELIANCE)
  Ctrl+O  — Options chain
  Ctrl+R  — Refresh all data panels
  Ctrl+Q  — Quit
  F1      — This help

[bold cyan]Commands:[/bold cyan]
  • rrg                         → Show sector momentum quadrants
  • forensic <symbol>           → Beneish, Altman & Piotroski audit
  • size <sym> <entry> <sl>     → Risk-parity position sizing
  • funnel <watchlist>          → Smart Funnel 3-stage screening
  • brief                       → Daily market posture & morning brief
""")


def run_tui() -> None:
    """Launch the Textual TUI."""
    app = TradingTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
