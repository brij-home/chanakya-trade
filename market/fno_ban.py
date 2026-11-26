"""
market/fno_ban.py
─────────────────
Authoritative F&O Ban Period & Market Wide Position Limit (MWPL) Intelligence for Indian Markets.

Under SEBI and NSE Clearing (NCL) regulations:
  - Ban Invariant: Securities where derivative open interest exceeds 95% of MWPL are placed in the Ban Period.
  - No Fresh Exposure: Market participants are strictly prohibited from initiating fresh positions in banned securities.
    Only position unwinding / square-off is permitted. Any order that increases open interest will be rejected by exchange RMS.
  - Ban Exit: A security exits the ban period when its MWPL utilization drops below 80%.
  - Pre-Ban Squeeze: When MWPL is between 88% and 94.9%, short-covering velocity surges, creating explosive upside gamma.

Zero AI Hallucination Invariant:
  - If official MWPL data is unavailable, this service returns None / UNAVAILABLE.
  - It NEVER synthesizes fictitious MWPL percentages (such as 89.5% or 72.0%).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.constants import IST
from config.paths import app_data_path
from market.instruments import canonical_symbol

logger = logging.getLogger("market.fno_ban")

_CACHE_DIR = app_data_path("cache")
_BAN_CACHE_FILE = _CACHE_DIR / "fno_ban_latest.json"
_BAN_LOCK = threading.Lock()


@dataclass
class FnoBanSnapshot:
    as_of_date: str
    banned_symbols: list[str] = field(default_factory=list)
    mwpl_utilization: dict[str, float] = field(default_factory=dict)  # Symbol -> MWPL % (e.g. 91.5)
    mwpl_limits: dict[str, float] = field(
        default_factory=dict
    )  # Symbol -> official MWPL share limit
    provenance: str = "NSE_OFFICIAL"  # "NSE_OFFICIAL" | "CACHED_EOD" | "EMPTY_DEFAULT"
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# In-memory singleton state
_LATEST_SNAPSHOT: Optional[FnoBanSnapshot] = None


def _load_persisted_snapshot() -> Optional[FnoBanSnapshot]:
    """Loads persisted F&O ban snapshot from disk."""
    if not _BAN_CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(_BAN_CACHE_FILE.read_text(encoding="utf-8"))
        return FnoBanSnapshot(
            as_of_date=raw.get("as_of_date", ""),
            banned_symbols=[s.upper() for s in raw.get("banned_symbols", [])],
            mwpl_utilization={
                k.upper(): float(v) for k, v in raw.get("mwpl_utilization", {}).items()
            },
            mwpl_limits={k.upper(): float(v) for k, v in raw.get("mwpl_limits", {}).items()},
            provenance="CACHED_EOD",
            updated_at=raw.get("updated_at", ""),
        )
    except Exception as e:
        logger.debug(f"[FnoBan] Failed loading persisted ban cache: {e}")
        return None


def _save_persisted_snapshot(snapshot: FnoBanSnapshot) -> None:
    """Persists ban snapshot to disk."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _BAN_CACHE_FILE.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[FnoBan] Failed saving ban cache: {e}")


def record_fno_ban_update(
    banned_symbols: list[str],
    mwpl_map: Optional[dict[str, float]] = None,
    as_of_date: Optional[str] = None,
    source: str = "NSE_OFFICIAL",
    mwpl_limits_map: Optional[dict[str, float]] = None,
) -> FnoBanSnapshot:
    """
    Records an authoritative update of F&O ban securities and MWPL utilization.
    Invoked daily after exchange circular publication or via administrative feeds.
    """
    global _LATEST_SNAPSHOT
    d_str = as_of_date or datetime.now(IST).strftime("%Y-%m-%d")
    clean_banned = sorted(list({canonical_symbol(s).upper() for s in banned_symbols if s}))
    clean_mwpl = (
        {canonical_symbol(k).upper(): float(v) for k, v in mwpl_map.items()} if mwpl_map else {}
    )
    existing_limits = dict(_LATEST_SNAPSHOT.mwpl_limits) if _LATEST_SNAPSHOT else {}
    if mwpl_limits_map:
        for k, v in mwpl_limits_map.items():
            if float(v) > 0:
                existing_limits[canonical_symbol(k).upper()] = float(v)

    with _BAN_LOCK:
        snapshot = FnoBanSnapshot(
            as_of_date=d_str,
            banned_symbols=clean_banned,
            mwpl_utilization=clean_mwpl,
            mwpl_limits=existing_limits,
            provenance=source,
            updated_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        )
        _LATEST_SNAPSHOT = snapshot
        _save_persisted_snapshot(snapshot)

    logger.info(
        f"[FnoBan] Recorded F&O ban update for {d_str}: {len(clean_banned)} banned securities ({', '.join(clean_banned[:5])}...)"
    )
    return snapshot


