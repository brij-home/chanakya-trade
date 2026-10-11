"""
tests/test_commodity_crypto_enhancements.py
───────────────────────────────────────────
Institutional test suite for Commodities and Crypto Signal Quality Enhancements:
  1. Crypto SMC: Retest volume suppression (blocks dead overnight chop RVOL < 0.85).
  2. Crypto SMC: Taker CVD absorption allows high-quality retests with confluence bonus.
  3. Deribit Options Gravity: Isolated prompt DTE <= 3.5 and negative gamma expansion veto.
  4. Commodity Macro Transmission: Bullion longs vetoed by macro headwind (DXY/Yields surge).
  5. Commodity Macro Transmission: Silver outperformance boost during GSR breakdown.
  6. Quality Gate: Low-liquidity chop vetoed on dead volume drift (RVOL < 0.70x).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.alert_model import AutoAlert
from engine.detectors.crypto import detect_single_crypto_symbol
from engine.detectors.commodity import detect_commodity_breakouts
from engine.quality_gate import evaluate_institutional_quality_gate
from market.commodity_macro import CommodityMacroSnapshot, BullionTransmission, EnergyTransmission

IST = timezone(timedelta(hours=5, minutes=30))


def _make_sample_crypto_klines(
    base_price: float = 85000.0, n_bars: int = 60, volume: float = 1000.0
) -> pd.DataFrame:
    """Generate synthetic klines for crypto structure analysis."""
    dates = pd.date_range("2026-10-10 10:00", periods=n_bars, freq="15min")
    df = pd.DataFrame(
        {
            "open": [base_price + (i % 5) * 20 for i in range(n_bars)],
            "high": [base_price + (i % 5) * 20 + 50 for i in range(n_bars)],
            "low": [base_price + (i % 5) * 20 - 40 for i in range(n_bars)],
            "close": [base_price + (i % 5) * 20 + 10 for i in range(n_bars)],
            "volume": [volume for _ in range(n_bars)],
        },
        index=dates,
    )
    df["date"] = df.index
    return df


# ── 1. Crypto SMC Retest Volume Floor & CVD Absorption ────────────────────────


def test_crypto_smc_retest_dead_volume_suppression():
    """Verify that an SMC retest on dead volume (e.g. RVOL 0.10x) is rejected."""
    df = _make_sample_crypto_klines(85000.0, 60, volume=1000.0)
    df.loc[df.index[-1], "volume"] = 50.0  # Dead volume (RVOL ~ 0.05x)

    mock_quote = MagicMock()
    mock_quote.last_price = 85050.0
    mock_quote.change_pct = 0.5

    mock_smc = MagicMock()
    mock_smc.regime = "BULLISH"
    mock_smc.choch_detected = False
    mock_smc.fair_value_gaps = []
    mock_smc.last_swing_high = 86000.0
    mock_smc.last_swing_low = 84500.0
    mock_smc.active_supply_zones = []

    mock_ob = MagicMock()
    mock_ob.bottom = 84900.0
    mock_ob.top = 85100.0
    mock_ob.volume_ratio = 0.10
    mock_ob.has_fvg_confluence = False
    mock_ob.ote_price = None
    mock_smc.active_demand_zones = [mock_ob]

    with (
        patch("market.crypto_stream.crypto_stream.get_quote", return_value=mock_quote),
        patch("market.crypto_stream.crypto_stream.get_klines", return_value=df),
        patch("analysis.market_structure.analyze_market_structure", return_value=mock_smc),
        patch(
            "market.crypto_stream.crypto_stream.get_squeeze_metrics",
            return_value={"squeeze_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_order_flow_metrics",
            return_value={"absorption_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_liquidation_cascade_metrics",
            return_value={"cascade_detected": False},
        ),
        patch(
            "market.crypto_stream.crypto_stream.fetch_futures_metrics",
            return_value={"basis_annualized_pct": 0.0},
        ),
        patch(
            "market.crypto_options.get_crypto_options_summary", return_value={"status": "NO_DATA"}
        ),
    ):
        alerts = detect_single_crypto_symbol("BTCUSDT")
        smc_alerts = [a for a in alerts if a.alert_type == "CRYPTO_MOMENTUM"]
        assert len(smc_alerts) == 0


def test_crypto_smc_retest_cvd_absorption_allowed():
    """Verify that an SMC retest with moderate volume fires when confirmed CVD absorption is present."""
    df = _make_sample_crypto_klines(85000.0, 60, volume=1000.0)
    df.loc[df.index[-1], "volume"] = 700.0  # RVOL ~ 0.70x (below 0.85x, but >= 0.60x)

    mock_quote = MagicMock()
    mock_quote.last_price = 85050.0
    mock_quote.change_pct = 0.8

    mock_smc = MagicMock()
    mock_smc.regime = "BULLISH"
    mock_smc.choch_detected = False
    mock_smc.fair_value_gaps = []
    mock_smc.last_swing_high = 86500.0
    mock_smc.last_swing_low = 84500.0
    mock_smc.active_supply_zones = []

    mock_ob = MagicMock()
    mock_ob.bottom = 84900.0
    mock_ob.top = 85100.0
    mock_ob.volume_ratio = 0.70
    mock_ob.has_fvg_confluence = True
    mock_ob.ote_price = None
    mock_smc.active_demand_zones = [mock_ob]

    mock_cvd = {
        "is_bullish_absorption": True,
        "is_bearish_exhaustion": False,
        "current_cvd": 1500.0,
        "delta_source": "REAL_TAKER_DELTA",
    }

    with (
        patch("market.crypto_stream.crypto_stream.get_quote", return_value=mock_quote),
        patch("market.crypto_stream.crypto_stream.get_klines", return_value=df),
        patch("analysis.market_structure.analyze_market_structure", return_value=mock_smc),
        patch(
            "engine.detectors.order_flow.compute_order_flow_cvd_divergence", return_value=mock_cvd
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_squeeze_metrics",
            return_value={"squeeze_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_order_flow_metrics",
            return_value={"absorption_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_liquidation_cascade_metrics",
            return_value={"cascade_detected": False},
        ),
        patch(
            "market.crypto_stream.crypto_stream.fetch_futures_metrics",
            return_value={"basis_annualized_pct": 0.0},
        ),
        patch(
            "market.crypto_options.get_crypto_options_summary", return_value={"status": "NO_DATA"}
        ),
    ):
        alerts = detect_single_crypto_symbol("BTCUSDT")
        smc_alerts = [a for a in alerts if a.alert_type == "CRYPTO_MOMENTUM"]
        assert len(smc_alerts) == 1
        alert = smc_alerts[0]
        assert alert.direction == "BULLISH"
        assert "Taker CVD Absorption Divergence" in alert.actionable_plan["setup_confluence"]


# ── 2. Deribit Options Gravity Gating (Prompt DTE & Gamma Regime) ────────────


def test_deribit_options_gravity_negative_gamma_veto():
    """Verify that options gravity pinning is vetoed when dealers are in negative gamma expansion."""
    df = _make_sample_crypto_klines(85000.0, 60, volume=1000.0)

    mock_quote = MagicMock()
    mock_quote.last_price = 85000.0
    mock_quote.change_pct = -1.0

    mock_opt_negative_gamma = {
        "status": "ONLINE",
        "currency": "BTC",
        "underlying_spot": 85000.0,
        "max_pain": 90000.0,
        "max_pain_distance_pct": 5.88,
        "gamma_regime": "NEGATIVE_GAMMA_EXPANSION",  # Accelerative regime
        "prompt_dte_days": 1.5,
        "net_gex_usd": -15000000.0,
        "pcr_open_interest": 0.95,
        "gex_flip_strike": 88000.0,
    }

    with (
        patch("market.crypto_stream.crypto_stream.get_quote", return_value=mock_quote),
        patch("market.crypto_stream.crypto_stream.get_klines", return_value=df),
        patch(
            "market.crypto_options.get_crypto_options_summary", return_value=mock_opt_negative_gamma
        ),
        patch("analysis.market_structure.analyze_market_structure", side_effect=Exception("skip")),
        patch(
            "market.crypto_stream.crypto_stream.get_squeeze_metrics",
            return_value={"squeeze_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_order_flow_metrics",
            return_value={"absorption_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_liquidation_cascade_metrics",
            return_value={"cascade_detected": False},
        ),
        patch(
            "market.crypto_stream.crypto_stream.fetch_futures_metrics",
            return_value={"basis_annualized_pct": 0.0},
        ),
    ):
        alerts = detect_single_crypto_symbol("BTCUSDT")
        grav_alerts = [
            a
            for a in alerts
            if a.alert_type == "CRYPTO_VOLATILITY" and "options-gravity" in a.alert_id
        ]
        assert len(grav_alerts) == 0


def test_deribit_options_gravity_far_dte_veto():
    """Verify that options gravity is vetoed when prompt DTE > 3.5 days (pinning too weak)."""
    df = _make_sample_crypto_klines(85000.0, 60, volume=1000.0)

    mock_quote = MagicMock()
    mock_quote.last_price = 85000.0
    mock_quote.change_pct = -1.0

    mock_opt_far_dte = {
        "status": "ONLINE",
        "currency": "BTC",
        "underlying_spot": 85000.0,
        "max_pain": 90000.0,
        "max_pain_distance_pct": 5.88,
        "gamma_regime": "POSITIVE_GAMMA_PINNING",
        "prompt_dte_days": 14.0,  # 14 days away -> no pinning
        "net_gex_usd": 25000000.0,
        "pcr_open_interest": 0.95,
        "gex_flip_strike": 83000.0,
    }

    with (
        patch("market.crypto_stream.crypto_stream.get_quote", return_value=mock_quote),
        patch("market.crypto_stream.crypto_stream.get_klines", return_value=df),
        patch("market.crypto_options.get_crypto_options_summary", return_value=mock_opt_far_dte),
        patch("analysis.market_structure.analyze_market_structure", side_effect=Exception("skip")),
        patch(
            "market.crypto_stream.crypto_stream.get_squeeze_metrics",
            return_value={"squeeze_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_order_flow_metrics",
            return_value={"absorption_signal": "NONE"},
        ),
        patch(
            "market.crypto_stream.crypto_stream.get_liquidation_cascade_metrics",
            return_value={"cascade_detected": False},
        ),
        patch(
            "market.crypto_stream.crypto_stream.fetch_futures_metrics",
            return_value={"basis_annualized_pct": 0.0},
        ),
    ):
        alerts = detect_single_crypto_symbol("BTCUSDT")
        grav_alerts = [
            a
            for a in alerts
            if a.alert_type == "CRYPTO_VOLATILITY" and "options-gravity" in a.alert_id
        ]
        assert len(grav_alerts) == 0


# ── 3. Commodity Intermarket Macro Transmission ───────────────────────────────


def test_commodity_bullion_macro_headwind_veto():
    """Verify that Gold longs are vetoed when DXY or US 10Y yields surge (STRONG_HEADWIND)."""
    mock_quote = MagicMock()
    mock_quote.last_price = 78000.0
    mock_quote.change_pct = 1.2
    mock_quote.open = 77200.0
    mock_quote.high = 78100.0
    mock_quote.low = 77150.0
    mock_quote.volume = 1200
    mock_quote.vwap = 77500.0
    mock_quote.force_live_eval = True

    dates = pd.date_range("2026-10-10 17:00", periods=30, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [77000.0 + i * 30 for i in range(30)],
            "high": [77050.0 + i * 30 for i in range(30)],
            "low": [76980.0 + i * 30 for i in range(30)],
            "close": [77040.0 + i * 30 for i in range(30)],
            "volume": [100.0 for _ in range(30)],
        },
        index=dates,
    )

    mock_macro = CommodityMacroSnapshot(
        bullion=BullionTransmission(
            dxy_ltp=105.2,
            dxy_change_pct=0.45,
            gold_silver_ratio=84.0,
            gsr_change_pct=0.20,
            us_10y_yield=4.35,
            us_10y_change_bps=6.5,
            bullion_bias="STRONG_HEADWIND",
            silver_outperformance_favored=False,
            notes=["DXY surging & 10Y yield spiking"],
        ),
        energy=EnergyTransmission(78.0, 0.0, 74.0, 0.0, 4.0, "NEUTRAL", "CLEAR", []),
        doctor_copper_gold_ratio=1.65,
        status="ONLINE",
        as_of_ts=1700000000.0,
    )

    with (
        patch("engine.quality_gate.is_mcx_golden_hours_window", return_value=True),
        patch("market.commodity_macro.get_commodity_macro_snapshot", return_value=mock_macro),
        patch("market.quotes.get_quote", return_value={"MCX:GOLD": mock_quote}),
        patch("market.history.get_ohlcv", return_value=df_5m),
        patch("analysis.market_structure.analyze_market_structure", return_value=None),
    ):
        alerts = detect_commodity_breakouts(
            universe=["GOLD"],
            quotes_map={"MCX:GOLD": mock_quote},
            ohlcv_map={"GOLD": df_5m},
        )
        gold_alerts = [a for a in alerts if a.symbol == "GOLD"]
        assert len(gold_alerts) == 0


def test_commodity_silver_gsr_breakdown_boost():
    """Verify that Silver breakouts receive an outperformance boost when GSR is breaking down."""
    mock_quote = MagicMock()
    mock_quote.last_price = 90225.0
    mock_quote.change_pct = 1.8
    mock_quote.open = 89800.0
    mock_quote.high = 90230.0
    mock_quote.low = 89700.0
    mock_quote.volume = 5000
    mock_quote.vwap = 90050.0
    mock_quote.force_live_eval = True

    dates = pd.date_range("2026-10-10 18:00", periods=30, freq="5min")
    prices = [90000.0 + (i % 5) * 40 + (i // 5) * 20 for i in range(30)]
    df_5m = pd.DataFrame(
        {
            "open": [p - 10 for p in prices],
            "high": [p + 25 for p in prices],
            "low": [p - 20 for p in prices],
            "close": prices,
            "volume": [300.0 for _ in range(30)],
        },
        index=dates,
    )
    df_5m.loc[df_5m.index[-1], "open"] = 90180.0
    df_5m.loc[df_5m.index[-1], "low"] = 90170.0
    df_5m.loc[df_5m.index[-1], "close"] = 90225.0
    df_5m.loc[df_5m.index[-1], "high"] = 90230.0
    df_5m.loc[df_5m.index[-1], "volume"] = 900.0  # RVOL > 2.0x

    mock_macro = CommodityMacroSnapshot(
        bullion=BullionTransmission(
            dxy_ltp=103.5,
            dxy_change_pct=-0.35,
            gold_silver_ratio=82.0,
            gsr_change_pct=-0.85,  # GSR breaking down
            us_10y_yield=4.15,
            us_10y_change_bps=-3.2,
            bullion_bias="STRONG_TAILWIND",
            silver_outperformance_favored=True,
            notes=["GSR declining — Silver leading"],
        ),
        energy=EnergyTransmission(78.0, 0.0, 74.0, 0.0, 4.0, "NEUTRAL", "CLEAR", []),
        doctor_copper_gold_ratio=1.65,
        status="ONLINE",
        as_of_ts=1700000000.0,
    )

    mock_adaptive = MagicMock()
    mock_adaptive.tiger.allow_routine_breakouts = True
    mock_adaptive.tiger.mandate = "MOMENTUM_EXPANSION"
    mock_adaptive.sniper = None
    mock_adaptive.eagle.overall_environment = "OPTIMAL_TREND_EXPANSION"

    with (
        patch("engine.quality_gate.is_mcx_golden_hours_window", return_value=True),
        patch("market.commodity_macro.get_commodity_macro_snapshot", return_value=mock_macro),
        patch("market.quotes.get_quote", return_value={"MCX:SILVER": mock_quote}),
        patch("market.history.get_ohlcv", return_value=df_5m),
        patch("analysis.market_structure.analyze_market_structure", return_value=None),
        patch(
            "engine.commodity_adaptive_regime.evaluate_commodity_adaptive_regime",
            return_value=mock_adaptive,
        ),
    ):
        alerts = detect_commodity_breakouts(
            universe=["SILVER"],
            quotes_map={"MCX:SILVER": mock_quote},
            ohlcv_map={"SILVER": df_5m},
        )
        assert len(alerts) >= 1
        silver_alert = alerts[0]
        assert silver_alert.symbol == "SILVER"
        assert (
            "Silver Outperformance (Falling GSR)"
            in silver_alert.actionable_plan["setup_confluence"]
        )


# ── 4. Quality Gate Low-Liquidity Chop Floor ──────────────────────────────────


def test_quality_gate_dead_volume_chop_veto():
    """Verify that evaluate_institutional_quality_gate vetoes crypto/commodity alerts with RVOL < 0.70x in dead chop."""
    alert = AutoAlert(
        alert_id="test-dead-vol-crypto",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="BNBUSDT",
        exchange="CRYPTO",
        direction="BULLISH",
        headline="Crypto Dead Volume Retest",
        summary="Testing dead volume chop veto",
        ltp=600.0,
        trigger_level=600.0,
        target_level=630.0,
        stop_loss=590.0,
        confidence=80,
        metrics={"rvol": 0.25},
        actionable_plan={"action": "BUY_SPOT", "rvol": 0.25, "segment": "CRYPTO"},
        is_live=True,
        environment="LIVE",
    )

    # Call with is_test overridden or ref_dt passed
    with patch.dict("os.environ", {"CHANAKYA_TESTING": "0"}, clear=False):
        verdict = evaluate_institutional_quality_gate(
            alert, ref_dt=datetime(2026, 10, 10, 14, 0, tzinfo=IST)
        )
        assert verdict.is_vetoed is True
        assert "Dead Liquidity Chop" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"
