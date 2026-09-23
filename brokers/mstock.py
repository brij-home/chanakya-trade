"""
brokers/mstock.py
─────────────────
m.Stock (Mirae Asset Capital Markets) BrokerAPI implementation.

m.Stock provides a free trading API for Indian equity & F&O markets,
supporting OAuth2 browser redirects, TOTP session generation, live quotes,
portfolio holdings, intraday positions, and order execution.

Credentials needed:
    MSTOCK_API_KEY      — API Key / Platform Key from m.Stock developer portal
    MSTOCK_API_SECRET   — API Secret / Secret Key
    MSTOCK_CLIENT_CODE  — Your m.Stock trading login ID / Client Code
    MSTOCK_PASSWORD     — Your m.Stock trading password (optional for direct login)
    MSTOCK_TOTP_SECRET  — (Optional) Base32 TOTP secret for automated 2FA login
    MSTOCK_REDIRECT_URL — Redirect URL (default: http://103.149.127.88:8765/mstock/callback)

Session token is persisted to ~/.trading_platform/mstock.json and auto-restored.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime
from typing import Optional

try:
    import dotenv

    dotenv.load_dotenv()
except ImportError:
    pass

import httpx

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
from config.paths import app_data_path

TOKEN_FILE = app_data_path("mstock.json")

MSTOCK_BASE_URL = os.environ.get("MSTOCK_BASE_URL", "https://api.mstock.trade")
MSTOCK_AUTH_URL = os.environ.get("MSTOCK_AUTH_URL", "https://api.mstock.trade")

# Exchange mapping
_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCX",
    "CDS": "CDS",
}

# Reverse exchange mapping
_REV_EXCHANGE_MAP = {v: k for k, v in _EXCHANGE_MAP.items()}

# Order Type mapping
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SL-M",
}

# Product Type mapping (Maps standard Chanakya types to official mStock Type B API values)
_PRODUCT_MAP = {
    "CNC": "DELIVERY",
    "MIS": "INTRADAY",
    "NRML": "MARGIN",
    "DELIVERY": "DELIVERY",
    "INTRADAY": "INTRADAY",
    "MARGIN": "MARGIN",
}

# Reverse mapping from mStock product types back to Chanakya standard
_REV_PRODUCT_MAP = {
    "DELIVERY": "CNC",
    "INTRADAY": "MIS",
    "MARGIN": "NRML",
    "CNC": "CNC",
    "MIS": "MIS",
    "NRML": "NRML",
}


# Common NSE segment security tokens
_KNOWN_NSE_TOKENS = {
    "NIFTY": "26000",
    "NIFTY50": "26000",
    "NIFTY 50": "26000",
    "BANKNIFTY": "26009",
    "NIFTY BANK": "26009",
    "FINNIFTY": "26037",
    "NIFTY FIN SERVICE": "26037",
    "NIFTY FINANCIAL SERVICES": "26037",
    "MIDCPNIFTY": "26074",
    "NIFTY MID SELECT": "26074",
    "NIFTYIT": "26002",
    "RELIANCE": "2885",
    "TCS": "11536",
    "INFY": "1594",
    "HDFCBANK": "1333",
    "ICICIBANK": "4963",
    "SBIN": "3045",
    "KOTAKBANK": "1922",
    "AXISBANK": "5900",
    "LT": "11483",
    "ITC": "1660",
    "BAJFINANCE": "317",
    "BHARTIARTL": "10604",
    "MARUTI": "10999",
    "TATAMOTORS": "3456",
    "WIPRO": "3787",
    "COFORGE": "11540",
    "TRENT": "1964",
    "HCLTECH": "7229",
    "DIVISLAB": "10940",
    "TECHM": "13538",
    "OFSS": "10738",
    "MFSL": "2142",
    "HDFCLIFE": "467",
    "ICICIPRULI": "18652",
    "SBILIFE": "21808",
    "PATANJALI": "17029",
    "OBEROIRLTY": "20242",
    "KPITTECH": "9683",
    "TATAELXSI": "3506",
    "MPHASIS": "4503",
    "MANKIND": "5926",
    "BSE": "19585",
    "MCX": "31181",
    "GOLD": "GOLD",
    "SILVER": "SILVER",
    "CRUDEOIL": "CRUDEOIL",
}


class MStockAPI(BrokerAPI):
    """
    m.Stock (Mirae Asset Capital Markets) Broker implementation for live data and order execution.
    Supports official Type B User APIs with TOTP automated session handshake.
    """

    name = "mstock"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        client_code: str = "",
        password: str = "",
        totp_secret: str = "",
        redirect_uri: str = "",
    ) -> None:
        self._api_key = api_key or os.environ.get("MSTOCK_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("MSTOCK_API_SECRET", "")
        self._client_code = client_code or os.environ.get("MSTOCK_CLIENT_CODE", "")
        self._password = password or os.environ.get("MSTOCK_PASSWORD", "")
        self._totp_secret = totp_secret or os.environ.get("MSTOCK_TOTP_SECRET", "")
        self._redirect_uri = (
            redirect_uri
            or os.environ.get("MSTOCK_REDIRECT_URL", "")
            or "http://103.149.127.88:8765/mstock/callback"
        )

        self._token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0
        self._user_profile: Optional[UserProfile] = None
        self._scrip_token_cache: dict[str, str] = {}
        self._client = httpx.Client(timeout=10.0)

        # Restore saved token session if valid
        self._load_token()

    # ── Token Resolution Helper ──────────────────────────────

    def get_symbol_token(self, symbol: str, exchange: str = "NSE") -> str:
        """Resolve security token for symbol via known tokens or cached scrip master."""
        clean_sym = (
            symbol.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").strip().upper()
        )
        if clean_sym in _KNOWN_NSE_TOKENS:
            return _KNOWN_NSE_TOKENS[clean_sym]

        cache_key = f"{exchange}:{clean_sym}"
        if cache_key in self._scrip_token_cache:
            return self._scrip_token_cache[cache_key]

        try:
            self._ensure_scrip_cache()
            if cache_key in self._scrip_token_cache:
                return self._scrip_token_cache[cache_key]
        except Exception:
            pass
        return clean_sym

    def _ensure_scrip_cache(self) -> None:
        """Parse instruments from Scrip Master if not yet loaded."""
        if self._scrip_token_cache or not self._token:
            return

        cache_disk_file = app_data_path("mstock_scrip_cache.json")
        now_ts = time.time()
        # 1. Try local disk cache if fresher than 24 hours
        if cache_disk_file.exists():
            try:
                disk_data = json.loads(cache_disk_file.read_text(encoding="utf-8"))
                if disk_data.get("timestamp", 0) > now_ts - 86400 and disk_data.get("tokens"):
                    self._scrip_token_cache.update(disk_data["tokens"])
                    return
            except Exception:
                pass

        scrip_txt = self.download_scrip_master()
        if not scrip_txt:
            return

        # 2. Try JSON parsing (mStock returns JSON array of instruments)
        try:
            items = json.loads(scrip_txt)
            if isinstance(items, list):
                for item in items:
                    tok = str(item.get("token") or "").strip()
                    sym = str(item.get("symbol") or "").strip().upper()
                    name = str(item.get("name") or "").strip().upper()
                    exch = str(item.get("exch_seg") or "NSE").strip().upper()
                    if tok and sym:
                        self._scrip_token_cache[f"{exch}:{sym}"] = tok
                        if sym.endswith("-EQ"):
                            self._scrip_token_cache[f"{exch}:{sym[:-3]}"] = tok
                    if tok and name:
                        self._scrip_token_cache[f"{exch}:{name}"] = tok
                        if name.endswith("-EQ"):
                            self._scrip_token_cache[f"{exch}:{name[:-3]}"] = tok

                if self._scrip_token_cache:
                    try:
                        cache_disk_file.write_text(
                            json.dumps({"timestamp": now_ts, "tokens": self._scrip_token_cache}),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                return
        except Exception:
            pass

        # 3. CSV fallback
        for line in scrip_txt.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                tok, sym = parts[0], parts[1].upper()
                exch = parts[2].upper() if len(parts) > 2 else "NSE"
                self._scrip_token_cache[f"{exch}:{sym}"] = tok
                if sym.endswith("-EQ"):
                    self._scrip_token_cache[f"{exch}:{sym[:-3]}"] = tok

    # ── Token persistence ─────────────────────────────────────

    def _load_token(self) -> bool:
        if not TOKEN_FILE.exists():
            return False
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = data.get("token", "")
            expiry = data.get("expiry", 0)
            client_code = data.get("client_code", "")

            if token and (client_code == self._client_code or not self._client_code):
                if expiry > time.time():
                    self._token = token
                    self._refresh_token = data.get("refresh_token", "")
                    self._token_expiry = expiry
                    self._client_code = client_code or self._client_code
                    if not self._api_key and data.get("api_key"):
                        self._api_key = data.get("api_key")
                    c_name = data.get("client_name")
                    if c_name:
                        self._user_profile = UserProfile(
                            user_id=self._client_code or "MSTOCK_USER",
                            name=c_name,
                            email="",
                            broker="MSTOCK",
                        )
                    return True
        except Exception:
            pass
        return False

    def _save_token(self, token: str, expiry_seconds: int = 28800, refresh_token: str = "") -> None:
        try:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Parse real JWT exp claim if present
            try:
                parts = token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    jwt_payload = json.loads(
                        base64.urlsafe_b64decode(padded.encode()).decode("utf-8")
                    )
                    jwt_exp = jwt_payload.get("exp")
                    if jwt_exp:
                        expiry_seconds = max(60, int(jwt_exp - time.time() - 120))
            except Exception:
                pass

            client_name = self._user_profile.name if self._user_profile else "m.Stock Trader"
            payload = {
                "token": token,
                "refresh_token": refresh_token,
                "client_code": self._client_code,
                "client_name": client_name,
                "api_key": self._api_key,
                "expiry": time.time() + expiry_seconds,
                "updated_at": datetime.now().isoformat(),
            }
            TOKEN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── Authentication ────────────────────────────────────────

    def is_authenticated(self) -> bool:
        """True if a valid session token is present and not expired."""
        if not self._token:
            return False
        if self._token_expiry > 0 and self._token_expiry < time.time():
            return False
        return True

    def authenticate(
        self,
        api_key: str = "",
        api_secret: str = "",
        client_code: str = "",
        password: str = "",
        totp_secret: str = "",
        force: bool = False,
    ) -> bool:
        """
        Authenticate with m.Stock Type B REST API.
        If already authenticated via active token and not forced, returns True.
        Performs official 2-step TOTP handshake:
          Step 1: POST /openapi/typeb/connect/login
          Step 2: POST /openapi/typeb/session/verifytotp
        Also gracefully supports single-step direct token mock responses for unit tests.
        """
        if not force and self.is_authenticated():
            return True
        if force:
            self._token = ""
            self._token_expiry = 0

        ak = api_key or self._api_key
        cc = client_code or self._client_code
        pwd = password or self._password
        totp_s = totp_secret or self._totp_secret

        if not cc:
            return False

        try:
            # Step 1: Login
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/connect/login"
            headers = {
                "X-Mirae-Version": "1",
                "Content-Type": "application/json",
            }
            if ak:
                headers["X-PrivateKey"] = ak
            payload = {
                "clientcode": cc,
                "password": pwd,
                "totp": "",
                "state": "",
            }
            resp = self._client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                res_data = data.get("data") or data.get("result") or data
                refresh_token = (
                    res_data.get("refreshToken")
                    or res_data.get("jwtToken")
                    or data.get("token", "")
                )

                # Step 2: Verify TOTP if totp_secret is present
                totp_code = ""
                if totp_s:
                    try:
                        import pyotp

                        totp_code = pyotp.TOTP(totp_s.strip()).now()
                    except ImportError:
                        pass

                if totp_code and refresh_token and ak:
                    v_url = f"{MSTOCK_BASE_URL}/openapi/typeb/session/verifytotp"
                    v_headers = {
                        "X-Mirae-Version": "1",
                        "X-PrivateKey": ak,
                        "Content-Type": "application/json",
                    }
                    v_body = {
                        "refreshToken": refresh_token,
                        "totp": totp_code,
                    }
                    v_resp = self._client.post(v_url, json=v_body, headers=v_headers)
                    if v_resp.status_code == 200:
                        v_data = v_resp.json()
                        v_res = v_data.get("data") or v_data.get("result") or v_data
                        jwt_token = (
                            v_res.get("jwtToken") or v_res.get("token") or v_res.get("accessToken")
                        )
                        if jwt_token:
                            self._token = jwt_token
                            self._client_code = cc
                            self._token_expiry = time.time() + 86400
                            client_name = (
                                v_res.get("ClientName")
                                or v_res.get("CLIENTNAME")
                                or "m.Stock Trader"
                            )
                            self._user_profile = UserProfile(
                                user_id=cc,
                                name=client_name,
                                email="",
                                broker="MSTOCK",
                            )
                            self._save_token(jwt_token, refresh_token=refresh_token)
                            return True

                # Direct token fallback (for test mocks or single-step responses)
                direct_token = (
                    res_data.get("jwtToken") or res_data.get("token") or res_data.get("accessToken")
                )
                if direct_token:
                    self._token = direct_token
                    self._client_code = cc
                    self._token_expiry = time.time() + 86400
                    self._save_token(direct_token, refresh_token=refresh_token)
                    return True
        except Exception:
            pass
        return False

    def get_login_url(self) -> str:
        """Returns the m.Stock OAuth authorization URL."""
        return f"{MSTOCK_AUTH_URL}/login/?platform_key={self._api_key}&redirect_url={self._redirect_uri}"

    def complete_login(
        self,
        token: str = "",
        auth_code: str = "",
        request_token: str = "",
        code: str = "",
        jwt: str = "",
        **kwargs,
    ) -> UserProfile:
        """
        Exchange or accept redirected token from m.Stock callback.
        Supports query parameters 'token', 'auth_token', 'jwt', 'request_token', 'code'.
        """
        candidate_token = (
            token or jwt or auth_code or request_token or code or kwargs.get("auth_token", "")
        )

        if not candidate_token:
            if not self.authenticate():
                raise RuntimeError(
                    "m.Stock authentication failed; no active session or authorization token found. "
                    "Verify your MSTOCK_API_KEY and credentials, or log in via the m.Stock OAuth portal."
                )
        else:
            self._token = candidate_token
            self._token_expiry = time.time() + 86400
            self._save_token(self._token)

        return self.get_profile()

    def generate_session(self, request_token: str, otp: str, api_key: str = "") -> bool:
        """
        Generate session access token using request/refresh token and SMS/email OTP
        (POST /openapi/typeb/session/token).
        """
        ak = api_key or self._api_key
        url = f"{MSTOCK_BASE_URL}/openapi/typeb/session/token"
        headers = self._headers()
        if ak:
            headers["X-PrivateKey"] = ak
        payload = {"refreshToken": request_token, "otp": str(otp)}
        try:
            resp = self._client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                res = data.get("data") or data.get("result") or data
                if isinstance(res, list) and res:
                    res = res[0]
                jwt_token = res.get("jwtToken") or res.get("token") or res.get("accessToken")
                if jwt_token:
                    self._token = jwt_token
                    self._token_expiry = time.time() + 86400
                    self._save_token(jwt_token, refresh_token=request_token)
                    return True
        except Exception:
            pass
        return False

    def logout(self) -> None:
        """Terminate active session on m.Stock server and clear local session file."""
        if self._token:
            try:
                url = f"{MSTOCK_BASE_URL}/openapi/typeb/logout"
                self._fetch_authed("GET", url)
            except Exception:
                pass
        self._token = ""
        self._user_profile = None
        if TOKEN_FILE.exists():
            try:
                TOKEN_FILE.unlink()
            except Exception:
                pass
        if hasattr(self, "_client") and self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def close(self) -> None:
        """Alias for logout to conform to standard resource close protocol."""
        self.logout()

    # ── Headers Helper ────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Mirae-Version": "1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._api_key:
            headers["X-PrivateKey"] = self._api_key
        return headers

    def _fetch_authed(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute request with automatic transparent re-auth retry on 401/403."""
        headers = self._headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        m = method.upper()
        if m == "GET":
            resp = self._client.get(url, headers=headers, **kwargs)
        elif m == "POST":
            resp = self._client.post(url, headers=headers, **kwargs)
        elif m == "PUT":
            resp = self._client.put(url, headers=headers, **kwargs)
        elif m == "DELETE":
            resp = self._client.delete(url, headers=headers, **kwargs)
        else:
            resp = self._client.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 429:
            time.sleep(0.5)
            headers = self._headers()
            if "headers" in kwargs:
                headers.update(kwargs["headers"])
            if m == "GET":
                resp = self._client.get(url, headers=headers, **kwargs)
            elif m == "POST":
                resp = self._client.post(url, headers=headers, **kwargs)
            elif m == "PUT":
                resp = self._client.put(url, headers=headers, **kwargs)
            elif m == "DELETE":
                resp = self._client.delete(url, headers=headers, **kwargs)
            else:
                resp = self._client.request(method, url, headers=headers, **kwargs)

        if (
            resp.status_code in (401, 403)
            and self._client_code
            and self._password
            and self._totp_secret
        ):
            if self.authenticate(force=True):
                headers = self._headers()
                if m == "GET":
                    resp = self._client.get(url, headers=headers, **kwargs)
                elif m == "POST":
                    resp = self._client.post(url, headers=headers, **kwargs)
                elif m == "PUT":
                    resp = self._client.put(url, headers=headers, **kwargs)
                elif m == "DELETE":
                    resp = self._client.delete(url, headers=headers, **kwargs)
                else:
                    resp = self._client.request(method, url, headers=headers, **kwargs)
        return resp

    # ── User Profile & Funds ──────────────────────────────────

    def get_profile(self) -> UserProfile:
        """Fetch user profile details from m.Stock."""
        if self._user_profile:
            return self._user_profile

        name = "m.Stock Trader"
        email = ""
        uid = self._client_code or "MSTOCK_USER"

        self._user_profile = UserProfile(
            user_id=uid,
            name=name,
            email=email,
            broker="MSTOCK",
        )
        return self._user_profile

    def get_funds(self) -> Funds:
        """Fetch available funds and margin utilization."""
        if not self._token:
            return Funds(available_cash=0.0, used_margin=0.0, total_balance=0.0)

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/user/fundsummary"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                item = (
                    items[0]
                    if isinstance(items, list) and items
                    else (items if isinstance(items, dict) else {})
                )
                avail = float(
                    item.get("AVAILABLE_BALANCE")
                    or item.get("CLEAR_BALANCE")
                    or item.get("availableMargin")
                    or item.get("netMargin")
                    or item.get("available_cash")
                    or 0.0
                )
                used = float(
                    item.get("AMOUNT_UTILIZED")
                    or item.get("usedMargin")
                    or item.get("marginUsed")
                    or 0.0
                )
                total = float(item.get("LIMIT_SOD") or item.get("totalMargin") or (avail + used))
                return Funds(available_cash=avail, used_margin=used, total_balance=total)
        except Exception:
            pass

        return Funds(available_cash=0.0, used_margin=0.0, total_balance=0.0)

    # ── Portfolio & Positions ─────────────────────────────────

    def get_holdings(self) -> list[Holding]:
        """Fetch long-term delivery (CNC) holdings."""
        if not self._token:
            return []

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/portfolio/holdings"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                if isinstance(items, dict):
                    items = items.get("holdings", [])
                if not isinstance(items, list):
                    items = []
                holdings = []
                for item in items:
                    qty = int(item.get("quantity") or item.get("totalQty") or 0)
                    avg = float(
                        item.get("averageprice")
                        or item.get("avgPrice")
                        or item.get("averagePrice")
                        or 0.0
                    )
                    ltp = float(item.get("ltp") or item.get("lastPrice") or avg)
                    pnl = float(item.get("pnl") or ((ltp - avg) * qty))
                    pnl_pct = (pnl / (avg * qty) * 100.0) if avg and qty else 0.0
                    sym = (
                        item.get("tradingsymbol")
                        or item.get("symbol")
                        or item.get("tradingSymbol")
                        or ""
                    )
                    holdings.append(
                        Holding(
                            symbol=sym,
                            exchange=item.get("exchange") or "NSE",
                            quantity=qty,
                            avg_price=avg,
                            last_price=ltp,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            day_change=float(item.get("dayChange") or 0.0),
                            day_change_pct=float(item.get("dayChangePct") or 0.0),
                        )
                    )
                return holdings
        except Exception:
            pass

        return []

    def get_positions(self) -> list[Position]:
        """Fetch open intraday and F&O positions."""
        if not self._token:
            return []

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/portfolio/positions"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or data
                if isinstance(items, dict):
                    items = items.get("positions", [])
                if not isinstance(items, list):
                    items = []
                positions = []
                for item in items:
                    qty = int(item.get("netqty") or item.get("netQty") or item.get("quantity") or 0)
                    avg = float(
                        item.get("buyavgprice")
                        or item.get("avgPrice")
                        or item.get("buyAvgPrice")
                        or 0.0
                    )
                    ltp = float(item.get("ltp") or item.get("lastPrice") or avg)
                    unrealised = float(
                        item.get("unrealisedPnl")
                        or item.get("unrealizedPnl")
                        or ((ltp - avg) * qty)
                    )
                    realised = float(item.get("realisedPnl") or item.get("realizedPnl") or 0.0)
                    sym = (
                        item.get("symbolname")
                        or item.get("tradingsymbol")
                        or item.get("symbol")
                        or item.get("tradingSymbol")
                        or ""
                    )
                    positions.append(
                        Position(
                            symbol=sym,
                            exchange=item.get("exchange") or "NSE",
                            product=item.get("producttype") or item.get("product") or "MIS",
                            quantity=qty,
                            avg_price=avg,
                            last_price=ltp,
                            pnl=unrealised + realised,
                        )
                    )
                return positions
        except Exception:
            pass
        return []

    # ── Market Data & Quotes ──────────────────────────────────

    def get_quote(self, instruments: list[str] | str) -> dict[str, Quote] | Quote:
        """
        Fetch live quote(s). Accepts either a single symbol string or a list of instruments.
        Utilizes m.Stock Type B quote API (POST /openapi/typeb/instruments/quote),
        falling back to market quote engine if unauthenticated or token not found.
        """
        is_single = isinstance(instruments, str)
        inst_list = [instruments] if is_single else list(instruments)

        quotes: dict[str, Quote] = {}
        if not self._token:
            return (
                quotes.get(instruments)
                or Quote(
                    symbol=str(instruments),
                    last_price=0.0,
                    open=0.0,
                    high=0.0,
                    low=0.0,
                    close=0.0,
                    volume=0,
                )
                if is_single
                else quotes
            )

        # 1. Partition and resolve tokens for batch query
        exchange_tokens: dict[str, list[str]] = {}
        token_to_targets: dict[tuple[str, str], list[tuple[str, str]]] = {}
        unresolved: list[tuple[str, str, str]] = []

        for inst in inst_list:
            # Fast filter: mStock only supports Indian NSE/BSE equities & indices
            if any(
                inst.startswith(p)
                for p in ("MCX:", "CRYPTO:", "CDS:", "GIFT:", "US:", "FX:", "INDEX:GIFT")
            ):
                continue

            clean_sym = (
                inst.replace("NSE:", "")
                .replace("BSE:", "")
                .replace("NFO:", "")
                .replace("BFO:", "")
                .strip()
            )
            if inst.startswith("NSE:"):
                exchange = "NSE"
            elif inst.startswith("BSE:"):
                exchange = "BSE"
            elif inst.startswith("BFO:"):
                exchange = "BFO"
            elif inst.startswith("NFO:"):
                exchange = "NFO"
            elif (
                re.search(r"\d+(?:CE|PE)$", clean_sym)
                or clean_sym.endswith("-FUT")
                or clean_sym.endswith("FUT")
            ):
                exchange = "NFO"
            else:
                exchange = "NSE"

            token = self.get_symbol_token(clean_sym, exchange)
            if token and token != clean_sym:
                token_str = str(token)
                exchange_tokens.setdefault(exchange, []).append(token_str)
                token_to_targets.setdefault((exchange, token_str), []).append((inst, clean_sym))
            else:
                unresolved.append((inst, clean_sym, exchange))

        # 2. Batch fetch via official Type B exchangeTokens API (single HTTP POST)
        url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/quote"
        if exchange_tokens:
            try:
                dedup_payload = {
                    exch: list(dict.fromkeys(toks)) for exch, toks in exchange_tokens.items()
                }
                q_payload = {"mode": "OHLC", "exchangeTokens": dedup_payload}
                resp = self._client.post(url, json=q_payload, headers=self._headers(), timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_data = data.get("data") or data.get("result") or data
                    if isinstance(raw_data, dict):
                        fetched = raw_data.get("fetched", [])
                        if not fetched and isinstance(raw_data.get("data"), list):
                            fetched = raw_data.get("data")
                    elif isinstance(raw_data, list):
                        fetched = raw_data
                    else:
                        fetched = []

                    for item in fetched:
                        exch = item.get("exchange") or "NSE"
                        tok = str(item.get("symbolToken") or item.get("token") or "")
                        ltp = float(
                            item.get("ltp")
                            or item.get("lastTradedPrice")
                            or item.get("lastPrice")
                            or 0.0
                        )
                        if ltp <= 0:
                            continue
                        close = float(item.get("close") or ltp)
                        change = ltp - close
                        change_pct = (change / close * 100.0) if close else 0.0

                        targets = token_to_targets.get((exch, tok)) or []
                        for orig_inst, target_sym in targets:
                            q_obj = Quote(
                                symbol=target_sym,
                                last_price=ltp,
                                open=float(item.get("open") or ltp),
                                high=float(item.get("high") or ltp),
                                low=float(item.get("low") or ltp),
                                close=close,
                                volume=int(item.get("volume") or 0),
                                change=round(change, 2),
                                change_pct=round(change_pct, 2),
                            )
                            quotes[orig_inst] = q_obj
                            quotes[target_sym] = q_obj
            except Exception:
                pass

        # 3. Fallback for remaining unresolved instruments
        remaining = [
            (inst, sym, exch)
            for inst, sym, exch in unresolved
            if inst not in quotes and sym not in quotes
        ]
        for inst, clean_sym, exchange in remaining:
            if clean_sym.startswith("MCX"):
                continue
            try:
                resp = self._client.get(
                    url,
                    params={"symbol": clean_sym, "exchange": exchange},
                    headers=self._headers(),
                    timeout=2.5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    res = data.get("result") or data.get("data") or data
                    if isinstance(res, list) and res:
                        res = res[0]
                    if isinstance(res, dict) and (res.get("ltp") or res.get("lastPrice")):
                        ltp = float(res.get("ltp") or res.get("lastPrice") or 0.0)
                        close = float(res.get("close") or res.get("prevClose") or ltp)
                        change = ltp - close
                        change_pct = (change / close * 100.0) if close else 0.0
                        if ltp > 0:
                            q_obj = Quote(
                                symbol=clean_sym,
                                last_price=ltp,
                                open=float(res.get("open") or ltp),
                                high=float(res.get("high") or ltp),
                                low=float(res.get("low") or ltp),
                                close=close,
                                volume=int(res.get("volume") or 0),
                                change=round(change, 2),
                                change_pct=round(change_pct, 2),
                            )
                            quotes[inst] = q_obj
                            quotes[clean_sym] = q_obj
            except Exception:
                pass

        if is_single:
            return quotes.get(instruments) or Quote(
                symbol=instruments, last_price=0.0, open=0.0, high=0.0, low=0.0, close=0.0, volume=0
            )
        return quotes

    # ── Option Chain APIs ─────────────────────────────────────

    def get_option_chain_master(self, exchange: int = 2) -> dict:
        """
        Fetch Option Chain Master data (GET /openapi/typeb/getoptionchainmaster/{exch}).
        Returns expiry mappings (dctExp), index option tokens (OPTIDX),
        stock option mappings (OFSTK), and index future tokens (FUTIDX).
        Results are cached in-memory for 15 minutes to avoid redundant network calls.
        """
        cache_key = f"master_{exchange}"
        cached = getattr(self, "_option_master_cache", {}).get(cache_key)
        if cached and time.time() - cached.get("time", 0) < 900:
            return cached.get("data", {})

        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/getoptionchainmaster/{exchange}"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                master_data = data.get("data") or data.get("result") or data
                if not hasattr(self, "_option_master_cache"):
                    self._option_master_cache = {}
                self._option_master_cache[cache_key] = {
                    "time": time.time(),
                    "data": master_data,
                }
                return master_data
        except Exception:
            pass
        return {}

    def get_expiries(self, underlying: str) -> list[str]:
        """
        Return all available sorted expiry dates (YYYY-MM-DD) for an underlying
        directly from m.Stock Option Chain Master.
        """
        clean_sym = underlying.replace("NSE:", "").replace("BSE:", "").upper().strip()
        if not self._token:
            self.authenticate()
        try:
            master = self.get_option_chain_master(exchange=2)
            dct_exp = master.get("dctExp", {})
            opt_idx = master.get("OPTIDX", [])
            of_stk = master.get("OFSTK", [])

            symbol_exp_keys = []
            for row in opt_idx:
                parts = row.split(",")
                if parts and parts[0].strip() == clean_sym:
                    symbol_exp_keys = [k.strip() for k in parts[2:] if k.strip()]
                    break
            if not symbol_exp_keys:
                for row in of_stk:
                    parts = row.split(",")
                    if parts and parts[0].strip() == clean_sym:
                        symbol_exp_keys = [k.strip() for k in parts[2:] if k.strip()]
                        break

            keys_to_check = symbol_exp_keys if symbol_exp_keys else list(dct_exp.keys())
            dates = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            for k in keys_to_check:
                if k in dct_exp:
                    try:
                        ep_int = int(dct_exp[k])
                        dt = datetime.fromtimestamp(ep_int)
                        if dt.year < 2026:
                            dt = dt.replace(year=dt.year + 10)
                        d_str = dt.strftime("%Y-%m-%d")
                        if d_str >= today_str:
                            dates.append(d_str)
                    except Exception:
                        pass
            return sorted(set(dates)) if dates else []
        except Exception:
            return []

    def get_options_chain(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> list[OptionsContract]:
        """
        Fetch live options chain for any equity or benchmark index using
        m.Stock Type B Option Chain APIs:
          1. GET /openapi/typeb/getoptionchainmaster/{exch}
          2. GET /openapi/typeb/GetOptionChain/{exch}/{expiry}/{token}
          3. Batch quote lookup (mode=OHLC) centered on ATM strikes.
        Falls back seamlessly to the market engine (NSE scraper) if session is unauthenticated
        or if m.Stock API encounters an error.
        """
        clean_sym = underlying.replace("NSE:", "").replace("BSE:", "").upper().strip()

        # Attempt native m.Stock Option Chain if token available
        if not self._token:
            self.authenticate()

        if self._token:
            try:
                master = self.get_option_chain_master(exchange=2)
                dct_exp = master.get("dctExp", {})
                opt_idx = master.get("OPTIDX", [])
                of_stk = master.get("OFSTK", [])

                token = ""
                symbol_exp_keys: list[str] = []
                # 1. Resolve token and expiry keys from OPTIDX (e.g. "NIFTY,26000,8,9,2,...")
                for row in opt_idx:
                    parts = row.split(",")
                    if parts and parts[0].strip() == clean_sym:
                        token = parts[1].strip()
                        symbol_exp_keys = [k.strip() for k in parts[2:] if k.strip()]
                        break

                # 2. Resolve token and expiry keys from OFSTK (e.g. "ACC,22,2,3,4")
                if not token:
                    for row in of_stk:
                        parts = row.split(",")
                        if parts and parts[0].strip() == clean_sym:
                            token = parts[1].strip()
                            symbol_exp_keys = [k.strip() for k in parts[2:] if k.strip()]
                            break

                # 3. Resolve from known tokens
                if not token:
                    token = _KNOWN_NSE_TOKENS.get(clean_sym, "")

                if token and dct_exp:
                    chosen_epoch = None
                    resolved_expiry_str = None

                    candidates: list[tuple[int, str]] = []
                    keys_to_check = symbol_exp_keys if symbol_exp_keys else list(dct_exp.keys())
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    for k in keys_to_check:
                        if k in dct_exp:
                            try:
                                ep_int = int(dct_exp[k])
                                dt = datetime.fromtimestamp(ep_int)
                                if dt.year < 2026:
                                    dt = dt.replace(year=dt.year + 10)
                                date_str = dt.strftime("%Y-%m-%d")
                                if date_str >= today_str:
                                    candidates.append((ep_int, date_str))
                            except Exception:
                                continue

                    # Strictly sort candidates chronologically so candidates[0] is always the nearest active expiry
                    candidates.sort(key=lambda x: (x[1], x[0]))

                    if expiry:
                        target_clean = expiry.strip()
                        for ep_int, date_str in candidates:
                            if date_str == target_clean or (
                                len(target_clean) >= 5 and date_str.endswith(target_clean[-5:])
                            ):
                                chosen_epoch = ep_int
                                resolved_expiry_str = date_str
                                break

                    if not chosen_epoch and candidates:
                        chosen_epoch = candidates[0][0]
                        resolved_expiry_str = candidates[0][1]

                    if chosen_epoch:
                        url = f"{MSTOCK_BASE_URL}/openapi/typeb/GetOptionChain/2/{chosen_epoch}/{token}"
                        resp = self._fetch_authed("GET", url)
                        if resp.status_code == 200:
                            data = resp.json()
                            chain_data = data.get("data") or data.get("result") or data
                            calls_raw = chain_data.get("call", [])
                            puts_raw = chain_data.get("put", [])
                            c_model = chain_data.get("contractModel") or {}
                            if isinstance(c_model, dict) and c_model.get("exp"):
                                try:
                                    dt_exp = datetime.strptime(c_model["exp"].strip(), "%d-%b-%Y")
                                    resolved_expiry_str = dt_exp.strftime("%Y-%m-%d")
                                except Exception:
                                    pass

                            expiry_str = resolved_expiry_str or datetime.fromtimestamp(
                                chosen_epoch
                            ).strftime("%Y-%m-%d")
                            contracts: list[OptionsContract] = []
                            token_map: dict[str, OptionsContract] = {}

                            # Parse calls
                            for item in calls_raw:
                                parts = item.split(",") if isinstance(item, str) else []
                                if len(parts) >= 2:
                                    c_token, s_raw = parts[0].strip(), float(parts[1].strip())
                                    strike = s_raw / 100.0 if s_raw >= 1000 else s_raw
                                    oi = int(parts[2].strip()) if len(parts) >= 3 else 0
                                    vol = int(parts[3].strip()) if len(parts) >= 4 else 0
                                    c_obj = OptionsContract(
                                        symbol=f"{clean_sym}{expiry_str.replace('-', '')}{int(strike)}CE",
                                        underlying=clean_sym,
                                        expiry=expiry_str,
                                        strike=strike,
                                        option_type="CE",
                                        last_price=0.0,
                                        oi=oi,
                                        oi_change=0,
                                        volume=vol,
                                        exchange="NFO",
                                    )
                                    contracts.append(c_obj)
                                    token_map[c_token] = c_obj

                            # Parse puts
                            for item in puts_raw:
                                parts = item.split(",") if isinstance(item, str) else []
                                if len(parts) >= 2:
                                    p_token, s_raw = parts[0].strip(), float(parts[1].strip())
                                    strike = s_raw / 100.0 if s_raw >= 1000 else s_raw
                                    oi = int(parts[2].strip()) if len(parts) >= 3 else 0
                                    vol = int(parts[3].strip()) if len(parts) >= 4 else 0
                                    p_obj = OptionsContract(
                                        symbol=f"{clean_sym}{expiry_str.replace('-', '')}{int(strike)}PE",
                                        underlying=clean_sym,
                                        expiry=expiry_str,
                                        strike=strike,
                                        option_type="PE",
                                        last_price=0.0,
                                        oi=oi,
                                        oi_change=0,
                                        volume=vol,
                                        exchange="NFO",
                                    )
                                    contracts.append(p_obj)
                                    token_map[p_token] = p_obj

                            # Batch enrich quotes with OHLC mode centered on ATM strikes
                            if token_map:
                                try:
                                    spot_est = 0.0
                                    try:
                                        from market.quotes import get_ltp

                                        fetched_spot = get_ltp(clean_sym)
                                        if fetched_spot and fetched_spot > 0:
                                            spot_est = float(fetched_spot)
                                    except Exception:
                                        pass

                                    if spot_est <= 0 and contracts:
                                        all_strikes = sorted({c.strike for c in contracts})
                                        spot_est = all_strikes[len(all_strikes) // 2]

                                    ce_contracts = sorted(
                                        [c for c in contracts if c.option_type == "CE"],
                                        key=lambda c: abs(c.strike - spot_est),
                                    )
                                    pe_contracts = sorted(
                                        [c for c in contracts if c.option_type == "PE"],
                                        key=lambda c: abs(c.strike - spot_est),
                                    )

                                    atm_contracts = ce_contracts[:25] + pe_contracts[:25]
                                    contract_to_tok = {id(v): k for k, v in token_map.items()}
                                    atm_tokens = [
                                        contract_to_tok[id(c)]
                                        for c in atm_contracts
                                        if id(c) in contract_to_tok
                                    ]

                                    if atm_tokens:
                                        q_url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/quote"
                                        q_resp = self._fetch_authed(
                                            "POST",
                                            q_url,
                                            json={
                                                "mode": "OHLC",
                                                "exchangeTokens": {"NFO": atm_tokens},
                                            },
                                            timeout=4.0,
                                        )
                                        if q_resp.status_code == 200:
                                            q_data = q_resp.json()
                                            fetched = q_data.get("data", {}).get("fetched", [])
                                            for item in fetched:
                                                tok = str(item.get("symbolToken", ""))
                                                c = token_map.get(tok)
                                                if not c:
                                                    continue
                                                ltp = float(item.get("ltp") or 0.0)
                                                if ltp > 0:
                                                    c.last_price = ltp
                                                    c.bid = round(ltp * 0.999, 2)
                                                    c.ask = round(ltp * 1.001, 2)
                                                    c.bid_qty = 65
                                                    c.ask_qty = 65
                                                high_p = float(item.get("high") or 0.0)
                                                if high_p > 0:
                                                    c.high = high_p
                                                low_p = float(item.get("low") or 0.0)
                                                if low_p > 0:
                                                    c.low = low_p
                                                open_p = float(item.get("open") or 0.0)
                                                if open_p > 0:
                                                    c.open = open_p
                                                close_p = float(item.get("close") or 0.0)
                                                if close_p > 0:
                                                    c.close = close_p
                                                    if ltp > 0:
                                                        c.pchange = round(
                                                            ((ltp - close_p) / close_p) * 100.0, 2
                                                        )
                                except Exception:
                                    pass

                            if contracts and any(
                                float(getattr(c, "last_price", 0.0) or 0.0) > 0 for c in contracts
                            ):
                                return contracts
            except Exception:
                pass

        # Defensive fallback to institutional NSE scraper engine
        from market.nse_scraper import nse_get_options_chain

        return nse_get_options_chain(underlying, expiry)

    def get_history(
        self,
        symbol: str,
        resolution: str = "D",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ):
        """
        Fetch historical OHLCV data.
        Maps resolution to m.Stock Type B intervals (ONE_DAY, ONE_MINUTE, etc.)
        when token is mapped, or smoothly falls back to Chanakya's historical engine.
        """
        import pandas as pd

        clean_sym = symbol.replace("NSE:", "").replace("BSE:", "")
        exchange = "BSE" if symbol.startswith("BSE:") else "NSE"
        token = _KNOWN_NSE_TOKENS.get(clean_sym, "")

        interval_map = {
            "D": "ONE_DAY",
            "1D": "ONE_DAY",
            "1": "ONE_MINUTE",
            "1m": "ONE_MINUTE",
            "5": "FIVE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15": "FIFTEEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "60": "ONE_HOUR",
            "1h": "ONE_HOUR",
        }
        interval = interval_map.get(str(resolution).upper(), "ONE_DAY")

        if self._token and token:
            try:
                url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/historical"
                f_date = from_date.strftime("%Y-%m-%d %H:%M") if from_date else "2024-01-01 09:15"
                t_date = (
                    to_date.strftime("%Y-%m-%d %H:%M")
                    if to_date
                    else datetime.now().strftime("%Y-%m-%d %H:%M")
                )
                h_payload = {
                    "exchange": exchange,
                    "symboltoken": str(token),
                    "interval": interval,
                    "fromdate": f_date,
                    "todate": t_date,
                }
                resp = self._client.post(url, json=h_payload, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    candles = (
                        data.get("data", {}).get("candles", [])
                        if isinstance(data.get("data"), dict)
                        else []
                    )
                    if candles:
                        df = pd.DataFrame(
                            candles,
                            columns=["timestamp", "open", "high", "low", "close", "volume"],
                        )
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df.set_index("timestamp", inplace=True)
                        df.index = df.index.tz_localize(None)
                        return df
            except Exception:
                pass

        try:
            from market.history import get_history

            return get_history(symbol, resolution=resolution, from_date=from_date, to_date=to_date)
        except Exception:
            import pandas as pd

            return pd.DataFrame()

    # ── Order Execution ───────────────────────────────────────

    def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Place an order through m.Stock (POST /openapi/typeb/orders/regular).
        Strictly enforces the live trading gate ALLOW_LIVE_TRADING=1.
        """
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError(
                "Live trading disabled. Set ALLOW_LIVE_TRADING=1 to execute live orders with m.Stock."
            )

        if not self._token:
            raise RuntimeError(
                "m.Stock session not authenticated. Please log in before placing orders."
            )

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/regular"
            clean_sym = order.symbol.replace("NSE:", "").replace("BSE:", "").strip()
            exchange = _EXCHANGE_MAP.get(order.exchange, "NSE")
            token = self.get_symbol_token(clean_sym, exchange)
            product = _PRODUCT_MAP.get(order.product, order.product)
            order_type = _ORDER_TYPE_MAP.get(order.order_type, "MARKET")

            # Trading symbol format (e.g. ACC-EQ for NSE equity)
            trading_symbol = clean_sym
            if (
                exchange == "NSE"
                and not clean_sym.endswith("-EQ")
                and not any(p in clean_sym for p in ("-INDEX", "NIFTY", "BANKNIFTY", "VIX"))
            ):
                trading_symbol = f"{clean_sym}-EQ"

            payload = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": str(token),
                "exchange": exchange,
                "transactiontype": order.transaction_type.upper(),
                "ordertype": order_type,
                "quantity": str(order.quantity),
                "producttype": product,
                "price": str(order.price if order_type != "MARKET" else "0"),
                "triggerprice": str(order.trigger_price or "0"),
                "squareoff": "0",
                "stoploss": "0",
                "trailingStopLoss": "",
                "disclosedquantity": "0",
                "duration": "DAY",
                "ordertag": "",
            }
            resp = self._client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    data = data[0]
                res = data.get("data") or data.get("result") or data
                if isinstance(res, list) and res:
                    res = res[0]
                order_id = str(
                    res.get("orderId") or res.get("order_id") or res.get("orderid") or ""
                )
                if order_id:
                    return OrderResponse(
                        order_id=order_id,
                        status="PLACED",
                        message="Order placed successfully with m.Stock",
                        average_price=order.price,
                        filled_quantity=order.quantity,
                    )
            raise RuntimeError(f"m.Stock order placement failed: {resp.text}")
        except Exception as e:
            if isinstance(e, PermissionError):
                raise
            raise RuntimeError(f"Failed to place order with m.Stock: {e}")

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """Cancel an open order (DELETE /openapi/typeb/orders/regular/{order_id})."""
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError("Live trading disabled. Set ALLOW_LIVE_TRADING=1.")

        if not self._token:
            return False

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/regular/{order_id}"
            payload = {"variety": variety, "orderid": str(order_id)}
            resp = self._client.request("DELETE", url, json=payload, headers=self._headers())
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def cancel_all(self) -> dict:
        """Cancel all open orders at once (POST /openapi/typeb/orders/cancelall)."""
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError("Live trading disabled. Set ALLOW_LIVE_TRADING=1.")
        if not self._token:
            raise RuntimeError("m.Stock session not authenticated.")
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/cancelall"
            resp = self._client.post(url, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data") or data.get("result") or data
            raise RuntimeError(f"Cancel all orders failed: {resp.text}")
        except Exception as e:
            if isinstance(e, PermissionError):
                raise
            raise RuntimeError(f"Failed to cancel all orders with m.Stock: {e}")

    def get_order_details(self, order_id: str) -> dict:
        """Retrieve individual order status details by order ID (POST /openapi/typeb/order/details)."""
        if not self._token:
            return {}
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/order/details"
            payload = {"order_no": str(order_id)}
            resp = self._client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    data = data[0]
                return data.get("data") or data.get("result") or data
        except Exception:
            pass
        return {}

    def get_trade_book(self) -> list[dict]:
        """Fetch trade executions for today (GET /openapi/typeb/tradebook)."""
        if not self._token:
            return []
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/tradebook"
            resp = self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or []
                return items if isinstance(items, list) else []
        except Exception:
            pass
        return []

    def get_trade_history(self, from_date: str, to_date: str) -> list[dict]:
        """Fetch trade history within date range (POST /openapi/typeb/trades)."""
        if not self._token:
            return []
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/trades"
            payload = {"fromdate": from_date, "todate": to_date}
            resp = self._client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or []
                return items if isinstance(items, list) else []
        except Exception:
            pass
        return []

    def get_health_statistics(self) -> dict:
        """Fetch m.Stock API server health statistics (GET /openapi/typeb/Health/GetHealthStatistics)."""
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/Health/GetHealthStatistics"
            resp = self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_orders(self) -> list[Order]:
        """Return orders placed today (GET /openapi/typeb/orders)."""
        if not self._token:
            return []
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders"
            resp = self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                raw_json = resp.json()
                if isinstance(raw_json, list) and raw_json:
                    raw = raw_json
                else:
                    raw = raw_json.get("data") or raw_json.get("result", raw_json)
                if isinstance(raw, dict):
                    raw = raw.get("orders", [])
                if not isinstance(raw, list):
                    raw = []
                orders = []
                for o in raw:
                    if not isinstance(o, dict):
                        continue
                    raw_st = str(o.get("status") or o.get("orderstatus") or "OPEN").upper()
                    st_map = {
                        "TRANSIT": "OPEN",
                        "PENDING": "PENDING",
                        "COMPLETE": "FILLED",
                        "EXECUTED": "FILLED",
                        "CANCELLED": "CANCELLED",
                        "CANCELED": "CANCELLED",
                        "REJECTED": "REJECTED",
                        "OPEN": "OPEN",
                    }
                    status = st_map.get(raw_st, raw_st)
                    prod = _REV_PRODUCT_MAP.get(
                        o.get("producttype") or o.get("product") or "DELIVERY", "CNC"
                    )
                    orders.append(
                        Order(
                            order_id=str(o.get("orderid") or o.get("orderId") or o.get("order_id")),
                            symbol=str(o.get("tradingsymbol") or o.get("symbol") or ""),
                            exchange=str(o.get("exchange") or "NSE"),
                            transaction_type=str(
                                o.get("transactiontype") or o.get("transactionType") or "BUY"
                            ),
                            order_type=str(o.get("ordertype") or o.get("orderType") or "LIMIT"),
                            product=prod,
                            quantity=int(o.get("quantity") or 0),
                            price=float(o.get("price") or 0.0),
                            status=status,
                            filled_quantity=int(
                                o.get("filledshares") or o.get("filledQuantity") or 0
                            ),
                        )
                    )
                return orders
        except Exception:
            pass
        return []

    def modify_order(
        self,
        order_id: str,
        quantity: int,
        price: float,
        trigger_price: float = 0.0,
        order_type: str = "LIMIT",
        product_type: str = "DELIVERY",
        duration: str = "DAY",
        trading_symbol: str = "",
        symbol_token: str = "",
        exchange: str = "NSE",
        variety: str = "NORMAL",
    ) -> OrderResponse:
        """
        Modify an open order (PUT /openapi/typeb/orders/regular/{order_id}).
        Strictly enforces live trading safety gate ALLOW_LIVE_TRADING=1.
        """
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError(
                "Live trading disabled. Set ALLOW_LIVE_TRADING=1 to modify live orders with m.Stock."
            )

        if not self._token:
            raise RuntimeError("m.Stock session not authenticated.")

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/orders/regular/{order_id}"
            prod = _PRODUCT_MAP.get(product_type, product_type)
            ot = _ORDER_TYPE_MAP.get(order_type, order_type)
            payload = {
                "variety": variety,
                "orderid": str(order_id),
                "ordertype": ot,
                "producttype": prod,
                "duration": duration,
                "price": str(price),
                "quantity": str(quantity),
                "tradingsymbol": trading_symbol,
                "symboltoken": str(symbol_token),
                "exchange": _EXCHANGE_MAP.get(exchange, exchange),
                "triggerprice": str(trigger_price),
            }
            resp = self._client.put(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    data = data[0]
                res = data.get("data") or data.get("result") or data
                if isinstance(res, list) and res:
                    res = res[0]
                return OrderResponse(
                    order_id=str(res.get("orderId") or res.get("orderid") or order_id),
                    status="MODIFIED",
                    message="Order modified successfully",
                    average_price=price,
                    filled_quantity=0,
                )
            raise RuntimeError(f"m.Stock order modification failed: {resp.text}")
        except Exception as e:
            if isinstance(e, PermissionError):
                raise
            raise RuntimeError(f"Failed to modify order with m.Stock: {e}")

    # ── Margin Calculation APIs ───────────────────────────────

    def calculate_order_margin(self, orders: list[dict]) -> dict:
        """
        Calculate required margin for single or multi-leg orders
        (POST /openapi/typeb/margins/orders).
        Returns SPAN, VAR, Exposure, Brokerage, and total required margin.
        """
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/margins/orders"
            payload = {"orders": orders}
            resp = self._fetch_authed("POST", url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data") or data.get("result") or data
        except Exception:
            pass
        return {}

    # ── Top Gainers / Losers API ──────────────────────────────

    def get_gainers_losers(
        self,
        exchange: int = 1,
        security_id_code: int = 13,
        segment: int = 1,
        type_flag: str = "G",
    ) -> list[dict]:
        """
        Fetch top gainers or losers (POST /openapi/typeb/losergainer).
        type_flag: "G" for gainers, "L" for losers.
        """
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/losergainer"
            payload = {
                "Exchange": exchange,
                "SecurityIdCode": security_id_code,
                "segment": segment,
                "TypeFlag": type_flag.upper(),
            }
            resp = self._fetch_authed("POST", url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("result") or []
                return items if isinstance(items, list) else []
        except Exception:
            pass
        return []

    # ── Basket Order APIs ─────────────────────────────────────

    def create_basket(self, name: str, description: str = "") -> dict:
        """Create a new basket for multi-leg execution (POST /openapi/typeb/CreateBasket)."""
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/CreateBasket"
            payload = {"BaskName": name, "BaskDesc": description or f"Basket {name}"}
            resp = self._fetch_authed("POST", url, json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"status": False, "message": "Failed to create basket"}

    def fetch_baskets(self) -> list[dict]:
        """Fetch all user baskets (GET /openapi/typeb/FetchBasket)."""
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/FetchBasket"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                data = resp.json()
                baskets = data.get("data") or data.get("result") or []
                return baskets if isinstance(baskets, list) else []
        except Exception:
            pass
        return []

    def rename_basket(self, basket_id: str, new_name: str) -> dict:
        """Rename an existing basket (PUT /openapi/typeb/RenameBasket)."""
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/RenameBasket"
            payload = {"basketName": new_name, "BasketId": str(basket_id)}
            resp = self._fetch_authed("PUT", url, json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"status": False, "message": "Failed to rename basket"}

    def delete_basket(self, basket_id: str) -> dict:
        """Delete an existing basket by ID (DELETE /openapi/typeb/DeleteBasket)."""
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/DeleteBasket"
            payload = {"BasketId": str(basket_id)}
            resp = self._fetch_authed("DELETE", url, json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"status": False, "message": "Failed to delete basket"}

    def calculate_basket(self, params_or_name: dict | str) -> dict:
        """
        Calculate margin & requirements for a basket (POST /openapi/typeb/CalculateBasket).
        Accepts full parameter dict or basket name string for basic margin calc.
        """
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/CalculateBasket"
            if isinstance(params_or_name, dict):
                payload = params_or_name
            else:
                payload = {
                    "basket_name": str(params_or_name),
                    "include_exist_pos": "0",
                    "ord_product": "DELIVERY",
                    "disc_qty": "0",
                    "segment": "1",
                    "trigger_price": "0",
                    "scriptcode": "",
                    "ord_type": "MARKET",
                    "operation": "A",
                    "order_validity": "DAY",
                    "order_qty": "1",
                    "script_stat": "0",
                    "buy_sell_indi": "B",
                    "basket_priority": "1",
                    "order_price": "0",
                    "basket_id": "",
                    "exch_id": "1",
                }
            resp = self._fetch_authed("POST", url, json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    # ── Position Conversion ───────────────────────────────────

    def convert_position(
        self,
        exchange: str,
        symbol: str,
        old_product: str,
        new_product: str,
        quantity: int,
        transaction_type: str = "BUY",
        symbol_token: str = "",
        **kwargs,
    ) -> dict:
        """
        Convert position between DELIVERY (CNC) and INTRADAY (MIS)
        (POST /openapi/typeb/portfolio/convertposition).
        """
        if os.environ.get("ALLOW_LIVE_TRADING", "0") != "1":
            raise PermissionError(
                "Live trading disabled. Set ALLOW_LIVE_TRADING=1 to execute position conversion."
            )

        if not self._token:
            raise RuntimeError("m.Stock session not authenticated.")

        clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip()
        token = (
            symbol_token or kwargs.get("symboltoken") or self.get_symbol_token(clean_sym, exchange)
        )
        old_p = _PRODUCT_MAP.get(old_product, old_product)
        new_p = _PRODUCT_MAP.get(new_product, new_product)

        payload = {
            "exchange": _EXCHANGE_MAP.get(exchange, exchange),
            "symboltoken": str(token),
            "oldproducttype": old_p,
            "newproducttype": new_p,
            "tradingsymbol": kwargs.get("tradingsymbol")
            or (f"{clean_sym}-EQ" if exchange == "NSE" else clean_sym),
            "symbolname": kwargs.get("symbolname") or clean_sym,
            "instrumenttype": kwargs.get("instrumenttype") or "EQ",
            "priceden": str(kwargs.get("priceden", "1")),
            "pricenum": str(kwargs.get("pricenum", "1")),
            "genden": str(kwargs.get("genden", "1")),
            "gennum": str(kwargs.get("gennum", "1")),
            "precision": str(kwargs.get("precision", "2")),
            "multiplier": str(kwargs.get("multiplier", "1")),
            "boardlotsize": str(kwargs.get("boardlotsize", "1")),
            "buyqty": str(
                kwargs.get("buyqty", quantity if transaction_type.upper() == "BUY" else "0")
            ),
            "sellqty": str(
                kwargs.get("sellqty", quantity if transaction_type.upper() == "SELL" else "0")
            ),
            "buyamount": str(kwargs.get("buyamount", "0")),
            "sellamount": str(kwargs.get("sellamount", "0")),
            "transactiontype": transaction_type.upper(),
            "quantity": str(quantity),
            "type": str(kwargs.get("type", "DAY")),
        }
        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/portfolio/convertposition"
            resp = self._client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Position conversion failed: {resp.text}")
        except Exception as e:
            if isinstance(e, PermissionError):
                raise
            raise RuntimeError(f"Failed to convert position with m.Stock: {e}")

    # ── Intraday Chart & Scrip Master ─────────────────────────

    def get_intraday_data(
        self,
        symbol: str,
        interval: str = "THREE_MINUTE",
    ):
        """
        Fetch intraday candle chart data (POST /openapi/typeb/instruments/intraday).
        Intervals: minute, THREE_MINUTE, FIVE_MINUTE, TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, SIXTY_MINUTE, day.
        """
        import pandas as pd

        clean_sym = symbol.replace("NSE:", "").replace("BSE:", "")
        exchange_id = "4" if symbol.startswith("BSE:") else "1"
        token = _KNOWN_NSE_TOKENS.get(clean_sym, "")

        if self._token and token:
            try:
                url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/intraday"
                payload = {
                    "exchange": exchange_id,
                    "symboltoken": token,
                    "interval": interval,
                }
                resp = self._client.post(url, json=payload, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    candles = (
                        data.get("data", {}).get("candles", [])
                        if isinstance(data.get("data"), dict)
                        else []
                    )
                    if candles:
                        df = pd.DataFrame(
                            candles,
                            columns=["timestamp", "open", "high", "low", "close", "volume"],
                        )
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df.set_index("timestamp", inplace=True)
                        df.index = df.index.tz_localize(None)
                        return df
            except Exception:
                pass
        return None

    def download_scrip_master(self) -> str:
        """
        Download consolidated Scrip Master file
        (GET /openapi/typeb/instruments/OpenAPIScripMaster).
        """
        if not self._token:
            self.authenticate()

        try:
            url = f"{MSTOCK_BASE_URL}/openapi/typeb/instruments/OpenAPIScripMaster"
            resp = self._fetch_authed("GET", url)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return ""