def get_fno_ban_snapshot() -> FnoBanSnapshot:
    """Returns the current active F&O ban snapshot (loading from disk if uninitialized)."""
    global _LATEST_SNAPSHOT
    with _BAN_LOCK:
        if _LATEST_SNAPSHOT is None:
            _LATEST_SNAPSHOT = _load_persisted_snapshot()
            if _LATEST_SNAPSHOT is None:
                _LATEST_SNAPSHOT = FnoBanSnapshot(
                    as_of_date=datetime.now(IST).strftime("%Y-%m-%d"),
                    banned_symbols=[],
                    mwpl_utilization={},
                    provenance="EMPTY_DEFAULT",
                )
        return _LATEST_SNAPSHOT


def get_fno_ban_list() -> set[str]:
    """Returns the set of canonical underlying symbols currently in the F&O ban period."""
    snap = get_fno_ban_snapshot()
    return set(snap.banned_symbols)


def is_in_fno_ban(symbol: str) -> bool:
    """
    Checks whether a symbol (underlying stock or derivative contract) is currently in the F&O ban period.
    Index derivatives (NIFTY, BANKNIFTY, etc.) are never subject to the single-stock F&O ban.
    """
    clean = canonical_symbol(symbol).upper()
    if clean in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        return False

    # Extract underlying if contract symbol (e.g. SAIL26NOV120CE -> SAIL)
    underlying = clean
    for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        if clean.startswith(idx):
            return False

    # Strip standard month codes and option strikes if symbol has contract structure
    import re

    match = re.match(r"^([A-Z0-9]+?)(?:\d{2}[A-Z]{3}|\d{2}[0-9A-Z]{3})", clean)
    if match:
        underlying = match.group(1)

    ban_set = get_fno_ban_list()
    return underlying in ban_set


def get_mwpl_utilization(symbol: str) -> Optional[float]:
    """
    Returns the real reported Market Wide Position Limit (MWPL) utilization percentage for a symbol.
    Returns None if MWPL is unrecorded/unknown — never returns a hallucinated number.
    """
    clean = canonical_symbol(symbol).upper()
    snap = get_fno_ban_snapshot()
    return snap.mwpl_utilization.get(clean)


def compute_intraday_futeq_utilization(
    symbol: str,
    option_chain: list[Any],
    *,
    fut_oi: float = 0.0,
    mwpl_limit: float = 0.0,
    spot: float = 0.0,
) -> dict[str, Any]:
    """Compute SEBI Delta-based Future Equivalent (FutEq) OI and MWPL utilization %.

    Under SEBI's FutEq intraday MWPL rules, calls contribute |N(d1)| * OI, puts contribute
    |N(d1) - 1| * OI, and futures contribute 1.0 * OI, with early warning at 60% and ban at 95%.
    Returns explicit UNAVAILABLE status when option chain or MWPL denominator is missing.
    """
    import math

    clean = canonical_symbol(symbol).upper()
    if mwpl_limit <= 0 or not option_chain:
        return {
            "symbol": clean,
            "status": "UNAVAILABLE",
            "futeq_oi": None,
            "mwpl_utilization_pct": None,
            "warning_level": "UNKNOWN",
        }

    total_futeq = max(0.0, float(fut_oi or 0.0))
    now_r = 0.065

    for c in option_chain:
        if isinstance(c, dict):
            oi = float(c.get("oi", 0) or c.get("open_interest", 0) or 0)
            delta = c.get("delta")
            strike = float(c.get("strike", 0.0) or 0.0)
            iv = float(c.get("iv", 0.0) or 0.0)
            opt_type = str(c.get("option_type", "") or "").upper()
        else:
            oi = float(getattr(c, "oi", 0) or getattr(c, "open_interest", 0) or 0)
            delta = getattr(c, "delta", None)
            strike = float(getattr(c, "strike", 0.0) or 0.0)
            iv = float(getattr(c, "iv", 0.0) or 0.0)
            opt_type = str(getattr(c, "option_type", "") or "").upper()

        if oi <= 0 or opt_type not in ("CE", "PE"):
            continue

        abs_delta = None
        if delta is not None:
            try:
                d_val = float(delta)
                if math.isfinite(d_val) and abs(d_val) > 0:
                    abs_delta = min(1.0, abs(d_val))
            except (TypeError, ValueError):
                abs_delta = None

        if abs_delta is None and spot > 0 and strike > 0:
            sigma = max(0.08, min(2.5, iv / 100.0)) if iv > 0 else 0.25
            t_years = 7.0 / 365.25
            d1 = (math.log(spot / strike) + (now_r + 0.5 * sigma * sigma) * t_years) / (
                sigma * math.sqrt(t_years)
            )
            cdf_d1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
            abs_delta = cdf_d1 if opt_type == "CE" else abs(cdf_d1 - 1.0)

        if abs_delta is not None:
            total_futeq += oi * abs_delta

    util_pct = (total_futeq / float(mwpl_limit)) * 100.0
    if util_pct >= 95.0:
        warning_level = "BAN_PERIOD_RISK"
    elif util_pct >= 60.0:
        warning_level = "BAN_APPROACH_RISK"
    else:
        warning_level = "NORMAL"

    return {
        "symbol": clean,
        "status": "AVAILABLE",
        "futeq_oi": round(total_futeq, 1),
        "mwpl_limit": float(mwpl_limit),
        "mwpl_utilization_pct": round(util_pct, 2),
        "warning_level": warning_level,
    }


