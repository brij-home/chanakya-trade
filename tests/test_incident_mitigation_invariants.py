"""
tests/test_incident_mitigation_invariants.py
─────────────────────────────────────────────
Institutional regression test suite for system incidents, data integrity,
5W dimensional attribution, scale resolution, and orderbook wall shields.
"""

from unittest.mock import MagicMock, patch

from analysis.universe import CORPORATE_ALIASES
from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import extract_5w_dimensions, generate_session_scorecard


def test_corporate_aliases_does_not_contain_awl():
    """Pillar 1: Ensure Adani Wilmar (AWL) is never aliased to ADANIENT."""
    assert "AWL" not in CORPORATE_ALIASES, (
        "AWL must not be aliased to ADANIENT in CORPORATE_ALIASES"
    )


def test_alert_postmortem_5w_extraction_from_level2_setup():
    """Pillar 2: Verify that extract_5w_dimensions correctly reads from level2_setup."""
    mock_alert = MagicMock()
    mock_alert.alert_type = "OPTIONS_MOMENTUM"
    mock_alert.metrics = {
        "hierarchical_pipeline": {
            "level2_setup": {
                "alpha_thesis": "GAMMA_UNPIN",
                "session_window": "AFTERNOON_EXPANSION",
                "location_anchors": ["INTRADAY_VWAP", "CENTRAL_PIVOT_RANGE"],
                "trapped_counterparty": "TRAPPED_OPTION_WRITERS",
            }
        }
    }

    why, when, where, who = extract_5w_dimensions(mock_alert)
    assert why == "GAMMA_UNPIN"
    assert when == "AFTERNOON_EXPANSION"
    assert where == "INTRADAY_VWAP"
    assert who == "TRAPPED_OPTION_WRITERS"


def test_scorecard_populates_5w_dimensions():
    """Pillar 2: Verify generate_session_scorecard populates 5W breakdown accurately."""
    mock_alert = MagicMock()
    mock_alert.symbol = "NIFTY"
    mock_alert.alert_type = "GAMMA_BLAST"
    mock_alert.has_triggered = True
    mock_alert.is_invalidated = False
    mock_alert.is_disqualified = False
    mock_alert.target_status = "TARGET_HIT"
    mock_alert.achieved_milestones = ["T1"]
    mock_alert.r_multiple = 2.4
    mock_alert.stage = "T1_ACHIEVED"
    mock_alert.metrics = {
        "hierarchical_pipeline": {
            "level2_setup": {
                "alpha_thesis": "GAMMA_BLAST",
                "session_window": "OPENING_DRIVE",
                "location_anchors": ["INTRADAY_VWAP"],
                "trapped_counterparty": "RETAIL_BEAR_TRAP",
            }
        }
    }

    scorecard = generate_session_scorecard([mock_alert], session_date="2026-11-17")
    dim_5ws = scorecard.get("dimensional_attribution_5ws", {})

    assert "OPENING_DRIVE" in dim_5ws["when_session_window"]
    assert dim_5ws["when_session_window"]["OPENING_DRIVE"]["wins"] == 1
    assert "INTRADAY_VWAP" in dim_5ws["where_structural_anchor"]
    assert "RETAIL_BEAR_TRAP" in dim_5ws["who_trapped_counterparty"]


def test_alert_model_sub_1500_spot_sl_isolation():
    """Pillar 4: Verify that stocks trading under ₹1500 do not have spot SL assigned to option SL."""
    alert = AutoAlert(
        alert_id="aa-predator-sweep-irfc-spring-20261117",
        alert_type="PREDATOR_SWEEP",
        stage="IGNITED",
        symbol="IRFC",
        exchange="NSE",
        direction="BULLISH",
        headline="Test IRFC",
        summary="Test IRFC summary",
        ltp=82.05,
        trigger_level=82.53,
        target_level=84.45,
        underlying_spot=82.05,
        stop_loss=81.57,  # Spot stop loss
        option_premium=1.17,
        contract_symbol="NSE:IRFC26NOV83CE",
        option_type="CE",
        strike=83.0,
    )

    # Spot SL must be preserved in structural_spot_sl
    assert alert.structural_spot_sl == 81.57
    assert alert.effective_spot_sl == 81.57

    # Tactical SL must NOT inherit 81.57
    assert alert.tactical_sl is None
    assert alert.effective_option_sl == 0.0

    # If tactical option SL is explicitly specified, effective_option_sl returns it
    alert.tactical_sl = 0.95
    assert alert.effective_option_sl == 0.95
    assert alert.effective_spot_sl == 81.57


