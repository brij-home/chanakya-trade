"""
engine/pipeline/alert_dispatcher.py
───────────────────────────────────
Extracted provenance & lifecycle tagger for multi-channel alert dispatch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DispatchClassification:
    env_tag: str  # "[TEST]" | "[OFF-MARKET/EOD]" | "[LIVE]"
    is_test: bool
    in_market: bool
    is_update: bool
    is_runner_exit: bool
    is_t0_5: bool
    is_t1: bool
    is_t2: bool
    is_final: bool
    is_target: bool
    is_session_exit: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_alert_dispatch(alert: Any, *, in_market: bool) -> DispatchClassification:
    """Classify provenance tag and lifecycle milestone flags deterministically."""
    aid = str(getattr(alert, "alert_id", "") or "")
    id_prefix_is_test = aid.startswith("test-") or aid.startswith("mock-")
    is_test = (
        getattr(alert, "environment", "") == "TEST"
        or (not getattr(alert, "is_live", False))
        or id_prefix_is_test
    )
    if is_test:
        env_tag = "[TEST]"
    elif not in_market:
        env_tag = "[OFF-MARKET/EOD]"
    else:
        env_tag = "[LIVE]"

    stage = str(getattr(alert, "stage", "") or "")
    t_status = str(getattr(alert, "target_status", "") or "")
    arch_reason = str(getattr(alert, "archive_reason", "") or "").lower()

    is_update = bool(
        getattr(alert, "telegram_dispatched", False)
        or getattr(alert, "is_invalidated", False)
        or t_status
    )

    is_runner_exit = stage in (
        "RUNNER_EXIT",
        "PROFIT_SECURED",
        "BREAKEVEN_EXIT",
        "RUNNER_CLOSED",
    ) or t_status in ("RUNNER_CLOSED", "RUNNER_EXIT", "PROFIT_SECURED")

    is_t0_5 = (
        stage in ("T0_5_ACHIEVED", "DE_RISK_0_5R")
        or "T0_5" in t_status
        or "T0.5" in t_status
        or "TARGET_0_5" in t_status
    )
    is_t1 = "T1" in t_status or stage == "T1_ACHIEVED"
    is_t2 = stage == "T2_ACHIEVED" or "T2" in t_status or "TARGET_2" in t_status

    is_session_exit = (
        stage in ("SESSION_CLOSE_EXIT", "SESSION_EXPIRED")
        or t_status
        in (
            "SESSION_CLOSE_EXIT",
            "SESSION_EXPIRED",
            "TIME_STOP_EXIT",
            "TIME_STOP_SCRATCH",
            "TIME_EXPIRED",
            "STAGNATION_SCRATCH",
            "SCRATCH",
            "STOP_LOSS_EXIT",
            "STOP_LOSS",
            "INVALIDATED",
        )
        or "session close" in arch_reason
        or "session expired" in arch_reason
    )
    is_final = (not is_session_exit) and (
        stage in ("TARGET_ACHIEVED", "FINAL_TARGET", "FINAL_TARGET_HIT")
        or (stage == "COMPLETED" and "TARGET" in t_status.upper())
        or "FINAL" in t_status
        or ("TARGET" in t_status and "PENDING" not in t_status and not (is_t0_5 or is_t1 or is_t2))
    )
    is_target = is_t0_5 or is_t1 or is_t2 or is_final

    return DispatchClassification(
        env_tag=env_tag,
        is_test=is_test,
        in_market=in_market,
        is_update=is_update,
        is_runner_exit=is_runner_exit,
        is_t0_5=is_t0_5,
        is_t1=is_t1,
        is_t2=is_t2,
        is_final=is_final,
        is_target=is_target,
        is_session_exit=is_session_exit,
    )
