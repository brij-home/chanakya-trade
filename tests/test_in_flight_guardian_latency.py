"""
tests/test_in_flight_guardian_latency.py
────────────────────────────────────────
Regression tests for high-frequency in-flight trade guardian:
1. Verifies that hedge plan legs with display strings containing spaces are never queried as quotes.
2. Verifies that get_quote accepts priority="URGENT" and passes FyersCallCategory.URGENT_QUOTE.
3. Verifies that in-flight guardian coalesces quote fetching and reuses quotes_map across all checks.
"""

from collections import OrderedDict
from unittest.mock import MagicMock, patch

from brokers.base import Quote
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from market.fyers_rate_gate import FyersCallCategory


def _make_alert(
    alert_id: str, symbol: str = "NIFTY", stage: str = "IGNITED", **kwargs
) -> AutoAlert:
    defaults = {
        "alert_type": "INDEX_CALL_SETUP",
        "exchange": "NSE",
        "direction": "BULLISH",
        "headline": "Test Headline",
        "summary": "Test Summary",
        "ltp": 120.0,
        "trigger_level": 120.0,
        "target_level": 160.0,
        "stop_loss": 95.0,
    }
    defaults.update(kwargs)
    return AutoAlert(
        alert_id=alert_id,
        stage=stage,
        symbol=symbol,
        **defaults,
    )


def test_batch_refresh_quotes_sanitizes_display_strings_with_spaces():
    """Hedge plan legs often have display text like 'LODHA 1080 CE'. These must NOT be sent to broker quotes."""
    engine = AutoAlertEngine()

    mock_alert = _make_alert(
        alert_id="test-alert-1",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26O1922950CE",
        actionable_plan={
            "hedge_plan": {
                "legs": [
                    {"instrument": "LODHA 1080 CE", "strike": 1080.0},
                    {"instrument": "NSE:NIFTY26O1922950CE", "strike": 22950.0},
                    {"symbol": "PERSISTENT 6200 CE", "strike": 6200.0},
                    {"contract": "NFO:RELIANCE26OCT1400CE", "strike": 1400.0},
                ]
            }
        },
    )

    with patch("market.quotes.get_quote") as mock_get_quote:
        mock_get_quote.return_value = {
            "NSE:NIFTY26O1922950CE": Quote(symbol="NIFTY26O1922950CE", last_price=165.0),
            "NFO:RELIANCE26OCT1400CE": Quote(symbol="RELIANCE26OCT1400CE", last_price=25.0),
        }

        res = engine._batch_refresh_quotes([mock_alert], priority="URGENT")
        assert "NSE:NIFTY26O1922950CE" in res

        assert mock_get_quote.called
        called_syms = mock_get_quote.call_args[0][0]
        # Verify no symbols with spaces were passed to get_quote
        for s in called_syms:
            clean_s = s.split(":")[-1]
            assert " " not in clean_s, f"Symbol '{s}' has space and should have been sanitized!"
            assert "LODHA 1080 CE" not in s
            assert "PERSISTENT 6200 CE" not in s

        # Verify valid contract symbols were preserved
        assert any("NIFTY26O1922950CE" in s for s in called_syms)
        assert any("RELIANCE26OCT1400CE" in s for s in called_syms)


def test_get_quote_passes_urgent_category_to_broker():
    """Verifies that calling get_quote(..., priority='URGENT') routes category=URGENT_QUOTE to the data broker."""
    from market.quotes import get_quote

    mock_broker = MagicMock()
    mock_broker.get_quote.return_value = {
        "NSE:NIFTY50-INDEX": Quote(symbol="NIFTY50-INDEX", last_price=22950.0)
    }

    with (
        patch("market.quotes.get_data_broker", return_value=mock_broker),
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.quotes._QUOTE_CACHE", OrderedDict()),
        patch("market.quotes._ws_quotes", return_value={}),
    ):
        res = get_quote(["NSE:NIFTY 50"], bypass_cache=True, priority="URGENT")
        assert len(res) == 1
        assert mock_broker.get_quote.called
        kwargs = mock_broker.get_quote.call_args[1]
        assert kwargs.get("category") == FyersCallCategory.URGENT_QUOTE


def test_guardian_loop_passes_pre_fetched_quotes_map():
    """Verifies that check_and_alert_targets_and_trailing uses pre-fetched quotes_map without re-fetching quotes."""
    engine = AutoAlertEngine()
    alert = _make_alert(
        alert_id="test-target-alert",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26O1922950CE",
        stage="IGNITED",
        ltp=120.0,
        target_level=159.05,
        stop_loss=95.9,
    )
    engine._alerts = [alert]

    pre_fetched_map = {
        "NSE:NIFTY26O1922950CE": 165.0,
        "NIFTY26O1922950CE": 165.0,
    }

    with (
        patch.object(engine, "_batch_refresh_quotes") as mock_batch_refresh,
        patch.object(engine, "_dispatch"),
    ):
        # Call with pre-fetched quotes_map
        engine.check_and_alert_targets_and_trailing(quotes_map=pre_fetched_map)

        # Verify _batch_refresh_quotes was NOT called because quotes_map was provided
        assert not mock_batch_refresh.called
        assert alert.ltp == 165.0
