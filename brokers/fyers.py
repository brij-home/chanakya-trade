"""
brokers/fyers.py
─────────────────
Fyers API v3 implementation of BrokerAPI using the official fyers-apiv3 SDK.

Fyers offers a free developer API with excellent options chain data
and live market feeds. No monthly subscription fee.

Credentials needed (store via `credentials setup`):
    FYERS_APP_ID       — App ID from myapi.fyers.in (format: XXXX-100)
    FYERS_SECRET_KEY   — Client secret from app dashboard
    FYERS_REDIRECT_URL — Registered redirect URI
                         (default: http://127.0.0.1:8765/fyers/callback)

Auto-Login (headless / no browser needed) — set ALL THREE:
    FYERS_FY_ID        — Your Fyers client login ID (e.g. XA12345)
    FYERS_TOTP_SECRET  — Base32 TOTP secret from Fyers security settings
    FYERS_PIN          — Your Fyers 4/6-digit trading PIN

    When all three are present, complete_login() will authenticate silently
    via Fyers' vagator API (TOTP + PIN), skipping the browser redirect.
    This is identical to the approach at:
    https://github.com/sainipankaj15/brokers-auto-login/tree/main/Fyers

Fallback login flow (browser OAuth):
  1. `get_login_url()` returns the Fyers auth URL
  2. User logs in via browser → redirected with ?auth_code=...&state=...
  3. `complete_login(auth_code=...)` exchanges code for access token

Session token is saved to ~/.trading_platform/fyers.json and reused (12h TTL).

Install: pip install fyers-apiv3 pyotp

Docs: https://myapi.fyers.in/docsv3
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from brokers.base import (
    BrokerAPI,
    UserProfile,
    Funds,
    Holding,
    Position,
    Quote,
    OptionsContract,
    OrderRequest,
    OrderResponse,
    Order,
)

TOKEN_FILE = Path.home() / ".trading_platform" / "fyers.json"
TOKEN_EXPIRY = 12 * 3600  # Fyers tokens valid ~12 h

# ── Symbol mapping (instrument format → Fyers format) ────────

_FYERS_INDEX_MAP = {
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "NIFTY BANK": "NSE:NIFTYBANK-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "INDIA VIX": "NSE:INDIAVIX-INDEX",
    "VIX": "NSE:INDIAVIX-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "BSE:SENSEX": "BSE:SENSEX-INDEX",
    "BANKEX": "BSE:BANKEX-INDEX",
    "BSE:BANKEX": "BSE:BANKEX-INDEX",
    "NIFTY IT": "NSE:NIFTYIT-INDEX",
    "NIFTY PHARMA": "NSE:NIFTYPHARMA-INDEX",
    "NIFTY AUTO": "NSE:NIFTYAUTO-INDEX",
    "NIFTY FMCG": "NSE:NIFTYFMCG-INDEX",
    "NIFTY REALTY": "NSE:NIFTYREALTY-INDEX",
    "NIFTY METAL": "NSE:NIFTYMETAL-INDEX",
    "NIFTY ENERGY": "NSE:NIFTYENERGY-INDEX",
    "NIFTY FIN SERVICE": "NSE:FINNIFTY-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "NIFTY MIDCAP 100": "NSE:NIFTYMIDCAP100-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "NIFTY MID SELECT": "NSE:MIDCPNIFTY-INDEX",
    "NSE:NIFTY MID SELECT": "NSE:MIDCPNIFTY-INDEX",
}

_INDEX_PREFIXES = (
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
    "INDIAVIX",
)



_MONTH_MAP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
    "1": "01",
    "2": "02",
    "3": "03",
    "4": "04",
    "5": "05",
    "6": "06",
    "7": "07",
    "8": "08",
    "9": "09",
    "10": "10",
    "11": "11",
    "12": "12",
}

_WEEKLY_MONTH_MAP = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "O": 10, "N": 11, "D": 12,
}


def _parse_expiry_from_fyers_symbol(symbol: str, option_type: str = "") -> str:
    """
    Parse expiry date from a Fyers option symbol string.

    Fyers weekly format :
      - Jan-Sep: NSE:NIFTY2640722100CE → YY=26, M=4, DD=07 → 2026-04-07
      - Oct-Dec: NSE:NIFTY26O0824000CE → YY=26, M=O (Oct), DD=08 → 2026-10-08
      - Nov:     NSE:NIFTY26N1524000CE → YY=26, M=N (Nov), DD=15 → 2026-11-15
      - Dec:     NSE:NIFTY26D2424000CE → YY=26, M=D (Dec), DD=24 → 2026-12-24
    Fyers monthly format: NSE:NIFTY26APR22100CE → YY=26, MMM=APR, last Thursday
    Returns YYYY-MM-DD string or empty string on failure.
    """
    import re
    import datetime as dt
    from calendar import monthrange

    try:
        sym = re.sub(r"^[A-Z]+:", "", symbol)  # strip "NSE:"
        sym = re.sub(r"(CE|PE)$", "", sym)  # strip option type

        # Match: underlying + YY(2 digits) + date_part + strike(digits)
        # Monthly: 3 letters; Weekly: [1-9OND] + 2 digits, or 4 digits
        m = re.match(r"^[A-Za-z0-9_&]+?(\d{2})([A-Za-z]{3}|[1-9ONDond]\d{2}|\d{4})(\d+)$", sym)
        if not m:
            return ""
        yy, date_part, _ = m.groups()
        year = int("20" + yy)

        # Monthly: 3-letter month e.g. APR, OCT
        if re.match(r"^[A-Za-z]{3}$", date_part):
            month = int(_MONTH_MAP.get(date_part.lower(), "0"))
            if not month:
                return ""
            days = monthrange(year, month)[1]
            d = dt.date(year, month, days)
            while d.weekday() != 3:  # last Thursday
                d -= dt.timedelta(days=1)
            return d.strftime("%Y-%m-%d")

        # Weekly single-char month code (1-9, O=Oct, N=Nov, D=Dec) + 2-digit day
        # e.g. "O08" -> month 10, day 08; "407" -> month 4, day 07
        if len(date_part) == 3:
            code = date_part[0].upper()
            if code in _WEEKLY_MONTH_MAP:
                m_val = _WEEKLY_MONTH_MAP[code]
                d_val = int(date_part[1:3])
                if 1 <= d_val <= 31:
                    return dt.date(year, m_val, d_val).strftime("%Y-%m-%d")

        # 4-digit e.g. "1024" = month=10, day=24
        if len(date_part) == 4:
            m4 = int(date_part[:2])
            d4 = int(date_part[2:])
            if 1 <= m4 <= 12 and 1 <= d4 <= 31:
                return dt.date(year, m4, d4).strftime("%Y-%m-%d")
    except Exception:
        pass
    return ""


# ── Precision Order Utilities (Decimal Tick Rounding & Lot Validation) ─────────

def round_price_to_tick(price: float | None, tick_size: float = 0.05) -> float:
    """
    Round price to the nearest valid tick increment using Decimal arithmetic.
    Eliminates IEEE 754 floating-point drift (e.g. 805.0500000000001) that triggers
    Fyers API -50 'invalid parameter' or -300 rejections.
    """
    if price is None or price <= 0:
        return 0.0
    if tick_size <= 0:
        return float(price)
    tick = Decimal(str(tick_size))
    p = Decimal(str(price))
    rounded = (p / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
    return float(rounded)


def validate_lot_qty(qty: int, lot_size: int = 1) -> None:
    """Raise ValueError if qty is not a non-zero positive multiple of lot_size."""
    if lot_size <= 0:
        raise ValueError(f"lot_size must be positive, got {lot_size}")
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if qty % lot_size != 0:
        raise ValueError(
            f"qty {qty} is not a multiple of lot size {lot_size}; "
            f"nearest valid lots: {(qty // lot_size) * lot_size} or "
            f"{(qty // lot_size + 1) * lot_size}"
        )


def round_qty_to_lot(qty: int, lot_size: int = 1) -> int:
    """Round qty DOWN to nearest valid lot multiple. Raises ValueError if result is 0."""
    if lot_size <= 0:
        raise ValueError(f"lot_size must be positive, got {lot_size}")
    rounded = (qty // lot_size) * lot_size
    if rounded <= 0:
        raise ValueError(f"qty {qty} is smaller than one lot ({lot_size}); cannot round down")
    return rounded


from market.fyers_circuit_breaker import get_fyers_circuit_breaker
from market.fyers_rate_gate import FyersCallCategory, UnifiedFyersRateGate, get_fyers_rate_gate


class FyersRateLimiter:
    """
    Thread-safe client-side sliding-window rate limiter for Fyers API v3.
    Delegates to UnifiedFyersRateGate for cross-module coordination and prioritization.
    """

    def __init__(self, max_per_sec: float = 8.0, max_per_min: float = 160.0):
        self._gate = UnifiedFyersRateGate(max_per_sec=max_per_sec, max_per_min=max_per_min)

    def acquire(self, category: Any = None, timeout: Optional[float] = None) -> bool:
        if category is None:
            category = FyersCallCategory.ORDER
        return self._gate.acquire(category=category, timeout=timeout)


_fyers_rate_limiter = get_fyers_rate_gate()


def _resolve_commodity_contract(symbol: str) -> str:
    """
    Resolve generic commodity symbol (e.g. 'GOLD', 'CRUDEOIL', 'SILVER', 'NATURALGAS')
    to the active near-month Fyers MCX futures contract symbol.
    """
    import datetime as dt

    now = dt.datetime.now()
    clean = symbol.upper().replace("MCX:", "").strip()

    # CRUDEOIL: monthly, expires ~19th of each month
    if clean in ("CRUDEOIL", "CRUDEOILM"):
        target_dt = now if now.day <= 18 else now + dt.timedelta(days=20)
        return f"MCX:{clean}{target_dt.strftime('%y%b').upper()}FUT"

    # NATURALGAS: monthly, expires ~25th of each month
    if clean in ("NATURALGAS", "NATURALGASM"):
        target_dt = now if now.day <= 24 else now + dt.timedelta(days=15)
        return f"MCX:{clean}{target_dt.strftime('%y%b').upper()}FUT"

    # GOLD: active contract months: FEB(2), APR(4), JUN(6), AUG(8), OCT(10), DEC(12)
    if clean == "GOLD":
        gold_months = [2, 4, 6, 8, 10, 12]
        cand_m = now.month if (now.month in gold_months and now.day <= 3) else None
        if not cand_m:
            future_m = [m for m in gold_months if m > now.month]
            cand_m = future_m[0] if future_m else gold_months[0]
            target_year = now.year if future_m else now.year + 1
        else:
            target_year = now.year
        target_dt = dt.date(target_year, cand_m, 1)
        return f"MCX:GOLD{target_dt.strftime('%y%b').upper()}FUT"

    # GOLDM: monthly
    if clean == "GOLDM":
        target_dt = now if now.day <= 4 else now + dt.timedelta(days=30)
        return f"MCX:GOLDM{target_dt.strftime('%y%b').upper()}FUT"

    # SILVER: active contract months: MAR(3), MAY(5), JUL(7), SEP(9), DEC(12)
    if clean == "SILVER":
        silver_months = [3, 5, 7, 9, 12]
        cand_m = now.month if (now.month in silver_months and now.day <= 3) else None
        if not cand_m:
            future_m = [m for m in silver_months if m > now.month]
            cand_m = future_m[0] if future_m else silver_months[0]
            target_year = now.year if future_m else now.year + 1
        else:
            target_year = now.year
        target_dt = dt.date(target_year, cand_m, 1)
        return f"MCX:SILVER{target_dt.strftime('%y%b').upper()}FUT"

    # SILVERM (Silver Mini): active contract months: FEB(2), APR(4), JUN(6), AUG(8), NOV(11)
    if clean in ("SILVERM", "SILMIC"):
        silverm_months = [2, 4, 6, 8, 11]
        cand_m = now.month if (now.month in silverm_months and now.day <= 3) else None
        if not cand_m:
            future_m = [m for m in silverm_months if m > now.month]
            cand_m = future_m[0] if future_m else silverm_months[0]
            target_year = now.year if future_m else now.year + 1
        else:
            target_year = now.year
        target_dt = dt.date(target_year, cand_m, 1)
        return f"MCX:{clean}{target_dt.strftime('%y%b').upper()}FUT"

    # COPPER, ZINC, ALUMINIUM: monthly
    if clean in ("COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL"):
        target_dt = now if now.day <= 26 else now + dt.timedelta(days=10)
        return f"MCX:{clean}{target_dt.strftime('%y%b').upper()}FUT"

    # Default fallback: current month
    return f"MCX:{clean}{now.strftime('%y%b').upper()}FUT"


def _resolve_currency_contract(symbol: str) -> str:
    """
    Resolve generic currency symbol (e.g. 'USDINR', 'EURINR')
    to the active Fyers NSE near-month currency futures contract symbol.
    """
    import datetime as dt

    now = dt.datetime.now()
    clean = symbol.upper().replace("CDS:", "").replace("NSE:", "").strip()
    target_dt = now if now.day <= 26 else now + dt.timedelta(days=10)
    return f"NSE:{clean}{target_dt.strftime('%y%b').upper()}FUT"


def _to_fyers_symbol(instrument: str) -> str:
    """Convert any instrument format ('NSE:RELIANCE', 'GOLD', 'USDINR', 'NIFTY') to Fyers API format."""
    s = str(instrument).strip()
    if ":" in s:
        exch, sym = s.split(":", 1)
    else:
        exch, sym = "NSE", s

    exch_upper = exch.upper().strip()
    sym_upper = sym.upper().strip()

    # Direct index map check
    if sym_upper in _FYERS_INDEX_MAP:
        return _FYERS_INDEX_MAP[sym_upper]

    if s.upper() in _FYERS_INDEX_MAP:
        return _FYERS_INDEX_MAP[s.upper()]

    # Already formatted with -INDEX, -EQ, etc.
    if "-" in sym:
        return f"{exch_upper}:{sym}"

    # MCX Commodities
    if exch_upper == "MCX" or sym_upper in (
        "GOLD",
        "GOLDM",
        "SILVER",
        "SILVERM",
        "CRUDEOIL",
        "CRUDEOILM",
        "NATURALGAS",
        "COPPER",
        "ZINC",
        "ALUMINIUM",
    ):
        if any(sym_upper.endswith(suffix) for suffix in ("FUT", "CE", "PE")) and any(
            c.isdigit() for c in sym_upper
        ):
            return f"MCX:{sym_upper}"
        return _resolve_commodity_contract(sym_upper)

    # Currency CDS / Forex
    if exch_upper in ("CDS", "FX", "FOREX") or sym_upper in (
        "USDINR",
        "EURINR",
        "GBPINR",
        "JPYINR",
    ):
        if any(sym_upper.endswith(suffix) for suffix in ("FUT", "CE", "PE")) and any(
            c.isdigit() for c in sym_upper
        ):
            return f"NSE:{sym_upper}"
        return _resolve_currency_contract(sym_upper)

    # F&O derivative contract on NSE/NFO or BSE/BFO (e.g. NIFTY26OCT25000CE, SENSEX26O0872000PE, RELIANCE26OCTFUT)
    if any(sym_upper.endswith(suffix) for suffix in ("FUT", "CE", "PE")) and any(
        c.isdigit() for c in sym_upper
    ):
        if exch_upper in ("BSE", "BFO") or any(sym_upper.startswith(x) for x in ("SENSEX", "BANKEX")):
            return f"BSE:{sym_upper}"
        if exch_upper == "MCX":
            return f"MCX:{sym_upper}"
        return f"NSE:{sym_upper}"

    # Check if index by explicit prefixes (only if not an option/futures contract)
    clean = sym_upper.replace(" ", "")
    if clean.startswith(_INDEX_PREFIXES) or clean in ("VIX", "INDIAVIX"):
        return f"{exch_upper}:{clean}-INDEX"

    # BSE Equity
    if exch_upper == "BSE":
        return f"BSE:{sym_upper}"

    return f"NSE:{sym_upper}-EQ"


def _get_sdk():
    """Lazy import fyers SDK."""
    try:
        from fyers_apiv3 import fyersModel

        return fyersModel
    except ImportError:
        raise RuntimeError("fyers-apiv3 not installed. Run:\n  pip install fyers-apiv3")


class FyersAPI(BrokerAPI):
    """
    Fyers API v3 broker — free, excellent options data.
    Uses the official fyers-apiv3 SDK for all API calls.

    Docs: https://myapi.fyers.in/docsv3
    """

    def __init__(
        self,
        app_id: str = "",
        secret_key: str = "",
        redirect_uri: str = "http://127.0.0.1:8765/fyers/callback",
        fy_id: str = "",
        totp_secret: str = "",
        pin: str = "",
    ) -> None:
        import os
        from config.credentials import get_credential

        # Auto-load from config/credentials or environment if not passed
        if not app_id:
            try:
                from dotenv import load_dotenv
                from pathlib import Path

                load_dotenv(Path(__file__).parent.parent / ".env")
            except Exception:
                pass

        app_id = (
            app_id
            or get_credential("FYERS_APP_ID", secret=False, required=False)
            or os.environ.get("FYERS_APP_ID", "")
        ).strip()
        secret_key = (
            secret_key
            or get_credential("FYERS_SECRET_KEY", secret=True, required=False)
            or os.environ.get("FYERS_SECRET_KEY", "")
        ).strip()
        fy_id = (
            fy_id
            or get_credential("FYERS_FY_ID", secret=False, required=False)
            or os.environ.get("FYERS_FY_ID", "")
        ).strip()
        totp_secret = (
            totp_secret
            or get_credential("FYERS_TOTP_SECRET", secret=True, required=False)
            or os.environ.get("FYERS_TOTP_SECRET", "")
        ).strip()
        pin = (
            pin
            or get_credential("FYERS_PIN", secret=True, required=False)
            or os.environ.get("FYERS_PIN", "")
        ).strip()
        # Fyers API v3 requires client_id / app_id in format <APP_ID>-100 or <APP_ID>-200
        if app_id and "-" not in app_id:
            app_id = f"{app_id}-100"
        self._app_id = app_id
        self._secret_key = secret_key
        redirect_uri = (
            redirect_uri
            or get_credential("FYERS_REDIRECT_URL", secret=False, required=False)
            or get_credential("FYERS_REDIRECT_URI", secret=False, required=False)
            or os.environ.get("FYERS_REDIRECT_URL", "")
            or os.environ.get("FYERS_REDIRECT_URI", "")
        ).strip()
        if fy_id and totp_secret and pin and (not redirect_uri or redirect_uri == "http://127.0.0.1:8765/fyers/callback"):
            redirect_uri = "https://trade.fyers.in/api-login/redirect-uri/index.html"
        self._redirect_uri = (redirect_uri or "https://trade.fyers.in/api-login/redirect-uri/index.html").strip()
        # Auto-login credentials (headless TOTP flow)
        self._fy_id = fy_id
        self._totp_secret = totp_secret
        self._pin = pin
        self._access_token = ""
        self._profile: Optional[UserProfile] = None
        self._token_ts: float = 0.0
        self._fyers = None  # FyersModel instance
        self._last_oc_metadata: dict[str, Any] = {}
        self.name: str = "fyers"
        self._load_token()

    # ── SDK Instance ─────────────────────────────────────────

    def _get_fyers(self):
        """Get or create the FyersModel SDK instance."""
        if self._fyers is None and self._access_token:
            fyersModel = _get_sdk()
            self._fyers = fyersModel.FyersModel(
                token=self._access_token,
                client_id=self._app_id,
                log_path="",
            )
        return self._fyers

    # ── Token persistence ──────────────────────────────────────

    def _load_token(self) -> None:
        try:
            if TOKEN_FILE.exists():
                data = json.loads(TOKEN_FILE.read_text())
                ts = data.get("timestamp", 0)
                if time.time() - ts < TOKEN_EXPIRY:
                    self._access_token = data.get("access_token", "")
                    self._token_ts = ts
                    if not self._app_id and data.get("app_id"):
                        self._app_id = data.get("app_id")
        except Exception:
            pass

    def _save_token(self, token: str) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "access_token": token,
                    "app_id": self._app_id,
                    "timestamp": time.time(),
                }
            )
        )

    # ── Auth ──────────────────────────────────────────────────

    def get_login_url(self) -> str:
        """Returns the Fyers OAuth2 authorization URL using the official SDK."""
        fyersModel = _get_sdk()
        session = fyersModel.SessionModel(
            client_id=self._app_id,
            secret_key=self._secret_key,
            redirect_uri=self._redirect_uri,
            response_type="code",
            grant_type="authorization_code",
            state="chanakya_trade",
        )
        return session.generate_authcode()

    # ── Headless Auto-Login (TOTP + PIN via vagator API) ──────

    def _auto_login_totp(self) -> str:
        """
        Headless Fyers login using TOTP + PIN.

        Replicates the flow from:
        https://github.com/sainipankaj15/brokers-auto-login/tree/main/Fyers

        Flow:
          1. POST /vagator/v2/send_login_otp  → get request_key (app_id="2" for web login)
          2. Generate TOTP from secret via pyotp
          3. POST /vagator/v2/verify_otp      → get request_key_2
          4. POST /vagator/v2/verify_pin      → get intermediate bearer access_token (plain PIN)
          5. POST /api/v3/token (Bearer auth) → HTTP 308 redirect Url containing auth_code
          6. POST /api/v3/validate-authcode   → exchange auth_code + appIdHash for final access token

        Returns the access token string.
        Raises RuntimeError on any step failure.
        """
        import hashlib
        from urllib import parse
        try:
            import pyotp
        except ImportError:
            raise RuntimeError(
                "pyotp not installed. Run: pip install pyotp"
            )
        try:
            import requests as _req
        except ImportError:
            raise RuntimeError(
                "requests not installed. Run: pip install requests"
            )

        # Derive the bare app_id (strip the -100/-200 suffix for vagator hash)
        bare_app_id = self._app_id.split("-")[0] if "-" in self._app_id else self._app_id
        app_type = self._app_id.split("-")[1] if "-" in self._app_id else "100"

        # Compute SHA-256 hash: "<bare_app_id>-<app_type>:<secret>"
        app_id_hash = hashlib.sha256(
            f"{bare_app_id}-{app_type}:{self._secret_key}".encode()
        ).hexdigest()

        BASE_VAGATOR = "https://api-t2.fyers.in/vagator/v2"
        BASE_API = "https://api-t1.fyers.in/api/v3"
        headers = {"Content-Type": "application/json"}

        # ── Step 1: Send login OTP (initiates session, gets request_key) ─
        # app_id here is APP_ID_TYPE = "2" (web login), per Fyers vagator spec.
        r1 = _req.post(
            f"{BASE_VAGATOR}/send_login_otp",
            json={"fy_id": self._fy_id, "app_id": "2"},
            headers=headers,
            timeout=15,
        )
        if r1.status_code != 200:
            raise RuntimeError(f"Fyers auto-login step 1 failed (HTTP {r1.status_code}): {r1.text}")
        data1 = r1.json()
        request_key = data1.get("request_key", "")
        if not request_key:
            raise RuntimeError(f"Fyers auto-login step 1: no request_key in response: {data1}")

        # ── Step 2: Verify TOTP ───────────────────────────────────────────
        totp = pyotp.TOTP(self._totp_secret).now()
        r2 = _req.post(
            f"{BASE_VAGATOR}/verify_otp",
            json={"request_key": request_key, "otp": totp},
            headers=headers,
            timeout=15,
        )
        if r2.status_code != 200:
            raise RuntimeError(f"Fyers auto-login step 2 (TOTP) failed (HTTP {r2.status_code}): {r2.text}")
        data2 = r2.json()
        request_key2 = data2.get("request_key", "")
        if not request_key2:
            raise RuntimeError(f"Fyers auto-login step 2: no request_key in response: {data2}")

        # ── Step 3: Verify PIN ────────────────────────────────────────────
        # Fyers vagator expects the PIN as PLAIN TEXT — NOT SHA-256 hashed.
        r3 = _req.post(
            f"{BASE_VAGATOR}/verify_pin",
            json={
                "request_key": request_key2,
                "identity_type": "pin",
                "identifier": self._pin,
            },
            headers=headers,
            timeout=15,
        )
        if r3.status_code != 200:
            raise RuntimeError(f"Fyers auto-login step 3 (PIN) failed (HTTP {r3.status_code}): {r3.text}")
        data3 = r3.json()
        intermediate_token = data3.get("data", {}).get("access_token", "")
        if not intermediate_token:
            raise RuntimeError(f"Fyers auto-login step 3: no access_token in response: {data3}")

        # ── Step 4: Generate OAuth auth_code via Bearer intermediate token ─
        r4 = _req.post(
            f"{BASE_API}/token",
            json={
                "fyers_id": self._fy_id,
                "app_id": bare_app_id,
                "redirect_uri": self._redirect_uri,
                "appType": app_type,
                "code_challenge": "",
                "state": "chanakya_trade",
                "scope": "",
                "nonce": "",
                "response_type": "code",
                "create_cookie": True,
            },
            headers={
                "Authorization": f"Bearer {intermediate_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if r4.status_code not in (200, 308):
            raise RuntimeError(f"Fyers auto-login step 4 (token) failed (HTTP {r4.status_code}): {r4.text}")
        url = r4.json().get("Url", "")
        if not url:
            raise RuntimeError(f"Fyers auto-login step 4: no Url in response: {r4.text}")

        parsed_query = parse.parse_qs(parse.urlparse(url).query)
        auth_code_list = parsed_query.get("auth_code")
        if not auth_code_list or not auth_code_list[0]:
            raise RuntimeError(f"Fyers auto-login step 4: auth_code not found in Url: {url}")
        auth_code = auth_code_list[0]

        # ── Step 5: Validate auth_code to obtain final access token ────────
        r5 = _req.post(
            f"{BASE_API}/validate-authcode",
            json={
                "grant_type": "authorization_code",
                "appIdHash": app_id_hash,
                "code": auth_code,
            },
            headers=headers,
            timeout=15,
        )
        if r5.status_code != 200:
            raise RuntimeError(f"Fyers auto-login step 5 (validate-authcode) failed (HTTP {r5.status_code}): {r5.text}")
        data5 = r5.json()
        access_token = data5.get("access_token", "")
        if not access_token:
            raise RuntimeError(f"Fyers auto-login step 5: no access_token in response: {data5}")

        return access_token

    def complete_login(self, auth_code: str = "", **kwargs) -> UserProfile:
        """
        Exchange an OAuth auth code for an access token.

        If FYERS_FY_ID + FYERS_TOTP_SECRET + FYERS_PIN are all set on this
        instance, the headless TOTP auto-login path is used first (no browser).
        Otherwise falls back to the standard OAuth auth_code exchange.
        """
        # ── Path A: Headless auto-login (TOTP + PIN) ──────────────────────
        if self._fy_id and self._totp_secret and self._pin and not auth_code:
            token = self._auto_login_totp()
            self._access_token = token
            self._token_ts = time.time()
            self._fyers = None
            self._save_token(token)
            return self.get_profile()

        # ── Path B: Standard OAuth auth_code exchange ─────────────────────
        fyersModel = _get_sdk()
        session = fyersModel.SessionModel(
            client_id=self._app_id,
            secret_key=self._secret_key,
            redirect_uri=self._redirect_uri,
            response_type="code",
            grant_type="authorization_code",
            state="chanakya_trade",
        )
        session.set_token(auth_code)
        response = session.generate_token()
        token = response.get("access_token", "")
        if not token:
            error_msg = response.get("message", "Unknown error")
            if "invalid app id" in error_msg.lower() or "app id hash" in error_msg.lower():
                raise RuntimeError(
                    f"Fyers login failed: {error_msg}\n"
                    "Your App ID and Secret Key don't match. To fix:\n"
                    "  trade\n"
                    "  > credentials delete FYERS_APP_ID\n"
                    "  > credentials delete FYERS_SECRET_KEY\n"
                    "  > login\n"
                    "Then re-enter the correct values from myapi.fyers.in"
                )
            raise RuntimeError(
                f"Fyers login failed: {error_msg}\n"
                "Possible causes: expired auth code, wrong redirect URL, or network issue.\n"
                "Try logging in again. If it persists, verify your app config at myapi.fyers.in\n"
                "and ensure Redirect URL is exactly: http://127.0.0.1:8765/fyers/callback"
            )

        self._access_token = token
        self._token_ts = time.time()
        self._fyers = None  # reset so it gets recreated with new token
        self._save_token(token)
        return self.get_profile()

    def is_authenticated(self) -> bool:
        if not self._access_token:
            self._load_token()
            if self._access_token:
                return True
            if self._fy_id and self._totp_secret and self._pin and self._app_id and self._secret_key:
                try:
                    logger.info("[FyersAPI] Auto-authenticating headlessly via TOTP + PIN credentials...")
                    self.complete_login()
                    return bool(self._access_token)
                except Exception as e:
                    logger.warning(f"[FyersAPI] Headless auto-login attempt failed: {e}")
                    return False
            return False
        if self._token_ts and time.time() - self._token_ts >= TOKEN_EXPIRY:
            self._access_token = ""
            self._fyers = None
            try:
                TOKEN_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            if self._fy_id and self._totp_secret and self._pin and self._app_id and self._secret_key:
                try:
                    logger.info("[FyersAPI] Token expired, refreshing headlessly via TOTP + PIN...")
                    self.complete_login()
                    return bool(self._access_token)
                except Exception as e:
                    logger.warning(f"[FyersAPI] Headless auto-login refresh failed: {e}")
                    return False
            return False
        # Token exists and is < 12 hours old — trust it (no API call)
        return True

    def logout(self) -> None:
        try:
            fyers = self._get_fyers()
            if fyers:
                fyers.logout()
        except Exception:
            pass
        self._access_token = ""
        self._profile = None
        self._fyers = None
        try:
            TOKEN_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Profile & Funds ───────────────────────────────────────

    def get_profile(self) -> UserProfile:
        if self._profile:
            return self._profile
        fyers = self._get_fyers()
        data = fyers.get_profile()
        payload = data.get("data", {})
        self._profile = UserProfile(
            user_id=payload.get("fy_id", ""),
            name=payload.get("name", ""),
            email=payload.get("email_id", ""),
            broker="Fyers",
        )
        return self._profile

    def get_funds(self) -> Funds:
        fyers = self._get_fyers()
        data = fyers.funds()
        payload = data.get("fund_limit", [])
        # fund_limit is a list of {id, title, equityAmount, commodityAmount}
        cash = next(
            (float(x.get("equityAmount", 0)) for x in payload if x.get("id") == 10), 0.0
        )  # id=10 → Available Balance
        margin = next(
            (float(x.get("equityAmount", 0)) for x in payload if x.get("id") == 12), 0.0
        )  # id=12 → Utilised Margin
        total = next(
            (float(x.get("equityAmount", 0)) for x in payload if x.get("id") == 1), 0.0
        )  # id=1  → Total Balance
        return Funds(
            available_cash=cash,
            used_margin=margin,
            total_balance=total,
        )

    # ── Portfolio ─────────────────────────────────────────────

    def get_holdings(self) -> list[Holding]:
        fyers = self._get_fyers()
        data = fyers.holdings()
        holdings = []
        for item in data.get("holdings", []):
            qty = int(item.get("quantity", 0))
            avg_px = float(item.get("costPrice", 0))
            ltp = float(item.get("ltp", avg_px))
            symbol = item.get("symbol", "")
            ticker = symbol.split(":")[-1].split("-")[0] if ":" in symbol else symbol
            pnl = float(item.get("pl", 0))
            pnl_pct = ((ltp - avg_px) / avg_px * 100) if avg_px else 0.0
            holdings.append(
                Holding(
                    symbol=ticker,
                    exchange="NSE",
                    quantity=qty,
                    avg_price=avg_px,
                    last_price=ltp,
                    pnl=pnl,
                    pnl_pct=round(pnl_pct, 2),
                    day_change=0.0,
                    day_change_pct=0.0,
                )
            )
        return holdings

    def get_positions(self) -> list[Position]:
        fyers = self._get_fyers()
        data = fyers.positions()
        positions = []
        for item in data.get("netPositions", []):
            qty = int(item.get("netQty", 0))
            if qty == 0:
                continue
            avg = float(item.get("avgPrice", 0))
            ltp = float(item.get("ltp", avg))
            symbol = item.get("symbol", "")
            ticker = symbol.split(":")[-1].split("-")[0] if ":" in symbol else symbol
            positions.append(
                Position(
                    symbol=ticker,
                    exchange=item.get("exchange", "NSE"),
                    product=item.get("productType", "CNC"),
                    quantity=qty,
                    avg_price=avg,
                    last_price=ltp,
                    pnl=float(item.get("pl", 0)),
                    instrument_type="EQ",
                )
            )
        return positions

    # ── Quotes ────────────────────────────────────────────────

    def get_quote(self, instruments: list[str] | str) -> dict[str, Quote]:
        """
        Get quotes. Instruments: ["NSE:RELIANCE", "NSE:NIFTY 50", "GOLD", "USDINR"]
        Fyers format: "NSE:RELIANCE-EQ", "NSE:NIFTY50-INDEX", "MCX:GOLD26OCTFUT"
        Batch chunking by 50 to honor Fyers API constraints.
        """
        if isinstance(instruments, str):
            instruments = [instruments]

        fyers = self._get_fyers()
        if not fyers:
            return {}

        # Convert to Fyers symbol format and build key mapping
        fyers_symbols = []
        key_map: dict[str, list[str]] = {}  # fyers_symbol → list of original instrument keys
        for inst in instruments:
            fyers_sym = _to_fyers_symbol(inst)
            fyers_symbols.append(fyers_sym)
            key_map.setdefault(fyers_sym, []).append(inst)

        # Unique preserving order
        unique_fyers_symbols = list(dict.fromkeys(fyers_symbols))
        result: dict[str, Quote] = {}

        if get_fyers_circuit_breaker().is_tripped():
            logger.warning("[FyersAPI] Circuit breaker is OPEN. Fast-failing get_quote to protect Fyers account.")
            return {}

        # Chunk in batches of 50
        CHUNK_SIZE = 50
        for i in range(0, len(unique_fyers_symbols), CHUNK_SIZE):
            chunk = unique_fyers_symbols[i : i + CHUNK_SIZE]
            try:
                _fyers_rate_limiter.acquire(category=FyersCallCategory.SCANNER_QUOTE)
                data = fyers.quotes({"symbols": ",".join(chunk)})
                if not isinstance(data, dict) or data.get("s") != "ok":
                    err_msg = str(data.get("message", "Fyers quotes error")) if isinstance(data, dict) else "Invalid quotes response"
                    if "429" in err_msg or "rate limit" in err_msg.lower():
                        get_fyers_circuit_breaker().record_failure(status_code=429, error_message=err_msg)
                else:
                    get_fyers_circuit_breaker().record_success()
                for item in data.get("d", []):
                    raw = item.get("n", "")
                    if item.get("s") == "error":
                        logger.warning(
                            f"[FyersAPI] Quotes error for {raw or item.get('n')}: {item.get('errmsg', 'Unknown')}"
                        )
                        continue
                    v = item.get("v", {})
                    if not v or v.get("s") == "error":
                        continue
                    last_price = float(v.get("lp", 0.0) or 0.0)
                    if last_price <= 0.0:
                        continue
                    open_price = float(v.get("open_price", 0.0) or 0.0)
                    high_price = float(v.get("high_price", 0.0) or 0.0)
                    low_price = float(v.get("low_price", 0.0) or 0.0)
                    prev_close = float(v.get("prev_close_price", 0.0) or 0.0)
                    ch = float(v.get("ch", 0.0) or 0.0)
                    chp = float(v.get("chp", 0.0) or 0.0)

                    # After NSE close Fyers rolls prev_close_price to today's official
                    # close, making ch ≈ 0. Detect this: if |ch| < 5% of the intraday
                    # range (and the range is meaningful), fall back to open-based change.
                    intraday_range = high_price - low_price
                    if intraday_range > 0.5 and open_price > 0 and abs(ch) < intraday_range * 0.05:
                        ch = round(last_price - open_price, 2)
                        chp = round((ch / open_price * 100), 2) if open_price else 0.0

                    orig_keys = key_map.get(raw, [raw])
                    for k in orig_keys:
                        k_sym = k.split(":")[-1] if ":" in k else k
                        result[k] = Quote(
                            symbol=k_sym,
                            last_price=last_price,
                            open=open_price,
                            high=high_price,
                            low=low_price,
                            close=prev_close,
                            volume=int(v.get("volume", 0) or 0),
                            change=ch,
                            change_pct=chp,
                            vwap=float(v.get("atp", 0.0) or 0.0) or None,
                            upper_circuit=float(v.get("upper_ckt", 0.0) or 0.0) or None,
                            lower_circuit=float(v.get("lower_ckt", 0.0) or 0.0) or None,
                        )
                    if raw not in result:
                        raw_sym = raw.split(":")[-1] if ":" in raw else raw
                        result[raw] = Quote(
                            symbol=raw_sym,
                            last_price=last_price,
                            open=open_price,
                            high=high_price,
                            low=low_price,
                            close=prev_close,
                            volume=int(v.get("volume", 0) or 0),
                            change=ch,
                            change_pct=chp,
                            vwap=float(v.get("atp", 0.0) or 0.0) or None,
                            upper_circuit=float(v.get("upper_ckt", 0.0) or 0.0) or None,
                            lower_circuit=float(v.get("lower_ckt", 0.0) or 0.0) or None,
                        )
            except Exception as exc:
                err_str = str(exc)
                get_fyers_circuit_breaker().record_failure(
                    status_code=429 if "429" in err_str else 0,
                    error_message=err_str,
                )
                logger.warning(
                    f"[FyersAPI] Quotes fetch error for chunk ({len(chunk)} symbols): {exc}",
                    exc_info=True,
                )
                continue

        return result

    def get_ltp(self, instrument: str) -> float:
        quotes = self.get_quote([instrument])
        q = quotes.get(instrument)
        return q.last_price if q else 0.0

    def get_market_depth(self, symbol: str) -> dict[str, Any]:
        """
        Level 2 Market Depth (5-level Order Book) + Circuit Limits + Official Exchange ATP (VWAP).
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"status": "UNAVAILABLE", "message": "Fyers broker session not authenticated"}
        fyers_sym = _to_fyers_symbol(symbol)
        try:
            _fyers_rate_limiter.acquire(category=FyersCallCategory.DEPTH_CHAIN)
            data = fyers.depth({"symbol": fyers_sym, "ohlcv_flag": 1})
            if data.get("s") != "ok":
                return {
                    "status": "UNAVAILABLE",
                    "message": data.get("message", "Error fetching market depth"),
                }
            d = data.get("d", {}).get(fyers_sym, {})
            bids = d.get("bids", d.get("bid", []))
            asks = d.get("asks", d.get("ask", []))
            total_buy = int(d.get("totalbuyqty", 0) or 0)
            total_sell = int(d.get("totalsellqty", 0) or 0)
            ratio = round(total_buy / max(total_sell, 1), 3) if total_sell > 0 else 1.0
            return {
                "status": "ok",
                "market_data_state": "LIVE",
                "symbol": symbol,
                "fyers_symbol": fyers_sym,
                "bids": bids,
                "asks": asks,
                "total_buy_qty": total_buy,
                "total_sell_qty": total_sell,
                "bid_ask_ratio": ratio,
                "order_book_imbalance_ratio": ratio,
                "atp": float(d.get("atp", 0.0) or 0.0),  # Official exchange VWAP
                "upper_circuit": float(d.get("upper_ckt", 0.0) or 0.0),
                "lower_circuit": float(d.get("lower_ckt", 0.0) or 0.0),
                "ltp": float(d.get("ltp", 0.0) or 0.0),
                "open": float(d.get("o", 0.0) or 0.0),
                "high": float(d.get("h", 0.0) or 0.0),
                "low": float(d.get("l", 0.0) or 0.0),
                "close": float(d.get("c", 0.0) or 0.0),
                "volume": int(d.get("v", 0) or 0),
                "oi": int(d.get("oi", 0) or 0),
                "pdoi": int(d.get("pdoi", 0) or 0),
                "oi_pct_change": float(d.get("oipercent", 0.0) or 0.0),
            }
        except Exception as e:
            return {"status": "UNAVAILABLE", "error": str(e)}

    def get_market_status(self) -> dict[str, Any]:
        """Real-time market status for Indian exchanges (NSE, BSE, MCX, CDS)."""
        fyers = self._get_fyers()
        if not fyers:
            return {"status": "UNAVAILABLE", "message": "Fyers broker session not authenticated"}
        try:
            _fyers_rate_limiter.acquire(category=FyersCallCategory.DEPTH_CHAIN)
            res = fyers.market_status()
            if isinstance(res, dict) and res.get("s") == "ok":
                return {
                    "status": "ok",
                    "marketStatus": res.get("marketStatus", []),
                }
            return {"status": "error", "raw": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_options_chain(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> list[OptionsContract]:
        """Fyers options chain with live Greeks, ΔOI, and institutional PCR via SDK."""
        fyers = self._get_fyers()
        if not fyers:
            return []
        if get_fyers_circuit_breaker().is_tripped():
            logger.warning(f"[FyersAPI] Circuit breaker is OPEN. Suppressing options chain for {underlying}.")
            return []
        try:
            fyers_sym = _to_fyers_symbol(underlying)
            if (
                "-INDEX" not in fyers_sym
                and "-EQ" not in fyers_sym
                and not fyers_sym.startswith("MCX:")
            ):
                fyers_sym = f"NSE:{fyers_sym.split(':')[-1]}-EQ"

            params: dict[str, Any] = {"symbol": fyers_sym, "strikecount": 20, "greeks": "1"}

            # If specific expiry requested, map YYYY-MM-DD to Fyers expiry timestamp
            if expiry:
                if str(expiry).isdigit():
                    params["timestamp"] = str(expiry)
                else:
                    exp_ts = self._resolve_expiry_timestamp(fyers_sym, expiry)
                    if exp_ts:
                        params["timestamp"] = str(exp_ts)

            _fyers_rate_limiter.acquire(category=FyersCallCategory.DEPTH_CHAIN)
            data = fyers.optionchain(params)
            payload = data.get("data", {})
            chain: list[OptionsContract] = []

            # Store root metadata for snapshot inspection
            self._last_oc_metadata = {
                "underlying": underlying,
                "call_oi": payload.get("callOi", 0),
                "put_oi": payload.get("putOi", 0),
                "pcr": round(
                    float(payload.get("putOi", 0) or 0) / max(float(payload.get("callOi", 1) or 1), 1),
                    4,
                ),
                "expiry_data": payload.get("expiryData", []),
                "indiavix": payload.get("indiavixData", {}).get("ltp"),
            }

            def _parse_greek_val(val: Any) -> Optional[float]:
                if val is None or val == "":
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            for item in payload.get("optionsChain", []):
                stk = item.get("strike_price")
                if stk is None or stk == -1:
                    continue  # Spot underlying header row

                opt_type = str(item.get("option_type", "")).upper()
                if opt_type not in ("CE", "PE"):
                    continue

                greeks = item.get("greeks") or {}
                raw_expiry = item.get("expiry", expiry or "")
                if not raw_expiry:
                    sym_str = item.get("symbol", "")
                    raw_expiry = _parse_expiry_from_fyers_symbol(sym_str, opt_type) or ""

                chain.append(
                    OptionsContract(
                        symbol=item.get("symbol", ""),
                        underlying=underlying,
                        expiry=raw_expiry,
                        strike=float(stk),
                        option_type=opt_type,
                        last_price=float(item.get("ltp", 0.0) or 0.0),
                        oi=int(item.get("oi", 0) or 0),
                        oi_change=int(item.get("doi", item.get("oich", item.get("oiChange", 0))) or 0),
                        pchange_oi=float(item.get("pdoi", item.get("oichp", 0.0)) or 0.0) or None,
                        volume=int(item.get("volume", 0) or 0),
                        iv=_parse_greek_val(greeks.get("iv")),
                        delta=_parse_greek_val(greeks.get("delta")),
                        gamma=_parse_greek_val(greeks.get("gamma")),
                        theta=_parse_greek_val(greeks.get("theta")),
                        vega=_parse_greek_val(greeks.get("vega")),
                        bid=float(item.get("bid", 0.0) or 0.0) or None,
                        ask=float(item.get("ask", 0.0) or 0.0) or None,
                        lot_size=int(item.get("lotSize", 50) or 50),
                        exchange=(
                            "MCX"
                            if (item.get("symbol", "").startswith("MCX:") or fyers_sym.startswith("MCX:"))
                            else "NFO"
                        ),
                    )
                )
            return chain
        except Exception:
            return []

    _expiry_ts_cache: dict[str, tuple[float, str]] = {}
    _expiries_dates_cache: dict[str, tuple[float, list[str]]] = {}

    def get_expiries(self, underlying: str) -> list[str]:
        """Extract all official available expiry dates from Fyers formatted as YYYY-MM-DD."""
        fyers = self._get_fyers()
        if not fyers:
            return []
        fyers_sym = _to_fyers_symbol(underlying)
        now_ts = time.time()
        cached = self._expiries_dates_cache.get(fyers_sym)
        if cached and (now_ts - cached[0] < 43200.0):
            return list(cached[1])

        try:
            _fyers_rate_limiter.acquire(category=FyersCallCategory.DEPTH_CHAIN)
            data = fyers.optionchain({"symbol": fyers_sym, "strikecount": 1})
            expiry_data = data.get("data", {}).get("expiryData", [])
            dates = []
            for item in expiry_data:
                d_str = item.get("date", "")
                exp_val = item.get("expiry")
                if "-" in d_str:
                    parts = d_str.split("-")
                    if len(parts) == 3:
                        iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                        dates.append(iso_date)
                        if exp_val:
                            self._expiry_ts_cache[f"{fyers_sym}:{iso_date}"] = (now_ts, str(exp_val))
            res = sorted(set(dates))
            if res:
                self._expiries_dates_cache[fyers_sym] = (now_ts, res)
            return res
        except Exception as exc:
            logger.warning(f"[FyersAPI] Failed to get expiries for {fyers_sym}: {exc}", exc_info=True)
            return []

    def _resolve_expiry_timestamp(
        self, fyers_symbol: str, target_expiry_iso: str
    ) -> Optional[str]:
        """Convert YYYY-MM-DD to Fyers epoch timestamp with 12h TTL cache."""
        cache_key = f"{fyers_symbol}:{target_expiry_iso}"
        now_ts = time.time()
        cached = self._expiry_ts_cache.get(cache_key)
        if cached and (now_ts - cached[0] < 43200.0):
            return cached[1]

        fyers = self._get_fyers()
        if not fyers:
            return None
        try:
            _fyers_rate_limiter.acquire(category=FyersCallCategory.DEPTH_CHAIN)
            data = fyers.optionchain({"symbol": fyers_symbol, "strikecount": 1})
            expiry_data = data.get("data", {}).get("expiryData", [])
            parts = target_expiry_iso.split("-")
            fyers_date_format = (
                f"{parts[2]}-{parts[1]}-{parts[0]}" if len(parts) == 3 else target_expiry_iso
            )
            matched_expiry = None
            all_dates = []
            for item in expiry_data:
                d_str = item.get("date", "")
                exp_val = item.get("expiry")
                if "-" in d_str and exp_val:
                    d_parts = d_str.split("-")
                    if len(d_parts) == 3:
                        iso = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
                        self._expiry_ts_cache[f"{fyers_symbol}:{iso}"] = (now_ts, str(exp_val))
                        all_dates.append(iso)
                if item.get("date") == fyers_date_format and exp_val:
                    matched_expiry = str(exp_val)

            if all_dates:
                self._expiries_dates_cache[fyers_symbol] = (now_ts, sorted(set(all_dates)))

            if matched_expiry:
                self._expiry_ts_cache[cache_key] = (now_ts, matched_expiry)
                return matched_expiry
        except Exception as exc:
            logger.warning(
                f"[FyersAPI] Failed to resolve expiry timestamp for {fyers_symbol} ({target_expiry_iso}): {exc}",
                exc_info=True,
            )
        return None

    def get_options_snapshot(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> tuple[list[OptionsContract], Optional[float], list[str], dict[str, Any]]:
        """
        Unified options snapshot returning (contracts, live_spot_price, available_expiries, source_info).
        Carries Greeks, PCR, India VIX, and official expiry dates.
        """
        from datetime import timezone

        chain = self.get_options_chain(underlying, expiry)
        meta = getattr(self, "_last_oc_metadata", {})
        spot = self.get_ltp(underlying)
        expiries = self.get_expiries(underlying)
        if not expiries and chain:
            expiries = sorted({c.expiry for c in chain if c.expiry})

        source_info = {
            "provider": "fyers",
            "source": "BROKER_REST",
            "data_state": "LIVE",
            "is_realtime": True,
            "pcr": meta.get("pcr"),
            "call_oi": meta.get("call_oi"),
            "put_oi": meta.get("put_oi"),
            "indiavix": meta.get("indiavix"),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        return chain, spot, expiries, source_info

    # ── Orders ────────────────────────────────────────────────

    @staticmethod
    def _to_fyers_order_type(order_type: str) -> int:
        """Map order type to Fyers API v3 numeric code.
        1: LIMIT, 2: MARKET, 3: STOP (SL-M), 4: STOP_LIMIT (SL-L).
        """
        ot = str(order_type or "").upper().strip()
        if ot in ("MARKET", "MKT"):
            return 2
        if ot in ("SL", "STOP", "SL-M", "STOP_MARKET"):
            return 3
        if ot in ("SL-L", "STOP_LIMIT", "STOPLIMIT"):
            return 4
        return 1  # LIMIT default

    def place_order(self, req: OrderRequest) -> OrderResponse:
        fyers = self._get_fyers()
        product_map = {
            "CNC": "CNC",
            "MIS": "INTRADAY",
            "INTRADAY": "INTRADAY",
            "NRML": "MARGIN",
            "MARGIN": "MARGIN",
            "CO": "CO",
            "BO": "BO",
        }
        fyers_sym = _to_fyers_symbol(f"{req.exchange}:{req.symbol}" if req.exchange else req.symbol)
        eff_type = self._to_fyers_order_type(req.order_type)
        limit_px = round_price_to_tick(float(req.price)) if eff_type in (1, 4) and req.price else 0.0
        stop_px = round_price_to_tick(float(req.trigger_price)) if req.trigger_price else 0.0
        payload = {
            "symbol": fyers_sym,
            "qty": int(req.quantity),
            "type": eff_type,
            "side": 1 if req.transaction_type == "BUY" else -1,
            "productType": product_map.get(req.product, "CNC"),
            "limitPrice": limit_px,
            "stopPrice": stop_px,
            "validity": req.validity or "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        _fyers_rate_limiter.acquire()
        data = fyers.place_order(payload)
        return OrderResponse(
            order_id=str(data.get("id", "")),
            status="OPEN" if data.get("s") == "ok" else "REJECTED",
            message=data.get("message", "Order placed"),
        )

    def place_basket_orders(self, orders: list[OrderRequest]) -> list[OrderResponse]:
        """Place multiple orders atomically in a single batch network call."""
        fyers = self._get_fyers()
        product_map = {
            "CNC": "CNC",
            "MIS": "INTRADAY",
            "INTRADAY": "INTRADAY",
            "NRML": "MARGIN",
            "MARGIN": "MARGIN",
            "CO": "CO",
            "BO": "BO",
        }
        payload_orders = []
        for req in orders:
            fyers_sym = _to_fyers_symbol(
                f"{req.exchange}:{req.symbol}" if req.exchange else req.symbol
            )
            eff_type = self._to_fyers_order_type(req.order_type)
            limit_px = round_price_to_tick(float(req.price)) if eff_type in (1, 4) and req.price else 0.0
            stop_px = round_price_to_tick(float(req.trigger_price)) if req.trigger_price else 0.0
            payload_orders.append(
                {
                    "symbol": fyers_sym,
                    "qty": int(req.quantity),
                    "type": eff_type,
                    "side": 1 if req.transaction_type == "BUY" else -1,
                    "productType": product_map.get(req.product, "CNC"),
                    "limitPrice": limit_px,
                    "stopPrice": stop_px,
                    "validity": req.validity or "DAY",
                    "disclosedQty": 0,
                    "offlineOrder": False,
                }
            )
        _fyers_rate_limiter.acquire()
        data = fyers.place_basket_orders(payload_orders)
        responses = []
        for item in data.get("data", []):
            responses.append(
                OrderResponse(
                    order_id=str(item.get("id", "")),
                    status=str(item.get("status", "SUBMITTED")),
                    message=item.get("message", "Basket order placed"),
                )
            )
        return responses

    def place_multileg_order(
        self,
        legs: list[dict],
        order_type: Optional[str] = None,
        product_type: str = "MARGIN",
    ) -> OrderResponse:
        """Place multi-leg options strategy order (e.g. Bull Call Spread, Straddle, Iron Condor)."""
        fyers = self._get_fyers()
        num_legs = len(legs)
        eff_order_type = order_type or f"{num_legs}L"
        payload_legs = {}
        for idx, leg in enumerate(legs, start=1):
            raw_side = str(leg.get("side", "BUY")).upper()
            side_code = 1 if raw_side in ("1", "BUY") else -1
            raw_type = str(leg.get("type", "LIMIT")).upper()
            type_code = 1 if raw_type in ("1", "LIMIT") else 2
            raw_px = float(leg.get("limitPrice", leg.get("limit_price", 0.0)) or 0.0)
            limit_px = round_price_to_tick(raw_px) if type_code == 1 and raw_px else 0.0
            payload_legs[f"leg{idx}"] = {
                "symbol": _to_fyers_symbol(leg["symbol"]),
                "qty": int(leg["qty"]),
                "side": side_code,
                "type": type_code,
                "limitPrice": limit_px,
            }
        payload = {
            "productType": product_type,
            "offlineOrder": False,
            "orderType": eff_order_type,
            "validity": "IOC",
            "legs": payload_legs,
        }
        _fyers_rate_limiter.acquire()
        data = fyers.place_multileg_order(payload)
        return OrderResponse(
            order_id=str(data.get("id", "")),
            status="SUBMITTED" if data.get("s") == "ok" else "REJECTED",
            message=data.get("message", "Multi-leg order placed"),
        )

    def exit_positions(self, position_id: Optional[str] = None) -> bool:
        """1-click square off specific position or panic square off all positions."""
        fyers = self._get_fyers()
        try:
            _fyers_rate_limiter.acquire()
            data = fyers.exit_positions(id=position_id) if position_id else fyers.exit_positions()
            return data.get("s") == "ok"
        except Exception:
            return False

    def get_orders(self) -> list[Order]:
        fyers = self._get_fyers()
        _fyers_rate_limiter.acquire()
        data = fyers.orderbook()
        orders = []
        for item in data.get("orderBook", []):
            symbol = item.get("symbol", "")
            ticker = symbol.split(":")[-1].split("-")[0] if ":" in symbol else symbol
            orders.append(
                Order(
                    order_id=str(item.get("id", "")),
                    symbol=ticker,
                    exchange="NSE",
                    transaction_type="BUY" if item.get("side", 0) == 1 else "SELL",
                    quantity=int(item.get("qty", 0)),
                    order_type="MARKET" if item.get("type") == 1 else "LIMIT",
                    product=item.get("productType", "CNC"),
                    status=str(item.get("status", "")),
                    price=float(item.get("limitPrice", 0)) or None,
                    average_price=float(item.get("tradedPrice", 0)) or None,
                    filled_quantity=int(item.get("filledQty", 0)),
                )
            )
        return orders

    def cancel_order(self, order_id: str) -> bool:
        fyers = self._get_fyers()
        try:
            _fyers_rate_limiter.acquire()
            data = fyers.cancel_order({"id": order_id})
            return data.get("s") == "ok"
        except Exception:
            return False

    def modify_order(
        self,
        order_id: str,
        price: Optional[float] = None,
        qty: Optional[int] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[str] = None,
    ) -> OrderResponse:
        """Modify an active pending order on Fyers."""
        fyers = self._get_fyers()
        payload: dict[str, Any] = {"id": str(order_id)}
        if price is not None:
            payload["limitPrice"] = round_price_to_tick(float(price))
        if trigger_price is not None:
            payload["stopPrice"] = round_price_to_tick(float(trigger_price))
        if qty is not None:
            payload["qty"] = int(qty)
        if order_type is not None:
            payload["type"] = self._to_fyers_order_type(order_type)
        try:
            _fyers_rate_limiter.acquire()
            data = fyers.modify_order(payload)
            return OrderResponse(
                order_id=str(data.get("id", order_id)),
                status="OPEN" if data.get("s") == "ok" else "REJECTED",
                message=data.get("message", "Order modified"),
            )
        except Exception as e:
            return OrderResponse(order_id=str(order_id), status="REJECTED", message=str(e))

    # ── Historical Data ──────────────────────────────────────

    def get_historical_data(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "day",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Fetch institutional OHLCV candles using Fyers official history API.

        Maps intervals ('day', '60minute', '15minute', '5minute', '1minute', etc.)
        to Fyers resolutions ('D', '60', '15', '5', '1').
        Automatically chunks date ranges exceeding Fyers single-request limits:
          - Minute resolutions: max 95 days per chunk (Fyers cap: 100 days)
          - Daily resolutions : max 360 days per chunk (Fyers cap: 366 days)
          - Seconds resolutions: max 25 days per chunk (Fyers cap: 30 days)
        Concatenates seamlessly and deduplicates by candle timestamp.
        """
        from datetime import timedelta

        fyers = self._get_fyers()
        if not fyers:
            raise RuntimeError("Fyers broker not initialized or logged in")
        if get_fyers_circuit_breaker().is_tripped():
            logger.warning(f"[FyersAPI] Circuit breaker is OPEN. Suppressing historical data for {symbol}.")
            return []

        fyers_sym = _to_fyers_symbol(symbol)
        if exchange and not fyers_sym.startswith(f"{exchange}:") and ":" not in fyers_sym:
            fyers_sym = f"{exchange.upper()}:{fyers_sym}"

        res_map = {
            "day": "D",
            "1d": "D",
            "d": "D",
            "60minute": "60",
            "60m": "60",
            "1h": "60",
            "30minute": "30",
            "30m": "30",
            "20minute": "20",
            "20m": "20",
            "15minute": "15",
            "15m": "15",
            "10minute": "10",
            "10m": "10",
            "5minute": "5",
            "5m": "5",
            "3minute": "3",
            "3m": "3",
            "2minute": "2",
            "2m": "2",
            "minute": "1",
            "1m": "1",
            "1minute": "1",
        }
        res_str = res_map.get(str(interval).lower(), "D")

        now = datetime.now()
        eff_to = to_date or now
        if not from_date:
            if res_str in ("1", "2", "3", "5"):
                eff_from = eff_to - timedelta(days=5)
            elif res_str in ("10", "15", "20", "30", "60"):
                eff_from = eff_to - timedelta(days=45)
            else:
                eff_from = eff_to - timedelta(days=365)
        else:
            eff_from = from_date

        if eff_from > eff_to:
            eff_from, eff_to = eff_to, eff_from

        # Determine safe chunk window per Fyers limits
        if res_str in ("1", "2", "3", "5", "10", "15", "20", "30", "60"):
            max_chunk_days = 95
        elif res_str.endswith("S"):
            max_chunk_days = 25
        else:
            max_chunk_days = 360

        total_days = max(1, (eff_to - eff_from).days)
        chunks: list[tuple[datetime, datetime]] = []
        if total_days <= max_chunk_days:
            chunks.append((eff_from, eff_to))
        else:
            curr_start = eff_from
            while curr_start < eff_to:
                curr_end = min(curr_start + timedelta(days=max_chunk_days), eff_to)
                chunks.append((curr_start, curr_end))
                curr_start = curr_end + timedelta(days=1)

        all_candles: list[list] = []
        for c_from, c_to in chunks:
            _fyers_rate_limiter.acquire(category=FyersCallCategory.HISTORICAL)
            payload = {
                "symbol": fyers_sym,
                "resolution": res_str,
                "date_format": "1",
                "range_from": c_from.strftime("%Y-%m-%d"),
                "range_to": c_to.strftime("%Y-%m-%d"),
                "cont_flag": "1",
            }
            try:
                data = fyers.history(payload)
                if isinstance(data, dict) and data.get("s") == "ok":
                    all_candles.extend(data.get("candles", []))
            except Exception as exc:
                logger.warning(
                    f"[FyersAPI] Historical data fetch failed for {fyers_sym} ({res_str}, {c_from} to {c_to}): {exc}",
                    exc_info=True,
                )
                continue

        # Deduplicate candles by epoch timestamp and sort chronologically
        seen_epochs = set()
        unique_candles = []
        for c in all_candles:
            if len(c) >= 6 and c[0] not in seen_epochs:
                seen_epochs.add(c[0])
                unique_candles.append(c)
        unique_candles.sort(key=lambda c: c[0])

        from datetime import timezone

        rows = []
        for c in unique_candles:
            epoch = c[0]
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            rows.append(
                {
                    "date": dt,
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                }
            )
        return rows

    # ── Advanced Institutional Orders & Screeners ─────────────

    def place_gtt_order(
        self,
        symbol: str,
        qty: int,
        side: int,  # 1 for BUY, -1 for SELL
        trigger_price: float,
        limit_price: Optional[float] = None,
        product: str = "CNC",
    ) -> dict[str, Any]:
        """Place a Good-Till-Triggered (GTT) order held server-side by Fyers for up to 1 year."""
        fyers = self._get_fyers()
        fyers_sym = _to_fyers_symbol(symbol)
        payload = {
            "side": side,
            "symbol": fyers_sym,
            "productType": product,
            "orderInfo": {
                "leg1": {
                    "price": float(limit_price or trigger_price),
                    "triggerPrice": float(trigger_price),
                    "qty": int(qty),
                }
            },
        }
        return fyers.place_gtt_order(payload)

    def get_gtt_orders(self) -> list[dict]:
        """Fetch active server-side GTT orders."""
        fyers = self._get_fyers()
        try:
            data = fyers.gtt_orderbook()
            return data.get("orderBook", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def cancel_gtt_order(self, order_id: str) -> bool:
        """Cancel an active GTT order."""
        fyers = self._get_fyers()
        try:
            data = fyers.cancel_gtt_order({"id": str(order_id)})
            return data.get("s") == "ok"
        except Exception:
            return False

    def create_smart_trailing_order(
        self,
        symbol: str,
        qty: int,
        side: int,  # 1 for BUY, -1 for SELL
        stop_price: float,
        trail_amount: float,
        limit_price: Optional[float] = None,
        product: str = "INTRADAY",
    ) -> dict[str, Any]:
        """Place an exchange-managed Smart Trailing Stop Loss order."""
        fyers = self._get_fyers()
        fyers_sym = _to_fyers_symbol(symbol)
        payload = {
            "symbol": fyers_sym,
            "side": side,
            "qty": int(qty),
            "productType": product,
            "orderType": 1 if limit_price else 2,
            "stopPrice": float(stop_price),
            "jump_diff": float(trail_amount),
            "limitPrice": float(limit_price) if limit_price else 0,
        }
        return fyers.create_smart_order_trail(payload)

    def exit_all_positions(self, segment: Optional[str] = None) -> dict[str, Any]:
        """1-Click Emergency Square-Off across all open positions or by segment."""
        fyers = self._get_fyers()
        payload = {"segment": segment} if segment else {"exit_all": 1}
        return fyers.exit_positions(payload)

    def get_screener_technical(self, screener: str = "cs004") -> dict[str, Any]:
        """Query native Fyers server-side technical screeners."""
        fyers = self._get_fyers()
        try:
            return fyers.screeners_technical({"screener": screener})
        except Exception as e:
            return {"status": "error", "error": str(e), "s": "error"}

    def get_screener_candlestick(self, pattern: str = "hammer") -> dict[str, Any]:
        """Query native Fyers server-side candlestick pattern recognizer."""
        fyers = self._get_fyers()
        try:
            if hasattr(fyers, "screeners_candlestick"):
                return fyers.screeners_candlestick({"pattern": pattern})
            elif hasattr(fyers, "screeners"):
                return fyers.screeners({"pattern": pattern, "type": "candlestick"})
            return {"s": "ok", "pattern": pattern, "data": []}
        except Exception as e:
            return {"status": "error", "error": str(e), "s": "error"}

    def get_trade_history(self) -> list[dict]:
        """Retrieve execution trade history for institutional audit."""
        fyers = self._get_fyers()
        try:
            data = fyers.tradebook()
            return data.get("tradeBook", []) if isinstance(data, dict) else []
        except Exception:
            return []

    # ── 24x7 Server-Side Price & Volatility Triggers ─────────

    def create_server_alert(
        self,
        symbol: str,
        name: str,
        target_price: float,
        condition: str = "GT",  # "GT" (greater) or "LT" (lesser)
        comparison_type: str = "LTP",
        notes: str = "",
    ) -> dict[str, Any]:
        """Create a 24x7 price alert monitored directly on Fyers exchange infrastructure."""
        fyers = self._get_fyers()
        fyers_sym = _to_fyers_symbol(symbol)
        payload = {
            "alert-type": 1,
            "name": name,
            "symbol": fyers_sym,
            "comparisonType": comparison_type.upper(),
            "condition": condition.upper(),
            "value": float(target_price),
            "notes": notes or f"ChanakyaTrade Alert on {symbol}",
        }
        return fyers.create_alert(payload)

    def get_server_alerts(self, archive: int = 0) -> list[dict]:
        """Retrieve all active or archived server-side price alerts."""
        fyers = self._get_fyers()
        try:
            res = fyers.get_alert({"archive": archive})
            return (
                res.get("data", [])
                if isinstance(res, dict) and isinstance(res.get("data"), list)
                else []
            )
        except Exception:
            return []

    def delete_server_alert(self, alert_id: str) -> bool:
        """Delete an active server-side price alert."""
        fyers = self._get_fyers()
        try:
            res = fyers.delete_alert({"id": alert_id})
            return res.get("s") == "ok"
        except Exception:
            return False

    # ── Server-Side Candlestick Recognizers ──────────────────

    def get_screener_candlestick(self, pattern: str = "hammer") -> dict[str, Any]:
        """Query native Fyers server-side candlestick pattern recognizer."""
        fyers = self._get_fyers()
        try:
            return fyers.screeners_candlestick({"screener": pattern})
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Real-Time Sector Breadth & Heatmap ───────────────────

    def get_sector_heatmap(self) -> dict[str, Any]:
        """
        Generate real-time Sector Heatmap & Relative Strength Breadth Matrix.
        Queries all major official NSE sectoral indices concurrently.
        """
        sector_symbols = [
            ("Bank", "NSE:NIFTYBANK-INDEX"),
            ("IT", "NSE:NIFTYIT-INDEX"),
            ("Auto", "NSE:NIFTYAUTO-INDEX"),
            ("Metal", "NSE:NIFTYMETAL-INDEX"),
            ("Pharma", "NSE:NIFTYPHARMA-INDEX"),
            ("FMCG", "NSE:NIFTYFMCG-INDEX"),
            ("Energy", "NSE:NIFTYENERGY-INDEX"),
            ("Infra", "NSE:NIFTYINFRA-INDEX"),
            ("Realty", "NSE:NIFTYREALTY-INDEX"),
            ("Fin Services", "NSE:NIFTYFINSERVICE-INDEX"),
            ("Media", "NSE:NIFTYMEDIA-INDEX"),
            ("PSE", "NSE:NIFTYPSE-INDEX"),
        ]
        sym_list = [sym for _, sym in sector_symbols]
        quotes = self.get_quote(sym_list)

        items = []
        advances = 0
        declines = 0

        for name, sym in sector_symbols:
            q = quotes.get(sym)
            if q:
                chg_pct = round(float(q.change_pct), 2)
                ltp = round(float(q.last_price), 2)
                chg = round(float(q.change), 2)
                if chg_pct > 0:
                    advances += 1
                elif chg_pct < 0:
                    declines += 1
                items.append(
                    {
                        "name": name,
                        "symbol": sym,
                        "ltp": ltp,
                        "change": chg,
                        "change_pct": chg_pct,
                        "status": "BULLISH" if chg_pct > 0 else "BEARISH",
                    }
                )

        items.sort(key=lambda x: x["change_pct"], reverse=True)
        leading = items[0]["name"] if items else "None"
        lagging = items[-1]["name"] if items else "None"
        breadth_ratio = round(advances / max(advances + declines, 1), 2)

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "leading_sector": leading,
            "lagging_sector": lagging,
            "advances": advances,
            "declines": declines,
            "breadth_ratio": breadth_ratio,
            "sectors": items,
        }

    def check_order_margin(
        self,
        orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Pre-flight margin calculation using official Fyers v3 Multi-Order Margin API.
        Combines exchange margin requirements with SEBI statutory transaction costs
        (Brokerage, STT, Exchange Fees, GST, Stamp Duty).
        """
        import requests
        from decimal import Decimal
        from engine.charges import calculate_transaction_charges

        if not self._access_token:
            return {"status": "UNAVAILABLE", "message": "Fyers broker session not authenticated"}

        fyers_orders = []
        parsed_orders = []

        for o in orders:
            raw_sym = str(o.get("symbol", "")).strip()
            fyers_sym = _to_fyers_symbol(raw_sym)
            qty = int(o.get("qty", o.get("quantity", 1)))
            raw_side = str(o.get("side", "BUY")).upper()
            side_code = 1 if raw_side in ("BUY", "1") else -1
            pt = str(o.get("product_type", o.get("productType", "INTRADAY"))).upper()
            if pt in ("MIS", "DAY", "INTRA"):
                pt = "INTRADAY"
            elif pt in ("NRML", "NORMAL", "CARRY"):
                pt = "MARGIN"
            elif pt in ("DELIVERY", "CASH"):
                pt = "CNC"

            limit_p = float(o.get("limit_price", o.get("price", 0.0)) or 0.0)
            stop_p = float(o.get("stop_price", 0.0) or 0.0)
            order_type = 1 if limit_p > 0 else 2

            fyers_payload = {
                "symbol": fyers_sym,
                "qty": qty,
                "side": side_code,
                "type": order_type,
                "productType": pt,
            }
            if limit_p > 0:
                fyers_payload["limitPrice"] = limit_p
            if stop_p > 0:
                fyers_payload["stopPrice"] = stop_p

            fyers_orders.append(fyers_payload)
            parsed_orders.append({
                "raw_symbol": raw_sym,
                "fyers_symbol": fyers_sym,
                "qty": qty,
                "side": "BUY" if side_code == 1 else "SELL",
                "product_type": pt,
                "price": limit_p,
            })

        # 1. Query Fyers official multiorder margin endpoint
        margin_url = "https://api-t1.fyers.in/api/v3/multiorder/margin"
        headers = {
            "Authorization": f"{self._app_id}:{self._access_token}",
            "Content-Type": "application/json",
        }

        margin_total = 0.0
        margin_avail = 0.0
        fyers_err = None

        try:
            resp = requests.post(margin_url, headers=headers, json={"data": fyers_orders}, timeout=5.0)
            if resp.status_code == 200:
                res_data = resp.json()
                if res_data.get("s") == "ok" and "data" in res_data:
                    d = res_data["data"]
                    margin_total = float(d.get("margin_total", 0.0) or 0.0)
                    margin_avail = float(d.get("margin_avail", 0.0) or 0.0)
                else:
                    fyers_err = res_data.get("message", "Fyers margin calculation failed")
            else:
                fyers_err = f"HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            fyers_err = str(e)

        # 2. If margin_avail is 0 or unpopulated, resolve from live funds endpoint
        if margin_avail <= 0:
            try:
                funds = self.get_funds()
                margin_avail = float(funds.available_margin or funds.equity_margin or funds.total_balance or 0.0)
            except Exception:
                pass

        # 3. Calculate statutory transaction charges across all orders
        total_brokerage = Decimal("0.00")
        total_stt = Decimal("0.00")
        total_exc = Decimal("0.00")
        total_gst = Decimal("0.00")
        total_stamp = Decimal("0.00")
        total_sebi = Decimal("0.00")
        total_charges = Decimal("0.00")

        order_details = []
        for p in parsed_orders:
            sym = p["raw_symbol"]
            sym_upper = sym.upper()
            is_opt = any(x in sym_upper for x in ("CE", "PE"))
            is_fut = "FUT" in sym_upper
            is_delivery = p["product_type"] == "CNC"

            if is_opt:
                seg = "OPTIONS"
            elif is_fut:
                seg = "FUTURES"
            elif is_delivery:
                seg = "EQUITY_DELIVERY"
            else:
                seg = "EQUITY_INTRADAY"

            exec_price = p["price"]
            if exec_price <= 0:
                exec_price = self.get_ltp(sym) or 100.0

            costs = calculate_transaction_charges(
                price=Decimal(str(round(exec_price, 2))),
                quantity=p["qty"],
                segment=seg,
                side=p["side"],
            )
            total_brokerage += costs.brokerage
            total_stt += costs.stt
            total_exc += costs.exchange_charges
            total_gst += costs.gst
            total_stamp += costs.stamp_duty
            total_sebi += costs.sebi_charges
            total_charges += costs.total_charges

            order_details.append({
                "symbol": sym,
                "fyers_symbol": p["fyers_symbol"],
                "side": p["side"],
                "qty": p["qty"],
                "estimated_price": round(exec_price, 2),
                "segment": seg,
                "notional_turnover": float(costs.notional_turnover),
                "charges": costs.to_dict(),
            })

        net_charges_float = float(total_charges)
        total_cash_required = round(margin_total + (net_charges_float if any(p["side"] == "BUY" for p in parsed_orders) else 0.0), 2)
        is_sufficient = (margin_avail >= total_cash_required) if margin_avail > 0 else True
        shortfall = max(0.0, round(total_cash_required - margin_avail, 2)) if margin_avail > 0 and not is_sufficient else 0.0

        return {
            "status": "ok" if not fyers_err else "DEGRADED",
            "fyers_error": fyers_err,
            "preflight_verdict": "CLEARED" if is_sufficient else "INSUFFICIENT_MARGIN",
            "required_margin": round(margin_total, 2),
            "available_margin": round(margin_avail, 2),
            "is_sufficient": is_sufficient,
            "shortfall": shortfall,
            "net_cash_required": total_cash_required,
            "total_transaction_charges": round(net_charges_float, 2),
            "charges_breakdown": {
                "brokerage": float(total_brokerage),
                "stt": float(total_stt),
                "exchange_charges": float(total_exc),
                "gst": float(total_gst),
                "stamp_duty": float(total_stamp),
                "sebi_charges": float(total_sebi),
                "total_charges": net_charges_float,
            },
            "orders": order_details,
        }

