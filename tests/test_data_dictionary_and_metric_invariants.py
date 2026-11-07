"""
tests/test_data_dictionary_and_metric_invariants.py
===================================================
Automated Test Guardian for Institutional Data Dictionary and Metric Invariants.
Verifies the 4-Pillar Universal Metric Canonicalization Contract:
  1. Universal Metric Dictionary Canonicalization in AutoAlert.__post_init__
  2. First-Class Typed Properties on AutoAlert (vwap, effective_spot, effective_rvol, effective_atr, etc.)
  3. Upstream Quote Gateway VWAP Guarantee & Fallback Resolution
  4. Cross-Detector Canonical Metric Parity and Serialization Round-Trip Integrity
"""

from datetime import datetime
from config.constants import IST
from engine.alert_model import AutoAlert


def _make_alert(**kwargs) -> AutoAlert:
    defaults = {
        "alert_id": "test-alert-01",
        "alert_type": "INDEX_CALL_SETUP",
        "stage": "IGNITED",
        "symbol": "NSE:NIFTY50-INDEX",
        "exchange": "NSE",
        "direction": "BULLISH",
        "headline": "Test Institutional Alert",
        "summary": "Data dictionary invariant test alert",
        "ltp": 155.0,
        "trigger_level": 160.0,
        "target_level": 220.0,
        "stop_loss": 120.0,
        "environment": "TEST",
    }
    defaults.update(kwargs)
    return AutoAlert(**defaults)


