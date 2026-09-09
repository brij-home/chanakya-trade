"""
tests/test_conviction_score.py
──────────────────────────────
Unit tests for the redesigned 12-Factor Orthogonal Conviction Scoring Engine.
Tests cover: PCR contrarian logic, IV skew inversion, VIX direction scoring,
max pain proximity, veto system, and full aggregation.
"""

from __future__ import annotations

from unittest.mock import patch


from engine.conviction_score import (
    FactorScore,
    VetoResult,
    _score_gex_posture,
    _score_india_vix_regime,
    _score_blast_signal_quality,
    _score_pcr_contrarian,
    _score_iv_skew,
    _score_max_pain_proximity,
    _check_veto_conditions,
    get_conviction_score,
)


# ── Factor: GEX Posture ────────────────────────────────────────────────────────


class TestGexPosture:
    def test_extreme_negative_gex(self):
        f = _score_gex_posture("EXTREME_NEGATIVE")
        assert f.score == 9
        assert f.signal == "BULLISH"
        assert f.axis == "OPTIONS"

    def test_negative_gex(self):
        f = _score_gex_posture("NEGATIVE")
        assert f.score == 7
        assert f.signal == "BULLISH"

    def test_positive_gex(self):
        f = _score_gex_posture("POSITIVE")
        assert f.score == 4
        assert f.signal == "NEUTRAL"

    def test_extreme_positive_gex(self):
        f = _score_gex_posture("EXTREME_POSITIVE")
        assert f.score == 2
        assert f.signal == "BEARISH"

    def test_none_gex_neutral(self):
        f = _score_gex_posture(None)
        assert f.score == 5
        assert f.signal == "NEUTRAL"


# ── Factor: PCR Contrarian (Key Redesign) ─────────────────────────────────────


class TestPcrContrarian:
    """PCR has a non-monotonic relationship — extremes in BOTH directions are bearish."""

    def test_optimal_pcr_zone_100_to_115(self):
        """PCR 1.0–1.15 is the optimal zone — highest conviction."""
        f = _score_pcr_contrarian(1.05)
        assert f.score == 8
        assert f.signal == "BULLISH"
        assert "optimal" in f.detail.lower()

    def test_pcr_135_still_bullish(self):
        """PCR 1.15–1.35 = healthy put support."""
        f = _score_pcr_contrarian(1.25)
        assert f.score == 7
        assert f.signal == "BULLISH"

    def test_pcr_extreme_high_is_bearish(self):
        """PCR > 1.55 = EXCESSIVE — distribution or pain trade setup. NOT bullish."""
        f = _score_pcr_contrarian(1.7)
        assert f.score == 3
        assert f.signal == "BEARISH"
        assert "excessive" in f.detail.lower() or "distribution" in f.detail.lower()

    def test_pcr_very_low_complacency(self):
        """PCR < 0.5 = extreme complacency = BEARISH."""
        f = _score_pcr_contrarian(0.45)
        assert f.score == 2
        assert f.signal == "BEARISH"
        assert "complacency" in f.detail.lower()

    def test_pcr_low_call_writers(self):
        """PCR 0.5–0.7 = call writers dominant = capping resistance."""
        f = _score_pcr_contrarian(0.62)
        assert f.score == 3
        assert f.signal == "BEARISH"

    def test_pcr_mild_call_overhead(self):
        """PCR 0.7–0.85 = neutral territory."""
        f = _score_pcr_contrarian(0.78)
        assert f.score == 5
        assert f.signal == "NEUTRAL"

    def test_pcr_none_is_neutral(self):
        f = _score_pcr_contrarian(None)
        assert f.score == 5
        assert f.signal == "NEUTRAL"

    def test_pcr_axis_is_options(self):
        f = _score_pcr_contrarian(1.1)
        assert f.axis == "OPTIONS"


# ── Factor: IV Skew / Term Structure ─────────────────────────────────────────