def _parse_nse_secban_csv(raw_text: str) -> tuple[Optional[str], list[str]]:
    """Parse NSE official fo_secban.csv into (YYYY-MM-DD, [symbols])."""
    import re

    if not raw_text or not raw_text.strip():
        return None, []

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    parsed_date: Optional[str] = None
    symbols: list[str] = []

    for idx, line in enumerate(lines):
        if idx == 0 and ("BAN" in line.upper() or "TRADE DATE" in line.upper()):
            m = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4}|\d{4}-\d{2}-\d{2})", line)
            if m:
                raw_d = m.group(1)
                for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        parsed_date = datetime.strptime(raw_d, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            continue

        # Standard NSE fo_secban.csv rows: "<slno>,<symbol>" or "<symbol>"
        parts = [p.strip().strip('"').upper() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        candidate = parts[-1] if parts[0].isdigit() and len(parts) >= 2 else parts[0]
        if candidate and candidate.isalnum() and candidate not in ("SYMBOL", "NIL", "NONE"):
            symbols.append(canonical_symbol(candidate).upper())

    return parsed_date, sorted(set(symbols))


def fetch_and_record_nse_fno_ban(
    url: str = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv",
    timeout: float = 10.0,
) -> Optional[FnoBanSnapshot]:
    """Fetch NSE official F&O ban CSV and persist snapshot. Returns None if unavailable."""
    import os
    import urllib.request

    is_test_runner = bool(
        os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
    )
    urlopen_unpatched = getattr(urllib.request.urlopen, "__module__", "") == "urllib.request"
    if is_test_runner and urlopen_unpatched:
        return None

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://www.nseindia.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        as_of_date, banned = _parse_nse_secban_csv(raw)
        if as_of_date is None and not banned and "BAN" not in raw.upper():
            logger.warning("[FnoBan] Unexpected NSE F&O ban response; skipping overwrite.")
            return None
        existing = get_fno_ban_snapshot()
        return record_fno_ban_update(
            banned_symbols=banned,
            mwpl_map=dict(existing.mwpl_utilization) if existing else None,
            as_of_date=as_of_date,
            source="NSE_OFFICIAL",
        )
    except Exception as exc:
        logger.debug(f"[FnoBan] NSE official F&O ban fetch unavailable: {exc}")
        return None


def update_mwpl_utilization_for_symbol(symbol: str, utilization_pct: float) -> None:
    """Persist an observed intraday/official MWPL utilization % without fabricating ban status."""
    if utilization_pct < 0:
        return
    clean = canonical_symbol(symbol).upper()
    with _BAN_LOCK:
        snap = get_fno_ban_snapshot() if _LATEST_SNAPSHOT is None else _LATEST_SNAPSHOT
        if snap is None:
            snap = FnoBanSnapshot(
                as_of_date=datetime.now(IST).strftime("%Y-%m-%d"),
                banned_symbols=[],
                mwpl_utilization={},
                provenance="FUT_EQ_INTRADAY",
            )
        snap.mwpl_utilization[clean] = round(float(utilization_pct), 2)
        snap.updated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        _save_persisted_snapshot(snap)


def _parse_nse_combineoi_csv(raw_text: str) -> tuple[Optional[str], dict[str, float], list[str]]:
    """Parse NSE combined OI/MWPL CSV into (as_of_date, {symbol: mwpl_limit}, banned_symbols)."""
    import csv
    import io

    if not raw_text or not raw_text.strip():
        return None, {}, []

    reader = csv.DictReader(io.StringIO(raw_text))
    if not reader.fieldnames:
        return None, {}, []

    norm_fields = {f.strip().upper(): f for f in reader.fieldnames if f}
    sym_col = next(
        (norm_fields[k] for k in ("NSE SYMBOL", "SYMBOL", "SCRIP") if k in norm_fields), None
    )
    mwpl_col = next(
        (norm_fields[k] for k in ("MWPL", "MWPL LIMIT", "MWPL_LIMIT") if k in norm_fields), None
    )
    oi_col = next(
        (norm_fields[k] for k in ("OPEN INTEREST", "COMBINED OI", "OI") if k in norm_fields), None
    )
    date_col = next((norm_fields[k] for k in ("DATE", "TRADE DATE") if k in norm_fields), None)
    if not sym_col or not mwpl_col:
        return None, {}, []

    limits: dict[str, float] = {}
    banned: list[str] = []
    parsed_date: Optional[str] = None
    for row in reader:
        sym_raw = str(row.get(sym_col) or "").strip().upper()
        if not sym_raw:
            continue
        clean = canonical_symbol(sym_raw).upper()
        try:
            mwpl_val = float(str(row.get(mwpl_col) or "").replace(",", "").strip())
        except ValueError:
            continue
        if mwpl_val <= 0:
            continue
        limits[clean] = mwpl_val
        if oi_col and row.get(oi_col):
            try:
                oi_val = float(str(row.get(oi_col) or "").replace(",", "").strip())
                if (oi_val / mwpl_val) * 100.0 >= 95.0:
                    banned.append(clean)
            except ValueError as e_mwpl:
                logger.debug(f"[FnOBan] Unparseable OI/MWPL value for {clean}: {e_mwpl}")
        if not parsed_date and date_col and row.get(date_col):
            raw_d = str(row[date_col]).strip()
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    parsed_date = datetime.strptime(raw_d, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

    return parsed_date, limits, sorted(set(banned))


def fetch_and_record_nse_mwpl_limits(
    ref_date: Optional[datetime] = None,
    timeout: float = 10.0,
) -> Optional[FnoBanSnapshot]:
    """Fetch official NSE combined OI/MWPL zip/csv to populate per-stock MWPL denominators."""
    import io
    import os
    import urllib.request
    import zipfile

    is_test_runner = bool(
        os.environ.get("CHANAKYA_TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
    )
    urlopen_unpatched = getattr(urllib.request.urlopen, "__module__", "") == "urllib.request"
    if is_test_runner and urlopen_unpatched:
        return None

    dt_ref = ref_date or datetime.now(IST)
    ddmmyyyy = dt_ref.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_{ddmmyyyy}.zip"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "*/*",
            "Referer": "https://www.nseindia.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
        raw_csv = ""
        if raw_bytes[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if csv_names:
                    raw_csv = zf.read(csv_names[0]).decode("utf-8", errors="replace")
        else:
            raw_csv = raw_bytes.decode("utf-8", errors="replace")

        as_of_date, limits, derived_banned = _parse_nse_combineoi_csv(raw_csv)
        if not limits:
            return None
        existing = get_fno_ban_snapshot()
        return record_fno_ban_update(
            banned_symbols=list(existing.banned_symbols)
            if existing and existing.banned_symbols
            else derived_banned,
            mwpl_map=dict(existing.mwpl_utilization) if existing else None,
            as_of_date=as_of_date or dt_ref.strftime("%Y-%m-%d"),
            source="NSE_OFFICIAL",
            mwpl_limits_map=limits,
        )
    except Exception as exc:
        logger.debug(f"[FnoBan] NSE MWPL combined OI fetch unavailable: {exc}")
        return None


def update_intraday_futeq_for_symbol(
    symbol: str,
    option_chain: list[Any],
    *,
    spot: float = 0.0,
    fut_oi: float = 0.0,
) -> dict[str, Any]:
    """Compute intraday SEBI FutEq utilization using persisted official MWPL denominator."""
    clean = canonical_symbol(symbol).upper()
    snap = get_fno_ban_snapshot()
    mwpl_limit = float((snap.mwpl_limits or {}).get(clean, 0.0) or 0.0)
    res = compute_intraday_futeq_utilization(
        clean,
        option_chain,
        fut_oi=fut_oi,
        mwpl_limit=mwpl_limit,
        spot=spot,
    )
    if res.get("status") == "AVAILABLE" and res.get("mwpl_utilization_pct") is not None:
        update_mwpl_utilization_for_symbol(clean, float(res["mwpl_utilization_pct"]))
    return res