class TestDataDictionaryAndMetricInvariants:
    """Test suite verifying canonical metric dictionary and typed properties on AutoAlert."""

    def test_vwap_canonicalization_from_spot_vwap(self):
        """Verify that an alert with 'spot_vwap' canonicalizes to 'vwap', 'underlying_vwap', and alert.vwap."""
        alert = _make_alert(
            alert_id="test-vwap-01",
            symbol="NSE:NIFTY50-INDEX",
            alert_type="INDEX_CALL_SETUP",
            direction="BULLISH",
            ltp=155.0,
            trigger_level=160.0,
            stop_loss=120.0,
            target_level=220.0,
            underlying_spot=24500.0,
            metrics={"spot_vwap": 24480.5, "rvol_10d": 2.5},
        )

        # Property checks
        assert alert.vwap == 24480.5
        assert alert.effective_spot == 24500.0
        assert alert.effective_rvol == 2.5

        # Dictionary canonicalization checks
        assert alert.metrics["vwap"] == 24480.5
        assert alert.metrics["spot_vwap"] == 24480.5
        assert alert.metrics["underlying_vwap"] == 24480.5
        assert alert.metrics["rvol"] == 2.5
        assert alert.metrics["rvol_10d"] == 2.5

        # Serialization checks
        d = alert.to_dict()
        assert d["vwap"] == 24480.5
        assert d["effective_spot"] == 24500.0
        assert d["effective_rvol"] == 2.5

    def test_vwap_canonicalization_from_atp(self):
        """Verify that an alert with 'atp' canonicalizes to 'vwap'."""
        alert = _make_alert(
            alert_id="test-vwap-02",
            symbol="NSE:RELIANCE",
            alert_type="OPENING_DRIVE",
            direction="BULLISH",
            ltp=1310.0,
            trigger_level=1315.0,
            stop_loss=1295.0,
            target_level=1340.0,
            metrics={"atp": 1308.75},
        )
        assert alert.vwap == 1308.75
        assert alert.metrics["vwap"] == 1308.75
        assert alert.effective_spot == 1310.0

    def test_spot_canonicalization_and_underlying_assignment(self):
        """Verify that underlying spot in metrics synchronizes self.underlying_spot and properties."""
        alert = _make_alert(
            alert_id="test-spot-01",
            symbol="NSE:BANKNIFTY",
            alert_type="OPTIONS_MOMENTUM",
            direction="BEARISH",
            ltp=340.0,
            trigger_level=350.0,
            stop_loss=280.0,
            target_level=460.0,
            metrics={"spot": 52150.0, "spot_vwap": 52200.0},
        )
        assert alert.effective_spot == 52150.0
        assert alert.underlying_spot == 52150.0
        assert alert.metrics["underlying_spot"] == 52150.0
        assert alert.metrics["underlying_ltp"] == 52150.0

    def test_rvol_and_atr_canonicalization(self):
        """Verify that rvol variants and atr variants canonicalize bidirectionally."""
        alert = _make_alert(
            alert_id="test-metrics-01",
            symbol="NSE:TCS",
            alert_type="SQUEEZE_BREAKOUT",
            direction="BULLISH",
            ltp=4120.0,
            trigger_level=4130.0,
            stop_loss=4080.0,
            target_level=4220.0,
            metrics={"relative_volume": "3.2x", "atr_14": "42.50"},
        )
        assert alert.effective_rvol == 3.2
        assert alert.effective_atr == 42.5
        assert alert.metrics["rvol"] == 3.2
        assert alert.metrics["rvol_10d"] == 3.2
        assert alert.metrics["atr"] == 42.5
        assert alert.metrics["atr_14"] == 42.5

    def test_day_extremes_canonicalization(self):
        """Verify that day/session high/low canonicalize properly."""
        alert = _make_alert(
            alert_id="test-extremes-01",
            symbol="NSE:INFY",
            alert_type="AFTERNOON_THRUST",
            direction="BULLISH",
            ltp=1850.0,
            trigger_level=1855.0,
            stop_loss=1830.0,
            target_level=1900.0,
            metrics={"high": 1860.0, "low": 1825.0},
        )
        assert alert.effective_day_high == 1860.0
        assert alert.effective_day_low == 1825.0
        assert alert.metrics["day_high"] == 1860.0
        assert alert.metrics["session_high"] == 1860.0
        assert alert.metrics["day_low"] == 1825.0
        assert alert.metrics["session_low"] == 1825.0

    def test_dual_horizon_stop_loss_separation_option_scale(self):
        """Verify that an option alert with tactical premium SL preserves scale separation."""
        alert = _make_alert(
            alert_id="test-sl-01",
            symbol="NSE:NIFTY50-INDEX",
            contract_symbol="NIFTY 24500 CE",
            strike=24500.0,
            option_type="CE",
            alert_type="OPTIONS_MOMENTUM",
            direction="BULLISH",
            ltp=165.0,
            trigger_level=170.0,
            stop_loss=130.0,
            target_level=230.0,
            underlying_spot=24520.0,
            structural_spot_sl=24450.0,
            metrics={"spot_vwap": 24500.0},
        )
        assert alert.effective_option_sl == 130.0
        assert alert.effective_spot_sl == 24450.0
        assert alert.tactical_sl == 130.0

    def test_dual_horizon_stop_loss_separation_spot_scale_guard(self):
        """
        Verify that an option alert where stop_loss was mistakenly supplied in spot scale
        (e.g., 24450.0) is segregated into effective_spot_sl and does NOT corrupt effective_option_sl.
        """
        alert = _make_alert(
            alert_id="test-sl-02",
            symbol="NSE:NIFTY50-INDEX",
            contract_symbol="NIFTY 24500 CE",
            strike=24500.0,
            option_type="CE",
            alert_type="OPTIONS_MOMENTUM",
            direction="BULLISH",
            ltp=165.0,
            trigger_level=170.0,
            stop_loss=24450.0,  # Spot scale!
            target_level=230.0,
            underlying_spot=24520.0,
            metrics={"spot_vwap": 24500.0},
        )
        assert alert.effective_spot_sl == 24450.0
        assert alert.effective_option_sl == 0.0  # Safeguarded!

    def test_serialization_and_deserialization_round_trip(self):
        """Verify that from_dict(alert.to_dict()) preserves canonical metrics and properties perfectly."""
        orig = _make_alert(
            alert_id="test-roundtrip-01",
            symbol="NSE:NIFTY50-INDEX",
            contract_symbol="NIFTY 24500 CE",
            strike=24500.0,
            option_type="CE",
            alert_type="INDEX_CALL_SETUP",
            direction="BULLISH",
            ltp=180.0,
            trigger_level=185.0,
            stop_loss=140.0,
            target_level=250.0,
            underlying_spot=24530.0,
            structural_spot_sl=24460.0,
            metrics={
                "spot_vwap": 24510.0,
                "rvol_10d": 2.8,
                "atr_5m": 28.0,
                "session_high": 24560.0,
                "session_low": 24470.0,
            },
        )

        d = orig.to_dict()
        restored = AutoAlert.from_dict(d)

        assert restored.alert_id == orig.alert_id
        assert restored.vwap == 24510.0
        assert restored.effective_spot == 24530.0
        assert restored.effective_rvol == 2.8
        assert restored.effective_atr == 28.0
        assert restored.effective_spot_sl == 24460.0
        assert restored.effective_option_sl == 140.0
        assert restored.effective_day_high == 24560.0
        assert restored.effective_day_low == 24470.0
        assert restored.metrics["vwap"] == 24510.0
        assert restored.metrics["spot_vwap"] == 24510.0

    def test_opening_drive_detector_canonical_metric_emission(self):
        """Verify detect_opening_drive emits alerts complying with the canonical metric contract."""
        import pandas as pd
        from engine.detectors.opening_drive import detect_opening_drive

        dates = pd.date_range("2026-10-30 09:15", periods=3, freq="5min", tz=IST)
        df_5m = pd.DataFrame(
            {
                "open": [1972.0, 1980.0, 1995.0],
                "high": [1985.0, 2005.0, 2012.0],
                "low": [1972.0, 1980.0, 1990.0],
                "close": [1982.0, 2000.0, 2008.0],
                "volume": [120000, 140000, 160000],
            },
            index=dates,
        )

        alert = detect_opening_drive(
            symbol="COFORGE",
            df_5m=df_5m,
            ltp=2008.0,
            vwap=2000.0,
            rvol=2.5,
            ref_time=datetime(2026, 10, 30, 9, 20, tzinfo=IST),
            prev_close=1962.0,
            prev_high=1975.0,
            prev_low=1940.0,
            ignore_time_gate=True,
        )

        assert alert is not None
        assert alert.vwap == 2000.0
        assert alert.effective_spot == 2008.0
        assert alert.effective_rvol == 2.5
        assert alert.metrics["vwap"] == 2000.0
        assert alert.metrics["spot_vwap"] == 2000.0

    def test_afternoon_thrust_detector_canonical_metric_emission(self):
        """Verify detect_afternoon_thrust emits alerts complying with the canonical metric contract."""
        import pandas as pd
        from engine.detectors.afternoon_thrust import detect_afternoon_thrust

        times = pd.date_range("2026-10-30 09:15", "2026-10-30 13:30", freq="5min", tz=IST)
        n = len(times)
        df_5m = pd.DataFrame(
            {
                "open": [25000.0 + (i * 0.5) for i in range(n)],
                "high": [25010.0 + (i * 0.5) for i in range(n)],
                "low": [24995.0 + (i * 0.5) for i in range(n)],
                "close": [25005.0 + (i * 0.5) for i in range(n)],
                "volume": [50000] * (n - 1) + [120000],
            },
            index=times,
        )
        ltp = float(df_5m["close"].iloc[-1])
        day_high = float(df_5m["high"].iloc[:-1].max())

        alert = detect_afternoon_thrust(
            symbol="NIFTY",
            df_5m=df_5m,
            ltp=ltp,
            vwap=ltp - 20.0,
            rvol=2.2,
            day_high=day_high,
            day_low=24980.0,
            ref_time=datetime(2026, 10, 30, 13, 30, tzinfo=IST),
            ignore_time_gate=True,
        )

        assert alert is not None
        assert alert.vwap == ltp - 20.0
        assert alert.effective_spot == ltp
        assert alert.effective_rvol >= 2.2
        assert alert.metrics["vwap"] == ltp - 20.0
        assert alert.metrics["spot_vwap"] == ltp - 20.0

    def test_option_resolver_greek_delta_atm_selection(self):
        """Verify resolve_option_contract dynamically selects the 50-Delta contract for ATM."""
        from brokers.base import OptionsContract
        from engine.option_resolver import resolve_option_contract

        c1 = OptionsContract(
            symbol="NIFTY26NOV24500CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24500.0,
            option_type="CE",
            last_price=160.0,
            oi=50000,
            oi_change=1000,
            volume=100000,
            delta=0.51,
            iv=14.2,
            lot_size=25,
            exchange="NFO",
        )
        c2 = OptionsContract(
            symbol="NIFTY26NOV24550CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24550.0,
            option_type="CE",
            last_price=130.0,
            oi=40000,
            oi_change=800,
            volume=80000,
            delta=0.43,
            iv=14.0,
            lot_size=25,
            exchange="NFO",
        )
        c3 = OptionsContract(
            symbol="NIFTY26NOV24600CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24600.0,
            option_type="CE",
            last_price=105.0,
            oi=60000,
            oi_change=1500,
            volume=120000,
            delta=0.35,
            iv=14.1,
            lot_size=25,
            exchange="NFO",
        )

        res = resolve_option_contract(
            "NIFTY",
            spot=24520.0,
            direction="BULLISH",
            underlying_sl=24470.0,
            contracts_override=[c1, c2, c3],
        )
        assert res is not None
        assert res.strike == 24500.0
        assert res.delta == 0.51
        # Spot risk = 50.0 pts * 0.51 delta = 25.5 pts -> sl_premium = 160.0 - 25.5 = 134.5
        assert res.sl_premium == 134.5

    def test_option_resolver_greek_delta_high_gamma_selection(self):
        """Verify resolve_option_contract selects ~0.35 Delta contract for HIGH_GAMMA_ASYMMETRY."""
        from brokers.base import OptionsContract
        from engine.option_resolver import resolve_option_contract

        c1 = OptionsContract(
            symbol="NIFTY26NOV24500CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24500.0,
            option_type="CE",
            last_price=160.0,
            oi=50000,
            oi_change=1000,
            volume=100000,
            delta=0.51,
            iv=14.2,
            lot_size=25,
            exchange="NFO",
        )
        c2 = OptionsContract(
            symbol="NIFTY26NOV24550CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24550.0,
            option_type="CE",
            last_price=130.0,
            oi=40000,
            oi_change=800,
            volume=80000,
            delta=0.43,
            iv=14.0,
            lot_size=25,
            exchange="NFO",
        )
        c3 = OptionsContract(
            symbol="NIFTY26NOV24600CE",
            underlying="NIFTY",
            expiry="2026-11-26",
            strike=24600.0,
            option_type="CE",
            last_price=105.0,
            oi=60000,
            oi_change=1500,
            volume=120000,
            delta=0.35,
            iv=14.1,
            lot_size=25,
            exchange="NFO",
        )

        res_gamma = resolve_option_contract(
            "NIFTY",
            spot=24520.0,
            direction="BULLISH",
            strike_tier="HIGH_GAMMA_ASYMMETRY",
            contracts_override=[c1, c2, c3],
        )
        assert res_gamma is not None
        assert res_gamma.strike == 24600.0
        assert res_gamma.delta == 0.35
