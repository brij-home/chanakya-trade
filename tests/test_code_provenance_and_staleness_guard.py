"""
tests/test_code_provenance_and_staleness_guard.py
─────────────────────────────────────────────────
Comprehensive invariant tests for Code Provenance, Build Integrity,
and In-Memory Bytecode Staleness Sentinel.
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from engine.code_provenance import (
    CodeProvenanceReport,
    CodeProvenanceSentinel,
)
from engine.telemetry import (
    EVENT_CODE_STALE,
    derive_priority,
    record_event,
    get_incident_counts,
    get_prioritized_incidents,
    clear_telemetry,
)
from engine.alert_model import AutoAlert


def test_code_provenance_report_dataclass():
    """Verify CodeProvenanceReport fields and serialization."""
    rep = CodeProvenanceReport(
        boot_timestamp="2026-10-23T06:00:00Z",
        uptime_seconds=3600.5,
        pid=1234,
        python_version="3.11.9",
        git_commit="4e18ff1",
        git_branch="main",
        git_dirty=False,
        is_stale_in_memory=False,
        stale_files_count=0,
        stale_files=[],
        staleness_latency_seconds=0.0,
        reload_required=False,
        scanned_roots=["engine", "bot", "web"],
        status="FRESH",
    )
    d = rep.to_dict()
    assert isinstance(d, dict)
    assert d["pid"] == 1234
    assert d["git_commit"] == "4e18ff1"
    assert d["is_stale_in_memory"] is False
    assert d["status"] == "FRESH"


def test_code_provenance_sentinel_fresh_state(tmp_path: Path):
    """Verify sentinel reports FRESH when all files have mtime prior to boot cutoff."""
    sentinel = CodeProvenanceSentinel(
        root_dir=tmp_path,
        boot_time=time.time() + 1000.0,  # Boot time far in the future
        boot_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    # Create mock engine directory with dummy python file
    eng_dir = tmp_path / "engine"
    eng_dir.mkdir()
    py_file = eng_dir / "risk_gate.py"
    py_file.write_text("class RiskGate: pass\n", encoding="utf-8")

    prov = sentinel.get_provenance(force_refresh=True)
    assert prov.is_stale_in_memory is False
    assert prov.status == "FRESH"
    assert prov.stale_files_count == 0
    assert prov.reload_required is False


def test_code_provenance_sentinel_staleness_detection(tmp_path: Path):
    """Verify sentinel accurately flags files modified after boot cutoff."""
    past_boot = time.time() - 500.0
    sentinel = CodeProvenanceSentinel(
        root_dir=tmp_path,
        boot_time=past_boot,
        boot_timestamp=datetime.fromtimestamp(past_boot, tz=timezone.utc).isoformat(),
    )
    # Create mock source tree
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    alert_tmpl = bot_dir / "alert_templates.py"
    alert_tmpl.write_text("# Updated template\n", encoding="utf-8")

    prov = sentinel.get_provenance(force_refresh=True)
    assert prov.is_stale_in_memory is True
    assert prov.status == "STALE"
    assert prov.stale_files_count >= 1
    assert any("alert_templates.py" in f["path"] for f in prov.stale_files)
    assert prov.reload_required is True
    assert prov.staleness_latency_seconds >= 0.0


def test_code_provenance_cache_ttl(tmp_path: Path):
    """Verify sentinel caches reports within CACHE_TTL_SECONDS window."""
    sentinel = CodeProvenanceSentinel(
        root_dir=tmp_path,
        boot_time=time.time() + 1000.0,
    )
    p1 = sentinel.get_provenance()
    time.sleep(0.05)
    p2 = sentinel.get_provenance()
    assert p1 is p2  # Same object reference returned from cache

    p_fresh = sentinel.get_provenance(force_refresh=True)
    assert p_fresh is not p1


def test_telemetry_event_code_stale_priority():
    """Verify EVENT_CODE_STALE maps to P1 institutional incident."""
    clear_telemetry()
    assert (
        derive_priority(
            EVENT_CODE_STALE, "RuntimeCodeProvenance", "WARNING", "Stale in-memory bytecode"
        )
        == "P1"
    )

    record_event(
        event_type=EVENT_CODE_STALE,
        component="RuntimeCodeProvenance",
        action_taken="Reload recommended",
        reason="Stale in-memory bytecode: 3 files modified after boot",
        severity="WARNING",
    )
    counts = get_incident_counts()
    assert counts["P1"] >= 1
    p1s = get_prioritized_incidents(priority="P1")
    assert any("RuntimeCodeProvenance" in inc["component"] for inc in p1s)
    clear_telemetry()


def test_alert_audit_trail_stamps_code_provenance():
    """Verify AutoAlert.record_audit automatically stamps code provenance metadata."""
    alert = AutoAlert(
        alert_id="aa-orb-breakout-nifty-20261023",
        alert_type="ORB_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY Breakout",
        summary="ORB Breakout confirmed",
        ltp=24500.0,
        trigger_level=24480.0,
        target_level=24700.0,
        stop_loss=24400.0,
    )
    evt = alert.record_audit(
        event_type="DISPATCH",
        message="Initial setup broadcast",
        actor="TEST",
    )
    assert "details" in evt
    assert "code_commit" in evt["details"]
    assert "code_boot_ts" in evt["details"]
    assert "code_stale" in evt["details"]
    assert isinstance(evt["details"]["code_stale"], bool)


def test_health_hub_endpoint_includes_code_provenance():
    """Verify /api/system/health-hub returns code_provenance object."""
    from web.api import app

    client = TestClient(app)
    resp = client.get("/api/system/health-hub")
    assert resp.status_code == 200
    data = resp.json()
    assert "code_provenance" in data
    prov = data["code_provenance"]
    assert "boot_timestamp" in prov
    assert "is_stale_in_memory" in prov
    assert "status" in prov
    assert prov["status"] in ("FRESH", "STALE")


def test_health_hub_elevates_to_degraded_when_code_stale():
    """Verify health hub elevates overall_status to DEGRADED when code is stale."""
    from web.api import app

    mock_prov = CodeProvenanceReport(
        boot_timestamp="2026-10-23T06:00:00Z",
        uptime_seconds=5000.0,
        pid=9999,
        python_version="3.11.9",
        git_commit="4e18ff1",
        git_branch="main",
        git_dirty=True,
        is_stale_in_memory=True,
        stale_files_count=2,
        stale_files=[
            {
                "path": "engine/alert_evaluator.py",
                "mtime": time.time(),
                "mtime_iso": "",
                "modified_after_boot_seconds": 120.0,
            }
        ],
        staleness_latency_seconds=120.0,
        reload_required=True,
        scanned_roots=["engine"],
        status="STALE",
    )

    with patch("engine.code_provenance.get_code_provenance", return_value=mock_prov):
        client = TestClient(app)
        resp = client.get("/api/system/health-hub")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] in ("DEGRADED", "CRITICAL")
        assert any(
            inc.get("component") == "RuntimeCodeProvenance" for inc in data.get("incidents", [])
        )


def test_code_provenance_direct_endpoint():
    """Verify /api/system/code-provenance endpoint returns valid provenance payload."""
    from web.api import app

    client = TestClient(app)
    resp = client.get("/api/system/code-provenance")
    assert resp.status_code == 200
    data = resp.json()
    assert "boot_timestamp" in data
    assert "uptime_seconds" in data
    assert "git_commit" in data
    assert "is_stale_in_memory" in data
