"""Regression tests for 2026-11-27 signal audit fixes (2026-11-28)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.alert_model import AutoAlert
from engine.alert_postmortem_runner import generate_session_scorecard
from engine.confluence_engine import evaluate_confluence
from engine.detectors.pre_inflection_dryup import detect_pre_inflection_dryup
from engine.eod_report_generator import EODReportGenerator
from engine.synthetic_sl import evaluate_synthetic_spot_sl, extract_dte

IST = ZoneInfo("Asia/Kolkata")


def test_extract_dte_prioritizes_future_expiry_over_stale_zero_metric() -> None:
    """32-DTE monthly option (WIPRO26DEC192.5PE) must never be treated as 0-DTE because metrics['dte'] == 0."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-wipro-pe-192p5-1130-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="WIPRO",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="WIPRO 192.5 PE",
        summary="Test",
        ltp=6.08,
        trigger_level=6.08,
        option_premium=6.08,
        stop_loss=4.74,
        initial_stop_loss=4.74,
        target_level=8.20,
        strike=192.5,
        option_type="PE",
        contract_symbol="NSE:WIPRO26DEC192.5PE",
        expiry_date="2026-12-29",
        expiry_type="MONTHLY",
        underlying_spot=192.65,
        structural_spot_sl=194.50,
        created_at="2026-11-27 11:34:20 IST",
        triggered_at="2026-11-27 11:34:20 IST",
        metrics={"dte": 0, "is_0dte": False, "spot_vwap": 193.5},
    )
    assert extract_dte(alert) == 32

    # Ensure 22m velocity check does not label a 32-DTE contract as 0-DTE Theta Expiry
    fake_now = datetime(2026, 11, 27, 11, 57, 0, tzinfo=IST)
    with patch("engine.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        res = evaluate_alert_targets_and_trailing(alert, current_ltp=5.87)
    if res is not None and res.trailing_rationale:
        assert "0-DTE Theta Expiry" not in res.trailing_rationale


def test_compress_stall_risk_does_not_trigger_premature_breakeven_or_disable_shield() -> None:
    """COMPRESS_STALL_RISK tightens SL below entry; it must NOT disable spot freak-wick shielding."""
    alert = AutoAlert(
        alert_id="aa-options-momentum-hyundai-pe-2000-0915-20261127",
        alert_type="OPTIONS_MOMENTUM",
        stage="COMPRESS_STALL_RISK",
        symbol="HYUNDAI",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BEARISH",
        headline="HYUNDAI 2000 PE",
        summary="Test",
        ltp=80.55,
        trigger_level=82.70,
        option_premium=82.70,
        stop_loss=73.88,
        initial_stop_loss=68.02,
        target_level=104.50,
        strike=2000.0,
        option_type="PE",
        contract_symbol="NSE:HYUNDAI26DEC2000PE",
        expiry_date="2026-12-29",
        underlying_spot=2015.0,
        structural_spot_sl=2035.0,
        achieved_milestones=["COMPRESS_STALL_RISK"],
        created_at="2026-11-27 11:17:19 IST",
        triggered_at="2026-11-27 11:17:19 IST",
    )
    with patch("engine.synthetic_sl.fetch_live_underlying_spot", return_value=2014.0):
        # Dip below compressed SL while spot (2014 < 2035) is intact -> shielded, NOT invalidated
        ev = evaluate_synthetic_spot_sl(
            alert, current_option_ltp=72.5, current_spot_override=2014.0
        )
    assert ev.is_invalidated is False
    assert ev.is_freak_wick_shielded is True


def test_pre_ignition_hierarchical_veto_is_untriggered_and_zero_r() -> None:
    """Pre-ignition STALK->PRIMED->INVALIDATED alerts must not book phantom -1.0R losses."""
    vetoed = AutoAlert(
        alert_id="aa-pre-inflection-dryup-drreddy-dryup-15m-20261127",
        alert_type="PRE_INFLECTION_DRYUP",
        stage="INVALIDATED",
        symbol="DRREDDY",
        exchange="NFO",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="DRREDDY dryup",
        summary="Test",
        ltp=38.25,
        trigger_level=38.10,
        stop_loss=29.72,
        initial_stop_loss=29.72,
        target_level=47.24,
        is_invalidated=True,
        invalidation_reason="Hierarchical veto on ignition: Setup lacks structural location confluence (score 65 < 75)",
        created_at="2026-11-27 10:12:26 IST",
        triggered_at=None,
        stage_history=[
            {"from_stage": None, "to_stage": "STALK", "at": "2026-11-27 10:12:26 IST"},
            {"from_stage": "STALK", "to_stage": "PRIMED", "at": "2026-11-27 10:13:40 IST"},
            {"from_stage": "PRIMED", "to_stage": "INVALIDATED", "at": "2026-11-27 10:14:45 IST"},
        ],
    )
    assert vetoed.has_triggered is False

    sc = generate_session_scorecard([vetoed], session_date="2026-11-27")
    assert sc["losses"] == 0
    assert sc["unfulfilled"] == 1
    assert sc["net_realized_r"] == 0.0

    # EOD report also keeps immutable initial_stop_loss in journal and classifies veto as SETUP_DISQUALIFIED
    trailed_win = AutoAlert(
        alert_id="aa-index-call-setup-banknifty-ce-63600-0915-20261127",
        alert_type="INDEX_CALL_SETUP",
        stage="RUNNER_EXIT",
        symbol="BANKNIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="BANKNIFTY 63600 CE",
        summary="Test",
        ltp=1571.60,
        trigger_level=1441.65,
        stop_loss=1580.00,  # Mutated trailing SL above target!
        initial_stop_loss=1280.00,
        target_level=1571.60,
        strike=63600.0,
        option_type="CE",
        contract_symbol="NSE:BANKNIFTY26DEC63600CE",
        achieved_milestones=["T1_ACHIEVED", "RUNNER_EXIT"],
        created_at="2026-11-27 09:34:02 IST",
        triggered_at="2026-11-27 09:34:02 IST",
    )
    gen = EODReportGenerator()
    with (
        patch.object(gen, "_load_alerts", return_value=[vetoed.to_dict(), trailed_win.to_dict()]),
        patch.object(
            gen,
            "_get_market_context",
            return_value={
                "nifty_ltp": 25607.2,
                "nifty_change_pct": -1.07,
                "banknifty_ltp": 63040.9,
                "banknifty_change_pct": -0.78,
                "sensex_ltp": 83339.26,
                "sensex_change_pct": -1.17,
                "vix_ltp": 16.55,
                "market_posture": "BEARISH",
                "fii_net_cr": 0.0,
                "dii_net_cr": 0.0,
            },
        ),
    ):
        rep = gen.generate(target_date="2026-11-27", use_ai=False)
    assert rep.loss_count == 0
    assert rep.untriggered_count == 1
    assert rep.win_count == 1
    bn_entry = next(j for j in rep.journal_entries if "BANKNIFTY" in j.symbol)
    assert bn_entry.stop_loss == 1280.00


def test_pre_inflection_dryup_symmetry_and_real_regime_snapshot(monkeypatch) -> None:
    """Dryup supports symmetric BEARISH coils and respects real RegimeSnapshot(ad_ratio) + NIFTY quote."""
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Bearish distribution coil near POC below SMA20 (with natural two-way oscillation so RSI in 26..58)
    n = 30
    idx = pd.date_range("2026-11-27 09:15", periods=n, freq="15min")
    closes = (
        [1015.0, 1012.0, 1014.0, 1010.0, 1012.0, 1008.0, 1010.0, 1006.0, 1008.0, 1005.0]
        + [1007.0, 1004.0, 1006.0, 1002.0, 1004.0, 1000.0, 1002.0, 999.0, 1001.0, 998.5]
        + [1000.0, 998.0, 999.5, 997.8, 999.2, 998.0, 998.8, 998.2, 998.5, 998.0]
    )
    df_bear = pd.DataFrame(
        {
            "open": [c + 0.5 for c in closes],
            "high": [c + 6.0 for c in closes[:-3]] + [999.8, 999.5, 999.2],
            "low": [c - 6.0 for c in closes[:-3]] + [997.2, 997.2, 997.0],
            "close": closes,
            "volume": [30000.0] * (n - 3) + [9000.0, 8500.0, 8000.0],
        },
        index=idx,
    )

    real_bear_reg = SimpleNamespace(is_edgeless=False, ad_ratio=0.55)
    with (
        patch("engine.market_regime_gate.evaluate_market_regime", return_value=real_bear_reg),
        patch("engine.option_resolver.resolve_option_contract", return_value=None),
    ):
        bear_alert = detect_pre_inflection_dryup(
            "TCS",
            df_bear,
            ltp=998.0,
            timeframe="15m",
            nifty_change_pct=-1.07,
            prev_close=1010.0,
        )
    assert bear_alert is not None
    assert bear_alert.direction == "BEARISH"
    assert bear_alert.stop_loss > bear_alert.trigger_level
    assert bear_alert.target_level < bear_alert.trigger_level
    assert bear_alert.metrics.get("nearest_supply_ob") is not None

    # Bullish coil is suppressed when real RegimeSnapshot has weak A/D (0.55) even without market_bias attr
    df_bull = df_bear.copy()
    bull_closes = [985.0] * 10 + [995.0] * 10 + [1005.0] * 7 + [1006.0, 1006.2, 1006.5]
    df_bull["close"] = bull_closes
    df_bull["open"] = [c - 0.5 for c in bull_closes]
    df_bull["high"] = [c + 5.0 for c in bull_closes[:-3]] + [1007.5, 1007.5, 1007.5]
    df_bull["low"] = [c - 5.0 for c in bull_closes[:-3]] + [1005.5, 1005.5, 1005.5]
    with patch("engine.market_regime_gate.evaluate_market_regime", return_value=real_bear_reg):
        assert (
            detect_pre_inflection_dryup(
                "RELIANCE",
                df_bull,
                ltp=1006.5,
                timeframe="15m",
                nifty_change_pct=-1.07,
                prev_close=1005.0,
            )
            is None
        )


def test_confluence_renormalizes_when_preopen_and_rvol_unrecorded() -> None:
    """Missing RVOL + missing pre-open gap must not artificially floor VWAP/BOS/RRG setups below 65."""
    rep = evaluate_confluence(
        symbol="SHRIRAMFIN",
        direction="BEARISH",
        ltp=925.0,
        vwap=945.0,
        rvol=None,
        pre_open_gap_pct=None,
        sector_quadrant="LAGGING",
        put_oi_change_pct=-12.0,
        market_structure_signal="BOS",
    )
    assert rep.total_score >= 70.0
    assert rep.is_qualified is True
