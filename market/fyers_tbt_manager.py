"""
market/fyers_tbt_manager.py
───────────────────────────
Fyers Institutional 50-Level Depth (Tick-By-Tick / TBT) Manager.

Manages high-frequency 50-level Depth of Market (DOM) streams using Fyers
TBT WebSocket (`fyers_apiv3.FyersWebsocket.tbt_ws.FyersTbtSocket`).

Features:
- Dynamic subscription to active Index Options / Target Stock Contracts
- 50-slot Order Book Imbalance (OBI-50) calculation
- Institutional Iceberg / Resting Liquidity Wall detection
- Book Density & Liquidity Quality scoring
- Pre-Trade VWAP Slippage modeling through 50 price levels
- Deep Order Book Audit Gatekeeper for setup conviction
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, time as dtime, timedelta
import logging
import threading
import time
from typing import Any, Callable, Optional, Set

from engine.ring_buffer import RollingTickBuffer

logger = logging.getLogger("market.fyers_tbt")

MAX_TBT_SYMBOLS = 15
MAX_IN_FLIGHT_SLOTS = 4
MAX_CORE_GRID_SLOTS = 6
MAX_TODAYS_EXPIRY_SLOTS = 3
MAX_SCOUT_SLOTS = 10  # Elastic scout capacity: uses all unallocated slots up to 15


def _resolve_index_future(index_name: str) -> str:
    """Resolve spot index name to the active near-month tradable Index Future."""
    from market.calendar import get_active_derivative_expiry

    now = datetime.now()
    name = index_name.upper().replace(" ", "").replace("-INDEX", "")
    if name in ("NIFTY50", "NIFTY_50"):
        name = "NIFTY"
    elif name == "NIFTYBANK":
        name = "BANKNIFTY"
    elif name in ("NIFTYFINSERVICE", "FIN_NIFTY"):
        name = "FINNIFTY"
    elif name in ("NIFTYMIDCAP100", "NIFTYMIDSELECT", "MIDCAP"):
        name = "MIDCPNIFTY"

    prefix = "BSE" if name in ("SENSEX", "BANKEX") else "NSE"
    exp_date = get_active_derivative_expiry(
        name, is_future=True, ref_date=now.date(), ref_time=now.time()
    )
    return f"{prefix}:{name}{exp_date.strftime('%y%b').upper()}FUT"


def _tbt_symbol_priority(
    symbol: str, session: Optional[str] = None, ref_time: Optional[dtime] = None
) -> int:
    """
    Score symbol priority for 15-slot TBT depth allocation.
    Institutional Hierarchy:
      - Commodity/Evening Session (COMMODITY_CDS: 15:30 - 23:30 IST):
          Active MCX Options (75), MCX Futures (70), Commodities (65), USDINR (62 before 17:00, 5 post 17:00)
          are dynamically elevated above closed equity/index instruments.
      - Daytime Session (EQUITY_NFO: 09:15 - 15:30 IST) & Default:
          Index Options (60..40), Index Futures (45..38), Commodities (35..30), Cash Equities (10).
    """
    if not symbol:
        return 0
    s = symbol.upper().strip()
    is_option = s.endswith("CE") or s.endswith("PE")
    is_fut = s.endswith("FUT")
    is_mcx = s.startswith("MCX:") or any(
        c in s for c in ("CRUDE", "NATURAL", "GOLD", "SILVER", "COPPER", "ZINC", "ALUMINIUM")
    )
    is_cds = s.startswith("NSE:USDINR") or "USDINR" in s

    sess = session or get_market_session()

    # ── Evening Session (COMMODITY_CDS: 15:30 - 23:30 IST) ─────────────
    # Dynamically elevate active MCX commodities above closed daytime equities.
    # Note: Currency derivatives (CDS) close at 17:00 IST! Post-17:00, CDS priority
    # drops to 5 (below closed equities) so active MCX commodities immediately evict it.
    if sess == "COMMODITY_CDS":
        if is_option and is_mcx:
            return 75  # Live MCX Commodity Option
        if is_fut and is_mcx:
            return 70  # Live MCX Commodity Future
        if is_mcx:
            return 65  # Live Commodity
        if is_cds:
            if ref_time is not None:
                return 62 if ref_time < dtime(17, 0) else 5
            try:
                from config.constants import IST_ZONE as IST

                now_t = datetime.now(IST).time()
            except Exception:
                now_t = datetime.now().time()
            return 62 if now_t < dtime(17, 0) else 5

    # ── Daytime Session (EQUITY_NFO: 09:15 - 15:30 IST) & Standard Hierarchy ────
    # Index Options (Highest value for intraday scalping & Level-3 DOM imbalance)
    if is_option:
        if "NIFTY" in s and "BANK" not in s and "MID" not in s and "FIN" not in s:
            return 60  # NIFTY Option
        if "BANKNIFTY" in s or "BANKEX" in s:
            return 55  # BANKNIFTY Option
        if "MIDCPNIFTY" in s or "MIDCAP" in s:
            return 50  # MIDCPNIFTY Option
        if "SENSEX" in s:
            return 45  # SENSEX Option
        if "FINNIFTY" in s:
            return 40  # FINNIFTY Option
        if is_mcx:
            return 35  # Commodity Option
        return 25  # Stock Option

    # Futures
    if is_fut:
        if "NIFTY" in s and "BANK" not in s and "MID" not in s and "FIN" not in s:
            return 45  # NIFTY Future
        if "BANKNIFTY" in s:
            return 42  # BANKNIFTY Future
        if "MIDCPNIFTY" in s:
            return 40  # MIDCPNIFTY Future
        if "SENSEX" in s:
            return 38  # SENSEX Future
        if is_mcx or is_cds:
            return 32  # Commodity / Currency Future
        return 20  # Stock Future

    # Commodities / Currencies
    if is_mcx or is_cds:
        return 30

    # Cash Equities
    return 10


def resolve_tradable_tbt_symbol(symbol: str) -> str:
    """
    Ensure symbol has an order book before sending to Fyers TBT WebSocket.
    Spot indices (-INDEX) lack market depth and trigger INDEX_DEPTH_ERROR_MESSAGE.
    Converts spot indices to their active tradable Index Futures.
    """
    if not symbol or not isinstance(symbol, str):
        return ""
    clean = symbol.strip().upper()

    # Reject crypto (Fyers TBT only supports Indian exchange instruments)
    if (
        clean.startswith("CRYPTO:")
        or clean.endswith("USDT")
        or clean in ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
    ):
        return ""

    from brokers.fyers import _to_fyers_symbol

    fyers_sym = _to_fyers_symbol(symbol)
    if "-INDEX" in fyers_sym:
        clean_idx = fyers_sym.split(":")[-1].replace("-INDEX", "")
        return _resolve_index_future(clean_idx)

    return fyers_sym


def get_market_session() -> str:
    """
    Determine the current active market session in IST:
      - 'EQUITY_NFO'   : 09:15 - 15:30 IST (Mon-Fri)
      - 'COMMODITY_CDS': 15:30 - 23:30 IST (Mon-Fri)
      - 'OFF_MARKET'   : Nights / Weekends
    """
    try:
        from config.constants import IST_ZONE as IST

        now = datetime.now(IST)
    except Exception:
        now = datetime.now()

    if now.weekday() >= 5:  # Saturday or Sunday
        return "OFF_MARKET"

    t = now.time()
    if dtime(9, 15) <= t < dtime(15, 30):
        return "EQUITY_NFO"
    elif dtime(15, 30) <= t <= dtime(23, 30):
        return "COMMODITY_CDS"
    return "OFF_MARKET"


def get_default_core_grid(
    session: str = "AUTO",
    primary_focus: Optional[str] = None,
    ref_time: Optional[dtime] = None,
) -> tuple[list[str], list[str]]:
    """
    Build default (core_grid, todays_expiry) for the active session.
    Guarantees that index options or MCX commodities are immediately available on TBT.
    Supports dynamic primary_focus to revolve multi-strike ATM/OTM options for an active index.
    """
    if session == "AUTO":
        if primary_focus and primary_focus.upper() in (
            "NIFTY",
            "BANKNIFTY",
            "MIDCPNIFTY",
            "SENSEX",
            "FINNIFTY",
        ):
            session = "EQUITY_NFO"
        else:
            session = get_market_session()

    from market.calendar import get_active_derivative_expiry
    from brokers.fyers import format_fyers_option_symbol
    from market.quotes import get_ltp

    now = datetime.now()
    cur_time = ref_time or now.time()

    if session in ("EQUITY_NFO", "OFF_MARKET"):
        # Daytime: Primary Index Futures in user's priority order:
        # NIFTY, BANKNIFTY, MIDCPNIFTY (SENSEX & FINNIFTY sampled on need-basis via Scout)
        nifty_fut = _resolve_index_future("NIFTY")
        banknifty_fut = _resolve_index_future("BANKNIFTY")
        midcp_fut = _resolve_index_future("MIDCPNIFTY")

        core = [nifty_fut, banknifty_fut, midcp_fut]

        focus = (primary_focus or "").upper() if primary_focus else None

        if focus == "MIDCPNIFTY":
            m_exp = get_active_derivative_expiry(
                "MIDCPNIFTY", is_future=False, ref_date=now.date(), ref_time=cur_time
            )
            m_spot = get_ltp("NSE:MIDCPNIFTY-INDEX") or 13200.0
            m_atm = int(round(m_spot / 25.0) * 25)
            core.extend(
                [
                    format_fyers_option_symbol("MIDCPNIFTY", m_exp, m_atm, "CE"),
                    format_fyers_option_symbol("MIDCPNIFTY", m_exp, m_atm, "PE"),
                    format_fyers_option_symbol("MIDCPNIFTY", m_exp, m_atm + 25, "CE"),
                    format_fyers_option_symbol("MIDCPNIFTY", m_exp, m_atm - 25, "PE"),
                ]
            )
        elif focus == "BANKNIFTY":
            bn_exp = get_active_derivative_expiry(
                "BANKNIFTY", is_future=False, ref_date=now.date(), ref_time=cur_time
            )
            bn_spot = get_ltp("NSE:NIFTYBANK-INDEX") or 52000.0
            bn_atm = int(round(bn_spot / 100.0) * 100)
            core.extend(
                [
                    format_fyers_option_symbol("BANKNIFTY", bn_exp, bn_atm, "CE"),
                    format_fyers_option_symbol("BANKNIFTY", bn_exp, bn_atm, "PE"),
                    format_fyers_option_symbol("BANKNIFTY", bn_exp, bn_atm + 100, "CE"),
                    format_fyers_option_symbol("BANKNIFTY", bn_exp, bn_atm - 100, "PE"),
                ]
            )
        elif focus == "SENSEX":
            s_fut = _resolve_index_future("SENSEX")
            s_exp = get_active_derivative_expiry(
                "SENSEX", is_future=False, ref_date=now.date(), ref_time=cur_time
            )
            s_spot = get_ltp("BSE:SENSEX-INDEX") or 81500.0
            s_atm = int(round(s_spot / 100.0) * 100)
            core.extend(
                [
                    s_fut,
                    format_fyers_option_symbol("SENSEX", s_exp, s_atm, "CE"),
                    format_fyers_option_symbol("SENSEX", s_exp, s_atm, "PE"),
                    format_fyers_option_symbol("SENSEX", s_exp, s_atm + 100, "CE"),
                    format_fyers_option_symbol("SENSEX", s_exp, s_atm - 100, "PE"),
                ]
            )
        else:
            # Default Balanced mode: NIFTY ATM CE & PE (plus wings if NIFTY focused or Thursday 0DTE)
            n_exp = get_active_derivative_expiry(
                "NIFTY", is_future=False, ref_date=now.date(), ref_time=cur_time
            )
            n_spot = get_ltp("NSE:NIFTY50-INDEX") or 25000.0
            n_atm = int(round(n_spot / 50.0) * 50)
            core.extend(
                [
                    format_fyers_option_symbol("NIFTY", n_exp, n_atm, "CE"),
                    format_fyers_option_symbol("NIFTY", n_exp, n_atm, "PE"),
                ]
            )
            # Expand wings if explicitly focused on NIFTY or if today is NIFTY expiry day
            if focus == "NIFTY" or n_exp == now.date():
                core.extend(
                    [
                        format_fyers_option_symbol("NIFTY", n_exp, n_atm + 50, "CE"),
                        format_fyers_option_symbol("NIFTY", n_exp, n_atm - 50, "PE"),
                    ]
                )

        # SEBI Regulatory Mandate (Circular SEBI/HO/MRD/MRD-PoD-2/P/CIR/2024/136):
        # Only ONE benchmark index derivative contract per exchange offers weekly options:
        #   - NSE: NIFTY (Thursday = 3)
        #   - BSE: SENSEX (Friday = 4)
        # On Monday-Wednesday, there are NO weekly index expiries — slots remain 100% free for Elastic Scouts.
        todays_exp: list[str] = []
        s_weekly_exp = get_active_derivative_expiry(
            "SENSEX", is_future=False, ref_date=now.date(), ref_time=cur_time
        )

        # Check if today is active 0DTE expiry for SENSEX (or NIFTY if not already in core)
        if s_weekly_exp == now.date() and focus != "SENSEX":
            exp_fut = _resolve_index_future("SENSEX")
            todays_exp.append(exp_fut)
            try:
                s_val = get_ltp(exp_fut) or get_ltp("BSE:SENSEX-INDEX") or 81500.0
                step = 100
                atm_val = int(round(s_val / float(step)) * step)
                todays_exp.extend(
                    [
                        format_fyers_option_symbol("SENSEX", s_weekly_exp, atm_val, "CE"),
                        format_fyers_option_symbol("SENSEX", s_weekly_exp, atm_val, "PE"),
                    ]
                )
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                )

        # Strict Single-Writer Invariant: eliminate any duplicate between core and todays_exp
        todays_exp = [s for s in todays_exp if s not in core]
        return core, todays_exp[:MAX_TODAYS_EXPIRY_SLOTS]

    else:
        # Evening (15:30 - 23:30 IST): MCX Commodities & Currency CDS
        from brokers.fyers import _resolve_commodity_contract, _resolve_currency_contract

        crude_fut = _resolve_commodity_contract("CRUDEOIL")
        core = [
            crude_fut,
            _resolve_commodity_contract("NATURALGAS"),
            _resolve_commodity_contract("GOLD"),
            _resolve_commodity_contract("SILVER"),
        ]
        try:
            from market.quotes import get_ltp

            c_ltp = get_ltp("MCX:CRUDEOIL") or 6500.0
            c_atm = int(round(c_ltp / 50.0) * 50)
            c_dt = now if now.day <= 18 else now + timedelta(days=20)
            c_suffix = c_dt.strftime("%y%b").upper()
            core.extend(
                [
                    f"MCX:CRUDEOIL{c_suffix}{c_atm}CE",
                    f"MCX:CRUDEOIL{c_suffix}{c_atm}PE",
                ]
            )
        except Exception:
            core.extend(
                [
                    _resolve_commodity_contract("COPPER"),
                    _resolve_commodity_contract("ZINC"),
                ]
            )

        # Currency derivatives (CDS) trade 09:00 - 17:00 IST.
        # After 17:00 IST, CDS is CLOSED. Never keep reserve for closed currency!
        # Allocate 100% of evening slots to active MCX base metals (COPPER, ZINC, ALUMINIUM).
        try:
            from config.constants import IST_ZONE as IST

            check_t = ref_time or datetime.now(IST).time()
        except Exception:
            check_t = ref_time or now.time()

        if check_t < dtime(17, 0):
            todays_exp = [
                _resolve_currency_contract("USDINR"),
                _resolve_commodity_contract("COPPER"),
                _resolve_commodity_contract("ZINC"),
            ]
        else:
            todays_exp = [
                _resolve_commodity_contract("COPPER"),
                _resolve_commodity_contract("ZINC"),
                _resolve_commodity_contract("ALUMINIUM"),
            ]
        return core[:MAX_CORE_GRID_SLOTS], todays_exp[:MAX_TODAYS_EXPIRY_SLOTS]


class FyersTbtManager:
    """Singleton manager for Fyers 50-level Tick-By-Tick (TBT) market depth."""

    _instance: Optional[FyersTbtManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> FyersTbtManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._ws: Any = None
        self._connected: bool = False
        self._access_token: str = ""
        self._app_id: str = ""
        self._thread: Optional[threading.Thread] = None
        self._subscribed: Set[str] = set()
        self._depth_cache: dict[str, dict[str, Any]] = {}
        self._depth_lock = threading.Lock()
        self._tick_buffers: dict[str, RollingTickBuffer] = {}
        self._callbacks: list[Callable[[str, dict[str, Any]], None]] = []

        # 15-Slot Dynamic Priority Governor
        self._in_flight: list[str] = []
        self._core_grid: list[str] = []
        self._todays_expiry: list[str] = []
        self._scout: OrderedDict[str, float] = OrderedDict()
        self._current_session: str = "AUTO"
        self._primary_focus_index: Optional[str] = None
        self._last_atm_strikes: dict[str, int] = {}
        self._slots_lock = threading.RLock()

        # Autonomous Session Handover & Drift Sentinel
        self._stop_event = threading.Event()
        self._guardian_thread: Optional[threading.Thread] = None

        self._initialized = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, access_token: str, app_id: str) -> None:
        """Start Fyers TBT WebSocket connection in a background thread."""
        if self._connected and self._access_token == access_token:
            return

        if self._connected and self._access_token != access_token:
            logger.info("[TbtManager] Restarting Fyers TBT socket with renewed access token")
            self.stop()

        self._access_token = access_token
        self._app_id = app_id

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

        if self._guardian_thread is None or not self._guardian_thread.is_alive():
            self._guardian_thread = threading.Thread(
                target=self._guardian_loop, daemon=True, name="tbt-session-guardian"
            )
            self._guardian_thread.start()

        logger.info("Fyers 50-Depth TBT Socket background thread started")

    def update_token(self, access_token: str, app_id: Optional[str] = None) -> None:
        """Update access token and reconnect if changed."""
        app = app_id or self._app_id
        if self._access_token != access_token or not self._connected:
            self.start(access_token=access_token, app_id=app)

    def stop(self, timeout: float = 1.0) -> None:
        """Gracefully disconnect the TBT WebSocket and stop sentinel without blocking."""
        self._stop_event.set()
        ws_to_close = self._ws
        self._connected = False
        self._ws = None

        if ws_to_close:

            def _close():
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    ws_obj = getattr(ws_to_close, "_FyersTbtSocket__ws_object", None)
                    if ws_obj and hasattr(ws_obj, "close"):
                        try:
                            ws_obj.close()
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                            )
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                    )

            t = threading.Thread(target=_close, daemon=True)
            t.start()
            t.join(timeout=timeout)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

        if self._guardian_thread and self._guardian_thread.is_alive():
            self._guardian_thread.join(timeout=timeout)
        self._guardian_thread = None

    def _guardian_loop(self) -> None:
        """
        Autonomous background sentinel (runs every 15s):
          1. Automated session handover: detects market session transitions (e.g. 15:30 IST
             EQUITY_NFO -> COMMODITY_CDS, or 09:15 morning open) and rotates TBT slots.
          2. Strike revolver: evaluates spot drift and rotates stale ATM option strikes.
          3. In-flight garbage collection: reconciles active open orders/positions to evict closed symbols.
        """
        logger.info("[TbtManager] Autonomous session & strike guardian started")
        while not self._stop_event.is_set():
            try:
                # 1. Automated session handover (09:15 open, 15:30 commodity transition, 23:30 close)
                active_session = get_market_session()
                with self._slots_lock:
                    curr_session = self._current_session

                # Auto-switch whenever market session boundary is crossed (never blocked by stale focus)
                if curr_session != active_session:
                    logger.info(
                        f"[TbtManager] Market session boundary detected: '{curr_session}' -> '{active_session}'. "
                        f"Auto-rotating TBT slots to {'MCX commodities' if active_session == 'COMMODITY_CDS' else 'Index futures & options'}."
                    )
                    self.switch_session(active_session)

                # 1b. Currency CDS Session Retirement Sentinel at 17:00 IST:
                # When in COMMODITY_CDS, check if clock crossed 17:00 IST and retire USDINR immediately
                if self._current_session == "COMMODITY_CDS":
                    try:
                        from config.constants import IST_ZONE as IST

                        now_t = datetime.now(IST).time()
                    except Exception:
                        now_t = datetime.now().time()
                    if now_t >= dtime(17, 0):
                        with self._slots_lock:
                            has_cds = any("USDINR" in s for s in self._todays_expiry) or any(
                                "USDINR" in s for s in self._scout
                            )
                        if has_cds:
                            logger.info(
                                "[TbtManager] 17:00 IST Currency CDS market closed. "
                                "Retiring USDINR slots and rotating 100% capacity to active MCX commodities."
                            )
                            with self._slots_lock:
                                cds_scouts = [s for s in self._scout if "USDINR" in s]
                                for s in cds_scouts:
                                    del self._scout[s]
                            self.refresh_grid("COMMODITY_CDS")

                # 2. Strike revolver for active equity session
                if self._current_session in ("EQUITY_NFO", "OFF_MARKET"):
                    self.revolve_atm_strikes()

                # 3. In-flight position cleanup
                if self._in_flight:
                    self.sync_in_flight_with_positions()

            except Exception as e:
                logger.debug(f"[TbtManager] Guardian loop pass error: {e}")

            # Sleep 15s or until stop_event is set
            self._stop_event.wait(timeout=15.0)
        logger.info("[TbtManager] Autonomous session & strike guardian stopped")

    def _connect(self) -> None:
        try:
            from fyers_apiv3.FyersWebsocket.tbt_ws import FyersTbtSocket

            auth_token = (
                f"{self._app_id}:{self._access_token}"
                if ":" not in self._access_token
                else self._access_token
            )

            self._ws = FyersTbtSocket(
                access_token=auth_token,
                on_depth_update=self._handle_depth_update,
                on_connect=self._handle_connect,
                on_close=self._handle_close,
                on_error=self._handle_error,
                reconnect=True,
            )
            self._ws.connect()
        except ImportError:
            logger.warning("fyers_apiv3 TBT module unavailable")
        except Exception as e:
            logger.warning(f"Fyers TBT Socket connect failed: {e}")

    def _handle_connect(self, *args, **kwargs) -> None:
        self._connected = True
        logger.info("Fyers TBT Socket: Handshake confirmed")
        if not self._core_grid and not self._subscribed:
            self.refresh_grid()
        if self._subscribed:
            self._do_subscribe(self._subscribed)

    def _handle_close(self, *args, **kwargs) -> None:
        self._connected = False
        logger.info("Fyers TBT Socket: Disconnected")

    def _handle_error(self, err, *args, **kwargs) -> None:
        logger.debug(f"Fyers TBT Socket error: {err}")

    def _handle_depth_update(self, symbol: str, depth_obj: Any) -> None:
        """Process incoming 50-depth packet from Fyers TBT socket and bridge to central quote cache."""
        try:
            parsed = self._parse_depth_object(symbol, depth_obj)
            with self._depth_lock:
                self._depth_cache[symbol] = parsed
                clean_sym = symbol.split(":")[-1]
                self._depth_cache[clean_sym] = parsed

            # Zero-latency L1 quote bridge: populate market.quotes cache to eliminate REST queries
            try:
                from market.quotes import _QUOTE_CACHE, _quote_cache_lock
                from brokers.base import Quote

                ltp_val = float(parsed.get("ltp") or 0.0)
                if ltp_val > 0:
                    bids_list = parsed.get("bids", [])
                    asks_list = parsed.get("asks", [])
                    top_b = float(bids_list[0]["price"]) if bids_list else ltp_val
                    top_a = float(asks_list[0]["price"]) if asks_list else ltp_val
                    q_obj = Quote(
                        symbol=symbol,
                        last_price=ltp_val,
                        open=ltp_val,
                        high=ltp_val,
                        low=ltp_val,
                        close=ltp_val,
                        volume=int(parsed.get("tbq", 0) + parsed.get("tsq", 0)),
                        bid=top_b,
                        ask=top_a,
                        source="STREAM",
                        data_state="LIVE",
                        provider="fyers_tbt",
                    )
                    now_w = time.time()
                    with _quote_cache_lock:
                        _QUOTE_CACHE[symbol] = (now_w, q_obj)
                        _QUOTE_CACHE[clean_sym] = (now_w, q_obj)
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                )

            for cb in self._callbacks:
                try:
                    cb(symbol, parsed)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                    )
        except Exception as e:
            logger.debug(f"Error parsing 50-depth packet for {symbol}: {e}")

    def _parse_depth_object(self, symbol: str, depth: Any) -> dict[str, Any]:
        """Convert SDK Depth protobuf object to structured institutional dict."""
        bid_prices = list(getattr(depth, "bidprice", []))
        ask_prices = list(getattr(depth, "askprice", []))
        bid_qtys = list(getattr(depth, "bidqty", []))
        ask_qtys = list(getattr(depth, "askqty", []))
        bid_orders = list(getattr(depth, "bidordn", []))
        ask_orders = list(getattr(depth, "askordn", []))

        bids = []
        asks = []
        tot_bid_q = 0
        tot_ask_q = 0

        for i in range(min(50, len(bid_prices))):
            bp = float(bid_prices[i] or 0.0)
            bq = int(bid_qtys[i] or 0)
            bo = int(bid_orders[i] or 0)
            if bp > 0 and bq > 0:
                bids.append({"level": i + 1, "price": bp, "qty": bq, "orders": bo})
                tot_bid_q += bq

        for i in range(min(50, len(ask_prices))):
            ap = float(ask_prices[i] or 0.0)
            aq = int(ask_qtys[i] or 0)
            ao = int(ask_orders[i] or 0)
            if ap > 0 and aq > 0:
                asks.append({"level": i + 1, "price": ap, "qty": aq, "orders": ao})
                tot_ask_q += aq

        tbq = int(getattr(depth, "tbq", tot_bid_q) or tot_bid_q)
        tsq = int(getattr(depth, "tsq", tot_ask_q) or tot_ask_q)

        # 50-level Order Book Imbalance ratio [-1.0 to +1.0]
        denom = tbq + tsq
        obi_50 = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        # Book Density Score: active populated levels out of 100 total slots
        active_slots = len(bids) + len(asks)
        density_score = round((active_slots / 100.0) * 100, 1)

        # Institutional Multi-Factor Order Book Wall Classification:
        # Evaluated across 4 orthogonal dimensions:
        #   1. Book Share Dominance (>= 12% of total depth on that side)
        #   2. Multi-Order Clustering (orders >= 2 confirms structural consensus vs 1-order spoof)
        #   3. Capital Commitment (notional turnover & instrument-calibrated minimum volume)
        #   4. Auction Proximity (levels 3 to 25 within actionable execution horizon)
        is_commodity_sym = symbol.startswith("MCX:") or any(
            c in symbol.upper()
            for c in ("CRUDE", "NATURAL", "GOLD", "SILVER", "COPPER", "ZINC", "ALUMINIUM")
        )
        min_wall_qty = 10 if is_commodity_sym else 2500

        avg_bid_q = (tot_bid_q / max(1, len(bids))) if bids else 0
        avg_ask_q = (tot_ask_q / max(1, len(asks))) if asks else 0

        ltp = bids[0]["price"] if bids else (asks[0]["price"] if asks else 0.0)

        def _classify_wall(
            row: dict[str, Any], tot_q: int, avg_q: float
        ) -> Optional[dict[str, Any]]:
            lvl = row["level"]
            # Exclude level 1-2 spread flicker / top-of-book oscillation
            if lvl <= 2:
                return None
            qty = row["qty"]
            price = row["price"]
            orders = row.get("orders", 1)

            book_share_pct = round((qty / max(1, tot_q)) * 100, 2)
            multiple_of_avg = round(qty / max(1.0, avg_q), 2)
            notional = round(qty * price, 2)
            dist_pct = round(abs(price - ltp) / max(0.01, ltp) * 100, 3) if ltp > 0 else 0.0

            # Must satisfy minimum volume or 2.5x multiple with at least 8% book share
            if (qty < max(min_wall_qty, avg_q * 2.5)) and book_share_pct < 8.0:
                return None
            if multiple_of_avg < 2.5 and qty < min_wall_qty:
                return None

            # Institutional Strength Hierarchy:
            # FORTRESS: Massive book dominance (>= 20% share) or heavy clustered institutional iceberg (orders >= 2 and >= 15% share)
            if (book_share_pct >= 20.0 and multiple_of_avg >= 4.0) or (
                orders >= 2 and book_share_pct >= 15.0 and multiple_of_avg >= 3.5
            ):
                strength = "FORTRESS"
            # STRONG: Dominates book (>= 12% share) and >= 3.0x average
            elif (book_share_pct >= 12.0 and multiple_of_avg >= 3.0) or (
                multiple_of_avg >= 3.0 and qty >= min_wall_qty
            ):
                strength = "STRONG"
            else:
                strength = "MODERATE"

            return {
                "level": lvl,
                "price": price,
                "qty": qty,
                "orders": orders,
                "book_share_pct": book_share_pct,
                "multiple_of_avg": multiple_of_avg,
                "notional_value": notional,
                "strength": strength,
                "distance_pct": dist_pct,
            }

        bid_walls = []
        for b in bids:
            w = _classify_wall(b, tot_bid_q, avg_bid_q)
            if w:
                bid_walls.append(w)

        ask_walls = []
        for a in asks:
            w = _classify_wall(a, tot_ask_q, avg_ask_q)
            if w:
                ask_walls.append(w)

        # Sort walls by structural significance: highest quantity & book share first
        bid_walls.sort(key=lambda x: (x["book_share_pct"], x["qty"]), reverse=True)
        ask_walls.sort(key=lambda x: (x["book_share_pct"], x["qty"]), reverse=True)

        strongest_bid_wall = bid_walls[0] if bid_walls else None
        strongest_ask_wall = ask_walls[0] if ask_walls else None

        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0
        micro_price = (
            round(
                (bids[0]["price"] * asks[0]["qty"] + asks[0]["price"] * bids[0]["qty"])
                / max(1, bids[0]["qty"] + asks[0]["qty"]),
                4,
            )
            if bids and asks
            else ltp
        )

        # Update O(1) rolling tick buffer for micro-price tracking
        buf = self._tick_buffers.setdefault(symbol, RollingTickBuffer(capacity=1000))
        if micro_price > 0:
            buf.append(micro_price, max(1, tbq + tsq))

        rolling_vwap = round(buf.vwap, 4) if buf.count > 0 else micro_price
        rolling_vol = round(buf.std_dev, 4) if buf.count > 1 else 0.0

        return {
            "symbol": symbol,
            "status": "LIVE",
            "timestamp": getattr(depth, "timestamp", int(time.time())),
            "ltp": ltp,
            "micro_price": micro_price,
            "rolling_tick_vwap": rolling_vwap,
            "rolling_tick_volatility": rolling_vol,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi_50,
            "density_score": density_score,
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": bid_walls,
            "ask_walls": ask_walls,
            "strongest_bid_wall": strongest_bid_wall,
            "strongest_ask_wall": strongest_ask_wall,
            "has_bid_wall": len(bid_walls) > 0,
            "has_ask_wall": len(ask_walls) > 0,
        }

    def refresh_grid(self, session: Optional[str] = None) -> None:
        """Populate the core grid and today's expiry symbols based on active market session and primary focus."""
        with self._slots_lock:
            if session and session != "AUTO":
                target_session = session
            elif self._primary_focus_index in (
                "NIFTY",
                "BANKNIFTY",
                "MIDCPNIFTY",
                "SENSEX",
                "FINNIFTY",
            ):
                target_session = "EQUITY_NFO"
            elif getattr(self, "_current_session", "AUTO") not in ("AUTO", None):
                target_session = self._current_session
            else:
                target_session = get_market_session()

            core, todays = get_default_core_grid(
                target_session, primary_focus=self._primary_focus_index
            )
            self._core_grid = core
            self._todays_expiry = todays
            self._current_session = target_session
            logger.info(
                f"[TbtManager] Refreshed TBT grid for session '{self._current_session}' (Focus={self._primary_focus_index}): "
                f"Core ({len(self._core_grid)})={self._core_grid}, Expiry ({len(self._todays_expiry)})={self._todays_expiry}"
            )
            self.sync_subscriptions()

    def set_primary_focus(
        self, index_name: Optional[str] = None, session: Optional[str] = None
    ) -> None:
        """
        Dynamically designate a primary focus index ('NIFTY', 'BANKNIFTY', 'MIDCPNIFTY', 'SENSEX').
        Expands core grid with ATM CE/PE and ATM +/- 1 wings by borrowing elastically from the scout pool.
        Pass None to return to balanced multi-index coverage.
        """
        with self._slots_lock:
            self._primary_focus_index = index_name.upper() if index_name else None
            logger.info(f"[TbtManager] Primary focus index set to: {self._primary_focus_index}")
            target_session = session or (
                "EQUITY_NFO"
                if self._primary_focus_index
                in ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX", "FINNIFTY")
                else self._current_session
            )
            self.refresh_grid(session=target_session)

    def revolve_atm_strikes(self, force: bool = False) -> bool:
        """
        Check underlying spot prices for NIFTY, BANKNIFTY, MIDCPNIFTY, and SENSEX.
        If spot has drifted by >= 1 strike step, automatically rotate stale ATM contracts
        out of TBT depth and subscribe the newly active ATM strikes.
        Returns True if grid was revolved, False otherwise.
        """
        try:
            from market.quotes import get_ltp
        except Exception:
            return False

        if self._current_session not in ("EQUITY_NFO", "OFF_MARKET"):
            if not (self._primary_focus_index or self._last_atm_strikes):
                return False

        index_configs = {
            "NIFTY": ("NSE:NIFTY50-INDEX", 50),
            "BANKNIFTY": ("NSE:NIFTYBANK-INDEX", 100),
            "MIDCPNIFTY": ("NSE:MIDCPNIFTY-INDEX", 25),
            "SENSEX": ("BSE:SENSEX-INDEX", 100),
        }

        revolved = False
        new_atm_map: dict[str, int] = {}

        for idx, (spot_sym, step) in index_configs.items():
            ltp = get_ltp(spot_sym) or get_ltp(idx)
            if ltp and ltp > 0:
                prev_atm = self._last_atm_strikes.get(idx)
                if prev_atm is None:
                    current_atm = int(round(ltp / float(step)) * step)
                    new_atm_map[idx] = current_atm
                    revolved = True
                else:
                    # 15% Strike Deadband (Hysteresis): prevents thrashing when spot oscillates near boundary
                    deadband = 0.15 * step
                    threshold = (0.5 * step) + deadband
                    if abs(ltp - prev_atm) >= threshold:
                        current_atm = int(round(ltp / float(step)) * step)
                        if current_atm != prev_atm:
                            new_atm_map[idx] = current_atm
                            revolved = True
                    else:
                        new_atm_map[idx] = prev_atm

        if force or (revolved and new_atm_map):
            with self._slots_lock:
                self._last_atm_strikes.update(new_atm_map)
                target_session = (
                    self._current_session if self._current_session != "AUTO" else "EQUITY_NFO"
                )
                self.refresh_grid(session=target_session)
                logger.info(
                    f"[TbtManager] Revolved ATM strikes due to spot drift: {self._last_atm_strikes}"
                )
            return True

        return False

    def switch_session(self, session_name: str) -> None:
        """
        Manually or automatically transition market session.
        E.g. 'EQUITY_NFO' at 09:15 IST -> 'COMMODITY_CDS' at 15:30 IST.
        Cleanses stale scouts and resets ATM strike caches for seamless morning switchover.
        """
        logger.info(
            f"[TbtManager] Switching TBT session from '{self._current_session}' to '{session_name}'"
        )
        with self._slots_lock:
            if session_name == "EQUITY_NFO":
                # Morning Handover (09:15 IST): Evict all commodity/currency scouts
                # to liberate all 15 slots for daytime index options & equity scouts.
                to_evict = [
                    s
                    for s in self._scout
                    if s.startswith("MCX:")
                    or "USDINR" in s
                    or any(
                        c in s
                        for c in (
                            "CRUDE",
                            "NATURAL",
                            "GOLD",
                            "SILVER",
                            "COPPER",
                            "ZINC",
                            "ALUMINIUM",
                        )
                    )
                ]
                for s in to_evict:
                    del self._scout[s]
                if to_evict:
                    logger.info(
                        f"[TbtManager] Liberated {len(to_evict)} evening commodity slots for morning equity open: {to_evict}"
                    )
                # Reset ATM strike cache and primary focus for fresh morning index open
                self._last_atm_strikes.clear()
                self._primary_focus_index = None

            elif session_name == "COMMODITY_CDS":
                # Evening Handover (15:30 IST): Evict closed daytime equity/NFO scouts
                to_evict = [
                    s
                    for s in self._scout
                    if not (
                        s.startswith("MCX:")
                        or "USDINR" in s
                        or any(
                            c in s
                            for c in (
                                "CRUDE",
                                "NATURAL",
                                "GOLD",
                                "SILVER",
                                "COPPER",
                                "ZINC",
                                "ALUMINIUM",
                            )
                        )
                    )
                ]
                for s in to_evict:
                    del self._scout[s]
                if to_evict:
                    logger.info(
                        f"[TbtManager] Evicted {len(to_evict)} closed daytime equity scouts for evening commodity session: {to_evict}"
                    )
                self._last_atm_strikes.clear()
                self._primary_focus_index = None

        self.refresh_grid(session=session_name)

    def register_in_flight(self, symbol: str) -> None:
        """
        Register in-flight active position or limit order.
        Allocated to highest priority Tier 1 (Slots 1-4) for institutional slippage & wall protection.
        """
        tradable = resolve_tradable_tbt_symbol(symbol)
        if not tradable:
            return
        with self._slots_lock:
            if tradable not in self._in_flight:
                self._in_flight.append(tradable)
                while len(self._in_flight) > MAX_IN_FLIGHT_SLOTS:
                    self._in_flight.pop(0)
                logger.info(
                    f"[TbtManager] Registered Tier 1 In-Flight position: {tradable} (Total: {len(self._in_flight)})"
                )
                self.sync_subscriptions()

    def unregister_in_flight(self, symbol: str) -> None:
        """Unregister in-flight symbol once position is closed or order filled/cancelled."""
        tradable = resolve_tradable_tbt_symbol(symbol)
        with self._slots_lock:
            removed = False
            if tradable and tradable in self._in_flight:
                self._in_flight.remove(tradable)
                removed = True
            elif symbol in self._in_flight:
                self._in_flight.remove(symbol)
                removed = True
            if removed:
                logger.info(
                    f"[TbtManager] Unregistered Tier 1 In-Flight position: {tradable or symbol}"
                )
                self.sync_subscriptions()

    def sync_in_flight_with_positions(self) -> None:
        """
        Reconcile Tier 1 In-Flight slots against active live open orders & positions.
        Evicts any closed/cancelled symbols that no longer have an active position or open order.
        """
        with self._slots_lock:
            if not self._in_flight:
                return

        active_symbols: set[str] = set()
        try:
            from engine.order_lifecycle import _get_orders_pool

            pool = _get_orders_pool()
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT symbol FROM orders_ledger WHERE status = 'OPEN'"
                ).fetchall()
                for r in rows:
                    if r and r[0]:
                        active_symbols.add(str(r[0]))
        except Exception as e_suppressed:
            logger.debug(
                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
            )

        try:
            from brokers.session import get_execution_broker

            broker = get_execution_broker()
            if broker and hasattr(broker, "get_positions"):
                for p in broker.get_positions():
                    if getattr(p, "quantity", 0) != 0:
                        active_symbols.add(str(p.symbol))
        except Exception as e_suppressed:
            logger.debug(
                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
            )

        self.sync_in_flight_with_active_symbols(active_symbols)

    def sync_in_flight_with_active_symbols(self, active_symbols: set[str] | list[str]) -> None:
        """Evict any in-flight symbol that is not in active_symbols."""
        normalized_active = set()
        for s in active_symbols:
            t = resolve_tradable_tbt_symbol(s)
            if t:
                normalized_active.add(t)
            normalized_active.add(s)

        with self._slots_lock:
            to_remove = [s for s in self._in_flight if s not in normalized_active]
            if to_remove:
                for s in to_remove:
                    self._in_flight.remove(s)
                logger.info(
                    f"[TbtManager] Evicted {len(to_remove)} closed/dead in-flight positions: {to_remove}"
                )
                self.sync_subscriptions()

    def compute_desired_subscriptions(self) -> list[str]:
        """
        Build exact prioritized list of up to MAX_TBT_SYMBOLS (15) symbols.
        Order of priority:
          1. IN_FLIGHT (Slots 1-4: active orders/positions)
          2. CORE_GRID (Benchmark Futures & Revolving ATM Options, elastic)
          3. TODAYS_EXPIRY (0DTE priority candidates when active)
          4. SCOUT (Elastic: fills all remaining unallocated slots up to 15)
        """
        with self._slots_lock:
            desired: list[str] = []

            # 1. In-flight open orders / positions
            for s in self._in_flight[:MAX_IN_FLIGHT_SLOTS]:
                if s and s not in desired:
                    desired.append(s)

            # 2. Core Grid (Benchmark Futures & ATM Options - elastic consumption)
            for s in self._core_grid:
                if len(desired) >= MAX_TBT_SYMBOLS:
                    break
                if s and s not in desired:
                    desired.append(s)

            # 3. Today's Expiry Radar
            for s in self._todays_expiry[:MAX_TODAYS_EXPIRY_SLOTS]:
                if len(desired) >= MAX_TBT_SYMBOLS:
                    break
                if s and s not in desired:
                    desired.append(s)

            # 4. Ephemeral Scout slots (Elastic: fills all remaining unallocated slots up to 15)
            remaining_slots = MAX_TBT_SYMBOLS - len(desired)
            if remaining_slots > 0 and self._scout:
                # Prioritize index options and futures ahead of stock options and equities
                sorted_scout = sorted(
                    self._scout.items(),
                    key=lambda item: (_tbt_symbol_priority(item[0]), item[1]),
                    reverse=True,
                )
                for s, _ in sorted_scout:
                    if len(desired) >= MAX_TBT_SYMBOLS:
                        break
                    if s and s not in desired:
                        desired.append(s)

            return desired[:MAX_TBT_SYMBOLS]

    def sync_subscriptions(self) -> None:
        """Synchronize current active Fyers TBT WebSocket subscriptions to desired set."""
        desired_list = self.compute_desired_subscriptions()
        desired_set = set(desired_list)

        with self._slots_lock:
            to_add = desired_set - self._subscribed
            to_remove = self._subscribed - desired_set

            if to_remove:
                self._subscribed.difference_update(to_remove)
                if self._connected and self._ws:
                    try:
                        self._ws.unsubscribe(symbols=to_remove, channelNo="1")
                        logger.info(
                            f"[TbtManager] Unsubscribed {len(to_remove)} symbols: {to_remove}"
                        )
                    except Exception as e:
                        logger.warning(f"[TbtManager] Unsubscribe failed: {e}")

            if to_add:
                self._subscribed.update(to_add)
                if self._connected and self._ws:
                    self._do_subscribe(to_add)

    def subscribe(self, symbols: list[str]) -> None:
        """
        Register symbols dynamically under the 15-slot governor.
        Symbols are routed through the Scout ring with prioritized LRU eviction.
        """
        if not symbols:
            return

        with self._slots_lock:
            now_ts = time.time()
            changed = False
            for s in symbols:
                tradable = resolve_tradable_tbt_symbol(s)
                if not tradable:
                    continue
                if (
                    tradable not in self._subscribed
                    and tradable not in self._core_grid
                    and tradable not in self._todays_expiry
                    and tradable not in self._in_flight
                ):
                    self._scout[tradable] = now_ts
                    changed = True

            # If scout exceeds capacity, evict lowest-priority items first, then oldest
            if len(self._scout) > MAX_SCOUT_SLOTS:
                sorted_by_eviction = sorted(
                    self._scout.items(),
                    key=lambda item: (_tbt_symbol_priority(item[0]), item[1]),
                )
                excess = len(self._scout) - MAX_SCOUT_SLOTS
                for k, _ in sorted_by_eviction[:excess]:
                    del self._scout[k]
                    changed = True

            if changed:
                self.sync_subscriptions()

    def _do_subscribe(self, symbols: Set[str]) -> None:
        try:
            from fyers_apiv3.FyersWebsocket.tbt_ws import SubscriptionModes

            self._ws.subscribe(
                symbol_tickers=symbols,
                channelNo="1",
                mode=SubscriptionModes.DEPTH,
            )
            logger.info(f"Fyers TBT 50-Depth: Subscribed to {len(symbols)} symbols: {symbols}")
        except Exception as e:
            logger.warning(f"Fyers TBT subscribe failed: {e}")

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe symbols from Scout or In-Flight tracking."""
        with self._slots_lock:
            changed = False
            for s in symbols:
                tradable = resolve_tradable_tbt_symbol(s) or s
                if tradable in self._scout:
                    del self._scout[tradable]
                    changed = True
                if tradable in self._in_flight:
                    self._in_flight.remove(tradable)
                    changed = True

            if changed:
                self.sync_subscriptions()
            else:
                formatted = {resolve_tradable_tbt_symbol(s) or s for s in symbols}
                to_remove = self._subscribed.intersection(formatted)
                if to_remove:
                    self._subscribed.difference_update(to_remove)
                    if self._connected and self._ws:
                        try:
                            self._ws.unsubscribe(symbols=to_remove, channelNo="1")
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
                            )

    def sample_symbol(self, symbol: str, duration_sec: float = 120.0) -> bool:
        """
        Dynamically sample order-book depth for any index (e.g. FINNIFTY, SENSEX) or stock
        on a need basis without blocking core grid.
        Allocates to Elastic Scout pool with an automatic expiration timer.
        """
        tradable = resolve_tradable_tbt_symbol(symbol)
        if not tradable:
            return False
        with self._slots_lock:
            self._scout[tradable] = time.time()
            self.sync_subscriptions()
            logger.info(
                f"[TbtManager] Elastic Scout sampling symbol: {tradable} (Duration: {duration_sec}s)"
            )

        if duration_sec > 0:

            def _expire():
                time.sleep(duration_sec)
                with self._slots_lock:
                    if (
                        tradable in self._scout
                        and (time.time() - self._scout[tradable]) >= duration_sec
                    ):
                        del self._scout[tradable]
                        self.sync_subscriptions()
                        logger.info(
                            f"[TbtManager] Finished sampling, released slot for: {tradable}"
                        )

            threading.Thread(target=_expire, daemon=True).start()
        return True

    def get_active_slots_status(self) -> dict[str, Any]:
        """Audit status of all 15 TBT slots and current allocation breakdown."""
        with self._slots_lock:
            return {
                "max_slots": MAX_TBT_SYMBOLS,
                "active_total": len(self._subscribed),
                "current_session": self._current_session,
                "primary_focus": self._primary_focus_index,
                "last_atm_strikes": dict(self._last_atm_strikes),
                "in_flight": list(self._in_flight),
                "core_grid": list(self._core_grid),
                "todays_expiry": list(self._todays_expiry),
                "scout": list(self._scout.keys()),
                "subscribed": sorted(self._subscribed),
            }

    def get_50_depth(self, symbol: str) -> dict[str, Any]:
        """
        Retrieve latest cached 50-depth for symbol.
        Falls back seamlessly to L2 5-depth if TBT packet is not yet populated.
        """
        from brokers.fyers import _to_fyers_symbol

        fyers_sym = _to_fyers_symbol(symbol)
        clean = symbol.split(":")[-1]

        with self._depth_lock:
            if symbol in self._depth_cache:
                return self._depth_cache[symbol]
            if fyers_sym in self._depth_cache:
                return self._depth_cache[fyers_sym]
            if clean in self._depth_cache:
                return self._depth_cache[clean]

        # Seamless Fallback to Broker L2 5-depth REST API
        try:
            from brokers.session import get_data_broker

            brk = get_data_broker()
            if brk and hasattr(brk, "get_market_depth"):
                d = brk.get_market_depth(symbol)
                if d.get("status") == "ok":
                    return self._convert_l2_to_depth_format(symbol, d)
        except Exception as e_suppressed:
            logger.debug(
                f"[market.fyers_tbt_manager] Non-fatal exception suppressed: {e_suppressed}"
            )

        return {
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "message": "50-depth data stream awaiting live packets",
            "tbq": 0,
            "tsq": 0,
            "obi_50": 0.0,
            "density_score": 0.0,
            "bids": [],
            "asks": [],
            "bid_walls": [],
            "ask_walls": [],
        }

    def get_depth(self, symbol: str) -> dict[str, Any]:
        """Convenience alias for get_50_depth."""
        return self.get_50_depth(symbol)

    def _convert_l2_to_depth_format(self, symbol: str, l2: dict[str, Any]) -> dict[str, Any]:
        """Convert standard 5-level broker depth into compatible DOM structure."""
        raw_bids = l2.get("bids", []) or []
        raw_asks = l2.get("asks", []) or []

        bids = [
            {
                "level": i + 1,
                "price": float(b.get("price", 0.0)),
                "qty": int(b.get("volume", b.get("qty", 0))),
                "orders": int(b.get("orders", 1)),
            }
            for i, b in enumerate(raw_bids[:5])
            if float(b.get("price", 0.0)) > 0
        ]
        asks = [
            {
                "level": i + 1,
                "price": float(a.get("price", 0.0)),
                "qty": int(a.get("volume", a.get("qty", 0))),
                "orders": int(a.get("orders", 1)),
            }
            for i, a in enumerate(raw_asks[:5])
            if float(a.get("price", 0.0)) > 0
        ]

        tbq = int(l2.get("total_buy_qty", sum(b["qty"] for b in bids)))
        tsq = int(l2.get("total_sell_qty", sum(a["qty"] for a in asks)))
        denom = tbq + tsq
        obi = round((tbq - tsq) / max(1, denom), 4) if denom > 0 else 0.0

        ltp = float(l2.get("ltp", bids[0]["price"] if bids else 0.0))
        spread = round(asks[0]["price"] - bids[0]["price"], 2) if bids and asks else 0.0

        return {
            "symbol": symbol,
            "status": "L2_FALLBACK",
            "timestamp": int(time.time()),
            "ltp": ltp,
            "spread": spread,
            "tbq": tbq,
            "tsq": tsq,
            "obi_50": obi,
            "density_score": round((len(bids) + len(asks)) / 10.0 * 100, 1),
            "bids_count": len(bids),
            "asks_count": len(asks),
            "bids": bids,
            "asks": asks,
            "bid_walls": [],
            "ask_walls": [],
            "has_bid_wall": False,
            "has_ask_wall": False,
        }

    def simulate_slippage(self, symbol: str, quantity: int, side: str = "BUY") -> dict[str, Any]:
        """
        Calculate volume-weighted fill price and slippage through the order book.
        """
        depth = self.get_50_depth(symbol)
        book = depth.get("asks", []) if side.upper() == "BUY" else depth.get("bids", [])
        if not book:
            return {"status": "UNAVAILABLE", "message": "Order book empty"}

        remaining = int(quantity)
        total_cost = 0.0
        levels_filled = 0
        top_price = book[0]["price"]

        for row in book:
            avail = row["qty"]
            price = row["price"]
            levels_filled += 1
            if remaining <= avail:
                total_cost += remaining * price
                remaining = 0
                break
            else:
                total_cost += avail * price
                remaining -= avail

        if remaining > 0:
            return {
                "status": "PARTIAL_FILL",
                "message": f"Order book exhausted. Remaining unfilled: {remaining} contracts",
                "requested_qty": quantity,
                "unfilled_qty": remaining,
            }

        vwap_fill = round(total_cost / max(1, quantity), 4)
        slippage_pts = round(abs(vwap_fill - top_price), 4)
        slippage_pct = round((slippage_pts / max(0.01, top_price)) * 100, 3)

        return {
            "status": "ok",
            "symbol": symbol,
            "side": side.upper(),
            "requested_qty": quantity,
            "top_of_book_price": top_price,
            "expected_vwap_price": vwap_fill,
            "estimated_slippage_pts": slippage_pts,
            "estimated_slippage_pct": slippage_pct,
            "depth_levels_swept": levels_filled,
        }

    def audit_candidate_depth(
        self,
        symbol: str,
        side: str = "BUY",
        lot_size: int = 65,
    ) -> dict[str, Any]:
        """
        Tier 2 Institutional 50-Depth Gatekeeper.
        Evaluates candidate setup quality, iceberg barriers, OBI-50, and liquidity density.
        """
        # Ensure symbol is registered for depth on order book
        tradable = resolve_tradable_tbt_symbol(symbol) or symbol
        self.subscribe([tradable])
        depth = self.get_50_depth(tradable)

        is_buy = side.upper() in ("BUY", "LONG")
        obi = depth.get("obi_50", 0.0)
        density = depth.get("density_score", 0.0)
        ltp = depth.get("ltp", 0.0)

        findings = []
        penalties = 0
        bonuses = 0

        # 1. Order Book Imbalance (OBI-50)
        if is_buy:
            if obi >= 0.25:
                bonuses += 20
                findings.append(f"Strong bid absorption (OBI-50: +{obi:.2f})")
            elif obi <= -0.30:
                penalties += 35
                findings.append(f"Severe ask pressure overhead (OBI-50: {obi:.2f})")
        else:
            if obi <= -0.25:
                bonuses += 20
                findings.append(f"Strong ask distribution (OBI-50: {obi:.2f})")
            elif obi >= 0.30:
                penalties += 35
                findings.append(f"Strong bid support absorbing sells (OBI-50: +{obi:.2f})")

        # 2. Iceberg / Resting Wall Barrier Check
        ask_walls = depth.get("ask_walls", [])
        bid_walls = depth.get("bid_walls", [])

        if is_buy and ask_walls:
            # Check if wall is within 2.5% of LTP (immediate roadblock)
            near_walls = [w for w in ask_walls if ltp > 0 and w["price"] <= ltp * 1.025]
            if near_walls:
                top_w = near_walls[0]
                str_lbl = top_w.get("strength", "STRONG")
                penalties += 35 if str_lbl == "FORTRESS" else (30 if str_lbl == "STRONG" else 20)
                findings.append(
                    f"[{str_lbl}] Institutional Ask Wall capping upside at ₹{top_w['price']} "
                    f"({top_w['qty']:,} contracts, {top_w.get('book_share_pct', 0)}% book share)"
                )
            else:
                bonuses += 5
                findings.append("No immediate institutional ask walls within +2.5%")
        elif not is_buy and bid_walls:
            near_bid_walls = [w for w in bid_walls if ltp > 0 and w["price"] >= ltp * 0.975]
            if near_bid_walls:
                top_w = near_bid_walls[0]
                str_lbl = top_w.get("strength", "STRONG")
                penalties += 35 if str_lbl == "FORTRESS" else (30 if str_lbl == "STRONG" else 20)
                findings.append(
                    f"[{str_lbl}] Institutional Bid Floor blocking downside at ₹{top_w['price']} "
                    f"({top_w['qty']:,} contracts, {top_w.get('book_share_pct', 0)}% book share)"
                )

        # 3. Density / Liquidity Quality Check
        if density < 15.0 and depth.get("status") != "L2_FALLBACK":
            penalties += 25
            findings.append(f"Thin order book density ({density:.1f}% slots filled)")
        else:
            bonuses += 10
            findings.append(f"Adequate book liquidity density ({density:.1f}%)")

        # 4. Slippage Check for 1 standard lot
        slip = self.simulate_slippage(symbol, quantity=lot_size, side=side)
        if slip.get("status") == "ok":
            slip_pct = slip.get("estimated_slippage_pct", 0.0)
            if slip_pct > 0.45:
                penalties += 20
                findings.append(f"High market order impact slippage ({slip_pct:.2f}%)")
            else:
                bonuses += 10
                findings.append(f"Minimal execution slippage ({slip_pct:.2f}%)")

        raw_score = 50 + bonuses - penalties
        final_conviction = max(0, min(100, raw_score))

        verdict = (
            "PASS"
            if final_conviction >= 65
            else ("CAUTION" if final_conviction >= 45 else "REJECT")
        )

        return {
            "symbol": symbol,
            "side": side.upper(),
            "verdict": verdict,
            "depth_conviction_score": final_conviction,
            "obi_50": obi,
            "density_score": density,
            "findings": findings,
            "audit_timestamp": int(time.time()),
        }


# Global Singleton Instance
fyers_tbt_manager = FyersTbtManager()
