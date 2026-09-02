"""
tests/test_security_360_unavailable.py
──────────────────────────────────────
Truthfulness tests for engine/security_360.py.

Verifies that the dossier never fabricates investment intelligence when
required inputs are missing, and that it calls real data sources rather
than returning hardcoded values.
"""

from unittest.mock import patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_canon(symbol="RELIANCE"):
    """Minimal canonical instrument stub."""
    m = MagicMock()
    m.symbol = symbol
    m.instrument_id = f"NSE:{symbol}"
    m.exchange = "NSE"
    m.segment = "EQ"
    m.lot_size = 1
    m.tick_size = 0.05
    return m


def _make_session():
    m = MagicMock()
    m.session_state = "CLOSED"
    return m


def _patch_instruments(symbol="RELIANCE"):
    """Context manager that patches market.instruments to return test stubs."""
    from unittest.mock import patch

    canon = _make_canon(symbol)
    session = _make_session()

    return (
        patch("engine.security_360.resolve_canonical_instrument", return_value=canon),
        patch("engine.security_360.get_market_session_state", return_value=session),
        patch(
            "engine.security_360.get_current_ist_time",
            return_value=MagicMock(strftime=lambda fmt: "2026-09-01T15:00:00+05:30"),
        ),
    )


# ── Test: UNAVAILABLE when price cannot be determined ─────────────────────────


def test_s360_no_price_and_quote_failure_returns_unavailable():
    """
    When current_price is None AND the quote fetch raises, the dossier must
    return _status='UNAVAILABLE' with decision=None and no trade levels.
    It must NOT use the former ₹2,500 hardcoded fallback.
    """
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()
    with p1, p2, p3:
        with patch("engine.security_360.get_quote", side_effect=ConnectionError("no network")):
            with patch("market.quotes.get_quote", side_effect=ConnectionError("no network")):
                dossier = build_security_360_dossier("RELIANCE", current_price=None)

    assert dossier._status == "UNAVAILABLE", (
        f"Expected _status='UNAVAILABLE', got {dossier._status!r}. "
        "A dossier built with no price must not claim to be READY."
    )
    assert dossier.current_price == 0.0, (
        "current_price must be 0.0 (not ₹2,500) when the price is unavailable."
    )
    assert dossier.decision is None, (
        "decision must be None when price is unavailable — no trade levels allowed."
    )
    assert dossier._unavailable_reason is not None
    assert len(dossier._unavailable_reason) > 0


def test_s360_zero_price_returns_unavailable():
    """A zero price from the quote is treated as unavailable."""
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()
    with p1, p2, p3:
        with patch("engine.security_360.get_quote", return_value={"price": 0.0}):
            dossier = build_security_360_dossier("RELIANCE", current_price=0)

    assert dossier._status == "UNAVAILABLE"
    assert dossier.decision is None


# ── Test: no trade levels in UNAVAILABLE dossier ─────────────────────────────


def test_s360_unavailable_has_no_trade_levels():
    """
    An UNAVAILABLE dossier must not expose stop-loss, targets, or trade levels.
    These would be fabricated and could harm users.
    """
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()
    with p1, p2, p3:
        with patch("engine.security_360.get_quote", side_effect=ValueError("symbol not found")):
            dossier = build_security_360_dossier("UNKNOWNSYM", current_price=None)

    assert dossier.decision is None
    assert dossier.methodology_lenses == []
    assert dossier.valuation_fair_value is None
    assert dossier.valuation_status == "UNAVAILABLE"


# ── Test: forensic status is not hardcoded ────────────────────────────────────


def test_s360_forensic_status_reflects_real_audit_flagged():
    """
    When audit_company_forensics returns overall_flag='FLAGGED',
    the dossier must reflect 'FLAGGED' — never hardcode 'CLEAN'.
    """
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()

    mock_forensic = MagicMock()
    mock_forensic.overall_flag = "FLAGGED"

    with p1, p2, p3:
        with patch("engine.security_360.get_quote", return_value={"price": 2900.0}):
            with patch(
                "engine.security_360.audit_company_forensics",
                return_value=mock_forensic,
            ):
                dossier = build_security_360_dossier("RELIANCE", current_price=2900.0)

    assert dossier.forensic_status == "FLAGGED", (
        f"forensic_status should be 'FLAGGED', got {dossier.forensic_status!r}. "
        "Do not hardcode 'CLEAN'."
    )


def test_s360_forensic_status_clean_when_audit_clean():
    """When forensic audit returns CLEAN, the dossier should reflect CLEAN."""
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()

    mock_forensic = MagicMock()
    mock_forensic.overall_flag = "CLEAN"

    with p1, p2, p3:
        with patch("engine.security_360.get_quote", return_value={"price": 3000.0}):
            with patch(
                "engine.security_360.audit_company_forensics",
                return_value=mock_forensic,
            ):
                dossier = build_security_360_dossier("TCS", current_price=3000.0)

    assert dossier.forensic_status == "CLEAN"


def test_s360_forensic_unavailable_when_audit_raises():
    """
    When audit_company_forensics raises an exception, forensic_status must be
    'UNAVAILABLE' — not 'CLEAN' or any other fabricated value.
    """
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()

    with p1, p2, p3:
        with patch("engine.security_360.get_quote", return_value={"price": 1800.0}):
            with patch(
                "engine.security_360.audit_company_forensics",
                side_effect=RuntimeError("DB offline"),
            ):
                dossier = build_security_360_dossier("INFY", current_price=1800.0)

    assert dossier.forensic_status == "UNAVAILABLE", (
        f"forensic_status should be 'UNAVAILABLE' on exception, got {dossier.forensic_status!r}."
    )


# ── Test: valuation is not hardcoded ─────────────────────────────────────────


def test_s360_valuation_fair_value_not_hardcoded():
    """
    valuation_fair_value must not be price × 1.15.
    Until real DCF is wired, it must be None with status UNAVAILABLE.
    """
    from engine.security_360 import build_security_360_dossier

    p1, p2, p3 = _patch_instruments()

    with p1, p2, p3:
        with patch("engine.security_360.get_quote", return_value={"price": 2500.0}):
            with patch(
                "engine.security_360.audit_company_forensics",
                return_value=MagicMock(overall_flag="CLEAN"),
            ):
                dossier = build_security_360_dossier("RELIANCE", current_price=2500.0)

    fabricated_fair_value = round(2500.0 * 1.15, 2)
    assert dossier.valuation_fair_value != fabricated_fair_value, (
        f"valuation_fair_value must not be price × 1.15 ({fabricated_fair_value}). "
        "That is not a DCF calculation."
    )
    assert dossier.valuation_status == "UNAVAILABLE"
