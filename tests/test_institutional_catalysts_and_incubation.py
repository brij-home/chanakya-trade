"""
tests/test_institutional_catalysts_and_incubation.py
────────────────────────────────────────────────────
Unit & integration tests for:
  1. Institutional Credit Rating Upgrades (CRISIL, ICRA, CARE) & Shareholding Dynamics
  2. Multi-Horizon classification (SHORT_TERM, MID_TERM, LONG_TERM)
  3. Cycle Incubation Pipeline (Persistence, Lifecycle Evaluation, Auto-Triggering)
  4. FastAPI Endpoints (/skills/incubation_pipeline, /skills/incubation_add, /skills/institutional_catalysts)
"""

import os
import tempfile
import pytest
from starlette.testclient import TestClient

from analysis.institutional_catalysts import (
    CreditRatingProfile,
    get_institutional_catalysts,
)
from engine.incubation_radar import (
    IncubatedCandidate,
    add_to_incubation,
    evaluate_incubated_pipeline,
    get_incubated_candidate,
    get_incubated_candidates,
    remove_from_incubation,
)
from web.api import app


def test_institutional_catalysts_canonical():
    """Validates that canonical institutional audits return high-fidelity credit & ownership data."""
    trent = get_institutional_catalysts("TRENT")
    assert trent.symbol == "TRENT"
    assert trent.credit_rating is not None
    assert trent.credit_rating.agency == "CRISIL"
    assert "CRISIL AA+" in trent.credit_rating.current_rating
    assert trent.credit_rating.is_upgrade is True
    assert trent.de_pledging_status == "ZERO_PLEDGE_CLEAN"
    assert trent.fii_holding_pct > 20.0
    assert trent.institutional_footprint in ("SMART_MONEY_ACCELERATION", "FII_EXPANSION")
    assert trent.catalyst_score >= 80
    assert any("CRISIL" in b for b in trent.catalyst_badges)

    cgpower = get_institutional_catalysts("CGPOWER")
    assert cgpower.de_pledging_status == "ZERO_PLEDGE_CLEAN"
    assert cgpower.pledge_reduction_1y_pct == 100.0
    assert cgpower.catalyst_score >= 85


def test_institutional_catalysts_dynamic_fallback():
    """Validates dynamic synthesis for symbols not in canonical ledger."""
    rep = get_institutional_catalysts(
        "XYZCORP", promoter_holding=55.0, institutional_holding=30.0, pledged_pct=0.0
    )
    assert rep.symbol == "XYZCORP"
    assert rep.de_pledging_status == "ZERO_PLEDGE_CLEAN"
    assert rep.catalyst_score >= 50


def test_incubation_pipeline_lifecycle():
    """Validates full retention and evaluation lifecycle of the Incubation Pipeline."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        test_db = tf.name

    try:
        # 1. Add candidate in COILING_PIVOT state
        cand = IncubatedCandidate(
            symbol="TESTSTOCK",
            name="Test Stock Ltd",
            sector="Industrials",
            horizon="LONG_TERM",
            cycle_state="COILING_PIVOT",
            eta_days=4,
            eta_label="2–5 Sessions",
            entry_pivot=1500.0,
            current_price=1485.0,
            stop_loss=1430.0,
            target_1=1640.0,
            target_2=1780.0,
            target_moonshot=2200.0,
            risk_reward_ratio=5.1,
            conviction_score=88,
            primary_archetype="STAGE_1_TO_2_EXPANSION",
            catalyst_badges=["🏆 CRISIL Upgraded", "🛡️ Zero Pledge"],
            catalyst_summary="High conviction multibagger setup.",
        )

        saved = add_to_incubation(cand, db_path=test_db)
        assert saved.symbol == "TESTSTOCK"
        assert saved.cycle_state == "COILING_PIVOT"

        # 2. Query candidates by horizon
        long_term_list = get_incubated_candidates(horizon_filter="LONG_TERM", db_path=test_db)
        assert len(long_term_list) == 1
        assert long_term_list[0].symbol == "TESTSTOCK"

        short_term_list = get_incubated_candidates(horizon_filter="SHORT_TERM", db_path=test_db)
        assert len(short_term_list) == 0

        # 3. Simulate breakout: price crosses entry_pivot (1510 >= 1500)
        eval_res = evaluate_incubated_pipeline(
            db_path=test_db, live_quotes={"TESTSTOCK": 1515.0}
        )
        assert "TESTSTOCK" in eval_res["triggered_breakouts"]

        # Verify candidate transitioned to TRIGGER_READY
        updated = get_incubated_candidate("TESTSTOCK", db_path=test_db)
        assert updated is not None
        assert updated.cycle_state == "TRIGGER_READY"
        assert "TODAY" in updated.eta_label

        # 4. Remove candidate
        removed = remove_from_incubation("TESTSTOCK", db_path=test_db)
        assert removed is True
        assert get_incubated_candidate("TESTSTOCK", db_path=test_db) is None

    finally:
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except Exception:
                pass


def test_api_incubation_and_catalysts_endpoints():
    """Validates FastAPI sidecar endpoints for incubation and institutional catalysts."""
    client = TestClient(app)

    # 1. Test Institutional Catalysts
    res = client.post("/skills/institutional_catalysts", json={"symbol": "TRENT"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["symbol"] == "TRENT"
    assert "CRISIL" in data["credit_status"]

    # 2. Test Incubation Add
    add_payload = {
        "symbol": "DIXON",
        "name": "Dixon Tech",
        "sector": "Consumer Electronics",
        "horizon": "MID_TERM",
        "cycle_state": "COILING_PIVOT",
        "eta_days": 3,
        "eta_label": "2–5 Sessions",
        "entry_pivot": 12500.0,
        "current_price": 12350.0,
        "stop_loss": 11900.0,
        "target_1": 13700.0,
        "target_2": 14900.0,
        "target_moonshot": 18000.0,
        "conviction_score": 92,
        "primary_archetype": "VCP_PIVOT_BREAKOUT",
        "catalyst_badges": ["🏆 ICRA AA", "🛡️ Zero Pledge"],
        "catalyst_summary": "Top-tier EMS compounder.",
    }
    res_add = client.post("/skills/incubation_add", json=add_payload)
    assert res_add.status_code == 200
    assert res_add.json()["data"]["symbol"] == "DIXON"

    # 3. Test Incubation Pipeline List
    res_list = client.get("/skills/incubation_pipeline")
    assert res_list.status_code == 200
    items = res_list.json()["data"]["candidates"]
    assert any(x["symbol"] == "DIXON" for x in items)

    # 4. Cleanup
    client.post("/skills/incubation_remove", json={"symbol": "DIXON"})
