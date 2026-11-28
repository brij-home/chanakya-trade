"""
engine/operational_readiness.py
───────────────────────────────
Honest End-to-End Runtime Calibration & Qualification Readiness Auditor.

Zero-Fabrication & Safety Governance:
  - Reports actual local workspace state without ever enabling live execution flags
    or synthesizing calibration/IV metrics.
  - Evaluates Fyers transport capability using actual submodule probe (`fyers_apiv3.fyersModel`)
    and 06:30 IST daily token boundary check (docs/SAFETY_CONTRACTS.md #22, #32).
  - Surfaces exact open blockers before `LIVE_EXECUTION_QUALIFIED=1` (Contract #12).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from datetime import datetime, time
from typing import Any

from config.constants import IST
from config.discovery_policy import get_discovery_policy
from config.paths import app_data_path

logger = logging.getLogger(__name__)

CORE_READINESS_UNIVERSE: tuple[str, ...] = (
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "MIDCPNIFTY",
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "SBIN",
)


def _check_fyers_token_status() -> dict[str, Any]:
    token_path = app_data_path("fyers.json")
    if not token_path.exists():
        return {"token_file_present": False, "fresh_for_session": False, "reason": "NO_TOKEN_FILE"}
    try:
        raw = json.loads(token_path.read_text(encoding="utf-8"))
        has_tok = bool(raw.get("access_token") or raw.get("token"))
        mtime_dt = datetime.fromtimestamp(token_path.stat().st_mtime, tz=IST)
        now_ist = datetime.now(IST)
        cutoff_today = datetime.combine(now_ist.date(), time(6, 30), tzinfo=IST)
        if now_ist >= cutoff_today:
            fresh = mtime_dt >= cutoff_today
        else:
            fresh = True
        return {
            "token_file_present": True,
            "has_access_token": has_tok,
            "updated_at": mtime_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "fresh_since_0630_ist": bool(has_tok and fresh),
        }
    except Exception as exc:
        return {"token_file_present": True, "fresh_for_session": False, "reason": str(exc)}


_READINESS_CACHE_LOCK = None
_READINESS_CACHE: tuple[float, dict[str, Any]] | None = None


def audit_operational_readiness(
    *, check_warehouse_bars: bool = True, max_cache_sec: float = 0.0
) -> dict[str, Any]:
    """Return an authoritative, non-mutating operational readiness and calibration audit."""
    import threading
    import time as _time

    global _READINESS_CACHE_LOCK, _READINESS_CACHE
    if max_cache_sec > 0:
        if _READINESS_CACHE_LOCK is None:
            _READINESS_CACHE_LOCK = threading.Lock()
        with _READINESS_CACHE_LOCK:
            if _READINESS_CACHE and (_time.monotonic() - _READINESS_CACHE[0]) <= max_cache_sec:
                return dict(_READINESS_CACHE[1])

    from engine.calibration_runner import calibration_runner
    from engine.detector_tournament import load_tournament_report
    from engine.iv_surface import load_historical_30d_ivs
    from engine.meta_labeler import load_meta_model
    from engine.tick_warehouse import get_tick_warehouse

    policy = get_discovery_policy()
    now_ist = datetime.now(IST)

    # 1. Execution & Qualification Safety (never bypassed)
    trading_mode = os.environ.get("TRADING_MODE", "PAPER").upper().strip() or "PAPER"
    allow_live = os.environ.get("ALLOW_LIVE_TRADING", "0").strip() == "1"
    live_qualified = os.environ.get("LIVE_EXECUTION_QUALIFIED", "0").strip() == "1"

    # 2. Broker & Transport Capabilities
    has_fyers_sdk = importlib.util.find_spec("fyers_apiv3.fyersModel") is not None
    fyers_plan = os.environ.get("FYERS_PLAN", "").strip()
    if not fyers_plan:
        try:
            from pathlib import Path
            from dotenv import dotenv_values

            for env_candidate in (Path(".env"), app_data_path(".env")):
                if env_candidate.exists():
                    val = str(dotenv_values(env_candidate).get("FYERS_PLAN") or "").strip()
                    if val:
                        fyers_plan = val
                        break
        except Exception as e_env_plan:
            logger.debug(f"[operational_readiness] .env FYERS_PLAN lookup skipped: {e_env_plan}")
    fyers_plan = fyers_plan or "UNSET"
    token_status = _check_fyers_token_status()

    # 3. Warehouse & Calibration Artifacts
    bar_counts: dict[str, int] = {}
    if check_warehouse_bars:
        try:
            from engine.historical_warehouse import historical_warehouse

            for sym in CORE_READINESS_UNIVERSE:
                df_5m = historical_warehouse.load_bars(sym, interval="5m")
                bar_counts[sym] = int(len(df_5m)) if df_5m is not None else 0
        except Exception:
            bar_counts = {}

    cal_status = calibration_runner.get_status().to_dict()
    cal_stale = calibration_runner.is_calibration_stale()
    tournament = load_tournament_report()
    detectors = tournament.get("detectors") or {}
    cal_detectors = [k for k, v in detectors.items() if v.get("status") == "CALIBRATED"]
    promoted_detectors = [
        k for k, v in detectors.items() if v.get("governance") == "PROMOTED_SHADOW"
    ]

    meta_model = load_meta_model()
    iv_depth = {
        sym: len(load_historical_30d_ivs(sym))
        for sym in ("NIFTY", "BANKNIFTY", "SENSEX", "RELIANCE")
    }
    wh_stats = get_tick_warehouse().get_storage_stats(max_cache_sec=max_cache_sec)

    ws_diag: dict[str, Any] = {}
    try:
        from market.ws_subscription_manager import get_ws_subscription_manager

        ws_diag = get_ws_subscription_manager().get_diagnostics()
    except Exception:
        ws_diag = {}

    bse_cap: dict[str, Any] = {}
    try:
        from market.fyers_tbt_manager import get_exchange_depth_capability

        bse_cap = get_exchange_depth_capability("BSE:SENSEX-INDEX")
    except Exception:
        bse_cap = {}

    # 4. Identify Concrete Actionable Gaps Honestly
    gaps: list[str] = []
    if policy.profile != "FNO_ONLY":
        gaps.append(
            f"Discovery profile is '{policy.profile}' rather than strict 'FNO_ONLY' default."
        )
    if not token_status.get("fresh_since_0630_ist"):
        gaps.append("Fyers token absent or stale prior to today's 06:30 IST cutoff.")
    if cal_stale:
        gaps.append("index_calibration.json is missing or stale (>24h / prior date).")
    if not cal_detectors:
        gaps.append("No calibrated detectors in tournament_report.json yet.")
    if meta_model is None or meta_model.status != "CALIBRATED":
        gaps.append("PurgedMetaModel is UNCALIBRATED (requires >=30 two-sided OOS trades).")
    if max(iv_depth.values() or [0]) < 20:
        gaps.append(
            f"IV daily surface depth < 20 sessions (max={max(iv_depth.values() or [0])}); IV Rank stays UNAVAILABLE."
        )
    if not live_qualified:
        gaps.append(
            "LIVE_EXECUTION_QUALIFIED!=1: account-scoped ledger, recovery, protection & broker acceptance remain owner-gated."
        )

    report = {
        "as_of": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "execution_safety": {
            "trading_mode": trading_mode,
            "allow_live_trading": allow_live,
            "live_execution_qualified": live_qualified,
            "live_orders_blocked": not (
                trading_mode == "EXECUTE" and allow_live and live_qualified
            ),
        },
        "discovery_policy": {
            "profile": policy.profile,
            "fno_only": policy.fno_only,
            "source": getattr(policy, "source", "default"),
        },
        "broker_and_feed": {
            "fyers_apiv3_transport_ready": has_fyers_sdk,
            "fyers_plan_env": fyers_plan,
            "fyers_token": token_status,
            "ws_subscriptions": {
                "total_subscribed": ws_diag.get("total_subscribed"),
                "by_purpose": ws_diag.get("by_purpose", {}),
                "retained_out_of_scope_symbols": ws_diag.get("retained_out_of_scope_symbols", []),
            },
            "bse_depth_capability": bse_cap,
        },
        "calibration_and_research": {
            "index_calibration_status": cal_status,
            "index_calibration_stale": cal_stale,
            "warehouse_5m_bars": bar_counts,
            "tournament_status": tournament.get("status")
            or ("COMPLETED" if detectors else "UNCALIBRATED"),
            "tournament_calibrated_detectors": cal_detectors,
            "tournament_promoted_shadow": promoted_detectors,
            "tournament_profiles": tournament.get("profiles", {}),
            "meta_model_status": meta_model.status if meta_model else "UNCALIBRATED",
            "meta_model_samples": meta_model.sample_count if meta_model else 0,
            "meta_model_oos_brier": meta_model.oos_brier_score if meta_model else None,
            "iv_daily_surface_sessions": iv_depth,
            "iv_rank_ready": any(v >= 20 for v in iv_depth.values()),
            "tick_warehouse": {
                "total_mb": wh_stats.get("total_mb"),
                "segment_files": wh_stats.get("segment_files"),
                "date_partitions": wh_stats.get("date_partitions"),
            },
        },
        "open_gaps": gaps,
    }
    if max_cache_sec > 0 and _READINESS_CACHE_LOCK is not None:
        with _READINESS_CACHE_LOCK:
            _READINESS_CACHE = (_time.monotonic(), dict(report))
    return report
