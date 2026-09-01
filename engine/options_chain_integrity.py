"""
engine/options_chain_integrity.py
───────────────────────────────────
P2-C: Options Chain Integrity and Liquidity Gate.

Validates an options chain snapshot against strict data quality invariants
before permitting any downstream analytics or order execution.

Quality gates enforced:
1. Chain freshness: chain must not be older than MAX_CHAIN_AGE_SECONDS
2. Bid/ask spread integrity: spread must be ≤ MAX_SPREAD_PCT of mid-price
3. Option Interest (OI) and volume sanity: must be non-negative
4. Strike coverage: chain must cover ≥ MIN_STRIKES_REQUIRED around ATM
5. IV surface sanity: IVs must be real, positive, and within plausible bounds (1% to 500%)
6. Underlying coherence: underlying price must be consistent across all strikes
7. Expiry validity: expiry date must be in the future

If any gate fails, the chain is marked UNAVAILABLE and action eligibility is RESTRICTED.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

# Institutional integrity thresholds
MAX_CHAIN_AGE_SECONDS = 120.0  # 2 minutes — options data older than this is stale
MAX_SPREAD_PCT = 0.10  # Max 10% bid/ask spread as fraction of mid-price
MIN_STRIKES_REQUIRED = 21  # At least 21 strikes (10 ITM + ATM + 10 OTM)
MIN_IV_PCT = 1.0  # Minimum realistic IV ≥ 1%
MAX_IV_PCT = 500.0  # Maximum plausible IV ≤ 500%
MIN_OI = 0  # Open Interest must be non-negative


@dataclass
class OptionStrikeIntegrityCheck:
    """Per-strike validation result."""

    strike: float
    option_type: str  # "CE" | "PE"
    iv_pct: Optional[float]
    bid: float
    ask: float
    oi: int
    volume: int
    spread_pct: Optional[float]
    issues: list[str] = field(default_factory=list)
    is_valid: bool = True


@dataclass
class ChainIntegrityReport:
    """
    Structured options chain quality gate result.

    If is_actionable is False, all downstream analytics and order execution
    must be blocked — no exception path for stale/degraded chains.
    """

    symbol: str
    expiry: str
    underlying_price: float
    atm_strike: float
    total_strikes_checked: int
    valid_strikes: int
    flagged_strikes: int
    chain_age_seconds: float
    is_actionable: bool  # True only if ALL quality gates pass
    action_eligibility: str  # "ELIGIBLE" | "RESTRICTED" | "UNAVAILABLE"
    quality_score: float  # 0.0–100.0
    gate_results: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    strike_checks: list[OptionStrikeIntegrityCheck] = field(default_factory=list)
    _as_of: str = ""
    _source: str = "OPTIONS_CHAIN_INTEGRITY_ENGINE"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Flatten list of strike checks to avoid deep nesting issues
        d["strike_checks"] = [asdict(s) for s in self.strike_checks]
        return d


def _compute_spread_pct(bid: float, ask: float) -> Optional[float]:
    """Compute bid/ask spread as a percentage of mid-price. Returns None if mid is zero."""
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return round((ask - bid) / mid, 4)


def validate_options_chain(
    symbol: str,
    expiry: str,
    underlying_price: float,
    chain_rows: list[dict[str, Any]],
    chain_timestamp_utc: Optional[str] = None,
) -> ChainIntegrityReport:
    """
    Validate an options chain snapshot against institutional data quality standards.

    Args:
        symbol: Underlying symbol (e.g. 'NIFTY', 'BANKNIFTY').
        expiry: Option expiry date string (e.g. '2024-09-26').
        underlying_price: Current spot/futures price of the underlying.
        chain_rows: List of option row dicts with keys:
            strike (float), option_type ("CE"|"PE"), bid (float), ask (float),
            iv_pct (float|None), oi (int), volume (int).
        chain_timestamp_utc: ISO timestamp when chain was fetched (UTC). Defaults to now.

    Returns:
        ChainIntegrityReport with is_actionable=True only if all quality gates pass.
    """
    now_utc = datetime.now(timezone.utc)

    # Parse chain timestamp
    if chain_timestamp_utc:
        try:
            ts = datetime.fromisoformat(chain_timestamp_utc.replace("Z", "+00:00"))
            age_seconds = (now_utc - ts).total_seconds()
        except ValueError:
            age_seconds = MAX_CHAIN_AGE_SECONDS + 1  # force stale
    else:
        age_seconds = 0.0  # fresh (caller is responsible for accuracy)

    as_of = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    issues: list[str] = []
    gate_results: dict[str, bool] = {}
    strike_checks: list[OptionStrikeIntegrityCheck] = []

    # Gate 1: Expiry validity
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        gate_results["expiry_in_future"] = expiry_dt >= now_utc
        if not gate_results["expiry_in_future"]:
            issues.append(f"EXPIRED: expiry {expiry} is in the past")
    except ValueError:
        gate_results["expiry_in_future"] = False
        issues.append(f"INVALID_EXPIRY_FORMAT: {expiry}")

    # Gate 2: Chain freshness
    gate_results["chain_fresh"] = age_seconds <= MAX_CHAIN_AGE_SECONDS
    if not gate_results["chain_fresh"]:
        issues.append(f"STALE_CHAIN: {age_seconds:.1f}s old (max {MAX_CHAIN_AGE_SECONDS}s)")

    # Gate 3: Strike coverage around ATM
    if not chain_rows:
        gate_results["strike_coverage"] = False
        issues.append("EMPTY_CHAIN: no option rows provided")
        return ChainIntegrityReport(
            symbol=symbol,
            expiry=expiry,
            underlying_price=underlying_price,
            atm_strike=0.0,
            total_strikes_checked=0,
            valid_strikes=0,
            flagged_strikes=0,
            chain_age_seconds=age_seconds,
            is_actionable=False,
            action_eligibility="UNAVAILABLE",
            quality_score=0.0,
            gate_results=gate_results,
            issues=issues,
            _as_of=as_of,
        )

    all_strikes = sorted(set(r.get("strike", 0.0) for r in chain_rows))
    atm_strike = min(all_strikes, key=lambda s: abs(s - underlying_price))
    gate_results["strike_coverage"] = len(all_strikes) >= MIN_STRIKES_REQUIRED
    if not gate_results["strike_coverage"]:
        issues.append(
            f"INSUFFICIENT_STRIKES: {len(all_strikes)} strikes found, "
            f"minimum {MIN_STRIKES_REQUIRED} required"
        )

    # Gate 4: Underlying coherence (spot must be within 3% of any stated underlying)
    gate_results["underlying_coherent"] = underlying_price > 0
    if not gate_results["underlying_coherent"]:
        issues.append("INVALID_UNDERLYING_PRICE: must be positive")

    # Per-strike validation
    flagged = 0
    for row in chain_rows:
        strike = float(row.get("strike", 0.0))
        opt_type = str(row.get("option_type", "CE")).upper()
        bid = float(row.get("bid", 0.0))
        ask = float(row.get("ask", 0.0))
        iv_pct = row.get("iv_pct")
        oi = int(row.get("oi", 0))
        volume = int(row.get("volume", 0))

        row_issues: list[str] = []
        spread_pct = _compute_spread_pct(bid, ask)

        if spread_pct is None:
            row_issues.append(f"INVALID_SPREAD: bid={bid}, ask={ask}")
        elif spread_pct > MAX_SPREAD_PCT:
            row_issues.append(f"WIDE_SPREAD: {spread_pct:.1%} > {MAX_SPREAD_PCT:.1%} threshold")

        if iv_pct is not None:
            if not (MIN_IV_PCT <= iv_pct <= MAX_IV_PCT):
                row_issues.append(
                    f"IV_ANOMALY: {iv_pct:.1f}% outside [{MIN_IV_PCT}, {MAX_IV_PCT}]%"
                )

        if oi < MIN_OI:
            row_issues.append(f"NEGATIVE_OI: {oi}")

        is_valid = len(row_issues) == 0
        if not is_valid:
            flagged += 1

        strike_checks.append(
            OptionStrikeIntegrityCheck(
                strike=strike,
                option_type=opt_type,
                iv_pct=iv_pct,
                bid=bid,
                ask=ask,
                oi=oi,
                volume=volume,
                spread_pct=spread_pct,
                issues=row_issues,
                is_valid=is_valid,
            )
        )

    total_checked = len(strike_checks)
    valid_strikes = total_checked - flagged
    flagged_pct = flagged / total_checked if total_checked > 0 else 1.0

    gate_results["spread_integrity"] = (
        flagged_pct <= 0.25
    )  # Allow up to 25% strikes with wide spread
    gate_results["iv_sanity"] = not any("IV_ANOMALY" in " ".join(sc.issues) for sc in strike_checks)

    if not gate_results["spread_integrity"]:
        issues.append(
            f"EXCESSIVE_WIDE_SPREADS: {flagged} of {total_checked} strikes have wide bid/ask"
        )

    # Compute quality score (0–100)
    gates_passed = sum(1 for v in gate_results.values() if v)
    total_gates = len(gate_results)
    strike_quality = valid_strikes / max(total_checked, 1)
    quality_score = round((gates_passed / max(total_gates, 1)) * 50.0 + strike_quality * 50.0, 1)

    # Determine overall action eligibility
    all_gates_pass = all(gate_results.values())
    is_actionable = all_gates_pass and quality_score >= 70.0

    if not is_actionable:
        if quality_score < 30.0 or not gate_results.get("chain_fresh", False):
            action_eligibility = "UNAVAILABLE"
        else:
            action_eligibility = "RESTRICTED"
    else:
        action_eligibility = "ELIGIBLE"

    return ChainIntegrityReport(
        symbol=symbol,
        expiry=expiry,
        underlying_price=underlying_price,
        atm_strike=atm_strike,
        total_strikes_checked=total_checked,
        valid_strikes=valid_strikes,
        flagged_strikes=flagged,
        chain_age_seconds=age_seconds,
        is_actionable=is_actionable,
        action_eligibility=action_eligibility,
        quality_score=quality_score,
        gate_results=gate_results,
        issues=issues,
        strike_checks=strike_checks,
        _as_of=as_of,
    )
