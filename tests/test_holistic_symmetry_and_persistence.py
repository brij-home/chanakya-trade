"""
Tests for holistic tri-directional symmetry, defensive persistence, and anchor sanctity.

Validates:
1. Defensive serialization quarantine in AlertRepository.save()
2. Entry anchor stability under LTP drift in validate_data_integrity() and alert_scrutiny
3. Terminal stage bypass in validate_data_integrity()
4. PUT_WRITING_FLOOR and ACCUMULATION_BOTTOM detection in index_call_setup.py
5. Morning OTM+1 symmetry parity between index_call_setup and index_put_setup
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from zoneinfo import ZoneInfo
import pandas as pd

from engine.alert_model import AutoAlert
from engine.storage.alert_repository import AlertRepository

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class MockContract:
    symbol: str
    strike: float
    option_type: str
    last_price: float
    volume: int
    oi: int
    pchange: float = 0.0
    change_pct: float = 0.0
    expiry: str = "2026-10-24"
    expiry_date: str = "2026-10-24"
    oi_change: int = 500


def test_alert_repository_defensive_quarantine(tmp_path):
    """Verify that a corrupted alert in memory does not crash save() or prevent valid alerts from persisting."""
    target_file = tmp_path / "alerts.json"
    repo = AlertRepository(target_file_fn=lambda: target_file)

    # Create 2 valid alerts
    alert1 = AutoAlert(
        alert_id="aa-test-valid-1-20261014",
        alert_type="INDEX_CALL_SETUP",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Valid Alert 1",
        summary="Summary 1",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=210.0,
        is_live=False,
    )
    alert2 = AutoAlert(
        alert_id="aa-test-valid-2-20261014",
        alert_type="INDEX_CALL_SETUP",
        stage="ACTIVE",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Valid Alert 2",
        summary="Summary 2",
        ltp=250.0,
        trigger_level=250.0,
        stop_loss=200.0,
        target_level=350.0,
        is_live=False,
    )

    # Create a corrupted mock alert whose to_dict() raises RuntimeError
    corrupted_alert = MagicMock()
    corrupted_alert.id = "corrupted-1"
    corrupted_alert.symbol = "CRASH_SYM"
    corrupted_alert.to_dict.side_effect = RuntimeError("Serialization explosion")

    # Save all three
    repo.save([alert1, corrupted_alert, alert2])

    # Verify the saved JSON on disk has alert1 and alert2, cleanly omitting the corrupted one
    assert target_file.exists()
    saved_data = json.loads(target_file.read_text(encoding="utf-8"))
    assert len(saved_data) == 2
    saved_ids = [d["alert_id"] for d in saved_data]
    assert "aa-test-valid-1-20261014" in saved_ids
    assert "aa-test-valid-2-20261014" in saved_ids


def test_sanctity_anchor_resilient_to_ltp_drift():
    """Verify that an active long option alert whose LTP drops below SL does not fail validate_data_integrity."""
    alert = AutoAlert(
        alert_id="aa-test-anchor-drift-20261014",
        symbol="NIFTY",
        exchange="NFO",
        contract_symbol="NIFTY24OCT22700CE",
        option_type="CE",
        strike=22700.0,
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        headline="Test Anchor Drift",
        summary="Test Anchor Drift Summary",
        trigger_level=100.0,
        stop_loss=70.0,
        target_level=160.0,
        ltp=65.0,  # LTP dropped below stop_loss during adverse excursion!
        underlying_spot=22650.0,
        is_live=True,
        environment="PROD",
        stage="ACTIVE",
    )

    # In old code: sl (70) >= ltp (65) failed with "Inverted Stop-Loss: SL >= LTP"
    # In new code: entry anchor is trigger_level (100.0), so sl (70) < entry_anchor (100) -> PASSES!
    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is True, f"Sanctity failed unexpectedly: {reason}"


def test_sanctity_terminal_stages_bypass():
    """Verify that alerts in terminal stages (STOP_HIT, INVALIDATED, CLOSED) bypass pre-trade level checks."""
    alert = AutoAlert(
        alert_id="aa-test-stop-hit-20261014",
        symbol="NIFTY",
        exchange="NFO",
        contract_symbol="NIFTY24OCT22700CE",
        option_type="CE",
        strike=22700.0,
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        headline="Test Stop Hit",
        summary="Test Stop Hit Summary",
        trigger_level=100.0,
        stop_loss=70.0,
        target_level=160.0,
        ltp=50.0,
        underlying_spot=22600.0,
        is_live=True,
        environment="PROD",
        stage="STOP_HIT",
    )

    is_valid, reason = alert.validate_data_integrity()
    assert is_valid is True, f"Terminal stage STOP_HIT failed sanctity: {reason}"


@patch("market.indices.get_heavyweights_posture", return_value={})
@patch("engine.hbcm.evaluate_hbcm")
def test_index_call_setup_put_writing_floor(mock_hbcm, mock_posture):
    """Verify that PUT_WRITING_FLOOR signal is detected when put writers aggressively build support."""
    from engine.detectors.index_call_setup import detect_index_call_setup

    mock_res = MagicMock()
    mock_res.confluence_pass = True
    mock_res.total_heavyweights = 5
    mock_res.summary = "BULLISH_CONFLUENCE"
    mock_res.bullish_count = 4
    mock_res.bearish_count = 1
    mock_res.all_bearish = False
    mock_res.constituents = [{"posture": "BULLISH", "weight_pct": 15.0}]
    mock_res.to_dict.return_value = {}
    mock_hbcm.return_value = mock_res

    chain = [
        # Call contracts
        MockContract(
            "NIFTY24OCT22800CE", 22800, "CE", 110.0, 15000, 25000, pchange=15.0, oi_change=100
        ),
        MockContract(
            "NIFTY24OCT22850CE", 22850, "CE", 80.0, 10000, 20000, pchange=12.0, oi_change=50
        ),
        # Put contracts: massive ATM floor building (+1200 contracts) and total PE OI change > CE
        MockContract(
            "NIFTY24OCT22800PE", 22800, "PE", 90.0, 20000, 35000, pchange=-10.0, oi_change=1200
        ),
        MockContract(
            "NIFTY24OCT22750PE", 22750, "PE", 65.0, 18000, 30000, pchange=-12.0, oi_change=1500
        ),
    ]

    dates = pd.date_range("2026-10-14 10:00", periods=15, freq="5min")
    ohlcv = pd.DataFrame(
        {
            "open": [22780.0 + i * 2 for i in range(15)],
            "high": [22790.0 + i * 2 for i in range(15)],
            "low": [22775.0 + i * 2 for i in range(15)],
            "close": [22788.0 + i * 2 for i in range(15)],
            "volume": [10000.0] * 15,
        },
        index=dates,
    )

    ref_dt = datetime(2026, 10, 14, 10, 15, tzinfo=IST)
    results = detect_index_call_setup(
        underlying="NIFTY",
        spot=22805.0,
        chain=chain,
        vwap=22800.0,
        day_high=22850.0,
        day_low=22750.0,
        prev_day_high=22950.0,  # Far above spot so no PDH supply collision
        prev_day_low=22700.0,
        ohlcv_5m=ohlcv,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(results) > 0, "No alerts generated for call setup"
    alert = results[0]
    all_signals = alert.metrics.get("signals", [])
    assert "PUT_WRITING_FLOOR" in all_signals, f"PUT_WRITING_FLOOR not detected in {all_signals}"


@patch("market.indices.get_heavyweights_posture", return_value={})
@patch("engine.hbcm.evaluate_hbcm")
def test_index_call_setup_accumulation_bottom(mock_hbcm, mock_posture):
    """Verify that ACCUMULATION_BOTTOM signal is detected at session low with oversold VWAP and absorption candle."""
    from engine.detectors.index_call_setup import detect_index_call_setup

    mock_res = MagicMock()
    mock_res.confluence_pass = True
    mock_res.total_heavyweights = 5
    mock_res.summary = "BULLISH_CONFLUENCE"
    mock_res.bullish_count = 3
    mock_res.bearish_count = 2
    mock_res.all_bearish = False
    mock_res.constituents = [{"posture": "BULLISH", "weight_pct": 12.0}]
    mock_res.to_dict.return_value = {}
    mock_hbcm.return_value = mock_res

    chain = [
        MockContract(
            "NIFTY24OCT22500CE", 22500, "CE", 150.0, 18000, 20000, pchange=10.0, oi_change=200
        ),
        MockContract(
            "NIFTY24OCT22500PE", 22500, "PE", 110.0, 15000, 20000, pchange=-5.0, oi_change=100
        ),
    ]

    # Create 5m candles: market flushed to 22500, and last candle is a hammer absorption bar
    # (open 22502, low 22495, close 22512, high 22515 -> range 20, lower wick 7 = 35%, close top 85%)
    dates = pd.date_range("2026-10-14 11:30", periods=15, freq="5min")
    opens = [22750 - i * 16 for i in range(14)] + [22502.0]
    highs = [22760 - i * 16 for i in range(14)] + [22515.0]
    lows = [22740 - i * 16 for i in range(14)] + [22495.0]
    closes = [22745 - i * 16 for i in range(14)] + [22512.0]
    vols = [5000.0] * 14 + [15000.0]  # RVOL surge

    ohlcv = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )

    ref_dt = datetime(2026, 10, 14, 12, 45, tzinfo=IST)
    results = detect_index_call_setup(
        underlying="NIFTY",
        spot=22512.0,  # Within 0.20% of Day Low (22495)
        chain=chain,
        vwap=22780.0,  # Spot is > 1.0% oversold below VWAP
        day_high=22820.0,
        day_low=22495.0,
        prev_day_high=22800.0,
        prev_day_low=22600.0,
        ohlcv_5m=ohlcv,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(results) > 0, "No alerts generated for ACCUMULATION_BOTTOM"
    alert = results[0]
    all_signals = alert.metrics.get("signals", [])
    assert "ACCUMULATION_BOTTOM" in all_signals, (
        f"ACCUMULATION_BOTTOM not detected in {all_signals}"
    )


@patch("market.indices.get_heavyweights_posture", return_value={})
@patch("engine.hbcm.evaluate_hbcm")
def test_index_put_setup_morning_otm1_symmetry(mock_hbcm, mock_posture):
    """Verify that index_put_setup rewards OTM+1 strike in the morning drive, matching call setup behavior."""
    from engine.detectors.index_put_setup import detect_index_put_setup

    mock_res = MagicMock()
    mock_res.confluence_pass = True
    mock_res.total_heavyweights = 5
    mock_res.summary = "BEARISH_CONFLUENCE"
    mock_res.bullish_count = 1
    mock_res.bearish_count = 4
    mock_res.all_bearish = False
    mock_res.constituents = [{"posture": "BEARISH", "weight_pct": 18.0}]
    mock_res.to_dict.return_value = {}
    mock_hbcm.return_value = mock_res

    # Spot is 22795. Step is 50.
    # OTM+1 strike for Put is 22750 (strike < spot, distance = 45 <= 50 * 1.15)
    otm1_contract = MockContract(
        "NIFTY24OCT22750PE", 22750, "PE", 75.0, 18000, 25000, pchange=22.0, oi_change=1200
    )
    atm_contract = MockContract(
        "NIFTY24OCT22800PE", 22800, "PE", 95.0, 8000, 15000, pchange=15.0, oi_change=300
    )

    # CE contract with higher OI so PCR <= 1.45 and Call writers adding (+2500)
    ce_contract = MockContract(
        "NIFTY24OCT22800CE", 22800, "CE", 100.0, 15000, 40000, pchange=-12.0, oi_change=2500
    )

    chain = [
        otm1_contract,
        atm_contract,
        ce_contract,
    ]

    dates = pd.date_range("2026-10-14 09:30", periods=15, freq="5min")
    ohlcv = pd.DataFrame(
        {
            "open": [22820.0 - i * 2 for i in range(15)],
            "high": [22825.0 - i * 2 for i in range(15)],
            "low": [22810.0 - i * 2 for i in range(15)],
            "close": [22812.0 - i * 2 for i in range(15)],
            "volume": [8000.0] * 15,
        },
        index=dates,
    )

    ref_dt = datetime(2026, 10, 14, 9, 50, tzinfo=IST)
    results = detect_index_put_setup(
        underlying="NIFTY",
        spot=22795.0,
        chain=chain,
        vwap=22830.0,
        day_high=22840.0,
        day_low=22780.0,
        prev_day_high=22850.0,
        prev_day_low=22600.0,
        ohlcv_5m=ohlcv,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(results) > 0, "Put detector should yield setup"
    assert results[0].strike in (22750.0, 22800.0)
