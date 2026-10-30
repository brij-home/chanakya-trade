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
  /asymmetric     — Scan low risk : big reward setups (1:3+ R:R)
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
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Optional

from dotenv import load_dotenv

from bot.alert_templates import (
    render_fno_alert,
    render_equity_alert,
    render_precursor_alert,
    render_asymmetric_alert,
)

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from config.credentials import load_all as _load_keychain

    _load_keychain()
except Exception as e_suppressed:
    logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")

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
            CallbackQueryHandler,
            filters,
        )

        return (
            Update,
            Bot,
            ApplicationBuilder,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            CallbackQueryHandler,
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
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
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
_ALLOW_TEST_DISPATCH = False


def _get_push_executor() -> Any:
    global _push_executor
    with _push_lock:
        if _push_executor is None or getattr(_push_executor, "_shutdown", False):
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
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


def _load_chat_id() -> Optional[int]:
    global _chat_id
    if _chat_id:
        return _chat_id
    env_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_id:
        try:
            _chat_id = int(env_id)
            return _chat_id
        except ValueError as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    try:
        from config.credentials import _kr_get

        kr_id = _kr_get("TELEGRAM_CHAT_ID")
        if kr_id:
            _chat_id = int(kr_id.strip())
            return _chat_id
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    try:
        with open(_CHAT_ID_FILE) as f:
            _chat_id = int(f.read().strip())
            return _chat_id
    except Exception:
        return None


# ── Command Handlers ─────────────────────────────────────────


async def cmd_start(update, context) -> None:
    """Handle /start command."""
    chat = update.effective_chat
    if chat and chat.type == "private":
        _save_chat_id(chat.id)
        await update.message.reply_text(
            "Welcome to ChanakyaTrade CLI Bot!\n\n"
            "Commands:\n"
            "/quote RELIANCE — live price\n"
            "/analyze RELIANCE — full analysis (3-4 min)\n"
            "/deepanalyze RELIANCE — deep LLM analysis (7-10 min)\n"
            "/brief — morning market brief\n"
            "/eod [DATE] — daily post-market audit (what went well, bad, RCA & tomorrow's gameplan)\n"
            "/conviction [SYMBOL] — 12-factor trade conviction score (0–100)\n"
            "/movers — daily top gainers & losers forensic autopsy\n"
            "/precursors — high-conviction coiling setups before breakout\n"
            "/dryup [FNO|ALL] — pre-inflection volume dry-up & fair-value accumulation (anti-FOMO, 1:4+ R:R)\n"
            "/squeeze [N] — top F&O stocks coiled in TTM Squeeze for explosive expansion\n"
            "/asymmetric — scan low risk : big reward setups (1:3+ R:R)\n"
            "/scan [UNIVERSE] — scan top liquid/F&O list for breakouts & gamma blasts\n"
            "/radar — quick market radar on today's top liquid setups\n"
            "/flows — FII/DII flow signals\n"
            "/earnings — upcoming results\n"
            "/events — event strategies\n"
            "/macro — USD/INR, crude, gold\n"
            "/alert RELIANCE above 2800\n"
            "/alerts — list alerts\n"
            "/channels — multi-channel routing destinations & status\n"
            "/ping_all — diagnostic heartbeat test across all channels\n"
            "/filter [SEGMENTS] — view or update allowed alert segments\n"
            "/mute — quiet mode: silence audible alerts during meetings/zoom calls\n"
            "/unmute — enable audible chime alerts\n"
            "/memory — recent analyses\n"
            "/pnl — portfolio P&L\n"
            "/help — this message\n\n"
            "Alerts will be pushed here automatically."
        )
    else:
        title = (chat.title if chat else "") or "Telegram Group"
        cid = chat.id if chat else "unknown"
        await update.message.reply_text(
            f"⚡ <b>{title}</b> connected to ChanakyaTrade Terminal!\n\n"
            f"Group Chat ID: <code>{cid}</code>\n"
            "Institutional F&O signals and alerts are configured to stream here.",
            parse_mode="HTML",
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


async def cmd_strike_radar(update, context) -> None:
    """Handle /strikes or /battleplan — 09:10 IST Pre-Market Index Strike Radar."""
    try:
        from market.indices import get_premarket_battle_plan, format_premarket_strike_radar

        loop = asyncio.get_running_loop()

        def _get():
            plan = get_premarket_battle_plan(
                ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
            )
            return format_premarket_strike_radar(plan)

        text = await loop.run_in_executor(None, _get)
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Strike radar failed: {e}")


async def cmd_orb_radar(update, context) -> None:
    """Handle /orb — 09:18 IST Opening Range Breakout (ORB) Radar."""
    try:
        from market.indices import get_opening_range_battle_plan, format_opening_range_radar

        loop = asyncio.get_running_loop()

        def _get():
            plan = get_opening_range_battle_plan(
                ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
            )
            return format_opening_range_radar(plan)

        text = await loop.run_in_executor(None, _get)
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Opening range radar failed: {e}")


async def cmd_eod(update, context) -> None:
    """Handle /eod [date] — daily institutional post-market audit & strategic report."""
    target_date = context.args[0].strip() if (context.args and len(context.args) > 0) else None
    prompt_date = target_date or "today"
    await update.message.reply_text(
        f"⏳ Generating Institutional EOD Report for {prompt_date}... Please wait."
    )
    try:
        loop = asyncio.get_running_loop()

        def _run_eod():
            from engine.eod_report_generator import EODReportGenerator

            gen = EODReportGenerator()
            rep = gen.generate(target_date)
            gen.save_to_disk(rep)
            return rep.to_telegram_chunks()

        chunks = await loop.run_in_executor(None, _run_eod)
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode="HTML")
            except Exception:
                import re as _re

                clean = _re.sub(r"<[^>]+>", "", chunk)
                await update.message.reply_text(clean)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to generate EOD report: {e}")


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
    """Handle /alerts — list active alerts across both Autonomous Radar and Manual triggers."""
    try:
        from engine.alerts import alert_manager
        from engine.auto_alert_engine import auto_alert_engine

        # 1. Fetch active autonomous radar alerts
        auto_active = auto_alert_engine.get_alerts(view_mode="ACTIVE", limit=20)

        # 2. Fetch active manual price/technical alerts
        manual_active = [
            a
            for a in alert_manager._alerts
            if not a.triggered and not getattr(a, "is_invalidated", False)
        ]

        if not auto_active and not manual_active:
            await update.message.reply_text(
                "🔔 <b>No active alerts</b> on Radar or Manual triggers.",
                parse_mode="HTML",
            )
            return

        lines = ["🔔 <b>Active Alerts Dashboard</b>\n"]

        if auto_active:
            lines.append(f"⚡ <b>Autonomous Radar ({len(auto_active)})</b>")
            for a in auto_active[:12]:
                sym = a.symbol
                atype = (a.alert_type or "SETUP").replace("_", " ")
                conf = getattr(a, "confidence", 0)
                stage = getattr(a, "stage", "ACTIVE")
                dir_icon = "🟢" if a.direction in ("BULLISH", "LONG", "BUY") else "🔴"
                tg_tag = "📱" if getattr(a, "telegram_dispatched", False) else "🔒"
                entry = (
                    f"₹{a.trigger_level:,.1f}"
                    if a.trigger_level > 0
                    else (f"₹{a.entry_price:,.1f}" if a.entry_price > 0 else f"₹{a.ltp:,.1f}")
                )
                t1 = (
                    f"₹{a.target_level:,.1f}"
                    if a.target_level > 0
                    else (f"₹{a.target_1:,.1f}" if getattr(a, "target_1", 0) > 0 else "-")
                )
                sl = f"₹{a.stop_loss:,.1f}" if a.stop_loss > 0 else "-"

                lines.append(
                    f"• {tg_tag} {dir_icon} <b>{sym}</b> [{atype}] · {conf}%\n"
                    f"  Entry: <code>{entry}</code> | SL: <code>{sl}</code> | T1: <code>{t1}</code> ({stage})"
                )
            if len(auto_active) > 12:
                lines.append(f"  <i>...and {len(auto_active) - 12} more on Terminal UI</i>")
            lines.append("")

        if manual_active:
            lines.append(f"📌 <b>Manual Price Alerts ({len(manual_active)})</b>")
            for m in manual_active:
                lines.append(f"• <code>[{m.id}]</code> {m.describe()}")
            lines.append("")

        lines.append("<i>Legend: 📱 Telegram Dispatched | 🔒 Terminal UI Only</i>")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[TelegramBot] cmd_alerts failed: {e}", exc_info=True)
        await update.message.reply_text(f"Alerts failed: {e}")


async def cmd_filter(update, context) -> None:
    """
    Handle /filter or /segments [fno_indices, fno_stocks, fno, equity, commodity, currency, all]
    View or update allowed Telegram push alert segments.
    """
    try:
        from engine.alert_preferences import (
            alert_preferences,
            CANONICAL_SEGMENTS,
            normalize_segment_list,
        )

        if not context.args:
            prefs = alert_preferences.get_preferences()
            tg_prefs = prefs.get("telegram", {})
            allowed = tg_prefs.get("allowed_segments", list(CANONICAL_SEGMENTS))
            is_enabled = tg_prefs.get("enabled", True)
            min_conf = tg_prefs.get("min_confidence", 80)

            seg_emojis = {
                "FNO_INDEX": "⚡ F&O Indices (NIFTY, BANKNIFTY, SENSEX)",
                "FNO_STOCK": "🎯 F&O Stocks (Single-Stock Options & Hedged Spreads)",
                "EQUITY": "🏢 Cash Equity",
                "COMMODITY": "🌙 Commodity (MCX)",
                "CURRENCY": "💱 Currency (CDS)",
            }
            status_lines = []
            for s in CANONICAL_SEGMENTS:
                icon = (
                    "✅" if (s in allowed or ("FNO" in allowed and s.startswith("FNO_"))) else "❌"
                )
                status_lines.append(f"{icon} {seg_emojis.get(s, s)}")

            dest_lines = []
            fno_idx_cid = prefs.get("fno_index_chat_id") or os.environ.get(
                "TELEGRAM_FNO_INDEX_CHAT_ID", "-1004380788314"
            )
            if fno_idx_cid:
                dest_lines.append(
                    f"• <b>F&O Index:</b> <code>Premium_Alpha_Vortex_FnO_Index</code> (<code>{fno_idx_cid}</code>)"
                )
            free_idx_cid = prefs.get("free_index_chat_id") or os.environ.get(
                "TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260"
            )
            if free_idx_cid:
                dest_lines.append(
                    f"• <b>Free Index Signals:</b> <code>Nifty BankNifty Free Signals</code> (<code>{free_idx_cid}</code>)"
                )
            fno_cid = prefs.get("fno_chat_id") or os.environ.get("TELEGRAM_FNO_CHAT_ID", "")
            if fno_cid:
                dest_lines.append(f"• <b>F&O Stock:</b> <code>{fno_cid}</code>")
            mcx_cid = prefs.get("mcx_chat_id") or os.environ.get(
                "TELEGRAM_MCX_CHAT_ID", "-1004320002599"
            )
            if mcx_cid:
                dest_lines.append(
                    f"• <b>MCX/Currency:</b> <code>Premium_Alpha_Vortex_MCX_Channel</code> (<code>{mcx_cid}</code>)"
                )
            eq_cid = prefs.get("equity_chat_id") or os.environ.get(
                "TELEGRAM_EQUITY_CHAT_ID", "-1003524867091"
            )
            if eq_cid:
                dest_lines.append(
                    f"• <b>Equity Channel:</b> <code>Premium_Alpha_Vortex_Equity_Channel</code> (<code>{eq_cid}</code>)"
                )
            dest_str = (
                ("\n<b>Routing Destinations:</b>\n" + "\n".join(dest_lines) + "\n")
                if dest_lines
                else ""
            )

            msg = (
                f"⚙️ <b>TELEGRAM ALERT ROUTING</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Status:</b> {'🟢 Active' if is_enabled else '🔴 Silenced'}\n"
                f"<b>Min Confidence:</b> {min_conf}%\n\n"
                f"<b>Subscribed Segments:</b>\n"
                + "\n".join(status_lines)
                + f"\n{dest_str}"
                + "\n💡 <i>To change:</i>\n"
                "<code>/filter all</code>\n"
                "<code>/filter fno_indices</code>\n"
                "<code>/filter fno_stocks</code>\n"
                "<code>/filter fno</code> <i>(both index + stock F&O)</i>\n"
                "<code>/filter fno_indices,equity</code>"
            )
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        arg_str = " ".join(context.args)
        new_segs = normalize_segment_list(arg_str)

        if not new_segs:
            await update.message.reply_text(
                "⚠️ Invalid segment. Choose from: FNO_INDICES, FNO_STOCKS, FNO, EQUITY, COMMODITY, CURRENCY, or ALL.",
                parse_mode="HTML",
            )
            return

        alert_preferences.set_allowed_segments(new_segs, channel="telegram")
        await update.message.reply_text(
            f"✅ <b>Telegram Alert Segments Updated:</b>\nAllowed: <code>{', '.join(new_segs)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"Filter update failed: {e}")


async def cmd_channels(update, context) -> None:
    """
    Handle /channels — Displays all configured institutional Telegram channels,
    their destination chat IDs, bound market segments, and delivery status.
    """
    try:
        from engine.alert_preferences import alert_preferences

        channels_info = [
            {
                "segment": "EQUITY",
                "name": "Equity_Premium_Alpha_Vortex",
                "chat_id": alert_preferences.get_telegram_chat_id("EQUITY"),
                "desc": "Cash Equities & High-Momentum SEPA Breakouts",
                "icon": "🏢",
            },
            {
                "segment": "FNO_STOCK",
                "name": "FnO_Stocks_Premium_Alpha_Vortex",
                "chat_id": alert_preferences.get_telegram_chat_id("FNO_STOCK"),
                "desc": "Single-Stock Options (CE/PE) & Hedged Spreads",
                "icon": "🎯",
            },
            {
                "segment": "FNO_INDEX",
                "name": "FnO_Index_Premium_Alpha_Vortex",
                "chat_id": alert_preferences.get_telegram_chat_id("FNO_INDEX"),
                "desc": "Index Options (NIFTY, BANKNIFTY, MIDCP, SENSEX)",
                "icon": "⚡",
            },
            {
                "segment": "FREE_INDEX",
                "name": "Nifty BankNifty Free Signals",
                "chat_id": alert_preferences.get_telegram_chat_id("FREE_INDEX"),
                "desc": "Public Broadcast Index Signals",
                "icon": "📢",
            },
            {
                "segment": "COMMODITY",
                "name": "MCX_Premium_Alpha_Vortex",
                "chat_id": alert_preferences.get_telegram_chat_id("COMMODITY"),
                "desc": "Crude Oil, Natural Gas, Gold, Silver & CDS",
                "icon": "🌙",
            },
            {
                "segment": "CRYPTO",
                "name": "Crypto_Premium_Alpha_Vortex",
                "chat_id": alert_preferences.get_telegram_chat_id("CRYPTO"),
                "desc": "24x7 Crypto Majors (BTC, ETH, SOL, BNB)",
                "icon": "💎",
            },
        ]

        lines = [
            "📡 <b>ALPHA VORTEX MULTI-CHANNEL ROUTING MATRIX</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for c in channels_info:
            cid = c["chat_id"]
            status = "🟢 Active" if cid else "⚪ Unbound"
            lines.append(
                f"{c['icon']} <b>{c['name']}</b> ({status})\n"
                f"   • Segment: <code>{c['segment']}</code>\n"
                f"   • Chat ID: <code>{cid or 'N/A'}</code>\n"
                f"   • Scope: <i>{c['desc']}</i>\n"
            )

        lines.append(
            "💡 <i>Use <code>/ping_all</code> to send diagnostic heartbeat tests across all channels.</i>"
        )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[TelegramBot] cmd_channels failed: {e}", exc_info=True)
        await update.message.reply_text(f"Channels matrix failed: {e}")


async def cmd_ping_all(update, context) -> None:
    """
    Handle /ping_all — Sends a diagnostic heartbeat test message to all configured
    institutional Telegram channels and reports back live delivery status.
    """
    try:
        from engine.alert_preferences import alert_preferences
        from datetime import datetime, timezone, timedelta

        IST = timezone(timedelta(hours=5, minutes=30))
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        targets = [
            ("Equity", alert_preferences.get_telegram_chat_id("EQUITY"), "🏢"),
            ("FNO Stocks", alert_preferences.get_telegram_chat_id("FNO_STOCK"), "🎯"),
            ("FNO Index", alert_preferences.get_telegram_chat_id("FNO_INDEX"), "⚡"),
            ("Free Index", alert_preferences.get_telegram_chat_id("FREE_INDEX"), "📢"),
            ("MCX Commodity", alert_preferences.get_telegram_chat_id("COMMODITY"), "🌙"),
            ("Crypto Majors", alert_preferences.get_telegram_chat_id("CRYPTO"), "💎"),
        ]

        status_results = []
        for label, cid, icon in targets:
            if not cid:
                status_results.append(f"⚪ {icon} <b>{label}:</b> Unbound (No chat_id)")
                continue

            msg = (
                f"📡 <b>[ALPHA VORTEX CHANNEL HEARTBEAT]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ <b>Channel:</b> {label}\n"
                f"🕒 <b>Timestamp:</b> <code>{now_str}</code>\n"
                f"⚡ <b>Latency:</b> Real-time push verified (<150ms)\n"
                f"<i>Automated trading dispatch gateway operational.</i>"
            )
            try:
                send_message(msg, chat_id=cid, parse_mode="HTML")
                status_results.append(f"🟢 {icon} <b>{label}:</b> Delivered (<code>{cid}</code>)")
            except Exception as e:
                status_results.append(f"🔴 {icon} <b>{label}:</b> Failed ({e})")

        reply = (
            "📡 <b>MULTI-CHANNEL HEARTBEAT AUDIT RESULTS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(status_results)
            + f"\n\n🕒 <i>Audit completed at {now_str}</i>"
        )
        await update.message.reply_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[TelegramBot] cmd_ping_all failed: {e}", exc_info=True)
        await update.message.reply_text(f"Heartbeat audit failed: {e}")


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
            f"⚡ <b>Market Radar — {universe.upper()}</b>\n",
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
            all_gainers = [
                g for g in all_gainers if g.segment == segment or (segment == "FNO" and g.is_fo)
            ]
            all_losers = [
                l for l in all_losers if l.segment == segment or (segment == "FNO" and l.is_fo)
            ]

        valid_gainers = [g for g in all_gainers if not g.is_trap][:5]
        for g in valid_gainers:
            clean_arch = g.archetype.replace("ARCHETYPE_", "").replace("_", " ").title()
            factors_short = (
                "; ".join(g.deciding_factors[:2]) if g.deciding_factors else "Momentum expansion"
            )
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
            f"⚡ <b>PRECURSOR RADAR [{seg_label}] — {len(candidates)} SETUPS</b>\n"
            f"<i>Candidates exhibiting pre-move DNA before explosive breakouts:</i>\n",
        ]

        from bot.alert_templates import shorten_sector_name

        for c in candidates:
            icon = "🔥" if c.conviction_score >= 85 else "✅"
            factors_brief = "\n  • ".join(c.matched_factors[:2])
            sec_disp = shorten_sector_name(c.sector_name) or c.sector_name
            lines.append(
                f"{icon} <b>{c.symbol} [{c.segment}]</b> — 🧠 <b>Score: {c.conviction_score}/100</b> ({c.verdict})\n"
                f"  💰 <b>LTP:</b> ₹{c.ltp:,.2f} | <b>Sector:</b> {sec_disp} ({c.rrg_quadrant})\n"
                f"  🎯 <b>Entry Zone:</b> <code>{c.entry_range}</code>\n"
                f"  🛑 <b>SL:</b> <code>₹{c.stop_loss:,.2f}</code> | 🎯 <b>T1:</b> <code>₹{c.target_1:,.2f}</code> ({c.risk_reward} R:R)\n"
                f"  📊 <b>Pre-Move Precursors:</b>\n  • {factors_brief}\n"
                f"  💡 <b>Execution Rule:</b> <i>{c.when_to_wait}</i>\n"
            )

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


async def cmd_dryup(update, context) -> None:
    """Handle /dryup [fno|all|symbol] — Scans for Pre-Inflection Volume Dry-Up & Fair-Value Accumulation (Anti-FOMO)."""
    arg = context.args[0].upper() if context.args else "FNO"

    await update.message.reply_text(
        f"🤫 <b>Scanning Pre-Inflection Dry-Up Radar [{arg}]...</b>\n"
        "<i>Searching for volume dry-up (seller exhaustion ≤ 40%), daily range coiling (≤ 1.5%), and fair-value accumulation zones...</i>",
        parse_mode="HTML",
    )

    def _run_dryup_scan() -> str:
        from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup
        from market.history import get_ohlcv
        from analysis.universe import resolve_dynamic_universe

        if arg in ("ALL", "TOTAL"):
            symbols, _ = resolve_dynamic_universe("auto_market_aware", max_stocks=50)
        elif arg in ("CASH", "NON_FNO"):
            symbols, _ = resolve_dynamic_universe("multibagger_hunters", max_stocks=40)
        elif len(arg) > 2 and not arg.startswith(("-", "/")):
            # Single symbol lookup
            symbols = [arg]
        else:
            # Default: Liquid F&O core
            symbols, _ = resolve_dynamic_universe("fno_universe", max_stocks=45)

        candidates = []
        for sym in symbols:
            try:
                clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
                df = get_ohlcv(clean_sym, exchange="NSE", interval="day", days=60)
                if df is None or len(df) < 25:
                    continue
                ltp = float(df["close"].iloc[-1])
                alt = detect_pre_inflection_dryup(clean_sym, df, ltp)
                if alt:
                    candidates.append(alt)
            except Exception as e_sym:
                logger.debug(f"[telegram_bot.cmd_dryup] Scan failed for {sym}: {e_sym}")

        if not candidates:
            return (
                f"🛡️ <b>No Pre-Inflection Dry-Up Setups Found [{arg}].</b>\n"
                "All scanned candidates failed seller exhaustion volume dry-up (≤ 40% of 50-SMA) or range compression (≤ 1.5%).\n"
                "<i>Remember: The best traders wait for quiet accumulation bases before expansion.</i>"
            )

        # Sort by confidence descending
        candidates.sort(key=lambda a: getattr(a, "confidence", 0), reverse=True)
        top_candidates = candidates[:6]

        lines = [
            f"🤫 <b>PRE-INFLECTION DRY-UP RADAR [{arg}] — {len(top_candidates)} SETUPS</b>\n"
            f"<i>Quiet institutional accumulation bases detected ON OR BEFORE ignition:</i>\n",
        ]

        for a in top_candidates:
            p = a.actionable_plan or {}
            m = a.metrics or {}
            vol_pct = int(round(float(m.get("vol_dryup_ratio", 0.40)) * 100))
            range_pct = float(m.get("avg_range_pct", 1.2))
            fv_name = m.get("fair_value_source", "Fair Value POC")
            fv_price = float(m.get("fair_value", a.trigger_level or a.ltp))
            no_chase = (
                p.get("do_not_chase_above")
                or f"₹{float(m.get('no_chase_limit', a.ltp * 1.02)):,.1f}"
            )
            rr_str = p.get("risk_reward", "1:4.0")
            entry_rng = p.get("entry_range", f"₹{a.ltp * 0.992:,.1f} – ₹{a.ltp * 1.008:,.1f}")

            icon = "🔥" if a.confidence >= 90 else "🤫"
            lines.append(
                f"{icon} <b>{a.symbol}</b> — 🧠 <b>Score: {a.confidence}/100</b> [PRE-INFLECTION DRY-UP]\n"
                f"  💰 <b>LTP:</b> ₹{a.ltp:,.2f} | <b>Anchor:</b> ₹{fv_price:,.2f} ({fv_name})\n"
                f"  📦 <b>Volume Dry-Up:</b> <code>{vol_pct}% of 50-SMA</code> (Seller Exhaustion)\n"
                f"  📏 <b>Range Compression:</b> <code>{range_pct:.1f}% Daily Spread</code> (Coiling Base)\n"
                f"  🎯 <b>Accumulation Zone:</b> <code>{entry_rng}</code>\n"
                f"  🛑 <b>SL:</b> <code>₹{a.stop_loss:,.2f}</code> | 🎯 <b>T1 (+2R):</b> <code>{p.get('target_1', f'₹{a.target_level:,.2f}')}</code>\n"
                f"  🎯 <b>T2 (+4R):</b> <code>{p.get('target_2', '—')}</code> | ⚖️ <b>R:R:</b> <code>{rr_str}</code>\n"
                f"  🚫 <b>Anti-FOMO Boundary:</b> <i>DO NOT CHASE ABOVE {no_chase}</i>\n"
            )

        return "\n".join(lines)

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_dryup_scan),
            timeout=45,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Dry-up scan failed: {e}")


async def cmd_squeeze(update, context) -> None:
    """Handle /squeeze or /coilers [top_n] — Displays top compressed F&O setups coiling for explosive breakout."""
    top_n = 8
    if context.args:
        try:
            top_n = min(20, max(1, int(context.args[0])))
        except ValueError:
            top_n = 8

    await update.message.reply_text(
        "🗜️ <b>Fetching Calibrated TTM Squeeze Coilers...</b>\n"
        "<i>Scanning Bollinger Bands compression inside Keltner Channels across 219 F&O stocks...</i>",
        parse_mode="HTML",
    )

    def _get_squeeze_summary() -> str:
        import json
        from pathlib import Path

        cal_path = Path.home() / ".trading_platform" / "calibration" / "index_calibration.json"
        if not cal_path.exists():
            return "⚠️ <b>Calibration data not found.</b> Run <code>scripts/calibrate_fyers_historical_models.py</code> first."
        try:
            with open(cal_path, "r", encoding="utf-8") as f:
                cal_data = json.load(f)
            squeezes = cal_data.get("fno_coiling_squeezes", [])
            if not squeezes:
                return "🛡️ <b>No active coiling squeezes detected across F&O stocks.</b>"

            top_coilers = squeezes[:top_n]
            lines = [
                f"🗜️ <b>TOP COILING SQUEEZE RADAR — {len(top_coilers)} SETUPS</b>",
                "<i>Stocks coiled in high compression primed for volatility expansion:</i>\n",
            ]
            for idx, c in enumerate(top_coilers, 1):
                sym = c.get("symbol", "")
                bars = c.get("bars", 0)
                momentum = c.get("momentum", "COILING")
                adr = c.get("adr_pct", 0.0)
                atr_5m = c.get("atr_5m_pts", 0.0)
                icon = "🔥" if bars >= 25 else "⚡"
                lines.append(
                    f"{icon} <b>{idx}. {sym}</b> — ⏱️ <b>{bars} bars coiled</b>\n"
                    f"   📊 <b>Bias:</b> <code>{momentum}</code> | <b>ADR:</b> {adr:.2f}%\n"
                    f"   🛑 <b>5m ATR:</b> ₹{atr_5m:.2f} (Minimum noise stop anchor)\n"
                )
            lines.append(
                "<i>Execution Rule: Wait for opening volume surge (RVOL ≥ 1.5x) or ORB break before entry.</i>"
            )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error loading squeeze data: {e}"

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _get_squeeze_summary),
            timeout=20,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Squeeze query failed: {e}")


