"""
Unit tests for Institutional SABR Volatility Smile & Surface Modeler in analysis/vol_surface.py.
"""

from analysis.vol_surface import (
    sabr_implied_volatility,
    calibrate_sabr,
    interpolate_sabr_smile,
    detect_strike_mispricings,
    SABRParameters,
)


def test_sabr_atm_continuity():
    """Verify SABR implied volatility is smooth and continuous near ATM."""
    f = 25000.0
    t = 30.0 / 365.0  # ~1 month
    # For beta=0.7 and F=25000, F^(1-beta) = 25000^0.3 = 21.05.
    # Alpha = 0.16 * 21.05 = ~3.37 for ~16% ATM IV
    alpha = 3.37
    beta = 0.7
    rho = -0.3
    nu = 0.5

    # Exact ATM
    atm_iv = sabr_implied_volatility(f, f, t, alpha, beta, rho, nu)
    assert atm_iv > 5.0 and atm_iv < 50.0  # Realistic IV %

    # 1 rupee above and below ATM
    iv_above = sabr_implied_volatility(f, f + 1.0, t, alpha, beta, rho, nu)
    iv_below = sabr_implied_volatility(f, f - 1.0, t, alpha, beta, rho, nu)

    # Discontinuity must be practically zero (< 0.05 pts)
    assert abs(iv_above - atm_iv) < 0.05
    assert abs(iv_below - atm_iv) < 0.05


def test_sabr_skew_shape_negative_rho():
    """Verify negative rho produces classic equity put skew (higher IV for lower strikes)."""
    f = 25000.0
    t = 15.0 / 365.0
    alpha = 3.37
    beta = 0.7
    rho = -0.45  # Negative correlation -> downside protection expensive
    nu = 0.6

    otm_put_k = 24000.0  # -4% OTM
    atm_k = 25000.0
    otm_call_k = 26000.0  # +4% OTM

    iv_put = sabr_implied_volatility(f, otm_put_k, t, alpha, beta, rho, nu)
    iv_atm = sabr_implied_volatility(f, atm_k, t, alpha, beta, rho, nu)
    iv_call = sabr_implied_volatility(f, otm_call_k, t, alpha, beta, rho, nu)

    # Classic equity skew: OTM Put IV > ATM IV > OTM Call IV
    assert iv_put > iv_atm
    assert iv_atm > iv_call


def test_sabr_smile_curvature_positive_nu():
    """Verify vol-of-vol (nu) controls smile curvature (wings lift above ATM when nu is high)."""
    f = 25000.0
    t = 30.0 / 365.0
    alpha = 3.37
    beta = 0.7
    rho = 0.0  # Zero correlation to isolate pure smile curvature
    nu_high = 1.2
    nu_low = 0.1

    deep_otm = 23000.0

    iv_high_nu = sabr_implied_volatility(f, deep_otm, t, alpha, beta, rho, nu_high)
    iv_low_nu = sabr_implied_volatility(f, deep_otm, t, alpha, beta, rho, nu_low)

    # Higher nu creates more wing curvature
    assert iv_high_nu > iv_low_nu


def test_calibrate_sabr_synthetic_data():
    """Verify calibrate_sabr converges to true parameters and maintains low RMSE."""
    f = 50000.0  # BankNifty scale
    t = 10.0 / 365.0
    true_alpha = 0.40
    true_beta = 0.7
    true_rho = -0.35
    true_nu = 0.65

    strikes = [48000.0, 48500.0, 49000.0, 49500.0, 50000.0, 50500.0, 51000.0, 51500.0, 52000.0]
    market_ivs = [
        sabr_implied_volatility(f, k, t, true_alpha, true_beta, true_rho, true_nu) for k in strikes
    ]

    calib = calibrate_sabr(
        forward_price=f,
        strikes=strikes,
        market_ivs=market_ivs,
        t_years=t,
        beta=true_beta,
    )

    assert calib.converged is True
    assert calib.rmse < 0.2  # Very tight fit on uncorrupted synthetic curve
    assert calib.mae < 0.2
    assert abs(calib.rho - true_rho) < 0.15
    assert abs(calib.nu - true_nu) < 0.25


def test_interpolate_sabr_smile():
    """Verify dense interpolation generates smooth monotonic or smile grid."""
    f = 25000.0
    t = 20.0 / 365.0
    params = SABRParameters(alpha=3.37, beta=0.7, rho=-0.3, nu=0.5, rmse=0.05, mae=0.04)

    strikes, ivs = interpolate_sabr_smile(
        forward_price=f,
        t_years=t,
        params=params,
        strike_min=24000.0,
        strike_max=26000.0,
        num_points=25,
    )

    assert len(strikes) == 25
    assert len(ivs) == 25
    assert strikes[0] == 24000.0
    assert strikes[-1] == 26000.0
    assert all(iv > 0.0 for iv in ivs)


def test_detect_strike_mispricings():
    """Verify quantitative detector flags overpriced and underpriced options strikes."""
    f = 25000.0
    t = 15.0 / 365.0
    params = SABRParameters(alpha=3.37, beta=0.7, rho=-0.3, nu=0.5, rmse=0.1, mae=0.08)

    strikes = [24000.0, 24500.0, 25000.0, 25500.0, 26000.0]
    fair_ivs = [
        sabr_implied_volatility(f, k, t, params.alpha, params.beta, params.rho, params.nu)
        for k in strikes
    ]

    # Inject artificial distortion:
    # Strike 24000 IV pumped up by +3.5 pts (retail panic bid)
    # Strike 26000 IV depressed by -2.5 pts (undervalued wing)
    distorted_ivs = list(fair_ivs)
    distorted_ivs[0] += 3.5
    distorted_ivs[4] -= 2.5

    mispricings = detect_strike_mispricings(
        forward_price=f,
        strikes=strikes,
        market_ivs=distorted_ivs,
        t_years=t,
        params=params,
        mispricing_threshold_pts=1.5,
    )

    assert len(mispricings) == 5
    # Strike 24000 must be OVERPRICED
    assert mispricings[0].strike == 24000.0
    assert mispricings[0].verdict == "OVERPRICED"
    assert mispricings[0].iv_edge_pts >= 3.0

    # ATM Strike 25000 must be FAIR
    assert mispricings[2].strike == 25000.0
    assert mispricings[2].verdict == "FAIR"

    # Strike 26000 must be UNDERPRICED
    assert mispricings[4].strike == 26000.0
    assert mispricings[4].verdict == "UNDERPRICED"
    assert mispricings[4].iv_edge_pts <= -2.0
