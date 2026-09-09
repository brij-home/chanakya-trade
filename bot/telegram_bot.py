"""
bot/telegram_bot.py
───────────────────
Telegram bot for the ChanakyaTrade CLI platform.

Commands:
  /start          — Welcome + command list
  /quote SYM      — Live quote for a stock
  /analyze SYM    — Quick analysis (scorecard, no full debate)
  /brief          — Morning market brief
  /flows          — FII/DII flow intelligence
  /earnings       — Upcoming earnings calendar
  /events         — Event-driven strategy recommendations
  /macro          — USD/INR, crude, gold snapshot
  /alert SYM above 2800  — Set a price alert
  /alerts         — List active alerts
  /memory         — Recent trade analyses
  /pnl            — Portfolio P&L summary
  /help           — Command reference

Also receives push notifications:
  - Alert triggers (price/technical/conditional)
  - Morning brief (scheduled, if configured)

Setup:
  1. Create a bot via @BotFather on Telegram → get the token
  2. Save: credentials setup → Telegram Bot Token
  3. Start: `telegram` command in REPL, or `python -m bot.telegram_bot`

Install: pip install python-telegram-bot
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import threading
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    from config.credentials import load_all as _load_keychain

    _load_keychain()
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress chatty third-party loggers at import time so they never
# flood the REPL regardless of when the bot thread starts.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("market.websocket").setLevel(logging.WARNING)
logging.getLogger("market").setLevel(logging.WARNING)


class _BotThreadFilter(logging.Filter):
    """
    Attached to the root logger's handlers.
    Only allows log records from the main thread (the REPL) through.
    All background threads (telegram-bot, executor pool, websocket, etc.)
    are silenced so their output never appears in the REPL.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return threading.current_thread().name == "MainThread"


class _BotThreadFileWrapper:
    """
    Wraps any file-like object and suppresses all writes from the
    telegram-bot thread at call time.

    Used in two places:
      1. Replaces sys.stdout so plain print() calls are silenced.
      2. Replaces the _file attribute on every existing Rich Console
         instance so that console.print() / progress spinners are
         silenced too (Rich stores a direct file reference at init time,
         so replacing sys.stdout alone is not enough).

    Thread-safe: the thread check happens at write time.
    """

    _bot_patched = True  # sentinel to avoid double-wrapping

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped

    def _is_bot_thread(self) -> bool:
        # Only the main thread (REPL) is allowed to produce terminal output.
        # All other threads (telegram-bot, executor pool, websocket, etc.)
        # are silenced.
        return threading.current_thread().name != "MainThread"

    def write(self, s: str) -> int:
        if self._is_bot_thread() or self._wrapped is None:
            return len(s) if isinstance(s, str) else 0
        return self._wrapped.write(s)  # type: ignore[union-attr]

    def flush(self) -> None:
        if not self._is_bot_thread() and self._wrapped is not None:
            self._wrapped.flush()  # type: ignore[union-attr]

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


# ── Telegram → REPL status badge ─────────────────────────────

import functools
from bot.status import set_active, clear_active


def _track_command(func):
    """Decorator that sets/clears the REPL status badge around a handler."""

    @functools.wraps(func)
    async def wrapper(update, context):
        cmd_text = update.message.text if update.message else func.__name__
        set_active(cmd_text)
        try:
            return await func(update, context)
        finally:
            clear_active()

    return wrapper


# ── Markdown → Telegram HTML helper ────────────────────────


def _md_to_html(text: str) -> str:
    """Convert common markdown to Telegram-compatible HTML.

    Handles: **bold**, *italic*, `code`, ```blocks```, ### headers,
    horizontal rules (━━━ / ---), and escapes HTML special chars first.
    """
    import re as _re

    # 1. Escape HTML special chars FIRST
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # 2. Code blocks (``` ... ```) — must be before inline code
    text = _re.sub(r"```(?:\w*\n)?(.*?)```", r"<pre>\1</pre>", text, flags=_re.DOTALL)

    # 3. Inline code (`code`)
    text = _re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # 4. Bold (**text**) — must be before italic
    text = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # 5. Italic (*text*) — but not **
    text = _re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)

    # 6. Headers (###, ##, #) — convert to bold
    text = _re.sub(r"^#{1,3}\s+(.+)$", r"<b>\1</b>", text, flags=_re.MULTILINE)

    # 7. Horizontal rules
    text = _re.sub(r"━{3,}", "—", text)
    text = _re.sub(r"^-{3,}$", "—", text, flags=_re.MULTILINE)

    return text


# ── Lazy imports to avoid startup overhead ───────────────────


