"""
market/participant_oi.py
────────────────────────
NSE Participant-wise Open Interest (F&O Derivatives) Ingestion & Intelligence.

Ingests the official daily participant-wise trading statistics published by the
National Stock Exchange (NSE) after market close (~18:30–19:00 IST).

Key Quantitative Metrics Extracted:
  1. FII Net Index Futures Long Ratio:
     FII Long % = FII_Index_Long / (FII_Index_Long + FII_Index_Short)
     - < 20%: Extreme bearishness / oversold exhaustion (short squeeze imminent).
     - > 75%: Overcrowded bullishness / distribution risk.
  2. Pro vs. Client Divergence:
     Retail Clients buying calls while Proprietary Desks write calls signals a bull trap.
  3. Net Index Option Delta / PCR across participants.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
from typing import Any, Optional
import httpx
from market.http_pool import get_nse_client

logger = logging.getLogger("market.participant_oi")

IST = timezone(timedelta(hours=5, minutes=30))


def _get_cache_dir() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    p = base / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


CACHE_FILE = _get_cache_dir() / "participant_oi_latest.json"
_CACHE_LOCK = threading.Lock()


@dataclass
class ParticipantRecord:
    client_type: str  # "Client" | "DII" | "FII" | "Pro" | "TOTAL"
    future_index_long: int = 0
    future_index_short: int = 0
    future_stock_long: int = 0
    future_stock_short: int = 0
    option_index_call_long: int = 0
    option_index_put_long: int = 0
    option_index_call_short: int = 0
    option_index_put_short: int = 0
    total_long_contracts: int = 0
    total_short_contracts: int = 0


@dataclass
class ParticipantOISummary:
    as_of_date: str
    fii_index_long_ratio: float  # 0.0 to 1.0 (e.g. 0.35 = 35% Long)
    fii_net_index_futures: int  # Net contracts (Long - Short)
    fii_net_stock_futures: int
    pro_net_index_futures: int
    client_net_index_futures: int
    dii_net_index_futures: int
    fii_index_pcr: float  # Put Long / Call Long
    pro_index_pcr: float
    client_index_pcr: float
    market_bias: str  # "STRONGLY_BULLISH" | "BULLISH" | "NEUTRAL" | "BEARISH" | "STRONGLY_BEARISH" | "SHORT_SQUEEZE_COILING"
    divergence_notes: list[str] = field(default_factory=list)
    records: dict[str, dict[str, int]] = field(default_factory=dict)
    provenance: str = "LIVE_NSE"  # "LIVE_NSE" | "CACHED_EOD" | "DEGRADED_BASELINE"
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Institutional Baseline Fallback (Historical Normative Anchor for Indian Markets)
_BASELINE_FALLBACK = ParticipantOISummary(
    as_of_date="2026-09-11",
    fii_index_long_ratio=0.38,
    fii_net_index_futures=-42500,
    fii_net_stock_futures=185000,
    pro_net_index_futures=22100,
    client_net_index_futures=21400,
    dii_net_index_futures=-1000,
    fii_index_pcr=0.88,
    pro_index_pcr=1.12,
    client_index_pcr=0.92,
    market_bias="NEUTRAL",
    divergence_notes=[
        "FII mildly short index futures (-42.5k contracts); Pro desks carrying slight long delta."
    ],
    provenance="DEGRADED_BASELINE",
)


def parse_participant_csv(csv_text: str, as_of_date: str = "") -> Optional[ParticipantOISummary]:
    """
    Parses NSE Participant OI CSV formatted text.
    Standard NSE header structure:
    Client Type, Future Index Long, Future Index Short, Future Stock Long, Future Stock Short,
    Option Index Call Long, Option Index Put Long, Option Index Call Short, Option Index Put Short, ...
    """
    try:
        reader = csv.reader(io.StringIO(csv_text.strip()))
        rows = [r for r in reader if r and len(r) >= 9]
        if len(rows) < 4:
            return None

        records: dict[str, ParticipantRecord] = {}

        # Look for the row containing 'Client' or 'FII'
        for row in rows:
            clean_cells = [c.strip().replace(",", "") for c in row]
            c_type = clean_cells[0].upper()
            matched_key = None
            if "CLIENT" in c_type:
                matched_key = "Client"
            elif "FII" in c_type or "FPI" in c_type:
                matched_key = "FII"
            elif "DII" in c_type:
                matched_key = "DII"
            elif "PRO" in c_type:
                matched_key = "Pro"
            elif "TOTAL" in c_type:
                matched_key = "TOTAL"

            if matched_key:
                try:
                    records[matched_key] = ParticipantRecord(
                        client_type=matched_key,
                        future_index_long=int(float(clean_cells[1])),
                        future_index_short=int(float(clean_cells[2])),
                        future_stock_long=int(float(clean_cells[3])),
                        future_stock_short=int(float(clean_cells[4])),
                        option_index_call_long=int(float(clean_cells[5])),
                        option_index_put_long=int(float(clean_cells[6])),
                        option_index_call_short=int(float(clean_cells[7])),
                        option_index_put_short=int(float(clean_cells[8])),
                        total_long_contracts=int(float(clean_cells[9]))
                        if len(clean_cells) > 9
                        else 0,
                        total_short_contracts=int(float(clean_cells[10]))
                        if len(clean_cells) > 10
                        else 0,
                    )
                except (ValueError, IndexError):
                    continue

        if "FII" not in records or "Client" not in records:
            return None

        fii = records["FII"]
        fii_tot = fii.future_index_long + fii.future_index_short
        fii_long_ratio = round(fii.future_index_long / max(1, fii_tot), 3)
        fii_net_idx = fii.future_index_long - fii.future_index_short
        fii_net_stk = fii.future_stock_long - fii.future_stock_short

        pro = records.get("Pro", ParticipantRecord("Pro"))
        pro_net_idx = pro.future_index_long - pro.future_index_short

        client = records["Client"]
        client_net_idx = client.future_index_long - client.future_index_short

        dii = records.get("DII", ParticipantRecord("DII"))
        dii_net_idx = dii.future_index_long - dii.future_index_short

        fii_pcr = round(fii.option_index_put_long / max(1, fii.option_index_call_long), 2)
        pro_pcr = round(pro.option_index_put_long / max(1, pro.option_index_call_long), 2)
        client_pcr = round(client.option_index_put_long / max(1, client.option_index_call_long), 2)

        # Quantitative Market Bias & Divergence Evaluation
        notes = []
        if fii_long_ratio <= 0.20:
            bias = "SHORT_SQUEEZE_COILING"
            notes.append(
                f"FII Index Long ratio severely depressed ({fii_long_ratio * 100:.1f}%) — high asymmetry for short-covering squeeze."
            )
        elif fii_long_ratio >= 0.75:
            bias = "STRONGLY_BULLISH"
            notes.append(
                f"FII heavily net long ({fii_long_ratio * 100:.1f}%) — trend continuation active, watch for exhaustion."
            )
        elif fii_long_ratio >= 0.55:
            bias = "BULLISH"
            notes.append(f"FII net long bias ({fii_long_ratio * 100:.1f}%).")
        elif fii_long_ratio <= 0.35:
            bias = "BEARISH"
            notes.append(f"FII net short bias ({fii_long_ratio * 100:.1f}%).")
        else:
            bias = "NEUTRAL"
            notes.append(f"FII balanced position ({fii_long_ratio * 100:.1f}%).")

        # Pro vs Client Smart Money Divergence
        if client_net_idx > 30000 and pro_net_idx < -20000:
            notes.append(
                "Divergence Warning: Retail heavily long index futures while Prop Desks net short."
            )
        elif client_net_idx < -30000 and pro_net_idx > 20000:
            notes.append(
                "Smart Money Trap: Retail heavily short index futures while Prop Desks absorbing long."
            )

        rec_dict = {k: asdict(v) for k, v in records.items()}

        return ParticipantOISummary(
            as_of_date=as_of_date or datetime.now(IST).strftime("%Y-%m-%d"),
            fii_index_long_ratio=fii_long_ratio,
            fii_net_index_futures=fii_net_idx,
            fii_net_stock_futures=fii_net_stk,
            pro_net_index_futures=pro_net_idx,
            client_net_index_futures=client_net_idx,
            dii_net_index_futures=dii_net_idx,
            fii_index_pcr=fii_pcr,
            pro_index_pcr=pro_pcr,
            client_index_pcr=client_pcr,
            market_bias=bias,
            divergence_notes=notes,
            records=rec_dict,
            provenance="LIVE_NSE",
        )
    except Exception as e:
        logger.error("Error parsing participant OI CSV: %s", e)
        return None


def fetch_and_cache_participant_oi() -> ParticipantOISummary:
    """
    Downloads the latest participant-wise open interest CSV from official NSE archives.
    Caches the parsed summary on disk.
    """
    today_ist = datetime.now(IST)
    # If weekend or pre-market, look at previous trading days
    date_candidates = []
    for d_offset in range(0, 5):
        cand = today_ist - timedelta(days=d_offset)
        if cand.weekday() < 5:  # Weekday Mon-Fri
            date_candidates.append(cand.strftime("%d%m%Y"))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    for dt_str in date_candidates:
        url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{dt_str}.csv"
        try:
            client = get_nse_client()
            resp = client.get(url, timeout=6.0)
            if resp.status_code == 200 and len(resp.text) > 200:
                summary = parse_participant_csv(
                    resp.text, as_of_date=f"{dt_str[4:]}-{dt_str[2:4]}-{dt_str[:2]}"
                )
                if summary:
                    summary.provenance = "LIVE_NSE"
                    with _CACHE_LOCK:
                        try:
                            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                                json.dump(summary.to_dict(), f, indent=2)
                        except Exception as write_err:
                            logger.warning(
                                "Could not persist participant OI cache: %s", write_err
                            )
                    return summary
        except Exception as net_err:
            logger.debug("Failed fetching %s: %s", url, net_err)

    # If network fetch failed, check disk cache
    with _CACHE_LOCK:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["provenance"] = "CACHED_EOD"
                    return ParticipantOISummary(**data)
            except Exception as read_err:
                logger.warning("Failed reading participant OI cache: %s", read_err)

    return _BASELINE_FALLBACK


def get_latest_participant_oi() -> ParticipantOISummary:
    """Returns the latest available participant OI summary with in-memory / disk caching."""
    with _CACHE_LOCK:
        if CACHE_FILE.exists():
            try:
                mtime = CACHE_FILE.stat().st_mtime
                age_seconds = datetime.now().timestamp() - mtime
                # Use cache if updated within the last 6 hours
                if age_seconds < 21600:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return ParticipantOISummary(**data)
            except Exception:
                pass

    return fetch_and_cache_participant_oi()
