"""
tests/test_relative_strength.py
────────────────────────────────
Unit and integration tests for the Intraday Relative Strength (RS) & Relative Weakness (RW) Radar.
"""

from brokers.base import Quote
from analysis.relative_strength import compute_intraday_rs_rw


def _make_quote(
    symbol: str,
    last_price: float,
    change_pct: float,
    vwap: float = 0.0,
    volume: int = 100000,
) -> Quote:
    return Quote(
        symbol=symbol,
        last_price=last_price,
        close=last_price / (1.0 + change_pct / 100.0) if change_pct != -100 else last_price,
        change=last_price * (change_pct / 100.0),
        change_pct=change_pct,
        volume=volume,
        vwap=vwap or last_price,
    )


def test_compute_rs_rw_basic_partitioning():
    """Verify outperforming stocks are grouped under leaders and underperforming under laggards."""
    mock_quotes = {
        "NSE:NIFTY50-INDEX": _make_quote("NSE:NIFTY50-INDEX", 24000.0, 0.50),
        "NSE:RELIANCE": _make_quote("NSE:RELIANCE", 2900.0, 2.50, vwap=2880.0),  # net_rs = +2.0%
        "NSE:INFY": _make_quote("NSE:INFY", 1850.0, 1.20, vwap=1840.0),  # net_rs = +0.7%
        "NSE:TCS": _make_quote("NSE:TCS", 4100.0, -1.50, vwap=4150.0),  # net_rs = -2.0%
        "NSE:HDFCBANK": _make_quote("NSE:HDFCBANK", 1650.0, -0.80, vwap=1670.0),  # net_rs = -1.3%
    }

    report = compute_intraday_rs_rw(
        universe=["RELIANCE", "INFY", "TCS", "HDFCBANK"],
        benchmark_symbol="NSE:NIFTY50-INDEX",
        quotes_map=mock_quotes,
        bypass_cache=True,
    )

    assert report.status == "OK"
    assert report.benchmark_symbol == "NSE:NIFTY50-INDEX"
    assert report.benchmark_ltp == 24000.0
    assert report.benchmark_change_pct == 0.50
    assert report.benchmark_state == "BULLISH"

    leader_syms = [l.clean_symbol for l in report.leaders]
    assert "RELIANCE" in leader_syms
    assert "INFY" in leader_syms

    laggard_syms = [l.clean_symbol for l in report.laggards]
    assert "TCS" in laggard_syms
    assert "HDFCBANK" in laggard_syms

    # Top leader should be RELIANCE with net_rs = 2.0
    rel_item = next(l for l in report.leaders if l.clean_symbol == "RELIANCE")
    assert rel_item.net_rs == 2.0
    assert rel_item.bias == "RELATIVE_STRENGTH"
    assert rel_item.above_vwap is True

    # Most negative laggard should be TCS with net_rs = -2.0
    tcs_item = next(l for l in report.laggards if l.clean_symbol == "TCS")
    assert tcs_item.net_rs == -2.0
    assert tcs_item.bias == "RELATIVE_WEAKNESS"
    assert tcs_item.above_vwap is False


def test_decoupled_alpha_badge_when_nifty_is_red():
    """Verify decoupled alpha badge fires when Nifty is red and stock is green with strong RS."""
    mock_quotes = {
        "NSE:NIFTY50-INDEX": _make_quote("NSE:NIFTY50-INDEX", 23900.0, -0.80),
        "NSE:POWERINDIA": _make_quote("NSE:POWERINDIA", 31200.0, 4.50, vwap=30500.0),
    }

    report = compute_intraday_rs_rw(
        universe=["POWERINDIA"],
        benchmark_symbol="NSE:NIFTY50-INDEX",
        quotes_map=mock_quotes,
        bypass_cache=True,
    )

    assert report.status == "OK"
    assert report.benchmark_state == "BEARISH"
    assert len(report.leaders) == 1
    pwr = report.leaders[0]
    assert pwr.clean_symbol == "POWERINDIA"
    assert pwr.catalyst_badge == "DECOUPLED_ALPHA"


def test_systemic_breakdown_badge_when_nifty_is_green():
    """Verify systemic breakdown badge fires when Nifty is green and stock is collapsing."""
    mock_quotes = {
        "NSE:NIFTY50-INDEX": _make_quote("NSE:NIFTY50-INDEX", 24200.0, 0.60),
        "NSE:WEAKSTOCK": _make_quote("NSE:WEAKSTOCK", 500.0, -2.50, vwap=520.0),
    }

    report = compute_intraday_rs_rw(
        universe=["WEAKSTOCK"],
        benchmark_symbol="NSE:NIFTY50-INDEX",
        quotes_map=mock_quotes,
        bypass_cache=True,
    )

    assert report.status == "OK"
    assert len(report.laggards) == 1
    weak = report.laggards[0]
    assert weak.catalyst_badge == "SYSTEMIC_BREAKDOWN"


def test_benchmark_unavailable_fails_closed():
    """Verify fail-closed contract: returns status UNAVAILABLE if benchmark quote is missing or zero."""
    mock_quotes = {
        "NSE:RELIANCE": _make_quote("NSE:RELIANCE", 2900.0, 2.50),
    }

    report = compute_intraday_rs_rw(
        universe=["RELIANCE"],
        benchmark_symbol="NSE:NIFTY50-INDEX",
        quotes_map=mock_quotes,
        bypass_cache=True,
    )

    assert report.status == "UNAVAILABLE"
    assert len(report.leaders) == 0
    assert len(report.laggards) == 0