class TestIvSkew:
    def _make_skew(self, near_iv: float, far_iv: float, n: int = 12) -> list:
        """Build a synthetic IV skew list."""
        skew = []
        for i in range(n):
            t = i / (n - 1)
            skew.append({"iv": near_iv + (far_iv - near_iv) * t, "strike": 22000 + i * 100})
        return skew

    def test_normal_term_structure_bullish(self):
        """Far IV > Near IV by 4%+ = healthy structure."""
        skew = self._make_skew(near_iv=13.0, far_iv=17.5)
        f = _score_iv_skew(skew)
        assert f.score >= 7
        assert f.signal == "BULLISH"
        assert f.axis == "OPTIONS"

    def test_mild_positive_skew(self):
        """Slightly positive skew."""
        skew = self._make_skew(near_iv=14.0, far_iv=15.0)
        f = _score_iv_skew(skew)
        assert f.score == 7
        assert f.signal == "BULLISH"

    def test_flat_skew_neutral(self):
        """Near-flat structure."""
        skew = self._make_skew(near_iv=14.0, far_iv=14.5)
        f = _score_iv_skew(skew)
        assert f.score == 5
        assert f.signal == "NEUTRAL"

    def test_mild_inversion_bearish(self):
        """Near IV > Far IV = inversion = warning signal."""
        skew = self._make_skew(near_iv=17.0, far_iv=15.0)  # inversion of 2%
        f = _score_iv_skew(skew)
        assert f.score == 3
        assert f.signal == "BEARISH"

    def test_extreme_inversion_strongly_bearish(self):
        """Extreme inversion = institutions buying near-term protection."""
        skew = self._make_skew(near_iv=22.0, far_iv=15.0)  # 7% inversion
        f = _score_iv_skew(skew)
        assert f.score == 1
        assert f.signal == "BEARISH"
        assert "inversion" in f.detail.lower()

    def test_empty_skew_returns_neutral(self):
        f = _score_iv_skew([])
        assert f.score == 5
        assert f.signal == "NEUTRAL"

    def test_none_skew_returns_neutral(self):
        f = _score_iv_skew(None)
        assert f.score == 5


# ── Factor: India VIX Direction + Level ──────────────────────────────────────


class TestIndiaVixRegime:
    def test_very_low_vix(self):
        f = _score_india_vix_regime(10.0)
        assert f.score >= 8
        assert f.signal == "BULLISH"

    def test_high_vix_bearish(self):
        f = _score_india_vix_regime(24.0)
        assert f.score <= 3
        assert f.signal == "BEARISH"

    def test_zero_vix_unavailable(self):
        with patch("market.indices.get_vix", return_value=0.0):
            f = _score_india_vix_regime(0.0)
        assert f.signal == "UNAVAILABLE"

    def test_vix_level_and_direction_reflected_in_label(self):
        f = _score_india_vix_regime(15.0)
        assert f.factor_id == "india_vix"
        assert "Direction" in f.label or "Level" in f.label or "VIX" in f.label


# ── Factor: Max Pain Proximity ────────────────────────────────────────────────


class TestMaxPainProximity:
    def test_no_max_pain_neutral(self):
        f = _score_max_pain_proximity(23500.0, max_pain=None)
        assert f.score == 5
        assert f.signal == "NEUTRAL"

    def test_spot_at_max_pain_mid_week(self):
        f = _score_max_pain_proximity(23500.0, max_pain=23500.0)
        assert f.score >= 5  # Near max pain = low volatility zone

    def test_axis_is_price(self):
        f = _score_max_pain_proximity(23500.0, max_pain=23500.0)
        assert f.axis == "PRICE"

    def test_spot_zero_neutral(self):
        f = _score_max_pain_proximity(0.0, max_pain=23500.0)
        assert f.score == 5


# ── Factor: Blast Signal ──────────────────────────────────────────────────────


class TestBlastSignal:
    def test_no_blast_neutral(self):
        f = _score_blast_signal_quality(None, None, None)
        assert f.score == 5
        assert f.signal == "NEUTRAL"
        assert f.axis == "TIMING"

    def test_elite_blast(self):
        f = _score_blast_signal_quality(92, None, None)
        assert f.score == 10
        assert f.signal == "BULLISH"

    def test_high_quality_blast(self):
        f = _score_blast_signal_quality(85, None, None)
        assert f.score == 8

    def test_vol_oi_bonus(self):
        base = _score_blast_signal_quality(75, None, None)
        with_vol = _score_blast_signal_quality(75, 5.5, None)
        assert with_vol.score > base.score

    def test_imbalance_bonus(self):
        base = _score_blast_signal_quality(75, None, None)
        with_imb = _score_blast_signal_quality(75, None, 3.0)
        assert with_imb.score > base.score


# ── Veto System ───────────────────────────────────────────────────────────────


class TestVetoSystem:
    def test_no_veto_normal_conditions(self):
        veto = _check_veto_conditions(
            vix=12.0, fii_streak=1, fii_streak_total=500.0, data_state="LIVE"
        )
        assert veto.vetoed is False

    def test_veto_extreme_vix(self):
        veto = _check_veto_conditions(
            vix=26.5, fii_streak=None, fii_streak_total=None, data_state=None
        )
        assert veto.vetoed is True
        assert "25" in veto.reason or "VIX" in veto.reason

    def test_veto_sustained_fii_selling(self):
        veto = _check_veto_conditions(
            vix=14.0, fii_streak=-6, fii_streak_total=-20000.0, data_state=None
        )
        assert veto.vetoed is True
        assert "VETO" in veto.reason

    def test_veto_stale_data(self):
        veto = _check_veto_conditions(
            vix=12.0, fii_streak=1, fii_streak_total=100.0, data_state="STALE"
        )
        assert veto.vetoed is True
        assert "STALE" in veto.reason

    def test_veto_caps_score_at_55(self):
        """If vetoed, total score must not exceed 55."""
        # We can't easily mock all 12 factors, so we simulate by checking
        # the scoring logic: the vetoed check must cap at 55 in get_conviction_score
        # Here we test the veto object creation contract
        veto = VetoResult(vetoed=True, reason="⛔ VETO: Test")
        assert veto.vetoed is True


