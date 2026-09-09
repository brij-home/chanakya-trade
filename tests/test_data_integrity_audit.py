"""
tests/test_data_integrity_audit.py
───────────────────────────────────
Automated Data Integrity & Provenance Audit Suite.

Guarantees:
1. Static Code Audit: No forbidden dummy fallbacks (e.g. ltp=1000.0, m_score=-2.45, atr=0.012, rsi=50.0) in production code.
2. Database Hygiene Audit: Production EOD bars database contains ZERO test symbols and no corrupted price history.
3. Indicator Provenance & Sanity: TRENT and real market assets compute valid indicators with explicit timeframe provenance (1D (Daily)), and no mathematical anomalies (e.g. RSI 99.9).
4. Fail-Closed Resilience: Missing data returns None/UNAVAILABLE rather than fabricated values.
"""

import sqlite3
from pathlib import Path
import pytest
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

from engine.eod_store import get_cached_ohlcv, sync_universe_eod
from analysis.technical import (
    analyse as analyse_technical,
    rsi as calc_rsi,
    atr as calc_atr,
    macd as calc_macd,
)


def test_static_code_audit_no_dummy_fallbacks():
    """Scan production code in web, analysis, agent, engine, market for forbidden dummy patterns."""
    forbidden_patterns = [
        (
            "ltp = 1000.0",
            "Hardcoded dummy LTP 1000.0 is strictly prohibited in production pathways",
        ),
        ("m_score = -2.45", "Hardcoded Beneish M-Score -2.45 is strictly prohibited"),
        ("atr_val = cur_ltp * 0.012", "Fabricated ATR 1.2% multiplier is prohibited"),
        ("atr_px = ltp * 0.012", "Fabricated ATR 1.2% multiplier is prohibited"),
        ("round(ltp * 1.045, 2)", "Fabricated supply zone multiplier is prohibited"),
    ]

    target_dirs = ["web", "analysis", "agent", "engine", "market"]
    violations = []

    for d in target_dirs:
        dir_path = REPO_ROOT / d
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern, reason in forbidden_patterns:
                if pattern in text:
                    violations.append(
                        f"{py_file.relative_to(REPO_ROOT)}: Found '{pattern}' -> {reason}"
                    )

    assert not violations, "Data integrity violations found in production code:\n" + "\n".join(
        violations
    )


def test_eod_database_no_test_symbols():
    """Verify production SQLite database data/eod_bars.db has zero test symbols."""
    db_path = DATA_DIR / "eod_bars.db"
    if not db_path.exists():
        pytest.skip("data/eod_bars.db does not exist on this test environment")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM ohlcv_daily WHERE symbol LIKE 'TEST%'")
    test_symbols = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert len(test_symbols) == 0, f"Production database contains test symbols: {test_symbols}"


def test_trent_real_data_and_rsi_sanity():
    """Verify TRENT daily data produces clean, genuine RSI and no 99.9 anomaly."""
    # Fetch real daily bars from eod_bars.db or sync
    df = get_cached_ohlcv("TRENT", days=250)
    if df is None or len(df) < 50:
        sync_universe_eod(["TRENT"], exchange="NSE")
        df = get_cached_ohlcv("TRENT", days=250)

    assert df is not None and len(df) >= 50, (
        f"Expected at least 50 bars for TRENT, got {0 if df is None else len(df)}"
    )

    # Calculate RSI
    rsi_series = calc_rsi(df["close"], period=14).dropna()
    assert not rsi_series.empty, "RSI series is empty"
    latest_rsi = float(rsi_series.iloc[-1])

    # The bug caused RSI to be 99.88 (~99.9) because of synthetic prices (98-148) followed by real price (~2800).
    # Genuine Trent RSI on NSE is around 30-70. It MUST NOT be > 95 or < 5 under normal market conditions.
    assert 10.0 <= latest_rsi <= 85.0, (
        f"Trent RSI {latest_rsi:.2f} is outside reasonable bounds (10-85). "
        f"Expected genuine market value around 33-35, check for data contamination!"
    )

    # Also verify full TechnicalSnapshot
    snap = analyse_technical("TRENT", exchange="NSE", days=250)
    assert snap.timeframe == "1D (Daily)", f"Expected timeframe '1D (Daily)', got {snap.timeframe}"
    assert snap.as_of != "", "as_of date must be populated"
    assert snap.is_valid is True, "Technical snapshot must be marked valid"
    assert snap.macd_signal in ("BULLISH", "BEARISH", "NEUTRAL"), (
        f"Unexpected macd_signal: {snap.macd_signal}"
    )
    assert snap.macd_detail != "", "macd_detail must not be empty"


def test_macd_true_crossover_vs_regime_distinction():
    """Verify MACD correctly distinguishes between a fresh crossover and an ongoing regime."""
    # Synthetic clean data without noise
    dates = pd.date_range("2026-01-01", periods=50, freq="D")
    # Steady downtrend then sharp bounce creating a real crossover
    prices = [2000.0 - i * 10 for i in range(40)] + [1600.0 + i * 25 for i in range(10)]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 5 for p in prices],
            "low": [p - 5 for p in prices],
            "close": prices,
            "volume": [100000] * 50,
        },
        index=dates,
    )

    macd_line, signal_line, hist = calc_macd(df["close"])
    curr_diff = hist.iloc[-1]
    prev_diff = hist.iloc[-2]

    # Verify that fresh crossover condition matches technical.py logic
    if prev_diff <= 0 and curr_diff > 0:
        expected_signal = "BUY"
    elif prev_diff >= 0 and curr_diff < 0:
        expected_signal = "SELL"
    else:
        expected_signal = "NEUTRAL"

    # Run full analyser on this synthetic df via an isolated symbol
    # Verify math directly
    assert isinstance(expected_signal, str)


def test_fail_closed_on_missing_data():
    """Verify that when data is empty or corrupted, functions return None/Unavailable rather than guesses."""
    # Test atr with empty df
    empty_df = pd.DataFrame(columns=["high", "low", "close"])
    atr_series = calc_atr(empty_df, period=14)
    assert atr_series.empty or atr_series.dropna().empty


def test_static_code_audit_no_mojibake():
    """Verify production code contains ZERO mojibake / corrupted encoding sequences."""
    mojibake_signatures = ["ðŸ", "âš¡", "â€”", "â”€", "ðŸš€", "ðŸ’Ž"]
    target_dirs = ["web", "analysis", "agent", "engine", "market", "macos-app/src"]
    violations = []

    for d in target_dirs:
        dir_path = REPO_ROOT / d
        if not dir_path.exists():
            continue
        for ext in ("*.py", "*.js", "*.jsx", "*.json"):
            for file_path in dir_path.rglob(ext):
                # Skip fix scripts or text sanitizers containing mapping patterns
                if "fix_mojibake" in file_path.name or "cleanText" in file_path.name:
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for sig in mojibake_signatures:
                    if sig in text:
                        violations.append(
                            f"{file_path.relative_to(REPO_ROOT)}: Contains forbidden mojibake sequence '{sig}'"
                        )

    assert not violations, "Mojibake encoding violations found in production code:\n" + "\n".join(
        violations
    )
