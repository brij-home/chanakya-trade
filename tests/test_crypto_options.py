"""
tests/test_crypto_options.py
────────────────────────────
Institutional test suite for 24x7 Deribit Options, Squeeze Analysis,
and Dedicated Telegram Routing to Crypto_Premium_Alpha_Vortex (-1004323607372).
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from market.crypto_options import (
    DeribitOptionContract,
    calculate_max_pain,
    get_crypto_options_summary,
    parse_deribit_instrument,
)
from market.crypto_stream import crypto_stream
from engine.alert_preferences import (
    AlertPreferences,
    classify_alert_segment,
    alert_preferences,
)
from web.api import app


# ── 1. Deribit Instrument Parsing Tests ────────────────────────


def test_parse_deribit_instrument():
    # Valid calls and puts
    res1 = parse_deribit_instrument("BTC-26SEP26-80000-C")
    assert res1 == ("BTC", "26SEP26", 80000.0, "CE")

    res2 = parse_deribit_instrument("ETH-27MAR26-2500-P")
    assert res2 == ("ETH", "27MAR26", 2500.0, "PE")

    res3 = parse_deribit_instrument("SOL-25DEC26-150.5-C")
    assert res3 == ("SOL", "25DEC26", 150.5, "CE")

    # Invalid instruments
    assert parse_deribit_instrument("BTC-PERPETUAL") is None
    assert parse_deribit_instrument("BTC-INVALID-FORMAT") is None
    assert parse_deribit_instrument("") is None


# ── 2. Max Pain Calculation Tests ──────────────────────────────


def test_calculate_max_pain():
    # Construct a synthetic option chain:
    # Spot is near 80,000.
    # Strikes: 70,000, 80,000, 90,000
    contracts = [
        DeribitOptionContract(
            instrument_name="BTC-TEST-70000-C",
            currency="BTC",
            expiry="TEST",
            strike=70000.0,
            option_type="CE",
            mark_price_crypto=0.15,
            mark_price_usd=12000.0,
            underlying_price=80000.0,
            iv=50.0,
            open_interest=100.0,
            volume_24h=10.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-70000-P",
            currency="BTC",
            expiry="TEST",
            strike=70000.0,
            option_type="PE",
            mark_price_crypto=0.01,
            mark_price_usd=800.0,
            underlying_price=80000.0,
            iv=55.0,
            open_interest=5.0,
            volume_24h=1.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-80000-C",
            currency="BTC",
            expiry="TEST",
            strike=80000.0,
            option_type="CE",
            mark_price_crypto=0.05,
            mark_price_usd=4000.0,
            underlying_price=80000.0,
            iv=48.0,
            open_interest=50.0,
            volume_24h=20.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-80000-P",
            currency="BTC",
            expiry="TEST",
            strike=80000.0,
            option_type="PE",
            mark_price_crypto=0.05,
            mark_price_usd=4000.0,
            underlying_price=80000.0,
            iv=48.0,
            open_interest=50.0,
            volume_24h=20.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-90000-C",
            currency="BTC",
            expiry="TEST",
            strike=90000.0,
            option_type="CE",
            mark_price_crypto=0.01,
            mark_price_usd=800.0,
            underlying_price=80000.0,
            iv=52.0,
            open_interest=10.0,
            volume_24h=5.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-90000-P",
            currency="BTC",
            expiry="TEST",
            strike=90000.0,
            option_type="PE",
            mark_price_crypto=0.15,
            mark_price_usd=12000.0,
            underlying_price=80000.0,
            iv=50.0,
            open_interest=120.0,
            volume_24h=15.0,
        ),
    ]

    # Pain at 70,000:
    # Calls: 0
    # Puts: (80000 - 70000)*50 + (90000 - 70000)*120 = 500,000 + 2,400,000 = 2,900,000
    #
    # Pain at 80,000:
    # Calls: (80000 - 70000)*100 = 1,000,000
    # Puts: (90000 - 80000)*120 = 1,200,000
    # Total = 2,200,000 (Lowest!)
    #
    # Pain at 90,000:
    # Calls: (90000 - 70000)*100 + (90000 - 80000)*50 = 2,000,000 + 500,000 = 2,500,000
    # Puts: 0
    # Total = 2,500,000
    max_pain = calculate_max_pain(contracts)
    assert max_pain == 80000.0


# ── 3. Deribit Options Summary & GEX Tests ─────────────────────


def test_calculate_deribit_gex():
    """Verify Dealer Gamma Exposure (GEX) calculation on synthetic options chain."""
    from market.crypto_options import calculate_deribit_gex

    contracts = [
        DeribitOptionContract(
            instrument_name="BTC-TEST-80000-C",
            currency="BTC",
            expiry="26DEC26",
            strike=80000.0,
            option_type="CE",
            mark_price_crypto=0.05,
            mark_price_usd=4000.0,
            underlying_price=80000.0,
            iv=50.0,
            open_interest=500.0,
            volume_24h=100.0,
        ),
        DeribitOptionContract(
            instrument_name="BTC-TEST-80000-P",
            currency="BTC",
            expiry="26DEC26",
            strike=80000.0,
            option_type="PE",
            mark_price_crypto=0.05,
            mark_price_usd=4000.0,
            underlying_price=80000.0,
            iv=50.0,
            open_interest=200.0,
            volume_24h=50.0,
        ),
    ]

    gex = calculate_deribit_gex(contracts, underlying_spot=80000.0)
    assert "net_gex_usd" in gex
    assert "call_gex_usd" in gex
    assert "put_gex_usd" in gex
    assert "gamma_regime" in gex
    assert "gex_flip_strike" in gex
    assert gex["call_gex_usd"] > 0
    assert gex["put_gex_usd"] > 0
    # Since call OI (500) > put OI (200) at ATM strike, net GEX should be positive
    assert gex["net_gex_usd"] > 0
    assert gex["gamma_regime"] == "POSITIVE_GAMMA_PIN"


def test_get_crypto_options_summary():
    summary = get_crypto_options_summary("BTC")
    assert "status" in summary
    assert summary["currency"] == "BTC"
    if summary["status"] == "ONLINE":
        assert summary["underlying_spot"] > 0
        assert summary["contracts_count"] > 0
        assert summary["max_pain"] > 0
        assert "pcr_open_interest" in summary
        assert "atm_implied_volatility_pct" in summary
        assert "net_gex_usd" in summary
        assert "gamma_regime" in summary
        assert summary["gamma_regime"] in ("POSITIVE_GAMMA_PIN", "NEGATIVE_GAMMA_ACCELERATION", "NEUTRAL")
        assert summary["pcr_sentiment"] in (
            "BULLISH_EXHAUSTION_EXTREME",
            "MILD_BULLISH",
            "BEARISH_GREED_EXTREME",
            "NEUTRAL",
        )


# ── 4. Binance Futures Squeeze Metrics Tests ───────────────────


def test_crypto_squeeze_metrics():
    squeeze = crypto_stream.get_squeeze_metrics("BTCUSDT")
    assert squeeze["symbol"] == "BTCUSDT"
    assert "squeeze_signal" in squeeze
    assert "conviction" in squeeze
    assert "recommendation" in squeeze
    assert "futures_metrics" in squeeze
    f_metrics = squeeze["futures_metrics"]
    assert "funding_rate_8h" in f_metrics
    assert "open_interest_contracts" in f_metrics


# ── 5. Telegram Routing & Channel Segregation Tests ────────────


def test_telegram_crypto_channel_segregation():
    prefs = AlertPreferences()

    # Verify dedicated Crypto Chat ID is strictly configured
    crypto_chat = prefs.get_telegram_chat_id("CRYPTO")
    assert crypto_chat == "-1004323607372"

    # Verify equity alerts do not leak into crypto channel
    equity_chat = prefs.get_telegram_chat_id("EQUITY")
    assert equity_chat == "-1003524867091"
    assert equity_chat != crypto_chat

    # Verify F&O stock alerts do not leak into crypto channel
    fno_stock_chat = prefs.get_telegram_chat_id("FNO_STOCK")
    assert fno_stock_chat == "-1004393392375"
    assert fno_stock_chat != crypto_chat

    # Verify F&O index alerts do not leak into crypto channel
    fno_index_chat = prefs.get_telegram_chat_id("FNO_INDEX")
    assert fno_index_chat == "-1004380788314"
    assert fno_index_chat != crypto_chat

    # Test segment classifier
    assert classify_alert_segment({"symbol": "BTCUSDT", "exchange": "CRYPTO"}) == "CRYPTO"
    assert classify_alert_segment({"symbol": "ETHUSDT", "exchange": "BINANCE"}) == "CRYPTO"
    assert classify_alert_segment({"symbol": "CRYPTO:SOL", "segment": "CRYPTO"}) == "CRYPTO"


# ── 6. FastAPI Crypto Options & Squeeze Endpoints Tests ─────────


def test_crypto_options_and_squeeze_api():
    client = TestClient(app)

    # 1. Options endpoint
    resp_opt = client.get("/api/crypto/options?currency=BTC")
    assert resp_opt.status_code == 200
    opt_data = resp_opt.json()
    assert "status" in opt_data
    assert opt_data["currency"] == "BTC"

    # 2. Squeeze endpoint
    resp_sq = client.get("/api/crypto/squeeze?symbol=BTCUSDT")
    assert resp_sq.status_code == 200
    sq_data = resp_sq.json()
    assert sq_data["symbol"] == "BTCUSDT"
    assert "squeeze_signal" in sq_data
    assert "conviction" in sq_data


# ── 7. Crypto Telegram Alert Template Rendering ────────────────


def test_render_crypto_auto_alert():
    from engine.auto_alert_engine import AutoAlert
    from bot.alert_templates import render_auto_alert

    alert = AutoAlert(
        alert_id="crypto-btcusdt-202609210200",
        alert_type="CRYPTO_SMC_BREAKOUT",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="CRYPTO",
        direction="BULLISH",
        headline="🪙 [CRYPTO 24x7] BTCUSDT +2.1% Order Block Demand Reclaim",
        summary="Institutional breakout in BTCUSDT at $81,250.",
        ltp=81250.0,
        trigger_level=81250.0,
        target_level=84500.0,
        stop_loss=80200.0,
        confidence=88,
        actionable_plan={
            "action": "BUY_SPOT / LONG",
            "segment": "CRYPTO",
            "contract": "CRYPTO:BTCUSDT",
            "entry_range": "$81,100.00 – $81,300.00",
            "stop_loss": "$80,200.00",
            "target": "$84,500.00",
            "target_2": "$86,800.00",
            "risk_reward": "1:3.1",
            "setup_confluence": "Demand OB + FVG Reclaim + Squeeze Exhaustion",
            "profit_rule": "Book 50% at T1, trail stop on 20-EMA.",
        },
    )

    rendered = render_auto_alert(alert, in_market=False)
    assert "[CRYPTO 24x7] ALPHA VORTEX" in rendered
    assert "$81,100.00" in rendered
    assert "$80,200.00" in rendered
    assert "$84,500.00" in rendered
    assert "Demand OB + FVG Reclaim" in rendered
    assert "Market is closed" not in rendered  # Crypto is 24x7, never suppressed!