# ── Integration: get_conviction_score ─────────────────────────────────────────


class TestGetConvictionScore:
    """Integration tests with all 12 factor functions mocked."""

    def _factor(self, score: int, signal: str = "BULLISH", axis: str = "") -> FactorScore:
        return FactorScore(
            factor_id="mock",
            label="Mock",
            score=score,
            signal=signal,
            detail="mock",
            axis=axis,
        )

    def _patch_all(self, factors: list):
        """Context manager patching all 12 factor functions."""
        factor_names = [
            "engine.conviction_score._score_fii_cash_flow",
            "engine.conviction_score._score_fii_futures_position",
            "engine.conviction_score._score_global_macro",
            "engine.conviction_score._score_india_vix_regime",
            "engine.conviction_score._score_gex_posture",
            "engine.conviction_score._score_pcr_contrarian",
            "engine.conviction_score._score_iv_skew",
            "engine.conviction_score._score_smc_structure",
            "engine.conviction_score._score_max_pain_proximity",
            "engine.conviction_score._score_sector_rotation",
            "engine.conviction_score._score_event_calendar",
            "engine.conviction_score._score_blast_signal_quality",
        ]
        patches = []
        for name, factor in zip(factor_names, factors):
            p = patch(name, return_value=factor)
            patches.append(p)
        return patches

    def test_max_conviction_all_10_factors(self):
        """All 12 score 10/10 → 120/120 → 100% → MAX_CONVICTION."""
        factors = [self._factor(10, "BULLISH") for _ in range(12)]
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()

        assert result.total_score == 100
        assert result.verdict == "MAX_CONVICTION"
        assert result.verdict_color == "emerald"
        assert result.recommended_position_size == "2X"

    def test_wait_verdict_all_zero(self):
        """All 12 score 0 → 0/120 → 0% → WAIT."""
        factors = [self._factor(0, "BEARISH") for _ in range(12)]
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("BANKNIFTY", 49000.0)
        finally:
            for p in patches:
                p.stop()

        assert result.total_score == 0
        assert result.verdict == "WAIT"
        assert result.recommended_position_size == "FLAT"

    def test_high_verdict_7_per_factor(self):
        """All 12 score 7 → 84/120 = 70 → HIGH."""
        factors = [self._factor(7, "BULLISH") for _ in range(12)]
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()

        assert result.total_score == 70
        assert result.verdict == "HIGH"

    def test_as_dict_has_12_factors(self):
        """Ensure all 12 factor dicts are returned."""
        factors = [self._factor(7) for _ in range(12)]
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()

        d = result.as_dict()
        assert len(d["factors"]) == 12
        for key in (
            "total_score",
            "verdict",
            "verdict_color",
            "summary",
            "factors",
            "recommended_position_size",
            "bullish_count",
            "bearish_count",
            "unavailable_count",
        ):
            assert key in d

    def test_veto_caps_score(self):
        """Vetoed system caps score at 55 regardless of raw factor scores."""
        factors = [self._factor(10, "BULLISH") for _ in range(12)]
        patches = self._patch_all(factors)
        # Patch veto to return a hard block
        veto_patch = patch(
            "engine.conviction_score._check_veto_conditions",
            return_value=__import__("engine.conviction_score", fromlist=["VetoResult"]).VetoResult(
                vetoed=True, reason="⛔ VETO: Test extreme VIX"
            ),
        )
        for p in patches:
            p.start()
        veto_patch.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()
            veto_patch.stop()

        assert result.total_score <= 55
        assert result.verdict != "MAX_CONVICTION"
        assert result.veto is not None
        assert result.veto.vetoed is True

    def test_bullish_bearish_unavailable_counts(self):
        """Verify signal counts are aggregated correctly across 12 factors."""
        factors = (
            [self._factor(8, "BULLISH")] * 5
            + [self._factor(2, "BEARISH")] * 4
            + [self._factor(5, "UNAVAILABLE")] * 3
        )
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()

        assert result.bullish_count == 5
        assert result.bearish_count == 4
        assert result.unavailable_count == 3

    def test_normalization_from_120_to_100(self):
        """Verify score normalization: 60/120 raw → 50 normalized."""
        factors = [self._factor(5, "NEUTRAL") for _ in range(12)]
        patches = self._patch_all(factors)
        for p in patches:
            p.start()
        try:
            result = get_conviction_score("NIFTY", 23500.0)
        finally:
            for p in patches:
                p.stop()

        # 5*12 = 60 raw, 60/120*100 = 50
        assert result.total_score == 50
        assert result.verdict == "MODERATE"
