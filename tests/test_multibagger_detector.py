"""
tests/test_multibagger_detector.py
──────────────────────────────────
Unit tests for institutional Multibagger and Stage 1-to-2 Expansion detector:
  1. Verifies detector evaluates high-growth universe and discovers multibaggers.
  2. Verifies AutoAlert time_horizon, eta_label, and actionable blueprints.
  3. Verifies alert identity invariants (Rule 17: no timestamps, deterministic session ID).
  4. Verifies integration with AutoAlertEngine.scan_multibagger_compounders().
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from engine.detectors.multibagger import detect_multibagger_breakouts, get_multibagger_universe
from engine.auto_alert_engine import auto_alert_engine

IST = ZoneInfo("Asia/Kolkata")


def _generate_synthetic_stage2_compounder(
    days: int = 300, base_price: float = 100.0
) -> pd.DataFrame:
    """Generates synthetic price series modeling Stage 2 Markup & Minervini 8/8 template."""
    np.random.seed(42)
    # Strong upward trend over 300 days (100 -> 350)
    trend = np.linspace(base_price, base_price * 3.5, days)
    noise = np.random.normal(0, 1.5, days)
    closes = trend + noise

    highs = closes + np.random.uniform(0.5, 3.0, days)
    lows = closes - np.random.uniform(0.5, 3.0, days)
    opens = (highs + lows) / 2.0
    volumes = np.random.uniform(200000, 800000, days)

    dates = pd.date_range(end=datetime.now(IST), periods=days, freq="B")
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


def test_get_multibagger_universe():
    """Verify curated multibagger universe contains top institutional compounders."""
    u = get_multibagger_universe()
    assert len(u) >= 25
    assert "TRENT" in u
    assert "DIXON" in u
    assert "HAL" in u
    assert "BEL" in u
    assert "SOLARINDS" in u
    assert "TITAGARH" in u


def test_detect_multibagger_breakouts_synthetic():
    """Verify detector discovers Stage 2 superperformer from synthetic data."""
    df = _generate_synthetic_stage2_compounder(days=300, base_price=200.0)
    cache = {"TITAGARH": df}

    alerts = detect_multibagger_breakouts(
        universe=["TITAGARH"],
        df_cache=cache,
        min_conviction=60,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "TITAGARH"
    assert alert.time_horizon in ("MULTIBAGGER", "SWING_MID", "LONG_TERM")
    assert alert.eta_label in ("6–24 Months", "1–6 Months")
    assert alert.target_level > alert.ltp
    assert alert.stop_loss < alert.ltp
    assert alert.actionable_plan is not None
    assert "Ride multi-quarter earnings expansion" in alert.actionable_plan.get("profit_rule", "")

    # Invariant Rule 17: deterministic alert ID format
    assert alert.alert_id.startswith("aa-")
    assert "titagarh" in alert.alert_id
    assert "-2026" in alert.alert_id  # session date format YYYYMMDD


def test_auto_alert_engine_scan_multibagger_compounders(tmp_path, monkeypatch):
    """Verify AutoAlertEngine integrates scan_multibagger_compounders and records alerts with full test isolation."""
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    from unittest.mock import patch

    with patch("engine.detectors.multibagger.scan_multibagger_opportunity") as mock_scan:
        from analysis.multibagger import MultibaggerReport

        mock_scan.return_value = MultibaggerReport(
            symbol="SOLARINDS",
            ltp=10500.0,
            multibagger_score=88,
            category="STAGE_2_SUPERPERFORMER",
            trend_template_passed=8,
            trend_template_qualified=True,
            weinstein_stage="STAGE_2_MARKUP",
            vcp_detected=True,
            vcp_pivot_price=10400.0,
            sector="Capital Goods",
            sector_tailwind_score=85,
            forensic_safe=True,
            summary="Solar Industries is in powerful Stage 2 markup expansion.",
            best_horizon="MULTIBAGGER",
            long_term_ticket={
                "entry_price": 10500.0,
                "stop_loss": 9450.0,
                "target_1": 15750.0,
                "target_2": 21000.0,
                "target_runner": 31500.0,
                "risk_reward_ratio": "1:5.0",
                "trailing_stop_rule": "Ride multi-quarter earnings expansion. Trail below rising 50-SMA floor.",
            },
        )

        # Clean up any pre-existing alert for SOLARINDS to ensure test isolation
        old_alerts = [a for a in auto_alert_engine._alerts if a.symbol == "SOLARINDS"]
        auto_alert_engine._alerts = [
            a for a in auto_alert_engine._alerts if a.symbol != "SOLARINDS"
        ]
        try:
            fresh = auto_alert_engine.scan_multibagger_compounders(
                universe=["SOLARINDS"], top_n=5, min_conviction=70
            )
            assert len(fresh) >= 1
            found = next(a for a in fresh if a.symbol == "SOLARINDS")
            assert found.time_horizon == "MULTIBAGGER"
            assert found.eta_label == "6–24 Months"
            assert found.confidence == 88
            assert found.is_active is True
        finally:
            auto_alert_engine._alerts = [
                a for a in auto_alert_engine._alerts if a.symbol != "SOLARINDS"
            ] + old_alerts
