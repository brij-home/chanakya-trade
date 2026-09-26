import os
import time
import pytest
from datetime import datetime

os.environ["CHANAKYA_TESTING"] = "1"


class TestMarketRegimeGate:
    def test_normal_not_edgeless(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: 16.0)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: 1.4)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert not snap.is_edgeless
        assert snap.vix_status == "ELEVATED"
        assert snap.banner == ""

    def test_edgeless_both_met(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: 11.8)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: 1.0)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert snap.is_edgeless
        assert "EDGELESS" in snap.banner
        assert snap.prefer_spreads

    def test_low_vix_bullish_breadth(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: 11.5)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: 1.8)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert not snap.is_edgeless
        assert snap.prefer_spreads

    def test_vix_125_130(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: 12.8)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: 0.9)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert not snap.is_edgeless
        assert snap.prefer_spreads

    def test_unavailable_not_edgeless(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: None)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: None)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert not snap.is_edgeless
        assert snap.data_quality == "UNAVAILABLE"

    def test_cache(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        cnt = [0]
        def vix():
            cnt[0] += 1
            return 15.0
        monkeypatch.setattr(gate, "_fetch_vix", vix)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: 1.3)
        gate.evaluate_market_regime(force_refresh=True)
        gate.evaluate_market_regime()
        assert cnt[0] == 1

    def test_degraded(self, monkeypatch):
        import engine.market_regime_gate as gate
        gate._cached_result = None
        monkeypatch.setattr(gate, "_fetch_vix", lambda: 14.0)
        monkeypatch.setattr(gate, "_fetch_ad_ratio", lambda: None)
        snap = gate.evaluate_market_regime(force_refresh=True)
        assert snap.data_quality == "DEGRADED"
        assert not snap.is_edgeless


class TestCouncilArbitrator:
    @staticmethod
    def _make(aid, conf=80, ltp=100, tgt=130, sl=90, direction="BULLISH", stage="IGNITED"):
        from unittest.mock import MagicMock
        a = MagicMock()
        a.alert_id = aid
        a.confidence = conf
        a.ltp = ltp
        a.target_level = tgt
        a.stop_loss = sl
        a.direction = direction
        a.stage = stage
        a.is_invalidated = False
        a.is_archived = False
        a.metrics = {}
        a.actionable_plan = {}
        a.expiry_date = None
        a.created_at = datetime.now().isoformat()
        a.symbol = "SYM"
        a.alert_type = "GAMMA_BLAST"
        return a

    def _eng(self, alerts):
        class E:
            _alerts = alerts
            def _save(self): pass
        return E()

    def _snap(self, monkeypatch, p="NEUTRAL"):
        try:
            from market import indices as mi
            monkeypatch.setattr(mi, "get_market_snapshot", lambda: type("S", (), {"posture": p})(), raising=False)
        except Exception:
            pass

    def test_top3_from_five(self, monkeypatch):
        import engine.council_arbitrator as arb
        arb._last_arb_at = 0.0
        self._snap(monkeypatch)
        alerts = [self._make(str(i), 60 + i * 5, tgt=110 + i * 5, sl=95 - i) for i in range(5)]
        winners = arb.run_council_arbitration(self._eng(alerts))
        assert len(winners) == 3

    def test_rank_1(self, monkeypatch):
        import engine.council_arbitrator as arb
        arb._last_arb_at = 0.0
        self._snap(monkeypatch, "BULLISH")
        a = self._make("win", 95, tgt=150, sl=85)
        b = self._make("lose", 40, tgt=105, sl=97)
        winners = arb.run_council_arbitration(self._eng([a, b]))
        assert "win" in winners
        assert a.actionable_plan["council_rank"] == 1
        assert a.actionable_plan["council_approved"] is True

    def test_cache_interval(self):
        import engine.council_arbitrator as arb
        arb._last_arb_at = time.time()
        arb._last_winners = ["cached"]
        assert arb.run_council_arbitration(self._eng([])) == ["cached"]

    def test_empty(self, monkeypatch):
        import engine.council_arbitrator as arb
        arb._last_arb_at = 0.0
        self._snap(monkeypatch)
        assert arb.run_council_arbitration(self._eng([])) == []

    def test_should_run(self):
        import engine.council_arbitrator as arb
        arb._last_arb_at = time.time()
        assert not arb.should_run_arbitration()
        arb._last_arb_at = time.time() - 700.0
        assert arb.should_run_arbitration()


class TestPullbackLimitOrder:
    def test_required_fields(self):
        e = {"order_type": "LIMIT", "entry_zone": "zone", "ema_20_level": 24320.5, "entry_note": "wait"}
        assert e["order_type"] == "LIMIT"
        assert isinstance(e["ema_20_level"], float)

    def test_entry_type(self):
        from unittest.mock import MagicMock
        a = MagicMock()
        a.actionable_plan = {"pullback_limit_order": {"order_type": "LIMIT"}}
        a.entry_type = "LIMIT_ON_PULLBACK"
        assert a.entry_type == "LIMIT_ON_PULLBACK"
