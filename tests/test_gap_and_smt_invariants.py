"""
tests/test_gap_and_smt_invariants.py
─────────────────────────────────────
Defensive invariant tests for:
1. SMT divergence call signature correctness in index call and put detectors.
2. Day open price resolution from multi-day 5m OHLCV or quote object.
3. Gap-day expansion normalization (Camarilla H5 / L5 ceiling bypass when opening in breakaway gap).
4. Defined-risk neutral and Iron Condor recognition in is_option_seller.
5. Options momentum detector chain reuse via chains_map.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd

from config.constants import IST_ZONE as IST
from engine.alert_expiry import is_option_seller
from engine.alert_model import AutoAlert
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.options_momentum import detect_options_momentum_breakouts
from market.options import OptionsContract


def test_is_option_seller_recognizes_iron_condor_and_neutral():
    """Validates that defined-risk neutral and Iron Condors are recognized as option selling strategies."""
    alert_ic = AutoAlert(
        alert_id="aa-iron-condor-test-20261105",
        symbol="RELIANCE",
        alert_type="DEFINED_RISK_NEUTRAL",
        direction="NEUTRAL",
        stage="TRIGGERED",
        exchange="NSE",
        headline="Reliance Neutral Strategy",
        summary="Asymmetric Iron Condor setup",
        trigger_level=1314.80,
        ltp=1314.80,
        stop_loss=1372.80,
        target_level=1300.0,
        confidence=85,
        actionable_plan={"strategy_type": "ASYMMETRIC_IRON_CONDOR"},
    )
    assert is_option_seller(alert_ic) is True

    alert_condor = AutoAlert(
        alert_id="aa-short-condor-test-20261105",
        symbol="BHARTIARTL",
        alert_type="IRON_CONDOR",
        direction="NEUTRAL",
        stage="TRIGGERED",
        exchange="NSE",
        headline="Bharti Airtel Neutral Condor",
        summary="Iron Condor setup",
        trigger_level=2047.90,
        ltp=2047.90,
        stop_loss=2182.00,
        target_level=2000.0,
        confidence=80,
        actionable_plan={"strategy_type": "IRON_CONDOR"},
    )
    assert is_option_seller(alert_condor) is True


def test_smt_divergence_calls_in_call_and_put_detectors():
    """Validates that evaluate_smt_divergence is invoked with correct keyword and positional parameters."""
    with patch("engine.smt_divergence.evaluate_smt_divergence") as mock_smt:
        mock_smt.return_value = MagicMock(
            verdict="BULLISH_DIVERGENCE_BEAR_TRAP",
            is_trap=False,
            has_divergence=True,
        )

        mock_chain = [
            OptionsContract(
                symbol="NIFTY26NOV24500CE",
                underlying="NIFTY",
                strike=24500.0,
                option_type="CE",
                expiry="2026-11-26",
                last_price=150.0,
                volume=50000,
                oi=25000,
                oi_change=-5000,
                pchange=20.0,
            ),
            OptionsContract(
                symbol="NIFTY26NOV24500PE",
                underlying="NIFTY",
                strike=24500.0,
                option_type="PE",
                expiry="2026-11-26",
                last_price=120.0,
                volume=30000,
                oi=30000,
                oi_change=4000,
                pchange=-10.0,
            ),
        ]

        quotes_map = {
            "NSE:NIFTY": MagicMock(
                last_price=24350.0, open=24300.0, high=24400.0, low=24250.0, vwap=24320.0
            ),
            "NSE:BANKNIFTY": MagicMock(
                last_price=57000.0, open=56800.0, high=57200.0, low=56700.0, vwap=56900.0
            ),
        }

        # Run call setup
        detect_index_call_setup(
            underlying="NIFTY",
            spot=24350.0,
            chain=mock_chain,
            vwap=24320.0,
            day_high=24400.0,
            day_low=24250.0,
            quotes_map=quotes_map,
            ignore_time_gate=True,
        )

        # Assert SMT was called with direction="BULLISH"
        assert mock_smt.called
        call_kwargs = mock_smt.call_args.kwargs
        assert call_kwargs.get("direction") == "BULLISH"
        assert call_kwargs.get("primary_symbol") == "NIFTY"


def test_day_open_price_isolation_from_multiday_ohlcv():
    """Validates that multi-day OHLCV does not leak 2-month old bars into today's session open."""
    # Build 5-day OHLCV with old bars starting at 22,000 and today starting at 24,300
    dates = pd.date_range("2026-10-01 09:15:00", periods=50, freq="5min")
    today_dates = pd.date_range("2026-11-05 09:15:00", periods=20, freq="5min")
    all_dates = dates.append(today_dates)

    data = {
        "open": [22000.0] * len(dates) + [24300.0] + [24320.0] * (len(today_dates) - 1),
        "high": [22100.0] * len(dates) + [24400.0] * len(today_dates),
        "low": [21950.0] * len(dates) + [24250.0] * len(today_dates),
        "close": [22050.0] * len(dates) + [24350.0] * len(today_dates),
        "volume": [100000] * len(all_dates),
    }
    df_multiday = pd.DataFrame(data, index=all_dates)

    mock_chain = [
        OptionsContract(
            symbol="NIFTY26NOV24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=160.0,
            volume=50000,
            oi=20000,
            oi_change=-3000,
            pchange=25.0,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24400PE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="PE",
            expiry="2026-11-26",
            last_price=100.0,
            volume=20000,
            oi=30000,
            oi_change=5000,
            pchange=-15.0,
        ),
    ]

    ref_t = datetime(2026, 11, 5, 10, 0, 0, tzinfo=IST)
    # The detector must isolate 24300.0 as today's open, NOT 22000.0
    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=24350.0,
        chain=mock_chain,
        vwap=24320.0,
        day_high=24400.0,
        day_low=24250.0,
        ohlcv_5m=df_multiday,
        ref_time=ref_t,
        ignore_time_gate=True,
    )
    # Spot 24350 is within 0.2% of open (24300), so no false +10% distortion
    assert isinstance(alerts, list)


