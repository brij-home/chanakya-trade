"""Tests for analysis/options.py — Greeks, IV rank, payoff."""

import pytest

from analysis.options import iv_rank, payoff, PayoffLeg


class TestIVRank:
    def test_at_low(self):
        """Current IV at historical low → rank 0."""
        assert iv_rank(10.0, [10.0, 20.0, 30.0, 40.0]) == pytest.approx(0.0)

    def test_at_high(self):
        """Current IV at historical high → rank 100."""
        assert iv_rank(40.0, [10.0, 20.0, 30.0, 40.0]) == pytest.approx(100.0)

    def test_at_midpoint(self):
        """Current IV at midpoint → rank 50."""
        assert iv_rank(25.0, [10.0, 40.0]) == pytest.approx(50.0)

    def test_empty_history(self):
        """No historical data → default 50."""
        assert iv_rank(20.0, []) == pytest.approx(50.0)

    def test_flat_history(self):
        """All same IVs → default 50."""
        assert iv_rank(20.0, [20.0, 20.0, 20.0]) == pytest.approx(50.0)


class TestPayoff:
    def test_single_long_call(self):
        """Long call: max loss = premium, profit unlimited above breakeven."""
        legs = [
            PayoffLeg(
                option_type="CE",
                transaction="BUY",
                strike=100.0,
                premium=5.0,
                lot_size=1,
                lots=1,
            )
        ]
        result = payoff(legs, spot_range=(80, 120), steps=40)
        assert result.max_loss == pytest.approx(-5.0, abs=0.5)
        assert result.max_profit > 0
        # Breakeven should be at strike + premium = 105
        assert any(abs(be - 105.0) < 2.0 for be in result.breakevens)

    def test_single_long_put(self):
        """Long put: max loss = premium."""
        legs = [
            PayoffLeg(
                option_type="PE",
                transaction="BUY",
                strike=100.0,
                premium=5.0,
                lot_size=1,
                lots=1,
            )
        ]
        result = payoff(legs, spot_range=(80, 120), steps=40)
        assert result.max_loss == pytest.approx(-5.0, abs=0.5)

    def test_iron_condor_four_legs(self):
        """Iron condor should have defined max profit and max loss."""
        legs = [
            PayoffLeg("PE", "SELL", 90.0, 3.0, 1, 1),  # sell put
            PayoffLeg("PE", "BUY", 85.0, 1.5, 1, 1),  # buy put (protection)
            PayoffLeg("CE", "SELL", 110.0, 3.0, 1, 1),  # sell call
            PayoffLeg("CE", "BUY", 115.0, 1.5, 1, 1),  # buy call (protection)
        ]
        result = payoff(legs, spot_range=(80, 120), steps=40)
        # Max profit = net premium collected = (3-1.5) + (3-1.5) = 3.0
        assert result.max_profit > 0
        # Max loss should be bounded (not infinite)
        assert result.max_loss > -10.0


class TestPCRAndMaxPain:
    def test_empty_chain_returns_none(self, monkeypatch):
        """When no options contracts exist (non-F&O stock), get_pcr and get_max_pain must return None."""
        import market.options as mo

        monkeypatch.setattr(mo, "get_options_chain", lambda *args, **kwargs: [])
        assert mo.get_pcr("KAYNES") is None
        assert mo.get_max_pain("KAYNES") is None

    def test_valid_chain_returns_values(self, monkeypatch):
        """When options contracts exist, get_pcr and get_max_pain compute accurate values."""
        import market.options as mo

        mock_chain = [
            mo.OptionsContract(
                symbol="NIFTY24DEC24000CE",
                underlying="NIFTY",
                expiry="2024-12-26",
                strike=24000.0,
                option_type="CE",
                last_price=100.0,
                oi=1000,
                oi_change=100,
                volume=5000,
            ),
            mo.OptionsContract(
                symbol="NIFTY24DEC24000PE",
                underlying="NIFTY",
                expiry="2024-12-26",
                strike=24000.0,
                option_type="PE",
                last_price=50.0,
                oi=1200,
                oi_change=120,
                volume=6000,
            ),
        ]
        monkeypatch.setattr(mo, "get_options_chain", lambda *args, **kwargs: mock_chain)
        pcr = mo.get_pcr("NIFTY")
        assert pcr == 1.2
        max_pain = mo.get_max_pain("NIFTY")
        assert max_pain == 24000.0

    def test_options_analyst_reports_unavailable_with_fno_awareness(self):
        """OptionsAnalyst should report UNAVAILABLE with 0 score, recognizing F&O vs Cash Equity status."""
        from agent.tools import build_registry
        from agent.multi_agent import OptionsAnalyst

        reg = build_registry()
        # 1. F&O stock without active live feed (e.g. KAYNES)
        report_fno = OptionsAnalyst(reg).analyze("KAYNES")
        assert report_fno.verdict == "UNAVAILABLE"
        assert report_fno.score == 0
        assert report_fno.confidence == 0
        assert any("F&O Stock" in pt for pt in report_fno.key_points)
        assert report_fno.data.get("is_fno") is True
        assert report_fno.data.get("options_available") is False

        # 2. Pure cash equity stock (not in F&O)
        report_cash = OptionsAnalyst(reg).analyze("MRPL")
        assert report_cash.verdict == "UNAVAILABLE"
        assert report_cash.score == 0
        assert report_cash.confidence == 0
        assert any("Cash Equity Stock" in pt for pt in report_cash.key_points)
        assert report_cash.data.get("is_fno") is False
        assert report_cash.data.get("options_available") is False

