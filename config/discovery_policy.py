"""Discovery scope, independent of execution mode and existing-exposure care."""

from dataclasses import dataclass
from functools import wraps
import logging
import os

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


def get_discovery_policy() -> DiscoveryPolicy:
    profile = os.environ.get("SESSION_FOCUS_MODE", SESSION_FOCUS_MODE).strip().upper()
    if profile not in _PROFILES:
        raise ValueError(f"Unknown SESSION_FOCUS_MODE: {profile!r}; expected {sorted(_PROFILES)}")
    return DiscoveryPolicy(profile)


def set_discovery_policy(profile: str) -> DiscoveryPolicy:
    """Dynamically update discovery policy profile (FNO_ONLY, FNO_PRIORITY, BALANCED)."""
    prof = profile.strip().upper()
    if prof not in _PROFILES:
        raise ValueError(f"Unknown SESSION_FOCUS_MODE: {prof!r}; expected {sorted(_PROFILES)}")
    os.environ["SESSION_FOCUS_MODE"] = prof
    logger.info("[discovery_policy] Session focus mode dynamically updated to: %s", prof)
    return DiscoveryPolicy(prof)


def discovery_desk(desk: str):
    """Gate list-returning discovery functions before imports, feeds and AI work.

    Never decorate lifecycle/exit/guardian functions with this policy.
    """

    def decorate(function):
        @wraps(function)
        def gated(*args, **kwargs):
            policy = get_discovery_policy()
            if not policy.allows(desk):
                logger.debug(
                    "FILTERED_BY_FOCUS profile=%s desk=%s operation=%s",
                    policy.profile,
                    desk,
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