def test_alert_model_high_priced_spot_sl():
    """Pillar 4: Verify Maruti at ₹11,000 preserves spot SL cleanly."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-maruti-call-20261117",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="MARUTI",
        exchange="NSE",
        direction="BULLISH",
        headline="Test Maruti",
        summary="Test Maruti summary",
        ltp=11000.0,
        trigger_level=11000.0,
        target_level=11200.0,
        underlying_spot=11000.0,
        stop_loss=10850.0,
        option_premium=220.0,
        contract_symbol="NSE:MARUTI26NOV11000CE",
        option_type="CE",
        strike=11000.0,
    )

    assert alert.structural_spot_sl == 10850.0
    assert alert.effective_spot_sl == 10850.0
    assert alert.effective_option_sl == 0.0


def test_session_close_does_not_trigger_invalidation_lockout():
    """Pillar 3: Verify that SESSION_CLOSE_EXIT alerts are recorded without calling invalidation postmortem."""
    from engine.alert_postmortem_runner import run_eod_alert_postmortems

    mock_alert = MagicMock()
    mock_alert.alert_id = "aa-predator-sweep-irfc-spring-20261117"
    mock_alert.symbol = "IRFC"
    mock_alert.alert_type = "PREDATOR_SWEEP"
    mock_alert.stage = "SESSION_CLOSE_EXIT"
    mock_alert.target_status = "SESSION_CLOSE"
    mock_alert.is_invalidated = False
    mock_alert.is_expired = True
    mock_alert.is_disqualified = False
    mock_alert.has_triggered = True
    mock_alert.achieved_milestones = []
    mock_alert.r_multiple = -0.4
    mock_alert.entry_price = 82.53
    mock_alert.ltp = 82.05
    mock_alert.stop_loss = 81.57
    mock_alert.created_at = "2026-11-17 09:33:59 IST"
    mock_alert.metrics = {}

    mock_engine = MagicMock()
    mock_engine.get_alerts.return_value = [mock_alert]

    with (
        patch(
            "engine.learning_engine.pattern_learning_engine.conduct_invalidation_post_mortem"
        ) as mock_pm,
        patch("engine.learning_engine.pattern_learning_engine.record_trade_outcome") as mock_record,
    ):
        report = run_eod_alert_postmortems(
            auto_engine=mock_engine, force=True, session_date="2026-11-17", broadcast=False
        )

        # conduct_invalidation_post_mortem must NOT be called for clean session close
        mock_pm.assert_not_called()
        assert report["post_mortems_conducted"] == 0

        # record_trade_outcome must be called with SESSION_CLOSE
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["outcome"] == "SESSION_CLOSE"


def test_intraday_spark_obi_wall_shield():
    """Pillar 5: Verify Gate 32 suppresses breakdown spark when severe bid wall (OBI50 >= +0.30) is present."""
    from engine.detectors.intraday_spark import detect_intraday_mover_sparks

    mock_quote = MagicMock()
    mock_quote.symbol = "NSE:MARUTI"
    mock_quote.ltp = 10800.0
    mock_quote.vwap = 11100.0
    mock_quote.change_pct = -2.5
    mock_quote.volume = 5000000
    mock_quote.day_high = 11150.0
    mock_quote.day_low = 10750.0
    mock_quote._is_mock = False
    mock_quote.provider = "live"

    mock_depth_wall = MagicMock()
    mock_depth_wall.best_bid = 10795.0
    mock_depth_wall.best_ask = 10800.0
    mock_depth_wall.obi.return_value = 0.40  # Massive BID wall (+0.40)

    with (
        patch("market.order_book.get_depth_book", return_value=mock_depth_wall),
        patch("engine.precursor_radar.get_scan_universe", return_value=["MARUTI"]),
        patch("engine.detectors.intraday_spark.get_cached_avg_volume_20", return_value=500000),
    ):
        quotes_map = {
            "NSE:MARUTI": mock_quote,
            "NSE:NIFTY": MagicMock(change_pct=-0.5, ltp=24000.0, vwap=24100.0),
        }
        alerts = detect_intraday_mover_sparks(quotes_map=quotes_map, universe=["MARUTI"])

        # Breakdown spark must be suppressed by Gate 32
        assert len(alerts) == 0, "Expected breakdown spark to be suppressed by Gate 32 OBI shield"