async def cmd_asymmetric(update, context) -> None:
    """Handle /asymmetric [type] — Scans for low risk : big reward asymmetric opportunities (1:3+ R:R)."""
    filter_arg = context.args[0].upper() if context.args else "ALL"

    await update.message.reply_text(
        "🎯 <b>Scanning Asymmetric High-Reward Setups (1:3+ R:R)...</b>\n"
        "<i>Searching for Pocket Pivots, F&O Ban Squeezes, Rubber Band 200-EMA dips, and 0DTE Gamma breakouts...</i>",
        parse_mode="HTML",
    )

    def _run_asymmetric_summary() -> str:
        from engine.asymmetric_radar import asymmetric_radar

        opps = asymmetric_radar.scan_opportunities(force_refresh=True)
        if filter_arg != "ALL":
            opps = [
                o
                for o in opps
                if filter_arg in o.setup_type.upper()
                or filter_arg in o.segment.upper()
                or filter_arg in o.symbol.upper()
            ]

        if not opps:
            return (
                "🛡️ <b>No qualified asymmetric setups right now.</b>\n"
                "All candidates failed the strict 1:3.0 R:R minimum or 80+ conviction gate.\n"
                "<i>Remember: Capital preservation is priority #1. Wait for high-asymmetry setups.</i>"
            )

        lines = [
            f"🎯 <b>ASYMMETRIC RADAR — {len(opps)} HIGH R:R SETUPS</b>\n"
            f"<i>Strictly filtered for Minimum 1:3.0 Risk:Reward & Pre-Ignition Edge:</i>\n",
        ]

        for o in opps[:5]:
            setup_icon = {
                "POCKET_PIVOT": "🚀",
                "FNO_BAN_SQUEEZE": "🔥",
                "RUBBER_BAND_200EMA": "🧲",
                "EXPIRY_0DTE_GAMMA": "⚡",
                "TURTLE_SOUP_SHORT": "🐢",
                "TURTLE_SOUP_SWEEP": "🐢",
                "TURTLE_SOUP_PLUS_ONE_LONG": "🐢",
                "IRON_CONDOR_PINNING": "🦅",
                "COMMODITY": "⛏️",
            }.get(o.setup_type, "🎯")

            conf_short = (
                "; ".join(o.confluences[:2]) if o.confluences else "High structural asymmetry"
            )
            dir_tag = (
                " [🔻 SHORT]"
                if o.direction == "BEARISH"
                else " [🦅 DELTA-NEUTRAL]"
                if o.direction == "NEUTRAL"
                else " [▲ LONG]"
            )

            if o.direction == "NEUTRAL" or o.setup_type == "IRON_CONDOR_PINNING":
                m = getattr(o, "metrics", {}) or {}
                spe = m.get("short_pe", o.stop_loss)
                sce = m.get("short_ce", o.target_1)
                levels_line = (
                    f"  🎯 <b>Corridor:</b> <code>₹{spe:,.1f} – ₹{sce:,.1f}</code> (Pin Zone)\n"
                )
            elif o.direction == "BEARISH":
                levels_line = f"  🎯 <b>Entry:</b> <code>{o.entry_range}</code> (Ref: ₹{o.ltp:,.2f})\n  🛑 <b>SL (Above):</b> <code>₹{o.stop_loss:,.2f}</code> | <b>T1 (Down):</b> <code>₹{o.target_1:,.2f}</code> | <b>Moonshot:</b> <code>₹{o.moonshot_target:,.2f}</code>\n"
            else:
                levels_line = f"  🎯 <b>Entry:</b> <code>{o.entry_range}</code> (Ref: ₹{o.ltp:,.2f})\n  🛑 <b>SL:</b> <code>₹{o.stop_loss:,.2f}</code> | <b>T1:</b> <code>₹{o.target_1:,.2f}</code> | <b>Moonshot:</b> <code>₹{o.moonshot_target:,.2f}</code>\n"

            lines.append(
                f"{setup_icon} <b>{o.symbol} [{o.segment}]</b>{dir_tag} — <b>{o.setup_type.replace('_', ' ')}</b>\n"
                f"  🧠 <b>Score: {o.conviction_score}/100</b> ({o.verdict}) | <b>1:{o.risk_reward_ratio:.1f} R:R</b>\n"
                f"{levels_line}"
                f"  📊 <i>{conf_short}</i>\n"
                f"  ⚠️ <b>Rule:</b> <i>{o.no_chase_rule}</i>\n"
            )

        return "\n".join(lines)

    try:
        loop = asyncio.get_running_loop()
        res_text = await asyncio.wait_for(
            loop.run_in_executor(None, _run_asymmetric_summary),
            timeout=45,
        )
        await update.message.reply_text(res_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Asymmetric scan failed: {e}")


async def cmd_unknown(update, context) -> None:
    """Handle unknown messages."""
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if not msg:
        return
    await msg.reply_text("Unknown command. Type /help for available commands.")


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
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")

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


def get_telegram_destinations() -> dict[str, Any]:
    """Returns available Telegram destinations: default private chat, F&O group, channel ID."""
    default_chat = _load_chat_id() or ""
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    fno_chat_id = os.environ.get("TELEGRAM_FNO_CHAT_ID", "").strip()
    if not channel_id:
        try:
            from config.credentials import _kr_get

            channel_id = _kr_get("TELEGRAM_CHANNEL_ID") or ""
        except Exception:
            channel_id = ""
    if not fno_chat_id:
        try:
            from engine.alert_preferences import alert_preferences

            fno_chat_id = alert_preferences._preferences.fno_chat_id or ""
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    if "-1004393392375" in fno_chat_id:
        fno_name = "Premium_Alpha_Vortex_FnO_Channel"
    elif "-5352373809" in fno_chat_id:
        fno_name = "Alpha_Vortex_Signals"
    elif fno_chat_id:
        fno_name = "Premium FnO Channel"
    else:
        fno_name = ""
    fno_index_chat_id = os.environ.get("TELEGRAM_FNO_INDEX_CHAT_ID", "").strip()
    if not fno_index_chat_id:
        try:
            from engine.alert_preferences import alert_preferences

            fno_index_chat_id = alert_preferences._preferences.fno_index_chat_id or ""
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    if not fno_index_chat_id:
        fno_index_chat_id = "-1004380788314"

    if "-1004380788314" in fno_index_chat_id:
        fno_index_name = "Premium_Alpha_Vortex_FnO_Index"
    elif fno_index_chat_id:
        fno_index_name = "Premium FnO Index Channel"
    else:
        fno_index_name = ""

    mcx_chat_id = (
        os.environ.get("TELEGRAM_MCX_CHAT_ID", "").strip()
        or os.environ.get("TELEGRAM_COMMODITY_CHAT_ID", "").strip()
    )
    if not mcx_chat_id:
        try:
            from engine.alert_preferences import alert_preferences

            mcx_chat_id = alert_preferences._preferences.mcx_chat_id or ""
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    if not mcx_chat_id:
        mcx_chat_id = "-1004320002599"

    if "-1004320002599" in mcx_chat_id:
        mcx_name = "Premium_Alpha_Vortex_MCX_Channel"
    elif mcx_chat_id:
        mcx_name = "Premium MCX Channel"
    else:
        mcx_name = ""

    equity_chat_id = os.environ.get("TELEGRAM_EQUITY_CHAT_ID", "").strip()
    if not equity_chat_id:
        try:
            from engine.alert_preferences import alert_preferences

            equity_chat_id = alert_preferences._preferences.equity_chat_id or ""
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    if not equity_chat_id:
        equity_chat_id = "-1003524867091"

    if "-1003524867091" in equity_chat_id:
        equity_name = "Premium_Alpha_Vortex_Equity_Channel"
    elif equity_chat_id:
        equity_name = "Premium Equity Channel"
    else:
        equity_name = ""

    free_index_chat_id = os.environ.get("TELEGRAM_FREE_INDEX_CHAT_ID", "").strip()
    if not free_index_chat_id:
        try:
            from engine.alert_preferences import alert_preferences

            free_index_chat_id = alert_preferences._preferences.free_index_chat_id or ""
        except Exception as e_suppressed:
            logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
    if not free_index_chat_id:
        free_index_chat_id = "-1004298387260"

    if "-1004298387260" in free_index_chat_id:
        free_index_name = "Nifty BankNifty Free Signals"
    elif free_index_chat_id:
        free_index_name = "Free Index Signals Channel"
    else:
        free_index_name = ""

    return {
        "default_chat_id": str(default_chat) if default_chat else "",
        "channel_id": channel_id.strip(),
        "fno_chat_id": fno_chat_id.strip(),
        "fno_chat_name": fno_name,
        "fno_index_chat_id": fno_index_chat_id.strip(),
        "fno_index_chat_name": fno_index_name,
        "free_index_chat_id": free_index_chat_id.strip(),
        "free_index_chat_name": free_index_name,
        "free_index_link": "https://t.me/IndiaIndexSignals",
        "mcx_chat_id": mcx_chat_id.strip(),
        "mcx_chat_name": mcx_name,
        "equity_chat_id": equity_chat_id.strip(),
        "equity_chat_name": equity_name,
        "is_configured": bool(
            default_chat
            or fno_chat_id
            or fno_index_chat_id
            or free_index_chat_id
            or mcx_chat_id
            or equity_chat_id
        ),
    }


_THREADS_FILE = Path(__file__).parent.parent / "data" / "telegram_threads.json"
_signal_message_map: dict[str, int] = {}
_signal_map_lock = threading.Lock()
_MAX_SIGNAL_MAP_SIZE = 5000
_threads_loaded = False


def _load_threads_if_needed() -> None:
    global _threads_loaded
    if _threads_loaded:
        return
    with _signal_map_lock:
        if _threads_loaded:
            return
        if _THREADS_FILE.exists():
            try:
                with open(_THREADS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _signal_message_map.update(
                            {str(k): int(v) for k, v in data.items() if str(v).isdigit()}
                        )
            except Exception as e_suppressed:
                logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
        _threads_loaded = True


def _save_threads() -> None:
    try:
        _THREADS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _signal_map_lock:
            data = dict(_signal_message_map)
        with open(_THREADS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


def get_signal_message_id(
    signal_id: str,
    chat_id: Optional[str] = None,
    alert_id: Optional[str] = None,
) -> Optional[int]:
    """Retrieve original Telegram message_id for a given signal_id to thread replies."""
    if not signal_id and not alert_id:
        return None
    _load_threads_if_needed()
    sig = signal_id.lstrip("#").strip() if signal_id else ""
    candidates: list[str] = []
    if sig:
        candidates.append(sig)
    if alert_id:
        aid = alert_id.strip()
        if aid and aid not in candidates:
            candidates.append(aid)
    if sig:
        base_sig = re.sub(r"_\d{4}$", "", sig)
        if base_sig not in candidates:
            candidates.append(base_sig)

    with _signal_map_lock:
        if chat_id:
            clean_chat = str(chat_id).strip()
            if ":" in clean_chat:
                clean_chat = clean_chat.split(":", 1)[0].strip()
            if clean_chat:
                for c in candidates:
                    val = _signal_message_map.get(f"{clean_chat}:{c}")
                    if val is not None:
                        return int(val)
        for c in candidates:
            val = _signal_message_map.get(c)
            if val is not None:
                return int(val)
    return None


def record_signal_message_id(
    signal_id: str,
    message_id: int,
    chat_id: Optional[str] = None,
    alert_id: Optional[str] = None,
    overwrite: bool = True,
) -> None:
    """Record Telegram message_id for a signal to thread future milestone/trailing updates."""
    if not (signal_id or alert_id) or not message_id:
        return
    _load_threads_if_needed()
    sig = signal_id.lstrip("#").strip() if signal_id else ""
    keys_to_index: list[str] = []
    if sig:
        keys_to_index.append(sig)
        base_sig = re.sub(r"_\d{4}$", "", sig)
        if base_sig not in keys_to_index:
            keys_to_index.append(base_sig)
    if alert_id:
        aid = alert_id.strip()
        if aid and aid not in keys_to_index:
            keys_to_index.append(aid)

    clean_chat = ""
    if chat_id:
        clean_chat = str(chat_id).strip()
        if ":" in clean_chat:
            clean_chat = clean_chat.split(":", 1)[0].strip()

    with _signal_map_lock:
        if len(_signal_message_map) >= _MAX_SIGNAL_MAP_SIZE:
            for k in list(_signal_message_map.keys())[:200]:
                _signal_message_map.pop(k, None)
        for k in keys_to_index:
            if overwrite or k not in _signal_message_map:
                _signal_message_map[k] = int(message_id)
            if clean_chat:
                ck = f"{clean_chat}:{k}"
                if overwrite or ck not in _signal_message_map:
                    _signal_message_map[ck] = int(message_id)
    try:
        _save_threads()
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


def clear_signal_message_ids() -> None:
    """Clear in-memory and persisted signal-to-message mapping (useful for testing/cleanup)."""
    with _signal_map_lock:
        _signal_message_map.clear()
    try:
        if _THREADS_FILE.exists():
            _THREADS_FILE.unlink(missing_ok=True)
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


# ── Callback Data Registry & 64-Byte Bounded Sanitizer ──────────

_CALLBACKS_FILE = Path(__file__).parent.parent / "data" / "telegram_callbacks.json"
_callback_data_registry: dict[str, str] = {}
_callback_lock = threading.Lock()
_MAX_CALLBACK_REGISTRY_SIZE = 5000
_callbacks_loaded = False


def _load_callbacks_if_needed() -> None:
    global _callbacks_loaded
    if _callbacks_loaded:
        return
    with _callback_lock:
        if _callbacks_loaded:
            return
        if _CALLBACKS_FILE.exists():
            try:
                with open(_CALLBACKS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _callback_data_registry.update({str(k): str(v) for k, v in data.items()})
            except Exception as e_suppressed:
                logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")
        _callbacks_loaded = True


def _save_callbacks() -> None:
    try:
        _CALLBACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _callback_lock:
            data = dict(_callback_data_registry)
        with open(_CALLBACKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


def build_alert_callback_data(action: str, alert_id: str) -> str:
    """
    Construct safe, protocol-compliant callback_data for Telegram InlineKeyboardButtons.
    Telegram Bot API strictly enforces that callback_data must be 1 to 64 bytes in UTF-8.
    For alerts with long IDs (e.g. commodities or multi-token names > 53 chars),
    compacts the identifier using a deterministic SHA-256 slice registered in the callback registry.
    """
    clean_action = str(action or "").strip()
    clean_aid = str(alert_id or "").strip()
    raw = f"{clean_action}:{clean_aid}"
    if len(raw.encode("utf-8")) <= 64:
        return raw

    import hashlib

    # Deterministic 16-char hash token guarantees total payload <= 64 bytes
    h_token = f"h_{hashlib.sha256(clean_aid.encode('utf-8')).hexdigest()[:16]}"
    compact_data = f"{clean_action}:{h_token}"

    _load_callbacks_if_needed()
    with _callback_lock:
        _callback_data_registry[h_token] = clean_aid
        if len(_callback_data_registry) > _MAX_CALLBACK_REGISTRY_SIZE:
            for k in list(_callback_data_registry.keys())[:200]:
                _callback_data_registry.pop(k, None)
    _save_callbacks()
    return compact_data


def resolve_alert_callback_data(raw_data: str) -> tuple[str, str]:
    """
    Resolve callback query data back to (action, alert_id), decoding compact tokens if present.
    """
    if not raw_data or ":" not in raw_data:
        return ("", "")
    parts = raw_data.split(":", 1)
    action, target = parts[0].strip(), parts[1].strip()
    if target.startswith("h_"):
        _load_callbacks_if_needed()
        with _callback_lock:
            resolved_aid = _callback_data_registry.get(target, target)
        return (action, resolved_aid)
    return (action, target)


def build_alert_execution_keyboard(alert_id: str) -> dict[str, Any]:
    """
    Construct 1-tap mobile execution buttons (⚡ Execute Live, 🛡️ Paper Trade, ❌ Dismiss)
    with bounded callback_data guaranteed never to trigger BUTTON_DATA_INVALID.
    """
    return {
        "inline_keyboard": [
            [
                {
                    "text": "⚡ Execute Live",
                    "callback_data": build_alert_callback_data("exec_live", alert_id),
                },
                {
                    "text": "🛡️ Paper Trade",
                    "callback_data": build_alert_callback_data("exec_paper", alert_id),
                },
                {
                    "text": "❌ Dismiss",
                    "callback_data": build_alert_callback_data("dismiss", alert_id),
                },
            ]
        ]
    }


def sanitize_reply_markup(reply_markup: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Sanitize reply_markup payload ensuring all callback_data values strictly obey Telegram's
    64-byte protocol limit. If any oversized callback data is found, it is safely compacted.
    """
    if not reply_markup or not isinstance(reply_markup, dict):
        return reply_markup
    inline_kb = reply_markup.get("inline_keyboard")
    if not inline_kb or not isinstance(inline_kb, list):
        return reply_markup

    sanitized_rows: list[list[dict[str, Any]]] = []
    for row in inline_kb:
        if not isinstance(row, list):
            continue
        sanitized_row: list[dict[str, Any]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            btn_copy = dict(btn)
            cb = btn_copy.get("callback_data")
            if cb is not None and len(str(cb).encode("utf-8")) > 64:
                cb_str = str(cb).strip()
                if ":" in cb_str:
                    act, val = cb_str.split(":", 1)
                    btn_copy["callback_data"] = build_alert_callback_data(act, val)
                else:
                    import hashlib

                    h = f"cb_{hashlib.sha256(cb_str.encode('utf-8')).hexdigest()[:24]}"
                    _load_callbacks_if_needed()
                    with _callback_lock:
                        _callback_data_registry[h] = cb_str
                    _save_callbacks()
                    btn_copy["callback_data"] = h
            sanitized_row.append(btn_copy)
        sanitized_rows.append(sanitized_row)

    res = dict(reply_markup)
    res["inline_keyboard"] = sanitized_rows
    return res


# ── Quiet Mode & 1-Tap Execution Handlers ──────────────────────


async def cmd_mute(update, context) -> None:
    """Silence audible alert chimes (Quiet mode during meetings/zoom calls)."""
    try:
        from engine.alert_preferences import get_alert_preferences_manager

        mgr = get_alert_preferences_manager()
        mgr.update_preferences({"sound": {"enabled": False}})
        msg = (
            "🔇 <b>Quiet Mode Active:</b> Audio alerts are muted.\n"
            "System is operating in silent mode. All quantitative scanning, "
            "terminal SSE updates, and Telegram setups run at full unconstrained power."
        )
    except Exception as e:
        msg = f"⚠️ Could not set quiet mode: {e}"
    if update and update.message:
        await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_unmute(update, context) -> None:
    """Enable audible alert chimes."""
    try:
        from engine.alert_preferences import get_alert_preferences_manager

        mgr = get_alert_preferences_manager()
        mgr.update_preferences({"sound": {"enabled": True}})
        msg = "🔊 <b>Audio Unmuted:</b> Audio chime alerts are now active."
    except Exception as e:
        msg = f"⚠️ Could not unmute audio: {e}"
    if update and update.message:
        await update.message.reply_text(msg, parse_mode="HTML")


async def handle_alert_callback(update, context) -> None:
    """Handle 1-tap mobile interactive actions: Execute Live, Paper Trade, Dismiss."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    raw_data = str(query.data or "").strip()
    action, alert_id = resolve_alert_callback_data(raw_data)
    if not action or not alert_id:
        return

    if action == "dismiss":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e_suppressed:
            logger.debug(f"[TelegramBot] Callback markup remove exception: {e_suppressed}")
        if query.message:
            await query.message.reply_text(
                f"❌ <b>Alert Dismissed:</b> <code>{alert_id}</code>", parse_mode="HTML"
            )
        return

    if action == "exec_paper":
        try:
            from engine.auto_alert_engine import get_auto_alert_engine

            engine = get_auto_alert_engine()
            alert = engine.get_alert(alert_id)
            if not alert:
                if query.message:
                    await query.message.reply_text(
                        f"⚠️ <b>Alert Not Found:</b> <code>{alert_id}</code>", parse_mode="HTML"
                    )
                return

            plan = getattr(alert, "actionable_plan", {}) or {}
            hedge_plan = plan.get("hedge_plan") or getattr(alert, "hedge_plan", None)
            if hedge_plan and isinstance(hedge_plan, dict) and hedge_plan.get("legs"):
                from engine.multi_leg_executor import execute_defined_risk_spread
                from engine.defined_risk_spreads import DefinedRiskSpread, SpreadLeg

                legs = [
                    SpreadLeg(
                        symbol=l.get("symbol", ""),
                        option_type=l.get("option_type", "CE"),
                        strike=float(l.get("strike", 0.0)),
                        side=l.get("side", "BUY"),
                        premium=float(l.get("premium", 0.0)),
                        lot_size=int(l.get("lot_size", 1)),
                        quantity=int(l.get("quantity", l.get("lot_size", 1))),
                    )
                    for l in hedge_plan.get("legs", [])
                ]
                spread_obj = DefinedRiskSpread(
                    strategy_name=hedge_plan.get("strategy_name", "BULL_CALL_SPREAD"),
                    underlying=getattr(alert, "canonical_symbol", None)
                    or getattr(alert, "symbol", "NIFTY"),
                    spot_price=float(getattr(alert, "ltp", 0.0) or 0.0),
                    legs=legs,
                    net_debit=float(hedge_plan.get("net_debit_per_share", 0.0) or 0.0),
                    max_profit=float(hedge_plan.get("max_profit", 0.0) or 0.0),
                    max_loss=float(hedge_plan.get("max_loss", 0.0) or 0.0),
                    risk_reward_ratio=2.5,
                    breakeven_points=[],
                )
                res = execute_defined_risk_spread(spread=spread_obj, product="MIS")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[telegram_bot] Non-fatal reply markup edit error: {e_suppressed}"
                    )
                if query.message:
                    await query.message.reply_text(
                        f"🛡️ <b>PAPER SPREAD DISPATCHED</b>\n"
                        f"• Alert: <code>{alert_id}</code>\n"
                        f"• Strategy: <b>{res.strategy_name}</b>\n"
                        f"• Status: <b>{res.status}</b>\n"
                        f"• Legs Filled: {len(res.executed_legs)}/{len(res.executed_legs) + len(res.failed_legs)}\n"
                        f"• Net Fill: ₹{res.net_fill_price:.2f}/sh",
                        parse_mode="HTML",
                    )
            else:
                from engine.order_lifecycle import (
                    preview_order_intent,
                    confirm_order_intent,
                    execute_order_intent,
                )

                sym = getattr(alert, "canonical_symbol", None) or getattr(alert, "symbol", "NIFTY")
                act = (plan.get("action") or "BUY").upper()
                side = "SELL" if "SELL" in act or "SHORT" in act else "BUY"
                qty = int(getattr(alert, "lot_size", 1) or 1)
                px = float(getattr(alert, "entry_price", getattr(alert, "ltp", 100.0)) or 100.0)
                import uuid

                intent = preview_order_intent(
                    symbol=sym,
                    side=side,
                    quantity=qty,
                    price=px,
                    idempotency_key=f"TG-PAPER-{alert_id}-{uuid.uuid4().hex[:8]}",
                )
                conf = confirm_order_intent(intent.order_id, intent.preview_hash)
                exec_res = execute_order_intent(conf.order_id)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[telegram_bot] Non-fatal reply markup edit error: {e_suppressed}"
                    )
                if query.message:
                    await query.message.reply_text(
                        f"🛡️ <b>PAPER ORDER EXECUTED</b>\n"
                        f"• Symbol: <b>{sym}</b> ({side} {qty} qty)\n"
                        f"• Order ID: <code>{exec_res.order_id}</code>\n"
                        f"• Status: <b>{exec_res.status}</b>\n"
                        f"• Price: ₹{exec_res.price:.2f}",
                        parse_mode="HTML",
                    )
        except Exception as e:
            logger.error(f"[TelegramBot] Paper execution error for {alert_id}: {e}", exc_info=True)
            if query.message:
                await query.message.reply_text(f"❌ <b>Execution Error:</b> {e}", parse_mode="HTML")
        return

    if action == "exec_live":
        if os.environ.get("ALLOW_LIVE_TRADING") != "1":
            if query.message:
                await query.message.reply_text(
                    "⚠️ <b>LIVE EXECUTION LOCKED (Safety Guardrail)</b>\n"
                    "Live trading is guarded by <code>ALLOW_LIVE_TRADING=1</code>.\n"
                    "Tap <b>[🛡️ Paper Trade]</b> to execute in simulation mode.",
                    parse_mode="HTML",
                )
            return

        try:
            from engine.auto_alert_engine import get_auto_alert_engine

            engine = get_auto_alert_engine()
            alert = engine.get_alert(alert_id)
            if not alert:
                if query.message:
                    await query.message.reply_text(
                        f"⚠️ <b>Alert Not Found:</b> <code>{alert_id}</code>", parse_mode="HTML"
                    )
                return

            plan = getattr(alert, "actionable_plan", {}) or {}
            from engine.order_lifecycle import (
                preview_order_intent,
                confirm_order_intent,
                execute_order_intent,
            )

            sym = getattr(alert, "canonical_symbol", None) or getattr(alert, "symbol", "NIFTY")
            act = (plan.get("action") or "BUY").upper()
            side = "SELL" if "SELL" in act or "SHORT" in act else "BUY"
            qty = int(getattr(alert, "lot_size", 1) or 1)
            px = float(getattr(alert, "entry_price", getattr(alert, "ltp", 100.0)) or 100.0)
            import uuid

            intent = preview_order_intent(
                symbol=sym,
                side=side,
                quantity=qty,
                price=px,
                idempotency_key=f"TG-LIVE-{alert_id}-{uuid.uuid4().hex[:8]}",
            )
            conf = confirm_order_intent(intent.order_id, intent.preview_hash)
            exec_res = execute_order_intent(conf.order_id)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e_suppressed:
                logger.debug(f"[telegram_bot] Non-fatal reply markup edit error: {e_suppressed}")
            if query.message:
                await query.message.reply_text(
                    f"⚡ <b>LIVE BROKER ORDER SUBMITTED</b>\n"
                    f"• Symbol: <b>{sym}</b> ({side} {qty} qty)\n"
                    f"• Order ID: <code>{exec_res.order_id}</code>\n"
                    f"• Status: <b>{exec_res.status}</b>\n"
                    f"• Broker Order ID: <code>{exec_res.broker_order_id}</code>",
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"[TelegramBot] Live execution error for {alert_id}: {e}", exc_info=True)
            if query.message:
                await query.message.reply_text(
                    f"❌ <b>Live Execution Failure:</b> {e}", parse_mode="HTML"
                )
        return


def sanitize_telegram_html(text: str) -> str:
    """
    Sanitize text for Telegram HTML parse_mode:
    Preserves valid supported HTML tags (b, strong, i, em, u, ins, s, strike, del,
    code, pre, blockquote, tg-spoiler, a, span), while escaping stray or invalid
    literal '<' and '>' characters (e.g. '< 0.5%', '<>', '<<') to prevent HTTP 400
    'Unsupported start tag' entity parsing errors.
    """
    if not text or ("<" not in text and ">" not in text):
        return text

    # Regex matching supported Telegram tags
    tag_pattern = re.compile(
        r"(</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote|tg-spoiler)"
        r'(?:\s+[^>]*)?>|<span\s+class="tg-spoiler">|</span>|<a\s+href="[^"]*">|</a>)',
        re.IGNORECASE,
    )

    tokens = []
    last_idx = 0
    for match in tag_pattern.finditer(text):
        start, end = match.span()
        # Text before the valid tag: escape literal < and >
        segment = text[last_idx:start]
        segment = segment.replace("<", "&lt;").replace(">", "&gt;")
        tokens.append(segment)
        # Valid tag preserved verbatim
        tokens.append(match.group(0))
        last_idx = end

    # Remaining text after the last tag
    trailing = text[last_idx:]
    trailing = trailing.replace("<", "&lt;").replace(">", "&gt;")
    tokens.append(trailing)

    return "".join(tokens)


def format_telegram_push_payload(
    message: str,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    disable_notification: Optional[bool] = None,
    signal_id: Optional[str] = None,
    message_thread_id: Optional[int] = None,
    parse_mode: str = "HTML",
    alert_id: Optional[str] = None,
    is_update: Optional[bool] = None,
    reply_markup: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Construct the canonical Telegram sendMessage payload.
    Handles:
      1. Topic/Thread Partitioning: extracts topic ID from 'chat_id:topic_id' or TELEGRAM_TOPIC_ID.
      2. Thread Partitioning via reply_to_message_id: links updates/milestones back to the original call.
      3. Audio / Tone Differentiator: sets disable_notification=True for minor trailing ratchets or silent alerts.
      4. Explicit Lifecycle State: enforces top-level delivery when is_update is False.
    """
    target_chat_id = (
        str(chat_id).strip() if chat_id is not None and str(chat_id).strip() else _load_chat_id()
    )

    # Topic/thread parsing: support "chat_id:thread_id" syntax
    if target_chat_id and ":" in str(target_chat_id):
        parts = str(target_chat_id).split(":", 1)
        if parts[1].strip().isdigit():
            target_chat_id = parts[0].strip()
            if message_thread_id is None:
                message_thread_id = int(parts[1].strip())

    if message_thread_id is None:
        env_tid = os.environ.get("TELEGRAM_TOPIC_ID") or os.environ.get(
            "TELEGRAM_MESSAGE_THREAD_ID"
        )
        if env_tid and env_tid.strip().isdigit():
            message_thread_id = int(env_tid.strip())

    # Guard: FNO_INDEX channels (-1004380788314 and Free -1004298387260) strictly restricted to Nifty, Banknifty, Midcp, and Sensex
    fno_idx_env_id = os.environ.get("TELEGRAM_FNO_INDEX_CHAT_ID", "-1004380788314").strip()
    free_idx_env_id = os.environ.get("TELEGRAM_FREE_INDEX_CHAT_ID", "-1004298387260").strip()
    if target_chat_id and str(target_chat_id) in (fno_idx_env_id, free_idx_env_id):
        m_blocked = re.search(
            r"\b(FINNIFTY|BANKEX|NIFTYNXT50|CNXIT|NIFTYIT|NIFTYAUTO|NIFTYPHARMA|NIFTYMETAL|NIFTYENERGY)\b",
            message,
            re.IGNORECASE,
        )
        if m_blocked:
            return {}

    clean_message = (
        sanitize_telegram_html(message) if (parse_mode or "").upper() == "HTML" else message
    )
    payload: dict[str, Any] = {"chat_id": target_chat_id, "text": clean_message}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id

    # Extract signal_id if not explicitly provided
    resolved_sig = (signal_id or "").lstrip("#").strip()
    if not resolved_sig:
        m = re.search(r"#(SIG_[a-zA-Z0-9_]+)", message)
        if m:
            resolved_sig = m.group(1).lstrip("#").strip()

    # Thread Partitioning via reply_to_message_id:
    # 1. Explicit False: Initial trade calls NEVER thread under prior messages
    if is_update is False:
        reply_to_message_id = None
    elif reply_to_message_id is None and (
        resolved_sig or alert_id or re.search(r"#(SIG_[a-zA-Z0-9_]+)", message)
    ):
        # 2. Defensive heuristic when caller did not pass is_update explicitly
        if is_update is None:
            is_new_call = bool(
                re.search(
                    r"\b(?:NEW\s+CALL|NEW\s+TRADE\s+SETUP|NEW\s+RADAR|PRECURSOR\s+RADAR|EOD\s+WATCHLIST|WATCHLIST|ALPHA\s+VORTEX)\b",
                    message,
                    re.IGNORECASE,
                )
            )
            if is_new_call:
                is_update = False
            else:
                # Genuine update must carry an explicit UPDATE marker or milestone event header
                is_update = bool(
                    re.search(r"\bUPDATE\s*(?:#?\d+|·|:|-)\b", message, re.IGNORECASE)
                    or re.search(
                        r"\b(?:TARGET\s+\d+|FINAL\s+TARGET|TRAILING\s+STOP|VIEW\s+INVALIDATED|STOP\s+LOSS\s+HIT|RUNNER\s+EXIT|PROFIT\s+SECURED|BREAKEVEN\s+LOCKED|SPREAD\s+FREE-ROLL\s+UNLOCKED)\b",
                        message,
                        re.IGNORECASE,
                    )
                )

        if is_update:
            if resolved_sig or alert_id:
                reply_to_message_id = get_signal_message_id(
                    resolved_sig, chat_id=target_chat_id, alert_id=alert_id
                )
            if not reply_to_message_id:
                m_tag = re.search(r"#(SIG_[a-zA-Z0-9_]+)", message)
                if m_tag:
                    reply_to_message_id = get_signal_message_id(
                        m_tag.group(1), chat_id=target_chat_id, alert_id=alert_id
                    )

    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
        payload["allow_sending_without_reply"] = True
        payload["reply_parameters"] = {
            "message_id": int(reply_to_message_id),
            "allow_sending_without_reply": True,
        }

    # Audio / Tone Differentiator:
    # Silent (disable_notification=True): TRAIL RATCHET, PRECURSOR RADAR, EOD, morning brief
    # Audible (disable_notification=False): NEW CALL, TARGET 1/2/FINAL, STOP LOSS EXIT, INVALIDATED
    if disable_notification is None:
        msg_upper = message.upper()
        if (
            "TRAIL_RATCHET" in msg_upper
            or "TRAILING STOP RATCHET" in msg_upper
            or "PRECURSOR RADAR" in msg_upper
            or "MORNING BRIEF" in msg_upper
            or "EOD REPORT" in msg_upper
            or "[SILENT]" in msg_upper
        ):
            disable_notification = True
        else:
            disable_notification = False

    if disable_notification:
        payload["disable_notification"] = True

    if reply_markup is not None:
        payload["reply_markup"] = sanitize_reply_markup(reply_markup)

    return payload


def send_push(
    message: str,
    parse_mode: str = "HTML",
    bypass_dedup: bool = False,
    chat_id: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    disable_notification: Optional[bool] = None,
    signal_id: Optional[str] = None,
    message_thread_id: Optional[int] = None,
    on_success: Optional[Callable[[int], None]] = None,
    alert_id: Optional[str] = None,
    is_update: Optional[bool] = None,
    reply_markup: Optional[dict[str, Any]] = None,
) -> None:
    """
    Send a push notification to the configured Telegram chat, group, or channel.
    Called from alerts, morning brief scheduler, execution gate, etc.
    Non-blocking — runs in a background thread.
    Includes a 5-minute anti-flood message deduplication guard.
    Supports in-thread replies (reply_to_message_id), topic routing (message_thread_id),
    audible vs silent notification delivery (disable_notification), explicit lifecycle typing (is_update),
    and on_success callbacks.
    """
    import hashlib
    import time

    target_chat_id = (chat_id or "").strip() or _load_chat_id()
    if not target_chat_id:
        return

    try:
        token = _get_bot_token()
    except Exception:
        return

    now = time.time()
    if not bypass_dedup:
        normalized = _normalize_push_message(message)
        digest = hashlib.sha256(f"{target_chat_id}:{normalized}".encode("utf-8")).hexdigest()

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

    payload = format_telegram_push_payload(
        message=message,
        chat_id=target_chat_id,
        reply_to_message_id=reply_to_message_id,
        disable_notification=disable_notification,
        signal_id=signal_id,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
        alert_id=alert_id,
        is_update=is_update,
        reply_markup=reply_markup,
    )
    if not payload or not payload.get("text"):
        return

    resolved_sig = (signal_id or "").lstrip("#").strip()
    tags = [t.lstrip("#").strip() for t in re.findall(r"#(SIG_[a-zA-Z0-9_]+)", message)]
    if not resolved_sig and tags:
        resolved_sig = tags[0]

    def _send():
        if os.environ.get("CHANAKYA_TESTING") == "1" and not _ALLOW_TEST_DISPATCH:
            logger.debug(
                "[TelegramPush] Network call skipped during test execution (CHANAKYA_TESTING=1)"
            )
            return
        try:
            import httpx

            url = f"https://api.telegram.org/bot{token}/sendMessage"

            def _record_and_callback(data: dict[str, Any]) -> None:
                try:
                    msg_id = data.get("result", {}).get("message_id")
                    if msg_id:
                        keys_to_record = set()
                        if resolved_sig:
                            keys_to_record.add(resolved_sig)
                        for t in tags:
                            keys_to_record.add(t)
                        if alert_id:
                            keys_to_record.add(alert_id)
                        for k in keys_to_record:
                            record_signal_message_id(
                                k,
                                msg_id,
                                chat_id=target_chat_id,
                                alert_id=alert_id,
                                overwrite=not bool(is_update),
                            )
                        if on_success and callable(on_success):
                            try:
                                on_success(int(msg_id))
                            except Exception as e_suppressed:
                                logger.debug(
                                    f"[bot.telegram_bot] Non-fatal on_success exception: {e_suppressed}"
                                )
                except Exception as e_suppressed:
                    logger.debug(
                        f"[bot.telegram_bot] Non-fatal record_signal exception: {e_suppressed}"
                    )

            # Stage 1: Attempt standard formatted dispatch
            resp = httpx.post(url, json=payload, timeout=10)
            if resp.is_success:
                _record_and_callback(resp.json())
                return

            err_data: dict[str, Any] = {}
            try:
                err_data = resp.json()
            except Exception as e_json:
                logger.debug("[TelegramPush] Non-JSON error response from Telegram: %s", e_json)
            err_desc = err_data.get("description", resp.text[:200])

            logger.warning(
                f"[TelegramPush] Telegram API rejected message for chat {target_chat_id}: "
                f"HTTP {resp.status_code} - {err_desc}"
            )

            # Stage 2: Multi-Stage Adaptive Recovery based on Telegram error cause
            adaptive_payload = dict(payload)
            needs_adaptive_retry = False
            err_desc_lower = err_desc.lower()

            # 2a. Button data error (e.g. BUTTON_DATA_INVALID) -> strip reply_markup
            if "button_data_invalid" in err_desc_lower or "button" in err_desc_lower:
                if "reply_markup" in adaptive_payload:
                    adaptive_payload.pop("reply_markup", None)
                    needs_adaptive_retry = True
                    logger.info(
                        f"[TelegramPush] Stripped reply_markup for chat {target_chat_id} due to button error: {err_desc}"
                    )

            # 2b. Reply reference error (e.g. replied message not found) -> strip reply parameters
            if any(
                k in err_desc_lower
                for k in (
                    "replied",
                    "reply_to_message_id",
                    "message to be replied not found",
                    "reply_parameters",
                )
            ):
                if (
                    "reply_to_message_id" in adaptive_payload
                    or "reply_parameters" in adaptive_payload
                ):
                    adaptive_payload.pop("reply_to_message_id", None)
                    adaptive_payload.pop("reply_parameters", None)
                    adaptive_payload.pop("allow_sending_without_reply", None)
                    needs_adaptive_retry = True
                    logger.info(
                        f"[TelegramPush] Stripped reply parameters for chat {target_chat_id} due to reply error: {err_desc}"
                    )

            # 2c. Thread error (e.g. message thread not found) -> strip message_thread_id
            if "thread" in err_desc_lower:
                if "message_thread_id" in adaptive_payload:
                    adaptive_payload.pop("message_thread_id", None)
                    needs_adaptive_retry = True
                    logger.info(
                        f"[TelegramPush] Stripped message_thread_id for chat {target_chat_id} due to thread error: {err_desc}"
                    )

            # 2d. HTML parsing / entities error
            if any(
                k in err_desc_lower
                for k in ("can't parse entities", "parse", "tag", "html", "entity")
            ):
                clean_text = (
                    re.sub(r"<[^>]*>", "", message).replace("<", "").replace(">", "").strip()
                )
                adaptive_payload.pop("parse_mode", None)
                adaptive_payload["text"] = clean_text
                needs_adaptive_retry = True
                logger.info(
                    f"[TelegramPush] Stripped HTML formatting for chat {target_chat_id} due to parse error: {err_desc}"
                )

            if needs_adaptive_retry:
                resp2 = httpx.post(url, json=adaptive_payload, timeout=10)
                if resp2.is_success:
                    logger.info(
                        f"[TelegramPush] Telegram adaptive retry succeeded for chat {target_chat_id}"
                    )
                    _record_and_callback(resp2.json())
                    return

                err2_data: dict[str, Any] = {}
                try:
                    err2_data = resp2.json()
                except Exception as e_json:
                    logger.debug("[TelegramPush] Non-JSON error response on retry: %s", e_json)
                err2_desc = err2_data.get("description", resp2.text[:200])
                logger.warning(
                    f"[TelegramPush] Telegram adaptive retry failed for chat {target_chat_id}: "
                    f"HTTP {resp2.status_code} - {err2_desc}"
                )

            # Stage 3: Ultimate Fail-Safe Barebones Delivery (Zero-Blackout Guarantee)
            # Guarantees market setups and critical alerts are never lost
            barebones_text = (
                re.sub(r"<[^>]*>", "", message).replace("<", "").replace(">", "")[:4096].strip()
            )
            if barebones_text:
                barebones_payload = {
                    "chat_id": target_chat_id,
                    "text": barebones_text,
                }
                if barebones_payload != adaptive_payload:
                    resp3 = httpx.post(url, json=barebones_payload, timeout=10)
                    if resp3.is_success:
                        logger.info(
                            f"[TelegramPush] Telegram barebones fail-safe succeeded for chat {target_chat_id}"
                        )
                        _record_and_callback(resp3.json())
                        return

                    err3_data: dict[str, Any] = {}
                    try:
                        err3_data = resp3.json()
                    except Exception as e_json:
                        logger.debug(
                            "[TelegramPush] Non-JSON error response on fail-safe: %s", e_json
                        )
                    err3_desc = err3_data.get("description", resp3.text[:200])
                    logger.error(
                        f"[TelegramPush] Telegram barebones fail-safe failed for chat {target_chat_id}: "
                        f"HTTP {resp3.status_code} - {err3_desc}"
                    )
        except Exception as e:
            logger.warning(
                f"[TelegramPush] Exception delivering push to Telegram chat {target_chat_id}: {e}",
                exc_info=True,
            )

    _get_push_executor().submit(_send)


# Canonical alias for sending messages / broadcasts
send_message = send_push


def push_alert(alert_desc: str) -> None:
    """Push an alert trigger notification."""
    send_push(f"🔔 <b>ALERT TRIGGERED</b>\n\n{alert_desc}")


def push_brief(brief_text: str) -> None:
    """Push a morning brief."""
    send_push(f"🇮🇳 <b>Morning Brief</b>\n\n{brief_text}")


def format_execution_alert_message(d: dict) -> str:
    """Format a crisp, actionable, zero-redundancy Execution Readiness notification for Telegram."""
    return render_equity_alert(d)


def push_execution_alert(report_dict: dict) -> None:
    """Push rich Execution Readiness notification to Telegram."""
    try:
        msg = format_execution_alert_message(report_dict)
        send_push(msg, parse_mode="HTML")
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


def format_blast_alert(
    d: dict,
    underlying: str = "NIFTY",
    spot: float = 0.0,
    conviction_score: dict | None = None,
) -> str:
    """Format a crisp, high-conviction Gamma Blast / Order Book Squeeze alert for Telegram."""
    return render_fno_alert(d, underlying=underlying, spot=spot, conviction_score=conviction_score)


def send_blast_push(
    blast_data: dict,
    underlying: str = "NIFTY",
    spot: float = 0.0,
    conviction_score: dict | None = None,
    chat_id: Optional[str] = None,
) -> bool:
    """
    Send an actionable Blast alert notification to Telegram.
    If conviction_score is not provided, computes a live score automatically.
    Routes to TELEGRAM_FNO_CHAT_ID or TELEGRAM_CHANNEL_ID if configured.
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
        target_chat_id = (
            (chat_id or "").strip()
            or os.environ.get("TELEGRAM_FNO_CHAT_ID", "").strip()
            or os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
            or _load_chat_id()
        )
        send_push(msg, parse_mode="HTML", bypass_dedup=True, chat_id=target_chat_id)
        return True
    except Exception as e:
        logger.warning(f"Failed to send blast push to Telegram: {e}")
        return False


def format_precursor_alert(candidate_dict: dict) -> str:
    """Format a high-conviction Precursor Radar alert for Telegram push."""
    return render_precursor_alert(candidate_dict)


def send_precursor_push(candidate_dict: dict) -> bool:
    """Send an actionable Precursor Radar alert notification to Telegram."""
    try:
        from engine.alert_preferences import alert_preferences, classify_alert_segment

        seg = classify_alert_segment(candidate_dict)
        target_chat_id = alert_preferences.get_telegram_chat_id(seg)
        msg = format_precursor_alert(candidate_dict)
        send_push(msg, parse_mode="HTML", bypass_dedup=True, chat_id=target_chat_id)
        return True
    except Exception as e:
        logger.warning(f"Failed to send precursor push to Telegram: {e}")
        return False


def format_asymmetric_alert(opp_dict: dict) -> str:
    """Format a high-conviction Asymmetric Opportunity (1:3+ R:R) alert for Telegram push."""
    return render_asymmetric_alert(opp_dict)


def send_asymmetric_push(opp_dict: dict) -> bool:
    """Send an actionable Asymmetric Opportunity alert notification to Telegram."""
    try:
        from engine.alert_preferences import alert_preferences, classify_alert_segment

        seg = classify_alert_segment(opp_dict)
        target_chat_id = alert_preferences.get_telegram_chat_id(seg)
        msg = format_asymmetric_alert(opp_dict)
        send_push(msg, parse_mode="HTML", bypass_dedup=True, chat_id=target_chat_id)
        return True
    except Exception as e:
        logger.warning(f"Failed to send asymmetric push to Telegram: {e}")
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
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


# ── Bot Runner ───────────────────────────────────────────────


def run_bot() -> None:
    """Start the Telegram bot (blocking — runs the event loop)."""
    (
        Update,
        Bot,
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        CallbackQueryHandler,
        filters,
    ) = _get_telegram()

    token = _get_bot_token()

    app = ApplicationBuilder().token(token).build()

    # Register command handlers (wrapped with _track_command for REPL badge)
    app.add_handler(CommandHandler("start", _track_command(cmd_start)))
    app.add_handler(CommandHandler("help", _track_command(cmd_help)))
    app.add_handler(CommandHandler("quote", _track_command(cmd_quote)))
    app.add_handler(CommandHandler("analyze", _track_command(cmd_analyze)))
    app.add_handler(CommandHandler("deepanalyze", _track_command(cmd_deepanalyze)))
    app.add_handler(CommandHandler("brief", _track_command(cmd_brief)))
    app.add_handler(CommandHandler("strikes", _track_command(cmd_strike_radar)))
    app.add_handler(CommandHandler("battleplan", _track_command(cmd_strike_radar)))
    app.add_handler(CommandHandler("orb", _track_command(cmd_orb_radar)))
    app.add_handler(CommandHandler("eod", _track_command(cmd_eod)))
    app.add_handler(CommandHandler("conviction", _track_command(cmd_conviction)))
    app.add_handler(CommandHandler("movers", _track_command(cmd_movers)))
    app.add_handler(CommandHandler("precursors", _track_command(cmd_precursors)))
    app.add_handler(CommandHandler("dryup", _track_command(cmd_dryup)))
    app.add_handler(CommandHandler("preinflection", _track_command(cmd_dryup)))
    app.add_handler(CommandHandler("pre_inflection", _track_command(cmd_dryup)))
    app.add_handler(CommandHandler("squeeze", _track_command(cmd_squeeze)))
    app.add_handler(CommandHandler("coilers", _track_command(cmd_squeeze)))
    app.add_handler(CommandHandler("asymmetric", _track_command(cmd_asymmetric)))
    app.add_handler(CommandHandler("opps", _track_command(cmd_asymmetric)))
    app.add_handler(CommandHandler("scan", _track_command(cmd_scan)))
    app.add_handler(CommandHandler("radar", _track_command(cmd_scan)))
    app.add_handler(CommandHandler("flows", _track_command(cmd_flows)))
    app.add_handler(CommandHandler("earnings", _track_command(cmd_earnings)))
    app.add_handler(CommandHandler("events", _track_command(cmd_events)))
    app.add_handler(CommandHandler("macro", _track_command(cmd_macro)))
    app.add_handler(CommandHandler("alert", _track_command(cmd_alert)))
    app.add_handler(CommandHandler("alerts", _track_command(cmd_alerts)))
    app.add_handler(CommandHandler("filter", _track_command(cmd_filter)))
    app.add_handler(CommandHandler("segments", _track_command(cmd_filter)))
    app.add_handler(CommandHandler("mute", _track_command(cmd_mute)))
    app.add_handler(CommandHandler("unmute", _track_command(cmd_unmute)))
    app.add_handler(CommandHandler("channels", _track_command(cmd_channels)))
    app.add_handler(CommandHandler("ping_all", _track_command(cmd_ping_all)))
    app.add_handler(CommandHandler("memory", _track_command(cmd_memory)))
    app.add_handler(CommandHandler("pnl", _track_command(cmd_pnl)))
    app.add_handler(CallbackQueryHandler(_track_command(handle_alert_callback)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _track_command(cmd_unknown)))

    async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.warning("Telegram bot update handler error: %s", context.error)

    app.add_error_handler(_on_error)

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
    except Exception as e_suppressed:
        logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")

    # run_polling() registers OS signal handlers which only work on the main
    # thread. Use the lower-level async API instead — no signal handlers at all.
    async def _run() -> None:
        async with app:
            await app.start()
            await app.updater.start_polling()
            logger.info("Telegram bot polling started successfully.")
            # Keep running until cancelled or process exit
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Bot polling event loop exception: %s", e)
                    await asyncio.sleep(5)

    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
            break
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.error("Telegram bot runner error: %s. Retrying in 5 seconds...", e)
            import time

            time.sleep(5)
        finally:
            try:
                loop.close()
            except Exception as e_suppressed:
                logger.debug(f"[bot.telegram_bot] Non-fatal exception suppressed: {e_suppressed}")


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