def _get_telegram():
    try:
        from telegram import Update, Bot
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        return (
            Update,
            Bot,
            ApplicationBuilder,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        raise RuntimeError(
            "python-telegram-bot not installed. Run:\n  pip install python-telegram-bot"
        )


# ── Bot token management ─────────────────────────────────────


def _get_bot_token() -> str:
    """Get Telegram bot token from keychain or env."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        try:
            from config.credentials import _kr_get

            token = _kr_get("TELEGRAM_BOT_TOKEN") or ""
        except Exception:
            pass
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN not set.\n"
            "1. Talk to @BotFather on Telegram → create a bot → copy the token\n"
            "2. Run: credentials setup → enter Telegram Bot Token\n"
            "   Or set TELEGRAM_BOT_TOKEN in .env"
        )
    return token


# Chat ID for push notifications (set on first /start)
_chat_id: Optional[int] = None

# Background bot thread — kept here to prevent starting duplicates
_bot_thread: Optional[threading.Thread] = None

# Bounded push notification executor to prevent thread explosion on alert storms
_push_executor: Optional[Any] = None
_push_lock = threading.Lock()


def _get_push_executor() -> Any:
    global _push_executor
    with _push_lock:
        if _push_executor is None:
            import concurrent.futures

            _push_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="tg-push"
            )
        return _push_executor


# Thread-local flag: set to True on any thread that should produce no output.
# Used to silence executor threads spawned by run_in_executor during analysis,
# which have a different name from "telegram-bot" and would otherwise bypass
# the _BotThreadFileWrapper name check.
_suppress_output = threading.local()
_CHAT_ID_FILE = os.path.expanduser("~/.trading_platform/telegram_chat_id")


def _save_chat_id(chat_id: int) -> None:
    global _chat_id
    _chat_id = chat_id
    try:
        os.makedirs(os.path.dirname(_CHAT_ID_FILE), exist_ok=True)
        with open(_CHAT_ID_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception:
        pass


def _load_chat_id() -> Optional[int]:
    global _chat_id
    if _chat_id:
        return _chat_id
    env_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_id:
        try:
            _chat_id = int(env_id)
            return _chat_id
        except ValueError:
            pass
    try:
        from config.credentials import _kr_get

        kr_id = _kr_get("TELEGRAM_CHAT_ID")
        if kr_id:
            _chat_id = int(kr_id.strip())
            return _chat_id
    except Exception:
        pass
    try:
        with open(_CHAT_ID_FILE) as f:
            _chat_id = int(f.read().strip())
            return _chat_id
    except Exception:
        return None


# ── Command Handlers ─────────────────────────────────────────


async def cmd_start(update, context) -> None:
    """Handle /start command."""
    _save_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "Welcome to ChanakyaTrade CLI Bot!\n\n"
        "Commands:\n"
        "/quote RELIANCE — live price\n"
        "/analyze RELIANCE — full analysis (3-4 min)\n"
        "/deepanalyze RELIANCE — deep LLM analysis (7-10 min)\n"
        "/brief — morning market brief\n"
        "/conviction [SYMBOL] — 12-factor trade conviction score (0–100)\n"
        "/movers — daily top gainers & losers forensic autopsy\n"
        "/precursors — high-conviction coiling setups before breakout\n"
        "/scan [UNIVERSE] — scan top liquid/F&O list for breakouts & gamma blasts\n"
        "/radar — quick market radar on today's top liquid setups\n"
        "/flows — FII/DII flow signals\n"
        "/earnings — upcoming results\n"
        "/events — event strategies\n"
        "/macro — USD/INR, crude, gold\n"
        "/alert RELIANCE above 2800\n"
        "/alerts — list alerts\n"
        "/memory — recent analyses\n"
        "/pnl — portfolio P&L\n"
        "/help — this message\n\n"
        "Alerts will be pushed here automatically."
    )


async def cmd_help(update, context) -> None:
    await cmd_start(update, context)


async def cmd_quote(update, context) -> None:
    """Handle /quote SYMBOL."""
    if not context.args:
        await update.message.reply_text("Usage: /quote RELIANCE")
        return

    symbol = context.args[0].upper()
    try:
        from market.quotes import get_quote

        quotes = get_quote([f"NSE:{symbol}"])
        q = quotes.get(f"NSE:{symbol}")
        if q and q.last_price:
            chg_emoji = "📈" if (q.change or 0) >= 0 else "📉"
            await update.message.reply_text(
                f"{chg_emoji} {symbol}\n"
                f"LTP: ₹{q.last_price:,.2f}\n"
                f"Change: {q.change:+.2f} ({q.change_pct:+.2f}%)\n"
                f"Open: ₹{q.open:,.2f} | High: ₹{q.high:,.2f} | Low: ₹{q.low:,.2f}\n"
                f"Volume: {q.volume:,}"
            )
        else:
            await update.message.reply_text(f"Could not get quote for {symbol}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_analyze(update, context) -> None:
    """Handle /analyze SYMBOL — full multi-agent analysis, same as CLI."""
    if not context.args:
        await update.message.reply_text("Usage: /analyze RELIANCE")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(
        f"🔍 Running full analysis on {symbol}...\n"
        f"(7 analysts + debate + synthesis — takes 3-4 min)"
    )

    def _run_analysis() -> tuple:
        """Synchronous full pipeline — run in executor to avoid blocking event loop."""
        _suppress_output.active = True
        # Log to file — stdout and logging are both suppressed on this thread
        import tempfile
        import pathlib

        _logfile = pathlib.Path(tempfile.gettempdir()) / "tg_analyze.log"

        def _log(msg):  # noqa: E731
            with open(_logfile, "a") as f:
                f.write(f"{msg}\n")

        try:
            _log(f"Starting analysis for {symbol}")
            from agent.tools import build_registry
            from agent.multi_agent import MultiAgentAnalyzer, compute_scorecard
            from agent.core import get_provider

            os.environ["_CLI_BATCH_MODE"] = "1"
            registry = build_registry()
            _log("Registry built")
            provider = get_provider()
            _log(f"Provider: {provider}")
            analyzer = MultiAgentAnalyzer(registry, provider, verbose=False)

            # Run all 7 analysts
            reports = []
            for i, a in enumerate(analyzer.analysts):
                try:
                    _log(f"Analyst {i + 1}/{len(analyzer.analysts)}: {a.__class__.__name__}")
                    reports.append(a.analyze(symbol))
                except Exception as ex:
                    _log(f"Analyst {a.__class__.__name__} failed: {ex}")

            _log(f"Got {len(reports)} reports, computing scorecard")
            scorecard = compute_scorecard(reports)

            verdict_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
            analyst_lines = []
            for r in reports:
                if not r.error:
                    e = verdict_emoji.get(r.verdict, "⚪")
                    analyst_lines.append(f"{e} {r.analyst}: {r.verdict} ({r.confidence}%)")

            # Run debate + synthesis
            _log("Running debate")
            debate = analyzer._run_debate(symbol, "NSE", reports)
            _log("Running synthesis")
            synthesis = analyzer._run_synthesis(symbol, "NSE", reports, debate)
            _log("Pipeline complete")

            # ── Message 1: analyst scorecard ─────────────────────
            score_emoji = verdict_emoji.get(scorecard.verdict, "🟡")
            msg1 = (
                f"📊 {symbol} — Full Analysis\n\n"
                + "\n".join(analyst_lines)
                + f"\n\n{score_emoji} Scorecard: {scorecard.verdict} ({scorecard.weighted_total:+.1f})\n"
                f"Agreement: {scorecard.agreement:.0f}%"
            )
            if scorecard.conflicts:
                msg1 += f"\nConflicts: {', '.join(scorecard.conflicts)}"

            # ── Message 2: debate ─────────────────────────────────
            msg2 = ""
            if debate:
                parts = ["🥊 Bull vs Bear Debate\n"]
                if debate.bull_argument:
                    parts.append(f"🟢 BULL (Round 1)\n{debate.bull_argument.strip()[:800]}")
                if debate.bear_argument:
                    parts.append(f"\n🔴 BEAR (Round 1)\n{debate.bear_argument.strip()[:800]}")
                if debate.bull_rebuttal:
                    parts.append(f"\n🟢 BULL (Rebuttal)\n{debate.bull_rebuttal.strip()[:600]}")
                if debate.bear_rebuttal:
                    parts.append(f"\n🔴 BEAR (Rebuttal)\n{debate.bear_rebuttal.strip()[:600]}")
                if debate.facilitator:
                    parts.append(f"\n🎙 Facilitator\n{debate.facilitator.strip()[:600]}")
                if debate.winner:
                    win_e = "🟢" if debate.winner == "BULL" else "🔴"
                    parts.append(f"\nVerdict: {win_e} {debate.winner} prevailed")
                msg2 = "\n".join(parts)[:3800]

            # ── Message 3: synthesis ──────────────────────────────
            synth_text = (synthesis or "").strip()[:3800]
            msg3 = f"🧠 Synthesis\n\n{synth_text}" if synth_text else ""

            os.environ.pop("_CLI_BATCH_MODE", None)
            _log(f"Returning msgs: {len(msg1)} / {len(msg2)} / {len(msg3)} chars")
            return msg1, msg2, msg3

        except Exception as e:
            os.environ.pop("_CLI_BATCH_MODE", None)
            import traceback

            _log(f"FAILED: {e}\n{traceback.format_exc()}")
            return f"Analysis failed: {e}", "", ""
        finally:
            _suppress_output.active = False

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_analysis),
            timeout=300,  # 5 minute hard timeout
        )
        msg1, msg2, msg3 = (
            result if isinstance(result, tuple) and len(result) == 3 else (str(result), "", "")
        )
        # Telegram limit is 4096 chars per message.
        if msg1:
            await update.message.reply_text(_md_to_html(msg1[:4000]), parse_mode="HTML")
        if msg2:
            await update.message.reply_text(_md_to_html(msg2[:4000]), parse_mode="HTML")
        if msg3:
            await update.message.reply_text(_md_to_html(msg3[:4000]), parse_mode="HTML")
        if not msg1:
            await update.message.reply_text("Analysis completed but produced no output.")
    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ Analysis timed out after 5 minutes. Try again later.")
    except Exception as e:
        err = str(e)[:500]
        await update.message.reply_text(f"Analysis failed: {err}")


async def cmd_deepanalyze(update, context) -> None:
    """Handle /deepanalyze SYMBOL — full LLM deep analysis (11 calls)."""
    if not context.args:
        await update.message.reply_text("Usage: /deepanalyze RELIANCE")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(
        f"🔬 Running deep analysis on {symbol}...\n"
        f"(11 LLM calls — every analyst uses AI — takes 7-10 min)"
    )

    def _run_deep() -> tuple:
        _suppress_output.active = True
        import tempfile
        import pathlib

        _logfile = pathlib.Path(tempfile.gettempdir()) / "tg_deepanalyze.log"

        def _log(msg):
            with open(_logfile, "a") as f:
                f.write(f"{msg}\n")

        try:
            _log(f"Starting deep analysis for {symbol}")
            from agent.tools import build_registry
            from agent.deep_agent import DeepAnalyzer
            from agent.core import get_provider

            os.environ["_CLI_BATCH_MODE"] = "1"
            registry = build_registry()
            provider = get_provider()
            deep = DeepAnalyzer(registry, provider, verbose=False)

            # Run the full pipeline — returns a text report
            full_report = deep.analyze(symbol)
            _log(f"Deep analysis complete, report length: {len(full_report or '')}")

            if not full_report:
                return "Deep analysis produced no output.", "", ""

            # Split into 3 telegram-friendly messages
            # Message 1: analyst scorecard section
            # Message 2: debate section
            # Message 3: synthesis section
            parts = full_report.split("=" * 60)

            msg1 = f"🔬 {symbol} — Deep Analysis (Full LLM)\n\n"
            msg2 = ""
            msg3 = ""

            # Parse sections from the report
            for i, part in enumerate(parts):
                stripped = part.strip()
                if stripped.startswith("LLM ANALYST REPORTS"):
                    # Next section is the analyst reports
                    if i + 1 < len(parts):
                        msg1 += parts[i + 1].strip()[:3800]
                elif stripped.startswith("BULL/BEAR DEBATE"):
                    if i + 1 < len(parts):
                        msg2 = f"🥊 Deep Debate\n\n{parts[i + 1].strip()[:3800]}"
                elif stripped.startswith("FUND MANAGER SYNTHESIS"):
                    if i + 1 < len(parts):
                        msg3 = f"🧠 Deep Synthesis\n\n{parts[i + 1].strip()[:3800]}"

            # Fallback: if parsing didn't split well, send as chunks
            if not msg1 or msg1 == f"🔬 {symbol} — Deep Analysis (Full LLM)\n\n":
                msg1 = full_report[:4000]
                msg2 = full_report[4000:8000] if len(full_report) > 4000 else ""
                msg3 = full_report[8000:12000] if len(full_report) > 8000 else ""

            os.environ.pop("_CLI_BATCH_MODE", None)
            return msg1, msg2, msg3

        except Exception as e:
            os.environ.pop("_CLI_BATCH_MODE", None)
            import traceback

            _log(f"FAILED: {e}\n{traceback.format_exc()}")
            return f"Deep analysis failed: {e}", "", ""
        finally:
            _suppress_output.active = False

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_deep),
            timeout=600,  # 10 minute timeout for deep analysis
        )
        msg1, msg2, msg3 = (
            result if isinstance(result, tuple) and len(result) == 3 else (str(result), "", "")
        )
        if msg1:
            await update.message.reply_text(_md_to_html(msg1[:4000]), parse_mode="HTML")
        if msg2:
            await update.message.reply_text(_md_to_html(msg2[:4000]), parse_mode="HTML")
        if msg3:
            await update.message.reply_text(_md_to_html(msg3[:4000]), parse_mode="HTML")
        if not msg1:
            await update.message.reply_text("Deep analysis completed but produced no output.")
    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ Deep analysis timed out after 10 minutes.")
    except Exception as e:
        err = str(e)[:500]
        await update.message.reply_text(f"Deep analysis failed: {err}")


async def cmd_brief(update, context) -> None:
    """Handle /brief — market snapshot."""
    try:
        from market.indices import get_market_snapshot

        snap = get_market_snapshot()
        nifty = snap.nifty
        vix = snap.vix

        n_emoji = "📈" if nifty.change_pct >= 0 else "📉"
        await update.message.reply_text(
            f"🇮🇳 Market Brief\n\n"
            f"{n_emoji} NIFTY: {nifty.ltp:,.0f} ({nifty.change_pct:+.2f}%)\n"
            f"{'📈' if snap.banknifty.change_pct >= 0 else '📉'} BANKNIFTY: {snap.banknifty.ltp:,.0f} ({snap.banknifty.change_pct:+.2f}%)\n"
            f"⚡ VIX: {vix.ltp:.1f}\n"
            f"\nPosture: {snap.posture}\n{snap.posture_reason}"
        )
    except Exception as e:
        await update.message.reply_text(f"Brief failed: {e}")


async def cmd_flows(update, context) -> None:
    """Handle /flows — FII/DII intelligence."""
    try:
        from market.flow_intel import get_flow_analysis

        a = get_flow_analysis()
        flow_msg = (
            f"💰 FII/DII Flows\n\n"
            f"FII today: {a.fii_net_today:+,.0f} Cr\n"
            f"DII today: {a.dii_net_today:+,.0f} Cr\n"
            f"FII 5-day: {a.fii_5d_net:+,.0f} Cr\n"
            f"FII streak: {a.fii_streak} days\n"
            f"{'⚠️ Divergence: ' + a.divergence_type if a.divergence else ''}\n"
            f"\nSignal: {a.signal} ({a.confidence}%)\n"
            f"{a.signal_reason}"
        )
        await update.message.reply_text(_md_to_html(flow_msg), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Flow data failed: {e}")


async def cmd_earnings(update, context) -> None:
    """Handle /earnings."""
    try:
        from market.earnings import get_earnings_calendar, _current_quarter

        syms = [a.upper() for a in context.args] if context.args else None
        calendar = get_earnings_calendar(syms)

        if not calendar:
            await update.message.reply_text("No upcoming earnings found.")
            return

        lines = [f"📅 Earnings — {_current_quarter()}\n"]
        for e in calendar[:10]:
            move = f" (±{e.avg_move:.1f}%)" if e.avg_move else ""
            lines.append(f"  {e.symbol}: {e.result_date}{move}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Earnings failed: {e}")


async def cmd_events(update, context) -> None:
    """Handle /events."""
    try:
        from engine.event_strategies import get_event_strategies

        strategies = get_event_strategies(days_ahead=7)

        if not strategies:
            await update.message.reply_text("No events in next 7 days.")
            return

        lines = ["📆 Event Strategies (7 days)\n"]
        for s in strategies:
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(s.risk_level, "⚪")
            lines.append(f"{risk_emoji} {s.event} (in {s.days_away}d)")
            lines.append(f"   {s.strategy[:80]}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Events failed: {e}")


async def cmd_macro(update, context) -> None:
    """Handle /macro."""
    try:
        from market.macro import get_macro_snapshot

        snap = get_macro_snapshot()
        lines = ["🌍 Macro Snapshot\n"]
        if snap.usdinr:
            lines.append(
                f"USD/INR: {snap.usdinr:.2f} ({snap.usdinr_change:+.2f}%)"
                if snap.usdinr_change
                else f"USD/INR: {snap.usdinr:.2f}"
            )
        if snap.crude_oil:
            lines.append(
                f"Crude: ${snap.crude_oil:.1f}/bbl ({snap.crude_change:+.1f}%)"
                if snap.crude_change
                else f"Crude: ${snap.crude_oil:.1f}"
            )
        if snap.gold:
            lines.append(
                f"Gold: ${snap.gold:.0f}/oz ({snap.gold_change:+.1f}%)"
                if snap.gold_change
                else f"Gold: ${snap.gold:.0f}"
            )
        if snap.us_10y:
            lines.append(f"US 10Y: {snap.us_10y:.2f}%")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Macro failed: {e}")


async def cmd_alert(update, context) -> None:
    """Handle /alert SYMBOL above/below PRICE."""
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /alert RELIANCE above 2800")
        return

    try:
        from engine.alerts import alert_manager

        symbol = context.args[0].upper()
        condition = context.args[1].upper()
        threshold = float(context.args[2])
        alert = alert_manager.add_price_alert(symbol, condition, threshold)
        await update.message.reply_text(f"✅ Alert set: {alert.describe()} (ID: {alert.id})")
    except Exception as e:
        await update.message.reply_text(f"Alert failed: {e}")


async def cmd_alerts(update, context) -> None:
    """Handle /alerts — list active alerts."""
    try:
        from engine.alerts import alert_manager

        active = [a for a in alert_manager._alerts if not a.triggered]
        if not active:
            await update.message.reply_text("No active alerts.")
            return
        lines = ["🔔 Active Alerts\n"]
        for a in active:
            lines.append(f"  [{a.id}] {a.describe()}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Alerts failed: {e}")


async def cmd_memory(update, context) -> None:
    """Handle /memory — recent analyses."""
    try:
        from engine.memory import trade_memory

        recent = list(reversed(trade_memory._records[-5:]))
        if not recent:
            await update.message.reply_text("No analyses stored yet.")
            return
        lines = ["📝 Recent Analyses\n"]
        for r in recent:
            outcome = f" → {r.outcome}" if r.outcome else ""
            lines.append(
                f"  [{r.id}] {r.timestamp[:10]} {r.symbol}: {r.verdict} ({r.confidence}%){outcome}"
            )
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Memory failed: {e}")


async def cmd_pnl(update, context) -> None:
    """Handle /pnl — portfolio summary."""
    try:
        from engine.portfolio import get_portfolio_summary

        summary = get_portfolio_summary()
        pnl_emoji = "📈" if summary.total_pnl >= 0 else "📉"
        await update.message.reply_text(
            f"💼 Portfolio\n\n"
            f"Value: ₹{summary.total_value:,.0f}\n"
            f"{pnl_emoji} P&L: ₹{summary.total_pnl:+,.0f}\n"
            f"Day P&L: ₹{summary.day_pnl:+,.0f}\n"
            f"Risk: {summary.risk.risk_rating} ({summary.risk.deployment_pct:.0f}% deployed)"
        )
    except Exception as e:
        await update.message.reply_text(f"Portfolio failed: {e}")


async def cmd_conviction(update, context) -> None:
    """Handle /conviction [SYMBOL] — 12-Factor Orthogonal Conviction Score."""
    symbol = context.args[0].upper() if context.args else "NIFTY"
    try:
        from engine.conviction_score import get_conviction_score
        from market.quotes import get_quote

        # Get spot price
        quotes = get_quote([f"NSE:{symbol}"])
        q = quotes.get(f"NSE:{symbol}")
        spot = float(q.last_price) if q and q.last_price else 0.0

        conviction = get_conviction_score(underlying=symbol, spot=spot)

        verdict_icon = {
            "MAX_CONVICTION": "🔥",
            "HIGH": "✅",
            "MODERATE": "⚠️",
            "WAIT": "🛑",
        }.get(conviction.verdict, "⚪")

        # Group factors by axis
        axis_scores: dict[str, list] = {}
        for f in conviction.factors:
            axis_scores.setdefault(f.axis, []).append(f)

        axis_icons = {
            "INSTITUTIONAL": "🏛️",
            "MACRO": "🌐",
            "OPTIONS": "⚡",
            "PRICE": "📊",
            "TIMING": "⏱️",
        }

        axis_summary = []
        for ax in ["INSTITUTIONAL", "MACRO", "OPTIONS", "PRICE", "TIMING"]:
            f_list = axis_scores.get(ax, [])
            if f_list:
                avg_score = sum(f.score for f in f_list) / len(f_list)
                icon = axis_icons.get(ax, "🔹")
                axis_summary.append(f"  {icon} {ax.title()}: {avg_score:.1f}/10")

        lines = [
            f"🎯 <b>{symbol} — 12-Factor Conviction Score</b>\n",
            f"Score: <b>{conviction.total_score}/100</b> ({verdict_icon} {conviction.verdict})",
            f"Sizing: <b>{conviction.recommended_position_size}</b>",
            f"Factors: 🟢 {conviction.bullish_count}▲ | 🔴 {conviction.bearish_count}▼ | ⚪ {conviction.unavailable_count}—\n",
        ]

        if conviction.veto and conviction.veto.vetoed:
            lines.append(f"⛔ <b>VETO ACTIVE:</b> {conviction.veto.reason}\n")

        lines.append("<b>5-Axis Orthogonal Breakdown:</b>")
        lines.extend(axis_summary)

        # Highlight decisive factors
        sorted_factors = sorted(conviction.factors, key=lambda x: abs(x.score - 5), reverse=True)
        top_factors = sorted_factors[:4]
        lines.append("\n<b>Top Decisive Factor Drivers:</b>")
        for f in top_factors:
            s_icon = "🟢" if f.signal == "BULLISH" else "🔴" if f.signal == "BEARISH" else "⚪"
            detail_clip = (f.detail[:75] + "...") if len(f.detail) > 75 else f.detail
            lines.append(f"  {s_icon} <b>{f.label}</b> ({f.score}/10): {detail_clip}")

        # Real Data-Driven Trade Plan (R:R & ETA)
        if conviction.trade_plan:
            tp = conviction.trade_plan
            asym_icon = "✅" if tp.is_asymmetry_viable else "⚠️"
            lines.append("\n<b>📐 Data-Driven Trade Plan (Zero Guesswork):</b>")
            lines.append(f"  • Direction: <b>{tp.direction}</b> @ ₹{tp.entry_price:,.1f}")
            lines.append(
                f"  • Invalidation (SL): <b>₹{tp.invalidation_stop:,.1f}</b> (-{tp.stop_distance_pts:,.1f} pts)"
            )
            lines.append(f"    <i>{tp.sl_rationale}</i>")
            lines.append(
                f"  • Target 1: <b>₹{tp.target_1:,.1f}</b> (+{tp.t1_distance_pts:,.1f} pts | <b>{tp.rr_t1}:1 R:R</b>)"
            )
            lines.append(f"    <i>{tp.t1_rationale}</i>")
            lines.append(f"    ⏱️ <b>ETA T1:</b> {tp.eta_t1_str}")
            lines.append(
                f"  • Target 2: <b>₹{tp.target_2:,.1f}</b> (+{tp.t2_distance_pts:,.1f} pts | <b>{tp.rr_t2}:1 R:R</b>)"
            )
            lines.append(f"    <i>{tp.t2_rationale}</i>")
            lines.append(f"    ⏱️ <b>ETA T2:</b> {tp.eta_t2_str}")
            lines.append(f"  • Expectancy: {asym_icon} <b>{tp.asymmetry_verdict}</b>")
            if tp.structure_advice:
                lines.append(f"  • Structure: <i>{tp.structure_advice}</i>")
            if tp.session_clock_note:
                lines.append(f"  • Clock: <i>{tp.session_clock_note}</i>")

        lines.append(f"\n<i>Calibrated as of: {conviction.as_of}</i>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Conviction scoring failed: {e}")


async def cmd_scan(update, context) -> None:
    """Handle /scan [UNIVERSE] or /radar — scans high-liquidity universe for breakout/gamma setups."""
    universe = context.args[0].lower() if context.args else "most_liquid_today"
    await update.message.reply_text(
        f"🔍 <b>Scanning '{universe.upper()}' for Breakouts & Gamma Surges...</b>\n"
        f"<i>Evaluating TTM squeeze coiling, volume expansion, options OI liquidation, and structural R:R...</i>",
        parse_mode="HTML",
    )

    def _run_scan() -> str:
        from analysis.universe import resolve_dynamic_universe, THEMATIC_PRESETS
        from analysis.execution_gate import evaluate_execution_gate
        from engine.trade_plan import calculate_trade_plan
        from market.quotes import get_quote

        symbols, desc = resolve_dynamic_universe(universe, max_stocks=15)
        if not symbols:
            symbols = THEMATIC_PRESETS.get("most_liquid_today", {}).get("symbols", [])[:15]

        quotes = get_quote([f"NSE:{s}" for s in symbols])

        candidates = []
        for s in symbols:
            try:
                q = quotes.get(f"NSE:{s}")
                if not q or not q.last_price or q.last_price <= 0:
                    continue
                gate = evaluate_execution_gate(s)
                tp = calculate_trade_plan(s, direction=gate.trade_bias, spot=q.last_price)
                candidates.append((s, q, gate, tp))
            except Exception:
                continue

        if not candidates:
            return "No valid candidates returned from scan."

        # Sort: READY first, then by tactical score descending, then by R:R
        candidates.sort(
            key=lambda x: (
                1
                if x[2].execution_status == "READY"
                else (0.5 if x[2].execution_status == "STALK" else 0),
                x[2].tactical_score,
                x[3].rr_t1 if x[3] else 0,
            ),
            reverse=True,
        )

        lines = [
            f"⚡ <b>Chanakya Market Radar — {universe.upper()}</b>\n",
            f"<i>Universe: {desc}</i>\n",
        ]

        top_picks = candidates[:5]
        for i, (sym, q, gate, tp) in enumerate(top_picks, 1):
            st_badge = (
                "🚀 READY"
                if gate.execution_status == "READY"
                else ("🎯 STALK" if gate.execution_status == "STALK" else "👀 WATCH")
            )
            chg_sign = "+" if (q.change_pct or 0) >= 0 else ""
            lines.append(
                f"<b>{i}. {sym}</b> · ₹{q.last_price:,.1f} ({chg_sign}{q.change_pct or 0:.2f}%) · <b>{st_badge}</b>"
            )
            lines.append(
                f"   📊 Strat: {gate.strategic_score}/100 | Tact: {gate.tactical_score}/100 | RVOL: {gate.rvol:.1f}x"
            )
            if tp and tp.invalidation_stop > 0:
                sl_sign = "-" if tp.direction == "LONG" else "+"
                lines.append(
                    f"   🛑 SL: <b>₹{tp.invalidation_stop:,.1f}</b> ({sl_sign}{tp.stop_distance_pts:,.1f} pts) | T1: <b>₹{tp.target_1:,.1f}</b> ({tp.rr_t1}:1 R:R)"
                )
                lines.append(
                    f"   ⏱️ ETA: <b>{tp.eta_t1_str}</b> | Flow: <i>{gate.options_oi_regime}</i>"
                )
            lines.append("")

        lines.append(
            "<i>Use /conviction [SYMBOL] for 12-factor deep audit and exact invalidation levels.</i>"
        )
        return "\n".join(lines)

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_scan),
            timeout=60,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ Scan timed out. Try a smaller universe or single stock.")
    except Exception as e:
        await update.message.reply_text(f"Scan failed: {e}")


async def cmd_movers(update, context) -> None:
    """Handle /movers [fno|cash|index] — Daily Top 10 Gainers & Losers forensic autopsy report."""
    arg = context.args[0].upper() if context.args else "ALL"
    if arg in ("FNO", "F&O"):
        segment = "FNO"
        seg_label = "F&O DERIVATIVES"
    elif arg in ("CASH", "NON_FNO", "EQUITY"):
        segment = "NON_FNO"
        seg_label = "NON-F&O CASH"
    elif arg in ("INDEX", "INDICES"):
        segment = "INDEX"
        seg_label = "INDICES"
    else:
        segment = None
        seg_label = "ALL UNIVERSES"

    await update.message.reply_text(
        f"🔬 <b>Running Top Movers Forensic Autopsy [{seg_label}]...</b>\n"
        "<i>Analyzing 5-dimensional causal drivers, control group contrast, and trap filters...</i>",
        parse_mode="HTML",
    )

    def _run_autopsy_summary() -> str:
        from engine.mover_autopsy import mover_autopsy_engine

        autopsy = mover_autopsy_engine.get_latest_autopsy()
        if not autopsy:
            autopsy = mover_autopsy_engine.run_daily_autopsy(segment=segment)

        if not autopsy:
            return f"No mover autopsy report available for {seg_label}."

        lines = [
            f"🔬 <b>DAILY MOVER FORENSIC AUTOPSY [{seg_label}] — {autopsy.date}</b>\n"
            f"<i>Market Regime: <b>{autopsy.market_regime}</b> | Traps Filtered: <b>{autopsy.traps_filtered}</b></i>\n",
            "🚀 <b>TOP GAINERS (Causal Breakdown):</b>",
        ]

        # Filter by segment if specified
        all_gainers = autopsy.gainers
        all_losers = autopsy.losers
        if segment:
            all_gainers = [g for g in all_gainers if g.segment == segment or (segment == "FNO" and g.is_fo)]
            all_losers = [l for l in all_losers if l.segment == segment or (segment == "FNO" and l.is_fo)]

        valid_gainers = [g for g in all_gainers if not g.is_trap][:5]
        for g in valid_gainers:
            clean_arch = g.archetype.replace("ARCHETYPE_", "").replace("_", " ").title()
            factors_short = "; ".join(g.deciding_factors[:2]) if g.deciding_factors else "Momentum expansion"
            lines.append(
                f"• <b>{g.symbol} [{g.segment}]</b>: <b>+{g.change_pct:.1f}%</b> (RVOL: {g.rvol:.1f}x)\n"
                f"  🏷️ <i>{clean_arch}</i>\n"
                f"  💡 {factors_short}"
            )

        lines.append("\n🩸 <b>TOP LOSERS (Breakdown Breakdown):</b>")
        valid_losers = [l for l in all_losers if not l.is_trap][:3]
        for l in valid_losers:
            lines.append(
                f"• <b>{l.symbol} [{l.segment}]</b>: <b>{l.change_pct:.1f}%</b> (RVOL: {l.rvol:.1f}x) | <i>{l.derivative_verdict}</i>"
            )

        if autopsy.top_predictive_precursors:
            lines.append("\n🧠 <b>TOP STATISTICAL PRECURSORS (Signal vs Noise):</b>")
            for p in autopsy.top_predictive_precursors[:3]:
                lines.append(f"• <b>{p}</b>")

        traps = [m for m in (autopsy.gainers + autopsy.losers) if m.is_trap]
        if traps:
            lines.append(f"\n🛡️ <b>TRAPS FILTERED OUT ({len(traps)}):</b>")
            for t in traps[:2]:
                lines.append(f"• <b>{t.symbol}</b> ({t.change_pct:+.1f}%): <i>{t.trap_reason}</i>")

        lines.append("\n⚡ <i>Chanakya Institutional Quantitative Forensics</i>")
        return "\n".join(lines)

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_autopsy_summary),
            timeout=45,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Autopsy failed: {e}")


async def cmd_precursors(update, context) -> None:
    """Handle /precursors [fno|cash|index] — Scans for tomorrow's high-conviction coiling setups."""
    arg = context.args[0].upper() if context.args else "ALL"
    if arg in ("FNO", "F&O"):
        segment = "FNO"
        seg_label = "F&O DERIVATIVES"
    elif arg in ("CASH", "NON_FNO", "EQUITY"):
        segment = "NON_FNO"
        seg_label = "NON-F&O CASH"
    elif arg in ("INDEX", "INDICES"):
        segment = "INDEX"
        seg_label = "INDICES"
    else:
        segment = None
        seg_label = "ALL UNIVERSES"

    await update.message.reply_text(
        f"⚡ <b>Scanning Pre-Ignition Radar Setups [{seg_label}]...</b>\n"
        "<i>Searching for volume dry-up, squeeze coiling, and institutional order block anchors...</i>",
        parse_mode="HTML",
    )

    def _run_precursors_summary() -> str:
        from engine.precursor_radar import precursor_radar

        candidates = precursor_radar.scan_precursors(segment=segment, top_n=5)
        if not candidates:
            return (
                f"🛡️ <b>No qualified pre-breakout setups in {seg_label} right now.</b>\n"
                "All scanned candidates failed minimum 75/100 conviction or were penalized below VWAP.\n"
                "<i>Disciplined quants wait for the market to come to them.</i>"
            )

        lines = [
            f"⚡ <b>CHANAKYA PRECURSOR RADAR [{seg_label}] — {len(candidates)} SETUPS</b>\n"
            f"<i>Candidates exhibiting pre-move DNA before explosive breakouts:</i>\n",
        ]

        for c in candidates:
            icon = "🔥" if c.conviction_score >= 85 else "✅"
            factors_brief = "\n  • ".join(c.matched_factors[:2])
            lines.append(
                f"{icon} <b>{c.symbol} [{c.segment}]</b> — 🧠 <b>Score: {c.conviction_score}/100</b> ({c.verdict})\n"
                f"  💰 <b>LTP:</b> ₹{c.ltp:,.2f} | <b>Sector:</b> {c.sector_name} ({c.rrg_quadrant})\n"
                f"  🎯 <b>Entry Zone:</b> <code>{c.entry_range}</code>\n"
                f"  🛑 <b>SL:</b> <code>₹{c.stop_loss:,.2f}</code> | 🎯 <b>T1:</b> <code>₹{c.target_1:,.2f}</code> ({c.risk_reward} R:R)\n"
                f"  📊 <b>Pre-Move Precursors:</b>\n  • {factors_brief}\n"
                f"  💡 <b>Execution Rule:</b> <i>{c.when_to_wait}</i>\n"
            )

        lines.append("⚡ <i>Chanakya Institutional Momentum Intelligence</i>")
        return "\n".join(lines)

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_precursors_summary),
            timeout=45,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Precursor scan failed: {e}")