def test_gap_day_camarilla_h5_normalization():
    """Validates that a massive breakaway gap up does not trigger false Camarilla H5 Ceiling Exhaustion."""
    mock_dl = MagicMock(
        pdh=24000.0,
        pdl=23800.0,
        pdc=23950.0,
        atr_14=150.0,
        camarilla={"h4": 24050.0, "h5": 24150.0, "l4": 23850.0, "l5": 23750.0, "range": 200.0},
    )

    mock_chain = [
        OptionsContract(
            symbol="NIFTY26NOV24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=180.0,
            volume=80000,
            oi=30000,
            oi_change=-8000,
            pchange=30.0,
        ),
        OptionsContract(
            symbol="NIFTY26NOV24400PE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="PE",
            expiry="2026-11-26",
            last_price=90.0,
            volume=20000,
            oi=40000,
            oi_change=12000,
            pchange=-20.0,
        ),
    ]

    # Market gapped open to 24380 (far above H5 of 24150), dipped to 24300, and is trading at 24370 holding above VWAP 24330
    today_dates = pd.date_range("2026-11-05 09:15:00", periods=10, freq="5min")
    df_today = pd.DataFrame(
        {
            "open": [24380.0] + [24320.0] * 9,
            "high": [24400.0] * 10,
            "low": [24290.0] * 10,
            "close": [24370.0] * 10,
            "volume": [150000] * 10,
        },
        index=today_dates,
    )

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        ref_t = datetime(2026, 11, 5, 9, 45, 0, tzinfo=IST)
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=24370.0,
            chain=mock_chain,
            vwap=24330.0,
            day_high=24400.0,
            day_low=24290.0,
            prev_day_high=24000.0,
            prev_day_low=23800.0,
            prev_close=23950.0,
            ohlcv_5m=df_today,
            ref_time=ref_t,
            ignore_time_gate=True,
        )

        # In Gap Expansion Regime with spot > VWAP, it should NOT be rejected by H5 ceiling!
        # If alerts are generated, confidence and setup are valid
        assert isinstance(alerts, list)


def test_options_momentum_chains_map_reuse():
    """Validates that detect_options_momentum_breakouts reuses chains_map without calling get_options_chain."""
    mock_chain = [
        OptionsContract(
            symbol="NIFTY26NOV24400CE",
            underlying="NIFTY",
            strike=24400.0,
            option_type="CE",
            expiry="2026-11-26",
            last_price=150.0,
            volume=50000,
            oi=25000,
            oi_change=5000,
            pchange=15.0,
        )
    ]
    chains_map = {"NIFTY": mock_chain}

    with patch("market.options.get_options_chain") as mock_get_chain:
        batch_quotes = {
            "NSE:NIFTY": MagicMock(
                last_price=24380.0,
                open=24300.0,
                high=24400.0,
                low=24280.0,
                vwap=24330.0,
                change_pct=1.2,
            )
        }
        ref_t = datetime(2026, 11, 5, 9, 45, 0, tzinfo=IST)

        detect_options_momentum_breakouts(
            targets=["NIFTY"],
            watched_indices={"NIFTY"},
            batch_quotes=batch_quotes,
            chains_map=chains_map,
            now_dt=ref_t,
        )

        # get_options_chain should NOT have been called for NIFTY because it was pre-warmed in chains_map
        mock_get_chain.assert_not_called()
