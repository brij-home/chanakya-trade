"""
tests/test_pretrade_fail_closed.py
==================================
Institutional regression test suite for Task P2-C: Pre-trade fail-closed contracts.

Covers:
1. Naked short derivative blocked when available cash is insufficient or missing.
2. Derivative short allowed when cash exceeds total margin required (SPAN+Exposure+ELM).
3. Held-quantity equity sell allowed; insufficient held-quantity blocked.
4. Trading holidays fail closed via exchange calendar.
5. Missing available_cash blocks when require_context=True.
6. Missing prev_close blocks limit orders when require_context=True.
7. Index options late-entry gate (14:40 0-DTE) fires for index options regardless of segment tag.
8. Daily loss cap breach blocks pre-trade execution.
"""

from datetime import datetime

from engine.pretrade import validate_pretrade, _gate_market_session
from engine.session_runway import evaluate_session_runway


def test_naked_short_option_blocked_when_cash_insufficient():
    """Selling an option requires SPAN + Exposure margin; blocks if cash is insufficient."""
    # NIFTY 24500 CE short, 1 lot = 25 qty, underlying spot 24500, price 150
    # Spot notional = 24500 * 25 = 612,500. Total margin is ~12% (SPAN 10% + Expo 2%) = ~73,500
    res = validate_pretrade(
        symbol="NIFTY24OCT24500CE",
        side="SELL",
        quantity=25,
        order_type="LIMIT",
        price=150.0,
        segment="OPTIONS",
        ltp=150.0,
        prev_close=140.0,
        quote_age_seconds=1.0,
        available_cash=20_000.0,  # Far below ~73.5k required
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("Insufficient margin for derivative short" in r for r in res.blocking_reasons)


def test_short_option_allowed_when_margin_sufficient():
    """Selling an option is permitted when cash is greater than required margin."""
    res = validate_pretrade(
        symbol="NIFTY24OCT24500CE",
        side="SELL",
        quantity=25,
        order_type="LIMIT",
        price=150.0,
        segment="OPTIONS",
        ltp=150.0,
        prev_close=140.0,
        quote_age_seconds=1.0,
        available_cash=150_000.0,  # Well above ~73.5k required
        skip_session_check=True,
    )
    assert res.is_eligible, f"Unexpected blocks: {res.blocking_reasons}"
    assert res.gate_results["buying_power"].passed


def test_equity_sell_holdings_check():
    """Equity sell requires held quantity; insufficient holdings block."""
    # Sells with sufficient holdings pass
    res_pass = validate_pretrade(
        symbol="RELIANCE",
        side="SELL",
        quantity=10,
        order_type="MARKET",
        segment="EQ",
        ltp=2500.0,
        quote_age_seconds=1.0,
        held_quantity=15,
        skip_session_check=True,
    )
    assert res_pass.is_eligible
    assert "Equity sell covered by holdings" in res_pass.gate_results["buying_power"].reason

    # Sells with insufficient holdings are blocked
    res_block = validate_pretrade(
        symbol="RELIANCE",
        side="SELL",
        quantity=20,
        order_type="MARKET",
        segment="EQ",
        ltp=2500.0,
        quote_age_seconds=1.0,
        held_quantity=10,
        skip_session_check=True,
    )
    assert not res_block.is_eligible
    assert any("Insufficient holdings" in r for r in res_block.blocking_reasons)


def test_missing_cash_blocked_with_require_context():
    """When require_context=True, missing available_cash blocks BUY orders."""
    res = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=2500.0,
        segment="EQ",
        ltp=2500.0,
        prev_close=2490.0,
        quote_age_seconds=2.0,
        available_cash=None,
        require_context=True,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("available_cash is required" in r for r in res.blocking_reasons)


def test_missing_prev_close_blocked_for_limit_order_with_require_context():
    """When require_context=True, missing prev_close blocks limit price-band validation."""
    res = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=2500.0,
        segment="EQ",
        ltp=2500.0,
        prev_close=None,
        quote_age_seconds=2.0,
        available_cash=50_000.0,
        require_context=True,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("Missing prev_close" in r for r in res.blocking_reasons)


def test_market_session_blocks_on_exchange_holiday(monkeypatch):
    """Trading session blocks on registered national/exchange holidays."""
    from config.constants import IST_ZONE

    # Good Friday 2025-04-18 is an official NSE holiday
    fake_holiday_dt = datetime(2025, 4, 18, 11, 0, tzinfo=IST_ZONE)

    # We mock datetime.now in engine.pretrade
    import engine.pretrade

    _original_datetime = engine.pretrade.datetime

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_holiday_dt

    monkeypatch.setattr(engine.pretrade, "datetime", MockDateTime)

    gate = _gate_market_session("EQ", "RELIANCE")
    assert not gate.passed
    assert "Good Friday" in gate.reason


def test_daily_loss_cap_blocks_execution_with_require_context():
    """When daily loss reaches or exceeds MAX_DAILY_LOSS_CAP_PCT, pretrade blocks."""
    res = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=5,
        order_type="MARKET",
        segment="EQ",
        ltp=2500.0,
        available_cash=100_000.0,
        portfolio_value=100_000.0,
        daily_pnl=-3500.0,  # 3.5% loss >= 3.0% cap
        require_context=True,
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("Daily loss cap reached" in r for r in res.blocking_reasons)


def test_session_runway_0dte_index_option_blocks_after_1440(monkeypatch):
    """Index options tagged OPTIONS/OPT block after 14:40 IST due to theta collapse."""
    from config.constants import IST_ZONE

    late_dt = datetime(2026, 11, 3, 14, 45, tzinfo=IST_ZONE)
    monkeypatch.setenv("FORCE_RUNWAY_CHECK", "1")

    eval_res = evaluate_session_runway(
        symbol="NIFTY26NOVFUT",
        alert_type="INDEX_SCALP",
        segment="OPTIONS",  # Tagged OPTIONS, not FNO_INDEX
        now_dt=late_dt,
    )
    assert not eval_res.is_allowed
    assert "0DTE Theta Cannibalization" in eval_res.veto_reason
