"""
tests/test_phase3_iv_optimizer_catalysts_cas.py
────────────────────────────────────────────────
Regression & contract tests for Phase 3:
  1. Constant-tenor 7D/30D IV Surface, Term Slope, Yang-Zhang RV, VRP & TickWarehouse integration.
  2. Strict listed-contract Options Optimizer (NSE/BSE), IV/GEX/Event structure routing.
  3. Honest Participant OI UNAVAILABLE behavior (no hardcoded baseline fallback).
  4. Stock F&O As-Of Event Shield, PEAD/SEPA, 4-Quadrant FutOI x Delivery%, MWPL gate.
  5. Effective-dated Dec-7 CAS Dispersion Window & Expiry Closing VWAP settlement tracking.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.constants import IST


def test_iv_surface_constant_7d_30d_vrp_and_warehouse_honest_iv_rank(monkeypatch, tmp_path):
    from engine.iv_surface import build_iv_surface_from_warehouse
    from engine.tick_warehouse import TickWarehouse
    import engine.tick_warehouse as tw_mod

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(tw_mod, "_GLOBAL_WAREHOUSE", TickWarehouse(base_dir=tmp_path / "ticks"))

    wh = tw_mod.get_tick_warehouse()
    snap_dt = datetime(2026, 11, 27, 14, 15, tzinfo=IST)
    ts_ms = int(snap_dt.timestamp() * 1000)

    contracts = [
        {
            "symbol": "NSE:NIFTY26DEC25000CE",
            "expiry": "2026-12-01",
            "strike": 25000.0,
            "option_type": "CE",
            "last_price": 125.0,
            "bid": 124.5,
            "ask": 125.5,
            "oi": 500000,
            "oi_change": 25000,
            "volume": 900000,
            "iv": 15.2,
            "delta": 0.51,
        },
        {
            "symbol": "NSE:NIFTY26DEC25000PE",
            "expiry": "2026-12-01",
            "strike": 25000.0,
            "option_type": "PE",
            "last_price": 118.0,
            "bid": 117.5,
            "ask": 118.5,
            "oi": 600000,
            "oi_change": 40000,
            "volume": 850000,
            "iv": 15.6,
            "delta": -0.49,
        },
        {
            "symbol": "NSE:NIFTY26DEC24600PE",
            "expiry": "2026-12-01",
            "strike": 24600.0,
            "option_type": "PE",
            "last_price": 42.0,
            "bid": 41.5,
            "ask": 42.5,
            "oi": 800000,
            "oi_change": 60000,
            "volume": 400000,
            "iv": 18.0,
            "delta": -0.25,
        },
        {
            "symbol": "NSE:NIFTY26DEC25400CE",
            "expiry": "2026-12-01",
            "strike": 25400.0,
            "option_type": "CE",
            "last_price": 39.0,
            "bid": 38.5,
            "ask": 39.5,
            "oi": 750000,
            "oi_change": 55000,
            "volume": 380000,
            "iv": 13.8,
            "delta": 0.25,
        },
        {
            "symbol": "NSE:NIFTY26DEC25000CE_NEXT",
            "expiry": "2026-12-29",
            "strike": 25000.0,
            "option_type": "CE",
            "last_price": 310.0,
            "oi": 300000,
            "volume": 120000,
            "iv": 16.5,
            "delta": 0.52,
        },
        {
            "symbol": "NSE:NIFTY26DEC25000PE_NEXT",
            "expiry": "2026-12-29",
            "strike": 25000.0,
            "option_type": "PE",
            "last_price": 295.0,
            "oi": 310000,
            "volume": 110000,
            "iv": 16.9,
            "delta": -0.48,
        },
    ]
    written = wh.record_option_chain_snapshot(
        "NIFTY", contracts, spot=25010.0, vix=14.9, timestamp_ms=ts_ms
    )
    assert written == 6

    # Build 25 daily OHLCV bars for realized volatility
    dates = pd.date_range("2026-10-20", periods=25, freq="B")
    rng = np.random.default_rng(7)
    close_arr = 24800.0 + np.cumsum(rng.normal(5.0, 90.0, size=len(dates)))
    daily_df = pd.DataFrame(
        {
            "open": close_arr - 30.0,
            "high": close_arr + 95.0,
            "low": close_arr - 95.0,
            "close": close_arr,
            "volume": np.full(len(dates), 1_000_000.0),
        },
        index=dates,
    )

    date_str = snap_dt.strftime("%Y-%m-%d")
    surf = build_iv_surface_from_warehouse("NIFTY", ohlcv_daily=daily_df, date_str=date_str)
    assert surf.status == "AVAILABLE"
    assert surf.atm_iv_30d is not None and surf.atm_iv_30d > 10.0
    assert surf.atm_iv_7d is not None and surf.atm_iv_7d > 10.0
    assert surf.term_structure_slope is not None and surf.term_structure_slope > 0.0
    assert surf.skew_25d is not None and surf.skew_25d > 0.0
    assert surf.realized_vol_20d is not None and surf.realized_vol_20d > 0.0
    assert surf.vrp == round(surf.atm_iv_30d - surf.realized_vol_20d, 4)

    # Contract #26: < 20 authentic IV sessions -> IV Rank MUST remain None (never RV substitution)
    assert surf.iv_rank is None
    assert surf.iv_percentile is None
    assert surf.iv_rank_depth_status == "INSUFFICIENT (<20)"


def test_listed_options_optimizer_enforces_master_and_routes_structures():
    from engine.options_optimizer import optimize_listed_option_contract
    from market.contract_selection import ListedContract

    as_of_dt = datetime(2026, 11, 27, 10, 30, tzinfo=IST)
    exp = date(2026, 12, 3)

    # 1. Fail-closed when master has zero listed contracts
    unavail = optimize_listed_option_contract(
        "SENSEX",
        "BULLISH",
        spot=80100.0,
        listed_contracts=[],
        iv=0.16,
        as_of=as_of_dt,
    )
    assert unavail.status == "UNAVAILABLE"
    assert unavail.contract_symbol == ""

    # 2. Listed BSE SENSEX option grid
    listed = [
        ListedContract("BSE:SENSEX26D0380000CE", "SENSEX", exp, "CE", 80000.0, 20, 0.05, "tok1"),
        ListedContract("BSE:SENSEX26D0380100CE", "SENSEX", exp, "CE", 80100.0, 20, 0.05, "tok2"),
        ListedContract("BSE:SENSEX26D0380200CE", "SENSEX", exp, "CE", 80200.0, 20, 0.05, "tok3"),
        ListedContract("BSE:SENSEX26D0380300CE", "SENSEX", exp, "CE", 80300.0, 20, 0.05, "tok4"),
        ListedContract("BSE:SENSEX26D0380100PE", "SENSEX", exp, "PE", 80100.0, 20, 0.05, "tok5"),
    ]
    chain = [
        {
            "strike": 80000.0,
            "option_type": "CE",
            "expiry": "2026-12-03",
            "last_price": 410.0,
            "bid": 408.0,
            "ask": 412.0,
            "iv": 14.5,
        },
        {
            "strike": 80100.0,
            "option_type": "CE",
            "expiry": "2026-12-03",
            "last_price": 340.0,
            "bid": 338.0,
            "ask": 342.0,
            "iv": 14.4,
        },
        {
            "strike": 80200.0,
            "option_type": "CE",
            "expiry": "2026-12-03",
            "last_price": 275.0,
            "bid": 273.0,
            "ask": 277.0,
            "iv": 14.3,
        },
        {
            "strike": 80300.0,
            "option_type": "CE",
            "expiry": "2026-12-03",
            "last_price": 220.0,
            "bid": 218.0,
            "ask": 222.0,
            "iv": 14.2,
        },
    ]

    # Negative GEX + low/normal IV -> NAKED_BUY on exact BSE listed ticker
    naked = optimize_listed_option_contract(
        "SENSEX",
        "BULLISH",
        spot=80110.0,
        regime="MOMENTUM_BREAKOUT",
        listed_contracts=listed,
        option_chain=chain,
        iv_snapshot=SimpleNamespace(
            status="AVAILABLE",
            atm_iv_30d=14.4,
            iv_rank=None,
            iv_percentile=None,
            vrp=1.2,
            skew_25d=0.05,
        ),
        gex_regime="NEGATIVE_GEX",
        as_of=as_of_dt,
    )
    assert naked.status == "AVAILABLE"
    assert naked.resolved_from_master is True
    assert naked.exchange == "BSE"
    assert naked.lot_size == 20
    assert naked.contract_symbol.startswith("BSE:SENSEX26D03")
    assert naked.execution_structure == "NAKED_BUY"
    assert naked.iv_rank is None  # Never synthesized
    assert naked.bid_ask_spread_pct is not None and naked.bid_ask_spread_pct < 2.0

    # Event crush window -> VERTICAL_DEBIT_SPREAD using listed hedge contract
    spread = optimize_listed_option_contract(
        "SENSEX",
        "BULLISH",
        spot=80110.0,
        regime="MOMENTUM_BREAKOUT",
        listed_contracts=listed,
        option_chain=chain,
        iv_snapshot=SimpleNamespace(
            status="AVAILABLE",
            atm_iv_30d=14.4,
            iv_rank=None,
            iv_percentile=None,
            vrp=1.2,
            skew_25d=0.05,
        ),
        is_event_window=True,
        as_of=as_of_dt,
    )
    assert spread.execution_structure == "VERTICAL_DEBIT_SPREAD"
    assert spread.hedge_contract_symbol in {c.symbol for c in listed}
    assert spread.hedge_strike > spread.strike
    assert spread.max_loss is not None and spread.max_loss > 0


def test_participant_oi_returns_explicit_unavailable_when_archive_missing(monkeypatch, tmp_path):
    import market.participant_oi as poi_mod

    monkeypatch.setattr(poi_mod, "CACHE_FILE", tmp_path / "missing_poi.json")

    class _FailClient:
        def get(self, *args, **kwargs):
            raise RuntimeError("NSE offline")

    monkeypatch.setattr(poi_mod, "get_nse_client", lambda: _FailClient())

    summary = poi_mod.fetch_and_cache_participant_oi()
    assert summary.status == "UNAVAILABLE"
    assert summary.provenance == "UNAVAILABLE"
    assert summary.as_of_date == ""
    assert summary.fii_index_long_ratio == 0.0


def test_stock_fno_catalysts_pead_delivery_mwpl_and_signal_policy_ban_gate(monkeypatch):
    from engine.alert_model import AutoAlert
    from engine.signal_policy import build_policy_context_from_alert, evaluate_candidate_policy
    from engine.stock_fno_catalysts import (
        assess_event_risk_shield,
        build_fno_catalyst_watchlist,
        classify_fut_oi_delivery_matrix,
        evaluate_mwpl_squeeze_state,
    )
    from market.earnings import EarningsEntry

    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")

    # 1. As-of Event Risk Shield: prevents lookahead of future filings while flagging known results
    as_of_dt = datetime(2026, 11, 27, 10, 0, tzinfo=IST)
    entries = [
        EarningsEntry(
            symbol="RELIANCE",
            result_date="2026-11-28",
            first_seen_at="2026-11-20T09:00:00+05:30",
        ),
        EarningsEntry(
            symbol="INFY",
            result_date="2026-11-28",
            first_seen_at="2026-11-28T08:00:00+05:30",  # Future relative to as_of_dt
        ),
    ]
    shield_rel = assess_event_risk_shield("RELIANCE", as_of=as_of_dt, earnings_entries=entries)
    shield_infy = assess_event_risk_shield("INFY", as_of=as_of_dt, earnings_entries=entries)
    assert shield_rel.event_iv_crush_risk is True
    assert shield_rel.recommended_structure == "VERTICAL_DEBIT_SPREAD"
    assert shield_infy.event_iv_crush_risk is False

    # 2. 4-Quadrant Fut OI x Delivery %
    missing_mat = classify_fut_oi_delivery_matrix(
        "RELIANCE", price_change_pct=1.8, fut_oi_change_pct=6.5, delivery_pct=None
    )
    assert missing_mat.status == "UNAVAILABLE"

    accum_mat = classify_fut_oi_delivery_matrix(
        "RELIANCE",
        price_change_pct=2.1,
        fut_oi_change_pct=8.4,
        delivery_pct=62.0,
        delivery_avg_20d=41.0,
        spot_price=1400.0,
        fut_price=1405.5,
    )
    assert accum_mat.quadrant == "INSTITUTIONAL_ACCUMULATION"
    assert accum_mat.fut_basis_bps > 0

    fragile_mat = classify_fut_oi_delivery_matrix(
        "SBIN",
        price_change_pct=1.4,
        fut_oi_change_pct=-5.2,
        delivery_pct=26.0,
        delivery_avg_20d=38.0,
    )
    assert fragile_mat.quadrant == "FRAGILE_SHORT_COVERING"

    # 3. MWPL Squeeze & Ban Gate
    assert evaluate_mwpl_squeeze_state("NIFTY").regime == "INDEX_EXEMPT"
    squeeze = evaluate_mwpl_squeeze_state(
        "SAIL",
        mwpl_pct_override=89.5,
        price_change_pct=1.6,
        breaking_resistance=True,
        now_dt=as_of_dt,
    )
    assert squeeze.regime == "PRE_BAN_SHORT_SQUEEZE"
    assert squeeze.allow_fresh_directional is True

    late_lock = evaluate_mwpl_squeeze_state(
        "SAIL", mwpl_pct_override=92.5, now_dt=datetime(2026, 11, 27, 14, 40, tzinfo=IST)
    )
    assert late_lock.regime == "LATE_BAN_LOCK_RISK"
    assert late_lock.allow_fresh_directional is False

    # 4. SignalPolicy Gate B0d: reject banned Stock F&O fresh entry
    monkeypatch.setattr("market.fno_ban.is_in_fno_ban", lambda sym: sym.upper() == "SAIL")
    monkeypatch.setattr(
        "market.fno_ban.get_mwpl_utilization", lambda sym: 96.4 if sym.upper() == "SAIL" else 40.0
    )
    monkeypatch.setattr(
        "engine.signal_policy.alert_scrutiny_auditor.verify_tier1_sanity",
        lambda *a, **k: (True, "", []),
    )
    monkeypatch.setattr(
        "engine.signal_policy.evaluate_institutional_quality_gate",
        lambda *a, **k: SimpleNamespace(
            is_vetoed=False,
            veto_reason="",
            conviction_tier="HIGH_CONVICTION",
            execution_mandate="STANDARD",
            metrics={},
        ),
    )

    alert = AutoAlert(
        alert_id="aa-breakout_retest-sail-20261127",
        alert_type="BREAKOUT_RETEST",
        stage="PRIMED",
        symbol="SAIL",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="SAIL Breakout",
        summary="SAIL breakout above resistance",
        ltp=125.0,
        trigger_level=125.0,
        stop_loss=120.0,
        target_level=140.0,
        confidence=78,
        metrics={"rvol": 2.4},
        details={},
        environment="PAPER",
        is_live=True,
    )
    ctx = build_policy_context_from_alert(alert)
    pol = evaluate_candidate_policy(ctx, alert)
    assert pol.decision == "REJECT"
    assert pol.blocking_gate is not None
    assert pol.blocking_gate.gate_name == "STOCK_FNO_MWPL_BAN_GATE"
    assert any(
        v.gate_name == "STOCK_FNO_MWPL_BAN_GATE" and v.status == "REJECT" for v in pol.gate_verdicts
    )

    # 5. Ranked Watchlist excludes banned/crypto and prioritizes institutional accumulation + SEPA
    ranked = build_fno_catalyst_watchlist(
        [
            {
                "symbol": "RELIANCE",
                "fundamental": SimpleNamespace(
                    sepa_qualified=True,
                    eps_q1_growth=32.0,
                    eps_acceleration=11.0,
                    revenue_q1_growth=19.0,
                ),
                "forensic_verdict": "CLEAN",
                "post_earnings_surprise": "BEAT",
                "tod_rvol": 2.3,
                "above_avwap": True,
                "price_change_pct": 2.2,
                "fut_oi_change_pct": 7.5,
                "delivery_pct": 61.0,
                "delivery_avg_20d": 40.0,
                "mwpl_pct": 45.0,
            },
            {
                "symbol": "SAIL",
                "mwpl_pct": 96.4,
                "price_change_pct": 3.0,
            },
            {
                "symbol": "BTCUSDT",
                "price_change_pct": 4.0,
            },
        ],
        as_of=as_of_dt,
    )
    syms = [r["symbol"] for r in ranked]
    assert "RELIANCE" in syms
    assert "SAIL" not in syms
    assert "BTCUSDT" not in syms


def test_cas_dispersion_and_expiry_vwap_schedule_boundary():
    from engine.cas_dispersion import assess_cas_dispersion_regime, assess_expiry_vwap_tracking

    # 1. Pre-Dec 7 (today 2026-11-27): CAS derivative dispersion window MUST stay inactive
    pre_dt = datetime(2026, 11, 27, 15, 35, tzinfo=IST)
    pre_reg = assess_cas_dispersion_regime(
        "RELIANCE", spot=1400.0, future_price=1405.0, as_of=pre_dt
    )
    assert pre_reg["is_cas_dispersion_window"] is False
    assert pre_reg["segment_close"] == "15:40:00"

    # 2. Post-Dec 7 (2026-12-08): non-expiring derivative dispersion 15:25-15:45 active, 15:45 close
    post_rel_dt = datetime(2026, 12, 8, 15, 35, tzinfo=IST)
    post_rel = assess_cas_dispersion_regime(
        "RELIANCE", spot=1400.0, future_price=1404.0, as_of=post_rel_dt, is_expiry=False
    )
    assert post_rel["is_cas_window"] is True
    assert post_rel["is_cas_dispersion_window"] is True
    assert post_rel["segment_close"] == "15:45:00"
    assert post_rel["dispersion_signal"] == "PREMIUM_EXPANSION"

    # 3. Post-Dec 7 expiring NIFTY index at 15:26 IST: closes 15:30, blocks fresh entries
    exp_dt = datetime(2026, 12, 8, 15, 26, tzinfo=IST)
    exp_reg = assess_cas_dispersion_regime("NIFTY", spot=25100.0, as_of=exp_dt, is_expiry=True)
    assert exp_reg["segment_close"] == "15:30:00"
    assert exp_reg["allow_new_entry"] is False
    assert exp_reg["dispersion_signal"] == "EXPIRING_INDEX_CLOSING_1530"

    # 4. 15:00-15:30 Expiry Closing VWAP settlement tracking error
    bars_idx = pd.date_range("2026-12-08 15:00:00", periods=6, freq="5min")
    bars_df = pd.DataFrame(
        {
            "open": [25000.0] * 6,
            "high": [25010.0] * 6,
            "low": [24990.0] * 6,
            "close": [25000.0] * 6,
            "volume": [100_000.0] * 6,
        },
        index=bars_idx,
    )
    vwap_res = assess_expiry_vwap_tracking(
        "NIFTY",
        spot=25080.0,
        bars_intraday=bars_df,
        as_of=exp_dt,
        is_expiry=True,
        gex_pin_strike=25000.0,
    )
    assert vwap_res["in_closing_vwap_window"] is True
    assert vwap_res["settlement_vwap"] == 25000.0
    assert vwap_res["tracking_error_bps"] > 20.0
    assert vwap_res["drift_flag"] == "VWAP_SETTLEMENT_DRIFT_HIGH"
    assert vwap_res["gex_pin_aligned"] is True
