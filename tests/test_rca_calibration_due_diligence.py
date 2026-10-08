"""
tests/test_rca_calibration_due_diligence.py
─────────────────────────────────────────────
Comprehensive regression & calibration invariant tests for:
1. BSE/BFO derivative symbol routing in Fyers (_to_fyers_symbol) preventing error -300.
2. Market quotes zero-price filtering: 0.0 quotes never suppress options/fallback snapshots.
3. Alert evaluator due diligence: EARLY_WARNING setups are NEVER falsely expired as
   "Setup did not trigger within momentum window" when quotes are missing or when price
   has actually ignited/reached targets.
4. Physical reach milestone integrity: Alerts at +0.57R de-risk never claim T1 HIT.
"""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_invalidation
from brokers.fyers import _to_fyers_symbol
from bot.free_index_templates import (
    render_free_index_alert,
    render_free_index_milestone,
    MilestoneAlertData,
)

IST = timezone(timedelta(hours=5, minutes=30))


def test_bse_sensex_options_symbol_routing():
    """Verify BSE/BFO option and futures contracts route to BSE: and never NSE:."""
    # Explicit BSE prefix
    assert _to_fyers_symbol("BSE:SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"
    assert _to_fyers_symbol("BSE:SENSEX26OCT72000CE") == "BSE:SENSEX26OCT72000CE"
    assert _to_fyers_symbol("BSE:BANKEX26O0872000PE") == "BSE:BANKEX26O0872000PE"
    assert _to_fyers_symbol("BFO:SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"

    # Implicit prefix (symbol starts with SENSEX or BANKEX derivative)
    assert _to_fyers_symbol("SENSEX26O0872000PE") == "BSE:SENSEX26O0872000PE"
    assert _to_fyers_symbol("BANKEX26O0854000CE") == "BSE:BANKEX26O0854000CE"

    # Standard NSE options remain NSE:
    assert _to_fyers_symbol("NSE:NIFTY26OCT25000CE") == "NSE:NIFTY26OCT25000CE"
    assert _to_fyers_symbol("NIFTY26O0822250PE") == "NSE:NIFTY26O0822250PE"


def test_broker_zero_quote_does_not_suppress_fallback():
    """Verify that a broker returning Quote(last_price=0.0) is not accepted into result."""
    from brokers.base import Quote
    from market.quotes import get_quote

    dummy_zero_quote = Quote(
        symbol="SENSEX26O0872000PE",
        last_price=0.0,
        data_state="UNAVAILABLE",
    )
    mock_broker = MagicMock()
    mock_broker.get_quote.return_value = {"BSE:SENSEX26O0872000PE": dummy_zero_quote}

    # When broker returns 0.0, it should not be in final result unless fallback resolves it
    with (
        patch("market.quotes.get_data_broker", return_value=mock_broker),
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.quotes._QUOTE_CACHE", OrderedDict()),
        patch(
            "market.quotes._options_quotes",
            return_value={
                "BSE:SENSEX26O0872000PE": Quote(symbol="SENSEX26O0872000PE", last_price=505.0)
            },
        ) as mock_opt_fallback,
    ):
        quotes = get_quote(["BSE:SENSEX26O0872000PE"])
        # Fallback MUST be called because broker quote was 0.0
        assert mock_opt_fallback.called
        assert quotes["BSE:SENSEX26O0872000PE"].last_price == 505.0


def test_early_warning_time_stop_due_diligence_missing_quotes():
    """Verify EARLY_WARNING setups are NOT expired when price quotes are missing (0.0 or None)."""
    now = datetime.now(IST)
    old_time = now - timedelta(minutes=70)

    alert = AutoAlert(
        alert_id="aa-test-sensex-pe-72000",
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="SENSEX",
        contract_symbol="BSE:SENSEX26O0872000PE",
        exchange="BSE",
        direction="BEARISH",
        headline="Sensex Put Breakout",
        summary="High gamma expansion",
        ltp=308.15,
        trigger_level=308.15,
        target_level=388.8,
        stop_loss=250.0,
        time_horizon="INTRADAY",
        ttl_seconds=3600,
        created_at=old_time.strftime("%Y-%m-%d %H:%M:%S IST"),
        actionable_plan={"target_1": 388.8, "target_2": 439.3, "recommended_entry": "308.15"},
    )
    alert._force_test_expiry = True

    # Case 1: Quotes missing/unavailable (LTP=0.0) -> MUST NOT expire as untriggered!
    with patch("market.calendar.is_market_open", return_value=True):
        reason = evaluate_alert_invalidation(alert, current_ltp=0.0)
        assert reason is None, "Missing quotes must NOT trigger false Time-Stop expiry"


def test_early_warning_time_stop_due_diligence_ignited_or_hit_targets():
    """Verify EARLY_WARNING setups are NOT expired as untriggered when price breached trigger or hit targets."""
    now = datetime.now(IST)
    old_time = now - timedelta(minutes=70)

    alert = AutoAlert(
        alert_id="aa-test-sensex-pe-72000",
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="SENSEX",
        contract_symbol="BSE:SENSEX26O0872000PE",
        exchange="BSE",
        direction="BEARISH",
        headline="Sensex Put Breakout",
        summary="High gamma expansion",
        ltp=308.15,
        trigger_level=308.15,
        target_level=388.8,
        stop_loss=250.0,
        time_horizon="INTRADAY",
        ttl_seconds=3600,
        created_at=old_time.strftime("%Y-%m-%d %H:%M:%S IST"),
        actionable_plan={"target_1": 388.8, "target_2": 439.3, "recommended_entry": "308.15"},
    )
    alert._force_test_expiry = True

    with patch("market.calendar.is_market_open", return_value=True):
        # Case 2: Market price is ₹460.85 (far above trigger ₹308.15, and above T1 ₹388.8 & T2 ₹439.3)
        reason = evaluate_alert_invalidation(alert, current_ltp=460.85)
        assert reason is None, (
            "Alert that ignited/reached targets MUST NOT expire with 'Setup did not trigger'"
        )

        # Case 3: Market price was unignited (e.g. ₹290.0 < trigger ₹308.15) throughout TTL
        reason_unignited = evaluate_alert_invalidation(alert, current_ltp=290.0)
        assert reason_unignited is not None
        assert "Time-Stop expired: Setup did not trigger" in reason_unignited


def test_milestone_physical_reach_invariant_nifty_22250_pe():
    """Verify NIFTY 22250 PE at LTP ₹96.55 (+0.57R) renders as T0.5 DE-RISK and NEVER T1 HIT."""
    alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-pe-22250-20261008",
        alert_type="GAMMA_BLAST",
        stage="DE_RISK_0_5R",
        symbol="NIFTY",
        contract_symbol="NIFTY26O0822250PE",
        exchange="NSE",
        direction="BEARISH",
        headline="NIFTY 22250 PE Gamma Blast",
        summary="De-risk 0.5R reached",
        ltp=96.55,
        trigger_level=90.45,
        target_level=106.94,
        stop_loss=79.0,
        r_multiple=0.57,
        pnl_pct=6.7,
        time_horizon="INTRADAY",
        actionable_plan={"target_1": 106.94, "target_2": 123.42, "recommended_entry": "90.45"},
    )

    rendered = render_free_index_alert(alert, in_market=True)
    assert "T1 HIT" not in rendered
    assert "hit T1" not in rendered
    assert "T0.5 DE-RISK" in rendered
    assert "₹96.55" in rendered
    assert "+0.53R" in rendered


def test_milestone_render_vetoed_t2_checks_t1():
    """Verify render_free_index_milestone vetoing false T2 checks T1 before demoting."""
    # When LTP reached T1 (₹108.0 >= T1 ₹106.94) but claimed T2 (₹123.42), demote to T1 HIT
    data_t1 = MilestoneAlertData(
        milestone_type="TARGET_2",
        symbol="NIFTY",
        contract="NIFTY26O0822250PE",
        ltp=108.0,
        target_1=106.94,
        target_2=123.42,
        entry_price=90.45,
        initial_sl=79.0,
        r_multiple=1.5,
        pnl_pct=19.4,
    )
    rendered_t1 = render_free_index_milestone(data_t1, in_market=True)
    assert "T2 HIT" not in rendered_t1
    assert "T1 HIT" in rendered_t1

    # When LTP reached neither T2 nor T1 (LTP=96.55), demote to T0.5 DE-RISK
    data_derisk = MilestoneAlertData(
        milestone_type="TARGET_2",
        symbol="NIFTY",
        contract="NIFTY26O0822250PE",
        ltp=96.55,
        target_1=106.94,
        target_2=123.42,
        entry_price=90.45,
        initial_sl=79.0,
        r_multiple=0.57,
        pnl_pct=6.7,
    )
    rendered_derisk = render_free_index_milestone(data_derisk, in_market=True)
    assert "T2 HIT" not in rendered_derisk
    assert "T1 HIT" not in rendered_derisk
    assert "T0.5 DE-RISK" in rendered_derisk
