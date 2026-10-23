"""
tests/test_sebi_expiry_mandate_invariants.py
────────────────────────────────────────────
Permanent static and runtime invariant test suite ensuring:
1. SEBI Single-Weekly Index Mandate (SEBI/HO/MRD/MRD-PoD-2/P/CIR/2024/136):
   - Only NIFTY (Thursday) and SENSEX (Friday) offer weekly contracts.
   - BANKNIFTY, FINNIFTY, MIDCPNIFTY, BANKEX, and single stocks are strictly MONTHLY.
2. System Prompts and Core Templates never inject stale pre-2024 assumptions:
   - No 'Bank Nifty Wednesday weekly expiry'
   - Canonical lot sizes (Nifty 65, BankNifty 30, Sensex 20).
"""

from __future__ import annotations

from datetime import date

from market.calendar import (
    get_nearest_weekly_expiry,
    get_nearest_monthly_expiry,
    get_active_derivative_expiry,
)
from engine.alert_expiry import classify_expiry_type
from agent.prompts.base_prompt import build_system_prompt
from bot.alert_templates import INDEX_EXPIRY_WEEKDAY


def test_sebi_single_weekly_mandate_only_nifty_and_sensex():
    """Verify that only NIFTY and SENSEX are permitted in weekly index expiry mapping."""
    allowed_weekly = {"NIFTY", "SENSEX"}
    for sym in INDEX_EXPIRY_WEEKDAY:
        assert sym in allowed_weekly, f"Discontinued index {sym} found in weekly expiry mapping!"

    assert "BANKNIFTY" not in INDEX_EXPIRY_WEEKDAY
    assert "FINNIFTY" not in INDEX_EXPIRY_WEEKDAY
    assert "MIDCPNIFTY" not in INDEX_EXPIRY_WEEKDAY
    assert "BANKEX" not in INDEX_EXPIRY_WEEKDAY


def test_banknifty_strictly_resolves_to_monthly_expiry():
    """Verify that BANKNIFTY resolves exclusively to monthly expiry across all calendar resolvers."""
    ref_d = date(2026, 10, 19)  # A Monday in mid-October 2026

    # get_nearest_weekly_expiry on BankNifty must automatically redirect to monthly
    weekly_bn = get_nearest_weekly_expiry("BANKNIFTY", ref_date=ref_d)
    monthly_bn = get_nearest_monthly_expiry("BANKNIFTY", ref_date=ref_d)
    active_bn = get_active_derivative_expiry("BANKNIFTY", is_future=False, ref_date=ref_d)

    assert weekly_bn == monthly_bn, "BANKNIFTY weekly resolver did not redirect to monthly expiry!"
    assert active_bn == monthly_bn, "BANKNIFTY active expiry did not resolve to monthly expiry!"
    assert classify_expiry_type(str(active_bn), symbol="BANKNIFTY") == "MONTHLY"

    # Last Thursday of October 2026 is 2026-10-29
    assert active_bn == date(2026, 10, 29)


def test_finnifty_and_midcpnifty_strictly_monthly():
    """Verify FINNIFTY and MIDCPNIFTY are strictly monthly contracts."""
    ref_d = date(2026, 10, 19)

    fin_exp = get_active_derivative_expiry("FINNIFTY", is_future=False, ref_date=ref_d)
    mid_exp = get_active_derivative_expiry("MIDCPNIFTY", is_future=False, ref_date=ref_d)

    assert classify_expiry_type(str(fin_exp), symbol="FINNIFTY") == "MONTHLY"
    assert classify_expiry_type(str(mid_exp), symbol="MIDCPNIFTY") == "MONTHLY"


def test_nifty_and_sensex_resolve_weekly():
    """Verify that NIFTY and SENSEX resolve to their weekly cycle."""
    ref_d = date(2026, 10, 19)  # Monday

    nifty_exp = get_active_derivative_expiry("NIFTY", is_future=False, ref_date=ref_d)
    # Thursday of the same week is 2026-10-22
    assert nifty_exp == date(2026, 10, 22)
    assert classify_expiry_type(str(nifty_exp), symbol="NIFTY") == "WEEKLY"

    sensex_exp = get_active_derivative_expiry("SENSEX", is_future=False, ref_date=ref_d)
    # Friday of the same week is 2026-10-23
    assert sensex_exp == date(2026, 10, 23)
    assert classify_expiry_type(str(sensex_exp), symbol="SENSEX") == "WEEKLY"


def test_base_system_prompt_enforces_sebi_mandate_and_canonical_lots():
    """Verify that build_system_prompt injects the SEBI mandate and current lot sizes."""
    prompt = build_system_prompt()

    assert "SEBI Single-Weekly Index Mandate" in prompt
    assert "NIFTY=65" in prompt
    assert "BANKNIFTY=30" in prompt
    assert "SENSEX=20" in prompt
    assert "NEVER refer to, simulate, or recommend weekly or 0DTE options for BANKNIFTY" in prompt
