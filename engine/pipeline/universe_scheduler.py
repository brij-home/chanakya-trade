"""
engine/pipeline/universe_scheduler.py
─────────────────────────────────────
Extracted universe velocity prioritization, strict FNO_ONLY target scheduling,
TBT dynamic grid rotation, and bounded slow-task concurrency isolation.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, Sequence

from config.discovery_policy import allows_context_symbol, get_discovery_policy

logger = logging.getLogger("engine.pipeline.universe_scheduler")

DEFAULT_WATCHED_INDICES: tuple[str, ...] = (
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "SENSEX",
    "BANKEX",
)


def score_symbol_velocity(
    symbol: str,
    quotes_map: dict[str, Any],
    *,
    lot_size: Optional[int] = None,
) -> float:
    """Rank equity/F&O symbol priority from live price change, turnover & TOD RVOL."""
    clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
    q = quotes_map.get(f"NSE:{clean}") or quotes_map.get(f"BSE:{clean}") or quotes_map.get(symbol)
    if not q:
        return 0.0

    is_d = isinstance(q, dict)
    chg = abs(float((q.get("change_pct") if is_d else getattr(q, "change_pct", 0.0)) or 0.0))
    vol = float((q.get("volume") if is_d else getattr(q, "volume", 0.0)) or 0.0)
    ltp = float(
        (
            (q.get("last_price") or q.get("ltp"))
            if is_d
            else (getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0))
        )
        or 0.0
    )
    turnover_cr = (ltp * vol) / 1e7 if (ltp > 0 and vol > 0) else 0.0
    rvol_p = float(
        (
            (q.get("rvol") or q.get("bar_rvol") or q.get("volume_surge"))
            if is_d
            else (
                getattr(q, "rvol", 0.0)
                or getattr(q, "bar_rvol", 0.0)
                or getattr(q, "volume_surge", 0.0)
            )
        )
        or 1.0
    )

    if lot_size is None:
        try:
            from engine.position_sizer import get_lot_size

            lot_sz = get_lot_size(clean) or 1
        except Exception:
            lot_sz = 1
    else:
        lot_sz = max(1, int(lot_size))

    is_fno = lot_sz > 1
    is_liquid = (
        (vol > 300_000) or (turnover_cr >= 10.0) or (is_fno and (vol / max(1, lot_sz) >= 60))
    )
    rvol_boost = 1.4 if (rvol_p >= 1.75 and chg >= 0.40) else 1.0
    drive_boost = 1.0
    if chg >= 0.50 and ltp > 0:
        open_p = float((q.get("open") if is_d else getattr(q, "open", 0.0)) or 0.0)
        high_p = float((q.get("high") if is_d else getattr(q, "high", 0.0)) or 0.0)
        low_p = float((q.get("low") if is_d else getattr(q, "low", 0.0)) or 0.0)
        raw_chg = float((q.get("change_pct") if is_d else getattr(q, "change_pct", 0.0)) or 0.0)
        day_rng = high_p - low_p
        if day_rng > 0:
            close_pos = (ltp - low_p) / day_rng
            if (raw_chg > 0 and close_pos >= 0.72) or (raw_chg < 0 and close_pos <= 0.28):
                drive_boost *= 1.30
            if open_p > 0:
                if (raw_chg > 0 and (open_p - low_p) / ltp <= 0.004) or (
                    raw_chg < 0 and (high_p - open_p) / ltp <= 0.004
                ):
                    drive_boost *= 1.15
            if (day_rng / ltp) * 100.0 >= 1.5 and rvol_p >= 1.5:
                drive_boost *= 1.20

    return chg * (1.5 if is_liquid else 1.0) * rvol_boost * drive_boost


def identify_early_fno_movers(
    equities: Sequence[str],
    quotes_map: Optional[dict[str, Any]],
    *,
    top_n: int = 60,
    min_move_pct: float = 0.5,
) -> list[str]:
    """Zero-chain full-F&O pre-filter surfacing opening drives & early velocity movers."""
    policy = get_discovery_policy()
    filtered: list[str] = []
    for sym in equities:
        clean = sym.upper().replace("NSE:", "").replace("BSE:", "").strip()
        if not clean:
            continue
        if policy.fno_only and not allows_context_symbol(sym if ":" in sym else f"NSE:{clean}"):
            continue
        filtered.append(sym)

    if not quotes_map:
        return filtered[: max(1, int(top_n))]

    active_movers: list[tuple[float, str]] = []
    quiet_pool: list[tuple[float, str]] = []
    for sym in filtered:
        clean = sym.upper().replace("NSE:", "").replace("BSE:", "").strip()
        q = quotes_map.get(f"NSE:{clean}") or quotes_map.get(f"BSE:{clean}") or quotes_map.get(sym)
        score = score_symbol_velocity(sym, quotes_map)
        chg = (
            abs(
                float(
                    (q.get("change_pct") if isinstance(q, dict) else getattr(q, "change_pct", 0.0))
                    or 0.0
                )
            )
            if q
            else 0.0
        )
        if chg >= float(min_move_pct):
            active_movers.append((score, sym))
        else:
            quiet_pool.append((score, sym))

    active_movers.sort(key=lambda item: item[0], reverse=True)
    quiet_pool.sort(key=lambda item: item[0], reverse=True)
    ranked = [sym for _, sym in active_movers] + [sym for _, sym in quiet_pool]
    return ranked[: max(1, int(top_n))]


def prioritize_equities_by_velocity(
    equities: Sequence[str],
    quotes_map: dict[str, Any],
    *,
    rotate_tbt: bool = False,
) -> list[str]:
    """Sort watched equities strictly honoring config.discovery_policy & velocity rank."""
    policy = get_discovery_policy()
    filtered: list[str] = []
    for sym in equities:
        clean = sym.upper().replace("NSE:", "").replace("BSE:", "").strip()
        if not clean:
            continue
        if policy.fno_only:
            full = sym if ":" in sym else f"NSE:{clean}"
            if not allows_context_symbol(full):
                continue
        filtered.append(sym)

    scored = sorted(
        filtered,
        key=lambda s: score_symbol_velocity(s, quotes_map),
        reverse=True,
    )
    if rotate_tbt and scored:
        try:
            from market.fyers_tbt_manager import fyers_tbt_manager

            fyers_tbt_manager.auto_rotate_dynamic_grid(scored[:6])
        except Exception as exc_rot:
            logger.debug(f"[UniverseScheduler] TBT dynamic grid rotation skipped: {exc_rot}")
    return scored


def schedule_cycle_targets(
    watched_equities: Sequence[str],
    quotes_map: dict[str, Any],
    *,
    watched_indices: Sequence[str] = DEFAULT_WATCHED_INDICES,
    max_targets: int = 30,
) -> list[str]:
    """Compose active scan slice prioritizing F&O indices followed by top-velocity F&O stocks."""
    ranked_eq = prioritize_equities_by_velocity(watched_equities, quotes_map, rotate_tbt=False)
    combined = list(dict.fromkeys(list(watched_indices) + ranked_eq))
    return combined[: max(1, int(max_targets))]


class BoundedBackgroundRunner:
    """Runs slow non-critical IO/LLM/compaction jobs off the live scan/trigger critical path."""

    def __init__(self, max_in_flight: int = 2) -> None:
        self._sem = threading.Semaphore(max(1, int(max_in_flight)))

    def submit(self, name: str, fn: Callable[[], Any]) -> bool:
        if not self._sem.acquire(blocking=False):
            logger.debug(f"[BoundedBackgroundRunner] Skipping '{name}': pool saturated.")
            return False

        def _worker() -> None:
            try:
                fn()
            except Exception as exc:
                logger.debug(f"[BoundedBackgroundRunner] Task '{name}' error: {exc}")
            finally:
                self._sem.release()

        t = threading.Thread(target=_worker, daemon=True, name=f"bg-{name[:24]}")
        t.start()
        return True


background_task_runner = BoundedBackgroundRunner(max_in_flight=3)
