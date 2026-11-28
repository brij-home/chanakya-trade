"""Regression tests for 2026-11-27 production runtime incidents."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from config.constants import IST
from market.fyers_socket_patch import _SafeSymbolTokenDict


def test_safe_symbol_token_dict_single_arg_pop_does_not_raise_keyerror() -> None:
    """FyersDataSocket.__unsub_resp calls symbol_token.pop(symbol) without default."""
    tokens = _SafeSymbolTokenDict({"sf|bse_fo|824477": "BSE:SENSEX26D0384000PE"})

    first = tokens.pop("sf|bse_fo|824477", None)
    assert first == "BSE:SENSEX26D0384000PE"

    # Second single-arg pop arriving asynchronously from SDK __unsub_resp must not raise KeyError
    second = tokens.pop("sf|bse_fo|824477")
    assert second == "BSE:SENSEX26D0384000PE"

    # Never-seen token popped with no default must also not raise KeyError
    unknown = tokens.pop("sf|bse_fo|824853")
    assert unknown == "sf|bse_fo|824853"


def test_commodity_detector_filters_expired_mcx_option_contracts(monkeypatch) -> None:
    """Expired MCX option contracts (e.g. GOLD 2026-11-25) must be excluded in favor of active contracts."""
    import pandas as pd

    from brokers.base import Quote
    from engine.detectors.commodity import detect_commodity_breakouts

    now_dt = datetime.now(IST)
    yesterday_str = (now_dt.date() - timedelta(days=2)).isoformat()
    next_month_str = (now_dt.date() + timedelta(days=20)).isoformat()

    expired_ce = SimpleNamespace(
        symbol="MCX:GOLD26NOV125000CE",
        strike=125000.0,
        option_type="CE",
        last_price=820.0,
        volume=5000,
        oi=12000,
        oi_change=1000,
        pchange=12.0,
        expiry=yesterday_str,
    )
    active_ce = SimpleNamespace(
        symbol="MCX:GOLD26DEC125000CE",
        strike=125000.0,
        option_type="CE",
        last_price=1450.0,
        volume=8000,
        oi=25000,
        oi_change=2500,
        pchange=15.0,
        expiry=next_month_str,
    )

    q_gold = Quote(
        symbol="MCX:GOLD",
        last_price=125000.0,
        open=123000.0,
        high=125200.0,
        low=123000.0,
        close=122500.0,
        vwap=124000.0,
        volume=40000,
        change=2500.0,
        change_pct=2.04,
        provider="mock",
        data_state="TEST",
    )

    dates = pd.date_range("2026-11-27 09:00", periods=25, freq="5min")
    closes = [123000.0 + (i % 3) * 20.0 for i in range(24)] + [125000.0]
    opens = [c - 20.0 for c in closes]
    opens[0] = 123000.0
    highs = [c + 30.0 for c in closes]
    lows = [c - 25.0 for c in closes]
    lows[0] = 123000.0
    volumes = [1000.0] * 24 + [6000.0]
    df_5m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    from config.discovery_policy import DiscoveryPolicy

    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    with (
        patch("engine.detectors.commodity.datetime") as mock_dt,
        patch(
            "config.discovery_policy.get_discovery_policy", return_value=DiscoveryPolicy("BALANCED")
        ),
        patch("market.quotes.get_quote", return_value={"MCX:GOLD": q_gold}),
        patch("market.history.get_ohlcv", return_value=df_5m),
        patch("market.options.get_options_chain", return_value=[expired_ce, active_ce]),
        patch("analysis.order_flow.analyze_order_flow", return_value=None),
        patch("market.order_book.analyze_symbol_order_book", return_value=None),
        patch("analysis.market_structure.analyze_market_structure", return_value=None),
    ):
        mock_dt.now.return_value = datetime(2026, 11, 27, 9, 20, tzinfo=IST)
        alerts = detect_commodity_breakouts(
            universe=["GOLD"],
            quotes_map={"MCX:GOLD": q_gold, "GOLD": q_gold},
            ohlcv_map={"GOLD": df_5m},
        )

    gold_opts = [a for a in alerts if a.symbol == "GOLD" and getattr(a, "option_type", None)]
    assert len(gold_opts) >= 1
    for a in gold_opts:
        assert a.expiry_date != yesterday_str
        assert a.expiry_date >= now_dt.date().isoformat()
        assert a.contract_symbol == "MCX:GOLD26DEC125000CE"


def test_commodity_live_dead_rvol_and_unconfirmed_counter_vwap_suppressed(monkeypatch) -> None:
    """
    RCA for 2026-11-27 15:38-15:42 CRUDEOIL & NATURALGAS stagnation alerts:
    1. Live CRUDEOIL pullback with dead RVOL (<1.0x) and high CHOP must be suppressed.
    2. Live NATURALGAS below VWAP (-0.5% day) with unconfirmed candle must be suppressed even on 1m wick.
    """
    import pandas as pd

    from brokers.base import Quote
    from config.discovery_policy import DiscoveryPolicy
    from engine.detectors.commodity import detect_commodity_breakouts

    now_dt = datetime(2026, 11, 27, 15, 40, tzinfo=IST)
    q_crude = Quote(
        symbol="MCX:CRUDEOIL",
        last_price=7989.0,
        open=7872.0,
        high=8035.0,
        low=7865.0,
        close=7872.0,
        vwap=7986.0,
        volume=13283,
        change=117.0,
        change_pct=1.49,
        provider="fyers",
        source="STREAM",
        data_state="LIVE",
    )
    q_crude.force_live_eval = True

    dates = pd.date_range("2026-11-27 13:30", periods=25, freq="5min")
    # Choppy pullback range below 50-bar peak with low trailing volume
    closes = [7990.0 + ((i % 2) * 8.0 - 4.0) for i in range(25)]
    df_crude = pd.DataFrame(
        {
            "open": [c + 2.0 for c in closes],
            "high": [c + 12.0 for c in closes],
            "low": [c - 12.0 for c in closes],
            "close": closes,
            "volume": [1000.0] * 24 + [600.0],  # RVOL ~ 0.6x
        },
        index=dates,
    )

    q_ng = Quote(
        symbol="MCX:NATURALGAS",
        last_price=333.3,
        open=335.1,
        high=335.5,
        low=332.7,
        close=335.1,
        vwap=335.07,
        volume=32659,
        change=-1.8,
        change_pct=-0.54,
        provider="fyers",
        source="STREAM",
        data_state="LIVE",
    )
    q_ng.force_live_eval = True

    closes_ng = [335.5 - i * 0.1 for i in range(25)]
    closes_ng[-1] = 333.3
    df_ng = pd.DataFrame(
        {
            "open": [c + 0.15 for c in closes_ng],
            "high": [c + 0.25 for c in closes_ng],
            "low": [c - 0.30 for c in closes_ng],
            "close": closes_ng,
            "volume": [1200.0] * 24 + [1500.0],
        },
        index=dates,
    )
    df_ng.loc[df_ng.index[-1], "low"] = 332.7

    smc_unconfirmed = SimpleNamespace(
        bos_detected=False,
        bos_type=None,
        choch_detected=False,
        choch_type=None,
        liquidity_sweeps=[SimpleNamespace(type="BULLISH_SWEEP")],
        active_demand_zones=[],
        active_supply_zones=[],
        demand_zones=[],
        supply_zones=[],
        fair_value_gaps=[],
        regime="NEUTRAL",
        structure_score=0,
        setup_type="BOTTOM_FISHING_SPRING",
        confirmation_confirmed=False,
        candle_pattern="Hammer",
        invalidation_level=0.0,
        divergence_type=None,
        divergence_bias=None,
    )

    with (
        patch("engine.detectors.commodity.datetime") as mock_dt,
        patch(
            "config.discovery_policy.get_discovery_policy", return_value=DiscoveryPolicy("BALANCED")
        ),
        patch(
            "market.quotes.get_quote",
            return_value={"MCX:CRUDEOIL": q_crude, "MCX:NATURALGAS": q_ng},
        ),
        patch("market.history.get_ohlcv", return_value=None),
        patch("analysis.order_flow.analyze_order_flow", return_value=None),
        patch("market.order_book.analyze_symbol_order_book", return_value=None),
        patch("analysis.market_structure.analyze_market_structure", return_value=smc_unconfirmed),
    ):
        mock_dt.now.return_value = now_dt
        monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
        alerts = detect_commodity_breakouts(
            universe=["CRUDEOIL", "NATURALGAS"],
            quotes_map={"MCX:CRUDEOIL": q_crude, "MCX:NATURALGAS": q_ng},
            ohlcv_map={"CRUDEOIL": df_crude, "NATURALGAS": df_ng},
        )

    assert len(alerts) == 0, (
        f"Low-RVOL chop and unconfirmed counter-VWAP must be suppressed, got: {alerts}"
    )


def test_defined_risk_spread_calibrates_chain_and_hides_zero_profit_spread() -> None:
    """
    RCA for CRUDEOIL 8000 CE Max Profit Potential Rs 0 bug:
    - With real chain quotes (or implied IV calibration), Bull Call Spread produces positive payoff.
    - Legacy/broken zero-profit debit spreads are omitted from Telegram spread boxes cleanly.
    """
    from types import SimpleNamespace as _NS
    from bot.alert_templates import render_auto_alert
    from engine.auto_alert_engine import AutoAlert
    from engine.defined_risk_spreads import build_defined_risk_spread

    fake_chain = [
        _NS(
            symbol="MCX:CRUDEOIL26DEC8000CE",
            option_type="CE",
            strike=8000.0,
            last_price=359.0,
            expiry="2026-12-29",
        ),
        _NS(
            symbol="MCX:CRUDEOIL26DEC8100CE",
            option_type="CE",
            strike=8100.0,
            last_price=297.2,
            expiry="2026-12-29",
        ),
        _NS(
            symbol="MCX:CRUDEOIL26DEC8200CE",
            option_type="CE",
            strike=8200.0,
            last_price=260.7,
            expiry="2026-12-29",
        ),
    ]
    with patch("market.options.get_options_chain", return_value=fake_chain):
        spread = build_defined_risk_spread(
            underlying="CRUDEOIL",
            spot_price=7989.0,
            strategy="BULL_CALL_SPREAD",
            dte=32,
            lot_size=100,
            primary_strike=8000.0,
            primary_premium=359.0,
            expiry_date="2026-12-29",
        )
    assert spread.max_profit > 0
    assert spread.risk_reward_ratio > 0.25
    assert spread.net_debit_or_credit < (spread.legs[1].strike - spread.legs[0].strike) * 100

    # Also test BS implied-IV fallback when chain lookup returns empty
    with patch("market.options.get_options_chain", return_value=[]):
        spread_fb = build_defined_risk_spread(
            underlying="CRUDEOIL",
            spot_price=7989.0,
            strategy="BULL_CALL_SPREAD",
            dte=32,
            lot_size=100,
            primary_strike=8000.0,
            primary_premium=359.0,
        )
    assert spread_fb.max_profit > 0
    assert spread_fb.risk_reward_ratio > 0.25

    # Broken zero-profit spread must never render 'Max Profit Potential: ₹0'
    broken_alert = AutoAlert(
        alert_id="aa-crude-broken-spread-test",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="CRUDEOIL",
        exchange="MCX",
        direction="BULLISH",
        headline="MCX OPTION: CRUDEOIL 8000 CE",
        summary="Test",
        ltp=359.0,
        trigger_level=359.0,
        target_level=552.8,
        stop_loss=294.4,
        strike=8000.0,
        option_type="CE",
        contract_symbol="MCX:CRUDEOIL26DEC8000CE",
        expiry_date="2026-12-29",
        confidence=85,
        metrics={"segment": "COMMODITY", "rvol": 1.5},
        actionable_plan={
            "hedged_spread": {
                "strategy": "BULL_CALL_SPREAD",
                "legs": [
                    {"option_type": "CE", "strike": 8000.0, "side": "BUY", "premium": 359.0},
                    {"option_type": "CE", "strike": 8100.0, "side": "SELL", "premium": 28.0},
                ],
                "net_debit_per_share": 331.0,
                "max_loss": 33100.0,
                "max_profit": 0.0,
                "risk_reward": "1:0.0",
            },
            "setup_confluence": "Global Crude Surge (Brent & WTI > +1%) + Dip Reclaim at 15m 50-EMA",
        },
    )
    rendered = render_auto_alert(broken_alert)
    assert "Max Profit Potential" not in rendered
    assert "+ Dip," not in rendered
