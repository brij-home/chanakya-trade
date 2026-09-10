"""
engine/alerts.py
────────────────
Price and technical alerts with background polling.

Usage:
    from engine.alerts import alert_manager

    alert_manager.add_price_alert("RELIANCE", "ABOVE", 2800)
    alert_manager.add_technical_alert("INFY", "RSI", "ABOVE", 70)
    alert_manager.start_polling()       # daemon thread, 60s interval
    alert_manager.list_alerts()         # show all active alerts
    alert_manager.remove_alert(id)      # cancel an alert
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

ALERTS_FILE = Path.home() / ".trading_platform" / "alerts.json"


def validate_webhook_url(url: str) -> str:
    """Accept only an HTTPS callback with a non-local hostname.

    DNS is checked again immediately before delivery to mitigate callbacks that
    resolve to a private address after registration.
    """
    parsed = urlparse(url.strip())
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Webhook URL must be an HTTPS URL without credentials")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Webhook URL must not target a local or private address")
    except ValueError as exc:
        if "must not target" in str(exc):
            raise
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".local"):
        raise ValueError("Webhook URL must not target a local hostname")
    return url.strip()


def _resolves_to_public_address(url: str) -> bool:
    """Return true only when every current DNS answer is publicly routable."""
    parsed = urlparse(url)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_global for item in addresses
        )
    except (OSError, ValueError):
        return False


# ── Data model ────────────────────────────────────────────────


@dataclass
class AlertCondition:
    """A single condition within a conditional alert."""

    condition_type: str  # "PRICE" or "TECHNICAL"
    condition: str  # "ABOVE" or "BELOW"
    threshold: float
    indicator: Optional[str] = None  # for TECHNICAL: "RSI", "MACD", etc.

    def describe(self) -> str:
        if self.condition_type == "TECHNICAL":
            return f"{self.indicator} {self.condition} {self.threshold}"
        return f"price {self.condition} ₹{self.threshold:,.2f}"


@dataclass
class Alert:
    id: str
    alert_type: str  # PRICE | TECHNICAL | CONDITIONAL
    symbol: str  # e.g. "RELIANCE"
    exchange: str  # e.g. "NSE"
    condition: str  # ABOVE | BELOW | CROSSES
    threshold: float  # e.g. 2800.0
    indicator: Optional[str] = None  # For technical: RSI, MACD_SIGNAL, etc.
    message: str = ""
    created_at: str = ""
    triggered: bool = False
    triggered_at: Optional[str] = None
    # Conditional alert: multiple conditions joined by AND
    conditions: list[dict] = field(default_factory=list)
    # OpenClaw / external callback: POST alert payload here when triggered
    webhook_url: Optional[str] = None
    # Generated per alert.  Persisted locally, never returned by alert lists.
    webhook_secret: Optional[str] = None
    is_live: bool = True  # True if Live market alert, False if TEST
    environment: str = "LIVE"  # "LIVE" | "TEST"
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    invalidated_at: Optional[str] = None
    invalidation_threshold: Optional[float] = None
    target_price: Optional[float] = None
    target_achieved: bool = False
    trailing_stop: Optional[float] = None
    should_trail: bool = False
    trailing_decision: Optional[str] = None
    trailing_rationale: Optional[str] = None
    achieved_milestones: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

    def describe(self) -> str:
        if self.alert_type == "CONDITIONAL" and self.conditions:
            parts = []
            for c in self.conditions:
                cond = AlertCondition(**c) if isinstance(c, dict) else c
                parts.append(cond.describe())
            return f"{self.symbol} ({' AND '.join(parts)})"
        if self.alert_type == "TECHNICAL":
            return f"{self.symbol} {self.indicator} {self.condition} {self.threshold}"
        return f"{self.symbol} price {self.condition} ₹{self.threshold:,.2f}"


# ── Alert Manager ─────────────────────────────────────────────


def _is_market_hours(exchange: str = "NSE") -> bool:
    """
    Returns True only during active trading hours for the given exchange:
      - NSE / BSE / NFO: Mon–Fri, 09:15–15:30 IST.
      - CDS (Currency Derivatives): Mon–Fri, 09:00–17:00 IST.
      - MCX (Commodities): Mon–Fri, 09:00–23:30 IST (or 23:55 in winter).
    Prevents alerts firing on stale prices outside market hours.
    """
    from datetime import timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    exch = (exchange or "NSE").upper()
    if exch == "MCX":
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=23, minute=30, second=0, microsecond=0)
    elif exch in ("CDS", "CURRENCY"):
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=17, minute=0, second=0, microsecond=0)
    else:  # NSE, BSE, NFO, default
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    return market_open <= now <= market_close


class AlertManager:
    """Manages alerts with persistence and background polling."""

    def __init__(self) -> None:
        self._alerts: list[Alert] = []
        self._poller_thread: Optional[threading.Thread] = None
        self._polling = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()  # protects triggered flag against tick races
        self._load()

    # ── Public API ────────────────────────────────────────────

    def add_price_alert(
        self,
        symbol: str,
        condition: str,
        threshold: float,
        exchange: str = "NSE",
        webhook_url: Optional[str] = None,
    ) -> Alert:
        """Create a price-based alert (ABOVE / BELOW / CROSSES).

        Returns existing alert without creating a duplicate if an identical
        non-triggered alert (same symbol, exchange, condition, threshold) already exists.
        """
        sym = symbol.upper()
        exch = exchange.upper()
        cond = condition.upper()
        thr = float(threshold)

        for existing in self._alerts:
            if (
                not existing.triggered
                and existing.alert_type == "PRICE"
                and existing.symbol == sym
                and existing.exchange == exch
                and existing.condition == cond
                and existing.threshold == thr
            ):
                return existing  # already watching this level

        alert = Alert(
            id=str(uuid.uuid4())[:8],
            alert_type="PRICE",
            symbol=sym,
            exchange=exch,
            condition=cond,
            threshold=thr,
            created_at=datetime.now().isoformat(timespec="seconds"),
            webhook_url=webhook_url,
            webhook_secret=secrets.token_urlsafe(32) if webhook_url else None,
        )
        alert.message = alert.describe()
        self._alerts.append(alert)
        self._save()
        self._auto_subscribe(alert)
        return alert

    def add_technical_alert(
        self,
        symbol: str,
        indicator: str,
        condition: str,
        threshold: float,
        exchange: str = "NSE",
        webhook_url: Optional[str] = None,
    ) -> Alert:
        """Create a technical-indicator alert (RSI > 70, etc.).

        Returns existing alert without creating a duplicate if an identical
        non-triggered alert already exists.
        """
        sym = symbol.upper()
        exch = exchange.upper()
        cond = condition.upper()
        ind = indicator.upper()
        thr = float(threshold)

        for existing in self._alerts:
            if (
                not existing.triggered
                and existing.alert_type == "TECHNICAL"
                and existing.symbol == sym
                and existing.exchange == exch
                and existing.condition == cond
                and existing.indicator == ind
                and existing.threshold == thr
            ):
                return existing  # already watching this indicator level

        alert = Alert(
            id=str(uuid.uuid4())[:8],
            alert_type="TECHNICAL",
            symbol=sym,
            exchange=exch,
            condition=cond,
            threshold=thr,
            indicator=ind,
            created_at=datetime.now().isoformat(timespec="seconds"),
            webhook_url=webhook_url,
            webhook_secret=secrets.token_urlsafe(32) if webhook_url else None,
        )
        alert.message = alert.describe()
        self._alerts.append(alert)
        self._save()
        return alert

    def add_conditional_alert(
        self,
        symbol: str,
        conditions: list[dict],
        exchange: str = "NSE",
        webhook_url: Optional[str] = None,
    ) -> Alert:
        """
        Create a conditional alert with AND logic.

        conditions: list of dicts, each with:
            condition_type: "PRICE" or "TECHNICAL"
            condition: "ABOVE" or "BELOW"
            threshold: float
            indicator: str (only for TECHNICAL, e.g. "RSI")

        Example:
            add_conditional_alert("RELIANCE", [
                {"condition_type": "PRICE", "condition": "ABOVE", "threshold": 2800},
                {"condition_type": "TECHNICAL", "condition": "ABOVE", "threshold": 60, "indicator": "RSI"},
            ])
            → Triggers when RELIANCE price > 2800 AND RSI > 60
        """
        alert = Alert(
            id=str(uuid.uuid4())[:8],
            alert_type="CONDITIONAL",
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            condition="AND",
            threshold=0,
            conditions=conditions,
            created_at=datetime.now().isoformat(timespec="seconds"),
            webhook_url=webhook_url,
            webhook_secret=secrets.token_urlsafe(32) if webhook_url else None,
        )
        alert.message = alert.describe()
        self._alerts.append(alert)
        self._save()
        return alert

    def remove_alert(self, alert_id: str) -> bool:
        before = len(self._alerts)
        self._alerts = [a for a in self._alerts if a.id != alert_id]
        removed = len(self._alerts) < before
        if removed:
            self._save()
        return removed

    def list_alerts(self) -> list[dict]:
        """Return all active (non-triggered) alerts as dicts."""
        return [self.public_dict(a) for a in self._alerts if not a.triggered]

    def cleanup_archived_alerts(self, max_age_days: int = 3) -> int:
        """Prunes triggered, invalidated, or target-achieved manual alerts older than max_age_days."""
        from datetime import datetime, timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))
        cutoff = datetime.now(IST) - timedelta(days=max_age_days)
        purged = 0
        surviving = []
        with self._lock:
            for a in self._alerts:
                if not (a.triggered or a.is_invalidated or a.target_achieved):
                    surviving.append(a)
                    continue
                # Parse timestamp
                ts_str = a.invalidated_at or a.triggered_at or a.created_at or ""
                dt = None
                if ts_str:
                    clean = ts_str.replace(" IST", "").strip()
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                        try:
                            dt = datetime.strptime(clean[:19], fmt).replace(tzinfo=IST)
                            break
                        except Exception:
                            continue
                if dt and dt < cutoff:
                    purged += 1
                else:
                    surviving.append(a)
            if purged > 0:
                self._alerts = surviving
                self._save()
        return purged

    @staticmethod
    def public_dict(alert: Alert) -> dict:
        """Serialize an alert without exposing its callback signing secret."""
        payload = asdict(alert)
        payload.pop("webhook_secret", None)
        payload["timestamp"] = (
            alert.triggered_at
            or alert.invalidated_at
            or alert.created_at
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        )
        return payload

    def active_count(self) -> int:
        return sum(1 for a in self._alerts if not a.triggered)

    def print_alerts(self) -> None:
        """Display alerts as a Rich table."""
        active = [a for a in self._alerts if not a.triggered]
        if not active:
            console.print("[dim]No active alerts.[/dim]")
            return

        table = Table(title="Active Alerts", show_lines=False)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Type", width=10)
        table.add_column("Alert", style="bold")
        table.add_column("Created", style="dim")

        for a in active:
            table.add_row(a.id, a.alert_type, a.describe(), a.created_at)
        console.print(table)

    # ── Polling ───────────────────────────────────────────────

    def start_realtime(self) -> None:
        """
        Register with WebSocket for real-time alert evaluation.
        Fires on every tick — instant alerts instead of 60s polling.
        Falls back to polling if WebSocket is not connected.
        """
        try:
            from market.websocket import ws_manager

            if ws_manager.connected:
                ws_manager.on_tick(self._on_tick)
                # Subscribe to all alerted symbols
                symbols = list(
                    {f"{a.exchange}:{a.symbol}" for a in self._alerts if not a.triggered}
                )
                if symbols:
                    ws_manager.subscribe(symbols)
                console.print("[dim]  Alerts: real-time via WebSocket[/dim]")
                return
        except Exception:
            pass

        # Fallback to polling
        self.start_polling(interval=60)

    def _on_tick(self, tick) -> None:
        """Called on every WebSocket tick — evaluate price alerts instantly.

        Uses a lock to prevent the race condition where multiple rapid ticks
        all see triggered=False simultaneously and each fire a notification.
        Only fires during market hours (9:15–15:30 IST, Mon–Fri).
        """
        if self.active_count() == 0:
            return
        if not _is_market_hours():
            return

        ltp = tick.ltp if hasattr(tick, "ltp") else 0
        if ltp <= 0:
            return

        tick_sym = tick.symbol if hasattr(tick, "symbol") else ""

        to_notify: list[tuple[Alert, float]] = []

        with self._lock:
            for alert in self._alerts:
                if alert.triggered:
                    continue
                if alert.alert_type != "PRICE":
                    continue

                alert_sym_variants = [
                    f"{alert.exchange}:{alert.symbol}-EQ",
                    f"{alert.exchange}:{alert.symbol}",
                ]
                if tick_sym not in alert_sym_variants:
                    continue

                condition_met = False
                if alert.condition == "ABOVE" and ltp >= alert.threshold:
                    condition_met = True
                elif alert.condition == "BELOW" and ltp <= alert.threshold:
                    condition_met = True
                elif alert.condition == "CROSSES" and ltp >= alert.threshold:
                    condition_met = True

                if condition_met:
                    # Set inside lock — prevents other threads double-firing
                    alert.triggered = True
                    alert.triggered_at = datetime.now().isoformat(timespec="seconds")
                    to_notify.append((alert, ltp))

        if to_notify:
            self._save()
            for alert, price in to_notify:
                self._notify(alert, ltp=price)

    def start_polling(self, interval: int = 60) -> None:
        """Start background alert checking (daemon thread). Fallback when no WebSocket."""
        if self._polling:
            return
        self._polling = True
        self._stop_event.clear()
        self._poller_thread = threading.Thread(
            target=self._poll_loop,
            args=(interval,),
            daemon=True,
        )
        self._poller_thread.start()

    def stop_polling(self) -> None:
        """Stop background alert checking immediately and join cleanly."""
        self._polling = False
        self._stop_event.set()
        if self._poller_thread and self._poller_thread.is_alive():
            try:
                self._poller_thread.join(timeout=1.0)
            except Exception:
                pass
        self._poller_thread = None

    def check_alerts(self) -> list[Alert]:
        """Check all active alerts and return any that just triggered."""
        triggered: list[Alert] = []
        for alert in self._alerts:
            if alert.triggered:
                continue
            if not _is_market_hours(alert.exchange):
                continue
            try:
                if self._evaluate(alert):
                    alert.triggered = True
                    alert.triggered_at = datetime.now().isoformat(timespec="seconds")
                    triggered.append(alert)
            except Exception:
                pass  # Skip alerts that fail to evaluate (broker down, etc.)
        if triggered:
            self._save()
        return triggered

    # ── Private ───────────────────────────────────────────────

    def _auto_subscribe(self, alert: Alert) -> None:
        """Auto-subscribe the alert's symbol to WebSocket for real-time ticks."""
        try:
            from market.websocket import ws_manager

            if ws_manager.connected:
                ws_manager.subscribe([f"{alert.exchange}:{alert.symbol}"])
        except Exception:
            pass

    def _poll_loop(self, interval: int) -> None:
        while self._polling and not self._stop_event.is_set():
            if self.active_count() > 0 and (
                _is_market_hours("NSE")
                or _is_market_hours("CDS")
                or _is_market_hours("MCX")
            ):
                # Check for triggered alerts
                triggered = self.check_alerts()
                for alert in triggered:
                    self._notify(alert)
                # Check for invalidated alerts
                self.check_invalidations()
            if self._stop_event.wait(timeout=interval):
                break

    def check_invalidations(self) -> list[Alert]:
        """Check active alerts for invalidations (e.g. stop-loss floor/ceiling reached)."""
        from market.quotes import get_ltp

        invalidated: list[Alert] = []
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            for alert in self._alerts:
                if alert.triggered or alert.is_invalidated:
                    continue
                if not _is_market_hours(alert.exchange):
                    continue
                if alert.invalidation_threshold is None:
                    continue

                try:
                    current_ltp = get_ltp(f"{alert.exchange}:{alert.symbol}")
                    if not current_ltp or current_ltp <= 0:
                        continue

                    # If watching ABOVE (bullish), invalidation is drop BELOW invalidation_threshold
                    if alert.condition == "ABOVE" and current_ltp <= alert.invalidation_threshold:
                        alert.is_invalidated = True
                        alert.invalidated_at = now_iso
                        alert.invalidation_reason = (
                            f"Price dropped to ₹{current_ltp:,.2f} (below invalidation floor ₹{alert.invalidation_threshold:,.2f}). "
                            f"Breakout alert above ₹{alert.threshold:,.2f} is invalidated."
                        )
                        invalidated.append(alert)
                    # If watching BELOW (bearish), invalidation is surge ABOVE invalidation_threshold
                    elif alert.condition == "BELOW" and current_ltp >= alert.invalidation_threshold:
                        alert.is_invalidated = True
                        alert.invalidated_at = now_iso
                        alert.invalidation_reason = (
                            f"Price surged to ₹{current_ltp:,.2f} (above invalidation ceiling ₹{alert.invalidation_threshold:,.2f}). "
                            f"Breakdown alert below ₹{alert.threshold:,.2f} is invalidated."
                        )
                        invalidated.append(alert)
                except Exception:
                    pass

        if invalidated:
            self._save()
            for a in invalidated:
                self._notify(a)
        return invalidated

    def create_test_alert(
        self,
        symbol: str = "INFY",
        condition: str = "ABOVE",
        threshold: float = 1850.0,
        is_invalidation: bool = False,
    ) -> Alert:
        """Create and trigger a simulated test alert clearly marked [TEST]."""
        now_iso = datetime.now().isoformat(timespec="seconds")
        alert = Alert(
            id=f"test-{uuid.uuid4().hex[:6]}",
            alert_type="PRICE",
            symbol=symbol.upper(),
            exchange="NSE",
            condition=condition.upper(),
            threshold=float(threshold),
            created_at=now_iso,
            triggered=not is_invalidation,
            triggered_at=now_iso if not is_invalidation else None,
            is_live=False,
            environment="TEST",
            is_invalidated=is_invalidation,
            invalidation_reason="[TEST SIMULATION] Stop level breached. Alert setup is invalidated."
            if is_invalidation
            else None,
            invalidated_at=now_iso if is_invalidation else None,
        )
        alert.message = f"[TEST] {alert.describe()}"
        with self._lock:
            self._alerts.append(alert)
            self._save()
        self._notify(alert, ltp=threshold)
        return alert

    def _notify(self, alert: Alert, ltp: Optional[float] = None) -> None:
        """
        Multi-channel alert notification with explicit REAL/LIVE vs TEST tagging
        and prominent Invalidation warning if the view/alert is no longer valid.
        """
        desc = alert.describe()
        ltp_str = f"  LTP: ₹{ltp:,.2f}" if ltp else ""
        is_test = (alert.environment == "TEST") or (not alert.is_live)
        in_market = _is_market_hours(alert.exchange)

        if is_test:
            env_tag = "[TEST]"
        elif not in_market:
            env_tag = "[OFF-MARKET]"
        else:
            env_tag = "[REAL/LIVE]"

        if alert.is_invalidated:
            panel_title = f"[bold red]⚠️ {env_tag} ALERT / VIEW INVALIDATED[/bold red]"
            desktop_title = f"⚠️ {env_tag} VIEW INVALIDATED: {alert.symbol}"
            desktop_msg = alert.invalidation_reason or f"{desc} is no longer valid."
            from bot.alert_templates import render_milestone_alert, MilestoneAlertData

            tg_msg = render_milestone_alert(
                MilestoneAlertData(
                    milestone_type="INVALIDATED",
                    symbol=alert.symbol,
                    alert_type=alert.alert_type,
                    invalidation_reason=alert.invalidation_reason or desc,
                    environment=alert.environment,
                    in_market=in_market,
                    timestamp=alert.invalidated_at or alert.created_at,
                ),
                in_market=in_market,
            )
            headline = f"⚠️ {env_tag} VIEW INVALIDATED: {alert.symbol} {alert.alert_type}"
            summary = alert.invalidation_reason or f"{desc} is no longer valid."
            border_style = "red"
            sys_type = "invalidation_alert"
        elif alert.target_achieved:
            panel_title = f"[bold cyan]🎯 {env_tag} TARGET ACHIEVED[/bold cyan]"
            desktop_title = f"🎯 {env_tag} TARGET HIT: {alert.symbol}"
            desktop_msg = (
                alert.trailing_rationale
                or f"{desc} reached target price ₹{alert.target_price or alert.threshold:,.2f}!"
            )
            from bot.alert_templates import render_milestone_alert, MilestoneAlertData

            tg_msg = render_milestone_alert(
                MilestoneAlertData(
                    milestone_type="FINAL_TARGET",
                    symbol=alert.symbol,
                    alert_type=alert.alert_type,
                    ltp=ltp or alert.threshold,
                    target_level=alert.target_price or alert.threshold,
                    trailing_stop=alert.trailing_stop,
                    decisive_action=alert.trailing_decision or "BOOK_50_TRAIL_BREAKEVEN",
                    rationale=alert.trailing_rationale or desc,
                    should_trail=alert.should_trail,
                    environment=alert.environment,
                    in_market=in_market,
                    timestamp=alert.triggered_at or alert.created_at,
                ),
                in_market=in_market,
            )
            headline = f"🎯 {env_tag} TARGET ACHIEVED: {alert.symbol} {alert.alert_type}"
            summary = alert.trailing_rationale or f"{desc} hit target price!"
            border_style = "cyan"
            sys_type = "target_achieved"
        else:
            panel_title = f"[bold {'magenta' if is_test else ('yellow' if not in_market else 'green')}]🔔 {env_tag} ALERT TRIGGERED[/bold {'magenta' if is_test else ('yellow' if not in_market else 'green')}]"
            desktop_title = f"{env_tag} Alert Triggered: {alert.symbol}"
            desktop_msg = f"{desc}{ltp_str}"
            from bot.alert_templates import render_price_alert

            tg_msg = render_price_alert(
                symbol=alert.symbol,
                condition_desc=f"{desc}{ltp_str}",
                environment=alert.environment,
                in_market=in_market,
            )
            headline = f"{env_tag} 🔔 {alert.symbol} {alert.alert_type} Alert Triggered"
            summary = f"{desc}{ltp_str}"
            border_style = "magenta" if is_test else ("yellow" if not in_market else "green")
            sys_type = "market_alert"

        now_stamp = (
            alert.triggered_at
            or alert.invalidated_at
            or alert.created_at
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        )

        # 1. Terminal
        console.print()
        console.print(
            Panel(
                f"[bold white]{desc}[/bold white]{ltp_str}\n\n[dim]🕒 Timestamp: {now_stamp}[/dim]",
                title=panel_title,
                border_style=border_style,
            )
        )
        print("\a", end="", flush=True)  # system bell

        # 2. macOS desktop notification
        _desktop_notify(
            title=desktop_title,
            message=desktop_msg,
        )

        # 3. Telegram push
        _telegram_notify(tg_msg)

        # 4. Webhook (OpenClaw / external agents)
        if alert.webhook_url:
            _webhook_notify(alert, ltp=ltp)

        # 5. Real-time SSE dispatch to React UI
        try:
            from web.sse import event_bus

            alert_payload = {
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "symbol": alert.symbol,
                "exchange": alert.exchange,
                "headline": headline,
                "description": desc,
                "summary": summary,
                "timestamp": now_stamp,
                "created_at": alert.created_at or now_stamp,
                "triggered_at": alert.triggered_at or alert.invalidated_at,
                "ltp": ltp or alert.threshold,
                "stage": "INVALIDATED"
                if alert.is_invalidated
                else ("TARGET_ACHIEVED" if alert.target_achieved else "TRIGGERED"),
                "is_live": not is_test,
                "environment": "TEST" if is_test else "LIVE",
                "env_tag": env_tag,
                "is_invalidated": alert.is_invalidated,
                "invalidation_reason": alert.invalidation_reason,
                "target_achieved": alert.target_achieved,
                "trailing_stop": alert.trailing_stop,
                "should_trail": alert.should_trail,
                "trailing_decision": alert.trailing_decision,
                "trailing_rationale": alert.trailing_rationale,
            }
            event_bus.publish_sync("alert", alert_payload)
            event_bus.publish_sync(
                "system",
                {
                    "type": sys_type,
                    "alert": alert_payload,
                    "is_invalidated": alert.is_invalidated,
                    "environment": alert.environment,
                },
            )
        except Exception:
            pass

    def _evaluate(self, alert: Alert) -> bool:
        """Check if an alert's condition is met right now."""
        if alert.alert_type == "PRICE":
            return self._check_price(alert)
        elif alert.alert_type == "TECHNICAL":
            return self._check_technical(alert)
        elif alert.alert_type == "CONDITIONAL":
            return self._check_conditional(alert)
        return False

    def _check_price(self, alert: Alert) -> bool:
        instrument = f"{alert.exchange}:{alert.symbol}"

        # Try WebSocket first (instant)
        try:
            from market.websocket import ws_manager

            ws_ltp = ws_manager.get_ltp(instrument)
            if ws_ltp and ws_ltp > 0:
                ltp = ws_ltp
            else:
                raise ValueError("no ws tick")
        except Exception:
            # Fall back to REST
            try:
                from market.quotes import get_ltp

                ltp = get_ltp(instrument)
            except Exception:
                return False

        if alert.condition == "ABOVE":
            return ltp >= alert.threshold
        elif alert.condition == "BELOW":
            return ltp <= alert.threshold
        elif alert.condition == "CROSSES":
            return ltp >= alert.threshold  # simplified: treated as ABOVE
        return False

    def _check_technical(self, alert: Alert) -> bool:
        from analysis.technical import analyse as tech_analyse

        snapshot = tech_analyse(alert.symbol, alert.exchange)
        indicator_key = (alert.indicator or "").upper()

        # Extract the indicator value from the TechnicalSnapshot
        value_map = {
            "RSI": getattr(snapshot, "rsi", None),
            "RSI14": getattr(snapshot, "rsi", None),
            "MACD": getattr(snapshot, "macd", None),
            "ADX": getattr(snapshot, "adx", None),
            "ATR": getattr(snapshot, "atr", None),
            "SCORE": getattr(snapshot, "score", None),
        }
        value = value_map.get(indicator_key)
        if value is None:
            return False

        if alert.condition == "ABOVE":
            return float(value) >= alert.threshold
        elif alert.condition == "BELOW":
            return float(value) <= alert.threshold
        return False

    def _check_conditional(self, alert: Alert) -> bool:
        """
        Check a conditional alert — ALL conditions must be true (AND logic).
        Each condition is either PRICE or TECHNICAL.
        """
        if not alert.conditions:
            return False

        from brokers.session import get_data_broker

        for cond_dict in alert.conditions:
            cond = AlertCondition(**cond_dict) if isinstance(cond_dict, dict) else cond_dict

            if cond.condition_type == "PRICE":
                try:
                    broker = get_data_broker()
                    instrument = f"{alert.exchange}:{alert.symbol}"
                    ltp = broker.get_ltp(instrument)
                except Exception:
                    try:
                        from market.quotes import get_ltp

                        ltp = get_ltp(f"{alert.exchange}:{alert.symbol}")
                    except Exception:
                        return False

                if cond.condition == "ABOVE" and ltp < cond.threshold:
                    return False
                elif cond.condition == "BELOW" and ltp > cond.threshold:
                    return False

            elif cond.condition_type == "TECHNICAL":
                try:
                    from analysis.technical import analyse as tech_analyse

                    snapshot = tech_analyse(alert.symbol, alert.exchange)
                    indicator_key = (cond.indicator or "").upper()
                    value_map = {
                        "RSI": getattr(snapshot, "rsi", None),
                        "MACD": getattr(snapshot, "macd", None),
                        "ADX": getattr(snapshot, "adx", None),
                        "ATR": getattr(snapshot, "atr", None),
                        "SCORE": getattr(snapshot, "score", None),
                    }
                    value = value_map.get(indicator_key)
                    if value is None:
                        return False

                    if cond.condition == "ABOVE" and float(value) < cond.threshold:
                        return False
                    elif cond.condition == "BELOW" and float(value) > cond.threshold:
                        return False
                except Exception:
                    return False

        return True  # all conditions passed

    # ── Persistence ───────────────────────────────────────────

    def _save(self) -> None:
        try:
            ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(a) for a in self._alerts]
            ALERTS_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load(self) -> None:
        try:
            if ALERTS_FILE.exists():
                data = json.loads(ALERTS_FILE.read_text())
                valid_keys = set(Alert.__dataclass_fields__.keys())
                self._alerts = [
                    Alert(**{k: v for k, v in d.items() if k in valid_keys})
                    for d in data
                    if isinstance(d, dict)
                ]
        except Exception:
            self._alerts = []


