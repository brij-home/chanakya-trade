"""
scripts/validate_fyers.py
─────────────────────────
Diagnostic and validation tool for Fyers API v3 integration in ChanakyaTrade.

Features:
  1. Inspects FYERS_APP_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URL in .env
  2. Verifies format (e.g. -100 suffix on App ID)
  3. Tests HTTP connectivity to Fyers auth endpoint (detects invalid clientId)
  4. Checks existing session token (~/.trading_platform/fyers.json)
  5. Optionally performs interactive OAuth login (--login) to authenticate & fetch live data

Usage:
  python scripts/validate_fyers.py
  python scripts/validate_fyers.py --login
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Ensure Windows UTF-8 encoding
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

# Load workspace .env
load_dotenv(REPO_ROOT / ".env")

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(legacy_windows=False)
TOKEN_FILE = Path.home() / ".trading_platform" / "fyers.json"
TOKEN_EXPIRY = 12 * 3600


def check_env_credentials() -> tuple[str, str, str, str, str, str, bool]:
    """Check .env credentials for Fyers."""
    app_id = os.environ.get("FYERS_APP_ID", "").strip()
    secret_key = os.environ.get("FYERS_SECRET_KEY", "").strip()
    redirect_uri = (
        os.environ.get("FYERS_REDIRECT_URL", "").strip() or "http://127.0.0.1:8765/fyers/callback"
    )
    fy_id = os.environ.get("FYERS_FY_ID", "").strip()
    totp_secret = os.environ.get("FYERS_TOTP_SECRET", "").strip()
    pin = os.environ.get("FYERS_PIN", "").strip()

    table = Table(title="Fyers Configuration Audit", border_style="cyan")
    table.add_column("Setting", style="bold white", width=22)
    table.add_column("Current Value", style="cyan", width=42)
    table.add_column("Status / Recommendation", style="white")

    is_ready = True

    # 1. APP ID
    if not app_id:
        table.add_row(
            "FYERS_APP_ID", "[red]MISSING[/red]", "[red]Required: App ID from myapi.fyers.in[/red]"
        )
        is_ready = False
    elif "-" not in app_id:
        normalized = f"{app_id}-100"
        table.add_row(
            "FYERS_APP_ID",
            f"[yellow]{app_id}[/yellow]",
            f"[yellow]Omitted '-100'. Fyers API v3 requires '{normalized}'. (Auto-handled)[/yellow]",
        )
    else:
        table.add_row(
            "FYERS_APP_ID", f"[green]{app_id}[/green]", "[green]Valid format (<ID>-100)[/green]"
        )

    # 2. SECRET KEY
    if not secret_key:
        table.add_row(
            "FYERS_SECRET_KEY",
            "[red]MISSING[/red]",
            "[red]Required: Secret Key from myapi.fyers.in[/red]",
        )
        is_ready = False
    else:
        masked = (
            secret_key[:4] + "*" * (len(secret_key) - 8) + secret_key[-4:]
            if len(secret_key) > 8
            else "****"
        )
        table.add_row("FYERS_SECRET_KEY", f"[green]{masked}[/green]", "[green]Configured[/green]")

    # 3. REDIRECT URI
    table.add_row(
        "FYERS_REDIRECT_URL",
        redirect_uri,
        "[green]Default: http://127.0.0.1:8765/fyers/callback[/green]"
        if "127.0.0.1" in redirect_uri or "localhost" in redirect_uri
        else "[yellow]Remote URL. Note: Exact match needed on myapi.fyers.in[/yellow]",
    )

    # 4. Auto-login credentials (all 3 or none)
    auto_login_ready = bool(fy_id and totp_secret and pin)
    table.add_row(
        "FYERS_FY_ID",
        f"[green]{fy_id}[/green]" if fy_id else "[dim]Not set[/dim]",
        "[green]Auto-login ready[/green]"
        if fy_id
        else "[dim]Optional — set for headless login[/dim]",
    )
    table.add_row(
        "FYERS_TOTP_SECRET",
        "[green]****[/green]" if totp_secret else "[dim]Not set[/dim]",
        "[green]Configured[/green]"
        if totp_secret
        else "[dim]Optional — set for headless login[/dim]",
    )
    table.add_row(
        "FYERS_PIN",
        "[green]****[/green]" if pin else "[dim]Not set[/dim]",
        "[green]Configured[/green]" if pin else "[dim]Optional — set for headless login[/dim]",
    )

    console.print(table)
    if auto_login_ready:
        console.print(
            "  [bold green]✓ Auto-login mode: ENABLED[/bold green] — will login silently via TOTP + PIN (no browser)"
        )
    else:
        console.print(
            "  [dim]Auto-login mode: DISABLED — set FYERS_FY_ID + FYERS_TOTP_SECRET + FYERS_PIN to enable[/dim]"
        )
    console.print()
    return app_id, secret_key, redirect_uri, fy_id, totp_secret, pin, is_ready


def test_auth_endpoint(app_id: str, secret_key: str, redirect_uri: str) -> bool:
    """Test generating auth URL and pinging Fyers authorization server."""
    from brokers.fyers import FyersAPI

    console.print("[bold cyan]Testing Fyers OAuth Endpoint Connectivity...[/bold cyan]")
    try:
        broker = FyersAPI(app_id=app_id, secret_key=secret_key, redirect_uri=redirect_uri)
        auth_url = broker.get_login_url()
        console.print(
            f"  [dim]Generated Auth URL:[/dim] [link={auth_url}]{auth_url[:80]}...[/link]"
        )

        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(auth_url)
            final_url = str(resp.url)

            if "invalid" in final_url.lower() and "clientid" in final_url.lower():
                console.print(
                    f"  [bold red]❌ Fyers rejected Client ID:[/bold red] {final_url}\n"
                    "  [yellow]Make sure your App ID has the '-100' suffix and exists in your myapi.fyers.in dashboard.[/yellow]"
                )
                return False
            elif resp.status_code == 200:
                console.print(
                    "  [bold green]✓ Fyers Auth endpoint accepted credentials successfully (HTTP 200).[/bold green]"
                )
                return True
            else:
                console.print(
                    f"  [yellow]Warning: Fyers endpoint returned HTTP {resp.status_code}.[/yellow]"
                )
                return True
    except Exception as exc:
        console.print(f"  [red]Failed to connect to Fyers: {exc}[/red]")
        return False


def check_existing_session() -> bool:
    """Check if token file exists and is still valid."""
    console.print("[bold cyan]Checking Active Fyers Session Token...[/bold cyan]")
    if not TOKEN_FILE.exists():
        console.print(
            "  [yellow]No existing token found (~/.trading_platform/fyers.json). Authentication required.[/yellow]"
        )
        return False

    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        ts = data.get("timestamp", 0)
        elapsed = time.time() - ts
        remaining = TOKEN_EXPIRY - elapsed

        if remaining <= 0:
            console.print("  [yellow]Token expired (>12 hours). Re-login required.[/yellow]")
            return False

        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        console.print(
            f"  [bold green]✓ Active token found (valid for another {hours}h {mins}m).[/bold green]"
        )
        return True
    except Exception as exc:
        console.print(f"  [yellow]Error reading token file: {exc}[/yellow]")
        return False


def test_live_data(app_id: str, secret_key: str, redirect_uri: str) -> None:
    """Test live data fetch with authenticated Fyers session."""
    from brokers.fyers import FyersAPI

    console.print("\n[bold cyan]Fetching Live Data from Fyers...[/bold cyan]")
    try:
        broker = FyersAPI(app_id=app_id, secret_key=secret_key, redirect_uri=redirect_uri)
        if not broker.is_authenticated():
            console.print("  [yellow]Broker is not authenticated yet.[/yellow]")
            return

        # Profile
        profile = broker.get_profile()
        console.print(
            f"  [green]✓ Profile:[/green] {profile.user_id} ({profile.name}) | Email: {profile.email}"
        )

        # Funds
        funds = broker.get_funds()
        console.print(
            f"  [green]✓ Funds:[/green] Available Cash: ₹{funds.available_cash:,.2f} | Total: ₹{funds.total_balance:,.2f}"
        )

        # Quotes
        symbols = ["NSE:NIFTY50-INDEX", "NSE:RELIANCE-EQ"]
        quotes = broker.get_quote(symbols)
        for sym, q in quotes.items():
            ch_color = "green" if q.change >= 0 else "red"
            sign = "+" if q.change >= 0 else ""
            console.print(
                f"  [green]✓ Quote {sym}:[/green] ₹{q.last_price:,.2f} ([{ch_color}]{sign}{q.change:,.2f} / {sign}{q.change_pct:.2f}%[/{ch_color}])"
            )

        console.print(
            "\n[bold green]🎉 All Fyers checks passed! Connection is fully operational.[/bold green]"
        )
    except Exception as exc:
        console.print(f"  [red]Failed to fetch live data: {exc}[/red]")


def run_interactive_login(
    app_id: str,
    secret_key: str,
    redirect_uri: str,
    fy_id: str = "",
    totp_secret: str = "",
    pin: str = "",
) -> None:
    """Run Fyers login — headless auto-login if TOTP creds present, else browser OAuth."""
    from brokers.session import login

    if fy_id and totp_secret and pin:
        console.print("\n[bold cyan]Starting Headless Auto-Login (TOTP + PIN)...[/bold cyan]")
        from brokers.fyers import FyersAPI

        try:
            b = FyersAPI(
                app_id=app_id,
                secret_key=secret_key,
                redirect_uri=redirect_uri,
                fy_id=fy_id,
                totp_secret=totp_secret,
                pin=pin,
            )
            profile = b.complete_login()
            console.print(
                f"  [bold green]✓ Logged in:[/bold green] {profile.user_id} ({profile.name})"
            )
            test_live_data(app_id, secret_key, redirect_uri)
        except Exception as exc:
            console.print(f"[bold red]Auto-login failed: {exc}[/bold red]")
    else:
        console.print("\n[bold cyan]Starting Interactive Browser OAuth Login...[/bold cyan]")
        try:
            broker = login("fyers")
            if broker and broker.is_authenticated():
                test_live_data(app_id, secret_key, redirect_uri)
        except Exception as exc:
            console.print(f"[bold red]Login failed: {exc}[/bold red]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Fyers API credentials and connection.")
    parser.add_argument(
        "--login",
        action="store_true",
        help="Authenticate Fyers (auto-login if TOTP creds set, else browser OAuth)",
    )
    args = parser.parse_args()

    console.print(
        Panel.fit(
            "[bold gold1]ChanakyaTrade[/bold gold1] — [bold cyan]Fyers API v3 Connection Validator[/bold cyan]",
            border_style="cyan",
        )
    )

    app_id, secret_key, redirect_uri, fy_id, totp_secret, pin, is_ready = check_env_credentials()

    if not is_ready:
        console.print(
            "[bold red]Please update your .env file with valid FYERS_APP_ID and FYERS_SECRET_KEY.[/bold red]\n"
            "Steps:\n"
            "  1. Go to https://myapi.fyers.in\n"
            "  2. Create an App with Redirect URL: http://127.0.0.1:8765/fyers/callback\n"
            "  3. Copy your App ID (with -100) and Secret Key into .env\n"
        )
        sys.exit(1)

    endpoint_ok = test_auth_endpoint(app_id, secret_key, redirect_uri)
    if not endpoint_ok:
        sys.exit(1)

    session_ok = check_existing_session()

    if session_ok:
        test_live_data(app_id, secret_key, redirect_uri)
    elif args.login:
        run_interactive_login(app_id, secret_key, redirect_uri, fy_id, totp_secret, pin)
    else:
        auto_hint = (
            (
                "\n[bold green]Auto-login credentials detected![/bold green] Run with --login to authenticate headlessly:"
                "\n  [bold cyan]python scripts/validate_fyers.py --login[/bold cyan]"
            )
            if (fy_id and totp_secret and pin)
            else (
                "\n[bold yellow]Next Step:[/bold yellow] To authenticate via browser, run:"
                "\n  [bold cyan]python scripts/validate_fyers.py --login[/bold cyan]"
                "\n\nOr add FYERS_FY_ID + FYERS_TOTP_SECRET + FYERS_PIN to .env for fully headless login."
            )
        )
        console.print(
            auto_hint + "\n\nOr start ChanakyaTrade directly and select Fyers from the login menu:"
            "\n  [bold cyan]python -m app.main[/bold cyan]\n"
        )


if __name__ == "__main__":
    main()
