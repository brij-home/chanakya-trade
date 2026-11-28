"""
tests/test_multi_profile_tournament_and_hardening.py
────────────────────────────────────────────────────
Tests for Track 1-4 remaining items:
  1. Multi-profile Purged Walk-Forward Tournament (`FUTURES_5M_SCALP`, `FUTURES_15M_SWING`,
     `OPTIONS_ATM_EQUIVALENT` including explicit expired-option tape replay).
  2. WsSubscriptionManager purpose classification & legacy retention (`retained_out_of_scope_symbols`).
  3. Exchange depth capability differentiation (`NSE`/`NFO` 50-depth TBT vs `BSE`/`BFO` 5-level).
  4. Telegram `/quantradar` and `/readiness` read-only commands.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.constants import IST


def test_multi_profile_tournament_compares_scalp_swing_and_options():
    from engine.detector_tournament import run_multi_profile_tournament

    rng = np.random.default_rng(77)
    n = 260
    idx = pd.date_range("2026-11-10 09:15", periods=n, freq="5min")
    t = np.arange(n, dtype=float)
    nifty_c = 25000.0 + 130.0 * np.sin(t / 6.0) + rng.normal(0.0, 6.0, size=n)
    nifty_df = pd.DataFrame(
        {
            "open": nifty_c - 2.0,
            "high": nifty_c + 10.0,
            "low": nifty_c - 10.0,
            "close": nifty_c,
            "volume": rng.integers(30_000, 120_000, size=n).astype(float),
        },
        index=idx,
    )
    opt_c = 180.0 + 18.0 * np.sin(t / 6.0) + rng.normal(0.0, 2.0, size=n)
    opt_df = pd.DataFrame(
        {
            "open": opt_c - 1.5,
            "high": opt_c + 4.5,
            "low": opt_c - 4.5,
            "close": opt_c,
            "volume": rng.integers(20_000, 90_000, size=n).astype(float),
        },
        index=idx,
    )

    # 1. Proxy options mode
    proxy_res = run_multi_profile_tournament(
        {"NIFTY": nifty_df},
        detectors=("ORB_BREAKOUT", "LEVEL_ARMED_TRIGGER"),
        collect_meta_samples=True,
    )
    assert set(proxy_res["profiles"].keys()) == {
        "FUTURES_5M_SCALP",
        "FUTURES_15M_SWING",
        "OPTIONS_ATM_EQUIVALENT",
    }
    assert (
        proxy_res["profiles"]["OPTIONS_ATM_EQUIVALENT"]["provenance"]
        == "RESEARCH_PROXY_ATM_DELTA_055"
    )
    assert isinstance(proxy_res["meta_samples"], list)

    # 2. Authentic expired option OHLC tape mode
    tape_res = run_multi_profile_tournament(
        {"NIFTY": nifty_df},
        expired_option_bars_by_symbol={"NIFTY": opt_df},
        detectors=("VWAP_PULLBACK",),
    )
    assert tape_res["profiles"]["OPTIONS_ATM_EQUIVALENT"]["provenance"] == "EXPIRED_OPTION_TAPE"


def test_ws_subscription_purpose_reconciliation_and_bse_depth_capability(
    monkeypatch, tmp_path: Path
):
    from market.fyers_tbt_manager import get_exchange_depth_capability
    from market.ws_subscription_manager import WsSubscriptionManager

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")

    mgr = WsSubscriptionManager(max_subscriptions=500)
    mgr._core_symbols.add("BINANCE:BTCUSDT")
    mgr._dynamic_symbols["NSE:NIFTY26DEC25000CE"] = 1.0
    mgr._dynamic_symbols["NSE:RELIANCE-EQ"] = 1.0

    purposes = mgr.reconcile_subscription_purposes(
        active_exposure_symbols=["NSE:NIFTY26DEC25000CE"]
    )
    assert purposes["NSE:NIFTY26DEC25000CE"] == "EXPOSURE"
    assert purposes["BINANCE:BTCUSDT"] == "UNKNOWN_LEGACY"
    assert purposes["NSE:RELIANCE-EQ"] == "FNO_STOCK"

    diag = mgr.get_diagnostics()
    assert "BINANCE:BTCUSDT" in diag["retained_out_of_scope_symbols"]
    assert diag["by_purpose"]["EXPOSURE"] >= 1
    assert diag["by_purpose"]["UNKNOWN_LEGACY"] >= 1

    # BFO / BSE vs NFO / NSE depth capability clarity
    bse_cap = get_exchange_depth_capability("BSE:SENSEX26DEC80000CE")
    nse_cap = get_exchange_depth_capability("NSE:NIFTY26DEC25000CE")
    assert bse_cap["supports_50_depth_tbt"] is False
    assert bse_cap["feed_mode"] == "DATASOCKET_5_LEVEL"
    assert nse_cap["supports_50_depth_tbt"] is True
    assert nse_cap["feed_mode"] == "TBT_50_LEVEL"


def test_telegram_quantradar_and_readiness_commands(monkeypatch, tmp_path: Path):
    from bot.telegram_bot import cmd_quantradar, cmd_readiness
    from engine.level_state_machine import LevelStageState

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)
    monkeypatch.setenv("TRADING_MODE", "PAPER")

    sent: list[str] = []

    class _FakeMsg:
        async def reply_text(self, text: str, **kwargs):
            sent.append(text)

    fake_update = SimpleNamespace(effective_message=_FakeMsg(), message=_FakeMsg())

    monkeypatch.setattr(
        "engine.level_state_machine.armed_radar.snapshot",
        lambda: [
            LevelStageState(
                symbol="NIFTY",
                asset_class="INDEX",
                stage="ARMED",
                direction="BULLISH",
                anchor_name="PDH",
                anchor_price=25100.0,
                spot=25096.0,
                atr_14=18.0,
                distance_atr=0.22,
                extension_atr=0.0,
                stop_loss=25075.0,
                target_1=25150.0,
                no_chase_boundary=25108.0,
                first_seen_at=datetime(2026, 11, 27, 10, 0, tzinfo=IST).isoformat(),
                updated_at=datetime(2026, 11, 27, 10, 5, tzinfo=IST).isoformat(),
            ).to_dict()
        ],
    )

    async def _run() -> None:
        await cmd_quantradar(fake_update, None)
        await cmd_readiness(fake_update, None)

    asyncio.run(_run())
    assert len(sent) == 2
    assert "Quant Armed Radar" in sent[0]
    assert "NIFTY" in sent[0]
    assert "Operational Readiness" in sent[1]
    assert "PAPER" in sent[1]