async def cmd_unknown(update, context) -> None:
    """Handle unknown messages."""
    await update.message.reply_text("Unknown command. Type /help for available commands.")


# ── Token validation ─────────────────────────────────────────


def validate_token(token: str) -> tuple[bool, str]:
    """
    Validate a bot token by calling the Telegram getMe API.

    Returns:
        (True,  "@username (Bot Name)")  on success
        (False, "error description")     on failure
    """
    try:
        import httpx

        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            info = data["result"]
            return True, f"@{info.get('username', '?')} ({info.get('first_name', '?')})"
        return False, data.get("description", "Unknown error from Telegram API")
    except Exception as e:
        return False, f"Could not reach Telegram: {e}"


def send_test_push(chat_id: Optional[int] = None, token: Optional[str] = None) -> bool:
    """
    Send a test message to verify the full setup is working.
    Uses the provided chat_id/token or falls back to stored values.
    Returns True if the message was delivered successfully.
    """
    cid = chat_id or _load_chat_id()
    if not cid:
        return False
    try:
        tok = token or _get_bot_token()
    except Exception:
        return False
    try:
        import httpx

        resp = httpx.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={
                "chat_id": cid,
                "text": (
                    "✅ ChanakyaTrade CLI connected!\n\n"
                    "You'll receive notifications here for:\n"
                    "  • Price alert triggers\n"
                    "  • Paper trade executions\n"
                    "  • Strategy signals\n\n"
                    "Try /help to see all available commands."
                ),
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return resp.json().get("ok", False)
    except Exception:
        return False


def wait_for_start(timeout: int = 120) -> bool:
    """
    Wait (poll) until the user sends /start to the bot, which saves the chat ID.
    The bot must already be running in the background before calling this.

    Args:
        timeout: Maximum seconds to wait (default 120).

    Returns:
        True if the chat ID was received within the timeout, False otherwise.
    """
    import time

    for _ in range(timeout):
        if _load_chat_id():
            return True
        time.sleep(1)
    return False


def run_setup_wizard() -> None:
    """
    Full end-to-end interactive Telegram setup wizard.

    Flow:
      Step 1 — Collect / confirm bot token
      Step 2 — Validate token with Telegram API
      Step 3 — Start bot, wait for user to send /start, send test message
    """
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()

    console.print("\n[bold cyan]━━━ Telegram Bot Setup ━━━[/bold cyan]")
    console.print("[dim]Connects your bot for push notifications and Telegram commands.[/dim]\n")

    # ── Step 1: Token ─────────────────────────────────────────
    console.print("[bold]Step 1 of 3 — Bot Token[/bold]")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        try:
            from config.credentials import _kr_get

            token = _kr_get("TELEGRAM_BOT_TOKEN") or ""
        except Exception:
            pass

    if token:
        console.print("  [green]✓ Token found in keychain/env[/green]")
    else:
        console.print(
            "\n  No token found. Here's how to create one:\n\n"
            "    1. Open Telegram → search [bold cyan]@BotFather[/bold cyan]\n"
            "    2. Send [cyan]/newbot[/cyan]\n"
            "    3. Choose a name    e.g. [dim]My Trade Bot[/dim]\n"
            "    4. Choose a username ending in [bold]bot[/bold]    e.g. [dim]mytrade_bot[/dim]\n"
            "    5. Copy the token BotFather gives you\n"
        )
        token = Prompt.ask("  Paste your bot token", password=True).strip()
        if not token:
            console.print("[red]No token provided. Setup cancelled.[/red]")
            return

        try:
            from config.credentials import _kr_set

            if _kr_set("TELEGRAM_BOT_TOKEN", token):
                os.environ["TELEGRAM_BOT_TOKEN"] = token
                console.print("  [green]✓ Token saved to keychain[/green]")
            else:
                os.environ["TELEGRAM_BOT_TOKEN"] = token
                console.print(
                    "  [yellow]⚠  Keychain unavailable — token active for this session only.[/yellow]"
                )
        except Exception:
            os.environ["TELEGRAM_BOT_TOKEN"] = token

    # ── Step 2: Validate ──────────────────────────────────────
    console.print("\n[bold]Step 2 of 3 — Validate Token[/bold]")
    console.print("  Checking with Telegram...")

    ok, info = validate_token(token)
    if not ok:
        console.print(
            f"  [red]✗ Token rejected: {info}[/red]\n"
            "  [dim]Double-check the token from @BotFather and run [bold]telegram setup[/bold] again.[/dim]"
        )
        return

    console.print(f"  [green]✓ Bot verified: {info}[/green]")

    # ── Step 3: Connect chat ───────────────────────────────────
    console.print("\n[bold]Step 3 of 3 — Connect Your Chat[/bold]")

    existing = _load_chat_id()
    if existing:
        console.print(f"  [green]✓ Chat already connected (ID: {existing})[/green]")
        console.print("  Sending test notification...")
        if send_test_push(existing, token):
            console.print("  [green]✓ Test message sent! Check your Telegram.[/green]")
        else:
            console.print("  [yellow]⚠  Message failed — check the bot isn't blocked.[/yellow]")
    else:
        bot_handle = info.split("(")[0].strip()  # e.g. "@mytrade_bot"
        console.print(
            f"\n  Open Telegram and send [bold]/start[/bold] to your bot [cyan]{bot_handle}[/cyan]\n"
            "  Waiting up to 2 minutes...\n"
        )

        run_bot_background()

        if wait_for_start(timeout=120):
            chat_id = _load_chat_id()
            console.print(f"  [green]✓ Connected! (Chat ID: {chat_id})[/green]")
            console.print("  Sending test notification...")
            if send_test_push(chat_id, token):
                console.print("  [green]✓ Test message delivered. Check your Telegram.[/green]")
            else:
                console.print(
                    "  [yellow]⚠  Bot connected but test message failed — try /start again.[/yellow]"
                )
        else:
            console.print(
                "\n  [yellow]⏱  Timed out — didn't receive /start within 2 minutes.[/yellow]\n"
                "  The bot is still running in the background.\n"
                "  [dim]Send /start to your bot whenever you're ready.[/dim]"
            )
            return

    console.print(
        "\n[bold green]✓  Telegram setup complete![/bold green]\n"
        "[dim]The bot will push alerts, paper trade signals, and strategy\n"
        "notifications here automatically. Use [bold]telegram[/bold] in the\n"
        "REPL to restart the bot in future sessions.[/dim]\n"
    )


# ── Push Notifications & Anti-Duplicate Buffer ────────────────
_recent_push_digests: dict[str, float] = {}
_push_dedup_lock = threading.Lock()
_PUSH_DEDUP_WINDOW_SEC = 300.0  # 5 minutes suppression for duplicate messages


def _normalize_push_message(msg: str) -> str:
    """Strips timestamps, tags, and dynamic spacing for canonical deduplication hashing."""
    import re

    # Remove timestamps like 2026-09-07 15:45:00, 15:45:00 IST, etc.
    s = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(\s+IST)?", "", msg)
    s = re.sub(r"\d{2}:\d{2}:\d{2}(\s+IST)?", "", s)
    # Remove HTML tags
    s = re.sub(r"<[^>]+>", "", s)
    # Collapse whitespace
    return " ".join(s.split()).strip().lower()


def send_push(message: str, parse_mode: str = "HTML", bypass_dedup: bool = False) -> None:
    """
    Send a push notification to the configured Telegram chat.
    Called from alerts, morning brief scheduler, execution gate, etc.
    Non-blocking — runs in a background thread.
    Includes a 5-minute anti-flood message deduplication guard.
    """
    import hashlib
    import time

    chat_id = _load_chat_id()
    if not chat_id:
        return

    try:
        token = _get_bot_token()
    except Exception:
        return

    now = time.time()
    if not bypass_dedup:
        normalized = _normalize_push_message(message)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        with _push_dedup_lock:
            # Clean expired items if buffer is growing
            if len(_recent_push_digests) > 200:
                expired = [
                    k for k, ts in _recent_push_digests.items() if now - ts > _PUSH_DEDUP_WINDOW_SEC
                ]
                for k in expired:
                    del _recent_push_digests[k]

            last_sent = _recent_push_digests.get(digest, 0.0)
            if (now - last_sent) < _PUSH_DEDUP_WINDOW_SEC:
                logger.debug(
                    f"[TelegramPush] Suppressed duplicate push notification (hash={digest[:8]})"
                )
                return

            _recent_push_digests[digest] = now

    def _send():
        if os.environ.get("CHANAKYA_TESTING") == "1":
            logger.debug(
                "[TelegramPush] Network call skipped during test execution (CHANAKYA_TESTING=1)"
            )
            return
        try:
            import httpx
            import re

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": message}
            if parse_mode:
                payload["parse_mode"] = parse_mode

            resp = httpx.post(url, json=payload, timeout=10)
            # If HTML parsing fails due to any unescaped tags/characters, retry as plain text so the alert is never lost
            if not resp.is_success and parse_mode == "HTML":
                clean_text = re.sub(r"<[^>]+>", "", message)
                httpx.post(url, json={"chat_id": chat_id, "text": clean_text}, timeout=10)
        except Exception:
            pass

    _get_push_executor().submit(_send)


def push_alert(alert_desc: str) -> None:
    """Push an alert trigger notification."""
    send_push(f"🔔 <b>ALERT TRIGGERED</b>\n\n{alert_desc}")


def push_brief(brief_text: str) -> None:
    """Push a morning brief."""
    send_push(f"🇮🇳 <b>Morning Brief</b>\n\n{brief_text}")


def format_execution_alert_message(d: dict) -> str:
    """
    Format a rich, actionable Execution Readiness notification for Telegram using valid HTML formatting.
    Includes exact Entry, Stop Loss, Targets, Risk:Reward, Expected Timelines, Profit Booking Playbook,
    and clean quick-execute commands.
    """
    symbol = d.get("symbol", "UNKNOWN")
    sector = d.get("sector", "General")
    sector_icon = d.get("sector_icon", "🏢")
    ltp = float(d.get("ltp", 0.0))
    status = d.get("execution_status", "STALK")
    strat_score = int(d.get("strategic_score", d.get("conviction_score", 0)))
    tact_score = int(d.get("tactical_score", 80))
    entry = float(d.get("entry_price", ltp))
    sl = float(d.get("stop_loss", ltp * 0.97))
    t1 = float(d.get("target_1", ltp * 1.05))
    t2 = float(d.get("target_2", ltp * 1.08))
    rr = float(d.get("risk_reward_ratio", 2.0))
    setup_title = d.get("setup_title", "Institutional Setup")
    rvol = float(d.get("rvol", d.get("rvol_20d", 1.5)))
    oi_regime = d.get("options_oi_regime", "LONG_BUILDUP")
    catalysts = d.get("catalysts", [])
    if not catalysts and d.get("catalyst_summary"):
        catalysts = [c.strip() for c in d.get("catalyst_summary", "").split("·") if c.strip()]

    timeline = d.get("expected_timeline", "3–10 Trading Days (Swing Momentum)")
    t1_time = d.get("target_1_timeline", "2–5 Trading Days")
    t2_time = d.get("target_2_timeline", "6–10 Trading Days")
    time_stop = d.get("time_stop_days", 10)

    risk_pct = abs((entry - sl) / entry * 100) if entry else 0.0
    t1_pct = abs((t1 - entry) / entry * 100) if entry else 0.0
    t2_pct = abs((t2 - entry) / entry * 100) if entry else 0.0

    status_badge = (
        "🚀 <b>READY TO EXECUTE</b>" if status == "READY" else "🎯 <b>STALK ON RETEST</b>"
    )
    cat_text = (
        "\n".join([f"• {c}" for c in catalysts[:3]])
        if catalysts
        else "• Confirmed Institutional Structure"
    )

    # Breakeven price with +0.2% cost buffer
    be_price = entry * 1.002

    msg = (
        f"{status_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{symbol}</b> ({sector_icon} {sector}) · <b>₹{ltp:,.2f}</b>\n"
        f"<i>{setup_title}</i>\n\n"
        f"📊 <b>Scores:</b> Strategic: <b>{strat_score}/100</b> | Live Tactical: <b>{tact_score}/100</b>\n"
        f"⚡ <b>RVOL:</b> {rvol:.1f}x | <b>OI Flow:</b> {oi_regime}\n\n"
        f"🎯 <b>Actionable Blueprint:</b>\n"
        f"• <b>Entry Zone:</b> <code>₹{entry:,.2f}</code>\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code> (-{risk_pct:.1f}%)\n"
        f"• <b>Target 1 (2R):</b> <code>₹{t1:,.2f}</code> (+{t1_pct:.1f}%)\n"
        f"• <b>Target 2 (3.5R):</b> <code>₹{t2:,.2f}</code> (+{t2_pct:.1f}%)\n"
        f"• <b>Risk : Reward:</b> <b>1:{rr:.1f} R:R</b>\n\n"
        f"⏳ <b>Expected Timeline & Horizon:</b>\n"
        f"• <b>Holding Horizon:</b> <b>{timeline}</b>\n"
        f"• <b>Target 1 Window:</b> Expected within <b>{t1_time}</b>\n"
        f"• <b>Target 2 Window:</b> Expected within <b>{t2_time}</b>\n"
        f"• <b>Time Stop Invalidation:</b> Exit if no expansion after <b>{time_stop} sessions</b>\n\n"
        f"📋 <b>Profit-Booking & Trade Playbook:</b>\n"
        f"1️⃣ <b>At Target 1 (₹{t1:,.2f}):</b> <b>Scale out 50% profit</b> & move Stop Loss to <b>Breakeven</b> (<code>₹{be_price:,.2f}</code>) for a 100% risk-free trade.\n"
        f"2️⃣ <b>Target 2 Trailing:</b> Trail remaining 50% position using <b>Daily 20-EMA / 3.0×ATR</b> trailing stop.\n"
        f"3️⃣ <b>Hard Invalidation:</b> Exit entire position if daily candle closes below <code>₹{sl:,.2f}</code>.\n\n"
        f"💡 <b>Live Catalysts:</b>\n"
        f"{cat_text}\n\n"
        f"⚡ <b>Quick Size / Place Order:</b>\n"
        f"<code>/size {symbol} {entry:.2f} {sl:.2f}</code>"
    )
    return msg


def push_execution_alert(report_dict: dict) -> None:
    """Push rich Execution Readiness notification to Telegram."""
    try:
        msg = format_execution_alert_message(report_dict)
        send_push(msg, parse_mode="HTML")
    except Exception:
        pass


def format_blast_alert(
    d: dict,
    underlying: str = "NIFTY",
    spot: float = 0.0,
    conviction_score: dict | None = None,
) -> str:
    """
    Format a high-conviction Gamma Blast / Order Book Squeeze alert for Telegram.
    Provides clear, institutional, profit-focused actionable levels and playbook.
    Optionally includes a 10-Factor Conviction Score badge.
    """
    contract = d.get("contract", f"{underlying} OPTION")
    opt_type = d.get("option_type", "CE")
    score = d.get("score", 85)
    reason = d.get("blast_reason", d.get("reason", "Heavy institutional order flow imbalance"))
    vol_oi = float(d.get("vol_oi_ratio", 2.5))
    oi_chg = int(d.get("oi_change", 0))
    imb = float(d.get("imbalance_ratio", 2.0))

    action_title = d.get("action_title", f"BUY {contract}")
    prem = float(d.get("premium", d.get("entry_price", d.get("ask", 0.0))) or 50.0)
    entry_low = d.get("entry_low") or round(max(0.5, prem * 0.95), 2)
    entry_high = d.get("entry_high") or round(prem * 1.03, 2)
    entry_range = d.get("entry_range") or f"₹{entry_low:,.2f} – ₹{entry_high:,.2f}"
    sl = float(d.get("stop_loss", prem * 0.75))
    sl_pct = str(d.get("stop_loss_pct", "-25.0%"))
    t1 = float(d.get("target_1", prem * 1.35))
    t1_pct = str(d.get("target_1_pct", "+35.0%"))
    t2 = float(d.get("target_2", prem * 1.65))
    t2_pct = str(d.get("target_2_pct", "+65.0%"))
    rr = str(d.get("risk_reward", "1:2.5"))

    when_buy = d.get("when_to_buy", f"Enter on Ask/Retest ({entry_range}) while momentum holds")
    when_wait = d.get(
        "when_to_wait",
        f"DO NOT CHASE if premium is above ₹{round(prem * 1.15, 1):,}. Wait for pullback",
    )
    when_hold = d.get("when_to_hold", "Hold while price respects 5-EMA and structure advances")
    profit_rule = d.get(
        "profit_rule", f"Book 50% profit at T1 (₹{t1:,.2f}), trail SL to Cost for T2"
    )

    is_call = opt_type == "CE"
    flame = "🔥" if is_call else "🚨"
    icon = "📈" if is_call else "📉"

    # ── Conviction Score badge (optional) ──────────────────────────
    conviction_block = ""
    if conviction_score and isinstance(conviction_score, dict):
        cs_total = conviction_score.get("total_score", 0)
        cs_verdict = conviction_score.get("verdict", "WAIT")
        cs_bullish = conviction_score.get("bullish_count", 0)
        cs_bearish = conviction_score.get("bearish_count", 0)
        cs_pos_size = conviction_score.get("recommended_position_size", "FLAT")

        verdict_icon = {
            "MAX_CONVICTION": "🔥",
            "HIGH": "✅",
            "MODERATE": "⚠️",
            "WAIT": "🛑",
        }.get(cs_verdict, "⚠️")

        pos_size_label = {
            "2X": "⚡ 2× Size",
            "NORMAL": "✓ Normal Size",
            "HALF": "½ Size",
            "FLAT": "No Trade",
        }.get(cs_pos_size, cs_pos_size)

        conviction_block = (
            f"\n🧠 <b>Conviction Score: {cs_total}/100</b> {verdict_icon} {cs_verdict}\n"
            f"• <b>Signal Factors:</b> {cs_bullish}▲ Bullish · {cs_bearish}▼ Bearish\n"
            f"• <b>Position Size:</b> {pos_size_label}\n"
        )

    msg = (
        f"{flame} <b>CHANAKYA BLAST SURGE ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{contract}</b> · {icon} <b>Score: {score}/100</b>\n"
        f"<i>{reason}</i>\n\n"
        f"📊 <b>Institutional Order Flow:</b>\n"
        f"• <b>Vol/OI Turnover:</b> <b>{vol_oi:.1f}x</b>\n"
        f"• <b>OI Liquidation/Shift:</b> <b>{oi_chg:+,} contracts</b>\n"
        f"• <b>Buyer/Seller Queue Imbalance:</b> <b>{imb:.1f}x Buyers</b>\n"
        f"• <b>Underlying Spot:</b> <b>₹{spot:,.2f}</b>\n"
        f"{conviction_block}\n"
        f"🎯 <b>Actionable Profit Blueprint:</b>\n"
        f"• <b>Action:</b> <b>{action_title}</b>\n"
        f"• <b>Entry Zone:</b> <code>{entry_range}</code> (Ref: ₹{prem:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code> ({sl_pct})\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{t1:,.2f}</code> ({t1_pct}) — <i>Scale 50% & SL to Cost</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{t2:,.2f}</code> ({t2_pct}) — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{rr} R:R</b>\n\n"
        f"💡 <b>Trader Execution Playbook:</b>\n"
        f"1️⃣ <b>When to Buy:</b> {when_buy}\n"
        f"2️⃣ <b>When to Wait (No Chase):</b> {when_wait}\n"
        f"3️⃣ <b>When to Hold:</b> {when_hold}\n"
        f"4️⃣ <b>Profit Rule:</b> {profit_rule}\n\n"
        f"⚡ <i>Chanakya Institutional Gamma Desk</i>"
    )
    return msg


def send_blast_push(
    blast_data: dict,
    underlying: str = "NIFTY",
    spot: float = 0.0,
    conviction_score: dict | None = None,
) -> bool:
    """
    Send an actionable Blast alert notification to Telegram.
    If conviction_score is not provided, computes a live score automatically.
    """
    try:
        # Compute live conviction score if not provided
        if conviction_score is None:
            try:
                from engine.conviction_score import get_conviction_score

                cs = get_conviction_score(
                    underlying=underlying,
                    spot=spot,
                    blast_score=blast_data.get("score"),
                    vol_oi_ratio=blast_data.get("vol_oi_ratio"),
                    imbalance_ratio=blast_data.get("imbalance_ratio"),
                )
                conviction_score = cs.as_dict()
            except Exception:
                conviction_score = None

        msg = format_blast_alert(blast_data, underlying, spot, conviction_score)
        send_push(msg, parse_mode="HTML", bypass_dedup=True)
        return True
    except Exception as e:
        logger.warning(f"Failed to send blast push to Telegram: {e}")
        return False


def format_precursor_alert(candidate_dict: dict) -> str:
    """Format a high-conviction Precursor Radar alert for Telegram push."""
    sym = candidate_dict.get("symbol", "STOCK")
    seg = candidate_dict.get("segment", "FNO")
    score = candidate_dict.get("conviction_score", 80)
    verdict = candidate_dict.get("verdict", "HIGH_CONVICTION")
    ltp = candidate_dict.get("ltp", 0.0)
    entry_range = candidate_dict.get("entry_range", f"₹{ltp:,.1f}")
    sl = candidate_dict.get("stop_loss", 0.0)
    t1 = candidate_dict.get("target_1", 0.0)
    t2 = candidate_dict.get("target_2", 0.0)
    rr = candidate_dict.get("risk_reward", "1:2.5")
    when_buy = candidate_dict.get("when_to_buy", "Enter on ask within coiling range with VWAP hold.")
    when_wait = candidate_dict.get("when_to_wait", "DO NOT CHASE if price gaps > 1.8%.")
    profit_rule = candidate_dict.get("profit_rule", "Book 50% at T1, trail runner to T2.")
    factors = candidate_dict.get("matched_factors", ["Pre-ignition volume dry-up & squeeze coiling"])
    factors_str = "\n• ".join(factors[:3]) if factors else "• Pre-ignition coiling setup"

    icon = "🔥" if score >= 85 else "⚡"
    msg = (
        f"{icon} <b>CHANAKYA HIGH-CONVICTION PRECURSOR RADAR [{seg}]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{sym} [{seg}]</b> · 🧠 <b>Score: {score}/100</b> ({verdict})\n\n"
        f"📊 <b>Matched Precursor DNA:</b>\n"
        f"• {factors_str}\n\n"
        f"🎯 <b>Actionable Profit Blueprint:</b>\n"
        f"• <b>Entry Zone:</b> <code>{entry_range}</code> (Ref: ₹{ltp:,.2f})\n"
        f"• <b>Invalidation SL:</b> <code>₹{sl:,.2f}</code>\n"
        f"• <b>Target 1 (1.5R):</b> <code>₹{t1:,.2f}</code> — <i>Scale 50% & SL to Cost</i>\n"
        f"• <b>Target 2 (2.5R):</b> <code>₹{t2:,.2f}</code> — <i>Full Extension</i>\n"
        f"• <b>Risk : Reward:</b> <b>{rr}</b>\n\n"
        f"💡 <b>Trader Execution Playbook:</b>\n"
        f"1️⃣ <b>When to Buy:</b> {when_buy}\n"
        f"2️⃣ <b>When to Wait:</b> {when_wait}\n"
        f"3️⃣ <b>Profit Rule:</b> {profit_rule}\n\n"
        f"⚡ <i>Chanakya Institutional Momentum Intelligence</i>"
    )
    return msg


def send_precursor_push(candidate_dict: dict) -> bool:
    """Send an actionable Precursor Radar alert notification to Telegram."""
    try:
        msg = format_precursor_alert(candidate_dict)
        send_push(msg, parse_mode="HTML", bypass_dedup=True)
        return True
    except Exception as e:
        logger.warning(f"Failed to send precursor push to Telegram: {e}")
        return False


# ── Alert Integration ────────────────────────────────────────


def patch_alert_manager() -> None:
    """
    Monkey-patch AlertManager._notify to also send Telegram push.
    Call this when the bot starts.
    """
    try:
        from engine.alerts import alert_manager

        original_notify = alert_manager._notify

        def _patched_notify(alert):
            original_notify(alert)
            push_alert(alert.describe())

        alert_manager._notify = _patched_notify
        logger.debug("Alert manager patched for Telegram push notifications")
    except Exception:
        pass


# ── Bot Runner ───────────────────────────────────────────────


def run_bot() -> None:
    """Start the Telegram bot (blocking — runs the event loop)."""
    Update, Bot, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters = (
        _get_telegram()
    )

    token = _get_bot_token()

    app = ApplicationBuilder().token(token).build()

    # Register command handlers (wrapped with _track_command for REPL badge)
    app.add_handler(CommandHandler("start", _track_command(cmd_start)))
    app.add_handler(CommandHandler("help", _track_command(cmd_help)))
    app.add_handler(CommandHandler("quote", _track_command(cmd_quote)))
    app.add_handler(CommandHandler("analyze", _track_command(cmd_analyze)))
    app.add_handler(CommandHandler("deepanalyze", _track_command(cmd_deepanalyze)))
    app.add_handler(CommandHandler("brief", _track_command(cmd_brief)))
    app.add_handler(CommandHandler("conviction", _track_command(cmd_conviction)))
    app.add_handler(CommandHandler("movers", _track_command(cmd_movers)))
    app.add_handler(CommandHandler("precursors", _track_command(cmd_precursors)))
    app.add_handler(CommandHandler("scan", _track_command(cmd_scan)))
    app.add_handler(CommandHandler("radar", _track_command(cmd_scan)))
    app.add_handler(CommandHandler("flows", _track_command(cmd_flows)))
    app.add_handler(CommandHandler("earnings", _track_command(cmd_earnings)))
    app.add_handler(CommandHandler("events", _track_command(cmd_events)))
    app.add_handler(CommandHandler("macro", _track_command(cmd_macro)))
    app.add_handler(CommandHandler("alert", _track_command(cmd_alert)))
    app.add_handler(CommandHandler("alerts", _track_command(cmd_alerts)))
    app.add_handler(CommandHandler("memory", _track_command(cmd_memory)))
    app.add_handler(CommandHandler("pnl", _track_command(cmd_pnl)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _track_command(cmd_unknown)))

    # Patch alerts for push notifications
    patch_alert_manager()

    logger.debug("Telegram bot starting...")

    # ── Silence ALL output from this thread ──────────────────────────────
    # 1. Logging filter: blocks log records (httpx, websocket, LLM API, etc.)
    _thread_filter = _BotThreadFilter()
    for _handler in logging.root.handlers:
        _handler.addFilter(_thread_filter)

    # Also silence any logger that adds its own handlers (e.g. FyersDataSocket)
    logging.getLogger("FyersDataSocket").setLevel(logging.CRITICAL)

    # 2. Stdout wrapper: blocks plain print() calls from this thread.
    import sys

    if not isinstance(sys.stdout, _BotThreadFileWrapper):
        sys.stdout = _BotThreadFileWrapper(sys.stdout)

    # 3. Rich Console patch: Rich stores a direct reference to sys.stdout at
    #    Console() creation time, so replacing sys.stdout is not enough.
    #    Walk every live Console instance and wrap its _file attribute too.
    try:
        import gc
        from rich.console import Console as _RichConsole

        for _obj in gc.get_objects():
            if isinstance(_obj, _RichConsole):
                if _obj._file is not None and not getattr(_obj._file, "_bot_patched", False):
                    _obj._file = _BotThreadFileWrapper(_obj._file)
    except Exception:
        pass

    # run_polling() registers OS signal handlers which only work on the main
    # thread. Use the lower-level async API instead — no signal handlers at all.
    async def _run() -> None:
        async with app:
            await app.start()
            await app.updater.start_polling()
            # Keep running until the daemon thread is killed on process exit
            while True:
                await asyncio.sleep(3600)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception:
        pass
    finally:
        loop.close()


def run_bot_background() -> threading.Thread:
    """Start the bot in a background thread (non-blocking, for REPL integration).
    If the bot is already running, returns the existing thread without starting a new one.
    """
    global _bot_thread
    if _bot_thread is not None and _bot_thread.is_alive():
        logger.debug("Bot thread already running — skipping duplicate start.")
        return _bot_thread
    _bot_thread = threading.Thread(target=run_bot, daemon=True, name="telegram-bot")
    _bot_thread.start()
    return _bot_thread


# ── CLI entry point ──────────────────────────────────────────

if __name__ == "__main__":
    run_bot()
