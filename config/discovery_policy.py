"""Discovery scope, independent of execution mode and existing-exposure care."""

from dataclasses import dataclass
from functools import wraps
import logging
import os
from typing import Callable, Union

from config.constants import SESSION_FOCUS_MODE

logger = logging.getLogger(__name__)
_PROFILES = frozenset({"FNO_ONLY", "FNO_PRIORITY", "BALANCED"})
_FNO_DESKS = frozenset({"FNO", "FNO_INDEX", "FNO_STOCK"})


@dataclass(frozen=True)
class DiscoveryPolicy:
    profile: str

    @property
    def fno_only(self) -> bool:
        return self.profile == "FNO_ONLY"

    def allows(self, desk: str) -> bool:
        # Legacy PRIORITY retains its existing session behavior. Strict scope
        # is enforced even in tests, after hours and on explicit scan calls.
        return not self.fno_only or desk.upper() in _FNO_DESKS

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "discovery_segments": sorted(_FNO_DESKS - {"FNO"}) if self.fno_only else ["ALL"],
            "priority": ["EXISTING_EXPOSURE", "FNO_INDEX", "FNO_STOCK", "CONTEXT", "RESEARCH"],
            "existing_exposure_monitoring": "UNRESTRICTED_BY_FOCUS",
        }


def _get_persisted_profile() -> Union[str, None]:
    """Retrieve persisted discovery profile from disk if set and not in testing."""
    is_testing = bool(
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )
    if is_testing and os.environ.get("TEST_DISCOVERY_PERSISTENCE") != "1":
        return None
    try:
        from config.paths import app_data_path
        import json

        p = app_data_path("discovery_profile.json")
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            prof = data.get("profile")
            if prof in _PROFILES:
                return prof
    except Exception as e_read:
        logger.debug(f"[discovery_policy] Could not load persisted profile: {e_read}")
    return None


def _persist_profile(prof: str) -> None:
    """Persist selected discovery profile to disk for cross-session survival."""
    is_testing = bool(
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )
    if is_testing and os.environ.get("TEST_DISCOVERY_PERSISTENCE") != "1":
        return
    try:
        from config.paths import app_data_path
        import json

        p = app_data_path("discovery_profile.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"profile": prof}), encoding="utf-8")
    except Exception as e_write:
        logger.debug(f"[discovery_policy] Could not persist discovery profile: {e_write}")


def get_discovery_policy() -> DiscoveryPolicy:
    env_prof = os.environ.get("SESSION_FOCUS_MODE")
    if env_prof:
        profile = env_prof.strip().upper()
    else:
        persisted = _get_persisted_profile()
        profile = persisted.strip().upper() if persisted else SESSION_FOCUS_MODE.strip().upper()
    if profile not in _PROFILES:
        raise ValueError(f"Unknown SESSION_FOCUS_MODE: {profile!r}; expected {sorted(_PROFILES)}")
    return DiscoveryPolicy(profile)


def set_discovery_policy(profile: str) -> DiscoveryPolicy:
    """Dynamically update and persist discovery policy profile (FNO_ONLY, FNO_PRIORITY, BALANCED)."""
    prof = profile.strip().upper()
    if prof not in _PROFILES:
        raise ValueError(f"Unknown SESSION_FOCUS_MODE: {prof!r}; expected {sorted(_PROFILES)}")
    os.environ["SESSION_FOCUS_MODE"] = prof
    _persist_profile(prof)
    logger.info("[discovery_policy] Session focus mode dynamically updated to: %s", prof)
    return DiscoveryPolicy(prof)


def discovery_desk(desk: Union[str, Callable[..., str]]):
    """Gate list-returning discovery functions before imports, feeds and AI work.

    Supports static desk names ('CASH', 'FNO_STOCK', 'FNO_INDEX') or dynamic
    callables (e.g. evaluating desk from function arguments).
    Never decorate lifecycle/exit/guardian functions with this policy.
    """

    def decorate(function):
        @wraps(function)
        def gated(*args, **kwargs):
            policy = get_discovery_policy()
            target_desk = desk(*args, **kwargs) if callable(desk) else desk
            if not policy.allows(target_desk):
                logger.debug(
                    "FILTERED_BY_FOCUS profile=%s desk=%s operation=%s",
                    policy.profile,
                    target_desk,
                    function.__qualname__,
                )
                return []
            return function(*args, **kwargs)

        return gated

    return decorate


def allows_context_symbol(symbol: str) -> bool:
    """Bound background context to domestic index/F&O inputs in strict scope.

    This applies to background discovery context only, never explicit risk
    subscriptions for existing exposure.
    """
    if not get_discovery_policy().fno_only:
        return True
    raw = str(symbol).strip().upper()
    venue, _, ticker = raw.partition(":")
    if not ticker or venue not in {"NSE", "BSE", "NFO", "BFO"}:
        return False
    if ticker.endswith("-INDEX"):
        return True
    from market.instruments import (
        is_derivative_eligible,
        parse_derivative_contract,
        canonical_symbol,
        COMMODITY_SYMBOLS,
        CURRENCY_SYMBOLS,
    )

    parsed = parse_derivative_contract(raw)
    underlying = parsed.underlying if parsed else canonical_symbol(raw)
    return underlying not in COMMODITY_SYMBOLS | CURRENCY_SYMBOLS and is_derivative_eligible(
        underlying
    )
