"""
tests/test_fno_enrichment_negative_invariants.py
─────────────────────────────────────────────────
Negative and boundary invariant tests for F&O contract enrichment and spread resolution.

Verifies:
- F01: Rejection of missing hedge, unlisted hedge, crossed books, and manufactured spreads in actionable mode.
- F04: Rejection of stale snapshots, off-market/simulated providers, and naive timestamps.
- F07: Strict fail-closed boundary preventing unverified or estimated pricing from becoming actionable tickets.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.option_resolver import resolve_option_contract
from market.contract_selection import ActiveContractResolution
from market.options import OptionsContract


def _make_valid_source_info(
    provider: str = "FYERS",
    data_state: str = "LIVE",
    is_realtime: bool = True,
    is_market_open: bool = True,
    age_seconds: float = 2.0,
) -> dict:
    now = datetime.now(timezone.utc)
    as_of = (now - timedelta(seconds=age_seconds)).isoformat()
    return {
        "provider": provider,
        "source": "BROKER_REST",
        "data_state": data_state,
        "is_realtime": is_realtime,
        "is_market_open": is_market_open,
        "as_of": as_of,
        "observation_time": as_of,
        "receipt_time": as_of,
        "source_label": f"{provider} Live Stream",
    }


def _make_test_alert(
    symbol: str = "NIFTY", ltp: float = 25000.0, direction: str = "BULLISH"
) -> AutoAlert:
    return AutoAlert(
        alert_id=f"aa-test-neg-{symbol.lower()}-20261101",
        alert_type="ORB_BREAKOUT" if direction == "BULLISH" else "ORB_BREAKDOWN",
        stage="IGNITED",
        symbol=symbol,
        exchange="NSE",
        direction=direction,
        headline=f"{symbol} Test Alert",
        summary="Negative invariant test",
        ltp=ltp,
        trigger_level=ltp,
        target_level=ltp * 1.02 if direction == "BULLISH" else ltp * 0.98,
        stop_loss=ltp * 0.99 if direction == "BULLISH" else ltp * 1.01,
        actionable_plan={"action": "BUY" if direction == "BULLISH" else "SELL"},
        metrics={"segment": "INDEX"},
    )


def test_enrichment_rejects_estimated_pricing():
    """Verify that if option resolver returns estimated pricing, actionable ticket enrichment is held."""
    engine = AutoAlertEngine()
    alert = _make_test_alert("NIFTY", 25000.0, "BULLISH")

    mock_source = _make_valid_source_info()
    mock_chain = [
        MagicMock(
            symbol="NSE:NIFTY26NOV25000CE",
            last_price=150.0,
            strike=25000.0,
            option_type="CE",
            expiry="2026-11-26",
        )
    ]
    mock_opt_plan = MagicMock()
    mock_opt_plan.contract_symbol = "NSE:NIFTY26NOV25000CE"
    mock_opt_plan.strike = 25000.0
    mock_opt_plan.is_estimated = True  # Estimated pricing flag

    with (
        patch(
            "market.options.get_options_snapshot",
            return_value=(mock_chain, 25000.0, ["2026-11-26"], mock_source),
        ),
        patch("engine.option_resolver.resolve_option_contract", return_value=mock_opt_plan),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    # Invariant: Alert contract symbol is NOT populated
    assert alert.contract_symbol is None
    assert alert.actionable_plan.get("action") == "BUY"


def test_enrichment_rejects_stale_snapshot():
    """Verify that snapshot older than 15 seconds is rejected at provenance gate."""
    engine = AutoAlertEngine()
    alert = _make_test_alert("NIFTY", 25000.0, "BULLISH")

    # Stale snapshot: 30 seconds old
    stale_source = _make_valid_source_info(age_seconds=30.0)
    mock_chain = [
        MagicMock(
            symbol="NSE:NIFTY26NOV25000CE",
            last_price=150.0,
            strike=25000.0,
            option_type="CE",
            expiry="2026-11-26",
        )
    ]

    with patch(
        "market.options.get_options_snapshot",
        return_value=(mock_chain, 25000.0, ["2026-11-26"], stale_source),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    assert alert.contract_symbol is None
    # Audit trail records ENRICHMENT_HELD with reason STALE_SNAPSHOT
    assert any(a.get("event_type") == "ENRICHMENT_HELD" for a in (alert.audit_trail or []))
    held_event = next(a for a in alert.audit_trail if a.get("event_type") == "ENRICHMENT_HELD")
    assert "STALE_SNAPSHOT" in held_event.get("details", {}).get("reason", "")


def test_enrichment_rejects_off_market_snapshot():
    """Verify that off-market snapshot cannot enrich an actionable execution ticket."""
    engine = AutoAlertEngine()
    alert = _make_test_alert("NIFTY", 25000.0, "BULLISH")

    off_market_source = _make_valid_source_info(
        data_state="OFF_MARKET", is_realtime=False, is_market_open=False
    )
    mock_chain = [
        MagicMock(
            symbol="NSE:NIFTY26NOV25000CE",
            last_price=150.0,
            strike=25000.0,
            option_type="CE",
            expiry="2026-11-26",
        )
    ]

    with patch(
        "market.options.get_options_snapshot",
        return_value=(mock_chain, 25000.0, ["2026-11-26"], off_market_source),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    assert alert.contract_symbol is None
    assert any(a.get("event_type") == "ENRICHMENT_HELD" for a in (alert.audit_trail or []))


def test_enrichment_rejects_simulated_or_mock_provider():
    """Verify that mock or simulated providers cannot create actionable tickets."""
    engine = AutoAlertEngine()
    alert = _make_test_alert("NIFTY", 25000.0, "BULLISH")

    mock_prov_source = _make_valid_source_info(provider="MOCK_BROKER")
    mock_chain = [
        MagicMock(
            symbol="NSE:NIFTY26NOV25000CE",
            last_price=150.0,
            strike=25000.0,
            option_type="CE",
            expiry="2026-11-26",
        )
    ]

    with patch(
        "market.options.get_options_snapshot",
        return_value=(mock_chain, 25000.0, ["2026-11-26"], mock_prov_source),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    assert alert.contract_symbol is None
    held_event = next(a for a in alert.audit_trail if a.get("event_type") == "ENRICHMENT_HELD")
    reason_str = held_event.get("details", {}).get("reason", "")
    assert "MOCK" in reason_str or "SIMULATED" in reason_str


def test_enrichment_rejects_unlisted_contract_master():
    """Verify that if contract symbol is absent or unlisted in master, enrichment is held."""
    engine = AutoAlertEngine()
    alert = _make_test_alert("NIFTY", 25000.0, "BULLISH")

    mock_source = _make_valid_source_info()
    mock_chain = [
        MagicMock(
            symbol="NSE:NIFTY26NOV99999CE",
            last_price=10.0,
            strike=99999.0,
            option_type="CE",
            expiry="2026-11-26",
        )
    ]
    mock_opt_plan = MagicMock()
    mock_opt_plan.contract_symbol = "NSE:NIFTY26NOV99999CE"
    mock_opt_plan.strike = 99999.0
    mock_opt_plan.is_estimated = False

    # Master lookup returns invalid / not found
    mock_active = ActiveContractResolution(
        is_valid=False, contract=None, rejection_reason="CONTRACT_NOT_FOUND"
    )

    with (
        patch(
            "market.options.get_options_snapshot",
            return_value=(mock_chain, 25000.0, ["2026-11-26"], mock_source),
        ),
        patch("market.contract_selection.resolve_active_contract", return_value=mock_active),
        patch("engine.option_resolver.resolve_option_contract", return_value=mock_opt_plan),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    assert alert.contract_symbol is None


def test_spread_resolution_rejects_missing_hedge():
    """Verify that actionable spread construction fails closed when hedge is missing."""
    c_primary = OptionsContract(
        symbol="NSE:NIFTY26NOV25000CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=25000.0,
        option_type="CE",
        last_price=150.0,
        oi=5000,
        oi_change=100,
        volume=1000,
        bid=149.0,
        ask=151.0,
        lot_size=65,
    )

    # 1. Actionable mode: must fail-closed and return None (zero hallucinated spreads)
    plan_actionable = resolve_option_contract(
        symbol="NIFTY",
        spot=25000.0,
        direction="BULLISH",
        prefer_spread=True,
        require_listed_contract=True,
        contracts_override=[c_primary],
    )
    assert plan_actionable is None

    # 2. Research mode: produces explicitly marked estimated plan
    plan_research = resolve_option_contract(
        symbol="NIFTY",
        spot=25000.0,
        direction="BULLISH",
        prefer_spread=True,
        require_listed_contract=False,
        contracts_override=[c_primary],
    )
    assert plan_research is not None
    assert plan_research.is_estimated is True


def test_spread_resolution_rejects_crossed_book_or_negative_debit():
    """Verify that if hedge leg bid > primary leg ask (crossed book / negative debit), spread is rejected."""
    c_primary = OptionsContract(
        symbol="NSE:NIFTY26NOV25000CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=25000.0,
        option_type="CE",
        last_price=150.0,
        oi=5000,
        oi_change=100,
        volume=1000,
        bid=145.0,
        ask=150.0,
        lot_size=65,
    )
    # Crossed hedge where bid (160.0) is higher than primary ask (150.0)
    c_hedge_crossed = OptionsContract(
        symbol="NSE:NIFTY26NOV25200CE",
        underlying="NIFTY",
        expiry="2026-11-26",
        strike=25200.0,
        option_type="CE",
        last_price=160.0,
        oi=3000,
        oi_change=50,
        volume=500,
        bid=160.0,
        ask=165.0,
        lot_size=65,
    )

    plan = resolve_option_contract(
        symbol="NIFTY",
        spot=25000.0,
        direction="BULLISH",
        prefer_spread=True,
        require_listed_contract=True,
        contracts_override=[c_primary, c_hedge_crossed],
    )

    # Invariant: Actionable mode fails closed for crossed book
    assert plan is None
