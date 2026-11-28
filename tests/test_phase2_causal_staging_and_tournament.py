"""Phase 2 tests: Causal WATCH->ARMED->TRIGGERED state machine, Internals Gate, and Tournament."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from config.constants import IST
from engine.detector_tournament import (
    load_tournament_report,
    run_detector_tournament,
    save_tournament_report,
)
from engine.level_state_machine import (
    ArmedRadarStore,
    evaluate_symbol_stage,
)


def _make_5m_bars(closes: list[float], *, start: str = "2026-11-27 09:15") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="5min")
    arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": arr - 2.0,
            "high": arr + 6.0,
            "low": arr - 6.0,
            "close": arr,
            "volume": np.full(len(closes), 25_000.0),
        },
        index=idx,
    )


def test_level_state_machine_prefix_invariance():
    """Same prefix must yield identical staging regardless of wildly mutated future bars."""
    base_closes = [25000.0 + (i % 3) * 3.0 for i in range(20)] + [25090.0]
    df_a = _make_5m_bars(base_closes + [25300.0, 25500.0, 25600.0])
    df_b = _make_5m_bars(base_closes + [24500.0, 24200.0, 24000.0])
    dl = {"pdh": 25100.0, "pdl": 24800.0, "pdc": 24950.0}
    ref_dt = datetime(2026, 11, 27, 10, 55, tzinfo=IST)

    st_a = evaluate_symbol_stage("NIFTY", df_a.iloc[:21], daily_levels=dl, as_of=ref_dt)
    st_b = evaluate_symbol_stage("NIFTY", df_b.iloc[:21], daily_levels=dl, as_of=ref_dt)
    assert st_a is not None and st_b is not None
    assert st_a.to_dict() == st_b.to_dict()


def test_causal_watch_armed_triggered_and_expired_stalk_transitions():
    dl = {"pdh": 25100.0, "pdl": 24800.0, "pdc": 24950.0}
    # Steady 5m ATR (~12 pts) approaching PDH (25100) without artificial gap spikes
    base = [25050.0 + i * 1.5 for i in range(19)]  # ends at 25077.0, VWAP ~ 25064

    # 1. WATCH: ~0.79 ATR below PDH (outside 0.55 coiling ARMED band, inside 0.90 WATCH)
    df_watch = _make_5m_bars(base + [25088.0, 25090.5])
    st_watch = evaluate_symbol_stage("NIFTY", df_watch, daily_levels=dl)
    assert st_watch is not None
    assert st_watch.stage == "WATCH"
    assert st_watch.anchor_name == "PDH"

    # 2. ARMED: within <= 0.35 ATR of PDH
    df_armed = _make_5m_bars(base + [25094.0, 25097.5])
    st_armed = evaluate_symbol_stage("NIFTY", df_armed, daily_levels=dl, previous_state=st_watch)
    assert st_armed is not None
    assert st_armed.stage == "ARMED"
    assert st_armed.armed_at is not None

    # 3. TRIGGERED: price crosses PDH and last two 5S bars hold above PDH with aligned CVD
    df_trig = _make_5m_bars(base + [25097.5, 25103.0])
    sec_idx = pd.date_range("2026-11-27 10:54:50", periods=4, freq="5s")
    df_sec = pd.DataFrame(
        {
            "open": [25098.0, 25100.0, 25101.5, 25102.5],
            "high": [25100.5, 25102.0, 25103.5, 25104.0],
            "low": [25097.5, 25099.5, 25100.5, 25101.5],
            "close": [25099.5, 25101.0, 25102.5, 25103.0],
            "volume": [500.0, 800.0, 1200.0, 1500.0],
        },
        index=sec_idx,
    )
    cvd_ok = SimpleNamespace(sample_count=12, cvd_divergence="ALIGNED", cvd_bias="BULLISH")
    st_trig = evaluate_symbol_stage(
        "NIFTY",
        df_trig,
        bars_seconds=df_sec,
        daily_levels=dl,
        cvd_metrics=cvd_ok,
        previous_state=st_armed,
    )
    assert st_trig is not None
    assert st_trig.stage == "TRIGGERED"
    assert "SECONDS_BAR_ACCEPTANCE" in st_trig.confirmation_reasons

    # 4. EXPIRED_STALK: extended well past no_chase_atr
    df_ext = _make_5m_bars(base + [25097.5, 25135.0])
    st_ext = evaluate_symbol_stage("NIFTY", df_ext, daily_levels=dl)
    assert st_ext is not None
    assert st_ext.stage == "EXPIRED_STALK"


def test_head_fake_divergence_vetoes_index_breakout_in_state_machine_and_policy():
    dl = {"pdh": 25100.0, "pdl": 24800.0, "pdc": 24950.0}
    base = [25000.0 + (i % 2) * 2.0 for i in range(19)]
    df_trig = _make_5m_bars(base + [25097.5, 25103.0])
    head_fake = SimpleNamespace(
        status="AVAILABLE",
        index="NIFTY",
        regime="HEAD_FAKE_DIVERGENCE",
        change_pct=0.35,
        ad_ratio=0.3,
        pct_above_vwap=25.0,
    )

    st_vetoed = evaluate_symbol_stage(
        "NIFTY",
        df_trig,
        daily_levels=dl,
        internals_report=head_fake,
        reversal_mode=False,
    )
    assert st_vetoed is not None
    assert st_vetoed.stage == "VETOED"
    assert "INDEX_HEAD_FAKE_DIVERGENCE" in st_vetoed.veto_reasons

    # SignalPolicy gate B0c tests: blocks when AVAILABLE HEAD_FAKE_DIVERGENCE, skips when UNAVAILABLE
    from engine.alert_model import AutoAlert
    from engine.signal_policy import build_policy_context_from_alert, evaluate_candidate_policy

    alert = AutoAlert(
        alert_id="aa-index_call_setup-nifty-20261127",
        alert_type="INDEX_CALL_SETUP",
        stage="PRIMED",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26DEC25100CE",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="NIFTY Call Breakout",
        summary="Breakout above PDH VWAP",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=220.0,
        confidence=85,
        is_live=True,
        environment="PAPER",
        metrics={"signals": ["PDH_BREAKOUT", "VWAP_RECLAIM"], "rvol": 1.8},
    )
    ctx = build_policy_context_from_alert(alert)
    with (
        patch(
            "engine.signal_policy.alert_scrutiny_auditor.verify_tier1_sanity",
            return_value=(True, "", []),
        ),
        patch(
            "engine.signal_policy.evaluate_institutional_quality_gate",
            return_value=SimpleNamespace(
                is_vetoed=False,
                veto_reason="",
                conviction_tier="HIGH_CONVICTION",
                execution_mandate="STANDARD",
                metrics={},
            ),
        ),
        patch("engine.market_internals.compute_index_internals", return_value=head_fake),
    ):
        res_veto = evaluate_candidate_policy(ctx, alert)
        assert res_veto.decision == "REJECT"
        assert res_veto.blocking_gate is not None
        assert res_veto.blocking_gate.gate_name == "INDEX_INTERNALS_HEAD_FAKE_GATE"


def test_armed_radar_covers_index_and_stock_fno_respecting_discovery_policy(monkeypatch):
    monkeypatch.setenv("SESSION_FOCUS_MODE", "FNO_ONLY")
    radar = ArmedRadarStore()
    base = [25000.0] * 19
    df_nifty = _make_5m_bars(base + [25092.5, 25097.5])
    df_rel = _make_5m_bars([1350.0] * 19 + [1361.0, 1363.0])
    df_btc = _make_5m_bars([95000.0] * 19 + [95200.0, 95300.0])

    updated = radar.evaluate_universe(
        ["NIFTY", "RELIANCE", "BTCUSDT"],
        ohlcv_5m_map={"NIFTY": df_nifty, "RELIANCE": df_rel, "BTCUSDT": df_btc},
        daily_levels_map={
            "NIFTY": {"pdh": 25100.0, "pdl": 24800.0, "pdc": 24950.0},
            "RELIANCE": {"pdh": 1365.0, "pdl": 1330.0, "pdc": 1345.0},
        },
    )
    syms = {u.symbol: u.asset_class for u in updated}
    assert syms.get("NIFTY") == "INDEX"
    assert syms.get("RELIANCE") == "STOCK_FNO"
    assert "BTCUSDT" not in syms
    assert len(radar.snapshot()) == 2


def test_detector_tournament_runs_purged_ablation_and_enforces_uncalibrated_contract(
    tmp_path: Path,
):
    rng = np.random.default_rng(11)
    n = 160
    idx = pd.date_range("2026-11-20 09:15", periods=n, freq="5min")
    t = np.arange(n, dtype=float)
    nifty_c = 25000.0 + 70.0 * np.sin(t / 5.0) + rng.normal(0.0, 6.0, size=n)
    rel_c = 1350.0 + 12.0 * np.sin(t / 4.0) + rng.normal(0.0, 1.5, size=n)

    def _to_df(c_arr: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": c_arr - 1.5,
                "high": c_arr + 6.0,
                "low": c_arr - 6.0,
                "close": c_arr,
                "volume": rng.integers(10_000, 60_000, size=n).astype(float),
            },
            index=idx,
        )

    report = run_detector_tournament(
        {"NIFTY": _to_df(nifty_c), "RELIANCE": _to_df(rel_c)},
        detectors=("ORB_BREAKOUT", "VWAP_PULLBACK", "FAILED_SWEEP_REVERSAL"),
    )
    assert report["provenance"] == "RESEARCH_ONLY_PURGED_WALK_FORWARD"
    assert report["delay_bars"] == 1
    assert set(report["symbols_evaluated"]) == {"NIFTY", "RELIANCE"}

    for det_stats in report["detectors"].values():
        assert "INDEX" in det_stats["by_asset_class"]
        assert "STOCK_FNO" in det_stats["by_asset_class"]
        if det_stats["trades"] < 30 or det_stats["losses"] == 0:
            assert det_stats["status"] == "UNCALIBRATED"
            assert det_stats["governance"] == "UNCALIBRATED"

    out_path = save_tournament_report(report, path=tmp_path / "tournament_report.json")
    loaded = load_tournament_report(path=out_path)
    assert loaded["provenance"] == "RESEARCH_ONLY_PURGED_WALK_FORWARD"