# ── Singleton ─────────────────────────────────────────────────

# ── Notification Helpers ──────────────────────────────────────


def _desktop_notify(title: str, message: str) -> None:
    """
    Send a macOS desktop notification via osascript.
    Non-blocking — runs in a background thread.
    Falls back silently on non-macOS systems.
    """
    import subprocess
    import sys

    if sys.platform != "darwin":
        return

    def _send():
        try:
            # Escape quotes for AppleScript
            t = title.replace('"', '\\"')
            m = message.replace('"', '\\"')
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{m}" with title "{t}" sound name "Glass"',
                ],
                timeout=5,
                capture_output=True,
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _telegram_notify(message: str) -> None:
    """
    Send a Telegram push notification.
    Non-blocking — runs in background thread.
    Never dispatches during test execution or test deployment modes.
    """
    import os
    if os.environ.get("CHANAKYA_TESTING") == "1" or os.environ.get("DEPLOY_MODE") == "test":
        return

    try:
        from bot.telegram_bot import send_push

        send_push(message)
    except Exception:
        pass


def _webhook_notify(alert: Alert, ltp: Optional[float] = None) -> None:
    """
    POST alert payload to the registered webhook_url.
    Non-blocking — runs in a background thread.
    """
    import json as _json

    def _send():
        try:
            import urllib.request

            # Resolve at send time as well as validating the supplied URL.
            # This blocks localhost, RFC1918 and cloud-metadata destinations.
            if not _resolves_to_public_address(alert.webhook_url):
                return

            payload = {
                "event": "alert_triggered",
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "symbol": alert.symbol,
                "exchange": alert.exchange,
                "description": alert.describe(),
                "triggered_at": alert.triggered_at,
                "ltp": ltp,
            }
            body = _json.dumps(payload).encode()
            signature_secret = getattr(alert, "webhook_secret", None)
            headers = {"Content-Type": "application/json"}
            if signature_secret:
                headers["X-Chanakya-Signature"] = (
                    "sha256="
                    + hmac.new(signature_secret.encode(), body, hashlib.sha256).hexdigest()
                )
            req = urllib.request.Request(
                alert.webhook_url,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as _:
                pass
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


alert_manager = AlertManager()
